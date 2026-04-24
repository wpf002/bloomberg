const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options = {}) {
  const url = `${BASE}${path}`;
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status} ${resp.statusText} :: ${text}`);
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
};
