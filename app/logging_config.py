from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(logfile_name: str) -> None:
    """Configure root logging with a console handler plus a rotating file handler under
    ``storage_dir/logs``. Without this, RQ worker processes (which never import app.main)
    have no handler beyond Python's bare stderr fallback — failures scroll past in whatever
    terminal happens to be open and are gone the moment it's closed."""
    log_dir = Path(settings.storage_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler(log_dir / logfile_name, maxBytes=5_000_000, backupCount=3),
    ]
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, handlers=handlers, force=True)
