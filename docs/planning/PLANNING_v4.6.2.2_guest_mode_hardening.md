# PLANNING v4.6.2.2 — Guest Mode False-Positive Hardening

**Status:** Plan complete, ready to implement
**Tier:** Tier 1 hotfix (≤3 files, single bug class, additive signal payload, no schema/lifecycle changes)
**Predecessor:** v4.6.2.1 (Humidity Fan Hardening — running in parallel worktree)
**Soak-safety:** Touches the guest-mode gate in `presence.py` and the census signal payload in `camera_census.py`. No interaction with routine awareness (B6/B7), regime detector, or D7 accuracy consumer. Safe to ship during v4.6.2 soak.

## Why

Live audit during v4.6.2 soak (2026-05-14):
- House flipped to `guest` at 08:58 CDT despite no guests being present.
- `sensor.universal_room_automation_unidentified_persons` showed `state=1, camera_total=2, ble_identified=1`.
- 3-day history of `unidentified_persons_in_house` oscillates 0↔1↔2↔3 essentially continuously during waking hours; house-state history shows many dozens of `home_day ↔ guest` flips per day across May 7–9.

### Root cause

The guest gate at `presence.py:408-415` fires on any single-tick `unidentified_count > 0` while the house is in `HOME_DAY / HOME_EVENING / HOME_NIGHT`. `unidentified_count` is computed at `camera_census.py:1162` as `max(0, camera_total - identified_count)` where identified is `face_ids ∪ ble_ids`.

When a family member is seen by the camera but not face-recognized (the BACKLOG-documented Frigate face-DB undersize: 11–17 samples per family member at threshold 0.9; 1 match per 50 events) **and** not currently BLE-resolved (phone not advertising, scanner gap, IRK rotation), they count as a guest. Single-tick mis-IDs immediately flip house state.

### Three independent failure paths the current gate doesn't close

1. **No persistence guard.** One transient census tick is sufficient to fire GUEST. Same shape as the vacation/sick-day false-positives the regime detector mitigated with persistence — a single tick is too eager.
2. **No confidence gate.** `presence.py` never reads `census_confidence`. When confidence is `low` (BLE-only, single-source, or cameras disagree), the gate still fires.
3. **Threshold of 1.** Single-person identification gaps are the common false-positive shape; a real visiting guest is almost always accompanied by a recognized resident, making the gap ≥ 2 in the realistic case. A `>=2` floor filters most of the noise without losing real-guest detection.

## Scope

### A. Extend `SIGNAL_CENSUS_UPDATED` payload

`camera_census.py:803-813` currently dispatches:
```python
{"interior_count", "identified_count", "unidentified_count", "property_count", "total_on_property"}
```

Add two fields read from `house_result`:
```python
"confidence": house_result.confidence,           # "high" | "medium" | "low" | "none"
"source_agreement": house_result.source_agreement,  # "both_agree" | "close" | "disagree" | "single_source"
```

Pure additive change to a dict payload. No subscribers break.

**Threshold knob (`min_unidentified`) considered and dropped after live audit.** Persistence + confidence together filter the observed chatter pattern (resident BLE flicker, face-DB miss producing transient unidentified=1 ticks) without sacrificing single-visitor detection. The current effective threshold of `unidentified > 0` is preserved.

### B. Two new config knobs (persistence + confidence, both consumed in `presence.py`)

| CONF | Default | Range | Helper text |
|---|---|---|---|
| `CONF_GUEST_MODE_PERSISTENCE_SECONDS` | `DEFAULT_GUEST_PERSISTENCE_SECONDS = 300` | 0–1800 (0 disables persistence) | "How long an unidentified person must persist before the house enters Guest mode. Filters transient ID failures (face DB miss, BLE coverage gap). Set to 0 to disable persistence." |
| `CONF_GUEST_MODE_REQUIRE_CONFIDENCE` | `DEFAULT_GUEST_REQUIRE_CONFIDENCE = "medium"` | enum: `high` / `medium` / `low` | "Minimum census confidence required to trigger Guest mode. 'medium' refuses to fire when cameras disagree or no camera data. 'high' requires both camera platforms agree." |

