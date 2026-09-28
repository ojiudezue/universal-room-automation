# PLANNING — Enable Custom Preset Ranges (D9 / `guest_mode_actuation`, HVAC arc step 5)

**Status:** PLAN (rev 0, 2026-09-27). Not built. Needs one adversarial plan review, then build.
**Operator ruling (2026-09-27):** "yes", the operator wants the feature.
**Arc position:** `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §11 row 5, "Enable Custom Preset Ranges (D9) once W1-B removed its blockers".
**Cards resolved:** `HVAC-S10-DPM-VS-S1-1`, `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`. Disposition of `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` in §9.
**Version:** next free `5.103.x` PATCH. It turns on an existing feature and is not a new capability.

---

## Read-first attestation

- I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full, all 470 lines, including §9e. W1-B shipped v5.103.18 and replaced the v3.8.0 S1 manual guard with four gates: (a/b) person-protected hold, (c) arrester grace/compromise, (d) arrester disabled, (e) live borrow row or the arrester's in-flight nudge/compromise timers. It also made borrow returns presets-only.
- This plan re-asserts nothing listed in §10 (C1–C25). In particular it does not rely on the retired guard (C25). It does not treat `hold_activity` as a universal oracle (C20/C22/C23). It does not use 42–79 s as Carrier's schedule (C16), and it does not claim `set_activity_setpoint` is a local patch (C15).
- I read both blocker cards in full (`kanban.data.yaml:2103-2128`, `:2391-2413`), including the constraint the operator added on 2026-09-27: *no new EXCURSION_KIND and no logic inside `begin_excursion` without a ruling; prefer S1-side reads.* This plan touches neither `begin_excursion`, `return_excursion`, nor the excursion kinds.

---

## STEP 0 — what the feature is today, and the real knob

### Q1. What does the feature do today, and why was it dormant?

**The code path.** The only actuator is `HVACCoordinator._async_apply_preset_overrides` (site id **S10**), `hvac.py:3373-3638`. It is called at the end of `_apply_house_state_presets` (`hvac.py:3317-3320`), in the same tick and right after S1. It returns at once when `_guest_mode_actuation_enabled` is False (`hvac.py:3390`).

When the switch is ON, S10 does the following for every zone on every tick:
1. It takes the **house-state** preset (`get_preset_for_house_state`, `hvac.py:3416`), not the zone's own preset. The exception is established-empty zones, where D9 compose-away swaps in `away` (`hvac.py:3518-3528`).
2. It builds a baseline from URA's editable seasonal table (`get_seasonal_setpoints`, `hvac_preset.py:126-180`). The table comes from CM options `hvac_baseline_<season>_<preset>_cool/_heat`; the live install has all 24 set.
3. **It sets the low side to `cool − 7`** and discards the configured heat value (`hvac.py:3537-3542`: `baseline_cool, _baseline_heat = baseline`; `baseline_low = baseline_cool - 7.0`).
4. It layers on any OverrideEngine records from EC `_dynamic_preset_overrides` (`energy.py:7126-7319`). Only Dynamic Preset produces records today, and only for `home` and `sleep` (`dynamic_preset.py:926-959`). Nothing produces guest overrides: `build_guest_mode_overrides` was deleted as dead code (`preset_overrides.py:241-249`).
5. It writes a **raw `climate.set_temperature`** through `emit_set_temperature` (`hvac.py:3598-3609`) whenever the pair differs from `_last_emitted_range`. On compose-away zones it writes on **every tick** (F2 bypass, `hvac.py:3575-3578`).

**What that does to a Carrier zone.** `set_temperature` rewrites the MANUAL activity and sets `hold=MANUAL` (`ha_carrier/climate.py:467-537`). With `infinite_holds: True`, that hold never expires. So every S10 write turns the zone into an anonymous `manual` hold.
- **Before v5.103.18:** the old S1 guard refused to write over `manual`. The feature "worked" by leaving the zone in a permanent manual hold, and S1 then lost control of that zone. This is the §9.1 strand class, created on purpose.
- **Under W1-B (live now):** no gate is armed for an S10 manual (no borrow row, no person hold, no arrester window). S1 reclaims it on the next tick with resume-then-pin. Two outcomes follow:
  - **Occupied zones:** S1 reclaims once. After that `_last_emitted_range` equals the pair, so S10 never writes again, and the zone runs its own Bryant profile. The feature silently does nothing.
  - **Empty zones:** the F2 bypass fires every tick, so each tick is S10 raw write (2 cloud calls), then S1 resume + pin (2+ calls), then S10 again. That is about 48 Carrier calls per hour per empty zone, indefinitely. It would also trip `s1_reclaim_rate_high` (`hvac.py:1653-1695`) on every such zone.
- **Latent comfort defect (Bug Class #63, coincidental equality).** `cool − 7` equals the configured heat only for home presets (for example 77/70). With the live winter away baseline of 80/65, S10 would write a **heat setpoint of 73 °F** to an empty zone in winter, not 65. Legal repro: CM option `hvac_baseline_winter_away_cool=80`, `_heat=65`, house `away`, January, switch ON → `target_temp_low=73`.

**Why it was dormant.** The v5.103.7 README (`README_v5.103.7.md:31-39, :63, :72-73`) shipped D9/F2/F4 on the assumption that `switch.ura_hvac_coordinator_guest_mode_actuation` stays OFF, and made the F2 storm a hard blocker on ever enabling it. The switch has been `off` in every recorded state since 09-18, and is `off` in `core.restore_state` today (last_changed at boot 2026-09-28T01:54Z). W1-B then added the S1-vs-S10 fight (A-L5 in `PLANNING_hvac_w1b_thermostat_definition.md:408`, card §5.P6). Who first turned it off, and why, is not in any record I found. **UNVERIFIED**; only the operator knows. Default was ON in v4.7.1 (`switch.py:2021`).

### Q2. Is `switch.ura_hvac_coordinator_guest_mode_actuation` the right switch? What is the real knob, and what does its label say?

**Yes, that is the actuation knob.** I checked it against the live entity registry (`/config/.storage/core.entity_registry`):

| Entity id (live) | unique_id | Label shown | Backing field | Live state |
|---|---|---|---|---|
| `switch.ura_hvac_coordinator_guest_mode_actuation` | `universal_room_automation_hvac_coordinator_guest_mode_actuation_enabled` | **"01 · Custom Preset Ranges"** (`switch.py:1998`) | `HVACCoordinator._guest_mode_actuation_enabled` (`hvac.py:540`) | off |
| `switch.ura_energy_coordinator_dynamic_preset_overrides` | `universal_room_automation_energy_dynamic_preset_enabled` | **"02 · Dynamic Preset Auto-Adjust"** (`switch.py:1715`) | `EnergyCoordinator._dynamic_preset_enabled` (`energy.py:791`) | off |

Corrections to earlier docs:
- The class docstring (`switch.py:1983`) and README_v4.7.1/4.7.2 give the entity as `..._guest_mode_actuation_enabled`. The real entity_id has no `_enabled` suffix.
- The entity_id says "guest mode", but nothing in the guest path produces overrides. The label "Custom Preset Ranges" matches what the switch actually gates: pushing URA's ranges to the thermostats.

**There are two knobs, and switch 01 alone gives no weather adjustment.**
- Switch 01 is the only **actuation** gate.
- Switch 02 is the **producer** gate for the only live override source (Dynamic Preset).
- Per-zone opt-in `zone_dynamic_preset_enabled` is already `true` on all four zone configs (ZM entry, `core.config_entries:374`).
- The CM option `dynamic_preset_enabled` is `true` (`:375`), but the switch's RestoreEntity `off` wins at boot (`switch.py:1869-1880`). So the options form and the switch disagree today. This is noted in §12, not fixed here.

**What the label tells the operator today.** The entity has no helper text; the label is all they see. The baseline editor description (`strings.json` / `en.json:1244`) says *"These are the baseline setpoints that every zone uses unless Dynamic Preset is configured per-zone."* **That is false while switch 01 is OFF**: every zone uses its own Bryant profile. The DPM description (`en.json:1231`) says *"When off, all zones fall back to the seasonal baseline setpoints"*, which is also false while 01 is OFF. Both strings are fixed in D5.

---

## 1. Config-first check (CLAUDE.md step 1b)

| Candidate setting | Solves it? | Evidence |
|---|---|---|
| Flip switch 01 ON with no code change | **No, harmful.** Occupied zones: the feature does nothing after one S1 reclaim. Empty zones: ~48 Carrier calls per hour per zone. Winter away: heat setpoint 73. | STEP 0 Q1 |
| Flip switch 02 ON only | No. It only fills `_dynamic_preset_overrides`; nothing acts on them while 01 is OFF. | `hvac.py:3390` |
| **Type URA's ranges into each Bryant preset in the Carrier app** (3 zones × 4 presets) | **Partly.** It gives the static custom ranges with no code, but the operator must retype them at each season change (URA has 3 seasons), and it cannot deliver the weather adjustment (±1 °F on Home/Sleep cooling, per-zone offset). | `dynamic_preset.py:109-132`; live `dpm_cool_day_relax_f=1.0`, `dpm_hot_day_tighten_f=1.0` |
| `ha_carrier` option `infinite_holds` | No. It does not affect which values a preset carries. | §5 |

**Marginal-benefit decomposition** (CLAUDE.md duty, stated so the operator ruling rests on the right facts):
- The **static half** (URA-managed ranges per preset and season) can be done by hand in the Carrier app. What the code adds is automatic season changes and one editing place in URA.
- The **dynamic half** (weather nudge) is ±1 °F on Home/Sleep cooling, and it is off November through February (`dynamic_preset.py:597-599`).
- The **simplest correct code** that delivers both is small once it writes the preset profile instead of a hold (§3). The risky parts of the old design (the D9 compose-away corrector and the F2 bypass) are **deleted, not narrowed**, because W1-B's presets-only returns and the live row-1 preset retreat already do their job (§8).

**Verdict: BUILD.** The operator has ruled, and the build removes more risky machinery than it adds. D0 (§4) shows the operator exactly which preset values change when the switch is turned on.

---

## 2. Institutional context verified

### 2.1 Greps run (prior-art scan, REUSE / BUILD per piece)

| Proposed piece | Verdict | Existing symbol / justification |
|---|---|---|
| Write a preset's range **without** a hold | **REUSE upstream** `ha_carrier.set_activity_setpoint` | `ha_carrier/climate.py:91-104` registers it; `:539-596` edits the **status-named** current activity's setpoints via `set_config_activity` and does **not** touch hold state (`:591`). Upstream PR #427 (C15). `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §3. |
| Funnel for the new verb with one `climate_write` row | **BUILD** `emit_set_activity_setpoint` in `hvac_setpoint.py` | No existing funnel calls a non-`climate` domain (grep `hvac_setpoint.py` for `async_call(`: only `"climate"`). W1-A planned for this: `PLANNING_hvac_w1a_thermostat_write_governance.md:363`, *"if Stage B adopts it, that funnel gets a row shape then."* It reuses `_snapshot_climate_state` (`:127-160`), `_schedule_climate_write_row` (`:163+`), `_log_deferred_write` (`:258`), and `apply_setpoint_guards` (`:96-112`). **It does not modify any existing `emit_*` funnel.** |
| Per-brand dispatch (Carrier supports it; others do not) | **REUSE + extend** `hvac_strategy.py` | `strategy_for` (`:254`), `WriteResult`/`WriteStatus` (`:56-75`), `observe` (`:119-139`), `LAST_SENT_TOLERANCE_F` (`:53`). Add one method, `set_preset_range`, on `GenericStrategy` (always `FAILED("preset_range_unsupported")`, zero calls) and on `CarrierStrategy`. |
| "Live borrow on this zone" read | **REUSE** gate (e) logic from `PresetManager.manual_guard_verdict` (`hvac_preset.py:293-317`) | Pull it out into a pure `borrow_live(zone_id) -> str \| None` (returns the source), which `manual_guard_verdict` then calls. Behaviour is identical. Calling `manual_guard_verdict` directly from S10 is **rejected**: it writes `_last_manual_verdict[zone_id]` (`:333`), a cache S1's deferral ledger reads. This is an S1-side-style read and does not touch borrow code (card constraint). |
| Person-protected hold skip | **REUSE** `OverrideArrester._corrective_writes_suppressed` (`hvac_override.py:672`) | Already at S10 (`hvac.py:3443-3451`). Kept. |
| Comfort-delay defer | **REUSE** `_s10_gate` → `comfort_delay_active` (`hvac.py:3589-3597`; `hvac_override.py:2463`) | Kept, passed as `gate=`. |
| Same-tick S1 write skip | **REUSE** `_zones_written_this_cycle` (`hvac.py:455`, reset at cycle entry `:1879`, added `:3194`) | S10 skips zones S1 wrote this tick. S1 writes `blocking=False` (`:3163`), so the zone's activity is not settled yet. |
| AC-reset skip | **REUSE** `has_active_ac_reset` (`hvac_override.py:2183`) | |
| Egress-pause skip | **REUSE** `EgressManager.is_paused` | Already at S10 (`hvac.py:3429-3433`). |
| Range values | **REUSE** `get_seasonal_setpoints` (`hvac_preset.py:126`) + OverrideEngine (`preset_overrides.py`) + EC `_dynamic_preset_overrides` | Change: use the configured **heat** value as the low side (fixes the §Q1 `cool − 7` defect at S10). |
| Arrester must not book S10 as an override | **REUSE** existing behaviour | `_handle_climate_change` ignores setpoint changes while `preset_mode` is not `manual` (`hvac_override.py:3216-3226`, *"a preset range adjustment. Ignore."*). A `suppress(kind="temp")` stamp is kept as a guard (`:2973`). |
| Write-rate trip-wire + NM | **REUSE pattern** of `_note_s1_reclaim` (`hvac.py:1653-1695`) | NEW in-memory per-(zone, preset) record plus 2 rung-1 constants (§6). |
| Persisted pre-edit profile snapshot | **NOT BUILT** (decision §3.4) | `_zone_state_store` side-key pattern (`hvac.py:2081-2103`) exists and would be the home if ever needed. |
| AST lint on raw writes | **EXTEND** `quality/tests/test_hvac_climate_write_funnel_completeness.py` | Today it only flags the `"climate"` literal (`:120-130`). Add `"ha_carrier"`, so the new verb cannot be called outside `hvac_setpoint.py`. |
| D9 compose-away, F2 throttle bypass, S10 transient-block hold, `_dpm_composed_away_zones` | **DELETE** (§8 supersession) | `hvac.py:3452-3528`, `:3563-3578`, `:3488-3517`, `:3522-3526`. Grep: `_dpm_composed_away_zones` has no readers in code or tests. |
| `_last_emitted_range` | **KEEP** (S10 stops writing it) | Still read and written by S11 banking release (`hvac_predict.py:864-920`, `:1060+`) and S13 (`:1589-1590`). Switch 01 is OFF live, so S10 never fills the map today; S11/S13 behaviour does not change from live. |

