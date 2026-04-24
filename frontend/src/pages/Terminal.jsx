import { useCallback, useRef, useState } from "react";
import Chart from "../components/Chart.jsx";
import CommandBar, { MnemonicHelp } from "../components/CommandBar.jsx";
import CryptoPanel from "../components/CryptoPanel.jsx";
import MacroPanel from "../components/MacroPanel.jsx";
import MarketOverview from "../components/MarketOverview.jsx";
import NewsFeed from "../components/NewsFeed.jsx";
import Panel from "../components/Panel.jsx";
import Portfolio from "../components/Portfolio.jsx";
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
  focus: "watchlist",
  chart: "chart",
  news: "news",
  options: "options",
  filings: "filings",
  portfolio: "portfolio",
  markets: "markets",
  macro: "macro",
  fx: "fx",
  crypto: "crypto",
  describe: "chart",
  help: "help",
  unknown: null,
};

export default function Terminal() {
  const [watchlist, setWatchlist] = useState(DEFAULT_WATCHLIST);
  const [activeSymbol, setActiveSymbol] = useState(DEFAULT_WATCHLIST[0]);
  const [focusPanel, setFocusPanel] = useState(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [lastCommand, setLastCommand] = useState(null);
  const focusTimer = useRef(null);

  const flashPanel = useCallback((panel) => {
    setFocusPanel(panel);
    if (focusTimer.current) clearTimeout(focusTimer.current);
    focusTimer.current = setTimeout(() => setFocusPanel(null), 1500);
  }, []);

  const onCommand = useCallback(
    (parsed) => {
      setLastCommand(`${parsed.symbol ?? ""} ${parsed.mnemonic}`.trim());
      if (parsed.symbol) {
        setActiveSymbol(parsed.symbol);
        setWatchlist((prev) =>
          prev.includes(parsed.symbol) ? prev : [parsed.symbol, ...prev]
        );
      }
      const panel = INTENT_TO_PANEL[parsed.intent];
      if (parsed.intent === "help") {
        setHelpOpen(true);
        return;
      }
      if (panel) flashPanel(panel);
    },
    [flashPanel]
  );

  const handleSelect = useCallback(
    (symbol) => {
      setActiveSymbol(symbol);
      flashPanel("chart");
    },
    [flashPanel]
  );

  const highlight = (panel) =>
    focusPanel === panel
      ? "ring-1 ring-terminal-amber/70 shadow-[0_0_0_1px_#ff9f1c]"
      : "";

  return (
    <div className="flex h-screen flex-col bg-terminal-bg text-terminal-text">
      <CommandBar
        onCommand={onCommand}
        activeSymbol={activeSymbol}
        lastCommand={lastCommand}
      />
      <main className="grid flex-1 min-h-0 grid-cols-12 grid-rows-12 gap-2 p-2">
        <div className={`col-span-3 row-span-8 min-h-0 ${highlight("watchlist")}`}>
          <Watchlist
            symbols={watchlist}
            activeSymbol={activeSymbol}
            onSelect={handleSelect}
          />
        </div>
        <div className={`col-span-6 row-span-8 min-h-0 ${highlight("chart")}`}>
          <Chart symbol={activeSymbol} />
        </div>
        <div className={`col-span-3 row-span-8 min-h-0 ${highlight("news")}`}>
          <NewsFeed symbols={[activeSymbol]} />
        </div>
        <div className={`col-span-3 row-span-4 min-h-0 ${highlight("markets")}`}>
          <MarketOverview onSelect={handleSelect} />
        </div>
        <div className={`col-span-3 row-span-4 min-h-0 ${highlight("macro")}`}>
          <MacroPanel />
        </div>
        <div className={`col-span-3 row-span-4 min-h-0 ${highlight("portfolio")}`}>
          <Portfolio />
        </div>
        <div className={`col-span-3 row-span-4 min-h-0 ${highlight("crypto")}`}>
          <CryptoPanel />
        </div>
      </main>
      <footer className="flex items-center justify-between border-t border-terminal-border bg-terminal-panelAlt px-4 py-1 text-[10px] uppercase tracking-widest text-terminal-muted">
        <span>
          Active: <span className="text-terminal-amber">{activeSymbol}</span>
        </span>
        <span>
          HELP mnemonics · <button onClick={() => setHelpOpen(true)} className="text-terminal-amber">?</button>
        </span>
        <span>Phase 1.1 · yfinance · alpaca · fred · edgar · public edition</span>
      </footer>
      {helpOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
          onClick={() => setHelpOpen(false)}
        >
          <div
            className="w-full max-w-2xl"
            onClick={(e) => e.stopPropagation()}
          >
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
                in the command bar. Example: <span className="text-terminal-amber">AAPL DES</span>,{" "}
                <span className="text-terminal-amber">SPY GP</span>,{" "}
                <span className="text-terminal-amber">EURUSD FXIP</span>,{" "}
                <span className="text-terminal-amber">NVDA OMON</span>.
              </p>
            </Panel>
          </div>
        </div>
      ) : null}
    </div>
  );
}
