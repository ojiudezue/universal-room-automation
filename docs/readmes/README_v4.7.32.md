# v4.7.32 — heat_cool mode-correction + reversible SPAN baseline prune

**Tier:** 2-DB (3 framing-disjoint reviews — see
`docs/reviews/code-review/v4.7.32_heat_cool_and_span_prune.md`). 4 review fixes
applied in-cycle. **Baseline tag:** `pre-review-v4.7.32`.

## What changed

### Part A — Always return zones to heat_cool (hvac_override.py)
The operator runs zones in ranges/presets (heat_cool). URA's `OverrideArrester`
absorbed the legacy "Arrester v10" severity/compromise logic but only re-asserted
heat_cool when the mode was exactly `off` — so a zone left in a single mode
(cool/heat) by a manual override or AC nudge/reset stayed there ("nudges sometimes
don't reset the mode"). Now:
- new `_supports_heat_cool()` capability probe;
- override revert forces heat_cool whenever `hvac_mode != heat_cool` (guarded);
- AC-reset restore targets heat_cool (guarded), and its verify-retry now confirms
  the zone reached heat_cool (not merely "not off"), alerting with the actual mode
  if it didn't.
Heat-only/cool-only thermostats (no heat_cool in `hvac_modes`) keep their mode.

### Part B — Prune orphaned SPAN "Unmapped Tab" baselines (energy.py)
SPAN exposes "Unmapped Tab N" sensors for unnamed tabs; its Circuit Name Sync
renames the entity the instant a tab is named, so a real circuit is never named
"Unmapped Tab N". URA had learned `circuit_power` anomaly baselines under the old
"Unmapped Tab N" names; after renaming, 18 were orphaned (boot WARN only). On boot
URA now **backs up** each orphaned "Unmapped Tab%" baseline to
`metric_baselines_pruned_backup`, then deletes it (delete-and-relearn). Real
(non-"Unmapped Tab") renames are still kept + warned. Scoped strictly to
`coordinator_id='energy' AND metric_name='circuit_power'`.

## Reversibility (operator-requested)
- **In-DB:** restore with
  `INSERT OR IGNORE INTO metric_baselines (coordinator_id,metric_name,scope,mean,variance,sample_count,last_updated) SELECT … FROM metric_baselines_pruned_backup;`
- **Pre-deploy DB snapshot:** the URA DB file is copied before this deploy (the prune
  first runs on this restart).

## Acceptance criteria
### In-suite (proven pre-deploy)
- `test_v4732_heat_cool_and_span_prune.py` (12) — `_supports_heat_cool` behavioral +
  structural guards (revert `!= heat_cool`; restore targets heat_cool; prune only
  "Unmapped Tab"; backup-before-delete; scoped DELETE; commit).
- Suite baseline-diff vs `pre-review-v4.7.32` = zero new failures.

### Live Validation (prospective — write back post-restart)
- **Live:** boot log shows `SPAN: pruned N orphaned 'Unmapped Tab' circuit
  baselines (backed up …)`; next boot shows no such line (idempotent); the
  "N circuit baselines could not be matched" WARN drops to only real renames (≈0).
- **Live:** `metric_baselines_pruned_backup` table exists with the pruned rows.
- **Live:** no fresh URA errors at boot.
- **Live (opportunistic, ~trip-wire):** on the next AC reset/override revert, the
  zone ends in `heat_cool`; the reset NM alert reads "restoring heat_cool".

## Deferred
- A-F5: `_suppressed_entities` single-pop amplification (pre-existing) → follow-up
  memo (TTL/counter-based suppression).
