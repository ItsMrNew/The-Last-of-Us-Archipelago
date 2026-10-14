"""Shared launcher/tracker colours, following the Renegade desktop palette."""
import tkinter as tk
from tkinter import ttk

from .notifications import ITEM_COLOURS, UNKNOWN_ITEM_COLOUR

PALETTES = {
    'dark': dict(bg='#20242b', panel='#2c323c', field='#171b21', fg='#f1f4f8', muted='#a8b0bd',
                 border='#4b5563', accent='#316ea8', selected='#344252',
                 locked='#FF7777', available='#FFB347', complete='#79D991'),
    'light': dict(bg='#f3f5f7', panel='#e4e9ef', field='#ffffff', fg='#202733', muted='#627083',
                  border='#acb7c5', accent='#245f9e', selected='#dce5ef',
                  locked='#AE3030', available='#955500', complete='#237344'),
}
LIGHT_ITEMS = {1: '#7651B0', 2: '#3055B2', 4: '#B43F32', 0: '#007E83'}


class Appearance:
    def __init__(self, root, name='light', on_change=None):
        self.root, self.on_change = root, on_change
        self.choice = tk.StringVar(root, value=(name if isinstance(name, str) and name in PALETTES else 'light').title())
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        self.tables, self.logs, self.combos, self.windows = [], [], [], [root]
        self.apply()

    @property
    def name(self):
        return self.choice.get().lower()

    def selector(self, parent):
        frame = ttk.Frame(parent)
        ttk.Label(frame, text='Theme').pack(side='left', padx=(0, 8))
        field = ttk.Combobox(frame, textvariable=self.choice, values=('Light', 'Dark'), state='readonly', width=8)
        field.pack(side='left')
        field.bind('<<ComboboxSelected>>', self.change)
        self.combos.append(field)
        return frame

    def change(self, _event=None):
        self.apply()
        if self.on_change:
            self.on_change()

    def apply(self):
        p = PALETTES[self.name]
        style = self.style
        style.configure('.', background=p['bg'], foreground=p['fg'], bordercolor=p['border'],
                        lightcolor=p['border'], darkcolor=p['border'], troughcolor=p['field'], focuscolor=p['accent'])
        style.map('.', foreground=[('disabled', p['muted'])])
        style.configure('TButton', background=p['panel'], padding=(10, 5))
        style.map('TButton', background=[('pressed', p['accent']), ('active', p['accent'])],
                  foreground=[('disabled', p['muted']), ('active', '#ffffff')])
        for kind in ('TEntry', 'TSpinbox', 'TCombobox'):
            style.configure(kind, fieldbackground=p['field'], foreground=p['fg'], insertcolor=p['fg'],
                            background=p['panel'], arrowcolor=p['fg'])
            style.map(kind, fieldbackground=[('disabled', p['panel']), ('readonly', p['field'])],
                      foreground=[('disabled', p['muted']), ('readonly', p['fg'])],
                      selectbackground=[('readonly', p['field'])], selectforeground=[('readonly', p['fg'])])
        style.configure('TNotebook', background=p['bg'])
        style.configure('TNotebook.Tab', background=p['panel'], foreground=p['fg'], padding=(12, 6))
        style.map('TNotebook.Tab', background=[('selected', p['field']), ('active', p['selected'])])
        style.configure('Treeview', background=p['field'], fieldbackground=p['field'], foreground=p['fg'], rowheight=26)
        style.map('Treeview', background=[('selected', p['selected'])], foreground=[])
        style.configure('Treeview.Heading', background=p['panel'], foreground=p['fg'], padding=(6, 5))
        style.map('Treeview.Heading', background=[('active', p['panel'])])
        for orient in ('Vertical', 'Horizontal'):
            style.configure(f'{orient}.TScrollbar', background=p['panel'], arrowcolor=p['fg'])
        style.configure('Muted.TLabel', foreground=p['muted'])
        for label, colour in (('Total', 'locked'), ('Logic', 'available'), ('Complete', 'complete'), ('Unknown', 'muted')):
            style.configure(f'{label}.Metric.TLabel', foreground=p[colour], font=('Segoe UI', 11, 'bold'))
        for collection in (self.tables, self.logs, self.combos, self.windows):
            collection[:] = [w for w in collection if w.winfo_exists()]
        for window in self.windows:
            window.configure(background=p['bg'])
        for table in self.tables:
            for tag, colour in (('confirmed', 'complete'), ('waiting', 'available'), ('available', 'available'),
                                ('logic', 'available'), ('locked', 'locked'), ('unknown', 'muted')):
                table.tag_configure(tag, foreground=p[colour])
        for log in self.logs:
            log.configure(background=p['field'], foreground=p['fg'], insertbackground=p['fg'],
                          selectbackground=p['accent'], selectforeground='#ffffff')
            for flag, colour in ITEM_COLOURS:
                log.tag_configure(colour, foreground=colour if self.name == 'dark' else LIGHT_ITEMS[flag])
            log.tag_configure(UNKNOWN_ITEM_COLOUR, foreground=p['muted'])
        for option, value in (('background', p['field']), ('foreground', p['fg']),
                              ('selectBackground', p['accent']), ('selectForeground', '#ffffff')):
            self.root.option_add('*TCombobox*Listbox.' + option, value)
        for combo in self.combos:
            dropdown = self.root.tk.call('ttk::combobox::PopdownWindow', str(combo))
            self.root.tk.call(str(dropdown) + '.f.l', 'configure', '-background', p['field'], '-foreground', p['fg'],
                              '-selectbackground', p['accent'], '-selectforeground', '#ffffff')
