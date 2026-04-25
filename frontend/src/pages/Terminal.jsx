import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AlertsPanel from "../components/AlertsPanel.jsx";
import CalendarPanel from "../components/CalendarPanel.jsx";
import Chart from "../components/Chart.jsx";
import CommandBar, { MnemonicHelp } from "../components/CommandBar.jsx";
import ComparePanel from "../components/ComparePanel.jsx";
import CryptoPanel from "../components/CryptoPanel.jsx";
import ExplainPanel from "../components/ExplainPanel.jsx";
import FactorAnalyticsPanel from "../components/FactorAnalyticsPanel.jsx";
import FilingsPanel from "../components/FilingsPanel.jsx";
import FilingsSearchPanel from "../components/FilingsSearchPanel.jsx";
import FixedIncomePanel from "../components/FixedIncomePanel.jsx";
import FundamentalsPanel from "../components/FundamentalsPanel.jsx";
import FuturesPanel from "../components/FuturesPanel.jsx";
import Launchpad from "../components/Launchpad.jsx";
import MacroPanel from "../components/MacroPanel.jsx";
import MarketOverview from "../components/MarketOverview.jsx";
import NewsFeed from "../components/NewsFeed.jsx";
import OptionsPanel from "../components/OptionsPanel.jsx";
import OrderTicket from "../components/OrderTicket.jsx";
import Panel from "../components/Panel.jsx";
import PayoffPanel from "../components/PayoffPanel.jsx";
import Portfolio from "../components/Portfolio.jsx";
import ShareLayoutDialog from "../components/ShareLayoutDialog.jsx";
import SizingPanel from "../components/SizingPanel.jsx";
import SqlPanel from "../components/SqlPanel.jsx";
import Watchlist from "../components/Watchlist.jsx";
import useAuth from "../hooks/useAuth.js";
import useTheme from "../hooks/useTheme.js";
import { useTranslation } from "../i18n/index.jsx";
import { api } from "../lib/api.js";

