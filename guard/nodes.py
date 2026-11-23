from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, asdict
import ipaddress
import json
from pathlib import Path
import re
import tomllib
import json5
import yaml
from .common import DEFAULT_PROXY_PORT, ps_json, quote, array

MAX_BYTES = 8 * 1024 * 1024
YAML_SUFFIXES = {'.yaml', '.yml'}
RUNTIME_SUFFIXES = YAML_SUFFIXES | {'.json', '.json5', '.toml'}
LOOPBACK_BINDS = {'', 'localhost', '127.0.0.1', '::1', '0.0.0.0', '::'}


class RuntimeYamlLoader(yaml.SafeLoader):
    """Bound nested input and mapping-merge expansion while retaining YAML anchors."""

    def __init__(self, stream):
        super().__init__(stream)
        self.depth = 0
        self.nodes_seen = 0
        self.merged_items = 0

    def compose_node(self, parent, index):
        self.depth += 1
        self.nodes_seen += 1
        try:
            if self.depth > 64 or self.nodes_seen > 200_000:
                raise ValueError('YAML structure limit')
            return super().compose_node(parent, index)
        finally:
            self.depth -= 1

    def flatten_mapping(self, node):
        size = len(node.value)
        for key, value in node.value:
            if key.tag != 'tag:yaml.org,2002:merge':
                continue
            sources = value.value if isinstance(value, yaml.SequenceNode) else [value]
            for source in sources:
                if isinstance(source, yaml.MappingNode):
                    self.flatten_mapping(source)
                    size += len(source.value)
                    if size > 8192:
                        raise ValueError('YAML mapping merge limit')
        self.merged_items += size - len(node.value)
        if self.merged_items > 100_000:
            raise ValueError('YAML document merge limit')
        super().flatten_mapping(node)


@dataclass(frozen=True)
class Node:
    tag: str
    host: str
    port: int
    protocol: str
    transport: str
    warning: str = ''

    def to_dict(self):
        return asdict(self)


@dataclass
class RuntimeProfile:
    family: str
    nodes: list[Node]
    warnings: list[str]
    socks_ports: tuple[int, ...]
    choose_node: bool = False


def valid_host(host):
    host = host.strip().strip('[]')
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    host = host.rstrip('.').encode('idna').decode('ascii')
    if len(host) > 253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
        raise ValueError('请输入 IP 或域名，不接受 URL、认证信息或路径')
    return host


def make_node(tag, host, port, proto, transport, warning=''):
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError('节点端口必须在 1–65535 之间')
    if transport not in ('TCP','UDP'):
        raise ValueError('实际传输协议必须为 TCP 或 UDP')
    return Node(str(tag)[:100], valid_host(host), port, str(proto)[:60], transport, warning)


def port_number(value):
    """Accept decimal ports, including strings from YAML, without coercing booleans."""
    if type(value) is int:
        port = value
    elif isinstance(value, str) and re.fullmatch(r'[0-9]{1,5}', value.strip()):
        port = int(value.strip())
    else:
        return None
    return port if 1 <= port <= 65535 else None


