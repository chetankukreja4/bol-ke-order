"""Loading the shop's own item and party lists from a Busy export (CSV or Excel)."""
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
from app.importer import ImportProblem, read_table, to_items
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_samples():
    """Imports replace the whole list; put the sample data back for the other tests."""
    yield
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_busy_xlsx_with_title_block():
    data = _xlsx([["Gupta Wholesale"], ["Item List as on 27-11-2026"], [],
                  ["Name", "Alias", "Group", "Main Unit"],
                  ["Lux Soap 100g", "LUX100", "Soaps", "Box"],
                  ["Parle G 800g", "", "Biscuits", "Pcs"],
                  ["", "", "", ""]])
    items, skipped = to_items(read_table("items.xlsx", data))
    assert [i["name"] for i in items] == ["Lux Soap 100g", "Parle G 800g"]
    assert items[0]["unit"] == "carton" and items[0]["group"] == "soap"  # "box" is a carton word
    assert items[1]["unit"] == "piece" and items[1]["group"] is None
    assert "lux100" in items[0]["aliases"] and "lux soap 100g" in items[0]["aliases"]
    assert items[0]["code"] == "I001" and skipped == []


def test_simple_csv_and_skips():
    csv = "code,name,unit,aliases\nSP9,Tata Salt,kg,namak|tata namak\nXX,,kg,\nSP10,tata salt,kg,\n"
    items, skipped = to_items(read_table("x.csv", csv.encode()))
    assert items[0]["code"] == "SP9" and items[0]["unit"] == "kg" and "namak" in items[0]["aliases"]
    assert [s["reason"] for s in skipped] == ["naam nahi", "dobara aaya"]


def test_units_never_fail_the_file():
    csv = "name,unit\nA one,Kgs\nB two,Bori\nC three,\nD four,Dozen\n"
    items, _ = to_items(read_table("u.csv", csv.encode()))
    assert [i["unit"] for i in items] == ["kg", "bag", "piece", "piece"]


def test_xls_refused():
    with pytest.raises(ImportProblem):
        read_table("old.xls", b"\xd0\xcf\x11\xe0")


def test_import_endpoint_preview_then_commit_changes_matching():
    body = b"name,unit\nKurkure Masala,packet\n"
    p = client.post("/api/items/import", files={"file": ("i.csv", body, "text/csv")}).json()
    assert p["count"] == 1 and p["committed"] is False and p["sample"][0]["name"] == "Kurkure Masala"
    d = client.post("/api/parse", json={"text": "ABC ko 5 packet kurkure masala kal"}).json()
    assert d["lines"][0]["match"] != "ok"  # preview changed nothing
    c = client.post("/api/items/import?commit=1", files={"file": ("i.csv", body, "text/csv")}).json()
    assert c["committed"] is True
    d = client.post("/api/parse", json={"text": "ABC ko 5 packet kurkure masala kal"}).json()
    assert d["lines"][0]["item"]["name"] == "Kurkure Masala"
    assert client.post("/api/items/import", files={"file": ("a.xls", b"x", "application/vnd.ms-excel")}).status_code == 400
