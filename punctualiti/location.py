"""Building / Floor / Room parsing. Best effort only: anything unsure is reported, never guessed silently."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .text import clean_spaces, smart_case


@dataclass
class FloorMatch:
    code: str
    start: int
    end: int
    note: str | None = None  # set when the code is an interpretation the reviewer should confirm


def _word_alt(words: list[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


def find_floors(text: str) -> list[FloorMatch]:
    """All floor mentions in a free-text location, left to right, non-overlapping."""
    cfg = config.floors()
    t = text.lower()
    found: list[FloorMatch] = []

    def add(m: re.Match, code: str, note: str | None = None) -> None:
        if not any(m.start() < f.end and f.start < m.end() for f in found):
            found.append(FloorMatch(code, m.start(), m.end(), note))

    b = cfg["basement"]
    for m in re.finditer(rf"(?<![a-z0-9])(?:{_word_alt(b['words'])})\s*[-.]?\s*0*(\d{{1,2}})(?![0-9])", t):
        add(m, b["code"].format(n=int(m.group(1))))

    f = cfg["numbered_floor"]
    for m in re.finditer(rf"(?<![a-z0-9])0*(\d{{1,3}})\s*(?:st|nd|rd|th)?\s*[-.]?\s*(?:{_word_alt(f['words'])})(?![a-z])", t):
        add(m, f["code"].format(n=int(m.group(1))))

    for code, words in cfg["fixed"].items():
        for m in re.finditer(rf"(?<![a-z0-9])(?:{_word_alt(words)})(?![a-z0-9])", t):
            add(m, code)

    # 'basement' with no number
    for m in re.finditer(r"(?<![a-z0-9])basement(?![a-z0-9]|\s*[-.]?\s*\d)", t):
        add(m, b["bare_word_code"], f"'basement' with no number read as {b['bare_word_code']}")

    return sorted(found, key=lambda x: x.start)


def strip_span(text: str, start: int, end: int) -> str:
    """Remove a matched span and tidy leftover separators/brackets."""
    rest = text[:start] + " " + text[end:]
    rest = re.sub(r"\(\s*\)", " ", rest)
    rest = rest.strip(" ,;-/|_.")
    rest = re.sub(r"^\((.*)\)$", r"\1", rest.strip())
    rest = re.sub(r"\s*,\s*", ", ", rest)
    rest = re.sub(r"(?:^|\s)[,;-]\s*$", "", rest)
    return clean_spaces(rest.strip(" ,;-/|_.()"))


_BUILDING = re.compile(r"^(?:tower|towerr|towar|twr|t)\s*[-.]?\s*0*([a-z]|\d{1,3})$", re.I)


def normalise_building(value) -> tuple[str, str | None]:
    """'Tower c ' -> 'Tower C', ' Towerr-b ' -> 'Tower B', 'T-01' -> 'Tower 1'.

    Returns (value, note). A note means the reading should be checked (e.g. 'TB').
    Values that don't look like a tower are only re-spaced and re-cased.
    """
    raw = clean_spaces(value)
    m = _BUILDING.match(raw)
    if not m:
        return smart_case(raw), None
    result = f"Tower {m.group(1).upper()}"
    word = re.match(r"[a-z]+", raw, re.I).group(0).lower()
    note = None
    if word == "t" or word not in ("tower",):
        note = f"Read '{raw}' as '{result}'"
    return result, note


@dataclass
class Location:
    building: str
    floor: str
    room: str
    floor_level: str | None = None   # None = confident; "amber" / "red" otherwise
    floor_note: str | None = None
    room_note: str | None = None
    building_note: str | None = None


def split_location(building: str, floor: str, room: str) -> Location:
    """Work out Floor and Room from the client's Floor and Room columns (either may hold free text).

    Cases, in order:
      1. Floor text contains one floor   -> use it; leftover text becomes Room if Room is empty,
                                           repeats the Floor text, or is itself only a floor.
      2. Only Room text contains a floor -> columns look swapped; swap and flag amber.
      3. No floor anywhere              -> keep the text, flag red.
    """
    floor, room = clean_spaces(floor), clean_spaces(room)
    in_floor, in_room = find_floors(floor), find_floors(room)

    if len({m.code for m in in_floor}) > 1:
        codes = ", ".join(sorted({m.code for m in in_floor}))
        return Location(building, floor, smart_case(room), "red", f"More than one floor in '{floor}' ({codes})")

    if in_floor:
        m = in_floor[0]
        loc = Location(building, m.code, smart_case(room), "amber" if m.note else None, m.note)
        prefix = floor[: m.start].strip(" -,/")
        if not building and prefix:
            # 'CW-B1-LT room': text before the floor is the building.
            loc.building = clean_spaces(prefix)
            loc.building_note = f"Building taken from location text '{floor}'"
            leftover = smart_case(strip_span(floor, 0, m.end))
        else:
            leftover = smart_case(strip_span(floor, m.start, m.end))

        room_is_only_floor = bool(in_room) and not strip_span(room, in_room[0].start, in_room[0].end)
        if not room or room.lower() == floor.lower():
            loc.room = leftover
        elif room_is_only_floor:
            if in_room[0].code != m.code:
                loc.floor_level = "red"
                loc.floor_note = f"Floor says {m.code} but Room says {in_room[0].code}"
            loc.room = leftover
        elif leftover and leftover.lower() not in loc.room.lower():
            loc.room_note = f"Floor column also said '{leftover}'"
        return loc

    if in_room:
        m = in_room[0]
        parts = [smart_case(floor), smart_case(strip_span(room, m.start, m.end))]
        return Location(building, m.code, ", ".join(p for p in parts if p), "amber",
                        f"Floor and Room looked swapped (Floor was '{floor}', Room was '{room}')")

    if not floor:
        return Location(building, "", smart_case(room), "red", "Floor missing")
    return Location(building, floor, smart_case(room), "red", f"Could not recognise a floor in '{floor}'")
