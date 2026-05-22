# Observed Signal Patterns — Bazzite 43 / KDE Plasma / KWin Wayland

Test run: `test-run-1778177929.log`
System: Bazzite 43 (bazzite-deck), KDE Plasma, KWin Wayland, PipeWire

---

## Signal source summary

| Source | Interface | What it tells us | Latency |
|--------|-----------|-----------------|---------|
| `ext_idle_notifier_v1` | Wayland | User has stopped providing input | Immediate (timeout-based) |
| `PowerMgmt.Inhibit` | DBus session | Something wants the screen/system awake | **~5s activation, 0-10s release** |
| `KDE PolicyAgent` | DBus session | Which apps inhibit what, with types | Same timing as PowerMgmt, but sends INVALIDATED (must re-query) |
| MPRIS | DBus session | Per-player PlaybackStatus + Metadata | **Immediate** (<1ms) |
| PulseAudio events | libpulse | Audio streams appear/disappear | **Immediate** (<1ms) |
| logind | DBus system | PrepareForSleep, session props | **Immediate** |
| NetworkManager | DBus system | Connectivity state for post-resume | ~5s after resume to reach FULL |

---

## Pattern 1: Idle / Resume (no media)

```
User stops input
  ├─ +5.0s  wayland/idle-notify IDLED
  │
User moves mouse
  └─ +0ms   wayland/idle-notify RESUMED
```

- logind `IdleHint` did NOT change during idle/resume cycles.
  KWin does not appear to set the session idle hint for short idle periods.
- `ext_idle_notifier_v1` works correctly and is the only reliable idle source.

---

## Pattern 2: Music playback (Firefox playing audio in tab)

### Play
```
t+0.0s   pulse/sink-input NEW
t+0.1s   MPRIS PlaybackStatus = Playing
t+5.1s   PowerMgmt.Inhibit has_inhibit = True      ← ~5s debounce
t+5.1s   PolicyAgent INVALIDATED (Active/Requested)
```

### Pause
```
t+0.0s   MPRIS PlaybackStatus = Paused
t+0.0s   pulse/sink-input CHANGE
t+0.0s   PolicyAgent INVALIDATED
t+10.0s  PowerMgmt.Inhibit has_inhibit = False      ← ~10s release delay!
```

Key observations:
- Firefox holds its inhibit for **~10 seconds after pause**. This is a
  browser-level debounce (avoids flicker during page navigation).
- MPRIS is immediate and trustworthy. `has_inhibit` lags by 5-10s.
- Wayland IDLED fires freely during active inhibit (see Pattern 6).

---

## Pattern 3: Video playback (Firefox, "Mocros")

Identical timing to audio. Firefox uses the same inhibit mechanism for both.

```
Play:   MPRIS Playing → +5.4s → has_inhibit=True
Pause:  MPRIS Paused  → +10.0s → has_inhibit=False
```

Firefox sets PolicyAgent inhibition type `idle` with reasons
`"Playing audio"` and `"Playing video"` (from initial state dump).
Both use `block` mode.

---

## Pattern 4: Jellyfin Desktop (Electron app, video+music)

### Track transition pattern (very noisy)
```
t+0.0s   MPRIS PlaybackStatus = Stopped
t+0.0s   MPRIS CanControl/CanPause/CanPlay/CanSeek = False
t+0.0s   MPRIS Position = 0
t+0.001s MPRIS CanControl = True, CanPlay = True
t+0.001s MPRIS PlaybackStatus = Paused                ← fake "paused"
t+0.1s   MPRIS Metadata = <next track>
t+0.3s   pulse/sink-input CHANGE or NEW
t+0.3s   MPRIS Rate = 1.0, CanPause = True
t+0.3s   MPRIS PlaybackStatus = Playing               ← real play
```

Every track change goes through Stopped → Paused → Playing in ~300ms.
Naive monitoring would see a "pause" event on every track boundary.

### Inhibit timing (Jellyfin)
```
Play:   MPRIS Playing → +5.3s → has_inhibit=True     ← same ~5s debounce
Pause:  MPRIS Paused  → +0.0s → has_inhibit=False    ← IMMEDIATE release
Stop:   MPRIS Stopped → +0.0s → has_inhibit=False    ← IMMEDIATE release
```

Jellyfin releases its inhibit **instantly** on pause/stop (unlike Firefox's
10s hold). This is the Electron default behavior — no debounce.

### Player lifecycle
```
App open:  MPRIS PLAYER APPEARED, PlaybackStatus = Stopped
App close: MPRIS Stopped → pulse REMOVE → PLAYER DISAPPEARED
           (4.6s between last stop and disappearance)
```

---

## Pattern 5: Gaming (Chromium-based, likely Steam overlay or game)

```
t+0.0s   pulse/sink-input NEW (client + stream)
t+0.7s   MPRIS chromium.instance2 APPEARED
t+0.7s   MPRIS WATCH FAILED: no Properties interface  ← BROKEN MPRIS
t+5.3s   has_inhibit = True
          ... intermittent has_inhibit True/False cycling ...
t+end    pulse REMOVE → has_inhibit = False (after ~5s delay)
```

Key findings:
- Chromium-based apps register as MPRIS players but expose **no Properties
  interface**. Cannot read PlaybackStatus or Metadata.
