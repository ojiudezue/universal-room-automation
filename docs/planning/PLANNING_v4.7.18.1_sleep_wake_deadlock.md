# PLANNING v4.7.18.1 — SLEEP→WAKING Deadlock Hotfix (Option D)

**Tier:** 1 (Hotfix — single file `presence.py`, one behavioral bug, no new
config/sensors/DB). One adversarial review + live validation.

**Branch:** `feature/v4.7.18.1-sleep-wake-deadlock` (off `develop` @ 692ad8e).

**Trigger (live incident 2026-06-03):** House observed stuck in `SLEEP` for
13.75h. `wake_blocked_ticks=4666` and climbing. `census_count=2` (Jaya home all
morning), `camera_occupied_count=0`, mmwave firing but masked. Both SLEEP exits
dead.

---

## Institutional context verified

### Root-cause trace (all file:line read end-to-end this session)

- **SLEEP has exactly two exits** — `house_state.py:66-69`:
  `SLEEP → {WAKING, AWAY}`. Nothing else.
- **AWAY exit is correctly blocked.** Inference returns AWAY only when
  `census_count == 0` (`presence.py:477`) or the v4.7.14 tracker-veto path which
  also requires `census_count == 0` (`presence.py:494-502`). Jaya is home →
  `census_count=2` → AWAY correctly withheld. *No change here.*
- **WAKING exit is structurally dead during sleep.** The engine *does* propose
  WAKING every tick after `sleep_end_hour` (`presence.py:530-532`,
  `current_state == SLEEP → return WAKING`). But the D3 gate
  (`presence.py:2825-2851`) vetoes it unless sustained zone occupancy is seen.
- **The gate reads override-masked occupancy.** `any_zone_occupied`
  (`presence.py:2524-2527`) = `any(t.mode == OCCUPIED)`. `ZonePresenceTracker.mode`
  (`presence.py:225-229`) returns `self._override` *before* `_derived_mode`.
  When the house sleeps, `set_sleep(True)` hard-sets `_override = SLEEP` on every
  auto tracker (`presence.py:351-357`). So `mode` returns `SLEEP`, never
  `OCCUPIED`, no matter what mmwave/camera/BLE report.
- **Therefore the wake timer can never start.**
  `_first_positive_zone_occupied_since` is set only when `any_zone_occupied`
  is True (`presence.py:2532-2538`) → stays `None` all sleep → `sustained_seconds=0`
  → Pattern-D veto fires every tick (`presence.py:893-908`,
  `_WAKING_SUSTAINED_THRESHOLD_SECONDS=90` @ `:108`) → WAKING suppressed forever.
- **Why it normally goes unnoticed:** on a typical morning everyone leaves →
  `census→0` → SLEEP→AWAY masks the broken wake path. The deadlock only surfaces
  when someone stays home all morning (no AWAY) — exactly the observed case.

### `_derived_mode` IS the raw computation we need

`presence.py:231-260`: `_derived_mode` already evaluates BLE (`_ble_occupied`),
Tier-1 (`_room_occupied`), Tier-2 (`_any_camera_occupied()`) — and is only ever
consulted when `_override is None`. It is exactly "occupancy ignoring the
override." We expose it via a new `raw_occupied` property (REUSE of existing
logic, no new tier math).

### Field-usage audit (blast radius of Option A)

`_first_positive_zone_occupied_since` is written only at `presence.py:2533-2538`
and read only at `presence.py:2830` (the WAKING gate). grep confirms no other
reader. **It is wake-gate-private** → re-sourcing it from raw occupancy cannot
affect any other consumer. `any_zone_occupied` (mode-based) stays untouched for
its other consumers (`infer()` arg `presence.py:451`, AWAY-veto log `:2807-2814`).

### Greps run — REUSED / NEW

- `raw_occupied` property → **NEW** (no equivalent; `_derived_mode` exists but is
  private and returns a mode string, not a bool). Thin wrapper, zero new logic.
- `any_zone_raw_occupied` local → **NEW** (parallels existing `any_zone_occupied`
  local at `:2524`).
- `_wake_backstop_fires` counter → **NEW** (parallels `_wake_blocked_ticks`
  `:658`, already surfaced at `sensor.py:3852`).
