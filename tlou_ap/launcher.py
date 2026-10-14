"""Windows desktop launcher for the native Archipelago client."""
import asyncio
import ctypes as c
from ctypes import wintypes as w
import json
import logging
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import uuid

from websockets.exceptions import ConnectionClosed, InvalidHandshake

from .client import Client
from .test_controls import TestControls
from .native.adapter import NativeAdapter
from .session import atomic_json
from .catalog import MISSIONS
from .notifications import DEFAULT_SETTINGS, ITEM_COLOURS, validate_settings, mission_lock_toast
from .overlay import NotificationOverlay, previews
from .recovery import backup, default_savedata
from .tracker import snapshot, death_status
from .tracker_ui import TrackerWindow, MetricStrip, CampaignTracker
from .theme import Appearance
from dataclasses import replace
from .preferences import DEFAULT_RUNTIME, DEFAULT_SEED, validate_runtime, seed_yaml
from .deliveries import delivery_snapshot, pending_supply_summary
from .client_tools import ClientTools
from .version import RELEASE
from .state_paths import state_directory, migrate_legacy_state
from .save_guide_ui import SaveGuide
from .run_profiles import RunProfiles
from .notifications import ToastQueue

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
STATE = state_directory(ROOT, getattr(sys, 'frozen', False))
LOG = logging.getLogger('tlou-ap')


