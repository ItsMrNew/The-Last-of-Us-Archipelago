"""Export Git-visible source and checksums without development or user data."""
import hashlib
from pathlib import Path
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.version import RELEASE


def main():
    raw = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    names = sorted(set(raw.decode('utf-8').split('\0')) - {''})
    forbidden = {'.git', '.state', '.research', '.deps', '.venv', 'build', 'dist', '__pycache__'}
    for name in names:
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or forbidden.intersection(path.parts):
            raise RuntimeError(f'Unexpected source entry: {name}')
        if name.startswith('tlou_ap/data/airhorns/') and path.suffix == '.wav':
            raise RuntimeError('Licensed recordings must not enter the source export')
    output = ROOT / f'dist/TLOU-Part-I-Archipelago-Source-{RELEASE}.zip'
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(ROOT / name, 'TLOU-Archipelago/' + name)
    assets = [ROOT / 'dist/tlou_part1.apworld',
              ROOT / f'dist/TLOU-Part-I-Archipelago-Standalone-{RELEASE}.zip',
              ROOT / f'dist/TLOU-Part-I-Archipelago-Windows-{RELEASE}.zip', output]
    sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in assets)
    (ROOT / 'dist/SHA256SUMS.txt').write_text(sums, encoding='utf-8')
    print(f'{output}\n{len(names)} source files\n{sums}')


if __name__ == '__main__':
    main()
