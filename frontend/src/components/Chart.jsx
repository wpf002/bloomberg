import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";

const PERIODS = [
  ["1D", "1d", "5m"],
  ["5D", "5d", "15m"],
  ["1M", "1mo", "1d"],
  ["6M", "6mo", "1d"],
  ["1Y", "1y", "1d"],
  ["5Y", "5y", "1wk"],
];

export default function Chart({ symbol }) {
  const [selected, setSelected] = useState(PERIODS[2]);
  const [, period, interval] = selected;

  const { data, loading, error } = usePolling(
    () => api.history(symbol, period, interval),
    60_000,
    [symbol, period, interval]
  );

  const series = useMemo(
    () =>
      (data || []).map((p) => ({
        t: new Date(p.timestamp).getTime(),
        close: p.close,
      })),
    [data]
  );

  const first = series[0]?.close;
  const last = series[series.length - 1]?.close;
  const delta = first && last ? last - first : 0;
  const deltaPct = first ? (delta / first) * 100 : 0;
  const positive = delta >= 0;

  return (
    <Panel
      title={`Chart — ${symbol}`}
      accent="blue"
      actions={
        <div className="flex items-center gap-1">
          {PERIODS.map((p) => (
            <button
              key={p[0]}
              onClick={() => setSelected(p)}
              className={`px-2 py-0.5 text-[10px] uppercase tracking-wider ${
                p === selected
                  ? "bg-terminal-amber text-black"
                  : "text-terminal-muted hover:text-terminal-text"
              }`}
            >
              {p[0]}
            </button>
          ))}
        </div>
      }
    >
      {loading && !data ? (
        <div className="text-terminal-muted">Loading history…</div>
      ) : error ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          No chart data available for{" "}
          <span className="text-terminal-amber">{symbol}</span>.
          {error.status === 404 ? (
            <> Pick a different symbol from the watchlist.</>
          ) : null}
        </div>
      ) : (
        <div className="flex h-full flex-col">
          <div className="mb-2 flex items-baseline gap-3 tabular">
            <span className="text-2xl font-bold text-terminal-text">
              {last ? last.toFixed(2) : "--"}
            </span>
            <span
              className={
                positive ? "text-terminal-green" : "text-terminal-red"
              }
            >
              {positive ? "+" : ""}
              {delta.toFixed(2)} ({positive ? "+" : ""}
              {deltaPct.toFixed(2)}%)
            </span>
            <span className="ml-auto text-xs text-terminal-muted">
              {series.length} points · {interval}
            </span>
          </div>
          <div className="flex-1 min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series}>
                <defs>
                  <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="0%"
                      stopColor={positive ? "#00d26a" : "#ff4d4d"}
                      stopOpacity={0.35}
                    />
                    <stop
                      offset="100%"
                      stopColor={positive ? "#00d26a" : "#ff4d4d"}
                      stopOpacity={0}
                    />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" />
                <XAxis
                  dataKey="t"
                  tickFormatter={(v) =>
                    new Date(v).toLocaleDateString(undefined, {
                      month: "short",
                      day: "2-digit",
                    })
                  }
                  stroke="#8a8f98"
                  fontSize={10}
                  minTickGap={32}
                />
                <YAxis
                  domain={["auto", "auto"]}
                  stroke="#8a8f98"
                  fontSize={10}
                  width={48}
                />
                <Tooltip
                  contentStyle={{
                    background: "#111418",
                    border: "1px solid #1f242c",
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: 11,
                  }}
                  labelFormatter={(v) => new Date(v).toLocaleString()}
                  formatter={(value) => [Number(value).toFixed(2), "Close"]}
                />
                <Area
                  type="monotone"
                  dataKey="close"
                  stroke={positive ? "#00d26a" : "#ff4d4d"}
                  strokeWidth={1.5}
                  fill="url(#chartFill)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </Panel>
  );
}
