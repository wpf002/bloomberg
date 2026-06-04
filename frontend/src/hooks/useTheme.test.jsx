import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import useTheme, { THEMES } from "./useTheme.js";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  // reset URL to a clean default
  window.history.replaceState({}, "", "/");
});

describe("useTheme", () => {
  it("defaults to dark and applies the theme class", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.classList.contains("theme-dark")).toBe(true);
  });

  it("setTheme swaps the class and persists", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("light"));
    expect(result.current.theme).toBe("light");
    expect(document.documentElement.classList.contains("theme-light")).toBe(true);
    expect(document.documentElement.classList.contains("theme-dark")).toBe(false);
    expect(localStorage.getItem("bt.theme.v1")).toBe("light");
  });

  it("ignores an unknown theme slug", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("neon"));
    expect(result.current.theme).toBe("dark");
  });

  it("cycle() advances through the palette and wraps", () => {
    const { result } = renderHook(() => useTheme());
    const order = THEMES.map((t) => t.slug);
    // start = dark (index 0); cycling len times returns to start
    for (let i = 0; i < order.length; i++) {
      act(() => result.current.cycle());
    }
    expect(result.current.theme).toBe(order[0]);
  });

  it("honours a ?theme= URL param on init", () => {
    window.history.replaceState({}, "", "/?theme=hc");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("hc");
  });

  it("prefers a stored theme over the default", () => {
    localStorage.setItem("bt.theme.v1", "light");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("light");
  });
});
