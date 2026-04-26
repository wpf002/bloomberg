import { useCallback, useRef, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

const TABS = [
  { key: "ask", label: "ASK" },
  { key: "review", label: "REVIEW" },
  { key: "picks", label: "PICKS" },
  { key: "brief", label: "BRIEF" },
  { key: "alert-analysis", label: "ALERT" },
];

async function streamInto(response, onChunk, onDone) {
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    onChunk(`[${response.status}] ${text || response.statusText}`);
    onDone();
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    onChunk(decoder.decode(value, { stream: true }));
  }
  onDone();
}

export default function AdvisorPanel({ symbol }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState("ask");
  const [history, setHistory] = useState([]);  // [{role, text}]
  const [streaming, setStreaming] = useState("");
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [briefMd, setBriefMd] = useState("");
  const inputRef = useRef(null);

  const runStream = useCallback(
    async (endpoint, body, accumulator) => {
      setBusy(true);
      setStreaming("");
      try {
        const response = await api.advisorStream(endpoint, body);
        let buf = "";
        await streamInto(
          response,
          (chunk) => {
            buf += chunk;
            setStreaming(buf);
          },
          () => {
            setStreaming("");
            setBusy(false);
            accumulator(buf);
          },
        );
      } catch (err) {
        setBusy(false);
        accumulator(`[advisor error: ${err.message}]`);
      }
    },
    [],
  );

  // The chat history is one continuous thread across all five tabs so
  // the AI can build on prior turns. We send it back to the backend on
  // every call (last 12 turns is plenty of context without exhausting
  // token budget), mapped to {role, content} pairs the API expects.
  const apiHistory = useCallback(
    () =>
      history.slice(-12).map((m) => ({
        role: m.role === "user" ? "user" : "assistant",
        content: m.text,
      })),
    [history],
  );

  const onAsk = useCallback(() => {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    const histSnapshot = apiHistory();
    setHistory((h) => [...h, { role: "user", text: q }]);
    runStream(
      "ask",
      { active_symbol: symbol, question: q, history: histSnapshot },
      (full) => setHistory((h) => [...h, { role: "advisor", text: full }]),
    );
  }, [input, busy, symbol, runStream, apiHistory]);

  const onReview = useCallback(() => {
    if (busy) return;
    const histSnapshot = apiHistory();
    setHistory((h) => [...h, { role: "user", text: "[Generate portfolio review]" }]);
    runStream(
      "review",
      { active_symbol: symbol, history: histSnapshot },
      (full) => setHistory((h) => [...h, { role: "advisor", text: full }]),
    );
  }, [busy, symbol, runStream, apiHistory]);

  const onPicks = useCallback(() => {
    if (busy) return;
    const histSnapshot = apiHistory();
    setHistory((h) => [...h, { role: "user", text: "[Generate picks]" }]);
    runStream(
      "picks",
      { active_symbol: symbol, history: histSnapshot },
      (full) => setHistory((h) => [...h, { role: "advisor", text: full }]),
    );
  }, [busy, symbol, runStream, apiHistory]);

  const onBrief = useCallback(() => {
    if (busy) return;
    setBriefMd("");
    const histSnapshot = apiHistory();
    runStream(
      "brief",
      { active_symbol: symbol, history: histSnapshot },
      (full) => setBriefMd(full),
    );
  }, [busy, symbol, runStream, apiHistory]);

  const onAlert = useCallback(() => {
    if (busy) return;
    const histSnapshot = apiHistory();
    setHistory((h) => [...h, { role: "user", text: "[Analyze most-recent alert]" }]);
    runStream(
      "alert-analysis",
      {
        active_symbol: symbol,
        alert: { symbol, condition: "manual trigger" },
        history: histSnapshot,
      },
      (full) => setHistory((h) => [...h, { role: "advisor", text: full }]),
    );
  }, [busy, symbol, runStream, apiHistory]);

  const exportBrief = useCallback(
    (format) => {
      if (!briefMd) return;
      const blob =
        format === "md"
          ? new Blob([briefMd], { type: "text/markdown" })
          : new Blob([briefMd], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aurora-brief-${new Date().toISOString().slice(0, 10)}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
    [briefMd],
  );

  const renderChat = () => (
    <div className="flex h-full flex-col">
      <div className="flex-1 min-h-0 overflow-auto pr-1">
        {history.length === 0 && !streaming ? (
          <div className="text-terminal-muted text-[12px]">
            Active: <span className="text-terminal-amber">{symbol || "—"}</span>. Ask anything
            about the portfolio, current regime, fragility, or any symbol. Context is sent on every
            call — the advisor never invents numbers.
          </div>
        ) : null}
        {history.map((m, i) => (
          <div key={i} className="mb-2">
            <div
              className={`text-[10px] uppercase tracking-widest ${m.role === "user" ? "text-terminal-blue" : "text-terminal-amber"}`}
            >
              {m.role === "user" ? "YOU" : "AURORA"}
            </div>
            <div className="whitespace-pre-wrap text-[12px] leading-relaxed text-terminal-text">
              {m.text}
            </div>
          </div>
        ))}
        {streaming ? (
          <div>
            <div className="text-[10px] uppercase tracking-widest text-terminal-amber">AURORA</div>
            <div className="whitespace-pre-wrap text-[12px] leading-relaxed text-terminal-text">
              {streaming}
              <span className="animate-pulse text-terminal-amber"> ▌</span>
            </div>
          </div>
        ) : null}
      </div>
      {tab === "ask" ? (
        <div className="mt-2 flex gap-2 border-t border-terminal-border pt-2">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onAsk();
              }
            }}
            placeholder={t("aurora.advisor.placeholder") || "Ask…"}
            className="flex-1 border border-terminal-border bg-terminal-bg px-2 py-1 text-[12px] text-terminal-text outline-none focus:border-terminal-amber"
          />
          <button
            onClick={onAsk}
            disabled={busy || !input.trim()}
            className="border border-terminal-amber px-3 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/20 disabled:opacity-40"
          >
            {t("aurora.advisor.send") || "Send"}
          </button>
        </div>
      ) : (
        <div className="mt-2 flex gap-2 border-t border-terminal-border pt-2">
          <button
            onClick={
              tab === "review" ? onReview : tab === "picks" ? onPicks : tab === "alert-analysis" ? onAlert : onBrief
            }
            disabled={busy}
            className="border border-terminal-amber px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/20 disabled:opacity-40"
          >
            {t("aurora.advisor.generate") || "Generate"}
          </button>
        </div>
      )}
    </div>
  );

  const renderBrief = () => (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex gap-2">
        <button
          onClick={onBrief}
          disabled={busy}
          className="border border-terminal-amber px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/20 disabled:opacity-40"
        >
          {t("aurora.advisor.generate") || "Generate"}
        </button>
        {briefMd ? (
          <>
            <button
              onClick={() => exportBrief("md")}
              className="border border-terminal-border px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-muted hover:text-terminal-text"
            >
              EXPORT MD
            </button>
            <button
              onClick={() => exportBrief("txt")}
              className="border border-terminal-border px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-muted hover:text-terminal-text"
            >
              EXPORT TXT
            </button>
          </>
        ) : null}
      </div>
      <div className="flex-1 min-h-0 overflow-auto whitespace-pre-wrap text-[12px] leading-relaxed text-terminal-text">
        {streaming || briefMd || (
          <span className="text-terminal-muted">Click Generate to stream this week's brief.</span>
        )}
        {streaming ? <span className="animate-pulse text-terminal-amber"> ▌</span> : null}
      </div>
    </div>
  );

  return (
    <Panel
      title={t("panels.advisor")}
      accent="amber"
      actions={
        <div className="flex gap-2 text-[10px] uppercase tracking-widest">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={tab === t.key ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
            >
              {t.label}
            </button>
          ))}
          {history.length > 0 ? (
            <button
              onClick={() => {
                setHistory([]);
                setBriefMd("");
              }}
              className="ml-2 border border-terminal-border px-2 text-terminal-muted hover:text-terminal-red"
              title="Wipe conversation thread and start fresh"
            >
              CLEAR
            </button>
          ) : null}
        </div>
      }
    >
      {tab === "brief" ? renderBrief() : renderChat()}
    </Panel>
  );
}
