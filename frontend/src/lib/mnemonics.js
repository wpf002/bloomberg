// Bloomberg-style function mnemonics. The command bar parses lines of the form
// "<SYMBOL> <MNEMONIC>" (e.g. "AAPL DES", "EURUSD FXIP") and the Terminal page
// dispatches on the returned intent.

export const MNEMONICS = {
  GO:      { intent: "focus",     description: "Load symbol as active" },
  DES:     { intent: "describe",  description: "Company description / fundamentals" },
  FA:      { intent: "describe",  description: "Financial analysis / fundamentals" },
  GP:      { intent: "chart",     description: "Price chart" },
  GIP:     { intent: "chart",     description: "Intraday price chart" },
  HP:      { intent: "chart",     description: "Historical price chart" },
  N:       { intent: "news",      description: "News stream" },
  TOP:     { intent: "news",      description: "Top news headlines" },
  OMON:    { intent: "options",   description: "Options monitor (chain + Greeks)" },
  OV:      { intent: "options",   description: "Options overview" },
  FIL:     { intent: "filings",   description: "SEC filings (EDGAR)" },
  CF:      { intent: "filings",   description: "Company filings" },
  PORT:    { intent: "portfolio", description: "Portfolio P/L" },
  SIZE:    { intent: "sizing",    description: "Position-size calculator" },
  SIZING:  { intent: "sizing",    description: "Position-size calculator" },
  EXPLAIN: { intent: "explain",   description: "LLM briefing (news + filings + fundamentals)" },
  COMPARE: { intent: "compare",   description: "Side-by-side LLM comparison (multi-symbol)" },
  BUY:     { intent: "trade",     description: "Open EMS / order ticket (paper)" },
  SELL:    { intent: "trade",     description: "Open EMS / order ticket (paper)" },
  TRADE:   { intent: "trade",     description: "Order ticket (Alpaca paper)" },
  EMSX:    { intent: "trade",     description: "EMS — paper order entry" },
  ALRT:    { intent: "alerts",    description: "Rule-based alerts" },
  ALERT:   { intent: "alerts",    description: "Rule-based alerts" },
  OVME:    { intent: "payoff",    description: "Options payoff diagram" },
  PAYOFF:  { intent: "payoff",    description: "Options payoff diagram" },
  WEI:     { intent: "markets",   description: "World equity indices" },
  MMAP:    { intent: "markets",   description: "Markets map / overview" },
  ECO:     { intent: "macro",     description: "Economic data (FRED)" },
  FXIP:    { intent: "fx",        description: "FX dashboard" },
  XBTC:    { intent: "crypto",    description: "Crypto overview" },
  CAL:     { intent: "calendar",  description: "Earnings & event calendar" },
  EVTS:    { intent: "calendar",  description: "Events / earnings calendar" },
  LAYOUT:  { intent: "layout",    description: "Toggle launchpad edit mode" },
  RESET:   { intent: "reset",     description: "Reset launchpad layout" },
  SHARE:   { intent: "share",     description: "Publish current Launchpad as a public URL" },
  SQL:     { intent: "sql",       description: "DuckDB SQL workbench (bars / macro / filings)" },
  BQNT:    { intent: "sql",       description: "DuckDB SQL workbench (BQuant analogue)" },
  SRCH:    { intent: "search",    description: "Full-text filings search (Meilisearch)" },
  SEARCH:  { intent: "search",    description: "Full-text filings search (Meilisearch)" },
  LOGIN:   { intent: "login",     description: "Sign in with GitHub" },
  LOGOUT:  { intent: "logout",    description: "Sign out" },
  MARS:    { intent: "factors",   description: "Portfolio factor analysis (Fama-French 5 + momentum)" },
  FACTORS: { intent: "factors",   description: "Portfolio factor analysis" },
  TK:      { intent: "fixed",     description: "Fixed income — Treasuries + corporate bonds" },
  TRACE:   { intent: "fixed",     description: "FINRA TRACE corporate bond prints" },
  BAUC:    { intent: "fixed",     description: "Treasury auction calendar" },
  CRV:     { intent: "futures",   description: "Futures dashboard + term-structure curve" },
  CTM:     { intent: "futures",   description: "Commodities / futures monitor" },
  PROV:        { intent: "provenance",   description: "AURORA — data provenance / audit log" },
  PROVENANCE:  { intent: "provenance",   description: "AURORA — data provenance / audit log" },
  RISK:        { intent: "risk",         description: "AURORA — risk engine (VaR / CVaR / stress / correlation)" },
  INTEL:       { intent: "intelligence", description: "AURORA — intelligence engine (regime / fragility / flows / rotation)" },
  REGIME:      { intent: "intelligence", description: "AURORA — current macro regime + contributing factors" },
  ADVISOR:     { intent: "advisor",      description: "AURORA — Claude AI portfolio advisor" },
  ASK:         { intent: "advisor",      description: "AURORA — ask the AI advisor a question" },
  FLOW:        { intent: "flow",         description: "Options flow + dark pool prints (V2.3)" },
  GEX:         { intent: "gex",          description: "Gamma / vanna exposure profile (V2.4)" },
  VEX:         { intent: "gex",          description: "Vanna exposure profile (V2.4)" },
  PRED:        { intent: "predictions",  description: "Prediction-market consensus (V2.5)" },
  DT:          { intent: "daytrader",    description: "AI Day Trader mode (V2.7)" },
  HELP:    { intent: "help",      description: "Show mnemonics" },
};

