# PLANNING — Device / Entity Architecture Cleanup for HA 2026.9

**Card:** `DEVICE-ENTITY-ARCH-2026-9-1`
**Date:** 2026-09-03
**Author:** ura-planner
**Precursor ship:** `v5.92.3` — stripped 109 `via_device=` declarations to
unblock the HA 2026.9 `DeviceInfo.via_device` breaking change. This un-nested
every URA coordinator/zone/room device on the HA device page (they now sit as
peers of the integration device instead of nested under it). This cycle
restores nesting via the durable `device_registry.async_update_device(
device_id, via_device_id=...)` path AND cleans up the pre-existing device
authorship divergences that the strip exposed.

**Tier:** **2-DB** (three framing-disjoint reviews) — operator-elevatable to
Tier 3 if the naming-convention decision (D4) triggers entity_id churn. Justification: this
cycle touches every entity platform file (`sensor.py`, `switch.py`,
`number.py`, `button.py`, `binary_sensor.py`, `select.py`, `time.py`,
`aggregation.py`, `entity.py`, `domain_coordinators/base.py`,
`domain_coordinators/notification_manager.py`), mutates the shared
device-registry write path, and interacts with the
`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` primitive (parent-entry-reload
watchdog hazard, memory
`feedback_parent_entry_reload_watchdog_hazard.md`). Regression-prone by every
Tier-2-DB standing criterion (feedback `tier2db_for_regression_prone`).

**Plan-review-before-build:** MANDATORY (Tier-2/2-DB standing rule). Reviewer
must independently re-enumerate: every `DeviceInfo(` call site (verified 143
today across 12 files); every `_*_device_info()` helper; every
`identifiers=` literal; and every concrete `Entity` subclass to close the
`has_entity_name` audit. The device-tree parent-map (D1) is the load-bearing
hypothesis.

**Operator checkpoint:** BEFORE build starts, operator picks one option from
`§ D4 — Naming-convention options` below. Everything downstream of D4 (the
canonical device names / models stamped by D2, and any entity friendly-name
implications from `has_entity_name`) resolves against the chosen option.

---

## SCOPE

**IN:**
- Restore device-tree nesting under 2026.9 via `dr.async_update_device(...,
  via_device_id=...)` after device creation (D1).
- Kill inline `DeviceInfo(...)` literals in favor of the single per-device
  helper (D2). Priority: music-following (3 sites) and notification_manager
  (3 sites).
- Fix the model-string first-writer-wins race between
  `domain_coordinators/base.py:200-208` and the sensor.py per-coordinator
  helpers (D3).
- Pick and stamp ONE naming convention across integration / coordinator /
  zone / room devices (D4 — operator decides).
- `has_entity_name` per-concrete-entity audit (D5).
- Reload-safety: the device-registry updates in D1/D2 must NOT require a
  parent-entry reload (D6).

**OUT (non-goals — do NOT expand into these):**
- The flat→subentries migration (`CONFIG-SUBENTRIES-MIGRATION-1`) — separate
  parked cycle.
- The setup/unload symmetry hotfix (separate
  `PLANNING_setup_unload_symmetry.md`).
- Actual entity_id / unique_id renames (would churn history; forbidden by AC).
- **ENTITYDESC-RUNTIMEDATA-HYGIENE-1**: opportunistic-fold NON-goal for this
  cycle. Rationale: this plan already touches every entity platform, so the
  temptation is real; but the SwitchEntityDescription / runtime-data hygiene
  is a distinct axis (entity metadata authoring style, not device authoring)
  and folding it doubles the diff surface and the reviewer surface. Ship this
  cycle first; the follow-up card runs against the tidied device authorship.

**Parsimony ledger:** +0 new CONF_*; +0 new sensors; +0 new signals; +1 new
setup hook (device-parenting stamper, D1); refactor-only diff to helpers
(D2/D3); +1 naming-convention constants block (D4); audit-and-annotate for
D5.

---

## Institutional context verified

### Greps run + results

