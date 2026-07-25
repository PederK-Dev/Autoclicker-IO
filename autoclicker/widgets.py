"""Hand-drawn canvas widgets: rounded buttons, segmented controls, switches, cards.

Tk has no rounded or flat-styled controls, so these draw themselves. Each one
takes the active :class:`~autoclicker.theme.Palette` and redraws on hover, press
and state changes.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import font as tkfont

from .theme import Palette, mix, px


def round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
               r: float, **kw) -> int:
    """Rounded rectangle drawn as a smoothed polygon."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2,
        x1 + r, y2, x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kw)


class PillButton(tk.Canvas):
    """A flat rounded button with hover/press feedback."""

    def __init__(self, parent, text: str, palette: Palette, font: tkfont.Font,
                 command: Callable[[], None] | None = None, kind: str = "soft",
                 width: int | None = None, height: int = 34, radius: int = 9,
                 pad: int = 18, bg: str | None = None) -> None:
        self.p = palette
        self.kind = kind
        self.font = font
        self.command = command
        self._text = text
        self._radius = px(radius)
        self._pad = px(pad)
        self._hover = False
        self._pressed = False
        self._state = "normal"
        self._h = px(height)
        self._fixed_width = px(width) if width else None
        super().__init__(parent, height=self._h, width=self._measure(),
                         bg=bg or palette.surface, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda _e: self._draw())
        self._draw()

    # -- geometry ----------------------------------------------------------

    def _measure(self) -> int:
        if self._fixed_width:
            return self._fixed_width
        return self.font.measure(self._text) + self._pad * 2

    @property
    def text(self) -> str:
        return self._text

    @property
    def state(self) -> str:
        return self._state

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        if not self._fixed_width:
            self.configure(width=self._measure())
        self._draw()

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self.configure(cursor="" if state == "disabled" else "hand2")
        self._draw()

    # -- colours -----------------------------------------------------------

    def _colours(self) -> tuple[str, str, str | None]:
        p = self.p
        base = {
            "accent": (p.accent, p.accent_text, None),
            "success": (p.success, "#ffffff", None),
            "danger": (p.danger, "#ffffff", None),
            "soft": (p.raised, p.text, None),
            "ghost": (p.surface, p.muted, p.border),
        }[self.kind]
        fill, fg, outline = base
        if self._state == "disabled":
            return mix(p.surface, p.raised, 0.5), p.muted, outline
        if self._pressed:
            fill = mix(fill, p.shadow, 0.22)
        elif self._hover:
            fill = mix(fill, p.text, 0.12)
            if self.kind == "ghost":
                fg = p.text
        return fill, fg, outline

    def _draw(self) -> None:
        self.delete("all")
        # An unmapped canvas reports a width of 1, so fall back to our own metric.
        w = self.winfo_width()
        if w <= 1:
            w = self._fixed_width or self._measure()
        h = self._h
        fill, fg, outline = self._colours()
        round_rect(self, 1, 1, w - 1, h - 1, self._radius, fill=fill,
                   outline=outline or fill, width=1)
        self.create_text(w / 2, h / 2 + 1, text=self._text, fill=fg,
                         font=self.font, anchor="center")

    # -- events ------------------------------------------------------------

    def _on_enter(self, _e) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _e) -> None:
        self._hover = self._pressed = False
        self._draw()

    def _on_press(self, _e) -> None:
        if self._state == "disabled":
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _e) -> None:
        fire = self._pressed and self._state != "disabled"
        self._pressed = False
        self._draw()
        if fire and self.command is not None:
            self.command()