Surfaces grepped: `const.py`, `hvac_const.py`, `energy_const.py` (constants); `config_flow.py`, `strings.json`, `translations/en.json` (fields and labels); `switch.py`, `sensor.py` (entities); `domain_coordinators/hvac*.py`, `energy.py`, `dynamic_preset.py`, `preset_overrides.py` (sites); `quality/tests/` (7 files call `_async_apply_preset_overrides`: `test_zzz_hvac_conditioning_demand.py`, `test_arrester_comfort_delay.py`, `test_v471_fixup_d2_d3_d4.py`, `test_freeze_floor.py`, `test_hvac_w1a_site_migration.py`, `test_v478_egress_window.py`, `test_hvac_live_room_hold_wire_in.py`).

### 2.2 Prior planning docs consulted
- `PLANNING_v4.7.x_guest_mode_actuation_phase1.md` (skim): OverrideEngine schema and the S10 origin.
- `PLANNING_v4.7.2_dpm_hvac_surface_plus_guest_signal.md` (grep): origin of the "01 · Custom Preset Ranges" label.
- `PLANNING_hvac_zone_conditioning_demand.md` §0b and D9 (read): D9's purpose was to stop S10 writing **house-state** setpoints over a zone S1 had narrowed. §3's "edit the zone's own preset" removes that seam by construction.
- `PLANNING_hvac_w1b_thermostat_definition.md` (grep; §5.P6, :408 A-L5, D2.4 five-site list :307-311).
- `PLANNING_hvac_w1a_thermostat_write_governance.md:363, :399`.
- `PLANNING_hvac_arc_w1_w2_integration.md` (full): contract C1 (one write path), C5 (call-rate budget), §5 decision (1). Its recommendation "no" on `set_activity_setpoint` was about **nudges**. See §3.4.
- `PLANNING_v5.7.0_guest_mode_detection_and_actuation.md:222`: DPM is cooling-side and gated off in winter.
- `HVAC_ARC_TAIL_2026_09_18.md:101-109`.

