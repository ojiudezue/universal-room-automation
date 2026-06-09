# Code Review — Energy Unit Normalization + 4-Tier Attribution Cycle

**Branch:** `feature/energy-unit-normalization` (5cf3aeb build → 342cacc fix-up → 96981b9 fix-up 2 → b58541a fix-up 3)
**Plan:** `docs/planning/PLANNING_energy_unit_normalization_and_attribution.md`
**Protocol:** Operator-elevated Tier 2-DB — 3 parallel framing-disjoint reviews + focused fourth pass.
**Pre-review tag:** `pre-review-energy-unit-norm`
**Date:** 2026-06-09

## Review framings

- **A — Unit/numeric correctness + DB migration** (1 CRITICAL, 2 HIGH, 3 MEDIUM, 4 LOW)
- **B — Cross-tier attribution semantics vs B4 D1c intent + no-double-count + no-flap** (4 HIGH, 2 MEDIUM, 2 LOW)
- **C — Consumer surfaces + monotonic guards + None-propagation + test authority** (2 CRITICAL, 1 HIGH, 3 MEDIUM, 2 LOW)
- **Fourth pass (post-fix-up spot-check)** (1 HIGH, 3 LOW)

The disjoint-framing requirement was vindicated again: A and C independently
found the same two daily-trigger defects from opposite directions; B found
plan-deviation defects neither A nor C looked for.

## Findings ledger

