# Review A: interior vision ship 1 (local correctness)

Branch `feature/interior-vision-d1` @ 9931a001, diff base 7b818ce1 (`git diff 7b818ce1 9931a001`). Framing A only: per-site logic,
edge cases, None handling and arithmetic. Spec: `PLANNING_vision_interior_sightings.md` @ 7b818ce1, ship 1 (§9.D1, §9.D5 no-model
leg, §9.D7 trip-wires, §12 switch and knobs, §6.3 guard).

I read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` completely before reviewing. I re-asserted nothing from
the §10 ledger, and no code contradicts the docs. The plan, `QUALITY_CONTEXT.md` and the tracing methodology were also read.

Note: during this review the worktree had an uncommitted change to `interior_vision.py`, probably another reviewer's mutation drill.
I made no edits and read only the committed tree through `git show` / `git diff`.

## Verdict: FIX-REQUIRED (no CRITICAL or HIGH; fix M1-M3 in the fix-up pass, plus the cheap LOWs)

## Findings

| # | Sev | Site (9931a001) | Class | Failing input / evidence |
|---|---|---|---|---|
| M1 | MEDIUM | `person_sighting.py:1002-1003` (`_ensure_interior_groups` signature) | #53 one missed site (rebuild trigger) | Groups are rebuilt only when the census interior list or `id(resolver)` changes. A room-type, room-area or room-entry edit does not rebuild them, and neither does an entity/device area move or a twin-pair admission. Repro: change Playroom `CONF_ROOM_TYPE` from common_area to bedroom in options. The cached group keeps room=Playroom, so a record keeps being built for a now-bedroom room until restart. That breaks INV-IV-SCOPE, which later ships will rely on for frame selection. Fix: add the room map (`_room_area_ids` plus room types) and a registry-change marker to the signature, or reset `_interior_sig` in `rebind()` / `_on_room_entry_lifecycle`. |
| M2 | MEDIUM | `person_sighting.py:1240-1246` with `:571-582` | trip-wire numerator gap | `interior_path_zero` counts only entries whose `_egress_key` matched an inward `from_key`. `_egress_key` caches the RAW camera id when the resolver is None or raises (`:574-582`; the cache is cleared only in `rebind()`, which returns early when FACE_SIGHTING is disabled). Repro: no camera manager when the first garage_a entry is processed, so key = `binary_sensor...` is cached forever. Every later entry is counted `entries_unmapped`, no path record is written and the trip-wire numerator stays 0, so no page. That is the exact failure the wire should catch, and it is also the D0(a) key-equality premise. Fix: count "entries on doors that have a path map", for example a crossing whose camera is an anchor camera of a mapped door, independent of the key match. Also do not cache a failed resolution. |
| M3 | MEDIUM | `person_sighting.py:1283-1314` (`_bodies_at`, `_path_n`) | spec deviation (arithmetic) | Plan §9.D5 says `n` falls back to "the max `bodies_nvr` on the first hop". The code uses the value at the first build at or after the hop's first on-edge. Repro: three entrants reach the staircase at E+50, E+52 and E+56. The census reads 1 at E+51 and 3 at E+61. `n` = 1 with `n_source="first_hop"`, where the spec gives 3. Ship 4 gates the vision leg on `n >= INTERIOR_TIMELAPSE_VISION_MIN_N` (2), so this undercount would suppress the call. Fix: take the max of `_bodies_hist[key]` over [first_on, that hop window's close]. Keep `bodies_nvr_at_first_on` on the hop tuple as is. |
| L1 | LOW | `sensor.py:4290+` (`InteriorAwarenessSensor.native_value`) | missing≠0 (display) | Every record `missing` (NVR host down), or no records yet (boot, kill constant): state = 0, which reads as "no unnamed people". Spirit of INV-IV-MISSING / "a dead camera is faulty equipment": return None (unknown) when no record has `bodies is not None`. |
| L2 | LOW | `person_sighting.py:1240` (deviation 5) | wrong discriminator | The door is chosen when the entry's key equals ANY inward `from_key`, which includes mid-chain nodes. `DoorMap.anchors` (the door group's egress keys, `interior_paths.py:49-53`) is the exact root test. Repro: a map where door X's egress camera key is also an inward from-node of door Y, with Y sorting first. An entry on X then opens Y's path. Use `root in dm.anchors` (with edges from root). |
| L3 | LOW | `person_sighting.py:1083` (`_on_interior_person_state`) | edge case | `unavailable -> on` and `None -> on` (add/restore) count as on-edges. A camera that recovers with someone in view stamps a hop that is not an arrival. Require `old_state.state == "off"`. |
| L4 | LOW | `person_sighting.py:1139` vs `:1171` | trip-wire independence | The `interior_room_records_zero` numerator is appended after `_ensure_interior_groups()` and the liveness loop. `pure_twin_groups` / `twin_pair_for_device` / `frigate_member` (`:1012-1050`) are not wrapped. If any of them raises, every tick ends in `tick_errors`, the numerator is never counted and no page fires. Compute the numerator first, in its own try. |
| L5 | LOW | `person_sighting.py` `_path_tick` (deviation 6) | fire-check masking | A path record with `hops=()` is written for every mapped entry. This is acceptable per the plan text, but it means `interior_path_zero` cannot see a dead hop detector (for example a listener that never binds). Add a diagnostics counter for hop-less records, and optionally a trip-wire on hop-less share. |
| L6 | LOW | `const.py` `INTERIOR_VISION_EXCLUDED_ROOM_TYPES` | REUSE miss | String literals; the plan says REUSE `ROOM_TYPE_BEDROOM` / `ROOM_TYPE_BATHROOM` (`const.py:583, :585`). The values are equal today. |
| L7 | LOW | `sensor.py:4329`; `interior_vision.build_room_records` | no runtime guard | D0(a) asserts one group per area, but nothing checks it at runtime. With two groups in one room, the sensor's `rooms` dict silently keeps one, and each record subtracts the same `named` set. Repro: bodies A=1, B=1, named {x} gives unnamed 0+0 where the truth is 1. Add a counter (`groups_sharing_room`) to diagnostics. |
| L8 | LOW | `interior_vision.group_bodies_nvr` + census `_stream_last_reading` | stale source | For a Frigate member, the reading comes from the person-COUNT sensor (`camera_census.py:2090-2097`) while LIVE is judged on the binary entity. If the count sensor is unavailable and the binary is live, the old count stays in `by_entity`. `_stream_last_reading` is never pruned. The record also uses the raw reading of a watchdog-discounted (stuck) camera, which is spec-faithful (§7) but shows a stuck camera as `unnamed_present` indefinitely. Display only; consider an age guard against `census_as_of`. |
| L9 | LOW (plan) | `interior_vision.chain_windows:230` | spec-faithful edge | For a missed camera u, the child window opens at u's bound, not at E. Repro: staircase misses, entrant on stairs_top at E+40 is outside [E+63, E+135] and is dropped. This matches the plan text (§9.D5), so it is a plan question, not a build defect. |
| L10 | LOW (design) | `switch.py` `InteriorVisionSwitch` + reload-suppress key (deviation 3) | knob semantics | Once the switch has a stored state, the options field `interior_vision_enabled` has no effect: a stored state wins and the key is reload-suppressed. This matches the `CrossingVisionCensusAuthoritySwitch` pattern and the plan. The options-form description should say it is the first-boot default only. |

## Cleared (holds because)

- **Status precedence** `interior_vision.build_room_records`: missing (bodies None) > unnamed_present (unnamed >= 1) > confirmed (bodies >= 1) >
  ble_unconfirmed (bodies 0 and a BLE source in `named_map`) > empty. Truth table checked:
  - bodies 2, {ezinne} gives unnamed_present (unnamed 1);
  - bodies 2, {ezinne, jaya} gives confirmed;
  - bodies 1, three named gives confirmed (unnamed clamped to 0);
  - bodies 0, BLE {jaya} gives ble_unconfirmed;
  - bodies 0, face-only named gives empty;
  - no LIVE member gives missing, with bodies and unnamed None.
- **Missing never 0**: `group_bodies_nvr` skips any non-LIVE member and any LIVE member with no reading, and returns None when nothing remains. A vision count is ignored when `nvr is None`, so vision never resurrects a missing group (INV-IV-MISSING). Deviation 7 (LIVE with no reading gives missing / `no_reading`) is correct: unknown is not 0.
- **LIVE-only bodies**: a held or released view returns before any state check (`member_liveness`). A held member's frozen value is never read, even though `_stream_last_reading` still holds it.
- **Vision replaces**: `bodies = vis`, never `nvr + vis`; provenance is `agree` only when equal.
- **place_named**: one entry per slug. BLE wins outright: a face for a slug already placed by BLE is skipped, even when that BLE room has no camera, which is the N5 repro. The newest fresh face otherwise; `age > fresh_s` and future timestamps (more than 1 s) are skipped. BLE and face slugs share the one id rule: `slug_of(display name)` against the census `canonical_person_slug` ∈ `tracked_person_slugs`.
- **persons_in_room** (`person_coordinator.py`): reuses `get_room_occupants` (same names). `active_only` drops non-ACTIVE persons via `data[name]["tracking_status"]`. `phone_trustworthy` resolves by URA's own unique_id and fails open. It returns a tuple, and `""` gives `()`. Deviation 2 (lazy import, not moved) is fine: same function, no second copy.
- **chain_windows**: cumulative windows checked against the plan's garage_a chain. Staircase at E+60, stairs_top at E+130 and playroom at E+195 give three hops. A missed node passes its close on as `t_u`. BFS depth is capped at `max_hops`. Sibling parents at the same depth union their windows, and an already-reached node is not revisited.
- **Crossing cursor**: `get_crossings_since` is `ts >= t`. The cursor advances to the max ts, and the `source_ref` set at that exact ts dedups. Append order equals crossing-ts order: `_resolve_direction` has no await before `_record_crossing`, and every crossing has the same 45 s delay. So out-of-order loss needs two `_resolve_direction` runs to interleave, which cannot happen.
- **n source order**: a G3 `people_count` int (bool excluded), then an arrival record with a matching `source_ref`, then the first hop. The order is right; the fallback value is M3.
- **hist_len**: `(4 x 180 + 15) / 10 + 2 = 75` ticks (750 s). This covers the worst close, 4 x `EGRESS_PATH_BUFFER_S` + pad + one tick, because path-map rule 8 caps `lag_p90_s` at `buffer_s` and the default window is 30 s.
- **records_zero numerator**: any interior entity LIVE with reading > 0 counts. Records are written whenever any group exists (a missing record still counts as built), so the wire fires only on no groups or a failed build, which is the intent. Latches reset on recovery; NM dedup is per day.
- **Switch restore matrix**: stored `on` gives on; stored `off` gives off; `unavailable` / `unknown` / no stored state gives the options value (default True). `is_on` reads the `hass.data` key, which is set on add, and falls back to the default before add.
- **Deviations 1, 4, 8**:
  - 1: field mappings are built in the pure core and records are constructed only in `_emit_unnamed` (R7 owner).
  - 4: the extra knobs (`INTERIOR_ONEDGE_RING_MAX`, `INTERIOR_ZERO_WINDOW_H`, `INTERIOR_VISION_SWITCH_HASS_KEY`) are named and rung 1, with a reason.
  - 8: the `MEMBER_CLASSES` entry for a class not yet built is harmless to local correctness. Framing C should confirm that the guard does not treat a missing class as vacuous.
- **Registry rule**: no inference from entity names anywhere in the diff. Camera device, twin group, area and platform come from the registries. Rooms use URA's own config names, persons the one `person_ids` rule, and the phone-left-behind sensor URA's own unique_id. The on-edge listener tests state `on` only.

## Bug-class frequency

| Class | Count |
|---|---|
| Trip-wire numerator / fire-check gap | 3 (M2, L4, L5) |
| #53 one missed site (rebuild trigger) | 1 (M1) |
| Spec deviation, arithmetic | 1 (M3) |
| Missing != 0 / stale source | 2 (L1, L8) |
| Discriminator / edge case | 2 (L2, L3) |
| REUSE miss, runtime guard, design notes | 4 (L6, L7, L9, L10) |
