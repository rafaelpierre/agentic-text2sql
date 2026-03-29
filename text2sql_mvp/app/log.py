"""Logging configuration for the Text2SQL pipeline."""
from __future__ import annotations

import logging
import os

# ANSI colour codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_BLUE = "\033[34m"
_RED = "\033[31m"
_DIM = "\033[2m"


class _ColourFormatter(logging.Formatter):
    _LEVEL_COLOURS = {
        logging.DEBUG: _DIM,
        logging.INFO: _CYAN,
        logging.WARNING: _YELLOW,
        logging.ERROR: _RED,
        logging.CRITICAL: _RED + _BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        colour = self._LEVEL_COLOURS.get(record.levelno, "")
        level = f"{colour}{record.levelname:<8}{_RESET}"
        name = f"{_DIM}{record.name}{_RESET}"
        msg = super().format(record)
        # Re-inject coloured level + name
        msg = msg.replace(record.levelname, level.strip(), 1)
        return msg

    def formatMessage(self, record: logging.LogRecord) -> str:
        colour = self._LEVEL_COLOURS.get(record.levelno, "")
        return (
            f"{_DIM}[{record.name}]{_RESET} "
            f"{colour}{record.getMessage()}{_RESET}"
        )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def configure_logging(level: int | None = None) -> None:
    """Configure root logger with colour output.  Call once at startup."""
    if level is None:
        env = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, env, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(_ColourFormatter("%(levelname)s %(message)s"))

    root = logging.getLogger("text2sql")
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)
    root.propagate = False
