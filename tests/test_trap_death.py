import json
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tlou_ap.airhorn import Airhorn
from tlou_ap.catalog import AIRHORN, ITEM_IDS, Config
from tlou_ap.session import Session, ReceivedItem
from tlou_ap.native.airhorn import NativeAirhorn
from tlou_ap.client import Client, REQUIRED_CAPABILITIES


class Adapter:
    capabilities = REQUIRED_CAPABILITIES | {'airhorn'}
    ready = True
    clock = 0
    outcome = 'applied'
    calls = 0
    cancelled = False

    def airhorn_status(self):
        return {'instance': 'game', 'clock': self.clock, 'ready': self.ready}

    def airhorn_pulse(self, receipt, instance, *, before_submit):
        before_submit()
        self.calls += 1
        return self.outcome

    def set_player_death_handler(self, callback):
        self.on_death = callback

    def set_timed_effects(self, values):
        pass

    def cancel_trap_commands(self):
        self.cancelled = True


class TrapDeathTests(unittest.TestCase):
    def setup_horn(self, folder, count=3, mode='timed'):
        session = Session(folder, 'seed', 0, 1, 'run', Config(airhorn_mode=mode, airhorn_duration=30))
        session.record_inventory([ReceivedItem(ITEM_IDS[AIRHORN], i, 1, 4) for i in range(count)])
        horn = Airhorn(); horn.bind(session)
        return horn, session, Adapter()

    def test_death_clears_entire_active_stack_and_survives_reconnect(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, adapter = self.setup_horn(folder)
            horn.poll(adapter)
            self.assertEqual(horn.timed_stack(), (90, 3))
            self.assertEqual(horn.clear_on_death('game:10'), 3)
            self.assertIsNone(horn.card())
            restored = Airhorn(); restored.bind(session); restored.poll(adapter)
            self.assertEqual(restored.queued, 0)
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(restored.clear_on_death('game:10'), 0)

    def test_unstarted_queue_survives_death(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, _, adapter = self.setup_horn(folder)
            adapter.ready = False; horn.poll(adapter)
            self.assertEqual(horn.clear_on_death('game:10'), 0)
            self.assertEqual(horn.queued, 3)
            adapter.ready = True; horn.poll(adapter)
            self.assertEqual(adapter.calls, 1)

    def test_pending_blast_cancelled_and_different_queue_block_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, _, adapter = self.setup_horn(folder)
            adapter.outcome = 'pending'; horn.poll(adapter)
            horn.data['items']['1']['mode'] = 'single_blast'; horn.save()
            self.assertEqual(horn.clear_on_death('game:10'), 1)
            self.assertEqual(horn.queued, 2)
            self.assertEqual(horn.current[0], '1')

    def test_failed_journal_write_leaves_cancellation_retryable(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, _, adapter = self.setup_horn(folder)
            horn.poll(adapter)
            with patch('tlou_ap.airhorn.atomic_json', side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError): horn.clear_on_death('game:10')
            self.assertEqual(horn.queued, 3)
            self.assertEqual(horn.clear_on_death('game:10'), 3)

    def test_duplicate_death_does_not_clear_new_traps(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, adapter = self.setup_horn(folder, count=1)
            horn.poll(adapter); horn.clear_on_death('game:10')
            session.record_inventory([ReceivedItem(ITEM_IDS[AIRHORN], i, 1, 4) for i in range(2)])
            horn.poll(adapter)
            self.assertEqual(horn.clear_on_death('game:10'), 0)
            self.assertEqual(horn.queued, 1)
            self.assertEqual(horn.clear_on_death('game:20'), 1)

    def test_client_death_cleanup_does_not_depend_on_deathlink_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            horn, session, adapter = self.setup_horn(folder)
            client = Client('Tester', folder, adapter)
            client.session = session; client.airhorn = horn
            horn.poll(adapter)
            self.assertFalse(client.deathlink.enabled)
            adapter.on_death('game:10')
            self.assertTrue(adapter.cancelled)
            self.assertEqual(horn.queued, 0)

    def test_cancelled_mailbox_reply_cannot_become_new_trap_result(self):
        result = [None]
        bridge = SimpleNamespace(command_result=lambda seq: result[0])
        native = NativeAirhorn(bridge, 'game')
        native.command = ('old-pulse', 3); native.cancel_pending()
        self.assertTrue(native.discarding)
        self.assertEqual(native.pulse('new-pulse', None, before_submit=lambda: None,
                                      can_submit=True), 'not_applied')
        result[0] = 1; native.reap_cancelled()
        self.assertIsNone(native.command)
        self.assertFalse(native.discarding)


if __name__ == '__main__':
    unittest.main()
