# URA Architecture Map — Geometry, Coordinators, Primitives, Scope

The structural mental model, on tap with every agent. Its job is to prevent **single-site errors** ("I changed the room path but the value is house-scoped") and **lack-of-understanding errors** ("I treated the HVAC zone as a house zone"). Companion to `URA_CODE_TRACING_METHODOLOGY.md`: that one is how a value FLOWS; this one is where things LIVE and at what SCOPE. Verify against source before betting on a detail — files move.

---

## 1. Geometry: Room → Zone → House

Three config-entry types define the physical model (`const.py:51-54`):

- **ROOM** (`ENTRY_TYPE_ROOM`) — the base unit. A room owns its input sensors (motion/mmWave/BLE, lux, humidity, temp) and its actuators (lights, night/alert lights, fans, covers, a `climate_entity`). Occupancy is computed **per room** from its sensor substrate.
- **ZONE** (`ENTRY_TYPE_ZONE`) + **ZONE_MANAGER** (`ENTRY_TYPE_ZONE_MANAGER`) — a **house zone** aggregates rooms for higher-level decisions (presence roll-up, zone occupancy, some HVAC control).
- **HOUSE** — not a config entry; it's the top aggregation, owned by the `house_state` coordinator (house state = home_day / home_night / away / sleep / vacation, etc.) and the whole-house domains (energy, security, safety).
- **COORDINATOR_MANAGER** (`ENTRY_TYPE_COORDINATOR_MANAGER`) — the singleton entry that constructs and registers the domain coordinators and drives their decision cycles.

### House zones ≠ HVAC zones — spell it out (the classic understanding error)
A **house zone** is a URA aggregation of rooms. An **HVAC zone** is keyed to a **thermostat**. They are NOT 1:1:
- One thermostat-keyed HVAC `zone_N` maps to **MULTIPLE house zones** by design (`hvac_zones.py:245`: "Multiple URA zones can share a thermostat, e.g. Entertainment + …"). Any of the mapped zones being occupied keeps that thermostat active.
- The HVAC zone number comes from the thermostat entity name (`zone_N` → matches the physical thermostat labeling, `hvac_zones.py:201-205`).
- **Compound names on HVAC entities are legitimate** (an HVAC entity spanning two house zones may be named for both). Do not "fix" them.
- **Tonnage is keyed by NUMBER, sliders by NAME**, and the mapping is not in source — the operator is the oracle. (Verified: zone 1 = 4-ton, zones 2 & 3 = 3-ton; a v4.5.11 doc says the opposite and is WRONG.)

**Rule:** before touching an HVAC-zone value, know whether the thing you're changing is thermostat-scoped (one per HVAC zone) or room/house-zone-scoped (fanned out). See `project_house_zones_vs_hvac_zones` memory.

---

## 2. The coordinators (registered domains; `domain_coordinators/`, `coordinator_id`)

Each is a `BaseCoordinator` (`base.py`) with a `coordinator_id` and a priority, registered on the `CoordinatorManager` (`manager.py:127`, `register_coordinator` :389). The big ones and their machinery files:

| coordinator_id | Entry file | Does | Scope |
|---|---|---|---|
| `energy` | `energy.py` (`EnergyCoordinator`) | Battery reserve/charge/discharge, TOU arbitrage, drain-precedence, EVSE pool, solar-follow, grid/circuit accounting, forecasting, write-verify. Machinery: `energy_battery` (strategy + `determine_mode` + `_result`), `energy_pool` (+`energy_pool_owners`), `energy_drain_precedence`, `energy_tou`, `inclement`, `energy_forecast`/`energy_projector`, `energy_billing`, `energy_circuits`, `energy_write_verify`, `energy_const`. | **House** (cost-AND-safety; Tier-3 by default) |
| `hvac` | `hvac.py` (`HvacCoordinator`) | Thermostat control via presets, setpoint governance, excursions/borrows, predictive pre-cool/pre-heat/banking, egress, fans, covers. Machinery: `hvac_preset`, `hvac_override`, `hvac_setpoint` (governed-write chokepoint), `hvac_excursion`, `hvac_predict`, `hvac_zones`, `hvac_egress`, `hvac_fans`, `hvac_covers`, `dynamic_preset`, `preset_overrides`, `hvac_const`. | **Zone (HVAC-zone) + room** |
| `presence` | `presence.py` | Fuses room sensors → zone → house occupancy; trust hierarchy; guest/census; sensor role vs capability. Machinery: `occupancy_substrate`, `sensor_role`/`sensor_capability`/`sensor_exclusion`, `regime_detector`, `chatter_detector`, `presence_fan_recheck`, `_ble_corroboration`. | **Room → zone → house** (cross-cutting fusion) |
| `house_state` | `house_state.py` | The house state machine (home_day/night, away, sleep, vacation) consumed by nearly everything. | **House** |
| `safety` | `safety.py` | Life-safety (smoke/CO reactions, lock checks); highest trust. | **House / cross-cutting** |
| `security` | `security.py` | Perimeter/exterior alerts, circling, cross-corroboration. | **House / perimeter** |
| `optimization` | `optimization.py` (+`optimization_llm`) | The Optimization Coordinator (savings unification, AC-ramp, load decisions); the v5.0.0 capability. | **House** |
| `music_following` | `music_following.py` | Music follows occupancy across rooms. | **Room → house (cross-cutting)** |
| notifications | `notification_manager.py` | The NM — routing/paging/repage/safe-word (recipients, channels). | **Cross-cutting** |
| weather | `weather_manager.py` | Weather provider manager (multi-provider, staleness). Feeds `inclement`. | **House** |
| diagnostics | `coordinator_diagnostics.py`, `anomaly_event.py` | Anomaly detection wired to NM (the in-code trip-wires that replace soak-watching). | **Cross-cutting** |
| `coordinator_manager` | `manager.py` | Constructs/registers/sequences the domains; the setup-order authority (Envoy-boot-incident territory). | — |

