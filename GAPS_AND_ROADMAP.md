# Gaps & Roadmap — Building a Bloomberg Terminal for the 99%

**Source:** [professional.bloomberg.com/products/bloomberg-terminal](https://professional.bloomberg.com/products/bloomberg-terminal/#overview)

Bloomberg's sell is: *best-in-class data + research + analytics + trading + a
350,000-person closed network*, delivered through a dense keyboard-driven UI,
a proprietary network (B-Pipe), and a ~$32k/seat/year price tag.

Our thesis: **the data is no longer the moat — distribution and price are.**
We can cover ~80% of the real workflow at $0 seat cost by stitching together
public + freemium data providers, and we can beat Bloomberg on the things
that matter to retail, prosumers, students, and emerging-market analysts:
**openness, price, programmability, and crypto-native coverage.**

---

## 1. Feature Map — Bloomberg vs. Us (Phase 1)

| Area | Bloomberg (functions / products) | Phase 1 (this repo) | Gap / Status |
|---|---|---|---|
| **Equities — quotes & charts** | `EQS`, `DES`, `GP`, `GIP`, `HP` | `/api/quotes`, `/api/quotes/{s}/history` | ✅ functional (yfinance delayed) |
| **Fundamentals** | `FA`, `FS`, `RV`, `EE` | ❌ | Add yfinance/Stooq/Financial Modeling Prep adapter |
| **Fixed income** | `TK`, `YAS`, `BVAL`, `TRACE` | FRED Treasury series only | Add FINRA TRACE + Treasury.gov direct auction data |
| **FX** | `FXIP`, `FRD`, `WCV` | ✅ added in Phase 1.1 (yfinance pairs) | Expand to forwards/crosses via Frankfurter.app |
| **Commodities / futures** | `CMCX`, `CTM`, `CRV` | ❌ | yfinance continuous contracts (`CL=F`, `GC=F`, `NG=F`) + curve build |
| **Options / derivatives** | `OMON`, `OVME`, `OVDV` | ✅ added in Phase 1.1 (yfinance chain + IV) | Add Greeks (py_vollib), skew, term structure |
| **Crypto** | `XBTC`, `DIG` | ✅ yfinance + extensible | Upgrade to Coinbase / Binance / Kraken public REST+WS |
| **Macroeconomics** | `ECO`, `WECO`, `GDP`, `CPI` | ✅ FRED | Add Trading Economics calendar or `econdb` for global |
| **News** | `TOP`, `N`, `NI`, `MLIV` | Alpaca News | Add Reuters/Yahoo/MarketAux RSS, polygon.io news, GDELT |
| **Research (BI)** | Bloomberg Intelligence | ❌ | LLM-synthesized 10-K / earnings call summaries (SEC EDGAR + Whisper) |
| **Filings** | `CF`, `FIL` | ✅ SEC EDGAR | Add full-text search over filings (Typesense/Meilisearch) |
| **Portfolio analytics** | `PORT`, `MARS`, `FA-FX` | ✅ P/L only | Add Fama-French risk attribution, VaR, factor exposures |
| **Trading / OMS/EMS** | `BXT`, `TSOX`, `EMSX` | ❌ | Alpaca paper-trading adapter (`/api/orders`) — retail-friendly |
| **Alerting** | `ALRT` | ❌ | Build: Redis streams + WS fan-out + rule engine |
| **Messaging / IB** | `MSG`, `IB` | ❌ | Optional: self-hosted Matrix or a lightweight room chat |
| **Scripting / BQuant** | `BQL`, `BQNT` | ❌ | Expose `/api/sql` over DuckDB on cached data |
| **Workspace / Launchpad** | Launchpad (draggable grid) | Static 12-col CSS grid | Upgrade to `react-grid-layout` + persisted layouts |
| **Command bar + mnemonics** | `GO`, `DES`, `N`, `GP`, `OMON`, `HELP` | ✅ mnemonic dispatcher added in Phase 1.1 | Extend function registry; fuzzy matching |
| **Indices / benchmarks** | `WEI`, `MMAP`, `TOP GOV` | ✅ Markets Overview panel (Phase 1.1) | Add sector heatmap |
| **Mobile** | Bloomberg Anywhere / App | ❌ | Responsive layout + PWA manifest |
| **ESG / climate** | `ESG`, `CARB` | ❌ | OpenESG / SEC climate disclosures |
| **Community / network** | IB messaging (~350k users) | ❌ | Public by default — Discord-style room + shared watchlists |

---

## 2. What Bloomberg does that we **cannot** match cheaply

Be honest about these — they're real moats:

1. **Tick-level consolidated market data (SIP).** Direct exchange feeds cost
   $100k+/year. We'll remain delayed or use IEX real-time (Alpaca's free tier).
