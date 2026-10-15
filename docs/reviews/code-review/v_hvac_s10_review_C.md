# HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1: Review C (test authority via per-site source mutation, plus new surfaces)

Branch `feature/hvac-s10-settle` @ `5145a1e9b` (7110e6ba6 build + bdb5b4651 Review A fix-ups + 5145a1e9b Review B fix-ups). Base `663fda018`, verified as the merge-base with `develop`.
I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full before starting. I also read the production diff, the test file, Reviews A and B, and the NM routing code with the live NM config.

**Method.** I neutered one site at a time in production source, cleared `__pycache__` and set `PYTHONDONTWRITEBYTECODE=1`. Then I ran `test_s10_post_preset_change_settle.py` + `test_hvac_cpr_batch_c.py` in ONE process (`.venv-ha`, `PYTHONPATH=quality`) and wrote the original back in a `finally`. Baseline: 183 passed. `git status` was clean after every run.

**Verdict: FIX-REQUIRED** (1 HIGH, 4 MEDIUM, 4 LOW)

## Drill table

| # | Site neutered | Result | Test(s) that went RED |
|---|---|---|---|
| M01 | observer: first readable observation stamps instead of seeding | RED | T16, T17, T15a, RA_L3_carrier_none |
| M02 | sentinel: `"unknown"` treated as readable | RED | T17 |
| M03 | Carrier `hold_activity=None` → unreadable | RED | RA_L3_carrier_none_hold_is_readable |
| M04 | absent `hold_activity` → readable | RED | RA_L3_absent_hold_still_inert |
| M05 | stamp `last_observed_preset_change = now` removed | RED | T15a, T15b, T16, RA_L3_carrier_none |
| M06 | `settle_episode_started_at = now` never set | RED | T15a, RA_L3_carrier_none |
| **M07** | **episode start reset on EVERY re-stamp (`prev_stamp is None` → `True`)** | **GREEN** | none |
| M08 | step 0.6 removed entirely | RED | T1, T3, T5, T6, T8, T13, T15a/b, T19, RA_L3 (note: T4 and T14 stay GREEN) |
| **M09** | step 0.6 `<` → `<=` | **GREEN** | none |
| **M10** | step 0.6 except → fail-OPEN (`return None`) | **GREEN** | none |
| M11 | step 0.6 placed after `s1_same_tick` | RED | T19 |
| M12 | apply pass ignores settle (pass level) | RED | T3 |
| **M13** | restore pass ignores settle (pass level) | **GREEN** | none |
| **M14** | pre-call re-check ignores settle | **GREEN** | none |
| **M34** | M13 + M14 together (restore path has NO settle gate at all) | **GREEN** | none |
| M15 | `rec["failures"] = 0` in `_s10_success` removed | RED | T9, T10, RB_L2 |
| M16 | SKIPPED_ALREADY_CORRECT call site bypasses `_s10_success` | RED | 4 batch-C tests (restore confirm / A6) |
| **M17** | limit-matching-view call site bypasses `_s10_success` (pre-existing site) | **GREEN** | none |
| **M35** | APPLIED branch ALSO resets `failures` (ruling A4 broken) | **GREEN** | none |
| M18 | `schedule_zone_state_save("s10_confirmed")` removed | RED | RB_L2 |
| **M19** | trip-wire threshold → 0 (fires on any armed episode) | **GREEN** | none |
| M20 | trip-wire threshold ×2 | RED | T18, RB_M1, RB_M2, RA_L1 |
| M21 | trip-wire freshness (release) branch removed | RED | T18 |
| M22 | NM dispatch removed | RED | RB_M1, RB_M2 |
| M23 | ledger row removed | RED | T18, RB_M1, RB_M2 |
| M24 | once-per-day latch write removed | RED | T18, RB_M1, RA_L1 |
| M25 | local day → UTC day | RED | RA_L1 |
| M26 | prune removed | RED | RA_L2 |
| M27 | trip-wire covered set = rollout only (B-M2 reverted) | RED | RB_M2 |
| M28 | diagnostic = rollout only | RED | RB_M2 |
| M29 | diagnostic None-after-release removed (A-M1 reverted) | RED | RA_M1, T18 |
| M30 | diagnostic `int` → `float` | RED | RA_L4, RA_M1, RB_M2 |
| **M31** | **`self._s10_check_settle_held()` call in `_async_apply_preset_overrides` removed** | **GREEN** | none |
| M32 | `s10_settle_held_s` key dropped from diagnostics | RED | T18, RA_M1, RA_L4, RB_M2 |
| M33 | severity LOW → HIGH | RED | RB_M1 |