| Question | Command | Result |
|---|---|---|
| `via_device=` residual after v5.92.3 strip? | `grep -rn via_device custom_components/universal_room_automation` | **1 hit — comment only** (`aggregation.py:3660` explains "No via_device needed"). Strip is effectively complete; there is no DeviceInfo-arg residual to catch. **CONFIRMED.** |
| `_*_device_info()` helpers in the tree | `grep -rn 'def _\w+_device_info' custom_components/universal_room_automation` | **10 helpers**: `_optimizer_device_info_button` (button.py:1864), `_nm_device_info` (number.py:3598 — nested in `_NMDeviceInfoMixin`), `_safety_device_info` (sensor.py:6254), `_security_device_info` (:6645), `_music_following_device_info` (:7352), `_nm_device_info` (:7791 — SECOND definition, module-level), `_energy_device_info` (:8328), `_hvac_device_info` (:11576), `_cm_device_info` (:14962), `_optimizer_device_info` (:16560). Presence coordinator has NO helper — inline literals in `domain_coordinators/presence.py`. Missing helpers for `music_following_coordinator` outside sensor.py (switch.py uses inline). |
| `DeviceInfo(` call sites (needle for inline literals) | `grep -c 'DeviceInfo('` | **143 total across 12 files**: sensor.py:30, binary_sensor.py:19, switch.py:35, number.py:28, select.py:10, button.py:14, time.py:1, entity.py:1, aggregation.py:2, base.py:1, manager.py:1, notification_manager.py:1. This is the working set for the D2 audit. |
| `has_entity_name` occurrences | `grep -c 'has_entity_name'` | **80+ across 10 code files** (excluding `frontend-v3/*.js` artifact). Base classes: `entity.py:22` (URAEntity), `aggregation.py:733` (AggregationEntity), `switch.py:608` (CoordinatorEnabledSwitch). Many concrete classes set it explicitly (`switch.py:5687` MFPersonFollowSwitch). Full per-class enumeration is a D5 deliverable, not a plan-time claim. |

### For each proposed addition — REUSED vs NEW

- **D1 setup hook to stamp `via_device_id` post-creation** → **NEW**. No
  equivalent exists. The closest precedent is the area-stamping in
  `entity.py:69-98`, which stamps a **different** DeviceEntry field
  (`area_id`) on the room device only. This cycle stamps `via_device_id`
  across ALL URA-authored devices. Justification: HA 2026.9 removed the
  `DeviceInfo.via_device` kwarg; the runtime-update path
  (`dr.async_update_device(device_id, via_device_id=<parent_device_id>)`)
  is the sanctioned replacement. **PRECEDENT REUSED**: exactly the
  post-creation `async_update_device` pattern of `entity.py:88-89`.
- **D2 helper routing** → **REUSED**. All 10 `_*_device_info()` helpers
  already exist; this deliverable is a diff-only refactor to route every
  in-file inline `DeviceInfo(...)` call through the local helper. **NEW**:
  a helper for `music_following_coordinator` accessible from `switch.py`
  (today it's only in `sensor.py:7352`; `switch.py:5708` duplicates the
  literal). Options: (a) move helper to a small shared module,
  (b) import the sensor.py helper into switch.py. Recommendation: (a) —
  new `_devices.py` module holds all 10 helpers + the naming constants
  from D4.
- **D3 canonical (name, model, manufacturer, sw_version) per identity**
  → **REUSED** — enforced by centralizing helpers per D2. No new state.
- **D4 naming-convention constants** → **NEW**. String literals today
  scattered across ~20 call sites; consolidate into a constants block in
  `_devices.py` (module from D2). Justification: no existing constants
  cover device NAMES (`const.MODEL` covers the model string for rooms
  only, per convention).
- **D6 reload-suppress interaction** → **REUSED**. Device-registry writes
  do not trip the `_async_update_listener` reload path — they touch the
  device registry, not `entry.options`. **VERIFY at build time** with a
  reload-absence test analogous to
  `test_face_matching_toggle_does_not_reload_parent_entry` from
  `PLANNING_census_toggles_to_device_switches.md`.

### Prior planning docs consulted

- `docs/planning/PLANNING_census_toggles_to_device_switches.md` (v5.81+
  device-switches cycle) — LOAD-BEARING precedent for the
  reload-suppression discipline any device-registry-adjacent write must
  respect. Reused: (i) sibling-`last_changed`-invariant test technique for
  proving no parent-entry reload occurred (D6 AC); (ii) INTEGRATION-entry
  device authoring pattern (`identifiers={(DOMAIN, "integration")}`).
- `docs/planning/PLANNING_setup_unload_symmetry.md` — adjacent cycle;
  explicit non-goal here (avoids two structural refactors in one deploy).

### Memory bodies pulled

- `feedback_parent_entry_reload_watchdog_hazard.md` — the 2026-06-03 /
  2026-08-07 outages. This cycle MUST NOT reintroduce the reload hazard.
