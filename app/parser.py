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
from datetime import date, datetime, timedelta, timezone

from .catalog import DISPATCH_MODES, UNITS
from .matcher import find_party, is_item_word, match_item
from .textnorm import WEAK_NUMBER_WORDS, WORD_TO_NUM, is_size, norm, parse_number_at

IST = timezone(timedelta(hours=5, minutes=30))

_UNIT_WORDS = {norm(w): u for u, ws in UNITS.items() for w in ws}
_ALT_WORDS = {"ya", "or", "yaa", "-", "to", "se"}  # "10 se 12 carton" = 10 or 12: ask
_SPLIT_RE = re.compile(r"[,;!?\n।]|(?<!\d)\.(?!\d)| aur\b| and | plus | phir | fir | uske baad | sath mein | saath mein | te ")  # "te" = Punjabi "and"
_BARGAIN = {norm(w) for w in ["rate", "rat", "bhav", "bhaav", "daam", "dam", "price", "discount",
                               "rupay", "rupaye", "rupee", "rs", "percent", "kam", "mehnga",
                               "mahanga", "sasta", "paisa", "paise", "udhaar", "udhar", "payment",
                               "kiraya", "kiraye", "kirae", "bhada", "bhaada", "fare", "rupees"]}
_MONEY = {norm(w) for w in ["rupay", "rupaye", "rupee", "rupees", "rs", "rupya", "paise", "inr"]}
# A number right before these is a price: "paanch sau ka rate", "490 lagega", "500 ka padega".
_PRICE_AFTER = {norm(w) for w in ["rate", "bhav", "bhaav", "daam", "price", "lagega", "lagegi", "padega", "padegi",
                                   "lagta", "padta", "chal", "rupay", "rupaye", "rupee", "rs"]}
_PRICE_BEFORE = {norm(w) for w in ["rate", "bhav", "bhaav", "daam", "price", "rs"]}
# "4 ya 5 din mein": a delivery time, not 4 of something
_TIME_AFTER = {norm(w) for w in ["din", "dino", "dinon", "days", "day", "hafte", "hafta", "ghante", "ghanta",
                                  "mahine", "mahina", "minute", "minat", "baje"]}
# "ek peti ke andar baarah hote hain": how many come in a pack, not an order
_PACK_WORDS = {norm(w) for w in ["andar", "hote", "hota", "hoti", "aate", "aati"]}  # not "aata": that is atta
_ITEM_COUNT_WORDS = {norm(w) for w in ["item", "items", "aitem", "cheez", "cheezein", "cheeze", "chizen", "saman",
                                        "line", "lines", "naam"]}
_TOTAL_WORDS = {norm(w) for w in ["total", "kul", "milake", "milakar", "mila ke"]}
_CHANGE_WORDS = [norm(p).split() for p in ["kar dijiye", "kar dijie", "kar do", "kar dena", "kar dijiyega", "karo",
                                          "kariye", "kar lijiye", "kar dete", "kardo", "kardijiye"]]
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
    "puch", "pooch", "bikte", "rehte", "wali", "koi", "apne", "apke", "aapke", "pas", "paas", "padegi", "padega", "lagega", "lagegi", "padta", "kam", "jayenge", "jaenge", "jayengi", "dono", "donon", "tino", "tinon",
    "vahan", "wahan", "yahan", "idhar", "udhar"]}
# A clause that starts like this gives the other quantity for the line before.
_ELSE_STARTS = [norm(w).split() for w in ["nahi toh", "nahi to", "nahin toh", "nahin to", "nahi tho",
                                          "warna", "varna", "ya phir", "ya fir", "otherwise"]]

