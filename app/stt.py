"""Server-side speech-to-text for uploaded recordings (Sarvam AI, Hindi/English/Hinglish).

Long audio (call recordings, WhatsApp notes up to 10 minutes) is cut into
25-second chunks with ffmpeg and sent chunk by chunk, with retries, so no
single request times out. Needs SARVAM_API_KEY; without it the app says
"key not set" and the browser's own speech recognition is used for live mic.
With the key set, the live mic also records and sends audio here (better on
noisy shop floors and Hinglish than the browser's recogniser).
"""
import asyncio
import glob
import os
import shutil
import subprocess
import tempfile

import json

import httpx

from .catalog import CATALOG, PARTIES

SARVAM_URL = os.getenv("SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text")
SARVAM_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
# translit = Roman-script Hinglish ("10 carton lux sabun"), which the parser reads directly.
SARVAM_MODE = os.getenv("SARVAM_STT_MODE", "translit")
SARVAM_LANG = os.getenv("SARVAM_STT_LANG", "hi-IN")


def _keyterms():
    """Shop words that bias recognition (Sarvam allows 50 terms of up to 64 chars)."""
    terms = []
    for it in CATALOG:
        terms.append(it["name"])
    for p in PARTIES:
        terms.append(p["name"])
    # Only names. Unit words like "katta"/"bori" made Sarvam hear "carton" as "katta".
    seen, out = set(), []
    for t in terms:
        if t.lower() not in seen and len(t) <= 64:
            seen.add(t.lower()); out.append(t)
    return out[:50]


def _form(minimal=False):
    data = {"model": SARVAM_MODEL, "language_code": SARVAM_LANG}
    if not minimal and SARVAM_MODEL.startswith("saaras"):
        data["mode"] = SARVAM_MODE
        if SARVAM_MODEL == "saaras:v4":
            data["keyterms"] = json.dumps(_keyterms())  # follows the Items page
    return data
CHUNK_SECONDS = 25
MAX_SECONDS = 10 * 60 + 5


class KeyNotSet(Exception):
    pass


class AudioError(Exception):
    pass


def stt_available() -> bool:
    return bool(os.getenv("SARVAM_API_KEY")) and shutil.which("ffmpeg") is not None


def duration_seconds(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def split_audio(src: str, workdir: str):
    """Convert to 16 kHz mono WAV and cut into CHUNK_SECONDS pieces."""
    pattern = os.path.join(workdir, "chunk%03d.wav")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "16000",
                        "-f", "segment", "-segment_time", str(CHUNK_SECONDS), pattern],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AudioError("Could not read this audio file")
    return sorted(glob.glob(os.path.join(workdir, "chunk*.wav")))


async def _transcribe_chunk(client, path, key, attempts=3):
    last, minimal = None, False
    for n in range(attempts):
        try:
            with open(path, "rb") as f:
                resp = await client.post(
                    SARVAM_URL,
                    headers={"api-subscription-key": key},
                    files={"file": (os.path.basename(path), f, "audio/wav")},
                    data=_form(minimal),
                )
            if resp.status_code in (401, 403):
                raise KeyNotSet("Speech key rejected")
            if resp.status_code in (400, 422) and not minimal:
                # Model/mode/keyterms not accepted on this account: retry with plain settings.
                last, minimal = httpx.HTTPStatusError(resp.text[:200], request=resp.request, response=resp), True
                continue
            resp.raise_for_status()
            return resp.json().get("transcript", "")
        except (httpx.HTTPError, ValueError) as e:
            last = e
            await asyncio.sleep(1.5 * (n + 1))
    raise AudioError(f"Speech service failed: {last}")


async def transcribe_file(src: str) -> dict:
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise KeyNotSet("SARVAM_API_KEY not set")
    if shutil.which("ffmpeg") is None:
        raise AudioError("ffmpeg not installed")
    secs = duration_seconds(src)
    if secs > MAX_SECONDS:
        raise AudioError("Recording is longer than 10 minutes")
    workdir = tempfile.mkdtemp(prefix="bko_")
    try:
        chunks = split_audio(src, workdir)
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=60) as client:
            async def run(p):
                async with sem:
                    return await _transcribe_chunk(client, p, key)
            parts = await asyncio.gather(*(run(p) for p in chunks))
        text = " ".join(p.strip() for p in parts if p and p.strip())
        return {"transcript": text, "chunks": len(chunks), "seconds": round(secs, 1)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
