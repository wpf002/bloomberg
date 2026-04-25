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
| **3.1** | `9d227ef` | ✅ shipped | Mock portfolio retired — `/api/portfolio/account` + `/api/portfolio/positions` hit live Alpaca paper (`@cached` 10s); new `Account` + `Position` schemas; Portfolio.jsx rewritten with real NAV/cash/BP/equity/day-trade header and unrealized P/L table; shared `get_alpaca_source()` singleton across news + portfolio; creds-missing empty state (no mock fallback). Docker preflight (`scripts/check_docker.sh` + `make up`) with README troubleshooting for the UI-open / VM-paused case. Smoke test lifted to `scripts/smoke.py` (46/46: 24 modules, 6 schemas, 6 Greeks, 16 routes). **Bonuses shipped same commit:** options route now returns empty chain instead of 502 when yfinance throttles; `/api/quotes` routes through Alpaca snapshots first, yfinance only as fallback for symbols Alpaca doesn't carry (indices, futures, FX, non-US). |
| **4** | `1362eed` | ✅ shipped | **Command bar polish:** fuzzy mnemonic matching (`matchMnemonics` ranks exact > prefix > substring > subsequence); ghost-text suggestion + Tab completion; recent-command history in localStorage (↑/↓); live suggestion dropdown with matched-char highlighting. **Position sizing:** `SIZE` / `SIZING` mnemonics, `/api/sizing/{symbol}?stop_pct=N` computes shares at 0.5/1/2/5% account risk using live Alpaca equity; new `PositionSize` + `SizingRow` schemas; `SizingPanel` with stop% input. **LLM synthesis:** YAML prompt registry (`backend/prompts/{explain,compare}.yaml`); `backend/core/llm.py` AsyncAnthropic wrapper; `/api/explain/{symbol}` merges fundamentals + news + SEC filings into a Claude briefing (cached 30m); `/api/compare?symbols=A,B` does side-by-side; multi-symbol parser handles `AAPL MSFT COMPARE`; `EXPLAIN` / `COMPARE` mnemonics; new `Brief` / `ComparisonBrief` schemas; `ExplainPanel` + `ComparePanel` with explicit "Run briefing" button (no auto-fetch — LLM calls aren't free). `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL` env vars plumbed through docker-compose. Smoke test now 55/55: 27 modules, 9 schemas, 6 Greeks, 19 routes. |
| **5** | `9032795` | ✅ shipped | **WebSocket streaming:** `backend/core/streaming.py` runs an in-process `StreamHub` (per-topic asyncio queues with non-blocking publish) + `AlpacaStreamer` that maintains one upstream IEX market-data WS and one news WS, demand-driven symbol subscribe/unsubscribe, exponential-backoff reconnect, REST-poll fallback when `websockets` lib or creds are absent. New `/api/ws/quotes?symbols=`, `/api/ws/news`, `/api/ws/alerts` routes with 25s pings. Frontend `useStream` hook (auto-reconnect, exp backoff, drops the snapshot when disconnected because stale ticks lie); Watchlist now overlays live trade/quote ticks on the polled snapshot with green/red flash on price change. **Paper order entry:** `OrderRequest` + `Order` schemas; `AlpacaSource.list_orders/place_order/cancel_order` thin wrappers over `/v2/orders`; `GET/POST /api/orders` + `DELETE /api/orders/{id}`; `OrderTicket.jsx` (BUY/SELL toggle, market/limit/stop/stop_limit + TIF + extended-hours, working-order list with cancel-✕). Errors from Alpaca propagate verbatim — broker is the source of truth. **Rule-based alerts:** `AlertRule`/`AlertCondition`/`AlertEvent` schemas; `core/alerts.py` evaluates rules on every quotes-topic tick with per-rule cooldown to prevent storm-fire; rules persisted in a Redis hash (`bt:alerts:rules`), fired events appended to a Redis Stream (`bt:alerts:events`, `MAXLEN ~500`) with in-memory fallback when Redis is down; `AlertsPanel.jsx` rule builder + live fire feed via `/api/ws/alerts`; `ALRT`/`ALERT` mnemonics. **Options payoff builder:** `core/payoff.py` computes per-leg expiry intrinsic-value + linear-interp breakevens + bounded/unbounded extrema (detected via slope at the edges); `POST /api/options/payoff` accepts a multi-leg request and returns 121 payoff points resampled at every strike; `PayoffPanel.jsx` with strategy presets (long call/put, covered call, bull spread, iron condor, straddle), per-leg editor, Recharts visualization with breakeven + spot reference lines; `OVME`/`PAYOFF` mnemonics. **New CommandBar chips:** TRADE, ALRT, PAYOFF. **Launchpad:** three new panels (`trade`, `alerts`, `payoff`) added to lg/md/sm layouts; existing scroll-into-view-on-flash now also drives the new panels (Quick chips smooth-scroll into view). `requirements.txt` adds `websockets==12.0`. Smoke test 88/88: 31 modules, 14 schemas, 6 Greeks, 7 payoff math, 27 HTTP routes, 3 WS routes. |
| **6** | `cbcb332` | ✅ shipped | **GitHub OAuth login.** Hand-rolled HS256 JWT in `backend/core/auth.py` (no extra dep) issued as an HttpOnly `bt_session` cookie; `/api/auth/github/login` 302s to GitHub with a CSRF state cookie, `/api/auth/github/callback` exchanges the code, fetches `/user` (+ `/user/emails` fallback when the public email is private), upserts a Postgres `users` row, and 302s back to `FRONTEND_URL`. `/api/auth/me`, `/api/auth/logout`, `/api/auth/status` (so the UI can hide the button when the env vars aren't set). **Postgres schema bootstrap.** `backend/core/schema.py` runs idempotent `CREATE TABLE IF NOT EXISTS` for `users`, `user_watchlists`, `user_layouts`, `user_alert_rules` on FastAPI startup — no migration framework, the surface area is too small to justify it. **Per-user persistence.** `GET/PUT /api/me/watchlist` + `GET/PUT /api/me/layout` round-trip JSONB columns; `Terminal.jsx` reads on login, debounces layout PUTs at 600ms, falls back to localStorage when signed out. `Launchpad.jsx` extended with optional `controlledLayouts` / `controlledHidden` props so the parent can own state without losing the "merge in newly-added panels at factory positions" logic. **DuckDB SQL workbench.** `backend/core/sql_engine.py` runs an in-memory DuckDB con with `bars` (Alpaca/yfinance daily for 10 default symbols × 1y), `macro` (6 FRED series), and `filings` (EDGAR metadata) — warmed in a background task on startup so the server accepts requests immediately. `POST /api/sql` is read-only by construction: a regex validator rejects multiple statements + every DDL/DML keyword _before_ it hits DuckDB, queries run in a worker thread with a hard 8s timeout and 5000-row cap, results JSON-serialize Python types into strings so `Decimal` / `datetime` cells survive. `GET /api/sql/tables` lists schemas + row counts. `SqlPanel.jsx` ships with four preset queries, Cmd/Ctrl+Enter to run, and a sticky-header result table. `SQL`/`BQNT` mnemonics. **Full-text filings search via Meilisearch.** New `meilisearch:v1.7` service in docker-compose with a `meili_data` volume; `backend/data/sources/meilisearch_source.py` indexes filings metadata (always cheap) and optionally fetches+strips the EDGAR primary document body up to 500KB so phrase search works. `GET /api/filings/search?q=&symbol=&form_type=&limit=` and `POST /api/filings/{symbol}/index?full_text=` (admin-ish, on-demand). `FilingsSearchPanel.jsx` parses Meili's `<mark>` highlights into React nodes (no `dangerouslySetInnerHTML`). `SRCH`/`SEARCH` mnemonics. **Frontend.** New `useAuth` hook polls `/api/auth/me` + `/api/auth/status`; footer shows GitHub login button (hidden when not configured) + signed-in `@login` + LOGOUT. All `fetch` calls now send `credentials: "include"` so the cookie reaches the API. `LOGIN`/`LOGOUT`/`SQL`/`BQNT`/`SRCH`/`SEARCH` mnemonics + matching CommandBar chips; two new panels (`sql`, `search`) added to lg/md/sm layouts. **Infra.** `docker-compose.yml` adds Meili + a healthcheck for it + new env vars (`GITHUB_CLIENT_ID/SECRET`, `JWT_SECRET`, `MEILISEARCH_*`, `FRONTEND_URL`); `.env.example` updated with the new keys + GitHub OAuth callback instructions; `requirements.txt` adds `duckdb==0.10.2`. Smoke test 127/127: 41 modules, 14 schemas, 6 Greeks, 7 payoff math, 41 HTTP routes (incl. 14 new auth/me/sql/filings-search routes), 3 WS routes, 4 JWT roundtrip checks, 9 SQL-validator deny-list checks. |
| **7** | _pending commit_ | ✅ shipped | **Shareable Launchpad layouts.** New `shared_layouts` Postgres table (slug PK, owner FK, JSONB layouts/hidden, view_count); `POST /api/me/layout/share` snapshots the user's current layout under a slug like `<login>-<name>-<6 random chars>` (collisions re-rolled), `GET /api/me/layout/shares` lists the user's publishes, `DELETE /api/me/layout/shares/{slug}` removes one. `GET /api/shared/layouts/{slug}` is the public read endpoint — auth-free, joins to `users.login` so the viewer sees who published it, bumps view_count on each fetch (best-effort, errors don't fail the read). New `ShareLayoutDialog.jsx` opens from a SHARE button in Launchpad edit mode (and the `SHARE` mnemonic): name input, publish, copy URL, list-and-delete. `Terminal.jsx` reads `?layout=<slug>` on mount and renders the shared layout in read-only mode (drag disabled, layout-PUT suppressed) with an amber banner ("Viewing X by @owner · Save to my account · Exit"); the Save button PUTs the shared layout to your account so anyone signed-in can adopt a friend's setup. Layouts are snapshotted at publish time — later edits don't propagate to existing shares (republish for a new snapshot). **Per-user alert rules.** `core/alerts.py` rewritten: rules now live in Postgres `user_alert_rules` for authenticated users (Redis `bt:alerts:rules` retained as the fallback path for anonymous deployments). New `AlertEngine.list_all_rules()` (yields `(user_id, rule)` tuples) drives the eval loop; per-rule cooldown unchanged. Fired events tagged with `user_id` and fanned out to two hub topics: `alerts` (legacy/global) and `alerts:user:{id}` (per-user). `/api/ws/alerts` reads the session cookie via `ws.cookies` and decodes the JWT in pure Python — no DB hit on the WS hot path — so signed-in users subscribe to their personal topic and only see their own fires. REST CRUD (`/api/alerts/rules`, `/api/alerts/events`) is auth-aware too: writes go to Postgres tagged with the user's id, lists return only that user's rules. **Bracket / OCO / OTO orders.** `OrderRequest` schema gains `order_class` (`simple`/`bracket`/`oco`/`oto`) plus `take_profit_limit_price`, `stop_loss_stop_price`, `stop_loss_limit_price`. `Order` carries `order_class` + a recursive `legs[]` for bracket children. `AlpacaSource.place_order` builds the right `take_profit` / `stop_loss` sub-objects in the v2 API payload. `/api/orders` POST validates the new combos before dispatch (bracket + oco require both TP and SL prices; oto requires at least one; bracket TIF must be day/gtc since extended-hours brackets aren't a thing). `OrderTicket.jsx` adds a Class selector with conditional TP/SL/SL-limit inputs, helper text per class, and a CLASS column in the recent-orders table. **Filings indexer cron.** New daily background task in `main.py` (`_filings_indexer_cron`) that re-indexes the default watchlist's filings metadata into Meilisearch every 24h; the same `_index_filings_metadata` helper runs once at startup so SRCH has hits immediately on a fresh deploy. **Frontend.** `useStream` automatically lands on the right alerts topic via the cookie (no client change needed). New `SHARE` mnemonic; v0.1 banner now reads "Phase 7"; footer copy updated. Smoke test 145/145: adds the 4 new sharing routes, the bracket/OCO schema checks, and signature checks asserting `AlertEngine.add_rule/list_rules/delete_rule` accept `user_id` plus `list_all_rules` exists. |

Clone & run: `git clone https://github.com/wpf002/bloomberg.git && cd bloomberg/bloomberg-terminal && cp .env.example .env && docker compose up --build`.

---

## 1. Next session — Phase 8 candidate punch list

Phase 7 shipped all four candidates (shareable layouts, per-user alerts,
bracket/OCO orders, filings indexer cron). The §5 Phase 8 vision is
"asset-class depth" — these are the highest-leverage items inside that:

1. **FINRA TRACE corporate prints + Treasury auctions.** Closes the
   biggest fixed-income gap on the feature map. TRACE is free, requires
   registration; Treasury auctions are on TreasuryDirect.
2. **Continuous futures + term structure.** CL / GC / NG / ZC / ZS curves
   with backwardation/contango overlays. Front-month rolls handled via
   yfinance contract chains.
3. **Factor-model portfolio analytics.** Fama-French 5 + Carhart on the
   live Alpaca paper positions. Pulls FF data from Ken French's data
   library (free, monthly).
4. **ESG / climate disclosures from SEC climate-rule filings.** New form
   types in EDGAR; the existing filings indexer can ingest them with a
   form-type extension.

Pick the ones that resonate; ship together rather than fragmenting into
sub-phases.

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
| **Options / derivatives** | `OMON` `OVME` `OVDV` | ✅ Phase 2 (chain + IV smile + Greeks) + Phase 5 (multi-leg payoff diagram) | Phase 6: term structure, vol surface |
| **Crypto** | `XBTC` `DIG` | ✅ Phase 1 | Phase 5: CEX L2 + on-chain |
| **Macroeconomics** | `ECO` `WECO` `GDP` `CPI` | ✅ Phase 1 (FRED) | Phase 5: econ calendar |
| **News** | `TOP` `N` `NI` `MLIV` | ✅ Phase 2 (Alpaca + RSS merged) | Phase 4: LLM summarization |
| **Research (BI)** | Bloomberg Intelligence | ✅ Phase 4 (EXPLAIN / COMPARE via Claude) + Phase 6 (full-text 10-K body indexed in Meili) | Phase 7: shareable briefs |
| **Filings** | `CF` `FIL` | ✅ Phase 2 + Phase 6 (full-text via Meilisearch — `SRCH`) | Phase 7: indexer cron, citation links |
| **Portfolio analytics** | `PORT` `MARS` | ✅ Phase 3.1 (live Alpaca paper) + Phase 5 (order entry) | Phase 6: factor risk, attribution |
| **Trading / OMS/EMS** | `BXT` `TSOX` `EMSX` | ✅ Phase 5 + Phase 7 (bracket / OCO / OTO via Alpaca's `order_class`) | Phase 8: trailing stops, conditional orders |
| **Alerting** | `ALRT` | ✅ Phase 5 + Phase 7 (per-user rules in Postgres, per-user WS topic) | Phase 8: webhook + email destinations |
| **Messaging / IB** | `MSG` `IB` | ❌ | Phase 7: optional Matrix room |
| **Scripting / BQuant** | `BQL` `BQNT` | ✅ Phase 6 (`/api/sql` over DuckDB — `SQL` / `BQNT`) | Phase 7: per-user macros, save queries |
| **Workspace / Launchpad** | Draggable multi-monitor | ✅ Phase 3 + Phase 7 (publish as `?layout=<slug>`, Save-to-account) | Phase 9: PWA / mobile-tuned |
| **Command bar + mnemonics** | `GO` `DES` `N` `GP` `OMON` `HELP` | ✅ Phase 4 (fuzzy + history + Tab) + Phase 5 (TRADE / ALRT / PAYOFF chips) | Phase 6: per-user macros |
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

### Phase 5 — Real-time + alerts + trading ✅ shipped

- WebSocket quote/news streaming from Alpaca + IEX. ✅
- Rule-based alerts (Redis Streams + rule DSL) with WS fan-out. ✅
- Alpaca paper order entry (`/api/orders` POST) — a proper EMS panel. ✅
- Options payoff builder. ✅

### Phase 6 — Persistence + scripting ✅ shipped

- GitHub OAuth + HS256 JWT cookies. ✅
- Per-user watchlists and Launchpad layouts in Postgres. ✅
- `/api/sql` endpoint over DuckDB on cached time-series data — our `BQL`. ✅
- Full-text filings search via Meilisearch (metadata + on-demand body). ✅

### Phase 7 — Sharing + per-user state hardening ✅ shipped

- Shareable Launchpad layouts via `?layout=<slug>` (Postgres-backed). ✅
- Per-user alert rules in Postgres + per-user WS topic. ✅
- Bracket / OCO / OTO orders on the Alpaca ticket. ✅
- Daily filings-indexer cron so `SRCH` stays current. ✅

(The original §5 sketch listed Matrix chat + an alert marketplace; both
were dropped — chat is a hosting question, not a code project, and a
marketplace is a multi-phase undertaking.)

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
