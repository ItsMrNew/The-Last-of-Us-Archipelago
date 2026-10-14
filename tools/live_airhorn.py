"""Offline Airhorn integration lab, restricted to the backed-up test save pack.

No server connection or real run state. Atomic control.json accepts incrementing
sequence and op: add, hold (mission), release, snapshot or stop. An existing
folder resumes its fake inventory and Airhorn journal, allowing restart tests.
"""
import json
from pathlib import Path
import sys
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.airhorn import Airhorn
from tlou_ap.catalog import AIRHORN, Config, ITEM_IDS
from tlou_ap.launcher import game_pid
from tlou_ap.native.airhorn import NativeAirhorn
from tlou_ap.native.bridge import Bridge
from tlou_ap.overlay import NotificationOverlay
from tlou_ap.session import ReceivedItem, Session, atomic_json

OWNER, ALL = 0x4c414231, (1 << 29) - 1


def main():
    if not (ROOT / '.state/save-pack-active.json').exists():
        raise SystemExit('Install the isolated test save pack first.')
    folder = Path(sys.argv[1]).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    config = Config(airhorn_trap_percentage=10, airhorn_mode='timed', airhorn_duration=30)
    session = Session(folder / 'fake-session', 'airhorn-offline', 0, 1, 'lab', config)
    root = tk.Tk(); root.withdraw()
    overlay = NotificationOverlay(root)
    horn = Airhorn(overlay.add); horn.bind(session)
    bridge = Bridge(game_pid(), ROOT / 'dist/native')
    sequence = 0
    atomic_json(folder / 'control.json', {'sequence': sequence})
    try:
        bridge.attach()
        if bridge.shared.reserved not in (0, OWNER):
            raise ValueError('Another run owns this game; restart first.')
        bridge.shared.reserved = OWNER
        bridge.shared.death_enabled = 0
        bridge.shared.mode, bridge.shared.allowed = 2, ALL
        native = NativeAirhorn(bridge, bridge.instance_key())

        class Adapter:
            def airhorn_status(self):
                return {'instance': native.instance, 'clock': bridge.shared.airhorn_clock_ms,
                        'ready': bool(bridge.shared.airhorn_ready)}

            def airhorn_pulse(self, receipt, instance, *, before_submit):
                return native.pulse(receipt, instance, before_submit=before_submit, can_submit=True)

        adapter = Adapter()
        deadline = time.monotonic() + 1800
        with (folder / 'events.jsonl').open('a', encoding='utf-8') as log:
            while time.monotonic() < deadline and bridge.is_alive():
                bridge.heartbeat()
                horn.poll(adapter)
                status = {'time': time.time(), 'bridge': bridge.status(), 'airhorn': adapter.airhorn_status(),
                          'journal': horn.data}
                atomic_json(folder / 'status.json', status)
                request = json.loads((folder / 'control.json').read_text())
                if request['sequence'] > sequence:
                    sequence = request['sequence']
                    op = request['op']
                    if op == 'stop':
                        break
                    if op == 'add':
                        items = [ReceivedItem.parse(i) for i in session.data['received']]
                        items.append(ReceivedItem(ITEM_IDS[AIRHORN], len(items), 1, 4))
                        session.record_inventory(items)
                    elif op == 'hold':
                        mission = int(request['mission']); assert 0 <= mission < 29
                        bridge.shared.allowed = ALL & ~(1 << mission)
                    elif op == 'release':
                        bridge.shared.allowed = ALL
                    elif op == 'snapshot':
                        atomic_json(folder / f'snapshot-{sequence}.json', status)
                overlay.state(bridge.pid, trap_card=horn.card())
                overlay.refresh(); root.update()
                for event in bridge.events():
                    log.write(json.dumps(event) + '\n')
                    bridge.acknowledge(event['sequence'])
                log.flush()
                time.sleep(.1)
    finally:
        if bridge.shared.reserved == OWNER:
            bridge.shared.mode = bridge.shared.death_enabled = 0
            bridge.shared.allowed = ALL
            time.sleep(.2)
            atomic_json(folder / 'shutdown.json', bridge.status())
        horn.suspend(); bridge.close(); root.destroy()


if __name__ == '__main__':
    main()
