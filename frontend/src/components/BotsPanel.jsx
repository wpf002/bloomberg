import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import Panel from "./Panel.jsx";
import BotBuilder from "./BotBuilder.jsx";
import BotApprovals from "./BotApprovals.jsx";
import BotActivityFeed from "./BotActivityFeed.jsx";
import usePolling from "../hooks/usePolling.js";
import useStream from "../hooks/useStream.js";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const STATUS_TONE = {
  active: "text-terminal-green border-terminal-green/60",
  paused: "text-terminal-amber border-terminal-amber/60",
  killed: "text-terminal-red border-terminal-red/60",
  draft: "text-terminal-muted border-terminal-border",
  stopped: "text-terminal-muted border-terminal-border",
};

export default function BotsPanel({ activeSymbol }) {
  const { t } = useTranslation();
  const [refreshKey, setRefreshKey] = useState(0);
  const [building, setBuilding] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [err, setErr] = useState(null);

  const statusQ = usePolling(() => api.botsStatus(), 0, []);
  const botsQ = usePolling(() => api.bots(), 20_000, [refreshKey]);

  const bots = botsQ.data || [];
  const needsLogin = botsQ.error?.status === 401;

  // Default the selection to the first bot once loaded.
  useEffect(() => {
    if (!selectedId && bots.length) setSelectedId(bots[0].id);
  }, [bots, selectedId]);

  const selected = useMemo(() => bots.find((b) => b.id === selectedId) || null, [bots, selectedId]);

  const eventsQ = usePolling(
    () => (selectedId ? api.botEvents(selectedId, 50) : Promise.resolve([])),
    20_000,
    [selectedId, refreshKey]
  );
  const pendingQ = usePolling(
    () => (selectedId ? api.botPending(selectedId) : Promise.resolve([])),
    10_000,
    [selectedId, refreshKey]
  );

  const stream = useStream("/api/ws/bots", {
    onMessage: (msg) => {
      if (!msg || msg.type === "ready") return;
      if (msg.type === "bot_event") {
        setLiveEvents((prev) => [msg, ...prev].slice(0, 50));
        if (["order", "signal", "lifecycle"].includes(msg.kind)) setRefreshKey((k) => k + 1);
      } else if (msg.type === "bot_paused") {
        setRefreshKey((k) => k + 1);
      }
    },
  });

  const refresh = () => setRefreshKey((k) => k + 1);

  const lifecycle = async (fn, id, confirmMsg) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setErr(null);
    try {
      await fn(id);
      refresh();
    } catch (e) {
      setErr(e?.detail || e?.message || String(e));
    }
  };

  const mergedEvents = useMemo(() => {
    const live = liveEvents
      .filter((e) => !selectedId || e.bot_id === selectedId)
      .map((e) => ({ kind: e.kind, ts: e.ts, detail: e.detail }));
    return [...live, ...(eventsQ.data || [])].slice(0, 50);
  }, [liveEvents, eventsQ.data, selectedId]);

  const status = statusQ.data || {};

  return (
    <Panel
      title={t("p.bots.title")}
      accent="amber"
      actions={
        <span className="tabular text-terminal-muted">
          <span className="rounded border border-terminal-green/60 px-1 text-[9px] uppercase tracking-widest text-terminal-green">
            {t("p.bots.paper")}
          </span>{" "}
          {t("p.bots.ws")}{" "}
          <span className={stream.status === "open" ? "text-terminal-green" : "text-terminal-muted"}>
            {stream.status}
          </span>{" "}
          · {t("p.bots.count", { count: bots.length })}
        </span>
      }
    >
      {needsLogin ? (
        <div className="text-xs text-terminal-muted">{t("p.bots.login_required")}</div>
      ) : status.alpaca_configured === false ? (
        <div className="mb-2 border border-terminal-amber/40 bg-terminal-amber/5 px-2 py-1 text-[11px] text-terminal-amber">
          {t("p.bots.no_creds")}
        </div>
      ) : null}

      {!needsLogin && (
        <>
          <div className="mb-2 flex items-center gap-2">
            <button
              onClick={() => setBuilding((b) => !b)}
              className="border border-terminal-amber px-2 py-1 text-xs uppercase tracking-wider text-terminal-amber hover:bg-terminal-amber/10"
            >
              {building ? t("p.common.cancel") : t("p.bots.new_bot")}
            </button>
          </div>

          {building && (
            <BotBuilder
              defaultSymbol={activeSymbol}
              onCreated={() => {
                setBuilding(false);
                refresh();
              }}
              onCancel={() => setBuilding(false)}
            />
          )}

          {err && <div className="my-2 text-[11px] text-terminal-red">{err}</div>}

          <div className="mt-2 space-y-1">
            {bots.length === 0 && !building ? (
              <div className="text-xs text-terminal-muted">{t("p.bots.none_yet")}</div>
            ) : (
              bots.map((b) => (
                <BotRow
                  key={b.id}
                  bot={b}
                  selected={b.id === selectedId}
                  onSelect={() => setSelectedId(b.id)}
                  onStart={() => lifecycle(api.startBot, b.id)}
                  onPause={() => lifecycle(api.pauseBot, b.id)}
                  onStop={() => lifecycle(api.stopBot, b.id)}
                  onKill={() => lifecycle(api.killBot, b.id, t("p.bots.confirm_kill", { name: b.name }))}
                  onDelete={() => lifecycle(api.deleteBot, b.id, t("p.bots.confirm_delete", { name: b.name }))}
                  t={t}
                />
              ))
            )}
          </div>

          {selected && (
            <>
              <BotApprovals pending={pendingQ.data || []} onResolved={refresh} />
              <BotActivityFeed events={mergedEvents} />
            </>
          )}
        </>
      )}
    </Panel>
  );
}