### 2.3 READMEs
`README_v5.103.7.md` (D9 dormant, rows 6/72/73), `README_v5.103.18.md:41`, `README_v4.7.1.md`, `README_v4.7.2.md`, `README_v4.7.3.md` (baseline editor).

### 2.4 Memory bodies pulled
- `feedback_label_style_guide.md`: ≤3-word entity names, plain helper text, no jargon.
- `reference_hvac_state_of_play.md`.
- `feedback_marginal_benefit_pushback.md` and `feedback_config_first_before_code.md` (from the index; applied in §1).

### 2.5 Design docs read
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (full).
- `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §2–§3, the verb table at :261-265, and open item 6 at :328.

### 2.6 Code read end-to-end for this plan
- `hvac.py`: `_async_apply_preset_overrides` 3373-3638; S1 block 2913-3210; `_run_decision_cycle` entry 1873-1880; snapshot builder 2081-2118; `_rehydrate_arrester_state` 1780-1871; `_note_s1_reclaim` 1653-1695.
- `hvac_preset.py` (all). `hvac_strategy.py` (all). `hvac_setpoint.py` 90-485. `preset_overrides.py` (all). `dynamic_preset.py` (all).
- `energy.py` 7126-7319. `switch.py` 1685-2104. `sensor.py` 10128-10260.
- `hvac_override.py` 2960-3290. `hvac_predict.py` 150-195, 855-1065.
- `ha_carrier/climate.py` 60-600 (installed copy on the Samba mount).

---

## 3. Design — the simplest correct fix

### 3.1 The core move: write the preset, never a hold

**S10 changes the zone's *named preset profile* in place with `ha_carrier.set_activity_setpoint`, only when the zone is sitting on that named preset.** It never calls `climate.set_temperature`.

This resolves `HVAC-S10-DPM-VS-S1-1` without touching borrow code or S1:
- The zone never goes to `manual`, so S1 sees `preset_mode == target` (or some other named preset) and has nothing to reclaim (`should_change_preset`, `hvac_preset.py:357-358`). S10 and S1 cannot fight: they write different fields of different objects. S1 writes *which* activity holds, and S10 writes *what that activity contains*.
- The arrester ignores the change, because the preset is not `manual` (`hvac_override.py:3220-3223`).
- Everything else follows from W1-B's presets-only returns. Nudge returns, arrester reverts (S4), banking and pre-heat returns, and schedule transitions all land on a named preset. That preset now already carries the custom range, so no corrector is needed after a borrow. This is why D9 compose-away and the F2 bypass can be deleted (§8).

Options the cards offered, and why they were rejected:
- (a) New `EXCURSION_KIND` DPM plus `begin_excursion`: forbidden by the operator constraint. It would also make custom ranges a *borrow* with a lease, which is the wrong model for a standing setting.
- (b) A per-tick `_s10_write_this_tick` flag read by gate (e): the flag clears next tick, S1 reclaims, and the range is lost. Making it sticky turns "manual at S10 values" into URA-owned provenance, which the operator dropped on 2026-09-27 (§9e). It also leaves every custom-range zone in the §9.1 strand class.
- "S10 writes presets": a preset alone cannot carry a custom range. Editing the preset's profile is the only way to express a range under a named preset, and that is exactly what this design does.

### 3.2 S10 per-zone algorithm (replaces the loop body at `hvac.py:3423-3636`)

The method-entry gate `if not self._guest_mode_actuation_enabled: return` (`:3390`) and the observation-mode gate at the call site (`:3319`) are unchanged. The EC read is unchanged except that **an absent EC or empty overrides no longer returns early**: the static half still runs. The house-state `target_preset` lookup is removed, because S10 acts on the zone's own observed preset.

For each zone, **in this order** (the first skip wins; each skip is `continue` with a debug log):
1. `egress_manager.is_paused(zone_id)` → skip. (existing)
2. `arrester._corrective_writes_suppressed(zone_id)` → skip, plus `_log_shave_skipped(..., "dpm_preset_override")`. (existing, gate a/b)
3. `zone_id in self._zones_written_this_cycle` → skip. S1 wrote this tick; its activity change has not landed yet.
4. `preset_manager.borrow_live(zone_id) is not None` → skip (gate e; see §2.1).
5. `arrester.has_active_ac_reset(zone_id)` → skip.
6. `P = zone.preset_mode`. If `P not in {"home", "sleep", "away", "vacation"}`, skip. This excludes `manual`, `wake`, `None`, and anything else. Presets without a configured baseline are left alone.
7. `baseline = preset_manager.get_seasonal_setpoints(P)`. If None, skip. `(base_cool, base_heat) = baseline`.
8. `active = engine.get_active_overrides(zone_id, P, house_state, True, all_overrides.get(zone_id, []))`; `resolved = engine.resolve_range(base_heat, base_cool, active)`.
   - **Only `resolved.cool_high` is used.** The low side is `base_heat`, the operator's configured "Heat Low" (§3.3).
   - `desired_low, desired_high = apply_setpoint_guards(base_heat, resolved.cool_high, freeze_active=self._freeze_active)`.
9. Rate check (§6.2) for `(zone_id, P, (desired_low, desired_high))`. If blocked, skip and record `rate_deferred` / `latched`.
10. `result = await strategy_for(hass, zone.climate_entity).set_preset_range(hass, zone.climate_entity, P, desired_low, desired_high, gate=_s10_gate, zone_id=zone_id, site="S10_preset_range", reason=<reason>)`.
    - `<reason>` is `preset_range_dpm` if `resolved.sources` has `cool_high`, otherwise `preset_range_baseline`.
11. Bookkeeping on `result.status`:
    - `APPLIED`: count the write in the rate record.
    - `SKIPPED_ALREADY_CORRECT`: mark the record confirmed; no call made.
    - `DEFERRED` (the gate deferred, or the precondition in §3.3 failed): nothing.
    - `FAILED`: count as an attempt, and log at warning once per (zone, P, value).

The arrester `suppress(kind="temp")` is stamped only inside the strategy immediately before the funnel call, and `unsuppress` is called on any non-APPLIED return. This is the same discipline as the existing S10 code (`:3581-3582`, `:3617-3618`).

### 3.3 `CarrierStrategy.set_preset_range` (brand rules live here, not in the funnel)

```python
async def set_preset_range(self, hass, entity_id, preset, low, high, *,
                           gate, zone_id, site, reason) -> WriteResult:
    obs = self.observe(hass, entity_id)
    # P1 both feeds name the SAME named preset -> set_activity_setpoint edits
    #    exactly `preset` (it edits the STATUS-named activity, climate.py:551/136-142).
    #    Any disagreement (e.g. §9.7 zone_1 status=home / hold=away) -> DEFERRED.
    if obs is None or obs.preset_mode != preset or obs.hold_activity != preset:
        return WriteResult(WriteStatus.DEFERRED, "activity_not_confirmed")
    # P2 heat_cool only (set_activity_setpoint uses low/high as-is only in AUTO, climate.py:559-566)
    if obs.hvac_mode != "heat_cool":
        return WriteResult(WriteStatus.DEFERRED, "not_heat_cool")
    # P3 device precision: Fahrenheit whole degrees (climate.py:218-221 PRECISION_WHOLE)
    low_r, high_r = float(round(low)), float(round(high))
    # P4 ground-truth compare: the displayed setpoints ARE the named activity's
    #    config profile (climate.py:222-240, upstream #408)
    if (obs.target_low is not None and obs.target_high is not None
            and abs(obs.target_low - low_r) <= LAST_SENT_TOLERANCE_F
            and abs(obs.target_high - high_r) <= LAST_SENT_TOLERANCE_F):
        return WriteResult(WriteStatus.SKIPPED_ALREADY_CORRECT, "profile_matches")
    # P5 funnel (gate + guards + climate_write row); blocking=True so a cloud
    #    failure surfaces as FAILED instead of vanishing
    ...  await emit_set_activity_setpoint(..., blocking=True) ...
