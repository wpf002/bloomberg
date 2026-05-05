import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const [tab, setTab] = useState("positions"); // "positions" | "manage"
  const accountQ = usePolling(() => api.portfolioAccount(), 15_000, []);
  const positionsQ = usePolling(() => api.portfolioPositions(), 15_000, []);
  const manualQ = usePolling(() => api.manualPositions(), 30_000, [tab]);

  const credsMissing =
    accountQ.error?.status === 503 || positionsQ.error?.status === 503;

  const account = accountQ.data;
  const positions = positionsQ.data || [];
  const manual = manualQ.data || [];

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

  const refreshManual = manualQ.refetch;

  return (
    <Panel
      title={t("p.portfolio.title")}
      accent="amber"
      actions={
        <div className="flex items-center gap-3">
          {account ? (
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
          ) : null}
          <div className="flex items-center gap-1">
            <TabButton active={tab === "positions"} onClick={() => setTab("positions")}>
              {t("p.portfolio.tabs.positions")}
            </TabButton>
            <TabButton active={tab === "manage"} onClick={() => setTab("manage")}>
              {t("p.portfolio.tabs.manage")}
            </TabButton>
          </div>
        </div>
      }
    >
      {tab === "positions" ? (
        credsMissing ? (
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
            <PositionsTable positions={positions} manual={manual} t={t} />
          </div>
        )
      ) : (
        <ManageTab
          rows={manual}
          loading={manualQ.loading && !manualQ.data}
          error={manualQ.error}
          refresh={refreshManual}
          t={t}
        />
      )}
    </Panel>
  );
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "px-2 py-0.5 text-[10px] uppercase tracking-wider",
        active
          ? "bg-terminal-amber text-black"
          : "text-terminal-muted hover:text-terminal-text"
      )}
    >
      {children}
    </button>
  );
}

