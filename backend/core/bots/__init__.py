"""Automated trading-bot engine (paper-first, Alpaca).

A bot = strategy params + trigger (the streaming quotes loop) + decision
(deterministic rules, optionally refined by Claude) + guardrails (the hard
safety gate) + executor (Alpaca paper) + audit. Guardrails run on *every*
proposed intent; the LLM advisor may only veto/shrink rule intents, never
invent new ones or exceed limits.

Public surface:
  - `manager`      — the process-wide BotManager singleton (started in main.py)
  - `store`        — the BotStore (Postgres-backed, in-memory fallback)
  - schemas        — Bot, BotConfig, Guardrails, Intent, BotEvent, ...
"""

from .manager import manager
from .store import store

__all__ = ["manager", "store"]
