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

## Review A fix-up (commit 2)

Review file: `docs/reviews/code-review/v_hvac_s10_review_A.md` on branch
`review/hvac-s10-A`. Verdict FIX-REQUIRED (1 MEDIUM + 4 LOWs). All five
fixes shipped in the same follow-up commit on `feature/hvac-s10-settle`:

- **A-M1 (`get_s10_diagnostics`):** `s10_settle_held_s` now returns None
  once the last stamp is older than `S10_POST_PRESET_CHANGE_SETTLE_S`
  (mirrors `_s10_check_settle_held`). Prevents forever-growing display
  that would false-fire the live acceptance criterion.
- **A-L1 (`_s10_check_settle_held`):** latch keys on `dt_util.now().date()`
  (local calendar day) instead of UTC day; a continuous evening episode
  no longer fires twice in one local day.
- **A-L2 (`_s10_check_settle_held`):** entries for zones no longer in the
  rollout are pruned at the top of the check; a same-day re-add can warn
  fresh.
- **A-L3 (observer, `update_zone_climate_state`):** Carrier
  `hold_activity = None` ("no hold") is treated as READABLE value
  `"none"` so Bryant-schedule preset changes on unheld Carrier zones
  (zones 1/2 rollout) are stamped. Attribute ABSENT (ecobee / Generic)
  still unreadable → gate inert on those platforms (plan non-goal
  preserved). State-of-play §4.2 wording corrected.
- **A-L4 (`get_s10_diagnostics`):** field is an `int` (whole seconds), not
  a growing float — prevents recorder churn.

New tests (each FAILS without its fix): `test_RA_M1_diagnostic_none_after_release`,
`test_RA_L4_diagnostic_is_int`, `test_RA_L1_latch_uses_local_calendar_day`,
`test_RA_L2_latch_pruned_on_rollout_removal`, `test_RA_L3_carrier_none_hold_is_readable`,
`test_RA_L3_absent_hold_still_inert`. T18 extended with a post-release
`None`-diagnostic assertion.

Suite now at **25 passed** on `test_s10_post_preset_change_settle.py`.
CPR regression check (`test_hvac_cpr_batch_c.py`): **155 passed**.

Per-site drills (A-M1 + A-L3):

| Site | File | Mutation | Target test | Result |
|---|---|---|---|---|
| Diagnostics "released -> None" branch | `hvac.py` `get_s10_diagnostics` | `if last_age >= settle: settle_held[...] = None; continue` → `pass` | `RA_M1_diagnostic_none_after_release` | RED ✓ |
| Observer Carrier-None hold rule | `hvac_zones.py` `update_zone_climate_state` | restore pre-fix `new_hold = state.attributes.get("hold_activity", "") or ""` (so None → "" → unreadable) | `RA_L3_carrier_none_hold_is_readable` | RED ✓ |

Source restored after each drill; `__pycache__` cleared; `git status`
clean against the committed tree.

## Review B fix-up (commit 3)

Review file: `docs/reviews/code-review/v_hvac_s10_review_B.md` on branch
`review/hvac-s10-B`. Verdict FIX-REQUIRED (2 MEDIUM + 2 LOW):

- **B-M1 (NM wiring, `_s10_check_settle_held`):** the trip-wire now ALSO
  dispatches `_s10_notify(hazard_type="s10_settle_held", severity="LOW")`
  — the existing S10 NM path used by `s10_restore_not_taking`,
  `s10_preset_range_call_failed` etc. — in addition to the ledger row.
  Once per zone per LOCAL calendar day (A-L1 latch unchanged). Plan R4
  honored: ONE anomaly reaches NM.
- **B-M2 (restore-candidate coverage, `_s10_check_settle_held` +
  `get_s10_diagnostics`):** both now iterate `rollout ∪ zones-with-non-
  empty-snapshot`, so a ruling-A6 restore candidate (zone removed from
  the rollout but still carrying a saved original) is not silently
  stranded under a Carrier flap. A-L2 latch pruning widened to the same
  covered set.
- **B-L2 (persist, `_s10_success` apply branch):** `self.schedule_zone_state_save("s10_confirmed")`
  on the apply-mode CONFIRMED success so `failures = 0` survives a
  restart. Restore path's own persist unchanged.
- **B-L1 (documented residual):** stamps are RAM-only; a restart within
  ~10 min of a preset change can let the first post-boot pass read stale
  legs (narrow window; seed-without-stamp is intentional per plan R3).
  Noted here and in state-of-play §4.2 S10 row.

New tests (each FAILS without its fix): `test_RB_M1_tripwire_dispatches_nm`,
`test_RB_M2_restore_candidate_included`, `test_RB_L2_confirmed_success_persists_apply`.

Suite now at **28 passed**. CPR regression `test_hvac_cpr_batch_c.py`
**155 passed**.

Per-site drills (B-M1 + B-M2):

| Site | File | Mutation | Target test | Result |
|---|---|---|---|---|
| Trip-wire NM dispatch | `hvac.py` `_s10_check_settle_held` | `_s10_notify(...)` → `if False: _s10_notify(...)` | `RB_M1_tripwire_dispatches_nm` | RED ✓ |
| Covered-set union with snapshots | `hvac.py` `_s10_check_settle_held` | `covered = set(rollout) \| snapshot_zones` → `covered = set(rollout)` | `RB_M2_restore_candidate_included` | RED ✓ |

Source restored; `__pycache__` cleared; `git status` clean against the
committed tree.

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
