"""Smoke test: exercises everything except actually injecting clicks."""
import statistics, sys, time, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclicker import config, engine, hooks, inputs, keys, recorder, winapi

ok = lambda m: print(f"  PASS  {m}")

# --- 1. cursor + screen metrics -------------------------------------------
print("[1] win32 basics")
print("   cursor:", inputs.cursor_pos(), " virtual screen:", winapi.virtual_screen_rect())
ok("GetCursorPos / virtual screen metrics")

# --- 2. timing -------------------------------------------------------------
print("[2] precise_sleep accuracy")
inputs.begin_high_resolution_timers()
for target in (0.001, 0.010, 0.100):
    samples = []
    for _ in range(20 if target < 0.05 else 5):
        t0 = time.perf_counter(); inputs.precise_sleep(target); samples.append(time.perf_counter() - t0)
    err = (statistics.mean(samples) - target) * 1000
    print(f"   target {target*1000:7.1f} ms -> mean {statistics.mean(samples)*1000:7.3f} ms  (err {err:+.3f} ms)")
    assert err >= -0.05, "slept short!"
    assert err < 1.5, "sleep overshoot too large"
inputs.end_high_resolution_timers()
ok("sub-millisecond timing")

# --- 3. keys ---------------------------------------------------------------
print("[3] hotkeys")
assert keys.vk_name(0x74) == "F5" and keys.vk_name(0x41) == "A"
hk = keys.Hotkey(0x74, ctrl=True, shift=True)
assert hk.label() == "Ctrl+Shift+F5", hk.label()
assert keys.Hotkey.parse("Ctrl+Shift+F5") == hk
assert keys.Hotkey.parse("Alt+K") == keys.Hotkey(0x4B, alt=True)
assert keys.Hotkey.from_dict(hk.to_dict(), keys.Hotkey(1)) == hk
ok("vk names, labels, parse, round-trip")

# --- 4. config -------------------------------------------------------------
print("[4] config")
s = config.Settings(hours=1, minutes=2, seconds=3, millis=400, start_hotkey=hk)
assert abs(s.fixed_interval() - 3723.4) < 1e-9
assert config.Settings.from_dict(s.to_dict()) == s
assert config.Settings(millis=0).validate(), "zero interval should be rejected"
assert not config.Settings().validate()
assert config.Settings(interval_mode="random", random_min=2, random_max=1).validate()
assert config.Settings(repeat_mode="count", repeat_count=0).validate()
tmp = Path(tempfile.mkdtemp()) / "cfg.json"
config.save(s, tmp); assert config.load(tmp) == s
assert config.safe_profile_name("../evil/../name?") == ".._evil_.._name_"
ok("validation, JSON round-trip, profile name sanitising")

# --- 5. engine (clicks stubbed) -------------------------------------------
print("[5] click engine")
fired = []
real_click, real_move = inputs.click, inputs.move_to
engine.inputs.click = lambda b="left", hold=0.0: fired.append((b, time.perf_counter()))
engine.inputs.move_to = lambda x, y: fired.append(("move", x, y))

done = []
eng = engine.ClickEngine(on_finished=done.append)
assert eng.start(config.Settings(millis=0)) , "invalid settings must be reported"
assert eng.start(config.Settings(millis=10, repeat_mode="count", repeat_count=25)) == []
eng._thread.join(timeout=5)
assert done == ["finished"], done
assert eng.clicks == 25, eng.clicks
stamps = [t for b, t in ((f[0], f[1]) for f in fired if f[0] == "left")]
gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
print(f"   25 clicks @10ms -> mean gap {statistics.mean(gaps):.3f} ms, max {max(gaps):.3f} ms")
assert 9.5 < statistics.mean(gaps) < 12.0
ok("count mode, interval accuracy, finish callback")

fired.clear(); done.clear()
eng2 = engine.ClickEngine(on_finished=done.append)
eng2.start(config.Settings(millis=5, repeat_mode="duration", duration_seconds=0.3))
eng2._thread.join(timeout=5)
assert done == ["finished"] and 40 < eng2.clicks < 75, eng2.clicks
ok(f"duration mode ({eng2.clicks} clicks in 0.3 s)")

fired.clear(); done.clear()
eng3 = engine.ClickEngine(on_finished=done.append)
eng3.start(config.Settings(millis=5))
time.sleep(0.15); eng3.stop(join=True)
assert done == ["stopped"] and eng3.clicks > 5
ok(f"infinite mode stops on request ({eng3.clicks} clicks)")

fired.clear(); done.clear()
eng4 = engine.ClickEngine(on_finished=done.append)
eng4.start(config.Settings(millis=5, repeat_mode="count", repeat_count=4, click_type="double",
                           position_mode="fixed", pos_x=700, pos_y=400, restore_cursor=True))
