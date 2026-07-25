"""Mouse buttons as hotkeys: matching, suppression rules and the live hook path."""
import os, sys, tempfile, time, tkinter as tk
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclicker import config, engine, hooks, inputs, keys, recorder, theme, ui
from autoclicker.hooks import KeyEvent, MouseEvent

ok = lambda m: print(f"  PASS  {m}")

# --- names / parsing -------------------------------------------------------
print("[1] mouse virtual keys")
assert keys.vk_name(0x05) == "Mouse X1" and keys.vk_name(0x04) == "Mouse Middle"
assert keys.is_mouse_vk(0x05) and not keys.is_mouse_vk(0x74)
assert keys.BUTTON_TO_VK["x2"] == 0x06 and keys.BUTTON_TO_VK["middle"] == 0x04
hk = keys.Hotkey(0x05)
assert hk.label() == "Mouse X1"
assert keys.Hotkey.parse("Mouse X1") == hk
assert keys.Hotkey.parse("Ctrl+Mouse Middle") == keys.Hotkey(0x04, ctrl=True)
assert config.Settings.from_dict(config.Settings(start_hotkey=hk).to_dict()).start_hotkey == hk
ok("mouse VKs name, parse and round-trip through config")

# --- app wiring ------------------------------------------------------------
print("[2] app hotkey wiring")
fired = []
engine.inputs.click = lambda b="left", hold=0.0: fired.append(b)
engine.inputs.move_to = lambda x, y: None
for mod in ("move_to", "mouse_down", "mouse_up", "key_down", "key_up", "scroll"):
    setattr(recorder.inputs, mod, lambda *a: None)

root = tk.Tk(); theme.init_scaling(root)
theme.apply_ttk(root, theme.get("dark"), theme.fonts())
app = ui.App(root)
pump = lambda n=12: [(root.update(), time.sleep(0.01)) for _ in range(n)]
pump()

X1, X2, MID, LEFT, RIGHT, F5 = 0x05, 0x06, 0x04, 0x01, 0x02, 0x74

# Keyboard-only hotkeys must not install the mouse hook.
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(F5)
app.settings.record_hotkey = keys.Hotkey(0x76)
app.settings.play_hotkey = keys.Hotkey(0x77)
app._sync_mouse_hook(); pump(4)
assert not app._mouse_hooked, "mouse hook should stay off for keyboard-only hotkeys"
ok("global mouse hook stays off when no mouse hotkey is bound")

app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(X1)
app._sync_mouse_hook(); pump(6)
assert app._mouse_hooked and app.hooks._mouse_hook, "mouse hook should install"
ok("binding a mouse hotkey installs the global mouse hook")

# --- the hook path actually starts/stops the engine ------------------------
app._apply_settings(config.Settings(millis=10, start_hotkey=keys.Hotkey(X1),
                                    stop_hotkey=keys.Hotkey(X1)))
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(X1)

down = MouseEvent("down", 100, 200, "x1", 0, False)
up = MouseEvent("up", 100, 200, "x1", 0, False)
swallowed_down = app._on_hook_mouse(down)
pump(15)
assert app.engine.running, "X1 press did not start the engine"
assert swallowed_down is True, "hotkey press should be hidden from other apps"
assert app._on_hook_mouse(up) is True, "the matching release must be hidden too"
ok("X1 press starts clicking through the real hook callback")

app._on_hook_mouse(down); app._on_hook_mouse(up)
time.sleep(0.2); pump(15)
assert not app.engine.running, "second X1 press did not toggle off"
assert len(fired) > 3
ok(f"second X1 press stops it ({len(fired)} clicks emitted)")

# --- injected events must never trigger ------------------------------------
app._on_hook_mouse(MouseEvent("down", 1, 1, "x1", 0, True))
pump(8)
assert not app.engine.running, "injected mouse events must not fire hotkeys"
ok("injected mouse events are ignored (autoclicker can't trigger itself)")

# --- suppression rules -----------------------------------------------------
print("[3] suppression safety")
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(LEFT)
app._swallowed.clear()
assert app._on_hook_mouse(MouseEvent("down", 1, 1, "left", 0, False)) is False, \
    "the left button must never be swallowed"
pump(10); app.stop_clicking(); time.sleep(0.15); pump(10)
app._swallowed.clear()
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(RIGHT)
assert app._on_hook_mouse(MouseEvent("down", 1, 1, "right", 0, False)) is False, \
    "the right button must never be swallowed"
pump(10); app.stop_clicking(); time.sleep(0.15); pump(10)
ok("left and right buttons are never hidden, even when bound")

app._swallowed.clear()
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(MID)
app.settings.suppress_hotkeys = False
assert app._on_hook_mouse(MouseEvent("down", 1, 1, "middle", 0, False)) is False
pump(10); app.stop_clicking(); time.sleep(0.15); pump(10)
app._swallowed.clear()
app.settings.suppress_hotkeys = True
assert app._on_hook_mouse(MouseEvent("down", 1, 1, "middle", 0, False)) is True
pump(10); app.stop_clicking(); time.sleep(0.15); pump(10)
ok("the suppress toggle controls whether the middle button is hidden")

# An unbound button is always passed through untouched.
app._swallowed.clear()
assert app._on_hook_mouse(MouseEvent("down", 1, 1, "x2", 0, False)) is False
assert app._on_hook_mouse(MouseEvent("move", 1, 1, None, 0, False)) is False
assert app._on_hook_mouse(MouseEvent("wheel", 1, 1, None, 120, False)) is False
ok("unbound buttons, moves and the wheel pass straight through")

# Keyboard suppression follows the same rule.
app._swallowed.clear()
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(F5)
assert app._on_hook_key(KeyEvent(F5, True, False)) is True
assert app._on_hook_key(KeyEvent(F5, False, False)) is True, "key release must be hidden too"
assert app._on_hook_key(KeyEvent(0x41, True, False)) is False
pump(12); app.stop_clicking(); time.sleep(0.2); pump(10)
ok("a bound F-key is hidden from other apps; unbound keys are not")

# --- capture accepts a mouse button ---------------------------------------
print("[4] rebinding to a mouse button")
got = []
app.capture_hotkey("start_hotkey", got.append)
assert app._mouse_hooked, "capture must listen to the mouse"
app._on_hook_mouse(MouseEvent("down", 1, 1, "x2", 0, False)); pump(6)
assert not got, "clicks before arming (the click that opened capture) are ignored"
time.sleep(0.4); pump(6)                       # arming delay elapses
app._on_hook_mouse(MouseEvent("down", 1, 1, "x2", 0, False)); pump(8)
assert got and got[0] == keys.Hotkey(X2), got
ok("capture ignores the opening click, then binds Mouse X2")

app.capture_hotkey("start_hotkey", got.append)
time.sleep(0.4); pump(4)
app._on_hook_key(KeyEvent(0x1B, True, False)); pump(8)
assert got[1] is None, "Esc must cancel the capture"
ok("Esc still cancels a capture")

# --- recorder ignores a mouse button used as a hotkey ---------------------
print("[5] recorder")
app.recorder.ignore_vks = {X1}
app.recorder.start(record_moves=False, record_keys=False)
app.recorder._on_mouse(MouseEvent("down", 5, 5, "x1", 0, False))
app.recorder._on_mouse(MouseEvent("down", 5, 5, "left", 0, False))
macro = app.recorder.stop()
assert len(macro) == 1 and macro.events[0].button == "left", [e.describe() for e in macro.events]
ok("a mouse button bound as a hotkey is not baked into recordings")

app.on_close()
print("\nMOUSE HOTKEY TESTS PASSED")
