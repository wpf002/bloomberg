// Static-shell service worker.
//
// Strategy: cache the HTML shell + Vite-built assets the first time the
// browser sees them, serve cache-first afterwards so the Launchpad opens
// instantly even on a flaky connection. We deliberately do NOT cache
// anything under /api/ — quotes/news/charts must always hit the network
// so users never see stale prices.

const CACHE = "bt-shell-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Never cache API or websocket traffic.
  if (url.pathname.startsWith("/api/")) return;
  if (request.method !== "GET") return;

  // Cache-first for the static shell + Vite assets.
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok && url.origin === self.location.origin) {
            const clone = response.clone();
            caches.open(CACHE).then((c) => c.put(request, clone));
          }
          return response;
        })
    )
  );
});
