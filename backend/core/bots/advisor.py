"""Hybrid decision layer — Claude as a risk-aware second opinion.

For `hybrid` bots, rule-proposed intents are passed to Claude along with
compact live context. Claude returns a per-intent verdict: keep (optionally
shrunk) or veto, with a one-line rationale. **Claude can only shrink or veto
— never invent new intents or exceed the rule's size.** Guardrails still run
*after* the advisor, so the advisor can only make the bot *more* conservative.

Degrades gracefully to rules-only (returns the intents unchanged) whenever
the LLM is not configured or errors.
"""

from __future__ import annotations

import json
import logging

from ..llm import LLMNotConfigured, synthesize
from .schemas import Bot, Intent

logger = logging.getLogger(__name__)


async def refine(bot: Bot, intents: list[Intent], context: dict) -> tuple[list[Intent], str]:
    """Return (approved_intents, rationale). On any failure, returns the
    original intents and an empty rationale (fail-open to rules-only — the
    rules already passed, and guardrails still run downstream)."""
    if not intents:
        return [], ""
    try:
        raw = await synthesize(
            "bot_decision",
            {
                "bot_name": bot.name,
                "strategy": bot.config.strategy.value,
                "context_json": json.dumps(context, default=str),
                "intents_json": json.dumps([i.model_dump() for i in intents], default=str),
            },
            max_tokens=600,
            temperature=0.0,
        )
    except LLMNotConfigured:
        return intents, ""
    except Exception as exc:
        logger.debug("bot advisor llm failed, passing intents through: %s", exc)
        return intents, ""

    verdicts = _parse(raw)
    if verdicts is None:
        return intents, ""

    approved: list[Intent] = []
    notes: list[str] = []
    for idx, intent in enumerate(intents):
        v = verdicts.get(idx) or verdicts.get(str(idx))
        if not v:
            approved.append(intent)  # no verdict → keep as-is
            continue
        if not v.get("keep", True):
            notes.append(f"veto {intent.symbol}: {v.get('reason', '')}".strip())
            continue
        # Apply a size shrink only — never grow. Scale 0<f<=1.
        scale = v.get("scale")
        out = intent
        if isinstance(scale, (int, float)) and 0 < scale < 1:
            if intent.qty is not None:
                out = intent.model_copy(update={"qty": round(intent.qty * scale, 4)})
            elif intent.notional is not None:
                out = intent.model_copy(update={"notional": round(intent.notional * scale, 2)})
            notes.append(f"shrink {intent.symbol} ×{scale:.2f}: {v.get('reason','')}".strip())
        approved.append(out)
    return approved, " · ".join(n for n in notes if n)


def _parse(raw: str) -> dict | None:
    """Pull the JSON object out of the model's reply. Expected shape:
    {"verdicts": {"0": {"keep": true, "scale": 0.5, "reason": "..."}}}"""
    if not raw:
        return None
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return None
    verdicts = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(verdicts, dict):
        return None
    # normalize keys to ints where possible
    out: dict = {}
    for k, v in verdicts.items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out
