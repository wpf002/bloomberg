import { useEffect, useState } from "react";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

function fmtUsd(value) {
  if (value == null) return "--";
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
  return `$${Number(value).toFixed(0)}`;
}

function fmtPct(value) {
  if (value == null) return "--";
  return `${Number(value).toFixed(3)}%`;
}

function fmtDate(iso) {
  if (!iso) return "--";
  // Treasury feeds often include time component; show date only
  const m = String(iso).match(/(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : iso;
}

const TABS = [
  { id: "auctions",  label: "Treasury Auctions" },
  { id: "auctioned", label: "Recent Results" },
  { id: "trace",     label: "FINRA Treasury Aggregates" },
];

export default function FixedIncomePanel() {
  const [tab, setTab] = useState("auctions");
  const [status, setStatus] = useState(null);
  const [auctions, setAuctions] = useState(null);
  const [auctioned, setAuctioned] = useState(null);
  const [trace, setTrace] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.fixedIncomeStatus().then(setStatus).catch(() => setStatus({ trace_configured: false }));
  }, []);

  const loadTab = async (which) => {
    setBusy(true);
    setError(null);
    try {
      if (which === "auctions") {
        setAuctions(await api.treasuryAuctions("announced", 30));
      } else if (which === "auctioned") {
        setAuctioned(await api.treasuryAuctions("auctioned", 30));
      } else if (which === "trace") {
        setTrace(await api.traceAggregates(undefined, 50));
      }
    } catch (err) {
      setError(err?.detail || err?.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    loadTab(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const traceMissing = error && /finra trace/i.test(error);

  return (
    <Panel
      title="Fixed Income (TK)"
      accent="amber"
      actions={
        <span className="text-[10px] uppercase tracking-widest text-terminal-muted">
          Treasury · {status?.trace_configured ? "TRACE ✓" : "TRACE not configured"}
        </span>
      }
    >
      <div className="flex gap-1 border-b border-terminal-border/60 pb-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "border px-2 py-0.5 text-[10px] uppercase tracking-widest",
              tab === t.id
                ? "border-terminal-amber text-terminal-amber"
                : "border-transparent text-terminal-muted hover:text-terminal-text"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {busy ? (
        <div className="mt-2 text-xs text-terminal-muted">Loading…</div>
      ) : tab === "auctions" ? (
        <AuctionTable rows={auctions} kind="upcoming" />
      ) : tab === "auctioned" ? (
        <AuctionTable rows={auctioned} kind="recent" />
      ) : traceMissing ? (
        <div className="mt-2 text-xs text-terminal-muted">
          <p className="mb-1 text-terminal-amber">FINRA not configured.</p>
          <p>
            Register a free dev account at{" "}
            <a
              href="https://developer.finra.org/manage-credentials"
              target="_blank"
              rel="noreferrer"
              className="text-terminal-amber underline"
            >
              developer.finra.org
            </a>{" "}
            and add <code className="text-terminal-green">FINRA_API_KEY</code> +{" "}
            <code className="text-terminal-green">FINRA_API_SECRET</code> to{" "}
            <code className="text-terminal-green">.env</code>.
          </p>
        </div>
      ) : error ? (
        <div className="mt-2 text-xs text-terminal-red">{error}</div>
      ) : (
        <TreasuryAggTable rows={trace} />
      )}
    </Panel>
  );
}

function AuctionTable({ rows, kind }) {
  if (!rows) return null;
  if (rows.length === 0) {
    return (
      <div className="mt-2 text-xs text-terminal-muted">No {kind} auctions returned.</div>
    );
  }
  return (
    <table className="mt-2 w-full text-xs tabular">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-widest text-terminal-muted">
          <th className="py-1 pr-2">Type</th>
          <th className="py-1 pr-2">Term</th>
          <th className="py-1 pr-2 text-right">Auction</th>
          <th className="py-1 pr-2 text-right">Issue</th>
          <th className="py-1 pr-2 text-right">Maturity</th>
          <th className="py-1 pr-2 text-right">Yield/Rate</th>
          <th className="py-1 text-right">Offering</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.cusip || i}`} className="border-t border-terminal-border/40">
            <td className="py-1 pr-2 font-bold text-terminal-amber">{r.security_type}</td>
            <td className="py-1 pr-2 text-terminal-muted">{r.security_term}</td>
            <td className="py-1 pr-2 text-right">{fmtDate(r.auction_date)}</td>
            <td className="py-1 pr-2 text-right">{fmtDate(r.issue_date)}</td>
            <td className="py-1 pr-2 text-right">{fmtDate(r.maturity_date)}</td>
            <td className="py-1 pr-2 text-right">{fmtPct(r.high_yield ?? r.interest_rate)}</td>
            <td className="py-1 text-right">{fmtUsd(r.offering_amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TreasuryAggTable({ rows }) {
  if (!rows) return null;
  if (rows.length === 0) {
    return <div className="mt-2 text-xs text-terminal-muted">No FINRA Treasury aggregates returned.</div>;
  }
  return (
    <table className="mt-2 w-full text-xs tabular">
      <thead>
        <tr className="text-left text-[10px] uppercase tracking-widest text-terminal-muted">
          <th className="py-1 pr-2">Period</th>
          <th className="py-1 pr-2">Type</th>
          <th className="py-1 pr-2">Term</th>
          <th className="py-1 pr-2 text-right">Par Volume</th>
          <th className="py-1 pr-2 text-right">Trades</th>
          <th className="py-1 pr-2 text-right">Avg Size</th>
          <th className="py-1 pr-2 text-right">D2C %</th>
          <th className="py-1 text-right">D2D %</th>
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 30).map((r, i) => (
          <tr key={`${r.period || ""}-${r.benchmark_term || ""}-${i}`} className="border-t border-terminal-border/40">
            <td className="py-1 pr-2 font-bold text-terminal-amber">{fmtDate(r.period)}</td>
            <td className="py-1 pr-2 text-terminal-muted">{r.security_type || "--"}</td>
            <td className="py-1 pr-2">{r.benchmark_term || "--"}</td>
            <td className="py-1 pr-2 text-right">{fmtUsd(r.total_par_volume)}</td>
            <td className="py-1 pr-2 text-right">{r.total_trade_count?.toLocaleString() ?? "--"}</td>
            <td className="py-1 pr-2 text-right">{fmtUsd(r.avg_trade_size)}</td>
            <td className="py-1 pr-2 text-right">
              {r.pct_dealer_to_customer != null ? Number(r.pct_dealer_to_customer).toFixed(2) + "%" : "--"}
            </td>
            <td className="py-1 text-right">
              {r.pct_dealer_to_dealer != null ? Number(r.pct_dealer_to_dealer).toFixed(2) + "%" : "--"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
