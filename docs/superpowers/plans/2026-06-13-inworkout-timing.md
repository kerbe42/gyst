# In-Workout Timing (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rest timers, rep-tempo cues, and a work-block stopwatch to the workout screen of both the standalone Strongman PWA and GYST, so the app actively times the user through each set.

**Architecture:** Pure parsing logic (`parseRestSeconds`, `parseTempo`) lives in the engine, is TDD'd in TypeScript, and is ported to Python for parity. All live ticking + audio is **client-side**: the React app uses a `RestTimer`/`TempoCue` component (`setInterval` + Web Audio); GYST ships a self-contained vanilla-JS custom element (`<gyst-timer>`) as a static asset (same pattern as the existing `voice.js`/`barcode.js`) rendered via `rx.html`, so the Reflex server never ticks.

**Tech Stack:** Vite + React + TypeScript + vitest (standalone); Reflex 0.9 / Python + a hand-rolled test harness (GYST); Web Audio API for beeps; vanilla JS Custom Elements for GYST.

**Spec:** `docs/superpowers/specs/2026-06-13-gyst-life-coach-design.md` §4.1

---

## File structure

**Standalone — `C:\Users\white\repos\strongman-rebuild`**
- Create `src/engine/timing.ts` — `parseRestSeconds`, `parseTempo` (pure).
- Create `src/engine/timing.test.ts` — tests for both.
- Modify `src/engine/index.ts` — re-export timing.
- Modify `src/engine/types.ts` — add `tempo?: string` to `SessionItem`.
- Modify `data/plan_config.json` — add `tempo` to `rep_schemes.mains` entries.
- Modify `src/engine/sessions.ts` — carry `tempo` onto built items.
- Create `src/components/RestTimer.tsx` — countdown component (client-side).
- Create `src/components/TempoCue.tsx` — per-rep metronome component.
- Modify `src/components/ExerciseCard.tsx` — auto-start rest on log; tempo button; work stopwatch for carries.

**GYST — `C:\Users\white\repos\gyst`**
- Create `strongman/timing.py` — `parse_rest_seconds`, `parse_tempo` (parity).
- Modify `strongman/tests/test_engine.py` — parity tests.
- Modify `strongman/seed/plan_config.json` — add `tempo` to `rep_schemes.mains`.
- Modify `strongman/sessions.py` — carry `tempo` onto built items.
- Create `house_demo/assets/strongman-timer.js` — `<gyst-timer>` custom element.
- Modify `house_demo/house_demo/house_demo.py` — load `strongman-timer.js` in head; bump `?v`.
- Modify `house_demo/house_demo/strongman_state.py` — add `rest_label`, `rest_seconds`, `tempo` to `ItemRow` + `_item_row`.
- Modify `house_demo/house_demo/strongman_pages.py` — render `<gyst-timer>` on each exercise card.
- Modify `house_demo/assets/sw.js`, `house_demo/assets/pwa-register.js`, `house_demo/house_demo/layout.py` — bump `BUILD_VERSION` 20260612e → 20260612f.

---

## Task 1: Engine — `parseRestSeconds` (standalone, TS)

**Files:**
- Create: `src/engine/timing.ts`
- Test: `src/engine/timing.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// src/engine/timing.test.ts
import { describe, expect, it } from "vitest";
import { parseRestSeconds } from "./timing";

describe("parseRestSeconds — turn a rest string into a seconds range", () => {
  it("parses minute ranges and singles", () => {
    expect(parseRestSeconds("3-4 min")).toEqual({ min: 180, max: 240 });
    expect(parseRestSeconds("2-3 min")).toEqual({ min: 120, max: 180 });
    expect(parseRestSeconds("2 min")).toEqual({ min: 120, max: 120 });
  });
  it("parses seconds (bare or 'sec')", () => {
    expect(parseRestSeconds("90 sec")).toEqual({ min: 90, max: 90 });
    expect(parseRestSeconds("60-90 sec")).toEqual({ min: 60, max: 90 });
  });
  it("returns null when there's no number", () => {
    expect(parseRestSeconds("superset")).toBeNull();
    expect(parseRestSeconds(undefined)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/engine/timing.test.ts`
