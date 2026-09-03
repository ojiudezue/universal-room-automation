# PLANNING — Device / Entity Architecture Cleanup for HA 2026.9

**Card:** `DEVICE-ENTITY-ARCH-2026-9-1`
**Date:** 2026-09-03 (revised; original scoping 2026-09-03 pre-live-audit)
**Author:** ura-planner
**Precursor ship:** `v5.92.3` — stripped 109 `via_device=` declarations to
unblock the HA 2026.9 `DeviceInfo.via_device` breaking change. This
un-nested every URA coordinator/zone/room device on the HA device page.

**Tier:** **2** (two framing-disjoint build-reviews + ura-validator +
live-validation) with **one elevated hard-gate on D1** (the coordinator
device-de-fragmentation) requiring an orchestrator registry-verify
pre-deploy AND a D0 measure-before-build registry probe. Operator has
authorized build-to-completion at Tier 2; do NOT re-elevate to Tier 3
without a new operator sign-off.

Rationale for the reduction from the prior 2-DB framing: the previously
top-billed nesting/authorship refactor is a code-hygiene diff on
statically-shaped code paths. The live-audit finding below (coordinator
device split-ownership across TWO config entries) is a genuine,
observable, `unavailable`-on-mis-migration defect and is the piece that
carries the elevated gate. The rest is Tier 2.

---

## LEAD DEFECT — coordinator devices are split-owned across two config entries

**Observed live 2026-09-03 (operator + registry read):**

The parent **"Universal Room Automation"** config entry (`ENTRY_TYPE_INTEGRATION`)
hosts:
- `Whole House` — **80 entities** — CORRECT.
- `Coordinator Manager` — **10 entities** — WRONG (belongs to CM entry).
- `Music Following Coordinator` — **1 entity** — WRONG.
- `Security Coordinator` — **6 entities** — WRONG.

The **"URA: Coordinator Manager"** entry (`ENTRY_TYPE_COORDINATOR_MANAGER`)
hosts the bulk of the same device identities:
- `Coordinator Manager` — **50 entities**.
- `Security Coordinator` — **15 entities**.
- `Music Following Coordinator` — **9 entities**.

Because both entries register entities whose `DeviceInfo.identifiers`
include the SAME `(DOMAIN, "<coord>_coordinator")` tuples, HA's device
registry merges each into ONE device — but the entities are owned by two
different `config_entry_id`s. **Deleting either config entry orphans
half of every affected device.** A dead greyed **`URA: Music Following`**
device (0 entities) also appears in both entries — a tombstone from a
prior naming shape and safe to delete once the split-ownership is fixed.

### Root cause (verified in source, not inferred)

Both the integration entry and the CM entry forward the SENSOR / SWITCH /
BUTTON / SELECT / TIME / BINARY_SENSOR platforms:

- `__init__.py:339-350` — `INTEGRATION_PLATFORMS` list.
- `__init__.py:3923` — integration `async_setup_entry` calls
  `async_forward_entry_setups(entry, INTEGRATION_PLATFORMS)`.
- `__init__.py:4160-4161` — CM `async_setup_entry` calls
  `async_forward_entry_setups(entry, cm_platforms)` where
  `cm_platforms = list(INTEGRATION_PLATFORMS) + [Platform.NUMBER]`.

Each platform's `async_setup_entry` branches by `CONF_ENTRY_TYPE`. On
the `ENTRY_TYPE_INTEGRATION` branch, some entities are registered whose
`DeviceInfo` identifiers point at COORDINATOR devices, not the
integration device. Verified sites (representative, not exhaustive —
D0 probe enumerates the rest):

- `sensor.py:139-179` — `ENTRY_TYPE_INTEGRATION` branch adds
  `MusicFollowingHealthSensor(hass, entry)` at :173 whose `_attr_device_info`
  points at `(DOMAIN, "music_following_coordinator")` (verified via the
  `_music_following_device_info` helper at `sensor.py:7352`), and
  `ReconcileHealthSensor(hass, entry)` at :175 whose DeviceInfo needs to
  be verified during the D0 probe (candidate CM-device owner).
- Other coordinator-device entities added on the INTEGRATION branch
  across `sensor.py`, `switch.py`, `binary_sensor.py`, `button.py`,
  `select.py` — D0 must enumerate.

The `ENTRY_TYPE_COORDINATOR_MANAGER` branch (`sensor.py:188` onward,
`switch.py:198` onward) then registers the FULL coordinator entity set
under the CM entry, so the second registration writes the same device
identity from a different `config_entry_id`. HA merges the device;
entities stay under whichever entry registered them. Result: split
ownership.

### The fix

Move every entity whose DeviceInfo resolves to a **coordinator device
identity** (`{coord}_coordinator`, `coordinator_manager`,
`notification_manager`, `music_following_coordinator`) out of the
`ENTRY_TYPE_INTEGRATION` platform-setup branches and into the
`ENTRY_TYPE_COORDINATOR_MANAGER` branches. The INTEGRATION entry hosts
ONLY entities whose DeviceInfo resolves to the Whole House
(`(DOMAIN, "integration")`) device — the census / aggregation / house
switches / integration-options switches already on that branch.

The dead `URA: Music Following` device (identifier verified at D0 —
suspected `(DOMAIN, "music_following")` bare) gets removed via
`dr.async_remove_device` after D1 lands and no entities point at it.

### Why entity_id preservation is the hard gate

When we move an entity's `async_add_entities` call from the INTEGRATION
entry's platform to the CM entry's platform, HA's entity registry will
re-home the entity to a new `config_entry_id`. **If the entity's
`unique_id` is stable across the move**, the registry's
`async_get_or_create` path matches the existing row by `(platform,
domain, unique_id)` and updates the `config_entry_id` in place — the
`entity_id` and history are preserved. **If the unique_id shifts (even
by prefix)**, the registry mints a NEW row and appends `_2` — the
`reference_frigate1_retired_2suffix_permanent` footgun. That outcome is
irreversible for practical purposes (HA never renames retroactively; the
old row lingers until manually removed and its history is stranded).

Therefore the D1 build MUST verify unique_id stability per entity before
flipping the registration site, and the acceptance gate is measurable
(zero `_2` mints, entity count preserved).

---

## SCOPE

**IN:**
- **D0 (NEW, MEASURE-BEFORE-BUILD):** live registry probe enumerating
  which URA entities are owned by which config entry today, keyed by
  device identity, plus each entity's unique_id — the hand-built fixture
  the D1 migration is diffed against.
- **D1 (ELEVATED gate):** de-fragment coordinator device ownership so
  every coordinator-device entity is owned by the CM entry ONLY, and
  the INTEGRATION entry hosts only Whole House entities. Preserve
  entity_id + unique_id (zero `_2` mints). Remove the dead
  `URA: Music Following` device.
- **D2:** consolidate every `_*_device_info()` into a single new
  `_devices.py`; kill inline DeviceInfo duplicates (music-following 3×:
  helper + `switch.py:5708` inline + coordinator switch inline;
  notification_manager 3×).
- **D3:** fix the model first-writer-wins race between
  `domain_coordinators/base.py:~200-208` ("Domain Coordinator") and the
  per-coordinator helpers in `sensor.py`.
- **D-NEST (was D1 in prior draft):** restore device-tree nesting via
  `dr.async_update_device(..., via_device_id=...)` POST-setup — the
  sanctioned 2026.9 path. Coordinators → CM → Whole House; zones →
  Whole House; rooms → Whole House. Mirrors the area-stamp precedent at
  `entity.py:~69-98`.
- **D4:** naming convention — **OPERATOR DECIDED = Option 3** (structural
  distinction via nesting; rooms untouched; no room-device renames;
  zero friendly-name churn). Baked in — no further decision required.
- **D5:** `has_entity_name` per-concrete-entity audit (oracle: zero
  "Error adding entity None" from URA at boot).
- **D6:** reload safety — device-registry writes only; NO parent-entry
  reload (watchdog hazard per `feedback_parent_entry_reload_watchdog_hazard`).
  Reuse the `CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1` precedent
  (sibling-`last_changed`-invariant test).

**OUT (non-goals — do NOT expand):**
- Flat→subentries migration (`CONFIG-SUBENTRIES-MIGRATION-1`) — parked.
- Setup/unload symmetry hotfix (`PLANNING_setup_unload_symmetry.md`) —
  separate card.
- `entity_id` / `unique_id` renames — permanently OUT. D1 preserves
  them; that IS the gate.
- `ENTITYDESC-RUNTIMEDATA-HYGIENE-1` — parked; fold in the follow-up
  cycle against tidied authorship unless trivially in-path.
- Zone→Rooms nesting (`DEVICE-ZONE-ROOM-NEST-1`) — parked.
- Person device (`PERSON-DEVICE-1`) — parked.

**Parsimony ledger:** +0 CONF_*; +0 sensors; +0 signals; +1 new module
(`_devices.py`); +1 setup hook (D-NEST stamper); refactor-only diff for
D1/D2/D3.

---

## Institutional context verified

### Greps run + results

| Question | Command | Result |
|---|---|---|
| Are coordinator-device entities registered on the INTEGRATION-entry branch? | Read `sensor.py:127-179` and `switch.py:153-196` | **YES.** `sensor.py:173` adds `MusicFollowingHealthSensor` under `ENTRY_TYPE_INTEGRATION` and its `_attr_device_info` uses `_music_following_device_info` (`sensor.py:7352`) → `(DOMAIN, "music_following_coordinator")`. `sensor.py:175` adds `ReconcileHealthSensor` (device identity TBD by D0 probe). This is the split-ownership producer. D0 enumerates the rest. |
| Does both entries forward the same platforms? | `grep -n 'INTEGRATION_PLATFORMS\|cm_platforms\s*=' __init__.py` | **YES.** `__init__.py:3923` (integration) and `__init__.py:4160-4161` (CM) both forward SENSOR / BINARY_SENSOR / SELECT / SWITCH / BUTTON / TIME; CM adds NUMBER. |
| ENTRY_TYPE constants | `const.py:50-54` | `ENTRY_TYPE_INTEGRATION`, `_ROOM`, `_ZONE`, `_ZONE_MANAGER`, `_COORDINATOR_MANAGER`. |
| `via_device=` residual after v5.92.3 strip? | `grep -rn via_device custom_components/universal_room_automation` | 1 hit — comment only (`aggregation.py:3660`). Strip complete. |
| `_*_device_info()` helpers in the tree | `grep -rn 'def _\w+_device_info' custom_components/universal_room_automation` | 10 helpers across `sensor.py` / `button.py` / `number.py` (see prior audit at bottom of this section). |
| `DeviceInfo(` call sites | `grep -c 'DeviceInfo('` | ~143 across 12 files (sensor.py:30, binary_sensor.py:19, switch.py:35, number.py:28, select.py:10, button.py:14, time.py:1, entity.py:1, aggregation.py:2, base.py:1, manager.py:1, notification_manager.py:1). The D0 probe is authoritative for the migration set — this grep is a floor, not the target. |
| Entity-registry contract for unique_id-stable config_entry_id change | Builder must cite `homeassistant/helpers/entity_registry.py` `async_get_or_create` at build; NOT asserted from memory (per `feedback_no_fabrication`). |

### For each proposed addition — REUSED vs NEW

- **D0 registry probe** → **REUSED pattern**. Read-only script over
  `.storage/core.entity_registry` + `core.device_registry` on the live
  homeassistant mount (see `feedback_measure_before_build`). No repo
  changes. Output committed as
  `docs/planning/AUDIT_device_entity_split_ownership_2026_09_03.md` and
  becomes the D1 acceptance fixture.
- **D1 branch-move** → **REUSED**. No new machinery; the fix is
  relocating existing `async_add_entities([...])` items between the
  `ENTRY_TYPE_INTEGRATION` and `ENTRY_TYPE_COORDINATOR_MANAGER`
  branches in the existing per-platform `async_setup_entry` functions.
  Precondition: entity unique_ids do not change (verified per-entity
  at build).
- **D-NEST setup hook to stamp `via_device_id` post-creation** → **NEW**
  code, **REUSED precedent** exactly: `entity.py:69-98` (post-creation
  `dr.async_update_device(..., area_id=...)`). Same shape, different
  DeviceEntry field (`via_device_id`). Builder must cite the HA
  device-registry source line supporting the field before writing.
- **D2 helper consolidation** → **REUSED** (10 helpers already exist);
  **NEW** placement (`_devices.py` module). One new helper:
  `_coordinator_device_info(coordinator_id)` dispatcher for D3.
- **D3 canonical (name, model, manufacturer, sw_version)** → REUSED via
  the D2 centralization; no new state.
- **D4 name/model constants** → NEW block inside `_devices.py`. Baked
  as Option 3 (no operator decision pending). Rooms untouched.
- **D6 reload-suppress** → REUSED — mirror the census-toggles
  sibling-`last_changed`-invariant test.

### Prior planning docs consulted

- `docs/planning/PLANNING_census_toggles_to_device_switches.md` — the
  load-bearing precedent for device-registry-adjacent writes that must
  NOT trigger `_async_update_listener`.
- `docs/planning/PLANNING_setup_unload_symmetry.md` — explicit non-goal.

### Memory bodies pulled

- `reference_frigate1_retired_2suffix_permanent` — the exact footgun D1
  is gating against. Any migration that mints a `_2` suffix is a hard
  fail.
- `feedback_parent_entry_reload_watchdog_hazard` — D6 invariant.
- `feedback_suppression_needs_discharge` — governs D6.
- `feedback_measure_before_build` — governs D0.
- `feedback_no_fabrication` — the HA device / entity registry API
  behavior must be cited from `homeassistant/helpers/*.py` at build,
  not asserted from memory.
- `feedback_read_consumers_before_asserting_function` — every
  `_*_device_info()` helper's consumers enumerated BEFORE D2 refactor;
  NM has two helpers (mixin + module-level) — read both consumer sets.
- `feedback_hollow_test_anchors` — D5 tests drill by detaching the
  value; D1 tests must exercise a REAL registry-move flow (real
  `hass.config_entries` fixtures, not mocks that paraphrase the API).
- `feedback_coincidental_equality_masks_concept_split` — the two
  music_following device identities (bare `music_following` tombstone
  vs `music_following_coordinator`) are the concept split; treat them
  as distinct even if the tombstone is empty today.

### Design docs read

- `docs/QUALITY_CONTEXT.md` — bug classes #7 (stale data source — device
  identity written from two sites with divergent values, i.e. D3), #22
  (enum mismatch — same class), #46 (unique_id churn on refactor — D1
  is expressly designed to avoid this).

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/const.py:40-70` (entry
  types).
- `custom_components/universal_room_automation/__init__.py:329-350`
  (platform lists), `:1611-1644` (integration setup),
  `:4091-4161` (CM setup), `:3923` (integration forward), `:4160-4161`
  (CM forward).
- `sensor.py:127-260` (integration + CM setup branches;
  MusicFollowingHealthSensor on integration branch is the smoking gun).
- `switch.py:153-296` (integration + CM setup branches; the seven
  `CoordinatorEnabledSwitch` registrations on the CM branch).
- `entity.py:1-99` (area-stamp precedent; has_entity_name base).
- `aggregation.py:720-760, 3660` (integration-device authoring, stale
  via_device comment context).
- `domain_coordinators/base.py:190-210` (model-string race source).
- `domain_coordinators/notification_manager.py:660-675` (3rd NM
  authoring site).
- `__init__.py:5905-6675` (reload-suppress infrastructure — D6 must not
  interact negatively).

---

## Falsifiable invariants

**INV-0 (D0 measurement):** The registry probe produces a table with
one row per URA-owned entity: `entity_id`, `unique_id`,
`config_entry_id`, `device_identifier`. The row count equals the live
entity count (4626 as of 2026-09-03). Any coordinator-device entity
(`device_identifier[1]` in the coordinator-identity set) whose
`config_entry_id` equals the INTEGRATION entry id is a migration target.

**INV-1 (D1 preservation — the elevated gate):** After deploy:
- Total URA entity count is unchanged (4626 pre → 4626 post).
- ZERO new entities with a `_2` suffix minted by URA in the migration
  window (grep the post-boot registry for `_2$` on the URA-owned
  entity_ids and diff against the D0 fixture).
- ZERO URA entities in `unavailable` state 60s after boot (excluding
  entities that were already `unavailable` in the D0 snapshot for
  independent reasons — enumerate them in the probe output).
- Every coordinator device (`safety_coordinator`, `security_coordinator`,
  `presence_coordinator`, `energy_coordinator`, `hvac_coordinator`,
  `optimizer_coordinator`, `music_following_coordinator`,
  `notification_manager`, `coordinator_manager`) has EXACTLY ONE
  `config_entry_id` owning its entities, and that entry is the CM entry.
- The INTEGRATION entry owns entities for the `integration` /
  `whole_house` device ONLY.
- The dead `URA: Music Following` device (identifier confirmed at D0)
  is removed from the device registry.
- Falsifier: any row in the post-deploy probe violates one of the above.

**INV-2 (D2 single-source-of-truth):** For every device identity
`(DOMAIN, X)` in the canonical set, `(name, model, manufacturer,
sw_version)` is stamped from EXACTLY ONE code path. AST oracle: for
each identifier, exactly one `DeviceInfo(identifiers={(DOMAIN, X)}, ...)`
constructor call in the URA package.

**INV-3 (D3 no-race model):** For any `{coord}_coordinator` identifier,
`domain_coordinators/base.py:device_info` returns a DeviceInfo whose
`(name, model)` equals the `_devices.py` helper's `(name, model)` for
the same identifier. Falsifier: unit test builds both, asserts equality
per identifier. Today the code fails this test (`base.py:206` emits
`"Domain Coordinator"` universally).

**INV-4 (D-NEST):** For every URA-owned DeviceEntry other than the
integration root, `device.via_device_id` resolves via `dr.async_get` to
the id of the DEVICE the D4 parent-map assigns. Discriminator: count of
URA devices with unresolved parents equals 0.

**INV-5 (D5 has_entity_name):** Every concrete `Entity` subclass in the
integration either sets `_attr_has_entity_name = True` OR sets
`_attr_name` to a non-None value. Discriminator: zero occurrences of
HA guard string `"Error adding entity None"` from URA in the post-boot
log.

**INV-6 (D6 no reload):** Neither the D-NEST stamper nor the D1
registration relocation triggers `_async_update_listener` or
`async_reload` on any config entry. Falsifier: sibling entity's
`last_changed` timestamp bumps across the setup window. **However —
D1 IS a code deploy that will naturally cause one reload of the URA
entries as part of the release itself.** The invariant applies to
post-setup runtime, not to the deploy restart itself.

---

## Deliverables

### D0 — Live registry probe (MEASURE-BEFORE-BUILD)

**Trigger check (from `feedback_measure_before_build`):** Does D1's
correctness depend on the exact set of split-owned entities today?
YES. Does the plan currently propose runtime instrumentation for
something a one-shot offline script can answer? YES if we just build.
→ Probe first.

**Method.** Read-only Python one-shot over the live
`.storage/core.entity_registry` and `.storage/core.device_registry`
from the mounted homeassistant config path
(`/Users/ojiudezue/ha-config/.storage/`) — do NOT modify. Emit a
committed audit doc:
`docs/planning/AUDIT_device_entity_split_ownership_2026_09_03.md`
with:

1. **Split-ownership table** — every URA-owned device with entity
   counts broken out per `config_entry_id`; every device whose entity
   count is non-zero under both entries is a D1 migration target.
2. **Migration set** — per entity: `entity_id`, `unique_id`,
   `platform`, current `config_entry_id`, target `config_entry_id`,
   `device_identifier`. This IS the D1 fixture; the build tests diff
   its live post-deploy re-run against this file.
3. **Baseline totals** — total URA entity count (~4626), entities
   already `unavailable` at probe time (excluded from D1's zero-unavail
   AC), and the identifier of the greyed `URA: Music Following` device
   (candidate `(DOMAIN, "music_following")`).
4. **Unique_id stability audit** — for each migration-target entity,
   verify the class's `__init__` computes `unique_id` from data that
   is independent of the config entry (typical: DOMAIN + slug + suffix,
   not `entry.entry_id + ...`). Any entity whose unique_id embeds the
   INTEGRATION `entry_id` is a HARD BLOCKER — flagged for the build to
   design a `_migrate_unique_id` step BEFORE re-registering, otherwise
   a `_2` mint is guaranteed.

**Deliverable format.** Markdown table + CSV attachment
(`AUDIT_device_entity_split_ownership_2026_09_03.csv`) so the D1 build
can load it as a test fixture directly.

### Acceptance Criteria — D0

- **Verify:** Audit doc + CSV committed under `docs/planning/`.
- **Verify:** Every device in the "Whole House / Coordinator Manager /
  Music Following / Security" split observed by the operator on
  2026-09-03 appears in the split-ownership table with matching counts
  (80 / 10 / 1 / 6 under integration; 50 / 15 / 9 under CM).
- **Verify:** Unique_id stability audit column marks each
  migration-target row as SAFE (unique_id independent of INTEGRATION
  `entry_id`) or BLOCKED (embeds INTEGRATION `entry_id`). Any BLOCKED
  row triggers a plan revision before D1 build dispatch.
- **Live:** Probe is one-shot read-only; no restart required.

### D1 — De-fragment coordinator device ownership (ELEVATED HARD GATE)

**Design.** For each entity in the D0 migration set:

1. Locate its `async_add_entities([...])` call site in the
   `ENTRY_TYPE_INTEGRATION` branch of the relevant platform.
2. Move the registration to the corresponding
   `ENTRY_TYPE_COORDINATOR_MANAGER` branch in the same platform file,
   preserving construction args (the entity is still constructed with
   the CM entry rather than the integration entry — verify the
   entity's `__init__` does not persist the `entry` arg in a way that
   affects unique_id).
3. If the entity's unique_id derives from `entry.entry_id`, add a
   `_migrate_entity_unique_id` step invoked from the CM `async_setup_entry`
   BEFORE the platform forward — analogous to
   `_migrate_excess_solar_entity_id` at `switch.py` (called from
   `switch.py:201`). Pattern: on setup, look up the pre-existing
   registry row by the OLD unique_id, rewrite `unique_id` to the new
   scheme (typically dropping the `entry_id` prefix), and the platform
   registration then matches the row in place.
4. Remove the dead `(DOMAIN, "music_following")` device (or whatever
   identifier D0 confirms) via `dr.async_remove_device` in the CM setup,
   guarded by "no entities point at it".

**Constraint — do NOT rename any entity_id.** The migration relies on
entity-registry unique_id matching to re-home rows in place. The AC
verifies zero `_2` mints and zero unavailable entities.

**Restart resilience.** If setup fails partway (e.g. CM setup crashes
after registering half the migrated entities), the partial state is
observable at the next boot via a re-run of the D0 probe (compare live
vs D0 fixture) — the build includes a `test_migration_is_idempotent`
that runs the CM setup twice against a fake hass and asserts the
second run performs zero registry writes.

### Acceptance Criteria — D1 (ELEVATED)

- **Verify (orchestrator):** Pre-deploy dry-run — the build's D1 test
  loads the D0 CSV fixture, walks every migration-target entity, and
  asserts (a) the unique_id computed by the entity's `__init__` when
  constructed with the CM entry equals the pre-existing unique_id in
  the fixture, OR (b) a `_migrate_entity_unique_id` step is wired that
  rewrites the fixture row to match. NO entity fails this check.
- **Test:** `test_coordinator_device_ownership_de_fragmented` — build
  a fake hass with integration entry + CM entry; run both entries'
  `async_setup_entry`; assert every URA device's owning
  `config_entry_id` set has size 1, and coordinator devices are owned
  by CM.
- **Test:** `test_no_underscore_2_suffix_minted` — same fixture; assert
  no entity_id in the post-setup registry ends with `_2` that did not
  already end with `_2` in the D0 fixture.
- **Test:** `test_migration_is_idempotent` — run CM setup twice; assert
  the second run makes zero writes to the entity registry.
- **Test:** `test_dead_music_following_device_removed` — start with a
  fake registry that includes the dead identifier; after setup, assert
  the device is gone AND no entities were orphaned.
- **Live (orchestrator registry-verify, MANDATORY pre-close):** Post
  restart, re-run the D0 probe; diff its output against the pre-deploy
  fixture. Discriminator table:

  | Check | Discriminator |
  |---|---|
  | Entity count | pre == post (4626) |
  | Zero `_2` mints | grep post CSV for `_2$` on URA entity_ids; count == 0 (excluding D0-baseline `_2` entries) |
  | Coordinator devices single-owner | every coord device's `config_entry_id` set size == 1 AND that entry is CM |
  | INTEGRATION entry owns Whole House only | every entity owned by the INTEGRATION entry has `device_identifier == (DOMAIN, "integration")` (or the Whole House canonical identifier D4 confirms) |
  | Dead device removed | `(DOMAIN, "music_following")` (or D0-confirmed identifier) is absent from device registry |
  | Zero unavailable at T+60s | live query: URA-owned entities in `unavailable` state at 60s post-boot minus D0-baseline unavailable set == 0 |

- **Live (README write-back):** The Validated table in the release
  README includes this discriminator table with observed values.

### D2 — Single source of truth per device

**Design.** All 10 existing `_*_device_info()` helpers move to a new
`custom_components/universal_room_automation/_devices.py`. Platforms
import a single symbol per device identity. Collapses:

- `_NMDeviceInfoMixin` (`number.py:~3596`) + module-level
  `_nm_device_info` (`sensor.py:~7791`) + inline in
  `domain_coordinators/notification_manager.py:~667` → ONE
  `_nm_device_info()` in `_devices.py`.
- `_music_following_device_info` (`sensor.py:~7352`) becomes importable
  from `switch.py:~5708` (currently duplicated inline —
  `v5.10.0` double-prefix bug comment at `switch.py:~5702-5706` is the
  institutional receipt for why divergence hurts).
- The 7 `CoordinatorEnabledSwitch` registrations at
  `switch.py:206-278` currently pass `device_name` / `device_model` as
  per-call kwargs — those get dropped; the switch's DeviceInfo comes
  from `_coordinator_device_info(coordinator_id)` in `_devices.py`.

**Deferred inline literals (out of scope):**
- Room DeviceInfo in `entity.py:38-44` — stays (intrinsically per-entry).
- Zone DeviceInfo in `aggregation.py:3662` (via_device context) — audit
  at build to confirm it stays.
- Integration DeviceInfo in `aggregation.py:736-742` — stays (sole
  author).

### Acceptance Criteria — D2

- **Verify:** For each canonical coordinator device identity, grep for
  `identifiers={(DOMAIN, "<id>")}` returns hits ONLY inside the
  canonical helper in `_devices.py`.
- **Verify:** `music_following_coordinator` appears as ONE DeviceEntry
  in the registry (INV-2 discriminator; v5.10.0 double-prefix was the
  negative case).
- **Verify:** `notification_manager` appears as ONE DeviceEntry.
- **Test:** `test_device_identity_has_single_author` — parse the URA
  package AST; for each canonical id, exactly one `DeviceInfo(
  identifiers={(DOMAIN, id)}, ...)` node exists.
- **Test:** `test_mf_person_follow_switch_shares_music_following_device`.
- **Test:** `test_nm_number_and_sensor_share_nm_device`.
- **Live:** Music Following Coordinator device page lists ALL
  music-following entities under that ONE device.

### D3 — Fix model-string first-writer-wins race

**Cause.** `domain_coordinators/base.py:~200-208` returns
`DeviceInfo(identifiers={(DOMAIN, f"{coordinator_id}_coordinator")},
model="Domain Coordinator", ...)`. Per-coordinator sensor.py helpers
(e.g. `_energy_device_info` at `sensor.py:~8328`) return
`model="Energy Coordinator"` for the SAME identifier. Whichever writes
first wins the model field on the device row.

**Fix.** Route `BaseCoordinator.device_info` through
`_devices._coordinator_device_info(self.coordinator_id)`. Delete the
generic `"Domain Coordinator"` string.

### Acceptance Criteria — D3

- **Verify:** `grep -n '"Domain Coordinator"' custom_components/`
  returns zero hits (excluding release notes / comments).
- **Test:** `test_base_coordinator_device_info_matches_shared_helper`
  (INV-3 oracle).
- **Live:** Each coordinator's device page shows the specific model
  string ("Energy Coordinator", etc.), not "Domain Coordinator".

### D-NEST — Restore device-tree nesting under 2026.9

**Design.** New coroutine `async_stamp_via_device_tree(hass)` in
`_devices.py`. Called from `async_setup_entry` of the integration entry
AND each CM/room/zone entry AFTER
`hass.config_entries.async_forward_entry_setups(...)` returns, so a
late-arriving child re-stamps. Guarded by
`hass.data[DOMAIN]["device_tree_stamped"]` per (entry_id, run_id) so
the walk is at-most-once per setup.

**Parent map:**

| Child identifier | Parent identifier |
|---|---|
| `(DOMAIN, "coordinator_manager")` | `(DOMAIN, "integration")` |
| `(DOMAIN, "<coord>_coordinator")` (safety, security, presence, energy, hvac, optimizer, music_following, notification_manager) | `(DOMAIN, "coordinator_manager")` |
| `(DOMAIN, "zone_<n>")` | `(DOMAIN, "integration")` |
| `(DOMAIN, "<room_entry_id>")` | `(DOMAIN, "integration")` |
| `(DOMAIN, "integration")` | (root; no parent) |

**Algorithm.**
```
for each URA-owned device in registry:
    parent_identifier = PARENT_MAP.get(device.identifiers)
    if parent_identifier is None: continue
    parent_device = dev_reg.async_get_device(identifiers={parent_identifier})
    if parent_device is None: continue  # retry on next child setup
    if device.via_device_id == parent_device.id: continue
    dev_reg.async_update_device(device.id, via_device_id=parent_device.id)
