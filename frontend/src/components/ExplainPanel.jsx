import { useCallback, useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

// The legacy explain prompt occasionally returns markdown bold (`**`) and
// horizontal rules (`---`) even though we render as plain text. Strip them
// client-side so the panel stays clean without re-running every cached entry.
function cleanBody(body) {
  if (!body) return body;
  return body
    .replace(/\*\*([^*]+)\*\*/g, "$1")  // **bold** → bold
    .replace(/__([^_]+)__/g, "$1")       // __bold__ → bold
    .replace(/^---+$/gm, "")              // horizontal rules
    .replace(/`([^`]+)`/g, "$1")          // inline `code`
    .replace(/\n{3,}/g, "\n\n");          // collapse runs of blanks
}

export default function ExplainPanel({ symbol }) {
  const { t } = useTranslation();
  const [state, setState] = useState({ loading: false, data: null, error: null });

  const fetchBrief = useCallback(async () => {
    if (!symbol) return;
    setState({ loading: true, data: null, error: null });
    try {
      const data = await api.explain(symbol);
      setState({ loading: false, data, error: null });
    } catch (err) {
      setState({ loading: false, data: null, error: err });
    }
  }, [symbol]);

  // Do NOT auto-fetch — LLM calls cost money. Render a "Run briefing" button
  // and only fire on explicit user action. The 30-min Redis cache keeps
  // repeated clicks cheap.
  useEffect(() => {
    setState({ loading: false, data: null, error: null });
  }, [symbol]);

  const credsMissing = state.error?.status === 503;

  return (
    <Panel
      title={t("p.explain.title", { sym: symbol ?? "—" })}
      accent="amber"
      actions={
        <button
          onClick={fetchBrief}
          disabled={!symbol || state.loading}
          className="border border-terminal-border px-2 py-0.5 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
        >
          {state.loading
            ? t("p.explain.busy")
            : state.data
              ? t("p.common.refresh")
              : t("p.explain.run")}
        </button>
      }
    >
      {credsMissing ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          <p className="mb-2 text-terminal-amber">{t("p.explain.need_anthropic_head")}</p>
          <p>{t("p.explain.need_anthropic_msg")}</p>
        </div>
      ) : state.error ? (
        <div className="text-terminal-red">
          {String(state.error.detail || state.error.message || state.error)}
        </div>
      ) : state.loading ? (
        <div className="text-terminal-muted">{t("p.explain.synth")}</div>
      ) : state.data ? (
        <div>
          <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-terminal-text">
            {cleanBody(state.data.body)}
          </pre>
          <div className="mt-3 border-t border-terminal-border/60 pt-2 text-[10px] uppercase tracking-widest text-terminal-muted">
            {t("p.explain.meta", {
              model: state.data.model,
              time: new Date(state.data.as_of).toLocaleString(),
            })}
          </div>
        </div>
      ) : (
        <div className="text-xs leading-relaxed text-terminal-muted">
          {t("p.explain.hint", { sym: symbol ?? "—" })}
        </div>
      )}
    </Panel>
  );
}
