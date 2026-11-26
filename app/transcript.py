"""Clean a pasted call transcript before the order parser reads it.

Phones (Samsung "Call transcript", Pixel, iPhone call recording notes) and AI
tools (Sarvam, Whisper, ChatGPT) write transcripts in many shapes:

    Speaker 1  00:03                 [00:03] Me: haan bolo
    Haan ji, 10 carton Lux bhejna    Gupta Kirana (0:12): 10 carton Lux
    +91 98765 43210 10:32 AM         Speaker 2 - 10 carton Lux

This strips timestamps and speaker labels, keeps contact names (they often
name the party), and joins the rest into plain text. Plain code, no AI.
"""
import re

# 0:12, 00:03, 01:02:33, 10:32 AM, with optional brackets / parentheses
_TIME = r"[\[(]?\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?\s*[\])]?"
_TIME_RE = re.compile(_TIME, re.I)
_PHONE_RE = re.compile(r"\+?\d[\d\s-]{8,}\d")
# Words a transcript uses for "who is speaking" that are not a shop or person name.
_GENERIC = {"speaker", "speakers", "person", "caller", "receiver", "me", "you", "i", "mai", "main",
            "customer", "client", "shop", "shopkeeper", "dukaan", "dukandar", "owner", "staff",
            "agent", "user", "unknown", "other", "s1", "s2", "a", "b"}
# Header lines some apps add.
_HEADER_RE = re.compile(r"^(call\s+(transcript|summary|recording|notes?)|transcript|summary|"
                        r"(incoming|outgoing|missed)\s+call|duration\b.*|\d{1,2}\s+\w{3,9}\s+\d{4}.*|"
                        r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}.*)\s*:?$", re.I)
# "Name: text", "Name - text", "Name (0:12): text" at the start of a line
_INLINE_LABEL_RE = re.compile(r"^\s*([A-Za-zऀ-ॿ+][\wऀ-ॿ .'&+-]{0,40}?)\s*(?:" + _TIME + r")?\s*[:\-–—]\s+(.*)$")


def _label_words(label: str):
    return [w for w in re.split(r"\s+", label.strip()) if w]


def _is_label(label: str) -> bool:
    """Short text that names a speaker rather than saying something."""
    words = _label_words(label)
    if not words or len(words) > 4 or re.search(r"[:.?!,]", label.strip()):
        return False
    if _PHONE_RE.fullmatch(label.strip()):
        return True
    low = [w.lower().strip(".") for w in words]
    if low[0] in _GENERIC:  # Speaker 1, Me, Caller 2 ...
        return all(w in _GENERIC or w.isdigit() for w in low)
    # A name: no digits (quantities have digits) and starts with a capital letter.
    return not any(ch.isdigit() for ch in label) and words[0][:1].isupper()


def _keep_name(label: str):
    """Contact names are kept once (they help find the party); generic labels are dropped."""
    low = [w.lower().strip(".") for w in _label_words(label)]
    if not low or low[0] in _GENERIC or _PHONE_RE.fullmatch(label.strip()):
        return None
    return label.strip()


def looks_like_transcript(text: str) -> bool:
    """True when the text has the timestamps or speaker labels of a call transcript."""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return False
    marked = sum(1 for l in lines if _TIME_RE.search(l) or _INLINE_LABEL_RE.match(l) and _is_label(_INLINE_LABEL_RE.match(l).group(1)))
    return marked >= 2


def clean_transcript(text: str) -> dict:
    """Returns {"text": plain text for the parser, "names": contact names seen, "turns": number of turns}."""
    names, parts, turns = [], [], 0
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip().strip("‎‏")
        if not line or _HEADER_RE.match(line):
            continue
        had_time = bool(_TIME_RE.search(line))
        line = re.sub(r"^\s*" + _TIME + r"\s*[-–—|]?\s*", "", line, flags=re.I)  # "[00:03] Me: ..."
        m = _INLINE_LABEL_RE.match(line)
        if m and _is_label(m.group(1)):
            label, line = m.group(1), m.group(2)
            turns += 1
            n = _keep_name(label)
            if n and n not in names:
                names.append(n)
        line = _TIME_RE.sub(" ", line).strip(" -–—:|")
        if not line:
            if had_time:
                turns += 1
            continue
        if had_time and _is_label(line):  # "Speaker 1  00:03" or "Gupta Kirana 10:32 AM" on its own line
            turns += 1
            n = _keep_name(line)
            if n and n not in names:
                names.append(n)
            continue
        if _PHONE_RE.fullmatch(line):
            continue
        parts.append(line.rstrip(" ,"))
    body = ". ".join(p.rstrip(".") for p in parts)
    if names:
        body = f"{', '.join(names)}. {body}" if body else ", ".join(names)
    return {"text": body.strip(), "names": names, "turns": turns}
