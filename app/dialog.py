"""Order draft, read-back and one-question-at-a-time dialog.

The server is stateless: the browser keeps the draft JSON and sends it back
with each spoken answer. Every function here is plain code (no LLM).
"""
import re
import uuid

from .catalog import ITEMS_BY_CODE, PARTIES, PARTIES_BY_CODE, UNITS
from .matcher import choose_from, find_party, group_label, item_option, match_item, party_option
from .parser import extract_rules, is_confirm, is_correction, is_leave_it, parse_date, quantities_in, today
from .textnorm import norm, numbers_in, readable




MAX_QTY = 9999  # more than this is almost surely mis-heard ("das hazaar"?): ask again
TWO_PARTIES = "Do party ka naam aaya. Ek order ek party ka hota hai; doosri party ka order alag se karein."


def _fmt_qty(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def _short(name):
    """'Fortune Refined Oil 1L' -> 'Fortune Refined Oil' for speaking. A pack size goes;
    a fitting size stays ('Astral Elbow 3/4"'), or three elbows would sound the same."""
    words = [w for w in name.split()
             if not re.fullmatch(r"\(?\d+(\.\d+)?\s*(l|ml|ltr|litre|g|gm|gms|gram|kg|kgs)\)?", w, re.I)]
    return " ".join(words) or name


def make_line(raw):
    m = match_item(raw["item_text"])
    vals = list(dict.fromkeys(raw["qty_values"]))
    line = {
        "id": uuid.uuid4().hex[:8],
        "heard": raw["heard"],
        "item_text": raw["item_text"],
        "match": m["status"],
        "item": m["item"],
        "options": m["options"],
        "group": m["group"],
        "qty": vals[0] if len(vals) == 1 else None,
        "qty_alts": vals if len(vals) > 1 else [],
        "unit": raw["unit"] or (m["item"]["unit"] if m["item"] else None),
        "heard_unit": bool(raw["unit"]),
        "note": raw.get("note"),  # "agar sasta rate ..." -- shown on the line, never decided for the shop
    }
    return _refresh_line(line)


def _too_big(line):
    return line["qty"] is not None and float(line["qty"]) > MAX_QTY


def _refresh_line(line):
    line["uncertain"] = line["match"] != "ok" or line["qty"] is None or _too_big(line)
    if line["item"] and not line["unit"]:
        line["unit"] = line["item"]["unit"]
    return line


def _merge_repeats(lines):
    """On a call the shop repeats the order back ("10 carton Lux, theek hai").
    The same item with the same quantity and unit is one line, not two."""
    out, seen = [], {}
    for ln in lines:
        key = (ln["item"]["code"], ln["qty"]) if ln["item"] and ln["qty"] is not None else None
        if key and key in seen and (ln["unit"] == seen[key] or not ln["heard_unit"]):
            continue  # same item + qty; a repeat without a unit ("6 Parle-G") counts too
        if key:
            seen[key] = ln["unit"]
        out.append(ln)
    return out


def build_draft(transcript: str, call: bool = False):
    data = extract_rules(transcript, call)
    draft = {
        "heard": readable(transcript),
        "party": {"status": data["party"]["status"], "party": data["party"]["party"],
                  "options": data["party"]["options"]},
        "delivery": data["delivery"],
        "lines": _merge_repeats([make_line(r) for r in data["lines"]]),
        "notice": None,
        "warning": TWO_PARTIES if data.get("two_parties") else None,
    }
    if not draft["lines"]:
        draft["notice"] = "unclear"
    return finish(draft)


# ------------------------------------------------------------- questions
def next_question(d):
    p = d["party"]
    if p["status"] == "choose":
        names = " ya ".join(o["name"] for o in p["options"][:3])
        return {"type": "party", "line_id": None, "options": p["options"],
                "text": f"Kaun sa party? {names}?"}
    if p["status"] != "ok":
        return {"type": "party", "line_id": None, "options": [party_option(x["code"]) for x in PARTIES],
                "text": "Order kis party ka hai?"}
    for ln in d["lines"]:
        if ln["match"] == "choose":
            return {"type": "item", "line_id": ln["id"], "options": ln["options"],
                    "text": f"Kaun sa {group_label(ln['group'])} brand?"}
        if ln["match"] in ("unsure", "unknown", "missing"):
            names = ", ".join(_short(o["name"]) for o in ln["options"][:3])
            said = ln["item_text"] or "ye item"
            return {"type": "item", "line_id": ln["id"], "options": ln["options"][:3],
                    "text": f"Pakka nahi hoon. '{said}' matlab {names}?"}
    for ln in d["lines"]:
        if ln["qty_alts"]:
            alts = " ya ".join(_fmt_qty(v) for v in ln["qty_alts"])
            return {"type": "qty", "line_id": ln["id"], "options": [],
                    "text": f"{_short(ln['item']['name'])} {alts} {ln['unit'] or ''}? Kitna?".replace("  ", " ")}
        if ln["qty"] is None or ln["qty"] <= 0:
            return {"type": "qty", "line_id": ln["id"], "options": [],
                    "text": f"{_short(ln['item']['name'])} kitna chahiye?"}
        if _too_big(ln):
            return {"type": "qty", "line_id": ln["id"], "options": [],
                    "text": f"{_short(ln['item']['name'])} {_fmt_qty(ln['qty'])}? Ye bahut zyada hai. Sahi quantity bolein."}
    if not d["delivery"]:
        return {"type": "date", "line_id": None, "options": [], "text": "Delivery kab? Aaj, kal ya parso?"}
    return None


def readback(d):
    parts = []
    if d["party"]["status"] == "ok":
        parts.append(d["party"]["party"]["name"])
    for ln in d["lines"]:
        q = _fmt_qty(ln["qty"]) if ln["qty"] is not None else " ya ".join(map(_fmt_qty, ln["qty_alts"])) or "?"
        what = _short(ln["item"]["name"]) if ln["item"] else (group_label(ln["group"]) if ln["group"] else ln["item_text"] or "?")
        parts.append(f"{q} {ln['unit'] or ''} {what}".replace("  ", " ").strip())
    if d["delivery"]:
        parts.append(f"delivery {d['delivery']['label']}")
    return ", ".join(parts) + "." if parts else ""


def finish(d):
    if d.get("notice") == "unclear":
        d["question"] = None
        d["readback"] = ""
        d["say"] = "Awaaz saaf nahi aayi, dobara bolein."
        d["ready"] = False
        return d
    d["question"] = next_question(d)
    d["readback"] = readback(d)
    d["ready"] = d["question"] is None and bool(d["lines"])
    tail = d["question"]["text"] if d["question"] else "Sahi hai? Haan pakka bolein."
    warn = d.get("warning") if d["party"]["status"] != "ok" else None
    d["say"] = f"{warn + ' ' if warn else ''}{d['readback']} {tail}".strip()
    return d


# ---------------------------------------------------------------- answers
def _line(d, line_id):
    return next((l for l in d["lines"] if l["id"] == line_id), None)


def _set_qty(line, values):
    vals = list(dict.fromkeys(values))
    line["qty"], line["qty_alts"] = (vals[0], []) if len(vals) == 1 else (None, vals)
    _refresh_line(line)


def _apply_correction(d, text):
    """'nahi, aath carton' / 'nahi, lux 8 carton' changes only that one line."""
    nums = quantities_in(" ".join(norm(text).split()[1:]))  # "rehne do" is not 2
    rest = extract_rules(text)
    target = None
    named = [r for r in rest["lines"] if r["item_text"]]
    if named:
        m = match_item(named[0]["item_text"])
        code = m["item"]["code"] if m["item"] else None
        target = next((l for l in d["lines"] if l["item"] and l["item"]["code"] == code), None)
        if target is None and m["group"]:
            target = next((l for l in d["lines"] if l["group"] == m["group"]), None)
    if target is None and d.get("question") and d["question"].get("line_id"):
        target = _line(d, d["question"]["line_id"])
    if target is None and d.get("last_line_id"):
        target = _line(d, d["last_line_id"])
    if target is None and len(d["lines"]) == 1:
        target = d["lines"][0]
    if target is None:
        d["say"] = "Kis item ki quantity badalni hai? Item ka naam bolein."
        return d, False
    if nums:
        _set_qty(target, [nums[-1]])
        d["last_line_id"] = target["id"]
        if rest["lines"] and rest["lines"][0]["unit"]:
            target["unit"] = rest["lines"][0]["unit"]
        return d, True
    return d, False


def _count(d, key):
    """Pilot numbers; drafts from an old browser tab have no stats."""
    if isinstance(d.get("stats"), dict):
        d["stats"][key] = d["stats"].get(key, 0) + 1


def answer(d, text: str):
    """Apply one spoken answer to the draft. Returns (draft, action).

    action: "confirm" (save now), "updated", or "repeat" (didn't understand).
    """
    text = readable(text or "").strip()
    d["notice"] = None
    if not text:
        d["say"] = "Awaaz saaf nahi aayi, dobara bolein."
        return d, "repeat"
    if is_leave_it(text):  # "nahi, rehne do": change nothing
        finish(d)
        d["say"] = f"Theek hai, kuch nahi badla. {d['say']}"
        return d, "repeat"
    if is_confirm(text) and not is_correction(text):
        finish(d)
        if d["ready"]:
            return d, "confirm"
        d["say"] = f"Pehle ye batayein: {d['question']['text']}"
        return d, "repeat"
    if is_correction(text) and parse_date(text) and not quantities_in(" ".join(norm(text).split()[1:])):
        d["delivery"] = parse_date(text)  # "nahi, parso": only the day changes
        _count(d, "corrections")
        return finish(d), "updated"
    if is_correction(text):
        d, ok = _apply_correction(d, text)
        if ok:
            _count(d, "corrections")
            return finish(d), "updated"
        if d["say"].startswith("Kis item"):
            return d, "repeat"

    q = d.get("question") or next_question(d)
    handled = False
    if q and q["type"] == "item":
        line = _line(d, q["line_id"])
        pick = choose_from(text, q["options"], "item")
        if pick is None:
            m = match_item(text)
            if m["status"] == "ok":
                pick = m["item"]
        if pick and pick["code"] not in ITEMS_BY_CODE:  # the item list changed while this order was open
            pick = None
        if pick and line:
            line["item"], line["match"], line["options"] = item_option(pick["code"]), "ok", []
            line["unit"] = line["unit"] or ITEMS_BY_CODE[pick["code"]]["unit"]
            nums = numbers_in(text)
            if nums:  # "Lux, 12 carton"
                _set_qty(line, nums)
            _refresh_line(line)
            d["last_line_id"] = line["id"]
            handled = True
    elif q and q["type"] == "qty":
        nums = numbers_in(text)
        line = _line(d, q["line_id"])
        if nums and line:
            _set_qty(line, nums if len(set(nums)) > 1 else [nums[0]])
            d["last_line_id"] = line["id"]
            handled = True
    elif q and q["type"] == "party":
        pick = choose_from(text, q["options"], "party")
        if pick is None:
            res, _ = find_party(text)
            pick = res["party"] if res["status"] == "ok" else None
            if res["status"] == "choose":
                d["party"] = {"status": "choose", "party": None, "options": res["options"]}
                return finish(d), "updated"
        if pick and pick["code"] in PARTIES_BY_CODE:
            d["party"] = {"status": "ok", "party": pick, "options": []}
            handled = True
    elif q and q["type"] == "date":
        dt = parse_date(text)
        if dt:
            d["delivery"] = dt
            handled = True

    # extra items said in the answer ("aur 5 bori cheeni") are added as new lines
    if not handled:
        extra = extract_rules(text)
        if extra["lines"]:
            d["lines"].extend(make_line(r) for r in extra["lines"])
            handled = True
        past = bool(d["delivery"]) and str(d["delivery"].get("date", "")) < today().isoformat()
        if extra["delivery"] and (not d["delivery"] or past):  # a passed date (order waited offline) can be said again
            d["delivery"], handled = extra["delivery"], True
    if handled:
        _count(d, "questions")  # every answer that changed the order
    if not handled:
        finish(d)
        d["say"] = f"Samjha nahi. {d['question']['text'] if d['question'] else 'Haan pakka bolein.'}"
        return d, "repeat"
    return finish(d), "updated"


def draft_from_order(o):
    """A saved order back as a draft, to correct by voice ("nahi, aath carton",
    "aur 2 bori cheeni") and save again under the same number."""
    from datetime import date
    lines = []
    for ln in o["lines"]:
        known = ln["code"] in ITEMS_BY_CODE
        m = None if known else match_item(ln["name"])
        lines.append(_refresh_line({
            "id": uuid.uuid4().hex[:8], "heard": "", "item_text": ln["name"],
            "match": "ok" if known else m["status"], "item": item_option(ln["code"]) if known else m["item"],
            "options": [] if known else m["options"], "group": ITEMS_BY_CODE[ln["code"]].get("group") if known else m["group"],
            "qty": ln["qty"], "qty_alts": [], "unit": ln["unit"], "heard_unit": True, "note": None}))
    party_ok = o["party_code"] in PARTIES_BY_CODE
    when = date.fromisoformat(o["delivery_date"])
    label = {0: "aaj", 1: "kal", 2: "parso"}.get((when - today()).days, o["delivery_date"])
    d = {"heard": o.get("heard_text") or "", "lines": lines, "notice": None, "warning": None,
         "party": {"status": "ok", "party": party_option(o["party_code"]), "options": []} if party_ok
         else {"status": "missing", "party": None, "options": []},
         "delivery": {"date": o["delivery_date"], "label": label, "heard": ""},
         "edit_of": o["id"], "draft_id": uuid.uuid4().hex}
    return finish(d)


def link_line(d, line_id, code):
    """Staff tapped "Kisi item se jodo" (or made a new item) for this line.
    Only a person links a line; the app never does it on its own."""
    line = _line(d, line_id)
    if line is None:
        raise KeyError("line")
    if code not in ITEMS_BY_CODE:
        raise KeyError("code")
    line["item"], line["match"], line["options"], line["group"] = item_option(code), "ok", [], ITEMS_BY_CODE[code].get("group")
    line["unit"] = line["unit"] if line.get("heard_unit") and line.get("unit") else ITEMS_BY_CODE[code]["unit"]
    _refresh_line(line)
    d["last_line_id"] = line["id"]
    _count(d, "questions")
    return finish(d)


def remove_line(d, line_id):
    """Staff tapped "Hatao": a line the app got wrong (talk, a repeat) is dropped."""
    if _line(d, line_id) is None:
        raise KeyError("line")
    d["lines"] = [ln for ln in d["lines"] if ln["id"] != line_id]
    if d.get("question") and d["question"].get("line_id") == line_id:
        d["question"] = None
    _count(d, "corrections")
    if not d["lines"]:
        d["say"] = "Saari lines hat gayi. Order dobara bolein."
    return finish(d)


def validate_for_save(d):
    """Server-side check before saving. Returns error text or None.
    The browser holds the draft, so nothing in it is trusted: codes must be on
    the lists, units known, quantities sane, the date real and near."""
    if d.get("party", {}).get("status") != "ok":
        return "Party not confirmed"
    if (d["party"].get("party") or {}).get("code") not in PARTIES_BY_CODE:
        return "Unknown party"
    if not d.get("lines"):
        return "No items"
    for ln in d["lines"]:
        if not ln.get("item") or ln.get("match") != "ok":
            return f"Item not confirmed: {ln.get('item_text')}"
        if ln.get("qty") is None or ln.get("qty_alts") or float(ln["qty"]) <= 0:
            return f"Quantity not confirmed: {ln['item']['name']}"
        if ln["item"]["code"] not in ITEMS_BY_CODE:
            return "Unknown item code"
        if float(ln["qty"]) > MAX_QTY:
            return f"Quantity too large: {ln['item']['name']}"
        if ln.get("unit") not in UNITS:
            return f"Unknown unit: {ln.get('unit')}"
    if not d.get("delivery"):
        return "Delivery date missing"
    try:
        from datetime import date
        when = date.fromisoformat(str(d["delivery"].get("date")))
    except (TypeError, ValueError):
        return "Delivery date not valid"
    days = (when - today()).days
    if days > 60:
        return "Delivery date bahut aage hai (60 din tak)"
    if days < -1 and d.get("edit_of") is None:  # a late order being edited keeps its date
        return "Delivery date pichhli hai. Nayi date bolein (aaj, kal, parso)"
    return None
