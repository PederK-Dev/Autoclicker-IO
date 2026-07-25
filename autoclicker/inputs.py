"""Synthetic input: real ``SendInput`` events plus high-resolution timing."""

from __future__ import annotations

import ctypes
import threading
import time

from . import winapi as w

# Tagged onto every event we inject so our own hooks can ignore them even when
# the injected flag is unreliable (some remote-desktop stacks strip it).
SIGNATURE = 0x10CC1CE7

LEFT = "left"
MIDDLE = "middle"
RIGHT = "right"
X1 = "x1"
X2 = "x2"

_BUTTON_FLAGS = {
    LEFT: (w.MOUSEEVENTF_LEFTDOWN, w.MOUSEEVENTF_LEFTUP, 0),
    RIGHT: (w.MOUSEEVENTF_RIGHTDOWN, w.MOUSEEVENTF_RIGHTUP, 0),
    MIDDLE: (w.MOUSEEVENTF_MIDDLEDOWN, w.MOUSEEVENTF_MIDDLEUP, 0),
    X1: (w.MOUSEEVENTF_XDOWN, w.MOUSEEVENTF_XUP, w.XBUTTON1),
    X2: (w.MOUSEEVENTF_XDOWN, w.MOUSEEVENTF_XUP, w.XBUTTON2),
}

_extra = ctypes.pointer(w.ULONG_PTR(SIGNATURE))


def _send(*inputs: w.INPUT) -> None:
    array = (w.INPUT * len(inputs))(*inputs)
    sent = w.user32.SendInput(len(inputs), array, ctypes.sizeof(w.INPUT))
    if sent != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())


def _mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> w.INPUT:
    return w.INPUT(
        type=w.INPUT_MOUSE,
        mi=w.MOUSEINPUT(dx=dx, dy=dy, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=_extra),
    )


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


def cursor_pos() -> tuple[int, int]:
    point = w.wintypes.POINT()
    w.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def move_to(x: int, y: int) -> None:
    """Move the pointer using an absolute virtual-desktop event.

    Going through ``SendInput`` (rather than ``SetCursorPos``) means games and
    apps that read raw/relative motion still see a genuine movement event.
    """
    left, top, width, height = w.virtual_screen_rect()
    if width <= 1 or height <= 1:
        w.user32.SetCursorPos(x, y)
        return
    nx = int(round((x - left) * 65535 / (width - 1)))
    ny = int(round((y - top) * 65535 / (height - 1)))
    nx = max(0, min(65535, nx))
    ny = max(0, min(65535, ny))
    _send(
        _mouse_input(
            w.MOUSEEVENTF_MOVE | w.MOUSEEVENTF_ABSOLUTE | w.MOUSEEVENTF_VIRTUALDESK,
            dx=nx,
            dy=ny,
        )
    )


# ---------------------------------------------------------------------------
# Buttons / wheel / keys
# ---------------------------------------------------------------------------


def mouse_down(button: str = LEFT) -> None:
    down, _, data = _BUTTON_FLAGS[button]
    _send(_mouse_input(down, data=data))


def mouse_up(button: str = LEFT) -> None:
    _, up, data = _BUTTON_FLAGS[button]
    _send(_mouse_input(up, data=data))


def click(button: str = LEFT, hold: float = 0.0) -> None:
    """One press/release pair, optionally holding the button down for `hold` s."""
    mouse_down(button)
    if hold > 0:
        precise_sleep(hold)
    mouse_up(button)


def scroll(delta: int, horizontal: bool = False) -> None:
    flag = w.MOUSEEVENTF_HWHEEL if horizontal else w.MOUSEEVENTF_WHEEL
    _send(_mouse_input(flag, data=delta & 0xFFFFFFFF))


def _key_input(vk: int, up: bool) -> w.INPUT:
    scan = w.user32.MapVirtualKeyW(vk, 0)
    flags = w.KEYEVENTF_SCANCODE | (w.KEYEVENTF_KEYUP if up else 0)
    if vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D):
        flags |= w.KEYEVENTF_EXTENDEDKEY
    return w.INPUT(
        type=w.INPUT_KEYBOARD,
        ki=w.KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=_extra),
    )


def key_down(vk: int) -> None:
    _send(_key_input(vk, up=False))


def key_up(vk: int) -> None:
    _send(_key_input(vk, up=True))


def press_key(vk: int, hold: float = 0.0) -> None:
    key_down(vk)
    if hold > 0:
        precise_sleep(hold)
    key_up(vk)


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

_timer_lock = threading.Lock()
_timer_refs = 0

# Below this many seconds we busy-spin instead of sleeping, because even a 1 ms
# timer resolution can overshoot a scheduled wake-up by a full tick.
_SPIN_THRESHOLD = 0.0016


def begin_high_resolution_timers() -> None:
    """Ask the OS for a 1 ms scheduler tick (reference counted)."""
    global _timer_refs
    with _timer_lock:
        if _timer_refs == 0:
            w.winmm.timeBeginPeriod(1)
        _timer_refs += 1


def end_high_resolution_timers() -> None:
    global _timer_refs
    with _timer_lock:
        if _timer_refs > 0:
            _timer_refs -= 1
            if _timer_refs == 0:
                w.winmm.timeEndPeriod(1)


def precise_sleep(duration: float, cancel: threading.Event | None = None) -> bool:
    """Sleep ``duration`` seconds accurately.

    Sleeps coarsely until the last ~1.6 ms, then spins. Returns ``False`` if
    ``cancel`` was set before the time elapsed, ``True`` otherwise.
    """
    if duration <= 0:
        return not (cancel is not None and cancel.is_set())
    deadline = time.perf_counter() + duration
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return True
        if remaining > _SPIN_THRESHOLD:
            slice_ = min(remaining - _SPIN_THRESHOLD, 0.02)
            if cancel is not None:
                if cancel.wait(slice_):
                    return False
            else:
                time.sleep(slice_)
        else:
            if cancel is not None and cancel.is_set():
                return False
            # Final approach: yield the rest of our quantum without sleeping.
            while time.perf_counter() < deadline:
                pass
            return True