function BotRow({ bot, selected, onSelect, onStart, onPause, onStop, onKill, onDelete, t }) {
  const tone = STATUS_TONE[bot.status] || STATUS_TONE.draft;
  const canStart = ["draft", "paused", "stopped"].includes(bot.status);
  const isActive = bot.status === "active";
  return (
    <div
      onClick={onSelect}
      className={clsx(
        "cursor-pointer border px-2 py-1 text-xs transition-colors",
        selected ? "border-terminal-amber/60 bg-terminal-panelAlt" : "border-terminal-border/60 hover:bg-terminal-panelAlt"
      )}
    >
      <div className="flex items-center gap-2">
        <span className={clsx("rounded border px-1 text-[9px] uppercase tracking-widest", tone)}>{bot.status}</span>
        <span className="font-bold text-terminal-amber">{bot.name}</span>
        <span className="truncate text-terminal-muted">
          {bot.config?.strategy} · {(bot.config?.symbols || []).join(" ")}
          {bot.decision_mode === "hybrid" ? " · AI" : ""}
          {bot.require_approval ? "" : " · auto"}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1" onClick={(e) => e.stopPropagation()}>
          {canStart && (
            <button onClick={onStart} className="border border-terminal-green px-1.5 py-0.5 uppercase tracking-wider text-terminal-green hover:bg-terminal-green/10">
              {t("p.bots.start")}
            </button>
          )}
          {isActive && (
            <button onClick={onPause} className="border border-terminal-amber px-1.5 py-0.5 uppercase tracking-wider text-terminal-amber hover:bg-terminal-amber/10">
              {t("p.bots.pause")}
            </button>
          )}
          {(isActive || bot.status === "paused") && (
            <button onClick={onStop} className="border border-terminal-border px-1.5 py-0.5 uppercase tracking-wider text-terminal-muted hover:bg-terminal-panelAlt">
              {t("p.bots.stop")}
            </button>
          )}
          {bot.status !== "killed" && (
            <button onClick={onKill} className="border border-terminal-red px-1.5 py-0.5 uppercase tracking-wider text-terminal-red hover:bg-terminal-red/10">
              {t("p.bots.kill")}
            </button>
          )}
          <button onClick={onDelete} title={t("p.common.delete")} className="text-terminal-muted hover:text-terminal-red">✕</button>
        </span>
      </div>
    </div>
  );
}
