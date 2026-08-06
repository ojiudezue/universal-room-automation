# Golden-Master Diff — Census Cutover to CameraResolver (CENSUS_USE_NEW_RESOLVER)

**Date:** 2026-08-06
**Flip prerequisite for:** `camera_resolver.py:92` `CENSUS_USE_NEW_RESOLVER = False`
(README_v5.45.0.md "What ships DARK": *"golden-master diff artifact: captured
legacy resolution vs resolver output, every difference explained"*).
**Probe:** `scripts/probes/golden_master_census_diff.py` (re-runnable; see §1).

## Verdict up front: **NO-GO**

3 of 5 differences are **resolver-wrong**: flipping the flag today silently
drops the entire UniFi Protect leg of the egress transit census (84–117
real ON-events per camera per week). Blocking findings in §5.

---

## 1. Methodology

Both paths are **pure functions of the entity + device registries** — neither
legacy `CameraIntegrationManager.resolve_cross_platform_sensors` nor the
`CameraResolver` cutover branch reads live states on this deployment (the
resolver's `state_getter` is only consulted by the F2 Frigate-collapse winner
pick, and `FRIGATE_CROSS_HOST_CORROBORATION_ENABLED=True` since 2026-08-04, so
the collapse is inert). The comparison is therefore fully deterministic
offline from a registry snapshot; no live-state reconstruction was needed.

- **Inputs (captured 2026-08-06, read-only over `ssh ha`):**
  - `/config/.storage/core.entity_registry` (29.7 MB) and
    `/config/.storage/core.device_registry` (1.96 MB) snapshots.
  - Live camera lists from the URA integration config entry
    (`.storage/core.config_entries`): `camera_person_entities` (9 entities) and
    `egress_cameras` (3 entities) — the ONLY inputs the flag-gated call sites
    (`get_transit_interior_entities` / `get_transit_egress_entities`,
    camera_census.py:883–895) feed to `resolve_cross_platform_sensors`.
    `perimeter_cameras` never routes through this function (it uses
    `_get_integration_camera_list` raw) and is out of scope for the flip.
- **Execution:** the probe imports the **real production modules**
  (`camera_census.py`, `camera_resolver.py`) under a synthetic package (so the
  HA-framework-heavy `__init__.py` is not executed), backs
  `er.async_get`/`dr.async_get` with duck-typed registries loaded from the
  snapshots (field-faithful: `disabled_by`, user `name` vs `original_name`,
  identifier/connection tuples), and calls `resolve_cross_platform_sensors`
  twice per list — once with the cutover flag forced `False` (legacy branch)
  and once forced `True` (resolver branch). Fresh `CameraIntegrationManager`
  per run (device cache empty). Bug Class #62 discipline: no reimplementation
  of either path.
- **Event weighting ("replay"):** since resolution output does not depend on
  events, event replay reduces to *which resolved entities actually fire*.
  Each row carries its 7-day count of `state='on'` transitions from the HA
  recorder DB (read-only `mode=ro` query, window 2026-07-30 → 2026-08-06), so
  every difference is weighted by real detection traffic, not hypotheticals.
- **Comparison surface:** the set the census actually consumes — person
  binary_sensors (what `_is_entity_on` iterates) + attached person_count
  sensors + platform labels.

**Registry facts that drive the ladder on this deployment** (verified from the
snapshot; consistent with AUDIT §F5):

| Integration | `identifiers` | `connections` |
|---|---|---|
| UniFi Protect devices | **empty** | `("mac", …)` |
| Frigate devices | `("frigate", "<host>:<object>")` | **empty** |

⇒ MAC rung: zero cross-integration matches (Frigate side has no MAC).
⇒ Identifiers rung: zero (Protect side has none).
⇒ The ONLY live cross-integration rung is rung-5 name-stem, whose index
(`_frigate_stem_to_device_ids`) is **Frigate-object-keyed only** — it can take
a UniFi input *to* a Frigate sibling, but a Frigate input can never reach a
Protect device. This asymmetry is the root of all three resolver-wrong diffs.

## 2. Agreement table

| List | Legacy person BS | Resolver person BS | Rows compared | Identical | Differing |
|---|---|---|---|---|---|
| interior (`camera_person_entities`) | 9 | 10 | 15 | 13 | 2 (both RESOLVER-ONLY) |
| egress (`egress_cameras`) | 6 | 3 | 9 | 6 | 3 (all LEGACY-ONLY) |
| **Total** | | | **24** | **19 (79%)** | **5** |

All 19 identical rows also agree on platform label and person_count
attachment. All 5 differences are explained below — none unexplained.

## 3. Per-difference explanation table (MANDATORY — complete)

| # | Entity | Side | 7d ON | Which is CORRECT | Mechanism |
|---|---|---|---|---|---|
| 1 | `binary_sensor.staircase_person_occupancy` | RESOLVER-ONLY | 122 | **Resolver** | **Legacy bug.** Input `camera.staircase_high_resolution_channel` sits on Protect device "Staircase" (`e13c85…`) whose only person BS is the mis-homed `binary_sensor.camera_protect_garagehallway_person_detected` (the AUDIT §F1 multi-camera NVR record). Legacy extracts its stem from the *found sensor's* name → `camera_protect_garagehallway` → sibling lookup misses, so the Frigate staircase leg is never joined. Resolver computes the stem from the *camera entity name* (`staircase`, D-HIGH-1 resolution-suffix strip) → rung-5 hits Frigate object `staircase` → recovers the leg. |
| 2 | `sensor.staircase_person_count` | RESOLVER-ONLY | n/a (count) | **Resolver** | Same mechanism as #1 — the count sensor rides on the recovered Frigate staircase device. |
| 3 | `binary_sensor.doorbell_lite_person_detected` | LEGACY-ONLY | 84 | **Legacy** | **Resolver gap (blocking).** Input `camera.doorbell_lite` is the FRIGATE camera entity. Legacy: finds Frigate `doorbell_lite_person_occupancy` on-device, stem `doorbell_lite` → registry probe for `binary_sensor.{stem}_person_detected` finds the real UniFi sensor (Protect device "Garage Doorbell Lite", enabled, active). Resolver: from a Frigate device there is NO rung to the Protect device — Frigate device has no MAC, Protect device has no identifiers, network-inventory is a stub, and the rung-5 stem index only maps stems→Frigate devices (never →Protect). The UniFi leg is silently dropped. |
| 4 | `binary_sensor.front_door_aerial_person_detected` | LEGACY-ONLY | 104 | **Legacy** | Identical mechanism to #3 (`camera.front_door_aerial` is Frigate-platform). |
| 5 | `binary_sensor.madrone_g6_entry_person_detected` | LEGACY-ONLY | 117 | **Legacy** | Identical mechanism to #3 (`camera.madrone_g6_entry` is Frigate-platform). |

Why interior does NOT show this gap: `camera_person_entities` happens to list
**both** platforms' camera entities per physical camera (e.g. `camera.playroom`
Frigate + `camera.playroom_high_resolution_channel` Protect), so each leg is
reached same-device; `egress_cameras` lists only the Frigate entities, so the
UniFi leg exists *only* via the cross-platform join — which the resolver
cannot make in the Frigate→Protect direction.

