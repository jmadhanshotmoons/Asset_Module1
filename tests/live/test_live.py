"""Post-deploy checks against a LIVE app (Vercel Data Desk or the Render API).

Skipped unless LIVE_URL is set. Environment:
  LIVE_URL             e.g. https://desk.jmadhan.me or https://asset-module1.onrender.com
  LIVE_EXPECT_COMMIT   optional git SHA; waits (up to LIVE_WAIT_SECONDS, default 900) until the
                       live app reports this commit, so the tests run on the new deploy
  APP_PASSWORD         optional; without it the cleaning tests are skipped
  LIVE_TEST_AI=1       optional; also make one small real AI call

Only a small made-up workbook is uploaded, never client data.
"""
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid

import openpyxl
import pytest

URL = os.environ.get("LIVE_URL", "").rstrip("/")
PASSWORD = os.environ.get("APP_PASSWORD", "")
pytestmark = pytest.mark.skipif(not URL, reason="LIVE_URL not set")

HEADERS = ["Asset Name", "Category", "Subcategory", "Asset Type", "Service Type", "Status", "Critical",
           "Building", "Floor", "Room", "Capacity", "UOM"]


def http(method, path, body=None, headers=None, timeout=120):
    req = urllib.request.Request(URL + path, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def status():
    code, _, body = http("GET", "/api/status")
    assert code == 200, f"/api/status returned {code}"
    return json.loads(body)


def upload(workbook_rows, use_ai=False, password=PASSWORD):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in workbook_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"use_ai\"\r\n\r\n{'1' if use_ai else '0'}\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"live-check.xlsx\"\r\n"
            "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n").encode() \
        + buf.getvalue() + f"\r\n--{b}--\r\n".encode()
    headers = {"Content-Type": f"multipart/form-data; boundary={b}"}
    if password is not None:
        headers["X-App-Password"] = password
    # ?format=json: the Render API returns JSON with it; the Data Desk always returns JSON.
    return http("POST", "/api/asset/clean?format=json", body, headers, timeout=240)


@pytest.fixture(scope="session", autouse=True)
def wait_for_deploy():
    """Wake the app (Render free tier sleeps) and wait until it serves the expected commit."""
    expect = os.environ.get("LIVE_EXPECT_COMMIT", "")
    deadline = time.time() + int(os.environ.get("LIVE_WAIT_SECONDS", "900"))
    last = None
    while True:
        try:
            last = status().get("commit")
            if not expect or (last and last.startswith(expect[:12])):
                return
        except Exception as e:  # cold start, deploy in progress
            last = f"error: {e}"
        if time.time() > deadline:
            pytest.fail(f"Live app never reported commit {expect[:12]} (last seen: {last})")
        time.sleep(15)


def test_home_page_up():
    code, _, _ = http("GET", "/")
    assert code == 200


def test_status_reports_ai_and_password():
    s = status()
    assert s["ai_ready"] is True, f"AI not configured on the live app: {s.get('ai')}"
    assert s["password_required"] is True, "Live app is open without APP_PASSWORD"


def test_clean_without_password_is_refused():
    code, _, _ = upload([["UPS 1"] + [None] * 11], password="")
    assert code == 401


@pytest.mark.skipif(not PASSWORD, reason="APP_PASSWORD not provided")
def test_clean_returns_highlighted_workbook():
    rows = [
        ["ups-1", "Electrical", "UPS", "UPS", "Technical Services", "Working", "Yes", "Tower a", "basement 1", "UPS Room", "120 kva", None],
        ["Pump 2", "Plumbing", "Pump", "Pump", "Technical Services", "Working", "Yes", "TB", "Security Room", "Ground", "7.5kw", "HP"],
    ]
    code, _, body = upload(rows)
    assert code == 200, body[:300]
    j = json.loads(body)
    assert j["rows"] == 2
    ws = openpyxl.load_workbook(io.BytesIO(base64.b64decode(j["file_b64"]))).active
    assert ws["A2"].value == "UPS-01"
    h = {str(c.value).split("(")[0].replace("*", "").strip(): c.column for c in ws[1]}
    assert ws.cell(2, h["Building"]).value == "Tower A"
    assert ws.cell(2, h["Floor"]).value == "BM1"
    assert ws.cell(2, h["Capacity"]).value == "120" and ws.cell(2, h["UOM"]).value == "kVA"
    # row 3: 'TB' read as Tower B (amber), swapped floor/room (amber), unit conflict (red)
    assert ws.cell(3, h["Floor"]).value == "GF"
    assert ws.cell(3, h["Building"]).comment is not None
    assert ws.cell(3, h["Capacity"]).fill.start_color.rgb == "FFFF9999"
    assert j["red_cells"] >= 1 and j["amber_cells"] >= 2


@pytest.mark.skipif(not PASSWORD or os.environ.get("LIVE_TEST_AI") != "1", reason="AI check not requested")
def test_ai_fills_missing_category():
    code, _, body = upload([["UPS 1", None, None, None, "Technical Services", "Working", "Yes",
                             "Tower A", "GF", "UPS Room", None, None]], use_ai=True)
    assert code == 200, body[:300]
    j = json.loads(body)
    assert j["ai_status"].startswith("Used for 1 rows"), j["ai_status"]
    ws = openpyxl.load_workbook(io.BytesIO(base64.b64decode(j["file_b64"]))).active
    assert ws["B2"].value and "Suggested by AI" in ws["B2"].comment.text
