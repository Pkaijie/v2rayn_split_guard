from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from guard import network
from guard.common import DEFAULTS
from guard.discovery import discover_runtime
from guard.nodes import read_nodes, read_runtime
from guard.routes import execute, plan_routes
from test_discovery import process
from test_guard import FakeBackend, route


CLASH = """mixed-port: 17890
socks-port: 17891
proxies:
  - {name: Alpha, type: ss, server: 203.0.113.10, port: 443, udp: true, password: DO_NOT_LEAK}
  - {name: Beta, type: hysteria2, server: '2001:db8::10', port: "8443", ports: "8443-8450"}
  - {name: DIRECT, type: direct}
proxy-groups:
  - {name: Auto, type: url-test, proxies: [Alpha, Beta]}
"""


class ClashTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.path = self.home / 'config.yaml'
        self.path.write_text(CLASH, encoding='utf-8-sig')
        self.config = dict(DEFAULTS, runtime=str(self.path))

    def test_ports_transport_and_groups(self):
        profile = read_runtime(self.path)
        self.assertEqual(profile.family, 'clash')
        self.assertEqual(profile.socks_ports, (17890, 17891))
        self.assertTrue(profile.choose_node)
        self.assertEqual([(n.tag, n.host, n.port, n.transport) for n in profile.nodes],
                         [('Alpha','203.0.113.10',443,'TCP'), ('Beta','2001:db8::10',8443,'UDP')])
        self.assertIn('端口跳跃', profile.nodes[1].warning)
        self.assertNotIn('DO_NOT_LEAK', repr(profile))

    def test_anchors_and_safe_inline_provider(self):
        self.path.write_text("""
node: &defaults {type: ss, server: 203.0.113.10, port: 443}
proxy-providers:
  provider-inline:
    type: inline
    payload:
      - {<<: *defaults, name: Alpha}
  provider-file:
    type: file
    path: private-provider.yaml
""", encoding='utf-8')
        profile = read_runtime(self.path)
        self.assertEqual([n.tag for n in profile.nodes], ['Alpha'])
        self.assertTrue(profile.choose_node)
        self.assertTrue(any('外部' in message for message in profile.warnings))
        self.assertNotIn('private-provider.yaml', repr(profile))

    def test_yaml_error_does_not_expose_config(self):
        for content in ('proxies: !custom DO_NOT_LEAK',
                        'proxies: [&test {name: DO_NOT_LEAK, <<: *test}]',
                        'proxies: [DO_NOT_LEAK'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError) as raised:
                    read_runtime(self.path)
                self.assertNotIn('DO_NOT_LEAK', str(raised.exception))

    def test_invalid_ports_names_and_chain(self):
        self.path.write_text("""
mixed-port: true
socks-port: 65536
port: 7890
proxies:
  - {name: Dup, type: ss, server: 203.0.113.10, port: 443}
  - {name: Dup, type: ss, server: 203.0.113.11, port: 443}
  - {name: Invalid, type: ss, server: 203.0.113.12, port: 1.5}
  - {name: Chain, type: trojan, server: 203.0.113.13, port: 443, dialer-proxy: Dup}
""", encoding='utf-8')
        profile = read_runtime(self.path)
        self.assertFalse(profile.socks_ports)
        self.assertEqual([n.tag for n in profile.nodes], ['Chain'])
        self.assertIn('第一跳', profile.nodes[0].warning)
        self.assertTrue(profile.choose_node)

    def discover(self, core, listeners):
        with patch('guard.discovery.psutil.process_iter', return_value=[core]), \
             patch('guard.discovery.local_proxy_listeners', return_value=listeners):
            return discover_runtime()

    def test_mihomo_f_is_relative_to_cwd_even_with_d(self):
        data_home = self.home / 'data home'
        data_home.mkdir()
        core = process(20, 'mihomo-windows-amd64-v3.exe',
                       args=['mihomo.exe', '-d', str(data_home), '-f=config.yaml'], cwd=self.home)
        detected = self.discover(core, {17891: {'pid': 20}})
        self.assertEqual(detected['automatic'], str(self.path.resolve()))
        self.assertIn('Clash / Mihomo', detected['candidates'][0]['source'])
        unmatched = self.discover(core, {17891: {'pid': 21}})
        self.assertFalse(unmatched['automatic'])
        self.assertEqual(len(unmatched['candidates']), 1)

    def test_clash_d_only_uses_home_config(self):
        core = process(20, 'clash.exe', args=['clash.exe', '-d', str(self.home)], cwd=self.home.parent)
        self.assertEqual(self.discover(core, {17890: {'pid': 20}})['automatic'], str(self.path.resolve()))

    def test_inline_config_argument_is_not_read_as_a_file(self):
        core = process(20, 'verge-mihomo.exe',
                       args=['verge-mihomo.exe', '-d', str(self.home), '-f', str(self.path), '-config', 'DO_NOT_LEAK'])
        result = self.discover(core, {17890: {'pid': 20}})
        self.assertFalse(result['candidates'])
        self.assertNotIn('DO_NOT_LEAK', repr(result))

    def test_check_requires_selection_and_routes_only_selected_node(self):
        net = dict(interfaces=[dict(InterfaceAlias='WLAN', InterfaceIndex=7, ConnectionState=1)],
                   addresses=[], routes=[dict(route(), prefix='0.0.0.0/0')], selected={})
        listener = dict(host='127.0.0.1', port=17891, pid=20)
        with patch('guard.network.snapshot', return_value=net) as snap, \
             patch('guard.network.proxy_listener', return_value=listener) as probe:
            first = network.check(self.config)
            self.assertTrue(first['needs_node_choice'])
            self.assertIsNone(first['node'])
            self.assertFalse(first['rows'])
            snap.assert_called_with(None, addresses=[])
            second = network.check(dict(self.config, tag='Beta'))
        probe.assert_called_with((17890, 17891))
        self.assertEqual(second['local_proxy_address'], '127.0.0.1:17891')
        self.assertEqual(second['node']['tag'], 'Beta')
        self.assertEqual(second['addresses'], ['2001:db8::10'])
        self.assertFalse(second['needs_node_choice'])

    def test_proxy_test_uses_live_loopback_and_override(self):
        with patch('guard.network.local_proxy_listeners', return_value={
                17891: dict(host='::1', port=17891), 18080: dict(host='127.0.0.1', port=18080)
        }), patch('guard.network.run', return_value='{"ip":"203.0.113.4"}') as run:
            self.assertTrue(network.test_proxy(config=self.config)['ok'])
            self.assertIn('socks5h://[::1]:17891', run.call_args.args[0])
            self.assertTrue(network.test_proxy(config=dict(self.config, proxy_port=18080))['ok'])
            self.assertIn('socks5h://127.0.0.1:18080', run.call_args.args[0])

    def test_http_only_does_not_fall_back_to_unrelated_10808(self):
        self.path.write_text('port: 7890\nproxies: []\n', encoding='utf-8')
        with patch('guard.network.local_proxy_listeners') as listeners, patch('guard.network.run') as run:
            result = network.test_proxy(config=self.config)
        self.assertFalse(result['ok'])
        self.assertIn('SOCKS5', result['message'])
        listeners.assert_not_called()
        run.assert_not_called()

    def test_detect_wildcard_and_ignore_non_loopback(self):
        connections = [
            SimpleNamespace(status='LISTEN', laddr=('::', 17890), pid=20),
            SimpleNamespace(status='LISTEN', laddr=('0.0.0.0', 17890), pid=21),
            SimpleNamespace(status='LISTEN', laddr=('192.0.2.9', 17891), pid=22),
        ]
        with patch('psutil.net_connections', return_value=connections):
            self.assertEqual(network.proxy_listener((17890,))['host'], '127.0.0.1')
            self.assertIsNone(network.proxy_listener((17891,)))

    def test_route_apply_revalidates_yaml_after_preview(self):
        (node, *_), _ = read_nodes(self.path)
        report = dict(node=node.to_dict(), addresses=[node.host], net={'routes': []},
                      wlan=dict(index=7, connected=True, gateway='192.0.2.1',
                                gateway6='', alias='WLAN'))
        plan = plan_routes(report, self.config, [])
        self.path.write_text(CLASH.replace('203.0.113.10', '203.0.113.11'), encoding='utf-8')
        backend = FakeBackend([])
        with self.assertRaisesRegex(ValueError, '节点配置'):
            execute(plan, backend, self.home)
        self.assertFalse(backend.mutations)