- `feedback_suppression_needs_discharge.md` — governs D6.
- `feedback_hollow_test_anchors.md` — D5 tests must drill by detaching the
  value (a `has_entity_name` regression should be caught by adding a
  concrete entity that violates the invariant AND observing the HA log
  guard "Error adding entity None", NOT by grepping the class body).
- `feedback_no_fabrication.md` — HA `device_registry.async_update_device`
  behavior (does it accept `via_device_id` today? does it break existing
  device rows if a via chain contains a stale identifier?) MUST be
  verified in HA source at build time, not asserted from memory. Planner
  has NOT re-read `homeassistant/helpers/device_registry.py` this session;
  the builder does so and cites file:line before writing D1.
- `feedback_read_consumers_before_asserting_function.md` — every
  `_*_device_info()` helper's consumers must be enumerated before D2
  refactor; NM has two helpers (module-level and mixin) — read both
  consumer sets, do not assume equivalence from name.

### Design docs read

- `docs/QUALITY_CONTEXT.md` — bug classes: #7 stale-data-source (device
  identity written from two sites with divergent values), #22 enum
  mismatch (the model-string race in D3 is a direct instance).

### Code locations surveyed end-to-end

- `custom_components/universal_room_automation/entity.py:1-99` (area-stamp
  precedent, has_entity_name base).
- `custom_components/universal_room_automation/aggregation.py:720-760`
  (integration-device DeviceInfo authoring; has_entity_name base).
- `custom_components/universal_room_automation/domain_coordinators/base.py:190-210`
  (the model-string race source — "Domain Coordinator" for every
  `{id}_coordinator` identifier).
- `custom_components/universal_room_automation/sensor.py` — 10 helper
  sites read (`:6254`, `:6645`, `:7352`, `:7791`, `:8328`, `:11576`,
  `:14962`, `:16560`) + surrounding class bodies.
- `custom_components/universal_room_automation/switch.py:200-670` (7 x
  `CoordinatorEnabledSwitch` registrations at :206-269, class def :598,
  inline DeviceInfo :633), `:5680-5720` (MFPersonFollowSwitch inline
  literal — v5.10.0 double-prefix bug comment at :5702-5706 is the
  institutional receipt for why divergence hurts).
