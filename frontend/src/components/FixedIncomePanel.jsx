import { useEffect, useState } from "react";
import clsx from "clsx";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  ComposedChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

function fmtUsd(value) {
  if (value == null) return "--";
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
  return `$${Number(value).toFixed(0)}`;
}

function fmtPct(value) {
  if (value == null) return "--";
  return `${Number(value).toFixed(3)}%`;
}

function fmtSigned(value, digits = 2) {
  if (value == null) return "--";
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${n.toFixed(digits)}`;
}

function fmtDate(iso) {
  if (!iso) return "--";
  const m = String(iso).match(/(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : iso;
}

const TAB_KEYS = ["auctions", "auctioned", "trace", "curve", "mbs"];

export default function FixedIncomePanel() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("curve");
  const [status, setStatus] = useState(null);
  const [auctions, setAuctions] = useState(null);
  const [auctioned, setAuctioned] = useState(null);
  const [trace, setTrace] = useState(null);
  const [curve, setCurve] = useState(null);
  const [mbs, setMbs] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.fixedIncomeStatus().then(setStatus).catch(() => setStatus({ trace_configured: false }));
  }, []);

  const loadTab = async (which) => {
    setBusy(true);
    setError(null);
    try {
      if (which === "auctions") {
        setAuctions(await api.treasuryAuctions("announced", 30));
      } else if (which === "auctioned") {
        setAuctioned(await api.treasuryAuctions("auctioned", 30));
      } else if (which === "trace") {
        setTrace(await api.traceAggregates(undefined, 50));
      } else if (which === "curve") {
        setCurve(await api.yieldCurve());
      } else if (which === "mbs") {
        setMbs(await api.agencyMbs());
      }
    } catch (err) {
      setError(err?.detail || err?.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    loadTab(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const traceMissing = error && /finra trace/i.test(error);
  const fredMissing = error && /fred/i.test(error);

  return (
    <Panel
      title={t("p.fixed.title")}
      accent="amber"
      actions={
        <span className="text-[10px] uppercase tracking-widest text-terminal-muted">
          {t("p.fixed.treasury")} · {status?.trace_configured ? t("p.fixed.trace_ok") : t("p.fixed.trace_off")}
        </span>
      }
    >
      <div className="flex gap-1 border-b border-terminal-border/60 pb-1">
        {TAB_KEYS.map((key) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={clsx(
              "border px-2 py-0.5 text-[10px] uppercase tracking-widest",
              tab === key
                ? "border-terminal-amber text-terminal-amber"
                : "border-transparent text-terminal-muted hover:text-terminal-text"
            )}
          >
            {t(`p.fixed.tabs.${key}`)}
          </button>
        ))}
      </div>

      {busy ? (
        <div className="mt-2 text-xs text-terminal-muted">{t("p.common.loading")}</div>
      ) : tab === "auctions" ? (
        <AuctionTable rows={auctions} kind="upcoming" t={t} />
      ) : tab === "auctioned" ? (
        <AuctionTable rows={auctioned} kind="recent" t={t} />
      ) : tab === "trace" ? (
        traceMissing ? (
          <div className="mt-2 text-xs text-terminal-muted">
            <p className="mb-1 text-terminal-amber">{t("p.fixed.finra_off_head")}</p>
            <p>{t("p.fixed.finra_off_msg")}</p>
          </div>
        ) : error ? (
          <div className="mt-2 text-xs text-terminal-red">{error}</div>
        ) : (
          <TreasuryAggTable rows={trace} t={t} />
        )
      ) : tab === "curve" ? (
        fredMissing ? (
          <div className="mt-2 text-xs text-terminal-amber">{t("p.fixed.curve.unavail")}</div>
        ) : error ? (
          <div className="mt-2 text-xs text-terminal-red">{error}</div>
        ) : (
          <YieldCurveBlock data={curve} t={t} />
        )
      ) : (
        // tab === "mbs"
        fredMissing ? (
          <div className="mt-2 text-xs text-terminal-amber">{t("p.fixed.mbs.unavail")}</div>
        ) : error ? (
          <div className="mt-2 text-xs text-terminal-red">{error}</div>
        ) : (
          <AgencyMbsBlock data={mbs} t={t} />
        )
      )}
    </Panel>
  );
}

function AuctionTable({ rows, kind, t }) {
  if (!rows) return null;
  if (rows.length === 0) {
    return (
      <div className="mt-2 text-xs text-terminal-muted">
        {t("p.fixed.no_auctions", { kind: t(`p.fixed.kind_${kind}`) })}
      </div>
    );
  }
  return (
    <table className="mt-2 w-full text-xs tabular">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-widest text-terminal-muted">
          <th className="py-1 pr-2">{t("p.fixed.cols_a.type")}</th>
          <th className="py-1 pr-2">{t("p.fixed.cols_a.term")}</th>
          <th className="py-1 pr-2 text-right">{t("p.fixed.cols_a.auction")}</th>
          <th className="py-1 pr-2 text-right">{t("p.fixed.cols_a.issue")}</th>
          <th className="py-1 pr-2 text-right">{t("p.fixed.cols_a.maturity")}</th>
          <th className="py-1 pr-2 text-right">{t("p.fixed.cols_a.yield")}</th>
          <th className="py-1 text-right">{t("p.fixed.cols_a.offering")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.cusip || i}`} className="border-t border-terminal-border/40">
            <td className="py-1 pr-2 font-bold text-terminal-amber">{r.security_type}</td>
            <td className="py-1 pr-2 text-terminal-muted">{r.security_term}</td>
            <td className="py-1 pr-2 text-right">{fmtDate(r.auction_date)}</td>
            <td className="py-1 pr-2 text-right">{fmtDate(r.issue_date)}</td>
            <td className="py-1 pr-2 text-right">{fmtDate(r.maturity_date)}</td>
            <td className="py-1 pr-2 text-right">{fmtPct(r.high_yield ?? r.interest_rate)}</td>
            <td className="py-1 text-right">{fmtUsd(r.offering_amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TreasuryAggTable({ rows, t }) {
  if (!rows) return null;
  if (rows.length === 0) {
    return <div className="mt-2 text-xs text-terminal-muted">{t("p.fixed.no_trace")}</div>;
  }
  return (
    <table className="mt-2 w-full text-xs tabular">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-widest text-terminal-muted">
          <th className="py-1 pr-2">{t("p.fixed.cols_t.period")}</th>
          <th className="py-1 pr-2">{t("p.fixed.cols_t.type")}</th>
          <th className="py-1 pr-2">{t("p.fixed.cols_t.term")}</th>
          <th className="py-1 pr-2 text-right">{t("p.fixed.cols_t.par_vol")}</th>
          <th className="py-1 pr-2 text-right">{t("p.fixed.cols_t.trades")}</th>
          <th className="py-1 pr-2 text-right">{t("p.fixed.cols_t.avg_size")}</th>
          <th className="py-1 pr-2 text-right">{t("p.fixed.cols_t.d2c")}</th>
          <th className="py-1 text-right">{t("p.fixed.cols_t.d2d")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 30).map((r, i) => (
          <tr key={`${r.period || ""}-${r.benchmark_term || ""}-${i}`} className="border-t border-terminal-border/40">
            <td className="py-1 pr-2 font-bold text-terminal-amber">{fmtDate(r.period)}</td>
            <td className="py-1 pr-2 text-terminal-muted">{r.security_type || "--"}</td>
            <td className="py-1 pr-2">{r.benchmark_term || "--"}</td>
            <td className="py-1 pr-2 text-right">{fmtUsd(r.total_par_volume)}</td>
            <td className="py-1 pr-2 text-right">{r.total_trade_count?.toLocaleString() ?? "--"}</td>
            <td className="py-1 pr-2 text-right">{fmtUsd(r.avg_trade_size)}</td>
            <td className="py-1 pr-2 text-right">
              {r.pct_dealer_to_customer != null ? Number(r.pct_dealer_to_customer).toFixed(2) + "%" : "--"}
            </td>
            <td className="py-1 text-right">
              {r.pct_dealer_to_dealer != null ? Number(r.pct_dealer_to_dealer).toFixed(2) + "%" : "--"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function YieldCurveBlock({ data, t }) {
  if (!data) return <div className="mt-2 text-xs text-terminal-muted">{t("p.fixed.curve.loading")}</div>;
  const interp = data.interpolated || [];
  const raw = data.raw || [];
  const merged = interp.map((p) => ({ years: p.years, smooth: p.yield, raw: null }));
  raw.forEach((r) => {
    merged.push({ years: r.years, smooth: null, raw: r.yield });
  });
  merged.sort((a, b) => a.years - b.years);

  const inverted = data.shape === "inverted";
  const shapeKey = inverted ? "p.fixed.curve.inverted" : "p.fixed.curve.normal";
  const shadeColor = inverted ? "#dc3c3c" : "#00d26a";

  // 2Y/10Y reference area — shade between the two when both are present.
  const y2 = raw.find((r) => r.label === "2Y");
  const y10 = raw.find((r) => r.label === "10Y");

  return (
    <div className="mt-2 flex flex-col gap-2">
      <div className="flex items-baseline justify-between text-[11px] uppercase tracking-widest">
        <span className="text-terminal-muted">{t("p.fixed.curve.head")}</span>
        <span className={inverted ? "text-terminal-red" : "text-terminal-green"}>
          {t(shapeKey)} · {t("p.fixed.curve.spread_2y10y", { bps: data.spread_2y10y_bps ?? "—" })}
        </span>
      </div>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={merged}>
            <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" />
            <XAxis
              dataKey="years"
              type="number"
              domain={[0, 30]}
              ticks={[0.25, 1, 2, 5, 10, 20, 30]}
              tickFormatter={(v) => (v < 1 ? `${Math.round(v * 12)}M` : `${v}Y`)}
              tick={{ fontSize: 10, fill: "#888" }}
              stroke="#5a606a"
            />
            <YAxis
              tickFormatter={(v) => `${Number(v).toFixed(2)}%`}
              tick={{ fontSize: 10, fill: "#888" }}
              stroke="#5a606a"
              domain={["auto", "auto"]}
              width={50}
            />
            <Tooltip
              contentStyle={{ background: "#0b0d10", border: "1px solid #1f242c", fontSize: 11 }}
              formatter={(value) => (value == null ? "--" : `${Number(value).toFixed(3)}%`)}
              labelFormatter={(v) => (v < 1 ? `${(v * 12).toFixed(0)}M` : `${Number(v).toFixed(2)}Y`)}
            />
            {y2 && y10 ? (
              <ReferenceArea
                x1={y2.years}
                x2={y10.years}
                fill={shadeColor}
                fillOpacity={0.12}
                strokeOpacity={0}
              />
            ) : null}
            <Line
              type="monotone"
              dataKey="smooth"
              stroke="#ff9f1c"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
              name={t("p.fixed.curve.smooth")}
            />
            <Scatter dataKey="raw" fill="#3b82f6" shape="circle" name={t("p.fixed.curve.raw")} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <table className="mt-1 w-full text-[11px] tabular">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-widest text-terminal-muted">
            <th className="py-1 pr-2">Tenor</th>
            <th className="py-1 pr-2 text-right">FRED ID</th>
            <th className="py-1 text-right">Yield</th>
          </tr>
        </thead>
        <tbody>
          {raw.map((r) => (
            <tr key={r.label} className="border-t border-terminal-border/40">
              <td className="py-1 pr-2 font-bold text-terminal-amber">{r.label}</td>
              <td className="py-1 pr-2 text-right text-terminal-muted">{r.series_id}</td>
              <td className="py-1 text-right">{Number(r.yield).toFixed(3)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AgencyMbsBlock({ data, t }) {
  if (!data) return <div className="mt-2 text-xs text-terminal-muted">{t("p.fixed.mbs.loading")}</div>;
  const metrics = data.metrics || [];
  const spread = data.mortgage_treasury_spread || [];

  return (
    <div className="mt-2 flex flex-col gap-3">
      <div className="text-[11px] uppercase tracking-widest text-terminal-muted">
        {t("p.fixed.mbs.head")}
      </div>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
        {metrics.map((m) => (
          <MetricCard key={m.series_id} metric={m} t={t} />
        ))}
      </div>

      <div className="mt-2 text-[11px] uppercase tracking-widest text-terminal-muted">
        {t("p.fixed.mbs.spread_head")}
      </div>
      <div className="text-[10px] text-terminal-muted">{t("p.fixed.mbs.spread_subhead")}</div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={spread}>
            <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 9, fill: "#888" }}
              minTickGap={40}
            />
            <YAxis
              tickFormatter={(v) => `${Number(v).toFixed(1)}%`}
              tick={{ fontSize: 10, fill: "#888" }}
              stroke="#5a606a"
              width={50}
            />
            <Tooltip
              contentStyle={{ background: "#0b0d10", border: "1px solid #1f242c", fontSize: 11 }}
              formatter={(value, name) => [`${Number(value).toFixed(3)}%`, name]}
            />
            <Line type="monotone" dataKey="mortgage" stroke="#ff9f1c" strokeWidth={1.5} dot={false} name="MORTGAGE30US" />
            <Line type="monotone" dataKey="treasury_10y" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="DGS10" />
            <Line type="monotone" dataKey="spread" stroke="#dc3c3c" strokeWidth={1.5} dot={false} name="Spread" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function MetricCard({ metric, t }) {
  const labelOverride = t(`p.fixed.mbs.labels.${metric.series_id}`);
  const label = labelOverride && labelOverride !== `p.fixed.mbs.labels.${metric.series_id}`
    ? labelOverride
    : metric.label;
  const cur = metric.current;
  const wow = metric.wow;
  const yoy = metric.yoy;
  const wowTone = wow == null ? "text-terminal-muted" : wow > 0 ? "text-terminal-red" : "text-terminal-green";
  const yoyTone = yoy == null ? "text-terminal-muted" : yoy > 0 ? "text-terminal-red" : "text-terminal-green";
  const sparkMin = (metric.sparkline || []).reduce((m, p) => Math.min(m, p.value), Infinity);
  const sparkMax = (metric.sparkline || []).reduce((m, p) => Math.max(m, p.value), -Infinity);
  return (
    <div className="border border-terminal-border bg-terminal-panelAlt p-2">
      <div className="text-[10px] uppercase tracking-widest text-terminal-muted">{label}</div>
      <div className="text-lg font-bold tabular text-terminal-text">
        {cur != null ? `${Number(cur).toFixed(2)}%` : "--"}
      </div>
      <div className="flex items-baseline justify-between text-[10px] tabular">
        <span className={wowTone}>{t("p.fixed.mbs.wow")} {fmtSigned(wow, 3)}</span>
        <span className={yoyTone}>{t("p.fixed.mbs.yoy")} {fmtSigned(yoy, 2)}</span>
      </div>
      {metric.sparkline?.length ? (
        <div className="mt-1 h-8 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={metric.sparkline} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
              <YAxis hide domain={[sparkMin, sparkMax]} />
              <Line type="monotone" dataKey="value" stroke="#ff9f1c" strokeWidth={1.2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : null}
    </div>
  );
}
