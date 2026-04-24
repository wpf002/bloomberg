import { useCallback, useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

export default function ExplainPanel({ symbol }) {
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
      title={`Explain — ${symbol ?? "—"}`}
      accent="amber"
      actions={
        <button
          onClick={fetchBrief}
          disabled={!symbol || state.loading}
          className="border border-terminal-border px-2 py-0.5 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
        >
          {state.loading ? "…" : state.data ? "Refresh" : "Run briefing"}
        </button>
      }
    >
      {credsMissing ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          <p className="mb-2 text-terminal-amber">LLM briefings need Anthropic.</p>
          <p>
            Add <code className="text-terminal-green">ANTHROPIC_API_KEY</code> to{" "}
            <code className="text-terminal-green">.env</code> (get one at{" "}
            <a
              href="https://console.anthropic.com/settings/keys"
              className="text-terminal-amber underline"
              target="_blank"
              rel="noreferrer"
            >
              console.anthropic.com
            </a>
            ) and restart the backend.
          </p>
        </div>
      ) : state.error ? (
        <div className="text-terminal-red">
          {String(state.error.detail || state.error.message || state.error)}
        </div>
      ) : state.loading ? (
        <div className="text-terminal-muted">
          Synthesizing briefing from fundamentals, news, and filings…
        </div>
      ) : state.data ? (
        <div>
          <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-terminal-text">
            {state.data.body}
          </pre>
          <div className="mt-3 border-t border-terminal-border/60 pt-2 text-[10px] uppercase tracking-widest text-terminal-muted">
            Model: {state.data.model} · {new Date(state.data.as_of).toLocaleString()} · cached 30m
          </div>
        </div>
      ) : (
        <div className="text-xs leading-relaxed text-terminal-muted">
          Press <span className="text-terminal-amber">Run briefing</span> to generate
          a terse analyst summary for{" "}
          <span className="text-terminal-amber">{symbol ?? "—"}</span> from current
          fundamentals, last-7-day news, and recent SEC filings.
        </div>
      )}
    </Panel>
  );
}
