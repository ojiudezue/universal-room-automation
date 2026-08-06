# v5.52.0 — Presence Coordinator Observability + Feature Kill Switches

Operator-requested (2026-08-05): audit PC observability, add sensors +
toggles to the PC device surface with the hygiene refined in HC/EC.
Audit of record: `docs/planning/AUDIT_presence_coordinator_observability.md`
(includes operator adjudication: additive-only, plain-English naming,
wake counter stays wake-scoped).

## New device surface (10 entities, PC device)

| Entity | Friendly name | What it tells you |
|---|---|---|
| sensor.ura_presence_census_count | People Home (census) | The people count driving inference, now graphable |
| sensor.ura_presence_wake_blocked_ticks | Mornings Blocked From Waking | "Why is the house still asleep" counter |
| sensor.ura_presence_wake_backstop_fires | Wake Safety Valve Fires | Safety-valve firings (+ NM anomaly, deduped once/day) |
| sensor.ura_presence_arriving_rearm_suppressed | Arrival Re-Alerts Muted (flap guard) | Flap-detector KPI |
| sensor.ura_presence_arriving_rearm_bypassed | Arrival Re-Alerts Skipped (real arrivals) | Interior-evidence bypasses |
| binary_sensor.ura_presence_arriving_rearm_active | Arrival Re-Alert Cooldown Active | Cooldown live state |
| sensor.ura_presence_diagnostics | Presence Diagnostics | Disabled-by-default DIAGNOSTIC copy of veto/consensus/exclusion payloads (house-state attrs untouched) |
| switch.ura_presence_guest_detection_enabled | Guest Detection | Kill both guest paths (A census + B sustained-room); OFF clears Path-B latches |
| switch.ura_presence_arriving_rearm_enabled | Arrival Re-Alerts | Kill re-arm suppression AND arming |
| switch.ura_presence_away_veto_enabled | Away Confirmation Veto | Kill the tracker-away veto; coerces engine inputs AND the sensor-surfaced attr |

All switches: default ON, v5.48.0 hygiene — signal-deferred restore on
new SIGNAL_PRESENCE_COORDINATOR_READY (dispatched in a finally so
switches converge even on partial setup failure), restore-on-"off"-only
(unavailable/unknown never poisons), suppressed_since preserved across
restart on BOTH fast and deferred paths. Observation-mode switch
retrofitted from the racy 5s timer onto the same signal.

## Reviews (Tier 2-DB: three framing-disjoint + orchestrator pass)

- A correctness: 1 HIGH (away-veto stale instance attr → coerced), 3 MED, 5 LOW — fixed.
- B lifecycle/restore: 3 HIGH (deferred suppressed_since loss; no dispatch watchdog; untracked NM task), 4 MED — fixed.
- C surfaces/test-authority: independent mutation battery found 3 silent-pass sites (loose dispatch regex, textual parity tests, unstamped suppressed_since) — all repaired with behavioral tests, re-verified red.
- Orchestrator: re-ran A-HIGH-1 mutation post-fix-up — found the fix UNTESTED (27/27 stayed green); added the anchor, verified red-then-green. (#62 ledger +1.)
- Deferred: C-L4 AggregationEntity 60s room-retry loop on promoted sensors (base-class change; evidence note in audit doc).

Tests: cycle file 27 (from 22); full suite 8145+ passed, 21 pre-existing
failures name-identical develop↔branch (zero regressions).

## Live Validation (prospective)

- **Live:** all 10 entities exist on the URA Presence Coordinator device post-restart; sensors non-unknown within one inference cycle.
- **Live:** census sensor equals house-state attr `census_count` at the same instant.
- **Live:** flip Guest Detection OFF → suppressed_since ISO appears; house continues normal inference; flip back ON.
- **Live:** switch OFF survives an HA restart with ORIGINAL suppressed_since (if operator exercises it).
- **Live:** diagnostic sensor stays disabled/absent by default; no recorder volume change.
- **Live:** zero new URA ERROR log lines through first hour.
