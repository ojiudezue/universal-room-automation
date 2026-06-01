# PLANNING v4.7.16 — Room-level veto + Bermuda-scanner-aware density weighting via existing CONF_SCANNER_AREAS

**Tier:** 2-DB (three parallel reviewers, each framed against a different risk axis)
**Sibling cycles (in flight):**
- v4.7.14 — Away-State Person-Tracker Trust Veto (inference engine veto plumbing)
- v4.7.14.1 — follow-up to v4.7.14 (not on disk yet at planning time; parallel-merge target)
- v4.7.15 — Universalize Bug Class #48 Veto (shared veto helper API; not on disk yet at planning time — confirmed by `Glob docs/planning/PLANNING_v4.7.15_*`)
- v4.7.16 (this doc) — consumes v4.7.15's helper, adds per-room weighting

**Catalyst:** v4.7.14 empty-house oscillation + 2026-05-30 user principle ("Cam person is good. Cam motion needs to be context-sensitive to configure for a room.") — surfaced in `INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md`. This cycle delivers the per-room weighting half of that investigation.

**Estimated size:** ~250-350 LoC across `const.py`, `presence.py` (zone presence module), `person_coordinator.py` (read-only surface extension), `sensor.py` (new diagnostic), `config_flow.py` (one new opt-out field), `strings.json` (UI text), `binary_sensor.py` (none), `tests/` (~12 cycle tests).

---

## 0. MANDATORY institutional-context probe (executed before scoping)

### 0.1 `CONF_SCANNER_AREAS` exists (verified)

`custom_components/universal_room_automation/const.py:316-317`:

```python
# v3.2.4: Scanner areas for sparse scanner homes (optional override)
CONF_SCANNER_AREAS: Final = "scanner_areas"  # List of HA area_ids where BLE scanners are
```

v3.2.4 is the origin shipped 2024. Memory + README reference at `docs/readmes/README_v4.5.4.md`, `docs/planning/PLANNING_v4.5.4_room_config_cleanup.md` confirm the constant has been load-bearing since v3.2.4.

### 0.2 `CONF_SCANNER_AREAS` is a per-room field (verified)

Initial config flow at `custom_components/universal_room_automation/config_flow.py:993-997`:

```python
# v3.2.4: Scanner areas for sparse scanner homes
# Optional - only needed if BLE scanners are in different HA areas than the room
vol.Optional(CONF_SCANNER_AREAS, default=[]): selector.AreaSelector(
    selector.AreaSelectorConfig(multiple=True)
),
```

Options flow re-edit at `config_flow.py:6524-6530`:

```python
# v3.2.4: Scanner areas for sparse scanner homes
vol.Optional(
    CONF_SCANNER_AREAS,
    default=self._get_current(CONF_SCANNER_AREAS, [])
): selector.AreaSelector(
    selector.AreaSelectorConfig(multiple=True)
),
```

Both surfaces use `AreaSelector(multiple=True)` — this is the canonical room-level field for sparse scanner overrides. **v4.7.16 does NOT add a new field for fallback rooms. It reuses this one.**

### 0.3 `_build_scanner_room_map` is the existing Tier 1 / Tier 2 classifier (verified)

`person_coordinator.py:448-549` builds three runtime caches off of the per-room `CONF_AREA_ID` + `CONF_SCANNER_AREAS` config: `_scanner_to_rooms`, `_area_id_to_room`, and (v3.8.9) `_direct_ble_rooms`. The classification rule is at `person_coordinator.py:501-504`:

```python
# v3.8.9: Track rooms with direct BLE coverage (Tier 1)
# A room is Tier 1 if it has an area_id but no scanner_areas override.
if area_id and not scanner_areas:
    self._direct_ble_rooms.add(room_name.lower().replace(" ", "_"))
```

The public accessor lives at `person_coordinator.py:1149-1161` (`is_direct_ble_room(room_name) -> bool`). v4.7.16 reads this surface; it does not modify `_build_scanner_room_map`.

### 0.4 The "Tier 1 / Tier 2" comment is in the file header (verified)

`person_coordinator.py:10-13`:

```python
# NEW: Three-tier scanner resolution for room-level person tracking
#   - Tier 1: Direct HA area name match (zero config for dense scanner homes)
#   - Tier 2: CONF_SCANNER_AREAS override lookup (for sparse scanner homes)
#   - Tier 3: Occupancy disambiguation (when multiple rooms share a scanner)
```

