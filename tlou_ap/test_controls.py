"""Local, run-bound mailbox for the separately built test utility.

Only the client polling thread handles requests or writes run state. The utility
has no server credentials and never writes native bridge commands or run files.
"""
import ctypes
import json
import logging
import mmap
import re
import secrets
import struct
import time
from pathlib import Path

from .catalog import COLLECTIBLES, MISSIONS, CHAPTERS, CHECKS, collectible_check
from .session import atomic_json

LOG = logging.getLogger('tlou-ap')
REQUEST = struct.Struct('<4I64s48s')
HEADER = struct.Struct('<6I2i4I64s128s272s')
ROW = struct.Struct('<4I240s')
MAX_ROWS, MAGIC = 192, 0x31545541
SIZE = REQUEST.size + HEADER.size + MAX_ROWS * ROW.size
assert REQUEST.size == 128 and HEADER.size == 512 and ROW.size == 256


def encoded(text, size):
    return str(text).encode('utf-8')[:size - 1].decode('utf-8', errors='ignore').encode('utf-8')


class TestControls:
    def __init__(self, client, mapping=None, clock=time.monotonic):
        self.client, self.adapter, self.clock = client, client.adapter, clock
        self.token = secrets.token_hex(24)
        self.mapping = mapping if mapping is not None else mmap.mmap(
            -1, SIZE, tagname=f'Local\\TLOUAP_Test_v1_{self.adapter.bridge.pid}')
        self.mapping[:] = bytes(SIZE)
        self.ack = self.outcome = self.revision = 0
        self.message = 'Select a check or supply action in the test app.'
        self.pending = None
        self.waiting_checks = set()
        self.path = self.adapter.ledger.path.with_suffix('.test-controls.json')
        self.audit = json.loads(self.path.read_text()) if self.path.exists() else {'requests': {}}
        self.last_received = 0
        self.publish()

    def ready(self):
        c, a = self.client, self.adapter
        return bool(c.connected and c.session and c.inventory.synchronized and
                    a.bound and a.ledger.data['started'] and not a.compatibility_error)

    def record(self, request, state, **extra):
        self.audit['requests'][request['nonce']] = {**request, 'state': state,
            'identity': self.client.session.identity, 'time': time.time(), **extra}
        atomic_json(self.path, self.audit)

    def reject(self, text):
        self.outcome, self.message = 4, text
        LOG.info('Test utility: %s', text)

    def accept_request(self):
        raw = bytes(self.mapping[:REQUEST.size])
        seq, action, index, reserved, token, nonce = REQUEST.unpack(raw)
        if not seq or seq == self.last_received:
            return
        # Writer publishes sequence last. The stable copy binds every field.
        if self.mapping[:4] != raw[:4]:
            return
        self.last_received = self.ack = seq
        if self.pending:
            self.reject('Another test action is still pending.'); return
        self.waiting_checks.clear()
        if token.rstrip(b'\0') != self.token.encode() or reserved:
            self.reject('The active client changed. Refresh and select the action again.'); return
        if not self.ready():
            self.reject('Connect to a matching active Archipelago run first.'); return
        if not re.fullmatch(b'[0-9a-f]{32}\x00{16}', nonce):
            self.reject('Invalid test request identifier.'); return
        nonce = nonce[:32].decode()
        if nonce in self.audit['requests']:
            self.reject('This request was already handled; it will not be repeated.'); return
        session = self.client.session
        if action == 1:
            if index >= len(COLLECTIBLES) or not session.config.collectible_checks:
                self.reject('That collectible check is not enabled in this seed.'); return
            if not session.can_collect(index):
                self.reject('Reach and unlock this collectible\'s chapter first.'); return
        elif action == 2:
            if index >= len(MISSIONS) or not session.can_start(index):
                self.reject('Complete missions in story order and unlock the chapter first.'); return
            if not session.config.mission_checks and not session.config.chapter_checks:
                self.reject('Mission and chapter checks are disabled in this seed.'); return
        elif action not in (3, 4) or index:
            self.reject('Unknown test action.'); return
        request = {'action': action, 'index': index, 'nonce': nonce, 'sequence': seq,
                   'native_instance': self.adapter.native_instance}
        self.record(request, 'accepted')
        self.pending = {**request, 'since': self.clock(), 'command': None}
        self.outcome, self.message = 1, 'Waiting for stable gameplay. Resume the game to apply.'
        if action == 2:
            # A deliberate AP-only override. Never fabricate native task events,
            # completion flags, or a game-world transition.
            before = set(session.earned_checks)
            overrides = self.adapter.ledger.data.setdefault('test_missions', [])
            if index not in session.data['missions'] and index not in overrides:
                overrides.append(index); overrides.sort(); self.adapter.ledger.save()
            session.complete_mission(index)
            checks = session.earned_checks - before
            checks.update(check.id for check in session.config.active_checks
                if check.id in session.earned_checks and
                ((check.category == 'mission' and check.mission == index) or
                 (check.category == 'chapter' and check.chapter == MISSIONS[index]['chapter'])))
            self.finish(request, checks)

    def finish(self, request, checks=()):
        self.record(request, 'applied', checks=sorted(checks))
        self.pending = None
        self.waiting_checks = set(checks)
        self.outcome = 2 if self.waiting_checks - self.client.checked else 3
        self.message = ('Applied locally; waiting for server confirmation.' if self.outcome == 2 else
                        'Confirmed by the Archipelago server.' if checks else
                        'Mission complete. The chapter check waits for its remaining missions.'
                        if request['action'] == 2 else 'Inventory filled to 3.')
        LOG.info('Test utility: action %d, index %d applied.', request['action'], request['index'])

    def step(self):
        """Return True only while this controller owns a native command."""
        self.accept_request()
        request = self.pending
        if request:
            bridge = self.adapter.bridge
            if request['command'] is not None:
                result = bridge.command_result(request['command'])
                if result is None:
                    if self.clock() - request['sent'] > 10:
                        self.outcome, self.message = 5, 'Game command is still pending; it will not be repeated.'
                    self.publish(); return True
                if result == 1:
                    checks = set()
                    if request['action'] == 1:
                        index = request['index']
                        entries = self.adapter.ledger.data['collectibles']
                        if index not in entries:
                            entries.append(index); self.adapter.ledger.save()
                        self.client.session.collect(index)
                        checks.add(collectible_check(COLLECTIBLES[index]).id)
                    self.finish(request, checks)
                else:
                    self.record(request, 'uncertain' if result == 3 else 'not_applied')
                    self.pending = None
                    self.outcome = 5 if result == 3 else 4
                    self.message = ('Could not confirm the game result. No automatic retry.' if result == 3 else
                                    'Not applied. Resume stable gameplay and try again.')
            elif not self.ready() or request['native_instance'] != self.adapter.native_instance:
                self.record(request, 'cancelled'); self.pending = None
                self.reject('Run or connection changed; the pending action was cancelled.')
            elif self.clock() - request['since'] > 60:
                self.record(request, 'cancelled'); self.pending = None
                self.reject('Gameplay was not ready. Resume the game and try again.')
            else:
                a, s = self.adapter, bridge.shared
                supply = bridge.supplies()
                free = not (bridge.command_busy or a.receipt_query or a.deathlink.command or a.airhorn.command)
                if (free and supply['ready'] and s.current > 2 and not s.pending and not s.blocked
                        and s.allowed & (1 << (s.current - 1))):
                    kind = {1: 8, 3: 9, 4: 10}[request['action']]
                    argument = request['index'] if kind == 8 else 3
                    receipt = int(request['nonce'][:16], 16) or 1
                    # Durable reservation precedes submission; never replay it on reconnect.
                    self.record(request, 'submitted')
                    request['command'] = bridge.begin_command(kind, argument | (s.current << 8), receipt)
                    request['sent'] = self.clock()
                    self.publish(); return True
        if self.waiting_checks and self.waiting_checks <= self.client.checked:
            self.outcome, self.message = 3, 'Confirmed by the Archipelago server.'
        self.publish()
        return False

    def publish(self):
        c, a = self.client, self.adapter
        session = c.session
        rows = []
        if session:
            for check in CHECKS:
                if check.category not in ('collectible', 'mission'):
                    continue
                collect = check.category == 'collectible'
                enabled = getattr(session.config, 'collectible_checks' if collect else 'mission_checks')
                if not collect:
                    enabled |= session.config.chapter_checks
                accessible = session.can_collect(check.native_index) if collect else session.can_start(check.native_index)
                flags = int(enabled and accessible)
                flags |= 2 if check.id in session.earned_checks else 0
                flags |= 4 if check.id in c.checked else 0
                flags |= 8 if not enabled else 0
                mission = MISSIONS[check.mission]
                label = (COLLECTIBLES[check.native_index]['name'] + ' — ' + mission['name'] if collect
                         else f"{check.native_index+1:02d}. {mission['name']}")
                label += ' — ' + CHAPTERS[check.chapter]['name']
                rows.append(ROW.pack(1 if collect else 2, check.native_index, check.id, flags,
                                     encoded(label, 240)))
        if len(rows) > MAX_ROWS:
            raise ValueError('Test protocol catalog capacity exceeded')
        supply = a.bridge.supplies()
        tick = ctypes.windll.kernel32.GetTickCount() & 0xffffffff
        flags = int(self.ready()) | (2 if self.pending else 0)
        self.revision = (self.revision + 2) & 0x7ffffffe
        struct.pack_into('<I', self.mapping, REQUEST.size, self.revision | 1)
        header = HEADER.pack(self.revision | 1, MAGIC, 1, SIZE, self.ack, self.outcome,
            supply['shivs'], supply['health_kits'], len(rows), flags, tick, 0,
            encoded(self.token,64), encoded(c.name if session else 'Not connected',128),
            encoded(self.message if self.ready() else 'Connect to a matching active Archipelago run.',272))
        self.mapping[REQUEST.size:REQUEST.size+HEADER.size] = header
        self.mapping[REQUEST.size+HEADER.size:] = b''.join(rows).ljust(MAX_ROWS*ROW.size,b'\0')
        struct.pack_into('<I', self.mapping, REQUEST.size, self.revision)

    def close(self):
        self.mapping[REQUEST.size:] = bytes(SIZE-REQUEST.size)
        self.mapping.close()

    def disconnected(self):
        self.token = secrets.token_hex(24)
        if self.pending and self.pending['command'] is None:
            self.record(self.pending, 'cancelled')
            self.pending = None
            self.reject('Disconnected; pending test action cancelled.')
        self.publish()
