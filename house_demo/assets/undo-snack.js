/* Auto-fade the undo snack ~0.5s after each arm, with full dismissal
 * by ~3s. Pauses on hover/touch and restarts on leave.
 *
 * Why this lives outside the snack's render tree: React doesn't
 * re-execute <script> tags rendered as JSX children. The snack stays
 * mounted (id="undo-snack") across consecutive UndoState arms — only
 * its data-seq attribute and label change. So an inline timer started
 * inside the first render is the only timer that would ever run.
 *
 * We use a MutationObserver on the body to detect any change to the
 * #undo-snack element (or its data-seq attribute), and (re)start the
 * fade cycle each time the seq value moves.
 */
(function () {
    let activeSeq = null;
    let fadeStartTimer = null;
    let dismissTimer = null;
    let paused = false;
    let listenersBoundFor = null;

    const FADE_START_MS = 500;   // briefly visible at full opacity
    const TOTAL_MS = 1500;       // dismissed entirely by this point

    function fireDismiss() {
        const btn = document.getElementById('undo-dismiss');
        if (btn) btn.click();
    }

    function clearTimers() {
        if (fadeStartTimer) { clearTimeout(fadeStartTimer); fadeStartTimer = null; }
        if (dismissTimer)   { clearTimeout(dismissTimer);   dismissTimer   = null; }
    }

    function snapToFull(snack) {
        // Cancel an in-progress CSS fade and snap back to opaque.
        if (!snack) return;
        snack.classList.remove('fading');
        // Inline opacity overrides the .fading class's opacity:0 mid-transition.
        snack.style.opacity = '1';
    }

    function startFade(snack) {
        if (!snack) return;
        // Clear inline opacity so the .fading class's CSS animation kicks in.
        snack.style.opacity = '';
        snack.classList.add('fading');
    }

    function scheduleFade(seq) {
        if (seq === activeSeq) return;
        activeSeq = seq;
        clearTimers();
        const snack = document.getElementById('undo-snack');
        snapToFull(snack);
        if (paused) return; // hovering — wait for resume
        fadeStartTimer = setTimeout(() => {
            const s = document.getElementById('undo-snack');
            startFade(s);
        }, FADE_START_MS);
        dismissTimer = setTimeout(fireDismiss, TOTAL_MS);
    }

    function bindHoverListeners(snack) {
        if (!snack || listenersBoundFor === snack) return;
        listenersBoundFor = snack;
        const pause = () => {
            paused = true;
            clearTimers();
            snapToFull(snack);
        };
        const resume = () => {
            paused = false;
            clearTimers();
            // Re-arm a fresh fade cycle on resume.
            snapToFull(snack);
            fadeStartTimer = setTimeout(() => {
                const s = document.getElementById('undo-snack');
                startFade(s);
            }, FADE_START_MS);
            dismissTimer = setTimeout(fireDismiss, TOTAL_MS);
        };
        snack.addEventListener('mouseenter', pause);
        snack.addEventListener('touchstart', pause, { passive: true });
        snack.addEventListener('mouseleave', resume);
        snack.addEventListener('touchend', resume);
        snack.addEventListener('touchcancel', resume);
    }

    function check() {
        const snack = document.getElementById('undo-snack');
        if (!snack) {
            clearTimers();
            activeSeq = null;
            paused = false;
            listenersBoundFor = null;
            return;
        }
        bindHoverListeners(snack);
        const seq = snack.getAttribute('data-seq') || '';
        if (!seq) return;
        scheduleFade(seq);
    }

    const observer = new MutationObserver(check);
    if (document.body) {
        observer.observe(document.body, {
            childList: true, subtree: true,
            attributes: true, attributeFilter: ['data-seq'],
        });
        check();
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.body, {
                childList: true, subtree: true,
                attributes: true, attributeFilter: ['data-seq'],
            });
            check();
        });
    }
})();
