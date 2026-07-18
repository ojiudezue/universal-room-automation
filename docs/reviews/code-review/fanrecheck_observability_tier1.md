# Fan-Recheck Observability — Tier-1 Review Record

**Cycle:** durable arm/outcome/cancel rows to `ura_activity_log` + RAM veto-reason
counters (17 named gates) + eval denominator on the existing
`RoomFanRecheckStateSensor`. NO state-machine behavior change (primary invariant).
Branch `build/fanrecheck-observability`: af27584b (build, tag
pre-review-fanrecheck-obs) + 5e0214fd (fix-up). Merged to develop; **rides the
next sanctioned restart** — the 2-4 week veto-data clock for
`ANALYSIS_fan_recheck_loosening_options.md` starts then.
**Verdict:** SHIP (single Tier-1 adversarial pass; additive-only).

## Findings ledger

| ID | Sev | Finding (bug class) | Resolution |
|---|---|---|---|
| H1 | MED | Recorder churn: monotonic counter attrs would create a state row per coordinator update once the sensor is enabled — and enabling is how the data harvest happens (state-write amplification, write-flood-adjacent) | FIXED 5e0214fd: `_unrecorded_attributes` frozenset (mechanism verified against installed HA source, entity.py:518 — cited in code). Live attrs visible; recorder skips. Pre-existing attrs left recorded deliberately. |
| L1 | LOW | PAUSED-path cancels emit cancel + outcome rows (double terminal event for analytics) | FIXED: `cancel_driven: true/false` marker on outcome rows + tests both paths |
| L2 | LOW | `get_aggregate_counters` had no consumer | Documented as reserved for analysis-memo §9 follow-up |
| L3 | LOW | Spy tests don't exercise real serializer/dedup | ACCEPTED (activity_logger's 2KB cap + default=str + dedup are pre-existing, reviewer-verified at activity_logger.py:70-82,143) |
| — | note | Pre-existing double-restore race (`_cancel_and_restore_async` schedules while still PAUSED) — predates cycle, made *visible* not caused; dedup suppresses the duplicate row | Recorded for a future framing-C pass on the recheck machinery |

## Verified clean (reviewer, gate-by-gate)
19/19 veto substitutions one-for-one vs develop, 3/3 authorize points untouched;
`_veto` side-effect-free beyond counter, cannot raise; `hass.async_create_task`
is the tracked pattern; zero-DB-write-on-vetoed-tick proven (50-tick spy test);
payloads bounded scalars, queue-poison-proof; counters RAM-only, clean boot reset.

## Stats
0 CRITICAL/HIGH · 1 MED fixed · 3 LOW (2 fixed, 1 accepted). Tests 69 → 86
(+17), full suite envelope preserved (7156 pass / 36F / 14E).
