"""Rule-based Hinglish order extraction (works with no API key).

Turns "ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena" into
    party_text="abc wale", delivery="kal",
    lines=[{item_text:"sabun", qty_values:[10], unit:"carton"}, ...]
Small talk and pure bargaining clauses (rate, discount, bhav) are dropped, but
a clause with a quantity is kept even if it mentions the rate.
"uski bees peti" uses the item named just before (even in a rate question), and
"agar ... toh das, nahi toh paanch" becomes one line with two quantities (asked).
No LLM is used anywhere: the app keeps working if any AI service goes away.
"""
import re
from datetime import datetime, timedelta, timezone

from .catalog import DISPATCH_MODES, UNITS
from .matcher import find_party, match_item
from .textnorm import WEAK_NUMBER_WORDS, is_size, norm, parse_number_at

IST = timezone(timedelta(hours=5, minutes=30))

_UNIT_WORDS = {norm(w): u for u, ws in UNITS.items() for w in ws}
_ALT_WORDS = {"ya", "or", "yaa", "-", "to", "se"}  # "10 se 12 carton" = 10 or 12: ask
_SPLIT_RE = re.compile(r"[,;!?\n।]|(?<!\d)\.(?!\d)| aur\b| and | plus | phir | fir | uske baad | sath mein | saath mein ")
_BARGAIN = {norm(w) for w in ["rate", "rat", "bhav", "bhaav", "daam", "dam", "price", "discount",
                               "rupay", "rupaye", "rupee", "rs", "percent", "kam", "mehnga",
                               "mahanga", "sasta", "paisa", "paise", "udhaar", "udhar", "payment",
                               "kiraya", "kiraye", "kirae", "bhada", "bhaada", "fare", "rupees"]}
_MONEY = {norm(w) for w in ["rupay", "rupaye", "rupee", "rupees", "rs", "rupya", "paise", "ka kiraya"]}
_STOP = {norm(w) for w in [
    "ko", "ka", "ki", "ke", "wale", "wala", "vale", "vala", "bhai", "ji", "sahab", "bhej", "bhejna",
    "bhejo", "bhejdo", "bhejun", "bhejoon", "bhejdu", "dena", "de", "dijiye", "dijie", "do", "chahiye", "chaiye", "hai", "hain",
    "haan", "han", "ha", "accha", "acha", "theek", "thik", "ok", "okay", "hello", "namaste", "sir",
    "aur", "and", "bhi", "bas", "please", "plz", "order", "likho", "likh", "lo", "le", "lena", "maal",
    "saman", "saamaan", "samaan", "wo", "woh", "vo", "ye", "yeh", "jo", "the", "a", "of", "mein",
    "me", "se", "tak", "to", "ek", "kar", "karna", "karo", "dijiyega", "dedo", "de do", "send",
    "deliver", "delivery", "bhejiye", "pe", "par", "liye", "wahi", "vahi", "same", "naya", "nahi",
    "no", "galat", "sorry", "matlab", "mtlb", "aap", "ap", "hum", "humko", "mujhe", "unko", "ab"]}

# Words that point back to the item said just before ("uski bees peti").
_REF = {norm(w) for w in ["uski", "uska", "uske", "usmein", "usme", "usmen", "isme", "ismein", "ismen",
                          "iski", "iska", "iske", "wahi", "vahi", "wohi", "vohi", "same", "wo", "woh", "vo"]}
# Filler in conditions and questions; never part of an item name.
_FILLER = {norm(w) for w in [
    "agar", "agr", "kuch", "kami", "peshi", "ayi", "aayi", "aaya", "aya", "toh", "tab", "sirf", "bas",
    "warna", "varna", "baaki", "baki", "mere", "mera", "meri", "kya", "kis", "kaisa", "kaise", "kaun",
    "chal", "raha", "rha", "rahi", "hua", "hui", "ho", "gaya", "gayi", "kaam", "cheez", "batao", "bata",
    "achha", "maalik", "malik", "haal", "dekh", "dekho", "lagta", "lage", "lag", "kitna", "kitne",
    "hota", "hoti", "hoga", "hogi", "honge", "rakh", "rakhe", "rakha", "rakho", "keh", "kah", "rahe", "karva",
    "karwa", "denge", "dikat", "dikkat", "bat", "baat", "bol", "dun", "dunga", "jayega", "jayegi", "jaega",
    "puch", "pooch", "bikte", "rehte", "wali", "koi", "apne", "apke", "aapke", "pas", "paas",
    "vahan", "wahan", "yahan", "idhar", "udhar"]}
