import clsx from "clsx";
import { useTranslation } from "../i18n/index.jsx";

// Color per event kind so the user can scan why a bot did or didn't act.
const KIND_TONE = {
  order: "text-terminal-green",
  fill: "text-terminal-green",
  signal: "text-terminal-amber",
  llm: "text-terminal-blue",
  reject: "text-terminal-muted",
  error: "text-terminal-red",
  lifecycle: "text-terminal-blue",
  eval: "text-terminal-muted",
  warning: "text-terminal-amber",
  tune: "text-terminal-blue",
};

// Human-readable label per event kind (e.g. "lifecycle" → "LIFE CYCLE").
const KIND_LABEL = {
  order: "ORDER",
  fill: "FILL",
  signal: "SIGNAL",
  llm: "AI",
  reject: "REJECT",
  error: "ERROR",
  lifecycle: "LIFE CYCLE",
  eval: "EVAL",
  warning: "WARNING",
  tune: "TUNE",
};

// Title-case an enum value: "auto_paused" → "Auto paused", "active" → "Active".
function prettify(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}

function summarize(ev) {
  const d = ev.detail || {};
  const intent = d.intent || {};
  const size = intent.qty != null ? `${intent.qty} sh` : intent.notional != null ? `$${intent.notional}` : "";
  switch (ev.kind) {
    case "order":
      return `${(d.side || intent.side || "").toUpperCase()} ${d.symbol || intent.symbol} ${size} · ${d.status || ""}`;
    case "signal":
      return `${(intent.side || "").toUpperCase()} ${intent.symbol} ${size}${d.awaiting_approval ? " · awaiting approval" : ""}`;
    case "reject":
      return `${intent.symbol || ""} rejected · ${d.reason || ""}`;
    case "llm":
      return d.note || "advisor note";
    case "lifecycle":
      return `${prettify(d.action)}${d.reason ? ` · ${d.reason}` : ""}`;
    case "error":
      return d.reason || "error";
    case "warning":
      return d.note || prettify(d.action) || "warning";
    case "tune":
      return d.note || `params updated — regime=${d.regime} score=${d.score}`;
    default:
      return JSON.stringify(d).slice(0, 80);
  }
}

export default function BotActivityFeed({ events }) {
  const { t } = useTranslation();
  return (
    <div className="mt-3">
      <div className="text-[10px] uppercase tracking-widest text-terminal-muted">
        {t("p.bots.activity")}
      </div>
      {!events || events.length === 0 ? (
        <div className="text-xs text-terminal-muted">{t("p.bots.no_activity")}</div>
      ) : (
        <ul className="mt-1 space-y-0.5">
          {events.slice(0, 30).map((ev, i) => (
            <li key={`${ev.ts}-${i}`} className="flex items-baseline gap-2 border-b border-terminal-border/30 py-0.5 text-[11px]">
              <span className={clsx("shrink-0 whitespace-nowrap uppercase tracking-wider", KIND_TONE[ev.kind] || "text-terminal-muted")}>
                {KIND_LABEL[ev.kind] || ev.kind}:
              </span>
              <span className="min-w-0 flex-1 truncate text-terminal-text">{summarize(ev)}</span>
              <span className="shrink-0 text-terminal-muted">
                {ev.ts ? new Date(ev.ts).toLocaleTimeString() : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
