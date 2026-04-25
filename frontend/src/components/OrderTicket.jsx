import { useEffect, useState } from "react";
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

const TYPES = ["market", "limit", "stop", "stop_limit"];
const TIFS = ["day", "gtc", "ioc", "fok", "opg", "cls"];
// `simple` matches Alpaca's default; the others wrap the entry leg with
// take-profit / stop-loss children in a single submission.
const ORDER_CLASSES = [
  { value: "simple",  label: "simple",  hint: "single-leg order" },
  { value: "bracket", label: "bracket", hint: "entry + TP + SL" },
  { value: "oco",     label: "oco",     hint: "two paired exits (no entry)" },
  { value: "oto",     label: "oto",     hint: "entry + TP or SL" },
];

export default function OrderTicket({ symbol }) {
  const [side, setSide] = useState("buy");
  const [qty, setQty] = useState("1");
  const [type, setType] = useState("market");
  const [tif, setTif] = useState("day");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [extended, setExtended] = useState(false);
  const [orderClass, setOrderClass] = useState("simple");
  const [tpLimit, setTpLimit] = useState("");
  const [slStop, setSlStop] = useState("");
  const [slLimit, setSlLimit] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState(null);
  const [lastSubmitted, setLastSubmitted] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const ordersQ = usePolling(() => api.orders("all", 25), 8_000, [refreshKey]);
  const credsMissing = ordersQ.error?.status === 503;

  useEffect(() => {
    setSubmitErr(null);
  }, [symbol, type, side, orderClass]);

  // Bracket orders need a TIF the broker accepts; quietly nudge the user.
  useEffect(() => {
    if (orderClass === "bracket" && tif !== "day" && tif !== "gtc") {
      setTif("day");
    }
  }, [orderClass]);

  const wantTakeProfit = ["bracket", "oco", "oto"].includes(orderClass);
  const wantStopLoss = ["bracket", "oco", "oto"].includes(orderClass);

  const submit = async (e) => {
    e.preventDefault();
    if (!symbol) return;
    setSubmitErr(null);
    setSubmitting(true);
    try {
      const body = {
        symbol,
        qty: Number(qty),
        side,
        type,
        time_in_force: tif,
        extended_hours: extended,
        order_class: orderClass,
      };
      if (type === "limit" || type === "stop_limit") body.limit_price = Number(limitPrice);
      if (type === "stop" || type === "stop_limit") body.stop_price = Number(stopPrice);
      if (wantTakeProfit && tpLimit !== "") body.take_profit_limit_price = Number(tpLimit);
      if (wantStopLoss && slStop !== "") body.stop_loss_stop_price = Number(slStop);
      if (wantStopLoss && slLimit !== "") body.stop_loss_limit_price = Number(slLimit);
      const placed = await api.placeOrder(body);
      setLastSubmitted(placed);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setSubmitErr(err?.detail || err?.message || String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async (id) => {
    try {
      await api.cancelOrder(id);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setSubmitErr(err?.detail || err?.message || String(err));
    }
  };

  const orders = ordersQ.data || [];

  return (
    <Panel
      title={`EMS — ${symbol ?? "—"}`}
      accent="amber"
      actions={
        <span className="tabular text-terminal-muted">
          PAPER · {credsMissing ? "no creds" : `${orders.length} orders`}
        </span>
      }
    >
      {credsMissing ? (
        <div className="text-xs text-terminal-muted">
          Connect Alpaca in <code className="text-terminal-green">.env</code> to
          submit paper orders (see Portfolio panel).
        </div>
      ) : (
        <>
          <form onSubmit={submit} className="grid grid-cols-2 gap-2 text-xs">
            <div className="col-span-2 flex gap-1">
              <button
                type="button"
                onClick={() => setSide("buy")}
                className={clsx(
                  "flex-1 border px-2 py-1 uppercase tracking-wider",
                  side === "buy"
                    ? "border-terminal-green bg-terminal-green/10 text-terminal-green"
                    : "border-terminal-border text-terminal-muted"
                )}
              >
                Buy
              </button>
              <button
                type="button"
                onClick={() => setSide("sell")}
                className={clsx(
                  "flex-1 border px-2 py-1 uppercase tracking-wider",
                  side === "sell"
                    ? "border-terminal-red bg-terminal-red/10 text-terminal-red"
                    : "border-terminal-border text-terminal-muted"
                )}
              >
                Sell
              </button>
            </div>
            <Field label="Qty">
              <input
                type="number"
                min="0.0001"
                step="0.0001"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
              />
            </Field>
            <Field label="Type">
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
              >
                {TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="TIF">
              <select
                value={tif}
                onChange={(e) => setTif(e.target.value)}
                className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
              >
                {TIFS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Class">
              <select
                value={orderClass}
                onChange={(e) => setOrderClass(e.target.value)}
                className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
                title={ORDER_CLASSES.find((c) => c.value === orderClass)?.hint}
              >
                {ORDER_CLASSES.map((c) => (
                  <option key={c.value} value={c.value} title={c.hint}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>
            <label className="col-span-2 flex items-center gap-2 text-terminal-muted">
              <input
                type="checkbox"
                checked={extended}
                onChange={(e) => setExtended(e.target.checked)}
              />
              Extended hours
            </label>
            {(type === "limit" || type === "stop_limit") && (
              <Field label="Limit $">
                <input
                  type="number"
                  step="0.01"
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                />
              </Field>
            )}
            {(type === "stop" || type === "stop_limit") && (
              <Field label="Stop $">
                <input
                  type="number"
                  step="0.01"
                  value={stopPrice}
                  onChange={(e) => setStopPrice(e.target.value)}
                  className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                />
              </Field>
            )}
            {wantTakeProfit && (
              <Field label="Take-profit $">
                <input
                  type="number"
                  step="0.01"
                  value={tpLimit}
                  onChange={(e) => setTpLimit(e.target.value)}
                  placeholder="limit"
                  className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                />
              </Field>
            )}
            {wantStopLoss && (
              <Field label="Stop-loss $">
                <input
                  type="number"
                  step="0.01"
                  value={slStop}
                  onChange={(e) => setSlStop(e.target.value)}
                  placeholder="stop"
                  className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                />
              </Field>
            )}
            {wantStopLoss && (
              <Field label="SL limit $ (opt)">
                <input
                  type="number"
                  step="0.01"
                  value={slLimit}
                  onChange={(e) => setSlLimit(e.target.value)}
                  placeholder="optional"
                  className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                />
              </Field>
            )}
            {orderClass !== "simple" && (
              <p className="col-span-2 text-[10px] leading-relaxed text-terminal-muted">
                {orderClass === "bracket" && "Bracket: entry fills, then take-profit and stop-loss go live as paired exits."}
                {orderClass === "oco" && "OCO: two exit legs only — when one fills, the other cancels. Use on an existing position."}
                {orderClass === "oto" && "OTO: entry plus a single attached exit (TP or SL)."}
              </p>
            )}
            <button
              type="submit"
              disabled={submitting || !symbol}
              className={clsx(
                "col-span-2 mt-1 border px-2 py-1 uppercase tracking-wider transition-colors disabled:opacity-50",
                side === "buy"
                  ? "border-terminal-green text-terminal-green hover:bg-terminal-green/10"
                  : "border-terminal-red text-terminal-red hover:bg-terminal-red/10"
              )}
            >
              {submitting ? "Sending…" : `Submit ${side.toUpperCase()} ${qty} ${symbol ?? ""}${orderClass !== "simple" ? ` (${orderClass})` : ""}`}
            </button>
          </form>
          {submitErr && (
            <div className="mt-2 border border-terminal-red/50 bg-terminal-red/5 px-2 py-1 text-[11px] text-terminal-red">
              {submitErr}
            </div>
          )}
          {lastSubmitted && !submitErr && (
            <div className="mt-2 border border-terminal-green/50 bg-terminal-green/5 px-2 py-1 text-[11px] text-terminal-green">
              Submitted · {lastSubmitted.id?.slice(0, 8)} · {lastSubmitted.status}
              {lastSubmitted.legs?.length ? ` · ${lastSubmitted.legs.length} legs` : ""}
            </div>
          )}

          <div className="mt-3 text-[10px] uppercase tracking-widest text-terminal-muted">
            Recent orders
          </div>
          {orders.length === 0 ? (
            <div className="text-xs text-terminal-muted">No orders yet.</div>
          ) : (
            <table className="w-full text-xs tabular">
              <thead>
                <tr className="text-left text-terminal-muted">
                  <th className="py-1 pr-2">SYM</th>
                  <th className="py-1 pr-2">SIDE</th>
                  <th className="py-1 pr-2 text-right">QTY</th>
                  <th className="py-1 pr-2 text-right">TYPE</th>
                  <th className="py-1 pr-2 text-right">CLASS</th>
                  <th className="py-1 pr-2 text-right">FILL</th>
                  <th className="py-1 pr-2">STATUS</th>
                  <th className="py-1"></th>
                </tr>
              </thead>
              <tbody>
                {orders.slice(0, 12).map((o) => (
                  <tr key={o.id} className="border-t border-terminal-border/60">
                    <td className="py-1 pr-2 font-bold text-terminal-amber">
                      {o.symbol}
                    </td>
                    <td
                      className={clsx(
                        "py-1 pr-2 uppercase",
                        o.side === "buy" ? "text-terminal-green" : "text-terminal-red"
                      )}
                    >
                      {o.side}
                    </td>
                    <td className="py-1 pr-2 text-right">{fmt(o.qty, 0)}</td>
                    <td className="py-1 pr-2 text-right text-terminal-muted">
                      {o.type}
                    </td>
                    <td className="py-1 pr-2 text-right text-terminal-muted">
                      {o.order_class && o.order_class !== "simple" ? o.order_class : "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {o.filled_avg_price ? fmt(o.filled_avg_price) : "—"}
                    </td>
                    <td className="py-1 pr-2 text-terminal-muted">{o.status}</td>
                    <td className="py-1 text-right">
                      {["new", "accepted", "pending_new", "partially_filled"].includes(
                        o.status
                      ) && (
                        <button
                          onClick={() => cancel(o.id)}
                          className="text-terminal-red hover:underline"
                        >
                          ✕
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="mt-2 text-[10px] leading-relaxed text-terminal-muted/80">
            Submits to Alpaca paper trading. Orders are visible at{" "}
            <a
              href="https://paper-api.alpaca.markets"
              className="underline"
              target="_blank"
              rel="noreferrer"
            >
              paper-api.alpaca.markets
            </a>
            .
          </p>
        </>
      )}
    </Panel>
  );
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-terminal-muted">
        {label}
      </span>
      {children}
    </label>
  );
}
