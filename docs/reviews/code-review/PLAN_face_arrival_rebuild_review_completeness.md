# Plan review: FACE-ARRIVAL-REBUILD-1, framing 1 (completeness)

Plan: `docs/planning/PLANNING_face_arrival_rebuild.md` rev 1, branch `plan/face-arrival-rebuild` (HEAD 187a1673).
Reviewer: ura-reviewer, Tier-3 plan review, framing 1 = completeness (independent re-enumeration). Read-only on code.
Date: 2026-11-12.

Read first: `IDENTITY_FUSION_CAMERAS_MANUAL.md` (outline plus §1, §2, §4.3, §4.5 and §5.5 in full),
`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (header entries, §1 rows 84-91, §10 ledger headings). HVAC state of play:
read only the pre-arrival rows (§2 trigger table, §4 borrow rows), not the whole doc. This plan changes no HVAC logic.
If the HVAC finding below (F9) turns into a logic change, the full read is required first.

Verdict: **FIX-PLAN.** Two HIGH findings: a false physical claim about the garage pick, and a concept split in the
egress source. Five MEDIUM. INV-ACCESS holds over the four sinks once D3 is built, with one fail-open gap to close (F4).

---

## Ranked findings

### F1 HIGH: `garage_a_camera_person_detected` is a URA entity, not UniFi Protect (claim false)
Registry (`.storage/core.entity_registry`, read-only): `binary_sensor.garage_a_camera_person_detected` has platform
`universal_room_automation` and sits on device `2e01cbf8…` "Garage A" (URA room device, identifier
`universal_room_automation/01KH050K…`). It is the D3 fused per-room `CameraPersonDetectedSensor`
(`binary_sensor.py:1520`, `camera_resolver.py:6`). The plan states it as fact in §0, §3.5, D0-P1 and §13 item 2.
Consequences the plan does not cover:
- `_device_derived_face_entity_id` on this pick resolves through the URA room device, which owns no Frigate face
  sensor. Only a string or stem match would reach `sensor.garage_a_last_recognized_face_2` (exists, Frigate), and the
  `_2` rule forbids string-building.
- The fused sensor covers the room's configured cameras (Frigate and maybe Protect). The right resolution is "the
  room's configured cameras -> their face sensors". The plan names no such path.
- Garage A is a door camera. If it resolves, one recognition produces an `interior_pick` sighting and an
  `egress_entry` sighting under different stems, so the (slug, stem) dedup does not collapse them (F8).
Fix: correct the claim. Specify how a URA fused room sensor resolves to faces, or exclude URA-platform picks and
report them as unresolved. Rewrite D0-P1 and §13.2.

### F2 HIGH: an egress `person_id` is not always a face, yet D1(c) makes every one a `FaceSighting` (#63 concept split)
`transit_validator._resolve_egress_face_identity` attaches identity from BLE alone. At `transit_validator.py:1655-1682`
it returns `(slug, BLE_TRANSITION_ONLY_CONFIDENCE, CENSUS_AGREEMENT_SINGLE)` with `contributor_engines ["ble"]` and
`provenance "ble"`. `BLE_TRANSITION_ONLY_CONFIDENCE = 0.72` (`const.py:3378`). That clears
`FACE_ARRIVAL_EGRESS_MIN_CONF = 0.6`. The bus event at `:2016-2031` carries no provenance field, so the producer
cannot tell a face from a BLE attach.
Effects:
- BLE crossings are counted as face sightings, which inflates the trip-wire numerator and could mask the zero-fire
  signature.
- A BLE-identified entry dispatches `SIGNAL_PERSON_ARRIVING(source=camera_face)`. In the access consumers this fails
  safe (it is held for a non-face edge), but the source label is false. HVAC may also get a duplicate of the
  `ble` arrival that `person_coordinator.py:1132` already sends for the same transition.
- `_face_suppressed_now` would suppress BLE-derived identities.
Fix: emit an egress sighting only for face-backed identities, which needs a provenance field added to the bus event
(today §8 says "no change to the egress producer"), or keep `egress_*` out of `FaceSighting` and give it its own
`sighting_source` and arrival `source`. State which in the plan.

### F3 MEDIUM: "Oji is unmapped" holds for presence only; the census mapper already maps him
`camera_census._canonical_person_slug` (`:3903-3960`) matches by first token, so "Oji" becomes `oji_udezue` when that
first name is unique among tracked persons. Only `presence._find_person_entity_from_face` (`presence.py:5644-5672`)
needs the alias. The plan lists both as REUSE for name to person (§1.2) and does not say which one D1 uses. The
answer changes `test_alias_maps_oji` and `face_sighting_unmapped_names`. §1.1 and §13.1 also say the alias "fixes
census", which is false.
Fix: pick one mapper. The recommendation is `_canonical_person_slug` plus `face_alias_person_slug`, which is
fail-closed on first-name collisions. Correct §0, §1.1, §13 and the test name. Keep the alias as optional hygiene.

### F4 MEDIUM: the security face gate has no state source and no fail-closed rule
`nonface_arrival_source` needs `tracker_arrivals` and the Bermuda stamp ring. Both live on the lock regime instance
(`security_lock_regime.py:1208` `_arrival_edges`, `_bermuda_moves`). Security holds `self._lock_regime`, which stays
`None` when `_async_setup_lock_regime` raises (`security.py:670`, `:710-728`). §3.4 says "shared helper via
`arrival_edges.nonface_arrival_source`" but does not say where security gets its edges.
Fix: specify that security calls `self._lock_regime._face_arrival_corroborated(person, at_ts=sighting.ts)` (or a
public wrapper), and that a missing lock regime means reject (fail-closed). Add a test: lock regime None, toggle on,
camera_face arrives, expected arrivals stay empty. Note that security, unlike the lock regime, has no held-face
re-check. A face that comes before its Bermuda edge is rejected for good. That is acceptable, but say so, because the
D3 "Verify" line implies symmetry.

### F5 MEDIUM: the D2 dispatch loses the Presence observation-mode gate (#23)
The v3.19 site gates dispatch on `self.observation_mode` (`presence.py:5624-5636`), and so does geofence (`:5285`).
§3.3 and D2 do not carry the gate over. Without it, the new site dispatches to HVAC and the lock regime while
Presence is in observation mode. Fix: state the gate and add `test_observation_mode_suppresses_arrival`.

### F6 MEDIUM: the trip-wire denominator does not exist as described ("REUSE" is wrong)
`_frigate_face_msg_face_count` is one global int, incremented at `camera_census.py:5510` before stem resolution, and
it counts drops too. There is no per-picked-stem count. The `face_sighting_zero` rule ("≥ N named face messages on
picked stems") needs a new counter written at the latch loop (`:5591-5593`). Also, one message can latch several
stems (`for stem in base_stems`). The plan says "call one callback (stem, name, now)" without saying whether it is
called per stem or per message. That decides the sighting count and the dedup.
Fix: mark the counter BUILD, place it at the latch write, and define the hook call as per stem or per message.

### F7 MEDIUM: egress arrivals into HVAC need a reconciliation with manual §5.5 doctrine, escalated to the operator
Manual §5.5(a): egress identity may "NEVER escalate or actuate", and security suppression needs ≥ 0.9. D2 sends
`egress_entry` at ≥ 0.6 into an actuating consumer (HVAC pre-cool S12 borrow and pre-arrival fans). With an edge, D3
also lets a ≥ 0.6 face add an expected arrival, which is a suppression. The table in §5.5(b) has no comfort class.
The manual's own rule: a contradiction escalates to the operator and is not silently overridden. The plan's §3.4
quietly adds the comfort class. Fix: add a "manual §5.5 amendment" item to §13 (operator decision) and to D5's doc
updates. Also note that in the expected-arrival case the non-face edge, not the face, does the suppressing.

### F8 LOW: double sightings from door cameras
A door camera reachable both as a pick (interior source a or b) and as egress (source c) produces two sightings with
different stems and `sighting_source`. Arrival debounce per person (600 s) collapses the arrivals but not the
sightings, which skews `face_sightings_today` and future consumers. Fix: define cross-source dedup on
(slug, physical camera) or document the double count.

### F9 LOW: HVAC doc drift (code wins, report only)
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md:175` cites `_handle_person_arriving` at `hvac.py:4186`, subscribed at `:1196`.
Code has `:7212` and `:1511`. Fix the doc in D5's same-commit doc update (D5 already touches this doc).
Separately, the sibling cycle HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1 (`plan/hvac-precool-standdown`) changes the same
pre-arrival pre-cool. This plan's L4 expects "an HVAC pre_arrival row (or explain the HVAC skip reason)". Name the
sibling's stand-down as an expected skip reason, and set build order.

