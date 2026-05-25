/* GYST voice input — uses the browser's built-in Web Speech API (no
 * server round trip, no API cost). Available on Chrome/Edge/Safari.
 *
 * Exposes window.gystVoice.{start, stop}. The Add-items page wires a
 * mic button to start() with a callback that receives the transcript.
 */
(function () {
  let recog = null;

  function makeRecognizer() {
    const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Rec) return null;
    const r = new Rec();
    r.lang = navigator.language || "en-US";
    r.interimResults = false;
    r.maxAlternatives = 1;
    r.continuous = false;
    return r;
  }

  /**
   * Speak into an existing form field. Appends the transcript to whatever
   * is already in the field and fires an 'input' event so React picks up
   * the change.
   *   selector: CSS selector for a <textarea> or <input>
   *   onStatus: optional callback for transient status text
   */
  /**
   * Resolve a "text-like" element. Radix Themes wraps <textarea> and
   * <input> in a root <div> that may carry the id we passed from Python,
   * so we first try the literal selector, then look for a textarea/input
   * descendant.
   */
  function _resolveField(selector) {
    const direct = document.querySelector(selector);
    if (!direct) return null;
    if (direct.tagName === "TEXTAREA" || direct.tagName === "INPUT") {
      return direct;
    }
    return direct.querySelector("textarea, input");
  }

  function _setStatus(selector, msg) {
    // Mic button gets a "listening" class so CSS can pulse it.
    const btn = document.querySelector(selector + "-mic");
    if (btn) {
      if (msg && msg.startsWith("Listening")) btn.classList.add("listening");
      else btn.classList.remove("listening");
    }
    const s = document.querySelector(selector + "-status");
    if (s) s.textContent = msg || "";
  }

  window.gystSpeakInto = (selector, statusSelector) => {
    if (!window.gystVoice) {
      alert("Voice input isn't loaded.");
      return;
    }
    const tag = statusSelector || selector;
    if (!window.gystVoice.isSupported()) {
      _setStatus(tag, "Voice input isn't supported in this browser.");
      alert(
        "This browser doesn't support voice input. " +
        "Try Chrome on Android, Edge, or Safari."
      );
      return;
    }
    window.gystVoice.start(
      (text) => {
        const el = _resolveField(selector);
        if (!el) {
          _setStatus(tag, "Couldn't find the text field.");
          return;
        }
        const sep = el.value && !el.value.endsWith(" ") ? " " : "";
        el.value = el.value + sep + text;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.focus();
        _setStatus(tag, "");
      },
      (msg) => _setStatus(tag, msg)
    );
  };

  /* ----- Hold-to-talk for the JARVIS chat input ----------------------
   * Bound to mousedown/touchstart (start) and mouseup/leave/touchend
   * (stop) on the chat mic button. Appends the final transcript to
   * whatever the user has already typed, then focuses the input. Does
   * NOT auto-submit — user reviews and hits send themselves.
   */
  let _chatMicActive = false;

  function _chatStatus(msg) {
    const btn = document.querySelector("#chat-input-mic");
    if (btn) {
      if (msg && msg.startsWith("Listening")) btn.classList.add("listening", "recording");
      else btn.classList.remove("listening", "recording");
    }
    const s = document.querySelector("#chat-input-status");
    if (s) s.textContent = msg || "";
  }

  window.gystChatMicStart = () => {
    if (_chatMicActive) return;
    if (!window.gystVoice || !window.gystVoice.isSupported()) {
      _chatStatus("Voice input isn't supported in this browser.");
      return;
    }
    _chatMicActive = true;
    window.gystVoice.start(
      (text) => {
        const el = _resolveField("#chat-input");
        if (!el) {
          _chatStatus("Couldn't find the chat input.");
          return;
        }
        const sep = el.value && !el.value.endsWith(" ") ? " " : "";
        el.value = el.value + sep + text;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.focus();
        _chatStatus("");
      },
      (msg) => _chatStatus(msg)
    );
  };

  window.gystChatMicStop = () => {
    if (!_chatMicActive) return;
    _chatMicActive = false;
    try { window.gystVoice.stop(); } catch {}
    // Recognizer fires onresult asynchronously; clear the visual cue now.
    const btn = document.querySelector("#chat-input-mic");
    if (btn) btn.classList.remove("listening", "recording");
  };

  window.gystVoice = {
    isSupported() {
      return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
    },
    start(onResult, onStatus) {
      if (recog) return;
      recog = makeRecognizer();
      if (!recog) {
        if (onStatus) onStatus("Voice input isn't supported in this browser.");
        return;
      }
      // Interim results give the user instant feedback ("Listening…"
      // → partial transcript) and reveal whether audio is being
      // captured at all. Some Android PWA shells never fire the final
      // result but stream interims fine.
      recog.interimResults = true;
      const status = (m) => {
        if (onStatus) onStatus(m);
      };
      let _emitted = false;
      recog.onstart = () => status("Listening…");
      recog.onerror = (ev) => {
        // Common ev.error codes:
        //   not-allowed         user denied mic permission (or no HTTPS)
        //   service-not-allowed PWA shell blocks Web Speech
        //   audio-capture       no mic hardware / busy
        //   no-speech           recognizer heard nothing
        //   network             cloud recognizer (Chrome) couldn't reach Google
        //   aborted             stop() called before any speech
        status("ERR:" + (ev.error || "unknown"));
        recog = null;
      };
      recog.onend = () => {
        if (!_emitted) status("ENDNORESULT");
        recog = null;
      };
      recog.onresult = (ev) => {
        let finalText = '';
        let interimText = '';
        for (let i = 0; i < ev.results.length; i++) {
          const r = ev.results[i];
          if (r.isFinal) finalText += r[0].transcript;
          else interimText += r[0].transcript;
        }
        if (interimText) status("INTERIM:" + interimText.trim());
        if (finalText && finalText.trim()) {
          _emitted = true;
          status("Heard: " + finalText.trim());
          if (onResult) onResult(finalText.trim());
        }
      };
      try { recog.start(); }
      catch (e) { status("Couldn't start: " + (e.message || e)); recog = null; }
    },
    stop() {
      try { if (recog) recog.stop(); } catch {}
    },
  };
})();

