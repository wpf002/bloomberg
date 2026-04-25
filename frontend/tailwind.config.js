/** @type {import('tailwindcss').Config} */
//
// Phase 9 — colours are now CSS custom properties so themes (dark, light,
// high-contrast) can swap palettes by toggling a class on <html> without
// re-rendering anything. Each variable holds a hex value; we wrap it with
// `var(--bt-*)` so Tailwind's existing `text-terminal-amber`, `bg-terminal-bg`
// etc. keep working unchanged across the codebase.
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg:        "var(--bt-bg)",
          panel:     "var(--bt-panel)",
          panelAlt:  "var(--bt-panel-alt)",
          border:    "var(--bt-border)",
          text:      "var(--bt-text)",
          muted:     "var(--bt-muted)",
          amber:     "var(--bt-amber)",
          amberDim:  "var(--bt-amber-dim)",
          green:     "var(--bt-green)",
          red:       "var(--bt-red)",
          blue:      "var(--bt-blue)",
        },
      },
      fontFamily: {
        mono: ["'JetBrains Mono'", "'Fira Code'", "Menlo", "monospace"],
      },
      boxShadow: {
        panel: "0 0 0 1px var(--bt-border), 0 2px 12px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};
