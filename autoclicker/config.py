"""Settings model, JSON persistence and named profiles."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .keys import Hotkey

APP_NAME = "AutoclickerIO"

DEFAULT_START_HOTKEY = Hotkey(vk=0x74)  # F5
DEFAULT_STOP_HOTKEY = Hotkey(vk=0x74)  # F5 toggles by default, like the reference app
DEFAULT_RECORD_HOTKEY = Hotkey(vk=0x76)  # F7
DEFAULT_PLAY_HOTKEY = Hotkey(vk=0x77)  # F8


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def profiles_dir() -> Path:
    path = config_dir() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_profile_name(name: str) -> str:
    cleaned = re.sub(r"[^\w \-().]", "_", name).strip() or "profile"
    return cleaned[:64]


@dataclass
class Settings:
    """Everything the click engine and the UI need to remember."""

    # Interval ---------------------------------------------------------
    interval_mode: str = "fixed"  # "fixed" | "random"
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    millis: int = 100
    random_min: float = 0.05
    random_max: float = 0.25

    # Click options ----------------------------------------------------
    button: str = "left"  # left | middle | right | x1 | x2
    click_type: str = "single"  # single | double | triple
    hold_ms: int = 0
    hold_jitter_ms: int = 0

    # Repeat -----------------------------------------------------------
    repeat_mode: str = "infinite"  # "infinite" | "count" | "duration"
    repeat_count: int = 100
    duration_seconds: float = 60.0
    start_delay: float = 0.0

    # Position ---------------------------------------------------------
    position_mode: str = "current"  # current | fixed | sequence
    pos_x: int = 0
    pos_y: int = 0
    position_jitter: int = 0
    restore_cursor: bool = True
    sequence: list[list[int]] = field(default_factory=list)

    # Playback ---------------------------------------------------------
    playback_speed: float = 1.0
    playback_repeat: int = 1
    playback_loop: bool = False

    # Hotkeys ----------------------------------------------------------
    start_hotkey: Hotkey = DEFAULT_START_HOTKEY
    stop_hotkey: Hotkey = DEFAULT_STOP_HOTKEY
    record_hotkey: Hotkey = DEFAULT_RECORD_HOTKEY
    play_hotkey: Hotkey = DEFAULT_PLAY_HOTKEY

    # Hotkeys bound to a mouse button normally still reach the app underneath.
    # Turning this on swallows them (never Left/Right — see keys.NEVER_SUPPRESS).
    suppress_hotkeys: bool = True

    # Window -----------------------------------------------------------
    theme: str = "dark"
    always_on_top: bool = False
    minimize_on_start: bool = False

    _HOTKEY_FIELDS = ("start_hotkey", "stop_hotkey", "record_hotkey", "play_hotkey")

    # -- interval helpers ---------------------------------------------

    def fixed_interval(self) -> float:
        """Configured fixed interval in seconds."""
        return (
            self.hours * 3600
            + self.minutes * 60
            + self.seconds
            + self.millis / 1000.0
        )

    def validate(self) -> list[str]:
        """Return human-readable problems; empty list means good to go."""
        problems: list[str] = []
        if self.interval_mode == "fixed":
            if self.fixed_interval() <= 0:
                problems.append("The click interval must be greater than zero.")
        else:
            if self.random_min <= 0 or self.random_max <= 0:
                problems.append("Random interval bounds must be greater than zero.")
            elif self.random_max < self.random_min:
                problems.append("The random interval maximum must not be below the minimum.")
        if self.repeat_mode == "count" and self.repeat_count <= 0:
            problems.append("Repeat count must be at least 1.")
        if self.repeat_mode == "duration" and self.duration_seconds <= 0:
            problems.append("Run duration must be greater than zero.")
        if self.position_mode == "sequence" and not self.sequence:
            problems.append("No click points captured for sequence mode.")
        return problems

    # -- serialisation -------------------------------------------------

    def to_dict(self) -> dict:
        data = asdict(self)
        for name in self._HOTKEY_FIELDS:
            data[name] = getattr(self, name).to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        kwargs = {}
        defaults = cls()
        for key, value in (data or {}).items():
            if key not in known:
                continue
            if key in cls._HOTKEY_FIELDS:
                kwargs[key] = Hotkey.from_dict(value, getattr(defaults, key))
            else:
                kwargs[key] = value
        settings = cls(**kwargs)
        settings.sequence = [
            [int(p[0]), int(p[1])]
            for p in (settings.sequence or [])
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
        return settings


def load(path: Path | None = None) -> Settings:
    target = path or config_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return Settings.from_dict(json.load(handle))
    except (OSError, ValueError, TypeError):
        return Settings()


def save(settings: Settings, path: Path | None = None) -> None:
    target = path or config_path()
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(settings.to_dict(), handle, indent=2)
    os.replace(tmp, target)


def list_profiles() -> list[str]:
    return sorted(p.stem for p in profiles_dir().glob("*.json"))


def profile_path(name: str) -> Path:
    return profiles_dir() / f"{safe_profile_name(name)}.json"