/* ----- Omnibox hold-to-talk ---------------------------------------
 * Same shape as the chat mic above, but binds to #omnibox-input /
 * #omnibox-mic. Used by the global floating JARVIS omnibox rendered
 * in layout.py.
 */
let _omniMicActive = false;

function _omniStatus(msg) {
  const btn = document.querySelector('#omnibox-mic');
  if (btn) {
    if (msg && msg.startsWith('Listening')) btn.classList.add('listening', 'recording');
    else btn.classList.remove('listening', 'recording');
  }
}

window.gystOmniMicStart = () => {
  if (_omniMicActive) return;
  if (!window.gystVoice || !window.gystVoice.isSupported()) {
    _omniStatus("Voice input isn't supported in this browser.");
    return;
  }
  _omniMicActive = true;
  // Snapshot pre-existing text so we can tell whether the recognized
  // transcript is the entirety of the message (auto-submit candidate)
  // or appended to something the user typed manually (don't auto-send
  // — they might still be editing).
  let _omniPriorText = '';
  try {
    const root0 = document.querySelector('#omnibox-input');
    const el0 = !root0 ? null : (root0.tagName === 'TEXTAREA' || root0.tagName === 'INPUT') ? root0 : root0.querySelector('textarea, input');
    if (el0) _omniPriorText = el0.value || '';
  } catch (_) {}

  window.gystVoice.start(
    (text) => {
      const root = document.querySelector('#omnibox-input');
      const el = !root ? null : (root.tagName === 'TEXTAREA' || root.tagName === 'INPUT') ? root : root.querySelector('textarea, input');
      if (!el) return;
      const sep = el.value && !el.value.endsWith(' ') ? ' ' : '';
      // Use the React-native value setter so onChange fires reliably
      // and Reflex's state.query stays in sync — without this, a
      // direct assignment can silently bypass React's controlled-
      // input bookkeeping and leave the backend with stale text.
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
      ).set || Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
      ).set;
      const newVal = el.value + sep + text;
      try { setter.call(el, newVal); } catch (_) { el.value = newVal; }
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.focus();
      _omniStatus('');

      // Walkie-talkie auto-submit: if the field was empty before the
      // user held the mic, treat this transcript as the complete
      // message and send it. Wait ~180ms so Reflex's set_query
      // WS round-trip lands before the form submit reads state.query.
      const trimmedPrior = (_omniPriorText || '').trim();
      const trimmedNew = (text || '').trim();
      if (trimmedPrior === '' && trimmedNew !== '') {
        setTimeout(() => {
          try {
            const sendBtn = document.querySelector(
              '#omnibox-root button[type="submit"]'
            );
            if (sendBtn && !sendBtn.disabled) sendBtn.click();
          } catch (_) {}
        }, 180);
      }
    },
    (msg) => _omniStatus(msg)
  );
};

