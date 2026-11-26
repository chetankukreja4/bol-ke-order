"""Bol-ke-Order API + static frontend."""
import csv
import io
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
from .parser import parse_dispatch
from .transcript import clean_transcript, looks_like_transcript
from .samples import TEST_PHRASES

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
MAX_UPLOAD = 30 * 1024 * 1024
ALLOWED = (".m4a", ".ogg", ".oga", ".opus", ".mp3", ".wav", ".webm", ".aac", ".mp4")

app = FastAPI(title="Bol-ke-Order")
catalog.replace_items(db.list_items())  # the shop's own item list from SQLite


class TextIn(BaseModel):
    text: str
    kind: str | None = None  # "transcript" = pasted call transcript


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
        return draft
    return build_draft(text)


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


@app.post("/api/dispatch/parse")
def dispatch_parse(body: TextIn):
    res = parse_dispatch(body.text)
    p = res["party"]
    if p["status"] == "choose":
        names = " ya ".join(o["name"] for o in p["options"])
        return {"ok": False, "say": f"Kaun sa party? {names}?", "options": p["options"], "mode": res["mode"]}
    if p["status"] != "ok":
        return {"ok": False, "say": "Kis party ka maal gaya? Dobara bolein."}
    order = db.latest_open_order(p["party"]["code"])
    if not order:
        return {"ok": False, "say": f"{p['party']['name']} ka koi khula order nahi hai."}
    if not res["mode"]:
        return {"ok": False, "say": "Kaise bheja? Rickshaw, tempo ya truck?", "order": order}
    items = ", ".join(f"{ln['qty']} {ln['unit']} {ln['name']}" for ln in order["lines"][:3])
    return {"ok": True, "order": order, "mode": res["mode"],
            "say": f"{p['party']['name']} order {order['id']}, {res['mode']} se gaya. Pakka?",
            "items": items}


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
