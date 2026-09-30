> **Operator rulings 2026-09-30 (all 5 open questions, answered as recommended):** (1) P3 ships in the normal release to both houses — profiles are auto-detected, no house-specific flag. (2) The ecobee profile reuses the existing per-zone Home/Sleep/Away setpoint fields; no ecobee-only set. (3) A Thermostat-type override persists; if detection later sees different hardware (swap), raise a repair/NM and ask — never silently revert. (4) Every notification string is templated by profile name ("your ecobee", "your Carrier"); no hard-coded "Bryant app". (5) P1 byte-identity proof = one parametrized suite (S-site × WriteStatus table), not per-site files.

# HVAC W1-C — Thermostat Profiles (brand-owned semantics; Generic net; ecobee first non-Carrier target)

Card: `HVAC-W1C-GENERIC-THERMOSTAT-1` (kanban.data.yaml:1975; workstream `HVAC-W1-THERMOSTAT-DEFINITION`; revival trigger fired 2026-09-29). Author: ura-planner. Deploys **held** for the operator throughout. Second home ("Home", 192.168.17.243) goes live weekend of 2026-10-03 with HVAC OFF until P3 validates the ecobee profile there.

Read first, in full: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 corrections ledger — never re-assert a wrong claim); `custom_components/universal_room_automation/domain_coordinators/hvac_strategy.py`; `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md` §14; `docs/planning/AUDIT_house2_ecobee_inspection_2026_09_30.md`; vibememo `169_thermostat_profiles_in_code_autodetected_generic_net.json`.

