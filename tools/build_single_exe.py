"""Wrap the verified APWorld client as one self-extracting Windows executable."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.version import RELEASE, CLIENT_VERSION


def main():
    assert importlib.metadata.version('pyinstaller') == '6.22.3'
    build = Path(tempfile.mkdtemp(prefix='single-exe-', dir=ROOT / 'build'))
    bundle = build / 'launcher_bundle'
    bundle.mkdir()
    with ZipFile(ROOT / 'dist/tlou_part1.apworld') as archive:
        for name in ('client.zip', 'manifest.json'):
            (bundle / name).write_bytes(archive.read('tlou_part1/launcher_bundle/' + name))
    manifest = json.loads((bundle / 'manifest.json').read_text())
    assert manifest['version'] == CLIENT_VERSION
    assert hashlib.sha256((bundle / 'client.zip').read_bytes()).hexdigest() == manifest['payload_sha256']
    name = f'TLOU-Part-I-Archipelago-Standalone-{RELEASE}'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed', '--noupx',
               '--name', name, '--icon', str(ROOT / 'tlou_ap/data/game.ico'), '--paths', str(ROOT),
               '--add-data', str(bundle) + ';launcher_bundle',
               '--distpath', str(build / 'dist'), '--workpath', str(build / 'work'),
               '--specpath', str(build), str(ROOT / 'tools/standalone_entry.py')]
    with (build / 'build.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
    executable = build / 'dist' / (name + '.exe')
    # No Python on PATH, no project working directory, no existing client cache.
    local = build / 'isolated-local'
    environment = {**os.environ, 'PYTHONPATH': '', 'PYTHONHOME': '', 'LOCALAPPDATA': str(local),
                   'PATH': str(Path(os.environ['SystemRoot']) / 'System32')}
    results = []
    cached = local / 'TLOUArchipelagoLauncher/clients' / manifest['payload_sha256'] / 'TLOU Archipelago.exe'
    for attempt in (1, 2):
        report = build / f'self-test-{attempt}.json'
        subprocess.run([str(executable), '--self-test', str(report)], cwd=build,
                       env=environment, check=True, timeout=120)
        data = json.loads(report.read_text())
        assert data['passed'] and data['frozen'] and data['client_version'] == CLIENT_VERSION
        assert not data['game_attached']
        assert hashlib.sha256(cached.read_bytes()).hexdigest() == manifest['files'][cached.name]
        results.append(dict(attempt=attempt, cache_mtime=cached.stat().st_mtime_ns, self_test=data))
    assert results[0]['cache_mtime'] == results[1]['cache_mtime']
    output = ROOT / 'dist' / executable.name
    shutil.copy2(executable, output)
    result = dict(passed=True, executable=str(output), client_version=CLIENT_VERSION,
                  sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  apworld_payload=manifest['payload_sha256'], python_on_path=False, attempts=results)
    (ROOT / 'dist/single-exe-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
