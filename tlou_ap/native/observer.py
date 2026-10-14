"""Read-only observer for the fingerprinted 1.1.3.0 AVX2 executable.

Chapter entries are telemetry only. They are NOT completion evidence.
"""
import hashlib
import json
from pathlib import Path
import struct

from .memory import ProcessReader
from .tasks import mission_difficulties, read_task_nodes
from ..catalog import COLLECTIBLES

PROFILE = Path(__file__).with_name('build_1130.json')


class Observer:
    # This observer deliberately cannot be used as a playable client adapter.
    capabilities = frozenset({'collectible_profile_read', 'collectible_inventory_read'})

    def __init__(self, pid):
        self.memory = ProcessReader(pid)
        try:
            self.profile = json.loads(PROFILE.read_text(encoding='utf-8'))
            path = Path(self.memory.game['path'])
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != self.profile['sha256']:
                raise ValueError('Unsupported executable fingerprint; native access disabled')
            base = self.memory.game['base']
            for anchor in self.profile['anchors']:
                data = bytes.fromhex(anchor['bytes'])
                if self.memory.read(base + anchor['rva'], len(data)) != data:
                    raise ValueError('Live code differs from the researched build; native access disabled')
        except BaseException:
            self.memory.close()
            raise

    def snapshot(self):
        memory, profile = self.memory, self.profile
        base = memory.game['base']
        manager = memory.qword(base + profile['treasure_manager_pointer'])
        checkpoint = memory.qword(base + profile['chapter_checkpoint_pointer'])
        if not manager or not checkpoint:
            raise ValueError('Game progress is not loaded yet')
        first = memory.read(manager + profile['profile_flags'], 159 * 4)
        inventory_header = memory.read(manager + profile['inventory_count'], 16)
        inventory_count = struct.unpack_from('<I', inventory_header)[0]
        if inventory_count > 350:
            raise ValueError('Invalid collectible inventory count')
        inventory = memory.read(manager, inventory_count * 8) if inventory_count else b''
        count_bytes = memory.read(checkpoint + profile['chapter_count'], 4)
        count = struct.unpack('<I', count_bytes)[0]
        if count > 48:
            raise ValueError('Invalid chapter entry count')
        chapters = memory.read(checkpoint, count * 8) if count else b''
        if (memory.qword(base + profile['treasure_manager_pointer']) != manager
                or memory.qword(base + profile['chapter_checkpoint_pointer']) != checkpoint
                or memory.read(manager + profile['profile_flags'], 159 * 4) != first
                or memory.read(manager + profile['inventory_count'], 16) != inventory_header
                or (inventory_count and memory.read(manager, inventory_count * 8) != inventory)
                or memory.read(checkpoint + profile['chapter_count'], 4) != count_bytes):
            raise ValueError('Game progress changed during read; retry')
        flags = struct.unpack('<159I', first)
        if not set(flags) <= {0, 1}:
            raise ValueError('Invalid collectible flags')
        inventory_sids = [f'{sid:016x}' for sid in struct.unpack(f'<{inventory_count}Q', inventory)]
        by_sid = {entry['sid']: entry for entry in COLLECTIBLES}
        try:
            tasks = self.task_snapshot()
        except (ValueError, OSError) as error:
            tasks = {'status': 'unavailable', 'reason': str(error)}
        return {'build': profile['version'], 'mode': 'read_only',
                'profile_collectibles': [i for i, flag in enumerate(flags) if flag],
                'inventory_treasure_sids': inventory_sids,
                'inventory_collectibles': [by_sid[sid]['index'] for sid in inventory_sids if sid in by_sid],
                'last_treasure_sid': f'{struct.unpack_from("<Q", inventory_header, 8)[0]:016x}',
                'entered_chapter_title_sids': [f'{sid:016x}' for sid in struct.unpack(f'<{count}Q', chapters)],
                'mission_telemetry': tasks,
                'capabilities': {'collectible_profile_read': True, 'collectible_inventory_read': True,
                                 'mission_completion': False,
                                 'chapter_gate': False, 'item_delivery': False}}

    def task_snapshot(self):
        nodes = read_task_nodes(self.memory, self.profile)
        difficulties = mission_difficulties(nodes)
        return {'status': 'candidate_unvalidated', 'task_count': len(nodes),
                'mission_difficulties': difficulties,
                'completed_mission_candidates': [i for i, value in enumerate(difficulties) if value >= 0]}

    def close(self):
        self.memory.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
