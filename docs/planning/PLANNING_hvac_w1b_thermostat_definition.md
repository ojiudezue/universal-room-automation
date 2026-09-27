# PLANNING — HVAC W1-B: Per-brand thermostat definition (Carrier/Bryant first) — REV 6

## OPERATOR RULINGS ON PRIOR HOLDS — RESOLVED 2026-09-27 (binding; verbatim below)

### P1 = **PERSIST IMMUNE HOLDS** (operator ruling)

**Verbatim (operator, 2026-09-27):** *"Persist the immune-person hold (zone, holder, start, sunset basis) so it survives a restart and gate (a/b) re-arms at boot before S1's first tick. Grace timers and comfort grants are NOT persisted. The accepted exposure is ≤ 20 min on restart."*

**Spec (folded into §5.P1 gate (a/b) + new §5 D-P1):**

- **Persist** every `_stamp_immune_hold` (`hvac_override.py:705`) as a DB row: `(zone_id, holder_user_name, holder_person_id, started_ts, sunset_basis, values_before_snapshot)`. Sunset basis captures the discriminator today's `sunset_immune_holds` (`:727`) uses (next_activity ts, durable house-state, or 4 h timer expiry) so post-restart sunset logic runs unchanged.
- **Rehydrate on setup** — read all rows into `_immune_holds` dict BEFORE the first decision cycle. Ordering guarantee: rehydration completes inside `async_setup_entry` before `SIGNAL_HVAC_COORDINATOR_READY` fires at `hvac.py:1381` (which is the seam gate (d) already respects, M10). Gate (a/b) via `_corrective_writes_suppressed(zone_id)` (`hvac_override.py:660`) then sees the row on the first tick at `hvac.py:1371`.
- **Clear on sunset** — every path that calls `sunset_immune_holds` / `_immune_holds.pop` (`hvac_override.py:838`) ALSO deletes the DB row. Same commit.
- **Not persisted (verbatim carve-out):** `_grace_timers`, `_comfort_delay_timers`, `_compromise_timers`, `_override_active`, `_nudge_excursion_tokens`, `_nudge_restore_timers`. Any of these that were in flight at shutdown are lost. Accepted exposure: `≤ 20 min on restart` — bounded by Comfort Grace (live 20 min, `hvac_const.py:452-456`).
- **TAO switch restore** — already `RestoreEntity` (verify at build; pattern precedent: `EnergyObservationModeSwitch` at `switch.py:701-791` and `MemoryNMConditioningSwitch` at `:909-965`). No change required if verified.

**Prior-art REUSE (Institutional Context First):**

| Piece | REUSE at | Note |
|---|---|---|
| DAO pattern (save / clear / get_all row on a coordinator-owned table) | `database.py:8219` `save_excursion_row`, `:8257` `clear_excursion_row`, `:8272` `get_all_excursion_rows` | Model the new immune-hold DAO on the same shape: `save_immune_hold_row(row)`, `clear_immune_hold_row(zone_id)`, `get_all_immune_hold_rows()`. Table `hvac_immune_holds` with the columns listed above; index on `zone_id`. |
| Boot-rehydration ordering | Existing boot audit `hvac_excursion.async_startup_excursion_audit` runs before `SIGNAL_HVAC_COORDINATOR_READY`; same call slot in `async_setup_entry`. | Add `arrester.async_rehydrate_immune_holds()` next to the excursion audit call. |
| SwitchEntity + RestoreEntity | `switch.py:701` (`EnergyObservationModeSwitch`), `:909` (`MemoryNMConditioningSwitch`), `:965` restore-retry pattern | Verify TAO switch (`switch.ura_hvac_coordinator_temp_arrester_override`) already subclasses `RestoreEntity`; if not, add per this precedent. |

**Acceptance (mandatory):**
- `test_immune_hold_persists_across_restart` — stamp an immune hold on zone_1; simulate HA restart; assert `_immune_holds['zone_1']` is populated BEFORE the first S1 tick; assert `_corrective_writes_suppressed('zone_1')` returns True on that tick; assert S1 does NOT reclaim.
- `test_immune_hold_sunset_deletes_db_row` — sunset the hold via each of the three sunset paths (next_activity / durable house-state / 4 h expiry); assert DB row cleared.
- **Reviewer C mutation:** neuter the rehydration call in `async_setup_entry` (delete the line); assert `test_immune_hold_persists_across_restart` goes RED with a specific named failure.
- **Reviewer B live:** post-deploy, place an immune hold via the Bryant app as an immune person; restart HA; observe `_corrective_writes_suppressed` True on first tick via debug attribute; observe zone NOT reclaimed.
- **Restart TAO test** — assert TAO switch state restored to its pre-restart value; gate (a/b) sees the restored TAO on first tick.

### P2 = **ACCEPT + LOG** (operator ruling)

**Verbatim (operator, 2026-09-27):** *"Within-tolerance human manuals (<1 °F, or <2 °F in coast) are reclaimed by S1 on its next tick with no grace and no NM. The reclaim row records the reason so it is visible in the log."*

**Spec (folded into §5.P1):**

