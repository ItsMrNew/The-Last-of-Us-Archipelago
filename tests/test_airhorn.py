import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from tlou_ap.airhorn import Airhorn
from tlou_ap.catalog import AIRHORN, Config, ITEM_IDS
from tlou_ap.native.airhorn import NativeAirhorn
from tlou_ap.session import ReceivedItem, Session


class Adapter:
    def __init__(self):
        self.ready, self.clock, self.instance = True, 0, 'game-1'
        self.result, self.calls = 'applied', []

    def airhorn_status(self):
        return {'ready': self.ready, 'clock': self.clock, 'instance': self.instance}

    def airhorn_pulse(self, receipt, instance, *, before_submit):
        if instance and instance != self.instance:
            return 'uncertain'
        before_submit()
        self.calls.append(receipt)
        return self.result


class AirhornTests(unittest.TestCase):
    def setup(self, folder, *, timed=True, count=2):
        config = Config(airhorn_trap_percentage=10, airhorn_mode='timed' if timed else 'single_blast',
                        airhorn_duration=30)
        session = Session(folder, 'seed', 0, 1, 'run', config)
        session.record_inventory([ReceivedItem(ITEM_IDS[AIRHORN], i, 1, 4) for i in range(count)])
        messages = []
        horn = Airhorn(messages.append); horn.bind(session)
        return horn, session, Adapter(), messages

    def test_modes_and_old_seed_compatibility(self):
        for config in (Config(), Config(death_link=True), Config(airhorn_trap_percentage=10),
                       Config(death_link=True, airhorn_trap_percentage=100, airhorn_mode='timed', airhorn_duration=120)):
            self.assertEqual(config, Config.from_slot_data(config.slot_data(), [c.id for c in config.active_checks]))
        self.assertEqual(Config().slot_data()['schema_version'], 1)
        for values in ({'airhorn_trap_percentage': True}, {'airhorn_duration': 29},
                       {'airhorn_duration': 121}, {'airhorn_mode': 'forever'}, {'airhorn_trap_percentage': 101}):
            with self.assertRaises(ValueError):
                Config(**values)

    def test_single_blast_queues_and_reconnect_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, a, messages = self.setup(folder, timed=False, count=1)
            a.ready = False; horn.poll(a)
            self.assertEqual(horn.queued, 1); self.assertEqual(a.calls, [])
            restored = Airhorn(messages.append); restored.bind(session)
            a.ready = True; restored.poll(a)
            self.assertEqual(restored.queued, 0); self.assertEqual(len(a.calls), 1)
            restored.bind(session); restored.poll(a)
            self.assertEqual(len(a.calls), 1)
            self.assertEqual(messages[0].colour, '#FA8072'); self.assertTrue(messages[0].sound)

    def test_timed_noise_follows_playable_clock_and_runs_sequentially(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, _, a, _ = self.setup(folder)
            horn.poll(a)
            for clock in (1000, 4999):
                a.clock = clock; horn.poll(a)
            self.assertEqual(len(a.calls), 1)
            a.clock = 5000; horn.poll(a); self.assertEqual(len(a.calls), 2)
            a.ready = False
            for _ in range(10): horn.poll(a)  # Native playable clock is frozen.
            self.assertEqual(horn.current[1]['elapsed'], 5000)
            self.assertIn('paused', horn.card().item)
            a.ready = True
            for clock in range(10000, 30001, 5000):
                a.clock = clock; horn.poll(a)
            self.assertEqual(len(a.calls), 7); self.assertEqual(horn.queued, 1)
            horn.poll(a); self.assertEqual(len(a.calls), 7)
            self.assertEqual(horn.current[1]['elapsed'], 0)

    def test_restart_preserves_remaining_duration_without_repeating_first_blast(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, a, _ = self.setup(folder, count=1)
            horn.poll(a); a.clock = 4000; horn.poll(a)
            restored = Airhorn(); restored.bind(session)
            a.instance, a.clock = 'game-2', 0; restored.poll(a)
            self.assertEqual(len(a.calls), 1)
            a.clock = 1000; restored.poll(a)
            self.assertEqual(len(a.calls), 2)
            self.assertEqual(restored.current[1]['elapsed'], 5000)

    def test_uncertain_pulse_holds_queue_and_explicit_retirement_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, a, _ = self.setup(folder)
            a.result = 'pending'; horn.poll(a)
            self.assertEqual(json.loads(horn.path.read_text())['items']['0']['state'], 'pending')
            restored = Airhorn(); restored.bind(session)
            a.instance = 'game-2'; restored.poll(a)
            self.assertEqual(restored.current[1]['state'], 'held')
            for _ in range(3): restored.poll(a)
            self.assertEqual(len(a.calls), 1)
            self.assertEqual(restored.retire_held(), 1)
            a.result = 'applied'; restored.poll(a)
            self.assertEqual(len(a.calls), 2)

    def test_refused_pulse_retains_receipt_and_timer(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, _, a, _ = self.setup(folder, count=1)
            a.result = 'not_applied'; horn.poll(a)
            self.assertEqual(horn.current[1]['state'], 'queued')
            a.result = 'applied'; horn.poll(a)
            self.assertEqual(a.calls[0], a.calls[1])
            self.assertEqual(horn.current[1]['pulses'], 1)

    def test_inventory_replacement_and_bad_journal_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, a, _ = self.setup(folder)
            horn.poll(a); session.data['received'][0]['location'] = 999
            with self.assertRaises(ValueError): horn.poll(a)
            horn.data['items']['0']['elapsed'] = -1
            with self.assertRaises(ValueError): horn.save()

    def test_transport_reserves_before_effect_and_recovers_read_only(self):
        calls = []
        bridge = SimpleNamespace(shared=SimpleNamespace(airhorn_ready=1, current=4), command_busy=False,
            begin_command=lambda *args: calls.append(args) or 1, command_result=lambda seq: 1)
        native = NativeAirhorn(bridge, 'game')
        def reserve(): self.assertEqual(calls, [])
        self.assertEqual(native.pulse('receipt', None, before_submit=reserve, can_submit=True), 'pending')
        self.assertEqual(calls[0][:2], (6, 1 | 4 << 8))
        self.assertEqual(native.pulse('receipt', 'game', before_submit=reserve, can_submit=True), 'applied')
        native = NativeAirhorn(bridge, 'game')
        self.assertEqual(native.pulse('receipt', 'game', before_submit=reserve, can_submit=True), 'pending')
        self.assertEqual(calls[1][:2], (101, 6))
        self.assertEqual(native.pulse('receipt', 'game', before_submit=reserve, can_submit=True), 'applied')
        self.assertEqual(native.pulse('receipt', 'old-game', before_submit=reserve, can_submit=True), 'uncertain')

    def test_busy_transport_does_not_submit_or_spend_queued_trap(self):
        bridge = SimpleNamespace(command_busy=True)
        native = NativeAirhorn(bridge, 'game')
        def unexpected(): self.fail('Reserved without mailbox access')
        self.assertEqual(native.pulse('x', None, before_submit=unexpected, can_submit=True), 'not_applied')
        self.assertEqual(native.pulse('x', 'game', before_submit=unexpected, can_submit=True), 'pending')


if __name__ == '__main__': unittest.main()