def parse_config(data):
    """Whitelist endpoint fields only. Never propagate credentials or raw config."""
    nodes, warnings = [], []
    ignored = {'direct', 'block', 'freedom', 'blackhole', 'dns', 'dns-out', 'loopback', 'selector', 'urltest'}
    known = {'vmess', 'vless', 'trojan', 'shadowsocks', 'shadowsocks2022', 'socks', 'http', 'hysteria', 'naive',
             'hysteria2', 'tuic', 'wireguard', 'anytls', 'ssh', 'shadowtls'}
    for i, o in enumerate(data.get('outbounds', [])):
        if not isinstance(o, dict):
            continue
        proto = str(o.get('type') or o.get('protocol') or '').lower()
        tag = str(o.get('tag') or f'出站 {i+1}')
        if proto in ignored:
            if proto in {'selector', 'urltest'}:
                warnings.append(f'{tag} 为动态选择器，请确认实际选中的叶子节点')
            continue
        settings = o['settings'] if isinstance(o.get('settings'), dict) else {}
        stream = o['streamSettings'] if isinstance(o.get('streamSettings'), dict) else {}
        sockopt = stream['sockopt'] if isinstance(stream.get('sockopt'), dict) else {}
        chain = bool(o.get('detour') or o.get('proxySettings') or
                     sockopt.get('dialerProxy'))
        uncertain = chain or proto not in known or proto in {'wireguard', 'shadowtls'}
        warning = '链式代理或自定义出站：请手动确认实际首先连接的服务器及端口' if uncertain else ''
        network = str(stream.get('network') or stream.get('transport') or '').lower()
        transport = 'UDP' if proto in {'hysteria', 'hysteria2', 'tuic', 'wireguard'} or network in {'quic', 'kcp', 'hysteria', 'hysteria2'} else 'TCP'
        hysteria = stream.get('hysteriaSettings')
        hy2 = settings.get('version') == 2 or (isinstance(hysteria, dict) and hysteria.get('version') == 2)
        display_proto = 'hysteria2' if proto == 'hysteria' and hy2 else proto
        endpoints = []
        if o.get('server') and o.get('server_port'):
            endpoints.append((o['server'], o['server_port']))
        if settings.get('address') and settings.get('port'):
            endpoints.append((settings['address'], settings['port']))
        for key in ('servers', 'vnext'):
            entries = settings.get(key)
            for s in entries if isinstance(entries, list) else ():
                if isinstance(s, dict) and s.get('address') and s.get('port'):
                    endpoints.append((s['address'], s['port']))
        if not endpoints:
            warnings.append(f'{tag} ({proto}) 无法识别端点，需要手动确认')
        if o.get('server_ports') or (settings.get('ports')):
            warning = '端口跳跃配置：请手动确认当前实际端口；本次端口证据可能不完整'
        endpoints = list(dict.fromkeys((host, port_number(port)) for host, port in endpoints if isinstance(host, str)))
        for j, (host, port) in enumerate(endpoints):
            try:
                nodes.append(make_node(tag + (f' #{j+1}' if len(endpoints)>1 else ''), host, port, display_proto, transport, warning))
            except (ValueError, TypeError, UnicodeError):
                warnings.append(f'{tag} 端点格式无法识别，需要手动输入')
    return nodes, warnings


def load_runtime_document(path):
    p = Path(path)
    with p.open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('运行配置超过大小限制')
    try:
        text = raw.decode('utf-8-sig')
        suffix = p.suffix.lower()
        if suffix in YAML_SUFFIXES:
            data = yaml.load(text, Loader=RuntimeYamlLoader)
        elif suffix == '.toml':
            data = tomllib.loads(text)
        elif suffix == '.json5':
            data = json5.loads(text, allow_duplicate_keys=False)
        else:
            data = json.loads(text)
    except (ValueError, yaml.YAMLError, RecursionError, OverflowError, TypeError, AttributeError):
        # Parsing errors can contain source lines with credentials.
        raise ValueError('无法解析运行配置，请核对文件格式与内容') from None
    if not isinstance(data, dict):
        raise ValueError('运行配置需要是键值映射')
    return data


def runtime_family(data):
    from .standalone import standalone_family
    family = standalone_family(data)
    if family:
        return family
    if isinstance(data.get('outbounds'), list):
        return 'outbounds'
    if (isinstance(data.get('proxies'), list) or isinstance(data.get('proxy-groups'), list)
            or isinstance(data.get('proxy-providers'), dict)):
        return 'clash'
    return ''


def runtime_socks_ports(data, family):
    if family == 'clash':
        ports = (port_number(data.get(key)) for key in ('mixed-port', 'socks-port'))
        return tuple(dict.fromkeys(port for port in ports if port is not None))
    inbounds = data.get('inbounds')
    if not isinstance(inbounds, list):
        return (DEFAULT_PROXY_PORT,)
    ports = []
    for kind in ('mixed', 'socks', 'socks5'):
        for item in inbounds:
            if not isinstance(item, dict) or (item.get('protocol') or item.get('type')) != kind:
                continue
            address = item.get('listen', '')
            if isinstance(address, str) and address.strip('[]').lower() in LOOPBACK_BINDS:
                port = port_number(item.get('listen_port', item.get('port')))
                if port and port not in ports:
                    ports.append(port)
    return tuple(ports)