Expected: FAIL — "parseRestSeconds is not a function" / cannot resolve `./timing`.

- [ ] **Step 3: Write minimal implementation**

```ts
// src/engine/timing.ts
// Pure helpers for in-workout timing. No React, no audio — just numbers.

export interface RestRange {
  /** Lower bound of the prescribed rest, in seconds (the countdown target). */
  min: number;
  /** Upper bound, in seconds. Equal to min when the prescription is a single value. */
  max: number;
}

/** Parse a rest prescription ("3-4 min", "90 sec", "2 min") into a seconds
 * range. "min" anywhere means minutes; otherwise the numbers are seconds.
 * Returns null when there is no number (e.g. "superset"). */
export function parseRestSeconds(rest: string | undefined): RestRange | null {
  if (!rest) return null;
  const s = rest.toLowerCase();
  const nums = (s.match(/\d+(?:\.\d+)?/g) ?? []).map(Number);
  if (nums.length === 0) return null;
  const unit = s.includes("min") ? 60 : 1;
  const toSec = (n: number) => Math.round(n * unit);
  return { min: toSec(nums[0]!), max: toSec(nums[nums.length - 1]!) };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/engine/timing.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/engine/timing.ts src/engine/timing.test.ts
git commit -m "feat(timing): parseRestSeconds"
```

---

## Task 2: Engine — `parseTempo` (standalone, TS)

**Files:**
- Modify: `src/engine/timing.ts`
- Test: `src/engine/timing.test.ts`

- [ ] **Step 1: Add the failing test**

