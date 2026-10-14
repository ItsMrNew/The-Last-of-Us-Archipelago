import json
import logging
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from tlou_ap.run_profiles import RunProfiles
from tlou_ap.native.run import RunLedger
from tlou_ap.session import Session
from tlou_ap.catalog import Config
from tlou_ap.launcher import Launcher
from tlou_ap.notifications import Toast
from tlou_ap.recovery import backup


class RunProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.first = RunLedger(self.state / 'runs/run-first.json', [])
        self.second = RunLedger(self.state / 'runs/run-second.json', [])
        self.settings = dict(run='run-first', server='room-one.example:123', slot='Player One')

    def test_migration_discovers_ledgers_not_recovery_or_controls(self):
        (self.state / 'runs/run-first.recovery-old.json').write_bytes(self.first.path.read_bytes())
        (self.state / 'runs/run-first.test-controls.json').write_text('{}')
        before = {p.name: p.read_bytes() for p in (self.state / 'runs').iterdir()}
        profiles = RunProfiles(self.state, self.settings)
        self.assertEqual(set(profiles.data['runs']), {'run-first', 'run-second'})
        self.assertEqual(profiles.data['runs']['run-first']['server'], self.settings['server'])
        self.assertEqual(profiles.data['runs']['run-second']['server'], '')
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.state / 'runs').iterdir()})

    def test_descriptions_rooms_and_new_unconnected_run_persist(self):
        profiles = RunProfiles(self.state, self.settings)
        profiles.update('run-second', description='Weekend co-op', server='room-two.example:456', slot='Player Two')
        new = profiles.create()
        reloaded = RunProfiles(self.state, self.settings)
        self.assertIn(new, reloaded.data['runs'])
        self.assertEqual(reloaded.label('run-second'), 'run-second — Weekend co-op')
        self.assertEqual(reloaded.data['runs']['run-second']['slot'], 'Player Two')
        self.assertEqual(reloaded.data['runs'][new], dict(description='', server='', slot=''))
        self.assertFalse((self.state / 'runs' / (new + '.json')).exists())

    def test_bad_description_or_password_field_does_not_replace_profiles(self):
        profiles = RunProfiles(self.state, self.settings); before = profiles.path.read_bytes()
        for value in ('x' * 121, 'two\nlines'):
            with self.assertRaises(ValueError): profiles.update('run-first', description=value)
        with self.assertRaises(TypeError): profiles.update('run-first', password='secret')
        self.assertEqual(before, profiles.path.read_bytes())

    def test_backup_includes_run_directory_and_selected_run(self):
        RunProfiles(self.state, self.settings)
        (self.state / 'launcher.json').write_text(json.dumps(self.settings))
        saves = self.state / 'saves/SAVEFILE17'; saves.mkdir(parents=True)
        (saves / 'USR-DATA').write_bytes(b'fixture')
        with ZipFile(backup(self.state, saves.parent, self.state / 'backups')) as bundle:
            self.assertIn('archipelago/run-profiles.json', bundle.namelist())
            self.assertIn('archipelago/launcher.json', bundle.namelist())

    def test_deleted_run_stays_removed_with_stale_settings_and_preserves_records(self):
        profiles = RunProfiles(self.state, self.settings)
        profiles.update('run-second', server='second:456', slot='Other')
        before = self.first.path.read_bytes()
        self.assertEqual(profiles.delete('run-first'), 'run-second')
        reloaded = RunProfiles(self.state, self.settings)
        self.assertNotIn('run-first', reloaded.data['runs'])
        self.assertEqual(reloaded.selected, 'run-second')
        self.assertEqual(reloaded.data['runs']['run-second']['server'], 'second:456')
        self.assertEqual(self.first.path.read_bytes(), before)

    def test_last_deletion_creates_blank_run(self):
        profiles = RunProfiles(self.state, self.settings)
        profiles.delete('run-second')
        replacement = profiles.delete('run-first')
        self.assertNotIn(replacement, ('run-first', 'run-second'))
        self.assertEqual(profiles.data['runs'][replacement], profiles.validate())
        reloaded = RunProfiles(self.state, self.settings)
        self.assertEqual(reloaded.selected, replacement)
        self.assertEqual(reloaded.data['runs'][replacement], profiles.validate())

    def test_failed_deletion_does_not_change_selection_or_index(self):
        profiles = RunProfiles(self.state, self.settings)
        before = profiles.path.read_bytes()
        with patch('tlou_ap.run_profiles.atomic_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): profiles.delete('run-first')
        self.assertEqual(profiles.selected, 'run-first')
        self.assertIn('run-first', profiles.data['runs'])
        self.assertEqual(before, profiles.path.read_bytes())


class RunSelectorUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.patch = patch('tlou_ap.launcher.STATE', self.state); self.patch.start(); self.addCleanup(self.patch.stop)
        self.root = tk.Tk(); self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.app = Launcher(self.root)
        self.app.save_guide.find_pid = lambda: 0
        self.addCleanup(self.close)

    def close(self):
        for callback in self.root.tk.call('after', 'info'): self.root.after_cancel(callback)
        self.root.update_idletasks()
        self.root.destroy()
        for handler in list(logging.getLogger('tlou-ap').handlers):
            handler.close(); logging.getLogger('tlou-ap').removeHandler(handler)

    def test_a_to_b_to_a_restores_room_and_keeps_journals_separate(self):
        a = self.app.run_name
        self.app.server.set('room-a:123'); self.app.slot.set('Alice'); self.app.password.set('not-persisted')
        self.app.run_description.set('Original run'); self.app.save_run_description()
        ledger_a = RunLedger(self.state / 'runs' / (a + '.json'), [])
        session_a = Session(self.state / 'sessions', 'seed-a', 0, 1, ledger_a.data['run_id'], Config())
        ledger_a.bind(session_a.identity); session_a.complete_mission(0)
        ledger_before, session_before = ledger_a.path.read_bytes(), session_a.path.read_bytes()
        self.app.new_run(); b = self.app.run_name
        self.assertNotEqual(a, b)
        self.assertEqual((self.app.server.get(), self.app.slot.get(), self.app.password.get()), ('', '', ''))
        self.app.server.set('room-b:456'); self.app.slot.set('Bob'); self.app.run_description.set('Second room')
        self.app.save_run_description()
        ledger_b = RunLedger(self.state / 'runs' / (b + '.json'), [])
        session_b = Session(self.state / 'sessions', 'seed-b', 0, 1, ledger_b.data['run_id'], Config())
        ledger_b.bind(session_b.identity)
        self.assertNotEqual(session_a.path, session_b.path)
        self.app.switch_run(a)
        self.assertEqual((self.app.server.get(), self.app.slot.get(), self.app.run_description.get()),
                         ('room-a:123', 'Alice', 'Original run'))
        self.assertEqual(ledger_a.path.read_bytes(), ledger_before)
        self.assertEqual(session_a.path.read_bytes(), session_before)
        self.assertEqual(session_b.data['missions'], [])
        self.assertNotIn('not-persisted', (self.state / 'run-profiles.json').read_text())
        self.assertNotIn('not-persisted', (self.state / 'launcher.json').read_text())
        self.assertEqual(json.loads((self.state / 'launcher.json').read_text())['run'], a)
        self.assertFalse(self.errors)

    def test_cannot_switch_or_create_while_connected(self):
        a = self.app.run_name; b = self.app.run_profiles.create()
        self.app.thread = Mock(); self.app.thread.is_alive.return_value = True
        with self.assertRaisesRegex(ValueError, 'Disconnect'): self.app.switch_run(b)
        count = len(self.app.run_profiles.data['runs']); self.app.new_run()
        self.assertEqual(self.app.run_name, a)
        self.assertEqual(len(self.app.run_profiles.data['runs']), count)

    def test_switch_discards_prior_run_display_and_pending_ui_actions(self):
        b = self.app.run_profiles.create()
        self.app.status.put({'stopped': True}); self.app.actions.put('retire')
        toast = Toast('OLD RUN', 'Item', 'Player', '', '#00EEEE')
        self.app.notifications.put(toast); self.app.overlay.add(toast)
        self.app.last_status = {'connected': False}; self.app.save_guide.identity = {'old': True}
        self.app.switch_run(b)
        self.assertTrue(self.app.status.empty()); self.assertTrue(self.app.actions.empty())
        self.assertTrue(self.app.notifications.empty()); self.assertFalse(self.app.overlay.queue.pending)
        self.assertIsNone(self.app.last_status); self.assertIsNone(self.app.save_guide.identity)
        self.assertFalse(self.app.save_guide.enabled.get())

    def test_delete_confirmation_and_connected_guard(self):
        a = self.app.run_name
        with patch('tlou_ap.launcher.messagebox.askyesno', return_value=False) as confirm:
            self.app.delete_run()
            confirm.assert_called_once()
        self.assertIn(a, self.app.run_profiles.data['runs'])
        self.app.thread = Mock(); self.app.thread.is_alive.return_value = True
        with patch('tlou_ap.launcher.messagebox.askyesno') as confirm:
            self.app.delete_run()
            confirm.assert_not_called()
        self.assertIn(a, self.app.run_profiles.data['runs'])

    def test_delete_switches_to_remaining_run_and_persists_selection(self):
        a = self.app.run_name
        b = self.app.run_profiles.create()
        self.app.run_profiles.update(b, server='second:123', slot='Bob')
        self.app.password.set('old password')
        self.app.status.put({'connected': True})
        with patch('tlou_ap.launcher.messagebox.askyesno', return_value=True):
            self.app.delete_run()
        self.assertEqual(self.app.run_name, b)
        self.assertEqual(self.app.server.get(), 'second:123')
        self.assertEqual(self.app.password.get(), '')
        self.assertTrue(self.app.status.empty())
        self.assertNotIn(a, self.app.run_profiles.data['runs'])
        self.assertEqual(json.loads((self.state / 'launcher.json').read_text())['run'], b)
        self.assertFalse(self.errors)


if __name__ == '__main__': unittest.main()
