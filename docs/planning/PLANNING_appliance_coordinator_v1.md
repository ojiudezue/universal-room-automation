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
`__init__.py:3178-3237` — but registered AFTER the Energy coordinator (see v1a-B4), so its `async_setup`
runs once `SPANCircuitMonitor` exists.** **Two persistence homes, by data kind:** the operator-declared
appliance record list lives in **CM-entry options** (`CONF_APPLIANCE_RECORDS`, default `[]`) like every
other config list; **`metric_baselines`** (`coordinator_diagnostics.py:1251`, table `database.py:1050`) is
used ONLY in v1d for numeric anomaly baselines — it is numeric-only (`mean/variance/sample_count`) and
`load_baselines` DELETEs any row whose `metric_name` is not a declared metric, so it CANNOT hold records or
categorical data.

---

## Zero-duplication reuse map (the spine — REUSE, do not rebuild) — re-review-verified

Every citation below was re-greped in the Tier-3 re-review (record `..._plan_review.md`); line drift ≤2.

| Capability | REUSE (file:line) | Class |
|---|---|---|
| Passive coordinator lifecycle template | `music_following.py:1-15,238-687` (evaluate→[] at :475) | model on |
| Registration shape | `__init__.py:3178-3237`; `COORDINATOR_ENABLED_KEYS` const.py:2455; `register_coordinator` manager.py:388; `_coordinator_device_info` base.py:200 | copy shape (register AFTER energy — v1a-B4) |
| Power/energy ingestion (any metered appliance) | `SPANCircuitMonitor` EXTRA_ENTITIES Tier-2 `energy_circuits.py:196-212` — ingests ANY live entity (only `hass.states.get` check); non-float silently dropped downstream at `:281-284` | REUSE-AS-IS |
| Operator add-path for power sensors | `CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES` energy_const.py:971 → selector config_flow.py:5457 (`domain=sensor, device_class=power` — POWER role only; control/state need per-role selectors) | REUSE-AS-IS (power role) |
| De-dup / exclude a double-counted feed | `CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES` energy_const.py:973; exclusion energy_circuits.py:214-219 | REUSE-AS-IS |
| **Multi-source resolver + unresolved snapshot** (the repo's OTHER census) | `camera_census.py`: `resolve_configured_cameras()` :570 (multi-source + **device_id dedup** :589-628), `resolve_cross_platform_sensors()` :658, `record_unresolved_for_scope()` :631 / `get_unresolved_configured_cameras()` :1048 (never auto-substitutes = "visible, never dropped") | **REUSE pattern** — model the appliance resolver on this, not a new one |
| Smart-plug control+measure (dumb loads) | `SmartPlugController` energy_pool.py:3361; no-meter estimate `L1_ESTIMATED_POWER_W` energy_const.py:961 | REUSE-AS-IS |
| TV/AV state (no power sensor) | room `media_player` URA already tracks: `CONF_ROOM_MEDIA_PLAYER` const.py:83, deadness sensor.py:1753 | REUSE reads |
| Anomaly detection (z-score + sudden-zero) | `check_anomalies` energy_circuits.py:267-395 (detection only) + emit/NM seam energy.py:6407-6456 (`_emit_circuit_anomaly_event` :6457) | REUSE-AS-IS (both halves) |
| Anomaly emit + NM | `AnomalyEvent`/`save_anomaly_event` (anomaly_event.py:155, database.py:6956); `fire_stuck_signal` _stuck_signal_nm.py:165 | REUSE-AS-IS |
| Cost rate + guard (v1c) | `_get_effective_rate_kwh` energy_billing.py:29 (REUSE); `PeakAvoidanceTracker` :478 double-count guard :610-615 — **RATE + GUARD reuse only; the tracker has NO per-appliance dimension → per-appliance attribution is genuinely NEW** (v1c) | REUSE rate/guard; per-appliance attribution = NEW |
| "URA-owned shows up" collector | `_iter_configured` is a **bound room-sensor method** (sensor.py:1829, yields `(entity_id,key,category)` over key-lists :1747-1756) — build a HOUSE-level iterator over ROOM entries modeled on `_collect_presence_input_entities` presence.py:7567. Appliance-relevant keys exist: `fans,humidity_fans,power_sensors,climate_entity,room_media_player,lights,covers` | REUSE skeleton (author house iterator) |
| Onboarding N-record add/edit/remove flow (v1b) | zone-picker `__getattr__` menu config_flow.py:2987 + dynamic build :8783-8800 + EntitySelector step :5457 | REUSE pattern |
| No-CM-reload on iterative saves (v1b) | EXTEND `OPTIONS_RELOAD_SUPPRESS_KEYS` __init__.py:6612 + in-place apply :5989 | EXTEND |
| Rename-stable identity | `CircuitInfo.unique_id` + `_lookup_unique_id` energy_circuits.py:65,116-140 | REUSE-AS-IS |

## Fragile patterns — DO NOT use (operator: avoid the ones we cannot rely on)

1. **`CircuitInfo.controllable` — DEAD STUB.** `energy_circuits.py:80` is its only occurrence repo-wide; never assigned/read. Resolve a controllable signal from the breaker/switch entity explicitly if needed.
2. **CROSS-integration `device_id`/MAC/model joins — no reliable key** (canonical: `docs/architecture/DEVICE_TREE.md`). De-dup ACROSS integrations = operator-declared only. **BUT intra-config-entry `device_id` grouping IS reliable and in production** (`camera_census.py:589-628` dedups two entities on one device) — USE it to collapse ThinQ's N-entities-per-device and SPAN's entities-per-circuit automatically, with zero operator effort. Operator grouping is only needed to bridge ACROSS integrations.
3. **`media_player` platform allow/deny literals** — heuristic default at most, never ground truth (306 media_players; `airplay` isn't a platform).
4. **Parsing model from name strings** — the `NON_GUEST_HOSTNAME_PREFIXES` const.py:3109 antipattern; the v5.12.0 SPAN re-key deliberately moved OFF friendly_name.
5. **RestoreEntity for coordinator state / midnight-snapshot accumulators** — documented restart-wipe history (energy.py:1897-1953,2324). Use CM-options (records) / `metric_baselines` (numeric, v1d).
6. **Untracked `async_create_task`** (v4.6.3 A5) — track in a set, cancel (without await) in teardown BEFORE any teardown persist (music_following.py:362-367,666-685).
7. **Gating setup on another integration's health/availability.** Corollary (v1a-B4): also do not gate on another coordinator being *constructed* — hence register after Energy or read SPAN lazily on first tick.
8. **`CONF_ENERGY_CIRCUIT_INTEGRATIONS` energy_const.py:970 — dead stub, do NOT repurpose.**

## The ONE genuinely-new structure: the per-appliance record (defined + read in v1a)
```
appliance = {
  name, functional_domain,            # media_av|kitchen|laundry|climate|cold_chain|water|cleaning|other
  room,                               # optional
  entity_refs: {power:[], energy:[], control:[], state:[]},   # any role may be empty
  source_tags: [span|emporia|thinq|smartplug|native|ura_config],
}
```
Stored as `CONF_APPLIANCE_RECORDS` in CM-entry options (default `[]`). A TV = state+control, no power. A
warming drawer = power, no control. **De-dup is layered:** intra-integration shadows collapse
automatically by `device_id` (reuse camera_census pattern); **operator grouping bridges only ACROSS
integrations** (ThinQ device + SPAN circuit + room entity → one record). URA-owned entities are *read in*
as a discovery source and shown; net-new entities are *added* through the v1b flow. Measuring **plugs
only** (not Shelly relays generally), **never auto-added** (operator 2026-09-14).
**Same-entity-in-two-records is a legal-config hole → the plan chooses reject-at-flow-validation** (v1b
validates an entity_id appears in ≤1 record); v1a's reader treats a duplicate as last-wins-with-warning as
a backstop.

---

## Staging (each slice its own tier + review; ship value at each)

### v1a — Appliance census (Tier 2-DB) — first shippable slice
- **Scaffold** the first-class passive `ApplianceCoordinator` (the numbered site list below), modeled on
  music_following, **registered after Energy**.
- **Record structure (owned by v1a):** define `CONF_APPLIANCE_RECORDS` (CM options, default `[]`) + the
  record schema above + the **read side** (a house-level iterator + resolver). v1b adds only the flow writer.
- **Discovery (read-only):** union of (1) SPAN circuits (read the existing monitor's `CircuitInfo` set —
  requires Energy up, hence registration order), (2) declared appliance records, (3) URA-owned entities via
  the house iterator. Intra-integration shadows auto-collapse by `device_id`; cross-integration only via
  declared grouping. Freshness-gated; degrades if a source is absent OR late.
- **One read-only sensor** `sensor.ura_appliance_census` with per-appliance attributes.
- **Falsifiable invariants (restated to be testable):**
  - **(i) de-dup** = entity-exclusivity (every `entity_id` in ≤1 record across all roles) + group-completeness
    (each declared group → exactly 1 record, suppresses same-entity records from other sources) + no-drop
    (every unclaimed entity → exactly 1 `other` record). (Replaces the untestable "physical appliance".)
  - **(ii) commands nothing** = the coordinator performs **zero `hass.services.async_call` of ANY
    domain/service AND zero `hass.states.async_set`** across a full tick and every public method — asserted
    by patching `hass.services.async_call` and checking `call_count == 0`. (The turn_on/number/select list
    is commentary only; the patch-and-assert-zero form cannot go stale.)
- **Persistence:** CM-options round-trip of the records. **Restart criterion (stated):** post-restart the
  census record identity is byte-identical pre/post from the persisted options (NOT metric_baselines — that
  is v1d).
- **Freshness knob:** `APPLIANCE_STALE_MAX_AGE_S` — **module constant** in a new `appliance_const.py` (rung 1,
  review-gated; not operator-tuned), modeled on `energy_circuits.py:20-44`, with a kill value documented.
- **`CONF_APPLIANCE_COORDINATOR_ENABLED` default = True** (matches `switch.py:657` which bakes default-True
  into the reused `CoordinatorEnabledSwitch`; a default-OFF choice would be a divergence and is NOT taken).
- **Acceptance (each achievable within v1a):** a URA room fan appears with `source_tags:[ura_config]` and
  needs NO onboarding step (URA-owned ≠ re-config); intra-integration shadows collapse by device_id → one
  record; **wire-in anchor** — the test reads `sensor.extra_state_attributes[...]` and asserts values, and
  neutering the resolver **call site in production source** turns it RED. *(Moved to v1b: "net-new TV absent
  until added" and "triple-covered cross-integration → one record AFTER operator grouping" — both need the
  v1b flow.)*

### v1b — Categorization + onboarding flow (Tier 2)
- The record's options-flow surface (zone-picker `__getattr__` menu + per-role EntitySelector steps), add/edit/remove + remove-path for a vanished entity + **reject-at-validation of an entity in two records**.
- **EXTEND `OPTIONS_RELOAD_SUPPRESS_KEYS`** with the appliance keys + in-place re-read; acceptance: an onboarding save does NOT reload the CM (oracle: sibling-entity `last_changed`).
- 4-axis categorization (functional-domain primary) + strings.json **(2 sub-sites: menu label + step block)** + translations/en.json (parity is test-guarded — `test_strings_en_translation_parity.py`). Acceptance moved here: net-new TV absent-until-added; cross-integration triple-covered → one record after grouping.

### v1c — Energy + cost (Tier 3 — money numbers)
- `energy_used_kwh` (unambiguous) SEPARATE from mix-aware `cost_attributed`.
- **REUSE the rate + double-count guard** (`_get_effective_rate_kwh`, `PeakAvoidanceTracker` guard) — but
  **per-appliance attribution is NEW** (the tracker is house-scope only). Adjudicate IN-PLAN the rule for
  which appliance's kWh was the grid-served fraction when several drew at once — pro-rata (not "marginal");
  carry the **"display-only, not billing-grade"** disclaimer. Cite Envoy ids `sensor.envoy_482543015950_*`.
- **Discriminating acceptance:** 100%-solar → cost≈0 AND (paired) 100%-grid → cost≈kwh×import_rate; a mixed case.

### v1d — Anomaly (Tier 2-DB)
- Thin `AnomalyDetector` + `ApplianceAnomalySensor` class + its registration alongside `MusicFollowingAnomalySensor` at `sensor.py:249`; `CONF_APPLIANCE_ANOMALY_SENSITIVITY` knob (model const.py:2541 + a config-flow step field like config_flow.py:7219).
- **Observability meta-test (belongs HERE, not v1a — needs the AnomalyDetector):** add `APPLIANCE_METRICS` + `APPLIANCE_SUPPRESSED_FROM_PERSISTENCE` module constants in `appliance.py` AND the **four** edits in `test_v465_observability_gap.py` (`_AUDIT_SPEC` :824, `coord_source_file` :887, suppression-pass :1321, `coord_files` :509). Omitting the constants → suite RED.
- Appliance anomalies as **EXTEND-not-new** vs `energy_circuits.py` cold-chain/tripped-breaker + z-score: add a `cold_chain` category tag to the existing detector, and state the **double-alert guard** (one page, not `circuit_anomaly` + `appliance_anomaly` both). Phantom-draw / left-on key off category thresholds. Every threshold on the knob ladder (name+rung+why, model energy_circuits.py:20-44). Wire-in anchor + per-site mutation drill.

## Scaffolding (v1a sites — a coordinator is NOT a config entry; config_flow.py:704 aborts add-coordinator)
Numbered (v1a unless marked):
1. `COORDINATOR_ENABLED_KEYS` const.py:2455 (+ `CONF_APPLIANCE_COORDINATOR_ENABLED`, default True)
2. construct + `register_coordinator` — **after Energy** (`__init__.py:~3567+`) / manager.py:388
3. `DEVICE_NAMES` _devices.py:36 **AND `DEVICE_MODELS` _devices.py** (both — parity test `test_device_entity_architecture.py:141`)
4. device-info dispatcher _devices.py:93 (covers `_coordinator` suffix — verify)
5. enable switch switch.py:206-253
6. census sensor under the **CM entry** sensor.py:185-249
7. CM menu + `async_step_coordinator_appliance` config_flow.py:3331-3358
8. strings.json (menu label + step block) + translations/en.json
9. `appliance_const.py` (new) — `APPLIANCE_STALE_MAX_AGE_S` + the record schema constants
10. telemetry: `UI_COORDINATORS` coordinator_telemetry_const.py:34 = **OUT** (music_following is also out; no emit labels) AND `COORDINATOR_EMIT_LABELS` :24 = OUT — stated, not "decide"
11. `docs/Coordinator/APPLIANCE_COORDINATOR.md` (new — required per CLAUDE.md)

**v1d-only scaffolding:** `ApplianceAnomalySensor` + registration; `CONF_APPLIANCE_ANOMALY_SENSITIVITY`; `APPLIANCE_METRICS`/`APPLIANCE_SUPPRESSED_FROM_PERSISTENCE` + the 4 observability-meta-test edits.

## Non-goals (v1 overall)
No control actuation (v1 references control entities by role, commands none). No breaker on/off ever. No
CROSS-integration auto-join (intra-integration device_id grouping IS used). No auto-added plugs. No
billing-grade cost claim. No new anomaly registry.

## Plan-review checklist (per slice, before its build)
- Re-grep the reuse citations (this map is a hypothesis until re-verified).
- v1a: confirm the house iterator's key-lists cover the appliance-relevant room keys; confirm invariant (ii)
  is the patch-and-assert-zero form; confirm registration lands after Energy.
- v1c: per-appliance attribution rule fully specified (no builder ambiguity) + discriminating paired test.
- v1d: EXTEND-vs-new per anomaly + double-alert guard + the 4 observability edits + the 2 module constants.
