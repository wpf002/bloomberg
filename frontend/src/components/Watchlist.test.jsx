import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Watchlist from "./Watchlist.jsx";
import { renderWithI18n, FakeWebSocket } from "../test/utils.jsx";

const QUOTES = [
  { symbol: "AAPL", price: 190.12, change: 1.5, change_percent: 0.8, previous_close: 188.62, volume: 1000000 },
  { symbol: "MSFT", price: 420.5, change: -2.0, change_percent: -0.47, previous_close: 422.5, volume: 500000 },
];

let fetchMock;

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  fetchMock = vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      statusText: "OK",
      json: () => Promise.resolve(QUOTES),
      text: () => Promise.resolve(JSON.stringify(QUOTES)),
    })
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("<Watchlist>", () => {
  it("renders the panel title and quote rows from the polled snapshot", async () => {
    renderWithI18n(<Watchlist symbols={["AAPL", "MSFT"]} activeSymbol="AAPL" />);
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
    // rows arrive after the async poll resolves
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("190.12")).toBeInTheDocument();
  });

  it("requests quotes for exactly the symbols it was given", async () => {
    renderWithI18n(<Watchlist symbols={["AAPL", "MSFT"]} />);
    // findBy lets the async poll's setState settle inside act()
    await screen.findByText("AAPL");
    const quoteCall = fetchMock.mock.calls.find(([u]) => u.includes("/api/quotes?"));
    expect(quoteCall[0]).toBe("/api/quotes?symbols=AAPL%2CMSFT");
  });

  it("opens a WebSocket stream for live ticks", async () => {
    renderWithI18n(<Watchlist symbols={["AAPL"]} />);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toContain("/api/ws/quotes");
    // let the polled snapshot land so its setState is act-wrapped
    await screen.findByText("AAPL");
  });

  it("fires onAdd with an uppercased symbol when the add form is submitted", async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<Watchlist symbols={["AAPL"]} onAdd={onAdd} />);
    await screen.findByText("AAPL"); // settle the poll before interacting
    const input = await screen.findByPlaceholderText(/add/i);
    await user.type(input, "nvda");
    await user.keyboard("{Enter}");
    expect(onAdd).toHaveBeenCalledWith("NVDA");
  });

  it("calls onSelect when a row is clicked", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<Watchlist symbols={["AAPL", "MSFT"]} onSelect={onSelect} />);
    const cell = await screen.findByText("MSFT");
    await user.click(cell);
    expect(onSelect).toHaveBeenCalledWith("MSFT");
  });

  it("surfaces an error message when the quote fetch fails", async () => {
    fetchMock.mockReturnValueOnce(
      Promise.resolve({
        ok: false,
        status: 500,
        statusText: "Server Error",
        json: () => Promise.resolve({}),
        text: () => Promise.resolve("boom"),
      })
    );
    renderWithI18n(<Watchlist symbols={["AAPL"]} />);
    expect(await screen.findByText(/500/)).toBeInTheDocument();
  });
});
