"""
aioli-screencap -- periodic screen capture, with play / pause / stop.

No network connection. The program only writes:
  - the captures, in the folder you pick;
  - config.json and logs/, in the tool folder.
"""
import ctypes
import datetime
import json
import logging
import math
import os
import queue
import re
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont

try:
    import mss
    from PIL import Image
    # mss >= 10.2: mss.MSS ; mss.mss() is deprecated and will be removed.
    MSS = getattr(mss, "MSS", None) or mss.mss
    IMPORT_ERROR = None
except ImportError as e:  # venv missing or incomplete
    IMPORT_ERROR = e

APP_NAME = "aioli-screencap"
VERSION = "1.3"
SITE = "aiolicollective.com"
REPO = "github.com/aiolicollective/aioli-screencap"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_DIR = os.path.join(APP_DIR, "logs")

UNITS = {"sec": 1, "min": 60, "h": 3600}
# Values written by older versions of config.json
LEGACY_UNITS = {"secondes": "sec", "seconds": "sec", "minutes": "min",
                "heures": "h", "hours": "h"}
FORMATS = ("JPG", "PNG")
MIN_INTERVAL = 1              # seconds
MAX_INTERVAL = 24 * 3600      # 24 h
MAX_CONSECUTIVE_ERRORS = 5    # e.g. disk full: stop cleanly
MAX_RECENT = 8                # recent folders remembered
IDENTIFY_MS = 2000            # how long the screen numbers stay up

# Look: the collective's logo, "> ai.oli/", a terminal prompt in black on white.
# "invert palette" swaps to the dark version. Within a palette every value is
# unique: switching maps each colour to the one with the same role.
PALETTES = {
    "light": {"bg": "#ffffff", "fg": "#111111", "dim": "#8a8a8a", "line": "#d4d4d4",
              "hover": "#efefef", "hover_strong": "#3a3a3a",
              "rec": "#d8402b"},   # the only colour: the recording dot
    "dark":  {"bg": "#111111", "fg": "#f2f2f2", "dim": "#8f8f8f", "line": "#363636",
              "hover": "#242424", "hover_strong": "#cfcfcf",
              "rec": "#ff5a42"},
}
C = dict(PALETTES["light"])   # current palette, read at paint time
COLOR_OPTIONS = ("bg", "fg", "highlightbackground", "highlightcolor", "insertbackground",
                 "selectbackground", "selectforeground", "disabledbackground",
                 "disabledforeground", "activebackground", "activeforeground")
MONO_FAMILIES = ("Cascadia Mono", "JetBrains Mono", "Consolas",
                 "DejaVu Sans Mono", "Courier New")

log = logging.getLogger(APP_NAME)


