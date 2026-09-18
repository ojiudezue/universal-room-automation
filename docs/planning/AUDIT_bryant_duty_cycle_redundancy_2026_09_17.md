# AUDIT — Is URA's D5 duty-cycle "protection" redundant with Bryant/Carrier native compressor protection?

**Date:** 2026-09-17 · **Method:** read-only research (ha_carrier source + carrier hardware literature) ·
**Feeds:** `HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1`, `HVAC-D5-KNOBS-TO-RUNG-3-1`, new `HVAC-D5-REGROUND-ON-ODU-VAR-1`.
Companion to `AUDIT_hvac_duty_cycle_protection_2026_09_17.md` (which first flagged D5 as un-grounded).

## VERDICT

**PARTIALLY REDUNDANT.** The compressor is already protected natively by the Infinity/Evolution
control board and the equipment's own delay-on-break logic. URA's D5 force-to-`away` does **NOT**
protect the compressor — widening the setpoint band changes *when* conditioning is demanded, it does
not lengthen any compressor off-time. **D5 is pure energy-shed policy wearing a compressor-protection
name.** The prior audit's "zero Bryant/Carrier grounding" claim **HOLDS**.

**Chosen path: option (b)** — reduce D5 to an explicit, operator-tunable energy-shed lever, drop the
protection pretense (rename the reason string), and gate it on the step-4-B fused occupancy signal.
NOT (c) blanket-remove: D5 is still a legitimate (bluntly-implemented) load-shed behavior during EC
coast/shed; deleting it silently drops that energy policy. **(d)** re-grounding on a real readable
duty signal is parked as a follow-up (the signal exists — see below — but Marginal-Benefit says
reframe+gate captures most of the value now).

## Evidence — `ha_carrier` / `carrier_api` surface

Installed: `/Users/okosisi/ha-config/custom_components/ha_carrier` v2.28.2, wrapping `carrier-api==3.6.0`
(`iot_class: cloud_push`, codeowner @dahlb).

- **No** min-off-time / CPH / short-cycle / lockout field anywhere in the integration. The only
  protection-adjacent code is the integration's OWN post-write debounce
  (`carrier_data_update_coordinator.py:154,206`, "keep their own protection period") — unrelated to
  equipment cycle protection. The onboard anti-short-cycle timer lives in the control board / equipment
  and is **not published to the cloud API**.
- **BUT readable real-duty fields DO exist** (this refines the prior audit, which assumed the 20-min
  `hvac_action` integral was the only available signal):
  - **`status.outdoor_unit_operational_status`** → sensor **"ODU Var"** (`sensor.py:788-834`,
    `OutdoorUnitVarSensor`): the variable-capacity outdoor-unit **% output** (PERCENTAGE, MEASUREMENT);
    `off`/`dehumidify` → 0%, else the numeric %. This is the actual compressor modulation level.
  - **"ODU Status" / "IDU Status"** (`sensor.py:735-791`) via `_unit_status_attributes = unit.as_dict()`.
  - **`status.airflow_cfm`** → "Airflow" (`sensor.py:667-693`); **`status.static_pressure`** →
    "Static Pressure" (`sensor.py:701-727`).
  - Per zone: **`zone.conditioning`** (`climate.py:207`), **`zone.stage_status`**
    (`entry_level_climate.py:153-158`) — the reported heat/cool stage URA already integrates via `hvac_action`.

## Evidence — Bryant/Carrier native protection (hardware literature)

- Anti-short-cycle protection is standard, equipment/control-level, independent of any external
  automation; industry-standard minimum-off ≈ 5 min / 300s (delay-on-break). (hvac-talk short-cycle
  thread; VIOX time-delay-relay guide; ATC AC-505-5 delay-on-break timer.)
- The installed class of hardware — Carrier Infinity / Bryant Evolution **variable-speed** compressors
  (24VNA9/26VNA1/27VNA0; Bryant 186CNV/288BNV) — **modulate compressor speed and run long at low speed
  rather than cycling** (humidity control comes from *not* cycling). The Infinity control **logs
  short-cycling as a fault and restarts after a delay** — the board owns cycle protection.
  (carrier.com 24VNA9 / 26VNA1 product pages; Bay Area HVAC Infinity-faults blog; JustAnswer Infinity
  short-cycling.)

## Recommendation detail (option b — the build spec)

1. **Rename the ledger reason** `runtime_exceeded` → `energy_shed_cap_reached`
   (`hvac.py:2200-2201`, allow-list `hvac.py:2168-2178`, precedence test). Per Single-User-No-Back-Compat:
   remove `runtime_exceeded` outright, no alias. This is the operator-facing surface that manufactures
   the "compressor protection" misconception.
2. **Occupancy gate** — consume step-4-B fused `hvac_occupied` before firing/consuming the forced-away
   at `hvac.py:1928`; skip force-away for a fused-occupied zone **unless** `energy_constraint_mode == shed`
   (shed dominates); log the deferral as `energy_shed_cap_deferred_occupied`. Resolves the direct
   competition with step-4-B INV-1 (no sleeping resident's own bedroom forced to `away`).
3. **Knobs to Rung 3** (`HVAC-D5-KNOBS-TO-RUNG-3-1`): promote `DUTY_CYCLE_WINDOW_SECONDS/COAST/SHED`
   (`hvac_const.py:396-399`) to `Number` entities, `0` = documented kill switch. These are shed-policy
   knobs, NOT safety bounds — Rung 1 is wrong for them.

## Cleanup / fixups implied

- "Zero Bryant grounding" **CONFIRMED** — no manufacturer spec / CPH / min-off anywhere in
  `hvac_const.py:396-399`, the README, or code comments.
- `hvac_const.py:561 DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT = 2  # compressor protection cap` is the
  ONLY correctly-named compressor-protection mechanism and is unrelated to D5 — **leave it**; it
  reinforces that D5's naming is the anomaly.
- Verify `window_start` restore across reload (`hvac_zones.py:685-700`) — Tier-1 contingent
  (`HVAC-D5-WINDOW-START-RESTORE-1`).
- **(d) follow-up:** re-ground D5 on ODU Var % / `stage_status` instead of the coarse 20-min
  `hvac_action` integral → new card `HVAC-D5-REGROUND-ON-ODU-VAR-1` (parked; trigger = if reframe+gate
  leaves duty mis-estimation visible in the ledger).

## Confidence / not-verified (No-Fabrication)

- **High:** D5 is un-grounded energy policy; `ha_carrier` exposes ODU Var %/stage but no min-off field
  (read source directly); native anti-short-cycle is standard equipment-level protection (multi-source).
- **Could NOT confirm from primary Carrier service literature:** the exact onboard minimum-off value for
  the specific installed unit (the ~5 min figure is industry-standard trade sourcing, not a Carrier
  service-manual quote). Did not read `carrier-api==3.6.0` library source (not pip-installed) — but the
  integration's own field accesses show no min-off/CPH is surfaced regardless.
- **Did not live-verify** which ODU Var / stage values the house thermostats currently report (not
  required for the redundancy verdict; needed only if (d) is built).