- No NM. No arrester grace or compromise (the arrester's existing `OVERRIDE_NORMAL_DELTA = 1 °F` / +1 °F coast threshold at `hvac_const.py:531-532` already skips reverting sub-delta manuals — unchanged).
- S1's `climate_write` row for the reclaim carries `reason = 's1_manual_write_through:sub_delta_human'` when at the time of the reclaim (i) `preset_mode == "manual"`, (ii) no Alt-A gate is armed, AND (iii) the last observed `override_detected` on the same entity within `SUB_DELTA_WINDOW_S = 300` (5 min; Rung 1 module const) had `details.delta_f < OVERRIDE_NORMAL_DELTA` (or `< OVERRIDE_NORMAL_DELTA + 1` under coast).
- If no such `override_detected` exists in the window, `reason = 's1_manual_write_through:zero_delta_ura'` (the URA-caused strand class — the default problem-1 case).
- Log visibility: `preset_deferrals_today` counter unchanged (this is not a deferral); the `climate_write` row IS the log. Grep-friendly reason string.

**Acceptance (mandatory):**
- `test_sub_delta_human_reclaim_reason_string` — arrester books `override_detected` with `delta_f=0.5` (sub-delta); no gate arms; next tick S1 writes; assert `climate_write.reason == 's1_manual_write_through:sub_delta_human'`.
- `test_zero_delta_ura_reclaim_reason_string` — no preceding `override_detected` in window; S1 reclaims; reason string `zero_delta_ura`.
- `test_coast_threshold_uses_plus_one` — with coast active, delta 1.5 °F is still sub-delta (below 2 °F); reason string `sub_delta_human`. Discriminating: delta 2.5 °F → NOT sub-delta (arrester would revert, gate (c) armed).
- `test_no_nm_fires_on_sub_delta_reclaim` — assert no NM latch or bus event emitted; only the `climate_write` row.
- **Reviewer C mutation:** flip the reason discriminator (compare delta with `>` instead of `<`); assert `test_sub_delta_human_reclaim_reason_string` and `test_zero_delta_ura_reclaim_reason_string` swap outcomes.

**Both P1 and P2 are RESOLVED. They land in D-P1 (persistence) and §5.P1 (reason-string discriminator) respectively; §7 ship gate carries a restart drill for P1 and a reason-string drill for P2.**

---

> **Alt A APPROVED 2026-09-27.** Provenance chain / kill-switch / drift sensor / D0 merge blocker — DROPPED. Rulings 15/16 SUPERSEDED where provenance-only.
>
> **REV 6 folds both Tier-3 plan reviews (both FIX-PLAN) + operator rulings on P1/P2.** State-of-play §9e (post-ea6fabfd1) is authoritative. Ledger discipline preserved.

**Card:** `HVAC-W1-THERMOSTAT-DEFINITION` (Stage B).
**Tier:** Tier 3.
**Depends on:** W1-A SHIPPED v5.103.16; echo-fix SHIPPED v5.103.17.

**MANDATORY reads:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all — §9e); `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2; `README_v5.103.16/17/v3.9.0`; `hvac_excursion.py:6-16`; REV-4 + REV-5 plan reviews (both FIX-PLAN); card `operator_rulings_2026_09_27`.

---

## REV 6 change log

REV 6 folds 12 must-fix + 6 also-fix + 4 legacy-test replacements from the two Tier-3 plan reviews on REV 5, PLUS the operator's binding P1/P2 rulings above.

| # | REV-6 fix | Where |
|---|---|---|
| **P1 (operator)** | **Persist immune holds** via a new DAO on `database.py`; rehydrate before `SIGNAL_HVAC_COORDINATOR_READY`; grace/comfort NOT persisted; ≤ 20 min accepted exposure. | Front matter; §5 D-P1 NEW; §7 restart drill. |
| **P2 (operator)** | Sub-delta human manuals reclaimed silently; reason string discriminates `sub_delta_human` vs `zero_delta_ura`; no NM. | Front matter; §5.P1 reason-string block. |
| M1 | Gate (c): comfort-delay + grace + compromise timers; drop `_override_active` (leaks under TAO/immune early-return `hvac_override.py:3366-3372`). Reuse `_corrective_writes_suppressed` for (a/b). | §5.P1. |
| M2 | Gate (e): fresh row OR `_nudge_excursion_tokens` OR `_nudge_restore_timers` OR `_compromise_timers`. NEW pure-read `hvac_excursion.is_borrow_active(zone_id)` — side-effect free. `stale_ts` claim fixed: BANKING/EGRESS `duration_s=None` → 7200 s cap. Boot audit rehydrates COMPROMISE/PREHEAT/EGRESS rows w/o timer — still covered by gate (e). | §5.P1 gate (e); §1.1. |
| M3 | Vacancy/runtime bypass `hvac.py:2623-2625` ALSO checks (a/b) and (e). | §5.P1; C2/C-P1B. |
| M4 | S1 `suppress()` at `hvac.py:2775` → `kind="preset"` (120 s). §5.P3 reasoning corrected. NM anomaly `s1_reclaim_rate_high` (`S1_RECLAIM_RATE_LIMIT_N = 3` / 30 min). | §5.P3; §5.P5. |
| M5 | Operator-constraint restoration: no-op suppression + `last_sent` MOVE INTO strategy layer, NOT funnel. Returns KEEP resume-then-pin. `allow_resume=False` dropped. `excursion_id` = join key only. | §5 D2.5; §5 D2a; D2.4 return contract. |
| M6 | S11 `_release_ok` self-exclusion; S11 comfort gate onto preset write `hvac_predict.py:1046` (Bug Class #53); S13 restructure `:1515-1583` incl. `_last_emitted_range` update. | §5 D2.4. |
| M7 | Same-tick nudge-start skip: `_zones_written_this_cycle` set (S1 `hvac.py:1748` runs before `check_ac_reset:1760`). | §5 D2.1. |
| M8 | Arrester booking site is `_handle_climate_change`, `override_detected` at `hvac_override.py:3028`. `gated_reason` in `details`. Precedence: immune stamp `:3050-3100` → TAO skip `:3105` → comfort grant `:3130-3143` → gate-(e) → passive `:3176` (deduplicate). | §5.P1 arrester booking. |
| M9 | S10 DPM `hvac.py:3217` — explicit exclusion this cycle + card `HVAC-S10-DPM-VS-S1-1` (sibling `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`). | §2 + card. |
| M10 | Gate (d) reload window: accessor reads OPTIONS value until `SIGNAL_HVAC_COORDINATOR_READY` fires (`hvac.py:1381` vs first cycle `:1371`). | §5.P1 gate (d). |
| M11 | D4a: change all three defaults (`hvac_const.py:361`, `hvac.py:165`, `hvac_override.py:191`) to 15; named constant `HVAC_COMPROMISE_MINUTES_MAX = 15`. | §5 D4a. |
| M12 | Acceptance queries use `S1_reason_ladder` (`hvac.py:2821`). Gate snapshot in `details`. HUMAN_MANUAL := `pre_preset ∈ {manual, None, ""}` with reason prefix `human_manual_`. C-P1A carve-outs: night-trust / row-1 transient / dwell. | §0 INV; §7. |
| Also-1 | `PresetManager` built before arrester (`hvac.py:248-249`) — inject via post-construction setter; None → `(True, 'arrester_not_wired')` (fail-closed); update 8 two-arg test call sites. | §5.P1 injection. |
| Also-2 | Rewrite as behavioural: `test_hvac_offphase_removed.py`, `test_hvac_live_room_hold_wire_in.py`, `test_v4511_ac_energy_aware_ramp_down.py`, `test_preset_hold_contract_resume_then_pin.py::test_lockout_*`. | §5 D2.6. |
| Also-3 | Rename `preset_lockouts_today` → `preset_deferrals_today` (per-gate breakdown); `nudge_win` suppresses `arrester_reverts_today` (verify at build). | §5.P3. |
| Also-4 | All-brands scope for `hvac_preset.py` edit. | §5.P1. |
| Also-5 | Drill M10 = neuter `begin_excursion` to return None; assert S1 refuses while timer live. | Reviewer C brief. |
| Also-6 | LOWs: `_needs_resume_first:331`, `emit_set_preset_mode:487`, use `_delete_row` (not `_clear_row`); ~54 writes/day (not 160). | §5.P3. |
| Inst | §1.2-1.5 restated (ARREST-COMFORT-1, excursion kill switch, S10). | §1.2-1.5. |
| W2 | W2 fast-path plan lines 234/349/588 — signature change (add `zone_id`). | §9. |

Ledger discipline: decisions 1-16 kept verbatim; REV-6 items 17-35 appended (17-18 = operator P1/P2 rulings).

---

## 0. Falsifiable invariant

> **INV-W1B (REV 6, Alt A + collapsed + reviews-folded + P1/P2-ruled).** On any thermostat zone, over §7 floor:
>
> **C1 (presets-only return).** Every URA borrow return emits ZERO `set_temperature` EXCEPT for HUMAN_MANUAL snapshots (`pre_preset ∈ {manual, None, ""}`). Exhaustive list = 5 sites (§5 D2.4).
>
> **C2 (borrow protection — manual-qualified, bypass-carve-out).** While `is_borrow_active(zone_id) is True`: (i) if zone reads `preset_mode == "manual"`, S1 emits ZERO preset writes at `S1_reason_ladder`; (ii) vacancy/runtime bypass at `hvac.py:2623-2625` ALSO refuses; (iii) arrester `_handle_climate_change` at `hvac_override.py:3028` books `details.gated_reason ∈ {'nudge_win','borrow_active'}` and skips revert. Borrow's own return exempt only in the falsification JOIN (via `excursion_id` key), not via a runtime gate. Bound: row's `stale_ts` (7200 s cap for `duration_s=None`).
>
> **C3 (nudge wins).** For active NUDGE (row present AND `_nudge_excursion_tokens[zone_id]` set), arrester books `details.gated_reason='nudge_win'`; no revert.
>
> **C5 (no-op at strategy layer, not funnel).** `Strategy.hold_preset` returns `SKIPPED_ALREADY_CORRECT` when (verb, values) match strategy `last_sent` AND observation matches (tolerance); ZERO service calls. `hvac_setpoint.py` unchanged.
>
> **C-P1A (S1 rewrites URA-caused zero-delta manual).** While arrester enabled AND `_corrective_writes_suppressed(zone_id) is False` AND no comfort-delay/grace/compromise armed AND `is_borrow_active(zone_id) is False` AND `effective_preset != "manual"` AND zone is NOT under night-trust suppression, row-1 transient hold, or entry dwell: S1 leaves zone in `manual` for AT MOST one S1 decision tick.
>
> **C-P1B (S1 never races a legitimate hold; manual-qualified).** When zone reads `preset_mode == "manual"`, S1 emits ZERO preset writes at `S1_reason_ladder` while ANY of the four Alt-A gates armed. When zone reads a NAMED preset, C2(ii) covers writes on the vacancy/runtime bypass path.
>
> **C-P1C (P1 persistence — restart survivability).** After a restart, an immune-person hold that was armed pre-shutdown is REHYDRATED into `_immune_holds` before `SIGNAL_HVAC_COORDINATOR_READY` fires, and S1's first post-boot tick sees `_corrective_writes_suppressed(zone_id) is True` for that zone. Falsifier: any `climate_write.site='S1_reason_ladder'` on a zone whose pre-restart immune-hold row was present in the DB, occurring before the DB row was cleared by a sunset event.
>
> **C-P1D (P2 sub-delta reason-string discipline).** Every `climate_write.reason` for `site='S1_reason_ladder'` on a manual→named write matches one of `s1_manual_write_through:sub_delta_human` or `s1_manual_write_through:zero_delta_ura`; discriminator is a preceding `override_detected` within `SUB_DELTA_WINDOW_S` with `details.delta_f < OVERRIDE_NORMAL_DELTA` (+1 °F coast).

### Falsification queries

| # | Query |
|---|---|
| C1 | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.verb')='set_temperature' AND json_extract(data,'$.site') IN (<5 sites>) AND json_extract(data,'$.reason') NOT LIKE 'human_manual_%';` MUST be 0. |
| C2 | Join `climate_write` × `hvac_excursion_events`(open) per `entity_id` × `[started_ts, stale_ts]`; exclude `excursion_id` matches; count MUST be 0. AND: `override_detected` inside window w/o `details.gated_reason IN ('nudge_win','borrow_active')` MUST be 0. |
| C3 | `override_detected` during active `_nudge_excursion_tokens[zone_id]` w/o `details.gated_reason='nudge_win'` MUST be 0. |
| C5 | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.wire_ok')=1 AND json_extract(data,'$.values_before')=json_extract(data,'$.values_after');` MUST be 0. |
| C-P1A | For every `manual` window with all conditions met per `preset_change_deferred.details.gate_snapshot`: interval to next `climate_write.site='S1_reason_ladder'` `wire_ok=1` MUST be ≤ `HVAC_DECISION_TICK + 30 s`. |
| C-P1B | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.site')='S1_reason_ladder' AND json_extract(data,'$.values_before.preset_mode')='manual' AND (<any of a/b/c/d/e armed per details.gate_snapshot>);` MUST be 0. |
| C-P1C | `SELECT COUNT(*) FROM ura_activity_log a WHERE a.action='climate_write' AND json_extract(a.data,'$.site')='S1_reason_ladder' AND EXISTS (SELECT 1 FROM hvac_immune_holds h WHERE h.zone_id = json_extract(a.data,'$.zone_id') AND h.started_ts < a.ts_issued AND (h.sunset_ts IS NULL OR h.sunset_ts > a.ts_issued));` MUST be 0. |
| C-P1D | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.site')='S1_reason_ladder' AND json_extract(data,'$.reason') NOT IN ('s1_manual_write_through:sub_delta_human', 's1_manual_write_through:zero_delta_ura');` for manual→named writes MUST be 0. |

