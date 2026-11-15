# Plan review: camera area map device fallback (ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1)

Plan: `docs/planning/PLANNING_camera_area_map_device_fallback.md` at fb43b22d (develop). Reviewer: ura-reviewer,
framing 1 (adversarial plan review) + framing G (goal fidelity). Read-only. Date 2026-11-15.

Read before review: the plan (complete); `docs/architecture/SENSOR_FLEET_CLASSES.md` (complete);
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (header entries incl. S2 "dead input holds" and ship 3b, §1
residency row, §2 ladder steps 0-2, §10 ledger titles 1-42); HVAC state of play occupancy entries (header 2026-11-14
entries, §3 gate-bypass table row); charter `ARC_DRIFT_ANALYSIS_identity_vision_census_2026_11_13.md` (goals section).
No ledger claim is re-asserted (in particular §10 #12: path α does not read zones, and this review relies on that).

## Verdict: PLAN-FIX-REQUIRED

Two HIGHs, both cheap to fix in the plan, both on the AWAY path the charter's hard constraint protects.

## AWAY-latency answer (framing G)

**Mechanism.** `PresenceCoordinator._run_inference` builds `any_zone_occupied_for_empty` and
`any_indoor_zone_occupied` from tracker modes (`presence.py:7691-7765`). A tracker reads OCCUPIED through Tier 2 when
`_any_camera_occupied` is true (`presence.py:807-809`), which holds for 300 s after the last camera `on`
(`_CAMERA_OCCUPANCY_TIMEOUT_SECONDS`, `presence.py:150`, `:819-850`) and, if the camera's stream dies while holding, for
up to `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S` = 900 s more (`const.py:6158`, `presence.py:840-848`). In `infer`:
- nobody-home (`presence.py:1243`) needs `not _zone_occ_for_empty`, so it is delayed by the tail;
- path α (`presence.py:1290-1301`) reads no zone, so it is not delayed (plan's claim correct);
- path β reads `any_indoor_zone_occupied` plus its indoor-clear tick debounce, so it is delayed too. **The plan omits
  β** (§1.6 Delivery, §7 item 1 say only "nobody-home").

**How often it bites.** Only when α cannot fire: `camera_input_degraded`, or a tracked person not ACTIVE-away (LOST, β
territory), with census 0. A normal departure (phones go `not_home`, interior cameras clear) goes through α and is
untouched. The rate is unmeasured: the plan's D0 (e) counts "delayed AWAY edges" but does not split them by
`veto_path`, so it cannot tell an α edge (never delayed) from a nobody-home / β edge. The bound is also wrong: "up to
300 s" is 300 s + up to 900 s dead hold + β debounce.

**Is it a breach?** On the dominant path, no. On nobody-home / β it is a real slowdown, and the plan sets Q5's default to
"accept". A hard constraint should not carry an accept-by-default. And the delay buys nothing. While an interior camera
reads `on`, the census already counts that body (`camera_total` > 0 blocks nobody-home, `unidentified_count` > 0
blocks α). What the zone tier adds to the AWAY decision is the 300 s tail, plus egress and perimeter cameras, which
should never block AWAY.

**Recommended fix (keeps AWAY speed byte-identical to develop).** Add one tracker property (e.g.
`occupied_excluding_camera`, BLE or Tier 1 only). The AWAY decision inputs read it: the OCCUPIED limb of
`any_zone_occupied_for_empty`, `any_indoor_zone_occupied`, and the `has_people` term evaluated while
`current_state == AWAY` (the ARRIVING trigger). The camera tier keeps feeding zone display, `raw_occupied` / WAKING,
the night limb if wanted, and D6. Pin it with a test: same evidence with D3 on and off gives the same AWAY edge time
on nobody-home and β. This matches the option the brief names ("the zone tier never delays the AWAY decision path"),
and it removes Q5.

**ARRIVING while AWAY.** `has_people = census_count > 0 or any_zone_occupied` → ARRIVING (`presence.py:1411-1432`). When
α's conditions hold, α returns None first ("already away", `:1296-1298`), so the zone tier raises no new ARRIVING. New
ARRIVING edges are possible only when α is off (camera fleet degraded, or a LOST tracker). In that state a
perimeter or egress camera filed in a room's device area (a delivery person, a passer-by) raises ARRIVING, and the
900 s re-arm cooldown bounds the repeats (`ARRIVING_REARM_COOLDOWN_S`, `:230`). The fix above closes this too.

**Census going down (charter "census accuracy", "guests counted via vision + NVR with deconfliction").** The direction
is on-goal. Per-area max plus BLE cancel IS the designed deconfliction, so D4-CORRECT delivers the charter and
D4-KEEP keeps a known double count. Two caveats belong in the plan:
- Under-count risk: the two NVRs watching one room collapse to max, which is correct. Two cameras in one area
  watching different people also collapse to max. D0 (d) should report this per area (a big area with two cameras).
- A downward census opens α more often. That fits "fast AWAY" only if the drops are real. D0 (d) already asks who
  was home at each 0-crossing, which is good. Make it a hard gate: zero contradicted 0-crossings.

## Findings (ranked)

| # | SEV | Where | Finding | Fix |
|---|---|---|---|---|
| 1 | HIGH (G, hard constraint) | plan §1.6, §7.1, §8 Q5; `presence.py:1243`, `:7704-7765`, `:819-848` | The zone tier slows nobody-home AND path β (β omitted). The bound is 300 s + 900 s dead hold, not 300 s. Q5 accepts the slowdown by default. D0 (e) is not split by `veto_path`. | Exclude the camera tier from the AWAY decision inputs (above) and pin it byte-identical. Correct the §7 text. D0 (e) splits edges by veto_path. |
| 2 | HIGH (#63 coincidental equality / self-corroboration) | `camera_census.py:2206-2221`, `:2522-2560`; plan §4 D4 (iv), INV-CENSUS-DOWN | `_any_zone_occupied_snapshot` reads `tracker.mode == "occupied"`. After D3, a Frigate person sensor `on` makes its own zone occupied, which then "corroborates" the same camera's divergent count. Repro: Frigate count 1 (ghost), Protect 0, no face, no BLE persons, Tier 1 quiet. Develop: uncorroborated → min-wins 0 (`DEFAULT_CENSUS_DIVERGENCE_DOWNGRADE = True`, `const.py:2463`). After D1+D3: zone OCCUPIED from that camera → corroborated → 1 kept → `census_count` 1 → nobody-home blocked. This disarms the guard built for the Frigate-ghost GUEST incident, and it happens in an empty house, exactly the AWAY window. INV-CENSUS-DOWN names `_calculate_house_census` as a census path that never rises, so as written it is FALSE with D3 on. The plan calls (iv) "indirect" and leaves it to D0 to measure; it is direct and needs no measuring. | Corroboration reads the camera-free tracker view (same property as #1). Restate INV-CENSUS-DOWN as holding with D3 on, and add the repro as a test. |
| 3 | MEDIUM (#53 scope) | `camera_census.py:1107` (`all_configured = room + egress + perimeter`), `presence.py:5246-5256` | The area map holds egress and perimeter cameras. After D1, any whose device area is a URA room's area (garage, foyer, porch) registers in that zone's tier. These are the cameras that see every departure. The plan's C5 row and D3 do not say so, and D3b filters by device class only, never by role. | D0 (b) gives each camera's role. Decide in the plan: zone tier registers room-role cameras only, or rely on #1. State it. |
| 4 | MEDIUM | plan D0 (e), §3.2 C5 | C5 lists SLEEP night_raw and WAKING as consumers, but D0 (e) measures only AWAY and ARRIVING. A kitchen or hallway camera at 05:00 can trigger the sustained WAKING gate earlier (`any_zone_raw_occupied`, `presence.py:7719`), and a camera in its timeout holds SLEEP through `_zone_night_raw`. | Add WAKING edges moved and SLEEP raw-hold minutes to D0 (e). |
| 5 | MEDIUM | plan §8 Q1, Q5, D4 branch rule | Some gates are not sized: "few delayed AWAY edges" (Q5) has no number; D4-KEEP's trigger, "a phoneless person was home", has no named ground-truth source. | Q5 goes away with #1. For D4, name the oracle (person state + BLE + Tier 1 in that area) and the threshold (0 contradicted crossings). |
| 6 | LOW | plan §1.1, §2 INV-MAP | There are six `CameraInfo(` construction sites (`camera_census.py:677, 919, 991, 1008, 1160, 1188`). The plan names five and correctly skips :919 (already `resolve_area_id_for_entity`, `:918`). INV-MAP's site list should name :919 as already compliant, so a test covers all six and nobody "fixes" :919 behind the kill switch. | One line plus one test row. |
| 7 | LOW | INV-HOLD-OPT-IN, D2 tests | The gate placement holds. `_camera_override_live_person_sensors` has one occupancy consumer (`coordinator.py:4492`). Its only other reader of the lookup is the stream tick extras (`:2623`), which promote dead extras into the exclusion set and never set `STATE_OCCUPIED`. Add a test that a default room with a DEAD extra camera (held view) stays vacant, so the dead-input-holds rule cannot reach a default room through the substrate later. | One test. |

## Cleared (holds because)

- **Census is a house-wide SUM today (plan §1.3 #1 correct).** Null-area contributions go to `unassigned_raw` and are
  summed (`camera_census.py:6356-6366`). Step 3 never cancels them (I3 comment, `:6386-6390`). The census reads
  `CameraInfo.area_id` (`:2078`, `:6302`), not `_cameras_by_area`. On the census arithmetic, max ≤ sum and
  `min(area_max, ble)` ≥ 0, so it can only go down. The exception is the upward path in finding #2.
- **Consumer enumeration.** `get_cameras_for_area` readers: `sensor.py:2839`, `presence.py:5240/5248`.
  `get_person_sensor_for_area`: `camera_stream_health.py:921`, which feeds the hold, the stream tick extras and
  `room_stream_input_entities` (3b Wr). `CameraInfo.area_id` readers: `camera_census.py:2078, 3072, 6302` plus logging.
  `transit_validator.py:259` reads the resolver's enumeration, not CameraInfo, so it is not a consumer. D6 Source 3
  reads `zone.zone_cameras` (`presence.py:2467`), not the map. This matches plan §3.2. No consumer is missing.
- **Gate in the consumer, not the lookup.** This is right: the lookup also feeds Wr, has_camera and the stream extras.
- **Face arrival is not a consumer** (plan §1.3 #2). This matches the presence doc's §1 FACE-ARRIVAL-REBUILD-1 entry.

## Invariant checklist

| Invariant | Verdict |
|---|---|
| INV-MAP | PASS as planned (add :919 to the test set, #6) |
| INV-HOLD-OPT-IN | PASS: falsifiable, single gate site `coordinator.py:4491-4492` (#7 test add) |
| INV-ZONE-PERSON | PASS for device class; role is unaddressed (#3) |
| INV-CENSUS-DOWN | LEAK with D3 on: self-corroboration through `_any_zone_occupied_snapshot` (#2) |
| Charter hard constraint (fast AWAY) | α PASS; nobody-home / β LEAK, up to 300 s + 900 s (#1) |

## Must-fix before build

1. #1: camera-free AWAY decision inputs; correct the §7 text and Q5; split D0 (e) by veto_path.
2. #2: camera-free corroboration snapshot; restate INV-CENSUS-DOWN with D3 on; add the repro test.
3. #3: decide the camera roles allowed in the zone tier.
4. #4, #5: extend D0 (e); name D4's oracle and threshold.
