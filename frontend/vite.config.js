import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite reads `process.env` synchronously when this file is loaded, which
// is fine because both `vite` and `vite preview` run under Node before
// any browser ever sees this file.
const PREVIEW_PORT = Number(process.env.PORT) || 4173;
const DEV_PROXY_TARGET = process.env.VITE_API_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // Disable HTTP caching outright in dev. Safari's default behaviour with
    // Vite's `Cache-Control: no-cache` is to keep the cached module graph
    // and serve it on revalidation 304s, which means a normal Cmd+R after
    // a code change reuses the previous bundle. `no-store` forces the
    // browser to refetch every asset on every reload — slower than
    // production caching, but in dev the convenience > the bandwidth.
    headers: {
      "Cache-Control": "no-store, max-age=0, must-revalidate",
    },
    proxy: {
      "/api": {
        target: DEV_PROXY_TARGET,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: PREVIEW_PORT,
    // Railway exposes the service on `<name>.up.railway.app` (and any
    // attached custom domain). Vite preview rejects host headers it
    // doesn't recognise — `true` means accept whatever Railway routes us.
    allowedHosts: true,
    strictPort: false,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    // Split the heavy vendors into their own chunks so no single file trips
    // Vite's 500 kB advisory (the Railway build "warning") — and so a code
    // change doesn't bust the cache for react/recharts/grid on every deploy.
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("recharts") || id.includes("/d3-")) return "charts";
          if (id.includes("react-grid-layout") || id.includes("react-resizable")) return "grid";
          if (id.includes("/react/") || id.includes("/react-dom/") || id.includes("/scheduler/")) return "react";
          return "vendor";
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    include: ["src/**/*.{test,spec}.{js,jsx}"],
    css: false,
  },
});
