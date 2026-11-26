"""Optional LLM field extraction (Claude). Used only when ANTHROPIC_API_KEY is set.

The LLM only copies spoken fields out of messy call text into JSON. It does not
match items, convert numbers or do any arithmetic: quantities come back as the
words that were said ("das", "10 ya 12") and normal code converts them.
"""
import json
import logging
import os

from .matcher import find_party
from .parser import _UNIT_WORDS, parse_date
from .textnorm import norm, numbers_in

log = logging.getLogger("bol-ke-order.llm")
MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

SYSTEM = """You read transcripts of phone calls and voice notes at Indian wholesale shops.
They are in Hinglish (Hindi + English), sometimes in Devanagari, often noisy.
Copy out ONLY the order fields as JSON. Rules:
- party_text: the customer/shop name exactly as spoken (nickname is fine), or "".
- delivery_text: the delivery day words as spoken ("kal", "parso", "Monday"), or "".
- lines: one per ordered item. item_text = item words as spoken (e.g. "sabun", "lux", "sarson tel").
  quantity_spoken = the quantity words exactly as spoken, e.g. "das", "10", "pachees".
  If two different quantities were said for the same item, keep both, e.g. "10 ya 12".
  If the speaker corrected themselves ("das nahi, aath"), keep only the final quantity.
  unit_spoken = unit word as spoken ("carton", "peti", "bori", "packet") or "".
- Ignore greetings, small talk, bargaining, prices, discounts, payment talk. Never output prices.
- Do not convert, guess or fix anything. Do not invent items that were not said."""

SCHEMA = {
    "type": "object",
    "properties": {
        "party_text": {"type": "string"},
        "delivery_text": {"type": "string"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_text": {"type": "string"},
                    "quantity_spoken": {"type": "string"},
                    "unit_spoken": {"type": "string"},
                },
                "required": ["item_text", "quantity_spoken", "unit_spoken"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["party_text", "delivery_text", "lines"],
    "additionalProperties": False,
}


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _call_claude(transcript: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(max_retries=2, timeout=60)
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Transcript:\n{transcript}"}],
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def extract_llm(transcript: str):
    """Same output shape as parser.extract_rules, or None if the call fails."""
    try:
        data = _call_claude(transcript)
    except Exception as e:  # network, key, quota: fall back to rules
        log.warning("LLM extraction failed, using rules: %s", e)
        return None
    party_res, _ = find_party(data.get("party_text", "")) if data.get("party_text") else (
        {"status": "missing", "party": None, "options": []}, None)
    lines = []
    for ln in data.get("lines", []):
        vals = numbers_in(ln.get("quantity_spoken", ""))
        unit = _UNIT_WORDS.get(norm(ln.get("unit_spoken", "")))
        lines.append({
            "heard": f'{ln.get("quantity_spoken", "")} {ln.get("unit_spoken", "")} {ln.get("item_text", "")}'.strip(),
            "item_text": ln.get("item_text", ""),
            "qty_values": list(dict.fromkeys(vals)),
            "unit": unit,
        })
    return {"party": party_res, "delivery": parse_date(data.get("delivery_text", "") or ""), "lines": lines}
