# Plan review, rev 10 Phase 1: completeness + build-prediction (Tier 3, adversarial)

Plan: `docs/planning/PLANNING_person_sighting_layer.md` rev 10 (branch `plan/face-arrival-rebuild`, e0db35fd), Phase 1
only (§0A: D0, D8a, D3, D1+D4, D2+D5+D6, D7). Reviewer read completely, before reviewing:
`IDENTITY_FUSION_CAMERAS_MANUAL.md`, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
`HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, and the rev-9 reviews (`..._rev9_buildprediction.md`, `..._rev9_completeness.md`).
No claim below re-asserts a presence §10 or HVAC §10 ledger entry. Read-only on code; every finding cites code read in
this worktree.

**Verdict: FIX-PLAN.** No HIGH. Seven MEDIUMs, all plan-text fixes (no design change); thirteen LOWs. The Phase 1 core
holds: nothing in Phase 1 can emit `camera_egress` or put a candidate name on any consumer, provided M3's stale text is
removed.

## MEDIUM

**M1. The access gates do not say what a MISSING `source` is.** §2 INV-ACCESS: "A source string that is in neither the
set nor the known non-camera set (`geofence`, `ble`) is treated as camera-derived (fail closed)." `None` is not a string.
`security_lock_regime.on_person_arriving` reads `payload.get("source")` (`:1006-1009`), so a payload without the key gives
`None`. Develop treats `None` as non-face. `test_lock_face_arrival_corroboration.py::test_non_face_sources_release_without_corroboration`
is parametrized over `["ble", "geofence", None]` and asserts a release, and about 20 other tests dispatch with no source
(`test_sc_garage_lockout.py:1503, :1622, :1627, :1845, :1978, :2065`; `test_cycle_f_signal_wiring.py:1046, :1133`;
`test_low_cleanup.py:629`; `test_sc_garage_lockout_review_c.py:49, :364`). Production always sends a source
(`presence.py:5297`, `person_coordinator.py:1132`), so this is not a live leak. A builder will still pick one reading:
fail-closed on `None` turns those tests red, while treating `None` as known makes "unknown fails closed" untrue for the
one unknown value that appears in tests. The presence doc §1 says "`ble` / `geofence` / missing source are unchanged".
Fix: state the rule for `None` in INV-ACCESS and D3. Either keep develop's behaviour (`None` counts as non-camera, the
doc line holds, tests unchanged) or fail it closed and list the tests and the doc line that change. Name the known
non-camera set as a const (L12).

**M2. The 4-tuple breaks 44 existing test call sites, and the plan does not mention them.** D8a changes
`_resolve_egress_face_identity` to return `(person_id, conf, agreement, resolution)`. Production has one call site
(`transit_validator.py:2011`), but tests unpack the 3-tuple 44 times across five files:
`test_egress_face_identity_d1.py` (7), `test_identity_fusion_d2_d3_d4.py` (10), `test_egress_identity_producer_d2b.py`
(22), `test_face_source_registry.py` (2), `test_frigate_face_name_bridge.py` (1). Each fails with "too many values to
unpack". These tests pin the existing resolver; edits to them are edits to the test authority of the code that INV-NOOP
claims is unchanged. Fix: choose and state one of these.
- (a) Keep the 3-tuple method and add `_resolve_egress_face_identity_ex` returning the 4-tuple. The old name becomes a
  thin wrapper, and `_resolve_direction` calls `_ex`. Existing tests stay unchanged.
- (b) Edit the 44 sites mechanically (`a, b, c = ...` becomes `a, b, c, _ = ...`) in a separate commit, with no
  assertion changes, verified by the validator's name-diff.

Make the pure tier helper module-level: `test_frigate_face_name_bridge.py:521-532` calls the unbound method with a
`SimpleNamespace` self that has no extra methods.

**M3. Rev-9 text still contradicts the Phase 1 scope in eight places. A builder reading top-down will build Phase 2
pieces.**
- D2 Phase 1 Verify, first bullet (`:1376-1378`): "Egress sightings dispatch `SIGNAL_PERSON_ARRIVING` only as
  `camera_egress` for an `arrival_confirmed` sighting with `FACE_ARRIVAL_EGRESS_ENABLED`". This bullet is Phase 2, and to
  satisfy it the builder has to write a `camera_egress` emitter in Phase 1. It is unreachable code, but it is exactly
  what the phase split forbids. Move it to D8b.
- §2B.5 HVAC row (`:707`) and §2B.6 (`:719`): "D8a adds `camera_egress` to `DEFAULT_PRE_ARRIVAL_SOURCES` ... migrates".
  §3.4 HVAC row (`:1029`): "(D8a migration)". D8a itself says this moved out. §2B's "§2B.7 wins" note does not cover
  §3.4.
- INV-ACCESS (`:749`) "from D8a on" and §6 (`:1148`) "from D8a": the set now ships in D3. Two stated homes for one const
  invite a second definition (Bug Class #53 shape).
- INV-NOOP rev-9 paragraph (`:789-798`): the HVAC option and `EGRESS_OUTCOMES_ATTACHED` are named as D8a
  switch-independent changes. Both are Phase 2.
- Live table: L10's "a real garage entry ... gets `path_score >= 2` on its bus event" cannot pass in Phase 1, because
  `path_score` on the bus is Phase 2 and D7 has no runtime reader. D7's Live line points only at L10. L11, L13, L15 and
  L16 are Phase 2.
Fix: mark every L row P1/P2, give D7 a Phase 1 live check (provenance attrs plus the diff report), and strike or re-label
the other lines above.

**M4. D5 deletes four functions but gives no disposition for the tests that call them.** Tests that reference
`_get_face_for_camera` / `_find_person_entity_from_face` / `_handle_face_arrival` /
`FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED`:
- `test_face_source_registry.py::test_presence_face_for_camera_reads_device_face`, `::test_presence_arrival_flag_default_off_keeps_legacy_skip`,
  `::test_presence_bare_camera_unchanged`, `::test_presence_alias_maps_face_to_person`;
- `test_identity_fusion_d2_d3_d4.py::test_fs4_presence_get_face_for_camera_gated_under_suppression` and
  `::test_fs_all_four_paths_suppressed_under_drill`;
- `test_face_resolver_migrate.py` (several);
- `test_d7_donor_hygiene.py` drills.

`test_fs_all_four_paths_suppressed_under_drill` is a cross-path invariant: every face-emission path honours
`_face_suppressed_now()` (`camera_census.py:4458`, "Every face-emission site MUST gate on this helper"). Deleting
path 4 without re-pointing the test at the new sighting producer silently drops the new producer from that invariant.
Fix: D5 lists each test as DELETE (dead function) or RE-POINT. The suppression-drill test is re-pointed so that path 4
becomes `person_sighting` emit. The alias test is re-pointed to the census mapper. Also do the supersession triage on
`camera_census.face_alias_person_slug`: after D5 its only reader is gone (KEEP+DOCUMENT or DELETE). Update manual §4.2
("used by `_find_person_entity_from_face`") in the D5 doc commit.

**M5. The shared loader helper's stated API cannot express D7's outcomes, and the seam behaviour it must keep is not
pinned.**
- D7 outcome (3) "invalid at setup -> validated const or none" and outcome (4) "invalid at reload -> keep previous" differ
  only by WHEN the load runs. The stated API `load_validated_json(hass, path, *, parse_validate, install, fallback)` plus
  `validate_fallback: bool` has no setup-vs-reload input. The seam caller gets "keep previous" at setup only because its
  constructor pre-installs the const (`exterior_track_linker.py:237`). State the mechanism: D7 pre-installs its validated
  fallback (or `none`) before the first load, and the helper always keeps previous on reject. Otherwise add `is_reload`.
- The sha semantics differ. The seam sets `seam_file_sha256` from the raw bytes BEFORE validation (`:509`), so a rejected
  file's sha is published, while D7 wants the sha of the installed source. The helper has to return the raw sha and the
  outcome, and each caller assigns its own attribute. `test_exterior_seam_loader.py` checks the sha only on a valid file
  (`:131`) and an absent one (`:142`), never on a rejected one. So "seam tests pass unchanged" does not detect a builder
  who "fixes" the seam to installed-source semantics. Add `test_seam_sha_on_rejected_file_unchanged` on develop BEFORE
  the extraction commit.
- "Resolver-ready point (after `EVENT_HOMEASSISTANT_STARTED` / the census's first resolver pass)": no such signal exists.
  `CameraIntegrationManager._get_resolver` (`camera_census.py:525`) builds lazily, and `grep RESOLVER_READY|resolver_ready`
  finds nothing. Name the hook: `EVENT_HOMEASSISTANT_STARTED`, or immediately when `hass.is_running` (a reload), then
  `census._get_resolver()`.
- Phase 1 has no re-validation trigger (§2B.7 L8 is Phase 2). With whole-file rejection, one camera that is not yet
  registered at that instant leaves `none` or the const until someone presses the button. Either bring the
  registry-update re-validation into Phase 1, or state it as a named residual with the button as the discharge.

**M6. P7's per-guard numbers need raw inputs that the recorder drops before the guards exist.** The weekly labeller
ships at step 2 (D8a), while the G2 scorer and a ratified map arrive at step 6 (D7, after D0-P4 plus operator
ratification). The recorder keeps 7 days (§7). P7 reports per-guard yields (G2 with the shared scorer, G3 from the
freshest GPS fix, G3 false-fails by fix-age bucket). Labelling weeks before D7 can compute none of these later unless the
weekly run stores the raw inputs. Fix: the labeller appends, per would-be candidate, the path-node person-edge
timestamps over the §2B.4 horizon and each GPS tracker's (lat, lon, acc, `last_updated`, `last_changed`) at resolution
to the labelled fixture, so G2 and G3 can be replayed after D7 and at day 28. Alternatively, ship the HA-free
`interior_paths.py` scorer with D8a. The go rules themselves (counts and the Wilson bound) do not need G2, so this is
MEDIUM, not HIGH.

**M7. A dead outcome logger would silently burn the 28-day clock. Use the trip-wire that already exists.** D8a is the
data source for the Phase 2 gate, and `log_memory_episode` never raises: it WARNs and returns None
(`database.py:10773-10775`). It also rejects an unregistered type with a WARNING only (`:10693-10699`). A logger that
writes nothing for weeks is noticed only at the day-28 judgement. The weekly memory-writer health trip-wire already
exists (`MEMORY_WRITER_BACKED_EPISODE_TYPES`, `const.py`, read at `database.py:11420-11445`). Fix: register
`egress_identity_outcome` there in the D8a commit (about 15 rows a day, so 0 in 7 days is a fault). State the
interaction with `EGRESS_OUTCOME_LOG_PERSIST = False`: an exemption or a conditional membership. Also give the weekly
labeller a forcing hook (a recurring board card swept at session start), because CLAUDE.md forbids calendar-only
processes. The operator travels (memory: NZ through 11-16), and a missed week is permanent loss of n.

## LOW

- **L1.** INV-LOG says "every return path". The `census is None` path (`transit_validator.py:1398-1399`) and the
  defensive `except` (`:1412-1413`) record no outcome label today. Give them one, for example `census_unavailable`, or
  exclude them by name.
- **L2.** `test_two_crossings_10s_apart_both_persist` (drill M30): two same-direction crossings on one door group 10 s
  apart are dropped by `DOOR_STEM_DEDUP_S = 30` (`const.py:3306`, `transit_validator.py:1980-1990`) BEFORE the resolver
  runs, so there is only one row. Specify different door groups or opposite directions.
- **L3.** Teardown race: a `_delayed_resolve` task (`:1266-1272`) that is already scheduled when `async_teardown` runs
  will create a logger task after the bounded gather. The DB closes at `__init__.py:5972`, after the tracker teardown at
  `:5920`. Add a `_torn_down` guard in the logger (precedent `_guest_stay_torn_down`).
- **L4.** D8a wire-in anchor: `test_every_resolution_persists_one_row_switch_off` must drive `_resolve_direction` (better,
  `_on_egress_state_change` with time advanced), not the resolver directly. Add drills: delete the logger call in
  `_resolve_direction`, and set `EGRESS_OUTCOME_LOG_PERSIST` ignored.
- **L5.** The D4 trip-wire denominator ignores `_face_suppressed_now()` (`camera_census.py:4458`: STRICT and a face
  drill, or the producer judged not live). During a face drill the bridge keeps latching while the producer correctly
  emits nothing, which sends a HIGH page. Exclude ring entries appended while suppressed, and add
  `test_suppressed_faces_silent`.
- **L6.** HVAC counter: `master_hallway` sits in two house zones that both map to HVAC zone_1 ("Entertainment + Master
  Suite", `hvac_zones.py:556`). Looping over `house_zones` adds 2. Count once per distinct HVAC zone and pin it in
  `test_hvac_counter_matches_compound_zone`.
- **L7.** `_last_face_time` must stay a `datetime`: `presence.py:1032` and `sensor.py:5988` call `.isoformat()`. If the
  sighting `ts` is an epoch float, convert it. `_last_face_recognized` changes from a face name to a slug (display).
  Declare that.
- **L8.** The HVAC cite has drifted: `_handle_person_arriving` is at `hvac.py:7222` (the plan says `:7212`). The
  subscription is at `:1510-1513`. The D5 HVAC-doc fix should re-grep at build.
- **L9.** The security gate uses `sighting.ts`. D3 ships at step 3, before any payload carries `sighting`, and
  `test_unknown_arrival_source_requires_corroboration` dispatches `camera_vision` with no sighting. Specify `at_ts` = now
  when the payload has no sighting. `_face_arrival_corroborated` already defaults to now (`security_lock_regime.py:1373`),
  and `_ts()` is epoch (`:416-417`), so the clocks agree.
- **L10.** Phase 2 gate realism: the Wilson rule needs n >= 10 operator-reviewed confirmations. At about 1 would-be
  candidate a week (P7's own floor) that is at least 10 weeks, not 28 days. Say so in §0A so the board does not expect a
  day-28 decision.
- **L11.** D2 rule 5's `_last_home_edge_ts` writer (in `_handle_geofence_change`) has no drill. Add "delete the write" ->
  `test_phone_already_home_skip`, driven through the real `person.*` listener.
- **L12.** Name the known non-camera set (`{"geofence", "ble"}`) as a rung-1 const next to
  `CAMERA_DERIVED_ARRIVAL_SOURCES`, and add it to the §6 table.
- **L13.** One channel: sighting source (c) still reads provenance from the `_egress_identity_last_attach` stash
  (`:2084-2088` pattern), while D8a introduces `EgressResolution` as the single return channel. Put `provenance` on
  `EgressResolution` and read it from there. This also removes the stale-stash risk that the `person_id is not None`
  gate guards today.

## Claims checked and holding (re-grepped)

| Claim | Evidence |
|---|---|
| Face-only veto only at `== "not_home"`, before the confidence block | `transit_validator.py:1840-1854`; block `:1856-1896` |
| Confidence-block side effects on a vetoed path would change outputs | stash `:1880`, boost ledger `:1888-1891`, bus reads stash `:2028-2030`, sensor 24 h boost count `sensor.py:3967-3975` |
| Face-only attach writes no `provenance` key; reader defaults to `face` | `:1908-1916`; `:2085-2088` |
| One production call site of the resolver; dedup returns before it | `:2011`; `:1980-1990` |
| Lock literal `source == "camera_face"`; security adds expected arrival with no face gate | `security_lock_regime.py:1017`; `security.py:2411-2421` |
| Lock regime always constructed (setup failure → None) | `security.py:710-728` |
| `_face_arrival_corroborated(person, at_ts)` exists; epoch clock | `security_lock_regime.py:1373-1408`, `:416-417` |
| Only three `SIGNAL_PERSON_ARRIVING` consumers; only two producers besides v3.19 | grep: `hvac.py:1511`, `security.py:817`, `music_following.py:281`; `presence.py:5297`, `person_coordinator.py:1132` |
| Other `add_expected_arrival` / `handle_disarm` callers are geofence, service, auto-follow | `security.py:2276, :2286, :2511, :1452`; `__init__.py:6595, :6621` |
| Tracker teardown precedes DB close | `__init__.py:5920` < `:5972` |
| memory_episodes has no prune (28-day log survives); readers are operator service + status counts only | no `DELETE FROM memory_episodes`; `__init__.py:6389, :6403`; `database.py:11126-11150` |
| Seam loader is linker methods; seam tests use a real file + fake executor (no reader monkeypatch) | `exterior_track_linker.py:433-552`; `test_exterior_seam_loader.py:79, :94-131` |
| Census bridge hook point exists after the sentinel drop | `camera_census.py:5521-5530` (sentinel), `:5584-5586` (latch loop) |
| Tracker face fields are display only | `presence.py:1031-1032`, `sensor.py:5986-5988` |
| HVAC accepts a missing source; filters by `pre_arrival_sources` | `hvac.py:7231-7235` |

## Invariant checklist (Phase 1)

| Invariant | Result | Note |
|---|---|---|
| INV-ACCESS | PASS by design; build ambiguity | M1 (missing source), L9 (`at_ts`); the set ships in D3 before any emitter (M3 text fix) |
| INV-PRODUCER | PASS | Filters are evidence-only; L5 is a trip-wire false page, not a producer filter |
| INV-PROVENANCE | PASS | `.get(..., FACE)` plus the explicit write; L13 for one channel |
| INV-NOOP (Phase 1) | PASS as written; LEAK risk in the build | M2 (test unpacks), pure helper per rev-9 M4 holds |
| INV-LOG | PASS with gaps | L1 (two unlabeled paths), L3 (post-teardown), M7 (silent dead logger) |
| No `camera_egress` / provisional name in Phase 1 | PASS once M3 is applied | D2 Verify bullet is the only path to an emitter; vetoed slug goes only to memory_episodes (operator query) |
| Dependencies ship before users | PASS except P7 data | M6 (labeller before scorer/map) |
| Extracted helper keeps seam behaviour | NOT PROVEN by the named test | M5 (sha on reject unpinned) |
| Wire-in test + red drill per deliverable | Mostly; gaps | L4 (D8a logger call), L11 (`_last_home_edge_ts`); D6 has no drill by nature |
| Acceptance criteria discriminate | Yes, except L10 live row | M3 |

## Must-fix before build dispatch
M1-M7 (plan text). LOWs are one-line edits; fix them in the same revision.
