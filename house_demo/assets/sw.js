/* Service worker — does two jobs:
 *   1. Marks the app as PWA-installable (Chrome needs a SW with a fetch
 *      handler to enable "Install app").
 *   2. Caches static assets so repeat visits feel instant on slow networks.
 *
 * Caching strategy:
 *   - Static fingerprinted assets (/assets/*.{js,css,woff2,...}, /icons/*,
 *     /manifest.webmanifest, /pwa-register.js):
 *     CACHE-FIRST. The filenames carry content hashes so they're safe to
 *     pin forever. On cache miss, fetch and store.
 *   - HTML navigations:
 *     NETWORK-FIRST with a 2s timeout, then cache fallback. Keeps the user
 *     seeing the live app whenever the server is reachable, but lets stale
 *     content show instead of an error if the WS dies mid-trip.
 *   - Everything else (Reflex /_event WebSocket upgrades, /photo/*,
 *     /chore_photo/*, /photo_crop/*, the JSON event API):
 *     PASS-THROUGH. We don't call respondWith so the browser handles the
 *     request natively (preserving cookies, websockets, range requests,
 *     content negotiation, etc.).
 */

// MUST match BUILD_VERSION in /assets/pwa-register.js. The page-side script
// fetches /sw.js with cache:'no-store' and compares this string; on mismatch
// it forces a hard reset (unregister + caches.delete + reload).
const BUILD_VERSION = "20260612a";
const CACHE_VERSION = "v5";
// Caching policy: when NETWORK_ONLY is true, the fetch handler is a
// transparent pass-through to the network. The app currently runs in
// this mode because Reflex emits content-hashed bundles under
// /assets/* which already have Cache-Control: immutable from Caddy,
// so a service-worker layer adds nothing and was the root cause of
// stale-bundle incidents on phones. Re-enable cache pre-fill by
// flipping this to false and bumping CACHE_VERSION.
const NETWORK_ONLY = true;
const STATIC_CACHE = `gyst-static-${CACHE_VERSION}`;
const PAGE_CACHE = `gyst-pages-${CACHE_VERSION}`;

self.addEventListener("install", (event) => {
  // Take over right away on first install / upgrade.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Take control of all open tabs immediately, and clean up any caches
  // from a previous version of this SW.
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter((k) => !k.endsWith(`-${CACHE_VERSION}`))
        .map((k) => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

function isStaticAsset(url) {
  if (url.pathname.startsWith("/assets/")) return true;
  if (url.pathname.startsWith("/icons/")) return true;
  if (url.pathname === "/manifest.webmanifest") return true;
  if (url.pathname === "/favicon.ico") return true;
  return false;
}

// ---- Push notifications -----------------------------------------------------
// The server POSTs an encrypted payload with {title, body, url}; we surface it
// as a native notification. Clicking the notification opens (or focuses) the
// URL inside our scope.

// ---- Build handshake -------------------------------------------------------
// pwa-register.js asks "what build are you?" via postMessage with a transferred
// MessagePort. We reply with our BUILD_VERSION so the page can decide whether
// the controlling SW is stale relative to the freshly-loaded HTML/JS.
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "GYST_BUILD?") {
    const port = event.ports && event.ports[0];
    if (port) {
      try { port.postMessage({ build: BUILD_VERSION }); } catch (_) {}
    }
  }
});

self.addEventListener("push", (event) => {
  let data = { title: "GYST", body: "", url: "/" };
  if (event.data) {
    try { data = { ...data, ...event.data.json() }; }
    catch { data.body = event.data.text() || data.body; }
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: data.url },
      tag: data.tag || "gyst",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      const u = new URL(c.url);
      if (u.origin === self.location.origin) {
        c.focus();
        if (u.pathname !== target) c.navigate(target).catch(() => {});
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});


self.addEventListener("fetch", (event) => {
  const req = event.request;

  // DEBUG: when NETWORK_ONLY is set, do nothing — the browser handles
  // the request directly. This rules out service-worker caching as a
  // factor when diagnosing fresh-bundle issues.
  if (NETWORK_ONLY) return;

  // Never touch non-GETs, cross-origin requests, or anything we don't
  // explicitly understand. Just let the browser do it.
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // PWA Web Share Target — POST entrypoint. Even on the GET handoff
  // we never want to cache or intercept; just let it through.
  if (url.pathname === "/share-target") return;

  // Static fingerprinted assets — cache-first.
  if (isStaticAsset(url)) {
    event.respondWith((async () => {
      const cache = await caches.open(STATIC_CACHE);
      const hit = await cache.match(req);
      if (hit) return hit;
      const fresh = await fetch(req);
      if (fresh.ok) cache.put(req, fresh.clone());
      return fresh;
    })());
    return;
  }

  // HTML navigations — network-first with a 2s budget, cache fallback.
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(PAGE_CACHE);
      try {
        const timeout = new Promise((_, rej) =>
          setTimeout(() => rej(new Error("net timeout")), 2000)
        );
        const fresh = await Promise.race([fetch(req), timeout]);
        if (fresh && fresh.ok) cache.put(req, fresh.clone());
        return fresh;
      } catch {
        const cached = await cache.match(req);
        if (cached) return cached;
        // Last-ditch: fall back to the root page from cache if there is one.
        const root = await cache.match("/");
        if (root) return root;
        return new Response("Offline", { status: 503 });
      }
    })());
    return;
  }

  // Everything else — pass through. No respondWith, no interception.
  // Reflex's /_event WebSocket, photo endpoints, etc. need this.
});
