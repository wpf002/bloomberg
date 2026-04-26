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

  // Ask tab is a multi-turn chat — history is sent back to the backend
  // so Claude can build on prior turns within the Ask conversation.
  const [askHistory, setAskHistory] = useState([]); // [{role, text}]
  const [askInput, setAskInput] = useState("");

  // Review / Picks / Brief / Alert tabs each cache their own most-recent
  // output. Switching tabs does NOT wipe state — clicking Generate within
  // a tab replaces that tab's output. Each Generate call is fresh (no
  // cross-tab context) so the user sees a clean prompt every time.
  const [tabOutputs, setTabOutputs] = useState({
    review: "",
    picks: "",
    brief: "",
    "alert-analysis": "",
  });

  const [streaming, setStreaming] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const runStream = useCallback(async (endpoint, body, onComplete) => {
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
          onComplete(buf);
        },
      );
    } catch (err) {
      setBusy(false);
      onComplete(`[advisor error: ${err.message}]`);
    }
  }, []);

  // Ask: send the question + last 12 turns of chat history.
  const onAsk = useCallback(() => {
    const q = askInput.trim();
    if (!q || busy) return;
    setAskInput("");
    const histSnapshot = askHistory.slice(-12).map((m) => ({
      role: m.role === "user" ? "user" : "assistant",
      content: m.text,
    }));
    setAskHistory((h) => [...h, { role: "user", text: q }]);
    runStream(
      "ask",
      { active_symbol: symbol, question: q, history: histSnapshot },
      (full) => setAskHistory((h) => [...h, { role: "advisor", text: full }]),
    );
  }, [askInput, busy, symbol, askHistory, runStream]);

  // One-shot generators: each replaces that tab's cached output. No
  // cross-tab history is sent — clicking Picks after Review gives a
  // fresh picks prompt without the review baked in.
  const generateOneShot = useCallback(
    (endpoint, body) => {
      runStream(endpoint, body, (full) =>
        setTabOutputs((prev) => ({ ...prev, [endpoint]: full })),
      );
    },
    [runStream],
  );

  const onReview = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, review: "" }));
    generateOneShot("review", { active_symbol: symbol });
  }, [busy, symbol, generateOneShot]);

  const onPicks = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, picks: "" }));
    generateOneShot("picks", { active_symbol: symbol });
  }, [busy, symbol, generateOneShot]);

  const onBrief = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, brief: "" }));
    generateOneShot("brief", { active_symbol: symbol });
  }, [busy, symbol, generateOneShot]);

  const onAlert = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, "alert-analysis": "" }));
    generateOneShot("alert-analysis", {
      active_symbol: symbol,
      alert: { symbol, condition: "manual trigger" },
    });
  }, [busy, symbol, generateOneShot]);

  // Generators stop mid-stream when the user switches tabs to keep the
  // displayed text from leaking across tabs.
  const switchTab = useCallback((next) => {
    setTab(next);
    setStreaming(""); // hide any in-flight stream when leaving its tab
  }, []);

  const exportBrief = useCallback(
    (format) => {
      const md = tabOutputs.brief;
      if (!md) return;
      const blob = new Blob([md], {
        type: format === "md" ? "text/markdown" : "text/plain",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aurora-brief-${new Date().toISOString().slice(0, 10)}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
    [tabOutputs.brief],
  );

  // ── tab renderers ──────────────────────────────────────────────────

  const renderAsk = () => (
    <div className="flex h-full flex-col">
      <div className="flex-1 min-h-0 overflow-auto pr-1">
        {askHistory.length === 0 && !streaming ? (
          <div className="text-terminal-muted text-[12px]">
            Active: <span className="text-terminal-amber">{symbol || "—"}</span>. Ask anything
            about the portfolio, current regime, fragility, or any symbol. The Ask tab
            keeps a running conversation; the other tabs are one-shot generators.
          </div>
        ) : null}
        {askHistory.map((m, i) => (
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
        {tab === "ask" && streaming ? (
          <div>
            <div className="text-[10px] uppercase tracking-widest text-terminal-amber">AURORA</div>
            <div className="whitespace-pre-wrap text-[12px] leading-relaxed text-terminal-text">
              {streaming}
              <span className="animate-pulse text-terminal-amber"> ▌</span>
            </div>
          </div>
        ) : null}
      </div>
      <div className="mt-2 flex gap-2 border-t border-terminal-border pt-2">
        <input
          ref={inputRef}
          value={askInput}
          onChange={(e) => setAskInput(e.target.value)}
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
          disabled={busy || !askInput.trim()}
          className="border border-terminal-amber px-3 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/20 disabled:opacity-40"
        >
          {t("aurora.advisor.send") || "Send"}
        </button>
      </div>
    </div>
  );

  const renderOneShot = (key, onGenerate, extras = null) => {
    const cached = tabOutputs[key];
    return (
      <div className="flex h-full flex-col">
        <div className="mb-2 flex flex-wrap gap-2">
          <button
            onClick={onGenerate}
            disabled={busy}
            className="border border-terminal-amber px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/20 disabled:opacity-40"
          >
            {cached ? "REGENERATE" : (t("aurora.advisor.generate") || "Generate")}
          </button>
          {extras}
        </div>
        <div className="flex-1 min-h-0 overflow-auto whitespace-pre-wrap text-[12px] leading-relaxed text-terminal-text">
          {tab === key && streaming ? (
            <>
              {streaming}
              <span className="animate-pulse text-terminal-amber"> ▌</span>
            </>
          ) : cached ? (
            cached
          ) : (
            <span className="text-terminal-muted">
              Click {cached ? "Regenerate" : "Generate"} to stream a fresh response.
            </span>
          )}
        </div>
      </div>
    );
  };

  const briefExtras = tabOutputs.brief ? (
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
  ) : null;

  return (
    <Panel
      title={t("panels.advisor")}
      accent="amber"
      actions={
        <div className="flex gap-2 text-[10px] uppercase tracking-widest">
          {TABS.map((opt) => (
            <button
              key={opt.key}
              onClick={() => switchTab(opt.key)}
              className={tab === opt.key ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
            >
              {opt.label}
            </button>
          ))}
          {tab === "ask" && askHistory.length > 0 ? (
            <button
              onClick={() => setAskHistory([])}
              className="ml-2 border border-terminal-border px-2 text-terminal-muted hover:text-terminal-red"
              title="Wipe Ask conversation thread"
            >
              CLEAR
            </button>
          ) : null}
        </div>
      }
    >
      {tab === "ask"
        ? renderAsk()
        : tab === "review"
          ? renderOneShot("review", onReview)
          : tab === "picks"
            ? renderOneShot("picks", onPicks)
            : tab === "brief"
              ? renderOneShot("brief", onBrief, briefExtras)
              : renderOneShot("alert-analysis", onAlert)}
    </Panel>
  );
}
