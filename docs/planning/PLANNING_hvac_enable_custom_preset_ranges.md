# PLANNING — Enable Custom Preset Ranges (D9 / `guest_mode_actuation`, HVAC arc step 5)

**Status:** PLAN **REV 2** (2026-09-27). Not built.
- REV 0 got a plan review verdict of FIX-PLAN. REV 2 folds in every must-fix (HIGH-1, M1–M4), LOWs 1–3 and 5–7, and the operator rulings Q1–Q3 (verbatim at the end).
- **The build is gated on D0 item 5**, a controlled live test that needs operator approval.

**Operator ruling (2026-09-27):** "yes", the operator wants the feature. URA wins over app edits. Carrier originals are restored when the feature is turned off. The heat-bug fallback is handled separately.

**Arc position:** `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §11 row 5.

**Cards resolved:** `HVAC-S10-DPM-VS-S1-1`, `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`. Disposition of `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` in §9.

**Version:** next free `5.103.x` PATCH.

### REV 2 delta (for the re-reviewer)

| Finding | Where fixed |
|---|---|
| HIGH-1: controlled live test of `set_activity_setpoint` before build | §4 D0 item 5 (build gate) |
| M1: wrong confirmation rationale (config re-read every 120 min; the post-write guard hides reverts) | §3.3 P4 renamed "HA-view comparison"; §6.1 interval re-derived (130 min); §7.3 L3 physical app check is the only oracle |
| M2: latch rule; FAILED counted separately | §6.2 |
| M3: persistence across restarts | §6.3 (`__s10_preset_ranges` side-key, write-ahead save) |
| M4: drop `suppress(kind="temp")` | §3.2 step 10, §2.1 row; test `test_s10_edit_books_no_override_detected` |
| LOW-1: P1 rationale; keep the `hold_activity` check? | §3.3 P1 (kept, with the real reason) |
| LOW-2: after-call preset check | §3.3 P6, `possible_wrong_profile` |
| LOW-3: clear records on switch paths | §3.5 (user transitions clear; restore paths do not, with reason) |
| LOW-4: fix the heat fallback here | **Not folded.** Operator ruling Q3: handled separately (card `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1`) |
| LOW-5: full list of preset-range consumers | §2.7 |
| LOW-6: switch default ON → OFF | D8 (conditional on operator answer, §13 Q4) |
| LOW-7: reword INV-RATE | §7.1 |
| New-funnel sanction line | §12 |
| Operator Q2: restore Carrier originals | §3.4 (full spec) + D3b + tests |

---

## Read-first attestation

- I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full, all 470 lines, including §9e. W1-B shipped v5.103.18: the v3.8.0 S1 manual guard was replaced by four gates (a/b person-protected, c arrester window, d arrester disabled, e live borrow), and borrow returns became presets-only.
- This plan re-asserts nothing in §10 (C1–C25), and in particular:
  - It does not rely on the retired guard (C25).
  - It does not treat `hold_activity` as a universal oracle (C20/C22/C23).
  - It does not use 42–79 s as Carrier's schedule (C16).
  - It does not call `set_activity_setpoint` a local patch (C15).
  - It does not claim ha_carrier re-sends anything to the cloud (C21).
- Both blocker cards were read in full, including the operator constraint added 2026-09-27: *no new EXCURSION_KIND and no logic inside `begin_excursion` without a ruling; prefer S1-side reads.* This plan touches neither `hvac_excursion.py` nor the excursion kinds.

---

## STEP 0 — what the feature is today, and the real knob

### Q1. What does the feature do today, and why was it dormant?

The only actuator is `HVACCoordinator._async_apply_preset_overrides` (site **S10**, `hvac.py:3373-3638`). It is called at the end of `_apply_house_state_presets` (`hvac.py:3317-3320`), in the same tick and right after S1. It returns immediately when `_guest_mode_actuation_enabled` is False (`hvac.py:3390`).

When the switch is ON, S10 does this for every zone on every tick:
1. It takes the **house-state** preset (`hvac.py:3416`). The exception is D9 compose-away, which swaps in `away` for established-empty zones (`:3518-3528`).
2. It builds a baseline from URA's editable seasonal table (`get_seasonal_setpoints`, `hvac_preset.py:126-180`). The live CM options set all 24 `hvac_baseline_*` values.
3. **It sets the low side to `cool − 7` and throws away the configured heat value** (`hvac.py:3537-3542`).
4. It layers on OverrideEngine records from EC `_dynamic_preset_overrides` (`energy.py:7126-7319`). Only Dynamic Preset produces records, and only for home and sleep (`dynamic_preset.py:926-959`). Nothing produces guest overrides (`preset_overrides.py:241-249`).
5. It writes **raw `climate.set_temperature`** (`hvac.py:3598-3609`) whenever the pair differs from `_last_emitted_range`. On compose-away zones it writes on **every tick** (the F2 bypass, `:3575-3578`).

A raw `set_temperature` rewrites the MANUAL activity and sets `hold=MANUAL` (`ha_carrier/climate.py:467-537`). Because `infinite_holds` is on, that hold never expires. What happens next depends on the era:
- **Before v5.103.18:** the old guard left the zone stuck in manual. The feature "worked" only by stranding zones there (the §9.1 class).
- **Under W1-B:** S1 reclaims the manual hold on the next tick.
  - Occupied zones: after one fight, `_last_emitted_range` matches, S10 goes silent, and the zone runs its Bryant profile. The feature does nothing.
  - Empty zones: the F2 bypass makes S10 write every tick, followed by S1 resume + pin. That is about 48 Carrier calls per hour per zone, indefinitely, and it would trip `s1_reclaim_rate_high`.

There is also a **latent comfort defect (Bug Class #63)**: `cool − 7` equals the configured heat only by coincidence. Repro with the live winter away setting 80/65: switch ON, January, house away → S10 writes heat setpoint **73 °F** to an empty zone.

**Why it was dormant.**
- v5.103.7 shipped D9/F2 assuming this switch stays off, and made the F2 storm a blocker on ever enabling it (`README_v5.103.7.md:31-39, :63, :72-73`).
- W1-B then added the S1-vs-S10 fight (A-L5, `PLANNING_hvac_w1b_thermostat_definition.md:408`).
- The switch is `off` in every recorded state since 09-18 and in `core.restore_state` today.
- Who first turned it off, and why: **UNVERIFIED**.

### Q2. Is `switch.ura_hvac_coordinator_guest_mode_actuation` the right switch? What is its label?

**Yes.** Verified in the live entity registry:

| Entity id (live) | unique_id | Label | Backing field | Live |
|---|---|---|---|---|
| `switch.ura_hvac_coordinator_guest_mode_actuation` | `..._hvac_coordinator_guest_mode_actuation_enabled` | **"01 · Custom Preset Ranges"** (`switch.py:1998`) | `HVACCoordinator._guest_mode_actuation_enabled` (`hvac.py:540`) | off |
| `switch.ura_energy_coordinator_dynamic_preset_overrides` | `..._energy_dynamic_preset_enabled` | **"02 · Dynamic Preset Auto-Adjust"** (`switch.py:1715`) | `EnergyCoordinator._dynamic_preset_enabled` (`energy.py:791`) | off |

Notes:
- The switch docstring and README_v4.7.1/4.7.2 give the entity id with an `_enabled` suffix. The real entity id has none.
- Switch 01 is the only actuation gate. Switch 02 gates the only override source.
- Per-zone opt-in is `true` on all four zone configs.
- The stored option `dynamic_preset_enabled` is `true`, but the switch's restored `off` wins at boot (`switch.py:1869-1880`). That mismatch is carded (§12).
- Two existing helper texts are wrong while 01 is off. `en.json:1244` claims every zone uses the baselines. `:1231` claims zones "fall back to the seasonal baseline". Both are fixed in D5.

---

## 1. Config-first check

| Candidate | Solves it? | Evidence |
|---|---|---|
| Flip 01 ON with no code change | **No, harmful**: silent on occupied zones, storm on empty zones, winter-away heat 73 | STEP 0 |
| Flip 02 only | No: nothing actuates while 01 is off | `hvac.py:3390` |
| Type URA's ranges into each Bryant preset in the Carrier app | **Partly.** Covers the static half with no code, but must be retyped at each season change and cannot follow the weather | `dynamic_preset.py:109-132` |
| `ha_carrier` option `infinite_holds` | No | — |

**Marginal benefit.**
- The static half can be done by hand. Code buys automatic season changes and one editing place in URA.
- The dynamic half is ±1 °F on Home/Sleep cooling and is off November through February.
- The simplest correct code is small because it writes the preset profile instead of a hold. It deletes more risky machinery (D9/F2) than it adds.

**Verdict: BUILD** (operator ruled yes), gated on D0 item 5.

---

## 2. Institutional context verified

### 2.1 Prior-art scan (REUSE / BUILD per piece)

| Piece | Verdict | Existing symbol / justification |
|---|---|---|
| Write a preset's range without a hold | **REUSE upstream** `ha_carrier.set_activity_setpoint` | `climate.py:91-104` registers it. `:539-596` edits the **status-named** activity (`_current_activity()`, `:136-142`) via `set_config_activity` and does not touch hold state (`:591`). Upstream PR #427 (C15). |
| Funnel for the new verb, with one `climate_write` row | **BUILD** `emit_set_activity_setpoint` | Sanctioned by W1-A (`PLANNING_hvac_w1a_thermostat_write_governance.md:363`). Reuses `_snapshot_climate_state` (`hvac_setpoint.py:127-160`), `_schedule_climate_write_row` (`:163+`), `_log_deferred_write` (`:258`), `apply_setpoint_guards` (`:96-112`). **No existing funnel changes** (§12). |
| Per-brand rules | **REUSE + extend** `hvac_strategy.py` | `strategy_for` (`:254`), `WriteResult` (`:56-75`), `observe` (`:119-139`), `LAST_SENT_TOLERANCE_F` (`:53`). Adds `set_preset_range` on Generic (unsupported) and Carrier. |
| Live-borrow read | **REUSE** gate (e) (`hvac_preset.py:293-317`) | Pulled out into a pure `borrow_live(zone_id)`. Calling `manual_guard_verdict` directly is rejected because it writes `_last_manual_verdict` (`:333`). |
| Person-protected skip | **REUSE** `_corrective_writes_suppressed` (`hvac_override.py:672`) | Already at S10 (`hvac.py:3443-3451`). |
| Comfort-delay defer | **REUSE** `_s10_gate` / `comfort_delay_active` (`hvac.py:3589-3597`) | |
| Same-tick S1 skip | **REUSE** `_zones_written_this_cycle` (`hvac.py:455`, `:1879`, `:3194`) | |
| AC-reset / egress skips | **REUSE** `has_active_ac_reset` (`hvac_override.py:2183`), `is_paused` | |
| Range values | **REUSE** `get_seasonal_setpoints` + OverrideEngine + EC overrides | The written low is now the configured heat value. |
| Arrester must not book S10 | **REUSE, no stamp** (M4) | `_handle_climate_change` books only a transition into `manual`. A setpoint change under a named preset is explicitly ignored (`hvac_override.py:3216-3226`, "a preset range adjustment. Ignore."). `_comfort_request_qualifies` (`:3327`) runs only after that return. A `suppress()` stamp would add nothing, and it would blind a genuine human change to `manual` for 15 s. **Dropped.** |
| Persistence | **REUSE** `_zone_state_store` side-key pattern (`hvac.py:2081-2118`, rehydrate `:1780-1871`) | New side-key `__s10_preset_ranges` (§6.3). |
| Trip-wire NM | **REUSE pattern** `_note_s1_reclaim` (`hvac.py:1653-1695`) | |
| AST lint | **EXTEND** `test_hvac_climate_write_funnel_completeness.py` | Add the `"ha_carrier"` literal (`:120-130` flags only `"climate"`). |
| D9 compose-away, F2 bypass, S10 transient hold, `_dpm_composed_away_zones`, the `cool − 7` baseline | **DELETE** (§8) | |
| `_last_emitted_range` | **KEEP**; S10 stops writing it | S11 (`hvac_predict.py:864-920, 1060+`) and S13 (`:1589`) still use it. |

**Surfaces grepped:**
- Constants: `const.py`, `hvac_const.py`, `energy_const.py`.
- Fields: `config_flow.py`, `strings.json`, `translations/en.json`.
- Entities: `switch.py`, `sensor.py`.
- Code: `hvac*.py`, `energy.py`, `dynamic_preset.py`, `preset_overrides.py`.
- `ha_carrier/{climate,const,carrier_data_update_coordinator}.py`.
- `quality/tests/`: 7 files call `_async_apply_preset_overrides`.

### 2.2 Prior plans
- `PLANNING_v4.7.x_guest_mode_actuation_phase1.md`
- `PLANNING_v4.7.2_dpm_hvac_surface_plus_guest_signal.md`
- `PLANNING_hvac_zone_conditioning_demand.md` §0b/D9
- `PLANNING_hvac_w1b_thermostat_definition.md` (§5.P6, :408, D2.4 :307-311)
- `PLANNING_hvac_w1a_thermostat_write_governance.md:363, :399`
- `PLANNING_hvac_arc_w1_w2_integration.md` (C1, C5, §5 decision 1)
- `PLANNING_v5.7.0_guest_mode_detection_and_actuation.md:222`
- `HVAC_ARC_TAIL_2026_09_18.md:101-109`

### 2.3 READMEs
v5.103.7, v5.103.18, v4.7.1, v4.7.2, v4.7.3.

### 2.4 Memory
`feedback_label_style_guide.md`, `reference_hvac_state_of_play.md`, marginal-benefit, config-first, `feedback_unrestored_mutation_drill_poisons_evidence`, `feedback_suppression_needs_discharge`.

### 2.5 Design docs
State-of-play (full). `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §2–§3, verb table :261-265, open item 6 :328.

### 2.6 Code read
- `hvac.py` 3373-3638, 2913-3210, 1873-1880, 2081-2118, 1780-1871, 1653-1695
- `hvac_preset.py` (all), `hvac_strategy.py` (all), `hvac_setpoint.py` 90-485
- `preset_overrides.py`, `dynamic_preset.py`, `energy.py` 7126-7319
- `switch.py` 1685-2104, `sensor.py` 10128-10260
- `hvac_override.py` 2262-2281, 2678-2830, 2960-3290
- `hvac_predict.py` 150-195, 855-1065
- `ha_carrier/climate.py` 60-600, `ha_carrier/const.py` 40-64, `ha_carrier/carrier_data_update_coordinator.py` 145-345, 425-435

### 2.7 Every consumer of a preset profile's setpoints (LOW-5)

Once S10 edits a named profile, every reader of `target_temp_high/low` under that preset sees URA's range. Every site is listed. None needs a code change: each one already reads the live profile, and that is the intended new behaviour.

| Consumer | File:line | Trust / display | Effect of an S10-edited profile |
|---|---|---|---|
| Zone refresh (source of `zone.target_temp_*`) | `hvac_zones.py:558-559`, exposed `:816-817` | producer | Carries URA's range |
| Soft-nudge trigger ("at/below setpoint") and nudge start/size | `hvac_override.py:4129, 4177, 4596, 4730-4765` | trust | Nudges are measured against URA's range. Intended. |
| Nudge snapshot/restore (HUMAN_MANUAL path only) | `hvac_override.py:4828, 4853, 5067` | trust | Named-snapshot returns pin the preset, so they land on URA's range |
| Nudge outcome evaluation | `hvac_override.py:5542` | trust | |
| Hard-reset escalation | `hvac_override.py:6146, 6165` | trust | |
| Cancel-nudge / boot ramp audit | `hvac_override.py:6294, 6708, 6766` | trust | |
| Arrester detection delta (manual transitions only) | `hvac_override.py:3211-3214` | trust | `old_high` is URA's range, so a human's delta is measured from it. Correct. |
| Comfort-grant qualification (manual path only) | `hvac_override.py:2789-2792` | trust | Same |
| Startup audit (manual zones only) | `hvac_override.py:2274-2275` | trust | Unaffected (named zones skipped) |
| Excursion `begin` snapshot | `hvac_excursion.py:823-824` | trust | Snapshots URA's range |
| Pre-cool / banking (reads live high; known ratchet) | `hvac_predict.py:1132-1140, 1236` | trust | Banks off URA's range |
| Pre-heat | `hvac_predict.py:1425-1428, 1451, 1486` | trust | |
| Predictor demand deltas | `hvac_predict.py:343-397` | trust | |
| Fans (setpoint-relative activation) | `hvac_fans.py:762` | trust | |
| Covers (occupied close delta) | `hvac_covers.py:617-640` | trust | |
| Compliance / diagnostics commanded-vs-actual | `coordinator_diagnostics.py:483-484, 536-537` | display | |
| HVAC zone status sensor | `sensor.py:12841-12842` | display | |
| HVAC status snapshot | `hvac.py:5547-5548` | display | Keys mislabelled (`cool_low`/`heat_high`). Pre-existing, noted only |
| Strategy observe | `hvac_strategy.py:135-136` | trust (S10 itself) | |
| PWA/frontend bundles | `frontend*/assets/*.js` | display | |