_DAY_WORDS = {
    0: ["aaj", "aj", "today", "abhi", "turant"],
    1: ["kal", "tomorrow", "kl"],
    2: ["parso", "parson", "parsoon", "parason", "parsom", "day after", "day after tomorrow"],  # परसों -> "parason"
}
_WEEKDAYS = {0: ["somvar", "monday"], 1: ["mangalvar", "mangal", "tuesday"],
             2: ["budhvar", "budh", "wednesday"], 3: ["guruvar", "veervar", "thursday"],
             4: ["shukravar", "shukra", "friday"], 5: ["shanivar", "shani", "saturday"],
             6: ["ravivar", "itvaar", "itwar", "sunday"]}


def today():
    return datetime.now(IST).date()


_ASKING = {"kitna", "kitne", "kitni", "kaisa", "kaise", "kaisi", "kaun", "kyun", "kab"}  # question words
_NOT_WORDS = {"nahi", "nahin", "nai", "na", "mat", "not", "no"}


_TARIKH = {norm(w) for w in ["tarikh", "tareekh", "tarik", "tariq"]}  # not "date": that is also the fruit
_ORDINAL = {"th", "nd", "rd"}  # "5th ko", "22nd tak" ("1st" is read as a pump stage, so not here)
_MONTHS = {}
for _m, _ws in enumerate([["january", "jan", "janvari", "janwari"], ["february", "feb", "farvari", "farwari"],
                          ["march"], ["april", "aprail"], [], ["june", "jun"], ["july", "julai"],
                          ["august", "aug", "agast"], ["september", "sept", "sitambar"],
                          ["october", "oct", "aktubar", "oktober"], ["november", "nov", "navambar", "nawambar"],
                          ["december", "dec", "disambar", "december"]], 1):  # "may" / "mai" is also "I"
    for _w in _ws:
        _MONTHS[norm(_w)] = _m


def _day_of_month(toks, i):
    """'3 tarikh', '15 tareekh', '3 december', 'teen tarikh ko' -> (date, label, tokens used) or None."""
    v, used = parse_number_at(toks, i)
    if not isinstance(v, int) or not 1 <= v <= 31 or i + used >= len(toks):
        return None
    nxt = toks[i + used]
    t = today()
    try:
        if nxt in _MONTHS:
            d = date(t.year, _MONTHS[nxt], v)
            if d < t:
                d = date(t.year + 1, _MONTHS[nxt], v)
            return d, f"{v} {d.strftime('%b')}", used + 1
    except ValueError:  # "30 february"
        return None
    if nxt in _TARIKH or (nxt in _ORDINAL and toks[i].isdigit()):
        y, m = t.year, t.month
        if v < t.day:  # "3 tarikh" on the 28th = the 3rd of next month
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        for _ in range(3):  # "31 tarikh" in a 30-day month = the next month that has a 31st
            try:
                return date(y, m, v), f"{v} tarikh", used + 1
            except ValueError:
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def date_spans(toks):
    """Token positions of '3 tarikh' / '3 december' (a date, never a quantity)."""
    out, i = [], 0
    while i < len(toks):
        r = _day_of_month(toks, i)
        if r:
            out.append((i, r))
            i += r[2]
        else:
            i += 1
    return out


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
    for i, (d, label, used) in date_spans(toks):
        found.append((i, used, d, label, " ".join(toks[i:i + used])))
    # "day after tomorrow": the long match wins over the "tomorrow" inside it
    found = [f for f in found if not any(g[1] > f[1] and g[0] <= f[0] and f[0] + f[1] <= g[0] + g[1] for g in found)]

    def dropped(f):  # "kal nahi parso": kal goes; "kal, nahi nahi 12" is about the quantity, kal stays
        k = f[0] + f[1]
        if k >= len(toks) or toks[k] not in _NOT_WORDS:
            return False
        while k < len(toks) and toks[k] in _NOT_WORDS:
            k += 1
        return k >= len(toks) or parse_number_at(toks, k)[0] is None
    kept = [f for f in found if not dropped(f)]
    vague = {i for i in range(len(toks) - 1) if toks[i] in _KAL and toks[i + 1] in _PARSO}
    kept = [f for f in kept if f[0] not in vague and f[0] - 1 not in vague]  # "kal parso" = some day soon
    kept = [f for f in kept if f[4] not in _NOW or _SEND & set(toks[max(0, f[0] - 3):f[0] + 4])]
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


