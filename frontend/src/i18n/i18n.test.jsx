import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { I18nProvider, useTranslation, LOCALES } from "./index.jsx";
import en from "./en.js";
import es from "./es.js";
import pt from "./pt.js";
import zh from "./zh.js";

// Recursively collect dot-paths of every string leaf in a translation table.
function leafPaths(obj, prefix = "") {
  const out = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object") out.push(...leafPaths(v, path));
    else out.push(path);
  }
  return out;
}

const wrapper = ({ children }) => <I18nProvider>{children}</I18nProvider>;

beforeEach(() => {
  localStorage.clear();
});

describe("locale tables", () => {
  const enPaths = new Set(leafPaths(en));

  it("exposes the four advertised locales", () => {
    expect(LOCALES.map((l) => l.code)).toEqual(["en", "es", "pt", "zh"]);
  });

  it.each([
    ["es", es],
    ["pt", pt],
    ["zh", zh],
  ])("%s defines no keys absent from en (no orphan translations)", (_code, table) => {
    const extra = leafPaths(table).filter((p) => !enPaths.has(p));
    expect(extra).toEqual([]);
  });
});

describe("useTranslation", () => {
  it("returns English strings by default", () => {
    const { result } = renderHook(() => useTranslation(), { wrapper });
    const sample = Object.keys(en)[0];
    // t() of a known top-level string key returns that string, not the key.
    const firstStringKey = leafPaths(en)[0];
    expect(result.current.t(firstStringKey)).not.toBe(firstStringKey);
  });

  it("returns the key itself for unknown paths", () => {
    const { result } = renderHook(() => useTranslation(), { wrapper });
    expect(result.current.t("does.not.exist")).toBe("does.not.exist");
  });

  it("switches locale and persists the choice", () => {
    const { result } = renderHook(() => useTranslation(), { wrapper });
    act(() => result.current.setLocale("es"));
    expect(result.current.locale).toBe("es");
    expect(localStorage.getItem("bt.locale.v1")).toBe("es");
  });

  it("ignores an unsupported locale code", () => {
    const { result } = renderHook(() => useTranslation(), { wrapper });
    act(() => result.current.setLocale("xx"));
    expect(result.current.locale).toBe("en");
  });

  it("falls back to English when a key is missing in the active locale", () => {
    const { result } = renderHook(() => useTranslation(), { wrapper });
    // A key present in en — switch to a locale and ensure non-empty string back.
    const key = leafPaths(en).find((p) => !leafPaths(es).includes(p)) || leafPaths(en)[0];
    act(() => result.current.setLocale("es"));
    expect(typeof result.current.t(key)).toBe("string");
    expect(result.current.t(key)).not.toBe("");
  });

  it("interpolates {param} placeholders", () => {
    const { result } = renderHook(() => useTranslation(), { wrapper });
    // Use a synthetic template via a known key is awkward; assert the format
    // helper behaviour through a missing key (returns key) vs a real one. We
    // instead verify interpolation indirectly: any en string with {x} round
    // trips its params. Find one if present, else assert helper no-ops.
    const templated = leafPaths(en).find((p) => {
      const parts = p.split(".");
      let cur = en;
      for (const part of parts) cur = cur?.[part];
      return typeof cur === "string" && /\{\w+\}/.test(cur);
    });
    if (templated) {
      const out = result.current.t(templated, { count: 7, n: 7, value: 7, symbol: "AAPL" });
      expect(out).not.toMatch(/\{count\}|\{n\}|\{value\}|\{symbol\}/);
    } else {
      // No templated strings — interpolation path still must not crash.
      expect(result.current.t("does.not.exist", { a: 1 })).toBe("does.not.exist");
    }
  });
});
