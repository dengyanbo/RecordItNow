"""Logging setup. Wraps loguru with a sensible default sink for RIN.

Console output is colorized and INFO-level by default; a rotated file
sink under ``%LOCALAPPDATA%\\RIN\\logs\\rin.log`` captures DEBUG with
14-day retention.
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from .. import paths

_CONFIGURED = False


def setup_logging(level: str = "INFO", *, log_file: Path | None = None) -> None:
    """Initialize loguru sinks. Idempotent.

    Skips the stderr sink when ``sys.stderr is None`` — this happens in
    PyInstaller's windowed-mode bundle (``console=False``) because the
    runw bootloader detaches stdio. Without this guard ``logger.add``
    raises ``TypeError: Cannot log to objects of type 'NoneType'`` and
    crashes the .exe before the first log line.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    logger.remove()
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=level,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level:<8}</level> | "
                "<cyan>{name}</cyan> - <level>{message}</level>"
            ),
        )
    file_path = log_file or (paths.logs_dir() / "rin.log")
    logger.add(
        file_path,
        level="DEBUG",
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level:<8} | "
            "{name}:{function}:{line} - {message}"
        ),
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )
    _CONFIGURED = True


def get_logger(name: str):
    """Return a loguru logger bound with a component name."""

    return logger.bind(component=name)
