import copy
import ipaddress
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from guard.nodes import parse_config,make_node,valid_host
from guard.network import inspect_routes,route_key,wlan_info,check
from guard.routes import plan_routes,execute,restore_plan,validate_route,identity


def route(ip='203.0.113.10',gw='10.0.0.1',idx=7,store='ActiveStore',metric=1):
    return dict(prefix=ip+('/128' if ':' in ip else '/32'),gateway=gw,index=idx,
                alias='WLAN' if idx==7 else 'PPPoE',metric=metric,ifmetric=0,store=store)


def report(routes=None,ips=None,gw='10.0.0.1'):
    return dict(node=dict(tag='proxy',host='node.example',port=34443,protocol='hysteria',transport='UDP',warning=''),
                addresses=ips or ['203.0.113.10'],net=dict(routes=routes or []),
                wlan=dict(index=7,connected=True,ipv4=['10.0.0.2'],ipv6=[],gateway=gw,gateway6='',alias='WLAN'))


class FakeBackend:
    def __init__(self,rows,fail=False,mirror=False):
        self.rows=copy.deepcopy(rows);self.fail=fail;self.mirror=mirror;self.mutations=[]
    def read(self):return copy.deepcopy(self.rows)
    def add(self,r):
        if route_key(r) in {route_key(x) for x in self.rows}:return
        if self.fail:
            self.fail=False;raise RuntimeError('模拟权限不足')
        self.rows.append(copy.deepcopy(r));self.mutations.append(('add',route_key(r)))
        if self.mirror and r['store']=='PersistentStore':
            a=dict(r,store='ActiveStore');self.add(a)
    def remove(self,r):
        self.rows=[x for x in self.rows if route_key(x)!=route_key(r)]
        self.mutations.append(('remove',route_key(r)))
        if self.mirror and r['store']=='PersistentStore':
            self.rows=[x for x in self.rows if not (identity(x)==identity(r) and x['store']=='ActiveStore')]


class NodesTests(unittest.TestCase):
    def test_live_hysteria_shape(self):
        n,w=parse_config({'outbounds':[{'tag':'proxy','protocol':'hysteria','settings':{'address':'a.example','port':34443},'streamSettings':{'hysteriaSettings':{'auth':'DO_NOT_LEAK'}}}]})
        self.assertEqual((n[0].port,n[0].transport),(34443,'UDP'));self.assertNotIn('DO_NOT_LEAK',str(n))
    def test_ignore_direct_block_selectors(self):
        n,w=parse_config({'outbounds':[{'type':t,'server':'x.example','server_port':1} for t in ['direct','block','dns','selector','urltest']]})
        self.assertFalse(n);self.assertEqual(len(w),2)
    def test_sing_box_multi(self):
        n,w=parse_config({'outbounds':[{'type':'hysteria2','tag':'a','server':'a.example','server_port':1234},{'type':'trojan','tag':'b','server':'b.example','server_port':443}]})
        self.assertEqual([x.transport for x in n],['UDP','TCP'])
    def test_xray_vnext_multi(self):
        n,w=parse_config({'outbounds':[{'protocol':'vless','settings':{'vnext':[{'address':'a.example','port':1},{'address':'b.example','port':2}]}}]})
        self.assertEqual(len(n),2);self.assertNotEqual(n[0].tag,n[1].tag)
    def test_chain_requires_confirmation(self):
        n,w=parse_config({'outbounds':[{'type':'socks','server':'a.example','server_port':80,'detour':'b'}]})
        self.assertTrue(n[0].warning)
    def test_custom_config_requires_confirmation(self):
        n,w=parse_config({'outbounds':[{'protocol':'custom','settings':{}}]})
        self.assertFalse(n);self.assertTrue(w)
    def test_port_changes(self):
        for p in (111,34443,65535):self.assertEqual(make_node('t','x.example',p,'x','UDP').port,p)
    def test_credentials_rejected(self):
        for host in ['https://a.example','user:pass@a.example','a.example/sub?token=123','x;Remove-Item']:
            with self.assertRaises(ValueError):valid_host(host)
    def test_ipv6(self):self.assertEqual(valid_host('[2001:db8::1]'),'2001:db8::1')


