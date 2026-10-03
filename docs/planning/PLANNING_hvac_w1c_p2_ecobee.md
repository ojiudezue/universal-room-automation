# HVAC W1-C P2 — ecobee as a thin command adapter (HomeKit first), plus P1 carry-over fixes — REV 2

**Status:** PLAN, not built. Plan reviews are pending (Tier 3 = two framing-disjoint plan reviews before build).
**REV 2 (2026-10-03) replaces REV 1's design.** Operator architecture ruling, verbatim:

> "Ecobee should work like Bryant does in my home. All we need to know is how to command it. That manufacturer
> abstraction is about how to command it efficiently given its features that Bryant may or may not have. URA HC does
> the rest and works the same. Keep the surface small and contained. It's a small Model.Brand specific
> wrapper/abstraction; URA should feel the same no matter where deployed. All those features should have a default
> on/off per URA and can be turned on or off at will. Even our preference for ranges can be preserved and it's an
> opinionated take. It allows Therms to work as they are designed and URA to do the minimum to command and futz with
> absolute temp all the time."

**What changed from REV 1:**
- Every brand-based "stands down / off on ecobee" gate is REMOVED: arrester revert/compromise, borrows, nudges, AC
  resets, egress pause, DPM/CPR, and the heat_cool enforcer gating. Each feature keeps its URA default and its existing
  switch on every brand.
- The REV 1 person-hold machinery is REMOVED: gate (f), `person_hold` state, `__person_holds`, the discharge rules and
  the `person_hold_limit` knob. The arrester and §9e already own "a person changed the thermostat". They work on ecobee
  once the adapter gives them the same view that Carrier gives them.
- The adapter (strategy) is now the ONLY brand-specific surface. It has four parts: command verbs, a state read,
  capability facts, and the ours-vs-person classifier (§4).
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
- "Hold preset P" becomes a heat_cool range write of the house's Seasonal Baseline range for P. This is URA's
  opinionated default, because ecobee over HomeKit has no presets.
- Setpoint and mode writes pass through.
- The adapter reports the thermostat's state in Carrier's vocabulary. A range that matches URA's held preset reads as
  that preset; any other range reads as `manual`. HC readers therefore see the same signals they see on Carrier.

Carrier zones stay byte-identical to v5.103.36. P2 also deletes P1's unused feature-gating scaffold and folds in four
P1 review findings (§4.7).

---

## 1. Institutional context verified

