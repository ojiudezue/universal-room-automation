# PLANNING: Boot AWAY Fence (CENSUS-SHUTDOWN-AWAY-FENCE-1)

**Thread:** presence
**Card:** `CENSUS-SHUTDOWN-AWAY-FENCE-1`
**Tier (proposed):** Tier 2-DB elevated — see §Tier Classification.
**Status:** awaiting plan review (one adversarial pass per Tier 2+ rule).

The house comes up as AWAY after ~18 of 21 restarts even when people are
home. On 2026-10-10 at 16:18:30Z (restart ~11:18 CDT, loading v5.103.47/48)
the URA DB `house_state_log` recorded `away` with `trigger=census_update`
within seconds of boot, then recovered via `arriving` and `home_day` after
~4 min. The 2026-10-03 incident stuck AWAY for ~62 min.

The symptom is systemic: cold-boot inference runs the Nobody-home branch
on the first census tick while every input is still empty, and the one
existing fence (R2-2 boot-restore deferral) does not cover the dominant
case — a stale persisted record.

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
  (feedback_suppression_needs_discharge).
- `docs/reviews/URA_CODE_TRACING_METHODOLOGY.md`,
  `docs/reviews/URA_ARCHITECTURE_MAP.md` — scope: house-level value,
  consumers span HVAC + security + music_following + sensor + hvac_override
  + routine_forecaster + __init__ bayesian guest listener.

### Prior planning docs consulted
- `docs/planning/AUDIT_census_subsystem_2026_10_04.md` R5 (the card's
  origin) — "Trace and fence the shutdown-window AWAY".
- `AUDIT_census_footage_ground_truth_2026_10_03.md` — ground-truth frame.
- `project_session_pickup_2026_10_04` memo + overnight 10-10 kanban note
  (card body, UNBLOCKED).
- Cycle precedent: v5.7.0 WS-A path-β LOST veto + grace +
  `sustained_external_empty` — exemplar of multi-tick empty discriminator.

### Memory bodies pulled
- `feedback_no_restart_during_sleep` — restart drops Sleep →
  zones flip to Home (same restart-driven house-state hazard class).
- `feedback_suppression_needs_discharge` — any defer/grace needs explicit
  re-fire + backstop + restart story.
- `feedback_config_first_before_code` — step 1b gate.
- `feedback_hollow_test_anchors` — mutation drill required.
- `feedback_coincidental_equality_masks_concept_split` — Bug Class #63.

### Prior-art scan (REUSE-or-BUILD per piece, with file:line)

| Piece | Verdict | Site |
|---|---|---|
| Boot-settle gate (self-release on real input / HA started / timeout) | **REUSE** | `presence.py:5638-5647` (predicate A), `presence.py:2497-2520` (predicates B1/B2), `const.py:3784` `BOOT_SETTLE_TIMEOUT_SECONDS=60`, `const.py:3789` `BOOT_SETTLE_MIN_INPUTS=1` |
| Transition deferral during boot (R2-2) | **REUSE + EXTEND** | `presence.py:6818-6833` (deferral call site), `presence.py:2331-2343` (`_should_defer_transition_for_boot_restore`), `presence.py:2345-2443` (`_boot_settle_reconciliation_tick`) |
| House-state restore (`_boot_restore_active`) | **REUSE** | `house_state.py:365-440`; constants `HOUSE_STATE_RESTORE_MAX_STALE_S=1800`, `HOUSE_STATE_HEARTBEAT_S=300` at `house_state.py:35-38` |
| Sustained-empty discriminator (multi-tick, carries indoor-clear debounce) | **REUSE PATTERN** | `presence.py:1217-1244` `sustained_external_empty`; CONF_LOST_AWAY_INDOOR_CLEAR_TICKS |
| `SIGNAL_CENSUS_UPDATED` payload with `camera_input_dark` | **REUSE** | `presence.py:4612` `_handle_census_update`; `presence.py:6384-6388` plumbing |
| Fleet-dark gate (skip path α when inputs are dark) | **REUSE PATTERN** | `presence.py:1156-1178`, `camera_input_degraded` kwarg |
| Arriving re-arm cooldown (post-AWAY) | **REUSE** | `presence.py:6780-6816`; `ARRIVING_REARM_COOLDOWN_S` |
| Dispatch helper + D3/D7 writers hoisted | **REUSE** | `_dispatch_house_state_change` (v5.103.27 A-HIGH-1); `presence.py:6911-6918` ref |

