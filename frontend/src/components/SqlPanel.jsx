import { useEffect, useMemo, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const PRESET_DEFS = [
  {
    key: "aapl_30",
    sql: "SELECT timestamp, close FROM bars WHERE symbol = 'AAPL' ORDER BY timestamp DESC LIMIT 30",
  },
  {
    key: "avg_vol",
    sql: "SELECT symbol, AVG(volume)::BIGINT AS avg_vol FROM bars GROUP BY symbol ORDER BY avg_vol DESC",
  },
  {
    key: "treas_10y",
    sql: "SELECT observation_date, value FROM macro WHERE series_id='DGS10' ORDER BY observation_date DESC LIMIT 250",
  },
  {
    key: "filings_form",
    sql: "SELECT symbol, form_type, COUNT(*) AS n FROM filings GROUP BY 1, 2 ORDER BY n DESC",
  },
];

const DEFAULT_QUERY = PRESET_DEFS[0].sql;

export default function SqlPanel() {
  const { t } = useTranslation();
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [tables, setTables] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const presets = useMemo(
    () => PRESET_DEFS.map((p) => ({ ...p, label: t(`p.sql.presets.${p.key}`) })),
    [t]
  );

  useEffect(() => {
    let active = true;
    api
      .sqlTables()
      .then((data) => {
        if (active) setTables(data?.tables || []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const runQuery = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.sqlQuery(query);
      setResult(data);
    } catch (err) {
      setError(err.detail || err.message || String(err));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runQuery();
    }
  };

  return (
    <Panel
      title={t("p.sql.title")}
      accent="amber"
      actions={
        <span className="text-terminal-muted">
          {tables.map((t2) => `${t2.name.toUpperCase()}(${t2.row_count})`).join(" · ") ||
            t("p.sql.no_tables")}
        </span>
      }
    >
      <div className="flex h-full min-h-0 flex-col gap-2">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">
          <div className="mb-1">Presets:</div>
          <div className="grid grid-cols-2 gap-1">
            {presets.map((p) => (
              <button
                key={p.key}
                onClick={() => setQuery(p.sql)}
                className="border border-terminal-border/60 px-2 py-0.5 text-left uppercase hover:border-terminal-amber hover:text-terminal-amber"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          spellCheck={false}
          rows={5}
          className="w-full resize-y border border-terminal-border bg-terminal-bg p-2 font-mono text-xs text-terminal-text focus:border-terminal-amber focus:outline-none"
          placeholder={t("p.sql.placeholder")}
        />
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-terminal-muted">
          <button
            onClick={runQuery}
            disabled={busy}
            className="border border-terminal-amber px-3 py-0.5 text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
          >
            {busy ? t("p.common.running") : t("p.sql.run")}
          </button>
          {result ? (
            <span>
              {t("p.sql.meta", { rows: result.row_count, ms: result.elapsed_ms })}
              {result.truncated ? t("p.sql.truncated") : ""}
            </span>
          ) : null}
          {error ? <span className="text-terminal-red">{error}</span> : null}
        </div>
        <div className="min-h-0 flex-1 overflow-auto border border-terminal-border bg-terminal-bg">
          {result?.rows?.length ? (
            <table className="w-full text-xs tabular">
              <thead className="sticky top-0 bg-terminal-panelAlt">
                <tr>
                  {result.columns.map((c) => (
                    <th
                      key={c}
                      className="border-b border-terminal-border px-2 py-1 text-left text-terminal-amber"
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr
                    key={i}
                    className="border-b border-terminal-border/40 hover:bg-terminal-panelAlt"
                  >
                    {result.columns.map((c) => (
                      <td
                        key={c}
                        className="px-2 py-1 align-top text-terminal-text"
                      >
                        {row[c] === null || row[c] === undefined ? (
                          <span className="text-terminal-muted/60">NULL</span>
                        ) : (
                          String(row[c])
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-3 text-xs text-terminal-muted">
              {busy ? t("p.common.running") : t("p.sql.empty")}
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}
