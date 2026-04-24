import { useCallback, useMemo, useRef, useState } from "react";
import CalendarPanel from "../components/CalendarPanel.jsx";
import Chart from "../components/Chart.jsx";
import CommandBar, { MnemonicHelp } from "../components/CommandBar.jsx";
import ComparePanel from "../components/ComparePanel.jsx";
import CryptoPanel from "../components/CryptoPanel.jsx";
import ExplainPanel from "../components/ExplainPanel.jsx";
import FilingsPanel from "../components/FilingsPanel.jsx";
import FundamentalsPanel from "../components/FundamentalsPanel.jsx";
import Launchpad from "../components/Launchpad.jsx";
import MacroPanel from "../components/MacroPanel.jsx";
import MarketOverview from "../components/MarketOverview.jsx";
import NewsFeed from "../components/NewsFeed.jsx";
import OptionsPanel from "../components/OptionsPanel.jsx";
import Panel from "../components/Panel.jsx";
import Portfolio from "../components/Portfolio.jsx";
import SizingPanel from "../components/SizingPanel.jsx";
import Watchlist from "../components/Watchlist.jsx";

const DEFAULT_WATCHLIST = [
  "AAPL",
  "MSFT",
  "NVDA",
  "TSLA",
  "AMZN",
  "GOOGL",
  "META",
  "SPY",
  "QQQ",
  "TLT",
];

const INTENT_TO_PANEL = {
  focus: "chart",
  chart: "chart",
  describe: "fundamentals",
  news: "news",
  options: "options",
  filings: "filings",
  portfolio: "portfolio",
  sizing: "sizing",
  explain: "explain",
  compare: "compare",
  markets: "markets",
  macro: "macro",
  fx: "markets",
  crypto: "crypto",
  calendar: "calendar",
  help: "help",
  layout: "layout",
  reset: "reset",
  unknown: null,
};

