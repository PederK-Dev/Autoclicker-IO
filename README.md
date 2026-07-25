# Autoclicker IO

A fast, precise auto clicker for Windows. Pure Python + `tkinter` + raw Win32 —
**no third-party packages to install**.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer

The standard Python installer for Windows includes `tkinter`, so there is no
`pip install` step.

## Quick start

```bash
python main.py
```

You can also run the package directly:

```bash
python -m autoclicker
```

The default global hotkeys are:

| Action | Hotkey |
| --- | --- |
| Start or stop clicking | `F5` |
| Start or stop recording | `F7` |
| Start or stop playback | `F8` |

Hotkeys can be changed from the app, including binding mouse buttons. Start
with a slower interval while checking a new configuration so you can stop it
comfortably.

## Features

**Click interval**

- Fixed interval in hours / minutes / seconds / milliseconds
- Random interval between a min and max, re-rolled before every click
- Live "clicks per second" readout so you can see what you're actually asking for

**Click options**

- Left, middle, right, or the two side buttons (X1 / X2)
- Single, double or triple click — double clicks are timed so the OS really
  reports them as double clicks, not two singles
- Hold time per click, with optional random jitter

**Repeat**

- Until stopped, a fixed number of clicks, or for a fixed duration
- Start delay with a visible countdown

**Cursor position**

- Click wherever the cursor happens to be
- Click a fixed point — *Pick location* captures your next real click anywhere
  on screen, so you can grab a target inside another app
- Click through a recorded sequence of points, cycling round
- Position jitter in pixels, and an option to put the cursor back after each
  click so the clicker doesn't fight you for the mouse

**Global hotkeys — keyboard *or* mouse buttons**

- Bind Start, Stop, Record and Playback to any key, with modifiers (`Ctrl+Shift+F6`)
- …or to a **mouse button**: middle, X1 or X2 (the side buttons), even left/right
- Leave Start and Stop on the same binding and it toggles
- *Hide hotkeys from other apps* stops a bound middle-click from also starting
  autoscroll, or F5 from refreshing the page underneath. The left and right
  buttons are never hidden, so you can't lock yourself out of your own desktop.
- Hotkeys work while any other application is focused
- The global mouse hook is only installed while a mouse button is actually bound

**Appearance**

- Dark and light themes, switched from the header, remembered between runs
- DPI-aware: sharp and correctly sized on scaled displays

**Record & playback**

- Records real mouse movement, clicks, scrolling and keystrokes with timing
- Replays at adjustable speed, N times or on a loop
- Save and load macros as JSON
- Export a macro's click points straight into the click-sequence mode

**Profiles** — save and reload whole configurations by name. Settings persist
automatically between runs.

## How it works

- Clicks are real `SendInput` events, not `PostMessage` fakes, so applications
  that read raw input see them normally.
- Cursor moves use absolute virtual-desktop coordinates, so they land on the
  exact pixel across multiple monitors at any DPI scaling.
- The interval loop asks Windows for a 1 ms scheduler tick, sleeps coarsely,
  then spins for the final ~1.6 ms. Measured drift at a 10 ms interval is
  ~0.02 ms per click.
- Global hotkeys and recording use `WH_KEYBOARD_LL` / `WH_MOUSE_LL` hooks on a
  dedicated message-pump thread.
- Everything the app injects is tagged, so recording never captures the app's
  own output and hotkeys can't be triggered by synthetic keys.

Settings and profiles are saved under `%APPDATA%\AutoclickerIO\`. The macro
file picker uses `%APPDATA%\AutoclickerIO\macros\` by default, but macros can be
saved anywhere.

## Layout

| File | Purpose |
| --- | --- |
| `autoclicker/winapi.py` | ctypes bindings for the Win32 APIs used |
| `autoclicker/inputs.py` | `SendInput` wrappers and the high-resolution sleep |
| `autoclicker/hooks.py` | global keyboard/mouse hooks on a message-pump thread |
| `autoclicker/keys.py` | virtual-key tables, hotkey parsing and matching |
| `autoclicker/engine.py` | the click loop |
| `autoclicker/recorder.py` | macro recording, serialisation and playback |
| `autoclicker/config.py` | settings model, persistence, profiles |
| `autoclicker/theme.py` | palettes, DPI scaling, ttk restyling |
| `autoclicker/widgets.py` | hand-drawn buttons, segmented controls, switches, cards |
| `autoclicker/ui.py` | tkinter front end |

## Tests

Run the non-injecting test scripts from the repository root:

```bash
python tests/test_core.py
python tests/test_mouse_hotkeys.py
python tests/test_ui.py
```

`test_core.py` covers timing accuracy, the click engine's modes, config
round-tripping, macro serialisation and hook lifecycle. `test_mouse_hotkeys.py`
covers binding mouse buttons, the suppression rules and the hook install/release
logic. `test_ui.py` builds the real Tk UI, switches themes and exercises every
control. None of these three scripts emit real clicks, though the UI tests need
an interactive Windows desktop.

The live end-to-end test intentionally moves the pointer and injects real mouse
input:

```bash
python tests/test_live.py
```

It clicks **only on its own test window** and restores the original cursor
position when it finishes. Do not move the mouse while it runs.

## Responsible use

Use input automation only where it is permitted. Some applications and online
games prohibit automation in their terms of service.
