"""Rule-based Hinglish order extraction (works with no API key).

Turns "ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena" into
    party_text="abc wale", delivery="kal",
    lines=[{item_text:"sabun", qty_values:[10], unit:"carton"}, ...]
Small talk and bargaining clauses (rate, discount, bhav) are dropped.
No LLM is used anywhere: the app keeps working if any AI service goes away.
"""
import re
from datetime import datetime, timedelta, timezone

from .catalog import DISPATCH_MODES, UNITS
from .matcher import find_party
from .textnorm import WEAK_NUMBER_WORDS, norm, parse_number_at

IST = timezone(timedelta(hours=5, minutes=30))

_UNIT_WORDS = {norm(w): u for u, ws in UNITS.items() for w in ws}
_ALT_WORDS = {"ya", "or", "yaa", "-", "to"}
_SPLIT_RE = re.compile(r"[,;!?\n।]|(?<!\d)\.(?!\d)| aur| and | plus | phir | fir | uske baad | sath mein | saath mein ")
_BARGAIN = {norm(w) for w in ["rate", "rat", "bhav", "bhaav", "daam", "dam", "price", "discount",
                               "rupay", "rupaye", "rupee", "rs", "percent", "kam", "mehnga",
                               "mahanga", "sasta", "paisa", "paise", "udhaar", "udhar", "payment"]}
_STOP = {norm(w) for w in [
    "ko", "ka", "ki", "ke", "wale", "wala", "vale", "vala", "bhai", "ji", "sahab", "bhej", "bhejna",
    "bhejo", "bhejdo", "dena", "de", "dijiye", "dijie", "do", "chahiye", "chaiye", "hai", "hain",
    "haan", "han", "ha", "accha", "acha", "theek", "thik", "ok", "okay", "hello", "namaste", "sir",
    "aur", "and", "bhi", "bas", "please", "plz", "order", "likho", "likh", "lo", "le", "lena", "maal",
    "saman", "saamaan", "samaan", "wo", "woh", "vo", "ye", "yeh", "jo", "the", "a", "of", "mein",
    "me", "se", "tak", "to", "ek", "kar", "karna", "karo", "dijiyega", "dedo", "de do", "send",
    "deliver", "delivery", "bhejiye", "pe", "par", "liye", "wahi", "vahi", "same", "naya", "nahi",
    "no", "galat", "sorry", "matlab", "mtlb", "aap", "ap", "hum", "humko", "mujhe", "unko", "ab"]}

_DAY_WORDS = {
    0: ["aaj", "aj", "today", "abhi", "turant"],
    1: ["kal", "tomorrow", "kl"],
    2: ["parso", "parson", "parsoon", "day after"],
}
_WEEKDAYS = {0: ["somvar", "monday"], 1: ["mangalvar", "mangal", "tuesday"],
             2: ["budhvar", "budh", "wednesday"], 3: ["guruvar", "veervar", "thursday"],
             4: ["shukravar", "shukra", "friday"], 5: ["shanivar", "shani", "saturday"],
             6: ["ravivar", "itvaar", "itwar", "sunday"]}


def today():
    return datetime.now(IST).date()


def parse_date(text: str):
    """Returns {"date": "YYYY-MM-DD", "label": "kal", "heard": ...} or None."""
    t = f" {norm(text)} "
    for days, words in _DAY_WORDS.items():
        for w in words:
            if f" {norm(w)} " in t:
                d = today() + timedelta(days=days)
                return {"date": d.isoformat(), "label": w if w in ("aaj", "kal", "parso") else
                        {0: "aaj", 1: "kal", 2: "parso"}[days], "heard": w}
    for wd, words in _WEEKDAYS.items():
        for w in words:
            if f" {norm(w)} " in t:
                ahead = (wd - today().weekday()) % 7 or 7
                d = today() + timedelta(days=ahead)
                return {"date": d.isoformat(), "label": words[0], "heard": w}
    return None


_DATE_TOKENS = {norm(w) for ws in list(_DAY_WORDS.values()) + list(_WEEKDAYS.values()) for w in ws}


def _tokens(text):
    t = norm(text)
    t = re.sub(r"(\d)\s*-\s*(\d)", r"\1 ya \2", t)
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)  # "10carton" -> "10 carton"
    return t.split()


def _is_qty_start(toks, i):
    v, used = parse_number_at(toks, i)
    if v is None:
        return None, 0
    if toks[i] in WEAK_NUMBER_WORDS and used == 1:
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if nxt not in _UNIT_WORDS:  # "bhej do", "ek minute" are not quantities
            return None, 0
    return v, used


def _read_qty(toks, i):
    """Quantity at i, with optional alternative ('10 ya 12') and unit."""
    v, used = _is_qty_start(toks, i)
    if v is None:
        return None
    vals, j = [v], i + used
    while j + 1 < len(toks) and toks[j] in _ALT_WORDS:
        v2, u2 = parse_number_at(toks, j + 1)
        if v2 is None:
            break
        vals.append(v2)
        j += 1 + u2
    unit = None
    if j < len(toks) and toks[j] in _UNIT_WORDS:
        unit = _UNIT_WORDS[toks[j]]
        j += 1
    return {"values": vals, "unit": unit, "end": j}


def _is_bargain(toks):
    return any(t in _BARGAIN for t in toks) or any("₹" in t for t in toks)


def _clean_item(toks):
    return [t for t in toks if t not in _STOP and t not in _DATE_TOKENS and t not in _UNIT_WORDS]


def extract_rules(text: str):
    party_res, party_phrase = find_party(text)
    party_tokens = set(party_phrase.split()) if party_phrase else set()
    lines = []
    for clause in _SPLIT_RE.split(f" {text} "):
        toks = _tokens(clause)
        if not toks or _is_bargain(toks):
            continue
        # find quantity spans; each starts a new line
        spans, i = [], 0
        while i < len(toks):
            q = _read_qty(toks, i)
            if q:
                spans.append((i, q))
                i = q["end"]
            else:
                i += 1
        if not spans:
            continue
        for n, (start, q) in enumerate(spans):
            stop = spans[n + 1][0] if n + 1 < len(spans) else len(toks)
            after = [t for t in toks[q["end"]:stop] if t not in party_tokens]
            item = _clean_item(after)
            if not item and n == 0:  # "sabun 10 carton" (item said first)
                item = _clean_item([t for t in toks[:start] if t not in party_tokens])
            lines.append({
                "heard": " ".join(toks[start:stop]) if item else " ".join(toks),
                "item_text": " ".join(item),
                "qty_values": q["values"],
                "unit": q["unit"],
            })
    return {"party": party_res, "delivery": parse_date(text), "lines": lines}


def is_confirm(text: str) -> bool:
    t = f" {norm(text)} "
    return any(f" {norm(w)} " in t for w in
               ["haan pakka", "han pakka", "ha pakka", "pakka", "confirm", "save karo", "save",
                "theek hai save", "done", "yes confirm", "bilkul sahi", "sahi hai", "haan sahi"])


def is_correction(text: str) -> bool:
    toks = norm(text).split()
    return bool(toks) and toks[0] in {norm(w) for w in ["nahi", "nahin", "nai", "no", "galat", "nope", "na"]}


def parse_dispatch(text: str):
    """'ABC ka maal gaya, rickshaw se' -> party + mode."""
    party_res, _ = find_party(text)
    t = f" {norm(text)} "
    mode = None
    for m, words in DISPATCH_MODES.items():
        if any(f" {norm(w)} " in t for w in words):
            mode = m
            break
    return {"party": party_res, "mode": mode}