// 12-col default layout. The grid layout library reads `x`, `y`, `w`, `h`, `i`.
// `minW/minH` prevent the user from shrinking panels into uselessness.
const DEFAULT_LAYOUTS = {
  lg: [
    { i: "watchlist",    x: 0,  y: 0,  w: 3, h: 8, minW: 2, minH: 4 },
    { i: "chart",        x: 3,  y: 0,  w: 6, h: 8, minW: 4, minH: 4 },
    { i: "news",         x: 9,  y: 0,  w: 3, h: 8, minW: 2, minH: 4 },
    { i: "markets",      x: 0,  y: 8,  w: 3, h: 4, minW: 2, minH: 3 },
    { i: "macro",        x: 3,  y: 8,  w: 3, h: 4, minW: 2, minH: 3 },
    { i: "portfolio",    x: 6,  y: 8,  w: 3, h: 4, minW: 2, minH: 3 },
    { i: "crypto",       x: 9,  y: 8,  w: 3, h: 4, minW: 2, minH: 3 },
    { i: "fundamentals", x: 0,  y: 12, w: 4, h: 8, minW: 3, minH: 4 },
    { i: "options",      x: 4,  y: 12, w: 5, h: 8, minW: 3, minH: 4 },
    { i: "filings",      x: 9,  y: 12, w: 3, h: 8, minW: 2, minH: 4 },
    { i: "calendar",     x: 0,  y: 20, w: 12, h: 4, minW: 4, minH: 3 },
    { i: "sizing",       x: 0,  y: 24, w: 5, h: 6, minW: 3, minH: 4 },
    { i: "explain",      x: 5,  y: 24, w: 4, h: 6, minW: 3, minH: 4 },
    { i: "compare",      x: 9,  y: 24, w: 3, h: 6, minW: 3, minH: 4 },
  ],
  md: [
    { i: "watchlist",    x: 0,  y: 0,  w: 4, h: 8 },
    { i: "chart",        x: 4,  y: 0,  w: 8, h: 8 },
    { i: "news",         x: 0,  y: 8,  w: 6, h: 6 },
    { i: "markets",      x: 6,  y: 8,  w: 6, h: 6 },
    { i: "macro",        x: 0,  y: 14, w: 6, h: 5 },
    { i: "portfolio",    x: 6,  y: 14, w: 6, h: 5 },
    { i: "crypto",       x: 0,  y: 19, w: 6, h: 5 },
    { i: "fundamentals", x: 6,  y: 19, w: 6, h: 8 },
    { i: "options",      x: 0,  y: 24, w: 12, h: 8 },
    { i: "filings",      x: 0,  y: 32, w: 6, h: 6 },
    { i: "calendar",     x: 6,  y: 32, w: 6, h: 6 },
    { i: "sizing",       x: 0,  y: 38, w: 6, h: 7 },
    { i: "explain",      x: 6,  y: 38, w: 6, h: 7 },
    { i: "compare",      x: 0,  y: 45, w: 12, h: 7 },
  ],
  sm: [
    { i: "watchlist",    x: 0, y: 0,  w: 6, h: 6 },
    { i: "chart",        x: 0, y: 6,  w: 6, h: 7 },
    { i: "news",         x: 0, y: 13, w: 6, h: 6 },
    { i: "markets",      x: 0, y: 19, w: 6, h: 5 },
    { i: "macro",        x: 0, y: 24, w: 6, h: 5 },
    { i: "portfolio",    x: 0, y: 29, w: 6, h: 5 },
    { i: "crypto",       x: 0, y: 34, w: 6, h: 5 },
    { i: "fundamentals", x: 0, y: 39, w: 6, h: 8 },
    { i: "options",      x: 0, y: 47, w: 6, h: 8 },
    { i: "filings",      x: 0, y: 55, w: 6, h: 6 },
    { i: "calendar",     x: 0, y: 61, w: 6, h: 4 },
    { i: "sizing",       x: 0, y: 65, w: 6, h: 7 },
    { i: "explain",      x: 0, y: 72, w: 6, h: 7 },
    { i: "compare",      x: 0, y: 79, w: 6, h: 7 },
  ],
};

