# Shop-ready + Pilot Numbers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the pilot wholesaler load their Busy item and party lists, and record before/after numbers for every order (time to confirm, questions, corrections, "Galat nikla") on a Pilot tab with CSV.

**Architecture:** Order stats ride inside the draft JSON the browser already sends back (server stays stateless) and are saved as new columns on `orders`. A new `app/pilot.py` computes the summary. A new `app/importer.py` reads Busy CSV/XLSX exports into the same item shape the Items page uses; parties move to a SQLite table with a live-rebuilt matcher index, like items.

**Tech Stack:** Python 3 / FastAPI / SQLite / RapidFuzz, `openpyxl` (new), vanilla JS in `static/app.js`.

**Spec:** `docs/superpowers/specs/2026-11-27-pilot-ready-design.md`

## Global Constraints

- Deadline: Round 2 closes 30 Nov 2026 EOD. Order of work: Tasks 1–3 first (core proof), then 4–6, then 7. Cut from the bottom.
- No LLM. Never guess an item, quantity or party. Nothing saved before "haan, pakka". Prices never stored. App starts with no keys.
- Every commit updates `HANDOFF.md` (Last updated line, sections 5, 7, 8, 12; section 3 if status moved) — `AGENTS.md` rule.
- Run `.venv\Scripts\python -m pytest -q` before every commit; all must pass.
- When `static/app.js` or `static/style.css` change, bump `?v=` on both links in `static/index.html` (currently `v=9`).
- Never commit `.env` or `data/*.db`. UI text in simple Hinglish (Roman), matching existing labels.
- Tests share one SQLite file (`DB_PATH` set at import of the first test module; files run alphabetically, so `test_import.py` runs before `test_orders.py`). Any test that replaces items or parties must restore the samples afterwards (fixture in Task 4).

## Review Focus

1. A real Busy `.xlsx` with a title block (company name, date rows) above the header row → header still found; a legacy `.xls` → clear message "Excel ko .xlsx ya CSV mein save karein", not a 500. (Task 4)
2. Busy account list contains banks, expenses and creditors, not just customers → only "Sundry Debtors" rows become parties when a group column is present. (Task 5)
3. Two real parties sharing a first word ("Sharma Traders", "Sharma General Store") → saying "Sharma" alone asks which one after import, not only for the seed data. (Task 5)
4. A draft from an old browser tab with no `stats` key → `/api/answer` and `/api/orders` still work; the order is saved with `seconds_to_confirm = NULL` and is left out of the time median. (Tasks 1–2)
5. Busy units like "Pcs", "Box", "Kgs", "Bori" or blank → mapped through `catalog.unit_from_word`, unknown → `piece`, never a 400 for the whole file. (Task 4)

---

### Task 1: Stats inside the draft

**Files:**
- Create: `app/pilot.py`
- Modify: `app/dialog.py` (`answer`), `app/main.py` (`TextIn`, `parse`)
- Test: `tests/test_pilot.py`

**Interfaces:**
- Produces: `pilot.SOURCES = ("mic", "upload", "transcript", "typed")`
- Produces: `pilot.new_stats(source: str | None, draft: dict, test: bool = False) -> dict` returning
  `{"started_at": <ISO IST now, seconds>, "source": source if in SOURCES else "typed", "questions": 0, "corrections": 0, "uncertain_start": <count of lines with uncertain=True + (1 if party status != "ok")>, "lines": len(draft["lines"]), "test": test}`
- Produces: `TextIn` gains `source: str | None = None`, `test: bool = False`. `/api/parse` sets `draft["stats"] = pilot.new_stats(...)`; for `kind == "transcript"` the source is forced to `"transcript"`.
- `dialog.answer`: if `d.get("stats")` exists, `questions += 1` when an asked question (`q` not None) was handled; `corrections += 1` when `_apply_correction` returns ok. Missing `stats` → no error.

- [ ] **Step 1: Write the failing tests** in `tests/test_pilot.py` (copy the env header lines from `tests/test_orders.py` top: `DB_PATH`, pop `SARVAM_API_KEY`, `BKO_NO_DOTENV`):