---

## 3. Design

### 3.1 Core move: write the preset's profile, never a hold

S10 edits the zone's **named preset profile** in place through `ha_carrier.set_activity_setpoint`, and only while the zone is on that preset. The zone never goes to `manual`, so there are two independent reasons nothing reacts:
- S1 has nothing to reclaim (`hvac_preset.py:357-358`).
- The arrester ignores the change (`hvac_override.py:3220-3223`).

S1 writes *which* activity holds; S10 writes *what that activity contains*. W1-B's presets-only returns, arrester reverts and schedule transitions all land on named presets that already carry the range, so no after-borrow corrector is needed.

Rejected options:
- (a) New EXCURSION_KIND: forbidden by the operator constraint, and it is the wrong model for a standing setting.
- (b) Per-tick flag read by gate (e): the flag clears, S1 reclaims, and the range is lost. Making it sticky would bring back the dropped provenance approach.
- "Write a preset": a preset cannot carry a custom range. Editing its profile is the only way.

### 3.2 S10 per-zone algorithm (replaces the loop at `hvac.py:3423-3636`)

**Method entry:**
- **Switch OFF:** run the **restore pass** (§3.4) if any snapshot exists, then return.
- **Switch ON:** run the apply pass.

The observation-mode gate at the call site (`:3319`) is unchanged. An absent EC or empty overrides no longer returns early, because the static half still applies.

**Apply pass, per zone.** The first skip wins; each skip is `continue` plus a debug log.
1. `egress_manager.is_paused(zone_id)`.
2. `arrester._corrective_writes_suppressed(zone_id)` (gate a/b), plus `_log_shave_skipped(..., "dpm_preset_override")`.
3. `zone_id in self._zones_written_this_cycle`.
4. `preset_manager.borrow_live(zone_id) is not None` (gate e).
5. `arrester.has_active_ac_reset(zone_id)`.
6. `P = zone.preset_mode`. Skip unless `P ∈ {home, sleep, away, vacation}`.
7. `(base_cool, base_heat) = get_seasonal_setpoints(P)`. Skip if None.
8. Compute the range:
   - `resolved = engine.resolve_range(base_heat, base_cool, engine.get_active_overrides(zone_id, P, house_state, True, overrides.get(zone_id, [])))`.
   - `desired = apply_setpoint_guards(base_heat, resolved.cool_high, freeze_active=self._freeze_active)`.
   - Only `cool_high` comes from overrides; the low side is always the configured heat.
9. Snapshot capture (§3.4): if there is no snapshot for (zone, P), capture and save it **first**.
10. Rate/latch check (§6.2) on `(zone_id, P, desired)`.
11. Write:
    - `result = await strategy_for(...).set_preset_range(hass, entity, P, *desired, gate=_s10_gate, zone_id, site="S10_preset_range", reason="preset_range_dpm" | "preset_range_baseline")`.
    - **No `suppress()` stamp (M4).**
12. Update the record per §6.2.

### 3.3 `CarrierStrategy.set_preset_range` (brand rules)

**P1. Both feeds name `preset`.** The check is `obs.preset_mode == preset and obs.hold_activity == preset`; otherwise return `DEFERRED("activity_not_confirmed")`. Two separate reasons (LOW-1):
- *Which profile gets edited:* the service edits the status-named activity. S10 reads `P` from that same status field, synchronously, in the same event-loop step. So the edited profile equals `P` whether or not the `hold_activity` check exists. The check is **not** needed for this.
- *Why the `hold_activity` check is kept anyway:* after any ha_carrier write, the integration's 5-minute guard re-asserts **the status activity type and setpoints** in HA's local copy whenever a websocket message differs (`carrier_data_update_coordinator.py:283-295`). If the zone's hold is changing at that moment (the config feed already says something else), an S10 write would make HA show the old activity for up to 5 minutes and hide that transition from S1 and the arrester. Requiring both feeds to agree avoids writing into an unstable hold state.
- Cost: on zone_1's status/hold split (§9.7), S10 defers. D0 item 3 measures how often.

**P2. `hvac_mode == "heat_cool"`**, otherwise `DEFERRED("not_heat_cool")`. The service uses low and high as given only in AUTO (`climate.py:559-566`).

**P3. Round to whole °F** (`climate.py:218-221`).

**P4. HA-view comparison** (renamed, M1). If `|obs.low − low| ≤ 0.5` and `|obs.high − high| ≤ 0.5`, return `SKIPPED_ALREADY_CORRECT("ha_view_matches")`.
- **This is HA's copy, not cloud truth.** The displayed setpoints come from the config activity (`climate.py:222-240`).
- ha_carrier's steady-state poll every 30 min refreshes **energy only**. Status and config come from websocket deltas plus a **full read every 120 min** (`FULL_RECONCILE_INTERVAL_MINUTES = 30 × 4`, `ha_carrier/const.py:46-52`; `carrier_data_update_coordinator.py:145-160, 318-330`).
- For 5 min after any write, the post-write guard masks a cloud revert in HA (`const.py:53-59`; C16/C21).
- So P4 only saves redundant calls. The only oracle for "the thermostat holds the range" is the physical app check (L3). The retry interval (§6.1) guarantees that at least one full read happens between a write and its retry.

**P5. Funnel call** `emit_set_activity_setpoint(..., blocking=True)`.
- **No `await` between `observe` and the wire call.** `observe` and the funnel's `_snapshot_climate_state` are synchronous, and the first `await` is `hass.services.async_call`.

**P6. After-call check (LOW-2).** Re-observe once, synchronously, after the funnel returns.
- If `preset_mode != preset` or `hold_activity` changed, return `APPLIED` with `flag="possible_wrong_profile"`.
- S10 then logs one `ura_activity_log` row `action="s10_possible_wrong_profile"` (importance `notable`) with the before and after observations, and counts it as unconfirmed.
- This catches the case where the status activity changed between the service's own read and HA's state after the call.

