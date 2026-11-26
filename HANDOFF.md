# Handoff: Bol-ke-Order

Last updated: 27 Nov 2026. Read this first if you are picking up the project.

## 1. What this is

A voice-first prototype for **Build for Bharat (Scaler × Flow), Round 2**: "build a working voice-first prototype for India". Theme: **Livelihoods and small business**.

Problem (from Round 1): in Indian wholesale shops, phone orders are written on a parchi and typed again into billing software (Busy). It is slow, and wrong items or quantities cause returns and a second dispatch. One wholesaler we interviewed gets about 20 phone orders a day and has agreed to test the prototype.

What it does: staff speak the order in Hinglish, or upload the customer's call recording / WhatsApp voice note. The app shows what it heard next to what it understood, reads the order back, asks one question at a time about anything unclear, and saves only after "haan, pakka". It then prints a parchi and gives a CSV for Busy. Dispatch is also recorded by voice.

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
| 1. Public GitHub code with `docker-compose.yml`, starts with no secret keys, 300+ lines of own code | Done. About 1,900 lines. Starts with no keys; missing keys show a "key not set" label. |
| 2. YouTube demo, 3 minutes or less | **To do.** Script idea in section 9. |
| 3. Pitch deck PDF (problem, users and how many, what it depends on, launch plan), key points as text | **To do.** Notes in section 10. |
| 4. Live link (optional bonus) | **To do.** Deploy on Dostack Cloud. |

