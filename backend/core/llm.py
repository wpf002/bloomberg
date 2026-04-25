"""Thin wrapper around the Anthropic Claude API.

Loads prompt templates from backend/prompts/*.yaml so they're swappable
without code changes. All synthesis routes funnel through this module
so we have one place to tune model, retry policy, and observability.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from anthropic import AsyncAnthropic

from .config import settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Render a template by substituting only the named keys present in `vars`.
# Unlike str.format, literal `{` and `}` (e.g. JSON examples in a system
# prompt) pass through untouched. This matters because we want to embed
# JSON output schemas in system prompts without escape-doubling every
# brace, which is fragile and easy to forget.
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _safe_format(template: str, variables: dict[str, Any]) -> str:
    def replace(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in variables:
            raise KeyError(key)
        return str(variables[key])

    return _PLACEHOLDER.sub(replace, template)


class LLMNotConfigured(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is missing. Routes should translate
    this into a 503 with a clear remediation message."""


@lru_cache(maxsize=8)
def _load_prompt(name: str) -> dict[str, str]:
    path = PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if "system" not in data or "user" not in data:
        raise ValueError(f"Prompt {name} must define both `system` and `user` keys")
    return data


def _client() -> AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY not set. Add it to .env (get a key at "
            "console.anthropic.com) and restart the backend."
        )
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


async def synthesize(
    prompt_name: str,
    variables: dict[str, Any],
    *,
    max_tokens: int = 1500,
    temperature: float = 0.3,
) -> str:
    """Render a named prompt with `variables`, call Claude, return the text.

    `variables` are substituted into both the system and user templates
    using Python str.format — every {placeholder} must be supplied.
    """
    prompt = _load_prompt(prompt_name)
    try:
        system = _safe_format(prompt["system"], variables)
        user = _safe_format(prompt["user"], variables)
    except KeyError as exc:
        raise ValueError(
            f"Prompt {prompt_name} references missing variable: {exc}"
        ) from exc

    client = _client()
    msg = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # `content` is a list of content blocks; we only request text.
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()
