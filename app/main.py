"""Bol-ke-Order API + static frontend."""
import csv
import io
import json
import os
import re
import tempfile


def _load_dotenv(path=os.path.join(os.path.dirname(__file__), "..", ".env")):
    """Read KEY=value lines from .env for local runs (real env vars win)."""
    if os.getenv("BKO_NO_DOTENV"):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if v.strip():
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, stt
from . import catalog
from .catalog import CATALOG, GROUP_LABEL, GROUP_WORDS, PARTIES, UNITS
from .dialog import answer, build_draft, validate_for_save
from .parser import is_cancel, is_confirm, parse_dispatch, split_joined_number
from .transcript import clean_transcript, looks_like_transcript
from .samples import TEST_PHRASES
from . import importer, pilot

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
MAX_UPLOAD = 30 * 1024 * 1024
ALLOWED = (".m4a", ".ogg", ".oga", ".opus", ".mp3", ".wav", ".webm", ".aac", ".mp4")

app = FastAPI(title="Bol-ke-Order")
catalog.replace_items(db.list_items())  # the shop's own item list from SQLite
catalog.replace_parties(db.list_parties())  # and its parties


class DispatchTextIn(BaseModel):
    text: str
    order_ids: list[int] = []  # the orders being discussed, from the previous turn
    mode: str | None = None


class TextIn(BaseModel):
    text: str
    kind: str | None = None  # "transcript" = pasted call transcript
    source: str | None = None  # mic | upload | transcript | typed (pilot numbers)
    test: bool = False  # practice order: left out of the pilot numbers
    elapsed: float | None = None  # seconds since staff started this order (mic / upload / paste)


class AnswerIn(BaseModel):
    draft: dict
    text: str


class DraftIn(BaseModel):
    draft: dict


class DispatchIn(BaseModel):
    mode: str


class ItemIn(BaseModel):
    code: str
    name: str
    unit: str
    group: str | None = None
    aliases: list[str] = []


@app.get("/api/config")
def config():
    return {
        "server_stt": stt.stt_available(),
        "stt_message": None if stt.stt_available() else "Speech key not set (SARVAM_API_KEY). Live mic uses the browser; uploads are off.",
        "catalog": CATALOG, "parties": PARTIES, "test_phrases": TEST_PHRASES,
        "units": list(UNITS), "groups": [{"key": g, "label": GROUP_LABEL.get(g, g), "words": w}
                                          for g, w in GROUP_WORDS.items()],
    }


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    name = (file.filename or "audio").lower()
    if not name.endswith(ALLOWED):
        raise HTTPException(400, "Use m4a, ogg, mp3, wav or webm audio")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large")
    if not data:
        raise HTTPException(400, "Empty file")
    suffix = os.path.splitext(name)[1] or ".audio"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        result = await stt.transcribe_file(path)
    except stt.KeyNotSet as e:
        return JSONResponse({"error": "key_not_set", "message": str(e)}, status_code=503)
    except stt.AudioError as e:
        return JSONResponse({"error": "audio", "message": str(e)}, status_code=502)
    finally:
        os.unlink(path)
    result["unclear"] = len(result["transcript"].split()) < 2
    return result


# ------------------------------------------------------------------- items
def _clean_item(body: ItemIn):
    code = re.sub(r"\s+", "", body.code).upper()
    name = re.sub(r"\s+", " ", body.name).strip()
    if not re.fullmatch(r"[A-Z0-9_-]{1,12}", code):
        raise HTTPException(400, "Item code: 1-12 letters or numbers, e.g. SP04")
    if not name or len(name) > 80:
        raise HTTPException(400, "Item name chahiye (80 letters tak)")
    if body.unit not in UNITS:
        raise HTTPException(400, f"Unit must be one of: {', '.join(UNITS)}")
    group = body.group or None
    if group is not None and group not in GROUP_WORDS:
        raise HTTPException(400, f"Group must be one of: {', '.join(GROUP_WORDS)}")
    aliases, seen = [], set()
    for a in body.aliases:
        a = re.sub(r"\s+", " ", a).strip().lower()
        if a and a not in seen and len(a) <= 60:
            seen.add(a); aliases.append(a)
    return {"code": code, "name": name, "unit": body.unit, "group": group, "aliases": aliases[:30]}


@app.get("/api/items")
def items_list():
    return db.list_items()


@app.post("/api/items", status_code=201)
def items_create(body: ItemIn):
    item = _clean_item(body)
    if db.get_item(item["code"]):
        raise HTTPException(409, f"Code {item['code']} pehle se hai")
    saved = db.save_item(item)
    catalog.replace_items(db.list_items())
    return saved


