"""Pilot numbers: what each order cost the shop in time, questions and corrections."""
from datetime import datetime, timedelta

from .parser import IST, today

SOURCES = ("mic", "upload", "transcript", "typed")


def now_iso():
    return datetime.now(IST).isoformat(timespec="seconds")


MAX_ELAPSED = 1800  # 30 min: anything longer is a tab left open, not order time


def new_stats(source, draft, test=False, elapsed=None, carry=None):
    """Stats that travel inside the draft until the order is saved.
    `elapsed` = seconds the browser says passed since staff started the order
    (pressed the mic, picked a recording, opened paste/type), so the clock
    covers speaking and transcription too, not only the checking."""
    try:
        back = min(max(float(elapsed or 0), 0), MAX_ELAPSED)
    except (TypeError, ValueError):
        back = 0
    uncertain = sum(1 for ln in draft["lines"] if ln.get("uncertain"))
    if draft["party"]["status"] != "ok":
        uncertain += 1
    if isinstance(carry, dict) and carry.get("started_at"):
        # "Back" and Samjho again: still the same order, so keep its clock and counts
        try:
            started = datetime.fromisoformat(str(carry["started_at"]))
            if 0 <= (datetime.now(IST) - started).total_seconds() <= MAX_ELAPSED:
                fresh = new_stats(source, draft, test)
                fresh.update(started_at=str(carry["started_at"]), questions=int(carry.get("questions") or 0),
                             corrections=int(carry.get("corrections") or 0))
                if carry.get("source") in SOURCES:
                    fresh["source"] = carry["source"]
                return fresh
        except (TypeError, ValueError):
            pass
    return {
        "started_at": (datetime.now(IST) - timedelta(seconds=back)).isoformat(timespec="seconds"),
        "source": source if source in SOURCES else "typed",
        "questions": 0,
        "corrections": 0,
        "uncertain_start": uncertain,
        "lines": len(draft["lines"]),
        "test": bool(test),
    }


WRONG_REASONS = ("item", "qty", "party", "missing", "other")
CSV_HEADER = ["id", "created_at", "party", "lines", "source", "test", "seconds_to_confirm",
              "questions", "corrections", "uncertain_start", "wrong_reason"]


def _median(vals):
    vals = sorted(vals)
    if not vals:
        return None
    mid = len(vals) // 2
    return round(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2, 1)


def _pct(part, whole):
    return round(100 * part / whole) if whole else None


def _is_test(o):
    return bool((o.get("stats") or {}).get("test"))


def summary(orders, baseline):
    """The numbers for the deck. Practice orders are left out of everything."""
    real = [o for o in orders if not _is_test(o) and o.get("status") != "cancelled"]
    with_stats = [o for o in real if o.get("stats")]
    times = [o["seconds_to_confirm"] for o in real if o.get("seconds_to_confirm") is not None]
    by_source, wrong = {}, {}
    for o in with_stats:
        src = o["stats"].get("source", "typed")
        by_source[src] = by_source.get(src, 0) + 1
    for o in real:
        if o.get("wrong_reason"):
            wrong[o["wrong_reason"]] = wrong.get(o["wrong_reason"], 0) + 1
    day = today().isoformat()
    corrections = sum(o["stats"].get("corrections", 0) for o in with_stats)
    return {
        "orders": len(real),
        "today": sum(1 for o in real if str(o.get("created_at", "")).startswith(day)),
        "median_seconds": _median(times),
        "avg_seconds": round(sum(times) / len(times), 1) if times else None,
        "pct_no_questions": _pct(sum(1 for o in with_stats if not o["stats"].get("questions")), len(with_stats)),
        "pct_right_after_save": _pct(sum(1 for o in real if not o.get("wrong_reason")), len(real)),
        "corrections_per_order": round(corrections / len(with_stats), 2) if with_stats else None,
        "by_source": by_source,
        "wrong_by_reason": wrong,
        "baseline_median": _median(baseline),
        "baseline_count": len(baseline),
    }


def csv_rows(orders):
    rows = [CSV_HEADER]
    for o in orders:
        if o.get("status") == "cancelled":
            continue
        st = o.get("stats") or {}
        rows.append([o["id"], o["created_at"], o["party"], len(o["lines"]), st.get("source", ""),
                     bool(st.get("test")), o.get("seconds_to_confirm"), st.get("questions", ""),
                     st.get("corrections", ""), st.get("uncertain_start", ""), o.get("wrong_reason") or ""])
    return rows
