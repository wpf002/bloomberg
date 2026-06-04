import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, wsURL } from "./api.js";

// VITE_API_URL is unset in the test env, so BASE === "" and requests are
// same-origin paths. We assert on the path + options passed to fetch.

function okJson(body) {
  return Promise.resolve({
    ok: true,
    status: 200,
    statusText: "OK",
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

function errResp(status, statusText, body) {
  return Promise.resolve({
    ok: false,
    status,
    statusText,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)),
  });
}

let fetchMock;

beforeEach(() => {
  fetchMock = vi.fn(() => okJson({ ok: true }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("wsURL", () => {
  it("derives ws:// from an http page origin when BASE is empty", () => {
    // jsdom default location is http://localhost:3000
    expect(wsURL("/api/ws/quotes")).toMatch(/^ws:\/\/localhost(:\d+)?\/api\/ws\/quotes$/);
  });
});

describe("api request construction", () => {
  it("sends credentials and JSON content-type by default", async () => {
    await api.quote("AAPL");
    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.credentials).toBe("include");
    expect(opts.headers["Content-Type"]).toBe("application/json");
  });

  it("URL-encodes path params", async () => {
    await api.quote("BRK.B");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/quotes/BRK.B");
    await api.filings("A&B");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/filings/A%26B");
  });

  it("joins comma-separated symbol lists for quotes()", async () => {
    await api.quotes(["AAPL", "MSFT"]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/quotes?symbols=AAPL%2CMSFT");
  });

  it("builds the news query with limit and optional symbols", async () => {
    await api.news(["AAPL"], 10);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/news?symbols=AAPL&limit=10");
    await api.news([], 5);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/news?limit=5");
  });

  it("POSTs a JSON body for placeOrder", async () => {
    await api.placeOrder({ symbol: "AAPL", qty: 1, side: "buy" });
    const [path, opts] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/orders");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ symbol: "AAPL", qty: 1, side: "buy" });
  });

  it("issues a DELETE for cancelOrder", async () => {
    await api.cancelOrder("order-123");
    const [path, opts] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/orders/order-123");
    expect(opts.method).toBe("DELETE");
  });

  it("defaults sizing stop_pct to 5", async () => {
    await api.sizing("AAPL");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/sizing/AAPL?stop_pct=5");
  });

  it("builds the flow/options query with defaults and optional filters", async () => {
    await api.flowOptions({ symbol: "AAPL", sector: "tech" });
    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain("/api/flow/options?");
    expect(url).toContain("side=all");
    expect(url).toContain("min_premium=100000");
    expect(url).toContain("symbol=AAPL");
    expect(url).toContain("sector=tech");
  });

  it("omits optional filings-search params when not provided", async () => {
    await api.filingsSearch("climate risk");
    const url = fetchMock.mock.calls[0][0];
    expect(url).toContain("q=climate+risk");
    expect(url).not.toContain("symbol=");
    expect(url).not.toContain("form_type=");
  });

  it("returns the resolved login URL without fetching", () => {
    expect(api.authLoginUrl()).toBe("/api/auth/github/login");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("api error handling", () => {
  it("throws an Error carrying status and parsed detail on non-2xx JSON", async () => {
    fetchMock.mockReturnValueOnce(errResp(422, "Unprocessable", { detail: "bad symbol" }));
    await expect(api.quote("???")).rejects.toMatchObject({
      status: 422,
      detail: "bad symbol",
    });
  });

  it("falls back to raw text when the error body is not JSON", async () => {
    fetchMock.mockReturnValueOnce(errResp(500, "Server Error", "boom"));
    await expect(api.quote("AAPL")).rejects.toMatchObject({
      status: 500,
      detail: "boom",
    });
  });

  it("resolves with parsed JSON on success", async () => {
    fetchMock.mockReturnValueOnce(okJson({ symbol: "AAPL", price: 100 }));
    await expect(api.quote("AAPL")).resolves.toEqual({ symbol: "AAPL", price: 100 });
  });
});
