"""Fingerprint-checked Windows loader and shared-memory transport for our DLL."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import mmap
from pathlib import Path
import struct
import time

from .memory import ProcessReader
from .tasks import STORY_END
from ..catalog import MISSIONS

MAGIC = 0x3150474449524241
EVENTS, ROUTES = 512, 640
# Event 11 is Airhorn pulse telemetry; 12 is confirmed local death cleanup.
PLAYER_DEATH_EVENT = 12

# Live testing showed this build could complete tasks while their starts were
# deferred, then crashed during a Drafting Notice pickup. Quarantine its gate;
# a zero native error code or a block event does not establish safe enforcement.
UNSAFE_GATE_BUILDS = {0x0ff9de8113ded92c}
UNSAFE_HOOK_BUILDS = {0xd03429926f61a01e}
# Alpha testing on the exact executable: menu access, Continue, checkpoint
# reload, save switching, natural Slums entry and post-release pickups passed.
# Alpha 8 retains that gate; a real AP unlock, locked menu/load access and
# queued DeathLink/checkpoint recovery also passed on its exact build.
# Alpha 11 keeps the gate and adds supply commands: the exact build passed
# held gameplay clocks, working pause/Load Game, and release preserving pause.
# This is an alpha admission list, not full campaign certification.
# Alpha 12 retains the gate and passed paused/menu/locked clock tests on its
# exact binary. Airhorn encounter coverage is documented separately.
# Alpha 18 passed the same clock/menu/release checks in Sarah's study, plus
# queued horn delivery/cinematic suspension and one DeathLink/checkpoint reload.
# Alpha 20 passed clock/menu/release checks at Joel's alley checkpoint, one
# scripted bite death, manual restart exclusion and incoming-death no-echo.
# Alpha31 retains the alpha30 gate and adds isolated local-test commands;
# the native regression harness covers both the existing gate and new commands.
# Alpha34 changes only the ammo eligibility guard; existing gate regressions
# pass. Ammo threshold live verification remains pending, not implied here.
VALIDATED_ENGINE_GATES = {0x96b4d08a1aa9aec5, 0xc40461d60666c46a, 0x616c0b7c5e8cf421, 0x99d6c0864e316360, 0xee143b9318f7dada,
                          0xd058868d7041f63b, 0xf818afd2465a624d, 0xe80002c9e90a1217, 0x7077cec8ac0ee9cc, 0x82ac26ded4f01a85,
                          # Alpha40: exact-binary startup, save load, paused and
                          # unpaused lock, menu access, unlock preserving pause,
                          # checkpoint reload and supply guards passed in game.
                          # Remaining feature acceptance is in validation_alpha40.md.
                          0xcb7988e78641366d,
                          # Scoped sway hotfix: native regressions and live
                          # controller scope/unscoped switching and expiry passed.
                          0x6e6140cbbafa3886}


def validate_gate_build(build_id, *, experimental=False):
    if build_id in UNSAFE_HOOK_BUILDS:
        raise ValueError('This preview aiming hook crashed during loading. Use the corrected register-preserving build.')
    if build_id == 0x6c8f1b0e5a6d256c:
        raise ValueError('This prototype stalled Continue while its gameplay clocks were held during loading. '
                         'Use the replacement scene-ready gameplay-clock build.')
    if build_id == 0xc2af8c72f3e532ea:
        raise ValueError('This prototype froze both gameplay and menu controls during live testing. '
                         'Use the replacement gameplay-clock build.')
    if build_id in UNSAFE_GATE_BUILDS:
        raise ValueError('Mission locking is disabled for this native build: the live Slums test '
                         'allowed progression during a hold and crashed during a collectible pickup. '
                         'A replacement gate must be validated before continuing an Archipelago run.')
    if not experimental and build_id not in VALIDATED_ENGINE_GATES:
        raise ValueError('This replacement mission gate is awaiting live validation. Use the isolated Offline Test Lab.')


class Route(c.Structure):
    _fields_ = [('sid', c.c_uint64), ('mission', c.c_int32), ('reserved', c.c_uint32)]


class Event(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ('sequence', 'ticks', 'sid', 'extra')] + [
        (name, c.c_uint32) for name in ('type', 'flags', 'caller', 'mission')]


class WeaponSupply(c.Structure):
    _fields_ = [('weapon', c.c_uint64), ('ammo_sid', c.c_uint64)] + [
        (name, c.c_int32) for name in ('ammo', 'maximum', 'clip', 'reserved')]


class Shared(c.Structure):
    _fields_ = [('magic', c.c_uint64), ('version', c.c_uint32), ('size', c.c_uint32),
                ('status', c.c_int32), ('error', c.c_int32),
                ('image_base', c.c_uint64), ('build_id', c.c_uint64),
                ('tick', c.c_int64), ('heartbeat', c.c_int64)] + [
        (name, c.c_int32) for name in ('mode', 'allowed', 'blocked', 'current',
            'write', 'ack', 'dropped', 'pending', 'command_seq', 'command_type',
            'command_arg', 'reply_seq', 'reply_status', 'detach')] + [
        ('command_receipt', c.c_uint64), ('route_count', c.c_uint32), ('reserved', c.c_uint32),
        ('reserved64', c.c_uint64 * 4), ('routes', Route * ROUTES), ('events', Event * EVENTS)] + [
        (name, c.c_int32) for name in ('death_enabled', 'death_state', 'death_local', 'death_remote',
            'supply_revision', 'shivs', 'shiv_max', 'kit_max', 'weapon_count', 'supply_ready')] + [
        ('weapons', WeaponSupply * 9), ('airhorn_clock_ms', c.c_int64),
        ('airhorn_ready', c.c_int32), ('prologue_stage', c.c_uint32),
        ('resources', c.c_int32 * 8), ('resource_max', c.c_int32 * 8),
        ('effect_clock', c.c_int64 * 2), ('effect_until', c.c_int64 * 2), ('effect_lease', c.c_int64),
        ('effect_mask', c.c_int32), ('effect_supported', c.c_int32)]


assert c.sizeof(Shared) == 35432 and Shared.routes.offset == 160 and Shared.events.offset == 10400


def routes_from_game(memory):
    cache = memory.game['base'] + 0x47fe910
    if struct.unpack('<II', memory.read(cache, 8)) != (602, 0):
        raise ValueError('Load the main story before attaching the bridge')
    pointers = struct.unpack('<602Q', memory.read(cache + 0x30, 602 * 8))
    sids = [memory.qword(pointer + 0x28) for pointer in pointers]
    positions = {sid: i for i, sid in enumerate(sids)}
    bounds = [positions[int(m['task_sid'], 16)] for m in MISSIONS] + [positions[STORY_END]]
    if len(positions) != 602 or bounds != sorted(set(bounds)) or bounds[0] != 0 or bounds[-1] != 601:
        raise ValueError('Unexpected main-story task layout')
    result = [(sid, mission) for mission, (start, end) in enumerate(zip(bounds, bounds[1:]))
              for sid in sids[start:end]]
    result.append((STORY_END, 28))
    return result


class Bridge:
    def __init__(self, pid, directory):
        self.pid, self.directory = pid, Path(directory).resolve()
        self.memory = ProcessReader(pid)
        self.mapping = self.shared = None
        try:
            self.manifest = json.loads((self.directory / 'manifest.json').read_text())
            self.dll = self.directory / self.manifest['dll']
            if self.dll.parent != self.directory:
                raise ValueError('Invalid native DLL path')
            for path, expected in ((Path(self.memory.game['path']), self.manifest['game_sha256']),
                                   (self.dll, self.manifest['dll_sha256'])):
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError(f'Fingerprint mismatch: {path.name}')
            self.mapping = mmap.mmap(-1, c.sizeof(Shared), tagname=f'Local\\TLOUAP_v2_{pid}')
            self.shared = Shared.from_buffer(self.mapping)
        except BaseException:
            self.close()
            raise

    def attach(self):
        if self.manifest['build_id'] in UNSAFE_HOOK_BUILDS:
            validate_gate_build(self.manifest['build_id'], experimental=True)
        s = self.shared
        if s.magic:
            if s.magic != MAGIC or s.version != 5 or s.size != c.sizeof(Shared):
                raise ValueError('An incompatible bridge is already attached; restart the game')
            if s.status == 1:
                if s.build_id != self.manifest['build_id']:
                    raise ValueError('A different bridge version is active; detach it first')
                return
            if s.status not in (3, -1):
                raise ValueError('Bridge initialization is already in progress')
        base = self.memory.game['base']
        for anchor in self.manifest['anchors']:
            data = bytes.fromhex(anchor['bytes'])
            if self.memory.read(base + anchor['rva'], len(data)) != data:
                raise ValueError('Hook target has been modified; restart the game without conflicting mods')
        routes = routes_from_game(self.memory)
        c.memset(c.addressof(s), 0, c.sizeof(s))
        s.magic, s.version, s.size = MAGIC, 5, c.sizeof(s)
        s.build_id = self.manifest['build_id']
        s.route_count = len(routes)
        for i, (sid, mission) in enumerate(routes):
            s.routes[i].sid, s.routes[i].mission = sid, mission
        self._inject()
        deadline = time.monotonic() + 10
        while s.status == 0 and time.monotonic() < deadline:
            time.sleep(.05)
        if s.status != 1:
            raise RuntimeError(f'Native bridge failed: status={s.status}, error={s.error}')

    def _inject(self):
        k = self.memory.kernel
        k.VirtualAllocEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, w.DWORD]
        k.VirtualAllocEx.restype = c.c_void_p
        k.VirtualFreeEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD]
        k.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        k.CreateRemoteThread.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, c.c_void_p,
                                        c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
        k.CreateRemoteThread.restype = w.HANDLE
        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.GetModuleHandleW.argtypes = [w.LPCWSTR]
        k.GetModuleHandleW.restype = w.HMODULE
        k.GetProcAddress.argtypes = [w.HMODULE, c.c_char_p]
        k.GetProcAddress.restype = c.c_void_p
        k.GetModuleHandleExW.argtypes = [w.DWORD, c.c_void_p, c.POINTER(w.HMODULE)]
        k.GetModuleFileNameW.argtypes = [w.HMODULE, w.LPWSTR, w.DWORD]
        # Find the actual module that owns LoadLibraryW, including API forwarding.
        address = k.GetProcAddress(k.GetModuleHandleW('kernel32.dll'), b'LoadLibraryW')
        owner = w.HMODULE()
        if not address or not k.GetModuleHandleExW(6, address, c.byref(owner)):
            raise c.WinError(c.get_last_error())
        owner_path = c.create_unicode_buffer(1024)
        if not k.GetModuleFileNameW(owner, owner_path, len(owner_path)):
            raise c.WinError(c.get_last_error())
        owner_name = Path(owner_path.value).name.lower()
        remote = next(m for m in self.memory.modules if m['name'].lower() == owner_name)
        start = remote['base'] + address - owner.value
        existing = next((m for m in self.memory.modules if m['name'].lower() == self.dll.name.lower()), None)
        handle = k.OpenProcess(0x043a, False, self.pid)
        if not handle:
            raise c.WinError(c.get_last_error())
        allocation = thread = None
        finished = False
        try:
            if existing:
                thread = k.CreateRemoteThread(handle, None, 0,
                    existing['base'] + self.manifest['restart_rva'], None, 0, None)
                if not thread:
                    raise c.WinError(c.get_last_error())
                return  # Worker stays resident; attach() waits for its status.
            path = (str(self.dll) + '\0').encode('utf-16-le')
            allocation = k.VirtualAllocEx(handle, None, len(path), 0x3000, 0x04)
            actual = c.c_size_t()
            if not allocation or not k.WriteProcessMemory(handle, allocation, path, len(path), c.byref(actual)):
                raise c.WinError(c.get_last_error())
            if actual.value != len(path):
                raise OSError('Incomplete DLL path write')
            thread = k.CreateRemoteThread(handle, None, 0, start, allocation, 0, None)
            if not thread:
                raise c.WinError(c.get_last_error())
            finished = k.WaitForSingleObject(thread, 10000) == 0
            if not finished:
                raise TimeoutError('DLL loader did not finish; path allocation retained until game exits')
        finally:
            if allocation and (finished or not thread):
                k.VirtualFreeEx(handle, allocation, 0, 0x8000)
            if thread:
                k.CloseHandle(thread)
            k.CloseHandle(handle)

    def events(self):
        s = self.shared
        if s.dropped:
            raise RuntimeError('Native event queue overflowed; run state needs recovery')
        result = []
        for index in range(s.ack, s.write):
            event = Event.from_buffer_copy(s.events[index % EVENTS])
            if event.sequence != index + 1:
                raise RuntimeError('Native event sequence mismatch')
            result.append({name: getattr(event, name) for name, _ in Event._fields_})
        return result

    def acknowledge(self, sequence):
        if not self.shared.ack <= sequence <= self.shared.write:
            raise ValueError('Invalid event acknowledgement')
        self.shared.ack = sequence

    def status(self):
        return {name: getattr(self.shared, name) for name in
                ('status', 'error', 'tick', 'mode', 'allowed', 'blocked', 'current', 'write', 'ack', 'dropped')}

    def heartbeat(self):
        self.memory.kernel.GetTickCount64.restype = c.c_uint64
        self.shared.heartbeat = self.memory.kernel.GetTickCount64()

    def instance_key(self):
        k = self.memory.kernel
        k.GetProcessTimes.argtypes = [w.HANDLE, *(c.POINTER(w.FILETIME) for _ in range(4))]
        times = [w.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(self.memory.handle, *(c.byref(value) for value in times)):
            raise c.WinError(c.get_last_error())
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return f'{self.pid}:{created}:{self.manifest["build_id"]:016x}'

    def command(self, kind, quantity=0, receipt=0, timeout=3):
        sequence = self.begin_command(kind, quantity, receipt)
        deadline = time.monotonic() + timeout
        while self.command_result(sequence) is None and time.monotonic() < deadline:
            self.heartbeat()
            time.sleep(.01)
        result = self.command_result(sequence)
        if result is None:
            raise TimeoutError('Game thread did not acknowledge the command; outcome uncertain')
        return result

    @property
    def command_busy(self):
        return self.shared.command_seq != self.shared.reply_seq

    def begin_command(self, kind, quantity=0, receipt=0):
        if self.command_busy:
            raise RuntimeError('Previous native command has not completed')
        s = self.shared
        s.command_type, s.command_arg, s.command_receipt = kind, quantity, receipt
        s.command_seq = (s.command_seq + 1) & 0x7fffffff
        return s.command_seq

    def command_result(self, sequence):
        if self.shared.command_seq != sequence:
            raise RuntimeError('Native command reply was overwritten')
        return self.shared.reply_status if self.shared.reply_seq == sequence else None

    def is_alive(self):
        k = self.memory.kernel
        k.GetExitCodeProcess.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
        code = w.DWORD()
        return bool(k.GetExitCodeProcess(self.memory.handle, c.byref(code)) and code.value == 259)

    def supplies(self):
        def signed(value):
            return c.c_int32(value & 0xffffffff).value
        for _ in range(3):
            revision = self.shared.supply_revision
            if revision & 1:
                continue
            snapshot = Shared.from_buffer_copy(self.shared)
            if revision != self.shared.supply_revision:
                continue
            return {'player': snapshot.reserved64[0], 'weapon': snapshot.reserved64[1],
                    'health_kits': signed(snapshot.reserved64[2]),
                    'ammo': signed(snapshot.reserved64[2] >> 32),
                    'ammo_sid': f'{snapshot.reserved64[3]:016x}',
                    'resources': list(snapshot.resources), 'resource_max': list(snapshot.resource_max),
                    'tool_level': snapshot.weapons[0].reserved,
                    'shivs': snapshot.shivs, 'shiv_max': snapshot.shiv_max,
                    'kit_max': snapshot.kit_max, 'ready': bool(snapshot.supply_ready),
                    'weapons': [{'weapon': w.weapon, 'ammo_sid': f'{w.ammo_sid:016x}',
                                 'ammo': w.ammo, 'maximum': w.maximum, 'clip': w.clip}
                                for w in snapshot.weapons[:max(0, min(9, snapshot.weapon_count))]]}
        return {'player': 0, 'weapon': 0, 'health_kits': -1, 'ammo': -1,
                'ammo_sid': '0000000000000000', 'shivs': -1, 'shiv_max': -1,
                'resources': [-1] * 8, 'resource_max': [-1] * 8,
                'kit_max': -1, 'ready': False, 'tool_level': -1, 'weapons': []}

    def detach(self):
        self.shared.detach = 1
        deadline = time.monotonic() + 5
        while self.shared.status == 1 and time.monotonic() < deadline:
            time.sleep(.05)
        if self.shared.status != 3:
            raise RuntimeError('Native hook detach did not complete')

    def close(self):
        self.shared = None
        mapping, self.mapping = self.mapping, None
        try:
            if mapping is not None:
                try:
                    mapping.close()
                except BufferError:
                    # A traceback/caller still owns a ctypes view. mmap remains
                    # owned by that view and closes when the final view dies.
                    pass
        finally:
            self.memory.close()
