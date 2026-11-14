"""Privacy boundaries, request integrity and pre-mutation validation."""
import hashlib
import json
from pathlib import Path
import tempfile
import os
import sys
import unittest
from unittest.mock import Mock, patch

from guard.common import DEFAULTS
from guard.elevation import worker, fresh_worker_environment
from guard.network import test_proxy
from guard.privacy import public_diagnostic
from guard.routes import execute


class PrivacyTests(unittest.TestCase):
    def test_diagnostic_uses_only_status_allowlist(self):
        canary='CANARY_PRIVATE_ENDPOINT'
        r=dict(time='2026-11-05 00:00:00 -0800',company=True,
               node=dict(host=canary,tag=canary,protocol=canary,port=34443,transport='UDP',password=canary),
               wlan=dict(connected=True,index=7,ipv4=[canary],gateway=canary,mac=canary),
               addresses=['203.0.113.10','2001:db8::1'],listener=dict(pid=123),dns_error=canary,
               faults=[canary],net=dict(adapters=[dict(InterfaceGuid=canary)]),
               rows=[dict(ip='203.0.113.10',via_wlan=True,active=True,persistent=True,
                          gateway_match=True,ok=True,chosen=[canary])],
               proxy_test=dict(ok=True,ip='203.0.113.20',message=canary))
        public=public_diagnostic(r)
        encoded=json.dumps(public)
        self.assertNotIn(canary,encoded)
        self.assertNotIn('203.0.113.',encoded)
        self.assertNotIn('2001:db8',encoded)
        self.assertEqual(public['node']['address_families'],[4,6])
        self.assertTrue(public['routes'][0]['ok'])
        self.assertEqual(public['fault_count'],1)

    def test_no_personal_defaults(self):
        self.assertEqual(DEFAULTS['runtime'],'')
        self.assertEqual(DEFAULTS['gui'],'')
        self.assertEqual(DEFAULTS['host'],'')

    def test_curl_ignores_ambient_configuration(self):
        with patch('guard.network.run',return_value='{"ip":"203.0.113.20"}') as run:
            result=test_proxy()
        self.assertTrue(result['ok'])
        self.assertEqual(run.call_args.args[0][:2],['curl.exe','-q'])
        self.assertIn('socks5h://127.0.0.1:10808',run.call_args.args[0])

    def test_invalid_plan_id_rejected_before_any_io(self):
        backend=Mock()
        with patch('guard.routes.save_json') as write:
            for ident in ('../escape','',None,'a'*33):
                with self.assertRaises(ValueError):execute(dict(id=ident),backend=backend)
        backend.assert_not_called()
        backend.read.assert_not_called()
        write.assert_not_called()

    def test_worker_rejects_output_outside_jobs(self):
        with tempfile.TemporaryDirectory() as tmp, patch('guard.elevation.DATA',Path(tmp)),patch('guard.elevation.save_json') as save,patch('guard.routes.execute') as mutate:
            ident='a'*32
            worker(Path(tmp)/'jobs'/f'{ident}.request.json',Path(tmp)/'escape.json','invalid')
            save.assert_not_called();mutate.assert_not_called()

    def run_worker(self,permission=True,tamper=False):
        with tempfile.TemporaryDirectory() as tmp,patch('guard.elevation.DATA',Path(tmp)),patch('guard.elevation.is_admin',return_value=permission),patch('guard.routes.execute',return_value={'ok':True}) as mutate:
            jobs=Path(tmp)/'jobs';jobs.mkdir()
            ident='a'*32
            req,res=jobs/f'{ident}.request.json',jobs/f'{ident}.result.json'
            raw=json.dumps(dict(action='routes',plan=dict(id=ident))).encode()
            req.write_bytes(raw)
            digest=hashlib.sha256(raw).hexdigest()
            if tamper:req.write_bytes(raw+b' ')
            worker(req,res,digest)
            return json.loads(res.read_text(encoding='utf-8')),mutate.call_count

    def test_worker_detects_request_tampering(self):
        result,count=self.run_worker(tamper=True)
        self.assertFalse(result['ok']);self.assertEqual(count,0)
        self.assertIn('已变化',result['error'])

    def test_worker_requires_administrator(self):
        result,count=self.run_worker(permission=False)
        self.assertFalse(result['ok']);self.assertEqual(count,0)
        self.assertIn('权限不足',result['error'])

    def test_worker_accepts_unchanged_confirmed_request(self):
        result,count=self.run_worker()
        self.assertTrue(result['ok']);self.assertEqual(count,1)

    def test_frozen_worker_gets_fresh_runtime_and_restores_environment(self):
        name='PYINSTALLER_RESET_ENVIRONMENT'
        with patch.object(sys,'frozen',True,create=True),patch.dict(os.environ,{name:'previous'}):
            with self.assertRaises(RuntimeError):
                with fresh_worker_environment():
                    self.assertEqual(os.environ[name],'1')
                    raise RuntimeError('模拟取消启动')
            self.assertEqual(os.environ[name],'previous')

    def test_frozen_worker_does_not_leave_extra_environment_variable(self):
        name='PYINSTALLER_RESET_ENVIRONMENT'
        with patch.object(sys,'frozen',True,create=True),patch.dict(os.environ,{},clear=True):
            with fresh_worker_environment():self.assertEqual(os.environ[name],'1')
            self.assertNotIn(name,os.environ)


if __name__=='__main__':unittest.main()