### F10 LOW: §5 sink list is incomplete (services)
`handle_disarm` is also reached from the service handler at `__init__.py:6595`, and `add_expected_arrival` through
`__init__.py:6612-6621` to `security.py:2511`. Both are operator or automation services, not face paths. Listing them
makes the D re-grep reproducible. Also leave a scope note for the perimeter D10.5 face de-escalation (a suppression
sink, ≥ 0.9). It is unchanged here because it listens to the bus egress event, not to sightings.

### F11 LOW: D2 drops the tracker face fields
`tracker._last_face_recognized` and `_last_face_time` (`presence.py:5606-5607`) are read by `sensor.py:5979-5981`
and `presence.py:1031-1032`. §3.3 keeps only the counter. Fix: keep the fields updated per house zone, or retire them
as KEEP + DOCUMENT.

---

## Verified claims (holds because)

| Claim | Result | Evidence |
|---|---|---|
| `security.py:2412-2419`: face-only expected-arrival leak | **CONFIRMED** (latent, toggle default off) | `_handle_person_arriving_signal` checks only `CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED`, never `source`, then `add_expected_arrival(person, 5)`. `SanctionChecker.check_entry` returns SANCTIONED for ANY non-empty `_expected_arrivals` (`:302-303`). That is person-agnostic, so one face sanctions every door entry for 5 min. |
| Oji maps to no person entity | **PARTIAL** (F3) | `person.oji` absent, `person.oji_udezue` present. The presence mapper fails without an alias; the census mapper succeeds. |
| `garage_a_camera_person_detected` is Protect with no face name | **FALSE** (F1) | URA platform, fused room sensor. |
| A pre-existing path where camera body evidence alone can unlock | **CONFIRMED** | `presence.py:1347-1369`: `has_people = census_count > 0 or any_zone_occupied`, AWAY becomes ARRIVING. Lock `_edge_decision` (`security_lock_regime.py:864-865`) returns `"arriving"` → release, so `_release("house_state:arriving")` (`:809`), which unlocks garage lockout entities. Also `security.py:192` `"arriving": DISARMED`, so auto-follow `handle_disarm` (`:1452`). `_away_release` is NOT on this path (callers `:1052, 1066, 1080, 2114, 2150`). Carding as LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 is correct. |
| `SIGNAL_PERSON_ARRIVING` producers | holds | `presence.py:5297` geofence, `person_coordinator.py:1132` ble, `presence.py:5634` camera_face. No others (`switch.py:3573`, `presence.py:1783`, `const.py:3505` are comments). |
| Consumers | holds | `hvac.py:1511`, `security.py:817` (which feeds the lock regime first, `:2389-2393`), `music_following.py:281`. |
| `_release` / `_away_release` face exposure | holds with D3 | Every `camera_face` passes `_face_arrival_corroborated` before `_apply_arrival` (`:1017`), and the held re-check (`_on_pc_update`) re-tests it. The other `_release` callers (P1 person `:1213`, approach zone `:1216`, proximity `:1340/:1547`, house state `:809`, backstop, hazard, kill switch) take no name input. |
| `handle_disarm` from arrival | holds | Only the auto-follow `:1452` (house state) and the service `__init__.py:6595`. |
| HVAC compound-zone counter miss | holds | `presence.py:5617` string equality. The counter is display only (`hvac_zones.py:1278`). |
| Music `zone` key | holds | `music_following.py:563` |
| `zone_cameras` readers | holds, plus one | `presence.py:2389`, `hvac_zones.py:540/1277`, plus `memory_facade.py:94` (a key list, not a consumer). |

## INV-ACCESS checklist (post-D3, as planned)

| Sink | Status |
|---|---|
| Garage lockout `_release` | PASS (existing gate). Body path pre-existing and carded, not widened by sightings (§8). |
| Away-lock `_away_release` | PASS (same gate). |
| `add_expected_arrival` | PASS only if F4 is fixed (fail-closed when the lock regime is None). LEAK today (latent). |
| `handle_disarm` | PASS (no arrival caller). |

## Parked-plan triggers this cycle would fire
- PLANNING_ble_seen_at_home_arrival §9 (parked): no trigger. It is BLE-keyed.
- D1-PROTECT-FACE-BRIDGE-ADDON-1: F1 makes the Protect premise moot for the garage pick. Its trigger is not fired.
- ZONE-CAMERA-DISCOVERY-DEVICE-AREA-1: not fired (§8 keeps the tracker untouched). Removing the face branch at
  `:5478-5481` must leave `:5466-5471` byte-identical.
- HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1 (sibling plan, live): interacts (F9).

## Must-fix before build dispatch
F1, F2, F3, F4, F5, F6, F7 (F7 means an operator decision recorded in §13).
