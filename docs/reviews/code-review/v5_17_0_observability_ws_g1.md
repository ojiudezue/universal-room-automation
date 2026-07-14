# Review record — v5.17.0: Observability WebSocket surface + G1 control attrs

**Date:** 2026-07-13/14 · **Builds:** `ff74a24d` (WS), `af77b605`→cherry-pick `96e9c9ec` (G1) · **Fix-up:** `63a128e8` · **Baseline tag:** `pre-review-v5.17.0`
**Protocol:** WS = Tier 2 (framings A+B, both on `ura-reviewer-std`/Opus per the cost trial); G1 = Tier 1 (single pass, Opus). Live validation (Review 3) pending post-deploy.

## Findings

| ID | Sev | Surface | Finding | Bug class | Fixed |
|---|---|---|---|---|---|
| A1 | CRITICAL | const.py severity map | Name→number map fabricated (`error/fatal` aliases; `critical→'3'`) vs canonical `AnomalySeverity` (INFO=0…CRITICAL=4) → `severity=critical` returned ALERT rows, silently dropped true CRITICALs. Docs enshrined the same wrong table. | #22 enum mismatch | ✅ map fixed; test now DERIVES expected map from the production enum |
| A2 | CRITICAL | subscribe min_severity | Same broken map on the live-push path | #22 | ✅ via A1 |
| B-H1 | HIGH | websocket_api push | `connection.send_message` called directly from dispatcher callback — fires on sync worker threads (v4.6.3.2 precedent at sensor.py:12648) → intermittent RuntimeError swallowed by callback except | thread-affinity (#34-adjacent) | ✅ marshalled via `hass.add_job` |
| B-H2 | HIGH | subscribe filter | `min_severity` read `payload["severity"]` which NO emit site produces (payload carries `importance`) → filter dead, all subscribers over-notified | #7 wrong data source / #55 reads-without-writers | ✅ renamed `min_importance`, ordinal map, below-floor dropped incl. missing field |
| B-H3 | HIGH | subscribe streams | `anomalies` vs `activity` streams indistinguishable (single OR-gate) | — | ✅ discriminated on `action == "anomaly"`; doc notes live anomaly-severity filtering unavailable until emit payload enriched |
| A3 | MED | DAO projection | Default columns include ALTER-added names; on un-migrated DB → OperationalError swallowed to empty-SUCCESS feed | silent-empty | ✅ PRAGMA-intersect + error surfaced |
| B-M1 | MED | registration | Mid-sequence register failure left partial registration unrecoverable behind swallow | lifecycle | ✅ idempotent per-command skip |
| A4/A5/B-L2 | LOW | envelope/logs | dead `capped` doc note; `str(exc)` leak; debug-level push failures | — | ✅ all |
| G1-L1/L2 | LOW | G1 | falsy-coerce robustness note; worktree base-state red (explained: fork predates WS suites; cross-cycle leak) | — | noted, no change |

## Statistics

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 2 | 2 | 0 |
| HIGH | 3 | 3 | 0 |
| MEDIUM | 2 | 2 | 0 |
| LOW | 5 | 3 | 2 (G1 notes, no change needed) |

Framing disjointness held again: A and B findings had ZERO overlap. A caught the enum fabrication via cross-check against production source; B caught thread-affinity + dead-filter + stream conflation via emit-site tracing. Neither would have found the other's set.

## Executed mutations (fix-up, all restored green)
severity map re-broken → RED; add_job unmarshalled → RED; stream discrimination collapsed → RED; importance floor neutered → RED (2 tests). G1 build: options-fallback dropped → RED; copy→ref → RED.

## Merged-state verification (orchestrator, independent)
- Cherry-pick `96e9c9ec` clean; spot-checked fixed map + add_job marshal in source directly.
- `test_g1_room_control_list_attrs.py` + `test_websocket_api.py`: 23/23 green on merged develop.
- Full suite: 36 failed / 14 errors — failing set identical to pre-cycle baseline; +23 net new passing.

## QUALITY_CONTEXT candidates
- B-H2 is a textbook new sub-pattern of #55: **a filter reading a field no producer emits** — "dead filter" (consumer-side reads-without-writers). Recommend noting under #55.
- A1 reinforces #22's standing mitigation: enum maps in consts MUST be built or asserted from the production enum, never hand-copied (now enforced by test here).

## Pending
- Live Validation (Review 3) post-deploy: wscat smoke of the three commands against the real socket; G1 = 38-row Appendix-A diff (PLANNING_g1_room_control_list_attrs.md); README write-back per ledger rule.
