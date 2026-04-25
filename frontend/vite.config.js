import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

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
        target: process.env.VITE_API_URL || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
