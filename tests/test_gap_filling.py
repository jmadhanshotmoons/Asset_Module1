"""Category / Subcategory / Asset Type gap filling: other rows first, then AI (mocked here)."""
import io

import openpyxl

from punctualiti import ai
from punctualiti.asset import clean_asset_file
from punctualiti.excel import display_header

HEADERS = ["Asset Name", "Category", "Subcategory", "Asset Type", "Service Type", "Status",
           "Critical", "Building", "Floor", "Room", "UOM"]


def make_file(rows) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def read(result):
    ws = openpyxl.load_workbook(io.BytesIO(result.content)).active
    h = {display_header(c.value): c.column for c in ws[1]}
    return ws, h


BASE = ["Technical Services", "Working", "Yes", "Tower A", "Ground", "Pump Room", "NA"]


def test_filled_from_other_rows():
    f = make_file([
        ["Pump 1", "Plumbing", "Transfer Pump", "Pump", *BASE],
        ["Pump 2", None, "Transfer Pump", "Pump", *BASE],
    ])
    ws, h = read(clean_asset_file(f, use_ai=False))
    cell = ws.cell(3, h["Category"])
    assert cell.value == "Plumbing"
    assert "Filled from other rows" in cell.comment.text


def test_ai_suggestions_are_amber(monkeypatch):
    calls = []

    def fake_classify(items, examples):
        calls.append(items)
        return {i["id"]: ai.Suggestion("Electrical", "UPS", "UPS") for i in items}

    monkeypatch.setattr(ai, "classify", fake_classify)
    f = make_file([["UPS 1", None, None, None, *BASE]])
    ws, h = read(clean_asset_file(f))
    assert len(calls) == 1 and calls[0][0]["asset_name"] == "UPS 01"
    for key in ("Category", "Subcategory", "Asset Type"):
        cell = ws.cell(2, h[key])
        assert "Suggested by AI" in cell.comment.text
        assert cell.fill.start_color.rgb == "FFFFE699"


def test_without_key_gaps_stay_red(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "PUNCTUALITI_AI_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    f = make_file([["UPS 1", None, None, None, *BASE]])
    result = clean_asset_file(f)
    ws, h = read(result)
    cell = ws.cell(2, h["Category"])
    assert cell.value is None
    assert cell.fill.start_color.rgb == "FFFF9999"
    assert "AI not set up" in cell.comment.text
    assert "AI not set up" in result.ai_status


def test_missing_required_column_is_red_header():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Asset Name", "Category", "Asset Type"])
    ws.append(["Chiller 1", "HVAC", "Chiller"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    out, h = read(clean_asset_file(buf, use_ai=False))
    header = out.cell(1, h["Building"])
    assert "Column missing in client file" in header.comment.text


def test_renamed_column_is_matched_and_flagged():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Equipment Name", "Category", "Asset Type", "Location"])
    ws.append(["Chiller 1", "HVAC", "Chiller", "Basement 1, Plant Room"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    out, h = read(clean_asset_file(buf, use_ai=False))
    assert out.cell(2, h["Asset Name"]).value == "Chiller 01"
    assert "Equipment Name" in out.cell(1, h["Asset Name"]).comment.text
    assert out.cell(2, h["Floor"]).value == "BM1"
    assert out.cell(2, h["Room"]).value == "Plant Room"


def test_provider_selection(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "PUNCTUALITI_AI_PROVIDER", "PUNCTUALITI_AI_MODEL", "AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(var, raising=False)
    assert ai.provider() is None

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    assert ai.provider() == ai.BEDROCK
    assert ai._model(ai.BEDROCK) == "anthropic.claude-opus-5-5"
    assert "ap-south-1" in ai.describe() and "test-secret" not in ai.describe()
    ai._client(ai.BEDROCK)  # builds offline, no request sent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert ai.provider() == ai.ANTHROPIC
    monkeypatch.setenv("PUNCTUALITI_AI_PROVIDER", "bedrock")
    assert ai.provider() == ai.BEDROCK
