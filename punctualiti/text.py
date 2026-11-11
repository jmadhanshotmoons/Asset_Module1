"""Deterministic text rules: spacing, casing, zero-padding, empty markers."""
from __future__ import annotations

import datetime as dt
import re

from . import config

NA = "NA"


def clean_spaces(value) -> str:
    """Trim and collapse any run of whitespace (incl. newlines/tabs) to one space."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())


def is_empty(value) -> bool:
    markers = set(config.asset_rules()["empty_markers"])
    return clean_spaces(value).lower() in markers


def _case_letters(part: str, abbrev: dict[str, str]) -> str:
    hit = abbrev.get(part.lower())
    if hit:
        return hit
    if part.isupper() or part.islower():
        return part[:1].upper() + part[1:].lower()
    return part  # mixed case such as 'iPhone' or 'kVA' is left as the client wrote it


def _case_word(word: str, abbrev: dict[str, str]) -> str:
    """Case one space-separated word. Parts split on '-' or '/' are cased separately
    ('no-1' -> 'No-1', 'B1-Office' -> 'B1-Office'). A part that is letters followed by
    digits ('Fhc1') gets its letters cased; any other part with digits ('4.5Kg',
    'KS749273U') is left exactly as written unless it is a known abbreviation ('co2')."""
    pieces = re.split(r"([-/])", word)
    out = []
    for p in pieces:
        if p in ("-", "/") or not p:
            out.append(p)
        elif p.lower() in abbrev:
            out.append(abbrev[p.lower()])
        elif p.isalpha():
            out.append(_case_letters(p, abbrev))
        elif m := re.fullmatch(r"([A-Za-z]+)(\d+)", p):
            out.append(_case_letters(m.group(1), abbrev) + m.group(2))
        else:
            out.append(p)
    return "".join(out)


def smart_case(text: str) -> str:
    """'EXHAUST AIR' -> 'Exhaust Air', 'fhc' -> 'FHC', 'led tv' -> 'LED TV'."""
    abbrev = config.abbreviations()
    return " ".join(_case_word(w, abbrev) for w in clean_spaces(text).split(" ") if w)


_TRAILING_NUM = re.compile(r"^(.*?)(\d+)$")


def pad_trailing_number(text: str, width: int = 2) -> str:
    """'UPS-1' -> 'UPS-01', 'FHC1' -> 'FHC01', 'Pump 2' -> 'Pump 02'. Decimals untouched."""
    m = _TRAILING_NUM.match(text)
    if not m:
        return text
    head, num = m.groups()
    if head.endswith((".", ",")) and head[:-1][-1:].isdigit():
        return text  # '4.5' is a decimal, not a serial
    return f"{head}{num.zfill(width)}"


def normalise_name(value, width: int) -> str:
    name = smart_case(value)
    last = name.rsplit(" ", 1)[-1].lower()
    if last in config.abbreviations():
        return name  # 'CO2' is a name, not 'CO' number 2
    return pad_trailing_number(name, width)


def format_date(value) -> str | None:
    """Return dd-mm-yyyy, or None if the value isn't a recognisable date."""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%d-%m-%Y")
    s = clean_spaces(value)
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return None


def number_text(value) -> str:
    """7.0 -> '7', 7.50 -> '7.5', '011' -> '011' (strings keep their digits)."""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return clean_spaces(value)
