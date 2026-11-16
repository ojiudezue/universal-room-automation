# Interior vision ship 2 - Review C (test authority by real per-site source mutation)

Branch `feature/interior-vision-ship2`, commit `0bc751d8`, diff base `develop...HEAD -- custom_components`.
Method: one production-source edit per drill, `__pycache__` purged, `python -B` with `PYTHONDONTWRITEBYTECODE=1`,
target set `-x` (first RED wins; GREEN re-run on the wider set for cv/nm/const groups), restore in `finally`,
`git status` clean at the end of every batch. Helpers: `.claude/tmp/ivrc_drive.py`, `ivrc_muts_{a,b,c}.py`
(+ `.out` result files). Sites enumerated from the diff, not from the builder's `ivship2_drills.py`.

Baseline: 716 passed (target set), 886 with the wider test set. No production defect found; every finding is a test gap.

## Counts

| Batch | Mutations | RED | GREEN | Invalid |
|---|---|---|---|---|
| A: interior_vision.py (pure helpers, budget, sampler, staging, trip-wires) + interior_dewarp.py | 233 | 123 | 110 | 0 (1 identity mutant `iv_stage_executor` counted GREEN, discard) |
| B: person_sighting, presence delegate, NM, select, number, const, __init__, crossing_vision, perimeter | 252 | 151 | 93 | 8 (6 anchor misses, 1 syntax, 2 identity mutants `ps_get_desc_none`, `nm_init_last`) |
| C: B re-runs with fixed anchors | 8 | 4 | 2 | 2 anchor misses (`pe_img_provider_*`, covered by `pe_img_provider_set`) |

Executed valid: about 480. RED 278. GREEN about 204: 26 equivalent mutants, about 178 gaps (most LOW).
Restored and clean: `git status --short` empty after every batch.

## Verdict: FIX-REQUIRED (tests only)

The suite proves the headline flows (wire-in, access gate, budget refusal, scrub of explicit names, end to end
call). It does not pin the pure helpers, the producer-to-sampler plumbing, or the day/cost accounting.

## HIGH gaps (test needed, mutation that stays GREEN)

