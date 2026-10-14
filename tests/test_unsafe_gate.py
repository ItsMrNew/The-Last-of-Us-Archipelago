import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tlou_ap.native.adapter import NativeAdapter
from tlou_ap.native.bridge import validate_gate_build
from tools.offline_lab import Lab


class UnsafeGateTests(unittest.TestCase):
    def test_live_validated_alpha_gate_is_admitted_but_a_changed_build_is_not(self):
        validate_gate_build(0x616c0b7c5e8cf421)
        validate_gate_build(0x99d6c0864e316360)
        with self.assertRaisesRegex(ValueError, 'awaiting live validation'):
            validate_gate_build(0x616c0b7c5e8cf420)

    def test_menu_freezing_prototype_and_unvalidated_builds_are_not_campaign_gates(self):
        for experimental in (False, True):
            with self.assertRaisesRegex(ValueError, 'froze both gameplay and menu'):
                validate_gate_build(0xc2af8c72f3e532ea, experimental=experimental)
            with self.assertRaisesRegex(ValueError, 'stalled Continue'):
                validate_gate_build(0x6c8f1b0e5a6d256c, experimental=experimental)
        with self.assertRaisesRegex(ValueError, 'awaiting live validation'):
            validate_gate_build(0x12345678)
        validate_gate_build(0x12345678, experimental=True)

    def bridge(self):
        return Mock(manifest={'build_id':0x0ff9de8113ded92c})

    def test_real_run_rejects_failed_build_before_injection_or_ledger_creation(self):
        bridge = self.bridge()
        with tempfile.TemporaryDirectory() as folder, patch('tlou_ap.native.adapter.Bridge', return_value=bridge):
            path = Path(folder) / 'runs/run.json'
            with self.assertRaisesRegex(ValueError, 'Mission locking is disabled'):
                NativeAdapter(123, folder, path)
            self.assertFalse(path.exists())
        bridge.attach.assert_not_called()
        bridge.close.assert_called_once_with()

    def test_lab_cannot_arm_failed_build(self):
        lab = Lab.__new__(Lab)
        lab.bridge = self.bridge()
        lab.bridge.shared = SimpleNamespace(allowed=(1 << 29) - 1)
        lab.hold = lab.hold_started = None
        lab.log, lab.publish_gate = Mock(), Mock()
        lab.arm()
        self.assertIsNone(lab.hold)
        self.assertEqual(lab.bridge.shared.allowed, (1 << 29) - 1)
        lab.publish_gate.assert_not_called()