**Build (new):** one additional precondition on the Nobody-home branch
(`presence.py:1124`) and on both veto paths (`presence.py:1167-1178`,
`1245-...`): a **boot-settle-is-up fence** that refuses to EMIT an
inference that lands AWAY when the current (restored OR default) state is
a home-like state, until **either** (a) the gate has released on real
input, **or** (b) a measured empty-house discriminator has fired across
≥N consecutive ticks after settle release. No new signal, no new table.

### Code locations surveyed end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/presence.py` (inference engine, `_run_inference`, boot-settle release, deferral call site)
- `.../domain_coordinators/house_state.py` (restore, `_boot_restore_active`, heartbeat/stale constants, override restore)
- `.../domain_coordinators/manager.py:681-700` (restore invocation site)
- `.../domain_coordinators/signals.py` (`SIGNAL_HOUSE_STATE_CHANGED`, payload shape)
- Consumer sites listed in §Consumer check.

---

## Pinned mechanism (proven in source) vs hypothesis

### Proven in source
1. **Nobody-home short-circuit fires before any veto.**
   `presence.py:1124-1128` — the FIRST clause of `infer()` is
   `if census_count == 0 and not any_zone_occupied: return HouseState.AWAY`
   at confidence 0.9. It runs before path α, path β, GUEST, and SLEEP.
2. **The boot-settle gate does NOT suppress inference-driven AWAY on its own.**
   `presence.py:5638-5647` only *releases* the gate; `_run_inference`
   continues to run inference every tick while `_boot_settle_done` is
   False. The gate's practical effect comes from the deferral at
   `presence.py:6825` which only fires when
   `_boot_settle_done is False` **AND** `machine.boot_restore_active is True`
   (`presence.py:2337-2343`).
3. **The deferral is conditional on a successful in-window restore.**
   `house_state.py:383-429`: `_boot_restore_active` is set True **only**
   when `restore_from_dict` succeeds within `max_stale_s=1800`.
   Returns `("no_record"|"missing_field"|"stale"|"clock_skew"|"corrupt:*",
   False)` otherwise and leaves `_boot_restore_active=False`.
   Heartbeat is `HOUSE_STATE_HEARTBEAT_S=300` (`house_state.py:38`); the
   staleness horizon is 1800s. **Any HA downtime > 30 min — or a restart
   that straddles a missed heartbeat and a stale record — produces
   `_boot_restore_active=False` on restore, which turns the deferral
   into a no-op.**
4. **BOOT_SETTLE_MIN_INPUTS=1 (`const.py:3789`), BOOT_SETTLE_TIMEOUT_SECONDS=60
   (`const.py:3784`).** Predicate A releases on `census_count>=1` OR any
   zone tracker OCCUPIED. On a cold boot where census arrives with
   `interior_count=0` (camera pipeline not yet seen a frame, BLE not yet
   paired, Frigate 2 cold), the FIRST `census_update` trigger fires
   `_run_inference` with `_census_count=0`, `any_zone_occupied=False`,
   and either `_boot_restore_active=False` (stale restore) or True but
   with the deferral path only buying ONE tick before
   `_boot_settle_reconciliation_tick` (`presence.py:2345-2402`) clears
   the flag and re-runs inference. If inputs are still empty at that
   single reconciliation tick, the Nobody-home branch wins again and
   the dispatch label becomes `boot_restore_diverged`.
5. **AWAY→HOME re-exit is throttled by ARRIVING_REARM_COOLDOWN.**
   `presence.py:6780-6816` — once AWAY has been accepted and then an
   ARRIVING→AWAY collapse arms the cooldown, outdoor-only motion is
   suppressed until real indoor evidence (`_arriving_rearm_bypass` at
   `presence.py:5519-5543`) materialises. This is the proven mechanism
   by which a boot AWAY can stick for *tens of minutes* while the house
   is actually occupied but the first evidence to arrive is outdoor-only.
6. **Every path that can SET AWAY (grep of returns of `HouseState.AWAY`
   from `infer`):** `presence.py:1124-1128` (Nobody-home), `1167-1178`
   (path α — ACTIVE-only veto), `1245-1285` (path β — LOST-admitted veto;
   gated on indoor-clear + grace + sustained-external-empty + sleep
   exemption). No other emission sites in `infer()`. Dispatch sites
   outside `infer()` that cite AWAY (`presence.py:6417, 6496, 6781,
   6851, 6871`, `sensor.py:7891`) are read-only / conditional branches,
   not writers.

