"""Delivery and live preferences windows. No game writes."""
import tkinter as tk
from tkinter import ttk, messagebox

from .notifications import validate_settings
from .preferences import validate_runtime
from .deliveries import display_rows


class ClientTools:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Archipelago • Deliveries and settings')
        self.window.geometry('1120x800'); self.window.minsize(960, 700)
        app.appearance.windows.append(self.window)
        frame = ttk.Frame(self.window, padding=18); frame.pack(fill='both', expand=True)
        header = ttk.Frame(frame); header.pack(fill='x', pady=(0, 12))
        ttk.Label(header, text='CLIENT TOOLS', font=('Segoe UI', 18, 'bold')).pack(side='left')
        app.appearance.selector(header).pack(side='right')
        self.tabs = ttk.Notebook(frame); self.tabs.pack(fill='both', expand=True)
        self.pages = {}
        for title in ('Deliveries', 'Live settings'):
            page = ttk.Frame(self.tabs, padding=14)
            self.tabs.add(page, text=title); self.pages[title] = page
        self.build_deliveries()
        self.build_settings()
        self.last_rows = None
        self.update(app.last_status)
        app.appearance.apply()

    def combo(self, parent, variable, values, width=22, command=None):
        widget = ttk.Combobox(parent, textvariable=variable, values=values, state='readonly', width=width)
        self.app.appearance.combos.append(widget)
        if command: widget.bind('<<ComboboxSelected>>', command)
        return widget

    def table(self, parent, columns, height=12):
        frame = ttk.Frame(parent); frame.pack(fill='both', expand=True)
        table = ttk.Treeview(frame, columns=[x[0] for x in columns], show='headings', height=height)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); table.pack(side='left', fill='both', expand=True)
        for key, name, width in columns:
            table.heading(key, text=name); table.column(key, width=width, minwidth=65)
        self.app.appearance.tables.append(table)
        return table

    def build_deliveries(self):
        page = self.pages['Deliveries']
        self.delivery_summary = ttk.Label(page, text='Connect to see deliveries.')
        self.delivery_summary.pack(anchor='w', pady=(0, 10))
        filters = ttk.Frame(page); filters.pack(fill='x', pady=(0, 10))
        self.history = tk.BooleanVar(value=False)
        ttk.Checkbutton(filters, text='Include completed delivery history', variable=self.history,
                        command=lambda: self.render_deliveries(force=True)).pack(side='left')
        self.delivery_table = self.table(page, [('number', '#', 50), ('item', 'Item / effect', 170),
            ('state', 'Status', 105), ('source', 'From', 125), ('reason', 'Waiting reason / result', 490)])
        self.delivery_detail = ttk.Label(page, text='Select a delivery to read its full status.', wraplength=980)
        self.delivery_detail.pack(anchor='w', fill='x', pady=(10, 0))
        self.delivery_table.bind('<<TreeviewSelect>>', self.select_delivery)
        ttk.Label(page, text='Two transfer cards appear at once; further cards queue in order. Effects do not wait for the cards.\n'
                  'Timed Airhorns stack. Completed history uses durable receipts; checkpoint rollback does not regrant supplies.',
                  wraplength=980).pack(anchor='w', pady=(10, 0))

    def slider(self, parent, title, variable, minimum, maximum, row, suffix=''):
        ttk.Label(parent, text=title).grid(row=row, column=0, sticky='w', padx=(0, 16), pady=8)
        scale = ttk.Scale(parent, variable=variable, from_=minimum, to=maximum)
        scale.grid(row=row, column=1, sticky='ew', pady=8)
        label = ttk.Label(parent, width=10)
        label.grid(row=row, column=2, sticky='w', padx=(12, 0))
        def changed(*_): label.configure(text=f'{round(variable.get())}{suffix}')
        variable.trace_add('write', changed); changed()
        return scale

    def build_settings(self):
        page = self.pages['Live settings']
        settings, runtime = self.app.notification_settings, self.app.runtime_settings
        form = ttk.Frame(page); form.pack(fill='x'); form.columnconfigure(1, weight=1)
        self.death_names = {'Follow YAML': 'yaml', 'Enabled': 'enabled', 'Disabled': 'disabled'}
        self.mode_names = {'Follow YAML': 'yaml', 'Single blast': 'single_blast', 'Timed': 'timed'}
        self.position_names = {name.replace('_', ' ').title(): name for name in
                               ('top_right', 'top_left', 'bottom_right', 'bottom_left')}
        def label_for(names, value): return next(name for name, code in names.items() if code == value)
        self.death = tk.StringVar(value=label_for(self.death_names, runtime['death_link']))
        self.mode = tk.StringVar(value=label_for(self.mode_names, runtime['airhorn_mode']))
        self.position = tk.StringVar(value=label_for(self.position_names, settings['position']))
        self.scope = tk.StringVar(value=label_for(self.app.scope_names, settings['scope']))
        for row, (title, var, names) in enumerate((('DeathLink', self.death, self.death_names),
                ('Airhorn mode', self.mode, self.mode_names), ('Notification position', self.position, self.position_names),
                ('Show transfers', self.scope, self.app.scope_names))):
            ttk.Label(form, text=title).grid(row=row, column=0, sticky='w', pady=8)
            self.combo(form, var, list(names)).grid(row=row, column=1, sticky='w', pady=8)
        self.duration = tk.DoubleVar(value=runtime['airhorn_duration'])
        self.volume = tk.DoubleVar(value=settings['volume'])
        self.seconds = tk.DoubleVar(value=settings['seconds'])
        self.slider(form, 'Timed Airhorn duration', self.duration, 30, 120, 4, 's')
        self.slider(form, 'Airhorn sound volume', self.volume, 0, 100, 5, '%')
        self.slider(form, 'Notification duration', self.seconds, 2, 30, 6, 's')
        from .sound import HornPlayer
        installed = len(HornPlayer().recordings())
        sound_status = (f'Horn sounds: {installed}/5 recordings installed. Shuffled per blast, without consecutive repeats.'
                        if installed > 1 else 'Horn sounds: 1/5 recordings installed. Add the remaining recordings for variety.'
                        if installed else 'Horn sounds: original fallback. The five selected recordings have not been installed yet.')
        ttk.Label(page, text=sound_status, wraplength=950).pack(anchor='w', pady=(12, 0))
        self.effective = ttk.Label(page, text='', wraplength=950)
        self.effective.pack(anchor='w', pady=12)
        ttk.Label(page, text='Apply takes effect during the current connection. Airhorn mode/duration changes apply to newly received traps;\n'
                  'queued and active traps keep their recorded durations. Three timed 30s traps combine into a 90s countdown.\n'
                  'Disabling DeathLink preserves waiting deaths. Volume 0 mutes only the horn sound; the trap still alerts enemies.',
                  wraplength=950).pack(anchor='w', pady=8)
        controls = ttk.Frame(page); controls.pack(fill='x', pady=12)
        ttk.Button(controls, text='Apply live settings', command=self.apply_settings).pack(side='left')
        ttk.Button(controls, text='Test horn sound', command=self.preview_sound).pack(side='left', padx=8)
        ttk.Button(controls, text='Preview notification colours', command=self.app.preview_notifications).pack(side='left')
        self.settings_result = ttk.Label(page, text=''); self.settings_result.pack(anchor='w')

    def preview_sound(self):
        from .sound import play_airhorn
        play_airhorn(round(self.volume.get()))

    def apply_settings(self):
        try:
            notifications = validate_settings({'scope': self.app.scope_names[self.scope.get()],
                'seconds': round(self.seconds.get()), 'volume': round(self.volume.get()),
                'position': self.position_names[self.position.get()]})
            runtime = validate_runtime({'death_link': self.death_names[self.death.get()],
                'airhorn_mode': self.mode_names[self.mode.get()], 'airhorn_duration': round(self.duration.get())})
            self.app.apply_preferences(notifications, runtime)
            self.settings_result.configure(text='Saved. Gameplay preferences apply on the next connected poll.')
        except (ValueError, OSError) as error:
            messagebox.showerror('Settings', str(error), parent=self.window)




    def render_deliveries(self, force=False):
        rows = display_rows(self.app.last_status)
        if rows == self.last_rows and not force: return
        self.last_rows = rows
        position, selected = self.delivery_table.yview(), self.delivery_table.selection()
        self.delivery_table.delete(*self.delivery_table.get_children())
        for row in rows:
            if not self.history.get() and row['state'] in ('Delivered', 'Completed', 'Applied', 'Retired'): continue
            self.delivery_table.insert('', 'end', iid=row['key'], values=(
                int(row['key']) + 1 if row['key'].isdecimal() else 'DL', row['item'], row['state'], row['source'], row['reason']))
        if position: self.delivery_table.yview_moveto(position[0])
        if selected and self.delivery_table.exists(selected[0]): self.delivery_table.selection_set(selected)

    def select_delivery(self, _=None):
        selected = self.delivery_table.selection()
        row = next((row for row in self.last_rows or [] if selected and row['key'] == selected[0]), None)
        self.delivery_detail.configure(text=f'{row["item"]} · {row["state"]}: {row["reason"]}' if row
                                       else 'Select a delivery to read its full status.')


    def update(self, status):
        status = status or {}
        self.delivery_summary.configure(text=('Connected' if status.get('connected') else 'Disconnected · last known status')
            + f'  •  Supplies queued: {status.get("queued", 0)}  •  Traps: {status.get("traps", 0)}  •  Held: {status.get("held", 0)}')
        self.render_deliveries()
        slot = status.get('slot_settings') or {}
        if status.get('connected'):
            text = (f'Effective DeathLink: {"Enabled" if status.get("death_link") else "Disabled"}. '
                f'Connected seed trap percentage: {slot.get("airhorn_trap_percentage", 0)}%. '
                f'YAML Airhorn: {slot.get("airhorn_mode", "single_blast")}, {slot.get("airhorn_duration", 60)}s.')
        else:
            text = 'Disconnected — connect to see effective DeathLink and seed settings. Saved preferences apply on connection.'
        self.effective.configure(text=text)