def _tokens(text, collapse=True):
    t = norm(text)
    t = re.sub(r"(\d)\s*-\s*(\d)", r"\1 ya \2", t)
    toks = t.split()
    # "do do katte", "chaar chaar kar dijiye", "do-do peti": a number said twice is said once
    toks = [w for k, w in enumerate(toks) if not (k > 0 and w == toks[k - 1] and (w.isdigit() or w in WORD_TO_NUM))]
    for i, (_, _, used) in reversed(date_spans(toks)):  # "3 tarikh" is the delivery day, not 3 of an item
        del toks[i:i + used]
    i = 0
    while collapse and i < len(toks):  # "10 carton nahi 12 carton Lux": only the second quantity counts
        q1 = _read_qty(toks, i)
        k = q1["end"] if q1 else -1
        j = _fix_markers(toks, k) if q1 and k < len(toks) and toks[k] in _NOT_WORDS else k
        if q1 and len(q1["values"]) == 1 and j > k and j < len(toks) and _read_qty(toks, j):
            del toks[i:j]
            continue
        i += 1
    return toks  # norm already splits "10carton" and keeps sizes ("1inch") whole


def _is_qty_start(toks, i):
    v, used = parse_number_at(toks, i)
    if v is None:
        return None, 0
    if toks[i] in WEAK_NUMBER_WORDS and used == 1:
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        v2, u2 = parse_number_at(toks, i + 1)
        rng = isinstance(v, int) and isinstance(v2, int) and v < v2 <= 2 * v + 2 and u2 == 1 and nxt.isalpha() \
            and i + 2 < len(toks) and toks[i + 2] in _UNIT_WORDS  # "teen chaar carton": 3 or 4
        if nxt in ("kar", "karo", "kardo", "kardijiye"):  # "toor dal teen kar do"
            rng = True
        if nxt not in _UNIT_WORDS and not rng:  # "bhej do", "ek minute" are not quantities
            return None, 0
    return v, used


def _read_qty(toks, i):
    """Quantity at i, with optional alternative ('10 ya 12') and unit."""
    v, used = _is_qty_start(toks, i)
    if v is None:
        return None
    vals, j = [v], i + used
    # "dus bara carton", "paanch-chhe peti": two numbers side by side are a range: ask which
    v2, u2 = parse_number_at(toks, j)
    if v2 is not None and u2 == 1 and isinstance(v, int) and isinstance(v2, int) and v < v2 <= 2 * v + 2 \
            and toks[j].isalpha() and toks[i].isalpha():
        vals.append(v2)
        j += 1
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


_FIX_WORDS = {norm(w) for w in ["sorry", "wait", "actually", "galti", "galat", "matlab", "sori"]}


def _fix_markers(toks, k):
    """Index after a run of correction words at k ("nahi nahi", "no wait", "sorry"), or k if none."""
    j = k
    while j < len(toks) and (toks[j] in _NOT_WORDS or toks[j] in _FIX_WORDS):
        j += 1
    return j


def _inline_fix(toks):
    """'10 nahi 12' / '10 carton nahi 12 carton' / 'nahi nahi, 12' / 'sorry 12 carton' /
    'no wait, 12' said right after a line: the quantity of the line before changes.
    Returns the new quantity, or None."""
    k = next((n for n, t in enumerate(toks) if t in _NOT_WORDS or t in _FIX_WORDS), None)
    if k is None:
        return None
    if k > 0:
        q1 = _read_qty(toks, 0)
        if not q1 or q1["end"] != k:
            return None
    j = _fix_markers(toks, k)
    if j == len(toks):
        return None
    q2 = _read_qty(toks, j)
    if not q2 or q2["end"] != len(toks) or len(q2["values"]) != 1:
        return None
    return q2


