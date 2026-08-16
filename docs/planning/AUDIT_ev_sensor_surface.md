# AUDIT: EV Sensor Surface (charge-rate dupes, dead Emporia, constant 2.9 kW Outlets)

Date: 2026-08-16. Evidence-first audit of three operator questions. Live HA + recorder +
repo source cited throughout. No code changed by this audit; small-item specs below.

---

## Q1 — `sensor.ura_energy_coordinator_ev_charge_rate_garage_a/_b`: REMOVE (functional dupes)

**Source:** `sensor.py:10939` (`EnergyEVChargeRateASensor`) / `:10970` (`...BSensor`), registered at
`sensor.py:315-316`. `native_value` → `energy.evse_garage_a_power` (`domain_coordinators/energy.py:9750/:9756`)
→ `_get_state_float(DEFAULT_EVSE_GARAGE_A/B_POWER_ENTITY)` (`energy_const.py:254-255`) =
`sensor.garage_a/b_power_minute_average` — the **Emporia EVSE power sensors**.

**Why unknown:** those Emporia upstreams are `unavailable` (`restored: true`) since the Emporia
outage (Q2) → `_get_state_float` returns None → sensor state `unknown`. Not never-wired; dead upstream.

**Dupe check:** `ev_charging_status` per-EVSE attrs read the *same* entity
(`energy_pool.py:168-183`, `"power": "sensor.garage_a_power_minute_average"`) via `_get_evse_state`
(`energy_pool.py:650`), **plus** a v4.2.19 switch-status fallback the standalone sensors lack. The
status attrs are therefore a strict superset. Live confirmation: `ev_charging_status.garage_a.power`
present (0, `power_source: unavailable`) while the standalone sensors sit `unknown`.

**Consumers (grepped before verdict):**
- Live HA: `grep -r ev_charge_rate /config/.storage /config/*.yaml` → only `core.entity_registry`.
  No dashboards, no automations. The v8 EV detail card was redesigned 2026-08-16 to read
  `ev_charging_status` attrs precisely because these sensors were dead (kanban card, `kanban.data.yaml:576`).
- URA repo: only the class defs + docs (`docs/dashboards/ura_v8_energy_ev_detail_card.md:73-74` — the
  *old* pre-redesign template; `ENERGY_COORDINATOR_PLAN.md`, `README_v3.7.7.md`, user manual).
- PWA (`~/Code/ura-dashboard-pwa`): zero hits.

**Verdict: REMOVE.** Small item for next deploy:
1. Delete `EnergyEVChargeRateASensor`/`BSensor` classes (`sensor.py:10939-10998`) and their two
   registrations (`sensor.py:315-316`).
2. Optionally remove the two registry orphans post-deploy (HA UI or `ha_remove_entity`).
3. Doc sweep: update `docs/user-manual/ENERGY_COORDINATOR.md:603` and the v8 card doc rows that still
   reference them. `evse_garage_a/b_power` properties in `energy.py` become caller-less → delete too
   (grep confirmed no other callers).

Tier 1 hotfix; no behavioral consumer exists.

---

## Q2 — Dead Emporia entities: ALL 178, integration-level, boto3 dependency conflict

**Scope:** entity registry has **178 emporia_vue entities** (174 sensor, 2 switch, 2 number) — EVSE
Garage A/B (switch/power/energy/status/current-limit), Mains Vue3 (PanelWall), and the 16-circuit
Sub Panel Vue 3 B set (Kitchen/Bedroom/Media/Exercise Plugs, Forced Air, Laundry…). **Every one is
`unavailable`.** (The live "emporia" entities that still report — `device_tracker.emporia*`,
`*_rx/_tx`, `span_panel_mains_emporia_vue_*` — are UniFi and SPAN entities, not emporia_vue.)

**Since when:** recorder statistics for `sensor.garage_a_power_minute_average` show real data through
the **2026-08-11** day bucket (mean 285 W, max 10.1 kW), nothing after → dead since ~Aug 11-12.

**Root cause (from error_log, not guessed):**
```
ERROR homeassistant.util.package: Unable to install package boto3==1.37.1:
  No solution found: Because you require boto3==1.37.1 and boto3==1.42.97 ...
ERROR homeassistant.setup: Setup failed for custom integration 'emporia_vue':
  Requirements for emporia_vue not found: ['boto3==1.37.1']
```
Config entry `01JNT2EV3961MYXDZKF54Q5W99` state = **`not_loaded`**. Installed emporia_vue v0.12.2
hard-pins `boto3==1.37.1` (manifest verified on host); something else in the env (HA core constraint
after a core update) requires `boto3==1.42.97`. Integration-level outage (amcrest-mDNS-class), not
device-level — all three Vue devices are on-WiFi (`device_tracker.emporia*` = home).

**Fix (in-band, no code):** HACS shows **v0.12.3 available, `pending_update`** (released 2026-08-08).
v0.12.3 manifest verified: `boto3>=1.37.1,<1.43.0` — compatible with 1.42.97. →
**Update emporia_vue to v0.12.3 in HACS, restart HA.** Entry reload alone will NOT fix it (the
requirement install fails at setup).

---

## Q3 — Constant 2.9 kW on Outlets: by-design estimate, not a stale sensor

**Mechanism:** the v8 card's Outlets row totals the per-plug `power` attrs on
`ev_charging_status`. The Moes garage plug is **switch-only — no power entities exist**
(verified: only `switch.smartplug_moes_wifi_garagealeftfront_socket_1..4` + child-lock/behavior).
URA's smart-plug snapshot (`energy_pool.py:3560-3625`) therefore emits a fixed estimate:
`estimated_power = L1_ESTIMATED_POWER_W if is_on else 0` with `power_source: "switch_status"`,
where `L1_ESTIMATED_POWER_W = 1440` (`energy_const.py:890`, 120 V × 12 A L1 assumption).
Two sockets on → 2 × 1440 = **2880 W ≈ 2.9 kW, constant**. Not stale, not cached, not a wrong
source entity — there is no measured source wired at all. (Live now: sockets 1 & 2 on, each 1440.)

Real outlet draw *is* measured by Emporia — the garage circuits on the dead sub-panel/EVSE monitors —
which is why the mismatch is visible to the operator, but URA never consumed an Emporia circuit for
the L1 plugs.

**Fix:**
- **Config/UX now (no deploy):** the card should render `power_source: switch_status` rows as an
  estimate ("~1.4 kW est") or show state only — dashboard-side template change.
- **Small code item (next deploy, after Emporia is back):** extend `_plug_config` to accept an
  optional per-plug `power` entity (mirroring EVSE `_get_evse_state`'s sensor-first/fallback
  pattern) and wire the appropriate Emporia garage circuit sensor; keep `L1_ESTIMATED_POWER_W`
  as fallback. Knob ladder: entity ids → config; the 1440 W constant stays a module constant.

---

## Verdicts
1. **charge_rate A/B: REMOVE** — same upstream as `ev_charging_status` power attrs minus the
   fallback; zero consumers. Two-class + two-line deletion next deploy.
2. **Emporia: integration-level outage since ~2026-08-11** — v0.12.2's `boto3==1.37.1` pin
   unresolvable against env's 1.42.97; all 178 entities down, devices online. Fix: HACS update to
   v0.12.3 (pin relaxed, verified) + restart.
3. **Outlets 2.9 kW: designed constant** — 2 × `L1_ESTIMATED_POWER_W` (1440 W) switch-status
   estimate; Moes plugs have no power sensing. Label as estimate now; optionally wire Emporia
   circuit as per-plug power source post-recovery.
