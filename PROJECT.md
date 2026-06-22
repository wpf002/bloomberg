# AURORA — Bloomberg-style Financial Terminal

A self-hosted, Bloomberg-style market terminal — *"a terminal for the 99%."* It
aggregates real-time and historical data across **equities, options, futures,
crypto, FX, fixed income, and macroeconomics** into a dense, draggable
multi-panel dashboard; layers **proprietary analytics** (regime, fragility,
capital flow, gamma/vanna exposure), a **streaming LLM analyst**, and a full
**autonomous trading-bot engine** on top; and runs on open / low-cost data feeds
at ~$0 seat cost. Internally branded **AURORA**. Single-operator deployment on
Railway.

**Scale:** ~35 routers · 130 HTTP + WebSocket endpoints · 17 data-source
adapters · ~37 frontend panels · 26 backend + 13 frontend test files.

---

## Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11 · FastAPI · asyncpg (PostgreSQL) · redis-py · Pydantic v2 · httpx · NumPy / SciPy / pandas · DuckDB · Anthropic SDK (Claude) · cryptography (Fernet) · websockets |
| **Frontend** | React 18 · Vite 5 · Tailwind CSS · Recharts · react-grid-layout · hand-rolled i18n (en / es / pt / zh) |
| **Local infra** | Docker Compose — Postgres 15 + Redis 7 + backend + frontend |
| **Prod infra** | Railway — `aurora-terminal` (frontend) + `backend-production-4975` (backend); GitHub auto-deploy on push to `main`; TLS-terminating proxy |
| **Persistence** | PostgreSQL (bots, events, orders, layouts, snapshots, creds) and Redis (cache, leader-lock, cooldowns, heartbeats) — both with in-memory fallback |

---

## Repository layout

```text
backend/
  api/routes/      ~35 routers (the HTTP/WS surface)
  data/sources/    17 async data adapters
  core/            config, db/cache clients, auth, encryption, streaming,
                   bots/, brokers/, bsm, payoff, factor_analysis, sql_engine,
                   schema (Postgres DDL), alerts, audit
  services/        intelligence_engine, risk_engine, advisor (LLM)
  models/          Pydantic schemas
  main.py          app factory + lifespan (starts bot manager, leader loop)
frontend/
  src/components/  panels (Watchlist, Chart, Options, Bots, Intelligence…)
  src/pages/       Terminal.jsx (the full multi-panel workspace)
  src/hooks/       usePolling, useStream, useAuth, useTheme
  src/lib/         api.js (fetch client), mnemonics.js (command bar)
  src/i18n/        en (authoritative) + es/pt/zh
tests/             pytest suite (26 files)
scripts/           smoke test, docker preflight
docker-compose.yml · railway.toml · Makefile
Docs: README · GAPS_AND_ROADMAP · GO_LIVE · RAILWAY_DEPLOY
```

---

## Data layer (17 adapters)

All adapters are async, cached (Redis + in-memory fallback), and degrade
gracefully when a key isn't entitled.

| Domain | Sources |
|---|---|
| Equities / brokerage | **Alpaca** (quotes, bars, streaming, paper+live trading), **Finnhub**, **FMP** (fundamentals + commodity spot) |
| Options / volatility | **Massive** (Polygon-compatible: options flow, aggregates), **CBOE** (IV buffer) |
| Macro / rates | **FRED**, **US Treasury** (yield curve) |
| Futures / commodities | **futures_source** — 3-tier cascade: Massive → FMP → FRED |
| FX | **Frankfurter** |
| Filings / regulatory | **SEC EDGAR** (13F, 10-K…), **FINRA** (short interest) |
| Factor research | **Ken French** data library (Fama-French) |
| Prediction markets | **Kalshi**, **Polymarket** |
| News / search | **RSS**, **Meilisearch** |
| External micro-service | **Prophet** (`wpf002/prophet`) — read-only forecasting API used by macro/predictions overlays |

---

## API surface (130 endpoints)

**Market data** — `/quotes` `/macro` `/crypto` `/fx` `/futures` `/fixed_income`
`/options` `/overview` `/market`

**Research** — `/fundamentals` `/calendar` `/news` `/filings` `/compare`
`/explain` `/symbols`

**Portfolio & trading** — `/portfolio` (Alpaca paper state + manual-position
overlay + factor exposures) `/sizing` `/orders` `/alerts` `/bots` `/risk`

**Proprietary analytics** — `/intelligence` (regime/fragility/flows/rotation)
`/advisor` (streaming Claude) `/flow` (large options orders + heatmap)
`/gex` (gamma exposure) `/vex` (vanna exposure) `/predictions` (Kalshi +
Polymarket consensus)

**Platform** — `/auth` (GitHub OAuth → JWT cookies) `/me` (per-user encrypted
broker keys) `/shared` (shareable layouts) `/sql` (read-only DuckDB "BQL")
`/provenance` `/audit` `/ws/*` (WebSocket streams: quotes, news, bots)

---

## The four engines

### 1. Intelligence (`services/intelligence_engine.py`)
- **Regime detection** — classifies the macro environment from a fixed FRED
  basket + VIX + yield curve + DXY + CPI + M2, with confidence + drivers.