def _item_swap(toks, lines):
    """'Lux nahi Dettol' / 'Lux nahi, Dettol' right after a Lux line: that line's item changes."""
    k = next((n for n, t in enumerate(toks) if t in _NOT_WORDS), None)
    if not k or not lines:
        return None
    old, new = _clean_item(toks[:k]), _clean_item(toks[_fix_markers(toks, k):])
    if not old or not new or any(parse_number_at(toks, n)[0] is not None for n in range(len(toks))):
        return None
    was, now = match_item(" ".join(old)), match_item(" ".join(new))
    prev = match_item(lines[-1]["item_text"])
    if was["status"] == "ok" and now["status"] == "ok" and prev["item"] and prev["item"]["code"] == was["item"]["code"]:
        return new
    return None


def stated_quantities(text: str):
    """Quantities said along with an answer ("Lux, 12 carton", "Lux 12"): a number with a
    unit, or in digits. "Lux de do" (the verb) and "second one" (which one) give none."""
    toks, out, i = _tokens(text), [], 0
    while i < len(toks):
        q = _read_qty(toks, i)
        if q and (q["unit"] or toks[i].isdigit()):
            out += q["values"]
            i = q["end"]
        else:
            i += 1
    return out


def _is_bargain(toks):
    return any(t in _BARGAIN for t in toks) or any("₹" in t for t in toks)


def _clean_item(toks):
    return [t for t in toks if t not in _STOP and t not in _DATE_TOKENS and t not in _UNIT_WORDS
            and (t not in _FILLER or is_item_word(t)) and t not in _REF and t not in _BARGAIN]


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


def _not_an_order_number(toks, i, q, long_call):
    """A price ("paanch sau ka rate", "490 lagega"), a delivery time ("4 ya 5 din mein")
    or, in a long call, a pack size ("ek peti ke andar baarah hote hain"), a variant
    ("das kilo wale") or a price said with no unit ("chaar sau nabbe chal raha hai")."""
    after = [t for t in toks[q["end"]:q["end"] + 3] if t not in ("ka", "ke", "ki", "hi", "to")]
    if after and after[0] in _PRICE_AFTER and not q["unit"]:
        return True
    if i > 0 and toks[i - 1] in _PRICE_BEFORE and not q["unit"]:
        return True
    if q["end"] < len(toks) and toks[q["end"]] in _TIME_AFTER:
        return True
    if not long_call:
        return False
    window = []
    for t in toks[q["end"]:q["end"] + 5]:  # up to the next number: "ek carton mein kitne Parle G hote hain"
        if window and parse_number_at([t], 0)[0] is not None and t not in WEAK_NUMBER_WORDS:
            break
        window.append(t)
    if _PACK_WORDS & set(window) or _PACK_WORDS & set(toks[max(0, i - 2):i]):  # "48 hote hain", "andar baarah"
        return True
    if q["end"] < len(toks) and toks[q["end"]] in ("wala", "wale", "vala", "vale", "wali", "vali"):
        return True
    return not q["unit"] and max(q["values"]) >= 100


_CHANGE_FILLER = {norm(w) for w in ["kar", "dijiye", "dijie", "do", "dena", "dijiyega", "karo", "kariye", "lijiye",
                                     "dete", "kardo", "kardijiye", "ek", "kaam", "aap", "ap", "bhai", "ji", "haan",
                                     "sir", "phir", "fir", "to", "na", "bas", "hi"]}


def _change_said(toks):
    """'chaar chaar kar dijiye' / 'paanch kar do': a new quantity for the line just said."""
    return any(toks[k:k + len(p)] == p for p in _CHANGE_WORDS for k in range(len(toks)))


_VARIANT_WORDS = {norm(w) for w in ["pink", "yellow", "pila", "peela", "laal", "lal", "red", "hara", "green", "blue",
                                    "nila", "neela", "kala", "safed", "white", "black", "bada", "bade", "chhota",
                                    "chhote", "medium", "small", "large", "alag", "deluxe", "premium", "sasta",
                                    "mehenga", "mehnga", "wala", "wale", "wali", "vala", "vale", "se", "bhi"]}