# ------------------------------------------------------------------ helpers
def setup_logging():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(os.path.join(LOG_DIR, "screencap.log"),
                                      maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
    except OSError:
        logging.basicConfig()
    log.setLevel(logging.INFO)
    sys.excepthook = lambda *exc: log.error("Unhandled error", exc_info=exc)


def enable_dpi_awareness():
    """Captures at real resolution even with Windows display scaling (125 %, 150 %...)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def load_config():
    cfg = {
        "folder": os.path.join(os.path.expanduser("~"), "Pictures", "Captures"),
        "interval": "5",
        "unit": "min",
        "format": "JPG",
        "monitor": 2,
        "session_name": "",
        "recent_folders": [],
        "theme": "light",
    }
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key, default in cfg.items():
                if type(data.get(key)) is type(default):   # ignore badly typed values
                    cfg[key] = data[key]
    except FileNotFoundError:
        pass
    except Exception:
        log.warning("Unreadable config.json, using defaults", exc_info=True)
    cfg["recent_folders"] = [f for f in cfg["recent_folders"] if isinstance(f, str)][:MAX_RECENT]
    cfg["unit"] = LEGACY_UNITS.get(cfg["unit"], cfg["unit"])
    if cfg["unit"] not in UNITS:
        cfg["unit"] = "min"
    if cfg["format"] not in FORMATS:
        cfg["format"] = "JPG"
    if cfg["theme"] not in PALETTES:
        cfg["theme"] = "light"
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)   # atomic write
    except OSError:
        log.warning("Could not save config.json", exc_info=True)


def clean_name(text):
    """Session name usable as a Windows folder name."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text)
    text = re.sub(r"\s+", "_", text.strip()).strip("._")
    return text[:50]


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def fmt_duration(seconds):
    seconds = int(math.ceil(max(0.0, seconds)))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def pick_mono(root):
    available = set(tkfont.families(root))
    for name in MONO_FAMILIES:
        if name in available:
            return name
    return "TkFixedFont"


def make_icon(root):
    """Window icon: the '>' of the logo, in the current palette. Drawn here, no file needed."""
    size, stroke = 32, 4
    img = tk.PhotoImage(master=root, width=size, height=size)
    img.put(C["bg"], to=(0, 0, size, size))
    for i in range(11):
        img.put(C["fg"], to=(7 + i, 5 + i, 7 + i + stroke, 5 + i + stroke))     # upper stroke
        img.put(C["fg"], to=(7 + i, 23 - i, 7 + i + stroke, 23 - i + stroke))   # lower stroke
    return img


# ------------------------------------------------------------------ widgets
class FlatButton(tk.Label):
    """Flat button with a thin outline. A Label, so it looks the same on every system."""

    def __init__(self, parent, text, command, font, primary=False, padx=10, pady=3):
        super().__init__(parent, text=text, font=font, padx=padx, pady=pady,
                         highlightthickness=1, bd=0, cursor="hand2")
        self.command = command
        self.primary = primary
        self.enabled = True
        self.selected = False
        self.hover = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._paint()

    def _set_hover(self, on):
        self.hover = on
        self._paint()

    def _click(self, event):
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if self.enabled and inside and self.command:
            self.command()

    def set_enabled(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._paint()

    def set_selected(self, on):
        self.selected = on
        self._paint()

    def _paint(self):
        if not self.enabled:
            # a selected option stays readable while a session runs
            bg, fg, border = ((C["dim"], C["bg"], C["dim"]) if self.selected
                              else (C["bg"], C["line"], C["line"]))
        elif self.primary or self.selected:
            bg, fg, border = (C["hover_strong"] if self.hover else C["fg"]), C["bg"], C["fg"]
        else:
            bg, fg, border = (C["hover"] if self.hover else C["bg"]), C["fg"], C["fg"]
        self.configure(bg=bg, fg=fg, highlightbackground=border, highlightcolor=border)


class Toggle(tk.Frame):
    """Row of FlatButtons, one selected: [sec] [min] [h]."""

    def __init__(self, parent, options, variable, font, gap):
        super().__init__(parent, bg=C["bg"])
        self.variable = variable
        self.buttons = {}
        for i, (value, label) in enumerate(options):
            b = FlatButton(self, label, lambda v=value: variable.set(v), font, padx=8)
            b.grid(row=0, column=i, padx=(0 if i == 0 else gap, 0))
            self.buttons[value] = b
        variable.trace_add("write", lambda *a: self._paint())
        self._paint()

    def _paint(self):
        for value, b in self.buttons.items():
            b.set_selected(value == self.variable.get())

    def set_enabled(self, on):
        for b in self.buttons.values():
            b.set_enabled(on)


# ------------------------------------------------------------ application
class CaptureApp:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
        root.resizable(False, False)
        root.report_callback_exception = self.on_tk_error
        self.cfg = load_config()
        self.theme = self.cfg["theme"]
        C.update(PALETTES[self.theme])      # before any widget is created
        root.configure(bg=C["bg"])
        self.set_icon()
        self.run_event = threading.Event()    # set = capturing
        self.stop_event = threading.Event()   # set = end of session
        self.snap_event = threading.Event()   # set = "snap" asked for one capture now
        self.msgs = queue.Queue()             # capture thread -> interface
        self.worker = None
        self.state = "stopped"
        self.count = 0
        self.next_capture = None
        self.monitors = []
        self.overlays = []                    # open "identify" windows
        self.overlay_timer = None

        self.folder = tk.StringVar(value=self.cfg["folder"])
        self.interval = tk.StringVar(value=self.cfg["interval"])
        self.unit = tk.StringVar(value=self.cfg["unit"])
        self.fmt = tk.StringVar(value=self.cfg["format"])
        self.session_name = tk.StringVar(value=self.cfg["session_name"])
        self.status = tk.StringVar(value="stopped")
        self.detail = tk.StringVar(value="// ready")

        # Fonts in points (Tk scales them with the display); spacing scaled by hand.
        scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        px = lambda n: int(round(n * scale))
        self.mono = pick_mono(root)
        f_base = (self.mono, 10)
        f_small = (self.mono, 9)
        f_title = (self.mono, 15, "bold")
        f_bold = (self.mono, 10, "bold")
        self.f_base = f_base
        self.setup_styles(f_base)

        f = tk.Frame(root, bg=C["bg"], padx=px(18), pady=px(14))
        f.grid()
        f.columnconfigure(1, weight=1)
        row_pad = {"pady": px(4)}

        def label(text, row):
            tk.Label(f, text=text, font=f_base, bg=C["bg"], fg=C["dim"]).grid(
                row=row, column=0, sticky="w", padx=(0, px(14)), **row_pad)

        def rule(row):
            tk.Frame(f, height=1, bg=C["line"]).grid(row=row, column=0, columnspan=3,
                                                     sticky="ew", pady=px(10))

        # header: "> ai.oli/ screencap"
        head = tk.Frame(f, bg=C["bg"])
        head.grid(row=0, column=0, columnspan=3, sticky="ew")
        head.columnconfigure(1, weight=1)
        tk.Label(head, text="> ai.oli/", font=f_title, bg=C["bg"], fg=C["fg"]).grid(row=0, column=0, sticky="w")
        tk.Label(head, text=" screencap", font=f_title, bg=C["bg"], fg=C["dim"]).grid(row=0, column=1, sticky="w")
        head_right = tk.Frame(head, bg=C["bg"])
        head_right.grid(row=0, column=2, sticky="e")
        # discreet link: light <-> dark
        self.l_theme = tk.Label(head_right, text="invert palette", font=f_small,
                                bg=C["bg"], fg=C["dim"], cursor="hand2")
        self.l_theme.grid(row=0, column=0, padx=(0, px(12)))
        self.l_theme.bind("<Enter>", lambda e: self.l_theme.configure(
            fg=C["fg"], font=(self.mono, 9, "underline")))
        self.l_theme.bind("<Leave>", lambda e: self.l_theme.configure(
            fg=C["dim"], font=f_small))
        self.l_theme.bind("<ButtonRelease-1>", lambda e: self.toggle_theme())
        tk.Label(head_right, text=f"v{VERSION}", font=f_small, bg=C["bg"], fg=C["dim"]).grid(
            row=0, column=1)
        tk.Label(f, text="// periodic screen capture, without taking focus", font=f_small,
                 bg=C["bg"], fg=C["dim"]).grid(row=1, column=0, columnspan=3, sticky="w")
        rule(2)

        # screen
        label("screen", 3)
        self.cb_mon = ttk.Combobox(f, state="readonly", width=34, style="Aioli.TCombobox",
                                   font=f_base)
        self.cb_mon.grid(row=3, column=1, sticky="ew", **row_pad)
        mon_btns = tk.Frame(f, bg=C["bg"])
        mon_btns.grid(row=3, column=2, sticky="w", padx=(px(8), 0))
        self.b_refresh = FlatButton(mon_btns, "↻ refresh", self.load_monitors, f_base)
        self.b_refresh.grid(row=0, column=0)
        self.b_identify = FlatButton(mon_btns, "identify", self.identify, f_base)
        self.b_identify.grid(row=0, column=1, padx=(px(6), 0))

        # folder: recent folders in the list, or type a path
        label("folder", 4)
        self.e_folder = ttk.Combobox(f, textvariable=self.folder, width=34, font=f_base,
                                     style="Aioli.TCombobox", values=self.cfg["recent_folders"])
        self.e_folder.grid(row=4, column=1, sticky="ew", **row_pad)
        self.b_browse = FlatButton(f, "browse…", self.browse, f_base)
        self.b_browse.grid(row=4, column=2, sticky="w", padx=(px(8), 0))

        # session name
        label("session", 5)
        self.e_name = self.entry(f, self.session_name, f_base, width=36)
        self.e_name.grid(row=5, column=1, sticky="ew", **row_pad)
        tk.Label(f, text="// optional", font=f_small, bg=C["bg"], fg=C["dim"]).grid(
            row=5, column=2, sticky="w", padx=(px(8), 0))

        # interval
        label("every", 6)
        every = tk.Frame(f, bg=C["bg"])
        every.grid(row=6, column=1, sticky="w", **row_pad)
        self.e_int = self.entry(every, self.interval, f_base, width=6)
        self.e_int.grid(row=0, column=0, sticky="ns", padx=(0, px(8)))
        self.t_unit = Toggle(every, [(u, u) for u in UNITS], self.unit, f_base, px(4))
        self.t_unit.grid(row=0, column=1)

        # format
        label("format", 7)
        self.t_fmt = Toggle(f, [(x, x.lower()) for x in FORMATS], self.fmt, f_base, px(4))
        self.t_fmt.grid(row=7, column=1, sticky="w", **row_pad)
        rule(8)

        # transport
        btns = tk.Frame(f, bg=C["bg"])
        btns.grid(row=9, column=0, columnspan=3, sticky="w")
        self.b_play = FlatButton(btns, "▶ play", self.play, f_bold, primary=True, padx=16, pady=5)
        self.b_pause = FlatButton(btns, "❚❚ pause", self.pause, f_bold, padx=16, pady=5)
        self.b_stop = FlatButton(btns, "■ stop", self.stop, f_bold, padx=16, pady=5)
        # one capture right now, while recording or paused
        self.b_snap = FlatButton(btns, "◉ snap", self.snap, f_bold, padx=16, pady=5)
        for i, b in enumerate((self.b_play, self.b_pause, self.b_stop, self.b_snap)):
            b.grid(row=0, column=i, padx=(0 if i == 0 else px(8), 0))

        # status: "> stopped" / "● recording · ..."
        st = tk.Frame(f, bg=C["bg"])
        st.grid(row=10, column=0, columnspan=3, sticky="w", pady=(px(12), 0))
        self.l_prompt = tk.Label(st, text=">", font=f_bold, bg=C["bg"], fg=C["fg"])
        self.l_prompt.grid(row=0, column=0)
        tk.Label(st, textvariable=self.status, font=f_base, bg=C["bg"], fg=C["fg"]).grid(
            row=0, column=1, padx=(px(6), 0))
        tk.Label(f, textvariable=self.detail, font=f_small, bg=C["bg"], fg=C["dim"]).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(px(2), 0))
        rule(12)

        tk.Label(f, text=f"{SITE}  ·  {REPO}", font=f_small, bg=C["bg"], fg=C["dim"]).grid(
            row=13, column=0, columnspan=3, sticky="w")

        self.settings = [self.cb_mon, self.b_refresh, self.b_identify, self.e_folder,
                         self.b_browse, self.e_name, self.e_int, self.t_unit, self.t_fmt]
        self.load_monitors()
        self.refresh_ui()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(50, self.set_titlebar)
        root.after(250, self.poll)

    # ---------- look ----------
    def toggle_theme(self):
        self.apply_theme("dark" if self.theme == "light" else "light")

    def apply_theme(self, name):
        """Switches palette on the live window: every colour takes the one with the same role."""
        self.close_overlays()
        swap = {value.lower(): PALETTES[name][role] for role, value in C.items()}
        C.update(PALETTES[name])
        self.theme = name
        self.root.configure(bg=C["bg"])
        self.recolor(self.root, swap)
        self.setup_styles(self.f_base)
        for cb in (self.cb_mon, self.e_folder):
            self.style_popdown(cb)
        self.refresh_ui()
        self.set_icon()
        self.set_titlebar()
        self.cfg["theme"] = name
        save_config(self.cfg)

    def recolor(self, widget, swap):
        for child in widget.winfo_children():
            if isinstance(child, FlatButton):
                child._paint()
            elif not isinstance(child, ttk.Widget):
                for opt in COLOR_OPTIONS:
                    try:
                        value = str(child.cget(opt)).lower()
                    except tk.TclError:   # option not supported by this widget
                        continue
                    if value in swap:
                        child.configure(**{opt: swap[value]})
            self.recolor(child, swap)

    def style_popdown(self, combobox):
        """The drop-down list of a combobox is not a Python widget: coloured through Tcl."""
        try:
            popdown = self.root.tk.call("ttk::combobox::PopdownWindow", combobox)
            self.root.tk.call(f"{popdown}.f.l", "configure",
                              "-background", C["bg"], "-foreground", C["fg"],
                              "-selectbackground", C["fg"], "-selectforeground", C["bg"])
        except tk.TclError:
            log.warning("Could not colour a drop-down list", exc_info=True)

    def set_icon(self):
        try:
            self.icon = make_icon(self.root)
            self.root.iconphoto(True, self.icon)
        except tk.TclError:
            pass

    def set_titlebar(self):
        """Windows 10/11: dark title bar in dark mode. Silent if not available."""
        if sys.platform != "win32":
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1 if self.theme == "dark" else 0)
            # DWMWA_USE_IMMERSIVE_DARK_MODE: 20, or 19 on older Windows 10 builds
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
            # redraw the frame: SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        except Exception:
            log.warning("Could not set the title bar colour", exc_info=True)

    def setup_styles(self, font):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")   # flat theme that respects colours on every system
        except tk.TclError:
            pass
        # clam draws a 3D edge with light/dark colours: set them to the background, flat.
        style.configure("Aioli.TCombobox", font=font, padding=3, foreground=C["fg"],
                        fieldbackground=C["bg"], background=C["bg"], bordercolor=C["line"],
                        lightcolor=C["bg"], darkcolor=C["bg"], troughcolor=C["bg"],
                        selectbackground=C["bg"], selectforeground=C["fg"], arrowcolor=C["fg"])
        # These maps replace the ones inherited from clam (blue field when focused).
        style.map("Aioli.TCombobox",
                  fieldbackground=[("disabled", C["bg"]), ("readonly", C["bg"])],
                  foreground=[("disabled", C["dim"]), ("readonly", C["fg"])],
                  background=[("disabled", C["bg"]), ("pressed", C["hover"]), ("active", C["hover"])],
                  arrowcolor=[("disabled", C["line"])],
                  bordercolor=[("disabled", C["line"]), ("focus", C["fg"]), ("hover", C["fg"])],
                  selectbackground=[("focus", C["bg"])],
                  selectforeground=[("focus", C["fg"])])
        style.configure("ComboboxPopdownFrame", bordercolor=C["fg"])
        o = self.root.option_add
        o("*TCombobox*Listbox.font", font)
        o("*TCombobox*Listbox.background", C["bg"])
        o("*TCombobox*Listbox.foreground", C["fg"])
        o("*TCombobox*Listbox.selectBackground", C["fg"])
        o("*TCombobox*Listbox.selectForeground", C["bg"])
        o("*TCombobox*Listbox.borderWidth", 0)

    @staticmethod
    def entry(parent, variable, font, width):
        return tk.Entry(parent, textvariable=variable, font=font, width=width,
                        relief="flat", bd=4, bg=C["bg"], fg=C["fg"], insertbackground=C["fg"],
                        selectbackground=C["fg"], selectforeground=C["bg"],
                        disabledbackground=C["bg"], disabledforeground=C["dim"],
                        highlightthickness=1, highlightbackground=C["line"], highlightcolor=C["fg"])

    # ---------- interface ----------
    def load_monitors(self):
        with MSS() as sct:
            self.monitors = sct.monitors[1:]   # [0] = all screens combined
        labels = [f"screen {i + 1} · {m['width']}x{m['height']} · at {m['left']},{m['top']}"
                  for i, m in enumerate(self.monitors)]
        # Keep the screen already chosen; at startup, the one from the settings.
        wanted = self.cb_mon.current() + 1 if self.cb_mon.current() >= 0 else self.cfg.get("monitor", 2)
        self.cb_mon.configure(values=labels)
        self.cb_mon.current(min(max(wanted, 1), len(labels)) - 1)

    def identify(self):
        """Shows each screen's number at its centre for IDENTIFY_MS milliseconds."""
        self.close_overlays()
        chosen = self.cb_mon.current()
        for i, m in enumerate(self.monitors):
            size = max(120, min(m["width"], m["height"]) // 3)
            x = m["left"] + (m["width"] - size) // 2
            y = m["top"] + (m["height"] - size) // 2
            color = C["bg"] if i == chosen else C["dim"]   # the chosen screen stands out
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)            # no title bar
            w.attributes("-topmost", True)
            w.configure(background=C["fg"], highlightthickness=4, highlightbackground=color)
            w.geometry(f"{size}x{size}+{x}+{y}")
            lbl = tk.Label(w, text=str(i + 1), fg=color, bg=C["fg"],
                           font=(self.mono, -int(size * 0.6), "bold"))
            lbl.place(relx=0.5, rely=0.5, anchor="center")
            for widget in (w, lbl):
                widget.bind("<Button-1>", lambda e: self.close_overlays())
            self.overlays.append(w)
        self.overlay_timer = self.root.after(IDENTIFY_MS, self.close_overlays)

    def close_overlays(self):
        """Closes the screen numbers. Returns True if some were shown."""
        was_open = bool(self.overlays)
        if self.overlay_timer is not None:
            self.root.after_cancel(self.overlay_timer)
            self.overlay_timer = None
        for w in self.overlays:
            try:
                w.destroy()
            except tk.TclError:   # already closed
                pass
        self.overlays = []
        return was_open

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get() or os.path.expanduser("~"))
        if d:
            self.folder.set(os.path.normpath(d))

    def current_settings(self):
        return {"folder": self.folder.get().strip(), "interval": self.interval.get().strip(),
                "unit": self.unit.get(), "format": self.fmt.get(),
                "session_name": self.session_name.get().strip(),
                "monitor": self.cb_mon.current() + 1, "theme": self.theme}

    def refresh_ui(self):
        stopped = self.state == "stopped"
        for w in self.settings:
            if isinstance(w, (FlatButton, Toggle)):
                w.set_enabled(stopped)
            elif w is self.e_folder:   # editable combobox
                w.configure(state="normal" if stopped else "disabled")
            elif isinstance(w, ttk.Combobox):
                w.configure(state="readonly" if stopped else "disabled")
            else:
                w.configure(state="normal" if stopped else "disabled")
        self.b_play.set_enabled(self.state != "running")
        self.b_pause.set_enabled(self.state == "running")
        self.b_stop.set_enabled(not stopped)
        self.b_snap.set_enabled(not stopped)
        if self.state == "running":
            self.l_prompt.configure(text="●", fg=C["rec"])
        elif self.state == "paused":
            self.l_prompt.configure(text="●", fg=C["dim"])
        else:
            self.l_prompt.configure(text=">", fg=C["fg"])

    def play(self):
        # Never a screen number on a capture: if some were shown, give the
        # screen time to redraw before the first image.
        start_delay = 0.5 if self.close_overlays() else 0.0
        if self.state == "paused":
            self.state = "running"
            self.run_event.set()
            self.refresh_ui()
            return

        try:
            value = float(self.interval.get().replace(",", ".").strip())
            seconds = value * UNITS[self.unit.get()]
        except (ValueError, KeyError):
            seconds = -1
        if not MIN_INTERVAL <= seconds <= MAX_INTERVAL:
            messagebox.showerror("Invalid interval",
                                 "Pick an interval between 1 second and 24 hours.")
            return

        base = self.folder.get().strip()
        if not base:
            messagebox.showerror("No folder", "Pick a destination folder.")
            return
        base = os.path.abspath(os.path.expanduser(base))
        name = clean_name(self.session_name.get()) or "session"
        session = f"{name}_{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}"
        folder = os.path.join(base, session)
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, ".write_test")
            with open(probe, "w") as fh:
                fh.write("ok")
            os.remove(probe)
        except OSError as e:
            messagebox.showerror("Folder not writable", f"Cannot write to:\n{folder}\n\n{e}")
            return

        recent = [base] + [d for d in self.cfg["recent_folders"] if not same_path(d, base)]
        self.cfg["recent_folders"] = recent[:MAX_RECENT]
        self.e_folder.configure(values=self.cfg["recent_folders"])
        self.folder.set(base)
        self.cfg.update(self.current_settings())
        save_config(self.cfg)

        self.count = 0
        self.next_capture = None
        # New event for every session: a stop followed by an immediate play
        # cannot wake up the previous capture thread.
        self.stop_event = threading.Event()
        self.snap_event.clear()
        self.run_event.set()
        self.state = "running"
        self.detail.set(f"// folder: {session}")
        self.worker = threading.Thread(
            target=self.loop,
            args=(self.cb_mon.current(), seconds, self.fmt.get(), folder, self.stop_event,
                  start_delay),
            daemon=True)
        self.worker.start()
        log.info("Session started: screen %s, %s s, %s, %s",
                 self.cb_mon.current() + 1, seconds, self.fmt.get(), folder)
        self.refresh_ui()

    def snap(self):
        """One extra capture now, in the session folder. The schedule does not move."""
        if self.state != "stopped":
            self.snap_event.set()

    def pause(self):
        self.run_event.clear()
        self.state = "paused"
        self.refresh_ui()

    def stop(self):
        if self.state != "stopped":
            log.info("Session stopped after %s capture(s)", self.count)
        self.stop_event.set()
        self.run_event.set()   # unblock the thread if it was paused
        self.state = "stopped"
        self.next_capture = None
        self.status.set(f"stopped · {plural(self.count, 'capture')} saved")
        self.refresh_ui()

    def poll(self):
        while True:
            try:
                kind, data = self.msgs.get_nowait()
            except queue.Empty:
                break
            if kind == "ok":
                self.detail.set(f"// last: {os.path.basename(data)}")
            elif kind == "snap":
                self.detail.set(f"// snap: {os.path.basename(data)}")
            elif kind == "err":
                self.detail.set(f"// error: {data}")
            elif kind == "fatal":
                self.stop()
                messagebox.showerror("Capture stopped", data)

        if self.state == "running":
            text = f"recording · {plural(self.count, 'capture')}"
            if self.next_capture is not None:
                text += f" · next in {fmt_duration(self.next_capture - time.monotonic())}"
            self.status.set(text)
        elif self.state == "paused":
            self.status.set(f"paused · {plural(self.count, 'capture')}")
        self.root.after(250, self.poll)

    def on_tk_error(self, exc, val, tb):
        log.error("Interface error", exc_info=(exc, val, tb))
        messagebox.showerror("Error", f"{val}\n\nDetails: logs\\screencap.log")

    def on_close(self):
        self.stop()
        if self.worker is not None:
            self.worker.join(timeout=3)   # let a write in progress finish
        self.cfg.update(self.current_settings())
        save_config(self.cfg)
        self.root.destroy()

    # ---------- capture (separate thread) ----------
    def loop(self, mon_index, interval, fmt, folder, stop_event, start_delay):
        try:
            self.capture_loop(mon_index, interval, fmt, folder, stop_event, start_delay)
        except Exception as e:   # otherwise the thread dies and the interface stays on "recording"
            log.error("Capture thread interrupted", exc_info=True)
            if not stop_event.is_set():
                self.msgs.put(("fatal", f"Capture interrupted.\n\n{e}"))

    def capture_loop(self, mon_index, interval, fmt, folder, stop_event, start_delay):
        errors = 0
        with MSS() as sct:
            if mon_index + 1 >= len(sct.monitors):
                self.msgs.put(("fatal", "This screen is no longer detected. Click ↻ refresh."))
                return
            mon = sct.monitors[mon_index + 1]
            next_t = time.monotonic() + start_delay   # 1st capture: right away, or after identify
            while not stop_event.is_set():
                if self.snap_event.is_set():     # "snap": one capture now, schedule unchanged
                    self.snap_event.clear()
                    tag = "snap"
                elif not self.run_event.is_set():  # paused
                    self.next_capture = None
                    self.run_event.wait(0.1)
                    next_t = time.monotonic()    # capture as soon as it resumes
                    continue
                else:
                    now = time.monotonic()
                    self.next_capture = next_t
                    if now < next_t:
                        stop_event.wait(min(next_t - now, 0.1))
                        continue
                    next_t = max(next_t + interval, now)
                    tag = ""
                try:
                    self.save_capture(sct, mon, fmt, folder, tag)
                    errors = 0
                except Exception as e:
                    errors += 1
                    log.error("Capture failed", exc_info=True)
                    self.msgs.put(("err", str(e)))
                    if errors >= MAX_CONSECUTIVE_ERRORS:
                        self.msgs.put(("fatal", f"{errors} failures in a row, capture stopped.\n\n{e}"))
                        return

    def save_capture(self, sct, mon, fmt, folder, tag):
        """Grabs the screen and writes one numbered file; a snap gets a _snap suffix."""
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        ext = ".png" if fmt == "PNG" else ".jpg"
        suffix = f"_{tag}" if tag else ""
        path = os.path.join(folder, f"{stamp}_{self.count + 1:05d}{suffix}{ext}")
        if fmt == "PNG":
            img.save(path, compress_level=1)   # fast compression
        else:
            img.save(path, quality=90)
        self.count += 1
        self.msgs.put(("snap" if tag else "ok", path))


def main():
    setup_logging()
    if IMPORT_ERROR is not None:
        log.error("Missing dependency: %s", IMPORT_ERROR)
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, f"Missing dependency ({IMPORT_ERROR}).\n\n"
                                       "Run setup.bat, then try again.")
        return
    enable_dpi_awareness()
    root = tk.Tk()
    CaptureApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
