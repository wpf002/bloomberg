import { useCallback, useEffect, useState } from "react";

// Available palette slugs — keep in sync with the `.theme-*` classes in
// src/index.css. The Tailwind config doesn't know about these by name;
// it just reads CSS variables, so adding a theme is two edits: add a
// `.theme-<slug>` block in index.css and add it to the array below.
export const THEMES = [
  { slug: "dark",  label: "Dark"           },
  { slug: "light", label: "Light"          },
  { slug: "hc",    label: "High contrast"  },
];

const STORAGE_KEY = "bt.theme.v1";
const URL_PARAM = "theme";

function applyTheme(slug) {
  const html = document.documentElement;
  THEMES.forEach((t) => html.classList.remove(`theme-${t.slug}`));
  html.classList.add(`theme-${slug}`);
  // Also update the meta theme-color so iOS/Android chrome picks up the swap.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    const colorByTheme = { dark: "#ff9f1c", light: "#c47100", hc: "#ffcc00" };
    meta.setAttribute("content", colorByTheme[slug] || "#ff9f1c");
  }
}

function readInitial() {
  // URL param wins (so `?theme=light` shareable links work), then
  // localStorage. Always falls back to dark — the terminal aesthetic is
  // dark-first; we don't honor OS prefers-color-scheme as a default.
  try {
    const url = new URL(window.location.href);
    const fromUrl = url.searchParams.get(URL_PARAM);
    if (fromUrl && THEMES.some((t) => t.slug === fromUrl)) return fromUrl;
  } catch {
    // ignore
  }
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && THEMES.some((t) => t.slug === stored)) return stored;
  } catch {
    // ignore
  }
  return "dark";
}

export default function useTheme() {
  const [theme, setThemeState] = useState(() => {
    const initial = readInitial();
    applyTheme(initial);
    return initial;
  });

  const setTheme = useCallback((slug) => {
    if (!THEMES.some((t) => t.slug === slug)) return;
    applyTheme(slug);
    setThemeState(slug);
    try {
      localStorage.setItem(STORAGE_KEY, slug);
    } catch {
      // ignore
    }
  }, []);

  // If the user lands with `?theme=` and then switches manually, drop the
  // param from the URL so a refresh doesn't override the new choice.
  useEffect(() => {
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.has(URL_PARAM) && url.searchParams.get(URL_PARAM) !== theme) {
        url.searchParams.delete(URL_PARAM);
        window.history.replaceState({}, "", url.toString());
      }
    } catch {
      // ignore
    }
  }, [theme]);

  const cycle = useCallback(() => {
    const idx = THEMES.findIndex((t) => t.slug === theme);
    const next = THEMES[(idx + 1) % THEMES.length];
    setTheme(next.slug);
  }, [theme, setTheme]);

  return { theme, setTheme, cycle, themes: THEMES };
}
