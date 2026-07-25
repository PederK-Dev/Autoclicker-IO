"""Tkinter front end for Autoclicker IO."""

from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import config, inputs, theme
from . import winapi as w
from .engine import ClickEngine
from .hooks import HookManager, KeyEvent, MouseEvent
from .keys import (BUTTON_TO_VK, MODIFIER_VKS, NEVER_SUPPRESS, Hotkey, is_mouse_vk,
                   matches, modifiers_down)
from .recorder import Macro, Player, Recorder, macros_dir
from .theme import px
from .widgets import (Card, PillButton, SegmentedControl, StatusPill, Switch, label,
                      round_rect)

APP_TITLE = "Autoclicker IO"

VK_ESCAPE = 0x1B

BUTTON_CHOICES = [("Left", "left"), ("Middle", "middle"), ("Right", "right"),
                  ("X1", "x1"), ("X2", "x2")]
CLICK_TYPE_CHOICES = [("Single", "single"), ("Double", "double"), ("Triple", "triple")]
INTERVAL_CHOICES = [("Fixed", "fixed"), ("Random", "random")]
REPEAT_CHOICES = [("Until stopped", "infinite"), ("Count", "count"), ("Duration", "duration")]
POSITION_CHOICES = [("Current location", "current"), ("Fixed point", "fixed"),
                    ("Recorded sequence", "sequence")]


def _to_int(value: str, default: int = 0, lo: int | None = None, hi: int | None = None) -> int:
    try:
        result = int(round(float(str(value).strip() or 0)))
    except (TypeError, ValueError):
        result = default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result


def _to_float(value: str, default: float = 0.0, lo: float | None = None) -> float:
    try:
        result = float(str(value).strip() or 0)
    except (TypeError, ValueError):
        result = default
    if lo is not None:
        result = max(lo, result)
    return result


