import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tlou_ap.save_affinity import SaveRegistry, read_save, run_identity
from tlou_ap.recovery import backup


class SaveAffinityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.savedata = self.root / 'savedata'; self.savedata.mkdir()
        self.state = self.root / 'state'; self.state.mkdir()
        self.registry = SaveRegistry(self.state / 'save-guide.json')
        self.identity = dict(game='The Last of Us Part I', seed='1', team=0, slot=1, run_id='run-one')
        self.folder = self.savedata / 'SAVEFILE17'; self.folder.mkdir()
        (self.folder / 'params.json').write_text(json.dumps(dict(subTitle='Save Game 18', detail='Suburbs\n4 hours')), encoding='utf-8')
        (self.folder / 'USR-DATA').write_bytes(b'game save contents')
        self.entry = read_save(self.folder)

    def confirm(self):
        return self.registry.confirm(self.savedata, self.entry, self.identity)

    def test_confirmation_survives_restart_without_modifying_save(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        self.confirm()
        reloaded = SaveRegistry(self.registry.path)
        self.assertEqual(reloaded.scan(self.savedata, self.identity)[0].status, 'current')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})

    def test_unconfirmed_saves_are_not_red(self):
        self.assertEqual(self.registry.scan(self.savedata, self.identity)[0].status, 'unknown')

    def test_other_seed_slot_team_or_local_run_is_red(self):
        self.confirm()
        for key, value in [('seed', '2'), ('team', 1), ('slot', 2), ('run_id', 'another-run')]:
            with self.subTest(key=key):
                self.assertEqual(self.registry.scan(self.savedata, {**self.identity, key: value})[0].status, 'other')

    def test_absent_identity_is_unknown(self):
        self.confirm()
        self.assertEqual(self.registry.scan(self.savedata, None)[0].status, 'unknown')

    def test_overwrite_same_slot_and_same_metadata_becomes_unknown(self):
        self.confirm()
        (self.folder / 'USR-DATA').write_bytes(b'new checkpoint saved')
        self.assertEqual(self.registry.scan(self.savedata, self.identity)[0].status, 'unknown')

    def test_changed_metadata_becomes_unknown(self):
        self.confirm()
        (self.folder / 'params.json').write_text(json.dumps(dict(subTitle='Save Game 18', detail='Hotel')), encoding='utf-8')
        self.assertEqual(self.registry.scan(self.savedata, self.identity)[0].status, 'unknown')

    def test_exact_backup_copy_remains_recognized(self):
        self.confirm()
        shutil.copytree(self.folder, self.savedata / 'SAVEFILE18')
        self.assertEqual([e.status for e in self.registry.scan(self.savedata, self.identity)], ['current', 'current'])

    def test_confirmation_rejects_save_changed_since_selection(self):
        (self.folder / 'USR-DATA').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'): self.confirm()
        self.assertFalse(self.registry.path.exists())

    def test_cannot_reassign_known_foreign_save(self):
        self.confirm()
        before = self.registry.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'another run'):
            self.registry.confirm(self.savedata, self.entry, {**self.identity, 'run_id': 'other'})
        self.assertEqual(before, self.registry.path.read_bytes())

    def test_partial_write_unavailable_and_profile_excluded(self):
        (self.folder / 'USR-DATA').write_bytes(b'')
        shutil.copytree(self.folder, self.savedata / 'SAVEFILE0P')
        rows = self.registry.scan(self.savedata, self.identity)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, 'unreadable')

    def test_metadata_change_during_hash_rejected(self):
        original = Path.read_bytes
        calls = 0
        def changing(path):
            nonlocal calls
            data = original(path)
            if path.name == 'params.json':
                calls += 1
                if calls == 2: return data + b' '
            return data
        with patch.object(Path, 'read_bytes', changing):
            with self.assertRaisesRegex(ValueError, 'being written'): read_save(self.folder)

    def test_malformed_registry_not_silently_replaced(self):
        self.registry.path.write_text('[]')
        with self.assertRaisesRegex(ValueError, 'Unrecognized'): SaveRegistry(self.registry.path)
        self.assertEqual(self.registry.path.read_text(), '[]')

    def test_registry_is_in_recovery_backup(self):
        self.confirm()
        bundle = backup(self.state, self.savedata, self.root / 'backups')
        with ZipFile(bundle) as z:
            data = z.read('archipelago/save-guide.json')
            self.assertEqual(data, self.registry.path.read_bytes())
            self.assertEqual(json.loads(z.read('manifest.json'))['sha256']['archipelago/save-guide.json'],
                             hashlib.sha256(data).hexdigest())

    def test_run_identity_requires_bound_run(self):
        self.assertEqual(run_identity({'run_id': 'run-one', 'identity': self.identity}), self.identity)
        for ledger in ({'run_id': 'run-one', 'identity': None}, {'run_id': 'wrong', 'identity': self.identity}):
            with self.assertRaises(ValueError): run_identity(ledger)


if __name__ == '__main__': unittest.main()
