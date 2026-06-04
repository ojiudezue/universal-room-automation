# PLANNING v4.7.18 — Census Service Shared Refactor + Phantom Tracker Filter + Tier Signals

**Tier:** 2 (operator-elevated Tier 2-DB per CLAUDE.md — touches `camera_census.py` aggregation + dispatch payload + presence consumer + new binary sensors)
**Owner-direction (2026-05-31):** shared service, NOT fold into presence coordinator
**Triggering incident:** 2026-05-31 13:00-13:40 CDT — house went to GUEST state with all 4 persons `not_home`. Root cause: `sensor.playroom_person_count = 1` (Frigate phantom tracker on a stationary object), feeding v2 census's `_get_unrecognized_camera_count` → `_apply_hold_decay("house")` → aggregator latched → guest persistence threshold tripped. Front Side PTZ blip was a red herring; v2 architecture correctly excludes perimeter from house count.

---

## 0. Institutional Context Verified (CLAUDE.md mandate)

### 0.1 Existing code paths cited file:line

| Surface | Location | Status |
|---|---|---|
| v2 enhanced census engine | `camera_census.py:1722-1782` (`_apply_enhanced_house_census`), `:1781-1815` (`_apply_enhanced_property_census`) | REUSED — refactor target |
| v2 hold/decay state machine | `camera_census.py:1372-1430` (`_apply_hold_decay`) + state fields `_peak_house_camera_count`, `_peak_house_timestamp`, `_peak_property_count`, `_peak_property_timestamp` | REUSED — relocate to shared service |
| Interior camera filter | `camera_census.py:1432-1488` (`_get_unrecognized_camera_count`) — iterates `_get_interior_camera_entities()`, skips non-Frigate | REUSED — extend with phantom filter |
| Categorization config keys | `const.py:782-784` — `CONF_CAMERA_PERSON_ENTITIES`, `CONF_EGRESS_CAMERAS`, `CONF_PERIMETER_CAMERAS` (v3.4.5 / v3.5.0) | REUSED, no new keys |
| Aggregator that reads house count | `binary_sensor.py:802-868` (`URAUnexpectedPersonSensor`) — reads `result.house.total_persons` | REUSED — extend reader |
| Census signal dispatch | `camera_census.py:805-813` (`SIGNAL_CENSUS_UPDATED` payload: `interior_count`, `identified_count`, `unidentified_count`, `property_count`) | REUSED — extend payload |
| Presence consumer of census signal | `presence_coordinator.py` — handler for `SIGNAL_CENSUS_UPDATED` (cite exact handler line in build) | REUSED |
| Frigate `_person_active_count` sensors | per-camera `sensor.<name>_person_active_count` — Frigate-native | NEW input for phantom filter |
| Operator's full v2 config | UI screenshots 2026-05-31: Indoor=6, Door=3, Outdoor=9; Enhanced Census v2=ON, Face Recognition=ON, Guest WiFi SSID=Revel, Interior Hold=15min, Exterior Hold=5min | Verified populated |

### 0.2 Prior planning docs scanned

