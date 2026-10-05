# HVAC W1-C P2 — ecobee as a thin command adapter (HomeKit first), plus P1 carry-over fixes — REV 3

**Status:** PLAN, not built. Both Tier 3 plan reviews are done (#1 completeness FIX-PLAN, #2 build-prediction
FIX-PLAN). REV 3 resolves every must-fix in both reviews; the resolution map is in §12. Build stays blocked on the
D0b GO (appendix at the end of plan review #2).

**REV 3 (2026-10-03) changes from REV 2:**
- **Effective range (review #1 HIGH, review #2 PR2-2).** The ecobee hold translation now writes the range URA would
  put on the device NOW: the S10 / CPR-composed range for that preset if S10 has set one, else the Seasonal Baseline
  range, always after the guards. The composed range lives in a URA-side store inside the adapter, written by
  `set_preset_range`, persisted with the existing HVAC zone-state store. S1's "already correct" check compares the
  live range with that effective range. See §4.2a.
- **Carrier freshness / reload moves into the adapter (review #1 MEDIUM).** `_check_carrier_freshness` keeps its
  loop, but the per-zone staleness test and the reload are adapter verbs: Carrier does today's work, every other
  profile is a no-op. No brand `if` in HC, and no INV-F lint allowlist entry is needed. See §4.10.
- **Folded into deliverables:** PR2-8 (classifier and pair-ring tolerance come from the profile, §4.4); PR2-10
  (deferral reporting, plus a hard failure and a Repair when an ecobee never reaches heat_cool, §4.11); PR2-11
  (confirmed covered by R16, §5); PR2-13 (setup notes and D0b P0, §7 D5).
- All REV 2 inline fixes (PR2-1…PR2-7, review #1 in-place fixes) are kept. The D0b probe safety appendix and the
  G1–G7 go/no-go are kept unchanged.

**REV 2 (2026-10-03) replaced REV 1's design.** Operator architecture ruling, verbatim:

> "Ecobee should work like Bryant does in my home. All we need to know is how to command it. That manufacturer
> abstraction is about how to command it efficiently given its features that Bryant may or may not have. URA HC does
> the rest and works the same. Keep the surface small and contained. It's a small Model.Brand specific
> wrapper/abstraction; URA should feel the same no matter where deployed. All those features should have a default
> on/off per URA and can be turned on or off at will. Even our preference for ranges can be preserved and it's an
> opinionated take. It allows Therms to work as they are designed and URA to do the minimum to command and futz with
> absolute temp all the time."

**What changed from REV 1 (kept for the record):**
- Every brand-based "stands down / off on ecobee" gate is REMOVED: arrester revert/compromise, borrows, nudges, AC
  resets, egress pause, DPM/CPR, and the heat_cool enforcer gating. Each feature keeps its URA default and its existing
  switch on every brand.
- The REV 1 person-hold machinery is REMOVED: gate (f), `person_hold` state, `__person_holds`, the discharge rules and
  the `person_hold_limit` knob. The arrester and §9e already own "a person changed the thermostat". They work on ecobee
  once the adapter gives them the same view that Carrier gives them.
- The adapter (strategy) is now the ONLY brand-specific surface. It has four parts: command verbs, a state read,
  capability facts, and the ours-vs-person classifier (§4). REV 3 adds the freshness/reload verb pair (§4.10), which
  is a command concern (how to recover a stale integration), not a feature gate.
- REV 1 §2 P2-C3 and F5 ("B1 overrides a person's cool/heat on ecobee") are WITHDRAWN as defects. Carrier does the same
  thing today, and the ruling is "works the same".
- **The P1 feature-gating scaffold is deleted (operator review addendum, 2026-10-03; §4.8):**
  - `feature_available` / `feature_unavailable_reason` are removed.
  - `ProfileCapabilities` is trimmed from 21 fields to the 10 command / read / classify facts.
  - The Batch C CPR plan's `feature_available("cpr")` skip is replaced by an adapter verb outcome.

**Parent plan:** `docs/planning/PLANNING_hvac_w1c_thermostat_profiles.md` (REV 3.2 banner + REV 3.1 errata). Where the
two plans disagree, this plan wins for P2 scope.
**Shipped base:** W1-C P1 in v5.103.36 (`domain_coordinators/hvac_strategy.py`; 168 Carrier goldens
`quality/tests/golden/w1c_p1_goldens.json`).
**Target:** House 2 ("Home", 192.168.17.243): `climate.master_closet_ecobee_downstairs` over `homekit_controller`.
Its HVAC coordinator stays OFF until this ships and the D0b probe passes.

---

## 0. What P2 delivers (one paragraph)

URA runs an ecobee zone exactly as it runs a Bryant zone. That covers S1 presets by house state, the arrester, borrows,
nudges, AC reset, egress, D9/CPR and the heat_cool enforcer. Every feature uses its URA default and its existing
switch. One small `EcobeeHomeKitStrategy` translates URA's verbs into what the thermostat understands:
- "Hold preset P" becomes a heat_cool range write of the **effective range** for P: the range S10/CPR has composed
  for P if any, else the house's Seasonal Baseline range for P (§4.2a). This is URA's opinionated default, because
  ecobee over HomeKit has no presets.
- "Edit preset P's range" (S10 / CPR) stores the range URA-side and, if the zone is holding P right now, writes it.
- Setpoint and mode writes pass through.
- The adapter reports the thermostat's state in Carrier's vocabulary. A range that matches URA's held preset reads as
  that preset; any other range reads as `manual`. HC readers therefore see the same signals they see on Carrier.
- Integration-staleness repair is an adapter verb: Carrier reloads `ha_carrier` as today; ecobee does nothing.

Carrier zones stay byte-identical to v5.103.36. P2 also deletes P1's unused feature-gating scaffold and folds in four
P1 review findings (§4.7).

---

## 1. Institutional context verified

### 1a. Read in full before planning (REV 2, re-read for REV 3)
- `CLAUDE.md` (project).
- The full `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:
  - §0–§12, including §3.3 (D9 dormant by design) and the 2026-10-03 live-state note (D9 switch ON at House 1,
    31 `S10_dpm_apply` writes);
  - §4.2 write sites, §5 Carrier facts and §7 arrester;
  - §9.7 (CPR blocked by the throttle bypass and restore writers not updating `_last_emitted_range`);
  - §9e four-gate rule and the "person interrupts" ruling;
  - §10 C1–C29 (none re-asserted here).
- Memory `feedback_thermostat_brand_layer_is_thin_command_adapter` (REV 3 re-read: "translate the command inside the
  adapter instead of gating features"; "if the adapter cannot do something reliably, surface it as an operator
  decision, not a silent disable").
- `docs/planning/PLANNING_hvac_w1c_thermostat_profiles.md`: REV 3.2 banner, REV 3.1 errata, REV 3 body.
- `docs/planning/AUDIT_house2_ecobee_inspection_2026_09_30.md`.
- `docs/readmes/README_v5.103.36.md`.
- This plan's REV 1 and REV 2 (git history).
- `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md`: REV 3.3 U1 (:29, :1196), `set_preset_range` design
  (:23-36, :637-657, :751), and the operator-ruling note :1215-1216 (thin adapter).

### 1b. Code read for this plan (file:line on `develop` @ `8a4619b32`; review #1 confirmed no code diff to `e15c4d49e`)
| File | What was read |
|---|---|
| `hvac_strategy.py` :77, :84-591 | `LAST_SENT_TOLERANCE_F = 0.5` :77; `ProfileCapabilities` :119-148 (21 fields); `CARRIER_CAPABILITIES` :157-182; `GENERIC_CAPABILITIES` :188-210; `WriteStatus` :213-217 (APPLIED / SKIPPED_ALREADY_CORRECT / DEFERRED / FAILED); `GenericStrategy`: `observe` :277-297 builds `HoldObservation` from the RAW `preset_mode`; `last_sent` / `_record_sent` :300-310; `is_human_manual_snapshot` :313-326; `is_manual_hold` :329-337; **`feature_available` / `feature_unavailable_reason` :340-352**; the pure delegates :364-413; `release_hold` :415-434; stub `classify_person_change` :437-441; `hold_preset` :444-490. `CarrierStrategy` :493-532; `strategy_for` :551-563 (registry miss → fresh uncached Generic); `strategy_for_platform` :566; `is_manual_hold_for` :581-586; `_test_reset_cache` :589 |
| `quality/tests/test_hvac_w1c_p1_profile_contract.py` :73, :163-210 | `"manual"` literal lint glob :73; `test_profile_capabilities_field_set_frozen` :163-173; `test_strategy_capabilities_bound_per_profile` :176-182; `test_carrier_capabilities_mirror_constants` :185-195; `test_feature_available_table` :198-210 |
| `hvac.py` | `_w1c_*` helpers :118-131; `_last_emitted_range` :687 (per-ZONE, post-guard S10 pair); `_zone_state_store` :864 (HA `Store`, `hvac_zone_state`), boot restore :2002-2025, snapshot build :2372-2378; freshness call :2186; B1 enforcer :2563-2630 (ungated by any switch; writes through `strategy.set_hvac_mode`); S1 manual readers :3398-3431, :3596, :3722, :3815; S1 FAILED raise :3678-3682 and DEFERRED silent `continue` :3683-3691; **S10 DPM apply :4085-4184** (baseline from `get_seasonal_setpoints` :4089, `engine.resolve_range` :4106, `apply_setpoint_guards` :4113, throttle :4130-4133, `set_setpoints` :4153-4165, `_last_emitted_range[zone] = resolved_pair` :4176); `_zone_last_write_is_away` :4795-4809; **`_check_carrier_freshness` :7381-7603** (loops ALL zones :7409-7511, `_reload_ha_carrier_entry` :7561, age-only NM :7584-7603); **`_reload_ha_carrier_entry` :7605-7720+** (ambiguous-entry NM :7694-7709) |
| `hvac_zones.py` | `ZoneState.preset_mode` :97; `update_zone_climate_state` :612 (RAW read) |
| `hvac_preset.py` :126-160 | `get_seasonal_setpoints(preset, season=None)`: CM-options baseline only, never the S10 composition (review #1 HIGH) |
| `hvac_override.py` | raw thermostat `preset_mode` reads at :212, :1340, :2595, :3014-3015, :3498-3499, :3599-3600, :5148, :5511, :5713, :6179, :6266, :7156, :7397; direct classifier call :3636; `_transition_is_human` ~:4240-4275 (pair-ring tolerance); `_supports_heat_cool` :4618-4629 (LIVE `hvac_modes` read); side-key persistence pattern :1059-1061, `__interrupt_latch` :1310-1328 |
| `hvac_egress.py` :668, `hvac_excursion.py` :886, `coordinator_diagnostics.py` :534-535, :575, :600 | raw thermostat `preset_mode` reads; `:534-535` compares commanded vs the `actual` built at `:575` |
| `hvac_fans.py` :2034, :2314 | `preset_mode` reads on **fan** entities. Out of scope |
| `hvac_setpoint.py` :159-160, :199 | `apply_setpoint_guards` (freeze floor, `MIN_DEADBAND`); `values_before` ledger snapshot stays RAW on purpose |
| `hvac_const.py` :474, :1132-1151, :1415 | `MIN_DEADBAND` 2.0; `SEASONAL_DEFAULTS`; `CONF_HVAC_CARRIER_STALE_MAX_AGE_S` |
| `__init__.py` :1234, :1270; `switch.py` :916 | existing `ir.async_create_issue` Repair usage (pattern REUSED for §4.11) |

**Consumer grep for the scaffold (re-run by plan review #1, results held):**
- `feature_available|feature_unavailable_reason` across `custom_components/**/*.py` + `quality/**/*.py` → production
  hits ONLY the definitions (`hvac_strategy.py:340-352`). Tests: only `test_feature_available_table`.
- The 11 fields being dropped (§4.8): no read outside the dataclass and the two constants, except
  `supports_activity_setpoint` inside `feature_unavailable_reason` :348. Tests: only the field-set pin.
- `.capabilities`: read only at `hvac_strategy.py:344` and `test_strategy_capabilities_bound_per_profile`.
- Planning docs: `PLANNING_hvac_enable_custom_preset_ranges.md` :29 (U1 step 0.3) and :34
  (`test_generic_set_preset_range_zero_calls_feature_unavailable`).

### 1c. External sources (No Fabrication) — carried from REV 1, re-checked for relevance
- **HomeKit Controller** (`homeassistant/components/homekit_controller/climate.py`, `dev`, fetched 2026-10-03):
  - No preset support.
  - `target_temperature_low/high` exist only in `heat_cool`.
  - **`async_set_temperature` with `target_temp_low/high` and no `hvac_mode` kwarg, while the device is not in
    heat_cool, falls to the `else` branch and writes `TEMPERATURE_TARGET = kwargs.get("temperature")` = None.**
    URA's funnel never sends `temperature` or `hvac_mode`. This is the one command-efficiency hazard the adapter must
    own (§4.2).
- **Native ecobee** (`homeassistant/components/ecobee/climate.py`): `preset_mode` is `temp` for any non-comfort hold
  and a comfort name otherwise; `set_temperature` in heat_cool → `set_auto_temp_hold`. Native is OUT of P2 (Q3).
- **NOT verified (measured at D0b, not assumed):**
  - the HomeKit ecobee device-registry `manufacturer` / `model` strings;
  - whether a HomeKit write creates an ecobee hold, and of what type;
  - HomeKit °C rounding on readback;
  - ecobee's minimum heat/cool delta;
  - echo latency;
  - whether HA's HomeKit entity reflects a `set_hvac_mode` before the device confirms it (this matters for the
    mode-then-range sequences in §4.2).
  - whether the HomeKit entity's `last_reported` ages the way Carrier's does (irrelevant after §4.10: ecobee's
    freshness verb is a no-op).

### 1d. Memory pulled
- `feedback_thermostat_brand_layer_is_thin_command_adapter` (the ruling; REV 3 resolution of both reviews follows it).
- `feedback_extend_existing_never_rebuild` (the REV 2 thesis: HC is the spec; the adapter only translates).
- `feedback_marginal_benefit_pushback`, `feedback_measure_before_build`, `feedback_tier2plus_prior_art_scan`,
  `feedback_wire_in_anchor_mandatory`, `feedback_hollow_test_anchors`,
  `feedback_coincidental_equality_masks_concept_split`, `feedback_suppression_needs_discharge` (§4.11 deferral
  reporting has an explicit discharge).
- `project_single_user_no_backcompat`: the 2nd home goes live 2026-10-03/04, and there must be no hard-wired house
  quirks in shared paths (the §4.10 freshness move).
- `feedback_no_restart_during_sleep`.

### 1e. Prior-art scan — REUSE vs BUILD (REV 3)
| Piece | Verdict | Where |
|---|---|---|
| Every HC behaviour (S1, §9e gates, arrester, borrows, nudges, AC reset, egress, D9/CPR, B1) | **REUSE unchanged** | state-of-play §4–§9e |
| Write routing through the strategy | **REUSE** (P1 already routes every write site A2–A14 and S1) | `hvac_strategy.py:364-490` |
| "manual" predicate routing | **REUSE** (P1 `is_manual_hold_for`) | `hvac_strategy.py:581` |
| Comfort ranges per preset | **REUSE**: Seasonal Baseline Presets | `hvac_const.py:1132-1223`; `hvac_preset.get_seasonal_setpoints` |
| Composed (CPR) range per preset | **REUSE the producer** (S10 composes via `engine.resolve_range` + `apply_setpoint_guards`, `hvac.py:4089-4116`) and its hand-off verb `set_preset_range` (Batch C). **BUILD** only the ecobee-side store `ranges[(entity, P, season)]` (§4.2a). `_last_emitted_range` (`hvac.py:687`) was considered and REJECTED as the store: it is keyed by ZONE not preset, it holds compose-AWAY pairs under the house target, and §9.7 records that restore writers do not update it | §4.2a |
| Persistence of adapter state across restart | **REUSE** the `_zone_state_store` side-key pattern (`__immune_holds`, `__tao_state`, `__interrupt_latch`; `hvac.py:864`, `:2002-2025`, `:2372`). One new side-key `__w1c_adapter`, written only when non-empty | §4.2a |
| Echo recognition of URA range writes | **REUSE** the pair ring | `hvac_setpoint.py:71-98` |
| Person-vs-URA classifier | **REUSE** `classify_manual_setpoint_change` (its `tol` parameter exists) through a projected state | `hvac_override.py` ~:150-240 |
| Classifier / pair-ring tolerance per profile | **BUILD** one strategy method `echo_tolerance_f()` (Carrier/Generic = `LAST_SENT_TOLERANCE_F`) | §4.4 |
| heat_cool capability | **REUSE** the live `hvac_modes` read (`_supports_heat_cool`); no capability field | `hvac_override.py:4618` |
| Integration-staleness detector + reload | **REUSE** the body verbatim; **MOVE** the per-zone test and the reload call behind two adapter verbs (§4.10) | `hvac.py:7381-7720` |
| Deferral row shape | **REUSE** `preset_change_deferred` (W1-B) | `hvac.py` S1 site |
| Repairs | **REUSE** `ir.async_create_issue` pattern | `__init__.py:1234` |
| **Degraded-feature predicate** `feature_available` / `feature_unavailable_reason` | **DELETE** (no consumer; contradicts the ruling) | `hvac_strategy.py:340-352` |
| **`ProfileCapabilities`** | **TRIM** to 10 command / read / classify facts (§4.8) | `hvac_strategy.py:119-210` |
| **Projected preset read** `strategy.preset_of(state)` | **BUILD** (one method). Carrier/Generic = the raw attribute (byte-identical) | none exists |
| `EcobeeHomeKitStrategy` | **BUILD** (one class) | none exists |
| Per-entity resolution cache (P1 F1) | **BUILD** (small fix) | `hvac_strategy.py:554-555` |
| `zone_thermostat_profile` override | **BUILD**, minimal (parent ruling 3); Q2 asks whether to drop it | none exists |
| REV 1 gate (f), `person_hold`, `person_hold_limit`, new feature keys, B1 brand gate, S10/egress/borrow/nudge brand gates | **DROPPED** (operator ruling) | — |

### 1f. Producer / consumer
**Value 1 — projected preset of an ecobee entity.**
- **Producer:** `EcobeeHomeKitStrategy.preset_of(state)` (§4.3). It depends on:
  - the live state;
  - the adapter's `held` record (label and post-guard range of URA's last hold or pin, stamped before the wire,
    persisted §4.2a);
  - the current-season effective ranges (the restart fallback, only when `held` is absent);
  - `ECOBEE_RANGE_TOLERANCE_F` (measured at D0b).
- **Consumers:** every site in §5. Trust consumers: S1, the arrester detection paths, the `begin_excursion` snapshot,
  egress snapshot, and the compliance tracker. Display: `zone_N_status.preset_mode`.

**Value 2 — effective range for (entity, P) (REV 3).**
- **Producer:** `EcobeeHomeKitStrategy.effective_range(entity, P)` (§4.2a). Derivations: (a) the stored S10/CPR range
  for (entity, P, current season), else (b) `get_seasonal_setpoints(P)`; then `apply_setpoint_guards` and the D0b
  device min delta. One derivation wins by that precedence; (a) is fed only by `set_preset_range`. Dependency health:
  (a) is empty until Batch C converts S10 to `set_preset_range` (§4.9) — then ecobee equals Carrier pre-Batch C
  (§4.2a "before Batch C"); (b) cannot be missing (P2-C1).
- **Consumers:** `hold_preset` / `pin_preset` (what goes on the wire), the S1 no-op third clause, the
  `set_preset_range` write-now decision, and the `preset_of` restart fallback. All are inside the adapter.

### 1g. Config-first check
No setting solves this. House 2 can run with no zones (HVAC idle) until this ships. The freshness move (§4.10) is not
solvable by config either: `hvac_carrier_reload_cooldown_s = 0` is a kill switch for House 1's reload too.

---

## 2. Corrections to the parent plan (fix the parent in the same commit as this plan's approval)

| # | Parent / REV 1 / REV 2 claim | Truth | Evidence |
|---|---|---|---|
| P2-C1 | Parent REV 3 banner: "per-zone Home/Sleep/Away setpoint fields do NOT exist … no AWAY"; REV 3.2: "Missing ranges → a Repair" | House-wide ranges for Home / Sleep / Away / Vacation exist per season, with defaults. They can never be missing | `hvac_const.py:1132-1223`; `config_flow.py:7853` |
| P2-C2 | Parent P2 item 7 (single-setpoint ring, select ring) and P3 item 4 (`emit_call_service`) are needed | Not needed: URA writes only heat_cool ranges and modes on HomeKit ecobee | §3 |
| P2-C4 | "The funnel writes setpoints" is profile-neutral | On HomeKit, a range write while the device is not in heat_cool sends `temperature=None` | §1c |
| P2-C5 | — | No P1 code-review record exists in `docs/reviews/code-review/` | Glob `docs/reviews/code-review/*w1c*` |
| R2-C1 | REV 1 P2-C3 / F5: B1 overriding a person's cool/heat on ecobee is a defect to gate | **Withdrawn.** B1 does the same on Carrier by design (`hvac.py:2584-2589`) | operator ruling 2026-10-03 |
| R2-C2 | REV 1 §4.7: on ecobee every feature except hold is unavailable | **Withdrawn.** Once `preset_of` gives the HC readers Carrier's view, the features work; their preset returns are translated by the adapter | §4 |
| R2-C3 | "Ideally zero HC changes beyond P1 routing" | **Not achievable for reads.** P1 routed every WRITE and every `"manual"` comparison, but the VALUE compared is still read raw at ~19 sites. Writes need no change | §5 |
| R2-C4 | Parent §3a/§3c and P1 code: "P2 pipes `feature_available` to the degraded-feature surface"; the 21-field `ProfileCapabilities` "is what a thermostat profile can do" | **Superseded by the ruling.** Features are never gated by brand. Capabilities record only how to command, read and classify. The predicate and 11 fields are deleted (§4.8) | operator review addendum 2026-10-03; consumer grep §1b |
| R2-C5 | Batch C REV 3.3 U1: S10 checks `strategy.feature_available("cpr")` as skip step 0.3 | **Superseded.** S10 calls `set_preset_range` and branches on its `WriteStatus` (§4.9) | §4.9; Batch C plan :1215-1216 |
| **R3-C1** | REV 2 §4.2/§4.9: "the adapter's hold translation always reads the CURRENT Seasonal Baseline / CPR range"; ecobee `set_preset_range` = SKIPPED with nothing stored | **Wrong.** `get_seasonal_setpoints` (`hvac_preset.py:126-160`) returns the baseline only; a SKIPPED that stores nothing drops CPR on ecobee, and the REV 2 no-op never rewrote while the house stayed in P | plan review #1 HIGH; §4.2a |
| **R3-C2** | `_check_carrier_freshness` is Carrier-only by nature | It loops ALL zones (`hvac.py:7409`); a stale non-Carrier entity reaches the `ha_carrier` reload and the "ambiguous entry" NM (`:7694-7709`) | plan review #1 MEDIUM; §4.10 |

---

## 3. Marginal-benefit decisions (parked, not deleted)

| Piece | Decision | Revival trigger |
|---|---|---|
| Native `ecobee` integration profile | **PARK** (Q3) | A real install to measure |
| Native comfort-preset holds as a per-brand option | **PARK**. When built it is a per-brand command choice, default OFF, so ranges stay URA's default | Native profile revived and the operator wants device comforts |
| Single-setpoint ring, select ring, `emit_call_service`, `release_hold` caller | **PARK** | A heat-only/cool-only profile, or an approved hand-back |
| `climate_write.profile` ledger key | **PARK** | A diagnosis the zone sensor + entity id cannot answer |
| Per-zone comfort ranges | **PARK** (the §4.2a store is per entity only because S10/CPR is per zone; it is not a new comfort surface) | Two ecobee zones needing different BASE comforts |
| Per-profile suppression TTL consumption | **CONDITIONAL** (only if D0b p95 echo exceeds the 15 / 120 s windows) | D0b result |
| An ecobee-native staleness remedy (e.g. a `homekit_controller` reload) | **PARK**. §4.10's ecobee verb is a no-op | A measured ecobee stale-entity incident |
| The 11 deleted capability fields (§4.8) | **DELETE**, not park. Each is either live-readable from the entity (`hvac_modes`, `preset_modes`) or a feature-support flag the ruling forbids. Re-adding one later requires a named command / read / classify consumer | — |

---

## 4. Design — the adapter is the only brand-specific surface

### 4.1 Detection and caching (`hvac_strategy.py`)
- `EcobeeHomeKitStrategy(GenericStrategy)`. It is selected when the registry platform is `homekit_controller` AND the
  device manufacturer contains `ecobee` (case-insensitive; exact string read at D0a). Other `homekit_controller`
  thermostats stay Generic.
- Order: operator override `zone_thermostat_profile` (if kept, Q2) → (platform, manufacturer) → platform → Generic.
- **Per-entity cache (P1 F1):** `_RESOLVED_BY_ENTITY` keeps the resolved instance per entity for the boot. A registry
  miss on an entity resolved earlier returns that instance. An entity never resolved gets ONE cached per-entity
  Generic. The Carrier platform cache is unchanged.
  - **(plan review #1)** The per-PLATFORM cache (`_STRATEGY_BY_PLATFORM`, `hvac_strategy.py:556-562`) must NOT be used
    for `homekit_controller`: an ecobee and a non-ecobee HomeKit thermostat share the platform, so the first resolution
    would win for both. Key that platform by entity (or by (platform, manufacturer)).
  - `strategy_for_platform` (`hvac_strategy.py:566`) has zero production callers today. It cannot see the manufacturer
    and would return Generic for an ecobee. Delete it, or make it refuse `homekit_controller`. Any return site that
    needs a strategy resolves it by ENTITY.
  - `_test_reset_cache` (`hvac_strategy.py:589`) also clears `_RESOLVED_BY_ENTITY` and the ecobee adapter state
    (`held`, `ranges`). Seven test files call it or patch `_entity_platform`, and they reuse entity ids, so state that
    is not cleared would leak between tests.
- **Cache keying (PR2-7):** `_STRATEGY_BY_PLATFORM` (`hvac_strategy.py:536`) is keyed by platform. The ecobee
  instance must NOT be stored under `"homekit_controller"`, or a non-ecobee HomeKit thermostat inherits it. Key it by
  (platform, manufacturer match) or by entity. A Generic cached from a registry MISS is replaced on the first later
  HIT (a profile switch, with the flushes below). Tests get an autouse fixture that clears both caches (the
  parametrized `test_registry_miss_generic_identical_to_carrier_golden` reuses entity ids; a leaked `last_sent` would
  flip a case to SKIPPED). Manufacturer comes from the DEVICE registry (`entry.device_id`), not the entity entry.
- **Undispatchable until measured:** while the D0b constants are `None`, the ecobee profile resolves to Generic: no
  writes of its own, and one Repair "complete the ecobee check".
- **Profile switch:**
  - flush `last_sent`, `held` and `ranges` for the entity on both instances (and the persisted `__w1c_adapter` entry);
  - flush the entity's suppression stamps;
  - close every live borrow row of the zone with NO write (`return_excursion(trigger="profile_switched",
    restore_ok=None)`) (P1 F3).

### 4.2 Command verbs (the "how to command it efficiently" part)
These have the same signatures as P1 (and Batch C for `set_preset_range`). HC call sites do not change.

| Verb | Carrier (unchanged) | EcobeeHomeKit |
|---|---|---|
| `hold_preset(P)` (S1) | `set_preset_mode P` (+ funnel resume-then-pin) | Resolve `(low, high) = effective_range(entity, P)` (§4.2a; includes guards and device min delta). No range → `FAILED("no_range_for_preset")`, zero calls. Then follow the binding ordering below; `_record_sent("set_preset_mode", P)` on APPLIED so the D2.5 no-op and `_zone_last_write_is_away` work unchanged. **No-op (PR2-2 + REV 3):** SKIPPED only when `last_sent == P` AND `preset_of(state) == P` AND the live legs equal `effective_range(entity, P)` within `ECOBEE_RANGE_TOLERANCE_F` |
| `pin_preset(P)` (S4, S7, S8/S9, A10, A14, egress resume, AC-reset preset, S11/S13 returns) | delegate to `emit_set_preset_mode` | Same translation as `hold_preset` (effective range), without the no-op and without `last_sent` (P1's pure-delegate contract: caller suppression, DEFERRED/APPLIED mapping and exception propagation behave as on Carrier) |
| `set_setpoints(low, high)` (S3, S5, S6 human restore, S10 before Batch C, S12) | delegate to `emit_set_temperature` | Same delegate **behind the §4.2 mode precondition AND a both-legs-numeric precondition** (several callers pass `zone.target_temp_low`, which is None when the ecobee is not in heat_cool — e.g. `hvac_override.py:5779`, `:6086`, `:7315`, `:7789`; a one-leg call is the same `temperature=None` hazard). Failing precondition → DEFERRED, zero calls (PR2-3). `held` NOT updated, so the range reads `manual` — what a raw setpoint write does on Carrier |
| `set_preset_range(P, low, high)` (S10 / CPR, Batch C) | Batch C `CarrierStrategy.set_preset_range` (edit the device preset via `ha_carrier.set_activity_setpoint`) | **REV 3 (review #1 HIGH):** (1) store `ranges[(entity, P, season)] = (low, high)` URA-side (§4.2a) — always, before any precondition, because the store is URA state, not wire state; (2) if `held[entity]` is NOT P → `SKIPPED_ALREADY_CORRECT("stored_for_next_hold")`, zero calls; (3) if `held` is P and the live legs already equal the new `effective_range(entity, P)` → `SKIPPED_ALREADY_CORRECT("range_already_live")`, zero calls; (4) otherwise write NOW through the binding range ordering below (the caller's `gate`, `site`, `zone_id`, `reason` pass through) → APPLIED / DEFERRED / exception exactly as the range path returns. This is Carrier parity: editing the active activity on Carrier changes the live setpoints at once, and editing an inactive one changes nothing until it is held |
| `set_hvac_mode(m)` (B1, B4, AC reset, egress) | delegate to `emit_set_hvac_mode` | Same delegate |
| `release_hold` | no caller | no caller; ecobee returns `FAILED("no_device_hold_release")`, zero calls |
| `freshness_row` / `remediate_stale` (REV 3, §4.10) | today's per-zone staleness test and `ha_carrier` reload, moved verbatim | no-op: row marked `freshness: "not_applicable"`, never qualifies, never reloads, never NMs |

**The one command hazard (P2-C4).** A range write while the device is not in heat_cool sends `temperature=None` on
HomeKit. The adapter owns this inside its range-writing verbs (`hold_preset`, `pin_preset`, `set_setpoints`, the
write-now leg of `set_preset_range`):
- **Live mode is `heat_cool`** → write the range.
- **Live mode is `off`** → DEFERRED `mode_not_heat_cool`, zero calls. `off` is always deliberate (egress pause, AC
  reset, or a person), and Carrier would not change mode on a setpoint write either.
- **Live mode is `cool`/`heat`** → the builder picks one of two mechanisms from D0b P1:
  - **(i)** if HA's HomeKit entity reflects `set_hvac_mode heat_cool` immediately, DEFER as for `off`;
  - **(ii)** otherwise, send the range with `hvac_mode="heat_cool"` in the same `set_temperature` call. This needs one
    optional funnel kwarg, default None, so Carrier `service_data` stays byte-identical.

  Mechanism (i) is preferred: zero funnel change. **(PR2-5) (i) is only valid if BOTH hold:** D0b P1 shows the
  entity reads `heat_cool` when a `blocking=True` `set_hvac_mode` returns, AND every in-coroutine mode→range/pin
  sequence uses `blocking=True` for the mode write. S4's B4 mode write is `blocking=False`
  (`hvac_override.py:4745-4752`, then the pin at `:4819`), so under (i) an arrester revert from `cool` drops its pin.
  Choosing (i) therefore means either flipping B4 to blocking on ecobee only (not allowed: Carrier byte-identity) or
  accepting that the next S1 tick repairs it — the builder must state which, with a test. If neither is acceptable, (ii).
- `heat_cool` absent from the live `hvac_modes` → `FAILED("no_heat_cool_mode")` (§4.11), zero calls.

**Ordering inside every ecobee range verb (PR2-1, binding):** (1) live-mode + both-legs precondition → DEFERRED,
zero calls, `held` and `last_sent` untouched; (2) resolve the range (`hold_preset` / `pin_preset` /
`set_preset_range`: `effective_range(entity, P)`, §4.2a); (3) apply `apply_setpoint_guards` (`hvac_setpoint.py`, same
`freeze_active` the funnel will get) and the D0b device min delta, so the stamped range is the range that goes on the
wire (clamp before stamp) — `effective_range` already returns post-guard values; `set_setpoints` applies them here;
(4) stamp `held` with the POST-guard range (range verbs that hold a preset only — never `set_setpoints`);
(5) call `emit_set_temperature`; (6) on DEFERRED or exception restore the previous `held` (then re-raise / return as
P1 does); (7) `_record_sent("set_preset_mode", P)` on APPLIED only (`hold_preset` only); (8) persist `held` if it
changed (§4.2a).
`pin_preset` on ecobee ignores the caller's `emit=` (it is the preset funnel) and always uses `emit_set_temperature`.
Device min delta: when the ecobee minimum exceeds the gap, keep heat and raise cool (matches `apply_setpoint_guards`;
PR2-9).

### 4.2a Effective range — where the composed range lives (REV 3; review #1 HIGH, review #2 PR2-2)
**Definition.** `effective_range(entity, P)` = the range URA would put on the device for preset P right now:
1. `ranges[(entity, P, season_now)]` if S10 has stored one via `set_preset_range` (the CPR composition, including
   compose-overrides Batch C passes);
2. else `get_seasonal_setpoints(P)` through the injected resolver (the Seasonal Baseline);
3. then `apply_setpoint_guards(low, high, freeze_active=<live>)` and the D0b device min delta.

Carrier never calls it; on Carrier the device preset itself IS the effective range (Batch C edits it in place).

**Store.** A per-instance dict on `EcobeeHomeKitStrategy`:
- `ranges: dict[(entity, preset, season), (low, high)]`. Season in the key means a season rollover falls back to the
  new season's baseline until S10 re-composes; a stale summer composition never lands in shoulder.
- When S10/Batch C hands back the plain baseline (CPR off / override expired), the builder deletes the entry instead
  of storing a value equal to the baseline (keeps the store and the persisted key small; behaviour is identical).
- `held: dict[entity, (P, low, high)]` (REV 2, unchanged meaning).

**Persistence (restart parity).** On Carrier the composed range survives a URA restart because it lives on the
device. For parity the ecobee adapter's `held` and `ranges` are persisted:
- ONE new side-key `__w1c_adapter` in the existing `_zone_state_store` (`hvac.py:864`), shaped
  `{entity: {"held": [P, low, high] | null, "ranges": [[P, season, low, high], …]}}`.
- Saved through the existing snapshot path (`hvac.py:2372-2378`) when `held` or `ranges` change (step 8 above;
  `set_preset_range` store step), and in the shutdown snapshot.
- Restored in the boot restore (`_rehydrate_arrester_state`, `hvac.py:2001-2025`, called at `hvac.py:1277`) BEFORE
  the arrester's state listener (`setup()`, `hvac.py:1472`), the first decision cycle (`hvac.py:1572`) and the
  arrester startup audit (inside the first cycle, `hvac.py:2219`) reads R4 — order re-verified on develop @`f9379a1c5`
  by plan re-review REV 3; builder still pins it with a test.
- **Rehydrate per ENTITY, not per cached instance (re-review REV 3):** at `:1277` no strategy instance is cached yet,
  so HC resolves `strategy_for(hass, entity)` for each entity in the persisted blob and hands that entity's slice to
  that instance. A slice whose entity resolves to Generic (registry miss, or D0b constants still `None`) is KEPT
  verbatim in an HC-side pending dict and re-emitted unchanged by the snapshot builder, so a save cannot erase it;
  it is handed over on the first later ecobee resolution. The miss→hit profile switch (§4.1) must NOT flush a
  pending slice (it only flushes live adapter state of an entity whose profile actually changed from one resolved
  brand to another).
- **Written only when non-empty**, so a Carrier-only install's snapshot is byte-identical (INV-C test asserts the key
  is absent on the Carrier fixture).
- Pruned for entities no longer mapped to any zone at the SAME seam as the interrupt latch: `_handle_zm_zones_updated`
  → `_prune_interrupt_latch` (`hvac.py:5474`, `:6143`), skipped while the zone map is empty, persisted by the
  snapshot save. **Not** the zone-removal rewrite `hvac.py:5489-5516`: that loop skips every `__`-prefixed key
  (`:5510`), so it would never prune `__w1c_adapter` (REV 3 claim corrected by re-review). Covers a thermostat swap
  on a kept zone (old entity's `held`/`ranges` dropped).
- Season hygiene: on rehydrate and on season rollover, entries whose season ≠ `season_now` are dropped (they are
  unreachable until the same season next year, where a year-old composition must not land before S10 re-composes).
- No DB table, no schema change. The adapter exposes `export_state()` / `rehydrate_state(dict)`; HC calls them the
  same way it calls `export_interrupt_latch` / `rehydrate_interrupt_latch` — on every strategy instance, so there is
  no brand branch (Carrier/Generic return `{}` and ignore input).

**S1 "already correct" (aligns PR2-2).** The `hold_preset` no-op third clause compares the live legs with
`effective_range(entity, P)`. So a season rollover, a baseline edit, or a CPR change for the held preset is rewritten
on the next S1 tick even while the house stays in P. Carrier's no-op is unchanged.

**Before Batch C (P2 ships first).** S10 still calls `set_setpoints` (`hvac.py:4153`), so `ranges` stays empty and
the effective range is the baseline. On ecobee the S10 raw write reads `manual` (held mismatch) — the same thing a raw
S10 write does on Carrier today. The §9.7 S10/S1 interplay is therefore identical on both brands, and Batch C fixes it
for both. P2 adds no ecobee-specific workaround.

**Repro now covered (review #1 HIGH):** D9 ON at House 2, house in `home`, S10 (post-Batch C) composes 69/78 →
`set_preset_range(home, 69, 78)` stores it; `held` is home → write now → live 69/78, `held = (home, 69, 78)` →
`preset_of` = home; next S1 tick: effective = 69/78 = live → SKIPPED. House → sleep → S1 holds sleep's effective range
(stored sleep composition if any, else baseline). Restart → `held` and `ranges` restored → `preset_of` = home →
S1 no-op; no false override at the startup audit.

### 4.3 State read — `preset_of(state)` (the projection)
- **Carrier / Generic:** `state.attributes.get("preset_mode")`, verbatim, with the call site's existing default.
- **EcobeeHomeKit:**
  1. None / `unavailable` / `unknown` → the site's existing default.
  2. Mode `heat_cool`, both legs numeric:
     - `held[entity]` matches within `ECOBEE_RANGE_TOLERANCE_F` → its label;
     - else, **only when `held[entity]` is ABSENT** (first boot, lost store, never held), exactly ONE current-season
       effective range (stored composition or baseline, §4.2a) matches → that preset name (two candidate ranges within
       2 × tolerance of each other → no match). With `held` present, a mismatch is `manual` (PR2-4: summer home 77/70
       vs sleep 76/70 differ by one leg by 1 °F — a person's 77→76 must read `manual` and reach the arrester, not read
       `sleep`);
     - else `"manual"`.
  3. Mode not `heat_cool` → the label of `held[entity]` if any, else `""` (mirrors Carrier: a mode drift keeps the
     preset name and B1 owns the drift).
- `is_manual_hold` is inherited unchanged (`== "manual"`). `observe()` uses `preset_of` on ecobee.
- **`is_human_manual_snapshot` MUST be overridden on ecobee (PR2-6)** to Carrier's rule (`pre_preset in (None, "",
  "manual")`). The inherited Generic version (`hvac_strategy.py:313-326`) also returns True when `preset_modes` is
  empty — always true on HomeKit — which would turn every ecobee borrow return into a raw-setpoint restore. (Review #1
  notes no production caller passes `preset_modes=` today; the override still pins the rule.)

**Consequence the operator should know (Q1).** If the ecobee's own hold expires or its program moves the range, the
projection reads `manual` and the arrester treats it like a person's change on Carrier. The setup notes (D5, PR2-13)
say: hold action "until I change it", no ecobee program, Smart Home/Away, Eco+ and Follow Me off.

### 4.4 Ours-vs-person classifier
- `EcobeeHomeKitStrategy.classify_person_change` is the same delegate as Carrier's, fed projected states. The raw
  read at `hvac_override.py:212` is routed (§5 R2), and because `classify_manual_setpoint_change` is called directly
  at `hvac_override.py:3636` (no hass / entity), the builder threads either a `preset_of` callable or pre-projected
  old/new presets. Carrier passes the raw values (byte-identical).
- **Tolerance (PR2-8 + review #1 LOW, folded):** new strategy method `echo_tolerance_f()`:
  - Carrier / Generic → `LAST_SENT_TOLERANCE_F` (0.5 °F, `hvac_strategy.py:77`) — byte-identical;
  - EcobeeHomeKit → `ECOBEE_RANGE_TOLERANCE_F` (D0b).
  It feeds BOTH tolerance consumers: the `tol=` of `classify_manual_setpoint_change` at `hvac_override.py:3636`
  (within-manual) and the pair-ring comparison in `_transition_is_human` (~`hvac_override.py:4240-4275`, interrupt
  eligibility). HC reads it through `_w1c_strategy(hass, entity).echo_tolerance_f()` — a method, not a
  `.capabilities.` read, so INV-F's lint holds. The Carrier classifier code is unchanged.
- Transitions INTO manual go through the existing arrester path (changed legs vs recent URA writes).
- Echoes: the existing suppression windows + pair ring + projection. An echo of a URA pin lands on `held` and reads as
  the named preset.
- **Operator decision point (not a silent disable).** If D0b shows URA's echo cannot be told apart from a wall-unit
  change, the probe report goes to the operator before build proceeds (Q4). No code path is turned off by brand.

### 4.5 Capability facts (rung 1) — the trimmed `ProfileCapabilities` (§4.8)
| Field | Carrier (values unchanged) | Generic | EcobeeHomeKit |
|---|---|---|---|
| platform / manufacturer | `ha_carrier` / Carrier | generic / None | `homekit_controller` / ecobee (D0a) |
| hold_via | `preset` | `unsupported` | `setpoint_range` (new enum value) |
| setpoint_shape | dual_leg | dual_leg | dual_leg |
| echo_ttl_s / preset_echo_ttl_s | 15 / 120 | 15 / 120 | from D0b |
| write_rate_min_interval_s / retry_interval_s | 60 / 0 | 60 / 0 | from D0b / 0 |
| person_change_shape / person_change_match_window_s | heat_cool_both_legs / None | **heat_cool_both_legs / None** (F2) | heat_cool_both_legs / None |

These facts are consumed only by the adapter itself: `hold_via` selects the hold translation, and the timings by the
conditional C1. No HC site branches on a capability. The tolerance (§4.4) is a method, not an 11th field.

**Immune-hold sunset** reads `next_activity_time`, which ecobee lacks. Review #1 confirmed (`hvac_override.py:4094`,
`isinstance(nxt_raw, str) and nxt_raw` inside a try) that absence reads as "no sunset signal" and never raises. This is
a read-safety fact, not a feature gate.

### 4.6 What does NOT change
- B1, S1 and §9e gates, the arrester, borrows and their primitive, nudges / AC reset, egress, D9/CPR.
- The funnels' service_data (except §4.2 option (ii), if chosen), the pair ring, and every switch default.
- No new user-facing switch. A feature the operator turns off on House 2 uses the switch it already has.
- The Carrier freshness / reload behaviour on Carrier zones (moved, not changed — §4.10).

### 4.7 P1 review findings folded in
| # | Finding | Fix |
|---|---|---|
| F1 | Generic no-op never fires (registry miss → fresh uncached Generic; A-L2) | Per-entity cache (§4.1). Test: two S1 ticks on a registry-miss entity → second SKIPPED |
| F2 | `GENERIC_CAPABILITIES` inconsistent: dual_leg but `person_change_shape=single_setpoint`, window 600 (A-L3) | Generic = heat_cool_both_legs / None (§4.5). Test pins consistency for every profile |
| F3 | `_auto_return` resolves the profile from the CURRENT entity (B-L2) | Close live borrow rows at profile switch (§4.1) |
| F4 | S1 FAILED raises `RuntimeError` → ERROR every tick; preset suppression never rolled back (B-L1) | FAILED → `unsuppress`, one INFO per (zone, reason) per boot, one `preset_change_deferred` row, `continue`. **Scope (plan review #1):** only for capability reasons (`no_presets_supported`, `no_range_for_preset`, and REV 3 `no_heat_cool_mode`). `FAILED("emit_raised")` (a Carrier wire exception, `hvac_strategy.py:484-486`) keeps today's `RuntimeError` path (`hvac.py:3678-3682`) unchanged; otherwise INV-C breaks outside its one named exception. Test: 3 ticks on a no-presets Generic → 0 ERROR, 1 INFO, empty suppression map. Test: a Carrier `emit_raised` still raises |
| ~~F5~~ | ~~B1 overrides a person's heat/cool~~ | **Withdrawn (R2-C1)** |

### 4.8 P1 scaffold removal (operator review addendum, 2026-10-03)
P1 shipped a feature-gating scaffold that contradicts the thin-adapter ruling: features needing a named preset were
marked unavailable on brands without one, and CPR was marked unavailable without Carrier's activity-setpoint service.
It has NO production consumer (§1b grep), so removing it changes no behaviour. P2 deletes it:

1. **Delete** `GenericStrategy.feature_available` and `feature_unavailable_reason` (`hvac_strategy.py:340-352`).
   - Features that need a named preset call `hold_preset` / `pin_preset`, and the adapter translates (ecobee: preset →
     effective range).
   - A thermostat that genuinely cannot hold (Generic) reports it through the verb's own `WriteResult`
     (`FAILED("no_presets_supported")`, handled per F4). It does not use a pre-check.
2. **Trim `ProfileCapabilities`** from 21 to 10 fields:
   - **Keep:** `platform`, `manufacturer`, `hold_via`, `setpoint_shape`, `echo_ttl_s`, `preset_echo_ttl_s`,
     `write_rate_min_interval_s`, `retry_interval_s`, `person_change_shape`, `person_change_match_window_s`.
   - **Delete:** `has_named_presets`, `named_preset_vocabulary`, `has_heat_cool_mode`, `supports_resume`,
     `supports_activity_setpoint`, `has_next_activity_time`, `has_write_confirmation_feed`, `has_mode_select`,
     `mode_select_options`, `hold_release_mechanism`, `equipment_telemetry`.
   - Why each deleted field goes:
     - live-readable from the entity, and the live read already wins: `hvac_modes` via `_supports_heat_cool`;
       `preset_modes` via the funnel's resume capability check (`hvac_setpoint.py`) and `observe()`;
     - feature-support flags the ruling forbids: `supports_activity_setpoint`, `has_next_activity_time`;
     - placeholders for parked work with no consumer: mode select, release mechanism, write-confirmation feed
       (`HVAC-WRITE-CONFIRMATION-ORACLE-1`), equipment telemetry (P4).
   - Docstring: "how this brand is commanded, read and classified — never whether a URA feature runs".
3. **Update the module docstring** (`hvac_strategy.py:39`) and the `ProfileCapabilities` / Generic comments
   (:121-126, :184-187) that promise a "degraded-feature surface".
4. **AST lint** (extend `test_hvac_w1c_p1_profile_contract.py`): no attribute named `feature_available` /
   `feature_unavailable_reason` exists on any strategy, and no module under `domain_coordinators/` reads
   `.capabilities.` except `hvac_strategy.py`. This stops the scaffold coming back through a call site.

**Tests changed by §4.8** (all in `quality/tests/test_hvac_w1c_p1_profile_contract.py`; `quality/tests` grep found no
other user):
| Test | Change |
|---|---|
| `test_profile_capabilities_field_set_frozen` :163-173 | Re-pin to the 10-field list (order as above) |
| `test_strategy_capabilities_bound_per_profile` :176-182 | Keep the identity asserts. `GENERIC_CAPABILITIES.person_change_match_window_s == 600` → `is None` (F2). Add `EcobeeHomeKitStrategy().capabilities.hold_via == "setpoint_range"` |
| `test_carrier_capabilities_mirror_constants` :185-195 | **Unchanged** (all three fields are kept) — it is the guard that the trim did not touch the Carrier timings |
| `test_feature_available_table` :198-210 | **Delete.** Replaced by the absence lint (item 4) |
| NEW `test_profile_capabilities_internally_consistent` | Per profile: `hold_via ∈ {preset, setpoint_range, unsupported}`; shape ↔ person-change shape; window None (F2) |

INV-C is unaffected: none of the deleted symbols is read on any Carrier path. The 168 goldens replay unchanged.

### 4.9 Batch C (Custom Preset Ranges) interface — what P2 hands it
- The Batch C plan REV 3.3 U1 (`PLANNING_hvac_enable_custom_preset_ranges.md:29`) adds S10 skip "step 0.3:
  `strategy.feature_available("cpr")`". That symbol no longer exists after P2 (§4.8), and its own operator-ruling note
  (:1215-1216) already supersedes it.
- **The interface:** S10 calls `strategy.set_preset_range(hass, entity, P, low, high, gate=…, zone_id, site, reason)`
  and branches on `.status` (Batch C :24 already forbids `_w1c_applied`):
  - Carrier: Batch C's own implementation (unchanged by P2).
  - Generic: Batch C's `FAILED("preset_range_unsupported")`, zero calls.
  - EcobeeHomeKit (REV 3, §4.2 / §4.2a): stores the range URA-side, then APPLIED (written now, the zone holds P),
    `SKIPPED_ALREADY_CORRECT("stored_for_next_hold" | "range_already_live")` (zero calls), or DEFERRED (mode
    precondition or the caller's gate; the range stays stored and the next hold carries it).
  - **CPR OFF / restore-originals (re-review REV 3).** Batch C §3.4 restores a captured device "original" while
    switch 01 is OFF. On ecobee there is no device preset, and S10 does not run the apply pass while OFF, so without a
    rule the stored composition would be carried by every S1 hold forever (Carrier gets its originals back; ecobee
    would not — an INV-P break). Rule: the ecobee "original" of every preset is its Seasonal Baseline. Batch C reads
    the snapshot through the adapter (no brand branch); on ecobee that read returns the baseline, so the restore call
    `set_preset_range(P, baseline)` DELETES the entry (§4.2a delete-on-baseline), and the restore-confirmation read
    matches. Test: CPR ON stores 69/78 for home → OFF → next S1 home hold writes the baseline and `ranges` is empty.
  - **Batch C must treat both ecobee SKIPPED reasons as success** (record its throttle entry, no retry, no
    `call_failed` latch) and DEFERRED as it treats a Carrier gate deferral.
- **Sequencing:** whichever of P2 and Batch C builds second adds its half:
  - Batch C first → P2 adds `EcobeeHomeKitStrategy.set_preset_range` and deletes the U1 step 0.3 if it shipped.
  - P2 first → Batch C builds against the verb shape directly and drops step 0.3 and the test
    `test_generic_set_preset_range_zero_calls_feature_unavailable` (rename to `..._unsupported`). P2 ships the ecobee
    `set_preset_range` with unit tests even though S10 does not call it yet (§4.2a "Before Batch C").
- **Open interaction for Batch C's reviewers:** compose-AWAY. S10 composes `away` for an empty established zone while
  the house target is `home` (`hvac.py:4073-4075`). Batch C decides which preset key it passes for that case. If it
  passes `away`, the ecobee store keys the composed range under `away`; S1 (which already holds `away` on an empty
  zone through row-1) then carries it. If Batch C instead writes compose-away through `set_setpoints`, ecobee reads
  `manual` — identical to Carrier. Either way, no P2 action.
- **Action in this commit:** add a one-line pointer in the Batch C plan's ruling note to §4.9 here (doc edit only).

### 4.10 Carrier freshness / reload as an adapter verb pair (REV 3; review #1 MEDIUM)
**Problem.** `_check_carrier_freshness` (`hvac.py:7381`) scans every zone. A stale non-Carrier entity qualifies, and
`_reload_ha_carrier_entry` then finds 0 `ha_carrier` entries and sends "Carrier reload skipped - ambiguous entry"
(`:7694-7709`); the age-only "Carrier climate stale" NM (`:7584-7603`) also names it. That is a Carrier repair command
in a shared path.

**Design (no brand branch in HC).**
- `strategy.freshness_row(hass, zone, *, max_age_s, require_corroboration, span_kw_fn, now_utc) -> dict`:
  - **Carrier:** the per-zone body of the loop (`hvac.py:7421-7511`) moved verbatim: same row keys, same staleness,
    corroboration and qualifier logic. Returns the row plus `qualifies: bool`.
  - **Generic / EcobeeHomeKit:** returns the row with `state` and `freshness: "not_applicable"`, `stale: False`,
    `qualifies: False`. No age is computed (so it never contributes to `worst_age`, `stale_count`, the trip-wire or
    the age-only NM).
- `strategy.remediate_stale(hass, qualifier_zones, *, reload_fn)`:
  - **Carrier:** `await reload_fn(qualifier_zones)` — `reload_fn` is the existing `_reload_ha_carrier_entry`, which
    stays in `hvac.py` unchanged (its lock, counters, cooldown, NMs and the parent-reload safety invariant are
    coordinator state). It is reachable only through the Carrier adapter.
  - **Generic / EcobeeHomeKit:** no-op, no NM.
- HC loop: resolve the strategy per zone, collect rows, group qualifier zones by strategy instance, call
  `remediate_stale` once per instance that has qualifiers. The in-flight fence (`:7550-7561`), the time-based settle
  counter and the D3 trip-wire run unchanged on the (Carrier-only, by construction) qualifier list.
- **Carrier byte-identity:** for an all-Carrier install, the rows, counters, reload calls and NMs are identical
  (golden: run the existing freshness tests unchanged). Non-Carrier rows add one key (`freshness`) that Carrier rows
  never carry.
- **INV-F lint:** with this move, `hvac.py` needs no allowlist entry for `_check_carrier_freshness` / `:7689`
  (review #1's suggested allowlist is withdrawn). `CARRIER_INTEGRATION_DOMAIN` inside `_reload_ha_carrier_entry` is
  not a strategy/platform comparison and stays.
- Option names (`hvac_carrier_stale_max_age_s` etc.) stay as-is (renaming is a migration with no benefit).

### 4.11 Deferral reporting and the "never reaches heat_cool" failure (REV 3; PR2-10)
- **DEFERRED(`mode_not_heat_cool`) at S1** today rolls back suppression and `continue`s silently (`hvac.py:3683-3691`
  assumes the chokepoint logged a row; on ecobee nothing is logged). REV 3: reuse the F4 shape — one INFO and one
  `preset_change_deferred` row per (zone, reason) per EPISODE. Episode opens on the first deferral; **discharge:** it
  closes on the first S1 tick for that zone that returns APPLIED or SKIPPED (or at restart). Applies to every
  strategy's DEFERRED with a reason the chokepoint did not already ledger (concretely: every reason except
  `gate_deferred`, the only DEFERRED a Carrier/Generic verb returns — `hvac_strategy.py:362`, `:488` — whose row
  `comfort_delay_deferred_write` is already written by `_log_deferred_write`, `hvac_setpoint.py:455-466`,
  `:565-576`; re-review REV 3), so it is brand-neutral; on Carrier the
  existing deferral reasons are already ledgered by the chokepoint, which the builder confirms with a golden (if any
  Carrier DEFERRED path is not ledgered today, its new row is a second reviewed INV-C exception — builder must report
  it, not silently add it).
- **`heat_cool` not in the live `hvac_modes`** (Auto heat/cool disabled on the ecobee): every ecobee range verb
  returns `FAILED("no_heat_cool_mode")`, zero calls. S1 handles it per F4 (INFO, `preset_change_deferred`, continue).
  Plus ONE Repair per entity: "<thermostat> cannot run heat/cool — enable Auto heat/cool on the thermostat". The
  Repair is deleted on the first tick that reads `heat_cool` in `hvac_modes`.
- **Advertised but never reached:** `heat_cool` is in `hvac_modes`, yet the live mode stays `cool` / `heat` for
  `ECOBEE_HEAT_COOL_STUCK_TICKS` consecutive S1 ticks with a `mode_not_heat_cool` deferral after B1 tried to fix it.
  Then: the same Repair (wording "did not switch to heat/cool"), and the S1 result for that zone escalates from
  DEFERRED to `FAILED("heat_cool_not_reached")` (F4 path). `off` is excluded: it is deliberate (egress pause, AC
  reset, a person) and can last hours. Discharge: first tick reading `heat_cool` → Repair deleted, streak reset.
- The streak counter and Repair live in the adapter (keyed by entity), not in HC. The B1 enforcer itself is
  unchanged. This is a verb outcome, not a feature gate (INV-F).

---

## 5. HC call sites that change — exactly this list

**Writes: NONE.** P1 already routes every write site through the strategy. The AST funnel lint stays green.

**Reads: one mechanical pass.** Each raw thermostat `preset_mode` read becomes `_w1c_strategy(hass,
entity).preset_of(state, default=<the site's existing default>)`. The P1 AST lint is extended to forbid new raw
thermostat `preset_mode` reads outside `hvac_strategy.py` and the allowlist. **The lint's glob must cover
`coordinator_diagnostics.py` (R16) as well as `hvac*.py`.** P1's `"manual"` literal lint scans only `hvac*.py`
(`test_hvac_w1c_p1_profile_contract.py:73`). `sensor.py` / `binary_sensor.py` read only `zone.preset_mode` (R1-fed,
`sensor.py:12845`, `:12861`). They need no routing but should be in the lint scope.

| # | Site (`develop` @ `8a4619b32`) | Role |
|---|---|---|
| R1 | `hvac_zones.py:612` `update_zone_climate_state` | **Hub.** Feeds `zone.preset_mode` for every `hvac.py` reader (S1 :3398-3431, :3596, :3722, :3815; D2.5; ledgers; `zone_N_status`) |
| R2 | `hvac_override.py:212` | within-manual classifier. **It is called DIRECTLY at `hvac_override.py:3636`, not through `strategy.classify_person_change`, which has no production caller.** Its signature has no `hass` / entity. The builder threads a projection, either as a `preset_of` callable parameter or as pre-projected old/new presets, AND passes `tol=strategy.echo_tolerance_f()` (§4.4). Carrier passes the raw values and 0.5 (byte-identical) |
| R3 | `hvac_override.py:1340` | `_latch_state_discharges`, the interrupt-latch discharge predicate (§9e N1). Trust: a raw None on ecobee would never discharge the latch |
| R4 | `hvac_override.py:2595` | startup audit (must run after the §4.2a rehydrate) |
| R5 | `hvac_override.py:3014-3015` | mid-window preset passthrough |
| R6 | `hvac_override.py:3498-3499` | episode-boundary read |
| R7 | `hvac_override.py:3599-3600` | `_handle_climate_change` into/within-manual |
| R8 | `hvac_override.py:5148` | AC-reset pre-state snapshot |
| R9 | `hvac_override.py:5511` | `hard_reset_completed` telemetry `_post_preset` (display/ledger only) |
| R10 | `hvac_override.py:5713` | nudge start snapshot |
| R11 | `hvac_override.py:6179`, `:6266` | nudge restore telemetry / settled verdict |
| R12 | `hvac_override.py:7156` | hard-reset pre snapshot |
| R13 | `hvac_override.py:7397` | cancel-nudge snapshot |
| R14 | `hvac_egress.py:668` | egress saved preset |
| R15 | `hvac_excursion.py:886` | `begin_excursion` `pre_preset` snapshot (drives `is_human_manual_snapshot` and C26) |
| R16 | `coordinator_diagnostics.py:575`, `:600` | compliance tracker actual / override source. **PR2-11 confirmed:** the commanded-vs-actual comparison at `:534-535` consumes the `actual` built at `:575`, so routing R16 covers it; D3 adds one assertion that an ecobee zone holding home reports actual = home there |

**Tolerance sites (REV 3, §4.4):**
- T1 `hvac_override.py:3636` — `tol=` of `classify_manual_setpoint_change` (same edit as R2).
- T2 `_transition_is_human` (~`hvac_override.py:4240-4275`) — the pair-ring comparison uses
  `strategy.echo_tolerance_f()` instead of the module constant. Builder re-greps `LAST_SENT_TOLERANCE_F` across
  `domain_coordinators/` and routes every pair-ring / classifier comparison; any other use is listed with a reason.

**Freshness (REV 3, §4.10):** `hvac.py:7381-7511` (loop body → `freshness_row`), `:7561` (→ `remediate_stale`).
`_reload_ha_carrier_entry` (`:7605`) unchanged.

**Persistence (REV 3, §4.2a):** `hvac.py:2002-2025` (rehydrate), `:2372` (export), `:5489-5516` (prune).

**Excluded on purpose:**
- `hvac_setpoint.py:199`: ledger `values_before` stays raw.
- `hvac_fans.py:2034`, `:2314`: fan entities.

**Scaffold removal (§4.8):**
- `hvac_strategy.py` only (:39, :119-210, :340-352).
- The test file `quality/tests/test_hvac_w1c_p1_profile_contract.py` (:163-210).
- No HC call site, because there are no consumers.

**Conditional (D0b-gated):**
- C1: suppression TTL read (`hvac_override.py:133` / `:173`) takes the profile's `echo_ttl_s` (mandatory if G3 fails).
- C2: the funnel `hvac_mode` kwarg, only for §4.2 option (ii).

Plan reviewers must re-grep `preset_mode`, `feature_available`, `.capabilities`, `LAST_SENT_TOLERANCE_F`,
`_check_carrier_freshness`, `_zone_state_store` and every deleted field name rather than trust these lists.

---

## 6. Falsifiable invariants (for reviewer D to break)
- **INV-C (Carrier byte-identity).** For any `ha_carrier` zone, the following are identical to v5.103.36: every
  `climate` call; every ledger row (`climate_write`, `ura_activity_log` incl. `gate_snapshot`, `ac_ramp_events`,
  `hvac_excursion_events`); the suppression store; the `_zone_state_store` snapshot (no `__w1c_adapter` key); the
  freshness snapshot, reload calls and Carrier NMs; the in-memory state; and every R-site read value. This holds
  across restart and mid-borrow reload. The 168 goldens replay unchanged and are not regenerated.
  - **Single named exception:** the F4 S1 FAILED row (reviewed one-row diff). A second exception is allowed ONLY if
    §4.11 finds an un-ledgered Carrier DEFERRED path, and only after review.
  - The §4.8 deletions add no exception.
- **INV-P (parity).** An ecobee zone and a Carrier fixture fed equivalent states (Carrier `preset_mode` =
  `preset_of(ecobee state)`, the same legs and events) produce the same HC decision trace. The only difference is the
  translated wire verb. Repro shapes:
  - URA pins `sleep` → echo → no `override_detected`;
  - a wall change to 72/68 under home → booked HUMAN → the arrester acts per delta as on Carrier;
  - nudge start → reads `manual` → restore pin → reads the named preset;
  - restart at the Home range → reads `home` → S1 no-op;
  - restart with a person's 72/68 → reads `manual` → §9e decides as on Carrier;
  - **(REV 3, replaces the false REV 2 bullet)** S10 `set_preset_range(home, 69, 78)` while the zone holds home →
    written now, reads `home`, next S1 no-op (Carrier: activity edited in place, reads `home`); the same while the
    zone holds sleep → stored, zero calls, and the next S1 `home` hold writes 69/78;
  - **(REV 3)** restart with a stored composition live → reads the held preset, no `override_detected`;
  - **(REV 3)** season rollover with the house in home → next S1 tick writes the new season's effective range.
- **INV-F (no brand feature gate).** No HC code path chooses whether a URA feature runs from the thermostat brand or
  from a capability field. It may only use a verb's `WriteResult`, a strategy method's return value, or a live entity
  read.
  - Falsified by: any `feature_available`-style predicate, or any `.capabilities.` read outside `hvac_strategy.py`
    (the AST lint, §4.8 item 4).
  - **(plan review #1)** The lint also forbids, outside `hvac_strategy.py`, any `.platform` read on a strategy, any
    `isinstance(..., <Strategy class>)`, and any comparison against `CARRIER_PLATFORM`. **REV 3:** no allowlist
    entry — the freshness/reload path is behind adapter verbs (§4.10).
- **INV-E2 (ecobee wire whitelist).** URA never calls the following on a HomeKit ecobee:
  - `climate.set_preset_mode`;
  - `set_temperature` with a `temperature` key;
  - a range while the live mode is not heat_cool, unless `hvac_mode="heat_cool"` is in the same call (option ii);
  - any non-`climate` service (including `ha_carrier` / `homekit_controller` reloads — §4.10).
- **INV-G (Generic stays blocked).** A Generic zone whose entity advertises no `preset_modes` makes zero
  `climate.set_preset_mode` calls, including `resume`. S1 on it returns `FAILED("no_presets_supported")` and makes
  zero calls. (Restated by plan review #1. Under the ruling, Generic still runs B1, nudges and borrow setpoint writes
  like any brand.)
- **INV-R (REV 3, effective range).** On an ecobee zone, whenever S1 reports SKIPPED for preset P, the live legs equal
  `effective_range(entity, P)` within `ECOBEE_RANGE_TOLERANCE_F`. Falsified by any reachable state where a stored
  composition, a baseline edit, or a season change for the held preset is not on the device after one S1 tick in
  heat_cool.

## 7. Deliverables

### D0 — Measure before build (gates D1–D6)
**D0a: read-only (orchestrator, House 2 REST; token held locally, never committed).**
- Device registry `manufacturer` / `model` / `sw_version`.
- `hvac_modes` and `supported_features`.
- Whether legs appear in heat_cool.
- 24 h of state changes.

Report: `docs/planning/AUDIT_house2_ecobee_probe_2026_10_0x.md`.

**D0b: supervised live probe — validates the ADAPTER CONTRACT (command + classify).** Operator-run, operator at the
thermostat, House 2 HVAC coordinator OFF. Script `scripts/probes/ecobee_write_probe.py`. Each step needs an operator
`y`; events are logged with monotonic timestamps. The procedure, safety additions, extra measurements and the G1–G7
go/no-go are in the "D0b go/no-go criteria" appendix of plan review #2 below, which is binding.
- **P0:** the operator reads the hold action, the min delta, whether a program is running, whether Auto heat/cool
  is enabled, and Smart Home/Away, Eco+ and Follow Me states (PR2-13).
- **P1 (mode command):** `set_hvac_mode heat_cool` from `cool`. Does the entity reflect it at once (§4.2 i/ii)? What
  is the latency? Do the legs appear?
- **P2 (range command + echo):** five range writes ≥ 2 min apart. Measures latency p50/p95/max, readback rounding
  (also against ±0.5 °F, review #1 LOW), and the hold type shown.
- **P3:** narrow range 72/74 → widened? Then 72/70 (PR2-9).
- **P4 (classify):** wall-unit setpoint change. Measures the shape, the latency, and whether it is separable from the
  P2 echoes by value and timing.
- **P5:** wall-unit mode change and back.
- **P6:** app "Resume schedule" → its signature.
- **P7 (optional):** one hold expiry or program transition.

Outputs: `ECOBEE_RANGE_TOLERANCE_F` (also the §4.4 `echo_tolerance_f`), echo p95 and the C1 verdict, deadband
minimum, the §4.2 (i)/(ii) verdict, and the §4.4 separability verdict.

**Acceptance:**
- **Verify:** a value table with n.
- **Verify:** a written separability verdict. NOT separable → operator (Q4) before build.
- **Verify:** G1–G7 each marked GO / NO-GO with evidence.
- **Live:** this IS the live step.

### D1 — Detection, per-entity cache, override, Repairs, profile switch (§4.1, F1, F3)
- **Test:** registry fixtures resolve as specified: Carrier / HomeKit-ecobee / HomeKit-non-ecobee / native ecobee
  (→ Generic) / made-up brand / no entry. Carrier goes through the unchanged platform cache (identity-asserted).
- **Test:** an ecobee and a non-ecobee HomeKit entity resolved in either order each get their own profile (PR2-7).
- **Test:** `test_w1c_p2_registry_miss_generic_noop_persists`.
- **Test:** undispatchable → Generic + Repair, zero writes.
- **Test:** a profile switch flushes `last_sent`, `held`, `ranges`, the persisted entry, suppression and live borrow
  rows.
- **Sensor:** `zone_{n}_status` attrs `thermostat_profile`, `profile_source`.
- **Live (House 1):** three zones `carrier` / `detected`; zero new Repairs.

### D2 — Command verbs + effective range (§4.2, §4.2a, §4.11)
- **Test:** S1 `home` on a HomeKit fixture in heat_cool → one `set_temperature {70, 77}` via the funnel; one
  `climate_write` row; pair ring (70, 77); `held` set before the wire with post-guard values.
- **Test:** the same tick again → SKIPPED.
- **Test (PR2-2/REV 3):** baseline edit, season rollover, and stored composition for the held preset each → the next
  S1 tick writes the new effective range; then SKIPPED.
- **Test (REV 3, review #1 HIGH):** `set_preset_range(home, 69, 78)` with `held` = home in heat_cool → APPLIED, one
  write, `held = (home, 69, 78)`; with `held` = sleep → `SKIPPED_ALREADY_CORRECT("stored_for_next_hold")`, zero calls,
  and the next `hold_preset(home)` writes 69/78; equal live range → `"range_already_live"`; mode `off` → DEFERRED, range
  still stored; passing the baseline back deletes the entry.
- **Test (REV 3):** persistence round-trip — export, new adapter, rehydrate → same `held` / `ranges`; boot restore
  runs before the first cycle and the startup audit; a Carrier-only snapshot has no `__w1c_adapter` key; zone
  removal prunes it.
- **Test:** every `pin_preset` caller (S4 / S7 / A10 / A14 / egress resume / AC-reset preset) → a range write of the
  effective range, never `set_preset_mode`.
- **Test:** `set_setpoints` leaves `held` untouched; a one-leg / None-leg call → DEFERRED, zero calls (PR2-3).
- **Test:** mode `off` → DEFERRED, zero calls.
- **Test:** mode `cool` → the chosen (i)/(ii) behaviour, including the S4 B4-non-blocking outcome (PR2-5).
- **Test:** `_zone_last_write_is_away` true after an applied `away` hold.
- **Test (PR2-10, §4.11):** 3 S1 ticks DEFERRED `mode_not_heat_cool` → 1 INFO, 1 `preset_change_deferred` row; an
  APPLIED tick closes the episode, a later deferral opens a new one. `hvac_modes` without `heat_cool` → `FAILED
  ("no_heat_cool_mode")`, zero calls, one Repair, Repair deleted when `heat_cool` appears. `cool` held for
  `ECOBEE_HEAT_COOL_STUCK_TICKS` ticks → Repair + `FAILED("heat_cool_not_reached")`; `off` for the same span → no
  Repair.
- **Mutation drills:**
  - remove the mode precondition → the INV-E2 test fails;
  - record `held` after the wire → the D3 echo test fails;
  - make `effective_range` return the baseline only → the review #1 HIGH test fails;
  - drop the no-op third clause → the season-rollover test fails;
  - skip the rehydrate → the restart-with-composition test fails.

### D3 — Projection + classifier + tolerance (§4.3, §4.4, §5 R1–R16, T1–T2)
- **Test:** table-driven `preset_of` over every §4.3 row, including tolerance edges, `held` present vs absent, and
  duplicate candidate ranges → no match.
- **Test:** the INV-P harness (one scenario list, Carrier vs ecobee fixture, decision traces compared field by field),
  including the three REV 3 bullets.
- **Test:** each R-site returns the identical value on Carrier (goldens) and the projection on ecobee. Each R-site
  gets one site-anchored test. R16 test also asserts the `:534-535` comparison (PR2-11).
- **Test (PR2-8):** an ecobee echo rounded by more than 0.5 °F but within `ECOBEE_RANGE_TOLERANCE_F` is classified
  `ura_echo` at T1 and is not interrupt-eligible at T2; on Carrier the same values use 0.5 (goldens unchanged).
- **Mutation drills:** reverting R1 / R7 / R15 to a raw read turns its own test red; reverting T1 or T2 to the module
  constant turns the PR2-8 test red.
- **Lint:** no raw thermostat `preset_mode` read outside `hvac_strategy.py` + allowlist.

### D4 — P1 scaffold removal + F2 + F4 (§4.7, §4.8)
- **Code:** §4.8 items 1–4.
- **Tests:** the §4.8 test table; `test_w1c_p2_s1_failed_no_error_spam`; Carrier `emit_raised` still raises.
- **Golden:** the single reviewed F4 row delta; the 168 goldens otherwise replay unchanged after the deletion.
- **Mutation drill:** re-add a `feature_available` method on `GenericStrategy` → the absence lint fails. Add a
  `strategy.capabilities.hold_via` read in `hvac.py` → the `.capabilities` lint fails. Add `if strategy.platform ==
  CARRIER_PLATFORM` in `hvac.py` → the INV-F lint fails.
- **Verify:** `grep -rn "feature_available\|feature_unavailable_reason" custom_components/` returns nothing.

### D5 — Docs
- State-of-play:
  - header line;
  - §4.1 (adapter row);
  - §4.4 (read model: `preset_of`, effective range);
  - §5 → an "ecobee/HomeKit facts" companion table from D0b;
  - §10: C30 = P2-C1; C31 = R2-C3; C32 = R2-C4 ("P1's `feature_available` / capability flags were the planned
    degraded-feature surface" — superseded, deleted unconsumed); C33 = R3-C1; C34 = R3-C2.
- Parent plan banner pointing here.
- Batch C plan pointer (§4.9), including "treat ecobee SKIPPED reasons as success" and the compose-away key question.
- `README_v5.103.x.md` with a Live section.
- **Ecobee setup notes (PR2-13):** hold action "until I change it"; no ecobee program/schedule; Auto heat/cool
  enabled; Smart Home/Away, Eco+ (including its schedule/peak-relief features) and Follow Me OFF. Each of these moves
  setpoints by itself and would read as a person (Q1).

### D6 — Freshness / reload adapter verbs (§4.10; REV 3)
- **Code:** `freshness_row` / `remediate_stale` on the strategy; HC loop rewritten to call them; `_reload_ha_carrier_
  entry` unchanged.
- **Test:** the existing Carrier freshness / reload / trip-wire tests pass unchanged (byte-identity of rows, counters,
  reload calls, NMs).
- **Test:** an ecobee zone with `last_reported` older than `hvac_carrier_stale_max_age_s` → row `freshness:
  "not_applicable"`, `stale_count` 0, no reload, no NM.
- **Test:** a mixed install (one Carrier stale + one ecobee stale) → exactly the Carrier zone qualifies, one reload,
  no ambiguous-entry NM.
- **Mutation drill:** make the ecobee `freshness_row` delegate to Carrier's → the ecobee test fails.
- **Live (House 2, coordinator ON):** no "Carrier" NM in the first 24 h of NM history (one-shot query at disposition).

**Live acceptance (post-deploy):**
- **House 1:** `SELECT DISTINCT verb, site, json_extract(values_after,'$')` key sets equal before vs after; zero new
  Repairs; zones show `carrier`; `hvac_zone_state` store has no `__w1c_adapter` key.
- **House 2** (operator-gated, coordinator ON):
  - A Home → Sleep → Home walk gives exactly 3 S1 `set_temperature` rows with the effective ranges, and
    `zone_1_status.preset_mode` reads home → sleep → home.
  - A wall-unit change gives one `override_detected` row matching what Carrier does with the same switches.
  - Zero `set_preset_mode` rows; zero Carrier NMs.
  - After an HA restart (house awake), `zone_1_status.preset_mode` reads the held preset and no `override_detected`
    row is written at boot.
- **Discrimination:**
  - a broken projection shows S1 rewriting the same range every tick;
  - a broken effective-range resolver shows S1 SKIPPED while the live range differs from the composition / baseline;
  - a broken classifier shows the wall change booked as `ura_echo`, or URA's own write booked as an override.

## 8. Knobs
| Name | Rung | Default | Why |
|---|---|---|---|
| `zone_thermostat_profile` | 2 (Manage Zones → Thermostat, Advanced) | absent = detect | set-once; kill switch for a wrong detection (Q2) |
| `ECOBEE_RANGE_TOLERANCE_F` | 1 | from D0b | physics; also the ecobee `echo_tolerance_f()` |
| `ECOBEE_HEAT_COOL_STUCK_TICKS` | 1 (`hvac_const.py`) | 3 (= 15 min at the 5-min tick; B1 gets two chances) | protocol window for §4.11 escalation; a change needs review. 0 is NOT a kill switch (the Repair for an absent `heat_cool` mode is unconditional) |
| ecobee `echo_ttl_s` / `preset_echo_ttl_s` / `write_rate_min_interval_s` | 1 (`ProfileCapabilities`) | from D0b | protocol |
| Comfort ranges | REUSED rung 2 (Seasonal Baseline Presets / CPR) | existing | URA's opinionated default |
| Every HC feature switch | REUSED | unchanged URA defaults | the ruling |
| `hvac_carrier_stale_max_age_s` and siblings | REUSED, unchanged | existing | now consumed only by the Carrier adapter |

No new Number / Switch entities. No inline literals.

## 9. Non-goals
- No brand gating of any HC feature, and no capability-based feature predicate (INV-F).
- No new person-hold concept, no new user switch.
- No native ecobee, no select/button writes, no `release_hold` caller, no ecobee program editing.
- No humidity / fan_mode control.
- No change to the borrow primitive, arrester state machine, pair-ring shape, or the Carrier classifier.
- No fix for the §9.7 S10 throttle / restore-writer gaps (Batch C owns them; P2 matches Carrier's behaviour).
- No ecobee staleness remedy (§4.10 no-op; parked §3).
- No optimizer climate actuation out of shadow.
- No golden regeneration beyond the F4 row.

## 10. Tier + review protocol
- **Tier 3 (kept).** Why it stays Tier 3:
  - The R1–R16 routing touches the shared read path of every zone's S1 and arrester. The failure is ONE missed site:
    a raw read that sees None on ecobee reads "not manual" → S1 writes over a person's change (Bug Class #53 shape).
  - REV 3 adds a persisted adapter store and moves the Carrier freshness path; both must leave Carrier byte-identical.
  - It is comfort-impacting at a live second home.
- The §4.8 deletion is zero-consumer and adds no risk class. It rides in the same cycle because it changes the
  contract the adapter is built against.
- **Plan reviews (two, framing-disjoint): DONE** (appended below; resolution map §12). REV 3 changes are confined to
  the must-fix items; no re-review is required unless the orchestrator judges §4.2a / §4.10 substantial, in which
  case one focused completeness pass on those two sections.
- **Build:** `ura-super-builder`. Then four framing-disjoint reviews:
  - **A:** adapter local correctness (incl. `effective_range`, store keys, persistence shape).
  - **B:** HC integration parity (INV-P), restart (rehydrate order), Carrier byte-identity (incl. snapshot and
    freshness).
  - **C:** per-site source mutation of every R-site, T1/T2, the precondition, `held` ordering, the effective-range
    resolver, the rehydrate, F1–F4, the §4.8 lints, the §4.10 verbs, plus the golden replay.
  - **D:** breaks INV-P / INV-F / INV-E2 / INV-C / INV-R across the whole read surface, including pre-existing raw
    reads in `sensor.py` / `binary_sensor.py`. Config extremes: arrester OFF, TAO ON, D9 ON, nudge master OFF/ON,
    egress pause, an operator-edited baseline creating a duplicate range, season rollover with a stored composition,
    restart mid-nudge on ecobee, Auto heat/cool disabled, mixed Carrier + ecobee install.
- The orchestrator re-greps and runs one live mutation before ship.
- Operator checkpoint before deploy. No restart while House 1 sleeps.

## 11. Operator questions (REV 3)
**Moot under the ruling (REV 1 Q → disposition):**
- REV 1 Q1 (person-hold discharge): moot. The arrester and §9e own it.
- REV 1 Q2 (house-wide baselines): answered by the ruling. Uses Seasonal Baseline Presets.
- REV 1 Q4 (native presets vs ranges): answered (ranges are the default). Native comfort holds parked as a default-OFF
  brand option.
- REV 1 Q6 (hand-back): moot. Carrier does not hand back either.
- REV 1 Q7 (egress on ecobee): moot. On, per the URA default.
- REV 1 Q8 (person mode change): moot. B1 behaves as on Carrier.

**Remaining (unchanged from REV 2; REV 3 adds none):**
1. **Q1: ecobee's own hold expiry / program / Smart features read as a person change.** The arrester then reverts or
   compromises by delta, as with a person on Bryant. The mitigation is the setup notes (D5). OK? (Recommended: yes.)
2. **Q2: keep the `zone_thermostat_profile` override field?** (Recommended: keep. It is one Advanced field and the
   only way to stop a misdetected brand without a release.)
3. **Q3: native `ecobee` integration.** Defer until a real install exists? (Recommended: defer. I believe ecobee
   stopped issuing new developer API keys, but I have not verified that.)
4. **Q4 (decision point raised only by D0b):** if URA's echo cannot be told apart from a wall-unit change on HomeKit,
   the report comes back to you with options: accept, widen tolerance, or run House 2 with the arrester switch off.
   No feature is disabled by brand without your call.

REV 3's design choices (URA-side composed-range store persisted in the existing HVAC zone-state store; freshness as a
Carrier-only adapter verb; `ECOBEE_HEAT_COOL_STUCK_TICKS = 3`) follow directly from the ruling and the reviews and need
no operator decision. They are listed here so the operator can object at the checkpoint.

## 12. REV 3 resolution map (both plan reviews)
| Review item | Sev | Resolution |
|---|---|---|
| #1 CPR range never reaches an ecobee | HIGH | **RESOLVED** §4.2 `set_preset_range` row, §4.2a, §4.9, INV-P (REV 3 bullets), INV-R, D2 tests + drills |
| #1 F4 scope | MED | Resolved in REV 2 (§4.7) — kept |
| #1 per-platform cache / `strategy_for_platform` / reset | MED | Resolved in REV 2 (§4.1) — kept; reset also clears adapter state |
| #1 R2 direct classifier call | MED | Resolved in REV 2 (§5 R2) — kept; tolerance added |
| #1 `_check_carrier_freshness` on all zones | MED | **RESOLVED** §4.10, D6, INV-F (allowlist withdrawn), INV-E2 |
| #1 lint glob, INV-F lint extension, INV-G restatement | LOW | Resolved in REV 2 — kept |
| #1 pair-ring tolerance vs HomeKit rounding | LOW | **RESOLVED** §4.4 `echo_tolerance_f`, §5 T1/T2, D3 test, D0b P2 |
| #2 PR2-1 `held` ordering | HIGH | Resolved in REV 2 (§4.2) — kept; step 8 (persist) added |
| #2 PR2-2 no-op misses range changes | HIGH | **RESOLVED** with the effective range (§4.2, §4.2a), D2 test |
| #2 PR2-3 / PR2-4 / PR2-5 / PR2-6 / PR2-7 | HIGH/MED | Resolved in REV 2 — kept |
| #2 PR2-8 classifier tolerance | MED | **RESOLVED** §4.4, §5 T1/T2, D3 |
| #2 PR2-9 device min delta | MED | Resolved by PR2-1 step 3 — kept (§4.2 last paragraph) |
| #2 PR2-10 silent deferral; Auto heat/cool off | MED | **RESOLVED** §4.11, D2 tests, knob `ECOBEE_HEAT_COOL_STUCK_TICKS` |
| #2 PR2-11 `coordinator_diagnostics.py:534-535` | LOW | **RESOLVED** (confirmed covered by R16; D3 assertion) |
| #2 PR2-12 Carrier byte-identity note | LOW | Builder note — kept |
| #2 PR2-13 ecobee self-moving features | LOW | **RESOLVED** D5 setup notes, D0b P0 |
| #2 D0b safety additions + G1–G7 | — | Kept verbatim, binding (appendix below) |

---

## Plan review #2 (build-prediction) — 2026-10-03

> **RESOLVED in REV 3** — every finding is closed; see §12. PR2-1…PR2-7 were fixed in place in REV 2; PR2-2 is
> completed by §4.2a; PR2-8 → §4.4/§5 T1–T2/D3; PR2-9 → §4.2; PR2-10 → §4.11/D2; PR2-11 → §5 R16/D3; PR2-13 →
> D5/D0b P0. The D0b appendix below is unchanged and binding.

Reviewer read `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely and the thin-adapter memory note first. No §10 claim is
re-asserted. Framing: "what will the builder get wrong reading this?" Findings verified against `develop` source.
Fixed in place where small (marked PR2-n in the body).

| # | Sev | Finding | Evidence | Disposition |
|---|---|---|---|---|
| PR2-1 | HIGH | `held` ordering was "set before the wire" with no placement of the mode precondition, the funnel's guard transforms, or rollback. A builder stamps PRE-guard values; `emit_set_temperature` then rewrites them (`apply_setpoint_guards`: freeze floor raises low; `MIN_DEADBAND` 2.0 raises high, `hvac_setpoint.py:159-160`, `hvac_const.py:474`), the readback ≠ `held` → `manual` → S1 rewrites every tick and the arrester books URA's own write. A DEFERRED with `held` already stamped makes branch 3 read the preset forever | `hvac_setpoint.py:466-469` | **Fixed in §4.2** (7-step order, clamp before stamp, rollback) |
| PR2-2 | HIGH | No-op `last_sent == P AND preset_of == P` never fires a rewrite after a season rollover, a baseline edit, or a CPR edit while the house state is unchanged: `held` still matches the OLD range, so `preset_of` reads P. INV-P repro "S10 → next S1 hold carries the new range" is false as written. Carrier has no such gap (the device preset itself is edited) | `hvac_strategy.py:463-468`; `SEASONAL_DEFAULTS` summer home 77/70 → shoulder 74/70 | **Fixed in §4.2** (third clause: live legs equal current resolved range) — **REV 3: resolved range = effective range, §4.2a** |
| PR2-3 | HIGH | §4.2 text says the adapter owns the hazard "inside its range-writing verbs" but the table made `set_setpoints` a pure delegate. Callers pass `zone.target_temp_low` (None outside heat_cool on HomeKit) → a one-leg call = same `temperature=None` hazard | `hvac_override.py:5779`, `:6086`, `:7315`, `:7789` | **Fixed in §4.2 table** |
| PR2-4 | HIGH | The baseline fallback in `preset_of` applied whenever `held` mismatched, not only after restart. With DEFAULT summer ranges (home 77/70, sleep 76/70) a person's 77→76 reads `sleep`, not `manual` → no `override_detected`, no grace; S1 reclaims home at once. Carrier would book a person. INV-P broken on defaults | `hvac_const.py:1132-1151` | **Fixed in §4.3** (fallback only when `held` absent; near-duplicate = no match) |
| PR2-5 | HIGH | Option (i) "DEFER, zero funnel change" is offered as preferred, but its premise cannot hold for non-blocking mode writes: B4 mode `blocking=False` then S4 pin (`hvac_override.py:4745-4823`). D0b alone cannot validate (i) | code | **Fixed in §4.2** (two-part validity condition; builder states the S4 outcome with a test) |
| PR2-6 | HIGH | Inherited Generic `is_human_manual_snapshot` returns True when `preset_modes` is empty (always on HomeKit) → every ecobee borrow return restores raw setpoints (reads `manual`), not the named preset. Plan only mentioned `is_manual_hold` | `hvac_strategy.py:313-326` | **Fixed in §4.3** (override to Carrier's rule); add a test per return site kind |
| PR2-7 | MEDIUM | `strategy_for` caches by platform (`_STRATEGY_BY_PLATFORM`); the obvious edit caches the ecobee instance under `homekit_controller`. Registry-miss Generic must be upgraded on a later hit. The new per-entity cache will leak between parametrized golden cases without a reset fixture | `hvac_strategy.py:536-563`; `test_hvac_w1c_p1_byte_identity.py:986` | **Fixed in §4.1** |
| PR2-8 | MEDIUM | `ECOBEE_RANGE_TOLERANCE_F` feeds the projection only. The within-manual classifier and the pair ring use `LAST_SENT_TOLERANCE_F` (0.5 °F). If HomeKit readback rounds by more (e.g. 0.5 °C steps ≈ 0.9 °F), URA's own echo is classified HUMAN. The ecobee `classify_person_change` must pass `tol=ECOBEE_RANGE_TOLERANCE_F` (the param exists; the Carrier classifier is unchanged) | `hvac_strategy.py:497-517` | Builder: pass the profile tolerance; D3 test with a rounded echo — **REV 3: RESOLVED §4.4 / §5 T1–T2 / D3** |
| PR2-9 | MEDIUM | Device min heat/cool delta vs URA's baselines: winter home 72/70 and sleep 70/68 are 2 °F apart; shoulder home 4 °F. If the ecobee minimum delta is larger, the device moves a leg → readback ≠ write → `manual` loop (S1 every tick + false override). D0b measures it, but the plan gave the number no consumer | `hvac_const.py:1144-1151`, `:474` (comment "Ecobee auto mode minimum" = unverified prior claim) | Fixed by PR2-1 step 3 (adapter widens to the device min before stamping). Which leg moves is a URA-default choice — builder: keep heat, raise cool (matches `apply_setpoint_guards`) |
| PR2-10 | MEDIUM | A DEFERRED(`mode_not_heat_cool`) from S1 rolls back suppression and `continue`s silently (`hvac.py:3683-3691` — the comment assumes the chokepoint already logged a row). On ecobee nothing is logged, every tick. Also: Auto heat/cool disabled on the ecobee → `heat_cool` absent from `hvac_modes` → B1 never fixes the mode → URA silently does nothing forever | `hvac.py:3683-3691`; `_supports_heat_cool` `hvac_override.py:4618` | Builder: one INFO + one `preset_change_deferred` row per (zone, reason) per episode (reuse the F4 shape); `heat_cool` not in `hvac_modes` → `FAILED("no_heat_cool_mode")` via F4 + a Repair — **REV 3: RESOLVED §4.11 / D2** |
| PR2-11 | LOW | `coordinator_diagnostics.py:534-535` compares commanded vs actual `preset_mode` dicts; not in the §5 list. It consumes `actual` built from `:575` (R16), so routing R16 should cover it — reviewer #1 to confirm | grep | Confirm, no plan change — **REV 3: confirmed, §5 R16 + D3 assertion** |
| PR2-12 | LOW | Carrier byte-identity risk is low: every change is behind the ecobee class except F1/F2/F4, the cache refactor, and the R-site wrapper (Carrier/Generic `preset_of` must return `attrs.get("preset_mode", <site default>)` VERBATIM, including the `or ""` coercions at R5/R6/R7/R9 — keep each site's coercion outside `preset_of`). The 168 goldens hold no S1 two-tick Generic case, so F1 adds no golden delta | goldens key scan | Builder note |
| PR2-13 | LOW | Ecobee features that move setpoints by themselves (Smart Home/Away, Eco+, Follow Me, schedule) read as a person (Q1). Setup notes list only hold action + no program | — | Add to D5 setup notes and D0b P0 — **REV 3: RESOLVED D5 / D0b P0** |

**Brand-gating temptations to fence (INV-F):** the deferral in PR2-10 is a verb outcome, not a gate; do not add
`if hold_via == ...` in `hvac.py`; do not skip nudges when `zone.target_temp_low` is None (that is the adapter's
DEFERRED, not a caller check); do not stand down B1 on ecobee.

### D0b go/no-go criteria (operator-run, House 2 HVAC coordinator OFF)

**Probe safety additions (the procedure as written is NOT safe enough):**
1. Snapshot the starting state (mode, both legs or `temperature`, ecobee hold shown) and print it; the final step is a
   scripted restore of exactly that state, gated by `y`, and it also runs on "stop" / Ctrl-C.
2. The probe itself must never send a range while the entity is not in `heat_cool` (it would trip the same
   `temperature=None` hazard). Every P2/P3 write asserts the live state first, and always sends BOTH legs.
3. "Abort outside 66–80 °F" means: every commanded leg is clamped to [66, 80] AND the run aborts if indoor
   temperature leaves that band.
4. Confirm no other HA automation on House 2 writes the thermostat during the probe (list automations/scripts
   referencing the entity).

**Additional measurements:**
- P1: whether `set_hvac_mode heat_cool` with `blocking=True` returns with the state already `heat_cool`; the same with
  a non-blocking call followed by an immediate state read (feeds PR2-5).
- P2: how many `state_changed` events one range write produces, and whether any intermediate state shows only one leg
  changed (an intermediate state reads `manual` inside the 120 s window and is booked by the mid-window passthrough).
  Include a `.5` value (nudge size is 1.5 °F) and 70 °F (non-integer °C) to measure rounding.
- P3: write 72/70 (the winter-home default, 2 °F gap). Record whether and which leg the ecobee moves.
- P4: whether a wall-unit change of one leg also moves the other leg (shape for the classifier).
- P0: also record Smart Home/Away, Eco+, Follow Me states and whether Auto heat/cool is enabled.

**GO (build may start) only if ALL hold:**
- G1 the entity exposes `heat_cool` with `target_temp_low/high` and Auto is enabled;
- G2 one range write lands as legs equal to the written values within a measured tolerance T ≤ 1.0 °F, and T is
  smaller than half the smallest gap between two same-season baseline ranges (summer home vs sleep: 1 °F → T < 0.5
  needed, or PR2-4's near-duplicate rule applies);
- G3 echo p95 ≤ 120 s (else C1 becomes mandatory, not conditional);
- G4 the device minimum delta is measured (any value; PR2-1 consumes it);
- G5 separability: no wall-unit change in P4 lands within T of the URA write on the changed leg within the echo
  window, or the operator accepts Q4;
- G6 a HomeKit write creates a hold that persists with the configured hold action (if it expires on its own, Q1
  must be answered before build);
- G7 the starting state was restored and confirmed.

**NO-GO:** any write produced `temperature=None` or a single-leg state, the restore failed, or G1/G2 fail → report to
the operator; do not build.

### Verdict

**FIX-PLAN → BUILD-READY once the orchestrator accepts the PR2-1…PR2-7 in-place fixes** (already written into §4.1–§4.3)
**and folds PR2-8/9/10/13 into D2/D3/D5.** No finding requires a new user-facing switch, a brand gate, or a Carrier
change. Build stays blocked on D0b GO.

---

## Plan review #1 (completeness) — 2026-10-03

> **RESOLVED in REV 3** — HIGH (CPR range on ecobee) → §4.2 `set_preset_range`, §4.2a, §4.9, INV-P, INV-R, D2.
> MEDIUM (`_check_carrier_freshness`) → §4.10, D6 (adapter verb pair; the suggested lint allowlist is no longer
> needed). LOW (pair-ring tolerance) → §4.4, §5 T1–T2, D3. All other items were fixed in place in REV 2. See §12.

**Reviewer:** ura-reviewer, Tier 3 plan review #1 (completeness). I read `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full and
the thin-adapter memory note first. Code anchors are on `develop` @`e15c4d49e`; `git diff 8a4619b32 HEAD --
custom_components quality` is empty, so the plan's line numbers hold. I re-ran every grep myself.

### Re-enumeration results
- **Raw thermostat `preset_mode` reads.** I grepped `attributes.get("preset_mode"` / `getattr(..).get("preset_mode")`
  / `.get("preset_mode")` / `ATTR_PRESET*` across `custom_components/**`. The hits are exactly R1–R16 plus
  `hvac_setpoint.py:199` (ledger, excluded on purpose) and `hvac_strategy.py:291` (`observe`, which §4.3 covers).
  - `hvac_fans.py` reads fan entities only (confirmed).
  - `hvac.py`, `hvac_predict.py`, `hvac_preset.py`, `sensor.py` and `binary_sensor.py` read only `zone.preset_mode`.
    R1 (`hvac_zones.py:612`) is its one producer; `grep '\.preset_mode = '` finds that one site.
  - **The §5 list is COMPLETE.** Two role labels were wrong and are fixed above: R3 is the latch discharge
    predicate, and R9 is telemetry.
- **`hold_activity` / `preset_modes`.** These are read only in the resume-then-pin funnel (`hvac_setpoint.py:418-421`),
  which ecobee never reaches, and in `observe`. No change is needed.
- **`next_activity_time`.** It is read at `hvac_override.py:4094` behind `isinstance(nxt_raw, str) and nxt_raw` inside
  a try block, so a missing value means no sunset. The §4.5 step-0 check holds.
- **`hvac_modes`.** It is read only by `_supports_heat_cool` (`hvac_override.py:4628`; callers `:4741`, `:5158`,
  `:5272`, `hvac.py:2605`). This is a live read, consistent with INV-F.
- **`target_temp_*`.** There are 33 reads across 7 files. All of them assume heat_cool legs, the same as on Carrier.
  The one-leg / None-leg hazard is now covered by review #2's `set_setpoints` precondition (§4.2 PR2-3).
- **Write sites.** Every `climate` write goes through `_w1c_strategy(...)` or `strategy_for(...)`
  (`hvac.py:2611`, `:3658`, `:4153`; `hvac_override.py` ×17; `hvac_predict.py` ×7; `hvac_egress.py` ×3;
  `hvac_excursion.py` ×2). §5's "Writes: NONE" holds.
- **`is_human_manual_snapshot` callers.** There are 9, and none passes `preset_modes=`. So Generic's "no presets →
  human" branch never fires in production, and ecobee's named/human verdict depends only on the PROJECTED snapshot
  (R8 / R10 / R13 / R14 / R15). This is consistent with the plan.
- **Scaffold.** `feature_available` / `feature_unavailable_reason` / `.capabilities` / `*_CAPABILITIES` /
  `ProfileCapabilities` and all 11 deleted field names appear only in `hvac_strategy.py` and
  `test_hvac_w1c_p1_profile_contract.py`.
  - The planning-doc hits are in the Batch C plan (5) and the parent plan (13).
  - **§1b and §4.8 are COMPLETE.**

### Findings
| Sev | Where | Finding | Disposition |
|---|---|---|---|
| **HIGH** | §4.2 `set_preset_range` row, §4.9, INV-P last bullet | **The CPR range never reaches an ecobee (Bug Class #53).** The plan says "the hold translation always reads the CURRENT Seasonal Baseline / CPR range". The resolver it names, `get_seasonal_setpoints` (`hvac_preset.py:126-160`), returns the CM-options baseline only. It never sees the S10-composed CPR range, and on ecobee `set_preset_range` drops that range (SKIPPED). There is a second, independent defect: even if a CPR range were stored, S1's no-op (`last_sent == P` AND `preset_of == P`) stays SKIPPED while the house remains in P, so the new range would not land until the preset changes. Repro: D9 ON at House 2, house in `home`, DPM composes 69/78 → S10 SKIPPED → the zone holds the baseline 70/77 indefinitely. That is CPR silently off on ecobee, which contradicts the ruling. The same no-op hole lets an operator's baseline edit wait until the next preset change. | **FIX-PLAN.** The author decides the shape. Suggested shape: `EcobeeHomeKitStrategy.set_preset_range` stores `ranges[(entity, P)]`; if `held` is P with a different range, it writes now (APPLIED, through the range path); otherwise it returns SKIPPED `no_device_presets`. hold/pin resolve `ranges` first, then the baseline. The no-op also requires `held`'s range == the resolved range. `preset_of`'s restart fallback must then also match stored CPR ranges, or document that it reads `manual` until the first S10 after a restart. Add a D2 test and fix the INV-P bullet. — **REV 3: RESOLVED (§4.2a; suggested shape adopted, keyed by season, persisted so restart reads the held preset)** |
| MEDIUM | §4.7 F4 | F4 as written turned every S1 `FAILED` into INFO + continue, including Carrier `emit_raised` (`hvac_strategy.py:484-486` → `hvac.py:3678-3682` RuntimeError). That breaks INV-C outside its one named exception. | **Fixed in plan:** scoped to capability reasons, plus a Carrier raise test. |
| MEDIUM | §4.1 | The per-PLATFORM cache (`hvac_strategy.py:556-562`) would bind every `homekit_controller` entity to whichever was resolved first (ecobee vs non-ecobee). `strategy_for_platform` (`:566`, 0 callers) cannot see the manufacturer. `_test_reset_cache` does not know about the new per-entity cache (7 test files use the seams). | **Fixed in plan** (§4.1 bullets). |
| MEDIUM | §5 R2 | `classify_manual_setpoint_change` is called directly at `hvac_override.py:3636`, with no hass or entity. `strategy.classify_person_change` has no production caller, so §4.4's "same delegate fed projected states" does not reach the live path. | **Fixed in plan:** the R2 row now names the threading requirement. |
| MEDIUM | HC, not in the plan | **A brand-hardwired path runs on every zone.** `_check_carrier_freshness` (`hvac.py:7381`) scans ALL zones. Its remediation reloads `ha_carrier` entries (`:7689`), and when it finds none it sends a "Carrier reload skipped - ambiguous entry" NM (`:7694-7702`). Repro: at House 2, the ecobee's `last_reported` age exceeds `hvac_carrier_stale_max_age_s` (900 s) → 0 `ha_carrier` entries → a spurious NM. This is not a feature gate. It is a Carrier repair command sitting in HC instead of the adapter, so it falls under INV-F's spirit and the memo's "no hard-wired Carrier quirks in shared paths". | **FIX-PLAN (small):** add a disposition to §4.6 / §5. Preferred: the staleness detector stays brand-neutral, and the reload becomes an adapter verb (Carrier = reload, others = no-op with no NM). Minimum: filter the reload/NM to Carrier-profile zones and add a test. Also allowlist it in the INV-F lint. — **REV 3: RESOLVED (§4.10; per-zone staleness test AND reload are adapter verbs, so the age-only NM is also Carrier-only; no allowlist needed)** |
| LOW | §5 lint | The new raw-`preset_mode` lint must glob `coordinator_diagnostics.py` (R16). P1's literal lint scans `hvac*.py` only. | **Fixed in plan.** |
| LOW | §6 INV-F | The lint caught only `.capabilities` and `feature_available`. A brand gate written as `strategy.platform ==`, `isinstance(…Strategy)` or `CARRIER_PLATFORM` would pass it. | **Fixed in plan** (lint extension). |
| LOW | §6 INV-G | "zero writes of its own initiative" was not falsifiable, and it conflicts with Generic running B1, nudges and borrows under the ruling. | **Fixed in plan** (restated). |
| LOW | §4.3 / D0b | The pair-ring tolerance `LAST_SENT_TOLERANCE_F` (±0.5 °F) feeds `_transition_is_human` (`hvac_override.py:4240-4275`) and R2. HomeKit °C readback rounding can exceed it. A nudge echo would then book as a HUMAN interrupt (it ends BANKING/PREHEAT borrows). Note that `is_override` is booked on ANY transition into manual (`:3627-3628`); only interrupt eligibility uses the tolerance. | D0b P2 must also report rounding against ±0.5 °F. If it is exceeded, the classifier tolerance becomes a per-profile fact (a capability field the adapter consumes) and is not left implicit. Hand this to plan review #2. — **REV 3: RESOLVED (§4.4 `echo_tolerance_f()` method rather than an 11th capability field, so the §4.8 trim and the `.capabilities` lint stay intact)** |

### Invariant falsifiability
- **INV-C:** PASS. It is falsifiable through the goldens plus a ledger diff. It now carries F4's narrowed exception.
- **INV-P:** PASS (harness-defined). The last repro bullet is false as designed (HIGH above). — **REV 3: bullet replaced.**
- **INV-F:** PASS after the lint extension.
- **INV-E2:** PASS. With review #2's PR2-3, `set_setpoints` is now covered.
- **INV-G:** PASS after the restatement.

### Batch C interface (§4.9)
The status-branching shape is sound, and `_w1c_applied` is correctly forbidden. Generic `FAILED` is counted only for
`emit_raised` under Batch C §6.2, so a non-Carrier zone never latches `call_failed`. The open gap is the HIGH above: a
SKIPPED that stores nothing means CPR is dropped on ecobee. — **REV 3: closed (§4.9 ecobee bullet).**

### Verdict: **FIX-PLAN**
Must-fix before build dispatch:
1. **HIGH:** define how an ecobee consumes the CPR range and how the S1 no-op notices a range change (the §4.2
   `set_preset_range` row, §4.9 and INV-P). — **RESOLVED REV 3.**
2. **MEDIUM:** a disposition for `_check_carrier_freshness` on non-Carrier zones. — **RESOLVED REV 3.**

Everything else is fixed in place above. After those two edits the plan is BUILD-READY from a completeness standpoint.

## Plan re-review REV 3 — 2026-10-03 (focused: §4.2a, §4.10, §4.11)

Read first: `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely (§10 ledger not re-asserted) and memory
`feedback_thermostat_brand_layer_is_thin_command_adapter.md`. Re-grepped on develop @`f9379a1c5`. Operator Q1-Q3 =
recommendations.

| # | Sev | Finding | Evidence | Disposition |
|---|---|---|---|---|
| RR3-1 | MEDIUM | §4.2a prune anchor wrong: the zone-removal rewrite skips all `__` keys, so `__w1c_adapter` would never be pruned (a thermostat swap leaves the old entity's `held`/`ranges` forever) | `hvac.py:5510`; latch prune seam `:5474`, `:6143`, `hvac_override.py:1354` | FIXED IN PLACE (§4.2a: prune at the latch seam) |
| RR3-2 | MEDIUM | Rehydrate "on every strategy instance" finds none at boot (`:1277` precedes any `strategy_for`); a Generic resolution (registry miss / D0b `None`) would ignore the slice and the next save (key written only when non-empty) would ERASE it; the miss→hit flush would also wipe it | `hvac.py:1277`, `:2372-2378`; §4.1 profile-switch flush | FIXED IN PLACE (per-entity rehydrate + HC pending passthrough; flush excludes pending) |
| RR3-3 | MEDIUM | Store leak across CPR OFF: S10 does not run the apply pass while switch 01 is OFF, so delete-on-baseline never fires; Batch C's restore-originals (§3.4) has no ecobee meaning → S1 carries the composition forever (INV-P break vs Carrier's restored originals) | Batch C plan §3.4 (`PLANNING_hvac_enable_custom_preset_ranges.md:661-690`); §4.2a here | FIXED IN PLACE (§4.9: ecobee original = baseline via adapter read → delete) |
| RR3-4 | LOW | Season-keyed entries survive a year; the next same season a stale composition is used by S1 before S10 re-composes | §4.2a store key | FIXED IN PLACE (drop non-current-season entries at rehydrate + rollover) |
| RR3-5 | LOW | §4.11 "reason the chokepoint did not already ledger" was implicit | only Carrier/Generic DEFERRED is `gate_deferred` (`hvac_strategy.py:362`, `:488`), ledgered by `_log_deferred_write` (`hvac_setpoint.py:455-466`, `:565-576`) | FIXED IN PLACE (exclude `gate_deferred`) |

**Restart ordering claim — HOLDS.** `_rehydrate_arrester_state` at `hvac.py:1277` → arrester listener `setup()`
`:1472` → first `_async_decision_cycle` `:1572` → startup audit `:2219` (guarded by `_startup_audit_done`). No
`preset_of` consumer runs before the rehydrate.

**set_preset_range / S1 already-correct — HOLDS.** Store first, then held≠P → zero calls; held=P and live = effective →
zero calls; else the binding ordering. INV-R's third S1 clause makes a stored change, baseline edit or season rollover
land on the next heat_cool tick. `held` is not season-keyed, but clause 3 compares against `effective_range(season_now)`,
so a rollover rewrites (no leak).

**§4.10 — HOLDS.** Sites re-verified: loop `hvac.py:7420`, in-flight fence `:7550-7551`, age-only NM `:7596`, ambiguous
NM `:7702-7707`, `_reload_ha_carrier_entry` `:7605`. A verbatim move plus `not_applicable` rows keeps an all-Carrier
install byte-identical; no allowlist needed.

**§4.11 Carrier byte-identity — HOLDS, no new exception.** Every Carrier DEFERRED is `gate_deferred` and already
ledgered, so with RR3-5 the episode row never fires on Carrier; the in-memory episode map is unobservable. INV-C
exceptions stay at exactly one (F4 S1 FAILED row, capability reasons only; Carrier `emit_raised` keeps the
`RuntimeError` at `hvac.py:3678-3682`). The 168 goldens should replay unchanged; `__w1c_adapter` is absent on Carrier
(export `{}` → key omitted).

**Verdict: BUILD-READY (pending D0b).** All five findings fixed in this commit; no code edited.

## Operator field evidence 2026-10-05 (Wigton, screenshots)
- A SECOND ecobee exists: **"Ecobee Upstairs"** (ECB501, fw 4.10.330032, HomeKit Device, area Game room) — plan previously assumed one (`climate.master_closet_ecobee_downstairs`). Zone mapping must cover both.
- HomeKit exposes: climate entity (showed "Idle (Cool) 76 °F", 57% RH), a **"Clear Hold" button**, and a **"Current Mode" select with options Home / Sleep / Away** (ecobee comfort settings) — reading **unknown** at capture time (likely while a manual hold is active; to verify in D0b).
- Thermostat on-device system modes: Heat, Cool, Heat/Cool (Auto), Off.
- Implication for the thin adapter: preset/comfort commands map to the Current Mode select (Home/Sleep/Away), hold release maps to the Clear Hold button; an `unknown` select must be treated as "no comfort setting readable", not as Away. D0b probe should capture select state before/after Clear Hold.
- **Operator 2026-10-05:** Wigton has **3 AC systems, like the main house → likely 3 HVAC zones**, each with its own ecobee; the other 2 ecobees were added to HA (HomeKit) today. Plan must cover 3 thermostats/zones (was 1). D0b probe re-scope: all 3.

## D0b results 2026-10-05 (read-only leg; `--discover`, 24 h recorder)

Scope: the read-only part of D0b/D0a only. P1-P7 (writes) are NOT run; G1-G7 stay open. Raw JSON kept off-repo.

| | Upstairs | Master suite | Downstairs |
|---|---|---|---|
| climate entity | `climate.game_room_ecobee_upstairs` | `climate.study_hallway_ecobee_master_suite` | `climate.master_closet_ecobee_downstairs` |
| area | Game room | Study Hallway | Down Guest bedroom hallway |
| device | ecobee Inc. ECB501, fw 4.10.330032 | ECB501, fw 4.10.330032 | ECB501, fw **4.10.70046** |
| hvac_modes | off/heat/cool/heat_cool | same | same |
| supported_features | 399 (TARGET_TEMP, RANGE, TARGET_HUMIDITY, FAN_MODE, TURN_OFF, TURN_ON; **no PRESET_MODE**) | 399 | 399 |
| preset_modes | absent | absent | absent |
| min/max temp | 45 / 92 °F | same | same |
| live mode / setpoint | cool, temperature 76, low/high **null** | same | same |
| fan_modes | on, auto (auto) | same | same |
| humidity | current 55 %; target `humidity` attr, range 20-50 | 54 % | 55 % |
| hvac_action seen 24 h | idle 208 / cooling 120 / fan 49 (n=377) | idle 142 / cooling 26 / fan 4 (n=172) | idle 364 / cooling 47 / fan 9 (n=420) |
| setpoint history 24 h | constant 76, always single-target | same | same |
| Current Mode select | options home/sleep/away; **unknown in 7/7 rows, 100 % of 24 h** | unknown 7/7 | unknown 5/5 |
| Clear Hold button | present | present | present |
| other siblings | identify button, motion + occupancy binary_sensors, temp + humidity sensors, display-units select | same | same |

Answers to D0b questions answerable read-only:
- **G1 (partial):** all three expose `heat_cool` and RANGE support, but none has been in heat_cool in 24 h, so legs
  appearing in heat_cool is UNMEASURED (P1 needed). Auto-enabled on the unit: operator P0.
- **Echo latency, rounding, min delta, separability, hold persistence (G2-G6):** unmeasured; need the supervised run
  on each entity.
- **Current Mode `unknown`:** constant across the whole window on all three, and its row timestamps coincide with the
  HomeKit entry reloads/restarts (00:05, 02:11, 05:00, 05:04 UTC), not with any setpoint event. Cannot yet tell
  "unknown under hold" from "HomeKit never reports it"; P-step to add: press Clear Hold (operator, supervised) and
  read the select before/after.
- Setpoint 76 °F constant with frequent cooling cycles = consistent with a held setpoint (hold action already
  "until I change it" or similar); confirm at P0.

Brand QUIRKS the thin adapter must absorb (never gate features by brand):
1. **No `preset_mode`.** The comfort setting is a sibling `select.<x>_current_mode` (home/sleep/away), resolved via
   the device registry, not the climate entity. `preset_of()` must read the select; adapter verb = `select_option`.
2. **Current Mode reads `unknown`** (24 h, all units). Treat as "no comfort setting readable", never as Away; the
   projection must fall back to the setpoint/range readback.
3. **Hold release is a button** (`button.<x>_clear_hold`), not a service on the climate entity — the adapter's
   "resume/release" verb maps to `button.press`.
4. **Dual setpoints only in heat_cool.** In cool/heat, `target_temp_low/high` are present but `null` and
   `temperature` is set; the adapter must not send a range outside heat_cool (D0b safety #2 stands).
5. **Target humidity ceiling 50 %** (min 20) while room RH sits 54-55 %; any humidity verb must clamp.
6. **Mixed firmware** (4.10.330032 ×2, 4.10.70046 ×1): measure P1/P2 on the Downstairs unit separately; don't
   assume one unit's echo profile covers all.
7. **Three thermostats → three zones**: detection/cache is per-entity (§4.1 already is); zone mapping must name all
   three.
8. Device-registry siblings also offer `occupancy`/`motion` binary_sensors (ecobee remote/occupancy): presence
   inputs, not adapter concerns — note for the zone config, no brand gate.

## D0b supervised results 2026-10-05 (P1-P3 write leg; operator-approved "Yes. Just restore.")

Scope and method: run via REST against Wigton HA (`192.168.17.243:80`) using
`scripts/probes/house2_ecobee_d0b_probe.py --entity <x>`, remote (no human physically at the thermostat/app this
run). P0 physical-only reads (hold action text, Auto-enabled, Smart Home/Away, Eco+, Follow Me, program running)
answered `?`/unknown — **not fabricated**; G1 stays UNKNOWN for that reason, not a failure. P4 (wall-unit change),
P5 (mode change at the wall), P6 ("Resume schedule" in the app) all declined — they require physical presence not
available this run; declining P4 triggers the script's own abort-and-restore path, so P1-P3 data is preserved and
the restore still runs. Raw JSON per unit in scratchpad only (not committed): `house2_d0b_supervised_{upstairs,
master_suite,downstairs}.json`, plus `house2_clearhold_results.json` for the separate Clear-Hold test below.

**Pre-step, all three units:** before the P1-P3 run, pressed `button.<x>_clear_hold` on all three (to test the
`unknown` Current-Mode question) with before/after reads of `select.<x>_current_mode` + the climate entity 30 s
apart. This is an extra write beyond the runbook's scripted P-steps and shifted all three setpoints off 76 °F
(see Clear-Hold finding below) — corrected back to `cool`/76 °F on all three via `climate.set_temperature` before
the P1-P3 run started, verified by readback. The P1-P3 run's own "starting state" snapshot was therefore taken
at the corrected 76 °F baseline, not the drifted one.

| | Upstairs | Master suite | Downstairs (older fw 4.10.70046) |
|---|---|---|---|
| G1 heat_cool + legs | **UNKNOWN** (Auto-enabled not recorded; heat_cool confirmed exposed, legs appeared immediately: `legs_at_return=[76,76]` on mode switch) | UNKNOWN (legs `[74,74]` at return — picked up the then-current single setpoint as both legs) | UNKNOWN (legs `[73,73]` at return) |
| G2 tolerance T | **GO** — T=0.50 °F (`.5` writes rounded to the nearest whole degree; `70.5/75.5`→`71/76`, `69.5/74.5`→`69/74` — rounds AWAY from the mean, not consistently up or down) | GO — T=0.50 °F, same rounding behavior | GO — T=0.50 °F, same rounding behavior |
| G3 echo p95 | **GO** — p95 0.044 s (sub-second; HA's blocking REST call returns after the echo, confirming measurement note in the script's docstring) | GO — p95 0.035 s | GO — p95 0.039 s |
| G4 device min delta | **≤ 2.0 °F** — both P3 writes (72/74, 70/72) landed exactly, device accepted the 2 °F gap with no leg correction | **5.0 °F** — P3's 70/72 write was NOT accepted as-is: device walked it through `70/74`→`69/74` over ~1 s (a real single-leg intermediate, not just a final correction) | **≤ 2.0 °F** — same as Upstairs, both gaps accepted |
| G5 separability | UNKNOWN — P4 not run (no wall-unit access) | UNKNOWN — P4 not run | UNKNOWN — P4 not run |
| G6 hold persistence | UNKNOWN — `hold_shown`/`hold_persists_operator` both `?` (no physical/app read) | UNKNOWN — same | UNKNOWN — same |
| G7 restore | **GO** — readback confirms `cool`/76 °F/fan `auto` after restore | **GO** — same | **GO** — same |
| OVERALL | NO-GO (G1/G5/G6 UNKNOWN — not a correctness failure, a coverage gap: physical P0/P4/P5/P6 need an operator at the unit) | **NO-GO (hard)** — `single_leg_intermediates` non-empty on the min-delta walk down to 70/72, which is an explicit hard NO-GO per the script's `evaluate_g()` | NO-GO (same UNKNOWN coverage gap as Upstairs) |

**Clear-Hold / `unknown` Current-Mode finding — answered.** Pressing `button.<x>_clear_hold` and re-reading the
`select.<x>_current_mode` 30 s later:
- Downstairs: `unknown` → `home` within the 30 s window.
- Master suite: still `unknown` at 30 s, but `home` by the time of the later post-snapshot read (a HomeKit
  polling-lag effect, consistent with the D0b read-only leg's observation that Current-Mode rows coincide with
  HomeKit reload timestamps, not setpoint events).
- Upstairs: still `unknown` at both the 30 s read and the later post-snapshot read.
- **Conclusion:** Clear Hold DOES surface a real Current-Mode value on at least 2/3 units — `unknown` is NOT purely
  "HomeKit never reports it"; it is at least partly "unknown while a hold is active, resolves on release," with a
  HomeKit polling lag of tens of seconds to longer. Upstairs not resolving within this run's observation window is
  inconclusive (could need longer, or could be a per-unit HomeKit quirk) — leave as an open question, not a
  contradiction.
- **Side effect (expected given the above):** releasing the hold let each unit's schedule assert a different
  setpoint immediately (76→77 Upstairs, 76→75 Master suite and Downstairs) — i.e., these units DO have a program/
  schedule that engages the moment a hold clears, contradicting the runbook's P0 setup assumption ("No ecobee
  program/schedule running"). This was corrected back to 76 °F before the P1-P3 run (see pre-step note above) and
  is itself a finding: **a bare Clear-Hold press is not safe to leave unattended** — it must always be paired with
  an immediate re-assertion of the desired setpoint, which the main script's P6 ("Resume schedule") step already
  anticipates but the ad-hoc Clear-Hold side-test did not script until this run surfaced the need.

**heat_cool / target_temp_low/high behaviour.** On all three, switching from `cool` (single `temperature`) to
`heat_cool` immediately populated both legs equal to the prior single setpoint (`[76,76]`, `[74,74]`, `[73,73]`)
with sub-second latency and no intermediate single-leg state — this part of G1 is solid evidence in favor of GO;
only the "Auto heat/cool enabled" operator confirmation is the open UNKNOWN. `hvac_action` was observed transitioning
`idle`↔`cooling` normally across writes, consistent with real cooling calls, not a stuck/no-op state.

**Updated quirks list (adds to the 8 above):**
9. **Half-degree (`.5`) range writes get rounded to the nearest whole degree by the device**, not truncated — and
   the rounding direction is away from the mean (`70.5/75.5`→`71/76`, i.e. both legs round outward), not a fixed
   round-up or round-down. The thin adapter must not assume `.5` survives a readback; any invariant comparing a
   written value to a readback needs the ≥0.5 °F tolerance the plan's PR2-4 near-duplicate rule already carries.
10. **Device minimum heat/cool delta is NOT uniform across the fleet.** Upstairs and Downstairs (despite different
    firmware) both accepted a 2 °F gap cleanly; Master suite enforced a real minimum by walking the setpoint through
    an intermediate single-leg state down to a final ~5 °F gap. **Per-unit min-delta must be measured/configured
    individually, not assumed from firmware version or from one unit's result** — this directly falsifies the plan's
    working assumption that one unit's profile could stand in for the fleet (quirk #6 was about echo latency; this
    is the same caution extended to min-delta).
11. **A single-leg intermediate during a narrowing range write is real and observable**, not just a theoretical
    hazard — Master suite produced one converging on 70/72. Any code that reads `target_temp_low`/`target_temp_high`
    mid-transition must tolerate a transient state where only one leg has moved; this is the exact hazard class
    D0b's G2/hard-NO-GO check exists to catch, and it fired correctly.
12. **Clear Hold engages the unit's schedule immediately**, even when the runbook's P0 setup asked for "no program
    running" — at least on this house's three units, a schedule was live underneath the hold. Any future "resume
    schedule" / "clear hold" adapter verb must immediately re-read and, if needed, re-assert the desired setpoint
    in the same call sequence — never leave a bare Clear-Hold press unattended.

**What remains before D0b can go OVERALL GO:** G1 (Auto heat/cool enabled, read at the unit), G5 (P4 wall-unit
separability test), G6 (hold-persistence / hold-action text, read at the unit or app), and — separately — Master
suite's hard NO-GO (single-leg intermediate) needs either an accepted per-unit min-delta design (adapter clamps
writes to each unit's measured minimum before sending) or a re-run proving the intermediate was a one-off. All four
require either an operator physically at a Wigton thermostat/app, or a design change that avoids needing G5/G6
read from a human. Build of P2 (D1-D6) stays blocked per the runbook until this resolves.

## Operator on-site check 2026-10-05 16:07 (Wigton, photos)
- **Heat/Cool Min Delta = 5°F on Upstairs AND Master suite** (Installation Settings → Thresholds). **Auto Heat/Cool = Enabled** on both. Downstairs not checked; assume the same (ecobee default). Operator's skepticism confirmed: the gap is a per-unit installer setting at the same value, not a per-unit hardware difference. The supervised probe's "upstairs/downstairs accept 2°F" reading is therefore suspect (device likely widened silently or the write landed outside auto) — do NOT design per-unit learning. **Ruling:** adapter enforces a configured min delta, default 5°F, operator-overridable per thermostat; any range write narrower than that is widened by the adapter before sending (never sent as-is).
- Hold UX: a URA/HA write shows **"70 - 77 | Holding ⊗"** (auto mode, both setpoints). Cancelling the hold (⊗) returns to the schedule: Cool, single setpoint **75** (Current Mode then reads the schedule's comfort setting, consistent with the Clear-Hold probe result).
- Wall setpoint change: scroll wheel on the unit creates a hold the same way (operator photo).
