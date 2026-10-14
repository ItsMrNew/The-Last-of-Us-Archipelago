import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from tools.offline_lab import Lab, HOLD_SECONDS


class HoldTimerTests(unittest.TestCase):
    def lab(self):
        lab = Lab.__new__(Lab)
        lab.bridge = SimpleNamespace(shared=SimpleNamespace(pending=0, blocked=0))
        lab.hold, lab.hold_started = 3, None
        lab.log, lab.release = Mock(), Mock()
        return lab

    def test_full_three_minutes_from_actual_matching_block(self):
        lab = self.lab()
        lab.tick_gate(1000)
        self.assertIsNone(lab.hold_started)
        lab.bridge.shared.pending, lab.bridge.shared.blocked = 1, 4
        lab.tick_gate(2000)
        self.assertEqual(lab.remaining_seconds(2000), 180)
        lab.tick_gate(2179.999)
        lab.release.assert_not_called()
        self.assertEqual(lab.remaining_seconds(2179.999), 1)
        lab.tick_gate(2180)
        lab.release.assert_called_once_with()
        self.assertEqual(HOLD_SECONDS, 180)

    def test_unrelated_pending_start_does_not_start_timer(self):
        lab = self.lab()
        lab.bridge.shared.pending, lab.bridge.shared.blocked = 1, 5
        lab.tick_gate(1000)
        self.assertIsNone(lab.remaining_seconds(1000))
        lab.release.assert_not_called()

    def test_cancelled_start_gets_full_duration_on_retry(self):
        lab = self.lab()
        lab.bridge.shared.pending, lab.bridge.shared.blocked = 1, 4
        lab.tick_gate(1000)
        lab.bridge.shared.pending = 0
        lab.tick_gate(1100)
        self.assertIsNone(lab.remaining_seconds(1100))
        lab.bridge.shared.pending = 1
        lab.tick_gate(1500)
        self.assertEqual(lab.remaining_seconds(1500), 180)
        lab.release.assert_not_called()


class QueuedAmmoTests(unittest.TestCase):
    def lab(self):
        lab = Lab.__new__(Lab)
        lab.bridge = SimpleNamespace(command_busy=False, shared=SimpleNamespace(current=3, pending=0))
        lab.pending_command = None
        lab.queued_ammo = (3, float('inf'))
        lab.log = Mock()
        lab.reward = Mock()
        return lab

    def test_waits_for_drawn_weapon_and_submits_only_once(self):
        lab = self.lab()
        supplies = dict(player=42, weapon=0, ammo=-1)
        lab.deliver_queued_ammo(supplies)
        lab.reward.assert_not_called()
        supplies.update(weapon=43, ammo=5)
        lab.bridge.command_busy = True
        lab.deliver_queued_ammo(supplies)
        lab.reward.assert_not_called()
        lab.bridge.command_busy = False
        lab.deliver_queued_ammo(supplies)
        lab.deliver_queued_ammo(supplies)
        lab.reward.assert_called_once_with(1)
        self.assertIsNone(lab.queued_ammo)

    def test_mission_change_or_timeout_cancels_delivery(self):
        for mission, deadline in ((4, float('inf')), (3, 0)):
            with self.subTest(mission=mission, deadline=deadline):
                lab = self.lab()
                lab.queued_ammo = (mission, deadline)
                lab.deliver_queued_ammo(dict(player=42, weapon=43, ammo=5))
                lab.reward.assert_not_called()
                self.assertIsNone(lab.queued_ammo)
