// === GYST capture handler — build 20260513c ===
try { console.log('[gyst-capture] camera-capture.js build 20260513c loaded'); } catch (_) {}

// Reflex's rx.upload component doesn't expose the HTML `capture` attribute.
// We patch it on by hand and — critically — re-apply it RIGHT before any
// click on an upload zone, because Chrome on Android sometimes ignores
// the attribute when React rewrote it on a re-render between our patch
// and the user's tap.
//
// Two surfaces:
//   1. A passive MutationObserver tags every image-accepting <input> with
//      capture="environment".
//   2. window.gystOpenCamera(uploadId) — explicit entry point for a
//      "Take photo" button that:
//         - finds the upload's hidden <input>
//         - re-stamps capture="environment" immediately
//         - clicks it
//      That synchronous capture-attr-then-click sequence is what Chrome
//      Android actually honors.

(function () {
    const tagInputs = () => {
        document.querySelectorAll('input[type="file"]').forEach((inp) => {
            const accept = inp.getAttribute('accept') || '';
            if (accept.includes('image') && !inp.hasAttribute('capture')) {
                inp.setAttribute('capture', 'environment');
            }
        });
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', tagInputs);
    } else {
        tagInputs();
    }

    // Re-tag on any DOM change. Also catches React's attribute-only
    // mutations where a re-render strips `capture` off our input.
    const observer = new MutationObserver(tagInputs);
    observer.observe(document.body, {
        childList: true, subtree: true,
        attributes: true, attributeFilter: ['type', 'accept'],
    });

    // Defensive capture event: if the user is about to interact with an
    // image-accepting input, ensure capture is set FIRST. Phase: capture
    // (third arg true) so we run before the input's own click handler.
    const lastSet = new WeakSet();
    function ensureCapture(inp) {
        if (!inp || lastSet.has(inp)) return;
        const accept = inp.getAttribute('accept') || '';
        if (!accept.includes('image')) return;
        inp.setAttribute('capture', 'environment');
        lastSet.add(inp);
    }
    document.addEventListener('mousedown', (ev) => {
        const inp = ev.target.closest && ev.target.closest('input[type="file"]');
        if (inp) ensureCapture(inp);
    }, true);
    document.addEventListener('touchstart', (ev) => {
        const inp = ev.target.closest && ev.target.closest('input[type="file"]');
        if (inp) ensureCapture(inp);
    }, true);

    // The capture-upload dropzone has a clickable WRAPPER, not a directly-
    // clickable <input>. When the wrapper is clicked, react-dropzone
    // synchronously invokes the input's .click() — but only AFTER our
    // listeners on the input itself have already fired. So we also stamp
    // capture on the dropzone's inner input as soon as a click/tap lands
    // anywhere inside #capture_upload. Running in the capture phase (third
    // arg true) ensures we beat react-dropzone's own handler.
    function stampCaptureOnDropzone(ev) {
        const root = ev.target && ev.target.closest && ev.target.closest('#capture_upload');
        if (!root) return;
        const inp = root.querySelector('input[type="file"]');
        if (inp) {
            inp.setAttribute('capture', 'environment');
            try { inp.capture = 'environment'; } catch (_) {}
        }
    }
    document.addEventListener('mousedown', stampCaptureOnDropzone, true);
    document.addEventListener('touchstart', stampCaptureOnDropzone, true);
    document.addEventListener('click', stampCaptureOnDropzone, true);

    /**
     * Internal: pick a file via a disposable native input. Setting the
     * attributes at creation time (before insertion) guarantees Chrome
     * honors `capture` — there's no React re-render to overwrite it.
     * On success, transfers the File into the rx.upload's hidden input
     * via DataTransfer and dispatches a 'change' event so react-dropzone
     * picks it up and Reflex's on_drop handler fires.
     */
    function _pickAndForward(targetUploadId, useCamera) {
        const root = document.getElementById(targetUploadId);
        const target = root && root.querySelector('input[type="file"]');
        if (!target) {
            alert('Upload widget not found. Reload the page.');
            return;
        }
        const picker = document.createElement('input');
        picker.type = 'file';
        picker.accept = 'image/*';
        if (useCamera) {
            picker.setAttribute('capture', 'environment');
            try { picker.capture = 'environment'; } catch (_) {}
        }
        picker.style.position = 'fixed';
        picker.style.left = '-9999px';
        picker.style.opacity = '0';
        picker.style.pointerEvents = 'none';
        picker.addEventListener('change', () => {
            const file = picker.files && picker.files[0];
            picker.remove();
            if (!file) return;
            try {
                const dt = new DataTransfer();
                dt.items.add(file);
                target.files = dt.files;
                target.dispatchEvent(new Event('change', { bubbles: true }));
            } catch (e) {
                alert('Couldn\'t hand the photo over: ' + e.message);
            }
        }, { once: true });
        document.body.appendChild(picker);
        picker.click();
    }

    window.gystOpenCamera  = (uploadId) => _pickAndForward(uploadId, true);
    window.gystOpenGallery = (uploadId) => _pickAndForward(uploadId, false);

    /**
     * Forward a file picked via the native <label>-driven inputs (with
     * id="gyst-cam-input" / "gyst-gal-input") to /api/capture-upload.
     *
     * Why POST instead of DataTransfer into rx.upload's hidden input:
     * we need the camera to actually open (Chrome only honors the
     * `capture` attribute when the click goes through a real
     * label→input gesture), AND we need the file to reliably reach
     * the server. React-dropzone's controlled-input layer drops
     * synthetic change events in inconsistent ways; the POST path
     * just bypasses it. After upload the page reloads with
     * ?recent=<photo_id> and the capture state rehydrates the summary
     * from the items table on on_load.
     */
    function _say(msg) {
        try {
            const el = document.getElementById('capture-handoff-status');
            if (el) {
                el.textContent = msg;
                el.style.opacity = '1';
            }
        } catch (_) {}
        try { console.log('[gyst-capture]', msg); } catch (_) {}
    }
    function _readCurrentRoom() {
        // Pull the active room from the Radix select trigger on the
        // page, so we don't have to round-trip through Reflex state.
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
    function _readCurrentMode() {
        try {
            const active = document.querySelector('.mode-seg-btn.active');
            if (active && active.textContent
                && active.textContent.toLowerCase().indexOf('receipt') >= 0) {
                return 'receipt';
            }
        } catch (_) {}
        return 'objects';
    }
    // Tiny helper retained for completeness, but it's NOT in the click
    // path any more — see _handleCapturedFile below. Pre-encoded images
    // can use this if we ever want client-side compression, but the
    // default path now hands the file straight to the browser's native
    // form submitter (zero-JS upload).
    async function _downscaleImage(file, maxDim, quality) {
        maxDim = maxDim || 1920;
        quality = quality || 0.85;
        if (!file || !file.type || file.type.indexOf('image/') !== 0) {
            return file;
        }
        // Tiny photos don't need compression — preserves quality for
        // close-up object recognition on already-low-res cameras.
        if (file.size < 1024 * 1024) return file;
        if (typeof createImageBitmap !== 'function') return file;

        let bitmap;
        try {
            bitmap = await createImageBitmap(file, {
                imageOrientation: 'from-image',
            });
        } catch (_) {
            // Some platforms reject the second-arg options bag; retry plain.
            try { bitmap = await createImageBitmap(file); }
            catch (_) { return file; }
        }
        try {
            let w = bitmap.width, h = bitmap.height;
            const longest = Math.max(w, h);
            if (longest > maxDim) {
                const scale = maxDim / longest;
                w = Math.round(w * scale);
                h = Math.round(h * scale);
            }
            const canvas = document.createElement('canvas');
            canvas.width = w; canvas.height = h;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(bitmap, 0, 0, w, h);
            const blob = await new Promise((resolve) => {
                canvas.toBlob(resolve, 'image/jpeg', quality);
            });
            return blob || file;
        } finally {
            try { bitmap.close && bitmap.close(); } catch (_) {}
        }
    }

    function _handleCapturedFile(src, file) {
        // Native form submit: the browser handles the upload itself,
        // streaming the file from disk straight to the network. No
        // FormData buffering, no decode, no fetch. Survives Android
        // Chrome's tight PWA WebView memory budget.
        if (!file) {
            _say('No photo selected.');
            return;
        }
        const form = document.getElementById('capture-form');
        if (!form) {
            _say('Capture form not on this page.');
            return;
        }
        // Sync hidden fields from current page state.
        try {
            const roomEl = document.getElementById('cap-room-hidden');
            if (roomEl) roomEl.value = _readCurrentRoom();
            const modeEl = document.getElementById('cap-mode-hidden');
            if (modeEl) modeEl.value = _readCurrentMode();
        } catch (_) {}

        _say('Uploading ' + Math.round(file.size / 1024) + ' KB photo…');
        // Submit. The browser navigates to the form's action URL with
        // the multipart body; on success the server 303s back to
        // /inventory/capture?recent=<photo_id> and on_load shows the
        // recognized items.
        try {
            form.submit();
        } catch (e) {
            _say('Submit failed: ' + (e && e.message || e));
        }
    }

    // Wire two ways into the same handler so we catch the file pick
    // no matter how the input event propagates:
    //
    //   1) Direct listener bound the first time we see #gyst-cam-input
    //      in the DOM. This is the most reliable path.
    //   2) Delegated listener on document for `[data-gyst-source]`
    //      inputs. Fires for any matching input even if it's mounted
    //      later or replaced by a React re-render.
    function _wireDirect() {
        const inp = document.getElementById('gyst-cam-input');
        if (inp && !inp.__gystWired) {
            inp.__gystWired = true;
            inp.addEventListener('change', () => {
                const f = inp.files && inp.files[0];
                _say('Direct change fired — file=' + (f ? Math.round(f.size/1024)+'KB' : 'none'));
                _handleCapturedFile(inp, f);
            });
            try { console.log('[gyst-capture] direct-wired #gyst-cam-input'); } catch (_) {}
        }
        const ig = document.getElementById('gyst-gal-input');
        if (ig && !ig.__gystWired) {
            ig.__gystWired = true;
            ig.addEventListener('change', () => {
                const f = ig.files && ig.files[0];
                _handleCapturedFile(ig, f);
            });
        }
    }
    // Sweep on mount + on every DOM mutation (React may remount the
    // input after a state update).
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _wireDirect);
    } else {
        _wireDirect();
    }
    new MutationObserver(_wireDirect).observe(document.body || document.documentElement, {
        childList: true, subtree: true,
    });

    // Delegated fallback.
    document.addEventListener('change', (ev) => {
        const src = ev.target;
        if (!src || src.tagName !== 'INPUT' || src.type !== 'file') return;
        const which = src.getAttribute('data-gyst-source');
        if (which !== 'camera' && which !== 'gallery') return;
        // If the direct listener already handled it (set _gystHandled
        // on the input), bail to avoid double-fetch.
        if (src.__gystHandling) return;
        src.__gystHandling = true;
        setTimeout(() => { src.__gystHandling = false; }, 5000);
        const file = src.files && src.files[0];
        _say('Delegated change fired — file=' + (file ? Math.round(file.size/1024)+'KB' : 'none'));
        _handleCapturedFile(src, file);
    });
})();
