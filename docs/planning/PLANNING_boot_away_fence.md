# PLANNING: Boot AWAY Fence (CENSUS-SHUTDOWN-AWAY-FENCE-1)

> **SUPERSEDED 2026-10-11 (overnight) pending a next-boot measurement.** Plan review returned PLAN-FIX-REQUIRED (docs/reviews/code-review/plan_review_boot_away_fence.md). The orchestrator confirmed CRITICAL-2: the URA DB house_state_log has no away row in 7 of the 8 "dirty" boots; those recorder rows came from the sensor fallback (sensor.py:5509-5510), not the state machine. Only the 10-03 stick is a real AWAY. Do not build from this doc. See card CENSUS-SHUTDOWN-AWAY-FENCE-1.

**Thread:** presence
**Card:** `CENSUS-SHUTDOWN-AWAY-FENCE-1`
**Tier (proposed):** Tier 2-DB elevated — see §Tier Classification.
**Status:** awaiting plan review (one adversarial pass per Tier 2+ rule).

## Evidence base (corrected 2026-10-11 via coordinator probes)

The original card body cited a 10-10 16:18:30Z `away` row as a boot
instance. That citation is **retracted**. Correct state of the evidence,
from read-only probes against the HA recorder:

- `homeassistant_start` events on 10-10 are 15:57:16Z and 19:50:28Z;
  16:18:30Z is ~21 min after boot. `census_snapshots` show
  `identified_persons` briefly empty in that hour, so the 16:18Z row is
  either a genuine (brief) departure or a mid-run census drop — **not a
  boot instance** — and must not be used to shape this fence.
- Recorder retention currently starts 2026-10-03 21:01Z (so the "18 of
  21 boots in 30 days" claim on the card body cannot be re-verified at
  this moment of writing — only the 16 boots since 10-03 can).
- Coordinator-run probe over the 16 boots since 10-03 (recorder
  `homeassistant_start`/`homeassistant_stop` + states for
  `sensor.ura_presence_coordinator_presence_house_state`, 30 s rows;
  offsets are minutes relative to `homeassistant_start`; the stop event
  precedes the start event by 3.5–20 min):

| Boot (`homeassistant_start`, UTC) | Observation | Classification |
|---|---|---|
| 10-03 21:01Z | `away` at -3.2, remained AWAY ~62 min (the stuck case) | DIRTY (stuck) |
| 10-03 22:02Z | `away` -3.7 → `arriving` -2.6 → `home_day` -1.6 | DIRTY (transient) |
| 10-05 19:01Z | clean | CLEAN |
| 10-06 00:19Z | `away` -7.9 → `home_evening` -7.6 | DIRTY (transient) |
| 10-06 16:46Z | clean | CLEAN |
| 10-06 19:41Z | pre-state already away | AMBIGUOUS |
| 10-08 12:03Z | `away` at -21 (BEFORE the stop event) | GENUINE pre-stop AWAY — excluded |
| 10-08 17:29Z | `away` -4.6 → `home_day` -3.6 | DIRTY (transient) |
| 10-08 20:46Z | clean | CLEAN |
| 10-08 22:23Z | `away` -2.5 → `home_day` -1.4 | DIRTY (transient) |
| 10-09 12:54Z | clean (then `guest` → `home_day` +3.0) | CLEAN |
| 10-09 13:17Z | `away` -3.3 → `home_day` -3.0 | DIRTY (transient) |
| 10-09 14:37Z | from GUEST: `away` -4.3 → `guest` -3.7 | DIRTY (transient) |
| 10-09 16:27Z | `away` -3.5 → `home_day` -3.2 | DIRTY (transient) |
| 10-10 15:57Z | clean (loads v5.103.48) | CLEAN |
| 10-10 19:50Z | clean (loads v5.103.49) | CLEAN |

Unambiguous denominator = 14 boots (excluding one ambiguous and one
genuine pre-stop AWAY). **8 of 14 unambiguous boots exhibited a
boot-window AWAY**, typically landing 0.3–1 min BEFORE the recorder's
`homeassistant_start` event — i.e. **inside URA's `async_setup` window,
before HA reports started**. One of the eight (10-03 21:01Z) stuck
for ~62 min.

