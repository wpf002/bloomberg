import { useEffect, useMemo, useState } from "react";
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
import clsx from "clsx";
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

const STRAT_KEYS = ["long_call", "long_put", "covered_call", "bull_call", "iron_condor", "straddle"];

const STRATEGY_BUILDERS = {
  long_call: (px) => [
    { type: "call", side: "long", strike: round(px), premium: 2.5, qty: 1 },
  ],
  long_put: (px) => [
    { type: "put", side: "long", strike: round(px), premium: 2.5, qty: 1 },
  ],
  covered_call: (px) => [
    { type: "stock", side: "long", strike: 0, premium: round(px), qty: 100 },
    { type: "call", side: "short", strike: round(px * 1.05), premium: 1.5, qty: 1 },
  ],
  bull_call: (px) => [
    { type: "call", side: "long", strike: round(px), premium: 3.0, qty: 1 },
    { type: "call", side: "short", strike: round(px * 1.05), premium: 1.2, qty: 1 },
  ],
  iron_condor: (px) => [
    { type: "put", side: "long", strike: round(px * 0.9), premium: 0.8, qty: 1 },
    { type: "put", side: "short", strike: round(px * 0.95), premium: 1.6, qty: 1 },
    { type: "call", side: "short", strike: round(px * 1.05), premium: 1.6, qty: 1 },
    { type: "call", side: "long", strike: round(px * 1.1), premium: 0.8, qty: 1 },
  ],
  straddle: (px) => [
    { type: "call", side: "long", strike: round(px), premium: 2.5, qty: 1 },
    { type: "put", side: "long", strike: round(px), premium: 2.5, qty: 1 },
  ],
};

function round(n) {
  return Math.round(n);
}

const SIDES = ["long", "short"];
const TYPES = ["call", "put", "stock"];

