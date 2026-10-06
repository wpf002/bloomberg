import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ScreenerPanel from "./ScreenerPanel.jsx";
import { renderWithI18n } from "../test/utils.jsx";

function jsonResp(body, status = 200) {
  return Promise.resolve({
    ok: status < 400, status, statusText: status < 400 ? "OK" : "Error",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

const FIELDS = [
  { key: "rsi14", label: "RSI 14", unit: "num", help: "" },
  { key: "dollar_volume", label: "Dollar volume", unit: "usd", help: "" },
  { key: "pe_ratio", label: "P/E", unit: "x", help: "" },
  { key: "market_cap", label: "Market cap", unit: "usd", help: "" },
];

const ROWS = [
  { symbol: "KHC", price: 21.84, market_cap: 2.6e10, pe_ratio: 11.2, change_pct: -1.2,
    rel_volume: 0.9, rsi14: 22.0, pct_off_52w_high: -22.2, price_vs_sma200: -8.1,
    ret_1m: -14.2, dollar_volume: 1.56e8 },
  { symbol: "NLY", price: 18.1, market_cap: 1.1e10, pe_ratio: null, change_pct: 0.4,
    rel_volume: 1.2, rsi14: 12.0, pct_off_52w_high: -9.0, price_vs_sma200: -3.0,
    ret_1m: -5.0, dollar_volume: 9.0e7 },
];

let fetchMock;
let screenBodies;

beforeEach(() => {
  screenBodies = [];
  fetchMock = vi.fn((url, opts) => {
    if (url.includes("/api/screener/fields")) return jsonResp(FIELDS);
    if (url.endsWith("/api/screener") && opts?.method === "POST") {
      screenBodies.push(JSON.parse(opts.body));
      return jsonResp({ rows: ROWS, count: ROWS.length, universe: 12460 });
    }
    return jsonResp({});
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("<ScreenerPanel>", () => {
  it("runs the default preset on mount and shows results", async () => {
    renderWithI18n(<ScreenerPanel />);
    expect(await screen.findByText("KHC")).toBeInTheDocument();
    expect(screen.getByText(/2 matches · 12460 symbols/i)).toBeInTheDocument();
    expect(screenBodies[0].filters.map((f) => f.field)).toEqual(["rsi14", "dollar_volume"]);
  });

  it("formats market cap and shows a dash for a missing P/E", async () => {
    renderWithI18n(<ScreenerPanel />);
    await screen.findByText("KHC");
    expect(screen.getByText("$26.00B")).toBeInTheDocument();
    const nlyRow = screen.getByText("NLY").closest("tr");
    expect(nlyRow.textContent).toContain("—");
  });

  it("loads a row into the terminal when clicked", async () => {
    const onSelect = vi.fn();
    renderWithI18n(<ScreenerPanel onSelectSymbol={onSelect} />);
    await userEvent.click(await screen.findByText("KHC"));
    expect(onSelect).toHaveBeenCalledWith("KHC");
  });

  it("switches to the Value preset", async () => {
    renderWithI18n(<ScreenerPanel />);
    await screen.findByText("KHC");
    await userEvent.click(screen.getByRole("button", { name: "Value" }));
    await waitFor(() => expect(screenBodies.length).toBe(2));
    const value = screenBodies[1];
    expect(value.filters.map((f) => f.field)).toEqual(["pe_ratio", "market_cap", "dollar_volume"]);
    expect(value.sort).toBe("pe_ratio");
    expect(value.desc).toBe(false);
  });

  it("shows the server's message when the universe isn't loaded yet", async () => {
    fetchMock.mockImplementation((url, opts) => {
      if (url.includes("/api/screener/fields")) return jsonResp(FIELDS);
      return jsonResp({ detail: "Screener universe is empty. Run POST /api/screener/refresh first." }, 503);
    });
    renderWithI18n(<ScreenerPanel />);
    expect(await screen.findByText(/universe is empty/i)).toBeInTheDocument();
  });
});