23 of 35 RED, 12 GREEN (M13 and M14 are also covered by M34).

## Findings

| # | Sev | Site | Bug class | Finding |
|---|---|---|---|---|
| C-H1 | HIGH | `hvac.py` `_s10_check_settle_held` NM (`hazard_type="s10_settle_held", severity="LOW"`); `notification_manager.py` `async_notify` per-person loop ~1712-1900, `_route_for_recipient` 4198, `_channel_qualifies` 4510; `database.py` `get_pending_digest` 4572 | Suppression without a discharge / display that lies (B-M1 not actually satisfied) | **The settle-held NM reaches no human under the live config.** Live config (`.storage/core.config_entries`, Coordinator Manager entry): one recipient `person.oji_udezue`, `nm_person_delivery_pref=digest`, no routing matrix and no hazard override. Channel gates: pushover/imessage/whatsapp `CRITICAL`, companion `HIGH`, lights `HIGH` but `nm_lights_enabled=False`, TTS disabled. For LOW, `effective_pref=digest`. The router's legacy/materialized matrix gives `_channel_qualifies(ch, LOW)` = False for every channel, so `_router_allowed` is empty. No immediate send happens, and **no digest row is queued**: digest rows are written only when the channel is in `_router_allowed`. The only row is the per-recipient `message='[audit]'` audit row, which `get_pending_digest` excludes by design. The net result is an INFO log + an audit row + the ledger row, which is the same silent outcome B-M1 asked to fix. RB_M1 passes because the test NM stub records every `async_notify` call and models no routing. **Fix:** severity `HIGH`, which coerces to IMMEDIATE and passes the companion gate (once per zone per local day, so it does not flood). The other options are an operator ruling plus an amended plan saying a ledger row is enough. Note: the pre-existing S10 NMs at MEDIUM/LOW (`s10_restore_not_taking`, `s10_preset_range_call_failed`, `s10_preset_range_not_sticking`, `s10_restore_pending`, backstop) are equally undelivered under this config. That is pre-existing and should be carded, not fixed here. |
| C-M1 | MEDIUM | `quality/tests/test_s10_post_preset_change_settle.py` T4, T14 (restore) and T5 (pre-call) | Hollow test anchor (#62) | **The settle gate on the restore path and at the pre-call re-check is untested.** M34 strips the gate from both the restore pass and the pre-call re-check and the suite stays green. M08 (gate deleted outright) leaves T4/T14 green too. They are vacuous: the staged snapshot (68/76) equals the live climate (68/76), so the restore never reaches a wire row either way. T5 calls `_s10_zone_skip_reason` directly, so it never exercises the pre-call site its docstring claims. The restore gating is the whole rationale of B-M2. **Fix:** in T4/T14, stage a snapshot that DIFFERS from the live range, assert a `S10_preset_range_restore` row appears with no stamp (control), then assert none appears with the stamp. Add a pre-call test that arms the stamp inside `_s10_save_strict` (monkeypatch the awaited save to set the stamp) and asserts zero `S10_preset_range` rows. |
| C-M2 | MEDIUM | `hvac_zones.py` observer episode-extension branch (`prev_stamp is None or age >= SETTLE`) | Hollow test anchor (#62); #53 risk | M07 (reopen the episode on every re-stamp) stays green. If that happened, `episode_s` would never exceed 600 s and the 4 h trip-wire could never fire in production. T18, RB_M1, RB_M2 and RA_L1 all set `settle_episode_started_at` by hand. **Fix:** a test that drives `update_zone_climate_state` through `H.set_climate` flips every 300 s for 4 h+, and asserts that `settle_episode_started_at` is unchanged and that `_s10_check_settle_held` fires. Also add one flip after a gap of 601 s or more that asserts a new episode start. |
| C-M3 | MEDIUM | `hvac.py` `_async_apply_preset_overrides` call `self._s10_check_settle_held()` (~4195) | Wire-in anchor missing | M31 (delete the call) stays green. Every trip-wire test calls the method directly, so the production wire-in is unanchored, and the R4 discharge could be dropped by a refactor with the suite still green. **Fix:** arm a 4 h+ episode, `await coord._async_apply_preset_overrides()`, and assert one `s10_settle_held` ledger row. |
| C-M4 | MEDIUM | T11 `test_T11_applied_does_not_reset_failures` | Hollow test anchor (#62) | M35 (APPLIED also zeroes `failures`, breaking ruling A4 / half of INV-S10-LATCH-RESET) stays green. T11 runs its own copy of the APPLIED record update instead of driving `_s10_write_one`. **Fix:** stub `strategy.set_preset_range` to return `APPLIED`, drive `_s10_write_one` (or `_s10_pass`) with `failures=2` pre-staged, and assert `failures == 2` afterwards. |
| C-L1 | LOW | step 0.6 boundary and fail-closed except | Untested boundary | M09 (`<=`) and M10 (fail-open) are green. Add `set_stamp(Z1, 600)` → not settle (equality boundary), and a zone whose stamp is a non-datetime → `post_preset_change_settle`. |
| C-L2 | LOW | trip-wire threshold | Missing negative test | M19 (threshold 0) is green, so no test shows that an episode under 4 h does NOT fire. Add an armed episode of `S10_SETTLE_HELD_WARN_S - 60` and assert zero rows and zero NMs. |
| C-L3 | LOW | limit-matching-view call site of `_s10_success` (pre-existing) | Coverage gap | M17 is green. T10 calls `_s10_success` directly. D2's "reset at both sites" holds by construction (the reset lives in the helper), but the limit-site call itself is unanchored in these two files. One test that drives `_s10_write_one` with `writes=3` and a matching view would close it. |
| C-L4 | LOW | whole test file | Literal oracles | Tests use the literals 600 / 601 / 14_400 / 14_500 rather than importing `S10_POST_PRESET_CHANGE_SETTLE_S` / `S10_SETTLE_HELD_WARN_S`. A retune of either constant silently invalidates the boundaries. Import the constants and express offsets relative to them. |

## Cleared (holds because)

- **Observer wire-in is real:** T15a/b, T16, T17 and RA_L3 drive `update_zone_climate_state` against real `hass.states.async_set` (StubHass) and the real `ZoneState`. M01-M06 each turn a named test red.
- **Ordering before `s1_same_tick`:** M11 → T19 red.
- **Apply-pass settle gate:** M12 → T3 red. T3 is non-vacuous (M08 also turns it red).
- **Failures reset + persistence:** M15 → T9/T10/RB_L2 and M18 → RB_L2.
- **Trip-wire mechanics:** latch, local day, prune, union, release, ledger and NM call are each pinned (M20-M27).
- **Diagnostics:** None after release, int, union and key presence are each pinned (M28-M30, M32).
- **Tree hygiene:** every drill restored the file in a `finally`. `git status --short` showed only the untracked drill script after each batch, and the script has been deleted.

## Must-fix

C-H1 (raise the settle-held NM to a severity that reaches the operator, or get an operator ruling plus amended docs). C-M1 to C-M4 (make the restore/pre-call, episode-extension, wire-in and APPLIED tests non-hollow; each fix is a test-only change). The LOWs can go in the same pass. Card the pre-existing S10 MEDIUM/LOW NMs that are undeliverable under the live channel thresholds.