// Panels considered "essential" on mobile/xs viewports. Others stay
// hidden behind a "+ MORE PANELS" toggle so a phone user isn't dropped
// into a 19-tile vertical wall on first open.
const MOBILE_PRIORITY_PANELS = new Set([
  "watchlist",
  "chart",
  "news",
  "markets",
  "portfolio",
]);

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
  trade: "trade",
  alerts: "alerts",
  payoff: "payoff",
  sql: "sql",
  search: "search",
  help: "help",
  layout: "layout",
  reset: "reset",
  share: "share",
  login: "login",
  logout: "logout",
  factors: "factors",
  fixed: "fixed",
  futures: "futures",
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
    { i: "portfolio",    x: 6,  y: 8,  w: 3, h: 4, minW: 2, minH: 2 },
    { i: "crypto",       x: 9,  y: 8,  w: 3, h: 4, minW: 2, minH: 3 },
    { i: "fundamentals", x: 0,  y: 12, w: 4, h: 8, minW: 3, minH: 4 },
    { i: "options",      x: 4,  y: 12, w: 5, h: 8, minW: 3, minH: 4 },
    { i: "filings",      x: 9,  y: 12, w: 3, h: 8, minW: 2, minH: 4 },
    { i: "calendar",     x: 0,  y: 20, w: 12, h: 4, minW: 4, minH: 3 },
    { i: "sizing",       x: 0,  y: 24, w: 5, h: 6, minW: 3, minH: 4 },
    { i: "explain",      x: 5,  y: 24, w: 4, h: 6, minW: 3, minH: 4 },
    { i: "compare",      x: 9,  y: 24, w: 3, h: 6, minW: 3, minH: 4 },
    { i: "trade",        x: 0,  y: 30, w: 4, h: 10, minW: 3, minH: 6 },
    { i: "alerts",       x: 4,  y: 30, w: 4, h: 10, minW: 3, minH: 6 },
    { i: "payoff",       x: 8,  y: 30, w: 4, h: 10, minW: 3, minH: 6 },
    { i: "sql",          x: 0,  y: 40, w: 8, h: 12, minW: 4, minH: 6 },
    { i: "search",       x: 8,  y: 40, w: 4, h: 12, minW: 3, minH: 6 },
    { i: "factors",      x: 0,  y: 52, w: 6, h: 7, minW: 4, minH: 5 },
    { i: "fixed",        x: 6,  y: 52, w: 6, h: 7, minW: 4, minH: 5 },
    { i: "futures",      x: 0,  y: 62, w: 12, h: 10, minW: 4, minH: 6 },
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
    { i: "trade",        x: 0,  y: 52, w: 6, h: 10 },
    { i: "alerts",       x: 6,  y: 52, w: 6, h: 10 },
    { i: "payoff",       x: 0,  y: 62, w: 12, h: 10 },
    { i: "sql",          x: 0,  y: 72, w: 12, h: 12 },
    { i: "search",       x: 0,  y: 84, w: 12, h: 10 },
    { i: "factors",      x: 0,  y: 94, w: 12, h: 7 },
    { i: "fixed",        x: 0,  y: 101, w: 12, h: 7 },
    { i: "futures",      x: 0,  y: 108, w: 12, h: 10 },
  ],
  sm: [
    { i: "watchlist",    x: 0, y: 0,   w: 6, h: 6 },
    { i: "chart",        x: 0, y: 6,   w: 6, h: 7 },
    { i: "news",         x: 0, y: 13,  w: 6, h: 6 },
    { i: "markets",      x: 0, y: 19,  w: 6, h: 5 },
    { i: "macro",        x: 0, y: 24,  w: 6, h: 5 },
    { i: "portfolio",    x: 0, y: 29,  w: 6, h: 4 },
    { i: "crypto",       x: 0, y: 34,  w: 6, h: 5 },
    { i: "fundamentals", x: 0, y: 39,  w: 6, h: 8 },
    { i: "options",      x: 0, y: 47,  w: 6, h: 8 },
    { i: "filings",      x: 0, y: 55,  w: 6, h: 6 },
    { i: "calendar",     x: 0, y: 61,  w: 6, h: 4 },
    { i: "sizing",       x: 0, y: 65,  w: 6, h: 7 },
    { i: "explain",      x: 0, y: 72,  w: 6, h: 7 },
    { i: "compare",      x: 0, y: 79,  w: 6, h: 7 },
    { i: "trade",        x: 0, y: 86,  w: 6, h: 10 },
    { i: "alerts",       x: 0, y: 96,  w: 6, h: 10 },
    { i: "payoff",       x: 0, y: 106, w: 6, h: 10 },
    { i: "sql",          x: 0, y: 116, w: 6, h: 12 },
    { i: "search",       x: 0, y: 128, w: 6, h: 10 },
    { i: "factors",      x: 0, y: 138, w: 6, h: 7 },
    { i: "fixed",        x: 0, y: 145, w: 6, h: 7 },
    { i: "futures",      x: 0, y: 152, w: 6, h: 10 },
  ],
};

