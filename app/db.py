"""SQLite storage for confirmed orders and the shop's item list."""
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
CREATE TABLE IF NOT EXISTS items (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    grp TEXT,                     -- soap | detergent | dal | NULL
    aliases TEXT NOT NULL,        -- JSON list of spoken names
    pos INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
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


# ------------------------------------------------------------------- items
def _item(r):
    return {"code": r["code"], "name": r["name"], "unit": r["unit"], "group": r["grp"],
            "aliases": json.loads(r["aliases"])}


def list_items():
    """All items. Seeds the sample catalog the first time the database is used."""
    from .catalog import SAMPLE_ITEMS
    with _conn() as c:
        if not c.execute("SELECT 1 FROM meta WHERE k='items_seeded'").fetchone():
            for n, it in enumerate(SAMPLE_ITEMS):
                c.execute("INSERT OR IGNORE INTO items (code, name, unit, grp, aliases, pos) VALUES (?,?,?,?,?,?)",
                          (it["code"], it["name"], it["unit"], it["group"], json.dumps(it["aliases"]), n))
            c.execute("INSERT INTO meta (k, v) VALUES ('items_seeded', '1')")
        return [_item(r) for r in c.execute("SELECT * FROM items ORDER BY pos, code")]


def get_item(code):
    with _conn() as c:
        r = c.execute("SELECT * FROM items WHERE code=?", (code,)).fetchone()
        return _item(r) if r else None


def save_item(item, old_code=None):
    """Insert, or update the item that had old_code (the code itself may change)."""
    with _conn() as c:
        row = (item["code"], item["name"], item["unit"], item["group"], json.dumps(item["aliases"]))
        if old_code:
            c.execute("UPDATE items SET code=?, name=?, unit=?, grp=?, aliases=? WHERE code=?", row + (old_code,))
        else:
            pos = c.execute("SELECT COALESCE(MAX(pos), -1) + 1 FROM items").fetchone()[0]
            c.execute("INSERT INTO items (code, name, unit, grp, aliases, pos) VALUES (?,?,?,?,?,?)", row + (pos,))
    return get_item(item["code"])


def delete_item(code):
    with _conn() as c:
        return c.execute("DELETE FROM items WHERE code=?", (code,)).rowcount > 0
