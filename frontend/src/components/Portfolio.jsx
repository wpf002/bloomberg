import { useMemo } from "react";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";

const HOLDINGS = [
  { symbol: "AAPL", qty: 120, cost: 168.2 },
  { symbol: "MSFT", qty: 60, cost: 312.5 },
  { symbol: "NVDA", qty: 40, cost: 480.0 },
  { symbol: "SPY", qty: 25, cost: 455.1 },
  { symbol: "TLT", qty: 100, cost: 94.75 },
];

function fmt(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export default function Portfolio() {
  const symbols = HOLDINGS.map((h) => h.symbol);
  const { data, error, loading } = usePolling(
    () => api.quotes(symbols),
    30_000,
    [symbols.join(",")]
  );

  const rows = useMemo(() => {
    if (!data) return [];
    const quoteBySym = Object.fromEntries(data.map((q) => [q.symbol, q]));
    return HOLDINGS.map((h) => {
      const quote = quoteBySym[h.symbol];
      const price = quote?.price ?? 0;
      const market = price * h.qty;
      const basis = h.cost * h.qty;
      const pnl = market - basis;
      const pnlPct = basis ? (pnl / basis) * 100 : 0;
      return { ...h, price, market, basis, pnl, pnlPct };
    });
  }, [data]);

  const totals = rows.reduce(
    (acc, r) => {
      acc.market += r.market;
      acc.basis += r.basis;
      acc.pnl += r.pnl;
      return acc;
    },
    { market: 0, basis: 0, pnl: 0 }
  );
  const totalPct = totals.basis ? (totals.pnl / totals.basis) * 100 : 0;

  return (
    <Panel
      title="Portfolio"
      accent="amber"
      actions={
        <span className="tabular text-terminal-muted">
          NAV {fmt(totals.market)}{" "}
          <span
            className={
              totals.pnl >= 0 ? "text-terminal-green" : "text-terminal-red"
            }
          >
            ({totals.pnl >= 0 ? "+" : ""}
            {fmt(totalPct)}%)
          </span>
        </span>
      }
    >
      {loading && !data ? (
        <div className="text-terminal-muted">Loading positions…</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (
        <table className="w-full text-xs tabular">
          <thead>
            <tr className="text-left text-terminal-muted">
              <th className="py-1 pr-2">SYM</th>
              <th className="py-1 pr-2 text-right">QTY</th>
              <th className="py-1 pr-2 text-right">COST</th>
              <th className="py-1 pr-2 text-right">LAST</th>
              <th className="py-1 pr-2 text-right">MKT</th>
              <th className="py-1 text-right">P/L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol} className="border-t border-terminal-border/60">
                <td className="py-1 pr-2 font-bold text-terminal-amber">{r.symbol}</td>
                <td className="py-1 pr-2 text-right">{r.qty}</td>
                <td className="py-1 pr-2 text-right">{fmt(r.cost)}</td>
                <td className="py-1 pr-2 text-right">{fmt(r.price)}</td>
                <td className="py-1 pr-2 text-right">{fmt(r.market)}</td>
                <td
                  className={clsx(
                    "py-1 text-right",
                    r.pnl >= 0 ? "text-terminal-green" : "text-terminal-red"
                  )}
                >
                  {r.pnl >= 0 ? "+" : ""}
                  {fmt(r.pnl)} ({r.pnl >= 0 ? "+" : ""}
                  {fmt(r.pnlPct)}%)
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
