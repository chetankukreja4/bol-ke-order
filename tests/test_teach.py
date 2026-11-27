"""Teaching the app the shop's words from the order screen.

A yellow line ("Pakka nahi hoon") can be linked to an item by staff ("Kisi item
se jodo"), and the words that were heard become a spoken name of that item, so
the next order with the same words is understood. Or a new item is made first
("Naya item banao") and the line is linked to it. The app never links on its own.
"""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import catalog, db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_samples():
    yield
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())


def parse(text):
    return client.post("/api/parse", json={"text": text}).json()


def teach(draft, line_id, code, learn=True):
    return client.post("/api/teach", json={"draft": draft, "line_id": line_id, "code": code, "learn": learn})


def line_with(draft, words):
    return next(ln for ln in draft["lines"] if ln["item_text"] == words)


def test_link_a_yellow_line_and_learn_the_words():
    d = parse("Gupta ko 5 carton heavy kal")
    ln = line_with(d, "heavy")
    assert ln["match"] != "ok"
    r = teach(d, ln["id"], "SP01").json()
    fixed = line_with(r["draft"], "heavy")
    assert fixed["match"] == "ok" and fixed["item"]["code"] == "SP01" and fixed["qty"] == 5
    assert r["learned"] is True and "heavy" in db.get_item("SP01")["aliases"]
    assert r["draft"]["ready"] is True and r["draft"]["stats"]["questions"] == 1
    again = parse("Gupta ko 3 carton heavy kal")["lines"][0]
    assert again["match"] == "ok" and again["item"]["code"] == "SP01"  # learned for next time


def test_words_of_another_item_are_not_learned_but_the_line_is_linked():
    d = parse("Gupta ko 5 carton lux kal")  # "lux" is Lux Soap's spoken name
    ln = d["lines"][0]
    r = teach(d, ln["id"], "SP02").json()
    assert r["draft"]["lines"][0]["item"]["code"] == "SP02"
    assert r["learned"] is False and "Lux Soap" in r["note"]
    assert "lux" not in db.get_item("SP02")["aliases"]


@pytest.mark.parametrize("words", ["sabun"])
def test_generic_group_word_is_never_learned(words):
    d = parse(f"Gupta ko 5 carton {words} kal")
    ln = line_with(d, words)
    r = teach(d, ln["id"], "SP02").json()
    assert r["draft"]["lines"][0]["item"]["code"] == "SP02" and r["learned"] is False
    assert words not in db.get_item("SP02")["aliases"]


def test_learn_false_only_links():
    d = parse("Gupta ko 5 carton heavy kal")
    ln = line_with(d, "heavy")
    r = teach(d, ln["id"], "SP03", learn=False).json()
    assert r["draft"]["lines"][0]["item"]["code"] == "SP03" and r["learned"] is False
    assert "heavy" not in db.get_item("SP03")["aliases"]


def test_new_item_then_link():
    d = parse("Gupta ko 4 carton inchy heavy kal")
    ln = line_with(d, "inchy heavy")
    made = client.post("/api/items", json={"code": "EL01", "name": "Elbow 1 inch Heavy", "unit": "carton",
                                            "aliases": ["inchy heavy"]})
    assert made.status_code == 201
    r = teach(d, ln["id"], "EL01", learn=False).json()
    assert r["draft"]["lines"][0]["item"]["name"] == "Elbow 1 inch Heavy"
    assert parse("Gupta ko 2 carton inchy heavy kal")["lines"][0]["item"]["code"] == "EL01"


def test_bad_code_or_line_refused():
    d = parse("Gupta ko 5 carton heavy kal")
    ln = line_with(d, "heavy")
    assert teach(d, ln["id"], "NOPE").status_code == 400
    assert teach(d, "no-such-line", "SP01").status_code == 400
