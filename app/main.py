"""Bol-ke-Order API + static frontend."""
import asyncio
import copy
import csv
import hashlib
import hmac
import time
import io
import json
import os
import re
import tempfile
import uuid


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

from fastapi import FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, stt
from . import catalog
from .catalog import CATALOG, GROUP_LABEL, GROUP_WORDS, PARTIES, UNITS
from .dialog import answer, build_draft, draft_from_order, link_line, validate_for_save
from .parser import is_cancel, is_confirm, parse_dispatch, split_joined_number
from .transcript import clean_transcript, looks_like_transcript
from .samples import TEST_PHRASES
from . import importer, pilot, tts

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
MAX_UPLOAD = 30 * 1024 * 1024
ALLOWED = (".m4a", ".ogg", ".oga", ".opus", ".mp3", ".wav", ".webm", ".aac", ".mp4")

app = FastAPI(title="Bol-ke-Order")
PIN_COOKIE = "bko_pin"


LOGIN_TRIES = 5          # wrong PINs allowed per address...
LOGIN_WINDOW = 10 * 60   # ...in this many seconds; then wait for the window to pass
_login_fails = {}


def reset_login_limits():
    _login_fails.clear()


def _pin_hash(pin):
    return hashlib.sha256(f"bko:{pin}".encode()).hexdigest()


def _same(a, b):
    """Constant-time compare that never raises on non-ASCII text."""
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


@app.middleware("http")
async def shop_pin(request, call_next):
    """Optional lock for a deployed app: set BKO_PIN and every /api call needs it.
    Without BKO_PIN the app stays open (it must start with no keys)."""
    pin = os.getenv("BKO_PIN", "").strip()
    path = request.url.path
    if pin and path.startswith("/api/") and path != "/api/login":
        if not _same(request.cookies.get(PIN_COOKIE, ""), _pin_hash(pin)):
            return JSONResponse({"detail": "PIN chahiye", "error": "pin"}, status_code=401)
    return await call_next(request)


class PinIn(BaseModel):
    pin: str