---

## 1. Institutional context verified

### 1.1 Prior-art scan — REUSE

- `_temp_arrester_override_active` `hvac_override.py:463/858`; `_immune_holds` `:448/656/705/727/838`; **`_corrective_writes_suppressed(zone_id)`** `:660` — pre-existing OR for gate (a/b).
- **Comfort-delay:** `comfort_delay_active(zone_id)` / `_comfort_delay_timers` `:2671/:3141-3143`.
- **Grace timers:** `_grace_timers` (verify field name at build).
- `_compromise_timers` `:220/2153/2885/3449/3476`.
- **DO NOT USE `_override_active`** for gate (c) — leaks under `_apply_compromise` early-return `:3366-3372`.
- `arrester.enabled` `:2816`; log `:2897`; passive-mode double-book at `:3172-3186/:3176`.
- **`is_borrow_active(zone_id)` — NEW pure-read accessor** in `hvac_excursion.py`. No `_reap_stale`, no NM, no DB delete. Signature: `def is_borrow_active(zone_id: str) -> bool: tok = _rows.get(zone_id); return tok is not None and _now() < tok.stale_ts()`. Sweep + NM continue via `_row_present_and_fresh` from `begin_excursion` / boot-audit paths.
- Arrester `_handle_climate_change` — `override_detected` row `hvac_override.py:3028`; precedence chain per M8.
- **Excursion kill switch:** `excursion_primitive_enabled` options field.
- **S10 DPM `hvac.py:3217`** — explicit exclusion + card `HVAC-S10-DPM-VS-S1-1`.
- `SUPPRESS_TTL_SECONDS_PRESET = 120` `hvac_override.py:173/2798`.
- `should_change_preset` consumer: one site — `hvac.py:2626`. S1 site string `S1_reason_ladder` `hvac.py:2821`.
- `_needs_resume_first` `hvac_setpoint.py:331`; `emit_set_preset_mode` `:487`. Row deletion API `hvac_excursion._delete_row`.
- **P1 persistence — REUSE prior art (Institutional Context First):**
  - **DAO shape** — `database.py:8219` `save_excursion_row`, `:8257` `clear_excursion_row`, `:8272` `get_all_excursion_rows`. Model `save_immune_hold_row` / `clear_immune_hold_row` / `get_all_immune_hold_rows` on the same shape. New table `hvac_immune_holds` (schema in §5 D-P1).
  - **Boot-rehydration ordering** — precedent: `hvac_excursion.async_startup_excursion_audit` runs in `async_setup_entry` before `SIGNAL_HVAC_COORDINATOR_READY` fires at `hvac.py:1381`. Add `arrester.async_rehydrate_immune_holds()` next to it.
  - **SwitchEntity + RestoreEntity** — `switch.py:701` (`EnergyObservationModeSwitch`), `:909` (`MemoryNMConditioningSwitch`), `:965` restore-retry pattern. Verify TAO switch (`switch.ura_hvac_coordinator_temp_arrester_override`) subclasses RestoreEntity; if not, add per this precedent.

