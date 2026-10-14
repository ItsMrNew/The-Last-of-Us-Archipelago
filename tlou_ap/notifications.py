"""Live item transfers. Inventory synchronization never creates notifications."""
from collections import deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
import unicodedata

from .catalog import GAME, ITEM_IDS, LOCATION_IDS, PROGRESSIVE_CHAPTER
from .session import atomic_json

# Same values and precedence as the user's Zero Hour zh/notifications.py.
ITEM_COLOURS = ((1, '#AF99EF'), (2, '#6D8BE8'), (4, '#FA8072'), (0, '#00EEEE'))
UNKNOWN_ITEM_COLOUR = '#AEB6C2'
POSITIONS = ('top_right', 'top_left', 'bottom_right', 'bottom_left')
DEFAULT_SETTINGS = {'scope': 'you', 'seconds': 8, 'position': 'top_right', 'volume': 100}


def item_flag(flags, *, location=0):
    """Use this transfer's server flags, never a game/name classification table.

    AP console grants use negative locations and can default flags to zero
    without looking up the item's type. That zero is unknown, not known filler.
    """
    if type(flags) is not int or flags < 0 or (location < 0 and flags == 0):
        return None
    return next((flag for flag in (1, 2, 4) if flags & flag), 0 if flags == 0 else None)


def item_colour(flags):
    return dict(ITEM_COLOURS).get(item_flag(flags), UNKNOWN_ITEM_COLOUR)


def clean_text(value, limit=180):
    text = unicodedata.normalize('NFC', str(value))
    text = ''.join(c if c in '\n\t' else '' if unicodedata.category(c).startswith('C') else c for c in text)
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def validate_settings(value):
    if (not isinstance(value, dict) or value.get('scope') not in ('you', 'all', 'off')
            or type(value.get('seconds')) is not int or not 2 <= value['seconds'] <= 30):
        raise ValueError('Invalid notification settings')
    position, volume = value.get('position', 'top_right'), value.get('volume', 100)
    if position not in POSITIONS or type(volume) is not int or not 0 <= volume <= 100:
        raise ValueError('Invalid notification position or Airhorn volume')
    return {'scope': value['scope'], 'seconds': value['seconds'], 'position': position, 'volume': volume}


@dataclass(frozen=True)
class Transfer:
    sender: int
    recipient: int
    item: int
    location: int
    flags: int | None


@dataclass(frozen=True)
class Toast:
    heading: str
    item: str
    detail: str
    location: str
    colour: str
    involves_local: bool = True
    sound: bool = False
    sound_only: bool = False

    @property
    def parts(self):
        return [(self.detail + ': ', None), (self.item, self.colour),
                (' — ' + self.location, None) if self.location else ('', None)]


def mission_lock_toast(name, *, chapter_unlocked=False, connected=True, compatible=True):
    if not compatible:
        detail = 'This save does not match your Archipelago run. Load a save from this run.'
    elif not connected:
        detail = 'Reconnect to Archipelago to restore mission access.'
    elif chapter_unlocked:
        detail = 'Complete the previous mission to continue.'
    else:
        detail = f'Mission has not been unlocked yet. Receive {PROGRESSIVE_CHAPTER} to unlock this mission.'
    return Toast('ARCHIPELAGO · MISSION LOCKED', name, detail,
                 'Use the pause menu to load another save or return to the main menu.', item_colour(1))


