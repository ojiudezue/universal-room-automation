# Review record — HVAC-ARRESTER-EPISODE-CANCELS-AC-RESET-RESTORE-1 (unshipped)

- **Branch:** `fix/arrester-episode-keeps-ac-reset-restore` @ `0297b1afc` (base `develop` `d8397a070`)
- **Commits:** `4e5d7d900` (fix), `a513919fb` (fix-up 1: A-M1 defer + e2e tests + docs), `0297b1afc` (test docstring)
- **Tier:** 1 (hotfix), driven autonomously in the 2026-09-29 overnight pass, so it got two framing-disjoint reviews plus orchestrator verification (per the autonomous-Tier-1 rule)
- **Origin:** B-L3 in `docs/reviews/code-review/v5.103.23_hvac_w1_w2_finish.md` (pre-existing on develop)
- **Not deployed.** Needs a rebase after Batch B (`feature/hvac-w1-w2-finish`) lands. Same three callers, no new ones; Review B confirmed the rebase is semantically safe.

## Change
`_cancel_zone_timers` was renamed to `_cancel_arrester_timers`, and its scope cut to grace plus compromise. `_reset_timers` is no longer cancelled when an arrester episode arms (`hvac_override.py` startup audit, `_handle_severe_override`, `_handle_normal_override`). Fix-up 1 adds that `_verify_restore` skips the pre-reset preset restore while an episode is armed, so the arrester owns the preset return. The mode restore still fires.

## Findings

| ID | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| A-M1 / B-LOW-1 (converged) | MEDIUM | With the reset now kept alive, the verify step's ungated preset restore landed at about T0+90 s while grace was pending. It erased the human's hold early, then the compromise wrote over it (72→76→74→76 flap). | Two owners writing one zone (#53 family) | FIXED (fix-up 1) |
| A-L1 | LOW | The startup-audit call site can't be exercised at runtime (`_reset_timers` is always empty at the first-cycle audit) | — | Accepted; documented |
| A-L2 | LOW | Pre-fix harm was overstated. The B1 heat_cool enforcer (`hvac.py:2415-2419`) bounded the strand at about 5 min plus Carrier lag, not 20 min or indefinitely. The test docstring also named the wrong method. | Documentation drift | FIXED (docstrings + card corrected) |
| A-L3 | LOW | Tests asserted a proxy (dict membership), not the B6 write | Hollow anchor (#62) | FIXED (end-to-end tests); leftover never-awaited coroutine warnings from shared scaffolding LEFT |
| B-LOW-2 | LOW | Redundant B4/S4 writes when grace fires, because `zone.hvac_mode` is stale | Stale data source (#7), duplicate emit | Deferred (pre-existing in kind, bounded) |
| B-LOW-3 | LOW | The reset preset restore can cut a live compromise short, but only when off duration is 270 s or more (default 60 s) | Gate bypass on snapshot restore | Deferred (pre-existing in kind; mostly moot after A-M1 defer) |
| B-LOW-4 | LOW | State-of-play not updated; Batch B docs describe the old behaviour | Documentation drift | FIXED (state-of-play §7); Batch B doc lines listed for the merge step |
| Builder flag | — | The restore can overwrite a human hvac_mode change inside the ~79 s lag window | — | PARKED on the card (rare; a naive "still off" gate would recreate the stranding) |

## Verification
- Review A (local correctness) SHIP; Review B (race/lifecycle) SHIP.
- Orchestrator mutation drills (bytecode off, caches cleared, restored clean). Re-adding `_reset_timers` to the helper: 3 failed (severe, normal, helper). Neutralising the defer guard: 1 failed (`test_episode_armed_before_verify_defers_preset_restore`).
- Full-suite name-diff vs `d8397a070` (ura-validator): 0 new failures, 0 disappeared (150 failed / 3 errors already on baseline); +7 passing.

## Merge-step checklist (when shipped with or after Batch B)
- `README_v5.103.23.md:120,123`, `PLANNING_hvac_w1_w2_finish.md:681,836`, and `v5.103.23_hvac_w1_w2_finish.md:30` should record B-L3 as FIXED, with its stats rows moved.
- After resolving conflicts, `git grep _cancel_zone_timers -- custom_components quality/tests` should return only docstring mentions.

## Summary

| Severity | Found | Fixed | Deferred / accepted |
|---|---|---|---|
| MEDIUM | 1 (converged) | 1 | 0 |
| LOW | 6 | 3 | 3 |

Bug classes: #53-family two-owner write (1), hollow anchor #62 (1), stale data source #7 (1), documentation drift (2). No new QUALITY_CONTEXT class. The cross-owner cancel is an instance of the existing "one site not checking ownership" family.
