"""Text clean-up for Hinglish: Devanagari -> Roman, spelling normalisation,
and spoken numbers ("das", "dus", "ten", "pachees", "25") -> integers.

Speech engines return Hinglish in either script ("दस कार्टन साबुन" or
"das carton sabun"), so everything is brought to one Roman form before any
matching happens.
"""
import re

# ---------------------------------------------------------------- Devanagari
_VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
           "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o"}
_MATRAS = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e",
           "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e"}
_CONS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh",
         "ज": "j", "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh",
         "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p",
         "फ": "f", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l",
         "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ड़": "r", "ढ़": "rh",
         "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "फ़": "f", "य़": "y"}
_SIGNS = {"ं": "n", "ँ": "n", "ः": "h", "़": ""}
_VIRAMA = "्"
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def deva_to_roman(text: str) -> str:
    out = []
    chars = list(text)
    i = 0
    while i < len(chars):
        c = chars[i]
        # nukta combinations
        if i + 1 < len(chars) and chars[i + 1] == "़" and (c + "़") in _CONS:
            c = c + "़"
            i += 1
        if c in _CONS:
            out.append(_CONS[c])
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            if nxt == _VIRAMA:
                i += 2
                continue
            if nxt in _MATRAS:
                out.append(_MATRAS[nxt])
                i += 2
                continue
            # inherent 'a', dropped at end of a word (schwa deletion)
            if nxt and ("ऀ" <= nxt <= "ॿ") and nxt not in _SIGNS:
                out.append("a")
            elif nxt in _SIGNS:
                out.append("a")
            i += 1
            continue
        if c in _VOWELS:
            out.append(_VOWELS[c])
        elif c in _MATRAS:
            out.append(_MATRAS[c])
        elif c in _SIGNS:
            out.append(_SIGNS[c])
        elif c in ("।", "॥"):
            out.append(".")
        else:
            out.append(c)
        i += 1
    return "".join(out).translate(_DIGITS)


def has_devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text)


def norm(text: str) -> str:
    """One spelling for many: lower case, Roman script, collapsed vowels/doubles."""
    t = deva_to_roman(text) if has_devanagari(text) else text
    t = t.lower()
    t = re.sub(r"[^a-z0-9.\s-]", " ", t)
    t = t.replace("ee", "i").replace("oo", "u")
    t = re.sub(r"([a-z])\1+", r"\1", t)  # aath->ath, pachchees->pachis, dass->das
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)  # keep 2.5, drop full stops
    return re.sub(r"\s+", " ", t).strip()


def readable(text: str) -> str:
    """Roman text for display (keeps spelling, only changes script)."""
    return deva_to_roman(text) if has_devanagari(text) else text


# ------------------------------------------------------------------- numbers
_RAW_NUMBERS = {
    1: ["ek", "ik", "aik", "one"], 2: ["do", "doh", "two"], 3: ["teen", "tin", "three"],
    4: ["char", "chaar", "four"], 5: ["paanch", "panch", "five"],
    6: ["chhe", "che", "chhah", "chah", "chheh", "six"], 7: ["saat", "seven"],
    8: ["aath", "ath", "aat", "eight"], 9: ["nau", "nao", "nine"],
    10: ["das", "dus", "dass", "ten"], 11: ["gyarah", "gyara", "igyara", "eleven"],
    12: ["barah", "bara", "baarah", "twelve"], 13: ["terah", "tera", "thirteen"],
    14: ["chaudah", "chauda", "choda", "fourteen"], 15: ["pandrah", "pandra", "fifteen"],
    16: ["solah", "sola", "sixteen"], 17: ["satrah", "satra", "seventeen"],
    18: ["atharah", "athara", "attharah", "eighteen"], 19: ["unnis", "unis", "nineteen"],
    20: ["bees", "twenty"], 21: ["ikkis", "ekkis"], 22: ["bais", "baais"],
    23: ["teis", "tais", "teyis"], 24: ["chaubis", "chobis", "chaubees"],
    25: ["pachees", "pachis", "pacchis", "pachchis", "pachchees"],
    26: ["chhabbis", "chabbis"], 27: ["sattais", "sataais"], 28: ["atthais", "athais"],
    29: ["untis", "untees"], 30: ["tees", "thirty"], 35: ["paintis", "paintees"],
    40: ["chalis", "chaalis", "forty"], 45: ["paintalis"], 50: ["pachas", "pachaas", "fifty"],
    60: ["sixty"], 70: ["sattar", "seventy"], 75: ["pachattar"], 80: ["assi", "eighty"],
    90: ["nabbe", "ninety"], 100: ["sau", "hundred"],
}
WORD_TO_NUM = {}
for _n, _words in _RAW_NUMBERS.items():
    for _w in _words:
        WORD_TO_NUM[norm(_w)] = _n
FRACTIONS = {norm("dedh"): 1.5, norm("dhai"): 2.5, norm("dhaai"): 2.5, norm("aadha"): 0.5}
# Number words that are also everyday words ("bhej do", "ek minute").
WEAK_NUMBER_WORDS = {norm(w) for w in ["do", "ek", "tin", "sat", "che", "nau", "bis", "tera", "bara", "sola"]}


def parse_number_at(tokens, i):
    """Read a number starting at tokens[i]. Returns (value, tokens_used) or (None, 0).

    Handles "25", "twenty five", "do sau", "ek sau bees", "dedh".
    """
    def single(tok):
        if re.fullmatch(r"\d+(\.\d+)?", tok):
            v = float(tok)
            return int(v) if v.is_integer() else v
        if tok in FRACTIONS:
            return FRACTIONS[tok]
        return WORD_TO_NUM.get(tok)

    if i >= len(tokens):
        return None, 0
    v = single(tokens[i])
    if v is None:
        return None, 0
    used = 1
    # "do sau" -> 200, "ek sau bees" -> 120
    if i + 1 < len(tokens) and tokens[i + 1] in (norm("sau"), "hundred") and v < 10:
        v, used = v * 100, 2
        nxt, u2 = parse_number_at(tokens, i + 2)
        if nxt is not None and nxt < 100:
            v, used = v + nxt, used + u2
        return v, used
    # "twenty five"
    if isinstance(v, int) and v in (20, 30, 40, 50, 60, 70, 80, 90) and i + 1 < len(tokens):
        nxt = single(tokens[i + 1])
        if isinstance(nxt, int) and 1 <= nxt <= 9 and tokens[i + 1].isalpha() and tokens[i + 1] in {
                norm(w) for w in ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]}:
            return v + nxt, 2
    return v, used


def numbers_in(text: str):
    """All numbers said in a piece of text, in order (used for answers like 'nahi, aath')."""
    toks = norm(text).replace("-", " ").split()
    found, i = [], 0
    while i < len(toks):
        v, used = parse_number_at(toks, i)
        if v is not None:
            found.append(v)
            i += used
        else:
            i += 1
    return found
