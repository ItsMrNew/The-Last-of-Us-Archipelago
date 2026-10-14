"""Seed/run-scoped Airhorn queue. Native playable time drives the saved timer."""
import copy
import json
import math

from .catalog import AIRHORN, ITEM_IDS
from .notifications import Toast, item_colour
from .session import atomic_json
from .preferences import DEFAULT_RUNTIME, validate_runtime


class Airhorn:
    def __init__(self, notify=None):
        self.notify = notify
        self.session = self.path = None
        self.data = None
        self.last_clock = None
        self.playable = False
        self.preferences = dict(DEFAULT_RUNTIME)

    def configure(self, preferences):
        self.preferences = validate_runtime(preferences)

    def bind(self, session):
        self.session = session
        self.path = session.path.with_suffix('.airhorn.json')
        self.data = {'version': 3, 'identity': session.identity,
                     'config': session.config.slot_data(), 'items': {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        # Existing durations are part of the receipt, never silently retimed.
        if (isinstance(self.data, dict) and self.data.get('version') == 1
                and self.data.get('identity') == session.identity
                and self.data.get('config') == session.config.slot_data()
                and isinstance(self.data.get('items'), dict)):
            for entry in self.data['items'].values():
                if not isinstance(entry, dict):
                    raise ValueError('Invalid Airhorn journal entry')
                entry.update(mode=session.config.airhorn_mode, duration=session.config.airhorn_duration)
            self.data['version'] = 2
        if (isinstance(self.data, dict) and self.data.get('version') == 2
                and self.data.get('identity') == session.identity
                and self.data.get('config') == session.config.slot_data()
                and isinstance(self.data.get('items'), dict)):
            for entry in self.data['items'].values():
                if not isinstance(entry, dict):
                    raise ValueError('Invalid Airhorn journal entry')
                entry.update(pulse_at=entry.get('elapsed', 0), carry_ms=0)
            self.data['version'] = 3
        self.last_clock = None
        self.playable = False
        self._validate()

    def _validate(self):
        d = self.data
        if (not isinstance(d, dict) or d.get('version') != 3 or d.get('identity') != self.session.identity
                or d.get('config') != self.session.config.slot_data() or not isinstance(d.get('items'), dict)):
            raise ValueError('Airhorn journal identity/configuration mismatch')
        for key, entry in d['items'].items():
            if (not isinstance(key, str) or not key.isdecimal() or str(int(key)) != key or not isinstance(entry, dict)
                    or entry.get('state') not in ('queued', 'active', 'pending', 'held', 'done')
                    or not isinstance(entry.get('item'), dict) or entry['item'].get('item') != ITEM_IDS[AIRHORN]
                    or entry.get('mode') not in ('single_blast', 'timed')
                    or type(entry.get('duration')) is not int or not 30 <= entry['duration'] <= 120
                    or any(type(entry.get(k)) is not int or not 0 <= entry[k] <= limit
                           for k, limit in (('elapsed', entry.get('duration', 120) * 1000), ('next_pulse', 125000),
                                            ('pulses', 24), ('pulse_at', 120000), ('carry_ms', 2**63 - 1)))
                    or (entry.get('instance') is not None and not isinstance(entry['instance'], str))):
                raise ValueError('Invalid Airhorn journal entry')

    def save(self):
        self._validate()
        atomic_json(self.path, self.data)

    def synchronize(self):
        received = self.session.data['received']
        for key, entry in self.data['items'].items():
            if int(key) >= len(received) or received[int(key)] != entry['item']:
                raise ValueError('Server inventory changed a queued or applied Airhorn')
        changed = False
        for i, item in enumerate(received):
            if item['item'] == ITEM_IDS[AIRHORN] and str(i) not in self.data['items']:
                use_yaml = self.preferences['airhorn_mode'] == 'yaml'
                self.data['items'][str(i)] = {'item': dict(item), 'state': 'queued',
                    'elapsed': 0, 'next_pulse': 0, 'pulses': 0, 'instance': None, 'pulse_at': 0, 'carry_ms': 0,
                    'mode': self.session.config.airhorn_mode if use_yaml else self.preferences['airhorn_mode'],
                    'duration': self.session.config.airhorn_duration if use_yaml else self.preferences['airhorn_duration']}
                changed = True
        if changed:
            self.save()

    @property
    def current(self):
        if not self.data:
            return None
        return next(((k, self.data['items'][k]) for k in sorted(self.data['items'], key=int)
                     if self.data['items'][k]['state'] != 'done'), None)

    @property
    def queued(self):
        return sum(e['state'] != 'done' for e in self.data['items'].values()) if self.data else 0

    def clear_on_death(self, token):
        """Cancel the active stack once; never consume a wholly unstarted queue."""
        if not self.data or self.data.get('last_death') == token:
            return 0
        previous = self.data
        self.data = copy.deepcopy(previous)
        current = self.current
        count = 0
        if current:
            _, first = current
            started = first['state'] in ('active', 'pending') or first['pulses'] or first['elapsed']
            if started and first['state'] != 'held':
                for key in sorted(self.data['items'], key=int):
                    entry = self.data['items'][key]
                    if entry['state'] == 'done':
                        continue
                    if entry['state'] == 'held' or entry['mode'] != first['mode']:
                        break
                    entry['state'] = 'done'
                    entry['instance'] = None
                    entry['carry_ms'] = 0
                    entry['resolution'] = 'Active trap cleared on death'
                    count += 1
                    if first['mode'] == 'single_blast':
                        break
        self.data['last_death'] = token
        try:
            self.save()
        except BaseException:
            self.data = previous
            raise
        self.suspend()
        return count

    def suspend(self):
        self.last_clock = None
        self.playable = False

    def poll(self, adapter):
        self.synchronize()
        status = adapter.airhorn_status()
        sample = status['instance'], status['clock']
        elapsed = (max(0, sample[1] - self.last_clock[1])
                   if self.last_clock and self.last_clock[0] == sample[0] else 0)
        self.last_clock = sample
        self.playable = bool(status['ready'])
        current = self.current
        if current is None:
            return
        key, entry = current
        if entry['state'] == 'held':
            return  # A recovery decision is required; later traps remain queued.
        duration = entry['duration'] * 1000
        timed = entry['mode'] == 'timed'
        if entry['state'] in ('active', 'pending') and elapsed:
            # Native replies arrive on a later client poll. Count playable time
            # from submission, not acknowledgement, including the first pulse.
            entry['carry_ms'] += max(0, entry['elapsed'] + elapsed - duration)
            entry['elapsed'] = min(duration, entry['elapsed'] + elapsed)
            self.save()
        while (entry['state'] != 'pending' and (entry['pulses'] or entry['elapsed'])
               and (not timed or entry['elapsed'] >= entry['duration'] * 1000)):
            overflow = entry['carry_ms']
            entry['state'] = 'done'
            if not entry['pulses']:
                entry['resolution'] = 'Timed stack elapsed during a delayed client poll; no catch-up blast emitted'
            self.save()
            current = self.current
            if not current or current[1]['state'] == 'held':
                return
            key, entry = current
            # Adjacent timed receipts share a continuous countdown. Retain each
            # receipt for recovery and carry boundary overshoot into the next.
            if timed and entry['mode'] == 'timed':
                total = entry['elapsed'] + overflow
                entry['elapsed'] = min(entry['duration'] * 1000, total)
                entry['carry_ms'] += max(0, total - entry['duration'] * 1000)
                self.save()
            timed = entry['mode'] == 'timed'
        if entry['state'] != 'pending' and (not self.playable or entry['elapsed'] < entry['next_pulse']):
            return
        receipt = f'{self.session.path.stem}:airhorn:{key}:{entry["pulses"]}'

        def reserve():
            entry['state'] = 'pending'
            entry['instance'] = status['instance']
            entry['pulse_at'] = entry['elapsed']
            self.save()  # Must commit before the game command can emit noise.

        outcome = adapter.airhorn_pulse(receipt, entry['instance'], before_submit=reserve)
        if outcome == 'applied':
            entry['pulses'] += 1
            entry['state'] = 'active' if timed else 'done'
            entry['instance'] = None
            # Schedule against submission. Reply latency must not add half a
            # second to every interval or extend each stacked trap.
            entry['next_pulse'] = entry['pulse_at'] + 5000
            self.save()
            if self.notify:
                self.notify(Toast('ARCHIPELAGO · AIRHORN', AIRHORN,
                    'A loud noise came from your current position.',
                    'Enemies use their normal hearing and search behavior.', item_colour(4),
                    sound=True, sound_only=entry['pulses'] > 1))
        elif outcome == 'not_applied' and entry['state'] == 'pending':
            entry['state'] = 'active' if entry['pulses'] else 'queued'
            entry['instance'] = None
            if not entry['pulses']:
                entry['elapsed'] = entry['carry_ms'] = 0
            self.save()
        elif outcome == 'uncertain':
            entry['state'] = 'held'
            self.save()

    def retire_held(self):
        if not self.data:
            return 0
        count = 0
        for entry in self.data['items'].values():
            if entry['state'] == 'held':
                entry['state'] = 'done'
                entry['resolution'] = 'Retired without replaying an uncertain blast'
                count += 1
        if count:
            self.save()
        return count

    def card(self):
        current = self.current
        if not current:
            return None
        _, entry = current
        if entry['state'] == 'held':
            text = 'Airhorn held for recovery'
            detail = 'An interrupted blast could not be confirmed. Use Retire held rewards to clear it.'
        elif entry['mode'] == 'single_blast':
            text, detail = 'Airhorn queued — single blast', 'Waiting for controllable gameplay in an unlocked mission.'
        else:
            remaining, count = self.timed_stack()
            state = 'queued' if not entry['pulses'] else 'active' if self.playable else 'paused'
            text = f'Airhorn {state} — {remaining}s remaining'
            detail = f'{count} timed trap(s) stacked. Noise every five seconds of active gameplay.'
        return Toast('ARCHIPELAGO · TRAP', text, detail,
                     'Waiting for gameplay.' if not self.playable else 'Timer pauses when gameplay is unavailable.', item_colour(4))

    def timed_stack(self):
        """Remaining time for the contiguous timed block at the head of the queue."""
        total = count = 0
        if self.data:
            for key in sorted(self.data['items'], key=int):
                entry = self.data['items'][key]
                if entry['state'] == 'done':
                    continue
                if entry['mode'] != 'timed' or entry['state'] == 'held':
                    break
                total += max(0, entry['duration'] * 1000 - entry['elapsed'])
                count += 1
        return math.ceil(total / 1000), count
