"""Record real input and play it back.

A macro is a flat list of timestamped events. Recording listens on the global
hooks and drops anything we injected ourselves, so playing a macro back while
recording can never feed on itself.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import diagnostics
from . import inputs
from .config import config_dir
from .hooks import HookManager, KeyEvent, MouseEvent
from .keys import BUTTON_TO_VK, vk_name

# Movement samples closer together than this are dropped; replaying every
# single hook sample makes huge macros without looking any smoother.
MOVE_SAMPLE_INTERVAL = 0.012

# Loading is deliberately bounded before JSON expansion and while validating
# the resulting list.  These limits are generous for real recordings while
# preventing accidental multi-gigabyte allocations or unbounded replay time.
MACRO_SCHEMA_VERSION = 1
MAX_MACRO_EVENTS = 100_000
MAX_EVENTS = MAX_MACRO_EVENTS  # public alias for integrations/tests
MAX_MACRO_FILE_BYTES = 16 * 1024 * 1024
MAX_MACRO_SIZE_BYTES = MAX_MACRO_FILE_BYTES
MAX_EVENT_TIME_SECONDS = 24 * 60 * 60
MAX_COORDINATE = 2**31 - 1
MAX_WHEEL_DELTA = 2**31 - 1
KNOWN_EVENT_KINDS = frozenset({"move", "down", "up", "wheel", "key"})
KNOWN_BUTTONS = frozenset({inputs.LEFT, inputs.MIDDLE, inputs.RIGHT, inputs.X1, inputs.X2})
EVENT_KINDS = KNOWN_EVENT_KINDS
BUTTONS = KNOWN_BUTTONS


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


def _field(item: dict, name: str, index: int) -> object:
    if name not in item:
        raise ValueError(f"Macro event {index} is missing required field '{name}'.")
    return item[name]


def _number(value: object, name: str, index: int, *, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        kind = "integer" if integer else "number"
        raise ValueError(f"Macro event {index} field '{name}' must be a {kind}.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"Macro event {index} field '{name}' must be finite.")
    if integer and not isinstance(value, int):
        raise ValueError(f"Macro event {index} field '{name}' must be an integer.")
    return value


def _decode_event(item: object, index: int) -> Event:
    if not isinstance(item, dict):
        raise ValueError(f"Macro event {index} must be an object.")

    kind_value = _field(item, "kind", index)
    if not isinstance(kind_value, str):
        raise ValueError(f"Macro event {index} field 'kind' must be a string.")
    kind = kind_value.strip().lower()
    if kind not in KNOWN_EVENT_KINDS:
        allowed = ", ".join(sorted(KNOWN_EVENT_KINDS))
        raise ValueError(f"Macro event {index} has unknown kind {kind_value!r}; expected {allowed}.")

    t_value = _number(_field(item, "t", index), "t", index)
    try:
        t = float(t_value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"Macro event {index} timestamp is outside the supported range.") from exc
    if t < 0 or t > MAX_EVENT_TIME_SECONDS:
        raise ValueError(
            f"Macro event {index} timestamp must be between 0 and {MAX_EVENT_TIME_SECONDS} seconds."
        )

    # Mouse events carry coordinates.  Key events historically serialised the
    # default x/y fields too, but they are irrelevant and remain optional.
    x = y = 0
    if kind != "key" or "x" in item or "y" in item:
        x_value = _number(
            _field(item, "x", index) if kind != "key" else item.get("x", 0),
            "x",
            index,
            integer=True,
        )
        y_value = _number(
            _field(item, "y", index) if kind != "key" else item.get("y", 0),
            "y",
            index,
            integer=True,
        )
        x, y = int(x_value), int(y_value)
        if abs(x) > MAX_COORDINATE or abs(y) > MAX_COORDINATE:
            raise ValueError(f"Macro event {index} coordinates are outside the 32-bit range.")

    button = item.get("button")
    if button is not None:
        if not isinstance(button, str) or button not in KNOWN_BUTTONS:
            allowed = ", ".join(sorted(KNOWN_BUTTONS))
            raise ValueError(f"Macro event {index} has unknown button {button!r}; expected {allowed}.")
    if kind in ("down", "up") and button is None:
        raise ValueError(f"Macro event {index} kind '{kind}' requires a button.")
    if kind not in ("down", "up") and button is not None:
        raise ValueError(f"Macro event {index} kind '{kind}' cannot specify a button.")

    delta = 0
    if kind == "wheel":
        delta_value = _number(_field(item, "delta", index), "delta", index, integer=True)
        delta = int(delta_value)
        if abs(delta) > MAX_WHEEL_DELTA:
            raise ValueError(f"Macro event {index} wheel delta is outside the 32-bit range.")
    elif "delta" in item:
        delta_value = _number(item["delta"], "delta", index, integer=True)
        delta = int(delta_value)
        if abs(delta) > MAX_WHEEL_DELTA:
            raise ValueError(f"Macro event {index} wheel delta is outside the 32-bit range.")

    vk = 0
    pressed = False
    if kind == "key":
        vk_value = _number(_field(item, "vk", index), "vk", index, integer=True)
        vk = int(vk_value)
        if not 1 <= vk <= 0xFF:
            raise ValueError(f"Macro event {index} virtual-key code must be between 1 and 255.")
        pressed_value = _field(item, "pressed", index)
        if not isinstance(pressed_value, bool):
            raise ValueError(f"Macro event {index} field 'pressed' must be a boolean.")
        pressed = pressed_value
    elif "vk" in item:
        vk_value = _number(item["vk"], "vk", index, integer=True)
        vk = int(vk_value)
        if not 0 <= vk <= 0xFF:
            raise ValueError(f"Macro event {index} virtual-key code must be between 0 and 255.")

    if "pressed" in item and kind != "key" and not isinstance(item["pressed"], bool):
        raise ValueError(f"Macro event {index} field 'pressed' must be a boolean.")

    return Event(
        t=t,
        kind=kind,
        x=x,
        y=y,
        button=button,
        delta=delta,
        vk=vk,
        pressed=pressed,
    )


class Macro:
    """An ordered list of :class:`Event` plus load/save helpers."""

    MAX_EVENTS = MAX_MACRO_EVENTS
    MAX_FILE_BYTES = MAX_MACRO_FILE_BYTES

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
        payload = {"version": MACRO_SCHEMA_VERSION, "events": [asdict(e) for e in self.events]}
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Macro":
        target = Path(path)
        try:
            size = target.stat().st_size
        except OSError:
            # Preserve the normal file-not-found/permission exception for the
            # caller; only malformed content is normalised to ValueError below.
            raise
        if size > MAX_MACRO_FILE_BYTES:
            raise ValueError(
                f"Macro file is too large ({size} bytes; maximum is {MAX_MACRO_FILE_BYTES})."
            )

        try:
            with open(target, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError(f"Invalid macro JSON: {exc.msg if hasattr(exc, 'msg') else exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Macro payload must be an object with 'version' and 'events'.")
        version = payload.get("version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("Macro version must be an integer.")
        if version != MACRO_SCHEMA_VERSION:
            raise ValueError(f"Unsupported macro version: {version}.")
        raw = payload.get("events")
        if not isinstance(raw, list):
            raise ValueError("Macro 'events' must be a JSON array.")
        if len(raw) > MAX_MACRO_EVENTS:
            raise ValueError(
                f"Macro contains too many events ({len(raw)}; maximum is {MAX_MACRO_EVENTS})."
            )

        events: list[Event] = []
        for index, item in enumerate(raw):
            events.append(_decode_event(item, index))
        # Existing files were sorted on load; retain that compatibility while
        # rejecting negative/non-finite timestamps above.
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
        self.last_error: str | None = None

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
        self.last_error = None
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
        held_buttons: set[str] = set()
        held_keys: set[int] = set()
        reason = "stopped"
        timers_started = False
        try:
            inputs.begin_high_resolution_timers()
            timers_started = True
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
        except Exception as exc:
            reason = "error"
            self.last_error = f"{type(exc).__name__}: {exc}"
            diagnostics.log_exception("Macro playback failed", exc)
        finally:
            # Never leave a button or key stuck down.
            for button in held_buttons:
                try:
                    inputs.mouse_up(button)
                except Exception as exc:
                    diagnostics.log_exception("Unable to release held mouse button", exc, button=button)
            for vk in held_keys:
                try:
                    inputs.key_up(vk)
                except Exception as exc:
                    diagnostics.log_exception("Unable to release held key", exc, vk=vk)
            if timers_started:
                try:
                    inputs.end_high_resolution_timers()
                except Exception as exc:
                    diagnostics.log_exception("Unable to restore timer resolution", exc)
            if self._on_finished is not None:
                try:
                    self._on_finished(reason)
                except Exception as exc:
                    diagnostics.log_exception("Macro completion callback failed", exc)

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
