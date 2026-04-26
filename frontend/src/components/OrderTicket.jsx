import { useEffect, useState } from "react";
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

const TYPES = ["market", "limit", "stop", "stop_limit"];
const TIFS = ["day", "gtc", "ioc", "fok", "opg", "cls"];

export default function OrderTicket({ symbol }) {
  const { t } = useTranslation();
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

  const ORDER_CLASSES = [
    { value: "simple",  label: t("p.trade.cls_simple"),  hint: t("p.trade.cls_simple_hint") },
    { value: "bracket", label: t("p.trade.cls_bracket"), hint: t("p.trade.cls_bracket_hint") },
    { value: "oco",     label: t("p.trade.cls_oco"),     hint: t("p.trade.cls_oco_hint") },
    { value: "oto",     label: t("p.trade.cls_oto"),     hint: t("p.trade.cls_oto_hint") },
  ];

  const ordersQ = usePolling(() => api.orders("all", 25), 8_000, [refreshKey]);
  const credsMissing = ordersQ.error?.status === 503;

  useEffect(() => {
    setSubmitErr(null);
  }, [symbol, type, side, orderClass]);

  useEffect(() => {
    if (orderClass === "bracket" && tif !== "day" && tif !== "gtc") {
      setTif("day");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      title={t("p.trade.title", { sym: symbol ?? "—" })}
      accent="amber"
      actions={
        <span className="tabular text-terminal-muted">
          {t("p.trade.paper")} · {credsMissing ? t("p.trade.no_creds") : t("p.trade.orders_count", { n: orders.length })}
        </span>
      }
    >
      {credsMissing ? (
        <div className="text-xs text-terminal-muted">{t("p.trade.need_alpaca")}</div>
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
                {t("p.trade.side_buy")}
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
                {t("p.trade.side_sell")}
              </button>
            </div>
            <Field label={t("p.trade.f.qty")}>
              <input
                type="number"
                min="0.0001"
                step="0.0001"
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
              />
            </Field>
            <Field label={t("p.trade.f.type")}>
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
              >
                {TYPES.map((tp) => (
                  <option key={tp} value={tp}>
                    {tp}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("p.trade.f.tif")}>
              <select
                value={tif}
                onChange={(e) => setTif(e.target.value)}
                className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
              >
                {TIFS.map((tp) => (
                  <option key={tp} value={tp}>
                    {tp}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("p.trade.f.cls")}>
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
              {t("p.trade.ext")}
            </label>
            {(type === "limit" || type === "stop_limit") && (
              <Field label={t("p.trade.f.limit")}>
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
              <Field label={t("p.trade.f.stop")}>
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
              <Field label={t("p.trade.f.tp")}>
                <input
                  type="number"
                  step="0.01"
                  value={tpLimit}
                  onChange={(e) => setTpLimit(e.target.value)}
                  placeholder={t("p.trade.tp_placeholder")}
                  className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                />
              </Field>
            )}
            {wantStopLoss && (
              <Field label={t("p.trade.f.sl")}>
                <input
                  type="number"
                  step="0.01"
                  value={slStop}
                  onChange={(e) => setSlStop(e.target.value)}
                  placeholder={t("p.trade.sl_placeholder")}
                  className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                />
              </Field>
            )}
            {wantStopLoss && (
              <Field label={t("p.trade.f.sl_lim")}>
                <input
                  type="number"
                  step="0.01"
                  value={slLimit}
                  onChange={(e) => setSlLimit(e.target.value)}
                  placeholder={t("p.trade.sl_lim_placeholder")}
                  className="w-full border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
                />
              </Field>
            )}
            {orderClass !== "simple" && (
              <p className="col-span-2 text-[10px] leading-relaxed text-terminal-muted">
                {orderClass === "bracket" && t("p.trade.bracket_hint")}
                {orderClass === "oco" && t("p.trade.oco_hint")}
                {orderClass === "oto" && t("p.trade.oto_hint")}
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
              {submitting
                ? t("p.trade.sending")
                : orderClass !== "simple"
                  ? t("p.trade.submit_with_class", {
                      side: side.toUpperCase(),
                      qty,
                      sym: symbol ?? "",
                      cls: orderClass,
                    })
                  : t("p.trade.submit", {
                      side: side.toUpperCase(),
                      qty,
                      sym: symbol ?? "",
                    })}
            </button>
          </form>
          {submitErr && (
            <div className="mt-2 border border-terminal-red/50 bg-terminal-red/5 px-2 py-1 text-[11px] text-terminal-red">
              {submitErr}
            </div>
          )}
          {lastSubmitted && !submitErr && (
            <div className="mt-2 border border-terminal-green/50 bg-terminal-green/5 px-2 py-1 text-[11px] text-terminal-green">
              {lastSubmitted.legs?.length
                ? t("p.trade.submitted_legs", {
                    id: lastSubmitted.id?.slice(0, 8),
                    status: lastSubmitted.status,
                    n: lastSubmitted.legs.length,
                  })
                : t("p.trade.submitted", {
                    id: lastSubmitted.id?.slice(0, 8),
                    status: lastSubmitted.status,
                  })}
            </div>
          )}

          <div className="mt-3 text-[10px] uppercase tracking-widest text-terminal-muted">
            {t("p.trade.recent")}
          </div>
          {orders.length === 0 ? (
            <div className="text-xs text-terminal-muted">{t("p.trade.none")}</div>
          ) : (
            <table className="w-full text-xs tabular">
              <thead>
                <tr className="text-left text-terminal-muted">
                  <th className="py-1 pr-2">{t("p.trade.cols.sym")}</th>
                  <th className="py-1 pr-2">{t("p.trade.cols.side")}</th>
                  <th className="py-1 pr-2 text-right">{t("p.trade.cols.qty")}</th>
                  <th className="py-1 pr-2 text-right">{t("p.trade.cols.type")}</th>
                  <th className="py-1 pr-2 text-right">{t("p.trade.cols.cls")}</th>
                  <th className="py-1 pr-2 text-right">{t("p.trade.cols.fill")}</th>
                  <th className="py-1 pr-2">{t("p.trade.cols.status")}</th>
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
            {t("p.trade.footer")}
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
