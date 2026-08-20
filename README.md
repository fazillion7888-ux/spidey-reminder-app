# Spidey Reminder — Desktop App

A tiny Spider-Man slides down from the top-right corner of your screen with
your custom message, on whatever schedule you set: a one-off countdown, a
specific clock time, or a repeating interval (every 10 minutes, every hour,
etc). It runs in the background with a system tray icon.

Tested and verified working: window builds, mode switching, the slide-down
animation, arm/disarm, and auto-fire on a countdown all run correctly, and
the packaging steps below were test-built successfully before being handed
to you.

## What's in this folder
```
spidey-reminder-app/
  main.py              <- the app
  assets/
    spiderman.png       <- your character, background removed
    spiderman.ico        <- Windows icon version
  requirements.txt
  README.md            <- this file
```

## Option A — Run it with Python (fastest way to try it)

1. Install Python 3.10+ from python.org if you don't already have it
   (tick "Add Python to PATH" during install on Windows).
2. Open a terminal/command prompt in this folder.
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run it:
   ```
   python main.py
   ```

A window titled "REMINDER PATROL" opens. Set your mode (Countdown / Exact
Time / Repeat Every), duration, and message, then click **Arm Reminder**.
Closing the window sends it to the system tray instead of quitting (right
click the tray icon to reopen it or quit for good).

## Option B — Turn it into a real double-click .exe (no Python needed to run it)

This is the "install it like a real program" path. You still need Python
once, to build the .exe — after that, the .exe runs on its own.

1. Do steps 1–3 from Option A, then also install the packager:
   ```
   pip install pyinstaller
   ```
2. From this folder, run:
   ```
   pyinstaller --noconfirm --onefile --windowed --name SpideyReminder --icon assets\spiderman.ico --add-data "assets;assets" main.py
   ```
   (On macOS/Linux, use a colon instead of a semicolon: `--add-data "assets:assets"`)
3. Your app appears at `dist\SpideyReminder.exe`. Copy that one file
   anywhere you like (Desktop, Start Menu folder, etc.) and double-click it
   — no terminal, no Python needed from here on.

## Option C — Fully hands-off: auto-start at login, already armed, no clicks

This is the "I don't want to do anything" setup — e.g. a reminder every
1 hour, forever, from the moment you log in.

1. Open the app normally once (Option A or B). It defaults to **Repeat
   Every → 1 → hours** already.
2. Set your message, tick **"Remember these settings & auto-arm on
   startup"**, then click **Arm Reminder**. This saves your settings to
   `%APPDATA%\SpideyReminder\settings.json` so future launches can restore
   them automatically. You can close the app now.
3. Build the .exe if you haven't (Option B).
4. Press `Win + R`, type `shell:startup`, hit Enter — this opens your
   Startup folder.
5. Right-click inside that folder → **New → Shortcut**. For the location,
   browse to `SpideyReminder.exe` and, importantly, add `--auto` after it,
   for example:
   ```
   "C:\Users\You\Desktop\SpideyReminder.exe" --auto
   ```
   (Right-click the finished shortcut → Properties → Target field, if you
   need to edit it after creating it.)
6. From now on: log in → the app launches invisibly, restores your saved
   settings, arms itself, and hides (to the tray if available, otherwise
   it just runs quietly in the background) — no window, no clicks.

**To change the schedule or message later:** open `SpideyReminder.exe`
normally (without `--auto`, e.g. by double-clicking it directly) — it
opens the visible window pre-filled with your last saved settings, so you
can tweak and re-arm.

**To stop it:** if you have a tray icon, right-click it → Quit. Without a
tray icon, open Task Manager, find "SpideyReminder", and End Task — or
just delete the Startup shortcut so it stops launching at login.

## "No system tray support detected on this install"

If you saw this note in the app, it means the `pystray` library didn't
load — the app still works fine without it, just without a tray icon
(closing the window quits it instead of hiding it, and Option C above
falls back to hiding silently in the background instead of showing a tray
icon). To try to get the tray icon working, run:
```
pip install --upgrade pystray pillow
```
then relaunch. Not required for Option C to work — it just makes the
running app less discoverable while it's hidden.

## Being upfront about limits

- The app needs to actually be running (in the tray counts) to fire a
  reminder — it can't wake your PC from being fully shut down.
- The repeat/countdown timers are wall-clock based, so if your PC sleeps,
  the timer effectively pauses and picks up on wake.
- No internet connection or admin rights are required for any of this.
