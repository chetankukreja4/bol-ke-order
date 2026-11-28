"""Hinglish as staff and speech-to-text really say it: Roman, Hindi script with English
words (the browser's hi-IN), mixed script, Haryanvi / Punjabi words, mixed numbers,
corrections inside the order and in answers. From the 28 Nov Hinglish check."""
import copy
import os
import tempfile
from datetime import timedelta

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest

from app import catalog
from app.dialog import answer, build_draft
from app.parser import parse_date, today
from app.textnorm import norm


@pytest.fixture(autouse=True)
def sample_lists():
    catalog.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_parties([dict(p, aliases=list(p["aliases"])) for p in catalog.SAMPLE_PARTIES])


def day(n):
    return (today() + timedelta(days=n)).isoformat()


def got(d):
    party = d["party"]["party"]["code"] if d["party"]["status"] == "ok" else None
    lines = [(ln["item"]["code"] if ln["match"] == "ok" else None, ln["qty"], ln["unit"]) for ln in d["lines"]]
    return party, lines, (d["delivery"] or {}).get("date")


ORDERS = [
    # Roman Hinglish (Sarvam translit)
    ("Jain sahab ka order likho, 3 carton Colgate, 4 carton Parle G, day after tomorrow",
     "P07", [("TP01", 3, "carton"), ("BS01", 4, "carton")], 2),
    ("Gupta ji ko ek dozen Colgate aur half dozen Dettol kal", "P04", [("TP01", 1, "dozen"), ("SP03", 0.5, "dozen")], 1),
    ("Gupta ji, kal ke liye 5 carton Surf Excel aur 2 bori sugar", "P04", [("DT01", 5, "carton"), ("SG01", 2, "bag")], 1),
    ("ABC, 10 ctn lux, 5 pkt maggi, kal", "P01", [("SP01", 10, "carton"), ("MG01", 5, "packet")], 1),
    # numbers across languages
    ("ABC ko twenty paanch carton Lux kal", "P01", [("SP01", 25, "carton")], 1),
    ("ABC ko twenty teen packet maggi aaj", "P01", [("MG01", 23, "packet")], 0),
    ("ABC ko paanch-chhe carton Lux kal", "P01", [("SP01", None, "carton")], 1),
    ("ABC ko dus bara carton Lux kal", "P01", [("SP01", None, "carton")], 1),
    ("Bittu ko teen chaar carton Lux kal", "P05", [("SP01", None, "carton")], 1),
    ("Bittu ko do teen carton Lux kal", "P05", [("SP01", None, "carton")], 1),
    # corrections inside the order
    ("ABC ko 10 carton Lux kal, sorry 12 carton", "P01", [("SP01", 12, "carton")], 1),
    ("ABC ko 10 carton Lux kal, nahi nahi 12", "P01", [("SP01", 12, "carton")], 1),
    ("ABC ko 10 carton Lux, no wait, 12 carton, kal", "P01", [("SP01", 12, "carton")], 1),
    ("ABC ko 10 carton Lux kal, Lux nahi Dettol", "P01", [("SP03", 10, "carton")], 1),
    ("Gupta ji 20 carton parle-g, 10 nahi nahi 15 carton maggi, kal", "P04",
     [("BS01", 20, "carton"), ("MG01", 15, "carton")], 1),
    # dates
    ("ABC ko 10 carton Lux kal nahi parso", "P01", [("SP01", 10, "carton")], 2),
    # Haryanvi / Punjabi
    ("Gupta ji nu das peti Lux te panj bori cheeni kal", "P04", [("SP01", 10, "carton"), ("SG01", 5, "bag")], 1),
    ("Punjab wale nu chhe peti Tide te do bori atta kal", "P06", [("DT02", 6, "carton"), ("AT01", 2, "bag")], 1),
    ("ABC aali dukaan pe 10 carton Lux bhej diyo kal", "P01", [("SP01", 10, "carton")], 1),
    # Hindi script with English words (browser hi-IN)
    ("बिट्टू को ट्वेंटी फाइव पैकेट मैगी कल", "P05", [("MG01", 25, "packet")], 1),
    ("जैन ब्रदर्स को 3 कार्टन कोलगेट टूथपेस्ट टुमारो", "P07", [("TP01", 3, "carton")], 1),
    ("एबीसी को 10 कार्टन फॉर्च्यून ऑयल कल", "P01", [("OL01", 10, "carton")], 1),
    ("एबीसी को 4 कार्टन टाटा टी कल", "P01", [("TE01", 4, "carton")], 1),
    ("शर्मा ट्रेडर्स को 4 कार्टन लक्स कल", "P02", [("SP01", 4, "carton")], 1),
    ("न्यू पंजाब स्टोर्स को 4 कार्टन लक्स कल", "P06", [("SP01", 4, "carton")], 1),
    ("एबीसी को 10 कार्टन लक्स कल, नहीं नहीं 12", "P01", [("SP01", 12, "carton")], 1),
    ("एबीसी को 5 कार्टन सरसों का तेल परसों", "P01", [("OL02", 5, "carton")], 2),
    ("गुप्ता जी को पचपन कार्टन मैगी टुडे", "P04", [("MG01", 55, "carton")], 0),
    ("बिट्टू भाई को फिफ्टी पैकेट मैगी कल", "P05", [("MG01", 50, "packet")], 1),
    ("एबीसी को दस बारह कार्टन लक्स कल", "P01", [("SP01", None, "carton")], 1),
    # mixed script
    ("Gupta जी को 5 बोरी sugar और 3 carton Maggi परसों", "P04", [("SG01", 5, "bag"), ("MG01", 3, "carton")], 2),
    ("Bittu Store को twenty five पैकेट Maggi tomorrow", "P05", [("MG01", 25, "packet")], 1),
]


