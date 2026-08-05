from __future__ import annotations

import configparser
import os
from pathlib import Path

_config = configparser.ConfigParser()
_config.read(Path(__file__).resolve().parent.parent.parent / "config.ini")

API_BASE: str = os.getenv("API_BASE") or _config.get(
    "ui", "api_base", fallback="http://localhost:8001"
)
