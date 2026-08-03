"""Loguru tabanlı merkezi loglama."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_configured = False


def setup_logging(log_path: "str | Path | None" = None, level: str = "INFO"):
    global _configured
    if _configured:
        return logger
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
               "<cyan>{name}</cyan> - <level>{message}</level>",
    )
    if log_path:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        logger.add(str(p), level="DEBUG", rotation="10 MB", retention="14 days",
                   encoding="utf-8")
    _configured = True
    return logger


log = logger
