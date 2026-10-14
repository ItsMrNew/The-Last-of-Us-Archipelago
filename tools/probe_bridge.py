"""Attach the native bridge, log events, and restore hooks on exit."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.native.bridge import Bridge

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pid', type=int, required=True)
parser.add_argument('--seconds', type=int, default=60)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
bridge = Bridge(args.pid, ROOT / 'dist/native')
try:
    bridge.attach()
    print(json.dumps(bridge.status()), flush=True)
    with args.output.open('a', encoding='utf-8') as stream:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            for event in bridge.events():
                stream.write(json.dumps(event) + '\n')
                stream.flush()
                bridge.acknowledge(event['sequence'])
                print(json.dumps(event), flush=True)
            time.sleep(.1)
    print(json.dumps(bridge.status()), flush=True)
finally:
    if bridge.shared.status == 1:
        bridge.detach()
    print('Final:', bridge.status(), flush=True)
    bridge.close()
