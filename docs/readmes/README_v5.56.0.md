# v5.56.0 — Writer B Retirement + Preset Reason Ledger

Removes the v3.3.5.9-era legacy preset writer (`ZoneAnyoneBinarySensor`'s
direct `climate.set_preset_mode` path — URA's ORIGINAL HVAC feature,
superseded by the HVAC Coordinator 12 days after it landed and never
retired; audit of record docs/planning/AUDIT_writer_b_removal_study.md).
The zone occupancy SENSOR is preserved byte-identical. Also ships the
operator-approved preset-change reason ledger: every preset write (and
night-trust suppression episode) records WHY —
stale_occupancy | vacant_past_grace | runtime_exceeded | pre_arrival |
house_state_transition — with input booleans echoed, in both
ura_activity_log details and DecisionLog context.

Evidence base: 2026-08-06 zone_1 incident — 5 home↔away oscillations
(16:05-17:45 CDT) + the smoking gun: 11 consecutive away→home re-issues
at ~5-min cadence (11:59-13:19 CDT) = the coordinator being stomped by
the untracked second writer. Baseline anchored in aggregation.py.

Reviews: Tier 2-DB (A removal-completeness / B ledger-correctness /
C test-authority) — 1 HIGH (stale-occupancy mislabel) + 1 HIGH
(unpinned precedence) + write-volume MED (per-tick suppression row →
episode-gated) all fixed; orchestrator pass caught a THIRD silent gap
(condition/reason mispairing passed the order-only anchor) — pairing
anchor added, red/green verified personally. Tests: 25 cycle tests;
suite 8243 passed, 21 pre-existing failures name-identical to develop.

## Live Validation (prospective)
- **Live:** zero URA-initiated home↔away oscillations on zone_1 over an
  equivalent occupied evening window (vs 5 on 2026-08-06); no repeated
  away→home re-issue chains.
- **Live:** preset_change rows carry `reason` within the first day;
  night-trust suppression appears as at most ONE row per episode.
- **Live:** ZoneAnyoneBinarySensor states unchanged across the deploy;
  dashboard zone cards unaffected; zero URA ERROR lines.
