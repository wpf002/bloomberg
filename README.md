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
| GET    | `/api/macro/series`               | Supported FRED series IDs                  |
| GET    | `/api/macro/series/{id}`          | FRED series with observations              |
| GET    | `/api/news?symbols=…`             | Alpaca news stream                         |
| GET    | `/api/filings/{symbol}`           | Recent SEC EDGAR filings                   |

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
| `FIL` / `CF` | SEC filings |
| `PORT` | Portfolio |
| `WEI` / `MMAP` | Markets overview |
| `ECO` | Macro / FRED |
| `FXIP` | FX |
| `XBTC` | Crypto |
| `HELP` | Mnemonic reference modal |

Try `AAPL DES`, `SPY GP`, `NVDA OMON`, `EURUSD FXIP`, or just `HELP`.

## Terminal UI

The front-end renders a dense multi-panel dashboard (dark theme, JetBrains
Mono, amber accents). Panels:

- **Watchlist** — click to set the active symbol
- **Chart** — Recharts area chart, period picker (1D → 5Y)
- **News Feed** — per-symbol headlines from Alpaca
- **Macro** — FRED series switcher (DGS10, FEDFUNDS, CPI, VIX, …)
- **Portfolio** — sample positions with live P/L
- **Crypto** — top pairs with 24h change

A command bar at the top accepts a ticker and sets it as the active symbol
(Bloomberg-style `<GO>` pattern).

## Environment Variables

See `.env.example`. Notable keys:

- `ALPACA_API_KEY` / `ALPACA_API_SECRET` — required for `/api/news`
- `FRED_API_KEY`   — required for real FRED observations on `/api/macro/*`
- `SEC_USER_AGENT` — SEC requires a descriptive UA for EDGAR requests

The app degrades gracefully: routes return empty lists when a key is missing,
rather than crashing.

## Phase 1 → Next

Phase 1 wires the scaffold and Phase-1 data sources. Future phases:

- Options chains + Greeks
- Futures curves
- WebSocket streaming for quotes/news
- Persistence to Postgres (historical warehouse) with Redis-cached reads
- Auth, watchlist persistence, alerting
