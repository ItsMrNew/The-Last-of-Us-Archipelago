from types import SimpleNamespace
import unittest

from tlou_ap.catalog import ITEM_IDS
from tlou_ap.native.adapter import NativeAdapter


class EffectContextTests(unittest.TestCase):
    def test_ammo_wait_reason_reports_draw_requirement_and_total_threshold(self):
        self.shared.current = 4; self.shared.allowed = 8
        supply = {'ready': True, 'shiv_max': 3, 'shivs': 3, 'kit_max': 3, 'health_kits': 3,
                  'weapon': 0, 'weapons': [{'weapon': 2, 'ammo_sid': 'b4ce74acb1317617',
                                           'ammo': 12, 'maximum': 20}]}
        self.adapter.bridge.supplies = lambda: supply
        ammo = ITEM_IDS['Ammo Supply']
        self.assertIn('Draw a weapon', self.adapter.delivery_context()['supplies'][ammo])
        supply.update(weapon=2, ammo_sid='b4ce74acb1317617', ammo=12)
        self.assertIn('12/20', self.adapter.delivery_context()['supplies'][ammo])
        self.assertIn('50% or less', self.adapter.delivery_context()['supplies'][ammo])
        supply['ammo'] = supply['weapons'][0]['ammo'] = 10
        self.assertIn('Ready;', self.adapter.delivery_context()['supplies'][ammo])

    def setUp(self):
        self.adapter = NativeAdapter.__new__(NativeAdapter)
        self.adapter.compatibility_error = ''
        self.adapter.ledger = SimpleNamespace(data={'started': True})
        self.shared = SimpleNamespace(current=1, allowed=1, blocked=0, death_state=2,
            airhorn_ready=1, prologue_stage=1, error=0, dropped=0)
        self.adapter.bridge = SimpleNamespace(shared=self.shared, manifest={'build_id': 1},
            supplies=lambda: {'ready': False, 'shiv_max': 0, 'shivs': 0,
                              'kit_max': 0, 'health_kits': 0, 'weapons': []})

    def test_prologue_effects_do_not_wait_for_inventory_but_supplies_do(self):
        view = self.adapter.delivery_context()
        self.assertEqual(view['death_reason'], '')
        self.assertEqual(view['airhorn_reason'], '')
        self.assertTrue(view['playable'])
        for item in ('Ammo Supply', 'Health Kit', 'Shiv'):
            self.assertIn('backpack', view['supplies'][ITEM_IDS[item]])

    def test_story_finale_is_explained_as_scripted(self):
        self.shared.prologue_stage = 2
        self.shared.death_state = self.shared.airhorn_ready = 0
        view = self.adapter.delivery_context()
        self.assertIn('story finale', view['death_reason'])
        self.assertIn('story finale', view['airhorn_reason'])
        self.assertFalse(view['playable'])

    def test_pause_inside_playable_task_and_20_years_later_need_control(self):
        for current in (1, 2):
            self.shared.current = current; self.shared.allowed = 3
            self.shared.death_state = self.shared.airhorn_ready = 0
            view = self.adapter.delivery_context()
            self.assertIn('stable gameplay', view['death_reason'])
            self.assertIn('stable gameplay', view['airhorn_reason'])
            self.assertNotIn('backpack', view['reason'])

    def test_run_protection_and_mission_locks_override_ready_telemetry(self):
        self.adapter.compatibility_error = 'bad save'
        view = self.adapter.delivery_context()
        self.assertEqual(view['death_reason'], 'Save does not match this run')
        self.assertEqual(view['airhorn_reason'], 'Save does not match this run')
        self.adapter.compatibility_error = ''; self.shared.allowed = 0
        view = self.adapter.delivery_context()
        self.assertEqual(view['death_reason'], 'Mission locked')
        self.assertEqual(view['airhorn_reason'], 'Mission locked')