| # | Site (mutation) | Why it matters | Test needed |
|---|---|---|---|
| H1 | `response_payload` structured_response branch (`iv_payload_structured_first`, `iv_payload_mapping`, `iv_payload_service_response`) | grep: zero tests use `structured_response`, the llmvision field for `response_format: json`. Whole real-world parse path unpinned (#62). | result with only `structured_response` dict / JSON string / `service_response` envelope parses. |
| H2 | day roll (`iv_rollday_reset_calls`, `_cost`, `iv_budget_method_roll`) | Cap never resets: describe dies for good after day one (INV-IV-OFF). | advance `now_fn` across local midnight, assert counters reset and a call is allowed. |
| H3 | cost accounting (`iv_desc_reserve_cost`, `iv_budget_method_estcost`) | `cost_today` never accrues, so the cost cap is inert. | N calls at est cost reach `cost_cap_reached` before the call cap. |
| H4 | person target resolution (`ps_tgt_ble_slug`, `ps_tgt_face_slug`, `ps_tgt_face_source`, `ps_tgt_face_newest`, `ps_tgt_slug_match`, `ps_tgt_first_unique`) | Single-person fixtures (#63 coincidental equality): "describe X" can describe Y's room, or an ambiguous first name picks one person. Privacy-relevant. | two tracked persons, distinct rooms; ambiguous first name refuses; display-name and space forms match; newest sighting wins; door-camera sighting ignored. |
| H5 | `_describe_scrub_names` composition (`ps_scrub_first`, `ps_scrub_disp`, `ps_scrub_slug`) and `iv_scrub_variants`, `iv_scrub_boundary_*`, `iv_parse_scrub_energy` | INV-IV-NO-NAME: tests hand `scrub_names` explicit names; nothing checks the producer builds first-name/slug/display words, nor the `_`/space variants, word boundary, or affect energy scrub. | producer-level test: model text carrying only the first name is scrubbed; "Anna" inside "Hannah" untouched; energy field scrubbed. |
| H6 | dewarp geometry on non-square stills (`dw_in_wh`, `dw_grid_fov`, `dw_visible_r`) | Fixture is square, so swapped width/height and a wrong vertical FOV are invisible (#63). Camera stills are not square. | ffmpeg-fixture comparison on a non-square fisheye through `dewarp_jpeg`, with `out_fov` args. |
| H7 | trip-wire and clock wire-in (`ps_sampler_fire`, `ps_sampler_now`) | Producer passes `fire=` and `now_fn=` to the sampler; no test drives it through the producer. Trip-wires could be no-ops. | producer-built sampler: force zero-calls condition, assert NM `fire` receives it; clock follows producer `now_fn`. |
| H8 | provider plumbing (`ps_provider`, `ps_sampler_provider`, `iv_run_provider`, `pe_img_provider_set`) | llmvision provider id never asserted to reach the service call (cost/privacy route). | assert `provider` key in `image_analyzer` data from `vision_provider_id`. |
| H9 | lens sensor registry match (`ps_lens_device`, `ps_lens_disabled`, `ps_lens_tk`, `ps_lens_uid_suffix`, `ps_lens_domain`) | Lens sensor of another camera or a disabled entity can drive dewarp of the wrong still. | registry fixture with a lens sensor on a different device, a disabled one, and a translation-key-less uid. |
| H10 | lifecycle (`ps_setup_torn_reset`, `iv_desc_torn_down`, `iv_teardown_flag`, `ps_setup_sweep_track`, `iv_desc_task_discard`) | After teardown a describe still starts; after re-setup the sampler can stay dead; sweep task untracked; task set leaks. | teardown then describe returns "" with no call and no task; setup after teardown works; sweep task is in the tracked set and cancelled. |

## MEDIUM gaps (grouped)

- Sampler pass-through args and constants never asserted: `iv_run_timeout`, `iv_call_still_timeout`, `iv_stage_timeout`, `iv_stage_infov`, `iv_stage_outfov`, `iv_stage_quality`, `iv_stage_stamp`, `iv_run_fields_ts` (record `ts=0.0` would make `max_age_s` useless), `c_dewarp_infov/outfov/quality/views_values`, `c_call_timeout`, `c_still_timeout`, `ps_dw_per_device`, `pe_img_format` (json to text), `pe_img_empty`, `pe_img_kill`.
- `get_room_description` / presence delegate `max_age_s` (`ps_get_desc_age`, `_cmp`, `pr_get_age`).
- NM: `nm_wire_return` (fall-through, possible double reply), `nm_unresolved` (denial text sent to an unresolved sender), `nm_cooldown_peruser` (one requester's cooldown blocks another), `nm_presence_none` (None dereference on a missing presence coordinator), `nm_log_inbound_gate`, `nm_channels` (extra channels admitted), `nm_prefix`.
- Staging discharge: `iv_write_prefix` (sweep deletes only `iv_*`; a prefix drift orphans stills, INV-IV-NO-STORE), `iv_write_cleanup`, `iv_remove_oserror`, `iv_remove_notfound`, `iv_unstage_exc_left`, `iv_sweep_left_counter`, `iv_frames_left_enabled`, `iv_frames_left_latch`.
- Trip-wire guards: `iv_tw_window_prune`, `iv_tw_zero_switch`, `iv_tw_zero_caps`, `iv_tw_zero_min`, `iv_tw_zero_threshold`, `iv_tw_zero_unlatch`, `iv_tw_err_minmin`, `iv_tw_err_off`, `iv_tw_err_rate`, `iv_tw_err_unlatch` (false positives when switch off, never-pruned window).
- Producer: `ps_live_discounted`, `ps_live_discount_read` (stuck sensor treated as live), `ps_log_torn_down`, `ps_log_dedup` (window dedup could drop a description row), `ps_log_ref`, `ps_log_attr_*`, `ps_log_task_track`, `iv_unparsed` (`iv_parse_unusable_none`, `iv_run_unparsed`, `iv_run_result_none`).
- Number/select: `num_calls_unique`, `num_device`, `num_clamp_int`, `num_clamp_min`, `num_calls_int`; `iv_sw_options_default`, `iv_sw_entry_type` (switch default before the switch loads), `iv_cap_bad_fallback`, `iv_cost_bad_fallback`.

## LOW gaps (counters, labels, diagnostics, dead seam)

Counters and diag keys (`iv_desc_counter`, `iv_desc_skip_count`, `iv_run_*counter`, `ps_req_*counter`, `ps_diag_*`, `iv_diag_*`, `nm_*counter`), reply text details (`iv_reply_*`), schema/prompt text (`iv_schema_affect_required`, `iv_schema_conf_bounds`, `iv_prompt_affect_empty`), parse clamps (`iv_parse_people_clamp/bool`, `iv_parse_conf_clamp`, `iv_parse_skip_blank_what`), the `clip` frame-source branch (`iv_call_clip_branch`, `iv_call_clip_expose`: no ship-2 producer builds a clip source, still an untested seam), `iv_desc_bg_task_name`, `iv_desc_task_fail_*`, dewarp `dw_round`, `dw_rgb`, `dw_quality`, `c_err_min_calls`, `cv_lookup_exc`, `cv_cfg_exc`, `pr_req_exc`, `pr_get_exc`.

## Equivalent mutants (GREEN, no test possible or needed)

| Mutant | Reason |
|---|---|
| `iv_access_operator_modes` | `operator_affect` falls to the `else` arm which is also `requester in ops`. |
| `iv_access_affect_allowed`, `iv_access_affect_ops` | `mode == operator_affect` already implies allowed iff requester in ops (redundant conjunct). |
| `iv_budget_cap_zero` | `cap <= 0` implies `calls_today >= cap` since `calls_today >= 0`. |
| `iv_budget_cost_zero` | with `INTERIOR_VISION_EST_COST_PER_CALL > 0`, `cost_cap <= 0` already trips `cost_today + est > cap`. |
| `iv_budget_reserve_zero`, `iv_budget_method_reserved`, `c_reserved` | with `reserved == 0` the sampling-only branch adds no refusal; ship 2 has only the describe purpose. |
| `iv_cap_nonneg`, `iv_cost_nonneg` | a negative cap refuses exactly as 0 does. |
| `iv_run_dewarp_fail_files` | `files` is only assigned on success. |
| `iv_run_cancel_reraise` | `CancelledError` is a `BaseException` and `except Exception` does not catch it (defensive duplicate). |
| `iv_sweep_notdir` | `os.listdir` error is caught by `async_sweep_stage`'s `except Exception`. |
| `dw_tx`, `dw_ty` | `out_hfov == out_vfov` always (single `out_fov_deg`). |
| `dw_normalize` | `x/h`, `y/h` and `arctan2(h, z)` are scale invariant. |
| `dw_lh_zero` | an even `out_px` grid never hits `h == 0`. |
| `dw_visible_uf` | `r <= 1` implies `abs(uf) <= 0.5`. |
| `ps_req_reply_affect_gate`, `nm_access_affect_knob` | affect is empty when the knob is off, so the reply carries none. |
| `ps_live_nostill` | `states.get(None)` is None, returns False anyway. |
| `ps_log_db_none` | the `AttributeError` is caught by the surrounding `except Exception`. |
| `cv_empty` | empty id gives `async_get_entry` None, same return. |
| `nm_cooldown_zero` | cooldown 0 never satisfies `elapsed < 0`. |
| `num_publish_int`, `c_access_hass_key` | `int()` cast on read, and the key const is imported on both sides. |

## RED rows (specific named tests; sample)

Each of the 278 RED rows names the first failing test in `ivrc_muts_{a,b,c}.py.out`. Representative: `iv_schema_required_conf` and `iv_prompt_views_text` -> `test_describe_schema_no_names_prompt`; `iv_scrub_ignorecase`, `iv_parse_scrub_where/context` -> `test_describe_scrubs_resident_names`; `ps_live_view` -> `test_describe_non_live_still_source_no_call`; `ps_lens_platform` -> `test_lens_by_registry_not_name[esphome-lens_type]`; `nm_presence_lookup` -> `test_describe_access_default_operator_only`; `sel_current` -> `test_describe_access_select_publishes_and_persists`; dewarp rotation/bilinear mutants -> `test_interior_dewarp.py` ffmpeg-fixture tests.

## Builder drill list comparison

`.claude/tmp/ivship2_drills.py` has 46 drills (NM wire-in, access, cooldown, presence delegate, producer-to-sampler call, still-live gate, budget switch/kill/caps/reserve, dewarp wire-in, lens 360/registry, scrub, reply affect, memory row, zero-calls and error trip-wires, frames-left page, teardown, sweep wire-in, BLE bar, face freshness, select/number publish, guard pins). All of those sit on the RED side here. Sites it missed, with GREEN consequences: `response_payload` branches, day roll and cost accrual, person-target slug filtering and sighting selection, `_describe_scrub_names` composition, dewarp geometry beyond the square fixture, producer-to-sampler `fire`/`now_fn`/`provider` plumbing, lens-entity device/disabled/translation-key filters, staging prefix and discharge, trip-wire guards, task tracking, `__init__` key sets (all six RED), constants, `analyze_crossing_images` flags (privacy flags `store_in_timeline`, `use_memory`, `expose_images` and entity/file/structure keys are RED; `response_format`, kill, empty-input and provider are GREEN), and `vision_provider_id` (rung order and domain check RED).

## Recommendations

1. Fix H1-H10 with tests (each mutation above is the RED proof the new test must satisfy).
2. Add a QUALITY_CONTEXT note: single-instance fixtures (one person, one camera, square image) mask whole-site filters (#63).
3. Cap the new tests' mutation anchors with `@pytest.mark.source_mutation` only where a subprocess drill is used.
