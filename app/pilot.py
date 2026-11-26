"""Pilot numbers: what each order cost the shop in time, questions and corrections."""
from datetime import datetime

from .parser import IST

SOURCES = ("mic", "upload", "transcript", "typed")


def now_iso():
    return datetime.now(IST).isoformat(timespec="seconds")


def new_stats(source, draft, test=False):
    """Stats that travel inside the draft until the order is saved."""
    uncertain = sum(1 for ln in draft["lines"] if ln.get("uncertain"))
    if draft["party"]["status"] != "ok":
        uncertain += 1
    return {
        "started_at": now_iso(),
        "source": source if source in SOURCES else "typed",
        "questions": 0,
        "corrections": 0,
        "uncertain_start": uncertain,
        "lines": len(draft["lines"]),
        "test": bool(test),
    }
