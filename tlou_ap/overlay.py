"""Non-activating, click-through overlay for Windows borderless/windowed play."""
import ctypes as c
from ctypes import wintypes as w
import tkinter as tk

from .notifications import Toast, ToastQueue, mission_lock_toast

KEY = '#010203'
BACKGROUND = '#161C20'
WHITE = '#EDF1F2'
MUTED = '#BAC4CB'


class GameWindow:
    def __init__(self):
        self.user = u = c.WinDLL('user32', use_last_error=True)
        u.GetForegroundWindow.restype = w.HWND
        u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
        u.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]
        u.IsIconic.argtypes = [w.HWND]
        u.GetAncestor.argtypes = [w.HWND, w.UINT]
        u.GetAncestor.restype = w.HWND
        u.GetWindowLongPtrW.argtypes = [w.HWND, c.c_int]
        u.GetWindowLongPtrW.restype = c.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [w.HWND, c.c_int, c.c_ssize_t]
        u.SetWindowLongPtrW.restype = c.c_ssize_t
        u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
        u.GetDpiForWindow.argtypes = [w.HWND]
        u.GetDpiForWindow.restype = w.UINT

    def focused_rect(self, pid):
        if not pid:
            return None
        hwnd, actual = self.user.GetForegroundWindow(), w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, c.byref(actual))
        if actual.value != pid or self.user.IsIconic(hwnd):
            return None
        rect, origin = w.RECT(), w.POINT()
        if not self.user.GetClientRect(hwnd, c.byref(rect)) or not self.user.ClientToScreen(hwnd, c.byref(origin)):
            return None
        if rect.right < 320 or rect.bottom < 240:
            return None
        return origin.x, origin.y, rect.right, rect.bottom, max(96, self.user.GetDpiForWindow(hwnd)) / 96

    def prepare(self, window):
        hwnd = self.user.GetAncestor(window.winfo_id(), 2)  # GA_ROOT: Tk's outer wrapper.
        style = self.user.GetWindowLongPtrW(hwnd, -20)
        # WS_EX_LAYERED | TRANSPARENT | NOACTIVATE | TOOLWINDOW, no APPWINDOW.
        self.user.SetWindowLongPtrW(hwnd, -20, (style | 0x080800A0) & ~0x00040000)
        return hwnd

    def position(self, hwnd, x, y, width, height):
        # HWND_TOPMOST, SWP_NOACTIVATE | SWP_SHOWWINDOW.
        return bool(self.user.SetWindowPos(hwnd, w.HWND(-1), x, y, width, height, 0x0050))


class NotificationCard:
    """Keep the displayed widgets alive while countdown text changes."""
    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=BACKGROUND, highlightthickness=1, highlightbackground='#39444B')
        self.accent = tk.Frame(self.frame)
        self.accent.pack(side='left', fill='y')
        self.body = tk.Frame(self.frame, bg=BACKGROUND)
        self.body.pack(side='left', fill='both', expand=True)
        self.labels = [tk.Label(self.body, bg=BACKGROUND, justify='left', anchor='w') for _ in range(4)]
        self.previous = None

    def update(self, toast, width, scale):
        signature = toast, width, scale
        if signature == self.previous:
            return
        pad = max(9, round(14 * scale))
        layout_changed = self.previous is None or self.previous[1:] != signature[1:]
        if layout_changed:
            self.frame.pack(fill='x', pady=(0, round(8 * scale)))
            self.accent.configure(width=round(3 * scale))
            self.body.pack_configure(padx=pad, pady=pad)
        if self.previous is None or self.previous[0].colour != toast.colour:
            self.accent.configure(bg=toast.colour)
        lines = ((toast.heading, MUTED, 10, 'bold'), (toast.item, toast.colour, 16, 'bold'),
                 (toast.detail, WHITE, 12, 'normal'), (toast.location, MUTED, 10, 'normal'))
        old = self.previous[0] if self.previous else None
        old_text = (old.heading, old.item, old.detail, old.location) if old else ('',) * 4
        repack = layout_changed or tuple(bool(t) for t in old_text) != tuple(bool(line[0]) for line in lines)
        for index, (label, (text, colour, size, weight)) in enumerate(zip(self.labels, lines)):
            if layout_changed:
                label.configure(font=('Segoe UI', -max(1, round(size * scale)), weight),
                                wraplength=width - 2 * pad - round(8 * scale))
            if old is None or old_text[index] != text:
                label.configure(text=text)
            if old is None or index == 1 and old.colour != toast.colour:
                label.configure(fg=colour)
            if repack:
                label.pack_forget()
        if repack:
            for label, (text, *_rest) in zip(self.labels, lines):
                if text:
                    label.pack(fill='x', pady=(0, round(4 * scale)))
        self.previous = signature


