"""Derive identifiers and short labels from an installed game (no game assets).

The table layouts are verified against 1.1.3.0. Output is development metadata,
not proof that every candidate acquisition is available in every playthrough.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from read_psarc import Archive


def qword(data, offset):
    return struct.unpack_from('<Q', data, offset)[0]


def localization(data):
    count = struct.unpack_from('<I', data)[0]
    base = 4 + count * 16
    result = {}
    for i in range(count):
        key, offset = struct.unpack_from('<QQ', data, 4 + i * 16)
        start = base + offset
        result[key] = data[start:data.index(0, start)].decode('utf-8').strip()
    return result


def build(root):
    dll = root / 'oo2core_9_win64.dll'
    binary = Archive(root / 'build/pc/main/bin.psarc', dll)
    core = Archive(root / 'build/pc/main/core.psarc', dll)
    text = localization(core.read('text2/eng.common'))
    chapters = binary.read('dc1/chapters.bin')
    treasures = binary.read('dc1/treasures.bin')
    if qword(chapters, 0x78) != 12 or qword(chapters, 0x2a8) != 30 or qword(treasures, 0x458) != 159:
        raise ValueError('Unrecognized catalog layout; review before updating')
    areas = []
    for i in range(12):
        offset = 0x90 + i * 24
        areas.append({'index': i, 'name': text[qword(chapters, offset + 8)],
                      'sid': f'{qword(chapters, offset):016x}'})
    area_indexes = {entry['sid']: entry['index'] for entry in areas}
    missions = []
    for i in range(29):  # Entry 29 is COMPLETE, not a playable mission.
        offset = 0x2c0 + i * 104
        missions.append({'index': i, 'name': text[qword(chapters, offset + 8)],
                         'sid': f'{qword(chapters, offset):016x}',
                         'title_sid': f'{qword(chapters, offset + 8):016x}',
                         'task_sid': f'{qword(chapters, offset + 24):016x}',
                         'chapter': area_indexes[f'{qword(chapters, offset + 48):016x}']})
    mission_indexes = {entry['sid']: entry['index'] for entry in missions}
    collectibles = []
    for i in range(140):  # Tools and Left Behind remain out of the check pool.
        offset = 0x470 + i * 240
        key = f'{qword(treasures, offset + 48):016x}'
        # Force Carrier is awarded at Pittsburgh's opening, with no chapter ID
        # in the data. Keep this explicit exception visible for live validation.
        mission = 13 if i == 128 else mission_indexes[key]
        title = text[qword(treasures, offset + 8)]
        if i == 18:
            title += ' (Returned)'
        if i == 78:
            title += ' (Ellie Inventory)'
        category = ('artifact' if i < 84 else 'pendant' if i < 114
                    else 'manual' if i < 126 else 'comic')
        collectibles.append({'index': i, 'name': title, 'mission': mission,
                             'category': category, 'sid': f'{qword(treasures, offset):016x}'})
    return {'schema': 1, 'source_build': '1.1.3.0',
            'source_hashes': {'chapters': hashlib.sha256(chapters).hexdigest(),
                              'treasures': hashlib.sha256(treasures).hexdigest()},
            'chapters': areas, 'missions': missions, 'collectibles': collectibles}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', type=Path)
    parser.add_argument('--output', type=Path, default=Path('tlou_ap/data/catalog.json'))
    args = parser.parse_args()
    result = build(args.game)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Wrote 12 chapters, 29 missions and 140 candidate collectible entries')