Operator-approved shape (NOT to be re-litigated; vibememo 169): brand families are CODE profiles in the `hvac_strategy` registry (capabilities; hold method; person-change detection; timings — echo TTL, confirm window, cloud write-rate bound, retry intervals); auto-detected from the device registry (integration + manufacturer → integration → Generic); shown per zone in **Manage Zones → Zone HVAC** as `Thermostat type: <X> — detected` with an override dropdown; **no** user-defined manufacturer UI, no research DB; unsupported features render as `unavailable` with a reason; **Generic** = setpoint-only holds, person-change = a setpoint moved without a URA write (using URA's own write context / last-write record from `hvac_strategy._last_sent` + W1-A `climate_write` rows), conservative timings, **no borrows** until a brand profile says safe.

---

## Institutional context verified

### 1. Prior planning docs consulted
- `docs/planning/PLANNING_hvac_w1a_thermostat_write_governance.md` (W1-A funnels + `climate_write`).
- `docs/planning/PLANNING_hvac_w1b_thermostat_definition.md` REV 7 (Carrier definition + strategy skeleton).
- `docs/planning/PLANNING_hvac_w1_w2_finish.md` REV 2 (W1/W2 finish Part A: person-interrupt classifier).
- `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md` §14 (CPR = Carrier-profile capability; strategy line rules; W1-C hand-off checklist).
- `docs/planning/PLANNING_hvac_arc_w1_w2_integration.md` (seams).
- `docs/planning/AUDIT_house2_ecobee_inspection_2026_09_30.md` (real second target).
- `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` (canonical Carrier definition).

### 2. Design/manual docs read
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §§1–10 (complete). §10 CORRECTIONS LEDGER acknowledged; nothing in this plan re-asserts a retracted claim (e.g. NOT: "status/config coherence" as a manual-hold discriminator; NOT: "arrester alone owns manual holds"; NOT: the retired excursion kill switch).

### 3. Memory bodies pulled
- vibememo `169_thermostat_profiles_in_code_autodetected_generic_net.json` (binding shape).
- `feedback_config_first_before_code`, `feedback_no_fabrication`, `feedback_tier2plus_prior_art_scan`, `feedback_tier2db_for_regression_prone`, `feedback_extend_existing_never_rebuild`, `feedback_falsify_before_asserting`, `feedback_wire_in_anchor_mandatory`.

### 4. Code locations surveyed end-to-end during scoping
- `domain_coordinators/hvac_strategy.py` (full — 286 lines, W1-B skeleton).
- `domain_coordinators/hvac_setpoint.py` (funnels `emit_set_temperature` / `emit_set_preset_mode` / `emit_set_hvac_mode` / `emit_set_activity_setpoint`).
- `domain_coordinators/hvac_override.py` (classifier `classify_manual_setpoint_change` :167, `_handle_climate_change` at :3594, arrester, nudge S5/S6/S7, AC ramp, gate 4, blower_rpm corroboration :2230).
- `domain_coordinators/hvac.py` (S1 preset writer, heat_cool enforcer B1 ~1926, pre-arrival, `_climate_unreadable` gate, `zone.preset_mode == "manual"` reads :3398/3409/3574/3700/3793).
- `domain_coordinators/hvac_excursion.py` (borrow primitive, boot audit `manual` snapshot handling :1168).
- `domain_coordinators/hvac_preset.py` :359 (`current_preset == "manual"`).
- `domain_coordinators/hvac_predict.py` (pre-cool/pre-heat).
- `domain_coordinators/hvac_zones.py`, `hvac_const.py`, `hvac_fans.py`.
- `config_flow.py` HVAC zone step; `sensor.py`, `switch.py`, `number.py`, `select.py`, `button.py` (borrow / arrester / ramp entities).

### 5. Prior-art scan — REUSE vs BUILD per proposed piece
| Piece | Verdict | Where |
|---|---|---|
| Strategy registry + dispatch (`strategy_for(hass, entity_id)`) | **REUSE** (extend) | `hvac_strategy.py:238-286` |
| `WriteResult` / `WriteStatus` / `HoldObservation` | **REUSE** | `hvac_strategy.py:56-90` |
| Per-verb `_last_sent` (D2a) — URA's own write record | **REUSE** (extend to `set_temperature` + `set_hvac_mode`) | `hvac_strategy.py:142-153` |
| Durable per-write ledger row (`climate_write`) | **REUSE** | `hvac_setpoint.py` W1-A funnels; state-of-play §4.1/4.3 |
| Person-change classifier | **REUSE + extend** (works on `heat_cool` setpoints today; add "setpoint-only" and "select-only" shapes) | `hvac_override.py:167 classify_manual_setpoint_change` |
| Resume-then-pin (Carrier quirk) | **REUSE** (already capability-gated) | `hvac_setpoint.py:171-222`, `:317-410` |
| Zone `climate_entity` field | **REUSE** (extend zone schema with `thermostat_profile` override + detection cache) | `config_flow.py` HVAC zone step |
| Manage Zones UI | **REUSE** (add "Thermostat type: X — detected" display + override dropdown) | `config_flow.py`, `strings.json`, `en.json` |
| CPR (Custom Preset Ranges) | **REUSE** (already scoped as Carrier-profile capability per CPR §14) | plan §14 |
| Equipment telemetry — variable-speed, static pressure, blower_rpm, gate-4 stage threshold, AC ramp, per-zone tonnage | **BUILD** capability gate on strategy (not a new sensor set) | `hvac_override.py:2230` (blower_rpm), `:2266+` (gate4), `hvac_const.py:876/914`; `feedback_config_first_before_code` — the per-zone tonnage values are today static in options |
| A new "manufacturer research DB" or user-defined-brand UI | **DROP** (operator: no) | — |

### 6. Producer / consumer checks for the new value "thermostat profile per zone"
- **Producer:** `strategy_for(hass, entity_id)` → registry `entry.platform` today (`hvac_strategy.py:242-266`). P2 extends to (platform, manufacturer, model) — device registry via the entity's `device_id` — with fall-through order in §Design. Cache is per-platform+manufacturer key. Result is stored on `ZoneState.thermostat_profile` at zone-refresh time; also written into the ledger row.
- **Consumers (trust decisions):** every write site listed in state-of-play §4.2 (S1, B1, S3/S4, AC hard reset, S5/S6/S7, S8/S9, S10 CPR, S11/S12/S13, egress); `classify_manual_setpoint_change` (arrester); S1 gates that read `preset_mode == "manual"` (hvac.py:3398/3409/3574/3700/3793; hvac_preset.py:359); the pre-arrival fan writers; borrow safety gates. Every consumer today assumes Carrier semantics; the strategy is the ONE seam that translates.
- **Display consumers:** the Manage Zones panel (new), `sensor.<zone>_status` attrs (new `thermostat_profile` + `profile_source`), NM texts that name "Bryant app".

### 7. Config-first check (per CLAUDE.md 2026-09-26 rule)
Not solvable by an existing knob. No CONF_* today discriminates thermostat brand behaviour; `CARRIER_INTEGRATION_DOMAIN` is hard-wired (`hvac_const.py:1473`). The change is genuinely code — but every NEW number this cycle proposes goes through §Knobs before it lands.

---

## INVENTORY — every Carrier-specific assumption in shared HVAC code

This is the exhaustive list P1 must route through the strategy. Each is either **byte-identical for Carrier** (P1) or **strategy-gated** (later phases). Line numbers verified on `develop` today.

### A. Write sites that bypass or hard-code Carrier semantics
| # | Site | Verb | Carrier assumption |
|---|---|---|---|
| A1 | S1 `hvac.py:2674` | preset (+ hidden `resume`) | `resume` capability, named-preset vocabulary, `preset_mode==manual` lockout reads |
| A2 | B1 heat_cool enforcer `hvac.py:1926-1938` | hvac_mode | assumes `heat_cool` mode is always the target; ecobee has it, generic thermostats often don't |
| A3 | S3 arrester compromise `hvac_override.py:3393` | setpoints | assumes dual-leg `target_temp_high/low` |
| A4 | S4 revert `_revert_override` | mode + preset | pins a NAMED preset; ecobee has none on climate |
| A5 | AC hard reset off/restore/retry/preset `hvac_override.py:3888/4006/4041/4113` | mode + preset | Carrier variable-speed rationale; assumes a named preset to restore |
| A6 | S5 soft-nudge start `hvac_override.py:4423` | setpoints (+`nudge_size` to high leg) | assumes `heat_cool` with a high leg; assumes "modulates at setpoint" Bryant physics |
| A7 | S6/S7 nudge restore `:4595` / `:4640` | setpoints then preset | dual-leg + named-preset pin |
| A8 | S8 cancel-nudge button `:5815/5841` | setpoints + preset | same |
| A9 | S9 boot ramp audit `:6221/6245` | setpoints + preset | same |
| A10 | Excursion lease-expiry auto-return `hvac_excursion.py:667` | preset | named-preset pin |
| A11 | S11 banking release / S12 pre-cool / pre-arrival S12 / S13 pre-heat | setpoints + preset | dual-leg + named-preset |
| A12 | Egress pause/resume `hvac_egress.py:683/779/795` | mode + preset | named-preset |
| A13 | S10 DPM Custom Preset Ranges `hvac.py:3046` (calls `emit_set_activity_setpoint` → `ha_carrier.set_activity_setpoint`) | activity setpoints | **Carrier-only service**; already scoped as Carrier-profile capability (CPR §14). Untouched by W1-C code — its strategy hook exists |

### B. Manual-detection assumptions (Carrier's `preset_mode=="manual"` proxy)
| # | Site | Assumption |
|---|---|---|
| B1 | S1 gates `hvac.py:3398 / 3409 / 3574 / 3700 / 3793` | `zone.preset_mode == "manual"` is the human-override signal |
| B2 | `hvac_preset.py:359` | same |
| B3 | Arrester TAO/immune paths keyed on the same string | same |
| B4 | Boot audit `hvac_excursion.py:1168` (`pre_preset == "manual"` → do NOT re-pin) | Carrier-only snapshot marker |
| B5 | `classify_manual_setpoint_change` `hvac_override.py:167` | assumes both states have `heat_cool` and 4 numeric legs; ecobee (single setpoint, no presets) trips every guard |
| B6 | `coordinator_diagnostics.py:594` | display consumer of same |

### C. Timings (Carrier cloud + Bryant physics)
| # | Constant | File | Assumption |
|---|---|---|---|
| C1 | `SUPPRESS_TTL_SECONDS = 15` (temp echo TTL) | `hvac_override.py:133` | measured Bryant echo 5.3–7.5 s |
| C2 | `SUPPRESS_TTL_SECONDS_PRESET = 120` | `hvac_override.py:173` | Carrier 42–79 s + Bryant schedule guard |
| C3 | `HVAC_DECISION_TICK = 5 min` | `hvac_const.py:13` | Carrier cloud call-rate ceiling |
| C4 | Post-reload settle 1800 s, cooldown 1800 s, max reloads/day 4, grace ticks 2 | `hvac_const.py:1432-1462` | Carrier-only reload machinery |
| C5 | Nudge duration 2 min, size 1.5 °F, eval delay 240 s, `AC_NUDGE_OVERSHOOT_GAP = 0` | `hvac_const.py:665, 746` | Bryant variable-speed physics |
| C6 | Preset write timeout, retry intervals | `hvac_setpoint.py` resume-then-pin | Carrier lag |

### D. Named-preset hold model
Everywhere named presets flow (`home / away / sleep / wake / vacation`): S1 target selection, D8 night tail selection, `_resolve_reference`, arrival target for pre-arrival, F2/F4, INFO-1 restore. Ecobee has none on climate; a select carries a subset (home/sleep/away).

### E. ODU/IDU telemetry consumers (all zero-telemetry-safe today for Generic — must stay so)
| # | Site | Consumes |
|---|---|---|
| E1 | AC ramp / hard reset | zone `ac_load_sensor` (per-zone kW), coil kW thresholds |
| E2 | Blower_rpm corroboration | `hvac_override.py:2230` — CORROBORATION, not veto |
| E3 | Gate-4 predicate + stage threshold (36 observed; 40 default) | `hvac_const.py:876, 914`; `hvac_override.py:2266+` |
| E4 | Equipment-health readers | anomaly detector (already blind-metrics safe per state-of-play 2026-09-29 anomaly note) |
| E5 | Nudge/AC ramp per-zone kWh gates | live `1.5/2.2/2.2` zone thresholds |
| E6 | Per-zone tonnage | operator-authoritative (state-of-play §5 reference; doc:252 correction in memory `reference_hvac_zone_tonnage`) |

### F. Carrier config-flow fields
`CONF_HVAC_CARRIER_STALE_MAX_AGE_S`, `_STALE_REQUIRE_BLIND_CORROBORATION`, `_RELOAD_COOLDOWN_S`, `_RELOAD_MAX_PER_DAY`, `_POST_RELOAD_GRACE_TICKS`, `_POST_RELOAD_SETTLE_S`, `CARRIER_BLIND_CORROBORATION_KW_THRESHOLD`, `CARRIER_INTEGRATION_DOMAIN` (`hvac_const.py:1415-1473`; `config_flow.py:6046, 6412+`). All become **Carrier-profile-scoped** at the config surface (still shown, still stored, but ignored for a non-Carrier zone; NM copy re-templated).

---

## DESIGN

### D1. Profile interface
Extend `GenericStrategy` with a capability set + methods. All methods return `WriteResult`; truthiness stays banned.

```
class ProfileCapabilities:
    has_named_presets: bool          # any preset_modes at all
    named_preset_vocabulary: frozenset[str]  # e.g. {home, sleep, away, vacation} for Carrier; {} for ecobee-HK
    has_heat_cool_mode: bool
    setpoint_shape: Literal["dual_leg", "single_setpoint"]
    supports_resume: bool             # 'resume' in preset_modes
    supports_activity_setpoint: bool  # Carrier ha_carrier.set_activity_setpoint (CPR)
    hold_via: Literal["preset", "select", "setpoint_only"]
    hold_release_mechanism: Literal["preset_named", "resume_service", "clear_hold_button", "setpoint_write", "select_write"]
    equipment_telemetry: frozenset[str]  # {"variable_speed", "static_pressure", "blower_rpm", "ac_load_kw"}
    echo_ttl_s: int                   # C1
    preset_echo_ttl_s: int            # C2
    write_rate_min_interval_s: int    # cloud bound
    retry_interval_s: int
    person_change_shape: Literal["heat_cool_both_legs", "single_setpoint", "select_or_setpoint"]

class GenericStrategy:
    capabilities: ProfileCapabilities
    async def hold_preset(...) -> WriteResult             # already there
    async def set_setpoints(...) -> WriteResult           # NEW (P1 for byte-identity)
    async def set_hvac_mode(...) -> WriteResult           # NEW
    async def release_hold(...) -> WriteResult            # NEW ("resume" / clear-hold button / setpoint-only fallback)
    async def snapshot(hass, entity_id) -> HoldObservation  # already
    def classify_person_change(...) -> PersonChangeVerdict # NEW — replaces per-site heat_cool assumption
    def is_human_manual_snapshot(...) -> bool             # already
    def feature_available(name: str) -> bool              # capability gate for equipment-telemetry features
    def feature_unavailable_reason(name: str) -> str
```

### D2. Detection + zone setting
- **Order:** (registry `platform`, device `manufacturer`, device `model`) → (platform, manufacturer) → (platform) → **Generic**.
- **Cache:** keyed by the resolved tuple; miss returns Generic **uncached** (existing rule in `hvac_strategy._entry_platform`).
- **Zone setting:** `ZoneState.thermostat_profile` + `profile_source` in {`detected`, `override`}. Manage Zones → Zone HVAC displays `Thermostat type: <human name> — detected` (or `— override`) with a dropdown of KNOWN profiles + `Generic`.
- **Persistence:** stored under the zone entry options as `zone_thermostat_profile` (labelled `Thermostat type` in the flow). Migration: absent → Generic + one-shot re-detect at next zone refresh; a config entry that reads `Carrier/Bryant` today keeps `carrier` explicitly.
- **Change semantics:** switching profile flushes `_last_sent` for that entity and re-emits P1 detection into `climate_write`.

### D3. Degraded-feature surface
- `feature_available("nudge") == False` → S5 stands down with `nudge_unavailable_profile` (`ac_ramp_events` reason); switch/button entities render `unavailable` with `feature_unavailable_reason(...)` (helper text under the entity).
- `feature_available("borrow.banking") == False` → Generic (until proven safe): S11/S12/S13 skip with `borrow_disabled_profile` and one INFO per zone/day.
- `feature_available("cpr") == False` → S10 continues to skip quietly (existing behaviour §14) with the strategy-supplied reason.

### D4. Generic semantics (fail-safe)
- **Hold:** SETPOINTS ONLY. `hold_preset` on Generic falls back to a setpoint write that matches the target preset's numbers (looked up from the operator's per-zone comfort table already used for Carrier presets), no named pin.
- **Release:** the presets-only return paths (state-of-play §9e / v5.103.24 INFO-1) are gated by `hold_via`. Generic's return is a setpoint write to the reference target; no `resume`, no Clear Hold, no named pin.
- **Person-change:** `classify_person_change` on Generic = any observed setpoint value that (a) is not within ±0.5 °F of any URA-recorded `set_temperature` in `_last_sent` for that entity in the last N min AND (b) has no corresponding `climate_write` row in the same window → HUMAN.
- **No borrows** (`banking`, `preheat`, `pre_cool`) until the concrete profile marks them safe. Nudges and AC ramp OFF for Generic in P1 shipping state.
- **B1 heat_cool enforcer**: gated on `has_heat_cool_mode`.

