"""Hold the next Cargo task start for three seconds, then release it."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.session import atomic_json

control = ROOT / '.research/live-control.json'
status = ROOT / '.research/live-status.json'
sequence = json.loads(control.read_text())['sequence'] + 1
atomic_json(control, {'sequence': sequence, 'op': 'gate', 'mask': ((1 << 29) - 1) & ~(1 << 4)})
print('Cargo lock armed; waiting for a task start.', flush=True)
try:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        data = json.loads(status.read_text())
        if data['sequence'] == sequence and data['bridge']['blocked'] == 5:
            atomic_json(ROOT / '.research/gate-held.json', data)
            print('Cargo start blocked. Releasing in three seconds.', flush=True)
            time.sleep(3)
            break
        time.sleep(.1)
finally:
    atomic_json(control, {'sequence': sequence + 1, 'op': 'release'})
    print('Gate released.', flush=True)
