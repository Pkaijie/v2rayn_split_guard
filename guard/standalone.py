"""Project standalone client settings onto node and loopback listener fields."""
import ipaddress
from collections import Counter
import re
from urllib.parse import parse_qs, urlsplit

import psutil

from .nodes import LOOPBACK_BINDS, RuntimeProfile, make_node, port_number, valid_host


CORE_LABELS = {
    'hysteria2': 'Hysteria 2', 'hysteria': 'Hysteria', 'naiveproxy': 'NaiveProxy',
    'tuic': 'TUIC', 'juicity': 'Juicity', 'overtls': 'OverTLS',
    'shadowquic': 'ShadowQUIC', 'brook': 'Brook',
}
FIRST_HOP = '配置可能使用其他第一跳，请在客户端核对后手动填写节点。'
PORT_HOP = '配置启用了端口跳跃，显示的是配置中的一个端口。'
SOCKS_SCHEMES = {'socks', 'socks5', 'socks5h', 'mixed'}
SHADOW_TYPES = {'shadowquic', 'sunnyquic'}


def mapping(value):
    return value if isinstance(value, dict) else {}


def objects(data, plural, singular):
    entries = data.get(plural)
    if isinstance(entries, list):
        return [entry for entry in entries if isinstance(entry, dict)]
    entry = data.get(singular)
    return [entry] if isinstance(entry, dict) else []


def standalone_family(data):
    if isinstance(data.get('client_settings'), dict) and 'server_host' in data['client_settings']:
        return 'overtls'
    if (any(item.get('type') in ('shadowquic', 'sunnyquic') or 'addr' in item
            for item in objects(data, 'outbounds', 'outbound'))
            or any('bind-addr' in item for item in objects(data, 'inbounds', 'inbound'))):
        return 'shadowquic'
    server = data.get('server')
    if isinstance(data.get('relay'), dict) or (isinstance(server, str) and isinstance(data.get('local'), dict)):
        return 'tuic'
    if isinstance(server, str) and (isinstance(data.get('listen'), str) or 'uuid' in data):
        return 'juicity'
    if isinstance(server, str) and (
            server.startswith(('hysteria2://', 'hy2://', 'realm://', 'hysteria2+realm'))
            or any(key in data for key in ('auth', 'socks5', 'http', 'tun', 'tcpForwarding', 'udpForwarding'))):
        if 'up_mbps' in data or 'down_mbps' in data or 'protocol' in data:
            return 'hysteria'
        return 'hysteria2'
    if isinstance(data.get('proxy'), (str, list)) and isinstance(data.get('listen'), (str, list)):
        return 'naiveproxy'
    return ''


def split_address(value, default=None):
    """Split an address without resolving it or treating its text as a URL."""
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError('地址无效')
    if value.startswith('['):
        host, close, suffix = value[1:].partition(']')
        if not close or (suffix and not suffix.startswith(':')):
            raise ValueError('IPv6 地址格式无效')
        return host, suffix[1:] if suffix else default
    if value.count(':') > 1:
        if default is not None and ipaddress.ip_address(value).version == 6:
            return value, default
        raise ValueError('带端口的 IPv6 地址需要方括号')
    host, sep, port = value.partition(':')
    return host, port if sep else default


def uri_address(value, schemes, defaults=None):
    if not isinstance(value, str) or len(value) > 32768:
        raise ValueError('代理地址无效')
    uri = urlsplit(value)
    if uri.scheme not in schemes or not uri.netloc:
        raise ValueError('代理地址格式无效')
    host, port = split_address(uri.netloc.rsplit('@', 1)[-1], (defaults or {}).get(uri.scheme))
    return uri, host, port


def listen_ports(value, *, uri_only=False):
    values = value if isinstance(value, list) else [value]
    ports = []
    for address in values:
        if not isinstance(address, str):
            continue
        try:
            if '://' in address:
                _, host, raw_port = uri_address(address, SOCKS_SCHEMES)
            elif not uri_only:
                host, raw_port = split_address(address)
            else:
                continue
            port = port_number(raw_port)
            if host.lower() in LOOPBACK_BINDS and port and port not in ports:
                ports.append(port)
        except ValueError:
            continue
    return tuple(ports)


