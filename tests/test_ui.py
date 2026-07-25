"""Drive the real Tk UI headlessly: build it, poke every control, tear it down."""
import os, sys, tempfile, time, tkinter as tk
from pathlib import Path

sandbox = tempfile.mkdtemp()
os.environ["APPDATA"] = sandbox          # keep the real user config untouched
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclicker import config, engine, keys, recorder, theme, ui, widgets, winapi
from autoclicker.hooks import KeyEvent, MouseEvent
from autoclicker.recorder import Event, Macro

winapi.enable_dpi_awareness()
ok = lambda m: print(f"  PASS  {m}")

# Never emit real clicks from this test.
fired = []
engine.inputs.click = lambda b="left", hold=0.0: fired.append(b)
engine.inputs.move_to = lambda x, y: None
for mod in ("move_to", "mouse_down", "mouse_up", "key_down", "key_up", "scroll"):
    setattr(recorder.inputs, mod, lambda *a: None)

root = tk.Tk()
root.title("uitest")
theme.init_scaling(root)
theme.apply_ttk(root, theme.get("dark"), theme.fonts())
app = ui.App(root)
pump = lambda n=8: [(root.update(), time.sleep(0.01)) for _ in range(n)]
pump()
ok("main window builds")

# --- theme -----------------------------------------------------------------
assert app.p.name == "dark"
app.switch_theme(); pump()
assert app.p.name == "light" and app._collect().theme == "light"
assert app.lbl_rate.winfo_exists() and app.btn_start.winfo_exists()
app.switch_theme(); pump()
assert app.p.name == "dark"
ok("dark/light switch rebuilds the whole view without losing widgets")

for name, p in (("dark", theme.DARK), ("light", theme.LIGHT)):
    for field in ("bg", "surface", "raised", "text", "accent", "danger", "success"):
        value = getattr(p, field)
        assert value.startswith("#") and len(value) == 7, (name, field, value)
assert theme.mix("#000000", "#ffffff", 0.5) == "#808080"
assert theme.px(10) >= 10
ok("palettes are well formed and colour mixing works")

# --- settings round trip ---------------------------------------------------
s = config.Settings(
    interval_mode="random", random_min=0.2, random_max=0.9, button="x2",
    click_type="triple", hold_ms=25, hold_jitter_ms=5, repeat_mode="count",
    repeat_count=42, duration_seconds=12.5, start_delay=1.5, position_mode="fixed",
    pos_x=321, pos_y=654, position_jitter=7, restore_cursor=False,
    always_on_top=True, minimize_on_start=True,
)
app._apply_settings(s)
pump(2)
back = app._collect()
for f in ("interval_mode","random_min","random_max","button","click_type","hold_ms",
          "hold_jitter_ms","repeat_mode","repeat_count","duration_seconds","start_delay",
          "position_mode","pos_x","pos_y","position_jitter","restore_cursor",
          "always_on_top","minimize_on_start"):
    assert getattr(back, f) == getattr(s, f), (f, getattr(back, f), getattr(s, f))
assert root.attributes("-topmost") == 1
ok("every widget round-trips settings (18 fields) and always-on-top applies")

# --- enable/disable wiring -------------------------------------------------
app.var_interval_mode.set("fixed"); app._sync_enabled()
assert str(app.fixed_widgets[0]["state"]) == "normal"
assert str(app.random_widgets[0]["state"]) == "disabled"
app.var_interval_mode.set("random"); app._sync_enabled()
assert str(app.fixed_widgets[0]["state"]) == "disabled"
assert str(app.random_widgets[0]["state"]) == "normal"
app.var_repeat_mode.set("duration"); app._sync_enabled()
assert str(app.spin_repeat["state"]) == "disabled" and str(app.spin_duration["state"]) == "normal"
app.var_position_mode.set("current"); app._sync_enabled()
assert str(app.spin_x["state"]) == "disabled" and app.btn_pick.state == "disabled"
app.var_position_mode.set("fixed"); app._sync_enabled()
assert str(app.spin_x["state"]) == "normal" and app.btn_pick.state == "normal"
ok("segmented controls enable/disable the right widgets")

# --- rate readout ----------------------------------------------------------
app._apply_settings(config.Settings(millis=50))
app._update_rate_label(); assert "20.0 clicks per second" in app.lbl_rate["text"], app.lbl_rate["text"]
app._apply_settings(config.Settings(millis=0))
app._update_rate_label(); assert "above zero" in app.lbl_rate["text"]
assert app.lbl_rate["fg"] == app.p.warn, "a bad interval should be flagged in the warn colour"
ok("clicks-per-second readout and zero-interval warning")