- `_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END` const → **NEW** (no equivalent;
  module-level alongside `_WAKING_SUSTAINED_THRESHOLD_SECONDS` `:108`).
- `sleep_start_hour` / `sleep_end_hour` → **REUSED** — already on the engine
  (`presence.py:436-437`), reachable via `self._inference_engine`.
- `census_count` → **REUSED** — `self._census_count` (`presence.py:635`), property
  at `:724`.

### Prior planning docs consulted

- `PLANNING_v4.7.15_*` (D3 = the WAKING/GUEST sustained-signal gates this hotfix
  repairs) — skimmed; D3 intent = "a single 03:24 Frigate blip cannot flip
  WAKING." We preserve that intent (see §Fan-noise interaction).
- `PLANNING_v4.7.16_*` (D4 = `CONF_DISABLE_CAMERA_PRESENCE`) — confirmed the
  camera opt-out is *not* the cause; it only skips zone-camera registration
  (`presence.py:1597-1607`) and does not touch census or the wake gate.

### Memory bodies pulled

- `project_v4_7_18_dpm_drift_guard_planned.md` (current live tip context).
- Feedback: `feedback_fix_lows_in_cycle`, `feedback_pre_deploy_zero_bugs_gate`,
  `feedback_no_soak`.

### Design docs

- No `docs/Coordinator/Presence.md` exists; presence logic is the source of truth.

---

## Problem statement

When the house is asleep and at least one tracked person remains home all
morning (`census_count > 0`), the house can never leave `SLEEP`:

- AWAY is (correctly) blocked because someone is provably home.
- WAKING is (incorrectly) blocked because the sustained-occupancy gate reads the
  SLEEP-override-masked `mode`, which can never report `OCCUPIED` during sleep —
  so the wake timer never starts and the veto fires indefinitely.

Net: HVAC, lighting, and every house-state-driven behavior stays in sleep policy
into the afternoon.

---

## D1 — Option A: raw-signal wake timer (root cause)

Make the WAKING sustained-occupancy timer observe **real** sensor tiers,
bypassing the SLEEP override. The gate's entire purpose is to detect movement
*during* sleep; reading the sleep-masked `mode` is self-defeating.

**Changes (`presence.py`):**

1. Add to `ZonePresenceTracker`:
   ```python
   @property
   def raw_occupied(self) -> bool:
       """Occupancy from raw sensor tiers, IGNORING any mode override.
       The WAKING gate must see real movement during sleep, which the
       SLEEP-override-masked `mode` cannot surface. (v4.7.18.1)"""
       return self._derived_mode == ZonePresenceMode.OCCUPIED
   ```
2. In the inference cycle (`presence.py:2524`), add a parallel local and re-source
   the wake timer from it (leave `any_zone_occupied` untouched):
   ```python
   any_zone_raw_occupied = any(
       t.raw_occupied for t in self._zone_trackers.values()
   )
   if any_zone_raw_occupied:
       if self._first_positive_zone_occupied_since is None:
           self._first_positive_zone_occupied_since = _now_utc
   else:
       self._first_positive_zone_occupied_since = None
   ```

### Fan-noise interaction (DESIGN NOTE — preserves v4.7.15 D3 intent)

Re-sourcing from raw mmwave reintroduces the risk D3 guarded against (noise
flipping WAKING). Two structural facts contain it:

1. **The engine only proposes WAKING *after* `sleep_end_hour`** (`presence.py:522-532`):
   during sleep hours it returns SLEEP/None, so the gate never runs mid-night.
   A fan firing mmwave at 03:24 cannot wake the house — the gate isn't consulted.
2. **The 90s sustained threshold still applies** — a brief mmwave blip that
   clears resets `_first_positive_zone_occupied_since` to `None`.

Residual: a fan running continuously could hold raw mmwave True so that at
`sleep_end_hour` the gate passes immediately (eager 6 AM wake even if everyone is
still asleep). This is **strictly better than the all-day deadlock** and is a
*latency/eagerness* concern, not a correctness one. Hardening mmwave against fan
false-positives (sensor fusion / zone masking) is tracked as a **separate
side-quest** (see §Deferred) and is out of scope for this hotfix.

