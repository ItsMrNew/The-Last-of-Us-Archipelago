import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from websockets.legacy.server import serve
from websockets.exceptions import ConnectionClosed

from tlou_ap.catalog import Config, GAME, ITEM_IDS
from tlou_ap.client import Client, REQUIRED_CAPABILITIES
from tlou_ap.notifications import (TransferFeed, Toast, ToastQueue, clean_text, item_colour,
                                   validate_settings, UNKNOWN_ITEM_COLOUR)


def connected():
    return {'cmd': 'Connected', 'team': 0, 'slot': 1,
            'players': [{'team': 0, 'slot': 1, 'alias': 'Joel'}, {'team': 0, 'slot': 2, 'alias': 'Friend'}],
            'slot_info': {'1': {'name': 'Survivor', 'game': GAME},
                          '2': {'name': 'Partner', 'game': 'Other Game'},
                          '3': {'name': 'Shared Items', 'game': GAME, 'group_members': [1, 4]}},
            'checked_locations': [], 'missing_locations': [c.id for c in Config().active_checks],
            'slot_data': Config().slot_data()}


def event(sender=1, recipient=2, item=10, location=19711000, flags=1):
    return {'cmd': 'PrintJSON', 'type': 'ItemSend', 'receiving': recipient,
            'item': {'player': sender, 'item': item, 'location': location, 'flags': flags}}


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 0
        self.feed = TransferFeed(self.temp.name, clock=lambda: self.now)
        self.feed.connected('seed', connected())
        self.package = {'cmd': 'DataPackage', 'data': {'games': {'Other Game': {
            'item_name_to_id': {'Master Sword': 10}, 'location_name_to_id': {'Forest Chest': 200}}}}}

    def test_exact_zero_hour_colours_and_precedence(self):
        self.assertEqual([item_colour(n) for n in (0, 1, 2, 4, 3, 6, 7)],
                         ['#00EEEE', '#AF99EF', '#6D8BE8', '#FA8072', '#AF99EF', '#6D8BE8', '#AF99EF'])

    def test_server_classification_wins_for_any_game_and_item_name(self):
        self.feed.data_package({'data': {'games': {'Other Game': {
            'item_name_to_id': {'Airhorn Trap': 10}}}}})
        for recipient, code in ((1, ITEM_IDS['Airhorn Trap']), (2, 10)):
            for flags, colour in ((0, '#00EEEE'), (1, '#AF99EF'), (2, '#6D8BE8'),
                                  (4, '#FA8072'), (6, '#6D8BE8'), (7, '#AF99EF')):
                with self.subTest(recipient=recipient, flags=flags):
                    self.feed.receive(event(1, recipient, code, 300 + flags, flags))
                    toast = self.feed.drain()[0]
                    self.assertEqual((toast.item, toast.colour), ('Airhorn Trap', colour))
                    self.assertEqual(toast.parts[1], ('Airhorn Trap', colour))

    def test_unclassified_grants_and_missing_or_invalid_flags_are_neutral(self):
        for kind in ('ItemSend', 'ItemCheat'):
            for flags in (None, False, '4', -1, 8, 0, 4):
                packet = event(0, 1, ITEM_IDS['Airhorn Trap'], -1, flags)
                packet['type'] = kind
                if flags is None:
                    del packet['item']['flags']
                self.feed.receive(packet)
                self.assertEqual(self.feed.drain()[0].colour,
                                 '#FA8072' if flags == 4 else UNKNOWN_ITEM_COLOUR)
        # Missing metadata on a real check is also unknown, not filler.
        packet = event(2, 1, ITEM_IDS['Health Kit'], 99)
        del packet['item']['flags']
        self.feed.receive(packet)
        self.assertEqual(self.feed.drain()[0].colour, UNKNOWN_ITEM_COLOUR)

    def test_wait_for_foreign_names_then_resolve_both_directions(self):
        self.feed.receive(event())
        self.assertEqual(self.feed.drain(), [])
        self.feed.data_package(self.package)
        outgoing = self.feed.drain()[0]
        self.assertEqual((outgoing.heading, outgoing.item, outgoing.detail), ('ITEM SENT', 'Master Sword', 'To Friend'))
        self.assertIn('Hometown', outgoing.location)
        self.feed.receive(event(2, 1, ITEM_IDS['Ammo Supply'], 200, 0))
        incoming = self.feed.drain()[0]
        self.assertEqual((incoming.heading, incoming.detail, incoming.location, incoming.colour),
                         ('ITEM RECEIVED', 'From Friend', 'Forest Chest', '#00EEEE'))

    def test_restart_deduplicates_real_checks_but_new_seed_and_grants_do_not(self):
        self.feed.receive(event())
        resumed = TransferFeed(self.temp.name)
        resumed.connected('seed', connected())
        resumed.receive(event())
        self.assertFalse(resumed.waiting)
        resumed.connected('another-seed', connected())
        resumed.receive(event())
        self.assertEqual(len(resumed.waiting), 1)
        for _ in range(2):
            resumed.receive(event(0, 1, ITEM_IDS['Health Kit'], -1, 0))
        self.assertEqual(len(resumed.drain()), 2)

    def test_group_receipt_self_find_and_unrelated_transfers(self):
        self.feed.receive(event(2, 3, ITEM_IDS['Health Kit'], 201, 0))
        group = self.feed.drain()[0]
        self.assertTrue(group.involves_local)
        self.assertIn('Shared Items', group.detail)
        self.feed.receive(event(1, 1, ITEM_IDS['Health Kit'], 19712000, 0))
        self.assertEqual(self.feed.drain()[0].heading, 'ITEM FOUND')
        self.feed.receive(event(2, 2, 10, 202, 1))
        self.feed.data_package(self.package)
        self.assertFalse(self.feed.drain()[0].involves_local)

    def test_unavailable_names_time_out_without_blocking_other_transfers(self):
        self.feed.receive(event())
        self.feed.receive(event(2, 1, ITEM_IDS['Health Kit'], 200, 0))
        self.assertEqual(self.feed.drain()[0].item, 'Health Kit')
        self.now = 5
        self.assertEqual(self.feed.drain()[0].item, 'Item #10')

    def test_unrelated_packets_and_wrong_team_do_not_create_toasts(self):
        for packet in ({**event(), 'type': 'Hint'}, {**event(), 'team': 1},
                       {'cmd': 'ReceivedItems', 'index': 0, 'items': [event()['item']]},
                       {**event(), 'item': {'player': True, 'item': 1, 'location': 1, 'flags': 1}}):
            self.feed.receive(packet)
        self.assertFalse(self.feed.waiting)
        self.assertEqual(clean_text('Éllie\u202e\n\x00  Test'), 'Éllie Test')

    def test_queue_pauses_when_alt_tabbed_and_settings_remove_other_players(self):
        queue = ToastQueue(clock=lambda: self.now)
        own = Toast('ITEM RECEIVED', 'Ammo', 'From Friend', '', '#00EEEE')
        other = Toast('ITEM TRANSFER', 'Sword', 'Friend to Other', '', '#AF99EF', False)
        queue.configure({'scope': 'all', 'seconds': 8})
        for toast in (own, other, own):
            queue.add(toast)
        self.assertEqual(queue.tick(True), (own, other))
        self.now = 3
        queue.tick(True)
        queue.tick(False)
        self.now = 100
        self.assertEqual(queue.tick(True), (own, other))
        queue.configure({'scope': 'you', 'seconds': 8})
        self.assertEqual(queue.tick(True), (own, own))
        self.now = 105
        self.assertEqual(queue.tick(True), (own,))
        queue.configure({'scope': 'off', 'seconds': 8})
        self.assertFalse(queue.tick(True))
        for invalid in ({'scope': 'you', 'seconds': True}, {'scope': 'x', 'seconds': 8}):
            with self.assertRaises(ValueError):
                validate_settings(invalid)


class NotificationProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_loopback_transfers_inventory_reconnect_and_coloured_callback(self):
        class Adapter:
            capabilities = REQUIRED_CAPABILITIES
            run_id = 'notification-test'
            def set_gate(self, session): pass
            def bind(self, identity, resume): pass
            def observe(self, session): pass
            def can_deliver(self, item): return False

        received, errors = [], []
        package = {'cmd': 'DataPackage', 'data': {'games': {'Other Game': {
            'item_name_to_id': {'Sword': 10}, 'location_name_to_id': {'Chest': 200}}}}}

        async def handler(socket):
            try:
                await socket.send(json.dumps([{'cmd': 'RoomInfo', 'seed_name': 'loopback'}]))
                await socket.recv()
                await socket.send(json.dumps([connected()]))
                self.assertEqual(json.loads(await socket.recv())[0]['cmd'], 'Sync')
                self.assertEqual(json.loads(await socket.recv())[0]['cmd'], 'GetDataPackage')
                await socket.send(json.dumps([package, {'cmd': 'ReceivedItems', 'index': 0, 'items': [
                    {'item': ITEM_IDS['Ammo Supply'], 'player': 2, 'location': 200, 'flags': 0}]},
                    event(), event(2, 1, ITEM_IDS['Ammo Supply'], 200, 0), event()]))
                for _ in range(30):
                    if len(received) >= 2:
                        break
                    await asyncio.sleep(.02)
                await socket.close()
            except Exception as error:
                errors.append(error)

        with tempfile.TemporaryDirectory() as directory:
            async with serve(handler, '127.0.0.1', 0) as server:
                port = server.sockets[0].getsockname()[1]
                for _ in range(2):
                    client = Client('Survivor', directory, Adapter(), notify=received.append)
                    with self.assertRaises(ConnectionClosed):
                        await client.connect(f'127.0.0.1:{port}')
            self.assertFalse(errors, errors)
            self.assertEqual([(t.heading, t.item, t.colour) for t in received],
                             [('ITEM SENT', 'Sword', '#AF99EF'), ('ITEM RECEIVED', 'Ammo Supply', '#00EEEE')])

    async def test_notification_storage_failure_does_not_stop_game_checks(self):
        class Adapter:
            capabilities = REQUIRED_CAPABILITIES
            run_id = 'storage-test'
            def set_gate(self, session): pass
            def bind(self, identity, resume): pass
        class Socket:
            async def send(self, message): pass
        with tempfile.TemporaryDirectory() as directory:
            client = Client('Survivor', directory, Adapter())
            client.seed = 'seed'
            await client.handle(Socket(), connected())
            with patch('tlou_ap.notifications.atomic_json', side_effect=OSError('Disk unavailable')):
                await client.handle(Socket(), event())
            self.assertTrue(client.connected)
            self.assertEqual(client.session.data['missions'], [])


if __name__ == '__main__':
    unittest.main()
