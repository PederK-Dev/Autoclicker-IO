"""Global low-level keyboard/mouse hooks running on a dedicated message thread.

Windows requires a hook to be installed from, and serviced by, a thread that
pumps messages. :class:`HookManager` owns that thread; the mouse hook is only
installed while something actually needs it (recording), because a global mouse
hook on the whole desktop is not free.

Callbacks fire on the hook thread and must return fast — they do nothing beyond
appending to a caller-supplied queue or flipping an event. A listener that
returns ``True`` swallows the event so no other application sees it, which is
how a bound hotkey avoids also doing its normal job (F5 refreshing a page, the
middle button starting autoscroll).
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from dataclasses import dataclass

from . import inputs
from . import winapi as w

_MSG_ENABLE_MOUSE = w.WM_APP + 1
_MSG_DISABLE_MOUSE = w.WM_APP + 2
_MSG_STOP = w.WM_APP + 3


@dataclass
class KeyEvent:
    vk: int
    pressed: bool
    injected: bool


@dataclass
class MouseEvent:
    kind: str  # "move" | "down" | "up" | "wheel"
    x: int
    y: int
    button: str | None
    delta: int
    injected: bool


_WHEEL_BUTTONS = {
    w.WM_LBUTTONDOWN: (inputs.LEFT, True),
    w.WM_LBUTTONUP: (inputs.LEFT, False),
    w.WM_RBUTTONDOWN: (inputs.RIGHT, True),
    w.WM_RBUTTONUP: (inputs.RIGHT, False),
    w.WM_MBUTTONDOWN: (inputs.MIDDLE, True),
    w.WM_MBUTTONUP: (inputs.MIDDLE, False),
}


class HookManager:
    """Owns the hook thread and dispatches events to registered listeners."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._kb_hook = None
        self._mouse_hook = None
        # Kept as attributes so the trampolines are not garbage collected while
        # Windows still holds a pointer to them.
        self._kb_proc = w.HOOKPROC(self._on_keyboard)
        self._mouse_proc = w.HOOKPROC(self._on_mouse)
        self._key_listeners: list[Callable[[KeyEvent], None]] = []
        self._mouse_listeners: list[Callable[[MouseEvent], None]] = []
        self._lock = threading.Lock()
        self._down_vks: set[int] = set()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="hook-pump", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("Timed out installing the global keyboard hook.")

    def stop(self) -> None:
        if self._thread_id is not None:
            w.user32.PostThreadMessageW(self._thread_id, _MSG_STOP, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None

    # -- listener registration --------------------------------------------

    def add_key_listener(self, fn: Callable[[KeyEvent], None]) -> None:
        with self._lock:
            self._key_listeners.append(fn)

    def remove_key_listener(self, fn: Callable[[KeyEvent], None]) -> None:
        with self._lock:
            if fn in self._key_listeners:
                self._key_listeners.remove(fn)

    def add_mouse_listener(self, fn: Callable[[MouseEvent], None]) -> None:
        with self._lock:
            self._mouse_listeners.append(fn)
            need_hook = len(self._mouse_listeners) == 1
        if need_hook and self._thread_id is not None:
            w.user32.PostThreadMessageW(self._thread_id, _MSG_ENABLE_MOUSE, 0, 0)

    def remove_mouse_listener(self, fn: Callable[[MouseEvent], None]) -> None:
        with self._lock:
            if fn in self._mouse_listeners:
                self._mouse_listeners.remove(fn)
            idle = not self._mouse_listeners
        if idle and self._thread_id is not None:
            w.user32.PostThreadMessageW(self._thread_id, _MSG_DISABLE_MOUSE, 0, 0)

    # -- hook thread -------------------------------------------------------

    def _run(self) -> None:
        self._thread_id = w.kernel32.GetCurrentThreadId()
        module = w.kernel32.GetModuleHandleW(None)
        self._kb_hook = w.user32.SetWindowsHookExW(
            w.WH_KEYBOARD_LL, self._kb_proc, module, 0
        )
        if not self._kb_hook:
            self._ready.set()
            raise ctypes.WinError(ctypes.get_last_error())
        self._ready.set()

        msg = w.wintypes.MSG()
        while True:
            result = w.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result in (0, -1):
                break
            if not msg.hWnd:  # thread message, not a window message
                if msg.message == _MSG_STOP:
                    break
                if msg.message == _MSG_ENABLE_MOUSE and not self._mouse_hook:
                    self._mouse_hook = w.user32.SetWindowsHookExW(
                        w.WH_MOUSE_LL, self._mouse_proc, module, 0
                    )
                    continue
                if msg.message == _MSG_DISABLE_MOUSE and self._mouse_hook:
                    w.user32.UnhookWindowsHookEx(self._mouse_hook)
                    self._mouse_hook = None
                    continue
            w.user32.TranslateMessage(ctypes.byref(msg))
            w.user32.DispatchMessageW(ctypes.byref(msg))

        if self._mouse_hook:
            w.user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        if self._kb_hook:
            w.user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None

    # -- hook procedures ---------------------------------------------------

    def _on_keyboard(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0:
            data = ctypes.cast(lparam, ctypes.POINTER(w.KBDLLHOOKSTRUCT)).contents
            pressed = wparam in (w.WM_KEYDOWN, w.WM_SYSKEYDOWN)
            injected = bool(data.flags & w.LLKHF_INJECTED) or data.dwExtraInfo == inputs.SIGNATURE
            vk = data.vkCode
            # Collapse auto-repeat into a single logical press.
            repeat = pressed and vk in self._down_vks
            if pressed:
                self._down_vks.add(vk)
            else:
                self._down_vks.discard(vk)
            if not repeat:
                event = KeyEvent(vk=vk, pressed=pressed, injected=injected)
                with self._lock:
                    listeners = list(self._key_listeners)
                swallow = False
                for fn in listeners:
                    try:
                        swallow = bool(fn(event)) or swallow
                    except Exception:
                        pass
                if swallow:
                    return 1
        return w.user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_mouse(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0:
            with self._lock:
                listeners = list(self._mouse_listeners)
            if listeners:
                data = ctypes.cast(lparam, ctypes.POINTER(w.MSLLHOOKSTRUCT)).contents
                injected = (
                    bool(data.flags & w.LLMHF_INJECTED)
                    or data.dwExtraInfo == inputs.SIGNATURE
                )
                event = None
                if wparam == w.WM_MOUSEMOVE:
                    event = MouseEvent("move", data.pt.x, data.pt.y, None, 0, injected)
                elif wparam in _WHEEL_BUTTONS:
                    button, down = _WHEEL_BUTTONS[wparam]
                    event = MouseEvent(
                        "down" if down else "up", data.pt.x, data.pt.y, button, 0, injected
                    )
                elif wparam in (w.WM_XBUTTONDOWN, w.WM_XBUTTONUP):
                    which = inputs.X2 if (data.mouseData >> 16) == w.XBUTTON2 else inputs.X1
                    kind = "down" if wparam == w.WM_XBUTTONDOWN else "up"
                    event = MouseEvent(kind, data.pt.x, data.pt.y, which, 0, injected)
                elif wparam == w.WM_MOUSEWHEEL:
                    delta = ctypes.c_short((data.mouseData >> 16) & 0xFFFF).value
                    event = MouseEvent("wheel", data.pt.x, data.pt.y, None, delta, injected)
                if event is not None:
                    swallow = False
                    for fn in listeners:
                        try:
                            swallow = bool(fn(event)) or swallow
                        except Exception:
                            pass
                    if swallow:
                        return 1
        return w.user32.CallNextHookEx(None, code, wparam, lparam)
