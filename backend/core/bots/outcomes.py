"""Persists trade-context snapshots (bot_trade_outcomes) and learned parameter
sets (bot_learned_params) for the bot learning engine.

Follows the same Postgres-backed / in-memory-fallback pattern as BotStore.
"""

from __future__ import annotations

import json
import logging

from ..database import database
from .schemas import LearnedParams, TradeOutcome

logger = logging.getLogger(__name__)


class OutcomeStore:
    def __init__(self) -> None:
        self._outcomes: list[TradeOutcome] = []
        self._learned: dict[tuple[str, str], LearnedParams] = {}

    @property
    def _pg(self) -> bool:
        return database.pool is not None

    async def log_trade(self, outcome: TradeOutcome) -> None:
        if self._pg:
            try:
                async with database.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO bot_trade_outcomes
                            (id, bot_id, user_id, bot_order_id, symbol, side,
                             price, qty, regime, indicator_snap, fired_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11)
                        """,
                        outcome.id, outcome.bot_id, outcome.user_id,
                        outcome.bot_order_id, outcome.symbol, outcome.side,
                        outcome.price, outcome.qty, outcome.regime,
                        json.dumps(outcome.indicator_snap, default=str),
                        outcome.fired_at,
                    )
                return
            except Exception as exc:
                logger.debug("outcome log pg failed: %s", exc)
        self._outcomes.append(outcome)

    async def count_since_last_tune(self, bot_id: str) -> int:
        """New outcomes logged after the bot's most recent tune (or all if never tuned)."""
        if self._pg:
            try:
                async with database.acquire() as conn:
                    last_tune = await conn.fetchval(
                        "SELECT MAX(updated_at) FROM bot_learned_params WHERE bot_id=$1",
                        bot_id,
                    )
                    if last_tune is None:
                        return int(await conn.fetchval(
                            "SELECT COUNT(*) FROM bot_trade_outcomes WHERE bot_id=$1",
                            bot_id,
                        ) or 0)
                    return int(await conn.fetchval(
                        "SELECT COUNT(*) FROM bot_trade_outcomes WHERE bot_id=$1 AND fired_at>$2",
                        bot_id, last_tune,
                    ) or 0)
            except Exception as exc:
                logger.debug("outcome count pg failed: %s", exc)
        return sum(1 for o in self._outcomes if o.bot_id == bot_id)

    async def save_learned(self, learned: LearnedParams) -> None:
        if self._pg:
            try:
                async with database.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO bot_learned_params (bot_id, regime, params, score, trades, updated_at)
                        VALUES ($1,$2,$3::jsonb,$4,$5,NOW())
                        ON CONFLICT (bot_id, regime) DO UPDATE
                            SET params=$3::jsonb, score=$4, trades=$5, updated_at=NOW()
                        """,
                        learned.bot_id, learned.regime,
                        json.dumps(learned.params, default=str),
                        learned.score, learned.trades,
                    )
                return
            except Exception as exc:
                logger.debug("learned params save pg failed: %s", exc)
        self._learned[(learned.bot_id, learned.regime)] = learned

    async def get_learned(self, bot_id: str, regime: str = "any") -> LearnedParams | None:
        if self._pg:
            try:
                async with database.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM bot_learned_params WHERE bot_id=$1 AND regime=$2",
                        bot_id, regime,
                    )
                if row:
                    return LearnedParams(
                        bot_id=row["bot_id"], regime=row["regime"],
                        params=_jsonb(row["params"]),
                        score=float(row["score"]), trades=int(row["trades"]),
                        updated_at=row["updated_at"],
                    )
            except Exception as exc:
                logger.debug("learned params get pg failed: %s", exc)
        return self._learned.get((bot_id, regime))

    async def list_learned(self, bot_id: str) -> list[LearnedParams]:
        if self._pg:
            try:
                async with database.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT * FROM bot_learned_params WHERE bot_id=$1 ORDER BY updated_at DESC",
                        bot_id,
                    )
                return [
                    LearnedParams(
                        bot_id=r["bot_id"], regime=r["regime"],
                        params=_jsonb(r["params"]),
                        score=float(r["score"]), trades=int(r["trades"]),
                        updated_at=r["updated_at"],
                    )
                    for r in rows
                ]
            except Exception as exc:
                logger.debug("learned params list pg failed: %s", exc)
        return [v for v in self._learned.values() if v.bot_id == bot_id]


def _jsonb(value) -> dict:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return dict(value) if value else {}


outcome_store = OutcomeStore()