class StateTests(unittest.TestCase):
    def test_dual_route_success(self):
        rows=[route(),route(store='PersistentStore')];r=report(rows)
        x=inspect_routes(r['addresses'],r['net'],r['wlan'],{r['addresses'][0]:[rows[0]]})
        self.assertTrue(x[0]['ok'])
    def test_bind_not_proof_and_wrong_route(self):
        r=report();x=inspect_routes(r['addresses'],r['net'],r['wlan'],{r['addresses'][0]:[route(idx=58)]})
        self.assertFalse(x[0]['via_wlan']);self.assertFalse(x[0]['ok'])
    def test_missing_persistent(self):
        r=report([route()]);x=inspect_routes(r['addresses'],r['net'],r['wlan'],{r['addresses'][0]:[route()]})
        self.assertFalse(x[0]['ok']);self.assertTrue(x[0]['via_wlan'])
    def test_gateway_changed(self):
        r=report([route()],gw='10.0.0.99');x=inspect_routes(r['addresses'],r['net'],r['wlan'],{r['addresses'][0]:[route()]})
        self.assertFalse(x[0]['gateway_match'])
    def test_ipv6_not_hidden(self):
        r=report([route(),route(store='PersistentStore')],['203.0.113.10','2001:db8::1'])
        x=inspect_routes(r['addresses'],r['net'],r['wlan'],{'203.0.113.10':[route()]})
        self.assertEqual(len(x),2);self.assertFalse(x[1]['ok'])
    def test_wlan_disconnect(self):
        n=dict(interfaces=[dict(InterfaceAlias='WLAN',InterfaceIndex=7,ConnectionState=0)],addresses=[],routes=[])
        self.assertFalse(wlan_info(n,'WLAN')['connected'])
    def test_dynamic_index(self):
        n=dict(interfaces=[dict(InterfaceAlias='WLAN',InterfaceIndex=999,ConnectionState=1)],addresses=[],routes=[])
        self.assertEqual(wlan_info(n,'WLAN')['index'],999)
    def test_wlan_alone_not_company_fault(self):
        from guard.common import DEFAULTS
        n=dict(interfaces=[dict(InterfaceAlias='WLAN',InterfaceIndex=7,ConnectionState=1)],addresses=[],
               routes=[dict(route(),prefix='0.0.0.0/0')])
        with patch('guard.network.read_nodes',return_value=([make_node('proxy','192.0.2.1',443,'trojan','TCP')],[])),patch('guard.network.snapshot',return_value=n),patch('guard.network.resolve',return_value=['192.0.2.1']),patch('guard.network.selected_routes',return_value={'192.0.2.1':[route('192.0.2.1')]}),patch('guard.network.proxy_listener',return_value={'pid':1}):
            x=check(DEFAULTS)
        self.assertFalse(x['company']);self.assertFalse(any('PPPoE' in f for f in x['faults']))


