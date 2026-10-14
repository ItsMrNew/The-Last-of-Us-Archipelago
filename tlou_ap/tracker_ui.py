"""Shared, read-only campaign tree for the launcher and enlarged tracker."""
import tkinter as tk
from tkinter import ttk

from .tracker import CHECK_TYPES, campaign_missions, check_status, metrics
from .theme import Appearance


class MetricStrip(ttk.Frame):
    def __init__(self, parent, columns=3):
        super().__init__(parent)
        self.labels = {}
        for index, (key, text, style) in enumerate(metrics(None)):
            label = ttk.Label(self, text=text, style=f'{style}.Metric.TLabel')
            label.grid(row=index // columns, column=index % columns, sticky='w', padx=(0, 22), pady=4)
            self.labels[key] = label

    def update(self, view):
        for key, text, style in metrics(view):
            self.labels[key].configure(text=text, style=f'{style}.Metric.TLabel')


class CampaignTracker(ttk.Frame):
    def __init__(self, parent, appearance):
        super().__init__(parent)
        self.view = None
        self.rows = ()
        self._ids = set()
        self._search_open = None
        self._current = None
        self.search = tk.StringVar(self)
        self.hide_completed = tk.BooleanVar(self, value=False)
        self.categories = {kind: tk.BooleanVar(self, value=True) for kind in CHECK_TYPES}
        filters = ttk.Frame(self); filters.pack(fill='x', pady=(0, 7))
        ttk.Label(filters, text='Campaign missions', font=('Segoe UI', 11, 'bold')).pack(side='left', padx=(0, 14))
        ttk.Label(filters, text='Search').pack(side='left', padx=(0, 6))
        ttk.Entry(filters, textvariable=self.search, width=19).pack(side='left', fill='x', expand=True, padx=(0, 10))
        ttk.Checkbutton(filters, text='Hide completed', variable=self.hide_completed,
                        command=self.render).pack(side='left', padx=(0, 8))
        for kind, label in (('mission', 'Missions'), ('chapter', 'Chapters'), ('collectible', 'Collectibles')):
            ttk.Checkbutton(filters, text=label, variable=self.categories[kind], command=self.render).pack(side='left', padx=(0, 5))
        ttk.Button(filters, text='Reset', command=self.reset_filters).pack(side='right', padx=(5, 0))
        frame = ttk.Frame(self)
        self.table = ttk.Treeview(frame, columns=('status', 'checks'), show='tree headings', selectmode='browse', height=12)
        self.table.heading('#0', text='Mission / check')
        self.table.column('#0', width=650, minwidth=360)
        self.table.heading('status', text='Status'); self.table.column('status', width=125, minwidth=110, stretch=False)
        self.table.heading('checks', text='Checks'); self.table.column('checks', width=75, minwidth=65, stretch=False)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.table.pack(side='left', fill='both', expand=True)
        appearance.tables.append(self.table)
        self.detail = ttk.Label(self, text='Connect to a run to see its missions and checks.', wraplength=880)
        self.count = ttk.Label(self, text='Expand a mission to view its checks.', style='Muted.TLabel')
        self.count.pack(side='bottom', anchor='w', pady=(3, 0))
        self.detail.pack(side='bottom', fill='x', pady=(7, 0))
        frame.pack(fill='both', expand=True)
        self.bind('<Configure>', lambda event: self.detail.configure(wraplength=max(300, event.width - 8)))
        self.table.bind('<<TreeviewSelect>>', self.selection_changed)
        self.search.trace_add('write', self.render)

    def clear(self):
        for iid in self._ids:
            if self.table.exists(iid): self.table.delete(iid)
        self._ids.clear()
        self._search_open = None
        self._current = None

    def update(self, view):
        if view == self.view: return
        if view is None or self.view is None or view.identity != self.view.identity: self.clear()
        self.view = view
        self.render()

    def reset_filters(self):
        self.hide_completed.set(False)
        for variable in self.categories.values(): variable.set(True)
        self.search.set('')
        self.render()

    def render(self, *_):
        position, selected = self.table.yview(), self.table.selection()
        query = self.search.get().strip()
        if query and self._search_open is None:
            self._search_open = {iid for iid in self._ids if iid.startswith('m:') and self.table.item(iid, 'open')}
        elif not query and self._search_open is not None:
            for iid in self._ids:
                if iid.startswith('m:'): self.table.item(iid, open=iid in self._search_open)
            self._search_open = None
        self.rows = campaign_missions(self.view, search=query, hide_completed=self.hide_completed.get(),
            categories=[kind for kind, variable in self.categories.items() if variable.get()])
        # Detaching filtered rows preserves expansion and selection across live updates.
        for iid in self._ids: self.table.detach(iid)
        visible = set()
        for row in self.rows:
            iid = f'm:{row.index}'
            title = f'{row.index + 1:02} · {row.name} — {row.chapter}'
            if row.current: title = '▶ ' + title
            values = (row.status, f'{row.confirmed}/{row.total}')
            if not self.table.exists(iid): self.table.insert('', 'end', iid=iid)
            self.table.item(iid, text=title, values=values, tags=(row.tag,))
            self.table.move(iid, '', 'end'); visible.add(iid)
            if query or (row.current and row.index != self._current): self.table.item(iid, open=True)
            for check in row.checks:
                child = f'c:{check.id}'
                status, tag = check_status(self.view, check)
                name = ('Complete mission' if check.category == 'mission' else
                        f'Complete chapter: {row.chapter}' if check.category == 'chapter' else
                        check.name.removeprefix(f'{row.chapter} - {row.name} - '))
                if not self.table.exists(child): self.table.insert(iid, 'end', iid=child)
                self.table.item(child, text=name, values=(status, '1/1' if check.status == 'Confirmed' else '0/1'), tags=(tag,))
                self.table.move(child, iid, 'end'); visible.add(child)
        self._ids |= visible
        if self.view: self._current = next((m.index for m in self.view.missions if m.current), None)
        if selected:
            if selected[0] in visible: self.table.selection_set(selected)
            else: self.table.selection_remove(selected)
        if position: self.table.yview_moveto(position[0])
        total = len(self.view.checks) if self.view else 0
        self.count.configure(text=f'Showing {sum(len(row.checks) for row in self.rows)} of {total} enabled checks · '
                                  'Collectibles follow suggested pickup order.' if self.view else 'Expand a mission to view its checks.')
        self.selection_changed()

    def selection_changed(self, _event=None):
        selected = self.table.selection()
        iid = selected[0] if selected else ''
        text = 'Select a mission or check for access requirements. Orange = available / in logic · Red = locked · Green = complete.'
        if self.view is None:
            text = 'Connect to a run to see its missions and checks.'
        elif not (self.view.connected and self.view.synchronized):
            text = 'Access is unknown until the client reconnects and synchronizes items. Displayed progress is last known.'
        elif iid.startswith('c:'):
            check = next((c for c in self.view.checks if iid == f'c:{c.id}'), None)
            if check: text = check.name + '\n' + check.requirement
        elif iid.startswith('m:'):
            mission = next((m for m in campaign_missions(self.view) if iid == f'm:{m.index}'), None)
            if mission:
                requirement = next((c.requirement for c in mission.checks if c.status == 'Remaining'), '')
                if not requirement:
                    requirement = ('Waiting for server acknowledgement.' if mission.status == 'Pending sync' else
                                   'Every enabled check in this mission is complete.' if mission.total else
                                   'No checks are enabled for this mission. It still follows chapter unlocks and story order.')
                text = f'{mission.chapter} · {mission.name} — {mission.confirmed}/{mission.total} checks confirmed.\n{requirement}'
        self.detail.configure(text=text)


class TrackerWindow:
    def __init__(self, root, appearance=None):
        self.view = None
        self.appearance = appearance or Appearance(root)
        self.window = tk.Toplevel(root)
        self.window.title('Archipelago • Campaign tracker')
        self.window.geometry('1100x760'); self.window.minsize(960, 600)
        self.appearance.windows.append(self.window)
        frame = ttk.Frame(self.window, padding=18); frame.pack(fill='both', expand=True)
        header = ttk.Frame(frame); header.pack(fill='x', pady=(0, 8))
        ttk.Label(header, text='CAMPAIGN TRACKER', font=('Segoe UI', 18, 'bold')).pack(side='left')
        self.appearance.selector(header).pack(side='right')
        self.metrics = MetricStrip(frame); self.metrics.pack(fill='x')
        self.context = ttk.Label(frame, text='Connect to a run to see its checks.')
        self.context.pack(anchor='w', pady=(6, 0))
        self.next = ttk.Label(frame, text=''); self.next.pack(anchor='w', pady=(6, 0))
        self.death = ttk.Label(frame, text=''); self.death.pack(anchor='w', pady=(6, 12))
        self.campaign = CampaignTracker(frame, self.appearance); self.campaign.pack(fill='both', expand=True)
        self.appearance.apply()

    def update(self, view):
        if view == self.view: return
        self.view = view
        self.metrics.update(view)
        self.campaign.update(view)
        if view is None:
            self.context.configure(text='Connect to a run to see its checks.')
            self.next.configure(text=''); self.death.configure(text='')
            return
        identity = dict(view.identity)
        state = 'Connected' if view.connected else 'Disconnected — last known progress'
        self.context.configure(text=f"{state} · Seed {identity['seed']} · Team {identity['team']} / Slot {identity['slot']}")
        self.next.configure(text=view.next_unlock if view.connected else 'Reconnect to refresh chapter unlocks and mission access.')
        self.death.configure(text=view.death)
