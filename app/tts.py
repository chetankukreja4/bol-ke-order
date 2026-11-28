"""The app's spoken read-back in a local Hindi voice (Piper, hi_IN "pratham").

The browser's own voice sounds robotic and mangles Hinglish. Piper runs on the
server's CPU (about 0.1 s per line), needs no key and no internet, and costs
nothing per order. Without the voice model the browser voice is used, so the
app still starts and works with nothing downloaded.

The Hindi voice reads Roman letters as English. So the Hinglish words the app
says ("Sahi hai? Haan pakka bolein.") are turned into Devanagari first, while
item and party names stay in Roman letters, where the English reading is what
shops say ("Lux Soap", "Fortune Refined Oil"). Digits are read in Hindi.

Get the model: python scripts/get_voice.py (the Docker image does it at build).
"""
import io
import os
import re
import shutil
import subprocess
import threading
import wave
from collections import OrderedDict

ROOT = os.path.join(os.path.dirname(__file__), "..")
VOICE = "hi_IN-pratham-medium"
MODEL_PATH = os.getenv("BKO_VOICE_MODEL", os.path.join(ROOT, "models", f"{VOICE}.onnx"))
MAX_CHARS = 600  # a read-back is a few hundred characters
CACHE_SIZE = 300

# Every Hinglish word the app itself says, in Devanagari. Names and English
# words (order, party, carton, delivery, truck) are left as they are.
HINGLISH = {
    "aaj": "आज", "aapne": "आपने", "aaya": "आया", "aayi": "आई", "alag": "अलग", "aur": "और", "awaaz": "आवाज़",
    "badalni": "बदलनी", "badla": "बदला", "bahut": "बहुत", "batayein": "बताएँ", "bheja": "भेजा", "bolein": "बोलें",
    "boliye": "बोलिए", "bolo": "बोलो", "chahiye": "चाहिए", "chuka": "चुका", "do": "दो", "dobara": "दोबारा",
    "doosri": "दूसरी", "ek": "एक", "gaya": "गया", "gaye": "गए", "haan": "हाँ", "hai": "है", "hain": "हैं",
    "hi": "ही", "ho": "हो", "hoon": "हूँ", "hota": "होता", "ja": "जा", "ji": "जी", "ka": "का", "kab": "कब",
    "kahe": "कहे", "kaise": "कैसे", "kal": "कल", "karein": "करें", "kaun": "कौन", "ke": "के", "khula": "खुला",
    "khule": "खुले", "ki": "की", "kis": "किस", "kitna": "कितना", "ko": "को", "koi": "कोई", "kuch": "कुछ",
    "kya": "क्या", "maal": "माल", "main": "मैं", "matlab": "मतलब", "mila": "मिला", "naam": "नाम",
    "nahi": "नहीं", "nahin": "नहीं", "pakka": "पक्का", "par": "पर", "parso": "परसों", "pehle": "पहले",
    "raha": "रहा", "saaf": "साफ़", "sa": "सा", "sahi": "सही", "samjha": "समझा", "se": "से", "sun": "सुन",
    "sune": "सुने", "theek": "ठीक", "wala": "वाला", "ya": "या", "ye": "ये", "zyada": "ज़्यादा",
    "dal": "दाल", "sabun": "साबुन", "tel": "तेल", "tarikh": "तारीख",
}

_WORD = re.compile(r"[A-Za-z]+")
_cache = OrderedDict()
_voice = None
_lock = threading.Lock()


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").replace("🔊", "")).strip()
    return text[:MAX_CHARS]


def _names():
    """Item and party names as the app says them (full, and without size words
    like '1L'), longest first, so "Main Road Stores" is never turned into Hindi."""
    from .catalog import CATALOG, PARTIES
    out = set()
    for n in [i["name"] for i in CATALOG] + [p["name"] for p in PARTIES]:
        out.add(n)
        short = " ".join(w for w in n.split() if not any(ch.isdigit() for ch in w))
        if short:
            out.add(short)
    return sorted(out, key=len, reverse=True)


