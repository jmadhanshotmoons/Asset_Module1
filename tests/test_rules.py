"""Unit tests for the deterministic rules, using values taken from the real client files."""
import pytest

from punctualiti.location import find_floors, normalise_building, split_location
from punctualiti.text import normalise_name, smart_case, format_date
from punctualiti.units import split_capacity


@pytest.mark.parametrize("raw, expected", [
    ("UPS-1", "UPS-01"),
    ("FHC1", "FHC01"),
    ("Fhc", "FHC"),
    (" Incomer ACB   No1", "Incomer ACB No01"),
    ("Compressor no-1", "Compressor No-01"),
    ("Water Transfer Pump 1 ", "Water Transfer Pump 01"),
    ("EXHAUST AIR", "Exhaust Air"),
    ("led tv", "LED TV"),
    ("CO2", "CO2"),
    ("Fire Extinguisher 4.5Kg", "Fire Extinguisher 4.5Kg"),
    ("UPS 01 120 kVA GF", "UPS 01 120 kVA GF"),
])
def test_asset_names(raw, expected):
    assert normalise_name(raw, 2) == expected


def test_casing_keeps_codes():
    assert smart_case("KS749273U") == "KS749273U"
    assert smart_case("tower  A") == "Tower A"


@pytest.mark.parametrize("raw, expected, flagged", [
    ("Tower c ", "Tower C", False),
    ("Tower  B ", "Tower B", False),
    ("Tower -B", "Tower B", False),
    (" Towerr-b ", "Tower B", True),
    ("TB", "Tower B", True),
    ("T-01", "Tower 1", True),
    ("Main Block", "Main Block", False),
])
def test_buildings(raw, expected, flagged):
    value, note = normalise_building(raw)
    assert value == expected
    assert bool(note) == flagged


@pytest.mark.parametrize("text, code", [
    ("Basement-1", "BM1"), ("BASE -3", "BM3"), ("B-2 Misting Room", "BM2"), ("basement 1", "BM1"),
    ("Ground", "GF"), ("LGF", "LGF"), ("UG", "UGF"), ("5th Floor", "5F"), ("1F", "1F"),
    ("Audi Tarrace", "Terrace"),
])
def test_floor_codes(text, code):
    assert [m.code for m in find_floors(text)] == [code]


def test_no_floor_in_room_name():
    assert find_floors("UPS Room") == []
    assert find_floors("Security Room") == []


def test_location_spec_examples():
    loc = split_location("", "CW-B1-LT room", "")
    assert (loc.building, loc.floor, loc.room) == ("CW", "BM1", "LT Room")
    loc = split_location("Tower 1", "basement 1, LT room", "")
    assert (loc.floor, loc.room) == ("BM1", "LT Room")


def test_location_single_combined_column():
    # Client has only a 'Location' column (mapped to Room) and no Floor/Building values.
    loc = split_location("", "", "CW-B1-LT room")
    assert (loc.building, loc.floor, loc.room, loc.floor_level) == ("CW", "BM1", "LT Room", None)
    loc = split_location("Tower 2", "", "GF, Reception")
    assert (loc.building, loc.floor, loc.room, loc.floor_level) == ("Tower 2", "GF", "Reception", None)


def test_location_repeated_text():
    loc = split_location("Tower 1", "Pump Room, Basement 2", "Pump Room, Basement 2")
    assert (loc.floor, loc.room, loc.floor_level) == ("BM2", "Pump Room", None)


def test_location_swapped_columns_are_flagged():
    loc = split_location("Tower C", "Security Room", "Ground")
    assert (loc.floor, loc.room, loc.floor_level) == ("GF", "Security Room", "amber")


def test_location_unknown_is_red():
    loc = split_location("Tower 1", "UPS Room", "UPS Room")
    assert loc.floor_level == "red"


def test_location_conflict_is_red():
    loc = split_location("Tower 1", "Ground", "Basement 1")
    assert loc.floor_level == "red"


@pytest.mark.parametrize("cap, uom, value, unit, level", [
    ("6KG", None, "6", "KG", None),
    ("9 liters", None, "9", "Liter", None),
    ("7.5 KW", "KW", "7.5", "KW", None),
    ("450 Tr", " TR", "450", "TR", None),
    ("Capacity : 10KL", None, "10", "KL", None),
    ("2500 (ACB)", "AMP", "2500", "AMP", "amber"),
    ("7.5kw", "HP", "7.5", "HP", "red"),
    ("22", None, "22", "", "red"),
    ("3.7KW/5HP", "HP", "3.7KW/5HP", "HP", "red"),
    (None, None, "NA", "NA", None),
])
def test_capacity(cap, uom, value, unit, level):
    c = split_capacity(cap, uom)
    assert (c.value, c.uom, c.level) == (value, unit, level)


def test_dates():
    assert format_date("2018-04-01") == "01-04-2018"
    assert format_date("15/04/2018") == "15-04-2018"
    assert format_date("soon") is None
