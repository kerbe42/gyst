# GYST Life Coach — Design

**Date:** 2026-06-13
**Owner:** Justin (kerbe42)
**Status:** Draft for review

## 1. Vision

Evolve GYST from a household-management app into a personal operating system that:

1. **Plans** the day — training, meals, sleep, movement, work, and existing GYST calendar/chores merged into one timeline.
2. **Times** you through it — rep tempo, rest timers, work blocks, meal windows, wind-down, lights-out.
3. **Holds you accountable** — escalating reminders, streaks, JARVIS call-outs, and an end-of-day report card.
4. **Enforces the routine** — restricts distractions (games, YouTube, streaming, free surfing) and can cut the phone's internet during training / focus / sleep windows, via two levers: the home firewall (pfSense/OPNsense) and an Android companion app.

This is a **self-binding** system (Justin restricting his own device to hold a routine — a commitment device, like Freedom / Cold Turkey / Pi-hole schedules). It must always preserve a **break-glass** path: emergency calls work, and there is one logged override so he can never truly lock himself out.

## 2. Confirmed constraints (from Justin)

- **Phone:** Android — enables real device-level enforcement (Accessibility + local VPN + Device Admin).
- **Home network:** pfSense/OPNsense — full firewall API for per-device blocking and scheduled internet kill.
- **Reach:** Both — network-level at home **and** phone-side everywhere (incl. cellular).
- **Accountability:** all four mechanics (escalating nudges, streaks + miss log, JARVIS call-outs, daily report card).

### Hard reality
GYST is a PWA; a browser app **cannot** block other apps or touch the network. All enforcement must run in one of the two real actuators below. GYST is the brain (schedule + policy + logs); the actuators are the muscle.

## 3. Architecture

```
                ┌─────────────────────────── GYST (houseapp, existing) ───────────────────────────┐
                │  Day Profile · Routine/Timeline engine · Policy model · Accountability · Logs     │
                │  (reuses: appointments, reminders dispatcher, VAPID push, briefings, JARVIS)       │
                └───────────────┬───────────────────────────────────────────────┬──────────────────┘
                                │ block window starts/ends                       │ policy + commands
                                ▼                                                ▼
                   ┌────────────────────────┐                      ┌───────────────────────────────┐
                   │ Network actuator        │                      │ Android companion ("Enforcer") │
                   │ pfSense/OPNsense API     │                      │ Accessibility (block apps)      │
                   │ - block domains/device   │                      │ Local VPN (block domains / kill)│
                   │ - kill phone internet    │                      │ Device Admin (resist removal)   │
                   │ HOME Wi-Fi only          │                      │ EVERYWHERE incl. cellular       │
                   └────────────────────────┘                      └───────────────────────────────┘
```