def to_speech_text(text: str) -> str:
    """'Sahi hai? Haan pakka bolein.' -> 'सही है? हाँ पक्का बोलें।'"""
    text = clean(text)
    # "Pakka nahi hoon. 'mini champ 1' matlab ...": quotes round what was heard, not inch marks
    text = re.sub(r"(?<!\w)'([a-z][^']*)'(?=\s+matlab\b)", r"\1", text)
    kept = []

    def hold(m):
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    names = [n for n in _names() if any(w.lower() in HINGLISH for w in _WORD.findall(n))]
    if names:
        text = re.sub(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b", hold, text, flags=re.I)
    text = _WORD.sub(lambda m: HINGLISH.get(m.group(0).lower(), m.group(0)), text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
    text = spoken_sizes(text)
    return re.sub(r"(?<!\d)\.(?!\d)", "।", text)  # a full stop, not a decimal point


# Sizes in item names, the way a shop says them: 'Elbow 3/4"' -> "पौना इंच",
# "Bush 2x1''" -> "2 बाय 1 इंच", "1.5hp" -> "डेढ़ hp". Without this the voice says
# "teen slash chaar", "do x ek", "ek dashamlav paanch", and drops the inch.
_INCH_MARK = r"(?:''|\"|”|″|’’|'|’)"


def _say_number(v):
    whole, part = int(v), round(v - int(v), 2)
    if part == 0:
        return str(whole)
    if whole == 0:
        return {0.25: "पाव", 0.5: "आधा", 0.75: "पौना"}.get(part)
    if part == 0.5:
        return {1: "डेढ़", 2: "ढाई"}.get(whole, f"साढ़े {whole}")
    if part == 0.25:
        return f"सवा {whole}"
    if part == 0.75:
        return f"पौने {whole + 1}"
    return None


def _say(m, v):
    return _say_number(v) or m.group(0)


def spoken_sizes(text):
    if not re.search(r"\d", text):
        return text
    t = re.sub(r"(\d)\s*[*×xX]\s*(?=\d)", r"\1 बाय ", text)  # 2x1, 1*1/2
    t = re.sub(r"(\d)\*", r"\1 डिग्री", t)  # "Elbow 1'' 45*": the bend angle
    t = re.sub(r"(?<![\d.])(\d)\s+(\d{1,2})\s*/\s*(2|4|8)(?![\d/])",  # 1 1/2
               lambda m: _say(m, int(m[1]) + int(m[2]) / int(m[3])), t)
    t = re.sub(r"(?<![\d./])(\d{1,2})\s*/\s*(2|4|8)(?![\d/])",  # 3/4
               lambda m: _say(m, int(m[1]) / int(m[2])) if int(m[1]) < int(m[2]) else m[0], t)
    t = re.sub(r"(?<![\d.])(\d+)\.(25|5|75)(?![\d.])", lambda m: _say(m, float(m[0])), t)  # 1.5, 1.25
    t = re.sub(r"(?<=[\dऀ-ॿ])\s*" + _INCH_MARK, " इंच", t)
    t = re.sub(r"(?<=[\dऀ-ॿ])\s*kgs?\b", " किलो", t, flags=re.I)  # "6kg ISI" was "chhah k g"
    return re.sub(r"([ऀ-ॿ])(?=[A-Za-z])", r"\1 ", t)  # "डेढ़hp" -> "डेढ़ hp"


def available() -> bool:
    if not os.path.exists(MODEL_PATH):
        return False
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return True


def reset():
    """Forget the loaded voice and cached audio (tests, or after changing the model)."""
    global _voice
    _voice = None
    _cache.clear()


def _load():
    global _voice
    if _voice is None:
        from piper import PiperVoice
        _voice = PiperVoice.load(MODEL_PATH)
    return _voice


def _synthesize(text: str):
    """(audio bytes, content type) for one line already in speech text. mp3 when
    ffmpeg is there (smaller on mobile data), otherwise wav."""
    with _lock:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            _load().synthesize_wav(text, wf)
    wav = buf.getvalue()
    if shutil.which("ffmpeg"):
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "wav", "-i", "pipe:0", "-b:a", "48k", "-f", "mp3", "pipe:1"],
                           input=wav, capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout, "audio/mpeg"
    return wav, "audio/wav"


def speak(text: str):
    """Audio for one line the app says, from the cache when said before."""
    line = to_speech_text(text)
    if line in _cache:
        _cache.move_to_end(line)
        return _cache[line]
    out = _synthesize(line)
    _cache[line] = out
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return out
