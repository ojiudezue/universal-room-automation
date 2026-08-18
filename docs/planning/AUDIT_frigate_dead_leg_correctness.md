# AUDIT — Frigate dead-leg correctness (READ-ONLY)

**Date:** 2026-08-18
**Scope:** Every URA site that resolves or reads a Frigate person / occupancy /
face / count entity, checked for whether it selects the LIVE Frigate-2 leg or a
DEAD Frigate-1 leg on both camera groups (interior bare-named / perimeter `_2`-named).
**Constraint:** read-only; DBs `mode=ro`; live mount `/Users/okosisi/ha-config/`.
**Hazard reference:** `reference_frigate1_retired_2suffix_permanent.md`, cards
`FRIGATE-LEG-NAMING-1`, `PERIMETER-PHANTOM-XCORR-1`.

---

## Headline verdict

**URA is NOT reading dead Frigate legs anywhere on the live system.**

The audit's own **hazard premise is not borne out by the live state as of the
Aug 17 22:00 registry snapshot**: the retired Frigate-1 legs are **fully REMOVED**
from both the entity registry and the state machine — they are *not* present-and-frozen.
Because every URA resolve/read path is either **registry-gated** (iterates
`entity_registry.entities`) or **state-gated** (`hass.states.get` / `_entity_exists`),
a dead F1 entity name that no longer exists resolves to **nothing** (404 / `None`),
never to a frozen value. There is therefore no live corruption of census, occupancy,
or perimeter telemetry from dead-leg reads.

There is ONE **latent structural hazard** (does not fire today, would fire if F1
legs ever returned): `camera_resolver._prefer_canonical` prefers the bare
(non-`_N`) name, which on a perimeter camera is the DEAD F1 name. See Finding L1.

### Live evidence (decisive)

| Probe | Result | Meaning |
|---|---|---|
| `binary_sensor.front_side_ptz_person_occupancy` (bare, perimeter = dead F1) | **ENTITY_NOT_FOUND (404)** | dead F1 leg removed, not frozen |
| `binary_sensor.hot_tub_person_occupancy` (bare, perimeter) | **ENTITY_NOT_FOUND** | removed |
| `binary_sensor.back_yard_person_occupancy` (bare, perimeter) | **ENTITY_NOT_FOUND** | removed |
| `binary_sensor.family_room_person_occupancy_2` (`_2`, interior = would-be F1) | **ENTITY_NOT_FOUND** | interior has bare only |
| `binary_sensor.front_side_ptz_person_occupancy_2` (live F2, perimeter) | `off`, toggled on/off 20:43/20:47/21:00 (36h history, 805 changes) | LIVE, updating now |
| `binary_sensor.back_yard_person_occupancy_2` (live F2, perimeter) | `off`, toggled 14:55/15:08/15:28 | LIVE |
| `binary_sensor.family_room_person_occupancy` (live F2, interior) | `off`, updating | LIVE |

**Registry census (`.storage/core.entity_registry`, snapshot Aug 17 22:00, 4 days
post-retirement):** exactly **23** `_person_occupancy` binary entities — one per
camera, all `platform=frigate`, all `disabled_by=None`. Interior cams carry the
**bare** name; perimeter/PTZ cams carry **`_2`**. **Zero** `f1retired`-named
entities. **Zero** dead bare-perimeter duplicates. The dead legs are simply gone.
(`sensor._person_count` is bare on ALL 23 cams; `_last_recognized_face` and
`_person_active_count` are `_2` on all 23 — the per-entity-suffix inconsistency the
memo describes, but again only one live leg exists per slot.)

---

## Read/resolve-site table

Leg-selection columns describe what each site WOULD pick given the live registry
(only the live-named leg present per camera). "reads DEAD leg?" = does it read a
frozen F1 value on the live system.

