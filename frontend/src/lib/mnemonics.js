// Bloomberg-style function mnemonics. The command bar parses lines of the form
// "<SYMBOL> <MNEMONIC>" (e.g. "AAPL DES", "EURUSD FXIP") and the Terminal page
// dispatches on the returned intent.

export const MNEMONICS = {
  GO:     { intent: "focus",    description: "Load symbol as active" },
  DES:    { intent: "describe", description: "Company description / fundamentals" },
  FA:     { intent: "describe", description: "Financial analysis / fundamentals" },
  GP:     { intent: "chart",    description: "Price chart" },
  GIP:    { intent: "chart",    description: "Intraday price chart" },
  HP:     { intent: "chart",    description: "Historical price chart" },
  N:      { intent: "news",     description: "News stream" },
  TOP:    { intent: "news",     description: "Top news headlines" },
  OMON:   { intent: "options",  description: "Options monitor (chain + Greeks)" },
  OV:     { intent: "options",  description: "Options overview" },
  FIL:    { intent: "filings",  description: "SEC filings (EDGAR)" },
  CF:     { intent: "filings",  description: "Company filings" },
  PORT:   { intent: "portfolio", description: "Portfolio P/L" },
  WEI:    { intent: "markets",  description: "World equity indices" },
  MMAP:   { intent: "markets",  description: "Markets map / overview" },
  ECO:    { intent: "macro",    description: "Economic data (FRED)" },
  FXIP:   { intent: "fx",       description: "FX dashboard" },
  XBTC:   { intent: "crypto",   description: "Crypto overview" },
  CAL:    { intent: "calendar", description: "Earnings & event calendar" },
  EVTS:   { intent: "calendar", description: "Events / earnings calendar" },
  LAYOUT: { intent: "layout",   description: "Toggle launchpad edit mode" },
  RESET:  { intent: "reset",    description: "Reset launchpad layout" },
  HELP:   { intent: "help",     description: "Show mnemonics" },
};

// Aliases: pressing <Enter> with just a symbol should act like <SYM> GO.
const SYMBOL_ONLY_INTENT = "focus";

export function parseCommand(input) {
  if (!input) return null;
  const trimmed = input.trim().toUpperCase();
  if (!trimmed) return null;
  const parts = trimmed.split(/\s+/);
  if (parts.length === 1) {
    const token = parts[0];
    if (MNEMONICS[token]) {
      return { symbol: null, mnemonic: token, ...MNEMONICS[token] };
    }
    return {
      symbol: token,
      mnemonic: "GO",
      intent: SYMBOL_ONLY_INTENT,
      description: MNEMONICS.GO.description,
    };
  }
  const [symbol, mnemonic] = parts;
  const known = MNEMONICS[mnemonic];
  if (!known) {
    return { symbol, mnemonic, intent: "unknown", description: `Unknown mnemonic: ${mnemonic}` };
  }
  return { symbol, mnemonic, intent: known.intent, description: known.description };
}
