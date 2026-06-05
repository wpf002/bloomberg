import { useState } from "react";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

// Pending proposed trades awaiting the user's approve/reject. `pending` is a
// flat list of { id, bot_id, intent, created_at }. onResolved() refreshes.
export default function BotApprovals({ pending, onResolved }) {
  const { t } = useTranslation();
  const [busyId, setBusyId] = useState(null);
  const [err, setErr] = useState(null);

  if (!pending || pending.length === 0) return null;

  const act = async (action, p) => {
    setBusyId(p.id);
    setErr(null);
    try {
      if (action === "approve") await api.approveBotPending(p.bot_id, p.id);
      else await api.rejectBotPending(p.bot_id, p.id);
      onResolved?.();
    } catch (e) {
      setErr(e?.detail || e?.message || String(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mt-3">
      <div className="text-[10px] uppercase tracking-widest text-terminal-amber">
        {t("p.bots.pending_approvals", { count: pending.length })}
      </div>
      {err && <div className="text-[11px] text-terminal-red">{err}</div>}
      <ul className="mt-1 space-y-1">
        {pending.map((p) => {
          const i = p.intent || {};
          const sizeLabel = i.qty != null ? `${i.qty} sh` : i.notional != null ? `$${i.notional}` : "";
          return (
            <li
              key={p.id}
              className="flex items-center justify-between gap-2 border border-terminal-amber/40 bg-terminal-amber/5 px-2 py-1 text-xs"
            >
              <span className="min-w-0 flex-1 truncate">
                <span className={i.side === "buy" ? "text-terminal-green" : "text-terminal-red"}>
                  {(i.side || "").toUpperCase()}
                </span>{" "}
                <span className="font-bold text-terminal-amber">{i.symbol}</span>{" "}
                <span className="text-terminal-text">{sizeLabel}</span>
                {i.reason ? <span className="text-terminal-muted"> · {i.reason}</span> : null}
              </span>
              <button
                disabled={busyId === p.id}
                onClick={() => act("approve", p)}
                className="border border-terminal-green px-2 py-0.5 uppercase tracking-wider text-terminal-green hover:bg-terminal-green/10 disabled:opacity-50"
              >
                {t("p.bots.approve")}
              </button>
              <button
                disabled={busyId === p.id}
                onClick={() => act("reject", p)}
                className="border border-terminal-red px-2 py-0.5 uppercase tracking-wider text-terminal-red hover:bg-terminal-red/10 disabled:opacity-50"
              >
                {t("p.bots.reject")}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