(Not every file is a registered coordinator — many are machinery of the domains above. `signals.py` is the dispatcher bus, not a coordinator.)

---

## 3. The abstractions we built to make hard things consistent — NAME THEM

These are the reusable primitives. Consistency errors come from NOT using them (hand-rolling a second path). When you touch their domain, route through the primitive.

- **The governed-write chokepoint** — `hvac_setpoint.emit_set_temperature` / `emit_set_preset_mode` / `emit_set_hvac_mode`. ONE governed primitive for all three thermostat axes, so every emission passes the same arrester/comfort-delay/idempotency guard. Never call `climate.set_*` directly from HVAC code.
- **The owner-set / peer-hold pattern** — `energy_pool_owners.EV_REGISTRY` + `EVChargerController._stronger_peer_holds`. Twelve owners (TOU, battery_drain, arbitrage, load_shed, fill_priority, blind_window, DP, excess_solar, …) claim membership on ONE physical EVSE switch; the registry is the single source for pruning/peer-checks/persistence/classification. Adding a new controller = a new owner, not a new writer.
- **The excursion / borrow primitive** — `hvac_excursion` (`hvac_excursion_state` / `hvac_excursion_events`, borrow *kinds*: banking, pre-cool, compromise, egress, off-phase-ceiling). A bounded, book-kept setpoint excursion that must have an ending that restores a preset. Migrate a new raw-setpoint writer AS A KIND; don't hand-roll a second restore path.
- **The reserve-floor clamp** — `energy_battery._floor_reserve`. The single guard that can only RAISE an emitted reserve (Bug Class #53 one-missed-site closure). Every reserve emission inside a hold branch routes through it.
- **The value-stamp + `command_trail`** — the emitter stamps the composed value (`_offpeak_drain_branch_target`); consumers read it verbatim; `command_trail` (hold_owner / effective_desired / live_desire / cloud_oracle / ages) is the AUTHORITATIVE decision telemetry. Diagnose off this, not display prose.
- **`_result`** — the ONLY correct emit path out of `energy_battery.determine_mode`. Every reachable branch returns via `_result` (state-matrix closure).
- **The write-verify machinery** — `energy_write_verify` (async_call_later with supersession + `cancel_all` on teardown). Surface-keyed; a new write target must register a surface to be verified.
- **The Fan Policy Oracle** — `fan_policy_oracle.FanPolicyOracle` / `RoomFanState`. The cross-cutting authority for fan decisions across rooms; `hvac_fans` and `presence_fan_recheck` delegate to it. Fans are the canonical **cross-cutting** example (a fan lives in a room but is governed house-wide).
- **The occupancy substrate + sensor role/capability split** — `occupancy_substrate` holds the fused per-room signal; `sensor_capability` = hardware KIND (mmWave/PIR/BLE/camera), `sensor_role` = analytic FUNCTION. Do not conflate kind with role.
- **The signal bus** — `signals.py` `SIGNAL_*` + HA dispatcher. Cross-coordinator events flow here; a producer/consumer trace often crosses a dispatch.
- **`BaseCoordinator`** — `base.py`: the common id/priority/setup/teardown contract every domain inherits.

---

## 4. Scope model — the anti-single-site rule

Before changing a value, classify its SCOPE and make sure you change every site AT that scope:

- **Room scope** — occupancy, room lights/night-lights/alert-lights, room climate-follow, room energy sensors. A room fix that forgets the zone/house roll-up is a single-site error.
- **Zone scope** — house-zone aggregation, HVAC-zone thermostat control (remember: HVAC zone fans out to multiple house zones).
- **House scope** — house_state, energy (battery/grid/TOU), security, safety, optimization, weather. A "room" change to a house-scoped value (e.g. a drain floor) is a category error.
- **Cross-cutting** — **fans** (room-resident, house-governed via the Fan Policy Oracle), presence fusion (room→zone→house), notifications, signals, anomaly/diagnostics. These span the geometry; a change here ripples across scopes — enumerate every scope it touches (context-wide scoping), not just the tier you're standing in.

**The two errors this map exists to kill:** (1) editing one emission/decision site of a multi-site value (pair this with the tracing methodology's emission-site enumeration and Bug Class #53); (2) reasoning about a value at the wrong scope — treating an HVAC zone as a house zone, a house-scoped floor as a room knob, or a cross-cutting fan as room-local. When in doubt, name the coordinator that OWNS the value and the scope it decides at, before you touch it.
