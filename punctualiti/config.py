"""Loads the editable JSON rule files in /config."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    """Read config/<name>.json. Cached; restart the app after editing."""
    with open(CONFIG_DIR / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def abbreviations() -> dict[str, str]:
    """Lowercase word -> required casing (e.g. 'kva' -> 'kVA')."""
    return {w.lower(): w for w in load("abbreviations")["words"]}


def units() -> dict[str, str]:
    return {k.lower(): v for k, v in load("units")["units"].items()}


def floors() -> dict:
    return load("floors")


def asset_rules() -> dict:
    return load("asset_rules")