```

**Kill switch.** `URA_DEVICE_TREE_STAMPING_ENABLED: Final = True` in
`_devices.py`.

### Acceptance Criteria — D-NEST

- **Test:** `test_via_device_stamper_stamps_all_ura_devices` (INV-4).
- **Test:** `test_via_device_stamper_idempotent`.
- **Test:** `test_via_device_stamper_skips_when_parent_not_yet_registered`.
- **Live:** HA UI device page nests coordinators under Coordinator
  Manager; CM under URA integration; zones + rooms under URA
  integration. Screenshot pasted into release README Validated table.

### D4 — Naming convention (BAKED: Option 3)

Operator decision: **Option 3 — structural distinction via nesting; no
room renames; zero friendly-name churn.**

- Integration device: name `"Universal Room Automation"`, model
  `"Whole House"` (unchanged from `aggregation.py:~736-742`).
- Coordinator Manager: name `"Coordinator Manager"`, model
  `"Coordinator Manager"` — drops the `"URA: "` prefix in favor of
  structural nesting (D-NEST parents it under URA integration).
- Individual coordinators: name `"<X> Coordinator"` (no `"URA: "`
  prefix), model `"<X> Coordinator"`. Distinguished from the house by
  being CHILDREN of CM in the tree, not by a name prefix.
- Zones: `"Zone: <X>"` (unchanged).
- Rooms: name `<room_name>` (bare), model `const.MODEL` (unchanged).
  **No room renames anywhere.**

### Acceptance Criteria — D4

- **Verify:** `_devices.py` holds `DEVICE_NAMES` + `DEVICE_MODELS`
  mappings that every D2 helper consults.
- **Verify:** `grep -rn '"URA: <Coord> Coordinator"'` returns only
  release-note / comment hits.
- **Verify:** Room device authoring (`entity.py:~38-44`) untouched;
  no room-name or room-model change committed in this cycle.
- **Test:** `test_device_naming_convention_option_3_applied`.
- **Live:** HA UI shows coordinators nested under CM under URA
  integration; screenshot in release README.
- **Live:** Diff pre vs post friendly names of room-owned entities;
  zero deltas (Option 3 guarantees this).

### D5 — has_entity_name per-concrete-entity audit

**Method.** Enumerate every concrete `Entity` subclass in the URA
package. For each, compute `has_entity_name` resolution and `name`
resolution. Entities that end up with `has_entity_name unset/False AND
name is None` are 2026.9 rejection targets.

**Deliverable.** Per-class table in
`docs/reviews/code-review/v<version>_device_entity_arch_review.md` plus
source-level fixes for stragglers. Base-class coverage (`URAEntity` at
`entity.py:22`, `AggregationEntity` at `aggregation.py:733`,
`CoordinatorEnabledSwitch` at `switch.py:608`) covers most.

### Acceptance Criteria — D5

- **Verify:** Audit table covers every concrete Entity subclass.
- **Test:** `test_no_entity_resolves_to_none_name` — construct every
  concrete Entity subclass with minimal fixtures; assert none produce
  `name is None AND not has_entity_name`. Skip list annotated
  explicitly with reason.
- **Live:** Boot log post-restart shows ZERO
  `"Error adding entity None"` occurrences attributable to URA.

### D6 — Reload safety

**Guarantee.** D1 relocates registrations between two platform-setup
branches — those setups run in the normal deploy restart, no runtime
reload. D-NEST writes device-registry rows only, not `entry.options`,
so it does NOT enter `_async_update_listener` (`__init__.py:~6434`).

### Acceptance Criteria — D6

- **Test:** `test_device_tree_stamper_does_not_reload_parent_entry` —
  sibling entity `last_changed` invariant (non-hollow — do NOT patch
  `async_reload`; observe the sibling directly).
- **Test:** `test_d1_migration_does_not_write_entry_options` — mock
  `hass.config_entries.async_update_entry`; run D1 CM setup; assert
  zero calls.
- **Verify:** grep in `_devices.py` returns zero
  `async_update_entry(` occurrences.
- **Live:** Post-deploy, `journalctl -u home-assistant --since <deploy>`
  shows URA setup completes without any "reloading" log line other
  than the code-deploy reload itself; no supervisor-watchdog restart
  in the 30 minutes post-deploy.

---

## Files changed (planned)

| File | Change | Approx LoC |
|---|---|---|
| `docs/planning/AUDIT_device_entity_split_ownership_2026_09_03.md` (NEW) + `.csv` | D0 probe output | data only |
| `custom_components/universal_room_automation/_devices.py` (NEW) | 10 canonical helpers, `_coordinator_device_info` dispatcher, `DEVICE_NAMES`/`DEVICE_MODELS` (Option 3), `async_stamp_via_device_tree`, `URA_DEVICE_TREE_STAMPING_ENABLED` | ~280 |
| `custom_components/universal_room_automation/__init__.py` | Wire `async_stamp_via_device_tree` into integration + CM + room + zone `async_setup_entry` post-forward | ~25 |
| `custom_components/universal_room_automation/sensor.py:139-179` (INTEGRATION branch) | Remove `MusicFollowingHealthSensor`, `ReconcileHealthSensor` (+ any others D0 flags) from integration branch | ~-10 |
| `custom_components/universal_room_automation/sensor.py:188+` (CM branch) | Add the same entities constructed with the CM entry | ~+10 |
| Analogous relocations in `switch.py` / `binary_sensor.py` / `button.py` / `select.py` (D0-driven set) | Move coordinator-device entities from INTEGRATION to CM branch | D0-driven |
| `custom_components/universal_room_automation/switch.py:201` (CM setup) | Optional `_migrate_entity_unique_id` hook wired here IF D0 flags any migration-target entity whose unique_id embeds the INTEGRATION entry_id | ~30 (only if needed) |
| `custom_components/universal_room_automation/domain_coordinators/base.py:~200-208` | Route through `_devices._coordinator_device_info`; delete `"Domain Coordinator"` | ~10 |
| `custom_components/universal_room_automation/sensor.py` (helper bodies) | Delete helper bodies; keep thin re-exports if consumers import by dotted path | ~-80 |
| `custom_components/universal_room_automation/number.py:~3596-3606` | Delete `_NMDeviceInfoMixin`; entities import helper | ~-15 |
| `custom_components/universal_room_automation/switch.py:206-278` | Drop `device_name`/`device_model` kwargs from 7 registrations; route DeviceInfo through `_coordinator_device_info` | ~-40 |
| `custom_components/universal_room_automation/switch.py:~5708` | Import + call `_music_following_device_info` | ~-10 |
| `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:~667` | Import + call `_nm_device_info` | ~-5 |
| `custom_components/universal_room_automation/button.py:~1864` | Delete `_optimizer_device_info_button`; import from `_devices.py` | ~-10 |
| `custom_components/universal_room_automation/aggregation.py:~3660` | Update stale via_device comment | ~2 |
| Entity files (D5 fixes) | Set `_attr_has_entity_name` / `_attr_name` where missing | ~10 |
| `quality/tests/test_device_entity_architecture.py` (NEW) | D0-loader + D1-D6 tests | ~500 |
| `docs/readmes/README_v<next>.md` | Release notes + Validated tables per deliverable + device-tree screenshot + D1 discriminator table with observed values | ~80 |

---

## Tier 2 review framings (two, parallel, framing-disjoint)

- **Reviewer A — Correctness + D1 preservation.** Verify the D0 probe
  fixture is the migration set (independently re-enumerate coordinator
  device entities registered on INTEGRATION-branch platform setups —
  do NOT trust the plan's list). Verify every migration-target entity's
  unique_id is stable under the entry-swap (read each entity's
  `__init__` and any `_attr_unique_id` computation). Verify D1 tests
  actually diff against the D0 CSV fixture (hollow anchor check: a
  test that hard-codes the migration set independently defeats the
  purpose). Verify INV-1's `_2`-mint check is executed against a real
  entity-registry state, not a mock.
- **Reviewer B — HA lifecycle + reload-suppress integrity +
  signal-chain + parent-map completeness.** Verify
  `async_update_device(..., via_device_id=...)` exists in the target HA
  version (cite `homeassistant/helpers/device_registry.py` line — no
  fabrication). Verify D-NEST placement is after
  `async_forward_entry_setups` on every entry type. Verify D6
  non-hollow (sibling `last_changed`, not patched `async_reload`).
  Verify no untracked-listener leak from any new subscription (Bug
  Class #38). Independently re-enumerate the D-NEST parent map against
  the live device registry — a missing coordinator identifier orphans
  a device in the tree.

**Pre-review baseline tag mandatory:**
`git tag pre-review-v<version> -m "Pre-review baseline"` before
applying any review fix-ups.

**Orchestrator registry-verify (pre-deploy, MANDATORY for D1):**
Independent of the reviewers, the orchestrator personally re-runs the
D0 probe against the pre-deploy state and diffs it against the D0
committed fixture; then runs the D1 test suite; then confirms the
`_migrate_entity_unique_id` hook (if any) is wired in the CM
`async_setup_entry` BEFORE the platform forward. If any migration-target
unique_id is not reproducibly stable, HALT the deploy.

**Live-validation (post-deploy):** ura-validator runs the D0 probe
against the live registry, produces the discriminator table for the
README write-back, and confirms INV-1 through INV-6. **Cycle is NOT
closed** until the README carries the observed discriminator table
(per the standing README write-back rule).

---

## Explicit deferrals

- **Zone→Rooms nesting** — `DEVICE-ZONE-ROOM-NEST-1`.
- **Person device** — `PERSON-DEVICE-1`.
- **CONFIG-SUBENTRIES-MIGRATION-1** — separate parked cycle.
- **PLANNING_setup_unload_symmetry.md** — separate.
- **ENTITYDESC-RUNTIMEDATA-HYGIENE-1** — parked; fold in next cycle.
- **Entity_id / unique_id renames** — permanently OUT.

## Operator decisions

**None outstanding.** D4 baked as Option 3; tier baked as 2 with
elevated D1 gate; scope frozen at the deliverables above.
