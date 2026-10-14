import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from tlou_ap.catalog import Config, ITEM_IDS, SUPPLIES
from tlou_ap.native.adapter import NativeAdapter
from tlou_ap.native.bridge import Bridge, Shared
from tlou_ap.native.run import RunLedger
from tlou_ap.session import ReceivedItem, Session


class SupplyTests(unittest.TestCase):
    def adapter(self, directory):
        adapter = NativeAdapter.__new__(NativeAdapter)
        adapter.ledger = RunLedger(Path(directory) / 'run.json', [{i} for i in range(29)])
        adapter.ledger.data['started'] = True
        adapter.compatibility_error = ''
        adapter.receipt_query = None
        adapter.deathlink = SimpleNamespace(command=None)
        adapter.next_attempt = {}
        adapter.native_instance = 'test-process'
        status = {'player': 1, 'weapon': 2, 'ammo_sid': 'b4ce74acb1317617', 'ammo': 10,
                  'resources': [0] * 8, 'resource_max': [12] * 6 + [9999] * 2,
                  'ready': True, 'health_kits': 3, 'kit_max': 3,
                  'shivs': 3, 'shiv_max': 3, 'weapons': [
                      {'weapon': 2, 'ammo_sid': 'b4ce74acb1317617', 'ammo': 10, 'maximum': 20}]}
        calls = []
        adapter.bridge = SimpleNamespace(shared=SimpleNamespace(current=4, pending=0, allowed=8),
            command_busy=False, supplies=lambda: status, begin_command=lambda *args: calls.append(args) or 1,
            command_result=lambda seq: 1)
        return adapter, status, calls

    def test_stable_ids_and_shiv_pool(self):
        self.assertEqual(ITEM_IDS['Ammo Supply'], 19710001)
        self.assertEqual(ITEM_IDS['Health Kit'], 19710002)
        self.assertEqual(ITEM_IDS['Shiv'], 19710003)
        self.assertIn('Shiv', SUPPLIES)

    def test_drawn_low_ammo_not_blocked_by_full_consumables(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, status, _ = self.adapter(directory)
            self.assertTrue(adapter.can_deliver(ITEM_IDS['Ammo Supply']))
            self.assertFalse(adapter.can_deliver(ITEM_IDS['Health Kit']))
            self.assertFalse(adapter.can_deliver(ITEM_IDS['Shiv']))
            status['ammo'] = status['weapons'][0]['ammo'] = 20
            self.assertFalse(adapter.can_deliver(ITEM_IDS['Ammo Supply']))
            status['health_kits'] = status['shivs'] = 2
            self.assertTrue(adapter.can_deliver(ITEM_IDS['Health Kit']))
            self.assertTrue(adapter.can_deliver(ITEM_IDS['Shiv']))
            status['shiv_max'] = 0
            self.assertFalse(adapter.can_deliver(ITEM_IDS['Shiv']))
            status['ready'] = False
            self.assertFalse(adapter.can_deliver(ITEM_IDS['Health Kit']))

    def test_ammo_trigger_uses_drawn_weapon_total_and_inclusive_half_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, status, calls = self.adapter(directory)
            # Empty holstered gun must not trigger while the drawn one is >50%.
            status['weapons'].append({'weapon': 3, 'ammo_sid': 'dde675074fc76559', 'ammo': 0, 'maximum': 20})
            for maximum, ammo, expected in ((20, 11, False), (20, 10, True),
                                            (20, 0, True), (9, 5, False), (9, 4, True),
                                            (20, -1, False), (0, 0, False)):
                with self.subTest(maximum=maximum, ammo=ammo):
                    status['weapons'][0].update(maximum=maximum, ammo=ammo)
                    status['ammo'] = ammo
                    self.assertEqual(adapter.can_deliver(ITEM_IDS['Ammo Supply']), expected)
            status['weapons'][0].update(maximum=20, ammo=10); status['ammo'] = 10
            for weapon, ammo_sid in ((0, 'b4ce74acb1317617'), (99, 'b4ce74acb1317617'), (2, 'unknown')):
                status.update(weapon=weapon, ammo_sid=ammo_sid)
                self.assertFalse(adapter.can_deliver(ITEM_IDS['Ammo Supply']))
            self.assertEqual(calls, [])

    def test_high_ammo_stays_queued_across_reconnect_without_spending_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, status, calls = self.adapter(directory)
            session = Session(directory, 'seed', 0, 1, adapter.ledger.data['run_id'], Config())
            session.record_inventory([ReceivedItem(ITEM_IDS['Ammo Supply'], 1, 1, 0)])
            status['ammo'] = status['weapons'][0]['ammo'] = 11
            self.assertFalse(adapter.can_deliver(ITEM_IDS['Ammo Supply']))
            restored = Session(directory, 'seed', 0, 1, adapter.ledger.data['run_id'], Config())
            self.assertEqual(restored.queued_supplies, (0,))
            self.assertEqual(restored.data['receipts'], {})
            self.assertEqual(calls, [])
            status['ammo'] = status['weapons'][0]['ammo'] = 10
            self.assertTrue(adapter.can_deliver(ITEM_IDS['Ammo Supply']))

    def test_each_new_command_has_durable_kind_and_recovers_once(self):
        for name, kind in (('Ammo Supply', 4), ('Health Kit', 2), ('Shiv', 5)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                adapter, _, calls = self.adapter(directory)
                session = Session(directory, 'seed', 0, 1, adapter.ledger.data['run_id'], Config())
                session.record_inventory([ReceivedItem(ITEM_IDS[name], 1, 1, 0)])
                receipt = session.reserve_supply(0)
                self.assertEqual(adapter.deliver(ITEM_IDS[name], receipt), 'uncertain')
                self.assertEqual(calls[0][:2], (kind, 1 | (4 << 8)))
                self.assertEqual(adapter.ledger.data['deliveries'][receipt]['command_kind'], kind)
                adapter.reconcile_deliveries(session)
                self.assertEqual(calls[1][:2], (101, kind))
                adapter.reconcile_deliveries(session)
                self.assertEqual(session.data['receipts']['0'], 'applied')
                self.assertEqual(adapter.deliver(ITEM_IDS[name], receipt), 'applied')
                self.assertEqual(len(calls), 2)

    def test_shared_snapshot_never_publishes_a_half_written_inventory(self):
        bridge = Bridge.__new__(Bridge)
        bridge.shared = Shared()
        bridge.shared.supply_revision = 1
        self.assertFalse(bridge.supplies()['ready'])
        bridge.shared.supply_revision = 2
        bridge.shared.shivs, bridge.shared.shiv_max = 2, 3
        bridge.shared.supply_ready = 1
        bridge.shared.weapon_count = 1
        bridge.shared.weapons[0].maximum = 20
        snapshot = bridge.supplies()
        self.assertTrue(snapshot['ready'])
        self.assertEqual(snapshot['shivs'], 2)
        self.assertEqual(snapshot['weapons'][0]['maximum'], 20)

    def test_deferred_native_delivery_survives_restart_and_delivers_once(self):
        for name in SUPPLIES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                adapter, status, calls = self.adapter(directory)
                session = Session(directory, 'seed', 0, 1, adapter.ledger.data['run_id'], Config())
                session.record_inventory([ReceivedItem(ITEM_IDS[name], 1, 1, 0)])
                status['health_kits'] = status['shivs'] = 0
                # Pause/cinematic/loading exposes ready=False. Locks have their
                # own independent native pending/permission guards.
                status['ready'] = False
                self.assertFalse(adapter.can_deliver(ITEM_IDS[name]))
                self.assertEqual(session.queued_supplies, (0,))
                self.assertEqual(calls, [])
                status['ready'] = True
                adapter.bridge.shared.pending = 1
                self.assertFalse(adapter.can_deliver(ITEM_IDS[name]))
                adapter.bridge.shared.pending = 0
                adapter.bridge.shared.allowed = 0
                self.assertFalse(adapter.can_deliver(ITEM_IDS[name]))
                adapter.bridge.shared.allowed = 8
                # The game may enter a cutscene between eligibility and native
                # execution. A refused command must restore the durable queue.
                receipt = session.reserve_supply(0)
                session.resolve_supply(0, adapter.deliver(ITEM_IDS[name], receipt))
                adapter.bridge.command_result = lambda seq: 5
                adapter.reconcile_deliveries(session)
                adapter.reconcile_deliveries(session)
                restored = Session(directory, 'seed', 0, 1, adapter.ledger.data['run_id'], Config())
                self.assertEqual(restored.queued_supplies, (0,))
                adapter.next_attempt.clear()
                self.assertTrue(adapter.can_deliver(ITEM_IDS[name]))
                self.assertEqual(restored.reserve_supply(0), receipt)
                restored.resolve_supply(0, adapter.deliver(ITEM_IDS[name], receipt))
                adapter.bridge.command_result = lambda seq: 1
                adapter.reconcile_deliveries(restored)
                adapter.reconcile_deliveries(restored)
                again = Session(directory, 'seed', 0, 1, adapter.ledger.data['run_id'], Config())
                self.assertEqual(again.queued_supplies, ())
                self.assertEqual(again.data['receipts'], {'0': 'applied'})
                count = len(calls)
                self.assertEqual(adapter.deliver(ITEM_IDS[name], receipt), 'applied')
                self.assertEqual(len(calls), count)


if __name__ == '__main__':
    unittest.main()
