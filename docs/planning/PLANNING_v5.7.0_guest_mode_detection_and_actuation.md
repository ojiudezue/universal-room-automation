# PLANNING v5.7.0 — Guest-Mode Detection Trust + HVAC Actuation

**Version:** v5.7.0
**Author:** ura-planner
**Status:** Build-ready
**Tier classification:** **Workstream A = Tier 3** (4 framing-disjoint reviews incl. adversarial-completeness + operator pre-deploy checkpoint); **Workstream B = Tier 2-DB** (3 framing-disjoint reviews). Cycle ships A then B (B gated on A live-validation).
**Predecessor cycle:** v4.6.2.2 (guest-entry gate); v4.7.14 (AWAY ghost-presence veto); v4.7.14.1 (H1 census guard, H2 phone-trust filter, H3 ACTIVE-only tracker filter).

---

## Motivation — the precise miss

v4.6.2.2 guest-hardening was scoped **only** to the unidentified/camera-census GUEST-entry gate (`presence.py:961-973`, `_guest_gate_armed` threshold/confidence/persistence guards). It never touched:

1. The **person-tracker trust axis** (`tracking_status` LOST/STALE vs `location=="away"`). The H3 ACTIVE-only filter shipped in v4.7.14.1 (`presence.py:4090-4147`) treats a LOST-but-away phone as **untrusted** and drops it from the denominator — meaning a dead-phone resident who has actually left the house never contributes to the AWAY veto.
2. **Outdoor zones.** No `is_outdoor` field exists today, so an occupied "Outside" / "Front Porch" zone counts equally with an indoor bedroom for `any_zone_occupied` (`presence.py:4178-4181`), and (after WS-A2 adds an indoor-occupancy guard) would silently jam the AWAY veto.
3. **The AWAY veto itself** (`presence.py:916-924`) — it didn't exist until v4.7.14, so v4.6.2.2 couldn't have addressed the LOST-tracker case.

