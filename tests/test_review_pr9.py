"""Fixes from the code review of the pipe/real-call change (PR #9)."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.dialog import build_draft
from app.main import app
from app.matcher import choose_from, match_item
from app.parser import extract_rules, parse_date
from app.textnorm import norm

client = TestClient(app)


def _item(code, name):
    return {"code": code, "name": name, "unit": "piece", "group": None, "aliases": [name.lower()]}


@pytest.fixture
def two_brands():
    catalog.replace_items([_item("A1", 'Astral Elbow 1"'), _item("A2", 'Astral Elbow 2"'), _item("A3", 'Astral Tee 1"'),
                           _item("A4", 'Astral Socket 1"'), _item("P1", 'Prince Elbow 1"'), _item("X1", "Pass Pass Pulse"),
                           _item("X2", "Cricket Bat Kashmir")])
    yield
    catalog.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])


def test_small_brand_is_not_lost_when_brand_is_dropped(two_brands):
    m = match_item("elbow 1 inch")  # Astral or Prince? ask
    assert m["status"] != "ok"
    assert {o["name"] for o in m["options"][:2]} == {'Astral Elbow 1"', 'Prince Elbow 1"'}
    assert match_item("prince elbow 1 inch")["item"]["name"] == 'Prince Elbow 1"'


@pytest.mark.parametrize("answer", ["1 inch wala", "ek inch", "ek inch wala dena"])
def test_size_answer_picks_the_option(two_brands, answer):
    opts = [{"code": "A1", "name": 'Astral Elbow 1"'}, {"code": "A2", "name": 'Astral Elbow 2"'}]
    assert choose_from(answer, opts)["code"] == "A1"


def test_item_words_are_not_filler(two_brands):
    lines = extract_rules("ABC ko 10 pass pass pulse, 2 cricket bat kashmir")["lines"]
    assert [ln["item_text"] for ln in lines] == ["pas pas pulse", "cricket bat kashmir"]


LONG_ORDER = ("ABC ko 10 carton lux 5 carton lifebuoy 3 carton dettol 2 bag sugar 4 bag atta 6 carton maggi "
              "2 carton colgate 1 carton tata tea 5 carton tata salt aur uske baad 20 bori bhi bhej dena "
              "aur 5 packet matchbox bhi kal subah tak pakka bhej dena bhai")


def test_long_spoken_order_keeps_every_line():
    assert len(LONG_ORDER.split()) > 40
    assert [20] in [ln["qty_values"] for ln in extract_rules(LONG_ORDER)["lines"]]  # asked, not dropped
    r = client.post("/api/parse", json={"text": LONG_ORDER, "source": "mic"}).json()
    assert 20 in [ln["qty"] for ln in r["lines"]]


def test_long_call_recording_still_drops_talk():
    r = client.post("/api/parse", json={"text": LONG_ORDER + " " + "chhah bundle ka ek rickshaw hota hai " * 3,
                                        "source": "upload"}).json()
    assert not any("rickshaw" in ln["heard"] for ln in r["lines"])


@pytest.mark.parametrize("text", ['ABC ko lux "10" carton', "ABC ko lux '10' carton", "ABC ko lux “10” carton"])
def test_quoted_quantity_is_not_inches(text):
    lines = build_draft(text)["lines"]
    assert lines and lines[0]["qty"] == 10 and lines[0]["item"]["name"] == "Lux Soap"


def test_unsure_line_with_money_word_stays():
    lines = build_draft("ABC ko 10 carton lufbuoy kam se kam, payment kal karunga")["lines"]
    assert lines and lines[0]["qty"] == 10


@pytest.mark.parametrize("text,qty,unit", [("ABC ko sugar das kilo wala", 10, "kg"), ("ABC ko 5 kilo ka lux", 5, "kg")])
def test_kilo_is_a_quantity_without_another_number(text, qty, unit):
    ln = build_draft(text)["lines"][0]
    assert (ln["qty"], ln["unit"]) == (qty, unit)


def test_kilo_class_before_a_quantity():
    assert norm("saadhe das kilo ke aath pipe") == "10.5kg ke ath pipe"


@pytest.mark.parametrize("text,want", [("wire 1.5mm 90m coil", "wire 1.5mm 90m coil"),
                                       ("Astral 40mm Elbow", "astral 40mm elbow"), ("40 mm", "40mm")])
def test_metres_are_not_millimetres(text, want):
    assert norm(text) == want


def test_rupees_before_a_number_is_not_a_quantity():
    lines = build_draft("ABC ko 10 carton lux. rs 250 lagega")["lines"]
    assert [ln["qty"] for ln in lines] == [10]


@pytest.mark.parametrize("text,label", [("maal bhej do abhi", "aaj"), ("abhi yahan rakha hai", None)])
def test_abhi_with_send_word_before(text, label):
    assert (parse_date(text) or {}).get("label") == label
