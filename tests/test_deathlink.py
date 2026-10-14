import json
import tempfile
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tlou_ap.catalog import Config
from tlou_ap.client import Client
from tlou_ap.deathlink import DeathLink
from tlou_ap.native.deathlink import NativeDeathLink
from tlou_ap.session import Session
from test_client import Adapter


def bounced(source='Friend', stamp=123, **extra):
    return {'cmd': 'Bounced', 'tags': ['DeathLink'],
            'data': {'source': source, 'time': stamp, **extra}}


class DeathLinkTests(unittest.TestCase):
    def test_option_preserves_existing_off_seeds(self):
        off, on = Config(), Config(death_link=True)
        self.assertEqual(off.slot_data()['schema_version'], 1)
        self.assertNotIn('death_link', off.slot_data())
        self.assertEqual(on.slot_data()['schema_version'], 2)
        for config in (off, on):
            self.assertEqual(Config.from_slot_data(config.slot_data(), [c.id for c in config.active_checks]), config)
        with self.assertRaises(ValueError):
            Config(death_link=1)

    def test_disabled_self_echo_duplicates_and_dead_players(self):
        state = DeathLink()
        self.assertIsNone(state.receive(bounced(), 'Me'))
        state.configure(True)
        self.assertIsNone(state.receive(bounced('Me'), 'Me'))
        self.assertIsNotNone(state.receive(bounced(), 'Me'))
        self.assertIsNone(state.receive(bounced(stamp=124), 'Me'))  # Burst coalesces.
        state.confirmed_death()
        self.assertIsNone(state.receive(bounced(), 'Me'))
        self.assertIsNone(state.receive(bounced(stamp=125), 'Me', dead=True))
        self.assertIsNone(state.pending)

    def test_invalid_packets_never_queue_a_death(self):
        state = DeathLink(); state.configure(True)
        for packet in ({}, {'tags': ['DeathLink']}, bounced(stamp=float('nan')), bounced(stamp=True),
                       bounced(source=''), bounced(stamp=-1), bounced(stamp=float('inf')), bounced(stamp=10**1000)):
            self.assertIsNone(state.receive(packet, 'Me'))
        toast = state.receive(bounced(cause='Hello\x00\nWorld'), 'Me')
        self.assertEqual(toast.detail, 'Hello World')

    def test_waits_indefinitely_until_control_disconnect_or_natural_death(self):
        now = [0]
        state = DeathLink(lambda: now[0], lambda: 99.5); state.configure(True)
        state.receive(bounced(), 'Me'); now[0] = 36000
        self.assertEqual(state.pending['source'], 'Friend')
        state.configure(False, preserve_pending=True)
        state.configure(True, preserve_pending=True)
        self.assertEqual(state.pending['source'], 'Friend')
        state.configure(False); state.configure(True)
        self.assertIsNotNone(state.pending)
        self.assertIsNone(state.receive(bounced(), 'Me'))
        state.receive(bounced(stamp=125), 'Me')
        packet = state.local_death('Me')
        self.assertEqual(packet['data']['time'], 99.5)
        self.assertIsNone(state.pending)
        self.assertIsNone(state.receive({**packet, 'cmd': 'Bounced'}, 'Me'))

    def test_native_mailbox_is_nonblocking_and_receipt_epoch_changes_on_reconnect(self):
        calls = []
        result = [None]
        shared = SimpleNamespace(death_local=7, death_remote=8, death_enabled=0, death_state=2, current=3)
        bridge = SimpleNamespace(shared=shared, command_busy=False,
            begin_command=lambda *args: calls.append(args) or len(calls), command_result=lambda seq: result[0])
        native = NativeDeathLink(bridge); native.configure(True)
        self.assertFalse(native.poll()['local'])
        first_epoch = shared.death_enabled
        reservations = []
        self.assertEqual(native.deliver('gift', before_submit=reservations.append), 'pending')
        self.assertEqual(native.deliver('gift', before_submit=reservations.append), 'pending')
        self.assertEqual(len(calls), 1); self.assertEqual(reservations, ['gift'])
        self.assertEqual(calls[0][2] >> 32, first_epoch)
        result[0] = 1
        self.assertEqual(native.deliver('gift', before_submit=reservations.append), 'submitted')
        shared.death_remote += 1
        self.assertTrue(native.poll()['remote']); self.assertFalse(native.poll()['remote'])
        shared.death_local += 1
        self.assertTrue(native.poll()['local']); self.assertFalse(native.poll()['local'])
        native.configure(False); self.assertEqual(shared.death_enabled, 0)
        native.configure(True); self.assertNotEqual(first_epoch, shared.death_enabled)