# A clause that starts like this gives the other quantity for the line before.
_ELSE_STARTS = [norm(w).split() for w in ["nahi toh", "nahi to", "nahin toh", "nahin to", "nahi tho",
                                          "warna", "varna", "ya phir", "ya fir", "otherwise"]]

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


_ASKING = {"kitna", "kitne", "kitni", "kaisa", "kaise", "kaisi", "kaun", "kyun", "kab"}  # question words
_NOT_WORDS = {"nahi", "nahin", "nai", "na", "mat", "not", "no"}


def parse_date(text: str):
    """Returns {"date": "YYYY-MM-DD", "label": "kal", "heard": ...} or None.
    The day said last wins ("aaj order de raha hun, kal bhejna" = kal), and a
    day followed by "nahi" is dropped ("kal nahi parso" = parso)."""
    toks = norm(text).split()
    found = []  # (position, date, label, heard)
    for days, words in _DAY_WORDS.items():
        for w in words:
            ww = norm(w).split()
            for i in range(len(toks) - len(ww) + 1):
                if toks[i:i + len(ww)] == ww:
                    d = today() + timedelta(days=days)
                    label = w if w in ("aaj", "kal", "parso") else {0: "aaj", 1: "kal", 2: "parso"}[days]
                    found.append((i, len(ww), d, label, w))
    for wd, words in _WEEKDAYS.items():
        for w in words:
            ww = norm(w).split()
            for i in range(len(toks) - len(ww) + 1):
                if toks[i:i + len(ww)] == ww:
                    ahead = (wd - today().weekday()) % 7 or 7
                    found.append((i, len(ww), today() + timedelta(days=ahead), words[0], w))
    kept = [f for f in found if not (f[0] + f[1] < len(toks) and toks[f[0] + f[1]] in _NOT_WORDS)]
    vague = {i for i in range(len(toks) - 1) if toks[i] in _KAL and toks[i + 1] in _PARSO}
    kept = [f for f in kept if f[0] not in vague and f[0] - 1 not in vague]  # "kal parso" = some day soon
    kept = [f for f in kept if f[4] not in _NOW or _SEND & set(toks[f[0] + 1:f[0] + 4])]
    if not kept:
        return None
    _, _, d, label, heard = max(kept, key=lambda f: f[0])
    return {"date": d.isoformat(), "label": label, "heard": heard}


_KAL = {norm(w) for w in _DAY_WORDS[1]}
_PARSO = {norm(w) for w in _DAY_WORDS[2]}
_NOW = {"abhi", "turant"}  # "abhi yahan rakha hai" is talk; "abhi bhej do" is a day
_SEND = {norm(w) for w in ["bhej", "bhejo", "bhejna", "bhejdo", "bhijwa", "bhijwado", "bhejiye", "chahiye", "chaiye",
                            "nikal", "nikalo", "dispatch", "de", "dena", "dedo", "do", "chahie"]}
_DATE_TOKENS = {norm(w) for ws in list(_DAY_WORDS.values()) + list(_WEEKDAYS.values()) for w in ws}


def _tokens(text):
    t = norm(text)
    t = re.sub(r"(\d)\s*-\s*(\d)", r"\1 ya \2", t)
    return t.split()  # norm already splits "10carton" and keeps sizes ("1inch") whole


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
    return [t for t in toks if t not in _STOP and t not in _DATE_TOKENS and t not in _UNIT_WORDS
            and t not in _FILLER and t not in _REF and t not in _BARGAIN]


def _named_item(toks, party_tokens):
    """The catalog item a clause clearly names ("Amul ghee kya rate chal raha hai"), else None."""
    words = _clean_item([t for t in toks if t not in party_tokens])
    if not words:
        return None
    m = match_item(" ".join(words))
    return words if m["status"] in ("ok", "choose") else None


def _starts_with_else(toks):
    return any(toks[:len(w)] == w for w in _ELSE_STARTS)


