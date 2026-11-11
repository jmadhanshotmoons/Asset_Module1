"""Minimal .env loader so the Claude key can live in a local, git-ignored .env file."""
from __future__ import annotations

import os

from .config import ROOT


def load_dotenv(path=None) -> None:
    """Set KEY=VALUE lines from .env into os.environ (existing variables win)."""
    path = path or ROOT / ".env"
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass
