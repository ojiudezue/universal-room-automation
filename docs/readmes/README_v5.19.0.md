# URA v5.19.0 — Behavioral Write-Verification + R7.1 Observability Rider

**Date:** 2026-07-17
**Tier:** 3 (write-verify) + 1 (R7.1 rider) — review records:
`docs/reviews/code-review/behavioral_write_verify_tier3.md` (5 passes, 8 HIGH found/fixed),
R7.1 in `docs/reviews/code-review/r7_projection_unification_tier3.md` lineage.
**Commits:** write-verify `1fabce77` + `d881bcde` + `0e97e20f`; R7.1 `4c7956fb` + `5df965b6`.

## What ships

### 1. Behavioral write-verification (EC headline — "echo can lie; verify conduct")
Motivated by three live incidents in one week (07-15 hardware discharged below
echoed floor ~5 kWh lost; 07-11 20.7-h stuck write found retroactively by the
B0 probe; 07-16 app/hardware divergence confusion).

- **D1 Conduct check** (detect-only): SOC below the EFFECTIVE commanded floor
  (post-overlay: max of strategy desire, EVSE hold, inclement floor) by >4 pp
  AND discharging >500 W for 3 consecutive ticks → `hardware_noncompliance`
  ALERT anomaly to NM. Narrow legal exceptions (verify-window, stale desire,
  blind, effective-desire-lower, inclement-floor-respected, grid outage);
  abstains when SOC/power/grid witnesses unavailable (they flap with the
  Envoy — B0).
- **D2 Pending-write watchdog**: inference-only divergence age (URA's own
  desire ledger vs hardware witness) → bounded retry ladder 15/30/60 min
  (spacing-gated; ≈2× measured apply-lag p90 of 7.7 min) via new narrow
  `force_redispatch` entrypoint. Every retry RE-DERIVES live effective desire
  (cancel-not-replay on strategy movement; no retry while blind). Alarm
  escalates per attempt; **hard stand-down after attempt 3** — surface marked
  non-compliant, NM page states URA has deliberately let go, ALL emitters
  (including the EVSE-hold overlay) gate same-value re-dispatch until a
  resume condition (convergence / desire change / 3-h cool-off probe).
- **D3 Command trail**: `command_trail` attr on the battery-strategy sensor —
  commanded (+ hold owner) / hardware-enforced / cloud-oracle view, each with
  age. Born from the 07-16 "is the battery full? who commanded 61?" confusion.
- All thresholds rung-1 reviewed constants sized by the B0 probes
  (energy_const.py CONF_CONDUCT_* / CONF_PENDING_*); kill switches
  CONF_CONDUCT_ENABLED / CONF_PENDING_WATCHDOG_ENABLED.

### 2. R7.1 rider (observability mirrors decision)
- `attain_reason` + attrs now carry `projected_soc` AND `horizon_min` from
  the SAME EnergyProjector result the decision consumed (kills the
  "153% < 80%" stale-text class); hold-current site refreshes per tick.
- Projector `mins=None` now fail-closed (blind) instead of silent
  zero-horizon; blind projection shows "?" horizon symmetrically.

## Review outcome
Write-verify: A SHIP / B, C, D FIX-FIRST → fix-up 1 → D re-pass found the
N+1th site (EVSE overlay bypassing stand-down) → fix-up 2 → SHIP. 22 findings
(8 HIGH, 8 MED) all fixed; 27 mutations executed RED across the campaign;
orchestrator re-executed 2 personally. New bug-class candidates:
invented-attribute getattr; pre-vs-post-overlay ledger split.

## Live Validation (prospective — replace with Validated table post-restart)
- **Live:** clean restart, zero URA ERRORs referencing write_verify/
  force_redispatch/conduct.
- **Live:** `command_trail` attr populates on
  `sensor.ura_energy_coordinator_battery_strategy` with three legs + ages;
  hold_owner shows "evse_battery_hold" during tonight's charge if car plugs in.
- **Live:** conduct + watchdog SILENT through a clean day (no false NM) —
  false-positive-freedom is the headline acceptance.
- **Live:** attain_reason carries "projection horizon N min" once the ladder
  runs (tomorrow ~11:00 window).
- **Organic (unbounded):** next Enphase wedge (3 occurred this week) exercises
  ladder attempt 1+ — NM shows pending_write_stuck with attempt number.
- R1 shadow marker check rides tonight's rollover (48h criterion, separate).
