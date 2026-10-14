import tempfile
from pathlib import Path
import unittest

from tlou_ap.catalog import Config, COLLECTIBLES, MISSIONS, CHECKS, ITEM_IDS
from tlou_ap.native.run import RunLedger, START
from tlou_ap.native.bridge import Shared, Event
from tlou_ap.session import Session, ReceivedItem
import ctypes


class ManagedRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.required = [{1000 + i * 2, 1001 + i * 2} for i in range(29)]
        self.path = Path(self.temp.name) / 'run.json'
        self.ledger = RunLedger(self.path, self.required)
        self.session = Session(self.temp.name, 'seed', 0, 1, self.ledger.data['run_id'], Config())
        self.ledger.bind(self.session.identity)

    def event(self, kind, sid, mission=0, flags=0):
        self.ledger.event({'type': kind, 'sid': sid, 'mission': mission + 1, 'flags': flags}, self.session)
        self.ledger.confirm_native([0] * 29, self.session)

    def test_unfinished_cinematic_prevents_mission_check(self):
        self.event(1, START)
        for sid in self.required[0]:
            self.ledger.event({'type': 6, 'sid': sid, 'mission': 1, 'flags': 2}, self.session)
        self.ledger.confirm_native([-1] * 29, self.session)
        self.assertEqual(self.session.data['missions'], [])
        self.ledger.confirm_native([0] + [-1] * 28, self.session)
        self.assertEqual(self.session.data['missions'], [0])

    def test_old_progress_cannot_arm_or_complete_a_run(self):
        self.event(1, int(MISSIONS[4]['task_sid'], 16), 4)
        self.event(6, 1000)
        self.event(6, 1001)
        self.assertFalse(self.ledger.data['started'])
        self.assertEqual(self.session.earned_checks, set())

    def test_all_live_tasks_needed_and_evidence_survives_restart(self):
        self.event(1, START)
        self.event(6, 1000)
        self.assertEqual(self.session.data['missions'], [])
        self.ledger = RunLedger(self.path, self.required)
        self.event(6, 1001)
        self.assertEqual(self.session.data['missions'], [0])
        self.event(6, 1001)
        self.assertEqual(len(self.session.earned_checks), 2)

    def test_locked_future_completion_is_not_saved_for_later(self):
        self.event(1, START)
        self.event(6, 1010, 5)
        self.event(6, 1011, 5)
        self.assertEqual(self.ledger.data['completed_tasks'], [])

    def test_restore_inventory_is_not_a_pickup(self):
        self.event(1, START)
        for mission in range(4):
            for sid in self.required[mission]: self.event(6, sid, mission)
        entry = COLLECTIBLES[1]
        self.event(2, int(entry['sid'], 16), flags=0)
        self.assertEqual(self.session.data['collectibles'], [])
        self.event(2, int(entry['sid'], 16), flags=3)
        self.assertEqual(self.session.data['collectibles'], [1])

    def test_locked_loading_root_retained_without_earning_checks_then_promoted(self):
        mission = 5
        root = int(MISSIONS[mission]['task_sid'], 16)
        self.required[mission] = {root, 99999}
        self.ledger.data.update(started=True, completed_tasks=list(set.union(*self.required[:mission])),
                                native_confirmed=list(range(mission)))
        self.session.data['missions'] = list(range(mission))
        self.session._commit()
        start = dict(type=1, sid=root, mission=mission+1, flags=0x40000000)
        finish = {**start, 'type':6, 'flags':2}
        self.ledger.record_events([start, finish], self.session, [0]*mission+[-1]*(29-mission))
        self.assertEqual(self.ledger.data['loading_roots'], [root])
        self.assertNotIn(root, self.ledger.data['completed_tasks'])
        self.assertFalse(self.session.can_start(mission))
        self.ledger = RunLedger(self.path, self.required)
        self.session.record_inventory([ReceivedItem(ITEM_IDS['Progressive Chapter Unlock'], 1, 1, 1)])
        self.ledger.confirm_native([0]*mission+[-1]*(29-mission), self.session)
        self.assertIn(root, self.ledger.data['completed_tasks'])
        self.assertEqual(self.session.data['missions'], list(range(mission)))

    def test_loading_root_without_start_or_across_restore_is_not_retained(self):
        mission = 5
        root = int(MISSIONS[mission]['task_sid'], 16)
        self.required[mission] = {root, 99999}
        self.ledger.data['started'] = True
        self.session.data['missions'] = list(range(mission))
        start = dict(type=1, sid=root, mission=mission+1, flags=0x40000000)
        finish = {**start, 'type':6, 'flags':2}
        for batch in ([finish], [start, {**start, 'flags':1}, finish]):
            self.ledger.retain_loading_root(batch, self.session)
            self.assertEqual(self.ledger.data.get('loading_roots', []), [])

    def test_cannot_rebind_run_to_another_seed(self):
        with self.assertRaises(ValueError):
            self.ledger.bind({**self.session.identity, 'seed': 'other'})

    def test_medical_pamphlet_awarded_during_downtown_survives_restart(self):
        self.session.record_inventory([ReceivedItem(ITEM_IDS['Progressive Chapter Unlock'], 1, 1, 1)])
        self.event(1, START)
        for mission in range(6):
            for sid in self.required[mission]:
                self.event(6, sid, mission)
        self.assertFalse(self.session.can_start(7))
        # Exact native pickup identity/mission/flags from the reported run.
        pickup = {'type': 7, 'sid': 0xa230bcda4867dee1, 'mission': 7, 'flags': 1}
        self.ledger.event({**pickup, 'flags': 0}, self.session)
        self.assertNotIn(12, self.session.data['collectibles'])
        self.ledger.event(pickup, self.session)
        self.ledger = RunLedger(self.path, self.required)
        self.session = Session(self.temp.name, 'seed', 0, 1, self.ledger.data['run_id'], Config())
        self.ledger.event({**pickup, 'type': 2, 'mission': 0, 'flags': 3}, self.session)
        self.assertEqual(self.ledger.data['collectibles'], [12])
        self.assertEqual(self.session.data['collectibles'], [12])
        self.assertEqual(self.session.data['missions'], list(range(6)))
        check = next(c for c in CHECKS if c.category == 'collectible' and c.native_index == 12)
        self.assertEqual(check.name, 'The Outskirts - Museum - Medical Pamphlet')
        self.assertIn(check.id, self.session.earned_checks)

    def test_locked_or_unreached_chapter_pickup_is_not_saved_for_later(self):
        self.event(1, START)
        pickup = {'type': 7, 'sid': 0xa230bcda4867dee1, 'mission': 7, 'flags': 1}
        # Chapter is locked initially, then unlocked but still not reached.
        for unlocked in (False, True):
            if unlocked:
                self.session.record_inventory([ReceivedItem(ITEM_IDS['Progressive Chapter Unlock'], 1, 1, 1)])
            self.ledger.event(pickup, self.session)
            self.assertEqual(self.ledger.data['collectibles'], [])
        for mission in range(6):
            for sid in self.required[mission]:
                self.event(6, sid, mission)
        self.ledger.reconcile_checks(self.session)
        self.assertEqual(self.session.data['collectibles'], [])

    def test_early_pickup_requires_started_managed_run(self):
        self.session.record_inventory([ReceivedItem(ITEM_IDS['Progressive Chapter Unlock'], 1, 1, 1)])
        for mission in range(6):
            self.session.complete_mission(mission)
        self.ledger.event({'type': 7, 'sid': 0xa230bcda4867dee1, 'mission': 7, 'flags': 1}, self.session)
        self.assertEqual(self.ledger.data['collectibles'], [])
        self.assertEqual(self.session.data['collectibles'], [])

    def test_all_catalog_entries_deduplicate_pickup_and_profile_award_paths(self):
        session = Session(self.temp.name, 'full', 0, 1, self.ledger.data['run_id'], Config(starting_chapters=12))
        self.ledger.data['started'] = True
        for mission in range(29): session.complete_mission(mission)
        for entry in COLLECTIBLES:
            sid = int(entry['sid'], 16)
            for kind, flags in ((7, 0), (2, 0)):
                self.ledger.event({'type': kind, 'sid': sid, 'mission': entry['mission'] + 1, 'flags': flags}, session)
            self.assertNotIn(entry['index'], session.data['collectibles'])
            for kind in (7, 2, 7):
                self.ledger.event({'type': kind, 'sid': sid, 'mission': entry['mission'] + 1, 'flags': 1}, session)
            self.assertIn(entry['index'], session.data['collectibles'])
        self.assertEqual(len(session.data['collectibles']), 140)
        self.assertEqual(len(set(entry['sid'] for entry in COLLECTIBLES)), 140)

    def test_shared_memory_abi_matches_native_contract(self):
        self.assertEqual(ctypes.sizeof(Shared), 35432)
        self.assertEqual(Shared.routes.offset, 160)
        self.assertEqual(Shared.events.offset, 10400)
        self.assertEqual(ctypes.sizeof(Event), 48)

    def test_batch_preview_does_not_mutate_state_or_unlock_chapters(self):
        self.event(1, START)
        events = [dict(type=6, sid=sid, mission=mission + 1, flags=2)
                  for mission, tasks in enumerate(self.required) for sid in tasks]
        self.assertEqual(self.ledger.available_missions(self.session, [0]*29, events), set(range(5)))
        self.assertEqual(self.session.data['missions'], [])
        self.assertEqual(self.ledger.data['completed_tasks'], [])
        # Completion events can be reordered without dropping newly allowed
        # missions. Locked chapters remain rejected even with hook evidence.
        self.ledger.record_events(list(reversed(events)), self.session, [0]*29)
        self.assertEqual(self.session.data['missions'], list(range(5)))
        self.assertEqual(set(self.ledger.data['completed_tasks']), set.union(*self.required[:5]))


if __name__ == '__main__':
    unittest.main()