Before submitting: ask a friend to clone the repo and run `docker compose up --build` on their machine (the organisers' tip). It has not been run in Docker yet (section 7).

## 4. How it works

```
Browser mic (Web Speech, hi-IN) ──┐
Upload m4a/ogg/mp3 → ffmpeg 25 s chunks → Sarvam STT ──┤
                                                       ▼
                                     transcript shown on screen
                                                       ▼
        Claude (optional) copies fields to JSON  ─or─  rule parser
                                                       ▼
   plain code: Devanagari → Roman, spoken numbers → numbers, fuzzy item
   and party match, dates, one question at a time, corrections, checks
                                                       ▼
      read-back (voice + screen) → "haan, pakka" → SQLite → parchi + CSV
```

Main rules (from the spec):
- The LLM only copies words that were said. All matching and number work is normal code.
- Never guesses: "sabun" asks the brand; weak matches show top 3; "10 ya 12" asks; "Sharma ji" asks which Sharma. Uncertain lines are yellow with "Pakka nahi hoon."
- "nahi, aath carton" changes only that line.
- Unclear audio → "Awaaz saaf nahi aayi, dobara bolein"; recording kept. 8 s silence → one gentle prompt. Network errors → retry; recording kept.
- Prices and discounts are never changed or stored.
- Consent note on the upload screen.
- Nothing is saved until confirm; the server checks again before saving.

## 5. Code map

| File | What it does |
|---|---|
| `app/main.py` | FastAPI routes: `/api/config`, `/api/transcribe`, `/api/parse`, `/api/answer`, `/api/orders` (+ CSV), `/api/dispatch/*`, `/healthz`, and the static page |
| `app/textnorm.py` | Devanagari → Roman, spelling clean-up, spoken numbers (das, dus, ten, pachees, do sau, दस) |
| `app/catalog.py` | 20 sample items with Hinglish aliases, 7 parties, units, dispatch modes |
| `app/matcher.py` | RapidFuzz item and party matching, brand groups, picking an option from an answer |
| `app/parser.py` | Rule-based extraction (no key needed), dates, confirm/correction words, dispatch parsing |
| `app/llm.py` | Optional Claude extraction (`claude-opus-5-5`, structured JSON output, refusal fallback). Falls back to rules on any error |
| `app/dialog.py` | Draft order, read-back text, next question, applying answers and corrections, save checks |
| `app/stt.py` | Sarvam speech-to-text for uploads, ffmpeg chunking, retries |
| `app/db.py` | SQLite `orders` table |
| `app/samples.py` | 10 Hinglish test phrases with expected results |
| `static/` | `index.html`, `app.js` (mic, TTS, screens), `style.css` (light + dark theme) |
| `tests/test_orders.py` | 33 tests |

The server keeps no session state: the browser holds the draft order and sends it back with each answer.

## 6. Run, test, deploy

```bash
docker compose up --build          # http://localhost:8000
pytest -q                          # 33 tests (inside .venv or the container)
```

Windows local dev (already set up): `.venv\Scripts\python -m uvicorn app.main:app --reload`

Keys (all optional, never commit them): `SARVAM_API_KEY`, `ANTHROPIC_API_KEY`. See `.env.example`.

Deploy: see `DEPLOY.md`. Needs a Dockerfile build, port 8000, HTTPS, a volume at `/data`, health check `/healthz`.

## 7. What is checked and what is not

Checked:
- 33 tests pass (numbers, Devanagari, all 10 phrases, small talk, two quantities, unknown items, similar parties, corrections, nothing saved before confirm, API flow, CSV, dispatch, "key not set").
- Full flow in a browser at phone size: sample phrase → brand question → correction → confirm → parchi → dispatch. Both light and dark themes.
- ffmpeg chunking: a 70 s file becomes 3 chunks.
- The server start command and health check work.

Not checked yet:
- **Docker build**: Docker is not installed on the dev PC. The Dockerfile is simple, but run it once before submitting.
- **Real microphone**: the preview browser blocks the mic. Test in Chrome on a phone over HTTPS.
- **Sarvam** with a real key: the request follows Sarvam's REST API (`/speech-to-text`, model `saarika:v2.5`, header `api-subscription-key`) but has never been called. Upload one real recording.
- **Claude** with a real key: never called. On any error it falls back to the rule parser, so the app keeps working.
- Real shop noise and accents: only typed and sample text tested so far.

## 8. Known limits and next steps

- Catalog and parties are hard-coded sample data. Next: load the pilot shop's real item list (CSV import).
- The browser's speech recognition works best in Chrome/Edge and needs internet. Browsers without it (e.g. Firefox) fall back to recording + server STT, which needs the Sarvam key.
- On Android Chrome the live mic does not also keep a recording (the mic can't be shared), so "retry with the same recording" only works for uploads and desktop.
- No login, one shop only, no dues or payments module (kept out on purpose).
- Busy integration is CSV only.
- Cost: each long call through Sarvam + Claude costs money. Measure the cost per order during the pilot; the shop owner said he would pay about ₹2,000 a year.

## 9. Demo video plan (≤ 3 min)

1. 0:00–0:20 Problem: parchi + typing into Busy, wrong orders = returns.
2. 0:20–1:30 Phone, hold **Order bolo**: "ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena" → read-back → "Kaun sa soap brand?" → "Lux" → "nahi, aath carton" → "haan, pakka" → parchi + CSV.
3. 1:30–2:00 Upload a WhatsApp voice note with small talk and bargaining; show that it is ignored.
4. 2:00–2:20 Unknown item → top 3 options, yellow "Pakka nahi hoon".
5. 2:20–2:40 Dispatch: "ABC ka maal gaya, rickshaw se".
6. 2:40–3:00 Pilot plan: 3 shops, 30 days, the three numbers we measure.

## 10. Pitch deck notes

- Problem and solution: sections 1 and 4.
- Users: wholesale shop owners and staff. Start with 3 pilot shops (one has agreed). Do not claim a national count we have not verified.
- What it depends on: browser speech recognition (free), Sarvam STT (paid per minute), Claude (paid per token), ffmpeg, SQLite. If Sarvam or Claude stop working or get too costly, the live mic and rule parser still work; uploads stop until another STT provider is plugged into `app/stt.py`.
- Launch plan: pilot in 3 shops for 30 days, measure (1) time from end of call to confirmed order, target under 1 minute; (2) returned or re-dispatched orders, target half; (3) 95% of orders saved with no later correction, and staff using it for 15 of 20 daily orders. Then other shops in the same market through the first wholesaler's network.

## 11. Accounts

- GitHub: `chetankukreja4` (repo owner).
- Hosting: Dostack Cloud (to be set up by Chetan). Keys go only in the host's secret settings.