### Acceptance Criteria — D1
- **Verify:** With house `SLEEP`, a zone tracker whose `_room_occupied` is True
  (mmwave) reports `raw_occupied == True` even though `mode == "sleep"`.
- **Verify:** After ≥90s of sustained `any_zone_raw_occupied`, a proposed
  SLEEP→WAKING is NOT vetoed.
- **Verify:** A single-tick raw blip (True→False) does not accumulate sustained
  seconds (`_first_positive_zone_occupied_since` resets to None).
- **Test:** `test_v47181_raw_occupied_bypasses_sleep_override`,
  `test_v47181_wake_timer_uses_raw_signal`,
  `test_v47181_wake_blip_resets_timer`.
- **Live:** see consolidated "Live Validation" section at the bottom of this
  doc — D1 is proven primarily by the unit-test suite; organic live
  confirmation arrives at the next natural night→morning cycle.

---

## D2 — Option B: daytime wake backstop (safety valve)

If the house remains `SLEEP` well past `sleep_end_hour` while people are provably
home, force the wake — defending against any future masking regression that could
re-trap the house. This is a **late** backstop, not a normal wake path, so it
does not undermine D3's "require real movement at sleep-end" intent.

**Changes (`presence.py`):**

1. Module const:
   ```python
   _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END = 3  # hrs past sleep_end before forcing wake
   ```
2. Counter on coordinator init (next to `_wake_blocked_ticks` @ `:658`):
   ```python
   self._wake_backstop_fires: int = 0
   ```
3. In the WAKING gate (`presence.py:2845`, inside `if wake_decision.fired:`),
   check the backstop BEFORE suppressing:
   ```python
   if wake_decision.fired:
       engine = self._inference_engine
       _local_hour = dt_util.now().hour
       _backstop_hour = engine.sleep_end_hour + _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END
       # Daytime window only; assumes overnight sleep (sleep_end < sleep_start).
       _backstop = (
           self._census_count > 0
           and _backstop_hour <= _local_hour < engine.sleep_start_hour
       )
       if _backstop:
           self._wake_backstop_fires += 1
           _LOGGER.warning(
               "v4.7.18.1: WAKING backstop fired — SLEEP past %02d:00 with "
               "census_count=%d; forcing wake despite insufficient sustained "
               "signal (%s)",
               _backstop_hour, self._census_count, wake_decision.reason,
           )
           # fall through WITHOUT suppressing — allow the WAKING transition
       else:
           self._wake_blocked_ticks += 1
           _LOGGER.debug("v4.7.15 D3: WAKING transition blocked — %s",
                         wake_decision.reason)
           new_state = None
   ```
4. Surface the counter (`sensor.py`, next to `wake_blocked_ticks` @ `:3852`):
   ```python
   attrs["wake_backstop_fires"] = getattr(presence, "_wake_backstop_fires", 0)
   ```

**Edge note:** condition assumes overnight sleep (`sleep_end_hour <
sleep_start_hour`, the shipped default 6/23). If a future config sets a daytime
sleep window the simple hour-window would need revisiting — documented, not
handled (single-install, no such config exists; per `single-user-no-backcompat`).

### Acceptance Criteria — D2
- **Verify:** House `SLEEP`, `census_count > 0`, local hour ≥ `sleep_end_hour+3`
  and < `sleep_start_hour`, sustained signal insufficient → WAKING is allowed
  (not suppressed) and `_wake_backstop_fires` increments.
- **Verify:** Same conditions but `census_count == 0` → backstop does NOT fire
  (AWAY path owns that case).
- **Verify:** Hour just after `sleep_end_hour` (< +3h) with insufficient signal →
  backstop does NOT fire; normal veto still suppresses (D3 intent preserved).
- **Test:** `test_v47181_backstop_fires_when_stuck_past_margin`,
  `test_v47181_backstop_skips_when_nobody_home`,
  `test_v47181_backstop_not_eager_at_sleep_end`.
- **Live:** see consolidated "Live Validation" section below.

---

## Out of scope / Deferred

