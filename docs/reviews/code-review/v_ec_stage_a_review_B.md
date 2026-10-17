# EC storm/blind Stage A — Tier-3 Review B (integration / state-machine integrity)

Branch `feature/ec-stage-a` @ 693814989, diff base develop `f2ec3cb38` (verified = merge-base; three-dot).
Spec: `PLANNING_ec_storm_and_blind_decisions.md` Rev 3.3 Stage A.
HVAC / presence docs not applicable (energy-only change).

## Verdict: SHIP (no CRITICAL/HIGH/MEDIUM; two LOW notes, no must-fix)

## Checks

| Area | Result | Evidence |
|---|---|---|
| Golden captured pre-change | PASS | Fixture added only in `b79a137a2` (parent of feature commit 15b7ab39b), never touched after. Re-ran `test_ec_stage_a_noop_golden.py` in a scratch worktree at `b79a137a2`: 180 passed, so the fixture is what pre-Stage-A code produces. Test drives real `make_shell(...).determine_mode(...)` and compares `mode/reason/actions/cfg/phase/desired/dp_stamp` (test_ec_stage_a_noop_golden.py:66-95). Harness `_reserve_governor_harness.py` is not in the diff. |
| Byte-identical sighted path | PASS | `_reserve_action` (energy_battery.py:6403-6486) is the old `_result` reserve block verbatim plus fold + earlier stamp. Floor is entry-reset at :5522 and only registered at :5859 (sighted) / :5637 (blind), so every `_result` before :5859 (grid-disconnect, :5845) folds nothing. Old stamp at end of `_result` and new stamp in `_reserve_action` produce the same value when no floor; nothing between them in `_result` reads `_last_reserve_level_desired`. Off-peak clamps re-keyed to `_tick_reserve_floor` (:6300, :6341): full_hold always returns before (:5860-5936), partial floor = `max(reserve_soc, partial)` (inclement.py:753-755) = `effective_reserve` (:5945). |
| No suppression of legitimate actions | PASS | Fold is raise-only (`max`). Blind full_hold exemption still emits no CFG turn_off and no CFG turn_on (`_result` not called on blind). De-escalation still emits `switch.turn_off`; its reserve is now `max(reserve_soc, floor)` — planned. |
| Restart | PASS (known limit) | `_tick_reserve_floor` is per-tick (entry-reset). `_last_reserve_level_desired` None at boot → blind base falls back to write leg; both None → one write of F, then deadband against the stamp (`_compare_to`, :5683-5686). Blind flags RAM-only, reset on every non-blind tick (:5785-5787); restart mid-raise loses the release = plan §12 known limit 8. Slider: `_inclement_config` re-reads CM `entry.options` each tick (:2591-2655) and the Number seeds from the same options (number.py:837-845); first tick after restart uses the persisted value. |
| v5.103.66 governor | PASS | `reserve_write` row: `tick_floor`/`tick_hold_depth` additive in `details_json` (energy.py:9287-9325); change-gate key `(path, value, hold_owner)` and `inclement_floor`/`floor_ok` semantics unchanged. `RESERVE_SET_VALUE_WRITERS` swaps `_result`+`determine_mode` for `_reserve_action` count 1 (energy_const.py:2328-2333); lint test re-pointed and still proves count-mismatch on injection. Optimizer `_check_reserve_role_hard_deny` (optimization.py:4514) is role-based, untouched. Governor A/B golden: 7 sighted branches exact, `blind` diff limited to `{last_reserve_level_desired, reason}`. |
| Write-verify / force_redispatch | PASS | Blind now stamps desired but not `_desired_stamped_at` (I-D3 kept). Within 600 s of blind onset the verifier sees desired == what blind wrote (more coherent than before, where desired was the stale sighted intent — the 2026-07 incident shape); after 600 s it stands down as before (energy_write_verify.py:890-905, energy_battery.py:6922-6944). |
| EVSE drain-precedence / overlay | PASS | Overlay clamps up to `_last_reserve_level_desired` (energy.py:5487-5502), now folded → inherits the floor. `_offpeak_drain_branch_target` stamp unchanged on sighted ticks (golden `dp_stamp`). |
| Options listener / no CM reload | PASS | Key in `_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS` (__init__.py:7453, :7495). `test_blind_floor_key_in_options_reload_suppress_keys` drives the real `_async_update_listener` via `test_cm_reload_suppression` loader: 0 reload calls, snapshot advances. |
| Renamed symbols / cross-coordinator readers | PASS | Only `RESERVE_SET_VALUE_WRITERS` rows changed; grep of `_result`/`determine_mode` writer references outside the lint test: none. New attrs `_tick_reserve_floor` read only by energy.py:9287. |
| Seven edited pre-existing tests | PASS, not weakened | arbitrage_floor (2): additionally disable `_registered_floor` so the per-branch wrap stays proven load-bearing. test_energy_battery (2): `[]` → exactly one `set_value 60`, no turn_off, `Blind hold — ` prefix; freshness test adds a control branch (stale-stamped decision → de-escalation fires). writeback: +1 key count 101→102. governor_ab: sighted exact, blind diff key-set pinned. chokepoint lint: re-pointed. write_rows: value 10→50 / floor_ok False→True per INV-1, plus tick_floor asserts. |

Targeted run on HEAD (cycle files + edited files + test_runtime_smoke): 596 passed; 2 failed + 2 errors all in test_runtime_smoke (`test_hvac_coordinator_async_setup_does_not_raise`, `test_database_init_creates_v4511_tables`, StubBus `event_filter`) — identical failures on develop main checkout, pre-existing.

## Findings

- **LOW-1 (restart, documented known limit)** energy_battery.py:5785-5787 / :454-457 — blind episode flags are RAM-only; restart while a blind raise is in place leaves the raised reserve until the first sighted tick. Plan §12 item 8. Cost-only, bounded by blindness. No action.
- **LOW-2 (behavior change, planned)** energy_battery.py:5662-5664 / :5689-5695 — a blind release restores `_blind_pre_raise` even when that captured base (write-leg) is below `reserve_soc` (e.g. hardware 0). Pre-Stage-A blind never wrote a value below `reserve_soc`. This restores the pre-raise hardware state and matches the plan's "restore the captured pre-raise value"; flagged for Framing D/A to confirm it is intended rather than floored at `reserve_soc`.

## Bug-class tally
Untracked background tasks: 0. Restart/RestoreEntity: 1 LOW (known limit). Byte-identical no-op: holds. #53 one-missed-site: no leak seen in my lane (D owns the full enumeration).
