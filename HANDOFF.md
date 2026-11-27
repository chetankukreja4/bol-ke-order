# Handoff: Bol-ke-Order

Last updated: 27 Nov 2026 (branch `teach-items`, built on `main` 85974a6). Read this first if you are picking up the project.

> **Rule for every AI agent or person working here (Claude, Codex, anyone):** after any change you commit,
> update this file in the same commit: section 3 (status), 5 (code map), 7 (checked / not checked),
> 8 (limits) and the change log in section 12. The owner switches between AI accounts when one hits its
> limit, so this file is the only memory that carries over. Write in plain English.

## 1. What this is

A voice-first prototype for **Build for Bharat (Scaler × Flow), Round 2**: "build a working voice-first prototype for India". Theme: **Livelihoods and small business**.

Problem (from Round 1): in Indian wholesale shops, phone orders are written on a parchi and typed again into billing software (Busy). It is slow, and wrong items or quantities cause returns and a second dispatch. One wholesaler we interviewed gets about 20 phone orders a day and has agreed to test the prototype.

What it does: staff speak the order in Hinglish, upload the customer's call recording / WhatsApp voice note, or paste a call transcript (from the phone's own call transcript, e.g. Samsung, or any AI app). The app shows what it heard next to what it understood, reads the order back, asks one question at a time about anything unclear, and saves only after "haan, pakka". It then prints a parchi and gives a CSV for Busy. Dispatch is also recorded by voice.

## 2. Where things are

| What | Where |
|---|---|
| Code | https://github.com/chetankukreja4/bol-ke-order (public, branch `main`) |
| Local copy | `E:\scaler\bol-ke-order` |
| Live URL | Not deployed yet. Plan: Dostack Cloud (see `DEPLOY.md`). |
| Round 1 research | `E:\scaler\Bharat_Ka_Hisaab_Research` |

## 3. Hackathon submission (deadline 30 Nov 2026, 11:59 pm, one submission per team)

| Item | Status |
|---|---|
| 1. Public GitHub code with `docker-compose.yml`, starts with no secret keys, 300+ lines of own code | Done. About 2,750 lines of app code + 300 lines of tests. Starts with no keys; a missing key shows a "key not set" label. |
| 2. YouTube demo, 3 minutes or less | **To do.** Script idea in section 9. |
| 3. Pitch deck PDF (problem, users and how many, what it depends on, launch plan), key points as text | **To do.** Notes in section 10. |
| 4. Live link (optional bonus) | **To do.** Deploy on Dostack Cloud. |

