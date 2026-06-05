"""Pydantic models + enums for the trading-bot engine."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class StrategyKind(str, Enum):
    threshold_dca = "threshold_dca"      # buy $X every -N% from a reference
    ma_crossover = "ma_crossover"        # fast/slow SMA cross → enter/exit
    rsi_reversion = "rsi_reversion"      # RSI < lo buy, > hi sell
    rebalance = "rebalance"              # drift positions toward target weights
    take_profit_stop = "take_profit_stop"  # exit rules on an open position


class BotStatus(str, Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    stopped = "stopped"
    killed = "killed"


class DecisionMode(str, Enum):
    rule = "rule"        # deterministic only
    hybrid = "hybrid"    # rules proposed, Claude may veto/shrink


class Intent(BaseModel):
    """A proposed order from a strategy. Either `qty` (shares) or `notional`
    (dollar amount) is set; the executor resolves notional→qty at the live
    price. `reason` explains why the strategy proposed it (shown in the feed).
    """
    symbol: str
    side: str  # buy | sell
    qty: Optional[float] = None
    notional: Optional[float] = None
    type: str = "market"
    limit_price: Optional[float] = None
    reason: str = ""

    def normalized(self) -> "Intent":
        return self.model_copy(update={"symbol": self.symbol.upper(), "side": self.side.lower()})


class Guardrails(BaseModel):
    """Hard limits enforced on every intent before execution."""
    max_position_usd: float = Field(default=1000.0, gt=0)
    max_position_pct: Optional[float] = None       # % of account equity, optional
    max_orders_per_day: int = Field(default=10, ge=1)
    daily_loss_limit_usd: Optional[float] = None    # kill-switch; None = disabled
    symbol_allowlist: list[str] = Field(default_factory=list)  # empty = config symbols
    allow_extended_hours: bool = False
    per_symbol_cooldown_seconds: int = Field(default=300, ge=0)


class BotConfig(BaseModel):
    strategy: StrategyKind
    symbols: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class Bot(BaseModel):
    id: str = Field(default_factory=_new_id)
    user_id: Optional[int] = None
    name: str
    status: BotStatus = BotStatus.draft
    mode: str = "paper"  # hard-pinned to paper in this build
    decision_mode: DecisionMode = DecisionMode.rule
    require_approval: bool = True
    config: BotConfig
    guardrails: Guardrails = Field(default_factory=Guardrails)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BotEvent(BaseModel):
    bot_id: str
    user_id: Optional[int] = None
    ts: datetime = Field(default_factory=datetime.utcnow)
    kind: str  # eval | signal | llm | reject | order | fill | error | lifecycle
    detail: dict[str, Any] = Field(default_factory=dict)


class BotOrder(BaseModel):
    id: str = Field(default_factory=_new_id)
    bot_id: str
    user_id: Optional[int] = None
    alpaca_order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    symbol: str
    side: str
    qty: float = 0.0
    intent: dict[str, Any] = Field(default_factory=dict)
    status: str = "submitted"
    submitted_at: datetime = Field(default_factory=datetime.utcnow)


class PendingAction(BaseModel):
    id: str = Field(default_factory=_new_id)
    bot_id: str
    user_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    intent: Intent
    status: str = "pending"  # pending | approved | rejected | expired
    resolved_at: Optional[datetime] = None


# ── requests + backtest results ──────────────────────────────────────────


class BotCreateRequest(BaseModel):
    name: str
    decision_mode: DecisionMode = DecisionMode.rule
    require_approval: bool = True
    config: BotConfig
    guardrails: Guardrails = Field(default_factory=Guardrails)


class BotUpdateRequest(BaseModel):
    name: Optional[str] = None
    decision_mode: Optional[DecisionMode] = None
    require_approval: Optional[bool] = None
    config: Optional[BotConfig] = None
    guardrails: Optional[Guardrails] = None


class BacktestTrade(BaseModel):
    ts: Optional[datetime] = None
    side: str
    symbol: str
    qty: float
    price: float
    reason: str = ""


class BacktestResult(BaseModel):
    symbol: str
    strategy: StrategyKind
    start_equity: float
    end_equity: float
    pnl: float
    pnl_pct: float
    max_drawdown_pct: float
    num_trades: int
    bars: int
    trades: list[BacktestTrade] = Field(default_factory=list)