def parse_clash_config(data):
    """Extract concrete endpoints only. A proxy group has no fixed server address."""
    proxies = data.get('proxies')
    entries = list(proxies) if isinstance(proxies, list) else []
    if len(entries) > 8192:
        raise ValueError('Clash / Mihomo 节点列表超过解析限制')
    providers = data.get('proxy-providers')
    warnings = []
    if isinstance(providers, dict):
        for provider in providers.values():
            if isinstance(provider, dict) and provider.get('type') == 'inline' and isinstance(provider.get('payload'), list):
                if not any(provider.get(key) for key in ('override', 'filter', 'exclude-filter', 'exclude-type')):
                    if len(entries) + len(provider['payload']) > 8192:
                        raise ValueError('Clash / Mihomo 节点列表超过解析限制')
                    entries.extend(provider['payload'])
                    continue
            message = '外部或带过滤/覆盖的节点提供者需在代理客户端确认，必要时手动输入节点。'
            if message not in warnings:
                warnings.append(message)

    nodes = []
    invalid = 0
    udp_protocols = {'hysteria', 'hysteria2', 'tuic', 'wireguard', 'shadowquic', 'masque'}
    direct_types = {'direct', 'reject', 'reject-drop', 'pass', 'dns', 'compatible', 'block', 'rematch'}
    for entry in entries:
        if not isinstance(entry, dict):
            invalid += 1
            continue
        kind, name, host = (entry.get(key) for key in ('type', 'name', 'server'))
        kind = kind.strip().lower() if isinstance(kind, str) else ''
        if kind in direct_types:
            continue
        port = port_number(entry.get('port'))
        if not kind or not isinstance(name, str) or not name.strip() or not isinstance(host, str) or port is None:
            invalid += 1
            continue
        warning = ''
        if entry.get('dialer-proxy'):
            warning = '此节点使用链式代理，请核对真正的第一跳并选择该节点。'
        elif entry.get('ports'):
            warning = '此节点启用了端口跳跃，请核对实际连接端口。'
        elif kind in {'wireguard', 'tailscale', 'zerotier'} or entry.get('realm-opts'):
            warning = '此节点可能使用其他端点，请在代理客户端确认实际第一跳。'
        # The Clash udp option enables forwarding UDP, not necessarily an outer UDP link.
        network = entry.get('network')
        transport = 'UDP' if kind in udp_protocols or network in ('quic', 'kcp') else 'TCP'
        try:
            nodes.append(make_node(name.strip(), host, port, kind, transport, warning))
        except (ValueError, UnicodeError):
            invalid += 1
    counts = Counter(node.tag for node in nodes)
    duplicates = any(count > 1 for count in counts.values())
    if duplicates:
        warnings.append('已跳过同名节点，请在代理客户端核对，或手动输入节点。')
        nodes = [node for node in nodes if counts[node.tag] == 1]
    if invalid:
        warnings.append(f'有 {invalid} 条代理记录的地址、端口或格式无法识别。')
    choose_node = (len(nodes) > 1 or duplicates or invalid > 0 or bool(data.get('proxy-groups') or providers)
                   or any(node.warning for node in nodes))
    if choose_node and nodes:
        warnings.append('请在代理客户端确认实际使用的第一跳，再选择相同节点。')
    return nodes, warnings, choose_node


def document_profile(data):
    family = runtime_family(data)
    if family == 'clash':
        nodes, warnings, choose_node = parse_clash_config(data)
    elif family == 'outbounds':
        nodes, warnings = parse_config(data)
        choose_node = False
    elif family:
        from .standalone import parse_standalone
        return parse_standalone(data, family)
    else:
        raise ValueError('未识别运行配置结构')
    return RuntimeProfile(family, nodes, warnings, runtime_socks_ports(data, family), choose_node)


def read_runtime(path):
    from .standalone import brook_pid, read_brook
    pid = brook_pid(path)
    return read_brook(pid) if pid else document_profile(load_runtime_document(path))


def read_nodes(path):
    profile = read_runtime(path)
    return profile.nodes, profile.warnings


def resolve(host, stop=None):
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    # DNS Client query has an outer subprocess timeout; query both A and AAAA.
    result = ps_json(f"$r=@(); foreach($t in @('A','AAAA')) {{ $r+=@(Resolve-DnsName -Name {quote(valid_host(host))} -Type $t -DnsOnly -QuickTimeout -ErrorAction SilentlyContinue | Where-Object {{$_.IPAddress}} | Select-Object -ExpandProperty IPAddress) }}; ConvertTo-Json -InputObject @($r)", 12, stop)
    addresses = sorted({str(ipaddress.ip_address(x)) for x in array(result)})
    if not addresses:
        raise ValueError('DNS 没有返回 A/AAAA 地址，无法检查节点路由')
    return addresses