### 1.2 Prior planning docs consulted

`PLANNING_hvac_governed_excursion.md` (rev-6 lease-strip); `PLANNING_hvac_excursion_restore_unified.md` (parked D2/D3/D4); `PLANNING_hvac_live_room_establishment.md` (Stage 0 SHIPPED v5.103.15); `AUDIT_thermostat_write_paths_2026_09_16`. REV-5 draft superseded.

### 1.3 Memory bodies pulled

`feedback_extend_existing_never_rebuild`, `feedback_wire_in_anchor_mandatory`, `feedback_suppression_needs_discharge`, `feedback_mutation_verification_pycache_staleness`, `feedback_no_soak`, `feedback_tier2plus_prior_art_scan`, `feedback_falsify_before_asserting`, `feedback_hollow_test_anchors`, `feedback_marginal_benefit_pushback`, `project_single_user_no_backcompat`, `project_reload_storm_refuted_restart_storm_live` (relevant to P1).

### 1.4 REV-3/4/5 plan-review findings folded

All prior CRIT/HIGH survivors retained. REV-5 draft's two Tier-3 plan reviews (both FIX-PLAN) folded as M1-M12 + Also-* above.

### 1.5 Design docs read

`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §9e (authoritative). `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2. `README_v5.103.16/17/v3.9.0`.

### 1.6 Code locations surveyed (with refreshed lines)

`hvac_preset.py:202-217`; `hvac.py:1371/1381` (READY signal), `:1748/1760` (S1 vs check_ac_reset), `:2623-2625` (vacancy bypass), `:2626`/`:2775`/`:2821`, `:3217` (S10); `hvac_override.py:2671`, `:2897`, `:3028`, `:3050-3100`, `:3105`, `:3130-3143`, `:3172-3186`, `:3366-3372`, `:3383`, `:4442`, `:660`, `:705`, `:727`, `:838`; `hvac_excursion.py:562-579` (side effects), `:6-16` (lease-strip); `hvac_predict.py:1046/1128/1419/1515-1583`; `hvac_egress.py:655`; `hvac_setpoint.py:331/487`; `hvac_const.py:361/452-456/531-532`; `database.py:8219/8257/8272`; `switch.py:701/909/965`.

---

## 2. Non-goals

- No provenance chain, kill-switch entity, drift sensor.
- **No `BORROW_LOCK` funnel-side gate.**
- No confirmation oracle / bounded retry.
- No knob-expiry reclaim (closed-by-A).
- No human-ends-borrow on NUDGE (ruling 13).
- No new state listeners.
- No `set_temperature` migration beyond D2.4.
- **No changes inside `begin_excursion` / `return_excursion` / any borrow code beyond the new pure-read `is_borrow_active` accessor.**
- **No changes inside `emit_*` funnels; strategy layer owns `last_sent` + no-op suppression.**
- No Nest strategy code.
- **S10 DPM vs S1: explicit exclusion; card `HVAC-S10-DPM-VS-S1-1`.**
- **Grace/comfort/compromise timers NOT persisted (operator P1 carve-out); accepted ≤ 20 min exposure on restart.**
- No NM on sub-delta human manual reclaim (operator P2).

---

## 3. D0 — Read-only measurement (Alt-A form; not a merge blocker)