```

- **No `await` between `observe` and the funnel's wire call.** `observe` is synchronous, the funnel's `_snapshot_climate_state` is synchronous, and the first `await` is `hass.services.async_call`. So P1 still holds when ha_carrier reads `_current_activity()`. This ordering is load-bearing and gets a comment plus a test (§10, T5).
- `GenericStrategy.set_preset_range` returns `FAILED("preset_range_unsupported")` and makes zero calls. Non-Carrier thermostats keep their own presets. S10 logs this once per entity.

**Why the low side is the configured heat value.** On a heat_cool thermostat, `target_temp_low` *is* the heat setpoint. There is no "lower cooling bound". OverrideEngine's `cool_low` field (DPM always sets it to `home_high − 7`, `dynamic_preset.py:905, :931`) has no physical meaning on this device. Ignoring it at the actuation site makes the written low exactly the operator's "Heat Low" field in the baseline editor. It also removes the winter-away `73 °F` defect. DPM remains cooling-only, which matches its own winter gate and the v5.7.0 note.

### 3.4 What happens when switch 01 is turned off, and why there is no snapshot/restore

When 01 is OFF, S10 stops, and each Bryant profile **keeps the last range URA wrote**. The plan deliberately adds **no** persisted pre-edit snapshot and no restore-on-disable pass. Reasons:
- `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §3 requires a snapshot plus restore for a **nudge** done with this verb, because a nudge is a *temporary* borrow and an interrupted return leaves the wrong value in place. A custom range is the *intended standing* value, so an interrupted write leaves the intended state. The §3 hazard does not apply. This is recorded in the doc update (D7).
- The original Bryant values are durably recorded anyway. Every S10 `climate_write` row carries `values_before` (setpoints captured just before the wire call, `hvac_setpoint.py:127-160`). If the operator ever wants the old ranges back, the ledger holds them and the Carrier app can restore them.
- A restore pass would need persistence, a restore-only mode while disabled, and "restore when the zone next visits that preset" scheduling. That is new stateful machinery for a case the operator can handle in one app edit. See the marginal-benefit rule.
- The switch's helper text (D5) says this in plain words.

The switch's `async_turn_off` no longer clears `_last_emitted_range` (`switch.py:2037-2039`). The ground-truth compare replaces "re-apply on next enable", and S11/S13 own that map now.

### 3.5 What S10 no longer does
- It no longer composes the house-state preset onto a zone. Empty-zone retreat is S1 row-1 at the preset layer (LIVE, `conditioning_retreat_ok`).
- It no longer writes raw setpoints, no longer puts a zone in `manual`, and no longer writes every tick on empty zones.
- It no longer writes `_last_emitted_range`.

---

## 4. D0 — measure before build (read-only probe, first deliverable)

`scripts/probes/hvac_preset_profile_probe.py` runs as `ssh ha "python3 -" < ...` against the recorder. It is one-shot and read-only. Its report goes into §4.1 of this doc before build dispatch.

1. **Current Bryant profile per (zone, preset).** For each of the 3 climate entities, over the last 7 days, take samples where `preset_mode == hold_activity == P` and `state == heat_cool`. Report the modal `(target_temp_low, target_temp_high)` and its sample count.
2. **The hand-built fixture.** A table (zone × preset): current Bryant profile vs. URA desired for `summer` (today) and `shoulder` (from Oct 1), using live CM options. Cells that differ are the writes expected on enable. Commit the table here. It is the acceptance fixture (CLAUDE.md "hand-build the fixture").
3. **S10 reach.** For each zone, the share of 5-minute samples where the two feeds agree on a named preset. This is the P1 precondition. If a zone agrees less than 50% of the time (zone_1 had the §9.7 split), report it. That zone gets its ranges only in the agreeing windows. This is safe (P1 defers) and gets written into the README.
4. **Restore-writers disposition (§9).** Since the v5.103.18 deploy: count episodes where a zone was HVAC-empty and established, yet sat on a comfort preset (`home`/`sleep`) for more than 15 minutes. The discriminator is expected to be ≈0, because row-1 flips it within one tick.