- **mmwave fan-noise rejection** (sensor fusion: discount fan-only mmwave lacking
  PIR/door/BLE/camera corroboration, esp. when fan entity `== on`; + coordinate
  zone-masking on positioning radars). Researched 2026-06-03 — **future cycle**,
  not this hotfix. Would also reduce the eager-6 AM-wake residual from D1.
- **Census honoring `CONF_DISABLE_CAMERA_PRESENCE`** — open question (a room
  flagged for camera false-positives still feeds census identity). Separate
  decision, not part of this deadlock fix.
- No new config knobs (per `configurability-clarity` + single-install).

## Test plan
`PYTHONPATH=quality python3 -m pytest quality/tests/ -v` — full suite green +
new `test_v47181_*` cases. Pre-deploy zero-bugs gate (conflict-marker grep +
py_compile presence.py/sensor.py + cycle tests + suite baseline diff).

## Live Validation (REWRITTEN per Reviewer B B-CRIT-1)

**Why the original "restart HA and watch the stuck SLEEP wake" plan was
invalid.** `HouseStateMachine` does NOT persist `_state` across restart —
`manager.py:143` constructs a fresh machine, `house_state.py:111`
initializes to `HouseState.AWAY`, and only `_transitions_today` is
hydrated from `house_state_log` at `presence.py:1158-1173`. So restarting
HA while the house is "stuck in SLEEP" resets the reported state to AWAY,
then walks ARRIVING → HOME_DAY via normal inference. The deadlock the
fix targets cannot be reproduced by restart-during-the-day — the test
would have produced "house woke" regardless of whether D1/D2 even shipped.

**The correct validation plan:**

(a) **Primary proof — unit tests.** The 26 cases in
`quality/tests/test_v47181_sleep_wake_deadlock.py` pin the D1 raw-signal
wake-timer wiring, the D2 backstop hour-window predicate, the override
bypass for `raw_occupied`, the sensor surface for `wake_backstop_fires`,
and the post-fix-up boot-ordering seed + clamp behaviors. These tests
exercise PRODUCTION code paths (real `ZonePresenceTracker`) and
source-grep + AST-pin the wake-gate branch wiring inside `_run_inference`.

(b) **Organic live confirmation — next natural night→morning cycle.**
After deploy, at the next natural cycle where a tracked person remains
home in the morning:

- `sensor.ura_presence_coordinator_presence_house_state` leaves SLEEP
  shortly after `sleep_end_hour` (organic D1 raw-timer wake) OR by
  `sleep_end_hour + 3` at the latest (D2 backstop wake).
- `wake_blocked_ticks` STOPS climbing after the WAKING transition lands
  (was at 4666 and rising in the incident; should plateau or reset
  across the next sleep cycle).
- `wake_backstop_fires` REMAINS 0 if D1 woke the house organically
  (the desired path); increments by 1 if D2 was needed (the safety
  valve fired — investigate why D1 didn't, but the house is unstuck).

(c) **Gotcha — the `set_house_state` service injects an OVERRIDE that
pins the reported state.** The service handler at `__init__.py:3060+`
calls `manager.house_state_machine.set_override(HouseState(state))`,
which sets `_override` on the state machine. The `state` property at
`house_state.py:122-127` returns `_override if set else _state`, so the
override pins the REPORTED state. Internal `transition(WAKING)` calls
update `_state` from SLEEP to WAKING — `_wake_backstop_fires` increments
and `house_state_log` records the transition — but `sensor.ura_presence_
coordinator_presence_house_state` continues to read "sleep" because the
override pin still wins. **This means `set_house_state: sleep` does NOT
cleanly demo the inference-driven wake.** Operator must `clear_override`
(or use `state: auto` if the service supports it) to see the sensor flip.
Documented so no one mistakes the override-pin behavior for a fix
failure.

(d) **Documented limitation — restart resets house_state.** As above,
`HouseStateMachine` has no persistence. A restart resets to AWAY and
re-derives via inference. Adding `RestoreEntity` persistence to the
state machine is a separate concern (candidate "Restorability Gap"
bug class per Reviewer B); out of scope for this hotfix.

## Files touched
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  (raw_occupied property, raw wake timer, backstop, const, counter)
- `custom_components/universal_room_automation/sensor.py` (surface counter)
- `quality/tests/test_v47181_sleep_wake_deadlock.py` (NEW)
