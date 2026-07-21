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

## Live Validation (prospective — write back observed results post-restart)

| # | Criterion | How to check |
|---|---|---|
| L1 | NM quieting: `sensor.ura_notification_manager` `notifications_today ≤ 6` over 24h; optimizer rows only in digest window | live sensor + `notification_log` |
| L2 | A7 preserved signals intact: AC Reset FAILED / Envoy Offline emits gate on real conditions (live-only; cannot be proven in-suite) | recorder / notification_log over subsequent days |
| L3 | A4 outdoor exclusion + quieted humidity thresholds produce no outdoor-humidity NM rows | recorder query post-deploy |
| L4 | DP-yield: next high-solar day with battery ≥95% while an EVSE carries deferred DP pause (`pause_reason_human` = "drain-precedence transition (paused)", `_dp_carrier.state = HOLD_ONLY`) → transitions to "excess solar (charging)" within one decision cycle; `switch.turn_on` in HA logs; EV draws PV | entity attributes + timestamps, recorded here per write-back rule |
| L5 | No URA ERROR logs attributable to either cycle post-restart | log scan |
| L6 | House state sensor available; all coordinators emitting post-restart | `sensor.ura_presence_coordinator_presence_house_state` |

L4 is organic (requires a real high-solar day + deferred DP pause); if not
exercised at validation time, mark pending-organic with the trigger
condition, per the v5.5.0 precedent.
