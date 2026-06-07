# Code Review — CM Option-Writeback Reload Suppression (Tier 2-DB)

**Branch:** `feature/cm-reload-suppression` (off `develop`)
**Pre-review baseline tag:** `pre-review-cm-reload-suppression` (build head `aff5a43`)
**Fix-up commit:** `f5ce136`
**Tier:** Tier 2-DB (operator-elevated) — three framing-disjoint staff-engineer reviews + live validation pending.
**Review date:** 2026-06-06

## Why Tier 2-DB

Operator-elevated. The CM update-listener reload blast radius spans ALL coordinators
(presence / HVAC / energy / safety / diagnostics / house_state / signals) and re-creates
every CM entity. Operator bar: "must be robust, no bugs in this very basic high-traffic
system." Three reviews were dispatched with disjoint framings so blind spots could not
overlap:

- **Review A** — data correctness + cross-field invariants + config-flow UX
- **Review B** — async correctness + HA lifecycle + reload/race + listener-as-apply-point
- **Review C** — new surfaces + restart/seed round-trip + test-fixture authority + translations lockstep + plan-completion accounting

## Outcome

**Zero CRITICAL. Three HIGH, all fixed.** Strong cross-reviewer convergence (B-HIGH-2 and
C3 both flagged snapshot-ownership; B-MED-1 and B-HIGH-2 both flagged the unload/reload
snapshot race). All HIGH + the worthwhile MEDIUM/LOW were fixed in `f5ce136` per the
fix-LOWs-in-cycle doctrine. One LOW deferred as a genuine non-issue.

## Findings

