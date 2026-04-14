"""Logging configuration module for the Zoe orchestrator.

Provides :func:`configure_logging` to set up console and file handlers
with optional log file rotation (by size and time).

Usage::

    from orchestrator.bin.logger_config import configure_logging

    configure_logging(level="DEBUG", log_file="/var/log/zoe/app.log")

    # With size-based rotation (10 MB, keep 5 backups)
    configure_logging(
        log_file="/var/log/zoe/app.log",
        max_bytes=10_000_000,
        backup_count=5,
    )

    # With time-based rotation (daily, keep 30 days)
    configure_logging(
        log_file="/var/log/zoe/app.log",
        when="midnight",
        interval=1,
        backup_count=30,
    )
"""

import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Optional


_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def configure_logging(
    level: Optional[str] = None,
    fmt: Optional[str] = None,
    datefmt: Optional[str] = None,
    log_file: Optional[str] = None,
    max_bytes: int = 0,
    backup_count: int = 0,
    when: Optional[str] = None,
    interval: int = 1,
    console: bool = True,
) -> None:
    """Configure the root logger with console and/or file handlers.

    Parameters
    ----------
    level:
        Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        Defaults to INFO.
    fmt:
        Custom format string for log messages.
    datefmt:
        Custom date format string. Defaults to ISO-8601.
    log_file:
        Path to a log file. If provided, a file handler is added.
    max_bytes:
        Maximum log file size in bytes before rotation. Only used when
        ``log_file`` is set and ``when`` is not provided. Set to 0 to
        disable size-based rotation.
    backup_count:
        Number of rotated log files to keep.
    when:
        Time-based rotation interval unit (e.g. ``"midnight"``, ``"H"``,
        ``"D"``). When set, :class:`TimedRotatingFileHandler` is used
        instead of :class:`RotatingFileHandler`.
    interval:
        Multiplier for *when* (e.g. ``when="H", interval=6`` rotates
        every 6 hours).
    console:
        If ``True`` (default), add a :class:`logging.StreamHandler`
        writing to stderr.

    Raises
    ------
    ValueError
        If *level* is not a recognised log level.
    """
    resolved_level = (level or "INFO").upper()
    if resolved_level not in _VALID_LEVELS:
        raise ValueError(
            f"Invalid log level: {level!r}. Must be one of {sorted(_VALID_LEVELS)}"
        )

    log_level = getattr(logging, resolved_level)
    formatter = logging.Formatter(
        fmt=fmt or _DEFAULT_FORMAT,
        datefmt=datefmt or _DEFAULT_DATE_FORMAT,
    )

    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove existing handlers to allow re-configuration.
    root.handlers.clear()

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if log_file is not None:
        file_handler: logging.Handler
        if when is not None:
            file_handler = TimedRotatingFileHandler(
                filename=log_file,
                when=when,
                interval=interval,
                backupCount=backup_count,
            )
        elif max_bytes > 0:
            file_handler = RotatingFileHandler(
                filename=log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
            )
        else:
            file_handler = logging.FileHandler(filename=log_file)

        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