- **GYST core** holds the schedule, the day plan, the policy (what's blocked when), and all logs. It already has the scheduling backbone: appointments, a reminders dispatcher (`gyst-reminders`), VAPID web push, morning/evening briefings, and JARVIS. *(Exact APIs to be confirmed during planning.)*
- **Network actuator** and **Android companion** are the only things that can actually restrict. They take their orders from GYST.
- **Fail-safe stance:** the Android app caches the current policy so it keeps enforcing even if GYST is briefly unreachable; during a known block window it fails *closed*.

## 4. Components

### 4.0 Foundations (shared, build first inside Phase 0)
- **Day Profile** — rhythm anchors, editable in GYST Settings: wake, lights-out, meal windows, work hours, training days/times, movement-break cadence (e.g., every 60 min).
- **Routine/Timeline engine** — merges Day Profile + the day's training session (Strongman) + meals + GYST appointments into an ordered list of time-blocked events: `{start, end, type, title, detail}` where type ∈ {sleep, wake, eat, train, move, work, focus, free}.
- **Policy model** — per block type, an allow/block set referencing app packages (Android) and domain lists. E.g. `train`, `focus`, `sleep` → block {games, YouTube, Netflix, social, general web}; `free` → allow all. One source of truth, consumed by both actuators.

### 4.1 In-workout timing — **Phase 1 (ship first, standalone, no enforcement)**
- **Rest timer**: auto-starts when a set is logged; counts the prescribed rest ("3–4 min"); push/buzz at done.
- **Rep tempo**: per-set cue/metronome (e.g. eccentric-pause-concentric like `3-1-1`); tempo added to the scheme/exercise config. Visual + optional audio.
- **Work-block timer**: for carries/events ("50 ft", timed carries).
- Lives on the existing Today screen. Pure value, smallest slice, usable Monday.

### 4.2 Daily timeline — **Phase 2**
- **Timeline view**: today as a vertical schedule with a "NOW" marker; each block = what + when + duration.
- **Up-next banner** on Today: "Next: eat (1:00 pm) · then Lower session (5:30 pm)".
- **Meal timing** tied to protein targets; **sleep** (wind-down + lights-out) and **movement** (hourly stand-up) blocks.

### 4.3 Accountability — **Phase 3** (all four, on the existing reminders/push)
- **Escalating nudges**: each block pushes at start; if not completed/acknowledged, escalate on a backoff (gentle → insistent → JARVIS DM → report-card ding).
- **Streaks + miss log**: per-habit streaks (trained / ate on plan / slept on time / movement / stayed off blocked apps); misses logged with timestamps + reason.
- **JARVIS call-outs**: proactive assistant messages ("you skipped the 2pm movement block — what happened?"), logs the reason, can adjust tomorrow.
- **Daily report card**: end-of-day score pushed to phone across all habits.

### 4.4 Enforcement — **Phase 4** (the teeth)

**4a. Network actuator — pfSense/OPNsense (home).** Build before 4b (GYST can drive it with no phone app).
- Phone gets a **static DHCP reservation** so its IP is stable.
- Firewall **aliases** for blocked-domain/IP sets + a **block-all** rule scoped to the phone's IP.
- On block-window boundaries, GYST calls the firewall API to enable/disable rules: block distraction domains, or **kill the phone's internet entirely** during sleep/training/focus.
- OPNsense: documented REST API (`/api/firewall/alias`, `/api/firewall/filter` + apply). pfSense: `pfSense-API` package or config-write + reload.
- Driven by the same scheduler loop that runs reminders. **Home Wi-Fi only** by nature.

**4b. Android companion app — "GYST Enforcer" (everywhere).**
- Native Kotlin app; receives the active policy + current block window from GYST (push/poll over the LAN, with local cache).
- **Accessibility service**: detects the foreground app; during a block window, if it's a blocked app, kicks out + shows a full-screen "back to your routine" overlay.
- **Local VPN service** (no-root): blackholes blocked domains, or **all traffic** ("kill internet"), during block windows — works on **cellular** too.
- **Device Admin**: resists casual uninstall/disable (with break-glass).
- Reports compliance back to GYST so accountability knows about bypasses.
- Distribution: **sideload** (Play Store restricts Accessibility-blocker apps) — fine for personal use.

### 4.5 Whole-life merge — **Phase 5**
- Fold existing GYST modules (chores, appointments, groceries) into the timeline so it's the *actual* day, not just training/health.

## 5. Safety / break-glass (non-negotiable)
- **Emergency calls/SMS always allowed** (never VPN-blocked; Accessibility never blocks the dialer).
- **One override/day**: time-delayed (e.g. "wait 5 min"), **logged**, and **breaks the relevant streak** — so it costs something but you're never bricked.
- **Sleep-window exceptions**: alarms, and a medical/emergency allowlist.
- Nothing touches money, accounts, or anything that could endanger you. This restricts entertainment/distraction apps and general web during your own chosen focus windows — that's it.

## 6. Risks & honest caveats
- Android Accessibility + VPN is exactly how real blockers work; reliable, but sideloaded.
- A determined person can always escape (cellular when network-only, disabling the app, factory reset). The dual lever + Device Admin + accountability logging maximizes **friction + accountability** — it's not a literal prison, and shouldn't pretend to be.
- pfSense/OPNsense "kill internet" = a block-all rule on the phone's IP; solid and reversible.
- The Android companion is a genuine second app to build/maintain (Kotlin) — the largest single piece. Network actuator (4a) delivers most of the home-time value far sooner.

## 7. Build order
- **Phase 0** — Day Profile + Timeline engine + Policy model (foundations).
- **Phase 1** — In-workout timing (ship immediately; standalone; no enforcement).
- **Phase 2** — Daily timeline view.
- **Phase 3** — Accountability (4 mechanics).
- **Phase 4a** — pfSense/OPNsense network actuator (home enforcement; GYST-only, no phone app).
- **Phase 4b** — Android "GYST Enforcer" companion (everywhere enforcement).
- **Phase 5** — Whole-life merge.

Each phase is usable on its own. Recommended first build: **Phase 1** (fast, tangible) — then **Phase 4a** (real teeth at home without waiting on the Android app).

## 8. Open questions (for planning, not blocking this doc)
- Daily rhythm specifics (wake/sleep/meal/work times, training time-of-day, movement cadence).
- Which exact distraction apps + domains to block, and which windows (training-only? all focus blocks? sleep?).
- pfSense vs OPNsense (which is actually running) + API access.
- Push transport for the native app (FCM vs LAN poll).
- Streak/override rules: how punishing the override is, streak reset rules.
