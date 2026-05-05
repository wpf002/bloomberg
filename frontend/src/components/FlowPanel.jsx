import { useMemo, useState } from "react";
import clsx from "clsx";
import {
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const SECTORS = [
  "Technology",
  "Communication Services",
  "Consumer Discretionary",
  "Consumer Staples",
  "Financials",
  "Health Care",
  "Energy",
  "Industrials",
  "Materials",
  "Real Estate",
  "Utilities",
];

const PREMIUM_PRESETS = [50_000, 100_000, 250_000, 500_000, 1_000_000];

function formatNumber(value, digits = 0) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatNotional(n) {
  if (n == null) return "--";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${formatNumber(n)}`;
}

function formatTime(ts) {
  if (!ts) return "--";
  try {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(ts).slice(11, 19);
  }
}

export default function FlowPanel({ symbol }) {
  const { t } = useTranslation();
  const [side, setSide] = useState("all");
  const [minPremium, setMinPremium] = useState(100_000);
  const [expiry, setExpiry] = useState("all");
  const [sector, setSector] = useState("");

  const filterParams = useMemo(
    () => ({ symbol: symbol || undefined, side, minPremium, expiry, sector: sector || undefined }),
    [symbol, side, minPremium, expiry, sector]
  );

  const flowQ = usePolling(() => api.flowOptions(filterParams), 60_000, [
    symbol,
    side,
    minPremium,
    expiry,
    sector,
  ]);
  const heatmapQ = usePolling(() => api.flowHeatmap({ side, minPremium }), 60_000, [side, minPremium]);

  // Dark-pool / sweeps / unusual aren't on our data tier — the panel
  // shows a static tier note instead of polling those endpoints.
  // Only the live tape + heatmap can need a configurable API key.
  const needsKey = flowQ.data?.needs_key && heatmapQ.data?.needs_key;

  const sources =
    flowQ.data?.sources_configured?.join(", ") ||
    heatmapQ.data?.sources_configured?.join(", ") ||
    "";

  return (
    <Panel
      title={t("p.flow.title")}
      accent="amber"
      actions={
        <div className="flex flex-wrap items-center gap-2 text-[10px] tabular">
          <SideToggle value={side} onChange={setSide} t={t} />
          <PremiumSlider value={minPremium} onChange={setMinPremium} t={t} />
          <select
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            className="bg-transparent border border-terminal-border/60 px-1 py-0.5 text-terminal-text outline-none"
          >
            <option value="all">{t("p.flow.exp.all")}</option>
            <option value="0dte">0DTE</option>
            <option value="weekly">{t("p.flow.exp.weekly")}</option>
            <option value="monthly">{t("p.flow.exp.monthly")}</option>
            <option value="leaps">LEAPS</option>
          </select>
          <select
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            className="bg-transparent border border-terminal-border/60 px-1 py-0.5 text-terminal-text outline-none max-w-[160px]"
          >
            <option value="">{t("p.flow.sector.all")}</option>
            {SECTORS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {sources ? (
            <span className="text-terminal-muted">{sources}</span>
          ) : null}
        </div>
      }
    >
      {needsKey ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          <p className="mb-2 text-terminal-amber">{t("p.flow.needs_key_head")}</p>
          <p>{t("p.flow.needs_key_msg")}</p>
        </div>
      ) : (
        <div className="space-y-4">
          <Section title={t("p.flow.sec.tape")}>
            <FlowChart items={flowQ.data?.items || []} loading={flowQ.loading && !flowQ.data} t={t} />
          </Section>
          <Section title={t("p.flow.sec.heatmap")}>
            <Heatmap buckets={heatmapQ.data?.buckets || []} loading={heatmapQ.loading && !heatmapQ.data} t={t} />
          </Section>
        </div>
      )}
    </Panel>
  );
}

function SideToggle({ value, onChange, t }) {
  const opts = [
    ["all", t("p.flow.side.all")],
    ["bullish", t("p.flow.side.bull")],
    ["bearish", t("p.flow.side.bear")],
  ];
  return (
    <div className="flex border border-terminal-border/60">
      {opts.map(([k, label]) => (
        <button
          key={k}
          onClick={() => onChange(k)}
          className={clsx(
            "px-1.5 py-0.5 uppercase tracking-wider",
            value === k
              ? k === "bullish"
                ? "bg-terminal-green text-black"
                : k === "bearish"
                ? "bg-terminal-red text-black"
                : "bg-terminal-amber text-black"
              : "text-terminal-muted hover:text-terminal-text"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function PremiumSlider({ value, onChange, t }) {
  return (
    <div className="flex items-center gap-1">
      <span className="uppercase tracking-wider text-terminal-muted">{t("p.flow.min_prem")}</span>
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="bg-transparent border border-terminal-border/60 px-1 py-0.5 text-terminal-text outline-none"
      >
        {PREMIUM_PRESETS.map((p) => (
          <option key={p} value={p}>
            {formatNotional(p)}
          </option>
        ))}
      </select>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section>
      <h3 className="mb-1 text-[10px] uppercase tracking-wider text-terminal-amber">
        {title}
      </h3>
      {children}
    </section>
  );
}

function FlowChart({ items, loading, t }) {
  if (loading) return <div className="text-terminal-muted text-xs">{t("p.common.loading")}</div>;
  if (!items.length) return <div className="text-terminal-muted text-xs">{t("p.flow.none")}</div>;
  // Top 100 by premium keeps the scatter legible without losing the
  // institutional-size tail. Each contract is one bubble; bubble area
  // scales with traded contracts, color encodes side.
  const data = items
    .slice(0, 100)
    .filter((r) => r.strike != null && r.premium != null)
    .map((r) => ({
      ...r,
      strike: Number(r.strike),
      premium: Number(r.premium),
      size: Number(r.size || 0),
    }));
  if (!data.length) return <div className="text-terminal-muted text-xs">{t("p.flow.none")}</div>;
  return (
    <div style={{ width: "100%", height: 320 }}>
      <ResponsiveContainer>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 24, left: 8 }}>
          <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" />
          <XAxis
            type="number"
            dataKey="strike"
            stroke="#8a8f98"
            fontSize={10}
            domain={["dataMin", "dataMax"]}
            label={{
              value: t("p.flow.cols.strike"),
              position: "insideBottom",
              offset: -8,
              fontSize: 10,
              fill: "#8a8f98",
            }}
          />
          <YAxis
            type="number"
            dataKey="premium"
            stroke="#8a8f98"
            fontSize={10}
            tickFormatter={(v) => formatNotional(v)}
            width={60}
          />
          <ZAxis type="number" dataKey="size" range={[40, 600]} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} content={<FlowTooltip t={t} />} />
          <Scatter data={data} isAnimationActive={false}>
            {data.map((row, idx) => (
              <Cell
                key={idx}
                fill={
                  row.side === "bullish"
                    ? "#00d26a"
                    : row.side === "bearish"
                    ? "#ff4d4d"
                    : "#facc15"
                }
                fillOpacity={0.7}
                stroke={
                  row.side === "bullish"
                    ? "#00d26a"
                    : row.side === "bearish"
                    ? "#ff4d4d"
                    : "#facc15"
                }
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function FlowTooltip({ active, payload, t }) {
  if (!active || !payload || !payload.length) return null;
  const r = payload[0].payload;
  return (
    <div className="border border-terminal-border/60 bg-terminal-bg px-2 py-1.5 text-[11px]">
      <div className="font-bold text-terminal-amber">
        {r.symbol} {String(r.type || "").toUpperCase()} {r.strike}
      </div>
      <div className="text-terminal-muted">
        {t("p.flow.cols.exp")} {r.expiry || "--"}
      </div>
      <div
        className={clsx(
          "font-bold uppercase",
          r.side === "bullish" && "text-terminal-green",
          r.side === "bearish" && "text-terminal-red"
        )}
      >
        {r.side}
      </div>
      <div>
        {t("p.flow.cols.prem")} {formatNotional(r.premium)}
      </div>
      <div>
        {t("p.flow.cols.size")} {formatNumber(r.size)}
      </div>
      <div className="text-terminal-muted">{formatTime(r.timestamp)}</div>
    </div>
  );
}

function Heatmap({ buckets, loading, t }) {
  if (loading) return <div className="text-terminal-muted text-xs">{t("p.common.loading")}</div>;
  if (!buckets.length) return <div className="text-terminal-muted text-xs">{t("p.flow.none")}</div>;
  const max = Math.max(...buckets.map((b) => Math.max(b.bullish_premium, b.bearish_premium)), 1);
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-1 text-xs tabular">
      {buckets.map((b) => {
        const tint =
          b.net_premium >= 0
            ? `rgba(0, 210, 106, ${Math.min(0.6, Math.abs(b.net_premium) / max * 0.6 + 0.05)})`
            : `rgba(255, 77, 77, ${Math.min(0.6, Math.abs(b.net_premium) / max * 0.6 + 0.05)})`;
        return (
          <div
            key={b.sector}
            className="border border-terminal-border/60 px-2 py-1"
            style={{ backgroundColor: tint }}
          >
            <div className="text-[10px] uppercase tracking-wider text-terminal-text/90">
              {b.sector}
            </div>
            <div className="text-terminal-text">
              {formatNotional(b.net_premium)}
            </div>
            <div className="text-[10px] text-terminal-muted">
              {t("p.flow.heatmap.dom", { pct: Math.round(b.bullish_dominance * 100) })}{" "}
              · {b.trade_count}
            </div>
          </div>
        );
      })}
    </div>
  );
}