def _format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class App(tk.Frame):
    """Main window. Owns the engine, hooks and recorder; the view is rebuildable."""

    def __init__(self, master: tk.Tk) -> None:
        self.settings = config.load()
        self.p = theme.get(self.settings.theme)
        self.f = theme.fonts()

        super().__init__(master, bg=self.p.bg)
        self.master = master
        self.pack(fill="both", expand=True)

        self.events: queue.Queue = queue.Queue()

        self.hooks = HookManager()
        self.hooks.start()
        self.hooks.add_key_listener(self._on_hook_key)
        self._mouse_hooked = False

        self.engine = ClickEngine(on_finished=lambda why: self.events.put(("engine_done", why)))
        self.recorder = Recorder(self.hooks)
        self.player = Player(on_finished=lambda why: self.events.put(("player_done", why)))
        self.macro = Macro()

        self._pick_armed = False
        self._picking = False
        self._capture_target: str | None = None
        self._capture_callback = None
        self._capture_armed = False
        self._swallowed: set[int] = set()
        self._macro_window: MacroWindow | None = None
        self._status_text = "Idle"

        self.container = tk.Frame(self, bg=self.p.bg)
        self.container.pack(fill="both", expand=True)
        self._build()
        self._apply_settings(self.settings)
        self._refresh_hotkey_labels()
        self._sync_mouse_hook()

        self.master.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(20, self._pump)
        self.after(100, self._tick)

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def switch_theme(self) -> None:
        """Flip dark/light and rebuild the view in place."""
        settings = self._collect()
        settings.theme = "light" if settings.theme == "dark" else "dark"
        self.settings = settings
        self.p = theme.get(settings.theme)
        theme.apply_ttk(self.master, self.p, self.f)
        self.master.configure(bg=self.p.bg)
        self.configure(bg=self.p.bg)
        self.container.destroy()
        self.container = tk.Frame(self, bg=self.p.bg)
        self.container.pack(fill="both", expand=True)
        self._build()
        self._apply_settings(settings)
        self._refresh_hotkey_labels()
        self.lbl_state.configure(text=self._status_text)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _spin(self, parent, var: tk.StringVar, lo, hi, width: int = 6,
              increment: float = 1) -> ttk.Spinbox:
        return ttk.Spinbox(parent, from_=lo, to=hi, increment=increment, width=width,
                           textvariable=var, justify="center")

    def _field(self, parent, caption: str, var: tk.StringVar, lo, hi,
               width: int = 6, increment: float = 1) -> tuple[tk.Frame, ttk.Spinbox]:
        """A spinbox with a small caption underneath."""
        box = tk.Frame(parent, bg=self.p.surface)
        spin = self._spin(box, var, lo, hi, width, increment)
        spin.pack()
        label(box, caption, self.p, self.f["small"], muted=True).pack(pady=(px(2), 0))
        return box, spin

    def _build(self) -> None:
        pad = px(14)
        self._build_header(pad)

        content = tk.Frame(self.container, bg=self.p.bg)
        content.pack(fill="both", expand=True, padx=pad)
        content.columnconfigure(0, weight=1, uniform="col")
        content.columnconfigure(1, weight=1, uniform="col")

        self._build_interval(content)
        self._build_click_options(content)
        self._build_repeat(content)
        self._build_position(content)
        self._build_actions(pad)
        self._build_footer()

    def _build_header(self, pad: int) -> None:
        header = tk.Frame(self.container, bg=self.p.bg)
        header.pack(fill="x", padx=pad, pady=(px(12), px(10)))

        logo = tk.Canvas(header, width=px(30), height=px(30), bg=self.p.bg,
                         highlightthickness=0, bd=0)
        round_rect(logo, 0, 0, px(30), px(30), px(9), fill=self.p.accent,
                   outline=self.p.accent)
        s = theme.scale()
        logo.create_polygon(11 * s, 7 * s, 11 * s, 23 * s, 15.2 * s, 18.6 * s,
                            18 * s, 24 * s, 20.4 * s, 22.6 * s, 17.6 * s, 17.4 * s,
                            23 * s, 16.4 * s, fill=self.p.accent_text,
                            outline=self.p.accent_text)
        logo.pack(side="left")

        titles = tk.Frame(header, bg=self.p.bg)
        titles.pack(side="left", padx=(px(10), 0))
        label(titles, APP_TITLE, self.p, self.f["title"], bg=self.p.bg).pack(anchor="w")

        PillButton(header, "Light mode" if self.p.name == "dark" else "Dark mode",
                   self.p, self.f["base"], command=self.switch_theme, kind="ghost",
                   height=28, pad=12, bg=self.p.bg).pack(side="right")
        PillButton(header, "Options", self.p, self.f["base"], command=self._popup_options,
                   kind="ghost", height=28, pad=12, bg=self.p.bg).pack(side="right", padx=px(6))
        PillButton(header, "Profiles", self.p, self.f["base"], command=self._popup_profiles,
                   kind="ghost", height=28, pad=12, bg=self.p.bg).pack(side="right")
        self.pill = StatusPill(header, self.p, self.f["base"], bg=self.p.bg)
        self.pill.pack(side="right", padx=px(12))

    def _build_interval(self, parent) -> None:
        card = Card(parent, "Click interval", self.p, self.f)
        card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(10)))
        body = card.body

        top = tk.Frame(body, bg=self.p.surface)
        top.pack(fill="x")
        self.var_interval_mode = tk.StringVar(value="fixed")
        SegmentedControl(top, INTERVAL_CHOICES, self.var_interval_mode, self.p,
                         self.f["base"], on_change=self._sync_enabled).pack(side="left")
        self.lbl_rate = label(top, "", self.p, self.f["bold"])
        self.lbl_rate.pack(side="right")

        row = tk.Frame(body, bg=self.p.surface)
        row.pack(fill="x", pady=(px(11), 0))

        self.var_hours = tk.StringVar(value="0")
        self.var_minutes = tk.StringVar(value="0")
        self.var_seconds = tk.StringVar(value="0")
        self.var_millis = tk.StringVar(value="100")
        self.fixed_widgets = []
        for caption, var, cap in [("Hours", self.var_hours, 999), ("Mins", self.var_minutes, 59),
                                  ("Secs", self.var_seconds, 59), ("Millis", self.var_millis, 999)]:
            box, spin = self._field(row, caption, var, 0, cap, width=5)
            box.pack(side="left", padx=(0, px(8)))
            self.fixed_widgets.append(spin)

        tk.Frame(row, bg=self.p.border, width=1).pack(side="left", fill="y",
                                                      padx=px(10), pady=px(2))

        self.var_rand_min = tk.StringVar(value="0.05")
        self.var_rand_max = tk.StringVar(value="0.25")
        self.random_widgets = []
        for caption, var in [("Min secs", self.var_rand_min), ("Max secs", self.var_rand_max)]:
            box, spin = self._field(row, caption, var, 0.001, 3600, width=6, increment=0.05)
            box.pack(side="left", padx=(0, px(8)))
            self.random_widgets.append(spin)

    def _build_click_options(self, parent) -> None:
        card = Card(parent, "Click options", self.p, self.f)
        card.grid(row=1, column=0, sticky="nsew", padx=(0, px(5)), pady=(0, px(10)))
        body = card.body

        label(body, "Mouse button", self.p, self.f["small"], muted=True).pack(anchor="w")
        self.var_button = tk.StringVar(value="left")
        SegmentedControl(body, BUTTON_CHOICES, self.var_button, self.p,
                         self.f["base"], pad=10).pack(anchor="w", pady=(px(4), px(10)))

        label(body, "Click type", self.p, self.f["small"], muted=True).pack(anchor="w")
        self.var_click_type = tk.StringVar(value="single")
        SegmentedControl(body, CLICK_TYPE_CHOICES, self.var_click_type, self.p,
                         self.f["base"], pad=12).pack(anchor="w", pady=(px(4), px(10)))

        row = tk.Frame(body, bg=self.p.surface)
        row.pack(anchor="w")
        self.var_hold = tk.StringVar(value="0")
        self.var_hold_jitter = tk.StringVar(value="0")
        box, _ = self._field(row, "Hold ms", self.var_hold, 0, 5000, width=6)
        box.pack(side="left", padx=(0, px(10)))
        box, _ = self._field(row, "Hold jitter ms", self.var_hold_jitter, 0, 5000, width=6)
        box.pack(side="left")

    def _build_repeat(self, parent) -> None:
        card = Card(parent, "Repeat", self.p, self.f)
        card.grid(row=1, column=1, sticky="nsew", padx=(px(5), 0), pady=(0, px(10)))
        body = card.body

        self.var_repeat_mode = tk.StringVar(value="infinite")
        SegmentedControl(body, REPEAT_CHOICES, self.var_repeat_mode, self.p,
                         self.f["base"], on_change=self._sync_enabled,
                         pad=10).pack(anchor="w", pady=(0, px(11)))

        row = tk.Frame(body, bg=self.p.surface)
        row.pack(anchor="w")
        self.var_repeat_count = tk.StringVar(value="100")
        self.var_duration = tk.StringVar(value="60")
        self.var_start_delay = tk.StringVar(value="0")
        box, self.spin_repeat = self._field(row, "Clicks", self.var_repeat_count,
                                            1, 10_000_000, width=8)
        box.pack(side="left", padx=(0, px(10)))
        box, self.spin_duration = self._field(row, "Duration secs", self.var_duration,
                                              0.1, 86400, width=8)
        box.pack(side="left", padx=(0, px(10)))
        box, _ = self._field(row, "Start delay secs", self.var_start_delay, 0, 3600, width=8)
        box.pack(side="left")

    def _build_position(self, parent) -> None:
        card = Card(parent, "Cursor position", self.p, self.f)
        card.grid(row=2, column=0, columnspan=2, sticky="ew")
        body = card.body

        top = tk.Frame(body, bg=self.p.surface)
        top.pack(fill="x")
        self.var_position_mode = tk.StringVar(value="current")
        SegmentedControl(top, POSITION_CHOICES, self.var_position_mode, self.p,
                         self.f["base"], on_change=self._sync_enabled).pack(side="left")
        self.lbl_cursor = label(top, "Cursor: (0, 0)", self.p, self.f["mono"], muted=True)
        self.lbl_cursor.pack(side="right")

        row = tk.Frame(body, bg=self.p.surface)
        row.pack(fill="x", pady=(px(11), 0))
        self.var_x = tk.StringVar(value="0")
        self.var_y = tk.StringVar(value="0")
        box, self.spin_x = self._field(row, "X", self.var_x, -32000, 32000, width=6)
        box.pack(side="left", padx=(0, px(8)))
        box, self.spin_y = self._field(row, "Y", self.var_y, -32000, 32000, width=6)
        box.pack(side="left", padx=(0, px(10)))
        self.btn_pick = PillButton(row, "Pick location", self.p, self.f["base"],
                                   command=self.begin_pick, kind="soft", height=30)
        self.btn_pick.pack(side="left", pady=(0, px(14)))

        self.var_jitter = tk.StringVar(value="0")
        box, _ = self._field(row, "Jitter px", self.var_jitter, 0, 500, width=5)
        box.pack(side="left", padx=(px(14), 0))

        self.var_restore = tk.BooleanVar(value=True)
        Switch(row, "Restore cursor after each click", self.var_restore, self.p,
               self.f["base"]).pack(side="left", padx=(px(16), 0), pady=(0, px(14)))

        self.lbl_sequence = label(row, "", self.p, self.f["small"], muted=True)
        self.lbl_sequence.pack(side="right", pady=(0, px(14)))

    def _build_actions(self, pad: int) -> None:
        bar = tk.Frame(self.container, bg=self.p.bg)
        bar.pack(fill="x", padx=pad, pady=(px(12), px(10)))

        self.btn_start = PillButton(bar, "Start", self.p, self.f["button"],
                                    command=self.start_clicking, kind="success",
                                    height=42, width=170, bg=self.p.bg)
        self.btn_start.pack(side="left")
        self.btn_stop = PillButton(bar, "Stop", self.p, self.f["button"],
                                   command=self.stop_clicking, kind="danger",
                                   height=42, width=170, bg=self.p.bg)
        self.btn_stop.pack(side="left", padx=px(8))
        self.btn_stop.set_state("disabled")

        PillButton(bar, "Record & playback", self.p, self.f["base"],
                   command=self.open_macros, kind="soft", height=42,
                   bg=self.p.bg).pack(side="right")
        PillButton(bar, "Hotkeys", self.p, self.f["base"], command=self.open_hotkeys,
                   kind="soft", height=42, bg=self.p.bg).pack(side="right", padx=px(8))

    def _build_footer(self) -> None:
        bar = tk.Frame(self.container, bg=self.p.surface, highlightthickness=1,
                       highlightbackground=self.p.border)
        bar.pack(fill="x", side="bottom")
        inner = tk.Frame(bar, bg=self.p.surface)
        inner.pack(fill="x", padx=px(14), pady=px(7))
        self.lbl_state = label(inner, "Idle", self.p, self.f["base"], muted=True)
        self.lbl_state.pack(side="left")
        self.lbl_stats = label(inner, "", self.p, self.f["mono"], muted=True)
        self.lbl_stats.pack(side="right")

    # ------------------------------------------------------------------
    # Popup menus
    # ------------------------------------------------------------------

    def _menu(self) -> tk.Menu:
        return tk.Menu(self, tearoff=0, bg=self.p.raised, fg=self.p.text,
                       activebackground=self.p.accent, activeforeground=self.p.accent_text,
                       bd=0, relief="flat", font=self.f["base"])

    def _popup_profiles(self) -> None:
        menu = self._menu()
        menu.add_command(label="Save profile as…", command=self.save_profile)
        names = config.list_profiles()
        if names:
            menu.add_separator()
            for name in names:
                menu.add_command(label=f"Load  {name}", command=lambda n=name: self.load_profile(n))
        menu.add_separator()
        menu.add_command(label="Reset to defaults", command=self.reset_defaults)
        self._show_menu(menu)

    def _popup_options(self) -> None:
        menu = self._menu()
        self.var_on_top = getattr(self, "var_on_top", tk.BooleanVar(value=False))
        self.var_minimize = getattr(self, "var_minimize", tk.BooleanVar(value=False))
        menu.add_checkbutton(label="Always on top", variable=self.var_on_top,
                             command=self._apply_on_top)
        menu.add_checkbutton(label="Minimize when clicking starts", variable=self.var_minimize)
        menu.add_separator()
        menu.add_command(label="Change hotkeys…", command=self.open_hotkeys)
        menu.add_command(label="About", command=self.show_about)
        self._show_menu(menu)

    def _show_menu(self, menu: tk.Menu) -> None:
        x = self.master.winfo_pointerx()
        y = self.master.winfo_pointery()
        try:
            menu.tk_popup(x, y + px(6))
        finally:
            menu.grab_release()

    # ------------------------------------------------------------------
    # Settings <-> widgets
    # ------------------------------------------------------------------

    def _apply_settings(self, s: config.Settings) -> None:
        self.var_interval_mode.set(s.interval_mode)
        self.var_hours.set(str(s.hours))
        self.var_minutes.set(str(s.minutes))
        self.var_seconds.set(str(s.seconds))
        self.var_millis.set(str(s.millis))
        self.var_rand_min.set(f"{s.random_min:g}")
        self.var_rand_max.set(f"{s.random_max:g}")

        self.var_button.set(s.button)
        self.var_click_type.set(s.click_type)
        self.var_hold.set(str(s.hold_ms))
        self.var_hold_jitter.set(str(s.hold_jitter_ms))

        self.var_repeat_mode.set(s.repeat_mode)
        self.var_repeat_count.set(str(s.repeat_count))
        self.var_duration.set(f"{s.duration_seconds:g}")
        self.var_start_delay.set(f"{s.start_delay:g}")

        self.var_position_mode.set(s.position_mode)
        self.var_x.set(str(s.pos_x))
        self.var_y.set(str(s.pos_y))
        self.var_jitter.set(str(s.position_jitter))
        self.var_restore.set(s.restore_cursor)

        self.var_on_top = getattr(self, "var_on_top", tk.BooleanVar())
        self.var_minimize = getattr(self, "var_minimize", tk.BooleanVar())
        self.var_on_top.set(s.always_on_top)
        self.var_minimize.set(s.minimize_on_start)
        self._apply_on_top()
        self._sync_enabled()

    def _collect(self) -> config.Settings:
        s = self.settings
        s.interval_mode = self.var_interval_mode.get()
        s.hours = _to_int(self.var_hours.get(), 0, 0)
        s.minutes = _to_int(self.var_minutes.get(), 0, 0)
        s.seconds = _to_int(self.var_seconds.get(), 0, 0)
        s.millis = _to_int(self.var_millis.get(), 100, 0)
        s.random_min = _to_float(self.var_rand_min.get(), 0.05, 0.0)
        s.random_max = _to_float(self.var_rand_max.get(), 0.25, 0.0)

        s.button = self.var_button.get()
        s.click_type = self.var_click_type.get()
        s.hold_ms = _to_int(self.var_hold.get(), 0, 0)
        s.hold_jitter_ms = _to_int(self.var_hold_jitter.get(), 0, 0)

        s.repeat_mode = self.var_repeat_mode.get()
        s.repeat_count = _to_int(self.var_repeat_count.get(), 1, 1)
        s.duration_seconds = _to_float(self.var_duration.get(), 60.0, 0.0)
        s.start_delay = _to_float(self.var_start_delay.get(), 0.0, 0.0)

        s.position_mode = self.var_position_mode.get()
        s.pos_x = _to_int(self.var_x.get(), 0)
        s.pos_y = _to_int(self.var_y.get(), 0)
        s.position_jitter = _to_int(self.var_jitter.get(), 0, 0)
        s.restore_cursor = bool(self.var_restore.get())

        s.always_on_top = bool(self.var_on_top.get())
        s.minimize_on_start = bool(self.var_minimize.get())
        s.theme = self.p.name
        return s

    def _sync_enabled(self) -> None:
        fixed = self.var_interval_mode.get() == "fixed"
        for widget in self.fixed_widgets:
            widget.configure(state="normal" if fixed else "disabled")
        for widget in self.random_widgets:
            widget.configure(state="disabled" if fixed else "normal")

        mode = self.var_repeat_mode.get()
        self.spin_repeat.configure(state="normal" if mode == "count" else "disabled")
        self.spin_duration.configure(state="normal" if mode == "duration" else "disabled")

        position = self.var_position_mode.get()
        state = "normal" if position == "fixed" else "disabled"
        self.spin_x.configure(state=state)
        self.spin_y.configure(state=state)
        self.btn_pick.set_state(state)
        self.lbl_sequence.configure(
            text=f"{len(self.settings.sequence)} point(s) captured"
            if position == "sequence" else ""
        )
        self._update_rate_label()

    def _update_rate_label(self) -> None:
        if self.var_interval_mode.get() == "fixed":
            interval = (
                _to_int(self.var_hours.get(), 0, 0) * 3600
                + _to_int(self.var_minutes.get(), 0, 0) * 60
                + _to_int(self.var_seconds.get(), 0, 0)
                + _to_int(self.var_millis.get(), 0, 0) / 1000.0
            )
            bad = interval <= 0
            text = "Interval must be above zero" if bad else f"≈ {1 / interval:,.1f} clicks per second"
        else:
            low = _to_float(self.var_rand_min.get(), 0.05, 0.0)
            high = max(low, _to_float(self.var_rand_max.get(), 0.25, 0.0))
            bad = low <= 0
            text = "Interval must be above zero" if bad else f"≈ {1 / high:,.1f}–{1 / low:,.1f} clicks per second"
        self.lbl_rate.configure(text=text, fg=self.p.warn if bad else self.p.text)

    def _apply_on_top(self) -> None:
        self.master.attributes("-topmost", bool(self.var_on_top.get()))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def start_clicking(self) -> None:
        if self.engine.running or self.player.running or self.recorder.active:
            return
        settings = self._collect()
        problems = self.engine.start(settings)
        if problems:
            messagebox.showerror(APP_TITLE, "\n".join(problems), parent=self.master)
            return
        self.btn_start.set_state("disabled")
        self.btn_stop.set_state("normal")
        if settings.minimize_on_start:
            self.master.iconify()

    def stop_clicking(self) -> None:
        self.engine.stop()
        self.player.stop()

    def toggle_clicking(self) -> None:
        if self.engine.running:
            self.stop_clicking()
        else:
            self.start_clicking()

    def begin_pick(self) -> None:
        """Capture the next real click anywhere on screen as the target point."""
        if self._picking:
            return
        self._picking = True
        self._pick_armed = True
        self._sync_mouse_hook()
        self._set_status("Click anywhere to set the point — Esc cancels")
        self.btn_pick.set_state("disabled")

    def _end_pick(self) -> None:
        if not self._picking:
            return
        self._picking = self._pick_armed = False
        self._sync_mouse_hook()
        self.btn_pick.set_state(
            "normal" if self.var_position_mode.get() == "fixed" else "disabled"
        )

    def open_hotkeys(self) -> None:
        HotkeyWindow(self)

    def open_macros(self) -> None:
        if self._macro_window is not None and self._macro_window.winfo_exists():
            self._macro_window.lift()
            self._macro_window.focus_force()
            return
        self._macro_window = MacroWindow(self)

    def save_profile(self) -> None:
        name = SimplePrompt.ask(self, "Save profile", "Profile name:")
        if not name:
            return
        config.save(self._collect(), config.profile_path(name))
        self._set_status(f"Saved profile “{config.safe_profile_name(name)}”")

    def load_profile(self, name: str) -> None:
        loaded = config.load(config.profile_path(name))
        theme_changed = loaded.theme != self.p.name
        self.settings = loaded
        if theme_changed:
            self.settings.theme = self.p.name   # switch_theme flips it back
            self.switch_theme()
        else:
            self._apply_settings(loaded)
        self._refresh_hotkey_labels()
        self._sync_mouse_hook()
        self._set_status(f"Loaded profile “{name}”")

    def reset_defaults(self) -> None:
        if not messagebox.askyesno(APP_TITLE, "Reset every setting to its default?",
                                   parent=self.master):
            return
        self.settings = config.Settings(theme=self.p.name)
        self._apply_settings(self.settings)
        self._refresh_hotkey_labels()
        self._sync_mouse_hook()

    def show_about(self) -> None:
        messagebox.showinfo(
            APP_TITLE,
            f"{APP_TITLE}\n\n"
            "A dependency-free Windows auto clicker with global keyboard and\n"
            "mouse hotkeys, randomised intervals and full record & playback.\n\n"
            f"Settings are stored in:\n{config.config_dir()}",
            parent=self.master,
        )

    def _refresh_hotkey_labels(self) -> None:
        s = self.settings
        if s.start_hotkey == s.stop_hotkey:
            self._hotkey_summary = f"Start/Stop  {s.start_hotkey.label()}"
        else:
            self._hotkey_summary = (
                f"Start  {s.start_hotkey.label()}   ·   Stop  {s.stop_hotkey.label()}"
            )
        self.btn_start.set_text(f"Start  ·  {s.start_hotkey.label()}")
        self.btn_stop.set_text(f"Stop  ·  {s.stop_hotkey.label()}")

    def _set_status(self, text: str) -> None:
        self._status_text = text
        self.lbl_state.configure(text=text)

    # ------------------------------------------------------------------
    # Hook listeners (these run on the hook thread)
    # ------------------------------------------------------------------

    def _hotkeys(self) -> tuple[Hotkey, ...]:
        s = self.settings
        return (s.start_hotkey, s.stop_hotkey, s.record_hotkey, s.play_hotkey)

    def _sync_mouse_hook(self) -> None:
        """Install the global mouse hook only while something needs it."""
        needed = (
            self._picking
            or self._capture_target is not None
            or any(is_mouse_vk(h.vk) for h in self._hotkeys())
        )
        if needed and not self._mouse_hooked:
            self.hooks.add_mouse_listener(self._on_hook_mouse)
            self._mouse_hooked = True
        elif not needed and self._mouse_hooked:
            self.hooks.remove_mouse_listener(self._on_hook_mouse)
            self._mouse_hooked = False

    def _on_hook_key(self, event: KeyEvent) -> bool:
        if event.injected:
            return False
        self.events.put(("key", event))
        return self._should_swallow(event.vk, event.pressed)

    def _on_hook_mouse(self, event: MouseEvent) -> bool:
        if event.injected or event.kind in ("move", "wheel") or event.button is None:
            return False
        vk = BUTTON_TO_VK.get(event.button)
        if vk is None:
            return False
        if event.kind == "down":
            if self._pick_armed:
                # Consume the click entirely: we want the coordinate, not the click.
                self._pick_armed = False
                self._swallowed.add(vk)
                self.events.put(("picked", (event.x, event.y)))
                return True
            self.events.put(("key", KeyEvent(vk=vk, pressed=True, injected=False)))
            return self._should_swallow(vk, True)
        if vk in self._swallowed:
            self._swallowed.discard(vk)
            return True
        self.events.put(("key", KeyEvent(vk=vk, pressed=False, injected=False)))
        return False

    def _should_swallow(self, vk: int, pressed: bool) -> bool:
        """Decide synchronously whether this event should be hidden from other apps."""
        if not pressed:
            if vk in self._swallowed:
                self._swallowed.discard(vk)
                return True
            return False
        if self._capture_target is not None:
            # While rebinding, eat the key being captured so it does nothing else.
            if self._capture_armed and vk not in MODIFIER_VKS and vk != VK_ESCAPE:
                self._swallowed.add(vk)
                return True
            return False
        if not self.settings.suppress_hotkeys or vk in NEVER_SUPPRESS:
            return False
        if any(matches(h, vk) for h in self._hotkeys()):
            self._swallowed.add(vk)
            return True
        return False

    # ------------------------------------------------------------------
    # Event pump / ticker
    # ------------------------------------------------------------------

    def capture_hotkey(self, target: str, callback) -> None:
        """Route the next key or mouse button to ``callback`` instead of the hotkeys."""
        self._capture_target = target
        self._capture_callback = callback
        self._capture_armed = False
        self._sync_mouse_hook()
        # Ignore the click that started the capture, and its release.
        self.after(350, self._arm_capture)

    def _arm_capture(self) -> None:
        if self._capture_target is not None:
            self._capture_armed = True

    def cancel_capture(self) -> None:
        self._capture_target = None
        self._capture_callback = None
        self._capture_armed = False
        self._sync_mouse_hook()

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "key":
                    self._handle_key(payload)
                elif kind == "engine_done":
                    self._on_engine_done(payload)
                elif kind == "player_done":
                    self._on_player_done(payload)
                elif kind == "picked":
                    self._end_pick()
                    self.var_x.set(str(payload[0]))
                    self.var_y.set(str(payload[1]))
                    self._set_status(f"Point set to ({payload[0]}, {payload[1]})")
        except queue.Empty:
            pass
        self.after(20, self._pump)

    def _handle_key(self, event: KeyEvent) -> None:
        if not event.pressed or event.injected:
            return
        if self._capture_target is not None:
            if not self._capture_armed or event.vk in MODIFIER_VKS:
                return
            callback, self._capture_callback = self._capture_callback, None
            self._capture_target = None
            self._capture_armed = False
            self._sync_mouse_hook()
            if callback is not None:
                if event.vk == VK_ESCAPE:
                    callback(None)
                else:
                    ctrl, shift, alt = modifiers_down()
                    callback(Hotkey(event.vk, ctrl, shift, alt))
            return

        if self._picking and event.vk == VK_ESCAPE:
            self._end_pick()
            self._set_status("Pick cancelled")
            return

        s = self.settings
        if s.start_hotkey == s.stop_hotkey:
            if matches(s.start_hotkey, event.vk):
                self.toggle_clicking()
                return
        else:
            if matches(s.stop_hotkey, event.vk):
                self.stop_clicking()
                return
            if matches(s.start_hotkey, event.vk):
                self.start_clicking()
                return
        if matches(s.record_hotkey, event.vk):
            self.open_macros()
            if self._macro_window is not None:
                self._macro_window.toggle_record()
            return
        if matches(s.play_hotkey, event.vk):
            if self.player.running:
                self.player.stop()
            elif self._macro_window is not None and self._macro_window.winfo_exists():
                self._macro_window.play()
            elif len(self.macro):
                self.player.start(self.macro, s.playback_speed, s.playback_repeat, s.playback_loop)

    def _on_engine_done(self, reason: str) -> None:
        self.btn_start.set_state("normal")
        self.btn_stop.set_state("disabled")
        word = {"finished": "Finished", "error": "Stopped (error)"}.get(reason, "Stopped")
        self._set_status(f"{word} after {self.engine.clicks:,} clicks")
        if self.settings.minimize_on_start:
            self.master.deiconify()

    def _on_player_done(self, reason: str) -> None:
        if self._macro_window is not None and self._macro_window.winfo_exists():
            self._macro_window.on_playback_done(reason)
        self._set_status("Playback finished" if reason == "finished" else "Playback stopped")

    def _tick(self) -> None:
        x, y = inputs.cursor_pos()
        self.lbl_cursor.configure(text=f"Cursor: ({x}, {y})")
        self._update_rate_label()

        if self.engine.running:
            if self.engine.pending_delay > 0:
                self.pill.set("Waiting", self.p.warn)
                self.lbl_state.configure(
                    text=f"Starting in {self.engine.pending_delay:0.1f}s — "
                         f"{self.settings.stop_hotkey.label()} cancels"
                )
            else:
                self.pill.set("Clicking", self.p.success)
                self.lbl_state.configure(text="Clicking")
            self.lbl_stats.configure(
                text=f"{self.engine.clicks:,} clicks   {_format_duration(self.engine.elapsed())}"
            )
            self.btn_start.set_state("disabled")
            self.btn_stop.set_state("normal")
        elif self.recorder.active:
            self.pill.set("Recording", self.p.danger)
            self.lbl_state.configure(text="Recording")
            self.lbl_stats.configure(text=f"{self.recorder.count:,} events")
        elif self.player.running:
            self.pill.set("Playing", self.p.accent)
            self.lbl_state.configure(text=f"Playing back — pass {self.player.iteration}")
            self.lbl_stats.configure(text=f"event {self.player.position + 1:,}/{len(self.macro):,}")
        else:
            self.pill.set("Idle", self.p.muted)
            self.lbl_state.configure(text=self._status_text)
            self.lbl_stats.configure(text=getattr(self, "_hotkey_summary", ""))

        if self._macro_window is not None and self._macro_window.winfo_exists():
            self._macro_window.refresh_counter()
        self.after(100, self._tick)

    # ------------------------------------------------------------------

    def on_close(self) -> None:
        self.engine.stop(join=True)
        self.player.stop(join=True)
        if self.recorder.active:
            self.recorder.stop()
        try:
            config.save(self._collect())
        except OSError:
            pass
        self.hooks.stop()
        self.master.destroy()


