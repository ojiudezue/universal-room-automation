# URA v5.16.2 — Rider deploy: DB write-worker gap hardening · battery_full_time attrs surfaced

Two small reviewed fixes riding one deploy. Commits `2e2dbd68`+`b2a49398`
(worker gap) and `5360c0f6` (attr surfacing).

## 1. DB write-worker gap hardening (Tier 1, reviewed SHIP)

Rows submitted while the DB write worker isn't running were raised+dropped
with ERROR logs (1 at the v5.15.0 boot, 4 at v5.16.0). Now they buffer on
the existing write queue and drain as the worker's first act — lossless,
ordering-independent; the error becomes a DEBUG note.

**Review correction worth recording (A1):** the trigger was misdiagnosed
as boot-setup concurrency — boot producers structurally cannot hit the
pre-start branch (they acquire the DB handle only after the worker
starts). The real trigger is the **worker-restart window** (the
post-STARTED SPAN re-migration stop/start cycle). Docstrings corrected;
`stop_write_worker`'s contract now documents buffer-not-raise (deliberate
stop windows see writes deferred, not rejected).

First cost-trial datapoint for the Opus-tier reviewer (`ura-reviewer-std`):
SHIP verdict, ~81k tokens, caught the A1 misattribution — quality
comparable to the session's Fable average.

## 2. battery_full_time attributes surfaced (Bug Class #55 follow-up)

v5.16.1's H2 computed the new attrs (basis, current_charge_rate_kw,
taper_band, taper_note, missing_input, consumption assumptions) at nine
predictor sites — but the sensor had no `extra_state_attributes` at all,
so nothing surfaced. Fixed: coordinator property + sensor attrs property.

## Acceptance

```yaml
version: 5.16.2
hypotheses:
  - id: H1
    name: ura_v5162_deployed
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.16.2" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: no_worker_gap_errors
    description: Zero "DB write worker not running" ERROR lines across this boot AND across the next SPAN re-migration worker re-cycle.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "DB write worker not running", period: 24h }
    expected: { condition: "==", value: 0 }
    window: { first_check_after: 30m, confirm_after: 1d, alert_if_violated_after: 2d }
  - id: H3
    name: full_time_attrs_live
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_energy_coordinator_battery_full_time, attribute: basis }
    expected: { condition: "in", value: ["current_rate", "solar_forecast", "unavailable"] }
    window: { first_check_after: 30m, confirm_after: 2h, alert_if_violated_after: 24h }
```

## Live Validation (prospective — write back post-restart)

| # | Criterion | How |
|---|---|---|
| L1 | Deploy healthy; ZERO "DB write worker not running" lines this boot (v5.16.0 had 4 — this boot includes the SPAN re-migration worker re-cycle, the real trigger) | error log |
| L2 | battery_full_time sensor carries `basis` + rate/taper attrs | sensor attrs |
| L3 | No regression on the v5.16.1 surfaces (write_route attrs, verification rows intact) | battery-strategy attrs |
