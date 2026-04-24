/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: "#0b0b0b",
          panel: "#111418",
          panelAlt: "#161a20",
          border: "#1f242c",
          text: "#e6e6e6",
          muted: "#8a8f98",
          amber: "#ff9f1c",
          amberDim: "#b26f14",
          green: "#00d26a",
          red: "#ff4d4d",
          blue: "#4cc9f0",
        },
      },
      fontFamily: {
        mono: ["'JetBrains Mono'", "'Fira Code'", "Menlo", "monospace"],
      },
      boxShadow: {
        panel: "0 0 0 1px #1f242c, 0 2px 12px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};
