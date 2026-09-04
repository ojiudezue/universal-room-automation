# PLANNING — Device / Entity Architecture Cleanup for HA 2026.9

**Card:** `DEVICE-ENTITY-ARCH-2026-9-1`
**Date:** 2026-09-03 (Rev 2 — post plan-review FIX-REQUIRED)
**Author:** ura-planner
**Precursor ship:** `v5.92.3` — stripped 109 `via_device=` declarations to
unblock the HA 2026.9 `DeviceInfo.via_device` breaking change.

**Tier:** **2** (two framing-disjoint build-reviews + ura-validator +
live-validation) with one elevated hard gate on D1 (coordinator
device-de-fragmentation). Operator has authorized build-to-completion at
Tier 2; do NOT re-elevate.

## Rev-2 revision summary (addresses plan-review FIX-REQUIRED)

- **C1 (make-or-break):** migration set expanded from `~sensor.py:173+`
  to the full **AST-verified 14 class sites → 17 D0 entities**
  (accounting for ×4 tracked persons at `aggregation.py:294/296`).
  **10 of the 17 are hosted inside `async_setup_aggregation_sensors`
  (`aggregation.py:204`, hard-return at :210) and
  `async_setup_aggregation_binary_sensors` (`aggregation.py:314`, hard-return
  at :320)**, both of which refuse anything but `ENTRY_TYPE_INTEGRATION`.
  Branch-move idiom does NOT apply here. D1 now specifies an explicit
  CM-side setup path — **split** two new coroutines out of those
  functions and call them from the CM entry's platform setup. Named
  below (`async_setup_cm_hosted_aggregation_sensors` /
  `async_setup_cm_hosted_aggregation_binary_sensors`).
- **C3:** `ReconcileHealthSensor` (`sensor.py:175`, canonical DeviceInfo
  at `sensor.py:7427`) and `IntegrationHouseStateSensor` (`sensor.py:6215`)
  resolve to `(DOMAIN, "integration")` = Whole House — **REMOVED from
  the migration set**; explicit "STAYS ON INTEGRATION" lines added.
  Moving them would create the exact split defect on the one clean
  device.
- **C2:** The per-person CM sensors read `CONF_TRACKED_PERSONS` from
  the integration entry's `entry.data` and `hass.data[DOMAIN]["person_coordinator"]`
  (`aggregation.py:264, 272`). CM-side setup MUST resolve those from
  the integration entry, not `self.entry` — spec below.
  Setup-order dependency (`person_coordinator` present) inherited via
  a defer-guard identical to the integration path's ternary. Runtime
  is clean: none of the migrated classes read `self.entry` at runtime.
- **C4:** Identifier strings corrected everywhere in this doc:
  `optimization_coordinator` (verified `select.py:459`), `notification_manager`
  (bare, verified `binary_sensor.py:2394`), `zone_manager` (verified
  `__init__.py:909, 4035`). Dynamic identifiers (`room` per-entry-id,
  `zone_<n>`) enumerated at D-NEST runtime from the registry, not
  hard-coded.
- **C5 (D2 scope-down):** The full "one helper per identity" refactor
  (~100+ inline sites — hvac 38, CM 23, energy 22, presence 21, NM 11)
  is **NOT** the cause of the split defect and is 10× the estimate.
  **PARKED** as a separate hygiene card. D2 scopes to ONLY the
  duplicate-authoring that risks real divergence:
  - `music_following` — three co-existing DeviceInfo authors (helper +
    `switch.py:5708` inline + `CoordinatorEnabledSwitch` inline).
  - `notification_manager` — three sites (mixin, module-level,
    coordinator).
  - The `base.py` first-writer-wins model race (D3, unchanged).
  INV-2 rescoped to these two identities. The rest becomes card
  `DEVICE-INFO-HELPER-CONSOLIDATION-1` (parked; revive trigger: after
  D1/D2/D3 land and next hygiene cycle).
- **C6 (D0 acceptance):** D0's authoritative check is
  **ENTITY-LEVEL SOURCE ENUMERATION** — the probe's INTEGRATION-branch
  coordinator-device entity set must equal an AST-derived source
  enumeration (the 17 entities below), NOT the operator's eyeballed
  panel counts (80/10/1/6). Panel counts are a sanity note (they hide
  disabled-by-default entities like `ExteriorOpenTracksDiagnosticSensor`
  at `sensor.py:167`).
- **C7 (unique_id migration):** `_migrate_entity_unique_id` is
  **CONTINGENT** — if D0 shows every migration-target has an
  entry-independent unique_id (expected — all 17 candidates read
  fixed slugs, not `entry.entry_id`), the hook is NOT needed. If ever
  needed, wire it in the **platform** `async_setup_entry` before
  `async_add_entities` (mirroring `_migrate_excess_solar_entity_id`
  called at `switch.py:201`), NOT in `__init__.py`. Contradiction with
  the orchestrator-gate paragraph resolved.

## LEAD DEFECT — coordinator devices are split-owned across two config entries

Observed live 2026-09-03: parent **"Universal Room Automation"** entry
(`ENTRY_TYPE_INTEGRATION`) hosts `Whole House` (80 ent — CORRECT), plus
fragments of `Coordinator Manager` (10 ent — WRONG), `Music Following
Coordinator` (1 — WRONG), `Security Coordinator` (6 — WRONG). The
**"URA: Coordinator Manager"** entry hosts the same identities in bulk:
CM 50, Security 15, MF 9. Both entries register entities against the
SAME `DeviceInfo.identifiers` → HA merges the device but retains
entities under two different `config_entry_id`s. **Deleting either
entry orphans half of every affected device.** A dead greyed
`URA: Music Following` device (candidate `(DOMAIN, "music_following")`
bare — D0 confirms) also appears in both entries.

### Root cause (verified in source)

Both entries forward the same platforms:
- `__init__.py:329-350` — `INTEGRATION_PLATFORMS = [SENSOR, BINARY_SENSOR,
  SELECT, SWITCH, BUTTON, TIME]`.
- `__init__.py:3923` — INTEGRATION forwards `INTEGRATION_PLATFORMS`.
- `__init__.py:4160-4161` — CM forwards `INTEGRATION_PLATFORMS + [NUMBER]`.

Every platform's `async_setup_entry` branches on `CONF_ENTRY_TYPE`. On
the `ENTRY_TYPE_INTEGRATION` branch — **directly at `sensor.py:161-175`
and indirectly via `aggregation.py:204/314`** — 14 concrete classes
register entities whose `DeviceInfo.identifiers` point at COORDINATOR
devices, not `(DOMAIN, "integration")`. The `ENTRY_TYPE_COORDINATOR_MANAGER`
branch (`sensor.py:188+`, `switch.py:198+`) then registers the full
coordinator entity set against the CM entry. Merged device; split entity
ownership.

### The fix (two idioms — D1)

- **Idiom A — branch-move.** For entities registered directly in a
  platform's `async_setup_entry` INTEGRATION branch (4 entities in
  `sensor.py:161-175` — see migration set), move to the platform's
  `ENTRY_TYPE_COORDINATOR_MANAGER` branch.
- **Idiom B — split CM-hosted aggregation coroutines.** For entities
  registered inside `async_setup_aggregation_sensors` /
  `async_setup_aggregation_binary_sensors` (10 entities — 8 per-person
  + house CM sensors, 2 alert binary sensors), those functions
  hard-return on non-INTEGRATION entries and CANNOT branch-move. Split
  new coroutines out and call from the CM setup. See D1.Idiom-B for
  the split spec.

INTEGRATION entry retains ONLY entities whose DeviceInfo resolves to
`(DOMAIN, "integration")` — including `IntegrationHouseStateSensor`
(`sensor.py:6215`) and `ReconcileHealthSensor` (`sensor.py:7427`) —
STAYS.

### Why unique_id preservation is the hard gate

Reference `frigate1_retired_2suffix_permanent`. If a moved entity's
`unique_id` is stable across the entry swap, HA's
`entity_registry.async_get_or_create` matches `(platform, domain,
unique_id)` and re-homes the row in place (new `config_entry_id`,
same `entity_id`, history preserved). If unique_id shifts (even by
prefix), a NEW row is minted with `_2` suffix — irreversible. D0
audits per-entity unique_id stability BEFORE D1 build.

---

## The AST-verified migration set (17 entities from 14 class sites)

| # | Site | Class | Persons | Target device identity | Idiom |
|---|---|---|---|---|---|
| 1 | `sensor.py:161` | `ExteriorPersonTracksActiveSensor` | 1 | `security_coordinator` | A |
| 2 | `sensor.py:162` | `ExteriorVehicleTracksActiveSensor` | 1 | `security_coordinator` | A |
| 3 | `sensor.py:163` | `ExteriorAnimalTracksActiveSensor` | 1 | `security_coordinator` | A |
| 4 | `sensor.py:164` | `ExteriorUnidentifiedPersonsSensor` | 1 | `security_coordinator` | A |
| 5 | `sensor.py:167` | `ExteriorOpenTracksDiagnosticSensor` (disabled-default) | 1 | `security_coordinator` | A |
| 6 | `sensor.py:169` | `PerimeterCirclingZeroDispatch24hSensor` | 1 | `security_coordinator` | A |
| 7 | `sensor.py:173` | `MusicFollowingHealthSensor` | 1 | `music_following_coordinator` | A |
| 8 | `aggregation.py:296` (persons ×N) | `PersonLikelyNextRoomSensor` | 4 (per D0) | `coordinator_manager` | B |
| 9 | `aggregation.py:297` (persons ×N) | `PersonCurrentPathSensor` | 4 (per D0) | `coordinator_manager` | B |
| 10 | `aggregation.py:299` (persons ×N) | `PersonNextRoomAccuracySensor` | 4 (per D0) | `coordinator_manager` | B |
| 11 | `aggregation.py:301` (persons ×N) | `PersonRoutineStatusSensor` | 4 (per D0) | `coordinator_manager` | B |
| 12 | `aggregation.py:307` | `HouseNextRoomAccuracySensor` | 1 | `coordinator_manager` | B |
| 13 | `aggregation.py:308` | `HouseRoutineStatusSensor` | 1 | `coordinator_manager` | B |
| 14 | `aggregation.py:327` | `SafetyAlertBinarySensor` | 1 | `safety_coordinator` | B |
| 15 | `aggregation.py:328` | `SecurityAlertBinarySensor` | 1 | `security_coordinator` | B |

Rows 8-11 expand to 4 entities each in the operator's live house
(`CONF_TRACKED_PERSONS` cardinality) — D0 emits the exact per-person
row set.

**STAYS on INTEGRATION entry (Whole House device, NOT migration
targets):**
- `sensor.py:6215` `IntegrationHouseStateSensor` → `(DOMAIN, "integration")`.
- `sensor.py:7427` (registered `sensor.py:175`) `ReconcileHealthSensor`
  → `(DOMAIN, "integration")`.
- Every entity registered inside `async_setup_aggregation_sensors` /
  `async_setup_aggregation_binary_sensors` that DOES resolve to
  `(DOMAIN, "integration")` (all of `aggregation.py:215-261, 325-326,
  330`) — the CM-split extracts ONLY the coordinator-device rows.
- Every entity in `sensor.py:139-160, 166` and switch/select/number/binary
  INTEGRATION-branch entities whose DeviceInfo is Whole House.

D0 must confirm no ADDITIONAL coordinator-device entities lurk on the
INTEGRATION branches beyond this set. Reviewer A re-enumerates
independently.

---

## SCOPE

**IN:**
- **D0** — live registry probe + AST source enumeration; commit both
  as the D1 fixture.
- **D1** (elevated gate) — de-fragment coordinator device ownership via
  Idiom A (branch-move, 7 entities) + Idiom B (CM-split, 10 entities);
  preserve `entity_id`/`unique_id`; remove the dead
  `URA: Music Following` device.
- **D2** (rescoped) — collapse `music_following` (3 sites) and
  `notification_manager` (3 sites) to ONE canonical `DeviceInfo` author
  each. NO broader helper-consolidation refactor.
- **D3** — fix `domain_coordinators/base.py:~200-208` model
  first-writer-wins race.
- **D-NEST** — restore device-tree nesting via
  `dr.async_update_device(..., via_device_id=...)` POST-setup. Parents
  coordinators under CM under Whole House; zone_manager, zones, rooms
  under Whole House.
- **D4** — naming convention **BAKED as Option 3**. Rooms untouched;
  zero friendly-name churn.
- **D5** — `has_entity_name` per-concrete-entity audit.
- **D6** — reload safety (device-registry writes only, no parent-entry
  reload).

**OUT:**
- `CONFIG-SUBENTRIES-MIGRATION-1` — parked.
- `PLANNING_setup_unload_symmetry.md` — separate card.
- `entity_id` / `unique_id` renames — permanently OUT (D1 preserves
  them; that IS the gate).
- **`DEVICE-INFO-HELPER-CONSOLIDATION-1`** (NEW parked card) — the
  broader "one helper per identity" refactor across hvac/CM/energy/
  presence/NM (~100+ inline sites). Revive trigger: after D1/D2/D3
  land and next hygiene cycle; scope against the tidied post-D2 state.
- `ENTITYDESC-RUNTIMEDATA-HYGIENE-1` — parked.
- Zone→Rooms nesting (`DEVICE-ZONE-ROOM-NEST-1`), Person device
  (`PERSON-DEVICE-1`) — parked.

**Parsimony ledger:** +0 CONF_*; +0 sensors; +0 signals; +1 new module
(`_devices.py`); +1 setup hook (D-NEST stamper); +2 CM-hosted
aggregation coroutines (extracted, not new logic); refactor-only diff
for D2/D3 scoped to 6 sites.

---

## Institutional context verified

### Greps run + results

| Question | Command / Site | Result |
|---|---|---|
| Both entries forward the same platforms? | `__init__.py:329-350, 3923, 4160-4161` | YES. INTEGRATION_PLATFORMS is a shared list; CM adds NUMBER. |
| Coordinator-device entities on the INTEGRATION-branch of platform setups? | Read `sensor.py:127-179`, `switch.py:153-196`, `binary_sensor.py`, `select.py`, `button.py`, `time.py` async_setup_entry; read `aggregation.py:204-334`. | 14 class sites, 17 entities (table above). |
| aggregation.py hard-return on non-INTEGRATION | `aggregation.py:210, 320` | Confirmed — Idiom B required. |
| CM-side `CONF_TRACKED_PERSONS` availability | `config_flow.py` + `__init__.py` CM setup path | CM entry does NOT carry `CONF_TRACKED_PERSONS` in its `entry.data`; only the INTEGRATION entry does. CM-side setup MUST look up the INTEGRATION entry via `hass.config_entries` and read `entry.data.get(CONF_TRACKED_PERSONS, [])` from it. Same for `hass.data[DOMAIN]["person_coordinator"]` (already keyed to the singleton, not per-entry). |
| Identifier strings — correct spellings | `grep 'identifiers={(DOMAIN, "'` | `optimization_coordinator` (select.py:459) — NOT `optimizer_coordinator`. `notification_manager` (binary_sensor.py:2394) — bare, NOT `notification_manager_coordinator`. `zone_manager` (__init__.py:909, 4035). |
| Rev-1 draft used `optimizer_coordinator` / `<coord>_coordinator` for NM? | Rev-1 text | YES — corrected everywhere in Rev-2. |
| Dead-device identifier | D0 probe confirms; suspected `(DOMAIN, "music_following")` bare | D0 CSV emits authoritative value. |
| Migration-target unique_id stability (spot check) | Read `MusicFollowingHealthSensor.__init__`, `PersonLikelyNextRoomSensor.__init__`, exterior sensors' `__init__` at build time. | Builder verifies + D0 audits all 17. Expected SAFE (fixed slugs, no `entry.entry_id` embed). If any BLOCKED → contingent `_migrate_entity_unique_id` per C7. |
| `_*_device_info()` helpers | 10 helpers (sensor.py, button.py, number.py mixin) | D2 does NOT touch 8 of them; only the 2 duplicate-authoring identities (music_following, notification_manager) collapse. |
| `DeviceInfo(` call sites | ~143 across 12 files | D2 rescope means most are UNTOUCHED. |
| HA entity-registry re-home contract | builder cites `homeassistant/helpers/entity_registry.py` `async_get_or_create` before writing D1 | Not asserted from memory. |
| HA `async_update_device(via_device_id=...)` support | builder cites `homeassistant/helpers/device_registry.py` before writing D-NEST | Not asserted from memory. |

### For each proposed addition — REUSED vs NEW

- **D0 registry probe** — REUSED pattern (`feedback_measure_before_build`);
  read-only over `.storage/core.entity_registry` + `core.device_registry`.
- **D1 Idiom A branch-move** — REUSED (existing branches).
- **D1 Idiom B CM-hosted aggregation coroutines** — NEW extraction from
  `async_setup_aggregation_sensors` / `_binary_sensors`. Same
  construction args; only the branching container is new.
- **D1 CM setup wiring** — REUSED (`sensor.py:188+` and
  `binary_sensor.py` CM branches already exist; two new function calls
  added).
- **D2** — REUSED (helpers exist); scoped refactor to 6 sites.
- **D3** — REUSED (route through helper).
- **D-NEST** — NEW code, REUSED precedent (`entity.py:69-98`
  post-creation `dr.async_update_device(..., area_id=...)`).
- **D4 constants** — NEW block in `_devices.py`; Option 3 baked.
- **D6** — REUSED census-toggles sibling-`last_changed` test technique.

### Prior planning docs consulted

- `PLANNING_census_toggles_to_device_switches.md` — reload-suppression
  precedent.
- `PLANNING_setup_unload_symmetry.md` — non-goal.

### Memory bodies pulled

- `reference_frigate1_retired_2suffix_permanent` — the footgun D1
  gates against.
- `feedback_parent_entry_reload_watchdog_hazard` — D6 invariant.
- `feedback_suppression_needs_discharge` — governs D6.
- `feedback_measure_before_build` — governs D0.
- `feedback_no_fabrication` — builder cites HA sources for registry
  APIs.
- `feedback_read_consumers_before_asserting_function` — every migrated
  class's `__init__` and DeviceInfo helper enumerated at build.
- `feedback_hollow_test_anchors` — D1 tests exercise REAL registry
  re-home; D5 tests drill by construction, not source grep.
- `feedback_coincidental_equality_masks_concept_split` —
  `music_following` (bare, tombstone) vs `music_following_coordinator`
  are distinct identities.

### Design docs read

- `docs/QUALITY_CONTEXT.md` — bug classes #7 (stale data — the model
  race), #22 (enum mismatch — same class), #46 (unique_id churn on
  refactor — D1 gates against this).

---

## Falsifiable invariants

**INV-0 (D0 measurement):** The probe's URA-owned entity table covers
every URA entity in the live registry (~4626). The subset with
`config_entry_id == INTEGRATION_ENTRY_ID` AND
`device_identifier ∈ {coordinator identity set}` equals the
17-entity source enumeration above (accounting for per-person
expansion of rows 8-11).

**INV-1 (D1 preservation — elevated gate):**
- Total URA entity count unchanged (pre == post).
- ZERO new `_2` mints attributable to the migration (grep post CSV;
  subtract D0-baseline `_2` rows).
- ZERO URA entities `unavailable` at T+60s beyond the D0-baseline
  unavailable set.
- Each coordinator device (`safety_coordinator`, `security_coordinator`,
  `presence_coordinator`, `energy_coordinator`, `hvac_coordinator`,
  `optimization_coordinator`, `music_following_coordinator`,
  `notification_manager`, `coordinator_manager`) has EXACTLY ONE
  owning `config_entry_id` set, and that entry is CM.
- INTEGRATION entry owns entities whose device identity is
  `(DOMAIN, "integration")` ONLY. Explicit STAYS list
  (`IntegrationHouseStateSensor`, `ReconcileHealthSensor`, all
  aggregation Whole-House entities) verified present under INTEGRATION.
- Dead device `(DOMAIN, "music_following")` (D0-confirmed) absent
  from device registry.

**INV-2 (D2 scoped SSOT):** For EACH of the two identities
`music_following_coordinator` and `notification_manager`, AST scan
returns EXACTLY ONE `DeviceInfo(identifiers={(DOMAIN, "<id>")}, ...)`
constructor in the URA package (all consumers route through the shared
helper). Other identities are OUT OF SCOPE for INV-2 in this cycle.

**INV-3 (D3 no-race model):** For each `{coord}_coordinator` and
`coordinator_manager`, `domain_coordinators/base.py:device_info`
returns a DeviceInfo whose `(name, model)` equals the shared helper's
`(name, model)`.

**INV-4 (D-NEST):** For every URA-owned DeviceEntry other than
`(DOMAIN, "integration")`, `device.via_device_id` resolves via
`dr.async_get` to the id of the parent device per the map (below).
Discriminator: count of URA devices with unresolved parents == 0. The
parent map covers ALL live URA identifiers, static AND dynamic — a
probe keyed on wrong strings passes vacuously; Reviewer B independently
re-enumerates.

**INV-5 (D5):** Zero `"Error adding entity None"` log lines
attributable to URA post-boot.

**INV-6 (D6):** Neither D1 nor D-NEST triggers `_async_update_listener`
or `async_reload` on any config entry at runtime (the deploy-restart
itself is exempt).

---

## Deliverables

### D0 — Live registry probe + AST source enumeration

**Method.** Read-only one-shot over live
`.storage/core.entity_registry` + `core.device_registry` at the mounted
homeassistant config path. Emit
`docs/planning/AUDIT_device_entity_split_ownership_2026_09_03.md` +
`.csv` with:

1. **Split-ownership table** — every URA-owned device with entity
   counts per `config_entry_id`.
2. **Migration set (authoritative)** — per entity: `entity_id`,
   `unique_id`, `platform`, current `config_entry_id`, target
   `config_entry_id` (= CM entry_id), `device_identifier`, class name.
   Loaded directly as the D1 test fixture.
3. **AST source enumeration** — independently, walk the URA package
   AST for every `async_add_entities([...])` call inside an
   `if entry_type == ENTRY_TYPE_INTEGRATION:` block (directly or via
   `async_setup_aggregation_*` invocation), resolve each class's
   canonical `_attr_device_info` identifier, and emit the set of
   coordinator-device class sites. **INV-0 discriminator: probe set
   == AST source enumeration set (per class + per-person expansion).**
   NOT compared against operator-eyeballed panel counts (those hide
   disabled-default entities like `ExteriorOpenTracksDiagnosticSensor`
   at `sensor.py:167`).
4. **Baseline totals** — total URA entity count; entities already
   `unavailable` at probe time (excluded from D1 AC); identifier of
   the dead `URA: Music Following` device (candidate
   `(DOMAIN, "music_following")` bare).
5. **Unique_id stability audit** — per migration-target: is unique_id
   independent of the INTEGRATION `entry_id`? Mark SAFE or BLOCKED.
   Any BLOCKED row triggers a plan revision (adds C7 contingent
   `_migrate_entity_unique_id` per that platform's setup) BEFORE D1
   build dispatch.

### Acceptance Criteria — D0

- **Verify:** Audit doc + CSV committed under `docs/planning/`.
- **Verify:** INV-0 discriminator passes — probe set matches AST
  source enumeration; operator's panel counts (80/10/1/6 under
  INTEGRATION; 50/15/9 under CM) noted as SANITY, not authority.
- **Verify:** Unique_id stability audit column marks every migration
  target SAFE. Any BLOCKED row halts build dispatch pending plan
  revision.
- **Live:** Probe is one-shot read-only.

### D1 — De-fragment coordinator device ownership (ELEVATED HARD GATE)

#### D1.Idiom-A — Branch-move (7 entities)

For each row 1-7 in the migration set, relocate the entity from the
`sensor.py:139-179` `ENTRY_TYPE_INTEGRATION` branch to the
`sensor.py:188+` `ENTRY_TYPE_COORDINATOR_MANAGER` branch. Preserve
construction args (`hass, entry`); the entity is now constructed with
the CM entry — verify each class's `__init__` does not persist
`entry.entry_id` into `unique_id` (D0 SAFE column).

**STAYS on INTEGRATION branch** (removed from any relocation list):
`IntegrationHouseStateSensor` (`sensor.py:6215`, added at
`sensor.py:~171`) and `ReconcileHealthSensor` (`sensor.py:7427`, added
at `sensor.py:175`).

#### D1.Idiom-B — CM-hosted aggregation coroutine split (10 entities)

`async_setup_aggregation_sensors` (`aggregation.py:204`) and
`async_setup_aggregation_binary_sensors` (`aggregation.py:314`) both
hard-return on non-INTEGRATION (:210, :320). Extract the
coordinator-device entities into two NEW coroutines in `aggregation.py`:

```python
async def async_setup_cm_hosted_aggregation_sensors(
    hass, cm_entry, async_add_entities
) -> None:
    """CM-side setup for coordinator-device sensors previously
    registered under the INTEGRATION entry's aggregation setup.
    Reads CONF_TRACKED_PERSONS + person_coordinator from the
    INTEGRATION entry / hass.data — see C2 resolution below."""
    if cm_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
        return
    integration_entry = _resolve_integration_entry(hass)
    if integration_entry is None:
        _LOGGER.warning(
            "CM aggregation setup: INTEGRATION entry not found; "
            "coordinator-device aggregation sensors not registered this boot."
        )
        return
    entities: list[SensorEntity] = []
    person_coordinator = hass.data[DOMAIN].get("person_coordinator")
    if person_coordinator:
        tracked_persons = integration_entry.data.get(CONF_TRACKED_PERSONS, [])
        for person_entity_id in tracked_persons:
            person_id = person_entity_id.split('.')[-1]
            entities.extend([
                PersonLikelyNextRoomSensor(hass, integration_entry, person_id),
                PersonCurrentPathSensor(hass, integration_entry, person_id),
                PersonNextRoomAccuracySensor(hass, integration_entry, person_id),
                PersonRoutineStatusSensor(hass, integration_entry, person_id),
            ])
    entities.append(HouseNextRoomAccuracySensor(hass, integration_entry))
    entities.append(HouseRoutineStatusSensor(hass, integration_entry))
    async_add_entities(entities)


async def async_setup_cm_hosted_aggregation_binary_sensors(
    hass, cm_entry, async_add_entities
) -> None:
    if cm_entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_COORDINATOR_MANAGER:
        return
    integration_entry = _resolve_integration_entry(hass)
    if integration_entry is None:
        _LOGGER.warning("CM aggregation-binary setup: INTEGRATION entry not found.")
        return
    async_add_entities([
        SafetyAlertBinarySensor(hass, integration_entry),
        SecurityAlertBinarySensor(hass, integration_entry),
    ])
```

**C2 resolution — reading INTEGRATION-entry data from CM setup:**

- `_resolve_integration_entry(hass)` helper — iterate
  `hass.config_entries.async_entries(DOMAIN)`; return the entry whose
  `entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION`; else
  `None`.
- Entities are constructed with `integration_entry` (NOT `cm_entry`)
  because their `__init__` reads `entry.data` for `CONF_TRACKED_PERSONS`
  and other integration-scoped keys; runtime is safe (verified — none
  of the migrated classes read `self.entry` at runtime, only
  construction-time to derive `unique_id` and person context).
