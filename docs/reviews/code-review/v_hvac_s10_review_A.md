# HVAC-S10-STALE-RANGE-AFTER-PRESET-CHANGE-1 — Review A (local correctness / edge / boundaries)

Branch `feature/hvac-s10-settle` @ `7110e6ba6`, base `develop` 663fda018 (verified = merge-base).
I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full, plus the plan (Rev 3) and the build notes.
Targeted suite: `test_s10_post_preset_change_settle.py`, 19 passed.

**Verdict: FIX-REQUIRED** (1 MEDIUM; the LOWs can be fixed in the same pass)

## Findings

| # | Sev | Site | Bug class | Finding / repro |
|---|---|---|---|---|
| A-M1 | MEDIUM | `hvac.py` `get_s10_diagnostics` ~5085-5100 | Stale data source (#7) / display that lies | `s10_settle_held_s` = `now - settle_episode_started_at` whenever the stamp is non-None. The stamp is never cleared, and the diagnostic, unlike the trip-wire, does not check that the stamp is still fresh (`< S10_POST_PRESET_CHANGE_SETTLE_S`). **Repro:** zone_3 makes one S1 preset change at 08:00 and nothing changes after that. The gate released at about 08:15, but at 12:00 the attribute reads 14 400 and at 20:00 it reads 43 200. That trips the plan's own live criterion (“no rollout zone reports `s10_settle_held_s >= 14_400`”) and sends any diagnostician the wrong way. T18 never checks the diagnostic after release. **Fix:** return None, or 0, when `now - last_observed_preset_change >= S10_POST_PRESET_CHANGE_SETTLE_S`, mirroring `_s10_check_settle_held`. Add a T18 assertion after the 601 s advance. |
| A-L1 | LOW | `hvac.py` `_s10_check_settle_held` (`today = now.date()` on `dt_util.utcnow()`) | Day-boundary-blind | "Once per calendar day" uses the UTC day, so it rolls over at 19:00 CDT. A continuous episode spanning local evening can fire twice in one local day. Use `dt_util.now().date()`. |
| A-L2 | LOW | `hvac.py` `_s10_settle_held_fired_on` | Stale latch | A zone removed from the rollout keeps its latch entry, because the loop iterates the rollout only. If it is re-added the same day, an episode over 4 h is silently suppressed. Prune keys not in `rollout` at the top of the check. |
| A-L3 | LOW | `hvac_zones.py` observer, `new_hold = ... or ""` | Doc ≠ code (state-of-play says "brand-neutral") | Carrier sets `hold_activity` to None when there is no hold (`ha_carrier/climate.py:261-269`), and ecobee/Generic have no such attribute. Every observation without a hold is therefore "unreadable": a Carrier schedule-driven preset change while unheld (zones 2/3 still run Bryant schedules) is never stamped, and the gate is fully inert on ecobee/Generic. That contradicts plan R7 ("ecobee gate DELAYS on option-C flip") and the doc's "brand-neutral" wording. No ecobee zone is in the rollout, and `infinite_holds` keeps Carrier zones held almost always, so impact is low. Correct the doc and R7 wording, or treat `None` hold as the readable value `"none"` for Carrier. |
| A-L4 | LOW | `get_s10_diagnostics` | Recorder churn | An unrounded float that grows on every sensor update makes the attribute differ on every write. Use `int(...)`. |

## Cleared (holds because)

- **Seed / sentinel:** both prev fields are set together, so `("","")` occurs only before the first readable observation. `""` / `"unknown"` on either leg skips with no prev update and no stamp (T16, T17). On an `unavailable` state the early return at `hvac_zones.py:672` leaves the prev fields untouched. On `unknown` the state carries no attrs, so `preset_of_for` returns `""` and the observation skips.
- **4th field `settle_episode_started_at`:** correct and needed. It opens when the prior stamp is None or ≥ 600 s old and is carried while re-stamps stay < 600 s apart. The boundaries agree with step 0.6 (`<` gates, `>=` opens a new episode). The episode ENDS implicitly once the last stamp turns 600 s old; nothing clears the field. The trip-wire handles that correctly; the diagnostic does not (A-M1).
- **Step 0.6:** placed after `climate_unreadable` and before egress / a-b / `s1_same_tick` (`hvac.py:4445-4458`). Strict `< 600`. Both datetimes are aware (`dt_util.utcnow()`). An exception fails closed. It is shared by apply, restore and the pre-call re-check (`:4551`, `:4748`).
- **D2 reset:** `rec["failures"] = 0` is set only in `_s10_success`, which is called only at `:4681` (limit-matching view) and `:4791` (SKIPPED_ALREADY_CORRECT). APPLIED does not reach it (ruling A4 preserved).
- **Trip-wire:** never fires for non-rollout zones (it iterates `_s10_rollout_zone_ids()`). It needs a fresh stamp and an episode ≥ 14 400 s. The latch clears on release or a missing zone. After a restart, RAM fields reset and the first readable observation seeds without stamping, so it cannot false-fire. It is wrapped in try/except, and it runs only once the switch has resolved.
- None handling: every read is `getattr(..., None)` and guarded.

## Must-fix
A-M1. A-L1 to A-L4 are recommended in-cycle; each is 1-5 LoC.
