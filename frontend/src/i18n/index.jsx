// Hand-rolled i18n — Phase 9.
//
// A full i18next + react-i18next stack would be ~30KB gzipped for our
// surface area (~120 strings, no plurals or interpolation we can't do
// in a one-line helper). Keeping this stdlib-only avoids the dep.
//
// Usage:
//   import { useTranslation } from "../i18n";
//   const { t, locale, setLocale, locales } = useTranslation();
//   ...
//   <h1>{t("watchlist.title")}</h1>
//
// Adding a string: drop it into ./en.js (the source of truth) and a
// matching key into ./es.js / ./pt.js / ./zh.js. Missing keys fall
// back to English so a half-translated locale still works.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import en from "./en.js";
import es from "./es.js";
import pt from "./pt.js";
import zh from "./zh.js";

export const LOCALES = [
  { code: "en", label: "English"     },
  { code: "es", label: "Español"     },
  { code: "pt", label: "Português"   },
  { code: "zh", label: "中文"         },
];

const TABLES = { en, es, pt, zh };
const STORAGE_KEY = "bt.locale.v1";

function readInitial() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && TABLES[stored]) return stored;
  } catch {
    // ignore
  }
  // Browser language → first two chars
  try {
    const nav = (navigator.language || "en").slice(0, 2).toLowerCase();
    if (TABLES[nav]) return nav;
  } catch {
    // ignore
  }
  return "en";
}

function lookup(table, key) {
  // Dot-path lookup: t("watchlist.title") → table.watchlist.title
  const parts = key.split(".");
  let cur = table;
  for (const p of parts) {
    if (cur == null) return undefined;
    cur = cur[p];
  }
  return typeof cur === "string" ? cur : undefined;
}

function format(template, params) {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, name) =>
    params[name] != null ? String(params[name]) : `{${name}}`
  );
}

const I18nContext = createContext({
  locale: "en",
  setLocale: () => {},
  t: (k) => k,
  locales: LOCALES,
});

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(() => readInitial());

  useEffect(() => {
    try {
      document.documentElement.setAttribute("lang", locale);
    } catch {
      // ignore
    }
  }, [locale]);

  const setLocale = useCallback((code) => {
    if (!TABLES[code]) return;
    setLocaleState(code);
    try {
      localStorage.setItem(STORAGE_KEY, code);
    } catch {
      // ignore
    }
  }, []);

  const t = useCallback(
    (key, params) => {
      const primary = lookup(TABLES[locale], key);
      const fallback = primary == null ? lookup(TABLES.en, key) : primary;
      return fallback != null ? format(fallback, params) : key;
    },
    [locale]
  );

  const value = useMemo(
    () => ({ locale, setLocale, t, locales: LOCALES }),
    [locale, setLocale, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useTranslation() {
  return useContext(I18nContext);
}
