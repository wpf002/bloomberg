import { useMemo, useState } from "react";
import clsx from "clsx";
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
  const dpQ = usePolling(
    () => api.flowDarkPool({ symbol: symbol || undefined, minPremium }),
    60_000,
    [symbol, minPremium]
  );
  const sweepsQ = usePolling(() => api.flowSweeps(filterParams), 60_000, [
    symbol,
    side,
    minPremium,
    sector,
  ]);

  const needsKey =
    flowQ.data?.needs_key &&
    heatmapQ.data?.needs_key &&
    dpQ.data?.needs_key &&
    sweepsQ.data?.needs_key;

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
          <Section title={t("p.flow.sec.sweeps")}>
            <FlowTable items={sweepsQ.data?.items || []} loading={sweepsQ.loading && !sweepsQ.data} sweepStyle t={t} />
          </Section>
          <Section title={t("p.flow.sec.tape")}>
            <FlowTable items={flowQ.data?.items || []} loading={flowQ.loading && !flowQ.data} t={t} />
          </Section>
          <Section title={t("p.flow.sec.heatmap")}>
            <Heatmap buckets={heatmapQ.data?.buckets || []} loading={heatmapQ.loading && !heatmapQ.data} t={t} />
          </Section>
          <Section title={t("p.flow.sec.darkpool")}>
            <DarkPoolTable items={dpQ.data?.items || []} loading={dpQ.loading && !dpQ.data} t={t} />
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

function FlowTable({ items, loading, sweepStyle, t }) {
  if (loading) return <div className="text-terminal-muted text-xs">{t("p.common.loading")}</div>;
  if (!items.length) return <div className="text-terminal-muted text-xs">{t("p.flow.none")}</div>;
  return (
    <div className="-mx-3 overflow-x-auto px-3">
      <table className="w-full min-w-[640px] text-xs tabular">
        <thead>
          <tr className="text-left text-terminal-muted">
            <th className="py-1 pr-2">{t("p.flow.cols.time")}</th>
            <th className="py-1 pr-2">{t("p.flow.cols.sym")}</th>
            <th className="py-1 pr-2">{t("p.flow.cols.type")}</th>
            <th className="py-1 pr-2 text-right">{t("p.flow.cols.strike")}</th>
            <th className="py-1 pr-2">{t("p.flow.cols.exp")}</th>
            <th className="py-1 pr-2 text-right">{t("p.flow.cols.size")}</th>
            <th className="py-1 pr-2 text-right">{t("p.flow.cols.prem")}</th>
            <th className="py-1 pr-2">{t("p.flow.cols.side")}</th>
            <th className="py-1 pr-2">{t("p.flow.cols.tag")}</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, sweepStyle ? 20 : 50).map((row, idx) => (
            <tr
              key={`${row.timestamp}-${row.symbol}-${idx}`}
              className={clsx(
                "border-t border-terminal-border/60",
                sweepStyle && "bg-terminal-amber/5"
              )}
            >
              <td className="py-1 pr-2 text-terminal-muted whitespace-nowrap">{formatTime(row.timestamp)}</td>
              <td className="py-1 pr-2 font-bold text-terminal-amber whitespace-nowrap">{row.symbol}</td>
              <td className="py-1 pr-2 uppercase whitespace-nowrap">{row.type || "--"}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{row.strike ?? "--"}</td>
              <td className="py-1 pr-2 whitespace-nowrap">{row.expiry ?? "--"}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{formatNumber(row.size)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{formatNotional(row.premium)}</td>
              <td
                className={clsx(
                  "py-1 pr-2 whitespace-nowrap font-bold uppercase",
                  row.side === "bullish" && "text-terminal-green",
                  row.side === "bearish" && "text-terminal-red"
                )}
              >
                {row.side}
              </td>
              <td className="py-1 pr-2 text-terminal-muted whitespace-nowrap">{row.sentiment || row.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
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

function DarkPoolTable({ items, loading, t }) {
  if (loading) return <div className="text-terminal-muted text-xs">{t("p.common.loading")}</div>;
  if (!items.length) return <div className="text-terminal-muted text-xs">{t("p.flow.none")}</div>;
  return (
    <div className="-mx-3 overflow-x-auto px-3">
      <table className="w-full min-w-[480px] text-xs tabular">
        <thead>
          <tr className="text-left text-terminal-muted">
            <th className="py-1 pr-2">{t("p.flow.cols.time")}</th>
            <th className="py-1 pr-2">{t("p.flow.cols.sym")}</th>
            <th className="py-1 pr-2 text-right">{t("p.flow.cols.price")}</th>
            <th className="py-1 pr-2 text-right">{t("p.flow.cols.size")}</th>
            <th className="py-1 pr-2 text-right">{t("p.flow.cols.notional")}</th>
            <th className="py-1 pr-2">{t("p.flow.cols.venue")}</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, 50).map((r, idx) => (
            <tr key={`${r.timestamp}-${r.symbol}-${idx}`} className="border-t border-terminal-border/60">
              <td className="py-1 pr-2 text-terminal-muted whitespace-nowrap">{formatTime(r.timestamp)}</td>
              <td className="py-1 pr-2 font-bold text-terminal-amber whitespace-nowrap">{r.symbol}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{formatNumber(r.price, 2)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{formatNumber(r.size)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{formatNotional(r.notional)}</td>
              <td className="py-1 pr-2 text-terminal-muted whitespace-nowrap">{r.venue || "--"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
