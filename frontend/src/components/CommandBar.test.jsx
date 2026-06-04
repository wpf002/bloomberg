import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CommandBar from "./CommandBar.jsx";
import { renderWithI18n } from "../test/utils.jsx";

let fetchMock;

beforeEach(() => {
  localStorage.clear();
  // symbol-search autocomplete hits the API; return nothing so the dropdown
  // stays driven purely by mnemonic matches (deterministic).
  fetchMock = vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      statusText: "OK",
      json: () => Promise.resolve([]),
      text: () => Promise.resolve("[]"),
    })
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("<CommandBar>", () => {
  it("renders the app title and the quick-action chips", () => {
    renderWithI18n(<CommandBar onCommand={() => {}} />);
    expect(screen.getByText("BLOOMBERG TERMINAL")).toBeInTheDocument();
    expect(screen.getByText("Quick:")).toBeInTheDocument();
    // a couple of representative chips
    expect(screen.getByText("DES · describe")).toBeInTheDocument();
    expect(screen.getByText("HELP · all mnemonics")).toBeInTheDocument();
  });

  it("parses and dispatches a typed command on Enter", async () => {
    const onCommand = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<CommandBar onCommand={onCommand} />);
    const input = screen.getByRole("textbox");
    await user.type(input, "AAPL DES");
    await user.keyboard("{Enter}");
    expect(onCommand).toHaveBeenCalledTimes(1);
    expect(onCommand.mock.calls[0][0]).toMatchObject({
      symbol: "AAPL",
      mnemonic: "DES",
      intent: "describe",
    });
  });

  it("clears the input after a command is run and records history", async () => {
    const user = userEvent.setup();
    renderWithI18n(<CommandBar onCommand={() => {}} />);
    const input = screen.getByRole("textbox");
    await user.type(input, "TSLA GP{Enter}");
    expect(input).toHaveValue("");
    expect(JSON.parse(localStorage.getItem("bt:cmd-history"))).toContain("TSLA GP");
  });

  it("runs a quick-action chip against the active symbol", async () => {
    const onCommand = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(<CommandBar onCommand={onCommand} activeSymbol="NVDA" />);
    await user.click(screen.getByText("GP · chart"));
    expect(onCommand.mock.calls[0][0]).toMatchObject({ symbol: "NVDA", mnemonic: "GP" });
  });

  it("switches mode when the mode toggle is clicked", async () => {
    const onModeChange = vi.fn();
    const user = userEvent.setup();
    renderWithI18n(
      <CommandBar onCommand={() => {}} mode="terminal" onModeChange={onModeChange} />
    );
    await user.click(screen.getByText("Intelligence"));
    expect(onModeChange).toHaveBeenCalledWith("intelligence");
  });

  it("shows a mnemonic-suggestion dropdown while typing a partial mnemonic", async () => {
    const user = userEvent.setup();
    renderWithI18n(<CommandBar onCommand={() => {}} />);
    const input = screen.getByRole("textbox");
    await user.type(input, "AAPL PAY");
    // PAYOFF should appear as a suggestion. The key glyphs are split into
    // per-char spans, so assert on the description instead.
    expect(await screen.findByText("Options payoff diagram")).toBeInTheDocument();
  });
});
