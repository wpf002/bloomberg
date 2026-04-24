import { useEffect, useState } from "react";

export default function CommandBar({ onSubmit }) {
  const [value, setValue] = useState("");
  const [clock, setClock] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const submit = (e) => {
    e.preventDefault();
    const trimmed = value.trim().toUpperCase();
    if (!trimmed) return;
    onSubmit?.(trimmed);
    setValue("");
  };

  return (
    <header className="flex items-center gap-4 border-b border-terminal-border bg-terminal-panelAlt px-4 py-2">
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-terminal-amber shadow-[0_0_8px_#ff9f1c]" />
        <span className="text-sm font-bold tracking-widest text-terminal-amber">
          BLOOMBERG TERMINAL
        </span>
        <span className="text-[10px] uppercase tracking-wider text-terminal-muted">
          v0.1 · Phase 1
        </span>
      </div>
      <form onSubmit={submit} className="flex-1">
        <div className="flex items-center border border-terminal-border bg-terminal-bg px-2 py-1">
          <span className="pr-2 text-terminal-amber">›</span>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Enter ticker (e.g. AAPL) <GO>"
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
    </header>
  );
}
