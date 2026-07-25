"""Virtual-key code tables and hotkey helpers."""

from __future__ import annotations

from dataclasses import dataclass

from . import winapi as w

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04
VK_XBUTTON1 = 0x05
VK_XBUTTON2 = 0x06

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C

# Modifier keys, kept out of the "plain key" part of a hotkey.
MODIFIER_VKS = {
    0xA0,  # LSHIFT
    0xA1,  # RSHIFT
    0xA2,  # LCONTROL
    0xA3,  # RCONTROL
    0xA4,  # LMENU
    0xA5,  # RMENU
    VK_SHIFT,
    VK_CONTROL,
    VK_MENU,
    VK_LWIN,
    VK_RWIN,
}

"""Mouse buttons usable as hotkeys, keyed by their virtual-key code."""
MOUSE_VKS: dict[int, str] = {
    VK_LBUTTON: "Mouse Left",
    VK_RBUTTON: "Mouse Right",
    VK_MBUTTON: "Mouse Middle",
    VK_XBUTTON1: "Mouse X1",
    VK_XBUTTON2: "Mouse X2",
}

# Button name (as used by `inputs`) -> virtual-key code.
BUTTON_TO_VK = {
    "left": VK_LBUTTON,
    "right": VK_RBUTTON,
    "middle": VK_MBUTTON,
    "x1": VK_XBUTTON1,
    "x2": VK_XBUTTON2,
}

# Swallowing the left or right button would leave the desktop unusable while the
# app runs, so those two are never suppressed no matter what the user picks.
NEVER_SUPPRESS = {VK_LBUTTON, VK_RBUTTON}


def is_mouse_vk(vk: int) -> bool:
    return vk in MOUSE_VKS


_NAMED_VKS: dict[int, str] = {
    **MOUSE_VKS,
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x13: "Pause",
    0x14: "CapsLock",
    0x1B: "Esc",
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2C: "PrintScreen",
    0x2D: "Insert",
    0x2E: "Delete",
    0x5D: "Menu",
    0x90: "NumLock",
    0x91: "ScrollLock",
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}

for _i in range(24):
    _NAMED_VKS[0x70 + _i] = f"F{_i + 1}"
for _i in range(10):
    _NAMED_VKS[0x60 + _i] = f"Num{_i}"
_NAMED_VKS.update(
    {
        0x6A: "Num*",
        0x6B: "Num+",
        0x6D: "Num-",
        0x6E: "Num.",
        0x6F: "Num/",
    }
)


def vk_name(vk: int) -> str:
    """Human-readable label for a virtual-key code."""
    if vk in _NAMED_VKS:
        return _NAMED_VKS[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if vk in (0xA0, 0xA1, VK_SHIFT):
        return "Shift"
    if vk in (0xA2, 0xA3, VK_CONTROL):
        return "Ctrl"
    if vk in (0xA4, 0xA5, VK_MENU):
        return "Alt"
    if vk in (VK_LWIN, VK_RWIN):
        return "Win"
    return f"VK{vk:02X}"


NAME_TO_VK: dict[str, int] = {vk_name(vk).lower(): vk for vk in _NAMED_VKS}
NAME_TO_VK.update({chr(c).lower(): c for c in range(0x30, 0x3A)})
NAME_TO_VK.update({chr(c).lower(): c for c in range(0x41, 0x5B)})
NAME_TO_VK.update({"ctrl": VK_CONTROL, "shift": VK_SHIFT, "alt": VK_MENU, "win": VK_LWIN})


@dataclass(frozen=True)
class Hotkey:
    """A global hotkey: one main key plus optional modifiers."""

    vk: int
    ctrl: bool = False
    shift: bool = False
    alt: bool = False

    def label(self) -> str:
        parts = []
        if self.ctrl:
            parts.append("Ctrl")
        if self.shift:
            parts.append("Shift")
        if self.alt:
            parts.append("Alt")
        parts.append(vk_name(self.vk))
        return "+".join(parts)

    def to_dict(self) -> dict:
        return {"vk": self.vk, "ctrl": self.ctrl, "shift": self.shift, "alt": self.alt}

    @classmethod
    def from_dict(cls, data: dict | None, default: "Hotkey") -> "Hotkey":
        if not isinstance(data, dict) or "vk" not in data:
            return default
        try:
            return cls(
                vk=int(data["vk"]),
                ctrl=bool(data.get("ctrl", False)),
                shift=bool(data.get("shift", False)),
                alt=bool(data.get("alt", False)),
            )
        except (TypeError, ValueError):
            return default

    @classmethod
    def parse(cls, text: str) -> "Hotkey | None":
        """Parse a label such as ``Ctrl+Shift+F6`` back into a Hotkey."""
        ctrl = shift = alt = False
        vk = None
        # Strip each part rather than all whitespace: names like "Mouse X1" have
        # a space inside them.
        for chunk in text.split("+"):
            low = chunk.strip().lower()
            if low == "ctrl":
                ctrl = True
            elif low == "shift":
                shift = True
            elif low == "alt":
                alt = True
            elif low in NAME_TO_VK:
                vk = NAME_TO_VK[low]
            else:
                return None
        return None if vk is None else cls(vk, ctrl, shift, alt)


def modifiers_down() -> tuple[bool, bool, bool]:
    """Live (ctrl, shift, alt) state, read straight from the OS."""
    down = lambda vk: bool(w.user32.GetAsyncKeyState(vk) & 0x8000)  # noqa: E731
    return down(VK_CONTROL), down(VK_SHIFT), down(VK_MENU)


def matches(hotkey: Hotkey, vk: int) -> bool:
    """True when ``vk`` was just pressed and the modifier state matches."""
    if vk != hotkey.vk:
        return False
    ctrl, shift, alt = modifiers_down()
    return ctrl == hotkey.ctrl and shift == hotkey.shift and alt == hotkey.alt
