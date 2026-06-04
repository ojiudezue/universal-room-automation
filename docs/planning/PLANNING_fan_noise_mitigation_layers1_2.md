# PLANNING — Fan-noise mmwave mitigation: Layer-1 (silent interference-conditioned discount + decay) + Layer-2 (BLE-gated rare fan-pause fallback)

**Status:** Draft (planning).  No version pre-stamped — assigned at deploy time per operator convention.
**Predecessor cycle (LIVE 2026-06-04):** Tier-1 provenance split + observation-only fan-interference Layer-1 diagnostic (`README_v4.7.19.md`).  This plan promotes the diagnostic into a gate (D1 here) and designs the actuation rung that follows it (D2 here).
**Supersedes the deferred-items doc relevant sections:** `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` Items 1 + 2 (Items 3 / 4 / 5 remain there).
**Origin notes:** memory body `project_fan_noise_mmwave_mitigation_backlog.md`; `docs/BACKLOG.md` "Fan-noise mmwave mitigation" entry; `docs/TECH_DEBT.md` Presence Tier-1 OR entry (now RESOLVED via predecessor).
**Operator no-regression mandate (verbatim):** *"I am not prepared to deal with Presence bugs at the mo... NOTHING is wrong, I just want to make it more Right."*  Every code path on the presence trust hierarchy (room → zone → house → presence-coordinator) must be audited to prove the discount cannot fabricate a false-unoccupied that ripples into HVAC / compliance / safety.

## Operator decisions — LOCKED 2026-06-04 (pre-build)

