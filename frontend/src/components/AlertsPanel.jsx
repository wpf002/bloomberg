import { useEffect, useState } from "react";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import usePolling from "../hooks/usePolling.js";
import useStream from "../hooks/useStream.js";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const FIELDS = ["price", "change_percent", "day_high", "day_low"];
const OPS = [">", "<", ">=", "<=", "=="];

function fmt(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return "--";
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export default function AlertsPanel({ symbol }) {
  const { t } = useTranslation();
  const [field, setField] = useState("price");
  const [op, setOp] = useState(">");
  const [value, setValue] = useState("");
  const [name, setName] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);

  const rulesQ = usePolling(() => api.alertRules(), 0, [refreshKey]);
  const eventsQ = usePolling(() => api.alertEvents(50), 30_000, [refreshKey]);

  const stream = useStream("/api/ws/alerts", {
    onMessage: (msg) => {
      if (!msg || msg.type === "ready") return;
      setLiveEvents((prev) => [msg, ...prev].slice(0, 50));
    },
  });

  useEffect(() => {
    setCreateErr(null);
  }, [symbol, field, op]);

  const submit = async (e) => {
    e.preventDefault();
    setCreating(true);
    setCreateErr(null);
    try {
      const rule = {
        symbol,
        name: name || null,
        cooldown_seconds: 300,
        conditions: [{ field, op, value: Number(value) }],
      };
      await api.createAlertRule(rule);
      setValue("");
      setName("");
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setCreateErr(err?.detail || err?.message || String(err));
    } finally {
      setCreating(false);
    }
  };

  const remove = async (id) => {
    try {
      await api.deleteAlertRule(id);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setCreateErr(err?.detail || err?.message || String(err));
    }
  };

  const rules = rulesQ.data || [];
  const persisted = eventsQ.data || [];
  const mergedEvents = [...liveEvents, ...persisted]
    .filter(
      (e, i, arr) =>
        arr.findIndex((x) => x.rule_id === e.rule_id && x.matched_at === e.matched_at) === i
    )
    .slice(0, 50);

  return (
    <Panel
      title={t("p.alerts.title")}
      accent="amber"
      actions={
        <span className="tabular text-terminal-muted">
          {t("p.alerts.ws")}{" "}
          <span
            className={
              stream.status === "open"
                ? "text-terminal-green"
                : stream.status === "error"
                ? "text-terminal-red"
                : "text-terminal-muted"
            }
          >
            {stream.status}
          </span>{" "}
          · {t("p.alerts.rules_count", { count: rules.length })}
        </span>
      }
    >
      <form onSubmit={submit} className="grid grid-cols-12 gap-1 text-xs">
        <div className="col-span-12 text-[10px] uppercase tracking-widest text-terminal-muted">
          {t("p.alerts.new_for", { sym: symbol ?? "—" })}
        </div>
        <select
          value={field}
          onChange={(e) => setField(e.target.value)}
          className="col-span-4 border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
        >
          {FIELDS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <select
          value={op}
          onChange={(e) => setOp(e.target.value)}
          className="col-span-2 border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
        >
          {OPS.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        <input
          type="number"
          step="0.0001"
          placeholder={t("p.alerts.placeholder_value")}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          required
          className="col-span-3 border border-terminal-border bg-terminal-bg px-2 py-0.5 tabular text-terminal-text focus:outline-none focus:border-terminal-amber"
        />
        <input
          placeholder={t("p.alerts.placeholder_label")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="col-span-3 border border-terminal-border bg-terminal-bg px-2 py-0.5 text-terminal-text focus:outline-none focus:border-terminal-amber"
        />
        <button
          type="submit"
          disabled={creating || !symbol || value === ""}
          className="col-span-12 mt-1 border border-terminal-amber px-2 py-1 uppercase tracking-wider text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
        >
          {creating ? t("p.common.creating") : t("p.alerts.add_for", { sym: symbol ?? "—" })}
        </button>
      </form>
      {createErr && (
        <div className="mt-2 text-[11px] text-terminal-red">{createErr}</div>
      )}

      <div className="mt-3">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">
          {t("p.alerts.active_rules")}
        </div>
        {rules.length === 0 ? (
          <div className="text-xs text-terminal-muted">{t("p.alerts.none_yet")}</div>
        ) : (
          <ul className="space-y-1">
            {rules.map((r) => (
              <li
                key={r.id}
                className="flex items-baseline justify-between gap-2 border-b border-terminal-border/40 py-1 text-xs"
              >
                <span className="font-bold text-terminal-amber">{r.symbol}</span>
                <span className="flex-1 truncate text-terminal-muted">
                  {r.name ? <span className="mr-1">{r.name} ·</span> : null}
                  {r.conditions
                    .map((c) => `${c.field} ${c.op} ${c.value}`)
                    .join(" AND ")}
                </span>
                <button
                  onClick={() => remove(r.id)}
                  className="text-terminal-red hover:underline"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-3">
        <div className="text-[10px] uppercase tracking-widest text-terminal-muted">
          {t("p.alerts.recent")}
        </div>
        {mergedEvents.length === 0 ? (
          <div className="text-xs text-terminal-muted">{t("p.alerts.none_fired")}</div>
        ) : (
          <ul className="space-y-1">
            {mergedEvents.slice(0, 12).map((e) => (
              <li
                key={`${e.rule_id}-${e.matched_at}`}
                className="border-b border-terminal-border/40 py-1 text-xs"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-bold text-terminal-amber">{e.symbol}</span>
                  <span className="text-terminal-muted">
                    {new Date(e.matched_at).toLocaleTimeString()}
                  </span>
                </div>
                <div className="text-terminal-muted">
                  {e.name || e.rule_id} · px{" "}
                  <span className="text-terminal-text">
                    {fmt(e.snapshot?.price)}
                  </span>{" "}
                  · chg{" "}
                  <span
                    className={clsx(
                      (e.snapshot?.change_percent ?? 0) >= 0
                        ? "text-terminal-green"
                        : "text-terminal-red"
                    )}
                  >
                    {fmt(e.snapshot?.change_percent)}%
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
