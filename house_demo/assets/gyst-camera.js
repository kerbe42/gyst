// === GYST in-page camera — build 20260514d ===
//
// Why this exists: on memory-tight Android phones in PWA mode, the
// HTML `<input type="file" capture="environment">` flow OOMs the
// WebView the moment the system camera intent returns with a 12 MP
// photo. Tried client-side downscale (still decodes the full bitmap)
// and native form submit (file still in memory when control returns).
// Both lose to the OS.
//
// This module captures the photo INSIDE the page via getUserMedia +
// canvas snapshot. We never leave the WebView, never receive a multi-
// megabyte File object from an external intent, and the captured
// frame is immediately re-encoded as a ~150 KB JPEG that lives just
// long enough to be POSTed.
//
// Usage from any page that wants the camera:
//     window.gystCamera.open({
//         postTo:      '/api/capture-upload',
//         extraFields: { room: 'kitchen', mode: 'objects' },
//         onSuccess:   (json) => { window.location.href = '...'; }
//     });

(function () {
    'use strict';
    try { console.log('[gyst-camera] build 20260514d loaded'); } catch (_) {}

    // When the page is opened with ?recent=<photo_id> in the URL,
    // Reflex's on_load is rendering the photo + items below via its
    // own <img src=/photo/...>. Our JS-managed blob preview img would
    // duplicate the same photo; clear it so the user sees one picture,
    // not two.
    function _hidePreviewIfRecent() {
        try {
            const sp = new URLSearchParams(window.location.search);
            if (!sp.has("recent")) return;
            const img = document.getElementById("capture-preview-img");
            if (img) {
                if (img.dataset.gystBlobUrl) {
                    try { URL.revokeObjectURL(img.dataset.gystBlobUrl); } catch (_) {}
                    delete img.dataset.gystBlobUrl;
                }
                img.src = "";
                img.style.display = "none";
            }
        } catch (_) {}
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", _hidePreviewIfRecent);
    } else {
        _hidePreviewIfRecent();
    }

    let overlay = null;
    let videoEl = null;
    let stream = null;
    let activeOpts = null;

    function _injectStyles() {
        if (document.getElementById('gyst-camera-styles')) return;
        const s = document.createElement('style');
        s.id = 'gyst-camera-styles';
        s.textContent = `
        .gyst-cam-overlay {
            position: fixed; inset: 0;
            background: #000;
            z-index: 99999;
            display: none;
            flex-direction: column;
            align-items: stretch;
            color: white;
            font-family: "Space Grotesk", system-ui, sans-serif;
        }
        .gyst-cam-overlay.open { display: flex; }
        .gyst-cam-video {
            flex: 1;
            width: 100%;
            object-fit: cover;
            background: #000;
            /* Mirror the front camera, not the rear */
        }
        .gyst-cam-status {
            padding: 0.8rem 1rem;
            text-align: center;
            font-size: 0.9rem;
            min-height: 1.2rem;
            background: rgba(0,0,0,0.6);
        }
        .gyst-cam-controls {
            display: flex;
            gap: 0.75rem;
            padding: 1.1rem 1rem calc(env(safe-area-inset-bottom, 0px) + 1.1rem);
            justify-content: space-between;
            background: rgba(0,0,0,0.85);
        }
        .gyst-cam-btn {
            flex: 1;
            border: 0;
            border-radius: 999px;
            padding: 0.85rem 1.2rem;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            min-height: 3rem;
        }
        .gyst-cam-btn-cancel { background: var(--gray-6, #555); color: white; }
        .gyst-cam-btn-flip   { background: var(--gray-7, #777); color: white; }
        .gyst-cam-btn-snap   {
            background: white; color: #111;
            font-weight: 700; font-size: 1.1rem;
            flex: 2;
        }
        .gyst-cam-btn:disabled { opacity: 0.4; }
        `;
        document.head.appendChild(s);
    }

    function _build() {
        if (overlay) return;
        _injectStyles();
        overlay = document.createElement('div');
        overlay.className = 'gyst-cam-overlay';
        overlay.id = 'gyst-cam-overlay';
        overlay.innerHTML = `
            <video class="gyst-cam-video" id="gyst-cam-video" autoplay playsinline muted></video>
            <div class="gyst-cam-status" id="gyst-cam-status">Starting camera…</div>
            <div class="gyst-cam-controls">
                <button class="gyst-cam-btn gyst-cam-btn-cancel" id="gyst-cam-cancel">Cancel</button>
                <button class="gyst-cam-btn gyst-cam-btn-flip"   id="gyst-cam-flip">Flip</button>
                <button class="gyst-cam-btn gyst-cam-btn-snap"   id="gyst-cam-snap" disabled>Snap</button>
            </div>
        `;
        document.body.appendChild(overlay);
        videoEl = overlay.querySelector('#gyst-cam-video');
        overlay.querySelector('#gyst-cam-cancel').addEventListener('click', _close);
        overlay.querySelector('#gyst-cam-flip').addEventListener('click', _flip);
        overlay.querySelector('#gyst-cam-snap').addEventListener('click', _snap);
    }

    function _setStatus(msg) {
        const el = overlay && overlay.querySelector('#gyst-cam-status');
        if (el) el.textContent = msg;
    }

    let facing = 'environment'; // rear camera by default

    async function _start() {
        _setStatus('Requesting camera…');
        const snapBtn = overlay.querySelector('#gyst-cam-snap');
        snapBtn.disabled = true;
        try {
            // Ask for a moderate resolution. We don't need 4K; 1280x960
            // gives plenty of detail for object recognition while
            // keeping the live preview cheap.
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: facing },
                    width:  { ideal: 1024 },
                    height: { ideal: 768 },
                },
                audio: false,
            });
            videoEl.srcObject = stream;
            await videoEl.play().catch(() => {});
            _setStatus('Tap Snap when ready');
            snapBtn.disabled = false;
        } catch (err) {
            _setStatus('Camera unavailable: ' + (err && err.message || err));
            // Surface details to the page status line too for visibility
            try {
                const pageStatus = document.getElementById('capture-handoff-status');
                if (pageStatus) {
                    pageStatus.textContent = 'Camera unavailable: ' + (err && err.message || err) + '. Use Gallery instead.';
                    pageStatus.style.opacity = '1';
                }
            } catch (_) {}
            // Auto-close after a beat so the user isn't stuck.
            setTimeout(_close, 2500);
        }
    }

    function _stop() {
        try {
            if (stream) {
                stream.getTracks().forEach((t) => { try { t.stop(); } catch (_) {} });
            }
        } catch (_) {}
        stream = null;
        if (videoEl) videoEl.srcObject = null;
    }

    function _close() {
        _stop();
        if (overlay) overlay.classList.remove('open');
        activeOpts = null;
    }

    async function _flip() {
        facing = (facing === 'environment') ? 'user' : 'environment';
        _stop();
        await _start();
    }

    async function _snap() {
        if (!videoEl || !videoEl.videoWidth) {
            _setStatus('Camera not ready yet');
            return;
        }
        const snapBtn = overlay.querySelector('#gyst-cam-snap');
        snapBtn.disabled = true;
        _setStatus('Capturing…');

        // Snapshot to a canvas at the video's native resolution. We
        // cap at 1920px longest side so the JPEG is small enough for
        // a low-memory upload — recognition models don't need more.
        const vw = videoEl.videoWidth, vh = videoEl.videoHeight;
        const longest = Math.max(vw, vh);
        const maxDim = 1024;
        let cw = vw, ch = vh;
        if (longest > maxDim) {
            const s = maxDim / longest;
            cw = Math.round(vw * s);
            ch = Math.round(vh * s);
        }
        const canvas = document.createElement('canvas');
        canvas.width = cw; canvas.height = ch;
        canvas.getContext('2d').drawImage(videoEl, 0, 0, cw, ch);

        // Free the camera right away — we have our frame.
        _stop();

        const blob = await new Promise((resolve) => {
            canvas.toBlob(resolve, 'image/jpeg', 0.85);
        });
        if (!blob) {
            _setStatus('Capture failed.');
            snapBtn.disabled = false;
            return;
        }
        // Close the overlay IMMEDIATELY now that we have the blob.
        // The user wants to see the captured photo on the main capture
        // page (not behind the camera UI) while recognition runs in
        // the background. Anything that needs to show progress from
        // here uses opts.setStatus / opts.onCaptured, which the page
        // wires to its own preview + status DOM.
        const opts = activeOpts || {};
        _close();
        const pageStatus = (msg) => {
            if (typeof opts.setStatus === 'function') {
                opts.setStatus(msg);
            }
        };
        if (typeof opts.onCaptured === 'function') {
            try { opts.onCaptured(blob); } catch (_) {}
        }
        pageStatus('Uploading ' + Math.round(blob.size / 1024) + ' KB…');

        const fd = new FormData();
        fd.append('file', blob, 'photo.jpg');
        const extras = opts.extraFields || {};
        for (const k in extras) {
            if (Object.prototype.hasOwnProperty.call(extras, k)) {
                fd.append(k, extras[k]);
            }
        }

        // Injection mode: hand the captured blob to an existing
        // rx.upload's hidden <input type=file>, so the Reflex upload
        // pipeline runs and handle_upload streams items dynamically.
        // Avoids the full page reload that the fetch path used to do.
        if (opts.injectIntoInputSelector) {
            try {
                const input = document.querySelector(opts.injectIntoInputSelector);
                if (!input) {
                    pageStatus('Internal: upload target missing.');
                    return;
                }
                const file = new File([blob], 'photo.jpg', { type: 'image/jpeg' });
                // FileList is read-only; DataTransfer is the standard
                // (and widely-supported) way to programmatically set it.
                const dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                // Capture-phase listeners (our FileReader instant-preview
                // hook + react-dropzone) both expect a bubbling change.
                input.dispatchEvent(new Event('change', { bubbles: true }));
                pageStatus('Uploading to recognizer…');
            } catch (err) {
                pageStatus('Capture handoff failed: ' + (err && err.message || err));
            }
            return;
        }

        try {
            const r = await fetch(opts.postTo || '/api/capture-upload', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Accept': 'application/json' },
                body: fd,
            });
            const j = await r.json().catch(() => ({}));
            if (!r.ok || !j.ok) {
                pageStatus('Upload failed: ' + (j.error || ('HTTP ' + r.status)));
                return;
            }
            pageStatus('Saved ' + (j.item_count || 0) + ' item(s) — loading…');
            if (typeof opts.onSuccess === 'function') {
                opts.onSuccess(j);
            } else {
                const u = new URL(window.location.href);
                if (j.photo_id) u.searchParams.set('recent', String(j.photo_id));
                window.location.href = u.toString();
            }
        } catch (err) {
            pageStatus('Upload error: ' + (err && err.message || err));
        }
    }

    function _readRoomFromPage() {
        try {
            const sel = document.querySelector(
                '.capture-room-select [data-radix-select-value], '
                + '[data-radix-select-value]'
            );
            if (sel && sel.textContent) {
                const t = sel.textContent.trim();
                if (t) return t;
            }
        } catch (_) {}
        return 'default';
    }
    function _readModeFromPage() {
        try {
            const active = document.querySelector('.mode-seg-btn.active');
            if (active && active.textContent
                && active.textContent.toLowerCase().indexOf('receipt') >= 0) {
                return 'receipt';
            }
        } catch (_) {}
        return 'objects';
    }

    window.gystCamera = {
        // Open the in-page camera. opts: { postTo, extraFields, onSuccess }
        open(opts) {
            _build();
            activeOpts = opts || {};
            overlay.classList.add('open');
            facing = 'environment';
            _start();
        },

        // Convenience: pulls room + mode from the current capture page
        // DOM, then opens the camera. The capture button's onclick wires
        // here.
        openForCapture() {
            // Clear any lingering preview / status from a previous
            // capture so the user sees a clean slate while the camera
            // is up and during the upload.
            try {
                const img = document.getElementById("capture-preview-img");
                if (img) {
                    if (img.dataset.gystBlobUrl) {
                        try { URL.revokeObjectURL(img.dataset.gystBlobUrl); } catch (_) {}
                        delete img.dataset.gystBlobUrl;
                    }
                    img.src = "";
                    img.style.display = "none";
                }
                const status = document.getElementById("capture-handoff-status");
                if (status) {
                    status.textContent = "";
                    status.style.opacity = "0";
                }
            } catch (_) {}
            // Inject the captured blob into the gallery rx.upload's
            // hidden file input. react-dropzone picks it up, fires
            // on_drop → InventoryCaptureState.handle_upload, which
            // immediately clears self.items + self.photo_url and
            // streams items as the LLM identifies them. The
            // FileReader instant-preview hook (bound by the page)
            // shows the captured frame underneath in the meantime.
            this.open({
                injectIntoInputSelector: '#cap-gallery-upload input[type=file]',
                setStatus: (msg) => {
                    try {
                        const el = document.getElementById('capture-handoff-status');
                        if (el) { el.textContent = msg; el.style.opacity = '1'; }
                    } catch (_) {}
                    try { console.log('[gyst-camera]', msg); } catch (_) {}
                },
            });
        },

        close: _close,
    };
})();
