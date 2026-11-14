"""Query budgets and safety boundaries; every network read/write is simulated."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch,Mock
from guard.common import DEFAULTS,OperationCancelled,run
from guard import routes,network
from guard.samples import report_fixture
from test_guard import FakeBackend


class RouteQueryTests(unittest.TestCase):
    def setUp(self):
        self.report=report_fixture();self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
    def execute(self,plan,**kwargs):
        return routes.execute(plan,backup_dir=self.directory/'backups',ledger_path=self.directory/'managed.json',**kwargs)
    def test_native_noop_one_snapshot_for_ipv4_and_dual_stack(self):
        for addresses in ([self.report['addresses'][0]],self.report['addresses']):
            r=copy.deepcopy(self.report);r['addresses']=addresses
            p=routes.plan_routes(r,DEFAULTS,[])
            with patch('guard.nodes.resolve',return_value=addresses),patch('guard.routes.snapshot',return_value=r['net']) as snapshot,patch('guard.routes.wlan_info',return_value=r['wlan']),patch('guard.routes.read_routes',side_effect=AssertionError('Redundant query')),patch.object(routes.WindowsRoutes,'add',side_effect=AssertionError('Write forbidden')),patch.object(routes.WindowsRoutes,'remove',side_effect=AssertionError('Write forbidden')):
                result=self.execute(p)
            self.assertEqual(snapshot.call_count,1);self.assertFalse(result['route_changed']);self.assertEqual(result['backup'],'')
        self.assertFalse((self.directory/'backups').exists())
    def test_adopt_noop_backs_up_ledger_without_route_reconcile(self):
        p=routes.plan_routes(self.report,DEFAULTS,[],adopt=True)
        b=FakeBackend(self.report['net']['routes'])
        with patch.object(b,'read',wraps=b.read) as reads,patch('guard.routes.reconcile',side_effect=AssertionError('Noop must not reconcile')):
            result=self.execute(p,backend=b,check_wlan=False)
        self.assertEqual(reads.call_count,1);self.assertFalse(b.mutations);self.assertFalse(result['route_changed'])
        self.assertTrue(Path(result['backup']).is_file());self.assertTrue((self.directory/'managed.json').is_file())
    def test_noop_still_refuses_concurrent_route_change(self):
        p=routes.plan_routes(self.report,DEFAULTS,[]);b=FakeBackend([])
        with self.assertRaisesRegex(ValueError,'路由自预览后已变化'):self.execute(p,backend=b,check_wlan=False)
        self.assertFalse(b.mutations)
    def test_noop_still_refuses_gateway_change(self):
        p=routes.plan_routes(self.report,DEFAULTS,[])
        with patch('guard.nodes.resolve',return_value=self.report['addresses']),patch('guard.routes.snapshot',return_value=self.report['net']),patch('guard.routes.wlan_info',return_value=dict(self.report['wlan'],gateway='10.0.0.9')):
            with self.assertRaisesRegex(ValueError,'WLAN'):self.execute(p)
    def test_manual_no_runtime_still_checks_dns(self):
        p=routes.plan_routes(self.report,dict(DEFAULTS,manual=True),[])
        with patch('guard.nodes.resolve',return_value=['192.0.2.8']):
            with self.assertRaisesRegex(ValueError,'DNS'):self.execute(p)
    def test_noop_does_not_skip_runtime_node_guard(self):
        p=routes.plan_routes(self.report,dict(DEFAULTS,runtime='example.json'),[])
        with patch('guard.nodes.read_nodes',return_value=([],[])):
            with self.assertRaisesRegex(ValueError,'节点配置'):self.execute(p)
    def test_missing_ipv6_persistent_store_never_passes_noop(self):
        p=routes.plan_routes(self.report,DEFAULTS,[])
        b=FakeBackend([r for r in self.report['net']['routes'] if not (':' in r['prefix'] and r['store']=='PersistentStore')])
        with self.assertRaisesRegex(ValueError,'路由自预览后已变化'):self.execute(p,backend=b,check_wlan=False)
    def test_inconsistent_noop_diff_rejected(self):
        p=routes.plan_routes(self.report,DEFAULTS,[]);p['after']=[]
        with self.assertRaisesRegex(ValueError,'差异不一致'):self.execute(p,check_wlan=False)
    def test_preview_expiring_during_preflight_refuses_save(self):
        p=routes.plan_routes(self.report,DEFAULTS,[]);b=FakeBackend(self.report['net']['routes'])
        with patch('guard.routes.time.time',side_effect=[p['created']+1,p['created']+181]):
            with self.assertRaisesRegex(ValueError,'超过 3 分钟'):self.execute(p,backend=b,check_wlan=False)
        self.assertFalse(list(self.directory.iterdir()))
    def test_cancel_after_fresh_read_prevents_ledger_backup(self):
        p=routes.plan_routes(self.report,DEFAULTS,[],adopt=True);b=FakeBackend(self.report['net']['routes']);stop=threading.Event()
        def read():stop.set();return b.rows
        with patch.object(b,'read',read):
            with self.assertRaises(OperationCancelled):self.execute(p,backend=b,check_wlan=False,stop=stop)
        self.assertFalse(list(self.directory.iterdir()));self.assertFalse(b.mutations)
    def test_mirrored_persistent_add_skips_redundant_active_add(self):
        report=copy.deepcopy(self.report);report['net']['routes']=[]
        p=routes.plan_routes(report,DEFAULTS,[]);b=FakeBackend([])
        calls=[];original=b.add
        def add(r):
            calls.append(r['store']);original(r)
            if r['store']=='PersistentStore':original(dict(r,store='ActiveStore'))
        with patch.object(b,'add',add):
            self.assertTrue(self.execute(p,backend=b,check_wlan=False)['ok'])
        self.assertEqual(calls,['PersistentStore','PersistentStore'])
        self.assertEqual(len(b.rows),4)
    def test_query_only_reads_both_stores_and_has_no_adapter_lookup(self):
        with patch('guard.network.ps_json',return_value=dict(active=[],persistent=[])) as query:
            self.assertEqual(network.read_routes({'203.0.113.10/32'}),[])
        script=query.call_args.args[0]
        self.assertIn('ActiveStore',script);self.assertIn('PersistentStore',script)
        self.assertNotIn('Get-NetAdapter',script);self.assertNotIn('Get-NetIPInterface',script)
        with patch('guard.network.ps_json',return_value=dict(active=[],persistent=[])) as query:network.snapshot()
        self.assertNotIn('Get-NetAdapter',query.call_args.args[0])
    def test_pre_cancelled_subprocess_is_not_started(self):
        stop=threading.Event();stop.set()
        with patch('guard.common.subprocess.Popen') as process:
            with self.assertRaises(OperationCancelled):run(['unused'],stop=stop)
        process.assert_not_called()
    def test_combined_snapshot_includes_ipv4_ipv6_selection_in_one_query(self):
        targets=['203.0.113.10','2001:db8::10']
        raw=[dict(DestinationPrefix=ip+('/128' if ':' in ip else '/32'),InterfaceIndex=7,InterfaceAlias='WLAN',NextHop='fe80::1' if ':' in ip else '10.0.0.1',RouteMetric=1,InterfaceMetric=20,Protocol=3) for ip in targets]
        result=dict(interfaces=[],addresses=[],active=raw,persistent=raw,selected={ip:[r] for ip,r in zip(targets,raw)})
        with patch('guard.network.ps_json',return_value=result) as query:
            snap=network.snapshot(addresses=targets)
        self.assertEqual(query.call_count,1);self.assertEqual(len(snap['routes']),4)
        self.assertEqual(set(snap['selected']),set(targets));self.assertTrue(all(snap['selected'][ip][0]['index']==7 for ip in targets))
        self.assertIn('Find-NetRoute',query.call_args.args[0]);self.assertNotIn('Get-NetAdapter',query.call_args.args[0])
    def test_adoption_backup_failure_leaves_ledger_and_routes_untouched(self):
        p=routes.plan_routes(self.report,DEFAULTS,[],adopt=True);b=FakeBackend(self.report['net']['routes'])
        with patch('guard.routes.save_json',side_effect=OSError('模拟备份失败')):
            with self.assertRaises(OSError):self.execute(p,backend=b,check_wlan=False)
        self.assertFalse(b.mutations)
    def test_post_write_mismatch_rolls_back_and_preserves_unrelated_routes(self):
        r=copy.deepcopy(self.report);r['net']['routes']=[];p=routes.plan_routes(r,DEFAULTS,[])
        b=FakeBackend([]);original=b.add
        def add(route):
            if ':' in route['prefix']:return  # Model a failed native operation.
            original(route)
        with patch.object(b,'add',add):result=self.execute(p,backend=b,check_wlan=False)
        self.assertFalse(result['ok']);self.assertEqual(b.rows,[]);self.assertIn('恢复',result['message'])
    def test_protocol_only_change_refuses_noop_before_ledger_update(self):
        p=routes.plan_routes(self.report,DEFAULTS,[],adopt=True);b=FakeBackend(self.report['net']['routes'])
        b.rows[0]['protocol']=2
        with self.assertRaisesRegex(ValueError,'路由自预览后已变化'):self.execute(p,backend=b,check_wlan=False)
        self.assertFalse(b.mutations);self.assertFalse(list(self.directory.iterdir()))
    def test_native_remove_rechecks_protocol_before_netsh(self):
        r=self.report['net']['routes'][0]
        with patch('guard.routes.read_routes',return_value=[dict(r,protocol=2)]),patch('guard.routes.run') as command:
            with self.assertRaisesRegex(ValueError,'拒绝删除'):routes.WindowsRoutes().remove(r)
        command.assert_not_called()
    def test_reconcile_refuses_protocol_change_during_transaction(self):
        r=self.report['net']['routes'][0];b=FakeBackend([dict(r,protocol=2)])
        with self.assertRaisesRegex(RuntimeError,'非 NetMgmt'):
            routes.reconcile(b,[r],[],{routes.identity(r)})
        self.assertFalse(b.mutations)
    def test_final_check_detects_protocol_only_mismatch(self):
        r=self.report['net']['routes'][0];b=FakeBackend([dict(r,protocol=2)])
        with self.assertRaisesRegex(RuntimeError,'核验不一致'):
            routes.reconcile(b,[r],[r],set())
        self.assertFalse(b.mutations)
    def test_native_add_cannot_recreate_protected_route_protocol(self):
        r=dict(self.report['net']['routes'][0],protocol=2)
        with patch('guard.routes.read_routes',return_value=[]),patch('guard.routes.run') as command:
            with self.assertRaisesRegex(ValueError,'拒绝写入'):routes.WindowsRoutes().add(r)
        command.assert_not_called()


class WorkerProgressTests(unittest.TestCase):
    def exercise(self,fail=False):
        from guard import elevation
        from guard.common import save_json
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);jobs=data/'jobs';jobs.mkdir();ident='a'*32
            request=jobs/(ident+'.request.json');result=jobs/(ident+'.result.json')
            request.write_text(json.dumps(dict(action='routes',plan={})),encoding='utf-8')
            digest=hashlib.sha256(request.read_bytes()).hexdigest();writes=[]
            def save(path,value):writes.append(copy.deepcopy(value));save_json(path,value)
            def execute(plan,*,progress):
                progress('备份变更前记录')
                if fail:raise RuntimeError('模拟任务失败')
                return dict(ok=True,message='模拟完成',backup='')
            with patch('guard.elevation.DATA',data),patch('guard.elevation.is_admin',return_value=True),patch('guard.elevation.save_json',save),patch('guard.routes.execute',execute):
                elevation.worker(request,result,digest)
            return writes,json.loads(result.read_text(encoding='utf-8'))
    def test_worker_progress_is_followed_by_final_result(self):
        writes,final=self.exercise()
        self.assertTrue(writes[0]['running']);self.assertEqual(writes[0]['stage'],'备份变更前记录')
        self.assertTrue(final['ok']);self.assertNotIn('running',final)
    def test_worker_error_replaces_pending_progress(self):
        writes,final=self.exercise(True)
        self.assertTrue(writes[0]['running']);self.assertFalse(final['ok']);self.assertNotIn('running',final)
