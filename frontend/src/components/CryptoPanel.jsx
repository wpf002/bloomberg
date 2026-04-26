import clsx from "clsx";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD"];

function fmt(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export default function CryptoPanel() {
  const { t } = useTranslation();
  const { data, error, loading } = usePolling(
    () => api.crypto(SYMBOLS),
    20_000,
    []
  );

  return (
    <Panel title={t("panels.crypto")} accent="blue">
      {loading && !data ? (
        <div className="text-terminal-muted">{t("p.crypto.loading")}</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (
        <table className="w-full text-xs tabular">
          <thead>
            <tr className="text-left text-terminal-muted">
              <th className="py-1 pr-2">{t("p.crypto.cols.pair")}</th>
              <th className="py-1 pr-2 text-right">{t("p.crypto.cols.price")}</th>
              <th className="py-1 text-right">{t("p.crypto.cols.chg24h")}</th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((c) => (
              <tr key={c.symbol} className="border-t border-terminal-border/60">
                <td className="py-1 pr-2 font-bold text-terminal-blue">{c.symbol}</td>
                <td className="py-1 pr-2 text-right">{fmt(c.price)}</td>
                <td
                  className={clsx(
                    "py-1 text-right",
                    c.change_percent_24h >= 0
                      ? "text-terminal-green"
                      : "text-terminal-red"
                  )}
                >
                  {c.change_percent_24h >= 0 ? "+" : ""}
                  {fmt(c.change_percent_24h)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
