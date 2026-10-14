"""Local recovery bundles; never writes or restores a game save."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from zipfile import ZipFile, ZIP_DEFLATED


def default_savedata():
    users = Path.home() / 'Saved Games/The Last of Us Part I/users'
    roots = sorted(users.glob('*/savedata'))
    if len(roots) != 1:
        raise ValueError('Expected one game save profile. Use the backup command with --savedata PATH.')
    return roots[0]


def backup(state, savedata, destination):
    state, savedata, destination = Path(state).resolve(), Path(savedata).resolve(), Path(destination).resolve()
    if not savedata.is_dir() or not state.is_dir():
        raise ValueError('Game saves and Archipelago state folders must both exist')
    candidates = {'game/' + p.relative_to(savedata).as_posix(): p for p in savedata.glob('*/*')
                  if p.is_file() and p.name in ('USR-DATA', 'params.json', 'ICN-ID')}
    for folder in ('runs', 'sessions'):
        candidates.update({'archipelago/' + p.relative_to(state).as_posix(): p
                           for p in (state / folder).rglob('*')
                           if p.is_file() and p.suffix in ('.json', '.jsonl')})
    if (state / 'save-guide.json').is_file():
        candidates['archipelago/save-guide.json'] = state / 'save-guide.json'
    for name in ('run-profiles.json', 'launcher.json'):
        if (state / name).is_file(): candidates['archipelago/' + name] = state / name
    if not any(name.endswith('/USR-DATA') for name in candidates):
        raise ValueError('No game save payloads found')
    # Do not package a mixture of files from a save write in progress.
    before = {name: (p.stat().st_size, p.stat().st_mtime_ns) for name, p in candidates.items()}
    contents = {name: p.read_bytes() for name, p in candidates.items()}
    after = {name: (p.stat().st_size, p.stat().st_mtime_ns) for name, p in candidates.items()}
    if before != after or any(len(contents[name]) != before[name][0] for name in contents):
        raise ValueError('A save changed during backup. Pause the game and try again.')
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / ('recovery-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8] + '.zip')
    manifest = {'schema': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                'note': 'Recovery snapshot only; game saves are not certified as belonging to this AP run.',
                'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    with ZipFile(path, 'x', ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
    return path
