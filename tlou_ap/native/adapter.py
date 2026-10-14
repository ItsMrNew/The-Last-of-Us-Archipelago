"""Native adapter for the fingerprinted Windows 1.1.3.0 AVX2 build."""
import hashlib
import ctypes as c
from ctypes import wintypes as w
import logging
import json
from pathlib import Path
import struct
import time

from .bridge import Bridge, validate_gate_build, PLAYER_DEATH_EVENT
from .run import RunLedger
from .progress import LiveTaskProgress
from .deathlink import NativeDeathLink
from .airhorn import NativeAirhorn
from .tasks import MOVIE_TASK, STORY_END, read_task_nodes, mission_difficulties, sid
from ..catalog import PROGRESSIVE_TOOLS, DELIVERABLES, ITEM_IDS, MISSIONS, SUPPLIES, RESOURCE_SUPPLIES

LOG = logging.getLogger('tlou-ap')
SUPPLY_COMMANDS = {ITEM_IDS[name]: kind for name, kind in zip(SUPPLIES, (4, 2, 5, 11, 12, 13))}


def resource_wait_reason(name, status):
    indexes = range(6) if name == 'Crafting Cache' else (6,) if name == 'Workbench Parts' else (7,)
    counts, caps = status.get('resources', []), status.get('resource_max', [])
    if len(counts) != 8 or len(caps) != 8 or any(
            caps[i] != (12 if i < 6 else 9999) or not 0 <= counts[i] <= caps[i] for i in indexes):
        return 'Waiting for a supported resource inventory'
    return 'Resource inventory full' if all(counts[i] == caps[i] for i in indexes) else ''



TASK_PROFILE = json.loads(Path(__file__).with_name('build_1130.json').read_text())
AMMO_TYPES = {f'{sid("t1x-ammo-" + name):016x}': name for name in
              ('9mm', 'revolver', 'rifle', 'shotgun', 'pistol-shotgun', 'pistol-uber',
               'arrow', 'assault-rifle', 'flamethrower')}


def ammo_supply_wait_reason(status):
    """Use loaded + reserve ammo for the drawn weapon, never magazine size."""
    if not status.get('weapon') or status.get('ammo_sid') not in AMMO_TYPES:
        return 'Draw a weapon with half its total ammo capacity or less'
    weapon = next((w for w in status['weapons'] if w['weapon'] == status['weapon']
                   and w['ammo_sid'] == status['ammo_sid']), None)
    if (weapon is None or not 1 <= weapon['maximum'] <= 11000
            or not 0 <= weapon['ammo'] <= weapon['maximum']
            or status.get('ammo') != weapon['ammo']):
        return 'Waiting for valid ammo capacity on the drawn weapon'
    if weapon['ammo'] * 2 > weapon['maximum']:
        return (f"Drawn weapon ammo {weapon['ammo']}/{weapon['maximum']}; "
                'waiting for 50% or less (loaded + reserve)')
    return ''


def required_tasks(memory):
    nodes = read_task_nodes(memory, TASK_PROFILE)
    positions = {node['sid']: i for i, node in enumerate(nodes)}
    bounds = [positions[int(m['task_sid'], 16)] for m in MISSIONS] + [positions[STORY_END]]
    if len(positions) != 602 or bounds != sorted(set(bounds)):
        raise ValueError('Unexpected task definitions')
    # Cinematics can complete through a separate native path. The aggregate
    # native check still includes them; live hook evidence covers gameplay.
    return [{nodes[start]['sid'], *(node['sid'] for node in nodes[start + 1:end]
              if node['script'] and node['type_sid'] not in (MOVIE_TASK, sid('TaskManagerCinematic')))}
            for start, end in zip(bounds, bounds[1:])]


def receipt_id(receipt):
    return int.from_bytes(hashlib.sha256(receipt.encode()).digest()[:8], 'little') or 1