class NotificationOverlay:
    def __init__(self, root, window_api=None):
        self.root, self.api = root, window_api or GameWindow()
        self.queue = ToastQueue()
        self.pid, self.blocked = 0, ''
        self.status_card = None
        self.trap_card = None
        self.current = None
        self.visible = False
        self.displayed_transfers = 0
        self.card_views = []
        self.layout_size = None
        self.placement = None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.configure(bg=KEY)
        self.window.attributes('-transparentcolor', KEY)
        self.window.attributes('-alpha', .96)
        self.window.update_idletasks()
        self.hwnd = self.api.prepare(self.window)

    def configure(self, settings):
        self.queue.configure(settings)
        self.current = None

    def add(self, toast):
        if toast.sound:
            from .sound import play_airhorn
            play_airhorn(self.queue.settings['volume'])
        if not toast.sound_only:
            self.queue.add(toast)

    def state(self, pid, blocked='', *, status_card=None, trap_card=None):
        self.pid, self.blocked = pid, blocked
        self.status_card = status_card
        self.trap_card = trap_card

    def cards(self, toasts, width, scale):
        while len(self.card_views) > len(toasts):
            self.card_views.pop().frame.destroy()
        while len(self.card_views) < len(toasts):
            self.card_views.append(NotificationCard(self.window))
        for card, toast in zip(self.card_views, toasts):
            card.update(toast, width, scale)

    def refresh(self):
        rect = self.api.focused_rect(self.pid)
        transfers = self.queue.tick(rect is not None)
        persistent = ()
        if self.trap_card and rect:
            persistent = (self.trap_card,)
        if self.status_card and rect:
            persistent = (self.status_card,) + persistent
        elif self.blocked and rect:
            persistent = (mission_lock_toast(self.blocked),) + persistent
        if not rect or not (persistent or transfers):
            if self.visible:
                self.window.withdraw()
                self.visible = False
                self.placement = None
            return
        x, y, game_width, game_height, scale = rect
        scale = min(scale, game_width / 640, game_height / 540)
        width, margin = min(round(410 * scale), game_width - 24), max(12, round(24 * scale))
        signature = (persistent, transfers, width, scale, game_height)
        if signature != self.current:
            count = len(transfers)
            minimum = 0 if persistent else 1
            # Keep persistent lock/trap guidance readable. Queue overflow cards
            # instead of drawing them outside the game window or aging unseen.
            for _ in range(24):
                self.cards(persistent + transfers[:count], width, scale)
                self.window.update_idletasks()
                height = self.window.winfo_reqheight()
                if height <= game_height - 2 * margin:
                    break
                if count > minimum:
                    count -= 1
                else:
                    scale *= .9
            self.displayed_transfers = count
            self.layout_height = height
            if self.layout_size != (width, height):
                self.window.geometry(f'{width}x{height}')
                self.layout_size = width, height
            self.current = signature
        self.queue.limit_visible(self.displayed_transfers)
        self.window.update_idletasks()
        height = self.layout_height
        # Position while hidden first; showing must not activate or steal focus.
        position = self.queue.settings['position']
        left = x + (margin if position.endswith('left') else max(margin, game_width - width - margin))
        top = y + (margin if position.startswith('top') else max(margin, game_height - height - margin))
        placement = left, top, width, height
        if placement != self.placement or not self.visible:
            self.api.position(self.hwnd, *placement)
            self.placement = placement
        if not self.visible:
            self.window.deiconify()
            self.api.position(self.hwnd, left, top, width, height)
            self.visible = True

    def close(self):
        self.window.destroy()


def previews():
    for heading, item, colour in (
            ('ITEM RECEIVED', 'Progressive Chapter Unlock', '#AF99EF'),
            ('ITEM SENT', 'Useful item', '#6D8BE8'),
            ('ITEM RECEIVED', 'Trap item', '#FA8072'),
            ('ITEM SENT', 'Ammo Supply', '#00EEEE')):
        yield Toast('PREVIEW · ' + heading, item, 'Example Player · display test only',
                    'No item granted or check submitted', colour)