class SegmentedControl(tk.Canvas):
    """A row of options with a sliding pill marking the selection."""

    def __init__(self, parent, options: list[tuple[str, str]], variable: tk.StringVar,
                 palette: Palette, font: tkfont.Font, height: int = 32,
                 on_change: Callable[[], None] | None = None, pad: int = 14,
                 bg: str | None = None, equal: bool = True) -> None:
        self.p = palette
        self.font = font
        self.options = options
        self.var = variable
        self.on_change = on_change
        self._equal = equal
        self._pad = px(pad)
        self._inset = px(3)
        self._h = px(height)
        self._hover_index = -1
        self._enabled = True
        self._widths = self._compute_widths()
        super().__init__(parent, height=self._h, width=sum(self._widths) + self._inset * 2,
                         bg=bg or palette.surface, highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self._trace = variable.trace_add("write", lambda *_a: self._draw())
        self._draw()

    def _compute_widths(self) -> list[int]:
        raw = [self.font.measure(label) + self._pad * 2 for label, _ in self.options]
        return [max(raw)] * len(raw) if self._equal else raw

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._draw()

    def _index_at(self, x: float) -> int:
        pos = self._inset
        for i, width in enumerate(self._widths):
            if pos <= x < pos + width:
                return i
            pos += width
        return -1

    def _draw(self) -> None:
        self.delete("all")
        p = self.p
        total = sum(self._widths) + self._inset * 2
        round_rect(self, 0, 0, total, self._h, px(9), fill=p.raised, outline=p.raised)

        current = self.var.get()
        pos = self._inset
        for i, ((label, value), width) in enumerate(zip(self.options, self._widths)):
            selected = value == current
            if selected:
                fill = p.accent if self._enabled else mix(p.raised, p.muted, 0.35)
                round_rect(self, pos, self._inset, pos + width, self._h - self._inset,
                           px(7), fill=fill, outline=fill)
                fg = p.accent_text
            elif not self._enabled:
                fg = mix(p.raised, p.muted, 0.6)
            elif i == self._hover_index:
                fg = p.text
            else:
                fg = p.muted
            self.create_text(pos + width / 2, self._h / 2 + 1, text=label,
                             fill=fg, font=self.font, anchor="center")
            pos += width

    def _on_click(self, event) -> None:
        if not self._enabled:
            return
        index = self._index_at(event.x)
        if index < 0:
            return
        value = self.options[index][1]
        if value != self.var.get():
            self.var.set(value)
        if self.on_change is not None:
            self.on_change()

    def _on_motion(self, event) -> None:
        index = self._index_at(event.x) if self._enabled else -1
        if index != self._hover_index:
            self._hover_index = index
            self._draw()

    def _on_leave(self, _e) -> None:
        if self._hover_index != -1:
            self._hover_index = -1
            self._draw()


class Switch(tk.Canvas):
    """An iOS-style toggle with a caption."""

    def __init__(self, parent, text: str, variable: tk.BooleanVar, palette: Palette,
                 font: tkfont.Font, command: Callable[[], None] | None = None,
                 bg: str | None = None) -> None:
        self.p = palette
        self.font = font
        self.var = variable
        self.command = command
        self._text = text
        self._tw, self._th = px(34), px(18)
        self._gap = px(8)
        self._hover = False
        self._enabled = True
        height = max(self._th, font.metrics("linespace")) + px(6)
        width = self._tw + self._gap + font.measure(text) + px(4)
        super().__init__(parent, width=width, height=height,
                         bg=bg or palette.surface, highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._trace = variable.trace_add("write", lambda *_a: self._draw())
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "")
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        p = self.p
        on = bool(self.var.get())
        cy = self.winfo_reqheight() / 2
        top, bottom = cy - self._th / 2, cy + self._th / 2
        if not self._enabled:
            track = mix(p.raised, p.surface, 0.4)
            knob, fg = p.border, mix(p.muted, p.surface, 0.4)
        else:
            track = p.accent if on else p.raised
            if self._hover:
                track = mix(track, p.text, 0.10)
            knob, fg = "#ffffff" if on else p.muted, p.text
        round_rect(self, 0, top, self._tw, bottom, self._th / 2, fill=track, outline=track)
        r = self._th / 2 - px(3)
        cx = self._tw - self._th / 2 if on else self._th / 2
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=knob, outline=knob)
        self.create_text(self._tw + self._gap, cy + 1, text=self._text, fill=fg,
                         font=self.font, anchor="w")

    def _toggle(self, _e) -> None:
        if not self._enabled:
            return
        self.var.set(not self.var.get())
        if self.command is not None:
            self.command()

    def _on_enter(self, _e) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _e) -> None:
        self._hover = False
        self._draw()


class StatusPill(tk.Canvas):
    """A coloured dot plus label, used for the live run state."""

    def __init__(self, parent, palette: Palette, font: tkfont.Font,
                 width: int = 130, bg: str | None = None) -> None:
        self.p = palette
        self.font = font
        self._text = "Idle"
        self._colour = palette.muted
        self._h = px(26)
        super().__init__(parent, width=px(width), height=self._h,
                         bg=bg or palette.bg, highlightthickness=0, bd=0)
        self._draw()

    def set(self, text: str, colour: str) -> None:
        if (text, colour) == (self._text, self._colour):
            return
        self._text, self._colour = text, colour
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w, h = self.winfo_reqwidth(), self._h
        round_rect(self, 0, 0, w, h, h / 2,
                   fill=mix(self.p.surface, self._colour, 0.16),
                   outline=mix(self.p.border, self._colour, 0.35))
        r = px(4)
        cx, cy = px(14), h / 2
        self.create_oval(cx - r, cy - r, cx + r, cy + r,
                         fill=self._colour, outline=self._colour)
        self.create_text(cx + px(11), cy + 1, text=self._text, fill=self.p.text,
                         font=self.font, anchor="w")


class Card(tk.Frame):
    """A titled surface panel. Put content in ``.body``."""

    def __init__(self, parent, title: str, palette: Palette, fonts: dict[str, tkfont.Font],
                 accent: str | None = None) -> None:
        super().__init__(parent, bg=palette.surface, highlightthickness=1,
                         highlightbackground=palette.border,
                         highlightcolor=palette.border, bd=0)
        self.p = palette
        header = tk.Frame(self, bg=palette.surface)
        header.pack(fill="x", padx=px(14), pady=(px(11), 0))
        bar = tk.Canvas(header, width=px(3), height=px(13), bg=palette.surface,
                        highlightthickness=0, bd=0)
        bar.create_rectangle(0, 0, px(3), px(13), fill=accent or palette.accent,
                             outline=accent or palette.accent)
        bar.pack(side="left", padx=(0, px(8)))
        tk.Label(header, text=title.upper(), bg=palette.surface, fg=palette.muted,
                 font=fonts["card"]).pack(side="left")
        self.header = header
        self.body = tk.Frame(self, bg=palette.surface)
        self.body.pack(fill="both", expand=True, padx=px(14), pady=(px(9), px(13)))


def label(parent, text: str, p: Palette, font: tkfont.Font, muted: bool = False,
          bg: str | None = None) -> tk.Label:
    """A plain themed label. Multi-line text stays left-aligned."""
    return tk.Label(parent, text=text, bg=bg or p.surface,
                    fg=p.muted if muted else p.text, font=font, justify="left")