**Last dirty boot: 10-09 16:27Z. The two subsequent boots
(10-10 15:57Z = v5.103.48, 10-10 19:50Z = v5.103.49) were clean. 2 of 2
clean boots is WEAK evidence of a fix** — expected clean rate under the
observed 8/14 base rate is `(6/14)^2 ≈ 18%`, so 2 clean is not yet
distinguishing. The defect is **treated as still-real** for this plan;
candidate "incidentally fixed by" cycles to be re-checked at the next
boot are: census inputs-first D1 (v5.103.39), name-dedup (v5.103.47),
RESTORE-UNAVAILABLE-OFF-SWEEP-1, and the shutdown DB fast-fail (v5.103.49).

The 62-min stick on 10-03 remains the headline risk: a boot into AWAY
followed by cooldown-suppressed ARRIVING attempts can trap an occupied
house in AWAY long enough to drive HVAC/security actuation.

---

## Institutional context verified

### Design docs read
- `docs/VISION_v7.md`, `docs/ROADMAP_v11.md` — architecture + 6.0.0
  identity-driven autonomy gate.
- `docs/Coordinator/PRESENCE_COORDINATOR.md` — inference engine
  responsibilities; path-α / path-β veto ladder.
- `docs/Coordinator/HOUSE_MANUAL.md` — house-state machine, override
  surface, dispatch contract.
- `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` — census producer
  (interior_count, face_recognized_count, camera_input_dark key),
  SIGNAL_CENSUS_UPDATED payload shape.
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (complete; per
  CLAUDE.md 5b) — §house-state consumer: HVAC reads
  SIGNAL_HOUSE_STATE_CHANGED to re-pick presets; §10 corrections ledger
  reviewed, no claim here conflicts.
- `docs/QUALITY_CONTEXT.md` — relevant classes: #22 enum, #23 observation
  gating, #19 untracked tasks, suppression-discharge discipline
  (`feedback_suppression_needs_discharge`).
- `docs/reviews/URA_CODE_TRACING_METHODOLOGY.md`,
  `docs/reviews/URA_ARCHITECTURE_MAP.md` — scope: house-level value,
  consumers span HVAC + security + music_following + sensor +
  hvac_override + routine_forecaster + __init__ bayesian listener.

### Prior planning docs consulted
- `docs/planning/AUDIT_census_subsystem_2026_10_04.md` R5 (the card's
  origin) — "Trace and fence the shutdown-window AWAY".
- `AUDIT_census_footage_ground_truth_2026_10_03.md` — ground-truth
  frame for the 10-03 incident.
- `project_session_pickup_2026_10_04` memo + overnight 10-10 kanban
  notes.
- Cycle precedent: v5.7.0 WS-A path-β LOST veto + grace +
  `sustained_external_empty` — exemplar of a multi-tick empty
  discriminator.

### Memory bodies pulled
- `feedback_no_restart_during_sleep` — restart drops Sleep → zones flip
  to Home (same restart-driven house-state hazard class).
- `feedback_suppression_needs_discharge` — any defer/grace needs
  explicit re-fire + backstop + restart story.
- `feedback_config_first_before_code` — step 1b gate.
- `feedback_hollow_test_anchors` — mutation drill required.
- `feedback_falsify_before_asserting`, `feedback_verify_claim_types`.

### Prior-art scan (REUSE-or-BUILD per piece, file:line)

| Piece | Verdict | Site |
|---|---|---|
| Boot-settle gate (self-release on real input / HA started / timeout) | **REUSE** | `presence.py:5638-5647` (predicate A), `presence.py:2497-2520` (predicates B1/B2), `const.py:3784` `BOOT_SETTLE_TIMEOUT_SECONDS=60`, `const.py:3789` `BOOT_SETTLE_MIN_INPUTS=1` |
| Transition deferral during boot (R2-2) | **REUSE + EXTEND** | call site `presence.py:6818-6833`; predicate `presence.py:2331-2343`; reconcile tick `presence.py:2345-2443` |
| House-state restore (`_boot_restore_active`) | **REUSE** | `house_state.py:365-440`; constants `HOUSE_STATE_RESTORE_MAX_STALE_S=1800`, `HOUSE_STATE_HEARTBEAT_S=300` at `house_state.py:35-38` |
| Restore invocation ordering | **REUSE (anchor)** | `manager.py:670-701` `_async_restore_house_state` |
| Sustained-empty discriminator (multi-tick + indoor-clear debounce) | **REUSE PATTERN** | `presence.py:1217-1244` `sustained_external_empty`; `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS` |
| `SIGNAL_CENSUS_UPDATED` payload + `camera_input_dark` key | **REUSE** | `_handle_census_update` `presence.py:4612`; plumbing `presence.py:6384-6388` |
| Fleet-dark gate (skip path α on dark fleet) | **REUSE PATTERN** | `presence.py:1156-1178`, `camera_input_degraded` kwarg |
| Arriving re-arm cooldown | **REUSE** | `presence.py:6780-6816`; bypass predicate `presence.py:5519-5543` |
| Dispatch helper (D3/D7 writers hoisted v5.103.27) | **REUSE** | `_dispatch_house_state_change`; call site `presence.py:6911-6918` |

