"""Learning from a better transcript, for when a local speech model runs first.

Plan (see HANDOFF section 8): a free local recogniser (e.g. Vosk small Hindi) hears the
audio first; when it is unsure, the same audio goes to Sarvam. Where the two transcripts
differ and Sarvam's words name an item, what the local model heard is a candidate spoken
name for that item. It is kept only after staff confirm that order ("haan pakka"), the
same way "Kisi item se jodo" and answered questions teach the app today
(`main._learn`). Numbers are never learned. Nothing here retrains a model.
"""
from difflib import SequenceMatcher

from .matcher import match_item
from .textnorm import norm, numbers_in


def alias_candidates(local_text: str, cloud_text: str, max_words: int = 4):
    """[(item_code, local_words)] where the local transcript said something else for an
    item the cloud transcript names. 'das carton luks' vs 'das carton lux' -> [('SP01', 'luks')]."""
    a, b = norm(local_text).split(), norm(cloud_text).split()
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "replace" or not (0 < i2 - i1 <= max_words and 0 < j2 - j1 <= max_words):
            continue
        heard, meant = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if numbers_in(heard) or numbers_in(meant):  # "das" vs "dus" is a number: never a name
            continue
        m = match_item(meant)
        if m["status"] == "ok" and match_item(heard).get("item", {}) != m["item"]:
            out.append((m["item"]["code"], heard))
    return out
