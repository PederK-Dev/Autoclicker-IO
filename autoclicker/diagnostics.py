"""Small, best-effort diagnostics helpers used by the core worker threads.

The application is primarily a desktop GUI, so diagnostics must never become a
second failure mode.  The logger is configured lazily on first use and falls
back to :class:`logging.NullHandler` if the per-user log directory cannot be
created (for example, when ``APPDATA`` is read-only).  Callers can therefore
log from hook/worker exception paths without having to wrap the logger itself.
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

APP_NAME = "AutoclickerIO"
LOG_FILENAME = "autoclicker.log"
LOG_MAX_BYTES = 1 * 1024 * 1024
LOG_BACKUP_COUNT = 3

_LOGGER_NAME = "autoclicker"
_lock = threading.Lock()
_configured = False
_configured_path: Path | None = None


def log_dir() -> Path:
    """Return the user log directory without creating it.

    The path is intentionally computed independently from ``config_dir`` so a
    logging failure cannot recurse into settings persistence.  ``APPDATA`` is
    preferred on Windows; the user home directory is the portable fallback.
    """

    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / APP_NAME / "logs"


def log_path() -> Path:
    """Return the path used for the rotating diagnostics file.

    This helper is safe to call before logging has been initialized and is
    intended for UI integrations (for example, an ``Open logs`` action).
    """

    return log_dir() / LOG_FILENAME


# Descriptive alias for callers that prefer an explicit getter.
get_log_path = log_path
get_log_file_path = log_path
logs_dir = log_dir


def get_logger() -> logging.Logger:
    """Return the application logger, configuring it at most once.

    Any error while creating the directory/handler is swallowed *here* and
    replaced with a ``NullHandler``.  The rest of the application can safely
    call ``logger.exception`` from exception handlers without risking another
    exception on a hook thread.
    """

    global _configured, _configured_path
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if _configured:
        return logger
    with _lock:
        if _configured:
            return logger
        path = log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler: logging.Handler = RotatingFileHandler(
                path,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"
                )
            )
            logger.addHandler(handler)
            _configured_path = path
        except Exception:
            # Logging must not crash the input hook or playback worker.  Avoid
            # logging this failure through the same logger (which would recurse).
            logger.addHandler(logging.NullHandler())
            _configured_path = None
        _configured = True
    return logger


def logger() -> logging.Logger:
    """Short alias for :func:`get_logger`."""

    return get_logger()


setup_logging = get_logger


def log_exception(message: str, exc: BaseException | None = None, **context: Any) -> None:
    """Record an exception without ever propagating logging failures."""

    try:
        log = get_logger()
        details = " ".join(f"{key}={value!r}" for key, value in context.items())
        if details:
            message = f"{message} ({details})"
        if exc is None:
            log.exception(message)
        else:
            log.error(message, exc_info=(type(exc), exc, exc.__traceback__))
    except Exception:
        # ``NullHandler`` and stdlib logging are normally safe, but diagnostics
        # are deliberately best effort even when a custom handler misbehaves.
        return


def log_warning(message: str, **context: Any) -> None:
    """Record a warning while keeping failure paths non-throwing."""

    try:
        details = " ".join(f"{key}={value!r}" for key, value in context.items())
        get_logger().warning(f"{message}{(' ' + details) if details else ''}")
    except Exception:
        return


def configured_log_path() -> Path | None:
    """Return the actual configured file path, if file logging succeeded."""

    # Calling ``get_logger`` is intentional: this remains lazy until the UI or
    # a diagnostic event actually asks for the status.
    get_logger()
    return _configured_path


__all__ = [
    "APP_NAME",
    "LOG_FILENAME",
    "LOG_MAX_BYTES",
    "LOG_BACKUP_COUNT",
    "log_dir",
    "log_path",
    "get_log_path",
    "get_log_file_path",
    "logs_dir",
    "get_logger",
    "logger",
    "setup_logging",
    "log_exception",
    "log_warning",
    "configured_log_path",
]