- **Fragility scoring** — 0–100 per holding: volatility percentile, drawdown
  depth, VIX correlation, beta, sector regime sensitivity.
- **Capital-flow inference** — 13F-filer holdings deltas → sectors seeing
  institutional inflow vs outflow.
- **Sector rotation** — 11 GICS-ETF 30-day relative strength → cycle phase
  (Early / Mid / Late / Recession).

### 2. Risk (`services/risk_engine.py`)
VaR / CVaR, beta-to-SPY, 90-day correlation matrix, drawdown, stress tests,
sector exposure. Also hosts the shared GEX / VEX math.

### 3. Advisor (`services/advisor.py`)
Streaming Claude analyst with two desk personas (investor & day-trader),
grounded in live context: options flow (skew, net premium, top trades), GEX
levels, ATM IV, regime, and portfolio fragility. Persona prompts ban "AI-speak"
so output reads like a real analyst; mid-stream errors degrade cleanly.

### 4. Trading bots (`core/bots/`)
The deepest subsystem — see below.

---

## Trading-bot subsystem

**Strategies:** threshold-DCA · MA-crossover · RSI-reversion · Bollinger ·
breakout · take-profit/stop · rebalance.

**Broker abstraction (`core/brokers/`):** a Protocol + resolver picks the
execution broker per `(user, broker, mode)`. Alpaca adapter uses per-user
encrypted keys (paper + live, env-key fallback); a Robinhood MCP client
(JSON-RPC over HTTP, tool auto-mapping) is turnkey but inert behind a flag.

**Decision modes:** rules-only or hybrid (LLM refines/vetoes intents);
approve-first (pending → you approve) or autonomous, within guardrails.

**Guardrails:** max position $, daily-loss kill-switch, per-symbol cooldown,
market-hours gate.

**Reliability & durability:**
- Redis **leader-lock** → only one replica trades (no double-orders).
- Redis-backed cooldowns + idempotent client-order-ids survive restarts.
- **60s interval floor** re-evaluates *every* active bot via direct quote
  polling, so a dead/disconnected stream can never silently stop a bot.
- Self-reconnecting tick loop (fast path); resilient loops never die on error.
- Active bots reload from Postgres on boot → resume across restarts/deploys.

**Observability:**
- Per-bot **heartbeat** snapshot every eval (last-checked, price,
  distance-to-trigger, orders-today) → live "Heartbeat" strip in the panel.
- **Watchdog** flags any stale heartbeat during market hours straight into the
  bot's Activity feed (one warning per episode + recovery note).
- Token-gated `GET /bots/monitor` → sessionless health pull for an external
  watcher; a weekday-morning routine sends a daily health ping.
- Backtest engine replays a strategy over ~6mo of daily bars before arming.

**Safety posture:** paper-pinned by default; live trading gated behind
`BOTS_ALLOW_LIVE` + per-user live keys. Live is fully plumbed but off; Robinhood
is a registered, documented turnkey client awaiting endpoint/token.

---

## Supporting analytics / utilities

| Module | Purpose |
|---|---|
| `core/bsm.py` | Black-Scholes-Merton pricing + Greeks (stdlib-only); decorates option-chain rows with delta/gamma/vega/theta/rho |
| `core/payoff.py` | option-strategy payoff diagrams |
| `core/factor_analysis.py` | Fama-French factor regression (Ken French data) |
| `core/sql_engine.py` | DuckDB tables registered in-memory at startup (the "BQL" equivalent) |
| `core/alerts.py` + `core/audit.py` | rule engine + immutable action/snapshot logging |

---

## Platform & trust

- **Auth:** GitHub OAuth → HS256 JWT cookies; `X-Forwarded-Proto`-aware so
  redirects work behind Railway's TLS proxy.
- **Security:** per-user broker creds **Fernet-encrypted at rest**; secrets live
  only in Railway env or the encrypted Settings UI — never in code or chat.
- **Provenance & audit:** every datum traceable to its source feed; intelligence
  snapshots and bot actions persisted and queryable.
- **Frontend UX:** draggable/resizable react-grid workspace; command bar with
  Bloomberg mnemonics (DES, GP, OMON, PORT, FIL, ALRT…); per-user shareable
  layouts; locked display-only chart; code-split bundles.
- **i18n:** en authoritative; es/pt/zh fall back to en.

---

## Testing & quality

- **Backend:** pytest (+ pytest-asyncio), 26 files — strategies, guardrails,
  executor, coordination, broker resolver, encryption, bot pipeline e2e,
  heartbeat/watchdog, OAuth callback, futures source, advisor stream, Robinhood
  MCP, and more.
- **Frontend:** Vitest + React Testing Library + jsdom, 13 files / ~102 tests.
- **Ops:** `scripts/smoke.py` route/health check; Docker preflight.

---

## Current status

- Live on Railway; both services healthy.
- One paper trading bot active (SPY Bot · threshold-DCA · Alpaca paper);
  heartbeat + watchdog + daily health ping all confirmed working.
- Live trading and Robinhood are plumbed but intentionally **off** behind flags.