class TransactionTests(unittest.TestCase):
    def perform(self,p,b):
        with tempfile.TemporaryDirectory() as tmp:
            return execute(p,b,Path(tmp)/'backups',False,Path(tmp)/'managed.json')
    def test_new_persistent_and_active(self):
        p=plan_routes(report(),{},[]);b=FakeBackend([])
        self.assertTrue(self.perform(p,b)['ok']);self.assertEqual(len(b.rows),2)
    def test_existing_route_idempotent(self):
        rows=[route(),route(store='PersistentStore')]
        p=plan_routes(report(rows),{},[]);b=FakeBackend(rows)
        self.assertTrue(self.perform(p,b)['ok']);self.assertFalse(b.mutations)
    def test_existing_requires_adopt(self):
        old=[route(gw='10.0.0.88')]
        p=plan_routes(report(old),{},[])
        self.assertFalse(p['deletes']);self.assertTrue(any(x['gateway']=='10.0.0.88' for x in p['after']))
    def test_metric_conflict_needs_adopt(self):
        with self.assertRaisesRegex(ValueError,'接管'):plan_routes(report([route(metric=10)]),{},[])
        p=plan_routes(report([route(metric=10)]),{},[],adopt=True)
        self.assertTrue(p['deletes'])
    def test_system_host_routes_not_adopted(self):
        r=dict(route(gw='10.0.0.8'),protocol=2)
        p=plan_routes(report([r]),{},[],adopt=True)
        self.assertNotIn(r,p['deletes']);self.assertIn(r,p['after'])
    def test_adoption_updates_old_gateway(self):
        old=[route(gw='10.0.0.88'),route(gw='10.0.0.88',store='PersistentStore')]
        p=plan_routes(report(old),{},[],adopt=True);b=FakeBackend(old,mirror=True)
        self.assertTrue(self.perform(p,b)['ok']);self.assertTrue(all(x['gateway']=='10.0.0.1' for x in b.rows))
    def test_unrelated_and_default_preserved(self):
        unrelated=route('198.51.100.8',idx=58);default=dict(route(idx=58),prefix='0.0.0.0/0')
        b=FakeBackend([unrelated,default]);p=plan_routes(report(b.rows),{},[],True,True)
        self.assertTrue(self.perform(p,b)['ok']);self.assertIn(default,b.rows);self.assertIn(unrelated,b.rows)
    def test_cleanup_only_managed_old_nodes(self):
        owned=route('192.0.2.1');unowned=route('198.51.100.8')
        p=plan_routes(report([owned,unowned]),{},[owned],cleanup=True)
        self.assertIn(owned,p['deletes']);self.assertNotIn(unowned,p['deletes'])
    def test_dns_change_no_implicit_cleanup(self):
        old=route('192.0.2.1');p=plan_routes(report([old]),{},[old])
        self.assertFalse(p['deletes']);self.assertIn(old,p['managed_after'])
    def test_ipv6_requires_gateway(self):
        with self.assertRaisesRegex(ValueError,'IPv6'):plan_routes(report(ips=['2001:db8::1']),{},[])
    def test_no_zero_gateway(self):
        with self.assertRaises(ValueError):plan_routes(report(),{'gateway':'0.0.0.0'},[])
    def test_ipv6_plan(self):
        p=plan_routes(report(ips=['2001:db8::1']),{'gateway6':'fe80::1'},[])
        self.assertTrue(all(x['prefix'].endswith('/128') for x in p['creates']))
    def test_permission_failure_rollback(self):
        old=[route(gw='10.0.0.88')];p=plan_routes(report(old),{},[],adopt=True);b=FakeBackend(old,fail=True)
        result=self.perform(p,b)
        self.assertFalse(result['ok']);self.assertEqual(b.rows,old);self.assertIn('恢复',result['message'])
    def test_stale_preview_no_mutations(self):
        p=plan_routes(report(),{},[]);b=FakeBackend([route()])
        with self.assertRaisesRegex(ValueError,'已变化'):self.perform(p,b)
        self.assertFalse(b.mutations)
    def test_expired_preview(self):
        p=plan_routes(report(),{},[]);p['created']-=181
        with self.assertRaises(ValueError):self.perform(p,FakeBackend([]))
    def test_node_config_change_aborts_before_mutation(self):
        p=plan_routes(report(),{'runtime':'fake.json'},[]);b=FakeBackend([])
        with patch('guard.nodes.read_nodes',return_value=([],[])):
            with self.assertRaisesRegex(ValueError,'节点配置'):execute(p,b,check_wlan=True)
        self.assertFalse(b.mutations)
    def test_dns_change_aborts_before_mutation(self):
        p=plan_routes(report(),{'runtime':'fake.json','manual':True},[]);b=FakeBackend([])
        with patch('guard.nodes.resolve',return_value=['198.51.100.8']):
            with self.assertRaisesRegex(ValueError,'DNS'):execute(p,b,check_wlan=True)
        self.assertFalse(b.mutations)
    def test_wlan_change_aborts_before_mutation(self):
        p=plan_routes(report(),{},[]);b=FakeBackend([])
        with patch('guard.nodes.resolve',return_value=p['node_guard']['addresses']),patch('guard.routes.snapshot',return_value={}),patch('guard.routes.wlan_info',return_value={'gateway':'10.0.0.99'}):
            with self.assertRaisesRegex(ValueError,'WLAN'):execute(p,b,check_wlan=True)
        self.assertFalse(b.mutations)
    def test_backup_before_first_write(self):
        p=plan_routes(report(),{},[]);b=FakeBackend([])
        with patch('guard.routes.save_json',side_effect=OSError('磁盘写入失败')):
            with self.assertRaises(OSError):self.perform(p,b)
        self.assertFalse(b.mutations)
    def test_persistent_mirroring(self):
        p=plan_routes(report(),{},[]);b=FakeBackend([],mirror=True)
        self.assertTrue(self.perform(p,b)['ok']);self.assertEqual(len(b.rows),2)
    def test_default_mutation_rejected(self):
        with self.assertRaises(ValueError):validate_route(dict(route(),prefix='0.0.0.0/0'))
    def test_restore_and_conflict(self):
        p=plan_routes(report(),{},[]);b=FakeBackend([])
        with tempfile.TemporaryDirectory() as tmp:
            result=execute(p,b,tmp,False,Path(tmp)/'managed.json')
            restore=restore_plan(result['backup'],b.rows)
            self.assertEqual(restore['after'],[])
            b.rows.append(route(gw='10.0.0.9'))
            with self.assertRaisesRegex(ValueError,'不一致'):restore_plan(result['backup'],b.rows)


if __name__=='__main__':unittest.main()
