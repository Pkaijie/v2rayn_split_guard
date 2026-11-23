import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import psutil

from guard import network
from guard.common import DEFAULTS
from guard.discovery import discover_runtime
from guard.nodes import read_runtime
from guard.routes import execute, plan_routes
from guard.standalone import brook_profile
from test_discovery import process
from test_guard import FakeBackend


HOST = 'node.example.invalid'
SECRET = 'DO_NOT_LEAK'
HY2 = f'server: {HOST}\nauth: {SECRET}\nsocks5: {{listen: "[::1]:18400"}}\n'
SHADOW = '''
inbounds:
  - {tag: socks, type: socks, bind-addr: '127.0.0.1:18405'}
outbounds:
  - {tag: proxy, type: shadowquic, addr: '[2001:db8::10]:8443'}
'''
TUIC = {'relay': {'server': HOST + ':443', 'ip': '203.0.113.41', 'password': SECRET},
        'local': {'server': '127.0.0.1:18402'}}
NAIVE = {'proxy': f'quic://test:{SECRET}@{HOST}',
         'listen': ['http://127.0.0.1:18401', 'socks://127.0.0.1:18411']}
JUICITY = {'server': HOST + ':7443', 'password': SECRET, 'listen': ':18403'}
OVERTLS = {'client_settings': {'server_host': '203.0.113.44', 'server_port': 9443,
                               'server_domain': HOST, 'listen': 'mixed://127.0.0.1:18404'},
           'tunnel_path': SECRET}


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        location = TemporaryDirectory()
        self.addCleanup(location.cleanup)
        self.home = Path(location.name)

    def config(self, filename, data):
        file = self.home / filename
        file.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
        return file

    def discovery(self, core, port):
        with patch('guard.discovery.psutil.process_iter', return_value=[core]), \
             patch('guard.discovery.local_proxy_listeners', return_value={port: {'pid': core.pid}}):
            return discover_runtime()

    def test_all_six_file_based_cores_and_windows_startup_forms(self):
        examples = (
            ('hysteria2', 'config.yaml', HY2, ['client', '-c', 'config.yaml'],
             'hysteria-windows-amd64.exe', HOST, 443, 'UDP', 18400),
            ('naiveproxy', 'naive custom.json', NAIVE, ['naive custom.json'],
             'naiveproxy.exe', HOST, 443, 'UDP', 18411),
            ('tuic', 'tuic.json', TUIC, ['-c=tuic.json'],
             'tuic-client.exe', '203.0.113.41', 443, 'UDP', 18402),
            ('juicity', 'juicity.json', JUICITY, ['run', '-c', 'juicity.json'],
             'juicity-client.exe', HOST, 7443, 'UDP', 18403),
            ('overtls', 'over.json', OVERTLS, ['-r', 'client', '--config', 'over.json'],
             'overtls-bin.exe', '203.0.113.44', 9443, 'TCP', 18404),
            ('shadowquic', 'shadow.yaml', SHADOW, ['-c', 'shadow.yaml'],
             'shadowquic.exe', '2001:db8::10', 8443, 'UDP', 18405),
        )
        for family, filename, data, args, exe, host, port, transport, listen in examples:
            with self.subTest(core=family):
                config = self.config(filename, data)
                profile = read_runtime(config)
                self.assertEqual((profile.family, profile.socks_ports), (family, (listen,)))
                node, = profile.nodes
                self.assertEqual((node.host, node.port, node.transport), (host, port, transport))
                self.assertNotIn(SECRET, repr(profile))
                core = process(20, exe, args=[exe, *args], cwd=self.home)
                result = self.discovery(core, listen)
                self.assertEqual(result['automatic'], str(config.resolve()))
                self.assertNotIn(SECRET, repr(result))

    def test_hysteria_uri_ipv6_port_hopping_and_realms(self):
        cfg = self.config('client.yaml', f'''
server: hy2://{SECRET}@[2001:db8::10]:18443-18445
socks5:
  listen: 127.0.0.1:18400
''')
        profile = read_runtime(cfg)
        node, = profile.nodes
        self.assertEqual((node.host, node.port, node.transport), ('2001:db8::10', 18443, 'UDP'))
        self.assertIn('端口跳跃', node.warning)
        self.assertNotIn(SECRET, repr(profile))
        cfg = self.config('client.yaml', HY2.replace(HOST, 'realm://' + SECRET + '@' + HOST + '/room'))
        profile = read_runtime(cfg)
        self.assertEqual(profile.socks_ports, (18400,))
        self.assertEqual(profile.nodes, [])
        self.assertIn('第一跳', profile.warnings[0])

    def test_hysteria_default_filename_is_a_safe_candidate_and_server_is_ignored(self):
        config = self.config('config.yaml', HY2)
        core = process(20, 'hysteria.exe', args=['hysteria.exe'], cwd=self.home)
        detected = self.discovery(core, 18400)
        self.assertEqual(detected['candidates'][0]['path'], str(config.resolve()))
        server = process(21, 'hysteria.exe', args=['hysteria.exe', 'server', '-c', str(config)], cwd=self.home)
        self.assertFalse(self.discovery(server, 18400)['candidates'])

    def test_modern_tuic_json5_and_toml_formats(self):
        statements = {
            'config.json5': f"{{server: '{HOST}:4443', // notes\n local: {{server: '127.0.0.1:18421',}},}}",
            'config.toml': f'server = "{HOST}:4443"\n[local]\nserver = "127.0.0.1:18421"\n',
        }
        for filename, data in statements.items():
            with self.subTest(filename=filename):
                profile = read_runtime(self.config(filename, data))
                self.assertEqual((profile.family, profile.nodes[0].port, profile.socks_ports), ('tuic', 4443, (18421,)))

    def test_tuic_relay_via_proxy_requires_explicit_first_hop(self):
        cfg = {'relay': dict(TUIC['relay'], proxy={'server': f'https://{SECRET}@{HOST}'}), 'local': TUIC['local']}
        profile = read_runtime(self.config('tuic.json', cfg))
        self.assertFalse(profile.nodes)
        self.assertIn('第一跳', profile.warnings[0])
        self.assertNotIn(SECRET, repr(profile))

    def test_shadowquic_singular_and_explicit_choice_with_multiple_outbounds(self):
        legacy = '''
inbound: {type: mixed, bind-addr: '0.0.0.0:18405'}
outbound: {type: shadowquic, addr: '203.0.113.45:443'}
'''
        profile = read_runtime(self.config('legacy.yaml', legacy))
        self.assertEqual((profile.nodes[0].host, profile.socks_ports), ('203.0.113.45', (18405,)))
        multi = SHADOW + "  - {tag: direct, type: direct}\nrouter: {default-outbound: direct}\n"
        profile = read_runtime(self.config('multi.yaml', multi))
        self.assertTrue(profile.choose_node)
        self.assertEqual(len(profile.nodes), 1)
        dynamic = read_runtime(self.config('lua.yaml', SHADOW + 'router: {path: private.lua}\n'))
        self.assertFalse(dynamic.nodes)
        self.assertEqual(dynamic.socks_ports, (18405,))
        self.assertNotIn('private.lua', repr(dynamic))

    def test_overtls_server_role_is_not_discovered(self):
        path = self.config('config.json', OVERTLS)
        core = process(20, 'overtls.exe', args=['overtls.exe', '--role=server', '-c', str(path)], cwd=self.home)
        self.assertFalse(self.discovery(core, 18404)['candidates'])

    def test_naive_http_only_and_multi_hop_do_not_guess_socks_or_node(self):
        config = self.config('config.json', dict(NAIVE, listen='http://127.0.0.1:18401',
                                               proxy=NAIVE['proxy'] + ',https://other.example.invalid'))
        profile = read_runtime(config)
        self.assertFalse(profile.nodes)
        self.assertFalse(profile.socks_ports)
        with patch('guard.network.run') as curl:
            result = network.test_proxy(config=dict(DEFAULTS, runtime=str(config)))
        self.assertFalse(result['ok'])
        curl.assert_not_called()

    def test_v2fly_v5_outbound_transport_and_file_listener(self):
        example = {
            'inbounds': [{'protocol': 'http', 'port': 18406}, {'protocol': 'socks', 'port': 18416}],
            'outbounds': [{'protocol': 'vmess', 'settings': {'address': HOST, 'port': 443},
                           'streamSettings': {'transport': 'quic'}}],
        }
        path = self.config('v5.json', example)
        profile = read_runtime(path)
        self.assertEqual((profile.family, profile.nodes[0].transport, profile.socks_ports),
                         ('outbounds', 'UDP', (18416,)))
        core = process(20, 'v2ray.exe', args=['v2ray.exe', 'run', '-c', 'v5.json', '-format', 'jsonv5'], cwd=self.home)
        self.assertEqual(self.discovery(core, 18416)['automatic'], str(path.resolve()))

    def test_brook_cli_and_link_pick_first_hop_without_password(self):
        plain = brook_profile(['brook.exe', 'client', '-s', HOST + ':443', '--password', SECRET])
        self.assertEqual((plain.nodes[0].transport, plain.socks_ports), ('TCP', (1080,)))
        link = 'brook://quicserver?' + urlencode({'quicserver': f'quic://{HOST}:443',
                                                'address': '203.0.113.40:8443', 'password': SECRET})
        argv = ['brook_windows_amd64.exe', 'connect', '-l', link, '--socks5=[::1]:18410']
        profile = brook_profile(argv)
        self.assertEqual((profile.nodes[0].host, profile.nodes[0].port, profile.nodes[0].transport, profile.socks_ports),
                         ('203.0.113.40', 8443, 'UDP', (18410,)))
        core = process(20, argv[0], args=argv, cwd=self.home)
        detected = self.discovery(core, 18410)
        self.assertEqual(detected['automatic'], '@brook:20')
        self.assertNotIn(SECRET, repr((plain, profile, detected)))
        with patch('guard.standalone.psutil.Process', return_value=Mock(name=argv[0], **{
                'name.return_value': argv[0], 'cmdline.return_value': argv})):
            self.assertEqual(read_runtime('@brook:20'), profile)

    def test_brook_only_tests_selected_process_loopback(self):
        with patch('guard.network.read_runtime', return_value=brook_profile(['brook.exe', 'client', '-s', HOST + ':443'])), \
             patch('guard.network.local_proxy_listeners', return_value={1080: {'host': '::1', 'port': 1080}}) as local, \
             patch('guard.network.run', return_value='{"ip":"203.0.113.30"}') as curl:
            self.assertTrue(network.test_proxy(config=dict(DEFAULTS, runtime='@brook:20'))['ok'])
        local.assert_called_once_with(pid=20)
        self.assertIn('socks5h://[::1]:1080', curl.call_args.args[0])
        with patch('guard.standalone.psutil.Process', side_effect=psutil.NoSuchProcess(20)):
            with self.assertRaisesRegex(ValueError, '重新检测'):
                read_runtime('@brook:20')

    def test_brook_changed_after_preview_cannot_write_routes(self):
        argv = ['brook.exe', 'client', '-s', '203.0.113.34:443']
        node, = brook_profile(argv).nodes
        report = dict(node=node.to_dict(), addresses=[node.host], net={'routes': []},
                      wlan=dict(index=7, connected=True, gateway='192.0.2.1', gateway6='', alias='WLAN'))
        plan = plan_routes(report, dict(DEFAULTS, runtime='@brook:20'), [])
        new = ['brook.exe', 'client', '-s', '203.0.113.35:443']
        core = Mock(**{'name.return_value': argv[0], 'cmdline.return_value': new})
        backend = FakeBackend([])
        with patch('guard.standalone.psutil.Process', return_value=core):
            with self.assertRaisesRegex(ValueError, '节点配置'):
                execute(plan, backend, self.home)
        self.assertFalse(backend.mutations)

    def test_stale_brook_pid_does_not_test_manually_overridden_port(self):
        config = dict(DEFAULTS, runtime='@brook:20', proxy_port=18410)
        process = Mock(**{'name.return_value': 'other.exe'})
        with patch('guard.standalone.psutil.Process', return_value=process), \
             patch('guard.network.local_proxy_listeners') as listeners, patch('guard.network.run') as curl:
            result = network.test_proxy(config=config)
        self.assertFalse(result['ok'])
        self.assertIn('重新检测', result['message'])
        listeners.assert_not_called()
        curl.assert_not_called()
