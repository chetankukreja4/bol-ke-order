"""Sample catalog (20 items) and sample parties, with Hinglish aliases.

The item list lives in SQLite (Items page) and is seeded from SAMPLE_ITEMS on
first start. CATALOG / ITEMS_BY_CODE always hold the current list; call
replace_items() after a change so the matcher rebuilds its index.

Each item has a `group` when the spoken word is generic (e.g. "sabun" could be
any of three soaps). A generic word never picks a brand on its own; the app
asks "Kaun sa soap brand?" instead.
"""

from .textnorm import norm

SAMPLE_ITEMS = [
    # code, name, default unit, group, aliases
    {"code": "SP01", "name": "Lux Soap", "unit": "carton", "group": "soap",
     "aliases": ["lux", "lux sabun", "lux soap", "laks"]},
    {"code": "SP02", "name": "Lifebuoy Soap", "unit": "carton", "group": "soap",
     "aliases": ["lifebuoy", "lifeboy", "laifboy", "lifebuoy sabun", "lifebuoy soap"]},
    {"code": "SP03", "name": "Dettol Soap", "unit": "carton", "group": "soap",
     "aliases": ["dettol", "detol", "dettol sabun", "dettol soap"]},
    {"code": "OL01", "name": "Fortune Refined Oil 1L", "unit": "carton", "group": None,
     "aliases": ["tel", "oil", "refined", "refind", "fortune", "fortune oil", "refined tel", "tail"]},
    {"code": "OL02", "name": "Mustard Oil 1L", "unit": "carton", "group": None,
     "aliases": ["sarson", "sarso", "sarson tel", "sarson ka tel", "mustard", "mustard oil", "kachi ghani"]},
    {"code": "DT01", "name": "Surf Excel 1kg", "unit": "carton", "group": "detergent",
     "aliases": ["surf", "surf excel", "sarf", "surf exel"]},
    {"code": "DT02", "name": "Tide 1kg", "unit": "carton", "group": "detergent",
     "aliases": ["tide", "taid", "tide powder"]},
    {"code": "DT03", "name": "Wheel 1kg", "unit": "carton", "group": "detergent",
     "aliases": ["wheel", "wil", "vheel", "wheel powder"]},
    {"code": "AT01", "name": "Aashirvaad Atta 10kg", "unit": "bag", "group": None,
     "aliases": ["atta", "aata", "ashirvad", "aashirvaad", "gehu ka atta", "flour"]},
    {"code": "RC01", "name": "Basmati Rice 25kg", "unit": "bag", "group": None,
     "aliases": ["chawal", "chaval", "rice", "basmati", "basmati chawal"]},
    {"code": "SG01", "name": "Sugar 50kg", "unit": "bag", "group": None,
     "aliases": ["cheeni", "chini", "shakkar", "sugar", "shakar"]},
    {"code": "SL01", "name": "Tata Salt 1kg", "unit": "carton", "group": None,
     "aliases": ["namak", "nmak", "salt", "tata namak", "tata salt"]},
    {"code": "TE01", "name": "Tata Tea 1kg", "unit": "carton", "group": None,
     "aliases": ["chai", "chai patti", "chaipatti", "patti", "tea", "tata tea"]},
    {"code": "DL01", "name": "Toor Dal 30kg", "unit": "bag", "group": "dal",
     "aliases": ["toor", "tur", "arhar", "toor dal", "arhar dal", "tuar"]},
    {"code": "DL02", "name": "Moong Dal 30kg", "unit": "bag", "group": "dal",
     "aliases": ["moong", "mung", "moong dal", "mung dal"]},
    {"code": "BS01", "name": "Parle-G Biscuit", "unit": "carton", "group": None,
     "aliases": ["parle", "parle g", "parleji", "biscuit", "biskut", "biskit"]},
    {"code": "MG01", "name": "Maggi Noodles", "unit": "carton", "group": None,
     "aliases": ["maggi", "magi", "noodles", "maggie"]},
    {"code": "TP01", "name": "Colgate Toothpaste", "unit": "carton", "group": None,
     "aliases": ["colgate", "kolgate", "manjan", "toothpaste", "paste"]},
    {"code": "GH01", "name": "Amul Ghee 1L", "unit": "carton", "group": None,
     "aliases": ["ghee", "ghi", "desi ghee", "amul ghee"]},
    {"code": "MC01", "name": "Matchbox (Ship)", "unit": "packet", "group": None,
     "aliases": ["machis", "maachis", "matchbox", "tili", "match"]},
]

# Generic spoken words that map to a group, not a single item.
GROUP_WORDS = {
    "soap": ["sabun", "saboon", "sabon", "soap", "sop"],
    "detergent": ["detergent", "powder", "kapde ka powder", "washing powder"],
    "dal": ["dal", "daal", "dhal"],
}
GROUP_LABEL = {"soap": "soap", "detergent": "powder", "dal": "dal"}