# --- bad input is coerced, not crashed on -------------------------------
app.var_millis.set("abc"); app.var_repeat_count.set(""); app.var_rand_max.set("-3")
app._update_rate_label(); got = app._collect()
assert got.millis == 100 and got.repeat_count == 1 and got.random_max == 0.0
ok("garbage in the number fields is coerced, never raises")

# --- starting with an invalid interval is refused ------------------------
errors = []
ui.messagebox.showerror = lambda *a, **k: errors.append(a)
app._apply_settings(config.Settings(millis=0))
app.start_clicking()
assert errors and not app.engine.running, "zero interval must be refused"
ok("Start refuses a zero interval with an error dialog")

# --- start / stop / hotkey toggle -----------------------------------------
app._apply_settings(config.Settings(millis=10, minimize_on_start=False))
app.start_clicking(); pump(20)
assert app.engine.running and app.btn_start.state == "disabled"
assert app.pill._text == "Clicking", app.pill._text
app.stop_clicking(); time.sleep(0.2); pump(10)
assert not app.engine.running and app.btn_start.state == "normal"
assert "Stopped after" in app.lbl_state["text"], app.lbl_state["text"]
assert app.pill._text == "Idle"
n = len(fired); assert n > 5
ok(f"Start/Stop drive the engine ({n} clicks) and update the status pill")

F5 = 0x74
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(F5)
app._handle_key(KeyEvent(F5, True, False)); pump(10)
assert app.engine.running, "hotkey did not start the engine"
app._handle_key(KeyEvent(F5, True, False)); time.sleep(0.2); pump(10)
assert not app.engine.running, "same-key hotkey did not toggle off"
ok("a shared Start/Stop hotkey toggles clicking")

app.settings.start_hotkey = keys.Hotkey(0x70)   # F1
app.settings.stop_hotkey = keys.Hotkey(0x71)    # F2
app._handle_key(KeyEvent(0x70, True, False)); pump(10)
assert app.engine.running
app._handle_key(KeyEvent(0x71, True, False)); time.sleep(0.2); pump(10)
assert not app.engine.running
app._handle_key(KeyEvent(0x70, True, True))     # injected -> must be ignored
pump(4); assert not app.engine.running, "injected keys must not trigger hotkeys"
ok("separate Start/Stop hotkeys work; injected keys are ignored")

# --- mouse buttons as hotkeys ---------------------------------------------
X1 = 0x05
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(X1)
app._sync_mouse_hook(); pump(4)
assert app._mouse_hooked, "a mouse hotkey must install the global mouse hook"
app._apply_settings(config.Settings(millis=10))
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(X1)
assert app._on_hook_mouse(MouseEvent("down", 9, 9, "x1", 0, False)) is True
pump(15)
assert app.engine.running, "Mouse X1 did not start clicking"
assert app._on_hook_mouse(MouseEvent("up", 9, 9, "x1", 0, False)) is True
app._on_hook_mouse(MouseEvent("down", 9, 9, "x1", 0, False))
app._on_hook_mouse(MouseEvent("up", 9, 9, "x1", 0, False))
time.sleep(0.2); pump(12)
assert not app.engine.running, "Mouse X1 did not toggle off"
ok("Mouse X1 starts and stops clicking, and is hidden from other apps")

app._swallowed.clear()
app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(0x01)  # left
assert app._on_hook_mouse(MouseEvent("down", 9, 9, "left", 0, False)) is False, \
    "the left button must never be swallowed"
pump(12)                                  # the hook only queues; the pump acts on it
assert app.engine.running, "a bound left button should still work as a hotkey"
app.stop_clicking(); time.sleep(0.2); pump(10)
assert not app.engine.running
ok("the left button still triggers the hotkey but is never hidden")

app.settings.start_hotkey = app.settings.stop_hotkey = keys.Hotkey(F5)
app.settings.record_hotkey = keys.Hotkey(0x76)
app.settings.play_hotkey = keys.Hotkey(0x77)
app._sync_mouse_hook(); pump(4)
assert not app._mouse_hooked, "the mouse hook should be released once unused"
ok("the mouse hook is released when no mouse hotkey remains")

