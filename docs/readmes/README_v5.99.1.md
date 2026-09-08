# v5.99.1 — Energy-pool actuation + charge-onset logging (observability)

**Type:** Observability instrumentation (diagnostic telemetry; control path byte-identical).
**Tier:** 2-DB-grade review (write-queue-adjacent — this project rolled back once on a
DB write-flood, v4.7.33). One focused review (write-flood + control-path safety) + orchestrator
mutation-verify. Card: `ENERGY-POOL-ACTUATION-NOT-IN-ACTIVITY-LOG-1` (prerequisite for
`EVSE-CHARGE-ONSET-NOT-HELD-1`).

## Why
Charge-onset didn't hold either charger the night of 2026-09-06 (L2 charged at 11.6 kW from
21:02, draining the house battery 46%→9%), but the diagnosis stalled: the energy-pool
controllers (EVSE + L1 plug) wrote **nothing** to `ura_activity_log`, so charger actuations
and onset-gate decisions couldn't be audited after core logs rotated. This adds that audit
trail so the next occurrence names the exact culprit (a real onset gate gap vs an external/
autonomous charger vs an ungated path).

## What shipped
- **Onset-gate telemetry** at all 4 gate sites (EV/plug × ensure-on/drain-release): edge-triggered
  `onset_hold` / `onset_release` rows carrying kind, leg, onset time, `remaining_to_onset`, and a
  discriminating reason (`gate_refused` / `onset_permits` / `must_start_by` / `dp_forcing` /
  `soc_recovered` / `bypass_onset`).
- **Applier telemetry**: `charger_on` / `charger_off` rows (kind, charger id, live power, pause-owner
  memberships) at the point the pool `switch.turn_on/off` is dispatched.
- **Flood-bounded**: both are EDGE-triggered — one row per state transition per (charger, leg), not
  per 5-min tick. (Review caught two per-tick flood paths — the idempotent ensure-on re-issue and a
  bypass/gated cache thrash — both fixed with edge caches; mutation-verified RED-on-neuter.)
- **Control path byte-identical**: every log call is try/except-wrapped (telemetry never raises into a
  charging decision or dispatch), no new await, no control-variable writes. No new numeric knobs.

## Live acceptance criteria (discriminating)
- **Verify:** after a restart + one overnight window, `ura_activity_log` contains a BOUNDED number of
  `onset_hold`/`onset_release`/`charger_on`/`charger_off` rows (edge count, ~single digits per charger
  per night) — NOT ~190/night. Discriminator vs the flood regression: a per-tick bug would produce
  dozens per hour.
- **Verify:** a charger held on across the window shows exactly one `charger_on` (not one per tick).
- **Diagnostic payoff:** the next in-window charge produces an `onset_hold`/`release` row whose reason
  names why it wasn't deferred → resolves `EVSE-CHARGE-ONSET-NOT-HELD-1`.
- **Live:** no DB write-flood / write-queue watchdog after deploy (the v4.7.33 regression class).

_Validated <date> — filled in post-restart._
