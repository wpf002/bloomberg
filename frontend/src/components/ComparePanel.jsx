import { useCallback, useEffect, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

export default function ComparePanel({ symbols }) {
  // symbols is an array; use first two, or render a prompt when fewer.
  const [a, b] = [symbols?.[0], symbols?.[1]];
  const [state, setState] = useState({ loading: false, data: null, error: null });

  const fetchCompare = useCallback(async () => {
    if (!a || !b) return;
    setState({ loading: true, data: null, error: null });
    try {
      const data = await api.compare(a, b);
      setState({ loading: false, data, error: null });
    } catch (err) {
      setState({ loading: false, data: null, error: err });
    }
  }, [a, b]);

  // Reset when the symbol pair changes; do not auto-fetch (LLM cost).
  useEffect(() => {
    setState({ loading: false, data: null, error: null });
  }, [a, b]);

  const credsMissing = state.error?.status === 503;
  const ready = a && b;

  return (
    <Panel
      title={`Compare — ${a ?? "?"} vs ${b ?? "?"}`}
      accent="amber"
      actions={
        ready ? (
          <button
            onClick={fetchCompare}
            disabled={state.loading}
            className="border border-terminal-border px-2 py-0.5 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/10 disabled:opacity-50"
          >
            {state.loading ? "…" : state.data ? "Refresh" : "Run comparison"}
          </button>
        ) : null
      }
    >
      {!ready ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          Enter two symbols in the command bar:{" "}
          <span className="text-terminal-amber">AAPL MSFT COMPARE</span>.
        </div>
      ) : credsMissing ? (
        <div className="text-xs leading-relaxed text-terminal-muted">
          <p className="mb-2 text-terminal-amber">LLM comparison needs Anthropic.</p>
          <p>
            Add <code className="text-terminal-green">ANTHROPIC_API_KEY</code> to{" "}
            <code className="text-terminal-green">.env</code> and restart.
          </p>
        </div>
      ) : state.error ? (
        <div className="text-terminal-red">
          {String(state.error.detail || state.error.message || state.error)}
        </div>
      ) : state.loading ? (
        <div className="text-terminal-muted">Synthesizing comparison…</div>
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
          Press <span className="text-terminal-amber">Run comparison</span> for
          side-by-side numeric + qualitative breakdown of{" "}
          <span className="text-terminal-amber">{a}</span> vs{" "}
          <span className="text-terminal-amber">{b}</span>.
        </div>
      )}
    </Panel>
  );
}
