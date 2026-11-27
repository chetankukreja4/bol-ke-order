"""Fuzzy matching of spoken item and party names against the catalog.

Rules (all in plain code):
* A strong, clear match (score >= 88 and well ahead of the next item) is accepted.
* A generic word like "sabun" maps to a group -> ask which brand.
* Anything weaker is never guessed: we return the top three and ask.
"""
from rapidfuzz import fuzz

from .catalog import (AMBIGUOUS_PARTY_WORDS, CATALOG, GROUP_LABEL, GROUP_WORDS,
                      ITEMS_BY_CODE, PARTIES, PARTIES_BY_CODE, on_items_change, on_parties_change)
from .textnorm import norm

STRONG = 88
WEAK = 55
LEAD = 8
MAX_CHOICES = 8  # a "which brand?" question never lists more than this

_ITEM_INDEX = []


@on_items_change
def rebuild_item_index():
    _ITEM_INDEX[:] = [(norm(a), it["code"]) for it in CATALOG for a in it["aliases"] + [it["name"]] if norm(a)]


rebuild_item_index()
_PARTY_INDEX = []
_PARTY_INDEX_SET = {}  # exact phrase -> party, except phrases that could mean two parties


@on_parties_change
def rebuild_party_index():
    _PARTY_INDEX[:] = [(norm(a), p["code"]) for p in PARTIES for a in p["aliases"] + [p["name"]] if norm(a)]
    _PARTY_INDEX_SET.clear()
    for alias, code in _PARTY_INDEX:
        if alias not in AMBIGUOUS_PARTY_WORDS:
            _PARTY_INDEX_SET[alias] = code


rebuild_party_index()
_GROUP_INDEX = {norm(w): g for g, words in GROUP_WORDS.items() for w in words}


def _ngrams(tokens, max_n=3):
    grams = []
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            grams.append(" ".join(tokens[i:i + n]))
    return grams


def _score(phrase_tokens, alias):
    best = 0
    for g in _ngrams(phrase_tokens):
        # avoid tiny fragments matching long aliases ("ka" ~ "kachi ghani")
        if len(g) < 3 and g != alias:
            continue
        s = fuzz.ratio(g, alias)
        if s == 100:  # an exact longer phrase beats a shorter one ("sarson tel" > "tel")
            s += 10 * (len(g.split()) - 1)
        if s > best:
            best = s
    return best


def _ranked(phrase, index):
    tokens = norm(phrase).split()
    best = {}
    for alias, code in index:
        s = _score(tokens, alias)
        if s > best.get(code, 0):
            best[code] = s
    return sorted(best.items(), key=lambda kv: -kv[1])


def item_option(code, score=None):
    it = ITEMS_BY_CODE[code]
    o = {"code": code, "name": it["name"], "unit": it["unit"]}
    if score is not None:
        o["score"] = round(score)
    return o


def match_item(phrase: str):
    """Returns dict(status, item, options, group).

    status: "ok" (sure), "choose" (generic word, pick brand),
            "unsure" (close but not sure), "unknown" (no good match), "missing".
    """
    tokens = norm(phrase).split()
    if not tokens:
        return {"status": "missing", "item": None, "options": [], "group": None}
    ranked = _ranked(phrase, _ITEM_INDEX)
    if not ranked:
        return {"status": "unknown", "item": None, "options": [], "group": None}
    top_code, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0

    group = next((_GROUP_INDEX[t] for t in tokens if t in _GROUP_INDEX), None)
    if group is None:
        group = next((_GROUP_INDEX[g] for g in _ngrams(tokens, 3) if g in _GROUP_INDEX), None)

    if top >= STRONG and (top - second >= LEAD or ranked[1][0] == top_code):
        # An exact spoken name ("toor dal", "haldi powder") is never a guess, even
        # if it contains a generic word and the item sits outside that group.
        if group is None or ITEMS_BY_CODE[top_code]["group"] == group or top >= 100:
            return {"status": "ok", "item": item_option(top_code, top), "options": [], "group": group}
    if group is not None:
        in_group = [i["code"] for i in CATALOG if i["group"] == group]
        if len(in_group) > MAX_CHOICES:  # big real lists: the closest few of the group
            score = dict(ranked)
            in_group = sorted(in_group, key=lambda c: -score.get(c, 0))[:MAX_CHOICES]
        if in_group:
            return {"status": "choose", "item": None, "options": [item_option(c) for c in in_group], "group": group}
        group = None  # nothing in that group: fall back to the closest names
    opts = [item_option(c, s) for c, s in ranked[:3]]
    if top >= WEAK:
        return {"status": "unsure", "item": None, "options": opts, "group": None}
    return {"status": "unknown", "item": None, "options": opts, "group": None}


def group_label(group):
    return GROUP_LABEL.get(group, group or "item")


def party_option(code):
    return {"code": code, "name": PARTIES_BY_CODE[code]["name"]}


def find_party(text: str):
    """Look for a party anywhere in the text. Returns (result, matched_phrase)."""
    tokens = norm(text).split()
    # a number ("10 carton") or a fragment of it never names a party
    grams = [g for g in _ngrams(tokens, 3) if any(ch.isalpha() for ch in g)]
    # exact ambiguous words first ("sharma" alone)
    for g in sorted(grams, key=lambda g: -len(g.split())):
        if g in _PARTY_INDEX_SET:
            code = _PARTY_INDEX_SET[g]
            return {"status": "ok", "party": party_option(code), "options": []}, g
    for g in grams:
        if g in AMBIGUOUS_PARTY_WORDS:
            opts = [party_option(c) for c in AMBIGUOUS_PARTY_WORDS[g]]
            return {"status": "choose", "party": None, "options": opts}, g
    per_code = {}  # code -> (best score, phrase)
    for g in grams:
        if len(g) < 3:
            continue
        for alias, code in _PARTY_INDEX:
            s = fuzz.ratio(g, alias)
            if s > per_code.get(code, (0, None))[0]:
                per_code[code] = (s, g)
    ranked = sorted(per_code.items(), key=lambda kv: -kv[1][0])
    if ranked and ranked[0][1][0] >= STRONG:
        best_code, (best, phrase) = ranked[0]
        close = [c for c, (s, _) in ranked[1:] if s >= STRONG and best - s < LEAD]
        if close:  # "Shiv Trader": Shiv Traders or Shiva Traders? ask, never guess
            opts = [party_option(c) for c in [best_code] + close[:2]]
            return {"status": "choose", "party": None, "options": opts}, phrase
        return {"status": "ok", "party": party_option(best_code), "options": []}, phrase
    return {"status": "missing", "party": None, "options": []}, None




def choose_from(text: str, options, kind="item"):
    """Pick one of the offered options from a spoken answer.

    Accepts the name ("Lux"), an ordinal ("pehla", "doosra", "first", "1"),
    or a fresh name from the full catalog.
    """
    t = norm(text)
    ordinals = {0: ["pehla", "pahla", "pehle", "first", "1", "ek", "one", "pela"],
                1: ["dusra", "dusre", "second", "2", "do", "two"],
                2: ["tisra", "tisre", "third", "3", "tin", "three"]}
    toks = t.split()
    for idx, words in ordinals.items():
        if idx < len(options) and any(norm(w) in toks for w in words):
            return options[idx]
    index = _ITEM_INDEX if kind == "item" else _PARTY_INDEX
    allowed = {o["code"] for o in options}
    ranked = [(c, s) for c, s in _ranked(text, index) if c in allowed]
    if ranked and ranked[0][1] >= 75 and (len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= 5):
        return next(o for o in options if o["code"] == ranked[0][0])
    return None
