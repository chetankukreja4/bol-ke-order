"""Fixes from the 28 Nov pre-submission review: Hindi fractions and hazaar,
Hindi-script units and परसों, number words 31-99, "3 tarikh" dates, and
"10 nahi 12" said inside the order."""
import os
import tempfile
from datetime import timedelta

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest

from app import catalog
from app.dialog import answer, build_draft
from app.parser import parse_date, quantities_in, today
from app.textnorm import numbers_in


@pytest.fixture(autouse=True)
def sample_lists():
    catalog.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_parties([dict(p, aliases=list(p["aliases"])) for p in catalog.SAMPLE_PARTIES])


def _lines(d):
    return [(ln["item"]["code"] if ln["item"] else None, ln["qty"], ln["unit"]) for ln in d["lines"]]


@pytest.mark.parametrize("said,value", [
    ("saadhe teen sau", 350), ("sava sau", 125), ("sawa do sau", 225), ("paune do sau", 175),
    ("dedh sau", 150), ("dhai sau", 250), ("saadhe paanch", 5.5), ("do hazaar", 2000),
    ("dedh hazaar", 1500), ("do hazaar paanch sau", 2500), ("ek sau bees", 120),
    ("साढ़े तीन सौ", 350), ("डेढ़ सौ", 150), ("सवा सौ", 125), ("दो हज़ार", 2000),
])
def test_fractions_and_hazaar(said, value):
    assert quantities_in(said) == [value]


@pytest.mark.parametrize("said,value", [
    ("pachpan", 55), ("bayalis", 42), ("athattar", 78), ("chhappan", 56), ("iktees", 31),
    ("ninyanve", 99), ("पचपन", 55), ("अठहत्तर", 78), ("चौंसठ", 64), ("निन्यानवे", 99),
])
def test_number_words_31_to_99(said, value):
    assert numbers_in(said) == [value]


def test_saath_is_still_with_not_sixty():
    assert numbers_in("ABC ke saath") == []


def test_sizes_still_work():
    d = build_draft("ABC ko 5 carton lux kal")
    assert d["ready"]
    assert quantities_in("sawa inch") == []  # a size, not 1.25 of something


@pytest.mark.parametrize("said,line", [
    ("एबीसी को साढ़े तीन सौ पैकेट मैगी कल", ("MG01", 350, "packet")),
    ("बिट्टू को 3 लीटर तेल कल", ("OL01", 3, "litre")),
    ("ABC ko dedh hazaar packet maggi kal", ("MG01", 1500, "packet")),
    ("ABC ko sava sau packet maggi kal", ("MG01", 125, "packet")),
])
def test_quantity_and_unit_in_a_whole_order(said, line):
    d = build_draft(said)
    assert _lines(d) == [line]


def test_hindi_piece_unit():
    d = build_draft("एबीसी को 12 पीस कोलगेट कल")
    assert d["lines"][0]["unit"] == "piece" and d["lines"][0]["qty"] == 12


def test_parso_in_hindi_script():
    d = build_draft("गुप्ता जी को पच्चीस बोरी चीनी परसों")
    assert d["delivery"]["date"] == (today() + timedelta(days=2)).isoformat()
    assert d["ready"]


def test_day_of_month_is_a_date_not_a_line():
    d = build_draft("ABC ko 5 carton lux 3 tarikh ko")
    assert _lines(d) == [("SP01", 5, "carton")]
    when = parse_date("3 tarikh")["date"]
    assert when >= today().isoformat() and when.endswith("-03")
    d = build_draft("एबीसी को 5 कार्टन लक्स 15 तारीख को")
    assert _lines(d) == [("SP01", 5, "carton")] and d["delivery"]["date"].endswith("-15")
    d = build_draft("ABC ko 5 carton lux 3 december")
    assert _lines(d) == [("SP01", 5, "carton")] and d["delivery"]["date"].endswith("-12-03")
    assert parse_date("31 tarikh")["date"].endswith("-31")  # in a 30-day month: the next one with a 31st


def test_day_of_month_as_an_answer():
    d = build_draft("ABC ko 5 carton lux")
    d, action = answer(d, "5 tarikh")
    assert action == "updated" and d["delivery"]["date"].endswith("-05") and d["ready"]


@pytest.mark.parametrize("said", [
    "ABC ko 10 carton lux kal, 10 nahi 12",
    "ABC ko 10 carton lux, nahi 12 carton, kal",
    "ABC ko 10 nahi 12 carton lux kal",
    "ABC ko das nahi barah carton lux kal",
])
def test_correction_inside_the_order(said):
    d = build_draft(said)
    assert _lines(d) == [("SP01", 12, "carton")]


def test_else_quantity_still_asks():
    d = build_draft("agar rate sahi hai toh 10 carton lux, nahi toh 5 carton, kal ABC")
    assert d["lines"][0]["qty_alts"] == [10, 5]


def test_no_empty_question_when_nothing_to_suggest():
    d = build_draft("ABC ko 10 carton kal")
    assert d["question"]["text"] == "10 carton kya? Item ka naam bolein."
    assert "matlab ?" not in d["say"]
