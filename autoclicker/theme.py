"""Colour palettes, DPI scaling and ttk styling.

Tk gives us no modern look out of the box, so the palette here drives both the
hand-drawn canvas widgets in :mod:`widgets` and a reskinned ``clam`` ttk theme
for the stock controls (entries, spinboxes, tree views, scrollbars).
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

from . import winapi as w

FONT_FAMILY = "Segoe UI"

# Pixel scale for hand-drawn widgets. Set once at startup from the system DPI.
_scale = 1.0


def px(value: float) -> int:
    """Scale a design pixel value for the current display."""
    return max(1, round(value * _scale))


def set_scale(value: float) -> None:
    global _scale
    _scale = value


def scale() -> float:
    return _scale


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str           # window background
    surface: str      # card background
    raised: str       # inputs, segmented-control troughs
    hover: str        # hover wash over `raised`
    border: str
    text: str
    muted: str        # secondary text
    accent: str       # primary action / selection
    accent_text: str  # text drawn on top of `accent`
    success: str
    danger: str
    warn: str
    shadow: str


DARK = Palette(
    name="dark",
    bg="#101318",
    surface="#191d25",
    raised="#232936",
    hover="#2c3342",
    border="#2b3240",
    text="#e8ecf3",
    muted="#8d97a8",
    # Action colours are deliberately a little deeper than the decorative
    # palette so white labels retain WCAG AA contrast on both themes.
    accent="#386fcb",
    accent_text="#ffffff",
    success="#1f8348",
    danger="#c23340",
    warn="#e2a33c",
    shadow="#0a0c10",
)

LIGHT = Palette(
    name="light",
    bg="#eef1f6",
    surface="#ffffff",
    raised="#e7ebf2",
    hover="#dbe1ea",
    border="#d3dae4",
    text="#141922",
    muted="#5f6b7d",
    accent="#2f6fe4",
    accent_text="#ffffff",
    success="#0f7d42",
    danger="#d63b48",
    warn="#c17d10",
    shadow="#c3cad6",
)

PALETTES = {"dark": DARK, "light": LIGHT}


def get(name: str) -> Palette:
    return PALETTES.get(name, DARK)


def mix(a: str, b: str, t: float) -> str:
    """Blend two ``#rrggbb`` colours; ``t=0`` gives ``a``, ``t=1`` gives ``b``."""
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg_, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (
        round(ar + (br - ar) * t),
        round(ag + (bg_ - ag) * t),
        round(ab + (bb - ab) * t),
    )


def init_scaling(root: tk.Tk) -> float:
    """Match Tk's point sizing and our pixel sizing to the system DPI."""
    dpi = 96
    try:
        dpi = int(w.user32.GetDpiForSystem()) or 96
    except Exception:
        pass
    root.tk.call("tk", "scaling", dpi / 72.0)
    set_scale(dpi / 96.0)
    return dpi / 96.0


def fonts() -> dict[str, tkfont.Font]:
    """Named fonts used across the UI. Point sizes; Tk scales them by DPI."""
    return {
        "base": tkfont.Font(family=FONT_FAMILY, size=9),
        "bold": tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
        "small": tkfont.Font(family=FONT_FAMILY, size=8),
        "card": tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
        "title": tkfont.Font(family=FONT_FAMILY, size=15, weight="bold"),
        "button": tkfont.Font(family=FONT_FAMILY, size=10, weight="bold"),
        "mono": tkfont.Font(family="Consolas", size=9),
    }


def apply_ttk(root: tk.Misc, p: Palette, f: dict[str, tkfont.Font]) -> None:
    """Reskin the stock ttk widgets we still rely on."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=p.surface, foreground=p.text, font=f["base"],
                    borderwidth=0, focuscolor=p.accent)
    style.configure("TFrame", background=p.surface)
    style.configure("Bg.TFrame", background=p.bg)
    style.configure("TLabel", background=p.surface, foreground=p.text)
    style.configure("Muted.TLabel", background=p.surface, foreground=p.muted, font=f["small"])

    for widget in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            widget,
            fieldbackground=p.raised, background=p.raised, foreground=p.text,
            bordercolor=p.border, lightcolor=p.raised, darkcolor=p.raised,
            insertcolor=p.text, arrowcolor=p.muted, arrowsize=px(12),
            padding=(px(6), px(4)), relief="flat", borderwidth=0,
        )
        style.map(
            widget,
            fieldbackground=[("disabled", p.surface), ("focus", p.raised)],
            foreground=[("disabled", p.muted)],
            bordercolor=[("focus", p.accent)],
            arrowcolor=[("disabled", p.border)],
        )
    style.map("TCombobox", selectbackground=[("!focus", p.raised)],
              selectforeground=[("!focus", p.text)])
    root.option_add("*TCombobox*Listbox.background", p.raised)
    root.option_add("*TCombobox*Listbox.foreground", p.text)
    root.option_add("*TCombobox*Listbox.selectBackground", p.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", p.accent_text)

    style.configure("TCheckbutton", background=p.surface, foreground=p.text,
                    indicatorcolor=p.raised, indicatorbackground=p.raised)
    style.map("TCheckbutton",
              indicatorcolor=[("selected", p.accent)],
              background=[("active", p.surface)])

    style.configure("TButton", background=p.raised, foreground=p.text,
                    bordercolor=p.border, relief="flat", padding=(px(10), px(5)))
    style.map("TButton", background=[("active", p.hover), ("disabled", p.surface)],
              foreground=[("disabled", p.muted)])

    style.configure("Treeview", background=p.raised, fieldbackground=p.raised,
                    foreground=p.text, bordercolor=p.border, rowheight=px(22))
    style.configure("Treeview.Heading", background=p.surface, foreground=p.muted,
                    font=f["small"], relief="flat", padding=(px(6), px(4)))
    style.map("Treeview.Heading", background=[("active", p.hover)])
    style.map("Treeview", background=[("selected", p.accent)],
              foreground=[("selected", p.accent_text)])

    # clam draws scrollbar bevels from light/dark/border colours too, so all of
    # them have to be overridden or the widget stays default grey.
    for name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(name, background=p.raised, troughcolor=p.surface,
                        bordercolor=p.surface, lightcolor=p.raised, darkcolor=p.raised,
                        arrowcolor=p.muted, relief="flat", borderwidth=0, width=px(11))
        style.map(name,
                  background=[("pressed", p.accent), ("active", p.hover)],
                  arrowcolor=[("active", p.text)])

    style.configure("TLabelframe", background=p.surface, bordercolor=p.border)
    style.configure("TLabelframe.Label", background=p.surface, foreground=p.muted,
                    font=f["small"])