**Gates on D0:**
- If every cell already matches, the static half has no effect on enable, and the operator is told that before enabling. The build still ships, because DPM and season changes still act.
- If any cell differs by more than 4 °F from Bryant, list it for the operator before enabling. It may be a deliberate Bryant setting.
- If item 4 is above 0, keep `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` open with the evidence.

### 4.1 D0 results
*(to be filled before build dispatch)*

---

## 5. Deliverables

### D1 — `emit_set_activity_setpoint` funnel (`hvac_setpoint.py`)

This is a sibling of `emit_set_temperature` (`:379-484`) with the same shape.
- Signature: `(hass, entity_id, *, target_temp_low, target_temp_high, freeze_active, blocking, gate, site, zone_id, reason) -> bool`.
- Steps: gate check → `_log_deferred_write` and `False`; `apply_setpoint_guards`; `_snapshot_climate_state` (before the await); wire `hass.services.async_call("ha_carrier", "set_activity_setpoint", {"entity_id", "target_temp_low", "target_temp_high"}, blocking=blocking)`; exactly one `_schedule_climate_write_row(verb="set_activity_setpoint", ...)` per attempted call, on both the success and the raise path (INV-A); re-raise on error.
- **No brand logic, no gate logic beyond the existing `gate=` parameter, and no change to any existing funnel.**

**Acceptance criteria**
- **Verify:** one wire call leaves exactly one `climate_write` row with `verb="set_activity_setpoint"`, `site`, `zone_id`, `values_before`, `values_after`, and `wire_ok`. A raising call also leaves exactly one row, with `wire_ok=false` and `exc` set.
- **Verify:** a deferring gate makes zero wire calls, writes zero `climate_write` rows, and writes one `comfort_delay_deferred_write` row.
- **Verify:** freeze floor. `freeze_active=True`, low 45 → the wire gets low 50.
- **Test:** `test_emit_set_activity_setpoint_one_row_per_call`, `test_emit_set_activity_setpoint_raise_one_row`, `test_emit_set_activity_setpoint_gate_defers_no_call`, `test_emit_set_activity_setpoint_freeze_floor`.
- **Test (lint):** `test_hvac_climate_write_funnel_completeness.py` is extended so an `"ha_carrier"` literal service call outside `hvac_setpoint.py` fails, plus a self-test fixture for it.
- **Live:** the first S10 write after enable shows as a `climate_write` row with `verb=set_activity_setpoint` in `ura_activity_log`.

### D2 — `set_preset_range` strategy method (`hvac_strategy.py`)

As specified in §3.3: Generic → `FAILED("preset_range_unsupported")`; Carrier → P1–P5.