def _condition(toks):
    """'agar sasta rate chal raha hai toh ...' -> 'agar sasta rate chal raha hai'."""
    if "agar" not in toks and "agr" not in toks:
        return None
    i = toks.index("agar") if "agar" in toks else toks.index("agr")
    j = next((k for k in range(i + 1, len(toks)) if toks[k] in ("toh", "to", "tab")), len(toks))
    words = [t for t in toks[i:j] if t not in ("agar", "agr")] or toks[i:j]
    return "agar " + " ".join(dict.fromkeys(words))


def _parties_named(clauses):
    """Every party named clearly in the clauses, in order ("ABC ko ..., Gupta ko ...")."""
    found = []
    for clause in clauses:
        res, _ = find_party(clause)
        if res["status"] == "ok" and res["party"]["code"] not in [p["code"] for p in found]:
            found.append(res["party"])
    return found


_MODE_WORDS = {norm(w) for ws in DISPATCH_MODES.values() for w in ws}
LONG_CALL = 40  # words: a whole phone call, not one spoken order


def _model_numbers(toks):
    """Positions of numbers that finish an item name ("Mini Champ 1", "Win Plus 2"):
    the words before it plus the number name one item, and that name has the number."""
    out = set()
    for i, t in enumerate(toks):
        if not re.fullmatch(r"\d+", t) or i == 0 or (i + 1 < len(toks) and toks[i + 1] in _UNIT_WORDS):
            continue
        words = [w for w in _clean_item(toks[max(0, i - 4):i]) if not re.fullmatch(r"[\d.]+", w)]
        if not words or not any(ch.isalpha() for w in words for ch in w):
            continue
        m = match_item(" ".join(words + [t]))
        if m["status"] == "ok" and t in norm(m["item"]["name"]).split():
            out.add(i)
    return out


def _call_talk(item):
    """In a long call, a 'line' with no item, a sentence for an item ('chaar bundle aap bhi
    rakh lo apke to bikte rehte honge') or only a vehicle ('chhah bundle ka ek rickshaw')
    that matches nothing on the list is conversation. Short new names ('pachas motor')
    stay, so staff can add them with 'Naya item banao'."""
    if not item or all(t in _MODE_WORDS for t in item):
        return True
    return len(item) > 3 and match_item(" ".join(item))["status"] == "unknown"


