import { useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const REGIME_COLORS = {
  RISK_ON:               "bg-terminal-green/30 text-terminal-green border-terminal-green",
  RISK_OFF:              "bg-terminal-red/30 text-terminal-red border-terminal-red",
  INFLATIONARY:          "bg-terminal-amber/30 text-terminal-amber border-terminal-amber",
  LIQUIDITY_CONTRACTION: "bg-purple-700/30 text-purple-300 border-purple-500",
  STAGFLATIONARY:        "bg-orange-700/30 text-orange-300 border-orange-500",
  NEUTRAL:               "bg-terminal-muted/20 text-terminal-text border-terminal-border",
};

const STATUS_COLOR = {
  LEADING: "text-terminal-green",
  LAGGING: "text-terminal-red",
  NEUTRAL: "text-terminal-muted",
  INFLOW: "text-terminal-green",
  OUTFLOW: "text-terminal-red",
  FLAT: "text-terminal-muted",
};

function pct(n, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(Number(n) * 100).toFixed(digits)}%`;
}

function fragilityBarColor(score) {
  if (score >= 70) return "bg-terminal-red";
  if (score >= 50) return "bg-terminal-amber";
  return "bg-terminal-green";
}

// Per-tab fetcher map. Each entry: api call + state setter slot.
const TAB_FETCHERS = {
  regime:    (api) => api.intelRegime(),
  fragility: (api) => api.intelFragility(),
  flows:     (api) => api.intelFlows(),
  rotation:  (api) => api.intelRotation(),
  predictions: async (api) => {
    const [macro, markets, events] = await Promise.all([
      api.predictionsMacro().catch(() => ({ items: [] })),
      api.predictionsMarkets().catch(() => ({ items: [] })),
      api.predictionsEvents().catch(() => ({ items: [] })),
    ]);
    return { macro: macro.items || [], markets: markets.items || [], events: events.items || [] };
  },
};

export default function IntelligencePanel() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("regime");
  const [data, setData] = useState({ regime: null, fragility: null, flows: null, rotation: null, predictions: null });
  const [loaded, setLoaded] = useState({ regime: false, fragility: false, flows: false, rotation: false, predictions: false });
  const [loading, setLoading] = useState({});
  const [pendingOrders, setPendingOrders] = useState([]);

  // Fragility tab needs pending orders for the empty-state copy. We only
  // pull them once, lazily, when fragility is first opened.
  const [ordersLoaded, setOrdersLoaded] = useState(false);

  useEffect(() => {
    if (loaded[tab] || loading[tab]) return;
    let cancelled = false;
    setLoading((p) => ({ ...p, [tab]: true }));
    TAB_FETCHERS[tab](api)
      .then((d) => {
        if (cancelled) return;
        setData((p) => ({ ...p, [tab]: d }));
        setLoaded((p) => ({ ...p, [tab]: true }));
      })
      .catch(() => {
        if (cancelled) return;
        setLoaded((p) => ({ ...p, [tab]: true }));
      })
      .finally(() => !cancelled && setLoading((p) => ({ ...p, [tab]: false })));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  useEffect(() => {
    if (tab !== "fragility" || ordersLoaded) return;
    let cancelled = false;
    api
      .orders("open", 50)
      .then((ords) => {
        if (cancelled) return;
        setPendingOrders(
          (ords || []).filter((o) =>
            ["accepted", "new", "pending_new", "partially_filled"].includes(o.status),
          ),
        );
        setOrdersLoaded(true);
      })
      .catch(() => !cancelled && setOrdersLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [tab, ordersLoaded]);

  return (
    <Panel
      title={t("panels.intelligence")}
      accent="amber"
      actions={
        <div className="flex gap-2 text-[10px] uppercase tracking-widest">
          {[
            ["regime", t("p.intel.tabs.regime")],
            ["fragility", t("p.intel.tabs.fragility")],
            ["flows", t("p.intel.tabs.flows")],
            ["rotation", t("p.intel.tabs.rotation")],
            ["predictions", t("p.intel.tabs.predictions")],
          ].map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={tab === k ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
            >
              {label}
            </button>
          ))}
        </div>
      }
    >
      {loading[tab] && !loaded[tab] ? (
        <div className="text-terminal-muted">{t("p.intel.loading")}</div>
      ) : tab === "regime" ? (
        <RegimeTab regime={data.regime} t={t} />
      ) : tab === "fragility" ? (
        <FragilityTab fragility={data.fragility} pendingOrders={pendingOrders} t={t} />
      ) : tab === "flows" ? (
        <FlowsTab flows={data.flows} t={t} />
      ) : tab === "predictions" ? (
        <PredictionsTab predictions={data.predictions} t={t} />
      ) : (
        <RotationTab rotation={data.rotation} t={t} />
      )}
    </Panel>
  );
}

// Pretty labels + display rules for the raw regime indicators. Anything
// not in this map falls through to a humanized version of the snake_case
// key with a 3-decimal float as the value.
const REGIME_INDICATORS = {
  vix:           { label: "VIX",         unit: "",   digits: 2 },
  ten_year:      { label: "10Y Yield",   unit: "%",  digits: 2 },
  dxy:           { label: "DXY",         unit: "",   digits: 2 },
  m2_yoy_pct:    { label: "M2 YoY",      unit: "%",  digits: 2 },
  cpi_mom_pct:   { label: "CPI MoM",     unit: "%",  digits: 2 },
  spy_30d_return:{ label: "SPY 30d",     unit: "%",  digits: 2, asPercent: true },
  spy_return_30d:{ label: "SPY 30d",     unit: "%",  digits: 2, asPercent: true },
  rsi:           { label: "RSI",         unit: "",   digits: 1 },
  curve_2y10y:   { label: "2Y/10Y",      unit: "%",  digits: 2 },
};

function humanizeKey(k) {
  return k
    .replace(/_pct$/, " %")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatIndicator(k, v) {
  if (v == null) return "—";
  const meta = REGIME_INDICATORS[k];
  const num = Number(v);
  if (Number.isNaN(num)) return String(v);
  if (meta) {
    const display = meta.asPercent ? num * 100 : num;
    return `${display.toFixed(meta.digits)}${meta.unit}`;
  }
  return num.toFixed(3);
}

function RegimeTab({ regime, t }) {
  if (!regime) return <div className="text-terminal-muted">{t("p.intel.regime.unavail")}</div>;
  const cls = REGIME_COLORS[regime.regime] || REGIME_COLORS.NEUTRAL;
  const conf = regime.confidence ?? 0;
  return (
    <div className="flex h-full flex-col gap-3">
      {/* Headline badge: regime + confidence bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div
          className={`inline-flex items-center rounded border px-4 py-2 text-lg font-bold uppercase tracking-widest ${cls}`}
        >
          {regime.regime?.replaceAll("_", " ") || "—"}
        </div>
        <div className="flex flex-1 min-w-[140px] flex-col gap-1">
          <div className="flex items-baseline justify-between text-[10px] uppercase tracking-widest text-terminal-muted">
            <span>{t("p.intel.regime.conf")}</span>
            <span className="text-terminal-text tabular">{pct(conf, 0)}</span>
          </div>
          <div className="h-1.5 w-full bg-terminal-border">
            <div
              className="h-1.5 bg-terminal-amber"
              style={{ width: `${Math.max(0, Math.min(100, conf * 100))}%` }}
            />
          </div>
        </div>
      </div>

      {/* Contributing factors */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-terminal-muted">
          {t("p.intel.regime.contributing")}
        </div>
        <ul className="space-y-0.5 text-[12px]">
          {(regime.contributing_factors || []).map((f, i) => (
            <li key={i} className="text-terminal-text">
              <span className="text-terminal-blue">›</span> {f}
            </li>
          ))}
        </ul>
      </div>

      {/* Indicator grid */}
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-widest text-terminal-muted">
          Indicators
        </div>
        <div className="grid grid-cols-2 gap-1.5 text-[11px] sm:grid-cols-3">
          {Object.entries(regime.raw || {}).map(([k, v]) => {
            const meta = REGIME_INDICATORS[k];
            return (
              <div
                key={k}
                className="flex flex-col rounded border border-terminal-border bg-terminal-panelAlt/40 px-2 py-1"
              >
                <span className="text-[9px] uppercase tracking-widest text-terminal-muted">
                  {meta?.label ?? humanizeKey(k)}
                </span>
                <span className="tabular text-terminal-text">{formatIndicator(k, v)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function FragilityTab({ fragility, pendingOrders = [], t }) {
  if (!fragility) return <div className="text-terminal-muted">{t("p.intel.frag.unavail")}</div>;
  const positions = fragility.positions || [];
  if (positions.length === 0) {
    if (pendingOrders.length > 0) {
      const key = pendingOrders.length === 1 ? "p.intel.frag.pending" : "p.intel.frag.pending_plural";
      return (
        <div className="flex flex-col gap-2 text-[12px]">
          <div className="text-terminal-amber">{t(key, { n: pendingOrders.length })}</div>
          <div className="text-terminal-muted leading-relaxed">
            {t("p.intel.frag.pending_msg", { regime: fragility.regime || "—" })}
          </div>
          <ul className="mt-1 text-[11px] text-terminal-text">
            {pendingOrders.map((o) => (
              <li key={o.id}>
                › {o.side?.toUpperCase()} {o.qty} {o.symbol} ({o.type}) — {o.status}
              </li>
            ))}
          </ul>
        </div>
      );
    }
    return (
      <div className="flex flex-col gap-2 text-[12px]">
        <div className="text-terminal-amber">{t("p.intel.frag.empty_head")}</div>
        <div className="text-terminal-muted leading-relaxed">
          {t("p.intel.frag.empty_msg", { regime: fragility.regime || "—" })}
        </div>
      </div>
    );
  }
  const score = fragility.portfolio_score ?? 0;
  return (
    <div>
      <div className="mb-2 text-[10px] uppercase tracking-widest text-terminal-muted">
        {t("p.intel.frag.portfolio_head", { regime: fragility.regime || "—" })}
      </div>
      <div className="mb-3">
        <div className="flex items-baseline gap-3">
          <span className="text-2xl font-bold text-terminal-amber">{score.toFixed(1)}</span>
          <span className="text-[10px] text-terminal-muted">{t("p.intel.frag.scale")}</span>
        </div>
        <div className="mt-1 h-2 w-full bg-terminal-border">
          <div
            className={`h-2 ${fragilityBarColor(score)}`}
            style={{ width: `${Math.min(100, score)}%` }}
          />
        </div>
      </div>
      <table className="w-full text-[11px]">
        <thead className="text-terminal-muted">
          <tr>
            <th className="text-left">{t("p.intel.frag.cols.sym")}</th>
            <th className="text-right">{t("p.intel.frag.cols.score")}</th>
            <th className="text-right">{t("p.intel.frag.cols.vol")}</th>
            <th className="text-right">{t("p.intel.frag.cols.dd")}</th>
            <th className="text-right">{t("p.intel.frag.cols.bvix")}</th>
            <th className="text-right">{t("p.intel.frag.cols.beta")}</th>
            <th className="text-left pl-2">{t("p.intel.frag.cols.flag")}</th>
          </tr>
        </thead>
        <tbody>
          {(fragility.positions || []).map((p) => (
            <tr key={p.symbol} className="border-b border-terminal-border/30">
              <td className="text-terminal-text">{p.symbol}</td>
              <td className={`text-right ${p.high_risk ? "text-terminal-red" : "text-terminal-amber"}`}>
                {p.score?.toFixed(1) ?? "—"}
              </td>
              <td className="text-right text-terminal-muted">
                {p.components?.vol_percentile != null ? p.components.vol_percentile.toFixed(2) : "—"}
              </td>
              <td className="text-right text-terminal-muted">
                {p.components?.drawdown_depth != null ? pct(p.components.drawdown_depth, 1) : "—"}
              </td>
              <td className="text-right text-terminal-muted">
                {p.components?.vix_correlation != null ? p.components.vix_correlation.toFixed(2) : "—"}
              </td>
              <td className="text-right text-terminal-muted">
                {p.components?.beta != null ? p.components.beta.toFixed(2) : "—"}
              </td>
              <td className="pl-2">
                {p.high_risk ? <span className="text-terminal-red">{t("p.intel.frag.high_risk")}</span> : <span className="text-terminal-muted">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FlowsTab({ flows, t }) {
  if (!flows) return <div className="text-terminal-muted">{t("p.intel.flows.unavail")}</div>;
  return (
    <div>
      <div className="mb-2 text-[10px] uppercase tracking-widest text-terminal-muted">
        {t("p.intel.flows.sec_head")}
      </div>
      <div className="grid grid-cols-2 gap-1 text-[11px]">
        {(flows.sector_flows || []).map((f) => {
          const intensity = Math.min(1, Math.abs(f.relative_to_spy) / 0.1);
          const bg = f.direction === "INFLOW"
            ? `rgba(0, 200, 110, ${(0.15 + 0.55 * intensity).toFixed(2)})`
            : f.direction === "OUTFLOW"
              ? `rgba(220, 60, 60, ${(0.15 + 0.55 * intensity).toFixed(2)})`
              : "rgba(120,120,120,0.15)";
          return (
            <div key={f.etf} className="flex items-center justify-between p-1.5 border border-terminal-border" style={{ background: bg }}>
              <div>
                <div className="text-terminal-text font-bold">{f.etf}</div>
                <div className="text-terminal-muted text-[10px]">{f.sector}</div>
              </div>
              <div className="text-right">
                <div className={STATUS_COLOR[f.direction] || "text-terminal-text"}>
                  {pct(f.relative_to_spy, 1)}
                </div>
                <div className="text-terminal-muted text-[10px]">{f.direction}</div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 mb-1 text-[10px] uppercase tracking-widest text-terminal-muted">
        {t("p.intel.flows.filers_head")}
      </div>
      <table className="w-full text-[11px]">
        <thead className="text-terminal-muted">
          <tr>
            <th className="text-left">{t("p.intel.flows.cols.filer")}</th>
            <th className="text-left">{t("p.intel.flows.cols.cik")}</th>
            <th className="text-left">{t("p.intel.flows.cols.latest")}</th>
            <th className="text-right">{t("p.intel.flows.cols.quarters")}</th>
          </tr>
        </thead>
        <tbody>
          {(flows.filers || []).map((f) => (
            <tr key={f.cik} className="border-b border-terminal-border/30">
              <td className="text-terminal-text">{f.name}</td>
              <td className="text-terminal-muted">{f.cik}</td>
              <td className="text-terminal-blue">{f.latest_13f?.filed || "—"}</td>
              <td className="text-right text-terminal-muted">{f.history_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 text-[10px] text-terminal-muted">{flows.method}</div>
    </div>
  );
}

function RotationTab({ rotation, t }) {
  if (!rotation) return <div className="text-terminal-muted">{t("p.intel.rot.unavail")}</div>;
  // Find the leading + lagging extremes for the bar visual.
  const signals = rotation.signals || [];
  const maxAbs = signals.reduce(
    (m, s) => Math.max(m, Math.abs(s.relative_strength ?? 0)),
    0.01,
  );
  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center gap-3">
        <span className="text-[10px] uppercase tracking-widest text-terminal-muted">
          {t("p.intel.rot.cycle_phase")}
        </span>
        <span className="rounded border border-terminal-amber px-2 py-0.5 text-[12px] font-bold uppercase tracking-widest text-terminal-amber">
          {rotation.phase}
        </span>
        <span className="text-[10px] text-terminal-muted">
          {t("p.intel.rot.spy30", { ret: pct(rotation.spy_return_30d) })}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-terminal-panel text-terminal-muted">
            <tr>
              <th className="text-left">{t("p.intel.rot.cols.etf")}</th>
              <th className="text-left">{t("p.intel.rot.cols.sector")}</th>
              <th className="text-right">{t("p.intel.rot.cols.r30")}</th>
              <th className="text-right">{t("p.intel.rot.cols.rs")}</th>
              <th className="text-left pl-2">{t("p.intel.rot.cols.status")}</th>
              <th className="pl-2 w-[180px]">RS strength</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s) => {
              const rs = s.relative_strength ?? 0;
              const widthPct = Math.min(100, (Math.abs(rs) / maxAbs) * 100);
              return (
                <tr key={s.etf} className="border-b border-terminal-border/30">
                  <td className="text-terminal-text">{s.etf}</td>
                  <td className="text-terminal-muted">{s.sector}</td>
                  <td className="text-right text-terminal-blue">{pct(s.return_30d)}</td>
                  <td className={`text-right ${rs >= 0 ? "text-terminal-green" : "text-terminal-red"}`}>
                    {pct(rs)}
                  </td>
                  <td className={`pl-2 ${STATUS_COLOR[s.status] || ""}`}>{s.status}</td>
                  <td className="pl-2">
                    <div className="relative h-2 w-full bg-terminal-border">
                      <div
                        className={`absolute top-0 h-2 ${rs >= 0 ? "bg-terminal-green" : "bg-terminal-red"}`}
                        style={{
                          width: `${widthPct / 2}%`,
                          left: rs >= 0 ? "50%" : `${50 - widthPct / 2}%`,
                        }}
                      />
                      <div className="absolute left-1/2 top-0 h-2 w-px bg-terminal-muted/40" />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PredictionsTab({ predictions, t }) {
  if (!predictions) {
    return <div className="text-terminal-muted">{t("p.intel.loading")}</div>;
  }
  const { macro = [], markets = [], events = [] } = predictions;
  const total = macro.length + markets.length + events.length;
  if (!total) {
    return <div className="text-terminal-muted">{t("p.intel.predictions.empty")}</div>;
  }
  return (
    <div className="space-y-3 text-xs">
      <Section title={t("p.intel.predictions.sec.macro")}>
        <ConsensusGrid items={macro} t={t} />
      </Section>
      <Section title={t("p.intel.predictions.sec.markets")}>
        <ConsensusGrid items={markets} t={t} />
      </Section>
      <Section title={t("p.intel.predictions.sec.events")}>
        <ConsensusGrid items={events} t={t} />
      </Section>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section>
      <h3 className="mb-1 text-[10px] uppercase tracking-wider text-terminal-amber">{title}</h3>
      {children}
    </section>
  );
}

function ConsensusGrid({ items, t }) {
  if (!items || !items.length) {
    return <div className="text-terminal-muted text-[11px]">{t("p.intel.predictions.empty")}</div>;
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
      {items.slice(0, 12).map((it) => (
        <ConsensusCard key={`${it.source}-${it.id || it.slug}`} item={it} t={t} />
      ))}
    </div>
  );
}

function ConsensusCard({ item, t }) {
  const prob = item.probability != null ? Number(item.probability) : null;
  const probPct = prob != null ? Math.round(prob * 100) : null;
  const cls =
    probPct == null
      ? "border-terminal-border/60 text-terminal-text"
      : probPct >= 70
      ? "border-terminal-green/60 text-terminal-green"
      : probPct <= 30
      ? "border-terminal-red/60 text-terminal-red"
      : "border-terminal-amber/60 text-terminal-amber";
  return (
    <a
      href={item.url || "#"}
      target="_blank"
      rel="noreferrer"
      className={`block rounded border ${cls} px-2 py-1.5 hover:bg-terminal-panelAlt`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wider text-terminal-muted">
          {(item.source || "").toUpperCase()}
        </span>
        <span className="text-base font-bold tabular">{probPct != null ? `${probPct}%` : "--"}</span>
      </div>
      <div className="mt-0.5 text-[11px] leading-snug text-terminal-text line-clamp-3">
        {item.question || item.slug}
      </div>
      <div className="mt-1 flex items-center justify-between text-[10px] text-terminal-muted tabular">
        <span>
          {item.days_to_resolution != null
            ? t("p.intel.predictions.days", { n: item.days_to_resolution })
            : ""}
        </span>
        <span>
          {item.volume_24h != null ? `$${formatVol(item.volume_24h)}` : ""}
        </span>
      </div>
    </a>
  );
}

function formatVol(v) {
  if (v == null) return "--";
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return Math.round(v).toLocaleString();
}
