from __future__ import annotations
import ipaddress
import json
from .common import ps_json, quote, array, timestamp, run,stage,OperationCancelled
from .nodes import read_nodes, resolve, make_node

ROUTE_FIELDS = 'DestinationPrefix,InterfaceIndex,InterfaceAlias,NextHop,RouteMetric,InterfaceMetric,Protocol'


def route_key(r):
    return (r['prefix'], int(r['index']), r['gateway'], int(r['metric']), r['store'])


def normalize_route(r, store):
    return dict(prefix=r['DestinationPrefix'], index=int(r['InterfaceIndex']),
                alias=r.get('InterfaceAlias', ''), gateway=r['NextHop'],
                metric=int(r['RouteMetric']), ifmetric=int(r.get('InterfaceMetric') or 0), store=store,
                protocol=int(r.get('Protocol') or 3))


def selection_script(addresses):
    targets=','.join(quote(str(ipaddress.ip_address(x))) for x in addresses)
    return f"$r=@{{}}; foreach($ip in @({targets})) {{ try {{ $r[$ip]=@(Find-NetRoute -RemoteIPAddress $ip | Where-Object {{$null -ne $_.DestinationPrefix}} | Select-Object {ROUTE_FIELDS}) }} catch {{$r[$ip]=@()}} }};"


def snapshot(stop=None,*,addresses=None):
    script = """
    $ifs=@(Get-NetIPInterface | Select-Object InterfaceAlias,InterfaceIndex,AddressFamily,ConnectionState,InterfaceMetric);
    $ips=@(Get-NetIPAddress | Select-Object InterfaceIndex,IPAddress,PrefixLength,AddressState);
    $a=@(Get-NetRoute -PolicyStore ActiveStore | Select-Object ROUTE_FIELDS);
    $p=@(Get-NetRoute -PolicyStore PersistentStore | Select-Object ROUTE_FIELDS);
    SELECTION
    @{interfaces=$ifs;addresses=$ips;active=$a;persistent=$p;SELECTED} | ConvertTo-Json -Depth 6 -Compress
    """.replace('ROUTE_FIELDS', ROUTE_FIELDS)
    script=script.replace('SELECTION',selection_script(addresses) if addresses is not None else '').replace('SELECTED','selected=$r' if addresses is not None else '')
    d = ps_json(script, 25, stop)
    d['routes'] = [normalize_route(r, s) for k,s in [('active','ActiveStore'),('persistent','PersistentStore')] for r in array(d[k])]
    if addresses is not None:d['selected']={ip:[normalize_route(r,'ActiveStore') for r in array((d.get('selected') or {}).get(ip))] for ip in addresses}
    return d


def read_routes(prefixes=None,stop=None):
    """Fresh reads of both stores, without unrelated interface/adapter queries."""
    filters=''
    if prefixes is not None:
        targets=','.join(quote(str(ipaddress.ip_network(p,strict=True))) for p in sorted(prefixes))
        if not targets:return []
        filters=f' | Where-Object {{$_.DestinationPrefix -in @({targets})}}'
    script=';'.join(f'${key}=@(Get-NetRoute -PolicyStore {store}{filters} | Select-Object {ROUTE_FIELDS})'
                    for key,store in [('a','ActiveStore'),('p','PersistentStore')])
    d=ps_json(script+'; @{active=$a;persistent=$p} | ConvertTo-Json -Depth 5 -Compress',25,stop)
    return [normalize_route(r,s) for key,s in [('active','ActiveStore'),('persistent','PersistentStore')] for r in array(d[key])]


def wlan_info(net, alias):
    items = [x for x in array(net['interfaces']) if x['InterfaceAlias']==alias]
    indexes = {int(x['InterfaceIndex']) for x in items}
    if len(indexes) != 1:
        return dict(connected=False, index=None, ipv4=[], ipv6=[], gateway='', gateway6='', alias=alias)
    idx = indexes.pop()
    ips = [x['IPAddress'] for x in array(net['addresses']) if int(x['InterfaceIndex'])==idx and int(x['AddressState'])==4]
    defaults = [r for r in net['routes'] if r['store']=='ActiveStore' and r['index']==idx and r['prefix'] in ('0.0.0.0/0','::/0')]
    defaults.sort(key=lambda r:r['metric']+r['ifmetric'])
    def gw(prefix):
        return next((r['gateway'] for r in defaults if r['prefix']==prefix and r['gateway'] not in ('0.0.0.0','::')), '')
    return dict(connected=any(int(x['ConnectionState'])==1 for x in items), index=idx,
                ipv4=[x for x in ips if ':' not in x], ipv6=[x for x in ips if ':' in x],
                gateway=gw('0.0.0.0/0'), gateway6=gw('::/0'), alias=alias)


