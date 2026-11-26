# Bol-ke-Order · बोल के ऑर्डर

A voice-first order taker for Indian wholesale shops. Staff speak the order in Hinglish (or upload the customer's call recording / WhatsApp voice note). The app shows what it heard next to what it understood, reads the order back, asks **one question at a time** about anything unclear, and saves **only after "haan, pakka"**. It then prints a parchi and gives a CSV review sheet for entry into billing software such as Busy.

> "ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena"
> → *"ABC Traders, 10 carton soap, 5 carton Fortune Refined Oil, delivery kal. Kaun sa soap brand?"*
> → "Lux" → "nahi, aath carton" → "haan, pakka" → **Parchi #1 saved**

Built for **Build for Bharat (Scaler × Flow), Round 2**, theme *Livelihoods and small business*. New to the project? Read **[HANDOFF.md](HANDOFF.md)**.

## Run it (one command)

```bash
docker compose up --build
```

Open http://localhost:8000. **No keys are needed** to start: the main screen, the browser microphone, the rule-based Hinglish parser, read-back, questions, saving, parchi, CSV and dispatch all work without any key. Features that need a key show a "key not set" label.

Optional keys (copy `.env.example` to `.env`):

| Key | What it adds | Without it |
|---|---|---|
| `SARVAM_API_KEY` | Server speech-to-text (Sarvam `saarika`, Hindi/English/Hinglish) for uploaded recordings, up to 10 minutes, processed in 25 s chunks | Uploads say "Speech key not set"; live mic uses the browser's speech recognition |
| `ANTHROPIC_API_KEY` | Claude extracts fields from messy call transcripts (party, item, quantity words, unit, date) as JSON | Built-in rule parser does the extraction |

Without Docker:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --reload
```

Live mic needs Chrome or Edge (Web Speech API) and HTTPS or localhost.

## How it works

```
mic (browser speech, hi-IN)  ─┐
upload m4a/ogg/mp3 ─► ffmpeg 25s chunks ─► Sarvam STT ─┤
                                                      ▼
                                         transcript (shown on screen)
                                                      ▼
            LLM (optional): copy fields to JSON — no matching, no maths
            or rule parser: clauses, small talk + bargaining dropped
                                                      ▼
   code only: Devanagari→Roman, spoken numbers → int, fuzzy match to catalog,
   party match, date, one question at a time, corrections, validation
                                                      ▼
        read-back (TTS + screen) ─► "haan, pakka" ─► SQLite ─► parchi + CSV
```

* **The LLM never decides anything.** It only copies the words that were said. Numbers ("das", "dus", "ten", "pachees", "25", "do sau", "दस") are converted in `app/textnorm.py`; items are matched with RapidFuzz in `app/matcher.py`.
* **Never guesses.** A generic word ("sabun") asks the brand. A weak match shows the top three and asks. Two quantities ("10 ya 12") ask. Two similar parties ("Sharma ji") ask which. Uncertain lines are yellow with "Pakka nahi hoon."
* **Corrections** like "nahi, aath carton" change only that one line.
* **Noise:** low confidence or empty text → "Awaaz saaf nahi aayi, dobara bolein", and the recording is kept for retry. 8 s of silence → one gentle prompt. Network failure → request retried, recording kept.
* **Prices and discounts are never changed or stored**; bargaining talk is ignored.
* **Consent:** the upload screen reminds staff that recording a customer's call needs their consent.

## Screens

Light and dark theme: follows the phone setting, with a 🌙/☀ button in the header to switch (remembered on the device).

Home (Order bolo, upload, dispatch, recent orders) → Transcript (heard text, editable) → Confirm (heard vs understood, question, voice answer) → Done (printable parchi, CSV).

Dispatch by voice: "ABC ka maal gaya, rickshaw se" → read back → "haan pakka" → order marked dispatched with mode and today's date.

## Data

SQLite table `orders`: party, items, quantities, units, delivery date, status (`confirmed`/`dispatched`), dispatch mode and date, heard text, created time. Sample catalog (20 items with Hinglish aliases) and parties are in `app/catalog.py`; 10 Hinglish test phrases in `app/samples.py` (also clickable in the app under "Try sample phrases").

## Tests

```bash
docker compose run --rm bol-ke-order pytest -q      # or: .venv/bin/pytest -q
```

33 tests cover spoken numbers, Devanagari input, all 10 test phrases, small talk/bargaining, two quantities, unknown items, similar parties, line-only corrections, "nothing saved before confirm", the full API flow, CSV and dispatch.

## Deploy (public URL)

One Docker container: build from the `Dockerfile`, port `8000` (or `$PORT`), HTTPS on, a persistent volume at `/data`, health check `/healthz`. Step-by-step for Dostack Cloud or any Docker host, a VPS, or Render: **[DEPLOY.md](DEPLOY.md)**.

## Project layout

```
app/        FastAPI backend (main, dialog, parser, matcher, textnorm, stt, llm, db, catalog, samples)
static/     index.html, app.js, style.css (light + dark)
tests/      pytest suite (33 tests)
Dockerfile, docker-compose.yml, render.yaml, .env.example
HANDOFF.md  status, what is tested, next steps, demo and deck notes
DEPLOY.md   how to host it
```

## Not in this prototype

Dues and payments, login, multiple shops, editing the catalog from the UI, Busy integration (CSV only).
