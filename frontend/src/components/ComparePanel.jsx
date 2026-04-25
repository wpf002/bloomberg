import { useCallback, useEffect, useMemo, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";

// LLM responses occasionally arrive wrapped in ```json … ``` even when the
// prompt forbids fences. Strip them defensively before parsing.
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

  const parsed = useMemo(() => tryParse(state.data?.body), [state.data]);
  const fallbackText = useMemo(
    () => (state.data?.body ? stripFences(state.data.body) : ""),
    [state.data]
  );

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
        <div className="space-y-3">
          {parsed ? (
            <>
              <table className="w-full text-xs tabular">
                <thead>
                  <tr className="border-b border-terminal-border/60 text-left text-[10px] uppercase tracking-widest text-terminal-muted">
                    <th className="py-1 pr-2">Metric</th>
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
                    Read
                  </div>
                  {parsed.qualitative}
                </div>
              )}
            </>
          ) : (
            // Legacy / unparseable response: render the cleaned body. Old
            // cached entries from before the JSON contract land here.
            <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-terminal-text">
              {fallbackText}
            </pre>
          )}
          <div className="border-t border-terminal-border/60 pt-2 text-[10px] uppercase tracking-widest text-terminal-muted">
            Model: {state.data.model} · {new Date(state.data.as_of).toLocaleString()} · cached 30m
          </div>
        </div>
      ) : (
        <div className="text-xs leading-relaxed text-terminal-muted">
          Press <span className="text-terminal-amber">Run comparison</span> for
          a side-by-side numeric + qualitative breakdown of{" "}
          <span className="text-terminal-amber">{a}</span> vs{" "}
          <span className="text-terminal-amber">{b}</span>.
        </div>
      )}
    </Panel>
  );
}
