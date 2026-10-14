"""Audit every stable collectible ID against the installed game and live evidence.

Read-only. Writes identifiers, counts and reference paths, never game assets.
Static references are not treated as proof of a live acquisition.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.catalog import COLLECTIBLES, MISSIONS, CHECKS, DATA
from tools.read_psarc import Archive


def audit(game, event_paths=()):
    archive = Archive(game / 'build/pc/main/bin.psarc', game / 'oo2core_9_win64.dll')
    binary = archive.read('dc1/treasures.bin')
    if hashlib.sha256(binary).hexdigest() != DATA['source_hashes']['treasures']:
        raise ValueError('Treasure metadata differs from the supported catalog')
    if len({x['sid'] for x in COLLECTIBLES}) != 140 or len({c.id for c in CHECKS}) != len(CHECKS):
        raise ValueError('Duplicate catalog identifiers')
    by_bytes = {struct.pack('<Q', int(e['sid'], 16)): e['index'] for e in COLLECTIBLES}
    pattern = re.compile(b'|'.join(re.escape(key) for key in by_bytes))
    references = defaultdict(list)
    for name, index in archive.names.items():
        if name == 'dc1/treasures.bin' or not name.startswith('dc1/'):
            continue
        if archive.entries[index].size > 64 * 1024 * 1024:
            continue
        for key in set(pattern.findall(archive.read(name))):
            references[by_bytes[key]].append(name)
    observations = defaultdict(list)
    for path in event_paths:
        for line in path.read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            if event.get('type') not in (2, 7) or event.get('quarantined'):
                continue
            observations[event['sid']].append({key: event.get(key) for key in
                ('type', 'flags', 'caller', 'native_instance', 'sequence')})
    automatic = {5, 6, 27, 72, 128}
    ellie = {65, 66, 67, 68, 69, 71, 73, 74, 78}
    rows = []
    for entry in COLLECTIBLES:
        i = entry['index']; offset = 0x470 + i * 240
        native_sid, = struct.unpack_from('<Q', binary, offset)
        native_mission, = struct.unpack_from('<Q', binary, offset + 48)
        expected_mission = int(MISSIONS[entry['mission']]['sid'], 16)
        if native_sid != int(entry['sid'], 16):
            raise ValueError(f'Native SID mismatch at index {i}')
        if native_mission != expected_mission and not (i == 128 and native_mission == 0):
            raise ValueError(f'Native mission mismatch at index {i}')
        evidence = observations[native_sid]
        kind = ('inspect_starting_inventory' if i in ellie else 'scripted_grant' if i in automatic
                else 'returned_variant' if i == 18 else 'optional_photo' if i == 79 else 'pickup')
        rows.append({**entry, 'metadata_verified': True, 'acquisition_to_test': kind,
                     'mission_exception': 'Pittsburgh opening script' if i == 128 else None,
                     'references': references[i], 'live_events': evidence,
                     'live_award_seen': any(e['flags'] & 1 for e in evidence)})
    return {'schema': 1, 'catalog_version': 1, 'native_metadata_sha256': hashlib.sha256(binary).hexdigest(),
            'counts': dict(Counter(row['category'] for row in rows)),
            'metadata_verified': len(rows), 'live_awards_seen': sum(row['live_award_seen'] for row in rows),
            'note': 'Reference and metadata validation do not prove every check is obtainable. '
                    'Live awards still require an acquisition during a managed campaign.', 'collectibles': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', type=Path)
    parser.add_argument('--events', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/collectible-audit.json')
    args = parser.parse_args()
    result = audit(args.game, args.events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    with args.output.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Index', 'Name', 'Mission', 'Category', 'Acquisition to test', 'Metadata verified',
                         'Live award seen', 'Native SID'])
        for row in result['collectibles']:
            writer.writerow([row['index'], row['name'], MISSIONS[row['mission']]['name'], row['category'],
                             row['acquisition_to_test'], True, row['live_award_seen'], row['sid']])
    print(json.dumps({key: value for key, value in result.items() if key != 'collectibles'}, indent=2))
