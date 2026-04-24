import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

const DEFAULTS = ["DGS10", "FEDFUNDS", "CPIAUCSL", "UNRATE", "VIXCLS"];

const PERCENT_SERIES = new Set([
  "DGS10",
  "DGS2",
  "FEDFUNDS",
  "UNRATE",
  "T10Y2Y",
]);

// Per-series fetch length. Daily series get ~2y of trading days; monthly get
// ~5y; quarterly get ~15y. Without this, monthly/quarterly series tail() far
// too many points and the chart visually flattens into a near-straight line.
const SERIES_LIMIT = {
  DGS10: 504,
  DGS2: 504,
  T10Y2Y: 504,
  VIXCLS: 504,
  DCOILWTICO: 504,
  FEDFUNDS: 60,
  CPIAUCSL: 60,
  UNRATE: 60,
  GDP: 60,
};

function formatValue(value, seriesId) {
  if (value == null || Number.isNaN(value)) return "--";
  const num = Number(value);
  if (PERCENT_SERIES.has(seriesId)) return `${num.toFixed(2)}%`;
  if (Math.abs(num) >= 1000) {
    return num.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
  return num.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatTick(value, seriesId) {
  if (value == null) return "";
  if (PERCENT_SERIES.has(seriesId)) return `${Number(value).toFixed(1)}%`;
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return Number(value).toFixed(abs < 10 ? 2 : 0);
}

function formatDateTick(ts, range) {
  const d = new Date(ts);
  if (range > 5 * 365 * 24 * 3600 * 1000) {
    return d.toLocaleDateString(undefined, { year: "numeric" });
  }
  return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

export default function MacroPanel() {
  const [series, setSeries] = useState(DEFAULTS);
  const [active, setActive] = useState(DEFAULTS[0]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .macroSeries()
      .then((ids) => {
        if (Array.isArray(ids) && ids.length) setSeries(ids);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .macroSeriesData(active, SERIES_LIMIT[active] ?? 240)
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setError(null);
        }
      })
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [active]);

  const points = useMemo(
    () =>
      (data?.observations || []).map((p) => ({
        t: new Date(p.date).getTime(),
        value: p.value,
      })),
    [data]
  );

  const summary = useMemo(() => {
    if (!points.length) return null;
    const first = points[0];
    const last = points[points.length - 1];
    const min = points.reduce((m, p) => (p.value < m.value ? p : m), last);
    const max = points.reduce((m, p) => (p.value > m.value ? p : m), last);
    const change = last.value - first.value;
    const changePct = first.value !== 0 ? (change / Math.abs(first.value)) * 100 : null;
    const range = last.t - first.t;
    return { first, last, min, max, change, changePct, range };
  }, [points]);

  const changeTone =
    summary == null
      ? "text-terminal-muted"
      : summary.change >= 0
        ? "text-terminal-green"
        : "text-terminal-red";

  return (
    <Panel
      title="Macro"
      accent="green"
      actions={
        <select
          value={active}
          onChange={(e) => setActive(e.target.value)}
          className="bg-terminal-panelAlt text-terminal-text text-xs border border-terminal-border px-1 py-0.5"
        >
          {series.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
      }
    >
      {loading && !data ? (
        <div className="text-terminal-muted">Loading series…</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (
        <div className="flex h-full flex-col">
          <div className="mb-2 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-widest text-terminal-muted">
                {data?.series_id}
              </div>
              <div className="truncate text-xs text-terminal-text" title={data?.title}>
                {data?.title}
              </div>
              <div className="text-[10px] text-terminal-muted">
                {data?.units}
                {data?.frequency ? ` · ${data.frequency}` : ""}
              </div>
            </div>
            {summary ? (
              <div className="shrink-0 text-right tabular">
                <div className="text-lg font-bold leading-tight text-terminal-text">
                  {formatValue(summary.last.value, active)}
                </div>
                <div className={clsx("text-[11px] leading-tight", changeTone)}>
                  {summary.change >= 0 ? "+" : ""}
                  {formatValue(summary.change, active)}
                  {summary.changePct != null
                    ? ` (${summary.change >= 0 ? "+" : ""}${summary.changePct.toFixed(2)}%)`
                    : ""}
                </div>
                <div className="text-[10px] text-terminal-muted">
                  as of {new Date(summary.last.t).toLocaleDateString()}
                </div>
              </div>
            ) : null}
          </div>

          <div className="flex-1 min-h-0">
            {points.length === 0 ? (
              <div className="text-terminal-muted text-xs">
                No observations. Set <code>FRED_API_KEY</code> in .env.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={points}
                  margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="macroFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00d26a" stopOpacity={0.45} />
                      <stop offset="100%" stopColor="#00d26a" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" vertical={false} />
                  <XAxis
                    dataKey="t"
                    type="number"
                    scale="time"
                    domain={["dataMin", "dataMax"]}
                    tickFormatter={(v) => formatDateTick(v, summary?.range ?? 0)}
                    stroke="#5a606a"
                    fontSize={10}
                    minTickGap={40}
                    tickLine={false}
                    axisLine={{ stroke: "#1f242c" }}
                  />
                  <YAxis
                    orientation="left"
                    stroke="#5a606a"
                    fontSize={10}
                    width={52}
                    tickFormatter={(v) => formatTick(v, active)}
                    domain={["auto", "auto"]}
                    tickLine={false}
                    axisLine={{ stroke: "#1f242c" }}
                  />
                  {summary ? (
                    <ReferenceLine
                      y={summary.last.value}
                      stroke="#00d26a"
                      strokeDasharray="2 3"
                      strokeOpacity={0.45}
                    />
                  ) : null}
                  <Tooltip
                    contentStyle={{
                      background: "#0b0d10",
                      border: "1px solid #1f242c",
                      fontSize: 11,
                      fontFamily: "JetBrains Mono, monospace",
                      padding: "6px 8px",
                    }}
                    labelStyle={{ color: "#8a8f98" }}
                    itemStyle={{ color: "#00d26a" }}
                    labelFormatter={(v) => new Date(v).toLocaleDateString()}
                    formatter={(value) => [formatValue(value, active), active]}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="#00d26a"
                    strokeWidth={1.75}
                    fill="url(#macroFill)"
                    dot={false}
                    activeDot={{ r: 3, fill: "#00d26a", stroke: "#0b0d10", strokeWidth: 1 }}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
