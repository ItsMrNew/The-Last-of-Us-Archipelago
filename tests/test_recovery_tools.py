import ctypes
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tlou_ap.native.bridge import Bridge, Shared
from tlou_ap.native.run import RunLedger
from tlou_ap.recovery import backup
from tlou_ap.session import atomic_json


class RecoveryToolsTests(unittest.TestCase):
    def test_atomic_rename_retries_windows_sharing_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            path.write_text('{"before":true}')
            import os
            real_replace = os.replace
            attempts = []
            def replace(source, target):
                attempts.append(1)
                if len(attempts) < 3:
                    self.assertEqual(json.loads(path.read_text()), {'before': True})
                    raise PermissionError('Reader temporarily denies delete sharing')
                real_replace(source, target)
            with patch('tlou_ap.session.os.replace', side_effect=replace):
                atomic_json(path, {'after': True})
            self.assertEqual(json.loads(path.read_text()), {'after': True})
            self.assertEqual(len(attempts), 3)

    def test_command_mailbox_is_nonblocking_and_never_overwrites_pending_effect(self):
        bridge = Bridge.__new__(Bridge)
        bridge.shared = Shared()
        seq = bridge.begin_command(1, 515, 42)
        self.assertIsNone(bridge.command_result(seq))
        with self.assertRaises(RuntimeError):
            bridge.begin_command(100)
        self.assertEqual(bridge.shared.command_receipt, 42)
        bridge.shared.reply_status = 1
        bridge.shared.reply_seq = seq
        self.assertEqual(bridge.command_result(seq), 1)
        bridge.begin_command(100)
        with self.assertRaises(RuntimeError):
            bridge.command_result(seq)

    def test_advanced_foreign_save_is_rejected_but_old_run_checkpoint_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = RunLedger(Path(directory) / 'run.json', [{i} for i in range(29)])
            ledger.data['started'] = True
            ledger.data['native_confirmed'] = [0]
            self.assertTrue(ledger.incompatible_progress([0, 0] + [-1] * 27))
            self.assertFalse(ledger.incompatible_progress([0] + [-1] * 28))
            self.assertFalse(ledger.incompatible_progress([-1] * 29))
            self.assertFalse(ledger.incompatible_progress([0, 0] + [-1] * 27,
                                                          [{'type': 6, 'sid': 1}]))

    def test_backup_preserves_game_bytes_and_includes_hashed_ap_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saves = root / 'saves/SAVEFILE0A'; saves.mkdir(parents=True)
            (saves / 'USR-DATA').write_bytes(b'game save payload')
            state = root / 'state/runs'; state.mkdir(parents=True)
            (state / 'run.json').write_text('{"example":true}')
            inbox = state.parent / 'sessions/deathlink/inbox.json'
            inbox.parent.mkdir(parents=True)
            inbox.write_text('{"incoming":{"state":"queued"}}')
            path = backup(state.parent, saves.parent, root / 'backups')
            with ZipFile(path) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(len(manifest['sha256']), 3)
                self.assertEqual(archive.read('archipelago/sessions/deathlink/inbox.json'), inbox.read_bytes())
                for name, digest in manifest['sha256'].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
                self.assertEqual(archive.read('game/SAVEFILE0A/USR-DATA'), b'game save payload')
            self.assertEqual((saves / 'USR-DATA').read_bytes(), b'game save payload')
