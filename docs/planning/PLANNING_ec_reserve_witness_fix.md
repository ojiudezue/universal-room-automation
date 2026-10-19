# PLANNING: EC reserve write-verifier witness fix

**Card:** EC-SELFHEAL-UNEXPLAINED-RESENDS-1. **Revised:** 2026-10-18 (rev 2).
**Evidence:** `docs/planning/AUDIT_ec_selfheal_resends_root_cause_2026_10_18.md` (root cause, re-verified),
`docs/planning/AUDIT_envoy_reliability_recount_and_witness_reconcile.md` (10-17 recount).
**Operator rulings:** 10-17 "no new setting"; 10-18 "why a new setting? What's the real problem" and
"keep the ±2 margin". Code on `develop` wins over this doc.

## 0. The real problem and the fix

The reserve verifier's local witness `_local_entity_for(RESERVE)`
(`domain_coordinators/energy_write_verify.py:369-409`) resolves to
`number.enpower_482348004678_reserve_battery_level` (`EC_ROLE_KEY_DEFAULTS`, `energy_const.py:2442-2444`).
That number is dead: only `10.0` or `unavailable` in the recorder since 2026-08-05, while the real
reserve moved 5..99. Every commanded reserve other than 10 looks unapplied, runs the 15/30/60-min
re-send ladder, pages CRITICAL with `oracle_seen=10.0`, and arms a 3-h stand-down. Every command of
10 looks converged even when the battery is elsewhere (10-12/13: commanded 10, battery 14, silent).

**Fix:** in the RESERVE branch of `_local_entity_for` only, prefer the live local Envoy sensor
`sensor.envoy_<envoy_serial>_reserve_battery_level`, found by entity-registry lookup anchored on the
configured SOC entity's Envoy device. Fall back to today's number when the sensor is not resolvable.
No new setting, no repoint of `energy_reserve_soc_entity`, no tolerance change.

## 1. Institutional context verified

### 1.1 Config-first
- Repointing `energy_reserve_soc_entity` (CONF_ENERGY_RESERVE_SOC_ENTITY → key `reserve_soc_number`,
  `energy.py:1091`) to the sensor: **rejected.** The same key is the write target for every
  `role="write"` read (`energy_battery.py:6133, 7568`; `energy.py:5368, 7251, 7471`), the floor read
  (`energy_battery.py:5304`), the call_service target filter (`energy.py:9697`) and the write-failover
  route key (`energy_write_verify.py:2394`). A read-only sensor there breaks the local write fallback.
- No existing witness setting: `grep -n "WITNESS\|reserve_witness" const.py energy_const.py config_flow.py`
  → only `TRUST_CLASS_WITNESS` (`const.py:534`, presence trust class) and
  `CONF_ENERGY_STREAM_COWITNESS_ENTITY` (`energy_const.py:337`, SOC MQTT stream freshness co-witness,
  read at `energy_battery.py:1737`; unrelated). Code change is required; no CONF is added (operator).

### 1.2 Re-run greps (2026-10-18, `develop`)
`grep -rn "_local_entity_for\|_local_reserve_witness_state" custom_components/universal_room_automation`:

| # | Site | Use | Trust vs display |
|---|---|---|---|
| C1 | `_witness_compare` `energy_write_verify.py:990` | emits `write_local_witness_divergence` (info) | analytics |
| C2 | `_local_reserve_witness_state` `:1558/1567` → `_pending_watchdog_reserve` `:2147` | attempts 1/2/3, NM CRITICAL, hard stand-down | **trust** |
| C3 | `_local_reserve_witness_state` → command_trail `:2498` | `hw` value | display |
| C4 | `_local_entity_for` → command_trail `:2515` | `hw_age_s` | display |
| C5 | stand-down state → `is_standdown_active_for_value` in `_reserve_action` / `force_redispatch` | same-value re-dispatch skip | **trust (write path, indirect)** |

No other caller of either function. All other `"reserve_soc_number"` reads
(`energy_battery.py:2500, 5304, 6133, 7021, 7568`; `energy.py:5368, 7251, 7471, 9697`;
`energy_write_verify.py:2394`) are write-target / role="write" / routing reads and are untouched.
`grep -rn reserve_battery_level` (prod) → no reader of the Envoy sensor exists today; the only
hits are the hard-coded default (`energy_const.py:2443`), the docstring at `:1563` that already
names the sensor as the honest witness (doc/code mismatch since July), and the literal
`"hw_witness": "envoy_reserve_battery_level"` at `:2274` (a label, not the entity read).

