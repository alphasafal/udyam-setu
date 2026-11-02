"""GenAI layer for Saathi.

The language model does two jobs and nothing else:
  1. UNDERSTAND — turn whatever the owner typed (any Indian language, Hinglish,
     typos) into the fixed answer schema the rule engine needs.
  2. EXPLAIN   — write the recommendation back in the owner's language.

It never chooses a product, a price or an eligibility outcome; those come from
app/catalogue.py. Every model output is validated:
  * UNDERSTAND: each key must be in the schema and each value in its allowed set;
    anything else is dropped (and logged), then the offline parser fills gaps.
  * EXPLAIN: every price, quantity and day-count in the rule-engine output must
    appear verbatim in the text, or the reviewed template is shown instead.
Text is PII-redacted before it leaves the service (phone, e-mail, GSTIN, PAN,
Aadhaar, Udyam numbers).

The client is an interface: Anthropic by default (ADVISOR_MODEL env), but any
provider (including a model Airtel hosts in India) can be dropped in.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Dict, List, Optional, Protocol

DEFAULT_MODEL = os.environ.get("ADVISOR_MODEL", "claude-haiku-5-5")

REDACT = [
    (re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", re.I), "[GSTIN]"),
    (re.compile(r"\bUDYAM-?[A-Z]{2}-?\d{2}-?\d{7}\b", re.I), "[UDYAM]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.I), "[PAN]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[AADHAAR]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{9}\b"), "[PHONE]"),
]


def redact(text: str) -> str:
    for rx, tag in REDACT:
        text = rx.sub(tag, text)
    return text


class LLMClient(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 400) -> str: ...


class AnthropicClient:
    def __init__(self, model: str = DEFAULT_MODEL):
        import anthropic  # type: ignore
        self._c = anthropic.Anthropic()
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 400) -> str:
        msg = self._c.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                      messages=[{"role": "user", "content": user}])
        return "".join(getattr(b, "text", "") for b in msg.content).strip()


_client: Optional[LLMClient] = None


def get_client() -> Optional[LLMClient]:
    """Return the configured client, or None (offline mode)."""
    global _client
    if _client is not None:
        return _client
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            _client = AnthropicClient()
        except Exception:
            _client = None
    return _client


def set_client(c: Optional[LLMClient]) -> None:
    """Inject a client (tests, or a different provider)."""
    global _client
    _client = c


def _json_from(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    i, j = text.find("{"), text.rfind("}")
    return json.loads(text[i:j + 1]) if i >= 0 and j > i else json.loads(text)


def understand(text: str, schema: Dict[str, List[str]], lang: str = "en") -> Dict[str, object]:
    """LLM extraction into the schema. Returns {} if no client or on any failure.
    Output keys: the question ids, plus 'needs' (list) and 'city' (free text)."""
    c = get_client()
    if not c:
        return {}
    system = (
        "You help a telecom advisor understand a small Indian business owner. The owner may write in any Indian "
        "language, Hinglish or English. Extract ONLY what they actually said into JSON with these keys, using "
        "ONLY these allowed values (omit a key if they did not say it; never guess):\n"
        + json.dumps(schema, ensure_ascii=False)
        + '\n"needs" is a list of allowed values. Also return "city" as the city name in English if one is named. '
        "For employees, the value encodes people|locations; pick the closest band. "
        "Reply with one JSON object and nothing else."
    )
    try:
        raw = _json_from(c.complete(system, redact(text), max_tokens=300))
    except Exception:
        return {}
    return validate(raw, schema)


def validate(raw: object, schema: Dict[str, List[str]]) -> Dict[str, object]:
    """Keep only keys in the schema and values in their allowed sets."""
    out: Dict[str, object] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if k == "city" and isinstance(v, str) and 0 < len(v) < 40:
            out["city"] = v.strip()
        elif k == "needs" and isinstance(v, list):
            ok = [x for x in v if isinstance(x, str) and x in schema.get("needs", [])]
            if ok:
                out["needs"] = sorted(set(ok), key=ok.index)
        elif k in schema and str(v) in schema[k]:
            out[k] = str(v)
    return out


def numbers_in(text: str) -> List[str]:
    return re.findall(r"₹\s?[\d,]+|\b\d+\b", text)


def explain(facts: Dict[str, object], template: str, lang_name: str) -> Dict[str, str]:
    """Ask the model to explain the rule-engine output in the owner's language.
    Returns {"text", "source"}; source is "genai" or "template" (fallback)."""
    c = get_client()
    must = numbers_in(template)
    if not c:
        return {"text": template, "source": "template"}
    system = (
        f"You are Saathi, a friendly advisor for small businesses in India. Write 2-3 short sentences in {lang_name} "
        "for a shop or clinic owner, explaining the bundle below and why it fits what they said. Use plain words, "
        "no jargon, no product codes. Use ONLY the facts given; do not add products, discounts, promises or numbers. "
        "Copy every price and number exactly as written (keep the ₹ sign and commas)."
    )
    try:
        out = c.complete(system, json.dumps(facts, ensure_ascii=False) + "\n\nReference wording:\n" + template, max_tokens=300)
    except Exception:
        return {"text": template, "source": "template"}
    norm = lambda s: s.replace(" ", "")
    if out and all(norm(n) in norm(out) for n in must):
        return {"text": out, "source": "genai"}
    return {"text": template, "source": "template"}
