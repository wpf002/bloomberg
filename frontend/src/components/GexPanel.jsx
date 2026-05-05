import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

function formatNumber(n, digits = 0) {
  if (n == null || Number.isNaN(n)) return "--";
  const v = Number(n);
  if (Math.abs(v) >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(1)}B`;
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(digits);
}

export default function GexPanel({ symbol }) {
  const { t } = useTranslation();
  const sym = (symbol || "AAPL").toUpperCase();
  const gexQ = usePolling(() => api.gexProfile(sym), 60_000, [sym]);
  const vexQ = usePolling(() => api.vexProfile(sym), 60_000, [sym]);

  const gex = gexQ.data;
  const vex = vexQ.data;

  const interpretation = useMemo(() => {
    if (!gex) return "";
    if (gex.net_gex > 0) {
      return t("p.gex.interp.long_gamma", { x: gex.flip_point?.toFixed(2) || "?" });
    }
    if (gex.net_gex < 0) {
      return t("p.gex.interp.short_gamma");
    }
    return t("p.gex.interp.neutral");
  }, [gex, t]);

  return (
    <Panel
      title={t("p.gex.title", { sym })}
      accent="blue"
      actions={
        gex?.spot != null ? (
          <span className="text-terminal-muted tabular">{t("p.gex.spot", { px: Number(gex.spot).toFixed(2) })}</span>
        ) : null
      }
    >
      {gexQ.loading && !gexQ.data ? (
        <div className="text-terminal-muted text-xs">{t("p.common.loading")}</div>
      ) : gexQ.error ? (
        <div className="text-terminal-red text-xs">{String(gexQ.error.detail || gexQ.error.message)}</div>
      ) : (
        <div className="space-y-3 text-xs">
          <KeyLevelsCard gex={gex} vex={vex} t={t} />
          <div className="rounded border border-terminal-border/60 px-2 py-1.5 text-[11px] leading-relaxed">
            {interpretation}
          </div>
          <Section title={t("p.gex.sec.gex_profile")}>
            <GexChart gex={gex} t={t} />
          </Section>
          <Section title={t("p.gex.sec.vex_profile")}>
            <VexChart vex={vex} t={t} />
          </Section>
        </div>
      )}
    </Panel>
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

function KeyLevelsCard({ gex, vex, t }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <Stat label={t("p.gex.flip")} value={gex?.flip_point != null ? gex.flip_point.toFixed(2) : "--"} />
      <Stat label={t("p.gex.max_gamma")} value={gex?.max_gamma_strike != null ? Number(gex.max_gamma_strike).toFixed(2) : "--"} />
      <Stat label={t("p.gex.net_gex")} value={formatNumber(gex?.net_gex)} />
      <Stat label={t("p.gex.vol_trigger")} value={vex?.vol_trigger != null ? `${(vex.vol_trigger * 100).toFixed(0)}%` : "--"} />
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded border border-terminal-border/60 px-2 py-1">
      <div className="text-[10px] uppercase tracking-wider text-terminal-muted">{label}</div>
      <div className="text-terminal-text tabular">{value}</div>
    </div>
  );
}

function GexChart({ gex, t }) {
  const rows = gex?.strikes || [];
  if (!rows.length) return <div className="text-terminal-muted">{t("p.common.no_data")}</div>;
  const data = rows.map((r) => ({
    strike: r.strike,
    call: r.call_gex,
    put: r.put_gex,
    net: r.net_gex,
  }));
  return (
    <div style={{ width: "100%", height: 260 }}>
      <ResponsiveContainer>
        <BarChart data={data} stackOffset="sign">
          <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" />
          <XAxis dataKey="strike" stroke="#8a8f98" fontSize={10} />
          <YAxis stroke="#8a8f98" fontSize={10} tickFormatter={(v) => formatNumber(v)} width={60} />
          <Tooltip
            contentStyle={{ background: "#111418", border: "1px solid #1f242c", fontSize: 11 }}
            formatter={(v, name) => [formatNumber(v), name]}
          />
          {gex.spot ? <ReferenceLine x={gex.spot} stroke="#facc15" label={{ value: "spot", fontSize: 10, fill: "#facc15" }} /> : null}
          {gex.flip_point ? <ReferenceLine x={gex.flip_point} stroke="#a78bfa" strokeDasharray="3 3" label={{ value: "flip", fontSize: 10, fill: "#a78bfa" }} /> : null}
          <Bar dataKey="call" stackId="g" fill="#00d26a" />
          <Bar dataKey="put" stackId="g" fill="#ff4d4d" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function VexChart({ vex, t }) {
  const rows = vex?.strikes || [];
  if (!rows.length) return <div className="text-terminal-muted">{t("p.common.no_data")}</div>;
  const data = rows.map((r) => ({ strike: r.strike, vex: r.vex }));
  return (
    <div style={{ width: "100%", height: 220 }}>
      <ResponsiveContainer>
        <BarChart data={data}>
          <CartesianGrid stroke="#1f242c" strokeDasharray="2 4" />
          <XAxis dataKey="strike" stroke="#8a8f98" fontSize={10} />
          <YAxis stroke="#8a8f98" fontSize={10} tickFormatter={(v) => formatNumber(v)} width={60} />
          <Tooltip
            contentStyle={{ background: "#111418", border: "1px solid #1f242c", fontSize: 11 }}
            formatter={(v) => [formatNumber(v), "VEX"]}
          />
          {vex.spot ? <ReferenceLine x={vex.spot} stroke="#facc15" label={{ value: "spot", fontSize: 10, fill: "#facc15" }} /> : null}
          <Bar dataKey="vex">
            {data.map((row, idx) => (
              <Cell key={idx} fill={row.vex >= 0 ? "#00d26a" : "#ff4d4d"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
