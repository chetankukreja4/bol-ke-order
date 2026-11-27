# Handoff: Bol-ke-Order

Last updated: 27 Nov 2026 (branch `fix/real-call-pipes`, built on `main` 41e3e84). Read this first if you are picking up the project.

> **Rule for every AI agent or person working here (Claude, Codex, anyone):** after any change you commit,
> update this file in the same commit: section 3 (status), 5 (code map), 7 (checked / not checked),
> 8 (limits) and the change log in section 12. The owner switches between AI accounts when one hits its
> limit, so this file is the only memory that carries over. Write in plain English.

## 1. What this is

A voice-first prototype for **Build for Bharat (Scaler × Flow), Round 2**: "build a working voice-first prototype for India". Theme: **Livelihoods and small business**.

Problem (from Round 1): in Indian wholesale shops, phone orders are written on a parchi and typed again into billing software (Busy). It is slow, and wrong items or quantities cause returns and a second dispatch. One wholesaler we interviewed gets about 20 phone orders a day and has agreed to test the prototype.

What it does: staff speak the order in Hinglish, upload the customer's call recording / WhatsApp voice note, or paste a call transcript (from the phone's own call transcript, e.g. Samsung, or any AI app). The app shows what it heard next to what it understood, reads the order back in a local Hindi voice, asks one question at a time about anything unclear, and saves only after "haan, pakka". It then prints a parchi, shares it on WhatsApp and gives a CSV for Busy. Dispatch is also recorded by voice. The shop's own items and parties come from a Busy export or a filled Excel template, and staff teach the app their words from the order screen. A Pilot tab measures time, questions and corrections for the deck.

## 2. Where things are

| What | Where |
|---|---|
| Code | https://github.com/chetankukreja4/bol-ke-order (public, branch `main`) |
| CI | GitHub Actions `tests` workflow: pytest, then `docker compose up --build` with no keys and a check of the main screen |
| Local copy | `E:\scaler\bol-ke-order` |
| Live URL | Not deployed yet. Host not chosen: `render.yaml` is ready; dostack.ai looked like an AI app builder rather than a Docker host (from its home page only, not confirmed). The rules say "You host it yourself". |
| Round 1 research | `E:\scaler\Bharat_Ka_Hisaab_Research` |

## 3. Hackathon submission (deadline 30 Nov 2026, 11:59 pm, one submission per team)

| Item | Status |
|---|---|
| 1. Public GitHub code with `docker-compose.yml`, starts with no secret keys, 300+ lines of own code | Done. About 4,800 lines of app code + 1,400 lines of tests. Starts with no keys; a missing key shows "key not set". CI checks this on every push. |
| 2. YouTube demo, 3 minutes or less | **To do.** Plan in section 9. Record it from the real shop test. |
| 3. Pitch deck PDF (problem, users and how many, what it depends on, launch plan), key points as text | **To do.** Notes in section 10. Use the Pilot tab numbers. |
| 4. Live link (optional bonus) | **To do.** Also needed for the phone mic (HTTPS). See `DEPLOY.md`. |

Plan agreed on 27 Nov: feature freeze; only fix what the real shop test shows. Day 1 deploy + import the shop's lists + practice run; day 2 real orders in the shop (record the video, download the Pilot CSV); day 3 fixes, deck, video; submit on the 30th well before 11:59 pm.