Form fields go into the **Coordinator Manager** options flow (the singleton coordinator that owns house-state policy), not per-room. House state is global.

### C. Apply gates in `presence.py:408-415`

Replace:
```python
if unidentified_count > 0 and current_state in (HOME_DAY, HOME_EVENING, HOME_NIGHT):
    if current_state != HouseState.GUEST:
        self._confidence = 0.8
        return HouseState.GUEST
```

With (sketch):
```python
if current_state in (HOME_DAY, HOME_EVENING, HOME_NIGHT):
    if self._guest_gate_armed(unidentified_count, census_confidence, now):
        if current_state != HouseState.GUEST:
            self._confidence = 0.8
            return HouseState.GUEST
```

`_guest_gate_armed` is a new private method that evaluates three guards in order:
1. **Existence:** `unidentified_count > 0`. Returns False immediately if no unidentified persons.
2. **Confidence:** `_confidence_at_least(census_confidence, require_confidence)` using rank map `{"none": 0, "low": 1, "medium": 2, "high": 3}`. Returns False if observed rank is below required rank.
3. **Persistence:** Tracks `_unidentified_first_seen` timestamp; on first qualifying tick, set it; on subsequent qualifying ticks, return True iff `(now - first_seen) >= persistence_seconds`; on any qualifying-condition-false tick, clear it.

Symmetric reset: on exit (`unidentified_count == 0` for a single tick → existing exit branch at `presence.py:417-419`) **also** clear `_unidentified_first_seen` and a new `_guest_active_since`. No persistence on exit (cheaper to leave guest mode than to enter it).

### D. Census-update reactivity

`_handle_census_update` at `presence.py:1075-1095` already triggers a `_run_inference` on any unidentified_count change. With persistence enabled, the FIRST qualifying tick will arm the gate but not fire; subsequent inference ticks must re-evaluate. Solution: schedule a one-shot re-inference at `now + persistence_seconds + 5` using `async_call_later` so we don't depend on census jitter to re-check.

Track the call_later handle on `self._guest_persistence_check_handle` so we can cancel it cleanly on:
- Successful gate fire (no longer needed)
- Disarm (unidentified dropped or confidence regressed)
- Coordinator unload

### Out of scope (deferred)

- **Underlying Frigate face DB undersize** — user-handled per existing memory; not URA code.
- **Per-zone unidentified gating** — current sensor `Per-zone unidentified count deferred until per-zone camera data available` (note at `sensor.py:3363`). House-level is the only available signal today.
- **Live Number entities** for the three knobs. Form fields are enough for v4.6.2.2; promote to runtime sliders later if user wants live tuning during a soak.
- **Anomaly emit on gate arm/fire** — could feed into v4.6.1 anomaly DAO. Defer to v4.6.3 anomaly migration to keep this hotfix tight (same pattern as v4.6.2.1).
- **Diagnostic sensor** exposing `_unidentified_first_seen` / `_guest_persistence_remaining_seconds`. Nice-to-have for debugging during initial soak. Defer unless we hit issues.

## Deliverables

### D1 — Extend `SIGNAL_CENSUS_UPDATED` payload

Add `confidence` and `source_agreement` to the dispatch dict at `camera_census.py:803-813`. Reading from `house_result.confidence` and `house_result.source_agreement` (both already on `CensusZoneResult` dataclass — no change needed there).

**Acceptance Criteria**
- **Verify:** Inspect `SIGNAL_CENSUS_UPDATED` dispatches via a test stub or by attaching a logger; payload includes both new keys.
- **Test:** `test_census_signal_payload_includes_confidence` and `test_census_signal_payload_includes_source_agreement` in `quality/tests/test_v4622_guest_mode_hardening.py`.

### D2 — New config keys + form fields + defaults

