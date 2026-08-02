"""Focused, non-injecting checks for the persistence and validation hardening."""

from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autoclicker import config, diagnostics, recorder
from autoclicker.engine import ClickEngine
from autoclicker.keys import Hotkey


@contextmanager
def raises(expected: type[BaseException], text: str = ""):
    try:
        yield
    except expected as exc:
        if text:
            assert text.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError(f"Expected {expected.__name__}")


def test_settings_legacy_current_round_trip_and_panic_hotkey(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    settings = config.Settings(
        advanced_mode=True,
        onboarding_complete=True,
        panic_hotkey=Hotkey(0x13, ctrl=True),
    )
    config.save(settings, target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["version"] == config.SETTINGS_SCHEMA_VERSION
    assert config.load(target) == settings
    # Existing flat files remain readable.
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(settings.to_dict()), encoding="utf-8")
    assert config.load(legacy) == settings


def test_settings_corrupt_primary_recovers_valid_backup(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    first = config.Settings(millis=123)
    second = config.Settings(millis=456)
    config.save(first, target)
    config.save(second, target)
    backup = Path(str(target) + ".bak")
    assert config.load(backup) == first
    # A corrupt primary must not replace the good backup when saving again.
    target.write_text("{not json", encoding="utf-8")
    config.save(second, target)
    assert config.load(backup) == first
    target.write_text("{not json", encoding="utf-8")
    assert config.load(target) == first
    assert config.consume_load_warning()
    assert config.consume_load_warning() is None


def test_engine_records_worker_error_and_logging(tmp_path: Path) -> None:
    # Stub only the non-injecting click path; force a worker failure.
    import autoclicker.engine as engine_module

    def fail_click(*args, **kwargs):
        raise RuntimeError("boom")

    callback: list[str] = []
    with patch.object(engine_module.inputs, "begin_high_resolution_timers", lambda: None), patch.object(
        engine_module.inputs, "end_high_resolution_timers", lambda: None
    ), patch.object(engine_module.inputs, "click", fail_click), patch.object(
        engine_module.inputs, "precise_sleep", lambda *args, **kwargs: True
    ):
        engine = ClickEngine(callback.append)
        assert engine.start(config.Settings(millis=1, repeat_mode="count", repeat_count=1)) == []
        assert engine._thread is not None
        engine._thread.join(timeout=2)
        assert callback == ["error"]
        assert engine.last_error and "boom" in engine.last_error


def test_macro_validation_rejects_malformed_and_oversized(tmp_path: Path) -> None:
    path = tmp_path / "macro.json"
    path.write_text(json.dumps({"version": 1, "events": [{"kind": "bogus", "t": 0}]}), encoding="utf-8")
    with raises(ValueError, "unknown kind"):
        recorder.Macro.load(path)
    path.write_text(json.dumps({"version": 1, "events": [{"kind": "key", "t": 0, "vk": "A", "pressed": True}]}), encoding="utf-8")
    with raises(ValueError, "vk"):
        recorder.Macro.load(path)
    path.write_text(json.dumps({"version": recorder.MACRO_SCHEMA_VERSION, "events": [None]}), encoding="utf-8")
    with raises(ValueError, "event 0"):
        recorder.Macro.load(path)
    path.write_bytes(b"x" * (recorder.MAX_MACRO_FILE_BYTES + 1))
    with raises(ValueError, "too large"):
        recorder.Macro.load(path)


def test_log_path_is_discoverable() -> None:
    assert diagnostics.log_path().name == diagnostics.LOG_FILENAME


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as root:
        base = Path(root)
        test_settings_legacy_current_round_trip_and_panic_hotkey(base)
        test_settings_corrupt_primary_recovers_valid_backup(base)
        test_engine_records_worker_error_and_logging(base)
        test_macro_validation_rejects_malformed_and_oversized(base)
    test_log_path_is_discoverable()
    print("HARDENING TESTS PASSED")