### Not yet proven (hypothesis for the probe to confirm)
- **10-10 (16:18:30Z, trigger=census_update, within ~70s of boot):**
  highest-probability path is (3) **restore returned `stale`** because
  the previous instance's last heartbeat was > 1800s before boot (the
  prior deploy sequence restarted HA twice within the window). The
  deferral was then a no-op and the first census_update tick that
  reached `_run_inference` ran the Nobody-home branch. The subsequent
  `arriving` at 16:22:50Z (`deferred_retry`) is consistent with the
  state machine's own retry path, not the R2-1 reconciliation tick.
- **10-03 (62-min stick):** AWAY accepted at boot per (1)+(3)+(4);
  ARRIVING→AWAY collapse armed the re-arm cooldown per (5); outdoor
  motion from the party on the covered patio (see
  `CENSUS-PATIO-THROUGH-GLASS-1`) was suppressed as `outdoor-only`
  until an indoor-tier1 trip finally bypassed the cooldown.

The planning probe (D0 below) MUST falsify or confirm (3)/(4) for 10-10
and (5) for 10-03 by reading `house_state_log` + the structured log for
`Boot-settle:` and `Boot-settle reconciliation:` lines, and reading the
corresponding `.storage/universal_room_automation.house_state` record's
`saved_at`.

---

## Producer and consumer checks

### Producers
| Value | Producer | Boot behaviour |
|---|---|---|
| `census_count` (= `_census_count`) | `camera_census.py` dispatches `SIGNAL_CENSUS_UPDATED` with `interior_count`; `_handle_census_update` at `presence.py:4612-4680` writes it. On cold boot the first census tick is empty until face/BLE pipelines warm (observed 2-60s). |
| `any_zone_occupied` / `any_indoor_zone_occupied` | Zone trackers aggregated at `presence.py:5848-5862`. Cold-boot: zone trackers are IDLE until their underlying motion/mmWave sources fire (observed up to tens of seconds post-boot while HA entities finish subscribing). |
| `all_tracked_persons_away` | Person coordinator roll-up. Cold-boot: person.* trackers may still be `unknown`/`not_home` while BLE/GPS re-converges. |
| `_boot_restore_active` | `house_state.py:383-428` set True on in-window restore ONLY. Writer `async_save` cadence = `HOUSE_STATE_HEARTBEAT_S=300`. |
| `camera_input_dark` | `camera_census.py` → `SIGNAL_CENSUS_UPDATED` key; mirrored into `self._census_camera_input_dark` and consumed as `camera_input_degraded` kwarg at `presence.py:6388` → gates path α. **Does NOT gate the Nobody-home branch today.** |

Producer dependency health at boot: all four input producers above are
plumbed through async setup. They can be legitimately `0 / False / dark`
for anywhere from a few seconds to tens of minutes (BLE re-pair,
Frigate-2 pipeline warm, camera entity rebuild). This is the window the
fence must span.

### Consumers of the AWAY transition (SIGNAL_HOUSE_STATE_CHANGED + `house_state_log`)

Grepped via `SIGNAL_HOUSE_STATE_CHANGED`:

| Consumer | File:line | Trust vs display | Blast radius if false AWAY |
|---|---|---|---|
| HVAC preset re-pick on house-state change | `coordinator.py:1722` (handler map), `hvac.py` house-state consumer, override logic at `hvac_override.py:942` | **Trust** — drives preset selection and setpoint shifts; AWAY preset shifts setpoints away from comfort band | HIGH — AC/heat may ramp away during an occupied house |
| Security coordinator | `security.py` SIGNAL_HOUSE_STATE_CHANGED listener | **Trust** — arming decisions | HIGH — can arm with people home |
| Music following (pause on AWAY) | `music_following.py:149, 299`, `domain_coordinators/music_following.py:42` | **Trust** — pauses output | MED — audible |
| Notification manager / bayesian guest listener | `__init__.py:2973-2989` | Display + feature-flagging | LOW — informational |
| Routine forecaster incremental update | `routine_forecaster.py:14,57,188` | Trust (model input) | MED — pollutes forecast |
| Sensors (next-state, veto-path, etc.) | `sensor.py:6490, 10222` | Display | LOW |
| Switch surface listeners | `switch.py:3511` | Display/feature flag | LOW |
| DB writer: `house_state_log` row | `database.py` via `_dispatch_house_state_change` hoisted hook (v5.103.27 A-HIGH-1), `presence.py:6911-6918` | Audit | LOW (but this is the Live-validation oracle) |

