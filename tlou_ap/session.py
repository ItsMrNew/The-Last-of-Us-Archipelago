"""Seed-scoped checks and durable reward receipts, following Renegade's design.

This is game-independent client logic. Native completion and delivery callbacks
are deliberately not fabricated by the read-only observer.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import uuid

from .catalog import (GAME, ITEM_IDS, PROGRESSIVE_CHAPTER, DELIVERABLES, MISSIONS, COLLECTIBLES,
                      Config, unlocked_chapters)


class SyncRequired(ValueError):
    pass


@dataclass(frozen=True)
class ReceivedItem:
    item: int
    location: int
    player: int
    flags: int

    @classmethod
    def parse(cls, entry):
        if not isinstance(entry, dict):
            raise ValueError('Received item must be an object')
        fields = [entry.get(key) for key in ('item', 'location', 'player', 'flags')]
        if any(type(value) is not int for value in fields) or fields[0] not in ITEM_IDS.values():
            raise ValueError('Invalid or unsupported received item')
        return cls(*fields)


class Inventory:
    def __init__(self):
        self.items = ()
        self.synchronized = False

    def apply(self, index, entries):
        if type(index) is not int or index < 0 or not isinstance(entries, list):
            raise ValueError('Invalid ReceivedItems packet')
        incoming = tuple(ReceivedItem.parse(entry) for entry in entries)
        if index == 0:
            self.items = incoming
            self.synchronized = True
        elif self.synchronized and index == len(self.items):
            self.items += incoming
        elif (self.synchronized and index < len(self.items)
              and self.items[index:index + len(incoming)] == incoming):
            pass
        else:
            self.synchronized = False
            raise SyncRequired('Received item gap or conflicting duplicate; request Sync')
        return self.items


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers (including backup/indexing tools) can briefly open the
        # destination without delete sharing. Retry the atomic rename; never
        # fall back to truncating the last good ledger.
        for attempt in range(10):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                import time
                time.sleep(.02)
    finally:
        temporary.unlink(missing_ok=True)


class Session:
    def __init__(self, directory, seed, team, slot, run_id, config: Config):
        if not isinstance(seed, str) or not seed or not isinstance(run_id, str) or not run_id:
            raise ValueError('Seed and managed run identity are required')
        if type(team) is not int or type(slot) is not int or team < 0 or slot < 1:
            raise ValueError('Invalid team or slot')
        self.identity = {'game': GAME, 'seed': seed, 'team': team, 'slot': slot, 'run_id': run_id}
        self.config = config
        key = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()
        self.path = Path(directory) / (key + '.json')
        self.data = {'version': 1, 'identity': self.identity, 'config': config.slot_data(),
                     'missions': [], 'collectibles': [], 'received': [], 'receipts': {}}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self._validate(data)
            self.data = data

    def _validate(self, data):
        if (not isinstance(data, dict) or data.get('version') != 1 or data.get('identity') != self.identity
                or data.get('config') != self.config.slot_data()):
            raise ValueError('Saved session identity or configuration mismatch')
        for field, limit in (('missions', len(MISSIONS)), ('collectibles', len(COLLECTIBLES))):
            values = data.get(field)
            if (not isinstance(values, list) or any(type(i) is not int or not 0 <= i < limit for i in values)
                    or len(values) != len(set(values))):
                raise ValueError(f'Invalid saved {field}')
        if not isinstance(data.get('received'), list) or not isinstance(data.get('receipts'), dict):
            raise ValueError('Invalid saved inventory or receipts')
        if sorted(data['missions']) != list(range(len(data['missions']))):
            raise ValueError('Saved mission completion is not in story order')
        items = [ReceivedItem.parse(entry) for entry in data['received']]
        for key, status in data['receipts'].items():
            if (not key.isdecimal() or str(int(key)) != key or not 0 <= int(key) < len(items)
                    or items[int(key)].item not in {ITEM_IDS[name] for name in DELIVERABLES}
                    or status not in ('reserved', 'applied', 'uncertain')):
                raise ValueError('Invalid saved reward receipt')

    def _commit(self, **changes):
        data = {**self.data, **changes}
        self._validate(data)
        atomic_json(self.path, data)
        self.data = data

    @property
    def unlocked(self):
        return unlocked_chapters(self.config, [entry['item'] for entry in self.data['received']])

    def record_inventory(self, received):
        entries = [asdict(entry) for entry in received]
        for key in self.data['receipts']:
            index = int(key)
            if index >= len(entries) or entries[index] != self.data['received'][index]:
                raise ValueError('Server inventory changed an already reserved or delivered reward')
        if entries != self.data['received']:
            self._commit(received=entries)

    def can_start(self, mission):
        if type(mission) is not int or not 0 <= mission < len(MISSIONS):
            return False
        return (MISSIONS[mission]['chapter'] in self.unlocked
                and (mission == 0 or mission - 1 in self.data['missions']))

    def complete_mission(self, mission):
        if not self.can_start(mission):
            raise ValueError('Completion rejected for a locked or out-of-order mission')
        if mission not in self.data['missions']:
            self._commit(missions=sorted([*self.data['missions'], mission]))

    def can_collect(self, index):
        """Admit live pickups by chapter access, not their catalog subchapter.

        Some pickups precede their assigned subchapter's task boundary (the
        Medical Pamphlet is reachable during Downtown but filed under Museum).
        The chapter must still be unlocked and reachable in story order.
        Actual pickup evidence is supplied by the native run ledger.
        """
        if type(index) is not int or not 0 <= index < len(COLLECTIBLES):
            return False
        chapter = MISSIONS[COLLECTIBLES[index]['mission']]['chapter']
        first = next(m['index'] for m in MISSIONS if m['chapter'] == chapter)
        return self.can_start(first)

    def collect(self, index):
        if type(index) is not int or not 0 <= index < len(COLLECTIBLES):
            raise ValueError('Unknown collectible')
        if not self.can_collect(index):
            raise ValueError('Collectible rejected in an inaccessible chapter')
        if index not in self.data['collectibles']:
            self._commit(collectibles=sorted([*self.data['collectibles'], index]))

    @property
    def earned_checks(self):
        missions, collectibles = set(self.data['missions']), set(self.data['collectibles'])
        return {check.id for check in self.config.active_checks
                if ((check.category == 'mission' and check.mission in missions)
                    or (check.category == 'collectible' and check.native_index in collectibles)
                    or (check.category == 'chapter' and all(m['index'] in missions for m in MISSIONS
                                                            if m['chapter'] == check.chapter)))}

    @property
    def story_complete(self):
        return set(self.data['missions']) == set(range(len(MISSIONS)))

    @property
    def queued_supplies(self):
        return tuple(index for index, entry in enumerate(self.data['received'])
                     if entry['item'] in {ITEM_IDS[name] for name in DELIVERABLES}
                     and str(index) not in self.data['receipts'])

    def reserve_supply(self, index):
        if type(index) is not int or index not in self.queued_supplies:
            raise ValueError('Supply is not queued')
        self._commit(receipts={**self.data['receipts'], str(index): 'reserved'})
        # A future game adapter must retain this receipt to reconcile a crash.
        return f'{self.path.stem}:{index}'

    def resolve_supply(self, index, outcome):
        if self.data['receipts'].get(str(index)) not in ('reserved', 'uncertain'):
            raise ValueError('No pending supply receipt')
        if outcome not in ('applied', 'not_applied', 'uncertain'):
            raise ValueError('Invalid delivery outcome')
        receipts = dict(self.data['receipts'])
        if outcome == 'not_applied':
            del receipts[str(index)]
        else:
            receipts[str(index)] = outcome
        self._commit(receipts=receipts)
