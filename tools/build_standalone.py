"""Build and verify a portable Windows client in a fresh, isolated output folder.

Build dependency: pip install -e .[bundle]
PyInstaller reference: https://pyinstaller.org/en/stable/usage.html
"""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DIST = ROOT / 'dist'
NAME = 'TLOU Archipelago'


def main():
    manifest = json.loads((DIST / 'native/manifest.json').read_text())
    dll = DIST / 'native' / manifest['dll']
    assert hashlib.sha256(dll.read_bytes()).hexdigest() == manifest['dll_sha256']
    sources = b''.join((ROOT / 'native' / name).read_bytes() for name in ('bridge.h', 'bridge.c', 'test_commands.h', 'test_collectibles.h', 'hook_decoder.c'))
    assert int.from_bytes(hashlib.sha256(sources).digest()[:8], 'little') == manifest['build_id']
    if metadata.version('pyinstaller') != '6.22.3':
        raise SystemExit('Install the pinned .[bundle] build dependencies first.')
    build = Path(tempfile.mkdtemp(prefix='standalone-', dir=ROOT / 'build'))
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed', '--noupx',
               '--name', NAME, '--icon', str(ROOT / 'tlou_ap/data/game.ico'), '--paths', str(ROOT), '--collect-data', 'tlou_ap',
               '--distpath', str(build / 'dist'), '--workpath', str(build / 'work'),
               '--specpath', str(build), str(ROOT / 'tools/launcher_entry.py')]
    with (build / 'build.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
    app = build / 'dist' / NAME
    extras = {'README.md': ROOT / 'tlou_ap/docs/setup_en.md',
              'VALIDATION.md': ROOT / 'tlou_ap/docs/validation_release.md',
              'THIRD_PARTY_NOTICES.txt': ROOT / 'THIRD_PARTY_NOTICES.txt',
              'LICENSE': ROOT / 'LICENSE',
              'dist/native/manifest.json': DIST / 'native/manifest.json',
              'dist/native/MinHook-LICENSE.txt': DIST / 'native/MinHook-LICENSE.txt',
              'dist/native/' + dll.name: dll,
              'dist/gate-validation.json': DIST / 'gate-validation.json',
              'templates/The Last of Us Part I.yaml': ROOT / 'templates/The Last of Us Part I.yaml',
              'licenses/Python.txt': Path(sys.base_prefix) / 'LICENSE.txt',
              'licenses/Tk.txt': Path(sys.base_prefix) / 'tcl/tk8.6/license.terms'}
    for package in ('websockets', 'pyinstaller'):
        for path in metadata.files(package):
            if path.name.lower() in ('license', 'license.txt', 'copying.txt'):
                extras[f'licenses/{package}-{path.name}'] = path.locate()
    for path in (ROOT / 'licenses').glob('*.txt'):
        extras['licenses/' + path.name] = path
    for name, source in extras.items():
        target = app / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (app / 'Offline Test Lab.cmd').write_text('@echo off\ncd /d "%~dp0"\nstart "" "TLOU Archipelago.exe" --offline-lab\n')
    executable = app / (NAME + '.exe')
    smoke = build / 'selftest.json'
    # The app must find everything without Python on PATH, outside the source cwd.
    import os
    environment = {**os.environ, 'PYTHONPATH': '', 'PYTHONHOME': '',
                   'PATH': str(Path(os.environ['SystemRoot']) / 'System32')}
    subprocess.run([str(executable), '--self-test', str(smoke)], cwd=build,
                   env=environment, timeout=45, check=True)
    report = json.loads(smoke.read_text())
    assert report['passed'] and report['frozen'] and not report['game_attached']
    assert report['horn_recordings_installed'] == 5
    files = {p.relative_to(app).as_posix(): p for p in app.rglob('*') if p.is_file()}
    assert not any(name.startswith('.state/') for name in files)
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}
    (app / 'SHA256SUMS.json').write_text(json.dumps(hashes, indent=2) + '\n')
    from tlou_ap.version import RELEASE
    output = DIST / f'TLOU-Part-I-Archipelago-Standalone-{RELEASE}.zip'
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file(): archive.write(path, 'TLOU-Archipelago/' + path.relative_to(app).as_posix())
    report.update(executable=str(executable), archive=str(output), files=len(hashes),
                  archive_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  pyinstaller=metadata.version('pyinstaller'))
    (DIST / 'standalone-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