**Trust-hierarchy ripple is real:** HVAC + security + music all actuate
on AWAY. This is why the tier is elevated to 2-DB.

---

## Config-first check

Is there an existing operator-settable knob that already fences this?

- `BOOT_SETTLE_TIMEOUT_SECONDS` = **60** (`const.py:3784`) — module
  constant, no Number/Options surface. Only governs how long the gate
  remains up at all; does NOT by itself suppress AWAY emission (see
  mechanism #2).
- `BOOT_SETTLE_MIN_INPUTS` = **1** (`const.py:3789`) — module constant.
  Already minimum-sized.
- `HOUSE_STATE_RESTORE_MAX_STALE_S` = **1800** (`house_state.py:35`).
  Lifting this would mask the stale case rather than fence it, and would
  risk restoring a genuinely-wrong state. Not the right knob.
- `HOUSE_STATE_HEARTBEAT_S` = **300**. Lowering helps edge cases but does
  not close the window.
- `CONF_LOST_AWAY_GRACE_MIN`, `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS`,
  `CONF_LOST_AWAY_SLEEP_EXEMPT` — all exist (path-β), **do not gate the
  Nobody-home branch**.

**Verdict: no live knob fixes this.** The Nobody-home branch has no
grace, no sustained-empty discriminator, no boot fence. Code change is
required. Config-first gate (CLAUDE.md 1b) satisfied.

---

## Falsifiable invariant

**I-BAF-1 (primary):** Within the boot-settle window AND for an
operator-configurable *additional* post-settle warm-up window
`CONF_BOOT_AWAY_WARMUP_TICKS` (default 3 ticks), when the restored
(or default) state is any of `{HOME_DAY, HOME_EVENING, HOME_NIGHT,
SLEEP, WAKING, GUEST, ARRIVING}`, no inference-driven transition to
`HouseState.AWAY` occurs **on ANY reachable path** inside `infer()`.
A transition to AWAY after the warm-up requires one of:
(a) `sustained_external_empty` is True (N consecutive ticks of
`census==0 AND unidentified==0 AND _indoor_clear_debounced`), **or**
(b) `all_tracked_persons_away AND unidentified_count==0 AND
face_recognized_count==0 AND not camera_input_degraded` holding for the
same N consecutive post-settle ticks.

**I-BAF-2 (restart-discharge):** The warm-up window is bounded and
*monotonically releases*. It cannot be held open indefinitely by a
stuck producer; it releases after `max(BOOT_SETTLE_TIMEOUT_SECONDS,
CONF_BOOT_AWAY_WARMUP_TICKS × tick_period)` even if no evidence
arrives. Backstop: identical to today's gate timeout at
`presence.py:2302-2308`.

**Emission-site enumeration (every site that can set AWAY) —
MUST be fenced:**
1. `presence.py:1124-1128` Nobody-home.
2. `presence.py:1167-1178` path-α ACTIVE-only veto.
3. `presence.py:1245+` path-β LOST-admitted veto (already carries
   `sustained_external_empty`; needs the boot gate added to the
   immediate-engage limb).
No other `return HouseState.AWAY` statements in `infer()`
(grep-verified in §Pinned mechanism point 6).

**Discriminator (I-BAF cannot both fail and look like a sibling bug):**
After the fix, a boot into an occupied house produces a `house_state_log`
whose first post-boot row is NOT `away` AND whose structured log line
reads `Boot-away fence: SUPPRESSED Nobody-home AWAY (warmup_ticks=k/N
census=0 any_zone_occupied=False restored=home_day)`. A boot into a
genuinely empty house still produces an `away` row — but no earlier than
N ticks after settle AND with trigger label `sustained_external_empty`
(not `census_update`). This discriminates "fence works" from "fence
over-fires and loses legitimate AWAY".

---

## Suppression needs discharge

The fence introduces a new suppression; per
`feedback_suppression_needs_discharge` the plan MUST specify what
re-fires it, the backstop, and the restart behaviour.

- **Re-fire:** every `_run_inference` tick re-evaluates the fence; the
  warm-up counter advances once per tick on which the inputs are STILL
  pointing at AWAY. Once the counter hits `CONF_BOOT_AWAY_WARMUP_TICKS`
  OR the inputs disagree with AWAY on any intervening tick, the fence
  releases and inference proceeds normally.
- **Backstop:** the existing `BOOT_SETTLE_TIMEOUT_SECONDS=60` async_call_later
  (`presence.py:2512-2518`) already caps the gate. We add a *second*
  independent backstop: the fence releases unconditionally after
  `3 × BOOT_SETTLE_TIMEOUT_SECONDS` wall-clock regardless of tick
  arithmetic. Prevents a stuck tick scheduler from freezing the house
  into non-AWAY forever (an empty house for the weekend).
- **Restart:** the fence state is pure in-process (counter + a monotonic
  deadline). Any restart re-enters the fence at boot by construction;
  no persistence needed. This is the correct choice — the state we DO
  persist is the house state itself, not the fence.

---

## Numbers get knobs

| Number | Name | Rung (per CLAUDE.md ladder) | Why |
|---|---|---|---|
| Warm-up ticks after settle release | `CONF_BOOT_AWAY_WARMUP_TICKS` (default **3**) | **Options flow** (per-deployment, infrequent). Not a live Number — knob-turn is "I don't trust this house's boot shape", not daily tuning. | Mirrors `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS` precedent. |
| Second-stage wall-clock backstop | `BOOT_AWAY_FENCE_BACKSTOP_MULTIPLIER = 3` | **Module constant** (safety bound; change should require review). | Change implies the base gate is wrong; wants review. |
| Kill switch | `CONF_BOOT_AWAY_FENCE_ENABLED` (default **True**) | **Options flow** | Operator can disable fence if it over-fires. Semantics: False = today's behaviour byte-identical. |

All three are named; no inline literals.

---

## Deliverables

### D0: Measurement probe (measure-before-build gate)
One-shot read-only script against the live mount:

1. Read `.storage/universal_room_automation.house_state` `saved_at` just
   before and just after the next scheduled restart.
2. From the URA DB, pull every `house_state_log` row within 5 min of the
   last 20 boots; cross-tab against the matching
   `Boot-settle: released via <reason>` journal line and any
   `Boot-settle reconciliation: boot_restore_<diverged|confirmed>` line.
3. For each of the 18 false-AWAY boots on the card, label by {restore
   outcome, settle-release reason, time-to-first-AWAY, trigger-of-AWAY}.

**Acceptance criterion for D0:** we can state, per boot, which of the
three proven mechanisms (stale restore, in-window-but-reconcile-tick,
other) fired. If the real distribution is dominated by (2) rather than
(3), the fence design does not change — the fence covers both — but the
default `CONF_BOOT_AWAY_WARMUP_TICKS` may be re-chosen from the data.

### D1: Fence the Nobody-home branch (`presence.py:1124`)
Wrap the branch in: *if the current state is non-AWAY home-like AND
the fence is active, do not return AWAY; instead emit a structured
`Boot-away fence: SUPPRESSED` log line, increment a diagnostic counter,
and `return None` (preserve current state).* The fence is active when:

```
fence_active = (
    conf_boot_away_fence_enabled
    and (
        not self._boot_settle_done
        or self._post_settle_warmup_ticks_remaining > 0
    )
    and now_monotonic < self._boot_away_fence_backstop_deadline
)
```

#### Acceptance Criteria
- **Verify:** on cold boot into a house with any resident present, the
  Nobody-home branch does not transition to AWAY in the first
  `CONF_BOOT_AWAY_WARMUP_TICKS` post-settle ticks.
- **Sensor:** `sensor.ura_presence_boot_away_fence_suppressions` (new,
  total_increasing) increments on every suppression event.
- **Test:** `test_boot_away_fence_suppresses_nobody_home_on_cold_boot`
  (unit) + mutation drill: deleting the fence predicate from the branch
  causes a specific behavioural test to fail (per CLAUDE.md hollow
  anchors).
- **Live:** post-restart, in the first 5 minutes, `house_state_log`
  shows NO `away` row where `trigger IN ('census_update',
  'camera_detection', 'occupancy_change')` AND `census_snapshots` at
  the same minute shows identified residents.

### D2: Fence paths α and β (`presence.py:1167-1178`, `1245+`)
Same fence predicate applied to both veto paths. Path β's existing
`sustained_external_empty` + grace is NOT weakened; we only ADD the
boot-fence precondition.

#### Acceptance Criteria
- **Verify:** path α cannot force AWAY during the fence window.
- **Verify:** path β cannot force AWAY during the fence window.
- **Test:** two unit tests, one per path, driving the fence open AND
  closed; each test's mutation point individually tested.

### D3: Warm-up counter + backstop deadline
In `_run_inference`, advance `_post_settle_warmup_ticks_remaining` and
clear it on first disagreement (any input says non-empty).

#### Acceptance Criteria
- **Verify:** counter decrements once per tick; reaches 0 and the fence
  releases.
- **Verify:** wall-clock backstop fires at
  `BOOT_AWAY_FENCE_BACKSTOP_MULTIPLIER × BOOT_SETTLE_TIMEOUT_SECONDS`
  (default 180 s) even if the tick scheduler is stalled (simulated).

### D4: Options-flow fields + kill switch
Add `CONF_BOOT_AWAY_FENCE_ENABLED` (bool, default True) and
`CONF_BOOT_AWAY_WARMUP_TICKS` (int, default 3) to options flow. Labels
per `feedback_label_style_guide`: short phrase + plain helper text, no
"hysteresis"/"debounce" words. Proposed: *"Hold off AWAY after restart"*
(bool), *"Extra ticks of boot warm-up"* (int).

#### Acceptance Criteria
- **Verify:** options round-trip through flow + RestoreEntity.
- **Live:** flipping the kill switch to False restores exactly v5.103.50
  behaviour (byte-identical fence-disabled branch).

### D5: Diagnostic sensor + journald observability
`sensor.ura_presence_boot_away_fence_suppressions` + a sibling
`sensor.ura_presence_boot_away_fence_last_release_reason` ∈
`{"warmup_elapsed", "evidence_contradicted", "backstop", "disabled",
"not_cold_boot"}`.

#### Acceptance Criteria
- **Sensor:** both entities expose non-null state within one tick of
  settle release.
- **Live:** at the next restart, the release reason reported matches the
  manually-traced journal line.

---

## Tier classification

**Proposed: Tier 2-DB elevated.**

Justification:
- Cross-coordinator trust-hierarchy ripple (presence → HVAC → security
  → music → routine forecaster): per CLAUDE.md standing policy for
  regression-prone work, elevate to 3 framing-disjoint reviews.
- Touches a shared primitive (house-state inference) consumed by many
  dispatch sites.
- The failure mode is "one missed emission site" (Bug Class #53) — three
  AWAY return sites must all be fenced in lockstep.

**Review framings (framing-disjoint):**
- **A — correctness + edge cases per path.** Each of the three AWAY
  sites, each with fence-active and fence-released; sleep/guest/arriving
  restored states; override-restore interaction.
- **B — cross-coordinator + lifecycle + restart.** HVAC preset re-pick,
  security arming decisions, music following, routine forecaster
  incremental update must be byte-identical when the fence is DISABLED.
  Options-flow + RestoreEntity + reload-path (gate born released) +
  cold-boot (gate scheduled) must all converge.
- **C — adversarial completeness + test authority.** Independently
  re-enumerate every `return HouseState.AWAY` and every call site that
  can CAUSE one (triggers, listeners). Mutation drill per site: deleting
  the fence predicate from site N must cause a site-N-specific
  behavioural test to fail. Hand-build fixture: a captured
  `house_state_log` + `camera_census` payload from the 10-10 incident,
  committed as the acceptance oracle.

**Plan review (per CLAUDE.md Tier 2+ plan review rule):** ONE
adversarial plan review before build dispatch, per the Tier 2/2-DB
plan-review line (not Tier 3's two). Reviewer must independently re-grep
the AWAY emission sites and verify no fourth site exists.

---

## Non-goals
- Do NOT change `HOUSE_STATE_RESTORE_MAX_STALE_S` or
  `HOUSE_STATE_HEARTBEAT_S`. Changing them masks rather than fences.
- Do NOT remove the Nobody-home branch. Legitimate empty-house AWAY must
  still fire after warm-up.
- Do NOT re-architect the R2-2 deferral. It stays as a parallel defense;
  the fence closes the stale-restore hole it does not cover.
- Do NOT add a new signal or DB table. Diagnostic surface piggybacks on
  existing dispatch + sensor patterns.

---

## Plan-completion tracking
On ship, record which of D0-D5 landed, with any deferral reasoned in
the Plan Completion Tracking section of the cycle README.