2. **Dealer-run pricing (BVAL) for illiquid FI.** No open equivalent.
3. **Regulated dealer-to-dealer chat network (IB).** Legally operated closed
   network — compliance moat, not a tech moat.
4. **Premium research (Bloomberg Intelligence, BIO).** We can partially cover
   with LLM-summarized public filings + transcripts, but not license-grade.
5. **The install base itself** — IB's value scales with the 350k network. We
   ship as open/self-hosted, so the community forms differently.

---

## 3. Where we can **beat** Bloomberg (for the 99%)

1. **Price.** $0 self-host vs. ~$32k/seat/yr. Removes the single biggest barrier.
2. **Crypto parity.** Native depth across CEXes & on-chain, not a bolt-on.
3. **Programmability.** Every panel is a REST endpoint. Python + JS. Notebooks.
   You don't need a `BQL` contract with us.
4. **LLM-native.** `AAPL EXPLAIN` mnemonic that runs a local/hosted LLM over
   the last 10-K, earnings call, and news — the kind of synthesis BI sells.
5. **Open layouts & themes.** Share a Launchpad layout as a JSON file or URL.
6. **Retail workflows first.** Options profit-curve, share-lot P/L, tax-aware
   cost basis, 1099 import — all things Bloomberg ignores because their users
   don't need them.
7. **Emerging-market & Spanish/Portuguese-language UX out of the box** — an
   addressable user base Bloomberg has historically under-served.
8. **Privacy-respecting.** Self-hosted means your watchlist never leaves your
   machine. Genuinely novel positioning in finance software.

---

## 4. Concrete Roadmap

### Phase 1 (shipped)
- FastAPI + Postgres + Redis backend scaffold
- React + Tailwind + Recharts multi-panel UI
- Data adapters: yfinance, Alpaca, FRED, SEC EDGAR
- Panels: Watchlist, Chart, News, Macro, Portfolio, Crypto
- Docker Compose stack

### Phase 1.1 (this commit — gap closers)
- `/api/fx` endpoint (yfinance forex pairs)
- `/api/options/{symbol}` endpoint (option chain + implied vol)
- `/api/overview` endpoint: global snapshot (SPX, NDX, VIX, DXY, 10Y, WTI, gold, BTC)
- **Markets Overview** panel — Bloomberg-style `WEI`/`MMAP` equivalent
- **Mnemonic command dispatcher**: `AAPL DES`, `AAPL GP`, `AAPL N`, `AAPL OMON`, `AAPL FIL`
- This document

### Phase 2 — the workflow parity sprint
- Options chain UI with vol smile + Greeks (py_vollib)
- Fundamentals panel (TTM/YoY tables, ratios)
- Earnings & economic calendars
- Reuters/Yahoo/MarketAux multi-source news
- Redis caching layer + rate-limit governors per provider

### Phase 3 — the differentiators
- LLM-backed `EXPLAIN` and `COMPARE` mnemonics (filings + calls + news)
- `react-grid-layout` draggable Launchpad with saved layouts
- WebSocket streaming (quotes, news, alerts)
- Alpaca paper-trading OMS/EMS panel
- Alert engine (rule DSL → WS push)
- Auth + per-user persisted watchlists/layouts

### Phase 4 — community & scale
- Shareable layouts + watchlists via URL
- Public crypto + on-chain depth (Binance/Coinbase/Kraken WS)
- Factor-model portfolio analytics (Fama-French 5, Carhart)
- PWA / mobile layout
- i18n (EN, ES, PT, ZH)

---

## 5. Non-goals (on purpose)

- **Real-time consolidated SIP quotes.** Delayed + IEX is the 80% solution.
- **A dealer-to-dealer closed chat network.** Regulatory burden, wrong user.
- **Selling data.** We orchestrate public data — we don't compete with
  exchanges or data vendors on redistribution.

The product is a **frame** around open data, not a data business.
