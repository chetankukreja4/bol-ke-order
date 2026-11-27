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


def _confirmed(text="ABC wale ko 10 carton Lux kal", **kw):
    d = client.post("/api/parse", json={"text": text, **kw}).json()
    return client.post("/api/orders", json={"draft": d}).json()


def test_saved_order_keeps_stats_and_time():
    o = _confirmed(source="mic")
    assert o["stats"]["source"] == "mic" and o["seconds_to_confirm"] >= 0 and o["wrong_reason"] is None


def test_old_draft_saves_without_time():
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton Lux kal"}).json()
    d.pop("stats")
    o = client.post("/api/orders", json={"draft": d}).json()
    assert o["stats"] is None and o["seconds_to_confirm"] is None


def test_galat_nikla():
    o = _confirmed()
    assert client.post(f"/api/orders/{o['id']}/wrong", json={"reason": "qty"}).json()["wrong_reason"] == "qty"
    assert client.post(f"/api/orders/{o['id']}/wrong", json={"reason": "bad"}).status_code == 400
    assert client.post("/api/orders/999999/wrong", json={"reason": "qty"}).status_code == 404


def test_pilot_summary_numbers():
    from app.pilot import summary
    base = {"party": "X", "lines": [], "created_at": "2026-11-28T10:00:00+05:30", "wrong_reason": None}
    orders = [
        {**base, "id": 1, "seconds_to_confirm": 30, "stats": {"source": "mic", "questions": 0, "corrections": 0, "test": False}},
        {**base, "id": 2, "seconds_to_confirm": 50, "stats": {"source": "upload", "questions": 2, "corrections": 1, "test": False}, "wrong_reason": "qty"},
        {**base, "id": 3, "seconds_to_confirm": 5, "stats": {"source": "mic", "questions": 0, "corrections": 0, "test": True}},
        {**base, "id": 4, "seconds_to_confirm": None, "stats": None},
    ]
    s = summary(orders, [120, 180, 240])
    assert s["orders"] == 3 and s["median_seconds"] == 40 and s["avg_seconds"] == 40
    assert s["pct_no_questions"] == 50 and s["pct_right_after_save"] == 67
    assert s["corrections_per_order"] == 0.5
    assert s["by_source"] == {"mic": 1, "upload": 1} and s["wrong_by_reason"] == {"qty": 1}
    assert s["baseline_median"] == 180 and s["baseline_count"] == 3


def test_pilot_summary_empty():
    from app.pilot import summary
    s = summary([], [])
    assert s["orders"] == 0 and s["median_seconds"] is None and s["pct_right_after_save"] is None


def test_pilot_csv_and_baseline():
    assert client.put("/api/pilot/baseline", json={"seconds": [120, 200]}).status_code == 200
    assert client.get("/api/pilot").json()["baseline"] == [120, 200]
    assert client.put("/api/pilot/baseline", json={"seconds": [0]}).status_code == 400
    r = client.get("/api/pilot.csv")
    assert r.text.splitlines()[0].startswith("id,created_at,party")


def test_clock_starts_when_capture_started():
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton Lux kal", "elapsed": 40}).json()
    o = client.post("/api/orders", json={"draft": d}).json()
    assert 40 <= o["seconds_to_confirm"] < 45
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton Lux kal", "elapsed": 99999}).json()
    assert client.post("/api/orders", json={"draft": d}).json()["seconds_to_confirm"] <= 1805
