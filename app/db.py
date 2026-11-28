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
CREATE TABLE IF NOT EXISTS parties (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL,        -- JSON list of spoken names
    pos INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS learned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code TEXT NOT NULL,
    words TEXT NOT NULL,          -- the spoken name the app learned for the item
    source TEXT NOT NULL,         -- jodo (staff linked a line) | answer (staff picked it, then "haan pakka") | stt
    order_id INTEGER,
    created_at TEXT NOT NULL
);
"""


NEW_ORDER_COLUMNS = [("stats", "TEXT"), ("seconds_to_confirm", "REAL"),
                     ("wrong_reason", "TEXT"), ("wrong_at", "TEXT"),
                     ("draft_id", "TEXT"), ("edited_at", "TEXT"), ("cancelled_at", "TEXT")]  # one draft = one order, even if Confirm is tapped twice


def _conn():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    have = {r["name"] for r in c.execute("PRAGMA table_info(orders)")}
    for col, typ in NEW_ORDER_COLUMNS:
        if col not in have:  # databases made before the pilot numbers
            c.execute(f"ALTER TABLE orders ADD COLUMN {col} {typ}")
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
        "stats": json.loads(r["stats"]) if r["stats"] else None,
        "seconds_to_confirm": r["seconds_to_confirm"],
        "wrong_reason": r["wrong_reason"], "wrong_at": r["wrong_at"],
        "edited_at": r["edited_at"], "cancelled_at": r["cancelled_at"],
    }


def _seconds_since(stats, now):
    """Seconds from the start of the order to its confirm. An order confirmed with
    no network is saved later; the phone sends how long it waited (offline_seconds)."""
    try:
        total = (now - datetime.fromisoformat(stats["started_at"])).total_seconds()
        waited = min(max(float(stats.get("offline_seconds") or 0), 0.0), max(total, 0.0))
        return max(0.0, round(total - waited, 1))
    except (TypeError, KeyError, ValueError, AttributeError):
        return None


def save_order(draft):
    lines = draft["lines"]
    now = datetime.now(IST)
    stats = draft.get("stats") if isinstance(draft.get("stats"), dict) else None
    draft_id = str(draft.get("draft_id") or "")[:40] or None
    with _conn() as c:
        if draft_id:  # a second tap or a network retry: the same order back, not a new one
            r = c.execute("SELECT id FROM orders WHERE draft_id=?", (draft_id,)).fetchone()
            if r:
                return get_order(r["id"], c)
        cur = c.execute(
            "INSERT INTO orders (party, party_code, items, quantities, units, delivery_date, heard_text, created_at,"
            " stats, seconds_to_confirm, draft_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (draft["party"]["party"]["name"], draft["party"]["party"]["code"],
             json.dumps([{"code": l["item"]["code"], "name": l["item"]["name"]} for l in lines]),
             json.dumps([l["qty"] for l in lines]),
             json.dumps([l["unit"] for l in lines]),
             draft["delivery"]["date"], draft.get("heard", ""),
             now.isoformat(timespec="seconds"),
             json.dumps(stats) if stats else None, _seconds_since(stats, now), draft_id))
        return get_order(cur.lastrowid, c)


def get_order(order_id, c=None):
    conn = c or _conn()
    r = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return _row(r) if r else None


def list_orders(limit=50):
    with _conn() as c:
        return [_row(r) for r in c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))]


def list_orders_for_ui(dispatched_limit=200):
    """Every order still waiting to go, plus the latest dispatched ones."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM orders WHERE status='confirmed' OR id IN "
                         "(SELECT id FROM orders WHERE status!='confirmed' ORDER BY id DESC LIMIT ?) ORDER BY id DESC",
                         (dispatched_limit,))
        return [_row(r) for r in rows]


def open_orders(party_code):
    with _conn() as c:
        return [_row(r) for r in c.execute(
            "SELECT * FROM orders WHERE party_code=? AND status='confirmed' ORDER BY id DESC", (party_code,))]


def mark_dispatched(order_id, mode):
    with _conn() as c:
        c.execute("UPDATE orders SET status='dispatched', dispatch_mode=?, dispatch_date=? WHERE id=?",
                  (mode, today().isoformat(), order_id))
        return get_order(order_id, c)


def mark_wrong(order_id, reason):
    """'Galat nikla': the saved order turned out wrong (pilot number)."""
    with _conn() as c:
        n = c.execute("UPDATE orders SET wrong_reason=?, wrong_at=? WHERE id=?",
                      (reason, datetime.now(IST).isoformat(timespec="seconds"), order_id)).rowcount
        return get_order(order_id, c) if n else None


def update_order(order_id, draft):
    """Edit: the order keeps its number, time and pilot numbers; party, lines and
    delivery are replaced. Only for an order that has not gone out."""
    lines = draft["lines"]
    with _conn() as c:
        c.execute(
            "UPDATE orders SET party=?, party_code=?, items=?, quantities=?, units=?, delivery_date=?, edited_at=?"
            " WHERE id=? AND status='confirmed'",
            (draft["party"]["party"]["name"], draft["party"]["party"]["code"],
             json.dumps([{"code": l["item"]["code"], "name": l["item"]["name"]} for l in lines]),
             json.dumps([l["qty"] for l in lines]), json.dumps([l["unit"] for l in lines]),
             draft["delivery"]["date"], datetime.now(IST).isoformat(timespec="seconds"), order_id))
        return get_order(order_id, c)


