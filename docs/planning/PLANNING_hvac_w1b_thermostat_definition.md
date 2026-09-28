# PLANNING — HVAC W1-B: Per-brand thermostat definition (Carrier/Bryant first) — REV 7

## OPERATOR RULINGS ON PRIOR HOLDS — RESOLVED (binding; verbatim)

### P1 = **PERSIST IMMUNE HOLDS** (operator 2026-09-27; REV-7 mechanism per N7)

*"Persist the immune-person hold (zone, holder, start, sunset basis) so it survives a restart and gate (a/b) re-arms at boot before S1's first tick. Grace timers and comfort grants are NOT persisted. The accepted exposure is ≤ 20 min on restart."*

Mechanism (N7): store side-key `_zone_state_store.__immune_holds` following `__person_zone_map` / `__short_cycles_today` precedent (`hvac.py:1809/1815`). NO new DB table. See §5 D-P1.

### P2 = **ACCEPT + LOG** (operator 2026-09-27; REV-7 refinement per N4)

*"Within-tolerance human manuals (<1 °F, or <2 °F in coast) are reclaimed by S1 on its next tick with no grace and no NM. The reclaim row records the reason so it is visible in the log."*

Landing spot (N4): `details.manual_class ∈ {sub_delta_human, zero_delta_ura, not_manual}`. Reason ladder preserved. Episode-scoped. `SUB_DELTA_WINDOW_S` dropped.

### TAO across restart = **RESTORE TAO IF STILL IN WINDOW** (operator 2026-09-27, decision 46)

*"Option (ii), Restore TAO if still in window."*

Landing spot: §5 D-P1a. Persist `(started_ts, expires_at)` for TAO in the SAME `_zone_state_store` snapshot under side-key `__tao_state`. Restore TAO ON at boot iff `dt_util.now() < expires_at`. Max window = `HVAC_ARRESTER_OVERRIDE_MAX_S = 6 h` (`hvac_const.py:205`).

---

> **Alt A APPROVED 2026-09-27.** All prior REV-3..REV-6 decisions retained verbatim + prior annotations. **REV 7 folds the focused re-review (FIX-PLAN) + operator TAO-across-restart ruling.** Ledger discipline preserved.

**Card:** `HVAC-W1-THERMOSTAT-DEFINITION` (Stage B). **Tier:** Tier 3 (NOT Tier 2-DB — N7 removed the DDL trigger).
**Depends on:** W1-A SHIPPED v5.103.16; echo-fix SHIPPED v5.103.17.

