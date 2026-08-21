# AUDIT — Stale entity references in stored URA config (READ-ONLY)

**Date:** 2026-08-21
**Cycle:** EGRESS-CAMERA-DEAD-CONFIG-1 Part D
**Sources:** `/Users/okosisi/ha-config/.storage/core.entity_registry`,
`/Users/okosisi/ha-config/.storage/core.config_entries` (live Samba mount, read-only).
**Sweep script:** `scratchpad/sweep_stale_entities.py` (session-local; not committed).
**Bug class:** stored config naming an HA entity_id that no longer exists in the
entity registry — silent contribution loss + potential log flood (2,030 WARNINGs / 5h
observed pre-fix on this class).

---

## Scope

Every URA config entry's stored entity-id-shaped values, across these keys, compared
against the live entity registry (28,524 entities). Values may be scalar or list.

Keys swept: `lights`, `night_lights`, `alert_lights`, `fans`, `humidity_fans`,
`covers`, `climate_entity`, `occupancy_sensors`, `motion_sensors`, `presence_sensors`,
`lux_sensors`, `lux_sensor`, `temperature_sensor`, `humidity_sensor`,
`camera_person_entities`, `egress_cameras`, `perimeter_cameras`, `person_entities`,
`cameras`.

URA config entries examined: **42**.

## Results

| entry | key | entity | present | suffixed-sibling-present |
|---|---|---|---|---|
| Universal Room Automation | egress_cameras | camera.garage_a | ABSENT | camera.garage_a_2, camera.garage_a_high_resolution_channel, camera.garage_a_low_resolution_channel, camera.garage_a_medium_resolution_channel |
| Universal Room Automation | egress_cameras | camera.garage_b | ABSENT | camera.garage_b_2, camera.garage_b_high_resolution_channel, camera.garage_b_low_resolution_channel, camera.garage_b_medium_resolution_channel |

**Total absent:** 2 / all others resolve.

## Classification

- Both rows are **operator-config-side** (the bare names were written when
  Frigate-1 was still live; Frigate-1 retired 2026-08-13 leaves `_2` as the
  permanent live suffix — see `reference_frigate1_retired_2suffix_permanent.md`).
- No code-side fixes required: the resolver is registry-gated and correctly
  refuses to guess a substitute (audit `AUDIT_frigate_dead_leg_correctness.md`
  Finding L1 already flags the opposite-direction guess as a latent hazard).
- No code deletions.

## Operator apply-list (single options-flow pass)

Integration entry **"Universal Room Automation"** → egress_cameras selector:

- Replace `camera.garage_a` with `camera.garage_a_2`
- Replace `camera.garage_b` with `camera.garage_b_2`

After the operator applies these, the diagnostic surface
`sensor.persons_in_house` attribute `unresolved_configured_cameras_count`
should return to `0` and `unresolved_configured_cameras` to `[]` on the next
resolve tick (or immediately on the next `EVENT_ENTITY_REGISTRY_UPDATED`).

## Method notes

- Regex-shape filter (`^[a-z_]+\.[a-z0-9_]+$`) skips non-entity strings such as
  free-text titles.
- "suffixed-sibling-present" enumerates any live entity_id whose id begins with
  `<absent>_` — informational only. **The code does NOT and will not substitute
  a sibling automatically** (Part C non-goal).
- No writes performed; the URA sqlite DB was not opened (Samba constraint).
