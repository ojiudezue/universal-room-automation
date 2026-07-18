# URA v5.22.0 — BLE Extends Occupancy, Never Creates It

Fixes the 2026-07-17 Master Bathroom light strobe: Bermuda placement jitter
(`sensor.iphone_oji_area` flapping Bedroom↔Bathroom) exploited the v3.8.8
Tier-1 direct-BLE unconditional occupancy-create, cycling the lights every
1-3 minutes with 18-63s on-times while the room's PIR/mmWave were silent.

## The fix (coordinator.py BLE block)
Two-leg admission, uniform for ALL scanner tiers:
- **Chain leg (EXTEND):** room occupied on the previous update cycle ⇒ BLE
  holds indefinitely while the person keeps being reported present. The
  v4.7.13 still-body sleep hold is fully preserved (review B caught the
  build initially bounding it — fixed via this chain formulation).
- **Motion leg (handoff):** real motion within `BLE_MOTION_CONFIRM_MULTIPLIER
  × occupancy_timeout` (rung-1 constant, default 2; **0 = BLE hold disabled
  entirely**). Negative clock-skew rejects (intentional hardening).
- A room UNOCCUPIED last tick with stale motion REJECTS — BLE can never
  flip a cold room to occupied. Sensor-only entry is the restored design
  contract (operator: "we didn't design for any BLE lighting on entry").

Truth correction shipped in-comment: the 4h occupancy failsafe does NOT
bound BLE holds (never did — its check point sees BLE ticks as unoccupied);
forgotten-phone mitigation is `PersonPhoneLeftBehindSensor`.

Composition guarantees (audited pre-deploy): lights + temperature fans +
humidity/exhaust fans all consume the same `STATE_OCCUPIED` edge (operator's
divergence hypothesis verified FALSE); fan-recheck arms only on mmwave source
and its release breaks the BLE chain; BLE-only rooms impossible by config-flow
construction; zone/house presence tier reads person_coordinator directly.

Review: `docs/reviews/code-review/ble_extend_not_create_tier2db.md`
(3 framings + B re-look + pre-deploy actuation audit; 1 HIGH + 1 test-CRIT
found/fixed; 9 reviewer mutations + 2 orchestrator mutations all conclusive).

## Rider
`custom_components/lovesac_stealthtech` (staged 2026-07-17, non-URA sibling
project) loads at this restart — expect its config-flow discovery card IF the
StealthTech hub is BLE-reachable via the ESPHome proxies; no URA interaction.

## Validated 2026-07-18 ~00:50 CDT (post-restart)

| Criterion | Result | Evidence |
|---|---|---|
| Cold-flap zero-actuation | **PASS (boot window) / organic PENDING** | Zero `source=ble` occupancy entries and zero Master Bathroom actuation rows post-restart (11 activity rows, none matching). Caveat: `sensor.iphone_oji_area` = `unknown` since boot — Bermuda hasn't flapped yet, so the exact fixture condition hasn't recurred. In-suite proof (17 tests incl. the 6-flap fixture + 2 orchestrator mutations RED) is the authority until the next organic jitter episode; check the activity log after the next one. |
| Still-body sleep hold intact | PENDING (organic, tonight) | House entered `home_night`; the chain-leg hold proves itself through the sleep period. Sleep-hold pin test + M3 mutation anchor are the in-suite authority. |
| Tier-2 over-hold watch | OPEN (multi-day) | Watch one shared-scanner room for phone-left-behind over-hold; `PersonPhoneLeftBehindSensor` is the mitigation. |
| Regression | PASS | Zero URA ERROR entries (all boot errors non-URA: Shelly reconnects, pyenphase teardown, unifiprotect media source, laundry >255 template, MQTT number range). House state live (`home_night`, 0.7). BAEC switch ON, EV Charging Plan `hold_only` — v5.21.0 undisturbed. |
| Rider: Lovesac first load | PASS-load / discovery pending | Component loaded with zero error lines. No discovery card — hub not currently advertising to the proxies (Lovesac app likely holding the single BLE slot, or out of proxy range). Couch probe session is the discriminator; manual-address config-flow entry is the fallback. |
| Suite | PASS | Cycle tests 17/17; full suite within the 36F/14E pre-existing envelope at deploy time. |
