import { useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const FRESH_THRESHOLD_S = 60;
const STALE_THRESHOLD_S = 600;

function freshnessDot(ingestedAt) {
  if (!ingestedAt) return { color: "bg-terminal-muted", label: "n/a" };
  const ageS = (Date.now() - new Date(ingestedAt).getTime()) / 1000;
  if (ageS < FRESH_THRESHOLD_S) return { color: "bg-terminal-green", label: `${Math.round(ageS)}s` };
  if (ageS < STALE_THRESHOLD_S) return { color: "bg-terminal-amber", label: `${Math.round(ageS / 60)}m` };
  if (ageS < 86400) return { color: "bg-terminal-red", label: `${Math.round(ageS / 3600)}h` };
  return { color: "bg-terminal-red", label: `${Math.round(ageS / 86400)}d` };
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toISOString().slice(0, 19).replace("T", " ")}Z`;
}

function fmtValue(v, unit) {
  if (v == null) return "—";
  const num = Number(v);
  if (Number.isNaN(num)) return String(v);
  const formatted =
    Math.abs(num) >= 1000
      ? num.toLocaleString(undefined, { maximumFractionDigits: 2 })
      : num.toFixed(4);
  return unit ? `${formatted} ${unit}` : formatted;
}

export default function ProvenancePanel({ symbol }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState("records"); // records | audit | snapshots
  const [records, setRecords] = useState([]);
  const [audit, setAudit] = useState({ rows: [], note: null });
  const [snapshots, setSnapshots] = useState([]);
  const [snapKind, setSnapKind] = useState("regime");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState({ sources: {}, count: 0 });

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .provenance(symbol, { limit: 100 })
      .then((data) => {
        if (cancelled) return;
        setRecords(data.records || []);
        setMeta({ sources: data.sources || {}, count: data.count || 0 });
      })
      .catch((err) => {
        if (!cancelled) setError(err.detail || err.message);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  useEffect(() => {
    if (tab !== "audit" || !symbol) return;
    let cancelled = false;
    api
      .audit(symbol, { limit: 50 })
      .then((data) => !cancelled && setAudit({ rows: data.rows || [], note: data.note || null }))
      .catch((err) => !cancelled && setAudit({ rows: [], note: err.detail || err.message }));
    return () => {
      cancelled = true;
    };
  }, [tab, symbol]);

  useEffect(() => {
    if (tab !== "snapshots") return;
    let cancelled = false;
    api
      .intelSnapshots(snapKind, 30)
      .then((data) => !cancelled && setSnapshots(data.rows || []))
      .catch(() => !cancelled && setSnapshots([]));
    return () => {
      cancelled = true;
    };
  }, [tab, snapKind]);

  const newest = records[0];
  const dot = freshnessDot(newest?.ingested_at);

  return (
    <Panel
      title={t("panels.provenance") || "Provenance"}
      accent="blue"
      actions={
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest">
          <span className="flex items-center gap-1 text-terminal-muted">
            <span className={`inline-block h-2 w-2 rounded-full ${dot.color}`}></span>
            {dot.label}
          </span>
          <span className="text-terminal-muted">·</span>
          <button
            onClick={() => setTab("records")}
            className={tab === "records" ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
          >
            REC
          </button>
          <button
            onClick={() => setTab("audit")}
            className={tab === "audit" ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
          >
            AUDIT
          </button>
          <button
            onClick={() => setTab("snapshots")}
            className={tab === "snapshots" ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
          >
            SNAP
          </button>
        </div>
      }
    >
      <div className="mb-2 text-[10px] uppercase tracking-widest text-terminal-muted">
        Symbol: <span className="text-terminal-amber">{symbol || "—"}</span>
        {tab === "records" ? (
          <>
            {" · "}records: {meta.count}
            {" · "}sources:{" "}
            {Object.entries(meta.sources).map(([s, c]) => (
              <span key={s} className="ml-1 text-terminal-blue">
                {s}({c})
              </span>
            ))}
          </>
        ) : null}
      </div>

      {loading && tab === "records" ? (
        <div className="text-terminal-muted">Loading…</div>
      ) : error ? (
        <div className="text-terminal-red">{error}</div>
      ) : tab === "records" ? (
        <table className="w-full text-[11px] leading-tight">
          <thead className="text-terminal-muted">
            <tr>
              <th className="text-left">SOURCE</th>
              <th className="text-left">SERIES</th>
              <th className="text-right">VALUE</th>
              <th className="text-left pl-2">TIMESTAMP</th>
              <th className="text-left pl-2">INGESTED</th>
            </tr>
          </thead>
          <tbody>
            {records.length === 0 ? (
              <tr>
                <td colSpan="5" className="py-2 text-terminal-muted">
                  No normalized records yet — interact with another panel for this symbol.
                </td>
              </tr>
            ) : (
              records.map((r, i) => (
                <tr key={i} className="border-b border-terminal-border/30">
                  <td className="text-terminal-blue">{r.source}</td>
                  <td className="text-terminal-text">{r.series_id}</td>
                  <td className="text-right text-terminal-amber">{fmtValue(r.value, r.unit)}</td>
                  <td className="pl-2 text-terminal-muted">{fmtTime(r.timestamp)}</td>
                  <td className="pl-2 text-terminal-muted">{fmtTime(r.ingested_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      ) : tab === "audit" ? (
        <div>
          {audit.note ? (
            <div className="mb-2 text-[10px] text-terminal-muted">{audit.note}</div>
          ) : null}
          <table className="w-full text-[11px] leading-tight">
            <thead className="text-terminal-muted">
              <tr>
                <th className="text-left">SOURCE</th>
                <th className="text-left">SYMBOL</th>
                <th className="text-left">ENDPOINT</th>
                <th className="text-left pl-2">USER</th>
                <th className="text-left pl-2">INGESTED</th>
              </tr>
            </thead>
            <tbody>
              {audit.rows.length === 0 ? (
                <tr>
                  <td colSpan="5" className="py-2 text-terminal-muted">
                    No audit events. TimescaleDB audit log is empty or unavailable.
                  </td>
                </tr>
              ) : (
                audit.rows.map((r, i) => (
                  <tr key={i} className="border-b border-terminal-border/30">
                    <td className="text-terminal-blue">{r.source}</td>
                    <td className="text-terminal-text">{r.symbol}</td>
                    <td className="text-terminal-muted">{r.endpoint_called || "—"}</td>
                    <td className="pl-2 text-terminal-muted">{r.user_id ?? "—"}</td>
                    <td className="pl-2 text-terminal-muted">{fmtTime(r.ingested_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div>
          <div className="mb-2 flex gap-2 text-[10px] uppercase tracking-widest">
            {["regime", "fragility", "rotation"].map((k) => (
              <button
                key={k}
                onClick={() => setSnapKind(k)}
                className={snapKind === k ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
              >
                {k}
              </button>
            ))}
          </div>
          <table className="w-full text-[11px] leading-tight">
            <thead className="text-terminal-muted">
              <tr>
                <th className="text-left">CAPTURED</th>
                <th className="text-left pl-2">OUTPUT</th>
                <th className="text-left pl-2">INPUTS HASH</th>
              </tr>
            </thead>
            <tbody>
              {snapshots.length === 0 ? (
                <tr>
                  <td colSpan="3" className="py-2 text-terminal-muted">
                    No intelligence snapshots persisted yet.
                  </td>
                </tr>
              ) : (
                snapshots.map((r, i) => (
                  <tr key={i} className="border-b border-terminal-border/30">
                    <td className="text-terminal-muted">{fmtTime(r.captured_at)}</td>
                    <td className="pl-2 text-terminal-text">{JSON.stringify(r.output)}</td>
                    <td className="pl-2 text-terminal-blue">{r.inputs_hash || "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
