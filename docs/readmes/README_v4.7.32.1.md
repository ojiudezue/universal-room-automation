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

### Live Validation — Validated 2026-06-08 (fresh live-DB reads, read-only SSH)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | v4.7.32.1 loaded | ✅ PASS | `installed_version=v4.7.32.1` (this boot). |
| 2 | All "Unmapped Tab" baselines pruned | ✅ PASS | Live DB: `0` remaining `circuit_power` baselines with scope LIKE `%Unmapped%` (was 15 across v4.7.32+.1). |
| 3 | Reversibility — all 15 backed up | ✅ PASS | `metric_baselines_pruned_backup` holds **15** rows: the 4 bare `Unmapped Tab N Power` (pruned in v4.7.32) + the 11 `Span Left/Right Unmapped Tab N Power` (pruned in v4.7.32.1). Restorable via `INSERT OR IGNORE`. Plus the pre-deploy dump `~/ura-db-backups/metric_baselines_pre_v4.7.32.sql`. |
| 4 | Real renames kept, not pruned | ✅ PASS | This boot warned only `3 circuit baselines could not be matched` — `Battery Power`, `Span Left Subpanel Power`, `Span Left Unknown Power` (genuine non-"Unmapped Tab" renames; correctly preserved for operator review). Warning count fell 18 → 3. |
| 5 | No new URA errors | ✅ PASS | Only URA ERRORs are pre-existing `DB write worker not running` boot-transition transients (last 11:13, before the v4.7.32.1 boot); the prune uses its own connection. |

**Note:** the 3 kept renames (`Battery Power`, `Span Left Subpanel Power`,
`Span Left Unknown Power`) are real-circuit baselines orphaned by renames — they
relearn under current names, or could be remapped later. Out of scope for the
auto-prune (which only touches "Unmapped Tab").

### Part A (heat_cool) — TRIP-WIRE
The heat_cool mode-correction (override revert + AC-reset restore) is exercised
only when a reset/revert actually fires (a stuck-AC or manual override) — observed
opportunistically, not a scheduled watch (no-soak). Mechanism proven by 12 in-suite
tests + Tier 2-DB review; the reset NM alert now reads "restoring heat_cool".
