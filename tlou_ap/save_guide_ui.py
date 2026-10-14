"""Read-only save guide, with a manually toggled click-through game overlay."""
import ctypes as c
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from .overlay import GameWindow, BACKGROUND, WHITE, MUTED
from .recovery import default_savedata
from .save_affinity import SaveRegistry, run_identity, LABELS

COLOURS = {'current': '#79D991', 'other': '#FF7777', 'unknown': '#FFB347', 'unreadable': '#BAC4CB'}
TAGS = {'current': 'confirmed', 'other': 'locked', 'unknown': 'waiting', 'unreadable': 'unknown'}
COLOURS.update(compatible=COLOURS['current'], incompatible=COLOURS['other'])
TAGS.update(compatible='confirmed', incompatible='locked')


class SaveGuide:
    def __init__(self, app, state, find_pid):
        self.app, self.state, self.find_pid = app, state, find_pid
        self.api = GameWindow()
        self.api.user.GetAsyncKeyState.argtypes = [c.c_int]
        self.api.user.GetAsyncKeyState.restype = c.c_short
        self.window = None
        self.overlay = tk.Toplevel(app.root)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.configure(bg=BACKGROUND)
        self.overlay.attributes('-alpha', .96)
        self.overlay.update_idletasks()
        self.hwnd = self.api.prepare(self.overlay)
        self.enabled = tk.BooleanVar(app.root, False)
        self.results = queue.Queue()
        self.busy, self.next_scan, self.key_down = False, 0, False
        self.entries, self.identity, self.savedata = [], None, None
        self.message = 'Reading saves…'
        self.active_run = None
        self.visible, self.placement, self.signature = False, None, None
        self.pid, self.next_pid = 0, 0
        self.labels = []

    def request_scan(self):
        if self.busy:
            self.next_scan = 0
            return
        self.busy = True
        name = self.app.run_name
        def scan():
            try:
                path = self.state / 'runs' / (name + '.json')
                ledger = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
                identity = run_identity(ledger) if ledger else None
                savedata = default_savedata()
                entries = SaveRegistry(self.state / 'save-guide.json').scan(savedata, identity, ledger=ledger)
                message = ('Updated ' + time.strftime('%H:%M:%S') + ' · ' + name if identity else
                           'Connect this managed run first; compatibility is unverified.')
                self.results.put((name, entries, identity, savedata, message))
            except Exception as error:
                # A reader/structure error must still complete this worker.
                # Otherwise busy stays true and stale labels never refresh.
                self.results.put((name, [], None, None, 'Save guide unavailable: ' + str(error)))
        threading.Thread(target=scan, daemon=True).start()
        self.next_scan = time.monotonic() + 5

    def show(self):
        if self.window is None or not self.window.winfo_exists():
            self.window = tk.Toplevel(self.app.root)
            self.window.title('Save guide — The Last of Us Part I')
            self.window.geometry('890x640')
            self.window.minsize(720, 480)
            self.app.appearance.windows.append(self.window)
            frame = ttk.Frame(self.window, padding=16); frame.pack(fill='both', expand=True)
            ttk.Label(frame, text='Save guide', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
            ttk.Label(frame, text='Green: compatible progress   ·   Red: incompatible / known other run   ·   Amber: unable to verify',
                      wraplength=820).pack(anchor='w', pady=(8, 3))
            ttk.Label(frame, text='Saves are checked automatically against this managed run’s progress. '
                      'Passing the check does not prove ownership or unlock later missions. Select a save for details.',
                      wraplength=820, style='Muted.TLabel').pack(anchor='w', pady=(0, 10))
            controls = ttk.Frame(frame); controls.pack(fill='x')
            ttk.Checkbutton(controls, text='Show guide over game (F9 toggles)', variable=self.enabled).pack(side='left')
            ttk.Button(controls, text='Refresh', command=self.request_scan).pack(side='right')
            self.status = ttk.Label(frame, text=self.message, wraplength=820)
            self.status.pack(anchor='w', pady=8)
            table = ttk.Frame(frame); table.pack(fill='both', expand=True)
            self.table = ttk.Treeview(table, columns=('status', 'chapter'), selectmode='browse')
            self.table.heading('#0', text='Save name'); self.table.column('#0', width=210, minwidth=160)
            self.table.heading('status', text='Progress check'); self.table.column('status', width=130, stretch=False)
            self.table.heading('chapter', text='Chapter / play time'); self.table.column('chapter', width=410)
            scroll = ttk.Scrollbar(table, orient='vertical', command=self.table.yview)
            self.table.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y'); self.table.pack(fill='both', expand=True)
            self.app.appearance.tables.append(self.table)
            self.detail = ttk.Label(frame, text='Select a save to see its details.', wraplength=820)
            self.detail.pack(anchor='w', pady=10)
            self.table.bind('<<TreeviewSelect>>', self.selected)
            ttk.Button(frame, text='Record known ownership…', command=self.confirm).pack(anchor='w')
            self.app.appearance.apply()
            self.render_table()
        self.window.lift()
        self.request_scan()

    def selected(self, _event=None):
        selected = self.table.selection()
        entry = next((e for e in self.entries if selected and e.slot == selected[0]), None)
        if entry:
            description = entry.error or entry.detail.split('\n\n')[0].replace('\n', ' · ')
            self.detail.configure(text=description + ('\n' + entry.reason if entry.reason else ''))

    def confirm(self):
        selected = self.table.selection()
        entry = next((e for e in self.entries if selected and e.slot == selected[0]), None)
        if entry is None or not entry.fingerprint or self.identity is None:
            messagebox.showinfo('Save guide', 'Select a readable save and connect this managed run first.', parent=self.window)
            return
        identity, run_name = dict(self.identity), self.app.run_name
        if not messagebox.askyesno('Confirm save ownership',
                f'Did you create {entry.title} while playing {run_name}?\n\n'
                + entry.detail.split('\n\n')[0] + '\n\n'
                'Only confirm if you know this save belongs to this run. This records ownership; '
                'it does not make an incompatible save safe or unlock missions.', parent=self.window):
            return
        try:
            current = run_identity(json.loads((self.state / 'runs' / (self.app.run_name + '.json')).read_text(encoding='utf-8')))
            if self.app.run_name != run_name or current != identity:
                raise ValueError('The selected run changed; refresh and try again.')
            SaveRegistry(self.state / 'save-guide.json').confirm(self.savedata, entry, identity)
        except (OSError, ValueError) as error:
            messagebox.showerror('Save guide', str(error), parent=self.window)
        self.request_scan()

    def render_table(self):
        if self.window is None or not self.window.winfo_exists():
            return
        self.status.configure(text=self.message)
        selected = self.table.selection()
        keep = {e.slot for e in self.entries}
        for iid in self.table.get_children():
            if iid not in keep: self.table.delete(iid)
        for index, entry in enumerate(self.entries):
            values = (LABELS[entry.status], ' · '.join(entry.detail.splitlines()[:2]))
            options = dict(text=entry.title, values=values, tags=(TAGS[entry.status],))
            if self.table.exists(entry.slot): self.table.item(entry.slot, **options)
            else: self.table.insert('', 'end', iid=entry.slot, **options)
            self.table.move(entry.slot, '', index)
        if selected and selected[0] in keep: self.table.selection_set(selected[0])
        self.selected()

    def tick(self):
        now = time.monotonic()
        if self.active_run != self.app.run_name:
            self.active_run = self.app.run_name
            self.entries, self.identity = [], None
            self.message = 'Reading saves for ' + self.active_run + '…'
            self.next_scan = 0
            self.render_table()
        while not self.results.empty():
            name, entries, identity, savedata, message = self.results.get_nowait()
            self.busy = False
            if name == self.app.run_name:
                self.entries, self.identity, self.savedata, self.message = entries, identity, savedata, message
                self.render_table()
        guide_open = self.window is not None and self.window.winfo_exists()
        if not self.busy and now >= self.next_scan and (guide_open or self.enabled.get()): self.request_scan()
        if now >= self.next_pid:
            try: self.pid = self.find_pid()
            except (ValueError, OSError): self.pid = 0
            self.next_pid = now + 2
        rect = self.api.focused_rect(self.pid)
        key_state = self.api.user.GetAsyncKeyState(0x78)
        down = bool(key_state & 0x8000)
        pressed = bool(key_state & 1) or (down and not self.key_down)
        if rect and pressed: self.enabled.set(not self.enabled.get())
        self.key_down = down
        if not rect or not self.enabled.get():
            if self.visible: self.overlay.withdraw()
            self.visible, self.placement = False, None
            return
        x, y, gw, gh, dpi = rect
        scale = min(dpi, gw / 900, gh / max(540, 145 + len(self.entries) * 24))
        width, pad = round(370 * scale), max(6, round(12 * scale))
        lines = [('ARCHIPELAGO · SAVE GUIDE · F9 TO HIDE', WHITE, True),
                 ('Green: compatible · Red: incompatible / other run\nAmber: unable to verify', MUTED, False)]
        lines += [(f'{e.title} — {LABELS[e.status]}', COLOURS[e.status], False) for e in self.entries]
        lines += [(self.message, MUTED, False),
                  ('Automatic progress check, not proof of ownership. Details in the launcher.', MUTED, False)]
        signature = tuple(lines), width, scale
        if signature != self.signature:
            while len(self.labels) > len(lines): self.labels.pop().destroy()
            while len(self.labels) < len(lines):
                label = tk.Label(self.overlay, bg=BACKGROUND, anchor='w', justify='left')
                label.pack(fill='x'); self.labels.append(label)
            for label, (text, colour, bold) in zip(self.labels, lines):
                label.configure(text=text, fg=colour,
                    font=('Segoe UI', -max(7, round(13 * scale)), 'bold' if bold else 'normal'),
                    wraplength=width - 2 * pad)
                label.pack_configure(padx=pad, pady=max(1, round(2 * scale)))
            self.overlay.update_idletasks()
            self.height = self.overlay.winfo_reqheight()
            self.overlay.geometry(f'{width}x{self.height}')
            self.signature = signature
        placement = x + gw - width - pad, y + max(pad, (gh - self.height) // 2), width, self.height
        if not self.visible:
            self.api.position(self.hwnd, *placement)
            self.overlay.deiconify()
        if placement != self.placement or not self.visible: self.api.position(self.hwnd, *placement)
        self.visible, self.placement = True, placement
