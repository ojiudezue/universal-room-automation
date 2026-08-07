# PLANNING — TRANSIT-1: Protect-sourced checkpoint inventory for transit_validator

**Kanban:** TRANSIT-1 (`docs/planning/kanban.data.yaml` L129-146) · **Thread:** presence
**Date:** 2026-08-07 · **Author:** ura-planner
**Ground-truth fixture:** `docs/planning/AUDIT_resolver_ground_truth_manual.md` (RESACC-1)
**Prerequisite (done this session):** 39 camera-registry area corrections landed —
all 5 physical traversal cameras (`master_hallway`, `foyer_fisheye`, `staircase`,
`upstairs_hall`, `stairs_top`) carry the correct interior area on the Protect
(and where present, Frigate) entity. Resolver area-attribution is therefore now
reliable for these cameras — the enabler for this cycle.

---

## 1. Problem statement (falsifiable)

The `TransitValidator` interior checkpoint inventory is fed from
`CONF_CAMERA_PERSON_ENTITIES` — a hand-maintained 9-entry list at the integration
config entry. Against the operator's real 5 traversal checkpoints, this yields:

| Checkpoint room | Physical camera | In hand-list? | Produces usable room-attributed signal? |
|---|---|---|---|
| garage_hallway | staircase | yes | YES (only working one) |
| master_hallway | master_hallway | yes | NO (no fused sensor path) |
| entry_way (foyer) | foyer_fisheye | yes | NO (no fused sensor path) |
| upstairs_hallway | upstairs_hall | **NO** | NO |
| stairs | stairs_top | **NO** | NO |

Two failure modes stack: (a) the hand-list has DRIFTED (2 of 5 cameras missing),
and (b) even for cameras that are listed, the code path only produces a
room-attributed signal when a per-room fused sensor exists — which these
transition-zone areas do NOT have (they are not URA rooms; no coordinator, no
D3 sensor).

**Invariant this cycle must guarantee (Tier-3 style, for D-framing):**

> Every physical camera whose UniFi Protect device carries an `area_id`
> matching a designated "checkpoint area" produces a room-attributed
> sighting into `TransitValidator._camera_sightings` when it fires — WITHOUT
> requiring any entry in `CONF_CAMERA_PERSON_ENTITIES`, and WITHOUT requiring
> a URA room/coordinator for that area. Adding a new Protect camera to a
> checkpoint area at any later date must be picked up on next HA restart
> with zero config edits.

---

## 2. Institutional context verified

**Greps run (2026-08-07):**

- `CONF_CAMERA_PERSON_ENTITIES` — 31 files. Load-bearing consumers:
  `transit_validator.py:26,84,124,312`; `camera_census.py:1024-1031,1790,1801`;
  `fan_veto.py:353`; `binary_sensor.py:61`; `__init__.py` migration path L441-508;
  `config_flow.py:306,1140,2878-2909`. Do NOT remove — used by census dedup,
  fan_veto camera leg, and the v3.4.5 migration guard. This cycle ADDS a
  parallel Protect-derived source; hand-list stays as override/supplement.
- `CONF_EGRESS_CAMERAS` — used at `transit_validator.py:27,124,550` (egress
  tracker) + `perimeter_alert.py:74,207`. Out of scope; unchanged.
- `resolve_detection_legs` — public API at `camera_resolver.py:817`, consumed
  by `perimeter_alert.py:1220`. REUSE for family="person" leg discovery per
  physical camera.
- `resolve_operator_declaration` — `camera_resolver.py:533`, groups entities
  by physical camera (device). REUSE for the F1/F2 collapse (twins land in
  one fusion).
- `resolve_area_id_for_entity` — `camera_resolver.py:297`, entity→device area
  fallback. REUSE for room attribution.
- `CameraIntegrationManager._extract_camera_stem` — `camera_census.py`,
  already used by transit for cross-platform dedup. REUSE.

**Prior planning docs skimmed:**

- `PLANNING_room_camera_fusion.md` — resolver adoption pattern (D3 sensor path).
- `PLANNING_exterior_person_escalation.md` — perimeter_alert.py's
  Protect+Frigate legs pattern; template for enumerate-then-resolve.
