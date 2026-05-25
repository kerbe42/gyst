#!/usr/bin/env bun
/*
 * Minimal Reflex /_event WebSocket probe.
 *
 * Goal: detect whether the FRESH bundle actually triggers
 * "d is not a function" under real connection conditions. The stale-cache
 * traces all reference esm-t7D30Tdn.js, which is no longer on disk — but
 * we want a yes/no for the current bundle too.
 *
 * Strategy:
 *  1. Fetch the page HTML to discover the current esm-*.js bundle hash.
 *  2. Hit the login endpoint via Reflex's socket.io-style WS handshake
 *     and emit a no-op `event` payload, then wait briefly for any frames.
 *  3. Print bundle hash + any error frames we saw. We DO NOT execute the
 *     bundle's JS; Bun isn't a browser. But Reflex sends server-side
 *     errors back as event frames, and those are what we care about.
 *
 * Run:  bun run scripts/probe-ws.mjs https://gyst.local
 */

const base = process.argv[2] || "https://gyst.local";
const wsUrl = base.replace(/^http/, "ws") + "/_event/?EIO=4&transport=websocket";

// We're hitting a homelab `tls internal` cert; trust it for this probe only.
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";

async function getBundleHash() {
  const r = await fetch(base + "/", { redirect: "manual" });
  const html = await r.text();
  const m = html.match(/\/assets\/(esm-[A-Za-z0-9_-]+)\.js/);
  return m ? m[1] : null;
}

function probe() {
  return new Promise((resolve) => {
    const errors = [];
    const frames = [];
    const ws = new WebSocket(wsUrl);
    const deadline = setTimeout(() => {
      try { ws.close(); } catch (_) {}
      resolve({ frames, errors });
    }, 4000);

    ws.addEventListener("open", () => {
      // Socket.IO v4 EIO=4: server sends "0{...}" handshake; client replies "40".
      // We don't need to talk; just listen for what comes back unsolicited.
    });
    ws.addEventListener("message", (ev) => {
      const data = typeof ev.data === "string" ? ev.data : "<binary>";
      frames.push(data.slice(0, 400));
      // After the initial open frame, send a "40/" namespace connect so the
      // server may surface state-init errors.
      if (data.startsWith("0{")) {
        try { ws.send("40"); } catch (_) {}
      }
      if (/d is not a function|TypeError/i.test(data)) {
        errors.push(data.slice(0, 800));
      }
    });
    ws.addEventListener("error", (e) => {
      errors.push(`ws-error: ${e.message || e.type}`);
    });
    ws.addEventListener("close", () => {
      clearTimeout(deadline);
      resolve({ frames, errors });
    });
  });
}

const bundle = await getBundleHash();
console.log("bundle:", bundle || "<not found>");
const { frames, errors } = await probe();
console.log(`frames received: ${frames.length}`);
for (const f of frames) console.log("  <-", f);
if (errors.length) {
  console.log("ERRORS:");
  for (const e of errors) console.log("  !!", e);
  process.exit(2);
}
console.log("no 'd is not a function' / TypeError in WS frames");
