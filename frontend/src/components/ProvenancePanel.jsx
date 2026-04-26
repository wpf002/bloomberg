import { useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const FRESH_THRESHOLD_S = 60;
const STALE_THRESHOLD_S = 600;

const SNAP_KINDS = [
  { id: "regime",    label: "Regime" },
  { id: "fragility", label: "Fragility" },
  { id: "rotation",  label: "Rotation" },
];

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

// Compact two-line "Apr 26 · 19:11:24" rendering for the captured-at column.
// Avoids the wrapped ISO timestamp the panel was showing before.
function fmtCompactTime(iso) {
  if (!iso) return { date: "—", time: "" };
  const d = new Date(iso);
  return {
    date: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    time: d.toLocaleTimeString(undefined, { hour12: false }),
  };
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

// Render a snapshot output JSON as a key/value table. Falls back to the
// raw string when the payload doesn't look like an object (or contains
// nested arrays we'd rather just print verbatim).
//
// The value cell uses min-w-0 + break-all so a long raw JSON blob (or a
// list of contributing factors) wraps within the card instead of pushing
// the right border off-screen.
function SnapshotOutput({ output }) {
  if (output == null) return <span className="text-terminal-muted">—</span>;
  if (typeof output === "string") {
    return (
      <pre className="whitespace-pre-wrap break-all font-mono text-[10px] leading-snug text-terminal-text">
        {output}
      </pre>
    );
  }
  if (typeof output !== "object") return <span>{String(output)}</span>;

  const entries = Object.entries(output);
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[11px] tabular">
      {entries.map(([k, v]) => (
        <SnapshotRow key={k} k={k} v={v} />
      ))}
    </div>
  );
}

function SnapshotRow({ k, v }) {
  const formatted = formatSnapshotValue(v);
  return (
    <>
      <div className="text-[10px] uppercase tracking-widest text-terminal-muted whitespace-nowrap">
        {k}
      </div>
      <div className="min-w-0 break-words text-terminal-text">{formatted}</div>
    </>
  );
}

function formatSnapshotValue(v) {
  if (v == null) return "—";
  if (Array.isArray(v)) {
    if (v.length === 0) return "[]";
    if (v.every((x) => typeof x === "string" || typeof x === "number")) {
      return v.join(" · ");
    }
    return (
      <span className="text-terminal-muted">
        [{v.length} items]
      </span>
    );
  }
  if (typeof v === "object") {
    // Long raw JSON blobs need explicit break-all so they don't shoot
    // past the card edge on a single unbroken character run.
    return (
      <span className="break-all font-mono text-[10px] text-terminal-muted">
        {JSON.stringify(v)}
      </span>
    );
  }
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(4);
  }
  return String(v);
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
      title={t("panels.provenance")}
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
            {t("p.provenance.tabs.records")}
          </button>
          <button
            onClick={() => setTab("audit")}
            className={tab === "audit" ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
          >
            {t("p.provenance.tabs.audit")}
          </button>
          <button
            onClick={() => setTab("snapshots")}
            className={tab === "snapshots" ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
          >
            {t("p.provenance.tabs.snap")}
          </button>
        </div>
      }
    >
      <div className="mb-2 text-[10px] uppercase tracking-widest text-terminal-muted">
        {t("p.provenance.symbol")} <span className="text-terminal-amber">{symbol || "—"}</span>
        {tab === "records" ? (
          <>
            {" · "}{t("p.provenance.records", { n: meta.count })}
            {" · "}{t("p.provenance.sources")}{" "}
            {Object.entries(meta.sources).map(([s, c]) => (
              <span key={s} className="ml-1 text-terminal-blue">
                {s}({c})
              </span>
            ))}
          </>
        ) : null}
      </div>

      {loading && tab === "records" ? (
        <div className="text-terminal-muted">{t("p.common.loading")}</div>
      ) : error ? (
        <div className="text-terminal-red">{error}</div>
      ) : tab === "records" ? (
        <table className="w-full text-[11px] leading-tight">
          <thead className="text-terminal-muted">
            <tr>
              <th className="text-left">{t("p.provenance.cols_r.source")}</th>
              <th className="text-left">{t("p.provenance.cols_r.series")}</th>
              <th className="text-right">{t("p.provenance.cols_r.value")}</th>
              <th className="text-left pl-2">{t("p.provenance.cols_r.ts")}</th>
              <th className="text-left pl-2">{t("p.provenance.cols_r.ingested")}</th>
            </tr>
          </thead>
          <tbody>
            {records.length === 0 ? (
              <tr>
                <td colSpan="5" className="py-2 text-terminal-muted">
                  {t("p.provenance.records_empty")}
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
                <th className="text-left">{t("p.provenance.cols_a.source")}</th>
                <th className="text-left">{t("p.provenance.cols_a.symbol")}</th>
                <th className="text-left">{t("p.provenance.cols_a.endpoint")}</th>
                <th className="text-left pl-2">{t("p.provenance.cols_a.user")}</th>
                <th className="text-left pl-2">{t("p.provenance.cols_a.ingested")}</th>
              </tr>
            </thead>
            <tbody>
              {audit.rows.length === 0 ? (
                <tr>
                  <td colSpan="5" className="py-2 text-terminal-muted">
                    {t("p.provenance.audit_empty")}
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
          <div className="mb-2 flex gap-1 text-[10px] uppercase tracking-widest">
            {SNAP_KINDS.map((k) => (
              <button
                key={k.id}
                onClick={() => setSnapKind(k.id)}
                className={
                  snapKind === k.id
                    ? "border border-terminal-amber px-2 py-0.5 text-terminal-amber"
                    : "border border-terminal-border px-2 py-0.5 text-terminal-muted hover:text-terminal-text"
                }
              >
                {k.label}
              </button>
            ))}
          </div>
          {snapshots.length === 0 ? (
            <div className="py-3 text-[11px] text-terminal-muted">
              {t("p.provenance.snap_empty")}
            </div>
          ) : (
            <ul className="space-y-2">
              {snapshots.map((r, i) => {
                const ts = fmtCompactTime(r.captured_at);
                return (
                  <li
                    key={i}
                    className="border border-terminal-border/40 bg-terminal-panelAlt/40 px-2 py-1.5"
                  >
                    <div className="mb-1 flex items-baseline justify-between text-[10px] uppercase tracking-widest text-terminal-muted">
                      <span>
                        <span className="text-terminal-amber">{ts.date}</span>{" "}
                        <span className="tabular text-terminal-text">{ts.time}</span>
                      </span>
                      <span className="text-terminal-blue">{r.inputs_hash || "—"}</span>
                    </div>
                    <SnapshotOutput output={r.output} />
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}