CONFIG-FIRST refresh; nudge-effectiveness sanity read; optional §9.1 replay.

---

## 4. Deliverable order (REV 6)

1. **D0** (Alt-A form).
2. **D1** — Strategy interface, quad-state `WriteResult`, strategy-layer `last_sent` + no-op (M5). Funnels untouched.
3. **D4** — module constants: `S1_RECLAIM_RATE_LIMIT_N = 3`; `HVAC_COMPROMISE_MINUTES_MAX = 15`; `SUB_DELTA_WINDOW_S = 300`. Rung 1 all.
4. **D4a** — UI-max clamp + default reduction (M11).
5. **D-P1** — Immune-hold persistence (operator P1 ruling; NEW).
6. **D5** — generic default.
7. **D2** — §5.P1 four-gate helper + `should_change_preset` replacement + `preset_change_deferred` telemetry + arrester `_handle_climate_change` gated_reason precedence + §5.P5 reclaim-rate NM + §5 D2.4 five-site migration + §5 D2a strategy `last_sent`.
8. **Live-validation write-back**.

---

## 5. Deliverables

### D1 — Strategy interface

Quad-state `WriteResult` (`APPLIED / SKIPPED_ALREADY_CORRECT / DEFERRED / FAILED`). Strategy layer owns `last_sent[entity_id][verb]` + no-op suppression. Returns KEEP resume-then-pin (`allow_resume=False` dropped). `_snapshot_climate_state` exempt.

Acceptance: `test_strategy_no_op_returns_skipped`; `test_last_sent_lives_in_strategy_not_funnel` (grep `hvac_setpoint.py` for `last_sent` MUST be 0); `test_returns_still_emit_resume_then_pin_via_needs_resume_first`.

### D-P1 — Immune-hold persistence (operator P1 ruling; NEW)

**Schema:** new table `hvac_immune_holds`
```
CREATE TABLE hvac_immune_holds (
  zone_id            TEXT PRIMARY KEY,
  holder_user_name   TEXT,
  holder_person_id   TEXT,
  started_ts         REAL NOT NULL,
  sunset_basis       TEXT NOT NULL,          -- 'next_activity' | 'durable_house_state' | 'timer_4h'
  sunset_ts          REAL,                    -- non-NULL when computable (timer_4h); NULL for event-driven
  values_before_snapshot TEXT                 -- JSON: pre-hold setpoints/preset (for diagnostics)
);
CREATE INDEX idx_hvac_immune_holds_started_ts ON hvac_immune_holds(started_ts);
```

**DAO** — new methods on `Database` (`database.py`), modelled on `save_excursion_row` / `clear_excursion_row` / `get_all_excursion_rows`:
```
async def save_immune_hold_row(self, row: dict) -> None
async def clear_immune_hold_row(self, zone_id: str) -> None
async def get_all_immune_hold_rows(self) -> list[dict]
```

**Write side.** Every `_stamp_immune_hold` (`hvac_override.py:705`) calls `save_immune_hold_row(...)` in the same commit. Every `sunset_immune_holds` / `_immune_holds.pop` (`:727/838`) calls `clear_immune_hold_row(zone_id)` in the same commit. Failure of the DB write does NOT block the in-memory stamp (belt-and-suspenders; on next restart the row is missing → gate (a/b) not armed → surface as a low-severity NM `immune_hold_persistence_gap` for operator awareness — Rung 1).

**Boot rehydration.** New method `arrester.async_rehydrate_immune_holds(hass)`:
```
rows = await db.get_all_immune_hold_rows()
for row in rows:
    self._immune_holds[row['zone_id']] = {
        'user_name': row['holder_user_name'],
        'person_id': row['holder_person_id'],
        'started_ts': row['started_ts'],
        'sunset_basis': row['sunset_basis'],
        'sunset_ts': row['sunset_ts'],
        'values_before_snapshot': json.loads(row['values_before_snapshot'] or '{}'),
    }
# Optionally schedule the 4h timer for 'timer_4h' rows whose sunset_ts is in the future.
```

Called from `async_setup_entry` NEXT TO `hvac_excursion.async_startup_excursion_audit`, BEFORE `SIGNAL_HVAC_COORDINATOR_READY` fires at `hvac.py:1381`. Gate (a/b) via `_corrective_writes_suppressed(zone_id)` (`hvac_override.py:660`) then sees the rehydrated row on the first tick at `hvac.py:1371`.

**Grace / comfort / compromise NOT persisted (verbatim operator carve-out).** Accepted exposure ≤ 20 min (Comfort Grace live 20 min, `hvac_const.py:452-456`). Documented; no code beyond leaving those dicts empty on boot.

**TAO switch restore.** Verify at build: `switch.ura_hvac_coordinator_temp_arrester_override` subclasses `RestoreEntity` (per `switch.py:701`/`:909` precedent). If yes: no change. If no: add per `switch.py:965` restore-retry precedent. Gate (a/b) then sees restored TAO on first tick.

**Acceptance (mandatory):**
- `test_immune_hold_persists_across_restart` — stamp; simulate restart; assert `_immune_holds['zone_1']` populated before first S1 tick; assert `_corrective_writes_suppressed('zone_1')` True; assert S1 does NOT reclaim.
- `test_immune_hold_sunset_deletes_db_row` — parametric across 3 sunset paths (next_activity / durable house-state / 4 h timer); DB row cleared.
- `test_immune_hold_dao_shape_matches_excursion_dao` — assert the three method signatures match the `save_excursion_row` pattern (reflection-based).
- `test_immune_hold_boot_rehydration_before_ready_signal` — order-of-operations assertion via a captured call log; rehydration precedes `SIGNAL_HVAC_COORDINATOR_READY`.
- `test_tao_switch_restore_entity` — verify TAO switch class inheritance; simulate restart with TAO on; assert TAO state restored.
- **Reviewer C mutation:** delete the `async_rehydrate_immune_holds` call in `async_setup_entry` → `test_immune_hold_persists_across_restart` RED with specific named failure.
- **Live:** post-deploy, place immune hold via Bryant app; restart HA; observe restore.

### D2 — Carrier strategy

#### §5.P1 — S1 manual-guard replacement (Alt A; REV-6 fixed gates)

Change site `hvac_preset.py:202-217`. Applies to ALL brands (Also-4). Signature carries `zone_id`. Helper injected via `set_arrester(arrester)` (Also-1); arrester-None → `(True, 'arrester_not_wired')` fail-closed.

