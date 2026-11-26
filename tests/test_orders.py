"""Success means every quantity is correct before saving."""
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"  # tests never use the real keys in .env

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
    assert cfg["server_stt"] is False and "llm" not in cfg
    d = client.post("/api/parse", json={"text": "Gupta ji ko das peti Lux aur pachees bori cheeni parso"}).json()
    assert d["ready"]
    r = client.post("/api/answer", json={"draft": d, "text": "haan pakka"}).json()
    assert r["action"] == "confirm"
    order = client.post("/api/orders", json={"draft": r["draft"]}).json()
    assert [(l["code"], l["qty"]) for l in order["lines"]] == [("SP01", 10), ("SG01", 25)]
    csv_text = client.get(f"/api/orders/{order['id']}/csv").text
    assert "SP01" in csv_text and "25" in csv_text
    disp = client.post("/api/dispatch/parse", json={"text": "Gupta ka maal gaya, rickshaw se"}).json()
    assert disp["ok"] and disp["mode"] == "rickshaw" and disp["orders"][0]["id"] == order["id"]
    done = client.post(f"/api/orders/{order['id']}/dispatch", json={"mode": "rickshaw"}).json()
    assert done["status"] == "dispatched" and done["dispatch_date"]


def test_upload_without_key_says_key_not_set():
    r = client.post("/api/transcribe", files={"file": ("a.mp3", b"123", "audio/mpeg")})
    assert r.status_code == 503 and r.json()["error"] == "key_not_set"


def test_dispatch_parse_modes():
    assert parse_dispatch("ABC ka maal gaya, rickshaw se")["mode"] == "rickshaw"
    assert parse_dispatch("Bittu ka saman tempo se bhej diya")["mode"] == "tempo"


def test_sarvam_request_uses_translit_and_shop_keyterms():
    import json as _json
    from app import stt
    form = stt._form()
    assert form["model"] == "saaras:v4" and form["mode"] == "translit" and form["language_code"] == "hi-IN"
    terms = _json.loads(form["keyterms"])
    assert "Lux Soap" in terms and "ABC Traders" in terms and len(terms) <= 50
    assert all(len(t) <= 64 for t in terms)
    assert stt._form(minimal=True) == {"model": "saaras:v4", "language_code": "hi-IN"}


def test_sarvam_falls_back_to_plain_settings_on_400(tmp_path):
    import asyncio
    import httpx
    from app import stt
    sent = []

    def handler(request):
        body = request.content.decode("latin-1")
        sent.append("keyterms" in body)
        if "keyterms" in body:
            return httpx.Response(400, json={"error": "keyterms not supported"})
        return httpx.Response(200, json={"transcript": "abc ko 10 carton lux"})

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF0000WAVE")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await stt._transcribe_chunk(c, str(wav), "k")

    assert asyncio.run(run()) == "abc ko 10 carton lux"
    assert sent == [True, False]


def test_items_page_add_edit_delete_changes_matching():
    items = client.get("/api/items").json()
    assert len(items) == 20 and items[0]["code"] == "SP01"
    # add a new item: speech now finds it
    r = client.post("/api/items", json={"code": "kw01", "name": "Kurkure Masala", "unit": "carton",
                                        "aliases": ["kurkure", " Kurkure ", "kurkre"]})
    assert r.status_code == 201 and r.json()["code"] == "KW01" and r.json()["aliases"] == ["kurkure", "kurkre"]
    assert client.post("/api/items", json={"code": "KW01", "name": "X", "unit": "carton"}).status_code == 409
    d = client.post("/api/parse", json={"text": "Gupta ji ko 4 carton kurkure kal"}).json()
    assert d["lines"][0]["item"]["code"] == "KW01"
    # edit: rename + new code
    r = client.put("/api/items/KW01", json={"code": "KW02", "name": "Kurkure Masala Munch", "unit": "packet",
                                            "aliases": ["kurkure"]})
    assert r.status_code == 200 and client.get("/api/items").json()[-1]["code"] == "KW02"
    d = client.post("/api/parse", json={"text": "Gupta ji ko 4 kurkure kal"}).json()
    assert d["lines"][0]["item"]["name"] == "Kurkure Masala Munch" and d["lines"][0]["unit"] == "packet"
    # delete: no longer matched
    assert client.delete("/api/items/KW02").status_code == 200
    assert client.delete("/api/items/KW02").status_code == 404
    d = client.post("/api/parse", json={"text": "Gupta ji ko 4 carton kurkure kal"}).json()
    assert d["lines"][0]["item"] is None