**Acceptance criteria**
- **Verify:** status `home`, hold `away` → `DEFERRED("activity_not_confirmed")`, zero calls. Status `manual` → `DEFERRED`, zero calls.
- **Verify:** `hvac_mode="cool"` → `DEFERRED("not_heat_cool")`.
- **Verify:** desired 75.4/70.2 against an observed 75/70 → `SKIPPED_ALREADY_CORRECT`, zero calls (rounding, then tolerance).
- **Verify:** desired 74/70 against an observed 76/70 → one funnel call with 74/70 → `APPLIED`.
- **Verify:** a Generic platform thermostat → `FAILED("preset_range_unsupported")`, zero calls.
- **Test:** `test_carrier_set_preset_range_requires_both_feeds`, `test_carrier_set_preset_range_manual_defers`, `test_carrier_set_preset_range_heat_cool_only`, `test_carrier_set_preset_range_rounds_and_skips`, `test_carrier_set_preset_range_applies_diff`, `test_generic_set_preset_range_unsupported`, `test_set_preset_range_no_await_between_observe_and_wire` (asserts the wire call's `values_before.preset_mode == preset`, with a state change scheduled via `hass.async_create_task` before the call).

### D3 — S10 rewrite (`hvac.py` `_async_apply_preset_overrides`) + `borrow_live` extraction (`hvac_preset.py`)

- Implement §3.2.
- **Delete** the D9 compose-away branch, the S10-local transient-block hold, the F2 bypass, `_dpm_composed_away_zones`, the `_last_emitted_range` write at `:3620`, and the `cool − 7` baseline at `:3541`.
- Update the comments at `hvac.py:383` and `:543` (the map is now owned by S11/S13).
- Pull gate (e) out of `manual_guard_verdict` into `borrow_live(zone_id) -> str | None`. The return values are `"row"`, `"row_accessor_error"`, `"nudge_restore_timer"`, `"nudge_in_flight"`, `"compromise_timer"`, or None. `manual_guard_verdict` calls it; the verdict dict is byte-identical.

**Acceptance criteria**
- **Verify (the fight is gone):** zone in `home`/`home`, DPM override home cool_high 75 against Bryant 76 → S10 makes one `set_activity_setpoint` call. On the next tick S1 does **not** write, because `preset_mode` is still `home`, and makes zero `set_preset_mode` calls. S10's next tick → `SKIPPED_ALREADY_CORRECT`.
- **Verify (the storm is gone):** an established-empty zone in `away` whose away profile already matches, over 12 ticks → **zero** wire calls from S10. Old behaviour was 12 `set_temperature` calls.
- **Verify (each skip):** egress-paused, a/b armed, same-tick S1 write, live borrow row, `_nudge_in_flight`, `_compromise_timers`, AC reset, `manual`, `wake` → zero S10 wire calls each.
- **Verify (low side):** winter, `away` baseline 80/65, no override → the write is 65/80, **not** 73/80.
- **Verify (no house-state composition):** house `home_day`, zone S1-narrowed to `away` → S10 edits the **away** profile only, and never writes home values to that zone.
- **Verify:** `manual_guard_verdict` output is unchanged across the full existing W1-B gate suite (regression).
- **Test:** `test_s10_edits_profile_not_hold_no_s1_reclaim`, `test_s10_empty_zone_no_storm_12_ticks`, `test_s10_skip_matrix` (parametrised over the 9 skip causes), `test_s10_low_side_uses_configured_heat_winter_away`, `test_s10_acts_on_zone_preset_not_house_state`, `test_s10_dpm_sleep_override_applies_only_in_sleep`, `test_borrow_live_extraction_verdict_identical`.
- **Tests retired or rewritten (list them in the build report):** D9 compose-away tests in `test_zzz_hvac_conditioning_demand.py`; the S10 transient-hold tests in `test_hvac_live_room_hold_wire_in.py` (the S1 row-1 hold tests stay); S10 `set_temperature` expectations in `test_freeze_floor.py`, `test_arrester_comfort_delay.py`, `test_v471_fixup_d2_d3_d4.py`, `test_hvac_w1a_site_migration.py`, `test_v478_egress_window.py`. These are rewritten to the new verb. None may simply be deleted without a replacement assertion for the same guarantee (egress skip, comfort defer, freeze floor, W1-A row).
- **Live:** see §7.

### D4 — Rate bound + trip-wire (`hvac.py`, `hvac_const.py`)

As specified in §6.2.

**Acceptance criteria**
- **Verify:** a thermostat that never takes the value (the mock keeps 76 after every write) → exactly `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` (3) wire calls for that (zone, preset, value), spaced at least `S10_PRESET_RANGE_MIN_INTERVAL_S` apart. Then one NM `s10_preset_range_not_sticking`, then zero calls for the rest of the run.
- **Verify (discharge):** change the desired value (a DPM bucket change) → the latch clears and writing resumes. Turning switch 01 off and on also clears it, and so does a restart (the record is RAM-only).
- **Verify:** two different presets on the same zone each get their own budget.
- **Test:** `test_s10_rate_min_interval`, `test_s10_latch_after_three_unconfirmed_and_nm_once`, `test_s10_latch_discharges_on_value_change`, `test_s10_latch_discharges_on_switch_toggle`.
- **Live:** during the first day after enable, S10 rows per zone ≤ (D0 differing cells for that zone) + (DPM value changes) + 3.

### D5 — User-facing text (`strings.json`, `translations/en.json`, `switch.py` docstring)

The label style guide applies: config-flow text is short phrases and plain sentences; entity names are ≤3 words with the numeric prefix kept; no jargon. The strings are exact:

| Surface | Key | Current | New (exact) |
|---|---|---|---|
| Switch name | `switch.py:1998` | `01 · Custom Preset Ranges` | **unchanged** (3 words) |
| Baseline editor description | `config.options.step.hvac_baseline_presets.description` (en.json:1244 and strings.json) | "Edit the house-wide preset temperature ranges per season. These are the baseline setpoints that every zone uses unless Dynamic Preset is configured per-zone. …" | `Temperature ranges for each preset, by season. When Custom Preset Ranges is on, URA writes these into each thermostat's Home, Sleep, Away and Vacation presets. When it is off, each thermostat keeps its own ranges. Cooling must be at least 3°F above heating. To restore factory defaults, check 'Reset all to defaults' and save.` |
| DPM master helper | `…hvac_dynamic_preset.data_description.dynamic_preset_enabled` (en.json:1231) | "Master toggle for the Dynamic Preset feature. When off, all zones fall back to the seasonal baseline setpoints." | `Adjusts the Home and Sleep cooling limit with the weather. Only reaches the thermostats when Custom Preset Ranges is on. Off in winter.` |
| NM title | `s10_preset_range_not_sticking` | — | `Preset range not taking: {zone_name}` |
| NM message | same | — | `URA set {zone_name} {preset} to {low}–{high}°F three times, but the thermostat kept a different range. URA has stopped trying until the range changes or Home Assistant restarts. Check that preset in the Bryant app.` |
| Switch docstring | `switch.py:1975-1988` | "Master kill switch for Guest Mode HVAC actuation … OverrideEngine temperature ranges are applied…" | Say that it writes URA's preset ranges into each thermostat's own presets (no hold); that when off, thermostats keep the last range written; that the entity_id is `switch.ura_hvac_coordinator_guest_mode_actuation`. |

No new config-flow field and no new entity. Parsimony: the two new numbers are rung-1 constants (§6.1).

**Acceptance criteria**
- **Test:** the existing strings/translations parity test passes. `test_label_no_jargon_s10_strings` asserts that none of the new strings contains "DPM", "override", "hold", "throttle", or "S10".
- **Live:** the options flow → HVAC → Baseline Presets shows the new description.

### D6 — Diagnostics (`sensor.py` `HVACActivePresetOverridesSensor`)

Add one attribute, `preset_range_by_zone`: `{zone_id: {preset, desired_low, desired_high, status, reason, last_write_iso, latched}}`, read from the S10 record. Keep the existing attributes.

The existing `resolved_ranges` attribute keeps the house-state view with the engine's `cool_low`. Add one line to its docstring: "display of the engine opinion; the written low is the configured heat". Display parity is carded (§12).

**Acceptance criteria**
- **Verify:** after an APPLIED write, the attribute shows `status=applied` with the written values.
- **Test:** `test_active_preset_overrides_sensor_exposes_s10_record`.
- **Live:** `sensor.ura_hvac_coordinator_active_preset_overrides` attribute `preset_range_by_zone` is filled for each zone within 2 ticks of enable.

### D7 — Docs in the same commit
- **`HVAC_ARCHITECTURE_STATE_OF_PLAY.md`:**
  - Header snapshot.
  - §1: setpoint layer. D9 is replaced; S10 edits named profiles.
  - §3.2: consumers of the gate. Remove D9 at `hvac.py:2966`.
  - §3.3: table row.
  - §4.1: add the `emit_set_activity_setpoint` funnel.
  - §4.2: S10 row.
  - §5: the `set_activity_setpoint` row now reads "used by S10".
  - §9.7 (the Custom Preset Ranges item): closed.
  - §11 row 5.
- **`THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §3:** "adopted for S10 standing ranges, not for borrows; the §3 snapshot/restore rule applies to borrows only (rationale §3.4 of this plan)". Close open item 6 for S10 with the live evidence.
- **README** `docs/readmes/README_v5.103.x.md` with a Validated table (§7).

---

## 6. Numbers and rate bound

### 6.1 Constants (knob ladder)

| Name | Value | Rung | Why this rung | Why this value |
|---|---|---|---|---|
| `S10_PRESET_RANGE_MIN_INTERVAL_S` | 1800 | **1** (`hvac_const.py`) | A Carrier cloud call-rate bound, governed like `HVAC_DECISION_TICK` (`hvac_const.py:11-13`, "change requires review"). | ≥ ha_carrier's normal refresh (`DEFAULT_UPDATE_INTERVAL_MINUTES=30`) and ≫ its 5-min post-write guard (C16/C21). A cloud revert is therefore visible before URA retries, so the retry is judged on cloud truth, not on ha_carrier's local re-assert. |
| `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` | 3 | **1** | Same reason. | Covers one lost write plus one transient cloud error. More than 3 means the device will not take the value (rounding, a device clamp, or a human re-editing in the app). Stop and tell the operator. |

There is no kill switch: switch 01 already is one.

### 6.2 Rate model

In-memory `self._s10_range_record[(zone_id, preset)] = {value, writes, last_write_mono, latched, confirmed}`:
- **Write allowed** iff `not latched` and (`last_write_mono is None` or `now − last_write_mono ≥ MIN_INTERVAL`).
- **After APPLIED/FAILED:** `writes += 1`, `last_write_mono = now`. If `writes ≥ LIMIT` and the next attempt is still not `SKIPPED_ALREADY_CORRECT`, then `latched = True` and send one NM.
- **Discharge:** `value` changes → reset the record. `SKIPPED_ALREADY_CORRECT` → `confirmed = True`; `writes` is **not** reset, so a guard-masked "confirmation" cannot re-arm an endless loop. Switch 01 toggle → clear all records. Restart → RAM-only, so fresh.

**Budget against Carrier constraints.** One `set_activity_setpoint` is one cloud call (`set_config_activity`, `climate.py:580-590`). The old path was `set_temperature` (2 calls) plus S1 resume-then-pin (≥2).

| Scenario | Old S10 (switch ON) | New S10 |
|---|---|---|
| Steady state (profiles match) | Occupied zones: 0 after one fight. **Empty zones: ≈48 calls/h/zone.** | **0** |
| Enable day | Storm as above | ≤ D0 differing cells (≤ 4 per zone) |
| DPM bucket change (dwell ≥ 60 min, `dynamic_preset_dwell_minutes=60`) | 1 raw write + S1 reclaim | ≤ 1 per affected preset, applied at its next visit |
| Season boundary (2×/yr, Oct 1 / Dec 1 / Mar 1 / Jun 1) | as above | ≤ 4 per zone |
| Device will not take the value | unbounded | ≤ 3 per (zone, preset, value), then latch + NM |

Worst-case ceiling while unlatched: at most 2 calls/h per (zone, preset). This is far inside the W1-B budget that was already accepted (~160 extra writes/day, state-of-play §9e).

---

## 7. Falsifiable invariant, and live validation after enable

### 7.1 Invariant (the thing that must never happen)

> **INV-S10.** With `switch.ura_hvac_coordinator_guest_mode_actuation` ON, **no S10 wire call ever changes a zone's hold state or lands while the zone's status preset and `hold_activity` disagree**. Specifically, every S10 `climate_write` row has `verb="set_activity_setpoint"`, and `values_before.preset_mode == values_before.hold_activity == the preset S10 targeted`, which is in {home, sleep, away, vacation}. No S10 wire call occurs for a zone with a live borrow, person-protected hold, arrester comfort window, AC reset, egress pause, or same-tick S1 write. **Hence S10 never creates `manual`, and S1 never reclaims a zone because of S10.**
>
> **INV-RATE.** For any (zone, preset, value), S10 issues at most `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` wire calls per HA run, spaced at least `S10_PRESET_RANGE_MIN_INTERVAL_S` apart.

**Falsifier queries** (live, against `ura_activity_log`, one-shot, not a watch):
- Q1: S10 rows with `verb != 'set_activity_setpoint'` → **must be 0**. (The old path signature is `set_temperature` at `site=S10_dpm_apply`.)
- Q2: S10 rows where `values_before.preset_mode != values_before.hold_activity`, or `values_before.preset_mode = 'manual'` → **must be 0**.
- Q3: `preset_change` rows with `manual_class='zero_delta_ura'` on a zone within 15 min after an S10 row, with no other URA `climate_write` on that zone in between → **must be 0**. This is the fight signature.
- Q4: count of S10 rows per (zone, preset, `values_after`) → **must be ≤ 3**. More than 3 means the storm or loop signature.

**Discrimination: why the observations tell fix from failure.**

| Observation | Under the fix | Old code / fight | Old code / storm | Another failure (wrong-profile edit) |
|---|---|---|---|---|
| S10 row verb | `set_activity_setpoint` | `set_temperature` | `set_temperature` | `set_activity_setpoint` |
| `preset_mode` after S10 write | unchanged named preset | `manual` | `manual` | unchanged |
| S1 `zero_delta_ura` after S10 | none | yes, once | yes, every tick | none |
| S10 rows/zone/hour, empty zone | 0 | 0 after first | ~12 | ≤ 2 |
| Bryant app, zone's preset | "Holding Home 70–75" (edited range) | "Holding Manual" then back to Home at the old range | alternating | the range appears on a **different** preset than targeted (caught by Q2 plus the app check) |

### 7.2 The enable step (operator action; exact knobs)

Do this after deploy, HACS install, restart, and D0 fixture review:
1. **Turn ON `switch.ura_hvac_coordinator_guest_mode_actuation`**, shown as **"URA: HVAC Coordinator — 01 · Custom Preset Ranges"**. This is required.
2. Run live checks L1–L6 (below) against the current preset of each zone.
3. **Then turn ON `switch.ura_energy_coordinator_dynamic_preset_overrides`**, shown as **"02 · Dynamic Preset Auto-Adjust"**. This is the weather nudge, and it is recommended in the same session once L1–L6 pass. Run L7.
   - Optional hygiene: open options flow → HVAC → Dynamic Preset and save, so the stored option matches the switch (§12).

Doing it in two steps separates the static half from the weather half, so a failure is attributable. There is no soak between the steps; each is a one-shot check.

### 7.3 Live checks (the README "Validated" table is filled from these)

| # | Check | Oracle | PASS if |
|---|---|---|---|
| L1 | For each zone whose feeds agree on a named preset: within 2 ticks, one S10 row **iff** the D0 fixture cell differs | `ura_activity_log` `climate_write` rows `site=S10_preset_range` | the set of rows = the set of differing cells for the current presets, and `values_after` = the fixture's desired values |
| L2 | The zone stays on its named preset | climate entity `preset_mode` and `hold_activity` 10 min after each S10 row | both unchanged (named), never `manual` |
| L3 | The thermostat shows the new range | climate `target_temp_low/high` **plus the operator reading the Bryant app** (physical, independent oracle: "Holding Home xx–yy", not "Manual") | both match `values_after` |
| L4 | No fight | Q3 | 0 |
| L5 | No storm | Q1, Q4; S10 rows on established-empty zones over the first hour | Q1 = 0, Q4 ≤ 3, empty-zone rows = only D0 differing cells |
| L6 | Borrows unaffected | the next soft nudge on any zone: `ac_ramp_events` `nudge_started` → `nudge_restored` returns to the named preset, which now carries the custom range; no S10 row during the nudge | as stated |
| L7 | Weather nudge reaches the profile | `sensor.ura_energy_coordinator_dynamic_preset_bucket_*` + `..._range_*` + an S10 row with `reason=preset_range_dpm` at the next Home/Sleep visit, or a documented skip reason (`winter_season`, `no_forecast_delta`) | row matches the DPM cool_high, or the skip reason is shown and explained |

Criteria that can only be proven in-suite: the trip-wire latch (D4) and the low side in winter (D3). The README must say so.

---

## 8. Supersession (post-ship audit, pre-declared)

| Item | File:line | Bucket | Superseded by | Reason |
|---|---|---|---|---|
| D9 compose-away branch | `hvac.py:3452-3528` | **DELETE** | S1 row-1 preset retreat (LIVE, `conditioning_retreat_ok`) + W1-B presets-only returns | It existed to correct third-writer raw-setpoint restores on empty zones. After D2.4, those restores are preset pins, and row-1 moves an empty zone's preset to `away` within one tick. It is also the storm source, a footgun. |
| F2 throttle bypass | `hvac.py:3563-3578` | **DELETE** | ground-truth compare (§3.3 P4) | Unconditional bypass, which is the storm. |
| S10-local transient-block hold | `hvac.py:3488-3517` | **DELETE** | S10 no longer composes a retreat | Its only purpose was to hold D9's retreat during a reload. The row-1 hold at S1 stays. |
| `_dpm_composed_away_zones` | `hvac.py:3522-3526` | **DELETE** | — | No readers (grep: code + tests). |
| `cool − 7` baseline at S10 | `hvac.py:3541` | **DELETE** | configured heat (§3.3) | Bug Class #63 defect. |
| `_last_emitted_range` writes by S10 | `hvac.py:3620`; clear at `switch.py:2037-2039` | **DELETE** (S10 only) | — | The map is kept for S11/S13. |
| `_last_emitted_range` map | `hvac.py:543` | **KEEP + DOCUMENT** | — | Live consumers S11/S13 remain. |
| `hvac_predict._resolve_baseline_range` `cool − 7` fallback | `hvac_predict.py:908-918` | **KEEP + WIRE** (card) | should use configured heat | Same defect class on the HUMAN_MANUAL raw-restore path. That path is live today, so the fix is behaviour-changing and has its own card. |
| OverrideEngine `cool_low` | `preset_overrides.py:60`, `dynamic_preset.py:905,931` | **KEEP + DOCUMENT** | — | Ignored at actuation; still shown on sensors. Comment: "no physical meaning on heat_cool devices; actuation uses configured heat". |

Expected DELETE count: 6. The deletes land in this cycle because the new path replaces them in the same change, and live validation L1–L6 confirms the replacement.

---

## 9. Card dispositions

- `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` → **done** once D3 and D4 ship. The bypass is deleted and S10 writes are bounded by INV-RATE. Evidence: Q1/Q4 = 0 / ≤ 3 live.
- `HVAC-S10-DPM-VS-S1-1` → **done** once D1–D3 ship. S10 never creates `manual`. Evidence: Q2/Q3 = 0 live. The operator constraint was honoured: no EXCURSION_KIND, `begin_excursion` untouched, and the only new read is a pure S1-side helper.
- `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` → **verify-and-close on D0 item 4**.
  - Its premise ("restore writers emit comfort setpoints to an empty zone; the D9 corrector is dormant") was removed by W1-B D2.4 presets-only returns (`hvac_override.py:5041`, `:6276`, `:6750`; `hvac_predict.py:984`, `:1542`) together with row-1.
  - Its HUMAN_MANUAL raw-restore residual now lands a `manual` that S1 reclaims under §9e.
  - **Its `FOLD_2026_09_17` item (EC coast/shed offset path snapshot + restore) is NOT covered by this plan.** It stays open as the card's residual.

---

## 10. Test authority requirements (for the builder and Reviewer C)

- **T1.** Each skip in the D3 matrix is mutation-anchored. Neuter that one line in the S10 loop and a named test must fail. Restore the line and check `git status` is clean. Bytecode is off during drills (`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared); see memory "mutation pyc staleness".
- **T2.** Wire-in anchor. Drive `_apply_house_state_presets` (the enclosing method), not `_async_apply_preset_overrides` alone, for the fight test. The S1-then-S10 same-tick ordering is part of what is proven.
- **T3.** Neuter the P1 both-feeds check in `CarrierStrategy` → `test_carrier_set_preset_range_requires_both_feeds` fails.
- **T4.** Neuter rounding → `test_carrier_set_preset_range_rounds_and_skips` fails, and D4's loop test shows more than 3 calls.
- **T5.** Insert an `await asyncio.sleep(0)` between `observe` and the funnel → `test_set_preset_range_no_await_between_observe_and_wire` fails.
- **T6.** Fixtures use the real `PresetManager.get_seasonal_setpoints` and real CM options shapes, not hand-copied tuples. The mock `ha_carrier` service honours "edit the status-named activity only", as in `climate.py:551-596`.
- **Suite:** `PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/ -v`, serial. Compare test names against the `pre-review` tag baseline, not counts.

