import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
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
import { useTranslation } from "../i18n/index.jsx";

function pct(n, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(Number(n) * 100).toFixed(digits)}%`;
}

function dollars(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const num = Number(n);
  const abs = Math.abs(num);
  if (abs >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `$${(num / 1e3).toFixed(2)}K`;
  return `$${num.toFixed(2)}`;
}

function corrColor(v) {
  if (v == null || Number.isNaN(v)) return "rgba(120,120,120,0.2)";
  const x = Math.max(-1, Math.min(1, v));
  if (x >= 0) {
    const a = 0.15 + 0.6 * x;
    return `rgba(0, 200, 110, ${a.toFixed(2)})`;
  }
  const a = 0.15 + 0.6 * Math.abs(x);
  return `rgba(220, 60, 60, ${a.toFixed(2)})`;
}

// Per-tab lazy fetchers. Summary needs both VaR and drawdown so it's the
// odd one out — we collapse those into a single "summary" key here.
const TAB_FETCHERS = {
  summary:     () => Promise.all([api.riskVar(), api.riskDrawdown()]).then(([v, d]) => ({ v, d })),
  exposure:    () => api.riskExposure(),
  correlation: () => api.riskCorrelation(),
  drawdown:    () => api.riskDrawdown(),
  stress:      () => api.riskStress(),
};

export default function RiskPanel() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("summary");
  const [data, setData] = useState({});
  const [loaded, setLoaded] = useState({});
  const [loading, setLoading] = useState({});
  const [pendingOrders, setPendingOrders] = useState([]);
  const [ordersLoaded, setOrdersLoaded] = useState(false);

  useEffect(() => {
    if (loaded[tab] || loading[tab]) return;
    let cancelled = false;
    setLoading((p) => ({ ...p, [tab]: true }));
    TAB_FETCHERS[tab]()
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

  // The summary tab also needs to know about empty portfolios; pull the
  // exposure call and pending orders in the background after first paint
  // so the empty-state copy shows up if applicable.
  useEffect(() => {
    if (loaded.exposure || loading.exposure) return;
    TAB_FETCHERS.exposure().then((d) => {
      setData((p) => ({ ...p, exposure: d }));
      setLoaded((p) => ({ ...p, exposure: true }));
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (ordersLoaded) return;
    api
      .orders("open", 50)
      .then((ords) => {
        setPendingOrders(
          (ords || []).filter((o) =>
            ["accepted", "new", "pending_new", "partially_filled"].includes(o.status),
          ),
        );
        setOrdersLoaded(true);
      })
      .catch(() => setOrdersLoaded(true));
  }, [ordersLoaded]);

  const summary = data.summary || {};
  const exposure = data.exposure;
  const varData = summary.v;
  const drawdown = data.drawdown || summary.d;

  return (
    <Panel
      title={t("panels.risk")}
      accent="red"
      actions={
        <div className="flex gap-2 text-[10px] uppercase tracking-widest">
          {[
            ["summary", t("p.risk.tabs.summary")],
            ["exposure", t("p.risk.tabs.exposure")],
            ["correlation", t("p.risk.tabs.correlation")],
            ["drawdown", t("p.risk.tabs.drawdown")],
            ["stress", t("p.risk.tabs.stress")],
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
        <div className="text-terminal-muted">{t("p.risk.loading")}</div>
      ) : isPortfolioEmpty(exposure, varData) ? (
        <EmptyState pendingOrders={pendingOrders} t={t} />
      ) : tab === "summary" ? (
        <SummaryTab varData={varData} drawdown={drawdown} t={t} />
      ) : tab === "exposure" ? (
        <ExposureTab exposure={data.exposure} t={t} />
      ) : tab === "correlation" ? (
        <CorrelationTab correlation={data.correlation} t={t} />
      ) : tab === "drawdown" ? (
        <DrawdownTab drawdown={data.drawdown} t={t} />
      ) : (
        <StressTab stress={data.stress} t={t} />
      )}
    </Panel>
  );
}

function isPortfolioEmpty(exposure, varData) {
  // Defer the empty check until exposure has actually loaded — otherwise we
  // flash the empty state on every initial render.
  if (exposure === undefined && varData === undefined) return false;
  const noExposure = !exposure || (exposure.total_value ?? 0) <= 0;
  const noObservations = !varData || (varData.observations ?? 0) === 0;
  return noExposure && noObservations;
}

function EmptyState({ pendingOrders = [], t }) {
  if (pendingOrders.length > 0) {
    const key = pendingOrders.length === 1 ? "p.risk.empty_pending" : "p.risk.empty_pending_plural";
    return (
      <div className="flex h-full flex-col items-start justify-start gap-2 text-[12px]">
        <div className="text-terminal-amber">{t(key, { n: pendingOrders.length })}</div>
        <div className="text-terminal-muted leading-relaxed">
          {t("p.risk.empty_pending_msg")}
        </div>
        <table className="w-full text-[11px] mt-1">
          <thead className="text-terminal-muted">
            <tr>
              <th className="text-left">{t("p.risk.cols_pending.sym")}</th>
              <th className="text-left">{t("p.risk.cols_pending.side")}</th>
              <th className="text-right">{t("p.risk.cols_pending.qty")}</th>
              <th className="text-left pl-2">{t("p.risk.cols_pending.type")}</th>
              <th className="text-left pl-2">{t("p.risk.cols_pending.submitted")}</th>
              <th className="text-left pl-2">{t("p.risk.cols_pending.status")}</th>
            </tr>
          </thead>
          <tbody>
            {pendingOrders.map((o) => (
              <tr key={o.id} className="border-b border-terminal-border/30">
                <td className="text-terminal-text">{o.symbol}</td>
                <td className={o.side === "buy" ? "text-terminal-green" : "text-terminal-red"}>
                  {o.side?.toUpperCase()}
                </td>
                <td className="text-right text-terminal-amber">{o.qty}</td>
                <td className="pl-2 text-terminal-muted">{o.type}</td>
                <td className="pl-2 text-terminal-muted">
                  {o.submitted_at ? new Date(o.submitted_at).toLocaleString() : "—"}
                </td>
                <td className="pl-2 text-terminal-blue">{o.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col items-start justify-start gap-2 text-[12px]">
      <div className="text-terminal-amber">{t("p.risk.empty_head")}</div>
      <div className="text-terminal-muted leading-relaxed">{t("p.risk.empty_msg")}</div>
    </div>
  );
}

function SummaryTab({ varData, drawdown, t }) {
  const v = varData || {};
  const port = drawdown?.portfolio || {};
  return (
    <div className="grid grid-cols-2 gap-3 text-[12px]">
      <div className="border border-terminal-border bg-terminal-panelAlt p-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">{t("p.risk.summary.var95")}</div>
        <div className="text-terminal-red text-lg">{pct(v.var_95)}</div>
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted mt-1">{t("p.risk.summary.cvar95")}</div>
        <div className="text-terminal-red">{pct(v.cvar_95)}</div>
      </div>
      <div className="border border-terminal-border bg-terminal-panelAlt p-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">{t("p.risk.summary.var99")}</div>
        <div className="text-terminal-red text-lg">{pct(v.var_99)}</div>
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted mt-1">{t("p.risk.summary.cvar99")}</div>
        <div className="text-terminal-red">{pct(v.cvar_99)}</div>
      </div>
      <div className="border border-terminal-border bg-terminal-panelAlt p-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">{t("p.risk.summary.max_dd")}</div>
        <div className="text-terminal-red text-lg">{pct(port.max_drawdown)}</div>
      </div>
      <div className="border border-terminal-border bg-terminal-panelAlt p-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">{t("p.risk.summary.curr_dd")}</div>
        <div className="text-terminal-amber text-lg">{pct(port.current_drawdown)}</div>
        <div className="text-[10px] text-terminal-muted">
          {t("p.risk.summary.duration", { n: port.duration_days ?? "—" })}
        </div>
      </div>
      <div className="col-span-2 text-[10px] text-terminal-muted">
        {t("p.risk.summary.method", { n: v.observations ?? 0, sigma: pct(v.stdev_daily_return, 3) })}
      </div>
    </div>
  );
}

function ExposureTab({ exposure, t }) {
  if (!exposure || !exposure.sectors?.length) return <div className="text-terminal-muted">{t("p.risk.expo.none")}</div>;
  return (
    <div>
      <div className="mb-2 text-[10px] uppercase tracking-widest text-terminal-muted">
        {t("p.risk.expo.total", { value: dollars(exposure.total_value) })}
      </div>
      <table className="w-full text-[11px]">
        <thead className="text-terminal-muted">
          <tr>
            <th className="text-left">{t("p.risk.expo.cols.sector")}</th>
            <th className="text-right">{t("p.risk.expo.cols.value")}</th>
            <th className="text-right">{t("p.risk.expo.cols.weight")}</th>
          </tr>
        </thead>
        <tbody>
          {exposure.sectors.map((s) => (
            <tr key={s.sector} className="border-b border-terminal-border/30">
              <td className="text-terminal-text">{s.sector}</td>
              <td className="text-right text-terminal-amber">{dollars(s.value)}</td>
              <td className="text-right text-terminal-blue">{pct(s.weight, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CorrelationTab({ correlation, t }) {
  if (!correlation || !correlation.symbols?.length) {
    return <div className="text-terminal-muted">{t("p.risk.corr.need")}</div>;
  }
  const { symbols, matrix } = correlation;
  return (
    <div className="overflow-auto">
      <table className="text-[10px]">
        <thead>
          <tr>
            <th></th>
            {symbols.map((s) => (
              <th key={s} className="px-1 text-terminal-muted">{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((row, i) => (
            <tr key={row}>
              <td className="text-terminal-muted pr-1">{row}</td>
              {symbols.map((col, j) => {
                const v = matrix[i][j];
                return (
                  <td
                    key={col}
                    className="px-1 text-center"
                    style={{ background: corrColor(v), color: "#e7e7e7", minWidth: 36 }}
                    title={`${row} vs ${col}: ${v}`}
                  >
                    {v?.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 text-[10px] text-terminal-muted">
        {t("p.risk.corr.footer", { n: correlation.observations })}
      </div>
    </div>
  );
}

function DrawdownTab({ drawdown, t }) {
  if (!drawdown) return <div className="text-terminal-muted">{t("p.risk.dd.none")}</div>;
  const port = drawdown.portfolio || {};
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-terminal-muted">{t("p.risk.dd.head")}</div>
      <div style={{ height: 140 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={port.nav || []}>
            <CartesianGrid stroke="#222" strokeDasharray="2 4" />
            <XAxis dataKey="date" hide />
            <YAxis tick={{ fontSize: 10, fill: "#888" }} domain={["auto", "auto"]} />
            <Tooltip contentStyle={{ background: "#0d0d0d", border: "1px solid #333" }} />
            <Line type="monotone" dataKey="value" stroke="#f5b400" dot={false} strokeWidth={1.5} name="NAV" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={{ height: 100 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={port.drawdown_curve || []}>
            <CartesianGrid stroke="#222" strokeDasharray="2 4" />
            <XAxis dataKey="date" hide />
            <YAxis tickFormatter={(v) => pct(v, 0)} tick={{ fontSize: 10, fill: "#888" }} />
            <Tooltip
              contentStyle={{ background: "#0d0d0d", border: "1px solid #333" }}
              formatter={(v) => pct(v)}
            />
            <Area type="monotone" dataKey="value" stroke="#dc3c3c" fill="#dc3c3c" fillOpacity={0.25} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <table className="mt-2 w-full text-[11px]">
        <thead className="text-terminal-muted">
          <tr>
            <th className="text-left">{t("p.risk.dd.cols.sym")}</th>
            <th className="text-right">{t("p.risk.dd.cols.max_dd")}</th>
            <th className="text-right">{t("p.risk.dd.cols.curr_dd")}</th>
            <th className="text-right">{t("p.risk.dd.cols.days")}</th>
          </tr>
        </thead>
        <tbody>
          {(drawdown.per_position || []).map((p) => (
            <tr key={p.symbol} className="border-b border-terminal-border/30">
              <td className="text-terminal-text">{p.symbol}</td>
              <td className="text-right text-terminal-red">{pct(p.max_drawdown)}</td>
              <td className="text-right text-terminal-amber">{pct(p.current_drawdown)}</td>
              <td className="text-right text-terminal-muted">{p.duration_days}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StressTab({ stress, t }) {
  if (!stress || !stress.scenarios?.length)
    return <div className="text-terminal-muted">{t("p.risk.stress.none")}</div>;
  return (
    <div>
      <div className="mb-2 text-[10px] uppercase tracking-widest text-terminal-muted">
        {t("p.risk.stress.head", { value: dollars(stress.current_value) })}
      </div>
      <table className="w-full text-[11px]">
        <thead className="text-terminal-muted">
          <tr>
            <th className="text-left">{t("p.risk.stress.cols.scenario")}</th>
            <th className="text-right">{t("p.risk.stress.cols.spy")}</th>
            <th className="text-right">{t("p.risk.stress.cols.port_pct")}</th>
            <th className="text-right">{t("p.risk.stress.cols.port_pl")}</th>
          </tr>
        </thead>
        <tbody>
          {stress.scenarios.map((s) => (
            <tr key={s.name} className="border-b border-terminal-border/30">
              <td className="text-terminal-text">{s.name}</td>
              <td className="text-right text-terminal-blue">{pct(s.spy_return)}</td>
              <td
                className={`text-right ${s.portfolio_return < 0 ? "text-terminal-red" : "text-terminal-green"}`}
              >
                {pct(s.portfolio_return)}
              </td>
              <td
                className={`text-right ${s.portfolio_pnl < 0 ? "text-terminal-red" : "text-terminal-green"}`}
              >
                {dollars(s.portfolio_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 text-[10px] text-terminal-muted">{t("p.risk.stress.footer")}</div>
    </div>
  );
}
