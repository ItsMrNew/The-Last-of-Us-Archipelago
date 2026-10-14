"""Archipelago protocol core shared by native and test adapters.

Adapters must supply validated completion events, run identity, persistent
reward receipts, and a gate covering all launch/continue/transition paths.
The read-only observer cannot satisfy that interface and is rejected.
"""
import asyncio
import json
import logging
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid
from contextlib import asynccontextmanager

from websockets.legacy.client import connect
from websockets.exceptions import InvalidMessage

from .catalog import GAME, Config
from .session import Inventory, Session, SyncRequired
from .notifications import TransferFeed
from .deathlink import DeathLink
from .airhorn import Airhorn
from .timed_effects import TimedEffects
from .preferences import DEFAULT_RUNTIME, validate_runtime, death_enabled

LOG = logging.getLogger('tlou-ap')
REQUIRED_CAPABILITIES = {'mission_completion', 'collectible_events', 'chapter_gate', 'item_delivery', 'managed_run'}


def server_uri(address):
    uri = address if '://' in address else 'ws://' + address
    parts = urlsplit(uri)
    if (parts.scheme not in ('ws', 'wss') or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ('', '/')):
        raise ValueError('Use a server address such as host:port, ws://host:port or wss://host:port')
    _ = parts.port
    return uri


@asynccontextmanager
async def open_server(address):
    """Negotiate plain/local or TLS AP servers before sending any AP packets."""
    uri = server_uri(address)
    try:
        socket = await connect(uri, max_size=8 * 1024 * 1024, open_timeout=10, close_timeout=3)
    except InvalidMessage:
        if not uri.startswith('ws://'):
            raise
        # TLS-only AP hosts close a plaintext handshake. Match CommonClient's
        # upgrade behavior; never downgrade TLS or retry an established session.
        uri = 'wss://' + uri[len('ws://'):]
        LOG.info('Server did not accept a plain WebSocket; trying an encrypted connection.')
        socket = await connect(uri, max_size=8 * 1024 * 1024, open_timeout=10, close_timeout=3)
    try:
        yield socket, uri
    finally:
        await socket.close()


