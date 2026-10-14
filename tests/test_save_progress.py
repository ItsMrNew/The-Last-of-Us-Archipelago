import json
from pathlib import Path
import struct
import tempfile
import unittest

from tlou_ap.save_progress import NODES, STRIDE, MARKER, BOUNDS, REQUIRED, saved_difficulties, compatibility_error
from tlou_ap.save_affinity import SaveRegistry, read_save
from tlou_ap.native.run import RunLedger


def fixture(completed=0, difficulty=2):
    # Synthetic save: no user save data is stored in the test suite.
    data = bytearray(64 + len(NODES) * STRIDE * 2)
    struct.pack_into('<I', data, 0, 60050)
    for copy in range(2):
        for i, node in enumerate(NODES):
            off = 64 + (copy * len(NODES) + i) * STRIDE
            struct.pack_into('<Q', data, off, node['sid'])
            struct.pack_into('<i', data, off + 24, difficulty if i < BOUNDS[completed] else -1)
            data[off + 32:off + 48] = MARKER
    return data


class SaveProgressTests(unittest.TestCase):
    def ledger(self, completed):
        return {'version': 1, 'run_id': 'example',
                'identity': {'game': 'The Last of Us Part I', 'seed': 'seed', 'team': 0, 'slot': 1, 'run_id': 'example'},
                'completed_tasks': [], 'native_confirmed': list(range(completed)), 'test_missions': [], 'loading_roots': []}

    def test_all_campaign_boundaries_and_supported_difficulties(self):
        for completed in range(30):
            for difficulty in range(7):
                with self.subTest(completed=completed, difficulty=difficulty):
                    self.assertEqual(saved_difficulties(fixture(completed, difficulty)),
                                     (difficulty,) * completed + (-1,) * (29 - completed))

    def test_same_result_as_loaded_save_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            live = RunLedger(Path(directory) / 'run.json', REQUIRED)
            for progress in (0, 2, 18, 29):
                live.data.update(self.ledger(progress))
                for saved in (0, 2, 18, 19, 29):
                    difficulties = list(saved_difficulties(fixture(saved)))
                    self.assertEqual(compatibility_error(live.data, difficulties), live.incompatible_progress(difficulties))
                    self.assertEqual(bool(compatibility_error(live.data, difficulties)), saved > progress)

    def test_live_task_evidence_and_loading_roots_use_the_same_rule(self):
        ledger = self.ledger(0)
        ledger['completed_tasks'] = list(REQUIRED[0])
        self.assertFalse(compatibility_error(ledger, saved_difficulties(fixture(1))))
        ledger['completed_tasks'] = []
        ledger['loading_roots'] = list(REQUIRED[0])
        self.assertFalse(compatibility_error(ledger, saved_difficulties(fixture(1))))

    def test_foreign_but_earlier_save_is_compatible_not_proven_owned(self):
        self.assertFalse(compatibility_error(self.ledger(18), saved_difficulties(fixture(2, 5))))

    def test_disagreeing_copies_fail_closed(self):
        data = fixture(2)
        struct.pack_into('<i', data, 64 + len(NODES) * STRIDE + 24, -1)
        with self.assertRaisesRegex(ValueError, 'copies differ'): saved_difficulties(data)

    def test_missing_truncated_extra_or_corrupt_tables_fail_closed(self):
        cases = [fixture()[:64 + len(NODES) * STRIDE], fixture()[:-4],
                 fixture() + fixture()[64:64 + len(NODES) * STRIDE]]
        data = fixture(); data[64 + 7 * STRIDE] ^= 1; cases.append(data)
        data = fixture(); data[64 + 7 * STRIDE + 32] ^= 1; cases.append(data)
        data = fixture(); struct.pack_into('<i', data, 64 + 24, 99); cases.append(data)
        data = fixture(); data[0] ^= 1; cases.append(data)
        for data in cases:
            with self.assertRaises(ValueError): saved_difficulties(data)

    def test_scan_rechecks_overwrites_and_new_run_progress_without_ownership_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); folder = root / 'SAVEFILE0A'; folder.mkdir()
            (folder / 'params.json').write_text(json.dumps({'subTitle': 'CURRENT AUTOSAVE', 'detail': 'Suburbs'}))
            (folder / 'USR-DATA').write_bytes(fixture(18))
            registry = SaveRegistry(root / 'registry.json'); ledger = self.ledger(18)
            def scan(): return registry.scan(root, ledger['identity'], ledger=ledger)[0]
            self.assertEqual(scan().status, 'compatible')
            self.assertFalse(registry.path.exists())
            (folder / 'USR-DATA').write_bytes(fixture(19))
            self.assertEqual(scan().status, 'incompatible')
            ledger['native_confirmed'].append(18)
            self.assertEqual(scan().status, 'compatible')
            (folder / 'USR-DATA').write_bytes(b'unsupported old save')
            self.assertEqual(scan().status, 'unknown')

    def test_known_foreign_ownership_stays_red_and_known_ownership_cannot_override_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); folder = root / 'SAVEFILE17'; folder.mkdir()
            (folder / 'params.json').write_text(json.dumps({'subTitle': 'Save Game 18', 'detail': 'Suburbs'}))
            (folder / 'USR-DATA').write_bytes(fixture(19))
            ledger = self.ledger(18); registry = SaveRegistry(root / 'registry.json')
            registry.confirm(root, read_save(folder), ledger['identity'])
            row = registry.scan(root, ledger['identity'], ledger=ledger)[0]
            self.assertEqual(row.status, 'incompatible')
            ledger['identity']['run_id'] = ledger['run_id'] = 'other-run'
            row = registry.scan(root, ledger['identity'], ledger=ledger)[0]
            self.assertEqual(row.status, 'other')


if __name__ == '__main__': unittest.main()
