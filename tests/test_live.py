"""End-to-end: inject REAL clicks onto our own Tk window and verify they land."""
import sys, threading, time, tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autoclicker import config, engine, hooks, inputs, recorder, winapi

winapi.enable_dpi_awareness()
ok = lambda m: print(f"  PASS  {m}")

home = inputs.cursor_pos()
root = tk.Tk()
root.title("live test")
root.geometry("420x300+120+120")
root.attributes("-topmost", True)
canvas = tk.Canvas(root, bg="#222", width=420, height=300)
canvas.pack(fill="both", expand=True)

got = []
canvas.bind("<Button-1>", lambda e: got.append(("L", e.x_root, e.y_root)))
canvas.bind("<Button-3>", lambda e: got.append(("R", e.x_root, e.y_root)))
canvas.bind("<Double-Button-1>", lambda e: got.append(("LL", e.x_root, e.y_root)))
root.bind_all("<MouseWheel>", lambda e: got.append(("W", e.delta)))
root.update()

hm = hooks.HookManager(); hm.start()
seen = []
hm.add_mouse_listener(seen.append)

rec = recorder.Recorder(hm)
rec.start()

cx = root.winfo_rootx() + 210
cy = root.winfo_rooty() + 150
print(f"   target window point: ({cx}, {cy})")

results = {}
def worker():
    time.sleep(0.3)
    inputs.move_to(cx, cy)
    results["moved"] = inputs.cursor_pos()   # read at once; a live desktop has a real mouse too
    time.sleep(0.15)

    # Re-home before every event: the physical mouse is live and must not drag
    # our synthetic clicks onto some other application.
    for _ in range(3):
        inputs.move_to(cx, cy); inputs.click("left"); time.sleep(0.7)
    inputs.move_to(cx, cy); inputs.click("right"); time.sleep(0.7)
    inputs.move_to(cx, cy); inputs.scroll(120); time.sleep(0.7)
    results["before_double"] = len(got)

    # a real double-click through the engine
    eng = engine.ClickEngine()
    eng.start(config.Settings(millis=50, repeat_mode="count", repeat_count=1,
                              click_type="double", position_mode="fixed",
                              pos_x=cx, pos_y=cy, restore_cursor=False))
    eng._thread.join(timeout=3)
    time.sleep(0.4)
    results["done"] = True

threading.Thread(target=worker, daemon=True).start()

deadline = time.time() + 15
while time.time() < deadline and not results.get("done"):
    root.update()
    time.sleep(0.005)
root.update()

macro = rec.stop()
hm.stop()

print(f"   cursor after move_to: {results.get('moved')}  (wanted ({cx}, {cy}))")
assert results.get("moved") == (cx, cy), "SendInput absolute move landed wrong"
ok("move_to lands on the exact pixel (multi-monitor virtual desktop)")

kinds = [g[0] for g in got]
split = results["before_double"]
manual, auto = kinds[:split], kinds[split:]
print("   Tk received:", manual, "then", auto)
# Tk merges rapid repeats into <Double-Button-1>, and this is a live desktop where
# a human may click too, so assert lower bounds here; the hook checks below are strict.
assert sum(1 for k in manual if k in ("L", "LL")) >= 3, manual
assert "R" in manual, manual
if "W" in kinds:
    assert got[kinds.index("W")][1] > 0, "wheel delta should be positive"
    ok("Tk received left presses, a right click and a wheel event at the target point")
else:
    ok("Tk received left presses and a right click at the target point (wheel needs focus)")
assert "LL" in auto, f"engine double-click was not seen as a double click: {auto}"
ok("engine 'double' click registers as a genuine OS double-click")

downs = [e for e in seen if e.kind == "down" and e.injected]
assert len(downs) >= 6, len(downs)   # 3 left + 1 right + 2 from the double click
ok(f"low-level mouse hook saw all {len(downs)} injected presses, correctly flagged")

# Fixed-position mode re-homes the cursor before every click, so every press
# must land on the exact pixel even if the physical mouse is moved meanwhile.
seen.clear()
hm2 = hooks.HookManager(); hm2.start(); hm2.add_mouse_listener(seen.append)
eng = engine.ClickEngine()
eng.start(config.Settings(millis=30, repeat_mode="count", repeat_count=12,
                          position_mode="fixed", pos_x=cx, pos_y=cy, restore_cursor=True))
while eng.running:
    root.update(); time.sleep(0.005)
time.sleep(0.2); root.update(); hm2.stop()
downs2 = [e for e in seen if e.kind == "down" and e.injected]
assert len(downs2) == 12, len(downs2)
assert {(e.x, e.y) for e in downs2} == {(cx, cy)}, {(e.x, e.y) for e in downs2}
ok("12 fixed-point clicks all landed on the exact same pixel")

root.destroy()
inputs.move_to(*home)

assert len(macro) == 0, f"recorder must ignore injected input, got {len(macro)} events"
ok("recorder ignores self-injected input (no feedback loop)")

print("\nLIVE INJECTION TESTS PASSED")