class TransferFeed:
    def __init__(self, directory, clock=time.monotonic):
        self.directory, self.clock = Path(directory), clock
        self.path = None
        self.identity = None
        self.team = self.slot = 0
        self.players, self.slots = {}, {}
        self.items = {GAME: {code: name for name, code in ITEM_IDS.items()}}
        self.locations = {GAME: {code: name for name, code in LOCATION_IDS.items()}}
        self.seen = set()
        self.waiting = deque(maxlen=512)

    def connected(self, seed, packet):
        identity = (seed, packet['team'], packet['slot'])
        if identity != self.identity:
            key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            path = self.directory / (key + '.json')
            seen = set()
            if path.exists():
                saved = json.loads(path.read_text(encoding='utf-8'))
                if (not isinstance(saved, dict) or saved.get('identity') != list(identity)
                        or saved.get('version') != 1):
                    raise ValueError('Notification history identity mismatch')
                entries = saved.get('seen', [])
                if (not isinstance(entries, list) or any(not isinstance(e, list) or len(e) != 4
                        or any(type(n) is not int for n in e) for e in entries)):
                    raise ValueError('Invalid notification history')
                seen = {tuple(entry) for entry in entries}
            # Commit only after history validation succeeds. A reconnect must
            # retry failed reads, never bypass validation and replace history.
            self.identity, self.path, self.seen = identity, path, seen
            self.waiting.clear()
        self.team, self.slot = identity[1:]
        self.players = {}
        self.slots = {int(k): v for k, v in packet.get('slot_info', {}).items()
                      if str(k).isdecimal() and isinstance(v, dict)}
        self.update_players(packet.get('players', []))
        return sorted({v['game'] for v in self.slots.values() if isinstance(v.get('game'), str)})

    def update_players(self, players):
        for player in players:
            if (isinstance(player, dict) and player.get('team') == self.team
                    and type(player.get('slot')) is int):
                self.players[player['slot']] = clean_text(player.get('alias') or player.get('name') or player['slot'])

    def data_package(self, packet):
        games = packet.get('data', {}).get('games', {})
        for game, data in games.items():
            if not isinstance(data, dict):
                continue
            for target, field in ((self.items, 'item_name_to_id'), (self.locations, 'location_name_to_id')):
                values = data.get(field, {})
                if isinstance(values, dict):
                    target.setdefault(game, {}).update({code: clean_text(name) for name, code in values.items()
                                                       if isinstance(name, str) and type(code) is int})

    def game(self, slot):
        return self.slots.get(slot, {}).get('game', GAME if slot == self.slot else '')

    def name(self, slot):
        return self.players.get(slot, clean_text(self.slots.get(slot, {}).get(
            'name', 'Server' if slot == 0 else f'Player {slot}')))

    def receive(self, packet):
        if (self.path is None or packet.get('type') not in ('ItemSend', 'ItemCheat')
                or packet.get('team', self.team) != self.team):
            return
        item, recipient = packet.get('item'), packet.get('receiving')
        if (not isinstance(item, dict) or type(recipient) is not int or recipient < 0
                or any(type(item.get(k)) is not int for k in ('player', 'item', 'location'))):
            return
        transfer = Transfer(item['player'], recipient, item['item'], item['location'],
                            item_flag(item.get('flags'), location=item['location']))
        key = (transfer.sender, recipient, transfer.item, transfer.location)
        # Real checks cannot happen twice; server grants at negative locations can.
        if transfer.location >= 0:
            if key in self.seen:
                return
            updated = self.seen | {key}
            atomic_json(self.path, {'version': 1, 'identity': self.identity, 'seen': sorted(updated)})
            self.seen = updated
        self.waiting.append((transfer, self.clock()))

    def drain(self):
        ready, remaining = [], deque(maxlen=512)
        for transfer, received in self.waiting:
            known = transfer.item in self.items.get(self.game(transfer.recipient), {})
            if not known and self.clock() - received < 5:
                remaining.append((transfer, received))
            else:
                ready.append(self.describe(transfer))
        self.waiting = remaining
        return ready

    def describe(self, transfer):
        sender, recipient = transfer.sender, transfer.recipient
        group = self.slot in self.slots.get(recipient, {}).get('group_members', [])
        incoming, outgoing = recipient == self.slot or group, sender == self.slot
        item = self.items.get(self.game(recipient), {}).get(transfer.item, f'Item #{transfer.item}')
        location = self.locations.get(self.game(sender), {}).get(transfer.location,
                    f'Check #{transfer.location}' if transfer.location >= 0 else 'Server grant')
        if sender == recipient and outgoing:
            heading, detail = 'ITEM FOUND', 'You found your item'
        elif incoming:
            heading, detail = 'ITEM RECEIVED', 'From ' + self.name(sender)
            if group:
                detail += ' · to ' + self.name(recipient)
        elif outgoing:
            heading, detail = 'ITEM SENT', 'To ' + self.name(recipient)
        else:
            heading, detail = 'ITEM TRANSFER', self.name(sender) + ' → ' + self.name(recipient)
        return Toast(heading, item, detail, location, item_colour(transfer.flags), incoming or outgoing)

    def render_server_text(self, parts):
        rendered = []
        for part in parts if isinstance(parts, list) else []:
            if not isinstance(part, dict):
                continue
            text, kind = str(part.get('text', '')), part.get('type')
            try:
                if kind == 'player_id':
                    text = self.name(int(text))
                elif kind in ('item_id', 'location_id'):
                    names = self.items if kind == 'item_id' else self.locations
                    text = names.get(self.game(part.get('player')), {}).get(int(text), text)
            except (TypeError, ValueError):
                pass
            rendered.append(text)
        return clean_text(''.join(rendered), 2000)


class ToastQueue:
    """Display time runs only while the game has focus; pausing the game is fine."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.settings = dict(DEFAULT_SETTINGS)
        self.pending = deque(maxlen=512)
        self.active = []
        self.last_tick = clock()
        self.was_visible = False
        self.visible_count = 0

    def accepts(self, toast):
        return self.settings['scope'] == 'all' or self.settings['scope'] == 'you' and toast.involves_local

    def configure(self, settings):
        self.settings = validate_settings(settings)
        self.pending = deque((t for t in self.pending if self.accepts(t)), maxlen=512)
        self.active = [(t, age) for t, age in self.active if self.accepts(t)]

    def add(self, toast):
        if self.accepts(toast):
            self.pending.append(toast)

    def tick(self, visible):
        now = self.clock()
        elapsed = max(0, now - self.last_tick) if visible and self.was_visible else 0
        self.last_tick, self.was_visible = now, visible
        self.active = [(t, age + (elapsed if i < self.visible_count else 0))
                       for i, (t, age) in enumerate(self.active)
                       if age + (elapsed if i < self.visible_count else 0) < self.settings['seconds']]
        if visible:
            while len(self.active) < 2 and self.pending:
                self.active.append((self.pending.popleft(), 0))
        self.visible_count = len(self.active) if visible else 0
        return tuple(t for t, _ in self.active) if visible else ()

    def limit_visible(self, count):
        # Layout may retain cards behind persistent lock/trap cards. Their
        # display time starts only once they actually fit on screen.
        self.visible_count = max(0, min(count, len(self.active)))
