# Presence Reliability Batch — GUEST Latch + Empty-House Veto Gap + Tier-1 Edge Observability

**Author:** ura-planner
**Date:** 2026-07-12
**Status:** DRAFT — pre-build
**Investigations:** `project_presence_guest_latch_and_veto_gap.md`; live incidents 2026-07-11 (guest 20:57→06:05 no-sleep) and 2026-07-12 11:38-12:41 (empty-house flapping, ~20 cycles, PIN'd to `binary_sensor.invisoutlet_b7d0_motion` 1,261 flips/3h under Study A fan).
**Tier classification (recommended):** **Tier 2-DB** (three framing-disjoint reviews).
The house state machine and presence trust hierarchy are the canonical shared primitives (HVAC, compliance, fans, safety, actuators all consume `house_state` + zone occupancy). D1 reorders a decision inside `StateInferenceEngine.infer()` (cross-branch precedence, regression-prone by CLAUDE.md standing policy). D2 changes the WS-A path-β predicate on the AWAY veto — the same surface v4.7.14 / v4.7.14.1 / v5.7.0 have each had to revisit. Standing policy: default to Tier 2-DB for regression-prone shared-primitive work, and elevation is warranted here without needing the DB triggers to fire.

---

## Institutional context verified

### Anchor re-verification (2026-07-12, against develop tip)

| Investigation-memory anchor | Re-verified location | Status |
|---|---|---|
| Guest-exit check | `domain_coordinators/presence.py:1106` (`if current_state == HouseState.GUEST and unidentified_count == 0 and not guest_gate_armed`) | CONFIRMED (memo said ~1106) |
| Sleep-hour branch | `domain_coordinators/presence.py:1072-1077` (`if self._is_sleep_hour(hour): ... return HouseState.SLEEP / return None`) | CONFIRMED — `return` unconditionally exits `infer()`, so line 1106 is unreachable 22:00-06:00 |
| Guest entry gate (arms only from HOME_*) | `presence.py:1094-1101` (`if guest_gate_armed and current_state in (HOME_DAY, HOME_EVENING, HOME_NIGHT)`) | CONFIRMED |
| `VALID_TRANSITIONS[GUEST]` | `domain_coordinators/house_state.py:74-79` — `{HOME_DAY, HOME_EVENING, HOME_NIGHT, AWAY}`. NO SLEEP target. | CONFIRMED |
| WS-A path-β LOST-admitted veto | `presence.py:1030-1052` | CONFIRMED — predicate requires `all_trusted_or_lost_away_persons_away AND unidentified_count == 0 AND census_count == 0 AND not indoor_blocked AND (grace_elapsed_for_lost_away or not lost_away_persons_present) AND not sleep_exempt_state` |
| Path-β grace default | `const.py:1462-1463` — `CONF_LOST_AWAY_GRACE_MIN = "lost_away_grace_min"`, `DEFAULT_LOST_AWAY_GRACE_MIN = 60` | CONFIRMED |
| Person tracker LOST classification | grep `TrackingStatus.LOST` — `person_coordinator.py` (top-level, not under `domain_coordinators/`), plus consumers in `presence.py` and `aggregation.py` | CONFIRMED |
| v4.7.14.1 H3 trust filter (LOST excluded from trusted denominator) | `presence.py:4600-4613` (`_tracked_persons_count_trusted` derivation) | CONFIRMED |
| Substrate dispatch (edge write path) | `domain_coordinators/occupancy_substrate.py:645-666` (`_handle_state_change` → `_dispatch`) | CONFIRMED |
| `last_kind_to_fire` sibling attr | `binary_sensor.py:468` (also fallback `:514`) | CONFIRMED |
| v4.7.15 planning-doc footnote (near-miss sighting of the sleep-branch precedence issue) | `docs/planning/PLANNING_v4.7.15_universalize_bug_class_48_veto.md:102` — "sleep-hour gate inside `infer()` (suppresses guest detection during sleep): structural sibling, different signal." | CONFIRMED — this is the near-miss; noted "structural sibling" but did not follow through to the latch |

### Prior planning docs consulted
- `PLANNING_v4.7.15_universalize_bug_class_48_veto.md` (line 102 explicit footnote; §0.7 "Prior veto / fallback patterns surveyed" is the definitive prior-art inventory for this surface).
- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` (path α origin — informs why we cannot just remove H3).
- v5.7.0 WS-A / WS-A4 planning artifacts (path β origin, sleep exemption, outdoor-zone carve-out).
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` (adjacent surface — D3b routing decision below).

### Memory bodies pulled (full read, not index line)
- `project_presence_guest_latch_and_veto_gap.md` — the driving investigation.
- `project_v4714_live.md` — path α semantics, `unidentified_count == 0` requirement to preserve guest detection.
- `project_zone_away_when_occupied_home_night_gap.md` — sibling person-trust gap; informs "extend trust to home_night" (out of scope here, noted for cross-cycle awareness).
- `project_camera_signal_context_investigation.md` — where a `motion`-kind mmWave channel misclassification audit belongs.
- `project_v4_7_22_fan_recheck_mode2_live.md` — v4.7.22 recheck is "disabled-during-sleep NOT sleep-only" and is mmwave-sole-keyed (relevant to D3b decision).

### Design docs read
- `docs/Coordinator/PRESENCE.md` (house-state machine + zone/room tier contracts).
- `docs/Coordinator/OCCUPANCY_SUBSTRATE.md` (Tier-1 raw layer, edge semantics — for D3 log placement).

### Code surveyed end-to-end during scoping
- `domain_coordinators/presence.py::StateInferenceEngine.infer()` (full body ~lines 900-1122) — required to see all branches D1 reorders.
- `domain_coordinators/house_state.py` (full: enum, VALID_TRANSITIONS, DEFAULT_HYSTERESIS, HouseStateMachine).
- `domain_coordinators/presence.py::_run_inference` window 4580-4720 (LOST filter, path-β args prep, guest-gate arming/eval).
- `domain_coordinators/occupancy_substrate.py::_handle_state_change` + `_dispatch` (D3 target).

### Proposed additions — REUSED vs NEW

| Item | REUSED / NEW | Location / Justification |
|---|---|---|
| `_veto_path` diagnostic string | REUSED at `presence.py:1039,1042` — D2 will additionally set `"lost_admitted_immediate"` (new value, same field). |
| Grace-immediate condition inputs (`census_count`, `any_indoor_zone_occupied`, `lost_away_persons_present`) | REUSED — all already computed and passed to `infer()` in the WS-A path-β prep block. No new plumbing. |
| `CONF_LOST_AWAY_GRACE_MIN` / `DEFAULT_LOST_AWAY_GRACE_MIN` | REUSED at `const.py:1462-1463` — D2 does NOT change the grace value; it adds a co-existing immediate-engage predicate that bypasses grace when the falsifiable predicate holds. |
| `SIGNAL_SUBSTRATE_KIND_CHANGED` | REUSED at `occupancy_substrate.py:697+` — D3 log lands on the same code path, no new signal. |
| `last_kind_to_fire` attr | REUSED at `binary_sensor.py:468` — D3's optional `last_edge_entity` is the sibling attr (same fallback pattern at `:514`). NEW attribute key, existing pattern. |
| GUEST→SLEEP transition | **NOT added.** Explicit product decision — see D1 rationale. |

---

## Falsifiable invariants (stated up front, per Tier-3 discipline — kept even at Tier 2-DB for reviewer D-style adversarial passes)

**I-D1 (guest-exit reachability):** For any tick where `current_state == GUEST` and `unidentified_count == 0` and `guest_gate_armed == False`, `infer()` MUST propose a non-GUEST successor (specifically `_time_based_home(hour)`), regardless of whether `_is_sleep_hour(hour)` is True. There must exist NO reachable path through `infer()` where a cleared guest signal is held in GUEST for more than one inference cycle.

**I-D2 (immediate-engage veto — safety of the grace):** The BLE-dropout-while-home protection that motivated the 60-min grace MUST remain intact. Formally: for any tick where at least one LOST person is present AND (`census_count > 0 OR any_indoor_zone_occupied == True`), the immediate-engage predicate MUST evaluate False. Equivalently: bypassing the grace is legal ONLY when the house is externally corroborated empty (camera census == 0 AND no indoor zone occupied AND `unidentified_count == 0`) — the same evidence set that already justifies path β at the *end* of the grace.

**I-D3 (observability additive-only):** D3 MUST NOT change any dispatch, gating, or state-machine decision. It is log + one read-only attribute. Byte-identical behavior on the no-observability path.

---

## D1 — GUEST latch fix: reorder guest-exit before sleep-hours branch

### Change

In `StateInferenceEngine.infer()` (`presence.py`), move the guest-exit check currently at `:1106` to execute BEFORE the sleep-hours branch at `:1072-1077`. The moved block:

```python
# Guest mode exit — evaluated BEFORE sleep-hour suppression so a cleared
# guest signal is not latched overnight (2026-07-11 incident: guest
# 20:57 → cleared 23:05 → held until 06:05).
if current_state == HouseState.GUEST and unidentified_count == 0 and not guest_gate_armed:
    self._confidence = 0.75
    return self._time_based_home(hour)
```

The sleep-hours branch, guest-entry branch, and the `HOME_NIGHT → SLEEP` transition all remain unchanged in relative order beneath it.

### What is explicitly NOT changed

- **`VALID_TRANSITIONS[GUEST]` is NOT touched.** Adding SLEEP to the set would push sleep actuations onto genuine guests (out-of-house residents' rooms shut down at 23:00 while a real guest is up watching TV). Product decision recorded per operator alignment 2026-07-12/13; archaeology at git `0d0e865e` shows the omission was scaffold-era, not a considered exclusion.
- **Guest-entry precedence is NOT touched.** Guest ARM remains gated to `HOME_DAY / HOME_EVENING / HOME_NIGHT` (`:1094`) and remains suppressed during sleep hours (a sleep-hour tick still returns SLEEP before the guest-entry block at `:1094` can fire, because SLEEP is proposed at `:1076` from any home-like state). Preserving this is load-bearing — otherwise chronic false unidentified arming (see investigation memo, 2-4×/day) would flip the house into GUEST at 3 AM.

### Traced semantics (operator pressure-tested — record in the doc so reviewer D can falsify)

| Scenario | Before fix | After fix |
|---|---|---|
| Real guest present at 22:00, gate still armed | Stays GUEST (correct) | Stays GUEST (unchanged — guest-exit predicate is False, falls through to sleep-branch which is a no-op from GUEST since GUEST is not in `(SLEEP, WAKING)` — wait: `:1074` proposes SLEEP if not in (SLEEP, WAKING). GUEST → SLEEP would then be REJECTED by `VALID_TRANSITIONS[GUEST]`. Net: stays GUEST. Correct.) |
| Guest signal clears at 23:30 (late-clearing gate) | Held in GUEST until 06:05 (BUG) | Guest-exit fires → `_time_based_home(23) == HOME_NIGHT`. Next tick: `_is_sleep_hour(23) == True` AND `current_state == HOME_NIGHT ∉ (SLEEP, WAKING)` → propose SLEEP → VALID (`HOME_NIGHT → SLEEP` is in the transition table). Sleep by 23:30 + ~1 tick + hysteresis. |
| Guest signal clears at 08:00 (day) | Guest-exit fires as before (already reachable outside sleep hours) | Identical — reorder is a no-op outside sleep hours. |
| False unidentified detection during SLEEP (3 AM) | Sleep-branch returns first → SLEEP proposed (no-op from SLEEP). No latch. | Identical — guest-exit predicate requires `current_state == GUEST`; when in SLEEP the block short-circuits. |

### D1b (optional, decide-in-review): rejected-proposal class

`infer()` at `:1094-1101` can propose GUEST from `HOME_NIGHT`. `VALID_TRANSITIONS[HOME_NIGHT] = {SLEEP, AWAY}` — GUEST is not in it. Every tick where a guest gate arms at 21:30-22:59 in HOME_NIGHT proposes GUEST and the state machine silently rejects it (Bug Class #53-adjacent: computed-but-not-consumed → propose-then-reject-silently). This is a separate small-scope hygiene fix.

**Options:**
1. **Fix:** add `GUEST` to `VALID_TRANSITIONS[HOME_NIGHT]`. Symmetric with HOME_DAY / HOME_EVENING. Consistent with how guest entry is scoped in `infer()`.
2. **Document:** leave as-is, add an INFO log or `_state_machine_rejections` counter for observability, defer the fix.

**Recommendation:** take option 1 as a scoped addendum inside D1 (single-line change, symmetric to sibling states, and directly consistent with `infer()`'s intent to accept guest arming while in any HOME_* variant). Reviewer B should verify no downstream code special-cases HOME_NIGHT → GUEST as impossible.

### Acceptance criteria — D1
- **Verify (unit):** new test `test_guest_exit_reachable_during_sleep_hours` — set state=GUEST, hour=02, `unidentified_count=0`, `guest_gate_armed=False` → `infer()` returns `HOME_NIGHT` (or `_time_based_home(2)`). Same test with old ordering asserts SLEEP (proves the reorder is load-bearing).
- **Verify (unit):** `test_real_guest_at_sleep_hour_holds` — state=GUEST, hour=23, `guest_gate_armed=True` → returns None (holds GUEST). Confirms real guests are not evicted.
- **Verify (unit):** `test_false_unidentified_during_sleep_no_guest_entry` — state=SLEEP, hour=03, `guest_gate_armed=True` → returns None (SLEEP is not in the guest-entry current_state set; and the sleep-branch fires first from any non-(SLEEP,WAKING) state). Confirms chronic false arming cannot escalate to GUEST overnight.
- **Verify (unit, D1b):** if the HOME_NIGHT → GUEST transition is added, add `test_home_night_to_guest_valid` and confirm no other test regresses.
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` `state` attribute transitions GUEST → HOME_NIGHT → SLEEP within one dwell cycle post-clear.
- **Live:** the next real guest episode that straddles 22:00 with a late-clearing gate must show `state == SLEEP` within `gate-clear + ~10 min` (accounts for 300s guest exit-persistence upstream at `:1715` + HOME_NIGHT hysteresis 120s from `house_state.py:92`). Recorded in the post-deploy README validation table with entity attribute timestamps.

---

## D2 — Empty-house veto gap: LOST-admitted immediate-engage

### Root cause (re-stated)

Once the whole family leaves, Bermuda drops every person's location and the person coordinator moves them to `TrackingStatus.LOST`. The v4.7.14.1 H3 trust filter (`presence.py:4600-4613`) then excludes LOST persons from the trusted denominator — path α (`all_tracked_persons_away`) can never fire because the denominator collapses to zero (false). Path β (WS-A LOST-admitted, `presence.py:1030-1052`) IS designed for this case, but its `grace_elapsed_for_lost_away` predicate holds it off for `DEFAULT_LOST_AWAY_GRACE_MIN = 60` minutes. Result during 2026-07-12 11:38-12:41: **zero AWAY veto available for the entire empty-house window** — the house state machine free-oscillates on 30s / 60s / 120s hysteresis under any noisy indoor signal (Study A `binary_sensor.invisoutlet_b7d0_motion`, 1,261 flips/3h).

### The grace exists for a real reason — do not remove it

BLE dropout while a person is genuinely home (phone battery low, radio flake, Bermuda coordinator restart) can flip a person to LOST even though the person is in the living room. The 60-min grace prevents an immediate false-AWAY veto in that case. **D2 does not shorten or remove the grace.** It adds an immediate-engage predicate that fires only when the house is externally corroborated empty.

### Change

In `StateInferenceEngine.infer()`, add a co-existing predicate that admits path β immediately when the "obviously empty" evidence is unambiguous. The clause is additive (a second admit path), not a replacement:

```python
# v5.x.y D2: immediate-engage veto when the house is externally
# corroborated empty. Bypasses `grace_elapsed_for_lost_away` ONLY when
# every non-BLE signal agrees the house is empty. Preserves the grace
# for the BLE-dropout-while-home scenario the grace was designed for.
immediate_engage_empty_house = (
    census_count == 0
    and unidentified_count == 0
    and not indoor_blocked          # `any_indoor_zone_occupied` (WS-A4 already excludes outdoor)
    and lost_away_persons_present   # at least one person is LOST-and-away (path β's raison d'être)
)

if (
    all_trusted_or_lost_away_persons_away
    and unidentified_count == 0
    and census_count == 0
    and not indoor_blocked
    and (
        grace_elapsed_for_lost_away
        or not lost_away_persons_present
        or immediate_engage_empty_house      # NEW
    )
    and not sleep_exempt_state
):
    ...
    self._veto_path = (
        "lost_admitted_immediate"
        if immediate_engage_empty_house and not grace_elapsed_for_lost_away
        else "lost_admitted"
    )
    ...
```

### Why this is safe against I-D2 (invariant proof sketch)

The BLE-dropout-while-home scenario the grace protects has **at least one** of the following True:
- `census_count > 0` (interior cameras see the person),
- `any_indoor_zone_occupied == True` (mmWave/PIR/occupancy fires in some room),
- `unidentified_count > 0` (a Frigate person that face-ID couldn't match — still evidence of a body).

`immediate_engage_empty_house` requires **all three** to be False simultaneously. Any single one being True defeats the immediate engage and falls back to the existing grace path. Zone-1 home_night home_state gap (`project_zone_away_when_occupied_home_night_gap.md`) does NOT apply here — that gap is about mmWave dropping a still body under a specific state; if any other room's substrate is True, or any indoor camera has a person count, immediate-engage is suppressed. Sleep protection is preserved by the existing `sleep_exempt_state` gate (unchanged).

### Falsifiable adversarial cases for reviewer D (Tier-2-DB framing C)
1. Solo occupant naps in bedroom, phone battery dies (LOST), mmWave drops still body for a scan cycle, no cameras cover bedroom. Any indoor zone occupied? If not, immediate-engage fires → false AWAY. **Mitigation:** the same failure mode already exists for path β at `grace_elapsed`; D2 accelerates it. **Live-check:** in current house wiring, verify at least one indoor room's Tier-1 substrate covers each sleeping location (D3 makes this observable). Sleep exemption also gates this — reviewer must confirm nap during `HOME_DAY` isn't sleep-exempt.
2. Guest present but no BLE tracked person (real guest) → guest gate armed, `unidentified_count > 0` → immediate-engage predicate False. Safe.
3. Family returns before grace elapses (2026-07-12 case: 11:30 leave, 12:41 return): with D2, veto fires immediately at ~11:31 → house goes AWAY at high confidence. On return at 12:41, `census_count > 0` → path α (or normal HOME transition) reasserts. Same recovery as a normal AWAY→ARRIVING. No pathology.

### Sleep interaction

The existing `sleep_exempt_state` gate (path β's I4 invariant) already denies path β during SLEEP / HOME_NIGHT / WAKING. Immediate-engage inherits this — no separate sleep guard needed. Reviewer B must trace that `sleep_exempt_state` is True in the caller's payload for all three states.

### Acceptance criteria — D2
- **Verify (unit):** `test_immediate_engage_fires_when_house_externally_empty` — state=HOME_DAY, one LOST-away person, census=0, no zones occupied → returns AWAY, `_veto_path == "lost_admitted_immediate"`.
- **Verify (unit):** `test_immediate_engage_denied_when_zone_occupied` — same but one zone OCCUPIED → returns None, no veto (predicate False on `indoor_blocked`).
- **Verify (unit):** `test_immediate_engage_denied_when_census_positive` — same but `census_count=1` → returns None.
- **Verify (unit):** `test_immediate_engage_denied_when_unidentified` — same but `unidentified_count=1` → returns None.
- **Verify (unit):** `test_immediate_engage_denied_during_sleep_state` — `sleep_exempt_state=True` → returns None regardless.
- **Verify (unit):** `test_immediate_engage_denied_no_lost_persons` — no LOST persons at all → falls through to the pre-existing `not lost_away_persons_present` limb, not the new one (path α should have handled it).
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` `veto_path` attribute reads `lost_admitted_immediate` during immediate-engage AWAY.
- **Live:** the next empty-house window (all persons `not_home`, all indoor zones idle) must show `state == AWAY` with `veto_path == "lost_admitted_immediate"` within the AWAY hysteresis window (30s) instead of flapping for up to 60 min. Post-deploy README must record the observed timestamps + `veto_path` value.

### Fix-up (Tier 2-DB reviews A/B/C) — 2026-07-13

The build's original D2 immediate-engage limb was a tautology inside the outer path-β clause (A-CRIT-1 = B-CRIT-1 = C-HIGH-1, triple-confirmed): the outer clause already required `census_count==0 AND unidentified_count==0 AND not indoor_blocked`, so restating those inside `immediate_engage_empty_house` reduced the OR-group to unconditionally True — silently deleting BOTH the 60-min grace AND the FIX-2b indoor-clear debounce. Empirical proof: `test_v570_fixup_wiring.test_n1_1_behavioral_debounce_below_threshold_suppresses_beta` and `test_n1_1_behavioral_stampless_lost_person_holds_beta` passed at parent 672118b6 and FAILED at build cd93d169.

**Fix (this pass):**
- Threaded a NEW independent kwarg `sustained_external_empty` into `StateInferenceEngine.infer()`. Computed in the caller `_run_inference` as N consecutive ticks of `(census_count == 0 AND unidentified_count == 0 AND _indoor_clear_debounced)`; N reuses `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS` (default 3) — no new CONF surface, consistent with FIX-2b semantics.
- `immediate_engage_empty_house = sustained_external_empty AND lost_away_persons_present`. Because `sustained_external_empty` carries the indoor-clear debounce inside it, a single-tick mmWave dropout on a still resident with a dead phone CANNOT force AWAY. Grace remains load-bearing on every tick where the sustained-empty confirmation is not met (`test_d2_grace_is_sole_keepout_when_sustained_empty_not_met` proves this at the gating level; `test_d2_whole_or_group_mutation_flipping_to_true_now_turns_something_red` proves the OR-group is no longer a tautology).

**No-flap honesty (B-MED-1):** D2 immediate-engage does NOT kill the 2026-07-12 indoor-blip flap cycle by itself. The real flap killer was the config-level removal of `binary_sensor.invisoutlet_b7d0_motion` from Study A's `motion_sensors` list. What D2 provides is: on a genuinely empty house, path β can fire at ~N-tick latency (default ~30-60s at 15s tick cadence) instead of 60 min — closing the empty-house-window where the state machine could free-oscillate. An AWAY-hold suppression (once AWAY is achieved, ignore noisy indoor blips for M seconds) is separately backlogged and would be the durable no-flap fix.

---

## D3 — Tier-1 substrate edge observability

### Change

In `domain_coordinators/occupancy_substrate.py::_handle_state_change` (verified `:624-666`), immediately before the `_dispatch(...)` call at `:666`, add:

```python
_LOGGER.info(
    "OccupancySubstrate edge: room=%s kind=%s entity=%s new=%s prior=%s",
    room_name, kind, entity_id, occupied, prior,
)
```

Plus (optional, recommended) a per-room `last_edge_entity` attribute on the room binary sensor, sibling of `last_kind_to_fire` at `binary_sensor.py:468`. Populated on the substrate subscriber callback; falls back to `""` in the exception path at `:514` (matches existing pattern).

**Log level rationale:** INFO not DEBUG because it needs to be visible without user log-level tweaks when triaging a flap incident. Volume estimate: on a healthy 30-room install this fires only on real edges (post-boot-settle), and the substrate's own single-writer discipline (F8 fix-up C-LOW-2) coalesces attribute-only updates. Bugs that would spike this (fan-under-noise like Study A) are exactly what we want to see.

### Explicit non-goals for D3
- No dispatch change (I-D3).
- No gating on the edge. Fan-interference mitigation stays in its existing surfaces (v4.7.20 hold, v4.7.22 recheck). D3 is diagnostic-only.

### Config-level mitigation for Study A is already done (record it)
The operator has already removed `binary_sensor.invisoutlet_b7d0_motion` from Study A's `motion_sensors`. D3 is the durable observability that would have pinned it in 5 minutes instead of an investigation. Note in README.

### D3b — Motion-kind mmWave-channel misclassification (routing decision)

The investigation memo flagged Study B `moving_target` as another mmWave physical channel that is classified as motion-KIND in URA's substrate, structurally invisible to the mmwave-sole-keyed fan mitigations. Two disposition options:

1. **Include in this batch:** add a D3b audit deliverable — grep every configured `motion_sensors` entry across rooms, flag any whose device class / entity naming implies mmWave underneath (`moving_target`, InvisOutlet mmWave channels, etc.), remap to `mmwave_sensors`. Small scope, same coordinator surface.
2. **Route to the open camera-signal-context investigation** (`INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md`).

**Recommendation: option 2 (defer to camera-signal-context investigation).** Rationale:
- D3b is a **classification-policy audit**, not a code-behavior change. It reads more like the camera-signal-context work (per-room signal-provenance policy) than like the presence-inference batch (state machine + veto predicates).
- Bundling D3b would broaden the Tier 2-DB scope and force reviewers to reason about substrate classification correctness alongside state-machine precedence — different framings, blind-spot risk.
- The Study A flap is *already* mitigated at config level; the reviewer framing benefit of keeping this batch tight outweighs the "one more room" savings.
- Explicitly cross-link both docs so the investigation picks up D3b as a first-class item.

### Acceptance criteria — D3
- **Verify (unit):** `test_substrate_edge_log_emitted` — mock logger, drive one edge through `_handle_state_change`, assert INFO record with expected format.
- **Verify (unit):** `test_last_edge_entity_attr_populated` — subscribe binary sensor to substrate, drive edge, assert `last_edge_entity` attr equals the driving entity_id.
- **Sensor:** `binary_sensor.<room>_occupied` `last_edge_entity` attribute reads the entity_id of the last substrate transition that entered this room.
- **Live:** enable a controlled edge (toggle a known sensor), grep HA log for the INFO line and confirm `entity=` field matches. Record in README validation table.

---

## Tier 2-DB — three proposed framings

Standing operator policy (2026-06-08): 3 framing-disjoint reviews for regression-prone shared-primitive work regardless of DB triggers. The "DB" name is historical; what we buy is three disjoint framings.

- **Review A — local correctness + precedence.** Focus on the reorder in `infer()`: is the new branch order semantically complete across every (current_state, hour, guest_gate_armed, unidentified_count) tuple? Enumerate the 9 house states × 24 hours × 2 gate armings × {0, >0} unidentified. Confirm no state that was previously unreachable becomes reachable in a way that other code (HVAC, compliance, fans) has come to depend on. Confirm D1b's optional HOME_NIGHT → GUEST transition addition does not regress any test.

- **Review B — cross-coordinator + trust hierarchy + no-flap under D2.** Focus: does D2's immediate-engage predicate leak in any legal-config combination where a person is genuinely home? Trace every input (`census_count`, `unidentified_count`, `indoor_blocked`, `lost_away_persons_present`, `sleep_exempt_state`) to its producer. Confirm the WS-A4 outdoor-zone carve-out is preserved (an occupied "Front Porch" zone must not both fail to block immediate-engage AND cause a false AWAY). Confirm interaction with v4.7.13 sleep-only person-trust (`hvac.py:1151`) — D2's sleep guard is `sleep_exempt_state`, which comes from a different producer; verify the two are consistent. Confirm no double-emit / no post-deploy silent regression of pre-existing path β behavior on the grace-elapsed path.

- **Review C — adversarial completeness + observability additive-safety + test authority via per-site source mutation.** Sole job: state I-D1 / I-D2 in falsifiable form and BREAK them. Enumerate the ENTIRE reachable state space, not just the diff. Include pre-existing code paths — the v4.7.15 planning doc's own §0.7 catalogued the sleep-branch as a "structural sibling" and did not act on it; the reviewer must confirm no other structural siblings exist elsewhere in `infer()`. For D3, mutate the log-emission site out of the source and confirm a test fails (proving the log is authoritatively covered). For D1/D2, mutate the reorder / new predicate site and confirm a test fails per site (no aggregate monkeypatch — real per-site source mutation).

Run all three in parallel with the framings above pinned in each dispatch prompt so they cannot converge on the same blind spot.

### Pre-review baseline

```bash
git tag pre-review-v<version> -m "Pre-review baseline for presence reliability batch"
```

### Live validation (Review D)

- Presence state attribute stream over the first real guest-episode-straddling-22:00 → GUEST → HOME_NIGHT → SLEEP timestamps recorded.
- Presence state attribute stream over the first real empty-house window → AWAY with `veto_path == "lost_admitted_immediate"`, no flapping.
- Log grep for `OccupancySubstrate edge:` INFO lines during a known toggled edge → entity_id matches.
- All three tables written back into `docs/readmes/README_v<version>.md` per the mandatory validation write-back rule.

---

## Deferred / explicitly out of scope
- **GUEST→SLEEP transition** — separate product decision; would push sleep actuations onto genuine guests. Not adding.
- **Chronic false unidentified arming from interior Frigate cameras (2-4×/day)** — root cause is camera identification deficit, belongs in the camera-signal-context investigation. D1 makes the *latch* survivable; it does not address the *arming*.
- **`CONF_DISABLE_CAMERA_PRESENCE` per-room opt-out** — part of the camera investigation, not this batch.
- **D3b motion-kind mmWave-channel audit** — routed to camera-signal-context investigation (rationale above).
- **Zone-1 `away` while occupied at `home_night`** (`project_zone_away_when_occupied_home_night_gap.md`) — separate Tier-1 sibling of v4.7.13, not blocked by this batch.
- **Path-β grace-value tuning** — leaving `DEFAULT_LOST_AWAY_GRACE_MIN=60` unchanged. D2 adds an immediate-engage path *around* the grace; if the immediate-engage predicate proves durable in live validation, a future cycle may propose shortening the grace.

---

## Open operator questions

1. **D1b — HOME_NIGHT → GUEST valid transition:** in-scope for this batch (small, symmetric fix), or defer to a hygiene ticket?
2. **D3 log level — INFO vs DEBUG:** INFO gives triage-time visibility without user log-tweaks but is more chatty. Confirm INFO is acceptable, or downgrade to DEBUG + a `substrate_edges_last_60s` counter attribute?
3. **`last_edge_entity` attribute — include in D3 or drop?** Log-only D3 is smaller; the attribute is convenient for dashboarding but adds a per-room RAM field.
4. **D3b routing — camera-signal-context investigation or here?** Recommendation is to route out; confirm.
5. **Immediate-engage confidence value:** current path β uses 0.95. Immediate-engage inherits it. Keep 0.95, or lower to (e.g.) 0.9 to differentiate on the sensor attribute for future analytics?
