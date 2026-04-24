const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options = {}) {
  const url = `${BASE}${path}`;
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
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
  sizing: (symbol, stopPct = 5) =>
    request(`/api/sizing/${encodeURIComponent(symbol)}?stop_pct=${stopPct}`),
  explain: (symbol) => request(`/api/explain/${encodeURIComponent(symbol)}`),
  compare: (symbolA, symbolB) =>
    request(`/api/compare?symbols=${encodeURIComponent(`${symbolA},${symbolB}`)}`),
};
