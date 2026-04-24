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

function daysFromNow(dateStr) {
  const d = new Date(`${dateStr}T00:00:00`);
  const delta = (d - new Date()) / (24 * 3600 * 1000);
  if (delta < -1) return `${Math.floor(-delta)}d ago`;
  if (delta < 1) return "today";
  return `in ${Math.ceil(delta)}d`;
}

export default function CalendarPanel({ symbols }) {
  const { data, loading, error } = usePolling(
    () => api.earningsCalendar(symbols, 4),
    // 1h: matches the backend Finnhub cache TTL so polling doesn't burn
    // requests on stale data. Earnings actuals appear within ~1h of release.
    60 * 60_000,
    [symbols.join(",")]
  );

  return (
    <Panel
      title="Earnings Calendar"
      accent="blue"
      actions={
        <span className="text-terminal-muted">
          {symbols.length} syms
        </span>
      }
    >
      {loading && !data ? (
        <div className="text-terminal-muted">Loading calendar…</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : (data || []).length === 0 ? (
        <div className="space-y-1 text-xs leading-relaxed text-terminal-muted">
          <p className="text-terminal-amber">No upcoming earnings dates in the next 120 days.</p>
          <p>
            Calendar comes from Finnhub (market-wide consensus) with Yahoo as
            a fallback. Tickers with no upcoming events typically just reported
            and won't have a next date until guidance is updated.
          </p>
        </div>
      ) : (
        <table className="w-full text-[11px] tabular">
          <thead>
            <tr className="text-left text-terminal-muted">
              <th className="py-1 pr-2">DATE</th>
              <th className="py-1 pr-2">SYM</th>
              <th className="py-1 pr-2">IN</th>
              <th className="py-1 pr-2 text-right">EST</th>
              <th className="py-1 pr-2 text-right">ACT</th>
              <th className="py-1 text-right">SURP</th>
            </tr>
          </thead>
          <tbody>
            {data.map((e, idx) => {
              const surprise = e.eps_surprise_percent;
              return (
                <tr
                  key={`${e.symbol}-${e.event_date}-${idx}`}
                  className="border-t border-terminal-border/40"
                >
                  <td className="py-0.5 pr-2">{e.event_date}</td>
                  <td className="py-0.5 pr-2 font-bold text-terminal-amber">
                    {e.symbol}
                  </td>
                  <td className="py-0.5 pr-2 text-terminal-muted">
                    {daysFromNow(e.event_date)}
                  </td>
                  <td className="py-0.5 pr-2 text-right">{fmt(e.eps_estimate)}</td>
                  <td className="py-0.5 pr-2 text-right">{fmt(e.eps_actual)}</td>
                  <td
                    className={clsx(
                      "py-0.5 text-right",
                      surprise == null
                        ? ""
                        : surprise >= 0
                          ? "text-terminal-green"
                          : "text-terminal-red"
                    )}
                  >
                    {surprise == null ? "--" : `${surprise > 0 ? "+" : ""}${fmt(surprise)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
