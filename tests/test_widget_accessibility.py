"""Keyboard/focus checks for the hand-drawn Tk controls.

The tests use Tk's local event queue only; they never call the input backend or
inject OS-level mouse/keyboard events.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclicker import theme
from autoclicker.widgets import PillButton, SegmentedControl, Switch


def _root() -> tuple[tk.Tk, dict[str, tkfont.Font]]:
    root = tk.Tk()
    root.geometry("480x240")
    fonts = theme.fonts()
    root.update_idletasks()
    return root, fonts


def _key(widget: tk.Widget, sequence: str) -> None:
    widget.event_generate(sequence)
    widget.update_idletasks()


def _contrast_with_white(colour: str) -> float:
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return 1.05 / (luminance + 0.05)


def test_action_colours_have_white_text_contrast() -> None:
    for palette in (theme.DARK, theme.LIGHT):
        for colour in (palette.accent, palette.success, palette.danger):
            assert _contrast_with_white(colour) >= 4.5, (palette.name, colour)


def test_pill_button_focus_keyboard_and_disabled_state() -> None:
    root, fonts = _root()
    try:
        fired: list[str] = []
        button = PillButton(root, "Run", theme.DARK, fonts["base"],
                            command=lambda: fired.append("run"), kind="accent")
        button.pack(padx=12, pady=12)
        root.update()
        button.focus_force()
        root.update()
        assert root.focus_get() is button and button._focused

        _key(button, "<KeyPress-space>")
        _key(button, "<KeyPress-space>")  # key repeat must not double-fire
        _key(button, "<KeyRelease-space>")
        assert fired == ["run"]
        _key(button, "<KeyPress-Return>")
        _key(button, "<KeyRelease-Return>")
        assert fired == ["run", "run"]

        button.set_state("disabled")
        assert str(button.cget("takefocus")) == "0"
        _key(button, "<KeyPress-space>")
        _key(button, "<KeyRelease-space>")
        assert fired == ["run", "run"]
    finally:
        root.destroy()


def test_segmented_control_navigation_selection_and_disabled_state() -> None:
    root, fonts = _root()
    try:
        variable = tk.StringVar(root, value="two")
        changed: list[str] = []
        segmented = SegmentedControl(
            root, [("One", "one"), ("Two", "two"), ("Three", "three")],
            variable, theme.LIGHT, fonts["base"], on_change=lambda: changed.append(variable.get()),
        )
        segmented.pack(padx=12, pady=12)
        root.update()
        segmented.focus_force()
        root.update()
        assert root.focus_get() is segmented and segmented._focused

        _key(segmented, "<KeyPress-Right>")
        assert variable.get() == "three"
        _key(segmented, "<KeyPress-Home>")
        assert variable.get() == "one"
        _key(segmented, "<KeyPress-End>")
        assert variable.get() == "three"
        before = len(changed)
        _key(segmented, "<KeyPress-space>")
        _key(segmented, "<KeyPress-space>")
        _key(segmented, "<KeyRelease-space>")
        assert len(changed) == before + 1

        segmented.set_enabled(False)
        assert str(segmented.cget("takefocus")) == "0"
        current = variable.get()
        before = len(changed)
        _key(segmented, "<KeyPress-Left>")
        _key(segmented, "<KeyPress-space>")
        _key(segmented, "<KeyRelease-space>")
        assert variable.get() == current and len(changed) == before
    finally:
        root.destroy()


def test_switch_focus_keyboard_and_disabled_state() -> None:
    root, fonts = _root()
    try:
        variable = tk.BooleanVar(root, value=False)
        changed: list[bool] = []
        switch = Switch(root, "Remember", variable, theme.DARK, fonts["base"],
                        command=lambda: changed.append(variable.get()))
        switch.pack(padx=12, pady=12)
        root.update()
        switch.focus_force()
        root.update()
        assert root.focus_get() is switch and switch._focused

        _key(switch, "<KeyPress-space>")
        _key(switch, "<KeyPress-space>")
        _key(switch, "<KeyRelease-space>")
        assert variable.get() is True and changed == [True]
        _key(switch, "<KeyPress-Return>")
        _key(switch, "<KeyRelease-Return>")
        assert variable.get() is False and changed == [True, False]

        switch.set_enabled(False)
        assert str(switch.cget("takefocus")) == "0"
        _key(switch, "<KeyPress-space>")
        _key(switch, "<KeyRelease-space>")
        assert variable.get() is False and changed == [True, False]
    finally:
        root.destroy()


if __name__ == "__main__":
    test_action_colours_have_white_text_contrast()
    test_pill_button_focus_keyboard_and_disabled_state()
    test_segmented_control_navigation_selection_and_disabled_state()
    test_switch_focus_keyboard_and_disabled_state()
    print("WIDGET ACCESSIBILITY TESTS PASSED")