- `INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md` —
  Protect stability characteristics; motivates the "Protect is authoritative"
  choice.
- `PLANNING_v4.7.18_census_service_shared_refactor.md` — census.get_transit_*
  helpers that transit already calls.
- `PLANNING_v3.5.2_CYCLE_6.md` — origin of TransitValidator.

**Design docs read:** `docs/Coordinator/PRESENCE_COORDINATOR.md` (transit
consumer). No dedicated transit design doc — this planning doc is the design
of record.

**Memory bodies pulled:** `project_shipwatch_spinoff_planned.md` (validation
back-write ceremony), `feedback_no_fabrication.md`, `feedback_measure_before_build.md`.

**Code files read end-to-end:** `transit_validator.py` (842 lines);
`camera_resolver.py` §resolve_area_id_for_entity + §resolve_operator_declaration
+ §resolve_detection_legs; `camera_census.py:509-580,1024-1031,1786-1810`;
`kanban.data.yaml` cards RESACC-1 + TRANSIT-1.

**Enumeration primitive verified (REUSED):** the `unifiprotect` platform tag
on entity registry entries is the authoritative discriminator for
"is this a Protect entity?". The resolver's synthetic-registry duck typing
already exposes `.platform` on EntityEntry-like objects
(`camera_resolver.py:349`).

**NEW surface justified:**

1. `CameraResolver.enumerate_platform_cameras(platform: str, family: str) -> list[EnumeratedCamera]`
   — no existing helper enumerates Protect (or any platform) cameras and
   returns per-physical-camera fusion + area. `perimeter_alert.py` open-codes
   a similar walk against Frigate; that ad-hoc pattern is what we are
   generalizing. Justification: the drift-proofing requires enumeration, not
   resolution of a pre-declared list.
2. `CONF_TRANSIT_CHECKPOINT_AREAS: Final = "transit_checkpoint_areas"` — the
   set of `area_id`s that qualify as traversal transition zones. NEW because
   no equivalent exists; house-zone / room lists are keyed on rooms, and
   these areas are explicitly NOT URA rooms. See §5 knob.
3. `CONF_TRANSIT_PROTECT_SOURCED_ENABLED: Final = "transit_protect_sourced_enabled"`
   — kill-switch boolean. NEW; the Numbers-Get-Knobs rung is a module
   constant (rung 1) at first, migrated to config-flow (rung 2) only if the
   operator asks. See §5.

---

## 3. Design

### 3.1 Where Protect enumeration lives

Add a **pure enumerator** to `CameraResolver` (module-level, testable against
synthetic registries):

```
enumerate_platform_cameras(platform: str, family: str = "person")
  -> list[EnumeratedCamera]

EnumeratedCamera:
  device_id: str            # canonical physical camera
  camera_key: str           # normalized stem (via _extract_camera_stem)
  area_id: str | None       # attributed area (see 3.2)
  legs: list[str]           # detection-family binary_sensor entity_ids
                            #   (superset across platforms for THIS device)
  primary_entity: str       # a canonical entity for logging/dedup
```

Contract:

- Walks `entity_registry.entities`; keeps entities with `platform == "unifiprotect"`
  where the parent DEVICE also hosts a family=person detector (excludes
  `_package_*` per `_is_package_detector`).
- Groups by `device_id` (physical camera). One `EnumeratedCamera` per device.
- For each grouped device, calls `resolve_detection_legs(<representative
  entity>, family="person")` so returned `legs` includes Frigate/Reolink/
  Dahua siblings of the SAME physical camera — this is where the F1/F2
  collapse falls out for free (twins share device via the resolver's
  identifier/MAC/stem ladder).
- Area precedence for `area_id`: apply `resolve_area_id_for_entity` to the
  Protect leg first (authoritative per AUDIT §A-3); fall back across the
  other legs to a non-None area (defensive, guards against the A-3 pattern
  ever recurring on a NEW camera).

### 3.2 What defines a "checkpoint"

An area is a checkpoint iff its `area_id` is in `CONF_TRANSIT_CHECKPOINT_AREAS`.
Default value at integration setup (seed migration):

