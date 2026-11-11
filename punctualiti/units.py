"""Split combined value + unit cells: '6KG' -> ('6', 'KG'), '9 liters' -> ('9', 'Liter')."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .text import NA, clean_spaces, is_empty, number_text

_VALUE_UNIT = re.compile(r"^(\d+(?:\.\d+)?)\s*([a-z][a-z0-9/]*)?\.?$", re.I)
_VALUE_PAREN = re.compile(r"^(\d+(?:\.\d+)?)\s*\(([^)]*)\)$")


def normalise_unit(text: str) -> str | None:
    key = re.sub(r"\s+", "", clean_spaces(text)).lower().rstrip(".")
    return config.units().get(key)


@dataclass
class Capacity:
    value: str
    uom: str
    level: str | None = None  # None, "amber" or "red"
    note: str | None = None


def split_capacity(capacity, uom) -> Capacity:
    """Combine the client's Capacity and UOM columns into a clean value and unit."""
    cap_raw = "" if is_empty(capacity) else number_text(capacity)
    cap_raw = re.sub(r"^(?:capacity|cap|rating)\s*[:=-]\s*", "", cap_raw, flags=re.I)
    uom_raw = "" if is_empty(uom) else clean_spaces(uom)
    uom_std = normalise_unit(uom_raw) if uom_raw else None
    if uom_raw and not uom_std:
        uom_std = uom_raw

    if not cap_raw:
        return Capacity(NA, uom_std or NA)

    m = _VALUE_UNIT.match(cap_raw)
    if m:
        value, unit_txt = m.group(1), m.group(2)
        if not unit_txt:
            if uom_std:
                return Capacity(value, uom_std)
            return Capacity(value, "", "red", "Capacity has no unit and UOM is empty")
        unit = normalise_unit(unit_txt)
        if not unit:
            return Capacity(cap_raw, uom_std or "", "red", f"Unknown unit '{unit_txt}' in capacity '{cap_raw}'")
        if uom_std and uom_std.lower() != unit.lower():
            return Capacity(value, uom_std, "red", f"Capacity '{cap_raw}' says {unit} but UOM says {uom_std}")
        return Capacity(value, unit)

    m = _VALUE_PAREN.match(cap_raw)
    if m and uom_std:
        return Capacity(m.group(1), uom_std, "amber", f"Removed '({m.group(2)})' from capacity '{cap_raw}'")

    return Capacity(cap_raw, uom_std or "", "red", f"Could not split capacity '{cap_raw}' into value + UOM")
