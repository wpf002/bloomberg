import { useEffect, useMemo, useState } from "react";
import { MNEMONICS, parseCommand } from "../lib/mnemonics.js";

export default function CommandBar({ onCommand, activeSymbol, lastCommand }) {
  const [value, setValue] = useState("");
  const [clock, setClock] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const preview = useMemo(() => parseCommand(value), [value]);

  const submit = (e) => {
    e.preventDefault();
    const parsed = parseCommand(value);
    if (!parsed) return;
    onCommand?.(parsed);
    setValue("");
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
            v0.1 · Phase 1.1 · Public Edition
          </span>
        </div>
        <form onSubmit={submit} className="flex-1">
          <div className="flex items-center border border-terminal-border bg-terminal-bg px-2 py-1">
            <span className="pr-2 text-terminal-amber">›</span>
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={`Active: ${activeSymbol ?? "—"}   Enter: <SYMBOL> <FN>   (HELP for mnemonics)`}
              className="w-full bg-transparent text-sm uppercase tracking-wider text-terminal-text placeholder:text-terminal-muted/60 focus:outline-none"
              spellCheck={false}
              autoComplete="off"
            />
            <span className="text-[10px] uppercase tracking-widest text-terminal-muted">
              ENTER
            </span>
          </div>
        </form>
        <div className="tabular text-xs text-terminal-muted">
          {clock.toUTCString().split(" ").slice(0, 5).join(" ")} UTC
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-terminal-border/60 px-4 py-1 text-[10px] uppercase tracking-widest text-terminal-muted">
        <span className="truncate">{mnemonicHint}</span>
        {lastCommand ? (
          <span>
            Last: <span className="text-terminal-amber">{lastCommand}</span>
          </span>
        ) : (
          <span>
            Try: <span className="text-terminal-amber">AAPL DES</span> ·{" "}
            <span className="text-terminal-amber">SPY GP</span> ·{" "}
            <span className="text-terminal-amber">FXIP</span>
          </span>
        )}
      </div>
    </header>
  );
}

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
