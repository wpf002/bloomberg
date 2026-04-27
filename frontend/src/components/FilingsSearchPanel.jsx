import { useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

function HighlightedText({ html, className }) {
  if (!html) return null;
  const parts = String(html).split(/(<mark>.*?<\/mark>)/g);
  return (
    <span className={className}>
      {parts.map((part, i) => {
        const m = part.match(/^<mark>(.*?)<\/mark>$/);
        if (m) {
          return (
            <mark key={i} className="bg-terminal-amber/30 text-terminal-amber">
              {m[1]}
            </mark>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}

export default function FilingsSearchPanel({ symbol }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [filterToActive, setFilterToActive] = useState(false);
  const [esgOnly, setEsgOnly] = useState(false);
  const [hits, setHits] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [indexing, setIndexing] = useState(false);
  const [indexResult, setIndexResult] = useState(null);

  // Reset every panel-local piece of state when the active symbol
  // changes, so leftover hits / errors / index results from the
  // previous symbol don't bleed into the new view.
  useEffect(() => {
    setQuery("");
    setHits(null);
    setError(null);
    setIndexResult(null);
    setLoading(false);
    setIndexing(false);
  }, [symbol]);

  const runSearch = async (e) => {
    e?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = esgOnly
        ? await api.filingsSearchEsg(query, {
            symbol: filterToActive ? symbol : undefined,
          })
        : await api.filingsSearch(query, {
            symbol: filterToActive ? symbol : undefined,
          });
      setHits(data?.hits || []);
    } catch (err) {
      setError(err.detail || err.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  const reindex = async (fullText) => {
    if (!symbol) return;
    setIndexing(true);
    setIndexResult(null);
    setError(null);
    try {
      const data = await api.indexFilings(symbol, { fullText, limit: 10 });
      setIndexResult(data);
    } catch (err) {
      setError(err.detail || err.message || String(err));
    } finally {
      setIndexing(false);
    }
  };

  return (
    <Panel
      title={t("p.search.title", { sym: symbol ?? "" })}
      accent="blue"
      actions={
        <span className="text-terminal-muted">
          {hits?.length != null ? t("p.search.hits", { count: hits.length }) : ""}
        </span>
      }
    >
      <div className="flex h-full min-h-0 flex-col gap-2">
        <form onSubmit={runSearch} className="flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("p.search.placeholder")}
            className="flex-1 border border-terminal-border bg-terminal-bg px-2 py-1 text-xs text-terminal-text focus:border-terminal-amber focus:outline-none"
          />
          <label className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-terminal-muted">
            <input
              type="checkbox"
              checked={filterToActive}
              onChange={(e) => setFilterToActive(e.target.checked)}
            />
            {t("p.search.limit_to", { sym: symbol })}
          </label>
          <label
            className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-terminal-muted"
            title={t("p.search.esg_title")}
          >
            <input
              type="checkbox"
              checked={esgOnly}
              onChange={(e) => setEsgOnly(e.target.checked)}
            />
            {t("p.search.esg_only")}
          </label>
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="border border-terminal-amber px-3 py-0.5 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
          >
            {loading ? t("p.common.searching") : t("p.common.search")}
          </button>
        </form>
        <div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-widest text-terminal-muted">
          <span>{t("p.search.index_label")}</span>
          <button
            onClick={() => reindex(false)}
            disabled={indexing || !symbol}
            className="border border-terminal-border/60 px-2 py-0.5 hover:border-terminal-amber hover:text-terminal-amber disabled:opacity-50"
          >
            {indexing ? "…" : t("p.search.index_meta", { sym: symbol ?? "—" })}
          </button>
          <button
            onClick={() => reindex(true)}
            disabled={indexing || !symbol}
            className="border border-terminal-border/60 px-2 py-0.5 hover:border-terminal-amber hover:text-terminal-amber disabled:opacity-50"
          >
            {indexing ? "…" : t("p.search.index_full", { sym: symbol ?? "—" })}
          </button>
          {indexResult ? (
            <span className="text-terminal-green">
              {t("p.search.indexed", { indexed: indexResult.indexed, bodies: indexResult.bodies_indexed })}
            </span>
          ) : null}
          {error ? <span className="text-terminal-red">{error}</span> : null}
        </div>
        <div className="min-h-0 flex-1 overflow-auto border border-terminal-border bg-terminal-bg">
          {hits === null ? (
            <div className="p-3 text-xs text-terminal-muted">{t("p.search.empty")}</div>
          ) : hits.length === 0 ? (
            <div className="p-3 text-xs text-terminal-muted">{t("p.search.none")}</div>
          ) : (
            <ul className="divide-y divide-terminal-border/60">
              {hits.map((h) => {
                const fmt = h._formatted || {};
                return (
                  <li key={h.id} className="p-2">
                    <a
                      href={h.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="block hover:bg-terminal-panelAlt"
                    >
                      <div className="flex items-baseline gap-2 text-[10px] uppercase tracking-wider text-terminal-muted">
                        <span className="font-bold text-terminal-amber">{h.form_type}</span>
                        <span>{h.symbol}</span>
                        <span>{h.filed_at?.slice(0, 10)}</span>
                        <span className="ml-auto text-terminal-muted/60">
                          {h.accession_number}
                        </span>
                      </div>
                      <HighlightedText
                        html={fmt.headline || h.headline}
                        className="block text-xs text-terminal-text"
                      />
                      {fmt.body || h.snippet ? (
                        <HighlightedText
                          html={fmt.body || h.snippet}
                          className="mt-1 block text-[11px] text-terminal-muted"
                        />
                      ) : null}
                    </a>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  );
}
