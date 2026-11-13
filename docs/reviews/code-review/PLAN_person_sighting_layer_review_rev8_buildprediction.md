# Plan review: person sighting layer rev 8, adversarial build-prediction

Plan: `docs/planning/PLANNING_person_sighting_layer.md` @ e89ef30e (branch `plan/face-arrival-rebuild`).
Framing: Tier-3 plan review 2 of 2, "what will the builder get wrong" for the rev 8 sections only (§2B, §2B.3,
§2B.4, D7, D8, D0-P7, §20). Read first: `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (complete).
Code read (worktree = develop + plan): `transit_validator.py` (:1020-1060, :1110-1140, :1256-1348, :1838-1860,
:1925-2215), `perimeter_alert.py:4940-5040`, `arrival_edges.py`, `hvac.py:881, :1436, :7222-7236`,
`security_lock_regime.py:340-400, :1011-1046`, `const.py:3305-3320, :3728-3740`, `config_flow.py:4861-4956`,
`docs/planning/FIXTURE_camera_paths_interior.md`.

**Verdict: FIX-PLAN.** 3 HIGH, 6 MEDIUM, 4 LOW. All are plan text fixes; none needs a redesign.

## HIGH

### H1. HVAC drops every `camera_egress` arrival (Bug Class #53, one missed consumer site)
`hvac.py:7231`: `if source and source not in self._pre_arrival_sources: return`. `_pre_arrival_sources` is CM config
(`hvac.py:1436`), default `["geofence", "ble", "camera_face"]` (`:881`), live value the same (plan :101). The plan's
§2B.6 sells `FACE_ARRIVAL_EGRESS_ENABLED` on HVAC lead time (D0-P7 go rule: "median >= 60 s ... else it adds nothing
over geofence/ble to HVAC"), yet nothing adds `camera_egress` to the default, the options-flow choices or the live
config. Builder outcome: D0-P7 passes, the flag is flipped, HVAC logs "Ignoring pre-arrival from source
camera_egress" and the feature delivers zero. The plan's §3.4 table row for HVAC (:672) says "None to logic", which
is the trap. Fix: add a D8 item (default list + options-flow choice + migration of the live CM option, or an operator
action in §13) and a test `test_hvac_accepts_camera_egress_when_listed` plus L-row "first egress arrival reaches
HVAC or is skipped with a reason other than `pre_arrival_sources`". Also note §3.3 rule 1 (next finding).

### H2. `path_score` cannot see most of the path at the moment identity is decided
Identity is resolved inside `_resolve_direction`, which runs from `async_call_later(ENTRY_WINDOW_SECONDS=45)` after
the egress edge (`transit_validator.py:1256-1275`, `:2011`). At that instant:
- Interior events are pruned at `max(ENTRY, EXIT) + 30` = 75 s (`:2254-2255`), and only `_interior_entities` are
  subscribed (`:1047-1055`). **No exterior camera is subscribed at all** (only egress binary/count sensors and
  interior). So the "+1 for an exterior-stage edge BEFORE the egress edge" in §2B.4 has no data source.
- Interior hops later than +45 s (Stair top -> Game room -> Upstairs hallway) have not happened yet. D7's own verify
  example (Back PTZ -> Garage A -> Garage hallway/stairs -> Stair top = 3) needs the exterior buffer plus a
  hallway->stair-top hop inside 45 s.
- Per-hop windows are "p90 of D0-P4 lag", unbounded by 45 s.

A builder will either (a) add exterior listeners ad hoc (new listeners, not in the plan's emission/listener
inventory, not covered by INV-NOOP's "no new listener" or teardown tests), (b) delay identity resolution (changes
DB write timing, notify timing, and the perimeter ±match window for every crossing, a non-goal violation), or
(c) silently score only what the 45 s buffer holds, so G2 fails most true arrivals and D0-P7's replayed score
(computed offline with full history) never matches live. Fix: state explicitly (1) the scoring horizon is the
resolution instant (egress+45 s) and hops whose window ends after it are not counted, (2) which exterior entities
are subscribed (the perimeter camera list via `CameraResolver` person legs), with buffer TTL = max approach-hop p90,
gated by `EGRESS_IDENTITY_DIRECTION_AWARE` and torn down in `_unsub`, (3) D0-P7 replays path_score with the SAME
horizon (else the go rule is computed on a score the runtime cannot produce). Add a test
`test_path_score_ignores_hops_after_resolution` and include exterior listener teardown in the existing teardown test.

### H3. "Extending `door_interior_neighbours`" breaks the existing option and its reader
Shape today: `{group: [entity_id, ...]}`, validated at `config_flow.py:4861-4900` (non-list value -> error "must be a
list of entity ids") and read at `transit_validator.py:1124-1134` (non-list/tuple value silently skipped). Keys are
entity ids, not `canonical_camera_key`; there is no order, no lag, no `approach`, no `same_view`, no branch.
If the builder changes the value to a stage object, (a) saving the options flow rejects it, and (b) any stored new
shape is silently dropped by `_load_door_config`, which makes `_get_interior_cameras_near` fall back to the FULL
interior list (`:2207` doc: unset -> full list) and changes direction resolution for that door. That is a live
regression of direction, not just of G2. Fix: specify a separate key (for example `door_paths`) whose absence leaves
`door_interior_neighbours` untouched, or a precise migration (version bump, both readers updated in the same commit,
validator accepts both shapes, test that the legacy list shape still yields today's neighbour list byte-identically).
Also specify the door key when `CONF_DOOR_GROUPS` is unset (today each stem is its own group).

## MEDIUM

### M1. §3.3 rule 1 blocks the egress branch
Rule 1 requires `FACE_ARRIVAL_INTERIOR_ENABLED` for EVERY dispatch; rule 2 adds the egress branch. With interior
parked (the expected D0-P3 outcome) and `FACE_ARRIVAL_EGRESS_ENABLED=True`, nothing dispatches. Also undefined:
`FACE_ARRIVAL_EGRESS_ENABLED=True` with `EGRESS_IDENTITY_DIRECTION_AWARE=False` (no candidates can exist; say so and
pin it with a test). Fix: rule 1 = `FACE_SIGHTING_ENABLED and (interior flag for interior_pick | egress flag for
egress_entry)`.

### M2. Learned map: where it is stored, when it is computed, and fresh-house behaviour
"Stored as config on the CM / integration entry ... learned at setup / weekly". Builder traps:
- Writing a learned map into entry options via `async_update_entry` fires the update listener (reload). The reload
  storm history (CM reload suppression allowlist, parent-entry reload -> watchdog hazard) makes this a known footgun.
  State: the learned map lives in RAM / `.storage` Store, never in entry options; only the operator override is an
  option.
- A recorder co-detection query at setup runs in the setup path and may precede the recorder; specify a deferred,
  executor-run, tracked job after `EVENT_HOMEASSISTANT_STARTED`, cancelled at unload.
- Fresh house / thin history: the plan says "no map -> G2 skipped". A PARTIAL learned map (a door with one spurious
  stage from a week of noise) makes G2 a hard fail for that door. Define a minimum (hops/day and sample count) for a
  door to have a map at all, below which the door is `skipped`.
- A weekly re-learn silently changes a trust gate feeding `camera_egress` -> HVAC. Record map version + diff in the
  diagnostic and freeze it between learns.

### M3. G3 data source is under-specified, and the default can fail real arrivals
- `person.<slug>` attributes carry `latitude`/`longitude`/`gps_accuracy` only when the active source tracker has them,
  and no fix timestamp. `person.last_updated` moves on any attribute or source change. "Last GPS fix younger than
  600 s" therefore needs the GPS `device_tracker` named in `person.<slug>.attributes.source` (or the person's
  `device_trackers` filtered to `source_type == gps`) and ITS `last_updated`. Say which.
- `CONF_SECURITY_LOCKOUT_DISTANCE_SENSORS` is a flat list (`security_lock_regime.py:351-356`), not keyed by person, and
  the unit varies (proximity sensors report in the HA unit system). Mapping a sensor to a slug by name is exactly the
  string-building §20 forbids. Specify the mapping (the proximity sensor's tracked entity via registry) and unit
  conversion, and the precedence when both sources exist.
- Default 600 s / 2 km: a resident driving home whose last fix was 8 min ago at 3 km fails G3 on a true arrival
  (sparse iOS fixes). D0-P7 must report G3 false-fail on true arrivals by age bucket; otherwise the default is a guess.

### M4. Kill-switch "byte-identical" is not, as written
INV-NOOP rev 8 says with the switch False the new keys "may still be written". Then: (a) `identity_role` with switch
False on exit + `home` is undefined (`attached` or `departure_candidate`?), and D1 source (c) reads `identity_role`
into the sighting payload, so sightings differ; (b) path scoring may still run and (per H2) needs new listeners;
(c) the bus dict is not byte-identical, so `test_switch_off_golden_replay` will be written to compare only
`person_id`/outcome, which is fine, but say so. Fix: with switch False, no exterior listener, no path computation,
`identity_role` absent (or always `attached`/legacy), outcome labels exactly today's; golden replay compares outcome
deque labels + DB row + bus `person_id`/`identity_confidence`, and the fixture MUST include an entry + `not_home`
case and an exit + `home` case (else M24 stays green).

### M5. Front-door fixture has cameras in two stages
Fixture: "Exterior, left approach: Front PTZ > Entry way" and "Egress: Entry way, Foyer" and "Interior: Foyer >
Family room". Entry way is exterior AND egress; Foyer is egress AND interior. Garage has a branch (DAG, not a list).
§2B.4 assumes disjoint ordered stages. A builder will either double-count (Entry way edge = exterior hop and egress)
or drop Foyer as interior. Fix: define the map as a DAG of camera nodes with typed edges; a camera that is the
crossing's own egress leg never scores; hops among egress cameras of the same door group never score. Add a front
door case to `test_path_score_entry_order`.

### M6. Notification follow-up mechanics are unspecified
`_arrival_departure_notify` (`transit_validator.py:2140`) is a synchronous fire-and-forget. The follow-up needs a
per-crossing waiter for 600 s. Unspecified: listener vs poll (perimeter polls every 5 s), task tracking and unload
cancel, supersession when the same person re-crosses, and what "edge lands" means: `nonface_arrival_source` checks
`abs(at_ts - ts) <= window_s` against a single `at_ts` (`arrival_edges.py:85-87`), so calling it with window 600
centred on the crossing also accepts a home edge up to 600 s BEFORE the crossing (that person was not a candidate).
Fix: specify "first live tracker/Bermuda edge with `ts > crossing_ts` and `<= crossing_ts + 600`", tracked unsub,
cancelled at teardown, one per (slug), plus a test for "edge before crossing does not trigger the follow-up".

## LOW

- **L1. Perimeter test can pass hollow.** D10.5 ignores egress identities below `floor = max(0.9, ...)`
  (`perimeter_alert.py:4995-4998`). A `test_perimeter_candidate_needs_nonface` built with a 0.75 candidate stays at
  severity with or without the change, so M22 stays GREEN. The test must use a 0.9 non-synthetic candidate.
  Also the role must reach `_recent_egress_identity` as a 5th tuple element read with `len(entry) > 4`.
- **L2. Missing drill for the G2 `skipped` branch.** Mutation "treat G2 skipped as pass" (candidate at 0.75 with no
  map) is caught only by `::test_g2_no_map_requires_0_9`; add it to the drill table (M21 covers only below-min).
- **L3. M23 tests the fail-closed default, not set membership.** By design both must be mutated together; record
  that the membership itself is not separately load-bearing so reviewer C does not report it as a GREEN row.
- **L4. Threading `identity_role` out of the resolver.** `_resolve_egress_face_identity` returns a 3-tuple used at
  `:2011`; the census skip at `:2091` needs the role. Specify the channel (extend the tuple, not another
  `self._last_*` stash like `_last_identity_synthetic_corroborated`), so the role cannot leak from a previous
  crossing if the resolver returns early.

## Cleared (holds because)

- Veto location and fail-open shape: `transit_validator.py:1841-1854` matches §2B.1.
- BLE branches never reach the veto: the face-only single-slug path is the only caller at :1838.
- Exit evict unchanged: `:2094-2095` evicts on any exit with `person_id`; a `departure_candidate` keeps the slug, so
  evict still fires.
- Access: lock regime literal `== "camera_face"` at `security_lock_regime.py:1017`, so the plan's M5 set-membership
  change is needed and correctly listed.
- 45 s timing claim in §2B.1 matches `ENTRY_WINDOW_SECONDS` scheduling at :1274.

## Must-fix before build dispatch
H1, H2, H3, M1, M4, M5 (plan text). M2, M3, M6 should be fixed in the same revision; L1-L4 are one-line additions.
