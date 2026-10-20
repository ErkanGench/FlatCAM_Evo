"""Shared helpers and errors for the updater transports and checkers."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


class TransportError(RuntimeError):
    """Raised for deterministic update transport failures."""


class DownloadCancelled(TransportError):
    """Raised when a caller cancels a download."""


_log = logging.getLogger(__name__)


def app_log(app, level: str, message: str) -> None:
    """Log through the application logger, falling back to the module logger."""
    logger = getattr(app, "log", None)
    method = getattr(logger, level, None)
    if callable(method):
        try:
            method(message)
            return
        except Exception:
            pass
    method = getattr(_log, level, None)
    if callable(method):
        method(message)


def inform(app, message: str, level: str = "warning") -> None:
    """Log a message and surface it through the application inform signal."""
    app_log(app, level, message)
    signal = getattr(app, "inform", None)
    emit = getattr(signal, "emit", None)
    if callable(emit):
        try:
            emit(f"[{level.upper()}] {message}")
        except Exception:
            pass


def emit(app, signal_name: str, payload: dict) -> None:
    """Emit a payload on an application signal when it exists."""
    signal = getattr(app, signal_name, None)
    emit = getattr(signal, "emit", None)
    if callable(emit):
        try:
            emit(payload)
        except Exception:
            app_log(app, "debug", f"UpdateChecker: {signal_name}.emit() failed.")


def local_build(app) -> str:
    """Return the local build identity, or an empty string when unavailable."""
    for name in ("build_string", "build", "version_date"):
        try:
            value = getattr(app, name, None)
        except RuntimeError:
            value = None
        if value:
            return str(value)
    return ""


def install_root(app) -> Path:
    """Return the application installation root."""
    configured = getattr(app, "install_root", None)
    if configured:
        return Path(configured)
    try:
        from .launcher import _install_root as launcher_install_root

        return Path(launcher_install_root())
    except Exception:
        return Path(sys.executable).resolve().parent
