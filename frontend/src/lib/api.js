const BASE = import.meta.env.VITE_API_URL || "";

export function wsURL(path) {
  // VITE_API_URL may be empty (same-origin in prod) or e.g. "http://localhost:8000".
  // Browsers' WebSocket requires ws:// or wss://.
  if (BASE) {
    const u = new URL(path, BASE);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    return u.toString();
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

async function request(path, options = {}) {
  const url = `${BASE}${path}`;
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      if (parsed && parsed.detail) detail = parsed.detail;
    } catch (_) {
      // leave detail as text
    }
    const err = new Error(`${resp.status} ${resp.statusText} :: ${detail}`);
    err.status = resp.status;
    err.detail = detail;
    throw err;
  }
  return resp.json();
}

export const api = {
  quotes: (symbols) =>
    request(`/api/quotes?symbols=${encodeURIComponent(symbols.join(","))}`),
  quote: (symbol) => request(`/api/quotes/${encodeURIComponent(symbol)}`),
  history: (symbol, period = "1mo", interval = "1d") =>
    request(
      `/api/quotes/${encodeURIComponent(symbol)}/history?period=${period}&interval=${interval}`
    ),
  macroSeries: () => request(`/api/macro/series`),
  macroSeriesData: (id, limit = 120) =>
    request(`/api/macro/series/${encodeURIComponent(id)}?limit=${limit}`),
  crypto: (symbols) =>
    request(
      `/api/crypto${symbols ? `?symbols=${encodeURIComponent(symbols.join(","))}` : ""}`
    ),
  news: (symbols, limit = 25) => {
    const q = new URLSearchParams();
    if (symbols?.length) q.set("symbols", symbols.join(","));
    q.set("limit", String(limit));
    return request(`/api/news?${q.toString()}`);
  },
  filings: (symbol) => request(`/api/filings/${encodeURIComponent(symbol)}`),
  fx: (pairs) =>
    request(`/api/fx${pairs ? `?pairs=${encodeURIComponent(pairs.join(","))}` : ""}`),
  options: (symbol, expiration) => {
    const q = expiration ? `?expiration=${encodeURIComponent(expiration)}` : "";
    return request(`/api/options/${encodeURIComponent(symbol)}${q}`);
  },
  overview: () => request(`/api/overview`),
  fundamentals: (symbol) =>
    request(`/api/fundamentals/${encodeURIComponent(symbol)}`),
  earningsCalendar: (symbols, limit = 8) => {
    const q = new URLSearchParams();
    q.set("symbols", symbols.join(","));
    q.set("limit", String(limit));
    return request(`/api/calendar/earnings?${q.toString()}`);
  },
  portfolioAccount: () => request(`/api/portfolio/account`),
  portfolioPositions: () => request(`/api/portfolio/positions`),

  // ── V2.2: manual positions ────────────────────────────────────────────
  manualPositions: () => request(`/api/portfolio/manual`),
  createManualPosition: (body) =>
    request(`/api/portfolio/manual`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateManualPosition: (id, body) =>
    request(`/api/portfolio/manual/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteManualPosition: (id) =>
    request(`/api/portfolio/manual/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  importManualPositions: async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    const url = `${BASE}/api/portfolio/manual/import`;
    const resp = await fetch(url, {
      method: "POST",
      credentials: "include",
      body: fd,
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      const err = new Error(`${resp.status} :: ${text}`);
      err.status = resp.status;
      err.detail = text;
      throw err;
    }
    return resp.json();
  },
  sizing: (symbol, stopPct = 5) =>
    request(`/api/sizing/${encodeURIComponent(symbol)}?stop_pct=${stopPct}`),
  explain: (symbol) => request(`/api/explain/${encodeURIComponent(symbol)}`),
  compare: (symbolA, symbolB) =>
    request(`/api/compare?symbols=${encodeURIComponent(`${symbolA},${symbolB}`)}`),

  // ── orders ────────────────────────────────────────────────────────────
  orders: (status = "all", limit = 50) =>
    request(`/api/orders?status=${encodeURIComponent(status)}&limit=${limit}`),
  placeOrder: (order) =>
    request(`/api/orders`, { method: "POST", body: JSON.stringify(order) }),
  cancelOrder: (orderId) =>
    request(`/api/orders/${encodeURIComponent(orderId)}`, { method: "DELETE" }),

  // ── alerts ────────────────────────────────────────────────────────────
  alertRules: () => request(`/api/alerts/rules`),
  createAlertRule: (rule) =>
    request(`/api/alerts/rules`, { method: "POST", body: JSON.stringify(rule) }),
  deleteAlertRule: (id) =>
    request(`/api/alerts/rules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  alertEvents: (limit = 50) => request(`/api/alerts/events?limit=${limit}`),

  // ── options payoff ────────────────────────────────────────────────────
  optionsPayoff: (body) =>
    request(`/api/options/payoff`, { method: "POST", body: JSON.stringify(body) }),

  // ── auth ──────────────────────────────────────────────────────────────
  authMe: () => request(`/api/auth/me`),
  authStatus: () => request(`/api/auth/status`),
  authLogout: () => request(`/api/auth/logout`, { method: "POST" }),
  // GitHub OAuth login is a full-page redirect, not a fetch — we expose the
  // URL so the caller can `window.location.assign` it.
  authLoginUrl: () => `${BASE}/api/auth/github/login`,

  // ── per-user state ────────────────────────────────────────────────────
  meWatchlist: () => request(`/api/me/watchlist`),
  putWatchlist: (symbols) =>
    request(`/api/me/watchlist`, {
      method: "PUT",
      body: JSON.stringify({ symbols }),
    }),
  meLayout: () => request(`/api/me/layout`),
  putLayout: (layouts, hidden) =>
    request(`/api/me/layout`, {
      method: "PUT",
      body: JSON.stringify({ layouts, hidden }),
    }),

  // ── shared layouts (Phase 7) ──────────────────────────────────────────
  shareLayout: (name) =>
    request(`/api/me/layout/share`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  myShares: () => request(`/api/me/layout/shares`),
  deleteShare: (slug) =>
    request(`/api/me/layout/shares/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    }),
  fetchSharedLayout: (slug) =>
    request(`/api/shared/layouts/${encodeURIComponent(slug)}`),

  // ── Phase 8: portfolio factor analysis (Fama-French 5 + Carhart) ─────
  portfolioFactors: (lookbackDays = 252) =>
    request(`/api/portfolio/factors?lookback_days=${lookbackDays}`),

  // ── Phase 8: fixed income (Treasury auctions + FINRA TRACE) ──────────
  fixedIncomeStatus: () => request(`/api/fixed_income/status`),
  treasuryAuctions: (kind = "announced", limit = 20) =>
    request(`/api/fixed_income/treasury/auctions?kind=${kind}&limit=${limit}`),
  traceAggregates: (cusip, limit = 50) => {
    const q = new URLSearchParams();
    q.set("limit", String(limit));
    if (cusip) q.set("cusip", cusip);
    return request(`/api/fixed_income/trace?${q.toString()}`);
  },
  // Phase 9.2: cubic-spline yield curve + Agency MBS / credit spreads
  yieldCurve: () => request(`/api/fixed_income/curve`),
  agencyMbs: () => request(`/api/fixed_income/mbs`),

  // ── Phase 8: futures dashboard + per-root term structure ─────────────
  futuresDashboard: () => request(`/api/futures/dashboard`),
  futuresCurve: (root) => request(`/api/futures/curve/${encodeURIComponent(root)}`),

  // Phase 9.1: command-bar symbol autocomplete
  searchSymbols: (q, limit = 8) =>
    request(`/api/symbols/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  // ── AURORA Module 1: data provenance ──────────────────────────────────
  provenance: (symbol, { limit = 100, seriesId } = {}) => {
    const q = new URLSearchParams({ symbol, limit: String(limit) });
    if (seriesId) q.set("series_id", seriesId);
    return request(`/api/provenance?${q.toString()}`);
  },

  // ── AURORA Module 2: risk engine ──────────────────────────────────────
  riskExposure: () => request(`/api/risk/exposure`),
  riskCorrelation: () => request(`/api/risk/correlation`),
  riskDrawdown: () => request(`/api/risk/drawdown`),
  riskVar: () => request(`/api/risk/var`),
  riskStress: () => request(`/api/risk/stress`),

  // ── AURORA Module 3: intelligence engine ──────────────────────────────
  intelRegime: () => request(`/api/intelligence/regime`),
  intelFragility: () => request(`/api/intelligence/fragility`),
  intelFlows: () => request(`/api/intelligence/flows`),
  intelRotation: () => request(`/api/intelligence/rotation`),

  // ── AURORA Module 4: AI advisor (streaming) ───────────────────────────
  // Endpoints: review, picks, ask, brief, alert-analysis (Module 4) +
  // validate-thesis, simulate, earnings-prep, rebalance, open-brief,
  // post-mortem (Phase 9.2). All return a streaming text/plain Response.
  advisorStream: (endpoint, body) =>
    fetch(`${BASE}/api/advisor/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body || {}),
    }),

  // ── AURORA Module 5: audit log ────────────────────────────────────────
  audit: (symbol, { from, to, limit = 100 } = {}) => {
    const q = new URLSearchParams({ symbol, limit: String(limit) });
    if (from) q.set("from", from);
    if (to) q.set("to", to);
    return request(`/api/audit?${q.toString()}`);
  },
  intelSnapshots: (kind, limit = 50) =>
    request(`/api/audit/snapshots?kind=${encodeURIComponent(kind)}&limit=${limit}`),

  // Phase 8: ESG-only filings search (preset over the existing endpoint)
  filingsSearchEsg: (q, { symbol, limit = 20 } = {}) => {
    const params = new URLSearchParams({ q, limit: String(limit), category: "esg" });
    if (symbol) params.set("symbol", symbol);
    return request(`/api/filings/search?${params.toString()}`);
  },

  // ── SQL (DuckDB) ──────────────────────────────────────────────────────
  sqlTables: () => request(`/api/sql/tables`),
  sqlQuery: (query, maxRows) =>
    request(`/api/sql`, {
      method: "POST",
      body: JSON.stringify({ query, max_rows: maxRows ?? null }),
    }),

  // ── V2.3: options flow + dark pool ────────────────────────────────────
  flowOptions: ({ symbol, side = "all", minPremium = 100000, expiry = "all", sector } = {}) => {
    const q = new URLSearchParams({
      side,
      min_premium: String(minPremium),
      expiry,
    });
    if (symbol) q.set("symbol", symbol);
    if (sector) q.set("sector", sector);
    return request(`/api/flow/options?${q.toString()}`);
  },
  flowDarkPool: ({ symbol, minPremium = 100000 } = {}) => {
    const q = new URLSearchParams({ min_premium: String(minPremium) });
    if (symbol) q.set("symbol", symbol);
    return request(`/api/flow/darkpool?${q.toString()}`);
  },
  flowSweeps: ({ symbol, side = "all", minPremium = 100000, sector } = {}) => {
    const q = new URLSearchParams({ side, min_premium: String(minPremium) });
    if (symbol) q.set("symbol", symbol);
    if (sector) q.set("sector", sector);
    return request(`/api/flow/sweeps?${q.toString()}`);
  },
  flowUnusual: ({ symbol, minPremium = 100000 } = {}) => {
    const q = new URLSearchParams({ min_premium: String(minPremium) });
    if (symbol) q.set("symbol", symbol);
    return request(`/api/flow/unusual?${q.toString()}`);
  },
  flowHeatmap: ({ side = "all", minPremium = 100000 } = {}) =>
    request(`/api/flow/heatmap?side=${side}&min_premium=${minPremium}`),

  // ── V2.4: GEX / VEX ─────────────────────────────────────────────────
  gexProfile: (symbol) => request(`/api/gex/${encodeURIComponent(symbol)}`),
  vexProfile: (symbol) => request(`/api/vex/${encodeURIComponent(symbol)}`),
  gexLevels: (symbol) => request(`/api/gex/${encodeURIComponent(symbol)}/levels`),

  // ── filings search ────────────────────────────────────────────────────
  filingsSearch: (q, { symbol, formType, limit = 20 } = {}) => {
    const params = new URLSearchParams({ q, limit: String(limit) });
    if (symbol) params.set("symbol", symbol);
    if (formType) params.set("form_type", formType);
    return request(`/api/filings/search?${params.toString()}`);
  },
  indexFilings: (symbol, { fullText = false, limit = 10 } = {}) => {
    const params = new URLSearchParams({
      limit: String(limit),
      full_text: fullText ? "true" : "false",
    });
    return request(`/api/filings/${encodeURIComponent(symbol)}/index?${params.toString()}`, {
      method: "POST",
    });
  },
};
