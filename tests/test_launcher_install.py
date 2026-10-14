import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from tlou_ap import launcher_client as client
from tlou_ap.state_paths import migrate_legacy_state, state_directory


class LauncherInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.bundle = self.root/'bundle'; self.bundle.mkdir()
        self.files = {'TLOU Archipelago.exe': b'test exe', '_internal/resource.dat': b'test resource'}
        self.make_bundle(self.files)
        self.resources = patch.object(client, 'resources', return_value=self.bundle)
        self.resources.start(); self.addCleanup(self.resources.stop)

    def make_bundle(self, files):
        stream=io.BytesIO()
        with ZipFile(stream,'w') as z:
            for name,data in files.items():z.writestr(name,data)
        payload=stream.getvalue();(self.bundle/'client.zip').write_bytes(payload)
        (self.bundle/'manifest.json').write_text(json.dumps({'payload_sha256':hashlib.sha256(payload).hexdigest(),
            'files':{n:hashlib.sha256(d).hexdigest() for n,d in files.items()}}))

    def test_extract_reuse_repair_and_state_preserved(self):
        cache=self.root/'cache';state=cache/'state';state.mkdir(parents=True);(state/'run').write_text('keep')
        exe=client.prepare_client(cache);stamp=exe.stat().st_mtime_ns
        self.assertEqual(client.prepare_client(cache),exe);self.assertEqual(exe.stat().st_mtime_ns,stamp)
        exe.write_bytes(b'damaged');self.assertEqual(client.prepare_client(cache).read_bytes(),self.files[exe.name])
        self.assertEqual((state/'run').read_text(),'keep')
        self.assertEqual(len(list((cache/'clients').glob('*.damaged-*'))),1)

    def test_payload_tampering_rejected(self):
        (self.bundle/'client.zip').write_bytes(b'corrupt')
        with self.assertRaisesRegex(RuntimeError,'damaged'):client.prepare_client(self.root/'cache')

    def test_invalid_windows_paths_rejected(self):
        for name in ('../outside','C:/evil','dir\\evil','/root','CON.txt','a./x','.state/run.json'):
            with self.subTest(name=name),self.assertRaises(RuntimeError):client.validate_names([name])
        with self.assertRaises(RuntimeError):client.validate_names(['A','a'])

    def test_extracted_hash_tampering_rejected(self):
        p=self.bundle/'manifest.json';m=json.loads(p.read_text());m['files']['TLOU Archipelago.exe']='0'*64;p.write_text(json.dumps(m))
        with self.assertRaisesRegex(RuntimeError,'integrity'):client.prepare_client(self.root/'cache')

    def test_new_bundle_gets_separate_cache(self):
        old=client.prepare_client(self.root/'cache')
        self.make_bundle({**self.files,'TLOU Archipelago.exe':b'new exe'})
        new=client.prepare_client(self.root/'cache')
        self.assertNotEqual(old,new);self.assertEqual(old.read_bytes(),b'test exe')

    def test_child_runtime_is_independent(self):
        with patch.dict(os.environ,{'_PYI_APPLICATION_HOME_DIR':'old','LOCALAPPDATA':'retained'}):
            env=client.client_environment()
        self.assertNotIn('_PYI_APPLICATION_HOME_DIR',env)
        self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'],'1')
        self.assertEqual(env['LOCALAPPDATA'],'retained')


class ProfileMigrationTests(unittest.TestCase):
    def test_migrate_once_without_overwriting_or_removing_old_profile(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);old=root/'old';old.mkdir();(old/'run.json').write_bytes(b'original')
            new=root/'new/state';self.assertTrue(migrate_legacy_state(old,new))
            self.assertEqual((old/'run.json').read_bytes(),(new/'run.json').read_bytes())
            (new/'run.json').write_bytes(b'new progress')
            self.assertFalse(migrate_legacy_state(old,new))
            self.assertEqual((new/'run.json').read_bytes(),b'new progress')

    def test_frozen_cache_versions_share_state_but_dev_is_isolated(self):
        with patch.dict(os.environ,{'LOCALAPPDATA':'C:/profile'},clear=True):
            self.assertEqual(state_directory('C:/cache/a',True),state_directory('C:/cache/b',True))
            self.assertEqual(state_directory('dev',False),Path('dev/.state'))


if __name__=='__main__':unittest.main()