**FOUR gates:**

| Gate | Condition | Signals | Reason string |
|---|---|---|---|
| **(a/b)** | Reuse pre-existing OR. Post-P1: signals include rehydrated immune holds after restart. | `arrester._corrective_writes_suppressed(zone_id)` (`hvac_override.py:660`) | `"person_protected_hold"` |
| **(c)** | Comfort-delay OR grace OR compromise. **Not `_override_active`.** | `comfort_delay_active(zone_id)` (`:2671`) OR `zone_id in _grace_timers` (verify at build) OR `zone_id in _compromise_timers` (`:220/3449`) | `"arrester_active_window"` (+ sub-reason in `details`) |
| **(d)** | Arrester off. Accessor reads OPTIONS until `SIGNAL_HVAC_COORDINATOR_READY` fires (M10). | `not arrester.enabled` | `"arrester_disabled_passive"` |
| **(e)** | Fresh row OR arrester-timer fallback. Pure read. | `is_borrow_active(zone_id)` OR `zone_id in arrester._nudge_excursion_tokens` OR `zone_id in arrester._nudge_restore_timers` OR `zone_id in arrester._compromise_timers` | `"active_borrow"` (+ sub-source in `details`) |

**Vacancy/runtime bypass (M3).** `hvac.py:2623-2625` also checks (a/b) + (e); logs `preset_change_deferred:vacancy_bypass_deferred:<gate>`. Gate (c) and (d) do NOT block vacancy bypass (documented explicitly).

**Arrester booking (M8).** `_handle_climate_change` at `override_detected` row `hvac_override.py:3028`, `details.gated_reason` by precedence (top-down):
1. Immune stamp (`:3050-3100`) → `'immune_stamp'`.
2. TAO skip (`:3105`) → no row.
3. Comfort grant (`:3130-3143`) → `'comfort_grant'`.
4. Gate (e) True → `'nudge_win'` if `_nudge_excursion_tokens[zone_id]` else `'borrow_active'`; skip revert.
5. Passive mode (`:3172-3186`) → `'passive_mode'` (dedup: only if no higher-precedence gate matched).

`details.gate_snapshot` in every row (for C-P1B falsifier).

**Ledger rewrite.** `hvac.py:2616-2675` `preset_change_locked_out` → `preset_change_deferred` with `{reason, gate_snapshot: {a_b, c, d, e, e_source, c_source}}`.

**Sub-delta human reason string (operator P2, verbatim).** At the S1 write site, when the write moves the zone out of `manual`:
- If a preceding `override_detected` on the entity within `SUB_DELTA_WINDOW_S = 300 s` has `details.delta_f < OVERRIDE_NORMAL_DELTA` (or `< OVERRIDE_NORMAL_DELTA + 1` under coast per `hvac_const.py:531-532`) → `reason = 's1_manual_write_through:sub_delta_human'`.
- Else → `reason = 's1_manual_write_through:zero_delta_ura'`.
- No NM. `preset_deferrals_today` unchanged (this is a write, not a deferral).

**Step-by-step (genuine human manual grace → compromise → S4).** As REV 5: gate (c) armed via comfort-delay/grace; compromise adds gate (e); both refuse; S4 clears both; S1 writes over on next tick.

**Acceptance (Alt A, REV-6, additive):**
- `test_gate_a_b_via_corrective_writes_suppressed` (TAO / non-operator immune).
- `test_gate_c_comfort_delay_grace_compromise` (parametric).
- `test_gate_c_does_not_leak_under_compromise_early_return` (M1 discriminator against `_override_active`).
- `test_gate_d_reload_window` (options-first accessor pre-READY).
- `test_gate_e_all_kinds_and_all_fallbacks` (M2 begin-None cases).
- `test_gate_e_pure_read_no_side_effects` (no `_reap_stale`).
- `test_vacancy_bypass_defers_under_borrow_and_tao` (M3).
- `test_arrester_gated_reason_precedence` (M8 five rungs).
- `test_passive_mode_no_longer_double_books`.
- `test_preset_manager_arrester_none_fails_closed`.
- `test_s1_site_string_is_S1_reason_ladder` (M12).
- **P2 tests:** `test_sub_delta_human_reclaim_reason_string`; `test_zero_delta_ura_reclaim_reason_string`; `test_coast_threshold_uses_plus_one`; `test_no_nm_fires_on_sub_delta_reclaim`.
- Per-site mutation of each of the 4 gates (.pyc-safe).
- Drill M10: neuter `begin_excursion` → gate (e) still armed via timer fallback → S1 refuses.
- **Live:** §9.1 four historical strands → written over within one S1 tick.

#### §5.P2 — Supersession triage (unchanged)

DELETE post-PASS: `hvac_excursion.py:629-650`; cards `HVAC-PRESET-LOCKOUT-ESCAPE-1`, `HVAC-ZONE1-MANUAL-OSCILLATION-1`. KEEP+WIRE: `hvac.py:2616-2675` → `preset_change_deferred`. KEEP+DOCUMENT: `hvac_predict.py:1540-1580`.

#### §5.P3 — Write volume + preset-kind suppression (REV-6)

~27 nudges/day house-wide × 2 wire calls = ~54 extra Carrier writes/day. `hvac.py:2775` `suppress(kind="preset")` (120 s); preset-suppression covers URA's reclaim echo which lands on `preset=<target>`, not on `manual`. `test_s1_manual_write_through_sets_preset_kind_suppression` MUST be RED on `develop`, GREEN after fix.

Counter renames: `preset_deferrals_today` (per-gate breakdown); `nudge_win` suppresses `arrester_reverts_today`.

#### §5.P4 — Problem 4 closed-by-A (unchanged)

`test_person_protected_hold_sunset_s1_reclaims_next_tick`.

#### §5.P5 — S1 reclaim-rate anomaly trip-wire (M4)

`S1_RECLAIM_RATE_LIMIT_N = 3` (Rung 1; infinity = disable) in 30 min → NM `s1_reclaim_rate_high` (medium) with `{zone_id, count, window_s, recent_reasons}`. Discharge: rate drops below N.

Acceptance: `test_s1_reclaim_rate_nm_fires_at_N_plus_1`; `test_s1_reclaim_rate_nm_discharges_after_window`.