**Build (new):** one additional precondition on the Nobody-home branch
(`presence.py:1124`) and on both AWAY-emitting veto paths
(`presence.py:1167-1178`, `1245-…`): a **boot-settle-is-up fence** that
refuses to emit AWAY when the current (restored OR default) state is
home-like, until either (a) the gate has released on real input *and*
`CONF_BOOT_AWAY_WARMUP_TICKS` post-release ticks have passed, or
(b) a measured empty-house discriminator has fired. No new signal, no
new DB table.

### Code locations surveyed end-to-end
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  (inference engine, `_run_inference`, boot-settle release/deferral,
  AWAY emission sites)
- `.../domain_coordinators/house_state.py` (restore, heartbeat/stale
  constants, override restore)
- `.../domain_coordinators/manager.py` (restore invocation + ordering)
- `.../domain_coordinators/signals.py` (`SIGNAL_HOUSE_STATE_CHANGED`,
  payload shape)
- Consumer sites listed in §Consumer check below.

---

## Pinned mechanism (proven in source) vs hypothesis

### Proven in source
1. **Nobody-home short-circuit fires before any veto.**
   `presence.py:1124-1128` — the FIRST clause of `infer()` is
   `if census_count == 0 and not any_zone_occupied: return
   HouseState.AWAY` at confidence 0.9. It runs ahead of path α, path β,
   GUEST, and SLEEP. Any upstream guard must sit *outside* this branch.
2. **The boot-settle gate does NOT, by itself, suppress inference AWAY.**
   `presence.py:5638-5647` only *releases* the gate; `_run_inference`
   continues to run inference on every tick while `_boot_settle_done`
   is False. The gate's practical effect comes from the deferral at
   `presence.py:6825` which only engages when
   `_boot_settle_done is False` **AND**
   `machine.boot_restore_active is True`
   (`presence.py:2331-2343`).
3. **The deferral is conditional on a successful in-window restore.**
   `house_state.py:383-429`: `_boot_restore_active` is set True **only**
   when `apply_restored` succeeds within `max_stale_s=1800`. It returns
   `False` for `no_record`, `missing_field`, `stale`, `clock_skew`,
   `corrupt:*`. Heartbeat is `HOUSE_STATE_HEARTBEAT_S=300`
   (`house_state.py:38`). Combined with the ~3.5-20 min stop→start
   gap observed in the probe, any boot where the record is missing,
   >30 min stale, or corrupt leaves `_boot_restore_active=False` → the
   deferral is a no-op.
4. **Restore ordering is an independent risk.** `manager.py:670-701`
   `_async_restore_house_state` is awaited during coordinator setup;
   inference ticks that fire before this await completes (e.g. a
   `SIGNAL_CENSUS_UPDATED` or motion-source change arriving during
   setup) will see `_boot_restore_active=False` even if the record is
   fresh — the flag has not been written yet. The 10-11 probe shows
   **AWAY rows landing 0.3–1 min BEFORE the recorder's
   `homeassistant_start` event**, i.e. during `async_setup`, consistent
   with this ordering hazard.
5. **BOOT_SETTLE_MIN_INPUTS=1.** Predicate A releases the gate on
   `census_count>=1` OR any zone tracker OCCUPIED. On a cold boot where
   the FIRST input to arrive is a `census_update` with `interior_count=0`
   (camera pipeline / Frigate2 / face recogniser still warming), the
   gate stays up but the tick still runs — and if `boot_restore_active`
   is also False (per 3 or 4), the Nobody-home branch wins.