- `docs/planning/PLANNING_v3.5.2_CYCLE_6.md` — original v2 census architecture
- `docs/planning/PLANNING_v3.10.1_CENSUS_V2.md` — Census v2 engine introduction
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` — closely related cycle (v4.7.16) already addressed per-room camera-presence opt-out
- `docs/planning/PLANNING_v4.7.16_room_level_veto_density_weighting.md` — v4.7.16's `CONF_DISABLE_CAMERA_PRESENCE` is **independent** of this cycle (it disables a room's camera signal entirely; v4.7.18 filters phantom tracks)

### 0.3 Memory consulted

- `project_camera_signal_context_investigation.md` — operator principle: cam person OK, cam motion needs context. v4.7.18 extends this to "cam person count" needs phantom filter.
- `project_nm_bb_wa_audit_2026_05_30.md` — unrelated but acknowledged.

### 0.4 What v4.7.18 does NOT touch

- Per-room camera opt-out (`CONF_DISABLE_CAMERA_PRESENCE`) — v4.7.16 territory
- Presence coordinator's guest gate (`_guest_gate_armed`, `_guest_room_gate_armed`) — semantics preserved
- Camera categorization conf keys — reused as-is

---

## 1. Deliverables (D1–D5)

### D1 — Extract `CensusHoldDecayService` (shared service)

**Goal:** lift hold/decay state machine from `camera_census.py` into a free-standing service consumed by both camera_census (producer) and presence_coordinator (consumer).

**Files:**
- NEW: `custom_components/universal_room_automation/census_service.py`
- MODIFY: `camera_census.py:1372-1430` (relocate `_apply_hold_decay` body), `camera_census.py:1722-1815` (call shared service instead of own method)
- MODIFY: `presence_coordinator.py` (gain read access to current peak/hold state)

**Service API (locked at planning time, verify exact signature at build):**

```python
class CensusHoldDecayService:
    """Shared hold/decay state machine for camera-based person counts.

    Decouples the hold/decay logic from camera_census (the producer) so
    presence_coordinator (the consumer) can read peak state, age, and
    phantom-tracker flags directly.
    """

    def update(self, fresh_count: int, zone: str, now: datetime) -> HoldDecayResult:
        """Apply hold/decay; update internal peak; return result.

        zone is "house" or "property" (semantics unchanged from v3.10.1).
        """

    def peek(self, zone: str) -> HoldDecayResult:
        """Read current state without updating."""

    def reset(self, zone: str) -> None:
        """Operator-facing reset (clears stuck peak)."""
```

```python
@dataclass(frozen=True)
class HoldDecayResult:
    count: int          # current count (held or decayed)
    is_peak_held: bool  # True if within hold window
    peak_age_minutes: int
    phantom_excluded: int  # NEW v4.7.18 D2 — count of cameras filtered as phantom
```

### Acceptance Criteria — D1

- **Verify:** `camera_census._apply_hold_decay` no longer contains state; delegates to service.
- **Verify:** Service is created once per HA boot, lifetime owned by integration setup (cite exact owner in build).
- **Verify:** `presence_coordinator` can call `service.peek("house")` to read current peak state without mutation.
- **Test:** `test_d1_service_update_replaces_camera_census_state_machine`
- **Test:** `test_d1_service_peek_does_not_mutate`
- **Test:** `test_d1_service_state_persists_across_camera_census_recompute`
- **Live:** Post-deploy, behavior identical to pre-v4.7.18 for the happy path (no phantom, no perimeter mis-classification).

### D2 — Phantom-tracker filter via `person_active_count`

**Goal:** when a Frigate interior camera reports `person_count > 0 AND person_active_count == 0` for ≥ `CENSUS_PHANTOM_GRACE_SECONDS` (default 90s), treat as phantom and exclude from `unidentified_raw`.

**Files:**
- MODIFY: `camera_census.py:1432-1488` (`_get_unrecognized_camera_count`)
- NEW const: `CENSUS_PHANTOM_GRACE_SECONDS: Final = 90` in `const.py`

**Logic (illustrative — verify Frigate sensor naming during build):**

```python
def _get_unrecognized_camera_count(self) -> tuple[int, int]:
    """Returns (count, phantom_excluded) for interior Frigate cameras."""
    unrecognized = 0
    phantom_excluded = 0
    now = dt_util.utcnow()
    configured_interior = self._get_interior_camera_entities()

    for entity_id in configured_interior:
        # ... existing platform + sensor checks ...
        count = self._get_sensor_int(camera_info.person_count_sensor)
        if count <= 0:
            continue

        # v4.7.18 D2: phantom filter
        active_count_sensor = self._derive_active_count_sensor(entity_id)
        active_count = self._get_sensor_int(active_count_sensor) if active_count_sensor else None
        if active_count == 0:
            last_active = self._get_last_active_time(entity_id)  # last_changed of active_count when it was > 0
            if last_active is None or (now - last_active).total_seconds() >= CENSUS_PHANTOM_GRACE_SECONDS:
                phantom_excluded += count
                continue  # do NOT count phantom

        # ... existing face freshness check ...
        unrecognized += count

    return unrecognized, phantom_excluded
