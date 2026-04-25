import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { MNEMONICS, matchMnemonics, parseCommand } from "../lib/mnemonics.js";

const HISTORY_KEY = "bt:cmd-history";
const HISTORY_MAX = 30;

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((s) => typeof s === "string") : [];
  } catch {
    return [];
  }
}

function saveHistory(entries) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_MAX)));
  } catch {
    // ignore quota / privacy errors
  }
}

// Given "AAPL DE", returns { head: "AAPL ", tail: "DE" } so we can replace
// just the mnemonic portion when applying a suggestion.
function splitTail(input) {
  const up = input.toUpperCase();
  const lastSpace = up.lastIndexOf(" ");
  if (lastSpace < 0) return { head: "", tail: up };
  return { head: up.slice(0, lastSpace + 1), tail: up.slice(lastSpace + 1) };
}

export default function CommandBar({ onCommand, activeSymbol, lastCommand }) {
  const [value, setValue] = useState("");
  const [clock, setClock] = useState(() => new Date());
  const [history, setHistory] = useState(() => loadHistory());
  const [historyIdx, setHistoryIdx] = useState(-1); // -1 == not navigating history
  const [suggestIdx, setSuggestIdx] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const preview = useMemo(() => parseCommand(value), [value]);
  const { tail } = splitTail(value);
  const suggestions = useMemo(() => (tail ? matchMnemonics(tail, 6) : []), [tail]);
  const showSuggestions = suggestions.length > 0 && tail !== suggestions[0]?.key;
  const ghost =
    showSuggestions && suggestions[suggestIdx]
      ? suggestions[suggestIdx].key.slice(tail.length)
      : "";

  // Reset suggestion highlight whenever the suggestion set changes.
  useEffect(() => {
    setSuggestIdx(0);
  }, [suggestions.map((s) => s.key).join("|")]);

  const applySuggestion = (sug) => {
    if (!sug) return;
    const { head } = splitTail(value);
    setValue(head + sug.key);
    setHistoryIdx(-1);
  };

  const runCommand = (cmdText) => {
    const parsed = parseCommand(cmdText);
    if (!parsed) return;
    onCommand?.(parsed);
    const next = [cmdText.trim().toUpperCase(), ...history.filter((h) => h !== cmdText.trim().toUpperCase())].slice(
      0,
      HISTORY_MAX
    );
    setHistory(next);
    saveHistory(next);
    setValue("");
    setHistoryIdx(-1);
  };

  const onKeyDown = (e) => {
    // Tab completes the highlighted suggestion into the input.
    if (e.key === "Tab" && showSuggestions) {
      e.preventDefault();
      applySuggestion(suggestions[suggestIdx]);
      return;
    }
    // Arrows navigate suggestions if visible, otherwise history.
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (showSuggestions) {
        setSuggestIdx((i) => Math.min(i + 1, suggestions.length - 1));
      } else if (history.length) {
        const nextIdx = Math.max(historyIdx - 1, -1);
        setHistoryIdx(nextIdx);
        setValue(nextIdx === -1 ? "" : history[nextIdx]);
      }
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (showSuggestions) {
        setSuggestIdx((i) => Math.max(i - 1, 0));
      } else if (history.length) {
        const nextIdx = Math.min(historyIdx + 1, history.length - 1);
        setHistoryIdx(nextIdx);
        setValue(history[nextIdx]);
      }
      return;
    }
    if (e.key === "Escape") {
      setValue("");
      setHistoryIdx(-1);
      return;
    }
  };

  const submit = (e) => {
    e.preventDefault();
    if (showSuggestions && suggestions[suggestIdx] && tail) {
      // Complete + submit in one Enter press if the user never finished typing
      // the mnemonic.
      const { head } = splitTail(value);
      const completed = head + suggestions[suggestIdx].key;
      runCommand(completed);
      return;
    }
    if (!value.trim()) return;
    runCommand(value);
  };

  const mnemonicHint = preview?.mnemonic
    ? `${preview.symbol ?? activeSymbol ?? "—"} ${preview.mnemonic} · ${preview.description}`
    : "<SYMBOL> <MNEMONIC>  e.g.  AAPL DES · AAPL GP · AAPL N · AAPL OMON · HELP";

  return (
    <header className="flex flex-col border-b border-terminal-border bg-terminal-panelAlt">
      <div className="flex items-center gap-4 px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-terminal-amber shadow-[0_0_8px_#ff9f1c]" />
          <span className="text-sm font-bold tracking-widest text-terminal-amber">
            BLOOMBERG TERMINAL
          </span>
          <span className="text-[10px] uppercase tracking-wider text-terminal-muted">
            v0.1 · Phase 6 · Public Edition
          </span>
        </div>
        <form onSubmit={submit} className="relative flex-1">
          <div className="flex items-center border border-terminal-border bg-terminal-bg px-2 py-1">
            <span className="pr-2 text-terminal-amber">›</span>
            <div className="relative flex-1">
              <input
                ref={inputRef}
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  setHistoryIdx(-1);
                }}
                onKeyDown={onKeyDown}
                placeholder={`Active: ${activeSymbol ?? "—"}   Enter: <SYMBOL> <FN>   (HELP for mnemonics)`}
                className="relative z-10 w-full bg-transparent text-sm uppercase tracking-wider text-terminal-text placeholder:text-terminal-muted/60 focus:outline-none"
                spellCheck={false}
                autoComplete="off"
              />
              {ghost && value && (
                <span
                  aria-hidden
                  className="pointer-events-none absolute left-0 top-0 z-0 select-none whitespace-pre text-sm uppercase tracking-wider text-terminal-muted/50"
                >
                  <span className="invisible">{value}</span>
                  {ghost}
                </span>
              )}
            </div>
            <span className="text-[10px] uppercase tracking-widest text-terminal-muted">
              {showSuggestions ? "TAB" : "ENTER"}
            </span>
          </div>
          {showSuggestions && (
            <ul className="absolute left-0 right-0 top-full z-20 mt-1 border border-terminal-border bg-terminal-panel shadow-panel">
              {suggestions.map((s, i) => (
                <li
                  key={s.key}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    applySuggestion(s);
                    inputRef.current?.focus();
                  }}
                  className={clsx(
                    "flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1 text-xs",
                    i === suggestIdx
                      ? "bg-terminal-amber/10 text-terminal-amber"
                      : "text-terminal-text hover:bg-terminal-panelAlt"
                  )}
                >
                  <span className="font-bold tracking-wider">
                    {s.key.split("").map((c, ci) => (
                      <span
                        key={ci}
                        className={
                          s.matchedIndex.includes(ci)
                            ? "text-terminal-amber"
                            : "text-terminal-muted"
                        }
                      >
                        {c}
                      </span>
                    ))}
                  </span>
                  <span className="truncate text-terminal-muted">{s.description}</span>
                </li>
              ))}
            </ul>
          )}
        </form>
        <div className="tabular text-xs text-terminal-muted">
          {clock.toUTCString().split(" ").slice(0, 5).join(" ")} UTC
        </div>
      </div>
      <div className="flex items-center gap-2 overflow-x-auto border-t border-terminal-border/60 px-4 py-1 text-[10px] uppercase tracking-widest text-terminal-muted">
        <span className="shrink-0">Quick:</span>
        {QUICK_ACTIONS.map(({ mnemonic, label, title }) => (
          <button
            key={mnemonic}
            onClick={() => {
              const symbolsPart =
                mnemonic === "COMPARE"
                  ? (activeSymbol ? `${activeSymbol} SPY` : "AAPL SPY")
                  : (activeSymbol ?? "");
              const cmd = [symbolsPart, mnemonic].filter(Boolean).join(" ").trim();
              runCommand(cmd);
            }}
            title={title}
            className="shrink-0 border border-terminal-border/60 px-2 py-0.5 text-terminal-amber hover:border-terminal-amber hover:bg-terminal-amber/10"
          >
            {label}
          </button>
        ))}
        <span className="ml-auto shrink-0 truncate">
          {lastCommand ? (
            <>
              Last: <span className="text-terminal-amber">{lastCommand}</span>
              {history.length > 0 && (
                <span className="pl-2 text-terminal-muted/70">
                  · ↑/↓ history ({history.length})
                </span>
              )}
            </>
          ) : (
            <>Click a chip · or type <span className="text-terminal-amber">HELP</span></>
          )}
        </span>
      </div>
    </header>
  );
}

