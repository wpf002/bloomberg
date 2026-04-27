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
  },
});
