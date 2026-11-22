"""A small widget that sits on the Windows taskbar, next to the system tray,
and shows the battery level of a wireless mouse."""

import ctypes
import threading
import tkinter as tk
import winreg
from ctypes import wintypes

from battery_checker.providers.steelseries import SteelSeriesProvider

REFRESH_SECONDS = 60
TICK_MS = 100
LAYOUT_EVERY = 10
SAMPLE_EVERY = 20
FULLSCREEN_TICKS = 3
LOW_LEVEL = 20
MOUSE_GLYPH = ""
MARGIN_Y = 4 
GAP_X = 2
DEBUG = True

HOVER_DARK = 0.06
HOVER_LIGHT = 0.04

SHELL_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
    "ControlCenterWindow", "TopLevelWindowForOverflowXamlIsland",
    "NotifyIconOverflowWindow", "TaskListThumbnailWnd", "MultitaskingViewFrame",
    "ForegroundStaging", "TkTopLevel", "#32768",
}

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.GetPixel.restype = wintypes.DWORD
gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]

GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
GW_HWNDPREV = 3
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUNDSMALL = 3
DWMWA_COLOR_NONE = 0xFFFFFFFE


def log(*args):
    if DEBUG:
        print(*args, flush=True)


def get_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_taskbar():
    """Returns (taskbar handle, taskbar rect, tray rect) or None."""
    taskbar = user32.FindWindowW("Shell_TrayWnd", None)
    if not taskbar:
        return None
    tray = user32.FindWindowExW(taskbar, None, "TrayNotifyWnd", None)
    if not tray:
        return None
    return taskbar, get_rect(taskbar), get_rect(tray)


def taskbar_is_light():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
        return value == 1
    except OSError:
        return False


