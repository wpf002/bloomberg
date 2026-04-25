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
| **7** | `dd73ec0` | ✅ shipped | **Shareable Launchpad layouts.** New `shared_layouts` Postgres table (slug PK, owner FK, JSONB layouts/hidden, view_count); `POST /api/me/layout/share` snapshots the user's current layout under a slug like `<login>-<name>-<6 random chars>` (collisions re-rolled), `GET /api/me/layout/shares` lists the user's publishes, `DELETE /api/me/layout/shares/{slug}` removes one. `GET /api/shared/layouts/{slug}` is the public read endpoint — auth-free, joins to `users.login` so the viewer sees who published it, bumps view_count on each fetch (best-effort, errors don't fail the read). New `ShareLayoutDialog.jsx` opens from a SHARE button in Launchpad edit mode (and the `SHARE` mnemonic): name input, publish, copy URL, list-and-delete. `Terminal.jsx` reads `?layout=<slug>` on mount and renders the shared layout in read-only mode (drag disabled, layout-PUT suppressed) with an amber banner ("Viewing X by @owner · Save to my account · Exit"); the Save button PUTs the shared layout to your account so anyone signed-in can adopt a friend's setup. Layouts are snapshotted at publish time — later edits don't propagate to existing shares (republish for a new snapshot). **Per-user alert rules.** `core/alerts.py` rewritten: rules now live in Postgres `user_alert_rules` for authenticated users (Redis `bt:alerts:rules` retained as the fallback path for anonymous deployments). New `AlertEngine.list_all_rules()` (yields `(user_id, rule)` tuples) drives the eval loop; per-rule cooldown unchanged. Fired events tagged with `user_id` and fanned out to two hub topics: `alerts` (legacy/global) and `alerts:user:{id}` (per-user). `/api/ws/alerts` reads the session cookie via `ws.cookies` and decodes the JWT in pure Python — no DB hit on the WS hot path — so signed-in users subscribe to their personal topic and only see their own fires. REST CRUD (`/api/alerts/rules`, `/api/alerts/events`) is auth-aware too: writes go to Postgres tagged with the user's id, lists return only that user's rules. **Bracket / OCO / OTO orders.** `OrderRequest` schema gains `order_class` (`simple`/`bracket`/`oco`/`oto`) plus `take_profit_limit_price`, `stop_loss_stop_price`, `stop_loss_limit_price`. `Order` carries `order_class` + a recursive `legs[]` for bracket children. `AlpacaSource.place_order` builds the right `take_profit` / `stop_loss` sub-objects in the v2 API payload. `/api/orders` POST validates the new combos before dispatch (bracket + oco require both TP and SL prices; oto requires at least one; bracket TIF must be day/gtc since extended-hours brackets aren't a thing). `OrderTicket.jsx` adds a Class selector with conditional TP/SL/SL-limit inputs, helper text per class, and a CLASS column in the recent-orders table. **Filings indexer cron.** New daily background task in `main.py` (`_filings_indexer_cron`) that re-indexes the default watchlist's filings metadata into Meilisearch every 24h; the same `_index_filings_metadata` helper runs once at startup so SRCH has hits immediately on a fresh deploy. **Frontend.** `useStream` automatically lands on the right alerts topic via the cookie (no client change needed). New `SHARE` mnemonic; v0.1 banner now reads "Phase 7"; footer copy updated. Smoke test 145/145: adds the 4 new sharing routes, the bracket/OCO schema checks, and signature checks asserting `AlertEngine.add_rule/list_rules/delete_rule` accept `user_id` plus `list_all_rules` exists. |

