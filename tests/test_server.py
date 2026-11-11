"""API server tests (AI off, so no network)."""
import io

import openpyxl
import pytest

from server import app

HEADERS = ["Asset Name", "Category", "Asset Type", "Service Type", "Status", "Critical", "Building", "Floor", "Room", "UOM"]


def xlsx() -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    ws.append(["ups-1", "Electrical", "UPS", "Technical Services", "Working", "Yes", "Tower a", "basement 1", "UPS Room", "kVA"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    return app.test_client()


def test_health(client):
    assert client.get("/health").get_json()["ok"] is True


def test_clean_returns_xlsx(client):
    r = client.post("/api/asset/clean", data={"file": (xlsx(), "list.xlsx"), "use_ai": "0"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.headers["X-Rows"] == "1"
    assert "list_cleaned.xlsx" in r.headers["Content-Disposition"]
    ws = openpyxl.load_workbook(io.BytesIO(r.data)).active
    assert ws["A2"].value == "UPS-01"


def test_clean_json(client):
    r = client.post("/api/asset/clean?format=json", data={"file": (xlsx(), "list.xlsx"), "use_ai": "0"},
                    content_type="multipart/form-data")
    j = r.get_json()
    assert j["rows"] == 1 and j["file_b64"]


def test_password_required(client, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret-for-test")
    r = client.post("/api/asset/clean", data={"file": (xlsx(), "list.xlsx")}, content_type="multipart/form-data")
    assert r.status_code == 401
    r = client.post("/api/asset/clean", data={"file": (xlsx(), "list.xlsx"), "use_ai": "0"},
                    content_type="multipart/form-data", headers={"X-App-Password": "secret-for-test"})
    assert r.status_code == 200


def test_rejects_non_xlsx(client):
    r = client.post("/api/asset/clean", data={"file": (io.BytesIO(b"a,b"), "list.csv")}, content_type="multipart/form-data")
    assert r.status_code == 400
