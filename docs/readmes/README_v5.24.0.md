# URA v5.24.0 — NM Cycle A Quieting + DP-Sticky Yields To Excess Solar

Combined feature deploy from develop. Two independently reviewed cycles:

## Cycle 1: NM Cycle A — Notification quieting (Tier 2, two-review)

Per `docs/planning/PLANNING_nm_overhaul_2026_07.md` Cycle A. NM remains in
de-facto observe mode (`CONF_NM_ENABLED=true` + blank per-person targets),
so deploy risk is notification-shape only.

- **A1–A6 quieting:** humidity thresholds 78/85/92 + outdoor exclusion via
  zone flag; CO2/TVOC gating; breaker NM demote; optimizer HIGH digest-defer;
  lock dedup; cloud-lag `last_reported`.
- **A7 preserved signals:** AC Reset FAILED, Envoy Offline, write-verify
  CRITICAL, water-leak, A5 blocklist — regex tripwires in
  `test_nm_cycle_a_preserved_signals.py` + behavioral emit-path legs in
  `test_safety_coordinator.py::TestNMCycleAA7Behavioral`.
- **Fix-up verified:** two-review CRIT/HIGH/MED findings fixed (badd0f98);
  tautological H2 swing fixture repaired (seed at 30-min window boundary +
  fixture self-check assert, 50524c78); all three mutation anchors
  (outdoor override, swing room-type gate, swing-fired set separation) each
  fail exactly one specific test.

## Cycle 2: DP-sticky yields to excess solar (Tier 3, operator go 2026-07-20)

Per `docs/planning/PLANNING_dp_sticky_yields_to_excess_solar.md`. Charter:
"High solar energy days should be squeezed for every joule."

- **D1:** yield predicate + atomic handoff in
  `energy_pool.py::determine_excess_solar_actions` — a HOLD_ONLY DP-carrier
  EVSE in `_paused_by_dp` yields to a live excess-solar claim (SOC ≥ 95,
  forecast ≥ 5.0 kWh) and moves atomically to `_excess_solar_active`.
- **D2:** restart-mid-yield resilience — yielded EVSE stays on, stays out of
  `_paused_by_dp`; restore-reconcile persists the mutation via guarded
  `_save_evse_state` (fix-up 2, d94deb25).
- **Review record:** four framing-disjoint reviews (A/B/C/D) + D re-pass +
  EC §2.4b reconciliation audit + orchestrator per-site mutation
  verification, all cleared. Tier-3 operator checkpoint passed.

## Docs riding this deploy
- EC manual §2.4b: 12-row enforced EVSE precedence table + two-tier BAEC
  rule + audit conclusions of record (a0d48a95).

## Test evidence
- 7210 passed; failure set byte-identical to pre-merge develop baseline
  (50 pre-existing env-drift failures/errors; zero introduced by either
  cycle). DP-yield adds `test_dp_yields_to_excess_solar.py` (1058 lines,
  all green).

## Live Validation — Validated 2026-07-20 (restart 19:34 CDT)

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | NM quieting: notifications_today ≤ 6 over 24h; optimizer rows only in digest window | PASS | Validated 2026-07-21 ~17:45 CDT: notification_log = 0 rows in trailing 26h (live DB query; target ≤6) — zero outdoor-humidity rows, zero optimizer rows outside digest. notifications_today sensor = 0. Zero URA ERROR lines in log. |
| L2 | A7 preserved signals gate on real conditions | PENDING-ORGANIC | Live-only by design (plan §A7); tripwire + behavioral tests green in-suite. Watch notification_log on next real HVAC/Envoy event. |
| L3 | No outdoor-humidity NM rows post-deploy | PASS | Same 26h DB query: zero rows of any kind, hence zero outdoor-humidity rows. |
| L4 | DP-yield: HOLD_ONLY DP-carrier EVSE yields to excess-solar claim within one cycle | PENDING-ORGANIC | Trigger: high-solar day, battery ≥95%, EVSE with `pause_reason_human` = "drain-precedence transition (paused)". At validation time SOC=88, no DP carrier active (`evse_paused_by_arbitrage=[]`). Record observation window here when it fires. |
| L5 | No URA ERROR logs post-restart | PASS | `error_log` level=ERROR search=universal_room_automation → 0 lines at T+4min and T+9min. Boot-transient WARNINGs only (sensor-unavailable holds, camera census, Envoy warm-up blind de-escalation — all known classes). |
| L6 | House state + coordinators live | PASS | `sensor.ura_presence_coordinator_presence_house_state`: away (boot) → arriving → `home_evening` conf 0.85 by 19:37:45. EC resolved `self_consumption` at 19:41:15 (SOC 88 via envoy primary, arbitrage phase discharge, write-verify surface healthy, `inclement_reserve_floor=10`). Installed manifest confirmed `v5.24.0` on live mount. |

Boot-only transients seen and dismissed: Envoy unavailable at URA start →
blind de-escalation ENGAGED (v5.17.5 behavior, correct), released once
Envoy resolved (~19:38). Pre-existing, NOT this deploy:
`pending_write_stuck_state.reserve_soc` cloud-oracle divergence (oracle 61
vs commanded 10) began 21:02 UTC pre-restart — known Enphase-side
reserve-reporting divergence.

L1/L3 (24h) and L2/L4 (organic) remain open per the v5.5.0
pending-organic precedent; cycle closes on L5/L6 with those tracked.
