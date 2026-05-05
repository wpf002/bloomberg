import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import useStream from "../hooks/useStream.js";
import { useTranslation } from "../i18n/index.jsx";
import { api } from "../lib/api.js";

function formatNumber(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

const FLASH_MS = 600;

export default function Watchlist({ symbols, activeSymbol, onSelect, onRemove, onAdd }) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");

  const submitAdd = (e) => {
    e?.preventDefault?.();
    if (!onAdd) return;
    const sym = (draft || "").trim().toUpperCase();
    if (!sym) return;
    onAdd(sym);
    setDraft("");
  };
  const { data, error, loading } = usePolling(
    () => api.quotes(symbols),
    15000,
    [symbols.join(",")]
  );

  // Local overlay map: streaming ticks layer on top of the polled snapshot.
  const [stream, setStream] = useState({}); // { SYM: { price, ts } }
  const flashRef = useRef({}); // SYM -> "up" | "down" | undefined

  const wsPath = useMemo(
    () => `/api/ws/quotes?symbols=${encodeURIComponent(symbols.join(","))}`,
    [symbols.join(",")]
  );

  const { status: wsStatus } = useStream(wsPath, {
    onMessage: (msg) => {
      if (!msg?.symbol || msg.type === "ready") return;
      const sym = msg.symbol;
      const next = msg.price;
      if (next == null) return;
      setStream((prev) => {
        const previous = prev[sym]?.price;
        if (previous != null && next !== previous) {
          flashRef.current[sym] = next > previous ? "up" : "down";
          setTimeout(() => {
            delete flashRef.current[sym];
            setStream((p) => ({ ...p })); // force re-render
          }, FLASH_MS);
        }
        return { ...prev, [sym]: { price: next, ts: msg.timestamp } };
      });
    },
  });

  return (
    <Panel
      title={t("panels.watchlist")}
      accent="amber"
      actions={
        <span className="text-terminal-muted">
          {t("watchlist.syms", { count: symbols.length })} ·{" "}
          <span
            className={
              wsStatus === "open"
                ? "text-terminal-green"
                : wsStatus === "error"
                ? "text-terminal-red"
                : "text-terminal-muted"
            }
          >
            ws {wsStatus === "open" ? t("watchlist.wsOpen") : wsStatus === "error" ? t("watchlist.wsError") : t("watchlist.wsClosed")}
          </span>
        </span>
      }
    >
      {loading && !data ? (
        <div className="text-terminal-muted">{t("watchlist.loading")}</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (
        <table className="w-full text-xs tabular">
          <thead>
            <tr className="text-left text-terminal-muted">
              <th className="py-1 pr-2">{t("watchlist.columns.sym")}</th>
              <th className="py-1 pr-2 text-right">{t("watchlist.columns.last")}</th>
              <th className="py-1 pr-2 text-right">{t("watchlist.columns.chg")}</th>
              <th className="py-1 pr-2 text-right">{t("watchlist.columns.pct")}</th>
              <th className="py-1 pr-2 text-right">{t("watchlist.columns.vol")}</th>
              <th className="py-1 w-6"></th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((q) => {
              const live = stream[q.symbol]?.price;
              const price = live ?? q.price;
              const baseClose = q.previous_close ?? q.price - q.change;
              const change = live != null ? live - baseClose : q.change;
              const pct =
                baseClose && live != null
                  ? (change / baseClose) * 100
                  : q.change_percent;
              const positive = change >= 0;
              const active = q.symbol === activeSymbol;
              const flash = flashRef.current[q.symbol];
              return (
                <tr
                  key={q.symbol}
                  onClick={() => onSelect?.(q.symbol)}
                  className={clsx(
                    "group cursor-pointer border-t border-terminal-border/60 hover:bg-terminal-panelAlt transition-colors",
                    active && "bg-terminal-panelAlt",
                    flash === "up" && "bg-terminal-green/10",
                    flash === "down" && "bg-terminal-red/10"
                  )}
                >
                  <td className="py-1 pr-2 font-bold text-terminal-amber">{q.symbol}</td>
                  <td className="py-1 pr-2 text-right">{formatNumber(price)}</td>
                  <td
                    className={clsx(
                      "py-1 pr-2 text-right",
                      positive ? "text-terminal-green" : "text-terminal-red"
                    )}
                  >
                    {positive ? "+" : ""}
                    {formatNumber(change)}
                  </td>
                  <td
                    className={clsx(
                      "py-1 pr-2 text-right",
                      positive ? "text-terminal-green" : "text-terminal-red"
                    )}
                  >
                    {positive ? "+" : ""}
                    {formatNumber(pct)}%
                  </td>
                  <td className="py-1 pr-2 text-right text-terminal-muted">
                    {q.volume ? q.volume.toLocaleString() : "--"}
                  </td>
                  <td className="py-1 text-right">
                    {onRemove ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onRemove(q.symbol);
                        }}
                        className="text-terminal-muted opacity-0 group-hover:opacity-100 hover:text-terminal-red"
                        title={t("p.watchlist.remove_title", { sym: q.symbol })}
                      >
                        ✕
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
            {(() => {
              // Symbols the user has but the backend couldn't quote (e.g.
              // they typo'd a chip name on a stale build). Render them
              // dimmed with a remove button so cleanup is one click away.
              const returned = new Set((data || []).map((q) => q.symbol));
              const missing = symbols.filter((s) => !returned.has(s));
              return missing.map((sym) => (
                <tr key={`missing-${sym}`} className="border-t border-terminal-border/60">
                  <td className="py-1 pr-2 font-bold text-terminal-muted line-through">{sym}</td>
                  <td colSpan={4} className="py-1 pr-2 text-right text-[11px] text-terminal-muted/80">
                    {t("p.watchlist.no_data_label")}
                  </td>
                  <td className="py-1 text-right">
                    {onRemove ? (
                      <button
                        onClick={() => onRemove(sym)}
                        className="text-terminal-red hover:underline"
                        title={t("p.watchlist.remove_title", { sym })}
                      >
                        ✕
                      </button>
                    ) : null}
                  </td>
                </tr>
              ));
            })()}
          </tbody>
        </table>
      )}
      {onAdd ? (
        <form onSubmit={submitAdd} className="mt-2 flex items-center gap-1 border-t border-terminal-border/60 pt-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value.toUpperCase())}
            placeholder={t("p.watchlist.add_placeholder")}
            className="flex-1 bg-transparent border border-terminal-border/60 px-2 py-1 text-xs uppercase tabular text-terminal-text outline-none focus:border-terminal-amber"
            maxLength={20}
          />
          <button
            type="submit"
            className="px-2 py-1 text-[10px] uppercase tracking-wider bg-terminal-amber text-black hover:opacity-90"
            title={t("p.watchlist.add_title")}
          >
            +
          </button>
        </form>
      ) : null}
    </Panel>
  );
}
