# Tier 2-DB Review — Part 2 EC/HC Options-Writeback Retrofit

**Cycle:** Part 2 (sequel to v4.7.26 CM reload-suppression / Cycle 1)
**Scope:** Drop RestoreEntity from the EC (energy-coordinator) Number
family, the Routine Number base class, and the `_HVACTunableNumber`
factory; route their persistence through `entry.options` as sole source
of truth; extend the CM reload-suppression allowlist
(`OPTIONS_RELOAD_SUPPRESS_KEYS`) + `_apply_in_place` dispatch from 5 keys
(Cycle 1) to 37 keys.
**Tier:** Operator-elevated Tier 2-DB (trust-hierarchy ripple — a single
options-writeback refactor touches EC ↔ HVAC ↔ DPM ↔ Routine consumers;
small surgical errors risk regressions across coordinators).
**Build commit (pre-review baseline):** `3768e61` (tag
`pre-review-part2-ec-hc`).
**Fix-up commit:** `f81c730`.

Three parallel framing-disjoint reviews were run per the Tier 2-DB
protocol. Reviews A and C ended mid-investigation without emitting a
structured report; their findings were reconstructed from transcript and
their open threads closed by direct source verification (recorded below).

---

## Review A — Data integrity + DB architecture preservation

**Frame:** existing rows preserved, no schema regression, write queue
unchanged, existing readers unaffected, options round-trip integrity.

| ID | Sev | Finding | Bug class | Status |
|----|-----|---------|-----------|--------|
| A-LOW-1 | LOW | `_NO_LIVE_ATTR_KEYS` comment understated *why* the routine/Bayesian keys are safe with no live-attr push (lumped four sub-families into one sentence). | Documentation drift | FIXED (f81c730) — comment now documents per-family consumer + sole-write-path reasoning. |

**Open thread closed during review:** whether the routine-regime keys
(`routine_regime_baseline_window_days` / `_recent_window_days`) being in
`_NO_LIVE_ATTR_KEYS` is *functionally* correct given their consumer.
Verified: `regime_detector._window_days` (regime_detector.py:104-133)
reads live HA entity-state with a hardcoded 56/14 fallback (NOT
`cm_opts.get(...)`). The Number setter calls `async_write_ha_state()`, so
the entity-state read sees fresh values after an in-place apply without a
live-attr push. **Functionally correct.** No DB schema touched this
cycle (options-only persistence); no readers/writers/indexes affected.

**Verdict:** No data-integrity defects. 0 CRIT / 0 HIGH / 0 MED / 1 LOW (fixed).

---

## Review B — Migration correctness + signal-chain integrity

**Frame:** every migrated call site produces equivalent persistence AND
fires downstream signals AND no double-emit; end-to-end trace per
migrated key; field-by-field shape vs pre-migration.

| ID | Sev | Finding | Bug class | Status |
|----|-----|---------|-----------|--------|
| B-MED-1 | MED | `_apply_in_place` called `hvac.egress_manager.set_threshold_min(...)` / `set_resume_delay_min(...)` without None-guarding the `egress_manager` @property (hvac.py:295, backed by `self._egress_manager` which is None mid-teardown). AttributeError risk in a teardown race. | Teardown-race None deref | FIXED (f81c730) — None-guard mirrors the HVAC-tunable loop's `if sub is None` guard; logs INFO + skips, value picked up next setup. |
| B-MED-2 | MED | `_hvac_tunable_number_factory.async_added_to_hass` deferred-retry path registered the same unsub callable on both the dispatcher and `async_on_remove`; both could fire → second unsub raises in HA. | Double-unsub | FIXED (f81c730) — one-shot `_safe_unsub` guard (`unsubbed` flag), mirrors EC sibling v4.7.6 B-M7 pattern. |
| B-LOW-1 | LOW | `_OFFPEAK_DRAIN_QUALITY` conf→quality map rebuilt per-call inside the offpeak loop. | Micro-inefficiency | DEFERRED (cold path, ≤4 keys; not worth the module-level churn). |
| B-LOW-2 | LOW | factory `_find_cm_entry` is O(N) over config entries per push. | Micro-inefficiency | DEFERRED (N is tiny; called only on Number add/set). |
| B-LOW-3 | LOW | `bayesian_cell_staleness_days` used a bare-string CONF in `__init__.py` + `number.py` (no shared Final). | Magic-string duplication | FIXED (f81c730) — promoted to `CONF_BAYESIAN_CELL_STALENESS_DAYS` Final in const.py; string value byte-identical preserved. |

