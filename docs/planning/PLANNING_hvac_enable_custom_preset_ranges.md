# PLANNING — Enable Custom Preset Ranges (D9 / `guest_mode_actuation`, HVAC arc step 5)

**Status:** PLAN **REV 3** (2026-09-29). Not built. Batch C parent card `HVAC-CUSTOM-PRESET-RANGES-1` (children `HVAC-S10-DPM-VS-S1-1`, `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`, `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`). Build zone_3 first. **Do NOT deploy after building until the operator says so** (operator 2026-09-27 Q5).

**Operator ruling (2026-09-27):** "yes", the operator wants the feature. URA wins over app edits. Carrier originals are restored when the feature is turned off. The heat-bug fallback is handled separately (shipped v5.103.22).

**Arc position:** `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §11 row 5.

**Cards resolved on ship:** `HVAC-S10-DPM-VS-S1-1`, `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` (both folded into D3 by construction, not by a separate deliverable). Disposition of `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` in §9; verify against D0 item 4 + Batch B/D restore-writer changes.

**Version:** next free `5.103.x` PATCH after Batch B/D land on `develop`.

---

### REV 3 changelog (2026-09-29) — what changed since REV 2

REV 3 was produced by re-reading `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full (589 lines: Batch B v5.103.21-23 entries at the top; Batch D v5.103.24/25; §4.2 W1-A funnel table; §7 arrester ↔ AC-reset interplay; §9e "person interrupts"; §10 C25-C29 corrections ledger; §11 W1-C position at step 5) and re-greping every write site the REV 2 plan cited on current `develop`. **The plan's behaviour is unchanged. What moved is (a) file:line anchors, (b) two new mandatory skips CPR must inherit, (c) tier framing, (d) explicit Carrier-profile scoping for the coming W1-C generic-thermostat cycle, (e) explicit fold of the three blocker cards as deliverables.**

**1. Every `hvac.py` line number in REV 2 is STALE.** Batch B v5.103.23 + Batch D v5.103.24 inserted ~500 lines above S10. Re-verified by grep on `develop` @ 2026-09-29:

| REV 2 cite | Current | Symbol |
|---|---|---|
| `hvac.py:540` | `hvac.py:664` | `_guest_mode_actuation_enabled` (default `True`) |
| `hvac.py:543` | `hvac.py:667` | `_last_emitted_range` map init |
| `hvac.py:3317-3320` | `hvac.py:3849` | `await self._async_apply_preset_overrides()` (S10 call, tail of `_apply_house_state_presets`) |
| `hvac.py:3373-3638` | `hvac.py:3906-4171` | `_async_apply_preset_overrides` (S10 method) |
| `hvac.py:3390` | `hvac.py:3923` | switch gate `if not self._guest_mode_actuation_enabled: return` |
| `hvac.py:3416` | `hvac.py:3949-3951` | `get_preset_for_house_state(self._house_state)` |
| `hvac.py:3452-3528` | `hvac.py:3985-4067` | D9 compose-away block |
| `hvac.py:3488-3517` | inside `hvac.py:3985-4067` | S10 transient hold (compose-away transient) |
| `hvac.py:3522-3526` | `hvac.py:4055-4056` | `_dpm_composed_away_zones` counter |
| `hvac.py:3541` | `hvac.py:4074` | `baseline_low = baseline_cool - 7.0` (Bug Class #63) |
| `hvac.py:3563-3578` | `hvac.py:4096-4111` | F2 throttle bypass (`if last == resolved_pair and not _compose_away: continue`) |
| `hvac.py:3581-3582`, `:3617-3618`, `:3634-3635` | `hvac.py:4114-4115` (`suppress(kind="temp")`), `hvac.py:4150-4151` (`unsuppress` roll-back) | arrester suppress stamps to DELETE (M4) |
| `hvac.py:3598-3609` | `hvac.py:4131-4142` | `emit_set_temperature(... site="S10_dpm_apply" reason="dpm_preset_apply")` (raw setpoint write to REPLACE) |
| `hvac.py:3620` | `hvac.py:4153` | throttle-map write `_last_emitted_range[zone_id] = resolved_pair` (to DELETE for S10) |
| `hvac_preset.py:333` (v3.8.0-era) | `hvac_preset.py:234` (`manual_guard_verdict`), caller `:365` | unchanged behaviour post W1-B; `borrow_live` extraction still valid |
| `hvac_preset.py:293-317` (gate e) | `hvac_preset.py:234-345` region | inline gate (e) inside `manual_guard_verdict`; `borrow_live(zone_id)` factoring still valid |
| `hvac_setpoint.py:127-160, :163+, :258` | present, plus **`emit_set_hvac_mode` at `hvac_setpoint.py:813-859`** (shipped v5.103.16, sibling to model for `emit_set_activity_setpoint`) | funnel helpers |
| `ha_carrier/climate.py:91-104, :467-537, :539-596` | verified unchanged in installed v2.28.4 (state-of-play §5, C15) | `set_activity_setpoint` is upstream, HACS-safe |

**Action for the builder:** treat the REV 2 site labels (S10, F2, compose-away, cool-7, etc.) as the source of truth for **what** changes; use the table above for **where**. Re-grep before touching (`_async_apply_preset_overrides`, `_dpm_composed_away_zones`, `_last_emitted_range`, `_guest_mode_actuation_enabled`, `suppress(zone.climate_entity, kind="temp")`) — the block is dense and future patches will shift it again.

**2. NEW SKIP — unavailable/unknown climate entity (from Batch D v5.103.24).** Batch D shipped `HVACCoordinator._climate_unreadable(zone_id, zone)` at `hvac.py:2382-2411` (backed by `HVAC_CLIMATE_UNREADABLE_STATES` in `hvac_const.py`) with one INFO + one `climate_write_held_unreadable` ledger row per outage EPISODE (opened on the first unreadable read, closed on the first readable one). S1 consults it at `hvac.py:3555`; the B1 heat_cool enforcer at `hvac.py:2581`. **CPR MUST consult it too**, at the same episode granularity — the incident that carded it (`HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1`) was 37 pointless `set_hvac_mode` writes on zone_1 during a 177-min ha_carrier outage; a CPR `set_activity_setpoint` against an unavailable entity is worse — it will either raise (chewing the retry budget for nothing) or silently no-op (locking the entity into `latched=True` with `latch_reason="call_failed"` for a fault that isn't the device's).

- **Added to §3.2 skip matrix as step 0.5:** `self._climate_unreadable(zone_id, zone)` → `continue` (no snapshot capture, no wire call, no counter increment, no rate-clock consumption). One `climate_write_held_unreadable` row per outage episode as the existing helper writes; do NOT open a second episode. Test: `test_s10_defers_when_climate_unreadable` (state = `unavailable`, expects zero wire calls and zero snapshot rows).

**3. NEW SKIP — interrupt latch (from Batch B v5.103.23 D2 + fix-up 2 N1).** Batch B introduced a persisted, level-triggered latch that blocks S12/S13 begins on a zone until it leaves manual (`OverrideArrester._latch_state_discharges`, side-key `__interrupt_latch`, state-of-play §9e). CPR does not begin an excursion, but it IS a preset-scoped write on a zone the person JUST fought URA on. **Rule:** while the zone is interrupt-latched, CPR defers (no wire call, no snapshot capture). Rationale: editing the same preset's profile mid-latch is exactly the surprise the latch exists to prevent — the person's change discharges the latch when they visit a named preset; until then, URA holds still.

- **Added to §3.2 skip matrix as step 3.5:** query the coordinator's latch predicate (grep `_interrupt_latch`, `latch_level_check`, `_latch_state_discharges`) → `continue`. Test: `test_s10_defers_when_interrupt_latched` (latch set on zone, expects zero wire calls; latch discharged, next tick allows the write).

**4. S6/S7 INFO-1 interaction (state-of-play §4.2, Batch D) — NO plan change; noted so reviewers do not treat it as a defect.** When a person's change ended a NON-nudge borrow the nudge was running on top of, S6 is skipped and S7 pins the S1 target preset (or the arrival target for a pre-arrival). Once CPR ships, the S1 target preset's profile CARRIES URA's edited range — S7's pin puts the zone on that named preset and the profile IS the range. No conflict, no extra write. Under person-protection at restore (fix-up 1), S6 restores the person's own setpoints (raw HUMAN_MANUAL), NOT the CPR profile — that is correct and outside CPR's remit.

**5. Blocker fold — explicit deliverable disposition** (see §9 for detail):

- **`HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`** → resolved by D3's DELETION of the compose-away block (§8 table). No separate deliverable; test `test_s10_empty_zone_no_storm_12_ticks` (D3) is its evidence. The kanban card's proposed solutions (edge-triggered `_last_emitted_range` invalidation OR ground-truth setpoint compare) are BOTH refused as unnecessary: the storm only exists because compose-away exists; when compose-away is deleted, the storm cannot recur.
- **`HVAC-S10-DPM-VS-S1-1`** → resolved by §3.1 core move (S10 edits the named profile via `set_activity_setpoint`, never a raw setpoint; the zone never goes to `manual`; S1 has nothing to reclaim). No separate deliverable; tests `test_s10_edits_profile_not_hold_no_s1_reclaim` + `test_s10_edit_books_no_override_detected` (D3, M4) are its evidence. The card's "solution (a)" (`begin_excursion(kind=DPM)`) is refused — it violates the operator constraint on `begin_excursion` (state-of-play §9e; W1-B REV 5). "Solution (b)" (per-tick `_s10_write_this_tick` flag consumed by gate (e)) is also refused — the flag would be a false positive for the four gates, and the fight only exists because S10 today writes raw setpoints; removing the raw write removes the fight.
- **`HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`** → verify-and-close on D0 item 4 (episodes since v5.103.18). The card's premise (S8/S9/S11/S13 restores strand empty zones because D9 was their corrector) is refuted by W1-B D2.4 presets-only returns (state-of-play §4.2) AND Batch B v5.103.23 pre-arrival S12 lifecycle (foreign-row guard at S12/S13; presets-only ends; no `_last_emitted_range` write on pre-arrival ends). Its `FOLD_2026_09_17` residual (EC coast/shed offset apply path — verify FIX-B2-style pre-write preset snapshot + `set_preset_mode` restore, like the nudge path) stays open as a separate concern; not blocking on CPR.

**6. Tier — Tier 2-DB confirmed; NOT elevated to Tier 3.** See §11 for the full argument. Short version: CPR is regression-prone (three framing-disjoint reviews mandatory under the standing rule) but does not thread a value through many emission sites — there is ONE emission site with two modes (apply + restore), ONE strategy method (`CarrierStrategy.set_preset_range`), ONE persisted snapshot store (`__s10_preset_ranges`). The falsifiable invariant (INV-RESTORE) is single-surface. **However, REV 3 pulls in one Tier-3 discipline as a standing requirement: the orchestrator personally re-greps every wire-call site and every consumer of the persisted snapshot before deploy** (state-of-play §11 Tier-3 rule; feedback `orchestrator_stays_in_main_checkout`). Rationale: the snapshot IS the operator's ONLY path back to Carrier defaults if they turn CPR off; a bug in the snapshot store is unrecoverable without their app. **If the operator prefers full Tier 3** (four framing-disjoint reviews including an adversarial-completeness pass D that re-enumerates the entire invariant surface INCLUDING pre-existing code), they may elevate — recommend YES only if D0 item 5 (already PASSED zone_3 2026-09-28) had surfaced unexpected Carrier behaviour. It did not; Tier 2-DB stands.

**7. Carrier-specific vs profile-agnostic scoping (new §14).** `HVAC-W1C-GENERIC-THERMOSTAT-1` trigger fired 2026-09-29 (operator: "Not everyone has a Bryant variable speed. As I roll this out to more homes"). REV 3 explicitly enumerates which CPR pieces are Carrier-specific and how the strategy layer already accommodates a generic thermostat, so W1-C can land as a thermostat-profile capability without unwinding CPR. See §14. **No CPR piece hard-codes Carrier assumptions ABOVE the strategy line.**

**8. Read-first attestation refreshed** (see below).

---

## Read-first attestation

- I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely (589 lines on `develop` @ 2026-09-29), including the Batch B v5.103.21-23 header block, the Batch D v5.103.24/25 header block, §3.2 (zone rollup, D5 transit filter), §4.1 (funnels including `emit_set_hvac_mode`), §4.2 (every write site, S6/S7 INFO-1, unreadable-thermostat guard), §4.2b (Fan Mode; unrelated), §4.3 (ledger coverage post W1-A), §5 (Carrier facts, `set_activity_setpoint` upstream), §6 (borrows, human-interrupt rulings), §7 (arrester + AC-reset interplay, C28/C29 supersession snapshots), §9e ("person interrupts, we end and revert" and the four S1 gates), §10 C1-C29 corrections ledger, §11 W1-C position at step 5.
- W1-B shipped v5.103.18: the v3.8.0 S1 manual guard was replaced by four gates (a/b person-protected, c arrester grace/compromise, d arrester disabled, e live borrow); borrow returns are presets-only.
- W1/W2 finish (Batch B, v5.103.23, built not deployed) shipped D1 within-manual detection with a URA-last-4-writes RAM record inside `emit_set_temperature`; ended BANKING/PREHEAT/ownerless COMPROMISE on human interrupt with no write; added the interrupt latch and its persistence + level discharge.
- Batch D (v5.103.24, built not deployed) shipped Fan Mode, the unreadable-thermostat guard on B1/S1, INFO-1 nudge-restore behaviour, arrester ↔ AC-reset separation (`_cancel_arrester_timers` no longer cancels reset restore).
- This plan re-asserts nothing in §10 (C1-C29), and in particular:
  - It does not rely on the retired v3.8.0 guard (C25).
  - It does not treat `hold_activity` as a universal oracle (C20/C22/C23).
  - It does not use 42-79 s as Carrier's schedule (C16).
  - It does not call `set_activity_setpoint` a local patch (C15).
  - It does not claim ha_carrier re-sends anything to the cloud (C21).
  - It does not remove the `hvac_excursion.py` `_auto_return` manual-skip (C26; SUPERSEDES the REV 2 assumption that W1-B made it dead).
  - It does not pin `manual` in a boot audit / S4 revert (C28/C29).
- Both blocker cards were read in full, including the operator constraint added 2026-09-27: *no new EXCURSION_KIND and no logic inside `begin_excursion` without a ruling; prefer S1-side reads.* This plan touches neither `hvac_excursion.py` nor the excursion kinds.
- The CPR parent card `HVAC-CUSTOM-PRESET-RANGES-1` (kanban `HVAC-CUSTOM-PRESET-RANGES-1`, created 2026-09-29 13:10) explicitly requires re-check against v5.103.23 (Batch B touched the same write paths); this REV 3 is that re-check.

---

### REV 2 delta (retained for the re-reviewer)

| Finding | Where fixed |
|---|---|
| HIGH-1: controlled live test of `set_activity_setpoint` before build | §4 D0 item 5 (build gate; PASSED zone_3 2026-09-28) |
| M1: wrong confirmation rationale (config re-read every 120 min; the post-write guard hides reverts) | §3.3 P4 renamed "HA-view comparison"; §6.1 interval re-derived (130 min); §7.3 L3 physical app check is the only oracle |
| M2: latch rule; FAILED counted separately | §6.2 |
| M3: persistence across restarts | §6.3 (`__s10_preset_ranges` side-key, write-ahead save) |
| M4: drop `suppress(kind="temp")` | §3.2 step 10, §2.1 row; test `test_s10_edit_books_no_override_detected` |
| LOW-1: P1 rationale; keep the `hold_activity` check? | §3.3 P1 (kept, with the real reason) |
| LOW-2: after-call preset check | §3.3 P6, `possible_wrong_profile` |
| LOW-3: clear records on switch paths | §3.5 (user transitions clear; restore paths do not, with reason) |
| LOW-4: fix the heat fallback here | **Not folded.** Operator ruling Q3: handled separately (SHIPPED v5.103.22, card `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` DONE) |
| LOW-5: full list of preset-range consumers | §2.7 |
| LOW-6: switch default ON → OFF | D8 (operator answered YES 2026-09-27) |
| LOW-7: reword INV-RATE | §7.1 |
| New-funnel sanction line | §12 |
| Operator Q2: restore Carrier originals | §3.4 (full spec) + D3b + tests |

---

## STEP 0 — what the feature is today, and the real knob

### Q1. What does the feature do today, and why was it dormant?

The only actuator is `HVACCoordinator._async_apply_preset_overrides` (site **S10**, `hvac.py:3906-4171` — REV 2 cited `:3373-3638`; see REV 3 changelog table). It is called at the end of `_apply_house_state_presets` (`hvac.py:3849` — REV 2 cited `:3317-3320`), in the same tick and right after S1. It returns immediately when `_guest_mode_actuation_enabled` is False (`hvac.py:3923` — REV 2 cited `:3390`).

When the switch is ON, S10 does this for every zone on every tick:
1. It takes the **house-state** preset (`hvac.py:3949-3951`). The exception is D9 compose-away, which swaps in `away` for established-empty zones (`hvac.py:3985-4067`).
2. It builds a baseline from URA's editable seasonal table (`get_seasonal_setpoints`, `hvac_preset.py:126-180`). The live CM options set all 24 `hvac_baseline_*` values.
3. **It sets the low side to `cool − 7` and throws away the configured heat value** (`hvac.py:4074`).
4. It layers on OverrideEngine records from EC `_dynamic_preset_overrides` (`energy.py:7126-7319`). Only Dynamic Preset produces records, and only for home and sleep (`dynamic_preset.py:926-959`). Nothing produces guest overrides (`preset_overrides.py:241-249`).
5. It writes **raw `climate.set_temperature`** via `emit_set_temperature` (`hvac.py:4131-4142`) whenever the pair differs from `_last_emitted_range`. On compose-away zones it writes on **every tick** (the F2 bypass, `hvac.py:4096-4111`).

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
| `switch.ura_hvac_coordinator_guest_mode_actuation` | `..._hvac_coordinator_guest_mode_actuation_enabled` | **"01 · Custom Preset Ranges"** (`switch.py:1998`) | `HVACCoordinator._guest_mode_actuation_enabled` (`hvac.py:664` — REV 2 cited `:540`) | off |
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
| Flip 02 only | No: nothing actuates while 01 is off | `hvac.py:3923` |
| Type URA's ranges into each Bryant preset in the Carrier app | **Partly.** Covers the static half with no code, but must be retyped at each season change and cannot follow the weather | `dynamic_preset.py:109-132` |
| `ha_carrier` option `infinite_holds` | No | — |

**Marginal benefit.**
- The static half can be done by hand. Code buys automatic season changes and one editing place in URA.
- The dynamic half is ±1 °F on Home/Sleep cooling and is off November through February.
- The simplest correct code is small because it writes the preset profile instead of a hold. It deletes more risky machinery (D9/F2) than it adds.

**Verdict: BUILD** (operator ruled yes), gated on D0 item 5 (PASSED zone_3 2026-09-28).

---

## 2. Institutional context verified

### 2.1 Prior-art scan (REUSE / BUILD per piece)

| Piece | Verdict | Existing symbol / justification |
|---|---|---|
| Write a preset's range without a hold | **REUSE upstream** `ha_carrier.set_activity_setpoint` | `climate.py:91-104` registers it. `:539-596` edits the **status-named** activity (`_current_activity()`, `:136-142`) via `set_config_activity` and does not touch hold state (`:591`). Upstream PR #427 (C15). |
| Funnel for the new verb, with one `climate_write` row | **BUILD** `emit_set_activity_setpoint` | Sanctioned by W1-A (`PLANNING_hvac_w1a_thermostat_write_governance.md:363`). Reuses `_snapshot_climate_state` (`hvac_setpoint.py:127-160`), `_schedule_climate_write_row` (`hvac_setpoint.py:213+`), `_log_deferred_write` (`hvac_setpoint.py:258`), `apply_setpoint_guards` (`hvac_setpoint.py:96-112`). Sibling to shape it against: `emit_set_hvac_mode` at `hvac_setpoint.py:813-859` (shipped v5.103.16). **No existing funnel changes** (§12). |
| Per-brand rules | **REUSE + extend** `hvac_strategy.py` | `strategy_for` (`hvac_strategy.py:254`), `WriteResult` (`hvac_strategy.py:64-97`), `observe` (existing), `LAST_SENT_TOLERANCE_F` (`hvac_strategy.py:53`). Adds `set_preset_range` on `GenericStrategy` (returns FAILED unsupported) and `CarrierStrategy` (P1-P6). See §14 for the profile-agnostic surface. |
| Live-borrow read | **REUSE** gate (e) (`hvac_preset.py` `manual_guard_verdict` at `:234`, callers `:365`) | Pulled out into a pure `borrow_live(zone_id)`. Calling `manual_guard_verdict` directly is rejected because it writes `_last_manual_verdict`. |
| Person-protected skip | **REUSE** `_corrective_writes_suppressed` (`hvac_override.py:672`) | Already at S10 (`hvac.py:3976-3984`). |
| **Unreadable-climate skip (NEW REV 3)** | **REUSE** `_climate_unreadable(zone_id, zone)` (`hvac.py:2382-2411`) | Added Batch D v5.103.24 (`HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1`). One INFO + `climate_write_held_unreadable` row per outage episode. |
| **Interrupt-latch skip (NEW REV 3)** | **REUSE** the latch predicate (grep `_interrupt_latch`, `latch_level_check`, `_latch_state_discharges`, side-key `__interrupt_latch`) | Added Batch B v5.103.23 (`OverrideArrester`). Persisted; level-discharged. |
| Comfort-delay defer | **REUSE** `_s10_gate` / `comfort_delay_active` (`hvac.py:4118-4130`) | |
| Same-tick S1 skip | **REUSE** `_zones_written_this_cycle` (`hvac.py:455`, `:1879`, `:3194`) | (line numbers may drift; grep) |
| AC-reset / egress skips | **REUSE** `has_active_ac_reset` (`hvac_override.py:2183`), `is_paused` | |
| Range values | **REUSE** `get_seasonal_setpoints` + OverrideEngine + EC overrides | The written low is now the configured heat value. |
| Arrester must not book S10 | **REUSE, no stamp** (M4) | `_handle_climate_change` books only a transition into `manual`. A setpoint change under a named preset is explicitly ignored (`hvac_override.py:3216-3226`, "a preset range adjustment. Ignore."). `_comfort_request_qualifies` (`hvac_override.py:3327`) runs only after that return. A `suppress()` stamp would add nothing, and it would blind a genuine human change to `manual` for 15 s. **Dropped** (the current `suppress(kind="temp")` at `hvac.py:4114-4115` is DELETED, and its `unsuppress` roll-back at `:4150-4151` too). |
| Persistence | **REUSE** `_zone_state_store` side-key pattern (`hvac.py:2081-2118`, rehydrate `:1780-1871`) | New side-key `__s10_preset_ranges` (§6.3). Coexists with `__interrupt_latch` (Batch B), `__immune_holds`, `__tao_state` (W1-B) — verify no key collision. |
| Trip-wire NM | **REUSE pattern** `_note_s1_reclaim` (`hvac.py:1653-1695`) | |
| AST lint | **EXTEND** `test_hvac_climate_write_funnel_completeness.py` | Add the `"ha_carrier"` literal (currently at `:120-130` flags only `"climate"`). |
| D9 compose-away, F2 bypass, S10 transient hold, `_dpm_composed_away_zones`, the `cool − 7` baseline | **DELETE** (§8) | |
| `_last_emitted_range` | **KEEP**; S10 stops writing it | S11 (`hvac_predict.py:864-920, 1060+`) and S13 (`hvac_predict.py:1589`) still use it. |

**Surfaces grepped:**
- Constants: `const.py`, `hvac_const.py`, `energy_const.py`.
- Fields: `config_flow.py`, `strings.json`, `translations/en.json`.
- Entities: `switch.py`, `sensor.py`.
- Code: `hvac*.py`, `energy.py`, `dynamic_preset.py`, `preset_overrides.py`.
- `ha_carrier/{climate,const,carrier_data_update_coordinator}.py`.
- `quality/tests/`: 7 files call `_async_apply_preset_overrides`.
- **Batch B/D adds re-greped:** `HVAC_CLIMATE_UNREADABLE_STATES`, `_climate_unreadable`, `_interrupt_latch`, `_latch_state_discharges`, `pre_arrival_reference_preset`, `emit_set_hvac_mode`.

### 2.2 Prior plans
- `PLANNING_v4.7.x_guest_mode_actuation_phase1.md`
- `PLANNING_v4.7.2_dpm_hvac_surface_plus_guest_signal.md`
- `PLANNING_hvac_zone_conditioning_demand.md` §0b/D9
- `PLANNING_hvac_w1b_thermostat_definition.md` (§5.P6, :408, D2.4 :307-311)
- `PLANNING_hvac_w1a_thermostat_write_governance.md:363, :399`
- `PLANNING_hvac_arc_w1_w2_integration.md` (C1, C5, §5 decision 1)
- `PLANNING_v5.7.0_guest_mode_detection_and_actuation.md:222`
- `HVAC_ARC_TAIL_2026_09_18.md:101-109`
- **NEW REV 3:** `PLANNING_hvac_w1_w2_finish.md` REV 2 (Batch B v5.103.23) — the interrupt-latch persistence, `pre_arrival_reference_preset`, S6/S7 INFO-1 spec.

### 2.3 READMEs
v5.103.7, v5.103.18, v4.7.1, v4.7.2, v4.7.3. **NEW REV 3:** v5.103.23 (Batch B), v5.103.24 (Batch D — unreadable guard, Fan Mode, INFO-1).

### 2.4 Memory
`feedback_label_style_guide.md`, `reference_hvac_state_of_play.md`, marginal-benefit, config-first, `feedback_unrestored_mutation_drill_poisons_evidence`, `feedback_suppression_needs_discharge`, `feedback_orchestrator_stays_in_main_checkout` (REV 3 Tier-3 discipline).

### 2.5 Design docs
State-of-play (full, 589 lines). `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §2–§3, verb table :261-265, open item 6 :328 — closed by D0 item 5 evidence (2026-09-28).

### 2.6 Code read
- `hvac.py` — S10 method `3906-4171`, S1 lockout `2913-3210`, boot rehydrate `1873-1880` / `2081-2118` / `1780-1871`, `_note_s1_reclaim` `1653-1695`, `_climate_unreadable` `2382-2411`, `HVAC_CLIMATE_UNREADABLE_STATES` import `:53`, `_climate_unreadable_episodes` init `:551`
- `hvac_preset.py` (all), `hvac_strategy.py` (all), `hvac_setpoint.py` including `emit_set_hvac_mode` `813-859`
- `preset_overrides.py`, `dynamic_preset.py`, `energy.py` 7126-7319
- `switch.py` 1685-2104, `sensor.py` 10128-10260
- `hvac_override.py` 2262-2281, 2678-2830, 2960-3290 (+ REV 3: interrupt-latch predicate + `_cancel_arrester_timers` scope narrowing)
- `hvac_excursion.py` — `_auto_return` C26 skip **RETAINED** (do not delete; state-of-play §10 C26)
- `hvac_predict.py` 150-195, 855-1065, 1132-1140 (Batch D `_resolve_baseline_range` fix at `~929` is `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1`, already shipped v5.103.22)
- `ha_carrier/climate.py` 60-600, `ha_carrier/const.py` 40-64, `ha_carrier/carrier_data_update_coordinator.py` 145-345, 425-435

### 2.7 Every consumer of a preset profile's setpoints (LOW-5)

Once S10 edits a named profile, every reader of `target_temp_high/low` under that preset sees URA's range. Every site is listed. None needs a code change: each one already reads the live profile, and that is the intended new behaviour.

| Consumer | File:line | Trust / display | Effect of an S10-edited profile |
|---|---|---|---|
| Zone refresh (source of `zone.target_temp_*`) | `hvac_zones.py:558-559`, exposed `:816-817` | producer | Carries URA's range |
| Soft-nudge trigger ("at/below setpoint") and nudge start/size | `hvac_override.py:4129, 4177, 4596, 4730-4765` | trust | Nudges are measured against URA's range. Intended. |
| Nudge snapshot/restore (HUMAN_MANUAL path only) | `hvac_override.py:4828, 4853, 5067` | trust | Named-snapshot returns pin the preset, so they land on URA's range |
| **Nudge restore INFO-1 (Batch D v5.103.24)** | `hvac_override.py` S6/S7 region (`~:4595`, `~:4640`) | trust | S7 pin lands on the S1 target preset whose profile now carries URA's range. No CPR write triggered. Under person-protection at restore, S6 restores the person's setpoints (raw HUMAN_MANUAL) — outside CPR's remit. |
| Nudge outcome evaluation | `hvac_override.py:5542` | trust | |
| Hard-reset escalation | `hvac_override.py:6146, 6165` | trust | |
| Cancel-nudge / boot ramp audit | `hvac_override.py:6294, 6708, 6766` | trust | |
| Arrester detection delta (manual transitions only) | `hvac_override.py:3211-3214` | trust | `old_high` is URA's range, so a human's delta is measured from it. Correct. |
| **Within-manual detection (Batch B v5.103.23 D1)** | `classify_manual_setpoint_change` (`hvac_override.py`) | trust | Only fires when both states are `heat_cool` and the zone reads `manual`. CPR writes edit a NAMED preset — the entity never reads `manual` from a CPR write. **CPR writes are NOT recorded in the URA-last-4 `set_temperature` RAM record** (the record lives inside `emit_set_temperature`; CPR uses `emit_set_activity_setpoint`), which is CORRECT: a CPR edit is a profile edit, not a raw setpoint. |
| Comfort-grant qualification (manual path only) | `hvac_override.py:2789-2792` | trust | Same |
| Startup audit (manual zones only) | `hvac_override.py:2274-2275` | trust | Unaffected (named zones skipped) |
| Excursion `begin` snapshot | `hvac_excursion.py:823-824` | trust | Snapshots URA's range |
| Pre-cool / banking (reads live high; known ratchet) | `hvac_predict.py:1132-1140, 1236` | trust | Banks off URA's range |
| Pre-heat | `hvac_predict.py:1425-1428, 1451, 1486` | trust | |
| Predictor demand deltas | `hvac_predict.py:343-397` | trust | |
| Fans (setpoint-relative activation) | `hvac_fans.py:762` | trust (gated on Batch D Fan Mode; per state-of-play §4.2b, unrelated to CPR) | |
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

**REV 3 clarification (Batch B interaction):** Batch B's "person interrupts, we end and revert" only ends BANKING/PREHEAT/ownerless COMPROMISE and fires when the arrester detects a CHANGED leg. A CPR profile edit does not change any leg on any zone that is on a different preset; on the target zone it changes the profile the zone is on, which the arrester ignores (named preset). Therefore CPR writes cannot spuriously trigger the "person interrupts" path.

Rejected options:
- (a) New EXCURSION_KIND: forbidden by the operator constraint, and it is the wrong model for a standing setting.
- (b) Per-tick flag read by gate (e): the flag clears, S1 reclaims, and the range is lost. Making it sticky would bring back the dropped provenance approach.
- "Write a preset": a preset cannot carry a custom range. Editing its profile is the only way.

### 3.2 S10 per-zone algorithm (replaces the loop at `hvac.py:3985-4171` — REV 2 cited `:3423-3636`)

**Method entry:**
- **Switch OFF:** run the **restore pass** (§3.4) if any snapshot exists, then return.
- **Switch ON:** run the apply pass.

The observation-mode gate at the call site (`hvac.py:3849`) is unchanged. An absent EC or empty overrides no longer returns early, because the static half still applies.

**Apply pass, per zone.** The first skip wins; each skip is `continue` plus a debug log.
0.5. **[NEW REV 3]** `self._climate_unreadable(zone_id, zone)` (`hvac.py:2382`). No wire call, no snapshot capture, no rate-clock consumption. Existing helper writes one INFO + one `climate_write_held_unreadable` row per outage EPISODE — DO NOT open a second episode for S10.
1. `egress_manager.is_paused(zone_id)`.
2. `arrester._corrective_writes_suppressed(zone_id)` (gate a/b), plus `_log_shave_skipped(..., "dpm_preset_override")`.
3. `zone_id in self._zones_written_this_cycle`.
3.5. **[NEW REV 3]** interrupt latch (Batch B v5.103.23) — grep `_interrupt_latch` / `latch_level_check` / `_latch_state_discharges` for the coordinator's read predicate. No wire call, no snapshot capture. Rationale in REV 3 changelog item 3.
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
    - **No `suppress()` stamp (M4).** Explicitly REMOVE the existing `suppress(zone.climate_entity, kind="temp")` at `hvac.py:4114-4115` and the paired `unsuppress` at `:4150-4151`.
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

**Persistence.** Side-key `__s10_preset_ranges.snapshots[zone_id][preset]` in `_build_zone_state_snapshot` (§6.3). It is rehydrated at boot. **REV 3 note:** verify no key collision with `__interrupt_latch` (Batch B), `__immune_holds` / `__tao_state` (W1-B) — all side-keys on the same `_zone_state_store`.

**Restore on OFF.**
- The restore pass runs on every tick while switch 01 is OFF and any snapshot exists. It is state-driven, not edge-driven, so a restart while OFF simply continues it.
- It uses the same skip matrix (steps 0.5, 1–6, plus the new 3.5 latch skip), the same strategy method and the same funnel, with `desired = snapshot`, `site="S10_preset_range_restore"`, `reason="restore_carrier_original"`.
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
- **[REV 3]** It no longer writes while the climate entity is `unavailable`/`unknown`, and no longer writes while the zone is interrupt-latched.

---

## 4. D0 — measure before build (first deliverable; gates the build)

Probe script: `scripts/probes/hvac_preset_profile_probe.py` (read-only, run via `ssh ha "python3 -" < ...`).

1. **Current Bryant profile per (zone, preset)** from the last 7 days of recorder data. Use samples with `preset_mode == hold_activity == P` and `heat_cool`, only those at least 125 min after any URA or human write to that zone (so they have passed a full read). Report the modal low/high and the sample count.
2. **The fixture.** Table of zone × preset: Bryant (item 1) vs URA desired, for summer now and shoulder from Oct 1. Differing cells are the writes expected on enable. This is the committed acceptance fixture, **and** the independent record of the originals for L8. The operator also notes the app's preset ranges before enabling.
3. **S10 reach.** For each zone, the share of 5-min samples where both feeds agree on a named preset. Flag any zone below 50%.
4. **Restore-writers disposition.** Episodes since v5.103.18 where a zone was established-empty but sat on a comfort preset for more than 15 min. Expected ≈0. **REV 3:** re-run against develop after Batch B v5.103.23 pre-arrival S12 lifecycle lands, since that changes what an "established-empty but on a comfort preset" episode looks like.
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

**Item 5 PASSED zone_3 2026-09-28 08:26 CDT** (see §"D0 item 5 — live test log" at the tail of REV 2, retained verbatim). Items 1-4 to be filled before build dispatch.

---

## 5. Deliverables

### D1 — `emit_set_activity_setpoint` funnel (`hvac_setpoint.py`)

A sibling of `emit_set_temperature` (`:429-522`) and `emit_set_hvac_mode` (`:813-859`):
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

As specified in §3.3 (P1–P6). See §14 for W1-C interaction — this is the Carrier profile method; generic returns FAILED.

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

- Implement §3.2. **[REV 3]** Skip steps 0.5 (unavailable) and 3.5 (interrupt latch) MUST be part of D3.
- DELETE D9 compose-away (`hvac.py:3985-4067`), the S10 transient hold (inside that block), the F2 bypass (`hvac.py:4096-4111`), `_dpm_composed_away_zones` (`hvac.py:4055-4056`), the `_last_emitted_range` write (`hvac.py:4153`), the `cool − 7` baseline (`hvac.py:4074`), and the suppress/unsuppress stamps (`hvac.py:4114-4115` and `:4150-4151`). REV 2 cited `:3452-3528`, `:3488-3517`, `:3563-3578`, `:3522-3526`, `:3620`, `:3541`, `:3581-3582 / :3617-3618 / :3634-3635` — those are STALE, use the REV 3 anchors.
- Pull gate (e) out into `borrow_live`. `manual_guard_verdict` must return byte-identical output.

**Acceptance** (D3 folds `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` + `HVAC-S10-DPM-VS-S1-1` — see REV 3 changelog item 5)
- **Verify (no fight):** zone on home/home, DPM cool_high 75 vs Bryant 76 → one S10 call. The next tick has zero S1 writes and S10 returns SKIPPED.
- **Verify (no storm):** an established-empty away zone whose profile matches, over 12 ticks → zero S10 calls (the old code made 12).
- **Verify (skip matrix):** egress / **unavailable [REV 3]** / a-b / same-tick / **interrupt-latch [REV 3]** / borrow row / `_nudge_in_flight` / `_compromise_timers` / AC reset / manual / wake → zero calls each.
- **Verify (low side):** winter away 80/65 → the write is 65/80.
- **Verify:** the zone's own preset is edited, never the house-state preset.
- **Verify (M4):** an S10 edit replayed as a climate state_changed event (named preset → same named preset, new high) → **no `override_detected` row, no comfort grant, and no `_suppressed_until` entry** for the entity.
- **Verify [REV 3]:** an S10 edit does NOT append to the URA-last-4 `set_temperature` RAM record (Batch B D1 within-manual detection); a subsequent human-typed setpoint on that entity's manual profile IS still detected correctly.
- **Tests:**
  - `test_s10_edits_profile_not_hold_no_s1_reclaim` (drives `_apply_house_state_presets`)
  - `test_s10_empty_zone_no_storm_12_ticks`
  - `test_s10_skip_matrix` (parametrised, **11 cases** [REV 3, was 9])
  - `test_s10_defers_when_climate_unreadable` **[NEW REV 3]**
  - `test_s10_defers_when_interrupt_latched` **[NEW REV 3]**
  - `test_s10_low_side_uses_configured_heat_winter_away`
  - `test_s10_acts_on_zone_preset_not_house_state`
  - `test_s10_dpm_sleep_override_applies_only_in_sleep`
  - `test_s10_edit_books_no_override_detected`
  - `test_s10_edit_not_recorded_in_within_manual_detector` **[NEW REV 3]**
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
  - **[NEW REV 3]** Rehydrate coexists with `__interrupt_latch`, `__immune_holds`, `__tao_state` — no side-key collision, all four restore independently.
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
  - `test_s10_snapshot_side_key_no_collision_with_batch_b_latch` **[NEW REV 3]**

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
  - Header (bump snapshot).
  - §1 (S10 setpoint-layer no longer DORMANT; §3.3 row 3 update).
  - §3.2 (remove the D9 consumer; add CPR to the readers-that-BYPASS list? — NO, CPR is neither a bypass nor a gate consumer).
  - §3.3 (row 3 layer LIVE).
  - §4.1 (new funnel `emit_set_activity_setpoint`).
  - §4.2 (S10 row now describes named-profile edits with the restore site; drop the "dormant" note).
  - §5 (`set_activity_setpoint` used by S10, with the D0-5 result closing open item 6).
  - §9.7 closed.
  - §11 row 5 SHIPPED.
- **`THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §3:**
  - Adopted for S10 standing ranges, with a persisted snapshot and restore-on-off (§3.4 of this plan). That satisfies §3's rule even though this is not a borrow.
  - Close open item 6 with the D0-5 evidence.
- **README** `README_v5.103.x.md` with a Validated table.

### D8 — Switch default OFF (LOW-6; operator answered YES 2026-09-27)

Today the default is ON: `hvac.py:664` (was `:540` in REV 2, `True`), `switch.py:2021-2022`, and `sensor.py:10203, 10235` (`getattr(..., True)`). Change all four to False, so a fresh install or lost restore-state cannot turn the feature on.
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
- **[REV 3]** Coexists with side-keys `__interrupt_latch` (Batch B), `__immune_holds`, `__tao_state` (W1-B). New test asserts no key collision (D3b).
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
| Thermostat unavailable (REV 3) | pointless calls, latch churn | **0** (one INFO/ledger row per outage episode) |
| Zone interrupt-latched (REV 3) | writes into the person's fight | **0** (waits for the level discharge) |

---

## 7. Invariants and live validation

### 7.1 Invariants

> **INV-S10.** With switch 01 ON, every S10 wire call is `ha_carrier.set_activity_setpoint`, issued only while `preset_mode == hold_activity == P ∈ {home, sleep, away, vacation}` in heat_cool, and never for a zone with a live borrow, person-protected hold, arrester comfort window, AC reset, egress pause, same-tick S1 write, **unavailable/unknown climate entity, or an active interrupt latch [REV 3]**. S10 never changes hold state, so it never creates `manual`, and S1 never reclaims a zone because of S10.

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
- **Q7 [NEW REV 3]:** S10 rows whose `values_before.hvac_mode ∈ HVAC_CLIMATE_UNREADABLE_STATES` → 0. (INV-S10 unavailable skip.)
- **Q8 [NEW REV 3]:** S10 rows on a zone whose interrupt-latch was active at the row's `ts_issued` (join against `__interrupt_latch` state snapshots or `preset_change_deferred` rows with `reason=interrupt_latched`) → 0.

**Discrimination: fix vs failure**

| Observation | Fix | Old / fight | Old / storm | Wrong-profile edit |
|---|---|---|---|---|
| S10 verb | `set_activity_setpoint` | `set_temperature` | `set_temperature` | `set_activity_setpoint` |
| Preset after write | unchanged, named | `manual` | `manual` | unchanged |
| S1 `zero_delta_ura` after | none | once | every tick | none |
| S10 rows/h, empty zone | 0 | 0 after first | ~12 | ≤ 1 |
| Bryant app | "Holding Home 70–75" | Manual, then old range | alternating | range on the wrong preset (Q6 + app) |

### 7.2 The enable step (operator action; exact knobs)

Prerequisites: D0 item 5 PASS (done zone_3 2026-09-28), deploy, HACS install, restart, and fixture review. Note the app's current preset ranges.
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
| **L10 [NEW REV 3]** | Unavailable skip | during any thermostat outage in the window, `climate_write_held_unreadable` rows exist for the zone but **zero** `S10_preset_range` rows | Q7 |
| **L11 [NEW REV 3]** | Interrupt-latch skip | for any zone with an interrupt latch in the window, **zero** `S10_preset_range` rows while the latch stands | Q8 |

Proven only in-suite: latch/NM (D4), restart-storm bound, winter low side, restore latch, side-key non-collision (D3b).

---

## 8. Supersession

| Item | File:line (REV 3 anchors) | Bucket | Superseded by | Reason |
|---|---|---|---|---|
| D9 compose-away | `hvac.py:3985-4067` (REV 2 `:3452-3528`) | DELETE | row-1 preset retreat + W1-B presets-only returns | The corrector is no longer needed; it is the storm source |
| F2 bypass | `hvac.py:4096-4111` (REV 2 `:3563-3578`) | DELETE | the rate model | Storm |
| S10 transient hold | inside `hvac.py:3985-4067` (REV 2 `:3488-3517`) | DELETE | — | It only held D9's retreat |
| `_dpm_composed_away_zones` | `hvac.py:4055-4056` (REV 2 `:3522-3526`) | DELETE | — | No readers |
| `cool − 7` baseline at S10 | `hvac.py:4074` (REV 2 `:3541`) | DELETE | configured heat | Bug Class #63 |
| suppress/unsuppress at S10 | `hvac.py:4114-4115` and `:4150-4151` (REV 2 `:3581-3582, 3617-3618, 3634-3635`) | DELETE | arrester's named-preset ignore (M4) | Would blind genuine manual detection |
| `_last_emitted_range` S10 write + switch clear | `hvac.py:4153`; `switch.py:2037-2039` | DELETE | — | S11/S13 keep the map |
| `_last_emitted_range` map | `hvac.py:667` (REV 2 `:543`) | KEEP + DOCUMENT | — | Live S11/S13 consumers |
| `hvac_predict` `cool − 7` fallback | `hvac_predict.py:~929` | **DONE** — shipped v5.103.22 (`HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1`) | — | Fixed in a separate cycle per operator ruling Q3 |
| OverrideEngine `cool_low` | `preset_overrides.py:60` | KEEP + DOCUMENT | — | Ignored at actuation |
| `hvac_excursion.py` `_auto_return` manual-skip | (unchanged) | **KEEP** (state-of-play §10 C26) | — | REV 2 anticipated deletion; refuted. `pre_preset` snapshot at `begin_excursion` can be `manual` (COMPROMISE begun during override), so deleting the skip would WRITE `manual`. Pinned by `test_hvac_excursion_d1_auto_release.py`. Do NOT delete in this cycle. |

---

## 9. Card dispositions

- `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` → **done on ship** by D3 DELETION (§8). Evidence: `test_s10_empty_zone_no_storm_12_ticks` in-suite; live Q1/Q4/Q5 zero rows/h on empty zones.
- `HVAC-S10-DPM-VS-S1-1` → **done on ship** by §3.1 named-profile write (never `manual`, so S1 has nothing to reclaim). Evidence: `test_s10_edits_profile_not_hold_no_s1_reclaim`, `test_s10_edit_books_no_override_detected`; live Q2/Q3 zero rows. Operator constraint honoured (no `begin_excursion` change).
- `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` → verify-and-close on D0 item 4. The premise was removed by W1-B D2.4 (`hvac_override.py:5041, 6276, 6750`; `hvac_predict.py:984, 1542`) together with row-1, and by Batch B pre-arrival S12 lifecycle (state-of-play §4.2). **The `FOLD_2026_09_17` item (EC coast/shed offset path — verify FIX-B2-style pre-write preset snapshot + `set_preset_mode` restore) stays open.** Not blocking on CPR.
- **New cards (already minted or shipped):**
  - `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` — **SHIPPED v5.103.22**, DONE.
  - `HVAC-DPM-OPTION-VS-SWITCH-SPLIT-1` — carded.
  - The DPM range sensor display, folded into the first card.
  - `HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1` — **SHIPPED Batch D v5.103.24** for B1/S1; CPR inherits via the same helper (REV 3 §3.2 step 0.5).

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
- **T9 [NEW REV 3].** Neuter step 0.5 (unavailable skip) → `test_s10_defers_when_climate_unreadable` fails.
- **T10 [NEW REV 3].** Neuter step 3.5 (interrupt-latch skip) → `test_s10_defers_when_interrupt_latched` fails.
- **T11 [NEW REV 3].** Route S10 through `emit_set_temperature` instead of `emit_set_activity_setpoint` → `test_s10_edit_not_recorded_in_within_manual_detector` fails (the Batch B RAM record captures the write when it should not).
- **Suite:** `PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/ -v`, serial. Compare test names against the `pre-review` baseline.

---

## 11. Tier and review

**Tier 2-DB** (three framing-disjoint build reviews + live validation + README write-back). It is elevated from the card's Tier 2 under the standing regression-prone policy:
- a new writer verb;
- a deleted corrector path;
- new persisted state (that coexists with three other side-keys shipped W1-B / Batch B);
- adjacency to S1 / nudge / arrester precedence (all of which have shifted under W1-B and Batch B/D).

**Not Tier 3** — the argument, re-stated for REV 3: there is one emission site with two modes (apply + restore), one strategy method (`CarrierStrategy.set_preset_range`), one persisted snapshot store (`__s10_preset_ranges`). The falsifiable invariant (INV-RESTORE) is single-surface. The operator may elevate. **REV 3 recommendation:** stay Tier 2-DB; do not elevate. D0 item 5 (already PASSED on zone_3 2026-09-28) surfaced no unexpected Carrier behaviour.

**REV 3 standing addition — Tier-3 discipline on the restore-snapshot invariant.** Because the persisted snapshot IS the operator's only path back to Carrier defaults if they turn CPR off (a bug in the snapshot store is unrecoverable without their app):
- The orchestrator personally re-greps every wire-call site and every consumer of the persisted snapshot before deploy (state-of-play §11 Tier-3 rule; memory `feedback_orchestrator_stays_in_main_checkout`).
- The falsifiable INV-RESTORE is stated up front and D's job (if the operator elevates to Tier 3) is to falsify exactly that: "for every (zone, preset) URA has edited, a persisted original exists from before the first edit until a confirmed restore".

**Reviews:**
- **Plan re-review:** one Tier-2 plan review over the REV 3 changelog + the new skip steps 0.5 and 3.5 + the strategy method + §14. The reviewer independently re-runs the write-site grep (the REV 3 anchor table is a hypothesis; verify).
- **Build reviews (three parallel, framing-disjoint):**
  - **A — correctness and edge cases:** P1–P6, rounding, guards, low side, season/DPM gates, snapshot capture rules, restore current-preset-only. **[REV 3]** the unavailable skip covers all restart / mid-write / partial-availability shapes; the interrupt-latch skip discharges correctly on the same tick a person's change arrives.
  - **B — cross-coordinator, lifecycle, no-flap:** S1 same-tick, the borrow family, arrester (no stamp), the ha_carrier guard vs the 130-min retry, the switch source paths, restart/rehydrate, zone delete, S11/S13 map. **[REV 3]** side-key coexistence with `__interrupt_latch` / `__immune_holds` / `__tao_state`; the Batch B within-manual RAM record is NOT polluted by CPR writes; the Batch D unreadable-episode ledger is NOT double-opened.
  - **C — test authority by real per-site mutation:** T1–T11, lint.
- **Pre-deploy:** `pre-review-v5.103.x` tag and the zero-bugs gate. Orchestrator re-greps every wire-call site and every consumer of `__s10_preset_ranges` on develop HEAD.
- **Post-deploy:** HACS check → the enable step (§7.2) → L1–L11 → README Validated table and state-of-play in the same commit. **DEPLOY IS HELD** until the operator says so.

---

## 12. Non-goals

- No new EXCURSION_KIND. No change to `begin_excursion` / `return_excursion` / `hvac_excursion.py` (including the `_auto_return` manual-skip, state-of-play §10 C26 — do not delete).
- **The new funnel is W1-A-sanctioned and does not conflict with W1-B's constraint.**
  - W1-A: `PLANNING_hvac_w1a_thermostat_write_governance.md:363` — "if Stage B adopts it [`set_activity_setpoint`], that funnel gets a row shape then."
  - The W1-B constraint "nothing added to the `emit_*` funnels" (`hvac_strategy.py:7-8`; state-of-play §9e) forbids adding **decision logic** to the **existing** funnels.
  - `emit_set_activity_setpoint` is a new verb funnel with the same behaviour-neutral shape: the existing `gate=` parameter only, no brand or gate logic. All S10 rules live at the S10 site and in the strategy. `emit_set_temperature` / `emit_set_preset_mode` / `emit_set_hvac_mode` are untouched.
- No change to S1's four gates or `should_change_preset`.
- Nudges stay on `set_temperature` (integration plan §5 decision 1).
- No heat-side weather adjustment. No guest-override producer. No entity_id rename.
- No non-Carrier support in THIS cycle — the strategy hook exists (§14) but W1-C carries the generic thermostat build.
- No `wake` preset.
- No fix for zone_1's status/hold split (S10 defers there; `HVAC-WRITE-CONFIRMATION-ORACLE-1`).
- **No change to the `hvac_predict` `cool − 7` fallback** (SHIPPED v5.103.22, `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` DONE).
- No Bryant schedule changes.
- No forcing a zone onto a preset in order to restore it (that would fight S1). Restores are lazy.
- **[REV 3]** No change to Batch B's within-manual RAM record, the interrupt-latch primitive, the pre-arrival lifecycle, the arrival-reference resolver, the Fan Mode, or the arrester ↔ AC-reset separation. CPR consumes; it does not modify.

---

## 13. Open questions for the operator

Q1–Q3 answered (rulings verbatim below). Q4–Q5 answered 2026-09-27 (verbatim below). Still open:

6. **[REV 3]** Is the operator willing to run L3 (physical Bryant-app check) once per zone × preset in the first 24 h post-enable, or should URA add a periodic HA-view compare as a weaker corroboration? Recommend: yes, one manual pass, then rely on falsifier queries.

## Operator rulings 2026-09-27 (verbatim, pre-build)
- **Q1 (app edits vs URA):** "Won't the app just reflect the new preset? Yes Ura wins." — Yes: the Carrier app shows URA's edited temperatures inside each named preset. While CPR is on, URA wins; stop + NM after 3 unconfirmed tries stays.
- **Q2 (turning CPR off):** "If we turn of cpr, it should go back to the default ranges inset right?" + picked **Restore Carrier originals**. BUILD CHANGE: before URA first edits a zone's named preset, snapshot the original Carrier range for that preset (persisted, per zone x preset); when switch 01 turns OFF, write each snapshotted original back once (same write path, confirmation + NM on failure) and clear the snapshot. Restart while ON keeps snapshots; a preset URA never edited is not touched.
- **Q3 (the minus-7 heat bug in the hvac_predict restore fallback):** **Separately** — carded and SHIPPED v5.103.22 (`HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` DONE).

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

## Cross-plan note (2026-09-28)
Fast-response review D-L4 found D9 compose-away does not consult the new pending hold (`_pending_arm_hold_write`, v5.103.20). This plan DELETES the compose-away path, so the finding is moot once CPR ships; if CPR is built before v5.103.20 merges, keep it deleted; if any D9 write path survives, gate it on `not _pending_arm_hold_write` with a drill.

---

## 14. Carrier-specific vs profile-agnostic scoping [NEW REV 3]

Feeds `HVAC-W1C-GENERIC-THERMOSTAT-1` (kanban trigger fired 2026-09-29 for multi-home rollout). CPR must land as a **Carrier-profile capability**, not a hard-wired assumption. This section enumerates the split so W1-C can add a generic thermostat without unwinding CPR.

**Above the strategy line (profile-agnostic — stays untouched by W1-C):**
- The S10 apply pass in `hvac.py` (§3.2): skip matrix, `borrow_live`, snapshot/restore state machine, latch/rate model, sensor exposure, switch entity, config-flow field, NM texts, `__s10_preset_ranges` side-key, `_climate_unreadable` skip, interrupt-latch skip. None of these read Carrier-specific state.
- `emit_set_activity_setpoint` funnel (`hvac_setpoint.py`, D1): the funnel is verb-shaped, not brand-shaped. Its wire call is `hass.services.async_call("ha_carrier", "set_activity_setpoint", ...)` — that literal IS Carrier-specific and belongs in the strategy method, NOT in the funnel. **REV 3 correction to D1:** the funnel must not name `ha_carrier`; it takes a `service_domain: str, service_name: str` pair (or a bound partial) from its caller. The strategy method supplies them. The AST lint (D1 test) already forbids `ha_carrier` service literals outside `hvac_setpoint.py`; extend to forbid the literal `"ha_carrier"` in the funnel body too, so the strategy layer is the ONLY place the service identity lives.

**Below the strategy line (Carrier-specific — behind `CarrierStrategy.set_preset_range`):**
- The choice of service (`ha_carrier.set_activity_setpoint`) and its exact schema.
- The two-feed P1 rule (status + config activity agreeing) — a Carrier-specific concept.
- The 5-minute post-write guard reasoning (P4 rationale).
- The 130-min retry interval (`FULL_RECONCILE_INTERVAL_MINUTES + 5 + 5`) — Carrier-cloud-specific; other brands set their own rung-1 constant.
- The "edit the status-named activity" semantics (P6 after-call check).
- The set of preset names `{home, sleep, away, vacation}` — Carrier-family. A Nest profile in W1-C would return FAILED from its own `set_preset_range` for absent presets, and W1-C decides whether to fall back to a setpoint-based hold.

**Generic strategy behaviour (already in D2):**
- `GenericStrategy.set_preset_range` returns `FAILED("preset_range_unsupported")` and makes zero calls.
- S10 logs this once per entity and skips that zone quietly on every subsequent tick (no NM churn).
- W1-C's per-brand profiles override `set_preset_range` with brand-appropriate behaviour (or leave the FAILED default, in which case CPR is a no-op on that brand — the correct outcome).

**W1-C hand-off checklist (goes into `HVAC-W1C-GENERIC-THERMOSTAT-1` planning):**
1. Rename `S10_PRESET_RANGE_MIN_INTERVAL_S` semantics if the constant becomes brand-scoped; today it is a Carrier-cloud interval.
2. Ensure `borrow_live` / `manual_guard_verdict` / `_climate_unreadable` are already brand-agnostic (they are).
3. Consider whether the NM text ("Bryant app") should be templated by brand profile.
4. Ensure the `__s10_preset_ranges` side-key does not encode brand-specific keys.
5. `emit_set_activity_setpoint`'s service parameters come from the strategy (REV 3 correction above).

No CPR piece hard-codes Carrier assumptions above the strategy line.