def endpoint(tag, host, value, protocol, transport, warning=''):
    port = port_number(value)
    if not isinstance(host, str) or not port:
        raise ValueError('节点地址或端口无效')
    return make_node(tag, host, port, protocol, transport, warning)


def hysteria_node(value, family):
    if value.startswith(('realm://', 'hysteria2+realm')):
        return None, FIRST_HOP
    if '://' in value:
        uri, host, port = uri_address(value, {'hysteria2', 'hy2'}, {'hysteria2': 443, 'hy2': 443})
        hopping = bool(parse_qs(uri.query, max_num_fields=128).get('mport'))
    else:
        host, port = split_address(value, 443 if family == 'hysteria2' else None)
        hopping = False
    if isinstance(port, str) and re.fullmatch(r'[0-9]{1,5}(?:[-,][0-9]{1,5})+', port):
        pieces = re.split(r'[-,]', port)
        if not all(port_number(piece) for piece in pieces):
            raise ValueError('端口范围无效')
        port, hopping = pieces[0], True
    return endpoint(CORE_LABELS[family], host, port, family, 'UDP', PORT_HOP if hopping else ''), ''


def naive_node(data):
    upstream = data.get('proxy')
    if not isinstance(upstream, str) or ',' in upstream or data.get('host-resolver-rules'):
        return None, FIRST_HOP
    uri, host, port = uri_address(upstream, {'https', 'quic'}, {'https': 443, 'quic': 443})
    return endpoint('NaiveProxy', host, port, 'naiveproxy', 'UDP' if uri.scheme == 'quic' else 'TCP'), ''


def shadow_profile(data):
    inbounds = objects(data, 'inbounds', 'inbound')
    ports = listen_ports([item.get('bind-addr') for item in inbounds if item.get('type') in ('socks', 'mixed')])
    outbounds = objects(data, 'outbounds', 'outbound')
    router = mapping(data.get('router'))
    if router.get('src') or router.get('path'):
        return RuntimeProfile('shadowquic', [], [FIRST_HOP], ports)
    nodes = []
    for item in outbounds:
        kind = item.get('type')
        if kind not in ('shadowquic', 'sunnyquic', 'socks'):
            continue
        tag = item.get('tag') or 'ShadowQUIC'
        hop = mapping(item.get('port-hopping')).get('enable')
        try:
            host, port = split_address(item.get('addr'))
            nodes.append(endpoint(tag, host, port, kind, 'UDP' if kind in SHADOW_TYPES else 'TCP', PORT_HOP if hop else ''))
        except (ValueError, UnicodeError):
            continue
    tags = Counter(node.tag for node in nodes)
    nodes = [node for node in nodes if tags[node.tag] == 1]
    default = router.get('default-outbound')
    choose = len(outbounds) > 1 or bool(default and (not isinstance(default, str) or default not in tags))
    warnings = ['请在客户端确认当前使用的 ShadowQUIC 出站。'] if choose else []
    if not nodes:
        warnings.append('未识别 ShadowQUIC 远端地址，请手动核对节点。')
    return RuntimeProfile('shadowquic', nodes, warnings, ports, choose)


def parse_standalone(data, family):
    if family == 'shadowquic':
        return shadow_profile(data)
    tag = CORE_LABELS[family]
    ports, node, warning = (), None, ''
    try:
        if family in ('hysteria2', 'hysteria'):
            ports = listen_ports(mapping(data.get('socks5')).get('listen'))
            node, warning = hysteria_node(data['server'], family)
        elif family == 'naiveproxy':
            ports = listen_ports(data['listen'], uri_only=True)
            node, warning = naive_node(data)
        elif family == 'tuic':
            ports = listen_ports(mapping(data.get('local')).get('server', '127.0.0.1:1080'))
            relay = mapping(data.get('relay')) if 'relay' in data else data
            if relay.get('proxy') or relay.get('forwarder_server'):
                warning = FIRST_HOP
            else:
                host, port = split_address(relay.get('server'))
                if relay.get('ip'):
                    pinned = relay['ip']
                    if not isinstance(pinned, str):
                        raise ValueError('TUIC 指定的 IP 无效')
                    host = str(ipaddress.ip_address(pinned))
                node = endpoint(tag, host, port, family, 'UDP')
        elif family == 'juicity':
            ports = listen_ports(data.get('listen'))
            host, port = split_address(data['server'])
            node = endpoint(tag, host, port, family, 'UDP')
        elif family == 'overtls':
            client = data['client_settings']
            ports = listen_ports(client.get('listen'))
            if 'listen' not in client and client.get('listen_host', '') in LOOPBACK_BINDS:
                legacy_port = port_number(client.get('listen_port'))
                ports = (legacy_port,) if legacy_port else ()
            node = endpoint(tag, client['server_host'], client.get('server_port'), family, 'TCP')
    except (ValueError, TypeError, UnicodeError):
        warning = '未识别 ' + tag + ' 远端地址，请核对配置或手动填写节点。'
    return RuntimeProfile(family, [node] if node else [], [warning] if warning else [], ports)


