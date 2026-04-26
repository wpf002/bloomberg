import { useEffect, useState } from "react";
import clsx from "clsx";
import {
  Line,
  LineChart,
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

const ROOTS = [
  { id: "CL", label: "WTI Crude" },
  { id: "NG", label: "Nat Gas" },
];

function fmt(v, digits = 2) {
  if (v == null) return "--";
  return Number(v).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export default function FuturesPanel() {
  const { t } = useTranslation();
  const [root, setRoot] = useState("CL");
  const dashQ = usePolling(() => api.futuresDashboard(), 60_000, []);
  const [curve, setCurve] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError(null);
    api
      .futuresCurve(root)
      .then((data) => {
        if (active) setCurve(data);
      })
      .catch((err) => {
        if (active) setError(err?.detail || err?.message || String(err));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [root]);

  const dash = dashQ.data || [];
  const points = (curve?.contracts || []).map((c) => ({
    expiration: c.expiration,
    price: c.price,
    contract: c.contract_symbol,
  }));
  const front = curve?.front_month_price;

  return (
    <Panel
      title={t("p.futures.title")}
      accent="amber"
      actions={
        <span className="text-[10px] uppercase tracking-widest text-terminal-muted">
          {t("p.futures.contracts_meta", { label: curve?.label ?? "—", n: points.length })}
        </span>
      }
    >
      <div className="flex h-full flex-col">
        <div className="grid grid-cols-5 gap-1 text-xs">
          {dash.map((c) => (
            <div
              key={c.contract_symbol}
              className="border border-terminal-border bg-terminal-panelAlt p-1"
            >
              <div className="text-[10px] uppercase tracking-widest text-terminal-muted">
                {c.contract_symbol}
              </div>
              <div className="text-sm font-bold tabular text-terminal-text">
                {fmt(c.price)}
              </div>
              <div
                className={clsx(
                  "text-[11px] tabular",
                  (c.change ?? 0) >= 0 ? "text-terminal-green" : "text-terminal-red"
                )}
              >
                {(c.change ?? 0) >= 0 ? "+" : ""}
                {fmt(c.change_percent)}%
              </div>
            </div>
          ))}
        </div>

        <div className="mt-3 flex items-center gap-1 text-[10px] uppercase tracking-widest text-terminal-muted">
          <span>{t("p.futures.curve")}</span>
          {ROOTS.map((r) => (
            <button
              key={r.id}
              onClick={() => setRoot(r.id)}
              className={clsx(
                "border px-2 py-0.5",
                root === r.id
                  ? "border-terminal-amber text-terminal-amber"
                  : "border-terminal-border text-terminal-muted hover:text-terminal-text"
              )}
            >
              {r.id} {r.label}
            </button>
          ))}
        </div>

        {error ? (
          <div className="mt-2 text-xs text-terminal-red">{error}</div>
        ) : busy && !curve ? (
          <div className="mt-2 text-xs text-terminal-muted">{t("p.futures.loading")}</div>
        ) : points.length === 0 ? (
          <div className="mt-2 text-xs text-terminal-muted">
            {t("p.futures.empty", { root })}
          </div>
        ) : (
          <div className="mt-2 flex flex-1 min-h-0 flex-col">
            <div className="flex-1 min-h-[140px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <XAxis
                    dataKey="expiration"
                    tick={{ fontSize: 10, fill: "#888" }}
                    tickFormatter={(d) => (d ? String(d).slice(2, 7) : "")}
                  />
                  <YAxis tick={{ fontSize: 10, fill: "#888" }} domain={["auto", "auto"]} width={50} />
                  <Tooltip
                    contentStyle={{ background: "#111", border: "1px solid #333", fontSize: 11 }}
                    formatter={(value) => [fmt(value), "Price"]}
                  />
                  {front ? (
                    <ReferenceLine y={front} stroke="#ff9f1c" strokeDasharray="4 4" />
                  ) : null}
                  <Line type="monotone" dataKey="price" stroke="#ff9f1c" strokeWidth={2} dot={{ r: 2 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <table className="mt-2 w-full text-[11px] tabular">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-widest text-terminal-muted">
                  <th className="py-1 pr-2">{t("p.futures.cols.contract")}</th>
                  <th className="py-1 pr-2 text-right">{t("p.futures.cols.expiration")}</th>
                  <th className="py-1 pr-2 text-right">{t("p.futures.cols.price")}</th>
                  <th className="py-1 text-right">{t("p.futures.cols.chg")}</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={p.contract} className="border-t border-terminal-border/40">
                    <td className="py-1 pr-2 font-bold text-terminal-amber">{p.contract}</td>
                    <td className="py-1 pr-2 text-right text-terminal-muted">
                      {p.expiration ? p.expiration.slice(0, 7) : "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">{fmt(p.price)}</td>
                    <td className="py-1 text-right">
                      {(curve?.contracts || []).find((c) => c.contract_symbol === p.contract)
                        ?.change_percent != null
                        ? `${fmt(
                            (curve?.contracts || []).find((c) => c.contract_symbol === p.contract)
                              ?.change_percent
                          )}%`
                        : "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[10px] leading-relaxed text-terminal-muted">
              {t("p.futures.footer_pre")}
              <span className="text-terminal-amber">{t("p.futures.footer_up")}</span>
              {t("p.futures.footer_contango")}
              <span className="text-terminal-amber">{t("p.futures.footer_down")}</span>
              {t("p.futures.footer_back")}
            </p>
          </div>
        )}
      </div>
    </Panel>
  );
}