export default function PayoffPanel({ symbol }) {
  const { t } = useTranslation();
  const [legs, setLegs] = useState([]);
  const [underlying, setUnderlying] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [strategyKey, setStrategyKey] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setData(null);
    api
      .quote(symbol)
      .then((q) => {
        if (cancelled || !q) return;
        setUnderlying(String(round(q.price)));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const applyStrategy = (key) => {
    const px = Number(underlying) || 100;
    const builder = STRATEGY_BUILDERS[key];
    if (!builder) return;
    setLegs(builder(px));
    setStrategyKey(key);
  };

  const updateLeg = (i, patch) =>
    setLegs((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));

  const removeLeg = (i) => setLegs((prev) => prev.filter((_, idx) => idx !== i));
  const addLeg = () =>
    setLegs((prev) => [
      ...prev,
      {
        type: "call",
        side: "long",
        strike: Number(underlying) || 100,
        premium: 1.0,
        qty: 1,
      },
    ]);

  const compute = async () => {
    if (!symbol || legs.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.optionsPayoff({
        symbol,
        legs: legs.map((l) => ({
          ...l,
          strike: Number(l.strike) || 0,
          premium: Number(l.premium) || 0,
          qty: Number(l.qty) || 1,
        })),
        underlying_price: underlying ? Number(underlying) : null,
        contract_multiplier: 100,
        points: 121,
      });
      setData(result);
    } catch (err) {
      setError(err?.detail || err?.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  const chartData = useMemo(() => {
    return (data?.points ?? []).map((p) => ({ spot: p.spot, pnl: p.pnl }));
  }, [data]);

  const stratLabel = strategyKey ? t(`p.payoff.strats.${strategyKey}`) : "";
  const title = stratLabel
    ? t("p.payoff.title_with_strat", { sym: symbol ?? "—", strat: stratLabel })
    : t("p.payoff.title", { sym: symbol ?? "—" });

  return (
    <Panel
      title={title}
      accent="amber"
      actions={
        data ? (
          <span className="tabular text-terminal-muted">
            {t("p.payoff.spot").toLowerCase()} {fmt(data.underlying_price)} · net{" "}
            <span
              className={
                data.net_premium >= 0 ? "text-terminal-green" : "text-terminal-red"
              }
            >
              {data.net_premium >= 0 ? t("p.payoff.net_credit") : t("p.payoff.net_debit")}{" "}
              {fmt(Math.abs(data.net_premium))}
            </span>
          </span>
        ) : null
      }
    >
      <div className="mb-2 flex flex-wrap gap-1 text-xs">
        {STRAT_KEYS.map((key) => (
          <button
            key={key}
            onClick={() => applyStrategy(key)}
            className={clsx(
              "border px-2 py-0.5",
              strategyKey === key
                ? "border-terminal-amber bg-terminal-amber/10 text-terminal-amber"
                : "border-terminal-border/60 text-terminal-muted hover:border-terminal-amber hover:text-terminal-amber"
            )}
          >
            {t(`p.payoff.strats.${key}`)}
          </button>
        ))}
      </div>

      <div className="mb-2 flex items-center gap-2 text-xs">
        <label className="flex items-center gap-1">
          <span className="text-terminal-muted">{t("p.payoff.spot")}</span>
          <input
            type="number"
            step="0.01"
            value={underlying}
            onChange={(e) => setUnderlying(e.target.value)}
            className="w-24 border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
          />
        </label>
        <button
          onClick={addLeg}
          className="border border-terminal-border px-2 py-0.5 text-terminal-muted hover:border-terminal-amber hover:text-terminal-amber"
        >
          {t("p.payoff.add_leg")}
        </button>
        <button
          onClick={compute}
          disabled={loading || legs.length === 0}
          className="border border-terminal-amber px-2 py-0.5 text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
        >
          {loading ? t("p.common.computing") : t("p.payoff.plot")}
        </button>
      </div>

      {legs.length > 0 && (
        <table className="mb-3 w-full text-xs tabular">
          <thead>
            <tr className="text-left text-terminal-muted">
              <th className="py-1 pr-2">{t("p.payoff.cols.side")}</th>
              <th className="py-1 pr-2">{t("p.payoff.cols.type")}</th>
              <th className="py-1 pr-2 text-right">{t("p.payoff.cols.strike")}</th>
              <th className="py-1 pr-2 text-right">{t("p.payoff.cols.premium")}</th>
              <th className="py-1 pr-2 text-right">{t("p.payoff.cols.qty")}</th>
              <th className="py-1"></th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, i) => (
              <tr key={i} className="border-t border-terminal-border/60">
                <td className="py-1 pr-2">
                  <select
                    value={leg.side}
                    onChange={(e) => updateLeg(i, { side: e.target.value })}
                    className="border border-terminal-border bg-terminal-bg px-1 text-terminal-text focus:outline-none focus:border-terminal-amber"
                  >
                    {SIDES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="py-1 pr-2">
                  <select
                    value={leg.type}
                    onChange={(e) => updateLeg(i, { type: e.target.value })}
                    className="border border-terminal-border bg-terminal-bg px-1 text-terminal-text focus:outline-none focus:border-terminal-amber"
                  >
                    {TYPES.map((t2) => (
                      <option key={t2} value={t2}>
                        {t2}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="py-1 pr-2 text-right">
                  <input
                    type="number"
                    step="0.5"
                    value={leg.strike}
                    onChange={(e) => updateLeg(i, { strike: Number(e.target.value) })}
                    className="w-16 border border-terminal-border bg-terminal-bg px-1 text-right tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                  />
                </td>
                <td className="py-1 pr-2 text-right">
                  <input
                    type="number"
                    step="0.05"
                    value={leg.premium}
                    onChange={(e) => updateLeg(i, { premium: Number(e.target.value) })}
                    className="w-16 border border-terminal-border bg-terminal-bg px-1 text-right tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                  />
                </td>
                <td className="py-1 pr-2 text-right">
                  <input
                    type="number"
                    step="1"
                    value={leg.qty}
                    onChange={(e) => updateLeg(i, { qty: Number(e.target.value) })}
                    className="w-14 border border-terminal-border bg-terminal-bg px-1 text-right tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                  />
                </td>
                <td className="py-1 text-right">
                  <button
                    onClick={() => removeLeg(i)}
                    className="text-terminal-red hover:underline"
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {error && <div className="mb-2 text-xs text-terminal-red">{error}</div>}

      {data && chartData.length > 0 && (
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
              <XAxis dataKey="spot" tick={{ fontSize: 10 }} stroke="#6b7280" />
              <YAxis tick={{ fontSize: 10 }} stroke="#6b7280" />
              <Tooltip
                contentStyle={{
                  background: "#0c0e15",
                  border: "1px solid #1f2937",
                  fontSize: 11,
                }}
                formatter={(v) => fmt(v)}
                labelFormatter={(v) => `spot ${fmt(v)}`}
              />
              <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="2 2" />
              <ReferenceLine
                x={data.underlying_price}
                stroke="#ff9f1c"
                strokeDasharray="2 2"
                label={{ value: "spot", fill: "#ff9f1c", fontSize: 10 }}
              />
              {(data.breakevens || []).map((be) => (
                <ReferenceLine
                  key={be}
                  x={be}
                  stroke="#3b82f6"
                  strokeDasharray="3 3"
                  label={{ value: `BE ${fmt(be)}`, fill: "#3b82f6", fontSize: 10 }}
                />
              ))}
              <Line
                type="monotone"
                dataKey="pnl"
                stroke="#10b981"
                strokeWidth={1.5}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {data && (
        <div className="mt-2 grid grid-cols-3 gap-2 text-xs tabular">
          <Stat
            label={t("p.payoff.max_profit")}
            value={data.max_profit == null ? t("p.payoff.unbounded") : `$${fmt(data.max_profit)}`}
            color={data.max_profit == null ? "amber" : "green"}
          />
          <Stat
            label={t("p.payoff.max_loss")}
            value={data.max_loss == null ? t("p.payoff.unbounded") : `$${fmt(data.max_loss)}`}
            color={data.max_loss == null ? "amber" : "red"}
          />
          <Stat
            label={t("p.payoff.breakevens")}
            value={
              data.breakevens?.length
                ? data.breakevens.map((b) => fmt(b)).join(" / ")
                : "—"
            }
            color="blue"
          />
        </div>
      )}

      {!data && legs.length === 0 && (
        <div className="text-xs text-terminal-muted">{t("p.payoff.hint")}</div>
      )}
    </Panel>
  );
}

function Stat({ label, value, color = "amber" }) {
  const cls =
    color === "green"
      ? "text-terminal-green"
      : color === "red"
      ? "text-terminal-red"
      : color === "blue"
      ? "text-terminal-blue"
      : "text-terminal-amber";
  return (
    <div className="rounded border border-terminal-border/60 px-2 py-1">
      <div className="text-[10px] uppercase tracking-wider text-terminal-muted">
        {label}
      </div>
      <div className={cls}>{value}</div>
    </div>
  );
}
