import { useState } from "react";
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

export default function SizingPanel({ symbol }) {
  const [stopPct, setStopPct] = useState(5);
  const { data, error, loading } = usePolling(
    () => (symbol ? api.sizing(symbol, stopPct) : Promise.resolve(null)),
    20_000,
    [symbol, stopPct]
  );

  const credsMissing = error?.status === 503;

  return (
    <Panel
      title={`Sizing — ${symbol ?? "—"}`}
      accent="amber"
      actions={
        data ? (
          <span className="tabular text-terminal-muted">
            PX {fmt(data.price)} · EQUITY {fmt(data.equity)}
          </span>
        ) : null
      }
    >
      <div className="mb-3 flex items-baseline gap-3 text-xs">
        <label className="flex items-center gap-2">
          <span className="text-terminal-muted">Stop %</span>
          <input
            type="number"
            min="0.5"
            max="50"
            step="0.5"
            value={stopPct}
            onChange={(e) => setStopPct(Math.max(0.5, Math.min(50, Number(e.target.value) || 0)))}
            className="w-16 border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
          />
        </label>
        <span className="text-[10px] uppercase tracking-wider text-terminal-muted">
          distance from entry you'd exit a losing trade
        </span>
      </div>
      {credsMissing ? (
        <div className="text-xs text-terminal-muted">
          Sizing needs live equity — connect Alpaca in{" "}
          <code className="text-terminal-green">.env</code> first (see Portfolio panel).
        </div>
      ) : loading && !data ? (
        <div className="text-terminal-muted">Loading…</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.detail || error.message || error)}</div>
      ) : data ? (
        <table className="w-full text-xs tabular">
          <thead>
            <tr className="text-left text-terminal-muted">
              <th className="py-1 pr-2">RISK</th>
              <th className="py-1 pr-2 text-right">MAX $ LOSS</th>
              <th className="py-1 pr-2 text-right">SHARES</th>
              <th className="py-1 pr-2 text-right">NOTIONAL $</th>
              <th className="py-1 text-right">% OF EQUITY</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.risk_pct} className="border-t border-terminal-border/60">
                <td className="py-1 pr-2 font-bold text-terminal-amber">
                  {fmt(r.risk_pct, 1)}%
                </td>
                <td className="py-1 pr-2 text-right">{fmt(r.max_loss_usd)}</td>
                <td className="py-1 pr-2 text-right">{r.shares.toLocaleString()}</td>
                <td className="py-1 pr-2 text-right">{fmt(r.notional_usd)}</td>
                <td
                  className={clsx(
                    "py-1 text-right",
                    r.notional_pct > 100 ? "text-terminal-red" : "text-terminal-text"
                  )}
                >
                  {fmt(r.notional_pct, 1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="text-terminal-muted">Enter a symbol.</div>
      )}
      {data && (
        <p className="mt-2 text-[10px] leading-relaxed text-terminal-muted/80">
          Rule: <span className="text-terminal-text">shares = (equity × risk%) ÷ (price × stop%)</span>.
          Rows where notional exceeds equity mean the stop is tight enough that
          the full position would require margin.
        </p>
      )}
    </Panel>
  );
}
