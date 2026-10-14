import asyncio
import json
import tempfile
import unittest
from websockets.legacy.server import serve
from websockets.exceptions import ConnectionClosed

from tlou_ap.catalog import AIRHORN, Config, GAME, ITEM_IDS, PROGRESSIVE_CHAPTER
from tlou_ap.client import Client, REQUIRED_CAPABILITIES, server_uri
from tlou_ap.native.observer import Observer
from tlou_ap.session import ReceivedItem, Session


class Adapter:
    capabilities = REQUIRED_CAPABILITIES
    run_id = 'test-run'

    def __init__(self):
        self.gate = None
        self.deliveries = []
        self.observe_calls = 0

    def set_gate(self, session):
        self.gate = session

    def bind(self, identity, resume):
        self.binding = (identity, resume)

    def observe(self, session):
        self.observe_calls += 1
        session.complete_mission(0)

    def can_deliver(self, item_id):
        return True

    def deliver(self, item_id, receipt):
        self.deliveries.append((item_id, receipt))
        return 'applied'


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_airhorn_inventory_waits_then_delivers_once_across_reconnect(self):
        class HornAdapter(Adapter):
            capabilities = REQUIRED_CAPABILITIES | {'airhorn'}
            ready = False
            pulses = 0

            def airhorn_status(self):
                return {'instance': 'game', 'clock': 0, 'ready': self.ready}

            def airhorn_pulse(self, receipt, instance, *, before_submit):
                before_submit(); self.pulses += 1
                return 'applied'

        class Socket:
            async def send(self, message): pass

        with tempfile.TemporaryDirectory() as directory:
            adapter, socket = HornAdapter(), Socket()
            config = Config(airhorn_trap_percentage=10)
            packet = {'cmd': 'Connected', 'team': 0, 'slot': 1, 'checked_locations': [],
                      'missing_locations': [c.id for c in config.active_checks],
                      'slot_data': config.slot_data()}
            items = {'cmd': 'ReceivedItems', 'index': 0, 'items': [
                {'item': ITEM_IDS[AIRHORN], 'location': 100, 'player': 2, 'flags': 4}]}
            client = Client('Tester', directory, adapter); client.seed = 'seed'
            await client.handle(socket, packet); await client.handle(socket, items)
            await client.poll(socket)
            self.assertEqual(client.airhorn.queued, 1)
            self.assertEqual(adapter.pulses, 0)
            adapter.ready = True; await client.poll(socket)
            self.assertEqual(adapter.pulses, 1)
            self.assertEqual(adapter.deliveries, [])  # Trap cannot enter the supply path.
            client = Client('Tester', directory, adapter); client.seed = 'seed'
            await client.handle(socket, packet)
            await client.poll(socket)  # Cached inventory cannot authorize replay.
            await client.handle(socket, items); await client.handle(socket, items)
            await client.poll(socket)
            self.assertEqual(adapter.pulses, 1)
            self.assertEqual(client.airhorn.queued, 0)

    async def test_airhorn_seed_rejects_adapter_without_trap_capability(self):
        class Socket:
            async def send(self, message): pass
        with tempfile.TemporaryDirectory() as directory:
            client = Client('Tester', directory, Adapter()); client.seed = 'seed'
            config = Config(airhorn_trap_percentage=10)
            with self.assertRaisesRegex(ValueError, 'Airhorn support'):
                await client.handle(Socket(), {'cmd': 'Connected', 'team': 0, 'slot': 1,
                    'checked_locations': [], 'missing_locations': [c.id for c in config.active_checks],
                    'slot_data': config.slot_data()})

    async def test_full_health_inventory_does_not_hold_up_ammo(self):
        class FullHealthAdapter(Adapter):
            def can_deliver(self, item_id):
                return item_id != ITEM_IDS['Health Kit']

        class Socket:
            async def send(self, message):
                pass

        with tempfile.TemporaryDirectory() as directory:
            adapter = FullHealthAdapter()
            client = Client('Tester', directory, adapter)
            client.session = Session(directory, 'seed', 0, 1, adapter.run_id, Config())
            entries = [{'item': ITEM_IDS[name], 'location': i, 'player': 1, 'flags': 0}
                       for i, name in enumerate(('Health Kit', 'Ammo Supply'))]
            client.session.record_inventory(client.inventory.apply(0, entries))
            client.connected = True
            await client.poll(Socket())
            self.assertEqual([i for i, _ in adapter.deliveries], [ITEM_IDS['Ammo Supply']])
            self.assertEqual(client.session.queued_supplies, (0,))
            self.assertEqual(client.session.data['receipts'], {'1': 'applied'})

    async def test_cached_unlocks_wait_for_authoritative_inventory(self):
        class Socket:
            def __init__(self):
                self.packets = []

            async def send(self, message):
                self.packets.extend(json.loads(message))

        with tempfile.TemporaryDirectory() as directory:
            config, adapter, socket = Config(), Adapter(), Socket()
            saved = Session(directory, 'seed', 0, 1, adapter.run_id, config)
            entry = {'item': ITEM_IDS[PROGRESSIVE_CHAPTER], 'location': 1, 'player': 1, 'flags': 1}
            saved.record_inventory([ReceivedItem.parse(entry)])
            client = Client('Tester', directory, adapter)
            client.seed = 'seed'
            await client.handle(socket, {'cmd': 'Connected', 'team': 0, 'slot': 1, 'checked_locations': [],
                                        'missing_locations': [c.id for c in config.active_checks],
                                        'slot_data': config.slot_data()})
            await client.poll(socket)
            self.assertIsNone(adapter.gate)
            self.assertEqual(adapter.observe_calls, 0)
            await client.handle(socket, {'cmd': 'ReceivedItems', 'index': 0, 'items': [entry]})
            self.assertEqual(len(adapter.gate.unlocked), 3)
            await client.handle(socket, {'cmd': 'ReceivedItems', 'index': 3, 'items': [entry]})
            self.assertIsNone(adapter.gate)
            self.assertEqual(socket.packets[-1], {'cmd': 'Sync'})

    def test_observer_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not playable'):
            Client('Tester', '.', Observer.__new__(Observer))

    def test_address_validation(self):
        self.assertEqual(server_uri('localhost:38281'), 'ws://localhost:38281')
        for address in ('https://host', 'ws://user:pass@host', 'ws://host/path', 'ws://host?x=1', 'host:bad'):
            with self.assertRaises(ValueError):
                server_uri(address)

    async def test_websocket_reconnect_deduplicates_and_locks_on_disconnect(self):
        config = Config()
        adapter = Adapter()
        config_packet = {'cmd': 'Connected', 'team': 0, 'slot': 1, 'checked_locations': [],
                         'missing_locations': [check.id for check in config.active_checks], 'slot_data': config.slot_data()}
        entries = [{'item': ITEM_IDS[name], 'location': index, 'player': 1, 'flags': 0}
                   for index, name in enumerate((PROGRESSIVE_CHAPTER, 'Health Kit'))]
        checks_received = []
        server_errors = []

        async def handler(socket):
            try:
                await socket.send(json.dumps([{'cmd': 'RoomInfo', 'seed_name': 'test-seed'}]))
                hello = json.loads(await socket.recv())[0]
                self.assertEqual(hello['game'], GAME)
                self.assertEqual(hello['items_handling'], 7)
                await socket.send(json.dumps([config_packet]))
                self.assertEqual(json.loads(await socket.recv())[0]['cmd'], 'Sync')
                await socket.send(json.dumps([{'cmd': 'ReceivedItems', 'index': 0, 'items': entries},
                                              {'cmd': 'ReceivedItems', 'index': 1, 'items': entries[1:]}]))
                while True:
                    for packet in json.loads(await asyncio.wait_for(socket.recv(), 3)):
                        if packet['cmd'] == 'LocationChecks':
                            checks_received.append(packet['locations'])
                            await socket.send(json.dumps([{'cmd': 'RoomUpdate', 'checked_locations': packet['locations']}]))
                            await socket.close()
                            return
            except Exception as error:
                server_errors.append(error)
                await socket.close()

        with tempfile.TemporaryDirectory() as directory:
            client = Client('Tester', directory, adapter)
            async with serve(handler, '127.0.0.1', 0) as server:
                port = server.sockets[0].getsockname()[1]
                for _ in range(2):
                    with self.assertRaises(ConnectionClosed):
                        await asyncio.wait_for(client.connect(f'127.0.0.1:{port}'), 5)
                    self.assertIsNone(adapter.gate)
            self.assertFalse(server_errors, server_errors)
            self.assertEqual(len(client.session.unlocked), 3)
            self.assertEqual(len(adapter.deliveries), 1)
            self.assertEqual(checks_received[0], checks_received[1])
            self.assertEqual(len(checks_received[0]), 2)  # Hometown mission and chapter


if __name__ == '__main__':
    unittest.main()