window.gystOmniMicStop = () => {
  if (!_omniMicActive) return;
  _omniMicActive = false;
  try { window.gystVoice.stop(); } catch {}
  const btn = document.querySelector('#omnibox-mic');
  if (btn) btn.classList.remove('listening', 'recording');
};

/* On load, hide the mic button if Web Speech isn't supported. The
 * button is rendered by Reflex regardless; we just toggle a class
 * the CSS keys off of. */
(function _hideOmniMicIfUnsupported() {
  function check() {
    if (!window.gystVoice || !window.gystVoice.isSupported()) {
      document.documentElement.classList.add('no-voice-support');
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', check);
  } else {
    check();
  }
})();




function _showOmniMicStatus(text, autoHideMs) {
  // Floating status banner anchored to the omnibox root. Created on
  // first use and reused thereafter. autoHideMs=0 means keep showing
  // (used for interim transcripts). Default 3500ms.
  let el = document.getElementById('omnibox-mic-status');
  if (!el) {
    el = document.createElement('div');
    el.id = 'omnibox-mic-status';
    el.className = 'omnibox-mic-status';
    const root = document.getElementById('omnibox-root') || document.body;
    root.appendChild(el);
  }
  el.textContent = text || '';
  el.style.opacity = text ? '1' : '0';
  if (el._hideT) { clearTimeout(el._hideT); el._hideT = null; }
  const hide = (autoHideMs === undefined) ? 3500 : autoHideMs;
  if (hide > 0 && text) {
    el._hideT = setTimeout(() => { el.style.opacity = '0'; }, hide);
  }
}

/* ----- Omnibox mic tap-to-toggle binding ---------------------------
 * Hold-to-talk worked for mouse but flaked on Android Chrome (mouse
 * events synthesized post-touchend; pointerdown sometimes never
 * reaches the button). Tap-to-toggle has a single reliable gesture
 * (click), the same on every platform.
 *
 * Tap 1: start recording, .recording class pulses the button.
 * Tap 2 (or recognizer auto-end): stop. If the input was empty
 *   before, auto-submit.
 *
 * MutationObserver re-binds the listener across Reflex re-renders.
 * Idempotent via dataset.gystToggleBound.
 */
(function () {
  let recording = false;
  let priorText = '';

  function _getInputEl() {
    const root = document.querySelector('#omnibox-input');
    if (!root) return null;
    if (root.tagName === 'TEXTAREA' || root.tagName === 'INPUT') return root;
    return root.querySelector('textarea, input');
  }

  function _setBtnState(btn, on) {
    if (!btn) return;
    if (on) btn.classList.add('recording', 'listening');
    else btn.classList.remove('recording', 'listening');
  }

  async function start(btn) {
    if (recording) return;
    if (!window.gystVoice || !window.gystVoice.isSupported()) {
      try {
        alert("Voice input isn't available in this browser. "
              + "If you're in the installed app, open the same page in Chrome instead.");
      } catch (_) {}
      return;
    }
    const el = _getInputEl();
    priorText = el ? (el.value || '') : '';
    recording = true;
    _setBtnState(btn, true);

    // Pre-flight: ask the OS for mic permission via getUserMedia.
    // Installed Android PWAs don't show the padlock, so without
    // this the SpeechRecognition.start() call silently fires the
    // 'not-allowed' error with no chance to grant. getUserMedia
    // triggers the native Android permission sheet.
    try {
      _showOmniMicStatus('Requesting microphone…', 0);
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // We only wanted the permission, not the audio stream itself —
      // SpeechRecognition opens its own internal capture. Close the
      // tracks so we don't leave the mic indicator on.
      try { stream.getTracks().forEach((t) => t.stop()); } catch (_) {}
    } catch (err) {
      recording = false;
      _setBtnState(btn, false);
      const name = (err && err.name) || '';
      let msg = 'Microphone error: ' + (err && err.message || name || 'unknown');
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        // The padlock guidance only works in a normal browser tab.
        // For the installed PWA case, point at Android settings.
        msg = (
          'Microphone permission denied. '
          + 'In the installed app: long-press the icon → App info → '
          + 'Permissions → Microphone → Allow. '
          + 'In a Chrome tab: tap the padlock in the URL bar.'
        );
      } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        msg = 'No microphone available on this device.';
      } else if (name === 'NotReadableError') {
        msg = 'Microphone is in use by another app — close it and try again.';
      }
      _showOmniMicStatus(msg, 9000);
      return;
    }

    window.gystVoice.start(
      (text) => {
        // Final transcript arrived.
        const el2 = _getInputEl();
        if (el2 && text) {
          const sep = el2.value && !el2.value.endsWith(' ') ? ' ' : '';
          const newVal = el2.value + sep + text;
          // React-native setter so Reflex's state stays in sync.
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
          ).set || Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, 'value'
          ).set;
          try { setter.call(el2, newVal); } catch (_) { el2.value = newVal; }
          el2.dispatchEvent(new Event('input', { bubbles: true }));
          el2.focus();
        }
        recording = false;
        _setBtnState(btn, false);
        _showOmniMicStatus('Heard: ' + text);

        // Auto-submit if the field was empty before this take.
        if ((priorText || '').trim() === '' && (text || '').trim() !== '') {
          // Flag this turn as voice-originated so the TTS auto-restart
          // (in the speak-replies block below) knows it can reopen
          // the mic after the reply finishes — closing the loop.
          try { window.__gystLastWasVoice = true; } catch (_) {}
          setTimeout(() => {
            try {
              const sendBtn = document.querySelector(
                '#omnibox-root button[type="submit"]'
              );
              if (sendBtn && !sendBtn.disabled) sendBtn.click();
            } catch (_) {}
          }, 200);
        }
      },
      (msg) => {
        // Tagged status messages from the recognizer. ERR: prefix
        // means a real failure -- surface it so the user knows the
        // mic stopped (otherwise the button looked stuck recording).
        if (typeof msg !== 'string') return;
        if (msg.startsWith('ERR:')) {
          const code = msg.slice(4);
          recording = false;
          _setBtnState(btn, false);
          let human = 'Voice error: ' + code;
          if (code === 'not-allowed') {
            human = ('Microphone permission denied. In the installed app: long-press the icon → App info → Permissions → Microphone → Allow. In a Chrome tab: tap the padlock in the URL bar.');
          } else if (code === 'service-not-allowed') {
            human = 'This installed app shell blocks voice. Open in regular Chrome.';
          } else if (code === 'audio-capture') {
            human = 'No microphone available.';
          } else if (code === 'no-speech') {
            human = 'Didn\'t hear anything. Try again.';
          } else if (code === 'network') {
            human = 'Voice service unreachable. Check your connection.';
          } else if (code === 'aborted') {
            human = '';  // user-initiated stop; no message needed
          }
          if (human) _showOmniMicStatus(human, 5000);
        } else if (msg === 'ENDNORESULT') {
          // Recognizer ended with no final or interim transcript.
          recording = false;
          _setBtnState(btn, false);
          _showOmniMicStatus('No speech detected — try again.', 3500);
        } else if (msg.startsWith('INTERIM:')) {
          _showOmniMicStatus('… ' + msg.slice(8), 0);
        } else if (msg === 'Listening…') {
          _showOmniMicStatus('Listening…', 0);
        }
      }
    );
  }

  function stop(btn) {
    if (!recording) return;
    recording = false;
    _setBtnState(btn, false);
    try { window.gystVoice.stop(); } catch (_) {}
  }

  function bind(btn) {
    if (!btn || btn.dataset.gystToggleBound === '1') return;
    btn.dataset.gystToggleBound = '1';
    btn.addEventListener('click', (e) => {
      // No preventDefault — let click bubble for Reflex's button
      // tracking. We only need the tap signal.
      if (recording) {
        stop(btn);
      } else {
        start(btn);
      }
    });
    // Belt-and-suspenders: if the browser fires pointerup without a
    // following click (rare, but happens on some Android keyboards
    // that grab focus), treat that as a tap too.
    let pdt = 0;
    btn.addEventListener('pointerdown', () => { pdt = Date.now(); });
    btn.addEventListener('pointerup', () => {
      const dt = Date.now() - pdt;
      if (dt > 0 && dt < 500) {
        // Click should fire shortly; if it doesn't within 200ms, we'll
        // never know — but the click handler above usually wins.
      }
    });
  }

  function tryBind() {
    const btn = document.getElementById('omnibox-mic');
    if (btn) bind(btn);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tryBind);
  } else {
    tryBind();
  }

  const mo = new MutationObserver(() => tryBind());
  try {
    mo.observe(document.body, { childList: true, subtree: true });
  } catch (_) {
    document.addEventListener('DOMContentLoaded', () => {
      mo.observe(document.body, { childList: true, subtree: true });
      tryBind();
    });
  }
})();


