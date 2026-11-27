"""Shops without Busy fill a plain Excel template and import it (no OCR, no LLM)."""
import io
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import catalog, db
from app.main import app

client = TestClient(app)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def restore_samples():
    yield
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())
    db.replace_parties([dict(p, aliases=list(p["aliases"])) for p in catalog.SAMPLE_PARTIES])
    catalog.replace_parties(db.list_parties())


def _book(path):
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith(XLSX)
    return openpyxl.load_workbook(io.BytesIO(r.content))


def _filled(path, rows):
    wb = _book(path)
    for row in rows:
        wb.worksheets[0].append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_item_template_is_an_empty_sheet_with_clear_headers_and_help():
    wb = _book("/api/items/template.xlsx")
    first = wb.worksheets[0]
    assert [c.value for c in first[1]] == ["Name", "Unit", "Spoken names", "Code"]
    assert first.max_row == 1  # no example rows that could be imported by mistake
    assert len(wb.worksheets) == 2 and "carton" in str([c.value for row in wb.worksheets[1] for c in row])


def test_filled_item_template_imports():
    data = _filled("/api/items/template.xlsx", [
        ["PVC Pipe 1 inch 6kg", "piece", "pipe, inchy pipe, ek inch pipe", ""],
        ["Elbow 1 inch Heavy", "Pcs", "inchy heavy, heavy elbow", "EL01"],
        ["Water Tank 500L", "", "tanki, 500 wali tanki", ""],
    ])
    r = client.post("/api/items/import?commit=1", files={"file": ("my-items.xlsx", data, XLSX)}).json()
    assert r["committed"] is True and r["count"] == 3
    items = {i["name"]: i for i in client.get("/api/items").json()}
    assert items["Elbow 1 inch Heavy"]["code"] == "EL01" and items["Elbow 1 inch Heavy"]["unit"] == "piece"
    assert "inchy heavy" in items["Elbow 1 inch Heavy"]["aliases"]
    d = client.post("/api/parse", json={"text": "Gupta ko 4 piece inchy heavy kal"}).json()
    assert d["lines"][0]["item"]["name"] == "Elbow 1 inch Heavy"


def test_party_template_imports_with_spoken_names():
    wb = _book("/api/parties/template.xlsx")
    assert [c.value for c in wb.worksheets[0][1]] == ["Name", "Spoken names"]
    data = _filled("/api/parties/template.xlsx", [["Shree Ganesh Hardware", "ganesh wale, ganesh bhai"]])
    r = client.post("/api/parties/import?commit=1", files={"file": ("p.xlsx", data, XLSX)}).json()
    assert r["count"] == 1
    d = client.post("/api/parse", json={"text": "ganesh wale ko 10 carton Lux kal"}).json()
    assert d["party"]["party"]["name"] == "Shree Ganesh Hardware"


def test_saved_with_the_help_sheet_open_still_imports():
    wb = _book("/api/items/template.xlsx")
    wb.worksheets[0].append(["Ball Valve 1 inch", "piece", "valve, inchy valve", ""])
    wb.active = 1  # the shop saved it while looking at "Kaise bharein"
    buf = io.BytesIO(); wb.save(buf)
    r = client.post("/api/items/import", files={"file": ("x.xlsx", buf.getvalue(), XLSX)})
    assert r.status_code == 200 and r.json()["count"] == 1
