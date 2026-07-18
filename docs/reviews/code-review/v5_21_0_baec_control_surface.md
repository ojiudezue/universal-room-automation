# v5.21.0 BAEC Control Surface — Tier 2-DB Review Record

**Cycle:** BAEC config-flow + display renames + device slim-down + shadow eval + D2 knob promotion.
Branch `build/baec-config-flow`: ef2cbfa0 (build, tagged pre-review-v5.21.0) + 955e89b4 (consolidated fix-up).
**Protocol:** 3 framing-disjoint reviews (A round-trip / B lifecycle-retirement / C mutation execution) + focused re-review of the substantial fix-up + orchestrator mutation verification.
**Final verdict:** SHIP.

## Findings ledger

| ID | Sev | Finding (bug class) | Found by | Resolution |
|---|---|---|---|---|
| B-HIGH-1 | HIGH | Options-flow enable toggle persisted but never applied (`_NO_LIVE_ATTR_KEYS`) — flow/switch/behavior three-way desync until restart | B | FIXED 955e89b4: live-apply via `_EC_SETTER_DISPATCH` + `set_dp_enabled` + `SIGNAL_ENERGY_ENTITIES_UPDATE` push to switch (real signal, signals.py:22; unsub via async_on_remove) |
| HIGH-C1 | HIGH | INV-BAEC-SHADOW "zero KV write" leg unenforced — injected `_save_evse_state()` call left 319 tests green (write-flood incident shape) | C (mutation D) | FIXED: spy-counter asserts; orchestrator re-ran mutation → 2 tests RED |
| MED-A1 | MED | New config-flow surface had zero direct test coverage (builder deferral rejected) | A | FIXED: test_baec_config_flow_round_trip.py (8 tests incl. flatten, sibling preservation, fresh-install) |
| MED-C2 | MED | Floor-mutation leg only incidentally covered | C (mutation B) | FIXED: `_dp_decision_soc is None` asserts; orchestrator re-ran mutation → RED |
| B-MED-1 | MED | `entity_registry_enabled_default` only affects NEW registrations — live-house slim-down can't happen from code | B (verified vs HA semantics) | Plan/acceptance wording corrected; live slim-down = one-shot MCP registry disable at deploy (reversible) |
| A2 | LOW | Hardcoded house-load dropdown vs source-of-truth tuple | A | FIXED: derived from DP_HOUSE_LOAD_SOURCES |
| B-LOW-1 | LOW | Shadow also ran on switch-ON daytime path (attr churn) | B | FIXED: gated on `not _dp_on` |
| A3 | LOW | Config-flow write → enabled Number displays stale value until restart | A | ACCEPTED (byte-matches peak-buffer precedent) |
| C3 | LOW | Shadow log rate-limit untested | C (mutation E) | ACCEPTED (rung-1 constant, bounded cadence) |
| L1 | LOW | Switch-only toggle never writes options → stale options re-assert at boot. PRE-EXISTING across ALL `_ec_switch_factory` switches (arbitrage, solar-aware, grid-cap…), not introduced here | re-review | ACCEPTED + BACKLOG: unify switch→options writeback or ratify options-as-boot-authority for switches |
| L2/L3 | LOW | Selector seeding style inconsistency; error-re-render loses unsaved section edits (matches sibling behavior) | re-review | ACCEPTED |

**Stats:** 0 CRITICAL · 2 HIGH found/fixed · 3 MED (2 fixed, 1 wording) · 6 LOW (2 fixed, 4 accepted).

## Operator ratifications (2026-07-17)
- BAEC folded INTO `async_step_coordinator_energy` as visible `baec` + collapsed `baec_advanced` sections (inclement/cloud_verification pattern) — standalone `coordinator_baec` menu step built then retired same cycle.
- D2 detection thresholds promoted rung-1 → rung-2 into `cloud_verification`: `energy_soc_divergence_threshold_pp` (0-50, default 10), `energy_soc_divergence_dwell_min` (0-60, default 5), `energy_cloud_lag_alert_s` (0-3600 step 30). Kill semantics (0 = off) preserved at the same branches and documented on the fields. All read sites migrated (energy_battery.py:1163-1316); kill-semantics test drives real `_evaluate_soc_divergence`.
- Cognitive-simplicity renames (display-only): Decision delay · Charging time buffer · Latest charge start · Typical charge needed — Garage A/B · Overnight house load estimate · Battery level disagreement alert · Disagreement confirmation time · Cloud update delay alert.
- Device surface: switch + Latest charge start remain; 4 Numbers + Select → diagnostic + disabled-by-default (new installs) + one-shot MCP registry disable on the live house at deploy.

## Orchestrator verification
Re-ran C's two surviving mutations against the fixed tree: shadow-KV-write → 2 RED; floor-stamp → 2 RED. Restored; 325/3 green; worktree clean.

## Bug-class notes
- Invented-attribute streak (3 cycles) BROKEN: re-review byte-verified seed/read attr parity on the same object, with production-path test proof.
- New QUALITY_CONTEXT candidate: **asserted-but-untested invariant leg** (HIGH-C1) — an invariant stated in the plan needs one enforcement test per leg, else it's Bug Class #53's testing twin.
- L1 pattern (entity-write vs options-boot-authority divergence on factory switches) → backlog sweep candidate.

## Test counts
Scoped filter: 319 (build) → 325 (fix-up), 3 skipped. Guard suites green (cm_reload_suppression, round-trip, cloud-verification flows: 38 + 158). Full suite within pre-existing baseline (36F/14E), no new failures.
