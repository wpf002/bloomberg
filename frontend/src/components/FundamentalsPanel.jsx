import { useEffect, useState } from "react";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

function fmt(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtMoney(value) {
  if (value == null || Number.isNaN(value)) return "--";
  const n = Number(value);
  const abs = Math.abs(n);
  if (abs >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `$${(n / 1e3).toFixed(2)}K`;
  return `$${n.toFixed(2)}`;
}

function fmtPct(value) {
  if (value == null || Number.isNaN(value)) return "--";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function Row({ label, children, tone }) {
  return (
    <div className="flex items-baseline justify-between border-b border-terminal-border/40 py-0.5 text-xs">
      <span className="text-terminal-muted">{label}</span>
      <span className={clsx("tabular", tone)}>{children}</span>
    </div>
  );
}

export default function FundamentalsPanel({ symbol }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .fundamentals(symbol)
      .then((payload) => !cancelled && setData(payload))
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const tone = (value) =>
    value == null
      ? undefined
      : value >= 0
        ? "text-terminal-green"
        : "text-terminal-red";

  return (
    <Panel
      title={`Fundamentals — ${symbol}`}
      accent="green"
      actions={
        data?.sector ? (
          <span className="text-terminal-muted">
            {data.sector} · {data.industry}
          </span>
        ) : null
      }
    >
      {loading && !data ? (
        <div className="text-terminal-muted">Loading fundamentals…</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.message || error)}</div>
      ) : !data ? (
        <div className="text-terminal-muted">No data.</div>
      ) : !data.name && data.market_cap == null && data.pe_ratio == null ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          <p className="mb-1 text-terminal-amber">
            No fundamentals returned for this ticker.
          </p>
          <p>
            Both providers (Financial Modeling Prep primary, Yahoo Finance
            fallback) came back empty. Most common causes: ticker isn't a US
            common stock (ETFs, ADRs, OTC tickers often miss), or both
            services are rate-limiting this IP. Usually clears in 10–30 min.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <header>
            <div className="text-base font-bold text-terminal-text">
              {data.name || data.symbol}
            </div>
            <div className="text-[11px] text-terminal-muted">
              {data.exchange ? `${data.exchange} · ` : ""}
              {data.currency || "USD"}
              {data.country ? ` · ${data.country}` : ""}
            </div>
          </header>

          {data.description ? (
            <p className="line-clamp-4 text-[11px] leading-relaxed text-terminal-muted">
              {data.description}
            </p>
          ) : null}

          <section>
            <div className="mb-1 text-[10px] uppercase tracking-widest text-terminal-amber">
              Valuation
            </div>
            <Row label="Market cap">{fmtMoney(data.market_cap)}</Row>
            <Row label="Enterprise value">{fmtMoney(data.enterprise_value)}</Row>
            <Row label="P/E (trailing)">{fmt(data.pe_ratio)}</Row>
            <Row label="P/E (forward)">{fmt(data.forward_pe)}</Row>
            <Row label="PEG">{fmt(data.peg_ratio)}</Row>
            <Row label="P/B">{fmt(data.price_to_book)}</Row>
            <Row label="P/S">{fmt(data.price_to_sales)}</Row>
            <Row label="EV/EBITDA">{fmt(data.ev_to_ebitda)}</Row>
          </section>

          <section>
            <div className="mb-1 text-[10px] uppercase tracking-widest text-terminal-amber">
              Performance
            </div>
            <Row label="Revenue (TTM)">{fmtMoney(data.revenue_ttm)}</Row>
            <Row label="Revenue growth YoY" tone={tone(data.revenue_growth_yoy)}>
              {fmtPct(data.revenue_growth_yoy)}
            </Row>
            <Row label="Net income (TTM)">{fmtMoney(data.net_income_ttm)}</Row>
            <Row label="Earnings growth YoY" tone={tone(data.earnings_growth_yoy)}>
              {fmtPct(data.earnings_growth_yoy)}
            </Row>
            <Row label="EPS (TTM)">{fmt(data.eps_ttm)}</Row>
            <Row label="FCF (TTM)">{fmtMoney(data.free_cash_flow_ttm)}</Row>
          </section>

          <section>
            <div className="mb-1 text-[10px] uppercase tracking-widest text-terminal-amber">
              Margins & Returns
            </div>
            <Row label="Gross margin">{fmtPct(data.gross_margin)}</Row>
            <Row label="Operating margin">{fmtPct(data.operating_margin)}</Row>
            <Row label="Profit margin">{fmtPct(data.profit_margin)}</Row>
            <Row label="Return on equity">{fmtPct(data.return_on_equity)}</Row>
            <Row label="Return on assets">{fmtPct(data.return_on_assets)}</Row>
            <Row label="Debt / equity">{fmt(data.debt_to_equity)}</Row>
          </section>

          <section>
            <div className="mb-1 text-[10px] uppercase tracking-widest text-terminal-amber">
              Market
            </div>
            <Row label="52-wk high">{fmt(data.fifty_two_week_high)}</Row>
            <Row label="52-wk low">{fmt(data.fifty_two_week_low)}</Row>
            <Row label="Beta">{fmt(data.beta)}</Row>
            <Row label="Dividend yield">{fmtPct(data.dividend_yield)}</Row>
            <Row label="Payout ratio">{fmtPct(data.payout_ratio)}</Row>
            <Row label="Analyst target">{fmt(data.analyst_target)}</Row>
            <Row label="Analyst reco">{data.analyst_recommendation || "--"}</Row>
          </section>
        </div>
      )}
    </Panel>
  );
}
