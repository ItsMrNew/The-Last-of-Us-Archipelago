import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_airhorn
import test_tracker_ui
from tlou_ap.coverage import Coverage
from tlou_ap.notifications import Toast, mission_lock_toast
from tlou_ap.preferences import DEFAULT_RUNTIME
from tlou_ap.deliveries import display_rows


class ReviewRegressionTests(unittest.TestCase):
    setup_horn = test_airhorn.AirhornTests.setup

    def test_three_timed_traps_with_native_reply_latency_keep_90s_and_five_second_cadence(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, _, adapter, _ = self.setup_horn(folder, count=3)
            pending = []
            times = []
            def pulse(receipt, instance, *, before_submit):
                if pending:
                    self.assertEqual(pending.pop(), receipt)
                    return 'applied'
                before_submit(); pending.append(receipt); times.append(adapter.clock)
                return 'pending'
            adapter.airhorn_pulse = pulse
            for clock in range(0, 90501, 500):
                adapter.clock = clock; horn.poll(adapter)
            self.assertEqual(horn.queued, 0)
            self.assertEqual(times, list(range(0, 90000, 5000)))

    def test_coverage_failed_write_does_not_claim_result_was_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            coverage = Coverage(Path(folder) / 'coverage.json', 'fixture')
            with patch('tlou_ap.coverage.atomic_json', side_effect=OSError('Disk full')):
                with self.assertRaises(OSError):
                    coverage.record('mission:0', 'Normal completion', 'Passed', 'Evidence')
            self.assertEqual(coverage.summary()['Passed'], 0)

    def test_refused_first_pulse_refunds_time_and_uncertain_does_not_skip_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, _, a, _ = self.setup_horn(folder, count=3)
            a.result = 'pending'; horn.poll(a)
            a.clock = 1000; a.result = 'not_applied'; horn.poll(a)
            self.assertEqual(horn.current[1]['elapsed'], 0)
            self.assertEqual(horn.timed_stack(), (90, 3))
            a.result = 'pending'; horn.poll(a)
            a.clock = 32000; a.result = 'uncertain'; horn.poll(a)
            self.assertEqual(horn.current[0], '0'); self.assertEqual(horn.current[1]['state'], 'held')
            calls = len(a.calls); horn.poll(a); self.assertEqual(len(a.calls), calls)

    def test_late_reply_carries_time_across_boundary_without_replaying_blast(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, a, _ = self.setup_horn(folder, count=3)
            horn.poll(a); a.clock = 29000; a.result = 'pending'; horn.poll(a)
            a.clock = 31000; a.result = 'applied'; horn.poll(a)
            self.assertEqual(horn.current[1]['carry_ms'], 1000)
            # Restore journal with a native clock baseline; saved carry survives.
            from tlou_ap.airhorn import Airhorn
            restored = Airhorn(); restored.bind(session); restored.poll(a)
            self.assertEqual(restored.current[0], '1')
            self.assertEqual(restored.timed_stack(), (59, 2))

    def test_disconnected_rows_are_copied_and_never_claim_active_delivery(self):
        raw = {'connected': False, 'deliveries': [
            {'key': '0', 'item': 'Airhorn Trap', 'state': 'Active', 'reason': 'Running', 'source': 'Peer'},
            {'key': '1', 'item': 'Health Kit', 'state': 'Delivered', 'reason': 'Confirmed', 'source': 'Peer'}]}
        rows = display_rows(raw)
        self.assertEqual(rows[0]['state'], 'Waiting')
        self.assertIn('Disconnected', rows[0]['reason'])
        self.assertEqual(rows[1]['state'], 'Delivered')
        self.assertEqual(raw['deliveries'][0]['state'], 'Active')

    def test_alpha13_journal_upgrade_keeps_completed_pulses_and_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, a, _ = self.setup_horn(folder, count=1)
            horn.poll(a); a.clock = 2000; horn.poll(a)
            old = json.loads(horn.path.read_text()); old['version'] = 2
            for entry in old['items'].values():
                del entry['pulse_at']; del entry['carry_ms']
            horn.path.write_text(json.dumps(old))
            from tlou_ap.airhorn import Airhorn
            restored = Airhorn(); restored.bind(session); restored.poll(a)
            self.assertEqual(restored.data['version'], 3)
            self.assertEqual(restored.timed_stack(), (28, 1))
            self.assertEqual(len(a.calls), 1)

    def test_single_blast_splits_timed_stack_and_each_receipt_only_runs_once(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, _, a, _ = self.setup_horn(folder, count=3)
            horn.synchronize(); horn.data['items']['1']['mode'] = 'single_blast'; horn.save()
            self.assertEqual(horn.timed_stack(), (30, 1))
            for clock in range(0, 30001, 5000):
                a.clock = clock; horn.poll(a)
            self.assertEqual(horn.current[0], '2')
            self.assertEqual(horn.timed_stack(), (30, 1))
            horn.poll(a)
            for clock in range(35000, 60001, 5000):
                a.clock = clock; horn.poll(a)
            self.assertEqual(horn.queued, 0)
            self.assertEqual(len(a.calls), 13)
            self.assertEqual(len(set(a.calls)), 13)


class ReviewUITests(unittest.TestCase):
    setUp = test_tracker_ui.TrackerUITests.setUp
    close = test_tracker_ui.TrackerUITests.close


    def test_disconnected_effective_settings_are_not_reported_as_live(self):
        self.app.show_tools(); tools = self.app.tools_window; self.root.update()
        self.assertIn('Disconnected', tools.effective.cget('text'))
        tools.update({'connected': True, 'death_link': True, 'slot_settings': {'schema_version': 1}})
        self.assertIn('Enabled', tools.effective.cget('text'))
        self.assertIn('0%', tools.effective.cget('text'))

    def test_failed_settings_save_keeps_running_preferences_unchanged(self):
        previous = dict(self.app.notification_settings)
        with patch('tlou_ap.launcher.atomic_json', side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):
                self.app.apply_preferences({**previous, 'volume': 0}, {**DEFAULT_RUNTIME, 'death_link': 'enabled'})
        self.assertEqual(self.app.notification_settings, previous)
        self.assertEqual(self.app.runtime_settings, DEFAULT_RUNTIME)
        self.assertTrue(self.app.actions.empty())


    def test_long_overlay_stack_stays_inside_720p_and_hidden_cards_keep_their_time(self):
        overlay = self.app.overlay
        positions = []
        overlay.api.focused_rect = lambda pid: (0, 0, 1280, 720, 1)
        overlay.api.position = lambda hwnd, x, y, width, height: positions.append((x, y, width, height)) or True
        now = [0.0]; overlay.queue.clock = lambda: now[0]; overlay.queue.last_tick = 0
        overlay.state(1, status_card=mission_lock_toast('Beyond the Wall'),
                      trap_card=Toast('TRAP', 'Airhorn paused — 90s remaining', 'Waiting for controllable gameplay.', '', '#FA8072'))
        for i in range(2):
            overlay.add(Toast('ITEM RECEIVED', ('Long item name ' * 12)[:180],
                ('From another player ' * 9)[:180], ('Long location name ' * 10)[:180], '#AF99EF'))
        overlay.refresh(); self.root.update_idletasks()
        _, y, _, height = positions[-1]
        self.assertLessEqual(y + height, 720)
        self.assertLess(overlay.displayed_transfers, 2)
        hidden = overlay.queue.active[1][0]
        now[0] = 4; overlay.refresh()
        self.assertEqual(next(age for toast, age in overlay.queue.active if toast is hidden), 0)
