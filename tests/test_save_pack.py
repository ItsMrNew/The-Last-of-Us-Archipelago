import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tlou_ap.native.adapter import NativeAdapter

spec=importlib.util.spec_from_file_location('save_pack',Path(__file__).resolve().parents[1]/'tools/save_pack.py')
save_pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(save_pack)


class SavePackTests(unittest.TestCase):
    def archive(self, directory):
        path=Path(directory)/'pack.zip'
        with ZipFile(path,'w') as z:
            for slot in ('SAVEFILE0P','SAVEFILE0A','SAVEFILE50'):
                for name in ('USR-DATA','params.json','ICN-ID'):
                    z.writestr(f'savedata/{slot}/{name}',b'test data')
        return path

    def test_round_trip_retains_original_and_new_testing_saves(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);savedata=root/'savedata';savedata.mkdir()
            (savedata/'precious-save').write_bytes(b'original')
            journal=root/'state/save-pack-active.json'
            result=save_pack.install(self.archive(root),savedata,journal)
            self.assertEqual((Path(result['original'])/'precious-save').read_bytes(),b'original')
            self.assertFalse((savedata/'SAVEFILE50').exists())
            (savedata/'SAVEFILE0A/USR-DATA').write_bytes(b'test progress')
            result=save_pack.restore(journal)
            self.assertEqual((savedata/'precious-save').read_bytes(),b'original')
            self.assertEqual((Path(result['testing'])/'SAVEFILE0A/USR-DATA').read_bytes(),b'test progress')
            self.assertFalse(journal.exists())

    def test_unsafe_archive_and_incomplete_slot_rejected_before_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.archive(temp)
            with ZipFile(path,'a') as z:z.writestr('savedata/../escape',b'bad')
            with self.assertRaisesRegex(ValueError,'Unsafe'):save_pack.payloads(path)
            path=self.archive(temp)
            with ZipFile(path,'a') as z:z.writestr('savedata/SAVEFILE01/USR-DATA',b'partial')
            with self.assertRaisesRegex(ValueError,'Incomplete'):save_pack.payloads(path)

    def test_real_client_rejects_active_test_pack_before_process_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'save-pack-active.json').write_text('{}')
            with patch('tlou_ap.native.adapter.Bridge') as bridge:
                with self.assertRaisesRegex(ValueError,'test save pack'):
                    NativeAdapter(1,root,root/'runs/run.json')
                bridge.assert_not_called()


if __name__=='__main__':unittest.main()
