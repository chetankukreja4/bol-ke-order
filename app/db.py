"""SQLite storage for confirmed orders."""
import json
import os
import sqlite3
from datetime import datetime

from .parser import IST, today

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "orders.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party TEXT NOT NULL,
    party_code TEXT NOT NULL,
    items TEXT NOT NULL,          -- JSON list of {code, name}
    quantities TEXT NOT NULL,     -- JSON list of numbers, same order as items
    units TEXT NOT NULL,          -- JSON list of units, same order as items
    delivery_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed',   -- confirmed | dispatched
    dispatch_mode TEXT,
    dispatch_date TEXT,
    heard_text TEXT,
    created_at TEXT NOT NULL
);
"""


def _conn():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _row(r):
    items, qtys, units = json.loads(r["items"]), json.loads(r["quantities"]), json.loads(r["units"])
    return {
        "id": r["id"], "party": r["party"], "party_code": r["party_code"],
        "lines": [{"code": i["code"], "name": i["name"], "qty": q, "unit": u}
                  for i, q, u in zip(items, qtys, units)],
        "delivery_date": r["delivery_date"], "status": r["status"],
        "dispatch_mode": r["dispatch_mode"], "dispatch_date": r["dispatch_date"],
        "heard_text": r["heard_text"], "created_at": r["created_at"],
    }


def save_order(draft):
    lines = draft["lines"]
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO orders (party, party_code, items, quantities, units, delivery_date, heard_text, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (draft["party"]["party"]["name"], draft["party"]["party"]["code"],
             json.dumps([{"code": l["item"]["code"], "name": l["item"]["name"]} for l in lines]),
             json.dumps([l["qty"] for l in lines]),
             json.dumps([l["unit"] for l in lines]),
             draft["delivery"]["date"], draft.get("heard", ""),
             datetime.now(IST).isoformat(timespec="seconds")))
        return get_order(cur.lastrowid, c)


def get_order(order_id, c=None):
    conn = c or _conn()
    r = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return _row(r) if r else None


def list_orders(limit=50):
    with _conn() as c:
        return [_row(r) for r in c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))]


def latest_open_order(party_code):
    with _conn() as c:
        r = c.execute("SELECT * FROM orders WHERE party_code=? AND status='confirmed' ORDER BY id DESC LIMIT 1",
                      (party_code,)).fetchone()
        return _row(r) if r else None


def mark_dispatched(order_id, mode):
    with _conn() as c:
        c.execute("UPDATE orders SET status='dispatched', dispatch_mode=?, dispatch_date=? WHERE id=?",
                  (mode, today().isoformat(), order_id))
        return get_order(order_id, c)