@pytest.mark.parametrize("said,party,lines,days", ORDERS)
def test_hinglish_orders(said, party, lines, days):
    assert got(build_draft(said)) == (party, lines, day(days))


def test_ordinal_dates():
    assert parse_date("5th ko")["date"].endswith("-05")
    assert parse_date("22nd tak")["date"].endswith("-22")
    d = build_draft("ABC ko 4 carton Lux 12th ko")
    assert got(d)[1] == [("SP01", 4, "carton")] and d["delivery"]["date"].endswith("-12")


def test_day_kept_when_nahi_is_about_the_quantity():
    assert parse_date("kal, nahi nahi 12")["date"] == day(1)
    assert parse_date("kal nahi") is None
    assert parse_date("day after tomorrow")["date"] == day(2)


def test_schwa_in_hindi_script():
    assert norm("कोलगेट") == "colgate"
    assert norm("सरसों") == "sarson" and norm("परसों") == "parson" and norm("समझा") == "samjha"
    assert norm("कार्टन") == "carton" and norm("चावल") == "chaval"


BRAND_Q = "ABC ko 10 carton sabun kal"


@pytest.mark.parametrize("said,code,qty", [
    ("Lux de do", "SP01", 10),        # "do" is the verb, not 2 or "the second one"
    ("second one", "SP02", 10),       # which one, not 1 carton
    ("doosra", "SP02", 10),
    ("Lux, 12 carton", "SP01", 12),
    ("do", "SP02", 10),               # a short answer: the second option
])
def test_brand_answers(said, code, qty):
    d, _ = answer(build_draft(BRAND_Q), said)
    assert (d["lines"][0]["item"]["code"], d["lines"][0]["qty"]) == (code, qty)


TWO = "ABC ko 10 carton Lux aur 5 carton Surf kal"


@pytest.mark.parametrize("said,lines", [
    ("Surf 8 kar do", [("SP01", 10), ("DT01", 8)]),
    ("Lux 12 karo", [("SP01", 12), ("DT01", 5)]),
    ("sorry, 12 carton Lux", [("SP01", 12), ("DT01", 5)]),
    ("Surf hata do", [("SP01", 10)]),
    ("Surf nahi chahiye", [("SP01", 10)]),
    ("Lux ki jagah Dettol", [("SP03", 10), ("DT01", 5)]),
    ("Dettol instead of Lux", [("SP03", 10), ("DT01", 5)]),
    ("aur 2 bori cheeni add karo", [("SP01", 10), ("DT01", 5), ("SG01", 2)]),
    ("5 carton Lux aur", [("SP01", 10), ("DT01", 5), ("SP01", 5)]),
])
def test_hinglish_edits_in_answers(said, lines):
    d, action = answer(build_draft(TWO), said)
    assert action == "updated"
    assert [(ln["item"]["code"], ln["qty"]) for ln in d["lines"]] == lines


def test_confirm_still_needs_pakka():
    base = build_draft("ABC ko 10 carton Lux kal")
    for said in ("haan", "ok", "yes"):
        assert answer(copy.deepcopy(base), said)[1] != "confirm"
    for said in ("haan ji pakka", "yes pakka", "हां जी पक्का"):
        assert answer(copy.deepcopy(base), said)[1] == "confirm"
