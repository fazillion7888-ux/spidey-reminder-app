"""
Spidey Reminder - a desktop background reminder app.

A tiny Spider-Man slides down from the top-right corner of your screen
with a custom message, on a schedule you set (countdown / exact time /
repeating interval). Runs quietly in the system tray.
"""

import os
import sys
import json
import threading
import time
from datetime import datetime, timedelta

import tkinter as tk
from tkinter import ttk, messagebox

# ---------------------------------------------------------------------------
# Optional dependencies: the app still runs without them, just with less
# polish (no tray icon and/or no OS toast notification backup).
# ---------------------------------------------------------------------------
try:
    import pystray
    from PIL import Image as PILImage
    HAVE_TRAY = True
except Exception:
    HAVE_TRAY = False

try:
    from plyer import notification as os_notification
    HAVE_PLYER = True
except Exception:
    HAVE_PLYER = False


def resource_path(relative_path):
    """Resolve a bundled asset path, whether running as a script or as a
    PyInstaller-frozen executable."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


IMG_PATH = resource_path(os.path.join("assets", "spiderman.png"))
ICO_PATH = resource_path(os.path.join("assets", "spiderman.ico"))

# Settings live in %APPDATA% (or the home folder on non-Windows) rather than
# next to the program, so they're writable even when the app is installed
# somewhere locked-down, and survive rebuilding the .exe.
CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SpideyReminder")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")

AUTO_FLAG = "--auto" in sys.argv


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_config(data):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass

BG = "#0a1128"
PANEL = "#131c3a"
EDGE = "#243463"
RED = "#d62828"
BLUE = "#1f4e8c"
GOLD = "#f4b400"
INK = "#05070f"
WHITE = "#f2f0e6"

TRANSPARENT_KEY = "#010203"  # chroma key used for the popup window (Windows only)


class Scheduler:
    """Tracks when the reminder should next fire."""

    def __init__(self):
        self.mode = "countdown"       # countdown | exact | repeat
        self.target_ts = None         # epoch seconds
        self.repeat_seconds = None
        self.armed = False

    def compute_target(self, params):
        now = time.time()
        if self.mode == "countdown":
            total = params["cd_min"] * 60 + params["cd_sec"]
            if total <= 0:
                return None
            return now + total
        elif self.mode == "exact":
            h, m = params["exact_h"], params["exact_m"]
            target_dt = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
            if target_dt.timestamp() <= now:
                target_dt += timedelta(days=1)
            return target_dt.timestamp()
        else:  # repeat
            unit_seconds = 3600 if params["repeat_unit"] == "hours" else 60
            self.repeat_seconds = max(1, params["repeat_value"]) * unit_seconds
            return now + self.repeat_seconds

    def arm(self, params):
        self.target_ts = self.compute_target(params)
        if self.target_ts is None:
            return False
        self.armed = True
        return True

    def disarm(self):
        self.armed = False
        self.target_ts = None

    def remaining(self):
        if self.target_ts is None:
            return 0
        return max(0, self.target_ts - time.time())

    def reschedule_repeat(self):
        self.target_ts = time.time() + self.repeat_seconds


class SpideyPopup:
    """The animated pop-up window: web-line descent, swing, message bubble,
    swing back up."""

    def __init__(self, root):
        self.root = root
        self.win = None
        self.photo = None
        self._closing = False

    def show(self, message, duration_seconds):
        if self.win is not None:
            return  # a popup is already showing; skip this fire

        win = tk.Toplevel(self.root)
        self.win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
            win.configure(bg=TRANSPARENT_KEY)
            bubble_bg_ok = True
        except tk.TclError:
            win.configure(bg=BG)
            bubble_bg_ok = False

        img = tk.PhotoImage(file=IMG_PATH)
        # Scale down if the source image is large; keep it a modest size.
        max_h = 260
        if img.height() > max_h:
            factor = max(1, round(img.height() / max_h))
            img = img.subsample(factor, factor)
        self.photo = img

        content_bg = TRANSPARENT_KEY if bubble_bg_ok else BG
        frame = tk.Frame(win, bg=content_bg)
        frame.pack(fill="both", expand=True)

        bubble = tk.Label(
            frame, text=message, wraplength=190, justify="left",
            bg=WHITE, fg=INK, font=("Segoe UI", 10, "bold"),
            padx=12, pady=10, bd=2, relief="solid",
        )
        bubble.grid(row=0, column=0, sticky="ne", padx=(0, 6), pady=(30, 0))

        spidey_label = tk.Label(frame, image=self.photo, bg=content_bg, bd=0)
        spidey_label.grid(row=0, column=1, sticky="n")

        win.update_idletasks()
        w = win.winfo_reqwidth() + 10
        h = win.winfo_reqheight() + 10
        screen_w = self.root.winfo_screenwidth()
        x = screen_w - w - 40
        start_y = -h - 10
        end_y = 20
        win.geometry(f"{w}x{h}+{x}+{start_y}")

        self._animate_down(win, x, start_y, end_y, duration_seconds)

    def _animate_down(self, win, x, start_y, end_y, duration_seconds):
        steps = 26
        distance = end_y - start_y

        def ease_out_cubic(t):
            return 1 - (1 - t) ** 3

        def step(i=0):
            if self._closing or not win.winfo_exists():
                return
            t = i / steps
            y = int(start_y + distance * ease_out_cubic(t))
            win.geometry(f"+{x}+{y}")
            if i < steps:
                win.after(12, step, i + 1)
            else:
                self._settle_swing(win, x, end_y, duration_seconds)

        step()

    def _settle_swing(self, win, base_x, y, duration_seconds):
        # small left/right wiggle to fake a pendulum swing settling
        offsets = [10, -7, 4, -2, 0]

        def wiggle(i=0):
            if self._closing or not win.winfo_exists():
                return
            if i < len(offsets):
                win.geometry(f"+{base_x + offsets[i]}+{y}")
                win.after(70, wiggle, i + 1)
            else:
                win.geometry(f"+{base_x}+{y}")
                win.after(int(duration_seconds * 1000), lambda: self._animate_up(win, base_x, y))

        wiggle()

    def _animate_up(self, win, x, start_y):
        if self._closing or not win.winfo_exists():
            return
        steps = 18
        end_y = -(win.winfo_height()) - 10
        distance = end_y - start_y

        def ease_in_cubic(t):
            return t ** 3

        def step(i=0):
            if not win.winfo_exists():
                return
            t = i / steps
            y = int(start_y + distance * ease_in_cubic(t))
            win.geometry(f"+{x}+{y}")
            if i < steps:
                win.after(10, step, i + 1)
            else:
                self._cleanup()

        step()

    def _cleanup(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.destroy()
        self.win = None
        self.photo = None


class SpideyApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Spidey Reminder")
        self.root.configure(bg=BG)
        self.root.geometry("420x560")
        self.root.resizable(False, False)
        if os.path.exists(ICO_PATH) and sys.platform == "win32":
            try:
                self.root.iconbitmap(ICO_PATH)
            except Exception:
                pass

        self.scheduler = Scheduler()
        self.popup = SpideyPopup(self.root)
        self.tray_icon = None

        self._build_ui()
        self._poll_job = None
        self._apply_saved_config()

        # Hide to tray instead of quitting on the window's close button,
        # if a tray icon is available. Otherwise closing the window quits.
        if HAVE_TRAY:
            self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
            self._start_tray()
        else:
            self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

        # Launched with --auto (e.g. from the Windows Startup folder): arm
        # automatically from saved settings and get out of the way without
        # any clicks needed.
        if AUTO_FLAG:
            config = load_config()
            if config and config.get("autostart"):
                self._on_arm_click()  # arms using the fields just restored
                # withdraw() hides the window reliably on every platform
                # (unlike iconify, it doesn't depend on a window manager).
                # With a tray icon, "Show Settings" brings it back; without
                # one, re-open the app normally (no --auto) to change things.
                self.root.after(200, self.root.withdraw)

    # -- UI ----------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 20}

        header = tk.Label(
            self.root, text="REMINDER PATROL", bg=BG, fg=WHITE,
            font=("Segoe UI", 20, "bold"),
        )
        header.pack(pady=(20, 0), **pad, anchor="w")

        sub = tk.Label(
            self.root,
            text="Runs in the background. Spidey swings by on your schedule.",
            bg=BG, fg="#9fb0d9", font=("Segoe UI", 9), wraplength=380, justify="left",
        )
        sub.pack(pady=(2, 14), **pad, anchor="w")

        # Mode selector
        mode_frame = tk.Frame(self.root, bg=BG)
        mode_frame.pack(fill="x", **pad)
        self.mode_var = tk.StringVar(value="repeat")
        for label, value in [("Countdown", "countdown"), ("Exact Time", "exact"), ("Repeat Every", "repeat")]:
            b = tk.Radiobutton(
                mode_frame, text=label, value=value, variable=self.mode_var,
                command=self._on_mode_change, bg=BG, fg=WHITE, selectcolor=PANEL,
                activebackground=BG, activeforeground=WHITE, font=("Segoe UI", 9, "bold"),
                indicatoron=True,
            )
            b.pack(side="left", padx=(0, 10))

        # Fields container (only one shown at a time)
        self.fields_frame = tk.Frame(self.root, bg=BG)
        self.fields_frame.pack(fill="x", **pad, pady=(10, 0))

        self._build_countdown_fields()
        self._build_exact_fields()
        self._build_repeat_fields()
        self._on_mode_change()

        # Duration
        tk.Label(self.root, text="ON-SCREEN DURATION (SECONDS)", bg=BG, fg=GOLD,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad, pady=(16, 4))
        self.duration_var = tk.IntVar(value=8)
        tk.Spinbox(self.root, from_=2, to=120, textvariable=self.duration_var, width=8,
                   bg="#0b1330", fg=WHITE, insertbackground=WHITE, relief="solid", bd=1).pack(anchor="w", **pad)

        # Message
        tk.Label(self.root, text="MESSAGE", bg=BG, fg=GOLD,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", **pad, pady=(16, 4))
        self.message_text = tk.Text(self.root, height=3, width=40, bg="#0b1330", fg=WHITE,
                                     insertbackground=WHITE, relief="solid", bd=1, wrap="word",
                                     font=("Segoe UI", 10))
        self.message_text.insert("1.0", "Time to stretch! Take a 5-minute break.")
        self.message_text.pack(**pad, fill="x")

        # Remember & auto-arm
        self.autostart_var = tk.BooleanVar(value=False)
        autostart_check = tk.Checkbutton(
            self.root, text="Remember these settings & auto-arm on startup",
            variable=self.autostart_var, bg=BG, fg="#b7c2e6", selectcolor=PANEL,
            activebackground=BG, activeforeground="#b7c2e6", font=("Segoe UI", 9),
        )
        autostart_check.pack(anchor="w", **pad, pady=(12, 0))

        # Buttons
        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(fill="x", **pad, pady=(18, 0))
        self.arm_btn = tk.Button(
            btn_frame, text="Arm Reminder", command=self._on_arm_click,
            bg=RED, fg="white", font=("Segoe UI", 11, "bold"), relief="flat",
            padx=14, pady=8, activebackground="#9c1c1c", activeforeground="white",
        )
        self.arm_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        test_btn = tk.Button(
            btn_frame, text="Test Swing", command=self._on_test_click,
            bg=BLUE, fg="white", font=("Segoe UI", 11, "bold"), relief="flat",
            padx=14, pady=8, activebackground="#163a67", activeforeground="white",
        )
        test_btn.pack(side="left", fill="x", expand=True)

        # Status
        self.status_var = tk.StringVar(value="Awaiting orders, Spidey.")
        tk.Label(self.root, textvariable=self.status_var, bg=BG, fg="#8b98bf",
                 font=("Segoe UI", 9)).pack(anchor="w", **pad, pady=(16, 0))

        note = ("Minimizing/closing this window sends it to the system tray (if available) "
                "so it keeps running in the background. Tick the box above, Arm, then set up "
                "Startup + --auto (see README) for a fully hands-off launch." if HAVE_TRAY else
                "Note: no system tray support detected on this install - closing this window quits "
                "the app, and it will just minimize to the taskbar instead when auto-armed.")
        tk.Label(self.root, text=note, bg=BG, fg="#5c6890", font=("Segoe UI", 8),
                 wraplength=380, justify="left").pack(anchor="w", **pad, pady=(14, 0))

    def _build_countdown_fields(self):
        self.countdown_frame = tk.Frame(self.fields_frame, bg=BG)
        tk.Label(self.countdown_frame, text="Minutes", bg=BG, fg="#9fb0d9",
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        tk.Label(self.countdown_frame, text="Seconds", bg=BG, fg="#9fb0d9",
                 font=("Segoe UI", 8)).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.cd_min_var = tk.IntVar(value=0)
        self.cd_sec_var = tk.IntVar(value=10)
        tk.Spinbox(self.countdown_frame, from_=0, to=999, textvariable=self.cd_min_var, width=8,
                   bg="#0b1330", fg=WHITE, insertbackground=WHITE, relief="solid", bd=1).grid(row=1, column=0)
        tk.Spinbox(self.countdown_frame, from_=0, to=59, textvariable=self.cd_sec_var, width=8,
                   bg="#0b1330", fg=WHITE, insertbackground=WHITE, relief="solid", bd=1).grid(row=1, column=1, padx=(10, 0))

    def _build_exact_fields(self):
        self.exact_frame = tk.Frame(self.fields_frame, bg=BG)
        tk.Label(self.exact_frame, text="Hour (0-23)", bg=BG, fg="#9fb0d9",
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        tk.Label(self.exact_frame, text="Minute", bg=BG, fg="#9fb0d9",
                 font=("Segoe UI", 8)).grid(row=0, column=1, sticky="w", padx=(10, 0))
        now = datetime.now()
        self.exact_h_var = tk.IntVar(value=now.hour)
        self.exact_m_var = tk.IntVar(value=(now.minute + 1) % 60)
        tk.Spinbox(self.exact_frame, from_=0, to=23, textvariable=self.exact_h_var, width=8,
                   bg="#0b1330", fg=WHITE, insertbackground=WHITE, relief="solid", bd=1).grid(row=1, column=0)
        tk.Spinbox(self.exact_frame, from_=0, to=59, textvariable=self.exact_m_var, width=8,
                   bg="#0b1330", fg=WHITE, insertbackground=WHITE, relief="solid", bd=1).grid(row=1, column=1, padx=(10, 0))
        tk.Label(self.exact_frame, text="Fires today at this time (tomorrow if already passed).",
                 bg=BG, fg="#6d7ba8", font=("Segoe UI", 8)).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _build_repeat_fields(self):
        self.repeat_frame = tk.Frame(self.fields_frame, bg=BG)
        tk.Label(self.repeat_frame, text="Every", bg=BG, fg="#9fb0d9",
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        tk.Label(self.repeat_frame, text="Unit", bg=BG, fg="#9fb0d9",
                 font=("Segoe UI", 8)).grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.repeat_value_var = tk.IntVar(value=1)
        self.repeat_unit_var = tk.StringVar(value="hours")
        tk.Spinbox(self.repeat_frame, from_=1, to=999, textvariable=self.repeat_value_var, width=8,
                   bg="#0b1330", fg=WHITE, insertbackground=WHITE, relief="solid", bd=1).grid(row=1, column=0)
        unit_menu = ttk.Combobox(self.repeat_frame, textvariable=self.repeat_unit_var,
                                  values=["minutes", "hours"], width=8, state="readonly")
        unit_menu.grid(row=1, column=1, padx=(10, 0))
        tk.Label(self.repeat_frame, text="Example: 10 + minutes = every 10 min. 1 + hours = every hour.",
                 bg=BG, fg="#6d7ba8", font=("Segoe UI", 8)).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _on_mode_change(self):
        for f in (self.countdown_frame, self.exact_frame, self.repeat_frame):
            f.pack_forget()
        mode = self.mode_var.get()
        if mode == "countdown":
            self.countdown_frame.pack(anchor="w")
        elif mode == "exact":
            self.exact_frame.pack(anchor="w")
        else:
            self.repeat_frame.pack(anchor="w")

    # -- Actions -------------------------------------------------------------
    def _gather_params(self):
        return {
            "cd_min": self.cd_min_var.get(),
            "cd_sec": self.cd_sec_var.get(),
            "exact_h": self.exact_h_var.get(),
            "exact_m": self.exact_m_var.get(),
            "repeat_value": self.repeat_value_var.get(),
            "repeat_unit": self.repeat_unit_var.get(),
        }

    def _save_current_config(self):
        data = {
            "mode": self.mode_var.get(),
            "cd_min": self.cd_min_var.get(),
            "cd_sec": self.cd_sec_var.get(),
            "exact_h": self.exact_h_var.get(),
            "exact_m": self.exact_m_var.get(),
            "repeat_value": self.repeat_value_var.get(),
            "repeat_unit": self.repeat_unit_var.get(),
            "duration": self.duration_var.get(),
            "message": self.message_text.get("1.0", "end").strip(),
            "autostart": self.autostart_var.get(),
        }
        save_config(data)

    def _apply_saved_config(self):
        data = load_config()
        if not data:
            return
        self.mode_var.set(data.get("mode", self.mode_var.get()))
        self.cd_min_var.set(data.get("cd_min", self.cd_min_var.get()))
        self.cd_sec_var.set(data.get("cd_sec", self.cd_sec_var.get()))
        self.exact_h_var.set(data.get("exact_h", self.exact_h_var.get()))
        self.exact_m_var.set(data.get("exact_m", self.exact_m_var.get()))
        self.repeat_value_var.set(data.get("repeat_value", self.repeat_value_var.get()))
        self.repeat_unit_var.set(data.get("repeat_unit", self.repeat_unit_var.get()))
        self.duration_var.set(data.get("duration", self.duration_var.get()))
        if data.get("message"):
            self.message_text.delete("1.0", "end")
            self.message_text.insert("1.0", data["message"])
        self.autostart_var.set(data.get("autostart", False))
        self._on_mode_change()

    def _on_arm_click(self):
        if self.scheduler.armed:
            self.scheduler.disarm()
            self.arm_btn.config(text="Arm Reminder", bg=RED)
            self.status_var.set("Stood down. Awaiting orders, Spidey.")
            if self._poll_job:
                self.root.after_cancel(self._poll_job)
                self._poll_job = None
            self.autostart_var.set(False)
            self._save_current_config()
            return

        self.scheduler.mode = self.mode_var.get()
        ok = self.scheduler.arm(self._gather_params())
        if not ok:
            messagebox.showwarning("Spidey Reminder", "Please set a valid time first.")
            return

        self._save_current_config()
        self.arm_btn.config(text="Disarm", bg="#3a3f52")
        label = "Repeating. Next swing in" if self.scheduler.mode == "repeat" else "Web-alert armed. Landing in"
        self.status_var.set(label)
        self._poll()

    def _on_test_click(self):
        self._fire_popup()

    def _poll(self):
        remaining = self.scheduler.remaining()
        if remaining <= 0 and self.scheduler.armed:
            self._fire_popup()
            if self.scheduler.mode == "repeat":
                self.scheduler.reschedule_repeat()
                self.status_var.set("Repeating. Next swing in " + self._fmt(self.scheduler.remaining()))
            else:
                self.scheduler.disarm()
                self.arm_btn.config(text="Arm Reminder", bg=RED)
                self.status_var.set("Alert delivered!")
                self._poll_job = None
                return
        elif self.scheduler.armed:
            label = "Repeating. Next swing in " if self.scheduler.mode == "repeat" else "Web-alert armed. Landing in "
            self.status_var.set(label + self._fmt(remaining))

        if self.scheduler.armed:
            self._poll_job = self.root.after(500, self._poll)

    @staticmethod
    def _fmt(seconds):
        seconds = int(seconds)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _fire_popup(self):
        message = self.message_text.get("1.0", "end").strip() or "With great reminders comes great responsibility."
        duration = max(2, min(120, self.duration_var.get()))
        self.popup.show(message, duration)
        if HAVE_PLYER:
            try:
                os_notification.notify(title="Spidey Reminder", message=message, timeout=duration)
            except Exception:
                pass

    # -- Tray ----------------------------------------------------------------
    def _start_tray(self):
        try:
            image = PILImage.open(IMG_PATH)
        except Exception:
            image = PILImage.new("RGBA", (64, 64), (214, 40, 40, 255))

        menu = pystray.Menu(
            pystray.MenuItem("Show Settings", self._show_from_tray, default=True),
            pystray.MenuItem("Quit", self._quit_from_tray),
        )
        self.tray_icon = pystray.Icon("spidey-reminder", image, "Spidey Reminder", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_from_tray(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def _quit_from_tray(self, icon=None, item=None):
        self.root.after(0, self.quit_app)

    def hide_to_tray(self):
        self.root.withdraw()

    def quit_app(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = SpideyApp()
    app.run()