class Dialog(tk.Toplevel):
    """Toplevel pre-painted with the active palette."""

    def __init__(self, app: App, title: str) -> None:
        super().__init__(app.master, bg=app.p.bg)
        self.app = app
        self.p = app.p
        self.f = app.f
        self.title(title)
        self.transient(app.master)


class SimplePrompt:
    """Minimal modal text prompt."""

    @staticmethod
    def ask(app: App, title: str, prompt: str, initial: str = "") -> str | None:
        top = Dialog(app, title)
        top.resizable(False, False)
        result: dict[str, str | None] = {"value": None}

        body = tk.Frame(top, bg=app.p.bg)
        body.pack(padx=px(16), pady=px(16))
        label(body, prompt, app.p, app.f["base"], bg=app.p.bg).pack(anchor="w")
        var = tk.StringVar(value=initial)
        entry = ttk.Entry(body, textvariable=var, width=32)
        entry.pack(fill="x", pady=(px(8), px(14)))
        entry.focus_set()

        def accept() -> None:
            result["value"] = var.get().strip()
            top.destroy()

        row = tk.Frame(body, bg=app.p.bg)
        row.pack(fill="x")
        PillButton(row, "Cancel", app.p, app.f["base"], command=top.destroy,
                   kind="ghost", bg=app.p.bg).pack(side="right")
        PillButton(row, "Save", app.p, app.f["base"], command=accept,
                   kind="accent", bg=app.p.bg).pack(side="right", padx=px(8))
        top.bind("<Return>", lambda _e: accept())
        top.bind("<Escape>", lambda _e: top.destroy())
        top.grab_set()
        app.master.wait_window(top)
        return result["value"]


