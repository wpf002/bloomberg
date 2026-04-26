import { useCallback, useEffect, useMemo, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

function stripFences(s) {
  if (!s) return s;
  return s
    .replace(/^\s*```(?:json)?\s*\n?/i, "")
    .replace(/\n?```\s*$/i, "")
    .trim();
}

function tryParse(body) {
  if (!body) return null;
  const cleaned = stripFences(body);
  try {
    const parsed = JSON.parse(cleaned);
    if (parsed && Array.isArray(parsed.metrics)) return parsed;
  } catch {
    // not JSON — caller falls back to plain-text render
  }
  return null;
}

export default function ComparePanel({ symbols }) {
  const { t } = useTranslation();
  const a = symbols?.[0];
  const [b, setB] = useState(symbols?.[1] || "");
  const [bDraft, setBDraft] = useState(b);
  useEffect(() => {
    if (symbols?.[1] && symbols[1] !== b) {
      setB(symbols[1]);
      setBDraft(symbols[1]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbols?.[1]]);

  const [state, setState] = useState({ loading: false, data: null, error: null });

  const fetchCompare = useCallback(async () => {
    const target = (bDraft || b || "").trim().toUpperCase();
    if (!a || !target) return;
    if (target !== b) {
      setB(target);
      setBDraft(target);
    }
    setState({ loading: true, data: null, error: null });
    try {
      const data = await api.compare(a, target);
      setState({ loading: false, data, error: null });
    } catch (err) {
      setState({ loading: false, data: null, error: err });
    }
  }, [a, b, bDraft]);

  useEffect(() => {
    setState({ loading: false, data: null, error: null });
  }, [a, b]);

  const applyB = (raw) => {
    const next = (raw || "").trim().toUpperCase();
    if (!next) return;
    setB(next);
    setBDraft(next);
  };

  const parsed = useMemo(() => tryParse(state.data?.body), [state.data]);
  const fallbackText = useMemo(
    () => (state.data?.body ? stripFences(state.data.body) : ""),
    [state.data]
  );

  const credsMissing = state.error?.status === 503;
  const ready = a && b;

  return (
    <Panel
      title={t("p.compare.title", { a: a ?? "?", b: b || "?" })}
      accent="amber"
      actions={
        ready ? (
          <button
            onClick={fetchCompare}
            disabled={state.loading}
            className="border border-terminal-border px-2 py-0.5 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
          >
            {state.loading ? "…" : state.data ? t("p.common.refresh") : t("p.compare.run")}
          </button>
        ) : null
      }
    >
      {!a ? (
        <div className="text-xs leading-relaxed text-terminal-muted">{t("p.compare.no_active")}</div>
      ) : (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              applyB(bDraft);
            }}
            className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-widest text-terminal-muted"
          >
            <span>{t("p.compare.vs")}</span>
            <input
              value={bDraft}
              onChange={(e) => setBDraft(e.target.value.toUpperCase())}
              onBlur={() => applyB(bDraft)}
              spellCheck={false}
              autoComplete="off"
              className="w-24 border border-terminal-border bg-terminal-bg px-2 py-0.5 text-xs uppercase tracking-wider text-terminal-text focus:outline-none focus:border-terminal-amber"
              placeholder="SPY"
            />
            <span className="text-terminal-muted/70 normal-case tracking-normal text-[10px]">
              {t("p.compare.enter_hint")}
            </span>
          </form>
        </>
      )}
      {ready && credsMissing ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          <p className="mb-2 text-terminal-amber">{t("p.compare.need_anthropic_head")}</p>
          <p>{t("p.compare.need_anthropic_msg")}</p>
        </div>
      ) : ready && state.error ? (
        <div className="text-terminal-red">
          {String(state.error.detail || state.error.message || state.error)}
        </div>
      ) : ready && state.loading ? (
        <div className="text-terminal-muted">{t("p.compare.synth")}</div>
      ) : ready && state.data ? (
        <div className="space-y-3">
          {parsed ? (
            <>
              <table className="w-full text-xs tabular">
                <thead>
                  <tr className="border-b border-terminal-border/60 text-left text-[10px] uppercase tracking-widest text-terminal-muted">
                    <th className="py-1 pr-2">{t("p.compare.cols.metric")}</th>
                    <th className="py-1 pr-2 text-right text-terminal-amber">{a}</th>
                    <th className="py-1 text-right text-terminal-amber">{b}</th>
                  </tr>
                </thead>
                <tbody>
                  {parsed.metrics.map((m, i) => (
                    <tr key={i} className="border-b border-terminal-border/40">
                      <td className="py-1 pr-2 text-terminal-muted">{m.label}</td>
                      <td className="py-1 pr-2 text-right">{m.a ?? "n/a"}</td>
                      <td className="py-1 text-right">{m.b ?? "n/a"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {parsed.verdict && (
                <div className="border-l-2 border-terminal-amber pl-2 text-xs text-terminal-text">
                  {parsed.verdict}
                </div>
              )}
              {parsed.qualitative && (
                <div className="text-xs leading-relaxed text-terminal-text">
                  <div className="mb-1 text-[10px] uppercase tracking-widest text-terminal-muted">
                    {t("p.compare.read")}
                  </div>
                  {parsed.qualitative}
                </div>
              )}
            </>
          ) : (
            <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-terminal-text">
              {fallbackText}
            </pre>
          )}
          <div className="border-t border-terminal-border/60 pt-2 text-[10px] uppercase tracking-widest text-terminal-muted">
            {t("p.compare.meta", {
              model: state.data.model,
              time: new Date(state.data.as_of).toLocaleString(),
            })}
          </div>
        </div>
      ) : ready ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          {t("p.compare.hint", { a, b })}
        </div>
      ) : null}
    </Panel>
  );
}
