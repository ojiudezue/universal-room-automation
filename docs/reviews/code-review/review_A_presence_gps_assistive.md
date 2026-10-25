# Review A (local correctness + edge cases): presence GPS assistive

Branch `fix/presence-gps-assistive`, diff `f96aaa0ed...acab9c3f3` (merge-base verified = f96aaa0ed; commits f2941715f, acab9c3f3).
Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`. No §10 ledger claim re-asserted.
Line numbers are `person_coordinator.py` at acab9c3f3 unless stated.

**Verdict: SHIP.** No CRITICAL or HIGH. One MEDIUM (not reachable in this house today, reachable on other installs) and four LOWs.

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| A1 | MEDIUM | `:544` gate reads `sources["wifi"]`; producer `_read_source_inventory` `:326-334` | The WiFi-witness conjunct reads the lossy last-wins WiFi axis. A person with two `router` trackers, the first `home` and the last `unavailable`/`unknown`, gets `wifi="unavailable"`, so the gate treats them as having no WiFi witness. If their BLE trackers all read `not_home` (phone asleep, armed fleet), GPS/person "home" is overruled while a router says home. Repro: `device_trackers=[unifi_phone(home), unifi_laptop(unavailable), private_ble(not_home)]`, person.state home, proxy 50 for 400 s → `away_ble_silent_only`. Today the WiFi axis is MISSING for every person in this house, so this cannot happen here. Fix: scan the person's `router` trackers directly for any `home`, the same way `_own_ble_trackers_all_not_home` scans BLE. | #63 (one axis value, two concepts: diagnostic last-wins vs trust "any home witness") |
| A2 | LOW | `:536-545` vs `:765` loop with awaits `:816`, `:826` | `_fleet_armed_now` is captured before the loop (and only used for the log), but `_ble_overrules_gps_home` re-reads `_fleet_healthy_since` per person. A proxy-dip listener event that lands during a loop await disarms later persons in the same tick while earlier persons were overruled under "armed". Each verdict was valid when it was taken, so no wrong-direction outcome. It still breaks "capture before the first await, then thread the local". Fix: pass `_fleet_armed_now` into the gate. | Value entry/exit |
| A3 | LOW | `:536-545`, `:293-316` | Home witnesses with a source type other than `router`/`bluetooth_le`/`gps` (e.g. legacy classic `bluetooth`) are invisible to both the WiFi conjunct and the BLE scan, so they can't block an overrule. That matches the plan's `test_fallback_home_without_witness_overruled`. Noting it as accepted, not as a bug. | — |
| A4 | LOW | `:571-577` with S2 `:1063` / `:1147` | The 15-min guard only declines to set `_person_was_away`. It never clears a stale `True`. S2 (GPS home) pops `_person_lost_since` but leaves `_person_was_away` True. This is pre-existing (S3→S2). So if S3 away is followed by an S2 return with no Bermuda room fix, and then a short overrule happens, a BLE return under 15 min still fires `SIGNAL_PERSON_ARRIVING`. This needs Bermuda to stay unresolved for the whole home stretch, so it is rare. | Pre-existing, exposed |
| A5 | LOW | `:571-577` | If the person went S5 `no_signal` for 15 min or more (lost_since stamped and not popped) and then overrule fires, `lost_s` is already ≥ 900 s, so pre-arrival arms at once. That is semantically defensible (the person really was unaccounted for), but the guard's clock starts at the S5 stamp, not at the overrule. | — |

## Cleared (holds because …)

- **Gate conjuncts, both sites** (`:1029-1036`, `:1125-1130`): `_ps_state == "home"` is the outer test, then switch → armed → wifi ∈ {MISSING, unavailable} → BLE all-not_home with ≥1 tracker. `ble_leads_on` is captured once per tick (`_ble_leads_on`) and threaded. Unavailable, unknown or home on any BLE tracker means False (`:311-312`). Zero `bluetooth_le` trackers means False (`seen >= 1`). Any exception means False.
- **Fleet floor/arm** (`:347-357`, `:417-425`): `float(x) >= 30` is inclusive. Non-numeric, None or NaN means unhealthy and resets the latch. The latch is None at construction (boot latch). Arming is `>= 360 s` measured from the first healthy reading after the last unhealthy one. The tick timestamp and the listener timestamp are both `dt_util.now()` (tz-aware). A registry miss clears the latch (`:387-390`). The unique_id `BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT` is verified against the live Bermuda source (`ha-config/custom_components/bermuda/sensor.py:531`). `async_get_entity_id("sensor","bermuda",uid)` is the correct signature.
- **effective_person_state / person_state_for_trust** (`:121-143`, `:481-507`): a missing entity gives None, so `== "home"` is False, which matches the old `st is not None and st.state == "home"`. With no coordinator, or on any exception, the raw state is returned. Switch OFF gives raw immediately, even before the next tick empties the set. The value differs from raw only if the person is in the overruled set AND `get_person_location == "away"`. In the window between the set assignment and the `self.data` swap, the result fails toward raw. A LOST or unknown person never enters the set (the set is added only at the overrule). The name→entity mapping matches the loop's `person_entity_id` construction (`:774`).
- **frozenset assign-once** (`:1182-1188`): built in the local `overruled_this_tick`, assigned once after the loop, never mutated. On UpdateFailed the previous set is kept.
- **6 swapped readers**: `aggregation.py` ×2, `hvac.py:3401` (trust), `hvac.py:3978` (display), `hvac_fans.py:1525`, `hvac_zones.py:2666`. Each keeps a strict `== "home"`, and None or a missing entity is not home. hvac_zones' old per-get try/except is subsumed by the helper's internal catch. `camera_census.py:5882` deliberately stays raw (consequence replay).
- **S3 refactor byte-identity** (`:550-568`, default `was_away_after_min_away=False`): same statements, same order as the removed blocks at both sites.
- **Switch OFF = today**: the gate returns False first, so the `elif _ps_state == "home"` S2 arm runs unchanged and `effective_person_state` returns raw. The leftover side effects are a proxy listener subscription and INFO logs. Neither feeds a decision.
- **Missing GPS has no effect**: the gate never reads the GPS axis. It is keyed on `person.state` plus own trackers, so a missing GPS changes nothing relative to today's S2 outcome unless the person is already "home" with all BLE not_home.
- **Operator invariant** (GPS never holds home against own-BLE-not_home on a healthy fleet, with no WiFi witness): PASS for the configured fleet. A1 is the only leak, and only on multi-router installs.

## Stats

| Sev | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | – | – |
| HIGH | 0 | – | – |
| MEDIUM | 1 (A1) | 0 | orchestrator call |
| LOW | 4 | 0 | – |

Bug classes: #63 coincidental-equality/concept split ×1, value entry/exit ×1.
QUALITY_CONTEXT candidate: "a trust gate reading a diagnostic last-wins axis" is a variant of #63, so no new class is needed.
