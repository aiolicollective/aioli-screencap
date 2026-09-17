"""
aioli-screencap -- capture periodique d'un ecran, avec Play / Pause / Stop.

Aucune connexion reseau. Le programme n'ecrit que :
  - les captures, dans le dossier que tu choisis ;
  - config.json et logs/, dans le dossier de l'outil.
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

try:
    import mss
    from PIL import Image
    IMPORT_ERROR = None
except ImportError as e:  # venv absent ou incomplet
    IMPORT_ERROR = e

APP_NAME = "aioli-screencap"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_DIR = os.path.join(APP_DIR, "logs")

UNITS = {"secondes": 1, "minutes": 60, "heures": 3600}
MIN_INTERVAL = 1              # secondes
MAX_INTERVAL = 24 * 3600      # 24 h
MAX_CONSECUTIVE_ERRORS = 5    # ex. disque plein : on arrete proprement
MAX_RECENT = 8                # dossiers recents memorises

log = logging.getLogger(APP_NAME)


# ------------------------------------------------------------------ outils
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
    sys.excepthook = lambda *exc: log.error("Erreur non geree", exc_info=exc)


def enable_dpi_awareness():
    """Captures en resolution reelle meme avec une mise a l'echelle Windows (125 %, 150 %...)."""
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
        "unit": "minutes",
        "format": "JPG",
        "monitor": 2,
        "session_name": "",
        "recent_folders": [],
    }
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key, default in cfg.items():
                if type(data.get(key)) is type(default):   # on ignore les valeurs mal typees
                    cfg[key] = data[key]
    except FileNotFoundError:
        pass
    except Exception:
        log.warning("config.json illisible, valeurs par defaut utilisees", exc_info=True)
    cfg["recent_folders"] = [f for f in cfg["recent_folders"] if isinstance(f, str)][:MAX_RECENT]
    if cfg["unit"] not in UNITS:
        cfg["unit"] = "minutes"
    if cfg["format"] not in ("JPG", "PNG"):
        cfg["format"] = "JPG"
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)   # ecriture atomique
    except OSError:
        log.warning("Impossible d'enregistrer config.json", exc_info=True)


def clean_name(text):
    """Nom de session utilisable comme nom de dossier Windows."""
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