```python
def test_parse_starts_stats():
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton sabun kal", "source": "mic"}).json()
    s = d["stats"]
    assert s["source"] == "mic" and s["questions"] == 0 and s["corrections"] == 0
    assert s["lines"] == 1 and s["uncertain_start"] == 1 and s["test"] is False
    assert s["started_at"].startswith("20")

def test_answers_count_questions_and_corrections():
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton sabun kal"}).json()
    d = client.post("/api/answer", json={"draft": d, "text": "Lux"}).json()["draft"]
    d = client.post("/api/answer", json={"draft": d, "text": "nahi, aath carton"}).json()["draft"]
    assert d["stats"]["questions"] == 1 and d["stats"]["corrections"] == 1
    assert d["stats"]["source"] == "typed"

def test_old_draft_without_stats_still_works():
    d = client.post("/api/parse", json={"text": "ABC wale ko 10 carton Lux kal"}).json()
    d.pop("stats")
    r = client.post("/api/answer", json={"draft": d, "text": "haan pakka"})
    assert r.status_code == 200 and r.json()["action"] == "confirm"
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_pilot.py -v` — Expected: FAIL (`KeyError: 'stats'`).
- [ ] **Step 3: Implement** `app/pilot.py` (`SOURCES`, `new_stats`; use `datetime.now(parser.IST).isoformat(timespec="seconds")`), the `TextIn` fields, `parse` wiring, and the two counters in `dialog.answer`.
- [ ] **Step 4: Run** the full suite — Expected: all pass (42 old + 3 new).
- [ ] **Step 5: Commit** with HANDOFF update: `git commit -m "Pilot: count questions and corrections in the draft"`

### Task 2: Save stats, "Galat nikla", Pilot summary + CSV, baseline

**Files:**
- Modify: `app/db.py`, `app/pilot.py`, `app/main.py`
- Test: `tests/test_pilot.py`

**Interfaces:**
- Consumes: `draft["stats"]` from Task 1.
- Produces (db): new `orders` columns `stats TEXT`, `seconds_to_confirm REAL`, `wrong_reason TEXT`, `wrong_at TEXT`, added in `_conn()` by checking `PRAGMA table_info(orders)` and running `ALTER TABLE orders ADD COLUMN ...` for missing ones. `_row()` adds `stats` (dict or None), `seconds_to_confirm`, `wrong_reason`, `wrong_at`.
- Produces (db): `save_order(draft)` stores `json.dumps(draft.get("stats"))` and `seconds_to_confirm = round(now − started_at, 1)` (None without stats); `mark_wrong(order_id: int, reason: str) -> dict | None`; `get_meta(k: str) -> str | None`; `set_meta(k: str, v: str) -> None`; `list_orders(limit=50)` keeps its default, pilot uses `list_orders(limit=100000)`.
- Produces (pilot): `WRONG_REASONS = ("item", "qty", "party", "missing", "other")`;
  `summary(orders: list[dict], baseline: list[float]) -> dict` with keys
  `orders, today, median_seconds, avg_seconds, pct_no_questions, pct_right_after_save, corrections_per_order, by_source, wrong_by_reason, baseline_median, baseline_count` (test orders excluded from everything; orders with `seconds_to_confirm is None` excluded from the two time numbers; percentages rounded to whole numbers; `None` when there is nothing to compute);
  `csv_rows(orders) -> list[list]` with header `id, created_at, party, lines, source, test, seconds_to_confirm, questions, corrections, uncertain_start, wrong_reason`.
- Produces (routes): `POST /api/orders/{id}/wrong` body `{"reason": str}` (400 if not in `WRONG_REASONS`, 404 if no order); `GET /api/pilot`; `GET /api/pilot.csv` (reuse `_csv` style from `main.py`); `PUT /api/pilot/baseline` body `{"seconds": list[float]}` (each 1–3600, max 50 values) stored as JSON in `meta` key `baseline_seconds`; `GET /api/pilot` includes `baseline` list.

- [ ] **Step 1: Write the failing tests:**

