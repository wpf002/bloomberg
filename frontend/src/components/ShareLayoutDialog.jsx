import { useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

// Modal: lets a signed-in user publish their current Launchpad as a public
// URL, and shows their existing shares with a delete button. Layout snapshot
// happens on the server (POST /api/me/layout/share) so we don't have to pass
// JSON across the wire — it reads the user's last-saved row directly.
export default function ShareLayoutDialog({ open, onClose }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [created, setCreated] = useState(null);
  const [shares, setShares] = useState([]);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setCreated(null);
    api.myShares().then(setShares).catch(() => setShares([]));
  }, [open]);

  if (!open) return null;

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const res = await api.shareLayout(name.trim());
      setCreated(res);
      setName("");
      const updated = await api.myShares().catch(() => null);
      if (updated) setShares(updated);
    } catch (err) {
      setError(err?.detail || err?.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (slug) => {
    setBusy(true);
    try {
      await api.deleteShare(slug);
      setShares((prev) => prev.filter((s) => s.slug !== slug));
      if (created?.slug === slug) setCreated(null);
    } catch (err) {
      setError(err?.detail || err?.message || String(err));
    } finally {
      setBusy(false);
    }
  };

  const shareUrl = (slug) =>
    `${window.location.origin}${window.location.pathname}?layout=${encodeURIComponent(slug)}`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
      onClick={onClose}
    >
      <div className="w-full max-w-xl" onClick={(e) => e.stopPropagation()}>
        <Panel
          title="Share Launchpad layout"
          accent="amber"
          actions={
            <button onClick={onClose} className="text-terminal-muted hover:text-terminal-text">
              ESC ✕
            </button>
          }
        >
          <form onSubmit={submit} className="flex items-end gap-2 text-xs">
            <label className="flex-1 flex flex-col gap-0.5">
              <span className="text-[10px] uppercase tracking-widest text-terminal-muted">
                Name (e.g. "scalper", "macro view")
              </span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={80}
                className="border border-terminal-border bg-terminal-bg px-2 py-1 text-terminal-text focus:outline-none focus:border-terminal-amber"
              />
            </label>
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className="border border-terminal-amber px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
            >
              {busy ? "Saving…" : "Publish"}
            </button>
          </form>

          {error ? (
            <div className="mt-2 text-[11px] text-terminal-red">{error}</div>
          ) : null}

          {created ? (
            <div className="mt-3 border border-terminal-green/50 bg-terminal-green/5 p-2 text-[11px]">
              <div className="text-terminal-green">
                Published — share this URL:
              </div>
              <input
                readOnly
                value={shareUrl(created.slug)}
                onFocus={(e) => e.target.select()}
                className="mt-1 w-full bg-transparent font-mono text-[11px] text-terminal-text outline-none"
              />
              <button
                type="button"
                onClick={() => navigator.clipboard?.writeText(shareUrl(created.slug))}
                className="mt-1 text-[10px] uppercase tracking-widest text-terminal-amber hover:underline"
              >
                Copy URL
              </button>
            </div>
          ) : null}

          <div className="mt-4">
            <div className="text-[10px] uppercase tracking-widest text-terminal-muted">
              Your shares ({shares.length})
            </div>
            {shares.length === 0 ? (
              <div className="text-xs text-terminal-muted">
                None yet. Publish your current layout above.
              </div>
            ) : (
              <ul className="mt-1 space-y-1">
                {shares.map((s) => (
                  <li
                    key={s.slug}
                    className="flex items-baseline justify-between gap-2 border-b border-terminal-border/40 py-1 text-xs"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="font-bold text-terminal-amber">{s.name}</div>
                      <div className="truncate text-[11px] text-terminal-muted">
                        {shareUrl(s.slug)} · {s.view_count} views
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard?.writeText(shareUrl(s.slug))}
                      className="text-terminal-amber hover:underline"
                    >
                      copy
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(s.slug)}
                      className="text-terminal-red hover:underline"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <p className="mt-3 text-[10px] leading-relaxed text-terminal-muted">
            The current layout is captured at publish time; later edits don't
            update existing shares (publish again for a new snapshot). Anyone
            with the URL can view it read-only — they don't see your watchlist
            or alert rules.
          </p>
        </Panel>
      </div>
    </div>
  );
}
