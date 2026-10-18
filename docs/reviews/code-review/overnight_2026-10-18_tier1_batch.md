# Review record: overnight 2026-10-18 Tier-1 batch (unreleased)

Three Tier-1 hotfixes built and reviewed by the unattended overnight pass. Not deployed; version and README get assigned at the next attended deploy. One review each (Tier 1), plus a combined full-suite name-diff (ura-validator) against tag `pre-review-overnight-1018`.

| Card | Branch | Commit | Review verdict |
|---|---|---|---|
| INIT-UNTRACKED-TASK-4211-1 | fix/init-untracked-task-4211 | 27ac96ccc | SHIP |
| ZONE-DELETE-ORPHAN-HVAC-SENSORS-1 | fix/zone-delete-orphan-hvac-sensors | 3e27887c8 | SHIP |
| SECURITY-REFIRE-INTRUSION-KEY-1 | fix/security-refire-intruder-key | e0ca1fd40 | SHIP |

## Findings

| # | Sev | Branch | Finding | Bug class | Disposition |
|---|---|---|---|---|---|
| 1 | LOW | init-untracked | A quick reload can cancel the TOU-rejected NM signal before it sends; the re-setup re-detects the bad file and sends again, so it heals itself. | Untracked background task (inverse) | Accepted, no fix |
| 2 | LOW | init-untracked | Guard test is an AST check, not a runtime cancellation test. | Hollow test anchor | Accepted (one-line fix; heavy fixture not worth it) |
| 3 | LOW | zone-delete | No test drives the leftover-warning site (config_flow.py ~12212) directly; it shares the helper with two tested sites. | Hollow test anchor | Accepted |
| 4 | LOW | zone-delete | Pre-existing: zone NAME prefixes ending in `_` still plain-prefix match, so zones `A` and `A_B` could cross-sweep. | One missed site (#53) | Residual recorded on the card |
| 5 | (fixed in build) | zone-delete | Bare `startswith` made deleting zone_1 sweep zone_10's id-keyed entities for every family. | Prefix collision | Fixed by `_zone_uid_matches` |
| 6 | MEDIUM (latent) | security-refire | `_active_alert` is cleared only on disarm; with `intruder` now re-evaluable, a future ALERT_HIGH would re-page CRITICAL every ~10 min after each ack until disarm/restart. Unreachable today (no `unknown_present` producer). `intruder` missing from NM COOLDOWN_CONFIG. | Suppression needs a discharge / #53 | Recorded as must-fix constraint on SECURITY-CENSUS-UNKNOWN-WIRE-1 |
| 7 | LOW | security-refire | `is_hazard_active` ignores location; consistent with one house-scope flag. | — | Accepted |

## Summary

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 1 (latent) | 0 | 1 (carded) |
| LOW | 5 | 0 | 5 (accepted / residual) |

## Bug class frequency

| Class | Count |
|---|---|
| Hollow test anchor | 2 |
| One missed site (#53) | 2 |
| Suppression needs a discharge | 1 |
| Untracked background task | 1 |

## QUALITY_CONTEXT.md

No new class. Finding 6 is a fresh instance of "suppression needs a discharge" applied to an alert latch: a latch with no "hazard gone" clear turns any re-fire path into a loop.
