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
from app.importer import ImportProblem, read_table, to_items, to_parties
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_samples():
    """Imports replace the whole list; put the sample data back for the other tests."""
    yield
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())
    db.replace_parties([dict(p, aliases=list(p["aliases"])) for p in catalog.SAMPLE_PARTIES])
    catalog.replace_parties(db.list_parties())


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


def test_seed_parties_still_ask_which_sharma():
    d = client.post("/api/parse", json={"text": "Sharma ji ko 10 carton Lux kal"}).json()
    assert d["party"]["status"] == "choose" and len(d["party"]["options"]) == 2


def test_ambiguous_words_from_shared_first_word():
    amb = catalog.ambiguous_words([
        {"code": "P1", "name": "Verma Kirana Store", "aliases": []},
        {"code": "P2", "name": "Verma Brothers", "aliases": []},
        {"code": "P3", "name": "New Punjab Stores", "aliases": []},
        {"code": "P4", "name": "New Delhi Traders", "aliases": []},
    ])
    assert amb["verma"] == ["P1", "P2"] and amb["verma ji"] == ["P1", "P2"]
    assert "new" not in amb


def test_busy_account_list_keeps_only_debtors_and_asks_which_one():
    data = _xlsx([["Name", "Group"],
                  ["Verma Kirana Store", "Sundry Debtors"], ["Verma Brothers", "Sundry Debtors"],
                  ["HDFC Bank", "Bank Accounts"], ["Rent", "Indirect Expenses"]])
    parties, skipped = to_parties(read_table("acc.xlsx", data))
    assert [p["name"] for p in parties] == ["Verma Kirana Store", "Verma Brothers"]
    assert parties[0]["code"] == "P001" and "verma kirana" in parties[0]["aliases"]
    assert {s["reason"] for s in skipped} == {"customer nahi"}
    r = client.post("/api/parties/import?commit=1", files={"file": ("acc.xlsx", data, "application/octet-stream")})
    assert r.json()["committed"] is True and [p["name"] for p in client.get("/api/parties").json()] == [
        "Verma Kirana Store", "Verma Brothers"]
    d = client.post("/api/parse", json={"text": "Verma ko 10 carton Lux kal"}).json()
    assert d["party"]["status"] == "choose"
    d = client.post("/api/parse", json={"text": "Verma Brothers ko 10 carton Lux kal"}).json()
    assert d["party"]["party"]["name"] == "Verma Brothers"
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton Lux kal"}).json()
    assert d["party"]["status"] != "ok"  # old sample parties are gone


def test_party_list_without_group_column_keeps_all():
    parties, skipped = to_parties(read_table("p.csv", b"Party Name\nBansal Store\nKhanna Traders\n"))
    assert [p["name"] for p in parties] == ["Bansal Store", "Khanna Traders"] and skipped == []


# ------------------------------------------------ final review fixes
def _commit_items(csv_text):
    client.post("/api/items/import?commit=1", files={"file": ("i.csv", csv_text.encode(), "text/csv")})


def _commit_parties(csv_text):
    return client.post("/api/parties/import?commit=1", files={"file": ("p.csv", csv_text.encode(), "text/csv")}).json()


def test_real_busy_groups_do_not_block_full_item_names():
    _commit_items("Name,Group,Unit\nLux Soap,HUL,Box\nToor Dal,Pulses,Bori\nHaldi Powder,Masala,Pkt\n"
                  "Surf Excel,Detergent Powder,Box\n")
    for text, name in [("ABC ko 10 carton lux soap kal", "Lux Soap"), ("ABC ko 2 bori toor dal kal", "Toor Dal"),
                       ("ABC ko 5 packet haldi powder kal", "Haldi Powder")]:
        ln = client.post("/api/parse", json={"text": text}).json()["lines"][0]
        assert ln["match"] == "ok" and ln["item"]["name"] == name, text


def test_generic_word_never_asks_with_no_options():
    _commit_items("Name,Group,Unit\nLux Soap,HUL,Box\nToor Dal,Pulses,Bori\n")
    ln = client.post("/api/parse", json={"text": "ABC ko 10 carton sabun kal"}).json()["lines"][0]
    assert ln["match"] != "ok" and (ln["options"] or ln["match"] == "unknown")
    assert not (ln["match"] == "choose" and not ln["options"])


def test_group_only_from_exact_busy_group_name():
    items, _ = to_items(read_table("g.csv", b"Name,Group\nA one,Soaps\nB two,Masala Powder\nC three,Dalda\nD four,Detergents\n"))
    assert [i["group"] for i in items] == ["soap", None, None, "detergent"]


def test_numeric_or_short_busy_alias_never_names_a_party():
    _commit_parties("Name,Alias\nVerma Store,10\nGupta Kirana,GK\n")
    d = client.post("/api/parse", json={"text": "Gupta ko 10 carton Lux kal"}).json()
    assert d["party"]["party"]["name"] == "Gupta Kirana"
    assert "10" not in [a for p in client.get("/api/parties").json() for a in p["aliases"]]


def test_reimport_keeps_party_codes():
    first = {p["name"]: p["code"] for p in _commit_parties("Name\nVerma Store\nGupta Kirana\n") and client.get("/api/parties").json()}
    _commit_parties("Name\nAgarwal Traders\nGupta Kirana\nVerma Store\n")
    second = {p["name"]: p["code"] for p in client.get("/api/parties").json()}
    assert second["Verma Store"] == first["Verma Store"] and second["Gupta Kirana"] == first["Gupta Kirana"]
    assert second["Agarwal Traders"] not in first.values()


def test_near_duplicate_party_names_ask():
    _commit_parties("Name\nShiv Traders\nShiva Traders\n")
    d = client.post("/api/parse", json={"text": "Shiv Trader ko 10 carton Lux kal"}).json()
    assert d["party"]["status"] == "choose"


def test_debtor_subgroups_kept_other_ledgers_dropped():
    parties, skipped = to_parties(read_table("a.csv", b"Name,Group\nRam Kirana,Delhi Parties\nShyam Store,Sundry Debtors\n"
                                                      b"HDFC Bank,Bank Accounts\nRent,Indirect Expenses\nAmul Dist,Sundry Creditors\n"))
    assert [p["name"] for p in parties] == ["Ram Kirana", "Shyam Store"]
    assert len(skipped) == 3


def test_keyterms_keep_parties_with_big_item_list():
    from app import stt
    _commit_items("Name\n" + "".join(f"Item number {n}\n" for n in range(80)))
    terms = stt._keyterms()
    assert "ABC Traders" in terms and len(terms) <= 50


def test_csv_with_odd_bytes_reads():
    items, _ = to_items(read_table("x.csv", b"name,unit\nA\x81B,kg\n"))
    assert len(items) == 1
