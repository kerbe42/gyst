/* Register the service worker, and expose tiny helpers on window.gystPush
   so the Settings page can drive subscribe / unsubscribe / test from a
   simple <button onclick>. Keeping it global-and-imperative avoids fighting
   Reflex's component system for what is essentially browser plumbing. */

// ---- Build version handshake -----------------------------------------------
// This string is the single source of truth for "what page-side bundle of
// PWA glue is loaded". It MUST match the BUILD_VERSION string in sw.js.
// When they disagree, we know the page is running newer client code than
// the active service worker (or vice versa) and we force a full reset.
const BUILD_VERSION = "20260612d";

// Surface the build identity to anything else on the page (the on-screen
// build banner reads this). Bundle hash comes from a <script src> on the
// page that points at /assets/esm-*.js — we sniff it once at load time.
function _sniffBundleHash() {
  try {
    const re = /\/assets\/(esm-[A-Za-z0-9_-]+)\.js/;
    for (const s of document.scripts || []) {
      const m = s.src && s.src.match(re);
      if (m) return m[1];
    }
  } catch (_) {}
  return "unknown";
}

function _isDebugMode() {
  try {
    const u = new URL(window.location.href);
    if (u.searchParams.get("debug") === "1") {
      // Sticky: setting ?debug=1 once flips on the local toggle too.
      try { localStorage.setItem("gyst_debug", "1"); } catch (_) {}
      return true;
    }
    if (u.searchParams.get("debug") === "0") {
      try { localStorage.removeItem("gyst_debug"); } catch (_) {}
    }
    try { return localStorage.getItem("gyst_debug") === "1"; } catch (_) {}
  } catch (_) {}
  return false;
}

function _publishBuild(swBuild) {
  try {
    window.__gystBuild = {
      build: BUILD_VERSION,
      sw_build: swBuild || "unknown",
      bundle: _sniffBundleHash(),
    };
    // Repaint the build banner if it's already in the DOM.
    const el = document.getElementById("gyst-build-banner");
    if (el) {
      const b = window.__gystBuild;
      el.textContent = `build ${b.build} · sw ${b.sw_build} · ${b.bundle}`;
      // Auto-hide once the SW build is verified to match the page
      // build. Keep visible if debug mode is on (URL ?debug=1 or
      // localStorage.gyst_debug = "1") so we can still diagnose in prod.
      if (
        swBuild &&
        swBuild !== "unknown" &&
        swBuild === BUILD_VERSION &&
        !_isDebugMode()
      ) {
        el.style.display = "none";
      } else if (_isDebugMode()) {
        el.style.display = "";
      }
    }
  } catch (_) {}
}
_publishBuild(null);

// ---- Aggressive self-heal --------------------------------------------------
// Runs on EVERY load. Three independent reset triggers:
//   1. sw.js on the network advertises a BUILD_VERSION different from ours.
//   2. The active SW controller was installed before this page's build (we
//      can't read source from a Client, but we can ask it via postMessage
//      and time out fast if it doesn't reply with our build).
//   3. ?gyst_reset=1 was passed as a URL param (manual escape hatch).
//
// To avoid reload loops, we limit one reset per (build, page-load) using
// sessionStorage. The key includes BUILD_VERSION so a NEW build push
// always gets one fresh shot at resetting, even in a tab that already
// reset itself for a previous build.
async function _hardReset(reason) {
  console.warn(`[gyst-reset] forcing reset: ${reason}`);
  try {
    if ("caches" in self) {
      const ks = await caches.keys();
      await Promise.all(ks.map((k) => caches.delete(k)));
    }
  } catch (_) {}
  try {
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
  } catch (_) {}
  // Add a cache-busting query so the next load can't be served by HTTP cache
  // or any surviving SW. Drop the query on the load AFTER the reset to keep
  // the URL clean.
  const u = new URL(window.location.href);
  u.searchParams.set("gyst_reset_done", BUILD_VERSION);
  window.location.replace(u.toString());
}