| read site (file:line) | what it feeds | leg on interior | leg on perimeter | reads DEAD leg? | live evidence |
|---|---|---|---|---|---|
| `camera_resolver.py:980-1035` `resolve_detection_legs` | perimeter_alert legs / coverage telemetry | bare (live) | `_2` (live) — returns ALL matching legs from registry | **N** | registry has only live legs; dead names absent so cannot be added as a leg |
| `camera_resolver.py:1395-1399` `_scan_device_entities` person_bs via `_prefer_canonical` | census `person_binary_sensor` (resolver path) | bare (live, only one) | `_2` (live, only one present) | **N (today); latent risk L1** | only `_2` present on perimeter device → `_prefer_canonical` returns it; bare F1 absent so no canonical/`_N` collision |
| `camera_resolver.py:1411-1414` count sensor | census person_count | bare `_person_count` (live) | bare `_person_count` (live) | **N** | count sensors are bare on all cams and live |
| `camera_resolver.py:1400-1421` face capability / `_last_recognized_face` | face dedup capability flag | `_2` (live) | `_2` (live) | **N** | face entities uniformly `_2`, live |
| `camera_census.py:369-416` `resolve_camera_entity` (occupancy/detected classify) | census interior/exterior classification | bare (live) | `_2` (live) | **N** | operates on the registry entry it was handed; dead not in registry |
| `camera_census.py:647-692` sibling string-build `f"binary_sensor.{stem}_person_occupancy"` | cross-platform sibling attach | constructs bare | constructs bare (= dead F1 name on perimeter) | **N** | **registry-gated**: `ent_reg.async_get(candidate_id)` returns `None` for the absent dead name → `continue` (line 658-660) |
| `camera_census.py:648-651,718` `_extract_camera_stem` / candidate list | stem derivation | n/a (string parse) | n/a | **N** | pure string ops, no read |
| `camera_census.py:816-846` platform/suffix classify | interior vs exterior census counting | bare→Frigate | `_2`→Frigate (via `_strip_disambiguation`) | **N** | reads only entities enumerated from registry (live) |
| `camera_census.py:2385-2397` `_last_recognized_face` scan (`bs_id.endswith("_person_occupancy")`) | fresh-face / face census | iterates registry Frigate cams | iterates registry cams | **N** | registry iteration; maps bare-or-`_2` occupancy → `_2` face, both live |
| `perimeter_alert.py:1814` `resolver.resolve_detection_legs` | perimeter alert legs | bare (live) | `_2` (live) + would include dead if present | **N** | dead absent from registry; live `_2` fired the alert (front_side_ptz history) |
| `perimeter_alert.py:1840-1845` `f"{base_bs}_2"` probe | OFF-path leg recovery | probes `_2` | probes `_2` | **N** | `_entity_exists` gate; dead names 404 |
| `perimeter_alert.py:1877-1889` `_person_detected(_2)` stem probes | Protect sibling recovery (kill-switch OFF) | `_entity_exists`-gated | `_entity_exists`-gated | **N** | gated; Protect legs, not F1 |
| `perimeter_alert.py:450-531` engine tagging on `base_bs` suffix | telemetry engine label | string classify | string classify | **N** | labels only; base_bs is a live entity |
| `fan_veto.py:301-312` `{entry_id}_camera_person_detected` | fan-veto camera person | URA-fused entity, not raw Frigate | same | **N** | reads URA's own fused `binary_sensor`, not a Frigate leg |
| `person_coordinator.py:1758` / `aggregation.py:1733-1738` `get_tracked_person_count` | tracked-person count | device_tracker/person, not Frigate | same | **N** | not a Frigate read |

---

## Findings (severity-ranked)

### F1 — INFO / verdict: No live dead-leg reads. Hazard premise not met on live system.
The retired Frigate-1 legs are **removed** from the registry and state machine, not
frozen-and-present. Every enumerated read site is registry- or state-gated, so a
dead name resolves to nothing. Census, occupancy, perimeter alert, and face dedup
all read live legs only. **Direct proof:** three bare-perimeter dead names return
404; live `_2` legs show real on/off toggles in 36h history.