1. **Keep Layer-2 of the BLE ladder + build `CONF_ADJACENT_ROOMS`.**  The adjacency (drift) layer is in scope — operator confirmed it is the layer that "kills the annoying false-pause."  Per-room adjacency config is acceptable; blank adjacency falls back to L1+L3 (incremental population is fine).
2. **Decay default = 300s** (`CONF_FAN_INTERFERENCE_HOLD_S` default 300, camera-tier-aligned per `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS`).  Range 60–1800.
3. **D1 stays Tier 2-DB** (three framing-disjoint reviews) — not split down.
4. **Sidecar ripple audit** `AUDIT_fan_interference_gate_ripple.md` to be produced (mirrors predecessor's audit doc).
5. **D2 (Layer-2 actuation) remains DESIGN-ONLY this cycle** — build-gated on D1 live + observed event volume.  This cycle BUILDS D1 only; the `CONF_ADJACENT_ROOMS` adjacency model ships WITH D1 (it feeds the L2 rung of the gate's BLE ladder, which is part of D1's silent discount — the *actuation* pause is what's deferred, not the ladder).

---

## Tier classification

**Tier 2-DB (three framing-disjoint reviews).**  Justification (CLAUDE.md operator-elevation criteria + standard triggers):

1. **Trust-hierarchy ripple.** D1 changes the SEMANTIC of `ZonePresenceTracker._room_provenance` reads — a previously-True mmwave provenance bool can now be discounted to "fan-suspect, hold under decay."  Reads of the derived `_room_occupied` property propagate into `_derived_mode` → `tracker.mode` → presence-coordinator consensus → HVAC defer gate (`check_zone_occupancy_confidence`) → compliance gate.  Any false-unoccupied is a regression in a hierarchy the operator just stabilized.  Operator-elevation criterion satisfied.
2. **Payload-shape change to a persisted record (D2).**  D2 adds a per-room `fan_pause_state` row (idle / armed / paused / restoring / cooldown) persisted across HA restart — mirrors the v4.7.8 `egress_state` precedent.  Cycle adds a new DAO and changes the shape of a dispatched event (NM `fan_pause_started` / `fan_pause_restored`).  Standard Tier 2-DB triggers satisfied.
3. **Actuation surface NEW** (D2 only).  First time the presence side commands a fan.  Snapshot/restore + restart-resilience surface needs DB-architecture review distinct from correctness review.

Framings (locked here, repeated at review dispatch):

- **Reviewer A — Correctness + state-machine invariants.** Layer-1 gate truth table; decay timer never holds a genuinely-vacated room "occupied" past `CONF_FAN_INTERFERENCE_HOLD_S`; Layer-2 state machine (idle → armed → paused → restoring → cooldown) is total; manual override + safe-fail branches.
- **Reviewer B — Async + lifecycle + restart resilience + cross-coordinator ripple.** All Layer-2 restart scenarios (paused-at-restart, restoring-at-restart, cooldown-at-restart, snapshot-corrupt-at-restart).  Listener teardown for the new fan-write path.  Cross-coordinator ripple audit — D1 effect on `check_zone_occupancy_confidence` callers (HVAC defer gate, compliance, safety).  Bug Class #14 (first-tick post-restart rehydration) + Bug Class #42 (dispatcher subscribers).
- **Reviewer C — New surfaces + DB schema + test fixture authority + cross-rule precedence.** New CONF_* round-trip through options flow + RestoreEntity.  `fan_pause_state` table DDL extracted from production source (never hand-copied).  Cross-rule precedence: Layer-2 vs existing `hvac_fans` fan-policy (`CONF_FAN_VACANCY_HOLD`, `CONF_FAN_TEMP_THRESHOLD`) — pause must not race the fan-temp manager.  Operator-pause vs URA-pause precedence.

---

## Institutional context verified

The fan-interference foundation is already shipped.  This section proves every proposed addition was greppped against prior art before scoping.

### A. Primitives the operator asked me to verify (REUSED / NEW verdict per item)

| Primitive | Verdict | Evidence (file:line) | Notes |
|---|---|---|---|
| `is_direct_ble_room` | **REUSED — under DIFFERENT NAME.**  Actual symbol is `is_room_direct_ble(room_name) -> bool` at `person_coordinator.py:1145` (return list of persons; bool wrap via `bool(...)`).  Audit doc explicitly captures the naming drift: `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md:838`. | One existing caller at `coordinator.py:1516`.  D1 must add a SECOND caller (on the presence side) to consult the BLE-direct-room flag for Layer-1 confidence ranking. | Memo claim that `is_direct_ble_room` exists is technically wrong — recorded in audit; use the real name. |
| `_check_zone_occupancy_confidence` | **REUSED — relocated + renamed.** Now public `check_zone_occupancy_confidence(zone) -> tuple[int, int]` on `PresenceCoordinator` at `presence.py:968` (relocated from HVAC in v4.7.15 D4 per `PLANNING_v4.7.15_universalize_bug_class_48_veto.md:360`).  Callers: HVAC defer gate at `hvac.py:870`, compliance at `compliance.py` callsite. | D1 ripple audit MUST trace every consumer of this helper — a "fan-suspect" room must NOT spuriously enter the `(confirmed, possible)` denominator and gate HVAC off-cycle. | Confirmed via grep — no stale `_check_zone_occupancy_confidence` private references remain (only the comment stub at `hvac.py:1441`). |
| `PersonPhoneLeftBehindSensor` | **REUSED — referenced not consumed.**  Class at `binary_sensor.py:1031`; registered at `binary_sensor.py:102`.  Default-disabled (`binary_sensor.py:988`).  Force-False 22-07 local. | Layer-2's L3 zone-BLE-absence read MUST NOT treat a phone-left-behind person as evidence of presence.  Mirror the v4.7.14.1 H2 pattern (`presence.py:3258-3265`): exclude phone-left-behind persons from the BLE-corroboration denominator.  Fail-OPEN when sensor disabled (preserves predecessor baseline). | This is the well-known BLE false-positive — both the gate and the pause guard must respect it. |
| Tier-3 `_ble_occupied` per-zone resolution path | **REUSED.**  `ZonePresenceTracker._ble_occupied: bool` at `presence.py:390`.  Set by `update_ble_presence(has_persons)` (`:649`).  Driven by `_run_inference` `person_coord.get_persons_in_zone(zone_rooms)` at `:1432`. | This IS the L3 ("zone-wide BLE absence") primitive — `not tracker._ble_occupied` is exactly "no BLE in zone."  Layer-2's pause guard reuses it; Layer-1's L3 fallback for unbinded rooms reuses it. | No new primitive needed for L3. |
| `_compute_fan_interference_rooms` | **REUSED + UPGRADED.**  Observation-only diagnostic at `presence.py:2217`.  Already checks: (a) `_fan_on_rooms`, (b) Tier-1 provenance shows mmwave-sole, (c) `get_persons_in_room` empty (L1), (d) zone-wide `_camera_occupied` empty.  Publishes `fan_interference_rooms` / `fan_interference_active` via `signal_consensus_inputs` at `:4187-4188`. | D1 promotes this from observation to gate.  Adds the L2 (adjacent) and L3 (zone-BLE) layers.  Output remains a per-room flag list — readers via `_room_provenance` get the discount semantic. | The helper already short-reads safely (`.get(..., {})`); D1 must preserve the "no exception leak" guarantee. |
| `_room_provenance` (predecessor D2 surface) | **REUSED.**  `Dict[str, Dict[str, bool]]` at `presence.py:372`.  Derived `@property _room_occupied` returns `{room: any(provenance.values())}` at `:414`. | D1's "hold last-known under decay" must NOT mutate `_room_provenance` directly (that would lie to every downstream reader).  Instead introduce a `_fan_interference_hold_until: Dict[str, datetime]` and consult it in the derived view — see D1.3 below. | Bug Class #1 (seed-vs-live divergence) — keep `_classify_entity_kind` the single source of truth. |
| `_camera_last_seen` + `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300` | **REUSED as design precedent.**  Camera tier already implements timeout-based "hold occupied for 5min after last detection" at `presence.py:520-535`.  Constant at `:71`. | D1's decay timer mirrors this pattern — same idiom, different lifetime (operator-configurable Number, default 5min). | Same code shape; reviewers will recognize it. |
| `D3_DIAGNOSTIC_ENABLED` | **REUSED.**  Module-level kill switch at `const.py:351`.  Imported at `presence.py:47`.  Read at `:2295` + `:3543`. | D1 reuses this flag as the gate kill switch (single source of "fan-interference feature on/off").  No new kill switch. | Already in place — perfect for a chicken-bit. |
| `CONF_FANS` / `CONF_FAN_CONTROL_ENABLED` / `CONF_FAN_VACANCY_HOLD` | **REUSED.**  `const.py:373, 481, 489`. | D2 MUST honor `CONF_FAN_VACANCY_HOLD` and the broader fan policy — the pause must not race the temperature manager.  Cross-rule precedence: URA-driven pause defers to operator-driven explicit fan policy (operator's hand on the wheel wins). | Confirmed: `hvac_fans.py` owns the existing fan-write surface. |
| `hvac_fans.turn_off_all_managed()` + direct `fan.turn_off` / `fan.turn_on` writes | **REUSED design + NEW surgical surface.**  Existing writes at `hvac_fans.py:508,514,521,527`; broad off at `:170`. | D2 needs a per-fan, per-room pause/restore that does NOT trigger the existing managed-fan logic (that would side-effect HVAC).  Add a new narrow surface (`pause_fan_for_interference_check(room_name)` / `restore_fan(room_name)`) on `hvac_fans.py` that ONLY this consumer calls. | New thin method on existing module — not a new file. |
| `egress_state` DAO + `EgressManager` snapshot/restore pattern | **REUSED as design precedent.**  v4.7.8 plan `docs/planning/PLANNING_v4.7.8_egress_window_hvac_pause.md` §D6 + `database.py` `egress_state` table block (mentioned in §3 of v4.7.8). | D2's `fan_pause_state` table mirrors `egress_state` line-for-line (4 restart scenarios: paused-at-restart, restoring-at-restart, cooldown-at-restart, snapshot-corrupt-at-restart). | Same 5-DAO surface (`get_fan_pause_state(room_id)`, `save_fan_pause_state`, `get_all_fan_pause_state`, `clear_fan_pause_state`, `prune_stale_fan_pause_state`). |
| `check_zone_occupancy_confidence` (the v4.7.15 D4 helper) | **REUSED + AUDITED for ripple.**  `presence.py:968`.  Callers must NOT see a fan-suspect mmwave room as `confirmed`. | D1 §D1.4 ripple audit covers this. | Reviewer A focus area. |
| `_ble_occupied` per-zone bool re-read for L3 | **REUSED — same field.**  See row above. |  |  |
| `CONF_ADJACENT_ROOMS` (or equivalent adjacency model) | **NEW.**  Verified absent: `grep -r "CONF_ADJACENT\|adjacent_room\|neighbor" custom_components/universal_room_automation/const.py` returns zero hits.  Project-wide grep returns ONLY the deferred-items doc speculative mention.  No HA area-graph helper consumed today either. | D1 needs adjacency for L2.  See D1.5 for the model decision (per-room `CONF_ADJACENT_ROOMS: list[str]` in the room config_flow). | This is the single biggest NEW addition — flagged for operator confirmation in §"Open questions / scope risks." |
| Decay timer attached to `_room_provenance` | **NEW.**  No `decay|hold_last|HOLD_LAST|last_known` matches in `presence.py`.  The closest pattern is camera tier (`_camera_last_seen` + `_CAMERA_OCCUPANCY_TIMEOUT_SECONDS`); D1 introduces a parallel `_fan_interference_hold_until: Dict[str, datetime]` field on each `ZonePresenceTracker`. | Same idiom as camera tier — minimal new surface.  Not a new dataclass, just a dict + a check in the derived view. |  |
| `CONF_FAN_INTERFERENCE_HOLD_S` (decay duration) | **NEW.**  No existing fan-interference Number.  Add ONE Number entity on the Presence Coordinator device. | Default 300s (mirror camera timeout); range 60-1800. |  |
| `CONF_FAN_INTERFERENCE_GATE_ENABLED` | **NEW — but possibly redundant with `D3_DIAGNOSTIC_ENABLED`.**  Decision recorded in D1.1: collapse into `D3_DIAGNOSTIC_ENABLED` as the single kill switch (off → no flagging, no gating, no pause; on → all three).  Avoids a 4-knob explosion. | Single switch, plus Layer-2-only switch for the pause (D2.1). |  |
| `CONF_FAN_PAUSE_ENABLED` (Layer-2 master) | **NEW.**  No existing pause-fan-for-recheck CONF. | Per-room and per-Presence-Coordinator master.  Default OFF — Layer-2 is opt-in (operator's "rare" requirement). |  |
| `SIGNAL_FAN_INTERFERENCE_*` | **NEW signals.**  `signals.py` has no fan-interference signals today.  Add `SIGNAL_FAN_INTERFERENCE_GATE_FIRED`, `SIGNAL_FAN_PAUSE_STARTED`, `SIGNAL_FAN_PAUSE_RESTORED`. | Used by NM for the rare pause notification and by diagnostic sensors for UI update. |  |
| `FanPauseHistorySensor` | **NEW sensor.**  Per-room history of pause attempts + outcome ("vacated" / "still-occupied").  Cap to last 10 events. | Operator's mandate: pause history must be visible. |  |

### B. Prior planning docs consulted

| Doc | Relevance | Read depth |
|---|---|---|
| `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md` | The predecessor cycle that shipped the foundation D1 builds on. | Full body. |
| `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` | The standing deferred-items doc.  This plan supersedes Items 1 + 2; Items 3 (PIR fusion), 4 (HA community blueprint), 5 (mmwave_occupied_count shim removal) remain there. | Full body. |
| `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md` | Audit GREEN verdict — names the 22 SAFE / 5 AT-RISK / 0 GATING readers of `_room_occupied` and `_room_provenance`.  D1's ripple audit uses Appendix A.2 + A.3 as the starting consumer list. | Skimmed for naming corrections (see Table A) + Appendix A.2/A.3 callsite map. |
| `docs/planning/AUDIT_presence_provenance.md` | GREEN verdict; consumer classification. | Header + verdict only. |
| `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md` | The non-URA research note stub.  Confirms publishing is gated on Layer-1 data, not blocking this cycle. | Full body. |
| `docs/planning/PLANNING_v4.7.8_egress_window_hvac_pause.md` | Snapshot/restore + restart-resilience pattern for the FIRST presence-side actuation.  D2 borrows the state machine + DAO shape. | §1-3, §D3-D6 (snapshot/restore + 4 restart scenarios). |
| `docs/planning/PLANNING_v4.7.15_universalize_bug_class_48_veto.md` | D4 relocation of `check_zone_occupancy_confidence` — confirms the public-method shape D1 ripples through. | §0.1 + §D4 only. |
| `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` | Confirms `_ble_occupied` path is the canonical "tier-3 BLE" surface and how the v4.7.14 veto integrates with it. | Skim. |
| `docs/planning/PLANNING_v4.7.14.1_forgotten_phone_hotfix.md` | The `PersonPhoneLeftBehindSensor` H2 carve-out pattern Layer-2's L3 check must mirror. | §D1 + fail-OPEN discipline only. |
| `docs/planning/PLANNING_v4.7.16_room_level_veto_density_weighting.md` | Source of the `is_room_direct_ble` naming truth — used to correct Table A row 1. | Header + §A.1 only. |
| `docs/readmes/README_v4.7.19.md` | Predecessor live-validated state.  D5 (the attribute surface) is the input D1 reads. | Full body. |
| `docs/TECH_DEBT.md` Presence Tier-1 OR entry | RESOLVED.  No longer the gating tech debt for this cycle. | Verified. |
| `docs/BACKLOG.md` Fan-noise entry | Source brief — operator's "BLE-gated pause not dumb periodic" framing. | Verified. |

### C. Memory bodies pulled

| File | Relevance |
|---|---|
| `project_fan_noise_mmwave_mitigation_backlog.md` | Operator's verbatim design intent (notes a + b, CORE REFRAME on interference-conditional reliability vs fusion, pets sharpen note a, 3-layer BLE ladder).  This plan IS the buildable form of that memo. |
| `project_v4_7_18_1_sleep_wake_deadlock.md` (referenced) | The D1 "fan-noise side-quest" memo — confirms predecessor cycle resolved the eager-6AM-wake residual.  No new constraint for this cycle. |

### D. Design docs read

| Doc | Relevance |
|---|---|
| `docs/Coordinator/PRESENCE_COORDINATOR.md` | Foundation coordinator semantics ("presence provides STATE, not ACTIONS").  D2 makes the FIRST presence-side actuation — see §11 of the design doc for the Tier-3-BLE outputs map.  Updated by predecessor with the per-kind provenance section. |

### E. Code locations surveyed (read end-to-end during scoping)

| File | Lines surveyed | What was confirmed |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/presence.py` | `:47` (D3 flag import), `:71` (camera timeout), `:370-450` (`_room_provenance`, `_room_occupied` derived, `provenance_for`), `:480-535` (`_derived_mode`, `_any_camera_occupied`), `:558-650` (`update_room_occupancy`, `update_camera_detection`, `update_ble_presence`), `:968` (`check_zone_occupancy_confidence` public method), `:988-990` (`_signal_consensus` state), `:1432` (`get_persons_in_zone` BLE Tier-3 driver), `:2151-2376` (D3 fan listener + `_compute_fan_interference_rooms`), `:3251-3315` (`PersonPhoneLeftBehindSensor` H2 carve-out pattern), `:4080-4198` (signal_consensus block + D3 output publish) | Foundation for D1 + D2.  Existing fan-interference machinery + BLE Tier-3 + camera-timeout decay pattern are all present and ready to be composed. |
| `custom_components/universal_room_automation/domain_coordinators/hvac_fans.py` | `:21` (CONF_FANS import), `:132` (fan list read), `:170` (`turn_off_all_managed`), `:508, 514, 521, 527` (existing fan-write callsites) | Existing fan actuation surface.  D2 adds a narrow `pause_fan_for_interference_check` / `restore_fan` pair that does NOT route through the fan-temp manager. |
| `custom_components/universal_room_automation/const.py` | `:351` (`D3_DIAGNOSTIC_ENABLED`), `:373` (CONF_FANS), `:481-490` (CONF_FAN_CONTROL_ENABLED, CONF_FAN_VACANCY_HOLD) | Existing CONF inventory.  No CONF_ADJACENT_ROOMS — NEW addition (D1.5). |
| `custom_components/universal_room_automation/aggregation.py` | `:3937, 3966, 4076` (`get_persons_in_zone` Bermuda BLE path) | The BLE Tier-3 reads zone-rooms list and counts persons.  Layer-2 L3 zone-absence check piggybacks on this. |
| `custom_components/universal_room_automation/binary_sensor.py` | `:410-458` (D5 D3 attribute block reading `fan_interference_rooms` from signal_consensus_inputs), `:973-1084` (`PersonPhoneLeftBehindSensor`), `:1031` (class definition) | D5 D3 attrs are the existing UI surface — D1 enriches them with the gate state.  D2 adds a new `fan_pause_state` per-room attribute alongside. |
| `custom_components/universal_room_automation/person_coordinator.py` | `:1145` (`get_persons_in_room`), `:1149` (`is_room_direct_ble`), `:1243` (`get_persons_in_zone`) | The BLE-direct-room accessor + zone-rooms BLE count. |

---

## Non-goals (explicit)

- **No removal of the existing observation-only D3 diagnostic.**  D1 builds ON it; the observation publish path stays so post-deploy validation can compare "rooms flagged but NOT gated" (the diagnostic) vs "rooms gated" (the new D1).
- **No PIR + mmwave fusion in this cycle.**  Stays in `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` Item 3 — hardware-gated.
- **No HA community blueprint.**  Stays in deferred-items Item 4 — separate audience.
- **No removal of the `mmwave_occupied_count` deprecation shim.**  Stays in deferred-items Item 5 — separate tail-clean.
- **No automatic adjacency derivation from HA areas.**  Operator-named per-room `CONF_ADJACENT_ROOMS: list[str]` is the model.  No HA area-graph heuristics.
- **No new house-level state.**  D1 may discount mmwave but cannot move the house out of OCCUPIED on its own — that's already protected by the Tier-3 BLE path + camera path + the v4.7.14 away-veto.
- **No DPM / preset interaction.**  Layer-2 pause is a temporary fan command — it does NOT mutate HVAC mode or preset.
- **No automatic Layer-2 enablement.**  Layer-2 is opt-in per room (default OFF), per operator's "rare" requirement.

---

## D1 — Layer-1: silent interference-conditioned confidence discount + decay (PROMOTE GATE)

### D1.1 — Kill switch + master config

**Scope:** `const.py`, `domain_coordinators/presence.py`.

**Changes:**

- REUSE `D3_DIAGNOSTIC_ENABLED` as the SINGLE kill switch for the whole fan-interference feature (observation + gate).  When False, `_compute_fan_interference_rooms` short-returns `[]` (already so at `:2295`) AND the new gate is inert.
- NEW per-Presence-Coordinator `CONF_FAN_INTERFERENCE_GATE_ENABLED` Number-style switch (Boolean), default **True**.  Allows the operator to disable JUST the gate without losing the diagnostic.  This is the rollback knob if the cycle ever needs to revert behavior without code change.
- NEW `CONF_FAN_INTERFERENCE_HOLD_S`: Number, default 300 (mirror camera), range 60-1800, step 30, unit `s`.  Per-Presence-Coordinator.

### D1.2 — The interference-conditioned gate (the headline)

**Scope:** `domain_coordinators/presence.py`.

**Semantic:** when a room is currently in `_compute_fan_interference_rooms()` AND the BLE corroboration ladder says "not corroborated," the room's mmwave-sole provenance is DISCOUNTED — but the room is NOT immediately dropped to unoccupied.  Instead `_fan_interference_hold_until[room_name] = now + CONF_FAN_INTERFERENCE_HOLD_S` and the derived `_room_occupied` view continues to read TRUE until the hold expires.  At hold expiry, the room is allowed to read FALSE normally.

**The BLE corroboration ladder (3 layers, all evaluated):**

1. **L1 — room BLE present.**  `person_coord.get_persons_in_room(room_name)` returns a non-empty list of phone-trustworthy persons (apply the `PersonPhoneLeftBehindSensor` H2 carve-out mirroring `presence.py:3258-3315`).  If TRUE → **trust mmwave**, no discount, no hold, no pause.
2. **L2 — adjacent room BLE present.**  Any room in `entry.options[CONF_ADJACENT_ROOMS]` for the fan-suspect room has `person_coord.get_persons_in_room(adj_room)` non-empty (same H2 carve-out).  If TRUE → **lean occupied** — set the hold but do NOT discount (mmwave still feeds the derived OR).  In effect: same as the hold path, but pause is FORBIDDEN even if Layer-2 (D2) is enabled.
3. **L3 — zone-wide BLE absence.**  `not tracker._ble_occupied` (already exists at `:498`).  If TRUE → **strongest discount signal** — set the hold AND mark the room `pause_eligible=True` (consumed by D2 if the operator enabled Layer-2 for the room).

If NONE of L1/L2/L3 give a verdict (e.g., zone has no BLE infrastructure), fall through to: hold under decay, no pause.  Pets are NOT rejected by Layers 1/2 (a dog has no phone); only L3 zone-absence rejects pets.

**Storage:** new field on `ZonePresenceTracker`:

```python
self._fan_interference_hold_until: Dict[str, datetime] = {}
```

**Derived view update:** modify the `@property _room_occupied` to consult the hold dict (does NOT mutate `_room_provenance` — the lie is contained to the read path):

```python
@property
def _room_occupied(self) -> Dict[str, bool]:
    now = dt_util.utcnow()
    return {
        room: (any(bool(v) for v in kinds.values()) or
               (room in self._fan_interference_hold_until and
                self._fan_interference_hold_until[room] > now))
        for room, kinds in self._room_provenance.items()
    }
```

This preserves all 22 SAFE consumers (the projected dict has the same shape) and means a fan-suspect mmwave-sole room continues to read OCCUPIED until the hold expires — exactly the "silent, no disruption" behavior the operator wants.

**Critical invariant (Reviewer A focus):** the hold can only EXTEND occupancy, never shorten it.  If `_room_provenance` has any True kind, the room reads occupied regardless of the hold.  The hold is a TRUTH-PRESERVING layer.

**Reset rules:**
- L1 fires (room BLE present) → clear hold (no longer needed; mmwave is trusted again).
- A non-mmwave kind in `_room_provenance` flips True → clear hold (no longer mmwave-sole).
- Hold expires → drop the key; next tick's `_compute_fan_interference_rooms` re-evaluates.

### D1.3 — Cross-coordinator ripple audit (the operator's "context-wide, no regression" gate)

**This is the deliverable that gates D1 build start.**  Same audit-first discipline as the predecessor cycle.

For each of the following consumers, verify the discount-via-hold behavior does NOT introduce a false-unoccupied that flips downstream gates:

| Consumer | File:line | Read shape | Hazard | Mitigation in D1 |
|---|---|---|---|---|
| HVAC defer gate | `hvac.py:870` calls `presence_coord.check_zone_occupancy_confidence(zone)` | `(confirmed, possible)` tuple counting Tier-1 occupied rooms | A fan-suspect "occupied via hold" room currently counts as `confirmed`; verify the gate semantics still match operator intent (the room IS effectively occupied per the conservative discount). | NO CODE CHANGE.  The discount-via-hold means the room stays in `confirmed`.  Documented invariant: the hold can only EXTEND occupancy.  Reviewer A verifies. |
| Compliance gate | (callsite — TBD via grep at build time) consuming `signal_consensus` and `_signal_consensus_inputs` | Reads `tier1_occupied_count` | Same as above — hold-occupied rooms still count.  No false-LOW consensus. | NO CODE CHANGE.  Same invariant. |
| Safety coordinator hazard counts | `safety.py` (read at build time) | Indirect via house state | Hold-occupied → house state unchanged from current cycle | NO CODE CHANGE. |
| HVAC zone-state aggregator | `hvac_zones.py` `update_room_conditions` | Reads zone tracker.mode | Mode derives from `_room_occupied` projection → unchanged by hold | NO CODE CHANGE. |
| `OccupiedBinarySensor` D5 attrs | `binary_sensor.py:410-458` | Reads `_room_provenance` + `fan_interference_rooms` | Surface ENRICHED: add `fan_interference_hold_active` + `fan_interference_hold_until_iso` attrs | NEW attributes (no behavior change). |
| House state inference (`_run_inference`) | `presence.py:3234+` | Reads `any_zone_occupied = any(t.mode == OCCUPIED for ...)` | Hold-occupied → zone mode stays OCCUPIED → no false AWAY transition | NO CODE CHANGE. |
| `check_zone_occupancy_confidence` itself | `presence.py:968` | Counts occupied rooms across BLE + Tier-1 + camera | Hold preserves Tier-1 count | NO CODE CHANGE. |
| `_audit_provenance_invariants` | (predecessor cycle) | Asserts derived view ⊇ recorded kinds | Hold makes the derived view sometimes BROADER than recorded kinds — invariant must be RELAXED to say "derived ⊇ kinds OR hold-active" | RELAX INVARIANT.  Reviewer A focus. |

**Audit deliverable:** a section in the planning doc PR description (or a sidecar `AUDIT_fan_interference_gate_ripple.md`) listing every read site of `_room_provenance` / `_room_occupied` / `tracker.mode` / `check_zone_occupancy_confidence` and the verdict (SAFE / NEEDS-CHANGE / GATING).  Builder MUST NOT start D1.2 until the audit is GREEN.

### D1.4 — Acceptance Criteria

- **Verify:** when fan-on + mmwave-sole + L3 zone-absent, the `OccupiedBinarySensor` for the room continues to read `on` for `CONF_FAN_INTERFERENCE_HOLD_S` after the (pre-D1) drop point.
- **Verify:** when L1 fires mid-hold (phone arrives in room), the hold clears and behavior returns to baseline within one inference tick.
- **Verify:** when mmwave clears naturally AND no fan is on, behavior matches predecessor (no hold extension, no regression).
- **Verify:** `_audit_provenance_invariants` no longer raises when the hold extends the derived OR.
- **Verify:** house-state inference does not flip OCCUPIED→AWAY because of a hold-extended room.
- **Sensor:** `binary_sensor.<room>_occupied` carries new attrs `fan_interference_hold_active: bool`, `fan_interference_hold_until_iso: str | None`, `ble_corroboration_layer: "L1" | "L2" | "L3" | "none"`.
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` `signal_consensus_inputs.fan_interference_gated_rooms: list[str]` distinct from the existing `fan_interference_rooms` (gated = "had a hold applied this tick"; suspect = "flagged by D3 logic").
- **Test:** `test_fan_interference_gate_L1_clears_hold`, `test_fan_interference_gate_L2_holds_no_pause`, `test_fan_interference_gate_L3_holds_pause_eligible`, `test_fan_interference_gate_hold_expires_drops_room`, `test_fan_interference_gate_phone_left_behind_excluded_from_L1` (H2 carve-out), `test_room_occupied_property_hold_preserves_provenance_dict_shape`, `test_audit_provenance_invariant_relaxed_under_hold`.
- **Live:** post-deploy + restart, identify a known fan-on bedroom; verify the room appears in `fan_interference_rooms` AND `fan_interference_gated_rooms` AND the `OccupiedBinarySensor` does NOT drop for at least `CONF_FAN_INTERFERENCE_HOLD_S` after the operator leaves the room with no BLE in the zone.  Conversely, verify a room with the operator's phone present (L1) never gets the hold.

### D1.5 — `CONF_ADJACENT_ROOMS` per-room config (the only big new surface)

**Scope:** `const.py`, `config_flow.py`, `options_flow.py`, room entry options shape.

- NEW `CONF_ADJACENT_ROOMS: Final = "adjacent_rooms"`.  Per-room list of room-entry IDs (or display names — TBD at build time, mirror the existing room-list selector pattern in zone config).
- Initial install + reconfigure: add an optional multi-select selector listing OTHER configured rooms.
- No migration helper (per the v4.7.4.4 lazy-derivation doctrine).  Read with `entry.options.get(CONF_ADJACENT_ROOMS, [])` — empty list is safe (L2 cannot fire, L1 and L3 still work).
- Per-room helper text: "Rooms whose BLE presence should be treated as 'probably the same person drifting' for fan-interference purposes.  Example: bathroom ↔ adjacent bedroom."

**Acceptance Criteria:**

- **Verify:** install-time + reconfigure round-trip preserves the list.
- **Verify:** a room with `adjacent_rooms=[]` falls through L2 (no L2 verdict) safely.
- **Test:** `test_conf_adjacent_rooms_default_empty_safe`, `test_conf_adjacent_rooms_roundtrip_options_flow`.
- **Live:** in the operator's house, configure Master Bedroom `adjacent_rooms = ["Master Bath"]` (and inverse).  Verify Jaya's drift-case (phone flipping bathroom↔bedroom) keeps both rooms occupied during a fan-on period.

---

## D2 — Layer-2: BLE-gated RARE fan-pause-and-recheck fallback (DESIGN, build-gated on D1 live)

### D2.0 — Build gating

**This deliverable is DESIGN ONLY in this doc.**  Build start gated on:

1. D1 LIVE for ≥1 full cycle without regression in HVAC/compliance/safety.
2. Live data shows ≥N events/week where D1 entered the hold-with-pause-eligible state (i.e., L3 zone-absent fan-suspect rooms — the only path that would have invoked D2).  N is operator-decided post-D1.
3. Operator confirms the per-room opt-in mechanism + the pause-history UI (D2.5).
4. HVAC fan-policy owner (same operator — but second-look at the cross-rule precedence matrix in D2.6) sign-off.

### D2.1 — State machine + master CONFs

**Scope:** new file `domain_coordinators/presence_fan_pause.py` (mirror `hvac_egress.py` sibling pattern).

States (mirror the v4.7.8 `EGRESS_STATE_*` constants):
- `idle` — default; not pause-eligible OR pause disabled for room.
- `armed` — D1 entered the hold with `pause_eligible=True`; waiting for an arm-confirmation timer (default 60s, configurable Number) to expire before pausing — gives L1 / L2 a chance to fire and cancel.
- `paused` — fan turned off; awaiting `CONF_FAN_PAUSE_RECHECK_S` (default 180s — half of the operator's prior "3 min" periodic, but BLE-justified).
- `restoring` — fan turning back on; awaiting `CONF_FAN_PAUSE_RESTORE_DELAY_S` (default 5s) before re-evaluating.
- `cooldown` — pause attempt completed; per-room rate-limit `CONF_FAN_PAUSE_COOLDOWN_S` (default 3600s — 1 hour) before another attempt is allowed.

NEW CONFs:
- `CONF_FAN_PAUSE_ENABLED` (per-Presence-Coordinator master switch).  Default **False** (Layer-2 is opt-in).
- `CONF_ROOM_FAN_PAUSE_ENABLED` (per-room).  Default **False**.
- `CONF_FAN_PAUSE_ARM_DELAY_S` (Number, default 60, range 30-300).
- `CONF_FAN_PAUSE_RECHECK_S` (Number, default 180, range 60-600).
- `CONF_FAN_PAUSE_RESTORE_DELAY_S` (Number, default 5, range 1-30).
- `CONF_FAN_PAUSE_COOLDOWN_S` (Number, default 3600, range 600-7200).
- `CONF_FAN_PAUSE_MAX_PER_HOUR` (Number, default 1, range 0-3).  Hard ceiling.

### D2.2 — Pause / restore actuation surface

**Scope:** `domain_coordinators/hvac_fans.py` — add a NEW narrow surgical surface:

```python
async def pause_fan_for_interference_check(room_name: str) -> FanSnapshot | None
async def restore_fan(room_name: str, snapshot: FanSnapshot) -> None
```

Both methods:
- Read `CONF_FANS` for the room.
- Snapshot current state (entity state + attributes: `percentage`, `preset_mode`, `oscillating`, `direction`).
- Issue `fan.turn_off` with the bare-fan entity (NOT routed through `turn_off_all_managed` which would side-effect HVAC).
- Restore via `fan.turn_on` with the snapshotted attributes.
- DO NOT touch HVAC climate state.

Cross-rule precedence (Reviewer C focus):
- If `CONF_FAN_CONTROL_ENABLED` is False for the room → pause is FORBIDDEN (operator has hand on the wheel).
- If the fan is already off when the gate fires → state machine goes idle → cooldown (no actuation needed; the "vacancy" hypothesis is already proven).
- If `CONF_FAN_VACANCY_HOLD` is active for the fan AND the fan-temp manager is currently asserting → defer pause attempt to next cycle (do not race the temp manager).

### D2.3 — Per-room snapshot DB

**Scope:** `database.py` — new table `fan_pause_state` mirroring `egress_state` line-for-line.  Schema (DDL extracted from production source by behavioral test — Reviewer C):

| Column | Type | Notes |
|---|---|---|
| `room_id` | TEXT PRIMARY KEY | Per-room (matches room config entry_id). |
| `state` | TEXT NOT NULL | One of the 5 state-machine labels. |
| `state_entered_at` | TEXT | ISO8601 UTC. |
| `snapshot_json` | TEXT | JSON-serialized `FanSnapshot` (fan entity_id + attrs). |
| `attempts_in_hour` | INTEGER NOT NULL DEFAULT 0 | Rolling-1h counter, decayed at read. |
| `last_outcome` | TEXT | `"vacated"` / `"still_occupied"` / NULL. |
| `last_attempt_at` | TEXT | ISO8601 UTC. |

DAOs (5, mirror `egress_state`):
- `get_fan_pause_state(room_id) -> FanPauseStateRow | None`
- `save_fan_pause_state(row: FanPauseStateRow) -> None`
- `get_all_fan_pause_state() -> list[FanPauseStateRow]`
- `clear_fan_pause_state(room_id) -> None`
- `prune_stale_fan_pause_state(cutoff_days: int = 14) -> int`

### D2.4 — Restart resilience (4 scenarios, mirror v4.7.8 §D6)

| Scenario | Behavior on `async_setup` rehydrate |
|---|---|
| Restart while `paused` | Read snapshot; if `(now - state_entered_at) < CONF_FAN_PAUSE_RECHECK_S * 2`, ABORT → transition `restoring` immediately (restore fan from snapshot).  Else snapshot is too old → log warning, transition `idle`, do not actuate. |
| Restart while `restoring` | Transition `idle` (HA restart resets fan to whatever physical state); operator can intervene. |
| Restart while `cooldown` | Honor remaining cooldown (state machine re-arms cooldown from `state_entered_at`). |
| Restart while `armed` | Drop to `idle` — the D1 hold conditions will re-evaluate on next inference tick.  No actuation attempted (Bug Class #14 — first-tick post-restart). |

### D2.5 — UI surfaces (operator-mandated visibility)

- `sensor.ura_room_<room>_fan_pause_state` per pause-eligible room — shows state label.
- `sensor.ura_room_<room>_fan_pause_history` — last 10 pause events with outcome.  Attribute-only ring buffer (no DB sensor table; reuse the `fan_pause_state.last_outcome` per row).
- `binary_sensor.ura_room_<room>_fan_pause_in_progress` — convenience boolean.
- NM dispatch on `fan_pause_started` and `fan_pause_restored` (NEW signals `SIGNAL_FAN_PAUSE_STARTED` / `SIGNAL_FAN_PAUSE_RESTORED`; NM notification category routed to the operator's phone only — not house-wide; not CRITICAL).
- Service `ura.fan_pause_force_restore(room)` — operator escape hatch if a pause hangs.

### D2.6 — Cross-rule precedence matrix (Reviewer C deliverable at D2 build)

| Rule | Winner over fan-pause | Notes |
|---|---|---|
| Operator-driven fan service call (`fan.turn_on` from outside URA) | OPERATOR wins | If a state change for the fan arrives while `paused`, abort → `restoring`. |
| `CONF_FAN_CONTROL_ENABLED == False` | OPERATOR wins | Pause forbidden. |
| `CONF_FAN_VACANCY_HOLD` active + fan-temp manager asserting | TEMP MANAGER wins | Defer pause attempt. |
| HVAC `EgressManager` paused this zone | EGRESS wins | Don't add a second actuation on top. |
| `MAX_PER_HOUR` exceeded | RATE LIMIT wins | State machine returns to idle without attempt. |
| Operator service `fan_pause_force_restore` | OPERATOR wins | Immediate restore from snapshot if available. |

### D2.7 — Acceptance Criteria (build-time only)

Filed as design-only here.  Will be expanded when D2 build start is authorized.

- **Verify:** all 4 restart scenarios behave per §D2.4 (behavioral tests with synthetic DB state).
- **Verify:** pause-then-physical-still-occupied → `last_outcome="still_occupied"` → fan restored → cooldown applied.
- **Verify:** pause-then-zone-truly-empty → `last_outcome="vacated"` → fan stays off (operator-empty bedroom case) → next inference tick correctly drops the zone via the natural BLE/camera/timeout path.
- **Sensor:** `sensor.ura_room_<room>_fan_pause_state` round-trips through restart.
- **Test:** new `quality/tests/test_fan_pause_state_machine.py`, `test_fan_pause_db_schema.py` (DDL extracted from production), `test_fan_pause_restart_scenarios.py`.
- **Live:** at least one observed pause-and-recheck event with operator-confirmed outcome.  Operator triggers `fan_pause_force_restore` once to verify escape hatch.

---

## D3 — Files changed (full list, both deliverables)

| File | D1 changes | D2 changes (design only) |
|---|---|---|
| `const.py` | + `CONF_FAN_INTERFERENCE_GATE_ENABLED`, `CONF_FAN_INTERFERENCE_HOLD_S`, `CONF_ADJACENT_ROOMS`, defaults | + all `CONF_FAN_PAUSE_*` constants, state labels, NM event types |
| `domain_coordinators/presence.py` | gate semantics in `_compute_fan_interference_rooms`, new `_fan_interference_hold_until` field, modified `_room_occupied` property, relaxed `_audit_provenance_invariants`, expanded `signal_consensus_inputs` | (none — D2 lives in its own file) |
| `domain_coordinators/presence_fan_pause.py` | (none) | NEW FILE — state machine, DB rehydrate, snapshot/restore, manual override, cooldown, NM dispatch, ~250 LoC |
| `domain_coordinators/hvac_fans.py` | (none) | + narrow `pause_fan_for_interference_check` / `restore_fan` surface |
| `domain_coordinators/signals.py` | (none) | + `SIGNAL_FAN_PAUSE_STARTED`, `SIGNAL_FAN_PAUSE_RESTORED` |
| `database.py` | (none) | + `fan_pause_state` DDL + 5 DAOs (mirror `egress_state`) |
| `config_flow.py` | + `CONF_ADJACENT_ROOMS` selector in room install + reconfigure | + `CONF_ROOM_FAN_PAUSE_ENABLED` per-room |
| `options_flow.py` | + `CONF_FAN_INTERFERENCE_GATE_ENABLED`, `CONF_FAN_INTERFERENCE_HOLD_S` on PresenceCoordinator entry | + `CONF_FAN_PAUSE_*` master + timing Numbers |
| `switch.py` | + Presence-Coordinator `FanInterferenceGateSwitch` | + Presence-Coordinator `FanPauseEnabledSwitch`, per-room `RoomFanPauseEnabledSwitch` |
| `number.py` | + `FanInterferenceHoldNumber` | + 5 `FanPause*Number` |
| `binary_sensor.py` | + new attrs on `OccupiedBinarySensor` (`fan_interference_hold_active`, `fan_interference_hold_until_iso`, `ble_corroboration_layer`) | + `RoomFanPauseInProgress` per pause-eligible room |
| `sensor.py` | + `fan_interference_gated_rooms` in house-state attrs | + `RoomFanPauseStateSensor`, `RoomFanPauseHistorySensor` |
| `services.yaml` | (none) | + `fan_pause_force_restore` |
| `quality/tests/test_fan_interference_gate_*.py` | NEW — see D1.4 | (none in D1 cycle) |
| `quality/tests/test_fan_pause_state_machine.py` + `test_fan_pause_db_schema.py` + `test_fan_pause_restart_scenarios.py` | (none) | NEW — for D2 build cycle |
| `quality/tests/test_room_occupied_property_hold.py` | NEW — property-level invariants | — |
| `quality/tests/test_cross_coordinator_ripple_gate.py` | NEW — explicit ripple test for HVAC defer gate, compliance gate | — |

**Reads (no edit):**
- `docs/QUALITY_CONTEXT.md` Bug Classes #1, #5, #10, #14, #20, #21, #42, #46
- `docs/planning/INVESTIGATION_presence_provenance_audit_and_fan_noise.md` Appendix A.2 + A.3 (consumer list)
- `docs/planning/PLANNING_v4.7.8_egress_window_hvac_pause.md` §D3-D6 (snapshot/restore + 4 restart scenarios)

---

## D4 — Plan completion tracking (CLAUDE.md mandate)

**NOT BUILT in this cycle (explicitly deferred):**

| Item | Defer reason | Where tracked |
|---|---|---|
| PIR + mmwave fusion backstop | Hardware-gated (rooms today are mmwave-only).  Provenance split makes the fusion expressible — gating is operator's hardware audit. | `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` Item 3. |
| NON-URA research note + HA blueprint | Separate audience.  Publishing depends on Layer-1 (this cycle's D1) producing ≥1 week of live data confirming the interference-conditional reliability primitive works. | `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` Item 4. |
| `mmwave_occupied_count` deprecation shim removal | Predecessor cycle is LIVE — 1-cycle grace ongoing. | `PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md` Item 5. |
| Automatic adjacency derivation from HA areas | Operator-named adjacency is the simpler, no-fabrication choice.  Auto-derivation can be a future "convenience" cycle if `CONF_ADJACENT_ROOMS` config burden proves painful. | This planning doc, §Non-goals. |
| D2 build (Layer-2 pause-and-recheck) | Design only this cycle.  Build authorized after D1 live + ≥N L3-zone-absent events observed + operator UI sign-off. | This planning doc, §D2.0 build gating. |

---

## D5 — Open questions / scope risks for operator weigh-in

1. **`CONF_ADJACENT_ROOMS` model is genuinely new and is a per-room config burden.**  Operator names neighbors (e.g., Master Bedroom ↔ Master Bath).  Alternative: derive from HA area hierarchy — REJECTED in this plan as too brittle.  Operator OK with the explicit-config approach for the rooms they care about, OR would they prefer to skip L2 entirely in D1 and rely only on L1 + L3?
2. **Decay default 300s (5 min) — same as camera tier.**  Operator's prior dumb-periodic was 3 min.  Are 5 min holds for a fan-suspect mmwave-sole room acceptable when the operator legitimately steps out for 4 min, OR should the default be 180s to align with their muscle memory?
3. **D1 ripple audit — should it be a sidecar `AUDIT_fan_interference_gate_ripple.md` doc, or inline in the planning-doc PR description?**  Recommend sidecar (mirror predecessor cycle's `AUDIT_presence_provenance.md` precedent — discoverable, scope-locked).
4. **D2 NM notification routing — operator phone only, or house-wide?**  Plan defaults to operator phone (rare event, not a CRITICAL).  Confirm.
5. **D2 pause default is OFF per-room.**  Operator confirmed in the memo "rare and BLE-justified" — this enforces opt-in.  Confirm OK.
6. **Tier 2-DB elevation — is the operator OK with the three-reviewer overhead for D1 alone?**  Alternative: defer the DB-changing pieces (D2 only) into a second cycle, ship D1 as plain Tier 2 (two reviewers).  Recommend keeping D1 at Tier 2-DB because of the cross-coordinator ripple — but acknowledge the build overhead trade-off.