**MANDATORY reads:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all — §9e); `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2; `README_v5.103.16/17/v3.9.0`; `hvac_excursion.py:6-16`; `hvac.py:665/1053/1809-1819` (store precedent); `hvac_override.py:463-464/705-720/777-796/825/834/838` (immune-hold + TAO in-memory); `hvac_const.py:205` (TAO max window); `switch.py:2429` (`HVACTempArresterOverrideSwitch`); card `operator_rulings_2026_09_27`.

---

## REV 7 change log — focused re-review fold + TAO ruling

| # | REV-7 fix | Where |
|---|---|---|
| N7 | Persist via `_zone_state_store` side-key `__immune_holds`, NOT new DAO/table. Rehydrate in `HVACCoordinator.async_setup` (`hvac.py:1309`) BEFORE first cycle at `:1372`. | §5 D-P1. |
| N1 | Mirror exact in-memory record shape (`hvac_override.py:714-720`): user_id/user_name/person_entity/started_ts/next_activity_ts/pending_sunset_state. ISO datetimes; aware on load; sunset gates at `:825/:834` preserved. | §5 D-P1. |
| **N2 RESOLVED — TAO restore approved (decision 46, option (ii)).** | Persist `(started_ts, expires_at)` for TAO in `_zone_state_store.__tao_state`. Restore TAO ON iff `now < expires_at`. Max window = 6 h (`hvac_const.py:205`). F7 annotated as SUPERSEDED for this reason; do NOT delete F7 text elsewhere. **Implementation channel — chosen: coordinator sets TAO from the store before the first cycle** (see §5 D-P1a justification). | §5 D-P1a NEW; front matter open-question removed; F7 annotation. |
| N3 | Restructure `_handle_climate_change`: move `override_detected` row write from `:3028` to AFTER delta computation at `:3195` (single-row, carries `delta_f` + `gated_reason`). In-memory `arrester.last_detection_for(entity_id)` — no DB read on decision path. Precedence top-down with **nudge_win at the TOP** so C3 holds. | §5.P1 arrester booking. |
| R1-H1 / R2-H5 | Gate (e) extends to BANKING/PREHEAT/EGRESS via `hvac_predict.py:1128-1147`, `:1419-1437`, `hvac_egress.py:655-670` (build verifies exact attribute names). | §5.P1 gate (e). |
| N5 | S11: `_s11_gate` polarity corrected (local func `hvac_predict.py:972-978`, True=DEFER). `_release_ok` uses new pure-read `hvac_excursion.excursion_id_for(zone_id)` for self-exclusion. `last_emitted` update at `:1003-1006` relocated. | §5 D2.4 M6. |
| N4 | P2 → `details.manual_class`; reason ladder preserved; episode-scoped. `SUB_DELTA_WINDOW_S` dropped. | Front matter P2 + §5.P1. |
| N6 | Falsifiers runnable: C-P1C queries `ura_activity_log` for `immune_hold_stamped`/`immune_hold_sunset` ledger rows; `ts_issued` via `json_extract`; C2 nudge windows use `ac_ramp_events`. | §0 queries. |
| N8 | Rehydration invariant: `async_setup` load path (`hvac.py:1053-1309`) before first cycle at `:1372`, NOT `SIGNAL_HVAC_COORDINATOR_READY`. | §5 D-P1. |
| N9 | `HVAC-S10-DPM-VS-S1-1` card text minted (§5.P6). Same-tick set resets at cycle ENTRY (N9a). README notes vacancy-bypass-defers-under-TAO (N9b). | §5.P6, D2.1, §9. |

Ledger discipline: decisions 1-35 kept verbatim + prior annotations; REV-7 decisions 36-46 appended.

---

## 0. Falsifiable invariant

> **INV-W1B (REV 7).** On any thermostat zone, over §7 floor:
>
> **C1.** Every URA borrow return emits ZERO `set_temperature` except HUMAN_MANUAL snapshots (5 sites).
>
> **C2.** While `is_borrow_active(zone_id)` OR arrester-timer/token fallback for any of the 5 kinds is True: (i) if `preset_mode='manual'`, S1 emits ZERO preset writes at `S1_reason_ladder`; (ii) vacancy bypass `hvac.py:2623-2625` refuses; (iii) arrester books `details.gated_reason ∈ {'nudge_win','borrow_active'}` and skips revert. Borrow's own return exempt via `excursion_id`.
>
> **C3.** During a live NUDGE, the single `override_detected` row carries `details.gated_reason='nudge_win'` regardless of immune-stamp or comfort-grant — nudge_win short-circuits at the TOP of precedence. No revert.
>
> **C5.** `Strategy.hold_preset` returns SKIPPED_ALREADY_CORRECT on no-op; ZERO service calls. Funnels untouched.
>
> **C-P1A.** Arrester enabled AND `_corrective_writes_suppressed(zone_id)=False` AND no comfort-delay/grace/compromise armed AND gate (e) False AND effective_preset != "manual" AND not under night-trust/row-1/dwell → S1 leaves manual for at most one decision tick.
>
> **C-P1B.** When zone reads manual, S1 emits ZERO preset writes at `S1_reason_ladder` while ANY of the four Alt-A gates armed.
>
> **C-P1C (P1 restart survivability).** For every `immune_hold_stamped` ledger row (§5 D-P1 ledger emit), no `climate_write.site='S1_reason_ladder'` fires on the same zone_id between that stamp and the matching `immune_hold_sunset` row. Queryable from `ura_activity_log` alone.
>
> **C-P1D (P2 discipline; A-M1 / D-LOW 2026-09-27).** For every S1 `preset_change` row whose paired `climate_write.site='S1_reason_ladder'` has `values_before.preset_mode='manual'`: `details.manual_class ∈ {'sub_delta_human','zero_delta_ura','gated_human','unknown'}` — `zero_delta_ura` iff the episode's booked `delta_f == 0`; `sub_delta_human` iff `0 < |delta_f| <` threshold (+1 F coast); `gated_human` iff `|delta_f| >=` threshold (gated by immune/comfort/TAO or a failed/expired arrest); `unknown` iff no detection was booked in the episode (incl. after a restart). Reason ladder unchanged. No NM.
>
> **C-P1E (TAO restart survivability — decision 46).** For every restart at time `t_boot`: if `_zone_state_store.__tao_state.expires_at > t_boot`, TAO switch is ON on the first cycle and `_temp_arrester_override_active` is True; if `expires_at <= t_boot`, TAO is OFF; in EITHER case no `climate_write.site='S1_reason_ladder'` occurs on a zone reading `manual` before the store-derived TAO state is applied.

### Falsification queries (REV-7 corrected per N6)

| # | Query |
|---|---|
| C1 | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.verb')='set_temperature' AND json_extract(data,'$.site') IN (<5 sites>) AND json_extract(data,'$.reason') NOT LIKE 'human_manual_%';` MUST be 0. |
| C2 | Nudges → join `climate_write` × `ac_ramp_events`(`nudge_started`..`nudge_settled`) per `entity_id`; exclude `excursion_id` matches; count MUST be 0. Other kinds → join × `hvac_excursion_events`. Plus: `override_detected` inside window w/o `details.gated_reason IN ('nudge_win','borrow_active')` MUST be 0. |
| C3 | `override_detected` during active nudge window (either `_nudge_excursion_tokens[zone_id]` OR `ac_ramp_events.nudge_started..nudge_settled`) w/o `details.gated_reason='nudge_win'` MUST be 0. |
| C5 | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.wire_ok')=1 AND json_extract(data,'$.values_before')=json_extract(data,'$.values_after');` MUST be 0. |
| C-P1A | Per `preset_change_deferred.details.gate_snapshot`: interval to next `climate_write.site='S1_reason_ladder'` MUST be ≤ `HVAC_DECISION_TICK + 30 s`. `ts_issued` via `json_extract(data,'$.ts_issued')`. |
| C-P1B | (A-M2 rewrite — `gate_snapshot` lives on S1's own `preset_change` row, the funnel payload is untouched) `SELECT COUNT(*) FROM ura_activity_log p JOIN ura_activity_log w ON w.action='climate_write' AND json_extract(w.details_json,'$.site') LIKE 'S1_reason_ladder%' AND w.zone=p.zone AND abs(julianday(w.timestamp)-julianday(p.timestamp))*86400 < 5 WHERE p.action='preset_change' AND json_extract(w.details_json,'$.values_before.preset_mode')='manual' AND (json_extract(p.details_json,'$.gate_snapshot.a_b')=1 OR json_extract(p.details_json,'$.gate_snapshot.c')=1 OR json_extract(p.details_json,'$.gate_snapshot.d')=1 OR json_extract(p.details_json,'$.gate_snapshot.e')=1 OR json_extract(p.details_json,'$.gate_snapshot.f')=1);` MUST be 0. |
| C-P1C | Join stamps/sunsets from `ura_activity_log` where `action IN ('immune_hold_stamped','immune_hold_sunset')`; find any `climate_write.site='S1_reason_ladder'` on the same `zone_id` between a stamp's `ts_issued` and the matching sunset's `ts_issued`. MUST be 0. |
| C-P1D | (A-M2 rewrite, same join as C-P1B) `SELECT COUNT(*) FROM ura_activity_log p JOIN ura_activity_log w ON w.action='climate_write' AND json_extract(w.details_json,'$.site') LIKE 'S1_reason_ladder%' AND w.zone=p.zone AND abs(julianday(w.timestamp)-julianday(p.timestamp))*86400 < 5 WHERE p.action='preset_change' AND json_extract(w.details_json,'$.values_before.preset_mode')='manual' AND json_extract(p.details_json,'$.manual_class') NOT IN ('sub_delta_human','zero_delta_ura','gated_human','unknown');` MUST be 0. NM channel scan for `s1_manual_write_through` events MUST be empty. |
| C-P1E | Boot ledger row emits `tao_restore_evaluated` with `{tao_persisted_expires_at, decision: 'restore_on'|'restore_off_expired'|'no_persisted_state'}` (§5 D-P1a). Verify decision matches `now < expires_at` at boot. AND: no `climate_write.site='S1_reason_ladder'` between `async_setup` load and the first tick where `values_before.preset_mode='manual'` AND stored TAO decision was `restore_on`. |

---

## 1. Institutional context verified

### 1.1 Prior-art scan — REUSE

- **Persistence** — `_zone_state_store` (HA `Store` `hvac_zone_state`) `hvac.py:665`; load `:1053`; save `:1819`; side-key precedent `__person_zone_map` (`:1809`), `__short_cycles_today` (`:1815`). REV-6 DAO SUPERSEDED.
- `_temp_arrester_override_active` `hvac_override.py:463/858`; **`_temp_arrester_override_started_ts` `:464`** (source of truth for TAO's start time — persisted per N7/decision 46).
- **`HVAC_ARRESTER_OVERRIDE_MAX_S`** (TAO max window, 6 h) `hvac_const.py:205`.
- `_immune_holds` `hvac_override.py:448/656/705/727/838`; `_corrective_writes_suppressed(zone_id)` `:660`; sunset gates `:825/:834`.
- `comfort_delay_active(zone_id)` `hvac_override.py:2671`; `_comfort_delay_timers` `:3141-3143`; `_compromise_timers` `:220/2153/2885/3449/3476`; `_grace_timers` (verify at build).
- **DO NOT USE `_override_active`** for gate (c) — `_apply_compromise` early-return `:3366-3372`.
- `arrester.enabled` `:2816`; passive-mode double-book `:3172-3186`.
- **`is_borrow_active(zone_id)` + `excursion_id_for(zone_id)`** — NEW pure-read accessors in `hvac_excursion.py` (no reap, no NM, no DB delete).
- Arrester `_handle_climate_change` — row at `:3028` (moves to post-`:3195` per N3); delta at `:3195`.
- **Arrester in-memory last-detection accessor** `arrester.last_detection_for(entity_id)` — no DB read on decision path.
- Borrow-token attributes (verify at build): `hvac_predict.py:1128-1147` BANKING, `:1419-1437` PREHEAT, `hvac_egress.py:655-670` EGRESS.
- **`HVACTempArresterOverrideSwitch`** `switch.py:2429` — currently NOT `RestoreEntity` (F7). Decision 46 supersedes F7's premise here; TAO state is now managed by the coordinator via the store side-key, NOT by making the switch itself a `RestoreEntity`. Justification for choosing the coordinator channel over the switch's own restore hook: (a) the store is already the single source of truth for coordinator-owned zone state (immune holds, person map, short-cycles); (b) the switch entity does not own the arrester's `_temp_arrester_override_active` boolean — the arrester does; a coordinator-driven restore writes both the switch state and the arrester internals atomically in one call; (c) it keeps every side-key related to arrester lifecycle in ONE store slot; (d) doing this in `async_setup` (before first cycle at `:1372`) is the same ordering guarantee as the immune-hold rehydration — one seam, not two.
- S10 DPM `hvac.py:3217` — explicit exclusion + card `HVAC-S10-DPM-VS-S1-1` (§5.P6).
- `SUPPRESS_TTL_SECONDS_PRESET = 120` `hvac_override.py:173/2798`.
- `should_change_preset` `hvac_preset.py:202-217`; consumer `hvac.py:2626`; S1 site string `S1_reason_ladder` `:2821`.
- `_needs_resume_first` `hvac_setpoint.py:331`; `emit_set_preset_mode` `:487`; row deletion `hvac_excursion._delete_row`.
- `_s11_gate` `hvac_predict.py:972-978` (True=DEFER); `last_emitted` `:1003-1006`.

### 1.2 Prior planning docs consulted

`PLANNING_hvac_governed_excursion.md` (rev-6); `PLANNING_hvac_excursion_restore_unified.md` (parked); `PLANNING_hvac_live_room_establishment.md` (SHIPPED); `AUDIT_thermostat_write_paths_2026_09_16`.

### 1.3 Memory bodies pulled

`feedback_extend_existing_never_rebuild`, `feedback_wire_in_anchor_mandatory`, `feedback_suppression_needs_discharge`, `feedback_mutation_verification_pycache_staleness`, `feedback_no_soak`, `feedback_tier2plus_prior_art_scan`, `feedback_falsify_before_asserting`, `feedback_hollow_test_anchors`, `feedback_marginal_benefit_pushback`, `project_single_user_no_backcompat`, `project_reload_storm_refuted_restart_storm_live`.

### 1.4 REV-3/4/5/6 findings folded

All prior CRIT/HIGH survivors retained. REV-6 focused re-review N1-N9 folded per §REV 7 change log.

### 1.5 Design docs read

`HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §9e; `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2; READMEs.

### 1.6 Code locations surveyed

`hvac.py:665/1053/1309/1372/1748/1760/1809-1819/2623-2625/2626/2775/2821/3217`; `hvac_override.py:220/463/464/705-720/725-745/777-796/825/834/838/2671/2816/2897/3028/3050-3100/3105/3130-3143/3141-3143/3172-3186/3195/3366-3372/3383/3449/4442`; `hvac_excursion.py:6-16/562-579/1009/1322`; `hvac_predict.py:972-978/984/1003-1006/1046/1128-1147/1419-1437/1515-1583`; `hvac_egress.py:655-670`; `hvac_setpoint.py:331/487`; `hvac_const.py:189-198/205/361/452-456/531-532`; `hvac_preset.py:202-217`; `switch.py:2429`.

**F7 annotation (decision 46 REV-7):** F7's stated premise — "restart ends TAO because OFF is the safe state" — is SUPERSEDED for the W1-B context: under Alt A, S1 reclaims a stray `manual` on the first post-restart tick, so a TAO that was intentionally protecting an operator's manual would be immediately violated. Persisting TAO's expiry with a 6-h ceiling restores the invariant "operator's active TAO holds through a restart if still in its own window." F7 text is retained (do not delete elsewhere) as historical context; the annotation lives here and in this file's §Operator-decisions decision 46.

---

## 2. Non-goals

- No provenance chain, kill-switch entity, drift sensor.
- No `BORROW_LOCK` funnel-side gate.
- No confirmation oracle / bounded retry.
- No knob-expiry reclaim.
- No human-ends-borrow on NUDGE.
- No new state listeners.
- No `set_temperature` migration beyond D2.4.
- No changes inside `begin_excursion` / `return_excursion` / any borrow code beyond `is_borrow_active` + `excursion_id_for` accessors.
- No changes inside `emit_*` funnels.
- **No new DB table / DAO for immune-hold or TAO persistence** (both go into `_zone_state_store` side-keys).
- **No conversion of `HVACTempArresterOverrideSwitch` to `RestoreEntity`** (F7 respected at the switch layer; coordinator drives restore via the store per decision 46 justification).
- No Nest strategy code.
- S10 DPM vs S1: explicit exclusion; card §5.P6.
- Grace/comfort/compromise NOT persisted (P1 verbatim).
- No NM on sub-delta reclaim (P2).

---

## 3. D0 — Read-only measurement (Alt-A form; not a merge blocker)

CONFIG-FIRST refresh; nudge-effectiveness sanity read; optional §9.1 replay.

---

## 4. Deliverable order (REV 7)

1. **D0** (Alt-A form).
2. **D1** — Strategy interface, quad-state `WriteResult`, strategy-layer `last_sent`.
3. **D4** — `S1_RECLAIM_RATE_LIMIT_N = 3`; `HVAC_COMPROMISE_MINUTES_MAX = 15`.
4. **D4a** — UI clamp + default reduction.
5. **D-P1** — Immune-hold persistence via `_zone_state_store.__immune_holds`.
6. **D-P1a — TAO persistence via `_zone_state_store.__tao_state` (decision 46, NEW).**
7. **D5** — generic default.
8. **D2** — §5.P1 four-gate helper + `should_change_preset` replacement + `preset_change_deferred` + arrester `_handle_climate_change` restructured single-row (N3) + in-memory `last_detection` accessor + P2 `details.manual_class` (N4) + §5.P5 reclaim-rate NM + §5.P6 S10 card + §5 D2.4 five-site migration incl. S11 corrections (N5) + §5 D2a strategy `last_sent` + gate (e) BANKING/PREHEAT/EGRESS fallback (R1-H1/R2-H5) + `hvac.py`-side ledger emits (N6a).
9. **Live-validation write-back** into `README_v<version>.md` (**N9b:** TAO note; **decision 46:** TAO restart-restore note).

---

## 5. Deliverables

### D1 — Strategy interface

Quad-state `WriteResult`. Strategy owns `last_sent`. Returns KEEP resume-then-pin. `_snapshot_climate_state` exempt.

### D-P1 — Immune-hold persistence (REV-7 via `_zone_state_store`; N7/N1/N8)

Side-key `__immune_holds`. Record shape mirrors `_stamp_immune_hold` (N1). ISO datetimes; aware on load. Rehydrate in `async_setup` load path before first cycle at `hvac.py:1372` (N8). Grace/comfort/compromise NOT persisted. Activity-log ledger emits `immune_hold_stamped` / `immune_hold_sunset` for C-P1C (N6a).

Acceptance: `test_immune_hold_persists_across_restart`; `test_immune_hold_max_age_sunset_on_rehydrated_hold`; `test_immune_hold_next_activity_sunset_on_rehydrated_hold`; `test_immune_hold_stamped_and_sunset_ledger_rows`; `test_immune_hold_boot_load_precedes_first_cycle`. Reviewer C mutations: delete rehydration line → RED; swap ISO parse for `float` → max-age sunset RED.

### D-P1a — TAO persistence + restart-restore (decision 46; NEW)

**Side-key** `__tao_state` in `_zone_state_store` (same store as `__immune_holds`, `__person_zone_map`, `__short_cycles_today`).

**Serialised shape:**

```json
"__tao_state": {
  "started_ts": "<ISO 8601, aware datetime | null>",
  "expires_at": "<ISO 8601, aware datetime | null>"
}
```

`expires_at = started_ts + HVAC_ARRESTER_OVERRIDE_MAX_S` (6 h; `hvac_const.py:205`). Computed at the moment TAO is turned ON and persisted immediately.

**Write side.** Every TAO ON transition (arrester `enabled` setter at `hvac_override.py:2877`, or the switch's `async_turn_on` path, whichever populates `_temp_arrester_override_started_ts` at `:464`) computes `expires_at` and calls `_zone_state_store.async_save(snapshot)` via the coordinator helper (same channel as the immune-hold save). Every TAO OFF transition writes `{"started_ts": null, "expires_at": null}` and saves.

**Boot restore (coordinator channel — chosen).** In `HVACCoordinator.async_setup` (`hvac.py:1309`), immediately after the immune-hold rehydration and BEFORE the first cycle at `:1372`:

```python
tao = stored.get("__tao_state") or {}
persisted_expires = tao.get("expires_at")
expires_at = dt_util.parse_datetime(persisted_expires) if persisted_expires else None
now = dt_util.now()
if expires_at and now < expires_at:
    # Restore ON: set arrester internals AND switch state atomically.
    self._arrester._temp_arrester_override_active = True
    self._arrester._temp_arrester_override_started_ts = (
        dt_util.parse_datetime(tao.get("started_ts")) or now
    )
    # Nudge the switch entity to reflect the restored state
    # (dispatcher signal `ura_hvac_temp_arrester_override_update` per hvac_const.py:1135).
    async_dispatcher_send(hass, "ura_hvac_temp_arrester_override_update", True)
    decision = "restore_on"
elif expires_at:
    decision = "restore_off_expired"
else:
    decision = "no_persisted_state"

# Emit a ledger row for C-P1E and operator diagnostics.
await self._db.write_activity_log(
    action="tao_restore_evaluated",
    details={
        "tao_persisted_started_ts": tao.get("started_ts"),
        "tao_persisted_expires_at": persisted_expires,
        "decision": decision,
        "now": now.isoformat(),
    },
)
```

**Why coordinator, not switch restore hook (justification per operator ask):**
1. The arrester (not the switch) owns `_temp_arrester_override_active` — the boolean gate (a/b) actually reads via `_corrective_writes_suppressed`. A switch-side `RestoreEntity` hook can only restore the switch's own `is_on`; the arrester internals must be updated in parallel, which requires a coordinator-level call anyway. Doing it all in one place is atomic; splitting risks a window where the switch says ON but `_temp_arrester_override_active` is still False (gate (a/b) not armed) — exactly the regression F7 was trying to avoid.
2. The store is already the single source of truth for coordinator-owned zone state; TAO state lives naturally next to `__immune_holds` in the same snapshot slot, one seam.
3. Ordering: `async_setup`'s existing load at `hvac.py:1053` runs before the first cycle at `:1372`. Reuses the exact ordering invariant N8 already established for immune holds — no new seam.
4. F7 respected at the switch layer — `HVACTempArresterOverrideSwitch` remains a plain `SwitchEntity` (no `RestoreEntity` mixin added). The switch's UI state on boot is driven by the dispatcher signal the coordinator emits after restore.

**F7 annotation:** F7's premise ("OFF is the safe state; restart ends TAO") is SUPERSEDED under Alt A because S1 will reclaim a stray `manual` on the first post-restart tick — a TAO that was protecting an operator's manual would be immediately violated. Decision 46 restores the invariant "operator's active TAO holds through a restart if still in its own 6-h window." The F7 text elsewhere (README v3.9.0, and any code comments) is RETAINED as historical context; do not delete. Annotate at the point where it is contradicted by decision 46 (e.g. add a `# SUPERSEDED 2026-09-27 by W1-B decision 46 for the W1-B context.` comment above the F7 code path if such a comment exists).

**Acceptance (mandatory):**
- `test_tao_restore_within_window_keeps_on_and_s1_refuses` — save `__tao_state = {started_ts: now - 1h, expires_at: now + 5h}`; simulate restart via `async_setup`; assert `_arrester._temp_arrester_override_active is True` before first cycle at `hvac.py:1372`; assert `_corrective_writes_suppressed('z1') is True`; drive S1 on a `manual` zone; assert S1 refuses with `reason='person_protected_hold'`; assert `tao_restore_evaluated` ledger row with `decision='restore_on'`.
- `test_tao_restore_after_window_turns_off_and_s1_reclaims` — save `__tao_state = {started_ts: now - 7h, expires_at: now - 1h}`; simulate restart; assert `_arrester._temp_arrester_override_active is False`; drive S1 on a `manual` zone with no other gate → S1 writes over; assert ledger row `decision='restore_off_expired'`.
- `test_tao_restore_no_persisted_state` — empty `__tao_state` (or key absent); simulate restart; assert TAO OFF; ledger row `decision='no_persisted_state'`.
- `test_tao_persistence_write_on_on` — turn TAO ON; assert `__tao_state.expires_at` = `started_ts + HVAC_ARRESTER_OVERRIDE_MAX_S`; assert save was triggered.
- `test_tao_persistence_clear_on_off` — turn TAO OFF; assert `__tao_state = {started_ts: null, expires_at: null}`; assert save was triggered.
- `test_tao_max_window_uses_hvac_const_205` — assert `expires_at - started_ts == HVAC_ARRESTER_OVERRIDE_MAX_S` from `hvac_const.py:205`.
- **Reviewer C mutation:** (a) delete the `now < expires_at` comparison → `test_tao_restore_within_window_...` and `test_tao_restore_after_window_...` swap outcomes; (b) change the coordinator restore call to only set the switch state (skip the arrester internals) → `test_tao_restore_within_window_...` RED because gate (a/b) not armed on first tick (this drill proves the "atomic" justification above).
- **Live:** post-deploy, turn TAO ON via the switch; restart HA within 6 h; observe TAO stays ON and gate (a/b) armed on first cycle. Restart 6+ h later; TAO restored OFF.

### D2 — Carrier strategy

#### §5.P1 — S1 manual-guard replacement (Alt A; REV-7)

Change site `hvac_preset.py:202-217`. All brands. Signature carries `zone_id`. Helper injected via `set_arrester(arrester)`; arrester-None → `(True, 'arrester_not_wired')`.

**FOUR gates** (unchanged from REV-7 pre-decision-46; gate (a/b) now benefits from BOTH immune-hold rehydration AND TAO restart-restore per D-P1 + D-P1a):

| Gate | Condition | Signals | Reason |
|---|---|---|---|
| (a/b) | Pre-existing OR. Post-P1+decision-46: includes rehydrated immune holds AND restored TAO. | `arrester._corrective_writes_suppressed(zone_id)` | `person_protected_hold` |
| (c) | Comfort-delay OR grace OR compromise. Not `_override_active`. | `comfort_delay_active(zone_id)` OR `_grace_timers[zone_id]` OR `_compromise_timers[zone_id]` | `arrester_active_window` |
| (d) | Arrester off. Accessor reads OPTIONS until `SIGNAL_HVAC_COORDINATOR_READY`. | `not arrester.enabled` | `arrester_disabled_passive` |
| (e) | Fresh row OR arrester-timer/token fallback for all 5 kinds. Pure read. | `is_borrow_active(zone_id)` OR nudge/compromise/banking/preheat/egress token/timer — orchestrator-verified names on develop: arrester `_nudge_excursion_tokens`, `_nudge_restore_timers`, `_compromise_timers`; `hvac_predict` `_banking_excursion_tokens` (`:1027`), `_preheat_excursion_tokens` / `_preheat_return_timers` (`:1436-1439`); `hvac_egress` `_egress_excursion_tokens` (`:671`). NOTE: tokens are only set when `begin_excursion` returned non-None — the builder must verify each kind still has a no-row signal when the kill switch is OFF (e.g. banking/egress in-flight state other than the token) and report any kind with none | `active_borrow` |

**Same-tick set (N9a):** resets at cycle ENTRY.

**Vacancy bypass (M3, N9b):** also checks (a/b) + (e). README note: vacancy bypass defers under TAO (now includes restart-restored TAO per decision 46).

**Arrester booking (N3):** single-row post-`:3195` with `delta_f` + `details.gated_reason` + `details.gate_snapshot`. Precedence top-down: **nudge_win** → borrow_active → immune_stamp → comfort_grant → passive_mode. In-memory `arrester.last_detection_for(entity_id)` accessor — no DB read on decision path.

**Ledger rewrite.** `preset_change_locked_out` → `preset_change_deferred` with reason + gate snapshot.

**P2 classifier (N4).** `details.manual_class` from `arrester.last_detection_for(entity)` walked over the current manual episode (episode := transitions of `preset_mode` in/out of `manual`). Reason ladder preserved.

Acceptance retained from REV 7 pre-decision-46 + tests listed in D-P1a above for TAO restart.

#### §5.P2 Supersession triage (unchanged)

DELETE post-PASS: `hvac_excursion.py:629-650`; cards `HVAC-PRESET-LOCKOUT-ESCAPE-1`, `HVAC-ZONE1-MANUAL-OSCILLATION-1`. KEEP+WIRE: `hvac.py:2616-2675` → `preset_change_deferred`. KEEP+DOCUMENT: `hvac_predict.py:1540-1580`.

#### §5.P3 Write volume + preset-kind suppression

~54 extra Carrier writes/day. `hvac.py:2775` `suppress(kind="preset")` (120 s). Counter renames: `preset_deferrals_today` (per-gate); `arrester_reverts_today`.

#### §5.P4 Problem 4 closed-by-A (unchanged)

`test_person_protected_hold_sunset_s1_reclaims_next_tick`.

#### §5.P5 S1 reclaim-rate anomaly

`S1_RECLAIM_RATE_LIMIT_N = 3` in 30 min → `s1_reclaim_rate_high` NM.

#### §5.P6 Card text for `HVAC-S10-DPM-VS-S1-1` (unchanged — see REV 7 §5.P6 body in prior draft; retained verbatim for the orchestrator to add to `kanban.data.yaml`)

#### D2.1 Same-tick nudge-start skip

`_zones_written_this_cycle` resets at cycle ENTRY.

#### D2.4 Presets-only returns — 5-site inventory + S11 fixes (N5)

Five sites: `hvac_override.py:4650`, `:5877`, `:6289`, `hvac_predict.py:984`, `:1520`. HUMAN_MANUAL := `pre_preset ∈ {manual, None, ""}`.

S11: `_s11_gate` True=DEFER; `_release_ok` uses new pure `excursion_id_for(zone_id)`; `last_emitted` update at `:1003-1006` relocates. S13 restructure `:1515-1583`.

#### D2.5 No-op suppression — strategy layer (M5)

Funnels untouched. Grep `hvac_setpoint.py` for `last_sent` MUST be 0.

#### D2.6 Consumer wiring — behavioural anchors + AST lint

Also-2 test rewrites unchanged.

#### D2.8 28-site write table (unchanged)

#### D2a Strategy-layer `last_sent` (M5)

### D4 — Module constants

| Constant | Value | Rung |
|---|---|---|
| `S1_RECLAIM_RATE_LIMIT_N` | 3 | 1 |
| `HVAC_COMPROMISE_MINUTES_MAX` | 15 | 1 |
| (No new TAO constants — `HVAC_ARRESTER_OVERRIDE_MAX_S` already exists at `hvac_const.py:205`.) |

### D4a UI clamp + defaults (unchanged)

---

## 6. Operator questions — NONE

All prior open decisions resolved. Decision 46 closes the TAO-across-restart question.

---

## 7. Ship gate

Pre-deploy replay: §9.1 four strands + four-gate parametric + gate-(e) all-five-kinds via token fallback + reload-window (M10) + preset-kind suppression (M4) + vacancy-bypass (M3 + TAO variant) + S11/S13 self-block (N5) + same-tick reset-at-entry (N9a) + arrester single-row + nudge_win precedence (N3) + reclaim-rate NM + **P1 restart drill via `_zone_state_store` rehydration** + **P2 episode-scoped classifier drill** + **decision 46: TAO restart-within-window / restart-after-window / no-persisted-state drills** + S10 exclusion probe.

Post-deploy disposition at N ≥ 10 non-nudge returns per zone (7-day cap). §0 REV-7 queries.

PASS → dispose + §5.P2 DELETE-bucket + confirm card `HVAC-S10-DPM-VS-S1-1` on the board.

---

## 8. Review protocol — Tier 3

**Reviewer A.** Four gates; single-row arrester + `delta_f` + gated_reason (N3); nudge_win at top of precedence (C3); `_release_ok` self-exclusion (N5); `_s11_gate` polarity (N5); D4a defaults; **D-P1 store shape (N7/N1); D-P1a TAO expiry arithmetic (decision 46); atomic restore (switch + arrester internals in one call).**

**Reviewer B.** No funnel-side gate; both `is_borrow_active` and `excursion_id_for` side-effect free; reload window (M10); vacancy bypass respects TAO (incl. restored TAO); passive-mode dedup; same-tick reset at ENTRY (N9a); **D-P1 ISO datetime round-trip preserves `isinstance(datetime)`; D-P1a atomic restore prevents the switch-ON-but-arrester-internal-False window; expires_at ceiling honoured at exactly 6 h (hvac_const.py:205).**

**Reviewer C.** Each gate mutated; each begin site deferred; drill M10; arrester precedence rungs mutated; grep `hvac_setpoint.py` for `last_sent` MUST be 0; **D-P1 mutations (delete rehydration; ISO→float swap); D-P1a mutations ((a) delete `now < expires_at` → within/after tests swap; (b) skip arrester-internals restore → within-window test RED because gate (a/b) not armed).**

**Reviewer D.** Re-enumerate every path setting `hold_activity = manual`; falsify INV C1..C-P1E; **verify C-P1C queries `ura_activity_log` alone (no live store); verify C2 nudge windows via `ac_ramp_events`; verify D-P1a's `tao_restore_evaluated` ledger row covers C-P1E; verify F7 annotation lands at the correct site and F7 text elsewhere is untouched.**

**Orchestrator hand-check:** re-grep 28 sites + 5 begin sites + BANKING/PREHEAT/EGRESS attr names; mutation drills; AST lint; §9.1 replay; reload / suppression / vacancy / S11 / same-tick / arrester precedence / reclaim-rate drills; **D-P1 restart drill; D-P1a TAO restart (within-window, after-window, no-persisted-state) drills**; grep `hvac_setpoint.py` for `last_sent` (MUST be 0); slider max = 15; defaults = 15; verify card `HVAC-S10-DPM-VS-S1-1` on board.

**Operator checkpoint:** four-gate demo; P1 restart demo; P2 log-only demo; **decision 46 TAO restart demo (within window + after window)**; vacancy-bypass-defers-under-TAO README note surfaced.

---

## 9. Sequencing / dependencies

1. W1-A SHIPPED v5.103.16. 2. Echo-fix SHIPPED v5.103.17. 3. Alt A APPROVED + REV-5 collapse + REV-6 review-fold + P1/P2 rulings + REV-7 focused re-review fold + **decision 46 TAO restart-restore ruling folded**. 4. Two Tier-3 plan reviews on this REV 7. 5. Build via `ura-super-builder` in worktree `.claude/worktrees/hvac-w1b-thermostat-definition`. 6. Build order per §4. W2 fast-path signature update. 7. Four framing-disjoint reviews. 8. Operator checkpoint. Deploy. 9. Live-validation write-back (incl. N9b vacancy-bypass-under-TAO + decision-46 TAO-restart-restore notes). 10. Disposition at N ≥ 10. 11. On PASS: §5.P2 DELETE-bucket.

**No soak.**

---

## Operator decisions — BINDING (verbatim; annotate, never edit)

**REV 3-6:** decisions 1-35 verbatim + prior annotations. [REV-7 no changes.]

**REV 7 (2026-09-27, focused re-review fold + TAO ruling):**

36. **N7 — persist via `_zone_state_store`, not new DAO.** Side-key `__immune_holds`; precedent `hvac.py:665/1809/1815`. Ruling 17 intent binding, mechanism revised.
37. **N1 — mirror exact in-memory record shape** from `_stamp_immune_hold` (`hvac_override.py:714-720`). ISO datetimes → aware on load; `isinstance(datetime)` gates preserved.
38. **N2 SUPERSEDED by decision 46** — see 46 below.
39. **N3 — restructure `_handle_climate_change`.** Single-row post-`:3195` with `delta_f` + `gated_reason` + `gate_snapshot`. In-memory `last_detection_for` accessor. Precedence top-down with **nudge_win at top** so C3 holds.
40. **R1-H1 / R2-H5 — gate (e) extended** to BANKING/PREHEAT/EGRESS via `hvac_predict.py:1128-1147`, `:1419-1437`, `hvac_egress.py:655-670`.
41. **N5 — S11 fixes.** `_s11_gate` True=DEFER; `_release_ok` via `excursion_id_for`; `last_emitted` update relocated.
42. **N4 — P2 discriminator in `details.manual_class`**; reason ladder preserved; episode-scoped; `SUB_DELTA_WINDOW_S` dropped.
43. **N6 — falsifiers runnable.** C-P1C queries `ura_activity_log` for stamp/sunset ledger rows; `ts_issued` via `json_extract`; C2 nudge windows use `ac_ramp_events`.
44. **N8 — rehydration ordering is `async_setup` load before first cycle at `hvac.py:1372`.**
45. **N9 — card text minted (§5.P6); same-tick set resets at cycle ENTRY (N9a); README notes vacancy-bypass-defers-under-TAO (N9b).**
46. **TAO across restart — RESTORE TAO IF STILL IN WINDOW.** Operator verbatim (2026-09-27): *"Option (ii), Restore TAO if still in window."* Spec (§5 D-P1a): persist `(started_ts, expires_at)` in `_zone_state_store.__tao_state`; `expires_at = started_ts + HVAC_ARRESTER_OVERRIDE_MAX_S` (6 h, `hvac_const.py:205`); restore TAO ON iff `now < expires_at`. **Channel = coordinator** (not switch's own `RestoreEntity` hook) because the arrester (not the switch) owns `_temp_arrester_override_active` and a coordinator-driven restore writes both atomically — the switch layer stays a plain `SwitchEntity` per F7. **F7 annotated as SUPERSEDED** for this reason at the site of the contradiction; F7 text elsewhere (README v3.9.0, code comments) RETAINED as historical context. Ledger row `tao_restore_evaluated` with `decision ∈ {'restore_on','restore_off_expired','no_persisted_state'}` for C-P1E. Tests: `test_tao_restore_within_window_keeps_on_and_s1_refuses`; `test_tao_restore_after_window_turns_off_and_s1_reclaims`; `test_tao_restore_no_persisted_state`; `test_tao_persistence_write_on_on`; `test_tao_persistence_clear_on_off`; `test_tao_max_window_uses_hvac_const_205`. Reviewer-C mutations: (a) delete `now < expires_at` → within/after tests swap; (b) skip arrester-internals restore → within-window test RED (gate a/b not armed).

**Fix-up round 1 (2026-09-27, four Tier-3 reviews A/B/C/D FIX-REQUIRED; baseline tag `pre-review-v5.103.18` @ b444046d) — appended verbatim from the orchestrator brief:**

47. **D47 (orchestrator): gate (e) is simplified and bounded.** *[Gate (f) below SUPERSEDED by D51 — the kill switch no longer exists; gate (e) = fresh row OR `_nudge_restore_timers` / `_nudge_in_flight` / `_compromise_timers`.]* This fixes A-H1, B-H2, D-H1 and D-M3.** Gate (e) = `is_borrow_active(zone)` (fresh row) OR `zone in _nudge_restore_timers` OR `zone in _nudge_in_flight` OR `zone in _compromise_timers`. These timer sources self-discharge. DROP the `banking_token`, `banking_precool_zone` (`_last_precool_zones`), `preheat_token`, `preheat_return_timer` and `egress_token`/`egress_paused` fallbacks — their leftovers outlive the row (e.g. the banking token after the 2 h sweep, and `_last_precool_zones` with Zone Intelligence OFF); S1 already skips egress-paused zones. NEW gate (f): if the excursion kill switch is OFF, S1 keeps the old respect-manual behaviour (defer, reason `excursion_primitive_disabled`), like gate (d) — this makes kill-switch-OFF behave exactly as today and removes the PREHEAT / pre-arrival no-row cases (D-M3). The vacancy bypass checks (a/b), (e) and (f). Tests: a stale banking token with no row → S1 reclaims; kill switch OFF → defer; each timer fallback → defer; drills for each.
48. **D48 (operator ruling, verbatim): Borrow STARTS win over person protection.** Operator: *"URA has more information and should win. URA understands energy saving strategies and Operators don't. They can redo if they want to pre-empt automation changes that are valid."* Do NOT gate S5/S12/S13/pre-arrival/S3 starts on (a/b). INV-1 rescoped: its "no URA writes while gated" covers S1 reclaim and the arrester, not borrow starts. D-H2 is by design.
49. **D49 (operator ruling): The vacancy bypass keeps today's behaviour.** It does NOT wait for gate (c) or (d). D-M2 is closed as intended.
50. **D50 (orchestrator, B-M2): An immune person wins over a live compromise.** In `_handle_climate_change`, when the only borrow is a compromise (not a nudge), stamp the immune hold before returning, as develop does. `nudge_win` stays top only for nudges. Test: an immune change mid-compromise → hold stamped → the S4 revert is skipped.

51. **D51 (operator ruling, amendment): retire the excursion kill switch.** Operator: *"Yes"* to *"retire the knob; borrow records always written; no special case."* Remove the v5.88.0 back-out option "Restore thermostats after temporary changes" (`excursion_primitive_enabled`) entirely: `hvac_excursion.py` early return at `begin_excursion` deleted (REJECT-on-existing-row stays), `_kill_switch_enabled` / `set_kill_switch_enabled` / `is_kill_switch_enabled` / `_test_set_kill_switch` deleted, docstring updated (deleting borrow code is permitted — removal, not new logic); `hvac_const.py` CONF + DEFAULT removed; `hvac.py` constructor param, attribute and property removed; `__init__.py` pass-through removed; `sensor.py` `primitive_enabled` attribute dropped from `sensor.ura_hvac_coordinator_thermostat_borrows` (no dashboard/template consumer found — grep `docs/`, dashboards); config/options-flow selector removed; `strings.json` / `translations/en.json` label + description removed. A stored option value is harmless (ignored; single install, no migration). **Gate (f) is dropped.** Tests: kill-switch tests deleted/converted; new test "with no switch, `begin_excursion` always records for every kind"; name-diff GONE entries for the deleted kill-switch tests are expected and listed.

52. **D52 (orchestrator ruling, fix-up round 2, by analogy with D48 — energy actions win; the hard reset already respects person protection):** the hard reset stays gated ONLY on (a/b). Not gated on the borrow row / arrester windows.

*Fix-up round 2 notes: LOW-2 — `unsuppress` overwrites (a second URA write's `unsuppress` on error can close a sibling write's still-valid window) is PRE-EXISTING (not W1-B), noted for a later cycle. LOW-3 — the restart marker is now also cleared on an automatic TAO sunset (`hvac.py` `_clear_tao_restart_marker`, called from the sunset-notify callback). D-1 — arrester timers check gate (e) (`excursion_id_for`, own token exempt) / live nudge / egress pause at FIRE time and discharge cleanly with an `arrester_deferred_to_borrow` ledger row. D-2 — `force_ac_reset` returns the nudge row; `nudge_win` requires a LIVE nudge. D-3 — egress rehydrate re-links the EGRESS row token (orphan rows returned). D-4 — in-window nudge resume seeds the snapshot from the persisted row so S6 is presets-only. MEDIUM-1 — nudge restore timer scheduled before DB bookkeeping (no stuck `_nudge_in_flight`).*

*A-L5 (noted, not fixed this cycle): the S10 DPM apply site's interaction with the S1 rule is carried on card `HVAC-S10-DPM-VS-S1-1` (§5.P6).*

---

## REV 7 delta summary (for reviewers)

- **Decision 46 folded:** TAO now persists in `_zone_state_store.__tao_state`; coordinator restores TAO (arrester internals + dispatcher signal for switch UI) in one atomic step during `async_setup` before first cycle at `hvac.py:1372`; F7's "restart ends TAO" premise annotated as SUPERSEDED for the W1-B context (F7 text retained elsewhere). New invariant C-P1E + `tao_restore_evaluated` ledger row + 6 tests + 2 mutations.
- All REV-7 focused re-review items N1-N9 remain folded per prior REV-7 body (persistence via `_zone_state_store` for immune holds, N1 record shape, N3 single-row arrester + nudge_win-at-top, gate (e) 5-kind fallback, N5 S11 fixes, N4 `details.manual_class`, N6 runnable falsifiers, N8 ordering, N9 card + same-tick + README).

**Falsifiable invariant (one sentence, REV 7 + decision 46):** on any thermostat zone, no URA borrow return writes a raw setpoint (except HUMAN_MANUAL); while `is_borrow_active(zone_id)` OR any of the five arrester borrow-timer/token fallbacks is True and the zone reads `manual`, S1 emits zero preset writes and the vacancy bypass does not write `away`; the arrester writes a single `override_detected` row (post-`:3195`) with `delta_f` + `details.gated_reason` per precedence (nudge_win → borrow_active → immune_stamp → comfort_grant → passive_mode) and skips revert where the gate wins; the strategy layer emits zero service calls on a proven no-op; while the arrester is enabled and none of the four Alt-A gates is armed, S1 leaves the zone in `manual` for at most one decision tick (carve-outs for night-trust / row-1 transient / dwell); an immune-person hold persisted via `_zone_state_store.__immune_holds` re-arms gate (a/b) on the first post-restart tick before `hvac.py:1372`; **a TAO whose 6-h window has not expired is restored ON in the same `async_setup` seam, both the switch state and `_temp_arrester_override_active` set atomically, so gate (a/b) is armed on the first cycle**; every S1 manual write-through carries `details.manual_class ∈ {sub_delta_human, zero_delta_ura}` scoped to the manual episode, with the S1 reason ladder preserved and no NM.

**Open questions: NONE.** All prior holds resolved. Ready for two Tier-3 plan reviews on this REV 7, then build via `ura-super-builder`.