A friend running `docker compose up --build` on their own machine is still a good last check (the organisers' tip).

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
   read-back (local Piper voice + screen) → "haan, pakka" → SQLite → parchi + CSV
```

Main rules:
- No LLM. All extraction, matching and number work is normal code (Claude was removed on 27 Nov to keep one paid dependency).
- Never guesses: "sabun" asks the brand; weak matches show top 3; "10 ya 12" / "10 se 12" ask; "Sharma ji" asks which Sharma; two parties in one call ask which; a party with two open orders asks which in dispatch. Uncertain lines are yellow with "Pakka nahi hoon." Only staff link a line to an item.
- "nahi, aath carton" changes only that line; "nahi, parso" only the day; "rehne do" changes nothing. "Pakka nahi", "save mat karo", "sahi hai kya" never save.
- Real calls mix rate talk, conditions and chat. A clause with a quantity is kept even if it says "rate"; a pure rate question is not a line but the item it names is remembered, so "uski bees peti" uses it. "agar ... toh das, nahi toh paanch" becomes one line with two quantities. A generic word with no quantity ("dal rahe ho" is the verb) and a question about something not on the list ("advertisement kitna pada hoga") are talk, not lines.
- The day said last wins ("aaj order, kal bhejna" = kal); a day followed by "nahi" is dropped. "kal parson" together means "some day soon" and is not a day; "abhi" counts only next to a send word ("abhi bhej do"), not in "abhi yahan rakha hai".
- Sizes are part of the item name, never a quantity: `textnorm.glue_sizes` turns "1 inch", `3/4"`, `1 1/2''`, "sawa inchi", "chaar by teen", "40mm", "1 hp", and a pipe class after a size ("3 inch 6 kg", "saadhe das kilo ke") into one token ("1inch", "0.75inch", "1.5inch", "1.25inch", "4x3", "40mm", "1hp", "6kg"), the same way for the Busy names and for what staff say. The matcher scores letters and sizes apart, so "elbow 1 inch" is never Elbow 2"; staff may drop the brand on a list full of it ("end cap 1 inch" = Astral End Cap 1''); a model number ends a name ("mini champ 1"). Questions say the size (`Astral Elbow 1"` or `Astral Elbow 2"`).
- Politeness is not a party ("ji sahab" is not Jain Sahab: the name word itself must be close). A number followed by "rupaye" is a price; fare talk ("kiraya") about nothing on the list is not a line. "bundle" is a unit. In a long call (40+ words), a line with no item, only a vehicle, or a whole sentence that matches nothing is talk; short new names ("pachas motor") stay for "Naya item banao".
- Unclear audio → "Awaaz saaf nahi aayi, dobara bolein"; recording kept. 8 s silence → one gentle prompt. Network errors → retry; recording kept. No network at Confirm → the order waits on the phone and is saved later (never dropped; a refused one shows "order atka hai" to fix).
- Prices and discounts are never changed or stored.
- Nothing is saved until confirm; the server checks again before saving (names come from the lists, unit known, date real and near, quantity up to 9999) and saves one draft only once.
- The parchi never prints what the app heard; that text is shown on screen only.

Pages (tabs `#order`, `#orders`, `#dispatch`, `#items`, `#pilot`):
- **Order**: hold-to-speak mic, upload recording, paste call transcript, type, sample phrases, "Practice order" tick; then Heard text → Check the order → Parchi. Yellow lines have **Kisi item se jodo** (link + learn the heard words), **Naya item banao**; every line has **Hatao**. After saving: print, CSV, WhatsApp, Edit, Cancel, Galat nikla (with Undo).
- **Orders**: All / Aaj jaana / Pending / Dispatched; tap one to see its parchi; "Aaj ki Busy CSV" and a review sheet.
- **Dispatch**: "Dispatch bolo" mic plus a "Waiting to go" list whose mode buttons ask "Pakka?" first. The talk keeps context between turns, so "truck se" and "हां पक्का" continue it. Orders can be named by party or number ("order 6", "order 3, 4 aur 5 ek hi truck"); joined numbers ("345") are split only when exactly one split fits. Cancelled orders say "cancel ho chuka hai".
- **Items**: items and parties; Busy / Excel import with preview; blank Excel templates; add, edit, remove, search. A spoken name used by another item is refused.
- **Pilot**: orders, time to confirm, questions, corrections, % right after saving, stopwatch baseline, CSV; Demo reset only with `BKO_DEMO=1`.

## 5. Code map

| File | What it does |
|---|---|
| `app/main.py` | FastAPI routes: `/api/config`, `/api/login` (PIN), `/api/transcribe`, `/api/parse`, `/api/answer`, `/api/teach`, `/api/line/remove`, `/api/orders` (save, list, `/draft` for edit, `/cancel`, `/wrong`, `/dispatch`, CSVs incl. `?day=today`), `/api/dispatch/parse`, `/api/items` and `/api/parties` (list, add, edit, remove, `/import`, `/template.xlsx`), `/api/pilot` (+ CSV, baseline), `/api/demo/reset`, `/api/speak`, `/healthz`, the static page, and the optional PIN middleware |
| `app/textnorm.py` | Devanagari → Roman, spelling clean-up, spoken numbers (das, dus, ten, pachees, do sau, दस), sizes as one token (`glue_sizes`, `is_size`) |
| `app/catalog.py` | 20 sample items and 7 sample parties (seeds), units (incl. dozen, gram, bundle), dispatch modes, live lists with `replace_items()` / `replace_parties()`, which-party words worked out from the list |
| `app/matcher.py` | RapidFuzz item and party matching (sizes scored apart from letters; names without a brand that 3+ items share; party name word must be close), brand groups, lead checks, picking an option from an answer |
| `app/parser.py` | Rule-based extraction, dates, confirm / correction / leave-it words, two-party detection, talk filters, dispatch parsing (party, mode, order numbers, joined numbers) |
| `app/dialog.py` | Draft order, read-back, next question, answers and corrections, `link_line` (teach), `remove_line`, `draft_from_order` (edit), save checks |
| `app/stt.py` | Sarvam speech-to-text (`saaras:v4`, `translit`, keyterms: parties then most-ordered items), ffmpeg chunking off the main thread, retries |
| `app/tts.py` | Local Piper Hindi voice (`hi_IN-pratham-medium`): Hinglish words → Devanagari (names stay English), mp3 via ffmpeg, cache |
| `app/transcript.py` | Cleans a pasted call transcript: removes times, speaker labels, phone numbers |
| `app/importer.py` | Busy / Excel / CSV import for items and parties (header found under title rows; whole-word customer groups; grouped exports; stable codes; spoken names need 3+ letters) and the blank Excel templates |
| `app/pilot.py` | Pilot stats in the draft (start time, source, questions, corrections, test order, offline wait), `summary()`, `csv_rows()` |
| `app/db.py` | SQLite `orders`, `items`, `parties`, `meta`; one order per draft id; edit, cancel, wrong / undo, orders of a day, most-ordered items, demo reset |
| `app/samples.py` | 10 Hinglish test phrases with expected results |
| `scripts/get_voice.py` | Downloads the Piper voice into `models/` (git-ignored); the Dockerfile runs it |
| `static/` | `index.html` (5 tabs), `app.js` (mic engines, voice, pages, teach dialog, offline queue, PIN prompt, imports), `style.css` (Codex look; light + dark). Bump `?v=` on the CSS/JS links when you change them |
| `.github/workflows/tests.yml` | CI: pytest; then `docker compose up --build` with no keys, `/healthz`, main screen, "key not set", one typed order |
| `tests/` | 207 tests (`test_orders`, `test_import`, `test_pilot`, `test_bugfixes`, `test_tts`, `test_improvements`, `test_review_fixes`, `test_teach`, `test_template`, `test_junk_lines`, `test_real_calls` with `tests/fixtures/pipe_items.csv`, a cut of a real pipe/pump list without prices). They never read `.env` (`BKO_NO_DOTENV=1`) |

The server keeps no session state: the browser holds the draft order and sends it back with each answer.

## 6. Run, test, deploy

```bash
docker compose up --build          # http://localhost:8000
pytest -q                          # 207 tests (CI runs them, then the compose check, on every push)
```

Windows local dev (already set up): `.venv\Scripts\python -m uvicorn app.main:app --reload`. Restart a server started without `--reload` after pulling new code: the page loads new JavaScript at once, but old Python keeps running (this caused "still same" on 27 Nov).

Key (optional, never commit it): `SARVAM_API_KEY` in `.env` (not `.env.example`, which is public).

Deploy: see `DEPLOY.md`. Needs a Dockerfile build, port 8000, HTTPS, a volume at `/data`, health check `/healthz`, and `BKO_PIN`.

## 7. What is checked and what is not

Checked:
- **207 tests pass** locally (CI runs on the PR).
- **Docker** (GitHub Actions on every push and PR): `docker compose up --build` with no keys, `/healthz`, the main screen, "key not set", one typed order. Docker is not installed on the dev PC. Memory use on a 512 MB host is not measured.
- **Sarvam** with the real key: about 0.7 s for a 10 s clip (tested with a Windows text-to-speech sample).
- **Local voice**: a full order spoke 4 lines from `/api/speak` in the browser with no fallback; the owner chose the voice from samples.
- **Browser** (scratch database, phone and desktop, light and dark): every tab, order flow to parchi, edit, cancel, Galat nikla + Undo, WhatsApp link text, Aaj jaana, Busy CSV, offline queue (blocked network, queued, saved once; a passed date shown as "atka hai" and fixed by voice), demo reset, Busy-style imports, Excel template download, teach (Jodo / Naya item, learned for the next order), Hatao.
- **Owner's real calls**: rate talk / "uski" / agar-nahi toh (fixed), and a pump/motor shop call where talk became lines (fixed; verified on the restarted server).
- **A real wholesaler's Busy item lists** (231 pipe fittings, 90 pumps; title rows, Sale Price column ignored) imported with nothing skipped, and **two real call recordings** (5.5 and 3 minutes) through Sarvam upload: no party, day, fare or size guessed; sized lines like "elbow sawa inchi tees" became 30 x Astral Elbow 1 1/4". Checked on a scratch DB, not in the browser.

Not checked yet:
- **Deploy and the phone microphone over HTTPS.**
- **The shop's party list from Busy** (items checked; parties tested with Busy-style files we made). Look at the preview before saying yes.
- **A real Samsung call transcript** copied from a phone.
- **WhatsApp link on a real phone.**
- Real shop noise and accents; staff using it for a full day.

## 8. Known limits and next steps

- **Shop-day checklist (pilot):**
  1. Deploy (`DEPLOY.md`): `SARVAM_API_KEY` and `BKO_PIN` as secrets; volume at `/data`; start with a fresh `/data` (old test orders would count in the pilot numbers). Never set `BKO_DEMO` there.
  2. Items tab: "Busy / Excel se items laayein", then parties; check the preview, then "Haan". No Busy? Fill the blank Excel template.
  3. Tick "Practice order" and run 5-10 of the shop's old recordings; on each yellow line use "Kisi item se jodo" / "Naya item banao", and "Hatao" for talk. The app learns the shop's words.
  4. Time 5 normal phone orders with a stopwatch (call end → entry done in Busy). Pilot tab → "Pehle ka time".
  5. Untick "Practice order" for real orders. When a saved order turns out wrong: Orders → open it → "Galat nikla?" (or Edit / Cancel before dispatch).
  6. End of day: Pilot tab → "CSV" for the video and the deck; Orders → "Aaj ki Busy CSV" for billing.
- The browser's speech recognition works best in Chrome/Edge and needs internet. Browsers without it fall back to recording + server STT, which needs the Sarvam key.
- On Android Chrome the live mic does not also keep a recording, so "retry with the same recording" only works for uploads and desktop.
- One shop only; no accounts beyond the optional PIN; no dues or payments (kept out on purpose).
- Busy integration is CSV only. Bill photo / PDF import was dropped (it would need OCR or an LLM).
- A brand that is not in the item list (the "Prakash" and "Aeromax" pipes in the real calls) stays a yellow line: add it to Busy or with "Naya item banao". A call still gives some yellow lines that are talk ("ek box", "chalis guna"); staff "Hatao" them.
- A Piper voice reads names in English; Hinglish words the app says are mapped to Devanagari by a fixed word list in `app/tts.py` (add new words there).
- Cost: Sarvam speech-to-text per minute is the only per-order cost; the voice is local and free. Measure the cost per order in the pilot; the shop owner said he would pay about ₹2,000 a year.

## 9. Demo video plan (≤ 3 min)

1. 0:00–0:20 Problem: parchi + typing into Busy, wrong orders = returns (shop footage).
2. 0:20–1:20 Phone in the shop, hold **Order bolo** on a real order → the app reads it back in Hindi → one question → "haan, pakka" → parchi, WhatsApp.
3. 1:20–1:50 Upload a real call recording with chat and bargaining: the talk is ignored; an unknown item is yellow → "Kisi item se jodo" → next order understands it.
4. 1:50–2:15 Dispatch by voice: "Order 3, 4 aur 5 ek hi truck mein gaye" → read-back → "haan pakka".
5. 2:15–2:40 Pilot tab: real numbers from the test day (time to confirm vs the stopwatch baseline, % right after saving).
6. 2:40–3:00 Launch plan: 3 shops, 30 days, the three numbers we measure.

## 10. Pitch deck notes

- Problem and solution: sections 1 and 4. Show the real shop numbers from the Pilot CSV.
- Users: wholesale shop owners and staff (kirana, hardware / PVC, pump and motor shops). Start with 3 pilot shops (one has agreed). Do not claim a national count we have not verified.
- What it depends on: Sarvam speech-to-text (the only paid service, per minute); the browser's free recogniser as a fallback; Piper Hindi voice (local, free); ffmpeg; SQLite. No LLM. If Sarvam stops working or gets too costly, the live mic switches to the browser's recogniser and typing / pasting always works; only recording uploads stop until another STT provider is plugged into `app/stt.py`.
- Onboarding: Busy export or a filled Excel template; the app learns the shop's own words from the order screen.
- Launch plan: pilot in 3 shops for 30 days, measure (1) time from end of call to confirmed order, target under 1 minute; (2) returned or re-dispatched orders, target half; (3) 95% of orders right after saving, and staff using it for 15 of 20 daily orders. Then other shops in the same market through the first wholesaler's network.

## 11. Accounts

- GitHub: `chetankukreja4` (repo owner).
- Hosting: Dostack Cloud (to be set up by Chetan). Keys go only in the host's secret settings.

## 12. Change log (newest first)

| Commit | What changed |
|---|---|
| real calls, pipes (branch `fix/real-call-pipes`) | From a real wholesaler's Busy lists and two call recordings: sizes are part of the name, never a quantity ("10 elbow 1 inch" was 2 lines, "3/4" was 3 and 4); size-aware matching, brand may be dropped, model numbers ("mini champ 1"); questions say the size; "ji sahab" no longer picks Jain Sahab; "rupaye" after a number and fare talk are not lines; "bundle" unit; "kal parson" and "abhi" in talk are not a delivery day; long calls drop item-less and sentence lines; an item said as "nahi hain" is not a line. Also fixed: clauses never split at "aur" (a backspace character was in the regex). 207 tests |
| docs (branch `docs-update`) | README rewritten for main; HANDOFF sections 1-10 brought up to date (pages, rules, code map, checks, shop-day checklist, demo and deck notes); DEPLOY host notes and checks updated |
| junk lines (branch `junk-lines`) | From a real pump/motor shop call: a generic word with no quantity ("dal rahe ho" is the verb daalna) and a question about something not on the list ("advertisement kitna pada hoga") no longer become order lines; "bhejun" is filler. Every line has "✕ Hatao" to drop a line the app got wrong (`POST /api/line/remove`, counted as a correction). Real unknown items ("pachas motor", "barah submersible") still become yellow lines |
| Excel template (branch `excel-template`) | Shops without Busy fill a plain Excel sheet: `GET /api/items/template.xlsx` and `/api/parties/template.xlsx` (header row only, plus a "Kaise bharein" help sheet; no example rows that could be imported by mistake). Import buttons now say "Busy / Excel se ...". The importer reads the sheet that has a Name header even if the help sheet was open when saved, and parties accept a "Spoken names" column. Bill photo / PDF import was considered and dropped: it would need OCR or an LLM |
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