The Docker image is built and started with no keys on every push and PR by GitHub Actions (`tests` workflow), and `/healthz` answers (all three PRs green on 27 Nov). A friend running `docker compose up --build` on their own machine is still a good last check (the organisers' tip).

## 4. How it works

```
Mic → Sarvam saaras:v4 (if key) or Web Speech hi-IN ──┐
Upload m4a/ogg/mp3 → ffmpeg 25 s chunks → Sarvam STT ──┤
Pasted call transcript → app/transcript.py clean-up ───┤
                                                       ▼
                                     transcript shown on screen
                                                       ▼
                    rule parser (plain code, no LLM)
                                                       ▼
   plain code: Devanagari → Roman, spoken numbers → numbers, fuzzy item
   and party match, dates, one question at a time, corrections, checks
                                                       ▼
      read-back (voice + screen) → "haan, pakka" → SQLite → parchi + CSV
```

Main rules (from the spec):
- No LLM. All extraction, matching and number work is normal code (removed Claude on 27 Nov to keep one paid dependency).
- Never guesses: "sabun" asks the brand; weak matches show top 3; "10 ya 12" asks; "Sharma ji" asks which Sharma. Uncertain lines are yellow with "Pakka nahi hoon."
- "nahi, aath carton" changes only that line.
- Real calls mix rate talk and conditions. A clause with a quantity is kept even if it says "rate"; a pure rate question is not a line but the item it names is remembered, so "uski bees peti" / "usmein ... das peti" use it (only when such a pointer word or "agar" is said; otherwise a missing item is asked, never filled in). "agar ... toh das, nahi toh paanch" becomes one line with two quantities, so the app asks "10 ya 5?". The condition is shown on the line ("❓ Shart: agar sasta rate ...") for staff to settle with the party.
- Unclear audio → "Awaaz saaf nahi aayi, dobara bolein"; recording kept. 8 s silence → one gentle prompt. Network errors → retry; recording kept.
- Prices and discounts are never changed or stored.
- Consent note on the upload screen.
- Nothing is saved until confirm; the server checks again before saving.
- The parchi never prints what the app heard; that text is shown on screen only, below the parchi.

Pages (tabs, `#order`, `#orders`, `#dispatch`, `#items`, `#pilot`):
- **Order**: hold-to-speak mic, upload recording, paste call transcript, type, sample phrases; then Heard text → Check the order → Parchi.
- **Orders**: all orders with All / Pending / Dispatched filter; tap one to see and print its parchi.
- **Dispatch**: "Dispatch bolo" mic plus a "Waiting to go" list with one-tap mode buttons. The talk keeps context between turns (the browser sends back `order_ids` and `mode`), so "truck se" and "हां पक्का" continue it. Orders can be named by party ("ABC ka maal gaya") or number ("order 6", "6 number wala", "order 3, 4 aur 5 ek hi truck"). If speech joins numbers ("345") and no such order exists, it is split into open orders only when exactly one split fits (and matches "teeno"/"dono" if said). Everything is read back for "pakka".
- **Items**: list, search, add, edit, remove items (code, name, unit, group, spoken names). Saved in SQLite; matching and Sarvam keyterms update at once.

## 5. Code map

| File | What it does |
|---|---|
| `app/main.py` | FastAPI routes: `/api/config`, `/api/transcribe`, `/api/parse`, `/api/answer`, `/api/orders` (+ CSV), `/api/dispatch/*`, `/api/items` (list, add, edit, remove), `/healthz`, and the static page |
| `app/textnorm.py` | Devanagari → Roman, spelling clean-up, spoken numbers (das, dus, ten, pachees, do sau, दस) |
| `app/catalog.py` | 20 sample items (seed for the Items page) with Hinglish aliases, 7 parties, units, dispatch modes. `replace_items()` swaps the live item list |
| `app/matcher.py` | RapidFuzz item and party matching, brand groups, picking an option from an answer |
| `app/parser.py` | Rule-based extraction (no key needed), dates, confirm/correction/cancel words, dispatch parsing: party, mode, order numbers (`find_order_numbers`), splitting joined numbers (`split_joined_number`) |
| `app/dialog.py` | Draft order, read-back text, next question, applying answers and corrections, save checks |
| `app/stt.py` | Sarvam speech-to-text (`saaras:v4`, `translit` mode = Roman Hinglish, shop keyterms) for the live mic and uploads, ffmpeg chunking, retries, falls back to plain settings on HTTP 400 |
| `app/transcript.py` | Cleans a pasted call transcript (Samsung call transcript, other phones, AI apps): removes times, speaker labels, phone numbers; keeps contact names. Repeated lines ("10 carton Lux, theek hai") are merged in `dialog.py` |
| `app/pilot.py` | Pilot numbers: `new_stats()` starts the stats that ride in the draft (source, questions, corrections, test order); `summary()` and `csv_rows()` for `/api/pilot` and `/api/pilot.csv` (practice orders left out) |
| `app/importer.py` | Reads a Busy export (CSV or .xlsx; title rows above the header are skipped) into the item list: Busy columns Name/Alias/Group/Main Unit or simple code,name,unit,group,aliases. Units map to the app's units (unknown = piece). `.xls` is refused with a message. Also the party list (`to_parties`): ledgers under bank/expense/creditor/tax groups are skipped, Sundry Debtors and its sub-groups kept. Spoken names need letters and 3+ characters (a Busy alias like "10" is dropped). A unique first word ("Gupta") becomes a spoken name unless it is close to another party's ("Shiv"/"Shiva"). Re-import keeps the code of a party or item with the same name |
| `app/db.py` | SQLite `orders`, `items` and `parties` tables (items and parties seeded from the samples once); orders also keep `stats`, `seconds_to_confirm`, `wrong_reason` |
| `app/samples.py` | 10 Hinglish test phrases with expected results |
| `static/` | `index.html` (5 tabs: Order, Orders, Dispatch, Items, Pilot), `app.js` (mic engines, TTS, pages, dispatch talk, item add/edit/remove), `style.css` (look taken from the Codex prototype `bol-ke-order-scaler-round-2`: green ink, lime accent, white cards, pill page nav at the top; light + dark). Bump the `?v=` number on the CSS/JS links in `index.html` when you change them, so phones don't keep old files |
| `tests/test_orders.py` | 44 tests (they never read `.env`: `BKO_NO_DOTENV=1`) |
| `tests/test_import.py`, `tests/test_pilot.py`, `tests/test_bugfixes.py`, `tests/test_tts.py`, `tests/test_improvements.py`, `tests/test_review_fixes.py` | Busy imports, which-party questions, pilot numbers, one test per bug from the 27 Nov full check, the local voice, edit/cancel and the other improvements, and the code-review fixes. 151 tests in all (plus `tests/test_teach.py`) |

The server keeps no session state: the browser holds the draft order and sends it back with each answer.

## 6. Run, test, deploy

```bash
docker compose up --build          # http://localhost:8000
pytest -q                          # 151 tests (inside .venv or the container; CI runs them on every push)
```

Windows local dev (already set up): `.venv\Scripts\python -m uvicorn app.main:app --reload`

Key (optional, never commit it): `SARVAM_API_KEY` in `.env` (not `.env.example`, which is public). See `.env.example`.

Deploy: see `DEPLOY.md`. Needs a Dockerfile build, port 8000, HTTPS, a volume at `/data`, health check `/healthz`.

## 7. What is checked and what is not

Checked:
- **Docker** (GitHub Actions on every push: `docker compose up --build` with no keys, then the health check, the main screen and one typed order; first green on PRs #1, #2, #3 on 27 Nov): the image builds (on `codex-look` and `improvements` it also downloads the voice model), starts with no keys, and `/healthz` answers. Docker is still not installed on the dev PC. Memory use on a 512 MB host is not measured.
- 145 tests pass (on `improvements`: 9+1 review-fix and 8 improvement tests, 11 voice tests, 44 bug tests on `codex-look`, 28 on `pilot-ready` for imports and pilot numbers; plus rate talk + "uski" + agar/nahi toh call from the owner's screenshot, numbers, Devanagari, all 10 phrases, small talk, two quantities, unknown items, similar parties, corrections, nothing saved before confirm, API flow, CSV, items add/edit/remove, pasted transcripts in 4 formats, dispatch context, Hindi "haan pakka", order numbers, several orders, joined numbers, "key not set").
- Sarvam with the real key: called and working (about 0.7 s for a 10 s clip). Tested with a Windows text-to-speech sample, not a real person yet.
- In the browser at phone and desktop size: all four tabs, items add/edit/remove, order flow to parchi, old parchi view, paste transcript, dispatch talk (with the last dispatch step stubbed so real orders were not changed). Light and dark themes.
- The owner tried the live mic on a laptop: orders and dispatch work; the screenshots led to the dispatch fixes above.
- ffmpeg chunking: a 70 s file becomes 3 chunks.
- The server start command and health check work.

Not checked yet:
- **A real Busy export**: the importer was tested with Busy-style files we made (title rows, Name/Alias/Group/Main Unit, Sundry Debtors). Import the shop's real file once and look at the preview before saying yes.
- **Phone microphone over HTTPS**: needs a deploy. The header pill "Mic: Sarvam AI ⇄" switches between Sarvam and the browser recogniser; the browser one writes Devanagari and mishears numbers and "truck" more often.
- **A real Samsung call transcript**: the four formats tested were written by us. Paste one real copy to check.
- **Upload of a real call recording** through Sarvam.
- Real shop noise and accents.

## 8. Known limits and next steps

- **Shop-day checklist (pilot):**
  1. Deploy (`DEPLOY.md`): Chetan creates the host account; `SARVAM_API_KEY` as a secret; volume at `/data`. Start with a fresh `/data` (old test orders would count in the pilot numbers).
  2. In Busy, export the item list and the account list to Excel (.xlsx) or CSV. On the Items tab: "Busy se items laayein", then "Busy se parties laayein"; check the preview, then "Haan".
  3. Before using the app, time 5 normal phone orders with a stopwatch (call end → entry done in Busy). Pilot tab → "Pehle ka time" → type the seconds.
  4. Tick "Practice order" while staff try it out; untick for real orders.
  5. When a saved order turns out wrong, open it in Orders → "Galat nikla?" → pick why.
  6. End of day: Pilot tab → "CSV" for the video and the deck.
- **Next (approved 27 Nov, branch `pilot-ready`):** shop-ready + pilot numbers before 30 Nov. Busy export import for items and parties, parties moved to SQLite, numbers saved with every order (time to confirm, questions, corrections, "Galat nikla"), a Pilot tab with CSV, then deploy and test in the shop. Design: `docs/superpowers/specs/2026-11-27-pilot-ready-design.md`. Why: the Round 2 masterclass (VC speaker) stressed real-user testing in person and before/after numbers; no rubric was published.
- Items are managed on the Items page (add, edit, remove; saved in SQLite). Parties are now in SQLite (seeded from the 7 samples) and both lists can be replaced from a Busy export.
- Orders can be cancelled or edited until they are dispatched, not deleted. For a clean demo, run with `BKO_DEMO=1` and use Demo reset on the Pilot tab.
- The browser's speech recognition works best in Chrome/Edge and needs internet. Browsers without it (e.g. Firefox) fall back to recording + server STT, which needs the Sarvam key.
- On Android Chrome the live mic does not also keep a recording (the mic can't be shared), so "retry with the same recording" only works for uploads and desktop.
- No login, one shop only, no dues or payments module (kept out on purpose).
- Busy integration is CSV only.
- Optional shop PIN: set `BKO_PIN` on the host and the app asks for it once (kept 90 days as a cookie). Without it the app stays open, as before.
- Cost: each long call through Sarvam costs money. Measure the cost per order during the pilot; the shop owner said he would pay about ₹2,000 a year.

## 9. Demo video plan (≤ 3 min)

1. 0:00–0:20 Problem: parchi + typing into Busy, wrong orders = returns.
2. 0:20–1:30 Phone, hold **Order bolo**: "ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena" → read-back → "Kaun sa soap brand?" → "Lux" → "nahi, aath carton" → "haan, pakka" → parchi + CSV.
3. 1:30–2:00 Upload a WhatsApp voice note with small talk and bargaining; show that it is ignored.
4. 2:00–2:20 Unknown item → top 3 options, yellow "Pakka nahi hoon".
5. 2:20–2:40 Dispatch: "Order 3, 4 aur 5 ek hi truck mein gaye" → read-back → "haan pakka". Also show Paste call transcript and the Items page if time allows.
6. 2:40–3:00 Pilot plan: 3 shops, 30 days, the three numbers we measure.

## 10. Pitch deck notes

- Problem and solution: sections 1 and 4.
- Users: wholesale shop owners and staff. Start with 3 pilot shops (one has agreed). Do not claim a national count we have not verified.
- What it depends on: Sarvam STT (the only paid service, per minute), browser speech recognition (free), ffmpeg, SQLite. No LLM. If Sarvam stops working or gets too costly, the live mic switches to the browser's free recogniser and typing always works; only uploads stop until another STT provider is plugged into `app/stt.py`.
- Launch plan: pilot in 3 shops for 30 days, measure (1) time from end of call to confirmed order, target under 1 minute; (2) returned or re-dispatched orders, target half; (3) 95% of orders saved with no later correction, and staff using it for 15 of 20 daily orders. Then other shops in the same market through the first wholesaler's network.

## 11. Accounts

- GitHub: `chetankukreja4` (repo owner).
- Hosting: Dostack Cloud (to be set up by Chetan). Keys go only in the host's secret settings.

## 12. Change log (newest first)

| Commit | What changed |
|---|---|
| teach items (branch `teach-items`) | A yellow line ("Pakka nahi hoon") now has "Kisi item se jodo" (pick an item; the heard words become its spoken name, unless another item already uses them or it is a generic word like "sabun") and "Naya item banao" (add-item form filled with the heard words; saving links the line). `POST /api/teach`. Only staff link; the app never does. For shops with their own catalog (PVC fittings, pipes, tanks): import Busy first, then teach the words from 5-10 practice recordings. Checked in the browser on a scratch DB |
| CI compose (branch `ci-compose`) | The Docker CI job now does what the organisers do: `docker compose up --build` with no keys, then `/healthz`, the main screen (`/`, app.js, style.css), "key not set" in `/api/config`, and one typed order through `/api/parse` |
| Docker checked (branch `improvements`) | HANDOFF: the Docker build passes in CI; the CI row moved from section 2 to this change log |
| CI (all branches) | `.github/workflows/tests.yml`: every push and PR runs `pytest` and builds the Docker image, starts it with no keys and checks `/healthz` |
| review fixes 2 (branch `improvements`) | From the code review of the whole branch: an order that waited offline is never dropped (a refused one shows "order atka hai" and opens to fix), and the wait is not counted as order time (`offline_seconds`); Busy sub-groups like "Wholesale Parties" stay customers (whole-word group check); grouped exports read sub-group heading rows; PIN login allows 5 wrong tries per 10 minutes per address and never 500s on odd characters; late pending orders can be edited, and a new order with a past date says "pichhli hai"; the day can be changed by voice ("nahi, parso", or just "kal" when the date has passed); cancelled orders say "cancel ho chuka hai" in dispatch; item and party names keep their English reading in the voice. 145 tests; offline flow checked in the browser |
| improvements (branch `improvements`) | Edit a saved order (it comes back to Check the order; voice or taps change it; same number, `edited_at`) and Cancel it (status `cancelled`, left out of pending, dispatch and pilot numbers); "Aaj jaana" filter (pending, due today or late); "Aaj ki Busy CSV" (`/api/orders.csv?day=today`, every order of the day, no limit); parchi on WhatsApp (wa.me link, the shop picks the contact); an order confirmed with no network waits on the phone and is saved when it is back (draft id stops duplicates); Sarvam keyterms put the most-ordered items first; Demo reset on the Pilot tab, only with `BKO_DEMO=1` and RESET typed. Already done earlier: shop PIN, open-order count in dispatch, Practice order layout. Checked in the browser on a scratch DB. Not pushed |
| local voice (branch `codex-look`) | The app speaks with a local Piper Hindi voice (hi_IN pratham, chosen by the owner): `app/tts.py`, `POST /api/speak`, Hinglish words turned into Devanagari, names stay English. Free, no key; ~0.1 s per line after the first. `python scripts/get_voice.py` downloads the model (64 MB, git-ignored in `models/`); the Dockerfile does it at build. Without it the browser voice is used. Checked in the browser: a full order (read-back, brand answer, confirm, saved) spoke 4 lines from `/api/speak`, all played, no fallback, no console errors. How it sounds was judged by the owner from samples. Not pushed |
| bug fixes (branch `codex-look`) | From the 27 Nov full check: "pakka nahi" / "save mat karo" / "sahi hai kya" never save; one draft saves one order (double tap, network retry); "rehne do" changes nothing; dozen and gram are units; the day said last wins and "kal nahi" is dropped; two parties in one call ask; a party with two open orders asks which in dispatch; "Waiting to go" taps ask "Pakka?"; the Orders list keeps every pending order; an item said without a quantity asks "kitna?"; save takes names from the lists and checks unit, date (up to 60 days) and quantity (max 9999); "10 se 12" asks which; re-dispatch refused, mode checked; "Galat nikla" has Undo; a spoken name used by another item is refused; grouped Busy exports skip headings and bank rows; ffmpeg no longer blocks the server; optional `BKO_PIN`. Checked in the browser on a scratch DB. Not pushed |
| Codex layout (branch `codex-look`) | Pages rebuilt in the Codex structure: heading row (title left, action right), content in white cards, equal two-column cards (Order: voice / paste; Dispatch: voice / waiting list; Done: parchi / next steps; Pilot: details / baseline), 3x2 pilot tiles, text-only page nav, footer. Paste box shows first; "Type the order instead" swaps it (same JS). Order lines show the name left and quantity right. Not pushed |
| Codex look (branch `codex-look`) | New look from the Codex prototype: `style.css` rewritten, Order page split into two cards (Voice or recording / Paste or type), "b." brand mark, page nav at the top on phones too. Only CSS and HTML wrappers changed; `app.js`, the backend and every element ID are the same. Checked in the browser: all tabs, the order flow, desktop and phone, light and dark |
| review fixes (branch `pilot-ready`) | After a whole-branch review: exact full item names are accepted even with a generic word ("toor dal", "haldi powder"), a "which brand?" never has zero options and shows at most 8; Busy group only from an exact name; numeric/short aliases dropped and numbers never name a party; near-same party names ("Shiv"/"Shiva") ask; party and item codes stay the same on re-import; Sarvam keyterms keep 20 parties first; odd CSV bytes read; the pilot clock starts when staff start the order (browser sends `elapsed`), and the Pilot tab says what is timed |
| deploy notes (branch `pilot-ready`) | Shop-day checklist (section 8); DEPLOY.md: import Busy lists after the first deploy |
| import buttons (branch `pilot-ready`) | Items tab: "Busy se items laayein" / "Busy se parties laayein" (preview, then "Haan" replaces the list) and a read-only Parties list. Checked in the browser on a scratch DB: CSV with a title row, 3 items + 2 debtor parties loaded, "Verma ko ..." asks which Verma, new item matched |
| party import (branch `pilot-ready`) | Parties in SQLite (`parties` table); `GET /api/parties`, `POST /api/parties/import` (only Sundry Debtors when the file has groups). "Which Sharma?" words are worked out from the list (`catalog.ambiguous_words`), so imported parties ask too |
| item import (branch `pilot-ready`) | `POST /api/items/import` (preview; `?commit=1` replaces the item list). Needs `openpyxl` (added to requirements) |
| pilot tab (branch `pilot-ready`) | Pilot tab (numbers, baseline stopwatch times, CSV); "Galat nikla" on a saved parchi; "Practice order" tick on the Order page; the app sends mic/upload/transcript/typed. Checked in the browser on a scratch DB: 3 orders, one marked wrong, phone size, dark theme |
| pilot numbers saved (branch `pilot-ready`) | Orders save `stats` + `seconds_to_confirm` (old DBs get the new columns automatically); `POST /api/orders/{id}/wrong` (Galat nikla); `GET /api/pilot`, `/api/pilot.csv`, `PUT /api/pilot/baseline` |
| pilot stats (branch `pilot-ready`) | Each draft carries `stats`: start time, source, questions answered, corrections; `/api/parse` takes `source` and `test` |
| plan (branch `pilot-ready`) | Implementation plan `docs/superpowers/plans/2026-11-27-pilot-ready.md` (7 tasks; 1-3 first) |
| design doc (branch `pilot-ready`) | Design for shop-ready + pilot numbers; no code change yet |
| parser fix (after `948189e`) | Parser: keep order clauses that mention rate, "uski/usmein" point to the last item, "agar ... nahi toh" gives two quantities to ask; condition shown on the line |
| `d5bc63c` | Dispatch keeps context between turns; Hindi "हां पक्का" works; find orders by number; several orders in one truck; split joined numbers like 345 |
| `e33375e` | Parchi no longer prints the heard text; nicer dates |
| `69e458d` | Four tabs (Order, Orders, Dispatch, Items); Items page backed by SQLite; Paste call transcript; Hindi title removed |
| `afcf5db` | Live mic uses Sarvam `saaras:v4` (translit + keyterms) when the key is set; LLM (Claude) removed, Sarvam is the only paid service |
| `24eeee3` | Handoff and deploy docs; container ready for the cloud |
| `0160eb6` | Dark theme |
| `1c7a054` | First version |
