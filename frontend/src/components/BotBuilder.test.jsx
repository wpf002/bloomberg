import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BotBuilder from "./BotBuilder.jsx";
import { renderWithI18n } from "../test/utils.jsx";

function jsonResp(body, { ok = true, status = 200 } = {}) {
  return Promise.resolve({
    ok, status, statusText: ok ? "OK" : "Error",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
  });
}

let fetchMock;
beforeEach(() => {
  fetchMock = vi.fn(() => jsonResp({}));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("<BotBuilder>", () => {
  it("renders the paper badge and a strategy selector", () => {
    renderWithI18n(<BotBuilder defaultSymbol="AAPL" />);
    expect(screen.getByText("Paper")).toBeInTheDocument();
    expect(screen.getByText("Threshold DCA")).toBeInTheDocument();
  });

  it("prefills the symbol from the active symbol", () => {
    renderWithI18n(<BotBuilder defaultSymbol="NVDA" />);
    expect(screen.getByDisplayValue("NVDA")).toBeInTheDocument();
  });

  it("gates Create behind a dry-run", async () => {
    const user = userEvent.setup();
    renderWithI18n(<BotBuilder defaultSymbol="AAPL" />);
    const createBtn = screen.getByRole("button", { name: /create bot/i });
    expect(createBtn).toBeDisabled();
  });

  it("runs a dry-run and posts the strategy config to /backtest", async () => {
    fetchMock.mockImplementation((url) => {
      if (url.includes("/api/bots/backtest")) {
        return jsonResp({ symbol: "AAPL", strategy: "threshold_dca", pnl: 120, pnl_pct: 1.2,
          max_drawdown_pct: 3.4, num_trades: 5, bars: 120, trades: [] });
      }
      return jsonResp({});
    });
    const user = userEvent.setup();
    renderWithI18n(<BotBuilder defaultSymbol="AAPL" />);
    await user.click(screen.getByRole("button", { name: /dry-run/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => u.includes("/api/bots/backtest"));
      expect(call).toBeTruthy();
      const body = JSON.parse(call[1].body);
      expect(body.config.strategy).toBe("threshold_dca");
      expect(body.config.symbols).toEqual(["AAPL"]);
      expect(body.guardrails.max_position_usd).toBe(1000);
    });
    // result renders and Create unlocks
    expect(await screen.findByText("+1.2%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create bot/i })).toBeEnabled();
  });

  it("creates the bot after a successful dry-run", async () => {
    fetchMock.mockImplementation((url) => {
      if (url.includes("/backtest")) return jsonResp({ pnl: 1, pnl_pct: 0.1, max_drawdown_pct: 0, num_trades: 1, bars: 50, trades: [] });
      if (url.endsWith("/api/bots")) return jsonResp({ id: "bot1", name: "x" });
      return jsonResp({});
    });
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<BotBuilder defaultSymbol="AAPL" onCreated={onCreated} />);
    await user.click(screen.getByRole("button", { name: /dry-run/i }));
    await screen.findByText(/0\.1%/);
    await user.click(screen.getByRole("button", { name: /create bot/i }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([u, o]) => u.endsWith("/api/bots") && o?.method === "POST");
      expect(post).toBeTruthy();
    });
    expect(onCreated).toHaveBeenCalled();
  });

  it("switches param fields when the strategy changes", async () => {
    const user = userEvent.setup();
    renderWithI18n(<BotBuilder defaultSymbol="AAPL" />);
    // threshold_dca shows a "Drop %" field
    expect(screen.getByText("Drop %")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox"), "rsi_reversion");
    // rsi shows the "Oversold <" param label (exact match — the blurb also
    // mentions "oversold")
    expect(screen.getByText("Oversold <")).toBeInTheDocument();
    expect(screen.queryByText("Drop %")).not.toBeInTheDocument();
  });
});