export default function Terminal() {
  const [watchlist, setWatchlist] = useState(DEFAULT_WATCHLIST);
  const [activeSymbol, setActiveSymbol] = useState(DEFAULT_WATCHLIST[0]);
  const [compareSymbols, setCompareSymbols] = useState([DEFAULT_WATCHLIST[0], DEFAULT_WATCHLIST[1]]);
  const [editMode, setEditMode] = useState(false);
  const [resetKey, setResetKey] = useState(0);
  const [helpOpen, setHelpOpen] = useState(false);
  const [lastCommand, setLastCommand] = useState(null);
  const [flash, setFlash] = useState(null);
  const flashTimer = useRef(null);

  const triggerFlash = useCallback((panel) => {
    setFlash(panel);
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), 1500);
  }, []);

  const onCommand = useCallback(
    (parsed) => {
      const symbolsStr = (parsed.symbols?.length ? parsed.symbols.join(" ") : parsed.symbol ?? "");
      setLastCommand(`${symbolsStr} ${parsed.mnemonic}`.trim());
      if (parsed.symbol) {
        setActiveSymbol(parsed.symbol);
        setWatchlist((prev) =>
          prev.includes(parsed.symbol) ? prev : [parsed.symbol, ...prev]
        );
      }
      if (parsed.intent === "compare" && parsed.symbols?.length >= 2) {
        setCompareSymbols([parsed.symbols[0], parsed.symbols[1]]);
      }
      switch (parsed.intent) {
        case "help":
          setHelpOpen(true);
          return;
        case "layout":
          setEditMode((prev) => !prev);
          return;
        case "reset":
          setResetKey((k) => k + 1);
          return;
        default: {
          const panel = INTENT_TO_PANEL[parsed.intent];
          if (panel) triggerFlash(panel);
        }
      }
    },
    [triggerFlash]
  );

  const handleSelect = useCallback(
    (symbol) => {
      setActiveSymbol(symbol);
      triggerFlash("chart");
    },
    [triggerFlash]
  );

  const panels = useMemo(
    () => [
      { id: "watchlist",    render: () => <Watchlist symbols={watchlist} activeSymbol={activeSymbol} onSelect={handleSelect} /> },
      { id: "chart",        render: () => <Chart symbol={activeSymbol} /> },
      { id: "news",         render: () => <NewsFeed symbols={[activeSymbol]} /> },
      { id: "markets",      render: () => <MarketOverview onSelect={handleSelect} /> },
      { id: "macro",        render: () => <MacroPanel /> },
      { id: "portfolio",    render: () => <Portfolio /> },
      { id: "crypto",       render: () => <CryptoPanel /> },
      { id: "fundamentals", render: () => <FundamentalsPanel symbol={activeSymbol} /> },
      { id: "options",      render: () => <OptionsPanel symbol={activeSymbol} /> },
      { id: "filings",      render: () => <FilingsPanel symbol={activeSymbol} /> },
      { id: "calendar",     render: () => <CalendarPanel symbols={watchlist.slice(0, 8)} /> },
      { id: "sizing",       render: () => <SizingPanel symbol={activeSymbol} /> },
      { id: "explain",      render: () => <ExplainPanel symbol={activeSymbol} /> },
      { id: "compare",      render: () => <ComparePanel symbols={compareSymbols} /> },
    ],
    [watchlist, activeSymbol, compareSymbols, handleSelect]
  );

  return (
    <div className="flex h-screen flex-col bg-terminal-bg text-terminal-text">
      <CommandBar
        onCommand={onCommand}
        activeSymbol={activeSymbol}
        lastCommand={lastCommand}
      />
      <main className="flex-1 min-h-0 overflow-auto">
        <Launchpad
          panels={panels}
          defaultLayouts={DEFAULT_LAYOUTS}
          editMode={editMode}
          resetKey={resetKey}
          flash={flash}
        />
      </main>
      <footer className="flex items-center justify-between border-t border-terminal-border bg-terminal-panelAlt px-4 py-1 text-[10px] uppercase tracking-widest text-terminal-muted">
        <span>
          Active: <span className="text-terminal-amber">{activeSymbol}</span>
        </span>
        <span>
          <button
            onClick={() => setEditMode((p) => !p)}
            className={editMode ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
          >
            LAYOUT {editMode ? "ON" : "OFF"}
          </button>
          {" · "}
          <button
            onClick={() => setResetKey((k) => k + 1)}
            className="text-terminal-muted hover:text-terminal-text"
          >
            RESET
          </button>
          {" · "}
          <button onClick={() => setHelpOpen(true)} className="text-terminal-amber">
            HELP
          </button>
        </span>
        <span>Phase 4 · Sizing · Explain · Compare</span>
      </footer>
      {helpOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
          onClick={() => setHelpOpen(false)}
        >
          <div className="w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
            <Panel
              title="Mnemonic Reference"
              accent="amber"
              actions={
                <button
                  onClick={() => setHelpOpen(false)}
                  className="text-terminal-muted hover:text-terminal-text"
                >
                  ESC ✕
                </button>
              }
            >
              <MnemonicHelp />
              <p className="mt-3 text-[11px] text-terminal-muted">
                Enter <span className="text-terminal-amber">&lt;SYMBOL&gt; &lt;FN&gt;</span>{" "}
                in the command bar. Layout is draggable when{" "}
                <span className="text-terminal-amber">LAYOUT</span> is on and is
                persisted per-browser. <span className="text-terminal-amber">RESET</span>{" "}
                restores the factory layout.
              </p>
            </Panel>
          </div>
        </div>
      ) : null}
    </div>
  );
}
