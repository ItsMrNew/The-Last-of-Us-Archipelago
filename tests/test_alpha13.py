import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import wave
from array import array
from unittest.mock import patch

import test_airhorn
from test_deathlink import DeathAdapter, bounced
import test_tracker_ui
from tlou_ap.airhorn import Airhorn
from tlou_ap.catalog import AIRHORN, ITEM_IDS, Config
from tlou_ap.client import Client
from tlou_ap.coverage import Coverage, targets, diagnostic_report
from tlou_ap.deliveries import delivery_snapshot
from tlou_ap.notifications import Toast, ToastQueue, validate_settings
from tlou_ap.preferences import DEFAULT_RUNTIME, DEFAULT_SEED, seed_yaml, validate_runtime
from tlou_ap.session import ReceivedItem
from tlou_ap.sound import scaled_wav


class StackingTests(unittest.TestCase):
    setup = test_airhorn.AirhornTests.setup

    def test_three_timed_traps_make_90s_and_18_unique_blasts_with_no_boundary_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, adapter, _ = self.setup(folder, count=3)
            horn.synchronize()
            self.assertEqual(horn.timed_stack(), (90, 3))
            self.assertIn('90s', horn.card().item)
            for clock in range(0, 90001, 500):
                adapter.clock = clock; horn.poll(adapter)
                if clock in (30000, 60000):
                    self.assertEqual(horn.current[1]['elapsed'], 0)
                    self.assertEqual(horn.current[1]['pulses'], 1)
            self.assertEqual(horn.queued, 0)
            self.assertEqual(len(adapter.calls), 18)
            self.assertEqual(len(set(adapter.calls)), 18)
            horn.bind(session); horn.poll(adapter)
            self.assertEqual(len(adapter.calls), 18)

    def test_stack_pause_restart_new_items_and_preference_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, a, _ = self.setup(folder, count=1)
            horn.poll(a); a.clock = 15000; horn.poll(a)
            horn.configure({**DEFAULT_RUNTIME, 'airhorn_mode': 'timed', 'airhorn_duration': 120})
            items = [ReceivedItem.parse(x) for x in session.data['received']]
            session.record_inventory([*items, ReceivedItem(ITEM_IDS[AIRHORN], 99, 2, 4)])
            horn.poll(a)
            self.assertEqual(horn.timed_stack(), (135, 2))
            a.ready = False
            for _ in range(5): horn.poll(a)
            self.assertEqual(horn.timed_stack(), (135, 2))
            saved = horn.data
            resumed = Airhorn(); resumed.bind(session)
            self.assertEqual(resumed.data, saved)
            self.assertEqual(resumed.timed_stack(), (135, 2))
            a.instance, a.clock = 'new-game', 0; resumed.poll(a)
            self.assertEqual(resumed.timed_stack(), (135, 2))

    def test_legacy_journal_migrates_without_retiming_and_held_breaks_stack(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, a, _ = self.setup(folder, count=3)
            horn.poll(a)
            old = json.loads(horn.path.read_text()); old['version'] = 1
            for entry in old['items'].values():
                del entry['mode']; del entry['duration']
            horn.path.write_text(json.dumps(old))
            restored = Airhorn(); restored.configure({**DEFAULT_RUNTIME, 'airhorn_mode': 'timed', 'airhorn_duration': 120})
            restored.bind(session)
            self.assertEqual(restored.timed_stack(), (90, 3))
            restored.data['items']['1']['state'] = 'held'; restored.save()
            self.assertEqual(restored.timed_stack(), (30, 1))


class PreferenceProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_deathlink_enable_disable_yaml_and_waiting_death_survives(self):
        class Socket:
            def __init__(self): self.packets = []
            async def send(self, text): self.packets.extend(json.loads(text))
        with tempfile.TemporaryDirectory() as folder:
            a, socket, config = DeathAdapter(), Socket(), Config()
            client = Client('Me', folder, a); client.seed = 'seed'
            await client.handle(socket, dict(cmd='Connected', team=0, slot=1, checked_locations=[],
                missing_locations=[c.id for c in config.active_checks], slot_data=config.slot_data()))
            self.assertFalse(client.deathlink.enabled)
            client.set_preferences({**DEFAULT_RUNTIME, 'death_link': 'enabled'}); await client.poll(socket)
            self.assertTrue(a.enabled)
            self.assertEqual(socket.packets[-1]['cmd'], 'LocationChecks')
            self.assertIn({'cmd': 'ConnectUpdate', 'tags': ['AP', 'DeathLink']}, socket.packets)
            await client.handle(socket, bounced())
            receipt = client.deathlink.pending['receipt']
            client.set_preferences({**DEFAULT_RUNTIME, 'death_link': 'disabled'}); await client.poll(socket)
            self.assertFalse(a.enabled); self.assertEqual(client.deathlink.pending['receipt'], receipt)
            self.assertEqual(socket.packets[-1], {'cmd': 'ConnectUpdate', 'tags': ['AP']})
            client.set_preferences(DEFAULT_RUNTIME); await client.poll(socket)
            self.assertFalse(a.enabled)
            client.set_preferences({**DEFAULT_RUNTIME, 'death_link': 'enabled'})
            a.outcome = 'submitted'; await client.poll(socket); await client.poll(socket)
            self.assertEqual(a.deaths, [receipt])
            a.remote = True; await client.poll(socket)
            self.assertEqual(client.deathlink.state, 'idle')
            self.assertFalse(client.session.config.death_link)


class DataTests(unittest.TestCase):
    def test_five_notifications_show_two_then_two_then_one_and_pause_offscreen(self):
        clock = [0]
        queue = ToastQueue(lambda: clock[0])
        items = [Toast('ITEM', str(i), '', '', '#fff') for i in range(5)]
        for item in items: queue.add(item)
        self.assertEqual(queue.tick(True), tuple(items[:2]))
        clock[0] = 4; queue.tick(True); queue.tick(False)
        clock[0] = 100; self.assertEqual(queue.tick(True), tuple(items[:2]))
        clock[0] = 104; self.assertEqual(queue.tick(True), tuple(items[2:4]))
        clock[0] = 112; self.assertEqual(queue.tick(True), tuple(items[4:]))
        clock[0] = 120; self.assertEqual(queue.tick(True), ())

    def test_volume_scales_samples_without_touching_source_and_zero_is_silent(self):
        source = Path(__file__).parents[1] / 'tlou_ap/data/airhorn.wav'
        original = source.read_bytes()
        with wave.open(str(source), 'rb') as stream: peak = max(array('h', stream.readframes(stream.getnframes())))
        with tempfile.TemporaryDirectory() as folder:
            for volume in (0, 50, 100):
                target = Path(folder) / f'{volume}.wav'; scaled_wav(source, target, volume)
                with wave.open(str(target), 'rb') as stream:
                    scaled = max(array('h', stream.readframes(stream.getnframes())))
                self.assertAlmostEqual(scaled, peak * volume / 100, delta=1)
        self.assertEqual(source.read_bytes(), original)

    def test_yaml_quotes_name_and_validates_logic_and_no_live_percentage(self):
        import yaml
        parsed = yaml.safe_load(seed_yaml('Tester: #1', {**DEFAULT_SEED, 'airhorn_trap_percentage': 65}))
        self.assertEqual(parsed['name'], 'Tester: #1')
        self.assertEqual(parsed['The Last of Us Part I']['airhorn_trap_percentage'], 65)
        with self.assertRaises(ValueError): validate_runtime({**DEFAULT_RUNTIME, 'airhorn_trap_percentage': 20})
        with self.assertRaises(ValueError):
            seed_yaml('Tester', {**DEFAULT_SEED, 'starting_chapters': 1, 'mission_checks': False, 'chapter_checks': False})
        for position in ('top_left', 'top_right', 'bottom_left', 'bottom_right'):
            self.assertEqual(validate_settings({'scope': 'you', 'seconds': 12, 'position': position, 'volume': 33})['position'], position)

    def test_coverage_persistence_build_guard_no_auto_pass_and_export_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'coverage.json'; store = Coverage(path, 'build')
            self.assertEqual(len(targets()), 182)
            self.assertEqual(store.summary()['Passed'], 0)
            with self.assertRaises(ValueError): store.record('mission:0', 'Normal completion', 'Passed', '')
            store.record('mission:0', 'Normal completion', 'Passed', 'Observed completion after reload')
            resumed = Coverage(path, 'build'); self.assertEqual(resumed.summary()['Passed'], 1)
            with self.assertRaises(ValueError): Coverage(path, 'different-build')
            report = diagnostic_report(store, {'password': 'SECRET', 'server': 'PRIVATE', 'checks': 8})
            self.assertNotIn('SECRET', json.dumps(report)); self.assertNotIn('PRIVATE', json.dumps(report))
            self.assertEqual(report['runtime']['checks'], 8)

    def test_queue_rows_explain_full_inventory_held_and_disabled_death(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, _, _ = test_airhorn.AirhornTests.setup(self, folder, count=1)
            session.record_inventory([ReceivedItem.parse(session.data['received'][0]),
                ReceivedItem(ITEM_IDS['Health Kit'], 99, 2, 0), ReceivedItem(ITEM_IDS['Shiv'], 100, 2, 0)])
            session.reserve_supply(2); session.resolve_supply(2, 'uncertain')
            horn.synchronize()
            client = Client('Me', folder, DeathAdapter()); client.session = session; client.airhorn = horn
            client.connected = client.inventory.synchronized = True
            client.deathlink.bind(session); client.deathlink.configure(True)
            client.deathlink.receive(bounced(), 'Me'); client.deathlink.configure(False)
            rows = delivery_snapshot(client, {'supplies': {ITEM_IDS['Health Kit']: 'Medkit inventory full (3/3)'}})
            self.assertIn('full', rows[1]['reason']); self.assertEqual(rows[2]['state'], 'Held')
            self.assertIn('preserved', rows[-1]['reason'])


class ToolsUITests(unittest.TestCase):
    setUp = test_tracker_ui.TrackerUITests.setUp
    close = test_tracker_ui.TrackerUITests.close
    def test_tabs_settings_and_delivery_history(self):
        self.app.slot.set('Fixture Player')
        self.app.show_tools(); tools = self.app.tools_window; self.root.update()
        self.assertEqual(len(tools.tabs.tabs()), 2)
        tools.death.set('Enabled'); tools.mode.set('Timed'); tools.duration.set(90)
        tools.volume.set(37); tools.position.set('Bottom Left'); tools.seconds.set(12)
        tools.apply_settings()
        saved = json.loads(self.app.settings_path.read_text())
        self.assertEqual(saved['notifications']['volume'], 37)
        self.assertEqual(saved['notifications']['position'], 'bottom_left')
        self.assertEqual(saved['gameplay']['death_link'], 'enabled')
        self.app.last_status = {'connected': True, 'deliveries': [
            {'key': '0', 'item': 'Health Kit', 'source': 'Test', 'state': 'Queued', 'reason': 'Inventory full'},
            {'key': '1', 'item': 'Ammo Supply', 'source': 'Test', 'state': 'Delivered', 'reason': 'Confirmed'}],
            'observed_missions': [0], 'observed_checks': []}
        tools.update(self.app.last_status); self.root.update()
        self.assertEqual(len(tools.delivery_table.get_children()), 1)
        tools.history.set(True); tools.render_deliveries(force=True)
        self.assertEqual(len(tools.delivery_table.get_children()), 2)
        self.assertFalse(self.callbacks)
