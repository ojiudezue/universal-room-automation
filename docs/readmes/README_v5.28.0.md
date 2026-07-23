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

## Live Validation — Validated 2026-07-23 (restart, boot 07:54 CDT)

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Clean boot | PASS | Zero URA ERROR lines post-boot; house state `home_day` by 07:56; EC `self_consumption` by 07:58 (SOC 39, all three resolver tiers agreeing at 0.0pp — wired-Envoy repoint delivering fresh cloud at 28.5s age). |
| L2 | Guard telemetry | PASS | 2 `dp_eval` rows in decision_log within minutes of boot (~1/tick as designed); prune registered on nightly cadence (in-suite anchored). |
| L3 | Guard organic (Envoy blip) | PENDING-ORGANIC | ~2-3 chances/day per probe. §2.5a watch note stands: flapping-on-healthy = freshness-gate suspect → backout sequence, never revert. |
| L4 | D4 witness units | PASS-with-correction | Power variants carry W (`mainw_vue_balance_power_minute_average` unit=W ✓, transiently unavailable — Emporia blip). NOTE: the `*_energy_today` variants are kWh ENERGY sensors — NOT valid witness candidates; when enabling D4, wire a *power* sensor. Config ships unset (feature dormant). |
| L5 | LKG fields post-boot | PASS | `soc_resolution` carries lkg_soc=39/lkg_age=0 live; restart round-trip proven in-suite. |
| L6 | C-2 surfaces | PASS | `nm_routing_audit_recent: []` present on the diagnostics sensor (empty = observe mode, correct); extras selector + routing step in-suite anchored; UI walkthrough at operator's leisure. |
| L7 | Fill-priority daylight hold | **PASS — ORGANIC, FIRST QUALIFYING MORNING** | 07:59:55 (minutes after boot, sun up, SOC 39<80, off_peak): all four chargers/plugs paused — `paused_by_fill_priority: [garage_a, garage_b, 2×smartplug]`, `pause_reason_human: "holding for battery fill (target 80%, solar healthy)"`. The exact behavior the 2026-07-22 trace found missing, restored and observed live. |
| L8 | Toggle symmetry no-reload | PENDING-OPERATOR | Toggle any room fan/humidity switch; sibling last_changed invariant. |

Deploy-time manual follow-ups still owed: `scripts/rename_nm_entities.py`
(HA STOPPED required — schedule at will) and the NM audit card via MCP
once routing goes live (card renders empty rows until notifications flow).