SAMPLE_PARTIES = [
    {"code": "P01", "name": "ABC Traders", "aliases": ["abc", "a b c", "abc traders", "abc wale", "ebc", "ebisi", "e bi si"]},
    {"code": "P02", "name": "Sharma Traders", "aliases": ["sharma traders", "sharma ji traders"]},
    {"code": "P03", "name": "Sharma General Store", "aliases": ["sharma general", "sharma store", "sharma general store"]},
    {"code": "P04", "name": "Gupta Kirana", "aliases": ["gupta", "gupta ji", "gupta kirana", "gupta wale"]},
    {"code": "P05", "name": "Bittu Store", "aliases": ["bittu", "bitu", "bittu store", "bittu bhai"]},
    {"code": "P06", "name": "New Punjab Stores", "aliases": ["punjab", "new punjab", "punjab store", "punjab wale"]},
    {"code": "P07", "name": "Jain Brothers", "aliases": ["jain", "jain brothers", "jain bhai", "jain sahab"]},
]
# Words that never name one party on their own ("New Punjab" and "New Delhi Traders").
GENERIC_PARTY_WORDS = {"new", "shree", "shri", "sri", "jai", "the", "m/s", "ms"}


def ambiguous_words(parties):
    """Words that, said alone, could mean more than one party ("Sharma" for
    Sharma Traders and Sharma General Store). Worked out from the list itself,
    so an imported party list asks "which one?" too."""
    holders = {}
    for p in parties:
        for phrase in [p["name"]] + list(p["aliases"]):
            words = norm(phrase).split()
            if not words:
                continue
            keys = {" ".join(words)}
            if words[0] not in GENERIC_PARTY_WORDS and len(words[0]) >= 3:
                keys |= {words[0], f"{words[0]} ji"}
            for k in keys:
                holders.setdefault(k, [])
                if p["code"] not in holders[k]:
                    holders[k].append(p["code"])
    return {k: codes for k, codes in holders.items() if len(codes) > 1}

UNITS = {
    "carton": ["carton", "kartan", "kartun", "cartoon", "kartoon", "karton", "peti", "box", "dabba", "dibba", "cartons"],
    "bag": ["bori", "bora", "bag", "katta", "bags", "boriya"],
    "packet": ["packet", "pkt", "paket", "packets", "pack"],
    "piece": ["piece", "pc", "pcs", "nag", "pieces"],
    "kg": ["kg", "kilo", "kilogram", "kgs"],
    "litre": ["litre", "liter", "ltr"],
}

DISPATCH_MODES = {
    "rickshaw": ["rickshaw", "riksha", "rikshaw", "e rickshaw", "erickshaw"],
    "tempo": ["tempo", "chhota hathi", "chota hathi", "loader"],
    "truck": ["truck", "trak", "traik", "track", "trek", "gaadi"],
    "auto": ["auto"],
    "bike": ["bike", "scooty", "motorcycle"],
    "courier": ["courier", "kuriyar", "transport"],
    "self pickup": ["khud", "khud le gaye", "pickup", "self"],
}

CATALOG = [dict(i, aliases=list(i["aliases"])) for i in SAMPLE_ITEMS]  # current items
ITEMS_BY_CODE = {i["code"]: i for i in CATALOG}
_on_change = []  # callbacks (matcher index rebuild)


def on_items_change(fn):
    _on_change.append(fn)
    return fn


def replace_items(items):
    """Swap in a new item list in place, so every importer sees it."""
    CATALOG[:] = items
    ITEMS_BY_CODE.clear()
    ITEMS_BY_CODE.update({i["code"]: i for i in items})
    for fn in _on_change:
        fn()

PARTIES = [dict(p, aliases=list(p["aliases"])) for p in SAMPLE_PARTIES]  # current parties
PARTIES_BY_CODE = {p["code"]: p for p in PARTIES}
AMBIGUOUS_PARTY_WORDS = ambiguous_words(PARTIES)
_on_parties_change = []  # callbacks (matcher party index rebuild)


def on_parties_change(fn):
    _on_parties_change.append(fn)
    return fn


def replace_parties(parties):
    """Swap in a new party list in place, so every importer sees it."""
    PARTIES[:] = parties
    PARTIES_BY_CODE.clear()
    PARTIES_BY_CODE.update({p["code"]: p for p in parties})
    AMBIGUOUS_PARTY_WORDS.clear()
    AMBIGUOUS_PARTY_WORDS.update(ambiguous_words(parties))
    for fn in _on_parties_change:
        fn()


def unit_from_word(word: str):
    w = word.lower().strip()
    for unit, words in UNITS.items():
        if w in words:
            return unit
    return None