def test_items_validation():
    bad = [{"code": "", "name": "A", "unit": "carton"}, {"code": "ABCDEFGHIJKLM", "name": "A", "unit": "carton"},
           {"code": "Z1", "name": " ", "unit": "carton"}, {"code": "Z1", "name": "A", "unit": "tonne"},
           {"code": "Z1", "name": "A", "unit": "carton", "group": "shampoo"}]
    for b in bad:
        assert client.post("/api/items", json=b).status_code == 400, b
    assert client.put("/api/items/NOPE", json={"code": "N1", "name": "A", "unit": "carton"}).status_code == 404


SAMSUNG_TRANSCRIPT = """Call with Gupta Kirana
Speaker 1  00:00
Hello, haan bhai Gupta ji bol rahe hain?
Speaker 2  00:03
Haan ji namaste. Order likh lo. 10 carton Lux sabun bhejna.
Speaker 1  00:09
10 carton Lux, theek hai. Aur?
Speaker 2  00:12
5 bori cheeni aur 3 carton Tata namak. Rate pichli baar wala hi lagana.
Speaker 1  00:20
Haan haan. Kab chahiye?
Speaker 2  00:22
Kal subah tak bhej dena."""


def _lines(d):
    return [(l["qty"], l["unit"], l["item"]["code"] if l["item"] else None) for l in d["lines"]]


def test_pasted_samsung_transcript():
    d = client.post("/api/parse", json={"text": SAMSUNG_TRANSCRIPT, "kind": "transcript"}).json()
    assert d["source"] == "transcript" and d["party"]["party"]["name"] == "Gupta Kirana"
    assert d["delivery"]["label"] == "kal"
    # the shop's repeat "10 carton Lux, theek hai" is not a second line; times and labels are gone
    assert _lines(d) == [(10, "carton", "SP01"), (5, "bag", "SG01"), (3, "carton", "SL01")]
    assert "speaker" not in d["heard"].lower() and "00:" not in d["heard"]
    # detected even without kind
    assert client.post("/api/parse", json={"text": SAMSUNG_TRANSCRIPT}).json()["source"] == "transcript"


def test_pasted_transcript_other_formats():
    from app.transcript import clean_transcript, looks_like_transcript
    inline = "[00:01] Me: haan bolo\n[00:04] Jain Brothers: bhai 8 carton Maggi aur 2 bag atta bhej do\n" \
             "[00:10] Me: 8 carton Maggi, 2 bag atta. Kab?\n[00:13] Jain Brothers: parso"
    c = clean_transcript(inline)
    assert c["names"] == ["Jain Brothers"] and "Me:" not in c["text"] and "00:" not in c["text"]
    d = build_draft(c["text"])
    assert d["party"]["party"]["name"] == "Jain Brothers" and d["delivery"]["label"] == "parso"
    assert _lines(d) == [(8, "carton", "MG01"), (2, "bag", "AT01")]
    ai = "Shopkeeper: Namaste, boliye.\nCustomer (0:05): ABC Traders se bol raha hoon. 6 carton Parle-G aur 4 carton Surf Excel.\n" \
         "Shopkeeper (0:11): 6 Parle-G, 4 Surf. Kal?\nCustomer (0:14): Haan kal."
    d = build_draft(clean_transcript(ai)["text"])
    assert _lines(d) == [(6, "carton", "BS01"), (4, "carton", "DT01")] and d["party"]["party"]["code"] == "P01"
    phone = "+91 98765 43210  10:32 AM\nBittu bhai, 12 packet maachis aur 2 carton ghee.\nYou  10:33 AM\n12 packet maachis, 2 carton ghee."
    c = clean_transcript(phone)
    assert "98765" not in c["text"] and _lines(build_draft(c["text"])) == [(12, "packet", "MC01"), (2, "carton", "GH01")]
    # an ordinary spoken order is not treated as a transcript
    assert not looks_like_transcript("ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena")


def _save(text):
    d = client.post("/api/parse", json={"text": text}).json()
    assert d["ready"], d["say"]
    return client.post("/api/orders", json={"draft": d}).json()


