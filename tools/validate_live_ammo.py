"""Wait for a drawn firearm, then send exactly one three-round test reward."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.session import atomic_json

control = ROOT / '.research/live-control.json'
status = ROOT / '.research/live-status.json'
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    data = json.loads(status.read_text())
    if data['supplies']['weapon'] and data['supplies']['ammo'] >= 0:
        sequence = json.loads(control.read_text())['sequence'] + 1
        atomic_json(ROOT / '.research/ammo-before.json', data)
        atomic_json(control, {'sequence': sequence, 'op': 'supply', 'type': 1, 'quantity': 3, 'receipt': 1002})
        print('Ammo reward requested.', flush=True)
        time.sleep(.75)
        after = json.loads(status.read_text())
        atomic_json(ROOT / '.research/ammo-after.json', after)
        print(json.dumps(after), flush=True)
        break
    time.sleep(.05)
else:
    print('No drawn firearm observed.', flush=True)