class HotkeyWindow(Dialog):
    """Rebind the global hotkeys — keyboard keys or mouse buttons."""

    FIELDS = [
        ("start_hotkey", "Start clicking"),
        ("stop_hotkey", "Stop clicking"),
        ("record_hotkey", "Start/stop recording"),
        ("play_hotkey", "Start/stop playback"),
    ]

    def __init__(self, app: App) -> None:
        super().__init__(app, "Hotkeys")
        self.resizable(False, False)
        self.pending = {name: getattr(app.settings, name) for name, _ in self.FIELDS}
        self.buttons: dict[str, PillButton] = {}
        self._active: str | None = None

        body = tk.Frame(self, bg=self.p.bg)
        body.pack(fill="both", expand=True, padx=px(16), pady=px(16))

        label(body, "Click a hotkey, then press any key or mouse button.",
              self.p, self.f["base"], bg=self.p.bg).pack(anchor="w")
        label(body, "Mouse X1/X2 (the side buttons) and the middle button work well. "
                    "Esc cancels a capture.",
              self.p, self.f["small"], muted=True, bg=self.p.bg).pack(anchor="w", pady=(px(2), px(14)))

        grid = tk.Frame(body, bg=self.p.bg)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        for i, (name, text) in enumerate(self.FIELDS):
            label(grid, text, self.p, self.f["base"], bg=self.p.bg).grid(
                row=i, column=0, sticky="w", pady=px(4)
            )
            button = PillButton(grid, "", self.p, self.f["base"],
                                command=lambda n=name: self.capture(n), kind="soft",
                                width=190, bg=self.p.bg)
            button.grid(row=i, column=1, sticky="e", padx=(px(20), 0), pady=px(4))
            self.buttons[name] = button

        self.var_suppress = tk.BooleanVar(value=app.settings.suppress_hotkeys)
        Switch(body, "Hide hotkeys from other apps", self.var_suppress, self.p,
               self.f["base"], bg=self.p.bg).pack(anchor="w", pady=(px(14), 0))
        label(body, "Stops a bound middle-click or F-key from also doing its normal job.\n"
                    "The left and right mouse buttons are never hidden.",
              self.p, self.f["small"], muted=True, bg=self.p.bg).pack(anchor="w", pady=(px(3), 0))

        actions = tk.Frame(body, bg=self.p.bg)
        actions.pack(fill="x", pady=(px(18), 0))
        PillButton(actions, "Cancel", self.p, self.f["base"], command=self.close,
                   kind="ghost", bg=self.p.bg).pack(side="right")
        PillButton(actions, "Save", self.p, self.f["base"], command=self.save,
                   kind="accent", bg=self.p.bg).pack(side="right", padx=px(8))

        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grab_set()

    def _refresh(self) -> None:
        for name, button in self.buttons.items():
            button.set_text(self.pending[name].label())

    def capture(self, name: str) -> None:
        self._active = name
        self.buttons[name].set_text("Press any key or button…")

        def done(hotkey: Hotkey | None) -> None:
            self._active = None
            if hotkey is not None:
                self.pending[name] = hotkey
            self._refresh()
            if hotkey is not None and hotkey.vk in NEVER_SUPPRESS:
                messagebox.showwarning(
                    "Hotkeys",
                    f"{hotkey.label()} is a button you use constantly — every normal "
                    "click will trigger this hotkey, and it can never be hidden from "
                    "other apps.\n\nThe side buttons (X1/X2) or the middle button are "
                    "much better choices.",
                    parent=self,
                )

        self.app.capture_hotkey(name, done)

    def save(self) -> None:
        for name, hotkey in self.pending.items():
            setattr(self.app.settings, name, hotkey)
        self.app.settings.suppress_hotkeys = bool(self.var_suppress.get())
        self.app._refresh_hotkey_labels()
        self.app._sync_mouse_hook()
        try:
            config.save(self.app._collect())
        except OSError:
            pass
        self.close()

    def close(self) -> None:
        self.app.cancel_capture()
        self.grab_release()
        self.destroy()


