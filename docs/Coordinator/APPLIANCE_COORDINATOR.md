# Appliance Coordinator (URA)

**Card:** APPLIANCE-MGMT-REFINE-1 · **Slice:** v1a (Tier-2-DB / regression-prone → 3 framing-disjoint reviews)
**Status:** v1a scaffolded (passive census, read-only). v1b/v1c/v1d NOT built.

---

## Purpose

A **first-class, PASSIVE** domain coordinator that produces a **read-only appliance census**. Peer of presence / safety / energy / hvac / music-following, not a hidden helper. It **commands nothing** — no `hass.services.async_call`, no `hass.states.async_set`, ever.

The census unions three discovery sources:

1. **SPAN circuits** — read (do NOT construct) the existing `SPANCircuitMonitor._circuits` on the Energy coordinator. Registration order (see `__init__.py` after `:3567`) guarantees Energy is up first.
2. **Operator-declared records** — the `CONF_APPLIANCE_RECORDS` list on the CM entry options (default `[]`). v1a reads; the flow WRITER is v1b.
3. **URA-owned entities** — every ROOM entry's appliance-relevant keys (`fans`, `humidity_fans`, `power_sensors`, `climate_entity`, `room_media_player`, `lights`, `covers`). Modeled on `presence.py:7567 _collect_presence_input_entities`.

De-dup discipline:
- Every `entity_id` claimed by a declared record is suppressed in sources (2) and (3) — invariant **(i) entity-exclusivity**.
- Duplicate declared claims resolve as **real** last-wins: the later record wins the entity_id and it is **removed from the earlier record's role lists** (not just a warning). The v1b flow validator will reject-at-save.
- **NO device_id auto-collapse in v1a.** `device_id` is not a reliable appliance boundary. A single LG ThinQ washer registers as one HA device with many entities (control + energy + state); a 2-channel Shelly registers as one device with two independent appliances. Collapsing on `device_id` either shatters a real appliance across records or silently merges two distinct appliances into one — both are unsafe. Source (3) therefore emits **one record per unique unclaimed `entity_id`** (dedup by `entity_id` ONLY). Grouping across entity_ids is an **operator decision** captured in source (1) declared records — never a heuristic. The Tier-2-DB Reviewer A1 finding (2026-09-13) is the record of this decision.
- Cross-integration bridging is **operator-declared only** (fragile-pattern #2 — no reliable cross-integration join key).
- Every unclaimed entity → exactly one `other` record — invariant **(i) no-drop**.

Freshness knob: **`APPLIANCE_STALE_MAX_AGE_S`** (module constant, rung 1; see `appliance_const.py`). Not operator-tuned.

## Invariants (falsifiable)

- **(i) De-dup / no-drop:** every `entity_id` appears in exactly one census record. Each declared group produces exactly one record and suppresses same-entity records from sources (2)+(3). Every unclaimed entity produces exactly one `other` record.
- **(ii) Commands nothing:** patched `hass.services.async_call` and `hass.states.async_set` register `call_count == 0` across `async_setup()`, `evaluate()`, `async_teardown()`, and `resolve_census()`.

## Wire-in anchor

`sensor.ura_appliance_census.extra_state_attributes["appliances"]` reads from `ApplianceCoordinator.resolve_census()`. Neutering that call site (`return {"appliances": [], "stale_max_age_s": None}` or short-circuit) turns `test_wire_in_anchor_appliance_census` RED under the mutation drill (`PYTHONDONTWRITEBYTECODE=1`, `find … -name __pycache__ -exec rm -rf {} +`).

## Files

- `custom_components/universal_room_automation/domain_coordinators/appliance.py` — the coordinator (evaluate→[], tracked task set, passive setup, three-source resolver).
- `custom_components/universal_room_automation/domain_coordinators/appliance_const.py` — `APPLIANCE_STALE_MAX_AGE_S` + per-appliance record schema constants + `URA_ROOM_APPLIANCE_KEYS`.
- `custom_components/universal_room_automation/const.py` — `CONF_APPLIANCE_COORDINATOR_ENABLED` (default True), `CONF_APPLIANCE_RECORDS` (default `[]`), `COORDINATOR_ENABLED_KEYS["appliance"]`.
- `custom_components/universal_room_automation/__init__.py` — construct + `register_coordinator` **AFTER** the Energy branch (see the `Appliance Coordinator disabled via config` log guard).
- `custom_components/universal_room_automation/switch.py` — `CoordinatorEnabledSwitch` entry under the CM entry.
- `custom_components/universal_room_automation/sensor.py` — `ApplianceCensusSensor` (read-only) registered under the CM entry.
- `custom_components/universal_room_automation/_devices.py` — `DEVICE_NAMES` + `DEVICE_MODELS` + `PARENT_MAP` entries for `appliance_coordinator` (nests under `coordinator_manager`).

## Non-goals (v1a)

- No control actuation. No breaker on/off. No CROSS-integration auto-join. No auto-added plugs. No cost or `energy_used_kwh` attribution (v1c). No `AnomalyDetector` and no observability meta-test rows (v1d). No onboarding flow (v1b). No menu step / strings.json entry beyond the switch fallback name — see v1b for the menu label + step block + `CONF_APPLIANCE_RECORDS` reload-suppression key.

## Fragile patterns explicitly avoided

- `CircuitInfo.controllable` NOT read (dead stub).
- No cross-integration `device_id`/MAC/model join. Intra-integration `device_id` grouping only.
- No `media_player` platform allow/deny literals.
- No name-string model parsing.
- No `RestoreEntity` / midnight-snapshot for state (records persist through CM options — v1b).
- No untracked `async_create_task` — tracked in `_pending_tasks`, cancelled in `async_teardown` **before** anything else.
- Not gated on Energy health — SPAN circuit read is lazy per-tick and returns empty if the monitor is absent.

## Downstream (future slices)

- v1b: onboarding options-flow surface + `OPTIONS_RELOAD_SUPPRESS_KEYS` extension + strings.json (menu label + step block) + translations parity.
- v1c: `energy_used_kwh` + mix-aware `cost_attributed`; reuse `_get_effective_rate_kwh` + `PeakAvoidanceTracker` guard; per-appliance attribution is NEW.
- v1d: `AnomalyDetector` + `ApplianceAnomalySensor` + `CONF_APPLIANCE_ANOMALY_SENSITIVITY` + observability meta-test wiring (the two module constants + four `test_v465_observability_gap.py` edits).