---

## 11. Tier and review protocol

**Tier 2-DB** (three framing-disjoint build reviews + live validation + README write-back). This is elevated from the card's Tier 2 under the standing policy (CLAUDE.md, 2026-06-08) because the change is regression-prone:
- It adds a new writer verb to the thermostats.
- It deletes a corrector path (D9/F2).
- It sits next to S1 / nudge / arrester precedence.

It is **not Tier 3**. There is one emission site (S10). The load-bearing precondition lives in one function (`CarrierStrategy.set_preset_range`). The failure mode is not "one missed site of many". The operator may elevate.

- **Plan review:** ONE adversarial plan review before build dispatch. It re-runs the §2.1 greps and independently re-lists every writer that can put a zone on a named preset with a stale profile, and every consumer of `_last_emitted_range`.
- **Build reviews (parallel, disjoint framings):**
  - **A — correctness and edge cases:** preconditions P1–P5, rounding, deadband and freeze guards, season boundary, winter DPM gate, low side, Generic fallback, WriteResult handling.
  - **B — cross-coordinator precedence, lifecycle, no-flap:** S1 same-tick ordering, nudge/compromise/banking/pre-heat/egress/AC-reset interplay, arrester booking, the ha_carrier 5-min guard against the 30-min retry, switch toggle and restart, `_last_emitted_range` S11/S13 consumers, NM latch discharge.
  - **C — test authority by real per-site source mutation:** T1–T6, the lint extension, and retired tests each replaced by a same-guarantee assertion.
