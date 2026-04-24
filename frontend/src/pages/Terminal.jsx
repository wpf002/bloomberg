import { useCallback, useState } from "react";
import Chart from "../components/Chart.jsx";
import CommandBar from "../components/CommandBar.jsx";
import CryptoPanel from "../components/CryptoPanel.jsx";
import MacroPanel from "../components/MacroPanel.jsx";
import NewsFeed from "../components/NewsFeed.jsx";
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

export default function Terminal() {
  const [watchlist, setWatchlist] = useState(DEFAULT_WATCHLIST);
  const [activeSymbol, setActiveSymbol] = useState(DEFAULT_WATCHLIST[0]);

  const onCommand = useCallback((symbol) => {
    setActiveSymbol(symbol);
    setWatchlist((prev) => (prev.includes(symbol) ? prev : [symbol, ...prev]));
  }, []);

  return (
    <div className="flex h-screen flex-col bg-terminal-bg text-terminal-text">
      <CommandBar onSubmit={onCommand} />
      <main className="grid flex-1 min-h-0 grid-cols-12 grid-rows-12 gap-2 p-2">
        <div className="col-span-3 row-span-8 min-h-0">
          <Watchlist
            symbols={watchlist}
            activeSymbol={activeSymbol}
            onSelect={setActiveSymbol}
          />
        </div>
        <div className="col-span-6 row-span-8 min-h-0">
          <Chart symbol={activeSymbol} />
        </div>
        <div className="col-span-3 row-span-8 min-h-0">
          <NewsFeed symbols={[activeSymbol]} />
        </div>
        <div className="col-span-4 row-span-4 min-h-0">
          <MacroPanel />
        </div>
        <div className="col-span-4 row-span-4 min-h-0">
          <Portfolio />
        </div>
        <div className="col-span-4 row-span-4 min-h-0">
          <CryptoPanel />
        </div>
      </main>
      <footer className="flex items-center justify-between border-t border-terminal-border bg-terminal-panelAlt px-4 py-1 text-[10px] uppercase tracking-widest text-terminal-muted">
        <span>
          Active: <span className="text-terminal-amber">{activeSymbol}</span>
        </span>
        <span>F1 Help · F2 Markets · F3 News · F4 Portfolio · F8 Macro</span>
        <span>Phase 1 · yfinance · alpaca · fred · edgar</span>
      </footer>
    </div>
  );
}
