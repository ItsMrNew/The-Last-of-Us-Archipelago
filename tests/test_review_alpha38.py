"""Failure-path regressions; isolated state, no game or real server access."""
import asyncio
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import test_run_profiles
import test_save_guide_ui
from tlou_ap.launcher import run_client
from tlou_ap.notifications import TransferFeed
from tlou_ap.session import atomic_json
from tlou_ap.save_guide_ui import SaveGuide


class RunSwitchFailureTests(unittest.TestCase):
    setUp = test_run_profiles.RunSelectorUITests.setUp
    close = test_run_profiles.RunSelectorUITests.close

    def test_failed_selection_write_keeps_original_run_and_fields(self):
        app = self.app
        original = app.run_name
        app.server.set('original.example:123'); app.slot.set('Original')
        app.password.set('temporary-secret'); app.run_description.set('Original run')
        app.save_run_description()
        other = app.run_profiles.create()
        app.run_profiles.update(other, description='Other run', server='other.example:456', slot='Other')
        before = app.settings_path.read_bytes()
        def persist(path, data):
            if data.get('run') == other: raise OSError('Disk full')
            atomic_json(path, data)
        with patch('tlou_ap.launcher.atomic_json', side_effect=persist):
            with self.assertRaises(OSError): app.switch_run(other)
        self.assertEqual(app.run_name, original)
        self.assertEqual((app.server.get(), app.slot.get(), app.password.get(), app.run_description.get()),
                         ('original.example:123', 'Original', 'temporary-secret', 'Original run'))
        self.assertEqual(app.settings_path.read_bytes(), before)
        self.assertEqual(app.run_selector.get(), app.run_profiles.label(original))


class WorkerCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def call_worker(self):
        stop = threading.Event(); stop.set()
        await run_client('room', 'slot', '', Path('fixture.json'), stop,
                         queue.Queue(), queue.Queue(), queue.Queue())

    async def test_client_initialization_failure_releases_adapter(self):
        adapter = Mock()
        with patch('tlou_ap.launcher.game_pid', return_value=123), \
                patch('tlou_ap.launcher.NativeAdapter', return_value=adapter), \
                patch('tlou_ap.launcher.Client', side_effect=ValueError('Invalid preferences')):
            with self.assertRaisesRegex(ValueError, 'Invalid preferences'): await self.call_worker()
        adapter.close.assert_called_once()

    async def test_test_controls_initialization_failure_releases_adapter(self):
        adapter = Mock()
        with patch('tlou_ap.launcher.game_pid', return_value=123), \
                patch('tlou_ap.launcher.NativeAdapter', return_value=adapter), \
                patch('tlou_ap.launcher.Client'), \
                patch('tlou_ap.launcher.TestControls', side_effect=OSError('Cannot open controls')):
            with self.assertRaisesRegex(OSError, 'Cannot open controls'): await self.call_worker()
        adapter.close.assert_called_once()

    async def test_controls_cleanup_failure_still_releases_adapter(self):
        adapter, controls = Mock(), Mock()
        controls.close.side_effect = OSError('Control cleanup failed')
        with patch('tlou_ap.launcher.game_pid', return_value=123), \
                patch('tlou_ap.launcher.NativeAdapter', return_value=adapter), \
                patch('tlou_ap.launcher.Client'), \
                patch('tlou_ap.launcher.TestControls', return_value=controls):
            with self.assertRaisesRegex(OSError, 'Control cleanup failed'): await self.call_worker()
        adapter.close.assert_called_once()


class NotificationHistoryFailureTests(unittest.TestCase):
    def test_reconnect_retries_validation_instead_of_overwriting_bad_history(self):
        packet = {'team': 0, 'slot': 1}
        with tempfile.TemporaryDirectory() as folder:
            good = TransferFeed(folder); good.connected('seed', packet)
            good.path.parent.mkdir(exist_ok=True)
            good.path.write_text('{broken', encoding='utf-8')
            feed = TransferFeed(folder)
            for _ in range(2):
                with self.assertRaises(ValueError): feed.connected('seed', packet)
                self.assertIsNone(feed.identity)
                self.assertIsNone(feed.path)
                self.assertEqual(good.path.read_text(), '{broken')
            good.path.write_text(json.dumps({'version': 1, 'identity': ['seed', 0, 1],
                                            'seen': [[1, 1, 2, 3]]}))
            feed.connected('seed', packet)
            self.assertEqual(feed.seen, {(1, 1, 2, 3)})

    def test_non_object_history_reports_validation_error(self):
        with tempfile.TemporaryDirectory() as folder:
            feed = TransferFeed(folder); feed.connected('seed', {'team': 0, 'slot': 1})
            feed.path.write_text('[]')
            with self.assertRaises(ValueError):
                TransferFeed(folder).connected('seed', {'team': 0, 'slot': 1})


class SaveGuideFailureTests(unittest.TestCase):
    setUp = test_save_guide_ui.SaveGuideUITests.setUp

    def test_unexpected_reader_error_clears_busy_and_old_green_labels(self):
        with patch('tlou_ap.save_guide_ui.default_savedata', side_effect=KeyError('malformed saved data')):
            SaveGuide.request_scan(self.guide)
            result = self.guide.results.get(timeout=2)
        self.guide.results.put(result)
        self.guide.tick()
        self.assertFalse(self.guide.busy)
        self.assertEqual(self.guide.entries, [])
        self.assertIsNone(self.guide.identity)
        self.assertIn('unavailable', self.guide.message)
        # A subsequent refresh can recover, instead of remaining busy forever.
        with patch('tlou_ap.save_guide_ui.default_savedata', return_value=Path(self.temp.name)), \
                patch('tlou_ap.save_guide_ui.SaveRegistry') as registry:
            registry.return_value.scan.return_value = []
            SaveGuide.request_scan(self.guide)
            result = self.guide.results.get(timeout=2)
        self.guide.results.put(result); self.guide.tick()
        self.assertFalse(self.guide.busy)
        self.assertNotIn('unavailable', self.guide.message)


if __name__ == '__main__': unittest.main()