@app.post("/api/login")
def login(body: PinIn, request: Request):
    pin = os.getenv("BKO_PIN", "").strip()
    who = request.client.host if request.client else "?"
    now = time.monotonic()
    recent = [t for t in _login_fails.get(who, []) if now - t < LOGIN_WINDOW]
    _login_fails[who] = recent
    if pin and len(recent) >= LOGIN_TRIES:
        raise HTTPException(429, "Bahut galat PIN. 10 minute baad try karein")
    if pin and not _same(body.pin.strip(), pin):
        recent.append(now)
        raise HTTPException(401, "PIN galat hai")
    resp = JSONResponse({"ok": True})
    if pin:
        resp.set_cookie(PIN_COOKIE, _pin_hash(pin), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
    return resp
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
    carry: dict | None = None  # stats of the same order before "Back" (keeps its clock and counts)


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
        "server_tts": tts.available(),  # local Piper voice; otherwise the browser speaks
        "demo": os.getenv("BKO_DEMO") == "1",
        "today": __import__("app.parser", fromlist=["today"]).today().isoformat(),
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


def _spoken_clash(item, own_code=None):
    """A spoken name already used by another item makes every order for it
    "Pakka nahi hoon". Refuse it with the other item's name."""
    mine = {a for a in item["aliases"]} | {item["name"].lower()}
    for other in catalog.CATALOG:
        if other["code"] in (own_code, item["code"]):
            continue
        theirs = {a.lower() for a in other["aliases"]} | {other["name"].lower()}
        both = sorted(mine & theirs)
        if both:
            raise HTTPException(409, f"Spoken name '{both[0]}' pehle se {other['name']} ({other['code']}) mein hai")


@app.post("/api/items", status_code=201)
def items_create(body: ItemIn):
    item = _clean_item(body)
    if db.get_item(item["code"]):
        raise HTTPException(409, f"Code {item['code']} pehle se hai")
    _spoken_clash(item)
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
    _spoken_clash(item, own_code=code)
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


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/items/template.xlsx")
def items_template():
    """Empty Excel sheet for shops that do not use Busy."""
    return Response(importer.template("items", list(UNITS)), media_type=XLSX_TYPE,
                    headers={"Content-Disposition": 'attachment; filename="bol-ke-order-items.xlsx"'})


@app.get("/api/parties/template.xlsx")
def parties_template():
    return Response(importer.template("parties"), media_type=XLSX_TYPE,
                    headers={"Content-Disposition": 'attachment; filename="bol-ke-order-parties.xlsx"'})


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
        draft["stats"] = pilot.new_stats("transcript", draft, body.test, body.elapsed, body.carry)
        draft["draft_id"] = uuid.uuid4().hex
        return draft
    draft = build_draft(text)
    draft["stats"] = pilot.new_stats(body.source, draft, body.test, body.elapsed, body.carry)
    draft["draft_id"] = uuid.uuid4().hex
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
    # names come from the shop's own lists, never from the browser's copy of the draft
    d = copy.deepcopy(body.draft)
    d["party"]["party"]["name"] = catalog.PARTIES_BY_CODE[d["party"]["party"]["code"]]["name"]
    for ln in d["lines"]:
        ln["item"]["name"] = catalog.ITEMS_BY_CODE[ln["item"]["code"]]["name"]
    d["heard"] = str(d.get("heard") or "")[:5000]
    if d.get("edit_of") is not None:  # an edited order keeps its number
        o = db.get_order(int(d["edit_of"]))
        if not o:
            raise HTTPException(404, "Order not found")
        if o["status"] != "confirmed":
            raise HTTPException(409, f"Order {o['id']} ab badal nahi sakta ({o['status']})")
        return db.update_order(o["id"], d)
    return db.save_order(d)


@app.get("/api/orders/{order_id}/draft")
def order_as_draft(order_id: int):
    """Edit a saved order: it comes back as a draft for the Check-the-order screen."""
    o = db.get_order(order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    if o["status"] != "confirmed":
        raise HTTPException(409, f"Order {order_id} ab badal nahi sakta ({o['status']})")
    return draft_from_order(o)


@app.post("/api/orders/{order_id}/cancel")
def order_cancel(order_id: int):
    o = db.get_order(order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    if o["status"] != "confirmed":
        raise HTTPException(409, f"Order {order_id} cancel nahi ho sakta ({o['status']})")
    return db.cancel_order(order_id)


@app.get("/api/orders")
def orders():
    return db.list_orders_for_ui()


def _csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["order_id", "party", "item_code", "item_name", "quantity", "unit", "delivery_date", "status"])
    for o in rows:
        for ln in o["lines"]:
            w.writerow([o["id"], o["party"], ln["code"], ln["name"], ln["qty"], ln["unit"], o["delivery_date"], o["status"]])
    buf.seek(0)
    return buf


class TeachIn(BaseModel):
    draft: dict
    line_id: str
    code: str
    learn: bool = True


def _learnable(words):
    """Heard words worth keeping as a spoken name: real words, not a generic
    group word like "sabun" (that one must keep asking which brand)."""
    from .textnorm import norm
    w = norm(words or "").strip()
    generic = {norm(x) for ws in catalog.GROUP_WORDS.values() for x in ws}
    return w if len(w) >= 3 and any(ch.isalpha() for ch in w) and w not in generic else ""


@app.post("/api/teach")
def teach(body: TeachIn):
    """Link a "Pakka nahi hoon" line to an item the staff chose, and learn the
    words that were heard as that item's spoken name, so next time they match."""
    code = body.code.strip().upper()
    if code not in catalog.ITEMS_BY_CODE:
        raise HTTPException(400, "Item nahi mila")
    line = next((ln for ln in body.draft.get("lines", []) if ln.get("id") == body.line_id), None)
    if line is None:
        raise HTTPException(400, "Line nahi mili")
    words = _learnable(line.get("item_text"))
    learned, note = False, None
    if body.learn and words:
        item = db.get_item(code)
        other = next((o for o in catalog.CATALOG if o["code"] != code and
                      words in {a.lower() for a in o["aliases"]} | {o["name"].lower()}), None)
        if other:
            note = f"'{words}' pehle se {other['name']} ka naam hai, isliye yaad nahi kiya"
        elif words not in item["aliases"]:
            item["aliases"] = (item["aliases"] + [words])[:30]
            db.save_item(item, old_code=code)
            catalog.replace_items(db.list_items())
            learned = True
    d = link_line(copy.deepcopy(body.draft), body.line_id, code)
    return {"draft": d, "learned": learned, "note": note}


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
def all_csv(day: str | None = None):
    """Review sheet of the latest orders, or with ?day=today (or YYYY-MM-DD) every
    order saved that day, for entering into Busy in one go."""
    if day:
        from .parser import today as _today
        d = _today().isoformat() if day == "today" else day
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise HTTPException(400, "day must be today or YYYY-MM-DD")
        return StreamingResponse(_csv(db.orders_on_day(d)), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="busy-orders-{d}.csv"'})
    return StreamingResponse(_csv(db.list_orders(500)), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="orders-review.csv"'})


class ResetIn(BaseModel):
    confirm: str


@app.post("/api/demo/reset")
def demo_reset(body: ResetIn):
    """Clean data for a demo video. Off unless BKO_DEMO=1, and needs "RESET" typed."""
    if os.getenv("BKO_DEMO") != "1":
        raise HTTPException(403, "Demo reset is off (set BKO_DEMO=1)")
    if body.confirm.strip() != "RESET":
        raise HTTPException(400, "Type RESET to confirm")
    db.reset_demo()
    catalog.replace_items(db.list_items())
    catalog.replace_parties(db.list_parties())
    return {"ok": True}


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
            if o["status"] == "cancelled":
                return {"ok": False, "say": f"Order {o['id']} cancel ho chuka hai."}
            if o["status"] != "confirmed":
                return {"ok": False, "say": f"Order {o['id']} pehle hi {o['dispatch_mode'] or ''} se ja chuka hai."}
            if p["status"] == "ok" and p["party"]["code"] != o["party_code"]:
                return {"ok": False, "say": f"Order {o['id']} {o['party']} ka hai, {p['party']['name']} ka nahi. Dobara bolein."}
            orders.append(o)
        if res["count"] and res["count"] != len(orders):
            return {"ok": False, "say": f"Aapne {res['count']} order kahe, par {len(orders)} number sune. Order number dobara bolein."}
    elif p["status"] == "ok":
        open_ = db.open_orders(p["party"]["code"])
        if not open_:
            return {"ok": False, "say": f"{p['party']['name']} ka koi khula order nahi hai."}
        if len(open_) > 1:  # never pick one of them silently
            ids = ", ".join(f"#{o['id']}" for o in open_[:5])
            return {"ok": False, "mode": res["mode"] or ctx_mode,
                    "say": f"{p['party']['name']} ke {len(open_)} order khule hain: {ids}. Order number bolein."}
        orders = open_
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
    o = db.get_order(order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    if body.mode not in catalog.DISPATCH_MODES:
        raise HTTPException(400, "Mode must be one of: " + ", ".join(catalog.DISPATCH_MODES))
    if o["status"] == "cancelled":
        raise HTTPException(409, f"Order {order_id} cancel ho chuka hai")
    if o["status"] != "confirmed":
        raise HTTPException(409, f"Order {order_id} pehle hi {o['dispatch_mode'] or ''} se ja chuka hai")
    return db.mark_dispatched(order_id, body.mode)


@app.delete("/api/orders/{order_id}/wrong")
def order_wrong_undo(order_id: int):
    o = db.clear_wrong(order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    return o


class SpeakIn(BaseModel):
    text: str


@app.post("/api/speak")
async def speak(body: SpeakIn):
    """One line the app says, in the local Hindi voice (Piper). 503 when the
    voice is not installed: the browser then uses its own voice."""
    if not tts.available():
        return JSONResponse({"error": "voice_not_installed"}, status_code=503)
    if not tts.clean(body.text):
        raise HTTPException(400, "Nothing to say")
    try:
        audio, kind = await asyncio.to_thread(tts.speak, body.text)
    except Exception as e:  # a broken model must never break the order flow
        return JSONResponse({"error": "tts", "message": str(e)[:200]}, status_code=502)
    return Response(content=audio, media_type=kind, headers={"Cache-Control": "private, max-age=86400"})


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