`GenericStrategy.set_preset_range` returns `FAILED("preset_range_unsupported")` and makes zero calls. S10 logs this once per entity.

**Why the low side is the configured heat value.** On heat_cool, `target_temp_low` *is* the heat setpoint. OverrideEngine's `cool_low` (DPM sets it to `high − 7`, `dynamic_preset.py:905, 931`) has no physical meaning on this device. So the written low equals the baseline editor's "Heat Low", and the winter-away 73 °F defect is gone.

### 3.4 Restore Carrier originals when the feature is turned off (operator ruling Q2)

**Snapshot capture: when.**
- In the apply pass, at step 9: the first time S10 is about to write (zone, P) and no snapshot exists for (zone, P).
- Only after P1 and P2 hold (the zone is confirmed on P, in heat_cool), and only if the HA view differs from `desired`. If it already matches, there is nothing to restore later, so no snapshot is taken.
- The snapshot is the HA view `(round(obs.low), round(obs.high))` plus `captured_iso`.

**Snapshot capture: order.**
- Record the snapshot, then `await self.async_save_zone_state()`, then write.
- If the save raises, skip the write this tick (`DEFERRED("snapshot_not_saved")`, warning).
- So no URA edit can exist without a persisted original.

**Snapshot capture: never overwritten.**
- An existing snapshot is never replaced while it exists. This holds across later DPM changes, season changes, re-enables and restarts, so it always holds the pre-URA value.
- It is cleared only by a confirmed restore.

**Independent record.** The HA view at capture can be stale for up to one full-read interval (M1). The D0 fixture (item 1) and the operator's app notes before enabling are the independent record of the originals. L8 compares them.

**Persistence.** Side-key `__s10_preset_ranges.snapshots[zone_id][preset]` in `_build_zone_state_snapshot` (§6.3). It is rehydrated at boot.

**Restore on OFF.**
- The restore pass runs on every tick while switch 01 is OFF and any snapshot exists. It is state-driven, not edge-driven, so a restart while OFF simply continues it.
- It uses the same skip matrix (steps 1–6), the same strategy method and the same funnel, with `desired = snapshot`, `site="S10_preset_range_restore"`, `reason="restore_carrier_original"`.
- It can only restore the preset the zone is **currently on**, because the service edits the current activity. Presets are restored lazily as each zone visits them. S1 keeps pinning presets normally, so home, sleep and away are visited daily. `vacation` may wait until its next use.
- Pending restores are shown on the sensor (D6), and the NM on OFF lists them.

**Restore confirmation.**
- A restore write is followed by an HA-view check at the next attempt, which is at least `S10_PRESET_RANGE_MIN_INTERVAL_S` later (so at least one full read has happened).
- If the view matches, the snapshot is deleted and saved, and one `s10_original_restored` ledger row is written.
- If it still differs, the same retry and latch rules apply (§6.2). The latch sends NM `s10_restore_not_taking`.

**A preset URA never edited has no snapshot and is never touched.**

**Re-enable while restores are pending.** The snapshots stay (they are still the originals). Records for the affected presets are cleared (§3.5). The apply pass resumes. No re-capture happens, because snapshots are never overwritten.

**Zone deleted from URA** (`hvac.py:4044` store rewrite). Its snapshot entries are dropped, with one `s10_original_dropped_zone_removed` ledger row listing the values so the operator can restore them in the app.

### 3.5 Switch paths (LOW-3)

One coordinator method, `set_custom_ranges_enabled(value: bool, *, source: str)`, is called by all three switch paths (`switch.py:2027`, `:2035`, `:2069`, `:2097`):
- `source="user"` (turn_on/turn_off), and the value actually changes → clear every S10 **record** (value, writes, failures, latch) and save. **Snapshots are kept.** A user toggle is the documented latch discharge.
- `source="restore"` (the RestoreEntity paths at `:2069`, `:2097`) → set the flag only. Records are **not** cleared, because that would undo M3's restart-storm protection. This is a deliberate narrowing of LOW-3's wording.
- `async_turn_off` no longer clears `_last_emitted_range` (`:2037-2039`). S11/S13 own that map.
- On a user OFF, one info NM lists the pending restores: `Custom Preset Ranges is off. Putting back the original ranges on {n} presets as each zone next uses them.`

### 3.6 What S10 no longer does
- It no longer composes the house-state preset onto a zone. Retreat is S1 row-1.
- It no longer writes raw setpoints, no longer creates `manual`, and no longer writes on every tick.
- It no longer writes `_last_emitted_range` and no longer stamps suppress.

---

## 4. D0 — measure before build (first deliverable; gates the build)

Probe script: `scripts/probes/hvac_preset_profile_probe.py` (read-only, run via `ssh ha "python3 -" < ...`).

