# Review A + B: fix/ec-reserve-witness-envoy-sensor @ 76ca12e39

Base f9fb1f5ba (verified = merge-base). Three-dot diff: energy_const.py (+2 consts), energy_write_verify.py (+77/-2), quality/tests/test_ec_reserve_witness_resolution.py (16 tests, pass). Card EC-SELFHEAL-UNEXPLAINED-RESENDS-1. Not HVAC/presence; state-of-play docs not applicable.

## Pass A: local correctness

| # | Sev | Site | Finding |
|---|---|---|---|
| A1 | clear | energy_write_verify.py:431-480 | unique_id formats verified in HA source: Encharge aggregate sensors `battery_level` and `reserve_soc` (enphase_envoy/sensor.py:748,755) both use `f"{envoy_serial_num}_{key}"` (EnvoySystemSensorEntity, sensor.py:1001), so the SOC anchor and the reserve sensor share the Envoy serial. Enpower number `reserve_soc` (number.py:160/172) is domain `number`, so the `"sensor"` filter correctly excludes it. Registry APIs: `async_get(entity_id)` (entity_registry.py:891) and `async_get_entity_id(domain, platform, unique_id)` (:902), both used correctly. |
| A2 | clear | :447-466 | Missing anchor, non-envoy platform, wrong suffix, empty serial, unregistered sensor, disabled sensor: all return None and fall back to the number. Exceptions are swallowed at DEBUG. Covered by the 16 tests. |
| A3 | LOW | :447 | Anchor must be the Encharge-aggregate `*_battery_level` sensor. If the operator points `battery_soc` at the ACB/aggregated SOC sensor (different key), the code silently falls back to the dead number. One INFO line is logged, so this degrades loudly enough. No fix required. |
| A4 | clear (cost) | no cache | Each call does 2-3 dict lookups. There are about 4 call sites per tick (watchdog, witness_compare, diagnostics x2, anomaly payload). The cost is negligible, and skipping the cache means a late-registered sensor gets picked up without a restart. |
| A5 | LOW | :472 | The log-once flag is per instance and is never reset. If resolution later succeeds and then fails again, nothing is logged the second time. Acceptable for an INFO hint. |
| A6 | clear | unit | The sensor is `PERCENTAGE` (sensor.py:757). The number was also %. `_compare` already normalizes percent, so units do not change. |
| A7 | clear | abstain | `_local_reserve_witness_state` (:1639-1648) returns (None,None) when the state is unavailable/unknown/non-float, and the watchdog abstains (:2219). `_witness_compare` (:1058-1062) skips on None raw. Diagnostics (:2571, :2588) display None. A sensor that is unavailable never falls back to the number, because resolvability depends only on the registry. All 5 readers verified. |
| A8 | clear | :2347 | `hw_witness_entity` is str or None and is serialized via `build_context_json`. No consumer outside write_verify reads `pending_write_stuck` payload keys (git grep). DB-safe. |
| A9 | NOTE | :1058 | Behaviour change outside the watchdog: `_witness_compare` (H1 secondary witness) now compares against the live sensor too. Before, every non-10 reserve produced a spurious `write_local_witness_divergence` row. Expect that anomaly row rate to drop after deploy. This is intended, and the plan should mention it in the live criteria. |

**Pass A verdict: SHIP.**

## Pass B: write-path integration

| # | Sev | Site | Finding |
|---|---|---|---|
| B1 | clear | energy.py:9683-9698 | The dispatch tap filter resolves `_get_entity("reserve_soc_number", role="write")`, which is unchanged. `_local_entity_for` / `_envoy_reserve_sensor_eid` have no callers outside energy_write_verify.py. Within it they are only read, never used as a service target. Failover routing (`_get_entity` role="write", energy_battery.py:881) is untouched. No write path reads the new witness. |
| B2 | clear | :2198-2330 | The ladder, 3 h stand-down and CRITICAL page logic are unchanged. Only the input value changes. With a live sensor, a converged write now hits `_reset_pending_episode` instead of climbing to attempt 3. That is the fix. |
| B3 | MEDIUM (pre-existing, not a regression) | :2219 | Unbounded abstain during an Envoy local outage. Sequence: Envoy LAN down, sensor `unavailable` for hours, commanded reserve 80 while hardware is really stuck at 20. The watchdog abstains every tick: no retry and no page, with no limit on how long. The old witness (Enpower number) sits on the same Envoy and was also `unavailable` during an outage, so the exposure is the same as before. The cloud primary oracle verify still runs and pages on a cloud-side mismatch, and `cloud_write_leg_unavailable` covers the cloud leg. Recommend a code trip-wire card: anomaly to NM when witness-abstain lasts longer than N min while an episode is open (No-Soak rule). Does not block ship. |
| B4 | LOW | :2219 + stand-down | If the sensor goes unavailable mid-episode, the episode, stand-down pin and attempts are frozen, not reset. The guards that read episode state (`is_reserve_verifiable`, the self-heal suppression) keep seeing the old episode until the sensor returns. This matches the existing observation-mode freeze semantics and is not new. |
| B5 | clear | boot | At boot the sensor is unavailable or missing. If the registry entry exists (it persists across restarts), the code resolves the sensor and abstains until a state arrives. If the entry is not loaded yet, it falls back to the number for those ticks, and that number is also unavailable at boot, so it abstains too. Either way there are no spurious re-sends. The ladder-spacing gate (:2275) still blocks a burst once the witness comes back after pre-aging. |
| B6 | clear | non-Envoy / Wigton | Without an enphase_envoy SOC anchor, `_local_entity_for` returns exactly what it returned before. The only differences are one INFO log line and one new payload key, `hw_witness_entity`, that is informational. Behaviour is byte-identical. |

**Pass B verdict: SHIP.** Must-fix: none. Follow-up card: B3 abstain-duration trip-wire.

## Stats
CRIT 0 / HIGH 0 / MED 1 (pre-existing, B3) / LOW 3 (A3, A5, B4) / notes 1 (A9). Bug classes: B3 = suppression-without-discharge (unbounded abstain); A9 = consumer re-enumeration (5th reader beyond the plan's list).