def cancel_order(order_id):
    with _conn() as c:
        c.execute("UPDATE orders SET status='cancelled', cancelled_at=? WHERE id=? AND status='confirmed'",
                  (datetime.now(IST).isoformat(timespec="seconds"), order_id))
        return get_order(order_id, c)


def orders_on_day(day):
    """Every order saved on that day (YYYY-MM-DD), oldest first, except cancelled ones."""
    with _conn() as c:
        return [_row(r) for r in c.execute(
            "SELECT * FROM orders WHERE substr(created_at, 1, 10)=? AND status!='cancelled' ORDER BY id", (day,))]


def top_item_codes(limit=30, days=60):
    """Item codes the shop orders most (by number of orders, recent days)."""
    from collections import Counter
    since = (today() - __import__("datetime").timedelta(days=days)).isoformat()
    count = Counter()
    with _conn() as c:
        for r in c.execute("SELECT items FROM orders WHERE created_at>=? AND status!='cancelled'", (since,)):
            for it in {i["code"] for i in json.loads(r["items"])}:
                count[it] += 1
    return [code for code, _ in count.most_common(limit)]


def reset_demo():
    """Demo only: delete every order and the baseline, put the sample items and parties back."""
    from .catalog import SAMPLE_ITEMS, SAMPLE_PARTIES
    with _conn() as c:
        c.execute("DELETE FROM orders")
        c.execute("DELETE FROM sqlite_sequence WHERE name='orders'")
        c.execute("DELETE FROM meta WHERE k='baseline_seconds'")
        c.execute("DELETE FROM learned")
    replace_items([dict(i, aliases=list(i["aliases"])) for i in SAMPLE_ITEMS])
    replace_parties([dict(p, aliases=list(p["aliases"])) for p in SAMPLE_PARTIES])


def clear_wrong(order_id):
    """Undo a "Galat nikla" tapped by mistake."""
    with _conn() as c:
        n = c.execute("UPDATE orders SET wrong_reason=NULL, wrong_at=NULL WHERE id=?", (order_id,)).rowcount
        return get_order(order_id, c) if n else None


def get_meta(k):
    with _conn() as c:
        r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None


def set_meta(k, v):
    with _conn() as c:
        c.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


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


def replace_items(items):
    """Swap the whole item list (Busy import). Orders keep their own copy of names."""
    with _conn() as c:
        c.execute("DELETE FROM items")
        for n, it in enumerate(items):
            c.execute("INSERT INTO items (code, name, unit, grp, aliases, pos) VALUES (?,?,?,?,?,?)",
                      (it["code"], it["name"], it["unit"], it["group"], json.dumps(it["aliases"]), n))
        c.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('items_seeded', '1')")


# ----------------------------------------------------------------- parties
def list_parties():
    """All parties. Seeds the sample parties the first time the database is used."""
    from .catalog import SAMPLE_PARTIES
    with _conn() as c:
        if not c.execute("SELECT 1 FROM meta WHERE k='parties_seeded'").fetchone():
            _insert_parties(c, SAMPLE_PARTIES)
        return [{"code": r["code"], "name": r["name"], "aliases": json.loads(r["aliases"])}
                for r in c.execute("SELECT * FROM parties ORDER BY pos, code")]


def _insert_parties(c, parties):
    for n, p in enumerate(parties):
        c.execute("INSERT OR IGNORE INTO parties (code, name, aliases, pos) VALUES (?,?,?,?)",
                  (p["code"], p["name"], json.dumps(p["aliases"]), n))
    c.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('parties_seeded', '1')")


def replace_parties(parties):
    """Swap the whole party list (Busy import)."""
    with _conn() as c:
        c.execute("DELETE FROM parties")
        _insert_parties(c, parties)


def delete_item(code):
    with _conn() as c:
        return c.execute("DELETE FROM items WHERE code=?", (code,)).rowcount > 0


# ------------------------------------------------------------- learned words
def add_learned(item_code, words, source, order_id=None):
    with _conn() as c:
        c.execute("INSERT INTO learned (item_code, words, source, order_id, created_at) VALUES (?,?,?,?,?)",
                  (item_code, words, source, order_id, datetime.now(IST).isoformat(timespec="seconds")))


def list_learned():
    """Every spoken name the app learned, newest first, with the item it points to now."""
    with _conn() as c:
        rows = c.execute("SELECT l.*, i.name AS item_name FROM learned l LEFT JOIN items i ON i.code = l.item_code "
                         "ORDER BY l.id DESC").fetchall()
        return [{"id": r["id"], "item_code": r["item_code"], "item_name": r["item_name"], "words": r["words"],
                 "source": r["source"], "order_id": r["order_id"], "created_at": r["created_at"]} for r in rows]


def delete_learned(learned_id):
    """Forget a learned name: it leaves the item's spoken names too. Returns the row or None."""
    with _conn() as c:
        r = c.execute("SELECT * FROM learned WHERE id=?", (learned_id,)).fetchone()
        if not r:
            return None
        c.execute("DELETE FROM learned WHERE id=?", (learned_id,))
        it = c.execute("SELECT aliases FROM items WHERE code=?", (r["item_code"],)).fetchone()
        if it:
            aliases = [a for a in json.loads(it["aliases"]) if a != r["words"]]
            c.execute("UPDATE items SET aliases=? WHERE code=?", (json.dumps(aliases), r["item_code"]))
        return dict(r)
