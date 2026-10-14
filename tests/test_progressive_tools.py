import tempfile
import unittest

from tlou_ap.catalog import Config, ITEM_IDS, PROGRESSIVE_TOOLS
from tlou_ap.session import Session, ReceivedItem
from tlou_ap.native.run import RunLedger
from tests.test_supplies import SupplyTests


TOOL = ITEM_IDS[PROGRESSIVE_TOOLS]


class ProgressiveToolTests(unittest.TestCase):
    def fixture(self, directory, level=0):
        adapter, status, calls = SupplyTests().adapter(directory)
        status['tool_level'] = level
        def command(kind, argument, receipt):
            calls.append((kind, argument, receipt))
            if kind == 7:
                status['tool_level'] = max(status['tool_level'], argument & 0xff)
            return len(calls)
        adapter.bridge.begin_command = command
        session = Session(directory, 'tools', 0, 1, adapter.ledger.data['run_id'], Config())
        session.record_inventory([ReceivedItem(TOOL, n, 1, 2) for n in range(5)])
        return adapter, status, calls, session

    def grant(self, adapter, session, index):
        receipt = session.reserve_supply(index)
        session.resolve_supply(index, adapter.deliver(TOOL, receipt))
        adapter.reconcile_deliveries(session)
        adapter.next_attempt.clear()
        return receipt

    def test_bonus_native_levels_cap_and_receipt_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter, status, calls, session = self.fixture(folder, 2)
            for i, expected in enumerate((3, 4, 5, 5, 5)):
                receipt = self.grant(adapter, session, i)
                self.assertEqual(status['tool_level'], expected)
                count = len(calls)
                self.assertEqual(adapter.deliver(TOOL, receipt), 'applied')
                self.assertEqual(len(calls), count)
            self.assertEqual(session.queued_supplies, ())

    def test_reload_restores_floor_without_counting_again(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter, status, calls, session = self.fixture(folder, 1)
            receipt = self.grant(adapter, session, 0)
            status['tool_level'] = 0
            adapter.reconcile_deliveries(session)
            self.assertEqual(status['tool_level'], 2)
            adapter.reconcile_deliveries(session)
            adapter.next_attempt.clear()
            adapter.reconcile_deliveries(session)
            self.assertEqual(adapter.ledger.data['deliveries'][receipt]['tool_target'], 2)
            self.assertEqual(len(calls), 2)
            status['tool_level'] = 4  # Normal toolbox progress is never downgraded.
            adapter.reconcile_deliveries(session)
            self.assertEqual(status['tool_level'], 4)

    def test_crash_after_submission_reconciles_absolute_target(self):
        for native_level in (0, 1):
            with self.subTest(native_level=native_level), tempfile.TemporaryDirectory() as folder:
                adapter, status, calls, session = self.fixture(folder)
                receipt = session.reserve_supply(0)
                adapter.deliver(TOOL, receipt)
                adapter.ledger = RunLedger(adapter.ledger.path, adapter.ledger.required)
                adapter.receipt_query = None
                adapter.native_instance = 'restarted-process'
                adapter.next_attempt.clear()
                status['tool_level'] = native_level
                session = Session(folder, 'tools', 0, 1, adapter.ledger.data['run_id'], Config())
                adapter.reconcile_deliveries(session)
                adapter.reconcile_deliveries(session)
                self.assertEqual(status['tool_level'], 1)
                self.assertEqual(session.data['receipts']['0'], 'applied')
                self.assertEqual(adapter.ledger.data['deliveries'][receipt]['tool_target'], 1)

    def test_waits_for_gameplay_and_joel(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter, status, calls, session = self.fixture(folder)
            for key, value in (('ready', False), ('shiv_max', 0), ('tool_level', -1)):
                old = status[key]; status[key] = value
                self.assertFalse(adapter.can_deliver(TOOL))
                adapter.reconcile_deliveries(session)
                self.assertFalse(calls)
                status[key] = old
            adapter.compatibility_error = 'foreign save'
            self.assertFalse(adapter.can_deliver(TOOL))

    def test_slot_backcompat_and_new_schema(self):
        old = Config()
        self.assertNotIn('progressive_tools', old.slot_data())
        new = Config(progressive_tools=5)
        self.assertEqual(new.slot_data()['schema_version'], 4)
        self.assertEqual(Config.from_slot_data(new.slot_data(), [c.id for c in new.active_checks]), new)
        for invalid in (-1, 6, True, 1.5):
            with self.assertRaises(ValueError):
                Config(progressive_tools=invalid)


if __name__ == '__main__':
    unittest.main()
