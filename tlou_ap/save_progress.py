"""Read the supported save's serialized task progress without loading the game.

Both saved task copies must agree. This checks compatibility with the AP
progress guard; it does not establish which run created a save.
"""
import json
from pathlib import Path
import struct

from .catalog import MISSIONS
from .native.tasks import MOVIE_TASK, STORY_END, mission_difficulties, sid
from .native.run import progress_compatibility_error

PROFILE = json.loads(Path(__file__).with_name('native').joinpath('save_tasks_1130.json').read_text())
NODES = tuple({**n, 'sid': int(n['sid'], 16), 'type_sid': int(n['type_sid'], 16)} for n in PROFILE['nodes'])
STRIDE = 72
MARKER = bytes.fromhex('01010101000000000600000004000000')
POSITIONS = {n['sid']: i for i, n in enumerate(NODES)}
BOUNDS = [POSITIONS[int(m['task_sid'], 16)] for m in MISSIONS] + [POSITIONS[STORY_END]]
REQUIRED = tuple({NODES[start]['sid'], *(n['sid'] for n in NODES[start + 1:end]
                 if n['script'] and n['type_sid'] not in (MOVIE_TASK, sid('TaskManagerCinematic')))}
                 for start, end in zip(BOUNDS, BOUNDS[1:]))


def saved_difficulties(payload):
    if len(payload) < 16 or struct.unpack_from('<I', payload)[0] != PROFILE['save_magic']:
        raise ValueError('Unsupported save format; progress could not be checked')
    if len(NODES) != 602 or len(POSITIONS) != 602 or BOUNDS != sorted(set(BOUNDS)):
        raise ValueError('Unsupported task profile')
    needle = struct.pack('<Q', NODES[0]['sid'])
    tables = []
    position = payload.find(needle)
    candidates = 0
    while position >= 0:
        candidates += 1
        if candidates > 64:
            raise ValueError('Unexpected number of task tables')
        if payload[position + 32:position + 48] == MARKER:
            if position + STRIDE * len(NODES) > len(payload):
                raise ValueError('Truncated saved task table')
            difficulties = []
            for i, node in enumerate(NODES):
                offset = position + STRIDE * i
                if (struct.unpack_from('<Q', payload, offset)[0] != node['sid'] or
                        payload[offset + 32:offset + 48] != MARKER):
                    raise ValueError('Unrecognized saved task layout')
                difficulty = struct.unpack_from('<i', payload, offset + 24)[0]
                if not -1 <= difficulty <= 6:
                    raise ValueError('Unrecognized saved task difficulty')
                difficulties.append(difficulty)
            tables.append(tuple(difficulties))
        position = payload.find(needle, position + 1)
    if len(tables) != 2:
        raise ValueError('Expected two complete saved task tables')
    if tables[0] != tables[1]:
        raise ValueError('Saved task copies differ; progress cannot be classified reliably')
    return tuple(mission_difficulties([{**n, 'difficulty': d} for n, d in zip(NODES, tables[0])]))


def compatibility_error(ledger, difficulties):
    return progress_compatibility_error(ledger, REQUIRED, list(difficulties))
