# Bloomberg Terminal — Public Edition

A self-hosted, Bloomberg-style financial terminal that aggregates real-time and
historical market data across equities, options, crypto, futures, FX, and
macroeconomics into a dense, multi-panel dashboard.

**Positioning:** a terminal for the 99%. Same dense workflow, open data
sources, $0 seat cost. See [GAPS_AND_ROADMAP.md](./GAPS_AND_ROADMAP.md) for a
feature-by-feature comparison against the commercial Bloomberg Terminal and
the roadmap to parity (and beyond, on the things that actually matter to
retail and prosumer users).

## Stack

- **Backend:** Python 3.11, FastAPI, asyncpg (PostgreSQL), redis-py (Redis),
  pydantic-settings
- **Frontend:** React 18, Vite, Tailwind CSS, Recharts
- **Data sources (Phase 1):** yfinance, alpaca-trade-api, fredapi, SEC EDGAR
- **Infra:** Docker + Docker Compose (Postgres 15, Redis 7, backend, frontend)

## Layout

```text
bloomberg-terminal/
├── backend/                FastAPI app, data adapters, routes
│   ├── api/routes/         /quotes /macro /crypto /news /filings
│   ├── data/sources/       yfinance / alpaca / fred / sec-edgar clients
│   ├── models/             pydantic schemas
│   ├── core/               config + postgres/redis clients
│   ├── main.py             app factory + lifespan
│   └── requirements.txt
├── frontend/               Vite + React 18 + Tailwind
│   └── src/
│       ├── components/     Watchlist, Chart, NewsFeed, Macro, Portfolio, …
│       ├── pages/          Terminal.jsx (full multi-panel layout)
│       ├── hooks/          usePolling
│       ├── lib/api.js      fetch client
│       └── main.jsx
├── docker-compose.yml
├── .env.example
└── .gitignore
```

## Quickstart

### 1. Clone and configure

```bash
git clone https://github.com/wpf002/bloomberg.git
cd bloomberg/bloomberg-terminal
cp .env.example .env
# add ALPACA_API_KEY / ALPACA_API_SECRET / FRED_API_KEY as available
```

### 2. Docker Compose (recommended)

```bash
make up        # runs scripts/check_docker.sh, then `docker compose up --build`
# or, without the preflight:
docker compose up --build
```

- Backend:   <http://localhost:8000> (OpenAPI docs at `/docs`)
- Frontend:  <http://localhost:5173>
- Postgres:  `localhost:5432`  (user/db/password: `bloomberg`)
- Redis:     `localhost:6379`

### 3. Running locally (without Docker)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## API Surface (Phase 1)

| Method | Path                              | Purpose                                    |
| ------ | --------------------------------- | ------------------------------------------ |
| GET    | `/healthz`                        | Liveness + postgres/redis status           |
| GET    | `/api/quotes?symbols=AAPL,MSFT`   | Batch equity quotes (yfinance)             |
| GET    | `/api/quotes/{symbol}`            | Single quote                               |
| GET    | `/api/quotes/{symbol}/history`    | OHLCV history (`period`, `interval` query) |
| GET    | `/api/crypto?symbols=BTC-USD,…`   | Crypto quotes                              |
| GET    | `/api/fx?pairs=EURUSD,USDJPY`     | FX pair quotes (yfinance)                  |
| GET    | `/api/options/{symbol}`           | Option chain (calls/puts, IV, OI, volume)  |
| GET    | `/api/overview`                   | Markets overview (indices, VIX, DXY, …)    |
| GET    | `/api/fundamentals/{symbol}`      | Valuation, margins, returns, 52-wk range   |
| GET    | `/api/calendar/earnings?symbols=` | Upcoming earnings with EPS surprise        |
| GET    | `/api/macro/series`               | Supported FRED series IDs                  |
| GET    | `/api/macro/series/{id}`          | FRED series with observations              |
| GET    | `/api/news?symbols=…`             | Alpaca + public RSS news, merged           |
| GET    | `/api/filings/{symbol}`           | Recent SEC EDGAR filings                   |
| GET    | `/api/portfolio/account`          | Alpaca paper account (cash/equity/BP)      |
| GET    | `/api/portfolio/positions`        | Alpaca paper positions with unrealized P/L |
| GET    | `/api/sizing/{symbol}?stop_pct=5` | Position-size grid at 0.5/1/2/5% risk      |
| GET    | `/api/explain/{symbol}`           | LLM briefing (fundamentals + news + 10-Qs) |
| GET    | `/api/compare?symbols=AAPL,MSFT`  | LLM side-by-side of two symbols            |
| GET    | `/api/orders?status=all`          | Paper order list (Alpaca)                  |
| POST   | `/api/orders`                     | Submit a paper order (market/limit/stop)   |
| DELETE | `/api/orders/{id}`                | Cancel a working paper order               |
| GET    | `/api/alerts/rules`               | List active alert rules                    |
| POST   | `/api/alerts/rules`               | Create an alert rule (symbol + conditions) |
| DELETE | `/api/alerts/rules/{id}`          | Remove an alert rule                       |
| GET    | `/api/alerts/events`              | Recent fired alerts (Redis stream)         |
| POST   | `/api/options/payoff`             | Multi-leg expiry payoff curve              |
| WS     | `/api/ws/quotes?symbols=AAPL,…`   | Live trades + quotes (Alpaca IEX)          |
| WS     | `/api/ws/news`                    | Live news firehose                         |
| WS     | `/api/ws/alerts`                  | Live alert fires                           |

