# Bol-ke-Order · बोल के ऑर्डर

A voice-first order taker for Indian wholesale shops. Staff speak the order in Hinglish, upload the customer's call recording or WhatsApp voice note, or paste a call transcript. The app shows what it heard next to what it understood, reads the order back, asks **one question at a time** about anything unclear, and saves **only after "haan, pakka"**. It then prints a parchi and gives a CSV for entry into billing software such as Busy. Dispatch is recorded by voice too.

> "ABC wale ko 10 carton sabun, 5 carton tel, kal bhej dena"
> → *"ABC Traders, 10 carton soap, 5 carton Fortune Refined Oil, delivery kal. Kaun sa soap brand?"*
> → "Lux" → "nahi, aath carton" → "haan, pakka" → **Parchi #1 saved**

Built for **Build for Bharat (Scaler × Flow), Round 2**, theme *Livelihoods and small business*. New to the project? Read **[HANDOFF.md](HANDOFF.md)**.

## Run it (one command)

```bash
docker compose up --build
```

Open http://localhost:8000. **No keys are needed**: the main screen, the browser microphone, the Hinglish parser, read-back (local Hindi voice), questions, saving, parchi, CSV, dispatch, imports and the pilot numbers all work without any key. A feature that needs a key shows "key not set". CI runs exactly this command on every push and checks the main screen.

Optional settings (copy `.env.example` to `.env`, or set them on the host):

| Setting | What it adds | Without it |
|---|---|---|
| `SARVAM_API_KEY` | Sarvam `saaras:v4` speech-to-text (Roman Hinglish, tuned with the shop's party names and most-ordered items) for the live mic and uploaded recordings up to 10 minutes | The live mic uses the browser's speech recognition; uploads say "Speech key not set" |
| `BKO_PIN` | A shop PIN, asked once per phone (5 wrong tries per 10 minutes) | Anyone with the link can open the app |
| `BKO_DEMO=1` | "Demo reset" on the Pilot tab (deletes every order) for a clean demo video | No reset button. Never set it on the shop's real app |

There is **no LLM**. Order understanding is plain code, so it costs nothing per order and keeps working if an AI service goes away. Sarvam is the only paid service.

Without Docker:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
python scripts/get_voice.py                                          # local Hindi voice (~64 MB), optional
.venv/bin/uvicorn app.main:app --reload
```

The live mic needs Chrome or Edge and HTTPS (or localhost).

## How it works

```
mic → Sarvam (if key) or browser speech hi-IN ──────┐
upload m4a/ogg/mp3 → ffmpeg 25 s chunks → Sarvam ───┤
pasted call transcript → clean-up ──────────────────┤
                                                    ▼
                                    heard text (shown on screen)
                                                    ▼
      rule parser: clauses; small talk, rate questions and talk about
      things not on the list are dropped
                                                    ▼
   code only: Devanagari → Roman, spoken numbers, fuzzy match to the shop's
   items and parties, dates, one question at a time, corrections, checks
                                                    ▼
   read-back (local Piper Hindi voice) → "haan, pakka" → SQLite → parchi + CSV
```

* **Never guesses.** A generic word ("sabun") asks the brand. A weak match shows the top three and asks. Two quantities ("10 ya 12", "10 se 12") ask. Two parties with the same name ("Sharma ji") ask which. A party with two open orders asks which in dispatch. Uncertain lines are yellow with "Pakka nahi hoon."
* **Corrections:** "nahi, aath carton" changes only that line; "nahi, parso" changes only the day; "rehne do" changes nothing.
* **"Pakka nahi" never saves.** Only a real yes ("haan pakka") or the Confirm button saves, and one order is saved once even on a double tap or a network retry.
* **Prices and discounts are never stored**; bargaining talk is ignored.
* **Consent:** the Order page reminds staff that recording a customer's call needs their consent.

## Pages

Light and dark theme (follows the phone; 🌙/☀ to switch). Look based on our Codex prototype.

* **Order**: hold-to-speak mic, upload a recording, paste a transcript or type; then Heard text → Check the order → Parchi.
  * On a yellow line: **🔗 Kisi item se jodo** (link it to an item; the heard words are learned as its spoken name), **＋ Naya item banao** (new item filled with the heard words), **✕ Hatao** (drop a line the app got wrong).
  * After saving: print, CSV, **WhatsApp par bhejo**, **Edit** or **Cancel** (until dispatched), **Galat nikla** (with Undo).
  * No network at Confirm: the order waits on the phone and is saved when the network is back.
* **Orders**: All / **Aaj jaana** (due today or late) / Pending / Dispatched; **Aaj ki Busy CSV** (every order of the day) and a review sheet.
* **Dispatch**: "Dispatch bolo" ("ABC ka maal gaya, rickshaw se", "order 3, 4 aur 5 ek hi truck") with read-back and "haan pakka"; a "Waiting to go" list where a tap asks "Pakka?" first.
* **Items**: the shop's items and parties. **Busy / Excel se items (parties) laayein** with a preview; blank **Excel templates** for shops without Busy; add, edit, remove; search.
* **Pilot**: numbers for the shop test (orders, time to confirm, questions, corrections, orders right after saving, stopwatch "before" times), CSV, and "Practice order" to leave trials out.

## Data

SQLite (`/data/orders.db` in Docker): `orders` (party, lines, delivery date, status `confirmed`/`dispatched`/`cancelled`, dispatch mode and date, heard text, pilot stats, wrong reason, edit and cancel times), `items` and `parties` (seeded once from the samples in `app/catalog.py`, then the shop's own lists). Ten Hinglish test phrases are in `app/samples.py` ("Try sample phrases" in the app).

## Tests

```bash
.venv/bin/pytest -q          # or inside the container
```

163 tests: spoken numbers, Devanagari, the 10 test phrases, small talk and rate talk, real-call lines, corrections, "nothing saved before confirm", the full API flow, Busy and Excel imports, which-party questions, teaching words, the local voice, pilot numbers, edit/cancel, offline save, PIN, and one test per bug found in the reviews. GitHub Actions runs them, then `docker compose up --build` with no keys, on every push and pull request.

## Deploy (public URL)

One Docker container: build from the `Dockerfile` (it also downloads the voice model), port `8000` (or `$PORT`), HTTPS on, a persistent volume at `/data`, health check `/healthz`, and `BKO_PIN` set. Steps: **[DEPLOY.md](DEPLOY.md)**.

## Project layout

```
app/        FastAPI backend: main (routes), dialog, parser, matcher, textnorm, transcript,
            stt (Sarvam), tts (Piper voice), importer (Busy / Excel), pilot, db, catalog, samples
static/     index.html, app.js, style.css (light + dark)
scripts/    get_voice.py (downloads the local Hindi voice)
tests/      pytest suite (163 tests)
.github/    CI: pytest + docker compose start check
Dockerfile, docker-compose.yml, render.yaml, .env.example
HANDOFF.md  status, what is tested, next steps, demo and deck notes
DEPLOY.md   how to host it
```

## Not in this prototype

Dues and payments, multiple shops, user accounts (one optional shop PIN only), importing items from a bill photo or PDF (it would need OCR or an LLM), direct Busy integration (CSV only).
