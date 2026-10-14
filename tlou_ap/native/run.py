"""Run-scoped evidence. Existing save/profile flags never earn new checks."""
import json
from pathlib import Path
import uuid

from ..catalog import COLLECTIBLES, MISSIONS
from ..session import atomic_json

START = int(MISSIONS[0]['task_sid'], 16)
BY_SID = {int(entry['sid'], 16): entry for entry in COLLECTIBLES}


def progress_compatibility_error(data, required, difficulties, events=()):
    """Shared read-only rule for loaded progress and supported disk saves."""
    if len(difficulties) != len(MISSIONS) or any(type(x) is not int or not -1 <= x <= 6 for x in difficulties):
        raise ValueError('Invalid native mission completion snapshot')
    completed = set(data['completed_tasks'])
    completed.update(e['sid'] for e in events if e['type'] == 6)
    completed.update(data.get('loading_roots', []))
    confirmed = set(data['native_confirmed']) | set(data.get('test_missions', []))
    for i, difficulty in enumerate(difficulties):
        if difficulty >= 0 and i not in confirmed and not required[i] <= completed:
            return ('Unrecognized saved progress in ' + MISSIONS[i]['name']
                    + '. Load a save from this managed run, or start New Game for a new run.')
    return ''


class RunLedger:
    def __init__(self, path, required):
        self.path, self.required = Path(path), required
        self.loading_root_starts = set()
        self.data = {'version': 1, 'run_id': str(uuid.uuid4()), 'identity': None,
                     'started': False, 'completed_tasks': [], 'native_confirmed': [],
                     'collectibles': [], 'deliveries': {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data.get('version') != 1 or not isinstance(self.data.get('run_id'), str):
                raise ValueError('Invalid managed run ledger')
            self.data.setdefault('native_confirmed', [])
        else:
            self.save()

    def save(self):
        atomic_json(self.path, self.data)

    def bind(self, identity):
        if self.data['identity'] is not None and self.data['identity'] != identity:
            raise ValueError('This run belongs to a different seed/team/slot. Create a new run.')
        self.data['identity'] = identity
        self.save()

    def incompatible_progress(self, difficulties, events=()):
        """Reject advanced save state without this run's live completion evidence.

        This is a consistency guard, not a save UUID: a foreign save with the
        same progress cannot be distinguished until native load identity exists.
        """
        return progress_compatibility_error(self.data, self.required, difficulties, events)

    def event(self, event, session):
        if event['type'] in (1, 4) and event['sid'] == START and not self.data['started']:
            self.data['started'] = True
            self.save()
        if not self.data['started']:
            return
        mission = event['mission'] - 1
        if event['type'] == 6 and session.can_start(mission):
            sid = event['sid']
            if sid not in self.data['completed_tasks']:
                self.data['completed_tasks'].append(sid)
                self.save()
        # Genuine gameplay pickups use the award flag. Restore/refresh calls
        # have it clear and must never import a save's old inventory as checks.
        if event['type'] in (2, 7) and event['flags'] & 1:
            collectible = BY_SID.get(event['sid'])
            if collectible and session.can_collect(collectible['index']):
                index = collectible['index']
                if index not in self.data['collectibles']:
                    self.data['collectibles'].append(index)
                    self.save()
        self.reconcile_checks(session)

    def available_missions(self, session, difficulties, events):
        """Preview access after this batch's proven completions, without writes.

        A new mission can start in the same poll that finishes its predecessor.
        Snapshot flags alone never advance this preview: every required task
        still needs managed-run evidence or a completion in this batch.
        """
        tasks = set(self.data['completed_tasks'])
        tasks.update(e['sid'] for e in events if e['type'] == 6)
        tasks.update(self.data.get('loading_roots', []))
        completed = set(session.data['missions'])
        available = set()
        for mission, definition in enumerate(MISSIONS):
            if definition['chapter'] not in session.unlocked or (mission and mission - 1 not in completed):
                break
            available.add(mission)
            if difficulties[mission] >= 0 and self.required[mission] <= tasks:
                completed.add(mission)
        return available

    def record_events(self, events, session, difficulties):
        """Commit a validated batch in mission order before processing pickups."""
        for event in events:
            if event['type'] in (1, 4) and event['sid'] == START:
                self.event(event, session)
        self.confirm_native(difficulties, session)
        for event in sorted((e for e in events if e['type'] == 6), key=lambda e: e['mission']):
            self.event(event, session)
            # Admit the next mission before recording its completions, including
            # inferred events which may precede the raw hooks in the input list.
            self.confirm_native(difficulties, session)
        for event in events:
            if event['type'] in (2, 7):
                self.event(event, session)
        self.retain_loading_root(events, session)

    def retain_loading_root(self, events, session):
        """Keep a proven opening task that finishes while the gate stages a load.

        Only the next mission's catalog root is eligible, with a live automatic
        start and completion. This earns no check or access while chapter-locked.
        Restores invalidate starts; arbitrary future completions stay rejected.
        """
        if any(e['type'] == 1 and e['flags'] != 0x40000000 for e in events):
            self.loading_root_starts.clear()
            return
        if not self.data['started']:
            return
        mission = len(session.data['missions'])
        if mission >= len(MISSIONS):
            return
        root = int(MISSIONS[mission]['task_sid'], 16)
        if root not in self.required[mission]:
            return
        for event in events:
            if event['sid'] != root or event['mission'] != mission + 1:
                continue
            if event['type'] == 1 and event['flags'] == 0x40000000:
                self.loading_root_starts.add(root)
            elif event['type'] == 6 and root in self.loading_root_starts:
                retained = self.data.setdefault('loading_roots', [])
                if root not in retained and root not in self.data['completed_tasks']:
                    retained.append(root)
                    self.save()
                self.loading_root_starts.discard(root)

    def reconcile_checks(self, session):
        if not self.data['started']:
            return
        completed = set(self.data['completed_tasks'])
        for mission in range(len(MISSIONS)):
            if mission in session.data['missions']:
                continue
            if (session.can_start(mission) and (mission in self.data.get('test_missions', []) or (self.required[mission] <= completed
                    and mission in self.data['native_confirmed']))):
                session.complete_mission(mission)
            else:
                break
        for index in self.data['collectibles']:
            if session.can_collect(index):
                session.collect(index)

    def confirm_native(self, difficulties, session):
        if not self.data['started']:
            return
        if len(difficulties) != len(MISSIONS) or any(type(x) is not int or not -1 <= x <= 6 for x in difficulties):
            raise ValueError('Invalid native mission completion snapshot')
        for mission, definition in enumerate(MISSIONS):
            root = int(definition['task_sid'], 16)
            if root in self.data.get('loading_roots', []) and session.can_start(mission):
                if root not in self.data['completed_tasks']:
                    self.data['completed_tasks'].append(root)
                self.data['loading_roots'].remove(root)
                self.save()
        completed = set(self.data['completed_tasks'])
        for mission, difficulty in enumerate(difficulties):
            if (difficulty >= 0 and session.can_start(mission) and self.required[mission] <= completed
                    and mission not in self.data['native_confirmed']):
                self.data['native_confirmed'].append(mission)
                self.save()
                self.reconcile_checks(session)
