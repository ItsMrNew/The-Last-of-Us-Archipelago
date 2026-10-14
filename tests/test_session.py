import json
from pathlib import Path
import tempfile
import unittest

from tlou_ap.catalog import (CHECKS, COLLECTIBLES, Config, ITEM_IDS, MISSIONS, PROGRESSIVE_CHAPTER,
                             unlocked_chapters)
from tlou_ap.session import Inventory, ReceivedItem, Session, SyncRequired


def item(name=PROGRESSIVE_CHAPTER, location=10):
    return {'item': ITEM_IDS[name], 'location': location, 'player': 1, 'flags': 0}


class InventoryTests(unittest.TestCase):
    def test_duplicate_gap_conflict_and_resync(self):
        inv = Inventory()
        with self.assertRaises(SyncRequired):
            inv.apply(1, [item()])
        inv.apply(0, [item()])
        inv.apply(1, [item(location=11)])
        inv.apply(1, [item(location=11)])
        self.assertEqual(len(inv.items), 2)
        with self.assertRaises(SyncRequired):
            inv.apply(1, [item('Health Kit')])
        self.assertFalse(inv.synchronized)
        inv.apply(0, [item()])
        self.assertTrue(inv.synchronized)
        self.assertEqual(len(inv.items), 1)

    def test_reject_unknown_items_and_booleans(self):
        for entry in (item() | {'item': 999}, item() | {'player': True}, item() | {'location': None}):
            with self.assertRaises(ValueError):
                Inventory().apply(0, [entry])


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Config()
        self.session = self.open()

    def open(self, seed='seed', run='run'):
        return Session(self.temp.name, seed, 0, 1, run, self.config)

    def unlock_all(self):
        self.session.record_inventory([ReceivedItem.parse(item(location=i)) for i in range(10)])

    def test_seed_run_isolation_and_resume(self):
        self.session.complete_mission(0)
        self.assertEqual(self.open().data['missions'], [0])
        self.assertEqual(self.open(seed='other').data['missions'], [])
        self.assertEqual(self.open(run='other').data['missions'], [])

    def test_mission_order_and_chapter_gate(self):
        with self.assertRaises(ValueError):
            self.session.complete_mission(1)
        for mission in MISSIONS:
            if mission['chapter'] < 2:
                self.session.complete_mission(mission['index'])
        next_mission = next(m['index'] for m in MISSIONS if m['chapter'] == 2)
        self.assertFalse(self.session.can_start(next_mission))
        self.session.record_inventory([ReceivedItem.parse(item())])
        self.assertTrue(self.session.can_start(next_mission))
        self.session.complete_mission(next_mission)
        self.assertEqual(len(self.session.unlocked), 3)

    def test_checks_deduplicate_and_goal_needs_epilogue(self):
        self.unlock_all()
        for mission in MISSIONS[:-1]:
            self.session.complete_mission(mission['index'])
            self.session.complete_mission(mission['index'])
        self.assertFalse(self.session.story_complete)
        self.session.complete_mission(len(MISSIONS) - 1)
        self.assertTrue(self.session.story_complete)
        self.assertEqual(len(self.session.earned_checks), 41)
        for entry in COLLECTIBLES:
            self.session.collect(entry['index'])
            self.session.collect(entry['index'])
        self.assertEqual(self.session.earned_checks, {check.id for check in CHECKS})

    def test_old_or_locked_collectible_rejected(self):
        with self.assertRaises(ValueError):
            self.session.collect(1)
        for mission in range(3):
            self.session.complete_mission(mission)
        self.session.collect(1)
        self.assertEqual(len(self.session.earned_checks), 5)  # 3 missions, Hometown, notice

    def test_reward_crash_receipt_is_not_replayed(self):
        self.session.record_inventory([ReceivedItem.parse(item('Ammo Supply')), ReceivedItem.parse(item('Health Kit'))])
        receipt = self.session.reserve_supply(0)
        self.assertTrue(receipt.endswith(':0'))
        resumed = self.open()
        self.assertEqual(resumed.queued_supplies, (1,))
        resumed.resolve_supply(0, 'uncertain')
        self.assertEqual(self.open().queued_supplies, (1,))
        resumed.resolve_supply(0, 'not_applied')
        self.assertEqual(self.open().queued_supplies, (0, 1))
        resumed.reserve_supply(0)
        resumed.resolve_supply(0, 'applied')
        with self.assertRaises(ValueError):
            resumed.record_inventory([])
        self.assertEqual(self.open().queued_supplies, (1,))

    def test_collectible_grouping_does_not_gate_early_pickup(self):
        self.session.record_inventory([ReceivedItem.parse(item())])
        for mission in range(6):
            self.session.complete_mission(mission)
        self.assertTrue(self.session.can_start(6))  # Downtown.
        self.assertFalse(self.session.can_start(7))  # Museum.
        self.assertTrue(self.session.can_collect(12))  # Medical Pamphlet.
        self.session.collect(12)
        self.session.collect(12)
        self.assertEqual(self.open().data['collectibles'], [12])
        self.assertEqual(self.session.data['missions'], list(range(6)))
        with self.assertRaises(ValueError):
            self.session.complete_mission(7)

    def test_early_pickup_still_requires_unlocked_reachable_chapter(self):
        for mission in range(5):
            self.session.complete_mission(mission)
        self.assertFalse(self.session.can_collect(12))  # Outskirts locked.
        with self.assertRaises(ValueError):
            self.session.collect(12)
        self.session.record_inventory([ReceivedItem.parse(item())])
        self.assertTrue(self.session.can_collect(12))
        for value in (True, -1, 140, None):
            self.assertFalse(self.session.can_collect(value))
        # Starting with every chapter unlocked must not bypass story order.
        future = Session(self.temp.name, 'all-open', 0, 1, 'other', Config(starting_chapters=12))
        self.assertFalse(future.can_collect(12))
        with self.assertRaises(ValueError):
            future.collect(12)

    def test_corrupt_save_rejected(self):
        self.session.complete_mission(0)
        data = json.loads(self.session.path.read_text())
        data['missions'] = [2]
        self.session.path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.open()

    def test_slot_schema_and_options(self):
        self.assertEqual(Config.from_slot_data(self.config.slot_data(), [c.id for c in CHECKS]), self.config)
        with self.assertRaises(ValueError):
            Config.from_slot_data(self.config.slot_data(), [])
        with self.assertRaises(ValueError):
            Config.from_slot_data(self.config.slot_data() | {'schema_version': 2}, [c.id for c in CHECKS])
        for args in ({'starting_chapters': 0}, {'starting_chapters': True},
                     {'mission_checks': False, 'chapter_checks': False, 'collectible_checks': False},
                     {'starting_chapters': 1, 'mission_checks': False, 'chapter_checks': False}):
            with self.assertRaises(ValueError):
                Config(**args)
        self.assertEqual(len(unlocked_chapters(self.config, [ITEM_IDS[PROGRESSIVE_CHAPTER]] * 100)), 12)


if __name__ == '__main__':
    unittest.main()
