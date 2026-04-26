import clsx from "clsx";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

function fmt(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

// Short, never-wrap display names for the tile grid. Full label stays in
// the tooltip so nothing is lost.
const SHORT = {
  SPY: "S&P",
  QQQ: "NDX",
  DIA: "DOW",
  IWM: "RUT",
  VIXY: "VIX",
  TLT: "TSY 20Y",
  UUP: "DXY",
  USO: "OIL",
  GLD: "GOLD",
  "BTC-USD": "BTC",
  "ETH-USD": "ETH",
};

export default function MarketOverview({ onSelect }) {
  const { t } = useTranslation();
  const { data, error, loading } = usePolling(() => api.overview(), 30_000, []);

  return (
    <Panel title={t("panels.markets")} accent="amber">
      {loading && !data ? (
        <div className="text-terminal-muted">{t("p.markets.loading")}</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (
        <div className="grid grid-cols-3 gap-2 text-xs tabular">
          {(data?.tiles || []).map((tile) => {
            const positive = tile.change >= 0;
            const short = SHORT[tile.symbol] ?? tile.symbol;
            return (
              <button
                key={tile.symbol}
                onClick={() => onSelect?.(tile.symbol)}
                title={`${tile.label} · ${tile.symbol}`}
                className="group min-w-0 rounded border border-terminal-border/40 px-2 py-1 text-left hover:border-terminal-amber/80"
              >
                <div className="truncate whitespace-nowrap text-[10px] uppercase tracking-wider text-terminal-amber">
                  {short}
                </div>
                <div className="truncate whitespace-nowrap text-terminal-text">
                  {fmt(tile.price)}
                </div>
                <div
                  className={clsx(
                    "truncate whitespace-nowrap text-[11px]",
                    positive ? "text-terminal-green" : "text-terminal-red"
                  )}
                >
                  {positive ? "+" : ""}
                  {fmt(tile.change_percent)}%
                </div>
              </button>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
