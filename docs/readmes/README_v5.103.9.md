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

## Live Validation — prospective (write observed results back after restart)
- **Verify:** `sensor.ura_hvac_coordinator_*` / HVAC zone-intelligence sensor `zones_energy_shed_cap_reached` (renamed from `zones_runtime_limited`) populates when a zone trips the cap under coast; **no** stray `runtime_exceeded` in any emitted reason/attr.
- **Verify:** the new duty-cap Number entities + enable switch exist, persist across reload, and `0` disables D5 for that mode.
- **Verify (discriminator):** a `preset_change` / `preset_change_suppressed` row for a duty-cap event now carries `any_room_hvac_occupied` + `constraint_mode` in `details_json` (so the gate is provable, not assumed). A coast+occupied event shows `energy_shed_cap_deferred_occupied` with **no** thermostat write; a coast+empty event shows `energy_shed_cap_reached` with the away write.
- **Verify:** zero URA ERROR on boot; the recurring absence of the old `runtime_exceeded` operator surface.
- **Live SQL (INV-D5-GATE):** see `PLANNING_hvac_d5_reframe_occupancy_gate.md` §6 (updated to the real reason + detail fields).

## Rollback
`git revert` the merge, or set the D5 master enable switch OFF (kill switch) for immediate mitigation.