This cycle owns that missing delta. The naive fix ("count LOST-but-away as away in the veto denominator") was prototyped and found to introduce a HIGH regression — force-AWAY-while-home for a dead-phone resident sitting still on mmWave with census==0. The plan below threads that needle: trust LOST-but-away **only** when no real indoor evidence contradicts it, AND only after a configurable grace, AND with a sleep exemption (a sleeping resident's phone can be dead for hours).

---

## Institutional context verified

### Greps run + results

**Workstream A — detection trust:**

| Proposed addition | Search | Result |
|---|---|---|
| `CONF_LOST_AWAY_GRACE_MIN` (house-level number, default 60) | grep `CONF_LOST_AWAY\|LOST_AWAY_GRACE\|lost_away_grace` across `custom_components/universal_room_automation/` | **NEW** — no equivalent. Closest neighbors are `CONF_GUEST_MODE_PERSISTENCE_SECONDS` (`const.py:1377`) and `CONF_GUEST_MODE_REQUIRE_CONFIDENCE` (`const.py:1380`) for the GUEST-entry path, and person_coordinator's `_min_away_minutes` (`person_coordinator.py:235-279`) which gates BLE pre-arrival, NOT veto denominator membership. Place in `const.py` near the other guest/presence CONFs (~`const.py:1370-1385`). |
| `CONF_LOST_AWAY_SLEEP_EXEMPT` (bool, default True) | grep `sleep_exempt\|SLEEP_EXEMPT` | **NEW** — no equivalent. House-state-aware exemption is unique to this veto path; no prior infrastructure. |
| `CONF_IS_OUTDOOR` / `CONF_ZONE_IS_OUTDOOR` (per-zone bool, default False) | grep `CONF_IS_OUTDOOR\|CONF_ZONE_IS_OUTDOOR\|is_outdoor\|outdoor_zone\|CONF_ZONE_TYPE` across whole package | **NEW** — zero hits (the only "outdoor" hits are outdoor-temp sensors in HVAC). Confirms there is no existing zone classification we can reuse. Add to zone config-flow alongside `CONF_ZONE_NAME` (`config_flow.py:270, 884`) on the zone setup step (`async_step_zone_setup` at `config_flow.py:802`) and zone options. |
| LOST-but-away counting in veto denominator | grep `_tracking_active\|TRACKING_STATUS_ACTIVE` in `presence.py` | **REUSED** — `_tracking_active` helper at `presence.py:4090-4101` is the exact site where H3 filters; the WS-A1 change relaxes the filter to permit `tracking_status in (LOST, STALE)` when `location=="away"`. The H2 `phone_left_behind` filter at `presence.py:4123-4147` is preserved unchanged. |
| AWAY veto site | grep `all_tracked_persons_away` in `presence.py` | **REUSED** — single emission site is `infer()` at `presence.py:916-924`. WS-A2 adds the indoor-occupancy guard there. The diagnostic helper `should_veto_due_to_reliable_signals` (`presence.py:1354`, called from `aggregation.py:3836, 3982, 3852, 3992` and `presence.py:4512/4604/4676`) is a SEPARATE surface; prior Fix-A tests drove it by mistake — new tests MUST drive `infer()`. |
| `any_zone_occupied` aggregation | grep `any_zone_occupied` in `presence.py` | **REUSED** — built at `presence.py:4178-4181`; consumed by `infer()` (`:899, :916`). WS-A4 introduces an `any_indoor_zone_occupied` derivation alongside it (zones whose config-flow `is_outdoor==False`); the existing `any_zone_occupied` symbol is preserved for non-veto consumers (no rename). |
| Census-count outdoor exclusion | grep `census_count` in `presence.py` and `camera_census.py` | **REUSED** — census is camera-only (mmWave doesn't feed it; confirmed by reading `presence.py:912-919` doc-comment "If Frigate face-IDs a resident…"). Camera-area→zone mapping lives in `camera_census.py`. WS-A4 excludes outdoor-zoned cameras from the indoor census contribution. |
| Sleep state for exemption | grep `HouseState.SLEEP\|HouseState.HOME_NIGHT\|_is_sleep_hour` | **REUSED** — `_is_sleep_hour` at `presence.py:945` and `HouseState.SLEEP / HOME_NIGHT` enum values. Pass `current_state` (already a parameter of `infer()`) through to the new guard. |
| Person-coordinator stamp of LOST+away | grep `TRACKING_STATUS_LOST` in `person_coordinator.py` | **REUSED** — verified at `person_coordinator.py:338-349` (no-Bermuda fallback writes `location="away"`, `tracking_status=LOST`, `confidence=0.9`) and `:371-381` (no-Bermuda-sensor path, same shape). This IS the data WS-A1 will permit into the denominator. |

**Workstream B — HVAC actuation (revised 2026-06-28 after deep re-audit; operator-confirmed substrate is the v4.7.17.2 DPM rolling-median relax/tighten engine, NOT the dormant per-bucket cells):**

| Proposed addition | Search | Result |
|---|---|---|
| Relax/tighten adjustment engine | grep `_compute_cool_high_adjustment\|relative_delta\|cool_high_adjustment_f` | **REUSED-and-EXTENDED** — `_compute_cool_high_adjustment(relative_delta, relax_f, tighten_f)` at `dynamic_preset.py:109-132` is the **live, working** substrate. Inputs: `relative_delta = today_apparent_high − 14d rolling median apparent high` computed via `statistics.median` at `weather_manager.py:613` (and the p25 used by the relax-ceiling gate at `weather_manager.py:636`). Output consumed at `dynamic_preset.py:923` as `effective_home_high = seasonal_cool + zone_offset + cool_high_adjustment_f`. WS-B2/B4 add **additional signed terms (guest-cool, vacant-warm) to this same arithmetic chain** — they are not separate producers. |
| Per-bucket cells as runtime clamp bounds | grep `_BUCKET_CONF_KEYS` + `CONF_ZONE_DYNAMIC_PRESET_*_HOME_HIGH` value-reads across `custom_components/` | **DORMANT / DIAGNOSTIC-ONLY** — `_BUCKET_CONF_KEYS` registry at `dynamic_preset.py:209-227`; explicit no-op at `dynamic_preset.py:629` / `:851-856` ("per-bucket CONF cells remain dormant in entry.options but are NOT read at runtime"); `docs/readmes/README_v4.7.17.2.md:59` confirms "per-zone bucket cells stay dormant… Runtime ignores them"; zero value-read hits outside the registry. **WS-B1 does NOT revive these cells.** The clamp bounds come from the live preset config the engine already uses (PresetManager seasonal baseline + a NEW per-zone min/max if one is wanted). The bucket cells stay diagnostic-only; do not treat them as the WS-B substrate. |
| Per-zone clamp bounds (live read) | grep `CONF_ZONE_DPM_MIN_F\|CONF_ZONE_DPM_MAX_F\|zone_dpm_clamp` | **NEW** (only if per-zone configurable bounds are desired). Add `CONF_ZONE_DPM_COOL_HIGH_MIN_F` / `CONF_ZONE_DPM_COOL_HIGH_MAX_F` (per zone, defaults derived from PresetManager seasonal min/max for "home" — e.g. `(home_high − 4.0, home_high + 4.0)`). Place in `energy_const.py` near `CONF_ZONE_DYNAMIC_PRESET_OFFSET`. Read scope: the **dict DPM actually reads** (`zone_data` in `_build_overrides_with_reason`, sourced from the Zone-Manager `zones[name]` dict), NOT the CM `entry.options` flat keyspace. If a per-zone live knob is judged unnecessary in build, B3 may clamp to the PresetManager-derived defaults alone; either way, do NOT route through the dormant `_BUCKET_CONF_KEYS`. |
| Per-zone offset | grep `CONF_ZONE_DYNAMIC_PRESET_OFFSET` | **REUSED** — `dynamic_preset.py:859` reads it as `base_offset`. Preserved unchanged. |
| Guest-reset-offset toggle | grep `CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST` | **REUSED (backwards branch — to be reversed)** — `dynamic_preset.py:860-864` zeroes the offset under guest, which RELAXES (warms) instead of cooling. WS-B2 reverses the semantics by folding a signed guest-cool term into `cool_high_adjustment_f`. The legacy flag is preserved as a backwards-compat opt-in. |
| Guest cool-target (per zone) | grep `guest_cool\|CONF_ZONE_GUEST_COOL` | **NEW** — no per-zone guest target exists. Add `CONF_ZONE_GUEST_COOL_HIGH_OFFSET` (per zone, default −1.0°F; negative = cooler) in `energy_const.py` alongside `CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST`. Read from `zone_data` (Zone-Manager `zones[name]` dict), not CM options flat. Folded into the **relax/tighten adjustment math** consumed by `effective_home_high`. |
| Vacant-warm bias (per zone) | grep `CONF_VACANT_WARM\|vacant_warm\|rarely_occupied\|CONF_RARELY_OCCUPIED` | **NEW** — zero hits. Add `CONF_ZONE_RARELY_OCCUPIED_BIAS_F` (per zone, default 0.0°F = disabled; +1.0 to +2.0 for wings). Threshold: `CONF_ZONE_RARELY_OCCUPIED_HOURS_PER_DAY` (default 4.0). Folded as a **+vacant_warm signed term** into the same `effective_home_high` arithmetic. |
| Occupancy-frequency source | grep `occupancy_hours\|7_day_occupancy\|occupancy_snapshot` | **REUSED** — 5-min occupancy snapshots already persist (per VISION_v7.md §"Data Collection: Occupancy snapshots (5-minute intervals)"). A read-only aggregation helper `_zone_avg_occupied_hours_last_7d(zone_id)` is NEW in `dynamic_preset.py` but builds on the existing DB schema; cite the table in build. |
| Guest actuation producer | grep `build_guest_mode_overrides\|"guest_mode"` for `PresetOverride.source` | **REUSED-as-deleted** — `build_guest_mode_overrides` was removed at `preset_overrides.py:241-249` because zero callers wired it. WS-B5 folds guest-cool into the DPM relax/tighten arithmetic (NOT a revived bucket/override-producer). Reasoning: a separate OverrideEngine producer would require a new emission site, new signal subscription, and a parallel test surface; DPM already evaluates per-zone every cycle and already publishes via `ec._dynamic_preset_overrides` (`energy.py:515, 3477-3478`) which HVAC reads at `hvac.py:1495`. Single source of bounds, single emission path. |
| HVAC sink | grep `_async_apply_preset_overrides` | **REUSED** — sink exists at `hvac.py:1462-1497+`, guarded by `_guest_mode_actuation_enabled` (`hvac.py:1479`; switch at `switch.py:1309-1424`). No change to the sink. |
| DPM unclamped path | grep `effective_home_high` | **REUSED-bug** — `dynamic_preset.py:923` `effective_home_high = home_high + zone_offset + cool_high_adjustment_f` has no min/max. WS-B3 clamps the COMBINED result (after guest-cool and vacant-warm terms are folded in) to the per-zone bounds. |
| Cooling-side / winter / master gates | grep `winter_season\|_dynamic_preset_enabled\|CONF_DYNAMIC_PRESET_ENABLED` | **REUSED (inherited limitation — must be documented)** — DPM is cooling-side only; the engine returns `[], "winter_season"` for months 11/12/1/2 at `dynamic_preset.py:597-599`; the entire DPM tick is gated on the `01 · Custom Preset Ranges` master at `energy.py:3329`; per-zone gate at `dynamic_preset.py:580-582`. **Consequence:** WS-B guest-cool and vacant-warm terms are **dormant in winter** and require the DPM master ON + per-zone DPM enabled. State this explicitly as a known limitation (heat-side analog deferred to v5.8.x). |

### Prior planning docs consulted

- `docs/planning/PLANNING_v4.7.x_guest_mode_actuation_phase1.md` (referenced from `hvac.py:1465`) — establishes the OverrideEngine + HVAC sink contract; B5 honors it.
- `docs/planning/PLANNING_v4.7.14_away_state_person_tracker_trust.md` (filename only, per MEMORY index entry "Away-State Person-Tracker Trust") — the original ghost-presence override; this cycle EXTENDS its denominator without weakening its ghost guarantee.
- `docs/planning/PLANNING_v4.7.14_1_*` (H1/H2/H3 fix-ups, per code comments at `presence.py:912-924, 4091-4147`) — establishes the trustworthy-person filter; WS-A1 relaxes ONLY the H3 limb.
- `docs/PLANNING_v3.6.0_REVISED.md` — current-milestone state; this cycle is incremental, no milestone shift.
- `docs/readmes/README_v4.7.17.2.md` — confirms the relax/tighten engine is the live substrate AND that the bucket cells are dormant/diagnostic. (Re-audit anchor, 2026-06-28.)

### Memory bodies pulled

- `project_v4714_live.md` — confirms v4.7.14 went live with `all_tracked_persons_away AND unidentified_count==0` semantics and 33-min uninterrupted post-restart dwell; this cycle preserves that path verbatim for ACTIVE trackers.
- `project_away_state_person_tracker_trust_backlog.md` — confirms the original veto was `presence.py:391` AND-gate + `:1502` away-filter (pre-v4.7.14) and that the StateInferenceEngine.infer() vs ZoneAnyoneBinarySensor.is_on distinction is load-bearing for test framing.
- `project_zone_away_when_occupied_home_night_gap.md` — confirms mmWave-drops-still-body is a known failure mode and that home_night is the uncovered window; WS-A's sleep exemption and indoor-occupancy guard both address this class.

### Design docs read

- `docs/Coordinator/PRESENCE.md` if present (not verified in scoping; builder must read end-to-end before WS-A build).
- `docs/Coordinator/HVAC.md` if present (same).

### Code locations surveyed (read end-to-end during scoping)

- `custom_components/universal_room_automation/domain_coordinators/presence.py` — `infer()` (`:870-980+`), tracker filter (`:4090-4180+`).
- `custom_components/universal_room_automation/person_coordinator.py` — Bermuda + fallback paths (`:140-385`).
- `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py` — `_compute_cool_high_adjustment` (`:109-132`), `_resolve_relax_ceiling` + gate (`:158-196, :694-710`), `evaluate_with_reason` body (`:580-805`), `_build_overrides_with_reason` (`:829-948+`).
- `custom_components/universal_room_automation/domain_coordinators/weather_manager.py` — rolling-median + p25 (`:613, :636`).
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — DPM master gate (`:3329`), `_dynamic_preset_overrides` publish (`:515, :3477-3478`).
- `custom_components/universal_room_automation/domain_coordinators/preset_overrides.py` — `OverrideEngine._eval_predicate` (`:136-155`), deleted `build_guest_mode_overrides` site (`:241-249`).
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — `_async_apply_preset_overrides` (`:1462-1500+`).
- `custom_components/universal_room_automation/switch.py` — guest-mode actuation toggle (`:1309-1424`).

---

## Falsifiable invariants (state up front; D-reviewer must break them)

**Workstream A:**

- **I1 (no force-AWAY-while-home):** Under any reachable state, the house never transitions to `HouseState.AWAY` via the LOST-derived denominator while a real resident is provably home. Formally: AWAY-via-LOST requires `(all_trusted_or_lost_away_persons_away AND unidentified_count == 0 AND census_count == 0 AND NOT any_indoor_zone_occupied)` OR `(grace_elapsed AND NOT sleep_exempt_state)`. Indoor census and indoor zones are the ground truth; an outdoor zone alone does NOT block the veto (WS-A4).
- **I2 (guest-detection preserved):** `unidentified_count > 0` while in HOME_* still arms GUEST. WS-A changes do not regress the v4.6.2.2 `_guest_gate_armed` path.
- **I3 (ACTIVE-tracker path unchanged):** When `tracking_status == ACTIVE`, the v4.7.14 AWAY veto and ghost-presence override behave byte-identically to v5.6.x. The relaxed denominator only widens behavior for LOST/STALE+away tracker entries.
- **I4 (sleep-state safety):** During `HouseState.SLEEP` / `HouseState.HOME_NIGHT`, the LOST-derived AWAY veto is suppressed when `CONF_LOST_AWAY_SLEEP_EXEMPT == True` regardless of grace elapsed.

**Workstream B (revised 2026-06-28 — clamp applies to the combined relax/tighten arithmetic, not bucket cells):**

- **I5 (clamp-everywhere — combined arithmetic):** No DPM-emitted `PresetOverride.cool_high` for any zone is ever outside the per-zone `[clamp_low, clamp_high]` interval, where the bounds come from the **live preset config** (PresetManager seasonal baseline + the optional NEW per-zone `CONF_ZONE_DPM_COOL_HIGH_MIN_F` / `..._MAX_F` knobs if configured). The clamp applies to the COMBINED `effective_home_high = seasonal_cool + zone_offset + cool_high_adjustment_f + guest_offset_f + warm_bias_f`, i.e. after every signed term (relax/tighten, guest-cool, vacant-warm) has been folded in. Holds across season change, guest, vacant-warm, and operator offset. The dormant per-bucket cells (`_BUCKET_CONF_KEYS`) are NEVER consulted for the clamp — using them would silently fall back to defaults because they round-trip to a different keyspace.
- **I6 (guest is cooler — signed term, not relaxed):** When `house_state == "guest"`, every DPM-emitted `cool_high` for zones with non-zero `CONF_ZONE_GUEST_COOL_HIGH_OFFSET` is strictly ≤ the non-guest `cool_high` (after clamp). The v5.6.x backwards branch (`dynamic_preset.py:861-864`) is reversed: guest-cool is an **additional negative term added to `cool_high_adjustment_f`**, not a zeroing of `zone_offset`.
- **I7 (vacant-warm bounded — signed term):** Rarely-occupied warm bias is an additive **positive term** in the same `cool_high_adjustment_f` arithmetic chain. It contributes ONLY in the direction of `cool_high`-up and is clamped by I5. It cannot push `cool_low` past `cool_high − MIN_DEADBAND`.
- **I8 (season/master gate honored — known dormancy window):** WS-B guest-cool and vacant-warm terms are dormant when EITHER the DPM master switch (`01 · Custom Preset Ranges`) is OFF, OR the per-zone DPM enable is OFF, OR the current month ∈ {11, 12, 1, 2} (winter early-return at `dynamic_preset.py:597-599`). This is an inherited limitation of operating inside the cooling-side engine; the heat-side analog is explicitly deferred to v5.8.x. Acceptance tests must include a winter-month assertion that confirms graceful dormancy (no error, no spurious override emission).

---

## Cross-workstream sequencing

WS-B (actuation) depends on WS-A (reliable detection): a backwards-actuating guest preset on a wrong `house_state == "guest"` signal would over-cool an empty wing. **Sequence:** ship WS-A as v5.7.0; live-validate I1-I4 over one full day (must observe a real LOST-but-away→AWAY transition AND a dead-phone-home→stay-HOME hold); ship WS-B as v5.7.1 gated on that validation. Document gate explicitly in README_v5.7.0 ("WS-B held until I1 observed live").

---

## WORKSTREAM A — Detection trust fix (Tier 3)

### A1: Permit LOST-but-away trackers into the veto denominator

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py`
**Site:** `_tracking_active` helper (`:4090-4101`) — RELAX, do not delete.

**Change:** introduce a sibling predicate `_tracking_active_or_lost_away(info)` that returns True iff `(tracking_status == ACTIVE)` OR `(tracking_status in {LOST, STALE} AND (info.get("location") or "") == "away")`. Use it ONLY for the `all_tracked_persons_away` accumulator (`:4148-4155`). The H2 `phone_left_behind` filter (`:4132-4143`) is preserved verbatim — a dead-but-left-behind phone is NOT counted as away.

The existing `tracking_status` field is the authority: person_coordinator stamps `LOST+location=away+confidence=0.9` at `person_coordinator.py:338-349` (no-Bermuda fallback) and `:371-381` (no-Bermuda-sensor) when HA's `person.<name>` entity state is `not_home`. That is the trustworthy signal source.

#### Acceptance Criteria

- **Verify:** with a single configured person whose `tracking_status=LOST, location=away, confidence=0.9`, `all_tracked_persons_away` becomes True (was False in v5.6.x).
- **Verify:** with `tracking_status=LOST, location=home`, `all_tracked_persons_away` remains False (the LOST-home case stays untrusted).
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` attribute `excluded_persons` no longer lists LOST+away persons as `tracking_status=LOST`; instead they appear in a new attribute `lost_away_persons` (parallel to `away_person_ids`).
- **Test:** new `test_a1_lost_away_counts_in_denominator` and `test_a1_lost_home_still_excluded` in `quality/tests/test_presence_lost_away_veto.py`. Tests must drive `StateInferenceEngine.infer()` directly via `PresenceCoordinator._async_update_data` round-trip; tests that drive `should_veto_due_to_reliable_signals` alone are NOT acceptance evidence (per the "Critical prior finding" note).
- **Live:** observe in HA logs a `v5.7.0 A1: LOST+away admitted to veto denominator: <person>` INFO line at least once per day; sensor attribute `lost_away_persons` non-empty when a phone dies/is off.

### A2: Indoor-occupancy guard on the AWAY veto

**File:** `presence.py`
**Site:** `infer()` (`:916-924`).

**Change:** widen the AWAY-via-LOST guard so it requires NOT `any_indoor_zone_occupied` (defined by WS-A4) in addition to the existing `census_count == 0`. The original ACTIVE-tracker path (`I3`) is preserved — only the LOST-admitted denominator is gated by indoor occupancy. Concretely, distinguish two veto paths in the same conditional block:

- Path α (v4.7.14 ACTIVE-only, unchanged): `all_active_trackers_away AND unidentified_count == 0 AND census_count == 0` → AWAY.
- Path β (v5.7.0 LOST-admitted, new): `all_trusted_or_lost_away_persons_away AND unidentified_count == 0 AND census_count == 0 AND NOT any_indoor_zone_occupied AND (grace_elapsed OR no_lost_persons_present) AND NOT sleep_exempt_state` → AWAY.

`any_zone_occupied` (`:927`) for non-veto consumers is preserved.

#### Acceptance Criteria

- **Verify:** dead-phone-home + still-on-mmWave (one indoor zone OCCUPIED, census==0, unidentified==0) does NOT trigger AWAY; house stays HOME_*. This is the explicit HIGH regression the naive Fix A produced.
- **Verify:** dead-phone-away + house empty (no indoor zones occupied, census==0) → AWAY at confidence 0.95 (matches v4.7.14 confidence).
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` attribute `veto_path` ∈ {"none", "active", "lost_admitted"} so operators can observe which limb fired.
- **Test:** `test_a2_dead_phone_home_with_mmwave_stays_home`, `test_a2_dead_phone_away_empty_house_goes_away`, `test_a2_active_path_unchanged_byte_identical` (a snapshot test that ACTIVE-only inputs produce v4.7.14-identical state+confidence).
- **Live:** during a real dead-phone-home event (operator can simulate by toggling phone airplane mode while sitting on the couch), HA log shows `veto_path=none, reason=indoor_zone_occupied`.

### A3: Configurable LOST-away grace + sleep exemption

**File:** `presence.py` (logic); `const.py` (CONFs); `config_flow.py` + `options_flow.py` (UI).

**New CONFs (both NEW, justified above):**

- `CONF_LOST_AWAY_GRACE_MIN: Final = "lost_away_grace_min"` in `const.py` near line 1383 (after the existing guest CONFs). Default 60.
- `CONF_LOST_AWAY_SLEEP_EXEMPT: Final = "lost_away_sleep_exempt"` in `const.py` same region. Default True.

**Logic:** before admitting the LOST-away path β (A2), require:

- If `current_state in (HouseState.SLEEP, HouseState.HOME_NIGHT, HouseState.WAKING)` AND `CONF_LOST_AWAY_SLEEP_EXEMPT`: deny path β (stay HOME).
- Else: require that EITHER no LOST-away persons are present (i.e., all-ACTIVE case, fall through to path α naturally) OR the oldest LOST-stamp timestamp for any LOST-away person is older than `CONF_LOST_AWAY_GRACE_MIN`. The "LOST-stamp timestamp" is read from a new `_lost_since: dict[str, datetime]` snapshot on PresenceCoordinator, populated when a person's `tracking_status` transitions to LOST (reuses the existing `_person_lost_since` already maintained in `person_coordinator.py:240, 276-279` — surface it cross-coordinator via the existing `person_coordinator.data` shape; add `lost_since` field to person_data dict).

#### Acceptance Criteria

- **Verify:** with grace=60, a LOST+away tracker that flipped LOST 30 min ago does NOT trigger path β. After 61 min (and an empty house), path β fires.
- **Verify:** during SLEEP, even a 24-hour-old LOST+away tracker does NOT fire path β when sleep-exempt=True.
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` attribute `lost_away_grace_remaining_s` (per oldest LOST person; 0 once elapsed; null if no LOST present).
- **Test:** `test_a3_grace_blocks_premature_path_beta`, `test_a3_grace_elapsed_fires_path_beta`, `test_a3_sleep_exempt_overrides_grace`, `test_a3_sleep_exempt_disabled_respects_grace`.
- **Live:** operator can lower `CONF_LOST_AWAY_GRACE_MIN` to 5 in options-flow for a one-shot live exercise; observe path β fire 5 min after phone-off; restore default.

### A4: Per-zone outdoor exclusion ("Fix B")

**File:** `config_flow.py` (zone setup + zone options); `const.py` (CONF); `presence.py` (consumption); `camera_census.py` (census exclusion).

**New CONF (NEW, justified above):**

- `CONF_ZONE_IS_OUTDOOR: Final = "zone_is_outdoor"` in `const.py` near `CONF_ZONE_NAME` (`const.py` zone-region, cross-referenced from `config_flow.py:270`). Default `False`. Placed in zone config-flow on the same step as `CONF_ZONE_NAME` (`config_flow.py:802 async_step_zone_setup`, schema starting at `:884`) as a `BooleanSelector` field "Outdoor zone (excluded from indoor presence/AWAY accounting)". Mirror in zone options flow.

**Logic — presence.py:** alongside existing `any_zone_occupied` aggregation (`:4178-4181`), build:

```
any_indoor_zone_occupied = any(
    t.mode == ZonePresenceMode.OCCUPIED
    for zone_id, t in self._zone_trackers.items()
    if not self._zone_is_outdoor(zone_id)
)
```

The `_zone_is_outdoor(zone_id)` helper reads the zone's config-entry `data[CONF_ZONE_IS_OUTDOOR]` via the existing zone-entry lookup pattern used elsewhere in PresenceCoordinator. `any_zone_occupied` is preserved unchanged (for HVAC, fan-noise, and other consumers that intentionally see "anyone anywhere"). `infer()` AWAY-veto path β (A2) consumes `any_indoor_zone_occupied`.

**Logic — camera_census.py:** when computing census contribution per camera, skip cameras whose primary zone is `is_outdoor=True`. Cite the camera→zone mapping site during build (operator-known: lives in camera_census.py). This prevents an outdoor doorbell-camera face-ID from blocking the empty-house AWAY veto.

#### Acceptance Criteria

- **Verify:** a zone marked `is_outdoor=True` with `mode=OCCUPIED` does NOT contribute to `any_indoor_zone_occupied`. It still contributes to `any_zone_occupied`.
- **Verify:** with all indoor zones empty + one outdoor zone occupied + all-away trackers + census==0, path β (A2) FIRES → AWAY (was inert in the naive Fix A).
- **Sensor:** `sensor.ura_presence_coordinator_presence_house_state` attribute `outdoor_zones` (list of zone_ids currently flagged) so operators can visually verify the classification took effect.
- **Test:** `test_a4_outdoor_zone_excluded_from_indoor_aggregation`, `test_a4_outdoor_zone_still_in_any_zone_occupied`, `test_a4_outdoor_camera_excluded_from_census`. Each test must construct two zones (one indoor, one outdoor) and exercise the parity.
- **Live:** operator marks the "Outside" zone (or equivalent doorbell-camera zone) `is_outdoor=True` in options-flow; restart; verify attribute `outdoor_zones=['outside']` and that a doorbell face-ID while everyone is away does NOT block AWAY.

### Tier 3 review framings (WS-A only)

Per CLAUDE.md Tier 3 protocol — four parallel framing-disjoint reviews:

- **A — local correctness:** the `_tracking_active_or_lost_away` predicate, the grace-elapsed arithmetic, the `any_indoor_zone_occupied` aggregator, the `_zone_is_outdoor` lookup. Per-site arithmetic.
- **B — integration / state-machine integrity:** path α byte-identical for ACTIVE-only inputs; v4.7.14 ghost override unchanged; `_guest_gate_armed` path unchanged; HouseStateMachine transition validity (path β can only fire from non-AWAY states); restart resilience for `_lost_since` snapshot (must survive a HA restart without re-arming an instant veto — reuse RestoreEntity pattern or recompute conservatively).
- **C — test authority via real per-site source mutation:** reviewer edits production source to bypass A1, A2, A3, A4 one at a time, runs the suite, confirms a SPECIFIC test fails per site, restores. A site whose bypass leaves the suite green is unacceptable and demands a new mutation-anchored test.
- **D — adversarial completeness / diff-blind:** state I1-I4 in falsifiable form; re-enumerate the entire AWAY-veto invariant surface INCLUDING pre-existing code (Bug Class #53 — v5.5.3 D-HIGH-1 precedent). Search for any other site that can write `HouseState.AWAY` (`infer()` first conditional at `:899-903` is "nobody home" — verify it is not weakened by A4's indoor-vs-any split; the ARRIVING path at `:932-935` reads `current_state == HouseState.AWAY` — verify path β confidence 0.95 still drives a clean re-entry). Every flagged leak must come with a concrete legal-config repro (CONF values + state snapshot).

**Operator pre-deploy checkpoint:** after the four reviews close and orchestrator independent verification (re-grep every site that writes HouseState.AWAY and re-run source mutation on path β's gating condition), surface the I1-I4 proof to the operator before invoking deploy.sh.

---

## WORKSTREAM B — HVAC actuation (Tier 2-DB)

**Revised 2026-06-28 (deep re-audit, operator-confirmed).** WS-B no longer touches the dormant per-bucket cells. The working substrate is the v4.7.17.2 DPM rolling-median relax/tighten engine (`_compute_cool_high_adjustment` → `cool_high_adjustment_f` → `effective_home_high`). WS-B2/B4 add additional signed terms (guest-cool, vacant-warm) into that same arithmetic; WS-B1/B3 add a clamp on the combined result.

**Inherited limitations (carry into README + acceptance):** the entire WS-B path is COOLING-SIDE and WINTER-GATED — DPM returns `[], "winter_season"` for months 11/12/1/2 (`dynamic_preset.py:597-599`) — and gated by the `01 · Custom Preset Ranges` master (`energy.py:3329`) plus per-zone DPM enable (`dynamic_preset.py:580-582`). WS-B guest-cool and vacant-warm are therefore dormant in winter / when the master is OFF. Heat-side symmetric analog is deferred to v5.8.x.

### B1: Establish per-zone clamp bounds from live preset config (NOT from dormant bucket cells)

**File:** `dynamic_preset.py` (read site); `energy_const.py` + `config_flow.py` + `options_flow.py` (optional NEW per-zone min/max knobs).
**Site:** `_build_overrides_with_reason` (`:847-924`).

**Change (REWRITTEN — supersedes the v1 "revive bucket cells" framing):** the clamp bounds (`clamp_low`, `clamp_high`) come from the **live preset config the engine already uses**, NOT from `_BUCKET_CONF_KEYS`. Two paths, in priority order:

1. **NEW per-zone live knobs (preferred when a configurable range is wanted):** read `CONF_ZONE_DPM_COOL_HIGH_MIN_F` and `CONF_ZONE_DPM_COOL_HIGH_MAX_F` from `zone_data` (the dict DPM actually reads — the Zone-Manager `zones[name]` dict sourced at `dynamic_preset.py:~524`). Defaults derive from the PresetManager seasonal "home" cool_setpoint already resolved at `:894-905` — e.g. `(home_high − 4.0, home_high + 4.0)`. **Do NOT route these new CONFs through the CM `entry.options` flat keyspace** — that is the keyspace the dormant bucket cells live in, and DPM provably does not read it for per-zone values (`docs/readmes/README_v4.7.17.2.md:59` + zero value-read hits across the codebase).
2. **PresetManager-derived defaults only (acceptable minimum):** if the build judges per-zone knobs unnecessary, B3 may clamp to PresetManager-derived bounds alone (same `(home_high − 4.0, home_high + 4.0)` shape, applied uniformly across zones). This still satisfies I5 and avoids any new CONF surface.

**Explicitly excluded:** the dormant `_BUCKET_CONF_KEYS` registry (`dynamic_preset.py:209-227`) stays untouched and stays diagnostic-only (used for bucket *labelling* via `classify_bucket()`, not for bound lookup). The no-op at `dynamic_preset.py:851-856` is preserved. The v1 plan's "wire dormant bucket cells" framing is DROPPED for the reason captured in the WS-B grep table (the cells are written to a different keyspace than the one DPM reads; lighting them up naively would silently fall back to defaults and the clamp invariant would degrade to `(60, 85)` for every zone).

**Side-effect:** B1 emits an INFO once per zone at startup naming the actual `(clamp_low, clamp_high)` it will use AND the source ("per-zone-knob" vs "preset-manager-default"). Operators can verify the bound reached the runtime via the diagnostic sensor (see acceptance).

#### Acceptance Criteria

- **Verify:** for any zone, the resulting `PresetOverride.cool_high` for any season never falls outside `[clamp_low, clamp_high]` regardless of relax/tighten, guest, vacant-warm, or operator offset.
- **Verify (substrate correctness):** the bounds are read from `zone_data` (path 1) or derived from the resolved PresetManager seasonal home value (path 2) — **never** from `_BUCKET_CONF_KEYS`. A test asserts that mutating a per-zone bucket cell (e.g. `CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_HIGH=72`) does NOT change the emitted `cool_high` (proves the bucket cells stay diagnostic-only).
- **Test:** `test_b1_clamp_bounds_from_preset_manager_default`, `test_b1_clamp_bounds_from_per_zone_knob_when_set` (path 1 only if implemented), `test_b1_bucket_cells_do_not_affect_clamp` (regression guard against accidental future re-wiring of the dormant substrate).
- **Live:** `sensor.ura_hvac_coordinator_active_preset_overrides` attribute per-zone shows `clamp_low`/`clamp_high` matching the PresetManager seasonal default (or the per-zone knob if configured) — NEVER the dormant bucket cell value.

### B2: Invert the guest branch — fold a signed guest-cool term into the relax/tighten arithmetic

**File:** `dynamic_preset.py`
**Site:** `_build_overrides_with_reason` (`:860-864` for the legacy backwards branch; `:919-923` for the arithmetic chain).

**New CONF (NEW, justified above):** `CONF_ZONE_GUEST_COOL_HIGH_OFFSET: Final = "zone_guest_cool_high_offset"` in `energy_const.py` near `:389`. Type float, default `-1.0` (°F). Sign convention: negative = cooler. Read from `zone_data` (Zone-Manager dict), not CM options flat.

**Change:** reverse the backwards branch at `dynamic_preset.py:861-864` (which today zeroes `zone_offset` under guest — that RELAXES, the opposite of what guest mode should do). Replace with a signed guest term folded into the SAME `cool_high_adjustment_f` arithmetic the v4.7.17.2 relax/tighten engine already produces:

```
guest_offset_f = 0.0
if house_state == "guest":
    guest_offset_f = float(zone_data.get(CONF_ZONE_GUEST_COOL_HIGH_OFFSET, -1.0))
# cool_high_adjustment_f was already computed at evaluate_with_reason time
# from _compute_cool_high_adjustment(relative_delta, relax_f, tighten_f).
# Fold guest_offset_f in BEFORE the final effective_home_high assignment.
effective_home_high = float(home_high) + zone_offset + cool_high_adjustment_f + guest_offset_f
# (B3 then clamps this to [clamp_low, clamp_high].)
```

The legacy `CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST` flag is preserved as a backwards-compat opt-in: if `True` (default), additionally zero `zone_offset` under guest (preserves any operator who actually wanted the v5.6.x reset semantics). Document the flag's new role in its config-flow help text.

**Inherited limitation (document in help text):** guest-cool is dormant in winter (`dynamic_preset.py:597-599` returns early) and when the DPM master is OFF (`energy.py:3329`). Acceptance includes a winter assertion (see below).

#### Acceptance Criteria

- **Verify:** with `guest_offset=-1.0` and a non-winter month, transitioning `house_state` HOME_DAY → GUEST drops the emitted `cool_high` by 1°F (post-clamp).
- **Verify:** I6 holds — guest `cool_high` ≤ non-guest `cool_high` for any non-zero offset.
- **Verify (season-gated):** with the system clock set to a winter month (e.g. January), `house_state=guest` produces NO override emission for the zone (DPM returns `[], "winter_season"` early). No error, no silent partial-apply.
- **Test:** `test_b2_guest_applies_negative_offset_in_summer`, `test_b2_guest_dormant_in_winter`, `test_b2_clamp_floors_guest_offset` (if `clamp_low + MIN_DEADBAND > home_high + offset`, override is clamped not silently dropped), `test_b2_legacy_reset_flag_preserved`.
- **Live:** force `house_state=guest` (via the existing `_guest_gate_armed` test path or operator-visible button) during a non-winter month; observe `sensor.ura_hvac_coordinator_active_preset_overrides` cool_high drop within one DPM tick.

### B3: Clamp the COMBINED relax/tighten result to per-zone bounds

**File:** `dynamic_preset.py`
**Site:** `:923` (the unclamped `effective_home_high = ...`).

**Change:** after computing the combined arithmetic `effective_home_high = home_high + zone_offset + cool_high_adjustment_f + guest_offset_f + warm_bias_f` (i.e. all signed terms folded), clamp to the WS-B1 bounds `[clamp_low, clamp_high]`. Then re-assert the OverrideEngine `MIN_DEADBAND` invariant (`preset_overrides.py:186-196`) and clamp `effective_home_low` upward if needed. The clamp must compose cleanly with the existing v4.7.18 relax-ceiling gate (`dynamic_preset.py:128, :694-710`) — that gate suppresses positive `cool_high_adjustment_f` on objectively hot days and runs BEFORE the arithmetic in this site; B3's clamp is the final-stage guardrail. Emit DEBUG only on clamp (avoid log spam).

#### Acceptance Criteria

- **Verify:** with `clamp_high=77`, `home_high=76`, `cool_high_adjustment_f=+3`, the emitted `cool_high` is 77 (not 79).
- **Verify:** I5 holds across (season × offset × guest × vacant-warm × relax-ceiling-gate) — write a parameterized test enumerating the extremes. The clamp must be the last term applied.
- **Verify:** the v4.7.18 relax-ceiling gate still fires independently — clamping does not mask the gate's INFO log line.
- **Test:** `test_b3_clamp_high_caps_combined_arithmetic`, `test_b3_clamp_low_floors_negative_drift`, `test_b3_deadband_preserved_after_clamp`, `test_b3_compose_with_relax_ceiling_gate`.
- **Live:** during a hot-bucket DPM cycle (verify via existing bucket DEBUG), the emitted `cool_high` never exceeds `clamp_high`.

### B4: Per-zone rarely-occupied warm bias (signed term in same arithmetic chain)

**File:** `dynamic_preset.py` (logic + aggregation helper); `energy_const.py` + `config_flow.py` + `options_flow.py` (CONFs + UI).

**New CONFs:**

- `CONF_ZONE_RARELY_OCCUPIED_BIAS_F: Final = "zone_rarely_occupied_bias_f"` — float, default 0.0 (disabled). Operator sets +1.0 to +2.0 for wings.
- `CONF_ZONE_RARELY_OCCUPIED_HOURS_PER_DAY: Final = "zone_rarely_occupied_hours_per_day"` — float, default 4.0. A zone with `avg_occupied_hours_last_7d < threshold` is "rarely occupied".

Both NEW (zero hits per the grep table). Read from `zone_data`, not CM options flat. Place in `energy_const.py` near the other zone CONFs and in zone options-flow alongside the existing per-zone DPM fields.

**Logic — new helper:** `_zone_avg_occupied_hours_last_7d(zone_id) -> float | None` reads the existing 5-min occupancy snapshot DB (per VISION_v7.md). Cache per-zone with a 1-hour TTL (DPM evaluates frequently; the metric drifts slowly). On DB error / cold-cache, return None and skip the bias (do NOT default to "rarely occupied" — that would warm an unmeasured zone).

**Logic — apply in `_build_overrides_with_reason` (folded into the same arithmetic chain as B2):**

```
warm_bias_f = 0.0
avg_hours = self._zone_avg_occupied_hours_last_7d(zone_id)
threshold = float(zone_data.get(CONF_ZONE_RARELY_OCCUPIED_HOURS_PER_DAY, 4.0))
bias = float(zone_data.get(CONF_ZONE_RARELY_OCCUPIED_BIAS_F, 0.0))
if avg_hours is not None and bias > 0.0 and avg_hours < threshold:
    warm_bias_f = bias
# Final arithmetic — both signed terms folded BEFORE B3 clamp:
effective_home_high = float(home_high) + zone_offset + cool_high_adjustment_f + guest_offset_f + warm_bias_f
```

Suppress under `house_state == "guest"` (a guest visiting a normally-rarely-used wing should not get warmed): `if house_state == "guest": warm_bias_f = 0.0`. Always pass through WS-B3 clamp last.

#### Acceptance Criteria

- **Verify:** for a zone with `avg_hours=2.0, threshold=4.0, bias=+1.5` in a non-winter month, the emitted `cool_high` is the baseline + 1.5 (then clamped per B3).
- **Verify:** under `house_state=guest`, warm bias is zeroed (and B2's guest offset still applies → cooler).
- **Verify:** I7 holds — warm bias cannot push `cool_low > cool_high − MIN_DEADBAND`.
- **Verify (season-gated):** in winter, the helper is not evaluated (DPM early-returns); no DB read, no bias.
- **Sensor:** `sensor.ura_hvac_coordinator_active_preset_overrides` per-zone attribute `rarely_occupied_active: bool` and `avg_hours_last_7d: float`.
- **Test:** `test_b4_warm_bias_applied_when_below_threshold`, `test_b4_warm_bias_skipped_at_threshold_boundary`, `test_b4_guest_zeros_warm_bias`, `test_b4_no_data_skips_bias_safely`, `test_b4_dormant_in_winter`.
- **Live:** operator sets the master-bedroom wing's bias to +1.5 and threshold to 4.0; over a week of low occupancy during a non-winter month, observe `rarely_occupied_active=True` and `cool_high` 1.5°F higher than a similarly-configured frequently-occupied zone.

### B5: Wire the guest actuation path via DPM relax/tighten fold (NOT a revived override producer)

**File:** `dynamic_preset.py` (chosen path); explicitly NOT `preset_overrides.py` (no resurrection of `build_guest_mode_overrides`).

**Rationale for the DPM-fold variant:**

- DPM already evaluates every zone every cycle (`_build_overrides_with_reason` is called per zone in EC's DPM tick).
- DPM already publishes via `ec._dynamic_preset_overrides` (`energy.py:515, 3477-3478`) which the HVAC sink reads (`hvac.py:1495`) and which already round-trips to the diagnostic sensor.
- WS-B2 already added the guest-offset arithmetic in the same chain that WS-B3 clamps.
- A separate producer would require: new signal subscription, new emit site, new test surface, and a parallel `active_when` predicate path. Strictly worse for review surface area and runtime determinism.

**Concrete change:** WS-B5 is the integration assertion that WS-B2's guest offset (a) reaches the HVAC sink without modification, (b) the dead predicate `house_state == 'guest'` at `preset_overrides.py:147` is now reachable through the DPM record (preserve the predicate but verify a test triggers it), and (c) the deleted-comment block at `preset_overrides.py:241-249` is updated to point at the DPM-fold as the chosen path so future readers do not re-add `build_guest_mode_overrides`.

#### Acceptance Criteria

- **Verify:** end-to-end with `house_state=guest` in a non-winter month: DPM emits per-zone override with cooler `cool_high` → record present in `ec._dynamic_preset_overrides` → HVAC sink reads it → `climate.set_temperature` called with the cooler high → thermostat reflects new value.
- **Verify (season-gated):** end-to-end in winter: no DPM override emission → HVAC sink sees no record → no thermostat write. No error.
- **Test:** `test_b5_e2e_guest_cooler_reaches_thermostat_in_summer`, `test_b5_e2e_guest_no_op_in_winter` (integration-shaped: drives EC's DPM tick + HVAC sink against a `MockClimate`).
- **Live:** trigger guest mode (via existing v4.6.2.2 path) during a non-winter month; observe `sensor.ura_hvac_coordinator_active_preset_overrides` cool_high drop AND `climate.<zone>` setpoint follow within one minute.

### Tier 2-DB review framings (WS-B only)

Per CLAUDE.md Tier 2-DB:

- **A — data integrity + DB architecture preservation:** the per-zone 7-day occupancy aggregation must not regress existing analytics; cache TTL safe under restart; existing `ec._dynamic_preset_overrides` shape preserved (additive attributes only).
- **B — migration correctness + signal chain integrity:** every emission site of `PresetOverride` (DPM is the sole emitter post-B5; verify) produces a clamp-bounded record built from the combined relax/tighten arithmetic; HVAC sink (`hvac.py:1462+`) consumes byte-identical shape; the legacy `CONF_ZONE_DYNAMIC_PRESET_RESET_OFFSET_GUEST` flag's new semantics are documented and round-trip through options-flow + RestoreEntity. **Verify the dormant `_BUCKET_CONF_KEYS` registry remains untouched and that no read path in WS-B accidentally routes through it** (regression guard against the v1 framing).
- **C — new surfaces + test fixture authority:** new CONFs (`CONF_ZONE_GUEST_COOL_HIGH_OFFSET`, `CONF_ZONE_RARELY_OCCUPIED_BIAS_F`, `CONF_ZONE_RARELY_OCCUPIED_HOURS_PER_DAY`, and the optional `CONF_ZONE_DPM_COOL_HIGH_{MIN,MAX}_F`) round-trip options-flow → Zone-Manager `zones[name]` dict → DPM `zone_data` read → HVAC sink → thermostat. Test fixtures extract schema from production source (no hand-copied dicts).

---

## Files to change (summary)

**Workstream A:**

- `custom_components/universal_room_automation/const.py` — add `CONF_LOST_AWAY_GRACE_MIN`, `CONF_LOST_AWAY_SLEEP_EXEMPT`, `CONF_ZONE_IS_OUTDOOR`.
- `custom_components/universal_room_automation/config_flow.py` — add `CONF_ZONE_IS_OUTDOOR` to zone setup schema (`:884` region) + options; add `CONF_LOST_AWAY_GRACE_MIN`, `CONF_LOST_AWAY_SLEEP_EXEMPT` to the house-level / presence section (near existing guest CONFs at `:3009-3110`).
- `custom_components/universal_room_automation/options_flow.py` — mirror.
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — `infer()` path α/β split (`:916-924`); new `_tracking_active_or_lost_away` predicate (`:4090` region); `any_indoor_zone_occupied` aggregator (`:4178` region); `_zone_is_outdoor` helper; `_lost_since` snapshot.
- `custom_components/universal_room_automation/person_coordinator.py` — add `lost_since` field to person_data dict at the LOST stamp sites (`:153, :333, :345, :377`) reusing the existing `_person_lost_since` map (`:240, :276-279`).
- `custom_components/universal_room_automation/camera_census.py` — outdoor-zone camera exclusion (cite the camera→zone mapping site during build).
- `custom_components/universal_room_automation/sensor.py` (PresenceHouseStateSensor) — expose new attributes `lost_away_persons`, `veto_path`, `lost_away_grace_remaining_s`, `outdoor_zones`.
- `quality/tests/test_presence_lost_away_veto.py` (NEW).
- `quality/tests/test_presence_outdoor_zones.py` (NEW).

**Workstream B (revised 2026-06-28):**

- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — add `CONF_ZONE_GUEST_COOL_HIGH_OFFSET`, `CONF_ZONE_RARELY_OCCUPIED_BIAS_F`, `CONF_ZONE_RARELY_OCCUPIED_HOURS_PER_DAY`; OPTIONALLY add `CONF_ZONE_DPM_COOL_HIGH_MIN_F` / `CONF_ZONE_DPM_COOL_HIGH_MAX_F` if B1 path 1 is chosen.
- `custom_components/universal_room_automation/config_flow.py` — extend the per-zone options surface (sourced into Zone-Manager `zones[name]` dict — NOT the CM options flat keyspace) with the new fields. **Explicitly does NOT touch the dormant bucket-cell round-trip at `:7053-7130` — those cells stay diagnostic-only.**
- `custom_components/universal_room_automation/options_flow.py` — mirror.
- `custom_components/universal_room_automation/domain_coordinators/dynamic_preset.py` — `_build_overrides_with_reason` (`:847-948`): establish `clamp_low`/`clamp_high` from live preset config (B1); invert guest branch via signed `guest_offset_f` (B2); clamp combined arithmetic (B3); fold `warm_bias_f` (B4); add `_zone_avg_occupied_hours_last_7d` helper. The dormant no-op at `:851-856` is preserved unchanged.
- `custom_components/universal_room_automation/domain_coordinators/preset_overrides.py` — update the deleted-block comment (`:241-249`) to point at DPM-fold.
- `custom_components/universal_room_automation/sensor.py` (ActivePresetOverridesSensor) — add per-zone attributes `clamp_low`, `clamp_high`, `clamp_source`, `rarely_occupied_active`, `avg_hours_last_7d`.
- `quality/tests/test_dynamic_preset_clamps_and_guest.py` (NEW).
- `quality/tests/test_dynamic_preset_rarely_occupied.py` (NEW).

---

## Plan completion tracking

Items in this plan that may be deferred (track explicitly post-build; do NOT drop silently):

| Item | Deferral condition | Track in |
|---|---|---|
| Camera-census outdoor exclusion (WS-A4 second half) | If the camera→zone mapping site is more invasive than scoped, ship the presence-side exclusion alone in v5.7.0 and follow up in v5.7.0.1 | README_v5.7.0 deferral table |
| `_lost_since` RestoreEntity persistence (WS-A3) | If conservative recompute proves sufficient under restart, skip restore-state machinery | README_v5.7.0 |
| Per-zone `CONF_ZONE_DPM_COOL_HIGH_{MIN,MAX}_F` knobs (WS-B1 path 1) | If PresetManager-derived defaults are judged sufficient, ship path 2 in v5.7.1 and defer knobs to v5.7.1.1 | README_v5.7.1 |
| WS-B integration test against real MockClimate (B5) | If MockClimate harness needs significant scaffolding, ship a coordinator-level test in v5.7.1 and the climate-sink test in v5.7.1.1 | README_v5.7.1 |
| Heat-side analog of WS-B (`heat_low` clamp + guest-warm) | Symmetric to cool-side; out of scope for the cooling-side engine | v5.8.x backlog |
| Dashboard surfacing of new sensor attributes | Lovelace-side; not blocking | hygiene-bucket backlog |

Items NOT in scope (explicit non-deliverables):

- Person-coordinator overhaul (BLE/Bermuda accuracy improvements) — outside this cycle.
- HVAC heat-side analog of WS-B (`heat_low` clamp + guest-warm) — symmetric design, deferred to v5.8.x once cool-side is live-validated.
- Outdoor-zone first-class concept (separate platform / dedicated sensors) — this cycle adds a flag, not a new entity class.
- Revival of the dormant `_BUCKET_CONF_KEYS` per-bucket cell surface — kept diagnostic-only by design.

---

## Live-validation acceptance (write back to README_v5.7.0 post-deploy)

Per the CLAUDE.md "Record Live Validation Back Into the README" mandate, replace the prospective Live bullets with a `Validated <date>` table after restart. Required rows (one per invariant):

| Invariant | How to observe live | Status |
|---|---|---|
| I1 no-force-AWAY-while-home | Operator simulates dead-phone-home; `sensor.ura_presence_coordinator_presence_house_state` stays HOME; `veto_path` attribute = "none" with reason indoor_zone_occupied | _(fill after restart)_ |
| I2 guest-detection preserved | Existing v4.6.2.2 guest-entry exercise still arms GUEST | _(fill after restart)_ |
| I3 ACTIVE path unchanged | Snapshot diff vs v5.6.x for ACTIVE-only inputs (in-suite) | _(fill after restart — note in-suite if not live-reachable)_ |
| I4 sleep-state safety | Across one overnight (SLEEP), no path β fires regardless of LOST-stamp age | _(fill after restart)_ |
| WS-B held until I1 observed | README_v5.7.0 explicitly states WS-B deferred to v5.7.1 | _(fill on ship)_ |

### Shipwatch acceptance block — drop into README_v5.7.0 at deploy (new `home_assistant.*` schema)

**Notes (must accompany the YAML in README_v5.7.0):**

- **Deep behavioral correctness of WS-A (dead-phone-home → stays-HOME, dead-phone-away + indoor-empty + grace-elapsed → AWAY at confidence 0.95, sleep exemption) is IN-SUITE-AUTHORITATIVE.** Shipwatch cannot stage the multi-actor scenarios required to falsify I1-I4 against a running house. The pytest suite is the canonical evidence; Shipwatch is a deployment liveness signal only.
- **The Shipwatch `home_assistant` adapter is currently a stub (backlogged 2026-06-28).** Until the adapter ships, the three hypotheses below will resolve `pending` rather than `confirmed`/`violated`. That is the expected status; do NOT interpret `pending` as a failed acceptance.
- **Verify entity IDs and attribute names against the live HA instance before trusting a `confirmed`.** A `confirmed` against a stale or mistyped entity is a false positive. The names below are taken from this plan's WS-A sensor exposure spec (`sensor.ura_presence_coordinator_presence_house_state` + new `veto_path` attribute) and the canonical update entity; cross-check post-deploy via ha-mcp or SSH before relying on them.

```yaml
version: 5.7.0
hypotheses:
  - id: H1
    name: ura_v570_deployed
    description: URA v5.7.0 is the running HACS-installed version.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.7.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: no_presence_error_storm
    description: No recurring URA error after the WS-A detection-trust change.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
  - id: H3
    name: veto_path_surface_live
    description: WS-A veto_path diagnostic is published on the house-state sensor.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_presence_coordinator_presence_house_state, attribute: veto_path }
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
```
