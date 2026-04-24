import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

const DEFAULTS = ["DGS10", "FEDFUNDS", "CPIAUCSL", "UNRATE", "VIXCLS"];

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
      .macroSeriesData(active, 180)
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

  const points = (data?.observations || []).map((p) => ({
    t: new Date(p.date).getTime(),
    value: p.value,
  }));

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
          <div className="mb-2">
            <div className="text-xs text-terminal-muted uppercase tracking-wider">
              {data?.series_id}
            </div>
            <div className="text-sm text-terminal-text">{data?.title}</div>
            <div className="text-xs text-terminal-muted">
              {data?.units} {data?.frequency ? `· ${data.frequency}` : ""}
            </div>
          </div>
          <div className="flex-1 min-h-0">
            {points.length === 0 ? (
              <div className="text-terminal-muted text-xs">
                No observations. Set <code>FRED_API_KEY</code> in .env.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points}>
                  <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" />
                  <XAxis
                    dataKey="t"
                    tickFormatter={(v) =>
                      new Date(v).toLocaleDateString(undefined, {
                        month: "short",
                        year: "2-digit",
                      })
                    }
                    stroke="#8a8f98"
                    fontSize={10}
                    minTickGap={32}
                  />
                  <YAxis
                    stroke="#8a8f98"
                    fontSize={10}
                    width={48}
                    domain={["auto", "auto"]}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#111418",
                      border: "1px solid #1f242c",
                      fontSize: 11,
                      fontFamily: "JetBrains Mono, monospace",
                    }}
                    labelFormatter={(v) => new Date(v).toLocaleDateString()}
                    formatter={(value) => [Number(value).toFixed(4), active]}
                  />
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke="#00d26a"
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