_ADD_WORDS = {norm(w) for w in ["aur", "bhi", "alag", "extra", "add", "plus", "upar"]}


_DROP_PHRASES = [norm(p).split() for p in ["rehne do", "rahne do", "rehne dijiye", "mat bhejo", "mat bhejna",
                                           "nahi chahiye", "nahin chahiye", "cancel", "hata do", "hatao", "chhod do"]]


def _dropped_item(raw, lines):
    """'Dettol rehne do': the line for that item goes, and nothing new is added."""
    for p in _DROP_PHRASES:
        k = next((k for k in range(len(raw) - len(p) + 1) if raw[k:k + len(p)] == p), None)
        if k is None:
            continue
        words = _clean_item(raw[:k])
        code = (match_item(" ".join(words)).get("item") or {}).get("code") if words else None
        if code:
            lines[:] = [ln for ln in lines if (match_item(ln["item_text"]).get("item") or {}).get("code") != code]
            return True
    return False


def _fills_unnamed(item, q, lines):
    last = lines[-1]
    if not item or match_item(" ".join(item))["status"] != "ok":
        return False
    if match_item(last["item_text"])["status"] == "ok" if last["item_text"] else False:
        return False
    if last["qty_values"] == q["values"] and (q["unit"] or last["unit"]) == (last["unit"] or q["unit"]):
        last["item_text"] = " ".join(item)
        last["unit"] = last["unit"] or q["unit"]
        return True
    return False


def _update_named(item, q, lines):
    code = (match_item(" ".join(item)).get("item") or {}).get("code")
    target = next((ln for ln in reversed(lines) if code and ln["qty_values"]
                   and (match_item(ln["item_text"]).get("item") or {}).get("code") == code), None)
    if target is None or len(q["values"]) != 1:
        return False
    target["qty_values"] = q["values"]
    target["unit"] = q["unit"] or target["unit"]
    return True


def _echo_of(item, q, lines):
    code = (match_item(" ".join(item)).get("item") or {}).get("code")
    if not code:
        return False
    for ln in lines:
        if ln["qty_values"] == q["values"] and (match_item(ln["item_text"]).get("item") or {}).get("code") == code:
            ln["said_at"] = _next_said(lines)  # "total baarah" after the echo goes to this line
            return True
    return False


def _next_said(lines):
    return 1 + max([x.get("said_at", 0) for x in lines] + [0])


def _last_said(lines):
    """The line talked about last: the newest one, or one repeated back after it."""
    return max(lines, key=lambda ln: (ln.get("said_at", 0), lines.index(ln)))


def _call_talk(item):
    """In a long call, a 'line' with no item, a sentence for an item ('chaar bundle aap bhi
    rakh lo apke to bikte rehte honge') or only a vehicle ('chhah bundle ka ek rickshaw')
    that matches nothing on the list is conversation. Short new names ('pachas motor')
    stay, so staff can add them with 'Naya item banao'."""
    if not item or all(t in _MODE_WORDS for t in item):
        return True
    if len(item) == 1 and len(item[0]) <= 3 and match_item(item[0])["status"] != "ok":
        return True  # "baarah can", "12 gaye": an echo, not a new item
    return len(item) > 3 and match_item(" ".join(item))["status"] == "unknown"


