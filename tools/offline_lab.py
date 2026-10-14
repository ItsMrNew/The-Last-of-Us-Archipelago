"""Offline game-hook laboratory. No AP connection, checks, inventory ledger or goal."""
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tlou_ap.catalog import CHAPTERS, COLLECTIBLES, MISSIONS
from tlou_ap.launcher import game_pid, ROOT as APP_ROOT
from tlou_ap.native.bridge import Bridge, validate_gate_build
from tlou_ap.notifications import Toast, item_colour
from tlou_ap.overlay import NotificationOverlay
from tlou_ap.session import atomic_json

ROOT = APP_ROOT
ALL = (1 << len(MISSIONS)) - 1
LAB_OWNER = 0x4C414230
HOLD_SECONDS = 180
NAMES = {int(item['sid'], 16): item['name'] for item in COLLECTIBLES}


class Lab:
    def __init__(self, root):
        self.root, self.bridge, self.mutex = root, None, None
        self.hold = self.hold_started = self.pending_command = self.last_reward = None
        self.queued_ammo = self.last_supplies = None
        self.effect_ends = [0, 0]
        self.overlay = NotificationOverlay(root)
        self.output_dir = ROOT / '.research/offline-lab' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
        self.output_dir.mkdir(parents=True)
        root.title('TLOU • Offline Test Lab'); root.geometry('950x760')
        panel = ttk.Frame(root, padding=16); panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='OFFLINE TEST LAB', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(panel, text='Uses test saves. No Archipelago server connection or checks. Restart the game before returning to your real run.').pack(anchor='w', pady=8)
        self.status = ttk.Label(panel, text='Attaching…'); self.status.pack(anchor='w', pady=8)
        self.selected = ttk.Combobox(panel, state='readonly', values=[
            f'{m["index"] + 1:02d}  {CHAPTERS[m["chapter"]]["name"]} — {m["name"]}' for m in MISSIONS])
        self.selected.pack(fill='x'); self.selected.current(2)
        row = ttk.Frame(panel); row.pack(fill='x', pady=8)
        self.hold_button = ttk.Button(row, text='Hold selected mission 3 minutes', command=self.arm)
        self.hold_button.pack(side='left')
        ttk.Button(row, text='Release all missions', command=self.release).pack(side='left', padx=8)
        row = ttk.Frame(panel); row.pack(fill='x', pady=8)
        for label, callback in [('All ammo +50%', lambda:self.reward(4)), ('Health kit +1', lambda:self.reward(2)),
                                ('Shiv +1', lambda:self.reward(5)),
                                ('Repeat last receipt', self.repeat), ('Look up last receipt', self.lookup)]:
            ttk.Button(row, text=label, command=callback).pack(side='left', padx=2)
        row = ttk.Frame(panel); row.pack(fill='x')
        ttk.Button(row, text='Queue legacy +3 drawn-gun test', command=self.queue_ammo).pack(side='left', padx=2)
        ttk.Button(row, text='Cancel queued ammo', command=self.cancel_ammo).pack(side='left', padx=2)
        row = ttk.Frame(panel); row.pack(fill='x', pady=6)
        for label, kind in (('Crafting Cache +1 each', 11), ('Workbench Parts +25', 12), ('Supplements +10', 13)):
            ttk.Button(row, text=label, command=lambda k=kind:self.reward(k)).pack(side='left', padx=2)
        row = ttk.Frame(panel); row.pack(fill='x', pady=6)
        ttk.Button(row, text='Shaky Hands +30s', command=lambda:self.trap(0)).pack(side='left', padx=2)
        ttk.Button(row, text='Faulty Flashlight +30s', command=lambda:self.trap(1)).pack(side='left', padx=2)
        ttk.Button(row, text='Stop both traps', command=self.stop_traps).pack(side='left', padx=2)
        self.effect_status = ttk.Label(panel, text='No timed traps queued'); self.effect_status.pack(anchor='w')
        self.text = tk.Text(panel, wrap='word', state='disabled', bg='#11181d', fg='#d8e7ef')
        self.text.pack(fill='both', expand=True, pady=8)
        ttk.Label(panel, text='Logs: ' + str(self.output_dir.relative_to(ROOT))).pack(anchor='w')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.attach)

    def log(self, text, **data):
        self.text.configure(state='normal'); self.text.insert('end', datetime.now().strftime('%H:%M:%S ') + text + '\n')
        self.text.see('end'); self.text.configure(state='disabled')
        with (self.output_dir / 'lab.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'time':time.time(), 'message':text, **data})+'\n')

    def attach(self):
        try:
            b = self.bridge = Bridge(game_pid(), ROOT / 'dist/native')
            k = b.memory.kernel
            k.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]; k.CreateMutexW.restype = w.HANDLE
            k.ReleaseMutex.argtypes = [w.HANDLE]
            c.set_last_error(0)
            self.mutex = k.CreateMutexW(None, True, f'Local\\TLOUAP_Client_{b.pid}')
            if not self.mutex or c.get_last_error() == 183:
                raise ValueError('Close the normal Archipelago client first.')
            b.attach()
            if b.shared.reserved not in (0, LAB_OWNER):
                raise ValueError('This process belongs to a real run. Restart the game before offline tests.')
            b.shared.reserved = LAB_OWNER
            self.release()
            self.log('Connected to game. All main-story missions permitted.', native_instance=b.instance_key())
            try:
                validate_gate_build(b.manifest['build_id'], experimental=True)
            except ValueError as error:
                self.hold_button.configure(text='Mission holds disabled: failed live test', state='disabled')
                self.log(str(error))
            self.poll()
        except Exception as error:
            self.status.configure(text=str(error)); self.log(str(error)); self.dispose()

    def arm(self):
        if self.bridge is None: return
        try:
            validate_gate_build(self.bridge.manifest['build_id'], experimental=True)
        except ValueError as error:
            self.log(str(error))
            return
        self.hold, self.hold_started = self.selected.current(), None
        self.log('Armed 3-minute hold: ' + MISSIONS[self.hold]['name'], duration_seconds=HOLD_SECONDS)
        self.publish_gate()

    def release(self):
        self.hold = self.hold_started = None
        if self.bridge:
            self.publish_gate(); self.log('All missions released.')

    def publish_gate(self):
        b = self.bridge; b.heartbeat()
        b.shared.allowed = ALL & ~(1 << self.hold) if self.hold is not None else ALL
        b.shared.mode = b.manifest.get('gate_mode', 1)

    def tick_gate(self, now):
        shared = self.bridge.shared
        blocked = self.hold is not None and shared.pending and shared.blocked == self.hold + 1
        if blocked and self.hold_started is None:
            self.hold_started = now
            self.log('Mission held; 3-minute timer running.', duration_seconds=HOLD_SECONDS)
        elif not blocked and self.hold_started is not None:
            self.hold_started = None
            self.log('Gameplay hold cleared for loading/menu; timer reset. Mission denial remains armed.')
        if self.hold_started is not None and now - self.hold_started >= HOLD_SECONDS:
            self.release()

    def remaining_seconds(self, now):
        if self.hold_started is None:
            return None
        return max(0, math.ceil(HOLD_SECONDS - (now - self.hold_started)))

    def refresh_overlay(self, now):
        card = None
        if self.hold is not None:
            remaining = self.remaining_seconds(now)
            card = Toast('OFFLINE TEST · ' + ('MISSION HELD' if remaining is not None else 'HOLD ARMED'),
                MISSIONS[self.hold]['name'],
                f'Resumes automatically in {remaining // 60}:{remaining % 60:02d}' if remaining is not None
                else 'Waiting for mission start · 3-minute hold',
                'Mission has not been unlocked yet. Receive Progressive Chapter Unlock to unlock this mission.' if remaining is not None
                else 'The countdown starts when the game attempts this mission.', item_colour(1))
        self.overlay.state(self.bridge.pid, status_card=card)
        self.overlay.refresh()

    def submit(self, kind, arg, receipt):
        b = self.bridge
        if not b or self.pending_command or b.command_busy:
            self.log('Game command busy; wait and try again.'); return
        self.pending_command = (b.begin_command(kind, arg, receipt), kind, receipt)
        self.log(f'Submitted command {kind}.', receipt=receipt, argument=arg)

    def reward(self, kind):
        if not self.bridge: return
        if self.bridge.command_busy or self.pending_command:
            self.log('Wait for telemetry to finish, then retry.'); return
        receipt = uuid.uuid4().int & ((1 << 64)-1) or 1
        self.last_reward = (kind, receipt)
        self.submit(kind, (3 if kind == 1 else 1) | (self.bridge.shared.current << 8), receipt)

    def trap(self, index):
        if not self.bridge: return
        s = self.bridge.shared
        self.effect_ends[index] = max(self.effect_ends[index], s.effect_clock[index]) + 30000
        self.log(('Shaky Hands' if index == 0 else 'Faulty Flashlight') + ' stacked +30 playable seconds.')

    def stop_traps(self):
        self.effect_ends = [0, 0]
        if self.bridge: self.bridge.shared.effect_mask = 0

    def tick_traps(self):
        s = self.bridge.shared
        s.effect_mask = 0
        remaining = [max(0, self.effect_ends[i] - s.effect_clock[i]) for i in range(2)]
        for i in range(2): s.effect_until[i] = self.effect_ends[i]
        k = self.bridge.memory.kernel; k.GetTickCount64.restype = c.c_uint64
        s.effect_lease = k.GetTickCount64()
        s.effect_mask = sum(1 << i for i, value in enumerate(remaining) if value)
        state = 'active' if s.airhorn_ready else 'queued / paused'
        self.effect_status.configure(text=f'Shaky Hands: {remaining[0]/1000:.1f}s | Faulty Flashlight: {remaining[1]/1000:.1f}s | {state}')

    def queue_ammo(self):
        if not self.bridge or not 1 <= self.bridge.shared.current <= len(MISSIONS):
            self.log('Load a mission before queuing ammo.'); return
        self.queued_ammo = (self.bridge.shared.current, time.monotonic() + 120)
        self.log('One ammo delivery queued for the next drawn weapon. Expires in two minutes or on mission change.')

    def cancel_ammo(self):
        if self.queued_ammo is not None:
            self.queued_ammo = None; self.log('Queued ammo cancelled.')

    def deliver_queued_ammo(self, supplies):
        if self.queued_ammo is None: return
        mission, deadline = self.queued_ammo
        b = self.bridge
        if time.monotonic() >= deadline or b.shared.current != mission:
            self.cancel_ammo(); return
        if (not b.command_busy and not self.pending_command and not b.shared.pending
                and supplies['player'] and supplies['weapon'] and supplies['ammo'] >= 0):
            # Consume the request before submitting. Never auto-retry an uncertain effect.
            self.queued_ammo = None
            self.log('Drawn weapon detected; attempting the queued delivery once.', before=supplies)
            self.reward(1)

    def repeat(self):
        if self.last_reward and self.bridge:
            kind, receipt = self.last_reward
            self.submit(kind, (3 if kind == 1 else 1) | (self.bridge.shared.current << 8), receipt)

    def lookup(self):
        if self.last_reward: self.submit(101, *self.last_reward)

    def poll(self):
        try:
            b = self.bridge
            if not b.is_alive(): raise ValueError('Game closed. Close this lab and relaunch for another test.')
            if b.shared.status != 1 or b.shared.error: raise ValueError(f'Bridge error: {b.status()}')
            now = time.monotonic()
            self.tick_gate(now)
            self.tick_traps()
            self.publish_gate()
            if self.pending_command:
                seq, kind, receipt = self.pending_command
                result = b.command_result(seq)
                if result is not None:
                    self.log('Command result: ' + {1:'applied/cached',2:'no effect; inventory unavailable/full',
                        3:'uncertain; do not regrant',4:'invalid command/receipt',5:'receipt absent'}.get(result,str(result)),
                        kind=kind, receipt=receipt, result=result, supplies=b.supplies())
                    self.pending_command = None
            for event in b.events():
                with (self.output_dir/'events.jsonl').open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps({**event,'native_instance':b.instance_key(),'offline_test':True})+'\n')
                if event['type'] in (2,7) and event['flags'] & 1:
                    self.log('Collectible award: '+NAMES.get(event['sid'],hex(event['sid'])), event=event)
                elif event['type'] in (1,3,4,8):
                    mission=event['mission']-1
                    path = ('engine gameplay pause' if event['flags'] & 0x20000000 else
                            'automatic graph' if event['flags'] & 0x40000000 else
                            'transition Begin' if event['flags'] & 0x80000000 else 'direct Play')
                    self.log({1:'Started: ',3:'Blocked: ',4:'Released: ',8:'Cancelled stale start: '}[event['type']] +
                             (MISSIONS[mission]['name'] if 0 <= mission < len(MISSIONS) else 'menu/unknown') +
                             ' (' + path + ')', event=event)
                    if (event['type'] == 4 and 0 <= mission < len(MISSIONS)
                            and b.shared.allowed & (1 << mission)):
                        self.overlay.add(Toast('OFFLINE TEST · MISSION RELEASED', MISSIONS[mission]['name'],
                            'The mission lock has been released.', '', item_colour(1)))
                b.acknowledge(event['sequence'])
            supplies=b.supplies();current=b.shared.current-1
            if supplies != self.last_supplies:
                self.log('Inventory telemetry changed.', supplies=supplies)
                self.last_supplies = supplies
            self.deliver_queued_ammo(supplies)
            self.status.configure(text=f"{MISSIONS[current]['name'] if 0<=current<len(MISSIONS) else 'Main menu/loading'} | "
                f"kits {supplies['health_kits']} | ammo {supplies['ammo']} | mission held {bool(b.shared.pending)}")
            atomic_json(self.output_dir/'status.json', {'time':time.time(),'bridge':b.status(),'supplies':supplies,
                'pending':b.shared.pending,'hold':self.hold,'hold_seconds':HOLD_SECONDS,
                'remaining_seconds':self.remaining_seconds(now),
                'native_instance':b.instance_key(),'offline_test':True})
            self.refresh_overlay(now)
            if not b.command_busy and not self.pending_command: b.begin_command(100)
            self.root.after(250, self.poll)
        except Exception as error:
            self.log(str(error));self.status.configure(text=str(error));self.dispose()

    def dispose(self):
        self.overlay.state(0)
        self.overlay.refresh()
        if self.bridge:
            # A stopped laboratory releases test starts; normal client still
            # rejects LAB_OWNER until the game restarts.
            if self.bridge.shared.status == 1 and self.bridge.shared.reserved == LAB_OWNER:
                self.bridge.shared.effect_mask = 0
                self.bridge.shared.mode = 0
            if self.mutex:
                self.bridge.memory.kernel.ReleaseMutex(self.mutex)
                self.bridge.memory.kernel.CloseHandle(self.mutex);self.mutex=None
            self.bridge.close();self.bridge=None

    def close(self):
        self.dispose();self.overlay.close();self.root.destroy()


if __name__ == '__main__':
    root=tk.Tk();Lab(root);root.mainloop()