### 1.3 REUSE-or-BUILD
| Piece | Verdict |
|---|---|
| Resolver | REUSED `_local_entity_for` `:369-409`, RESERVE branch only |
| Serial anchor | REUSED configured SOC entity `battery._get_entity("battery_soc")` (from `derive_envoy_config`, `energy_const.py` ~1576-1600) |
| Registry sibling pattern | REUSED shape of `_nws_last_updated_entity` `energy_battery.py` ~3049-3075 (registry + unique_id sibling, warn-once) |
| Registry API | REUSED HA `EntityRegistry.async_get_entity_id(domain, platform, unique_id)` |
| Sensor unique_id | VERIFIED HA core `enphase_envoy/sensor.py` (`<envoy_serial>_reserve_soc`; SOC `<envoy_serial>_battery_level`). Envoy serial 482543015950 ≠ Enpower serial 482348004678, so the number's serial is not usable |
| Fallback | REUSED today's `reserve_soc_number` role="read" |
| Tolerance | REUSED `_compare` ±2.0 `:1139`, unchanged |
| New CONF / sensor / knob | NONE |
| `hw_witness_entity` key on `pending_write_stuck` extras (`:2265-2276`) | NEW additive key (the existing `hw_witness` literal is left as-is) |

### 1.4 Prior docs / memory
`PLANNING_behavioral_write_verify.md` §B0-D2 (July probe already named the sensor; build wired the
number: computed-but-not-consumed). `PLANNING_envoy_write_verification_and_redundancy.md` (origin of
`_local_entity_for`). `PLANNING_reserve_write_governor.md` (writer allowlist; no writer added).
`PLANNING_envoy_local_witness_and_solar_follow.md` MQTT stream witness: closed NO-GO 10-07, not revived.
Memory: `project_battery_soc_envoy_not_span`, `reference_ec_reserve_verifiable_backout_knob`
(`is_reserve_verifiable` reads the cloud oracle; unaffected), `feedback_coincidental_equality_masks_concept_split`.

## 2. Falsifiable invariants

- **INV-W1.** Where the registry has a `sensor` entity, platform `enphase_envoy`, unique_id
  `<serial-of-configured-SOC-entity>_reserve_soc`, no reserve witness read (C1-C4) ever reads the
  `reserve_soc_number` entity, including while the sensor is `unavailable`/`unknown` (abstain, never
  fall back on state).
- **INV-W2.** Where that sensor is not resolvable, every witness read returns exactly today's entity;
  charge_from_grid and storage_mode witness resolution is byte-identical on every install.
- **INV-W3.** No write-side change: no writer, deadband, floor, tolerance, or `energy_reserve_soc_entity`
  routing changes; `RESERVE_SET_VALUE_WRITERS` lint unchanged and green.

Break attempts (reviewer D): Envoy offline (sensor unavailable, number 10, commanded 10 and 30);
SOC anchor unset or non-Envoy; registry raises; a `number` with the same unique_id; renamed sensor
entity_id; two Envoys registered.

## 3. Producer check

- **Today:** Enpower `reserved_soc` number. BROKEN (10.0/unavailable only since 08-05).
- **After:** Encharge aggregate `reserve_state_of_charge` sensor. Healthy: tracked the cloud number
  within a median ~41 s (B0-D2); read 14 in 10-12/13 while the battery held 14; matched 90 on 10-14
  46 s after the cloud. Goes `unavailable` with the Envoy → existing abstain at `:1570-1571` /
  `:2148-2153`. Residual: a land slower than the 15-min attempt-1 rung still yields an attempt-1 row;
  that is a real slow signal.

## 4. Deliverables

### D1: Resolve the Envoy reserve sensor as the reserve witness
- New private helper `_envoy_reserve_sensor_eid(battery) -> Optional[str]`: anchor =
  `battery._get_entity("battery_soc")`; registry entry must be platform `enphase_envoy` with
  unique_id ending `_battery_level`; serial = prefix; return
  `reg.async_get_entity_id("sensor", "enphase_envoy", f"{serial}_reserve_soc")`. Any exception or
  miss → None, logged INFO once per instance. No caching.
- `_local_entity_for(RESERVE)`: helper result if not None, else today's read. Other branches untouched.
- **Ordering rule (load-bearing):** fallback is on RESOLVABILITY, never on state. Falling back when the
  sensor is unavailable re-introduces the frozen 10 during every Envoy outage.
- Fix docstrings `:370-380`, `:1559-1565`. Add `hw_witness_entity` to the `pending_write_stuck` extras.