## 4. Non-difference observations (parity preserved, recorded for the record)

- **`camera_protect_garagehallway_person_detected` appears under the staircase
  input on BOTH sides** (421 ON/7d). The resolver's F1 stem filter *should*
  exclude it (stem `staircase`), but F1 only applies when
  `_infer_integration(dev) == "unifiprotect"` — and live Protect devices have
  **empty identifiers**, so integration infers `""` and the F1 filter is inert
  on this deployment. Pre-existing mis-fusion, identical on both paths → not a
  flip regression, but the v5.45.0 F1 fix is not actually protecting anything
  live. Follow-up: infer integration from entity `platform` (populated) rather
  than device identifiers.
- **`area_id`:** the cutover branch hard-codes `area_id=None`
  (camera_census.py:456); legacy carries registry `area_id`. No live diff —
  every legacy row also resolved `area_id=null` — but this becomes a latent
  diff the day any of these sensors gets an area assigned.
- **Platform labels:** identical for all shared rows (the branch's
  `""→unifiprotect` fallback lands correctly because the only
  identifier-less devices in play are Protect).

## 5. Blocking findings (resolver-wrong)

1. **BLOCK-1 — Frigate→Protect direction missing from the ladder** (diffs
   #3–#5). Flipping today zeroes the UniFi leg of the egress transit census
   (~305 ON-events/week across the three egress cameras), degrading egress
   cross-validation to single-platform and changing `unifi_count` on the
   transit path. Fix options: (a) index Protect devices by camera-entity stem
   and add a reverse rung-5 lookup; (b) infer integration from entity
   `platform` and extend the stem index beyond Frigate; or (c) operator config
   amendment adding the Protect camera entities to `egress_cameras`
   (operator-declared rung) — then re-run this probe to prove parity.
2. **BLOCK-2 — re-run required.** Whatever remedy lands, this probe must be
   re-run (same command, fresh snapshots) and show `differing` = only the
   #1/#2 class (resolver-correct improvements) before the reviewed flip.

## 6. What could not be compared, and why it does not matter here

- **Live in-process execution** was replayed from registry snapshots via
  duck-typed fakes, not against a running `hass`. Faithful because both paths
  consume only registry fields the snapshot carries verbatim; the single
  state-dependent branch (F2 collapse winner pick) is gated off live.
- **Recorder "events" were used as weights, not replayed through the census**,
  because resolution output is event-independent; downstream census math
  (hold/decay, dedup, cross-validation) is out of scope for this flag and
  unchanged by it.
- **`perimeter_cameras`** and the room-level `room_cameras` path are not
  gated by this flag and were not compared.

## 7. Go/no-go

**NO-GO.** Do not flip `CENSUS_USE_NEW_RESOLVER` until BLOCK-1 is remedied
and BLOCK-2's re-run shows the egress UniFi leg restored. The two
resolver-correct improvements (#1/#2, staircase Frigate leg + count, 122
ON/7d recovered) are a genuine argument *for* the cutover once the egress gap
is closed — record them as the flip's expected census delta.

## 8. Reproduction

```bash
ssh ha "cat /config/.storage/core.entity_registry" > /tmp/er.json
ssh ha "cat /config/.storage/core.device_registry" > /tmp/dr.json
python3 scripts/probes/golden_master_census_diff.py --emit-activity-script \
  | ssh ha "python3 -" > /tmp/activity.json
python3 scripts/probes/golden_master_census_diff.py \
  --entity-registry /tmp/er.json --device-registry /tmp/dr.json \
  --activity /tmp/activity.json
```
(Refresh the `CAMERA_LISTS` constant from `core.config_entries` if the
integration entry's camera lists have changed.)
