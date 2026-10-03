import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

// Starting points that mirror how traders actually screen, so the panel is
// useful before anyone builds a filter by hand.
const PRESETS = [
  {
    key: "oversold",
    label: "Oversold",
    filters: [
      { field: "rsi14", op: "lt", value: 30 },
      { field: "dollar_volume", op: "gt", value: 5_000_000 },
    ],
    sort: "rsi14",
    desc: false,
  },
  {
    key: "momentum",
    label: "Momentum",
    filters: [
      { field: "price_vs_sma200", op: "gt", value: 0 },
      { field: "ret_3m", op: "gt", value: 20 },
      { field: "dollar_volume", op: "gt", value: 10_000_000 },
    ],
    sort: "ret_3m",
  },
  {
    key: "unusual_volume",
    label: "Unusual volume",
    filters: [
      { field: "rel_volume", op: "gt", value: 3 },
      { field: "price", op: "gt", value: 2 },
    ],
    sort: "rel_volume",
  },
  {
    key: "near_highs",
    label: "Near 52w high",
    filters: [
      { field: "pct_off_52w_high", op: "gt", value: -3 },
      { field: "dollar_volume", op: "gt", value: 5_000_000 },
    ],
    sort: "dollar_volume",
  },
  {
    key: "gappers",
    label: "Gappers",
    filters: [
      { field: "gap_pct", op: "gt", value: 4 },
      { field: "dollar_volume", op: "gt", value: 1_000_000 },
    ],
    sort: "gap_pct",
  },
];

// Columns shown in the results grid. Kept short on purpose — the full metric
// set is available through the filter builder and the SQL workbench.
const COLUMNS = [
  { key: "price", label: "Price", unit: "usd" },
  { key: "change_pct", label: "Chg%", unit: "pct" },
  { key: "rel_volume", label: "RVol", unit: "x" },
  { key: "rsi14", label: "RSI", unit: "num" },
  { key: "pct_off_52w_high", label: "Off 52wH", unit: "pct" },
  { key: "price_vs_sma200", label: "vs200", unit: "pct" },
  { key: "ret_1m", label: "1m", unit: "pct" },
  { key: "dollar_volume", label: "$Vol", unit: "usd" },
];

function fmt(value, unit) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (unit === "pct") return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
  if (unit === "x") return `${n.toFixed(2)}x`;
  if (unit === "usd") {
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    return `$${n.toFixed(2)}`;
  }
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  return n.toFixed(2);
}

function toneFor(key, value) {
  if (value === null || value === undefined) return "text-terminal-text";
  if (!["change_pct", "ret_1m", "price_vs_sma200", "gap_pct"].includes(key)) {
    return "text-terminal-text";
  }
  return value >= 0 ? "text-terminal-green" : "text-terminal-red";
}

