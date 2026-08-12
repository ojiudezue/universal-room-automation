# URA v5.73.0 — One alerting brain with AI eyes (CONSOL-1) + honest duty-cycling (PRESET-FLAP-1) + iMessage photos (NM-BB-IMAGE-1)

Three cycles, one deploy. Each ran the full pipeline: adversarial plan review(s), Tier-2-DB/Tier-1
code reviews, consolidated fix-ups, orchestrator re-drills. Deploy deliberately held overnight
(hostile-timing rule) after the 08-11 incident night.

## CONSOL-1 — alerting consolidation + universal llmvision

- **llmvision enrichment on perimeter alerts** (person + vehicle): AI description appended to the
  message, image attached, budget-bounded (`perimeter_enrichment_timeout_s` Number, default 4.0s
  = 2× the D0-probe max; cancel-on-timeout — a late completion structurally cannot double-send).
  **Three-class failure contract**: exception, timeout, and EMPTY response all fall through to the
  un-enriched alert with `enrichment_failed_fall_through` in the ledger — the alert is never
  blocked, delayed past budget, silenced, or given a dangling "📸 " tail. Ships **default OFF**
  (promote after 14 full ledger days). Model pinned gpt-4o-mini/1500 tokens — the D0 probe found
  the reference doorbell automation had been silently emitting EMPTY descriptions since the
  February provider switch (fixed live, operator-approved).
- **Contextual severity** replaces the person day/night window: total over all 9 house states
  (every row test-pinned), circling override scoped to home_day/home_evening, vehicle deep-night
  window retained under renamed `CONF_PERIMETER_VEHICLE_HOURS_*` (values migrated).
- **Legacy legs retired** (both person + vehicle notify calls deleted); zone_monitoring tripwire
  (NM alert if that stack ever fires again — in-code, no soak watching); dormancy receipts for the
  12 automations queued for post-parity deletion; test-alert Button on the NM device.
- **Doorbell/G4 retirement is event-count gated**: N=5 organic front-door events, all parity
  checks clean by ledger, then step-1 disable. Until then the parity window means **two WhatsApp
  messages per front-door event — expected, not a bug.**

## PRESET-FLAP-1 — the duty limiter stops abandoning occupied rooms

Measured founding case: nine home↔away preset flips in two hours of confirmed occupancy, room
parked at ambient because the away ceiling (80) equalled the temperature. The limiter was working
as designed; the design was dishonest. Now:
- During a coast/shed duty off-phase in an **occupied** zone, the preset stays home and the
  cooling ceiling holds at `home_target + offset` (rung-3 Number, default 2.0°F, 0 = documented
  diagnostic) — the compressor coasts without the room being abandoned or the UI lying "away".
- Throttled emits (one service call per value change, not per tick), suppress-rollback on gate
  defer, S14 registered in the ARREST-COMFORT gate table, ledger row
  `runtime_exceeded_offphase` once per (zone, house_state) with live `home_persons`.
- Dominance preserved and mutation-anchored: stale-sensor, vacancy, comfort-grace, shed, and the
  kill-switch each individually proven to win. Ceiling holds until the next preset transition
  **by design** (documented trade).
- `duty_cycle_off_phase` attribute on the zone preset sensor — true only when the mechanism is
  actually engaged (not under kill-switch/shed).

## NM-BB-IMAGE-1 — iMessage photos

BlueBubbles v0.6.0 added attachment support; NM now sends the real keys (`attachment` local path
/ `media_url`). Security images land on BOTH channels. Closes SNAP-1-followup.

## Acceptance criteria

- **Live:** loads, zero URA errors; enrichment knobs present (timeout Number 4.0, enrichment OFF);
  off-phase knobs present (offset 2.0, honesty Switch ON).
- **Live (PRESET-FLAP founding case, organic):** next occupied-evening coast episode — preset does
  NOT flip to away; setpoint ceiling home+2; ONE ledger row; `duty_cycle_off_phase: true`.
- **Live (B5 named criterion):** during an off-phase on the Bryant, arrester `overrides_today`
  stays flat (the manual-hold echo does not register as an operator manual).
- **Live (NM-BB, organic):** next security alert carries the photo on iMessage too.
- **Live (CONSOL-1):** test-alert button delivers through the full stack; tripwire silent.

## Live Validation

### Validated 2026-08-12 (v5.73.0 boot, morning)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | `system_log` ERROR search for `universal_room` empty post-restart |
| L2 | Knobs live | **PASS** | `number.ura_notification_manager_perimeter_enrichment_timeout` = 4.0; `number.ura_hvac_coordinator_duty_off_phase_offset_degf` = 2.0; `switch.ura_hvac_coordinator_duty_off_phase_honesty` = on. Enrichment default OFF as specced |
| L3 | PRESET-FLAP founding case | **ORGANIC (open)** | Next occupied coast episode: preset stays home, ceiling home+2, one ledger row, honest attr. Wire-in + dominance + throttle all mutation-anchored in-suite (orchestrator re-drilled the emit neuter: 11 red) |
| L4 | B5 — Bryant manual-hold echo not misclassified | **ORGANIC (open, named criterion)** | Arrester `overrides_today` must stay flat through an off-phase episode |
| L5 | NM-BB iMessage photo | **ORGANIC (open)** | Next security alert carries the image on iMessage (BB v0.6.0 keys verified against installed source) |
| L6 | CONSOL-1 tripwire + parity window | **ORGANIC (open)** | Tripwire silent; doorbell parity window = 2 WhatsApp per front-door event (expected) counting toward the N=5 retire gate |

Context notes: v5.71.0's founding case CONFIRMED organically pre-deploy (operator received the
perimeter photo). The same alerts exposed the Frigate-1 nighttime-IR ghost-detection issue —
probed same morning (`AUDIT_perimeter_fp_correlation.md`), carded PERIM-FP-1 awaiting operator
fix-direction pick. Envoy back post OS-updates; cloud reserve legs coherent (8/8); local Enpower
number still carries the cosmetic 10 wedge.
