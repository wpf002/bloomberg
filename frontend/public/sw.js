// Static-shell service worker.
//
// Strategy:
//   - HTML / nav requests   → NETWORK-FIRST (with cache fallback for offline).
//     Required because index.html references content-hashed asset bundles
//     (`/assets/index-<hash>.js`) — if we cache the HTML and a new deploy
//     ships, the cached HTML points at a hash that no longer exists on the
//     server and the page goes blank. Network-first ensures every refresh
//     picks up the latest hashed-asset references when online.
//   - Hashed assets (/assets/*) → CACHE-FIRST. These filenames change on
//     every build (Vite content-hash), so caching forever is safe.
//   - /api/* + non-GET     → SKIP entirely. Quotes/news/charts must always
//     hit the network so users never see stale prices.

const CACHE = "bt-shell-v2";
const SHELL_FALLBACK = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL_FALLBACK)));
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

function isHashedAsset(url) {
  // Vite ships hashed filenames under /assets/. Anything else (favicon,
  // manifest, sw.js itself) we treat as a navigable resource.
  return url.pathname.startsWith("/assets/");
}

function isNavigation(request, url) {
  if (request.mode === "navigate") return true;
  // Direct fetches of "/" or "/index.html" should also use network-first.
  return url.pathname === "/" || url.pathname === "/index.html";
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Never cache API / websocket traffic.
  if (url.pathname.startsWith("/api/")) return;
  // Don't intercept cross-origin requests (the API lives on a different
  // Railway subdomain in production).
  if (url.origin !== self.location.origin) return;

  if (isNavigation(request, url)) {
    // Network-first: always try the network so a new deploy's index.html
    // wins. Fall back to the last cached shell only when offline.
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE).then((c) => c.put(request, clone));
          }
          return response;
        })
        .catch(() =>
          caches.match(request).then((c) => c || caches.match("/index.html"))
        )
    );
    return;
  }

  if (isHashedAsset(url)) {
    // Cache-first: hashed asset URLs are immutable, so a hit is safe and
    // makes navigation instant on a flaky connection.
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const clone = response.clone();
              caches.open(CACHE).then((c) => c.put(request, clone));
            }
            return response;
          })
      )
    );
    return;
  }

  // Anything else (favicon, robots, etc.) — pass through with opportunistic
  // caching, but never block on a stale cache.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE).then((c) => c.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