**Verified safe during review:** `timedelta` / cache-invalidation paths
unchanged; `SIGNAL_HVAC_ENTITIES_UPDATE` still fired by the factory
retry; per-key try/except isolation preserved (one failed key doesn't
abort the rest, and a failed key keeps its OLD snapshot value to re-diff
next time); B-CRIT-1 from Cycle 1 (untracked `async_create_task` for the
full-reload fallback) preserved unchanged.

**Verdict:** 0 CRIT / 0 HIGH / 2 MED (both fixed) / 3 LOW (1 fixed, 2 deferred).

---

## Review C — New surfaces + test-fixture authority

**Frame:** new Number knobs round-trip through options flow + restart;
test fixtures extract schema from production source (never hand-copy);
tests drive production code paths, not their own writes.

| ID | Sev | Finding | Bug class | Status |
|----|-----|---------|-----------|--------|
| C-LOW-1 | LOW | `regime_detector._window_days` docstring still cited the retired URA Mirror Pattern / RestoreEntity doctrine, contradicting the new options-as-sole-source model. | Documentation drift | FIXED (f81c730) — docstring rewritten to state entry.options is now sole source; live-entity-state read is correct under either backing store; fallback order documented. |

**Open thread closed during review:** `_apply_in_place` dispatch coverage
vs the 37-key allowlist. Verified 1:1, no double-handling: 4 v4.7.26 HVAC
branches + 7 `_NO_LIVE_ATTR_KEYS` + 4 offpeak + 5 EC setters + 14 HVAC
tunable + 2 egress + 1 fan = 37. Asserted in production by
`test_apply_in_place_dispatch_coverage` (derives coverage from the live
dispatch tables, not a hand-listed copy).

**Test-fixture authority:** both cycle test files exec an AST-extracted
slice of `__init__.py` (dispatch tables + helpers) so they drive the REAL
production structures. The fix-up's B-LOW-3 change (promoting the Bayesian
constant from a module-local literal to an import) moved it OUTSIDE the
AST slice; both harnesses' `ns` stand-in dicts were updated to model it as
an imported constant (consistent with how routine/egress/fan constants
are already handled) — a faithful reflection of the production refactor,
not a weakening of assertions.

**Verdict:** 0 CRIT / 0 HIGH / 0 MED / 1 LOW (fixed).

---

## Summary statistics

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 0 | 0 | 0 |
| MEDIUM | 2 | 2 | 0 |
| LOW | 5 | 3 | 2 |
| **Total** | **7** | **5** | **2** |

### Bug-class frequency

| Bug class | Count |
|-----------|-------|
| Documentation drift | 2 (A-LOW-1, C-LOW-1) |
| Teardown-race None deref | 1 (B-MED-1) |
| Double-unsub | 1 (B-MED-2) |
| Magic-string duplication | 1 (B-LOW-3) |
| Micro-inefficiency | 2 (B-LOW-1, B-LOW-2) |

### Deferred (within ~6-entry cap per "Fix LOWs In-Cycle")

- **B-LOW-1** — `_OFFPEAK_DRAIN_QUALITY` per-call rebuild. Cold path, ≤4 keys.
- **B-LOW-2** — factory `_find_cm_entry` O(N) scan. Tiny N, infrequent.

---

## Pre-deploy gate

- Conflict markers: none.
- `py_compile` on all 4 changed source files: OK.
- Cycle tests (`test_part2_ec_hc_writeback.py` + `test_cm_reload_suppression.py`): **98 passed**.
- Suite baseline-diff vs `pre-review-part2-ec-hc`: **no new failures.**
  61 pre-existing failures + 14 errors are HA-runtime `ModuleNotFound` /
  metric-baseline-integration / config-flow env issues, unchanged with or
  without this cycle's changes. No Part 2 test among them.

## QUALITY_CONTEXT.md recommendation

No new bug class warranted. "Teardown-race None deref" and "Double-unsub"
are already covered by existing classes (None-handling; Untracked
Background Tasks / listener-cleanup family). The recurring theme this
cycle was **documentation drift after a persistence-model flip** —
worth a one-line note in the options-as-sole-source migration playbook:
*when dropping RestoreEntity, grep consumers' docstrings for stale
RestoreEntity/Mirror-Pattern references.*