@app.put("/api/items/{code}")
def items_update(code: str, body: ItemIn):
    if not db.get_item(code):
        raise HTTPException(404, "Item not found")
    item = _clean_item(body)
    if item["code"] != code and db.get_item(item["code"]):
        raise HTTPException(409, f"Code {item['code']} pehle se hai")
    saved = db.save_item(item, old_code=code)
    catalog.replace_items(db.list_items())
    return saved


MAX_IMPORT = 5 * 1024 * 1024


async def _read_import(file: UploadFile, convert):
    data = await file.read(MAX_IMPORT + 1)
    if len(data) > MAX_IMPORT:
        raise HTTPException(400, "File 5 MB se badi hai")
    try:
        rows = importer.read_table(file.filename or "", data)
    except importer.ImportProblem as e:
        raise HTTPException(400, str(e))
    found, skipped = convert(rows)
    return rows, found, skipped


def _import_reply(rows, found, skipped, committed):
    return {"total_rows": len(rows), "count": len(found), "sample": found[:10],
            "skipped": skipped, "committed": committed}


@app.post("/api/items/import")
async def items_import(file: UploadFile = File(...), commit: int = 0):
    """Busy item list. Without commit=1 it only shows what would be loaded."""
    rows, items, skipped = await _read_import(file, lambda r: importer.to_items(r, catalog.CATALOG))
    done = bool(commit) and bool(items)
    if done:
        db.replace_items(items)
        catalog.replace_items(db.list_items())
    return _import_reply(rows, items, skipped, done)


@app.get("/api/parties")
def parties_list():
    return db.list_parties()


@app.post("/api/parties/import")
async def parties_import(file: UploadFile = File(...), commit: int = 0):
    """Busy account list (customers). Without commit=1 it only shows what would be loaded."""
    rows, parties, skipped = await _read_import(file, lambda r: importer.to_parties(r, catalog.PARTIES))
    done = bool(commit) and bool(parties)
    if done:
        db.replace_parties(parties)
        catalog.replace_parties(db.list_parties())
    return _import_reply(rows, parties, skipped, done)


@app.delete("/api/items/{code}")
def items_delete(code: str):
    if not db.delete_item(code):
        raise HTTPException(404, "Item not found")
    catalog.replace_items(db.list_items())
    return {"deleted": code}


@app.post("/api/parse")
def parse(body: TextIn):
    text = body.text.strip()
    if body.kind == "transcript" or looks_like_transcript(text):
        cleaned = clean_transcript(text)
        draft = build_draft(cleaned["text"])
        draft["source"] = "transcript"
        draft["turns"] = cleaned["turns"]
        draft["stats"] = pilot.new_stats("transcript", draft, body.test, body.elapsed)
        return draft
    draft = build_draft(text)
    draft["stats"] = pilot.new_stats(body.source, draft, body.test, body.elapsed)
    return draft


@app.post("/api/answer")
def post_answer(body: AnswerIn):
    draft, action = answer(body.draft, body.text)
    return {"draft": draft, "action": action}


@app.post("/api/orders")
def create_order(body: DraftIn):
    err = validate_for_save(body.draft)
    if err:
        raise HTTPException(400, err)
    return db.save_order(body.draft)


@app.get("/api/orders")
def orders():
    return db.list_orders()


def _csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["order_id", "party", "item_code", "item_name", "quantity", "unit", "delivery_date", "status"])
    for o in rows:
        for ln in o["lines"]:
            w.writerow([o["id"], o["party"], ln["code"], ln["name"], ln["qty"], ln["unit"], o["delivery_date"], o["status"]])
    buf.seek(0)
    return buf


class WrongIn(BaseModel):
    reason: str


class BaselineIn(BaseModel):
    seconds: list[float]


@app.post("/api/orders/{order_id}/wrong")
def order_wrong(order_id: int, body: WrongIn):
    if body.reason not in pilot.WRONG_REASONS:
        raise HTTPException(400, f"Reason must be one of: {', '.join(pilot.WRONG_REASONS)}")
    o = db.mark_wrong(order_id, body.reason)
    if not o:
        raise HTTPException(404, "Order not found")
    return o


def _baseline():
    raw = db.get_meta("baseline_seconds")
    return json.loads(raw) if raw else []


@app.get("/api/pilot")
def pilot_numbers():
    base = _baseline()
    out = pilot.summary(db.list_orders(100000), base)
    out["baseline"] = base
    return out


@app.put("/api/pilot/baseline")
def pilot_baseline(body: BaselineIn):
    if len(body.seconds) > 50 or any(not 1 <= s <= 3600 for s in body.seconds):
        raise HTTPException(400, "1 se 3600 second tak, 50 times tak")
    db.set_meta("baseline_seconds", json.dumps(body.seconds))
    return {"baseline": body.seconds}


