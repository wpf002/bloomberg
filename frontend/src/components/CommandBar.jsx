import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { useTranslation } from "../i18n/index.jsx";
import { api } from "../lib/api.js";
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
  const { t } = useTranslation();
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
  const mnemonicMatches = useMemo(() => (tail ? matchMnemonics(tail, 6) : []), [tail]);

  // Symbol autocomplete — debounced fetch from /api/symbols/search whenever
  // the user is typing a token. Symbol matches show alongside mnemonic
  // matches in the suggestion dropdown.
  const [symbolMatches, setSymbolMatches] = useState([]);
  useEffect(() => {
    if (!tail || tail.length < 1) {
      setSymbolMatches([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .searchSymbols(tail, 6)
        .then((rows) => {
          if (cancelled) return;
          setSymbolMatches(Array.isArray(rows) ? rows : []);
        })
        .catch(() => {
          if (!cancelled) setSymbolMatches([]);
        });
    }, 150);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [tail]);

  // Merge mnemonic + symbol matches into a unified suggestion list.
  // Each item has `kind: "mnemonic" | "symbol"`, a `key` we'd insert
  // into the input, and display data. Symbols come first because that's
  // what the user is typically reaching for when they enter a partial
  // ticker; mnemonics fall through after.
  const suggestions = useMemo(() => {
    const list = [];
    const seen = new Set();
    for (const s of symbolMatches) {
      const key = (s.symbol || "").toUpperCase();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      list.push({ kind: "symbol", key, name: s.name || "", exchange: s.exchange || "" });
    }
    for (const m of mnemonicMatches) {
      if (seen.has(m.key)) continue;
      seen.add(m.key);
      list.push({
        kind: "mnemonic",
        key: m.key,
        description: m.description,
        matchedIndex: m.matchedIndex,
      });
    }
    return list.slice(0, 8);
  }, [symbolMatches, mnemonicMatches]);

  // Show the dropdown whenever we have suggestions, except when there's
  // exactly one and the user has already typed it verbatim (no value in
  // suggesting what they're already typing). Earlier this check fired
  // greedily and hid the dropdown when the user typed the exact symbol
  // of the first match — which broke the symbol-search autocomplete
  // for any ticker that happened to be a real ticker (e.g. "AAP").
  const showSuggestions =
    suggestions.length > 0 &&
    !(suggestions.length === 1 && tail === suggestions[0]?.key);
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
            {t("app.title").toUpperCase()}
          </span>
          <span className="text-[10px] uppercase tracking-wider text-terminal-muted">
            v0.1 · {t("app.edition")}
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
                placeholder={t("command.placeholder", { symbol: activeSymbol ?? t("command.placeholderEmpty") })}
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
              {showSuggestions ? t("command.tab") : t("command.enter")}
            </span>
          </div>
          {showSuggestions && (
            <ul className="absolute left-0 right-0 top-full z-20 mt-1 border border-terminal-border bg-terminal-panel shadow-panel">
              {suggestions.map((s, i) => (
                <li
                  key={`${s.kind}-${s.key}`}
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
                  <span className="flex items-baseline gap-2">
                    <span
                      className={clsx(
                        "rounded border px-1 text-[9px] uppercase tracking-widest",
                        s.kind === "symbol"
                          ? "border-terminal-blue/60 text-terminal-blue"
                          : "border-terminal-amber/60 text-terminal-amber"
                      )}
                    >
                      {s.kind === "symbol" ? "SYM" : "FN"}
                    </span>
                    <span className="font-bold tracking-wider">
                      {s.kind === "mnemonic"
                        ? s.key.split("").map((c, ci) => (
                            <span
                              key={ci}
                              className={
                                s.matchedIndex?.includes(ci)
                                  ? "text-terminal-amber"
                                  : "text-terminal-muted"
                              }
                            >
                              {c}
                            </span>
                          ))
                        : s.key}
                    </span>
                  </span>
                  <span className="truncate text-terminal-muted">
                    {s.kind === "symbol"
                      ? s.name + (s.exchange ? ` · ${s.exchange}` : "")
                      : s.description}
                  </span>
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
        <span className="shrink-0">{t("command.quick")}</span>
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
              {t("command.last")} <span className="text-terminal-amber">{lastCommand}</span>
              {history.length > 0 && (
                <span className="pl-2 text-terminal-muted/70">
                  · {t("command.history", { count: history.length })}
                </span>
              )}
            </>
          ) : (
            <>{t("command.clickHint")} <span className="text-terminal-amber">HELP</span></>
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
  { mnemonic: "MARS",    label: "MARS · factor analysis",  title: "Fama-French 5 + momentum on your portfolio" },
  { mnemonic: "TK",      label: "TK · fixed income",       title: "Treasury auctions + FINRA TRACE corp bonds" },
  { mnemonic: "CTM",     label: "CTM · futures",           title: "Front-month strip + term-structure curve" },
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