```python
def _confirmed(text="ABC wale ko 10 carton Lux kal", **kw):
    d = client.post("/api/parse", json={"text": text, **kw}).json()
    return client.post("/api/orders", json={"draft": d}).json()

def test_saved_order_keeps_stats_and_time():
    o = _confirmed(source="mic")
    assert o["stats"]["source"] == "mic" and o["seconds_to_confirm"] >= 0 and o["wrong_reason"] is None

def test_galat_nikla():
    o = _confirmed()
    assert client.post(f"/api/orders/{o['id']}/wrong", json={"reason": "qty"}).json()["wrong_reason"] == "qty"
    assert client.post(f"/api/orders/{o['id']}/wrong", json={"reason": "bad"}).status_code == 400
    assert client.post("/api/orders/999999/wrong", json={"reason": "qty"}).status_code == 404

def test_pilot_summary_numbers():
    from app.pilot import summary
    base = {"party": "X", "lines": [], "created_at": "2026-11-28T10:00:00+05:30", "wrong_reason": None}
    orders = [
        {**base, "id": 1, "seconds_to_confirm": 30, "stats": {"source": "mic", "questions": 0, "corrections": 0, "test": False}},
        {**base, "id": 2, "seconds_to_confirm": 50, "stats": {"source": "upload", "questions": 2, "corrections": 1, "test": False}, "wrong_reason": "qty"},
        {**base, "id": 3, "seconds_to_confirm": 5, "stats": {"source": "mic", "questions": 0, "corrections": 0, "test": True}},
        {**base, "id": 4, "seconds_to_confirm": None, "stats": None},
    ]
    s = summary(orders, [120, 180, 240])
    assert s["orders"] == 3 and s["median_seconds"] == 40 and s["avg_seconds"] == 40
    assert s["pct_no_questions"] == 50 and s["pct_right_after_save"] == 67
    assert s["by_source"] == {"mic": 1, "upload": 1} and s["wrong_by_reason"] == {"qty": 1}
    assert s["baseline_median"] == 180 and s["baseline_count"] == 3

def test_pilot_csv_and_baseline():
    assert client.put("/api/pilot/baseline", json={"seconds": [120, 200]}).status_code == 200
    assert client.get("/api/pilot").json()["baseline"] == [120, 200]
    assert client.put("/api/pilot/baseline", json={"seconds": [0]}).status_code == 400
    r = client.get("/api/pilot.csv")
    assert r.text.splitlines()[0].startswith("id,created_at,party")
```

(Old-draft orders — id 4 above — count as non-test orders with no time; `pct_no_questions` and `corrections_per_order` use only orders that have stats.)

- [ ] **Step 2: Run** `pytest tests/test_pilot.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** the db migration + functions, `pilot.summary` / `csv_rows`, and the four routes. `today` = non-test orders whose `created_at` date equals `parser.today()`.
- [ ] **Step 4: Run** full suite — Expected: all pass. Also delete nothing: check an existing `data/orders.db` from before still opens (start uvicorn once and `GET /api/orders`).
- [ ] **Step 5: Commit** with HANDOFF: `"Pilot: save order numbers, Galat nikla, summary and CSV"`

### Task 3: Pilot tab, Galat nikla button, source + test toggle (frontend)

**Files:**
- Modify: `static/index.html` (5th tab `#pilot` 📊 "Pilot", `section#screen-pilot`, test checkbox on the Order screen, `?v=10`), `static/app.js`, `static/style.css`

**Interfaces:**
- Consumes: Task 1 `source`/`test` on `/api/parse`; Task 2 routes.
- `TABS` gains `'pilot'`. `parseTranscript()` sends `source`: `'transcript'` for pasted text, `'upload'` after `sendRecording()` from a file, `'mic'` after the mic, `'typed'` otherwise — keep the last capture kind in `state.source`. `test` from a checkbox "Practice order (pilot mein nahi gina jayega)"; remember it in `localStorage`.
- Pilot screen: tiles for orders (today / all), median seconds, % no questions, % sahi after save, corrections per order; source split; "Parchi + Busy (pehle)" baseline median beside the app median; a small form to enter baseline seconds (comma-separated) → `PUT /api/pilot/baseline`; "Download CSV" link to `/api/pilot.csv`.
- Order view in Orders tab (`renderDone(viewOnly)`): a "Galat nikla" button → reason choice (Item galat / Quantity galat / Party galat / Item chhoot gaya / Kuch aur → `item|qty|party|missing|other`) → `POST /api/orders/{id}/wrong`; once marked, show the reason in red and hide the button. The parchi print layout must not show it (`no-print`).