def extract_rules(text: str):
    long_call = len(norm(text).split()) > LONG_CALL
    party_res, party_phrase = find_party(text)
    party_tokens = set(party_phrase.split()) if party_phrase else set()
    clauses = _SPLIT_RE.split(f" {text} ")
    named = _parties_named(clauses)
    two_parties = len(named) > 1
    if two_parties:  # one order is for one party: ask, never merge them silently
        party_res = {"status": "choose", "party": None, "options": named}
        party_tokens = {t for p in named for t in norm(p["name"]).split()} | party_tokens
    lines, last_item = [], None
    for clause in clauses:
        toks = _tokens(clause)
        if not toks:
            continue
        # find quantity spans; each starts a new line
        spans, i = [], 0
        model_nos = _model_numbers(toks)
        while i < len(toks):
            if i in model_nos:  # "mini champ 1": part of the name
                i += 1
                continue
            q = _read_qty(toks, i)
            if q and q["end"] < len(toks) and toks[q["end"]] in _MONEY:
                i = q["end"] + 1  # "dhai sau rupaye": a price, not 250 of something
                continue
            if q:
                spans.append((i, q))
                i = q["end"]
            else:
                i += 1
        if not spans:
            # no quantity: rate questions and small talk are not lines, but remember the item they name
            named_item = _named_item(toks, party_tokens)
            last_item = named_item or last_item
            # "ABC ko Lux bhejna kal": an item with no quantity is a line, and the app asks "kitna?"
            # only a clearly named item: a generic word alone ("dal rahe ho" is the verb daalna) is talk
            if named_item and match_item(" ".join(named_item))["status"] == "ok" and not _is_bargain(toks) \
                    and not (_QUESTION_WORDS | _ASKING | _NOT_WORDS) & set(toks) and not _already_listed(named_item, lines):
                lines.append({"heard": " ".join(toks), "item_text": " ".join(named_item),
                              "qty_values": [], "unit": None, "note": None})
            continue
        if _is_bargain(toks) and not _condition(toks) and not any(
                _clean_item(toks[q["end"]:]) or _REF & set(toks) for _, q in spans):
            continue  # "das rupay kam karo": a price, not an order
        # "..., nahi toh sirf paanch peti" -> second quantity for the line before
        if lines and _starts_with_else(toks) and len(spans) == 1:
            q = spans[0][1]
            if not _clean_item(toks[q["end"]:]) and not _clean_item(toks[:spans[0][0]]):
                prev = lines[-1]
                prev["qty_values"] = list(dict.fromkeys(prev["qty_values"] + q["values"]))
                prev["unit"] = prev["unit"] or q["unit"]
                prev["heard"] += " / " + " ".join(toks)
                continue
        cond = _condition(toks)
        for n, (start, q) in enumerate(spans):
            stop = spans[n + 1][0] if n + 1 < len(spans) else len(toks)
            after = [t for t in toks[q["end"]:stop] if t not in party_tokens]
            item = _clean_item(after)
            before = _clean_item([t for t in toks[:start] if t not in party_tokens]) if n == 0 else []
            if not item and n == 0:  # "sabun 10 carton" (item said first)
                item = before
            elif before and any(is_size(t) for t in before) and match_item(" ".join(item))["status"] != "ok":
                item = before + item  # "pipe teen inch ke paanch heavy", "3 inch ke 5 pipe": one item
            if not item and last_item and (_REF & set(toks) or cond):  # "uski bees peti": the item said before
                item = list(last_item)
            elif item:
                last_item = item
            # "advertisement kitna pada hoga": a question about something not on the list is talk, not an order
            if item and (_QUESTION_WORDS | _ASKING) & set(toks) and match_item(" ".join(item))["status"] != "ok":
                continue
            # "saadhe teen sau to vahan se kiraya lagega": fare or price talk about nothing on the list
            if _is_bargain(toks) and match_item(" ".join(item))["status"] not in ("ok", "choose"):
                continue
            if long_call and _call_talk(item):
                continue
            lines.append({
                "heard": " ".join(toks[start:stop]) if item else " ".join(toks),
                "item_text": " ".join(item),
                "qty_values": q["values"],
                "unit": q["unit"],
                "note": cond,
            })
    # an item named first and given a quantity later ("Parle-G ... usmein das peti") is one line
    lines = [ln for n, ln in enumerate(lines)
             if ln["qty_values"] or not _already_listed(ln["item_text"].split(), [x for x in lines if x["qty_values"]])]
    return {"party": party_res, "delivery": parse_date(text), "lines": lines, "two_parties": two_parties}


def _already_listed(words, lines):
    """The same item already has a line (a call often names it again without a quantity)."""
    code = (match_item(" ".join(words)).get("item") or {}).get("code")
    return bool(code) and any((match_item(ln["item_text"]).get("item") or {}).get("code") == code for ln in lines)


_CONFIRM_PHRASES = ["haan pakka", "han pakka", "ha pakka", "pakka", "confirm", "save karo", "save",
                    "theek hai save", "done", "yes confirm", "bilkul sahi", "sahi hai", "haan sahi"]
_QUESTION_WORDS = {"kya", "kyaa", "kyun", "?"}


def is_confirm(text: str) -> bool:
    """'haan pakka' saves. 'pakka nahi', 'save mat karo', 'sahi hai kya' never do."""
    raw = text or ""
    t = f" {norm(raw)} "
    toks = t.split()
    if not any(f" {norm(w)} " in t for w in _CONFIRM_PHRASES):
        return False
    if _NOT_WORDS & set(toks) or {"ruko", "wait", "abhi nahi"} & set(toks):
        return False
    if raw.strip().endswith("?") or _QUESTION_WORDS & set(toks):
        return False
    return True


def is_correction(text: str) -> bool:
    toks = norm(text).split()
    return bool(toks) and toks[0] in {norm(w) for w in ["nahi", "nahin", "nai", "no", "galat", "nope", "na"]}