```python
DEFAULT_TRANSIT_CHECKPOINT_AREAS = [
    "master_hallway",
    "entry_way",
    "garage_hallway",
    "upstairs_hallway",
    "stairs",
]
```

Design rationale for area-based (not room-based): transition zones are not
URA rooms; there is no per-room coordinator to hang a D3 sensor on. Attribution
must therefore be by area — which is exactly what the registry area work
this session enabled. A future room-ified transition zone still works
(area_id ⊇ room_area).

### 3.3 Transit consumption

In `TransitValidator.async_init` (transit_validator.py:80-158) and
`EgressDirectionTracker.async_init` (transit_validator.py:512-595), add — in
front of the existing census/camera_manager path — a Protect enumeration step:

```
if CONF_TRANSIT_PROTECT_SOURCED_ENABLED:
    resolver = hass.data[DOMAIN]["camera_resolver"]
    enumerated = resolver.enumerate_platform_cameras("unifiprotect", "person")
    for cam in enumerated:
        if cam.area_id in checkpoint_area_ids:
            camera_entities.extend(cam.legs)      # subscribe ALL legs,
                                                  # dedup via existing stem path
            # pre-seed area->room mapping for _on_camera_state_change
```

Then UNION with the existing hand-list results. Rationale:

- **UNION, not replace**, on first ship — preserves backward compat with any
  hand-listed entity not on Protect (dahua, reolink interior). Kill switch OFF
  → behavior byte-identical to today.
- Dedup is already handled inside transit via
  `CameraIntegrationManager._extract_camera_stem` — the set() at
  transit_validator.py:137 collapses duplicate subscriptions per stem.
- Room attribution in `_on_camera_state_change` (L418-427) already resolves
  entity→area→room by name. Because Protect entities carry correct area_id
  now, this path yields the room string without further change. NO room object
  required.

### 3.4 F1/F2 collapse

Handled by `resolve_detection_legs` grouping legs by device identifier/MAC
ladder. Both a Frigate F1 twin and a Frigate F2 twin of the same physical
camera resolve to the same `device_id` (via `resolve_operator_declaration`'s
device-consolidation) and therefore appear as ONE `EnumeratedCamera` with
both legs in `.legs`. Transit will subscribe both entities; the stem-based
dedup in `_extract_camera_stem` collapses the fires into one sighting.

### 3.5 Backward compat with egress

`CONF_EGRESS_CAMERAS` is out of scope — egress cameras are at exterior doors,
not interior checkpoints. `EgressDirectionTracker._interior_entities` (the
"near-door" interior list) DOES benefit from the same Protect enumeration
(it currently reads `_get_interior_camera_entities()` which walks the
hand-list). Same Protect-enum path is applied there — behind the same kill
switch.

### 3.6 Migration / persistence

None. The checkpoint-areas list defaults at integration setup and is idempotent
on restart. If the operator explicitly clears the option, we fall back to the
hand-list only (kill-switch semantics documented on the knob).

---

## 4. Deliverables

### D1: `CameraResolver.enumerate_platform_cameras`

Add the enumerator + `EnumeratedCamera` dataclass in `camera_resolver.py`.
Pure; no `hass` dependency; drives off the same synthetic-registry duck types
the rest of the resolver uses.

#### Acceptance Criteria
- **Verify:** given a synthetic registry with 5 Protect person entities
  across 5 devices in 5 areas, returns 5 `EnumeratedCamera`s, each with the
  correct `area_id`.
- **Verify:** given a device with both a Protect leg and a Frigate F1+F2 twin
  of the same physical camera, returns ONE `EnumeratedCamera` with three legs
  in `.legs` and area drawn from the Protect leg.
- **Verify:** `_package_*` Frigate person detectors are excluded from `.legs`.
- **Test:** `quality/tests/test_resolver_enumerate.py::test_enumerate_protect_person_returns_one_per_device`,
  `::test_enumerate_collapses_f1_f2_twins`, `::test_enumerate_area_falls_back_across_legs`,
  `::test_enumerate_excludes_package_detector`.
- **Live:** `resolver.enumerate_platform_cameras("unifiprotect", "person")` on the
  live registry returns ≥5 rows whose `area_id` set is a superset of
  `{master_hallway, entry_way, garage_hallway, upstairs_hallway, stairs}`.

