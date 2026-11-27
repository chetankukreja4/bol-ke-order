# Design: shop-ready + pilot numbers

Date: 27 Nov 2026. Approved by the owner. Next: implementation plan.


## Context
Round 2 closes **30 Nov 2026 EOD** (confirmed in the Scaler × Wispr Flow masterclass, YouTube `zcuAyQ0ZbEg`).
No rubric was published. The speaker (a VC) said judges look for a proven problem → a better way,
**value then usability tested in person with a real user**, frequency/scale, why voice, and distribution.
The wholesaler has agreed to test in the shop before 30 Nov. So the additions make the app work on
**their** data and **measure** each order, giving real before/after numbers for the video and deck.
Chosen approach: **A — shop-ready + metrics** (over B "demo polish" and C "imports + deploy only").
Item and party lists will come from a **Busy export** (Excel/CSV).

## Goals / non-goals
- Goals: load the shop's real items and parties from a Busy export; record numbers for every order;
  show them on one page and as CSV; deploy over HTTPS so the phone mic works in the shop.
- Non-goals: prices, payments, login, multi-shop, changing the no-LLM rule, voice-quality work.
- Anti-goals: numbers that can't be traced to real saved orders; anything that slows the order flow for staff.

## Design

### 1. Busy import for items and parties (`app/importer.py`, new)
- One endpoint each: `POST /api/items/import`, `POST /api/parties/import` (multipart file; `.csv` or `.xlsx`).
  Two-step: first call returns a **preview** (rows found, rows skipped with reasons, codes that clash);
  `?commit=1` saves. Mode: **replace** sample data (the pilot starts clean) — confirm prompt in the UI.
- Header matching is case/space-insensitive with Busy names first: `Name`, `Alias`, `Group`, `Unit`
  (also `Main Unit`, `Item Name`, `Account Name`, `Print Name`), plus simple ones: `code, name, unit, group, aliases`.
  `aliases` split on `|` or `,`. Missing code → generated (`I001…`, `P001…`). The name and Busy alias
  are always added as spoken names. Group kept as text; only known groups (soap/detergent/dal) trigger
  the brand question.
- `.xlsx` via `openpyxl` (add to `requirements.txt`); find the header row by scanning the first ~10 rows
  (Busy exports often start with a title block).
- Reuse: `db.save_item` / `db.list_items`, `catalog.replace_items()` (already rebuilds the matcher index
  and Sarvam keyterms).

### 2. Parties move from code to SQLite (like items)
- `parties` table in `app/db.py` (code, name, aliases JSON, pos), seeded once from `catalog.PARTIES`
  (same `meta` flag pattern as `items_seeded`).
- `catalog.replace_parties()` + change hook, mirroring `replace_items()`; `matcher._PARTY_INDEX`,
  `PARTIES_BY_CODE` and `stt` keyterms rebuild on change.
- `AMBIGUOUS_PARTY_WORDS` computed automatically: any first word / alias shared by 2+ parties
  (so "Sharma" asks "which Sharma" with real data too). Keep the hard-coded entries as seed only.
- UI: a **Parties** section on the Items tab: list + search + import button. (No add/edit form —
  my call, to save time; edits go through re-import.)

### 3. Numbers saved with every order
- The draft carries `stats` (browser keeps it, server stays stateless):
  `started_at` (server time at `/api/parse`), `source` (mic / upload / transcript / typed),
  `questions` (count of questions answered in `dialog.answer`), `corrections` (each "nahi, …" applied),
  `uncertain_start` (yellow lines when first parsed), `lines`.
- `save_order` stores `stats` JSON + `seconds_to_confirm` (now − started_at). New columns added with a
  guarded `ALTER TABLE` (old DBs keep working).
- **"Galat nikla"** button on a saved order's parchi (Orders tab): reason picker (wrong item / wrong qty /
  wrong party / missing item / other) → `wrong_reason`, `wrong_at`. This is the "fixed after saving" number.
- Optional manual baseline: a field on the Pilot page to enter "parchi + Busy typing" times measured with a
  stopwatch before the pilot (stored in `meta`), so before/after sit side by side.

### 4. Pilot page (`#pilot` tab) + CSV
- Shows: orders saved (today / all), median and average seconds to confirm, % orders with zero
  questions, % with no correction after save, corrections per order, source split, baseline vs app.
- `GET /api/pilot` (JSON) and `GET /api/pilot.csv` (one row per order with all stats) for the deck.
- A "test order" toggle on the Order page so demo/practice orders are excluded from pilot numbers.

### 5. Deploy
- Follow `DEPLOY.md` (Dostack Cloud, Docker, volume at `/data`, `/healthz`, HTTPS, `SARVAM_API_KEY` as a secret).
  Needs Chetan to create the host account. Run `docker compose up --build` once before (never run yet).

### Order of work (fits 3 days; cut from the bottom)
1. Order stats + Galat nikla + Pilot page (core proof) — day 1
2. Busy import for items, then parties in SQLite + import — day 1–2
3. Deploy + shop test — day 2
4. Baseline field, test-order toggle — if time

## Files
- New: `app/importer.py`, `tests/test_import.py`, `tests/test_pilot.py`, sample `tests/data/busy_items.xlsx`/`.csv`.
- Change: `app/db.py`, `app/catalog.py`, `app/matcher.py`, `app/stt.py`, `app/dialog.py`, `app/main.py`,
  `static/index.html` (new tab, bump `?v=`), `static/app.js`, `static/style.css`, `requirements.txt`,
  `HANDOFF.md` (sections 3, 5, 7, 8, 12 in the same commit — repo rule), and the design doc at
  `docs/superpowers/specs/2026-11-27-pilot-ready-design.md`.

## Calls I made (check these)
- Import replaces sample data rather than merging.
- Parties: import + list only, no edit form.
- "Time to confirm" starts when the app first reads the order (it can't know when the phone call ended).

## Left to the builder
Exact Busy column variants seen in the real file; Pilot page layout; reason list wording.

## Verification
- `pytest -q` (existing 42 + new import and stats tests): Busy-style xlsx with a title block, CSV with simple
  headers, duplicate codes, shared "Sharma" first word → ambiguity question, stats counted through
  `/api/parse` → `/api/answer` (question + correction) → `/api/orders`, Galat nikla, `/api/pilot` numbers.
- Run locally (`.venv\Scripts\python -m uvicorn app.main:app --reload`), import a sample Busy file in the
  browser, place 3 orders by typing/mic, mark one "Galat nikla", check the Pilot page and CSV.
- `docker compose up --build` once; after deploy, phone mic over HTTPS in the shop.
