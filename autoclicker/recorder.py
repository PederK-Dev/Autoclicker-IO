"""Record real input and play it back.

A macro is a flat list of timestamped events. Recording listens on the global
hooks and drops anything we injected ourselves, so playing a macro back while
recording can never feed on itself.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import inputs
from .config import config_dir
from .hooks import HookManager, KeyEvent, MouseEvent
from .keys import BUTTON_TO_VK, vk_name

# Movement samples closer together than this are dropped; replaying every
# single hook sample makes huge macros without looking any smoother.
MOVE_SAMPLE_INTERVAL = 0.012


def macros_dir() -> Path:
    path = config_dir() / "macros"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Event:
    t: float  # seconds since the recording started
    kind: str  # move | down | up | wheel | key
    x: int = 0
    y: int = 0
    button: str | None = None
    delta: int = 0
    vk: int = 0
    pressed: bool = False

    def describe(self) -> str:
        if self.kind == "move":
            return f"Move to ({self.x}, {self.y})"
        if self.kind in ("down", "up"):
            verb = "press" if self.kind == "down" else "release"
            return f"Mouse {verb} {self.button} at ({self.x}, {self.y})"
        if self.kind == "wheel":
            return f"Scroll {self.delta:+d} at ({self.x}, {self.y})"
        verb = "press" if self.pressed else "release"
        return f"Key {verb} {vk_name(self.vk)}"


class Macro:
    """An ordered list of :class:`Event` plus load/save helpers."""

    def __init__(self, events: list[Event] | None = None) -> None:
        self.events: list[Event] = events or []

    def __len__(self) -> int:
        return len(self.events)

    @property
    def duration(self) -> float:
        return self.events[-1].t if self.events else 0.0

    def click_points(self) -> list[list[int]]:
        """Just the press locations — handy as a click-sequence source."""
        return [[e.x, e.y] for e in self.events if e.kind == "down"]

    def save(self, path: Path) -> None:
        payload = {"version": 1, "events": [asdict(e) for e in self.events]}
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Macro":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw = payload.get("events", []) if isinstance(payload, dict) else payload
        events = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            events.append(
                Event(
                    t=float(item.get("t", 0.0)),
                    kind=str(item.get("kind", "move")),
                    x=int(item.get("x", 0)),
                    y=int(item.get("y", 0)),
                    button=item.get("button"),
                    delta=int(item.get("delta", 0)),
                    vk=int(item.get("vk", 0)),
                    pressed=bool(item.get("pressed", False)),
                )
            )
        events.sort(key=lambda e: e.t)
        return cls(events)


class Recorder:
    """Captures live input into a :class:`Macro`."""

    def __init__(self, hooks: HookManager) -> None:
        self._hooks = hooks
        self._events: list[Event] = []
        self._t0 = 0.0
        self._last_move = 0.0
        self._active = False
        self._lock = threading.Lock()
        self.record_moves = True
        self.record_keys = True
        self.ignore_vks: set[int] = set()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def count(self) -> int:
        return len(self._events)

    def start(self, record_moves: bool = True, record_keys: bool = True) -> None:
        if self._active:
            return
        self.record_moves = record_moves
        self.record_keys = record_keys
        with self._lock:
            self._events = []
        self._t0 = time.perf_counter()
        self._last_move = 0.0
        self._active = True
        self._hooks.add_mouse_listener(self._on_mouse)
        self._hooks.add_key_listener(self._on_key)

    def stop(self) -> Macro:
        if self._active:
            self._active = False
            self._hooks.remove_mouse_listener(self._on_mouse)
            self._hooks.remove_key_listener(self._on_key)
        with self._lock:
            events = list(self._events)
        # A trailing hotkey press that ended the recording adds nothing useful.
        while events and events[-1].kind == "move":
            events.pop()
        return Macro(events)

    # -- listeners (hook thread) ------------------------------------------

    def _append(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)

    def _on_mouse(self, event: MouseEvent) -> None:
        if not self._active or event.injected:
            return
        # A mouse button bound as a hotkey controls the app; don't record it.
        if event.button is not None and BUTTON_TO_VK.get(event.button) in self.ignore_vks:
            return
        now = time.perf_counter() - self._t0
        if event.kind == "move":
            if not self.record_moves or now - self._last_move < MOVE_SAMPLE_INTERVAL:
                return
            self._last_move = now
            self._append(Event(t=now, kind="move", x=event.x, y=event.y))
        elif event.kind == "wheel":
            self._append(Event(t=now, kind="wheel", x=event.x, y=event.y, delta=event.delta))
        else:
            self._append(
                Event(t=now, kind=event.kind, x=event.x, y=event.y, button=event.button)
            )

    def _on_key(self, event: KeyEvent) -> None:
        if not self._active or event.injected or not self.record_keys:
            return
        if event.vk in self.ignore_vks:
            return
        now = time.perf_counter() - self._t0
        self._append(Event(t=now, kind="key", vk=event.vk, pressed=event.pressed))


class Player:
    """Replays a macro on a worker thread, honouring the original timing."""

    def __init__(self, on_finished: Callable[[str], None] | None = None) -> None:
        self._on_finished = on_finished
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self.iteration = 0
        self.position = 0

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(
        self,
        macro: Macro,
        speed: float = 1.0,
        repeat: int = 1,
        loop: bool = False,
    ) -> bool:
        if self.running or not macro.events:
            return False
        self._cancel.clear()
        self.iteration = 0
        self.position = 0
        self._thread = threading.Thread(
            target=self._run,
            args=(macro, max(0.05, speed), max(1, repeat), loop),
            name="macro-player",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self, join: bool = False) -> None:
        self._cancel.set()
        if join:
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)

    def _run(self, macro: Macro, speed: float, repeat: int, loop: bool) -> None:
        inputs.begin_high_resolution_timers()
        held_buttons: set[str] = set()
        held_keys: set[int] = set()
        reason = "stopped"
        try:
            pass_index = 0
            while not self._cancel.is_set():
                self.iteration = pass_index + 1
                origin = time.perf_counter()
                for i, event in enumerate(macro.events):
                    self.position = i
                    if not inputs.precise_sleep(
                        (event.t / speed) - (time.perf_counter() - origin), self._cancel
                    ):
                        return
                    self._apply(event, held_buttons, held_keys)
                pass_index += 1
                if not loop and pass_index >= repeat:
                    reason = "finished"
                    break
                # Small breather between passes so apps see distinct runs.
                if not inputs.precise_sleep(0.05, self._cancel):
                    return
        finally:
            # Never leave a button or key stuck down.
            for button in held_buttons:
                try:
                    inputs.mouse_up(button)
                except Exception:
                    pass
            for vk in held_keys:
                try:
                    inputs.key_up(vk)
                except Exception:
                    pass
            inputs.end_high_resolution_timers()
            if self._on_finished is not None:
                try:
                    self._on_finished(reason)
                except Exception:
                    pass

    @staticmethod
    def _apply(event: Event, held_buttons: set[str], held_keys: set[int]) -> None:
        if event.kind == "move":
            inputs.move_to(event.x, event.y)
        elif event.kind == "down" and event.button:
            inputs.move_to(event.x, event.y)
            inputs.mouse_down(event.button)
            held_buttons.add(event.button)
        elif event.kind == "up" and event.button:
            inputs.move_to(event.x, event.y)
            inputs.mouse_up(event.button)
            held_buttons.discard(event.button)
        elif event.kind == "wheel":
            inputs.move_to(event.x, event.y)
            inputs.scroll(event.delta)
        elif event.kind == "key":
            if event.pressed:
                inputs.key_down(event.vk)
                held_keys.add(event.vk)
            else:
                inputs.key_up(event.vk)
                held_keys.discard(event.vk)
