"""Run-scoped DeathLink inbox, durable before notification or native dispatch."""
import json
import math
import time
import uuid

from .notifications import Toast, clean_text, item_colour
from .session import atomic_json


class DeathLink:
    def __init__(self, clock=time.monotonic, wall_clock=time.time):
        self.wall_clock = wall_clock
        self.enabled = False
        self.path = None
        self.data = self.empty(None)

    @staticmethod
    def empty(identity):
        return {'version': 1, 'identity': identity, 'seen': [], 'incoming': None, 'sent': 0, 'received': 0}

    def bind(self, session):
        path = session.path.parent / 'deathlink' / session.path.name
        if path == self.path and self.data['identity'] == session.identity:
            return
        data = self.empty(dict(session.identity))
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            self.validate(data, session.identity)
            # The process may have ended after dispatch but before its reply was
            # saved. Never turn that uncertainty into another automatic death.
            if data['incoming'] and data['incoming']['state'] != 'queued':
                data['incoming']['state'] = 'held'
                atomic_json(path, data)
        self.path, self.data = path, data

    @staticmethod
    def validate(data, identity):
        error = 'Invalid DeathLink journal; preserve it for recovery.'
        if (not isinstance(data, dict) or data.get('version') != 1 or data.get('identity') != identity
                or set(data) != {'version', 'identity', 'seen', 'incoming', 'sent', 'received'}):
            raise ValueError(error)
        if any(type(data[k]) is not int or data[k] < 0 for k in ('sent', 'received')):
            raise ValueError(error)
        seen = data['seen']
        if not isinstance(seen, list) or len(seen) > 256:
            raise ValueError(error)
        for key in seen:
            if (not isinstance(key, list) or len(key) != 2 or not isinstance(key[0], str)
                    or not key[0] or len(key[0]) > 256 or type(key[1]) not in (float, int)
                    or not 0 <= key[1] <= 1e15 or not math.isfinite(key[1])):
                raise ValueError(error)
        entry = data['incoming']
        if entry is not None:
            if (not isinstance(entry, dict) or set(entry) != {'receipt', 'source', 'cause', 'state'}
                    or not isinstance(entry['receipt'], str) or len(entry['receipt']) != 32
                    or any(c not in '0123456789abcdef' for c in entry['receipt'])
                    or any(not isinstance(entry[k], str) or len(entry[k]) > 180 for k in ('source', 'cause'))
                    or entry['state'] not in ('queued', 'dispatching', 'awaiting_death', 'held')):
                raise ValueError(error)

    def commit(self, **changes):
        data = {**self.data, **changes}
        self.validate(data, self.data['identity'])
        if self.path:
            atomic_json(self.path, data)
        self.data = data

    @property
    def pending(self):
        entry = self.data['incoming']
        return entry if entry and entry['state'] in ('queued', 'dispatching') else None

    @property
    def state(self):
        return self.data['incoming']['state'] if self.data['incoming'] else 'idle'

    @property
    def sent(self):
        return self.data['sent']

    @property
    def received(self):
        return self.data['received']

    def configure(self, enabled, *, preserve_pending=True):
        # Disabling/reconnecting never deletes a waiting death. preserve_pending
        # remains accepted for compatibility with existing diagnostic tools.
        self.enabled = enabled
        if not enabled and self.state in ('dispatching', 'awaiting_death'):
            self.commit(incoming={**self.data['incoming'], 'state': 'held'})

    def receive(self, packet, source, dead=False):
        if not self.enabled or not isinstance(packet.get('tags'), list) or 'DeathLink' not in packet['tags']:
            return None
        data = packet.get('data')
        if not isinstance(data, dict):
            return None
        stamp, sender = data.get('time'), data.get('source')
        if (type(stamp) not in (int, float) or not 0 <= stamp <= 1e15 or not math.isfinite(stamp)
                or not isinstance(sender, str) or not sender or len(sender) > 256 or sender == source):
            return None
        key = [sender, stamp]
        if key in self.data['seen']:
            return None
        changes = {'seen': [*self.data['seen'], key][-256:]}
        # Coalesce bursts, including while dispatching, and don't kill dead players.
        if dead or self.data['incoming']:
            self.commit(**changes)
            return None
        cause = data.get('cause')
        entry = {'receipt': uuid.uuid4().hex, 'state': 'queued', 'source': clean_text(sender),
                 'cause': clean_text(cause) if isinstance(cause, str) and cause else ''}
        self.commit(**changes, incoming=entry, received=self.received + 1)
        return self.toast('Received', entry['cause'] or f"Received from {entry['source']}",
                          'Queued until you regain control of your character.')

    def reserve(self, receipt):
        if not self.pending or self.pending['receipt'] != receipt or self.state != 'queued':
            raise ValueError('DeathLink is not queued for dispatch')
        self.commit(incoming={**self.pending, 'state': 'dispatching'})

    def resolve(self, receipt, outcome):
        if outcome not in ('not_applied', 'pending', 'submitted', 'uncertain'):
            raise ValueError('Invalid DeathLink delivery outcome')
        if not self.pending or self.pending['receipt'] != receipt or outcome == 'pending':
            return
        state = {'not_applied': 'queued', 'submitted': 'awaiting_death', 'uncertain': 'held'}[outcome]
        if self.state != state:
            self.commit(incoming={**self.pending, 'state': state})

    def unconfirmed(self):
        if self.data['incoming'] and self.state != 'queued':
            self.commit(incoming={**self.data['incoming'], 'state': 'held'})

    def confirmed_death(self):
        if self.data['incoming']:
            self.commit(incoming=None)

    def local_death(self, source):
        if not self.enabled:
            return None
        stamp = self.wall_clock()
        # A natural death satisfies a waiting or uncertain incoming death too.
        self.commit(incoming=None, seen=[*self.data['seen'], [source, stamp]][-256:], sent=self.sent + 1)
        return {'cmd': 'Bounce', 'tags': ['DeathLink'],
                'data': {'time': stamp, 'source': source, 'cause': f'{source} died in The Last of Us Part I.'}}

    @staticmethod
    def toast(label, detail, location=''):
        return Toast('ARCHIPELAGO · DEATHLINK', label, detail, location, item_colour(4))