- [ ] **Step 1: Implement** the above.
- [ ] **Step 2: Verify in the browser** (preview the local server): place one typed order, one pasted transcript order, one with "Practice order" ticked; mark one "Galat nikla → Quantity". Expected on Pilot tab: orders = 2, source split typed 1 / transcript 1, % sahi after save = 50, CSV downloads with 3 rows (test row has `test=True`). Check phone width and dark theme. No console errors.
- [ ] **Step 3: Run** full pytest — all pass.
- [ ] **Step 4: Commit** with HANDOFF: `"Pilot tab, Galat nikla button, practice orders"`

### Task 4: Busy item import

**Files:**
- Create: `app/importer.py`, `tests/test_import.py`, `tests/data/busy_items.csv`, `tests/data/busy_items.xlsx` (generate the xlsx in the test with `openpyxl` instead of committing a binary — preferred)
- Modify: `app/db.py`, `app/main.py`, `requirements.txt` (`openpyxl>=3.1`)

**Interfaces:**
- Produces: `importer.ImportError_(Exception)` (message shown to staff) — name it `ImportProblem` to avoid shadowing the builtin.
- Produces: `importer.read_table(filename: str, data: bytes) -> list[dict[str, str]]` — `.csv` (utf-8-sig, fallback cp1252) or `.xlsx`; `.xls` and anything else → `ImportProblem("Excel ko .xlsx ya CSV mein save karein")`. Header row = the first of the first 10 rows that contains a name column (see below); keys are lower-cased, single-spaced header text; blank rows dropped.
- Produces: `importer.to_items(rows) -> tuple[list[dict], list[dict]]` = (items, skipped). Item shape = the Items page shape `{"code","name","unit","group","aliases"}`; skipped = `{"row": int (1-based data row), "name": str, "reason": str}`.
  Columns (first match wins): name ← `name`, `item name`, `item`, `particulars`; code ← `code`, `item code`; unit ← `unit`, `main unit`, `units`, `uom`; group ← `group`, `item group`, `parent group`, `under`; spoken names ← `aliases`, `spoken names`, `alias`, `print name`.
  Rules: name required, ≤80 chars, else skipped "naam nahi"; duplicate name (case-insensitive) skipped "dobara aaya"; code kept if it fits `[A-Z0-9_-]{1,12}` and is unique, else generated `I001`, `I002`…; unit via `catalog.unit_from_word` on the lowered value (also try without a trailing "s"), else `piece`; group = a key of `catalog.GROUP_WORDS` only if the group text contains one of that group's words (e.g. "Soaps" → `soap`), else None; aliases = split on `|` or `,`, lowered, plus the lowered name, deduped, ≤60 chars each, max 30.
- Produces: `db.replace_items(items: list[dict]) -> None` (delete all, insert with `pos` in order, keep `items_seeded` flag set).
- Produces route: `POST /api/items/import?commit=0|1` multipart `file` → `{"total_rows", "count", "sample": first 10 items, "skipped": [...], "committed": bool}`; on commit with `count > 0` call `db.replace_items` then `catalog.replace_items(db.list_items())`. `ImportProblem` → 400 with its message. Max file 5 MB.
- Produces test fixture (in `tests/test_import.py`): `restore_samples` (autouse) that after each test calls `db.replace_items` with `catalog.SAMPLE_ITEMS` and `catalog.replace_items(db.list_items())` (and, after Task 5, the same for parties).

- [ ] **Step 1: Write the failing tests:**

