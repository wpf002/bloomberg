"""Guardrails — the hard safety gate. Every rejection path is exercised."""

from backend.core.bots.guardrails import GuardrailContext, check
from backend.core.bots.schemas import Guardrails, Intent


def _ctx(**kw):
    base = dict(price=100.0, equity=10_000.0, buying_power=10_000.0,
                position_qty=0.0, position_market_value=0.0, orders_today=0,
                today_pnl=0.0, market_open=True, last_fired_age=None)
    base.update(kw)
    return GuardrailContext(**base)


def test_buy_within_limits_passes_and_resolves_qty():
    gr = Guardrails(max_position_usd=1000)
    d = check(Intent(symbol="AAPL", side="buy", notional=500), gr, _ctx())
    assert d.allow
    assert d.intent.qty == 5.0  # 500 / 100
    assert d.intent.notional is None


def test_symbol_allowlist_rejects():
    gr = Guardrails(symbol_allowlist=["MSFT"])
    d = check(Intent(symbol="AAPL", side="buy", notional=100), gr, _ctx())
    assert not d.allow and "allowlist" in d.reason


def test_allowlist_falls_back_to_config_symbols():
    gr = Guardrails()  # empty allowlist
    d = check(Intent(symbol="AAPL", side="buy", notional=100), gr, _ctx(), config_symbols=["MSFT"])
    assert not d.allow and "allowlist" in d.reason


def test_position_cap_rejects():
    gr = Guardrails(max_position_usd=1000)
    d = check(Intent(symbol="AAPL", side="buy", notional=600), gr,
              _ctx(position_market_value=500))
    assert not d.allow and "position cap" in d.reason


def test_position_pct_cap_rejects():
    gr = Guardrails(max_position_usd=1_000_000, max_position_pct=10)
    d = check(Intent(symbol="AAPL", side="buy", notional=2000), gr, _ctx(equity=10_000))
    assert not d.allow and "% > " in d.reason


def test_buying_power_rejects():
    gr = Guardrails(max_position_usd=1_000_000)
    d = check(Intent(symbol="AAPL", side="buy", notional=5000), gr, _ctx(buying_power=1000))
    assert not d.allow and "buying power" in d.reason


def test_orders_per_day_rejects():
    gr = Guardrails(max_orders_per_day=3, max_position_usd=1_000_000)
    d = check(Intent(symbol="AAPL", side="buy", notional=100), gr, _ctx(orders_today=3))
    assert not d.allow and "max orders/day" in d.reason


def test_cooldown_rejects():
    gr = Guardrails(per_symbol_cooldown_seconds=300, max_position_usd=1_000_000)
    d = check(Intent(symbol="AAPL", side="buy", notional=100), gr, _ctx(last_fired_age=120))
    assert not d.allow and "cooldown" in d.reason


def test_daily_loss_kill_switch():
    gr = Guardrails(daily_loss_limit_usd=200, max_position_usd=1_000_000)
    d = check(Intent(symbol="AAPL", side="buy", notional=100), gr, _ctx(today_pnl=-250))
    assert not d.allow and d.kill is True


def test_market_closed_blocks_unless_extended():
    gr = Guardrails(max_position_usd=1_000_000)
    d = check(Intent(symbol="AAPL", side="buy", notional=100), gr, _ctx(market_open=False))
    assert not d.allow and "market closed" in d.reason
    gr2 = Guardrails(max_position_usd=1_000_000, allow_extended_hours=True)
    d2 = check(Intent(symbol="AAPL", side="buy", notional=100), gr2, _ctx(market_open=False))
    assert d2.allow


def test_sell_bypasses_caps_but_needs_position():
    gr = Guardrails(max_position_usd=10)  # tiny cap shouldn't block a sell
    held = check(Intent(symbol="AAPL", side="sell", qty=3), gr, _ctx(position_qty=5))
    assert held.allow and held.intent.qty == 3
    none = check(Intent(symbol="AAPL", side="sell", qty=3), gr, _ctx(position_qty=0))
    assert not none.allow and "no position" in none.reason


def test_sell_qty_clamped_to_holdings():
    gr = Guardrails()
    d = check(Intent(symbol="AAPL", side="sell", qty=100), gr, _ctx(position_qty=4))
    assert d.allow and d.intent.qty == 4