- Add CONFs and DEFAULTs to `const.py` per the table above (`CONF_GUEST_MODE_PERSISTENCE_SECONDS`, `CONF_GUEST_MODE_REQUIRE_CONFIDENCE`). Note: `CONF_GUEST_MODE_MIN_UNIDENTIFIED` was considered and dropped — only 2 new CONF + 2 new DEFAULT entries.
- Form fields in the **coordinator-manager options flow** in `config_flow.py` (locate the step that already handles census / presence options; create one if it doesn't exist).
- `strings.json` + `translations/en.json` entries for the two field labels + helper text.

**Acceptance Criteria**
- **Verify:** Options flow shows the two new fields with the documented defaults and ranges.
- **Verify:** Round-trip: set values, save, reload form, see saved values.
- **Test:** `test_guest_mode_config_defaults`, `test_guest_mode_config_round_trip`.

### D3 — Existence + confidence + persistence gates in `_guest_gate_armed`

Implement `_guest_gate_armed(unidentified_count, census_confidence, now)`:
- Existence gate: `unidentified_count > 0` (False if 0). No min-count threshold — single visitor must fire.
- Confidence gate: `_confidence_at_least(census_confidence, require_confidence)` where:
  - Define a private rank map: `{"none": 0, "low": 1, "medium": 2, "high": 3}`.
  - Return False if observed rank < required rank.
- Persistence gate: only after existence + confidence pass, evaluate `_unidentified_first_seen` timing.

**Acceptance Criteria**
- **Verify (behavioral test):** With `require_confidence=medium`: census ticks (count=1, conf=high) for < persistence_seconds → no guest. Census ticks (count=1, conf=low) → no guest. Census ticks (count=1, conf=medium) for >= persistence_seconds → guest fires (single visitor must not be blocked).
- **Verify:** Disarm — once guest is active, if next tick has count=0, exit branch fires immediately (existing behavior preserved, no persistence-on-exit).
- **Test:** `test_guest_gate_confidence_blocks_low_census`, `test_guest_gate_persistence_fires_after_window`, `test_guest_gate_disarms_when_count_drops_before_window`, `test_guest_gate_exit_is_immediate`, `test_single_visitor_still_triggers_guest`, `test_resident_ble_flicker_does_not_fire_guest`.

### D4 — Persistence timer + cleanup

- New state fields on `PresenceCoordinator`: `_unidentified_first_seen: datetime | None`, `_guest_persistence_check_handle`.
- On qualifying-tick arm: set `_unidentified_first_seen = now`; schedule `async_call_later(hass, persistence_seconds + 5, self._recheck_guest_gate)`.
- On `_recheck_guest_gate`: run `_run_inference("guest_persistence_recheck")`.
- On gate fire OR disarm OR coordinator unload: cancel handle if set; clear `_unidentified_first_seen`.
- On `async_unload`: ensure handle is cancelled (Bug Class #19 / untracked-task prevention).

**Acceptance Criteria**
- **Verify (behavioral test):** With persistence=300s, census ticks (count=2, conf=high) → handle scheduled. Patch `dt_util.utcnow()` to advance 301s, invoke `_recheck_guest_gate` directly, assert house transitions to guest.
- **Verify:** Unload during pending recheck → handle is cancelled (no orphan callbacks).
- **Test:** `test_persistence_handle_scheduled_on_arm`, `test_persistence_handle_cancelled_on_disarm`, `test_persistence_handle_cancelled_on_unload`.

### D5 — Wire census-signal additions into `_handle_census_update`

Update `_handle_census_update` to read `confidence` and `source_agreement` from the payload, store on `self._census_confidence` and `self._census_source_agreement` (new fields). Pass to `_run_inference`. Update the inference signature to accept and use these.

**Acceptance Criteria**
- **Verify:** Stubbed census dispatch with `confidence="low"` → presence sees `_census_confidence == "low"`.
- **Test:** `test_census_confidence_propagated_to_presence`.

### D6 — Source-grep regression tests

- AST regression: `_guest_gate_armed` exists on `PresenceCoordinator` and is called from `_infer_state` at the expected line.
- Import-resolves: new CONF/DEFAULT constants in `const.py` import cleanly into `presence.py` and `config_flow.py`. Same shape as the v4.5.10.1 footgun-prevention test.
- AST regression: `async_call_later` handles tracked via `entry.async_on_unload` or equivalent cleanup pattern (Bug Class #19 prevention).

**Acceptance Criteria**
- **Test:** `test_guest_gate_method_exists`, `test_guest_mode_constants_import_cleanly`, `test_guest_persistence_handle_cleanup_registered`.

## Files touched

- `const.py` — 2 new CONF + 2 new DEFAULT entries (threshold knob dropped)
- `camera_census.py` — 2 extra dict keys in `SIGNAL_CENSUS_UPDATED` payload (~5 LoC)
- `domain_coordinators/presence.py` — `_guest_gate_armed`, persistence timer wiring, payload-field reads (~80 LoC)
- `config_flow.py` — coordinator-manager options-flow additions (~20 LoC)
- `strings.json` + `translations/en.json` — labels + helper text (2 fields, not 3)
- `quality/tests/test_v4622_guest_mode_hardening.py` — new test file (~200 LoC)

## Cost

- Production: ~100 LoC across 4 files (~10 LoC less than original plan — no threshold knob)
- Tests: ~200 LoC
- Tier 1 review (one staff-engineer pass, mental execution required)

## Risks

1. **Persistence timer leakage (Bug Class #19).** If the `async_call_later` handle is not cancelled on unload or disarm, we leak callbacks. Mitigation: cleanup on every exit path (gate fire, disarm, unload). AST regression in D6.
2. **Confidence-low-blocks-real-guests.** If a real guest visit happens when census confidence is `low` (e.g., one camera down), they won't trigger guest mode. Mitigation: default `require_confidence="medium"` (not `"high"`) — only `low` and `none` are blocked. User can dial to `low` if they want maximum sensitivity.
3. **Persistence delays real guests.** With persistence=300s, a real guest visit takes 5 min to register. Acceptable trade-off — the alternative is constant false flips. User can dial persistence to 0 to disable.
4. **`_unidentified_first_seen` not cleared on house-state change.** If house transitions HOME_DAY → AWAY mid-arm, the arm timer must clear. Mitigation: clear `_unidentified_first_seen` whenever current_state leaves the HOME_* states. Cover in tests.
5. **Stale census between ticks.** If census signals stop (camera down), the persistence timer fires at T+305s and re-runs inference — but `_unidentified_count` may be stale-stuck. Mitigation: `_run_inference` already re-reads all signals at evaluation time; the timer just forces a re-eval, it doesn't bypass freshness checks.
6. **Default-value chosen without long-term data.** 300s persistence and threshold=2 are educated guesses from a 3-day observation. Worth re-tuning after a week of soak using D5's anomaly trail (deferred to v4.6.3).

## Review checklist

- [ ] `_guest_gate_armed` correctly applies existence → confidence → persistence in that order (short-circuit on fail)
- [ ] `_unidentified_first_seen` cleared on disarm AND on house-state change away from HOME_*
- [ ] `async_call_later` handle tracked via `entry.async_on_unload` or coordinator unload path
- [ ] No regression in immediate-exit behavior (guest → home_day when count drops to 0)
- [ ] Confidence enum compare uses the documented rank order, not lexicographic
- [ ] Tests cover: single-visitor detection, confidence gate, persistence, disarm-before-window, exit-immediate, handle-cleanup
- [ ] No module-level imports introduced that could trigger Bug Class #34
- [ ] Strings/translations updated for 2 new fields (threshold field absent)

## Live validation post-deploy

1. Confirm `binary_sensor.ura_guest_mode` / `sensor.ura_coordinator_manager_house_state` do NOT flip to `guest` for short (< 5 min) unidentified-count blips. Compare to baseline frequency from the 3-day pre-deploy history.
2. Drop persistence to 60s temporarily (via options flow) to validate the gate timing — confirm guest fires ~60s after a sustained unidentified blip.
3. Confirm guest fires correctly when a single unidentified person persists for >= persistence_seconds (e.g., during an actual guest visit).
4. Confirm exit timing is unchanged (guest → home_day immediate on count=0 tick).
5. Watch logs for `async_call_later` warnings or orphan-callback errors on entry reload.
6. After 24h, query DB for any `house_state` write rate anomalies vs baseline.