# --- hotkey capture --------------------------------------------------------
captured = []
app.capture_hotkey("start_hotkey", captured.append)
app._capture_armed = True                          # skip the anti-misfire delay
app._handle_key(KeyEvent(0xA2, True, False))       # Ctrl alone: ignored
assert not captured
app._handle_key(KeyEvent(0x77, True, False))       # F8
assert captured and captured[0].vk == 0x77, captured
app.capture_hotkey("start_hotkey", captured.append)
app._capture_armed = True
app._handle_key(KeyEvent(0x1B, True, False))       # Esc cancels
assert captured[1] is None
app.capture_hotkey("start_hotkey", captured.append)
app._handle_key(KeyEvent(0x77, True, False))       # not armed yet -> ignored
assert len(captured) == 2, "an unarmed capture must ignore input"
app.cancel_capture()
ok("hotkey capture skips modifiers, cancels on Esc, ignores the opening click")

# --- dialogs ---------------------------------------------------------------
hk = ui.HotkeyWindow(app); pump()
assert hk.buttons["start_hotkey"].text == app.settings.start_hotkey.label()
hk.pending["start_hotkey"] = keys.Hotkey(0x73, ctrl=True)   # Ctrl+F4
hk.var_suppress.set(False)
hk.save(); pump()
assert app.settings.start_hotkey.label() == "Ctrl+F4"
assert app.settings.suppress_hotkeys is False
assert "Ctrl+F4" in app.btn_start.text, app.btn_start.text
app.settings.suppress_hotkeys = True
ok("hotkey dialog saves the bindings, the suppress toggle and relabels Start")

app.macro = Macro([Event(0.0, "move", 11, 22), Event(0.1, "down", 11, 22, button="left"),
                   Event(0.2, "up", 11, 22, button="left"),
                   Event(0.3, "down", 33, 44, button="left"),
                   Event(0.4, "up", 33, 44, button="left")])
app.open_macros(); pump()
mw = app._macro_window
assert mw is not None and len(mw.tree.get_children()) == 5
assert "5 events" in mw.lbl_info["text"], mw.lbl_info["text"]
ui.messagebox.showinfo = lambda *a, **k: None
mw.use_as_sequence(); pump()
assert app.settings.sequence == [[11, 22], [33, 44]]
assert app.var_position_mode.get() == "sequence"
assert "2 point(s)" in app.lbl_sequence["text"], app.lbl_sequence["text"]
ok("macro window lists events and exports click points as a sequence")

mw.var_speed.set("2"); mw.var_repeat.set("2"); mw.play(); pump(4)
assert app.player.running
app.player.stop(join=True); pump(6)
ok("macro playback starts and stops from the dialog")

mw.var_loop.set(True); mw._sync_loop()
assert str(mw.spin_repeat["state"]) == "disabled"
p = Path(sandbox) / "m.json"; app.macro.save(p)
assert Macro.load(p).click_points() == [[11, 22], [33, 44]]
mw.clear(); pump(); assert len(app.macro) == 0 and mw.lbl_info["text"] == "No macro loaded"
mw.close(); pump()
assert app._macro_window is None
ok("loop disables repeat; save/load/clear/close all behave")

# --- recording round trip through the UI ----------------------------------
app.open_macros(); pump(); mw = app._macro_window
mw.toggle_record(); pump(4)
assert app.recorder.active and "Stop" in mw.btn_record.text
app.recorder._on_mouse(MouseEvent("down", 5, 6, "left", 0, False))
mw.toggle_record(); pump(4)
assert not app.recorder.active and len(app.macro) == 1
ok("record button toggles the recorder and keeps the captured event")
mw.close(); pump()

# --- profiles --------------------------------------------------------------
app._apply_settings(config.Settings(millis=250, button="right"))
config.save(app._collect(), config.profile_path("my test"))
assert "my test" in config.list_profiles()
app._apply_settings(config.Settings())
app.load_profile("my test"); pump()
assert app._collect().millis == 250 and app._collect().button == "right"
assert "Loaded profile" in app.lbl_state["text"]
ok("profile save + load")

# --- pick location ---------------------------------------------------------
app.var_position_mode.set("fixed"); app._sync_enabled()
app.begin_pick(); pump(2)
assert app._picking and app.btn_pick.state == "disabled" and app._mouse_hooked
assert app._on_hook_mouse(MouseEvent("down", 777, 888, "left", 0, False)) is True, \
    "the picking click must be consumed, not passed to the app underneath"
pump(6)
assert not app._picking and app.var_x.get() == "777" and app.var_y.get() == "888"
app.begin_pick(); app._handle_key(KeyEvent(0x1B, True, False))
assert not app._picking, "Esc must cancel picking"
ok("pick-location consumes the click, captures the point and cancels on Esc")

# --- shutdown --------------------------------------------------------------
app.on_close()
assert os.path.exists(config.config_path()), "settings should persist on close"
assert app.hooks._kb_hook is None
ok("clean shutdown: settings saved, hooks released")

print("\nUI TESTS PASSED")
