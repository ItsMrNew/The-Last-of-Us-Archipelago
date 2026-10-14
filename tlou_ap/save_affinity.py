"""Conservative, content-addressed save labels. Never alters a game save.

Only explicit player confirmation establishes ownership. Slot names, dates,
story progress and a connected client are not evidence of save ownership.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .session import atomic_json

LABELS = {'current': 'This run', 'other': 'Other run', 'unknown': 'Unverified',
          'unreadable': 'Unavailable', 'compatible': 'Compatible', 'incompatible': 'Incompatible'}


def run_identity(ledger):
    if not isinstance(ledger, dict):
        raise ValueError('Invalid managed run ledger')
    identity = ledger.get('identity')
    if not isinstance(identity, dict) or not ledger.get('run_id'):
        raise ValueError('Connect this managed run to its Archipelago slot first.')
    if identity.get('run_id') != ledger['run_id'] or any(
            key not in identity for key in ('game', 'seed', 'team', 'slot')):
        raise ValueError('The managed run has no complete Archipelago identity.')
    return dict(identity)


@dataclass(frozen=True)
class SaveEntry:
    slot: str
    title: str
    detail: str
    fingerprint: str = ''
    status: str = 'unknown'
    error: str = ''
    modified_ns: int = 0
    difficulties: tuple | None = None
    progress_error: str = ''
    reason: str = ''


def read_save(folder, *, inspect_progress=False):
    """Read twice around hashing; fail closed if either file changes mid-read."""
    folder = Path(folder)
    if not re.fullmatch(r'SAVEFILE[0-9A-F]{2}', folder.name):
        raise ValueError('Not a playable save slot')
    paths = [folder / 'params.json', folder / 'USR-DATA']
    before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
    if not 0 < before[0][0] <= 65536 or not 0 < before[1][0] <= 128 * 1024 * 1024:
        raise ValueError('Save files are empty or outside supported size limits')
    metadata = paths[0].read_bytes()
    digest = hashlib.sha256()
    payload = paths[1].read_bytes()
    digest.update(payload)
    after = [(p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
    if before != after or len(payload) != before[1][0] or paths[0].read_bytes() != metadata:
        raise ValueError('Save is being written; refresh after saving finishes')
    params = json.loads(metadata)
    if not isinstance(params, dict):
        raise ValueError('Invalid save metadata')
    title, detail = params.get('subTitle'), params.get('detail')
    if not isinstance(title, str) or not isinstance(detail, str) or not title.strip():
        raise ValueError('Save metadata has no readable title or description')
    # Include metadata to prevent an old payload/new title mixture being green.
    digest.update(b'\0AP-SAVE-METADATA\0')
    digest.update(metadata)
    difficulties, error = None, ''
    if inspect_progress:
        from .save_progress import saved_difficulties
        try:
            difficulties = saved_difficulties(payload)
        except ValueError as failure:
            error = str(failure)
    return SaveEntry(folder.name, title, detail, digest.hexdigest(), modified_ns=after[1][1],
                     difficulties=difficulties, progress_error=error)


class SaveRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {'version': 1, 'saves': {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self.data, dict) or self.data.get('version') != 1 or not isinstance(self.data.get('saves'), dict):
                raise ValueError('Unrecognized save guide registry; existing labels were not replaced')

    def classify(self, entry, identity):
        if not entry.fingerprint or identity is None:
            return entry
        record = self.data['saves'].get(entry.fingerprint)
        if record is None:
            return entry
        if not isinstance(record, dict) or not isinstance(record.get('identity'), dict):
            raise ValueError('Invalid saved ownership record')
        return replace(entry, status='current' if record['identity'] == identity else 'other')

    def scan(self, savedata, identity, *, ledger=None):
        entries = []
        for folder in sorted(Path(savedata).iterdir()):
            if not folder.is_dir() or not re.fullmatch(r'SAVEFILE[0-9A-F]{2}', folder.name):
                continue
            try:
                entry = read_save(folder, inspect_progress=ledger is not None)
            except (OSError, ValueError, UnicodeError) as error:
                entry = SaveEntry(folder.name, folder.name, '', status='unreadable', error=str(error))
            entry = self.classify(entry, identity)
            if ledger is not None and identity is not None and entry.fingerprint:
                from .save_progress import compatibility_error
                if run_identity(ledger) != identity:
                    raise ValueError('Run identity changed during the save scan')
                if entry.status == 'other':
                    entry = replace(entry, reason='This exact save was previously linked to another managed run.')
                elif entry.difficulties is None:
                    entry = replace(entry, status='unknown', reason=entry.progress_error)
                else:
                    error = compatibility_error(ledger, entry.difficulties)
                    entry = replace(entry, status='incompatible' if error else 'compatible',
                        reason=error or 'Passes the managed-run progress guard. This does not prove run ownership.')
            entries.append(entry)
        return sorted(entries, key=lambda e: (-e.modified_ns, e.slot))

    def confirm(self, savedata, entry, identity):
        if identity is None or not identity.get('run_id'):
            raise ValueError('Select a connected managed run first')
        actual = read_save(Path(savedata) / entry.slot)
        if not entry.fingerprint or actual.fingerprint != entry.fingerprint:
            raise ValueError('This save changed since you selected it. Refresh and check it again.')
        existing = self.data['saves'].get(actual.fingerprint)
        if existing and existing['identity'] != identity:
            raise ValueError('This exact save is already linked to another run; it was not reassigned.')
        record = {'identity': dict(identity), 'title': actual.title, 'slot': actual.slot,
                  'confirmed_utc': datetime.now(timezone.utc).isoformat(), 'source': 'player-confirmed'}
        updated = {**self.data, 'saves': {**self.data['saves'], actual.fingerprint: record}}
        atomic_json(self.path, updated)
        self.data = updated
        return replace(actual, status='current')
