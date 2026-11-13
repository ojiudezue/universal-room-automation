# Plan review, rev 8: completeness of the direction-aware egress identity rule

Plan: `docs/planning/PLANNING_person_sighting_layer.md` rev 8 (branch `plan/face-arrival-rebuild`, e89ef30e).
Framing: COMPLETENESS (Tier 3 plan review 1 of 2). Scope: §2B, D7, D8, D0-P7, §20.
Reviewer read completely first: `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`,
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`,
`docs/planning/FIXTURE_camera_paths_interior.md`. Code read-only. Live config read from
`.storage/core.config_entries` on the Samba mount.

**Verdict: FIX-PLAN.** 3 HIGH, 7 MEDIUM, 5 LOW. The census-union invariant holds as specified. INV-ACCESS
holds for the new `camera_egress` signal path, but D7's storage choice would widen the corroboration
surface. The rule's main comfort consumer (HVAC) silently drops the new source. The guards do not stop
the 10-24 failure they are named for.

## Re-enumeration (greps, not the plan's list)

| Surface | Sites found | In plan §2B.5 / §5? |
|---|---|---|
| `ura_person_egress_event` listeners | `sensor.py:4746, :4877, :4987, :5037` (4 displays, read only `person_id` / `direction` / `egress_camera` / `timestamp`); `perimeter_alert.py:1006` (D10.5) | yes |
| `person_entry_exit_events` readers | `database.get_entry_exit_events_since` (`:4654`, display rehydrate, `sensor.py:4725, :4859, :4931, :5080`); `find_unnamed_exit_crossings` (`:4684`, exit backfill, NULL rows only); `backfill_entry_exit_person_id` (`:4723`) | displays yes; DB-side role loss NO (M2) |
| Egress outcome deque (the `vetoed` label) | writer `camera_census._note_egress_identity_outcome` `:3603` (RAM, 24h prune, `:1444`); reader `sensor.py:3936-3956` attach / ambiguity / abstain rates, counts only `"attached"` | NO (M2) |
| `_egress_identity_last_attach` | writers `transit_validator.py:1657, :1705, :1769, :1908`; readers `:2084-2088` (union provenance), `sensor.py:3978` (display) | partly (M2) |
| Census union register | ONE site, `transit_validator.py:2091`; evict `:2095` | yes |
| `SIGNAL_PERSON_ARRIVING` producers | `presence.py:5297` (geofence), `:5634` (camera_face), `person_coordinator.py:1132` (ble) | yes |
| `SIGNAL_PERSON_ARRIVING` consumers | `hvac.py:1511` -> `_handle_person_arriving` with **source filter `:7231`**; `security.py:817` -> lock regime `:996` then `add_expected_arrival`; `music_following.py:281` (log only) | HVAC filter NO (H1) |
| Access sinks | `_release`, `_away_release`, `add_expected_arrival` (`security.py:2419` + service), `handle_disarm` (`:1452` auto-follow, service) | yes |
| `door_interior_neighbours` readers | `transit_validator.py:1113-1140` (load), `:2221` (direction), `arrival_edges.door_entry_areas` `:234` (lock corroboration areas, via `security_lock_regime.py:1371`), `perimeter_alert._near_areas` `:5112`, `config_flow._validate_door_interior_neighbours` `:4861` | NO (H2) |
| Out-of-repo consumers | none: grep of `ura-dashboard-pwa`, `ura-hospitality`, `ha-health-monitor`, `halo-panels`, `wall-tablet`, `shipwatch`, live HA `*.yaml` | n/a |

## Findings (ranked)

### H1 — HVAC drops every `camera_egress` arrival (Bug Class #53, one missed site)
`hvac.py:7231`: `if source and source not in self._pre_arrival_sources: return`. Live CM option
`pre_arrival_sources = ['geofence', 'ble', 'camera_face']` (read today; also plan line 101). The options
selector (`config_flow.py:8195-8201`) and `DEFAULT_PRE_ARRIVAL_SOURCES` (`hvac_const.py:350`) offer no
`camera_egress` value. §3.4 lists HVAC as "None to logic". So with `FACE_ARRIVAL_EGRESS_ENABLED` True,
every egress arrival is dropped at HVAC with a DEBUG line. HVAC is the consumer the D0-P7 go rule is
priced against ("else it adds nothing over geofence/ble to HVAC"), and L6 has no row for it.
Repro: switch on, Oji not_home, 0.9 face at garage_a, path 2 -> `SIGNAL_PERSON_ARRIVING(camera_egress)`
-> `hvac.py:7231` returns; no pre-arrival. Fix in plan: add `camera_egress` to the selector, the default,
and a migration or §13 operator action for the stored option. Or decide on purpose that egress arrivals
ride under the `camera_face` checkbox (a membership test against `CAMERA_DERIVED_ARRIVAL_SOURCES`). Add
a D8 test and an L-row.

### H2 — D7 stores the path map in `door_interior_neighbours`, which widens access corroboration and changes direction
D7: "extending the existing `door_interior_neighbours` option ... the exterior side reads the same
option's new `approach` list". That option already has three readers outside path scoring:
- `arrival_edges.door_entry_areas` (`:234`), which the lock regime uses for its Bermuda corroboration
  areas (`security_lock_regime.py:1371`, INV-ACCESS);
- `perimeter_alert._near_areas` (`:5112`), D10.5 de-escalation;
- `EgressDirectionTracker._get_interior_cameras_near` (`transit_validator.py:2221`), which picks the
  direction.

Putting the fixture's deep stages (Game room, Upstairs hallway, Master hallway) or exterior cameras into
that structure therefore:
- (a) turns those rooms' areas into "entry areas", so a Bermuda move between interior rooms corroborates
  a face for an unlock or de-escalation. The manual says interior room hops never count (§4.5).
- (b) changes the resolved direction, which the plan lists as a non-goal (§2B.4, §8). Repro, legal config:
  garage_a person edge at t, then a different resident on the upstairs-hallway camera at t+20. Today
  that crossing is `exit` or `ambiguous`. With the hallway in the garage_a list it becomes `entry`, so
  the DB row, the notification and the union register all change with the kill switch off. INV-NOOP
  breaks.
- (c) gets refused by the options validator (`config_flow.py:4878-4881`: values must be lists, else the
  key is dropped on save).

Fix in plan: store the path map under its own key (or a sub-key that the three readers never iterate),
and add tests pinning `door_entry_areas`, `_near_areas` and the direction result as byte-identical with
a path map present.

### H3 — G1-G3 do not replace the veto for the case they are named for (10-24 mislabel)
INV-CANDIDATE holds formally, but the safety claims in §2B.3 / §2B.5 do not.
- **G3 passes on a stale far fix.** The rule fails only when the fix is younger than 600 s AND farther
  than 2 km. A resident abroad whose app has not reported for 3 h, at 9,000 km, passes G3. Travellers
  report rarely, so this is the common case. G3 also never names its fix-timestamp source: HA
  `person.*` has no fix-time attribute, and `last_updated` moves with other trackers.
- **G2 is identity-blind.** It shows a body walked outside -> door -> inside, which a misnamed person
  does too.
- **G1 0.9 does not need two correct recognitions.** A face model that consistently confuses Jaya and
  Oji gives an independent-pair 0.9 (garage_a + family_room, distinct `base_stem`,
  `transit_validator.py:1858-1883`).
- **The anonymous-first branch never fires on a mapped door.** On a mapped door every candidate has
  already passed G2, so it is path-corroborated by construction. Every candidate there is named at once.

Repro: Oji in Lagos (`not_home`, last fix 3 h old). Jaya enters through garage_a. Frigate names her
"Oji" on garage_a and family_room, live legs, path_score 3. G1 = 0.9 passes, G2 passes, G3 passes (stale
fix). Result: `arrival_candidate` Oji, immediate "Oji arrived", an `egress_entry` sighting, and a D2
`camera_egress` arrival (HVAC pre-arrival in Oji's zones once H1 is fixed). Access holds (INV-ACCESS).
The comfort, notification and display consumers G1-G4 were meant to protect do not.

Fix in plan:
- G3 by speed plausibility: fail when distance / (fix age) implies more than a ground-travel bound, with
  the fix time taken from the GPS `device_tracker`'s own `last_updated`.
- A guard for confusable residents: abstain or demote when another resident whose face is confused with
  the named one is home, or BLE places the named person away.
- Anonymous-first notification for every candidate.
- Make D0-P7 report each guard's yield on the 10-24 window specifically.

### M1 — Named zones are misdescribed; switch-on behaviour changes for them undeclared
The veto is `state == "not_home"` only (`transit_validator.py:1846-1847`). Today a resident in a named
zone (`Work`) is fail-open `attached`. On entry that registers in the census union, which matches manual
§5.4: "a mislabelled entry crossing can still register a slug". So:
- the §2B.2 "Today: always vetoed" row is wrong for zones;
- "exit + zone -> vetoed (unchanged)" is wrong: today it is `attached` plus evict, and under rev 8 it
  becomes `vetoed`, so it no longer evicts and `person_id` is None.

Correct the table, state the zone deltas in INV-NOOP's switch-on text, and add a zone row to the golden
replay and the D8 tests.

### M2 — §2B.5 consumer audit misses three readers (Bug Class #53 / #63)
- **Attach rate.** `sensor.py:3950` counts only `"attached"`. Exit + home becomes `departure_candidate`,
  so `egress_identity_attach_rate_24h` drops with no change in reality. Say which new labels count as
  attached.
- **Stale provenance.** The candidate path must write `_egress_identity_last_attach` (with
  `provenance: face`) before the union and sighting reads at `:2084-2088`. Otherwise the previous
  crossing's provenance (for example `ble`) is reused, which breaks INV-PROVENANCE.
- **Role not persisted.** The DB row has no role column (`database.py:1090-1103`). After a restart the
  displays rehydrate candidate names as plain names (`sensor.py:4725`). Any 6.0.0 consumer keyed to DB
  `person_id` cannot tell a candidate from an attach, so `person_id` silently changes meaning. Either
  persist the role (that is a schema change, so the Tier 2-DB triggers apply) or document the new
  meaning of the column in manual §4.6 / §5.5.

### M3 — §3.3 rule 1 gates egress arrivals on the interior switch
Rule 1 requires `FACE_ARRIVAL_INTERIOR_ENABLED` for every D2 dispatch, while §2B.6 cites only rules 3, 4
and 6. Read literally, this couples the P3 and P7 go-gates. The skip reason `egress` (`:654`) is a
leftover from rev 2. Split rule 1 by branch.

### M4 — `path_score` has no named event source and no evaluation time
- Resolution runs once at +45 s (`transit_validator.py:1256-1275`).
- The tracker subscribes only to egress and interior cameras (`:983-1035`). The exterior stages (Back
  PTZ, G5, Utilities PTZ, Sonoff) are perimeter cameras with no store in the tracker.
- Deep interior hops (Stair top -> Game room -> Upstairs hallway) can land after +45 s.

D7 / D8 must name the producer (for example the `FrigateEventIngress` / perimeter linker edges) and the
evaluation horizon, and must say that resolution timing is unchanged (notification latency, INV-NOOP).
Without that, the D7 Verify example (score 3) may not be reachable at resolution time.

### M5 — Fixture and live egress config disagree
- Live `egress_cameras`: madrone_g6_entry, doorbell_lite, front_door_aerial, garage_a_2, garage_b_2.
- `door_groups`: `doorbell_lite -> garage_a`.

The fixture makes Doorbell Lite an EXTERIOR stage of the garage path. It has no table for garage_b (live
neighbours `[]`), front_door_aerial or patio, and it puts "Entry way" in two stages. The D7 Verify "the
egress stages resolve to the five egress cameras" cannot pass from this fixture. Define:
- how a camera that is both an egress camera and a stage scores;
- that a door with no map is `skipped`, per door;
- an operator action (§13) to settle the fixture against the live egress list.

### M6 — Stale sections contradict §2B
- §5 still calls perimeter D10.5 "out of scope ... does not change its reads", and its producer list
  omits the D2 `camera_egress` branch.
- §10 still says "Producer change in the egress path: one additive bus key, no reader changes
  behaviour".
- §6 and the INV-ACCESS text keep `CAMERA_DERIVED_ARRIVAL_SOURCES` = `{"camera_face"}`.
- §1.2a has no row for D7's learned default. That is a new in-process recorder-history reader run "at
  setup / weekly", which needs boot-load and restart-storm pricing in §10. No prior art reads the
  recorder for camera history in the hot setup path.

### M7 — D0-P7's data is thinner than the plan says
- `egress_identity_outcomes` is RAM-only with a 24 h prune (`camera_census.py:1444, :3613-3618`). It is
  not persisted, so the plan's "if persisted" is no.
- Vetoed rows have `person_id` NULL in the DB, so P7 is a replay over recorder face history, which is
  about 7 days.
- At about 3 door faces a day, ">= 1 candidate per week" can pass on n = 1.
- 20 hand labels cannot support a 0.9 precision bar: one error gives 0.95, zero gives 1.0.

Require a minimum number of labelled misrecognitions (or a Wilson lower bound) and say how many
would-be arrivals the window contains before the gate is judged.

### L1 — Portability (§20) misses house-specific defaults
- `DEFAULT_TRANSIT_CHECKPOINT_AREAS` (`const.py:3270-3276`: master_hallway, entry_way, garage_hallway,
  upstairs_hallway, stairs) are house area ids used as code defaults. They feed the interior camera set
  that direction and the path stages read. They degrade to empty on another house, but §20 should list
  them.
- `CAMERA_COVERED_ROOMS = {"Study A"}` (`const.py:1573`) is outside this surface. Note it only.
- §20's absolute "no code path builds an entity id from a slug" is contradicted by the plan's own
  `person.<slug>` reads (G3, rule 5, and the existing veto `:1842`). These are tracked-person round-trips
  and harmless, but the sentence should scope itself to camera entities.

No other house-specific constant was found in the egress / transit / arrival-edge surface. The camera
names in `camera_resolver.py` / `camera_census.py` are comments or docstrings; the `garage_a` /
`garage_b` literals in `sensor.py` / `number.py` / `__init__.py` belong to EV chargers.

### L2 — G1 "not synthetic-only" has no flag below 0.9
`_last_identity_synthetic_corroborated` is computed only in the 0.9 branch (`:1879-1883`). Define
synthetic-only for 0.75 as "any contributing leg synthetic". On this house 0.75 cannot arise from a
synthetic and a live leg, because legs dedup by (slug, engine, base_stem), `camera_census.py:3572-3588`.

### L3 — Knob semantics
`EGRESS_ARRIVAL_PATH_MIN = 0` ("path not required") still fails a negative `path_score`. Say whether 0
means "skip G2".

### L4 — Role side-channel needs an entry reset
If `identity_role` is passed the way `_last_identity_synthetic_corroborated` is, it needs the same
per-call reset (`:1397`). Otherwise a stale role could skip a real `attached` union register.

### L5 — Doc vs code contradiction (presence state of play §1, line 88)
The LOCK-ENTRY-AREAS-WRONG-OBJECT-1 correction says entry areas are always empty. The code was fixed in
b70e3a2f: `security_lock_regime.py:1371` and `perimeter_alert.py:5112` read `egress_tracker`. The doc was
corrected in this commit. This matters for H2: with real entry areas, widening the neighbour list does
widen access corroboration.

## Invariant checklist

| Invariant | Result | Evidence |
|---|---|---|
| INV-CENSUS-HOME (candidates never in census union) | PASS as specified | One register site (`transit_validator.py:2091`); the skip branch covers it. Conditional on L4 (entry reset) and M2 (fresh last_attach). |
| INV-CANDIDATE (candidates only when guards pass) | PASS formally; the protection claim fails | H3 (stale-fix G3, identity-blind G2), M1 (zones), L2, L3 |
| INV-ACCESS (no face/vision-only access release) | PASS on the signal path; LEAK risk via D7 | Lock regime membership plus the security gate cover `camera_egress`; disarm callers unchanged. H2 widens `door_entry_areas`. |
| INV-NOOP (switch off = byte-identical) | LEAK if D7 is built as written | H2(b): the direction change does not depend on the switch |
| Portability (§20) | Mostly holds | L1 |

## Must-fix before build dispatch
H1, H2, H3, M1, M2, M3, M4, M5. M6 and M7 should be fixed in the same pass (doc edits and a probe
spec).
