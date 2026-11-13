# Plan review, rev 9: completeness of the rev-9 deltas

Plan: `docs/planning/PLANNING_person_sighting_layer.md` rev 9 (branch `plan/face-arrival-rebuild`, b4ee0853; changelog §22).
Framing: COMPLETENESS (Tier 3 plan re-review). Scope: §2B (provisional candidates, waiter, G3 speed rule), D7
`interior_paths.json`, D8a / D8b, the HVAC `camera_egress` source and migration, §7 P7, the kill-switch byte-identical
definition. Read completely first: `IDENTITY_FUSION_CAMERAS_MANUAL.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`,
`SENSOR_FLEET_CLASSES.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, both rev-8 reviews. Code read-only (plan worktree,
plus `develop` 397edc55 for the seam loader).

**Verdict: FIX-PLAN.** 2 HIGH, 6 MEDIUM, 11 LOW. Most rev-8 findings are resolved. Two new problems sit in the parts
rev 9 added. The confirmation legs can attach a wrong name, and the DB backfill brackets the wrong timestamp.

## Rev-8 findings: resolution check

| Rev-8 finding | Status | Residual |
|---|---|---|
| C-H1 / B-H1 HVAC drops `camera_egress` | Resolved (default, selector, migration) | Third default site at `hvac.py:881` (L1); HVAC doc update placed in D8b although D8a ships the HVAC change (L2); BLE-leg value is about 0 (M5) |
| C-H2 / B-H3 D7 widens `door_interior_neighbours` | Resolved: separate file, M31, `test_entry_areas_near_areas_direction_identical_with_map` | Loader premise stale (L4) |
| C-H3 guards miss the 10-24 case | Partly resolved. Provisional naming fixes "named at the crossing" | Confirmation legs (a)/(c) can confirm the wrong name (H1) |
| C-M1 named zones | Resolved | Union effect of "exit + zone, no evict" is bounded but undeclared (L11) |
| C-M2 attach rate / last_attach / role | Partly resolved | The candidate branch's position relative to the `last_attach` write is unspecified (M3) |
| C-M3 / B-M1 rule 1 | Resolved (split by branch) | none |
| C-M4 / B-H2 path_score time and sources | Resolved | Exit horizon is asymmetric (L7) |
| C-M5 / B-M5 fixture vs live config, DAG | Resolved (DAG, questions §13.4) | Map is never re-validated when the config changes (L8) |
| C-M6 stale sections | Resolved | none found |
| C-M7 P7 data thin | Partly resolved (log persisted, Wilson bound) | Labels and review need data the system keeps only 7 days (M6). Vetoed rows need confidence that the veto path never computes (M4) |
| B-M4 kill switch byte identity | Resolved as written | Same reorder trap (M4); one-time CM options write (L3) |
| B-M6 waiter mechanics | Resolved | Name kill switch not honoured (M2); DB bracket (H2) |
| C-L1..L5, B-L1..L4 | Resolved | L9 (PATH_MIN 0 semantics) |

## Re-enumeration (greps, not the plan's list)

| Surface | Sites found | In plan? |
|---|---|---|
| `ura_person_egress_event` listeners | `sensor.py:4753, :4884, :4994, :5044`; `perimeter_alert.py:1006` | yes |
| `person_entry_exit_events` readers / writers | INSERT `database.py:4623/:4637` (ts = `utcnow()` at write); `get_entry_exit_events_since` `:4654`; `find_unnamed_exit_crossings` `:4685` (LIMIT 2, no camera filter); `backfill_entry_exit_person_id` `:4723`; exit backfill `camera_census.py:4930, :4988` | yes, but the INSERT timestamp is misdescribed (H2) |
| `_egress_identity_last_attach` | writers `transit_validator.py:1657, :1705, :1769, :1908`; readers `:2086`, `sensor.py:3978-3980` (display attr) | write-order gap (M3) |
| `SIGNAL_PERSON_ARRIVING` producers | `presence.py:5297` geofence, `:5634` camera_face, `person_coordinator.py:1132` ble | yes; leg (b) and ble fire on the same Bermuda tick (M5) |
| `SIGNAL_PERSON_ARRIVING` consumers | `hvac.py:1511` (filter `:7231`), `security.py:817` (lock `:996`, literal `:1017`; expected arrival `:2412-2419`, no source test), `music_following.py:281` | ordering gap (M1) |
| Pre-arrival source defaults | `hvac_const.py:350`, `hvac.py:881` (ctor literal), `config_flow.py:7683`, `:8192-8201`; text `strings.json:1425`, `translations/en.json:1425` | `:881` and the help text missing (L1) |
| CM options migration precedents | `_migrate_hvac_zone_entry_dwell_to_zero` `__init__.py:749` (no snapshot reseed); `_bootstrap_pin_ec_defaults_once` `:3641` ("reload-safe, listener snapshot reseeded"); `OPTIONS_RELOAD_SUPPRESS_KEYS` `:7526` lacks `pre_arrival_sources` | L3 |
| memory_episodes | `log_memory_episode` `database.py:10664`; index only `(node_id, episode_type, started_at)` `:2014`; `dedup_source_ref` runs an unindexed `source_ref` SELECT `:10735`; no prune found | L6 |
| Seam loader (prereq of D7) | shipped v5.108.15 on develop (a7059b50) as linker methods `async_load_seam_file`, `_read_seam_file`, `_seam_file_path` | plan text says "in build" (L4) |

## Findings (ranked)

### H1. Confirmation legs (a) and (c) can confirm the wrong name (the 10-24 case comes back for a resident near home)
§2B.3 says "a real arrival brings that person's phone; a misnamed person does not". That holds only when the named
person is far away. Leg (c) confirms on ANY fix within `EGRESS_ARRIVAL_CONFIRM_GPS_KM` (0.5 km) after the crossing. Leg (a)
confirms on the named person's own home edge up to 600 s later, even if that person came in through another door.

Repro (legal config, defaults; live `zone.home` radius 53 m, presence doc §3):
- Oji is walking the dog 300 m away, so `person.oji_udezue` is `not_home`. His phone reports GPS while he moves.
- Jaya enters through garage_a. Frigate names her "Oji" on garage_a and family_room. This is the consistent-mislabel
  0.9 shape (`transit_validator.py:1858-1883`).
- G1 passes and G2 passes (path 3).
- G3: fix 300 m, 2 min old, d = 0.3 - 0.02 - 0.053 = 0.227 km, about 7 km/h. Pass.
- Candidate opens.
- At +90 s Oji's next fix reads d = 0.2 km, which is at most 0.5. The candidate is CONFIRMED. Results:
  - DB `person_id` = oji_udezue;
  - "That was Oji Udezue";
  - an `egress_entry` sighting `arrival_confirmed`;
  - with `FACE_ARRIVAL_EGRESS_ENABLED`, `SIGNAL_PERSON_ARRIVING(camera_egress)` for Oji. Rule 5 passes because Oji is
    raw `not_home`. HVAC then pre-conditions his zones.
- Access still holds: the lock regime has no edge, so it holds the arrival and then drops it.

Variant for leg (a): Oji comes home 4 min later through the front door with no face match. His tracker home edge confirms
Jaya's garage crossing as Oji.

INV-PROVISIONAL holds formally, because a confirming edge exists. The protection claim does not. Leg (c) is also the only
leg that can lead HVAC (M5), so the feature's value and this risk sit on the same leg.

Fix in plan:
- Leg (c): require d = 0 (inside the home zone plus accuracy) AND a shown approach. The G3 fix, or the last fix before the
  crossing, must be farther than `EGRESS_ARRIVAL_CONFIRM_GPS_KM`.
- Legs (a) to (c): abstain (`arrival_confirm_ambiguous`) when another crossing at any door lands between `crossing_ts` and
  the confirming edge, or when the named person has a later candidate.
- P7 reports wrong confirmations per leg.
- Tests: `test_gps_near_without_approach_does_not_confirm`, `test_intervening_crossing_abstains`.

### H2. The DB backfill brackets the wrong timestamp
§2B.3a step 1 says to bracket "the crossing's own timestamp (naive UTC, the INSERT format)". The INSERT writes
`datetime.utcnow()` at write time (`database.py:4628`, `:4645`). That write runs at the END of `_resolve_direction`, after
the bus fire, the notify and the census feed (`transit_validator.py:2116-2124`). That is `t_E + 45 s` plus processing,
not `t_E`. The bus `timestamp` is `t_E` (`:2019`).

A bracket around `t_E` finds no row. The step is best-effort, so the failure is silent: no row is named, Entered Today
shows nothing, and L11 fails live.

The plan's test `test_confirmation_backfills_that_entry_row_only` will pass hollow if it calls `_resolve_direction` with
`egress_timestamp = now`, because then the INSERT time and the crossing time coincide.

Also:
- `find_unnamed_exit_crossings` has `LIMIT 2` and no camera filter (`:4704-4710`). A Python-side camera match can lose the
  target row when two NULL entries from other cameras sit nearer in the bracket.
- On contention the exit backfill re-selects in a claim loop (`camera_census.py:4928-5035`). The waiter has no such loop.

Fix in plan:
- Bracket the resolution instant: `[T - a, T + b]` with named constants, or record the INSERT time.
- Push the camera filter into the extended DAO (`egress_camera = ?`).
- Abstain when more than one NULL candidate row matches.
- The test must drive the 45 s scheduled path (`_on_egress_state_change` -> `async_call_later`) with time advanced.

### M1. Build order lets a `camera_egress` dispatch ship before the access gates that recognise it
The lock regime gates only `source == "camera_face"` (`security_lock_regime.py:1017`). Any other source goes straight to
`_apply_arrival`, and the really-away release fires for an away resident. The security expected-arrival path tests no
source at all (`security.py:2412-2419`).

The membership edits are in D3 (§3.4). The build order is D8a -> D7 -> D1 -> **D8b** -> D2..D6. D8b carries "the D2 egress
branch" and sighting (c'). D2 is built after D8b, which is an ordering contradiction of its own. Between D8b/D2 and D3, a
`camera_egress` arrival would unlock on a face alone. Only the default-False const prevents it.

Tier 3 asks INV-ACCESS to hold at every ship. Fix in plan: move the two membership edits (lock `:1017`, security gate)
into D8a next to the set they read, or make D3 a hard prerequisite of D8b. Also fix the D8b/D2 order text.

### M2. The waiter ignores `switch.ura_name_people_at_doors` except for the notify
Only step 3 fresh-reads the switch. The exit-backfill precedent (manual §4.3a R1) re-reads it before the UPDATE
(`camera_census.py:4984`), and OFF means no write.

Repro: a candidate at 10:00; the operator turns naming off at 10:01; the tracker edge lands at 10:03. The DB row is
named, Entered Today shows the name, and a sighting is emitted, all with naming off.

Fix in plan: fresh-read the switch before the DB write, the signal and the sighting (count
`arrival_confirm_disabled_skip`). Add a test.

### M3. INV-PROVISIONAL misses the `egress_identity_last_attach` display, and the write order is unspecified
G1 needs `identity_confidence`, which is computed AFTER today's veto position (`:1875-1896`). The `last_attach` write
follows immediately (`:1908-1916`). A builder who moves the direction-aware decision below the confidence block, but
after `:1908`, publishes the candidate slug through `sensor.py:3978-3980` (`egress_identity_last_attach`, a display
attribute). That breaks INV-PROVISIONAL: a name is shown before confirmation.

§2B.5 only asserts "a candidate makes no attach". The test pins only the stale READ.

Fix in plan:
- State that the candidate and `vetoed_arrival_unverified` branches return before any `last_attach` write.
- Add `egress_identity_last_attach` to INV-PROVISIONAL's consumer list.
- Add `test_candidate_does_not_write_last_attach` and a mutation drill for it.

### M4. D8a's vetoed outcome rows need confidence and synthetic flags the veto path never computes, and a naive reorder breaks INV-NOOP
D8a logs `identity_confidence` and `synthetic` for vetoed rows, and P7 splits by tier and synthetic. With the switch False
the veto returns at `:1845-1854`, before confidence is computed. Running the confidence block on the veto path has side
effects:
- it appends to `census._egress_identity_boost_events` (`:1888-1891`), so `egress_identity_correlated_boost_count_24h`
  rises;
- it sets `_last_identity_synthetic_corroborated` (`:1880`), so the bus `identity_synthetic_corroborated` reads True on a
  vetoed crossing.

Both change outputs with the switch off.

Fix in plan:
- A pure helper computes tier and synthetic from `in_window` with no stash and no ledger append.
- The veto-path record uses that helper.
- `test_switch_off_golden_replay` includes a vetoed 0.75 crossing and a vetoed synthetic 0.9 crossing.

### M5. BLE confirmation (leg b) cannot come before the `ble` arrival, so the stated HVAC value is about 0 on that leg
Leg (b) reads PersonCoordinator `method == "bermuda"` with `last_changed = area_state.last_changed`
(`person_coordinator.py:1083-1089`). On that same tick, PersonCoordinator dispatches `SIGNAL_PERSON_ARRIVING(source="ble")`
after an absence of at least `min_away` (`:1127-1134`). The waiter polls after that.

So the case "BLE-confirmed before geofence/ble" can essentially never happen:
- §0, §2B.6 and the P7 go rule ("BLE- or GPS-confirmed ... precedes the first geofence/ble arrival") count on it;
- the D8 Verify "Bermuda in-house read at +40 s ... reaches HVAC" will only show a duplicate.

Rule 5 does not catch the duplicate (raw `person.*` can still read `not_home`). HVAC absorbs it through `pre_arrival_spent`
and the debounce.

Fix in plan:
- The P7 go rule counts GPS-confirmed leads only.
- Rule 5 also skips (`arrival_already_dispatched`) when presence saw any geofence/ble `SIGNAL_PERSON_ARRIVING` for the
  person since `crossing_ts`.
- Restate §0's value line to match.

### M6. P7's labels and review need data that is gone before the 28-day gate is judged
- Auto-labels use tracker, Bermuda and GPS edges from the recorder, which keeps 7 days.
- Operator review needs crossing media. Perimeter snapshots keep 168 h (`PERIMETER_SNAPSHOT_RETENTION_AGE_H`).
- The gate is judged over at least 28 days of log.
- The auto-label "a non-face edge follows within 10 min" IS the confirmation rule, so it cannot measure that rule's
  precision. Only the operator's review can.

Fix in plan:
- Run the labeller weekly, appending labels to the committed fixture, with operator review inside the retention window.
- Or name URA-DB sources that live longer: `person_presence_snapshots`, and the activity-log `pre_arrival` rows for
  geofence/ble. GPS fixes have no URA-DB source.
- State that the Wilson n counts reviewed confirmations only.

## LOW
- **L1.** `hvac.py:881` keeps a third copy of the default (`["geofence","ble","camera_face"]`). It is inert, but it is the
  one-missed-site shape (Bug Class #53). Use the const. The help text (`strings.json:1425`, `en.json:1425`) also needs the
  new source.
- **L2.** D8a ships the HVAC source change, yet §11 and the D8b docs put the HVAC_STATE_OF_PLAY edit in D8b. The HVAC
  doc rule is "every HVAC ship updates it in the same commit", so move the edit to D8a (with the §2 `:4186`/`:1196` →
  `:7212`/`:1511` cite fix, which code confirms).
- **L3.** The migration copies the dwell precedent, which does not reseed the CM listener snapshot, and
  `pre_arrival_sources` is not in `OPTIONS_RELOAD_SUPPRESS_KEYS`. Either use the EC-pin pattern ("reload-safe, listener
  snapshot reseeded", `__init__.py:3635-3641`) or state why the CM listener is not armed at that point. INV-NOOP should
  name the one-time options write.
- **L4.** EXTERIOR-SEAM-FILE-LOADER-1 shipped (develop a7059b50, v5.108.15) as seam-specific linker methods. D7's "extract
  the shared helper" is therefore mandatory. Require the existing seam tests to pass unchanged after extraction, and merge
  develop into the plan branch (develop is not an ancestor of b4ee0853).
- **L5.** For a tracker-confirmed candidate, rule 5's first clause (raw state now `home`) gives skip reason `home`. §2B.6,
  the D8 Verify and `test_tracker_confirmed_skips_phone_already_home` say `phone_already_home`. Pick one.
- **L6.** The outcome-log scope contradicts itself. D8a says "where the slug is known". L14 and
  `test_every_resolution_persists_one_row_switch_off` say one row per resolved crossing. Also:
  - `dedup_source_ref=True` adds an unindexed `source_ref` SELECT inside the single writer, and the per-crossing `node_id`
    already makes it unnecessary;
  - the resolver is sync, so name the tracked task set the logger task goes into and its teardown cancel.
- **L7.** Exit scoring: nodes in `_interior_entities` prune at 75 s, while `_path_events` keeps 180 s. Reversed deep hops
  more than 30 s before `t_E` are invisible on interior-list nodes and visible on others. That biases the
  EGRESS-PATH-OVERRIDES-DIRECTION-1 evidence. P7 must replay the same per-list horizons.
- **L8.** The path map has no re-validation trigger on door-group or egress-camera option changes, or on registry updates.
  Picks have four triggers (§3.2). A stale door key keeps scoring the old door.
- **L9.** `EGRESS_ARRIVAL_PATH_MIN = 0` means "G2 not evaluated", yet with G2 `skipped` a candidate needs 0.9. Setting
  0 to relax G2 therefore tightens G1. Say this on the knob.
- **L10.** Leg (b) needs slug -> PersonCoordinator key. Data is keyed by tracked person name (`person_coordinator.py:970`).
  The existing `_find_person_entity` (`:1722`) string-builds `person.<name>`. Specify a registry or tracked-person mapping.
- **L11.** "exit + zone -> vetoed, no evict" leaves an entry-registered slug in the union for up to
  `EGRESS_FACE_UNION_TTL_S` (300 s). That is bounded and the same as `not_home` today. Declare it next to the other
  switch-on deltas.
- Adjacent (pre-existing, card): `LastPersonEntrySensor` discards its `async_listen` unsub (`sensor.py:4994`) and has no
  DB read path. "Re-read like the exit readers" is undefined for it. Specify "take the name only when its last entry is
  the confirmed crossing".

## Doc vs code contradictions found
- HVAC_STATE_OF_PLAY §2 pre-arrival row cites `hvac.py:4186` / `:1196`. Code: `_handle_person_arriving` `:7212`, subscribed
  `:1511` (the plan already notes this; the fix belongs in L2's commit).
- The plan's §1.2b and D7 say the seam loader is "in build". It is shipped (L4).

## Invariant checklist

| Invariant | Result | Evidence |
|---|---|---|
| INV-PROVISIONAL | LEAK risk + claim weakness | M3 (`last_attach` display); H1 (wrong-name confirmation is formally allowed) |
| INV-CENSUS-HOME | PASS | Register only behind `if person_id` (`transit_validator.py:2086`); a candidate's `person_id` is None; confirmation never registers |
| INV-ACCESS | PASS by design; LEAK risk by build order | M1 (`security_lock_regime.py:1017` literal until D3) |
| INV-CANDIDATE | PASS | G1/G2/G3 as specified; L9 semantics |
| INV-NOOP | PASS as written; LEAK risk in the build | M4 (confidence side effects), L3 (one-time CM write) |
| D7 does not widen `door_entry_areas` | PASS | own file; M31 + test |

## Must-fix before build dispatch
H1, H2, M1, M2, M3, M4, M5, M6. The LOWs are one-line plan edits; fix them in the same revision.