- **Pre-deploy:** tag `pre-review-v5.103.x`; the zero-bugs gate (conflict markers, py_compile, cycle tests, suite name-diff).
- **Post-deploy:** HACS install check, then the operator performs the enable step (§7.2), then live checks L1–L7, then the README Validated table and state-of-play update in the same commit.

---

## 12. Non-goals (explicit)

- No new `EXCURSION_KIND`. No change to `begin_excursion` / `return_excursion` / `hvac_excursion.py` (operator constraint).
- No change to S1's four gates, `should_change_preset`, or any existing `emit_*` funnel.
- Nudges stay on `set_temperature` (integration plan §5 decision 1 stands). This cycle adopts `set_activity_setpoint` for standing ranges only.
- No snapshot/restore of Bryant profiles on disable (§3.4). The ledger `values_before` is the record.
- No heat-side weather adjustment. DPM stays cooling-only and off in winter.
- No guest-mode override producer. The entity_id keeps its historical `guest_mode_actuation` name (renaming a unique_id is a registry migration and not worth it).
- No support for non-Carrier thermostats (Generic returns unsupported; S10 skips).
- No `wake` preset (no baseline row exists).
- No fix for the zone_1 status/hold split (§9.7). S10 just defers there; the fix belongs to `HVAC-WRITE-CONFIRMATION-ORACLE-1`.
- Not fixed, carded instead (adjacency sweep at mint time):
  - `hvac_predict._resolve_baseline_range` `cool − 7` fallback → **new card** `HVAC-BASELINE-HEAT-LOW-COOL-MINUS-7-1` (Bug Class #63). Candidate for the same build if the plan review rates it ≤ 30 LoC with no ripple.
  - Options-form `dynamic_preset_enabled=true` vs switch 02 `off` (two surfaces for one knob) → **new card** `HVAC-DPM-OPTION-VS-SWITCH-SPLIT-1`.
  - `sensor.ura_energy_coordinator_dynamic_preset_range_*` shows `cool_low = high − 7`, which is not what gets written → fold into the first card.
- No Bryant schedule changes. Profiles edited by S10 are also used by any remaining vendor schedule entries, which is consistent with URA control.

---

## 13. Open questions for the operator (answer before build)

1. **Profile edits in the Carrier app while the switch is ON** get overwritten at the next visit to that preset. After 3 edits of the same value, URA stops and sends a notification. OK? *(Recommendation: yes. This matches "URA has more information and should win", §9e D48.)*
2. **On switch-off, keep the last URA ranges** rather than restoring the Bryant originals (§3.4). OK? *(Recommendation: yes. The originals stay in the ledger.)*
3. **Include the S11/S13 `cool − 7` fallback fix in this build**, or ship it separately? *(Recommendation: separately, unless the plan review rates it trivial.)*