1. **Current Bryant profile per (zone, preset)** from the last 7 days of recorder data. Use samples with `preset_mode == hold_activity == P` and `heat_cool`, only those at least 125 min after any URA or human write to that zone (so they have passed a full read). Report the modal low/high and the sample count.
2. **The fixture.** Table of zone × preset: Bryant (item 1) vs URA desired, for summer now and shoulder from Oct 1. Differing cells are the writes expected on enable. This is the committed acceptance fixture, **and** the independent record of the originals for L8. The operator also notes the app's preset ranges before enabling.
3. **S10 reach.** For each zone, the share of 5-min samples where both feeds agree on a named preset. Flag any zone below 50%.
4. **Restore-writers disposition.** Episodes since v5.103.18 where a zone was established-empty but sat on a comfort preset for more than 15 min. Expected ≈0.
5. **Controlled live test of `set_activity_setpoint` (HIGH-1). Needs operator approval before it runs. BUILD GATE.**
   - **Target:** one zone, recommended zone_3 (Back Hallway). It must be on a named preset with both feeds agreeing, in heat_cool, with no nudge, borrow, AC reset or arrester window in flight (check `ac_ramp_events` and the borrows sensor). S10 is off, as it is today.
   - **Step A — edit.** From Developer Tools, call `ha_carrier.set_activity_setpoint` on the zone's climate entity with `target_temp_low` = current low and `target_temp_high` = current high **+1 °F**.
   - **Observe** `preset_mode`, `hold_activity`, `hold_until`, `target_temp_low/high` at +0, +1, +2, +5 and +10 min, and again at the first sample after the next full read (≤120 min; the ha_carrier debug log shows "forcing full refresh", or use a recorder attribute change on a non-guarded field).
   - **Operator app view** at +2 min and after the full read: screenshot showing "Holding <Preset> lo–hi+1" and **not** "Manual".
   - **URA side during the window:** no `override_detected` row, no S1 `preset_change` on that zone, no NM.
   - **Step B — revert.** The same call with the original high, then the same observation schedule.
   - **PASS (build may start):**
     - Neither feed ever reads `manual`, and `hold_until` is unchanged, at every observation of A and B.
     - The app shows the named preset with the new range after the full read (the cloud accepted it) and the original range after B.
     - No URA reaction.
   - **FAIL (any manual reading, a cloud revert after the full read, or an app showing Manual):** no build. Re-plan. Record the result in `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §3 and close its open item 6 either way.

**D0 gates:**
- Item 5 FAIL → stop.
- Items 1–2: if every cell matches, tell the operator that enabling changes nothing until DPM or the season changes it.
- Any cell >4 °F from Bryant → list it for the operator before enabling.
- Item 4 >0 → keep the restore-writers card open with the evidence.

### 4.1 D0 results
*(to be filled before build dispatch)*

---

## 5. Deliverables

### D1 — `emit_set_activity_setpoint` funnel (`hvac_setpoint.py`)

A sibling of `emit_set_temperature` (`:379-484`):
- Signature: `(hass, entity_id, *, target_temp_low, target_temp_high, freeze_active, blocking, gate, site, zone_id, reason) -> bool`.
- Steps: gate check; `apply_setpoint_guards`; synchronous snapshot; wire call `hass.services.async_call("ha_carrier", "set_activity_setpoint", {...}, blocking=blocking)`.
- Exactly one `climate_write` row (`verb="set_activity_setpoint"`) per attempted call, on the success and the raise path.
- No brand logic.

**Acceptance**
- **Test:** `test_emit_set_activity_setpoint_one_row_per_call`
- **Test:** `test_emit_set_activity_setpoint_raise_one_row`
- **Test:** `test_emit_set_activity_setpoint_gate_defers_no_call`
- **Test:** `test_emit_set_activity_setpoint_freeze_floor`
- **Test (lint):** extended `test_hvac_climate_write_funnel_completeness.py` fails on an `"ha_carrier"` service literal outside `hvac_setpoint.py`, with a self-test fixture.
- **Live:** S10 rows appear as `climate_write` with `verb=set_activity_setpoint`.

### D2 — `set_preset_range` strategy method (`hvac_strategy.py`)

As specified in §3.3 (P1–P6).

**Acceptance**
- **Verify:** status home / hold away → DEFERRED, zero calls. Status `manual` → DEFERRED, zero calls. Mode `cool` → DEFERRED.
- **Verify:** desired 75.4/70.2 vs HA view 75/70 → `SKIPPED_ALREADY_CORRECT`, zero calls.
- **Verify:** desired 74/70 vs 76/70 → one call → APPLIED.
- **Verify:** preset changes between the call and the re-observe → APPLIED with `possible_wrong_profile`.
- **Verify:** Generic → FAILED unsupported, zero calls.
- **Tests:**
  - `test_carrier_set_preset_range_requires_both_feeds`
  - `test_carrier_set_preset_range_manual_defers`
  - `test_carrier_set_preset_range_heat_cool_only`
  - `test_carrier_set_preset_range_rounds_and_skips`
  - `test_carrier_set_preset_range_applies_diff`
  - `test_carrier_set_preset_range_flags_possible_wrong_profile`
  - `test_generic_set_preset_range_unsupported`
  - `test_set_preset_range_no_await_between_observe_and_wire`

### D3 — S10 apply pass (`hvac.py`) + `borrow_live` (`hvac_preset.py`)

- Implement §3.2.
- DELETE D9 compose-away (`:3452-3528`), the S10 transient hold (`:3488-3517`), the F2 bypass (`:3563-3578`), `_dpm_composed_away_zones`, the `_last_emitted_range` write (`:3620`), the `cool − 7` baseline (`:3541`) and the suppress/unsuppress stamps (`:3581-3582, 3617-3618, 3634-3635`).
- Pull gate (e) out into `borrow_live`. `manual_guard_verdict` must return byte-identical output.

**Acceptance**
- **Verify (no fight):** zone on home/home, DPM cool_high 75 vs Bryant 76 → one S10 call. The next tick has zero S1 writes and S10 returns SKIPPED.
- **Verify (no storm):** an established-empty away zone whose profile matches, over 12 ticks → zero S10 calls (the old code made 12).
- **Verify (skip matrix):** egress / a-b / same-tick / borrow row / `_nudge_in_flight` / `_compromise_timers` / AC reset / manual / wake → zero calls each.
- **Verify (low side):** winter away 80/65 → the write is 65/80.
- **Verify:** the zone's own preset is edited, never the house-state preset.
- **Verify (M4):** an S10 edit replayed as a climate state_changed event (named preset → same named preset, new high) → **no `override_detected` row, no comfort grant, and no `_suppressed_until` entry** for the entity.
- **Tests:**
  - `test_s10_edits_profile_not_hold_no_s1_reclaim` (drives `_apply_house_state_presets`)
  - `test_s10_empty_zone_no_storm_12_ticks`
  - `test_s10_skip_matrix` (parametrised, 9 cases)
  - `test_s10_low_side_uses_configured_heat_winter_away`
  - `test_s10_acts_on_zone_preset_not_house_state`
  - `test_s10_dpm_sleep_override_applies_only_in_sleep`
  - `test_s10_edit_books_no_override_detected`
  - `test_borrow_live_extraction_verdict_identical`
- **Retired or rewritten tests** (each replaced by an assertion of the same guarantee): D9 tests in `test_zzz_hvac_conditioning_demand.py`; the S10 transient-hold tests in `test_hvac_live_room_hold_wire_in.py` (the row-1 hold tests stay); the S10 expectations in `test_freeze_floor.py`, `test_arrester_comfort_delay.py`, `test_v471_fixup_d2_d3_d4.py`, `test_hvac_w1a_site_migration.py`, `test_v478_egress_window.py`.

### D3b — Restore originals (`hvac.py`, `switch.py`)

Implements §3.4 and §3.5.

**Acceptance**
- **Verify (capture):**
  - The first write to (z, home) saves `{low, high}` from the HA view **before** the wire call. The call order is asserted: save awaited, then service call.
  - A later DPM change to (z, home) does not overwrite it.
  - A matching HA view takes no snapshot.
  - A failed save means no write.
- **Verify (restore):** switch OFF by user with a snapshot for (z, home) and the zone on home:
  - One call with the snapshot values at `site=S10_preset_range_restore`.
  - At the next attempt ≥ interval later, with a matching view → the snapshot is deleted and saved, and an `s10_original_restored` row is written.
  - A zone on `away` with only a home snapshot → no call until it is on home.
- **Verify (never-edited):** a preset with no snapshot gets zero calls while OFF.
- **Verify (restart):**
  - Rehydrate with switch ON → snapshots kept and no re-capture.
  - Rehydrate with switch OFF and snapshots → the restore pass continues.
  - Rehydrate with a latched record → still latched, zero calls.
- **Verify (toggle):**
  - A user OFF→ON clears records and keeps snapshots.
  - A RestoreEntity path clears nothing.
- **Verify (restore latch):** the view never matches → exactly LIMIT restore calls, then NM `s10_restore_not_taking`.
- **Tests:**
  - `test_s10_snapshot_saved_before_first_edit`
  - `test_s10_snapshot_never_overwritten`
  - `test_s10_no_snapshot_when_already_matching`
  - `test_s10_snapshot_save_failure_blocks_write`
  - `test_s10_restore_on_off_current_preset_only`
  - `test_s10_restore_confirm_clears_snapshot`
  - `test_s10_restore_never_edited_untouched`
  - `test_s10_restart_on_keeps_snapshots`
  - `test_s10_restart_off_continues_restore`
  - `test_s10_restart_keeps_latch`
  - `test_s10_user_toggle_clears_records_keeps_snapshots`
  - `test_s10_restore_entity_path_clears_nothing`
  - `test_s10_restore_latch_nm`
  - `test_s10_zone_removed_drops_snapshot_with_row`

### D4 — Rate bound, latch, persistence (`hvac.py`, `hvac_const.py`)

As specified in §6.

**Acceptance**
- **Verify:** a device that never takes the value → exactly 3 calls for (zone, preset, value), at least 130 min apart. At the fourth due attempt, **latch without calling** and send one NM `s10_preset_range_not_sticking`. Zero calls after that.
- **Verify:** the service raises on every call → exactly 3 attempts, then latch with NM `s10_preset_range_call_failed`. Failures do not count toward the not-sticking counter, and the reverse also holds.
- **Verify:** changing the value (DPM, baseline edit or season) resets the record and allows a write in the same tick.
- **Verify:** a user toggle discharges the latch. A restart does **not**.
- **Verify:** the write-ahead save happens before each call.
- **Tests:**
  - `test_s10_retry_interval_130min`
  - `test_s10_latch_without_call_at_limit`
  - `test_s10_failed_counted_separately_own_nm`
  - `test_s10_value_change_resets_record`
  - `test_s10_restart_storm_no_refire` (simulate 8 restarts: total calls ≤ 3)
  - `test_s10_write_ahead_save`

### D5 — User-facing text (label style guide)

Entity names are ≤3 words with the prefix kept. Config-flow text uses short phrases and plain sentences. No jargon.

| Surface | Key | New text (exact) |
|---|---|---|
| Switch name | `switch.py:1998` | **unchanged:** `01 · Custom Preset Ranges` |
| Baseline editor description | `config.options.step.hvac_baseline_presets.description` (`strings.json` + `en.json:1244`) | `Temperature ranges for each preset, by season. When Custom Preset Ranges is on, URA writes these into each thermostat's Home, Sleep, Away and Vacation presets. When you turn it off, each thermostat gets its original ranges back. Cooling must be at least 3°F above heating. To restore factory defaults, check 'Reset all to defaults' and save.` |
| DPM master helper | `...hvac_dynamic_preset.data_description.dynamic_preset_enabled` (`en.json:1231`) | `Adjusts the Home and Sleep cooling limit with the weather. Only reaches the thermostats when Custom Preset Ranges is on. Off in winter.` |
| NM title | `s10_preset_range_not_sticking` | `Preset range not taking: {zone_name}` |
| NM message | same | `URA set {zone_name} {preset} to {low}–{high}°F three times, but the thermostat kept a different range. URA has stopped trying until the range changes or Custom Preset Ranges is turned off and on. Check that preset in the Bryant app.` |
| NM title | `s10_preset_range_call_failed` | `Thermostat not responding: {zone_name}` |
| NM message | same | `URA could not reach the {zone_name} thermostat to set its {preset} range after three tries. It has stopped trying until the range changes or Custom Preset Ranges is turned off and on.` |
| NM title | `s10_restore_not_taking` | `Original range not restored: {zone_name}` |
| NM message | same | `URA tried three times to put {zone_name} {preset} back to {low}–{high}°F. Please set it in the Bryant app.` |
| NM (info, on user OFF) | `s10_restore_pending` | Title `Putting original ranges back`; message `Custom Preset Ranges is off. Putting back the original ranges on {n} presets as each zone next uses them.` |
| Switch docstring | `switch.py:1975-1988` | Explain that it writes URA's ranges into the thermostat's own presets (no hold); that turning it off restores the originals as each preset is next used; and give the real entity id. |