function PositionsTable({ positions, manual, t }) {
  const hasAny = positions.length > 0 || manual.length > 0;
  if (!hasAny) {
    return (
      <div className="text-terminal-muted text-xs">
        {t("p.portfolio.none")}
      </div>
    );
  }
  return (
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
            <tr key={`alpaca-${p.symbol}`} className="border-t border-terminal-border/60">
              <td className="py-1 pr-2 font-bold text-terminal-amber whitespace-nowrap">{p.symbol}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.qty, 0)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.avg_entry_price)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.current_price)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.market_value)}</td>
              <td className={clsx("py-1 pr-2 text-right whitespace-nowrap", (p.change_today_percent ?? 0) >= 0 ? "text-terminal-green" : "text-terminal-red")}>
                {signed(p.change_today_percent)}%
              </td>
              <td className={clsx("py-1 text-right whitespace-nowrap", (p.unrealized_pl ?? 0) >= 0 ? "text-terminal-green" : "text-terminal-red")}>
                {signed(p.unrealized_pl)} ({signed(p.unrealized_pl_percent)}%)
              </td>
            </tr>
          ))}
          {manual.map((p) => (
            <tr key={`man-${p.id}`} className="border-t border-terminal-border/60">
              <td className="py-1 pr-2 whitespace-nowrap">
                <span className="font-bold text-terminal-amber">{p.symbol}</span>{" "}
                <span className="text-[9px] uppercase tracking-wider text-terminal-muted border border-terminal-muted/60 px-1 ml-1">
                  {t("p.portfolio.manual_badge")}
                </span>
              </td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.quantity, 0)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.cost_basis)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.current_price)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(p.market_value)}</td>
              <td className="py-1 pr-2 text-right whitespace-nowrap text-terminal-muted">--</td>
              <td className={clsx("py-1 text-right whitespace-nowrap", (p.unrealized_pl ?? 0) >= 0 ? "text-terminal-green" : "text-terminal-red")}>
                {signed(p.unrealized_pl)} ({signed(p.unrealized_pl_percent)}%)
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ManageTab({ rows, loading, error, refresh, t }) {
  const [draft, setDraft] = useState({ symbol: "", quantity: "", cost_basis: "", entry_date: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const fileRef = useRef(null);

  const submit = useCallback(
    async (e) => {
      e?.preventDefault?.();
      if (busy) return;
      setBusy(true);
      setMsg(null);
      try {
        await api.createManualPosition({
          symbol: draft.symbol.trim().toUpperCase(),
          quantity: Number(draft.quantity),
          cost_basis: Number(draft.cost_basis),
          entry_date: draft.entry_date || null,
          notes: draft.notes || null,
        });
        setDraft({ symbol: "", quantity: "", cost_basis: "", entry_date: "", notes: "" });
        await refresh();
        setMsg({ type: "ok", text: t("p.portfolio.manage.added") });
      } catch (e) {
        setMsg({ type: "err", text: String(e.detail || e.message || e) });
      } finally {
        setBusy(false);
      }
    },
    [busy, draft, refresh, t]
  );

  const remove = useCallback(
    async (id) => {
      try {
        await api.deleteManualPosition(id);
        await refresh();
      } catch (e) {
        setMsg({ type: "err", text: String(e.detail || e.message || e) });
      }
    },
    [refresh]
  );

  const onImport = useCallback(
    async (file) => {
      if (!file) return;
      setBusy(true);
      setMsg(null);
      try {
        const r = await api.importManualPositions(file);
        await refresh();
        setMsg({
          type: r.errors?.length ? "warn" : "ok",
          text: t("p.portfolio.manage.import_done", {
            imported: r.imported,
            skipped: r.skipped,
            errs: r.errors?.length || 0,
          }),
        });
      } catch (e) {
        setMsg({ type: "err", text: String(e.detail || e.message || e) });
      } finally {
        setBusy(false);
      }
    },
    [refresh, t]
  );

  return (
    <div className="space-y-3 text-xs">
      <form onSubmit={submit} className="grid grid-cols-1 sm:grid-cols-6 gap-1 items-end">
        <FieldInput label={t("p.portfolio.manage.f.symbol")} value={draft.symbol} onChange={(v) => setDraft((d) => ({ ...d, symbol: v.toUpperCase() }))} placeholder="AAPL" />
        <FieldInput label={t("p.portfolio.manage.f.qty")} value={draft.quantity} type="number" step="any" onChange={(v) => setDraft((d) => ({ ...d, quantity: v }))} />
        <FieldInput label={t("p.portfolio.manage.f.cost")} value={draft.cost_basis} type="number" step="any" onChange={(v) => setDraft((d) => ({ ...d, cost_basis: v }))} />
        <FieldInput label={t("p.portfolio.manage.f.entry")} value={draft.entry_date} type="date" onChange={(v) => setDraft((d) => ({ ...d, entry_date: v }))} />
        <FieldInput label={t("p.portfolio.manage.f.notes")} value={draft.notes} onChange={(v) => setDraft((d) => ({ ...d, notes: v }))} />
        <button
          type="submit"
          disabled={busy || !draft.symbol || !draft.quantity || !draft.cost_basis}
          className="px-2 py-1 text-[10px] uppercase tracking-wider bg-terminal-amber text-black disabled:opacity-50"
        >
          {busy ? "…" : t("p.portfolio.manage.add")}
        </button>
      </form>
      <div className="flex items-center gap-2">
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => onImport(e.target.files?.[0])}
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="px-2 py-1 text-[10px] uppercase tracking-wider border border-terminal-border hover:bg-terminal-panelAlt disabled:opacity-50"
        >
          {t("p.portfolio.manage.import_csv")}
        </button>
        <span className="text-[10px] text-terminal-muted">
          {t("p.portfolio.manage.csv_hint")}
        </span>
      </div>
      {msg ? (
        <div
          className={clsx(
            "text-[11px]",
            msg.type === "ok" && "text-terminal-green",
            msg.type === "warn" && "text-terminal-amber",
            msg.type === "err" && "text-terminal-red"
          )}
        >
          {msg.text}
        </div>
      ) : null}
      {loading ? (
        <div className="text-terminal-muted">{t("p.portfolio.loading")}</div>
      ) : error ? (
        <div className="text-terminal-red">{String(error.detail || error.message || error)}</div>
      ) : rows.length === 0 ? (
        <div className="text-terminal-muted">{t("p.portfolio.manage.empty")}</div>
      ) : (
        <ManageTable rows={rows} onDelete={remove} onUpdate={refresh} t={t} />
      )}
    </div>
  );
}

function FieldInput({ label, value, onChange, type = "text", placeholder, step }) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wider text-terminal-muted">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={type}
        step={step}
        placeholder={placeholder}
        className="w-full bg-transparent border border-terminal-border/60 px-2 py-1 text-xs tabular text-terminal-text outline-none focus:border-terminal-amber"
      />
    </label>
  );
}

