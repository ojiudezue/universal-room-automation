# URA v5.28.0 — Blind-Window EVSE Guard + NM C-2 + Fill-Priority Restoration + Toggle Symmetry

Combined deploy of four fully-reviewed cycles (operator go 2026-07-23).

## 1. EC blind-window EVSE guard (Tier 3)
From the 2026-07-21 incident (84-min Envoy outage; battery fed a 5 kW car).
INV-BW1: while SOC is unresolved AND the reserve write unverifiable, no EVSE
starts via any of the 12 enumerated emission sites; mid-charge cars ride on
the LKG physics envelope; two sanctioned, decision_log-audited liveness
escapes (force-charge; must-start-by/max-defer via the liveness helper with
per-epoch ride authority). Plus: dp_eval forensic rows (~12/hr, 90d prune),
D4 Emporia-mains backup export witness (unit-normalized), persisted LKG +
decay envelope (the reusable primitive), debounce per the outage probe.
Review: `v5.28.0_ec_blind_window_guard.md` — 23 findings across 6 passes,
all closed; 15+ mutation kills. **Emergency backout: EC manual §2.5a**
(MAX_AGE_S=0 = fire axe; partial outages knowingly exposed at 0).

## 2. NM Cycle C-2 (Tier 3)
Routing-matrix options UI (CM step, clobber-safe, default-drop);
`CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS` additive-only tunable (promote
overheat/high_co2 from UI; demotion impossible by construction; 8 consumer
sites union-anchored behaviorally); routing-audit ring on the diagnostics
sensor for the dashboard card. Review: `v5.29.0_nm_cycle_c2.md` (record
retains its pre-merge tag name; SHIPPED IN v5.28.0). Deploy-time manual
follow-ups: `scripts/rename_nm_entities.py` (REQUIRES HA STOPPED — operator
schedules separately); audit card via MCP (docs/dashboard-prototypes/).

## 3. Fill-priority daylight restoration (Tier 2-DB)
Mornings are battery-first again: off_peak∩daylight re-applies the 80% hold
(sun-anchored via the attain `_daylight_bounds` primitive; v5.5.5 night
release + cross-midnight behavior preserved; L1/L2 mirror completed).
Restores the pre-v5.5.5 ratified intent the TOU-as-night proxy surrendered.

## 4. Room fan/humidity toggle symmetry (Tier 2)
The existing room switches no longer trigger a full ~90-entity room reload
per toggle (room suppress-set membership); boot precedence corrected
(options wins when present).

## Test evidence
Combined tree: 7486 passed; 36 failed + 14 errors = exact pre-existing
env-drift baseline. Cross-cycle compositions verified at merge: guard ×
fill-priority (142/142), suppress-set count reconciled (82+1+1=83).

## Live Validation (prospective — write back observed results post-restart)

| # | Criterion | How to check |
|---|---|---|
| L1 | Clean boot; house state + EC resolve; zero URA ERRORs | logs + sensors |
| L2 | Guard telemetry: dp_eval rows appear (~12/hr); retention prune registered | decision_log query |
| L3 | ORGANIC (probe: ~2-3 chances/day): next >2-min Envoy blip → guard engages, blind_window_defer rows, no EVSE start in-window; §2.5a watch note applies if it flaps on healthy telemetry | decision_log + logs |
| L4 | `mains_vue_*` unit_of_measurement ∈ {W, kW} allowlist | entity attributes |
| L5 | LKG snapshot survives restart (soc_resolution lkg fields present post-boot) | battery-strategy attrs |
| L6 | C-2: routing options step reachable; extras selector offers env hazards; NM diagnostics sensor carries `nm_routing_audit_recent` | UI + attrs |
| L7 | Fill-priority ORGANIC: next below-80% daylight off_peak morning with a car plugged in → hold until SOC≥80 (tomorrow morning qualifies if SOC<80 at sunrise) | recorder + pause_reason |
| L8 | Toggle symmetry: room fan switch toggle → no room reload (sibling last_changed invariant) | operator-exercised |