- `custom_components/universal_room_automation/number.py:3590-3610`
  (`_NMDeviceInfoMixin`).
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:660-675`
  (third NM authoring site).
- `custom_components/universal_room_automation/button.py:1860-1870`
  (`_optimizer_device_info_button` — parallel to sensor.py's optimizer
  helper; verify at build that they emit identical (name, model,
  manufacturer, sw_version)).
- `__init__.py:5905-6675` — reload-suppress infrastructure (D6 must not
  interact with this negatively).

---

## Falsifiable invariants

**INV-A (D1 nesting):** For every URA-authored DeviceEntry other than the
integration root, `device.via_device_id` resolves (via `dr.async_get`) to
the id of the DEVICE the D4 mapping assigns as its parent — verified by a
device-registry walk post-boot. Under a plausible alternative (D1 fails to
run for some devices), a random-order registry walk would find at least
one URA device with `via_device_id is None` that is not the integration
root. **Discriminator:** count of URA devices with unresolved parents
equals 0.

**INV-B (D2 single-source-of-truth):** For every device identity
`(DOMAIN, X)`, the (name, model, manufacturer, sw_version) tuple is
stamped from EXACTLY ONE code path across the codebase. Falsifier: grep
for `identifiers={(DOMAIN, "<id>")}` returns exactly one enclosing
function per id, and that function is the canonical helper. A cheap
in-suite oracle enumerates the identifier→helper map.

**INV-C (D3 no-race model):** For any `{coord}_coordinator` identifier,
`domain_coordinators/base.py:device_info` returns a DeviceInfo whose
`(name, model)` equals the sensor.py helper's `(name, model)` for the
same identifier. Falsifier: unit test builds both, asserts equality per
identifier. **The v5.92.3-shipped code fails this test today** —
base.py:206 emits `model="Domain Coordinator"` for every coordinator
whereas sensor.py helpers emit specific models ("Energy Coordinator",
etc.). The fix routes base.py through the same shared helper OR removes
the base.py property entirely if no consumer needs it.

**INV-D (D5 has_entity_name):** Every concrete `Entity` subclass in the
integration either sets `_attr_has_entity_name = True` OR sets
`_attr_name` to a non-None value (or `_attr_translation_key` — but URA
does not use translations today). Falsifier: an entity that resolves to
`(has_entity_name unset OR False) AND name is None` — HA 2026.9 logs
"Error adding entity None" and drops it. Zero such entities in the boot
log is the discriminator.

**INV-E (D6 no reload):** Applying the D1 stamper on integration setup
does NOT trigger `_async_update_listener` and does NOT invoke
`async_reload` on any config entry. Falsifier: sibling entity's
`last_changed` timestamp bumps across the D1 stamp window. Discriminator
is the same technique used in the census-toggles cycle's D3 AC.

---

## Deliverables

### D1 — Restore device nesting under 2026.9 (device-registry stamper)

**Design.** After the integration and all child entries have completed
platform setup, walk the device registry for entries owned by URA and
stamp each device's `via_device_id` to the DeviceEntry.id of the parent
device dictated by the parent-map (below). Do **NOT** re-add
`via_device=(DOMAIN, ...)` to any `DeviceInfo(...)` call — that path is
removed in 2026.9.

**Parent map (subject to D4 confirmation of names; identifiers are
stable):**

| Child identifier | Parent identifier | Rationale |
|---|---|---|
| `(DOMAIN, "coordinator_manager")` | `(DOMAIN, "integration")` | CM is the roof of the coordinator subtree. |
| `(DOMAIN, "<coord>_coordinator")` for each of safety, security, presence, energy, hvac, optimization, notification_manager, music_following | `(DOMAIN, "coordinator_manager")` | Restores pre-v5.92.3 nesting. |
| `(DOMAIN, "zone_<n>")` for each zone | `(DOMAIN, "integration")` (default) | Zones are house-scoped, not coordinator-scoped. Alternative: nest under a new "Zones" grouping device — carded, not built here. |
| `(DOMAIN, "<entry_id>")` for each room | `(DOMAIN, "integration")` (default) | Rooms are house-scoped. Room→Zone nesting requires a new zone→rooms mapping surface — non-goal. |
| `(DOMAIN, "integration")` | (self / root) | No parent. |

**Where the stamper runs.** New coroutine `async_stamp_via_device_tree(
hass)` in a new module `custom_components/universal_room_automation/_devices.py`. Called
from `async_setup_entry` of the integration entry **AFTER** all platforms
have completed forwarding (i.e. after
`hass.config_entries.async_forward_entry_setups(...)` awaits) AND from
each room / zone entry's `async_setup_entry` in the same position, so a
late-arriving child re-stamps itself. Guarded by
`hass.data[DOMAIN]["device_tree_stamped"]` per (entry_id, run_id) so the
walk is at-most-once per setup.

**Algorithm.**
```
for each URA-owned device in registry (filter by identifiers[0][0] == DOMAIN):
    parent_identifier = PARENT_MAP.get(device.identifiers)  # deterministic
    if parent_identifier is None:  # integration root
        continue
    parent_device = dev_reg.async_get_device(identifiers={parent_identifier})
    if parent_device is None:
        # Parent not yet registered (platform not loaded). Log and skip;
        # this pass will retry on next child entry's setup.
        continue
    if device.via_device_id == parent_device.id:
        continue  # already correct
    dev_reg.async_update_device(device.id, via_device_id=parent_device.id)
