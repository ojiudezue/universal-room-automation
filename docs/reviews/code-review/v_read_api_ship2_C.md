# Review C (test authority, real per-site source mutation): person-awareness read API ship 2

Branch `feature/person-awareness-read-api-ship2`, impl HEAD 1d49aef9, base `release/batch-1` ca133c9d (merge-base verified).
Read the PRESENCE state-of-play doc and SENSOR_FLEET_CLASSES completely before starting.
Method: one production site mutated at a time (line- or string-anchored, restored in a finally, SHA verified, `git status` clean),
`__pycache__` purged before every run, `PYTHONDONTWRITEBYTECODE=1`, one pytest process at a time. Test set per drill: the cycle's
files (ship2, ship1 read-api, the 11 test files the diff touches) plus the sibling files of the mutated module (HVAC/aggregation
trust tests, security/lock-regime tests, music-following tests, person-sighting tests). No full suite.

## Result: 154 drills (64 RA6 + 90 other, incl. 3 re-runs with wider sets), 148 RED on a named test, 6 GREEN

| Area | Drills | RED | GREEN |
|---|---|---|---|
| RA6 delegate / writer / reader bodies in `camera_census.py` | 20 | 20 | 0 |
| RA6 call sites: `transit_validator` (29) | 29 | 29 | 0 |
| RA6 call sites: perimeter (4 + 3 RA9) / sighting (4) / `__init__` (3) / sensor RA9 | 17 | 15 | 2 (sighting L717, L710: see below, RED once sibling files included) |
| RA7 `census_view` fields + 3 readers + restored dead hook | 33 | 32 | 1 (seed branch) |
| RA8 helpers + six zone sites + `get_residents_home(zone_persons)` | 16 | 16 | 0 |
| RA9 ids / person_coordinator / arrival_edges / uid builders | 21 | 19 | 2 |
| RA10 `from_signal` + 3 consumers | 10 | 10 | 0 |
| AST guard (leak method / getattr / counter write / `self._census` hasattr / duplicate allowlisted read / stale allowlist) | 7 | 6 | 1 (alias receiver, stated limit) |

Representative named REDs (full runs showed 1-8 failures each): every `RA6-delegate-*` -> `test_public_census_method_delegates_to_private[<name>]`
or `test_public_census_note_outcome_and_counters`; `transit_validator` sites -> `test_identity_fusion_d2_d3_d4.py`,
`test_egress_identity_producer_d2b.py`, `test_transit_validator_provenance.py` (each abstain / consume / boost / last-attach
occurrence went RED individually); RA7 fields -> the `*_golden` tests in ship2 and `test_person_awareness_read_api.py`;
RA8 -> `test_persons_home_for_trust_*`, `test_zone_has_home_person`, `test_get_residents_home_zone_persons_form_has_no_plb_cut`,
and the HVAC/aggregation sibling suites for the six call sites; RA10 -> `test_lock_regime_reads_the_normalised_payload`,
`test_security_arrival_handler_*`, `test_music_arrival_handler_*`, `test_person_arriving_payload_from_signal_dict_and_object`;
guard -> `test_no_private_census_reads_outside_module` (all six leak shapes, plus the exact-count and stale-allowlist branches).

## Findings (GREEN rows)

| # | SEV | Site | Mutation | Why GREEN | Class |
|---|---|---|---|---|---|
| C1 | MEDIUM | `person_coordinator.py:1019` `_async_update_data` `person_entity_id = tracked_person_entity_id(person_name)` | revert to `f"person.{name.lower().replace(' ', '_')}"` | 171 passed (ship2, gps-assistive, fleet-fraction, setup-wirein). The two other RA9 person-coordinator copies (`:847`, `:1769`) are pinned by `test_effective_person_state_overrule_*` / `test_find_person_entity_*`; the main update loop, the site the Review A `person.person.*` fix was mainly about, has no `person.*`-entry test. Under the live config (display names) both forms are identical, so only a `person.*` entry exposes it. | #62 untested site |
| C2 | LOW | `person_ids.slug_of` `s = str(entity_or_name).strip()` | drop `.strip()` | `slug_of` has no direct test: the blank / whitespace-only and surrounding-space rows of its docstring ("blank -> ''", "whitespace ignored") are unpinned (`'  '` would become `'__'`). Only `live_arrival_slug`, `_person_key`, `display_of` reach it with clean input. | #62 |
| C3 | LOW | `presence.py` seed block (RA7 deleted `camera_integration_manager` branch) | re-add the branch | 441 passed. Deleting a no-writer dead branch has no pin; re-adding it is inert unless something writes the key. Harmless, noted for completeness. | dead-code deletion unpinned |
| C4 | LOW (process) | person_sighting L717 `_denominator` tracked read and L710 ring read | `[]` / wrong name | GREEN on the cycle's own file set, RED (5 failed: `test_a1_denominator_boundary_literal`, `test_bm1_*`, `test_face_sighting_tripwire.py::test_zero_with_faces_pages`, `::test_rearm_after_recovery`) once the sighting sibling files run. Covered, but the README's targeted file list should include `test_person_sighting*.py` and `test_face_sighting_tripwire.py` so the validator name-diff runs them. | coverage lives in sibling files |
| C5 | LOW (stated limit) | AST guard receiver match `(^|[._])cens` | `_cc = self.hass.data['x']; _cc._get_tracked_person_slugs()` | Guard passes: a census held under a name without `cens` is invisible. The guard's own docstring states this limit; the six realistic shapes (`census`, `census_ref`, `self._census`, `_cens`, `hass.data[...]["census"]` inline, getattr/hasattr with a constant) all go RED. No action required unless the operator wants the alias hole closed (e.g. also flag attribute reads on any name assigned from `hass.data[DOMAIN]["census"]`). | guard limit |

Equivalent mutants skipped (cannot be RED by construction): `census_view` `if last is None / house is None: return None` (the
AttributeError lands in the same `except` and returns None).

## Anti-hollow note
No test in the cycle set is a source grep; the guard test parses production source by AST but is itself drilled (6/6 leak shapes RED,
plus anti-vacuous `len(private) > 100`). `test_private_census_detector_controls` pins the detector on good and bad shapes.

## Verdict: SHIP (no must-fix)

148 of 154 drills RED on a specific named test; every RA6 call site, every RA7 reader, every RA8 zone site, every RA9 unique-id
builder and all RA10 consumers are individually pinned. Recommended before merge (cheap, not blocking): C1 add one test driving
`PersonTrackingCoordinator._async_update_data`'s entity lookup with a `person.oji_udezue` tracked entry; C2 add a direct `slug_of`
table (`None`, `''`, `'  '`, `' Oji '`, `'person.Oji'`). Tree left clean (`git status` empty after every drill; helper files removed).
