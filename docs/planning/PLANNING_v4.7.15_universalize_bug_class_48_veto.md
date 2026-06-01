# PLANNING v4.7.15 — Universalize the Bug Class #48 Veto Helper Across Room / Zone / House / Coordinator Layers

**Tier:** 2-DB (three parallel reviews, different framings)
**Status:** Planning — institutional context gathered, scope defined
**Predecessors shipped:** v4.7.13 (sleep-state zone aggregator fallback), v4.7.14 (away-state house-inference person-tracker veto)
**Successor (NOT in scope):** v4.7.16 — room-level veto + sparse-room weighting via existing `CONF_SCANNER_AREAS` (`const.py:317`)
**Master link doc:** `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` *(does not yet exist — to be created alongside this doc by the planner pass or as a side artefact in v4.7.15 D0; planning agent flag this for operator on read)*

---

## 0. Institutional context — verified before scoping

### 0.1 `_check_zone_occupancy_confidence` — current location, signature, callers

**Location.** `custom_components/universal_room_automation/domain_coordinators/hvac.py:1350`.

**Signature** (verified):
```python
def _check_zone_occupancy_confidence(self, zone) -> tuple[int, int]:
    """v3.22.2: Multi-source confidence check for D6 stale occupancy failsafe.
    Returns (confirmed, possible) where:
      confirmed: number of source types actively confirming presence (0-4)
      possible:  number of source types available for this zone (0-4)
    Source types:
      1. Motion/mmWave (recent activity within 30 min)
      2. BLE person detection (phone in zone via person_coordinator.get_persons_in_zone)
      3. Camera person detection (Frigate person entity "on")
      4. Multiple occupied rooms (2+ rooms occupied = unlikely all stuck)
    """
```

**Callers** (verified, single caller):
- `hvac.py:870` — D6 stale-failsafe inside `_apply_house_state_presets`. Pattern:
  ```python
  confirmed, possible = self._check_zone_occupancy_confidence(zone)
  threshold = min(2, possible) if possible > 0 else 1
  if confirmed >= threshold: ...
  ```
  Reaches here under three conjunctive conditions: zone has `any_room_occupied`, `house_state != "sleep"`, `continuous_occupied_since` older than `_max_occupancy_hours * 3600`.

**Risk for D4 relocation.** Method internally imports `DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM, CONF_ROOM_NAME` from `..const`. Touches `self.hass`, `self._max_occupancy_hours` (not actually used in body — only the caller uses it). Reads `person_coordinator` from `self.hass.data[DOMAIN]`. **No other code path imports or calls this method** (grep verified above). Relocation surface is therefore small: change the call site at `hvac.py:870` to invoke the new presence-side accessor, retain the existing `(confirmed, possible)` tuple shape and adaptive-threshold semantics at the call site.

### 0.2 `_derived_mode`, `_run_inference`, `infer()` call sites — verified

| Call | File:Line | Notes |
|---|---|---|
| `_derived_mode` property | `presence.py:152` | Returns ZonePresenceMode based on Tier 1/2/3 signals; called from `ZonePresenceTracker.mode` (line 149) and exported in `to_dict` (line 301). |
| `_run_inference` triggers | `presence.py:823, 1285, 1330, 1369, 1507, 1547, 1722, 1868, 2518, 2522` (10 sites) | All schedule via `hass.async_create_task` except `:823` (`startup`, awaited) and `:1507` (`periodic`, awaited). The dispatcher payload is built at lines 2089-2096. |
| `_run_inference` definition | `presence.py:1879` | Async, computes `all_tracked_persons_away` (1903-1923), builds `any_zone_occupied` (1928-1931), then calls `infer()` at 1995. |
| `infer()` definition | `presence.py:367` | Engine method; v4.7.14 veto branch at 410-414. Hot AND-gate at 397-401. |

### 0.3 What downstream coordinators do with `confidence` today

Greps performed:
- `house_state_confidence` — referenced only in `sensor.py:3659, 3671` (the dedicated `sensor.ura_house_state_confidence` thin mirror).
- `inference_engine.confidence` — used in 5 sites, all inside `presence.py`: lines 621 (public property), 2066 (DB log row), 2094 (dispatcher payload), 2111 (activity log), 2408 (re-dispatch from observation-mode exit).
- `safety.py` — has its own `confidence` field on `HazardEvent` (1300, 1346, 1350, 1362, 1367, ...). **This is a different domain field; not derived from PresenceCoordinator confidence.** No safety coordinator reads `presence.confidence`.
- `music_following.py` — `MIN_CONFIDENCE` / `high_confidence_distance` — Bermuda BLE proximity confidence, again unrelated to house-state confidence.

**Conclusion (verified).** Nothing in URA today *gates* on `presence.confidence`. It is published, logged, and dispatched — but no downstream coordinator branches on its value. v4.7.15 D6 will be the first consumer that uses confidence (specifically `signal_consensus`) to actively defer behavior.

### 0.4 v4.7.13 zone aggregator veto pattern — verified

`aggregation.py:3185-3268`. `ZoneAnyoneBinarySensor.is_on`:
1. Layer 1 — existing room-level rollup (line 3196-3199): returns True if any room coordinator reports `STATE_OCCUPIED`.
2. Layer 2 — sleep fallback (line 3201-3203) calls `_sleep_person_fallback_occupied()` which guards on:
   - `coordinator_manager` present
   - `manager.house_state == "sleep"`
   - HVAC coordinator + `_zone_manager` ready (else WARN-once via `_warn_sleep_fallback_unavailable`)
   - `zone_persons` non-empty
   - At least one `zone_persons` entity literally `state == "home"`

v4.7.13 fix-up MEDIUM-2 added one-shot WARN at `aggregation.py:3270-3287` for boot-race telemetry. We must preserve this surface.

### 0.5 v4.7.14 house-inference veto pattern — verified

`presence.py:1896-1926` computes `all_tracked_persons_away` per-cycle inside `_run_inference`. `presence.py:367-414` defines `infer()` with the new kwarg defaulted False; veto branch at 410-414 short-circuits to AWAY with confidence 0.95 (above the 0.9 census-driven AWAY and the 0.85 ARRIVING). Diagnostic attributes wired through `PresenceHouseStateSensor.extra_state_attributes` at `sensor.py:3629-3634`.

### 0.6 INVESTIGATION_camera_signal_context_sensitivity §6.5 — verified

The investigation explicitly says (line 222-228): **"Fix: attach the new consensus metric as another attribute on the same canonical sensor. Do not create a new dedicated sensor."** It also identifies `sensor.ura_presence_coordinator_presence_house_state` (i.e., `PresenceHouseStateSensor` at `sensor.py:3579`) as the canonical surface, with `sensor.ura_house_state_confidence` (`sensor.py:3656`) as a thin mirror.

**Operator brief explicitly requests** in D5 BOTH a dedicated `sensor.ura_signal_consensus_confidence` AND a mirror attribute on the rich sensor. That diverges from the investigation's text. We adopt the operator brief literally — dedicated sensor + mirror attribute — and note the divergence here for review. Reviewer C is asked to assess.

Computation formula (verified from §6.5 line 257-268), to be implemented in `_run_inference` after `infer()` returns:
```
consensus = 1.0
if all_tracked_persons_away and any_zone_occupied:        consensus -= 0.4
if any_stale_or_lost_tracker and not all_tracked_persons_away: consensus -= 0.2
if camera_occupied_count > 0 and mmwave_occupied_count == 0:   consensus -= 0.15
if state_confidence < 0.85:                                consensus -= 0.1
consensus = max(0.0, consensus)
```

Downstream gating (verified from §6.5 line 270-275):
- HVAC defers non-critical preset changes when `consensus < 0.5`, resumes at `> 0.7` (40-pt hysteresis)
- Compliance suppresses violations when `consensus < 0.6` sustained ≥ 60 s

### 0.7 Prior veto / fallback patterns surveyed beyond v4.7.13/14

- `presence.py:397-401` — original `census_count == 0 AND not any_zone_occupied → AWAY` AND-gate (commit `b761cbe`, v3.6.0-c1). This is the ancestor of all veto patterns.
- `presence.py:435-439` — sleep-hour gate inside `infer()` (suppresses guest detection during sleep): structural sibling, different signal.
- `presence.py:444-449` — WAKING transition (SLEEP → WAKING when current state is SLEEP). v4.7.15 D3 will harden this with sustained-signal requirement.
- `presence.py:451-470` — `guest_gate_armed` flow (v4.6.2.2): pre-evaluated boolean fed into engine. Architectural precedent for D2/D3 wiring.
- `hvac.py:865-893` — D6 stale-failsafe with `_check_zone_occupancy_confidence` (the very helper D4 relocates). Multi-source confidence threshold.
- `hvac.py:924-973` — `effective_preset == "away" and self._house_state == "sleep"` guard (v4.7.13 D2 — shipped). This is the in-HVAC preset-flip suppression.