- The `config_entry_id` under which each entity is REGISTERED is
  determined by which `async_add_entities` callback is invoked
  (the CM entry's), NOT by which entry object is passed to `__init__`.
  This is the crux: CM-owned entities can hold a reference to the
  INTEGRATION entry for data reads, while being registry-owned by CM.

**Setup-order dependency (person_coordinator).** The integration path
guarded on `person_coordinator` presence via truthy check
(`aggregation.py:271`); the CM path inherits the same guard. If
person_coordinator is absent at CM setup time, per-person sensors are
skipped this boot; the House-level sensors register unconditionally.
Reviewer B verifies CM setup ordering guarantees person_coordinator is
populated before this coroutine runs (`__init__.py:4091-4161` — CM
setup flow); if not, either defer via `async_at_started` OR document
the boot ordering that guarantees it. Builder to confirm at build.

**CM entry wiring** (in `sensor.py` / `binary_sensor.py`'s
`async_setup_entry` CM branch):

```python
if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:
    # ... existing CM sensors ...
    from .aggregation import async_setup_cm_hosted_aggregation_sensors
    await async_setup_cm_hosted_aggregation_sensors(hass, entry, async_add_entities)
```

Same shape in `binary_sensor.py` for
`async_setup_cm_hosted_aggregation_binary_sensors`.

The extracted entities are DELETED from the original
`async_setup_aggregation_sensors` / `_binary_sensors` bodies
(`aggregation.py:289-308, 327-328` in the current source).

#### D1 — Dead device removal

In CM `async_setup_entry`, after platform forwards complete and D-NEST
runs, guard-check the dead device identifier (D0-confirmed — expected
`(DOMAIN, "music_following")` bare). If it exists AND has zero
entities pointing at it (verified via `entity_registry.async_entries_for_device`),
call `dr.async_remove_device(device_id)`. Skip otherwise (safety —
never orphan entities).

#### D1 — Unique_id migration (CONTINGENT per C7)

If D0 marks ANY migration-target BLOCKED (unique_id embeds
INTEGRATION `entry_id`), the build adds `_migrate_<platform>_entity_unique_ids`
called from **that platform's** `async_setup_entry` CM branch, BEFORE
`async_add_entities([...])`. Precedent: `_migrate_excess_solar_entity_id`
called at `switch.py:201`. NOT wired in `__init__.py`. Expected: not
needed — D0 shows all 17 SAFE.

### Acceptance Criteria — D1 (ELEVATED)

- **Test:** `test_migration_set_matches_d0_fixture` — load D0 CSV;
  assert build's migration set (branch-move list + CM-split list)
  equals D0's migration column.
- **Test:** `test_cm_hosted_aggregation_reads_integration_entry_data`
  — fake hass with CM entry + INTEGRATION entry carrying
  `CONF_TRACKED_PERSONS = ["person.a", "person.b"]`; run CM setup;
  assert 2 × per-person sensor sets registered + 2 house-level +
  2 alert binaries; assert their `_attr_device_info` identifiers
  target the correct coordinator devices.
- **Test:** `test_cm_hosted_aggregation_handles_missing_integration_entry`
  — CM setup without INTEGRATION entry present; assert no crash and
  warning logged; zero entities registered.
- **Test:** `test_cm_hosted_aggregation_handles_missing_person_coordinator`
  — INTEGRATION entry present, `person_coordinator` absent; assert
  house-level sensors register, per-person skipped.
- **Test:** `test_no_underscore_2_suffix_minted` — build fake registry
  from D0 CSV; run full INTEGRATION + CM setup; assert no NEW `_2`
  entity_ids in the post-setup registry beyond D0 baseline.
- **Test:** `test_stays_on_integration_entities_remain`
  — assert `IntegrationHouseStateSensor` + `ReconcileHealthSensor`
  post-setup owning `config_entry_id` == INTEGRATION entry_id AND
  device identity `(DOMAIN, "integration")`.
- **Test:** `test_coordinator_device_single_owner` — post-setup,
  every coordinator device's owning `config_entry_id` set has size 1
  and equals CM entry_id.
- **Test:** `test_dead_music_following_device_removed` — pre-state
  includes dead device with zero entities; post-setup device is gone.
- **Test:** `test_dead_device_not_removed_if_entities_present` —
  safety: if any entity points at it, the removal is skipped.
- **Test:** `test_migration_idempotent` — run CM setup twice; second
  run performs zero registry writes.
- **Live (orchestrator, MANDATORY pre-close):** re-run D0 probe;
  produce discriminator table:

  | Check | Discriminator |
  |---|---|
  | Entity count | pre == post |
  | Zero `_2` mints | count(post `_2` URA rows) − count(D0 `_2` URA rows) == 0 |
  | Coordinator devices single-owner (CM) | for each of the 9 coordinator identities, `|{config_entry_id}| == 1 AND == CM_ENTRY_ID` |
  | INTEGRATION owns Whole House only | every entity with `config_entry_id == INTEGRATION_ENTRY_ID` has `device_identifier == (DOMAIN, "integration")` |
  | STAYS entities preserved | `IntegrationHouseStateSensor`, `ReconcileHealthSensor` present under INTEGRATION |
  | Dead device removed | `(DOMAIN, "music_following")` absent |
  | Zero unavailable at T+60s | `post_unavailable − D0_unavailable == 0` |

- **Live (README write-back):** the discriminator table above with
  observed values goes into the release README's Validated section.

### D2 — Scoped duplicate-authoring collapse (music_following + notification_manager only)

**Music Following** — three co-existing authors, real divergence risk
(v5.10.0 double-prefix incident documented at `switch.py:~5702-5706`):
1. `_music_following_device_info` helper at `sensor.py:~7352`.
2. Inline `DeviceInfo(...)` at `switch.py:~5708` (MFPersonFollowSwitch).
3. Inline in the `music_following` `CoordinatorEnabledSwitch`
   registration at `switch.py:236-245` (via `device_name`/`device_model`
   kwargs).

**Fix.** Move `_music_following_device_info` to the new `_devices.py`
module. Route `MFPersonFollowSwitch.__init__` through the helper; drop
the inline literal at `switch.py:5708`. Route the
`music_following` `CoordinatorEnabledSwitch` through
`_coordinator_device_info("music_following")` from `_devices.py` (which
delegates to the same helper); drop `device_name`/`device_model`
kwargs at the registration site.

**Notification Manager** — three co-existing authors:
1. `_NMDeviceInfoMixin` at `number.py:~3596`.
2. Module-level `_nm_device_info` at `sensor.py:~7791`.
3. Inline at `domain_coordinators/notification_manager.py:~667`.

**Fix.** Move `_nm_device_info` to `_devices.py` as the sole author.
Delete the mixin at `number.py:3596-3606`; NM number entities import
the helper. Route the NM inline at `notification_manager.py:667`
through the helper.

**Out of scope for D2 (parked to `DEVICE-INFO-HELPER-CONSOLIDATION-1`):**
- The 7 non-NM/non-MF `_*_device_info()` helpers (safety, security,
  presence, energy, hvac, optimization, CM) stay in their current
  files.
- The ~100 inline `DeviceInfo(...)` literals in hvac (38), CM (23),
  energy (22), presence (21), NM-remaining (11 non-collapsed sites)
  — UNTOUCHED. These are not the cause of the split defect and are a
  separate refactor.

### Acceptance Criteria — D2 (scoped)

- **Verify:** `grep 'identifiers={(DOMAIN, "music_following_coordinator")}'`
  returns exactly ONE constructor call in the URA package
  (`_devices.py._music_following_device_info`).
- **Verify:** `grep 'identifiers={(DOMAIN, "notification_manager")}'`
  returns exactly ONE constructor call (`_devices.py._nm_device_info`).
- **Verify:** `switch.py:5708` no longer builds a DeviceInfo inline;
  imports + calls the helper.
- **Verify:** `_NMDeviceInfoMixin` deleted from `number.py`.
- **Test:** `test_music_following_single_devicinfo_author` (AST-based).
- **Test:** `test_notification_manager_single_deviceinfo_author`
  (AST-based).
- **Test:** `test_mf_person_follow_switch_shares_music_following_device`.
- **Test:** `test_nm_number_and_sensor_share_nm_device`.
- **Live:** MF device page lists ALL MF entities under one device;
  NM device page same.

### D3 — Fix model-string first-writer-wins race

Unchanged from Rev-1. Route `BaseCoordinator.device_info`
(`base.py:~200-208`) through
`_devices._coordinator_device_info(self.coordinator_id)`. Delete the
generic `"Domain Coordinator"` string.

### Acceptance Criteria — D3

- **Verify:** `grep -n '"Domain Coordinator"' custom_components/`
  returns zero non-comment hits.
- **Test:** `test_base_coordinator_device_info_matches_shared_helper`
  (INV-3 oracle) — for each `coordinator_id ∈ {safety, security,
  presence, energy, hvac, optimization, music_following,
  notification_manager, coordinator_manager}`, assert
  `BaseCoordinator(coordinator_id=...).device_info` equals
  `_devices._coordinator_device_info(coordinator_id)` on all four
  canonical fields.
- **Live:** Each coordinator's device page shows its specific model
  (e.g. "Energy Coordinator"), not "Domain Coordinator".

### D-NEST — Restore device-tree nesting

**Design.** `async_stamp_via_device_tree(hass)` in `_devices.py`, called
from `async_setup_entry` of INTEGRATION, CM, ZONE_MANAGER, each ZONE,
each ROOM entry AFTER `async_forward_entry_setups` returns. Guarded by
`hass.data[DOMAIN]["device_tree_stamped"]` per (entry_id, run_id).

**Parent map (identifiers verified against source):**

| Child identifier (as it appears in the registry) | Parent identifier | Source proof |
|---|---|---|
| `(DOMAIN, "coordinator_manager")` | `(DOMAIN, "integration")` | `__init__.py:4151` |
| `(DOMAIN, "zone_manager")` | `(DOMAIN, "integration")` | `__init__.py:4035, 909` |
| `(DOMAIN, "safety_coordinator")` | `(DOMAIN, "coordinator_manager")` | `binary_sensor.py:2085` |
| `(DOMAIN, "security_coordinator")` | `(DOMAIN, "coordinator_manager")` | `binary_sensor.py:2315` |
| `(DOMAIN, "presence_coordinator")` | `(DOMAIN, "coordinator_manager")` | `select.py:237` |
| `(DOMAIN, "energy_coordinator")` | `(DOMAIN, "coordinator_manager")` | `select.py:700` |
| `(DOMAIN, "hvac_coordinator")` | `(DOMAIN, "coordinator_manager")` | `select.py:979` |
| `(DOMAIN, "optimization_coordinator")` | `(DOMAIN, "coordinator_manager")` | `select.py:459` |
| `(DOMAIN, "music_following_coordinator")` | `(DOMAIN, "coordinator_manager")` | `sensor.py:~7352` (helper) |
| `(DOMAIN, "notification_manager")` | `(DOMAIN, "coordinator_manager")` | `binary_sensor.py:2394` |
| `(DOMAIN, "zone_<n>")` for each zone (dynamic — enumerate from registry at runtime) | `(DOMAIN, "zone_manager")` OR `(DOMAIN, "integration")` — pick at build (Reviewer B adjudicates; default: `zone_manager` since zone_manager device exists as `__init__.py:4035`) | dynamic |
| `(DOMAIN, "<room_entry_id>")` for each room (dynamic) | `(DOMAIN, "integration")` | dynamic |
| `(DOMAIN, "integration")` | (root; skip) | `aggregation.py:737` |

Static identifiers are pinned in a `PARENT_MAP` dict; dynamic ones
(zones, rooms) are matched by an identifier-prefix predicate at
runtime (`identifier[0] == DOMAIN AND (identifier[1].startswith("zone_")
OR identifier[1] not in STATIC_MAP)` — the latter catches room
identifiers whose entry_ids are unpredictable).

**Kill switch.** `URA_DEVICE_TREE_STAMPING_ENABLED: Final = True` in
`_devices.py`.

### Acceptance Criteria — D-NEST

- **Test:** `test_via_device_stamper_covers_all_ura_devices` (INV-4)
  — fake registry with every static identity + one zone + one room;
  post-run, every non-root URA device has `via_device_id` resolving
  to the correct parent per the map.
- **Test:** `test_via_device_stamper_idempotent`.
- **Test:** `test_via_device_stamper_skips_when_parent_not_yet_registered`.
- **Test:** `test_via_device_stamper_dynamic_zone_room_identifiers`
  — asserts zone_<n> and room-entry_id identifiers get correctly
  parented under `zone_manager` and `integration` respectively.
- **Live:** HA UI device page nests coordinators under CM under URA
  integration; zone_manager + zones + rooms under URA integration.
  Screenshot in README.

### D4 — Naming convention (BAKED: Option 3)

Unchanged from Rev-1. Integration name "Universal Room Automation" /
model "Whole House"; Coordinator Manager name "Coordinator Manager";
individual coordinators "<X> Coordinator" (no "URA:" prefix);
`zone_manager` device stays as authored today; zones "Zone: <X>";
rooms untouched.

### Acceptance Criteria — D4

- **Verify:** `_devices.py` holds `DEVICE_NAMES` + `DEVICE_MODELS`
  mappings; helpers consult them.
- **Verify:** grep old "URA: <Coord> Coordinator" strings — only
  release-note / comment hits.
- **Verify:** room device authoring at `entity.py:~38-44` untouched.
- **Test:** `test_device_naming_convention_option_3_applied`.
- **Live:** HA UI structure matches Option 3; screenshot in README.
- **Live:** Diff of room-owned entity friendly names pre vs post ==
  zero deltas.

### D5 — has_entity_name audit

Unchanged from Rev-1. Per-class table in the review doc; source-level
fixes for stragglers.

### Acceptance Criteria — D5

- **Verify:** audit table covers every concrete Entity subclass.
- **Test:** `test_no_entity_resolves_to_none_name`.
- **Live:** zero `"Error adding entity None"` URA log lines post-boot.

### D6 — Reload safety

Unchanged from Rev-1.

### Acceptance Criteria — D6

- **Test:** `test_device_tree_stamper_does_not_reload_parent_entry`
  (sibling `last_changed` invariant; non-hollow).
- **Test:** `test_d1_migration_does_not_write_entry_options` (mock
  `hass.config_entries.async_update_entry`; assert zero calls from
  D1 code paths).
- **Verify:** grep in `_devices.py` — zero `async_update_entry(`.
- **Live:** journalctl since deploy — no "reloading" URA log line
  beyond the code-deploy reload; no supervisor watchdog restart in
  30 min post-deploy.

---

## Files changed (planned, Rev-2)

| File | Change | Approx LoC |
|---|---|---|
| `docs/planning/AUDIT_device_entity_split_ownership_2026_09_03.md` + `.csv` (NEW) | D0 probe output + AST source enumeration | data only |
| `custom_components/universal_room_automation/_devices.py` (NEW) | `_music_following_device_info`, `_nm_device_info`, `_coordinator_device_info(coordinator_id)` dispatcher, `DEVICE_NAMES`/`DEVICE_MODELS` (Option 3), `async_stamp_via_device_tree`, `PARENT_MAP`, `URA_DEVICE_TREE_STAMPING_ENABLED` | ~220 |
| `custom_components/universal_room_automation/__init__.py` | Wire `async_stamp_via_device_tree` into integration + CM + zone_manager + zone + room `async_setup_entry` post-forward | ~25 |
| `custom_components/universal_room_automation/aggregation.py` | Delete lines 289-308 + 327-328 from existing coroutines; add `async_setup_cm_hosted_aggregation_sensors` + `async_setup_cm_hosted_aggregation_binary_sensors` + `_resolve_integration_entry` helper | ~+90 / −25 |
| `custom_components/universal_room_automation/sensor.py:161-175` (INTEGRATION branch) | Remove Exterior/Perimeter 6 + MusicFollowingHealthSensor (7 total); KEEP IntegrationHouseStateSensor + ReconcileHealthSensor + census | ~-10 |
| `custom_components/universal_room_automation/sensor.py:188+` (CM branch) | Add the 7 relocated sensors + `await async_setup_cm_hosted_aggregation_sensors(hass, entry, async_add_entities)` | ~+15 |
| `custom_components/universal_room_automation/binary_sensor.py` CM branch | Add `await async_setup_cm_hosted_aggregation_binary_sensors(...)` | ~+5 |
| CM `async_setup_entry` (`__init__.py:4091-4161`) | After D-NEST, dead-device cleanup guard for `(DOMAIN, "music_following")` | ~15 |
| `custom_components/universal_room_automation/domain_coordinators/base.py:~200-208` | Route through `_devices._coordinator_device_info`; delete `"Domain Coordinator"` | ~10 |
| `custom_components/universal_room_automation/sensor.py:~7352` | Move `_music_following_device_info` body to `_devices.py`; keep thin re-export if any external consumer imports by dotted path | ~-30 |
| `custom_components/universal_room_automation/sensor.py:~7791` | Delete duplicate `_nm_device_info` body; import from `_devices.py` | ~-30 |
| `custom_components/universal_room_automation/number.py:~3596-3606` | Delete `_NMDeviceInfoMixin`; NM number entities import helper | ~-15 |
| `custom_components/universal_room_automation/switch.py:~5708` | Import + call `_music_following_device_info` | ~-8 |
| `custom_components/universal_room_automation/switch.py:236-245` (MF `CoordinatorEnabledSwitch`) | Drop `device_name`/`device_model` kwargs; DeviceInfo comes from `_coordinator_device_info("music_following")` | ~-5 |
| `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:~667` | Import + call `_nm_device_info` | ~-5 |
| Entity files (D5 fixes) | Set `_attr_has_entity_name` / `_attr_name` where missing | ~10 |
| `quality/tests/test_device_entity_architecture.py` (NEW) | D0-loader + D1-D6 tests | ~500 |
| `docs/readmes/README_v<next>.md` | Release notes + Validated table + D1 discriminator with observed values + device-tree screenshot | ~80 |

Not in the diff (parked): the 7 other `_*_device_info` helpers; the
~100 non-MF/non-NM inline `DeviceInfo(...)` literals across hvac / CM /
energy / presence.

---

## Tier 2 review framings (two, parallel, framing-disjoint)

- **Reviewer A — Correctness + D1 preservation + migration completeness.**
  Verify D0 CSV IS the migration set (independently re-enumerate
  coordinator-device entities on INTEGRATION-branch platform setups
  AND inside `async_setup_aggregation_*` — do NOT trust the plan's
  table). Verify STAYS entities (`IntegrationHouseStateSensor`,
  `ReconcileHealthSensor`) present in the STAYS list and absent from
  the migration list. Verify each migration-target's unique_id is
  stable under the entry-swap (read each `__init__`). Verify D1 tests
  diff against the D0 CSV (hollow-anchor check: a test that hard-codes
  the migration set defeats the purpose). Verify INV-1's `_2`-mint
  check runs against a real entity-registry fixture, not a mock that
  paraphrases the API. Verify CM-hosted aggregation coroutines are
  invoked from the CM platform setups (not orphaned).
- **Reviewer B — HA lifecycle + reload-suppress + parent-map
  completeness + person_coordinator ordering.** Cite
  `homeassistant/helpers/device_registry.py` for
  `async_update_device(via_device_id=...)` support. Verify D-NEST
  placement is after `async_forward_entry_setups` on every entry type.
  Verify D6 non-hollow (sibling `last_changed`, not patched
  `async_reload`). Verify `async_setup_cm_hosted_aggregation_sensors`
  is invoked AFTER `person_coordinator` is populated in `hass.data`
  (CM setup ordering — `__init__.py:4091-4161`); if not guaranteed,
  require `async_at_started` deferral. Independently re-enumerate
  `PARENT_MAP` against a live registry export (INV-4 must not pass
  vacuously on wrong strings); verify `optimization_coordinator`,
  `notification_manager`, `zone_manager` all covered. Verify dynamic
  zone/room identifier predicate is correct.

**Pre-review baseline tag mandatory:**
`git tag pre-review-v<version> -m "Pre-review baseline"` before
review fix-ups.

**Orchestrator registry-verify (pre-deploy, MANDATORY for D1):**
Orchestrator personally re-runs the D0 probe pre-deploy, diffs
against the committed D0 fixture, runs the D1 test suite, and IF D0
flagged any BLOCKED unique_ids confirms the contingent per-platform
`_migrate_..._entity_unique_ids` hook is wired BEFORE
`async_add_entities` in that platform's CM branch (per C7). Halt
deploy on any drift.

**Live validation (post-deploy):** ura-validator re-runs the D0 probe
against the live registry, produces the INV-1 discriminator table,
and confirms INV-1 through INV-6. Cycle NOT closed until the README
carries the observed discriminator table (standing README write-back
rule).

---

## Explicit deferrals

- **Zone→Rooms nesting** — `DEVICE-ZONE-ROOM-NEST-1`.
- **Person device** — `PERSON-DEVICE-1`.
- **CONFIG-SUBENTRIES-MIGRATION-1**.
- **PLANNING_setup_unload_symmetry.md**.
- **`DEVICE-INFO-HELPER-CONSOLIDATION-1`** (NEW parked card) — the
  ~100-site inline `DeviceInfo(...)` consolidation for hvac / CM /
  energy / presence / remaining-NM. Revive trigger: after D1/D2/D3
  land and the next hygiene cycle picks it up against the tidied
  post-D2 baseline.
- **ENTITYDESC-RUNTIMEDATA-HYGIENE-1**.
- **entity_id / unique_id renames** — permanently OUT.

## Operator decisions

**None outstanding.** D4 baked as Option 3; tier baked as 2 with
elevated D1 gate; migration set fixed at 14 class sites → 17 D0
entities; STAYS list fixed at IntegrationHouseStateSensor +
ReconcileHealthSensor (+ all `(DOMAIN, "integration")`-identified
Whole-House aggregation entities); D2 scoped to music_following +
notification_manager only.