class NativeAdapter:
    capabilities = frozenset({'mission_completion', 'collectible_events', 'chapter_gate',
                              'item_delivery', 'managed_run', 'death_link', 'airhorn', 'resources', 'timed_effects'})

    def __init__(self, pid, native_directory, run_path):
        if (Path(run_path).resolve().parent.parent / 'save-pack-active.json').exists():
            raise ValueError('A test save pack is active. Use the Offline Test Lab, or restore your original saves before connecting to Archipelago.')
        self.bridge = Bridge(pid, native_directory)
        try:
            validate_gate_build(self.bridge.manifest['build_id'])
        except ValueError:
            self.bridge.close()
            raise
        k = self.bridge.memory.kernel
        k.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
        k.CreateMutexW.restype = w.HANDLE
        k.ReleaseMutex.argtypes = [w.HANDLE]
        c.set_last_error(0)
        self.mutex = k.CreateMutexW(None, True, f'Local\\TLOUAP_Client_{pid}')
        if not self.mutex or c.get_last_error() == 183:
            if self.mutex:
                k.CloseHandle(self.mutex)
            self.bridge.close()
            raise ValueError('Another Archipelago client is already attached to this game')
        try:
            self.ledger = RunLedger(run_path, required_tasks(self.bridge.memory))
            self.run_id = self.ledger.data['run_id']
            self.bound = False
            self.next_attempt = {}
            self.last_status = None
            self.receipt_query = None
            self.compatibility_error = ''
            self.live_progress = LiveTaskProgress()
            self.pending_progress_error = ''
            self.bridge.attach()
            self.native_instance = self.bridge.instance_key()
            # One live run owns the bridge. Reconnecting the same run is supported.
            owner = int.from_bytes(hashlib.sha256(self.run_id.encode()).digest()[:4], 'little') or 1
            if self.bridge.shared.reserved not in (0, owner):
                raise ValueError('Another managed run owns this game process. Restart the game before connecting the selected run.')
            self.bridge.shared.reserved = owner
            self.deathlink = NativeDeathLink(self.bridge)
            self.airhorn = NativeAirhorn(self.bridge, self.native_instance)
            self.set_gate(None)
        except BaseException:
            k.ReleaseMutex(self.mutex)
            k.CloseHandle(self.mutex)
            self.bridge.close()
            raise

    def bind(self, identity, resume):
        self.ledger.bind(identity)
        self.bound = True
        if not self.ledger.data['started']:
            LOG.info('Connected. Start a NEW main-story game from Hometown to begin this run.')
        else:
            LOG.info('Resuming this managed run. Load a save made during this run.')

    def set_gate(self, session):
        self.bridge.heartbeat()
        self.bridge.shared.allowed = (sum(1 << i for i in range(len(MISSIONS)) if session.can_start(i))
                                      if session and not self.compatibility_error else 0)
        self.bridge.shared.mode = 2

    def set_player_death_handler(self, handler):
        self.player_death_handler = handler

    def cancel_trap_commands(self):
        self.airhorn.cancel_pending()

    def observe(self, session):
        if getattr(self, 'airhorn', None):
            self.airhorn.reap_cancelled()
        self.bridge.heartbeat()
        if not self.bridge.is_alive():
            raise ValueError('The game has closed. Relaunch it and reconnect to resume this run.')
        if self.bridge.shared.status != 1 or self.bridge.shared.error:
            raise RuntimeError(f'Native bridge error: {self.bridge.status()}')
        # Death cleanup must happen before another trap poll, even while the
        # checkpoint's task snapshot is temporarily unreadable. Leave ring
        # acknowledgement to normal observation; journal tokens make retries safe.
        handler = getattr(self, 'player_death_handler', None)
        death_events = self.bridge.events() if handler and self.bound else None
        if death_events is not None:
            for event in death_events:
                if event['type'] == PLAYER_DEATH_EVENT:
                    handler(f'{self.native_instance}:{event["sequence"]}')
        try:
            nodes = read_task_nodes(self.bridge.memory, TASK_PROFILE)
            difficulties = mission_difficulties(nodes)
        except (ValueError, OSError):
            # Keep unacknowledged events for a stable snapshot after loading.
            self.reconcile_deliveries(session)
            return
        # Reuse prefetched death events; later task events remain queued for the next poll.
        events = death_events if death_events is not None else self.bridge.events()
        def can_track(mission, pending):
            return mission in self.ledger.available_missions(session, difficulties, [*events, *pending])
        inferred = self.live_progress.observe(nodes, events, session, can_track) if self.bound else []
        error = self.ledger.incompatible_progress(difficulties, [*events, *inferred])
        if error != self.compatibility_error:
            self.compatibility_error = error
            LOG.warning('%s', error or 'Loaded progress is consistent with this managed run.')
        if error and error != self.pending_progress_error:
            # The hook publishes after the game writes its completion flag.
            # Keep the ring events for one poll before quarantining a mismatch.
            self.pending_progress_error = error
            self.reconcile_deliveries(session)
            return
        self.pending_progress_error = error
        if self.bound and not error:
            self.ledger.record_events([*events, *inferred], session, difficulties)
        if not error:
            for event in inferred:
                with self.ledger.path.with_suffix('.events.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({**event, 'native_instance': self.native_instance,
                                             'quarantined': False}) + '\n')
                LOG.info('Verified live task completion from game progress: %016x.', event['sid'])
            self.live_progress.accepted()
        for event in events:
            with self.ledger.path.with_suffix('.events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({**event, 'native_instance': self.native_instance,
                                         'quarantined': bool(error)}) + '\n')
            if event['type'] == 3:
                LOG.info('Locked: %s. Waiting for its chapter unlock and prior mission completion.',
                         MISSIONS[event['mission'] - 1]['name'])
            elif event['type'] == 4:
                # Clock holds also clear temporarily for load teardown and menus;
                # that event is not itself an Archipelago unlock.
                LOG.info('Gameplay hold cleared: %s.', MISSIONS[event['mission'] - 1]['name'])
            elif event['type'] == 10:
                self.deathlink.unconfirmed = True
                LOG.warning('DeathLink was submitted but the game did not confirm death. '
                            'This uncertain effect will not be repeated.')
            self.bridge.acknowledge(event['sequence'])
        if not error:
            self.ledger.confirm_native(difficulties, session)
            self.ledger.reconcile_checks(session)
        current = (len(session.data['missions']), len(session.data['collectibles']), len(session.unlocked))
        if current != self.last_status:
            LOG.info('Progress: %d/29 missions, %d collectibles, %d/12 chapters unlocked.', *current)
            self.last_status = current
        self.reconcile_deliveries(session)

    def reconcile_deliveries(self, session):
        if getattr(self, 'airhorn', None) and self.airhorn.command:
            return
        if self.deathlink.command:
            return  # Preserve the death mailbox reply until the protocol polls it.
        # Same-process retries use the DLL's receipt cache. After game restart,
        # an interrupted effect stays held because native receipt evidence died.
        if self.receipt_query:
            receipt, index, sequence = self.receipt_query
            result = self.bridge.command_result(sequence)
            if result is None:
                return
            self.receipt_query = None
            outcome = {1: 'applied', 2: 'not_applied', 5: 'not_applied'}.get(result, 'uncertain')
            previous = self.ledger.data['deliveries'].get(receipt, {})
            if not isinstance(previous, dict):
                previous = {}
            restoring = session.data['receipts'].get(str(index)) == 'applied'
            self.ledger.data['deliveries'][receipt] = {**previous, 'outcome': outcome, 'native_instance': self.native_instance}
            self.ledger.save()
            if not restoring:
                session.resolve_supply(int(index), outcome)
            # Waiting rewards are shown in the launcher's live status area.
            # Keep the session log for completed deliveries and recovery warnings.
            if outcome != 'not_applied' and not restoring:
                item_id = session.data['received'][int(index)]['item']
                item_name = next((name for name, code in ITEM_IDS.items() if code == item_id),
                                 f'Unknown item ({item_id})')
                LOG.info('Reward %s: %s.', item_name,
                         {'applied': 'Delivered', 'uncertain': 'Held for recovery'}[outcome])
        if self.reconcile_tools(session):
            return
        for index, state in list(session.data['receipts'].items()):
            if session.data['received'][int(index)]['item'] == ITEM_IDS[PROGRESSIVE_TOOLS]:
                continue
            if state in ('reserved', 'uncertain'):
                receipt = f'{session.path.stem}:{index}'
                entry = self.ledger.data['deliveries'].get(receipt)
                outcome = entry.get('outcome') if isinstance(entry, dict) else entry
                item = session.data['received'][int(index)]['item']
                if (outcome == 'pending' and entry['native_instance'] == self.native_instance
                        and not self.bridge.command_busy):
                    kind = entry.get('command_kind', 1 if item == ITEM_IDS['Ammo Supply'] else 2)
                    sequence = self.bridge.begin_command(101, kind, receipt_id(receipt))
                    self.receipt_query = (receipt, index, sequence)
                    return
                # A crash between session reservation and ledger submission
                # cannot have applied anything: the ledger is saved first.
                if entry is None:
                    outcome = 'not_applied'
                if outcome in ('applied', 'not_applied', 'retired'):
                    session.resolve_supply(int(index), 'applied' if outcome == 'retired' else outcome)

    def reconcile_tools(self, session):
        """Restore durable tool floors; replay can never increment them twice."""
        if not self.can_deliver(ITEM_IDS[PROGRESSIVE_TOOLS]):
            return False
        level = self.bridge.supplies().get('tool_level', -1)
        for index, state in list(session.data['receipts'].items()):
            if session.data['received'][int(index)]['item'] != ITEM_IDS[PROGRESSIVE_TOOLS]:
                continue
            receipt = f'{session.path.stem}:{index}'
            entry = self.ledger.data['deliveries'].get(receipt)
            if not entry:
                if state != 'applied':
                    session.resolve_supply(int(index), 'not_applied')
                continue
            if entry.get('outcome') == 'retired':
                continue
            target = entry.get('tool_target')
            if type(target) is not int or not 1 <= target <= 5:
                raise ValueError('Invalid persisted tool target; recovery required')
            if level >= target:
                if state != 'applied':
                    self.ledger.data['deliveries'][receipt] = {**entry, 'outcome': 'applied'}
                    self.ledger.save()
                    session.resolve_supply(int(index), 'applied')
                    LOG.info('Reward %s: Delivered.', PROGRESSIVE_TOOLS)
                continue
            self.submit_tool_target(receipt, target)
            return True
        return False

    def submit_tool_target(self, receipt, target):
        entry = self.ledger.data['deliveries'].get(receipt, {})
        self.ledger.data['deliveries'][receipt] = {**entry, 'outcome': 'pending',
            'native_instance': self.native_instance, 'command_kind': 7, 'tool_target': target}
        self.ledger.save()  # Record the absolute target before touching the game.
        sequence = self.bridge.begin_command(7, target | (self.bridge.shared.current << 8), receipt_id(receipt))
        self.receipt_query = (receipt, receipt.rsplit(':', 1)[1], sequence)
        self.next_attempt[ITEM_IDS[PROGRESSIVE_TOOLS]] = time.monotonic() + 5

    def retire_held(self, session):
        """User-selected conservative recovery: consume ambiguous gifts, never regrant."""
        if self.bridge.command_busy or self.receipt_query:
            raise ValueError('Wait for the pending game command to finish before retiring held rewards.')
        count = 0
        for index, state in list(session.data['receipts'].items()):
            if state not in ('reserved', 'uncertain'):
                continue
            receipt = f'{session.path.stem}:{index}'
            entry = self.ledger.data['deliveries'].get(receipt)
            if not isinstance(entry, dict):
                continue
            if entry['outcome'] == 'pending' and entry['native_instance'] == self.native_instance:
                continue  # A read-only cache query can still resolve this one.
            if entry['outcome'] not in ('pending', 'uncertain'):
                continue
            self.ledger.data['deliveries'][receipt] = {**entry, 'outcome': 'retired',
                'decision': 'User retired an ambiguous reward without granting it again.', 'time': time.time()}
            self.ledger.save()  # Persist the decision before repairing the session.
            session.resolve_supply(int(index), 'applied')
            count += 1
        LOG.info('Retired %d held rewards without granting additional items.', count)
        return count

    def after_poll(self):
        # Never block the network loop waiting for a loading/paused game thread.
        # Submit telemetry after delivery decisions, so it cannot starve rewards.
        if (not self.bridge.command_busy and self.receipt_query is None and self.deathlink.command is None
                and not self.airhorn.command):
            self.bridge.begin_command(100)

    def airhorn_status(self):
        return {'instance': self.native_instance, 'clock': self.bridge.shared.airhorn_clock_ms,
                'ready': bool(self.bridge.shared.airhorn_ready and self.ledger.data['started']
                              and not self.compatibility_error)}

    def airhorn_pulse(self, receipt, pending_instance, *, before_submit):
        return self.airhorn.pulse(receipt, pending_instance, before_submit=before_submit,
            can_submit=not self.receipt_query and not self.deathlink.command and
                       not self.compatibility_error and self.ledger.data['started'])

    def timed_effect_status(self):
        s = self.bridge.shared
        return {'instance': self.native_instance, 'clocks': list(s.effect_clock),
                'ready': self.airhorn_status()['ready'], 'supported': s.effect_supported}

    def set_timed_effects(self, remaining):
        s = self.bridge.shared
        s.effect_mask = 0
        if self.compatibility_error or not self.ledger.data['started']:
            return
        if len(remaining) != 2 or any(type(v) is not int or v < 0 for v in remaining):
            raise ValueError('Invalid timed effect durations')
        for i, duration in enumerate(remaining):
            s.effect_until[i] = s.effect_clock[i] + duration
        self.bridge.memory.kernel.GetTickCount64.restype = c.c_uint64
        s.effect_lease = self.bridge.memory.kernel.GetTickCount64()
        s.effect_mask = sum(1 << i for i, duration in enumerate(remaining) if duration)

    def configure_death_link(self, enabled):
        self.deathlink.configure(enabled)

    def death_link_dead(self):
        return self.bridge.shared.death_state in (1, 3)

    def poll_death_link(self):
        return self.deathlink.poll()

    def deliver_death_link(self, receipt, *, before_submit):
        if (not self.deathlink.command and
                (self.compatibility_error or not self.ledger.data['started'] or self.receipt_query
                 or (getattr(self, 'airhorn', None) and self.airhorn.command))):
            return 'not_applied'
        return self.deathlink.deliver(receipt, before_submit=before_submit)

    def clear_death_link_command(self):
        self.deathlink.clear_finished()

    def can_deliver(self, item):
        if getattr(self, 'airhorn', None) and self.airhorn.command:
            return False
        if (self.compatibility_error or not self.ledger.data['started'] or self.bridge.shared.pending or self.bridge.command_busy
                or self.receipt_query is not None or self.deathlink.command is not None
                or time.monotonic() < self.next_attempt.get(item, 0)):
            return False
        current = self.bridge.shared.current - 1
        # Sarah and 20 Years Later use temporary inventories. The native side
        # also holds Beyond the Wall's backpack task and inventory changes.
        if current <= 1 or not (self.bridge.shared.allowed & (1 << current)):
            return False
        status = self.bridge.supplies()
        if not status['player'] or not status.get('ready'):
            return False
        if item == ITEM_IDS['Health Kit']:
            return status['kit_max'] == 3 and 0 <= status['health_kits'] < 3
        if item == ITEM_IDS[PROGRESSIVE_TOOLS]:
            return status['shiv_max'] == 3 and 0 <= status.get('tool_level', -1) <= 5
        if item == ITEM_IDS['Shiv']:
            return status['shiv_max'] == 3 and 0 <= status['shivs'] < 3
        for name in RESOURCE_SUPPLIES:
            if item == ITEM_IDS[name]:
                return not resource_wait_reason(name, status)
        return item == ITEM_IDS['Ammo Supply'] and not ammo_supply_wait_reason(status)

    def delivery_context(self):
        """Read-only telemetry for the UI; never submit a game command here."""
        s = self.bridge.shared
        supply = self.bridge.supplies()
        if self.compatibility_error:
            reason = 'Save does not match this run'
        elif not self.ledger.data['started']:
            reason = 'Waiting for this managed run to start'
        elif s.blocked or (s.current and not s.allowed & (1 << (s.current - 1))):
            reason = 'Mission locked'
        else:
            reason = ''
        gameplay = ('Waiting for a living, controllable character' if s.death_state in (1, 3) else
                    'Waiting for a playable Prologue section (scripted scene / story finale)' if
                    s.current == 1 and getattr(s, 'prologue_stage', 0) == 2 else
                    'Waiting for stable gameplay (menu, cutscene, loading or scripted control)')
        death_reason = reason or ('' if s.death_state == 2 else gameplay)
        airhorn_reason = reason or ('' if s.airhorn_ready else gameplay)
        # Effects do not need Joel's backpack. Supplies still wait for an
        # inventory that persists beyond the opening chapters.
        supply_reason = reason or ('Waiting for a persistent inventory / backpack' if s.current <= 2 else
                                  gameplay if not supply['ready'] else '')
        reasons = {}
        for name in DELIVERABLES:
            detail = supply_reason
            if not detail and name == PROGRESSIVE_TOOLS:
                detail = ('Waiting for Joel' if supply['shiv_max'] != 3 else 'Waiting for valid tool-level data' if not 0 <= supply.get('tool_level', -1) <= 5 else '')
            if not detail and name == 'Shiv':
                detail = ('Waiting for Joel’s shiv inventory' if supply['shiv_max'] != 3
                          else 'Shiv inventory full (3/3)' if supply['shivs'] >= 3 else '')
            if not detail and name == 'Health Kit':
                detail = ('Waiting for a usable medkit inventory' if supply['kit_max'] != 3
                          else 'Medkit inventory full (3/3)' if supply['health_kits'] >= 3 else '')
            if not detail and name == 'Ammo Supply':
                detail = ammo_supply_wait_reason(supply)
            if not detail and name in RESOURCE_SUPPLIES:
                detail = resource_wait_reason(name, supply)
            reasons[ITEM_IDS[name]] = detail or 'Ready; waiting for the delivery channel'
        return {'reason': reason or (gameplay if not (s.airhorn_ready or s.death_state == 2) else ''),
                'death_reason': death_reason, 'airhorn_reason': airhorn_reason,
                'supplies': reasons, 'tool_level': supply.get('tool_level', -1), 'blocked': s.blocked, 'prologue_stage': getattr(s, 'prologue_stage', 0),
                'current': s.current - 1, 'playable': bool(s.airhorn_ready),
                'native_build': f'{self.bridge.manifest["build_id"]:016x}',
                'bridge_error': s.error, 'dropped_events': s.dropped}

    def deliver(self, item, receipt):
        if item == ITEM_IDS[PROGRESSIVE_TOOLS]:
            entry = self.ledger.data['deliveries'].get(receipt, {})
            if entry.get('outcome') in ('applied', 'retired'):
                return 'applied'
            level = self.bridge.supplies().get('tool_level', -1)
            if not 0 <= level <= 5:
                return 'not_applied'
            target = entry.get('tool_target', min(5, level + 1))
            if type(target) is not int or not 1 <= target <= 5:
                raise ValueError('Invalid persisted tool target')
            self.submit_tool_target(receipt, target)
            return 'uncertain'
        if item not in SUPPLY_COMMANDS:
            raise ValueError('Unknown native supply item')
        previous = self.ledger.data['deliveries'].get(receipt)
        if isinstance(previous, dict):
            previous = previous['outcome']
        if previous in ('applied', 'retired'):
            return 'applied'
        kind = SUPPLY_COMMANDS[item]
        self.ledger.data['deliveries'][receipt] = {'outcome': 'pending', 'native_instance': self.native_instance,
                                                 'command_kind': kind}
        self.ledger.save()
        self.bridge.begin_command(kind, 1 | (self.bridge.shared.current << 8), receipt_id(receipt))
        self.next_attempt[item] = time.monotonic() + 5
        # Resolve through the read-only native cache on a subsequent poll. The
        # durable pending entry survives a client crash at any point here.
        return 'uncertain'

    def close(self):
        # Keep enforcement installed while the run is disconnected. Restarting
        # the game removes the DLL and its hooks; reconnect restores the run.
        self.bridge.shared.effect_mask = 0
        self.configure_death_link(False)
        self.set_gate(None)
        self.bridge.memory.kernel.ReleaseMutex(self.mutex)
        self.bridge.memory.kernel.CloseHandle(self.mutex)
        self.bridge.close()