// Mnemonics that can take more than one symbol before the mnemonic token,
// e.g. "AAPL MSFT COMPARE". The parser passes the full list via `symbols`.
const MULTI_SYMBOL_MNEMONICS = new Set(["COMPARE"]);

// Aliases: pressing <Enter> with just a symbol should act like <SYM> GO.
const SYMBOL_ONLY_INTENT = "focus";

// Fuzzy match a partial mnemonic against the known set. Returns up to `limit`
// ranked candidates. Ranking: exact > prefix > substring > subsequence.
// Each candidate: { key, intent, description, rank, matchedIndex[] } where
// matchedIndex is the list of char positions in `key` that matched `partial`
// (used to bold the matched chars in the UI).
export function matchMnemonics(partial, limit = 6) {
  const q = (partial || "").trim().toUpperCase();
  if (!q) return [];
  const out = [];
  for (const [key, def] of Object.entries(MNEMONICS)) {
    let rank = -1;
    let idx = [];
    if (key === q) {
      rank = 0;
      idx = [...q].map((_, i) => i);
    } else if (key.startsWith(q)) {
      rank = 1;
      idx = [...q].map((_, i) => i);
    } else if (key.includes(q)) {
      rank = 2;
      const start = key.indexOf(q);
      idx = [...q].map((_, i) => start + i);
    } else {
      // subsequence match: all chars of q appear in key in order
      let ki = 0;
      const pos = [];
      for (const ch of q) {
        const found = key.indexOf(ch, ki);
        if (found === -1) {
          pos.length = 0;
          break;
        }
        pos.push(found);
        ki = found + 1;
      }
      if (pos.length === q.length) {
        rank = 3 + (pos[pos.length - 1] - pos[0]); // tighter spans rank better
        idx = pos;
      }
    }
    if (rank >= 0) {
      out.push({ key, intent: def.intent, description: def.description, rank, matchedIndex: idx });
    }
  }
  out.sort((a, b) => a.rank - b.rank || a.key.length - b.key.length || a.key.localeCompare(b.key));
  return out.slice(0, limit);
}

export function parseCommand(input) {
  if (!input) return null;
  const trimmed = input.trim().toUpperCase();
  if (!trimmed) return null;
  const parts = trimmed.split(/\s+/);
  if (parts.length === 1) {
    const token = parts[0];
    if (MNEMONICS[token]) {
      return { symbol: null, symbols: [], mnemonic: token, ...MNEMONICS[token] };
    }
    return {
      symbol: token,
      symbols: [token],
      mnemonic: "GO",
      intent: SYMBOL_ONLY_INTENT,
      description: MNEMONICS.GO.description,
    };
  }
  // Multi-symbol form: "AAPL MSFT COMPARE" → symbols = [AAPL, MSFT], mnemonic = COMPARE.
  const last = parts[parts.length - 1];
  if (parts.length >= 3 && MULTI_SYMBOL_MNEMONICS.has(last)) {
    const known = MNEMONICS[last];
    const symbols = parts.slice(0, -1);
    return {
      symbol: symbols[0],
      symbols,
      mnemonic: last,
      intent: known.intent,
      description: known.description,
    };
  }
  const [symbol, mnemonic] = parts;
  const known = MNEMONICS[mnemonic];
  if (!known) {
    return { symbol, symbols: [symbol], mnemonic, intent: "unknown", description: `Unknown mnemonic: ${mnemonic}` };
  }
  return { symbol, symbols: [symbol], mnemonic, intent: known.intent, description: known.description };
}
