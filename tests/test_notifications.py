"""Virtual-time reminder policy, independent of the UI event loop."""
import unittest
from guard.notifications import NotificationState, fault_snapshot

FAULT={'proxy_https':('代理测试失败','模拟超时')}

class Clock:
    value = 0

    def __call__(self):
        return self.value

    def stamp(self):
        return f'T+{self.value}s'


class NotificationStateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.state = NotificationState(clock=self.clock, stamp=self.clock.stamp)

    def test_eight_hours_without_acknowledgement_delivers_once(self):
        delivered = 0
        for i in range(1920):
            self.clock.value = i * 15
            self.state.update_faults(FAULT)
            self.state.event('change.gateway', '网关变化', f'模拟变化 {i}')
            delivered += self.state.take_notification()
        self.assertEqual(delivered, 1)
        self.assertEqual(len(self.state.records), 2)
        self.assertEqual(self.state.records['proxy_https'].count, 1920)
        self.assertEqual(self.state.records['change.gateway'].message, '模拟变化 1919')
        self.assertEqual(self.state.unread_count, 2)

    def test_acknowledged_ongoing_fault_is_silent_past_cooldown(self):
        self.state.update_faults(FAULT)
        self.assertTrue(self.state.take_notification())
        self.state.acknowledge()
        self.clock.value = 10000
        self.state.update_faults(FAULT)
        self.assertFalse(self.state.take_notification())
        self.assertEqual(self.state.active_count, 1)
        self.assertEqual(self.state.unread_count, 0)

    def test_recovery_reoccurrence_waits_for_cooldown_then_delivers_once(self):
        self.state.update_faults(FAULT)
        self.assertTrue(self.state.take_notification())
        self.state.acknowledge()
        self.state.update_faults({})
        self.assertEqual(self.state.records['proxy_https'].status, 'recovered')
        self.clock.value = 30
        self.state.update_faults(FAULT)
        self.assertFalse(self.state.take_notification())
        self.clock.value = 120
        self.assertTrue(self.state.take_notification())
        self.assertFalse(self.state.take_notification())

    def test_recovered_pending_fault_is_not_replayed(self):
        self.state.event('change.node', '变化', '模拟')
        self.state.take_notification();self.state.acknowledge()
        self.clock.value = 10
        self.state.update_faults(FAULT)
        self.assertFalse(self.state.take_notification())
        self.state.update_faults({})
        self.clock.value = 500
        self.assertFalse(self.state.take_notification())
        self.assertFalse(self.state.pending)

    def test_invalidated_evidence_is_not_recovery(self):
        self.state.update_faults(FAULT)
        self.state.take_notification();self.state.acknowledge()
        self.state.update_faults({}, unconfirmed=('proxy_https',))
        self.assertEqual(self.state.records['proxy_https'].status, 'unconfirmed')
        self.clock.value = 500
        self.state.update_faults(FAULT)
        self.assertFalse(self.state.take_notification())
        self.assertTrue(self.state.records['proxy_https'].acknowledged)

    def test_changing_addresses_and_errors_use_stable_categories(self):
        for ip in ('192.0.2.1', '2001:db8::2'):
            snapshot = fault_snapshot({'faults': ['节点选路未经过 WLAN：'+ip]},
                                      dict(ok=False, message='模拟失败 '+ip))
            self.state.update_faults(snapshot)
            self.state.take_notification();self.state.acknowledge()
        self.assertEqual(set(self.state.records), {'route_not_wlan', 'proxy_https'})
        self.assertEqual(self.state.unread_count, 0)
        self.assertIn('2001:db8::2', self.state.records['route_not_wlan'].message)

    def test_faults_and_changes_are_batched_and_history_is_bounded(self):
        self.state.update_faults(FAULT)
        for i in range(1000):
            self.state.event(f'change.{i}', '变化', str(i))
        self.assertEqual(len(self.state.records), 50)
        self.assertLessEqual(len(self.state.pending), 50)
        self.assertIn('proxy_https', self.state.records)
        self.assertTrue(self.state.take_notification())
        self.assertFalse(self.state.take_notification())

    def test_manual_presentation_prevents_automatic_duplicate(self):
        self.state.update_faults(FAULT)
        self.state.mark_presented()
        self.clock.value = 1000
        self.state.update_faults(FAULT)
        self.assertFalse(self.state.take_notification())
