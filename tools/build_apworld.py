"""Package generation code and an optional verified standalone Windows client."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.version import CLIENT_VERSION
FILES = ['__init__.py', 'catalog.py', 'world.py', 'options.py', 'archipelago.json',
         'data/catalog.json', 'docs/setup_en.md']


def build(*, world_only=False, output=None, executable=None):
    output = Path(output or ROOT / 'dist/tlou_part1.apworld')
    payload = manifest = None
    if not world_only:
        report = json.loads((ROOT / 'dist/standalone-validation.json').read_text())
        if not report.get('passed') or report.get('client_version') != CLIENT_VERSION:
            raise ValueError('Build and verify the current standalone client first.')
        executable = Path(executable or report['executable'])
        app = executable.parent
        hashes = json.loads((app / 'SHA256SUMS.json').read_text())
        from tlou_ap.launcher_client import validate_names
        validate_names(hashes)
        stream = io.BytesIO()
        with ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
            for name, digest in hashes.items():
                if '.state' in Path(name).parts or name.endswith('.apworld'):
                    raise ValueError('Client bundle must not contain state or nested APWorlds.')
                data = (app / name).read_bytes()
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError(f'Client hash mismatch: {name}')
                archive.writestr(name, data)
        payload = stream.getvalue()
        manifest = {'version': CLIENT_VERSION, 'payload_sha256': hashlib.sha256(payload).hexdigest(), 'files': hashes}
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((ROOT / 'tlou_ap/archipelago.json').read_text())
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('archipelago.json', json.dumps(metadata, indent=2))
        for name in FILES:
            data = (ROOT / 'tlou_ap' / name).read_bytes()
            if name == '__init__.py' and payload:
                data += b'\nfrom .launcher_client import register as _register_launcher\n_register_launcher()\n'
            archive.writestr('tlou_part1/' + name, data)
        archive.write(ROOT / 'LICENSE', 'tlou_part1/LICENSE')
        if payload:
            archive.write(ROOT / 'tlou_ap/launcher_client.py', 'tlou_part1/launcher_client.py')
            archive.writestr('tlou_part1/launcher_bundle/client.zip', payload, compress_type=ZIP_STORED)
            archive.writestr('tlou_part1/launcher_bundle/manifest.json', json.dumps(manifest, indent=2))
            archive.write(ROOT / 'tlou_ap/data/game.png', 'tlou_part1/launcher_bundle/icon.png')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--world-only', action='store_true', help='Development package without the client')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--executable', type=Path)
    args = parser.parse_args()
    print(build(world_only=args.world_only, output=args.output, executable=args.executable))
