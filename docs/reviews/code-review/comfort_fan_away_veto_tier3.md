# Tier-3 Review Record — Comfort-Fan AWAY Veto (mmWave-corroboration cycle, D3 core)

Branch `feature/comfort-fan-away-veto`; build 5ec5ba169 → fix-up 4c1572ed2 → orchestrator fixes 0ce0e987c.
Plan: `docs/planning/PLANNING_mmwave_corroboration_tier3.md` (+ Amendments 1-2). Four framing-disjoint reviews per Tier-3 protocol.

## Findings

| ID | Sev | Finding | Bug class | Status |
|---|---|---|---|---|
| C-CRIT-1 | CRITICAL | All 3 per-site tests grep-only; mutation drills proved every site neuterable green | #62 test reimpl / #53 unanchored | FIXED (17 behavioral tests; drills red per site) |
| D-HIGH-1 | HIGH | 4th actuation site: `restore_after_recheck` re-issues fan ON unvetoed (house→AWAY inside recheck window) | #53 one-missed-site | FIXED (guard + mutation-anchored test) |
| B-H1 | HIGH | No boot-settle gate; boot-AWAY window could suppress legit fans post-restart | boot posture | FIXED (fail-open during settle, mirrors fan-recheck) |
| B-H2 | HIGH | Fan-already-ON when house→AWAY not covered by ON-edge veto (the Study A incident shape) | scope | DEFERRED-DOCUMENTED (Known residuals; fan-recheck covers organically post-bucket-reclassification; OFF-edge would fight manual remote turn-ons) |
| C-HIGH-1 | HIGH | Humidity-guard test vacuous if handler renamed | test authority | FIXED (hard assert) |
| A-M1/B-M1 | MED | Empty merged config fails CLOSED (re-enables operator-disabled veto); O(N) entry scan before cheap gates | fail-direction | FIXED (fail-open + is_veto_relevant early-out) |
| D-MED-1 | MED | `""` house-state fail-open on AWAY cold boot | boot posture | ACCEPTED-RISK (adjudicated: suppressing legit post-restart fans worse; comment + D7 trip-wire) |
| D-MED-2 | MED | mmWave hybrids misfiled in motion_sensors satisfy "recent motion", defeating the veto | #7 data source | FIXED (MMWAVE_NAME_PATTERN exclusion) |
| C-MED-1/2 | MED | Knob-off unproven per site; ON-edge scoping untested | coverage | FIXED (behavioral variants) |
| A-L1/B-L2 | LOW | Recent-transition counted non-OFF states; boot-transient bias | | FIXED |
| A-L3 | LOW | Silent nested excepts | observability | FIXED (warnings) |
| B-L1 | LOW | Function-local imports | style | FIXED (module top) |
| D-LOW-1 | LOW | AI-rule executor can fan.turn_on unvetoed | trust domain | DEFERRED (parked list) |
| D-LOW-2 | LOW | Frozen tracker defeats BLE leg | Ezinne-class | FIXED (tracking_status filter) |
| D-LOW-3 | LOW | Camera-map room-name string fragility | | FIXED (normalize) |
| ORCH-1 | HIGH (test-infra) | Harness `homeassistant.const` = bare MagicMock → ALL state-string comparisons under test silently wrong; t4 asserted the exception path | #62-adjacent harness gap | FIXED in orchestrator pass (pinned real strings) |
| ORCH-2 | MED (test-infra) | Naive/aware clock mismatch fixture vs dt_util | wall-clock-coupled tests | FIXED (clock-derived fixtures) |

## Statistics
Found: 1 CRIT, 5 HIGH (incl. ORCH-1), 6 MED, 6 LOW. Fixed: all except B-H2 + D-MED-1 + D-LOW-1 (documented deferrals/adjudications).

## Mutation verification (orchestrator, personal)
- automation.py room-tier: `if False and` → `test_veto_fires_house_away_blocks_turn_on` FAIL → restored.
- hvac_fans restore site (D-HIGH-1 guard): `if False and` → `test_restore_vetoed_when_house_now_away` FAIL → restored.
- Builder drills (all 4 sites) independently recorded red in fix-up report.
- Re-grep: 4 ON-actuation sites all route through `should_veto_comfort_fan`; only OFF-writes (hvac_fans:171, :686) bypass, by design.

## Suite
38/38 veto tests both file orders; full suite 7777 passed / 32 failed — identical to pre-cycle baseline (zero drift).

## QUALITY_CONTEXT candidates
- **Harness-constant authority**: a stub const module of bare MagicMocks makes every equality against imported constants silently false — pin real values for constants production compares against. (ORCH-1; likely affects other suites' latent coverage.)
