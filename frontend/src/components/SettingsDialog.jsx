import { useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

// A single (broker, mode) credential slot: shows configured status (masked,
// never the secret) and lets the user save or clear keys.
function BrokerSlot({ broker, mode, label, configured, last4, onSaved }) {
  const { t } = useTranslation();
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.putBrokerCreds(broker, mode, { key: key.trim(), secret: secret.trim() });
      setKey("");
      setSecret("");
      onSaved?.();
    } catch (e) {
      setErr(e?.detail || e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.deleteBrokerCreds(broker, mode);
      onSaved?.();
    } catch (e) {
      setErr(e?.detail || e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border border-terminal-border/60 p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-bold text-terminal-amber">{label}</span>
        {configured ? (
          <span className="text-[10px] uppercase tracking-widest text-terminal-green">
            {t("p.settings.configured")} ····{last4}
          </span>
        ) : (
          <span className="text-[10px] uppercase tracking-widest text-terminal-muted">
            {t("p.settings.not_set")}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-1">
        <input
          type="password"
          autoComplete="off"
          placeholder={t("p.settings.api_key")}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          className="border border-terminal-border bg-terminal-bg px-2 py-1 text-xs text-terminal-text focus:outline-none focus:border-terminal-amber"
        />
        <input
          type="password"
          autoComplete="off"
          placeholder={t("p.settings.api_secret")}
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          className="border border-terminal-border bg-terminal-bg px-2 py-1 text-xs text-terminal-text focus:outline-none focus:border-terminal-amber"
        />
      </div>
      {err && <div className="mt-1 text-[11px] text-terminal-red">{err}</div>}
      <div className="mt-1 flex items-center gap-2">
        <button
          onClick={save}
          disabled={busy || !key.trim() || !secret.trim()}
          className="border border-terminal-amber px-2 py-0.5 text-[10px] uppercase tracking-wider text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
        >
          {t("p.common.save")}
        </button>
        {configured && (
          <button
            onClick={clear}
            disabled={busy}
            className="border border-terminal-red px-2 py-0.5 text-[10px] uppercase tracking-wider text-terminal-red hover:bg-terminal-red/10 disabled:opacity-50"
          >
            {t("p.common.clear")}
          </button>
        )}
      </div>
    </div>
  );
}

export default function SettingsDialog({ open, onClose }) {
  const { t } = useTranslation();
  const [slots, setSlots] = useState([]);
  const [status, setStatus] = useState({});
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const [creds, st] = await Promise.all([api.brokerCreds(), api.botsStatus()]);
      setSlots(creds?.brokers || []);
      setStatus(st || {});
    } catch (e) {
      setErr(e?.detail || e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) load();
  }, [open]);

  if (!open) return null;

  const slotFor = (broker, mode) => slots.find((s) => s.broker === broker && s.mode === mode);
  const liveEnabled = !!status.live_enabled;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div className="w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <Panel
          title={t("p.settings.title")}
          accent="amber"
          actions={
            <button onClick={onClose} className="text-terminal-muted hover:text-terminal-text">
              ESC ✕
            </button>
          }
        >
          <p className="mb-2 text-[11px] leading-relaxed text-terminal-muted">
            {t("p.settings.blurb")}
          </p>
          {err && <div className="mb-2 text-[11px] text-terminal-red">{err}</div>}
          {loading ? (
            <div className="text-xs text-terminal-muted">{t("p.common.loading")}</div>
          ) : (
            <div className="space-y-2">
              <BrokerSlot
                broker="alpaca"
                mode="paper"
                label={t("p.settings.alpaca_paper")}
                configured={!!slotFor("alpaca", "paper")}
                last4={slotFor("alpaca", "paper")?.key_last4}
                onSaved={load}
              />
              <BrokerSlot
                broker="alpaca"
                mode="live"
                label={
                  t("p.settings.alpaca_live") + (liveEnabled ? "" : ` · ${t("p.settings.live_disabled")}`)
                }
                configured={!!slotFor("alpaca", "live")}
                last4={slotFor("alpaca", "live")?.key_last4}
                onSaved={load}
              />
            </div>
          )}
          <p className="mt-3 text-[10px] leading-relaxed text-terminal-muted/80">
            {t("p.settings.security_note")}
          </p>
        </Panel>
      </div>
    </div>
  );
}