export default function Terminal() {
  const { user, oauthConfigured, login, logout } = useAuth();
  const { theme, cycle: cycleTheme, themes } = useTheme();
  const { t, locale, setLocale, locales } = useTranslation();

  // Mobile breakpoint: collapse to a priority-only panel set on screens
  // narrower than ~720px. The user can flip it off via the "+ MORE PANELS"
  // button to see the full layout if they really want.
  const [mobilePriorityOnly, setMobilePriorityOnly] = useState(() => {
    try {
      return window.matchMedia("(max-width: 720px)").matches;
    } catch {
      return false;
    }
  });
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(max-width: 720px)");
    const handler = (e) => setMobilePriorityOnly(e.matches);
    mq.addEventListener?.("change", handler);
    return () => mq.removeEventListener?.("change", handler);
  }, []);
  const cycleLocale = useCallback(() => {
    const idx = locales.findIndex((l) => l.code === locale);
    setLocale(locales[(idx + 1) % locales.length].code);
  }, [locale, locales, setLocale]);

  const [watchlist, setWatchlist] = useState(DEFAULT_WATCHLIST);
  const [activeSymbol, setActiveSymbol] = useState(DEFAULT_WATCHLIST[0]);
  const [compareSymbols, setCompareSymbols] = useState([DEFAULT_WATCHLIST[0], ""]);

  // Keep Compare's "A" in sync with the active symbol so changing the
  // focused stock from anywhere (watchlist click, command bar, chip,
  // etc.) automatically retargets the comparison. The user no longer
  // has to type `<NEW> <B> COMPARE` just to switch sides — A follows
  // the rest of the panels, B stays whatever it was last set to.
  useEffect(() => {
    setCompareSymbols(([_prev, b]) =>
      activeSymbol && activeSymbol !== _prev ? [activeSymbol, b] : [_prev, b]
    );
  }, [activeSymbol]);
  const [editMode, setEditMode] = useState(false);
  const [resetKey, setResetKey] = useState(0);
  const [helpOpen, setHelpOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [lastCommand, setLastCommand] = useState(null);
  const [flash, setFlash] = useState(null);
  const flashTimer = useRef(null);

  // Layout state mirrored on the server when authenticated. Keeping it
  // here (vs only in Launchpad) lets us debounce PUT calls and avoids a
  // round-trip on every drag pixel.
  const [serverLayouts, setServerLayouts] = useState(null);
  const [serverHidden, setServerHidden] = useState(null);
  const layoutPutTimer = useRef(null);

  // Phase 7: when the URL contains ?layout=<slug>, fetch that public
  // shared layout and render it instead of the user's own. Read-only —
  // dragging is disabled and writes back to /api/me/layout are suppressed.
  const [sharedView, setSharedView] = useState(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const slug = params.get("layout");
    if (!slug) return;
    let active = true;
    api
      .fetchSharedLayout(slug)
      .then((data) => {
        if (active) setSharedView(data);
      })
      .catch(() => {
        if (active) setSharedView({ error: "shared layout not found", slug });
      });
    return () => {
      active = false;
    };
  }, []);

  const exitSharedView = () => {
    setSharedView(null);
    const url = new URL(window.location.href);
    url.searchParams.delete("layout");
    window.history.replaceState({}, "", url.toString());
  };

  const adoptSharedView = async () => {
    if (!user || !sharedView || sharedView.error) return;
    try {
      await api.putLayout(sharedView.layouts ?? {}, sharedView.hidden ?? []);
      setServerLayouts(sharedView.layouts ?? {});
      setServerHidden(sharedView.hidden ?? []);
      exitSharedView();
    } catch {
      // Surface failure but don't crash; user can retry.
    }
  };

  // Load per-user state from the backend on login. On logout, fall back to
  // the local default symbol set so the user isn't stuck on a now-private
  // watchlist.
  useEffect(() => {
    if (!user) {
      setServerLayouts(null);
      setServerHidden(null);
      setWatchlist(DEFAULT_WATCHLIST);
      setActiveSymbol(DEFAULT_WATCHLIST[0]);
      return;
    }
    let active = true;
    (async () => {
      try {
        const wl = await api.meWatchlist();
        if (!active) return;
        const symbols = wl?.symbols?.length ? wl.symbols : DEFAULT_WATCHLIST;
        setWatchlist(symbols);
        setActiveSymbol(symbols[0] ?? DEFAULT_WATCHLIST[0]);
        // First-time sign-in: seed the server with the default list.
        if (!wl?.symbols?.length) {
          api.putWatchlist(DEFAULT_WATCHLIST).catch(() => {});
        }
      } catch {
        // Server unreachable — keep defaults.
      }
      try {
        const layout = await api.meLayout();
        if (!active) return;
        setServerLayouts(layout?.layouts ?? {});
        setServerHidden(layout?.hidden ?? []);
      } catch {
        // ignore
      }
    })();
    return () => {
      active = false;
    };
  }, [user]);

  const persistWatchlist = useCallback(
    (next) => {
      if (!user) return;
      api.putWatchlist(next).catch(() => {});
    },
    [user]
  );

  const persistLayout = useCallback(
    (layouts, hidden) => {
      if (!user) return;
      if (layoutPutTimer.current) clearTimeout(layoutPutTimer.current);
      layoutPutTimer.current = setTimeout(() => {
        api.putLayout(layouts ?? {}, hidden ?? []).catch(() => {});
      }, 600);
    },
    [user]
  );

  const triggerFlash = useCallback((panel) => {
    // Force a re-render even when the same panel flashes twice in a row.
    setFlash(null);
    requestAnimationFrame(() => setFlash(panel));
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), 2300);
  }, []);

  const onCommand = useCallback(
    (parsed) => {
      const symbolsStr = (parsed.symbols?.length ? parsed.symbols.join(" ") : parsed.symbol ?? "");
      setLastCommand(`${symbolsStr} ${parsed.mnemonic}`.trim());
      if (parsed.symbol) {
        setActiveSymbol(parsed.symbol);
        setWatchlist((prev) => {
          if (prev.includes(parsed.symbol)) return prev;
          const next = [parsed.symbol, ...prev];
          persistWatchlist(next);
          return next;
        });
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
        case "share":
          if (user) setShareOpen(true);
          return;
        case "login":
          login();
          return;
        case "logout":
          logout();
          return;
        default: {
          const panel = INTENT_TO_PANEL[parsed.intent];
          if (panel) triggerFlash(panel);
        }
      }
    },
    [triggerFlash, persistWatchlist, login, logout, user, cycleTheme, cycleLocale]
  );

  const handleSelect = useCallback(
    (symbol) => {
      setActiveSymbol(symbol);
      triggerFlash("chart");
    },
    [triggerFlash]
  );

  const handleRemove = useCallback(
    (symbol) => {
      setWatchlist((prev) => {
        const next = prev.filter((s) => s !== symbol);
        if (next.length === prev.length) return prev;
        persistWatchlist(next);
        // If the removed row was the active symbol, fall back to the
        // first remaining ticker so panels keep rendering something.
        if (symbol === activeSymbol && next.length) setActiveSymbol(next[0]);
        return next;
      });
    },
    [activeSymbol, persistWatchlist]
  );

  const panels = useMemo(
    () => [
      { id: "watchlist",    render: () => <Watchlist symbols={watchlist} activeSymbol={activeSymbol} onSelect={handleSelect} onRemove={handleRemove} /> },
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
      { id: "trade",        render: () => <OrderTicket symbol={activeSymbol} /> },
      { id: "alerts",       render: () => <AlertsPanel symbol={activeSymbol} /> },
      { id: "payoff",       render: () => <PayoffPanel symbol={activeSymbol} /> },
      { id: "sql",          render: () => <SqlPanel /> },
      { id: "search",       render: () => <FilingsSearchPanel symbol={activeSymbol} /> },
      { id: "factors",      render: () => <FactorAnalyticsPanel /> },
      { id: "fixed",        render: () => <FixedIncomePanel /> },
      { id: "futures",      render: () => <FuturesPanel /> },
    ],
    [watchlist, activeSymbol, compareSymbols, handleSelect, handleRemove]
  );

  // On mobile, narrow to the priority set unless the user explicitly
  // toggled "+ MORE PANELS". Layout sharing still includes every panel
  // — this is a pure render-time filter so a mobile viewer of a
  // desktop layout doesn't get a 19-tile wall of charts.
  const renderedPanels = useMemo(
    () => (mobilePriorityOnly ? panels.filter((p) => MOBILE_PRIORITY_PANELS.has(p.id)) : panels),
    [panels, mobilePriorityOnly]
  );

  return (
    <div className="flex h-screen flex-col bg-terminal-bg text-terminal-text">
      <CommandBar
        onCommand={onCommand}
        activeSymbol={activeSymbol}
        lastCommand={lastCommand}
      />
      {sharedView ? (
        <div className="flex flex-wrap items-center gap-3 border-b border-terminal-amber/60 bg-terminal-amber/10 px-4 py-1.5 text-[11px] uppercase tracking-widest text-terminal-amber">
          {sharedView.error ? (
            <>
              <span>{t("shared.notFound", { slug: sharedView.slug })}</span>
              <button onClick={exitSharedView} className="hover:underline">
                {t("shared.dismiss")}
              </button>
            </>
          ) : (
            <>
              <span>
                {t("shared.viewing", { name: sharedView.name, owner: sharedView.owner_login })}
                {" · "}
                {t("shared.views", { count: sharedView.view_count })}
              </span>
              <span className="ml-auto flex items-center gap-3">
                {user ? (
                  <button onClick={adoptSharedView} className="hover:underline">
                    {t("shared.saveToAccount")}
                  </button>
                ) : (
                  <span className="text-terminal-muted">{t("shared.signInToSave")}</span>
                )}
                <button onClick={exitSharedView} className="hover:underline">
                  {t("shared.exit")}
                </button>
              </span>
            </>
          )}
        </div>
      ) : null}
      <main className="flex-1 min-h-0 overflow-auto">
        <Launchpad
          panels={renderedPanels}
          defaultLayouts={DEFAULT_LAYOUTS}
          editMode={editMode && !sharedView}
          resetKey={resetKey}
          flash={flash}
          controlledLayouts={
            sharedView && !sharedView.error
              ? sharedView.layouts ?? {}
              : user
                ? serverLayouts ?? {}
                : undefined
          }
          controlledHidden={
            sharedView && !sharedView.error
              ? sharedView.hidden ?? []
              : user
                ? serverHidden ?? []
                : undefined
          }
          onLayoutsChange={(next) => {
            if (sharedView) return; // read-only when viewing a shared layout
            setServerLayouts(next);
            persistLayout(next, serverHidden ?? []);
          }}
          onHiddenChange={(next) => {
            if (sharedView) return;
            setServerHidden(next);
            persistLayout(serverLayouts ?? {}, next);
          }}
          onShare={user && !sharedView ? () => setShareOpen(true) : undefined}
        />
      </main>
      <footer className="relative border-t border-terminal-border bg-terminal-panelAlt px-4 py-1 text-[10px] uppercase tracking-widest text-terminal-muted">
        <span className="absolute left-4 top-1/2 -translate-y-1/2 hidden md:inline">
          {t("footer.active")} <span className="text-terminal-amber">{activeSymbol}</span>
          {user ? (
            <span className="pl-3">
              · <span className="text-terminal-green">{user.login}</span>
            </span>
          ) : null}
        </span>
        <span className="mx-auto flex max-w-3xl items-center justify-between gap-2">
          <button
            onClick={() => setEditMode((p) => !p)}
            className={editMode ? "text-terminal-amber" : "text-terminal-muted hover:text-terminal-text"}
          >
            {editMode ? t("footer.layoutOn") : t("footer.layoutOff")}
          </button>
          <span>·</span>
          <button
            onClick={() => setResetKey((k) => k + 1)}
            className="text-terminal-muted hover:text-terminal-text"
          >
            {t("footer.reset")}
          </button>
          <span>·</span>
          <button onClick={() => setHelpOpen(true)} className="text-terminal-amber">
            {t("footer.help")}
          </button>
          <span>·</span>
          <button
            onClick={cycleTheme}
            className="text-terminal-muted hover:text-terminal-text"
            title={themes.map((tt) => tt.label).join(" / ")}
          >
            {t("theme.label")} {(themes.find((tt) => tt.slug === theme) || themes[0]).label}
          </button>
          <span>·</span>
          <button
            onClick={cycleLocale}
            className="text-terminal-muted hover:text-terminal-text"
            title={locales.map((l) => l.label).join(" / ")}
          >
            {t("language.label")} {(locales.find((l) => l.code === locale) || locales[0]).label}
          </button>
          <span>·</span>
          {user ? (
            <button onClick={logout} className="text-terminal-muted hover:text-terminal-text">
              {t("footer.logout")}
            </button>
          ) : oauthConfigured ? (
            <button onClick={login} className="text-terminal-amber hover:underline">
              {t("footer.login")}
            </button>
          ) : (
            <span title={t("footer.loginNaTitle")}>
              {t("footer.loginNa")}
            </span>
          )}
        </span>
        <span className="absolute right-4 top-1/2 -translate-y-1/2 hidden md:inline">{t("app.phase")}</span>
      </footer>
      <ShareLayoutDialog open={shareOpen} onClose={() => setShareOpen(false)} />
      {helpOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
          onClick={() => setHelpOpen(false)}
        >
          <div className="w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
            <Panel
              title={t("panels.help")}
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
                {t("command.helpFooter")}
              </p>
            </Panel>
          </div>
        </div>
      ) : null}
    </div>
  );
}