// Chips always visible beneath the command bar. Each runs "<active> <MNEMONIC>"
// when clicked. The COMPARE chip supplies SPY as a default second symbol so
// new users aren't blocked by parser requirements.
const QUICK_ACTIONS = [
  { mnemonic: "DES",     label: "DES · describe",          title: "Company description + fundamentals" },
  { mnemonic: "GP",      label: "GP · chart",              title: "Price chart" },
  { mnemonic: "N",       label: "N · news",                title: "Latest news" },
  { mnemonic: "OMON",    label: "OMON · options",          title: "Options chain + Greeks" },
  { mnemonic: "FIL",     label: "FIL · filings",           title: "SEC filings" },
  { mnemonic: "SIZE",    label: "SIZE · position size",    title: "Position-size calculator" },
  { mnemonic: "EXPLAIN", label: "EXPLAIN · AI briefing",   title: "LLM briefing (news + filings + fundamentals)" },
  { mnemonic: "COMPARE", label: "COMPARE · vs SPY",        title: "LLM side-by-side (active vs SPY by default)" },
  { mnemonic: "PORT",    label: "PORT · portfolio",        title: "Paper portfolio" },
  { mnemonic: "TRADE",   label: "TRADE · order ticket",    title: "Submit a paper order via Alpaca" },
  { mnemonic: "ALRT",    label: "ALRT · alerts",           title: "Create / monitor rule-based alerts" },
  { mnemonic: "PAYOFF",  label: "PAYOFF · option strategy", title: "Multi-leg options payoff diagram" },
  { mnemonic: "SQL",     label: "SQL · workbench",         title: "DuckDB SQL workbench (bars / macro / filings)" },
  { mnemonic: "SRCH",    label: "SRCH · filings search",   title: "Full-text filings search via Meilisearch" },
  { mnemonic: "HELP",    label: "HELP · all mnemonics",    title: "Full mnemonic reference" },
];

export function MnemonicHelp() {
  return (
    <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {Object.entries(MNEMONICS).map(([key, def]) => (
        <li key={key} className="flex justify-between gap-2 border-b border-terminal-border/40 py-0.5">
          <span className="font-bold text-terminal-amber">{key}</span>
          <span className="text-terminal-muted">{def.description}</span>
        </li>
      ))}
    </ul>
  );
}