def sample_color(x, y):
    """Average color of 3 pixels around (x, y), as (r, g, b)."""
    hdc = user32.GetDC(None)
    pixels = []
    for dy in (-6, 0, 6):
        c = gdi32.GetPixel(hdc, x, y + dy)
        if c != 0xFFFFFFFF:
            pixels.append((c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF))
    user32.ReleaseDC(None, hdc)
    if not pixels:
        return None
    return tuple(sum(p[i] for p in pixels) // len(pixels) for i in range(3))


def blend(rgb, target, amount):
    """Mixes `amount` (0..1) of `target` into `rgb`."""
    return tuple(round(c + (t - c) * amount) for c, t in zip(rgb, target))


def to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def covered_by(hwnd, other):
    """True if window `other` is above our window in the z-order."""
    above = user32.GetWindow(hwnd, GW_HWNDPREV)
    steps = 0
    while above and steps < 500:
        if above == other:
            return True
        above = user32.GetWindow(above, GW_HWNDPREV)
        steps += 1
    return False


def fullscreen_app_running(own_hwnd):
    """True if the active window covers the whole monitor (game, fullscreen video, F11)."""
    fg = user32.GetForegroundWindow()
    if not fg or fg == own_hwnd or class_name(fg) in SHELL_CLASSES:
        return False
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    monitor = user32.MonitorFromWindow(fg, 2)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    w, m = get_rect(fg), info.rcMonitor
    return w.left <= m.left and w.top <= m.top and w.right >= m.right and w.bottom >= m.bottom


class TaskbarWidget:
    def __init__(self):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)

        self.provider = SteelSeriesProvider()
        self.level = None
        self.charging = False
        self.device_name = "No device found"

        self.light = taskbar_is_light()
        self.fg = "#000000" if self.light else "#ffffff"
        self.bg_rgb = None
        self.hovered = False
        self.menu_open = False
        self.hidden = False
        self.last_geometry = None
        self.last_render = None
        self.owner = None
        self.ticks = 0
        self.fullscreen_ticks = 0

        self.stop_event = threading.Event()
        self.wake_event = threading.Event()

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        self.frame = tk.Frame(self.root)
        self.frame.pack(expand=True)
        self.icon_label = tk.Label(self.frame, text=MOUSE_GLYPH,
                                   font=("Segoe Fluent Icons", 12))
        self.icon_label.pack(side="left", padx=(8, 4))
        self.text_label = tk.Label(self.frame, text="?", font=("Segoe UI", 10))
        self.text_label.pack(side="left", padx=(0, 8))

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label=self.device_name, state="disabled")
        self.menu.add_separator()
        self.menu.add_command(label="Refresh", command=self.refresh_now)
        self.menu.add_command(label="Quit", command=self.quit)

        self.root.bind("<Enter>", self.on_enter)
        self.root.bind("<Leave>", self.on_leave)
        self.root.bind("<Button-3>", self.on_right_click)

        self.render(force=True)
        self.root.update_idletasks()
        self.hwnd = user32.GetParent(self.root.winfo_id())

        ex = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

        self.set_dwm_attribute(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUNDSMALL)
        self.set_dwm_attribute(DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE)

    def set_dwm_attribute(self, attribute, value):
        v = ctypes.c_uint(value)
        dwmapi.DwmSetWindowAttribute(self.hwnd, attribute, ctypes.byref(v), ctypes.sizeof(v))

    def battery_loop(self):
        while not self.stop_event.is_set():
            devices = self.provider.scan()
            if devices:
                d = devices[0]
                self.level, self.charging, self.device_name = d.level, d.charging, d.name
            else:
                self.level, self.charging, self.device_name = None, False, "No device found"
            self.wake_event.wait(REFRESH_SECONDS)
            self.wake_event.clear()

    def tick(self):
        if self.stop_event.is_set():
            return
        self.root.after(TICK_MS, self.tick)
        if self.menu_open:
            return
        self.ticks += 1

        found = find_taskbar()
        if found is None:
            self.hide("taskbar not found")
            return

        if fullscreen_app_running(self.hwnd):
            self.fullscreen_ticks += 1
        else:
            self.fullscreen_ticks = 0
        if self.fullscreen_ticks >= FULLSCREEN_TICKS:
            self.hide("fullscreen: " + class_name(user32.GetForegroundWindow()))
            return

        taskbar, tb, tr = found
        self.show()

        if taskbar != self.owner:
            user32.SetWindowLongPtrW(self.hwnd, GWLP_HWNDPARENT, taskbar)
            self.owner = taskbar

        if covered_by(self.hwnd, taskbar):
            log("covered by the taskbar, moving back on top")
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        if self.ticks % LAYOUT_EVERY == 1:
            self.place(tb, tr)
        if self.bg_rgb is None or self.ticks % SAMPLE_EVERY == 2:
            self.update_background()
        self.render()

    def place(self, tb, tr):
        width = self.root.winfo_reqwidth()
        height = (tb.bottom - tb.top) - 2 * MARGIN_Y
        x = tr.left - width - GAP_X
        y = tb.top + MARGIN_Y
        geometry = (x, y, width, height)
        if geometry != self.last_geometry:
            self.root.geometry(f"{width}x{height}+{x}+{y}")
            self.last_geometry = geometry

    def update_background(self):
        """Matches the background to the taskbar by sampling pixels right next to the widget."""
        if self.hovered or self.last_geometry is None:
            return
        x, y, _, height = self.last_geometry
        rgb = sample_color(x - 3, y + height // 2)
        if rgb is None:
            return
        if self.bg_rgb is None or sum(abs(a - b) for a, b in zip(rgb, self.bg_rgb)) > 4:
            self.bg_rgb = rgb

    def render(self, force=False):
        if self.level is None:
            text, fg = "?", self.fg
        else:
            text = f"{self.level}%"
            fg = "#e64646" if self.level <= LOW_LEVEL and not self.charging else self.fg
            if self.charging:
                text += " +"

        base = self.bg_rgb or ((243, 243, 243) if self.light else (28, 28, 28))
        if self.hovered:
            base = blend(base, (0, 0, 0), HOVER_LIGHT) if self.light \
                else blend(base, (255, 255, 255), HOVER_DARK)
        bg = to_hex(base)

        state = (text, fg, bg, self.device_name)
        if state == self.last_render and not force:
            return
        self.last_render = state

        self.text_label.config(text=text, fg=fg, bg=bg)
        self.icon_label.config(fg=self.fg, bg=bg)
        self.frame.config(bg=bg)
        self.root.config(bg=bg)
        self.menu.entryconfig(0, label=self.device_name)

    def show(self):
        if self.hidden:
            log("showing")
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.hidden = False

    def hide(self, reason=""):
        if not self.hidden:
            log("hiding:", reason)
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.hidden = True

    def on_enter(self, event):
        self.hovered = True
        self.render()

    def on_leave(self, event):
        if self.root.winfo_containing(event.x_root, event.y_root) is None:
            self.hovered = False
            self.render()

    def on_right_click(self, event):
        self.menu_open = True
        user32.SetForegroundWindow(self.hwnd)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu_open = False
            if not self.stop_event.is_set():
                self.menu.grab_release()
                self.update_hover()

    def update_hover(self):
        """After the menu closes, check whether the cursor is still over the widget."""
        x, y = self.root.winfo_pointerxy()
        self.hovered = self.root.winfo_containing(x, y) is not None
        self.render()

    def refresh_now(self):
        self.wake_event.set()

    def quit(self):
        self.stop_event.set()
        self.wake_event.set()
        self.root.destroy()

    def run(self):
        threading.Thread(target=self.battery_loop, daemon=True).start()
        self.root.after(0, self.tick)
        self.root.mainloop()
