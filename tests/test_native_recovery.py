import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from tlou_ap.catalog import Config, ITEM_IDS
from tlou_ap.native.adapter import NativeAdapter
from tlou_ap.native.run import RunLedger
from tlou_ap.session import ReceivedItem, Session


class NativeRecoveryTests(unittest.TestCase):
    def make_adapter(self, directory):
        adapter = NativeAdapter.__new__(NativeAdapter)
        adapter.ledger = RunLedger(Path(directory) / 'run.json', [{i} for i in range(29)])
        adapter.ledger.data['started'] = True
        adapter.native_instance = 'process-creation-and-build'
        adapter.next_attempt = {}
        adapter.receipt_query = None
        adapter.compatibility_error = ''
        adapter.deathlink = SimpleNamespace(command=None)
        calls = []
        def command(*args):
            calls.append(args)
            return 1  # Native cache confirms the existing receipt; no new effect.
        adapter.bridge = SimpleNamespace(begin_command=command, command_busy=False, command_result=lambda seq: 1)
        adapter.can_deliver = lambda item: False  # Full/holstered must not block read-only recovery.
        session = Session(directory, 'seed', 0, 1, adapter.ledger.data['run_id'], Config())
        session.record_inventory([ReceivedItem(ITEM_IDS['Ammo Supply'], 1, 1, 0)])
        receipt = session.reserve_supply(0)
        return adapter, session, receipt, calls

    def test_interrupted_client_reconciles_through_same_native_receipt_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.ledger.data['deliveries'][receipt] = {
                'outcome': 'pending', 'native_instance': adapter.native_instance}
            adapter.reconcile_deliveries(session)
            self.assertEqual(session.data['receipts']['0'], 'reserved')
            adapter.reconcile_deliveries(session)
            self.assertEqual(session.data['receipts']['0'], 'applied')
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], 101)
            adapter.reconcile_deliveries(session)
            self.assertEqual(len(calls), 1)

    def test_game_restart_does_not_replay_an_interrupted_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.ledger.data['deliveries'][receipt] = {
                'outcome': 'pending', 'native_instance': 'old-game-process'}
            adapter.reconcile_deliveries(session)
            self.assertEqual(session.data['receipts']['0'], 'reserved')
            self.assertEqual(calls, [])

    def test_confirmed_uncertain_native_result_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.ledger.data['deliveries'][receipt] = {
                'outcome': 'uncertain', 'native_instance': adapter.native_instance}
            adapter.reconcile_deliveries(session)
            self.assertEqual(calls, [])

    def test_durable_applied_result_repairs_session_without_calling_game(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.ledger.data['deliveries'][receipt] = 'applied'  # Earlier ledger format.
            adapter.reconcile_deliveries(session)
            self.assertEqual(session.data['receipts']['0'], 'applied')
            self.assertEqual(calls, [])

    def test_retired_receipt_cannot_be_regranted_directly(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.ledger.data['deliveries'][receipt] = {'outcome': 'retired', 'native_instance': 'old-game-process'}
            self.assertEqual(adapter.deliver(ITEM_IDS['Ammo Supply'], receipt), 'applied')
            self.assertEqual(calls, [])

    def test_reservation_crash_before_native_submission_requeues(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.reconcile_deliveries(session)
            self.assertEqual(session.queued_supplies, (0,))
            self.assertEqual(calls, [])

    def test_loading_command_does_not_block_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.bridge.command_busy = True
            adapter.ledger.data['deliveries'][receipt] = {'outcome': 'pending', 'native_instance': adapter.native_instance}
            adapter.reconcile_deliveries(session)
            adapter.after_poll()
            self.assertEqual(calls, [])
            self.assertEqual(session.data['receipts']['0'], 'reserved')

    def test_cache_absence_in_same_process_safely_requeues(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.bridge.command_result = lambda seq: 5
            adapter.ledger.data['deliveries'][receipt] = {'outcome': 'pending', 'native_instance': adapter.native_instance}
            adapter.reconcile_deliveries(session)
            adapter.reconcile_deliveries(session)
            self.assertEqual(session.queued_supplies, (0,))
            self.assertEqual(calls[0][0], 101)

    def test_retirement_survives_session_write_interruption_without_regrant(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, session, receipt, calls = self.make_adapter(directory)
            adapter.ledger.data['deliveries'][receipt] = {'outcome': 'pending', 'native_instance': 'old-game-process'}
            self.assertEqual(adapter.retire_held(session), 1)
            self.assertEqual(session.data['receipts']['0'], 'applied')
            session.data['receipts']['0'] = 'uncertain'
            adapter.reconcile_deliveries(session)
            self.assertEqual(session.data['receipts']['0'], 'applied')
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
