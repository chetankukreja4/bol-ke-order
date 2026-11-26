"""Read the shop's item and party lists from a Busy export (CSV or .xlsx).

Busy's "List of Items" / "List of Accounts" exports often start with a title
block (company name, date). The header row is found by looking for a name
column in the first rows. Nothing here guesses a match for an order: it only
fills the lists the matcher already uses.
"""
import csv
import io
import re

from .catalog import GROUP_WORDS, unit_from_word

MAX_ROWS = 20000
HEADER_SCAN = 10

ITEM_COLS = {
    "name": ["name", "item name", "item", "particulars"],
    "code": ["code", "item code"],
    "unit": ["unit", "main unit", "units", "uom"],
    "group": ["group", "item group", "parent group", "under"],
    "aliases": ["aliases", "spoken names", "alias", "print name"],
}
CODE_RE = re.compile(r"[A-Z0-9_-]{1,12}")


class ImportProblem(Exception):
    """A file the app cannot read. The message is shown to shop staff."""


def _key(v):
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def _grid(filename, data):
    name = (filename or "").lower()
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return [[_cell(c) for c in row] for row in csv.reader(io.StringIO(text))]
    if name.endswith(".xlsx"):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:  # corrupt file, password, not really xlsx
            raise ImportProblem("Ye Excel file khul nahi rahi. Busy se dobara .xlsx ya CSV export karein.") from e
        return [[_cell(c) for c in row] for row in wb.active.iter_rows(values_only=True)]
    raise ImportProblem("Excel ko .xlsx ya CSV mein save karein")


def read_table(filename, data):
    """Rows as {lower-cased header: text}, starting under the header row."""
    grid = _grid(filename, data)
    names = set(ITEM_COLS["name"]) | {"account name", "party name"}
    for i, row in enumerate(grid[:HEADER_SCAN]):
        heads = [_key(c) for c in row]
        if names & set(heads):
            break
    else:
        raise ImportProblem("Header nahi mila. Pehli line mein 'Name' column hona chahiye.")
    rows = []
    for row in grid[i + 1:i + 1 + MAX_ROWS]:
        if not any(row):
            continue
        rows.append({h: (row[j] if j < len(row) else "") for j, h in enumerate(heads) if h})
    return rows


def _pick(row, names):
    for n in names:
        if row.get(n):
            return row[n]
    return ""


def _unit(text):
    w = _key(text)
    return unit_from_word(w) or (w.endswith("s") and unit_from_word(w[:-1])) or "piece"


def _group(text):
    t = _key(text)
    for g, words in GROUP_WORDS.items():
        if any(w in t for w in words):
            return g
    return None


def _aliases(name, extra):
    out, seen = [], set()
    for a in [name] + [x for e in extra for x in re.split(r"[|,]", e)]:
        a = _key(a)
        if a and a not in seen and len(a) <= 60:
            seen.add(a)
            out.append(a)
    return out[:30]


def _code(raw, used, prefix):
    code = re.sub(r"\s+", "", raw or "").upper()
    if CODE_RE.fullmatch(code) and code not in used:
        return code
    n = 1
    while f"{prefix}{n:03d}" in used:
        n += 1
    return f"{prefix}{n:03d}"


def to_items(rows):
    """Busy item rows -> (items in the Items page shape, skipped rows with a reason)."""
    items, skipped, names, used = [], [], set(), set()
    for n, row in enumerate(rows, 1):
        name = _pick(row, ITEM_COLS["name"])
        if not name or len(name) > 80:
            skipped.append({"row": n, "name": name, "reason": "naam nahi"})
            continue
        if name.lower() in names:
            skipped.append({"row": n, "name": name, "reason": "dobara aaya"})
            continue
        names.add(name.lower())
        code = _code(_pick(row, ITEM_COLS["code"]), used, "I")
        used.add(code)
        items.append({
            "code": code, "name": name,
            "unit": _unit(_pick(row, ITEM_COLS["unit"])),
            "group": _group(_pick(row, ITEM_COLS["group"])),
            "aliases": _aliases(name, [row.get(c, "") for c in ITEM_COLS["aliases"]]),
        })
    return items, skipped
