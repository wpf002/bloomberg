import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BotsPanel from "./BotsPanel.jsx";
import { renderWithI18n, FakeWebSocket } from "../test/utils.jsx";

function jsonResp(body, { ok = true, status = 200 } = {}) {
  return Promise.resolve({
    ok, status, statusText: ok ? "OK" : "Error",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
  });
}

const BOT = {
  id: "bot1", name: "Dip buyer", status: "active", mode: "paper",
  decision_mode: "rule", require_approval: true,
  config: { strategy: "threshold_dca", symbols: ["AAPL"], params: {} },
  guardrails: {},
};

function routeFetch(overrides = {}) {
  return vi.fn((url) => {
    if (url.includes("/api/bots/status")) return jsonResp({ paper: true, alpaca_configured: true, mode: "paper" });
    if (url.match(/\/api\/bots\/[^/]+\/events/)) return jsonResp([]);
    if (url.match(/\/api\/bots\/[^/]+\/pending/)) return jsonResp([]);
    if (url.match(/\/api\/bots\/[^/]+\/(start|pause|stop|kill)/)) return jsonResp({ ...BOT });
    if (url.endsWith("/api/bots")) return jsonResp(overrides.bots ?? [BOT]);
    return jsonResp({});
  });
}

let fetchMock;
beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  fetchMock = routeFetch();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("<BotsPanel>", () => {
  it("renders the title, paper badge, and bot list", async () => {
    renderWithI18n(<BotsPanel activeSymbol="AAPL" />);
    expect(screen.getByText("Trading Bots")).toBeInTheDocument();
    expect(screen.getAllByText("Paper").length).toBeGreaterThan(0);
    expect(await screen.findByText("Dip buyer")).toBeInTheDocument();
  });

  it("opens a /api/ws/bots stream", async () => {
    renderWithI18n(<BotsPanel activeSymbol="AAPL" />);
    await screen.findByText("Dip buyer");
    expect(FakeWebSocket.instances.some((w) => w.url.includes("/api/ws/bots"))).toBe(true);
  });

  it("shows a login prompt on 401", async () => {
    fetchMock.mockImplementation((url) => {
      if (url.includes("/api/bots/status")) return jsonResp({ paper: true, alpaca_configured: true });
      if (url.endsWith("/api/bots")) return jsonResp({ detail: "login required" }, { ok: false, status: 401 });
      return jsonResp([]);
    });
    renderWithI18n(<BotsPanel activeSymbol="AAPL" />);
    expect(await screen.findByText(/sign in/i)).toBeInTheDocument();
  });

  it("pauses an active bot via its control", async () => {
    const user = userEvent.setup();
    renderWithI18n(<BotsPanel activeSymbol="AAPL" />);
    await screen.findByText("Dip buyer");
    await user.click(screen.getByRole("button", { name: /^pause$/i }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u, o]) => u.includes("/bot1/pause") && o?.method === "POST")).toBe(true);
    });
  });

  it("gates Kill behind a confirm dialog", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderWithI18n(<BotsPanel activeSymbol="AAPL" />);
    await screen.findByText("Dip buyer");
    await user.click(screen.getByRole("button", { name: /^kill$/i }));
    expect(confirmSpy).toHaveBeenCalled();
    // confirm returned false → no kill request fired
    expect(fetchMock.mock.calls.some(([u]) => u.includes("/bot1/kill"))).toBe(false);

    confirmSpy.mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: /^kill$/i }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u, o]) => u.includes("/bot1/kill") && o?.method === "POST")).toBe(true);
    });
    confirmSpy.mockRestore();
  });
});