| ID | Sev | Bug class | Summary | Disposition |
|---|---|---|---|---|
| A-HIGH-1 | HIGH | Config snapshot staleness (#14 variant) | Single try/except wrapped all four key-apply blocks; one bad value silently dropped its three siblings while the snapshot still advanced | **FIXED** — per-key try/except; `_apply_in_place` returns the cleanly-applied set |
| B-HIGH-1 | HIGH | Cross-field invariant on alt write path (#11 borderline) | `_apply_in_place` blindly trusted the v4.7.25 A-HIGH-1 clamp; an out-of-band write (external `async_update_entry`, future service/YAML) could push `constrained > normal` into live HVAC attrs | **FIXED** — defensive re-clamp after the per-key writes |
| B-HIGH-2 | HIGH | Lifecycle ordering (#46 family) | Reload fall-through did not reseed the snapshot; a second in-flight write during the reload could diff against a popped/stale baseline → "looks all new" | **FIXED** — explicit snapshot reseed to post-write options before scheduling the untracked reload |
| C3 | MED | Hidden coupling / contract drift | Snapshot write lived in the listener, not the helper; a future caller (Part 2) could forget it | **FIXED** — listener owns the snapshot MERGE based on the applied-set return; failed keys keep old value to re-diff |
| A-MED-2 | MED | UX correctness | Combined cover+vacancy error gated on `len(error_keys) >= 2` — brittle if a future third validator is added | **FIXED** — fires only when BOTH specific keys present |
| B-MED-1 | MED | Setup/unload ordering (#46) | Snapshot pop ran AFTER `async_unload_platforms`, exposing a teardown-window race | **FIXED** — pop moved before the platform unload await |
| B-MED-2 | MED | Over-narrow exception (#21) | `_apply_in_place` catch missed `AttributeError` (torn-down coordinator) | **FIXED** — widened each per-key catch to `(AttributeError, KeyError, ValueError, TypeError)` |
| A-MED-1 | MED | Observability | Silent no-op when HVAC coordinator is None (mid-reload) | **FIXED** — single INFO log; DPM dwell excluded (energy.py re-reads each tick) |
| C1 | MED | Plan-completion accounting | Plan named 3 D1 snapshot-lifecycle tests; only the seed one shipped | **FIXED** — added cleared-on-unload + reseeded-after-reload tests |
| C2 | MED | Translation drift | Lockstep test only checked key presence + substring | **FIXED** — byte-equal assertion for the combined key + both per-violation keys |
| A-LOW-2 / B-MED-4 / C4 | LOW | Comment clarity | Seed comment had a mangled parenthetical | **FIXED** — reworded |
| B-LOW-3 | LOW | Observability | CM mixed-key fall-through logged the same generic message as ROOM/ZONE | **FIXED** — CM-specific INFO with sorted changed_keys |
| A-LOW-1 | LOW | Startup race (#5) | Snapshot stays stale if `async_setup_entry` raises mid-reload | **DEFERRED** — non-issue: setup-failed state is already broken; HA retries setup; reload-path reseed + unload-pop cover the realistic paths |

### Positive verifications (recorded for audit trail; no action)

- **C5** — `OPTIONS_RELOAD_SUPPRESS_KEYS` members resolve to the SAME `CONF_*` constants used by the Number setters, the CM constructor, and the DPM re-read. No string-literal drift, no aliasing error.
- **C6** — `hass.data[DOMAIN]["cm_last_applied_options"]` does not collide with any of the ~30 existing `hass.data[DOMAIN]` sub-keys.
- **C7** — DPM-dwell restart/seed round-trip intact: `DynamicPresetDwellMinutesNumber` no longer inherits `RestoreEntity`, no `async_added_to_hass` restore branch, seeds from `{**entry.data, **entry.options}`; persistence via `async_update_entry`.
- **Bug Class #34** — the new `from .domain_coordinators.{hvac,energy}_const import` statements are module-level (col 0), unconditional — not function-local; no UnboundLocalError risk.
- **B-CRIT-1** — the fall-through reload remains an UNTRACKED `hass.async_create_task(... async_reload(...))`, NOT `entry.async_create_background_task` (would be cancelled mid-reload during unload). Preserved by the fix-up.
- **ROOM / ZONE_MANAGER** behavior byte-identical — the entry-type guard gates the suppress path to `ENTRY_TYPE_COORDINATOR_MANAGER` only.

## Summary statistics

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 3 | 3 | 0 |
| MEDIUM | 6 | 6 | 0 |
| LOW | 3 | 2 | 1 |
| **Total** | **12** | **11** | **1** |

## Bug class frequency

| Bug class | Count |
|---|---|
| Lifecycle / setup-unload ordering (#46 family) | 3 |
| Config snapshot staleness (#14 variant) | 1 |
| Cross-field invariant on alt write path (#11 borderline) | 1 |
| Over-narrow exception handling (#21) | 1 |
| Observability / test-coverage gap | 4 |
| UX correctness | 1 |
| Documentation clarity | 1 |

## QUALITY_CONTEXT.md recommendation

No NEW bug class required. The findings are instances of existing classes (#46 lifecycle
ordering, #14 snapshot staleness, #21 over-narrow exception, #11 cross-field invariant).
The "listener-as-single-apply-point must own its own snapshot consistency" lesson (C3) is
worth a one-line note under the existing mirror-pattern guidance rather than a new class.

## Fix-up verification

- Pre-deploy zero-bugs gate: no conflict markers; `py_compile` clean on all changed `.py`;
  `strings.json` + `translations/en.json` parse as JSON.
- Cycle tests: **31 passed** (was 26; +5 from the fix-up).
- Suite baseline-diff: **5105 passed** (was 5100), 62 failed + 14 collection errors — all
  pre-existing environmental (`ModuleNotFound: homeassistant` / missing DB fixtures); zero
  new failures attributable to the cycle or fix-up.
- Fix-up touched only `__init__.py`, `config_flow.py`, and the cycle test file
  (3 files, +326 / -51). No JSON edits were required (the combined key shipped in the
  original build; C2 was a test-assertion tightening only).

## Remaining steps

1. Assign version at deploy time; write `docs/readmes/README_v<version>.md` before deploy.
2. Deploy via `./scripts/deploy.sh`.
3. Live validation (Review D) post-restart; record observed results back into the README.