### D2: New consts + knobs

Add to `const.py`:
- `CONF_TRANSIT_CHECKPOINT_AREAS: Final = "transit_checkpoint_areas"`
- `CONF_TRANSIT_PROTECT_SOURCED_ENABLED: Final = "transit_protect_sourced_enabled"`
- `DEFAULT_TRANSIT_CHECKPOINT_AREAS: Final = (...)` per §3.2
- `TRANSIT_PROTECT_SOURCED_ENABLED_DEFAULT: Final = True` (ship-on; kill-switch
  flips to False)

#### Acceptance Criteria
- **Verify:** `grep -n TRANSIT_CHECKPOINT_AREAS const.py` returns exactly one
  definition site (per Numbers-Get-Knobs discipline: named, not inline).
- **Test:** `quality/tests/test_const_transit_protect.py::test_defaults_present`.

### D3: Wire `TransitValidator` + `EgressDirectionTracker`

Prepend Protect-enumeration branch (§3.3, §3.5) in both `async_init` methods,
gated by `CONF_TRANSIT_PROTECT_SOURCED_ENABLED`, UNIONed with existing paths.

#### Acceptance Criteria
- **Verify:** with kill-switch OFF, subscribed entity set is byte-identical
  to pre-change (assert via snapshot test against a fixture registry).
- **Verify:** with kill-switch ON and a fixture registry mirroring the live
  5 checkpoint cameras, `TransitValidator._unsub` count grows to cover ALL 5
  physical cameras (i.e. at least one subscription per checkpoint stem).
- **Sensor:** `sensor.ura_transit_validator_diagnostics` (existing, if any;
  ELSE new diagnostic attribute on the integration diagnostics entry) exposes
  `checkpoint_cameras_by_area`: dict of area_id → list of subscribed entity_ids.
  All 5 checkpoint areas must be keys with ≥1 entity each.
- **Test:** `test_transit_validator_protect_sourcing.py::test_all_five_checkpoints_covered`,
  `::test_kill_switch_off_matches_legacy_subscriptions`,
  `::test_new_protect_camera_picked_up_on_restart`.
- **Live:** post-restart HA logs show line
  `TransitValidator initialized: subscribed to N camera entities` with
  N ≥ (legacy_count + delta_for_upstairs_hall + delta_for_stairs_top).
  Log INFO line added: `TransitValidator Protect-sourced checkpoints: {area: [entities]}`.

### D4: Drift-proof acceptance (the falsifiable invariant)

#### Acceptance Criteria
- **Verify (mutation test):** delete the hand-list entry for `staircase`
  (garage_hallway) in the fixture; assert subscription still occurs via the
  Protect enumeration path.
- **Verify (mutation test):** add a NEW synthetic Protect camera whose
  device area_id is `master_hallway`; assert on next `async_init` it is
  subscribed WITHOUT any edit to `CONF_CAMERA_PERSON_ENTITIES`.
- **Live:** manually fire `binary_sensor.upstairs_hall_person_detected` (or
  observe next organic fire) and confirm a sighting lands with room=
  `upstairs_hallway` in `TransitValidator._camera_sightings` (surfaced on the
  diagnostics sensor attribute added in D3).

---

## 5. Numbers-Get-Knobs — knob inventory

| Knob | Rung | Default | Why |
|---|---|---|---|
| `CONF_TRANSIT_CHECKPOINT_AREAS` | 2 (config/options flow, per-deployment structure) | 5-area list per §3.2 | These are house-specific areas; the operator legitimately might rename or add one (e.g. a mid-house hallway). |
| `CONF_TRANSIT_PROTECT_SOURCED_ENABLED` | 1 (module constant, ship default True) | True | **Kill switch.** Flipping to False reverts to legacy hand-list-only subscription path — the pre-cycle behavior — without a code roll-back. Rung 1 (not entity) because it should require review to disable a drift-proofing safety net. |
| `TRANSIT_CHECKPOINT_STALE_SECONDS` / `TRANSIT_CHECKPOINT_WINDOW_SECONDS` | unchanged | as-is | Existing knobs; not touched. |

---

## 6. Tier classification