### D5. Ecobee-HomeKit profile (`homekit_controller`, manufacturer `ecobee`)
Observed capabilities (audit doc):
- `hvac_modes = off / heat / cool / heat_cool`; `preset_modes = None`; single setpoint in single-mode; humidity target present; `select.<x>_current_mode` (home/sleep/away); `button.<x>_clear_hold`.
- `hold_via = "select"` for {home,sleep,away}; falls through to setpoints when the target isn't one of those three.
- `hold_release_mechanism = "clear_hold_button"` → the profile calls `button.press` on `button.<zone_entity>_clear_hold` before or instead of setpoint writes, per verb.
- `person_change_shape = "select_or_setpoint"`: `classify_person_change` inspects both the select's `current_mode` and the single setpoint; comparison against `_last_sent["set_temperature"|"select_option"]`.
- `has_heat_cool_mode = True` (mode exists); dual-leg setpoints unavailable when mode is single — the strategy exposes ONLY `temperature` writes in that state; B1 stays a no-op unless the mode is `heat_cool`.
- Timings: `echo_ttl_s = 30`, `preset_echo_ttl_s = 60` (single install, no cloud lag; verify P3), `write_rate_min_interval_s = 30`.
- Borrows: DISABLED in P3 first ship; opened only after live proof.

### D6. Batch C (CPR) sits as a Carrier-only capability
No change to CPR's scope. `CarrierStrategy.capabilities.supports_activity_setpoint = True`; Generic / ecobee: False. `emit_set_activity_setpoint`'s service_domain/service_name are already strategy-supplied (CPR §14 F3). S10 skip on Generic/ecobee is unchanged.

