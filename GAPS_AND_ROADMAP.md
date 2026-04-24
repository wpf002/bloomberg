# Roadmap — Bloomberg Terminal (Public Edition)

**Source benchmark:** [professional.bloomberg.com/products/bloomberg-terminal](https://professional.bloomberg.com/products/bloomberg-terminal/#overview)

Thesis: the data is no longer the moat — distribution and price are. We cover
~80% of the real workflow at $0 seat cost by stitching together public and
freemium providers, and we beat Bloomberg on the things that matter to
retail, prosumers, students, and emerging-market analysts: **openness, price,
programmability, and crypto-native coverage.**

---

## 0. Progress at a glance

| Phase | Commit | Status | What shipped |
| --- | --- | --- | --- |
| **1** | `d77515c` | ✅ shipped | FastAPI + asyncpg + Redis scaffold; yfinance / Alpaca / FRED / SEC EDGAR adapters; React 18 + Vite + Tailwind + Recharts panels; Watchlist / Chart / News / Macro / Portfolio (mock) / Crypto; Docker Compose (Postgres 15 + Redis 7 + backend + frontend). |
| **1.1** | `c2ea8b9` | ✅ shipped | Gap-analysis doc; `/api/fx`, `/api/options/{symbol}`, `/api/overview`; Markets Overview panel; Bloomberg-style mnemonic dispatcher (`AAPL DES`, `SPY GP`, `NVDA OMON`, `EURUSD FXIP`, `HELP`, …). |
| **2** | `9803bb0` | ✅ shipped | Black-Scholes Greeks (stdlib; verified vs. Hull); Redis TTL cache decorator with pydantic-aware (de)serialization; multi-source RSS news (Yahoo / Nasdaq / MarketWatch / SEC) merged with Alpaca; **Options panel** with IV smile + call/put Greeks table; **Filings panel**; right-column tab switcher (News / Options / Filings) driven by intent. |
| **3** | `b4e3664` | ✅ shipped | Fundamentals endpoint + panel (valuation / performance / margins / 52w); earnings-calendar endpoint + panel with EPS surprise; **draggable/resizable Launchpad** (`react-grid-layout`, localStorage-persisted, show/hide per panel, `LAYOUT` + `RESET` mnemonics); Python 3.11 smoke test (`uv` + `/tmp/bt_smoke.py`) that passes: 22/22 modules, 4/4 schemas, 6/6 Greek checks, 17/17 routes. |
| **3.1** | _pending commit_ | ✅ shipped | Mock portfolio retired — `/api/portfolio/account` + `/api/portfolio/positions` hit live Alpaca paper (`@cached` 10s); new `Account` + `Position` schemas; Portfolio.jsx rewritten with real NAV/cash/BP/equity/day-trade header and unrealized P/L table; shared `get_alpaca_source()` singleton across news + portfolio; creds-missing empty state (no mock fallback). Docker preflight (`scripts/check_docker.sh` + `make up`) with README troubleshooting for the UI-open / VM-paused case. Smoke test lifted to `scripts/smoke.py` (46/46: 24 modules, 6 schemas, 6 Greeks, 16 routes). **Bonuses unscoped in 3.1 but shipped same session:** options route now returns empty chain instead of 502 when yfinance throttles; `/api/quotes` routes through Alpaca snapshots first, yfinance only as fallback for symbols Alpaca doesn't carry (indices, futures, FX, non-US). |

Clone & run: `git clone https://github.com/wpf002/bloomberg.git && cd bloomberg/bloomberg-terminal && cp .env.example .env && docker compose up --build`.

---

## 1. Next session — Phase 3.1 punch list

Two items, both scoped. Estimated ≤ 1 session.

### 1.1 Replace mock portfolio with Alpaca paper-trading (decided)

**Only remaining mock in the app** is the hardcoded `HOLDINGS` array in
`frontend/src/components/Portfolio.jsx`. Everything else (quotes, history,
options + Greeks, FX, crypto, fundamentals, earnings, macro, filings, news,
market overview) is already real.

**Chosen approach:** Alpaca paper-trading over local JSON or Postgres seed,
because it gives us a real broker API (positions, orders, account equity,
day-trade count, buying power), lot-level detail, server-side P/L, and maps
cleanly onto Bloomberg's EMSX/OMS paradigm. Zero cost on a paper account.

Work items:

- [ ] Extend `backend/data/sources/alpaca_source.py`:
  - `get_account()` → `GET {trading_base}/v2/account`
  - `get_positions()` → `GET {trading_base}/v2/positions`
  - Re-use the existing `ALPACA_API_KEY` / `ALPACA_API_SECRET` / `ALPACA_BASE_URL` (which already defaults to `https://paper-api.alpaca.markets`).
- [ ] Pydantic models in `backend/models/schemas.py`: `Account`, `Position` (fields in the scratchpad below).
- [ ] Routes:
  - `GET /api/portfolio/account` → `Account`
  - `GET /api/portfolio/positions` → `List[Position]`
  - Both with `@cached("alpaca:account", ttl=10)` and `("alpaca:positions", ttl=10)`.
- [ ] Rewrite `frontend/src/components/Portfolio.jsx` to fetch live from those two endpoints; show account NAV / cash / buying power header, positions table with real unrealized P/L and today's change.
- [ ] Empty-state CTA when no Alpaca creds: "Add `ALPACA_API_KEY` + `ALPACA_API_SECRET` to `.env` and restart to see live positions. Get a free paper account at alpaca.markets/signup." — **do not fall back to mock data**.
- [ ] Update `/api/news` + `/api/portfolio` to share the single Alpaca client instance (minor refactor).
- [ ] Update the smoke test to assert `/api/portfolio/account` and `/api/portfolio/positions` are registered.
- [ ] Update README endpoint table + note the Alpaca paper signup flow.

Scratchpad — planned schema shape (don't treat as final):

```python
class Account(BaseModel):
    account_number: str | None
    status: str | None
    currency: str = "USD"
    cash: float
    buying_power: float
    portfolio_value: float
    equity: float
    last_equity: float
    long_market_value: float
    short_market_value: float
    daytrade_count: int
    pattern_day_trader: bool
    source: str = "alpaca-paper"

class Position(BaseModel):
    symbol: str
    asset_class: str | None
    exchange: str | None
    qty: float
    side: str = "long"
    avg_entry_price: float
    current_price: float | None
    market_value: float | None
    cost_basis: float | None
    unrealized_pl: float | None
    unrealized_pl_percent: float | None
    unrealized_intraday_pl: float | None
    unrealized_intraday_pl_percent: float | None
    change_today_percent: float | None
    source: str = "alpaca-paper"
```

### 1.2 Docker engine preflight + troubleshooting (dev experience)

**Problem seen live:** Docker Desktop's UI is open, the socket exists, the
symlink is correct — but `docker version` reports:

> Cannot connect to the Docker daemon at `unix:///Users/willfoti/.docker/run/docker.sock`

Cause: the Docker Desktop Electron app and the Linux VM that hosts `dockerd`
are independent. The VM can be paused while the dashboard is up. Someone
running `docker compose up` for the first time gets an opaque error.

Work items:

- [ ] `scripts/check_docker.sh`:
  - Probes `docker version` (client vs. server)
  - If server is missing, probes the socket directly with `curl --unix-socket ~/.docker/run/docker.sock /_ping`
  - Prints a human message: _"Docker Desktop is running but the engine is paused. Click the whale icon in the menu bar → **Resume**, then re-run."_
  - Exits non-zero so `make` / CI surfaces it.
- [ ] Wrap `docker compose up` in a `make up` target that runs the preflight first.
- [ ] README "Troubleshooting" section:
  - The UI-open / engine-paused distinction
  - Verify with `docker version` (client-only ≠ healthy)
  - Resume from the whale menu → _Start_ / _Resume_
  - Last resort: `osascript -e 'quit app "Docker"' && open -a Docker`
- [ ] Not an action on the user's machine: we **never** auto-restart Docker from this repo's scripts — it kills any running containers.

---

## 2. Feature map — Bloomberg vs. us

Status updated for everything shipped through Phase 3.

| Area | Bloomberg (functions / products) | Our status | Next step |
| --- | --- | --- | --- |
| **Equities — quotes & charts** | `EQS` `DES` `GP` `GIP` `HP` | ✅ Phase 1 + Phase 3 | — |
| **Fundamentals** | `FA` `FS` `RV` `EE` | ✅ Phase 3 (DES / FA mnemonic) | Phase 4: add YoY bar charts |
| **Fixed income** | `TK` `YAS` `BVAL` `TRACE` | ⚠️ FRED treasuries only | Phase 8: add FINRA TRACE + Treasury auctions |
| **FX** | `FXIP` `FRD` `WCV` | ✅ Phase 1.1 | Phase 8: cross-rates, forwards |
| **Commodities / futures** | `CMCX` `CTM` `CRV` | ⚠️ via overview tiles | Phase 8: curve builder |
| **Options / derivatives** | `OMON` `OVME` `OVDV` | ✅ Phase 2 (chain + IV smile + Greeks) | Phase 4: payoff builder, term structure |
| **Crypto** | `XBTC` `DIG` | ✅ Phase 1 | Phase 5: CEX L2 + on-chain |
| **Macroeconomics** | `ECO` `WECO` `GDP` `CPI` | ✅ Phase 1 (FRED) | Phase 5: econ calendar |
| **News** | `TOP` `N` `NI` `MLIV` | ✅ Phase 2 (Alpaca + RSS merged) | Phase 4: LLM summarization |
| **Research (BI)** | Bloomberg Intelligence | ❌ | Phase 4: LLM-synthesized from 10-K + calls |
| **Filings** | `CF` `FIL` | ✅ Phase 2 | Phase 6: full-text search |
| **Portfolio analytics** | `PORT` `MARS` | ✅ Phase 3.1 (live Alpaca paper) | Phase 5: order entry |
| **Trading / OMS/EMS** | `BXT` `TSOX` `EMSX` | ❌ | Phase 5: Alpaca paper orders |
| **Alerting** | `ALRT` | ❌ | Phase 5: Redis Streams + WS push |
| **Messaging / IB** | `MSG` `IB` | ❌ | Phase 7: optional Matrix room |
| **Scripting / BQuant** | `BQL` `BQNT` | ❌ | Phase 6: `/api/sql` over DuckDB |
| **Workspace / Launchpad** | Draggable multi-monitor | ✅ Phase 3 | Phase 7: shareable layout JSON |
| **Command bar + mnemonics** | `GO` `DES` `N` `GP` `OMON` `HELP` | ✅ Phase 1.1 + 3 | Phase 4: fuzzy matching, history |
| **Indices / benchmarks** | `WEI` `MMAP` `TOP GOV` | ✅ Phase 1.1 | Phase 4: sector heatmap |
| **Mobile** | Bloomberg Anywhere / App | ⚠️ responsive breakpoints exist | Phase 9: PWA + tuned layouts |
| **ESG / climate** | `ESG` `CARB` | ❌ | Phase 8 |
| **Community / network** | IB (~350k users) | ❌ | Phase 7 (open-by-default) |

---

## 3. What Bloomberg does that we **cannot** match cheaply

Honest moats. Not trying to close these.

1. **Tick-level consolidated market data (SIP).** Direct exchange feeds cost
   $100k+/year. We'll stay delayed or use IEX (Alpaca's free tier).
2. **Dealer-run pricing (BVAL) for illiquid FI.** No open equivalent.
3. **Regulated dealer-to-dealer chat network (IB).** A compliance moat, not
   a tech moat — wrong posture for us to adopt.
4. **Premium research (Bloomberg Intelligence, BIO).** We partially cover
   with LLM synthesis of public filings (Phase 4), but not license-grade.
5. **Install-base network effect.** IB's value scales with its 350k users.
   We ship open / self-hosted; community forms differently.

---

## 4. Where we beat Bloomberg for the 99%

1. **Price** — $0 self-host vs. ~$32k/seat/yr.
2. **Crypto parity** — native depth across CEXes + on-chain, not a bolt-on.
3. **Programmability** — every panel is a REST endpoint. Python + JS.
   Notebook-friendly. No `BQL` contract.
4. **LLM-native** (Phase 4) — `AAPL EXPLAIN` over 10-K + call + news.
5. **Open layouts & themes** — share a Launchpad layout as JSON/URL.
6. **Retail workflows** — options profit-curve, share-lot P/L, tax-aware
   cost basis, 1099 import.
7. **Emerging-market & Spanish/Portuguese UX out of the box** — an
   underserved user base.
8. **Privacy-respecting** — self-hosted, watchlist never leaves your box.

---

## 5. Future phases

### Phase 4 — LLM synthesis + command bar polish

- `AAPL EXPLAIN`: summarize recent 10-K + latest earnings call + last-7-day
  news. Prompts stored in a YAML registry so they're swappable.
- `AAPL vs MSFT COMPARE`: side-by-side on the same dimensions.
- `AAPL SIZING`: Kelly / fixed-fractional position-size suggestion.
- Fuzzy mnemonic matching, recent-command history, tab completion.

### Phase 5 — Real-time + alerts + trading

- WebSocket quote/news streaming from Alpaca + IEX.
- Rule-based alerts (Redis Streams + rule DSL) with WS fan-out.
- Alpaca paper order entry (`/api/orders` POST) — a proper EMS panel.
- Options payoff builder.

### Phase 6 — Persistence + scripting

- Auth (magic-link email or GitHub OAuth).
- Per-user watchlists and Launchpad layouts in Postgres.
- `/api/sql` endpoint over DuckDB on cached time-series data — our `BQL`.
- Full-text filings search (Meilisearch or Typesense on EDGAR text).

### Phase 7 — Community + sharing

- Shareable Launchpad layouts via URL or JSON file.
- Public-read dashboards ("Dave's Watchlist").
- Optional Matrix-backed chat room.
- Alert marketplace (public rules others can subscribe to).

### Phase 8 — Asset-class depth

- FINRA TRACE corporate prints; Treasury.gov auctions.
- Continuous futures + term structure (CL, GC, NG, ZC, ZS).
- Factor-model portfolio analytics (Fama-French 5, Carhart).
- ESG / climate disclosures from SEC climate rule filings.

### Phase 9 — Mobile + i18n

- PWA manifest + service worker.
- Mobile-tuned Launchpad (lg / md / sm already responsive; needs design).
- i18n: EN, ES, PT, ZH.
- Dark / light / high-contrast themes as shareable JSON.

---

## 6. Non-goals (on purpose)

- **Real-time consolidated SIP quotes.** Delayed + IEX is the 80% solution.
- **A dealer-to-dealer closed chat network.** Regulatory burden, wrong user.
- **Selling data.** We orchestrate public data — we don't compete with
  exchanges or data vendors on redistribution.

The product is a **frame** around open data, not a data business.
