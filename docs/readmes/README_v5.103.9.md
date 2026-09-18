# v5.103.9 — D5 duty-cycle reframed: honest name, occupancy-gated, operator knobs

**Cycle:** `HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1` · Tier 2-DB (3 framing-disjoint reviews + fix-up + orchestrator mutation-verify)

## Problem
The D5 "duty-cycle protection" limiter forced a zone to `away` once its compressor ran past a
fraction of a rolling 20-min window **during EC coast/shed — regardless of occupancy.** A Bryant
duty-cycle audit (`AUDIT_bryant_duty_cycle_redundancy_2026_09_17.md`) established it protects
**nothing**: the Infinity/Evolution control board already protects the compressor natively
(variable-speed units modulate rather than cycle). D5 is **occupancy-blind energy-shed policy
wearing a compressor-protection name** — so a kitchen you're standing in got abandoned on a hot
evening, with the reason string `runtime_exceeded` implying a hardware safety it doesn't earn.

## Solution (option b — reframe + gate, not delete; it's still a legit coast/shed lever on empty zones)
- **D-b1 — honest name.** Operator-facing `runtime_exceeded` → **`energy_shed_cap_reached`** (no
  alias, Single-User-No-Back-Compat). Internal field name kept for stability.
- **D-b2 — occupancy gate (NO-WRITE defer).** Under coast (non-shed), when a zone is fused-occupied
  (`any_room_hvac_occupied`), D5 **defers** the forced-away and writes **nothing** to the thermostat
  (ledger-only, reason `energy_shed_cap_deferred_occupied`). **Shed still dominates** (occupied zones
  still forced away under shed). Empty zones under coast are still forced away (the lever is
  preserved). The no-write defer specifically avoids re-creating the S14 self-lockout (a setpoint
  write flips Carrier to `manual`).
- **D-b3 — knobs to Rung 3.** Duty window + coast/shed caps are now live `Number` entities + a master
  enable switch; `0` on any cap = documented kill (clears the latch immediately).

## Review ledger
3 framing-disjoint reviews (A correctness/rename · B state-machine/restart · C test-authority +
adversarial INV-D5-GATE) all returned FIX-REQUIRED and **converged**: the rename missed its
sensor/frontend consumers, the defer observability was unwired, the kill-switch left the latch
latched, the live discriminator couldn't fail, and every test was a hollow source-grep (8/9
load-bearing sites untested). One fix-up round addressed all (F1–F7 + MED/LOW), replacing the
anchors with **13 behavioral tests**. **Orchestrator independently re-ran the mutation drills**
(gate defer, F5 latch clear, rename producer) — all RED when neutered. `INV-D5-GATE` held under
adversarial static enumeration (no away-forcing path leaks an occupied zone under non-shed).

## Validated 2026-09-18 (post-restart, running v5.103.9, house_state=away/normal mode ~00:47 CDT)

| Criterion | Result | Observed evidence |
|---|---|---|
| D5 duty knobs exist + correct defaults + enable | **PASS** | `number.ura_hvac_coordinator_d5_duty_cycle_window_minutes`=20, `..._coast`=75, `..._shed`=50; `switch.ura_hvac_coordinator_hvac_d5_duty_cycle_enable`=on |
| Coast/shed dwell attrs | **PASS** | `sensor.ura_hvac_coordinator_mode` (10 · Mode): `energy_constraint_mode=normal`, `energy_constraint_since=null`, `energy_constraint_duration_s=0` (correct — not in coast) |
| `retreat_reason` live, no stray `runtime_exceeded` | **PASS** | `sensor.ura_hvac_coordinator_hvac_zone_preset_zone_{1,2,3}` retreat_reason = `house_state_transition` / `vacant_past_grace` / `vacant_past_grace`; template scan of all sensors found **no** `runtime_exceeded` operator surface |
| `d5_occupancy_deferred` wired (was the "zero readers" HIGH) | **PASS** | present on all three zone-preset sensors = `False` (correct — no defer at normal mode) |
| CRIT rename consumer fix (permanently-empty list) | **PASS (corrected note)** | sensor.py:13717 comparand fixed to `== "energy_shed_cap_reached"`; **the attribute KEY was intentionally KEPT as `zones_runtime_limited`** (sensor.py:13711 comment — stable operational name / dashboard compat), NOT renamed. This README's original claim of a `zones_energy_shed_cap_reached` key was wrong; the *functional* fix (list no longer permanently empty) is in place. |
| Zero URA ERROR on boot | **PASS** | system log (WARNING+) shows only benign known boot transients (Envoy re-validation, HVAC boot-settle 60s timeout, sensors-unavailable-holding, Bermuda/camera at boot, HA-2027 deprecation notices); no ERROR, HVAC first decision cycle proceeding |

### Deferred to the next coast evening (the soak-exit `--revisit` discriminator — coast-only behavior)
- The occupancy **defer** itself (`energy_shed_cap_deferred_occupied`, NO thermostat write on an occupied coast zone) and the populated `zones_runtime_limited` list + `energy_shed_cap_reached` away on empty coast zones. **Discriminator:** on a coast/peak-TOU evening (~18:00–21:00) `ura_activity_log` shows ≥1 `energy_shed_cap_deferred_occupied` row (`details_json.any_room_hvac_occupied=1`, occupied zone NOT written) AND ≥1 `energy_shed_cap_reached` (empty zone shed), ZERO `runtime_exceeded`. See `PLANNING_hvac_d5_reframe_occupancy_gate.md` §6.

## Rollback
`git revert` the merge, or set the D5 master enable switch OFF (kill switch) for immediate mitigation.

## Rollback
`git revert` the merge, or set the D5 master enable switch OFF (kill switch) for immediate mitigation.
