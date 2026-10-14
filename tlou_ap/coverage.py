"""Build-scoped campaign test evidence; observed checks never imply a test pass."""
import hashlib
import json
from datetime import datetime, timezone

from .catalog import CHECKS, MISSIONS, CHAPTERS, DATA
from .session import atomic_json
from .version import RELEASE

SCENARIOS = ('Normal completion', 'Cinematic skip', 'Prolonged lock / menus', 'Unlock received',
             'Disconnect / reconnect', 'Restart checkpoint', 'Menu / load entry')
CHECK_SCENARIOS = ('Acquisition / completion', 'Duplicate / reload', 'Assignment / reachability')
STATES = ('Not tested', 'Passed', 'Failed', 'Needs retest')
CATALOG_HASH = hashlib.sha256(json.dumps(DATA, sort_keys=True).encode()).hexdigest()


def targets():
    result = [{'key': f'mission:{m["index"]}', 'name': f'{CHAPTERS[m["chapter"]]["name"]} · {m["name"]}',
               'kind': 'Mission', 'scenarios': SCENARIOS} for m in MISSIONS]
    result += [{'key': f'check:{c.id}', 'name': c.name, 'kind': c.category.title(),
                'scenarios': CHECK_SCENARIOS} for c in CHECKS if c.category != 'mission']
    result.append({'key': 'goal', 'name': 'Jackson · Final goal acknowledged by server', 'kind': 'Goal',
                   'scenarios': ('Full multiworld completion', 'Reconnect / no duplicate goal')})
    return result


class Coverage:
    def __init__(self, path, build):
        self.path = path
        self.identity = {'native_build': build, 'catalog': CATALOG_HASH, 'client': RELEASE}
        self.data = {'version': 1, 'identity': self.identity, 'records': {}}
        self.allowed = {f'{row["key"]}/{scenario}' for row in targets() for scenario in row['scenarios']}
        if path.exists():
            self.data = json.loads(path.read_text(encoding='utf-8'))
        self.validate()

    def validate(self, data=None):
        data = self.data if data is None else data
        if (not isinstance(data, dict) or data.get('version') != 1
                or data.get('identity') != self.identity or not isinstance(data.get('records'), dict)):
            raise ValueError('Coverage file identity does not match this build/catalog')
        for key, row in data['records'].items():
            if (key not in self.allowed or not isinstance(row, dict) or row.get('status') not in STATES
                    or not isinstance(row.get('note'), str) or not isinstance(row.get('time'), str)
                    or not isinstance(row.get('context'), dict)):
                raise ValueError('Invalid coverage evidence')

    def record(self, target, scenario, status, note, context=None):
        key = f'{target}/{scenario}'
        if key not in self.allowed or status not in STATES:
            raise ValueError('Unknown test or result')
        if status != 'Not tested' and not note.strip():
            raise ValueError('Add an evidence note describing what was tested and observed')
        record = {'status': status, 'note': note.strip()[:4000],
                  'time': datetime.now(timezone.utc).isoformat(), 'context': context or {}}
        data = {**self.data, 'records': {**self.data['records'], key: record}}
        self.validate(data)
        atomic_json(self.path, data)
        self.data = data

    def summary(self):
        counts = {state: 0 for state in STATES}
        counts['Not tested'] = len(self.allowed) - len(self.data['records'])
        for row in self.data['records'].values():
            counts[row['status']] += 1
        return counts


def diagnostic_report(coverage, status):
    """Allowlist data. Never export passwords, server addresses, saves or raw logs."""
    status = status or {}
    return {'format': 'tlou-ap-diagnostics', 'version': 1,
            'created': datetime.now(timezone.utc).isoformat(), 'client': RELEASE,
            'coverage': coverage.data,
            'runtime': {key: status.get(key) for key in ('connected', 'started', 'missions', 'checks',
                'unlocked', 'queued', 'held', 'blocked', 'death_link', 'death_state', 'traps', 'context',
                'preferences', 'slot_settings', 'observed_missions', 'observed_checks')},
            'deliveries': status.get('deliveries', []),
            'notice': 'Observed progress is not a validation pass. Notes and item source names are included; '
                      'review before sharing. No game saves, passwords, server address or raw logs included.'}
