/* GYST barcode scanner — build 20260513v
 *
 * Native BarcodeDetector where available; ZXing per-frame fallback
 * (lazy CDN). Multi-source lookup chain — works for groceries, books,
 * household goods, electronics, anything with a UPC/EAN/ISBN/QR.
 *
 * Lookup order:
 *   1. Open Food Facts        — groceries
 *   2. UPCitemdb (trial tier) — general consumer products (100/day)
 *   3. Open Library           — books (ISBN-13 only)
 *   4. Raw UPC                — if all fail, stage the code itself so
 *                               "Use this product" still works.
 *
 * Always stashes a hit in window.__lastBarcode = {name, upc}; the
 * Add-items dialog's "Use this product" button reads from there.
 */

(function () {
  let stream = null;
  let videoEl = null;
  let onProductCb = null;
  let scanning = false;
  let detector = null;
  let zxingReader = null;
  let zxingCanvas = null;
  let zxingCtx = null;
  let frameCount = 0;
  let lastCode = null;
  // The still-image blob captured at decode time. Sent to /api/scan-product
  // as the item's photo so barcode-added items aren't placeholder-pathed.
  let _lastStillBlob = null;

  const FORMATS_FULL = [
    "ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39",
    "code_93", "codabar", "itf", "qr_code", "data_matrix", "pdf417",
  ];

  function setStatus(msg) {
    const el = document.getElementById("barcode-status");
    if (el) el.textContent = msg;
    try { console.log("[gyst-barcode]", msg); } catch (_) {}
  }

  async function startCamera(video) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      const insecure = window.location.protocol !== "https:" &&
                       window.location.hostname !== "localhost" &&
                       window.location.hostname !== "127.0.0.1";
      throw new Error(insecure
        ? "Camera requires HTTPS. Use manual UPC entry below."
        : "Camera API not available in this browser.");
    }
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1280 }, height: { ideal: 720 },
      },
    });
    video.srcObject = stream;
    await video.play();
    if (!video.videoWidth || !video.videoHeight) {
      await new Promise((resolve) => {
        const onMeta = () => { video.removeEventListener("loadedmetadata", onMeta); resolve(); };
        video.addEventListener("loadedmetadata", onMeta);
        setTimeout(resolve, 1500);
      });
    }
  }

  function stopCamera() {
    if (stream) { for (const t of stream.getTracks()) t.stop(); stream = null; }
    if (videoEl) { try { videoEl.srcObject = null; } catch (_) {} }
  }

  async function _snapshotVideoFrame() {
    // Snapshot the current video frame to a JPEG Blob (~150 KB at
    // 1280x720). Used to upload the still alongside the barcode add
    // so each scanned item has a real photo, not a placeholder.
    if (!videoEl || !videoEl.videoWidth || !videoEl.videoHeight) return null;
    const canvas = document.createElement("canvas");
    canvas.width = videoEl.videoWidth;
    canvas.height = videoEl.videoHeight;
    const ctx = canvas.getContext("2d");
    try { ctx.drawImage(videoEl, 0, 0); } catch (e) { return null; }
    return await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.85));
  }

  // ---- Multi-source lookups -----------------------------------------------
  async function lookupOpenFoodFacts(upc) {
    try {
      const r = await fetch(
        "https://world.openfoodfacts.org/api/v2/product/" +
          encodeURIComponent(upc) + ".json",
        { credentials: "omit" }
      );
      if (!r.ok) return null;
      const j = await r.json();
      const p = j && j.product;
      if (!p) return null;
      const name = p.product_name || p.product_name_en || p.generic_name ||
                   p.abbreviated_product_name || null;
      if (!name) return null;
      const image_url = p.image_front_url || p.image_url || "";
      return { name, image_url, est_price_usd: 0, category: "pantry / food" };
    } catch { return null; }
  }

  async function lookupUPCitemdb(upc) {
    try {
      const r = await fetch(
        "https://api.upcitemdb.com/prod/trial/lookup?upc=" +
          encodeURIComponent(upc),
        { credentials: "omit" }
      );
      if (!r.ok) return null;
      const j = await r.json();
      const items = j && j.items;
      if (!items || !items.length) return null;
      const it = items[0];
      const name = it.title || (it.brand && it.model ? it.brand + " " + it.model : "") || null;
      if (!name) return null;
      const image_url = (it.images && it.images[0]) || "";
      // Midpoint of lowest/highest recorded — UPCitemdb prices are USD.
      const lo = parseFloat(it.lowest_recorded_price || 0);
      const hi = parseFloat(it.highest_recorded_price || 0);
      const est_price_usd = (lo && hi) ? (lo + hi) / 2 : (lo || hi || 0);
      // Pick a sensible category based on the source's category hint.
      let category = "other";
      const cat = (it.category || "").toLowerCase();
      if (cat.includes("food") || cat.includes("grocer")) category = "pantry / food";
      else if (cat.includes("book")) category = "book";
      else if (cat.includes("electron")) category = "electronics";
      return { name, image_url, est_price_usd, category };
    } catch { return null; }
  }

  async function lookupOpenLibrary(upc) {
    if (!/^97[89]\d{10}$/.test(upc)) return null;
    try {
      const r = await fetch(
        "https://openlibrary.org/api/books?bibkeys=ISBN:" +
          encodeURIComponent(upc) + "&format=json&jscmd=data",
        { credentials: "omit" }
      );
      if (!r.ok) return null;
      const j = await r.json();
      const key = "ISBN:" + upc;
      const rec = j && j[key];
      if (!rec) return null;
      const title = rec.title || "";
      const author = (rec.authors && rec.authors[0] && rec.authors[0].name) || "";
      const name = author ? (title + " — " + author) : (title || null);
      if (!name) return null;
      const image_url = (rec.cover && (rec.cover.large || rec.cover.medium || rec.cover.small)) || "";
      return { name, image_url, est_price_usd: 0, category: "book" };
    } catch { return null; }
  }

  async function lookupBarcode(upc) {
    // Try sources in order. First hit wins.
    let r = await lookupOpenFoodFacts(upc);
    if (r) return Object.assign(r, { source: "Open Food Facts" });
    r = await lookupUPCitemdb(upc);
    if (r) return Object.assign(r, { source: "UPCitemdb" });
    r = await lookupOpenLibrary(upc);
    if (r) return Object.assign(r, { source: "Open Library" });
    return null;
  }

  // ---- Scan loop ----------------------------------------------------------
  function buildDetector() {
    if (!("BarcodeDetector" in window)) return null;
    try {
      try { return new BarcodeDetector({ formats: FORMATS_FULL }); }
      catch { return new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] }); }
    } catch { return null; }
  }

  async function decodeNativeFrame(video) {
    if (!detector) return null;
    try {
      const codes = await detector.detect(video);
      if (codes && codes.length) return codes[0].rawValue;
    } catch {}
    return null;
  }

  // ZXing is now bundled locally at /zxing.min.js — no public-internet
  // dependency. We cache the load result so a single failure (e.g.
  // permission denied, manifest weirdness) doesn't trigger a status-
  // line flicker on every subsequent frame in the scan loop.
  let _zxingLoadAttempted = false;
  let _zxingLoadFailed = false;
  async function ensureZxing() {
    if (window.ZXing) return window.ZXing;
    if (_zxingLoadFailed) return null;
    if (_zxingLoadAttempted) {
      // A previous frame is still loading; wait briefly and retry.
      await new Promise((r) => setTimeout(r, 100));
      return window.ZXing || null;
    }
    _zxingLoadAttempted = true;
    try {
      await new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "/zxing.min.js?v=20260514c";
        s.onload = resolve;
        s.onerror = () => reject(new Error("local /zxing.min.js failed"));
        document.head.appendChild(s);
      });
    } catch (e) {
      _zxingLoadFailed = true;
      setStatus(
        "ZXing fallback unavailable: " + e.message
        + " (native scanner only)"
      );
      return null;
    }
    return window.ZXing || null;
  }

  async function decodeZxingFrame(video) {
    const lib = await ensureZxing();
    if (!lib || !video.videoWidth) return null;
    if (!zxingReader) {
      try {
        zxingReader = new lib.MultiFormatReader();
        const hints = new Map();
        const f = lib.BarcodeFormat;
        if (f) {
          hints.set(lib.DecodeHintType.POSSIBLE_FORMATS,
            [f.EAN_13, f.EAN_8, f.UPC_A, f.UPC_E, f.CODE_128, f.CODE_39,
             f.QR_CODE].filter(Boolean));
          hints.set(lib.DecodeHintType.TRY_HARDER, true);
          zxingReader.setHints(hints);
        }
      } catch (e) { setStatus("ZXing reader ctor failed: " + e.message); return null; }
    }
    if (!zxingCanvas) {
      zxingCanvas = document.createElement("canvas");
      zxingCtx = zxingCanvas.getContext("2d", { willReadFrequently: true });
    }
    const w = Math.min(video.videoWidth, 1024);
    const h = Math.round(video.videoHeight * (w / video.videoWidth));
    zxingCanvas.width = w; zxingCanvas.height = h;
    try {
      zxingCtx.drawImage(video, 0, 0, w, h);
      const data = zxingCtx.getImageData(0, 0, w, h);
      const lum = new lib.RGBLuminanceSource(
        new Int32Array(data.data.buffer.slice(0)), w, h
      );
      const bitmap = new lib.BinaryBitmap(new lib.HybridBinarizer(lum));
      const result = zxingReader.decode(bitmap);
      return result && result.getText ? result.getText() : null;
    } catch { return null; }
    finally { try { zxingReader.reset(); } catch (_) {} }
  }

  async function scanLoop() {
    setStatus((detector ? "Native scanner" : "ZXing fallback") +
              " active — point a barcode center, hold steady.");
    while (scanning && videoEl) {
      frameCount++;
      if (frameCount % 30 === 0) {
        const sf = document.getElementById("barcode-status");
        if (sf && !sf.dataset.locked) {
          sf.textContent = (detector ? "Native scanner" : "ZXing") +
            ` · ${frameCount} frames · move closer if not detected`;
        }
      }
      let code = null;
      try {
        code = await decodeNativeFrame(videoEl);
        if (!code) code = await decodeZxingFrame(videoEl);
      } catch (e) {
        try { console.warn("[gyst-barcode] decode error", e); } catch (_) {}
      }
      if (code && code !== lastCode) {
        lastCode = code;
        const st = document.getElementById("barcode-status");
        if (st) { st.dataset.locked = "1"; st.textContent = `Looking up ${code}…`; }
        const hit = await lookupBarcode(code);
        // Capture a still BEFORE we pause + before we change the
        // dialog — the canvas should snapshot the frame we actually
        // decoded.
        try { _lastStillBlob = await _snapshotVideoFrame(); }
        catch (_) { _lastStillBlob = null; }
        if (hit && hit.name) {
          window.__lastBarcode = {
            name: hit.name,
            upc: code,
            image_url: hit.image_url || "",
            est_price_usd: hit.est_price_usd || 0,
            category: hit.category || "other",
            source: hit.source || "",
          };
          let extra = "";
          if (hit.est_price_usd) {
            extra = ` (~USD $${hit.est_price_usd.toFixed(2)})`;
          }
          setStatus(`Found (${hit.source}): ${hit.name}${extra}. Tap "Use this product" to add.`);
          if (onProductCb) { try { onProductCb(hit.name, code); } catch (_) {} }
        } else {
          // No database match — stage the raw UPC so the user can
          // confirm adding it as-is, or type a friendlier name.
          window.__lastBarcode = {
            name: code, upc: code,
            image_url: "", est_price_usd: 0, category: "other", source: "",
          };
          if (st) {
            st.textContent =
              `Read ${code}. No database match — tap Add to save with the code as its name, or type a different UPC below.`;
          }
        }
        // STOP scanning on first hit AND freeze the video frame so
        // the user can see what was captured. We pause() rather than
        // stopping the stream — pausing keeps the last frame painted
        // on the <video> element while halting decode work.
        scanning = false;
        try { if (videoEl) videoEl.pause(); } catch (_) {}
        if (st) {
          st.dataset.locked = "1";
          const btn = document.getElementById("barcode-rescan-btn");
          if (btn) btn.style.display = "inline-block";
        }
        return;
      } else {
        await new Promise((r) => setTimeout(r, 200));
      }
    }
  }

  window.gystBarcode = {
    async open(onProduct) {
      onProductCb = onProduct || null;
      const dlg = document.getElementById("barcode-dialog");
      videoEl = document.getElementById("barcode-video");
      if (!dlg || !videoEl) return;
      dlg.style.display = "flex";
      window.__lastBarcode = null;
      frameCount = 0;
      lastCode = null;
      setStatus("Opening camera…");
      try { await startCamera(videoEl); }
      catch (e) { setStatus("Camera unavailable: " + e.message); return; }
      detector = buildDetector();
      setStatus(detector ? "Native scanner ready…" : "Loading ZXing…");
      if (!detector) await ensureZxing();
      scanning = true;
      scanLoop();
    },
    close() {
      scanning = false;
      stopCamera();
      const dlg = document.getElementById("barcode-dialog");
      if (dlg) dlg.style.display = "none";
      const btn = document.getElementById("barcode-rescan-btn");
      if (btn) btn.style.display = "none";
    },
    rescan() {
      // Resume from the frozen frame: un-pause the video, clear the
      // last code, restart the loop.
      lastCode = null;
      frameCount = 0;
      window.__lastBarcode = null;
      const st = document.getElementById("barcode-status");
      if (st) { delete st.dataset.locked; st.textContent = "Scanning…"; }
      const btn = document.getElementById("barcode-rescan-btn");
      if (btn) btn.style.display = "none";
      try { if (videoEl) { videoEl.play().catch(() => {}); } } catch (_) {}
      scanning = true;
      scanLoop();
    },

    async useCurrentMatch() {
      // Sends the staged __lastBarcode plus the captured still frame
      // (or product image URL) and est USD price to /api/scan-product.
      // Server converts USD -> CAD via FX and saves the still as the
      // item's photo. Reloads the page on success.
      const ev = window.__lastBarcode;
      if (!ev || !ev.name) {
        setStatus("No product detected yet. Aim at a barcode first.");
        return;
      }
      let room = "default";
      try {
        const sel = document.querySelector("[data-radix-select-value]");
        if (sel && sel.textContent) {
          const t = sel.textContent.trim();
          if (t) room = t;
        }
      } catch (_) {}

      setStatus("Adding " + ev.name + " to " + room + "…");
      try {
        const fd = new FormData();
        fd.append("name", ev.name);
        fd.append("upc", ev.upc || "");
        fd.append("room", room);
        if (ev.image_url) fd.append("image_url", ev.image_url);
        if (ev.est_price_usd) fd.append("est_price_usd", String(ev.est_price_usd));
        if (ev.category) fd.append("category", ev.category);
        if (_lastStillBlob) fd.append("file", _lastStillBlob, "scan.jpg");

        const r = await fetch("/api/scan-product", {
          method: "POST",
          credentials: "include",
          body: fd,
        });
        if (!r.ok) {
          let detail = "HTTP " + r.status;
          try { const j = await r.json(); if (j && j.detail) detail = j.detail; } catch (_) {}
          throw new Error(detail);
        }
        const j = await r.json().catch(() => ({}));
        let msg = "Added " + ev.name + " to " + room + ".";
        if (j && j.estimated_value_cad) {
          msg += " Est. CAD $" + j.estimated_value_cad.toFixed(2);
        }
        setStatus(msg + " Reloading…");
        scanning = false;
        try { if (stream) for (const t of stream.getTracks()) t.stop(); } catch (_) {}
        _lastStillBlob = null;
        setTimeout(() => window.location.reload(), 800);
      } catch (e) {
        setStatus("Add failed: " + (e && e.message || e));
        try { console.warn("[gyst-barcode] add failed", e); } catch (_) {}
      }
    },

    lookupBarcode(upc) {
      // Expose the multi-source lookup so manual-UPC entry can reuse
      // the full pipeline instead of doing its own OFF-only lookup.
      return lookupBarcode(upc);
    },
  };
})();