6. **AWAY→HOME re-exit is throttled by `ARRIVING_REARM_COOLDOWN`.**
   `presence.py:6780-6816`: once AWAY is accepted and an
   ARRIVING→AWAY collapse arms the cooldown, outdoor-only motion is
   suppressed until real indoor evidence (`_arriving_rearm_bypass` at
   `presence.py:5519-5543`) materialises. This is the proven mechanism
   that explains the **62-min stick on 2026-10-03 21:01Z** — once a
   boot AWAY lands, re-exit is gated on indoor tier1, and outdoor-only
   motion from the party kept rearming the cooldown.
7. **Every path that can set AWAY inside `infer()` (grep-verified):**
   - `presence.py:1124-1128` Nobody-home.
   - `presence.py:1167-1178` path α — ACTIVE-only tracker veto.
   - `presence.py:1245+` path β — LOST-admitted veto (already carries
     grace + `sustained_external_empty`; the boot fence must be ADDED
     to the immediate-engage limb at `1241-1244`).

   No other `return HouseState.AWAY` statements in `infer()`. Other
   `HouseState.AWAY` references in `presence.py` (`6417, 6496, 6781,
   6851, 6871`) and `sensor.py:7891` are read-only branches, not
   writers. The reviewer MUST independently re-grep this enumeration.

### Not yet proven (what the next-boot probe must falsify)
Which of {restore-returned-False (3), restore-not-yet-run (4),
predicate-A-released-with-dark-inputs (5)} dominates in production.
The three cases converge on the same code path and the same fence
closes all three, but telling them apart matters for whether cycles
v5.103.47-49 incidentally fixed the hazard. The D0 probe below is the
discriminator.

---

## Producer and consumer checks

### Producers
| Value | Producer | Boot behaviour |
|---|---|---|
| `census_count` | `camera_census.py` → `SIGNAL_CENSUS_UPDATED { interior_count, ... }`; written by `_handle_census_update` `presence.py:4612-4680` | Empty for seconds-to-minutes while face/BLE pipelines warm. |
| `any_zone_occupied` / `any_indoor_zone_occupied` | Zone trackers rolled up at `presence.py:5848-5862` | IDLE until underlying motion/mmWave sources fire post-boot. |
| `all_tracked_persons_away` | Person coordinator roll-up | `person.*` may be `unknown`/`not_home` while BLE/GPS reconverges. |
| `_boot_restore_active` | `house_state.py:383-428` | True **only** on in-window restore AFTER `_async_restore_house_state` awaits. Writer cadence `HOUSE_STATE_HEARTBEAT_S=300`. |
| `camera_input_dark` → `camera_input_degraded` | `camera_census.py` → `SIGNAL_CENSUS_UPDATED` key; `presence.py:6384-6388` | Gates path α today; does NOT gate the Nobody-home branch. |

Every producer is legitimately empty/False for part of the boot window.
This is the window the fence must span.

### Consumers of the AWAY transition (SIGNAL_HOUSE_STATE_CHANGED + `house_state_log`)
| Consumer | File:line | Trust vs display | Blast radius if false AWAY |
|---|---|---|---|
| HVAC preset re-pick | `coordinator.py:1722`; HVAC listener in `hvac.py`; override `hvac_override.py:942` | **Trust** — drives preset + setpoints | HIGH — AC/heat ramps away in occupied house |
| Security coordinator | `security.py` SIGNAL_HOUSE_STATE_CHANGED listener | **Trust** — arming | HIGH |
| Music following | `music_following.py:149,299`, `domain_coordinators/music_following.py:42` | **Trust** — pauses | MED |
| NM / bayesian guest listener | `__init__.py:2973-2989` | Display | LOW |
| Routine forecaster incremental update | `routine_forecaster.py:14,57,188` | Trust (model input) | MED |
| Sensors (next-state, veto-path) | `sensor.py:6490, 10222` | Display | LOW |
| Switch surface listeners | `switch.py:3511` | Display/feature-flag | LOW |
| DB writer: `house_state_log` row | `database.py` via hoisted `_dispatch_house_state_change` (v5.103.27 A-HIGH-1); call site `presence.py:6911-6918` | Audit | LOW (but this is the Live oracle) |

Trust-hierarchy ripple across HVAC + security + music justifies Tier 2-DB.

---

## Config-first check

Is there an existing operator-settable knob that already fences this?