def test_dispatch_conversation_keeps_context_and_confirms_in_hindi():
    o = _save("Jain bhai ko 8 carton Maggi aur 2 bag atta parso")
    dp = lambda text, ctx=None: client.post("/api/dispatch/parse", json={"text": text, **(ctx or {})}).json()
    # party, no mode -> asks how; "truck se" continues the same order (used to loop on "Kis party?")
    r = dp("जैन ब्रदर्स का माल गया")
    assert not r["ok"] and r["orders"][0]["id"] == o["id"] and "Kaise" in r["say"]
    r = dp("truck se", {"order_ids": [o["id"]]})
    assert r["ok"] and r["mode"] == "truck" and r["orders"][0]["id"] == o["id"]
    # "हां पक्का" in Devanagari confirms (the browser used to miss it and start over)
    r2 = dp("हां पक्का", {"order_ids": [o["id"]], "mode": "truck"})
    assert r2["action"] == "confirm" and r2["orders"][0]["id"] == o["id"]
    assert dp("nahi rehne do", {"order_ids": [o["id"]], "mode": "truck"})["action"] == "cancel"
    # without context, "haan pakka" alone does not dispatch anything
    assert not dp("haan pakka")["ok"]


def test_dispatch_by_order_number():
    a = _save("Bittu bhai ko 3 carton ghee kal")
    b = _save("Bittu bhai ko 4 carton Maggi kal")
    dp = lambda text: client.post("/api/dispatch/parse", json={"text": text}).json()
    for said in (f"order {a['id']} truck se gaya", f"order number {a['id']} tempo se",
                 f"{a['id']} number wala rickshaw se gaya", f"#{a['id']} auto"):
        r = dp(said)
        assert r["ok"] and [x["id"] for x in r["orders"]] == [a["id"]] and r["orders"][0]["party"] == "Bittu Store", said
    # the party name alone still means the latest open order
    assert dp("Bittu ka maal tempo se")["orders"][0]["id"] == b["id"]
    # wrong party for that number, unknown number, already sent
    assert "ka hai" in dp(f"Gupta ji ka order {a['id']} truck se")["say"]
    assert "nahi mila" in dp("order 999 truck se")["say"]
    client.post(f"/api/orders/{a['id']}/dispatch", json={"mode": "truck"})
    assert "ja chuka" in dp(f"order {a['id']} truck se")["say"]


def test_dispatch_several_orders_in_one_truck():
    from app import db
    from app.parser import find_order_numbers, split_joined_number
    assert find_order_numbers("order 3, 4 aur 5 ek hi truck")["numbers"] == [3, 4, 5]  # "ek" is not order 1
    assert find_order_numbers("ऑर्डर तीन चार और पांच ट्रक से")["numbers"] == [3, 4, 5]
    assert find_order_numbers("ऑर्डर 345 तीनों एक ही ट्रक में") == {"numbers": [345], "count": 3}
    assert split_joined_number(345, [3, 4, 5, 6], 3) == [[3, 4, 5]]
    assert split_joined_number(1213, [1, 2, 3, 12, 13], 2) == [[12, 13]]

    ids = [_save(t)["id"] for t in ("Gupta ji ko 2 carton ghee kal", "Jain bhai ko 3 carton Maggi kal",
                                    "Bittu bhai ko 4 bori cheeni kal")]
    open_ids = [o["id"] for o in db.list_orders(500) if o["status"] == "confirmed"]
    dp = lambda text, ctx=None: client.post("/api/dispatch/parse", json={"text": text, **(ctx or {})}).json()
    said = f"order {ids[0]}, {ids[1]} aur {ids[2]} teeno ek hi truck mein gaye"
    r = dp(said)
    assert r["ok"] and [o["id"] for o in r["orders"]] == ids and r["mode"] == "truck" and len(r["items"]) == 3
    # the speech engine joined the numbers; split only when exactly one way fits
    joined = int("".join(map(str, ids)))
    ways = split_joined_number(joined, open_ids, 3)
    r = dp(f"ऑर्डर {joined} तीनों एक ही ट्रक में")
    if ways == [ids]:
        assert r["ok"] and [o["id"] for o in r["orders"]] == ids
    else:
        assert not r["ok"]
    # no mode yet: asks, then "tempo se" applies to all three, then "haan pakka"
    r = dp(f"order {ids[0]} {ids[1]} aur {ids[2]}")
    assert not r["ok"] and len(r["orders"]) == 3 and "Kaise" in r["say"]
    r = dp("tempo se", {"order_ids": ids})
    assert r["ok"] and r["mode"] == "tempo" and len(r["orders"]) == 3
    r = dp("haan pakka", {"order_ids": ids, "mode": "tempo"})
    assert r["action"] == "confirm" and [o["id"] for o in r["orders"]] == ids
    # said "teeno" but only two numbers heard -> ask again
    assert "number dobara" in dp(f"order {ids[0]} aur {ids[1]} teeno truck se")["say"]
