"""The click engine: a worker thread that emits clicks on a schedule."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable

from . import diagnostics
from . import inputs
from .config import Settings

CLICK_REPEATS = {"single": 1, "double": 2, "triple": 3}

# Gap between the presses of a double/triple click. Comfortably under the
# Windows default double-click time (500 ms) so the OS groups them.
_MULTI_CLICK_GAP = 0.035


class ClickEngine:
    """Runs a click loop on its own thread until stopped or finished.

    All public methods are safe to call from any thread. ``on_finished`` fires
    on the worker thread once the loop exits, with the reason as a string.
    """

    def __init__(self, on_finished: Callable[[str], None] | None = None) -> None:
        self._on_finished = on_finished
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.clicks = 0
        self.started_at = 0.0
        self.pending_delay = 0.0
        # A concise, UI-friendly description of the most recent worker error.
        # ``None`` means the engine has not failed since the last start.
        self.last_error: str | None = None

    # -- state -------------------------------------------------------------

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def elapsed(self) -> float:
        return 0.0 if not self.started_at else time.perf_counter() - self.started_at

    # -- control -----------------------------------------------------------

    def start(self, settings: Settings) -> list[str]:
        """Begin clicking. Returns validation problems; non-empty means nothing started."""
        with self._lock:
            if self.running:
                return []
            self.last_error = None
            try:
                problems = settings.validate()
            except Exception as exc:
                self.last_error = f"Settings validation failed: {exc}"
                diagnostics.log_exception("Click engine settings validation failed", exc)
                return [self.last_error]
            if problems:
                return problems
            self._cancel.clear()
            self.clicks = 0
            self.started_at = 0.0
            self.pending_delay = settings.start_delay
            self._thread = threading.Thread(
                target=self._run, args=(settings,), name="click-engine", daemon=True
            )
            self._thread.start()
            return []

    def stop(self, join: bool = False) -> None:
        self._cancel.set()
        if join:
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)

    # -- worker ------------------------------------------------------------

    def _run(self, settings: Settings) -> None:
        reason = "stopped"
        timers_started = False
        try:
            inputs.begin_high_resolution_timers()
            timers_started = True
            if settings.start_delay > 0:
                deadline = time.perf_counter() + settings.start_delay
                while True:
                    remaining = deadline - time.perf_counter()
                    self.pending_delay = max(0.0, remaining)
                    if remaining <= 0:
                        break
                    if self._cancel.wait(min(remaining, 0.05)):
                        return
            self.pending_delay = 0.0

            self.started_at = time.perf_counter()
            deadline = (
                self.started_at + settings.duration_seconds
                if settings.repeat_mode == "duration"
                else None
            )
            limit = settings.repeat_count if settings.repeat_mode == "count" else None
            repeats = CLICK_REPEATS.get(settings.click_type, 1)
            sequence = [tuple(p) for p in settings.sequence] if settings.sequence else []
            index = 0

            while not self._cancel.is_set():
                if limit is not None and self.clicks >= limit:
                    reason = "finished"
                    break
                if deadline is not None and time.perf_counter() >= deadline:
                    reason = "finished"
                    break

                target = self._resolve_target(settings, sequence, index)
                if target is not None:
                    index += 1
                self._emit(settings, target, repeats)
                self.clicks += 1

                interval = self._next_interval(settings)
                if not inputs.precise_sleep(interval, self._cancel):
                    break
        except Exception as exc:
            reason = "error"
            self.last_error = f"{type(exc).__name__}: {exc}" or type(exc).__name__
            diagnostics.log_exception("Click engine worker failed", exc)
        finally:
            if timers_started:
                try:
                    inputs.end_high_resolution_timers()
                except Exception as exc:
                    diagnostics.log_exception("Unable to restore timer resolution", exc)
            self.pending_delay = 0.0
            if self._on_finished is not None:
                try:
                    self._on_finished(reason)
                except Exception as exc:
                    diagnostics.log_exception("Click engine completion callback failed", exc)

    # -- helpers -----------------------------------------------------------

    def _resolve_target(
        self, settings: Settings, sequence: list[tuple[int, int]], index: int
    ) -> tuple[int, int] | None:
        """Where this click should land, or ``None`` to click where the cursor is."""
        if settings.position_mode == "fixed":
            point = (settings.pos_x, settings.pos_y)
        elif settings.position_mode == "sequence" and sequence:
            point = sequence[index % len(sequence)]
        else:
            return None
        jitter = settings.position_jitter
        if jitter > 0:
            point = (
                point[0] + random.randint(-jitter, jitter),
                point[1] + random.randint(-jitter, jitter),
            )
        return point

    def _emit(
        self, settings: Settings, target: tuple[int, int] | None, repeats: int
    ) -> None:
        origin = None
        try:
            if target is not None:
                if settings.restore_cursor:
                    origin = inputs.cursor_pos()
                inputs.move_to(*target)

            hold = max(0, settings.hold_ms) / 1000.0
            if settings.hold_jitter_ms > 0:
                hold += random.uniform(0, settings.hold_jitter_ms / 1000.0)

            for i in range(repeats):
                if i:
                    inputs.precise_sleep(_MULTI_CLICK_GAP, self._cancel)
                    if self._cancel.is_set():
                        break
                inputs.click(settings.button, hold)
        finally:
            if origin is not None:
                # Cursor restoration is part of the click contract.  If the
                # restore itself fails, let the worker's outer handler record
                # the error while still attempting it exactly once.
                inputs.move_to(*origin)

    def _next_interval(self, settings: Settings) -> float:
        if settings.interval_mode == "random":
            low, high = sorted((settings.random_min, settings.random_max))
            return random.uniform(low, high)
        return settings.fixed_interval()