#### D2.1 Same-tick nudge-start skip (M7)

`_zones_written_this_cycle: set[str]` populated by S1's `climate_write`; consumed by `check_ac_reset`; cleared at cycle end.

#### D2.4 Presets-only returns — 5-site inventory (unchanged from REV 5 + M6)

Five sites: `hvac_override.py:4650`, `:5877`, `:6289`, `hvac_predict.py:984`, `:1520`. HUMAN_MANUAL := `pre_preset ∈ {manual, None, ""}`.

**M6:**
- S11 `_release_ok` self-exclusion: `is_borrow_active(zone) AND active_row.excursion_id != self_token.excursion_id`.
- S11 comfort gate onto preset write `hvac_predict.py:1046` (`gate=lambda: not self._s11_gate.deferred`).
- S13 block restructure `:1515-1583`: setpoint (`:1520`) dropped; preset (`:1570`) sole restore; `_last_emitted_range` update moves to preset site (or the strategy-layer `last_sent` replaces it — verify at build).

#### D2.5 No-op suppression — MOVED TO STRATEGY LAYER (M5)

Funnels untouched. Grep `hvac_setpoint.py` for `last_sent` / `SKIPPED_ALREADY_CORRECT` → MUST be 0.

#### D2.6 Consumer wiring — behavioural anchors + AST lint

Also-2 test rewrites: `test_hvac_offphase_removed.py`, `test_hvac_live_room_hold_wire_in.py`, `test_v4511_ac_energy_aware_ramp_down.py`, `test_preset_hold_contract_resume_then_pin.py::test_lockout_*` — behavioural, gate-state-driven.

#### D2.8 28-site write table (unchanged)

S1 site 2 writes with `reason` per §5.P1 P2 discriminator; `site='S1_reason_ladder'`.

#### D2a — Strategy-layer `last_sent` (M5)

Owns per-verb `last_sent[entity_id][verb] = (values, ts)`. Replaces funnel-side `_last_emitted_range` for no-op purposes. `HvacZoneBaseline` (S10 comfort baseline) stays separate.

### D4 — Module constants

| Constant | Value | Rung |
|---|---|---|
| `S1_RECLAIM_RATE_LIMIT_N` | 3 | 1 |
| `HVAC_COMPROMISE_MINUTES_MAX` | 15 | 1 |
| `SUB_DELTA_WINDOW_S` | 300 | 1 |

### D4a — UI clamp + default reduction (M11)

`config_flow.py:6106` max 120 → 15. `hvac_const.py:361` `DEFAULT_COMPROMISE_MINUTES` 30 → 15. Defaults at `hvac.py:165` and `hvac_override.py:191` → 15. Named constant `HVAC_COMPROMISE_MINUTES_MAX = 15`. Clamp-on-read helper `_read_hvac_compromise_minutes(options)` in `hvac_const.py`; consumer `__init__.py:3804/3862`.

### D5 — Generic default (unchanged)

---

## 6. Operator questions

**None remaining.** P1 = persist (D-P1). P2 = accept + log (§5.P1 reason discriminator). Signature-change note (W2 fast-path lines 234/349/588) is a mechanical follow-up, not a question.

---

## 7. Ship gate

Pre-deploy replay: §9.1 four historical strands + four-gate parametric + gate-(e) discharge matrix (row return / stale reap / sweep / boot audit) + reload-window drill (M10) + suppression-kind drill (M4) + vacancy-bypass drill (M3) + S11/S13 self-block drills (M6) + same-tick drill (M7) + arrester precedence drill (M8) + reclaim-rate NM drill (§5.P5) + **P1 restart drill** (D-P1) + **P2 reason-string drill** + S10 exclusion probe (assert no fight while `guest_mode_actuation` off).

Post-deploy disposition at N ≥ 10 non-nudge return episodes per zone (7-day cap). §0 queries; gate snapshot in `details`.

PASS → dispose + §5.P2 DELETE-bucket + confirm card `HVAC-S10-DPM-VS-S1-1` sibling exists.

---

## 8. Review protocol — Tier 3 (4 framing-disjoint + orchestrator hand-check + operator checkpoint)

**Reviewer A.** Four gates at correct signals; precedence chain at `:3028`; `_release_ok` self-exclusion; D2.4 five-site coverage; D4a all three default sites reduced to 15; **P1 DAO shape matches excursion DAO precedent**; **P2 reason-string discriminator arithmetic.**

**Reviewer B.** No funnel-side gate; `is_borrow_active` side-effect free; reload window (M10); `_apply_compromise` early-return doesn't leak into (c); vacancy bypass respects (a/b)+(e); passive-mode dedup; same-tick set cleared at cycle end; boot-audit rehydration covered by (e) via `stale_ts`; **P1: rehydration precedes `SIGNAL_HVAC_COORDINATOR_READY`; DB failure surfaces as low-severity NM; grace/comfort/compromise NOT rehydrated (verbatim carve-out)**; **P2: no NM on sub-delta reclaim (verify NM channels silent).**

**Reviewer C.** Each of the 4 gates mutated; each of 5 `begin_excursion` sites deferred; drill M10; arrester precedence rungs mutated; grep `hvac_setpoint.py` for `last_sent` MUST be 0 (lint failure); **P1: neuter rehydration call → `test_immune_hold_persists_across_restart` RED**; **P2: flip delta comparator → sub_delta/zero_delta reason strings swap.**

**Reviewer D.** Re-enumerate every path that could set `hold_activity == manual` from URA; confirm gate (e) covers all five borrow kinds via row OR arrester-timer fallback; confirm `_handle_climate_change` reads same source; confirm precedence top-down and no double-book; falsify INV C1..C-P1D; **verify restart storm doesn't reintroduce lockout for immune-hold zones (P1 rehydration wins); verify sub-delta case is silent + reason-string discriminates (P2).**

**Orchestrator hand-check before deploy:** re-grep 28 sites + 5 begin sites; mutation of each gate + each migrated site + each begin-site defer; AST lint; §9.1 replay; reload-window, suppression-kind, vacancy-bypass, S11/S13 self-block, arrester precedence, reclaim-rate NM drills; **P1 restart drill (simulate boot, assert rehydration completes pre-READY); P2 reason-string drill**; grep `hvac_setpoint.py` for `last_sent` (MUST be 0); slider max = 15 and defaults = 15.