def is_brook(name):
    return re.fullmatch(r'brook(?:_windows_(?:amd64|arm64|386))?\.exe', name) is not None


def brook_pid(value):
    ref = re.fullmatch(r'@brook:([1-9][0-9]{0,9})', str(value))
    return int(ref[1]) if ref and int(ref[1]) <= 0xFFFFFFFF else None


def brook_options(arguments):
    commands = {'client', 'wsclient', 'wssclient', 'quicclient', 'connect'}
    aliases = {'-s': 'server', '-l': 'link', '-d': 'dial'}
    options = {}
    command = ''
    ignored_values = {'password', 'p', 'ca', 'script', 'log', 'pid', 'cliToken', 'socks5ServerIP',
                      'http', 'username', 'tcpTimeout', 'udpTimeout'}
    values = {'server', 'wsserver', 'wssserver', 'quicserver', 'dial', 'address', 'link', 'socks5'} | ignored_values
    argv = iter(arguments[1:])
    for token in argv:
        if not token.startswith('-'):
            if not command and token in commands:
                command = token
                continue
            break
        flag, eq, value = token.partition('=')
        flag = aliases.get(flag, flag.lstrip('-'))
        if flag in values:
            value = value if eq else next(argv, '')
            if flag not in ignored_values:
                options[flag] = value
        elif flag == 'help':
            return '', {}
    return command, options


def brook_node(command, options):
    kind = {'client': 'server', 'wsclient': 'wsserver', 'wssclient': 'wssserver',
            'quicclient': 'quicserver'}.get(command)
    upstream = options.get(kind) or options.get('server')
    address = options.get('address')
    if options.get('link'):
        uri = urlsplit(options['link'])
        kind = uri.netloc
        if uri.scheme != 'brook' or kind not in ('server', 'wsserver', 'wssserver', 'quicserver', 'socks5'):
            raise ValueError('Brook 链接类型无法识别')
        params = parse_qs(uri.query, max_num_fields=128)
        upstream = params.get(kind, [''])[0]
        address = params.get('address', [''])[0]
    schemes = {'wsserver': 'ws', 'wssserver': 'wss', 'quicserver': 'quic', 'socks5': 'socks5'}
    if kind in schemes:
        _, host, port = uri_address(upstream, {schemes[kind]})
        if address:
            host, port = split_address(address)
    else:
        host, port = split_address(upstream)
    return endpoint('Brook', host, port, 'brook', 'UDP' if kind == 'quicserver' else 'TCP')


def brook_profile(arguments):
    command, options = brook_options(arguments)
    if not command:
        return None
    ports = listen_ports(options.get('socks5', '127.0.0.1:1080'))
    if options.get('dial'):
        return RuntimeProfile('brook', [], [FIRST_HOP], ports)
    try:
        node = brook_node(command, options)
    except (ValueError, UnicodeError):
        return RuntimeProfile('brook', [], ['未识别 Brook 第一跳，请手动填写节点。'], ports)
    return RuntimeProfile('brook', [node], [], ports)


def read_brook(pid):
    try:
        process = psutil.Process(pid)
        if is_brook(process.name().lower()):
            profile = brook_profile(process.cmdline())
            if profile:
                return profile
    except (psutil.Error, OSError):
        pass
    raise ValueError('Brook 进程已退出或不可读取，请在高级设置重新检测') from None