@app.get("/api/pilot.csv")
def pilot_csv():
    buf = io.StringIO()
    csv.writer(buf).writerows(pilot.csv_rows(db.list_orders(100000)))
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="pilot-numbers.csv"'})


@app.get("/api/orders/{order_id}/csv")
def order_csv(order_id: int):
    o = db.get_order(order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    return StreamingResponse(_csv([o]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="order-{order_id}.csv"'})


@app.get("/api/orders.csv")
def all_csv():
    return StreamingResponse(_csv(db.list_orders(500)), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="orders-review.csv"'})


def _orders_say(orders):
    if len(orders) == 1:
        return f"{orders[0]['party']} order {orders[0]['id']}"
    parties = list(dict.fromkeys(o["party"] for o in orders))
    ids = ", ".join(str(o["id"]) for o in orders[:-1]) + f" aur {orders[-1]['id']}"
    return f"Order {ids} ({', '.join(parties)})"


@app.post("/api/dispatch/parse")
def dispatch_parse(body: DispatchTextIn):
    """One turn of the dispatch talk. The browser sends back the orders and mode
    from the previous turn, so "truck se" or "haan pakka" continue it.
    Several orders can go together: "order 3, 4 aur 5 ek hi truck mein"."""
    text = body.text.strip()
    ctx = [o for o in (db.get_order(i) for i in body.order_ids) if o and o["status"] == "confirmed"]
    ctx_mode = body.mode if ctx else None

    if ctx and ctx_mode and is_confirm(text):
        return {"ok": True, "action": "confirm", "orders": ctx, "mode": ctx_mode, "say": ""}
    res = parse_dispatch(text)
    if ctx and is_cancel(text) and not res["mode"]:
        return {"ok": False, "action": "cancel", "say": "Theek hai, cancel."}

    orders, p = [], res["party"]
    if res["order_nos"]:
        open_ids = [o["id"] for o in db.list_orders(500) if o["status"] == "confirmed"]
        nos = res["order_nos"]
        if len(nos) == 1 and not db.get_order(nos[0]):
            # "3, 4, 5" heard as "345": cut it into open orders, then read it back for "pakka"
            ways = split_joined_number(nos[0], open_ids, res["count"])
            if len(ways) == 1:
                nos = ways[0]
            elif ways:
                opts = " ya ".join(", ".join(map(str, w)) for w in ways[:3])
                return {"ok": False, "say": f"Order {nos[0]} nahi mila. Kya matlab {opts}? Order number alag alag bolein."}
        for n in nos:
            o = db.get_order(n)
            if not o:
                return {"ok": False, "say": f"Order {n} nahi mila. Dobara bolein."}
            if o["status"] != "confirmed":
                return {"ok": False, "say": f"Order {o['id']} pehle hi {o['dispatch_mode'] or ''} se ja chuka hai."}
            if p["status"] == "ok" and p["party"]["code"] != o["party_code"]:
                return {"ok": False, "say": f"Order {o['id']} {o['party']} ka hai, {p['party']['name']} ka nahi. Dobara bolein."}
            orders.append(o)
        if res["count"] and res["count"] != len(orders):
            return {"ok": False, "say": f"Aapne {res['count']} order kahe, par {len(orders)} number sune. Order number dobara bolein."}
    elif p["status"] == "ok":
        o = db.latest_open_order(p["party"]["code"])
        if not o:
            return {"ok": False, "say": f"{p['party']['name']} ka koi khula order nahi hai."}
        orders = [o]
    elif p["status"] == "choose":
        names = " ya ".join(o["name"] for o in p["options"])
        return {"ok": False, "say": f"Kaun sa party? {names}? Ya order number bolein.", "options": p["options"],
                "mode": res["mode"] or ctx_mode, "orders": ctx}
    elif ctx:
        orders = ctx  # "truck se" after we asked how it went
    else:
        return {"ok": False, "say": "Kis party ka maal gaya? Party ka naam ya order number bolein."}

    same = ctx and [o["id"] for o in orders] == [o["id"] for o in ctx]
    mode = res["mode"] or (ctx_mode if same else None)
    who = _orders_say(orders)
    if not mode:
        return {"ok": False, "orders": orders, "say": f"{who}. Kaise bheja? Rickshaw, tempo ya truck?"}
    items = [f"#{o['id']} {o['party']}: " + ", ".join(f"{ln['qty']} {ln['unit']} {ln['name']}" for ln in o["lines"][:3])
             for o in orders]
    return {"ok": True, "orders": orders, "mode": mode, "items": items,
            "say": f"{who}, {mode} se gaya. Pakka?"}


@app.post("/api/orders/{order_id}/dispatch")
def dispatch(order_id: int, body: DispatchIn):
    if not db.get_order(order_id):
        raise HTTPException(404, "Order not found")
    return db.mark_dispatched(order_id, body.mode)


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
