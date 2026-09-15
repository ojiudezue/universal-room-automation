# PLANNING — Appliance capability, v1 (APPLIANCE-MGMT-REFINE-1) — REWRITTEN post-sweep

**Card:** APPLIANCE-MGMT-REFINE-1 · **Date:** 2026-09-14 (rewrite) · **Tier:** 3 (staged; each slice carries its own tier)
**Status:** rewritten after a deep coordinator-pattern + prior-art sweep (operator-ordered: zero duplication, most-mature patterns only, avoid unreliable ones). Supersedes the pre-sweep draft that both Tier-3 plan reviews returned FIX-PLAN-FIRST on.
**Inputs:** two Tier-3 plan reviews (record `docs/reviews/code-review/APPLIANCE-MGMT-REFINE-1_plan_review.md`) + three read-only sweeps (pattern-maturity, zero-duplication reuse map, extend-vs-new adjudication).

---

## Decision: a FIRST-CLASS `ApplianceCoordinator` (architecture, not code-size)

**This is an architecture decision, not a "how much code" decision (operator, 2026-09-14).** The question is:
does appliance management appear as a first-class coordinator under **'Add Coordinator'**, and how does it
integrate with the **anomaly subsystem** — independent of how much of its internals are reused. The answer
is **yes, first-class**:

- **It appears under 'Add Coordinator'** — its own entry in the CM options menu (`config_flow.py:3334`), its
  own `CONF_APPLIANCE_COORDINATOR_ENABLED` key + enable switch, its own device. It is a peer of presence /
  safety / energy / music-following, not a hidden helper.
