"""Findings from the code review of the improvements branch. One test each."""
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import catalog, db, main, tts
from app.importer import read_table, to_parties
from app.main import app
from app.parser import IST, today

client = TestClient(app)


@pytest.fixture(autouse=True)
def tidy():
    before = max([o["id"] for o in db.list_orders(1)] or [0])
    yield
    for o in db.list_orders_for_ui():
        if o["id"] > before and o["status"] == "confirmed":
            db.mark_dispatched(o["id"], "truck")
    main.reset_login_limits()


def parse(text):
    return client.post("/api/parse", json={"text": text}).json()


# 2 ---------------------------------------------------------------- offline wait is not order time
def test_offline_wait_is_taken_out_of_the_order_time():
    d = parse("Bittu ko 2 carton Lux kal")
    d["stats"]["started_at"] = (datetime.now(IST) - timedelta(seconds=1000)).isoformat(timespec="seconds")
    d["stats"]["offline_seconds"] = 950  # confirmed 50 s after starting, then waited offline
    o = client.post("/api/orders", json={"draft": d}).json()
    assert 45 <= o["seconds_to_confirm"] <= 56


# 3 ---------------------------------------------------------------- "Wholesale Parties" are customers
def test_debtor_subgroup_with_sale_in_its_name_is_kept():
    parties, skipped = to_parties(read_table("p.csv", b"Name,Group\nRam Kirana,Wholesale Parties\n"
                                                      b"HDFC Bank,Bank Accounts\nGST Payable,Duties & Taxes\n"))
    assert [p["name"] for p in parties] == ["Ram Kirana"] and len(skipped) == 2


# 4 ---------------------------------------------------------------- PIN guessing is slowed down
def test_pin_login_is_limited(monkeypatch):
    monkeypatch.setenv("BKO_PIN", "4321")
    c = TestClient(app)
    codes = [c.post("/api/login", json={"pin": f"{n:04d}"}).status_code for n in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    assert c.post("/api/login", json={"pin": "4321"}).status_code == 429  # even the right PIN waits


# 5 ---------------------------------------------------------------- late orders can be edited
def test_late_pending_order_can_be_edited():
    o = client.post("/api/orders", json={"draft": parse("Gupta ko 10 carton Lux kal")}).json()
    late = (today() - timedelta(days=5)).isoformat()
    con = sqlite3.connect(db.DB_PATH)
    con.execute("UPDATE orders SET delivery_date=? WHERE id=?", (late, o["id"]))
    con.commit(); con.close()
    d = client.get(f"/api/orders/{o['id']}/draft").json()
    d = client.post("/api/answer", json={"draft": d, "text": "nahi, aath carton"}).json()["draft"]
    r = client.post("/api/orders", json={"draft": d})
    assert r.status_code == 200 and r.json()["lines"][0]["qty"] == 8


def test_new_order_with_an_old_date_says_so():
    d = parse("Gupta ko 10 carton Lux kal")
    d["delivery"]["date"] = (today() - timedelta(days=5)).isoformat()
    r = client.post("/api/orders", json={"draft": d})
    assert r.status_code == 400 and "pichhli" in r.json()["detail"].lower()


# 6 ---------------------------------------------------------------- cancelled is not "already sent"
def test_cancelled_order_is_called_cancelled_in_dispatch():
    o = client.post("/api/orders", json={"draft": parse("Jain ko 2 carton Lux kal")}).json()
    client.post(f"/api/orders/{o['id']}/cancel")
    r = client.post("/api/dispatch/parse", json={"text": f"order {o['id']} truck se"}).json()
    assert "cancel" in r["say"].lower() and "ja chuka" not in r["say"]
    r = client.post(f"/api/orders/{o['id']}/dispatch", json={"mode": "truck"})
    assert r.status_code == 409 and "cancel" in r.json()["detail"].lower()


# 7 ---------------------------------------------------------------- names are not turned into Hindi
def test_hinglish_words_inside_names_stay_english():
    old_items, old_parties = list(catalog.CATALOG), list(catalog.PARTIES)
    try:
        catalog.replace_items(old_items + [{"code": "ZZ9", "name": "Sun Flower Oil 1L", "unit": "carton",
                                             "group": None, "aliases": ["sunflower"]}])
        catalog.replace_parties(old_parties + [{"code": "PZ9", "name": "Main Road Stores", "aliases": []}])
        said = tts.to_speech_text("Main Road Stores, 2 carton Sun Flower Oil. Sahi hai?")
        assert said == "Main Road Stores, 2 carton Sun Flower Oil। सही है?"
    finally:
        catalog.replace_items(old_items)
        catalog.replace_parties(old_parties)


# 8 ---------------------------------------------------------------- grouped export with unknown sub-groups
def test_grouped_export_reads_subgroup_headings():
    data = b"Name,Balance\nBank Accounts,\nHDFC Bank,5000\nDelhi Parties,\nRam Store,200\nShyam Kirana,150\n"
    parties, skipped = to_parties(read_table("g.csv", data))
    assert [p["name"] for p in parties] == ["Ram Store", "Shyam Kirana"]
    assert {s["name"] for s in skipped} >= {"Bank Accounts", "HDFC Bank", "Delhi Parties"}


# 10 --------------------------------------------------------------- odd characters never crash the PIN check
def test_non_ascii_pin_and_cookie_do_not_crash(monkeypatch):
    monkeypatch.setenv("BKO_PIN", "4321")
    c = TestClient(app)
    assert c.post("/api/login", json={"pin": "४३२१"}).status_code == 401
    # an HTTP client cannot even send a non-ASCII cookie, so check the compare the middleware uses
    assert main._same("é", main._pin_hash("4321")) is False


# 1 ---------------------------------------------------------------- a stuck order's date can be fixed by voice
def test_date_can_be_changed_by_voice():
    d = parse("Gupta ko 10 carton Lux kal")
    d = client.post("/api/answer", json={"draft": d, "text": "nahi, parso"}).json()["draft"]
    assert d["delivery"]["label"] == "parso" and d["lines"][0]["qty"] == 10
    d["delivery"]["date"] = (today() - timedelta(days=3)).isoformat()  # waited offline, date has passed
    d = client.post("/api/answer", json={"draft": d, "text": "kal"}).json()["draft"]
    assert d["delivery"]["label"] == "kal"
