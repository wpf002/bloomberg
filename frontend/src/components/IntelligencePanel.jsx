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

export default function IntelligencePanel() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("regime");
  const [regime, setRegime] = useState(null);
  const [fragility, setFragility] = useState(null);
  const [flows, setFlows] = useState(null);
  const [rotation, setRotation] = useState(null);
  const [pendingOrders, setPendingOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.intelRegime().catch(() => null),
      api.intelFragility().catch(() => null),
      api.intelFlows().catch(() => null),
      api.intelRotation().catch(() => null),
      api.orders("open", 50).catch(() => []),
    ])
      .then(([r, f, fl, ro, ords]) => {
        if (cancelled) return;
        setRegime(r);
        setFragility(f);
        setFlows(fl);
        setRotation(ro);
        setPendingOrders(
          (ords || []).filter(
            (o) => ["accepted", "new", "pending_new", "partially_filled"].includes(o.status),
          ),
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

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
      {loading ? (
        <div className="text-terminal-muted">{t("p.intel.loading")}</div>
      ) : tab === "regime" ? (
        <RegimeTab regime={regime} t={t} />
      ) : tab === "fragility" ? (
        <FragilityTab fragility={fragility} pendingOrders={pendingOrders} t={t} />
      ) : tab === "flows" ? (
        <FlowsTab flows={flows} t={t} />
      ) : (
        <RotationTab rotation={rotation} t={t} />
      )}
    </Panel>
  );
}

function RegimeTab({ regime, t }) {
  if (!regime) return <div className="text-terminal-muted">{t("p.intel.regime.unavail")}</div>;
  const cls = REGIME_COLORS[regime.regime] || REGIME_COLORS.NEUTRAL;
  return (
    <div>
      <div
        className={`mb-3 inline-flex items-center gap-3 rounded border px-4 py-2 text-lg font-bold uppercase tracking-widest ${cls}`}
      >
        {regime.regime?.replaceAll("_", " ") || "—"}
        <span className="text-xs opacity-70">{t("p.intel.regime.conf")} {pct(regime.confidence, 0)}</span>
      </div>
      <div className="mb-3 text-[10px] uppercase tracking-widest text-terminal-muted">
        {t("p.intel.regime.contributing")}
      </div>
      <ul className="space-y-1 text-[12px]">
        {(regime.contributing_factors || []).map((f, i) => (
          <li key={i} className="text-terminal-text">
            <span className="text-terminal-blue">›</span> {f}
          </li>
        ))}
      </ul>
      <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-terminal-muted">
        {Object.entries(regime.raw || {}).map(([k, v]) => (
          <div key={k} className="border border-terminal-border p-1">
            <div className="text-[9px] uppercase tracking-widest">{k}</div>
            <div className="text-terminal-text">{v == null ? "—" : Number(v).toFixed(3)}</div>
          </div>
        ))}
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
  return (
    <div>
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
      <table className="w-full text-[11px]">
        <thead className="text-terminal-muted">
          <tr>
            <th className="text-left">{t("p.intel.rot.cols.etf")}</th>
            <th className="text-left">{t("p.intel.rot.cols.sector")}</th>
            <th className="text-right">{t("p.intel.rot.cols.r30")}</th>
            <th className="text-right">{t("p.intel.rot.cols.rs")}</th>
            <th className="text-left pl-2">{t("p.intel.rot.cols.status")}</th>
          </tr>
        </thead>
        <tbody>
          {(rotation.signals || []).map((s) => (
            <tr key={s.etf} className="border-b border-terminal-border/30">
              <td className="text-terminal-text">{s.etf}</td>
              <td className="text-terminal-muted">{s.sector}</td>
              <td className="text-right text-terminal-blue">{pct(s.return_30d)}</td>
              <td className={`text-right ${s.relative_strength >= 0 ? "text-terminal-green" : "text-terminal-red"}`}>
                {pct(s.relative_strength)}
              </td>
              <td className={`pl-2 ${STATUS_COLOR[s.status] || ""}`}>{s.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