| **8** | `05c4d76` | ✅ shipped | **Portfolio factor analysis (MARS).** New `backend/core/factor_analysis.py` runs a 6-factor OLS regression — Fama-French 5 (Mkt-RF / SMB / HML / RMW / CMA) + Carhart momentum — against the user's live Alpaca paper portfolio under static current-weights. Daily factors come from Ken French's data library at Dartmouth, downloaded as zipped CSVs in `backend/data/sources/french_source.py`, parsed in a worker thread, and cached for 24h in Redis. `/api/portfolio/factors?lookback_days=` returns betas + alpha (annualized via × 252) + R² + observation count + the symbol weights it ran on. `FactorAnalyticsPanel.jsx` renders the result with plain-English readings ("strongly long the market", "moderately small-cap tilt") next to each beta — designed for non-technical users. `MARS` / `FACTORS` mnemonics. Smoke verifies the OLS engine recovers known coefficients within 0.05 on a synthetic regression with R² > 0.99. **Fixed income (TK).** New `treasury_source.py` wraps TreasuryDirect's free `/TA_WS/securities/{announced,auctioned}` endpoints; `finra_source.py` does the OAuth2 client-credentials handshake against FINRA's IDP and pulls `treasuryMonthlyAggregates` / `treasuryWeeklyAggregates` (the datasets free dev-tier accounts are entitled to — corp-bond TRACE prints need a paid subscription; the route 503s with a clear hint when the keys aren't set). `/api/fixed_income/treasury/auctions?kind=announced|auctioned` and `/api/fixed_income/trace`. `FixedIncomePanel.jsx` is a tabbed viewer (upcoming auctions / recent results / FINRA Treasury aggregates). `TK` / `BAUC` / `TRACE` mnemonics. **Futures (CTM).** `futures_source.py` carries five physical/financial roots (CL / GC / NG / ZC / ZS) with a continuous front-month snapshot strip plus a 12-month forward grid via CME contract month codes (`CLM26.NYM`, etc.). Yahoo periodically blocks the front-month tickers; we now retry via `Ticker.history(period='5d')` and, if that's also empty, fall back to FRED daily-spot series (`DCOILWTICO` / `GOLDAMGBD228NLBM` / `DHHNGSP`) so the strip is reliably populated even when yfinance is throttled. `/api/futures/dashboard` + `/api/futures/curve/{root}`. `FuturesPanel.jsx` shows the strip as a 5-tile header + a Recharts curve with a dashed front-month reference line + plain-English contango/backwardation copy. `CRV` / `CTM` mnemonics. yfinance bumped to 0.2.50. **ESG / climate filings.** Filings search route gets a `?category=esg` preset that issues parallel queries against the form-type families that typically carry climate disclosures (10-K, 8-K, DEF 14A, S-K) and merges the results, deduped by accession number. `FilingsSearchPanel.jsx` adds an "ESG only" checkbox next to the symbol filter. **Infra.** `.env.example` adds `FINRA_API_KEY` + `FINRA_API_SECRET` with a comment pointing at developer.finra.org; docker-compose forwards them to the backend container. Smoke test 145+ checks pass: 4 new Phase 8 schema constructions, 4 OLS-recovers-coefficients sanity checks, 6 new HTTP routes, 5 new module imports. |

| **8.1** | `86a839c` | ✅ shipped | **yfinance retired wholesale.** Yahoo started actively blocking yfinance from this network — even AAPL fails through it. Replacements: Alpaca for equity quotes/charts/options/crypto (already primary, fallback removed); Alpaca via ETF proxy for raw indices (^GSPC→SPY, ^VIX→VIXY, ^DJI→DIA, ^IXIC→QQQ, ^RUT→IWM); FMP only for fundamentals; Finnhub for the earnings calendar + per-symbol news; **new Frankfurter source** (api.frankfurter.dev/v1/latest, ECB reference rates, no key) for FX since Finnhub free tier blocks /forex/rates; FRED-only for futures (CL via DCOILWTICO + NG via DHHNGSP — back-month curve dropped, no public free source). Yahoo Finance RSS feeds removed from the news aggregator. `backend/data/sources/yfinance_source.py` deleted, `yfinance` removed from requirements.txt. Net `−245 lines` across 21 files; 19/19 routes return 200 post-rebuild; `import yfinance` raises ModuleNotFoundError in the container. |
| **8.2** | `f28bd72` | ✅ shipped | **Launchpad chip-scroll fix.** Quick chips on the command bar were silently broken — clicking one flashed the panel amber but the viewport never moved, so chips for off-screen panels appeared to do nothing on tall layouts. Two interlocking root causes diagnosed live with a temporary debug banner: (1) the inline ref callback was being recreated on every flash change and React's "old callback null, new callback node" cycle was leaving the ref empty when our effect fired (`flash=explain but ref=null`); (2) `scrollIntoView({behavior: "smooth"})` and `scrollTo({behavior: "smooth"})` both silently no-op in Safari when the scroll ancestor is a flex child with `overflow: auto`. Fix: query the panel by `data-panel-id` instead of holding a ref (zero React timing dependency) and walk a small candidate list (`<main>` → `.launchpad` → document) short-circuiting on whichever container's `scrollTop` actually moved. Defers one rAF tick so the freshly-applied panel-flash class has committed before measuring. Click an on-screen chip → amber flash, no movement; click an off-screen chip → page snaps the panel to centre then plays the flash. |
| **9** | _pending commit_ | ✅ shipped | **PWA — installable, offline-shell.** New `frontend/public/manifest.webmanifest` + `sw.js` + amber-on-charcoal `icon.svg`. `index.html` adds `<link rel="manifest">`, `<link rel="apple-touch-icon">`, `<meta name="theme-color">`, and the iOS `apple-mobile-web-app-*` meta tags so Add-to-Home-Screen produces a real standalone icon. Service worker caches the static shell on first paint (HTML + Vite-built JS/CSS) and serves cache-first afterwards; never caches `/api/`, never caches non-GET requests, so quotes/news/charts always hit the network and users never trade on stale prices. Registration is gated to non-localhost so HMR doesn't fight the SW during dev. **Theme registry — Dark / Light / High-contrast.** `tailwind.config.js` colour palette refactored to read CSS custom properties (`var(--bt-amber)` etc.); `src/index.css` defines three `.theme-*` blocks (`:root`/.theme-dark default, `.theme-light` with high-amber accent on warm-paper background, `.theme-hc` pure-black/pure-white for low-vision + sunlight). New `useTheme` hook (`src/hooks/useTheme.js`) cycles themes, persists in localStorage, honours `?theme=<slug>` URL params (so themes share like layouts do via Phase 7), updates the meta theme-color on swap. Footer gets a `Theme: <label>` switcher; `THEME` mnemonic. **i18n — EN / ES / PT / ZH.** Hand-rolled provider in `src/i18n/index.jsx` (no react-i18next dep — surface area is small enough to not justify ~30KB gzipped); locale tables in `src/i18n/{en,es,pt,zh}.js` covering app banners, command-bar copy, footer buttons, panel titles, watchlist column headers, share-layout banner, theme/language labels (~50 keys). `t("key", { interpolation })` does dot-path lookup with EN fallback for missing translations. Persists locale choice to localStorage; Spanish/Portuguese covered for headline strings, simplified Chinese (zh-CN) likewise. Footer `Language: <label>` switcher + `LANG` mnemonic. **Mobile-tuned Launchpad.** `Terminal.jsx` watches `(max-width: 720px)` via `matchMedia` and on small screens renders only the priority set: Watchlist, Chart, News, Markets, Portfolio. A `+ MORE PANELS` toggle in the footer reveals the full layout, `− FEWER PANELS` collapses back. The filter is render-time only — sharing/saving still uses the full layout — so a mobile viewer of a desktop layout doesn't get a 19-tile vertical wall. **Frontend chrome translations applied** to `Terminal.jsx` footer + share banner + help dialog, `CommandBar.jsx` (header / placeholder / quick label / TAB-ENTER / last-command / click hint), and `Watchlist.jsx` (title, status, column headers). Other panel internals stay English for now — opening that work is straightforward but bigger; locale tables are wired so they translate as soon as the strings are wrapped. **Infra:** no new env vars or backend changes; backend smoke still 145/145 green. |

Clone & run: `git clone https://github.com/wpf002/bloomberg.git && cd bloomberg/bloomberg-terminal && cp .env.example .env && docker compose up --build`.

---

## 1. Next session — Phase 10 candidate punch list

Phase 9 shipped all four candidates (PWA, mobile-tuned Launchpad,
i18n, theme registry). Open candidates for the next session, ranked
by retail/prosumer leverage:

1. **Translate panel internals.** Phase 9 wired the i18n provider and
   four locale tables but only touched the high-traffic chrome (header,
   footer, share banner, command bar, watchlist). Wrapping the rest of
   the panel content in `t(...)` is mechanical and low-risk.
2. **Public-read dashboards.** Extend the Phase 7 share infrastructure
   to vanity URLs (`/u/dave/scalper`) so a layout share is a
   shareable URL plus a name, not just a slug. Pairs with the existing
   `view_count` we already track.
3. **Yield-curve interpolation + agency MBS.** Adds depth to Phase 8's
   Fixed Income panel — a yield-curve chart from the existing FRED
   `DGS*` series, plus FRED's MBS series (`MORTGAGE30US`, etc.).
4. **Per-user macros.** Let users save command sequences as a single
   mnemonic (e.g. `MYBRIEF` runs `AAPL DES`, then `AAPL EXPLAIN`,
   then opens the alerts panel). Postgres-backed alongside layouts +
   alert rules.

Pick the ones that resonate; ship together rather than fragmenting into
sub-phases.

---

## 2. Feature map — Bloomberg vs. us

Status updated for everything shipped through Phase 3.

| Area | Bloomberg (functions / products) | Our status | Next step |
| --- | --- | --- | --- |
| **Equities — quotes & charts** | `EQS` `DES` `GP` `GIP` `HP` | ✅ Phase 1 + Phase 3 | — |
| **Fundamentals** | `FA` `FS` `RV` `EE` | ✅ Phase 3 (DES / FA mnemonic) | Phase 4: add YoY bar charts |
| **Fixed income** | `TK` `YAS` `BVAL` `TRACE` | ✅ Phase 8 (TreasuryDirect auctions + FINRA Treasury aggregates — `TK`/`BAUC`/`TRACE`) | Phase 9: yield curve interpolation, agency MBS |
| **FX** | `FXIP` `FRD` `WCV` | ✅ Phase 1.1 | Phase 8: cross-rates, forwards |
| **Commodities / futures** | `CMCX` `CTM` `CRV` | ✅ Phase 8 (front-month strip + term-structure curve via yfinance, FRED fallback) | Phase 9: continuous-roll back-adjusted series |
| **Options / derivatives** | `OMON` `OVME` `OVDV` | ✅ Phase 2 (chain + IV smile + Greeks) + Phase 5 (multi-leg payoff diagram) | Phase 6: term structure, vol surface |
| **Crypto** | `XBTC` `DIG` | ✅ Phase 1 | Phase 5: CEX L2 + on-chain |
| **Macroeconomics** | `ECO` `WECO` `GDP` `CPI` | ✅ Phase 1 (FRED) | Phase 5: econ calendar |
| **News** | `TOP` `N` `NI` `MLIV` | ✅ Phase 2 (Alpaca + RSS merged) | Phase 4: LLM summarization |
| **Research (BI)** | Bloomberg Intelligence | ✅ Phase 4 (EXPLAIN / COMPARE via Claude) + Phase 6 (full-text 10-K body indexed in Meili) | Phase 7: shareable briefs |
| **Filings** | `CF` `FIL` | ✅ Phase 2 + Phase 6 (full-text via Meilisearch — `SRCH`) | Phase 7: indexer cron, citation links |
| **Portfolio analytics** | `PORT` `MARS` | ✅ Phase 3.1 + Phase 5 + Phase 8 (Fama-French 5 + Carhart factor regression — `MARS`) | Phase 9: attribution by sector / factor contribution |
| **Trading / OMS/EMS** | `BXT` `TSOX` `EMSX` | ✅ Phase 5 + Phase 7 (bracket / OCO / OTO via Alpaca's `order_class`) | Phase 8: trailing stops, conditional orders |
| **Alerting** | `ALRT` | ✅ Phase 5 + Phase 7 (per-user rules in Postgres, per-user WS topic) | Phase 8: webhook + email destinations |
| **Messaging / IB** | `MSG` `IB` | ❌ | Phase 7: optional Matrix room |
| **Scripting / BQuant** | `BQL` `BQNT` | ✅ Phase 6 (`/api/sql` over DuckDB — `SQL` / `BQNT`) | Phase 7: per-user macros, save queries |
| **Workspace / Launchpad** | Draggable multi-monitor | ✅ Phase 3 + Phase 7 (publish as `?layout=<slug>`, Save-to-account) | Phase 9: PWA / mobile-tuned |
| **Command bar + mnemonics** | `GO` `DES` `N` `GP` `OMON` `HELP` | ✅ Phase 4 (fuzzy + history + Tab) + Phase 5 (TRADE / ALRT / PAYOFF chips) | Phase 6: per-user macros |
| **Indices / benchmarks** | `WEI` `MMAP` `TOP GOV` | ✅ Phase 1.1 | Phase 4: sector heatmap |
| **Mobile** | Bloomberg Anywhere / App | ✅ Phase 9 (PWA + manifest + service worker + mobile-priority layout) | Phase 10: native shell? |
| **ESG / climate** | `ESG` `CARB` | ✅ Phase 8 (`?category=esg` preset on filings search; "ESG only" checkbox in `SRCH`) | Phase 9: dedicated ESG scorecard from filings text |
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

### Phase 8 — Asset-class depth ✅ shipped

- TreasuryDirect auctions + FINRA Treasury aggregates (free dev tier). ✅
- Continuous futures + term structure with FRED fallback. ✅
- Fama-French 5 + Carhart factor regression on Alpaca paper portfolio. ✅
- ESG/climate filings preset filter on SRCH. ✅

### Phase 9 — Mobile + i18n + themes ✅ shipped

- PWA manifest + service worker (installable on iOS/Android/desktop,
  shell cache on first paint, never caches `/api/`). ✅
- Mobile-tuned Launchpad (priority panels on `<= 720px` + MORE/FEWER
  toggle in the footer). ✅
- i18n: EN / ES / PT / ZH with hand-rolled provider, locale tables,
  language switcher, `LANG` mnemonic. ✅
- Theme registry: Dark / Light / High-contrast as CSS-variable
  palettes, shareable via `?theme=<slug>`, `THEME` mnemonic. ✅

---

## 6. Non-goals (on purpose)

- **Real-time consolidated SIP quotes.** Delayed + IEX is the 80% solution.
- **A dealer-to-dealer closed chat network.** Regulatory burden, wrong user.
- **Selling data.** We orchestrate public data — we don't compete with
  exchanges or data vendors on redistribution.

The product is a **frame** around open data, not a data business.