/* ----- TTS: speak Jarvis replies + close the conversation loop -----
 * Lifecycle:
 *   1. User taps the speaker icon next to the mic. We toggle its
 *      data-on attribute and persist to localStorage.
 *   2. On every render of the omnibox reply div (id=omnibox-reply-text),
 *      a MutationObserver fires. If data-on=1 AND the text changed,
 *      we hand it to window.speechSynthesis.
 *   3. utterance.onend: if the speak-replies button is on AND the
 *      most recent submit came from voice (window.__gystLastWasVoice),
 *      auto-restart listening — closing the loop into a real
 *      back-and-forth.
 */
(function () {
  const TTS_KEY = 'gyst.speakReplies';
  let _lastSpoken = '';

  function setSpeakState(btn, on) {
    if (!btn) return;
    btn.dataset.on = on ? '1' : '0';
    btn.classList.toggle('active', !!on);
    try { localStorage.setItem(TTS_KEY, on ? '1' : '0'); } catch (_) {}
  }

  function isSpeakOn() {
    const btn = document.getElementById('omnibox-speak');
    return !!(btn && btn.dataset.on === '1');
  }

  function bindSpeakBtn() {
    const btn = document.getElementById('omnibox-speak');
    if (!btn || btn.dataset.gystSpeakBound === '1') return;
    btn.dataset.gystSpeakBound = '1';
    let initial = '0';
    try { initial = localStorage.getItem(TTS_KEY) || '0'; } catch (_) {}
    setSpeakState(btn, initial === '1');
    btn.addEventListener('click', () => {
      const on = btn.dataset.on === '1';
      setSpeakState(btn, !on);
      if (!on) {
        // Test cue so the user knows TTS is wired and unblocked.
        _speak('Voice on.');
      } else {
        try { window.speechSynthesis.cancel(); } catch (_) {}
      }
    });
  }

  function _speak(text) {
    if (!text || !('speechSynthesis' in window)) return;
    try { window.speechSynthesis.cancel(); } catch (_) {}
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.05;
    u.pitch = 1.0;
    u.lang = navigator.language || 'en-US';
    u.onend = () => {
      // Conversation loop: if the user spoke this turn and TTS is on,
      // auto-restart listening so they can reply hands-free.
      if (isSpeakOn() && window.__gystLastWasVoice) {
        window.__gystLastWasVoice = false;
        const micBtn = document.getElementById('omnibox-mic');
        if (micBtn) {
          // Small delay so SpeechRecognition releases internal state
          // from the prior turn before we start the next one.
          setTimeout(() => { try { micBtn.click(); } catch (_) {} }, 300);
        }
      }
    };
    try { window.speechSynthesis.speak(u); } catch (_) {}
  }

  function watchReply() {
    const div = document.getElementById('omnibox-reply-text');
    if (!div) return;
    const text = (div.textContent || '').trim();
    if (!text || text === _lastSpoken) return;
    _lastSpoken = text;
    if (isSpeakOn()) _speak(text);
  }

  function tick() {
    bindSpeakBtn();
    watchReply();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tick);
  } else {
    tick();
  }

  const mo = new MutationObserver(tick);
  try {
    mo.observe(document.body, { childList: true, subtree: true, characterData: true });
  } catch (_) {
    document.addEventListener('DOMContentLoaded', () => {
      mo.observe(document.body, { childList: true, subtree: true, characterData: true });
      tick();
    });
  }
})();
