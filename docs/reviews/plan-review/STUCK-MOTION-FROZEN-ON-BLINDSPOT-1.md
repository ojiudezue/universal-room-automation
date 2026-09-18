# Plan-review — STUCK-MOTION-FROZEN-ON-BLINDSPOT-1 (occupancy freshness gate)

**Date:** 2026-09-18 · **Tier:** 2-DB · **Verdict on first draft:** NOT BUILD-READY (4 CRIT + 3 HIGH + 2 MED + 1 LOW)
**Method:** adversarial plan-review, claims re-greped (not trusted). All findings folded into
`PLANNING_occupancy_freshness_gate.md` before any build dispatch.

## Verified TRUE (reuse claims that held)
| Claim | Evidence |
|---|---|
| `SensorExclusionSet` multi-writer per-client + `reset_tick()` (no sticky state) | `sensor_exclusion.py:53-120` |
| demoted vote → 0 in the room OR | `coordinator.py:2247-2258` (`_fusion_filter_active`), legs `:3239-3254`, OR `:3260` |
| promotion sites real + ordered | `:2980` reset, `:2988` p22, `:3070` dutycycle, before legs `:3239` |
| `CORROBORATOR_DISAGREE_S=900.0` | `const.py:4184` |
| `_CORROBORATOR_KINDS` | `sensor_role.py:59-66` |
| precedent helper w/ non-empty guard + cold-state fail-safe | `coordinator.py:2619-2664` |

## Findings (all fixed in plan)
- **CRIT-1** room-tier exclusion never reaches zone/house; frozen sensor emits no edge → substrate bucket
  latched. → **added D2** (substrate-edge propagation; incident-fix acceptance criterion moved to D2).
- **CRIT-2** self-corroboration: incident subject `kind=motion` ∈ corroborator kinds → gate can never fire.
  → condition 3 subject-excludes the subject sensor.
- **CRIT-3** lone-corroborator vacuous-true (empty universal) + stale `_effective_corroborators_last_tick`.
  → non-empty guard + independent recompute / `_d2_completed_cleanly` gate.
- **CRIT-4** `camera_motion` is not a kind (`const.py:461-468`); incomplete floor map. → real-kind table +
  fail-safe never-demote default.
- **HIGH-1** `last_updated` bumps on attribute-only writes (Frigate churn) → use `last_changed`.
- **HIGH-2** INV-FRESH.2 overclaimed vs 11% p95 margin → restated as "never by age alone" + tail acceptance row.
- **HIGH-3** no sleep-doctrine guard / kill switch; `_mmwave_demoted_latch` false-clear. → all three added.
- **MED-1** no observable surface → D3.
- **MED-2** two-frozen-siblings → corroborator eligibility gate + accepted-gap non-goal.
- **LOW-1** release semantics → "per-tick recompute, no release bookkeeping."

## Build-prediction (fixed by plan wording)
Builder would otherwise: key floors on nonexistent `camera_motion`; reuse the corroborator loop verbatim
(never fires on motion subject + drops non-empty guard); use `last_updated`; wire inside the
`_detect_duty_cycle_stuck` try (one exception disables freshness); believe room demote fixes the zone.
