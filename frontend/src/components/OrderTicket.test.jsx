import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OrderTicket from "./OrderTicket.jsx";
import { renderWithI18n } from "../test/utils.jsx";

function jsonResp(body, { ok = true, status = 200 } = {}) {
  return Promise.resolve({
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
  });
}

let fetchMock;

beforeEach(() => {
  // default: orders poll returns an empty list
  fetchMock = vi.fn((url) => {
    if (url.includes("/api/orders")) return jsonResp([]);
    return jsonResp({});
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("<OrderTicket>", () => {
  it("renders the ticket with BUY/SELL toggle and an empty recent-orders state", async () => {
    renderWithI18n(<OrderTicket symbol="AAPL" />);
    expect(screen.getByText("Buy")).toBeInTheDocument();
    expect(screen.getByText("Sell")).toBeInTheDocument();
    expect(screen.getByText("Recent orders")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });

  it("polls the orders endpoint on mount", async () => {
    renderWithI18n(<OrderTicket symbol="AAPL" />);
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => u.includes("/api/orders"))).toBe(true)
    );
  });

  it("submits a market order with the form's values", async () => {
    const user = userEvent.setup();
    renderWithI18n(<OrderTicket symbol="AAPL" />);
    // wait for initial poll so the form is interactive
    await screen.findByText("Recent orders");

    // set quantity to 3
    const qty = screen.getByRole("spinbutton");
    await user.clear(qty);
    await user.type(qty, "3");

    // submit (the button label includes the side/qty/sym)
    const submitBtn = screen.getByRole("button", { name: /AAPL/i });
    await user.click(submitBtn);

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([u, o]) => u === "/api/orders" && o?.method === "POST"
      );
      expect(postCall).toBeTruthy();
      const body = JSON.parse(postCall[1].body);
      expect(body).toMatchObject({
        symbol: "AAPL",
        qty: 3,
        side: "buy",
        type: "market",
        order_class: "simple",
      });
    });
  });

  it("reveals take-profit / stop-loss fields when a bracket order is chosen", async () => {
    const user = userEvent.setup();
    renderWithI18n(<OrderTicket symbol="AAPL" />);
    await screen.findByText("Recent orders");
    const classSelect = screen.getAllByRole("combobox").at(-1); // class is the last select
    await user.selectOptions(classSelect, "bracket");
    // bracket exposes take-profit / stop-loss inputs + a hint line
    await waitFor(() =>
      expect(screen.getAllByText(/take[- ]profit/i).length).toBeGreaterThan(0)
    );
  });

  it("shows the creds-missing notice when the orders endpoint returns 503", async () => {
    fetchMock.mockImplementation((url) => {
      if (url.includes("/api/orders")) return jsonResp({ detail: "no creds" }, { ok: false, status: 503 });
      return jsonResp({});
    });
    renderWithI18n(<OrderTicket symbol="AAPL" />);
    await waitFor(() => expect(screen.queryByText("Recent orders")).not.toBeInTheDocument());
  });
});