- `BOOT_SETTLE_TIMEOUT_SECONDS=60` (`const.py:3784`) — module constant,
  no Number/Options surface. Governs only how long the gate stays up;
  does NOT by itself suppress AWAY emission.
- `BOOT_SETTLE_MIN_INPUTS=1` (`const.py:3789`) — already minimum.
- `HOUSE_STATE_RESTORE_MAX_STALE_S=1800` (`house_state.py:35`) —
  lifting this masks the stale case rather than fencing it, and risks
  restoring genuinely-wrong state. Not the right knob.
- `HOUSE_STATE_HEARTBEAT_S=300` — lowering helps edge cases but does
  not close the ordering window.
- `CONF_LOST_AWAY_GRACE_MIN`, `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS`,
  `CONF_LOST_AWAY_SLEEP_EXEMPT` — path-β only; do not gate Nobody-home.

**Verdict: no live knob fixes this.** CLAUDE.md 1b config-first gate
satisfied — code change required.

---

## Falsifiable invariant

**I-BAF-1 (primary).** Within the boot-settle window AND for an
operator-configurable *additional* post-settle warm-up window
`CONF_BOOT_AWAY_WARMUP_TICKS` (default **3**), when the current state
(restored OR default) is any of `{HOME_DAY, HOME_EVENING, HOME_NIGHT,
SLEEP, WAKING, GUEST, ARRIVING}`, no inference-driven transition to
`HouseState.AWAY` occurs on **any reachable path** inside `infer()`.
A transition to AWAY after the warm-up requires one of:
(a) `sustained_external_empty` True (N consecutive ticks of `census==0
AND unidentified==0 AND _indoor_clear_debounced`), or
(b) `all_tracked_persons_away AND unidentified_count==0 AND
face_recognized_count==0 AND not camera_input_degraded` holding for N
consecutive post-settle ticks.

**I-BAF-2 (restart-discharge).** The warm-up window is bounded and
monotonically releases. It cannot be held open indefinitely by a stuck
producer; it releases after `max(BOOT_SETTLE_TIMEOUT_SECONDS,
CONF_BOOT_AWAY_WARMUP_TICKS × tick_period, BOOT_AWAY_FENCE_BACKSTOP)`
even if no evidence arrives. Backstop mirrors
`presence.py:2302-2308`.

**Discriminating observation.** After the fix, a boot into an occupied
house produces a `house_state_log` whose first post-boot row is NOT
`away` AND whose structured log reads
`Boot-away fence: SUPPRESSED Nobody-home AWAY (warmup_ticks=k/N
census=0 any_zone_occupied=False restored=home_day)`. A boot into a
genuinely empty house still produces an `away` row — but no earlier
than N ticks after settle AND with trigger
`sustained_external_empty`, not `census_update`. The two
observations discriminate "fence works" from "fence over-fires".

---

## Suppression needs discharge

- **Re-fire.** Every `_run_inference` tick re-evaluates the fence.
  The warm-up counter decrements once per tick on which inputs STILL
  point at AWAY. On any intervening tick where inputs disagree (census
  >0, any zone OCCUPIED, or a tracker reports home), the fence
  releases immediately. The deferred retry path (`presence.py` existing
  retry machinery) continues to drive subsequent ticks.
- **Backstop.** The existing `BOOT_SETTLE_TIMEOUT_SECONDS=60`
  `async_call_later` (`presence.py:2512-2518`) caps the gate. We add a
  second independent wall-clock backstop
  `BOOT_AWAY_FENCE_BACKSTOP = 3 × BOOT_SETTLE_TIMEOUT_SECONDS = 180s`
  so a stuck tick scheduler cannot freeze the house into non-AWAY
  forever.
- **Restart.** The fence state is pure in-process (counter + monotonic
  deadline). Any restart re-enters the fence at setup by construction;
  no persistence needed. The persisted artefact is the house state
  itself.

---

## Numbers get knobs

| Number | Name | Rung | Why |
|---|---|---|---|
| Post-settle warm-up ticks | `CONF_BOOT_AWAY_WARMUP_TICKS` (default **3**) | **Options flow** | Mirrors `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS`; per-deployment, infrequent. |
| Wall-clock backstop multiplier | `BOOT_AWAY_FENCE_BACKSTOP_MULTIPLIER = 3` | **Module constant** (safety bound) | Change implies the base gate is wrong; wants review. |
| Kill switch | `CONF_BOOT_AWAY_FENCE_ENABLED` (default **True**) | **Options flow** | False restores v5.103.50 behaviour byte-identically. |

