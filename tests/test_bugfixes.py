"""Bugs found in the full code and website check (27 Nov). One test per bug."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import copy

import openpyxl  # noqa: F401  (import check: the importer needs it)
import pytest
from fastapi.testclient import TestClient

from app import catalog, db
from app.dialog import answer, build_draft, validate_for_save
from app.importer import read_table, to_parties
from app.main import app
from app.parser import is_confirm, parse_date, today

client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_samples():
    yield
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())
    db.replace_parties([dict(p, aliases=list(p["aliases"])) for p in catalog.SAMPLE_PARTIES])
    catalog.replace_parties(db.list_parties())


def parse(text, **kw):
    return client.post("/api/parse", json={"text": text, **kw}).json()


def ans(d, text):
    r = client.post("/api/answer", json={"draft": d, "text": text}).json()
    return r["draft"], r["action"]


# 1 ---------------------------------------------------------------- "pakka nahi"
@pytest.mark.parametrize("text", ["abhi pakka nahi, ruko", "save mat karo", "done nahi hua", "ye sahi hai kya",
                                  "pakka nahi hai", "abhi confirm mat karna"])
def test_negated_confirm_is_not_confirm(text):
    assert not is_confirm(text)


@pytest.mark.parametrize("text", ["haan pakka", "pakka", "haan sahi hai", "theek hai save karo", "confirm", "हां पक्का"])
def test_real_confirm_still_confirms(text):
    assert is_confirm(text)


def test_pakka_nahi_never_saves():
    d = parse("ABC wale ko 10 carton Lux kal")
    _, action = ans(d, "abhi pakka nahi, ruko")
    assert action != "confirm"


# 2 ---------------------------------------------------------------- double save
def test_same_draft_saves_once():
    d = parse("Bittu ko 3 carton Lux kal")
    a = client.post("/api/orders", json={"draft": d}).json()
    b = client.post("/api/orders", json={"draft": d}).json()
    assert a["id"] == b["id"]


# 3 ---------------------------------------------------------------- "rehne do"
def test_rehne_do_changes_nothing():
    d = parse("Gupta ko 3 bori cheeni kal")
    d, _ = ans(d, "nahi, rehne do")
    assert d["lines"][0]["qty"] == 3


def test_nahi_do_carton_still_sets_two():
    d = parse("Gupta ko 3 carton Lux kal")
    d, _ = ans(d, "nahi, do carton")
    assert d["lines"][0]["qty"] == 2


# 4 ---------------------------------------------------------------- units the app did not know
def test_dozen_is_kept_not_turned_into_carton():
    ln = parse("ABC ko 2 dozen lux kal")["lines"][0]
    assert ln["qty"] == 2 and ln["unit"] == "dozen"


# 5 ---------------------------------------------------------------- two days said
@pytest.mark.parametrize("text,days", [("aaj order de raha hun kal bhejna", 1), ("kal ka order, aaj bhejna", 0),
                                       ("kal nahi parso", 2), ("parso nahi kal chahiye", 1), ("kal", 1)])
def test_date_said_last_wins(text, days):
    from datetime import timedelta
    assert parse_date(text)["date"] == (today() + timedelta(days=days)).isoformat()


# 6 ---------------------------------------------------------------- two parties in one call
def test_two_parties_ask_which_one():
    d = parse("ABC ko 10 carton Lux kal, Gupta ko 5 bori cheeni")
    assert d["party"]["status"] == "choose"
    assert {o["name"] for o in d["party"]["options"]} == {"ABC Traders", "Gupta Kirana"}
    assert "do party" in d["say"].lower()


# 7 ---------------------------------------------------------------- dispatch, party has 2 open orders
def test_dispatch_party_with_two_open_orders_asks():
    a = client.post("/api/orders", json={"draft": parse("Jain ko 5 bori cheeni kal")}).json()
    b = client.post("/api/orders", json={"draft": parse("Jain ko 2 bori chawal kal")}).json()
    r = client.post("/api/dispatch/parse", json={"text": "Jain ka maal gaya truck se"}).json()
    assert r["ok"] is False and str(a["id"]) in r["say"] and str(b["id"]) in r["say"]
    for o in (a, b):  # send them, so other tests see no extra open Jain orders
        client.post(f"/api/orders/{o['id']}/dispatch", json={"mode": "truck"})


# 9 ---------------------------------------------------------------- only 50 orders listed
def test_order_list_keeps_every_pending_order():
    ids = [client.post("/api/orders", json={"draft": parse(f"New Punjab ko {n} carton Lux kal")}).json()["id"]
           for n in range(1, 56)]
    listed = {o["id"] for o in client.get("/api/orders").json()}
    assert set(ids) <= listed
    for i in ids:
        client.post(f"/api/orders/{i}/dispatch", json={"mode": "truck"})


# 10 --------------------------------------------------------------- item without a quantity
def test_item_without_quantity_asks_how_much():
    d = parse("ABC ko lux bhejna kal")
    assert d["notice"] is None and len(d["lines"]) == 1
    assert d["lines"][0]["qty"] is None and "kitna" in d["question"]["text"].lower()


# 11 --------------------------------------------------------------- the browser's draft is not trusted
def test_save_takes_names_from_the_lists_not_the_browser():
    d = parse("ABC ko 10 carton Lux kal")
    bad = copy.deepcopy(d)
    bad["party"]["party"]["name"] = "<img src=x onerror=alert(1)>"
    bad["lines"][0]["item"]["name"] = "FAKE ITEM"
    o = client.post("/api/orders", json={"draft": bad}).json()
    assert o["party"] == "ABC Traders" and o["lines"][0]["name"] == "Lux Soap"


@pytest.mark.parametrize("field,value", [("unit", "<b>tonnes</b>"), ("date", "not-a-date"), ("date", "2099-01-01")])
def test_save_refuses_bad_unit_or_date(field, value):
    d = copy.deepcopy(parse("ABC ko 10 carton Lux kal"))
    if field == "unit":
        d["lines"][0]["unit"] = value
    else:
        d["delivery"]["date"] = value
    assert client.post("/api/orders", json={"draft": d}).status_code == 400


def test_unknown_party_code_refused():
    d = copy.deepcopy(parse("ABC ko 10 carton Lux kal"))
    d["party"]["party"]["code"] = "NOPE"
    assert client.post("/api/orders", json={"draft": d}).status_code == 400


# 12 --------------------------------------------------------------- shop PIN
def test_shop_pin_locks_the_api(monkeypatch):
    monkeypatch.setenv("BKO_PIN", "4321")
    c = TestClient(app)
    assert c.get("/api/orders").status_code == 401
    assert c.get("/healthz").status_code == 200 and c.get("/").status_code == 200
    assert c.post("/api/login", json={"pin": "0000"}).status_code == 401
    assert c.post("/api/login", json={"pin": "4321"}).status_code == 200
    assert c.get("/api/orders").status_code == 200  # cookie set by login


def test_no_pin_means_open(monkeypatch):
    monkeypatch.delenv("BKO_PIN", raising=False)
    assert TestClient(app).get("/api/orders").status_code == 200


# 14 --------------------------------------------------------------- "10 se 12"
def test_range_with_se_is_one_line_with_two_quantities():
    lines = parse("ABC ko 10 se 12 carton lux kal")["lines"]
    assert len(lines) == 1 and lines[0]["qty_alts"] == [10, 12]


# 15 --------------------------------------------------------------- party name starting with "aur"
def test_party_starting_with_aur_is_found():
    client.post("/api/parties/import?commit=1", files={"file": ("p.csv", b"Name\nAurora Traders\n", "text/csv")})
    d = parse("Aurora Traders ko 5 carton lux kal")
    assert d["party"]["status"] == "ok" and d["party"]["party"]["name"] == "Aurora Traders"
    assert d["lines"][0]["qty"] == 5


# 16 --------------------------------------------------------------- re-dispatch, undo "Galat nikla"
def test_dispatch_twice_refused_and_mode_checked():
    o = client.post("/api/orders", json={"draft": parse("Bittu ko 1 carton Lux kal")}).json()
    assert client.post(f"/api/orders/{o['id']}/dispatch", json={"mode": "spaceship"}).status_code == 400
    assert client.post(f"/api/orders/{o['id']}/dispatch", json={"mode": "truck"}).status_code == 200
    assert client.post(f"/api/orders/{o['id']}/dispatch", json={"mode": "tempo"}).status_code == 409


def test_galat_nikla_can_be_undone():
    o = client.post("/api/orders", json={"draft": parse("Bittu ko 2 carton Lux kal")}).json()
    client.post(f"/api/orders/{o['id']}/wrong", json={"reason": "qty"})
    assert client.delete(f"/api/orders/{o['id']}/wrong").json()["wrong_reason"] is None


# 17 --------------------------------------------------------------- huge quantity
def test_huge_quantity_is_asked_and_never_saved():
    d = parse("ABC ko 100000 carton lux kal")
    assert d["ready"] is False and d["question"]["type"] == "qty"
    assert validate_for_save(build_draft("ABC ko 100000 carton lux kal"))


# 18 --------------------------------------------------------------- same spoken name on two items
def test_spoken_name_already_used_by_another_item_is_refused():
    r = client.post("/api/items", json={"code": "ZZ1", "name": "Lux Mini", "unit": "carton", "aliases": ["lux"]})
    assert r.status_code == 409 and "Lux Soap" in r.json()["detail"]


# 19 --------------------------------------------------------------- smaller ones
def test_answer_after_item_list_changed_does_not_crash():
    d = parse("ABC ko 10 carton sabun kal")  # asks which soap
    client.post("/api/items/import?commit=1", files={"file": ("i.csv", b"name\nParle G\n", "text/csv")})
    r = client.post("/api/answer", json={"draft": d, "text": "pehla"})
    assert r.status_code == 200


def test_grouped_busy_export_skips_headings_and_bank_rows():
    parties, _ = to_parties(read_table("g.csv", b"Name\nSundry Debtors\nRam Store\nShyam Kirana\nBank Accounts\nHDFC Bank\n"))
    assert [p["name"] for p in parties] == ["Ram Store", "Shyam Kirana"]


def test_duplicate_header_first_column_wins():
    rows = read_table("d.csv", b"Name,Unit,Name\nLux Soap,Box,\n")
    assert rows[0]["name"] == "Lux Soap"


def test_every_answer_turn_is_counted():
    d = parse("ABC wale ko 10 carton Lux kal")
    d, _ = ans(d, "aur 5 bori cheeni")
    assert d["stats"]["questions"] == 1


def test_going_back_keeps_the_clock_and_counts():
    d = parse("ABC wale ko 10 carton sabun kal")
    d, _ = ans(d, "Lux")
    again = parse("ABC wale ko 10 carton Lux kal", carry=d["stats"])
    assert again["stats"]["started_at"] == d["stats"]["started_at"] and again["stats"]["questions"] == 1