(async () => {
  if (typeof window === "undefined") return;
  try {
    // One-shot guard per build per page-load.
    const GUARD = `gyst_reset_${BUILD_VERSION}`;
    const url = new URL(window.location.href);
    const justReset = url.searchParams.get("gyst_reset_done") === BUILD_VERSION;
    if (justReset) {
      // We just reloaded after a reset. Clean the URL and let the page run.
      url.searchParams.delete("gyst_reset_done");
      window.history.replaceState({}, "", url.toString());
      sessionStorage.setItem(GUARD, "done");
      return;
    }

    if (url.searchParams.get("gyst_reset") === "1") {
      sessionStorage.setItem(GUARD, "manual");
      return _hardReset("manual ?gyst_reset=1");
    }

    if (sessionStorage.getItem(GUARD)) return; // already handled this tab/build

    if (!("serviceWorker" in navigator)) {
      _publishBuild(BUILD_VERSION);
      return;
    }

    // Trigger 1: fetch /sw.js fresh and look at its BUILD_VERSION line.
    try {
      const r = await fetch("/sw.js", { cache: "no-store" });
      if (r.ok) {
        const txt = await r.text();
        const m = txt.match(/BUILD_VERSION\s*=\s*"([^"]+)"/);
        const networkSwBuild = m ? m[1] : null;
        if (networkSwBuild && networkSwBuild !== BUILD_VERSION) {
          sessionStorage.setItem(GUARD, "sw-mismatch");
          return _hardReset(
            `sw.js BUILD_VERSION=${networkSwBuild} but page=${BUILD_VERSION}`
          );
        }
      }
    } catch (_) {}

    // Trigger 2: ask the active SW its build via postMessage; if missing,
    // wrong, or unresponsive within 1.5s, treat as stale.
    const controller = navigator.serviceWorker.controller;
    if (controller) {
      const swBuild = await new Promise((resolve) => {
        let done = false;
        const ch = new MessageChannel();
        ch.port1.onmessage = (e) => {
          if (done) return;
          done = true;
          resolve(e.data && e.data.build);
        };
        try {
          controller.postMessage({ type: "GYST_BUILD?" }, [ch.port2]);
        } catch (_) {
          done = true;
          resolve(null);
        }
        setTimeout(() => {
          if (!done) {
            done = true;
            resolve(null);
          }
        }, 1500);
      });
      if (swBuild !== BUILD_VERSION) {
        sessionStorage.setItem(GUARD, "controller-mismatch");
        return _hardReset(
          `active SW build=${swBuild || "<no-reply>"} but page=${BUILD_VERSION}`
        );
      }
      _publishBuild(swBuild);
    } else {
      _publishBuild(BUILD_VERSION);
    }

    sessionStorage.setItem(GUARD, "ok");
  } catch (e) {
    console.warn("[gyst-reset] failed:", e);
  }
})();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", async () => {
    try {
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });

      // Force an update check on every page load. The SW spec only does
      // this every ~24h by default, which means a fix push can sit
      // invisible behind a stale cache for a full day. Calling update()
      // pulls /sw.js fresh; if it differs, install → activate runs and
      // skipWaiting + clients.claim from sw.js takes over right away.
      try { await reg.update(); } catch (_) {}

      // When the new worker takes control mid-session, reload once so
      // the page picks up fresh /assets/* under the new SW (the old SW
      // had cached the broken bundle).
      let reloadGuard = false;
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (reloadGuard) return;
        reloadGuard = true;
        console.log("[pwa] new SW took control — reloading");
        window.location.reload();
      });

      // Self-heal: if a chunked /assets/*.js 404s, the active SW is
      // serving a stale HTML that references long-gone bundle hashes.
      // Nuke its caches + unregister and reload.
      window.addEventListener("error", (e) => {
        const src = e.target && e.target.src;
        if (typeof src === "string" && /\/assets\/[A-Za-z0-9_./-]+\.js$/.test(src)) {
          console.warn("[pwa] asset load failed, busting SW cache:", src);
          _hardReset(`asset load failed: ${src}`);
        }
      }, true);
    } catch (err) {
      console.warn("[pwa] sw register failed:", err);
    }
  });
}

function b64UrlToUint8Array(b64url) {
  const padding = "=".repeat((4 - (b64url.length % 4)) % 4);
  const b64 = (b64url + padding).replace(/-/g, "+").replace(/_/g, "/");
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return arr;
}

window.gystPush = {
  async isSupported() {
    return (
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window
    );
  },

  async currentPermission() {
    if (!("Notification" in window)) return "unsupported";
    return Notification.permission; // "default" | "granted" | "denied"
  },

  async currentSubscription() {
    if (!("serviceWorker" in navigator)) return null;
    const reg = await navigator.serviceWorker.ready;
    return reg.pushManager.getSubscription();
  },

  async subscribe() {
    if (!(await this.isSupported())) {
      throw new Error("Push notifications aren't supported in this browser.");
    }
    const perm = await Notification.requestPermission();
    if (perm !== "granted") {
      throw new Error("Notification permission denied.");
    }
    const reg = await navigator.serviceWorker.ready;
    const r = await fetch("/push/vapid-public-key", { credentials: "include" });
    if (!r.ok) throw new Error(`vapid key fetch ${r.status}`);
    const { public_key } = await r.json();
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: b64UrlToUint8Array(public_key),
    });
    const payload = sub.toJSON();
    const sr = await fetch("/push/subscribe", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!sr.ok) throw new Error(`subscribe ${sr.status}`);
    return true;
  },

  async unsubscribe() {
    const sub = await this.currentSubscription();
    let endpoint = null;
    if (sub) {
      endpoint = sub.endpoint;
      await sub.unsubscribe();
    }
    await fetch("/push/unsubscribe", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint }),
    });
    return true;
  },

  async sendTest() {
    const r = await fetch("/push/test", {
      method: "POST",
      credentials: "include",
    });
    if (!r.ok) throw new Error(`test ${r.status}`);
    return r.json();
  },
};