**Acceptance**
- **Verify:** registry with sensor + Envoy SOC anchor → helper returns the sensor; without → number.
- **Discriminates:** sensor resolved + `unavailable`, number 10, commanded 10 → watchdog abstains (a
  fallback-on-state build converges on 10); commanded 30 → abstains, no attempt row (wrong build fires attempt 1).
- **Test** (`quality/tests/test_ec_reserve_witness_resolution.py`, real HA `entity_registry` via
  `async_get_or_create`, no stubbed resolver): `test_reserve_witness_prefers_envoy_sensor_via_registry`,
  `test_reserve_witness_falls_back_when_sensor_unregistered`,
  `test_reserve_witness_unavailable_sensor_abstains_not_fallback`,
  `test_reserve_witness_ignores_number_domain_same_unique_id`,
  `test_reserve_witness_anchor_not_envoy_falls_back`, `test_reserve_witness_registry_raises_falls_back`,
  `test_cfg_and_storage_mode_witness_unchanged`.

### D2: Both-direction behaviour on the pending watchdog
Drive `_pending_watchdog_reserve` with a real ledger (`_last_reserve_level`, `_last_reserve_level_at`)
and registry-resolved entities, advancing time past each attempt threshold.

**Acceptance**
- **Direction 1 (false re-send class):** commanded 80, sensor 80, number 10, age 3,700 s → zero
  `pending_write_stuck`, zero NM calls, stand-down not armed, no `write_local_witness_divergence`.
  Today: attempts + CRITICAL `oracle_seen=10.0` + stand-down.
- **Direction 2 (masked real failure, the 10-12/13 case):** commanded 10, sensor 14, number 10 →
  attempts 1/2/3 fire at existing thresholds; attempt 3 CRITICAL with `oracle_seen=14.0` and
  `hw_witness_entity=sensor.envoy_S_reserve_battery_level`; stand-down armed. Today: silent.
- **Policy pin:** commanded 10, sensor 9 → converged (±2 kept by operator ruling).
- **Test:** `test_watchdog_no_alert_when_envoy_sensor_matches_command`,
  `test_watchdog_alerts_when_sensor_diverges_and_frozen_number_equals_command`,
  `test_watchdog_one_point_miss_within_deadband_tolerance_is_converged`,
  `test_pending_stuck_row_carries_hw_witness_entity`, `test_standdown_not_armed_on_matching_sensor`.
- **Live** (post-restart, Envoy online; one-shot DB/entity reads, no soak):
  1. command_trail `hw` equals the live `sensor.envoy_482543015950_reserve_battery_level` state, not a
     constant 10.0 (old code: 10.0 regardless).
  2. No "reserve witness ... not resolved" INFO line in the HA log.
  3. `anomaly_log` reserve `write_local_witness_divergence` rows: daily rate drops from the 13-172/day
     baseline (audit §3) to near zero; any remaining rows show `local_seen` varying, never constant 10.0.
  4. No `pending_write_stuck` row (sev 3 or 4) with `oracle_seen=10.0` unless the sensor itself read
     10 at that time. Any row present carries `hw_witness_entity` = the sensor.
  5. Envoy offline at validation time: no new reserve `pending_write_stuck` rows during the outage
     (abstain); defer items 1/3 and record that in the README table.

## 5. Numbers and knobs
No new behavioural number. Reused unchanged: `_compare` ±2.0, `CONF_PENDING_MAX_ATTEMPTS`, attempt
ages, 3-h stand-down. Kill switch for the watchdog stays `CONF_PENDING_WATCHDOG_ENABLED`. The unique_id
suffixes `_battery_level` / `_reserve_soc` are HA-core protocol strings: rung-1 module constants
`ENVOY_SOC_UNIQUE_SUFFIX` / `ENVOY_RESERVE_UNIQUE_SUFFIX` in `energy_const.py` (not knobs).

## 6. Non-goals
- No new options-flow setting; no change to `energy_reserve_soc_entity`, write routing, failover, or any writer.
- No tolerance or deadband change.
- `write_verification_failed` / `write_reverted` rows (30-75/day on 10-13/10-14): those come from the
  cloud-oracle stall, not this witness; this fix does not remove them.
- Cloud-oracle stall (10-14, `number.iq_battery_hacs_battery_reserve` stuck at 6 for 6.5 h): resilience card
  EC-ENPHASE-CONNECTIVITY-RESILIENCE-1.
