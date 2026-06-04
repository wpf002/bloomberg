import { describe, it, expect } from "vitest";
import { MNEMONICS, matchMnemonics, parseCommand } from "./mnemonics.js";

describe("parseCommand", () => {
  it("returns null for empty / whitespace input", () => {
    expect(parseCommand("")).toBeNull();
    expect(parseCommand(null)).toBeNull();
    expect(parseCommand("   ")).toBeNull();
  });

  it("treats a bare symbol as a focus (GO) intent", () => {
    const cmd = parseCommand("aapl");
    expect(cmd).toMatchObject({
      symbol: "AAPL",
      symbols: ["AAPL"],
      mnemonic: "GO",
      intent: "focus",
    });
  });

  it("uppercases input", () => {
    expect(parseCommand("msft gp").symbol).toBe("MSFT");
    expect(parseCommand("msft gp").mnemonic).toBe("GP");
  });

  it("resolves a bare mnemonic token with no symbol", () => {
    const cmd = parseCommand("HELP");
    expect(cmd).toMatchObject({ symbol: null, symbols: [], mnemonic: "HELP", intent: "help" });
  });

  it("maps a symbol + mnemonic to the mnemonic's intent", () => {
    expect(parseCommand("AAPL DES").intent).toBe("describe");
    expect(parseCommand("AAPL OMON").intent).toBe("options");
    expect(parseCommand("TSLA GP").intent).toBe("chart");
  });

  it("flags unknown mnemonics", () => {
    const cmd = parseCommand("AAPL ZZZ");
    expect(cmd.intent).toBe("unknown");
    expect(cmd.description).toContain("ZZZ");
  });

  it("handles the multi-symbol COMPARE form", () => {
    const cmd = parseCommand("AAPL MSFT COMPARE");
    expect(cmd).toMatchObject({
      symbol: "AAPL",
      symbols: ["AAPL", "MSFT"],
      mnemonic: "COMPARE",
      intent: "compare",
    });
  });

  it("supports more than two symbols before COMPARE", () => {
    const cmd = parseCommand("AAPL MSFT NVDA COMPARE");
    expect(cmd.symbols).toEqual(["AAPL", "MSFT", "NVDA"]);
  });

  it("collapses repeated whitespace between tokens", () => {
    const cmd = parseCommand("  aapl    des  ");
    expect(cmd).toMatchObject({ symbol: "AAPL", mnemonic: "DES" });
  });

  it("does not treat a 2-token COMPARE as multi-symbol", () => {
    // "AAPL COMPARE" → symbol AAPL, mnemonic COMPARE (not the >=3 branch)
    const cmd = parseCommand("AAPL COMPARE");
    expect(cmd.symbols).toEqual(["AAPL"]);
    expect(cmd.mnemonic).toBe("COMPARE");
  });
});

describe("matchMnemonics", () => {
  it("returns [] for empty query", () => {
    expect(matchMnemonics("")).toEqual([]);
    expect(matchMnemonics("   ")).toEqual([]);
  });

  it("ranks an exact match first", () => {
    const res = matchMnemonics("GEX");
    expect(res[0].key).toBe("GEX");
    expect(res[0].rank).toBe(0);
  });

  it("ranks prefix matches above substring matches", () => {
    const res = matchMnemonics("GE");
    // GEX is a prefix match (rank 1); any substring-only matches rank 2+.
    expect(res[0].key).toBe("GEX");
    expect(res[0].rank).toBe(1);
  });

  it("is case-insensitive", () => {
    expect(matchMnemonics("gex")[0].key).toBe("GEX");
  });

  it("honours the limit argument", () => {
    expect(matchMnemonics("S", 3).length).toBeLessThanOrEqual(3);
  });

  it("reports matched character indices for highlighting", () => {
    const res = matchMnemonics("PAY");
    const payoff = res.find((r) => r.key === "PAYOFF");
    expect(payoff.matchedIndex).toEqual([0, 1, 2]);
  });

  it("finds subsequence matches when no prefix/substring exists", () => {
    // "OON" is a subsequence of OMON (O_M_O_N) but not a substring.
    const res = matchMnemonics("OON");
    const hit = res.find((r) => r.key === "OMON");
    expect(hit).toBeTruthy();
    expect(hit.rank).toBeGreaterThanOrEqual(3);
  });

  it("returns nothing for a query that matches no key", () => {
    expect(matchMnemonics("QQZZXX")).toEqual([]);
  });

  it("carries intent + description through from the registry", () => {
    const hit = matchMnemonics("RISK")[0];
    expect(hit.intent).toBe(MNEMONICS.RISK.intent);
    expect(hit.description).toBe(MNEMONICS.RISK.description);
  });
});

describe("MNEMONICS registry", () => {
  it("every entry has an intent and description", () => {
    for (const [key, def] of Object.entries(MNEMONICS)) {
      expect(def.intent, `${key}.intent`).toBeTruthy();
      expect(def.description, `${key}.description`).toBeTruthy();
    }
  });
});
