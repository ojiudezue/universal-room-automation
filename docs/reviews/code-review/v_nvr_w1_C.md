# NVR witness W1 -- Review C (test authority via per-site source mutation)

Branch feature/nvr-witness-w1-pairing, HEAD d450c382, base 4b825c50 (merge-base with develop, verified; diff is 7 files, one production file: camera_resolver.py).
Method: one site mutated at a time in production source (or the test loader), pycache purged, `test_nvr_witness_w1_resolver.py` run; any mutant that left it green was re-run against 6 sibling files (test_camera_resolver, test_camera_census, test_census_suffix_disambiguation, test_transit_protect_sourced, test_person_sighting, test_census_fusion_policy: 172 tests). Tree restored and `git status` clean after every mutant.
Independent check: the golden `nvr_w1_resolver_golden_develop.json` was regenerated with develop's resolver (`git show 4b825c50:camera_resolver.py`) over the fixture registry: identical, 105 cameras.

## Per-site table (RED = a named test failed)

| Site | Mutation | Result | First named test that went RED |
|---|---|---|---|
| knob default | `= True` -> `False` | RED | test_resolver_knob_shipped_default_true (+7 more) |
| knob gate (on path) | `if KNOB:` -> `if True:` | RED | test_resolver_knob_off_byte_identical_all_callers |
| knob gate (off path) | `if KNOB:` -> `if False:` | RED | test_resolver_object_name_collapses_unique_protect_sibling |
| source tag at site | `BASIS_FRIGATE_OBJECT_NAME` -> `BASIS_NAME_STEM` | RED | test_resolver_object_name_collapses_unique_protect_sibling |
| source tag constant value | value -> "name_stem" | RED | same |
| `sibling_did not in expanded` | dropped | RED | test_fusion_callers_golden_except_garage_shape |
| slugify | `slugify(name)` -> `name.lower()` | RED | test_resolver_slugify_matches_ha_device_name_punctuation |
| name_by_user precedence | swapped / ignored | RED | test_resolver_pairs_on_device_registry_name_not_entity_id |
| camera-device gate (index from all devices) | add non-camera devices | RED | test_resolver_object_name_ignores_device_with_only_disabled_camera |
| index build skipped | removed | RED | 8 tests |
| disabled-entity filter (resolver build) | removed | RED | test_resolver_object_name_ignores_device_with_only_disabled_camera |
| input must be Frigate | gate removed | RED | test_resolver_object_name_refuses_non_frigate_input |
| cond (3) no other Frigate device with the object name | removed | RED | test_resolver_object_name_refuses_two_frigate_devices |
| cond (1) obj == candidate slug | lookup widened to all slugs | RED | test_resolver_object_name_requires_equal_registry_name |
| cond (2) exactly one candidate | `!= 1` -> `== 0` and `< 1` | RED | test_resolver_object_name_refuses_two_candidates |
| candidate must be non-Frigate | filter removed | RED | test_resolver_other_frigate_device_with_same_name_not_a_candidate |
| cond (4) candidate has no Frigate identifier | removed | RED | test_resolver_object_name_refuses_candidate_with_frigate_identifier |
| loader: name_by_user / name / identifiers / connections / disabled_by dropped | each | RED | golden + census + sighting tests (see transcript logic: all five RED) |
| loader snapshot: decl / pick / legs dropped; camera list includes disabled | each | RED | knob_off_byte_identical + golden test |

## GREEN rows (all analysed)

| Mutation | Verdict |
|---|---|
| `if sibling_did and sibling_did not in expanded` -> `if sibling_did is not None and ...` | equivalent mutant (id is never an empty string) |
| `slugify(name) or None` -> `slugify(name)` | equivalent: the only consumer is `if _slug:` in the index build |
| blank-name check `not name.strip()` dropped | equivalent: `slugify("  ")` is "" and is filtered by the same `if _slug:` |
| `if dev is None: return None` dropped | equivalent: `getattr(None, ...)` yields None, falls to the str check |
| `if not obj: return None` dropped | equivalent: an empty or None key matches no slug bucket (an empty slug is never indexed) |
| `c != input_did` self-exclusion dropped | redundant: the input is Frigate and is already excluded by the non-Frigate filter |
| slugify ImportError branch fail-open (`name.lower()` instead of None) | LOW: no test forces the import to fail. Unreachable inside HA; comment promises fail-closed, untested |

No sibling file (172 tests) went red on any green mutant, as expected for equivalents.

## Findings

- LOW (C-1) camera_resolver.py `_device_name_slug` except-branch: fail-closed on HA import failure has no test. Optional: monkeypatch `homeassistant.util` import to raise and assert no pairing. Not blocking; the branch is unreachable in a running HA.
- No MEDIUM/HIGH. Every non-equivalent site, including all four uniqueness conditions, the camera-device gate, disabled filter, slugify, name precedence, knob gate/default, source tag and the fixture loader fields, is anchored by a specific RED test. Test count is small (19) but each test varies one registry variable.
- Observation (not a finding): `test_person_sighting_bind_and_egress_key` and the census test both go RED on knob/slug mutants, so the caller-layer wiring is exercised against the real modules, not only the resolver.

## Verdict: SHIP (Review C). Tree clean; helper scripts deleted.
