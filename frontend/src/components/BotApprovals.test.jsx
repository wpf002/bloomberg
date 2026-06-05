import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BotApprovals from "./BotApprovals.jsx";
import { renderWithI18n } from "../test/utils.jsx";

function jsonResp(body) {
  return Promise.resolve({
    ok: true, status: 200, statusText: "OK",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

const PENDING = [
  { id: "p1", bot_id: "bot1", intent: { symbol: "AAPL", side: "buy", qty: 2, reason: "dip -2%" } },
];

let fetchMock;
beforeEach(() => {
  fetchMock = vi.fn(() => jsonResp({ approved: true }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("<BotApprovals>", () => {
  it("renders nothing when there are no pending actions", () => {
    const { container } = renderWithI18n(<BotApprovals pending={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a pending trade with its side, symbol, and size", () => {
    renderWithI18n(<BotApprovals pending={PENDING} />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("2 sh")).toBeInTheDocument();
  });

  it("approves via the approve endpoint and calls onResolved", async () => {
    const onResolved = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<BotApprovals pending={PENDING} onResolved={onResolved} />);
    await user.click(screen.getByRole("button", { name: /approve/i }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => u.includes("/bot1/pending/p1/approve"));
      expect(call).toBeTruthy();
      expect(call[1].method).toBe("POST");
    });
    expect(onResolved).toHaveBeenCalled();
  });

  it("rejects via the reject endpoint", async () => {
    const user = userEvent.setup();
    renderWithI18n(<BotApprovals pending={PENDING} onResolved={() => {}} />);
    await user.click(screen.getByRole("button", { name: /reject/i }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => u.includes("/bot1/pending/p1/reject"))).toBe(true);
    });
  });
});