### 1a. Read in full before planning (REV 2)
- `CLAUDE.md` (project).
- The full `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:
  - §0–§12, including §4.2 write sites, §5 Carrier facts and §7 arrester;
  - §9e four-gate rule and the "person interrupts" ruling;
  - §10 C1–C29;
  - the 2026-10-03 live-state note (D9 switch ON at House 1).
- `docs/planning/PLANNING_hvac_w1c_thermostat_profiles.md`: REV 3.2 banner, REV 3.1 errata, REV 3 body.
- `docs/planning/AUDIT_house2_ecobee_inspection_2026_09_30.md`.
- `docs/readmes/README_v5.103.36.md`.
- This plan's REV 1 (superseded, kept in git history).
- `docs/planning/PLANNING_hvac_enable_custom_preset_ranges.md`: REV 3.3 U1 (:29, :1196), `set_preset_range` design
  (:23-36, :637-657, :751), and the operator-ruling note :1215-1216 (thin adapter).

### 1b. Code read for this plan (file:line on `develop` @ `8a4619b32`)
| File | What was read |
|---|---|
| `hvac_strategy.py` :84-591 | `ProfileCapabilities` :119-148 (21 fields); `CARRIER_CAPABILITIES` :157-182; `GENERIC_CAPABILITIES` :188-210; `GenericStrategy`: `observe` :277-297 builds `HoldObservation` from the RAW `preset_mode`; `last_sent` / `_record_sent` :300-310; `is_human_manual_snapshot` :313-326; `is_manual_hold` :329-337; **`feature_available` / `feature_unavailable_reason` :340-352**; the pure delegates :364-413; `release_hold` :415-434; stub `classify_person_change` :437-441; `hold_preset` :444-490. `CarrierStrategy` :493-532; `strategy_for` :551-563 (registry miss → fresh uncached Generic); `is_manual_hold_for` :581-586 |
| `quality/tests/test_hvac_w1c_p1_profile_contract.py` :163-210 | `test_profile_capabilities_field_set_frozen` :163-173; `test_strategy_capabilities_bound_per_profile` :176-182; `test_carrier_capabilities_mirror_constants` :185-195; `test_feature_available_table` :198-210 |
| `hvac.py` | `_w1c_*` helpers :118-131; B1 enforcer :2563-2630 (ungated by any switch; writes through `strategy.set_hvac_mode`); S1 manual readers :3398-3431, :3596, :3722, :3815; `_zone_last_write_is_away` :4795-4809 |
| `hvac_zones.py` | `ZoneState.preset_mode` :97; `update_zone_climate_state` :612 (RAW read) |
| `hvac_override.py` | raw thermostat `preset_mode` reads at :212, :1340, :2595, :3014-3015, :3498-3499, :3599-3600, :5148, :5511, :5713, :6179, :6266, :7156, :7397; `_supports_heat_cool` :4618-4629 (LIVE `hvac_modes` read) |
| `hvac_egress.py` :668, `hvac_excursion.py` :886, `coordinator_diagnostics.py` :575, :600 | raw thermostat `preset_mode` reads |
| `hvac_fans.py` :2034, :2314 | `preset_mode` reads on **fan** entities. Out of scope (the builder confirms the entity domain) |
| `hvac_setpoint.py` :199 | `values_before` ledger snapshot. Stays RAW on purpose |
| `hvac_const.py` :1132-1151 | `SEASONAL_DEFAULTS`: no two presets share a range within one season |

**Consumer grep for the scaffold (re-run by plan review):**
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

### 1d. Memory pulled
- `feedback_extend_existing_never_rebuild` (the REV 2 thesis: HC is the spec; the adapter only translates).
- `feedback_marginal_benefit_pushback`, `feedback_measure_before_build`, `feedback_tier2plus_prior_art_scan`,
  `feedback_wire_in_anchor_mandatory`, `feedback_hollow_test_anchors`,
  `feedback_coincidental_equality_masks_concept_split`.
- `project_single_user_no_backcompat`: the 2nd home goes live 2026-10-03/04, and there must be no hard-wired house
  quirks in shared paths.
- `feedback_no_restart_during_sleep`.

### 1e. Prior-art scan — REUSE vs BUILD (REV 2)
| Piece | Verdict | Where |
|---|---|---|
| Every HC behaviour (S1, §9e gates, arrester, borrows, nudges, AC reset, egress, D9/CPR, B1) | **REUSE unchanged** | state-of-play §4–§9e |
| Write routing through the strategy | **REUSE** (P1 already routes every write site A2–A14 and S1) | `hvac_strategy.py:364-490` |
| "manual" predicate routing | **REUSE** (P1 `is_manual_hold_for`) | `hvac_strategy.py:581` |
| Comfort ranges per preset | **REUSE**: Seasonal Baseline Presets | `hvac_const.py:1132-1223`; `hvac_preset.get_seasonal_setpoints` |
| Echo recognition of URA range writes | **REUSE** the pair ring | `hvac_setpoint.py:71-98` |
| Person-vs-URA classifier | **REUSE** `classify_manual_setpoint_change` through a projected state | `hvac_override.py` ~:150-240 |
| heat_cool capability | **REUSE** the live `hvac_modes` read (`_supports_heat_cool`); no capability field | `hvac_override.py:4618` |
| **Degraded-feature predicate** `feature_available` / `feature_unavailable_reason` | **DELETE** (no consumer; contradicts the ruling) | `hvac_strategy.py:340-352` |
| **`ProfileCapabilities`** | **TRIM** to 10 command / read / classify facts (§4.8) | `hvac_strategy.py:119-210` |
| **Projected preset read** `strategy.preset_of(state)` | **BUILD** (one method). Carrier/Generic = the raw attribute (byte-identical) | none exists. HC reads the raw `preset_mode` at ~19 sites (§5) |
| `EcobeeHomeKitStrategy` | **BUILD** (one class) | none exists |
| Per-entity resolution cache (P1 F1) | **BUILD** (small fix) | `hvac_strategy.py:554-555` |
| `zone_thermostat_profile` override | **BUILD**, minimal (parent ruling 3); Q2 asks whether to drop it | none exists |
| REV 1 gate (f), `person_hold`, `person_hold_limit`, new feature keys, B1 brand gate, S10/egress/borrow/nudge brand gates | **DROPPED** (operator ruling) | — |

### 1f. Producer / consumer — new value "projected preset of an ecobee entity"
- **Producer:** `EcobeeHomeKitStrategy.preset_of(state)` (§4.3). It depends on:
  - the live state;
  - the adapter's `held` record (label and range of URA's last hold or pin, set BEFORE the wire);
  - the current-season Seasonal Baseline table (the restart fallback);
  - `ECOBEE_RANGE_TOLERANCE_F` (measured at D0b).
- **Consumers:** every site in §5. Trust consumers: S1, the arrester detection paths, the `begin_excursion` snapshot,
  egress snapshot, and the compliance tracker. Display: `zone_N_status.preset_mode`.

### 1g. Config-first check
No setting solves this. House 2 can run with no zones (HVAC idle) until this ships.

---

## 2. Corrections to the parent plan (fix the parent in the same commit as this plan's approval)

| # | Parent / REV 1 claim | Truth | Evidence |
|---|---|---|---|
| P2-C1 | Parent REV 3 banner: "per-zone Home/Sleep/Away setpoint fields do NOT exist … no AWAY"; REV 3.2: "Missing ranges → a Repair" | House-wide ranges for Home / Sleep / Away / Vacation exist per season, with defaults. They can never be missing | `hvac_const.py:1132-1223`; `config_flow.py:7853` |
| P2-C2 | Parent P2 item 7 (single-setpoint ring, select ring) and P3 item 4 (`emit_call_service`) are needed | Not needed: URA writes only heat_cool ranges and modes on HomeKit ecobee | §3 |
| P2-C4 | "The funnel writes setpoints" is profile-neutral | On HomeKit, a range write while the device is not in heat_cool sends `temperature=None` | §1c |
| P2-C5 | — | No P1 code-review record exists in `docs/reviews/code-review/` | Glob `docs/reviews/code-review/*w1c*` |
| R2-C1 | REV 1 P2-C3 / F5: B1 overriding a person's cool/heat on ecobee is a defect to gate | **Withdrawn.** B1 does the same on Carrier by design (`hvac.py:2584-2589`) | operator ruling 2026-10-03 |
| R2-C2 | REV 1 §4.7: on ecobee every feature except hold is unavailable | **Withdrawn.** Once `preset_of` gives the HC readers Carrier's view, the features work; their preset returns are translated by the adapter | §4 |
| R2-C3 | "Ideally zero HC changes beyond P1 routing" | **Not achievable for reads.** P1 routed every WRITE and every `"manual"` comparison, but the VALUE compared is still read raw at ~19 sites. Writes need no change | §5 |
| **R2-C4** | Parent §3a/§3c and P1 code: "P2 pipes `feature_available` to the degraded-feature surface"; the 21-field `ProfileCapabilities` "is what a thermostat profile can do" | **Superseded by the ruling.** Features are never gated by brand. Capabilities record only how to command, read and classify. The predicate and 11 fields are deleted (§4.8) | operator review addendum 2026-10-03; consumer grep §1b |
| **R2-C5** | Batch C REV 3.3 U1: S10 checks `strategy.feature_available("cpr")` as skip step 0.3 | **Superseded.** S10 calls `set_preset_range` and branches on its `WriteStatus`; a brand with no device preset to edit returns `SKIPPED_ALREADY_CORRECT("no_device_presets")` | §4.9; Batch C plan :1215-1216 |

---

## 3. Marginal-benefit decisions (parked, not deleted)

| Piece | Decision | Revival trigger |
|---|---|---|
| Native `ecobee` integration profile | **PARK** (Q3) | A real install to measure |
| Native comfort-preset holds as a per-brand option | **PARK**. When built it is a per-brand command choice, default OFF, so ranges stay URA's default | Native profile revived and the operator wants device comforts |
| Single-setpoint ring, select ring, `emit_call_service`, `release_hold` caller | **PARK** | A heat-only/cool-only profile, or an approved hand-back |
| `climate_write.profile` ledger key | **PARK** | A diagnosis the zone sensor + entity id cannot answer |
| Per-zone comfort ranges | **PARK** | Two ecobee zones needing different comforts |
| Per-profile suppression TTL consumption | **CONDITIONAL** (only if D0b p95 echo exceeds the 15 / 120 s windows) | D0b result |
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
  - `_test_reset_cache` (`hvac_strategy.py:589`) also clears `_RESOLVED_BY_ENTITY`. Seven test files call it or patch
    `_entity_platform`, and they reuse entity ids, so a cache that is not cleared would leak between tests.
- **Cache keying (PR2-7):** `_STRATEGY_BY_PLATFORM` (`hvac_strategy.py:536`) is keyed by platform. The ecobee
  instance must NOT be stored under `"homekit_controller"`, or a non-ecobee HomeKit thermostat inherits it. Key it by
  (platform, manufacturer match) or by entity. A Generic cached from a registry MISS is replaced on the first later
  HIT (a profile switch, with the flushes below). Tests get an autouse fixture that clears both caches (the
  parametrized `test_registry_miss_generic_identical_to_carrier_golden` reuses entity ids; a leaked `last_sent` would
  flip a case to SKIPPED). Manufacturer comes from the DEVICE registry (`entry.device_id`), not the entity entry.
- **Undispatchable until measured:** while the D0b constants are `None`, the ecobee profile resolves to Generic: no
  writes of its own, and one Repair "complete the ecobee check".
- **Profile switch:**
  - flush `last_sent` and `held` on both instances;
  - flush the entity's suppression stamps;
  - close every live borrow row of the zone with NO write (`return_excursion(trigger="profile_switched",
    restore_ok=None)`) (P1 F3).

### 4.2 Command verbs (the "how to command it efficiently" part)
These have the same signatures as P1. HC call sites do not change.

| Verb | Carrier (unchanged) | EcobeeHomeKit |
|---|---|---|
| `hold_preset(P)` (S1) | `set_preset_mode P` (+ funnel resume-then-pin) | Look up `(cool, heat) = get_seasonal_setpoints(P)` through an injected resolver. No range → `FAILED("no_range_for_preset")`, zero calls. Then: (1) set `held[entity] = (P, heat, cool)` BEFORE the wire; (2) write the range through `emit_set_temperature` (freeze floor, deadband and pair ring apply); (3) `_record_sent("set_preset_mode", P)` so the D2.5 no-op and `_zone_last_write_is_away` work unchanged. No-op: SKIPPED when `last_sent == P` AND `preset_of(state) == P` |
| `pin_preset(P)` (S4, S7, S8/S9, A10, A14, egress resume, AC-reset preset, S11/S13 returns) | delegate to `emit_set_preset_mode` | Same translation as `hold_preset`, without the no-op and without `last_sent` (P1's pure-delegate contract: caller suppression, DEFERRED/APPLIED mapping and exception propagation behave as on Carrier) |
| `set_setpoints(low, high)` (S3, S5, S6 human restore, S12) | delegate to `emit_set_temperature` | Same delegate **behind the §4.2 mode precondition AND a both-legs-numeric precondition** (several callers pass `zone.target_temp_low`, which is None when the ecobee is not in heat_cool — e.g. `hvac_override.py:5779`, `:6086`, `:7315`, `:7789`; a one-leg call is the same `temperature=None` hazard). Failing precondition → DEFERRED, zero calls (PR2-3). `held` NOT updated, so the range reads `manual` — what a raw setpoint write does on Carrier |
| `set_preset_range(P, low, high)` (S10 / CPR, Batch C) | Batch C `CarrierStrategy.set_preset_range` (edit the device preset via `ha_carrier.set_activity_setpoint`) | **No device preset to edit** → `SKIPPED_ALREADY_CORRECT("no_device_presets")`, zero calls. URA keeps the range itself: the adapter's hold translation always reads the CURRENT Seasonal Baseline / CPR range, so the next `hold_preset(P)` / `pin_preset(P)` writes the new range. See §4.9 |
| `set_hvac_mode(m)` (B1, B4, AC reset, egress) | delegate to `emit_set_hvac_mode` | Same delegate |
| `release_hold` | no caller | no caller |

**The one command hazard (P2-C4).** A range write while the device is not in heat_cool sends `temperature=None` on
HomeKit. The adapter owns this inside its range-writing verbs:
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

**Ordering inside every ecobee range verb (PR2-1, binding):** (1) live-mode + both-legs precondition → DEFERRED,
zero calls, `held` and `last_sent` untouched; (2) resolve the range (`hold_preset`/`pin_preset` only); (3) apply
`apply_setpoint_guards` (`hvac_setpoint.py`, same `freeze_active` the funnel will get) and the D0b device min delta,
so the stamped range is the range that goes on the wire (clamp before stamp); (4) stamp `held` with the POST-guard
range; (5) call `emit_set_temperature`; (6) on DEFERRED or exception restore the previous `held` (then re-raise /
return as P1 does); (7) `_record_sent("set_preset_mode", P)` on APPLIED only (`hold_preset` only).
**No-op (PR2-2):** SKIPPED only when `last_sent == P` AND `preset_of(state) == P` AND the live legs equal the
CURRENTLY resolved post-guard range for P within tolerance. Without the third clause a season rollover, a baseline
edit or a CPR edit never reaches the thermostat while the house state stays the same.
`pin_preset` on ecobee ignores the caller's `emit=` (it is the preset funnel) and always uses `emit_set_temperature`.

### 4.3 State read — `preset_of(state)` (the projection)
- **Carrier / Generic:** `state.attributes.get("preset_mode")`, verbatim, with the call site's existing default.
- **EcobeeHomeKit:**
  1. None / `unavailable` / `unknown` → the site's existing default.
  2. Mode `heat_cool`, both legs numeric:
     - `held[entity]` matches within `ECOBEE_RANGE_TOLERANCE_F` → its label;
     - else, **only when `held[entity]` is ABSENT** (restart / never held), exactly ONE current-season baseline range
       matches → that preset name (restart fallback; two baseline ranges within 2 × tolerance of each other → no
       match). With `held` present, a mismatch is `manual` (PR2-4: summer home 77/70 vs sleep 76/70 differ by one
       leg by 1 °F — a person's 77→76 must read `manual` and reach the arrester, not read `sleep`);
     - else `"manual"`.
  3. Mode not `heat_cool` → the label of `held[entity]` if any, else `""` (mirrors Carrier: a mode drift keeps the
     preset name and B1 owns the drift).
- `is_manual_hold` is inherited unchanged (`== "manual"`). `observe()` uses `preset_of` on ecobee.
- **`is_human_manual_snapshot` MUST be overridden on ecobee (PR2-6)** to Carrier's rule (`pre_preset in (None, "",
  "manual")`). The inherited Generic version (`hvac_strategy.py:313-326`) also returns True when `preset_modes` is
  empty — always true on HomeKit — which would turn every ecobee borrow return into a raw-setpoint restore.
- `release_hold` on ecobee returns `FAILED("no_device_hold_release")`, zero calls (it would send preset `resume`,
  breaking INV-E2 if a caller is ever added).

**Consequence the operator should know (Q1).** If the ecobee's own hold expires or its program moves the range, the
projection reads `manual` and the arrester treats it like a person's change on Carrier. The setup notes say: hold
action "until I change it", no ecobee program.

### 4.4 Ours-vs-person classifier
- `EcobeeHomeKitStrategy.classify_person_change` is the same delegate as Carrier's, fed projected states. The raw
  read at `hvac_override.py:212` is routed (§5 R2).
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
conditional C1. No HC site branches on a capability.

**Immune-hold sunset** reads `next_activity_time`, which ecobee lacks. The builder confirms (step 0) that it reads
absent as "no sunset signal" and never raises. This is a read-safety check, not a feature gate. The deleted
`has_next_activity_time` field is not needed for it.

### 4.6 What does NOT change
- B1, S1 and §9e gates, the arrester, borrows and their primitive, nudges / AC reset, egress, D9/CPR.
- The funnels' service_data (except §4.2 option (ii), if chosen), the pair ring, and every switch default.
- No new user-facing switch. A feature the operator turns off on House 2 uses the switch it already has.

### 4.7 P1 review findings folded in
| # | Finding | Fix |
|---|---|---|
| F1 | Generic no-op never fires (registry miss → fresh uncached Generic; A-L2) | Per-entity cache (§4.1). Test: two S1 ticks on a registry-miss entity → second SKIPPED |
| F2 | `GENERIC_CAPABILITIES` inconsistent: dual_leg but `person_change_shape=single_setpoint`, window 600 (A-L3) | Generic = heat_cool_both_legs / None (§4.5). Test pins consistency for every profile |
| F3 | `_auto_return` resolves the profile from the CURRENT entity (B-L2) | Close live borrow rows at profile switch (§4.1) |
| F4 | S1 FAILED raises `RuntimeError` → ERROR every tick; preset suppression never rolled back (B-L1) | FAILED → `unsuppress`, one INFO per (zone, reason) per boot, one `preset_change_deferred` row, `continue`. **Scope (plan review #1):** only for capability reasons (`no_presets_supported`, `no_range_for_preset`). `FAILED("emit_raised")` (a Carrier wire exception, `hvac_strategy.py:484-486`) keeps today's `RuntimeError` path (`hvac.py:3678-3682`) unchanged; otherwise INV-C breaks outside its one named exception. Test: 3 ticks on a no-presets Generic → 0 ERROR, 1 INFO, empty suppression map. Test: a Carrier `emit_raised` still raises |
| ~~F5~~ | ~~B1 overrides a person's heat/cool~~ | **Withdrawn (R2-C1)** |

### 4.8 P1 scaffold removal (operator review addendum, 2026-10-03)
P1 shipped a feature-gating scaffold that contradicts the thin-adapter ruling: features needing a named preset were
marked unavailable on brands without one, and CPR was marked unavailable without Carrier's activity-setpoint service.
It has NO production consumer (§1b grep), so removing it changes no behaviour. P2 deletes it:

1. **Delete** `GenericStrategy.feature_available` and `feature_unavailable_reason` (`hvac_strategy.py:340-352`).
   - Features that need a named preset call `hold_preset` / `pin_preset`, and the adapter translates (ecobee: preset →
     Seasonal Baseline range).
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
  - EcobeeHomeKit: `SKIPPED_ALREADY_CORRECT("no_device_presets")`, zero calls. URA keeps the range in its own
    config, and the next hold or pin writes it (§4.2).
- **Sequencing:** whichever of P2 and Batch C builds second adds its half:
  - Batch C first → P2 adds `EcobeeHomeKitStrategy.set_preset_range` and deletes the U1 step 0.3 if it shipped.
  - P2 first → Batch C builds against the verb shape directly and drops step 0.3 and the test
    `test_generic_set_preset_range_zero_calls_feature_unavailable` (rename to `..._unsupported`).
- **Open interaction for Batch C's reviewers:** on ecobee, a D9 compose-away S10 write today goes through
  `set_setpoints` (raw range, reads `manual`) on Carrier too. That is the same semantics, so no P2 action.
- **Action in this commit:** add a one-line pointer in the Batch C plan's ruling note to §4.9 here (doc edit only).

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
| R2 | `hvac_override.py:212` | within-manual classifier. **It is called DIRECTLY at `hvac_override.py:3636`, not through `strategy.classify_person_change`, which has no production caller.** Its signature has no `hass` / entity. The builder threads a projection, either as a `preset_of` callable parameter or as pre-projected old/new presets. Carrier passes the raw values (byte-identical) |
| R3 | `hvac_override.py:1340` | `_latch_state_discharges`, the interrupt-latch discharge predicate (§9e N1). Trust: a raw None on ecobee would never discharge the latch |
| R4 | `hvac_override.py:2595` | startup audit |
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
| R16 | `coordinator_diagnostics.py:575`, `:600` | compliance tracker actual / override source |

**Excluded on purpose:**
- `hvac_setpoint.py:199`: ledger `values_before` stays raw.
- `hvac_fans.py:2034`, `:2314`: fan entities.

**Scaffold removal (§4.8):**
- `hvac_strategy.py` only (:39, :119-210, :340-352).
- The test file `quality/tests/test_hvac_w1c_p1_profile_contract.py` (:163-210).
- No HC call site, because there are no consumers.

**Conditional (D0b-gated):**
- C1: suppression TTL read (`hvac_override.py:133` / `:173`) takes the profile's `echo_ttl_s`.
- C2: the funnel `hvac_mode` kwarg, only for §4.2 option (ii).

Plan reviewers must re-grep `preset_mode`, `feature_available`, `.capabilities` and every deleted field name rather
than trust these lists.

---

## 6. Falsifiable invariants (for reviewer D to break)
- **INV-C (Carrier byte-identity).** For any `ha_carrier` zone, the following are identical to v5.103.36: every
  `climate` call; every ledger row (`climate_write`, `ura_activity_log` incl. `gate_snapshot`, `ac_ramp_events`,
  `hvac_excursion_events`); the suppression store; the in-memory state; and every R-site read value. This holds across
  restart and mid-borrow reload. The 168 goldens replay unchanged and are not regenerated.
  - **Single named exception:** the F4 S1 FAILED row (reviewed one-row diff).
  - The §4.8 deletions add no exception.
- **INV-P (parity).** An ecobee zone and a Carrier fixture fed equivalent states (Carrier `preset_mode` =
  `preset_of(ecobee state)`, the same legs and events) produce the same HC decision trace. The only difference is the
  translated wire verb. Repro shapes:
  - URA pins `sleep` → echo → no `override_detected`;
  - a wall change to 72/68 under home → booked HUMAN → the arrester acts per delta as on Carrier;
  - nudge start → reads `manual` → restore pin → reads the named preset;
  - restart at the Home range → reads `home` → S1 no-op;
  - restart with a person's 72/68 → reads `manual` → §9e decides as on Carrier;
  - S10 on ecobee → `no_device_presets`, then the next S1 hold carries the new range.
- **INV-F (no brand feature gate).** No HC code path chooses whether a URA feature runs from the thermostat brand or
  from a capability field. It may only use a verb's `WriteResult` or a live entity read.
  - Falsified by: any `feature_available`-style predicate, or any `.capabilities.` read outside `hvac_strategy.py`
    (the AST lint, §4.8 item 4).
  - **(plan review #1)** The lint also forbids, outside `hvac_strategy.py`, any `.platform` read on a strategy, any
    `isinstance(..., <Strategy class>)`, and any comparison against `CARRIER_PLATFORM`. One reasoned allowlist entry
    covers the Carrier freshness/reload path (`hvac.py:7381` `_check_carrier_freshness`, `:7689`), per the §12
    disposition below.
- **INV-E2 (ecobee wire whitelist).** URA never calls the following on a HomeKit ecobee:
  - `climate.set_preset_mode`;
  - `set_temperature` with a `temperature` key;
  - a range while the live mode is not heat_cool, unless `hvac_mode="heat_cool"` is in the same call (option ii);
  - any non-`climate` service.
- **INV-G (Generic stays blocked).** A Generic zone whose entity advertises no `preset_modes` makes zero
  `climate.set_preset_mode` calls, including `resume`. S1 on it returns `FAILED("no_presets_supported")` and makes
  zero calls. (Restated by plan review #1: "zero writes of its own initiative" was not falsifiable. Under the ruling,
  Generic still runs B1, nudges and borrow setpoint writes like any brand.)

## 7. Deliverables

### D0 — Measure before build (gates D1–D3)
**D0a: read-only (orchestrator, House 2 REST; token held locally, never committed).**
- Device registry `manufacturer` / `model` / `sw_version`.
- `hvac_modes` and `supported_features`.
- Whether legs appear in heat_cool.
- 24 h of state changes.

Report: `docs/planning/AUDIT_house2_ecobee_probe_2026_10_0x.md`.

**D0b: supervised live probe — validates the ADAPTER CONTRACT (command + classify).** Operator-run, operator at the
thermostat, House 2 HVAC coordinator OFF. Script `scripts/probes/ecobee_write_probe.py`. Each step needs an operator
`y`; events are logged with monotonic timestamps. Abort outside 66–80 °F or on "stop". The operator restores the
original settings at the end.
- **P0:** the operator reads the hold action, the min delta, whether a program is running, and whether Auto heat/cool
  is enabled.
- **P1 (mode command):** `set_hvac_mode heat_cool` from `cool`. Does the entity reflect it at once (§4.2 i/ii)? What
  is the latency? Do the legs appear?
- **P2 (range command + echo):** five range writes ≥ 2 min apart. Measures latency p50/p95/max, readback rounding,
  and the hold type shown.
- **P3:** narrow range 72/74 → widened?
- **P4 (classify):** wall-unit setpoint change. Measures the shape, the latency, and whether it is separable from the
  P2 echoes by value and timing.
- **P5:** wall-unit mode change and back.
- **P6:** app "Resume schedule" → its signature.
- **P7 (optional):** one hold expiry or program transition.

Outputs: `ECOBEE_RANGE_TOLERANCE_F`, echo p95 and the C1 verdict, deadband minimum, the §4.2 (i)/(ii) verdict, and the
§4.4 separability verdict.

**Acceptance:**
- **Verify:** a value table with n.
- **Verify:** a written separability verdict. NOT separable → operator (Q4) before build.
- **Live:** this IS the live step.

### D1 — Detection, per-entity cache, override, Repairs, profile switch (§4.1, F1, F3)
- **Test:** registry fixtures resolve as specified: Carrier / HomeKit-ecobee / HomeKit-non-ecobee / native ecobee
  (→ Generic) / made-up brand / no entry. Carrier goes through the unchanged platform cache (identity-asserted).
- **Test:** `test_w1c_p2_registry_miss_generic_noop_persists`.
- **Test:** undispatchable → Generic + Repair, zero writes.
- **Test:** a profile switch flushes `last_sent`, `held`, suppression and live borrow rows.
- **Sensor:** `zone_{n}_status` attrs `thermostat_profile`, `profile_source`.
- **Live (House 1):** three zones `carrier` / `detected`; zero new Repairs.

### D2 — Command verbs (§4.2)
- **Test:** S1 `home` on a HomeKit fixture in heat_cool → one `set_temperature {70, 77}` via the funnel; one
  `climate_write` row; pair ring (70, 77); `held` set before the wire.
- **Test:** the same tick again → SKIPPED.
- **Test:** every `pin_preset` caller (S4 / S7 / A10 / A14 / egress resume / AC-reset preset) → a range write, never
  `set_preset_mode`.
- **Test:** `set_setpoints` leaves `held` untouched.
- **Test:** `set_preset_range` → `SKIPPED_ALREADY_CORRECT("no_device_presets")`, zero calls (only if Batch C's verb
  exists at build time; else §4.9 sequencing).
- **Test:** mode `off` → DEFERRED, zero calls.
- **Test:** mode `cool` → the chosen (i)/(ii) behaviour.
- **Test:** `_zone_last_write_is_away` true after an applied `away` hold.
- **Mutation drills:**
  - remove the mode precondition → the INV-E2 test fails;
  - record `held` after the wire → the D3 echo test fails.

### D3 — Projection + classifier (§4.3, §4.4, §5 R1–R16)
- **Test:** table-driven `preset_of` over every §4.3 row, including tolerance edges and duplicate-baseline → no match.
- **Test:** the INV-P harness (one scenario list, Carrier vs ecobee fixture, decision traces compared field by field).
- **Test:** each R-site returns the identical value on Carrier (goldens) and the projection on ecobee. Each R-site
  gets one site-anchored test.
- **Mutation drills:** reverting R1 / R7 / R15 to a raw read turns its own test red.
- **Lint:** no raw thermostat `preset_mode` read outside `hvac_strategy.py` + allowlist.

### D4 — P1 scaffold removal + F2 + F4 (§4.7, §4.8)
- **Code:** §4.8 items 1–4.
- **Tests:** the §4.8 test table; `test_w1c_p2_s1_failed_no_error_spam`.
- **Golden:** the single reviewed F4 row delta; the 168 goldens otherwise replay unchanged after the deletion.
- **Mutation drill:** re-add a `feature_available` method on `GenericStrategy` → the absence lint fails. Add a
  `strategy.capabilities.hold_via` read in `hvac.py` → the `.capabilities` lint fails.
- **Verify:** `grep -rn "feature_available\|feature_unavailable_reason" custom_components/` returns nothing.

### D5 — Docs
- State-of-play:
  - header line;
  - §4.1 (adapter row);
  - §4.4 (read model: `preset_of`);
  - §5 → an "ecobee/HomeKit facts" companion table from D0b;
  - §10: C30 = P2-C1; C31 = R2-C3; C32 = R2-C4 ("P1's `feature_available` / capability flags were the planned
    degraded-feature surface" — superseded, deleted unconsumed).
- Parent plan banner pointing here.
- Batch C plan pointer (§4.9).
- `README_v5.103.x.md` with a Live section.
- Ecobee setup notes: hold action "until I change it", no ecobee program, Auto heat/cool enabled.

**Live acceptance (post-deploy):**
- **House 1:** `SELECT DISTINCT verb, site, json_extract(values_after,'$')` key sets equal before vs after; zero new
  Repairs; zones show `carrier`.
- **House 2** (operator-gated, coordinator ON):
  - A Home → Sleep → Home walk gives exactly 3 S1 `set_temperature` rows with the baseline ranges, and
    `zone_1_status.preset_mode` reads home → sleep → home.
  - A wall-unit change gives one `override_detected` row matching what Carrier does with the same switches.
  - Zero `set_preset_mode` rows.
- **Discrimination:**
  - a broken projection shows S1 rewriting the same range every tick;
  - a broken classifier shows the wall change booked as `ura_echo`, or URA's own write booked as an override.

## 8. Knobs
| Name | Rung | Default | Why |
|---|---|---|---|
| `zone_thermostat_profile` | 2 (Manage Zones → Thermostat, Advanced) | absent = detect | set-once; kill switch for a wrong detection (Q2) |
| `ECOBEE_RANGE_TOLERANCE_F` | 1 | from D0b | physics |
| ecobee `echo_ttl_s` / `preset_echo_ttl_s` / `write_rate_min_interval_s` | 1 (`ProfileCapabilities`) | from D0b | protocol |
| Comfort ranges | REUSED rung 2 (Seasonal Baseline Presets / CPR) | existing | URA's opinionated default |
| Every HC feature switch | REUSED | unchanged URA defaults | the ruling |

No new Number / Switch entities. No inline literals.

## 9. Non-goals
- No brand gating of any HC feature, and no capability-based feature predicate (INV-F).
- No new person-hold concept, no new user switch.
- No native ecobee, no select/button writes, no `release_hold` caller, no ecobee program editing.
- No humidity / fan_mode control.
- No change to the borrow primitive, arrester state machine, pair-ring shape, or the Carrier classifier.
- No optimizer climate actuation out of shadow.
- No golden regeneration beyond the F4 row.

## 10. Tier + review protocol
- **Tier 3 (kept, with a smaller surface than REV 1).** Why it stays Tier 3:
  - The R1–R16 routing touches the shared read path of every zone's S1 and arrester. The failure is ONE missed site:
    a raw read that sees None on ecobee reads "not manual" → S1 writes over a person's change (Bug Class #53 shape).
  - Carrier byte-identity must hold.
  - It is comfort-impacting at a live second home.
- The §4.8 deletion is zero-consumer and adds no risk class. It rides in the same cycle because it changes the
  contract the adapter is built against.
- **Plan reviews (two, framing-disjoint):**
  1. Completeness: re-grep every thermostat `preset_mode` / `hvac_modes` / `target_temp_*` / `next_activity_time` /
     `hold_activity` read, every strategy write site, every `feature_available` / `.capabilities` / deleted-field
     reference (code, tests, plans); confirm §5.
  2. Adversarial build-prediction: `held` ordering, the season-rollover fallback, (i) vs (ii), the non-heat_cool
     projection branch, Batch C sequencing.
- **Build:** `ura-super-builder`. Then four framing-disjoint reviews:
  - **A:** adapter local correctness.
  - **B:** HC integration parity (INV-P), restart, Carrier byte-identity.
  - **C:** per-site source mutation of every R-site, the precondition, `held` ordering, F1–F4 and the §4.8 lints, plus
    the golden replay.
  - **D:** breaks INV-P / INV-F / INV-E2 / INV-C across the whole read surface, including pre-existing raw reads in
    `sensor.py` / `binary_sensor.py`. Config extremes: arrester OFF, TAO ON, D9 ON, nudge master OFF/ON, egress
    pause, an operator-edited baseline creating a duplicate range, season rollover, restart mid-nudge on ecobee.
- The orchestrator re-greps and runs one live mutation before ship.
- Operator checkpoint before deploy. No restart while House 1 sleeps.

## 11. Operator questions (REV 2)
**Moot under the ruling (REV 1 Q → disposition):**
- REV 1 Q1 (person-hold discharge): moot. The arrester and §9e own it.
- REV 1 Q2 (house-wide baselines): answered by the ruling. Uses Seasonal Baseline Presets.
- REV 1 Q4 (native presets vs ranges): answered (ranges are the default). Native comfort holds parked as a default-OFF
  brand option.
- REV 1 Q6 (hand-back): moot. Carrier does not hand back either.
- REV 1 Q7 (egress on ecobee): moot. On, per the URA default.
- REV 1 Q8 (person mode change): moot. B1 behaves as on Carrier.

**Remaining:**
1. **Q1: ecobee's own hold expiry / program reads as a person change.** The arrester then reverts or compromises by
   delta, as with a person on Bryant. The mitigation is the setup notes (hold "until I change it", no ecobee program).
   OK? (Recommended: yes.)
2. **Q2: keep the `zone_thermostat_profile` override field?** (Recommended: keep. It is one Advanced field and the
   only way to stop a misdetected brand without a release.)
3. **Q3: native `ecobee` integration.** Defer until a real install exists? (Recommended: defer. I believe ecobee
   stopped issuing new developer API keys, but I have not verified that.)
4. **Q4 (decision point raised only by D0b):** if URA's echo cannot be told apart from a wall-unit change on HomeKit,
   the report comes back to you with options: accept, widen tolerance, or run House 2 with the arrester switch off.
   No feature is disabled by brand without your call.
