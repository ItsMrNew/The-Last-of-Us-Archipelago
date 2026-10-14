"""Local live-validation console. Commands are read from a workspace JSON file."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.native.bridge import Bridge
from tlou_ap.session import atomic_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pid', type=int, required=True)
args = parser.parse_args()
control = ROOT / '.research/live-control.json'
status = ROOT / '.research/live-status.json'
bridge = Bridge(args.pid, ROOT / 'dist/native')
sequence = None
try:
    bridge.attach()
    print('Native bridge active', flush=True)
    with (ROOT / '.research/live-events.jsonl').open('a', encoding='utf-8') as stream:
        while True:
            bridge.heartbeat()
            command = json.loads(control.read_text()) if control.exists() else {'sequence': 0, 'op': 'observe'}
            if command['sequence'] != sequence:
                sequence = command['sequence']
                if command['op'] == 'detach':
                    break
                if command['op'] == 'gate':
                    bridge.shared.allowed = command['mask']
                    bridge.shared.mode = 1
                if command['op'] == 'release':
                    bridge.shared.mode = 0
                if command['op'] == 'supply':
                    result = bridge.command(command['type'], command['quantity'], command['receipt'])
                    print('Delivery result:', result, flush=True)
                print('Command:', command, flush=True)
            bridge.command(100)
            current = {'time': time.time(), 'sequence': sequence,
                       'bridge': bridge.status(), 'supplies': bridge.supplies()}
            atomic_json(status, current)
            for event in bridge.events():
                stream.write(json.dumps(event) + '\n'); stream.flush()
                print('Event:', json.dumps(event), flush=True)
                bridge.acknowledge(event['sequence'])
            time.sleep(.25)
finally:
    if bridge.shared.status == 1:
        bridge.detach()
    print('Final:', bridge.status(), flush=True)
    bridge.close()
