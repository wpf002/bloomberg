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

export default function RiskPanel() {
  const { t } = useTranslation();
  const [tab, setTab] = useState("summary");
  const [exposure, setExposure] = useState(null);
  const [correlation, setCorrelation] = useState(null);
  const [drawdown, setDrawdown] = useState(null);
  const [varData, setVarData] = useState(null);
  const [stress, setStress] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      api.riskExposure().catch(() => null),
      api.riskCorrelation().catch(() => null),
      api.riskDrawdown().catch(() => null),
      api.riskVar().catch(() => null),
      api.riskStress().catch(() => null),
    ])
      .then(([e, c, d, v, s]) => {
        if (cancelled) return;
        setExposure(e);
        setCorrelation(c);
        setDrawdown(d);
        setVarData(v);
        setStress(s);
        if (!e && !c && !d && !v && !s) {
          setError("All risk endpoints failed — Alpaca credentials may be missing.");
        }
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Panel
      title={t("panels.risk")}
      accent="red"
      actions={
        <div className="flex gap-2 text-[10px] uppercase tracking-widest">
          {[
            ["summary", "VaR/CVaR"],
            ["exposure", "EXPO"],
            ["correlation", "CORR"],
            ["drawdown", "DD"],
            ["stress", "STRESS"],
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
        <div className="text-terminal-muted">Loading risk analytics…</div>
      ) : error ? (
        <div className="text-terminal-red">{error}</div>
      ) : tab === "summary" ? (
        <SummaryTab varData={varData} drawdown={drawdown} />
      ) : tab === "exposure" ? (
        <ExposureTab exposure={exposure} />
      ) : tab === "correlation" ? (
        <CorrelationTab correlation={correlation} />
      ) : tab === "drawdown" ? (
        <DrawdownTab drawdown={drawdown} />
      ) : (
        <StressTab stress={stress} />
      )}
    </Panel>
  );
}

function SummaryTab({ varData, drawdown }) {
  const v = varData || {};
  const port = drawdown?.portfolio || {};
  return (
    <div className="grid grid-cols-2 gap-3 text-[12px]">
      <div className="border border-terminal-border bg-terminal-panelAlt p-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">VaR 95%</div>
        <div className="text-terminal-red text-lg">{pct(v.var_95)}</div>
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted mt-1">CVaR 95%</div>
        <div className="text-terminal-red">{pct(v.cvar_95)}</div>
      </div>
      <div className="border border-terminal-border bg-terminal-panelAlt p-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">VaR 99%</div>
        <div className="text-terminal-red text-lg">{pct(v.var_99)}</div>
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted mt-1">CVaR 99%</div>
        <div className="text-terminal-red">{pct(v.cvar_99)}</div>
      </div>
      <div className="border border-terminal-border bg-terminal-panelAlt p-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">Max Drawdown</div>
        <div className="text-terminal-red text-lg">{pct(port.max_drawdown)}</div>
      </div>
      <div className="border border-terminal-border bg-terminal-panelAlt p-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">Current Drawdown</div>
        <div className="text-terminal-amber text-lg">{pct(port.current_drawdown)}</div>
        <div className="text-[10px] text-terminal-muted">Duration: {port.duration_days ?? "—"} d</div>
      </div>
      <div className="col-span-2 text-[10px] text-terminal-muted">
        Method: historical simulation, observations: {v.observations ?? 0} trading days · daily portfolio
        return σ {pct(v.stdev_daily_return, 3)}
      </div>
    </div>
  );
}

function ExposureTab({ exposure }) {
  if (!exposure || !exposure.sectors?.length) return <div className="text-terminal-muted">No positions or sector data.</div>;
  return (
    <div>
      <div className="mb-2 text-[10px] uppercase tracking-widest text-terminal-muted">
        Total: {dollars(exposure.total_value)}
      </div>
      <table className="w-full text-[11px]">
        <thead className="text-terminal-muted">
          <tr>
            <th className="text-left">SECTOR</th>
            <th className="text-right">VALUE</th>
            <th className="text-right">WEIGHT</th>
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

function CorrelationTab({ correlation }) {
  if (!correlation || !correlation.symbols?.length) {
    return <div className="text-terminal-muted">Need ≥2 holdings with overlapping history.</div>;
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
        90-day daily-return correlation · {correlation.observations} obs.
      </div>
    </div>
  );
}

function DrawdownTab({ drawdown }) {
  if (!drawdown) return <div className="text-terminal-muted">No drawdown data.</div>;
  const port = drawdown.portfolio || {};
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-terminal-muted">Portfolio NAV vs drawdown</div>
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
            <th className="text-left">SYM</th>
            <th className="text-right">MAX DD</th>
            <th className="text-right">CURR DD</th>
            <th className="text-right">DAYS</th>
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

function StressTab({ stress }) {
  if (!stress || !stress.scenarios?.length)
    return <div className="text-terminal-muted">No stress data.</div>;
  return (
    <div>
      <div className="mb-2 text-[10px] uppercase tracking-widest text-terminal-muted">
        Current portfolio: {dollars(stress.current_value)}
      </div>
      <table className="w-full text-[11px]">
        <thead className="text-terminal-muted">
          <tr>
            <th className="text-left">SCENARIO</th>
            <th className="text-right">SPY</th>
            <th className="text-right">PORT %</th>
            <th className="text-right">PORT P/L</th>
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
      <div className="mt-2 text-[10px] text-terminal-muted">
        Stress = SPY historical path × position β · betas computed from 1y daily returns.
      </div>
    </div>
  );
}
