import clsx from "clsx";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";

function formatNumber(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export default function Watchlist({ symbols, activeSymbol, onSelect }) {
  const { data, error, loading } = usePolling(
    () => api.quotes(symbols),
    15000,
    [symbols.join(",")]
  );

  return (
    <Panel
      title="Watchlist"
      accent="amber"
      actions={<span className="text-terminal-muted">{symbols.length} syms</span>}
    >
      {loading && !data ? (
        <div className="text-terminal-muted">Loading quotes…</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (
        <table className="w-full text-xs tabular">
          <thead>
            <tr className="text-left text-terminal-muted">
              <th className="py-1 pr-2">SYM</th>
              <th className="py-1 pr-2 text-right">LAST</th>
              <th className="py-1 pr-2 text-right">CHG</th>
              <th className="py-1 pr-2 text-right">%</th>
              <th className="py-1 text-right">VOL</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((q) => {
              const positive = q.change >= 0;
              const active = q.symbol === activeSymbol;
              return (
                <tr
                  key={q.symbol}
                  onClick={() => onSelect?.(q.symbol)}
                  className={clsx(
                    "cursor-pointer border-t border-terminal-border/60 hover:bg-terminal-panelAlt",
                    active && "bg-terminal-panelAlt"
                  )}
                >
                  <td className="py-1 pr-2 font-bold text-terminal-amber">{q.symbol}</td>
                  <td className="py-1 pr-2 text-right">{formatNumber(q.price)}</td>
                  <td
                    className={clsx(
                      "py-1 pr-2 text-right",
                      positive ? "text-terminal-green" : "text-terminal-red"
                    )}
                  >
                    {positive ? "+" : ""}
                    {formatNumber(q.change)}
                  </td>
                  <td
                    className={clsx(
                      "py-1 pr-2 text-right",
                      positive ? "text-terminal-green" : "text-terminal-red"
                    )}
                  >
                    {positive ? "+" : ""}
                    {formatNumber(q.change_percent)}%
                  </td>
                  <td className="py-1 text-right text-terminal-muted">
                    {q.volume ? q.volume.toLocaleString() : "--"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