| ID | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| A-C1 / C2 | CRITICAL | `today_delta_kwh` replaced tracker dict on date rollover, dropping `scope` → KeyError kills coverage sensor after first midnight | Shared-mutable-state clobber (#50 spirit, in-memory) | FIXED (342cacc) + date-boundary regression test |
| C1 / A-H2 | CRITICAL | `.get(STATE_ENERGY_TODAY, 0)` returns None when key present-with-None → `round(None*rate)` TypeError in EnergyCostTodaySensor | None-propagation | FIXED (342cacc) — returns None (unknown) per D4 semantics |
| A-H1 | HIGH | 90-day cleanup deleted `__schema_version__` sentinel → recurring full baseline reset every ~90 days | #7 stale/lost data | FIXED (342cacc) + behavioral test drives real cleanup DAO |
| B-H1 | HIGH | Plan D2.3 scope detection missing on zone/house-device tiers; mixed scopes summed instead of skipped | Plan-deviation / silent partial implementation | FIXED (342cacc) — per-tier classification + mixed→skip + warning |
| B-H2 | HIGH | B4 D1c divergence cross-check degenerate (≡0 by construction); acceptance criterion unmeetable | Acceptance-criteria fiction | RESOLVED by plan amendment (criterion replaced with delta_percent bounds rating); no fake metric fabricated |
| B-H3 | HIGH | Scope heuristic sticky-wrong on young cumulative counters (<1000 kWh) | #30-adjacent sticky misclassification | FIXED (342cacc) — midnight re-eval + immediate flip when "today" value exceeds threshold |
| B-H4 | HIGH | Restart asymmetry (rooms DB-persisted vs in-memory tiers) → all-day false Anomalous + misattributed #30 WARNING | #7 asymmetric data source | FIXED (342cacc + b58541a, see 4th-H-1) |
| C-H1 | HIGH | `current < 0.1` day-reset heuristic in normal range post-normalization → monotonic guard leaks decreases, recorder churn | Heuristic invalidated by unit change | FIXED (342cacc) — date-based acceptance at all 5 sites |
| A-M1 | MEDIUM | Migration race across N room coordinators could wipe fresh baselines | Concurrency | FIXED (342cacc) — atomic `migrate_energy_baselines_if_needed` in single queued write |
| A-M2 | MEDIUM | Schema-version read returning 0 on transient DB error → spurious full reset | Error-path conflation | FIXED (342cacc) — None = skip migration this boot |
| A-M3 | MEDIUM | Negative delta in (−500, 0) left stale baseline until midnight | Counter-reset handling | FIXED (342cacc) — any negative delta re-anchors |
| B-M1 / C-L2 | MEDIUM | `scope_mismatch_warning` / `whole_house_scope` flap on unavailable flicker | No-flap | FIXED (342cacc) — retain prior values on dead cycles |
| B-M2 | MEDIUM | `WholeHouseEnergySensor` raw-summed lifetime counters; disagreed with coverage attr by 6 orders | #30 sibling surface | FIXED (342cacc) — same classification treatment |
| C-M1 | MEDIUM | Docstrings claimed midnight anchoring; actual is boot-time | Doc accuracy | FIXED (342cacc) |
| C-M2 | MEDIUM | No epsilon band: −1% delta_percent read "Anomalous" chronically | Threshold sensitivity | FIXED (342cacc) — [−2, 0) treated as 0 |
| C-M3 | MEDIUM | D4 + migration tests were source-grep only | Test fixture authority (Pre-Deploy Zero-Bugs Gate memo) | FIXED (342cacc + 96981b9) — behavioral vs real DAOs/sqlite |
| A-L4 / C-L1 | LOW | Function-local `import time` | #34 watch-list | FIXED (342cacc) + full dt_util local-import sweep of both touched files (96981b9) |
| A-L1 | LOW | Missing-uom defaults to kWh passthrough | #30 | ACCEPTED — documented; uom-less Wh template sensor would still inflate; operator config hygiene |
| A-L2 | LOW | Reset-succeeds/set-version-fails ordering | Idempotent re-reset | ACCEPTED — harmless |
| B-L1 | LOW | Lazy midnight re-anchor drops 00:00→first-poll accrual | Bounded by poll interval | ACCEPTED |
| B-L2 | LOW | Mid-day counter reset loses pre-reset accrual | Documented in `_units.py` | ACCEPTED |
| 4th-H-1 | HIGH | `_last_reclassify_date = None` seed closed the B-H4 post-restart window on first read — protection never engaged | Sentinel-seed defect in a fix | FIXED (b58541a) — seeded with boot date |
| 4th-L-1 | LOW | `WholeHouseEnergySensor` lacks the midnight `scope_pending_reeval` parity path | Parity gap | DEFERRED — immediate-flip clause bounds the damage; revisit if live shows misclassification |
| 4th-L-2 | LOW | Same-day counter reset holds stale value until midnight (C-H1 trade-off) | Documented trade-off | ACCEPTED — Review-D awareness item |
| 4th-L-3 | LOW | Zone flattening double-counts a sensor_id shared across zones | Pre-existing, not a regression | DEFERRED — operator config hygiene (#31 family) |

### Fix-up regression caught between passes

The 342cacc fix-up itself introduced a **test-pollution defect**: the rewritten
migration test ASSIGNED a 2-attribute stub over
`sys.modules["custom_components.universal_room_automation.const"]` and never
restored it → 107 unrelated tests failed in full-suite runs while passing in
isolation. Root-caused and fixed in 96981b9 (suite-convention `setdefault`
mocks + driving the real `UniversalRoomDatabase` DAOs). The same commit's
dt_util sweep introduced 3 indentation slips (substring-match hazard of a
bulk line removal), caught by Read-back inspection and repaired in the same
commit. **Lesson:** bulk `replace_all` with an indented pattern substring-matches
deeper-indented lines; always re-grep + compile after a sweep.

## Summary statistics

| Severity | Found | Fixed | Accepted/Deferred |
|---|---|---|---|
| CRITICAL | 2 (deduped from 3 reports) | 2 | 0 |
| HIGH | 7 | 7 | 0 |
| MEDIUM | 8 | 8 | 0 |
| LOW | 9 | 2 | 7 (all documented above — none silent) |

## Bug class frequency

| Bug class | Hits this cycle |
|---|---|
| #30 Unit-of-Measurement Drift (and adjacents) | 4 (root cause + B-M2 + B-H3 + A-L1) |
| #7 Stale/lost/asymmetric data source | 3 (A-H1, B-H4, D4 root) |
| None-propagation | 2 (C1, audit) |
| Test fixture authority / source-grep tests | 2 (C-M3, sys.modules poison) |
| #50-spirit shared-state clobber | 1 (A-C1) |
| #34 function-local imports (watch-list) | 2 (A-L4, sweep) |
| Concurrency (migration race) | 1 (A-M1) |

## QUALITY_CONTEXT.md recommendations

1. **New bug-class candidate: "Test-suite sys.modules poisoning"** — a test
   file that ASSIGNS (rather than `setdefault`s) over a shared module path
   passes in isolation and fails ~100 unrelated tests in full runs. Detection:
   any `sys.modules[...] =` assignment in `quality/tests/` targeting
   `custom_components.*` or `homeassistant.*` paths another file may own.
2. **Extend #30's checklist line:** "any `float(state.state)` on an energy or
   power device-class entity without a uom check is a #30 recurrence" — this
   cycle proved the bug class was fixed 5 times on power surfaces while the
   energy surface stayed exposed for ~8 versions.
3. **Heuristic-invalidation note (C-H1 shape):** when a fix changes a value's
   magnitude regime, grep for magnitude-based heuristics (`< 0.1`, `> 1000`)
   downstream of the changed value.
