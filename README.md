# Autoclicker IO

Autoclicker IO is a precise, configurable auto clicker and macro recorder for
Windows. It is written with Python's standard library (`tkinter`, `ctypes`, and
Win32 APIs), so the running application has no third-party dependencies.

Automation can affect the application that currently has focus. Use it only
where you have permission, and start with a slow interval while checking a new
configuration.

## Requirements and limitations

- Windows 10 or Windows 11 (64-bit for the published executable).
- Python 3.10 or newer for a source checkout. Use the standard Windows Python
  installer and include **Tcl/Tk**.
- The application is Windows-only. It calls `user32.dll` directly and does not
  provide a Linux, macOS, Wine, or headless-server fallback.
- Windows security boundaries still apply: input sent to an elevated program
  may require Autoclicker IO to run at the same elevation. It cannot bypass
  secure desktops, UAC prompts, anti-cheat systems, or an application's own
  automation policy.

## Install and run from source

Clone the repository, then run from its root. There is no runtime dependency to
install:

```powershell
python main.py
# or
python -m autoclicker
```

To install the package in the active environment and expose the GUI command:

```powershell
python -m pip install .
autoclicker-io
```

The `build` extra is optional and is only needed to produce a standalone
executable:

```powershell
python -m pip install ".[build]"
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

PowerShell 7 users can substitute `pwsh` for `powershell`.

The script checks Python and PyInstaller, cleans only the repository's explicit
`build\` and `dist\` directories, and writes a versioned artifact such as
`dist\AutoclickerIO-1.0.0-windows-x64.exe`.

## Safe defaults and panic stop

The first launch is idle and uses conservative defaults: a 100 ms interval,
the current cursor position, cursor restoration after each click, and `F5` as a
start/stop toggle. The interval and repeat settings are validated before a run
starts.

By default, press **Pause/Break** at any time for the global panic stop. It stops
active clicking, recording, and macro playback without generating another input
event. Use it before moving the pointer to investigate an unexpected run; `F5`
remains the normal start/stop control. Both bindings can be changed in Hotkeys.

Default global hotkeys:

| Action | Hotkey |
| --- | --- |
| Start/stop clicking | `F5` |
| Start/stop recording | `F7` |
| Start/stop playback | `F8` |
| Panic stop | `Pause/Break` |

Hotkeys can be changed, including to mouse buttons. Bound hotkeys are hidden
from other apps by default, and suppression can be disabled. The left/right
buttons are never suppressed, so a binding cannot lock you out of the desktop.

## Features

- Fixed or random intervals with hour/minute/second/millisecond precision and a
  live clicks-per-second estimate.
- Left, middle, right, X1, or X2 input; single, double, or triple clicks;
  optional hold time and jitter.
- Infinite, count-limited, or duration-limited repeats, with a visible start
  countdown.
- Current cursor, a captured fixed point, or a recorded sequence of points;
  optional pixel jitter and cursor restoration.
- Global keyboard and mouse-button hotkeys, optional suppression, and a
  dedicated low-level hook thread.
- Macro recording and playback of mouse movement, clicks, scrolling, and
  keystrokes with timing, speed, repeat, looping, JSON save/load, and conversion
  to a click sequence.
- Named profiles, persistent settings, dark/light themes, and DPI-aware Tk
  rendering.
- A focused Basic view with an optional Advanced behavior panel, first-run
  safety guidance, and keyboard-operable custom controls.

## Data and diagnostics locations

Settings are stored in the Windows roaming application-data directory:

```text
%APPDATA%\AutoclickerIO\config.json
%APPDATA%\AutoclickerIO\config.json.bak   (last known-good settings)
%APPDATA%\AutoclickerIO\profiles\*.json
%APPDATA%\AutoclickerIO\macros\*.json   (default macro-picker directory)
%APPDATA%\AutoclickerIO\logs\autoclicker.log   (rotating diagnostics log)
```

Macros may also be saved anywhere through the file picker. Diagnostics are
written lazily to the rotating log above when a warning or exception occurs;
status text and error dialogs remain the primary user-facing diagnostics. If
the per-user directory is unavailable, logging falls back safely and does not
stop clicking. For source troubleshooting, launch `python main.py` from
PowerShell to capture console output; the windowed packaged executable writes
diagnostics to the rotating file instead. Do not put secrets or personal data
in a report.

## Tests

The CI workflow runs only tests that do not intentionally inject real mouse
input, across Python 3.10, 3.11, 3.12, and 3.13:

```powershell
python tests/test_core.py
python tests/test_hardening.py
python tests/test_mouse_hotkeys.py
python tests/test_widget_accessibility.py
```

`test_core.py` covers timing, engine modes, configuration round-trips, macro
serialization, hook lifecycle, and worker cleanup. `test_hardening.py` covers
versioned settings, backup recovery, diagnostics, and malformed macro files.
`test_mouse_hotkeys.py` covers mouse-button bindings, suppression, and hook
install/release.
`test_widget_accessibility.py` covers keyboard reachability, labels, focus,
disabled-state behavior, and contrast-sensitive UI details. The panic-stop and
error-path hardening checks are included in `tests/test_ui.py`.

`tests/test_ui.py` builds the real Tk window and should be run locally on an
interactive Windows desktop. `tests/test_live.py` deliberately moves the
pointer and injects real input into its own test window; it is never run by CI.
Do not move the mouse while the live test is running.

## Release artifacts

Every push to `main`, pull request, or manually dispatched workflow validates
compilation and builds a wheel and source distribution. A separate, non-matrix
job builds one PyInstaller executable with Python 3.13 and uploads the
versioned `AutoclickerIO-<version>-windows-x64.exe` artifact. Runtime packages
remain dependency-free; PyInstaller is build-time tooling only.

The executable is not code-signed. Windows SmartScreen may therefore show an
unknown-publisher warning. Verify the artifact source and inspect the version
before allowing it to run; do not describe it as signed or trusted by
Microsoft.

## Troubleshooting

- **`python` is not recognized:** install Python 3.10+ from python.org, enable
  “Add Python to PATH,” and open a new PowerShell window. Check with
  `python --version`.
- **Tkinter cannot import or the window will not open:** reinstall Python with
  Tcl/Tk, then verify `python -m tkinter`. Tk UI tests need an interactive
  desktop session.
- **`ctypes.windll` or Win32 import errors:** this project only supports
  Windows. Use `main.py` from a Windows Python, not WSL or a Linux container.
- **The build script cannot find PyInstaller:** run
  `python -m pip install ".[build]"` in the same environment and invoke the
  script with PowerShell (`pwsh` or Windows PowerShell).
- **An app does not receive clicks:** check that both applications have a
  compatible elevation level and that the target allows automation. Press
  `Pause/Break` to stop first; never test against a protected or online target
  without permission.
- **Settings behave unexpectedly:** close the app, back up, and inspect
  `%APPDATA%\AutoclickerIO\config.json`. Removing `config.json` and its
  `config.json.bak` backup resets global settings; profiles and macros are
  separate directories.

## Project layout

| Path | Purpose |
| --- | --- |
| `autoclicker/winapi.py` | Win32 `ctypes` bindings |
| `autoclicker/inputs.py` | `SendInput` wrappers and precise sleeping |
| `autoclicker/hooks.py` | Low-level keyboard/mouse hooks |
| `autoclicker/keys.py` | Virtual-key tables and hotkey matching |
| `autoclicker/engine.py` | Click loop and repeat modes |
| `autoclicker/recorder.py` | Macro recording, serialization, playback |
| `autoclicker/config.py` | Settings persistence and profiles |
| `autoclicker/diagnostics.py` | Best-effort rotating diagnostics log |
| `autoclicker/ui.py` | Tkinter GUI |
| `scripts/build.ps1` | Clean, versioned PyInstaller build |

## License

Autoclicker IO is released under the [MIT License](LICENSE) © 2026 PederK-Dev.
See [SECURITY.md](SECURITY.md) for private vulnerability reporting.