class Client:
    def __init__(self, name, directory, adapter, password=None, notify=None, preferences=None):
        missing = REQUIRED_CAPABILITIES - set(getattr(adapter, 'capabilities', ()))
        if missing:
            raise ValueError('Native adapter is not playable yet; missing: ' + ', '.join(sorted(missing)))
        self.name, self.directory, self.adapter, self.password = name, directory, adapter, password
        self.inventory = Inventory()
        self.session = None
        self.seed = None
        self.checked = set()
        self.connected = False
        self.goal_sent = False
        self.sent_at = {}
        self.feed = TransferFeed(Path(directory) / 'notifications')
        self.feed_ready = False
        self.notify = notify
        self.deathlink = DeathLink()
        self.airhorn = Airhorn(notify)
        self.timed_effects = TimedEffects()
        self.preferences = validate_runtime(preferences or DEFAULT_RUNTIME)
        self.airhorn.configure(self.preferences)
        self.resolved_server = None
        if hasattr(adapter, "set_player_death_handler"):
            adapter.set_player_death_handler(self.on_player_death)

    def on_player_death(self, token):
        if self.airhorn.data and self.airhorn.data.get('last_death') == token and (not self.timed_effects.data or self.timed_effects.data.get('last_death') == token):
            return
        count = self.airhorn.clear_on_death(token)
        count += self.timed_effects.clear_on_death(token, self.adapter)
        self.adapter.cancel_trap_commands()
        if count:
            LOG.info('Death cleared %d active trap receipt(s).', count)

    def set_preferences(self, value):
        self.preferences = validate_runtime(value)
        self.airhorn.configure(self.preferences)

    async def apply_death_preference(self, socket, *, force=False):
        enabled = death_enabled(self.preferences, self.session.config)
        if force or enabled != self.deathlink.enabled:
            self.configure_death_link(enabled, preserve_pending=True)
            # Initial Connect already advertises AP without DeathLink.
            if enabled or not force:
                await self.send(socket, {'cmd': 'ConnectUpdate', 'tags': ['AP', 'DeathLink'] if enabled else ['AP']})
            LOG.info('DeathLink %s (%s). Waiting deaths are preserved.',
                     'enabled' if enabled else 'disabled', self.preferences['death_link'])

    def death_notification(self, toast):
        if toast:
            LOG.info('DeathLink: %s', toast.detail)
            if self.notify:
                self.notify(toast)

    def configure_death_link(self, enabled, *, preserve_pending=False):
        if enabled and 'death_link' not in self.adapter.capabilities:
            raise ValueError('This room requires a client/native bridge with DeathLink support.')
        self.deathlink.configure(enabled, preserve_pending=preserve_pending)
        if hasattr(self.adapter, 'configure_death_link'):
            self.adapter.configure_death_link(enabled)

    async def send(self, socket, *packets):
        await socket.send(json.dumps(packets))

    def gate(self):
        if not self.connected or not self.inventory.synchronized or self.session is None:
            self.adapter.set_gate(None)
        else:
            self.adapter.set_gate(self.session)

    async def handle(self, socket, packet):
        command = packet.get('cmd')
        if command == 'RoomInfo':
            self.seed = packet['seed_name']
            await self.send(socket, {'cmd': 'Connect', 'game': GAME, 'name': self.name, 'password': self.password,
                                    'uuid': str(uuid.uuid5(uuid.NAMESPACE_URL, self.adapter.run_id + self.name)),
                                    'version': {'major': 0, 'minor': 6, 'build': 7, 'class': 'Version'},
                                    'items_handling': 7, 'tags': ['AP'], 'slot_data': True})
        elif command == 'ConnectionRefused':
            raise ValueError('Connection refused: ' + ', '.join(packet.get('errors', [])))
        elif command == 'Connected':
            if self.seed is None:
                raise ValueError('Connected before RoomInfo')
            locations = set(packet['checked_locations']) | set(packet['missing_locations'])
            config = Config.from_slot_data(packet['slot_data'], locations)
            if config.airhorn_trap_percentage and 'airhorn' not in self.adapter.capabilities:
                raise ValueError('This room requires a client/native bridge with Airhorn support.')
            session = Session(self.directory, self.seed, packet['team'], packet['slot'], self.adapter.run_id, config)
            self.adapter.bind(session.identity, resume=session.path.exists())
            self.session = session
            if config.resource_supplies and 'resources' not in self.adapter.capabilities:
                raise ValueError('This seed requires resource delivery support')
            required_effects = bool(config.shaky_hands_percentage) | (bool(config.faulty_flashlight_percentage) << 1)
            if required_effects and ('timed_effects' not in self.adapter.capabilities or
                    self.adapter.timed_effect_status()['supported'] & required_effects != required_effects):
                raise ValueError('This seed requires native trap hooks that this build does not support')
            self.timed_effects.bind(session)
            self.airhorn.bind(session)
            self.checked = set(packet['checked_locations'])
            self.connected = True
            # Empty AP inventories may omit ReceivedItems. Starting chapters are
            # safe to allow; cached rewards/unlocks are never trusted on reconnect.
            self.inventory = Inventory()
            self.inventory.synchronized = not bool(session.data['received'])
            # Gate with the authoritative stream, without discarding saved receipts.
            self.adapter.set_gate(None)
            await self.send(socket, {'cmd': 'Sync'})
            self.deathlink.bind(session)
            await self.apply_death_preference(socket, force=True)
            if self.deathlink.enabled:
                LOG.info('DeathLink enabled for this room.')
                if self.deathlink.state == 'queued':
                    LOG.info('Restored waiting DeathLink for this managed run.')
                elif self.deathlink.state == 'held':
                    LOG.warning('DeathLink confirmation is uncertain after interruption. '
                                'It will not be repeated; your next confirmed death clears the hold.')
            try:
                games = self.feed.connected(self.seed, packet)
            except (OSError, ValueError, TypeError) as error:
                self.feed_ready = False
                LOG.warning('Notifications unavailable: %s', error)
            else:
                self.feed_ready = True
                if games:
                    await self.send(socket, {'cmd': 'GetDataPackage', 'games': games})
        elif command == 'ReceivedItems':
            if self.session is None:
                raise ValueError('ReceivedItems before Connected')
            try:
                received = self.inventory.apply(packet['index'], packet['items'])
            except SyncRequired:
                self.gate()
                await self.send(socket, {'cmd': 'Sync'})
                return
            self.session.record_inventory(received)
            self.airhorn.synchronize()
            self.timed_effects.synchronize()
            self.gate()
        elif command == 'RoomUpdate':
            if self.session is None:
                raise ValueError('RoomUpdate before Connected')
            updated = set(packet.get('checked_locations', []))
            valid = {check.id for check in self.session.config.active_checks}
            if not updated <= valid:
                raise ValueError('Server acknowledged unknown locations')
            self.checked.update(updated)
            self.feed.update_players(packet.get('players', []))
        elif command == 'DataPackage':
            try:
                self.feed.data_package(packet)
            except (TypeError, AttributeError, ValueError) as error:
                LOG.warning('Notification name lookup unavailable: %s', error)
        elif command == 'PrintJSON':
            if self.feed_ready and packet.get('type') in ('ItemSend', 'ItemCheat'):
                try:
                    self.feed.receive(packet)
                except (OSError, ValueError, TypeError) as error:
                    LOG.warning('Could not save notification: %s', error)
                    LOG.info('Server: %s', self.feed.render_server_text(packet.get('data', [])))
            else:
                LOG.info('Server: %s', self.feed.render_server_text(packet.get('data', [])))
        elif command == 'Bounced' and self.connected and self.deathlink.enabled:
            self.death_notification(self.deathlink.receive(packet, self.name, self.adapter.death_link_dead()))
        elif command == 'InvalidPacket':
            raise ValueError('Server rejected a packet: ' + packet.get('text', 'unknown error'))

    async def poll(self, socket):
        if self.feed_ready:
            for toast in self.feed.drain():
                LOG.info('%s', ''.join(text for text, _ in toast.parts), extra={'item_parts': toast.parts})
                if self.notify:
                    self.notify(toast)
        if self.session is None or not self.connected or not self.inventory.synchronized:
            return
        await self.apply_death_preference(socket)
        controls = getattr(self, 'test_controls', None)
        if controls and controls.step():
            self.gate()
            return
        self.adapter.observe(self.session)
        if 'timed_effects' in self.adapter.capabilities:
            self.timed_effects.poll(self.adapter)
        if 'airhorn' in self.adapter.capabilities:
            self.airhorn.poll(self.adapter)
        if self.deathlink.enabled:
            state = self.adapter.poll_death_link()
            if state['local']:
                await self.send(socket, self.deathlink.local_death(self.name))
                self.death_notification(self.deathlink.toast('Sent', 'Your death was sent to linked players.'))
            if state['remote']:
                self.deathlink.confirmed_death()
                self.death_notification(self.deathlink.toast('Applied', 'A linked death reached your character.'))
            if state.get('unconfirmed'):
                self.deathlink.unconfirmed()
            if self.deathlink.pending:
                receipt = self.deathlink.pending['receipt']
                outcome = self.adapter.deliver_death_link(receipt, before_submit=self.deathlink.reserve)
                self.deathlink.resolve(receipt, outcome)
                if outcome == 'uncertain':
                    LOG.warning('DeathLink outcome uncertain; this death will not be retried.')
            else:
                self.adapter.clear_death_link_command()
        elif hasattr(self.adapter, 'clear_death_link_command'):
            self.adapter.clear_death_link_command()
        # Reservations survive process/client crashes. An uncertain effect is
        # held for adapter reconciliation, never replayed on an AP reconnect.
        # Check capacity per item: a full health-kit inventory must not prevent
        # an ammo reward from being delivered. Each item keeps its own receipt.
        index = next((i for i in self.session.queued_supplies
                      if self.adapter.can_deliver(self.session.data['received'][i]['item'])), None)
        if index is not None:
            receipt = self.session.reserve_supply(index)
            try:
                outcome = self.adapter.deliver(self.session.data['received'][index]['item'], receipt)
            except Exception:
                self.session.resolve_supply(index, 'uncertain')
                raise
            self.session.resolve_supply(index, outcome)
        now = time.monotonic()
        pending = {check for check in self.session.earned_checks - self.checked
                   if now - self.sent_at.get(check, -60) >= 15}
        if pending:
            await self.send(socket, {'cmd': 'LocationChecks', 'locations': sorted(pending)})
            self.sent_at.update({check: now for check in pending})
        if self.session.story_complete and self.session.earned_checks <= self.checked and not self.goal_sent:
            await self.send(socket, {'cmd': 'StatusUpdate', 'status': 30})
            self.goal_sent = True
        self.gate()

        after_poll = getattr(self.adapter, 'after_poll', None)
        if after_poll:
            after_poll()

    async def run_connection(self, socket):
        self.connected = False
        self.session = None
        self.seed = None
        self.inventory = Inventory()
        self.sent_at = {}
        self.goal_sent = False
        self.feed_ready = False
        self.configure_death_link(False, preserve_pending=True)
        self.gate()
        try:
            while True:
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
                else:
                    packets = json.loads(message)
                    if not isinstance(packets, list):
                        raise ValueError('Expected an Archipelago packet list')
                    for packet in packets:
                        await self.handle(socket, packet)
                await self.poll(socket)
        finally:
            self.connected = False
            controls = getattr(self, 'test_controls', None)
            if controls:
                controls.disconnected()
            self.airhorn.suspend()
            if 'timed_effects' in self.adapter.capabilities:
                self.adapter.set_timed_effects([0, 0])
            self.configure_death_link(False, preserve_pending=True)
            self.inventory.synchronized = False
            self.gate()

    async def connect(self, address):
        requested = server_uri(address)
        uri = (self.resolved_server[1] if self.resolved_server and self.resolved_server[0] == requested
               else requested)
        async with open_server(uri) as (socket, resolved):
            self.resolved_server = requested, resolved
            LOG.info('Server connection established%s.', ' with encryption' if resolved.startswith('wss://') else '')
            await self.run_connection(socket)