```python
def _xlsx(rows):
    import io, openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

def test_busy_xlsx_with_title_block():
    data = _xlsx([["Gupta Wholesale"], ["Item List as on 27-11-2026"], [],
                  ["Name", "Alias", "Group", "Main Unit"],
                  ["Lux Soap 100g", "LUX100", "Soaps", "Box"],
                  ["Parle G 800g", "", "Biscuits", "Pcs"],
                  ["", "", "", ""]])
    items, skipped = to_items(read_table("items.xlsx", data))
    assert [i["name"] for i in items] == ["Lux Soap 100g", "Parle G 800g"]
    assert items[0]["unit"] == "carton" and items[0]["group"] == "soap"   # "box" is a carton word
    assert items[1]["unit"] == "piece" and items[1]["group"] is None
    assert "lux100" in items[0]["aliases"] and "lux soap 100g" in items[0]["aliases"]
    assert items[0]["code"] == "I001" and skipped == []

def test_simple_csv_and_skips():
    csv = "code,name,unit,aliases\nSP9,Tata Salt,kg,namak|tata namak\nXX,,kg,\nSP10,tata salt,kg,\n"
    items, skipped = to_items(read_table("x.csv", csv.encode()))
    assert items[0]["code"] == "SP9" and items[0]["unit"] == "kg" and "namak" in items[0]["aliases"]
    assert [s["reason"] for s in skipped] == ["naam nahi", "dobara aaya"]

def test_xls_refused():
    with pytest.raises(ImportProblem): read_table("old.xls", b"\xd0\xcf\x11\xe0")

def test_import_endpoint_preview_then_commit_changes_matching():
    f = {"file": ("i.csv", b"name,unit\nKurkure Masala,packet\n", "text/csv")}
    p = client.post("/api/items/import", files=f).json()
    assert p["count"] == 1 and p["committed"] is False
    assert client.post("/api/parse", json={"text": "ABC ko 5 packet kurkure masala kal"}).json()["lines"][0]["match"] != "ok"
    client.post("/api/items/import?commit=1", files={"file": ("i.csv", b"name,unit\nKurkure Masala,packet\n", "text/csv")})
    d = client.post("/api/parse", json={"text": "ABC ko 5 packet kurkure masala kal"}).json()
    assert d["lines"][0]["item"]["name"] == "Kurkure Masala"
    assert client.post("/api/items/import", files={"file": ("a.xls", b"x", "application/vnd.ms-excel")}).status_code == 400
```

- [ ] **Step 2: Run** `pytest tests/test_import.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `app/importer.py`, `db.replace_items`, the route, the fixture, and add `openpyxl>=3.1` to `requirements.txt` (install into `.venv`).
- [ ] **Step 4: Run** the full suite (import tests run before `test_orders.py`) — Expected: all pass.
- [ ] **Step 5: Commit** with HANDOFF: `"Import the shop's item list from a Busy export"`

### Task 5: Parties in SQLite, auto "which Sharma", party import

**Files:**
- Modify: `app/catalog.py`, `app/matcher.py`, `app/db.py`, `app/stt.py` (no change needed if it reads the live `PARTIES` list — verify), `app/main.py`, `app/importer.py`
- Test: `tests/test_import.py`

**Interfaces:**
- `catalog`: `SAMPLE_PARTIES` = today's literal list; `PARTIES` becomes a live list (copy of samples at start) mutated in place; `PARTIES_BY_CODE` live dict; `AMBIGUOUS_PARTY_WORDS` live dict; `on_parties_change(fn)` and `replace_parties(parties: list[dict]) -> None` mirroring `on_items_change` / `replace_items`. `replace_parties` recomputes `AMBIGUOUS_PARTY_WORDS` with `ambiguous_words(parties) -> dict[str, list[str]]`: for each party take the normalized first word of its name and each alias; any key held by 2+ parties maps to their codes. Skip keys shorter than 3 chars and the generic words `{"new", "shree", "shri", "sri", "jai", "the", "m/s", "ms"}`. For the seed list this must still give `"sharma": ["P02", "P03"]` (add `"sharma ji"` too: also index "<first word> ji").
- `matcher`: `rebuild_party_index()` decorated with `@on_parties_change`, rebuilding `_PARTY_INDEX` and `_PARTY_INDEX_SET` in place (both are module-level lists/dicts used by `find_party`).
- `db`: `parties` table (`code TEXT PRIMARY KEY, name TEXT NOT NULL, aliases TEXT NOT NULL, pos INTEGER NOT NULL`), `list_parties()` (seeds from `catalog.SAMPLE_PARTIES` once, meta key `parties_seeded`), `replace_parties(parties)`.
- `main`: at start `catalog.replace_parties(db.list_parties())`; `GET /api/parties`; `POST /api/parties/import?commit=0|1` same response shape as items. `/api/config` keeps returning `parties`.
- `importer.to_parties(rows) -> tuple[list[dict], list[dict]]`: name ← `name`, `account name`, `party name`, `particulars`; group ← `group`, `parent group`, `under`; spoken names ← `aliases`, `alias`, `print name`. **If a group column exists and any row's group contains "debtor", keep only rows whose group contains "debtor"** (others skipped, reason "customer nahi"). Codes `P001…`. Aliases = lowered name + its first two words (e.g. "gupta kirana store" → "gupta kirana") + given aliases, deduped.

- [ ] **Step 1: Write the failing tests:**

```python
def test_seed_parties_still_ask_which_sharma():
    d = client.post("/api/parse", json={"text": "Sharma ji ko 10 carton Lux kal"}).json()
    assert d["party"]["status"] == "choose" and len(d["party"]["options"]) == 2