def selected_routes(addresses, stop=None):
    targets = ','.join(quote(str(ipaddress.ip_address(x))) for x in addresses)
    if not targets:
        return {}
    d = ps_json(selection_script(addresses)+' $r | ConvertTo-Json -Depth 5 -Compress', 20, stop)
    return {ip: [normalize_route(r, 'ActiveStore') for r in array(d.get(ip))] for ip in addresses}


def proxy_listener():
    import psutil
    for c in psutil.net_connections(kind='tcp'):
        if c.status=='LISTEN' and c.laddr.port==10808 and c.laddr.ip in ('127.0.0.1','0.0.0.0','::'):
            return dict(pid=c.pid, address=c.laddr.ip, port=10808)
    return None


def inspect_routes(addresses, net, wlan, selected):
    rows = []
    for ip in addresses:
        v6 = ':' in ip
        prefix = f'{ip}/{128 if v6 else 32}'
        exact = [r for r in net['routes'] if r['prefix']==prefix]
        chosen = selected.get(ip, [])
        gw = wlan['gateway6' if v6 else 'gateway']
        via = bool(chosen) and all(r['index']==wlan['index'] for r in chosen)
        good_gw = bool(gw) and bool(exact) and all(r['gateway']==gw and r['index']==wlan['index'] for r in exact)
        active = any(r['store']=='ActiveStore' for r in exact)
        persistent = any(r['store']=='PersistentStore' for r in exact)
        rows.append(dict(ip=ip, prefix=prefix, chosen=chosen, exact=exact, via_wlan=via,
                         gateway_match=good_gw, active=active, persistent=persistent,
                         ok=via and good_gw and active and persistent))
    return rows


def check(config, stop=None, progress=None):
    warnings = []
    try:
        nodes, warnings = stage('读取当前节点',lambda:read_nodes(config['runtime']),stop,progress)
    except OperationCancelled:raise
    except (OSError, ValueError, TypeError):
        nodes = []
        warnings.append('无法读取运行配置，请检查路径或手动输入节点')
    if config['manual']:
        node = make_node('手动', config['host'], config['port'], config['protocol'], config['transport'])
    else:
        node = next((n for n in nodes if n.tag==config.get('tag')), nodes[0] if nodes else None)
    addresses, dns_error = [], ''
    if node:
        try:
            addresses = stage('解析节点 A / AAAA 地址',lambda:resolve(node.host, stop),stop,progress)
        except OperationCancelled:raise
        except (ValueError, RuntimeError, TimeoutError) as e:
            dns_error = str(e)
    net = stage('读取 WLAN、网关、路由存储和系统选路',lambda:snapshot(stop,addresses=addresses),stop,progress)
    wlan = wlan_info(net, config['wlan'])
    company = any(x['InterfaceAlias']==config['company'] and int(x['ConnectionState'])==1 for x in array(net['interfaces']))
    defaults = [r for r in net['routes'] if r['store']=='ActiveStore' and r['prefix']=='0.0.0.0/0']
    defaults.sort(key=lambda r:r['metric']+r['ifmetric'])
    selected=net['selected'] if 'selected' in net else stage('检查 IPv4 / IPv6 系统选路',lambda:selected_routes(addresses,stop),stop,progress)
    rows = inspect_routes(addresses, net, wlan, selected)
    listener = stage('检查本地代理监听',proxy_listener,stop,progress)
    faults = []
    if not wlan['connected']:
        faults.append('WLAN 已断开')
    elif not wlan['gateway']:
        faults.append('WLAN IPv4 网关缺失')
    if not node:
        faults.append('未识别代理节点，请手动确认')
    if dns_error:
        faults.append('节点域名解析失败')
    if not listener:
        faults.append('127.0.0.1:10808 代理监听不存在')
    for row in rows:
        if not row['via_wlan']:
            faults.append('节点选路未经过 WLAN：'+row['ip'])
        elif not row['gateway_match']:
            faults.append('节点专用路由缺失或网关不匹配：'+row['ip'])
    return dict(time=timestamp(), nodes=[n.to_dict() for n in nodes], node=node.to_dict() if node else None,
                warnings=warnings, addresses=addresses, dns_error=dns_error, net=net, wlan=wlan,
                company=company, defaults=defaults, rows=rows, listener=listener, faults=faults)


def test_proxy(stop=None):
    # socks5h lets the proxy resolve HTTPS destination; curl enforces total timeout.
    try:
        raw = run(['curl.exe', '-q', '--silent', '--show-error', '--fail', '--proxy',
                   'socks5h://127.0.0.1:10808', '--noproxy', '', '--connect-timeout','5',
                   '--max-time','12', '--max-filesize','4096', 'https://api.ipify.org?format=json'], 15, stop)
        ip = str(ipaddress.ip_address(json.loads(raw)['ip']))
        return dict(ok=True, ip=ip, time=timestamp(), message='HTTPS 请求成功；出口公网 IP：'+ip)
    except Exception as e:
        return dict(ok=False, ip='', time=timestamp(), message='代理测试失败：'+str(e)[:500])
