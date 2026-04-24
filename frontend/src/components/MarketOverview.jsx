import clsx from "clsx";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";

function fmt(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export default function MarketOverview({ onSelect }) {
  const { data, error, loading } = usePolling(() => api.overview(), 30_000, []);

  return (
    <Panel title="Markets" accent="amber">
      {loading && !data ? (
        <div className="text-terminal-muted">Loading markets…</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs tabular">
          {(data?.tiles || []).map((t) => {
            const positive = t.change >= 0;
            return (
              <button
                key={t.symbol}
                onClick={() => onSelect?.(t.symbol)}
                className="flex items-baseline justify-between border-b border-terminal-border/40 py-1 text-left hover:bg-terminal-panelAlt"
              >
                <span className="min-w-[72px] text-terminal-amber">{t.label}</span>
                <span className="flex-1 pl-2 text-right">{fmt(t.price)}</span>
                <span
                  className={clsx(
                    "min-w-[64px] pl-2 text-right",
                    positive ? "text-terminal-green" : "text-terminal-red"
                  )}
                >
                  {positive ? "+" : ""}
                  {fmt(t.change_percent)}%
                </span>
              </button>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