def test_busy_account_list_keeps_only_debtors_and_asks_which_one():
    data = _xlsx([["Name", "Group"],
                  ["Verma Kirana Store", "Sundry Debtors"], ["Verma Brothers", "Sundry Debtors"],
                  ["HDFC Bank", "Bank Accounts"], ["Rent", "Indirect Expenses"]])
    parties, skipped = to_parties(read_table("acc.xlsx", data))
    assert [p["name"] for p in parties] == ["Verma Kirana Store", "Verma Brothers"]
    assert {s["reason"] for s in skipped} == {"customer nahi"}
    client.post("/api/parties/import?commit=1", files={"file": ("acc.xlsx", data, "application/octet-stream")})
    d = client.post("/api/parse", json={"text": "Verma ko 10 carton Lux kal"}).json()
    assert d["party"]["status"] == "choose"
    d = client.post("/api/parse", json={"text": "Verma Brothers ko 10 carton Lux kal"}).json()
    assert d["party"]["party"]["name"] == "Verma Brothers"
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; extend the `restore_samples` fixture to restore parties.
- [ ] **Step 4: Run** the full suite — Expected: all pass (including old `test_similar_party_names_ask`).
- [ ] **Step 5: Commit** with HANDOFF: `"Parties in SQLite, import from Busy, auto which-one question"`

### Task 6: Import buttons and Parties list on the Items tab (frontend)

**Files:**
- Modify: `static/index.html` (bump `?v=`), `static/app.js` (`initItems`, `loadItems`, `renderItems` area), `static/style.css`

**Interfaces:**
- Consumes: `POST /api/items/import`, `POST /api/parties/import`, `GET /api/parties`.
- Items tab gets two buttons: "Busy se items laayein" and "Busy se parties laayein" (file input accepting `.csv,.xlsx`). Flow: upload → show preview (count, first 10 names, skipped list with reasons) → "Haan, purani list hata kar ye daalein" commits with `?commit=1` → reload lists + `state.cfg` (so the mic keyterms and the Order screen see the new data) → toast. Errors show the 400 message.
- A "Parties" list under the items list with a search box (name + spoken names), read-only.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Verify in the browser:** import `tests/data`-style CSV for items and a parties xlsx (create one locally in the scratchpad, do not commit), check preview → commit → both lists update → a typed order using a new item and "Verma" asks which party. Phone width + dark theme. No console errors.
- [ ] **Step 3: Run** full pytest. Restore a clean local DB afterwards (delete `data/orders.db` only if it holds nothing but test data — ask the owner first).
- [ ] **Step 4: Commit** with HANDOFF: `"Items tab: Busy import buttons and Parties list"`

### Task 7: Container check and deploy hand-off

**Files:**
- Modify: `HANDOFF.md` (sections 3, 7, 8), `DEPLOY.md` (note: run the Busy imports once after the first deploy; `openpyxl` now required)

- [ ] **Step 1:** If Docker is available, run `docker compose up --build`, then `curl http://localhost:8000/healthz` — Expected `{"ok": true}`. If Docker is not installed on this PC, say so in HANDOFF section 7 and ask the owner to have a friend run it (organiser tip).
- [ ] **Step 2:** Write the shop-day checklist in HANDOFF section 8: deploy (owner creates Dostack account; `SARVAM_API_KEY` as secret; volume `/data`), import Busy items + parties, enter baseline stopwatch times for 5 parchi orders, tick "Practice order" for trial runs, then real orders; download `/api/pilot.csv` at day end for the video and deck.
- [ ] **Step 3: Run** full pytest; commit `"Deploy notes and shop-day checklist"`.