- Pending-episode back-off / one-page-per-episode: resilience card.
- Commanded-below-hardware-minimum clamp (commanded 3 vs Enphase min 5, `out_of_range`): separate
  Tier-3 card EC-RESERVE-HW-MIN-CLAMP-1 (write-side clamp-before-stamp; measure the `min` attribute first).
- charge_from_grid / storage_mode witnesses; MQTT stream witness; backfill/relabel of historical rows.

## 7. Tier
**Tier 2, elevated to three framing-disjoint code reviews (Tier 2-DB protocol); one adversarial plan
review before build.** Why not Tier 3: the change is a read-path source swap with no writer, floor,
clamp or tolerance change, so it does not thread a value through the reserve emission sites (INV-W3).
Why elevated: the witness arms/disarms the stand-down skip on the reserve write path (C5) and gates
CRITICAL pages, which is the standing regression-prone-energy rule.
- A: resolution correctness, fallback ordering, §2 break list.
- B: write-path ripple (stand-down arm/disarm, `force_redispatch`, restart with restored ledger,
  governor lint unchanged).
- C (mutation): M1 resolver always returns fallback → prefer + both direction tests RED; M2 fall back on
  unavailable → abstain test RED; M3 drop `sensor`/platform filter → number-domain test RED; M4 drop
  anchor check → anchor test RED; M5 omit `hw_witness_entity` → carries test RED.
Live validation per D2; README write-back of the validated table.

## Plan review 2026-10-18 (Tier-2 adversarial, ura-planner)

Verified by grep and a read-only registry read, not trust.

1. **Consumers re-enumerated: matches §1.2.** `grep -rn "_local_entity_for\|_local_reserve_witness_state"` gives exactly
   `energy_write_verify.py:990` (C1), `:1567` via `:2147` (C2) and `:2498` (C3), and `:2515` (C4). C5 is indirect through
   the stand-down armed in C2. C1 already abstains when the local state is None (`:994-995`), and so does C2
   (`:1570-1571`, `:2148-2153`). No other reader of the reserve witness exists.
2. **Anchor is correct on this house** (`core.entity_registry` + `core.device_registry`, read 10-18):
   - `sensor.envoy_482543015950_battery`: uid `482543015950_battery_level`, device Envoy 482543015950. This is the
     SOC entity `derive_envoy_config` builds (`energy_const.py:1589`).
   - `sensor.envoy_482543015950_reserve_battery_level`: uid `482543015950_reserve_soc`, same Envoy device, enabled.
   - `number.enpower_482348004678_reserve_battery_level`: uid **`482348004678_reserve_soc`**. It has the same suffix,
     so the `sensor` domain filter is load-bearing and is not just defensive. M3 and the number-domain test stay
     mandatory.

   A home whose SOC is not on Envoy (Wigton, or a cloud-only SOC) fails the platform check and falls back to
   today's resolution, so its behaviour is unchanged. That is acceptable and matches INV-W2.
3. **Fallback ordering: one remaining leak, now fixed in the plan (F1, MEDIUM).** When the sensor is registered
   but `disabled_by` is set, `async_get_entity_id` still returns the entity_id, but no state is ever written. The
   witness would then abstain forever and silently turn off the watchdog. **Amend D1:** a registry entry with
   `disabled_by` set counts as *unresolvable*. Fall back and log INFO once. This is a registry property, so it
   does not break the never-fall-back-on-state rule. Add test
   `test_reserve_witness_disabled_sensor_treated_unresolvable` and mutation **M6** (drop the `disabled_by`
   check, so the disabled test goes RED).

   I found no other path that falls back to the frozen number while the sensor is resolvable: `unavailable` and
   `unknown` both return None at `:1570`, and C1 skips at `:995`.
4. **Acceptance discriminates.** Direction 1 and Direction 2 give opposite outcomes under the old code and the
   fixed code. The abstain test separates "fall back on state" from "fall back on resolvability". **Add (F2, LOW):**
   the sensor's `unit_of_measurement` (`%`) must pass `_compare` without `STATUS_UNIT_MISMATCH`. Assert this
   inside `test_watchdog_no_alert_when_envoy_sensor_matches_command` by giving the fixture state the real
   unit attribute.
5. **Operator rulings respected.** No CONF is added, ±2 is unchanged, and the writers and routing are not
   touched. The only new names are the two rung-1 protocol-string constants and one additive extras key. There
   is no mission creep, and §6 keeps the HW-min clamp and the resilience work out of scope.

**Verdict: SHIP-TO-BUILD, with F1 and F2 folded into D1/D2 as above.**