---

## PHASES

### P1 — Route every thermostat write through the profile; Carrier byte-identical
**Deliverables**
1. Every A1–A12 site calls a `strategy.*` method rather than the funnel directly (funnels stay — the strategy calls them). Carrier's methods delegate to the exact same funnel calls in the same order with the same kwargs.
2. `_last_sent` extended to `set_temperature` and `set_hvac_mode`.
3. B1/B2/B3/B4/B5/B6 read `strategy.is_manual_hold(observation)` instead of literal `preset_mode == "manual"` (Carrier: same predicate; keeps behaviour).
4. AST completeness test: NO raw `service.async_call("climate", ...)` outside `hvac_setpoint.py`; NO raw `preset_mode == "manual"` in any HVAC file except the strategy.
5. Ledger: every `climate_write` row carries `profile` + `profile_source`.
**Acceptance / Verify**
- Test: for every A-site, a byte-identity test captures the exact `service_data` (verb, entity, values, order) pre- vs post-P1 on the Carrier fixture and asserts equality. Run it under both APPLIED and DEFERRED paths.
- Test: per-site call-neuter drill (`feedback_wire_in_anchor_mandatory`): stub `CarrierStrategy.<method>` and confirm the specific test for that site fails.
- Live: after deploy (operator-gated), 24 h of Carrier `climate_write` rows show no new `verb/site/values` shape vs the 24 h before.
**Tier: 3** — same reason W1-B was Tier 3: this threads one primitive through every emission/decision site; the failure mode is one missed site (Bug Class #53). Four framing-disjoint reviews (A local, B state-machine + funnel identity, C per-site mutation, D adversarial completeness re-enumerating A1–A12 + B1–B6 + C-timings across pre-existing code, not just the diff).
**Falsifiable invariant:** *for a Carrier zone, every `climate` service call URA makes after P1 is identical in domain, service, service_data (deep), and emission order to pre-P1 for every S-site under every `WriteStatus` outcome, across restart and reload.* D falsifies it by picking a site the diff didn't touch and mutating the pre-P1 call shape in tests.

### P2 — Detection + zone setting + Generic hardening + degraded-feature status
**Deliverables**
1. `strategy_for(...)` extended to (platform, manufacturer, model). Manage Zones dropdown + display; migration.
2. `ZoneState.thermostat_profile` + `profile_source`; exposed on `sensor.<zone>_status`.
3. `feature_available` / `feature_unavailable_reason` piped to switch/button/number entities (`entity.available` + a helper attribute `unavailable_reason`).
4. Generic hardening: setpoint-only hold, setpoint-only return, `classify_person_change` (setpoint-only shape), borrows disabled.
5. Per-profile timings live only on the profile (C1–C6 accessed via `strategy.capabilities`; module constants keep Carrier values as defaults).
**Acceptance / Verify**
- Test: registry fixture (Carrier / ecobee-HK / made-up brand / no registry entry) → each resolves to the expected profile; miss returns Generic uncached.
- Test: switching a zone's profile flushes `_last_sent` for that entity and writes one `climate_write` row with `profile_source=override`.
- Sensor: `sensor.ura_hvac_coordinator_zone_1_status` attr `thermostat_profile == "carrier"` on House 1.
- Live: entity registry shows S5/S6/S7 switches + nudge number entities as `available == False` with `unavailable_reason` populated on a Generic-forced zone.
**Tier: 3** — Generic hardening changes behaviour on any zone whose profile is not Carrier (which today equals `Carrier` for every live zone, but the moment P2 flips the ecobee zone off Generic in P3, this code owns the outcome). Same 4-framing review.
**Falsifiable invariant:** *no shared HVAC code path reads `preset_mode == "manual"`, calls a `climate` service, or reads `hold_activity` outside the strategy; a zone whose `thermostat_profile` is Generic performs ZERO named-preset writes, ZERO `resume` calls, ZERO borrow begins.*

### P3 — Ecobee-HomeKit profile validated against House 2
**D0 (measure-before-build):** a **read-only** probe against 192.168.17.243:80 (operator token held by orchestrator; NEVER checked in). Records for 24 h: `climate.<x>` state + attrs, `select.<x>_current_mode` state, `button.<x>_clear_hold` availability, each entity's `last_updated` rhythm. Report writes to `docs/planning/AUDIT_house2_ecobee_probe_2026_10_0x.md`. Go/no-go on:
- `hvac_modes` / `preset_modes` match the audit doc.
- `select` transitions are observable and the API reflects them within a bounded window.
- `button.press` on Clear Hold returns cleanly.
- Setpoint write latency + echo timing (measured, not assumed).
**Deliverables (post-D0)**
1. `EcobeeHomeKitStrategy` (`platform=homekit_controller`, `manufacturer contains "ecobee"` — case-insensitive match with a fall-back list).
2. Hold via `select_option` on `current_mode` for {home,sleep,away}; setpoint fallback for other targets; release via `button.press` on `clear_hold`.
3. `classify_person_change` "select_or_setpoint" implementation.
4. Ecobee-safe defaults: B1 gated on live mode; nudges + borrows OFF.
5. House 2 opt-in switch: HVAC coordinator remains OFF until this ships live-validated.
**Acceptance / Verify**
- Live (House 2, HVAC coordinator ON with 1 zone bound to the ecobee): a scripted `Home → Sleep → Home` walk shows exactly 3 `climate_write` rows (verb `select.select_option`); Clear Hold releases; a person's setpoint bump classifies HUMAN within one tick; no borrows fire.
- Test: fixture states matching the audit doc drive every method with no exception; a fixture that mutates `current_mode` mid-write does not double-emit.
**Tier: 2-DB** (regression-prone new consumer of the same primitives; three framing-disjoint reviews A correctness / B cross-coordinator + person-change / C test authority via per-site source mutation on House 1 fixture).
**Falsifiable invariant:** *for an ecobee-HK zone, URA never calls `climate.set_preset_mode`, never sends `resume`, never writes `target_temp_high/low` while the entity's mode is not `heat_cool`.*

### P4 — Capability-gating of equipment-telemetry features
**Deliverables**
1. Nudge / AC hard reset / gate-4 stage threshold / blower_rpm corroboration read `strategy.capabilities.equipment_telemetry` before arming. Missing telemetry → feature is `unavailable` with a reason (never crashes, never silently mis-fires).
2. Per-zone tonnage stays operator-authoritative; the profile records `has_tonnage_source: bool` (Carrier False — operator config wins).
3. NM texts templated by profile (no `"Bryant app"` for a non-Carrier zone).
**Acceptance / Verify**
- Test: an ecobee-HK zone with no `ac_load_sensor` reads `feature_available("nudge") == False`; the S5 code path is unreachable in that case (mutation-verified).
- Sensor: `sensor.<zone>_status` `thermostat_profile_features` attr lists the available features.
- Live (House 1): no behaviour change (Carrier has all telemetry).
**Tier: 2** — additive gates; behaviour change only where telemetry is missing.
**Falsifiable invariant:** *no equipment-telemetry feature emits a write on a zone whose profile does not advertise the corresponding capability.*

---

## KNOBS (Numbers Get Knobs — placement per operator ladder)

| Knob | Rung | Home | Why |
|---|---|---|---|
| `zone_thermostat_profile` (Select) | 2 — config flow | Manage Zones → Zone HVAC | Set-once per zone; override of detection; kill switch for the wrong profile (`Generic` = safe) |
| Per-profile `echo_ttl_s`, `preset_echo_ttl_s`, `write_rate_min_interval_s`, `retry_interval_s` | 1 — module const on `ProfileCapabilities` | code | Physics/protocol bounds; change requires review |
| `HVAC_PROFILE_DETECTION_RECHECK_S` (rare) | 1 — module const | code | We don't want dashboards re-detecting live |
| Feature-availability overrides per zone | Not exposed in P1–P4 | — | Ship the detection; add operator overrides only if a real case appears |

Any inline literal in the new code = plan violation.

---

## NON-GOALS

- No user-defined-brand UI, no research DB, no manufacturer text-input field.
- No new sensor / entity for equipment telemetry (P4 gates existing readers).
- No change to CPR scope (Carrier-only, per §14).
- No change to the borrow primitive, the arrester state machine, the AC-ramp math, S1 gate structure, Fan Mode, or the interrupt-latch primitive (v5.103.23).
- No changes to `_last_sent` semantics beyond adding two verbs.
- No back-compat migration beyond "absent profile → Generic + one-shot detect" (single install / two installs; no multi-year back-compat).

---

## OPEN QUESTIONS FOR THE OPERATOR

1. **P3 timing.** Should P3 ship on House 2 ONLY (behind a per-install flag) before it can affect House 1, or is a joint deploy fine given House 1 has no ecobee entity?
2. **Ecobee comfort table.** House 2 has no per-zone comfort presets configured yet. Do we (a) reuse the existing per-zone comfort fields (home/sleep/away setpoints) for the select-fallback + setpoint-fallback paths, or (b) add a small ecobee-scoped equivalent?
3. **Persistence of the override.** If the operator overrides to Generic and later swaps hardware, do we auto-revert to detection on the next boot, or hold the override forever?
4. **NM copy scope.** Rename "Bryant app" to "your thermostat" in the shared strings and keep the Carrier profile's NM copy specific, or template every string via the profile name?
5. **P1 mutation-fixture cost.** Byte-identity tests per A-site are ~15 fixtures — is a per-A-site file layout OK, or one parametrized suite?

---

## SUMMARY (for the parent)

Plan lands as 4 phases: **P1 route-everything-through-the-strategy (Carrier byte-identical, Tier 3)**, **P2 detection + zone setting + Generic hardening (Tier 3)**, **P3 ecobee-HomeKit profile validated on House 2 with a D0 read-only probe first (Tier 2-DB)**, **P4 capability-gate equipment-telemetry features (Tier 2)**. The strategy skeleton (`hvac_strategy.py`) is REUSED and extended — no new registry, no new database. CPR stays Carrier-only per §14. Generic = setpoint-only holds + no borrows; ecobee-HK holds via `select.<x>_current_mode` and releases via `button.<x>_clear_hold`. Falsifiable invariants stated per phase. Every new number goes through the knob ladder; no inline literals. Deploys held for operator go at every phase boundary. 5 open questions listed.
