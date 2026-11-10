# Review: SECURITY-LOCK-SWEEP-RETRY-CAP-1 merged onto v5.106.0 (overnight 2026-11-08)

Scope: the merge resolution only (commit 561d593a on integ/overnight-2026-11-08). The retry-cap feature itself was
reviewed on its old base (security_lock_retry_cap_review.md). Tier 1, one pass (framing A, local correctness).

## Why a re-review
v5.106.0 (SC-LOCK-SWEEP-EXCLUDE-1) and the retry-cap branch both edited `_evaluate_lock_check` and const.py, and they
conflicted. Resolution: exclusion runs before the retry cap; an excluded lock also clears any stale retry episode; the
sweep record keeps both `excluded` and `retry_capped`.

## Findings
| # | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| 1 | LOW | `retry_capped` was not exposed on the last-lock-sweep sensor (pre-existing on the retry branch) | Computed-but-not-consumed (#53) | FIXED: sensor.py attribute + test `test_last_lock_sweep_sensor_exposes_retry_capped` (mutation RED) |
| 2 | LOW | Episode for a lock removed from config lingered in `retry_capped` until restart (pre-existing) | Stale data source (#7) | FIXED: prune unconfigured episodes at sweep start + test `test_episode_for_unconfigured_device_is_dropped` (mutation RED) |

No CRITICAL/HIGH/MEDIUM. The reviewer confirmed: excluded locks are never commanded, counted or noticed; garage covers are
unchanged from the retry branch; episode semantics (observation mode, 24 h re-arm, end on locked/closed) are unchanged;
the only consumer of the sweep dict is sensor.py.

## Evidence
- New interaction test `test_excluded_lock_never_opens_or_keeps_a_retry_episode`: mutation of the episode-clear line -> RED.
- Full suite name-diff, candidate (develop c7e049ae + retry cap + optimizer meta + anomaly undeclare) vs plain develop:
  14 failed / 19,511 passed vs 14 failed / 19,488 passed; failing-name lists identical (0 new, 0 gone).

## Stats
| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| LOW | 2 | 2 | 0 |

Bug classes: #53 x1, #7 x1. No new class for QUALITY_CONTEXT.md.
