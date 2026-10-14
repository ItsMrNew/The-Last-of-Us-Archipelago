import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tlou_ap.catalog import Config
from tlou_ap.native.adapter import NativeAdapter
from tlou_ap.native.progress import LiveTaskProgress
from tlou_ap.native.run import RunLedger
from tlou_ap.session import Session


class LiveProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = RunLedger(Path(self.temp.name) / 'run.json', [{10}, {20, 21}, *[{100+i} for i in range(27)]])
        self.ledger.data.update(started=True, completed_tasks=[10], native_confirmed=[0])
        self.session = Session(self.temp.name, 'seed', 0, 1, self.ledger.data['run_id'], Config())
        self.session.complete_mission(0)
        self.progress = LiveTaskProgress()

    def nodes(self, a=-1, b=-1):
        return [{'sid': 20, 'difficulty': a}, {'sid': 21, 'difficulty': b}]

    def event(self, task=20, kind=1, flags=0x40000000, sequence=1):
        return dict(sid=task, type=kind, mission=2, flags=flags, sequence=sequence)

    def test_live_start_and_difficulty_change_recover_missing_hook_once(self):
        self.progress.observe(self.nodes(), [], self.session)
        self.progress.observe(self.nodes(), [self.event()], self.session)
        inferred = self.progress.observe(self.nodes(0), [], self.session)
        self.assertEqual([e['sid'] for e in inferred], [20])
        self.assertEqual(inferred[0]['source'], 'live_task_difficulty')
        self.ledger.event(inferred[0], self.session)
        self.progress.accepted()
        self.assertEqual(self.progress.observe(self.nodes(0), [], self.session), [])
        self.assertEqual(self.session.data['missions'], [0])
        self.ledger.event(self.event(21, 6, 2), self.session)
        self.ledger.confirm_native([0, 0] + [-1]*27, self.session)
        self.assertEqual(self.session.data['missions'], [0, 1])

    def test_start_and_finish_between_polls_and_hook_deduplication(self):
        self.progress.observe(self.nodes(), [], self.session)
        self.assertEqual(len(self.progress.observe(self.nodes(0), [self.event()], self.session)), 1)
        self.assertEqual(self.progress.observe(self.nodes(0), [self.event(20, 6, 2)], self.session), [])

    def test_imported_completed_snapshot_and_unobserved_tasks_cannot_earn_checks(self):
        self.assertEqual(self.progress.observe(self.nodes(0, 0), [self.event()], self.session), [])
        self.assertEqual(self.progress.observe(self.nodes(0, 0), [], self.session), [])
        self.progress = LiveTaskProgress()
        self.progress.observe(self.nodes(), [], self.session)
        self.assertEqual(self.progress.observe(self.nodes(0, 0), [], self.session), [])

    def test_load_restart_begin_and_level_play_invalidate_tracking(self):
        for flags in (1, 3, 11, 0x80000000):
            with self.subTest(flags=flags):
                progress = LiveTaskProgress()
                progress.observe(self.nodes(), [], self.session)
                progress.observe(self.nodes(), [self.event()], self.session)
                self.assertEqual(progress.observe(self.nodes(0),
                    [self.event(flags=flags), self.event()], self.session), [])
                self.assertEqual(progress.observe(self.nodes(0), [], self.session), [])

    def test_locked_mission_and_out_of_range_events_do_not_arm(self):
        self.progress.observe(self.nodes(), [], self.session)
        self.assertEqual(self.progress.observe(self.nodes(0),
            [{**self.event(), 'mission': 4}, {**self.event(21), 'mission': 0}], self.session), [])

    def test_checkpoint_start_rearms_only_after_later_unfinished_baseline(self):
        self.progress.observe(self.nodes(), [], self.session)
        self.assertEqual(self.progress.observe(self.nodes(),
            [self.event(flags=1), self.event()], self.session), [])
        self.assertEqual(self.progress.observe(self.nodes(), [], self.session), [])
        inferred = self.progress.observe(self.nodes(0), [], self.session)
        self.assertEqual([e['sid'] for e in inferred], [20])
        self.assertEqual(inferred[0]['source'], 'live_task_difficulty')

    def test_checkpoint_completed_snapshot_never_rearms(self):
        self.progress.observe(self.nodes(), [], self.session)
        self.progress.observe(self.nodes(), [self.event(flags=1), self.event()], self.session)
        self.assertEqual(self.progress.observe(self.nodes(0), [], self.session), [])
        self.assertEqual(self.progress.observe(self.nodes(0), [], self.session), [])


    def test_inferred_evidence_survives_one_poll_wait_for_native_hook(self):
        self.progress.observe(self.nodes(), [], self.session)
        first = self.progress.observe(self.nodes(0), [self.event()], self.session)
        self.assertEqual(self.progress.observe(self.nodes(0), [], self.session), first)

    def adapter(self, batches):
        adapter = NativeAdapter.__new__(NativeAdapter)
        adapter.ledger = self.ledger
        adapter.native_instance = 'test-process'
        adapter.bound = True
        adapter.last_status = None
        adapter.compatibility_error = ''
        adapter.pending_progress_error = ''
        adapter.live_progress = self.progress
        adapter.reconcile_deliveries = lambda session: None
        adapter.deathlink = SimpleNamespace(unconfirmed=False)
        acknowledged = []
        adapter.bridge = SimpleNamespace(heartbeat=lambda: None, is_alive=lambda: True,
            shared=SimpleNamespace(status=1, error=0), memory=None,
            events=lambda: batches.pop(0), acknowledge=acknowledged.append)
        return adapter, acknowledged

    def test_production_observer_records_missing_task_and_unlocks_next_mission(self):
        adapter, acknowledged = self.adapter([[], [self.event()], [self.event(21, 6, 2, 2)]])
        with patch('tlou_ap.native.adapter.read_task_nodes', side_effect=[self.nodes(), self.nodes(), self.nodes(0, 0)]), \
             patch('tlou_ap.native.adapter.mission_difficulties', side_effect=[[0]+[-1]*28, [0]+[-1]*28, [0,0]+[-1]*27]):
            for _ in range(3): adapter.observe(self.session)
        self.assertEqual(adapter.compatibility_error, '')
        self.assertEqual(self.session.data['missions'], [0, 1])
        self.assertTrue(self.session.can_start(2))
        self.assertEqual(acknowledged, [1, 2])
        logged = [json.loads(line) for line in self.ledger.path.with_suffix('.events.jsonl').read_text().splitlines()]
        self.assertEqual(sum(e.get('source') == 'live_task_difficulty' for e in logged), 1)

    def test_snapshot_writing_before_hook_publication_is_retried_without_losing_events(self):
        self.ledger.data['completed_tasks'].append(20)
        adapter, acknowledged = self.adapter([[self.event(21)], [self.event(21), self.event(21, 6, 2, 2)]])
        with patch('tlou_ap.native.adapter.read_task_nodes', return_value=self.nodes(0, 0)), \
             patch('tlou_ap.native.adapter.mission_difficulties', return_value=[0,0]+[-1]*27):
            adapter.observe(self.session)
            self.assertEqual(acknowledged, [])
            self.assertEqual(self.session.data['missions'], [0])
            adapter.observe(self.session)
        self.assertEqual(adapter.compatibility_error, '')
        self.assertEqual(self.session.data['missions'], [0, 1])

    def test_foreign_save_stays_blocked_and_quarantines_events(self):
        adapter, acknowledged = self.adapter([[self.event(flags=3)], [self.event(flags=3)]])
        with patch('tlou_ap.native.adapter.read_task_nodes', return_value=self.nodes(0, 0)), \
             patch('tlou_ap.native.adapter.mission_difficulties', return_value=[0,0]+[-1]*27):
            adapter.observe(self.session)
            adapter.observe(self.session)
        self.assertTrue(adapter.compatibility_error)
        self.assertEqual(acknowledged, [1])
        self.assertEqual(self.session.data['missions'], [0])
        self.assertEqual(self.ledger.data['completed_tasks'], [10])

    def transition_nodes(self, previous=-1, first=-1, last=-1):
        return [*self.nodes(0, previous), {'sid': 100, 'difficulty': first},
                {'sid': 101, 'difficulty': last}]

    def test_transition_batch_tracks_new_mission_before_predecessor_is_committed(self):
        self.ledger.required[2] = {100, 101}
        self.ledger.data['completed_tasks'].append(20)
        start = {**self.event(100, sequence=3), 'mission': 3}
        finish = {**self.event(101, 6, 2, 4), 'mission': 3}
        adapter, _ = self.adapter([[], [self.event(21, 6, 2, 2), start], [finish]])
        snapshots = [self.transition_nodes(), self.transition_nodes(0, 0), self.transition_nodes(0, 0, 0)]
        with patch('tlou_ap.native.adapter.read_task_nodes', side_effect=snapshots), \
             patch('tlou_ap.native.adapter.mission_difficulties', side_effect=[
                 [0]+[-1]*28, [0,0]+[-1]*27, [0,0,0]+[-1]*26]):
            adapter.observe(self.session)
            adapter.observe(self.session)
            self.assertEqual(self.session.data['missions'], [0, 1])
            self.assertIn(100, self.ledger.data['completed_tasks'])
            adapter.observe(self.session)
        self.assertEqual(adapter.compatibility_error, '')
        self.assertEqual(self.session.data['missions'], [0, 1, 2])

    def test_inferred_predecessor_and_next_mission_can_finish_in_one_batch(self):
        self.ledger.required[2] = {100, 101}
        self.ledger.data['completed_tasks'].append(20)
        start = {**self.event(100, sequence=3), 'mission': 3}
        finish = {**self.event(101, 6, 2, 4), 'mission': 3}
        adapter, _ = self.adapter([[], [self.event(21)], [start, finish]])
        with patch('tlou_ap.native.adapter.read_task_nodes', side_effect=[
                self.transition_nodes(), self.transition_nodes(), self.transition_nodes(0, 0, 0)]), \
             patch('tlou_ap.native.adapter.mission_difficulties', side_effect=[
                 [0]+[-1]*28, [0]+[-1]*28, [0,0,0]+[-1]*26]):
            for _ in range(3): adapter.observe(self.session)
        self.assertEqual(adapter.compatibility_error, '')
        self.assertEqual(self.session.data['missions'], [0, 1, 2])
        self.assertTrue({21, 100, 101} <= set(self.ledger.data['completed_tasks']))
        logged = [json.loads(line) for line in self.ledger.path.with_suffix('.events.jsonl').read_text().splitlines()]
        self.assertEqual({e['sid'] for e in logged if e.get('source') == 'live_task_difficulty'}, {21, 100})

    def test_snapshot_alone_cannot_authorize_next_mission_start(self):
        self.ledger.data['completed_tasks'].append(20)
        start = {**self.event(100), 'mission': 3}
        adapter, _ = self.adapter([[], [start], [start]])
        with patch('tlou_ap.native.adapter.read_task_nodes', side_effect=[
                self.transition_nodes(), self.transition_nodes(0, 0), self.transition_nodes(0, 0)]), \
             patch('tlou_ap.native.adapter.mission_difficulties', side_effect=[
                 [0]+[-1]*28, [0,0,0]+[-1]*26, [0,0,0]+[-1]*26]):
            for _ in range(3): adapter.observe(self.session)
        self.assertTrue(adapter.compatibility_error)
        self.assertEqual(self.session.data['missions'], [0])
        self.assertNotIn(100, self.progress.started)
        self.assertNotIn(100, self.ledger.data['completed_tasks'])

    def test_restore_batch_does_not_infer_new_mission_completion(self):
        self.ledger.data['completed_tasks'].append(20)
        start = {**self.event(100, sequence=3), 'mission': 3}
        batch = [self.event(21, 6, 2, 2), {**start, 'flags': 11}, start]
        adapter, _ = self.adapter([[], batch, batch])
        with patch('tlou_ap.native.adapter.read_task_nodes', side_effect=[
                self.transition_nodes(), self.transition_nodes(0, 0), self.transition_nodes(0, 0)]), \
             patch('tlou_ap.native.adapter.mission_difficulties', side_effect=[
                 [0]+[-1]*28, [0,0,0]+[-1]*26, [0,0,0]+[-1]*26]):
            for _ in range(3): adapter.observe(self.session)
        self.assertTrue(adapter.compatibility_error)
        self.assertEqual(self.session.data['missions'], [0])
        self.assertNotIn(100, self.ledger.data['completed_tasks'])


    def test_death_cleanup_journals_before_acknowledgement_and_retries_errors(self):
        event = self.event()
        event['type'] = 12
        adapter, acknowledged = self.adapter([[event], [event]])
        called = []
        def failed(token):
            called.append(token)
            self.assertEqual(acknowledged, [])
            raise OSError('journal unavailable')
        adapter.set_player_death_handler(failed)
        with patch('tlou_ap.native.adapter.read_task_nodes', return_value=self.nodes()), \
             patch('tlou_ap.native.adapter.mission_difficulties', return_value=[0]+[-1]*28):
            with self.assertRaises(OSError): adapter.observe(self.session)
            self.assertEqual(acknowledged, [])
            adapter.set_player_death_handler(called.append)
            adapter.observe(self.session)
        self.assertEqual(called, ['test-process:1', 'test-process:1'])
        self.assertEqual(acknowledged, [1])

    def test_death_cleanup_runs_even_when_checkpoint_snapshot_is_unreadable(self):
        event = self.event(); event['type'] = 12
        adapter, acknowledged = self.adapter([[event]])
        called = []; adapter.set_player_death_handler(called.append)
        with patch('tlou_ap.native.adapter.read_task_nodes', side_effect=OSError('loading')):
            adapter.observe(self.session)
        self.assertEqual(called, ['test-process:1'])
        self.assertEqual(acknowledged, [])

    def test_horn_pulse_is_not_a_player_death(self):
        event = self.event(); event['type'] = 11
        adapter, acknowledged = self.adapter([[event]])
        called = []; adapter.set_player_death_handler(called.append)
        with patch('tlou_ap.native.adapter.read_task_nodes', return_value=self.nodes()), \
             patch('tlou_ap.native.adapter.mission_difficulties', return_value=[0]+[-1]*28):
            adapter.observe(self.session)
        self.assertEqual(called, [])
        self.assertEqual(acknowledged, [1])