**Operator checkpoint:** four-gate demo; P1 restart demo; P2 log-only demo; false-positive-under-restart sanity check.

---

## 9. Sequencing / dependencies

1. W1-A SHIPPED v5.103.16. 2. Echo-fix SHIPPED v5.103.17. 3. Alt A APPROVED + REV-5 collapse + REV-6 review-fold + **operator P1/P2 rulings folded (this REV)**. 4. Two Tier-3 plan reviews on this REV 6 (the focused re-review the orchestrator will run before build). 5. Build via new `ura-super-builder` agent in worktree `.claude/worktrees/hvac-w1b-thermostat-definition`. 6. Build order per §4. W2 fast-path plan lines 234/349/588 signature-updated. 7. Four framing-disjoint reviews. 8. Operator checkpoint. Deploy. 9. Live-validation write-back. 10. Disposition at N ≥ 10. 11. On PASS: §5.P2 DELETE-bucket.

**No soak.**

---

## Operator decisions — BINDING (verbatim; annotate, never edit earlier text)

**REV 3 (2026-09-26):** 1-7 verbatim + prior annotations. [REV-6 no changes.]

**REV 4 (2026-09-26 evening):** 8-12 verbatim + prior annotations. [REV-6 no changes.]

**REV 5 (2026-09-27):** 13-16 verbatim + prior annotations. [REV-6 no changes.]

**Mid-turn (2026-09-27):** Alt A APPROVED; gate (e) added; REV-5 BORROW_LOCK collapse.

**REV 6 (2026-09-27, Tier-3 plan-review fold + operator SIMPLIFY + P1/P2 rulings):**

17. **P1 = PERSIST IMMUNE HOLDS.** Operator verbatim (2026-09-27): *"Persist the immune-person hold (zone, holder, start, sunset basis) so it survives a restart and gate (a/b) re-arms at boot before S1's first tick. Grace timers and comfort grants are NOT persisted. The accepted exposure is ≤ 20 min on restart."* Spec: §5 D-P1 (new DAO on `database.py` modelled on `save_excursion_row` precedent; rehydration before `SIGNAL_HVAC_COORDINATOR_READY`; TAO switch RestoreEntity verified/added; ≤ 20 min accepted exposure carve-out documented). Restart test + mutation drill mandatory.
18. **P2 = ACCEPT + LOG.** Operator verbatim (2026-09-27): *"Within-tolerance human manuals (<1 °F, or <2 °F in coast) are reclaimed by S1 on its next tick with no grace and no NM. The reclaim row records the reason so it is visible in the log."* Spec: `SUB_DELTA_WINDOW_S = 300 s`; reason discriminator `s1_manual_write_through:sub_delta_human` vs `s1_manual_write_through:zero_delta_ura`; no NM; test that pins the behaviour.
19-27. Gate corrections (M1), gate (e) with pure-read accessor (M2), vacancy-bypass (M3), preset-kind suppression + reclaim-rate NM (M4), operator-constraint restoration (M5), S11/S13 fixes (M6), same-tick (M7), arrester booking precedence (M8), S10 explicit exclusion (M9). [As detailed in the change log.]
28. Gate (d) reload window (M10).
29. D4a defaults + named clamp constant (M11).
30. Acceptance queries corrected + gate snapshot in details + HUMAN_MANUAL definition + C-P1A carve-outs (M12).
31. PresetManager arrester injection (Also-1).
32. Behavioural test replacements (Also-2).
33. Counter renames (Also-3).
34. All-brands scope (Also-4).
35. Line refresh (Also-6).

---

## REV 6 delta summary (for reviewers)

- **Operator ruled P1 = persist, P2 = accept+log.** Both folded verbatim into front matter + decisions 17-18 + §5 D-P1 (new) + §5.P1 reason discriminator + §7 restart drill + acceptance tests.
- **P1 REUSE cited:** `database.py:8219/8257/8272` DAO shape; `hvac_excursion.async_startup_excursion_audit` rehydration ordering; `switch.py:701/909/965` RestoreEntity precedent for TAO.
- **P2 constants:** `SUB_DELTA_WINDOW_S = 300 s`; reason strings grep-friendly; no NM channel touched.
- **Gates corrected:** (a/b) via `_corrective_writes_suppressed` (post-P1 also sees rehydrated immune holds); (c) comfort-delay + grace + compromise timers (not `_override_active`); (d) reload-window fix; (e) NEW pure-read `is_borrow_active` + arrester-timer fallback.
- **Vacancy bypass** checks (a/b) + (e); C2/C-P1B manual-qualified with bypass carve-out.
- **Preset-kind suppression** fix at `hvac.py:2775`; reclaim-rate NM trip-wire.
- **Operator constraint enforced:** no-op + `last_sent` in strategy; funnels untouched; `allow_resume=False` dropped; resume-then-pin kept.
- **Arrester `_handle_climate_change:3028`** with precedence chain in `details.gated_reason`; passive-mode dedup.
- **S10 DPM:** explicit exclusion + card sibling.
- **D4a:** all three default sites reduced to 15 + named constant.
- **Accept criteria:** `S1_reason_ladder` site string; gate snapshot in `details`; HUMAN_MANUAL definition; C-P1A carve-outs.
- **Injection + test rewrites + counters + brand scope + LOWs** folded.

**Falsifiable invariant (one sentence, REV 6 + P1/P2):** on any thermostat zone, no URA borrow return writes a raw setpoint (except HUMAN_MANUAL); while `is_borrow_active(zone_id)` is True and the zone reads `manual`, S1 emits zero preset writes and the vacancy bypass does not write `away`; the arrester at `hvac_override.py:3028` books `override_detected` with `details.gated_reason` per precedence and skips revert where the gate wins; the nudge wins over any human change for its duration; the strategy layer emits zero service calls on a proven no-op; while the arrester is enabled and none of the four Alt-A gates is armed, S1 leaves the zone in `manual` for at most one decision tick (with carve-outs for night-trust / row-1 transient / dwell); **an immune-person hold persisted via `hvac_immune_holds` re-arms gate (a/b) on the first post-restart tick, so S1 never reclaims across a restart while the DB row is present; every S1 manual write-through carries a reason string that discriminates `sub_delta_human` from `zero_delta_ura` and fires no NM.**

**Open questions: none.** Ready for the orchestrator's focused re-review, then build via `ura-super-builder`.
