# HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1 — build notes

Plan: `docs/planning/PLANNING_hvac_s10_stale_range.md` Rev 3.
Branch: `feature/hvac-s10-settle` (from `develop @ 663fda018`).

## Files changed

- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  — new `S10_POST_PRESET_CHANGE_SETTLE_S = 600`,
  `S10_SETTLE_HELD_WARN_S = 14_400` (both rung 1).
- `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py`
  — four new `ZoneState` fields (`prev_preset_mode`, `prev_hold_activity`,
  `last_observed_preset_change`, `settle_episode_started_at`); observer wire-in
  inside `update_zone_climate_state` after the existing `preset_mode` read
  (seed-on-first-readable, sentinel skip on `""`/`"unknown"`, stamp when the
  readable (preset, hold) pair changes; episode-start tracked for the R4
  trip-wire).
- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
  — new skip-step `post_preset_change_settle` (step 0.6) inserted after
  `climate_unreadable` and strictly ahead of `s1_same_tick` (T19); failure
  reset on CONFIRMED success in `_s10_success` (D2 / R2); new
  `_s10_check_settle_held()` R4 trip-wire + `_s10_settle_held_fired_on` latch
  dict; call-site in `_async_apply_preset_overrides`; new
  `s10_settle_held_s` field in `get_s10_diagnostics()`; two §9.7 → §9.9
  comment corrections (lines ~3938, ~5593).
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — §4.2 S10 row:
  residual replaced with shipped behaviour; new skip-matrix step; D2 reset
  rule; §10 ledger entry C38.
- `quality/tests/test_s10_post_preset_change_settle.py` — T1-T19 (T12 dropped
  per Rev 3 R6).

## Tests

`PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/test_s10_post_preset_change_settle.py -v`
→ **19 passed**.

`...test_hvac_cpr_batch_c.py` → 155 passed (no regression on the Batch C
suite).

## Per-site mutation drill table

Procedure: for each load-bearing site, mutate ONE site in production source,
clear `__pycache__`, run the TARGET test, confirm it goes red, restore,
clear `__pycache__`, verify `git status` matches the pre-drill tree.

| # | Site | File | Mutation | Target test | Result |
|---|---|---|---|---|---|
| 1 | Settle skip step `_s10_zone_skip_reason` step 0.6 | `hvac.py` | `return "post_preset_change_settle"` → `pass` | `T1_gate_active_within_settle` | RED ✓ |
| 2 | Observer stamp assignments in `update_zone_climate_state` | `hvac_zones.py` | three stamp assignments → `pass` | `T15a_observer_fires_on_preset_mode_change` | RED ✓ |
| 3 | Sentinel-seed first-readable path in `update_zone_climate_state` | `hvac_zones.py` | `if zone.prev_preset_mode == "" and ...:` → `if False:` | `T16_boot_seed_without_stamping` | RED ✓ |
| 4 | Confirmed-success reset in `_s10_success` | `hvac.py` | `rec["failures"] = 0` → removed | `T9_failures_reset_on_skipped_already_correct` | RED ✓ |
| 5 | Trip-wire ledger dispatch in `_s10_check_settle_held` | `hvac.py` | `_s10_ledger(...)` → `if False: _s10_ledger(...)` | `T18_trip_wire_fires_once_per_day` | RED ✓ |

Final `git status` (after all drills restored) shows ONLY the intentional
build diff on the three source files + the state-of-play edit + the new
test file. No stray mutations.

## Deferred

None vs. plan. T12 was DROPPED by Rev 3 R6 (hollow-anchor risk; the two
reachable-path mechanism discrimination lives in the post-ship falsifier
runbook, not a URA test mock).

## Note on `settle_episode_started_at` (vs. the plan's three ZoneState fields)

Rev 3 §Deliverables D1 Change 1 lists three new `ZoneState` fields. The
R4 trip-wire invariant ("continuous settle episode >= 4 h") requires an
episode-start anchor independent of the last re-stamp — otherwise
`s10_settle_held_s = now - last_observed_preset_change` would stay near-zero
while a flapping zone was continuously held. The build adds a FOURTH field,
`settle_episode_started_at`, set by the same observer path (fresh when the
prior stamp is None or expired past the settle window, otherwise carried
over). This is the only material deviation from the plan's shape and it is
required to make `INV-S10-SETTLE-OBSERVABLE` observable per T18. The field
is RAM-only on the same lifecycle as the other three.