**No prior veto code exists outside these.** No security-coordinator veto, no safety-coordinator veto, no DPM veto. D5/D6 are the first time `signal_consensus` becomes an input to other coordinators.

### 0.8 Docs / memory consulted (full list)

- `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md` (read in full)
- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` (read in full)
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` (sections 1-2, 6, 6.5, 7, 8 read; §6.5 is load-bearing)
- `docs/QUALITY_CONTEXT.md` v7.2 — Bug Class #48 entry (line 1855-1905), plus #20, #22, #23, #33, #44, #46, #47 headers
- Source files cited inline above with file:line
- Memory entry `feedback_db_sensitive_3x_targeted_reviews.md` (Tier 2-DB protocol)
- Memory entry `project_v475_design_intent.md` (canonical-resolution Bug Class #47 — relevant because D5's dedicated sensor must avoid #47 lazy violation)

---

## 1. Cycle goal — one sentence

Promote the Bug-Class-#48 veto pattern from two ad-hoc inline implementations (v4.7.13 in aggregation.py, v4.7.14 in presence.py) into a shared, well-tested utility on `PresenceCoordinator`, then plug it in at three more layers (zone aggregator for non-sleep states, house inference for WAKING/GUEST transitions, HVAC + compliance defer gates driven by a new `signal_consensus` metric).

## 2. Scope summary table

| Deliverable | Layer | Net new code | Reuses |
|---|---|---|---|
| D1 | Helper extraction (`presence.py`) | ~80 LoC + dataclass + tests | `_run_inference` 1896-1926, `infer()` 410-414, aggregation.py 3207-3268 |
| D2 | Zone aggregator non-sleep states | ~30 LoC | D1, `aggregation.py:3185-3205`, existing `zone_persons` accessor |
| D3 | House inference WAKING + GUEST sustained-signal | ~50 LoC | D1, `infer()` 444-449 (WAKING), 451-470 (GUEST) |
| D4 | Relocate `_check_zone_occupancy_confidence` | ~50 LoC (move + call-site rewire) | Existing body at `hvac.py:1350-1421`, single caller at `hvac.py:870` |
| D5 | `signal_consensus_confidence` calc + sensor + mirror attribute | ~120 LoC | `PresenceHouseStateSensor` 3579-3653, `HouseStateConfidenceSensor` 3656-3691 (kept untouched), `_run_inference` cycle |
| D6 | HVAC + compliance defer gates | ~60 LoC + 2 switches | `_apply_house_state_presets` (hvac.py:765+), `coordinator_diagnostics._emit_compliance_violation_anomaly` (line 524+), D5 consensus |
| Tests | Unit + cycle + AST | ~300 LoC | `quality/tests/` fixtures |
| **Total** | **~690 LoC + ~300 test LoC** | | |

Estimated review surface: ~1000 LoC including tests. Above the Tier-2-DB threshold (which the cycle already crosses on D5 + D6 schema/sensor changes alone).

---

## 3. Deliverables

### D1 — Shared veto helper on `PresenceCoordinator`

**Why.** v4.7.13 and v4.7.14 implement the same conceptual decision (`reliable_signal_says_X but transient_signal_says_Y → trust reliable`) in two different code locations with subtly different shapes (`aggregation.py:3207-3268` uses literal `state == "home"`; `presence.py:1903-1923` uses `(info.get("location") or "") in ("away", "")`). v4.7.15 unifies them so future cycles (v4.7.16 room level, v4.8.x scanner sparseness) don't fork the logic a third time.

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py`
**Site:** New module-level dataclass + new public method on `PresenceCoordinator` (insertion point after `confidence` property at line 621, before `get_next_state_prediction` at line 623).

**Dataclass.**
```python
@dataclass(frozen=True)
class VetoDecision:
    """Result of a Bug Class #48 transient-vs-reliable arbitration.

    fired: True iff the reliable signal vetoed the transient evidence.
    confidence: 0.0-1.0 confidence in the vetoed conclusion (only meaningful
                when fired=True). Mirrors the 1.0=good/0.0=bad scale used by
                inference_engine.confidence and signal_consensus.
    reason: Short human-readable reason for activity-log + diagnostics.
            Empty string when fired=False.
    """
    fired: bool
    confidence: float
    reason: str
```

**Helper signature.**
```python
def should_veto_due_to_reliable_signals(
    self,
    *,
    reliable_signals: list[ReliableSignal],
    transient_signals: list[TransientSignal],
    state_context: dict[str, Any],
) -> VetoDecision:
    """Bug Class #48 arbitration: when reliable signals agree on a negative
    conclusion AND no transient-signal carve-out applies, fire a veto.

    reliable_signals: list of (kind, value) tuples. kind ∈ {
        "person_tracker_away", "person_tracker_home", "zone_persons_home",
        "ble_proximity_present", "ble_proximity_absent",
    }
    transient_signals: list of (kind, count) tuples. kind ∈ {
        "camera_person_detected", "mmwave_occupied", "pir_motion",
        "unidentified_person_count",
    }
    state_context: dict with keys: "house_state", "zone_name" (optional),
        "tracked_count" (for empty-config fail-safe), "now" (datetime).

    Default returned VetoDecision is fired=False (preserves caller behavior
    when none of the documented patterns match). Callers can therefore add
    new patterns without breaking existing sites.
    """
```

The signature is **deliberately generic** rather than coding the two existing patterns as switches inside the helper, because:

1. v4.7.16 will need a room-level pattern (`scanner_areas` empty → trust phone over PIR).
2. v4.8.x BLE proximity work may want a fourth pattern (BLE absent + camera firing).
3. Each pattern is essentially "given this reliable signal kind + this transient signal kind + this state context, fire?". The helper enumerates known patterns internally and returns the first match.

**Implementation skeleton.**
```python
def should_veto_due_to_reliable_signals(
    self, *, reliable_signals, transient_signals, state_context,
):
    house_state = state_context.get("house_state", "")
    tracked_count = state_context.get("tracked_count", 0)

    # Pattern A — v4.7.14 house-inference AWAY veto.
    # Reliable: all_tracked_persons_away. Transient: camera_person_detected only.
    # Carve-out: unidentified_person_count > 0 (guest path).
    if state_context.get("scope") == "house_inference":
        all_away = any(s.kind == "person_tracker_away" and s.value for s in reliable_signals)
        any_home = any(s.kind == "person_tracker_home" and s.value for s in reliable_signals)
        unid = next((s.count for s in transient_signals if s.kind == "unidentified_person_count"), 0)
        if tracked_count > 0 and all_away and not any_home and unid == 0:
            return VetoDecision(True, 0.95, "all_tracked_persons_away (no guests)")

    # Pattern B — v4.7.13 zone-aggregator SLEEP fallback.
    # Reliable: zone_persons_home. Transient: room sensors quiet.
    # Carve-out: house_state must be "sleep".
    if state_context.get("scope") == "zone_aggregator" and house_state == "sleep":
        any_home = any(s.kind == "zone_persons_home" and s.value for s in reliable_signals)
        if any_home:
            return VetoDecision(True, 0.90, "zone_persons home during sleep")

    # Pattern C — v4.7.15 D2 zone-aggregator non-sleep states (new).
    # Reliable: zone_persons_home. Transient: room sensors quiet for >=N min.
    # Allowed in: HOME_DAY, HOME_EVENING, HOME_NIGHT, ARRIVING, GUEST, WAKING.
    if state_context.get("scope") == "zone_aggregator" and house_state in (
        "home_day", "home_evening", "home_night", "arriving", "guest", "waking",
    ):
        any_home = any(s.kind == "zone_persons_home" and s.value for s in reliable_signals)
        sensors_quiet_seconds = state_context.get("room_sensors_quiet_seconds", 0)
        # Conservative: only veto when sensors have been quiet > 5 min
        # (room going briefly dark while occupant is present is normal; we
        # only want to bridge the long structural-degeneration window).
        if any_home and sensors_quiet_seconds >= 300:
            return VetoDecision(True, 0.85, f"zone_persons home {house_state}")

    # Pattern D — v4.7.15 D3 WAKING sustained-signal gate (new).
    # Reliable: person_tracker_home AND mmwave_occupied sustained.
    # Transient: single camera_person_detected blip.
    if state_context.get("scope") == "waking_transition":
        sustained_seconds = state_context.get("sustained_occupancy_seconds", 0)
        any_home = any(s.kind == "person_tracker_home" and s.value for s in reliable_signals)
        if any_home and sustained_seconds >= 90:
            return VetoDecision(False, 0.85, "sustained occupancy confirms wake")
        return VetoDecision(True, 0.6, f"insufficient sustained signal ({sustained_seconds}s)")

    return VetoDecision(False, 0.0, "")
```

**Refactor of existing call sites.**

1. `aggregation.py:3201-3263` (`_sleep_person_fallback_occupied`) — refactor to delegate to `should_veto_due_to_reliable_signals` with `scope="zone_aggregator"`. Behavior must be byte-identical to v4.7.13: same WARN-once boot-race telemetry preserved. Test fixture from v4.7.13 must pass unchanged.

2. `presence.py:410-414` (the `all_tracked_persons_away` veto branch inside `infer()`) — **stays where it is** for now, but the `_run_inference` site at `presence.py:1903-1923` that computes `all_tracked_persons_away` will be augmented to also build a parallel `VetoDecision` via the new helper for logging + diagnostics. This is a no-op behavior change in v4.7.15 — the actual `infer()` veto firing path stays as v4.7.14 shipped. Reviewer B verify that the dispatcher payload at `presence.py:2089-2096` is unaffected (Bug Class #1 in DB cycle "payload shape preservation").

   Rationale for the split: we do NOT want to make `StateInferenceEngine.infer()` depend on `PresenceCoordinator` — the engine is a pure inner class used as a leaf unit in tests. So D1 wires the helper at the OUTER coordinator level only; `infer()` keeps its existing kwarg.

**Acceptance Criteria — D1**

- **Verify:** New dataclass `VetoDecision` defined at module scope (visible to test imports). Frozen, three fields.
- **Verify:** Helper is a public method on `PresenceCoordinator` (no underscore prefix), so it can be called from `aggregation.py` via `manager.coordinators["presence"]`.
- **Verify:** Helper has a default fall-through that returns `fired=False` — adding a new caller without a matching pattern is a no-op.
- **Verify:** v4.7.13 zone aggregator refactor preserves the WARN-once boot-race telemetry at `aggregation.py:3270-3287`. The `_warn_sleep_fallback_unavailable` method is NOT deleted; it is moved or retained at the call site of the helper, whichever the build agent finds simpler. Mark `[verify in build]` if simpler design emerges.
- **Verify:** v4.7.14 path leaves `infer()` veto behavior bit-identical. Only the OUTER `_run_inference` now also asks the helper for parallel diagnostics.
- **Sensor:** `sensor.ura_presence_house_state` attributes gain `last_veto_decision: {fired, confidence, reason, scope}` populated each `_run_inference` tick.
- **Test:** `test_veto_helper_pattern_a_house_inference_away_fires_when_all_away_no_guests`
- **Test:** `test_veto_helper_pattern_a_does_not_fire_with_unidentified`
- **Test:** `test_veto_helper_pattern_a_does_not_fire_with_empty_tracked_count`
- **Test:** `test_veto_helper_pattern_b_zone_sleep_fires_when_zone_persons_home`
- **Test:** `test_veto_helper_pattern_b_does_not_fire_outside_sleep`
- **Test:** `test_veto_helper_pattern_c_zone_non_sleep_fires_after_quiet_window`
- **Test:** `test_veto_helper_pattern_c_does_not_fire_before_quiet_window_threshold`
- **Test:** `test_veto_helper_pattern_d_waking_blocks_until_sustained`
- **Test:** `test_veto_helper_unknown_scope_returns_fired_false`
- **Test:** `test_aggregation_v4713_refactor_preserves_exact_behavior` — drive the v4.7.13 acceptance scenarios through the refactored path, assert identical `is_on` outputs.
- **Test:** `test_inference_v4714_refactor_preserves_exact_behavior` — drive v4.7.14 acceptance scenarios, assert identical `infer()` returns.
- **Live:** After deploy, the `last_veto_decision` attribute on `sensor.ura_presence_house_state` shows scope/reason/confidence values matching the active conditions. Observe overnight + workday-empty.

---

### D2 — Apply the helper at the zone aggregator level for non-sleep states

**Why.** v4.7.13 covers SLEEP only. The exact same sensor-degeneration patterns (mmWave dropping motionless body, camera blind in low light, PIR not firing on still occupant) happen during HOME_NIGHT (watching a movie still), HOME_DAY (working at desk still), ARRIVING (sitting in entry mudroom putting away gear), GUEST (guest reading on couch), and WAKING (occupant lying in bed before getting up). The structural sensor-coverage degeneration is the same; only the time-of-day differs.

**File:** `custom_components/universal_room_automation/aggregation.py`
**Site:** `ZoneAnyoneBinarySensor.is_on` at line 3185-3205. Add Layer 3 fallback AFTER existing Layer 2 (sleep) and BEFORE the final `return False`.

```python
# Layer 3 (v4.7.15 D2): non-sleep state-aware person-tracker fallback.
# Same Bug Class #48 pattern as Layer 2, broadened to other house states
# where the room can still be legitimately occupied by a still person.
if self._nonsleep_person_fallback_occupied():
    return True
```

Implementation of `_nonsleep_person_fallback_occupied()` calls the D1 helper with `scope="zone_aggregator"`, computes `room_sensors_quiet_seconds` from the existing per-room coordinator `data.get("last_motion_time")` lookup pattern already used at `hvac.py:1386-1390`.

**Quiet-window threshold:** 300 seconds (5 min). Below this, do NOT veto — room briefly going dark while occupant is in fact there is too noisy to override. The veto only bridges multi-minute structural degeneration.

**Acceptance Criteria — D2**

- **Verify:** Layer 3 only engages when `house_state ∈ {home_day, home_evening, home_night, arriving, guest, waking}`. Outside these states, falls through to existing return False.
- **Verify:** Layer 3 requires `sensors_quiet_seconds >= 300` (configurable constant `_NONSLEEP_QUIET_THRESHOLD_SECONDS = 300` at module scope).
- **Verify:** Layer 3 requires `zone_persons` non-empty AND at least one entity literally `state == "home"` (mirrors v4.7.13 conservative bias).
- **Verify:** Same WARN-once boot-race telemetry path as v4.7.13 reused for Layer 3 — extend the WARN-once cache key to `(zone_id, scope)` so SLEEP and non-sleep failures don't dedup-mask each other.
- **Sensor:** `binary_sensor.zone_<canonical>_anyone` reports `on` when at-desk occupant goes still for >5 min during HOME_DAY but their phone tracker says home.
- **Test:** `test_v4715_zone_layer3_fires_during_home_day_when_quiet_and_person_home`
- **Test:** `test_v4715_zone_layer3_does_not_fire_below_quiet_threshold`
- **Test:** `test_v4715_zone_layer3_does_not_fire_during_away_or_sleep` (sleep handled by Layer 2)
- **Test:** `test_v4715_zone_layer3_does_not_fire_when_zone_persons_all_not_home`
- **Test:** `test_v4715_zone_layer3_zone_persons_empty_no_fallback`
- **Live:** Workday simulation — operator at desk in study for 90 min, no motion, phone home, zone aggregator stays `on` continuously. Compare with pre-deploy baseline where aggregator flickered.

---

### D3 — Apply the helper at house-inference WAKING and GUEST transitions

**Why.** Today `infer()` transitions SLEEP → WAKING (presence.py:444-449) on ANY positive zone-occupied signal. That includes a single Frigate person-detect blip from a camera viewing the front porch at 03:24. The bedroom occupant is still asleep but URA flips house to WAKING, fires HVAC preset change, fan re-evaluates, room reacts. The fix: require sustained occupancy signal before honoring the WAKING transition — D1's Pattern D.

Similarly for GUEST entry: `guest_gate_armed` already has persistence guards (`_guest_persistence_seconds`, default 300 s) for the unidentified-person path. The `guest_room_gate_armed` path (`_guest_room_gate_armed`, v4.7.2 D5) needs a parallel sustained-signal check to prevent ghost-GUEST from a single camera blip in a guest room.

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py`
**Site 1 (WAKING):** Inside `_run_inference` between `infer()` return (line 1995-2002) and the manager transition acceptance (line 2026). Specifically: when `new_state == HouseState.WAKING` and the current state is SLEEP, consult the helper with `scope="waking_transition"`. If the helper returns `fired=True` (i.e., NOT sustained), set `new_state = None` to suppress the transition; record a `wake_blocked_ticks` counter for diagnostics.

**Site 2 (GUEST):** Augment `_guest_room_gate_armed` (existing at `_run_inference` ~1970) so that its arm flag requires the underlying signal to have been continuously asserted for ≥ `_guest_persistence_seconds`. **Verify in build that the existing v4.7.2 D5 implementation does not already do this** — if it does, D3 is a no-op for GUEST and only the WAKING half ships. Mark `[verify in build]`.

**Sustained-signal computation.** A new instance field on `PresenceCoordinator`:
```python
self._first_positive_zone_occupied_since: Optional[datetime] = None
```
Set when `any_zone_occupied` flips False → True; cleared when False. `sustained_occupancy_seconds = (now - first_positive_zone_occupied_since).total_seconds()`.

**Threshold:** 90 s. Aligns with `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300` lifetime — a 90 s requirement means the signal must be re-asserted at least 3 times (Frigate detection cadence is ~15-30 s) before WAKING fires. A single shadow-blip cannot satisfy it.

**Acceptance Criteria — D3**

- **Verify:** WAKING transition is BLOCKED when `sustained_occupancy_seconds < 90`. The block writes a debug log and increments `_wake_blocked_ticks` for diagnostics.
- **Verify:** WAKING transition fires normally when `sustained_occupancy_seconds >= 90`.
- **Verify:** The block does NOT affect any other state transition (AWAY, ARRIVING, HOME_*, GUEST, SLEEP entry) — verified by behavioral test re-running the entire v4.7.14 + v4.6.2.2 test corpus.
- **Verify:** `_first_positive_zone_occupied_since` resets to None when `any_zone_occupied` goes False, so a brief False → True → False → True burst cannot accumulate seconds.
- **Verify:** GUEST sustained-signal gate either added to `_guest_room_gate_armed` OR confirmed already present from v4.7.2 D5 (`[verify in build]`). If already present, document in plan-completion-tracking as "D3 GUEST half shipped retroactively in v4.7.2".
- **Sensor:** `sensor.ura_presence_house_state` attribute `wake_blocked_ticks` exposed; `wake_block_reason` attribute set to the helper's reason string when blocked.
- **Test:** `test_v4715_waking_blocked_below_sustained_threshold`
- **Test:** `test_v4715_waking_fires_after_sustained_threshold_met`
- **Test:** `test_v4715_waking_brief_burst_does_not_accumulate_sustained_seconds`
- **Test:** `test_v4715_first_positive_zone_occupied_since_resets_correctly`
- **Test:** `test_v4715_d3_does_not_affect_existing_state_transitions` — full corpus replay
- **Live:** Overnight observation — zero false WAKING transitions logged in `sensor.ura_coordinator_manager_last_activity` during the SLEEP window despite Frigate person blips on perimeter cameras.

---

### D4 — Relocate `_check_zone_occupancy_confidence` to PresenceCoordinator

**Why.** Today the multi-source occupancy confidence function lives in HVAC even though three of its four sources (motion via room coordinator data, BLE via `person_coordinator`, camera via Frigate person sensor) are presence concerns, not HVAC concerns. The fourth source (multi-room occupied) is also a presence concern. HVAC is the only caller today, but D5/D6 want the same function from the consensus calculator, and v4.7.16 will want it from room-level veto code. Sitting in HVAC blocks all of that without circular imports.

**Source file:** `custom_components/universal_room_automation/domain_coordinators/hvac.py:1350-1421` (`_check_zone_occupancy_confidence`).
**Destination file:** `custom_components/universal_room_automation/domain_coordinators/presence.py` (insert as public method on `PresenceCoordinator`, near the `should_veto_due_to_reliable_signals` helper).

**Renamed signature** (now public, lives on presence):
```python
def check_zone_occupancy_confidence(self, zone) -> tuple[int, int]:
    """Multi-source occupancy confidence for a zone.

    Migrated from hvac.py:1350 in v4.7.15 D4. Identical semantics.
    Returns (confirmed, possible) tuple — see original docstring.
    """
```

**Call site rewire.** `hvac.py:870`:
```python
# Before:
# confirmed, possible = self._check_zone_occupancy_confidence(zone)
# After:
presence = self.hass.data.get(DOMAIN, {}).get("presence_coordinator")
if presence is not None:
    confirmed, possible = presence.check_zone_occupancy_confidence(zone)
else:
    # Fail-safe: if presence coordinator not ready (boot race), behave
    # as if no confirmation — caller falls to stale-failsafe behavior
    # exactly as v3.22.2 originally intended.
    confirmed, possible = 0, 0
```

**Boot-race risk.** `hvac.py:870` is inside `_apply_house_state_presets`. `_apply_house_state_presets` is gated by `_house_state` (line 771); `_house_state` is initialized from presence at line 465-466 of HVAC `async_setup`. So by the time `_apply_house_state_presets` runs, presence coordinator must have been at least partially initialized. The None-fallback above is defensive belt-and-suspenders.

**Zone object type considerations.** `_check_zone_occupancy_confidence` reads `zone.rooms`, `zone.zone_cameras`, `zone.room_conditions`. These are attributes of HVAC's `Zone` dataclass (not the `ZonePresenceTracker` used by presence). The PRESENCE coordinator does not natively have access to HVAC's Zone dataclass shape. **The relocated method must accept the same `zone` parameter shape** — duck-typed — and the call site continues to pass HVAC's Zone object across the coordinator boundary. Reviewer C verify that this cross-coordinator typing does not introduce a regression.

**Acceptance Criteria — D4**

- **Verify:** Public method `check_zone_occupancy_confidence` exists on `PresenceCoordinator` and is reachable via `hass.data[DOMAIN]["presence_coordinator"]`.
- **Verify:** Behavior is byte-identical to v4.7.14 — same `(confirmed, possible)` tuple shape, same source ordering, same heuristics, same `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS` semantics not relied on (the original uses 30-min motion window, which is preserved).
- **Verify:** Old `_check_zone_occupancy_confidence` deleted from hvac.py.
- **Verify:** Call site at `hvac.py:870` rewired with None-fallback.
- **Verify:** No other file imports or calls `_check_zone_occupancy_confidence` (grep verified in §0.1 — currently single caller).
- **Test:** `test_d4_relocated_returns_identical_tuple_as_v4714` — drive the same fixture inputs that worked against the HVAC version, assert identical tuple outputs.
- **Test:** `test_d4_call_site_falls_back_when_presence_unavailable` — boot-race fail-safe.
- **Test:** AST regression test asserting `_check_zone_occupancy_confidence` no longer exists as a method on `HVACCoordinator` (prevents accidental restoration during merge).
- **Live:** D6 stale-failsafe behavior at `hvac.py:870-893` unchanged — verified by an overnight observation period where a zone occupied for `_max_occupancy_hours + 1` continues to log the same "X/Y sources confirm" pattern as before deploy.

---

### D5 — `signal_consensus_confidence` calculation + dedicated sensor + mirror attribute

**Why.** Today URA publishes `confidence` (the inference engine's certainty in the chosen state) but has no measure of input agreement. They are different concepts (INVESTIGATION §6.5 line 247-252):
- `confidence` = "engine settled on X with N% certainty"
- `signal_consensus` = "raw inputs agree with each other N% well at this instant"

`signal_consensus` is the earlier warning — it can drop before the engine has the chance to incorporate the disagreement into its output confidence. D5/D6 use it to defer downstream actuation.

**Implementation file:** `custom_components/universal_room_automation/domain_coordinators/presence.py`

**Calculation site:** Inside `_run_inference`, AFTER `infer()` returns (line 2002) and BEFORE the manager transition (line 2026). New instance field `self._signal_consensus: float = 1.0` initialized in `__init__`.

```python
# v4.7.15 D5: signal consensus calculation (1.0 = good, 0.0 = degraded).
camera_occupied_count = sum(
    1 for t in self._zone_trackers.values()
    if t._any_camera_occupied()  # noqa: SLF001 — public via .mode but raw count via _
)
mmwave_occupied_count = sum(
    1 for t in self._zone_trackers.values()
    if any(t._room_occupied.values())
)
# any_stale_or_lost_tracker — Bermuda or person tracker reporting "unknown"
# (intentionally distinct from "away" — see Bug Class #48 conservative bias)
person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
any_stale_or_lost_tracker = False
if person_coord and getattr(person_coord, "data", None):
    any_stale_or_lost_tracker = any(
        (info.get("location") or "") == "unknown"
        for info in (person_coord.data or {}).values()
    )

consensus = 1.0
if all_tracked_persons_away and any_zone_occupied:
    consensus -= 0.4
if any_stale_or_lost_tracker and not all_tracked_persons_away:
    consensus -= 0.2
if camera_occupied_count > 0 and mmwave_occupied_count == 0:
    consensus -= 0.15
if self._inference_engine.confidence < 0.85:
    consensus -= 0.1
self._signal_consensus = max(0.0, consensus)
```

**Dedicated sensor.** `sensor.ura_signal_consensus_confidence` — new `SignalConsensusConfidenceSensor` class in `sensor.py`, modeled on `HouseStateConfidenceSensor` (sensor.py:3656). Lives on `URA: Presence Coordinator` device. `native_value` returns `round(presence._signal_consensus, 2)`.

**Mirror attribute on rich sensor.** `PresenceHouseStateSensor.extra_state_attributes` (sensor.py:3614-3653) gains:
- `signal_consensus: float` (current value)
- `signal_consensus_band: str` (decorative: `"high"` if ≥0.85, `"moderate"` if ≥0.6, `"low"` if ≥0.3, else `"degraded"`)
- `signal_consensus_inputs: dict` (snapshot of the 4 boolean contributors so operators can debug why consensus dropped)

**Confidence dimension table** (preserved from §6.5):

| Surface | Source | Update cadence |
|---|---|---|
| `sensor.ura_house_state_confidence` (existing, untouched) | `presence._inference_engine.confidence` | Per state transition |
| `sensor.ura_presence_house_state` attribute `confidence` (existing, untouched) | Same as above | Same |
| `sensor.ura_signal_consensus_confidence` (NEW) | `presence._signal_consensus` | Per `_run_inference` cycle |
| `sensor.ura_presence_house_state` attribute `signal_consensus` (NEW) | Same as above | Same |

Both dimensions on the same 1.0=good / 0.0=bad scale.

**Divergence flag.** The investigation §6.5 explicitly recommended attribute-only, no dedicated sensor. Operator brief explicitly says BOTH. We ship BOTH. Reviewer C is invited to assess whether the dedicated sensor is justified given §6.5's argument that the mirror attribute is sufficient. If the reviewer recommends collapsing to attribute-only, defer the dedicated sensor to a deprecation cycle (do not block ship on this).

**Acceptance Criteria — D5**

- **Verify:** `self._signal_consensus` field initialized to 1.0 in `__init__`.
- **Verify:** Calculation runs every `_run_inference` cycle, even when `new_state is None` (this is the entire point — consensus tracks inputs in motion, not transitions).
- **Verify:** All 4 contribution clauses applied in stated order; `max(0.0, ...)` floor enforced.
- **Verify:** New sensor `sensor.ura_signal_consensus_confidence` registered on `URA: Presence Coordinator` device, `_attr_unique_id = "{DOMAIN}_signal_consensus_confidence"`.
- **Verify:** Mirror attributes `signal_consensus`, `signal_consensus_band`, `signal_consensus_inputs` present on `sensor.ura_presence_house_state`.
- **Verify:** Existing `sensor.ura_house_state_confidence` and existing `confidence` attribute untouched (no regression). Manually grep diff verified by reviewer.
- **Verify:** Bug Class #47 mitigation — the dedicated sensor uses LAZY computation (`native_value` reads from `presence._signal_consensus` at read time). Does NOT persist into entry.options or registry.
- **Sensor:** `sensor.ura_signal_consensus_confidence` = 1.0 in calm steady state; drops to ≤0.6 within one `_run_inference` cycle after a Bug-Class-#48-shape disagreement (cameras fire while phones away).
- **Sensor:** Mirror attribute matches dedicated sensor value at all times.
- **Test:** `test_signal_consensus_starts_at_1_0`
- **Test:** `test_signal_consensus_drops_by_0_4_on_camera_vs_phone_disagreement`
- **Test:** `test_signal_consensus_drops_by_0_2_on_stale_tracker`
- **Test:** `test_signal_consensus_drops_by_0_15_on_camera_only_occupancy`
- **Test:** `test_signal_consensus_drops_by_0_1_on_low_state_confidence`
- **Test:** `test_signal_consensus_floors_at_0_0`
- **Test:** `test_signal_consensus_band_high_above_0_85`
- **Test:** `test_signal_consensus_band_degraded_below_0_3`
- **Test:** `test_dedicated_sensor_value_matches_mirror_attribute`
- **Test:** `test_existing_confidence_attribute_unchanged_when_consensus_added`
- **Live:** During the v4.7.14 ghost-presence scenario (phones away, cameras firing), pre-deploy compares baseline — `sensor.ura_house_state_confidence` was 0.85-0.95. Post-deploy — `sensor.ura_signal_consensus_confidence` should be ≤0.6 in the same instant (the disagreement is now visible).

---

### D6 — HVAC + compliance defer gates driven by `signal_consensus`

**Why.** When consensus is degraded, the inference engine's chosen state is itself less trustworthy. Acting on it (flipping HVAC presets, firing compliance violations) amplifies the noise. The defer gate buys 30-60 seconds for the inputs to settle.

**File 1:** `custom_components/universal_room_automation/domain_coordinators/hvac.py` — `_apply_house_state_presets` (line 765+).

**Gate logic** (added near top of `_apply_house_state_presets`, after the `if not self._house_state: return` guard at line 771):
```python
# v4.7.15 D6: HVAC defer gate driven by signal_consensus.
# When consensus is degraded AND the last house-state transition was recent,
# defer non-critical preset writes. Critical events (CO2, fire, safety hazard
# fired from safety coordinator) bypass — they call dedicated paths, not this.
presence = self.hass.data.get(DOMAIN, {}).get("presence_coordinator")
if presence is not None and self._defer_gate_enabled:
    consensus = getattr(presence, "_signal_consensus", 1.0)
    last_transition = getattr(presence, "_last_transition_time", None)
    now = dt_util.utcnow()
    secs_since_transition = (
        (now - last_transition).total_seconds() if last_transition else 1e9
    )
    # Asymmetric hysteresis: defer if <0.5, resume only at >0.7.
    if consensus < 0.5 and secs_since_transition < 30:
        _LOGGER.info(
            "v4.7.15 D6: HVAC preset write deferred — consensus=%.2f, "
            "secs_since_transition=%.0f",
            consensus, secs_since_transition,
        )
        self._d6_deferrals_today += 1
        return  # skip — next cycle will retry
```

**Operator switch.** New switch entity `switch.ura_hvac_consensus_defer_gate` controls `self._defer_gate_enabled` (default True). Provides operator-level kill-switch for rollback without restart. Mirrors the existing observation-mode switch pattern (`switch.ura_presence_observation_mode`).

**Diagnostic counter.** `self._d6_deferrals_today` reset daily by the existing midnight reset hook in HVAC. Exposed as attribute on `sensor.ura_hvac_coordinator_compliance` (existing sensor).

**File 2:** `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py` — `_emit_compliance_violation_anomaly` (line 524).

**Gate logic** (added at top of the method, before the existing logic):
```python
# v4.7.15 D6: Compliance violation defer gate.
# Same Bug Class #48 logic: when inputs disagree sustained, the violation
# itself is likely a downstream symptom of the disagreement, not a true
# user override. Defer when consensus has been below 0.6 for ≥60s.
presence = self.hass.data.get(DOMAIN, {}).get("presence_coordinator")
if presence is not None and self._compliance_defer_gate_enabled:
    consensus = getattr(presence, "_signal_consensus", 1.0)
    consensus_low_since = getattr(presence, "_consensus_low_since", None)
    if consensus < 0.6 and consensus_low_since is not None:
        secs_low = (dt_util.utcnow() - consensus_low_since).total_seconds()
        if secs_low >= 60:
            _LOGGER.info(
                "v4.7.15 D6: Compliance violation suppressed — consensus=%.2f "
                "sustained for %.0fs",
                consensus, secs_low,
            )
            return  # do not emit
```

**Supporting state.** PresenceCoordinator gains `_consensus_low_since: Optional[datetime] = None` updated each `_run_inference`:
```python
if self._signal_consensus < 0.6:
    if self._consensus_low_since is None:
        self._consensus_low_since = dt_util.utcnow()
else:
    self._consensus_low_since = None
```

**Operator switch.** New switch `switch.ura_compliance_consensus_defer_gate` (default True).

**Critical-event bypass.** Safety coordinator already short-circuits the standard preset/policy path for true hazard events (`safety.py:1300+` HazardEvent flow). The D6 gate in HVAC sits inside `_apply_house_state_presets` and is bypassed entirely by `_apply_house_state_presets_emergency_override` (if it exists — `[verify in build]`). No additional bypass code needed at D6 level; safety paths already do not go through these gates.

**Acceptance Criteria — D6**

- **Verify:** HVAC gate fires only when ALL of: `consensus < 0.5`, `secs_since_transition < 30`, `self._defer_gate_enabled == True`.
- **Verify:** HVAC gate resumes normal at `consensus > 0.7` (40-pt hysteresis observable via test).
- **Verify:** Compliance gate fires only when `consensus < 0.6` sustained `≥ 60s` (one-cycle drops don't suppress).
- **Verify:** Both gates can be disabled via switch without HA restart.
- **Verify:** Critical safety paths (CO2, fire, hazard) do NOT go through `_apply_house_state_presets` — verified by grep.
- **Verify:** `_consensus_low_since` resets to None when consensus recovers to ≥ 0.6.
- **Verify:** Backward compatibility — gates default to ENABLED but operator can disable for rollback.
- **Sensor:** `switch.ura_hvac_consensus_defer_gate` registered, default ON, lives on Coordinator Manager device.
- **Sensor:** `switch.ura_compliance_consensus_defer_gate` registered, default ON.
- **Sensor:** `sensor.ura_hvac_coordinator_compliance` attribute `d6_deferrals_today` exposes the counter.
- **Sensor:** `sensor.ura_presence_house_state` attribute `consensus_low_since` exposes the start timestamp (or None).
- **Test:** `test_d6_hvac_gate_fires_below_0_5_within_30s_of_transition`
- **Test:** `test_d6_hvac_gate_does_not_fire_above_0_5`
- **Test:** `test_d6_hvac_gate_resumes_at_0_7_hysteresis`
- **Test:** `test_d6_hvac_gate_does_not_fire_after_30s_window` — old transition, gate inactive
- **Test:** `test_d6_hvac_gate_disabled_via_switch`
- **Test:** `test_d6_compliance_gate_requires_sustained_60s_low`
- **Test:** `test_d6_compliance_gate_does_not_suppress_brief_dip`
- **Test:** `test_d6_compliance_gate_disabled_via_switch`
- **Test:** `test_d6_consensus_low_since_resets_on_recovery`
- **Test:** AST regression — confirm `_apply_house_state_presets` is the ONLY HVAC entry point gated by D6; emergency / safety paths bypass.
- **Live:** During the same v4.7.14 ghost-presence scenario, observe HVAC log lines reporting "preset write deferred — consensus=0.45" instead of cycling presets. AC actuation count over the empty-house window should drop from N (pre-deploy) to ≤2 (post-deploy).
- **Live:** No new compliance violations recorded in `compliance_log` table during the ghost-presence window; pre-deploy baseline showed M violations.

---

## 4. Out of scope

- **Room-level veto (v4.7.16).** D2 explicitly stops at the ZONE aggregator. The same Bug Class #48 patterns at the ROOM level — where the room-coordinator computes whether a single room is occupied — are deferred to v4.7.16. Helper supports the pattern (Pattern C is shaped to accept it) but no room-level call site is wired in v4.7.15.
- **Sparse-room detection via `CONF_SCANNER_AREAS` (v4.7.16).** `CONF_SCANNER_AREAS` is a v3.2.4-era field (`const.py:317`, `config_flow.py:995`) used today by person_coordinator's BLE proximity mapping. v4.7.16 will wire it as a room-level weighting input (sparse rooms weight phone tracker higher). **DO NOT rebuild this field. DO NOT touch config_flow at all in v4.7.15.**
- **Per-room camera opt-out** (`CONF_DISABLE_CAMERA_PRESENCE` from INVESTIGATION §7). Operator brief lists this as "could fold here or to v4.7.16 — recommend; verify with operator." **Recommendation: defer to v4.7.16.** Rationale: it is a config-flow change that touches a different surface (per-room camera registration in `_async_setup_zone_cameras` at `presence.py:1100+`), and v4.7.15 is already at Tier-2-DB scope. Folding camera opt-out adds review surface that risks crowding D1-D6. Operator may override; if so, add as D7.
- **Frigate vs Protect durability audit** (INVESTIGATION Part B). Separate cycle.
- **Camera motion (non-person) signal classification.** Per investigation §2.1, URA does not consume `*_motion` for presence today; v4.7.15 does not touch this. Separate cycle.
- **`sensor.ura_house_state_confidence` deprecation.** Investigation §6.5 line 254 suggests deprecate-then-delete in v5.0 after operator audits. v4.7.15 does NOT deprecate this — it adds the consensus dimension alongside. Reviewer C noted in §0.6 may recommend collapsing dedicated to attribute; defer to follow-up.

---

## 5. Bug-class watchlist

| Class | Risk in this cycle | Mitigation |
|---|---|---|
| #11 (UTC vs local TZ) | D3 / D6 use `dt_util.utcnow()` for `_first_positive_zone_occupied_since` and `_consensus_low_since`. | Test enforces all new datetime fields use `utcnow()`; AST regression for `dt_util.now()` outside known-OK sites. |
| #14 (config snapshot staleness) | D6 reads `self._defer_gate_enabled` per cycle — must reflect switch state without restart. | Switch entity drives the field via `async_turn_on/off` writing `self._defer_gate_enabled`. Test verifies switch toggle reflects in same cycle. |
| **#20 (concurrent reload race)** | D5 adds a new dedicated sensor. D6 adds two new switches. All three are entity additions that must be idempotent across reload. | Use `async_add_entities` discovery path the same as existing `HouseStateConfidenceSensor` (sensor.py:3656). No registry mutations from coordinator code. AST regression test confirms no `entity_registry.async_update_entity` from D5/D6 code. |
| #22 (enum mismatch) | D3 compares `current_state` to `HouseState.SLEEP` (enum) — D1 helper takes `house_state` as string. | Verify in build: D1 helper accepts both `"sleep"` (str) and `HouseState.SLEEP` via `str(house_state).lower()` normalization. Test covers both inputs. |
| #23 (incomplete observation mode gating) | D6 gates HVAC writes. Observation mode also gates HVAC writes. Verify they compose correctly (observation mode is stricter — when ON, all writes suppress; D6 only suppresses when consensus AND recency are bad). | Verify the gates compose via short-circuit: D6 gate runs after observation-mode gate (`hvac.py:~820`). Test for observation-mode=ON + consensus=high — writes still suppressed. |
| #26 (in-memory only reads) | D5 consensus state read from presence in-memory only — no DB round-trip. | Acceptable — consensus is per-tick metric, not persisted. |
| **#33 (sibling helpers skipped)** | D1 unifies the helper. Are there other sites with the same shape that get missed? E.g., security coordinator after-hours arming logic, music_following BLE proximity arbitration. | Reviewer A explicitly tasked with sibling-helper sweep. Mandatory grep for `not_home|away|home` filter patterns across all `domain_coordinators/*.py` BEFORE the build commits. |
| #38 (untracked unsub) | D6 switches register `async_added_to_hass` listeners. | Switches use standard SwitchEntity inheritance — no manual listeners. AST test confirms zero `bus.async_listen` outside known-OK sites. |
| #42 (lambda + async_create_task) | D3 `_first_positive_zone_occupied_since` set/cleared synchronously inside `_run_inference`. No scheduling. | None — no new scheduling in this cycle. |
| **#44 (cross-file sys.modules pollution / test fixture authority)** | D5 sensor + D6 switches need behavioral test infrastructure against real schemas — and D1 helper must drive existing production code paths in v4.7.13 + v4.7.14 acceptance fixtures. | Reviewer C explicitly tasked with fixture authority audit. Tests MUST drive `aggregation.py:_sleep_person_fallback_occupied` and `presence.py:_run_inference` directly — no shadow re-implementations. |
| #46 (async_update_entry re-entrancy) | None — no config-entry mutations. | N/A |
| **#47 (lazy canonical UI surface violation)** | D5 dedicated sensor must compute via `native_value` at read time, NOT persist into entry.options. Risk if mirror attribute and dedicated sensor disagree. | Test: assert `presence._signal_consensus` and `sensor.ura_signal_consensus_confidence.native_value` and `sensor.ura_presence_house_state.attributes["signal_consensus"]` all match at every tick. |
| **#48 (transient-vs-reliable)** | THIS IS THE CYCLE. | All deliverables are exemplars of the fix pattern. Helper enforces conservative bias (Pattern A `unidentified_count == 0` carve-out, Pattern B `house_state == "sleep"` strict gate). |

---

## 6. Tier 2-DB review framing

Per `feedback_db_sensitive_3x_targeted_reviews.md` and CLAUDE.md Tier 2-DB protocol. Three parallel reviewers, three explicit framings.

### Reviewer A — Correctness + state-machine boundaries + sustained-signal logic

- v4.7.13 and v4.7.14 acceptance scenarios still pass byte-identically after D1 refactor.
- D3 sustained-signal threshold (90 s) is defensible against the Frigate cadence math (≥3 confirmations required).
- D2 quiet-window threshold (300 s) is defensible against legitimate-occupant scenarios (person at desk for 6 min should still be occupied).
- WAKING / GUEST transition gates do NOT block legitimate transitions — full state-machine regression test corpus replayed.
- VetoDecision dataclass invariants (frozen, three fields, default fired=False).
- Sibling helper grep: ANY other coordinator with a "filter not_home/away" pattern that should also use D1 helper? Surface them as MEDIUM if found; do not add to v4.7.15 scope — file for v4.7.16+.

### Reviewer B — Cross-coordinator interactions + signal_consensus computation + dispatch payload preservation

- D4 relocation: HVAC `_apply_house_state_presets` at line 870 produces equivalent behavior; downstream signal/dispatch unchanged.
- D5 consensus calculation: each of the 4 contribution clauses produces the expected delta in isolation AND in combination (truth-table test).
- D5 dispatcher payload at `presence.py:2089-2096` is UNCHANGED — `confidence` still flows, no field renames, no shape mutation.
- D6 HVAC gate composes correctly with observation-mode gate (short-circuit order).
- D6 compliance gate composes correctly with the existing 60 s dedup window at `coordinator_diagnostics.py:569` — verify the two 60 s windows are independent and do not interlock.
- `_consensus_low_since` lifecycle: set / clear / boot / unload paths all leave the field in a consistent state.
- Switch state changes propagate to coordinator behavior on the SAME tick (no restart required).

### Reviewer C — Test fixture authority + refactor risk of relocating `_check_zone_occupancy_confidence` + parallel-merge risk with v4.7.14.1 and v4.7.16

- Behavioral test fixtures for D1 derive from PRODUCTION schemas / call paths (Bug Class #44). No hand-copied dataclass shapes; no shadow VetoDecision in tests.
- D1 acceptance tests for v4.7.13 / v4.7.14 preservation drive the REAL refactored production paths (`_sleep_person_fallback_occupied`, `_run_inference`), not stubs.
- D4 cross-coordinator typing of `zone` parameter: HVAC's `Zone` dataclass passed across to PresenceCoordinator — verify no AttributeError risk, verify no circular import.
- D5 dedicated sensor + mirror attribute coherence: assess INVESTIGATION §6.5's argument for attribute-only and either ratify the operator brief (ship both) or recommend collapsing.
- Parallel-merge risk: v4.7.14.1 hotfix branch (if any) and v4.7.16 planning may both touch presence.py near 1900-2000 and aggregation.py near 3185-3270. Recommend merge order: v4.7.14.x first → v4.7.15 → v4.7.16. Surface specific conflict zones for the deploy agent.
- Pre-deploy snapshot of row rates in `house_state_log` and `compliance_log` tables — required by Tier 2-DB protocol. Capture pre-deploy median rows/hour for both tables; post-deploy must be within ±25% during a same-shape time window (excluding deploy moment + 30 min).

---

## 7. Backward compatibility statements

| Surface | Pre-v4.7.15 | Post-v4.7.15 | Compatibility |
|---|---|---|---|
| `sensor.ura_house_state_confidence` | Returns inference confidence | Returns inference confidence | UNCHANGED |
| `sensor.ura_presence_house_state` attr `confidence` | Inference confidence | Inference confidence | UNCHANGED |
| `sensor.ura_presence_house_state` attr `tracked_persons_count`, `all_tracked_persons_away` | v4.7.14 attrs | v4.7.14 attrs | UNCHANGED |
| `sensor.ura_signal_consensus_confidence` | DID NOT EXIST | NEW; defaults to 1.0 in calm state | NEW (additive) |
| `sensor.ura_presence_house_state` attrs `signal_consensus`, `signal_consensus_band`, `signal_consensus_inputs`, `last_veto_decision`, `wake_blocked_ticks`, `consensus_low_since` | DID NOT EXIST | NEW; defaults conservative | NEW (additive) |
| `switch.ura_hvac_consensus_defer_gate` | DID NOT EXIST | NEW; default ON | NEW (additive); set OFF to disable D6 HVAC gate |
| `switch.ura_compliance_consensus_defer_gate` | DID NOT EXIST | NEW; default ON | NEW (additive); set OFF to disable D6 compliance gate |
| `HVACCoordinator._check_zone_occupancy_confidence` | Existed at `hvac.py:1350` | DELETED | Internal method, single caller migrated; no external callers (verified §0.1) |
| `PresenceCoordinator.check_zone_occupancy_confidence` | DID NOT EXIST | NEW public method | NEW (additive); same `(int, int)` tuple shape as old HVAC method |
| `PresenceCoordinator.should_veto_due_to_reliable_signals` | DID NOT EXIST | NEW public method | NEW (additive) |
| `StateInferenceEngine.infer()` signature | `all_tracked_persons_away` kwarg (v4.7.14) | Same signature | UNCHANGED |
| `SIGNAL_HOUSE_STATE_CHANGED` dispatcher payload | `{old_state, new_state, trigger, confidence}` (v4.7.14) | Same shape | UNCHANGED — Reviewer B verifies. |
| `house_state_log` DB row shape | `state, confidence, trigger, previous_state` | Same | UNCHANGED |
| `compliance_log` DB row shape | Pre-v4.7.15 shape | Same; fewer rows when defer gate active | UNCHANGED (shape) |
| `aggregation.py:_warn_sleep_fallback_unavailable` WARN-once telemetry | v4.7.13 behavior | Preserved, cache key extended to `(zone_id, scope)` | EXTENDED (backward-compatible: existing log line format kept) |

**Default for every new switch / sensor / config: preserve pre-v4.7.15 behavior.** Defer gates default ON (they only fire when consensus is degraded, which by definition was not visible pre-v4.7.15 — so the only behavioral change in normal operation is "fewer needless preset flips during ghost-presence windows", which is the goal).

---

## 8. Live validation criteria

Per Tier 2-DB Review D protocol.

### Pre-deploy snapshot

- Median `house_state_log` rows/hour over the prior 72 h (Reviewer C captures via MCP `ura-sqlite`).
- Median `compliance_log` rows/hour over prior 72 h.
- Current value of `sensor.ura_house_state_confidence` (steady-state expectation: ~0.85-0.95).
- Existence check: `sensor.ura_signal_consensus_confidence` does NOT exist (will be NEW).

### Post-deploy verification (Review D — within 1 hour of restart)

- `sensor.ura_signal_consensus_confidence` exists and registers a non-None numeric value.
- `sensor.ura_presence_house_state` attribute `signal_consensus` matches the dedicated sensor.
- `switch.ura_hvac_consensus_defer_gate` exists, default ON.
- `switch.ura_compliance_consensus_defer_gate` exists, default ON.
- One row in `house_state_log` with non-zero NOT NULL columns within 1 h of restart — payload shape integrity check.
- `last_veto_decision` attribute on rich sensor reads a non-default value if conditions allow (or `{fired: false, reason: ""}` if calm).

### Post-deploy verification (Review D — over 24 h workday window when phones away)

- Zero `away → arriving → home_day → away` bounces in `sensor.ura_coordinator_manager_last_activity` while all persons away.
- `sensor.ura_signal_consensus_confidence` drops below 0.6 within one inference cycle of the Frigate ghost-detect.
- HVAC preset write count over the empty-house window drops ≥75% vs pre-deploy baseline.
- `d6_deferrals_today` counter on `sensor.ura_hvac_coordinator_compliance` registers ≥1 over the window.
- Compliance violation row count over the window drops ≥50% vs pre-deploy baseline.

### Rollback procedure (operator-runnable, no restart needed)

If post-deploy validation surfaces a regression:

1. **Turn off D6 HVAC gate.** Switch `switch.ura_hvac_consensus_defer_gate` to OFF. HVAC reverts to v4.7.14 behavior (no consensus-based defer).
2. **Turn off D6 compliance gate.** Switch `switch.ura_compliance_consensus_defer_gate` to OFF. Compliance violations resume at v4.7.14 cadence.
3. D5 sensors are read-only — no rollback needed; they keep publishing values but nothing acts on them.
4. D1-D4 are pure refactors with preserved behavior — no operational rollback path needed for these alone. If a regression is in D1-D4, full revert to v4.7.14 via `scripts/deploy.sh` rollback.

Both D6 switches and the D5 sensors are designed so the cycle can be "soft-disabled" (gates OFF) without losing the visibility of consensus values. Operator can run with D5 only (visibility) while debugging a D6 regression.

---

## 9. README requirements

`docs/readmes/README_v4.7.15.md` MUST include:

1. **Operator runbook — what changes day-to-day:**
   - HVAC may defer preset writes for up to 30 s when consensus drops below 0.5; this is intentional.
   - During a deferral, log lines `"v4.7.15 D6: HVAC preset write deferred"` will appear in HA core log.
   - Compliance violations may be suppressed for up to 60 s of sustained-low consensus.
   - Critical safety paths (CO2, fire, smoke, hazard) are UNCHANGED and never deferred.

2. **New sensors / switches the operator will see:**
   - `sensor.ura_signal_consensus_confidence`
   - `sensor.ura_presence_house_state` attributes: `signal_consensus`, `signal_consensus_band`, `signal_consensus_inputs`, `last_veto_decision`, `wake_blocked_ticks`, `consensus_low_since`
   - `switch.ura_hvac_consensus_defer_gate` (default ON)
   - `switch.ura_compliance_consensus_defer_gate` (default ON)

3. **Rollback procedure** (literal switch toggles, see §8 above).

4. **Pre/post snapshot guide:**
   - How to capture `sensor.ura_house_state_confidence` median and ranges.
   - How to capture `sensor.ura_signal_consensus_confidence` (will not exist pre-deploy — note as such).
   - SQL queries for `house_state_log` and `compliance_log` row rates.

5. **Bug Class #48 expansion** — note that v4.7.15 generalizes the pattern across four layers (zone aggregator, house inference, HVAC defer, compliance defer) and reference the v4.7.13 / v4.7.14 originals.

6. **Hand-off to v4.7.16** — note explicitly that room-level veto and sparse-room weighting via `CONF_SCANNER_AREAS` are out-of-scope for v4.7.15 and slated for v4.7.16.

---

## 10. Hand-off to v4.7.16

v4.7.16 will:
1. Add a room-level call site for the D1 helper using `scope="room_occupancy"` (Pattern E — TBD shape).
2. Weight `check_zone_occupancy_confidence` BLE source higher in sparse rooms via `CONF_SCANNER_AREAS` membership.
3. Optionally fold `CONF_DISABLE_CAMERA_PRESENCE` per-room camera opt-out from INVESTIGATION §7.

**v4.7.15 must NOT:**
- Touch `config_flow.py` (no new room config fields).
- Touch `CONF_SCANNER_AREAS` definition or any caller.
- Modify `RoomCoordinator` occupancy aggregation logic at the room level.
- Pre-create call sites for "Pattern E" — the helper accepts unknown `scope` and returns `fired=False`, which is the design for forward compatibility.

This keeps the v4.7.15 / v4.7.16 layer separation clean.

---

## 11. Plan completion tracking

After implementation, document explicitly:

- D1-D6 status (shipped, partial, deferred)
- Whether the GUEST half of D3 was newly added or confirmed retroactive from v4.7.2 D5
- Whether D5 ended up shipping BOTH the dedicated sensor AND the mirror attribute, or collapsed per Reviewer C
- D4 relocation cleanliness — confirm zero remaining `_check_zone_occupancy_confidence` references in HVAC
- Pre/post snapshot deltas for `house_state_log` rows/hour and `compliance_log` rows/hour
- Live overnight + workday observation evidence (zero away/arrive bounces; consensus drops on ghost-presence; HVAC deferrals counted)
- Any sibling helpers Reviewer A surfaced that should be filed for v4.7.16+
- Any out-of-scope items the operator overrode (e.g., camera opt-out D7)

---

## 12. References

- v4.7.13 plan + ship: `docs/planning/PLANNING_v4.7.13_sleep_state_zone_presence_trust.md`, fix-up MEDIUM-2 in `aggregation.py:3270-3287`
- v4.7.14 plan + ship: `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md`, veto branch at `presence.py:410-414`
- INVESTIGATION §6.5: `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` line 190-275
- Bug Class #48: `docs/QUALITY_CONTEXT.md` line 1855-1905 (filed 2026-05-30)
- Tier 2-DB protocol: `CLAUDE.md` § "Tier 2-DB: DB-Sensitive Feature Cycle"
- Source — helper to relocate: `custom_components/universal_room_automation/domain_coordinators/hvac.py:1350-1421`
- Source — helper single caller: `custom_components/universal_room_automation/domain_coordinators/hvac.py:870`
- Source — v4.7.14 call-site computation: `custom_components/universal_room_automation/domain_coordinators/presence.py:1896-1926`
- Source — v4.7.14 veto inside infer: `custom_components/universal_room_automation/domain_coordinators/presence.py:403-414`
- Source — v4.7.13 zone aggregator: `custom_components/universal_room_automation/aggregation.py:3185-3287`
- Source — rich sensor attributes (v4.7.14 baseline): `custom_components/universal_room_automation/sensor.py:3579-3653`
- Source — dedicated confidence sensor (untouched): `custom_components/universal_room_automation/sensor.py:3656-3691`
- Source — compliance violation emit site: `custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py:524-588`
- Source — HVAC `_apply_house_state_presets` start: `custom_components/universal_room_automation/domain_coordinators/hvac.py:765`
- Source — `CONF_SCANNER_AREAS` (v4.7.16, NOT touched here): `custom_components/universal_room_automation/const.py:317`, `config_flow.py:995`
- Memory: `feedback_db_sensitive_3x_targeted_reviews.md`, `feedback_pre_deploy_zero_bugs_gate.md`, `feedback_verify_hacs_install.md`

## 13. Recall

- "Plan v4.7.15 universalize Bug Class #48 veto"
- "Resume v4.7.15 universalize veto"
- "Apply consensus defer gates"

---

## 14. Operator-decision addendum (2026-05-30, post-planner-return)

The planner correctly flagged two scope decisions for operator. Both resolved here:

### D5 — Keep BOTH dedicated sensors AND mirror attributes

The planner brief said "BOTH dedicated sensor + mirror attribute"; the investigation memo §6.5 (as last-edited at planning time) said "attribute-only + deprecate standalone." Operator decision: **keep both.** The plan's D5 as-written is correct. The investigation memo has been updated to align.

Final design (no change to plan):
- `sensor.ura_house_state_confidence` (existing, no entity-ID change)
- `sensor.ura_signal_consensus_confidence` (new, ships in this cycle)
- Mirror attributes on `sensor.ura_presence_coordinator_presence_house_state`: `confidence` (already there) + `signal_consensus` (new) + `consensus_band` (decorative)

The earlier "deprecate the standalone confidence sensor" candidate is **withdrawn from v4.7.16 scope**.

### D3 GUEST half — Verified, gap found, scope clarified

Planner correctly flagged the GUEST sustained-signal coverage as `[verify in build]`. Verification done at 2026-05-30 by direct code reading:

**Already shipped by v4.7.2 D5 (do NOT duplicate):**
- `_guest_gate_armed` at `presence.py:1777-1843` — three-guard GUEST **entry** detection (existence + confidence + persistence with arming + scheduled recheck)
- `_guest_room_gate_armed` at `presence.py:1751-1775` — sustained-occupancy threshold (operator-tunable `threshold_min`, default 30)
- Bug Class #11 UTC-aware timestamps throughout

**Material gap that D3 GUEST half MUST close (asymmetry v4.7.2 D5 deliberately left):**
- GUEST → HOME_* **exit** is immediate. At `presence.py:467-469`:
  ```python
  if current_state == HouseState.GUEST and unidentified_count == 0 and not guest_gate_armed:
      return self._time_based_home(hour)
  ```
- A single frame where Frigate misclassifies and `unidentified_count` drops to 0 → GUEST exits to HOME_*. No exit-side persistence guard mirrors the entry-side one.
- v4.7.2 D5's `_guest_room_gate_armed` docstring at line 1758 explicitly states "Exit is immediate" — deliberate at the time, but now leaves the cycle vulnerable to single-frame Frigate FP ghost-exit.

**D3 GUEST half scope (revised from planner's `[verify in build]` placeholder):**
- Add an **exit-side sustained-signal guard** for the GUEST → HOME_* transition. Mirror the entry-side `_unidentified_first_seen` + `_schedule_guest_persistence_recheck` pattern at lines 1813-1843, but inverted (require N seconds of `unidentified_count == 0 AND not guest_gate_armed` before firing the exit).
- Reuse the v4.7.15 D1 shared veto helper. The helper's "transient signal needs N seconds to overcome reliable signal" pattern is exactly what this gap needs.
- **DO NOT touch `_guest_gate_armed` or `_guest_room_gate_armed`** — those are correct as-is and were the v4.7.2 D5 cycle.
- Test: `test_d3_guest_exit_persists_against_single_frame_frigate_fp`.
- Operator config: reuse existing `_guest_persistence_seconds` for the exit guard (symmetric with entry) unless reviewer prefers a separate exit-side number.

This narrows D3 GUEST scope from "build new GUEST sustained-signal" (which would have duplicated v4.7.2 D5) to "close the deliberate v4.7.2 D5 exit-side asymmetry." Smaller LoC, cleaner cycle, no rebuild.
