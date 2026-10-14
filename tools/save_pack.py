"""Install a temporary main-story save pack, preserving the entire original folder."""
import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import uuid
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.recovery import default_savedata
from tlou_ap.session import atomic_json

JOURNAL = ROOT / '.state/save-pack-active.json'


def ensure_closed():
    output = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, check=True)
    if any(row and row[0].lower() in ('tlou-i.exe', 'tlou-i-l.exe')
           for row in csv.reader(io.StringIO(output.stdout))):
        raise ValueError('Close The Last of Us before switching save folders.')


def payloads(archive):
    """Read only bounded, main-story save data; never extract arbitrary paths."""
    result = {}
    with ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 128 * 1024 * 1024:
            raise ValueError('Save archive is unexpectedly large')
        for item in z.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in item.filename:
                raise ValueError('Unsafe archive path')
            if len(path.parts) != 3 or path.parts[0] != 'savedata':
                continue
            folder, name = path.parts[1:]
            # Left Behind slots begin at 0x50. Profile 0P is shared by the game.
            if not re.fullmatch(r'SAVEFILE(?:0P|[0-4][0-9A-F])', folder):
                continue
            if name not in ('USR-DATA', 'params.json', 'ICN-ID'):
                raise ValueError('Unexpected file inside a save slot')
            key = folder + '/' + name
            if key in result or item.file_size > 16 * 1024 * 1024:
                raise ValueError('Duplicate or oversized save payload')
            result[key] = z.read(item)
    if 'SAVEFILE0P/USR-DATA' not in result or 'SAVEFILE0A/USR-DATA' not in result:
        raise ValueError('Pack needs a profile and current autosave')
    for folder in {name.split('/')[0] for name in result}:
        if not {folder + '/' + name for name in ('USR-DATA', 'params.json', 'ICN-ID')} <= result.keys():
            raise ValueError('Incomplete save slot: ' + folder)
    return result


def install(archive, savedata, journal):
    savedata, journal = Path(savedata).resolve(), Path(journal).resolve()
    if journal.exists():
        raise ValueError('A test save switch already exists; restore it first.')
    if savedata.name != 'savedata' or not savedata.is_dir() or savedata.is_symlink():
        raise ValueError('Expected the existing savedata directory')
    contents = payloads(archive)
    suffix = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    original = savedata.with_name('savedata.ap-original-' + suffix)
    staging = savedata.with_name('savedata.ap-staged-' + suffix)
    staging.mkdir()
    for name, data in contents.items():
        target = staging / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
    record = {'schema': 1, 'phase': 'prepared', 'savedata': str(savedata), 'original': str(original),
              'staging': str(staging), 'archive_sha256': hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
              'files': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    atomic_json(journal, record)  # Recovery paths exist on disk before either rename.
    savedata.rename(original)
    try:
        staging.rename(savedata)
    except BaseException:
        original.rename(savedata)
        raise
    record['phase'] = 'active'; atomic_json(journal, record)
    return record


def restore(journal):
    journal = Path(journal).resolve()
    record = json.loads(journal.read_text())
    savedata, original = Path(record['savedata']).resolve(), Path(record['original']).resolve()
    if (savedata.name != 'savedata' or original.parent != savedata.parent
            or not original.name.startswith('savedata.ap-original-') or not original.is_dir()
            or original.is_symlink() or savedata.is_symlink()):
        raise ValueError('Original save directory is missing or the journal is invalid.')
    testing = Path(record['testing']).resolve() if record.get('testing') else savedata.with_name(
        'savedata.ap-tests-' + uuid.uuid4().hex[:8])
    if testing.parent != savedata.parent or not testing.name.startswith('savedata.ap-tests-'):
        raise ValueError('Invalid test archive directory')
    record.update(phase='restoring', testing=str(testing)); atomic_json(journal, record)
    if savedata.exists():
        if testing.exists(): raise ValueError('Test archive already exists; inspect the journal.')
        savedata.rename(testing)
    original.rename(savedata)
    record['phase'] = 'restored'; atomic_json(journal, record)
    history = journal.with_name('save-pack-restored-' + uuid.uuid4().hex[:8] + '.json')
    journal.rename(history)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('install'); add.add_argument('archive', type=Path)
    add.add_argument('--savedata', type=Path)
    sub.add_parser('restore')
    args = parser.parse_args()
    ensure_closed()
    record = (install(args.archive, args.savedata or default_savedata(), JOURNAL)
              if args.command == 'install' else restore(JOURNAL))
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
