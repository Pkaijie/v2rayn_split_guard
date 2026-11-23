"""Synthetic process records only; no real app/configuration or network mutation."""
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import psutil
from guard.discovery import config_arguments, discover_runtime, runtime_file
from guard.nodes import MAX_BYTES


def process(pid, name, exe='', args=(), cwd='', parent=0):
    return SimpleNamespace(pid=pid, info=dict(name=name,ppid=parent),
        exe=Mock(return_value=str(exe)), cmdline=Mock(return_value=list(args)),
        cwd=Mock(return_value=str(cwd)))


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.write('示例 空格/binConfigs/config.json')

    def write(self, relative, data=None):
        path=self.home/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data if data is not None else
            dict(outbounds=[dict(type='hysteria2',tag='proxy',server='node.example.invalid',server_port=443)])),encoding='utf-8-sig')
        return path.resolve()

    def discover(self, processes, listener=None, **kw):
        listeners = {listener.get('port', 10808):listener} if listener else {}
        with patch('guard.discovery.psutil.process_iter',return_value=processes), \
             patch('guard.discovery.local_proxy_listeners',return_value=listeners):
            return discover_runtime(**kw)

    def core(self, pid=20, path=None, parent=0):
        return process(pid,'xray.exe',args=['xray.exe','run','-config',str(path or self.config)],parent=parent)

    def test_listener_core_is_preferred_and_paths_are_deduplicated(self):
        gui=process(10,'v2rayN.exe',self.config.parent.parent/'v2rayN.exe')
        result=self.discover([gui,self.core(parent=10)],dict(pid=20))
        self.assertEqual(result['automatic'],str(self.config))
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(result['candidates'][0]['rank'],0)
        self.assertNotIn('outbounds',repr(result))
        self.assertNotIn('node.example.invalid',repr(result))

    def test_core_descendant_without_listener_can_be_identified(self):
        gui=process(10,'v2rayN.exe')
        wrapper=process(15,'wrapper.exe',parent=10)
        result=self.discover([gui,wrapper,self.core(parent=15)])
        self.assertEqual(result['automatic'],str(self.config))
        self.assertEqual(result['candidates'][0]['rank'],1)

    def test_unrelated_core_is_only_a_manual_candidate(self):
        result=self.discover([self.core()])
        self.assertFalse(result['automatic'])
        self.assertEqual(len(result['candidates']),1)
        self.assertFalse(result['candidates'][0]['confirmed'])

    def test_multiple_active_instances_are_not_guessed(self):
        other=self.write('第二个/config.json')
        gui=process(10,'v2rayN.exe')
        result=self.discover([gui,self.core(parent=10),self.core(21,other,parent=10)])
        self.assertEqual(len(result['candidates']),2)
        self.assertFalse(result['automatic'])
        preferred=self.discover([gui,self.core(parent=10),self.core(21,other,parent=10)],dict(pid=21))
        self.assertEqual(preferred['automatic'],str(other))

    def test_directory_fallback_requires_confirmation(self):
        gui=process(10,'v2rayN.exe',self.config.parent.parent/'v2rayN.exe')
        result=self.discover([gui])
        self.assertEqual(result['candidates'][0]['path'],str(self.config))
        self.assertFalse(result['automatic'])

    def test_relative_config_uses_cwd_and_singbox_directory(self):
        core=process(20,'sing-box.exe',args=['sing-box.exe','run','-D',str(self.config.parent),'-c','config.json'])
        result=self.discover([core],dict(pid=20))
        self.assertEqual(result['automatic'],str(self.config))
        core.cmdline.return_value=['xray.exe','-c','binConfigs/config.json']
        core.cwd.return_value=str(self.config.parent.parent)
        self.assertEqual(self.discover([core],dict(pid=20))['automatic'],str(self.config))

    def test_config_switch_forms_and_quoted_space_path(self):
        for flag in ('-c','-config','--config'):
            with self.subTest(flag=flag):
                self.assertEqual(config_arguments(['core',flag,'"'+str(self.config)+'"'])[0],[str(self.config)])
                self.assertEqual(config_arguments(['core',flag+'='+str(self.config)])[0],[str(self.config)])

    def test_merged_config_never_automatically_selects_one_file(self):
        other=self.write('other.json')
        for suffix in (['-c',str(other)],['-C',str(self.home)]):
            core=self.core();core.cmdline.return_value+=suffix
            result=self.discover([core],dict(pid=20))
            self.assertFalse(result['automatic'])
            self.assertTrue(result['notes'])
            self.assertTrue(all(not c['confirmed'] for c in result['candidates']))

    def test_permission_denied_is_sanitized_and_falls_back(self):
        gui=process(10,'v2rayN.exe',self.config.parent.parent/'v2rayN.exe')
        core=self.core(parent=10)
        core.cmdline.side_effect=psutil.AccessDenied(pid=20,msg='SENSITIVE_ARGUMENT_SENTINEL')
        result=self.discover([gui,core])
        self.assertFalse(result['automatic'])
        self.assertTrue(result['notes'])
        self.assertNotIn('SENSITIVE_ARGUMENT_SENTINEL',repr(result))

    def test_missing_cwd_does_not_resolve_relative_path_against_tool(self):
        core=self.core();core.cmdline.return_value=['xray.exe','-c','config.json']
        core.cwd.side_effect=psutil.AccessDenied(pid=20)
        result=self.discover([core],dict(pid=20))
        self.assertFalse(result['candidates'])
        self.assertFalse(result['automatic'])

    def test_no_process_or_config_gives_manual_guidance(self):
        result=self.discover([])
        self.assertFalse(result['candidates'])
        self.assertIn('启动代理客户端',' '.join(result['notes']))

    def test_gui_json_malformed_large_and_missing_files_are_rejected(self):
        gui=self.write('guiNConfig.json',dict(coreType=1))
        invalid=self.home/'invalid.json';invalid.write_text('{',encoding='utf-8')
        large=self.home/'large.json'
        with large.open('wb') as f:f.truncate(MAX_BYTES+1)
        for path in (gui,invalid,large,self.home/'missing.json'):
            self.assertFalse(runtime_file(path))

    def test_cancel_and_timeout_disable_automatic_choice(self):
        stop=threading.Event();stop.set()
        self.assertTrue(self.discover([self.core()],stop=stop)['cancelled'])
        self.assertFalse(self.discover([self.core()],timeout=0)['automatic'])

    def test_unc_and_device_arguments_are_not_probed(self):
        for path in (r'\\server\share\config.json',r'\\.\pipe\config.json'):
            core=self.core(path=path)
            with patch('guard.discovery.runtime_metadata') as validate:
                result=self.discover([core],dict(pid=20))
            self.assertFalse(result['candidates'])
            validate.assert_not_called()
