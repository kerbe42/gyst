/* GYST scan-product helper — defines window._gystAddBarcode used by
 * the barcode dialog and (potentially) other surfaces. Lives in its own
 * file because React won't execute inline <script> tags rendered via
 * JSX, so the rx.el.script(content) pattern silently does nothing. */
(function () {
  window._gystAddBarcode = async function (name, upc) {
    // Pull the current room from the page's Radix select; fall back
    // to "default" when the select isn't on the current page.
    let room = "default";
    try {
      const sel = document.querySelector("[data-radix-select-value]");
      if (sel && sel.textContent) {
        const t = sel.textContent.trim();
        if (t) room = t;
      }
    } catch (_) {}

    const status = document.getElementById("barcode-status");
    if (status) status.textContent = "Adding " + name + " to " + room + "…";
    try {
      const r = await fetch("/api/scan-product", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, upc, room }),
      });
      if (!r.ok) {
        let detail = "HTTP " + r.status;
        try {
          const j = await r.json();
          if (j && j.detail) detail = j.detail;
        } catch (_) {}
        throw new Error(detail);
      }
      if (status) status.textContent = "Added " + name + " to " + room + ". Reloading…";
      // Reload so the inventory page refreshes.
      setTimeout(function () { window.location.reload(); }, 800);
    } catch (e) {
      if (status) status.textContent = "Add failed: " + (e && e.message || e);
      try { console.warn("[scan-product] add failed", e); } catch (_) {}
    }
  };
  try { console.log("[scan-product] _gystAddBarcode wired"); } catch (_) {}
})();