Note: this file uses Tier 1/2/3 to mean **BLE scanner-resolution tiers** (distinct from `ZonePresenceTracker`'s Tier 1/2/3 which mean **signal-class tiers**: mmWave/PIR, camera, BLE). To avoid ambiguity, v4.7.16 uses the explicit name `ble_tier` for the scanner-resolution dimension and never says "Tier 1" unqualified in code or attributes.

### 0.5 `strings.json` `scanner_areas` description (verified, exact quote)

`strings.json:123`:

> "Only needed for sparse scanner homes. Select areas where BLE scanners are located that should map to this room. Leave empty if this room has its own scanner."

Options-flow variant at `strings.json:1318`:

> "For sparse scanner homes only. Select areas with BLE scanners that should map to this room."

v4.7.16 README + sensor `friendly_name` text must align with the same vocabulary ("sparse scanner home", "BLE scanner", "scanner areas") — do not re-coin terms.

### 0.6 Prior BLE-tier exposure check (verified)

`grep -rn 'ble_tier\|ble_coverage\|tier_1\|tier_2\|direct_ble_rooms\|ble_fallback' custom_components/` (excluding bundled frontend JS) returns three hits, all in `person_coordinator.py`:
- `:87` — `self._direct_ble_rooms: set[str] = set()` init
- `:482` — reset on rebuild
- `:504` — populate
- `:1149-1161` — `is_direct_ble_room` public accessor

**There is NO existing `ble_tier`, `ble_coverage`, `ble_fallback_room`, or signal-inventory sensor in the codebase.** v4.7.16 is the first introduction. Naming choice: `ble_tier` (1/2/0 — see §2.D1).

Also greppped: `signal_inventory`, `disable_camera_presence`, `DISABLE_CAMERA` → all return no matches. None of these proposed surfaces pre-exist.

### 0.7 Sibling v4.7.15 helper (FORWARD REFERENCE — flagged risk)

Per operator brief, v4.7.15 ships a shared veto helper to be called from this cycle. **`Glob docs/planning/PLANNING_v4.7.15_*` returns no file at planning time.** This is a forward reference. v4.7.16 plan is written assuming v4.7.15 lands first and exposes:
- A pure function (or class method) on a helper module that takes a per-tier weight map and per-room signal state and returns an action: `accept_occupied`, `veto_to_away`, or `defer_to_consensus`.
- The exact signature must be re-confirmed in the v4.7.16 build's pre-implementation review step.

**Mitigation:** if v4.7.15 ships with a different helper signature than this doc assumes, D3 in this cycle is the integration point and will be re-spec'd in a v4.7.16-pre-build note. The rest of v4.7.16 (D1, D2, D4) does not depend on the v4.7.15 helper.

### 0.8 `INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` (verified)

Read in full. Per-room camera opt-out design is at §4.1 (Part A) and §7. Direct quote on the new field name from §4.1:

> "A new room config flag `CONF_DISABLE_CAMERA_PRESENCE: bool` (default False) that, when True, causes URA's discovery code at `presence.py:1118` to skip `tracker.register_camera()` for that room."

The investigation suggested splitting this across two cycles (v4.7.15 Part A + v4.7.16 Part B audit). v4.7.16 takes the per-room camera opt-out as **D4 of this cycle** because (a) v4.7.15 is occupied with the Bug Class #48 veto generalization, and (b) the opt-out is structurally cheap and parallel-mergeable with v4.7.15's helper.

Also: §6.5 of the investigation defines the Bermuda-scanner enumeration rule that this cycle's BLE-tier classification implicitly inherits — Bermuda's scanner registry is the canonical source, **never** an integration-name allowlist. The existing `_build_scanner_room_map` already honors this (it reads HA area registry + per-room config, not Bermuda integration listing). v4.7.16 does not re-implement Bermuda enumeration; it consumes the already-cached results.

### 0.9 v3.2.4 + v3.8.9 origin context (verified)

- v3.2.4 introduced `CONF_SCANNER_AREAS` as the "sparse scanner home" override. Decision context: deprecated `CONF_PHONE_TRACKER` (verified at `const.py:314-315`) in favor of Bermuda person tracking. Origin readme: `docs/readmes/README_v4.5.4.md` (a follow-up cleanup cycle that references the v3.2.4 origin).
- v3.8.9 added the `_direct_ble_rooms` Tier 1 set (`docs/readmes/README_v3.8.9.md`, `docs/ROADMAP_v10.md`, `docs/ROADMAP_v11.md`). Decision context: protect against BLE-tier signals dominating in rooms that were borrowing a scanner from an adjacent area — direct-coverage rooms should still get BLE-as-primary, borrowed-coverage rooms should require confirmatory sensors. **v4.7.16 generalizes this exact distinction into a weight (1.0 vs 0.6 vs 0.0) instead of a binary.**

### 0.10 Prior planning docs + memory entries consulted

Planning docs:
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` (origin of D4 + the §6.5 Bermuda-scanner enumeration rule)
- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` (predecessor — inference engine veto plumbing; v4.7.16 builds on its `infer()` signature)
- `docs/planning/PLANNING_v4.5.4_room_config_cleanup.md` (last cycle to touch the `CONF_SCANNER_AREAS` surface intentionally; backward-compat constraints noted)
- (forward-reference) `docs/planning/PLANNING_v4.7.15_universalize_bug_class_48_veto.md` — **not present at planning time**
- (forward-reference) `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` — **not present at planning time**; this cycle must link to it once v4.7.15 creates it

Source files:
- `custom_components/universal_room_automation/const.py:310-330` (CONF_SCANNER_AREAS + sibling room-config constants)
- `custom_components/universal_room_automation/config_flow.py:985-997` + `:6515-6530` (per-room field surfaces)
- `custom_components/universal_room_automation/person_coordinator.py:1-90, 448-549, 1149-1161` (`_build_scanner_room_map` + `is_direct_ble_room` accessor)
- `custom_components/universal_room_automation/domain_coordinators/presence.py:85-200, 290-300, 1100-1160` (`ZonePresenceTracker._derived_mode` + `register_camera` + camera-discovery loop)
- `custom_components/universal_room_automation/strings.json:107-130, 1300-1325` (per-room field UI text)
- `custom_components/universal_room_automation/sensor.py:1855-1955` (`AutomationHealthSensor` — exemplar per-room diagnostic sensor pattern; v4.7.16's new sensor mirrors this entity-class shape)

Memory entries referenced (consulted, not re-quoted):
- `feedback_no_fabrication.md` (cite file:line for every architectural claim — applied throughout this doc)
- `feedback_db_sensitive_3x_targeted_reviews.md` (3-reviewer Tier 2-DB protocol)
- `feedback_pre_deploy_zero_bugs_gate.md` (mandatory gate before deploy.sh)
- `project_v475_live.md` (Bug Class #47 origin — lazy canonical UI surface; D2 sensor must comply)

---

## 1. Problem statement

Today URA classifies each room as "BLE-direct" (Tier 1) or "scanner-borrowing" (Tier 2 via `CONF_SCANNER_AREAS`) or "neither" (no `area_id` configured), via `person_coordinator._build_scanner_room_map`. The classification is used internally for person-room attribution but is **not surfaced to the inference engine** and **not visible to operators**:

1. **Hidden from operators.** No sensor exposes per-room BLE coverage. Operators don't know which rooms are sparse, can't reason about confidence, and can't target `CONF_SCANNER_AREAS` configuration changes.
2. **Hidden from the veto engine.** When the v4.7.14 / v4.7.15 inference veto fires (all phones away), the weight given to BLE evidence is the same for a direct-coverage room and a sparse room. Sparse rooms should yield more deference to multi-sensor consensus; direct rooms should weight BLE more.
3. **No camera-presence opt-out per room.** Investigation §4.1 identified the surgical fix: allow operators to skip `tracker.register_camera()` for high-false-positive rooms (TV reflections, hallways with sun glare). No such field exists today (`grep CONF_DISABLE_CAMERA` → no matches).

This cycle exposes the existing classification, plugs it into the veto weight, and adds the camera opt-out — all on top of `CONF_SCANNER_AREAS` (v3.2.4 origin) without inventing parallel concepts.

---

## 2. Deliverables

All deliverables follow the strict reuse contract:

> REUSING `CONF_SCANNER_AREAS` from `const.py:317` (v3.2.4 origin) — NOT creating a new field for the fallback-room mechanism.
> REUSING `_build_scanner_room_map` classifications from `person_coordinator.py:448-549` — read-only consumer, not modifying.
> REUSING `is_direct_ble_room` accessor at `person_coordinator.py:1149-1161` (v3.8.9 origin) — extending the same data with a numeric tier.

### D1 — Expose derived attribute `ble_tier` on per-room config-info surface

**File:** `person_coordinator.py` (new read-only accessor) + `binary_sensor.py` or `sensor.py` (whichever already publishes per-room config-info attributes; the build agent verifies which one)

**Behavior:**

Add a public method `get_ble_tier(room_name: str) -> int` on `PersonTrackingCoordinator` that returns:

| Return | Meaning | Source data |
|---|---|---|
| `1` | Direct / dense — room has own scanner | `room_name in self._direct_ble_rooms` |
| `2` | Borrowing / sparse — `CONF_SCANNER_AREAS` configured | room's entry options has non-empty `CONF_SCANNER_AREAS` AND `area_id` is set (else falls to 0) |
| `0` | No BLE / unmapped — neither own scanner nor scanner_areas | otherwise |

Implementation pattern (mirrors `is_direct_ble_room`):

```python
def get_ble_tier(self, room_name: str) -> int:
    """Return BLE coverage tier for a room.

    1 = direct (own scanner), 2 = borrowing (scanner_areas), 0 = neither.
    Read-only consumer of _build_scanner_room_map output.
    """
    norm = room_name.lower().replace(" ", "_")
    if norm in self._direct_ble_rooms:
        return 1
    # Walk room entries to find scanner_areas override
    for entry in self.hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
            continue
        if (entry.data.get("room_name") or "").lower().replace(" ", "_") != norm:
            continue
        config = {**entry.data, **entry.options}
        if config.get(CONF_SCANNER_AREAS) and config.get(CONF_AREA_ID):
            return 2
        return 0
    return 0
```

**No new constant. No new config field. No new persistence.** The value is derived lazily at read time (Bug Class #46 doctrine — see `feedback_no_fabrication.md` lessons applied; cycle v4.7.4.4 set this rule).

### Acceptance Criteria — D1

- **Verify:** `get_ble_tier("Master Bedroom")` returns `1` when the room has `area_id="master_bedroom"` and no `scanner_areas`.
- **Verify:** `get_ble_tier("Living Room")` returns `2` when the room has `area_id="living_room"` AND `scanner_areas=["family_room"]`.
- **Verify:** `get_ble_tier("Closet")` returns `0` when the room has no `area_id` configured.
- **Verify:** Calling `get_ble_tier` before `_build_scanner_room_map` has run returns `0` for any room (no crash, no KeyError — fail-safe).
- **Verify:** Changing a room's `CONF_SCANNER_AREAS` via options flow and reloading the entry causes `get_ble_tier` to return the new tier on next coordinator cycle (read-after-write through cache invalidation in `_build_scanner_room_map`).
- **Test:** `test_get_ble_tier_tier_1_for_direct_coverage`
- **Test:** `test_get_ble_tier_tier_2_for_scanner_areas_override`
- **Test:** `test_get_ble_tier_tier_0_for_unmapped_room`
- **Test:** `test_get_ble_tier_returns_0_before_scanner_map_built` (regression — early-call fail-safe)
- **Test:** `test_get_ble_tier_unknown_room_returns_0`
- **Live:** `state_attr('sensor.ura_room_master_bedroom_signal_inventory', 'ble_tier')` == 1 after restart.
- **Live:** Configuring `CONF_SCANNER_AREAS=["family_room"]` on `living_room` via options-flow, reloading, and re-querying yields `ble_tier=2` within 30 s.

### D2 — New per-room diagnostic sensor `sensor.ura_room_<name>_signal_inventory`

**File:** `sensor.py` (new entity class `RoomSignalInventorySensor`, registered in the room-platform setup loop)

**Entity shape** (mirrors `AutomationHealthSensor` at `sensor.py:1855-1955`):

- `entity_id`: `sensor.ura_room_<slug>_signal_inventory`
- `unique_id`: `<config_entry_id>_signal_inventory`
- `_attr_entity_category = EntityCategory.DIAGNOSTIC`
- `_attr_icon = "mdi:radar"`
- `device_info`: attached to the room device (same as other per-room diagnostics)
- `native_value` (state): a single rolled-up string label, e.g.:
  - `dense` (ble_tier=1 AND at least mmWave OR PIR present)
  - `sparse_with_fallback` (ble_tier=2)
  - `sparse_no_fallback` (ble_tier=0)
  - `pir_only`, `camera_only`, `none` (when ble_tier=0 + degraded sensor mix)

  Rolled-up state intentionally hides numeric tier; numeric tier lives in attributes (Bug Class #47 — lazy canonical UI surface; state is human-readable, attributes are machine-readable).

- `extra_state_attributes`:
  - `ble_tier`: int (1 / 2 / 0)
  - `has_mmwave`: bool (true iff `CONF_MMWAVE_SENSORS` non-empty on this room's config)
  - `has_pir`: bool (true iff `CONF_MOTION_SENSORS` non-empty on this room's config)
  - `has_camera`: bool (true iff `presence.py` discovery registered any camera person sensor for this room — read from `_camera_entity_ids` set membership filtered by room area_id)
  - `has_ble_fallback_room`: bool (true iff `ble_tier == 2`)
  - `scanner_areas`: list[str] (raw value of `CONF_SCANNER_AREAS` for transparency; empty list when absent)
  - `area_id`: str | None (raw `CONF_AREA_ID`)

**Pure introspection.** Reads only — no signal dispatch, no DB writes, no side effects. State derives at read time; attributes derive at read time. No migration helper required (Bug Class #46 doctrine).

**Strict alignment to existing strings.** `friendly_name` and translation strings must use the exact vocabulary in `strings.json:123` ("sparse scanner homes", "BLE scanners", "scanner areas") — do not coin synonyms.

### Acceptance Criteria — D2

- **Verify:** A room with `area_id="master_bedroom"`, `motion_sensors=[binary_sensor.master_bedroom_motion]`, `presence_sensors=[binary_sensor.master_bedroom_mmwave]`, no `scanner_areas`, no discovered camera → state `dense`, `ble_tier=1`, `has_mmwave=True`, `has_pir=True`, `has_camera=False`, `has_ble_fallback_room=False`.
- **Verify:** A room with `area_id="living_room"`, `scanner_areas=["family_room"]`, motion sensors empty, mmwave empty, camera discovered → state `sparse_with_fallback`, `ble_tier=2`, `has_camera=True`, `has_ble_fallback_room=True`, `scanner_areas=["family_room"]`.
- **Verify:** A closet room with no `area_id` and no sensors → state `none`, `ble_tier=0`.
- **Verify:** Sensor exposes `EntityCategory.DIAGNOSTIC` so it doesn't appear in main dashboards by default.
- **Verify:** Round-trip restart preserves state (entity restores from registry; values re-derive lazily on first read).
- **Test:** `test_signal_inventory_state_dense_for_direct_coverage_room`
- **Test:** `test_signal_inventory_state_sparse_with_fallback_when_scanner_areas_configured`
- **Test:** `test_signal_inventory_attributes_ble_tier_matches_get_ble_tier`
- **Test:** `test_signal_inventory_has_camera_reflects_discovery_state`
- **Test:** `test_signal_inventory_lazy_attribute_read_no_migration_required` (Bug Class #46 regression guard)
- **Test:** `test_signal_inventory_pre_setup_no_crash` (entity registered before person_coordinator first cycle returns benign defaults, no exceptions)
- **Live:** Every room config entry has exactly one `sensor.ura_room_<slug>_signal_inventory` entity registered post-restart.
- **Live:** At least one room reports `ble_tier=1`, at least one reports `ble_tier=2` (operator's house has both — confirmed in investigation §6.5 sample), at least one reports `ble_tier=0` (closet or unmapped room).
- **Live:** Operator probe: `ha-mcp` call `get_state('sensor.ura_room_<slug>_signal_inventory')` returns the same `ble_tier` value as `person_coordinator.get_ble_tier(room_name)` for the same room.

### D3 — Per-room confidence-weighted veto in `ZonePresenceTracker._derived_mode`

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py:152-180` (`ZonePresenceTracker._derived_mode`)

**Important architectural note for reviewers:** `_derived_mode` runs on the **zone tracker**, not per room. The zone has `self.room_names: List[str]` (constructor at `presence.py:118, 122`). The per-room weight applies when reasoning about which room's BLE/camera/sensor signal contributed to the current zone-mode decision. Concretely:

- Today: zone is OCCUPIED if **any** room's signal fires (room_occupied dict, any camera fires, any BLE).
- v4.7.16 D3: when the v4.7.15 shared veto helper is consulted, call it once per zone with a **per-room weight aggregation**: each room contributes its `ble_tier`-derived weight to the veto decision rather than a flat 1.0.

The veto helper from v4.7.15 (signature pending — see §0.7) is expected to take:

- `signals: list[RoomSignal]` where each `RoomSignal = (room_name, mode_tier, weight, source_kind)`
- `inputs: VetoInputs` (all_tracked_persons_away, house_state, etc.)
- returns: `VetoVerdict` — one of `accept_occupied`, `veto_to_away`, `defer_to_consensus`

v4.7.16 builds the `signals` list by iterating `self.room_names`, asking person_coordinator for each room's `ble_tier`, and assigning the per-tier weight:

```python
# v4.7.16: per-room BLE weight from canonical CONF_SCANNER_AREAS classification
person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
weights: dict[str, float] = {}
for room_name in self.room_names:
    if person_coord is None:
        weights[room_name] = 1.0  # fail-open: behave like today
        continue
    tier = person_coord.get_ble_tier(room_name)
    if tier == 1:
        weights[room_name] = 1.0
    elif tier == 2:
        weights[room_name] = BLE_TIER_2_WEIGHT  # default 0.6
    else:
        weights[room_name] = 0.0  # BLE contributes nothing; fall back to multi-tier consensus
```

**New constant in `const.py`:**

```python
# v4.7.16: BLE evidence weight for rooms borrowing a scanner via CONF_SCANNER_AREAS.
# Tier 1 rooms (own scanner) implicitly weight 1.0; Tier 0 rooms (no BLE) weight 0.0.
# Operator-tunable so users with high-confidence borrowed scanners can raise
# toward 1.0, or users with noisier shared scanners can lower toward 0.3.
BLE_TIER_2_WEIGHT: Final = 0.6
```

No options-flow exposure in this cycle. The constant is a tuning knob; if operators need to override, that becomes a v4.7.16.x follow-up (cite memory `feedback_configurability_clarity.md` — named-bucket dropdown over raw Number entities).

**Boundary case — what happens when all weights are 0:**

For a zone where every constituent room is Tier 0 (no BLE at all), the BLE channel contributes nothing. The current Tier 1 (mmWave/PIR) and Tier 2 (camera) signal classes in `_derived_mode` still apply. **The zone falls back to multi-tier sensor agreement, exactly as today, without BLE input.** This must be explicitly preserved — see Reviewer A framing.

**Boundary case — when veto helper is unavailable:**

If v4.7.15 ships later than expected or the helper import fails at runtime, D3 falls back to today's behavior (`_derived_mode` returns its existing computation). Wrap the helper call in `try`/`except ImportError` AND a `getattr(..., None)` check for the helper-module method. Log once at WARNING, then degrade gracefully.

### Acceptance Criteria — D3

- **Verify:** A zone composed entirely of `ble_tier=1` rooms produces an `accept_occupied` verdict from the helper when any room's BLE fires (today's behavior preserved).
- **Verify:** A zone composed entirely of `ble_tier=2` rooms (weight 0.6 each) needs corroborating Tier 1/2 (mmWave or camera) before producing `accept_occupied`. With BLE-only firing, helper returns `defer_to_consensus`.
- **Verify:** A zone composed entirely of `ble_tier=0` rooms ignores BLE entirely; the zone's `_derived_mode` returns its pre-v4.7.16 result (sensor + camera tiers only).
- **Verify:** A mixed zone (one Tier 1 room, one Tier 2 room) reports `aggregate_weight=1.0` (max-aggregation; the Tier-1 room dominates), which the helper accepts as occupied. — **POST-REVIEW A1 (HIGH):** updated from "sums to 1.6" → "max=1.0" because Reviewer A chose `max` over `sum` to preserve the v3.8.9 invariant "Tier 1 dominates Tier 2". Under sum, five Tier-2 rooms (5 * 0.6 = 3.0) would outweigh one Tier-1 room (1.0), inverting the design rationale.
- **Verify:** `BLE_TIER_2_WEIGHT` set to 0.0 in `const.py` results in Tier 2 rooms behaving identically to Tier 0 rooms (operator-tunable knob works).
- **Verify:** Helper unavailable (import fails) → `_derived_mode` produces its pre-v4.7.16 result and logs a single WARNING.
- **Verify:** `_derived_mode` performance: per-cycle overhead must be ≤ 5% over pre-v4.7.16 baseline on a 30-room install. Measure with `pytest --benchmark` or timing decorator.
- **Test:** `test_derived_mode_tier_1_room_accepts_occupied_on_ble`
- **Test:** `test_derived_mode_tier_2_room_defers_without_confirmatory_sensor`
- **Test:** `test_derived_mode_tier_0_room_ignores_ble_entirely`
- **Test:** `test_derived_mode_mixed_tier_zone_weight_sums_correctly`
- **Test:** `test_derived_mode_helper_unavailable_falls_back_gracefully`
- **Test:** `test_derived_mode_tier_2_weight_constant_tunable`
- **Test:** `test_derived_mode_called_per_cycle_no_excessive_overhead` (perf regression guard)
- **Live:** After deploy, when all 4 persons are `not_home`, no zone composed entirely of `ble_tier=2` rooms flips to OCCUPIED on camera-only firing.
- **Live:** A `ble_tier=1` zone (e.g., master bedroom) continues to flip to OCCUPIED on BLE-only signal (no regression of dense-house behavior).

### D4 — Per-room camera-presence opt-out at discovery

**New constant** in `const.py`:

```python
# v4.7.16: Per-room opt-out for camera-presence Tier 2 signal contribution.
# When True, presence.py discovery skips tracker.register_camera() for this room.
# Use for rooms with chronic camera person-classifier false positives (TV reflections,
# sun-glare hallways). The room still appears in URA; only its camera signal is muted.
CONF_DISABLE_CAMERA_PRESENCE: Final = "disable_camera_presence"
DEFAULT_DISABLE_CAMERA_PRESENCE: Final = False
```

**Config flow surfaces:**

- Initial flow (`config_flow.py:~995`, immediately after the `CONF_SCANNER_AREAS` selector for visual grouping):
  ```python
  vol.Optional(CONF_DISABLE_CAMERA_PRESENCE, default=False): selector.BooleanSelector(),
  ```
- Options flow (`config_flow.py:~6530`, same neighborhood):
  ```python
  vol.Optional(
      CONF_DISABLE_CAMERA_PRESENCE,
      default=self._get_current(CONF_DISABLE_CAMERA_PRESENCE, False),
  ): selector.BooleanSelector(),
  ```

**Discovery-time check** in `presence.py:~1118-1146` (the loop that iterates `area_to_zone` and registers cameras). Per the investigation §4.1 design, the check goes at the camera-registration site, NOT inside `register_camera` (so the tracker's internal state never knows about opt-out — keeps the tracker pure):

```python
# v4.7.16: Skip camera registration for rooms with CONF_DISABLE_CAMERA_PRESENCE=True
for area_id, zone_name in area_to_zone.items():
    cameras_in_area = camera_manager.get_cameras_for_area(area_id)
    tracker = self._zone_trackers[zone_name]

    # v4.7.16: which room owns this area_id? Skip if that room opts out.
    owning_room_opts_out = False
    for room_name in tracker.room_names:
        if self._room_area_ids.get(room_name) != area_id:
            continue
        entry = self._room_entry_for(room_name)
        if entry is None:
            continue
        config = {**entry.data, **entry.options}
        if config.get(CONF_DISABLE_CAMERA_PRESENCE, DEFAULT_DISABLE_CAMERA_PRESENCE):
            owning_room_opts_out = True
            break

    if owning_room_opts_out:
        _LOGGER.info(
            "Camera-presence opt-out: skipping %d cameras for zone %s (room area %s)",
            len(cameras_in_area), zone_name, area_id,
        )
        continue

    for camera_info in cameras_in_area:
        ...  # existing registration
```

(The `self._room_entry_for(room_name)` helper either exists or is added in this cycle; build agent confirms.)

**UI strings** in `strings.json` (both initial and options flow blocks):

```json
"disable_camera_presence": "Disable Camera Presence (Opt-Out)"
```

Description:

```json
"disable_camera_presence": "Skip camera-based presence detection for this room. Use for rooms with chronic camera person-classifier false positives (TV reflections, sun-glare hallways). The room's other sensors (mmWave, PIR, BLE) continue to contribute."
```

### Acceptance Criteria — D4

- **Verify:** Room with `CONF_DISABLE_CAMERA_PRESENCE=True` results in zero `tracker.register_camera()` calls for cameras whose `area_id` matches that room.
- **Verify:** Room without the field set (back-compat) behaves identically to today — camera registration proceeds normally. Default value is False; absent key reads as False.
- **Verify:** Toggling the field from False to True via options flow and reloading the entry causes the next `_discover_zone_cameras` cycle to skip those cameras. The room's existing camera subscriptions are released on entry reload.
- **Verify:** Toggling False → True → False (mid-flight) leaves no orphan subscriptions and re-registers cleanly.
- **Verify:** D4 does not affect Tier 1 (mmWave) or Tier 3 (BLE) signals for the room. Only camera registration is skipped.
- **Verify:** The signal inventory sensor (D2) `has_camera` attribute reflects opt-out: returns False for opted-out rooms even when cameras exist in the area.
- **Test:** `test_disable_camera_presence_skips_register_camera`
- **Test:** `test_disable_camera_presence_default_false_preserves_behavior`
- **Test:** `test_disable_camera_presence_toggle_at_reload`
- **Test:** `test_disable_camera_presence_does_not_affect_mmwave_or_ble`
- **Test:** `test_signal_inventory_has_camera_false_when_opted_out`
- **Live:** Operator opts out `master_hallway`, `upstairs_hall`, and one TV-room (e.g., `family_room`) — verifies zero camera-driven ghost-flips overnight while all phones away.
- **Live:** `sensor.ura_room_master_hallway_signal_inventory.has_camera` reads `false` post-opt-out.

---

## 3. Out of scope (explicit deferrals — required by Plan Completion Tracking)

The following are intentionally NOT in v4.7.16:

| Item | Reason | Where it lands |
|---|---|---|
| WAKING-state gate / sleep-state veto | Owned by v4.7.15 + future v4.7.x | v4.7.15 (helper) + cycle TBD |
| House-level veto gates | Owned by v4.7.14 / v4.7.15 | v4.7.14 + v4.7.15 |
| Modifying `_build_scanner_room_map` | Load-bearing; consumed only | Permanent — read-only contract |
| Per-camera opt-out (instead of per-room) | Investigation §9 Q1: per-room recommended; per-camera is post-v5.0 if needed | Backlog |
| Camera-shadow mode (log-only, no signal contribution) | Investigation §9 Q4 open question | Backlog (would gate Part B audit cycle) |
| Per-room `CONF_SCANNER_AREAS` weight override | Out — `BLE_TIER_2_WEIGHT` is the global knob; per-room override defers to v4.7.16.x if user audit demands it | Conditional backlog |
| Bermuda-scanner enumeration sensor (`untagged_scanners_count`) | Investigation §6.5; would expose misconfiguration. Useful but standalone | v4.7.16.x or v4.7.17 |
| Part B durability audit (Frigate vs Protect 7-day) | Investigation §4.1 Part B; needs its own cycle | v4.7.17 candidate |
| Deprecating `sensor.ura_house_state_confidence` (`sensor.py:3659`) | Investigation §6.5 cleanup; deferred until automation/dashboard audit confirms zero readers | v5.0 cleanup |

---

## 4. Backward compatibility

- Rooms with no `CONF_SCANNER_AREAS` configured continue to be classified as Tier 1 if they have `CONF_AREA_ID`, Tier 0 if they don't. Identical to today.
- Rooms with no `CONF_DISABLE_CAMERA_PRESENCE` field set continue to receive camera registration. Identical to today.
- `_build_scanner_room_map` output is unchanged; only new consumer (`get_ble_tier`) is added.
- `_derived_mode` falls back to its pre-v4.7.16 path if the v4.7.15 helper is unavailable.
- Pre-v4.7.16 config entries reload without migration. No `__VERSION__` bump in config entry data. Lazy derivation per Bug Class #46 doctrine.
- Existing `sensor.ura_house_state_confidence` (`sensor.py:3659`) untouched in this cycle.

---

## 5. Bug class watchlist

Reviewers must check this cycle against the following classes from `docs/QUALITY_CONTEXT.md`:

| Class | Why it applies | What to check |
|---|---|---|
| **#20** — Concurrent Config Entry Reload Race (`QUALITY_CONTEXT.md:792`) | D4 toggles a config field that triggers reload; D2 sensor reads from a coordinator whose data may be mid-rebuild | Verify `_build_scanner_room_map` cache invalidation is safe under simultaneous reload; D2 sensor must defend against `coordinator.data` transient empty state |
| **#44** — Cross-File `sys.modules` Pollution in Test Harness (`QUALITY_CONTEXT.md:1678`) | New tests touch `const.py`, `presence.py`, `sensor.py`, `config_flow.py` | Tests must use the existing fixture-isolation pattern; new fixtures must extract schema from production source, never hand-copy. Per Tier 2-DB rule. |
| **#46** — Lazy Derivation, No Migration (per v4.7.4.4 doctrine) | D1's `get_ble_tier` derives at read time; D2 sensor derives state at read time | NO migration helper added. Readers default safely when keys absent. |
| **#47** — Lazy Canonical Resolution UI Surface (`QUALITY_CONTEXT.md:1791`) | D2 sensor exposes the `ble_tier` classification — operator-facing UI surface that derives from canonical config | Sensor state must be human-readable (Bug Class #47 requires the rolled-up label as state, numeric tier in attributes only). Verify no automation in the cookbook references `state == "1"`. |

(Bug Class #48 is the subject of v4.7.15 — this cycle is the consumer of its veto-helper output, not the introducer.)

---

## 6. Tier 2-DB review framing (three parallel reviewers)

Per CLAUDE.md Tier 2-DB protocol, three parallel reviewers with **explicitly distinct framings**:

### Reviewer A — Correctness of per-room weight application + boundary cases

Focus questions:
- For a Tier 0 zone (no BLE anywhere), what determines occupancy? Is the fallback to mmWave/PIR + camera signal aggregation correct and equivalent to pre-v4.7.16 behavior?
- For a Tier 2 room with mmWave but no camera, does the weight aggregation correctly produce `accept_occupied` on mmWave + BLE confirmation?
- For a mixed-tier zone, is the weight summation rule (1.0 + 0.6 = 1.6 → accept) sound, or should the aggregation be `max(weights)` instead of `sum`? Reviewer A must explicitly defend the chosen aggregation.
- Edge case: `BLE_TIER_2_WEIGHT=0.0` should be functionally identical to Tier 0 — does the code path verify this?
- Edge case: a room transitions from Tier 1 to Tier 2 (operator adds `scanner_areas`) — is there any window where the in-flight `_derived_mode` evaluation sees stale tier and applies the wrong weight?
- Per `feedback_no_fabrication.md`: every weight threshold and helper-return contract must be cited from v4.7.15 source (when shipped) or flagged as forward-reference assumption.

### Reviewer B — `_derived_mode` refactor risk + helper integration + signal chain integrity

Focus questions:
- `_derived_mode` runs every coordinator cycle. The new code adds a `for room in self.room_names` loop + a `get_ble_tier` call per room + a helper invocation. What's the per-cycle wall-clock overhead on a 30-room install? Is the perf-regression test sufficient?
- The v4.7.15 helper is a forward reference. Reviewer B must verify the integration point's contract is sound: signature `helper(signals: list, inputs: VetoInputs) -> VetoVerdict` must be re-confirmed once v4.7.15 lands. Flag any assumption-induced risk.
- Race condition: `person_coordinator._build_scanner_room_map` is rebuilt on entry-set change; `_derived_mode` reads `_direct_ble_rooms` mid-rebuild. Is the rebuild atomic with respect to readers?
- Listener cleanup: D4's opt-out is checked at discovery time; if the opt-out toggles mid-flight (config reload), are existing camera subscriptions on the affected room cleanly released?
- Signal chain: does D3's verdict propagate to `infer()` correctly? The v4.7.14 contract added `all_tracked_persons_away` to the signature; v4.7.16's per-room weight feeds into the helper, whose verdict feeds back into `_derived_mode` (not `infer` directly). Verify the flow is end-to-end correct without double-veto or missed-veto.
- HA lifecycle: D2 sensor must respect `async_will_remove_from_hass` properly (per `AutomationHealthSensor` pattern). No leaked listeners.

### Reviewer C — Test fixture authority + new-sensor metadata correctness + opt-out UX + parallel-merge safety

Focus questions:
- New tests must extract schema from `const.py` / `config_flow.py` / `sensor.py` production source. Reviewer C verifies no hand-copied DDL or hand-copied entity attributes in fixtures. Per Tier 2-DB Reviewer C framing from CLAUDE.md.
- D2 sensor's `device_info`, `unique_id`, `entity_category`, `icon`, and `friendly_name` must align with the rest of URA's per-room diagnostic sensors. Reviewer C runs the entity through HA's `RestoreEntity` lifecycle and the registry round-trip.
- D4's new config field UX: does it appear immediately after `CONF_SCANNER_AREAS` in both initial and options flows (visual grouping)? Does the description text honor the `strings.json:123` vocabulary ("sparse scanner home", etc.)?
- Parallel-merge safety with v4.7.14.1 and v4.7.15:
  - v4.7.14.1 touches `presence.py:_run_inference` / `infer()`. v4.7.16 D3 touches `_derived_mode` (same file, different function). Check for merge-conflict surface.
  - v4.7.15 introduces the helper module. v4.7.16 imports it. Check for import-order and circular-import risk.
- README + operator runbook: are the pre/post diagnostic probes specified concretely enough that the live-validation step can mechanically execute them?

**The three reviews run in PARALLEL.** Findings consolidated post-review; CRITICAL/HIGH fixed before deploy. Per Tier 2-DB rule, a focused 4th pass spot-check is warranted if fix-up is substantial.

**Pre-deploy snapshot of affected row rates:** N/A — this cycle adds no new DB writes. The `anomaly_log` and `room_visits` tables are untouched. Pre-deploy snapshot requirement is the diagnostic-sensor state distribution: count of rooms by `ble_tier` value (1, 2, 0). Post-deploy: same distribution should match expectation (no rooms misclassified due to schema drift).

**Live Validation (Review D):** Post-restart, verify:
- D1: `state_attr('sensor.ura_room_<slug>_signal_inventory', 'ble_tier')` returns int for every room.
- D2: every room config entry has exactly one `signal_inventory` sensor in the entity registry.
- D3: with all phones away, no Tier-2-only zone flips OCCUPIED on camera-only firing within 60 minutes.
- D4: opted-out rooms show `has_camera=false` and have zero camera-state-change subscriptions in `_unsub_listeners`.

---

## 7. README requirements

`docs/readmes/README_v4.7.16.md` MUST include:

### 7.1 Operator runbook — setting up scanner_areas for sparse rooms

Step-by-step with concrete example:

> **Example:** Living room has no BLE scanner, but the adjacent Family Room has a Shelly Plus BLE proxy.
> 1. Settings → Devices & Services → URA → Living Room → Configure
> 2. Find "BLE Scanner Areas (Optional)" — select `Family Room`
> 3. Save. URA reloads the Living Room entry.
> 4. Probe: `state_attr('sensor.ura_room_living_room_signal_inventory', 'ble_tier')` should return `2` within 30 s.

### 7.2 Rollback procedure

> **To reset a room to Tier 1 (or Tier 0):**
> 1. URA → <Room> → Configure → BLE Scanner Areas → clear all selections → Save
> 2. URA reloads. `ble_tier` reverts to 1 (if `area_id` is set) or 0 (if not).
> 3. No data migration; no DB changes; safe to repeat.

### 7.3 Per-room diagnostic sensor probes — pre/post deploy

Pre-deploy snapshot (run via `ha-mcp`):

```
get_states_filtered(domain='sensor', entity_id_pattern='ura_room_*_signal_inventory')
→ expected: zero entities (pre-deploy)
```

Post-deploy:

```
get_states_filtered(domain='sensor', entity_id_pattern='ura_room_*_signal_inventory')
→ expected: one entity per room config entry; ble_tier distribution matches operator's house topology
```

### 7.4 Camera opt-out probe

> For each room the operator opts out via `CONF_DISABLE_CAMERA_PRESENCE`:
> ```
> state_attr('sensor.ura_room_<slug>_signal_inventory', 'has_camera')
> → expected: false (post-opt-out)
> ```

### 7.5 Master link doc reference

> See `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` for the full Bug Class #48 sprint context (introduced by v4.7.15). This cycle is the per-room weighting consumer of that sprint's veto helper.

---

## 8. Recall + memory hooks

- "Resume v4.7.16 room-level veto"
- "Plan BLE tier exposure"
- "Per-room camera opt-out"

Memory entry to write after live-validation closes:

```
project_v4_7_16_live.md — v4.7.16 SHIPPED. CONF_SCANNER_AREAS now drives per-room
BLE tier (1/2/0) exposed via sensor.ura_room_<slug>_signal_inventory. Veto helper
weights Tier 2 at BLE_TIER_2_WEIGHT=0.6 (tunable constant). New per-room opt-out
CONF_DISABLE_CAMERA_PRESENCE skips camera registration. Tier 2-DB (3 reviewers
framed A/B/C). Bug Class watchlist: #20 #44 #46 #47.
```

---

## 9. References

- `custom_components/universal_room_automation/const.py:316-317` (CONF_SCANNER_AREAS origin)
- `custom_components/universal_room_automation/config_flow.py:993-997, 6524-6530` (per-room field surfaces)
- `custom_components/universal_room_automation/person_coordinator.py:10-13, 80-90, 448-549, 1149-1161` (Tier 1/2/3 header comment + `_direct_ble_rooms` cache + `_build_scanner_room_map` + `is_direct_ble_room` accessor)
- `custom_components/universal_room_automation/domain_coordinators/presence.py:85-200, 290-300, 1100-1160` (`ZonePresenceTracker._derived_mode` + `register_camera` + camera discovery loop)
- `custom_components/universal_room_automation/strings.json:107-130, 1300-1325` (per-room scanner_areas UI text)
- `custom_components/universal_room_automation/sensor.py:1855-1955` (`AutomationHealthSensor` — diagnostic sensor exemplar)
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` (Part A opt-out design + §6.5 Bermuda enumeration rule)
- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` (predecessor veto plumbing)
- `docs/readmes/README_v3.8.9.md` (origin of `_direct_ble_rooms`)
- `docs/readmes/README_v4.5.4.md` (last room-config cleanup cycle referencing v3.2.4)
- `docs/QUALITY_CONTEXT.md:792, 1678, 1791` (Bug Classes #20, #44, #47)
- `docs/planning/PLANNING_v4.7.15_universalize_bug_class_48_veto.md` (FORWARD REFERENCE — not present at planning time; must exist before v4.7.16 build starts)
- `docs/planning/PLANNING_BUG_CLASS_48_SPRINT_LINK.md` (FORWARD REFERENCE — not present at planning time; created by v4.7.15)