Labels per `feedback_label_style_guide` — short phrase, no "hysteresis"
or "debounce": *"Hold off AWAY after restart"* (bool), *"Extra ticks of
boot warm-up"* (int).

---

## Deliverables

### D0: Next-boot discriminator probe (MANDATORY before build)
Because 2/2 clean boots since 10-09 16:27Z is not yet statistically
distinguishing, D0 is **a next-boot read-only probe** that labels the
mechanism (if the defect re-fires) OR corroborates that one of
{v5.103.39, v5.103.47, RESTORE-UNAVAILABLE-OFF-SWEEP-1, v5.103.49}
incidentally closed it.

Per boot, record:
1. Journald lines from the URA integration: `House-state restore: ...
   (reason=X age_s=Y)` from `manager.py:684-700` → labels the restore
   outcome (ok / stale / no_record / clock_skew / corrupt / missing).
2. `Boot-settle: released via <reason>` from `_release_boot_settle`
   `presence.py:2302-2313` → labels the gate release path (real_input /
   ha_started / timeout).
3. `Boot-settle reconciliation: boot_restore_<diverged|confirmed>`
   from `_boot_settle_reconciliation_tick` `presence.py:2405-2416`.
4. First `house_state_log` row (via URA DB) within 5 min of boot: time,
   `old`, `new`, `trigger`, `confidence`.
5. Matching `census_snapshots` rows for the boot minute.

**Acceptance for D0:**
- If 5+ consecutive boots are clean, raise this plan to parked status
  with a code trip-wire (NM-wired anomaly `boot_away_within_settle`
  that counts the exact predicate inside `_run_inference`), close the
  card as "met with residual trip-wire", and card the trip-wire. Do
  NOT delete the card without a trip-wire — 8/14 base rate is real.
- If any boot re-fires the defect, labels (1)–(3) tell us which
  mechanism dominates and the fence (D1–D5) proceeds as specified.
- Either outcome is a legitimate exit; this is the measure-before-build
  gate per CLAUDE.md.

### D1: Fence the Nobody-home branch (`presence.py:1124`)
Wrap in: *if `current_state` is non-AWAY home-like AND `fence_active`,
do not return AWAY — emit a structured
`Boot-away fence: SUPPRESSED` log, increment a diagnostic counter,
return `None` (keep current state)*.

```python
fence_active = (
    self._boot_away_fence_enabled
    and (
        not self._boot_settle_done
        or self._post_settle_warmup_ticks_remaining > 0
    )
    and time.monotonic() < self._boot_away_fence_backstop_deadline
)
```

#### Acceptance Criteria
- **Verify:** cold boot into an occupied house → Nobody-home branch
  does not transition to AWAY in the first
  `CONF_BOOT_AWAY_WARMUP_TICKS` post-settle ticks.
- **Sensor:** new `sensor.ura_presence_boot_away_fence_suppressions`
  (total_increasing) increments on every suppression.
- **Test:** `test_boot_away_fence_suppresses_nobody_home_on_cold_boot`
  (unit) + mutation drill — deleting the fence predicate causes a
  specific behavioural test to fail (CLAUDE.md hollow-anchors rule).
- **Live:** post-restart, within 5 min, `house_state_log` shows NO
  `away` row with `trigger IN ('census_update', 'camera_detection',
  'occupancy_change')` while matching `census_snapshots` show
  identified residents. **Discriminator** (per
  `feedback_cross_investigation_synthesis`): a *genuinely* empty house
  still produces an `away` row, but with `trigger =
  sustained_external_empty` and at least N ticks after settle.

### D2: Fence paths α and β (`presence.py:1167-1178`, `1245+`)
Same `fence_active` predicate added to both veto paths. Path β's
`sustained_external_empty` + grace is NOT weakened — only ADDed.

#### Acceptance Criteria
- **Verify:** path α cannot force AWAY during the fence window.
- **Verify:** path β's immediate-engage limb cannot force AWAY during
  the fence window.
- **Test:** two unit tests, one per path, with mutation points
  individually drilled.

