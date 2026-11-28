"""The app learns spoken names from staff, never on its own: when staff link a line
("Kisi item se jodo"), or answer "Pakka nahi hoon. 'X' matlab ...?" and then confirm the
order. Learned names are listed and can be removed. `learn.alias_candidates` compares a
local transcript with Sarvam's for a later local speech model."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import catalog, db
from app.learn import alias_candidates
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def sample_lists():
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())
    catalog.replace_parties([dict(p, aliases=list(p["aliases"])) for p in catalog.SAMPLE_PARTIES])
    for r in db.list_learned():
        db.delete_learned(r["id"])
    yield
    db.replace_items([dict(i, aliases=list(i["aliases"])) for i in catalog.SAMPLE_ITEMS])
    catalog.replace_items(db.list_items())


def _unsure_order(text="ABC ko 5 carton lucks soapy kal"):
    d = client.post("/api/parse", json={"text": text}).json()
    ln = d["lines"][0]
    assert ln["uncertain"] and d["question"]["type"] == "item"
    return d


def _answer(d, text):
    return client.post("/api/answer", json={"draft": d, "text": text}).json()


def test_answer_then_confirm_learns_the_heard_words():
    d = _unsure_order()
    heard = d["lines"][0]["item_text"]
    d = _answer(d, "Lux Soap")["draft"]
    assert d["lines"][0]["item"]["code"] == "SP01"
    assert heard not in db.get_item("SP01")["aliases"]  # nothing learned before the order is saved
    r = _answer(d, "haan pakka")
    assert r["action"] == "confirm"
    order = client.post("/api/orders", json={"draft": r["draft"]}).json()
    assert heard in db.get_item("SP01")["aliases"]
    learned = client.get("/api/learned").json()
    assert learned[0]["words"] == heard and learned[0]["source"] == "answer" and learned[0]["order_id"] == order["id"]
    # next time the same words match by themselves
    d2 = client.post("/api/parse", json={"text": "ABC ko 3 carton lucks soapy kal"}).json()
    assert d2["lines"][0]["item"]["code"] == "SP01" and d2["ready"]


def test_nothing_learned_without_saving():
    d = _unsure_order()
    _answer(d, "Lux Soap")
    assert client.get("/api/learned").json() == []


def test_saving_twice_learns_once():
    d = _answer(_unsure_order(), "Lux Soap")["draft"]
    client.post("/api/orders", json={"draft": d})
    client.post("/api/orders", json={"draft": d})
    assert len(client.get("/api/learned").json()) == 1


def test_generic_word_is_never_learned():
    d = client.post("/api/parse", json={"text": "ABC ko 5 carton sabun kal"}).json()
    d = _answer(d, "Lux")["draft"]
    client.post("/api/orders", json={"draft": d})
    assert client.get("/api/learned").json() == []  # "sabun" must keep asking which brand


def test_forget_a_learned_name():
    d = _answer(_unsure_order(), "Lux Soap")["draft"]
    client.post("/api/orders", json={"draft": d})
    row = client.get("/api/learned").json()[0]
    assert client.delete(f"/api/learned/{row['id']}").status_code == 200
    assert row["words"] not in db.get_item("SP01")["aliases"]
    assert client.get("/api/learned").json() == []
    assert client.delete(f"/api/learned/{row['id']}").status_code == 404


def test_jodo_is_listed_too():
    d = _unsure_order()
    r = client.post("/api/teach", json={"draft": d, "line_id": d["lines"][0]["id"], "code": "SP01"}).json()
    assert r["learned"]
    assert client.get("/api/learned").json()[0]["source"] == "jodo"


@pytest.mark.parametrize("local,cloud,want", [
    ("ABC ko das carton luks kal", "ABC ko das carton lux kal", [("SP01", "luks")]),
    ("das carton surf", "das carton surf", []),
    ("das carton lux", "dus carton lux", []),          # numbers are never names
    ("paanch carton madgi", "paanch carton maggi", [("MG01", "madgi")]),
    ("paanch carton kuch bhi", "paanch carton kya hai", []),  # the cloud words name no item
])
def test_alias_candidates(local, cloud, want):
    assert alias_candidates(local, cloud) == want