class DeathAdapter(Adapter):
    capabilities = Adapter.capabilities | {'death_link'}

    def __init__(self):
        super().__init__(); self.enabled = self.dead = self.local = self.remote = False
        self.deaths = []
        self.outcome = 'not_applied'

    def configure_death_link(self, enabled): self.enabled = enabled
    def death_link_dead(self): return self.dead
    def clear_death_link_command(self): pass
    def deliver_death_link(self, receipt, *, before_submit):
        if self.outcome == 'submitted':
            before_submit(receipt)
            self.deaths.append(receipt)
        return self.outcome

    def poll_death_link(self):
        result = dict(local=self.local, remote=self.remote, dead=self.dead)
        self.local = self.remote = False
        return result


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_client_and_game_adapter_restore_the_same_waiting_death(self):
        class Socket:
            async def send(self, data): pass
        with tempfile.TemporaryDirectory() as folder:
            config, socket = Config(death_link=True), Socket()
            packet = dict(cmd='Connected', team=0, slot=1, checked_locations=[],
                missing_locations=[c.id for c in config.active_checks], slot_data=config.slot_data())
            client = Client('Me', folder, DeathAdapter()); client.seed = 'persistent'
            await client.handle(socket, packet); await client.handle(socket, bounced())
            receipt = client.deathlink.pending['receipt']
            client.configure_death_link(False)
            # Recreating both objects models closing the client and restarting the game.
            adapter = DeathAdapter()
            resumed = Client('Me', folder, adapter); resumed.seed = 'persistent'
            await resumed.handle(socket, packet)
            self.assertEqual(resumed.deathlink.pending['receipt'], receipt)
            for _ in range(3): await resumed.poll(socket)
            self.assertEqual(adapter.deaths, [])
            adapter.outcome = 'submitted'
            await resumed.poll(socket); await resumed.poll(socket)
            self.assertEqual(adapter.deaths, [receipt])
            adapter.remote = True; await resumed.poll(socket)
            again = Client('Me', folder, DeathAdapter()); again.seed = 'persistent'
            await again.handle(socket, packet); await again.handle(socket, bounced())
            self.assertEqual(again.deathlink.state, 'idle')

    async def test_restarted_client_never_replays_an_ambiguous_dispatch(self):
        class Socket:
            async def send(self, data): pass
        with tempfile.TemporaryDirectory() as folder:
            config, socket = Config(death_link=True), Socket()
            packet = dict(cmd='Connected', team=0, slot=1, checked_locations=[],
                missing_locations=[c.id for c in config.active_checks], slot_data=config.slot_data())
            client = Client('Me', folder, DeathAdapter()); client.seed = 'ambiguous'
            await client.handle(socket, packet); await client.handle(socket, bounced())
            client.deathlink.reserve(client.deathlink.pending['receipt'])
            adapter = DeathAdapter(); adapter.outcome = 'submitted'
            resumed = Client('Me', folder, adapter); resumed.seed = 'ambiguous'
            await resumed.handle(socket, packet)
            for _ in range(3): await resumed.poll(socket)
            self.assertEqual(adapter.deaths, [])
            self.assertEqual(resumed.deathlink.state, 'held')
            adapter.local = True; await resumed.poll(socket)
            self.assertEqual(resumed.deathlink.state, 'idle')

    async def test_waiting_death_survives_same_run_reconnect_but_not_identity_change(self):
        class Socket:
            async def send(self, data): pass

        with tempfile.TemporaryDirectory() as folder:
            adapter, socket = DeathAdapter(), Socket()
            client = Client('Me', folder, adapter)
            config = Config(death_link=True)
            connected = dict(cmd='Connected', team=0, slot=1, checked_locations=[],
                missing_locations=[c.id for c in config.active_checks], slot_data=config.slot_data())
            client.seed = 'first'
            await client.handle(socket, connected)
            await client.handle(socket, bounced())
            receipt = client.deathlink.pending['receipt']
            client.configure_death_link(False, preserve_pending=True)
            self.assertFalse(adapter.enabled)
            await client.handle(socket, connected)
            self.assertEqual(client.deathlink.pending['receipt'], receipt)
            await client.poll(socket)
            self.assertEqual(client.deathlink.pending['receipt'], receipt)
            client.seed = 'second'
            await client.handle(socket, connected)
            self.assertIsNone(client.deathlink.pending)
            await client.handle(socket, bounced(stamp=124))
            self.assertIsNotNone(client.deathlink.pending)
            await client.handle(socket, {**connected, 'slot': 2})
            self.assertIsNone(client.deathlink.pending)
            client.seed = 'first'
            await client.handle(socket, connected)
            self.assertEqual(client.deathlink.pending['receipt'], receipt)

    async def test_subscription_receipt_delivery_and_outbound_no_echo(self):
        class Socket:
            def __init__(self): self.packets = []
            async def send(self, data): self.packets.extend(json.loads(data))
        with tempfile.TemporaryDirectory() as folder:
            adapter, socket, notices = DeathAdapter(), Socket(), []
            client = Client('Me', folder, adapter, notify=notices.append)
            client.seed = 'test'
            config = Config(death_link=True)
            await client.handle(socket, dict(cmd='Connected', team=0, slot=1, checked_locations=[],
                missing_locations=[c.id for c in config.active_checks], slot_data=config.slot_data()))
            self.assertIn({'cmd': 'ConnectUpdate', 'tags': ['AP', 'DeathLink']}, socket.packets)
            await client.handle(socket, bounced())
            await client.poll(socket); self.assertTrue(client.deathlink.pending)
            adapter.outcome = 'submitted'
            await client.poll(socket); self.assertIsNone(client.deathlink.pending)
            self.assertEqual(client.deathlink.state, 'awaiting_death')
            adapter.remote = True
            await client.poll(socket)
            await client.handle(socket, bounced())
            await client.poll(socket)
            self.assertEqual(len(adapter.deaths), 1)
            self.assertFalse(any(p['cmd'] == 'Bounce' for p in socket.packets))
            adapter.local = True
            await client.poll(socket); await client.poll(socket)
            self.assertEqual(sum(p['cmd'] == 'Bounce' for p in socket.packets), 1)
            self.assertEqual([t.item for t in notices], ['Received', 'Applied', 'Sent'])


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.session = Session(self.folder.name, 'seed', 0, 1, 'run', Config(death_link=True))
        self.state = self.reopen()

    def reopen(self, session=None):
        state = DeathLink()
        state.bind(session or self.session)
        state.configure(True)
        return state

    def queue(self):
        self.state.receive(bounced(), 'Me')
        return self.state.pending['receipt']

    def test_waiting_death_and_burst_history_survive_restart(self):
        receipt = self.queue()
        self.state.receive(bounced(stamp=124), 'Me')
        resumed = self.reopen()
        self.assertEqual(resumed.pending['receipt'], receipt)
        resumed.confirmed_death()
        resumed = self.reopen()
        self.assertIsNone(resumed.receive(bounced(), 'Me'))
        self.assertIsNone(resumed.receive(bounced(stamp=124), 'Me'))
        self.assertIsNotNone(resumed.receive(bounced(stamp=125), 'Me'))

    def test_all_identity_fields_isolate_queues_and_restore_original(self):
        receipt = self.queue()
        for seed, team, slot, run in [('other', 0, 1, 'run'), ('seed', 1, 1, 'run'),
                                      ('seed', 0, 2, 'run'), ('seed', 0, 1, 'other')]:
            with self.subTest(seed=seed, team=team, slot=slot, run=run):
                other = Session(self.folder.name, seed, team, slot, run, Config(death_link=True))
                self.state.bind(other)
                self.assertIsNone(self.state.pending)
                self.assertIsNotNone(self.state.receive(bounced(), 'Me'))
        self.state.bind(self.session)
        self.assertEqual(self.state.pending['receipt'], receipt)

    def test_dispatch_interruption_is_held_until_a_confirmed_death(self):
        receipt = self.queue()
        self.state.reserve(receipt)
        resumed = self.reopen()
        self.assertEqual(resumed.state, 'held')
        self.assertIsNone(resumed.pending)
        self.assertIsNone(resumed.receive(bounced(stamp=124), 'Me'))
        resumed.local_death('Me')
        self.assertEqual(self.reopen().state, 'idle')

    def test_submission_does_not_claim_actual_death(self):
        receipt = self.queue(); self.state.reserve(receipt)
        self.state.resolve(receipt, 'submitted')
        self.assertEqual(self.state.state, 'awaiting_death')
        self.assertEqual(self.reopen().state, 'held')
        self.state.confirmed_death()
        self.assertEqual(self.reopen().state, 'idle')

    def test_native_rejection_restores_waiting_but_uncertain_does_not_retry(self):
        receipt = self.queue(); self.state.reserve(receipt)
        self.state.resolve(receipt, 'not_applied')
        self.assertEqual(self.reopen().pending['receipt'], receipt)
        self.state.reserve(receipt)
        self.state.resolve(receipt, 'uncertain')
        self.assertEqual(self.reopen().state, 'held')

    def test_unconfirmed_native_event_is_held(self):
        receipt = self.queue(); self.state.reserve(receipt)
        self.state.resolve(receipt, 'submitted'); self.state.unconfirmed()
        self.assertEqual(self.state.state, 'held')
        self.assertIsNone(self.state.pending)

    def test_failed_write_leaves_last_good_queue_and_memory_intact(self):
        receipt = self.queue()
        before = self.state.path.read_bytes()
        with patch('tlou_ap.deathlink.atomic_json', side_effect=OSError('Disk full')):
            with self.assertRaises(OSError): self.state.reserve(receipt)
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertEqual(self.state.state, 'queued')

    def test_bad_journal_is_preserved_and_rejected(self):
        self.queue()
        good = json.loads(self.state.path.read_text())
        for content in ('{broken', json.dumps({**good, 'identity': {**good['identity'], 'slot': 2}}),
                        json.dumps({**good, 'incoming': {'state': 'queued'}}),
                        json.dumps({**good, 'seen': [['Friend', True]]})):
            with self.subTest(content=content):
                self.state.path.write_text(content)
                with self.assertRaises(ValueError): self.reopen()
                self.assertEqual(self.state.path.read_text(), content)

    def test_real_process_exit_preserves_waiting_or_holds_dispatch(self):
        script = '''
import os, sys
from tlou_ap.catalog import Config
from tlou_ap.session import Session
from tlou_ap.deathlink import DeathLink
s = Session(sys.argv[1], 'seed', 0, 1, 'run', Config(death_link=True))
d = DeathLink(); d.bind(s); d.configure(True)
d.receive({'tags':['DeathLink'], 'data':{'source':'Friend', 'time':123}}, 'Me')
if sys.argv[2] == 'dispatch': d.reserve(d.pending['receipt'])
os._exit(0)
'''
        for phase, expected in [('queue', 'queued'), ('dispatch', 'held')]:
            subprocess.run([sys.executable, '-c', script, self.folder.name, phase], check=True,
                           cwd=Path(__file__).resolve().parents[1], timeout=20)
            self.assertEqual(self.reopen().state, expected)

    def test_native_never_dispatches_without_durable_reservation(self):
        receipt = self.queue()
        calls = []
        def begin(*args):
            self.assertEqual(json.loads(self.state.path.read_text())['incoming']['state'], 'dispatching')
            calls.append(args)
            return 1
        shared = SimpleNamespace(death_local=0, death_remote=0, death_enabled=0, death_state=0, current=3)
        native = NativeDeathLink(SimpleNamespace(shared=shared, command_busy=False,
                                                begin_command=begin, command_result=lambda _: None))
        native.configure(True)
        for unavailable in (0, 1, 3):
            shared.death_state = unavailable
            self.assertEqual(native.deliver(receipt, before_submit=self.state.reserve), 'not_applied')
            self.assertEqual(self.state.state, 'queued')
        shared.death_state = 2
        with patch('tlou_ap.deathlink.atomic_json', side_effect=OSError('Disk full')):
            with self.assertRaises(OSError): native.deliver(receipt, before_submit=self.state.reserve)
        self.assertEqual(calls, [])
        self.assertEqual(native.deliver(receipt, before_submit=self.state.reserve), 'pending')
        self.assertEqual(len(calls), 1)
