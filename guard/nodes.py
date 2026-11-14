from __future__ import annotations
from dataclasses import dataclass, asdict
import ipaddress
import json
from pathlib import Path
import re
from .common import ps_json, quote, array


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


def parse_config(data):
    """Whitelist endpoint fields only. Never propagate credentials or raw config."""
    nodes, warnings = [], []
    ignored = {'direct', 'block', 'freedom', 'blackhole', 'dns', 'dns-out', 'selector', 'urltest'}
    known = {'vmess', 'vless', 'trojan', 'shadowsocks', 'socks', 'http', 'hysteria',
             'hysteria2', 'tuic', 'wireguard', 'anytls', 'ssh', 'shadowtls'}
    for i, o in enumerate(data.get('outbounds', [])):
        proto = str(o.get('type') or o.get('protocol') or '').lower()
        tag = str(o.get('tag') or f'出站 {i+1}')
        if proto in ignored:
            if proto in {'selector', 'urltest'}:
                warnings.append(f'{tag} 为动态选择器，请确认实际选中的叶子节点')
            continue
        settings = o.get('settings') or {}
        stream = o.get('streamSettings') or {}
        chain = bool(o.get('detour') or o.get('proxySettings') or
                     (stream.get('sockopt') or {}).get('dialerProxy'))
        uncertain = chain or proto not in known or proto in {'wireguard', 'shadowtls'}
        warning = '链式代理或自定义出站：请手动确认实际首先连接的服务器及端口' if uncertain else ''
        transport = 'UDP' if proto in {'hysteria', 'hysteria2', 'tuic', 'wireguard'} or str(stream.get('network', '')).lower() in {'quic', 'kcp', 'hysteria'} else 'TCP'
        display_proto = 'hysteria2' if proto=='hysteria' and (settings.get('version')==2 or (stream.get('hysteriaSettings') or {}).get('version')==2) else proto
        endpoints = []
        if o.get('server') and o.get('server_port'):
            endpoints.append((o['server'], o['server_port']))
        if settings.get('address') and settings.get('port'):
            endpoints.append((settings['address'], settings['port']))
        for key in ('servers', 'vnext'):
            for s in settings.get(key, []):
                if s.get('address') and s.get('port'):
                    endpoints.append((s['address'], s['port']))
        if not endpoints:
            warnings.append(f'{tag} ({proto}) 无法识别端点，需要手动确认')
        if o.get('server_ports') or (settings.get('ports')):
            warning = '端口跳跃配置：请手动确认当前实际端口；本次端口证据可能不完整'
        for j, (host, port) in enumerate(dict.fromkeys(endpoints)):
            try:
                nodes.append(make_node(tag + (f' #{j+1}' if len(endpoints)>1 else ''), host, port, display_proto, transport, warning))
            except (ValueError, TypeError, UnicodeError):
                warnings.append(f'{tag} 端点格式无法识别，需要手动输入')
    return nodes, warnings


def read_nodes(path):
    p = Path(path)
    if p.stat().st_size > 8*1024*1024:
        raise ValueError('运行配置超过大小限制')
    # Parse errors must not expose the source line (which might contain secrets).
    try:
        d = json.loads(p.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError):
        raise ValueError('运行配置不是可识别的 JSON，请手动确认节点') from None
    return parse_config(d)


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