```ts
// append to src/engine/timing.test.ts
import { parseTempo } from "./timing"; // add to the existing import line

describe("parseTempo — eccentric-pause-concentric phase seconds", () => {
  it("parses dash notation; X = explosive = 0", () => {
    expect(parseTempo("3-1-1")).toEqual([3, 1, 1]);
    expect(parseTempo("3-0-1")).toEqual([3, 0, 1]);
    expect(parseTempo("3-1-X-1")).toEqual([3, 1, 0, 1]);
  });
  it("returns null for empty or non-numeric", () => {
    expect(parseTempo(undefined)).toBeNull();
    expect(parseTempo("abc")).toBeNull();
  });
});
```
(Adjust the top import to `import { parseRestSeconds, parseTempo } from "./timing";`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/engine/timing.test.ts`
Expected: FAIL — "parseTempo is not a function".

- [ ] **Step 3: Implement**

```ts
// append to src/engine/timing.ts
/** Parse tempo notation ("3-1-1", "3-1-X-1") into per-phase seconds.
 * "X" (explosive) = 0. Returns null when empty or any phase isn't a number. */
export function parseTempo(tempo: string | undefined): number[] | null {
  if (!tempo) return null;
  const phases = tempo.split("-").map((p) => {
    const t = p.trim().toUpperCase();
    return t === "X" ? 0 : Number(t);
  });
  if (phases.length === 0 || phases.some((n) => Number.isNaN(n))) return null;
  return phases;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/engine/timing.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Export + commit**

Modify `src/engine/index.ts` — add after the other exports:
```ts
export * from "./timing";
```
```bash
git add src/engine/timing.ts src/engine/timing.test.ts src/engine/index.ts
git commit -m "feat(timing): parseTempo + export timing module"
```

---

## Task 3: Tempo config + carry onto session items (standalone)

**Files:**
- Modify: `data/plan_config.json` (`rep_schemes.mains`)
- Modify: `src/engine/types.ts` (`SessionItem`)
- Modify: `src/engine/sessions.ts` (`buildItem` mains branch)
- Test: `src/engine/sessions.test.ts`

- [ ] **Step 1: Add `tempo` to the mains schemes in `data/plan_config.json`**

In `rep_schemes.mains`, add `"tempo"` to each entry:
```json
"mains": [
  { "k_range": [1, 3], "sets": 4, "reps": 5, "rpe_cap": "7", "tempo": "3-1-1" },
  { "k_range": [4, 6], "sets": 4, "reps": 4, "rpe_cap": "7-8", "tempo": "3-1-1" },
  { "k_range": [7, 9], "sets": 4, "reps": 3, "rpe_cap": "8", "tempo": "2-1-X" }
]
```

- [ ] **Step 2: Add `tempo` to `SessionItem`**

`src/engine/types.ts`, inside `interface SessionItem` (after `rpeCap?: string;`):
```ts
  /** Rep tempo notation (e.g. "3-1-1") for main lifts; undefined otherwise. */
  tempo?: string;
```

- [ ] **Step 3: Write the failing test**

```ts
// append to src/engine/sessions.test.ts
import { sessionForDate } from "./sessions"; // if not already imported
it("carries rep tempo onto the main lift on a build week", () => {
  const s = sessionForDate("2026-06-15", { equipment: { sandbag: true, axle: true } });
  const dl = s!.items.find((i) => i.exerciseId === "trap_bar_deadlift")!;
  expect(dl.tempo).toBe("3-1-1");
});
```
(Match the existing test file's import style/signature for `sessionForDate`/`resolveSession`; use whatever the file already uses to build a session for a date.)

- [ ] **Step 4: Run test to verify it fails**

Run: `npx vitest run src/engine/sessions.test.ts`
Expected: FAIL — `dl.tempo` is `undefined`.

- [ ] **Step 5: Implement in `buildItem`**

`src/engine/sessions.ts`, in the `if (b.scheme === "mains")` block, where the non-deload branch sets `sets/reps/rpeCap` from `mainsScheme(...)`, capture and assign tempo. Update `mainsScheme` to return tempo and assign it:
```ts
// where the mains scheme is read:
const m = mainsScheme(buildIndex(day.week));
sets = m.sets;
reps = m.reps;
rpeCap = m.rpeCap;
tempo = m.tempo;            // NEW
```
Add `let tempo: string | undefined = b.tempo;` near the other `let sets/reps/rpeCap` declarations, ensure `mainsScheme` returns `tempo` (read `r.tempo` from the scheme entry), and add `tempo,` to the returned `SessionItem` object literal.

- [ ] **Step 6: Run test + full engine suite**

Run: `npx vitest run src/engine`
Expected: PASS (new test + all existing).

- [ ] **Step 7: Commit**

```bash
git add data/plan_config.json src/engine/types.ts src/engine/sessions.ts src/engine/sessions.test.ts
git commit -m "feat(timing): tempo config on mains scheme, carried onto session items"
```

---

## Task 4: `RestTimer` + `TempoCue` React components (standalone)

**Files:**
- Create: `src/components/RestTimer.tsx`
- Create: `src/components/TempoCue.tsx`

- [ ] **Step 1: Create `RestTimer.tsx`**

```tsx
// src/components/RestTimer.tsx
import { useEffect, useRef, useState } from "react";

/** A short beep via Web Audio (no asset needed). */
function beep(times = 1) {
  try {
    const Ctx = window.AudioContext ?? (window as any).webkitAudioContext;
    const ctx = new Ctx();
    let t = ctx.currentTime;
    for (let i = 0; i < times; i++) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      osc.connect(gain);
      gain.connect(ctx.destination);
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.3, t + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
      osc.start(t);
      osc.stop(t + 0.2);
      t += 0.28;
    }
    setTimeout(() => ctx.close(), 1500);
  } catch {
    /* audio not available — silent */
  }
}

function mmss(s: number): string {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

export function RestTimer({
  seconds,
  maxSeconds,
  autoStart = false,
}: {
  seconds: number;
  maxSeconds?: number;
  autoStart?: boolean;
}) {
  const [remaining, setRemaining] = useState(seconds);
  const [running, setRunning] = useState(autoStart);
  const fired = useRef(false);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setRemaining((r) => Math.max(0, r - 1)), 1000);
    return () => clearInterval(id);
  }, [running]);

  useEffect(() => {
    if (remaining === 0 && running && !fired.current) {
      fired.current = true;
      beep(2);
      setRunning(false);
    }
  }, [remaining, running]);

  function reset() {
    fired.current = false;
    setRemaining(seconds);
    setRunning(true);
  }

  const done = remaining === 0;
  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg bg-slate-800/70 px-3 py-2">
      <span className={`tabular-nums text-lg font-semibold ${done ? "text-emerald-400" : "text-slate-100"}`}>
        {done ? "Rest done ✓" : mmss(remaining)}
      </span>
      {maxSeconds && maxSeconds !== seconds && !done && (
        <span className="text-xs text-slate-500">up to {mmss(maxSeconds)}</span>
      )}
      <span className="flex-1" />
      <button
        className="rounded-md bg-slate-700 px-2 py-1 text-xs text-slate-200"
        onClick={() => setRunning((r) => !r)}
      >
        {running ? "Pause" : "Start"}
      </button>
      <button className="rounded-md bg-slate-700 px-2 py-1 text-xs text-slate-200" onClick={reset}>
        Reset
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Create `TempoCue.tsx`**

```tsx
// src/components/TempoCue.tsx
import { useEffect, useRef, useState } from "react";

const LABELS = ["Down", "Pause", "Up", "Hold"]; // eccentric, pause, concentric, top

function tick() {
  try {
    const Ctx = window.AudioContext ?? (window as any).webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 660;
    osc.connect(gain);
    gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0.25, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.12);
    osc.start();
    osc.stop(ctx.currentTime + 0.13);
    setTimeout(() => ctx.close(), 400);
  } catch {
    /* silent */
  }
}

/** Runs one rep through its tempo phases with a tick + label per phase. */
export function TempoCue({ phases }: { phases: number[] }) {
  const [phase, setPhase] = useState(-1); // -1 = idle
  const [count, setCount] = useState(0);
  const idx = useRef(0);
  const left = useRef(0);

  useEffect(() => {
    if (phase < 0) return;
    const id = setInterval(() => {
      left.current -= 1;
      if (left.current <= 0) {
        idx.current += 1;
        if (idx.current >= phases.length) {
          setPhase(-1); // rep done
          return;
        }
        tick();
        left.current = Math.max(1, phases[idx.current]!);
        setPhase(idx.current);
      }
      setCount((c) => c + 1);
    }, 1000);
    return () => clearInterval(id);
  }, [phase, phases]);

  function startRep() {
    idx.current = 0;
    left.current = Math.max(1, phases[0]!);
    tick();
    setPhase(0);
  }

  const active = phase >= 0;
  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg bg-slate-800/70 px-3 py-2">
      <span className="text-xs text-slate-500">Tempo {phases.join("-")}</span>
      <span className="flex-1" />
      {active ? (
        <span className="tabular-nums text-sm font-semibold text-blue-300">
          {LABELS[phase] ?? `Phase ${phase + 1}`} · {left.current}s
        </span>
      ) : (
        <button className="rounded-md bg-slate-700 px-2 py-1 text-xs text-slate-200" onClick={startRep}>
          Cue a rep
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: PASS (no errors).

- [ ] **Step 4: Commit**

```bash
git add src/components/RestTimer.tsx src/components/TempoCue.tsx
git commit -m "feat(timing): RestTimer + TempoCue components"
```

---

## Task 5: Wire timers into `ExerciseCard` (standalone)

**Files:**
- Modify: `src/components/ExerciseCard.tsx`

- [ ] **Step 1: Imports + computed values**

Add imports:
```ts
import { parseRestSeconds, parseTempo } from "../engine";
import { RestTimer } from "./RestTimer";
import { TempoCue } from "./TempoCue";
```
Inside the component body (near the other derived values):
```ts
const rest = parseRestSeconds(item.rest);
const tempo = parseTempo(item.tempo);
const [restKey, setRestKey] = useState(0); // bump to remount/restart the rest timer
```

- [ ] **Step 2: Auto-start rest on Save**

In the `save()` function, after `setTrainingLog(...)` and before `setOpen(false)`, add:
```ts
if (rest) setRestKey((k) => k + 1); // arm the rest timer
```

- [ ] **Step 3: Render the timers**

Right after the prescription/warm-up block (before the pills `<div className="mt-1.5 ...">` or just after the cues/notes — keep it under the set/rep line), add:
```tsx
{tempo && tempo.length > 1 && <TempoCue phases={tempo} />}
{rest && restKey > 0 && (
  <RestTimer key={restKey} seconds={rest.min} maxSeconds={rest.max} autoStart />
)}
```

- [ ] **Step 4: Typecheck + full test suite**

Run: `npx tsc --noEmit && npx vitest run src/engine`
Expected: PASS.

- [ ] **Step 5: Build**

Run: `npm run build`
Expected: built, no errors.

- [ ] **Step 6: Commit**

```bash
git add src/components/ExerciseCard.tsx
git commit -m "feat(timing): rest timer auto-starts on log + tempo cue on Today"
```

---

## Task 6: Engine parity — `timing.py` (GYST)

**Files:**
- Create: `strongman/timing.py`
- Modify: `strongman/tests/test_engine.py`

- [ ] **Step 1: Add the failing parity test**

In `strongman/tests/test_engine.py`, add `parse_rest_seconds, parse_tempo` to the `from strongman.timing import ...` (create that import line) and add:
```python
def test_timing():
    eq(parse_rest_seconds("3-4 min"), {"min": 180, "max": 240}, "rest 3-4 min")
    eq(parse_rest_seconds("90 sec"), {"min": 90, "max": 90}, "rest 90 sec")
    eq(parse_rest_seconds("60-90 sec"), {"min": 60, "max": 90}, "rest 60-90 sec")
    eq(parse_rest_seconds("superset"), None, "rest superset -> None")
    eq(parse_tempo("3-1-1"), [3, 1, 1], "tempo 3-1-1")
    eq(parse_tempo("2-1-X"), [2, 1, 0], "tempo X=0")
    eq(parse_tempo(None), None, "tempo None")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m strongman.tests.test_engine`
Expected: FAIL — `ModuleNotFoundError: strongman.timing` / function missing.

- [ ] **Step 3: Implement `strongman/timing.py`**

```python
"""Pure helpers for in-workout timing — parity port of src/engine/timing.ts."""
from __future__ import annotations

import re
from typing import Optional


def parse_rest_seconds(rest: Optional[str]) -> Optional[dict]:
    """'3-4 min'/'90 sec'/'2 min' -> {'min': sec, 'max': sec}; None if no number."""
    if not rest:
        return None
    s = rest.lower()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    if not nums:
        return None
    unit = 60 if "min" in s else 1
    return {"min": round(nums[0] * unit), "max": round(nums[-1] * unit)}


def parse_tempo(tempo: Optional[str]) -> Optional[list]:
    """'3-1-1' -> [3,1,1]; 'X' (explosive) = 0; None if empty/non-numeric."""
    if not tempo:
        return None
    out = []
    for p in tempo.split("-"):
        t = p.strip().upper()
        if t == "X":
            out.append(0)
        else:
            try:
                out.append(int(t))
            except ValueError:
                return None
    return out or None
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m strongman.tests.test_engine`
Expected: `OK — N test groups, all assertions passed.`

- [ ] **Step 5: Commit**

```bash
git add strongman/timing.py strongman/tests/test_engine.py
git commit -m "feat(timing): parse_rest_seconds + parse_tempo (Python parity)"
```

---

## Task 7: Tempo config + carry onto items (GYST)

**Files:**
- Modify: `strongman/seed/plan_config.json` (`rep_schemes.mains`)
- Modify: `strongman/sessions.py` (mains scheme + item dict)
- Modify: `strongman/tests/test_engine.py`

- [ ] **Step 1: Add `tempo` to mains schemes** in `strongman/seed/plan_config.json` — identical to Task 3 Step 1 (add `"tempo": "3-1-1"` to k1-3 and k4-6, `"tempo": "2-1-X"` to k7-9).

- [ ] **Step 2: Add the failing test**

Append to `test_sessions()` in `strongman/tests/test_engine.py` (which already builds `mon`):
```python
    eq(main.get("tempo"), "3-1-1", "lower main carries tempo")
```
(`main` is the lower-day main item already fetched in that test.)

- [ ] **Step 3: Run to verify it fails**

Run: `python -m strongman.tests.test_engine`
Expected: FAIL — tempo is None.

- [ ] **Step 4: Implement in `strongman/sessions.py`**

In `_mains_scheme(...)` (the function returning `{"sets","reps","rpe_cap"}`), include `"tempo": r.get("tempo")` from the matched scheme entry and the fallback. In `_build_item`, where the mains scheme is applied, set `item["tempo"] = sch.get("tempo")` (and ensure the item dict includes `"tempo": None` by default so the key always exists).

- [ ] **Step 5: Run to verify it passes**

Run: `python -m strongman.tests.test_engine`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add strongman/seed/plan_config.json strongman/sessions.py strongman/tests/test_engine.py
git commit -m "feat(timing): tempo on GYST mains scheme, carried onto items"
```

---

## Task 8: GYST `<gyst-timer>` custom element + page wiring

**Files:**
- Create: `house_demo/assets/strongman-timer.js`
- Modify: `house_demo/house_demo/house_demo.py` (load script)
- Modify: `house_demo/house_demo/strongman_state.py` (`ItemRow` + `_item_row`)
- Modify: `house_demo/house_demo/strongman_pages.py` (`_exercise_card`)

- [ ] **Step 1: Create the custom element `house_demo/assets/strongman-timer.js`**

```js
// Self-contained workout timers as a custom element. No framework.
// <gyst-timer kind="rest" seconds="180" max="240"></gyst-timer>
// <gyst-timer kind="tempo" phases="3,1,1"></gyst-timer>
(function () {
  function beep(freq, dur) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = freq;
      osc.connect(gain); gain.connect(ctx.destination);
      gain.gain.setValueAtTime(0.25, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + dur);
      osc.start(); osc.stop(ctx.currentTime + dur + 0.02);
      setTimeout(function () { ctx.close(); }, (dur + 0.4) * 1000);
    } catch (e) {}
  }
  function mmss(s) { var m = Math.floor(s / 60); var r = s % 60; return m + ":" + (r < 10 ? "0" : "") + r; }

  class GystTimer extends HTMLElement {
    connectedCallback() {
      if (this._wired) return; this._wired = true;
      this.kind = this.getAttribute("kind") || "rest";
      this.style.cssText = "display:flex;align-items:center;gap:8px;margin-top:8px;padding:6px 10px;border-radius:8px;background:rgba(100,116,139,.18);font-size:13px";
      this.timer = null;
      if (this.kind === "tempo") this._renderTempo(); else this._renderRest();
    }
    disconnectedCallback() { if (this.timer) clearInterval(this.timer); }
    _btn(label, cb) {
      var b = document.createElement("button");
      b.textContent = label;
      b.style.cssText = "border:0;border-radius:6px;padding:4px 8px;background:#334155;color:#e2e8f0;font-size:12px";
      b.onclick = cb; return b;
    }
    _renderRest() {
      var self = this;
      this.target = parseInt(this.getAttribute("seconds") || "0", 10);
      this.max = parseInt(this.getAttribute("max") || "0", 10);
      this.left = this.target;
      var disp = document.createElement("span");
      disp.style.cssText = "font-variant-numeric:tabular-nums;font-weight:600;font-size:16px;color:#f1f5f9";
      var note = document.createElement("span");
      note.style.cssText = "font-size:11px;color:#64748b";
      if (this.max && this.max !== this.target) note.textContent = "up to " + mmss(this.max);
      var spacer = document.createElement("span"); spacer.style.flex = "1";
      var startBtn = this._btn("Start", function () { self._start(disp); });
      var resetBtn = this._btn("Reset", function () { self.left = self.target; self._stop(); disp.textContent = mmss(self.left); disp.style.color = "#f1f5f9"; });
      function paint() { disp.textContent = self.left <= 0 ? "Rest done ✓" : mmss(self.left); }
      paint();
      this._start = function () {
        self._stop();
        self.timer = setInterval(function () {
          self.left -= 1;
          if (self.left <= 0) { self.left = 0; self._stop(); disp.style.color = "#34d399"; beep(880, 0.18); setTimeout(function(){beep(880,0.18);}, 260); }
          paint();
        }, 1000);
      };
      this._stop = function () { if (self.timer) { clearInterval(self.timer); self.timer = null; } };
      this.append(disp, note, spacer, startBtn, resetBtn);
    }
    _renderTempo() {
      var self = this;
      this.phases = (this.getAttribute("phases") || "").split(",").map(function (n) { return parseInt(n, 10) || 0; });
      var LABELS = ["Down", "Pause", "Up", "Hold"];
      var label = document.createElement("span");
      label.style.cssText = "font-size:11px;color:#64748b";
      label.textContent = "Tempo " + this.phases.join("-");
      var spacer = document.createElement("span"); spacer.style.flex = "1";
      var state = document.createElement("span");
      state.style.cssText = "font-variant-numeric:tabular-nums;font-weight:600;color:#93c5fd";
      var btn = this._btn("Cue a rep", function () { self._run(state, btn); });
      this.append(label, spacer, state, btn);
    }
    _run(state, btn) {
      var self = this; var i = 0; var left = Math.max(1, this.phases[0] || 1);
      var LABELS = ["Down", "Pause", "Up", "Hold"];
      btn.style.display = "none"; beep(660, 0.12);
      function paint() { state.textContent = (LABELS[i] || ("P" + (i + 1))) + " · " + left + "s"; }
      paint();
      this.timer = setInterval(function () {
        left -= 1;
        if (left <= 0) {
          i += 1;
          if (i >= self.phases.length) { clearInterval(self.timer); self.timer = null; state.textContent = ""; btn.style.display = ""; return; }
          beep(660, 0.12); left = Math.max(1, self.phases[i]);
        }
        paint();
      }, 1000);
    }
  }
  if (!customElements.get("gyst-timer")) customElements.define("gyst-timer", GystTimer);
})();
```

- [ ] **Step 2: Load the script** in `house_demo/house_demo/house_demo.py` `head_components`, next to the other `rx.el.script(...)` lines:
```python
        rx.el.script(src="/strongman-timer.js?v=20260612f", defer=True),
```

- [ ] **Step 3: Add timer data to `ItemRow` + `_item_row`** in `strongman/.../strongman_state.py`:

Add to `ItemRow(TypedDict, total=False)`:
```python
    rest_seconds: int
    rest_max: int
    tempo_csv: str
```
In `_item_row`, compute from the engine and add to the returned `ItemRow(...)`:
```python
    from strongman.timing import parse_rest_seconds, parse_tempo  # top-of-file import
    rr = parse_rest_seconds(item.get("rest"))
    tp = parse_tempo(item.get("tempo"))
    # ... in ItemRow(...):
    rest_seconds=(rr["min"] if rr else 0),
    rest_max=(rr["max"] if rr else 0),
    tempo_csv=(",".join(str(n) for n in tp) if tp and len(tp) > 1 else ""),
```
(Move the import to the module top with the other `from strongman...` imports.)

- [ ] **Step 4: Render the elements** in `_exercise_card` in `strongman_pages.py`, after the warm-up `rx.cond(...)` and before the `rx.hstack` of badges:
```python
            rx.cond(
                item["tempo_csv"] != "",
                rx.html('<gyst-timer kind="tempo" phases="' + item["tempo_csv"] + '"></gyst-timer>'),
                rx.fragment(),
            ),
            rx.cond(
                item["rest_seconds"] > 0,
                rx.html('<gyst-timer kind="rest" seconds="'
                        + item["rest_seconds"].to(str) + '" max="' + item["rest_max"].to(str) + '"></gyst-timer>'),
                rx.fragment(),
            ),
```
(If `rx.html` rejects interpolated Vars, fall back to building the element string in `_item_row` as a full `rest_html`/`tempo_html` field and render `rx.html(item["rest_html"])`. Verify which works during the dev compile in Step 6.)

- [ ] **Step 5: py_compile**

Run: `python -m py_compile strongman/timing.py strongman/sessions.py house_demo/house_demo/strongman_state.py house_demo/house_demo/strongman_pages.py house_demo/house_demo/house_demo.py`
Expected: RC=0.

- [ ] **Step 6: Dev compile check (on houseapp)**

Sync the changed files to `/opt/house-inventory`, restart `gyst-dev`, confirm "App running" with no traceback and `/strongman` serves. (Use the established staging/scp flow.)

- [ ] **Step 7: Commit**

```bash
git add house_demo/assets/strongman-timer.js house_demo/house_demo/house_demo.py house_demo/house_demo/strongman_state.py house_demo/house_demo/strongman_pages.py
git commit -m "feat(timing): <gyst-timer> custom element + rest/tempo on Today cards"
```

---

## Task 9: Deploy both apps

- [ ] **Step 1: Standalone — push (triggers Pages CI)**

```bash
cd C:/Users/white/repos/strongman-rebuild
git push origin main
```
Then watch the run: `gh run watch <id> --exit-status` — expect `npm test` ✓, build ✓, deploy ✓. Confirm `https://kerbe42.github.io/strongman-rebuild/` → 200.

- [ ] **Step 2: GYST — bump BUILD_VERSION 20260612e → 20260612f**

In `house_demo/assets/sw.js`, `house_demo/assets/pwa-register.js`, `house_demo/house_demo/layout.py`, and the `?v=` on the `pwa-register.js` + `strongman-timer.js` script tags in `house_demo/house_demo/house_demo.py`: replace `20260612e` → `20260612f`. Commit.

- [ ] **Step 3: GYST — deploy to prod**

Sync the changed files into `/opt/house-inventory`, snapshot prod data, run `sudo bash /opt/house-inventory/deploy/sync-to-prod.sh`, then verify served `BUILD_VERSION = "20260612f"`, `/strongman` route healthy, `strongman-timer.js` served (curl `/strongman-timer.js` → 200), clean journal. (Follow the runbook in `gyst_houseapp_deploy` memory.)

- [ ] **Step 4: Push GYST**

```bash
cd C:/Users/white/repos/gyst
git fetch origin && git rebase origin/main && git push origin main
```

---

## Notes for the implementer
- **No server ticking in Reflex** — the timer lives entirely in `strongman-timer.js`. The Reflex side only passes static numbers (`rest_seconds`, `rest_max`, `tempo_csv`) into the element's attributes.
- **Audio needs a user gesture** on mobile — the Start/Cue buttons provide it; auto-start countdown is fine but the beep only fires after the first interaction in the session. Acceptable for v1.
- **Rest countdown target = the lower bound** (`min`); the upper bound shows as "up to m:ss".
- **Tempo only renders when there are ≥2 phases** (skips noise on lifts with no real tempo).
- Standalone tests must stay green (`npx vitest run`); GYST engine harness must print `OK`. The standalone `store.test.ts` localStorage failure on Node 26 is a known local-env artifact (passes in Node-20 CI) — see `strongman_rebuild_goal` memory.
- **Scope decision — work-block (count-up) timer for carries is deferred to a P1.1 follow-up.** Spec §4.1 lists it, but timed carries only begin in Q2 ("Q2+: 2x50 ft timed"); week-1/Q1 carries are distance-only. The same `<gyst-timer>` / `RestTimer` gains a `kind="work"` count-up mode then. Tracked here so it isn't silently dropped.
- **Task 3/7 internals:** the exact edit points in `sessions.ts` `buildItem`/`mainsScheme` and `sessions.py` `_build_item`/`_mains_scheme` should match the functions' existing signatures — read them before editing; the plan specifies the field to add (`tempo`) and where it flows, not line numbers.
