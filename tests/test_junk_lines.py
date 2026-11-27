"""Lines from a real pump/motor shop call (27 Nov screenshot): talk must not become order lines,
and staff can remove a line the app got wrong."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.dialog import build_draft
from app.main import app

client = TestClient(app)


def texts(text):
    return [ln["item_text"] for ln in build_draft(text)["lines"]]


@pytest.mark.parametrize("talk", [
    "phir ye jo dal rahe ho ye lo na",          # "dal" here is the verb daalna
    "are ye toh mota sa dal raha hai na",
    "sabun ka kya haal hai",                   # a generic word alone, no quantity
])
def test_generic_word_without_quantity_is_not_a_line(talk):
    assert texts(f"Gupta ko 5 carton Lux kal. {talk}") == ["lux"]


def test_a_question_about_something_unknown_is_not_a_line():
    assert texts("Gupta ko 5 carton Lux kal. nine p ke apne pas advertisement kitna pada hoga") == ["lux"]


def test_real_unknown_items_still_become_lines():
    got = texts("Gupta ko pachas motor aur barah submersible kal")
    assert got == ["motor", "submersible"]


def test_named_item_without_quantity_still_asks():
    d = build_draft("ABC ko lux bhejna kal")
    assert [ln["item_text"] for ln in d["lines"]] == ["lux"] and d["lines"][0]["qty"] is None


def test_a_question_with_a_known_item_is_still_a_line():
    # "Lux kitna? 10 carton" style: a catalog item with a quantity stays
    assert texts("Gupta ko Lux kitna bhejun 10 carton kal") == ["lux"]


def test_staff_can_remove_a_line():
    d = client.post("/api/parse", json={"text": "Gupta ko 5 carton Lux aur 9 advertisement kal"}).json()
    junk = next(ln for ln in d["lines"] if ln["item_text"] != "lux")
    r = client.post("/api/line/remove", json={"draft": d, "line_id": junk["id"]})
    assert r.status_code == 200
    d2 = r.json()
    assert [ln["item_text"] for ln in d2["lines"]] == ["lux"] and d2["ready"] is True
    assert d2["stats"]["corrections"] == 1
    assert client.post("/api/line/remove", json={"draft": d2, "line_id": "nope"}).status_code == 400
