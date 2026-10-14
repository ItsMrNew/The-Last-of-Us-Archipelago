"""Create a source-based Windows client bundle with the current native DLL."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'dist/native/manifest.json').read_text())
dll = ROOT / 'dist/native' / manifest['dll']
if hashlib.sha256(dll.read_bytes()).hexdigest() != manifest['dll_sha256']:
    raise SystemExit('Native DLL hash mismatch')
sources = b''.join((ROOT / 'native' / name).read_bytes() for name in ('bridge.h', 'bridge.c', 'test_commands.h', 'test_collectibles.h', 'hook_decoder.c'))
if int.from_bytes(hashlib.sha256(sources).digest()[:8], 'little') != manifest['build_id']:
    raise SystemExit('Rebuild the native DLL before packaging changed native sources')
files = {path.relative_to(ROOT).as_posix(): path for path in (ROOT / 'tlou_ap').rglob('*')
         if path.is_file() and path.suffix in ('.py', '.json', '.md', '.wav', '.ico', '.png') and '__pycache__' not in path.parts}
for name in ('pyproject.toml', 'Launch Archipelago.cmd', 'Setup Client.cmd', 'THIRD_PARTY_NOTICES.txt',
             'Launch Offline Test Lab.cmd', 'tools/offline_lab.py',
             'templates/The Last of Us Part I.yaml', 'LICENSE',
             'dist/native/manifest.json', 'dist/native/MinHook-LICENSE.txt', 'dist/gate-validation.json',
             'native/bridge.c', 'native/bridge.h', 'native/test_commands.h', 'native/test_collectibles.h', 'native/hook_decoder.c'):
    files[name] = ROOT / name
files['dist/native/' + dll.name] = dll
files['README.md'] = ROOT / 'tlou_ap/docs/setup_en.md'
files['VALIDATION.md'] = ROOT / 'tlou_ap/docs/validation_release.md'
import sys
sys.path.insert(0, str(ROOT))
from tlou_ap.version import RELEASE
output = ROOT / f'dist/TLOU-Part-I-Archipelago-Windows-{RELEASE}.zip'
hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}
with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
    for name, path in sorted(files.items()):
        archive.write(path, 'TLOU-Archipelago/' + name)
    archive.writestr('TLOU-Archipelago/SHA256SUMS.json', json.dumps(hashes, indent=2) + '\n')
print(output)
print(f'{len(files)} files; {output.stat().st_size:,} bytes')