# ------------------------------------------------------------ application
class CaptureApp:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
        root.resizable(False, False)
        root.report_callback_exception = self.on_tk_error

        self.cfg = load_config()
        self.run_event = threading.Event()    # active = capture en cours
        self.stop_event = threading.Event()   # active = fin de session
        self.msgs = queue.Queue()             # thread de capture -> interface
        self.worker = None
        self.state = "stopped"
        self.count = 0
        self.next_capture = None
        self.monitors = []

        self.folder = tk.StringVar(value=self.cfg["folder"])
        self.interval = tk.StringVar(value=self.cfg["interval"])
        self.unit = tk.StringVar(value=self.cfg["unit"])
        self.fmt = tk.StringVar(value=self.cfg["format"])
        self.session_name = tk.StringVar(value=self.cfg["session_name"])
        self.status = tk.StringVar(value="Arrêté")
        self.detail = tk.StringVar(value="")

        pad = {"padx": 8, "pady": 4}
        f = ttk.Frame(root, padding=10)
        f.grid()

        ttk.Label(f, text="Écran :").grid(row=0, column=0, sticky="w", **pad)
        self.cb_mon = ttk.Combobox(f, state="readonly", width=38)
        self.cb_mon.grid(row=0, column=1, sticky="w", **pad)
        self.b_refresh = ttk.Button(f, text="↻ Écrans", command=self.load_monitors)
        self.b_refresh.grid(row=0, column=2, **pad)

        ttk.Label(f, text="Dossier :").grid(row=1, column=0, sticky="w", **pad)
        # Liste deroulante des dossiers recents, mais on peut aussi taper un chemin
        self.e_folder = ttk.Combobox(f, textvariable=self.folder, width=38,
                                     values=self.cfg["recent_folders"])
        self.e_folder.grid(row=1, column=1, sticky="w", **pad)
        self.b_browse = ttk.Button(f, text="Parcourir…", command=self.browse)
        self.b_browse.grid(row=1, column=2, **pad)

        ttk.Label(f, text="Nom de session :").grid(row=2, column=0, sticky="w", **pad)
        self.e_name = ttk.Entry(f, textvariable=self.session_name, width=40)
        self.e_name.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(f, text="(optionnel)", foreground="gray").grid(row=2, column=2, sticky="w", **pad)

        ttk.Label(f, text="Intervalle :").grid(row=3, column=0, sticky="w", **pad)
        row = ttk.Frame(f)
        row.grid(row=3, column=1, sticky="w", **pad)
        self.e_int = ttk.Entry(row, textvariable=self.interval, width=8)
        self.e_int.grid(row=0, column=0)
        self.cb_unit = ttk.Combobox(row, values=list(UNITS), textvariable=self.unit,
                                    state="readonly", width=10)
        self.cb_unit.grid(row=0, column=1, padx=(6, 0))

        ttk.Label(f, text="Format :").grid(row=4, column=0, sticky="w", **pad)
        self.cb_fmt = ttk.Combobox(f, values=["JPG", "PNG"], textvariable=self.fmt,
                                   state="readonly", width=6)
        self.cb_fmt.grid(row=4, column=1, sticky="w", **pad)

        btns = ttk.Frame(f)
        btns.grid(row=5, column=0, columnspan=3, pady=10)
        self.b_play = ttk.Button(btns, text="▶ Play", command=self.play)
        self.b_pause = ttk.Button(btns, text="⏸ Pause", command=self.pause)
        self.b_stop = ttk.Button(btns, text="⏹ Stop", command=self.stop)
        for i, b in enumerate((self.b_play, self.b_pause, self.b_stop)):
            b.grid(row=0, column=i, padx=6)

        ttk.Label(f, textvariable=self.status).grid(row=6, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(f, textvariable=self.detail, foreground="gray").grid(
            row=7, column=0, columnspan=3, sticky="w", **pad)

        self.settings = [self.cb_mon, self.b_refresh, self.e_folder, self.b_browse,
                         self.e_name, self.e_int, self.cb_unit, self.cb_fmt]
        self.load_monitors()
        self.refresh_ui()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(250, self.poll)

    # ---------- interface ----------
    def load_monitors(self):
        with mss.mss() as sct:
            self.monitors = sct.monitors[1:]   # [0] = tous les ecrans reunis
        labels = [f"Écran {i + 1} — {m['width']}x{m['height']} (position {m['left']},{m['top']})"
                  for i, m in enumerate(self.monitors)]
        self.cb_mon.configure(values=labels)
        wanted = self.cfg.get("monitor", 2)
        self.cb_mon.current(min(max(wanted, 1), len(labels)) - 1)

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get() or os.path.expanduser("~"))
        if d:
            self.folder.set(os.path.normpath(d))

    def current_settings(self):
        return {"folder": self.folder.get().strip(), "interval": self.interval.get().strip(),
                "unit": self.unit.get(), "format": self.fmt.get(),
                "session_name": self.session_name.get().strip(),
                "monitor": self.cb_mon.current() + 1}

    def refresh_ui(self):
        stopped = self.state == "stopped"
        for w in self.settings:
            if w is self.e_folder:   # combobox editable
                w.configure(state="normal" if stopped else "disabled")
            elif isinstance(w, ttk.Combobox):
                w.configure(state="readonly" if stopped else "disabled")
            else:
                w.configure(state="normal" if stopped else "disabled")
        self.b_play.configure(state="disabled" if self.state == "running" else "normal")
        self.b_pause.configure(state="normal" if self.state == "running" else "disabled")
        self.b_stop.configure(state="disabled" if stopped else "normal")

    def play(self):
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
            messagebox.showerror("Intervalle invalide",
                                 "Choisis un intervalle entre 1 seconde et 24 heures.")
            return

        base = self.folder.get().strip()
        if not base:
            messagebox.showerror("Dossier manquant", "Choisis un dossier de destination.")
            return
        base = os.path.abspath(os.path.expanduser(base))
        name = clean_name(self.session_name.get()) or "session"
        session = f"{name}_{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}"
        folder = os.path.join(base, session)
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, ".test_ecriture")
            with open(probe, "w") as fh:
                fh.write("ok")
            os.remove(probe)
        except OSError as e:
            messagebox.showerror("Dossier inaccessible", f"Impossible d'écrire dans :\n{folder}\n\n{e}")
            return

        recent = [base] + [d for d in self.cfg["recent_folders"] if not same_path(d, base)]
        self.cfg["recent_folders"] = recent[:MAX_RECENT]
        self.e_folder.configure(values=self.cfg["recent_folders"])
        self.folder.set(base)
        self.cfg.update(self.current_settings())
        save_config(self.cfg)

        self.count = 0
        self.next_capture = None
        # Nouvel evenement a chaque session : un Stop suivi d'un Play immediat
        # ne peut pas reveiller l'ancien thread de capture.
        self.stop_event = threading.Event()
        self.run_event.set()
        self.state = "running"
        self.detail.set(f"Dossier : {session}")
        self.worker = threading.Thread(
            target=self.loop,
            args=(self.cb_mon.current(), seconds, self.fmt.get(), folder, self.stop_event),
            daemon=True)
        self.worker.start()
        log.info("Session demarree : ecran %s, %s s, %s, %s",
                 self.cb_mon.current() + 1, seconds, self.fmt.get(), folder)
        self.refresh_ui()

    def pause(self):
        self.run_event.clear()
        self.state = "paused"
        self.refresh_ui()

    def stop(self):
        if self.state != "stopped":
            log.info("Session arretee apres %s capture(s)", self.count)
        self.stop_event.set()
        self.run_event.set()   # debloque le thread s'il etait en pause
        self.state = "stopped"
        self.next_capture = None
        self.status.set(f"Arrêté — {self.count} capture(s) enregistrée(s)")
        self.refresh_ui()

    def poll(self):
        while True:
            try:
                kind, data = self.msgs.get_nowait()
            except queue.Empty:
                break
            if kind == "ok":
                self.detail.set(f"Dernière : {os.path.basename(data)}")
            elif kind == "err":
                self.detail.set(f"Erreur : {data}")
            elif kind == "fatal":
                self.stop()
                messagebox.showerror("Capture arrêtée", data)

        if self.state == "running":
            text = f"En cours — {self.count} capture(s)"
            if self.next_capture is not None:
                text += f" — prochaine dans {fmt_duration(self.next_capture - time.monotonic())}"
            self.status.set(text)
        elif self.state == "paused":
            self.status.set(f"En pause — {self.count} capture(s)")
        self.root.after(250, self.poll)

    def on_tk_error(self, exc, val, tb):
        log.error("Erreur interface", exc_info=(exc, val, tb))
        messagebox.showerror("Erreur", f"{val}\n\nDétails : logs\\screencap.log")

    def on_close(self):
        self.stop()
        if self.worker is not None:
            self.worker.join(timeout=3)   # laisse finir une ecriture en cours
        self.cfg.update(self.current_settings())
        save_config(self.cfg)
        self.root.destroy()

    # ---------- capture (thread separe) ----------
    def loop(self, mon_index, interval, fmt, folder, stop_event):
        try:
            self.capture_loop(mon_index, interval, fmt, folder, stop_event)
        except Exception as e:   # sinon le thread meurt et l'interface reste "En cours"
            log.error("Thread de capture interrompu", exc_info=True)
            if not stop_event.is_set():
                self.msgs.put(("fatal", f"Capture interrompue.\n\n{e}"))

    def capture_loop(self, mon_index, interval, fmt, folder, stop_event):
        errors = 0
        with mss.mss() as sct:
            if mon_index + 1 >= len(sct.monitors):
                self.msgs.put(("fatal", "Cet écran n'est plus détecté. Clique sur ↻ Écrans."))
                return
            mon = sct.monitors[mon_index + 1]
            next_t = time.monotonic()           # premiere capture immediate
            while not stop_event.is_set():
                if not self.run_event.is_set():  # en pause
                    self.next_capture = None
                    self.run_event.wait(0.2)
                    next_t = time.monotonic()    # capture des la reprise
                    continue
                now = time.monotonic()
                self.next_capture = next_t
                if now < next_t:
                    stop_event.wait(min(next_t - now, 0.2))
                    continue
                next_t = max(next_t + interval, now)
                try:
                    shot = sct.grab(mon)
                    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    ext = ".png" if fmt == "PNG" else ".jpg"
                    path = os.path.join(folder, f"{stamp}_{self.count + 1:05d}{ext}")
                    if fmt == "PNG":
                        img.save(path, compress_level=1)   # compression rapide
                    else:
                        img.save(path, quality=90)
                    self.count += 1
                    errors = 0
                    self.msgs.put(("ok", path))
                except Exception as e:
                    errors += 1
                    log.error("Echec de capture", exc_info=True)
                    self.msgs.put(("err", str(e)))
                    if errors >= MAX_CONSECUTIVE_ERRORS:
                        self.msgs.put(("fatal", f"{errors} échecs d'affilée, capture arrêtée.\n\n{e}"))
                        return


def main():
    setup_logging()
    if IMPORT_ERROR is not None:
        log.error("Dependance manquante : %s", IMPORT_ERROR)
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, f"Dépendance manquante ({IMPORT_ERROR}).\n\n"
                                       "Lance setup.bat puis réessaie.")
        return
    enable_dpi_awareness()
    root = tk.Tk()
    CaptureApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
