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

function signed(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${fmt(n, digits)}`;
}

function EmptyState() {
  const { t } = useTranslation();
  return (
    <div className="text-xs leading-relaxed text-terminal-muted">
      <p className="mb-2 text-terminal-amber">{t("p.portfolio.no_alpaca_head")}</p>
      <p className="mb-2">{t("p.portfolio.no_alpaca_msg")}</p>
      <p>{t("p.portfolio.free_paper")}</p>
    </div>
  );
}

export default function Portfolio() {
  const { t } = useTranslation();
  const accountQ = usePolling(() => api.portfolioAccount(), 15_000, []);
  const positionsQ = usePolling(() => api.portfolioPositions(), 15_000, []);

  const credsMissing =
    accountQ.error?.status === 503 || positionsQ.error?.status === 503;

  const account = accountQ.data;
  const positions = positionsQ.data || [];

  const equity = account?.equity ?? 0;
  const lastEquity = account?.last_equity ?? 0;
  const dayPL = equity - lastEquity;
  const dayPct = lastEquity ? (dayPL / lastEquity) * 100 : 0;

  const loading =
    (accountQ.loading && !accountQ.data) ||
    (positionsQ.loading && !positionsQ.data);

  const otherError =
    !credsMissing &&
    (accountQ.error || positionsQ.error) &&
    (accountQ.error || positionsQ.error);

  return (
    <Panel
      title={t("p.portfolio.title")}
      accent="amber"
      actions={
        account ? (
          <span className="tabular text-terminal-muted">
            NAV {fmt(account.portfolio_value)}{" "}
            <span
              className={
                dayPL >= 0 ? "text-terminal-green" : "text-terminal-red"
              }
            >
              ({signed(dayPL)} / {signed(dayPct)}%)
            </span>
          </span>
        ) : null
      }
    >
      {credsMissing ? (
        <EmptyState />
      ) : loading ? (
        <div className="text-terminal-muted">{t("p.portfolio.loading")}</div>
      ) : otherError ? (
        <div className="text-terminal-red">
          {String(otherError.detail || otherError.message || otherError)}
        </div>
      ) : (
        <div className="space-y-3">
          {account && (
            <div className="grid grid-cols-2 gap-2 text-xs tabular">
              <Stat label={t("p.portfolio.stats.cash")} value={fmt(account.cash)} />
              <Stat
                label={t("p.portfolio.stats.buy_pwr")}
                value={fmt(account.buying_power)}
                title={t("p.portfolio.buy_pwr_title")}
              />
              <Stat label={t("p.portfolio.stats.equity")} value={fmt(account.equity)} />
              <Stat
                label={t("p.portfolio.stats.day_tr")}
                title={t("p.portfolio.day_tr_title")}
                value={`${account.daytrade_count}${
                  account.pattern_day_trader ? " PDT" : ""
                }`}
              />
            </div>
          )}
          {positions.length === 0 ? (
            <div className="text-terminal-muted text-xs">
              {t("p.portfolio.none")}
            </div>
          ) : (
            <div className="-mx-3 overflow-x-auto px-3">
              <table className="w-full min-w-[480px] text-xs tabular">
                <thead>
                  <tr className="text-left text-terminal-muted">
                    <th className="py-1 pr-2 whitespace-nowrap">{t("p.portfolio.cols.sym")}</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">{t("p.portfolio.cols.qty")}</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">{t("p.portfolio.cols.avg")}</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">{t("p.portfolio.cols.last")}</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">{t("p.portfolio.cols.mkt_val")}</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">{t("p.portfolio.cols.day")}</th>
                    <th className="py-1 text-right whitespace-nowrap">{t("p.portfolio.cols.unr_pl")}</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr
                      key={p.symbol}
                      className="border-t border-terminal-border/60"
                    >
                      <td className="py-1 pr-2 font-bold text-terminal-amber whitespace-nowrap">
                        {p.symbol}
                      </td>
                      <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.qty, 0)}</td>
                      <td className="py-1 pr-2 text-right whitespace-nowrap">
                        {fmt(p.avg_entry_price)}
                      </td>
                      <td className="py-1 pr-2 text-right whitespace-nowrap">
                        {fmt(p.current_price)}
                      </td>
                      <td className="py-1 pr-2 text-right whitespace-nowrap">
                        {fmt(p.market_value)}
                      </td>
                      <td
                        className={clsx(
                          "py-1 pr-2 text-right whitespace-nowrap",
                          (p.change_today_percent ?? 0) >= 0
                            ? "text-terminal-green"
                            : "text-terminal-red"
                        )}
                      >
                        {signed(p.change_today_percent)}%
                      </td>
                      <td
                        className={clsx(
                          "py-1 text-right whitespace-nowrap",
                          (p.unrealized_pl ?? 0) >= 0
                            ? "text-terminal-green"
                            : "text-terminal-red"
                        )}
                      >
                        {signed(p.unrealized_pl)} ({signed(p.unrealized_pl_percent)}%)
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

function Stat({ label, value, title }) {
  return (
    <div
      className="min-w-0 rounded border border-terminal-border/60 px-2 py-1 overflow-hidden"
      title={title}
    >
      <div className="truncate whitespace-nowrap text-[10px] uppercase tracking-wider text-terminal-muted">
        {label}
      </div>
      <div className="truncate whitespace-nowrap text-terminal-text">{value}</div>
    </div>
  );
}
