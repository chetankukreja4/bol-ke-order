"""Improvements after the pilot build: edit or cancel a saved order, today's Busy CSV,
keyterms from what the shop really orders, and a demo reset."""
import csv
import io
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import catalog, db, stt
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def send_leftover_orders():
    """Orders a test leaves open would confuse the dispatch tests that share this database."""
    before = max([o["id"] for o in db.list_orders(1)] or [0])
    yield
    for o in db.list_orders_for_ui():
        if o["id"] > before and o["status"] == "confirmed":
            db.mark_dispatched(o["id"], "truck")
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())


def parse(text):
    return client.post("/api/parse", json={"text": text}).json()


def save(text):
    return client.post("/api/orders", json={"draft": parse(text)}).json()


def answer(draft, text):
    return client.post("/api/answer", json={"draft": draft, "text": text}).json()["draft"]


# 1 ---------------------------------------------------------------- cancel a saved order
def test_cancel_a_pending_order():
    o = save("Bittu ko 4 carton Lux kal")
    c = client.post(f"/api/orders/{o['id']}/cancel").json()
    assert c["status"] == "cancelled"
    r = client.post("/api/dispatch/parse", json={"text": f"order {o['id']} truck se"}).json()
    assert r["ok"] is False  # a cancelled order cannot go out
    pilot_ids = [row[0] for row in csv.reader(io.StringIO(client.get("/api/pilot.csv").text))][1:]
    assert str(o["id"]) not in pilot_ids  # and does not count in the pilot numbers


def test_cannot_cancel_a_dispatched_order():
    o = save("Bittu ko 1 carton Lux kal")
    client.post(f"/api/orders/{o['id']}/dispatch", json={"mode": "truck"})
    assert client.post(f"/api/orders/{o['id']}/cancel").status_code == 409


# 1 ---------------------------------------------------------------- edit a saved order
def test_edit_a_saved_order_by_voice():
    o = save("Gupta ko 10 carton Lux kal")
    d = client.get(f"/api/orders/{o['id']}/draft").json()
    assert d["edit_of"] == o["id"] and d["ready"] is True and d["party"]["party"]["code"] == "P04"
    assert [(ln["item"]["code"], ln["qty"]) for ln in d["lines"]] == [("SP01", 10)]
    d = answer(d, "nahi, aath carton")
    d = answer(d, "aur 2 bori cheeni")
    saved = client.post("/api/orders", json={"draft": d}).json()
    assert saved["id"] == o["id"] and saved["edited_at"]
    assert [(ln["code"], ln["qty"]) for ln in saved["lines"]] == [("SP01", 8), ("SG01", 2)]
    assert len([x for x in client.get("/api/orders").json() if x["id"] == o["id"]]) == 1


def test_cannot_edit_a_dispatched_order():
    o = save("Gupta ko 3 carton Lux kal")
    client.post(f"/api/orders/{o['id']}/dispatch", json={"mode": "tempo"})
    assert client.get(f"/api/orders/{o['id']}/draft").status_code == 409


# 7 ---------------------------------------------------------------- today's Busy CSV, no limit
def test_todays_busy_csv_has_every_order_of_the_day_except_cancelled():
    a = save("Jain ko 2 carton Lux kal")
    b = save("Jain ko 3 bori cheeni kal")
    client.post(f"/api/orders/{b['id']}/cancel")
    rows = list(csv.reader(io.StringIO(client.get("/api/orders.csv?day=today").text)))
    ids = {r[0] for r in rows[1:]}
    assert rows[0][0] == "order_id" and str(a["id"]) in ids and str(b["id"]) not in ids


# 8 ---------------------------------------------------------------- keyterms follow real orders
def test_keyterms_put_the_most_ordered_items_first():
    for _ in range(3):
        save("Bittu ko 2 carton Tata salt kal")
    top = db.top_item_codes()
    assert top[0] in catalog.ITEMS_BY_CODE
    terms = stt._keyterms()
    first_item = next(t for t in terms if t not in {p["name"] for p in catalog.PARTIES})
    assert first_item == catalog.ITEMS_BY_CODE[top[0]]["name"]


# 9 ---------------------------------------------------------------- demo reset
def test_demo_reset_is_off_unless_enabled(monkeypatch):
    monkeypatch.delenv("BKO_DEMO", raising=False)
    assert client.post("/api/demo/reset", json={"confirm": "RESET"}).status_code == 403
    assert client.get("/api/config").json()["demo"] is False


def test_demo_reset_clears_orders_and_restores_samples(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "demo.db"))  # never touch the shared test database
    monkeypatch.setenv("BKO_DEMO", "1")
    save("Bittu ko 4 carton Lux kal")
    client.post("/api/items/import?commit=1", files={"file": ("i.csv", b"name\nParle G\n", "text/csv")})
    assert client.post("/api/demo/reset", json={"confirm": "nahi"}).status_code == 400
    assert client.post("/api/demo/reset", json={"confirm": "RESET"}).status_code == 200
    assert client.get("/api/orders").json() == []
    assert {i["code"] for i in client.get("/api/items").json()} == {i["code"] for i in catalog.SAMPLE_ITEMS}
    assert parse("ABC ko 10 carton Lux kal")["lines"][0]["item"]["code"] == "SP01"