### L1 — LOW / LATENT (does not fire today): `_prefer_canonical` prefers the bare name = the DEAD F1 name on perimeter.
`camera_resolver._prefer_canonical` (`camera_resolver.py:335-362`) resolves a
bare-vs-`_N` collision on the **same device** by **preferring the bare (canonical)
name**. On an interior camera the bare name is the LIVE leg — correct. On a
**perimeter camera the bare `_person_occupancy` is the DEAD F1 name** and `_2` is
live. IF a dead F1 perimeter leg were ever present-and-enabled on the device
(e.g. F1 re-added, a restore that re-materializes the old entity, or a different
registry snapshot where retirement had not yet purged it), `_scan_device_entities`
(line 1395-1399) would set `person_bs` to the **dead bare leg** and the census
would read a frozen value for that camera. Today this cannot happen because the
dead leg is absent, so there is no bare/`_2` collision to arbitrate. **This is a
name-based liveness assumption of exactly the class the memo warns against**
("NEVER identify the live Frigate leg by name pattern; use recency/registry").
Recommended durable fix (future cycle, not this audit): when both a bare and a
`_N` person_occupancy match the same Frigate device, prefer by **`last_updated`
recency**, not by canonical-name — or explicitly skip a leg whose state is
`unavailable`/stale. Track under `FRIGATE-LEG-NAMING-1`.

### F2 (census) — SAFE.
`camera_census.py` resolves `person_binary_sensor` per camera through the resolver
(`_scan_device_entities`) and through registry-gated sibling string-builds
(lines 647-660). On perimeter cams it gets the **live `_2`** leg (only leg present);
on interior cams the **live bare** leg. The dead F1 name, when string-built
(line 649), is dropped by the `ent_reg.async_get(...) is None` gate before any read.
No frozen value enters the interior or exterior census. **No over/under-count from a
wrong leg.** (The historical census under-count in `AUDIT_census_accuracy_regression.md`
was the *strict-endswith dropped `_2`* bug, already fixed by `_has_any_suffix_stripped`
at `camera_resolver.py:317-327`; that fix is present and correct here.)

### F3 (perimeter alert) — SAFE, and no dead leg inflates leg-agreement telemetry today.
`perimeter_alert.py` discovers legs via `resolve_detection_legs` (registry) plus
`_entity_exists`-gated `_2`/`_person_detected` probes. For front_side_ptz the alert
fires on the live `_2` leg (history shows real toggles). Because the dead bare F1
leg is **absent from the registry**, `resolve_detection_legs` cannot return it, so it
is **not** counted as a coverage/leg-agreement leg. The `PERIMETER-PHANTOM-XCORR-1`
concern (dead corpse subscribed alongside the live `_2`, inflating coverage) **does
not materialize on the current registry** — it required the dead leg to still exist,
which it does not. If the memo's "subscribes the dead corpse" note was written
against an earlier registry state, that state no longer holds.

### F4 — Note on evidence provenance / freshness.
The registry snapshot is `Aug 17 22:00`; live states/history pulled `Aug 18`. The
`unavailable`→`off` transition at 21:49→21:50 on Aug 17 across all legs is a URA
reload/restart transient (identical timestamps fleet-wide), not a dead leg — the
same legs show genuine on/off cycling before and after. No entity anywhere was found
frozen at the F1 retirement instant (2026-08-13 16:37); a scan of all 23 registered
`_person_occupancy` entities found only live-named legs.

---

## Verdict (restated)

- **Dead-leg reads found: NO.** Not in census, not in occupancy, not in perimeter
  alert, not in face dedup, not in fan-veto.
- **Why:** F1 retirement fully removed the dead entities; every URA read is
  registry- or state-gated, so absent dead names resolve to nothing.
- **Census:** reads the live leg on both groups (bare interior, `_2` perimeter). Safe.
- **Perimeter alert:** fires on the live `_2` leg; no dead corpse in the leg set;
  `PERIMETER-PHANTOM-XCORR-1` does not fire on the current registry.
- **One latent structural risk (LOW):** `_prefer_canonical` would pick the dead bare
  F1 leg on perimeter IF such a leg ever reappears on a device alongside the live
  `_2`. Recommend a recency/registry-liveness tiebreak instead of canonical-name
  preference in a future cycle (`FRIGATE-LEG-NAMING-1`). No action required today.
