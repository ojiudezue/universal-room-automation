# Review D (adversarial completeness, diff-blind): person sightings Phase 1

Branch `feature/person-sightings-p1`, base `3348d379`, head `f4455a9d` (three-dot diff). Plan
`docs/planning/PLANNING_person_sighting_layer.md` rev 11. Tier 3, framing D.

Read in full before review: `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`,
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`.
No claim in the presence §10 ledger is re-asserted here.

## Invariants (falsifiable form)

**INV-ACCESS.** For any `SIGNAL_PERSON_ARRIVING` whose `source` is camera-derived (in
`CAMERA_DERIVED_ARRIVAL_SOURCES`) or unknown, in any reachable config, neither (a) a lock
`unlock` through the SC lock regime (garage lockout release or away-lock release), nor (b) an
`add_expected_arrival` from the Security Coordinator happens unless
`arrival_edges.nonface_arrival_source(slug, ...)` returns non-None for the SAME person
(a live `person.*` not_home -> home edge or a Bermuda move into an entry area, within
`PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S`, outside the boot exclusion). Falsified by any path
from a face / camera sighting to `lock.unlock` or `add_expected_arrival` that skips that test.

**INV-NOOP.** With `FACE_ARRIVAL_INTERIOR_ENABLED = False` (shipped value, `const.py:3375`),
no code path dispatches `SIGNAL_PERSON_ARRIVING` with a camera-derived source, and no producer
of `source = "camera_egress"` exists. Falsified by any dispatch of a camera-derived arrival, or
any other actuation change, reachable with the flag False.

## Surface re-enumerated (whole repo, not only the diff)

Producers of `SIGNAL_PERSON_ARRIVING` (grep of `SIGNAL_PERSON_ARRIVING` and the literal
`ura_person_arriving`): exactly three.
| Site | Source | Notes |
|---|---|---|
| `person_coordinator.py:1130` | `ble` | pre-existing, observation-gated |
| `presence.py:5317` | `geofence` | pre-existing; now also stamps `_last_home_edge_ts` (`:5297`), no dispatch change |
| `presence.py:5576` `_derive_face_arrival` | `camera_face` | the only camera-derived producer; flag test at `:5537` precedes the dispatch; egress sightings return at `:5534` (`not_arrival_role`) |

The v3.19 producer (`_handle_face_arrival`, `_get_face_for_camera`) is deleted (D5); the
camera-change handler now only schedules inference. `camera_egress`: no producer anywhere
(only `const.py:3460` and docs). No other module dispatches the literal.

Consumers of `SIGNAL_PERSON_ARRIVING`: four.
| Consumer | Class | Gate |
|---|---|---|
| `security.py:2392` -> `security_lock_regime.on_person_arriving` (`:997`) | access (unlock) | `arrival_source_needs_corroboration` + `_face_arrival_corroborated` (`:1022-1034`); held faces re-checked once in `_on_pc_update` (`:1474`) with the same predicate at the face's own time |
| `security.py:2429-2446` expected-arrival add | access (alarm suppression) | same classifier + `face_input_corroborated` (`:1382`); no regime or torn-down regime = reject |
| `hvac.py:1511` pre-arrival | comfort | `_pre_arrival_sources` (`hvac.py:881`, default includes `camera_face`) |
| `music_following.py:281` | comfort | none |

`_apply_arrival` (`security_lock_regime.py:1036`) has two callers (`:1034`, `:1481`), both behind
the corroboration test. Every other `_release` / `_away_release` caller (`:810` house state,
`:1071`/`:1074` hazard, `:1088`/`:1098` kill switch, `:1221`/`:1224` person/approach edges,
`:1348`/`:1566` proximity, `:2039` backstop, `:2133`/`:2169` away person edges) reads no
sighting and no face. Other unlock sites: `security.py:2336` (hazard egress), the lock
regime's teardown/disable loops. Other `add_expected_arrival` sites: `security.py:2277/2287`
(raw `person.*` geofence edges) and the manual service. None is camera-derived.

`SIGNAL_PERSON_SIGHTING` has no dispatcher subscriber in the repo; the sighting reaches
decisions only through the injected `arrival_rule`. `get_last_person_sighting(s)`,
`_last_face_recognized` / `_last_face_time`, `camera_face_arrivals_today` are display only
(`sensor.py:6014`, `presence.py:1032`, `hvac_zones.py:1278`).

Census inputs: the diff to `camera_census.py` adds a ring (only while `FACE_SIGHTING_ENABLED`)
and a callback hook after the latch loop (exceptions caught, `:5632-5645`), and extracts
`_face_latch_veto_source` from `_get_face_recognized_person_names`. Old vs new decision
compared line by line: raw `not_home` -> `"raw"`; else trust reader `not_home` ->
`"ble_overrule"` with the counter bumped only on that branch. Byte-identical. Sightings write
nothing into the census.

Transit validator: `egress_identity_tier` (`transit_validator.py:113`) reproduces the old
HIGH / BOOST / MEDIUM and synthetic arithmetic exactly; the veto path still sets no stash and
appends no BOOST ledger entry; the bus event gains only the additive `identity_provenance`;
the outcome log is write-only. Direction, census union register/evict and the
`_arrival_departure_notify` call are unchanged.

Interior path map: `self.path_map` is written (`transit_validator.py:2460`, `:2490`) and read only
for status (`:2499`, sensor provenance). No decision reader. `door_interior_neighbours` and
`_entry_areas` are untouched.

## Config extremes and repros tried

| Case | Result |
|---|---|
| `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S = 0` | `nonface_arrival_source` returns None (`arrival_edges.py:209`): a face never unlocks and never adds an expected arrival. Holds. |
| No lock regime on SC (`_lock_regime is None`) with `security_on_arrival_add_expected` on | expected-arrival rejected (`security.py:2437`). Holds. |
| Garage lockout switch off / away lock list empty | the gate still runs; `_apply_arrival` effects are no-ops. No new path. Holds. |
| Payload `source` missing (None) | treated as non-camera (develop behaviour, `arrival_edges.py:46`). No production producer of a camera arrival omits `source` (only `_derive_face_arrival`, which sets it). Holds. |
| Unknown source string | fails closed (held / rejected). Holds. |
| Security in observation mode | lock regime still fed above the return (pre-existing, `security.py:2389`), still gated. Holds. |
| Face of person A while A is away, B present (mislabel) | needs A's own edge; B's edges are keyed by B's slug. Holds. |
| Garage B (detached, `INTERIOR_PATH_DETACHED_DOORS`) / an unmapped door group | entry areas are the union of egress camera areas + configured neighbours (`security_lock_regime.py:1371`, egress_tracker object). Garage B's camera area is an entry area, as before this branch; a Bermuda move there is a real non-face edge for the same person. Path map has no reader, so Garage B rule 10 changes nothing at runtime. No leak. |
| Unresolved pick (Garage A `room_cameras_empty`) | no sighting from that pick; no access effect. |
| Flag flipped to True (Phase 2 preview) | access consumers still need the edge; HVAC pre-arrival and music following would act on a face alone (comfort class, `raw` not_home / named zone required). See L-2. |

## Findings

No CRITICAL / HIGH / MEDIUM.

- **LOW L-1 (pre-existing, not in the diff; class: invariant scope).** The garage lockout also
  releases on the house-state edge to `arriving` (`security_lock_regime.py:865-866`, called from
  `:810`). `infer()` returns ARRIVING from AWAY whenever `census_count > 0`
  (`presence.py:1349-1370`), and `census_count` includes camera body counts and census face ids.
  Repro: lockout engaged for SLEEP, house goes SLEEP -> AWAY (`house_state.py` allows it), then
  any interior camera person detection lifts `census_count` to 1 -> ARRIVING -> release. This
  is camera-derived and person-agnostic, but it is body evidence through the house state machine,
  not a face or sighting, and this branch does not touch it (sightings feed no census or
  inference). Out of INV-ACCESS as stated in the plan; recorded so nobody reads INV-ACCESS as
  "no camera input can ever release a lockout". Suggest the operator decide whether a card is
  wanted.
- **LOW L-2 (Phase 2 note; class: policy lives in the consumer).** HVAC pre-arrival
  (`hvac.py:7231`, default `DEFAULT_PRE_ARRIVAL_SOURCES` includes `camera_face`) and music
  following accept `camera_face` with no corroboration. Inert while the flag is False. Before
  enabling interior arrivals, decide whether comfort consumers accept a face alone (the D2 rule
  already requires raw `not_home` / named zone, which is exactly the mislabel case of 10-24).
- **LOW L-3 (display; class: concept change).** `_last_face_recognized` on the zone tracker now
  holds the URA slug, not the raw face name (`person_sighting.py:646`). Display attribute only;
  no URA reader. Dashboards that matched on the raw name would see a different string.

## Invariant checklist

| Invariant | Verdict | Evidence |
|---|---|---|
| INV-ACCESS (a) lock unlock | PASS | both `_apply_arrival` callers gated; no other release reads a face or sighting |
| INV-ACCESS (b) expected arrival | PASS | single camera-derived add site gated, fail closed with no regime |
| INV-NOOP no `camera_egress` emitter | PASS | grep: no producer |
| INV-NOOP flag False = no camera arrival | PASS | single dispatch site behind the flag; egress short-circuits earlier |
| INV-NOOP census / egress decisions unchanged | PASS | refactors compared line by line, byte-identical |

## Verdict

**SHIP.** No must-fix items. L-1 is pre-existing and outside this cycle's invariant; L-2 is a
gate for Phase 2; L-3 is display.