def game_pid():
    class Process(c.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
                    ('heap', c.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                    ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD),
                    ('exe', w.WCHAR * 260)]
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [w.HANDLE, c.POINTER(Process)]
    k.CloseHandle.argtypes = [w.HANDLE]
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    if snapshot == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    found = []
    try:
        entry = Process(); entry.size = c.sizeof(entry)
        ok = k.Process32FirstW(snapshot, c.byref(entry))
        while ok:
            if entry.exe.lower() in ('tlou-i.exe', 'tlou-i-l.exe'):
                found.append(entry.pid)
            ok = k.Process32NextW(snapshot, c.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    if len(found) != 1:
        raise ValueError('Start one instance of The Last of Us Part I, then connect.')
    return found[0]


class QueueHandler(logging.Handler):
    def __init__(self, messages):
        super().__init__(); self.messages = messages

    def emit(self, record):
        self.messages.put((self.format(record), getattr(record, 'item_parts', None)))


async def run_client(server, slot, password, run_path, stop, status, notifications, actions, preferences=None):
    adapter = NativeAdapter(game_pid(), ROOT / 'dist/native', run_path)
    controls = None
    try:
        client = Client(slot, STATE / 'sessions', adapter, password or None, notify=notifications.put, preferences=preferences)
        controls = client.test_controls = TestControls(client)
        while not stop.is_set():
            connection = asyncio.create_task(client.connect(server))
            try:
                while not stop.is_set() and not connection.done():
                    adapter.bridge.heartbeat()
                    session = client.session
                    while not actions.empty():
                        action = actions.get_nowait()
                        try:
                            if action == 'backup':
                                LOG.info('Recovery bundle saved: %s', backup(STATE, default_savedata(), STATE / 'backups'))
                            elif action == 'retire' and session:
                                adapter.retire_held(session)
                                LOG.info('Retired %d held Airhorns.', client.airhorn.retire_held())
                            elif isinstance(action, dict) and action.get('type') == 'preferences':
                                client.set_preferences(action['value'])
                        except (OSError, ValueError) as error:
                            LOG.warning('Recovery action: %s', error)
                    blocked = adapter.bridge.shared.blocked
                    card = None
                    if 1 <= blocked <= len(MISSIONS):
                        mission = MISSIONS[blocked - 1]
                        card = mission_lock_toast(mission['name'],
                            chapter_unlocked=bool(session and mission['chapter'] in session.unlocked),
                            connected=client.connected, compatible=not adapter.compatibility_error)
                    context = adapter.delivery_context()
                    status.put({'connected': client.connected, 'pid': adapter.bridge.pid, 'lock_card':card,
                                'context': context, 'deliveries': delivery_snapshot(client, context),
                                'preferences': dict(client.preferences),
                                'slot_settings': session.config.slot_data() if session else None,
                                'observed_missions': list(session.data['missions']) if session else [],
                                'observed_checks': sorted(session.earned_checks) if session else [],
                                'trap_card': client.timed_effects.card() or client.airhorn.card(),
                                'traps': client.airhorn.queued + client.timed_effects.queued,
                                'started': adapter.ledger.data['started'],
                                'missions': len(session.data['missions']) if session else 0,
                                'checks': len(session.earned_checks) if session else 0,
                                'unlocked': len(session.unlocked) if session else 0,
                                'queued': len(session.queued_supplies) if session else 0,
                                'held': (sum(s in ('reserved', 'uncertain') for s in session.data['receipts'].values())
                                         + sum(e['state'] == 'held' for e in (client.airhorn.data or {}).get('items', {}).values()))
                                        if session else 0,
                                'blocked': adapter.bridge.shared.blocked,
                                'death_link': client.deathlink.enabled,
                                'death_pending': bool(client.deathlink.pending),
                                'death_state': client.deathlink.state,
                                'tracker': snapshot(session, client.checked, connected=client.connected,
                                    synchronized=client.inventory.synchronized,
                                    current=adapter.bridge.shared.current - 1,
                                    death_enabled=client.deathlink.enabled, death_state=client.deathlink.state)
                                    if session else None,
                                'compatibility_error': adapter.compatibility_error})
                    await asyncio.sleep(.5)
                if connection.done():
                    await connection
            except (OSError, ConnectionClosed, InvalidHandshake, asyncio.TimeoutError) as error:
                LOG.warning('Connection lost: %s. Retrying in five seconds.', error)
            finally:
                if not connection.done():
                    connection.cancel()
                try:
                    await connection
                except (asyncio.CancelledError, OSError, ConnectionClosed, InvalidHandshake, asyncio.TimeoutError):
                    pass
            for _ in range(10):
                if stop.is_set(): break
                await asyncio.sleep(.5)
    finally:
        try:
            if controls is not None: controls.close()
        finally:
            adapter.close()


class Launcher:
    def __init__(self, root):
        self.root, self.messages, self.status = root, queue.Queue(), queue.Queue()
        self.notifications = queue.Queue()
        self.actions = queue.Queue()
        self.stop = threading.Event()
        self.thread = None
        self.closing = False
        self.tracker = None
        self.tracker_view = None
        self.tools_window = None
        self.last_status = None
        STATE.mkdir(parents=True, exist_ok=True)
        self.settings_path = STATE / 'launcher.json'
        settings = json.loads(self.settings_path.read_text()) if self.settings_path.exists() else {}
        try:
            self.runtime_settings = validate_runtime(settings.get('gameplay', DEFAULT_RUNTIME))
        except ValueError:
            self.runtime_settings = dict(DEFAULT_RUNTIME)
        self.seed_settings = {**DEFAULT_SEED, **settings.get('seed_settings', {})}
        try:
            seed_yaml('Survivor', self.seed_settings)
        except (ValueError, TypeError):
            self.seed_settings = dict(DEFAULT_SEED)
        self.appearance = Appearance(root, settings.get('theme', 'light'), self.save_theme)
        try:
            self.notification_settings = validate_settings(settings.get('notifications', DEFAULT_SETTINGS))
        except ValueError:
            self.notification_settings = dict(DEFAULT_SETTINGS)
        self.overlay = NotificationOverlay(root)
        self.overlay.configure(self.notification_settings)
        self.run_profiles = RunProfiles(STATE, settings)
        self.run_name = self.run_profiles.selected
        self.save_guide = SaveGuide(self, STATE, game_pid)
        root.title('The Last of Us Part I • Archipelago')
        root.geometry('1060x960'); root.minsize(960, 800)
        style = self.appearance.style
        style.configure('Title.TLabel', font=('Segoe UI', 21, 'bold'))
        style.configure('Status.TLabel', font=('Segoe UI', 10))
        frame = ttk.Frame(root, padding=20); frame.pack(fill='both', expand=True)
        header = ttk.Frame(frame); header.pack(fill='x')
        ttk.Label(header, text='THE LAST OF US PART I', style='Title.TLabel').pack(side='left')
        self.appearance.selector(header).pack(side='right')
        ttk.Label(frame, text=f'Archipelago  •  Main story  •  {RELEASE}').pack(anchor='w', pady=(3, 12))
        runs = ttk.Frame(frame); runs.pack(fill='x', pady=(0, 8))
        ttk.Label(runs, text='Managed run').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.run_selector = ttk.Combobox(runs, state='readonly', width=40)
        self.run_selector.grid(row=0, column=1, sticky='ew', padx=(0, 12))
        runs.columnconfigure(1, weight=1)
        self.run_selector.bind('<<ComboboxSelected>>', self.select_run)
        self.appearance.combos.append(self.run_selector)
        ttk.Label(runs, text='Description').grid(row=0, column=2, padx=(0, 8))
        self.run_description = tk.StringVar(value=self.run_profiles.data['runs'][self.run_name]['description'])
        ttk.Entry(runs, textvariable=self.run_description, width=28).grid(row=0, column=3, sticky='ew')
        ttk.Button(runs, text='Save', command=self.save_run_description).grid(row=0, column=4, padx=(8, 0))
        self.delete_run_button = ttk.Button(runs, text='Delete run', command=self.delete_run)
        self.delete_run_button.grid(row=0, column=5, padx=(8, 0))
        self.refresh_run_choices()
        ttk.Label(frame, text='Switch runs: disconnect, restart the game, select a run, connect, then load its manual save.',
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        form = ttk.LabelFrame(frame, text='Archipelago room', padding=12); form.pack(fill='x')
        profile = self.run_profiles.data['runs'][self.run_name]
        self.server = tk.StringVar(value=profile['server'])
        self.slot = tk.StringVar(value=profile['slot'])
        self.password = tk.StringVar()
        self.room_fields = []
        for column, (label, variable) in enumerate((('Server', self.server), ('Slot name', self.slot), ('Password (optional)', self.password))):
            ttk.Label(form, text=label).grid(row=0, column=column, sticky='w', pady=(0, 6))
            field = ttk.Entry(form, textvariable=variable, width=22, show='•' if column == 2 else '')
            field.grid(row=1, column=column, sticky='ew', padx=(0, 10))
            self.room_fields.append(field)
            form.columnconfigure(column, weight=1)
        controls = ttk.Frame(form); controls.grid(row=1, column=3)
        self.connect_button = ttk.Button(controls, text='Connect', command=self.connect)
        self.connect_button.pack(side='left')
        self.disconnect_button = ttk.Button(controls, text='Disconnect', command=self.disconnect, state='disabled')
        self.disconnect_button.pack(side='left', padx=(6, 0))
        ttk.Label(form, text='Start the game separately. New runs begin in Hometown; resume with a save from the same run.',
                  style='Muted.TLabel').grid(row=2, column=0, columnspan=4, sticky='w', pady=(10, 0))
        self.connection_label = ttk.Label(frame, text='Start the game, then connect.', style='Status.TLabel')
        self.connection_label.pack(anchor='w', pady=(12, 5))
        self.run_label = ttk.Label(frame, text='Run: ' + self.run_name)
        self.run_label.pack(anchor='w')
        self.metrics = MetricStrip(frame); self.metrics.pack(fill='x', pady=(3, 0))
        self.progress_label = ttk.Label(frame, text='')
        self.progress_label.pack(anchor='w')
        self.pending_label = ttk.Label(frame, text='', style='Muted.TLabel')
        self.next_label = ttk.Label(frame, text='', style='Muted.TLabel')
        self.next_label.pack(anchor='w', pady=(3, 10))
        frame.bind('<Configure>', lambda event: [label.configure(wraplength=max(300, event.width - 40))
            for label in (self.connection_label, self.run_label, self.progress_label, self.pending_label, self.next_label)])
        panes = ttk.Panedwindow(frame, orient='vertical'); panes.pack(fill='both', expand=True)
        self.campaign = CampaignTracker(panes, self.appearance)
        panes.add(self.campaign, weight=4)
        lower = ttk.Frame(panes); panes.add(lower, weight=1)
        recovery_controls = ttk.Frame(lower); recovery_controls.pack(fill='x', pady=(9, 9))
        self.new_button = ttk.Button(recovery_controls, text='New managed run', command=self.new_run)
        self.new_button.pack(side='left', padx=(0, 8))
        ttk.Button(recovery_controls, text='Back up saves and run', command=self.backup_run).pack(side='left')
        ttk.Button(recovery_controls, text='Save guide (F9)', command=self.save_guide.show).pack(side='left')
        ttk.Button(recovery_controls, text='Expand tracker', command=self.show_tracker).pack(side='right')
        ttk.Button(recovery_controls, text='Deliveries / settings', command=self.show_tools).pack(side='right', padx=8)
        preferences = ttk.Frame(lower); preferences.pack(fill='x', pady=(0, 6))
        ttk.Label(preferences, text='Session log', font=('Segoe UI', 11, 'bold')).pack(side='left')
        self.scope_names = {'Your transfers': 'you', 'All players': 'all', 'Off': 'off'}
        self.scope = tk.StringVar(value=next(name for name, scope in self.scope_names.items()
                                           if scope == self.notification_settings['scope']))
        self.seconds = tk.StringVar(value=str(self.notification_settings['seconds']))
        ttk.Button(preferences, text='Preview colours', command=self.preview_notifications).pack(side='right', padx=(8, 0))
        scope = ttk.Combobox(preferences, textvariable=self.scope, values=list(self.scope_names),
                             state='readonly', width=16)
        scope.pack(side='right')
        scope.bind('<<ComboboxSelected>>', self.update_notifications)
        self.appearance.combos.append(scope)
        ttk.Label(preferences, text='In-game transfers').pack(side='right', padx=(0, 8))
        log_frame = ttk.Frame(lower); log_frame.pack(fill='both', expand=True)
        self.output = tk.Text(log_frame, wrap='word', height=7, font=('Consolas', 10), state='disabled',
                              bg='#10161A', fg='#E0E7EB', insertbackground='#E0E7EB')
        log_scroll = ttk.Scrollbar(log_frame, orient='vertical', command=self.output.yview)
        self.output.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side='right', fill='y'); self.output.pack(side='left', fill='both', expand=True)
        self.appearance.logs.append(self.output)
        for _, colour in ITEM_COLOURS:
            self.output.tag_configure(colour, foreground=colour)
        self.handler = QueueHandler(self.messages)
        self.handler.setFormatter(logging.Formatter('%(asctime)s  %(message)s', datefmt='%H:%M:%S'))
        LOG.setLevel(logging.INFO); LOG.addHandler(self.handler)
        file_handler = logging.FileHandler(STATE / 'client.log', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        LOG.addHandler(file_handler)
        self.appearance.apply()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(150, self.refresh)

    def save_settings(self, **overrides):
        self.run_profiles.update(self.run_name, description=self.run_description.get(),
                                 server=self.server.get(), slot=self.slot.get())
        atomic_json(self.settings_path, {**{'server': self.server.get().strip(), 'slot': self.slot.get().strip(),
                                        'run': self.run_name, 'notifications': self.notification_settings,
                                        'theme': self.appearance.name, 'gameplay': self.runtime_settings,
                                        'seed_settings': self.seed_settings}, **overrides})

    def save_theme(self):
        try:
            self.save_settings()
        except (OSError, ValueError) as error:
            LOG.warning('Could not save theme preference: %s', error)

    def update_notifications(self, _event=None):
        try:
            settings = validate_settings({**self.notification_settings,
                'scope': self.scope_names[self.scope.get()], 'seconds': int(self.seconds.get())})
            self.save_settings(notifications=settings)
            self.notification_settings = settings
        except (ValueError, OSError) as error:
            LOG.warning('Could not save notification settings: %s', error)
            return
        self.overlay.configure(settings)

    def apply_preferences(self, notifications, runtime):
        notifications = validate_settings(notifications)
        runtime = validate_runtime(runtime)
        self.save_settings(notifications=notifications, gameplay=runtime)
        self.notification_settings = notifications
        self.runtime_settings = runtime
        self.scope.set(next(name for name, code in self.scope_names.items() if code == notifications['scope']))
        self.seconds.set(str(notifications['seconds']))
        self.overlay.configure(notifications)
        if self.thread and self.thread.is_alive():
            self.actions.put({'type': 'preferences', 'value': dict(runtime)})

    def show_tools(self):
        if self.tools_window is None or not self.tools_window.window.winfo_exists():
            try:
                self.tools_window = ClientTools(self)
            except (ValueError, OSError) as error:
                messagebox.showerror('Client tools', str(error), parent=self.root)
                return
        self.tools_window.window.lift()

    def preview_notifications(self):
        try:
            pid = game_pid()
        except (ValueError, OSError) as error:
            LOG.warning('%s', error)
            return
        if self.notification_settings['scope'] == 'off':
            LOG.info('Enable notifications before previewing their colours.')
            return
        self.overlay.pid = pid
        for toast in previews():
            self.overlay.add(toast)
        LOG.info('Notification preview queued. Return to the game to see all four colours; no items or checks are changed.')

    def new_run(self):
        if self.thread and self.thread.is_alive():
            LOG.warning('Disconnect before creating or switching runs.'); return
        try:
            self.save_settings()
            name = self.run_profiles.create()
            self.switch_run(name)
        except (OSError, ValueError) as error:
            messagebox.showerror('Managed runs', str(error), parent=self.root)

    def refresh_run_choices(self):
        self.run_choices = list(self.run_profiles.data['runs'])
        self.run_selector.configure(values=[self.run_profiles.label(n) for n in self.run_choices])
        self.run_selector.current(self.run_choices.index(self.run_name))

    def delete_run(self):
        if self.thread and self.thread.is_alive():
            LOG.warning('Disconnect before deleting a run.'); return
        name = self.run_name
        if not messagebox.askyesno('Delete managed run',
                f'Delete {self.run_profiles.label(name)} from the run list?\n\n'
                'Game saves and the Archipelago room are not deleted. Local progress '
                'records are retained for recovery. If this is the last run, a blank run will be created.',
                parent=self.root):
            return
        try:
            replacement = self.run_profiles.delete(name)
            self.activate_run(replacement)
            self.save_settings()
            LOG.info('Deleted %s from the run list. Game saves and recovery records were preserved.', name)
        except (OSError, ValueError) as error:
            messagebox.showerror('Managed runs', str(error), parent=self.root)

    def save_run_description(self):
        try:
            self.save_settings()
            self.refresh_run_choices()
            self.run_label.configure(text='Run: ' + self.run_profiles.label(self.run_name))
        except (OSError, ValueError) as error:
            messagebox.showerror('Managed runs', str(error), parent=self.root)

    def select_run(self, _event=None):
        index = self.run_selector.current()
        if index < 0 or index >= len(self.run_choices): return
        try:
            self.switch_run(self.run_choices[index])
        except (OSError, ValueError) as error:
            self.refresh_run_choices()
            messagebox.showerror('Managed runs', str(error), parent=self.root)

    def switch_run(self, name):
        if self.thread and self.thread.is_alive():
            raise ValueError('Disconnect before switching runs.')
        if name == self.run_name: return
        if name not in self.run_profiles.data['runs']: raise ValueError('Unknown managed run')
        profile = self.run_profiles.data['runs'][name]
        # Persist selection before changing any visible or active run state.
        # A failed write must leave the previous run selected and usable.
        self.save_settings(run=name, server=profile['server'], slot=profile['slot'])
        self.activate_run(name)

    def activate_run(self, name):
        """Refresh all run-owned UI after a durable selection or deletion."""
        profile = self.run_profiles.data['runs'][name]
        self.run_name = self.run_profiles.selected = name
        self.server.set(profile['server']); self.slot.set(profile['slot']); self.password.set('')
        self.run_description.set(profile['description'])
        self.refresh_run_choices()
        # Drain all messages owned by the previous worker before displaying the
        # selected run. A live worker is disallowed above.
        for channel in (self.status, self.notifications, self.actions, self.messages):
            while not channel.empty(): channel.get_nowait()
        self.overlay.queue = ToastQueue()
        self.overlay.configure(self.notification_settings)
        self.overlay.state(0)
        self.save_guide.entries, self.save_guide.identity = [], None
        self.save_guide.enabled.set(False)
        self.save_guide.tick()
        self.tracker_view = None
        self.last_status = None
        if self.tools_window and self.tools_window.window.winfo_exists(): self.tools_window.update(None)
        self.metrics.update(None)
        self.campaign.update(None)
        self.progress_label.configure(text='')
        self.pending_label.configure(text=''); self.pending_label.pack_forget()
        self.next_label.configure(text='')
        if self.tracker and self.tracker.window.winfo_exists(): self.tracker.update(None)
        self.run_label.configure(text='Run: ' + self.run_profiles.label(self.run_name))
        self.connection_label.configure(text='Run selected. Restart the game if switching from another run, then connect.')
        self.output.configure(state='normal'); self.output.delete('1.0', 'end'); self.output.configure(state='disabled')
        LOG.info('Selected %s. Use its own manual save, or New Game for a new run. Restart the game when changing runs.',
                 self.run_profiles.label(self.run_name))

    def backup_run(self):
        if self.thread and self.thread.is_alive():
            self.actions.put('backup')
        else:
            try:
                LOG.info('Recovery bundle saved: %s', backup(STATE, default_savedata(), STATE / 'backups'))
            except (ValueError, OSError) as error:
                LOG.warning('Backup unavailable: %s', error)

    def show_tracker(self):
        if self.tracker is None or not self.tracker.window.winfo_exists():
            self.tracker = TrackerWindow(self.root, self.appearance)
        self.tracker.update(self.tracker_view)
        self.tracker.window.lift()


    def connect(self):
        if self.thread and self.thread.is_alive(): return
        if not self.server.get().strip() or not self.slot.get().strip():
            LOG.error('Enter the server and slot name.'); return
        server, slot, password = self.server.get().strip(), self.slot.get().strip(), self.password.get()
        try:
            self.save_settings()
        except (OSError, ValueError) as error:
            LOG.error('Could not save run settings: %s', error); return
        self.stop.clear()
        while not self.actions.empty(): self.actions.get_nowait()
        preferences = dict(self.runtime_settings)
        self.connect_button.configure(state='disabled'); self.new_button.configure(state='disabled')
        self.run_selector.configure(state='disabled')
        self.delete_run_button.configure(state='disabled')
        for field in self.room_fields: field.configure(state='disabled')
        self.disconnect_button.configure(state='normal')
        self.connection_label.configure(text='Attaching and connecting…')
        run_path = STATE / 'runs' / (self.run_name + '.json')
        def worker():
            try:
                asyncio.run(run_client(server, slot, password, run_path,
                                       self.stop, self.status, self.notifications, self.actions, preferences))
            except ValueError as error:
                LOG.error('%s', error)
            except Exception:
                LOG.exception('Client stopped')
            finally:
                self.status.put({'stopped': True})
        self.thread = threading.Thread(target=worker, daemon=True); self.thread.start()

    def disconnect(self):
        self.stop.set()
        self.disconnect_button.configure(state='disabled')
        LOG.info('Disconnecting. Chapter enforcement stays active; reconnect or restart the game for ordinary play.')

    def close(self):
        if self.thread and self.thread.is_alive():
            self.closing = True; self.disconnect()
        else:
            self.root.destroy()

    def refresh(self):
        while not self.messages.empty():
            text, parts = self.messages.get()
            self.output.configure(state='normal')
            if parts:
                self.output.insert('end', text.split('  ', 1)[0] + '  ')
                for part, colour in parts:
                    self.output.insert('end', part, (colour,) if colour else ())
                self.output.insert('end', '\n')
            else:
                self.output.insert('end', text + '\n')
            self.output.see('end')
            self.output.configure(state='disabled')
        while not self.status.empty():
            status = self.status.get()
            if status.get('stopped'):
                if self.last_status:
                    self.last_status = {**self.last_status, 'connected': False}
                if self.tracker_view:
                    self.tracker_view = replace(self.tracker_view, connected=False)
                self.connect_button.configure(state='normal'); self.new_button.configure(state='normal')
                self.run_selector.configure(state='readonly')
                self.delete_run_button.configure(state='normal')
                for field in self.room_fields: field.configure(state='normal')
                self.disconnect_button.configure(state='disabled')
                self.connection_label.configure(text='Disconnected. See the log for details.')
                self.overlay.state(0)
                if self.closing:
                    self.root.destroy(); return
            else:
                self.last_status = status
                if status.get('tracker') is not None:
                    self.tracker_view = status['tracker']
                elif self.tracker_view:
                    self.tracker_view = replace(self.tracker_view, connected=False)
                blocked = status['blocked']
                self.overlay.state(status['pid'], status_card=status.get('lock_card'), trap_card=status.get('trap_card'))
                text = ('Connected — start New Game in Hometown.' if not status['started'] else 'Connected — run active.')
                if not status['connected']: text = 'Waiting for the Archipelago server…'
                elif status['blocked']: text = 'Waiting at a locked mission — see the log.'
                if status.get('compatibility_error'): text = 'Save does not match this run — see the log.'
                self.connection_label.configure(text=text)
                self.progress_label.configure(text=f"{status['missions']}/29 missions complete  •  "
                    f"{status['queued']} supplies queued  •  {status['held']} receipts held  •  "
                    + f"{status.get('traps', 0)} traps waiting/active  •  "
                    + death_status(status.get('death_link'), status.get('death_state', 'idle')))
            pending_text = pending_supply_summary(self.last_status)
            self.pending_label.configure(text=pending_text)
            if pending_text:
                self.pending_label.pack(after=self.progress_label, anchor='w', pady=(3, 0))
            else:
                self.pending_label.pack_forget()
            if self.tracker and self.tracker.window.winfo_exists():
                self.tracker.update(self.tracker_view)
            self.metrics.update(self.tracker_view)
            self.campaign.update(self.tracker_view)
            if self.tracker_view:
                identity = dict(self.tracker_view.identity)
                self.run_label.configure(text=f"Run: {self.run_profiles.label(self.run_name)}  •  Slot: {self.slot.get()}  •  Seed: {identity['seed']}")
                self.next_label.configure(text=self.tracker_view.next_unlock if self.tracker_view.connected else
                                          'Disconnected — last known progress. Reconnect to refresh mission access.')
                level = status.get('context', {}).get('tool_level', -1)
                if self.tracker_view.connected and 0 <= level <= 5:
                    self.next_label.configure(text=self.tracker_view.next_unlock + f'  |  Tools: {level}/5')
            if self.tools_window and self.tools_window.window.winfo_exists():
                self.tools_window.update(self.last_status)
        while not self.notifications.empty():
            self.overlay.add(self.notifications.get())
        self.overlay.refresh()
        self.save_guide.tick()
        self.root.after(150, self.refresh)


def main():
    if '--offline-lab' in sys.argv:
        from tools.offline_lab import Lab
        root = tk.Tk(); Lab(root); root.mainloop()
        return
    if '--self-test' in sys.argv:
        from .selftest import run
        address = (sys.argv[sys.argv.index('--self-test-server') + 1]
                   if '--self-test-server' in sys.argv else None)
        run(Path(sys.argv[sys.argv.index('--self-test') + 1]), ROOT, address,
            experimental='--self-test-experimental' in sys.argv)
        return
    try:
        c.WinDLL('user32').SetProcessDpiAwarenessContext(c.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    migrate_legacy_state(ROOT / '.state', STATE)
    root = tk.Tk()
    icon = Path(__file__).with_name('data') / 'game.ico'
    if icon.is_file():
        root.iconbitmap(str(icon))
    app = Launcher(root)
    if '--connect' in sys.argv:
        root.after(300, app.connect)
    if '--preview-notifications' in sys.argv:
        root.after(1500, app.preview_notifications)
    root.mainloop()


if __name__ == '__main__':
    main()
