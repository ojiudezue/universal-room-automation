# URA v5.69.0 — Comfort-delay grace: the arrester stops arresting the kids (ARREST-COMFORT-1 Cycle A)

**Tier 3** — four framing-disjoint reviews (A local correctness / B integration+flakes / C test
authority via 26 re-executed drills / D adversarial completeness ×2 runs), a 19-finding
consolidated fix-up, an anchor follow-up (hollow-anchor instance #12 caught by orchestrator
re-drill), and D's post-fix re-enumeration returning SHIP with the invariant holding across a
13-site chokepoint census.

## The founding incident

2026-08-09: kids in an 80°F zone set the thermostat to cool — twice. The override arrester
reverted both inside 10 minutes. After 17:19, no further manual writes: they gave up. The system
trained them that the thermostat does not work. Probe (7d recorder): ~44 qualifying comfort
events/week, ~50% at SOC ≥ 80.

## What ships

- **Comfort-delay grace**: a genuine manual setpoint change that (a) moves TOWARD comfort on the
  hvac-mode-relevant leg, (b) in a LIVE-occupied zone (`any_room_occupied` — not the configured
  persons list), (c) with battery SOC ≥ floor at grant (evaluated ONCE), (d) no shed, no blind
  battery, fresh temps — earns a grace window during which URA's write surfaces defer instead of
  reverting. Standard arrest resumes at expiry, zone vacancy, or the arrester kill-switch.
- **S1–S13 write-site verdict table, enforced**: dual chokepoints (`emit_set_temperature` gate
  param + new `emit_set_preset_mode`) with per-site gates: S1 reason-ladder (relabel now scoped
  to the actual forced-away skip), S3 compromise, S4 revert (+ mode-flip short-circuit), S5 nudge
  start DEFER; S6–S9 + egress-resume restorations ALLOW; **S10 DPM apply, S11 release-banked,
  S12 pre-cool, S13 pre-heat** — the four pre-existing ungated surfaces Review D found — now
  gated, each caller-site mutation-anchored with a paired no-grace positive control.
- **AI-rules climate block**: `_execute_rule_action` refuses direct
  `climate.set_temperature/set_preset_mode/set_hvac_mode` (the real R2-residual site — found in
  `coordinator.py`, not where the plan looked). Zero live climate rules; chain-bypass via
  `automation.trigger` documented open until the parked chokepoint-routing upgrade.
- **Rung-3 knobs**: `comfort_grace_minutes` (default 30, 0 = kill) and `comfort_soc_floor_pct`
  (default 80, 0 = SOC-blind with boot WARN under 20) as persisted Number entities, eager-seeded
  at coordinator construction (no boot-default window).
- **Kids-incident replay fixture** committed: drives the real `_handle_climate_change`; first
  transition grants at SOC 99, kill-switch drill drops it into the severe path.
- **Ledger**: every deferred write logs `comfort_delay_deferred_write` with site tag (anchored);
  grace evictions log expiry_reason (timer / switch_on / zone_unoccupied).

## Review provenance

Build 18b491e01 → A DO-NOT-SHIP (CRIT: occupancy read the static config list) / B SHIP /
C DO-NOT-SHIP (hvac.py-side consumer untested) / D DO-NOT-SHIP (invariant VIOLATED via S10-S13 +
AI-rules). Fix-up b49087bcc (18/19; B-MED-2 deferred — trigger absent from baseline) →
orchestrator re-drill caught hollow S10 anchor → follow-up 831514d1d (5 caller-site drills +
positive controls + 3 D-LOWs). Orchestrator independently re-drilled A-CRIT-1 (both sites), S10
(2 red), S12 (1 red) — all restore-green. D re-enumeration: **invariant HOLDS**, SHIP.
Suite: 23 failed / 8626 passed — failing names identical to the pre-cycle baseline.

## Acceptance criteria

- **Live:** integration loads; zero URA errors; `number.ura_*comfort_grace*` and
  `number.ura_*comfort_soc_floor*` entities exist with defaults 30 / 80.
- **Live (founding case, organic):** a genuine manual cool request in an occupied zone at
  SOC ≥ 80 is NOT reverted within the grace window; ledger shows the grant and any
  `comfort_delay_deferred_write` rows with site tags.
- **Live (no suppression):** normal DPM preset applies, pre-cool/pre-heat, and arrest of
  NON-qualifying manuals (vacant zone, shed, low SOC) continue unchanged.
- **Live (restart):** grace is RAM-only; post-restart coast tick snaps back per documented
  behavior; knobs restore their persisted values.

## Live Validation

_(prospective — to be replaced with the validated table post-restart)_