Option contracts returned by `/api/options/{symbol}` now include analytical
Black-Scholes Greeks (`delta`, `gamma`, `vega`, `theta`, `rho`) derived from
the provider's implied volatility and the configured `RISK_FREE_RATE`. News
is merged from Alpaca **and** public RSS (Yahoo Finance, Nasdaq, MarketWatch,
SEC press releases) so the feed degrades gracefully without an Alpaca key.

## Command Mnemonics

The command bar accepts Bloomberg-style mnemonics: `<SYMBOL> <FN>`.

| Mnemonic | Action |
| -------- | ------ |
| `GO` | Focus symbol (same as Enter with symbol alone) |
| `DES` | Company description / key stats |
| `GP` / `GIP` / `HP` | Price chart |
| `N` / `TOP` | News |
| `OMON` / `OV` | Options chain |
| `OVME` / `PAYOFF` | Options payoff diagram (multi-leg) |
| `FIL` / `CF` | SEC filings |
| `PORT` | Portfolio |
| `TRADE` / `EMSX` / `BUY` / `SELL` | Paper order ticket |
| `ALRT` / `ALERT` | Rule-based alerts |
| `SIZE` / `SIZING` | Position-size calculator |
| `WEI` / `MMAP` | Markets overview |
| `ECO` | Macro / FRED |
| `FXIP` | FX |
| `XBTC` | Crypto |
| `HELP` | Mnemonic reference modal |

Try `AAPL DES`, `SPY GP`, `NVDA OMON`, `EURUSD FXIP`, or just `HELP`.

## Terminal UI

The front-end renders a dense multi-panel dashboard (dark theme, JetBrains
Mono, amber accents). Panels:

- **Watchlist** — click to set the active symbol; rows tick live via the `/api/ws/quotes` WebSocket
- **Chart** — Recharts area chart, period picker (1D → 5Y)
- **News Feed** — per-symbol headlines from Alpaca
- **Macro** — FRED series switcher (DGS10, FEDFUNDS, CPI, VIX, …)
- **Portfolio** — live Alpaca paper account + positions (unrealized P/L)
- **Crypto** — top pairs with 24h change
- **EMS / Order Ticket** — submit paper orders (market / limit / stop / stop-limit) and cancel working orders
- **Alerts** — rule builder (`price > 200`, `change_percent < -3`, …) with a live fire feed over `/api/ws/alerts`
- **Payoff** — multi-leg options strategy diagrams (long call, covered call, bull spread, iron condor, straddle, custom)

A command bar at the top accepts a ticker and sets it as the active symbol
(Bloomberg-style `<GO>` pattern).

## Environment Variables

See `.env.example`. Notable keys:

- `ALPACA_API_KEY` / `ALPACA_API_SECRET` — required for `/api/news`,
  `/api/portfolio/*`, `/api/sizing/*`, and to back `/api/quotes` with
  real-time IEX. Get a free paper account at
  [alpaca.markets/signup](https://alpaca.markets/signup); the default
  `ALPACA_BASE_URL` already points at `https://paper-api.alpaca.markets`.
- `ANTHROPIC_API_KEY` — required for `/api/explain/*` and `/api/compare`.
  Generate at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys).
  `ANTHROPIC_MODEL` defaults to `claude-sonnet-4-6`.
- `FRED_API_KEY`   — required for real FRED observations on `/api/macro/*`
- `SEC_USER_AGENT` — SEC requires a descriptive UA for EDGAR requests

The app degrades gracefully: routes return empty lists when a key is missing,
rather than crashing.

## Troubleshooting

### `Cannot connect to the Docker daemon` (macOS)

Docker Desktop is actually two processes: the Electron UI, and a separate
Linux VM that runs `dockerd`. The UI can be open while the VM is paused or
stopped, which produces an opaque error like:

```text
Cannot connect to the Docker daemon at unix:///Users/you/.docker/run/docker.sock.
```

How to tell which state you're in, and what to do:

1. Run `docker version`. A healthy install shows both a **Client** block
   *and* a **Server** block. Client-only means the VM isn't running.
2. Click the whale icon in the macOS menu bar → **Resume** (or **Start**).
   Don't restart the app unless you have to — it kills any running
   containers.
3. Re-run `docker version`. Once the Server block appears, you're good.
4. Last resort (kills other containers): `osascript -e 'quit app "Docker"' && open -a Docker`.

`make up` runs `scripts/check_docker.sh` first and prints a human-readable
diagnosis instead of the cryptic socket error. Use `make up` by default.

## Phases shipped

- **Phase 1** — scaffold + Phase-1 data sources
- **Phase 1.1** — Markets overview, FX, options chain, mnemonic dispatcher
- **Phase 2** — Greeks, options panel, multi-source RSS, filings panel
- **Phase 3** — fundamentals, earnings, draggable Launchpad
- **Phase 3.1** — live Alpaca portfolio, Docker preflight
- **Phase 4** — command-bar polish, sizing, LLM EXPLAIN/COMPARE
- **Phase 5** — WebSocket streaming, paper order entry, rule-based alerts, options payoff

## Next

- Auth + per-user watchlists / Launchpad layouts in Postgres
- DuckDB-backed `/api/sql` endpoint (BQL-style scripting)
- Full-text filings search