eng4._thread.join(timeout=5)
moves = [f for f in fired if f[0] == "move"]
clicks = [f for f in fired if f[0] == "left"]
assert len(clicks) == 8, len(clicks)          # double click = 2 presses
assert len(moves) == 8 and moves[0][1:] == (700, 400)   # move there + restore, per click
ok("double click, fixed point, cursor restore")

fired.clear(); done.clear()
eng5 = engine.ClickEngine(on_finished=done.append)
eng5.start(config.Settings(millis=5, repeat_mode="count", repeat_count=6, restore_cursor=False,
                           position_mode="sequence", sequence=[[10, 10], [20, 20], [30, 30]]))
eng5._thread.join(timeout=5)
seq = [f[1:] for f in fired if f[0] == "move"]
assert seq == [(10,10),(20,20),(30,30)]*2, seq
ok("sequence mode cycles through points")

fired.clear(); done.clear()
eng6 = engine.ClickEngine(on_finished=done.append)
eng6.start(config.Settings(interval_mode="random", random_min=0.004, random_max=0.012,
                           repeat_mode="count", repeat_count=40, button="right"))
eng6._thread.join(timeout=10)
rstamps = [f[1] for f in fired if f[0] == "right"]
rgaps = [(b - a) for a, b in zip(rstamps, rstamps[1:])]
assert len(rstamps) == 40 and min(rgaps) < 0.008 < max(rgaps), (min(rgaps), max(rgaps))
ok(f"random interval spread {min(rgaps)*1000:.1f}–{max(rgaps)*1000:.1f} ms, right button")

fired.clear(); done.clear()
eng7 = engine.ClickEngine(on_finished=done.append)
t0 = time.perf_counter()
eng7.start(config.Settings(millis=5, repeat_mode="count", repeat_count=2, start_delay=0.4))
time.sleep(0.15); assert 0.1 < eng7.pending_delay < 0.4, eng7.pending_delay
eng7._thread.join(timeout=5)
assert time.perf_counter() - t0 > 0.4 and eng7.clicks == 2
ok("start delay countdown")

engine.inputs.click, engine.inputs.move_to = real_click, real_move

# --- 6. macros -------------------------------------------------------------
print("[6] macro record/playback plumbing")
E = recorder.Event
m = recorder.Macro([E(0.0, "move", 5, 6), E(0.1, "down", 5, 6, button="left"),
                    E(0.2, "up", 5, 6, button="left"), E(0.3, "key", vk=0x41, pressed=True),
                    E(0.4, "key", vk=0x41), E(0.5, "wheel", 5, 6, delta=120)])
assert m.duration == 0.5 and m.click_points() == [[5, 6]]
p = Path(tempfile.mkdtemp()) / "m.json"
m.save(p)
loaded = recorder.Macro.load(p)
assert [e.describe() for e in loaded.events] == [e.describe() for e in m.events]
assert loaded.events[3].describe() == "Key press A"
ok("save/load round-trip + descriptions")

applied = []
for mod in ("move_to", "mouse_down", "mouse_up", "key_down", "key_up", "scroll"):
    setattr(recorder.inputs, mod, (lambda n: (lambda *a: applied.append((n, *a))))(mod))
pdone = []
pl = recorder.Player(on_finished=pdone.append)
t0 = time.perf_counter()
assert pl.start(loaded, speed=2.0, repeat=2)
pl._thread.join(timeout=5)
took = time.perf_counter() - t0
assert pdone == ["finished"], pdone
assert 0.5 < took < 0.9, took                      # 2 passes of 0.25 s + 0.05 s gap
assert sum(1 for a in applied if a[0] == "mouse_down") == 2
assert sum(1 for a in applied if a[0] == "scroll") == 2
ok(f"playback honours speed & repeat ({took:.2f}s, {len(applied)} actions)")

applied.clear(); pdone.clear()
pl2 = recorder.Player(on_finished=pdone.append)
pl2.start(recorder.Macro([E(0.0, "down", 1, 1, button="left"), E(9.0, "up", 1, 1, button="left")]))
time.sleep(0.2); pl2.stop(join=True)
assert pdone == ["stopped"] and ("mouse_up", "left") in applied, applied
ok("held button is released when playback is cancelled")

# --- 7. hooks --------------------------------------------------------------
print("[7] global hooks")
hm = hooks.HookManager(); hm.start()
seen = []
hm.add_key_listener(seen.append)
hm.add_mouse_listener(seen.append)
time.sleep(0.3)
assert hm._kb_hook and hm._mouse_hook, "hooks not installed"
hm.remove_mouse_listener(seen.append) if False else None
hm.stop()
assert hm._kb_hook is None and hm._mouse_hook is None
ok("keyboard + mouse hooks install and tear down cleanly")

print("\nALL SMOKE TESTS PASSED")
