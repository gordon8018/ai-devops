"""Unified logging module for the Zoe orchestrator.

Provides a ``getLogger`` factory that returns pre-configured
:class:`logging.Logger` instances with structured output.

Usage::

    from orchestrator.bin.logger import getLogger

    log = getLogger(__name__)
    log.info("Pipeline started", extra={"pipeline": "build"})
    log.error("Step failed", extra={"step": "lint", "exit_code": 1})
"""

import logging
import sys
from typing import Optional


_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def getLogger(
    name: str,
    level: Optional[str] = None,
    fmt: Optional[str] = None,
    datefmt: Optional[str] = None,
) -> logging.Logger:
    """Return a configured :class:`logging.Logger`.

    Parameters
    ----------
    name:
        Logger name, typically ``__name__``.
    level:
        Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        Defaults to INFO.
    fmt:
        Custom format string. Defaults to structured timestamp/level/name format.
    datefmt:
        Custom date format string. Defaults to ISO-8601.

    Returns
    -------
    logging.Logger
        A configured logger instance.

    Examples
    --------
    >>> log = getLogger("mymodule")
    >>> log.info("hello")

    >>> log = getLogger("mymodule", level="DEBUG")
    >>> log.debug("verbose output")
    """
    logger = logging.getLogger(name)

    resolved_level = (level or "INFO").upper()
    if resolved_level not in _VALID_LEVELS:
        raise ValueError(
            f"Invalid log level: {level!r}. Must be one of {sorted(_VALID_LEVELS)}"
        )
    logger.setLevel(getattr(logging, resolved_level))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(getattr(logging, resolved_level))
        formatter = logging.Formatter(
            fmt=fmt or _DEFAULT_FORMAT,
            datefmt=datefmt or _DEFAULT_DATE_FORMAT,
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
