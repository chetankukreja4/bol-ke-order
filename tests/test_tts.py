"""The app speaks with a local Piper voice (hi_IN pratham): free, no internet, no key.

Hinglish words the app says ("Sahi hai? Haan pakka bolein.") are turned into
Devanagari first, because the Hindi voice reads Roman letters as English.
Item and party names stay in Roman letters: the voice reads those as English
("Lux Soap"), which is how shops say them. Numbers stay as digits.
"""
import os
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.pop("SARVAM_API_KEY", None)
os.environ["BKO_NO_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import tts
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("roman,spoken", [
    ("Sahi hai? Haan pakka bolein.", "सही है? हाँ पक्का बोलें।"),
    ("Kaun sa soap brand?", "कौन सा soap brand?"),
    ("Lux Soap kitna chahiye?", "Lux Soap कितना चाहिए?"),
    ("ABC Traders, 10 carton Lux Soap, delivery kal.", "ABC Traders, 10 carton Lux Soap, delivery कल।"),
    ("Delivery kab? Aaj, kal ya parso?", "Delivery कब? आज, कल या परसों?"),
    ("Order 5 save ho gaya.", "Order 5 save हो गया।"),
])
def test_hinglish_words_become_devanagari(roman, spoken):
    assert tts.to_speech_text(roman) == spoken


def test_every_hinglish_word_the_app_says_is_known():
    lines = ["Awaaz saaf nahi aayi, dobara bolein.", "Boliye, main sun raha hoon.",
             "Pakka nahi hoon. 'lux' matlab Lux Soap, Lifebuoy Soap?", "Order kis party ka hai?",
             "Theek hai, kuch nahi badla.", "Pehle ye batayein:", "Samjha nahi.", "Ye bahut zyada hai. Sahi quantity bolein.",
             "Kis item ki quantity badalni hai? Item ka naam bolein.",
             "Do party ka naam aaya. Ek order ek party ka hota hai; doosri party ka order alag se karein.",
             "Kaise bheja? Rickshaw, tempo ya truck?", "Kis party ka maal gaya? Party ka naam ya order number bolein.",
             "Order 6 nahi mila. Dobara bolein.", "Gupta Kirana ke 2 order khule hain: #8, #9. Order number bolein.",
             "Order 4 pehle hi truck se ja chuka hai.", "Aapne 3 order kahe, par 2 number sune.",
             "truck se gaya. Pakka?", "Theek hai, cancel.", "ABC Traders ka koi khula order nahi hai.",
             "2 order dispatch ho gaye.", "Kitna?"]
    english_ok = {"order", "party", "item", "quantity", "truck", "rickshaw", "tempo", "cancel", "dispatch", "save",
                  "lux", "soap", "lifebuoy", "abc", "traders", "gupta", "kirana", "delivery", "brand", "number"}
    left = set()
    for line in lines:
        for w in tts.to_speech_text(line).replace("'", " ").split():
            w = w.strip(".,?:;!#।").lower()
            if w and w.isascii() and w.isalpha() and w not in english_ok:
                left.add(w)
    assert not left, f"Hinglish words still in Roman letters: {sorted(left)}"


def test_voice_missing_means_browser_voice(monkeypatch):
    monkeypatch.setattr(tts, "MODEL_PATH", "does/not/exist.onnx")
    tts.reset()
    assert client.get("/api/config").json()["server_tts"] is False
    r = client.post("/api/speak", json={"text": "Sahi hai?"})
    assert r.status_code == 503 and r.json()["error"] == "voice_not_installed"


def test_speak_returns_audio_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(tts, "available", lambda: True)
    monkeypatch.setattr(tts, "_synthesize", lambda text: calls.append(text) or (b"RIFFfake", "audio/wav"))
    tts.reset()
    for _ in range(2):
        r = client.post("/api/speak", json={"text": "  Sahi hai?  "})
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == b"RIFFfake"
    assert calls == ["सही है?"]  # converted once, made once, then served from the cache


def test_empty_text_refused_and_long_text_cut(monkeypatch):
    monkeypatch.setattr(tts, "available", lambda: True)
    assert client.post("/api/speak", json={"text": "  🔊 "}).status_code == 400
    assert len(tts.clean("haan " * 1000)) <= tts.MAX_CHARS


@pytest.mark.skipif(not os.path.exists(tts.MODEL_PATH), reason="voice model not downloaded (python scripts/get_voice.py)")
def test_real_voice_makes_audio():
    tts.reset()
    audio, kind = tts._synthesize(tts.to_speech_text("Sahi hai? Haan pakka bolein."))
    assert kind in ("audio/mpeg", "audio/wav") and len(audio) > 5000


@pytest.mark.parametrize("text,want", [
    ('Astral Elbow 1"', "Astral Elbow 1 इंच"),
    ('Astral Tee 3/4"', "Astral Tee पौना इंच"),
    ('Astral Socket 1/2"', "Astral Socket आधा इंच"),
    ("Astral Bush 2x1''", "Astral Bush 2 बाय 1 इंच"),
    ("Astral Bush 1 1/2x1''", "Astral Bush डेढ़ बाय 1 इंच"),
    ("Astral Brass Ft Elbow 1*1/2", "Astral Brass Ft Elbow 1 बाय आधा"),
    ("Astral Elbow 1'' 45*", "Astral Elbow 1 इंच 45 डिग्री"),
    ("Astral Pipe 1.25' 6kg ISI", "Astral Pipe सवा 1 इंच 6 किलो ISI"),
    ("Crompton Sumercible 1.5hp Water", "Crompton Sumercible डेढ़ hp Water"),
    ("Astral Elbow 2 1/2''", "Astral Elbow ढाई इंच"),
    ("Astral Bush 3.5''", "Astral Bush साढ़े 3 इंच"),
])
def test_sizes_are_said_the_shop_way(text, want):
    """The voice said 'teen slash chaar' and 'do x ek', and dropped the inch."""
    assert tts.to_speech_text(text) == want


def test_quotes_round_what_was_heard_are_not_inches():
    said = tts.to_speech_text("Pakka nahi hoon. 'mini champ 1' matlab Crompton Mini Champ 1, Crompton Mini Champ 2?")
    assert "इंच" not in said and "'" not in said
    assert tts.to_speech_text("Order 3, 4 aur 5 truck se gaye") == "Order 3, 4 और 5 truck से गए"