- **It wires into the anomaly subsystem like every coordinator** — its own `AnomalyDetector` + a first-class
  `sensor.ura_appliance_anomaly` + its own NM identity (operator's original Q1 requirement). Appliance
  anomalies are NOT routed through the Energy coordinator's surface.

**Reuse is an INTERNAL implementation detail, not the architectural identity.** The coordinator *reads* the
existing `SPANCircuitMonitor` circuits and reuses the mature measure/anomaly/cost primitives — but that
reuse lives behind the coordinator's own identity; it does not make appliances an Energy-internal concern.

Rejected architectures (both fail the first-class test): (a) forcing appliances into `SPANCircuitMonitor`'s
EXTRA path — appliances would be invisible under 'Add Coordinator' and anomalies would surface as
*circuit* anomalies under Energy; also pollutes a Tier-3-delicate power-only engine (`CircuitInfo` has no
room/domain/control/state, drops non-float `media_player` state at `energy_circuits.py:282-284`). (b) a
sibling monitor inside the 10k-line `EnergyCoordinator` tick — same invisibility, plus unnecessary coupling.

Chosen: **a first-class, passive `ApplianceCoordinator`** — passive meaning `evaluate()→[]` (it observes,
it does not drive actions), NOT meaning second-class. **Template = `music_following.py`** (the sweep's
gold-standard passive coordinator: event-driven, `AnomalyDetector`, tracked-teardown, backed by the
observability meta-test — and itself a first-class coordinator under 'Add Coordinator'). **Registered like
`__init__.py:3178-3237`.** **Persisted via the `metric_baselines` DB table** through `AnomalyDetector`
(`coordinator_diagnostics.py:1251-1345`, table `database.py:1050`) — the most mature persistence path.

---

## Zero-duplication reuse map (the spine — REUSE, do not rebuild)

| Capability | REUSE (file:line) | Class |
|---|---|---|
| Passive coordinator lifecycle template | `music_following.py:1-15,238-687` | model on |
| Registration (enable-key/switch/device/register) | `__init__.py:3178-3237`; `COORDINATOR_ENABLED_KEYS` const.py:2455; `register_coordinator` manager.py:388; `_coordinator_device_info` base.py:200 | copy shape |
| Power/energy ingestion (any metered appliance) | `SPANCircuitMonitor` EXTRA_ENTITIES Tier-2 path `energy_circuits.py:196-212` (source-agnostic already — takes any live float sensor) | REUSE-AS-IS |
| Operator add-path for extra power sensors | `CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES` energy_const.py:971 → config_flow.py:5457 → energy.py:517 | REUSE-AS-IS |
| De-dup / exclude a double-counted feed | `CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES` energy_const.py:973; exclusion block energy_circuits.py:214-219 | REUSE-AS-IS |
| Smart-plug control+measure (dumb loads) | `SmartPlugController` energy_pool.py:3361; no-meter estimate `L1_ESTIMATED_POWER_W` energy_const.py:961 | REUSE-AS-IS |
| TV/AV state (no power sensor) | room `media_player` URA already tracks: `CONF_ROOM_MEDIA_PLAYER` const.py:83, deadness sensor.py:1753 | REUSE reads |
| Anomaly detection (z-score + sudden-zero) | `check_anomalies` energy_circuits.py:267-395 (detection only) + emit/NM seam energy.py:6407-6456 | REUSE-AS-IS (both halves) |
| Anomaly emit + NM | `AnomalyEvent`/`save_anomaly_event` (domain_coordinators/anomaly_event.py:155, database.py:6956); `fire_stuck_signal` domain_coordinators/_stuck_signal_nm.py:165 | REUSE-AS-IS |
| Cost / TOU rate | `_get_effective_rate_kwh` energy_billing.py:29; `PeakAvoidanceTracker` apportionment energy_billing.py:478-675 (double-count guard :605-617) | REUSE (display-only) |
| "URA-owned shows up" collector | `_iter_configured` typed-yield sensor.py:1829 + key constants :1747-1756, driven over entries like `_collect_presence_input_entities` presence.py:7567 | REUSE skeleton |
| Onboarding N-record add/edit/remove flow | zone-picker `__getattr__` dynamic menu config_flow.py:2987,8782 + EntitySelector step config_flow.py:5457 | REUSE pattern |
| No-CM-reload on iterative saves | **EXTEND** `OPTIONS_RELOAD_SUPPRESS_KEYS` __init__.py:6612 (add appliance keys) | EXTEND |
| Rename-stable identity | `CircuitInfo.unique_id` + `_lookup_unique_id` energy_circuits.py:65,116-140 | REUSE-AS-IS |
| Persistence | `metric_baselines` table via AnomalyDetector coordinator_diagnostics.py:1251 | REUSE pattern |

## Fragile patterns — DO NOT use (operator: avoid the ones we cannot rely on)

1. **`CircuitInfo.controllable` — DEAD STUB.** Init `True`, never assigned anywhere. Do NOT read it as truth; if a controllable signal is needed, resolve it from the breaker/switch entity explicitly.
2. **Cross-integration `device_id`/`via_device_id`/MAC/model joins — NO reliable key exists** (registry: one config-entry per device, `via_device` parenting races kanban.data.yaml:2499/3252/3307). De-dup is **operator-declared only**, never auto-joined.
3. **`media_player` platform allow/deny literals** — heuristic default at most, never ground truth (306 media_players, ~10× noise; `airplay` isn't even a platform).
4. **Parsing model from name strings** (the `IOT_HOSTNAME_PREFIXES` const.py:3110 antipattern; the v5.12.0 SPAN re-key deliberately moved OFF friendly_name).
5. **RestoreEntity for coordinator state / midnight-snapshot accumulators** — documented restart-wipe history (energy.py:1897-1953,2324; B-HIGH-1/2). Use `metric_baselines`.
6. **Untracked `async_create_task`** (v4.6.3 A5 class) — track in a set, cancel in teardown (music_following.py:362-367).
7. **Gating setup on another integration's health** (SPAN/Envoy/cloud availability). A passive census must degrade gracefully, never block on a source being loaded.
8. **`CONF_ENERGY_CIRCUIT_INTEGRATIONS` energy_const.py:970 — dead stub, do NOT repurpose** as the appliance key.

## The ONE genuinely-new structure: the per-appliance record
Nothing today expresses multi-entity-ref membership (`plug_config` is single-key+bool at __init__.py:3453). The one new config structure:
```
appliance = {
  name, functional_domain,            # media_av|kitchen|laundry|climate|cold_chain|water|cleaning|other
  room,                               # optional
  entity_refs: {power:[], energy:[], control:[], state:[]},   # any role may be empty
  source_tags: [span|emporia|thinq|smartplug|native|ura_config],
}
```
A TV = state+control, no power. A warming drawer = power, no control. **Operator grouping into one record is the de-dup mechanism** (collapses the ≤3 shadows). URA-owned entities are *read in* as a discovery source and shown; net-new entities are *added* through the flow. Measuring **plugs only** (not Shelly relays generally), and **never auto-added** — plugs enter only via the add-path (operator directive 2026-09-14).

---

## Staging (each slice its own tier + review; ship value at each)

### v1a — Appliance census (Tier 2-DB) — the first shippable slice
- **Scaffold** the passive `ApplianceCoordinator` (all 11 registration sites, below) modeled on music_following.
- **Discovery (read-only):** union of (1) SPAN circuits (read the existing monitor's `CircuitInfo` set), (2) operator-declared appliance records, (3) URA-owned entities via the `_iter_configured` collector. Freshness-gated; degrades if a source is absent.
- **Resolver:** collapse shadows **only** by operator-declared grouping (no auto-join). Unmapped entity = visible, `other`/uncategorized, never dropped.
- **One read-only sensor** `sensor.ura_appliance_census` with per-appliance attributes (name, domain, roles, source_tags, current power/state, freshness).
- **Falsifiable invariants:** (i) no physical appliance yields >1 census record under any combination of the 3 sources **given the operator grouping**; (ii) the coordinator commands nothing — **no service call in any write domain against any entity** (enumerated: turn_on/off, number.set_value, select.select_option, switch — closing the MED-9 hole).
- **Persistence:** observed energy-behaviour classification + any baselines via `metric_baselines`. **Restart acceptance criterion mandatory.**
- **Acceptance (discriminating):** a URA room fan appears with `source_tags:[ura_config]` and requires NO onboarding step (URA-owned ≠ re-config); a net-new TV is absent until added; a triple-covered appliance yields ONE record; **wire-in anchor** — the census reads the live coordinator output, and neutering the resolver call turns a test RED (not a fixture-only assertion).

### v1b — Categorization + onboarding flow (Tier 2)
- The per-appliance record's options-flow surface, built on the zone-picker `__getattr__` dynamic-menu + EntitySelector step. Add/edit/remove + a remove-path for a vanished entity.
- **EXTEND `OPTIONS_RELOAD_SUPPRESS_KEYS`** with the appliance keys + in-place re-read; acceptance: an onboarding save does NOT reload the CM (oracle: sibling-entity `last_changed` invariant).
- 4-axis categorization (functional-domain primary — what it does, independent of add-vector) + strings.json/en.json for every new step.

### v1c — Energy + cost (Tier 3 — money numbers)
- `energy_used_kwh` (unambiguous) **separate from** mix-aware `cost_attributed`.
- **REUSE `PeakAvoidanceTracker` apportionment** (energy_billing.py:544-637) + `_get_effective_rate_kwh`; label it **pro-rata** (not "marginal") and carry the **"display-only, not billing-grade"** disclaimer. Cite Envoy ids `sensor.envoy_482543015950_*`.
- **Adjudicate the genuinely-open question in-plan:** house-level served-locally → per-appliance attribution rule (which appliance's kWh was the grid-served fraction when several drew at once). Do NOT leave this to the builder.
- **Discriminating acceptance:** 100%-solar → cost≈0 AND (paired) 100%-grid → cost≈kwh×import_rate; a mixed case between. (cost≈0 alone is non-discriminating vs a dead pipeline.)

### v1d — Anomaly (Tier 2-DB)
- Thin `AnomalyDetector` + `sensor.ura_appliance_anomaly` (music_following wiring).
- Appliance anomalies as **EXTEND-not-new** vs `energy_circuits.py` (cold-chain-power-loss/tripped-breaker + z-score already exist): add a `cold_chain` **category tag** to the existing detector rather than a second path, and state the **double-alert guard** (one operator page, not `circuit_anomaly` + `appliance_anomaly` both). Phantom-draw / left-on key off category thresholds.
- Every threshold on the knob ladder with name+rung+why (model on energy_circuits.py:20-44). Wire-in anchor + per-site mutation drill.

## Scaffolding (the 11 sites v1a must touch — a coordinator is NOT a config entry; config_flow.py:703 aborts)
`COORDINATOR_ENABLED_KEYS` const.py:2455 · `CONF_APPLIANCE_COORDINATOR_ENABLED`+default · construct+`register_coordinator` __init__.py:3178-pattern / manager.py:388 · `DEVICE_NAMES` _devices.py:36 · device-info dispatcher _devices.py:92 · enable switch switch.py:213 · sensors under the **CM entry** sensor.py:186 · CM menu + `async_step_coordinator_appliance` config_flow.py:3334 · strings.json + translations/en.json · telemetry `UI_COORDINATORS` coordinator_telemetry_const.py:24 (decide in/out) · observability meta-test allowlist test_v465_observability_gap.py:822 (omission = silently unguarded metrics) · **new `docs/Coordinator/APPLIANCE_COORDINATOR.md`**.

## Non-goals (v1 overall)
No control actuation (v1 references control entities by role, commands none). No breaker on/off ever. No auto-join de-dup. No auto-added plugs. No billing-grade cost claim. No new anomaly registry (reuse the two paths).

## Plan-review checklist (per slice, before its build)
- Re-grep the reuse citations (this plan's map is a hypothesis until re-verified).
- v1a: confirm `_iter_configured` key-lists cover the appliance-relevant room keys; confirm the resolver invariant is falsifiable and the no-write invariant enumerates every write domain.
- v1c: confirm the per-appliance attribution rule is fully specified (no builder ambiguity) and the discriminating paired test is present.
- v1d: confirm EXTEND-vs-new per anomaly + the double-alert guard.
