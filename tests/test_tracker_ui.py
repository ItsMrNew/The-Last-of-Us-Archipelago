"""Tk integration tests use isolated settings and never attach to a game."""
import json
from dataclasses import replace
import logging
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from tlou_ap.catalog import Config
from tlou_ap.session import Session
from tlou_ap.tracker import snapshot
from tlou_ap.theme import PALETTES
from tlou_ap.launcher import Launcher


class TrackerUITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.patch = patch('tlou_ap.launcher.STATE', Path(self.folder.name))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.root = tk.Tk(); self.root.withdraw()
        self.callbacks = []
        self.root.report_callback_exception = lambda *args: self.callbacks.append(args)
        self.app = Launcher(self.root)
        self.addCleanup(self.close)

    def close(self):
        for callback in self.root.tk.call('after', 'info'):
            self.root.after_cancel(callback)
        self.root.update_idletasks()
        self.root.destroy()
        for handler in list(logging.getLogger('tlou-ap').handlers):
            handler.close(); logging.getLogger('tlou-ap').removeHandler(handler)

    def test_theme_switch_from_tracker_updates_both_windows_and_saves_settings(self):
        self.app.server.set('example.test:38281'); self.app.slot.set('TestSlot')
        self.app.show_tracker(); tracker = self.app.tracker
        self.assertIs(tracker.appearance, self.app.appearance)
        for mode in ('Dark', 'Light', 'Dark'):
            tracker.appearance.choice.set(mode); tracker.appearance.change()
            self.root.update()
            palette = PALETTES[mode.lower()]
            self.assertEqual(self.app.output.cget('background'), palette['field'])
            for campaign in (tracker.campaign, self.app.campaign):
                self.assertEqual(campaign.table.tag_configure('available')['foreground'], palette['available'])
            self.assertEqual(self.app.appearance.style.lookup('Treeview', 'background'), palette['field'])
            settings = json.loads(self.app.settings_path.read_text())
            self.assertEqual((settings['theme'], settings['server'], settings['slot']),
                             (mode.lower(), 'example.test:38281', 'TestSlot'))
        self.assertFalse(self.callbacks)
        tracker.window.destroy(); self.app.show_tracker()
        self.assertEqual(self.app.tracker.appearance.name, 'dark')

    def test_inline_and_enlarged_filters_and_selection_do_not_change_session(self):
        session = Session(Path(self.folder.name) / 'sessions', 'sample', 0, 1, 'fixture', Config())
        for mission in range(3): session.complete_mission(mission)
        before = session.path.read_bytes()
        self.app.tracker_view = snapshot(session, session.earned_checks, connected=True, synchronized=True)
        self.app.campaign.update(self.app.tracker_view)
        self.app.show_tracker()
        for tracker in (self.app.campaign, self.app.tracker.campaign):
            self.assertEqual(len(tracker.table.get_children()), 29)
            self.assertEqual(tracker.table.get_children('m:15'),
                             ('c:19711015', 'c:19713037', 'c:19713036', 'c:19713031', 'c:19713039'))
            tracker.search.set('Drafting Notice'); self.root.update()
            self.assertEqual(tracker.table.get_children(), ('m:3',))
            self.assertEqual(tracker.table.get_children('m:3'), ('c:19713001',))
            self.assertTrue(tracker.table.item('m:3', 'open'))
            tracker.table.selection_set('c:19713001'); self.root.update()
            self.assertIn('can be attempted', tracker.detail.cget('text'))
            self.assertEqual(tracker.table.item('m:3', 'values')[1], '0/5')
            tracker.categories['collectible'].set(False); tracker.render()
            self.assertFalse(tracker.table.get_children())
            self.assertFalse(tracker.table.selection())
            tracker.reset_filters()
            self.assertEqual(len(tracker.table.get_children()), 29)
        self.assertEqual(session.path.read_bytes(), before)
        self.assertFalse(self.callbacks)

    def test_live_refresh_preserves_expansion_selection_and_offline_progress(self):
        session = Session(Path(self.folder.name) / 'sessions', 'sample', 0, 1, 'fixture', Config())
        view = snapshot(session, (), connected=True, synchronized=True, current=3)
        tracker = self.app.campaign; tracker.update(view)
        tracker.table.item('m:3', open=False)
        tracker.table.item('m:4', open=True)
        tracker.table.selection_set('c:19712001')
        tracker.update(replace(view, connected=False)); self.root.update()
        self.assertFalse(tracker.table.item('m:3', 'open'))
        self.assertTrue(tracker.table.item('m:4', 'open'))
        self.assertEqual(tracker.table.selection(), ('c:19712001',))
        self.assertEqual(tracker.table.item('m:4', 'values')[0], 'Unknown')
        self.assertIn('unknown', tracker.detail.cget('text'))
        tracker.search.set('Drafting'); self.root.update()
        tracker.reset_filters()
        self.assertFalse(tracker.table.item('m:3', 'open'))
        self.assertTrue(tracker.table.item('m:4', 'open'))
        tracker.update(None)
        self.assertFalse(tracker.table.get_children())
        self.assertFalse(tracker.table.exists('c:19713001'))
        self.assertFalse(self.callbacks)

    def test_hidden_completed_mission_remains_when_collectibles_are_unfinished(self):
        session = Session(Path(self.folder.name) / 'sessions', 'sample', 0, 1, 'fixture', Config())
        for mission in range(4): session.complete_mission(mission)
        view = snapshot(session, session.earned_checks, connected=True, synchronized=True)
        tracker = self.app.campaign; tracker.update(view)
        tracker.hide_completed.set(True); tracker.render(); self.root.update()
        self.assertNotIn('m:0', tracker.table.get_children())
        self.assertIn('m:3', tracker.table.get_children())
        self.assertEqual(tracker.table.item('m:3', 'values'), ('Available', '1/5'))
        self.assertNotIn('c:19711003', tracker.table.get_children('m:3'))
        self.assertIn('c:19713001', tracker.table.get_children('m:3'))
        self.assertFalse(self.callbacks)

    def test_saved_theme_is_loaded_on_a_fresh_launcher(self):
        self.app.appearance.choice.set('Dark'); self.app.appearance.change()
        # Recreate the launcher with the same isolated state, as on application restart.
        self.close()
        self.root = tk.Tk(); self.root.withdraw()
        self.app = Launcher(self.root)
        self.assertEqual(self.app.appearance.name, 'dark')
        self.assertEqual(self.app.output.cget('background'), PALETTES['dark']['field'])
