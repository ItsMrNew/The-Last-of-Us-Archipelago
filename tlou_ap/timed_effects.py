"""Durable, stacking transient traps driven by separate native playable clocks.

The native lease expires if the client disappears. No permanent inventory or
settings mutation is involved, so conservative replay of an unsaved fraction
of a second after a crash is safe. Never spend time in menus or cutscenes.
"""
import copy
import json
import math

from .catalog import ITEM_IDS, TIMED_TRAPS
from .notifications import Toast, item_colour
from .session import atomic_json

DURATION_MS = 30000


class TimedEffects:
    def __init__(self):
        self.session = self.path = self.data = None
        self.ready = False

    def bind(self, session):
        path = session.path.with_suffix('.effects.json')
        data = {'version': 1, 'identity': session.identity,
                'config': session.config.slot_data(), 'items': {}, 'sample': None}
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('version') != 1
                or data.get('identity') != session.identity
                or data.get('config') != session.config.slot_data()
                or not isinstance(data.get('items'), dict)):
            raise ValueError('Timed trap journal identity/configuration mismatch')
        for key, entry in data['items'].items():
            if (not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key
                    or not isinstance(entry, dict) or not isinstance(entry.get('item'), dict)
                    or entry['item'].get('item') not in {ITEM_IDS[n] for n in TIMED_TRAPS}
                    or type(entry.get('started', False)) is not bool
                    or type(entry.get('elapsed')) is not int or not 0 <= entry['elapsed'] <= DURATION_MS):
                raise ValueError('Invalid timed trap journal entry')
        sample = data.get('sample')
        if sample is not None and (not isinstance(sample, dict) or not isinstance(sample.get('instance'), str)
                or not isinstance(sample.get('clocks'), list) or len(sample['clocks']) != 2
                or any(type(v) is not int or v < 0 for v in sample['clocks'])):
            raise ValueError('Invalid timed trap clock sample')
        self.session, self.path, self.data = session, path, data

    def save(self):
        atomic_json(self.path, self.data)

    def synchronize(self):
        received = self.session.data['received']
        for key, entry in self.data['items'].items():
            if int(key) >= len(received) or received[int(key)] != entry['item']:
                raise ValueError('Server inventory changed a timed trap')
        changed = False
        for index, item in enumerate(received):
            if item['item'] in {ITEM_IDS[n] for n in TIMED_TRAPS} and str(index) not in self.data['items']:
                self.data['items'][str(index)] = {'item': dict(item), 'elapsed': 0, 'started': False}
                changed = True
        if changed:
            self.save()

    def remaining(self, name):
        if not self.data:
            return 0
        return sum(DURATION_MS - e['elapsed'] for e in self.data['items'].values()
                   if e['item']['item'] == ITEM_IDS[name])

    @property
    def queued(self):
        return sum(e['elapsed'] < DURATION_MS for e in self.data['items'].values()) if self.data else 0

    def clear_on_death(self, token, adapter):
        adapter.set_timed_effects([0, 0])
        if not self.data or self.data.get('last_death') == token:
            return 0
        old = self.data
        self.data = copy.deepcopy(old)
        status = adapter.timed_effect_status()
        previous = self.data['sample']
        active = set()
        for channel, name in enumerate(TIMED_TRAPS):
            advanced = (previous and previous['instance'] == status['instance']
                        and status['clocks'][channel] > previous['clocks'][channel])
            if advanced or any(e.get('started', e['elapsed'] > 0) and e['elapsed'] < DURATION_MS
                               for e in self.data['items'].values() if e['item']['item'] == ITEM_IDS[name]):
                active.add(ITEM_IDS[name])
        count = 0
        for e in self.data['items'].values():
            if e['item']['item'] in active and e['elapsed'] < DURATION_MS:
                e['elapsed'] = DURATION_MS
                e['resolution'] = 'Active trap cleared on death'
                count += 1
        self.data['last_death'] = token
        self.data['sample'] = None
        try:
            self.save()
        except BaseException:
            self.data = old
            raise
        self.ready = False
        return count

    def poll(self, adapter):
        self.synchronize()
        if not self.queued:
            adapter.set_timed_effects([0, 0])
            return
        status = adapter.timed_effect_status()
        previous = self.data['sample']
        if previous and previous['instance'] == status['instance']:
            for channel, name in enumerate(TIMED_TRAPS):
                elapsed = max(0, status['clocks'][channel] - previous['clocks'][channel])
                for key in sorted(self.data['items'], key=int):
                    entry = self.data['items'][key]
                    if entry['item']['item'] == ITEM_IDS[name]:
                        spent = min(DURATION_MS - entry['elapsed'], elapsed)
                        entry['elapsed'] += spent
                        elapsed -= spent
        self.ready = bool(status['ready'])
        if self.ready:
            for entry in self.data['items'].values():
                if entry['elapsed'] < DURATION_MS:
                    entry['started'] = True
        sample = {'instance': status['instance'], 'clocks': list(status['clocks'])}
        # Persist the new baseline before renewing the native effect lease.
        self.data['sample'] = sample
        self.save()
        adapter.set_timed_effects([self.remaining(name) for name in TIMED_TRAPS])

    def card(self):
        if not self.queued:
            return None
        text = ' | '.join(f'{name}: {math.ceil(self.remaining(name) / 1000)}s'
                          for name in TIMED_TRAPS if self.remaining(name))
        return Toast('ARCHIPELAGO · TRAPS', text,
                     'Active' if self.ready else 'Queued / paused until controllable gameplay.',
                     'Repeated traps stack. Timers pause in menus, scenes and locked missions.', item_colour(4))