**Tier 2-DB (standing policy: 3 framing-disjoint reviews).**

Justification: transit_validator is a **shared primitive** consumed by
presence/transition confidence, egress direction, and phone-left-behind
detection. It touches the trust hierarchy (path_confidence_delta feeds
transition acceptance). This is regression-prone by the standing-policy
definition. Not Tier 3 because:
- No new synthetic-time / clock coupling.
- No cross-coordinator ripple beyond presence itself.
- The change is additive (UNION), with a working kill switch.

**Framings (must be assigned disjoint):**

- **A — correctness + edge cases.** Enumerator returns per-device rows, area
  fallback across legs, `_package_*` exclusion, empty-registry safety, mixed
  Protect+non-Protect devices, entities with `disabled_by` set.
- **B — subscription lifecycle + cross-coordinator no-flap.** No double-
  subscribe (set() dedup); `async_teardown` unsubs everything (including
  Protect-sourced adds); reload of the integration re-enumerates cleanly;
  the union does not double-fire a sighting when the same physical camera
  is BOTH in hand-list AND Protect-enumerated (must dedup by stem or entity_id).
  Kill-switch off matches legacy subscription set byte-identical.
- **C — enumeration authority + adversarial completeness.** Falsifiable
  invariant per §1 stated up front. Reviewer C constructs a fixture where a
  Protect entity lives on a device whose `area_id` is a checkpoint but whose
  Protect leg's OWN `area_id` is None — assert fallback recovers area from a
  sibling leg. Reviewer C also mutation-tests: temporarily reassign a
  checkpoint camera's device area to a NON-checkpoint area — assert it is
  NOT subscribed. And: add a new synthetic Protect camera at a checkpoint
  area — assert pickup on next init WITHOUT any hand-list edit (this is the
  drift-proofing proof).

**Pre-review baseline tag:** `pre-review-v<X.Y.Z>` before any fix-up.

**Live Validation (Review D):** after HA restart on shipped build, verify
diagnostics attribute shows all 5 checkpoint areas populated, and — within
one organic occupancy sweep of the house — at least 3 of the 5 checkpoints
produce a real sighting into `_camera_sightings` (the other two may not fire
in a single sweep; documented on the README result table).

---

## 7. Plan-completion / deferral accounting (up-front)

Deliberately OUT of scope for this cycle:

1. **Retiring `CONF_CAMERA_PERSON_ENTITIES`** — kept as override/supplement.
   Retirement is a separate cycle after ≥2 weeks of Protect-sourced
   coverage proving drift-proof. Tracked as follow-up card TRANSIT-2 (to be
   filed on ship).
2. **Adding a URA room for transition zones** — considered and rejected.
   These areas exist as HA areas only; creating rooms would add coordinator
   overhead for no consumer beyond transit. Area-based attribution suffices.
3. **Extending Protect-sourcing to census interior cameras (D3 fused sensor
   for room-level occupancy)** — separate concern; census already has per-
   room fusion via `resolve_operator_declaration` per room. Not touched.
4. **Perimeter (exterior) cameras** — perimeter_alert.py already resolves via
   `resolve_detection_legs`; drift there is bounded by CONF_PERIMETER_CAMERAS
   / config-flow. Out of scope.
5. **Diagnostics dashboard card exposing `checkpoint_cameras_by_area`** —
   attribute is added (D3) so a dashboard card is trivial; card work deferred
   to dashboarding workstream.

---

## 8. References

- `custom_components/universal_room_automation/transit_validator.py` (v3.5.2, 842 lines)
- `custom_components/universal_room_automation/camera_resolver.py:297,533,817`
- `custom_components/universal_room_automation/camera_census.py:509-580,1786-1810`
- `docs/planning/AUDIT_resolver_ground_truth_manual.md` (RESACC-1 ground truth)
- `docs/planning/kanban.data.yaml` cards TRANSIT-1 (L129-146), RESACC-1 (L73-105)
- `docs/planning/PLANNING_room_camera_fusion.md`
- `docs/planning/PLANNING_exterior_person_escalation.md`
- `docs/planning/INVESTIGATION_camera_signal_context_sensitivity_protect_vs_frigate.md`
