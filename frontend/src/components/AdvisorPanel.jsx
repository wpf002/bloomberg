import { useCallback, useRef, useState } from "react";
import Panel from "./Panel.jsx";
import { api } from "../lib/api.js";
import { useTranslation } from "../i18n/index.jsx";

// 11 tabs split into two visual tiers. Primary = quick generators users
// reach for daily; secondary = form-driven / situation-specific runs.
const TAB_PRIMARY = ["ask", "review", "picks", "brief", "open-brief"];
const TAB_SECONDARY = [
  "validate-thesis",
  "simulate",
  "earnings-prep",
  "rebalance",
  "post-mortem",
  "alert-analysis",
];
const TAB_KEYS = [...TAB_PRIMARY, ...TAB_SECONDARY];

// Map endpoint key -> i18n tab label key
const TAB_LABEL = {
  ask: "ask",
  review: "review",
  picks: "picks",
  brief: "brief",
  "validate-thesis": "validate",
  simulate: "simulate",
  "earnings-prep": "earnings",
  rebalance: "rebalance",
  "open-brief": "morning",
  "post-mortem": "postmortem",
  "alert-analysis": "alert",
};

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

export default function AdvisorPanel({ symbol, watchlist }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState("ask");

  // Ask is the only multi-turn tab. Everything else is stateless.
  const [askHistory, setAskHistory] = useState([]); // [{role, text}]
  const [askInput, setAskInput] = useState("");

  // Per-tab cached output (last completed stream).
  const [tabOutputs, setTabOutputs] = useState(
    () => Object.fromEntries(TAB_KEYS.filter((k) => k !== "ask").map((k) => [k, ""]))
  );

  // Per-tab form state for the new capabilities.
  const [validateForm, setValidateForm] = useState({ ticker: "", thesis: "", size: "" });
  const [simulateForm, setSimulateForm] = useState({ scenario: "" });
  const [earningsForm, setEarningsForm] = useState({ ticker: "" });
  const [postmortemForm, setPostmortemForm] = useState({
    ticker: "",
    entry_date: "",
    entry_price: "",
    exit_date: "",
    exit_price: "",
    thesis: "",
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
      { active_symbol: symbol, watchlist, question: q, history: histSnapshot },
      (full) => setAskHistory((h) => [...h, { role: "advisor", text: full }]),
    );
  }, [askInput, busy, symbol, watchlist, askHistory, runStream]);

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
    generateOneShot("review", { active_symbol: symbol, watchlist });
  }, [busy, symbol, watchlist, generateOneShot]);

  const onPicks = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, picks: "" }));
    generateOneShot("picks", { active_symbol: symbol, watchlist });
  }, [busy, symbol, watchlist, generateOneShot]);

  const onBrief = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, brief: "" }));
    generateOneShot("brief", { active_symbol: symbol, watchlist });
  }, [busy, symbol, watchlist, generateOneShot]);

  const onAlert = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, "alert-analysis": "" }));
    generateOneShot("alert-analysis", {
      active_symbol: symbol,
      watchlist,
      alert: { symbol, condition: "manual trigger" },
    });
  }, [busy, symbol, watchlist, generateOneShot]);

  const onValidate = useCallback(() => {
    if (busy || !validateForm.ticker.trim() || !validateForm.thesis.trim()) return;
    setTabOutputs((p) => ({ ...p, "validate-thesis": "" }));
    generateOneShot("validate-thesis", {
      active_symbol: symbol,
      watchlist,
      ticker: validateForm.ticker.toUpperCase().trim(),
      thesis: validateForm.thesis.trim(),
      intended_size_usd: validateForm.size ? Number(validateForm.size) : null,
    });
  }, [busy, symbol, watchlist, validateForm, generateOneShot]);

  const onSimulate = useCallback(() => {
    if (busy || !simulateForm.scenario.trim()) return;
    setTabOutputs((p) => ({ ...p, simulate: "" }));
    generateOneShot("simulate", {
      active_symbol: symbol,
      watchlist,
      scenario: simulateForm.scenario.trim(),
    });
  }, [busy, symbol, watchlist, simulateForm, generateOneShot]);

  const onEarnings = useCallback(() => {
    if (busy || !earningsForm.ticker.trim()) return;
    setTabOutputs((p) => ({ ...p, "earnings-prep": "" }));
    generateOneShot("earnings-prep", {
      active_symbol: symbol,
      watchlist,
      ticker: earningsForm.ticker.toUpperCase().trim(),
    });
  }, [busy, symbol, watchlist, earningsForm, generateOneShot]);

  const onRebalance = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, rebalance: "" }));
    generateOneShot("rebalance", { active_symbol: symbol, watchlist });
  }, [busy, symbol, watchlist, generateOneShot]);

  const onOpenBrief = useCallback(() => {
    if (busy) return;
    setTabOutputs((p) => ({ ...p, "open-brief": "" }));
    generateOneShot("open-brief", { active_symbol: symbol, watchlist });
  }, [busy, symbol, watchlist, generateOneShot]);

  const onPostMortem = useCallback(() => {
    if (
      busy ||
      !postmortemForm.ticker.trim() ||
      !postmortemForm.entry_date ||
      !postmortemForm.exit_date ||
      !postmortemForm.entry_price ||
      !postmortemForm.exit_price
    )
      return;
    setTabOutputs((p) => ({ ...p, "post-mortem": "" }));
    generateOneShot("post-mortem", {
      active_symbol: symbol,
      watchlist,
      ticker: postmortemForm.ticker.toUpperCase().trim(),
      entry_date: postmortemForm.entry_date,
      entry_price: Number(postmortemForm.entry_price),
      exit_date: postmortemForm.exit_date,
      exit_price: Number(postmortemForm.exit_price),
      original_thesis: postmortemForm.thesis.trim(),
    });
  }, [busy, symbol, watchlist, postmortemForm, generateOneShot]);

  const switchTab = useCallback((next) => {
    setTab(next);
    setStreaming(""); // hide any in-flight stream when leaving its tab
  }, []);

  // ── copy / export helpers ──────────────────────────────────────────

  const [copyFlash, setCopyFlash] = useState("");
  const copyText = useCallback(async (text) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopyFlash("ok");
      setTimeout(() => setCopyFlash(""), 1200);
    } catch {
      setCopyFlash("err");
      setTimeout(() => setCopyFlash(""), 1500);
    }
  }, []);

  const exportText = useCallback(
    (text, capability, format) => {
      if (!text) return;
      const blob = new Blob([text], {
        type: format === "md" ? "text/markdown" : "text/plain",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aurora-${capability}-${new Date().toISOString().slice(0, 10)}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
    []
  );

  // ── tab renderers ───────────────────────────────────────────────────

  const renderAsk = () => (
    <div className="flex h-full flex-col">
      <div className="flex-1 min-h-0 overflow-auto pr-1">
        {askHistory.length === 0 && !streaming ? (
          <div className="text-terminal-muted text-[12px]">
            {t("p.advisor.ask_empty", { sym: symbol || "—" })}
          </div>
        ) : null}
        {askHistory.map((m, i) => (
          <div key={i} className="mb-2">
            <div
              className={`text-[10px] uppercase tracking-widest ${m.role === "user" ? "text-terminal-blue" : "text-terminal-amber"}`}
            >
              {m.role === "user" ? t("p.advisor.you") : t("p.advisor.aurora")}
            </div>
            <div className="whitespace-pre-wrap text-[12px] leading-relaxed text-terminal-text">
              {m.text}
            </div>
          </div>
        ))}
        {tab === "ask" && streaming ? (
          <div>
            <div className="text-[10px] uppercase tracking-widest text-terminal-amber">
              {t("p.advisor.aurora")}
            </div>
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
          placeholder={t("p.advisor.ask_placeholder")}
          className="flex-1 border border-terminal-border bg-terminal-bg px-2 py-1 text-[12px] text-terminal-text outline-none focus:border-terminal-amber"
        />
        <button
          onClick={onAsk}
          disabled={busy || !askInput.trim()}
          className="border border-terminal-amber px-3 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/20 disabled:opacity-40"
        >
          {t("aurora.advisor.send")}
        </button>
      </div>
    </div>
  );

  // Generic streaming output area with copy + export buttons.
  const renderStreamingArea = (capability, runButton, formArea = null) => {
    const cached = tabOutputs[capability];
    const text = tab === capability && streaming ? streaming : cached;
    return (
      <div className="flex h-full flex-col">
        {formArea}
        <div className="mb-2 flex flex-wrap gap-2">
          {runButton}
          <button
            onClick={() => copyText(text)}
            disabled={!text}
            className="border border-terminal-border px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-muted hover:text-terminal-text disabled:opacity-30"
          >
            {copyFlash === "ok" ? t("p.advisor.copied") : t("p.advisor.copy")}
          </button>
          <button
            onClick={() => exportText(text, capability, "md")}
            disabled={!text}
            className="border border-terminal-border px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-muted hover:text-terminal-text disabled:opacity-30"
          >
            {t("p.common.export_md")}
          </button>
          <button
            onClick={() => exportText(text, capability, "txt")}
            disabled={!text}
            className="border border-terminal-border px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-muted hover:text-terminal-text disabled:opacity-30"
          >
            {t("p.common.export_txt")}
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-auto whitespace-pre-wrap text-[12px] leading-relaxed text-terminal-text">
          {tab === capability && streaming ? (
            <>
              {streaming}
              <span className="animate-pulse text-terminal-amber"> ▌</span>
            </>
          ) : cached ? (
            cached
          ) : (
            <span className="text-terminal-muted">
              {cached ? t("p.advisor.hint_regenerate") : t("p.advisor.hint_generate")}
            </span>
          )}
        </div>
      </div>
    );
  };

  const inputCls =
    "w-full border border-terminal-border bg-terminal-bg px-2 py-1 text-[12px] text-terminal-text outline-none focus:border-terminal-amber";

  // Per-tab forms.
  const validateForm_ui = (
    <div className="mb-2 flex flex-col gap-2 border-b border-terminal-border/40 pb-2">
      <input
        value={validateForm.ticker}
        onChange={(e) => setValidateForm({ ...validateForm, ticker: e.target.value.toUpperCase() })}
        placeholder={t("p.advisor.validate.ticker")}
        className={inputCls}
      />
      <textarea
        value={validateForm.thesis}
        onChange={(e) => setValidateForm({ ...validateForm, thesis: e.target.value })}
        placeholder={t("p.advisor.validate.thesis_ph")}
        rows={3}
        className={inputCls + " resize-y"}
      />
      <input
        type="number"
        value={validateForm.size}
        onChange={(e) => setValidateForm({ ...validateForm, size: e.target.value })}
        placeholder={t("p.advisor.validate.size")}
        className={inputCls}
      />
    </div>
  );

  const simulateForm_ui = (
    <div className="mb-2 border-b border-terminal-border/40 pb-2">
      <textarea
        value={simulateForm.scenario}
        onChange={(e) => setSimulateForm({ scenario: e.target.value })}
        placeholder={t("p.advisor.simulate.scenario_ph")}
        rows={3}
        className={inputCls + " resize-y"}
      />
    </div>
  );

  const earningsForm_ui = (
    <div className="mb-2 border-b border-terminal-border/40 pb-2">
      <input
        value={earningsForm.ticker}
        onChange={(e) => setEarningsForm({ ticker: e.target.value.toUpperCase() })}
        placeholder={t("p.advisor.earnings.ticker")}
        className={inputCls}
      />
    </div>
  );

  const rebalance_ui = (
    <div className="mb-2 text-[12px] text-terminal-muted">{t("p.advisor.rebalance.head")}</div>
  );
  const morning_ui = (
    <div className="mb-2 text-[12px] text-terminal-muted">{t("p.advisor.morning.head")}</div>
  );

  const postmortem_ui = (
    <div className="mb-2 grid grid-cols-2 gap-2 border-b border-terminal-border/40 pb-2">
      <input
        value={postmortemForm.ticker}
        onChange={(e) => setPostmortemForm({ ...postmortemForm, ticker: e.target.value.toUpperCase() })}
        placeholder={t("p.advisor.postmortem.ticker")}
        className={inputCls}
      />
      <span />
      <input
        type="date"
        value={postmortemForm.entry_date}
        onChange={(e) => setPostmortemForm({ ...postmortemForm, entry_date: e.target.value })}
        title={t("p.advisor.postmortem.entry_date")}
        className={inputCls}
      />
      <input
        type="number"
        step="0.01"
        value={postmortemForm.entry_price}
        onChange={(e) => setPostmortemForm({ ...postmortemForm, entry_price: e.target.value })}
        placeholder={t("p.advisor.postmortem.entry_price")}
        className={inputCls}
      />
      <input
        type="date"
        value={postmortemForm.exit_date}
        onChange={(e) => setPostmortemForm({ ...postmortemForm, exit_date: e.target.value })}
        title={t("p.advisor.postmortem.exit_date")}
        className={inputCls}
      />
      <input
        type="number"
        step="0.01"
        value={postmortemForm.exit_price}
        onChange={(e) => setPostmortemForm({ ...postmortemForm, exit_price: e.target.value })}
        placeholder={t("p.advisor.postmortem.exit_price")}
        className={inputCls}
      />
      <textarea
        value={postmortemForm.thesis}
        onChange={(e) => setPostmortemForm({ ...postmortemForm, thesis: e.target.value })}
        placeholder={t("p.advisor.postmortem.thesis_ph")}
        rows={2}
        className={inputCls + " col-span-2 resize-y"}
      />
    </div>
  );

  // Helper: build a run button with regenerate fallback label.
  const runBtn = (onClick, runLabel, capability) => {
    const cached = tabOutputs[capability];
    return (
      <button
        onClick={onClick}
        disabled={busy}
        className="border border-terminal-amber px-3 py-1 text-[10px] uppercase tracking-widest text-terminal-amber hover:bg-terminal-amber/20 disabled:opacity-40"
      >
        {cached ? t("p.common.regenerate") : runLabel}
      </button>
    );
  };

  // Single row renderer used by both tiers. Buttons are visually identical;
  // the only thing differentiating tiers is which row they sit in.
  const renderTabRow = (keys) => (
    <div className="flex flex-nowrap items-center overflow-x-auto whitespace-nowrap text-[10px] uppercase tracking-widest">
      {keys.map((key, i) => (
        <span key={key} className="flex shrink-0 items-center">
          {i > 0 ? (
            <span className="px-2 text-terminal-border" aria-hidden>
              ·
            </span>
          ) : null}
          <button
            onClick={() => switchTab(key)}
            disabled={busy}
            className={
              (tab === key
                ? "text-terminal-amber"
                : "text-terminal-muted hover:text-terminal-text") +
              " disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-terminal-muted"
            }
            title={busy ? "Wait for the current response to finish" : undefined}
          >
            {t(`p.advisor.tabs.${TAB_LABEL[key]}`)}
          </button>
        </span>
      ))}
    </div>
  );

  return (
    <Panel
      title={t("panels.advisor")}
      accent="amber"
      actions={
        <div className="flex items-center gap-3">
          {renderTabRow(TAB_PRIMARY)}
          {tab === "ask" && askHistory.length > 0 ? (
            <button
              onClick={() => setAskHistory([])}
              className="ml-2 border border-terminal-border px-2 text-[10px] uppercase tracking-widest text-terminal-muted hover:text-terminal-red"
              title={t("p.advisor.clear_title")}
            >
              {t("p.common.clear")}
            </button>
          ) : null}
        </div>
      }
    >
      <div className="flex h-full flex-col">
        <div className="mb-2 flex items-center gap-2 border-b border-terminal-border/40 pb-2 text-[10px] uppercase tracking-widest text-terminal-muted/70">
          <span className="shrink-0 text-terminal-muted/60">More:</span>
          {renderTabRow(TAB_SECONDARY)}
        </div>
        <div className="min-h-0 flex-1">
          {tab === "ask" ? (
            renderAsk()
          ) : tab === "review" ? (
            renderStreamingArea("review", runBtn(onReview, t("aurora.advisor.generate"), "review"))
          ) : tab === "picks" ? (
            renderStreamingArea("picks", runBtn(onPicks, t("aurora.advisor.generate"), "picks"))
          ) : tab === "brief" ? (
            renderStreamingArea("brief", runBtn(onBrief, t("aurora.advisor.generate"), "brief"))
          ) : tab === "validate-thesis" ? (
            renderStreamingArea(
              "validate-thesis",
              runBtn(onValidate, t("p.advisor.validate.run"), "validate-thesis"),
              validateForm_ui,
            )
          ) : tab === "simulate" ? (
            renderStreamingArea(
              "simulate",
              runBtn(onSimulate, t("p.advisor.simulate.run"), "simulate"),
              simulateForm_ui,
            )
          ) : tab === "earnings-prep" ? (
            renderStreamingArea(
              "earnings-prep",
              runBtn(onEarnings, t("p.advisor.earnings.run"), "earnings-prep"),
              earningsForm_ui,
            )
          ) : tab === "rebalance" ? (
            renderStreamingArea(
              "rebalance",
              runBtn(onRebalance, t("p.advisor.rebalance.run"), "rebalance"),
              rebalance_ui,
            )
          ) : tab === "open-brief" ? (
            renderStreamingArea(
              "open-brief",
              runBtn(onOpenBrief, t("p.advisor.morning.run"), "open-brief"),
              morning_ui,
            )
          ) : tab === "post-mortem" ? (
            renderStreamingArea(
              "post-mortem",
              runBtn(onPostMortem, t("p.advisor.postmortem.run"), "post-mortem"),
              postmortem_ui,
            )
          ) : (
            renderStreamingArea("alert-analysis", runBtn(onAlert, t("aurora.advisor.generate"), "alert-analysis"))
          )}
        </div>
      </div>
    </Panel>
  );
}
