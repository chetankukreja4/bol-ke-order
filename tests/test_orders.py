"""Success means every quantity is correct before saving."""
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("SARVAM_API_KEY", None)

import pytest
from fastapi.testclient import TestClient

from app.dialog import answer, build_draft, validate_for_save
from app.main import app
from app.parser import parse_dispatch
from app.samples import TEST_PHRASES
from app.textnorm import deva_to_roman, numbers_in

client = TestClient(app)


@pytest.mark.parametrize("words,value", [
    ("das", 10), ("dus", 10), ("ten", 10), ("10", 10), ("pachees", 25), ("pachchis", 25),
    ("25", 25), ("twenty five", 25), ("aath", 8), ("do sau", 200), ("dedh", 1.5), ("दस", 10), ("१२", 12),
])
def test_spoken_numbers(words, value):
    assert numbers_in(words) == [value]


def test_devanagari_to_roman():
    assert deva_to_roman("कल") == "kal"
    assert deva_to_roman("चीनी") == "cheenee"


@pytest.mark.parametrize("sample", TEST_PHRASES, ids=[s["text"][:30] for s in TEST_PHRASES])
def test_ten_phrases(sample):
    d = build_draft(sample["text"])
    got = [(l["item"]["code"] if l["item"] else "?" + (l["group"] or l["match"]), l["qty"]) for l in d["lines"]]
    party = d["party"]["party"]["code"] if d["party"]["party"] else "?"
    assert party == sample["expect"]["party"]
    assert got == sample["expect"]["lines"]
    if "ask" in sample["expect"]:
        assert d["question"]["text"] == sample["expect"]["ask"]


def test_small_talk_and_bargaining_ignored():
    d = build_draft("Namaste ji, rate 20 rupay kam karo, 5 percent discount. Gupta ji 3 bori atta kal")
    assert [(l["item"]["code"], l["qty"]) for l in d["lines"]] == [("AT01", 3)]


def test_two_quantities_asks():
    d = build_draft("ABC ko 10 ya 12 carton lux kal")
    assert d["question"]["type"] == "qty" and not d["ready"]
    d, _ = answer(d, "barah")
    assert d["lines"][0]["qty"] == 12 and d["ready"]


def test_unknown_item_never_guessed():
    d = build_draft("ABC ko 4 carton xylo kal")
    ln = d["lines"][0]
    assert ln["item"] is None and len(ln["options"]) == 3 and ln["uncertain"]
    assert d["question"]["text"].startswith("Pakka nahi hoon")


def test_similar_party_names_ask():
    d = build_draft("Sharma ji ko 5 carton lux kal")
    assert d["question"]["type"] == "party"
    d, _ = answer(d, "general store")
    assert d["party"]["party"]["code"] == "P03"


def test_correction_changes_only_that_line():
    d = build_draft("ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena")
    d, _ = answer(d, "Lux")
    d, _ = answer(d, "nahi, aath carton")
    assert [(l["item"]["code"], l["qty"]) for l in d["lines"]] == [("SP01", 8), ("OL01", 5)]
    d, _ = answer(d, "nahi, tel 6 carton")
    assert [(l["item"]["code"], l["qty"]) for l in d["lines"]] == [("SP01", 8), ("OL01", 6)]


def test_nothing_saved_until_confirm():
    d = build_draft("ABC wale ko 10 carton sabun, 5 carton tel, kal")
    assert validate_for_save(d) is not None
    r = client.post("/api/orders", json={"draft": d})
    assert r.status_code == 400
    d, action = answer(d, "haan pakka")
    assert action == "repeat"  # still a question open
    d, _ = answer(d, "dettol")
    d, action = answer(d, "haan, pakka")
    assert action == "confirm" and validate_for_save(d) is None


def test_full_api_flow_and_dispatch():
    cfg = client.get("/api/config").json()
    assert cfg["server_stt"] is False and cfg["llm"] is False
    d = client.post("/api/parse", json={"text": "Gupta ji ko das peti Lux aur pachees bori cheeni parso"}).json()
    assert d["ready"]
    r = client.post("/api/answer", json={"draft": d, "text": "haan pakka"}).json()
    assert r["action"] == "confirm"
    order = client.post("/api/orders", json={"draft": r["draft"]}).json()
    assert [(l["code"], l["qty"]) for l in order["lines"]] == [("SP01", 10), ("SG01", 25)]
    csv_text = client.get(f"/api/orders/{order['id']}/csv").text
    assert "SP01" in csv_text and "25" in csv_text
    disp = client.post("/api/dispatch/parse", json={"text": "Gupta ka maal gaya, rickshaw se"}).json()
    assert disp["ok"] and disp["mode"] == "rickshaw" and disp["order"]["id"] == order["id"]
    done = client.post(f"/api/orders/{order['id']}/dispatch", json={"mode": "rickshaw"}).json()
    assert done["status"] == "dispatched" and done["dispatch_date"]


def test_upload_without_key_says_key_not_set():
    r = client.post("/api/transcribe", files={"file": ("a.mp3", b"123", "audio/mpeg")})
    assert r.status_code == 503 and r.json()["error"] == "key_not_set"


def test_dispatch_parse_modes():
    assert parse_dispatch("ABC ka maal gaya, rickshaw se")["mode"] == "rickshaw"
    assert parse_dispatch("Bittu ka saman tempo se bhej diya")["mode"] == "tempo"
