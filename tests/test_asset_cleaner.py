"""End-to-end test of Module 1 on the real client asset list in samples/ (AI switched off)."""
import io
from pathlib import Path

import openpyxl
import pytest

from punctualiti.asset import clean_asset_file
from punctualiti.excel import display_header

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "Asset list.xlsx"


@pytest.fixture(scope="module")
def result():
    if not SAMPLE.exists():
        pytest.skip("sample file not present")
    return clean_asset_file(SAMPLE, use_ai=False)


@pytest.fixture(scope="module")
def sheet(result):
    ws = openpyxl.load_workbook(io.BytesIO(result.content)).active
    headers = {display_header(c.value): c.column for c in ws[1]}
    return ws, headers


def test_keeps_template_headers(sheet):
    ws, headers = sheet
    template = openpyxl.load_workbook("punctualiti/data/asset_template.xlsx").active
    assert [c.value for c in ws[1]] == [c.value for c in template[1]]


def test_all_rows_written(result, sheet):
    ws, _ = sheet
    assert result.rows == 641
    assert ws.max_row == 642


def test_first_row_cleaned(sheet):
    ws, h = sheet
    row = {k: ws.cell(2, c).value for k, c in h.items()}
    assert row["Asset Name"] == "Incomer ACB No01"
    assert row["Subcategory"] == "Incomer ACB"
    assert row["Building"] == "Tower 1"
    assert row["Floor"] == "BM1"
    assert row["Room"] == "LT Room"
    assert row["Capacity"] == "2500"
    assert row["UOM"] == "AMP"
    assert row["Wing"] == "NA"


def test_no_double_spaces_anywhere(sheet):
    ws, _ = sheet
    for row in ws.iter_rows(min_row=2, values_only=True):
        for v in row:
            if isinstance(v, str):
                assert v == v.strip() and "  " not in v


def test_flags_are_in_cells(result, sheet):
    ws, h = sheet
    flagged = [c for row in ws.iter_rows(min_row=2) for c in row if c.comment]
    assert flagged, "expected highlighted cells"
    assert all(c.fill.start_color.rgb in ("FFFF9999", "FFFFE699") for c in flagged)
    assert result.red_cells > 0 and result.amber_cells > 0


def test_typo_corrected_and_flagged(sheet):
    ws, h = sheet
    col = h["Asset Type"]
    cameras = [ws.cell(r, col) for r in range(2, ws.max_row + 1) if ws.cell(r, col).value == "Camera"]
    assert cameras and all("Corrected" in c.comment.text for c in cameras)