### D3: Warm-up counter + backstop deadline
Initialise `_post_settle_warmup_ticks_remaining =
CONF_BOOT_AWAY_WARMUP_TICKS` at settle release; decrement once per
`_run_inference` tick on which inputs still point AWAY; clear on first
disagreement.

#### Acceptance Criteria
- **Verify:** counter decrements, reaches 0, fence releases.
- **Verify:** wall-clock backstop fires at
  `BOOT_AWAY_FENCE_BACKSTOP_MULTIPLIER × BOOT_SETTLE_TIMEOUT_SECONDS`
  (default 180 s) under simulated stalled scheduler.

### D4: Options-flow fields + kill switch
Add `CONF_BOOT_AWAY_FENCE_ENABLED` (bool, default True) and
`CONF_BOOT_AWAY_WARMUP_TICKS` (int, default 3) to the options flow.

#### Acceptance Criteria
- **Verify:** options round-trip through flow + RestoreEntity.
- **Live:** kill switch → False restores exactly v5.103.50 behaviour
  (byte-identical fence-disabled branch).

### D5: Diagnostic observability
- `sensor.ura_presence_boot_away_fence_suppressions` (total_increasing).
- `sensor.ura_presence_boot_away_fence_last_release_reason` ∈
  `{warmup_elapsed, evidence_contradicted, backstop, disabled,
  not_cold_boot}`.
- NM anomaly `boot_away_fence_backstop_fired` — any backstop fire is a
  sev-2 operator signal (should never fire in normal operation).

#### Acceptance Criteria
- **Sensor:** both entities expose non-null state within one tick of
  settle release.
- **Live:** at the next restart, the release reason reported matches
  the manually-traced journal line.
- **Live:** no NM `boot_away_fence_backstop_fired` emission in the
  first week after ship.

---

## Tier classification

**Proposed: Tier 2-DB elevated (3 framing-disjoint reviews + live
validation).**

Justifications:
- **Cross-coordinator ripple:** presence → HVAC + security + music +
  routine forecaster — standing policy for regression-prone work
  (`feedback_tier2db_for_regression_prone`).
- **Shared primitive:** house-state inference is consumed by many
  dispatch sites.
- **Failure mode is "one missed emission site" (Bug Class #53):** three
  AWAY return sites must all be fenced in lockstep.

**Review framings (disjoint):**
- **A — correctness + edge cases per path.** Each of the three AWAY
  sites × {fence active, fence released, restored sleep/guest/arriving,
  override restore interaction}.
- **B — cross-coordinator + lifecycle + restart.** HVAC preset re-pick,
  security arming, music following, routine forecaster incremental
  update MUST be byte-identical when fence is DISABLED. Options-flow +
  RestoreEntity + reload path (gate born released, `presence.py:2482-2488`)
  + cold-boot (gate scheduled) all converge.
- **C — adversarial completeness + test authority.** Independently
  re-enumerate every `return HouseState.AWAY` and every call site that
  can CAUSE one. Mutation drill per site: deleting the fence predicate
  at site N must cause a site-N-specific behavioural test to fail
  (`feedback_hollow_test_anchors`). Hand-build fixture
  (`feedback_measure_before_build`): the recorder-probe table in
  §Evidence base above is committed as the acceptance oracle.

**Plan review (CLAUDE.md Tier 2+ plan review rule):** ONE adversarial
plan review before build dispatch. Reviewer MUST independently re-grep
the three AWAY emission sites (§Pinned mechanism point 7) and confirm
no fourth site exists.

---

## Non-goals
- Do NOT change `HOUSE_STATE_RESTORE_MAX_STALE_S` or
  `HOUSE_STATE_HEARTBEAT_S` — masks rather than fences.
- Do NOT remove the Nobody-home branch — legitimate empty-house AWAY
  must still fire after warm-up.
- Do NOT re-architect the R2-2 deferral — it stays as a parallel defence;
  the fence closes the stale-restore / pre-restore-ordering hole it
  does not cover.
- Do NOT add a new signal or DB table — diagnostics piggyback on
  existing sensor + NM patterns.

---

## Plan-completion tracking
On ship, record which of D0-D5 landed in the cycle README's Plan
Completion Tracking section with explicit reasons for any deferral.
D0's outcome dictates whether D1-D5 ship or the card closes with a
trip-wire; both outcomes are legitimate.
