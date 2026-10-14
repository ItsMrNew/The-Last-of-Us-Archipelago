import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tlou_ap.catalog import Config, ITEM_IDS, RESOURCE_SUPPLIES, TIMED_TRAPS
from tlou_ap.native.adapter import resource_wait_reason
from tlou_ap.session import Session, ReceivedItem
from tlou_ap.timed_effects import TimedEffects


class Adapter:
    def __init__(self):
        self.clocks = [0, 0]
        self.instance = 'process-one'
        self.ready = True
        self.leases = []

    def timed_effect_status(self):
        return dict(instance=self.instance, clocks=self.clocks[:], ready=self.ready, supported=3)

    def set_timed_effects(self, remaining):
        self.leases.append(remaining)


class ResourceEffectTests(unittest.TestCase):
    def setup_effects(self, directory):
        session = Session(directory, 'seed', 0, 1, 'run', Config())
        session.record_inventory([ReceivedItem(ITEM_IDS[name], i, 1, 4)
                                  for i, name in enumerate([TIMED_TRAPS[0]] * 3 + [TIMED_TRAPS[1]])])
        effects = TimedEffects()
        effects.bind(session)
        return session, effects, Adapter()

    def test_new_ids_do_not_reuse_tools_and_old_schemas_round_trip(self):
        self.assertEqual([ITEM_IDS[n] for n in RESOURCE_SUPPLIES + TIMED_TRAPS], list(range(19710006, 19710011)))
        for config in (Config(), Config(death_link=True), Config(airhorn_trap_percentage=10),
                       Config(resource_supplies=True, shaky_hands_percentage=20, faulty_flashlight_percentage=10)):
            self.assertEqual(Config.from_slot_data(config.slot_data(), [c.id for c in config.active_checks]), config)
        self.assertEqual(Config().slot_data()['schema_version'], 1)
        self.assertEqual(Config(airhorn_trap_percentage=10).slot_data()['schema_version'], 3)
        for values in ({'resource_supplies': 1}, {'shaky_hands_percentage': True},
                       {'faulty_flashlight_percentage': -1},
                       {'airhorn_trap_percentage': 80, 'shaky_hands_percentage': 21}):
            with self.assertRaises(ValueError):
                Config(**values)

    def test_resources_wait_at_cap_and_accept_partial_cache_space(self):
        status = {'resources': [12] * 6 + [9999] * 2, 'resource_max': [12] * 6 + [9999] * 2}
        for name in RESOURCE_SUPPLIES:
            self.assertEqual(resource_wait_reason(name, status), 'Resource inventory full')
        status['resources'][2] = 11
        self.assertEqual(resource_wait_reason('Crafting Cache', status), '')
        status['resource_max'][4] = 0
        self.assertIn('supported', resource_wait_reason('Crafting Cache', status))
        self.assertIn('supported', resource_wait_reason('Workbench Parts', {}))

    def test_same_traps_stack_different_traps_overlap_and_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            session, effects, adapter = self.setup_effects(folder)
            effects.poll(adapter)
            self.assertEqual(adapter.leases[-1], [90000, 30000])
            adapter.clocks = [35000, 30000]
            effects.poll(adapter)
            self.assertEqual(adapter.leases[-1], [55000, 0])
            self.assertEqual(effects.data['items']['0']['elapsed'], 30000)
            self.assertEqual(effects.data['items']['1']['elapsed'], 5000)
            adapter.ready = False
            effects.poll(adapter)
            self.assertFalse(effects.ready)
            self.assertEqual(adapter.leases[-1], [55000, 0])
            self.assertEqual(effects.queued, 2)
            adapter.ready = True
            adapter.clocks[0] = 90000
            effects.poll(adapter)
            self.assertEqual(effects.queued, 0)
            self.assertEqual(adapter.leases[-1], [0, 0])
            self.assertIsNone(effects.card())

    def test_client_reconnect_counts_native_tail_once_and_game_restart_preserves_remaining(self):
        with tempfile.TemporaryDirectory() as folder:
            session, effects, adapter = self.setup_effects(folder)
            effects.poll(adapter)
            adapter.clocks = [12000, 12000]
            effects.poll(adapter)
            restored = TimedEffects(); restored.bind(session)
            adapter.clocks = [13000, 13000]
            restored.poll(adapter)
            self.assertEqual(adapter.leases[-1], [77000, 17000])
            restored.poll(adapter)
            self.assertEqual(adapter.leases[-1], [77000, 17000])
            adapter.instance = 'process-two'; adapter.clocks = [0, 0]
            restored.poll(adapter)
            self.assertEqual(adapter.leases[-1], [77000, 17000])

    def test_journal_failure_never_renews_effect_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            session, effects, adapter = self.setup_effects(folder)
            effects.synchronize()
            with patch('tlou_ap.timed_effects.atomic_json', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    effects.poll(adapter)
            self.assertEqual(adapter.leases, [])

    def test_wrong_run_or_invalid_elapsed_is_rejected_before_effects(self):
        with tempfile.TemporaryDirectory() as folder:
            session, effects, adapter = self.setup_effects(folder)
            effects.poll(adapter)
            data = json.loads(effects.path.read_text())
            data['items']['0']['elapsed'] = -1
            effects.path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                TimedEffects().bind(session)
            data['items']['0']['elapsed'] = 0
            data['identity'] = {'wrong': 'run'}
            effects.path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                TimedEffects().bind(session)

    def test_death_clears_active_stacks_and_reconnect_cannot_restore_them(self):
        with tempfile.TemporaryDirectory() as folder:
            session, effects, adapter = self.setup_effects(folder)
            effects.poll(adapter)
            self.assertEqual(effects.clear_on_death('game:1', adapter), 4)
            self.assertEqual(adapter.leases[-1], [0, 0])
            self.assertIsNone(effects.card())
            restored = TimedEffects(); restored.bind(session); restored.poll(adapter)
            self.assertEqual(restored.queued, 0)
            self.assertEqual(restored.clear_on_death('game:1', adapter), 0)

    def test_death_preserves_traps_never_started_in_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            session, effects, adapter = self.setup_effects(folder)
            adapter.ready = False; effects.poll(adapter)
            self.assertEqual(effects.clear_on_death('game:1', adapter), 0)
            self.assertEqual(effects.queued, 4)
            adapter.ready = True; effects.poll(adapter)
            self.assertEqual(effects.clear_on_death('game:2', adapter), 4)

    def test_native_clock_start_between_polls_is_not_missed(self):
        with tempfile.TemporaryDirectory() as folder:
            session, effects, adapter = self.setup_effects(folder)
            adapter.ready = False; effects.poll(adapter)
            adapter.clocks = [500, 0]
            self.assertEqual(effects.clear_on_death('game:1', adapter), 3)
            self.assertEqual(effects.queued, 1)
            self.assertEqual(effects.remaining(TIMED_TRAPS[1]), 30000)

    def test_death_journal_failure_is_retryable(self):
        with tempfile.TemporaryDirectory() as folder:
            session, effects, adapter = self.setup_effects(folder)
            effects.poll(adapter)
            with patch('tlou_ap.timed_effects.atomic_json', side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError): effects.clear_on_death('game:1', adapter)
            self.assertEqual(effects.queued, 4)
            self.assertEqual(effects.clear_on_death('game:1', adapter), 4)
