"""Native mission-completion telemetry, combined with managed-run live evidence.

Mirrors the task ranges and minimum difficulty used by the chapter collection.
An old save can contain completed tasks; this snapshot alone never earns checks.
"""
import struct

from ..catalog import MISSIONS


def sid(text):
    value = 0xcbf29ce484222325
    for byte in text.encode('ascii'):
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return value


MOVIE_TASK = sid('TaskManagerPlayMovie')
STORY_END = 0x91ab584921c66c2f


def mission_difficulties(nodes):
    positions = {node['sid']: i for i, node in enumerate(nodes)}
    if len(positions) != len(nodes):
        raise ValueError('Duplicate task identifiers')
    try:
        bounds = [positions[int(mission['task_sid'], 16)] for mission in MISSIONS]
        bounds.append(positions[STORY_END])
    except KeyError as error:
        raise ValueError('Main-story task boundaries unavailable') from error
    if bounds != sorted(set(bounds)):
        raise ValueError('Main-story task boundaries out of order')
    result = []
    for start, end in zip(bounds, bounds[1:]):
        # The chapter collection initializes from the first node, even if it
        # has no script; later nodes exclude movie tasks and absent scripts.
        included = [nodes[start], *(node for node in nodes[start + 1:end]
                                  if node['script'] and node['type_sid'] != MOVIE_TASK)]
        difficulty = min(node['difficulty'] for node in included)
        if any(not -1 <= node['difficulty'] <= 6 for node in included):
            raise ValueError('Unrecognized task difficulty')
        result.append(difficulty)
    return result


def read_task_nodes(memory, profile):
    """Read and recheck the fields used by the native chapter-completion rule."""
    cache = memory.game['base'] + profile['task_cache']
    header = memory.read(cache, 12)
    count, story = struct.unpack_from('<II', header)
    if count != profile['main_task_count'] or story != 0:
        raise ValueError('Main-story task cache not loaded')
    pointers = memory.read(cache + 0x30, count * 8)
    nodes, raw_nodes = [], []
    type_cache = {}
    for pointer in struct.unpack(f'<{count}Q', pointers):
        data = memory.read(pointer, 0x100)
        definition = struct.unpack_from('<Q', data, 0xf8)[0]
        if not definition:
            raise ValueError('Task definition unavailable')
        if definition not in type_cache:
            type_cache[definition] = memory.qword(definition + 8)
        nodes.append({'sid': struct.unpack_from('<Q', data, 0x28)[0],
                      'difficulty': struct.unpack_from('<h', data, 0x6a)[0],
                      'script': struct.unpack_from('<Q', data, 0xb8)[0],
                      'type_sid': type_cache[definition]})
        raw_nodes.append((pointer, data))
    # Re-read only fields used for interpretation; unrelated task state
    # can legitimately change while the game runs.
    for pointer, first in raw_nodes:
        again = memory.read(pointer, 0x100)
        if any(first[start:end] != again[start:end]
               for start, end in ((0x28, 0x30), (0x6a, 0x6c), (0xb8, 0xc0), (0xf8, 0x100))):
            raise ValueError('Task progress changed during read; retry')
    if memory.read(cache, 12) != header or memory.read(cache + 0x30, count * 8) != pointers:
        raise ValueError('Task cache changed during read; retry')
    return nodes
