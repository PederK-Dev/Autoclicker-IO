"""Settings model, JSON persistence and named profiles."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import diagnostics
from .keys import Hotkey

APP_NAME = "AutoclickerIO"

DEFAULT_START_HOTKEY = Hotkey(vk=0x74)  # F5
DEFAULT_STOP_HOTKEY = Hotkey(vk=0x74)  # F5 toggles by default, like the reference app
DEFAULT_RECORD_HOTKEY = Hotkey(vk=0x76)  # F7
DEFAULT_PLAY_HOTKEY = Hotkey(vk=0x77)  # F8
DEFAULT_PANIC_HOTKEY = Hotkey(vk=0x13)  # Pause/Break

# Version zero is the original flat object (there was no explicit version).
# New files use a small envelope so future migrations can be handled without
# guessing which fields belonged to which release.
SETTINGS_SCHEMA_VERSION = 1
CURRENT_SCHEMA_VERSION = SETTINGS_SCHEMA_VERSION
SETTINGS_VERSION = SETTINGS_SCHEMA_VERSION
CONFIG_SCHEMA_VERSION = SETTINGS_SCHEMA_VERSION

_warning_lock = threading.Lock()
_load_warning: str | None = None


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
    panic_hotkey: Hotkey = DEFAULT_PANIC_HOTKEY

    # Hotkeys bound to a mouse button normally still reach the app underneath.
    # Turning this on swallows them (never Left/Right — see keys.NEVER_SUPPRESS).
    suppress_hotkeys: bool = True

    # Onboarding / advanced controls ----------------------------------
    # These fields were added after the initial flat schema and deliberately
    # default to the old application's behaviour.
    advanced_mode: bool = False
    onboarding_complete: bool = False

    # Window -----------------------------------------------------------
    theme: str = "dark"
    always_on_top: bool = False
    minimize_on_start: bool = False

    _HOTKEY_FIELDS = (
        "start_hotkey",
        "stop_hotkey",
        "record_hotkey",
        "play_hotkey",
        "panic_hotkey",
    )

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
        if not isinstance(data, dict):
            return defaults
        for key, value in data.items():
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


def _set_load_warning(message: str | None) -> None:
    global _load_warning
    with _warning_lock:
        _load_warning = message


def peek_load_warning() -> str | None:
    """Return the latest load warning without consuming it."""

    with _warning_lock:
        return _load_warning


def consume_load_warning() -> str | None:
    """Return and clear the latest load warning (a one-shot UI helper)."""

    global _load_warning
    with _warning_lock:
        warning = _load_warning
        _load_warning = None
        return warning


# Compatibility aliases for UI callers that use getter/take wording.
get_load_warning = consume_load_warning
take_load_warning = consume_load_warning
load_warning = consume_load_warning


def _decode_payload(payload: object) -> Settings:
    """Decode either the current envelope or the original flat JSON object."""

    if not isinstance(payload, dict):
        raise ValueError("Settings payload must be a JSON object.")

    # Legacy files had no marker and contained fields directly at the root.
    if "version" not in payload and "schema_version" not in payload and "settings" not in payload:
        return Settings.from_dict(payload)

    version = payload.get("version", payload.get("schema_version"))
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("Settings version must be an integer.")
    if version not in (0, SETTINGS_SCHEMA_VERSION):
        raise ValueError(f"Unsupported settings version: {version}.")
    values = payload.get("settings")
    if values is None:
        # Also accept a version marker added directly to the old flat object;
        # this costs nothing and makes hand-edited/early migration files safe.
        values = {key: value for key, value in payload.items() if key not in ("version", "schema_version")}
    if not isinstance(values, dict):
        raise ValueError("Settings envelope is missing its object-valued 'settings'.")
    return Settings.from_dict(values)


def _load_json(target: Path) -> Settings:
    with open(target, "r", encoding="utf-8") as handle:
        return _decode_payload(json.load(handle))


def _backup_candidates(target: Path) -> tuple[Path, ...]:
    # ``config.json.bak`` is the canonical name.  Also accept ``config.bak``
    # used by a few early development builds and convenient for callers using
    # ``Path.with_suffix('.bak')``.
    canonical = Path(str(target) + ".bak")
    alternate = target.with_suffix(".bak") if target.suffix else Path(str(target) + ".bak")
    return (canonical,) if alternate == canonical else (canonical, alternate)


def backup_path(path: Path | None = None) -> Path:
    """Return the canonical on-disk backup path for a settings file."""

    target = Path(path) if path is not None else config_path()
    return _backup_candidates(target)[0]


def _valid_persisted_file(target: Path) -> bool:
    try:
        _load_json(target)
        return True
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        diagnostics.log_warning("Ignoring invalid settings file", path=str(target), error=str(exc))
        return False


def load(path: Path | None = None) -> Settings:
    """Load settings, recovering from a valid ``.bak`` when necessary.

    The warning is retained for one UI read via :func:`consume_load_warning`;
    missing files on first launch intentionally do not produce a warning.
    """

    _set_load_warning(None)
    try:
        target = Path(path) if path is not None else config_path()
    except (OSError, TypeError, ValueError) as exc:
        message = f"Unable to locate settings: {exc}"
        diagnostics.log_exception(message, exc)
        _set_load_warning(message)
        return Settings()

    try:
        return _load_json(target)
    except FileNotFoundError as exc:
        primary_error = exc
        diagnostics.log_warning("Settings file not found", path=str(target))
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        primary_error = exc
        diagnostics.log_exception("Unable to load settings", exc, path=str(target))

    for backup in _backup_candidates(target):
        if not backup.exists():
            continue
        try:
            settings = _load_json(backup)
            message = f"Recovered settings from backup: {backup.name}."
            diagnostics.log_warning(message, primary=str(target), backup=str(backup))
            _set_load_warning(message)
            return settings
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            diagnostics.log_exception("Unable to load settings backup", exc, path=str(backup))

    # A missing file is normal on first run; malformed/unsupported data should
    # still be visible to the UI and log for troubleshooting.
    if not isinstance(primary_error, FileNotFoundError):
        message = f"Settings could not be loaded; defaults were used ({target.name})."
        _set_load_warning(message)
    return Settings()


def save(settings: Settings, path: Path | None = None) -> None:
    target = Path(path) if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    # Preserve a known-good previous primary.  Crucially, parse/validate it
    # before copying so a corrupt primary can never overwrite a good backup.
    if target.exists() and _valid_persisted_file(target):
        for backup in _backup_candidates(target):
            try:
                shutil.copy2(target, backup)
            except OSError as exc:
                diagnostics.log_exception("Unable to create settings backup", exc, path=str(backup))

    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = {"version": SETTINGS_SCHEMA_VERSION, "settings": settings.to_dict()}
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except Exception as exc:
        diagnostics.log_exception("Unable to save settings", exc, path=str(target))
        try:
            tmp.unlink()
        except OSError as cleanup_exc:
            diagnostics.log_warning("Unable to remove temporary settings file", path=str(tmp), error=str(cleanup_exc))
        raise


def list_profiles() -> list[str]:
    return sorted(p.stem for p in profiles_dir().glob("*.json"))


def profile_path(name: str) -> Path:
    return profiles_dir() / f"{safe_profile_name(name)}.json"
