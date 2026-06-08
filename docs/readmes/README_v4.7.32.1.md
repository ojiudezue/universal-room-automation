# v4.7.32.1 — SPAN prune guard: substring match (fix-forward)

**Tier:** 1 hotfix (fix-forward on v4.7.32 Part B). The prune *mechanism*
(backup-then-delete, reversibility, scoping) was Tier 2-DB-reviewed and
validated working in v4.7.32 live-validation — only the match guard was too
narrow.

## What changed
v4.7.32 pruned orphaned SPAN `circuit_power` baselines whose scope
**started with** "Unmapped Tab". Live validation showed the actual scopes are
panel-prefixed — `"Span Left Unmapped Tab 24 Power"` / `"Span Right Unmapped
Tab 32 Power"` (older ones were bare `"Unmapped Tab N Power"`). So v4.7.32
pruned only the 4 bare-named baselines and left 11 panel-prefixed ones warning.

Guard changed from `str(scope).startswith("Unmapped Tab")` to
`"Unmapped Tab" in str(scope)` — catches panel-prefixed and bare scopes; a real
user-named circuit never contains "Unmapped Tab".

## Reversibility (unchanged)
- In-DB: each pruned row → `metric_baselines_pruned_backup` before delete.
- Snapshot: `~/ura-db-backups/metric_baselines_pre_v4.7.32.sql` already captured
  all 15 unmapped rows (4 pruned in v4.7.32 + 11 to prune now), restorable via
  `INSERT OR IGNORE`.

## Acceptance
- **In-suite:** `test_v4732_heat_cool_and_span_prune.py` (12) — guard assertion
  updated to the substring form. Suite baseline = zero new failures.
- **Live (write back post-restart):** boot log `SPAN: pruned 11 orphaned
  'Unmapped Tab' circuit baselines`; "N could not be matched" drops to only the
  genuine non-Unmapped renames (≈3); `metric_baselines_pruned_backup` now holds
  all 15; no fresh URA errors.
