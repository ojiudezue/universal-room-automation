# Plan review, rev 9: adversarial build-prediction

Plan: `docs/planning/PLANNING_person_sighting_layer.md` at b4ee0853 (branch `plan/face-arrival-rebuild`).
Scope: the rev-9 deltas (§2B.2-§2B.6, D7, D8a/D8b, drills M20-M34, L10-L16, build order).
Framing: what the builder will get wrong reading this text. Read first: `IDENTITY_FUSION_CAMERAS_MANUAL.md`.
Code read on the plan branch, plus the exterior seam loader on develop (110cb2da, not yet an ancestor of b4ee0853).

**Verdict: FIX-PLAN.** Three HIGH, six MEDIUM, four LOW. Every one is a text fix. None changes the design.

## HIGH

**H1. Confirmation cannot find its row: the DB timestamp is the INSERT time, not the crossing time.**
`log_entry_exit_event` stamps `datetime.utcnow()` when it writes (`database.py:4618-4646`). The INSERT runs at the
end of `_resolve_direction` (`transit_validator.py:2126`), so it lands at t_E + 45 s plus write-queue lag. §2B.3a
step 1 says "`lo`/`hi` bracketing the crossing's own timestamp". A builder who reads `crossing_ts` as t_E (the
waiter's own anchor for "strictly after" and the 600 s expiry) brackets t_E and finds nothing. The backfill is
"best-effort and logged", so every confirmation would leave the row NULL while the signal and "That was X" still go
out. The DB and the notification would disagree, and a test that seeds the row with a hand-picked timestamp passes
anyway.
Fix: either `log_entry_exit_event` returns `lastrowid` and the waiter stores the row id (no search, so no bracket
and no wrong-row risk), or state the bracket as `[T − 5 s, T + EGRESS_ARRIVAL_ROW_SLACK_S]` in naive UTC with a
named knob. The row-id route is simpler and drops the camera-match question in M3. Add a test that drives the real
`_resolve_direction` INSERT and then confirms.

**H2. Ordering: the waiter can confirm before the INSERT commits.**
Order today: bus fire (`:2016`), notify (`:2047`, detached task), census (`:2075`), DB INSERT awaited through the
write queue (`:2126`). The natural place for the builder to open the waiter is next to the role result (`:2011`) or
the bus fire. With a Bermuda read already in a room, the first 5 s poll confirms, and if the write queue is backed up
(the queue is saturated at boot and during vacuum, `database.py:367`), the SELECT runs before the row exists. The
plan never orders the waiter against the INSERT.
Fix: say "the waiter is created after `log_entry_exit_event` returns, with the row id from H1". If the row is
missing at confirmation, retry the find once per poll until expiry instead of firing the signal. Test: a slow write
queue (the INSERT deferred) plus an immediate BLE confirmation must still name the row and must send "That was X"
only after the row is named.

**H3. Drill M27 and its verify line cannot go red through the real path for source (a).**
"A home edge 20 s BEFORE the crossing confirms nothing": with the tracker at `home` from t_E − 20, `S == home` at
resolution, so the crossing is `attached` and no waiter exists (§2B.2 row 1). The test passes because there is no
candidate, not because the strict-after rule held, and M27 (abs window) stays GREEN. The same is true for any
tracker edge in (t_E, T). Only (b) and (c) can carry a pre-crossing timestamp into a live waiter: a Bermuda room read,
or a GPS fix, from before t_E while the tracker still reads `not_home`.
Fix: rewrite `test_home_edge_before_crossing_does_not_confirm` as two tests: a Bermuda `last_changed` = t_E − 20 and
a GPS fix at t_E − 20 within 0.5 km, each with the tracker `not_home`, each asserting the candidate stays open. Point
M27 at them. Rewrite the verify bullet the same way, because as written it does not discriminate.

## MEDIUM

**M1. Build order puts D7 before the helper it needs, and D8b before the site it edits.**
D7 resolves nodes with `canonical_camera_key` (§2B.4, D7 storage). That helper does not exist (grep
`camera_resolver.py`: 0 hits). D1 creates it (M17, `test_canonical_camera_key_same_for_all_legs`). The order is
D8a -> D7 -> D1 -> D8b -> D2-D6. The D7 builder will either write the helper (then D1 finds it and its tests change
owner) or key nodes by entity id, so Frigate and Protect legs become two nodes and `test_frigate_and_protect_legs_one_node`
gets written against a stopgap. D8b also lists "the D2 egress branch behind `FACE_ARRIVAL_EGRESS_ENABLED`" and four
`test_face_arrival_rule.py` tests, but D2 ships after D8b, so that branch has no site to land in. And D8a ships
`test_face_access_invariant.py::test_camera_egress_requires_corroboration` before D3 builds the gates the test exercises.
Fix: move `canonical_camera_key` into D7 (or D7 after D1). Move the D2 egress branch and its four tests into D2.
Move the access test into D3, and in D8a test only the set's contents.

**M2. "On the exterior seam loader" names a method, not a loader.**
`async_load_seam_file` is a method of `ExteriorTrackLinker` (`exterior_track_linker.py:479`) hard-wired to
`validate_seam_spec`, `graph_from_spec`, `set_adjacency` and the linker's attributes. There is no reusable loader. The
builder will copy it into `EgressDirectionTracker`, which is a second hand-rolled path, or bolt the interior map onto
the linker, which is the wrong owner because `transit_validator` scores the path. Its semantics also differ from D7's
text in three ways:
- the const fallback is never validated (`_install_const_seams`, `:433`), while D7 needs the const validated so that
  another install gets `none`;
- a missing file installs the const, and a rejected file keeps the previous map;
- the sha is set on the rejected file (`:509`), so `seam_file_sha256` names a file that is not installed.
Fix: name the shape. Either extract a small generic `load_validated_json(path, validate, install, fallback)` helper
in this cycle and have both callers use it (REUSE row), or say "copy the contract, owned by `EgressDirectionTracker`".
Then state the four outcomes for the interior map: file valid, file absent -> validated const or `none`, file invalid
at setup -> validated const or `none`, file invalid at reload -> previous map. State that `path_map_sha256` is the
sha of the INSTALLED source.

**M3. The DAO cannot match `egress_camera`; LIMIT 2 drops rows.**
`find_unnamed_exit_crossings` returns the nearest 2 NULL rows with no camera filter (`database.py:4685-4718`). The plan
says "the row's `egress_camera` matched" and adds only a `direction` parameter. Two NULL entries at different doors
inside the bracket (garage and front, both families coming home) put the wrong row in `rows[0..1]`, and a post-filter
in Python misses the right one. H1's row-id route removes this. Otherwise add `egress_camera` to the DAO WHERE clause.

**M4. The outcome log's site, task and count disagree with L14.**
D8a: "at each outcome site ... (where the slug is known, vetoed included)". L14: rows = "resolved crossings since
restart (one each)". The resolver has early returns with no slug (no legs, abstain, disagree, ambiguous at `:1430`).
Logging only where a slug is known breaks L14, and P7's denominator becomes "crossings with a slug". Also,
`_resolve_egress_face_identity` is synchronous (called without await at `:2011`), so the DB write has to be a task.
The plan says nothing about tracking that task. The linker's `_episode_tasks` set plus a bounded teardown gather
(`exterior_track_linker.py:250, :361-379`) is the precedent.
Fix: one record per call to `_resolve_egress_face_identity`, every return path, with slug null when there is none.
Emit it from `_resolve_direction` after the call returns (async context, one site, the 4-tuple already in hand). Name
the tracked-task set and the teardown wait. Test: `test_every_resolution_persists_one_row_switch_off` must include a
no-legs crossing and an ambiguous one.

**M5. Waiter lifecycle has holes the tests will not catch.**
- Restart or unload drops waiters with no outcome row, so P7 sees candidates with neither `arrival_confirmed` nor
  `arrival_unconfirmed`. Fix: teardown writes `arrival_dropped_teardown` for each pending waiter (best-effort,
  bounded), or P7 states that candidates with no terminal outcome are excluded.
- "One tracked task" on confirmation is not tied to teardown. The existing `async_teardown` (`transit_validator.py:2276`)
  only calls unsubs. A confirmation task in flight at unload awaits the DB write after `stop_write_worker` and buffers
  silently (`database.py:367`). Fix: put the task in a set, cancel or gather it in teardown, and test unload during a
  confirmation.
- The poll unsub: if the builder appends it to `self._unsub` (the tracker's habit), confirmation and expiry must
  remove it (the self-removing idiom at `:1264-1277`), or the list grows. Say "held only in the waiter, never in
  `self._unsub`".
- Supersession cancels the older waiter. Say that its row stays NULL and log it with the slug and both crossing ts.
- `stale_source_arrival` needs `stale_s` (`arrival_edges.py:48-53`). The plan names no knob. Name the existing const
  that the lock regime passes, and reuse it.

**M6. Drill M28 "skip the migration" goes red only if a test drives setup.**
`test_migration_appends_camera_egress_once` will call the migration function directly, as the dwell-migration tests
do, so deleting the call in `__init__.py` leaves it GREEN. Also, HVAC reads `{**ce.data, **ce.options}`
(`hvac.py:1434-1438`), but the dwell precedent reads `options` only (`__init__.py:771-776`). If `pre_arrival_sources`
sits in `data` (set at initial config), an options-only migration sees nothing and appends nothing.
Fix: the migration reads the merged view and writes `options`. Add `test_setup_runs_camera_egress_migration` (wiring
anchor) and point M28's second half at it. A test with the key only in `data` is needed too. Already true, no change:
the options flow merges onto the existing options (`config_flow.py:7847, :8428`), so the sentinel survives a save.

## LOW

**L1.** G3 uses the tracker's `last_updated`. A companion-app attribute refresh (battery level) moves it without a new
fix, so the fix looks younger than it is and the implied speed comes out too high. That fails closed (no name), the
safe side, but P7's false-fail-by-age bucket will be skewed. Prefer the tracker's `last_changed`, or say P7 reports
both.
**L2.** D7 validator rule 3 needs `CameraResolver` populated and rule 2 needs the live door groups when
`EgressDirectionTracker` sets up (`__init__.py:3471`). State the ordering, or make the first load wait for the
resolver-ready point. Otherwise a cold boot rejects a valid file, falls back to the const, and the provenance shows the
const until someone presses reload.
**L3.** `test_g2_no_map_requires_0_9` with M21b: the G1 0.9 tier is only reachable non-synthetically with two
recognizers. Say that the test fixture uses two live legs, or the test is not constructible.
**L4.** "Exit + home -> `departure_candidate`, evict, counted attached": the evict path reads `person_id`, which is
the slug here. Say so on the bus-key table, because the "candidates only" wording for `candidate_person_id` will make
the builder null `person_id` for both kinds of candidate.

## Claims checked and holding

- Loader on develop: `async_load_seam_file`, `button.ura_reload_exterior_seams`, `seam_status` provenance. Exists as
  cited, but it is not reusable as written (M2).
- `log_memory_episode` goes through `_db()` (write queue), registry gate on `MEMORY_EPISODE_TYPES`, and the 60 s
  in-memory `(node_id, type)` dedup (`database.py:10690-10716`). So M30 with a constant `node_id` does go red on two
  crossings 10 s apart.
- `backfill_entry_exit_person_id` writes `person_id` only, with an `IS NULL` guard (`database.py:4723-4760`).
- `_migrate_hvac_zone_entry_dwell_to_zero` at `__init__.py:749`, called before `cm_config` is built (`:3696`).
- The options flow preserves unknown keys on save.
- PersonCoordinator Bermuda data carries `method == "bermuda"` and `last_changed` (`person_coordinator.py:1085-1089`).
- The census register sits behind `if person_id` (`transit_validator.py:2075`), so a candidate with `person_id` None
  is skipped. The `_last_attach` read is inside that gate.

## Summary

| Sev | Count | Classes |
|---|---|---|
| HIGH | 3 | #53 computed-not-consumed (H1/H2 backfill no-op), #62 hollow anchor (H3) |
| MEDIUM | 6 | build-order dependency, second hand-rolled path, untracked background tasks (M4/M5), hollow wiring anchor (M6) |
| LOW | 4 | stale data source #7 (L1), boot ordering (L2), fixture constructibility (L3/L4) |
