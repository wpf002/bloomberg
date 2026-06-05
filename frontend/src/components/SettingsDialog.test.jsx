import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SettingsDialog from "./SettingsDialog.jsx";
import { renderWithI18n } from "../test/utils.jsx";

function jsonResp(body) {
  return Promise.resolve({
    ok: true, status: 200, statusText: "OK",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

function routeFetch(brokers = []) {
  return vi.fn((url, opts) => {
    if (url.includes("/api/me/brokers") && (!opts || !opts.method || opts.method === "GET")) {
      return jsonResp({ brokers });
    }
    if (url.includes("/api/bots/status")) {
      return jsonResp({ paper: true, alpaca_configured: true, live_enabled: false, robinhood_enabled: false });
    }
    return jsonResp({ configured: true });
  });
}

let fetchMock;
beforeEach(() => {
  fetchMock = routeFetch();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("<SettingsDialog>", () => {
  it("renders nothing when closed", () => {
    const { container } = renderWithI18n(<SettingsDialog open={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("loads broker slots and shows the Alpaca paper slot", async () => {
    renderWithI18n(<SettingsDialog open onClose={() => {}} />);
    expect(await screen.findByText("Alpaca · Paper")).toBeInTheDocument();
    // not configured by default
    expect(screen.getAllByText("Not set").length).toBeGreaterThan(0);
  });

  it("shows masked 'configured' status without ever exposing the secret", async () => {
    fetchMock = routeFetch([{ broker: "alpaca", mode: "paper", configured: true, key_last4: "1234" }]);
    vi.stubGlobal("fetch", fetchMock);
    renderWithI18n(<SettingsDialog open onClose={() => {}} />);
    expect(await screen.findByText(/····1234/)).toBeInTheDocument();
  });

  it("PUTs keys to /api/me/brokers/alpaca/paper and never echoes them back", async () => {
    const user = userEvent.setup();
    renderWithI18n(<SettingsDialog open onClose={() => {}} />);
    await screen.findByText("Alpaca · Paper");
    const pwInputs = screen.getAllByPlaceholderText(/API key|API secret/i);
    // first slot is alpaca/paper: [key, secret]
    await user.type(pwInputs[0], "PKTESTKEY");
    await user.type(pwInputs[1], "TESTSECRET");
    const saveBtns = screen.getAllByRole("button", { name: /^save$/i });
    await user.click(saveBtns[0]);
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([u, o]) => u.includes("/api/me/brokers/alpaca/paper") && o?.method === "PUT"
      );
      expect(put).toBeTruthy();
      const body = JSON.parse(put[1].body);
      expect(body).toEqual({ key: "PKTESTKEY", secret: "TESTSECRET" });
    });
    // inputs are password type — secret not rendered as visible text
    expect(screen.queryByText("TESTSECRET")).not.toBeInTheDocument();
  });
});