```

### Acceptance Criteria — D2

- **Verify:** Today's incident reproducer: `sensor.playroom_person_count=1`, `sensor.playroom_person_active_count=0` sustained ≥ 90s → excluded from unrecognized count.
- **Verify:** Real person walking through Playroom: `person_active_count` flips to 1, phantom timer resets, count is included.
- **Verify:** `phantom_excluded` surfaced on `URAUnexpectedPersonSensor.extra_state_attributes` so operator can see "I'm ignoring N phantom tracks."
- **Test:** `test_d2_phantom_excluded_when_active_zero_sustained`
- **Test:** `test_d2_phantom_grace_window_real_movement_resets_timer`
- **Test:** `test_d2_phantom_excluded_attr_exposed`
- **Live:** After Playroom Frigate restart + v4.7.18 deploy, simulated phantom (stationary object) does not arm GUEST state.

### D3 — Tier-1 + Tier-2 signals (operator-requested 3-tier model)

**Goal:** expose the 3-tier signal hierarchy the operator described as architecturally cleaner:

- **Tier 1** — `binary_sensor.ura_any_person_on_property` — `result.total_on_property > BLE_total`. ALREADY computed at `camera_census.py:774` as `total_on_property`. Just needs new sensor.
- **Tier 2** — `binary_sensor.ura_possible_guest_entry` — EGRESS-only person count > 0, sustained ≥ N seconds.
- **Tier 3** — existing `URAUnexpectedPersonSensor` (interior only) — UNCHANGED. Drives GUEST persistence.

**Files:**
- NEW: `binary_sensor.py` — add `URAAnyPersonOnPropertySensor` (Tier 1) + `URAPossibleGuestEntrySensor` (Tier 2)
- MODIFY: `camera_census.py` — split egress vs perimeter in `property_result` OR add `egress_count` as a separate field on `FullCensusResult`
- MODIFY: `SIGNAL_CENSUS_UPDATED` payload (extend, don't rename — back-compat)

**Backwards-compat constraint:**
- `result.house.total_persons` semantics unchanged
- `result.property_exterior.total_persons` semantics unchanged (egress + perimeter combined)
- ADD `result.property_exterior.egress_count`, `result.property_exterior.perimeter_count` (split)
- Existing consumers see the same aggregate; new tier sensors read the split.

### Acceptance Criteria — D3

- **Sensor:** `binary_sensor.ura_any_person_on_property` = `on` when any camera (interior + egress + perimeter) detects an unrecognized person.
- **Sensor:** `binary_sensor.ura_possible_guest_entry` = `on` when an egress camera detects an unrecognized person sustained ≥ 60s. Resets when egress count drops to 0.
- **Verify:** Neither Tier 1 nor Tier 2 forces GUEST state. Only Tier 3 (existing interior aggregator) does.
- **Verify:** Egress doorbell delivery scenario — person at door for 30s — Tier 2 stays `off`. 60s+ sustained → Tier 2 fires.
- **Test:** `test_d3_tier1_fires_on_any_property_person`
- **Test:** `test_d3_tier2_egress_sustained_threshold`
- **Test:** `test_d3_tier3_unchanged_interior_only`
- **Live:** Post-deploy, Tier 2 fires once during the next delivery / mail / package event; Tier 1 fires on any detection.

### D4 — Startup warning when full_scan fallback fires

**Goal:** prevent the silent trap where empty options → `_discover_full_scan` → all cameras treated as interior. Today's investigation revealed this fallback exists but emits no operator-visible warning.

**Files:**
- MODIFY: `camera_census.py:480-490` — when `_discover_full_scan` runs because no categorization is configured, log `WARNING` once + set a persistent diagnostic flag.
- NEW sensor (small): `binary_sensor.ura_census_unconfigured_full_scan` — surfaces the flag for operator alerting.

### Acceptance Criteria — D4

- **Verify:** When all 3 category lists are empty AND `_discover_full_scan` fires, a single `_LOGGER.warning` line is emitted at integration setup AND `binary_sensor.ura_census_unconfigured_full_scan = on`.
- **Verify:** When at least one category list is populated, no warning + sensor `off`.
- **Test:** `test_d4_warning_fires_on_empty_categorization`
- **Test:** `test_d4_no_warning_when_configured`
- **Live:** On THIS install (user has populated categorization per 2026-05-31 screenshots), sensor stays `off`.

### D5 — `presence_coordinator` gains visibility into hold/decay state

**Goal:** close the architectural seam. Presence coordinator can now read `service.peek("house")` to know IF the unidentified count it's consuming is "fresh" or "held under decay." This means the guest gate can check phantom_excluded, peak_age, etc.

**Files:**
- MODIFY: `presence_coordinator.py` — accept the `CensusHoldDecayService` via DI / `hass.data` lookup
- MODIFY: `_guest_gate_armed` (`presence_coordinator.py:1777-1843`) — when `peek("house").is_peak_held AND peak_age_minutes > threshold`, dispatch a debug log line (NOT changing decision logic this cycle — instrumentation only)

**Out of scope for v4.7.18:** changing the guest gate's decision logic. That's a follow-up cycle once we have empirical data on `phantom_excluded` rates.

### Acceptance Criteria — D5

- **Verify:** `presence_coordinator._guest_gate_armed` can read `service.peek("house").is_peak_held` without mutating service state.
- **Verify:** When guest gate fires, log includes `peak_age_minutes` and `phantom_excluded` for diagnostics.
- **Test:** `test_d5_presence_can_peek_service`
- **Test:** `test_d5_guest_gate_log_includes_peak_age`
- **Live:** Post-deploy, log lines on next guest-gate evaluation include the new fields.

---

## 2. Tier classification — Tier 2-DB (operator-elevated)

Per CLAUDE.md "operator-elevated" clause. Justification:

- Refactor ripples across `camera_census.py`, `binary_sensor.py`, `presence_coordinator.py`, `const.py`
- Changes payload shape of `SIGNAL_CENSUS_UPDATED` (additive, but consumers must tolerate)
- New sensors (Tier 1, Tier 2, full_scan_warning) — registry stability requirement
- Risk: regression in guest detection → today's incident class could repeat or worsen if D2 phantom filter has edge cases

### Three reviewer framings (framing-disjoint per CLAUDE.md Tier 2-DB protocol)

- **A — Correctness + state-machine boundaries.** Phantom filter correctness (active=0 sustained window), tier-1/tier-2 threshold semantics, signal payload back-compat, hold/decay equivalence pre/post refactor.
- **B — Service lifecycle + cross-coordinator integration.** Service owner / boot ordering / lifecycle (Bug Class #5 deferred restore via signal watch), DI pattern, `presence_coordinator` peek-not-mutate guarantee, dispatch payload preservation.
- **C — Test fixture authority + parallel-merge risk.** Bug Class #44 — tests drive real `CensusHoldDecayService` + real `_apply_hold_decay` semantics; verify D1 byte-equivalence; phantom-tracker tests use real Frigate-shaped sensors not stubs; merge risk vs v4.7.14.1 + v4.7.15 + v4.7.15.1 + v4.7.16 already-shipped sprint.

---

## 3. Bug class watchlist

- **#5 (deferred restore via signal)** — `CensusHoldDecayService` peak state on HA restart: persist via RestoreEntity or accept reset-on-restart? Plan: **accept reset-on-restart** (counts repopulate within first census cycle). Document.
- **#11 (UTC vs local TZ)** — phantom-grace timestamp comparison. Use `dt_util.utcnow()` consistently.
- **#14 (config snapshot staleness)** — categorization read at boot; on options-flow change → reload integration (existing pattern).
- **#20 (concurrent reload race)** — service singleton vs integration reload. Document the reload behavior (drop service, recreate).
- **#22 (enum mismatch)** — `zone="house"|"property"` string literal — use constants.
- **#26 (in-memory reads only)** — `service.peek()` is in-memory; no DB.
- **#43 (silent person drop)** — D2 phantom filter explicitly counts excluded persons via `phantom_excluded` attr; not silent.
- **#44 (test fixture authority)** — tests drive REAL service, REAL hold/decay; phantom sensor fixtures match Frigate's actual entity ID pattern.
- **#46 (async_update_entry re-entrancy)** — N/A unless service touches config entries (it shouldn't).
- **#47 (lazy canonical UI surface)** — new sensors have human-readable state strings.

---

## 4. Plan Completion Tracking (mandatory per CLAUDE.md)

After implementation, account for:
- D1/D2/D3/D4/D5 status (complete / partial / deferred + reason)
- Whether `CensusHoldDecayService` was successfully extracted vs partially extracted
- Whether phantom filter caught today's reproducer in test (Playroom shape: count=1, active=0, sustained)
- Whether tier-1 / tier-2 sensors landed AND fire on first appropriate live event

---

## 5. Out of scope (explicit deferrals)

- **Folding v2 census into presence coordinator wholesale.** Operator-directed: shared service, not absorb-into-presence. Future cycle could re-evaluate.
- **Changing guest gate decision logic.** D5 is instrumentation only.
- **Per-camera phantom-grace tuning UI.** Single global const this cycle. Per-room tuning is a follow-up.
- **WiFi VLAN guest re-enable.** Already disabled per v3.10.1 cycle (too many IoT false-positives).
- **Restart-resilient peak persistence.** Accept reset-on-restart this cycle.
- **Operator-facing peak reset button.** Documented in service API as `reset(zone)` but no UI surface this cycle.

---

## 6. Pre-deploy zero-bugs gates

1. Conflict-marker grep across changed files
2. `py_compile` every changed `.py` file
3. Cycle tests pass (all D1-D5 tests)
4. Sibling test suite delta: no new failures in v4.7.13/14/14.1/15/15.1/16 test files
5. JSON validity (manifest, strings, en.json)
6. Token-leak grep
7. AST regression test for v2 census: ensure `_apply_hold_decay` body has truly been relocated (no shadow definition left in camera_census.py)

---

## 7. README requirements (extra-robust Tier 2-DB bar per CLAUDE.md)

`docs/readmes/README_v4.7.18.md` must include:

1. **Operator runbook** — what behavioral changes the operator will see (3 new sensors, phantom filter behavior, full_scan warning)
2. **Pre-deploy snapshot procedure** — operator runs SQL/template query on `unexpected_person_detected` peak age + Frigate `_person_count`/`_person_active_count` per interior camera (to baseline against post-deploy)
3. **Post-deploy validation** — exact entity IDs + expected values for all 3 new sensors + `phantom_excluded` attribute
4. **Rollback procedure** — feature flag (env var or new switch) to disable phantom filter (revert to pre-v4.7.18 behavior); rollback to prior version if needed
5. **Live-validation checklist** — explicit pass criteria for the phantom-filter reproducer (Playroom case)
6. **Known limitations** — peak resets on HA restart; no per-camera phantom tuning yet; v4.7.18 does NOT change guest gate decision logic
7. **Cross-cycle references** — v4.7.14.1 / v4.7.15 / v4.7.15.1 / v4.7.16 (just shipped sprint), v3.10.1 (Census v2 origin), v3.5.0 (categorization origin)

---

## 8. Size estimate

- D1 (service extraction): ~80-120 LoC + ~60 LoC tests
- D2 (phantom filter): ~30-50 LoC + ~40 LoC tests
- D3 (tier-1 + tier-2 sensors): ~70-100 LoC + ~60 LoC tests
- D4 (full_scan warning): ~20 LoC + ~20 LoC tests
- D5 (presence peek): ~30 LoC + ~30 LoC tests

**Total estimate:** ~230-320 LoC production + ~210 LoC tests + README. Tier 2-DB cycle. Should sequence AFTER current sprint deploys (so we're not stacking on unverified base).

---

## 9. Recall

- "Plan v4.7.18 census service"
- "Resume v4.7.18 phantom filter"
- "Census shared service refactor"
- "Why did URA go to GUEST with no one home" (today's incident)

---

## 10. References

- **2026-05-31 incident transcript** — diagnosed root cause to `sensor.playroom_person_count = 1` with `_person_active_count = 0` (Frigate ghost tracker)
- `docs/planning/PLANNING_v3.10.1_CENSUS_V2.md` — Enhanced Census v2 architectural origin
- `docs/planning/PLANNING_v3.5.2_CYCLE_6.md` — Original v2 census architecture
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` — Camera-signal context investigation (separate, complementary)
- `docs/planning/PLANNING_v4.7.16_room_level_veto_density_weighting.md` — `CONF_DISABLE_CAMERA_PRESENCE` independent of v4.7.18 phantom filter
- `docs/QUALITY_CONTEXT.md` Bug Class #48 — Transient-sensor over-trust during reliable-truth-says-otherwise periods (today's incident is a member of this class — Frigate ghost tracker = transient noise; sustained `active=0` = reliable counter-signal)