export default function ScreenerPanel({ onSelectSymbol }) {
  const [fields, setFields] = useState([]);
  const [filters, setFilters] = useState(PRESETS[0].filters);
  const [sort, setSort] = useState(PRESETS[0].sort);
  const [desc, setDesc] = useState(PRESETS[0].desc !== false);
  const [activePreset, setActivePreset] = useState(PRESETS[0].key);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fieldMap = useMemo(
    () => Object.fromEntries(fields.map((f) => [f.key, f])),
    [fields]
  );

  useEffect(() => {
    let active = true;
    api
      .screenerFields()
      .then((data) => {
        if (active) setFields(Array.isArray(data) ? data : []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const run = async (next = {}) => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.screenerRun({
        filters: next.filters ?? filters,
        sort: next.sort ?? sort,
        desc: next.desc ?? desc,
        limit: 100,
      });
      setResult(data);
    } catch (err) {
      setError(err?.message || "screen failed");
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  // Run the default preset once the panel mounts.
  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyPreset = (preset) => {
    setActivePreset(preset.key);
    setFilters(preset.filters);
    setSort(preset.sort);
    const d = preset.desc !== false;
    setDesc(d);
    run({ filters: preset.filters, sort: preset.sort, desc: d });
  };

  const updateFilter = (idx, patch) => {
    const next = filters.map((f, i) => (i === idx ? { ...f, ...patch } : f));
    setFilters(next);
    setActivePreset(null);
  };

  const removeFilter = (idx) => {
    const next = filters.filter((_, i) => i !== idx);
    setFilters(next);
    setActivePreset(null);
    run({ filters: next });
  };

  const addFilter = () => {
    const used = new Set(filters.map((f) => f.field));
    const free = fields.find((f) => !used.has(f.key));
    if (!free) return;
    setFilters([...filters, { field: free.key, op: "gt", value: 0 }]);
    setActivePreset(null);
  };

  const refreshUniverse = async () => {
    setRefreshing(true);
    setError(null);
    try {
      await api.screenerRefresh();
      await run();
    } catch (err) {
      setError(err?.message || "refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const toggleSort = (key) => {
    const nextDesc = key === sort ? !desc : true;
    setSort(key);
    setDesc(nextDesc);
    run({ sort: key, desc: nextDesc });
  };

  return (
    <Panel title="EQS · Screener">
      <div className="flex flex-wrap gap-1">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => applyPreset(p)}
            className={clsx(
              "border px-2 py-0.5 text-[10px] uppercase tracking-wider",
              activePreset === p.key
                ? "border-terminal-amber text-terminal-amber"
                : "border-terminal-border text-terminal-muted hover:text-terminal-text"
            )}
          >
            {p.label}
          </button>
        ))}
        <span className="flex-1" />
        <button
          type="button"
          onClick={refreshUniverse}
          disabled={refreshing}
          title="Re-ingest daily bars for the full equity universe"
          className="border border-terminal-border px-2 py-0.5 text-[10px] uppercase tracking-wider text-terminal-muted hover:text-terminal-text disabled:opacity-50"
        >
          {refreshing ? "refreshing…" : "refresh universe"}
        </button>
      </div>

      <div className="mt-2 space-y-1">
        {filters.map((f, i) => (
          <div key={`${f.field}-${i}`} className="flex items-center gap-1 text-[11px]">
            <select
              value={f.field}
              onChange={(e) => updateFilter(i, { field: e.target.value })}
              className="min-w-0 flex-1 border border-terminal-border bg-terminal-panelAlt px-1 py-0.5 text-terminal-text"
            >
              {fields.map((opt) => (
                <option key={opt.key} value={opt.key}>
                  {opt.label}
                </option>
              ))}
            </select>
            <select
              value={f.op}
              onChange={(e) => updateFilter(i, { op: e.target.value })}
              className="border border-terminal-border bg-terminal-panelAlt px-1 py-0.5 text-terminal-text"
            >
              <option value="gt">&gt;</option>
              <option value="gte">&ge;</option>
              <option value="lt">&lt;</option>
              <option value="lte">&le;</option>
              <option value="eq">=</option>
            </select>
            <input
              type="number"
              value={f.value ?? 0}
              onChange={(e) => updateFilter(i, { value: Number(e.target.value) })}
              className="w-24 border border-terminal-border bg-terminal-panelAlt px-1 py-0.5 text-right text-terminal-text"
            />
            <span className="w-6 text-terminal-muted">
              {fieldMap[f.field]?.unit === "pct" ? "%" : ""}
            </span>
            <button
              type="button"
              onClick={() => removeFilter(i)}
              aria-label="Remove filter"
              className="px-1 text-terminal-muted hover:text-terminal-red"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="mt-1 flex gap-2">
        <button
          type="button"
          onClick={addFilter}
          className="text-[10px] uppercase tracking-wider text-terminal-muted hover:text-terminal-text"
        >
          + filter
        </button>
        <button
          type="button"
          onClick={() => run()}
          disabled={busy}
          className="border border-terminal-amber px-2 py-0.5 text-[10px] uppercase tracking-wider text-terminal-amber disabled:opacity-50"
        >
          {busy ? "running…" : "run"}
        </button>
      </div>

      {error ? (
        <div className="mt-2 text-[11px] text-terminal-red">{error}</div>
      ) : null}

      {result ? (
        <div className="mt-2">
          <div className="text-[10px] uppercase tracking-widest text-terminal-muted">
            {result.count} match{result.count === 1 ? "" : "es"} · {result.universe} symbols
          </div>
          <div className="mt-1 max-h-72 overflow-auto">
            <table className="w-full text-[11px] tabular-nums">
              <thead className="sticky top-0 bg-terminal-panel">
                <tr>
                  <th className="px-1 py-0.5 text-left text-[10px] uppercase tracking-wider text-terminal-muted">
                    Sym
                  </th>
                  {COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      onClick={() => toggleSort(c.key)}
                      className={clsx(
                        "cursor-pointer px-1 py-0.5 text-right text-[10px] uppercase tracking-wider",
                        sort === c.key ? "text-terminal-amber" : "text-terminal-muted"
                      )}
                    >
                      {c.label}
                      {sort === c.key ? (desc ? " ↓" : " ↑") : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row) => (
                  <tr
                    key={row.symbol}
                    onClick={() => onSelectSymbol?.(row.symbol)}
                    className="cursor-pointer border-b border-terminal-border/30 hover:bg-terminal-panelAlt"
                  >
                    <td className="px-1 py-0.5 font-bold text-terminal-amber">{row.symbol}</td>
                    {COLUMNS.map((c) => (
                      <td
                        key={c.key}
                        className={clsx("px-1 py-0.5 text-right", toneFor(c.key, row[c.key]))}
                      >
                        {fmt(row[c.key], c.unit)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {result.rows.length === 0 ? (
              <div className="py-3 text-center text-[11px] text-terminal-muted">
                No matches. Loosen a filter.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </Panel>
  );
}
