import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

function fmt(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function pct(value) {
  if (value == null || Number.isNaN(value)) return "--";
  return `${(value * 100).toFixed(1)}%`;
}

export default function OptionsPanel({ symbol }) {
  const { t } = useTranslation();
  const [expiration, setExpiration] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .options(symbol, expiration)
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        if (!expiration && payload?.selected_expiration) {
          setExpiration(payload.selected_expiration);
        }
      })
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, expiration]);

  useEffect(() => {
    setExpiration(null);
    setData(null);
  }, [symbol]);

  const smile = useMemo(() => {
    if (!data) return [];
    const calls = (data.calls || []).map((c) => ({ strike: c.strike, call_iv: c.implied_volatility }));
    const puts = (data.puts || []).map((p) => ({ strike: p.strike, put_iv: p.implied_volatility }));
    const byStrike = new Map();
    for (const row of [...calls, ...puts]) {
      const entry = byStrike.get(row.strike) || { strike: row.strike };
      Object.assign(entry, row);
      byStrike.set(row.strike, entry);
    }
    return Array.from(byStrike.values()).sort((a, b) => a.strike - b.strike);
  }, [data]);

  const rows = useMemo(() => {
    if (!data) return [];
    const calls = data.calls || [];
    const puts = data.puts || [];
    const strikes = Array.from(
      new Set([...calls.map((c) => c.strike), ...puts.map((p) => p.strike)])
    ).sort((a, b) => a - b);
    const callByStrike = new Map(calls.map((c) => [c.strike, c]));
    const putByStrike = new Map(puts.map((p) => [p.strike, p]));
    return strikes.map((k) => ({
      strike: k,
      call: callByStrike.get(k) || null,
      put: putByStrike.get(k) || null,
    }));
  }, [data]);

  const spot = data?.underlying_price;

  return (
    <Panel
      title={t("p.options.title", { sym: symbol })}
      accent="blue"
      actions={
        <div className="flex items-center gap-2">
          <span className="text-terminal-muted">{t("p.options.exp")}</span>
          <select
            value={expiration || ""}
            onChange={(e) => setExpiration(e.target.value)}
            className="bg-terminal-panelAlt text-terminal-text text-xs border border-terminal-border px-1 py-0.5"
          >
            {(data?.expirations || []).map((exp) => (
              <option key={exp} value={exp}>
                {exp}
              </option>
            ))}
          </select>
        </div>
      }
    >
      {loading && !data ? (
        <div className="text-terminal-muted">{t("p.options.loading")}</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : !data || (!data.calls.length && !data.puts.length) ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          <p className="mb-1 text-terminal-amber">
            {t("p.options.none_head", { sym: symbol })}
          </p>
          <p>{t("p.options.none_msg")}</p>
        </div>
      ) : (
        <div className="flex h-full flex-col gap-2">
          <div className="flex items-baseline justify-between text-xs">
            <span>
              {t("p.options.spot")} <span className="text-terminal-amber tabular">{fmt(spot)}</span>
            </span>
            <span className="text-terminal-muted">
              {t("p.options.counts", { calls: data.calls.length, puts: data.puts.length })}
            </span>
          </div>

          <div className="h-24 min-h-[96px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={smile}>
                <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" />
                <XAxis
                  dataKey="strike"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  stroke="#8a8f98"
                  fontSize={10}
                />
                <YAxis
                  stroke="#8a8f98"
                  fontSize={10}
                  tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                  width={36}
                />
                <Tooltip
                  contentStyle={{
                    background: "#111418",
                    border: "1px solid #1f242c",
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: 11,
                  }}
                  formatter={(value) => (value != null ? pct(value) : "--")}
                  labelFormatter={(v) => `K=${v}`}
                />
                {spot ? (
                  <ReferenceLine x={spot} stroke="#ff9f1c" strokeDasharray="3 3" />
                ) : null}
                <Line
                  type="monotone"
                  dataKey="call_iv"
                  stroke="#00d26a"
                  dot={false}
                  strokeWidth={1.3}
                  isAnimationActive={false}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="put_iv"
                  stroke="#ff4d4d"
                  dot={false}
                  strokeWidth={1.3}
                  isAnimationActive={false}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="min-h-0 flex-1 overflow-auto border-t border-terminal-border/60">
            <table className="w-full text-[11px] tabular">
              <thead className="sticky top-0 bg-terminal-panel text-terminal-muted">
                <tr>
                  <th className="py-1 text-right" colSpan={4}>{t("p.options.h_calls")}</th>
                  <th className="py-1 text-center">{t("p.options.h_strike")}</th>
                  <th className="py-1 text-left" colSpan={4}>{t("p.options.h_puts")}</th>
                </tr>
                <tr className="text-terminal-muted">
                  <th className="py-1 pr-2 text-right">{t("p.options.h_iv")}</th>
                  <th className="py-1 pr-2 text-right">Δ</th>
                  <th className="py-1 pr-2 text-right">{t("p.options.h_bid")}</th>
                  <th className="py-1 pr-2 text-right">{t("p.options.h_ask")}</th>
                  <th className="py-1 text-center">K</th>
                  <th className="py-1 pl-2 text-left">{t("p.options.h_bid")}</th>
                  <th className="py-1 pl-2 text-left">{t("p.options.h_ask")}</th>
                  <th className="py-1 pl-2 text-left">Δ</th>
                  <th className="py-1 pl-2 text-left">{t("p.options.h_iv")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ strike, call, put }) => {
                  const atm = spot ? Math.abs(strike - spot) < 0.005 * spot : false;
                  return (
                    <tr
                      key={strike}
                      className={clsx(
                        "border-t border-terminal-border/40",
                        atm && "bg-terminal-panelAlt"
                      )}
                    >
                      <td className={clsx("py-0.5 pr-2 text-right", call?.in_the_money && "text-terminal-green")}>
                        {pct(call?.implied_volatility)}
                      </td>
                      <td className="py-0.5 pr-2 text-right">{fmt(call?.delta, 2)}</td>
                      <td className="py-0.5 pr-2 text-right">{fmt(call?.bid)}</td>
                      <td className="py-0.5 pr-2 text-right">{fmt(call?.ask)}</td>
                      <td className="py-0.5 text-center font-bold text-terminal-amber">{fmt(strike)}</td>
                      <td className={clsx("py-0.5 pl-2 text-left", put?.in_the_money && "text-terminal-red")}>
                        {fmt(put?.bid)}
                      </td>
                      <td className="py-0.5 pl-2 text-left">{fmt(put?.ask)}</td>
                      <td className="py-0.5 pl-2 text-left">{fmt(put?.delta, 2)}</td>
                      <td className="py-0.5 pl-2 text-left">{pct(put?.implied_volatility)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Panel>
  );
}
