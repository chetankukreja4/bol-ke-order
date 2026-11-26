"""Pilot numbers: every order records how long it took and how many questions it needed."""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_parse_starts_stats():
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton sabun kal", "source": "mic"}).json()
    s = d["stats"]
    assert s["source"] == "mic" and s["questions"] == 0 and s["corrections"] == 0
    assert s["lines"] == 1 and s["uncertain_start"] == 1 and s["test"] is False
    assert s["started_at"].startswith("20")


def test_answers_count_questions_and_corrections():
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton sabun kal"}).json()
    d = client.post("/api/answer", json={"draft": d, "text": "Lux"}).json()["draft"]
    d = client.post("/api/answer", json={"draft": d, "text": "nahi, aath carton"}).json()["draft"]
    assert d["stats"]["questions"] == 1 and d["stats"]["corrections"] == 1
    assert d["stats"]["source"] == "typed"


def test_old_draft_without_stats_still_works():
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton Lux kal"}).json()
    d.pop("stats", None)
    r = client.post("/api/answer", json={"draft": d, "text": "haan pakka"})
    assert r.status_code == 200 and r.json()["action"] == "confirm"
