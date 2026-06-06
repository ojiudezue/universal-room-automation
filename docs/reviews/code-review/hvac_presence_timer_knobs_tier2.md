# Code Review — HVAC Presence-Timer Knobs + Options Writeback (Tier 2)

**Cycle:** Expose three hardcoded HVAC presence timers as BOTH device Number
entities AND collapsed config-flow form fields, plus a Reset button.
**Branch:** `feature/hvac-presence-timer-knobs`
**Reviewed commit:** `97bdbe7` (build); fixes landed in `e693008`.
**Tier:** 2 (feature cycle) — two parallel framing-disjoint reviews + live validation.
**No version number** — assigned at deploy time per operator convention.

## Review framings
- **Review A — correctness + edge cases + Bug Class #32 (no-persistence-path) + cross-field validation.**
- **Review B — async correctness + HA lifecycle + Bug Class #46 (async_update_entry off setup path) + CM reload race + restart resilience.**

## Findings

| ID | Sev | Bug class | File:line | Status |
|---|---|---|---|---|
| A-HIGH-1 | HIGH | invariant enforced in one path, missed in another (#34 cousin) | number.py constrained/normal setters | **FIXED** (e693008) |
| B-H1 | HIGH | new candidate: options-save fan-out w/o coalescing during heavyweight reload | number.py setters | **ACCEPTED + DOCUMENTED** (convergent) |
| A-MED-1 | MEDIUM | form UX: `errors["base"]` collision (two-trip fix) | config_flow.py:3983/3997 | **DEFERRED** (see rationale) |
| A-MED-2 | MEDIUM | type-drift hygiene | number.py:328 | **FIXED** (e693008) |
| A-MED-3 | MEDIUM | consistency reminder on A-HIGH-1 (`<=` not `<`) | — | **FIXED** (clamp uses `<=`/`min`) |
| B-M1 | MEDIUM | Bug Class #46 adjacent (reload window doc) | number.py setters | **FIXED** (doc comment) |
| A-LOW-1 | LOW | UI freshness (reset button relies on reload) | button.py | **ACCEPTED** (cosmetic, brief lag) |
| A-LOW-2 | LOW | hygiene — remove `from __future__ import annotations` | number.py:7 / button.py:7 | **REJECTED** (load-bearing) |
| B-L1 | LOW | cosmetic — ButtonDeviceClass.RESTART | button.py | **ACCEPTED** (skip) |

### A-HIGH-1 (FIXED) — energy-saving vacancy delay could exceed normal via Number entity
The config-flow form enforced `grace_constrained <= grace`, but the two Number
entities are independently settable (device card / `number.set_value` /
scripts). Driving constrained above normal inverts the HVAC `energy_constrained`
branch (`hvac.py:1037-1038`): the house would wait *longer* to back off to Away
during an energy-coast/shed regime — the opposite of the knob's intent.
**Fix:** clamp the energy-saving setter to `min(value, normal)`; and when the
normal setter lowers below the persisted energy-saving value, clamp the latter
down in the SAME writeback. Both honor `<=` (equality allowed). Two regression
tests added (`test_constrained_number_clamps_to_normal`,
`test_lowering_normal_clamps_constrained_down`).

### B-H1 (ACCEPTED + DOCUMENTED) — rapid multi-edit → multiple CM reloads
Each Number's `async_update_entry` fires the CM update-listener → one untracked
`async_reload(CM)`. Four quick edits = four reloads (vs the form's single save =
single reload). Both reviewers confirmed the outcome is **convergent**: HA
serializes reloads per-entry via the entry reload lock, and the rebuilt
coordinator re-seeds every attr from `entry.options` on setup. A debounce timer
was considered and **rejected** as over-engineering — it introduces its own
untracked-timer hazard surface for a convergent, edge-case UX cost. The Reset
button already batches all four into one writeback by design. Documented at the
live-attr push sites (B-M1 comment) and here.

### A-MED-1 (DEFERRED) — config-flow `errors["base"]` collision
Cover-temp-hysteresis and vacancy cross-field checks both write `errors["base"]`;
the vacancy check is gated `if not errors`, so a cover failure hides the vacancy
error until the next submit (two-trip fix). **Deferred:** surfacing both
simultaneously requires field-attached errors inside a `section(...)`, whose HA
rendering behavior is unverified (No-Fabrication rule). The single-base-error
pattern is the established convention across all 15 base-error sites in
config_flow.py — this is not a regression introduced by this cycle. Track as a
form-UX backlog item if it ever bites.

### A-LOW-2 (REJECTED) — keep `from __future__ import annotations`
The reviewer suggested removing it as unused. It is **load-bearing**: number.py
and button.py carry pre-existing PEP 604 union annotations
(`unit: str | None` at number.py factory, `category: EntityCategory | None` at
button.py) that raise `TypeError` at import on Python 3.9 (the local test
harness) without the future import. The deploy target is 3.10+, but the test
suite runs 3.9.6. Removing re-breaks behavioral tests that `exec_module` these
files. Matches the convention already in sensor.py / binary_sensor.py.

## Bug-class statistics
- Found: 2 HIGH, 4 MEDIUM, 3 LOW.
- Fixed: 1 HIGH (A-HIGH-1), 2 MEDIUM (A-MED-2, B-M1), A-MED-3 (subsumed by HIGH-1 fix).
- Accepted/Documented: 1 HIGH (B-H1), 2 LOW.
- Deferred: 1 MEDIUM (A-MED-1).
- Rejected: 1 LOW (A-LOW-2).

## Clean verifications (no finding)
- Bug Class #32 closed for all 4 cluster members — live-attr names match
  `hvac.py:221-224`, read each decision cycle.
- Bug Class #46 not regressed — every `async_update_entry` is runtime-user-action-only.
- Restart resilience — CM setup (`__init__.py:2020-2031`) re-seeds all four CONF_*
  keys; Numbers render persisted options on cold boot (no RestoreEntity needed).
- CONF_* key consistency across number/button/config_flow/const (incl. the
  no-`_MINUTES`-suffix `CONF_HVAC_VACANCY_GRACE_CONSTRAINED`).
- Strings/translations in lockstep; error key present.

## Test result
- Cycle tests: 196 passed, 1 skipped (incl. 2 new HIGH-1 regression tests).
- Full suite baseline-diff: 62 failed both pre- and post-change (all pre-existing
  environmental failures needing real `homeassistant`/DB fixtures); passing count
  5034 → 5074. Zero new failures attributable to this cycle.

## Recommendation
Cycle is ready for deploy after operator authorization. Post-deploy: run Live
Validation (Review 3) and write the observed results back into the README.
