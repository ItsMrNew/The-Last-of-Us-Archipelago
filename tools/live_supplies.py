"""Isolated supply validation mailbox. Requires the backed-up test save pack.

No AP connection or real run ledger. Write a request to control.json with a new
sequence and op: grant (kind 2/4/5/6 and receipt), hold (mission index), release,
or stop. Status and before/after evidence are written alongside it.
"""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.launcher import game_pid
from tlou_ap.native.bridge import Bridge
from tlou_ap.session import atomic_json

LAB_OWNER = 0x4c414231
ALL = (1 << 29) - 1


def main():
    if not (ROOT / '.state/save-pack-active.json').exists():
        raise SystemExit('Install the isolated test save pack first.')
    folder = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / '.research/supply-lab'
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / 'control.json', {'sequence': 0})
    bridge = Bridge(game_pid(), ROOT / 'dist/native')
    sequence = 0
    try:
        bridge.attach()
        if bridge.shared.reserved not in (0, LAB_OWNER):
            raise ValueError('The game belongs to another run; restart before testing.')
        bridge.shared.reserved = LAB_OWNER
        bridge.shared.death_enabled = 0
        bridge.shared.mode, bridge.shared.allowed = 2, ALL
        deadline = time.monotonic() + 1800
        with (folder / 'events.jsonl').open('a', encoding='utf-8') as log:
            while time.monotonic() < deadline and bridge.is_alive():
                bridge.heartbeat()
                bridge.command(100)
                status = {'time': time.time(), 'pid': bridge.pid, 'instance': bridge.instance_key(),
                          'bridge': bridge.status(), 'supplies': bridge.supplies(),
                          'airhorn': {'clock': bridge.shared.airhorn_clock_ms,
                                      'ready': bool(bridge.shared.airhorn_ready)}}
                atomic_json(folder / 'status.json', status)
                request = json.loads((folder / 'control.json').read_text())
                if request['sequence'] > sequence:
                    sequence = request['sequence']
                    op = request['op']
                    if op == 'stop':
                        break
                    if op == 'hold':
                        mission = int(request['mission'])
                        assert 0 <= mission < 29
                        bridge.shared.allowed = ALL & ~(1 << mission)
                    elif op == 'release':
                        bridge.shared.allowed = ALL
                    elif op == 'grant':
                        kind = request['kind']
                        assert kind in (2, 4, 5, 6)
                        result = bridge.command(kind, 1 | (bridge.shared.current << 8), request['receipt'])
                        bridge.command(100)
                        evidence = {'request': request, 'before': status,
                                    'result': result, 'after': bridge.supplies(),
                                    'cache': bridge.command(101, kind, request['receipt'])}
                        atomic_json(folder / f'grant-{sequence}.json', evidence)
                        print(json.dumps(evidence), flush=True)
                    elif op == 'snapshot':
                        atomic_json(folder / f'snapshot-{sequence}.json', status)
                for event in bridge.events():
                    log.write(json.dumps(event) + '\n')
                    bridge.acknowledge(event['sequence'])
                log.flush()
                time.sleep(.1)
    finally:
        if bridge.shared.reserved == LAB_OWNER:
            bridge.shared.mode = bridge.shared.death_enabled = 0
            bridge.shared.allowed = ALL
            time.sleep(.2)
            atomic_json(folder / 'shutdown.json', {**bridge.status(),
                        'pending': bridge.shared.pending, 'death_enabled': bridge.shared.death_enabled})
        bridge.close()


if __name__ == '__main__':
    main()