```

**Restart & re-add resilience.** The stamper is idempotent (early-return
on match). On device removal + re-add (HA restart with cleared registry),
the next stamper pass restores nesting.

**Kill switch.** Module-constant `URA_DEVICE_TREE_STAMPING_ENABLED:
Final = True` in `_devices.py`. Flip False to disable if a 2026.9-later
HA change breaks `async_update_device(via_device_id=...)`.

### Acceptance Criteria — D1

- **Verify:** Post-boot device-registry walk shows every URA device other
  than `(DOMAIN, "integration")` has non-None `via_device_id` resolving
  to the parent per the map. (INV-A discriminator.)
- **Verify:** HA UI device page nests coordinators under Coordinator
  Manager; CM nests under Universal Room Automation; zones and rooms are
  children of the integration.
- **Sensor:** No new sensor introduced; verification via `dr.async_get`
  directly in-test.
- **Test:** `test_via_device_stamper_stamps_all_ura_devices` — construct
  a fake device registry with URA devices at each level, run
  `async_stamp_via_device_tree`, assert every device's `via_device_id`
  matches the parent map.
- **Test:** `test_via_device_stamper_idempotent` — run twice, assert
  second run performs zero writes (mock `async_update_device` and count
  calls).
- **Test:** `test_via_device_stamper_skips_when_parent_not_yet_registered`
  — remove CM device; run stamper; assert children with parent=CM are
  skipped (not errored) and integration-parented devices are still
  stamped.
- **Live:** On the running HA instance post-deploy, open the URA
  integration device page and confirm the nested tree matches D4-chosen
  labels; take a snapshot of the device tree and paste into the release
  README's Validated table.

### D2 — Single source of truth per device

**Design.** Every entity that lives on a non-room, non-zone URA device
gets its `_attr_device_info` from ONE canonical helper per device
identity. All 10 existing helpers move to `_devices.py` (from D1) so
platforms can import a single symbol. The `_NMDeviceInfoMixin` (number.py:3596)
and the module-level `_nm_device_info` (sensor.py:7791) collapse into ONE
`_nm_device_info()` in `_devices.py`. The `_music_following_device_info`
(sensor.py:7352) becomes importable from `switch.py:5708`.

**Priority replacements (verified inline literals to eliminate):**

| Site | Current | Replace with |
|---|---|---|
| `switch.py:5708` (MFPersonFollowSwitch.__init__) | Inline literal identical to `_music_following_device_info()` | Import + call the helper |
| `switch.py:633` (CoordinatorEnabledSwitch.__init__) | Builds inline using per-instance `device_id`/`device_name`/`device_model` kwargs from `switch.py:206-269` (7 registrations) | Route through a `_coordinator_device_info(coordinator_id)` helper in `_devices.py` that returns the same DeviceInfo the sensor.py helpers do. Delete the `device_name`/`device_model` kwargs from the 7 call sites — the helper is the sole authority. |
| `notification_manager.py:667` | 3rd NM authoring site | Import `_nm_device_info` from `_devices.py` |
| `number.py:3596-3606` `_NMDeviceInfoMixin` | 2nd NM authoring site | Delete mixin; entities use module-imported helper |
| `sensor.py:7791` | Duplicate NM helper | Delete; import from `_devices.py` |
| Any of the 143 `DeviceInfo(` call sites whose identifier maps to one of the 10 canonical devices | Inline | Route through helper |

**Deferred inline literals (out of scope):**
- Room DeviceInfo in `entity.py:38-44` — stays, room device identity is
  intrinsically per-entry.
- Zone DeviceInfo in `aggregation.py:3662` (via_device comment context)
  — stays if per-zone; audit at build time to confirm.
- Integration DeviceInfo in `aggregation.py:736-742` — stays, sole author.

### Acceptance Criteria — D2

- **Verify:** For each of the 10 canonical device identities, grep for
  `identifiers={(DOMAIN, "<id>")}` returns hits ONLY inside the
  canonical helper in `_devices.py` (integration, room, zone identifiers
  excepted per above).
- **Verify:** `switch.py` no longer imports `DeviceInfo` OR imports it
  only for room/zone helpers if any remain (grep line count drops).
- **Verify:** `music_following_coordinator` device appears as ONE
  DeviceEntry in the registry (INV-B discriminator; the v5.10.0
  double-prefix incident was the negative case).
- **Verify:** `notification_manager` device appears as ONE DeviceEntry;
  no ghost "URA: Notification Manager" duplicate on the device page.
- **Test:** `test_device_identity_has_single_author` — parse the URA
  package source; for each canonical id in a hand-built fixture,
  assert exactly one `DeviceInfo(identifiers={(DOMAIN, id)}, ...)` AST
  node exists in the codebase.
- **Test:** `test_mf_person_follow_switch_shares_music_following_device`
  — construct MFPersonFollowSwitch + `MusicFollowingHealthSensor`;
  assert `.device_info["identifiers"]` and all four canonical fields
  match.
- **Test:** `test_nm_number_and_sensor_share_nm_device` — same shape for
  NM number and NM sensor.
- **Live:** On the running HA instance, navigate to the Music Following
  Coordinator device page; confirm ALL music-following entities (health
  sensor, diagnostic sensors, per-person follow switches, NM prefs
  numbers where applicable) are listed under that ONE device.

### D3 — Fix model-string first-writer-wins race

**Cause.** `domain_coordinators/base.py:200-208` returns
`DeviceInfo(identifiers={(DOMAIN, f"{coordinator_id}_coordinator")},
model="Domain Coordinator", ...)`. The sensor.py helpers (e.g.
`_energy_device_info` at :8328) return `model="Energy Coordinator"` for
the SAME identifier `(DOMAIN, "energy_coordinator")`. Per HA device
registry semantics, whichever DeviceInfo is materialized first wins the
model field; subsequent identical-identifier registrations update it
(and vice versa on the next boot). Sightings today are inconsistent per
boot order.

**Fix.** Route `BaseCoordinator.device_info` (base.py:200) through the
same canonical helper set in `_devices.py`. Introduce
`_coordinator_device_info(coordinator_id: str) -> DeviceInfo` in
`_devices.py` that dispatches to the correct per-coordinator helper (or
holds the canonical table inline). Every consumer of
`BaseCoordinator.device_info` gets the specific model; the generic
"Domain Coordinator" string is deleted.

**Backwards-compat.** HA will `async_update_device` the model field on
first stamped boot; no manual data migration.

### Acceptance Criteria — D3

- **Verify:** `grep -n '"Domain Coordinator"' custom_components/` returns
  zero hits.
- **Test:** `test_base_coordinator_device_info_matches_sensor_helper`
  (INV-C oracle) — for each coordinator_id in a fixture list, assert
  `BaseCoordinator(...).device_info` equals
  `_devices._<coord>_device_info()` on all four canonical fields.
- **Live:** On the running HA instance, each coordinator's device page
  shows the SPECIFIC model string (e.g. "Energy Coordinator"), not
  "Domain Coordinator".

### D4 — Naming convention decision (OPERATOR PICKS)

**Current schemes** (verified):
- Integration device: name `"Universal Room Automation"`, model `"Whole
  House"` (aggregation.py:738-740).
- Coordinator devices: name `"URA: <X> Coordinator"`, model `"<X>
  Coordinator"` (sensor.py helpers) OR `"Domain Coordinator"` (base.py —
  see D3).
- Coordinator Manager: name `"URA: Coordinator Manager"`, model
  `"Coordinator Manager"` (sensor.py:14966-14971).
- Zones: name `"Zone: <X>"` per aggregation.py:3662 (verify at build).
- Rooms: name `<room_name>` (bare), model `const.MODEL` — nominally
  `"Smart Room"` per prompt; verify against `const.py` at build.

**Options for operator to pick:**

- **Option 1 — Keep current, no rename.** Purely cosmetic
  inconsistency. Coordinator names retain `"URA: "` prefix; house device
  stays `"Universal Room Automation"`; zones `"Zone: "`; rooms bare.
  Grouping in HA UI is by `via_device_id` (D1). Operator wanted
  coordinator menus distinct from house menus — satisfied by D1 nesting,
  not by rename.
  - **Pros:** zero name-string diff; zero entity friendly-name churn
    (has_entity_name True + device name change would ripple into every
    entity's rendered name).
  - **Cons:** inconsistency persists as a documentation smell.
- **Option 2 — Uniform `"URA: "` prefix everywhere.** Integration
  becomes `"URA: Home"` (model `"Whole House"`), zones `"URA: Zone
  <X>"`, rooms `"URA: <room_name>"`.
  - **Pros:** consistent branding; all URA devices sort together in the
    HA device list.
  - **Cons:** ripples into every entity friendly name via
    `has_entity_name=True` composition. Real churn for the operator to
    re-scan. Room-name change is the largest surface.
- **Option 3 — Section prefix instead of `"URA: "`.** Coordinator
  section named `"Coordinators"` (via CM at `"Coordinator Manager"`,
  children `"Safety"`, `"Security"`, etc. — no prefix). House stays
  `"Universal Room Automation"`. Zones `"Zone <X>"`. Rooms bare.
  Distinguishes menus by hierarchy + name, not prefix.
  - **Pros:** clean UI hierarchy, minimal room-name churn, operator's
    coordinator-vs-house distinction shows up structurally.
  - **Cons:** coordinator entity friendly names lose their `"URA: "`
    breadcrumb.

**Recommendation for operator consideration:** **Option 3**. It solves
the coordinator-menu-vs-house-menu ask via structure (which is
observable in the HA UI today, once D1 restores nesting), while
minimizing entity-friendly-name churn (rooms unaffected). Option 1 is
the zero-risk fallback.

### Acceptance Criteria — D4

- **Verify:** After operator picks, `_devices.py` contains a
  `DEVICE_NAMES` and `DEVICE_MODELS` mapping that all D2 helpers
  consult; grep for the OLD strings returns only comments / release
  notes.
- **Test:** `test_device_naming_convention_applied` — for each
  identifier in the fixture, assert helper returns the chosen-option
  name/model.
- **Live:** HA UI device list matches the chosen option; screenshot
  pasted into README.

### D5 — has_entity_name per-concrete-entity audit

**Method.** Enumerate every concrete `Entity` subclass in the URA
package (sensor.py, switch.py, number.py, button.py, binary_sensor.py,
select.py, time.py, aggregation.py, notification_manager.py). For each,
compute:
- `has_entity_name` resolution: does the class or any base set
  `_attr_has_entity_name = True`?
- `name` resolution: is `_attr_name` set to a non-None value in
  `__init__` OR is `name` overridden as a non-None property?

An entity that ends up with `has_entity_name unset/False AND name is
None` is a 2026.9 rejection target ("Error adding entity None").

**Deliverable.** A per-class table in the review doc AND source-level
annotations for any class that needs a fix. Base-class coverage
(`URAEntity` at entity.py:22, `AggregationEntity` at aggregation.py:733,
`CoordinatorEnabledSwitch` at switch.py:608) covers most; the audit
proves it, and fixes stragglers.

### Acceptance Criteria — D5

- **Verify:** The audit table lives in
  `docs/reviews/code-review/v<version>_device_entity_arch_review.md` and
  covers every concrete Entity subclass.
- **Test:** `test_no_entity_resolves_to_none_name` — attempt to
  construct every concrete Entity subclass with minimal fixtures; assert
  none produce `name is None AND not has_entity_name`. (Test may skip
  subclasses whose constructors demand a fully-set-up runtime; annotate
  the skip list explicitly.)
- **Live:** Boot log post-restart shows ZERO occurrences of the HA
  guard string `"Error adding entity None"` from the URA integration.
  Grep the journalctl core log for the deploy timestamp window.

### D6 — Reload safety (no parent-entry reload)

**Guarantee.** The D1 stamper writes to the device registry only. It
does NOT touch `entry.options`, so it does NOT enter
`_async_update_listener` (`__init__.py:6434`) and does NOT trip the
allowlist / reload branch. This is a passive property of the design,
not a mitigation; the AC pins it as an invariant so a future refactor
that adds an options write in the stamper would fail the test.

**Where the census-toggles precedent DOES apply.** If, during
implementation, D2 or D4 requires persisting a chosen device-name into
`entry.options` (it should NOT — the names are code constants), that
key MUST land in `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`
(`__init__.py:5929`) with an entry in `_INTEGRATION_KEY_SIGNAL_TABLE`
per `feedback_suppression_needs_discharge`. Planner's judgment: not
needed.

### Acceptance Criteria — D6

- **Test:** `test_device_tree_stamper_does_not_reload_parent_entry`
  (non-hollow) — record a sibling entity's `last_changed`; run the
  stamper on a fresh setup; assert the sibling's `last_changed` did NOT
  advance across the stamp window. Do NOT patch `async_reload`.
- **Test:** `test_device_tree_stamper_does_not_write_entry_options` —
  mock `hass.config_entries.async_update_entry`; run stamper; assert
  zero calls.
- **Verify:** grep in `_devices.py` returns zero
  `async_update_entry(` occurrences.
- **Live:** Post-deploy, `journalctl -u home-assistant --since` for the
  deploy window shows the URA integration setup completes without any
  "reloading" log line other than the code-deploy reload itself; no
  supervisor-watchdog restart in the 30 minutes post-deploy.

---

## Files changed (planned)

| File | Change | Approx LoC |
|---|---|---|
| `custom_components/universal_room_automation/_devices.py` (NEW) | 10 canonical `_*_device_info()` helpers moved here; `_coordinator_device_info(coordinator_id)` dispatcher; naming constants per D4; `async_stamp_via_device_tree(hass)` (D1); `URA_DEVICE_TREE_STAMPING_ENABLED` kill switch | ~250 |
| `custom_components/universal_room_automation/__init__.py` | Import + call `async_stamp_via_device_tree` in integration `async_setup_entry` + each entry-type setup post-forward | ~20 |
| `custom_components/universal_room_automation/domain_coordinators/base.py:200-208` | Route through `_devices._coordinator_device_info(self.coordinator_id)`; delete generic "Domain Coordinator" model | ~10 |
| `custom_components/universal_room_automation/sensor.py` | Delete duplicate `_nm_device_info` (:7791) and each other helper's body; keep thin re-exports if any consumers import by dotted path | ~-80 |
| `custom_components/universal_room_automation/number.py:3596-3606` | Delete `_NMDeviceInfoMixin`; entities use imported helper | ~-15 |
| `custom_components/universal_room_automation/switch.py` | Delete inline `DeviceInfo(` at :633 (route through `_coordinator_device_info`), :5708 (route through `_music_following_device_info`), and any other coordinator-device inline literals; drop `device_name`/`device_model` kwargs from the 7 `CoordinatorEnabledSwitch` registrations at :206-269 | ~-50 |
| `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:667` | Route through imported `_nm_device_info` | ~-5 |
| `custom_components/universal_room_automation/button.py:1864` | Delete `_optimizer_device_info_button`; import from `_devices.py` | ~-10 |
| `custom_components/universal_room_automation/aggregation.py:3660` | Update stale via_device comment to reference D1 stamper | ~2 |
| Entity files (audit fixes from D5) | Set `_attr_has_entity_name` / `_attr_name` where missing | ~10 |
| `quality/tests/test_device_entity_architecture.py` (NEW) | D1–D6 tests | ~400 |
| `docs/readmes/README_v<next>.md` | Standard release notes; Validated table for D1/D2/D3/D4/D5/D6; device-tree screenshot | ~60 |

---

## Tier 2-DB review framings (three, parallel, framing-disjoint)

- **Reviewer A — correctness + INV-A/INV-B/INV-C discrimination.** Verify
  the parent map is complete (re-enumerate URA identifiers independently
  from the registry, do not trust the map in the plan); verify D2 leaves
  exactly one author per identifier (AST oracle, not grep alone); verify
  D3 test asserts field equality per coordinator_id.
- **Reviewer B — HA lifecycle + reload-suppress integrity + signal chain.**
  Verify `async_update_device(..., via_device_id=...)` is a supported HA
  call on the target HA version (cite `homeassistant/helpers/device_registry.py`
  line); verify the stamper's placement is after
  `async_forward_entry_setups` so all platforms have registered their
  devices; verify D6 non-hollow (sibling `last_changed` invariant, not
  patched `async_reload`); verify no untracked-listener leak from any
  new subscription (Bug Class #38).
- **Reviewer C — new surfaces + test authority + naming convention
  application.** Verify D4 chosen option is stamped uniformly (no legacy
  strings survive except in comments); verify entity friendly-name
  churn (or lack thereof) matches the D4 pros/cons; verify D5 audit
  table is complete and the "Error adding entity None" grep is the
  discriminator; verify tests drive production code paths (real
  DeviceInfo objects through real helpers, not hand-built fixtures that
  paraphrase the helper).

**Pre-review baseline tag mandatory:** `git tag pre-review-v<version>
-m "Pre-review baseline"` before applying any review fix-ups.

---

## Explicit deferrals

- **Zone→Rooms nesting** (rooms as `via_device` children of their
  zone). Requires a zone→rooms mapping surface. Card: `DEVICE-ZONE-ROOM-NEST-1`.
- **Person device** (MFPersonFollowSwitch comment at switch.py:5683-5684
  flags a future migration to a per-Person device). Card:
  `PERSON-DEVICE-1`.
- **CONFIG-SUBENTRIES-MIGRATION-1** — separate parked cycle.
- **PLANNING_setup_unload_symmetry.md** — separate.
- **ENTITYDESC-RUNTIMEDATA-HYGIENE-1** — parked with trigger: fold in
  the cycle after this one lands, against the tidied device authorship.
- **Entity_id / unique_id renames** — permanently OUT of scope for this
  cycle (churn hazard).

---

## Operator decisions required BEFORE build dispatch

1. **D4 naming-convention option**: 1 (keep), 2 (uniform "URA: " prefix),
   or 3 (structural / recommended).
2. **Zones parent**: integration root (default) OR a new "URA Zones"
   grouping device (would require a small +1 identifier — flagged NEW).
3. **Rooms parent**: integration root (default) OR their zone (deferred
   to `DEVICE-ZONE-ROOM-NEST-1`; confirm defer).
4. **Tier escalation**: stay 2-DB, or elevate to Tier 3 given D4 could
   trigger user-facing name churn?