def extract_rules(text: str, call: bool = False):
    """call=True for an uploaded recording or a pasted call transcript; a long one is
    full of talk. A spoken or typed order keeps every line and asks about it."""
    # a whole call: many words, or many turns (Sarvam puts each speaker turn on its own line)
    long_call = call and (len(norm(text).split()) > LONG_CALL or text.count("\n") >= 6)
    party_res, party_phrase = find_party(text)
    party_tokens = set(party_phrase.split()) if party_phrase else set()
    clauses = _SPLIT_RE.split(f" {text} ")
    named = _parties_named(clauses)
    two_parties = len(named) > 1
    if two_parties:  # one order is for one party: ask, never merge them silently
        party_res = {"status": "choose", "party": None, "options": named}
        party_tokens = {t for p in named for t in norm(p["name"]).split()} | party_tokens
    lines, last_item, fix_next = [], None, False
    for clause in clauses:
        toks = _tokens(clause)
        if not toks:
            continue
        raw = _tokens(clause, collapse=False)
        if long_call and _dropped_item(raw, lines):  # "Dettol rehne do", "Tide mat bhejo"
            continue
        if long_call and _TOTAL_WORDS & set(raw) and lines:
            # "to chhah se total baarah ho gaye": the line before now comes to the total
            nums = [v for v in (parse_number_at(raw, k)[0] for k in range(len(raw))) if v is not None]
            k_total = next(k for k, t in enumerate(raw) if t in _TOTAL_WORDS)
            after = [v for v in (parse_number_at(raw, k)[0] for k in range(k_total + 1, len(raw))) if v is not None]
            counting_items = _ITEM_COUNT_WORDS & set(raw)  # "total do item ho gaye" counts lines, not cartons
            named_code = (match_item(" ".join(_clean_item(raw))).get("item") or {}).get("code") if _clean_item(raw) else None
            last = next((ln for ln in lines if named_code and
                         (match_item(ln["item_text"]).get("item") or {}).get("code") == named_code), None)
            order_total = after and len(lines) > 1 and after[0] == sum(max(ln["qty_values"] or [0]) for ln in lines)
            last = last or (None if order_total else _last_said(lines))  # "total sattais carton" = the whole order
            if last and after and last["item_text"] and isinstance(after[0], int) and not counting_items \
                    and max(last["qty_values"] or [0]) <= after[0] <= 9999:  # a total is never less
                last["qty_values"] = [after[0]]
                last["heard"] += " / " + " ".join(raw)
            if nums:
                continue
        if long_call and lines and _change_said(raw) and not _clean_item(
                [t for t in raw if t not in _CHANGE_FILLER and parse_number_at(raw, raw.index(t))[0] is None]):
            k = next((k for k in range(len(raw)) if _read_qty(raw, k)), None)
            q = _read_qty(raw, k) if k is not None else None
            if q and len(q["values"]) == 1 and not _not_an_order_number(raw, k, q, True):
                target = next((ln for ln in reversed(lines) if ln["item_text"] and ln["qty_values"]), None)
                if target:  # "do do katte Aashirvaad ... ek kaam kariye, chaar chaar kar dijiye"
                    target["qty_values"] = q["values"]
                    target["unit"] = q["unit"] or target["unit"]
                    target["heard"] += " / " + " ".join(raw)
                    continue
        if raw and lines and _fix_markers(raw, 0) == len(raw):  # "no wait," / "nahi nahi," then the right quantity
            fix_next = True
            continue
        if fix_next and lines:
            fix_next = False
            q = _read_qty(raw, 0)
            if q and q["end"] == len(raw) and len(q["values"]) == 1:
                lines[-1]["qty_values"] = q["values"]
                lines[-1]["unit"] = q["unit"] or lines[-1]["unit"]
                lines[-1]["heard"] += " / " + " ".join(raw)
                continue
        swap = _item_swap(raw, lines)
        if swap:  # "10 carton Lux, Lux nahi Dettol": the line before is Dettol
            lines[-1]["item_text"] = " ".join(swap)
            lines[-1]["heard"] += " / " + " ".join(raw)
            continue
        fix = _inline_fix(raw) if lines else None
        if fix:  # "10 carton Lux, 10 nahi 12": the line before is 12, no new line
            lines[-1]["qty_values"] = fix["values"]
            lines[-1]["unit"] = fix["unit"] or lines[-1]["unit"]
            lines[-1]["heard"] += " / " + " ".join(toks)
            continue
        # find quantity spans; each starts a new line
        spans, skipped, i = [], [], 0
        model_nos = _model_numbers(toks)
        while i < len(toks):
            if i in model_nos:  # "mini champ 1": part of the name
                i += 1
                continue
            q = _read_qty(toks, i)
            if q and ((q["end"] < len(toks) and toks[q["end"]] in _MONEY) or (i > 0 and toks[i - 1] in _MONEY)):
                i = q["end"] + 1  # "dhai sau rupaye": a price, not 250 of something
                continue
            if q and _not_an_order_number(toks, i, q, long_call):
                skipped.append(i)  # still ends the item name of the line before
                i = q["end"]
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
            stop = min([stop] + [k for k in skipped if k > start])
            after = [t for t in toks[q["end"]:stop] if t not in party_tokens]
            item = _clean_item(after)
            before = _clean_item([t for t in toks[:start] if t not in party_tokens]) if n == 0 else []
            if not item and n == 0:  # "sabun 10 carton" (item said first)
                item = before
            elif before and any(is_size(t) for t in before) and match_item(" ".join(item))["status"] != "ok":
                item = before + item  # "pipe teen inch ke paanch heavy", "3 inch ke 5 pipe": one item
            if not item and last_item and (_REF & set(toks) or (cond and not long_call)):  # "uski bees peti": the item said before
                item = list(last_item)
            elif item:
                last_item = item
            # "advertisement kitna pada hoga": a question about something not on the list is talk, not an order
            if item and (_QUESTION_WORDS | _ASKING) & set(toks) and match_item(" ".join(item))["status"] != "ok":
                continue
            # "saadhe teen sau to vahan se kiraya lagega": fare or price talk about nothing on the list
            if _is_bargain(toks) and match_item(" ".join(item))["status"] in ("unknown", "missing"):
                continue
            if long_call and not item and lines and not lines[-1]["qty_values"] and lines[-1]["item_text"] \
                    and len(q["values"]) == 1:
                lines[-1]["qty_values"] = q["values"]  # "Amul ghee ke can chahiye. Kitne carton? Do carton."
                lines[-1]["unit"] = q["unit"]
                lines[-1]["heard"] += " / " + " ".join(toks)
                lines[-1]["said_at"] = _next_said(lines)
                continue
            if long_call and _call_talk(item):
                continue
            if long_call and (_change_said(toks) or _NOT_WORDS & set(toks)) and _update_named(item, q, lines):
                continue  # "nahi yaar cheeni aath kar do": the cheeni line is now 8
            if long_call and lines and _fills_unnamed(item, q, lines):
                continue  # "chalo do bori de do" / "do bori basmati": the shop names what the 2 bags are
            if long_call and _echo_of(item, q, lines):
                continue  # the shop repeating it back ("chhah peti Lux ho gaya"): same item, same quantity
            if long_call and lines and item and all(t in _VARIANT_WORDS for t in item):
                # "pink wala do peti alag se": a kind of the item before, not a new item. Shown on that
                # line for staff to check; a later "total chhah" sets the number.
                prev = _last_said(lines)
                note = f"{' '.join(item)}: {' ya '.join(map(str, q['values']))} {q['unit'] or ''}".strip()
                if note not in (prev.get("note") or ""):
                    prev["note"] = f"{prev['note']}; {note}" if prev.get("note") else note
                continue
            if long_call and not _ADD_WORDS & set(toks) and _update_named(item, q, lines):
                continue  # the same item again with another number later in the call: the later one counts
            lines.append({
                "said_at": _next_said(lines),
                "heard": " ".join(toks[start:stop]) if item else " ".join(toks),
                "item_text": " ".join(item),
                # in a call, a number with no unit in price talk is never taken as sure: the app asks "kitna?"
                "qty_values": [] if long_call and not q["unit"] and _is_bargain(toks) else q["values"],
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
