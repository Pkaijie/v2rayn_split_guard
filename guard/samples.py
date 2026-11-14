"""Documentation-only network data for UI tests and an isolated preview."""
from .network import inspect_routes


def report_fixture():
    ip='203.0.113.10'
    node=dict(tag='示例代理',host='node.example.invalid',port=34443,protocol='hysteria2',transport='UDP',warning='')
    wlan=dict(connected=True,index=7,ipv4=['10.0.0.2'],ipv6=[],gateway='10.0.0.1',gateway6='fe80::1',alias='WLAN')
    route=dict(prefix=ip+'/32',gateway='10.0.0.1',index=7,alias='WLAN',metric=1,ifmetric=0,store='ActiveStore',protocol=3)
    ipv6=dict(route,prefix='2001:db8::10/128',gateway='fe80::1')
    net=dict(routes=[route,dict(route,store='PersistentStore'),ipv6,dict(ipv6,store='PersistentStore')])
    addresses=[ip,'2001:db8::10']
    return dict(time='2026-11-13 12:00:00 -0800',nodes=[node],node=node,addresses=addresses,
        warnings=[],dns_error='',wlan=wlan,company=True,defaults=[dict(alias='PPPoE')],
        listener=dict(pid=123,address='127.0.0.1',port=10808),faults=[],net=net,
        rows=inspect_routes(addresses,net,wlan,{ip:[route],'2001:db8::10':[ipv6]}))