- Inhibit is set via a non-MPRIS mechanism (likely portal or PolicyAgent directly).
- Inhibit **cycles on and off** during gameplay (~2-10s intervals). This may be
  cutscene/loading transitions or the game's own inhibit management.
- Wayland IDLED fires during gaming. Controller input likely does NOT reset the
  Wayland idle timer.

---

## Pattern 6: Wayland IDLED vs. DBus inhibit (critical finding)

**`ext_idle_notifier_v1` ALWAYS fires based on user inactivity, completely
independent of `PowerMgmt.Inhibit` or `PolicyAgent` state.**

Observed: IDLED fired during active inhibit at t=32s, 134s, 189s, 202s, 230s,
369s, 380s, 432s. Zero cases of IDLED being suppressed by an active inhibit.

This means the app MUST bridge these two worlds itself: deregister the Wayland
idle notification when `has_inhibit=True`, re-register when `False`.

The current app does this correctly via `PowerManagementIdleInhibitor` →
`IdleManager.inhibit()` → `WaylandIdleManager._on_inhibit()` which calls
`_deregister_idle_notification()`.

---

## Pattern 7: Suspend / Resume

### Pre-suspend (network goes down within 80ms)
```
t+0.000s  logind PREPARE_FOR_SLEEP start=True
t+0.009s  NetworkManager State = ASLEEP
t+0.073s  NM connections torn down
t+0.080s  NM Connectivity = NONE
t+0.401s  PulseAudio: sink/source removed and recreated
```

**The TV power-off command must be sent between PrepareForSleep(true) and the
system actually suspending. The network dies within 80ms of the signal but the
delay inhibitor holds suspend until the fd is closed (up to InhibitDelayMaxSec).**

### Post-resume (5.4s to full network)
```
t+0.000s  logind PREPARE_FOR_SLEEP start=False
t+0.000s  NM State = DISCONNECTED (network driver reloading)
t+0.050s  Wayland IDLED + RESUMED (reset artifact, ignore)
t+0.150s  PulseAudio: massive sink/source reconfiguration
t+3.036s  NM State = CONNECTING
t+5.035s  NM Connectivity = LIMITED
t+5.211s  NM State = CONNECTED_SITE
t+5.421s  NM State = CONNECTED_GLOBAL, Connectivity = FULL
```

**Wait for `Connectivity=4(FULL)` or `State=70(CONNECTED_GLOBAL)` before
sending the TV wake command. Do not trust `PrepareForSleep(false)` alone.**

The Wayland IDLED/RESUMED that fires at +50ms after resume is an artifact of
the compositor resetting. The app should ignore idle events for a brief window
after resume.

---

## Pattern 8: Lock screen

**Not tested** — Meta+L did not work on this Bazzite install. The
`ScreenSaver` and `kde.screensaver` interfaces are present and return
`active=False` at startup, so the signal infrastructure exists but could not
be triggered.

---

## Design implications

### What the current app gets right
1. Bridging `PowerMgmt.Inhibit` → deregister Wayland idle notification. Works.
2. logind `PrepareForSleep` with delay inhibitor. Correct architecture.
3. PulseAudio sink-input for audio stream detection. Works.

### What needs attention

#### The ~5s inhibit activation delay
`PowerMgmt.Inhibit` goes True ~5 seconds after playback starts. During this
window, the app would incorrectly allow idle-triggered screen-off if the user
happens to be idle when starting playback (e.g. pressing play and immediately
going hands-off, or starting playback with a remote control).

**Mitigation options:**
- Also watch MPRIS `PlaybackStatus=Playing` and inhibit immediately on that,
  not just on `has_inhibit`. Treat MPRIS as an early signal.
- PulseAudio `sink-input NEW` is even earlier (arrives ~100ms before MPRIS).

#### The ~10s Firefox inhibit release delay
Firefox holds its inhibit for 10s after pause. During this window, the app
blocks idling unnecessarily. With the real 180s idle timeout this is irrelevant
(10s out of 180s). But worth knowing.

#### Jellyfin's Stopped→Paused→Playing track transitions
Every track boundary produces a false "Paused" event. If the app were to use
MPRIS directly for inhibit decisions, it would need to debounce: don't react
to Paused/Stopped unless the state persists for >500ms.

#### Chromium/Electron MPRIS is broken
Some apps appear as MPRIS players but expose no Properties interface. The app
cannot fall back to MPRIS for these. `PowerMgmt.Inhibit` is the only source,
despite its latency.

#### Gaming and controller input
Wayland IDLED fires during gameplay. If the game is controller-only (no
mouse/keyboard), the idle timer will fire. The current `PowerMgmt.Inhibit`
bridge handles this (games set inhibit → idle notification deregistered),
but see the ~5s activation delay above.

The inhibit also cycles on/off during gameplay, possibly due to cutscene
transitions. This could cause brief idle-triggered screen-offs. Debouncing
the uninhibit (wait ~2s before re-registering idle notification) would help.

#### Post-resume: wait for network
Don't send TV wake command on `PrepareForSleep(false)`. Wait for
`NetworkManager.Connectivity=4(FULL)`, which takes ~5.4s on this system.

#### PolicyAgent sends INVALIDATED, not values
When PolicyAgent properties change, DBus sends `PropertiesChanged` with the
properties listed in the `invalidated` array, not in `changed`. The actual
values must be explicitly re-queried with a `Get` call.
