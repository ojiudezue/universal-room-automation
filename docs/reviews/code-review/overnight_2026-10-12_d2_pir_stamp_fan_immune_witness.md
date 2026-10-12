# Review record — D2-PIR-STAMP-FOLLOWS-FAN-IMMUNE-WITNESS-1 (overnight 2026-10-12)

Branch `fix/d2-pir-stamp-fan-immune-witness`: build 487d8c69b (ura-builder) → fix-up 8e678d826 (orchestrator).
Base develop 9667cece1. Tier 1 (card), driven autonomously, so two framing-disjoint reviews plus an orchestrator verify.
Not deployed. Left in `review`.

## Findings

| ID | Sev | Reviewer | Bug class | Finding | Status |
|---|---|---|---|---|---|
| A-1 | HIGH | A (correctness) | #53 computed-but-not-consumed, the exclusion filter missing at one site | `_fan_immune_motion_witness_on` iterated raw `motion_sensors`, while `motion_detected` uses `_fusion_filter_active(...)`. An excluded (stuck-on) PIR then counted as a witness: the latch cleared every tick while the stamp never refreshed (oscillation), and with a radar bit on, the stamp leaked. | FIXED: helper iterates the filtered list; test `test_helper_false_when_witness_pir_is_excluded`; drill RED |
| A-2 | LOW | A | doc/comment accuracy | "Fail-closed" wording overstated the direction for the stamp. | FIXED: docstring states both directions + bound |
| B-1 | MED | B (consumers/fleet) | #53 consumer not enumerated | `_last_pir_motion_time` also feeds the P24 max-occupancy FAILSAFE freshness gate. GB1/GB2 (ZV + MS600) would newly force-vacate a sleeping guest after the failsafe duration. | FIXED by scope fence: failsafe reads new `_last_motion_bit_time` (legacy semantics). Tests: slice test on the real failsafe block + stamp test; drills RED. Whether the failsafe SHOULD ignore radar bits is left as a separate operator question on the card. |
| B-2 | LOW | B | stale doc (corrections ledger) | PRESENCE state-of-play said "ZV-only means D2 is UNREACHABLE (7/10 fan rooms)". Code: ZV is family `zigbee_zv`, not radar, so it is a witness. | FIXED: both doc lines marked CORRECTED/SUPERSEDED |

Cleared by A: legacy `None` fallback (only one production caller), grace-hold, ZV-only rooms byte-identical, unavailable states.
Cleared by B: restart seed (`_now`), fail-closed rooms (Media), per-tick cost. Fleet impact: GB1, GB2 change (D2 latch/stamp only); Media unchanged (no witness); the rest unchanged.

## Orchestrator verification
- Read full production diff; `motion_witness_detected` assigned unconditionally at function scope before the stamp site.
- Per-site mutation drills (PYTHONDONTWRITEBYTECODE=1, pycache cleared, file restored + `diff -q` identical after each):
  M1 helper raw list → `test_helper_false_when_witness_pir_is_excluded` RED; M2 failsafe reads witness stamp →
  `test_failsafe_freshness_reads_legacy_motion_bit_field` RED; M3 drop legacy stamp →
  `test_stamp_slice_failsafe_field_follows_raw_motion_bit` RED; M4 stamp guard `if True` →
  `test_stamp_slice_no_refresh_on_radar_motion_bit` RED.
- Targeted: 52 passed (d2 file + occupancy_source_follows_capability). Full-suite name-diff: run by ura-validator, recorded on the card.

## Stats
| Sev | Found | Fixed | Deferred |
|---|---|---|---|
| HIGH | 1 | 1 | 0 |
| MED | 1 | 1 | 0 |
| LOW | 2 | 2 | 0 |

Bug class frequency: #53 ×2 (one missed filter site, one unenumerated consumer). QUALITY_CONTEXT: no new class. Both are
instances of #53. Recommend adding "a shared timestamp has more than one reader" as an example under #53.
