# v5.103.93: battery charge from a second local source when the main source drops

Card: ENVOY-STREAM-SOC-TIER-1. Plan: `docs/planning/PLANNING_ec_source_failover_class.md` (operator-approved 2026-10-30). Tier 3: two plan reviews, four build reviews, orchestrator mutation check. Review record: `docs/reviews/code-review/ec_stream_soc_tier_review_summary.md`. Deploy risk: LOW until configured (feature does nothing with the stream entity unset); MEDIUM once configured (it feeds battery SOC to the Energy Coordinator).

## Problem

The Envoy coordinator fails every night around 23:00 when `/production.json?details=1` hangs (10-30 on HA 2026.10.4: out from 23:04:56 for over 36 minutes). Every native Envoy entity, including battery charge, goes unavailable, and the Energy Coordinator falls back to last-known-good SOC. The realtime battery sensor from a different integration kept reporting for most of that window.

## Fix

- New optional field in options → cloud verification: **Local battery stream** (a second SOC sensor), with **max age** (seconds) and the existing heartbeat sensor. Unset = behaviour identical to before.
- The stream is used only when the native SOC is unavailable, and only after it has earned trust: 3 agreements with native (within 3 pp), refreshed within 6 h. A disagreement quarantines it.
- On reconnect, the stream waits 60 s (capped at 120 s) and must stay within a physical slew bound (charge rate × elapsed + 3 pp) before it is served.
- Guards: a stream equal to the main battery charge sensor is rejected in the options flow and disabled at runtime with one WARNING. Max age above 300 s requires a heartbeat sensor.
- The EVSE blind guard stands down while a trusted stream supplies SOC.
- Heartbeat help text now says "(for example its house load power)".
- Knobs: `energy_const.DEFAULT_SOC_STREAM_*` (rung 1), kill switch `SOC_STREAM_TIER_ENABLED`.

## Known limit

A capacity entity with no unit is read as Wh (pre-existing).

## Tests

`test_ec_stream_soc_tier.py` (102), `test_ec_role_defaults_rev5.py` (+5). Full-suite name-diff clean vs f9a2ff33c (18,616 passed; the one failure is pre-existing on both).

## Operator action after deploy (daytime)

Options → cloud verification: Local battery stream = `sensor.envoy_482543015950_battery_2`; heartbeat = `sensor.envoy_482543015950_load_power`; max age = 120.

## Live acceptance (prospective)

| Criterion | How to check |
|---|---|
| Load clean | No URA ERROR after restart |
| Unset is a no-op | Before configuring: EC SOC source attributes unchanged; `stream_trust` unset |
| Trust earned | After configuring: trust attributes show agreement count reach 3 within ~15 min of daytime native data |
| Serves during a drop | Next native Envoy outage: EC SOC source label = stream tier, value tracks `battery_2`, not LKG |
| Returns to native | When native recovers, source label returns to native within one tick |
| No false serve | No stream serve while native is available |