_ORDER_WORDS = {norm(w) for w in ["order", "ordar", "ardar", "aardar", "odar", "orderno", "parchi", "bill"]}
_NUMBER_WORDS = {norm(w) for w in ["number", "nambar", "nanbar", "numbar", "no", "num", "kramank"]}
_CANCEL_WORDS = {norm(w) for w in ["cancel", "kainsal", "kensal", "rehne do", "chhodo", "ruko", "mat bhejo"]}


_JOIN_WORDS = {norm(w) for w in ["aur", "or", "and", "ar", "va", "tatha", "bhi", "comma"]}
_COUNT_WORDS = {norm("dono"): 2, norm("donon"): 2, norm("teeno"): 3, norm("tinon"): 3, norm("tino"): 3,
                norm("charon"): 4, norm("charo"): 4, norm("paancho"): 5, norm("panchon"): 5}


def _numbers_from(toks, j):
    """Read '3 4 aur 5' starting at toks[j]. Small number words ("ek", "do")
    only count right after a joining word, so "5 ek hi truck" stops at 5."""
    out, after_join = [], True
    while j < len(toks):
        t = toks[j]
        if t in _JOIN_WORDS:
            after_join, j = True, j + 1
            continue
        if t in _NUMBER_WORDS:
            j += 1
            continue
        if not after_join and not t.isdigit() and t in WEAK_NUMBER_WORDS:
            break
        v, used = parse_number_at(toks, j)
        if not isinstance(v, int) or v <= 0:
            break
        out.append(v)
        after_join, j = False, j + used
    return out


def find_order_numbers(text: str):
    """'order 3, 4 aur 5 teeno' -> {"numbers": [3, 4, 5], "count": 3}.
    '6 number wala' -> [6]. No order number -> numbers == []."""
    toks = norm(text.replace("#", " number ").replace(",", " aur ")).split()
    count = next((_COUNT_WORDS[t] for t in toks if t in _COUNT_WORDS), None)
    for i, t in enumerate(toks):
        if t in _ORDER_WORDS or t in _NUMBER_WORDS:
            nums = _numbers_from(toks, i + 1)
            if nums:
                return {"numbers": list(dict.fromkeys(nums)), "count": count}
        if t in _NUMBER_WORDS and i > 0:  # "6 number wala"
            v, _ = parse_number_at(toks, i - 1)
            if isinstance(v, int) and v > 0:
                return {"numbers": [v], "count": count}
    return {"numbers": [], "count": count}


def find_order_number(text: str):
    nums = find_order_numbers(text)["numbers"]
    return nums[0] if nums else None


def split_joined_number(n: int, open_ids, count=None):
    """Speech-to-text often joins "3, 4, 5" into 345. Return the ways to cut the
    digits into open order ids (each order once), keeping only `count` parts if known."""
    digits, ids, found = str(n), {str(i) for i in open_ids}, []

    def walk(rest, parts):
        if not rest:
            if len(parts) > 1 and (count is None or len(parts) == count):
                found.append([int(p) for p in parts])
            return
        for k in range(1, len(rest) + 1):
            head = rest[:k]
            if head in ids and head not in parts:
                walk(rest[k:], parts + [head])

    walk(digits, [])
    return found


def is_leave_it(text: str) -> bool:
    """'rehne do', 'chhodo', 'cancel': change nothing."""
    t = f" {norm(text)} "
    return any(f" {w} " in t for w in _CANCEL_WORDS)


def quantities_in(text: str):
    """Numbers that are really quantities: a small word like "do" or "ek" only
    counts before a unit ("do carton"), so "rehne do" is not 2."""
    toks = _tokens(text)
    out, i = [], 0
    while i < len(toks):
        v, used = _is_qty_start(toks, i)
        if v is None:
            i += 1
            continue
        out.append(v)
        i += used
    return out


def is_cancel(text: str) -> bool:
    t = f" {norm(text)} "
    return is_correction(text) or any(f" {w} " in t for w in _CANCEL_WORDS)


def parse_dispatch(text: str):
    """'ABC ka maal gaya, rickshaw se' -> party + mode."""
    party_res, _ = find_party(text)
    t = f" {norm(text)} "
    mode = None
    for m, words in DISPATCH_MODES.items():
        if any(f" {norm(w)} " in t for w in words):
            mode = m
            break
    nums = find_order_numbers(text)
    return {"party": party_res, "mode": mode, "order_nos": nums["numbers"], "count": nums["count"]}