function ManageTable({ rows, onDelete, onUpdate, t }) {
  return (
    <div className="-mx-3 overflow-x-auto px-3">
      <table className="w-full min-w-[640px] text-xs tabular">
        <thead>
          <tr className="text-left text-terminal-muted">
            <th className="py-1 pr-2">{t("p.portfolio.cols.sym")}</th>
            <th className="py-1 pr-2 text-right">{t("p.portfolio.cols.qty")}</th>
            <th className="py-1 pr-2 text-right">{t("p.portfolio.manage.cols.cost")}</th>
            <th className="py-1 pr-2 text-right">{t("p.portfolio.cols.last")}</th>
            <th className="py-1 pr-2 text-right">{t("p.portfolio.cols.unr_pl")}</th>
            <th className="py-1 pr-2">{t("p.portfolio.manage.cols.notes")}</th>
            <th className="py-1 w-10"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <ManageRow key={r.id} row={r} onDelete={onDelete} onUpdate={onUpdate} t={t} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ManageRow({ row, onDelete, onUpdate, t }) {
  const [editing, setEditing] = useState(null); // 'cost' | 'notes' | null
  const [costDraft, setCostDraft] = useState(String(row.cost_basis ?? ""));
  const [noteDraft, setNoteDraft] = useState(row.notes ?? "");

  useEffect(() => {
    setCostDraft(String(row.cost_basis ?? ""));
    setNoteDraft(row.notes ?? "");
  }, [row.cost_basis, row.notes]);

  const saveCost = useCallback(async () => {
    if (Number.isNaN(Number(costDraft))) {
      setEditing(null);
      return;
    }
    await api.updateManualPosition(row.id, { cost_basis: Number(costDraft) }).catch(() => {});
    setEditing(null);
    await onUpdate?.();
  }, [costDraft, row.id, onUpdate]);

  const saveNotes = useCallback(async () => {
    await api.updateManualPosition(row.id, { notes: noteDraft }).catch(() => {});
    setEditing(null);
    await onUpdate?.();
  }, [noteDraft, row.id, onUpdate]);

  return (
    <tr className="border-t border-terminal-border/60">
      <td className="py-1 pr-2 font-bold text-terminal-amber whitespace-nowrap">{row.symbol}</td>
      <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(row.quantity, 0)}</td>
      <td
        className="py-1 pr-2 text-right whitespace-nowrap cursor-pointer"
        onClick={() => setEditing("cost")}
      >
        {editing === "cost" ? (
          <input
            autoFocus
            value={costDraft}
            type="number"
            step="any"
            onChange={(e) => setCostDraft(e.target.value)}
            onBlur={saveCost}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveCost();
              if (e.key === "Escape") setEditing(null);
            }}
            className="w-20 bg-terminal-panelAlt border border-terminal-amber px-1 text-right text-xs tabular outline-none"
          />
        ) : (
          fmt(row.cost_basis)
        )}
      </td>
      <td className="py-1 pr-2 text-right whitespace-nowrap">{fmt(row.current_price)}</td>
      <td className={clsx("py-1 pr-2 text-right whitespace-nowrap", (row.unrealized_pl ?? 0) >= 0 ? "text-terminal-green" : "text-terminal-red")}>
        {signed(row.unrealized_pl)} ({signed(row.unrealized_pl_percent)}%)
      </td>
      <td className="py-1 pr-2 max-w-[200px] truncate cursor-pointer" onClick={() => setEditing("notes")}>
        {editing === "notes" ? (
          <input
            autoFocus
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            onBlur={saveNotes}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveNotes();
              if (e.key === "Escape") setEditing(null);
            }}
            className="w-full bg-terminal-panelAlt border border-terminal-amber px-1 text-xs outline-none"
          />
        ) : (
          row.notes || <span className="text-terminal-muted">—</span>
        )}
      </td>
      <td className="py-1 text-right">
        <button
          onClick={() => onDelete(row.id)}
          className="text-terminal-red hover:underline"
          title={t("p.portfolio.manage.delete")}
        >
          ✕
        </button>
      </td>
    </tr>
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