class MacroWindow(Dialog):
    """Record real input, inspect it, replay it, and save it to disk."""

    def __init__(self, app: App) -> None:
        super().__init__(app, "Record & playback")
        self.geometry(f"{px(660)}x{px(500)}")
        self.minsize(px(640), px(430))

        body = tk.Frame(self, bg=self.p.bg)
        body.pack(fill="both", expand=True, padx=px(14), pady=px(14))

        controls = tk.Frame(body, bg=self.p.bg)
        controls.pack(fill="x")
        self.btn_record = PillButton(controls, "Record", self.p, self.f["base"],
                                     command=self.toggle_record, kind="danger",
                                     width=150, bg=self.p.bg)
        self.btn_record.pack(side="left")
        self.btn_play = PillButton(controls, "Play", self.p, self.f["base"],
                                   command=self.play, kind="accent", width=130,
                                   bg=self.p.bg)
        self.btn_play.pack(side="left", padx=px(6))
        for text, cmd in (("Stop", self.stop_playback), ("Clear", self.clear),
                          ("Load", self.load_macro), ("Save", self.save_macro)):
            PillButton(controls, text, self.p, self.f["base"], command=cmd,
                       kind="soft", bg=self.p.bg).pack(side="left", padx=(px(6), 0))

        options = tk.Frame(body, bg=self.p.bg)
        options.pack(fill="x", pady=(px(12), px(10)))

        self.var_moves = tk.BooleanVar(value=True)
        self.var_keys = tk.BooleanVar(value=True)
        label(options, "Capture", self.p, self.f["small"], muted=True,
              bg=self.p.bg).pack(side="left", padx=(0, px(8)))
        Switch(options, "Mouse movement", self.var_moves, self.p, self.f["base"],
               bg=self.p.bg).pack(side="left")
        Switch(options, "Keyboard", self.var_keys, self.p, self.f["base"],
               bg=self.p.bg).pack(side="left", padx=(px(12), 0))

        self.var_loop = tk.BooleanVar(value=app.settings.playback_loop)
        Switch(options, "Loop", self.var_loop, self.p, self.f["base"],
               command=self._sync_loop, bg=self.p.bg).pack(side="right")
        self.var_repeat = tk.StringVar(value=str(app.settings.playback_repeat))
        self.spin_repeat = ttk.Spinbox(options, from_=1, to=100000, width=6,
                                       textvariable=self.var_repeat, justify="center")
        self.spin_repeat.pack(side="right", padx=(px(4), px(12)))
        label(options, "Repeat", self.p, self.f["small"], muted=True,
              bg=self.p.bg).pack(side="right")
        self.var_speed = tk.StringVar(value=f"{app.settings.playback_speed:g}")
        ttk.Spinbox(options, from_=0.1, to=20, increment=0.25, width=5,
                    textvariable=self.var_speed, justify="center").pack(
            side="right", padx=(px(4), px(14)))
        label(options, "Speed", self.p, self.f["small"], muted=True,
              bg=self.p.bg).pack(side="right")

        table = tk.Frame(body, bg=self.p.border, highlightthickness=0)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("time", "event"), show="headings")
        self.tree.heading("time", text="TIME", anchor="e")
        self.tree.heading("event", text="EVENT", anchor="w")
        self.tree.column("time", width=px(90), anchor="e", stretch=False)
        self.tree.column("event", width=px(430), anchor="w")
        self.tree.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("odd", background=theme.mix(self.p.raised, self.p.surface, 0.5))

        footer = tk.Frame(body, bg=self.p.bg)
        footer.pack(fill="x", pady=(px(10), 0))
        self.lbl_info = label(footer, "No macro loaded", self.p, self.f["base"],
                              muted=True, bg=self.p.bg)
        self.lbl_info.pack(side="left")
        PillButton(footer, "Use click points as sequence", self.p, self.f["base"],
                   command=self.use_as_sequence, kind="ghost",
                   bg=self.p.bg).pack(side="right")

        self._sync_loop()
        self._populate()
        self.protocol("WM_DELETE_WINDOW", self.close)

    # -- helpers -----------------------------------------------------------

    def _sync_loop(self) -> None:
        self.spin_repeat.configure(state="disabled" if self.var_loop.get() else "normal")

    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        events = self.app.macro.events
        # Long macros make the tree crawl; show the head and tail instead.
        shown = events if len(events) <= 500 else events[:250] + events[-250:]
        for i, event in enumerate(shown):
            if len(events) > 500 and i == 250:
                self.tree.insert("", "end", values=("…", f"{len(events) - 500:,} more events"))
            self.tree.insert("", "end", values=(f"{event.t:.3f}s", event.describe()),
                             tags=("odd",) if i % 2 else ())
        self.refresh_counter()

    def refresh_counter(self) -> None:
        record_key = self.app.settings.record_hotkey.label()
        if self.app.recorder.active:
            self.lbl_info.configure(text=f"Recording… {self.app.recorder.count:,} events captured")
            self.btn_record.set_text(f"Stop  ·  {record_key}")
        else:
            self.btn_record.set_text(f"Record  ·  {record_key}")
            macro = self.app.macro
            self.lbl_info.configure(
                text=f"{len(macro):,} events   ·   {macro.duration:0.2f}s"
                if len(macro) else "No macro loaded"
            )
        play_key = self.app.settings.play_hotkey.label()
        self.btn_play.set_text(
            f"Stop  ·  {play_key}" if self.app.player.running else f"Play  ·  {play_key}"
        )

    # -- actions -----------------------------------------------------------

    def toggle_record(self) -> None:
        recorder = self.app.recorder
        if recorder.active:
            self.app.macro = recorder.stop()
            self._populate()
            return
        if self.app.engine.running or self.app.player.running:
            return
        # Don't bake the app's own hotkeys into the macro.
        recorder.ignore_vks = {h.vk for h in self.app._hotkeys()}
        recorder.start(record_moves=self.var_moves.get(), record_keys=self.var_keys.get())
        self.tree.delete(*self.tree.get_children())
        self.refresh_counter()

    def play(self) -> None:
        if self.app.player.running:
            self.stop_playback()
            return
        if self.app.recorder.active or self.app.engine.running:
            return
        if not len(self.app.macro):
            messagebox.showinfo("Record & playback", "Record or load a macro first.", parent=self)
            return
        speed = _to_float(self.var_speed.get(), 1.0, 0.05)
        repeat = _to_int(self.var_repeat.get(), 1, 1)
        loop = bool(self.var_loop.get())
        self.app.settings.playback_speed = speed
        self.app.settings.playback_repeat = repeat
        self.app.settings.playback_loop = loop
        self.app.player.start(self.app.macro, speed, repeat, loop)
        self.refresh_counter()

    def stop_playback(self) -> None:
        self.app.player.stop()

    def on_playback_done(self, _reason: str) -> None:
        self.refresh_counter()

    def clear(self) -> None:
        if self.app.recorder.active:
            return
        self.app.macro = Macro()
        self._populate()

    def save_macro(self) -> None:
        if not len(self.app.macro):
            messagebox.showinfo("Record & playback", "Nothing to save yet.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save macro", defaultextension=".json",
            initialdir=str(macros_dir()), filetypes=[("Macro files", "*.json")],
        )
        if path:
            self.app.macro.save(Path(path))
            self.lbl_info.configure(text=f"Saved to {Path(path).name}")

    def load_macro(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Load macro", initialdir=str(macros_dir()),
            filetypes=[("Macro files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.app.macro = Macro.load(Path(path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Record & playback", f"Could not load that macro:\n{exc}",
                                 parent=self)
            return
        self._populate()

    def use_as_sequence(self) -> None:
        points = self.app.macro.click_points()
        if not points:
            messagebox.showinfo("Record & playback", "This macro has no click points.", parent=self)
            return
        self.app.settings.sequence = points
        self.app.var_position_mode.set("sequence")
        self.app._sync_enabled()
        messagebox.showinfo(
            "Record & playback",
            f"{len(points)} click point(s) are now the click sequence.\n"
            "The clicker will cycle through them.",
            parent=self,
        )

    def close(self) -> None:
        if self.app.recorder.active:
            self.app.macro = self.app.recorder.stop()
        self.app._macro_window = None
        self.destroy()


def run() -> None:
    w.enable_dpi_awareness()
    root = tk.Tk()
    root.title(APP_TITLE)
    root.resizable(False, False)
    theme.init_scaling(root)

    settings = config.load()
    palette = theme.get(settings.theme)
    root.configure(bg=palette.bg)
    theme.apply_ttk(root, palette, theme.fonts())

    App(root)
    root.mainloop()
