import clsx from "clsx";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import { api } from "../lib/api.js";

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
  return (
    <div className="text-xs leading-relaxed text-terminal-muted">
      <p className="mb-2 text-terminal-amber">No Alpaca paper account connected.</p>
      <p className="mb-2">
        Add <code className="text-terminal-green">ALPACA_API_KEY</code> and{" "}
        <code className="text-terminal-green">ALPACA_API_SECRET</code> to{" "}
        <code className="text-terminal-green">.env</code> and restart the
        backend to see live positions.
      </p>
      <p>
        Free paper account:{" "}
        <a
          href="https://alpaca.markets/signup"
          className="text-terminal-amber underline"
          target="_blank"
          rel="noreferrer"
        >
          alpaca.markets/signup
        </a>
      </p>
    </div>
  );
}

export default function Portfolio() {
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
      title="Portfolio"
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
        <div className="text-terminal-muted">Loading positions…</div>
      ) : otherError ? (
        <div className="text-terminal-red">
          {String(otherError.detail || otherError.message || otherError)}
        </div>
      ) : (
        <div className="space-y-3">
          {account && (
            <div className="grid grid-cols-2 gap-2 text-xs tabular">
              <Stat label="CASH" value={fmt(account.cash)} />
              <Stat label="BUY PWR" value={fmt(account.buying_power)} title="Buying power" />
              <Stat label="EQUITY" value={fmt(account.equity)} />
              <Stat
                label="DAY TR"
                title="Day trades (pattern day trader if 4+ in 5 biz days)"
                value={`${account.daytrade_count}${
                  account.pattern_day_trader ? " PDT" : ""
                }`}
              />
            </div>
          )}
          {positions.length === 0 ? (
            <div className="text-terminal-muted text-xs">
              No open positions.
            </div>
          ) : (
            <div className="-mx-3 overflow-x-auto px-3">
              <table className="w-full min-w-[480px] text-xs tabular">
                <thead>
                  <tr className="text-left text-terminal-muted">
                    <th className="py-1 pr-2 whitespace-nowrap">SYM</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">QTY</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">AVG</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">LAST</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">MKT VAL</th>
                    <th className="py-1 pr-2 text-right whitespace-nowrap">DAY</th>
                    <th className="py-1 text-right whitespace-nowrap">UNR P/L</th>
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
