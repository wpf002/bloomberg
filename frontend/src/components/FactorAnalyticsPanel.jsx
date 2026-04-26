import { useEffect, useState } from "react";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const FACTOR_KEYS = ["mkt_rf", "smb", "hml", "rmw", "cma", "mom"];

function fmtPct(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return `${(value * 100).toFixed(digits)}%`;
}

function fmtNum(value, digits = 3) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export default function FactorAnalyticsPanel() {
  const { t } = useTranslation();
  const [lookback, setLookback] = useState(252);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.portfolioFactors(lookback);
      setData(res);
    } catch (err) {
      setError(err?.detail || err?.message || String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const credsMissing = error && /alpaca credentials/i.test(error);

  return (
    <Panel
      title={t("p.factors.title")}
      accent="amber"
      actions={
        <span className="flex items-center gap-2 tabular text-terminal-muted">
          <select
            value={lookback}
            onChange={(e) => setLookback(Number(e.target.value))}
            className="border border-terminal-border bg-terminal-bg px-1 py-0.5 text-[10px] uppercase tracking-widest text-terminal-text focus:outline-none focus:border-terminal-amber"
          >
            <option value={63}>3m</option>
            <option value={126}>6m</option>
            <option value={252}>1y</option>
            <option value={504}>2y</option>
            <option value={1260}>5y</option>
          </select>
          <button
            onClick={load}
            disabled={loading}
            className="border border-terminal-amber px-2 py-0.5 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
          >
            {loading ? "…" : data ? t("p.common.refresh") : t("p.common.run")}
          </button>
        </span>
      }
    >
      {credsMissing ? (
        <div className="text-xs text-terminal-muted">
          <p className="mb-2 text-terminal-amber">{t("p.factors.need_alpaca_head")}</p>
          <p>{t("p.factors.need_alpaca_msg")}</p>
        </div>
      ) : error ? (
        <div className="text-xs text-terminal-red">{error}</div>
      ) : loading && !data ? (
        <div className="text-xs text-terminal-muted">{t("p.factors.pulling")}</div>
      ) : !data || data.insufficient_data ? (
        <div className="text-xs text-terminal-muted">
          {data?.message || t("p.factors.hint")}
        </div>
      ) : (
        <div className="space-y-3 text-xs">
          <div className="grid grid-cols-3 gap-2 border border-terminal-border bg-terminal-panelAlt p-2">
            <Stat
              label={t("p.factors.stats.alpha")}
              value={fmtPct(data.alpha_annual, 2)}
              accent={data.alpha_annual > 0 ? "green" : "red"}
            />
            <Stat label={t("p.factors.stats.r2")} value={fmtNum(data.r_squared, 3)} />
            <Stat label={t("p.factors.stats.days")} value={String(data.observations)} />
          </div>
          <table className="w-full tabular">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-widest text-terminal-muted">
                <th className="py-1 pr-2">{t("p.factors.cols.factor")}</th>
                <th className="py-1 pr-2 text-right">{t("p.factors.cols.beta")}</th>
                <th className="py-1 pr-2">{t("p.factors.cols.reading")}</th>
              </tr>
            </thead>
            <tbody>
              {FACTOR_KEYS.map((key) => {
                const beta = data.factors?.[key];
                const reading = readBeta(key, beta, t);
                return (
                  <tr key={key} className="border-t border-terminal-border/40">
                    <td className="py-1 pr-2 text-terminal-text">
                      {t(`p.factors.labels.${key}`)}
                    </td>
                    <td className={clsx(
                      "py-1 pr-2 text-right",
                      beta > 0 ? "text-terminal-green" : beta < 0 ? "text-terminal-red" : "text-terminal-muted"
                    )}>{fmtNum(beta, 3)}</td>
                    <td className="py-1 pr-2 text-terminal-muted">{reading}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data.weights ? (
            <details className="text-[11px] text-terminal-muted">
              <summary className="cursor-pointer hover:text-terminal-amber">
                {t("p.factors.weights_count", { count: Object.keys(data.weights).length })}
              </summary>
              <table className="mt-1 w-full tabular">
                <tbody>
                  {Object.entries(data.weights)
                    .sort((a, b) => b[1] - a[1])
                    .map(([sym, w]) => (
                      <tr key={sym} className="border-t border-terminal-border/40">
                        <td className="py-0.5 pr-2 font-bold text-terminal-amber">{sym}</td>
                        <td className="py-0.5 text-right">{fmtPct(w)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </details>
          ) : null}
          {data.message ? (
            <div className="border border-terminal-amber/40 bg-terminal-amber/5 px-2 py-1 text-[11px] text-terminal-amber">
              ⚠ {data.message}
            </div>
          ) : null}
          <p className="text-[10px] leading-relaxed text-terminal-muted">
            {t("p.factors.footer")}
          </p>
        </div>
      )}
    </Panel>
  );
}

function Stat({ label, value, accent }) {
  const cls =
    accent === "green" ? "text-terminal-green"
    : accent === "red" ? "text-terminal-red"
    : "text-terminal-text";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-terminal-muted">{label}</div>
      <div className={`text-base font-bold ${cls}`}>{value}</div>
    </div>
  );
}

// Plain-English readings stay in English — they're a numeric narration that
// downstream advisor prompts also consume verbatim. Translating these would
// also require translating the regex hooks downstream.
function readBeta(key, beta) {
  if (beta == null) return "";
  const abs = Math.abs(beta);
  const intensity = abs > 0.5 ? "strongly" : abs > 0.2 ? "moderately" : abs > 0.05 ? "slightly" : "near zero —";
  if (key === "mkt_rf") {
    if (abs <= 0.05) return "market-neutral";
    return beta > 0 ? `${intensity} long the market` : `${intensity} short the market`;
  }
  if (key === "smb") return beta > 0 ? `${intensity} small-cap tilt` : `${intensity} large-cap tilt`;
  if (key === "hml") return beta > 0 ? `${intensity} value tilt` : `${intensity} growth tilt`;
  if (key === "rmw") return beta > 0 ? `${intensity} profitable-firm tilt` : `${intensity} unprofitable-firm tilt`;
  if (key === "cma") return beta > 0 ? `${intensity} conservative-investment tilt` : `${intensity} aggressive-investment tilt`;
  if (key === "mom") return beta > 0 ? `${intensity} momentum tilt` : `${intensity} reversal tilt`;
  return "";
}
