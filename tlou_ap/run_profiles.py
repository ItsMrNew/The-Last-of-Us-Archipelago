"""Launcher run directory; progress remains in the existing run/session journals."""
import json
from pathlib import Path
import re
import uuid

from .session import atomic_json


def valid_name(name):
    return isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', name) is not None


class RunProfiles:
    def __init__(self, state, settings):
        self.state = Path(state)
        self.path = self.state / 'run-profiles.json'
        self.data = {'version': 1, 'runs': {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(self.data, dict) or self.data.get('version') != 1 or
                    not isinstance(self.data.get('runs'), dict)):
                raise ValueError('Invalid run directory; existing run files were not changed')
        for name, entry in self.data['runs'].items():
            if (not valid_name(name) or not isinstance(entry, dict) or
                    set(entry) != {'description', 'server', 'slot'}):
                raise ValueError('Invalid run profile')
            self.validate(**entry)
        deleted = self.data.get('deleted', [])
        if (not isinstance(deleted, list) or any(not valid_name(n) for n in deleted)
                or len(set(deleted)) != len(deleted) or set(deleted) & self.data['runs'].keys()):
            raise ValueError('Invalid deleted-run directory')
        # Ignore backup/recovery and test-control sidecars, even if they contain
        # a run_id. Only a plain, valid run ledger is eligible for discovery.
        for path in sorted((self.state / 'runs').glob('*.json')):
            if not valid_name(path.stem) or path.stem in deleted:
                continue
            try:
                ledger = json.loads(path.read_text(encoding='utf-8'))
                valid = (isinstance(ledger, dict) and ledger.get('version') == 1 and
                         isinstance(ledger.get('run_id'), str) and isinstance(ledger.get('completed_tasks'), list) and
                         isinstance(ledger.get('deliveries'), dict))
            except (OSError, ValueError):
                continue
            if valid:
                self.data['runs'].setdefault(path.stem, self.validate())
        selected = settings.get('run')
        self.selected = (selected if valid_name(selected) and selected not in deleted else
                         next(iter(self.data['runs']), None) or self.new_name())
        if self.selected not in self.data['runs']:
            self.data['runs'][self.selected] = self.validate()
        # The old launcher only stored room details for its selected run.
        # Migrate those fields without guessing room details for older runs.
        entry = self.data['runs'][self.selected]
        if self.selected == selected and ('server' in settings or 'slot' in settings):
            entry.update(self.validate(entry['description'], settings.get('server', entry['server']),
                                       settings.get('slot', entry['slot'])))
        self.save()

    @staticmethod
    def validate(description='', server='', slot=''):
        result = {}
        for key, value, limit in (('description', description, 120), ('server', server, 512), ('slot', slot, 64)):
            if not isinstance(value, str) or len(value.strip()) > limit or any(ord(ch) < 32 for ch in value):
                raise ValueError(f'{key.title()} must be one line, at most {limit} characters')
            result[key] = value.strip()
        return result

    def save(self):
        atomic_json(self.path, self.data)

    def update(self, name, **fields):
        if name not in self.data['runs']:
            raise ValueError('Unknown managed run')
        updated = self.validate(**{**self.data['runs'][name], **fields})
        data = {**self.data, 'runs': {**self.data['runs'], name: updated}}
        atomic_json(self.path, data)
        self.data = data

    def new_name(self):
        while True:
            name = 'run-' + uuid.uuid4().hex[:8]
            if (name not in self.data['runs'] and name not in self.data.get('deleted', [])
                    and not (self.state / 'runs' / (name + '.json')).exists()):
                return name

    def create(self):
        name = self.new_name()
        data = {**self.data, 'runs': {**self.data['runs'], name: self.validate()}}
        atomic_json(self.path, data)
        self.data = data
        return name

    def delete(self, name):
        """Remove from selection permanently; preserve journals for recovery."""
        if name not in self.data['runs']:
            raise ValueError('Unknown managed run')
        runs = {n: entry for n, entry in self.data['runs'].items() if n != name}
        if not runs:
            runs[self.new_name()] = self.validate()
        selected = self.selected if self.selected in runs else next(iter(runs))
        data = {**self.data, 'runs': runs,
                'deleted': [*self.data.get('deleted', []), name]}
        atomic_json(self.path, data)
        self.data, self.selected = data, selected
        return selected

    def label(self, name):
        description = self.data['runs'][name]['description']
        return name + (' — ' + description if description else '')