**Acceptance**
- **Test:** strings/translations parity.
- **Test:** `test_label_no_jargon_s10_strings` fails if any new string contains "DPM", "override", "hold", "throttle", "S10" or "latch".
- **Live:** the options flow shows the new description.

### D6 — Diagnostics (`sensor.py` `HVACActivePresetOverridesSensor`)

New attributes:
- `preset_range_by_zone`: `{zone_id: {preset: {desired_low, desired_high, status, reason, writes, failures, latched, last_write_iso}}}`.
- `originals_pending_restore`: `{zone_id: {preset: {low, high, captured_iso}}}`.

Also a docstring line on `resolved_ranges` (it shows the engine's opinion; the written low is the configured heat).

**Acceptance**
- **Test:** `test_active_preset_overrides_sensor_exposes_s10_record_and_originals`.
- **Live:** both attributes are filled within 2 ticks of enabling.

### D7 — Docs in the same commit

- **State-of-play:**
  - Header.
  - §1.
  - §3.2 (remove the D9 consumer).
  - §3.3.
  - §4.1 (new funnel).
  - §4.2 (S10 row, including the restore site).
  - §5 (`set_activity_setpoint` used by S10, with the D0-5 result).
  - §9.7 closed.
  - §11 row 5.
- **`THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §3:**
  - Adopted for S10 standing ranges, with a persisted snapshot and restore-on-off (§3.4 of this plan). That satisfies §3's rule even though this is not a borrow.
  - Close open item 6 with the D0-5 evidence.
- **README** `README_v5.103.x.md` with a Validated table.

### D8 — Switch default OFF (LOW-6; conditional on operator §13 Q4)

Today the default is ON: `hvac.py:540` (`True`), `switch.py:2021-2022`, and `sensor.py:10203, 10235` (`getattr(..., True)`). If approved, change all four to False, so a fresh install or lost restore-state cannot turn the feature on.
- There is no live effect, because the restored state `off` exists.
- **Test:** `test_custom_preset_ranges_default_off` (no last state → off; the coordinator attribute is False).

---

## 6. Numbers, rate model, persistence

### 6.1 Constants (knob ladder)

| Name | Value | Rung | Why this rung | Why this value |
|---|---|---|---|---|
| `S10_PRESET_RANGE_MIN_INTERVAL_S` | **7800** (130 min) | 1 (`hvac_const.py`) | A Carrier cloud call-rate bound, governed like `HVAC_DECISION_TICK` (`hvac_const.py:11-13`). | Must be at least `FULL_RECONCILE_INTERVAL_MINUTES` (120) plus the post-write guard (5) plus 5 slack. Any 120-min window after a write contains at least one full read, and the guard has expired, so a retry is judged on an HA view that has been refreshed from the cloud at least once. It is still not an oracle (M1). |
| `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` | 3 | 1 | same | Covers a lost write plus a transient error; more means the device will not take it. Also used as the separate FAILED limit. |

Switch 01 is the kill switch.

### 6.2 Rate and latch model (M2)

The record is keyed by `(zone_id, preset, mode)`, where mode ∈ {apply, restore}:

```
{value:[lo,hi], writes:int, failures:int, latched:bool, latch_reason:str|None, last_attempt_iso:str|None}
```

- **The value differs from the record** → reset the record to this value. The **first write of a new value is allowed immediately.**
- **`latched`** → no call.
- **Retry of the same value** (a previous attempt exists) → allowed only if `now − last_attempt ≥ MIN_INTERVAL`.
- **At a due retry:** if `writes == LIMIT` and the HA view still differs, then `latched = True`, `latch_reason = "not_sticking"`, send one NM, and **make no call**.
- **Otherwise** write ahead: increment the attempt, set `last_attempt_iso`, `await` save, then call:
  - APPLIED → `writes += 1`.
  - FAILED → `writes` unchanged; `failures += 1`. If `failures == LIMIT`, latch with `latch_reason="call_failed"` and send its own NM.
  - DEFERRED (the gate or the precondition deferred) → roll back the attempt stamp (no call was made), and do not save.
- **`SKIPPED_ALREADY_CORRECT`** → no call. The counters are **not** reset, so a guard-masked match cannot re-arm an endless loop. In restore mode, if `last_attempt ≥ MIN_INTERVAL` ago, this confirms the restore (§3.4).
- **Discharge:** the value changes; a user toggle of switch 01 (§3.5). **Not** on restart.

### 6.3 Persistence (M3)

`_build_zone_state_snapshot` (`hvac.py:2081-2103`) gains:

```
"__s10_preset_ranges": {
  "snapshots": {zone_id: {preset: {"low": float, "high": float, "captured_iso": str}}},
  "records":   {zone_id: {"<preset>|<mode>": {record fields above}}}
}
```

- It is rehydrated in a new `_rehydrate_s10_state(stored)`, called next to `_rehydrate_arrester_state` (boot load, `hvac.py:1059`). Wall-clock ISO timestamps are used (monotonic time does not survive a restart).
- Saves:
  - The snapshot save before the first edit is awaited.
  - Each attempt is saved before its call (write-ahead, awaited; S10 writes are rare).
  - Confirmations and latches are saved by scheduling (`schedule_zone_state_save`).
- The zone-delete rewrite (`hvac.py:4044-4081`) prunes the deleted zone's entries (§3.4).

**Budget against Carrier constraints.** One call is one `set_config_activity` (`climate.py:580-590`). The old path was 2 calls plus S1's resume + pin (≥2).

| Scenario | Old S10 (switch ON) | New S10 |
|---|---|---|
| Steady state | ~48 calls/h per empty zone | **0** |
| Enable | storm | ≤ D0 differing cells (≤4/zone), each as its preset is visited |
| DPM change (dwell ≥60 min) | raw write + reclaim | ≤1 per affected preset at its next visit |
| Season boundary | — | ≤4/zone |
| Device refuses | unbounded | ≤3 per (zone, preset, value, mode) **across restarts**, then latch |
| Turn off | — | ≤ the number of snapshots, each ≤3 |

---

## 7. Invariants and live validation

### 7.1 Invariants

> **INV-S10.** With switch 01 ON, every S10 wire call is `ha_carrier.set_activity_setpoint`, issued only while `preset_mode == hold_activity == P ∈ {home, sleep, away, vacation}` in heat_cool, and never for a zone with a live borrow, person-protected hold, arrester comfort window, AC reset, egress pause, or same-tick S1 write. S10 never changes hold state, so it never creates `manual`, and S1 never reclaims a zone because of S10.

> **INV-RATE (reworded, LOW-7).**
> - For any (zone, preset, mode, value), the count of S10 wire calls **summed over any number of HA restarts** is ≤ `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` successful plus ≤ `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` failed.
> - Any two calls for the same value are ≥ `S10_PRESET_RANGE_MIN_INTERVAL_S` apart.
> - The only things that re-open the budget are a change of value or a user toggle of switch 01.

> **INV-RESTORE.** For every (zone, preset) URA has edited, a persisted original exists from before the first edit until a confirmed restore. With switch 01 OFF, no preset without a snapshot is ever written.

**Falsifier queries** (one-shot, `ura_activity_log`):
- Q1: S10 rows (both sites) with `verb != 'set_activity_setpoint'` → 0.
- Q2: S10 rows with `values_before.preset_mode != values_before.hold_activity`, or with `manual` → 0.
- Q3: `preset_change` rows with `manual_class='zero_delta_ura'` on a zone within 15 min after an S10 row, with no other URA write in between → 0.
- Q4: count per (zone, site, `values_after`) → ≤ 3 (≤ 6 counting failures).
- Q5: `override_detected` rows within 2 min after an S10 row on the same zone, with no preset transition → 0.
- Q6: `s10_possible_wrong_profile` rows → 0 expected. Any row is investigated.

**Discrimination: fix vs failure**

| Observation | Fix | Old / fight | Old / storm | Wrong-profile edit |
|---|---|---|---|---|
| S10 verb | `set_activity_setpoint` | `set_temperature` | `set_temperature` | `set_activity_setpoint` |
| Preset after write | unchanged, named | `manual` | `manual` | unchanged |
| S1 `zero_delta_ura` after | none | once | every tick | none |
| S10 rows/h, empty zone | 0 | 0 after first | ~12 | ≤ 1 |
| Bryant app | "Holding Home 70–75" | Manual, then old range | alternating | range on the wrong preset (Q6 + app) |

### 7.2 The enable step (operator action; exact knobs)

Prerequisites: D0 item 5 PASS, deploy, HACS install, restart, and fixture review. Note the app's current preset ranges.
1. **Turn ON `switch.ura_hvac_coordinator_guest_mode_actuation`** ("URA: HVAC Coordinator — 01 · Custom Preset Ranges"). Run L1–L6 and L8.
2. **Turn ON `switch.ura_energy_coordinator_dynamic_preset_overrides`** ("02 · Dynamic Preset Auto-Adjust"). Run L7.
   - Optional: open options → HVAC → Dynamic Preset and save, so the stored option matches.
3. **Restore drill (L9)**, at the operator's choice, in the same session or deferred to the first real turn-off: turn 01 OFF, verify, turn it back ON.

### 7.3 Live checks

| # | Check | Oracle | PASS if |
|---|---|---|---|
| L1 | Rows only for differing cells of current presets | `climate_write` `site=S10_preset_range` | the set of rows = the differing fixture cells; `values_after` = the fixture |
| L2 | Zone stays named | `preset_mode` and `hold_activity` 10 min after each row | unchanged, never `manual` |
| L3 | **The thermostat holds the range** | **Only oracle: the operator reads the Bryant app** after the next full read (≥125 min after the write): "Holding <Preset> lo–hi" and not Manual. The HA view is corroboration only (M1). | the app matches `values_after` |
| L4 | No fight | Q3 | 0 |
| L5 | No storm, no false override | Q1, Q4, Q5 | 0 / ≤3 / 0 |
| L6 | Borrows unaffected | the next soft nudge returns to the named preset with the custom range; no S10 row during it | as stated |
| L7 | Weather reaches the profile | the bucket/range sensors plus an S10 row with `reason=preset_range_dpm` at the next Home/Sleep visit, or a documented skip reason | as stated |
| L8 | Originals captured correctly | sensor `originals_pending_restore` vs the D0 fixture item 1 and the operator's app notes | equal per cell |
| L9 | Restore works | after OFF: `site=S10_preset_range_restore` rows as each preset is visited; the **app** shows the originals; the snapshots drain | as stated |

Proven only in-suite: latch/NM (D4), restart-storm bound, winter low side, restore latch.

---

## 8. Supersession

| Item | File:line | Bucket | Superseded by | Reason |
|---|---|---|---|---|
| D9 compose-away | `hvac.py:3452-3528` | DELETE | row-1 preset retreat + W1-B presets-only returns | The corrector is no longer needed; it is the storm source |
| F2 bypass | `:3563-3578` | DELETE | the rate model | Storm |
| S10 transient hold | `:3488-3517` | DELETE | — | It only held D9's retreat |
| `_dpm_composed_away_zones` | `:3522-3526` | DELETE | — | No readers |
| `cool − 7` baseline at S10 | `:3541` | DELETE | configured heat | Bug Class #63 |
| suppress/unsuppress at S10 | `:3581-3582, 3617-3618, 3634-3635` | DELETE | arrester's named-preset ignore (M4) | Would blind genuine manual detection |
| `_last_emitted_range` S10 write + switch clear | `:3620`; `switch.py:2037-2039` | DELETE | — | S11/S13 keep the map |
| `_last_emitted_range` map | `hvac.py:543` | KEEP + DOCUMENT | — | Live S11/S13 consumers |
| `hvac_predict` `cool − 7` fallback | `hvac_predict.py:908-918` | KEEP + WIRE — **separate card `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` (operator ruling Q3)** | — | Not in this build |
| OverrideEngine `cool_low` | `preset_overrides.py:60` | KEEP + DOCUMENT | — | Ignored at actuation |

---

## 9. Card dispositions
- `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` → **done** on ship. Evidence: live Q1/Q4.
- `HVAC-S10-DPM-VS-S1-1` → **done** on ship. Evidence: Q2/Q3. Operator constraint honoured.
- `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` → verify-and-close on D0 item 4. The premise was removed by W1-B D2.4 (`hvac_override.py:5041, 6276, 6750`; `hvac_predict.py:984, 1542`) together with row-1. **The `FOLD_2026_09_17` item (EC coast/shed offset path) stays open.**
- **New cards:**
  - `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` (operator Q3; the orchestrator mints it)
  - `HVAC-DPM-OPTION-VS-SWITCH-SPLIT-1`
  - The DPM range sensor display, folded into the first card.

---

## 10. Test authority (builder + Reviewer C)

- **T1.** Every skip, precondition and counter branch is mutation-anchored: neuter it and a named test fails. Restore and check `git status`. Bytecode off, `__pycache__` cleared.
- **T2.** The fight and restore tests drive `_apply_house_state_presets` (the enclosing method).
- **T3.** Neuter P1 → the both-feeds test fails.
- **T3b.** Neuter the `hold_activity` half only → `test_carrier_set_preset_range_requires_both_feeds` still fails (it has a status=home / hold=away case).
- **T4.** Neuter rounding → the rounding test fails and the latch test shows its limit reached earlier.
- **T5.** Insert an `await asyncio.sleep(0)` between observe and wire → the no-await test fails.
- **T6.** Re-add a `suppress()` stamp → `test_s10_edit_books_no_override_detected` fails. The test asserts the `_suppressed_until` key is absent, and that a genuine human manual transition 5 s later is booked.
- **T7.** Delete the write-ahead save → `test_s10_restart_storm_no_refire` fails. Delete the snapshot-before-write order → `test_s10_snapshot_saved_before_first_edit` fails.
- **T8.** Fixtures use the real `PresetManager`, real CM options shapes, and a real `Store` round-trip for the side-key. The mock service edits only the status-named activity, as `climate.py:551-596` does.
- **Suite:** `PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/ -v`, serial. Compare test names against the `pre-review` baseline.

---

## 11. Tier and review

**Tier 2-DB** (three framing-disjoint build reviews + live validation + README write-back). It is elevated from the card's Tier 2 under the standing regression-prone policy:
- a new writer verb;
- a deleted corrector path;
- new persisted state;
- adjacency to S1 / nudge / arrester precedence.

It is **not Tier 3**: there is one emission site with two modes, and the preconditions live in one function. The operator may elevate.

- **Plan re-review:** one pass over the REV 2 delta table plus §3.4 / §6.
- **Build reviews:**
  - **A — correctness and edge cases:** P1–P6, rounding, guards, low side, season/DPM gates, snapshot capture rules, restore current-preset-only.
  - **B — cross-coordinator, lifecycle, no-flap:** S1 same-tick, the borrow family, arrester (no stamp), the ha_carrier guard vs the 130-min retry, the switch source paths, restart/rehydrate, zone delete, S11/S13 map.
  - **C — test authority by real per-site mutation:** T1–T8, lint.
- **Pre-deploy:** `pre-review-v5.103.x` tag and the zero-bugs gate.
- **Post-deploy:** HACS check → the enable step (§7.2) → L1–L9 → README Validated table and state-of-play in the same commit.

---

## 12. Non-goals

- No new EXCURSION_KIND. No change to `begin_excursion` / `return_excursion` / `hvac_excursion.py`.
- **The new funnel is W1-A-sanctioned and does not conflict with W1-B's constraint.**
  - W1-A: `PLANNING_hvac_w1a_thermostat_write_governance.md:363` — "if Stage B adopts it [`set_activity_setpoint`], that funnel gets a row shape then."
  - The W1-B constraint "nothing added to the `emit_*` funnels" (`hvac_strategy.py:7-8`; state-of-play §9e) forbids adding **decision logic** to the **existing** funnels.
  - `emit_set_activity_setpoint` is a new verb funnel with the same behaviour-neutral shape: the existing `gate=` parameter only, no brand or gate logic. All S10 rules live at the S10 site and in the strategy. `emit_set_temperature` / `emit_set_preset_mode` / `emit_set_hvac_mode` are untouched.
- No change to S1's four gates or `should_change_preset`.
- Nudges stay on `set_temperature` (integration plan §5 decision 1).
- No heat-side weather adjustment. No guest-override producer. No entity_id rename.
- No non-Carrier support. No `wake` preset.
- No fix for zone_1's status/hold split (S10 defers there; `HVAC-WRITE-CONFIRMATION-ORACLE-1`).
- **No change to the `hvac_predict` `cool − 7` fallback** (operator Q3 → `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1`). Review LOW-4's suggestion to fold it in is declined per that ruling.
- No Bryant schedule changes.
- No forcing a zone onto a preset in order to restore it (that would fight S1). Restores are lazy.

---

## 13. Open questions for the operator

Q1–Q3 are answered (rulings below). Still open:

4. **Switch default (LOW-6).** Today a fresh install, or a lost restore-state, turns Custom Preset Ranges **ON**. Change the default to OFF? *(Recommendation: yes. Live is unaffected.)*
5. **D0 item 5 approval.** OK to run the controlled +1 °F edit-and-revert on zone_3, at a quiet time, with your app screenshots at +2 min and after the next full read (≤2 h)? This is the build gate.

## Operator rulings 2026-09-27 (verbatim, pre-build)
- **Q1 (app edits vs URA):** "Won't the app just reflect the new preset? Yes Ura wins." — Yes: the Carrier app shows URA's edited temperatures inside each named preset. While CPR is on, URA wins; stop + NM after 3 unconfirmed tries stays.
- **Q2 (turning CPR off):** "If we turn of cpr, it should go back to the default ranges inset right?" + picked **Restore Carrier originals**. BUILD CHANGE: before URA first edits a zone's named preset, snapshot the original Carrier range for that preset (persisted, per zone x preset); when switch 01 turns OFF, write each snapshotted original back once (same write path, confirmation + NM on failure) and clear the snapshot. Restart while ON keeps snapshots; a preset URA never edited is not touched.
- **Q3 (the minus-7 heat bug in the hvac_predict restore fallback):** **Separately** — carded, not in this build.

## Operator answers to questions 4-5 (2026-09-27 ~22:25, verbatim)
- **Q4 switch default:** "Default OFF (Recommended)" — D8 proceeds.
- **Q5 D0 item 5 live test:** "Run it in zone 3. Btw don't deploy after building until I say so" — test target zone_3; **the CPR build must NOT be deployed until the operator says so** (hold after build + reviews).

## D0 item 5 — live test log (zone_3)
- 22:33:0x CDT 2026-09-27: `ha_carrier.set_activity_setpoint` on `climate.back_hallway_zone_3` while on named preset **away** (both feeds away, 66/80): target_temp_low 66, target_temp_high 81.
- +0 (HA): preset_mode away, hold_activity away, hold_until None, 66/81.
- +1 min (operator app screenshot 22:34): Zone 3 "66 - 81 · Holding Away" — named preset retained, NOT manual.
- Pending: through the next full config read (≤ 120 min, ~00:35) — pass = still away/away, no manual, app still "Holding Away" 81; then revert to 80 via the same service.
- +31 min (22:37): unchanged, away/away, no hold_until, 66/81.
- **Bonus evidence (unplanned):** at 23:04:50 URA switched zone 3 away -> sleep (house_state_transition), showing sleep's own 70/77; at 23:24:51 URA switched it back sleep -> away (vacant_past_grace) and the zone came back at **66/81** — the edited value is stored IN the away profile and survives a preset round-trip; neither switch produced `manual`.
- **RESULT (read 2026-09-28 08:26 CDT, ~10 h): PASS.** Zone 3 never read `manual` (0 rows) across ~10 h, multiple Carrier full reconciles (> 120 min) and 5 URA preset round-trips (away->sleep->away, away->home->away). Every return to away showed the edited 66/81, so the edit lives in the away profile and survives full reads. Gate for the CPR build is MET. Revert pending: `set_activity_setpoint` edits the CURRENT activity, so the away profile goes back to 80 the next time zone 3 is on away.
- **Reverted 2026-09-28 08:3x CDT:** zone 3 on away (house away) — `set_activity_setpoint` 66/80; result away/away, no hold, 66/80. Test closed.
