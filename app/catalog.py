"""Built-in sample catalog (20 items) and sample parties, with Hinglish aliases.

Each item has a `group` when the spoken word is generic (e.g. "sabun" could be
any of three soaps). A generic word never picks a brand on its own; the app
asks "Kaun sa soap brand?" instead.
"""

CATALOG = [
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

PARTIES = [
    {"code": "P01", "name": "ABC Traders", "aliases": ["abc", "a b c", "abc traders", "abc wale", "ebc", "ebisi", "e bi si"]},
    {"code": "P02", "name": "Sharma Traders", "aliases": ["sharma traders", "sharma ji traders"]},
    {"code": "P03", "name": "Sharma General Store", "aliases": ["sharma general", "sharma store", "sharma general store"]},
    {"code": "P04", "name": "Gupta Kirana", "aliases": ["gupta", "gupta ji", "gupta kirana", "gupta wale"]},
    {"code": "P05", "name": "Bittu Store", "aliases": ["bittu", "bitu", "bittu store", "bittu bhai"]},
    {"code": "P06", "name": "New Punjab Stores", "aliases": ["punjab", "new punjab", "punjab store", "punjab wale"]},
    {"code": "P07", "name": "Jain Brothers", "aliases": ["jain", "jain brothers", "jain bhai", "jain sahab"]},
]
# Words that, said alone, could mean more than one party.
AMBIGUOUS_PARTY_WORDS = {"sharma": ["P02", "P03"], "sharma ji": ["P02", "P03"]}

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
    "truck": ["truck", "trak", "gaadi"],
    "auto": ["auto"],
    "bike": ["bike", "scooty", "motorcycle"],
    "courier": ["courier", "kuriyar", "transport"],
    "self pickup": ["khud", "khud le gaye", "pickup", "self"],
}

ITEMS_BY_CODE = {i["code"]: i for i in CATALOG}
PARTIES_BY_CODE = {p["code"]: p for p in PARTIES}


def unit_from_word(word: str):
    w = word.lower().strip()
    for unit, words in UNITS.items():
        if w in words:
            return unit
    return None
