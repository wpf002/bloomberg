# Going live with trading bots

This is the checklist for switching a bot from **paper** to **real money** on
Alpaca. Everything is gated so going live is a deliberate, reversible series of
steps — not a single switch. Read the whole thing once before you start.

> The bot engine defaults to paper. Live requires **three independent things**:
> the `BOTS_ALLOW_LIVE` master switch, your Alpaca **live** API keys, and a bot
> explicitly set to `mode: live`. Missing any one → it stays paper / refuses.

---

## 0. Prerequisites
- You've run the strategy on **paper** and are happy with how it behaves.
- You understand that live orders are **real, irreversible fills with real money**.
- You have access to your Alpaca account (live trading enabled, funded).

## 1. Get your Alpaca **live** API keys
Alpaca issues **separate** keys for paper vs. live — your existing Railway
`ALPACA_API_KEY` is a *paper* key and cannot trade live.
1. Log in at [app.alpaca.markets](https://app.alpaca.markets).
2. Switch the dashboard from **Paper** to **Live**.
3. Generate an API key + secret under the live environment. Copy both (the
   secret is shown once).

## 2. Add the live keys to Railway (backend service)
Add these two variables (the master switch `BOTS_ALLOW_LIVE=true` is already set):
```
ALPACA_LIVE_API_KEY=<your Alpaca LIVE key>
ALPACA_LIVE_API_SECRET=<your Alpaca LIVE secret>
```
Railway redeploys the backend automatically. (Alternatively, enter them in the
app: **SETTINGS → Alpaca · Live** — encrypted per-user. Either path works; env
vars are simplest for a single-user setup.)

## 3. Verify the engine sees live keys
Hit the status endpoint (no auth needed):
```
curl -s https://<your-backend>/api/bots/status
```
You want:
```json
{"paper": true, "alpaca_configured": true, "live_enabled": true, "live_keys_present": true, ...}
```
`live_enabled: true` **and** `live_keys_present: true` means you're ready.

## 4. Create a conservative live bot (recommended first run)
In the app: **BOTS → New bot**, then set **Mode → Live** (now selectable).
Start with tight limits and **approve-first** so nothing executes without you:

| Setting | Recommended first-run value | Why |
|---|---|---|
| Strategy | `threshold_dca` on a liquid ETF (e.g. **SPY**) | predictable, liquid, easy to reason about |
| Drop % / Buy $ | `2` / `$50` | tiny clips |
| **Approve each trade** | **ON** | every order waits for your tap |
| Max position $ | `$200` | hard cap on exposure |
| Daily loss $ (kill-switch) | `$25` | auto-pauses the bot on a bad day |
| Orders/day | `3` | limits churn |
| Cooldown (s) | `3600` | at most one signal/hour per symbol |

Equivalent API payload (POST `/api/bots`):
```json
{
  "name": "SPY live starter",
  "broker": "alpaca",
  "mode": "live",
  "decision_mode": "rule",
  "require_approval": true,
  "config": { "strategy": "threshold_dca", "symbols": ["SPY"],
              "params": { "drop_pct": 2, "notional": 50 } },
  "guardrails": { "max_position_usd": 200, "daily_loss_limit_usd": 25,
                  "max_orders_per_day": 3, "per_symbol_cooldown_seconds": 3600 }
}
```
**Dry-run it first** (the builder requires this) to see the backtest, then **Create → Start**.

## 5. Monitor
- The **Activity** feed shows every eval / signal / reject / order with reasons.
- **Pending approvals** appear inline — approve or reject each.
- **Per-bot orders** table shows what actually filled.
- A daily-loss breach **auto-pauses** the bot and emits a `lifecycle` event.

## 6. Stop / roll back (any of these)
- **Pause** or **Kill** the bot from the panel (Kill is confirm-gated).
- Flip the master switch off: set `BOTS_ALLOW_LIVE=false` in Railway → no bot
  can trade live (existing live bots refuse on the next tick).
- Remove `ALPACA_LIVE_API_KEY/SECRET` → live resolution fails closed.

---

## Safety model (how the guardrails protect you)
- **Paper-first by default**; live needs the flag + live keys + per-bot `mode: live`.
- **Approve-first** is the default for new bots — autonomous is an explicit opt-in.
- **Guardrails run on every intent**: symbol allowlist, position $/% caps,
  buying-power check, orders/day, per-symbol cooldown, market-hours, and the
  **daily-loss kill-switch** (auto-pause).
- **Idempotent order IDs** (bucketed per cooldown window) so a restart or
  double-eval can't double-submit.
- **Single-leader execution** so >1 backend replica never double-trades.
- **Full audit**: every decision lands in `bot_events` + the audit log.

## Known follow-ups before heavy live use
- **Per-account P&L sizing**: the daily-loss kill-switch currently uses
  account-level equity change (`equity - last_equity`), not per-bot P&L. With
  one live account that's the right number; if you run several live bots on one
  account, consider per-bot P&L attribution.
- **Robinhood**: the MCP client is implemented but inert until you set
  `ROBINHOOD_MCP_ENDPOINT/TOKEN`, discover tool names via
  `GET /api/bots/robinhood/tools`, map `ROBINHOOD_TOOL_*`, and set
  `ROBINHOOD_ENABLED=true`.
