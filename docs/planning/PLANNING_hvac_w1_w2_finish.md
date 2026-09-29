# PLANNING — HVAC W1/W2 finish (REV 2)

**Cards:**
- Part A: `ARRESTER-BOOT-BLIND-1` gap (2), revived 2026-09-28. Operator ruling: "The person interrupts. We end and revert. Closest to my intent."
- Part B: `HVAC-PRE-ARRIVAL-BORROW-LIFETIME-1`, approved.
- Part C: `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1` (W2-2). Cut to the occupancy-clock fix only, per ruling Q5.

**Author:** ura-planner. REV 1 2026-09-28; REV 2 2026-09-28 (answers the plan review).
**Snapshot:** `develop` @`37b678966` (v5.103.21). v5.103.20 is built but not deployed.
**Status:** PLAN ONLY. Each deliverable is gated by the §2 probe. REV 2 must be re-checked by the plan reviewer before build.
**Tier:** Tier 2-DB with four reviews (Q6): three framing-disjoint reviews plus one adversarial-completeness pass. Then live validation and the README write-back (§6).
**Plan review:** `docs/reviews/code-review/plan_review_hvac_w1_w2_finish.md`, verdict FIX-PLAN-FIRST (5 HIGH, 10 MED, 7 LOW).

Each part is a separate deliverable group with its own falsifiable invariant.

---

## REV 2 — revision table

| Finding | Fix in REV 2 | Where |
|---|---|---|
| **H1** — a mode change was read as a human setpoint change | A change counts as within-manual only if both states are `heat_cool` and all four legs are numeric. Otherwise the classifier returns `none`. Verified: ha_carrier sets both legs to None outside HEAT_COOL (`climate.py:230-240`). New test `test_classify_mode_change_is_none` | D1 rule steps 1–2 |
| **H2** — D2c could not re-dispatch | D2c forces `_borrow_row` and `_comp_live` to False for the zone and rebuilds `gate_snapshot` before the precedence runs. The test asserts a NEW timer, and that `gated_reason` is not `borrow_active` | D2c |
| **H3** — the case-A revert target and delta basis came from different presets | ONE reference preset per case. Case A uses `T.pre_preset` for BOTH the revert target and the delta (that preset's seasonal setpoints). The 09-28 replay outcome is written into the AC and into "What the operator will see". Q7 asks the operator to confirm | D2 baseline table; A.2; Q7 |
| **H4** — the latch was erased by the next booking | Separate `_interrupt_latch: set[entity_id]` on the arrester. Removed only at the manual-exit boundary (`hvac_override.py:3109-3115`), plus teardown. Two-change test added | D2e |
| **H5** — Part C not scoped to Q5 | Part C = C3 only. C1, C2 and C4 are PARKED in Appendix A with a trigger you can evaluate (a named probe and threshold). INV-C is (b) only. §6 framing fixed | Part C; Appendix A; §6 |
| **M1** — S12/S13 write after an interrupt that lands inside `begin` | A returned-token check immediately before each emit | D2b table |
| **M2** — S13 writes over a foreign row | The D4b foreign-row guard now also covers S13 | D4b |
| **M3** — orphan COMPROMISE rows | A COMPROMISE row with no arrester timer and no token counts as endable (case C baseline). The `enabled=False` setter now releases compromise rows. The three orphan paths are listed in §3 | D2a; D2f; §3 |
| **M4** — C3's edit shape would skip the back-fill | Guard ONLY the single assignment `zone.continuous_occupied_since = None`. The v5.103.20 back-fill in the same `else` is untouched | C3 |
| **M5** — the pre-arrival borrow could reach `lease_expiry` | D3 also ends the borrow when its age reaches the window, measured from the borrow's START. Knob max = 110 | D3; D5 |
| **M6** — knob wiring under-specified | All five `__init__.py` sites named, including `OPTIONS_RELOAD_SUPPRESS_KEYS`. Settings-form field too (knob-52 precedent). CONF placed in `hvac_const.py` | D5 |
| **M7** — P1 could not discriminate | Window from 2026-09-26 (when `climate_write` coverage began), changed-legs rule, minimum N, late-arrival split, a named remediation branch, and D1 decoupled from the other gates | §2 P1 |
| **M8** — INV-A.3 / INV-B.2 mis-stated | Restated with explicit carve-outs (D48/D52 nudge and hard reset, egress mode, heat_cool enforcer, S1, arrester; `stale_boot_release`, CM wire-fail) | A.1; B.1 |
| **M9** — case C had no test or AC | Tests for case C and for the resolver-None branch; a README line | D2 AC |
| **M10** — fast-run D3 acted on other zones | In a fast run, expiry and ending are scoped to `{Z}`. Other zones wait for the next full pass, which ends them before S1 | D3 |
| **L1** — fixture expected classes | Expected result per row, taken from the P1 rows | D1 AC |
| **L2** — boot seed runs after the listener | Accepted and documented (a window of seconds, safe direction) | D1 |
| **L3** — funnel escapes | Named as INV-A5 carve-outs | A.1 |
| **L4** — reason vocabulary | No new `reason=` literal is planned. Any literal a builder adds must go into `HVAC_PRESET_REASONS` (`const.py:1321`) | §4 |
| **L5** — latch discharge on a feed flicker | Documented as accepted | D2e |
| **L6** — D2c race with an already-pending `_apply_compromise` | Per-zone episode generation counter; stale tasks stand down | D2c |
| **L7** — doc hygiene | One §8; four reviews; `monotonic_ts` dropped from the record; INV timestamps use the `climate_write` row timestamp (the wall-clock issue time) | throughout |
| **Batch A, LOW-4** — boot audit re-pins `manual` after a mid-nudge restart | New deliverable **D6**: HIGH-1-style skip in the boot-audit NUDGE branch. Added to §3 | D6; §3 |
| **W3 G0** — 12 unexplained out-of-window S12 borrows | New probe **P7** classifies them | §2 P7 |

---

## 0. Institutional context verified

**State of play read completely.** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, all 472 lines: §1–§12, §9e (the four S1 gates and rulings D13/D48/D49/D50/D52) and the §10 ledger C1–C25. This plan re-asserts no §10 claim. It respects C13 (return sites write, not the primitive), C16/C21 (the ha_carrier 5-min guard and full-read release), C17/C23 (15 s / 120 s suppression), C24 and C25.

**Stale citations in the state-of-play doc** (fix in the landing commit):
- §9e: HIGH-1 skip `hvac_excursion.py:629-650` → `:644-666`.
- §3.2 / §9.4: D5 coast defer `hvac.py:2271-2289` → `:2882-2962`.
- D6: `hvac.py:2063` → `:2676-2685`. Presence Source 1 is `presence.py:2100-2122`; Source 4 is `:2147-2159`.
- `continuous_occupied_since`: `hvac_zones.py:746-754` → `:964-985`.
- §4.2: S12 `hvac_predict.py:1160` → begin `:1154`, write `:1193`.
- Card: pre-cool offset `:1134` → `:1135`.

### Re-verified facts, each with its source
- The arrester books an override only on a transition INTO manual (`hvac_override.py:3218`). A setpoint change while already manual returns silently (`:3220-3226`).
- S12 begins BANKING with `duration_s=None` (`hvac_predict.py:1154-1164`). The row is stale only at `EXCURSION_LEASE_MAX_S = 7200` (`hvac_excursion.py:79`, `:146-148`).
- `_expire_pre_arrival_zones` (`hvac.py:5857-5887`) never touches the borrow.
- The ratchet: the offset is applied to the LIVE high on every pass (`hvac_predict.py:645-649`, `:1135`).
- **Write-despite-reject.** A rejected `begin_excursion` returns None (`hvac_excursion.py:805-813`), and S12 (`hvac_predict.py:1193`) and S13 (`:1482`) still write.
- **Mode legs.** ha_carrier reports `target_temp_high/low = None` in every mode except HEAT_COOL (`/config/custom_components/ha_carrier/climate.py:230-240`). Egress (`hvac_egress.py:721`) and AC hard-reset mode writes open no suppression window.
- **S4 re-pins `manual`.** `_revert_override` uses the compromise token's `pre_preset` whenever it is truthy (`hvac_override.py:3938-3942`). The value is snapshotted after the human's change, so it reads `manual`. The write itself does go through the funnel; the VALUE is wrong (operator follow-up, §8).
- **Boot audit re-pins `manual` after a nudge** (Batch A builder, LOW-4). A NUDGE can begin on a zone that reads `manual`: `check_ac_reset` checks only `_override_active`, and the force-nudge button checks no preset. `begin_excursion` then snapshots `pre_preset="manual"`. The boot-audit NUDGE branch pins any non-empty `pre_preset` (`hvac_excursion.py:1126-1148`) and has no manual skip.
- **Orphan COMPROMISE rows.**
  - The `enabled=False` setter cancels compromise timers but never returns the row (`hvac_override.py:3070-3091`).
  - `teardown()` is synchronous and cancels timers (`:2346-2362`).
  - The boot audit rehydrates COMPROMISE rows with no arrester owner (`hvac_excursion.py:1240-1256`).
- **Knob wiring precedent (knob 52).**
  - `__init__.py`: setup read `:3776`/`:3899`, import `:6201`, `OPTIONS_RELOAD_SUPPRESS_KEYS` `:6859`, apply-in-place set `:7287`, dispatch `:7389-7400`.
  - `config_flow.py`: `:5934`, `:6497-6499`.
  - `number.py`: `:511-587`.
- **Reason vocabulary.** `HVAC_PRESET_REASONS` (`const.py:1321-1352`) is enforced by tests. `_auto_return` passes `reason=trigger` (`hvac_excursion.py:675`), so `lease_expiry` and `stale_boot_release` are in it.

### Greps run
`begin_excursion(|return_excursion(|_compromise_release_lease(|site="S[0-9]`, `_pre_arrival_zones|PRE_ARRIVAL_TIMEOUT_MINUTES`, `_last_emitted_range[`, `last_sent|values_after`, `last_detection_for`, `override_count_today`, `caller_site`, `S12_pre_cool`, `set_on_.*`, `vacancy_bypass_deferred|manual_guard_verdict`, `any_room_occupied|is_zone_transient_blocked`, `continuous_occupied_since =`, `CONF_HVAC_RETURN_WINDOW_MINUTES` (`__init__`, `config_flow`), `HVAC_PRESET_REASONS`, `def teardown`.

### Prior plans consulted
- `PLANNING_hvac_w1b_thermostat_definition.md`: rulings, §2 non-goals, §5.P1. Its funnel non-goal gets one exception, granted by ruling Q1.
- `PLANNING_hvac_governed_excursion.md`: row 11, the ratchet left unscoped at `:753`, and the rev-6 banner.
- `PLANNING_hvac_fast_occupancy_response.md` REV 7: pre-arrival bypasses D5; expiry runs in fast runs.
- `PLANNING_hvac_enable_custom_preset_ranges.md`: its consumer table lists banking as a "known ratchet" reader.
- `PLANNING_hvac_reloading_room_placeholder_readers.md`, full read. Part C and Appendix A reuse it; its §5a D0 result was PARK.
- `PLANNING_hvac_w2_night_sleeper_and_placeholder_readers.md` Piece B, now superseded.
- `PLANNING_hvac_arrester_nudge_echo.md` (via §10 C23).

### Memory bodies
- `project_reload_storm_refuted_restart_storm_live`: restarts, not reloads, are the live trigger.
- `feedback_suppression_needs_discharge`: every latch here names its discharge, backstop and restart behaviour.
- Index lines: `feedback_extend_existing_never_rebuild`, `feedback_marginal_benefit_pushback`, `feedback_wire_in_anchor_mandatory`, `feedback_hollow_test_anchors`.

### Code read
- `hvac_override.py`: `:2206-2400`, `:2628-2722`, `:2973-3091`, `:3094-4015`, `:5040-5130`, `:6490-6530`.
- `hvac_excursion.py`: `:60-230`, `:540-1370`.
- `hvac_predict.py`: `:400-690`, `:860-1226`, `:1409-1627`.
- `hvac_egress.py`: `:425-454`, `:635-905`.
- `hvac.py`: `:1048-1068`, `:2120-2230`, `:2380-2975`, `:3200-3435`, `:3900-3985`, `:4290-4340`, `:4760-4800`, `:5797-5888`, `:6011-6045`.
- `hvac_preset.py`: `:225-376`. `hvac_strategy.py`: full. `hvac_setpoint.py`: `:100-485`.
- `hvac_zones.py`: `:950-985`, `:2347-2371`. `presence.py`: `:2100-2161`.
- `number.py`: `:505-590`. `switch.py`: `:4232-4261`. `const.py`: `:1321-1352`.
- `ha_carrier/climate.py`: `:222-243`.

### REUSE-or-BUILD per piece

| Piece | Verdict | Symbol |
|---|---|---|
| Suppression windows | REUSE, no new window | `_is_genuine_manual` `hvac_override.py:2628-2676` |
| Reconnect guard | REUSE | `:3145-3191` |
| Match tolerance | REUSE | `LAST_SENT_TOLERANCE_F` `hvac_strategy.py:53` |
| Record of URA's recent setpoint writes | NEW, small, allowed by ruling Q1 | Only strategy `last_sent` exists, and it holds S1 presets only (`hvac_strategy.py:141-149`). No DB read on the decision path (N4) |
| Manual-episode boundary | REUSE | `hvac_override.py:3109-3115` |
| Interrupt latch | NEW set, discharged at the REUSED boundary | — |
| Borrow end with no write | REUSE | `return_excursion(..., restore_ok=None)`; precedent `force_reset` `:6517-6525` |
| Registry reads | REUSE + 1 pure accessor + 1 property | `is_borrow_active` / `excursion_id_for` (`:570-594`); NEW `live_token_for`; NEW `ExcursionToken.returned` |
| Arrester timer cancel | REUSE | the `_defer_arrester_to_borrow` loop `:3528-3533` |
| HUMAN_MANUAL classifier | REUSE | `is_human_manual_snapshot` (`hvac_strategy.py:155-168`, `:231-235`) |
| Preset → seasonal setpoints | REUSE arithmetic via a NEW callback setter | startup audit `:2222-2229`; setter pattern `set_on_sunset_notify` `:1130-1137` |
| Pre-arrival end writer | REUSE + extend | `_release_banked_zones` `hvac_predict.py:922-1099` |
| Baseline | REUSE | `_resolve_baseline_range` `:864-920` |
| Arrival signal | REUSE | `any_room_hvac_occupied`, with the fallback pattern of `hvac_predict.py:583-586` |
| Window knob | NEW, REUSE pattern | knob 52, all sites listed above |
| Part C predicate | REUSE | `is_zone_transient_blocked` `hvac_zones.py:2347` |
| Probes | NEW `hvac_borrow_end_probe.py`; REUSE `hvac_reloading_room_probe.py` | — |

---

## 1. Decisions this plan makes

| # | Decision | Why |
|---|---|---|
| P1 | A human change ends BANKING (pre-arrival and energy), PREHEAT and COMPROMISE borrows, including ownerless COMPROMISE rows. It does not end NUDGE (D13) or EGRESS_PAUSE (Q2) | Egress writes only mode `off` for an open door (`hvac_egress.py:721`). Ending its bookkeeping would leave `_paused_by_egress` inconsistent |
| P2 | During a grace or compromise, a new human change ENDS the compromise and RE-DISPATCHES against the episode's ORIGINAL preset and baseline | The compromise answered an older value. Using the original baseline keeps the revert target fixed |
| P3 | **One reference preset per case** (H3). That preset is the revert target, and its seasonal setpoints are the delta basis, counting only the legs the human changed | Mixing presets produced "compromise toward home, then pin away". Counting only changed legs keeps S12's synthetic low (`cool − 7`) out of the delta |
| P4 | Arrival = `any_room_hvac_occupied`, hallway-excluded | A hallway crossing must not end the pre-cool |
| P5 | The pre-arrival end is a presets-only return of the snapshot, run before S1 in the same pass | The borrow contract. It also leaves no strand when S1 gates (a/b) or (d) refuse |
| P6 | Interrupt latch: no S12/S13 begin on the zone until it leaves manual (Q3). The interrupted pre-arrival episode also ends | Otherwise the next pass pre-cools over the person |

---

## 2. Measure first — read-only probes

NEW `scripts/probes/hvac_borrow_end_probe.py`. It uses the access pattern of `hvac_reloading_room_probe.py` (recorder `mode=ro`, URA DB read-only). The orchestrator runs it.

**Gates are decoupled.** D1/D2 (Part A) depend on P1. D3/D4/D5, D6 and C3 do not, and can build even if P1 sends D1 back to the plan.

| Id | Question | Use |
|---|---|---|
| **P1** (M7) | **Window 2026-09-26 00:00 CDT onward**, when `climate_write` coverage began (v5.103.16). Take every recorder change where both sides are `heat_cool`, `preset_mode == manual` and all four legs are numeric, and at least one leg changed. Apply the D1 changed-legs rule against the last 4 URA `set_temperature` rows (`values_after`) for that entity. Classes: `matched`, `unmatched_borrow_live`, `unmatched_no_borrow`. Report echo lag, and split out arrivals more than 5 min after the last URA write (the ha_carrier full-read release, C16/C21). **Minimum N = 20 within-manual changes.** If N < 20, extend back to 2026-09-12 for nudge windows only, using `ac_ramp_events` nudge values as the "URA writes". | **D1 gate:** 0 unmatched rows inside a known URA window (an `ac_ramp_events` nudge window or a borrow window). The 09-28 22:15:40 zone_2 row must come out unmatched. **Named remediation branch:** if any unmatched row falls inside a known URA window, STOP D1/D2. Return to the plan with those rows (value, lag, legs) and decide between a wider match rule and a feed-specific exclusion then. Do not raise the depth blindly. **Fixture:** commit the 09-28 22:03–22:16 zone_2 rows as `quality/tests/fixtures/hvac_09_28_zone2_prearrival.json`, with the expected class per row taken from P1 (L1) |
| P2 | Every `S12_pre_cool` borrow over 14 d: duration, trigger, and the count of `climate_write` rows with its `excursion_id`, plus NULL-id S12 writes in its window | Sizes the lifetime and ratchet problems |
| P3 | Minutes from `pre_arrival` to the zone's first HVAC-occupied sample; share with no arrival inside 30 / 60 / 110 min | Default for the D5 window |
| P4 | Seasonal setpoints the resolver returns for home / away / sleep now, compared with Bryant profile values seen when a zone sits in that named preset | Checks P3's basis. If a preset disagrees by ≥ 1 °F, the README says so and the fixture AC uses the live values |
| P5 | `climate_write` rows with `site='S4_revert'` and `values_after.preset_mode='manual'`; also `site='startup_audit_nudge_preset_restore'` with `manual` | Confirms D2d and D6 |
| P6 | Re-run `hvac_reloading_room_probe.py` P1/P3 since v5.103.15 | README evidence for C3, and the Appendix A trigger |
| **P7** (W3 G0) | Classify the 12 out-of-window S12 BANKING borrows that are not pre-arrival (of the 73 found by the W3 G0 cross-check). For each borrow, from `climate_write.reason`, `hvac_excursion_events`, `ura_activity_log` and recorder: (a) the `reason` on its first write; (b) any `pre_arrival` row in the 30 min before; (c) master or energy gate flips; (d) the post-restart orphan reconciliation (`hvac_predict.py:522-543`) or a boot `stale_boot_release`; (e) a time-zone slip, UTC vs local, against the window; (f) other. Output one row per borrow | Any class that is a pre-arrival variant Part B does not cover → add it to Part B before build. Any other class → a new card. P7 does not block Part A |

---

## PART A — A human change ends a non-nudge borrow

### A.0 Producer / consumer

**Producer: the within-manual human change.**
- Inputs: the HA `state_changed` event, which carries status-feed values. §5 of the state of play warns that status values lag, and that ha_carrier's 5-min guard can hide a cloud revert and then release it on a full read (C16/C21). Also the NEW record of URA writes.
- Failure direction:
  - An unmatched URA echo read as human is the harmful direction. P1 measures it, and H1 removes the mode-change form of it.
  - A human value that equals a recent URA value is missed. That is today's behaviour and the safe direction.

**Consumers:**

| Consumer | file:line | Kind |
|---|---|---|
| `override_detected` row (new keys) | `hvac_override.py:3366-3388` | Durable; Tier 2-DB trigger |
| `_last_detection` → S1 `_classify_manual_episode` | `:3363`; `hvac.py:3398-3406` | Ledger label |
| `override_count_today` | `hvac_override.py:3396/3432/3444/3459` | Optimizer advisory at ≥ 10/day (`optimization.py:2471-2508`); comfort-score penalty (`sensor.py:1596`) |
| D2 end, D2e latch, governed dispatch | new; `:3466-3496` | Trust |

### A.1 Falsifiable invariants

> **INV-A.** Suppose D1 classifies a change on zone Z at wall-clock time t as HUMAN: both states `heat_cool`, `manual` → `manual`, legs numeric, outside suppression, and no match among URA's last 4 setpoint writes to that entity. Suppose also that a BANKING, PREHEAT or COMPROMISE borrow B is live on Z at t (owned or ownerless). Then, until Z next leaves `manual`:
> 1. no `climate_write` row for Z's entity has `excursion_id = B.id` and a row timestamp after t (the wall-clock issue time);
> 2. no `climate_write` row for Z has `site ∈ {S12_pre_cool, S13_pre_heat}`;
> 3. B's `hvac_excursion_events` row has `trigger='human_interrupt'` and a NULL `restore_ok`.
>
> **Allowed writes to Z in that period (carve-outs, M8):** S1 under the §9e gates; the arrester's S3/S4 for the NEW episode; S5 nudge starts and AC hard resets (D48/D52); egress mode writes; the heat_cool enforcer.
>
> **INV-A4 (D13).** With a nudge live on Z, the change is booked `nudge_win`, the nudge is not ended, and no arrester timer is created.
>
> **INV-A5.** A URA `set_temperature` echo that matches one of the last 4 URA writes is never booked HUMAN. A mode change (either side not `heat_cool`) is never booked HUMAN by D1.
> Carve-outs (L3): writes that bypass the funnel, namely the optimizer's allowlisted raw call (`optimization.py:3545`, shadow by default) and AI-rule chained scripts/scenes (`coordinator.py:1104-1137`). Both are out of scope.

### D1: Detect a human within-manual change

**Where.** `_handle_climate_change`, replacing the test at `hvac_override.py:3216-3226`. It runs after the reconnect guard and after `_is_genuine_manual` (REUSED windows).

**The rule.** A pure function, `classify_manual_setpoint_change(old_state, new_state, recent, tol) -> "none" | "ura_echo" | "human"`:
1. **(H1)** Return `none` unless `old.state == new.state == "heat_cool"` AND `old.preset_mode == new.preset_mode == "manual"`.
2. **(H1)** Return `none` unless all four legs (old/new high/low) are numeric (`float()` succeeds).
3. `changed_legs` = the legs whose value differs. If none, return `none`.
4. If ANY entry in `recent` has `abs(entry.leg − new.leg) ≤ tol` for every changed leg, return `ura_echo`.
5. Otherwise return `human`.

On `human`, set `is_override = True` and `within_manual = True`. On `ura_echo`, return with one DEBUG line. The into-manual branch (`:3218`) is unchanged.

**The record (ruling Q1).**
- A module-level map in `hvac_setpoint.py`: `entity_id → deque[(low, high)]`, `maxlen = ARRESTER_URA_WRITE_RING_DEPTH` (4). No timestamp (L7).
- Appended in `emit_set_temperature` right after the post-guard `service_data` is built (`:427-431`), BEFORE the wire await, so failed calls are recorded too.
- Read through the pure accessor `recent_ura_setpoints(entity_id)`.
- No other funnel change. The AST funnel lint guarantees it is complete apart from the L3 carve-outs.

**Boot seed.** After `async_startup_excursion_audit` (`hvac.py:1432`), seed the record from each rehydrated row's `excursion_target_low/high`.
- L2: the listener is live from `hvac.py:1401`. For those few seconds of awaits, an unseeded echo could be read as human. Accepted: the first post-restart state change has `old_state=None` and is dropped (`:3100`), and no URA write happens in that window.

**Ledger.** `override_detected` details gain `within_manual`, `changed_legs`, `human_interrupt`, `interrupted_excursion_id`, `interrupted_kind`, `baseline_case` (A/B/C/transition) and `gate_snapshot_pre_interrupt`.

#### Acceptance criteria
- **Verify:** fixture rows are classified per P1 (L1). Expected:
  - 22:04:05 (into manual, 78): classifier `none`. This is the transition branch, dropped by the 15 s temp window.
  - 22:04:26 (76) and 22:06:02 (74): `ura_echo`, or dropped in-window.
  - 22:15:40 (71): `human`.
- **Test:** `test_classify_within_manual_fixture_09_28`. Oracle classes are typed by hand from P1.
- **Test:** `test_classify_mode_change_is_none`. off↔heat_cool, cool→heat_cool, and legs → None (H1).
- **Test:** `test_egress_mode_off_during_banking_not_booked_human` (the H1 repro).
- **Test:** `test_within_manual_change_books_override_detected_row`. **Mutation:** restore the `:3218` two-branch test → red.
- **Test:** `test_emit_set_temperature_records_before_await` (the service call raises and the entry still exists). **Mutation:** append after the await → red.
- **Test:** `test_recent_writes_depth_bound`.
- **Test:** `test_boot_seed_from_rehydrated_rows`.
- **Test:** `test_reconnect_within_manual_ignored`.
- **Live:** operator-staged. During a live zone_1 nudge, change the setpoint by 2 °F in the app. Expect `override_detected` with `within_manual=true` and `gated_reason='nudge_win'`, no arrester timer, and the nudge restoring on schedule. **Discriminates:** before the fix there is no row.
- **Live:** 7 d after deploy, `override_detected` rows with `within_manual=true` whose values match one of the prior 4 `climate_write` rows for the entity = 0. Rows with either state not `heat_cool` = 0.

### D2: Apply the ruling

**D2a — End.** After `is_override` and after the unchanged `_nudge_live` check (`:3307-3310`):
- Let `T = live_token_for(zone_id)`. T is endable if:
  - `T.kind ∈ {BANKING, PREHEAT}`; or
  - `T.kind == COMPROMISE` and the zone has neither a `_compromise_timers` entry nor a `_compromise_excursion_tokens` entry (an ownerless row, M3).
- If T is endable: schedule `return_excursion(T, trigger="human_interrupt", restore_ok=None, trigger_detail=...)`. Add the entity to `_interrupt_latch`. Force `_borrow_row=False` and rebuild `gate_snapshot`.
- The owned-compromise case is D2c.
- Precedence after this point is unchanged: `immune_stamp` → `borrow_active` (EGRESS rows, and a fresh NUDGE row with no live timers) → `temp_arrester_override` → `comfort_grant` → `passive_mode` → governed.
- Scheduling (rather than awaiting) is safe: an S1 pass that sees the row first defers once.

**D2b — Owner guards on `token.returned`.** Pop the token and write nothing:

| Site | file:line |
|---|---|
| S11 `_release_banked_zones` | `hvac_predict.py:922-1099` (before any emit) |
| S13 `_return_preheat` | `:1518-1606` |
| **(M1)** S12, immediately before `emit_set_temperature` | `:1193` (also unsuppress) |
| **(M1)** S13 start, immediately before its emit | `:1482` (also unsuppress; no return timer) |

**D2c — Compromise and grace re-dispatch (H2, L6).** If the zone has `_grace_timers` or `_compromise_timers`:
1. Cancel ONLY those two timers (the `:3528-3533` loop; `_reset_timers` survives). Clear `_override_active` / `_compromise_active`.
2. Bump `_arrest_episode[zone]["gen"]`.
3. If an owned compromise token exists, schedule `_compromise_release_lease(zone, trigger="human_interrupt", restore_ok=None, trigger_detail="compromise_superseded_by_human")`.
4. **Force `_borrow_row = False` and `_comp_live = False` for this evaluation and rebuild `gate_snapshot` BEFORE the precedence ladder**, so the ladder cannot reach `borrow_active` (`:3317`) for this zone.
5. Dispatch using case B.

**L6 race.** `_apply_compromise` and `_revert_override` capture `gen` when scheduled and return without writing if it has changed. This covers a task that was already pending when its timer handle was cancelled.

`_arrest_episode[zone] = {original_preset, expected_cool, expected_heat, gen}` is written in `_handle_severe_override` / `_handle_normal_override`. It is cleared in `_revert_override`, `_defer_arrester_to_borrow`, the `enabled=False` setter and `teardown()`. It lives in RAM, as grace and compromise already do.

**Baseline — one reference preset per case (H3, P3):**

| Case | Reference preset R (the revert target) | Delta basis per CHANGED leg |
|---|---|---|
| A: BANKING/PREHEAT borrow T ended | `T.pre_preset` if named (not `is_human_manual_snapshot`), else the resolver's house-target preset | the seasonal setpoints of R |
| B: arrester episode in flight | `episode.original_preset` | `episode.expected_*` (itself derived from R when the episode began) |
| C: plain within-manual change (no borrow/episode), or an ownerless compromise ended | the resolver's house-target preset | the seasonal setpoints of R |
| Transition into manual, no interrupt | today's `old_preset` | today's `old_high/low` (unchanged) |

- Resolver: NEW `arrester.set_baseline_resolver(cb)`, mirroring `set_on_sunset_notify`. `cb(zone_id, preset=None) -> (preset, cool, heat) | None`, using the startup-audit arithmetic. `preset=None` means the house target.
- If it returns None: book the row, do not dispatch, and let S1 reclaim.
- Thresholds are unchanged (`OVERRIDE_NORMAL_DELTA` 1, `OVERRIDE_SEVERE_DELTA` 3, coast bonus).

**D2d — The S4 revert value.**
- At `hvac_override.py:3938-3942`, `_revert_preset` = the compromise token's `pre_preset` only if it is not a HUMAN_MANUAL snapshot; otherwise `original_preset`.
- If neither is named, skip the S4 write and close the lease with `restore_ok=None` and `trigger_detail="revert_no_named_preset"`.
- The reason literal stays `severe_override_revert`.

**D2e — Interrupt latch (H4).**
- `OverrideArrester._interrupt_latch: set[str]` holds entity_ids and is added to by D2a/D2c.
- It is removed ONLY:
  - in the manual-exit block `hvac_override.py:3109-3115`, next to `_last_detection.pop`;
  - in `teardown()`.
  Later bookings in the same episode do not touch it.
- Pure accessor `interrupt_latched(entity_id)`. The predictor checks it before the S12 begin (both reasons) and the S13 begin.
- Discharge: the zone leaves manual (S4 pin, S1 reclaim or a human preset). ~~Backstop: RAM, so a restart loses it. At boot, BANKING rows are released with a preset pin, and that ends the manual episode.~~ **CORRECTED fix-up 1 (D-M1, D-M2):**
  - Discharge happens only when the new state is readable (not unavailable/unknown) AND the new preset is a non-empty named preset other than `manual`. A manual → unavailable → manual flap keeps the latch.
  - The latch is PERSISTED in the `_zone_state_store` side-key `__interrupt_latch` (precedent `__immune_holds` / `__tao_state`). It is saved on every set and discharge, and it is part of the shutdown snapshot taken before the arrester teardown.
  - At boot it is restored only while the zone still reads `manual`. It is also kept while the state is unreadable, and discharged if the zone reads a named preset.
  - So a restart mid-interrupt begins no S12/S13 on the zone.
- **L5 (accepted, documented):** a status-feed flicker manual→named→manual also discharges it. That flicker ends the arrester's episode by the same rule.
- `_expire_pre_arrival_zones` also clears a zone whose pre-arrival token is `returned`, with reason `interrupted` (a pull, not a callback). The fans are left on.

**D2f — Disable releases compromise rows (M3).** In the `enabled=False` setter (`:3070-3091`), for each zone with an owned compromise token, schedule `_compromise_release_lease(zone, trigger="arrester_disabled", restore_ok=None)`. Rehydrated and teardown orphans are handled by the D2a ownerless rule, or the sweep at `stale_ts` (a 15-min compromise plus 30 s).

#### What the operator will see — the 09-28 zone_2 replay (H3)

1. 22:03:51 — pre-arrival for Jaya. **One** pre-cool write: away's baseline − 2 °F (D4). No 78 → 76 → 74 walk.
2. 22:15:40 — someone sets 71. URA books "override detected (within manual)" and ends the pre-cool borrow with no write. The zone leaves pre-arrival on the next pass, and no new pre-cool starts.
3. The arrester treats 71 against **Away** (the preset the zone was in before the pre-cool). That is 9 °F cooler, a severe override. **If** a room upstairs is occupied (lighting) and the battery is at or above 85 %, the person gets comfort grace (20 min) and nothing is written. **Otherwise**, after the 2-min severe grace, URA pins **Away at about 22:17:40**. If the zone is empty, S1's empty-zone retreat may send it to Away on its next pass even sooner (ruling Q4).
4. When Jaya arrives, the zone becomes HVAC-occupied and S1 sets **Home** (fast run, within about 1–2 min).

So "we end and revert" means: the person's 71 lasts about 2 minutes, unless they are in the zone with enough battery; then the zone goes back to Away until someone arrives. **Q7: the operator must confirm this is the intended meaning.** The alternative reference preset is the house target (Home), which would revert to Home 76 instead of Away.

#### Acceptance criteria
- **Test:** `test_replay_09_28_zone2_expected_writes`. Drives the fixture through the real `_handle_climate_change` and predictor. Expected:
  - exactly one S12 write;
  - a `human_interrupt` event at 22:15:40;
  - no S12/S13 write afterwards;
  - (unoccupied branch) an S4 `set_preset_mode away` at 22:17:40 ± 5 s;
  - (occupied + SOC ≥ 85 branch) a comfort grant and no S4 write.
- **Test:** `test_human_interrupt_ends_banking_borrow_bookkeeping_only`. **Mutation:** delete the D2a end → red.
- **Test:** `test_interrupt_inside_begin_await_blocks_s12_write` (M1; mutation → red) and `test_interrupt_inside_begin_await_blocks_s13_write`.
- **Test:** `test_return_preheat_skips_returned_token` and `test_release_banked_zones_skips_returned_token` (mutation-anchored).
- **Test:** `test_human_change_during_compromise_redispatches`. Asserts a NEW grace or compromise timer, `gated_reason != 'borrow_active'`, and the S4 target is the original preset. **Mutation:** drop the H2 forcing → red.
- **Test:** `test_pending_apply_compromise_stands_down_on_gen_bump` (L6).
- **Test:** `test_ownerless_compromise_row_ended_by_human` (M3).
- **Test:** `test_arrester_disable_releases_compromise_rows` (D2f).
- **Test:** `test_nudge_live_human_change_nudge_win_not_ended` (INV-A4). **Mutation:** move the end above `_nudge_live` → red.
- **Test:** `test_case_c_plain_within_manual_dispatch_against_resolver` (M9). Asserts the severity path against the house-target preset.
- **Test:** `test_case_c_resolver_none_books_no_dispatch` (M9).
- **Test:** `test_case_a_single_reference_preset` (H3). A human 78 with pre_preset away (80) and house target home (76) gives delta −2 vs away, a compromise at 79, then S4 away. **Mutation:** use resolver setpoints for the delta → red.
- **Test:** `test_interrupt_latch_survives_second_human_change` (H4 repro: 71, then 70, then no S12 begin). **Mutation:** keep the latch in `_last_detection` → red.
- **Test:** `test_interrupt_latch_discharges_on_manual_exit`.
- **Test:** `test_s4_revert_never_pins_manual` (D2d). **Mutation:** restore the truthy test → red.
- **Test:** `test_immune_person_interrupt_ends_borrow_and_stamps` and `test_passive_mode_interrupt_ends_borrow_no_revert`.
- **Test:** `test_interrupt_does_not_cancel_reset_timers`.
- **Live:** the next organic or operator-staged human change during a pre-arrival pre-cool shows:
  - event `trigger='human_interrupt'` with a NULL `restore_ok`;
  - `override_detected.within_manual=true`;
  - no S12 `climate_write` for the zone until it leaves manual;
  - an S4, comfort-grant or S1 write per the replay paragraph.
  **Discriminates:** today's outcome is a `lease_expiry` row about 7200 s later and no detection row.
- **Live:** 7 d, count of S4 `climate_write` rows with `values_after.preset_mode='manual'` = 0.
- **README:** one line stating case C. The arrester now also acts on a person fine-tuning an existing manual hold, measured against the house-target preset (M9).

### D6: The boot audit never pins `manual` after a nudge (Batch A, LOW-4)
- In `async_startup_excursion_audit`'s NUDGE branch (`hvac_excursion.py:1126-1148`), skip the `set_preset_mode` when `pre_preset in (None, "", "manual")`. This is the same rule as HIGH-1 at `:660`.
- Log `startup_audit_nudge_preset_restore_skipped_manual` and still clear the row.
- The S9 ramp audit restores the setpoints, and S1's §9e reclaim returns the zone to its target on the next tick.
- Sibling noted, not changed: S7 (`hvac_override.py:5108-5129`) re-pins `manual` after S6's raw restore for a HUMAN_MANUAL snapshot. That pin is idempotent over the just-restored values, so it is left as is (a candidate for a later cleanup card).

#### Acceptance criteria
- **Test:** `test_boot_audit_nudge_manual_snapshot_no_pin`. **Mutation:** remove the skip → red.
- **Test:** `test_boot_audit_nudge_named_snapshot_still_pins` (byte-identical twin).
- **Live:** P5 query, `startup_audit_nudge_preset_restore` rows with `manual` after deploy = 0.

---

## PART B — Pre-arrival borrow lifetime

### B.0 Producer / consumer

**Producers:**
- The `_pre_arrival_zones` set (`hvac.py:5798-5855`). Each trigger resets `_pre_arrival_start`.
- The S12 pre-arrival borrow. Its baseline comes from `_resolve_baseline_range`, which prefers `_last_emitted_range`. That map is written only by S10 (dormant), S11 and S13, so on the live house it is often stale or empty (Bug Class #7). The fallback is the house-target preset: seasonal cool, and a synthetic low of `cool − 7`.

**Consumers of set membership:**

| Consumer | file:line | Kind |
|---|---|---|
| Row-1 hold eligibility | `hvac.py:2586` | Trust |
| Reason ladder | `:3335` | Ledger |
| D5 away edge | `:4316` | Trust |
| `zone_presence_state` | `:6031` | Display |
| Sensor attrs | `:6716`, `:6785` | Display |
| Predictor | `:2215` | Trust |

Borrow consumers: gate (e), the arrester, the borrows sensor (`sensor.py:18199`) and `hvac_excursion_events`.

### B.1 Falsifiable invariant

> **INV-B.** For every borrow with `caller_site='S12_pre_arrival'` on zone Z:
> 1. exactly one S12 `set_temperature` carries its id, with `target_temp_high = max(baseline_high + PRE_ARRIVAL_PRECOOL_OFFSET_F, floor)`;
> 2. its trigger ∈ {`pre_arrival_arrived`, `pre_arrival_timeout`, `pre_arrival_interrupted`, `pre_arrival_inactive`, `pre_arrival_max_age`, `human_interrupt`}. Carve-outs (M8): `stale_boot_release` (a restart mid-borrow) and the CM `s12_banking_wire_failed` release. Never `lease_expiry`;
> 3. it ends in the first FULL pass, or the first fast run scoped to Z, that removes Z from the set, finds pre-arrival inactive, or finds the borrow at least `window` old. It ends before S1 in that pass;
> 4. no S12 or S13 write lands on Z while another borrow row is live on Z.

### D3: End conditions

**Arrival.** `_expire_pre_arrival_zones` gains a `zone_filter` parameter.
- Arrival is read from `any_room_hvac_occupied`, falling back to lighting only when the attribute is missing (P4).
- It returns `{zone_id: reason}` with reason ∈ {`arrived`, `timeout`, `interrupted`}.
- The timeout reads the D5 knob.

**The single reconciliation (NEW).** `predictor.async_end_pre_arrival_borrows(active_zones, reasons, window_s, zone_filter=None)` walks `_banking_excursion_tokens` for tokens with `caller_site == "S12_pre_arrival"`, within `zone_filter` if one is given:
- `returned` → pop the token, no write;
- zone not in `active_zones` → `_release_banked_zones({Z}, trigger=f"pre_arrival_{reason or 'inactive'}", update_throttle=False)`;
- **(M5)** `now − token.started_ts ≥ window_s` → the same release with trigger `pre_arrival_max_age`, AND drop Z from the pre-arrival set. This bounds repeated triggers by the borrow's own start, not the last trigger.

The S11 preset emit keeps `reason="banking_release"`, so no new reason literal is added.

**Call sites.** Both run before S1, then refresh the zone's climate state (`update_zone_climate_state`, `hvac_zones.py:600`):
- **Full pass:** after the ZI block (`hvac.py:2145-2149`) and before `_apply_house_state_presets` (`:2174`), outside the `if zi` guard, with `active = self._pre_arrival_zones if zi else set()`.
- **Fast run (M10):** `_expire_pre_arrival_zones(now, zone_filter={Z})` and `async_end_pre_arrival_borrows(..., zone_filter={Z})` at `:4780`, before `:4782`. Other zones are left untouched; the next full pass ends them before its S1.

It runs whatever the observation mode (S12 starts regardless, `hvac.py:2212`).

**Site string.** S12 begins with site `S12_pre_arrival` for the pre-arrival reason. The `climate_write` site is unchanged (`S12_pre_cool`, `reason="pre_arrival"`). `caller_site` consumers are display and DB only. Tests that pin `S12_pre_cool` for this path are updated.

#### Acceptance criteria
- **Test:** `test_pre_arrival_ends_on_hvac_arrival_before_s1` (the order is pin, then S1). **Mutation:** move the call after `_apply_house_state_presets` → red.
- **Test:** `test_pre_arrival_ends_on_timeout_knob`.
- **Test:** `test_pre_arrival_max_age_with_repeated_triggers` (M5: triggers every 10 min, and it ends at `window` from the start).
- **Test:** `test_knob_max_ends_before_lease_sweep` (window 110, no arrival, never `lease_expiry`).
- **Test:** `test_hallway_lighting_does_not_end_pre_arrival` (P4). **Mutation:** revert to lighting → red.
- **Test:** `test_zi_off_ends_pre_arrival_borrows`.
- **Test:** `test_fast_run_ends_only_its_zone` (M10: Y is untouched in Z's fast run and ended on the next full pass before S1).
- **Test:** `test_pre_arrival_release_does_not_touch_last_emitted_range`.
- **Live:** the next pre-arrival shows `site='S12_pre_arrival'`, a trigger from INV-B.2, and `duration_actual_s ≤ window + 300`. **Discriminates:** today it is `lease_expiry` at about 7200 s.
- **Live:** after a zone's pre-arrival ends, it has 0 `vacancy_bypass_deferred:active_borrow` rows.

### D4: No ratchet — one write, from the baseline
- **The guard.** In the pre-arrival branch (`hvac_predict.py:645-653`), call `_execute_zone_pre_cool` only if `not is_borrow_active(zone_id)` and `not interrupt_latched(entity)`.
- **The value.** NEW keyword `from_baseline=True`: `banked_high = baseline_high + PRE_ARRIVAL_PRECOOL_OFFSET_F`. If the baseline is None, skip. The floor (`:1137`) and the "never warm the zone" check (`:1140`) are kept.
- **D4b — foreign-row guard at S12 AND S13 (M2).** If `begin_excursion` returned None and the live row's id is not this path's own token (same id and same `caller_site`), return before the suppress and the emit. S12 energy pre-cool on its own row is unchanged (its ratchet is a non-goal and a card).
- **README:** the first pre-arrival write moves from "live − 2" to "baseline − 2".

#### Acceptance criteria
- **Test:** `test_pre_arrival_single_write_across_three_triggers`. **Mutation:** drop the guard → 3 writes → red.
- **Test:** `test_pre_arrival_value_from_baseline_not_live`.
- **Test:** `test_pre_arrival_baseline_none_no_write`.
- **Test:** `test_s12_never_writes_over_foreign_row` and `test_s13_never_writes_over_foreign_row`. **Mutation:** remove each guard → red.
- **Test:** `test_energy_precool_own_row_behaviour_unchanged`.
- **Live:** for each `S12_pre_arrival` id, count of `climate_write` rows = 1.

### D5: Knobs

| Number | Rung | Knob | Why |
|---|---|---|---|
| Pre-arrival window, 30 min | **3** | NEW `CONF_HVAC_PRE_ARRIVAL_WINDOW_MINUTES` in `hvac_const.py` next to `CONF_PRE_ARRIVAL_SOURCES` (`:349`). Default `PRE_ARRIVAL_TIMEOUT_MINUTES` (30, REUSED). Entity `35 · Pre-Arrival Window (min)` (`number.ura_hvac_coordinator_35_pre_arrival_window_min`), range **5–110** (M5), step 5, CONFIG category. Settings-form field "Pre-arrival window (minutes)" as well (knob-52 precedent) | The operator asked for it and it is tuned by observation. Max 110, plus one 5-min pass, stays under the 7200 s lease. 0 is not allowed; turning pre-arrival off is the switch's job |
| Offset, −2 °F | 1 | NEW `PRE_ARRIVAL_PRECOOL_OFFSET_F` | Comfort magnitude; no evidence yet for a live knob |
| Record depth, 4 | 1 | NEW `ARRESTER_URA_WRITE_RING_DEPTH` | Defines what counts as human, so a change should need review |
| Tolerance, 0.5 °F | 1 | REUSE `LAST_SENT_TOLERANCE_F` | — |
| `EXCURSION_LEASE_MAX_S`, 7200 | 1, unchanged | — | A backstop, not a lifetime |

**Knob wiring (M6)** — every site of the knob-52 precedent, or the knob either reloads the CM or silently does nothing:
1. `number.py`: new class following `ReturnWindowMinutesNumber` (`:511-587`), registered in the HVAC numbers list. It pushes `hvac._pre_arrival_window_minutes` BEFORE the options writeback.
2. `__init__.py`: setup read (`:3776` / `:3899`), import (`:6201`), `OPTIONS_RELOAD_SUPPRESS_KEYS` (`:6859` — **mandatory, or a knob turn reloads the CM**), apply-in-place set (`:7287`), dispatch branch (`:7389-7400`).
3. `config_flow.py`: the settings step (`:5934`, `:6497-6499`), plus `strings.json` / `translations/en.json`.
4. `hvac.py`: `_pre_arrival_window_minutes`, read by `_expire_pre_arrival_zones` and D3.

#### Acceptance criteria
- **Sensor:** `number.ura_hvac_coordinator_35_pre_arrival_window_min` = 30 after deploy.
- **Test:** `test_pre_arrival_window_knob_live_and_persisted`. **Mutation:** read the const → red.
- **Test:** `test_pre_arrival_window_key_in_reload_suppress_set`.
- **Live:** set it to 20. The CM does NOT reload (sibling `last_changed` is unchanged), the options value is 20, and the expiry uses 20. Then set it back to 30.

**Answer to the operator ("pre-cool is 2 hours? Is this a knob?").** No. Pre-cool was meant to last until you arrive, or 30 minutes. The 2 hours was a safety cap it fell back on because nothing ended it. Now it ends on arrival, on the window, or when someone changes the thermostat. The window becomes the knob `35 · Pre-Arrival Window (min)` (5–110 min).

---

## PART C — Reloading-room readers: the occupancy clock only (ruling Q5)

The design is reused from `PLANNING_hvac_reloading_room_placeholder_readers.md` §4 D3. The other three readers are in Appendix A.

**Recorded pushback:** that plan's D0 (2026-09-27) found 0 reloading-room samples and 0 boot resets. C3 is insurance for the stuck-occupancy failsafe's clock. P6 refreshes the evidence for the README.

### C.1 Falsifiable invariant

> **INV-C.** On any pass where zone Z contains a TRANSIENT room and fused HVAC occupancy is False, `Z.continuous_occupied_since` after the pass equals its value before the pass. The v5.103.20 `last_occupied_time` back-fill runs exactly as it does today.

### C3: The occupancy clock is not reset while a room is reloading
- In `hvac_zones.py`, the `else:` branch starting at `:970`: guard ONLY the single assignment `zone.continuous_occupied_since = None` (`:972`) with `if not self.is_zone_transient_blocked(zone.zone_id):`.
- The rest of that `else` block, including the v5.103.20 back-fill (`:973+`), stays unconditional (M4).
- `is_zone_transient_blocked` returns False until classification is ready (`:2362-2363`), so the first boot pass behaves as today.

#### Acceptance criteria
- **Test:** `test_continuous_clock_not_reset_while_room_reloading` (real `update_room_conditions` and a real `ConfigEntryState`). **Mutation:** remove the guard → red.
- **Test:** `test_backfill_still_runs_while_room_reloading` (M4). **Mutation:** move the guard to wrap the whole `else` → red.
- **Test:** `test_continuous_clock_resets_after_room_excluded` (the 300 s discharge).
- **Test:** `test_boot_pass_keeps_restored_continuous_clock`.
- **Live:** after the next HA restart, for zones HVAC-occupied on both sides of it, `continuous_occupied_hours` on `sensor.ura_hvac_coordinator_zone_{n}_status` at the first sample is ≥ the last sample before the stop.

---

## 3. Emission-site enumeration

The reviewers re-run this independently.

**Begins**

| Site | Kind | file:line | Change |
|---|---|---|---|
| S3 compromise | COMPROMISE | `hvac_override.py:3732` | L6 gen check in `_apply_compromise` |
| S5 nudge start | NUDGE | `:4823` | none (D13/D52). May begin on a `manual` zone, hence D6 |
| S12 energy | BANKING | `hvac_predict.py:598` → `:1154` / `:1193` | D2e latch; D4b; M1 returned-check |
| S12 pre-arrival | BANKING | `:649` → `:1154` / `:1193` | site `S12_pre_arrival`; D4; D4b; D2e; M1 |
| S13 pre-heat | PREHEAT | `:1445` / `:1482` | D2e latch; D4b (M2); M1 |
| S15 egress | EGRESS_PAUSE | `hvac_egress.py:688` | none (Q2) |
| Boot rehydrate | PREHEAT / COMPROMISE / EGRESS | `hvac_excursion.py:1240-1256` | D1 boot seed; ownerless COMPROMISE is endable (D2a) |

**Returns and ends**

| Site | Kind | file:line | Change |
|---|---|---|---|
| S4 revert → `_compromise_release_lease` | COMPROMISE | `hvac_override.py:3817-4014` | D2d value; L6 gen check; D2c new exit |
| S6/S7 nudge restore | NUDGE | `:5040-5130`, `:5293` | none (S7 `manual` pin noted in D6) |
| S8 cancel-nudge / force_ac_reset | NUDGE | `:6298-6412`, `:6517-6525` | none |
| S9 boot ramp audit | NUDGE | `:6770`, `:6791` | none |
| S11 `_release_banked_zones` (callers `:472`, `:542`, `:551`, D3) | BANKING | `hvac_predict.py:922-1099` | D2b guard; `trigger` / `update_throttle` params |
| S13 `_return_preheat` | PREHEAT | `:1518-1606` | D2b guard |
| Egress resume / abort / orphan | EGRESS | `hvac_egress.py:773-904`, `:442-453` | none |
| Lease sweep → `_auto_return` | non-nudge | `hvac_excursion.py:733-778`, `:632-730` | none (an INV-B failure for pre-arrival) |
| Boot audit NUDGE | NUDGE | `:1126-1167` | **D6 manual skip** |
| Boot audit BANKING / stale | BANKING / all | `:1169-1238` | none |
| CM auto-release; `_reap_stale` | all | `:1297-1365`; `:597-608` | none |
| NEW human-interrupt end | BANKING / PREHEAT / ownerless COMPROMISE | `_handle_climate_change` | D2a |
| NEW compromise supersede | COMPROMISE | `_handle_climate_change` | D2c |
| NEW pre-arrival end | BANKING (`S12_pre_arrival`) | `async_end_pre_arrival_borrows` | D3 |

**End paths WITHOUT a return (orphaning), per M3:**

| Path | file:line | How it is covered |
|---|---|---|
| `enabled=False` setter | `hvac_override.py:3070-3091` | D2f releases compromise rows |
| `teardown()` | `:2346-2362` | synchronous; the orphan is rehydrated at next boot, then D2a ownerless rule or the sweep |
| Rehydrated COMPROMISE / PREHEAT with no owner | `hvac_excursion.py:1240-1256` | D2a ownerless rule (COMPROMISE); PREHEAT: D2a ends it on a human change, the sweep otherwise |

**Other wire writers:** S1 (§9e), the heat_cool enforcer, AC hard reset, egress mode, and S10 (dormant). No change.

---

## 4. Edge cases (QUALITY_CONTEXT)

- **#53.** Every site that can still write for an ended token has a guard: the D2b table (4 sites), D3 pop, the D2e latch (S12, S13) and the L6 gen checks. Reviewer C mutates each.
- **#7.** D3 does not write `_last_emitted_range`. The existing S11/S13 writes stay pre-existing; card them if P4 shows a mismatch.
- **#22 / L4.**
  - New site: `S12_pre_arrival`.
  - New triggers: `human_interrupt`, `pre_arrival_{arrived,timeout,interrupted,inactive,max_age}`, `arrester_disabled`.
  - New details: `compromise_superseded_by_human`, `revert_no_named_preset`.
  - None of these reaches `reason=` (S11 keeps `banking_release`; S4 keeps `severe_override_revert`). A builder who adds any `reason=` literal must add it to `HVAC_PRESET_REASONS` (`const.py:1321`).
  - Grep every consumer of trigger and site values before merge.
- **#23.** D3 ends borrows in observation mode, symmetric with S12 starts.
- **#32.** The D5 wiring list.
- **D49 / Q4.** A human change to an empty zone is still sent to Away by S1 on its next pass. That is the ruling.
- **Restart.** The record (boot-seeded), `_arrest_episode`, the latch and the pre-arrival set are all RAM. BANKING rows are released at boot.

---

## 5. Non-goals
- Boot-window reconciliation (ARRESTER-BOOT-BLIND-1 gap (1)).
- A human choosing a NAMED preset during a borrow (card it).
- Human `hvac_mode` changes. D1 now explicitly returns `none` for them.
- The energy pre-cool ratchet on its own row: NEW card `HVAC-ENERGY-PRECOOL-RATCHET-1`.
- Nudge starts on a `manual` zone (D48/D52). Only their boot-restore consequence is fixed (D6).
- The S7 `manual` re-pin (idempotent, noted).
- Changes to `begin_excursion` / `return_excursion` semantics. Only the pure `live_token_for` and the `returned` property are added.
- A DB-seeded record.
- Egress under the interrupt rule (Q2).
- Persisting grace or episodes.
- Part C readers C1/C2/C4 (Appendix A).
- No new table, DAO or signal.

---

## 6. Tier and reviews (fixed for H5 and L7)

**Tier 2-DB, plus a 4th adversarial-completeness review (ruling Q6).** Triggers:
- persisted payload changes (`override_detected` keys; excursion site and trigger values);
- trust-hierarchy ripple across the arrester, S1 gates, predictor and egress;
- a comfort and cost strategy change.

**Four parallel reviews:**
- **A — correctness and edge cases.**
  - The D1 classifier (H1 mode rules, changed legs) against the P1 fixture.
  - The one-reference-preset baseline table and the replay outcome.
  - D4 arithmetic.
  - D3 max-age.
  - The knob bounds.
  - C3's single-assignment guard.
- **B — cross-coordinator precedence, lifecycle and no-flap.**
  - The new rung vs D13/D48/D49/D50/D52.
  - D2c forcing and gen races.
  - D3 ordering before S1 in full and fast runs (M10).
  - Task scheduling vs gate (e).
  - Latch discharge.
  - Orphan paths.
  - Restart.
- **C — test authority and DB surfaces.**
  - Real per-site source mutation for every "Change" row in §3 and every named mutation.
  - Ledger and event payload shapes and values.
  - Knob round-trip, including reload suppression.
  - `climate_write` rows unchanged.
- **D — adversarial completeness (diff-blind).** State INV-A / INV-B / INV-C falsifiably and break them. Re-enumerate every begin, return, end and orphan path, including pre-existing code.

Then live validation and the README write-back.

---

## 7. Open operator questions
- Q1–Q6 are answered in §8.
- **Q7 (NEW).** Confirm the replay: after someone overrides a pre-cool, the arrester measures their change against the preset the zone was in BEFORE the pre-cool (Away on 09-28). It reverts to Away after 2 minutes, unless they are in the zone with the battery at or above 85 %, in which case they get 20 minutes. S1 then sets Home when someone arrives. The alternative is to measure and revert against the house's current target (Home), so the zone would go to Home 76, not Away 80. Is Away what "We end and revert" means?

## 8. Operator rulings 2026-09-28 (binding; answers to §7)

Operator: **"all recommendations"**.

| Q | Ruling |
|---|---|
| Q1 | YES: add the read-only URA-write record inside the setpoint funnel (record only, no behaviour change). This is an explicit, narrow exception to the W1-B "nothing added to the emit_* funnels" constraint, justified because the alternative (8+ site-local records) fails open on one missed site. |
| Q2 | YES: the egress (open-door) pause is excluded from "person interrupts". |
| Q3 | YES: after a human interrupt, no new pre-cool/pre-heat start on that zone until it leaves manual (narrow D48 carve-out). |
| Q4 | KEEP today's behaviour: a human change to an EMPTY zone is still sent Away by S1 on its next pass. |
| Q5 | Part C: build ONLY the occupancy-clock fix that feeds the stuck-occupancy failsafe; PARK the other three readers with a revival trigger (first measured reloading-room harm). |
| Q6 | ADD a 4th adversarial-completeness review (diff-blind, missed return/end sites) on top of the three framing-disjoint reviews, plus the mandatory per-site mutation tests. |

Operator follow-up on D2d (compromise revert re-pins `manual`): it did NOT escape the funnel. S4 writes through `emit_set_preset_mode` (`hvac_override.py:3945-3957`, logged as `climate_write` site=S4_revert). The defect is the VALUE: `_revert_preset` comes from the compromise token's `pre_preset` (`:3938-3942`), which is snapshotted after the human's change already put the zone in `manual`. D2d fixes the value source (the zone's pre-override preset), not the write path.

## 9. State-of-play updates due with the build
- The §0 stale citations.
- §6: interruptible kinds.
- §7: within-manual detection (heat_cool only).
- §9e: a ruling row for 2026-09-28 "person interrupts" (D13 kept; D48 narrowed per Q3; compromise re-dispatch; one reference preset per case, per Q7).
- §4.2: `S12_pre_arrival`.
- §10: new entries for the S4 `manual` pin and the boot-audit NUDGE `manual` pin, if P5 confirms them.

---

## Appendix A — PARKED W2-2 readers (C1 D5 coast defer, C2 D6 skip, C4 row-11 grant)

The design is preserved verbatim in `PLANNING_hvac_reloading_room_placeholder_readers.md` §4 (D1, D2, D4 there). Re-verified sites:
- D5 defer: `hvac.py:2896-2900` (ledger `:2908-2948`, shed `:2949-2962`).
- D6 entry: `:2679-2685`.
- Row 11: `hvac_override.py:2718`.

**Revival trigger (evaluable).** Run `scripts/probes/hvac_reloading_room_probe.py` (P1 and P4) at each HVAC cycle close (the soak-exit forcing hook). Revive the matching reader when ONE `sensor.ura_hvac_coordinator_zone_{n}_status` sample with a non-empty `transient_rooms` falls within ±300 s of any of:
- a `preset_change` `away` with reason `energy_shed_cap_reached` and `constraint_mode='coast'` (→ C1);
- a `preset_change` `away` with reason `stale_occupancy` (→ C2);
- an `override_detected` row on that zone with no comfort grant (→ C4).

Threshold: ≥ 1 coincidence in the probe window. Until then these readers stay parked. That is a clean result, not a deferral.

### Q7 ruling (operator 2026-09-28 23:50, binding)
Operator: **"Agree"** to the orchestrator recommendation: when a person interrupts a **pre-arrival** pre-cool (S12 with reason `pre_arrival`), the reference preset for BOTH the arrester delta and the revert target is the house's CURRENT S1 target for that zone (e.g. `home` in `home_evening`/`home_night`, `sleep` in `sleep`), not the borrow's pre-borrow snapshot (`away`). Rationale: a pre-arrival run means URA already expects someone, so reverting to Away only to flip to Home minutes later is churn. ALL OTHER borrow kinds (energy banking, pre-heat, compromise) keep the pre-borrow preset as the reference (H3 single-reference rule unchanged for them). 09-28 fixture expectation under this ruling: 71 is judged against Home 76 (delta 5 °F, severe); after grace, the revert pins `home`, not `away`. The builder must add this as a distinct case with its own test and replay assertion, and the README must state it. Also required (boot evidence, README_v5.103.22): at 23:40 the stale-boot release restored `away` over a human 71 set at 23:03. Once the 23:03 interrupt ends the row, the boot audit must have nothing to restore; add a replay test.


---

## Builder notes (ura-super-builder, 2026-09-29, branch `feature/hvac-w1-w2-finish`)

Mandatory reads done in full: the state of play (§0–§12, §9e, §10 C1–C26), this plan (REV 2, §8 Q1–Q6, the Q7 ruling), and the plan review. No §10 claim is re-asserted.

### Probe results (the gates)
- **P1 PASSED (D1/D2 built).**
  - Window 09-26 00:00 CDT → 09-29. `climate_write` `set_temperature` coverage starts 09-27 12:43 CDT.
  - **N = 53** within-manual changes: 48 `matched`, 2 `unmatched_borrow_live`, 3 `unmatched_no_borrow`.
  - **0 unmatched rows inside a URA echo window** (≤ 5 min of a URA temp write, or a nudge window).
  - 22:15:40 zone_2 (74 → 71) is `unmatched_borrow_live`, 577 s after URA's last write.
  - The other 4 unmatched rows are 6–7 h or 58 min from any URA write (09-27 20:28/21:31/21:32, 09-28 23:03).
  - Load-bearing detail: every nudge echo matches only because the tolerance is **inclusive** (URA 77.5 → Carrier 78 is |0.5| ≤ 0.5). Pinned by `test_classify_tolerance_boundary_inclusive`.
  - Late matched echoes (341 s, 1062 s, 2035 s) all fell inside the last 4 writes.
  - Fixture committed: `quality/tests/fixtures/hvac_09_28_zone2_prearrival.json`.
- **P5:**
  - 4 `climate_write` rows with an S4 site pinned `manual` on zone_1 (09-28 03:51Z, 06:12Z; 09-29 00:52Z, 01:11Z). This confirms D2d and adds §10 C27.
  - 0 `startup_audit_nudge_preset_restore` rows pinned `manual` in the window. D6 was built from code reading (C28).
- **P7:** 74 S12 borrows started outside [10,14) local; 13 have no `pre_arrival` row within 2 min before.
  - 12 of the 13 fall on 08-26 → 08-29, before `ura_activity_log` exists (earliest row 08-30 04:43Z), so they are unclassifiable. Not a new variant.
  - The 13th (09-28 09:00:20) has `climate_write.reason='pre_arrival'`, with `pre_arrival` rows at 08:57:54 / 08:58:12 (a 2.4-min trigger → begin lag). Part B covers it.
  - Result: no Part B addition and no new card. Note: the `pre_arrival` ledger row keeps its zones in `details_json.zones`; the `zone` column is NULL.

### Deviations and clarifications (conservative choice each time)
1. **INV-A5 on the transition branch.** D2a runs for a transition INTO manual too (the 23:03 case). A late (> 15 s) echo of URA's own S12 write arrives as exactly such a transition, so a transition counts as a person only when both sides are `heat_cool` and its changed legs match none of URA's last 4 writes (`_transition_is_human`). Booking of the transition itself is unchanged.
2. **In-flight `_apply_compromise` race.** Between `begin_excursion` and the timer, the COMPROMISE row exists with no timer or token. Two changes cover it:
   - `_compromise_active` counts as "episode in flight" (D2c) and not as "ownerless" (D2a).
   - `_apply_compromise` re-checks the generation after `begin`; if a person superseded it, it closes the just-opened row as `human_interrupt`/None and writes nothing.
   - `_revert_override` re-checks before S4, after the B4 mode await.
3. **Generation is a separate monotonic `_arrest_gen[zone]`,** not a field inside `_arrest_episode`. Clearing an episode must never reset the counter to a value a stale task still holds. The episode record also carries it.
4. **M1 also checks the latch.** The arrester SCHEDULES `return_excursion` from its synchronous callback; the latch is set synchronously in the same callback. S12/S13 skip when the token is returned **or** the zone is latched, and mark the auto-release guard committed so the scheduled `human_interrupt` return (not a false `s12_banking_wire_failed`) closes the row. Each conjunct has its own test.
5. **S12 suppression moved after `begin`,** so the D4b foreign-row return happens "before the suppress" (plan D4b).
6. **D4 value.** The plan's operator paragraph says "away's baseline − 2". The formula in D4 / INV-B.1 is `_resolve_baseline_range` + offset, i.e. the last emitted range, else the house-target preset. On 09-28 that gives Home 76 − 2 = **74** (the formula is followed; the README says 74).
7. **D4's latch conjunct is folded into `_execute_zone_pre_cool`.** That is one site for both reasons, rather than a second, redundant check in the pre-arrival branch that could never be mutation-anchored.
8. **Resolver = the house-state preset** (`get_preset_for_house_state`, the startup-audit arithmetic), not the per-zone vacancy target. Q4 leaves vacancy to S1.
9. **C3 boot pass.** The plan says the first boot pass "behaves as today". In code, `_classify_all_rooms` runs inside the same `update_room_conditions` call **before** the rollup (`hvac_zones.py` classification then the `else` at ~:970). So the guard already applies on the first pass, and a restored clock survives while rooms are still loading. That is the intended direction (P6 BOOT-RESET). Pinned by `test_boot_pass_keeps_restored_continuous_clock`.
10. **`test_interrupt_does_not_cancel_reset_timers`** pins the interrupt step (passive mode, so no dispatch). A governed re-dispatch still runs the pre-existing `_cancel_zone_timers` in the severe/normal handler, which cancels a pending AC-reset restore timer. That is pre-existing and not changed (flag for Review B).
11. **Three duplicate sites removed** because no mutation could ever turn them red:
    - the `_resolver_missing` early return (`delta = None` already blocks the dispatch);
    - the reconciliation's own returned-token branch (the D2b guard in `_release_banked_zones` pops it with no write);
    - the re-clamp in `_pre_arrival_window_s` (every writer clamps).
    - Also the redundant `return` after a URA-echo classification.
12. **Knob 35 form placement:** next to "Pre-Arrival Trigger Sources" on the main HVAC settings form (knob 52 lives in the `presence_timing` section).
13. **No new `reason=` literal.** S11 keeps `banking_release`; S4 keeps `severe_override_revert`. New values are triggers / details / site only. Consumers of `caller_site` are display (`sensor.py:18206`) and DB, plus the Q7 check.
14. **Accepted:** a single human action reported as several same-second within-manual rows (09-27 21:31:30: 68/72 → 70/80 → 70/72) books a row per step and re-dispatches each time; the last value wins and `override_count_today` counts each step.
15. **Existing tests changed to the new contract:**
    - `test_hvac_excursion_startup_audit.py::test_F1_…` (write `manual` back → not pinned, D6);
    - `test_hvac_w1b_arrester_booking.py` (BANKING row / compromise timer → egress row; the new behaviour is pinned in part_a);
    - AST-slice loader stubs;
    - suppress-set counts;
    - `test_hvac_w1a_site_migration.py` hand-built arrester (new state, checklist 9);
    - two source greps converted to behavioural tests (rule 7: `test_v5_7_1…::test_pre_arrival_block_unchanged`, `test_v4510…` floor).

### Per-site mutation drills — 104 sites, 104 RED
Each: one site neutered in source, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared, named test(s) run, restored with `git checkout`, `git status --porcelain` empty.

| Site | File | Test that went RED | Result |
|---|---|---|---|
| D1.record-call | `hvac_setpoint.py` | `test_emit_set_temperature_records_before_await` | RED |
| D1.record-after-await | `hvac_setpoint.py` | `test_emit_set_temperature_records_before_await` | RED |
| D1.ring-depth | `hvac_const.py` | `test_recent_writes_depth_bound` | RED |
| D1.cls-old-heat_cool | `hvac_override.py` | `test_classify_mode_change_is_none[off-heat_cool-old0-new0]` | RED |
| D1.cls-new-heat_cool | `hvac_override.py` | `test_classify_mode_change_is_none[heat_cool-off-old1-new1]` | RED |
| D1.cls-numeric-legs | `hvac_override.py` | `test_classify_mode_change_is_none[heat_cool-heat_cool-old3-new3]` | RED |
| D1.cls-tolerance-inclusive | `hvac_override.py` | `test_classify_tolerance_boundary_inclusive[77.5-ura_echo]` | RED |
| D1.cls-changed-legs-only | `hvac_override.py` | `test_classify_only_changed_legs_must_match` | RED |
| D1.within-manual-branch | `hvac_override.py` | `test_within_manual_change_books_override_detected_row` | RED |
| D1.transition-ring-check | `hvac_override.py` | `test_transition_late_ura_echo_does_not_end_borrow` | RED |
| D1.boot-seed-call | `hvac.py` | `test_boot_seed_from_rehydrated_rows` | RED |
| D2a.not-nudge-live | `hvac_override.py` | `test_nudge_live_human_change_nudge_win_not_ended` | RED |
| D2a.interrupt-eligible | `hvac_override.py` | `test_transition_late_ura_echo_does_not_end_borrow` | RED |
| D2a.end-call | `hvac_override.py` | `test_human_interrupt_ends_banking_borrow_bookkeeping_only` | RED |
| D2a.force-borrow-row | `hvac_override.py` | `test_human_interrupt_ends_banking_borrow_bookkeeping_only` | RED |
| D2a.kinds-preheat | `hvac_override.py` | `test_human_interrupt_ends_preheat_borrow` | RED |
| D2a.ownerless-branch | `hvac_override.py` | `test_ownerless_compromise_row_ended_by_human` | RED |
| D2a.ownerless-no-timer | `hvac_override.py` | `test_compromise_row_with_timer_only_is_not_ownerless` | RED |
| D2a.ownerless-no-token | `hvac_override.py` | `test_owned_compromise_is_not_ownerless` | RED |
| D2a.ownerless-not-active | `hvac_override.py` | `test_compromise_row_being_applied_is_not_ownerless` | RED |
| D2a.egress-excluded(kind-set) | `hvac_override.py` | `test_egress_row_not_ended_by_human` | RED |
| D2e.latch-add | `hvac_override.py` | `test_interrupt_latch_survives_second_human_change` | RED |
| D2e.latch-discard-manual-exit | `hvac_override.py` | `test_interrupt_latch_discharges_on_manual_exit` | RED |
| D2e.latch-teardown | `hvac_override.py` | `test_interrupt_latch_cleared_by_teardown` | RED |
| D2e.latch-predict-precool | `hvac_predict.py` | `test_interrupt_latch_survives_second_human_change` | RED |
| D2e.latch-predict-preheat | `hvac_predict.py` | `test_interrupt_latch_blocks_preheat` | RED |
| D2e.latch-strict-True | `hvac_predict.py` | `test_interrupt_latch_survives_second_human_change` | RED |
| D2c.in-flight-grace | `hvac_override.py` | `test_d2c_gen_bump_without_redispatch` | RED |
| D2c.in-flight-comp-timer | `hvac_override.py` | `test_compromise_row_with_timer_only_is_not_ownerless` | RED |
| D2c.in-flight-owned-token | `hvac_override.py` | `test_owned_compromise_is_not_ownerless` | RED |
| D2c.in-flight-active | `hvac_override.py` | `test_compromise_row_being_applied_is_not_ownerless` | RED |
| D2c.cancel-timers | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.gen-bump | `hvac_override.py` | `test_d2c_gen_bump_without_redispatch` | RED |
| D2c.release-owned | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.force-borrow-row(H2) | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.force-comp-live(H2) | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.case-B | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.episode-write-normal | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.episode-write-severe | `hvac_override.py` | `test_case_c_plain_within_manual_dispatch_against_resolver` | RED |
| L6.severe-gen-capture | `hvac_override.py` | `test_stale_revert_stands_down` | RED |
| L6.normal-gen-capture | `hvac_override.py` | `test_d2c_gen_bump_without_redispatch` | RED |
| L6.compromise-gen-capture | `hvac_override.py` | `test_fired_compromise_revert_stands_down_on_supersede` | RED |
| L6.apply-start-check | `hvac_override.py` | `test_pending_apply_compromise_stands_down_on_gen_bump` | RED |
| L6.apply-after-begin-check | `hvac_override.py` | `test_apply_compromise_stands_down_when_superseded_during_begin` | RED |
| L6.revert-start-check | `hvac_override.py` | `test_stale_revert_stands_down` | RED |
| L6.revert-before-S4-check | `hvac_override.py` | `test_revert_stands_down_when_superseded_during_mode_write` | RED |
| BASE.caseA-named-pre-preset | `hvac_override.py` | `test_case_a_single_reference_preset` | RED |
| BASE.Q7-pre-arrival | `hvac_override.py` | `test_case_a_pre_arrival_uses_house_target` | RED |
| BASE.human-manual-snapshot | `hvac_override.py` | `test_case_a_human_manual_snapshot_uses_house_target` | RED |
| BASE.changed-high-only | `hvac_override.py` | `test_delta_and_compromise_count_only_changed_legs` | RED |
| BASE.resolver-none-no-dispatch | `hvac_override.py` | `test_case_c_resolver_none_books_no_dispatch` | RED |
| BASE.ref-preset-severe | `hvac_override.py` | `test_case_c_plain_within_manual_dispatch_against_resolver` | RED |
| BASE.ref-preset-normal | `hvac_override.py` | `test_case_a_single_reference_preset` | RED |
| BASE.normal-changed-legs | `hvac_override.py` | `test_delta_and_compromise_count_only_changed_legs` | RED |
| BASE.resolver-wiring | `hvac.py` | `test_coordinator_wires_real_resolver` | RED |
| D2d.token-named-check | `hvac_override.py` | `test_s4_revert_never_pins_manual` | RED |
| D2d.no-named-skip | `hvac_override.py` | `test_s4_revert_no_named_preset_skips` | RED |
| D2f.disable-release | `hvac_override.py` | `test_arrester_disable_releases_compromise_rows` | RED |
| D6.boot-nudge-manual-skip | `hvac_excursion.py` | `test_boot_audit_nudge_manual_snapshot_no_pin` | RED |
| EX.live_token_for | `hvac_excursion.py` | `test_human_interrupt_ends_banking_borrow_bookkeeping_only` | RED |
| EX.returned-property | `hvac_excursion.py` | `test_release_banked_zones_skips_returned_token` | RED |
| D2b.S11-returned | `hvac_predict.py` | `test_release_banked_zones_skips_returned_token` | RED |
| D2b.S13-return-returned | `hvac_predict.py` | `test_return_preheat_skips_returned_token` | RED |
| M1.S12-returned-conjunct | `hvac_predict.py` | `test_m1_returned_token_blocks_s12_write` | RED |
| M1.S12-latch-conjunct | `hvac_predict.py` | `test_m1_latch_blocks_s12_write` | RED |
| M1.S12-mark-committed | `hvac_predict.py` | `test_m1_latch_blocks_s12_write` | RED |
| M1.S13-returned-conjunct | `hvac_predict.py` | `test_m1_returned_token_blocks_s13_write` | RED |
| M1.S13-latch-conjunct | `hvac_predict.py` | `test_m1_latch_blocks_s13_write` | RED |
| D4.no-second-begin | `hvac_predict.py` | `test_pre_arrival_single_write_across_three_triggers[True]` | RED |
| D4.from-baseline-arg | `hvac_predict.py` | `test_pre_arrival_value_from_baseline_not_live` | RED |
| D4.from-baseline-value | `hvac_predict.py` | `test_pre_arrival_value_from_baseline_not_live` | RED |
| D4.baseline-none-skip | `hvac_predict.py` | `test_pre_arrival_baseline_none_no_write` | RED |
| D4.offset-const | `hvac_const.py` | `test_pre_arrival_single_write_across_three_triggers[False]` | RED |
| D4.floor-kept(solar_bank_floor) | `hvac_predict.py` | `test_precool_floor_reads_runtime_solar_bank_floor` | RED |
| D3.site-S12_pre_arrival | `hvac_predict.py` | `test_pre_arrival_single_write_across_three_triggers[False]` | RED |
| D4b.S12-foreign | `hvac_predict.py` | `test_s12_never_writes_over_foreign_row` | RED |
| D4b.S12-same-id | `hvac_predict.py` | `test_s12_stale_own_token_does_not_license_foreign_row` | RED |
| D4b.S12-same-site | `hvac_predict.py` | `test_energy_precool_does_not_write_over_pre_arrival_row` | RED |
| D4b.S13-foreign | `hvac_predict.py` | `test_s13_never_writes_over_foreign_row` | RED |
| D3.full-pass-call | `hvac.py` | `test_pre_arrival_ends_on_hvac_arrival_before_s1` | RED |
| D3.fast-run-call | `hvac.py` | `test_fast_run_ends_only_its_zone` | RED |
| D3.fast-run-expire-filter | `hvac.py` | `test_fast_run_ends_only_its_zone` | RED |
| D3.fast-run-reconcile-filter | `hvac.py` | `test_fast_run_ends_only_its_zone` | RED |
| D3.arrival-hvac-occupancy | `hvac.py` | `test_hallway_lighting_does_not_end_pre_arrival` | RED |
| D3.interrupted-clear | `hvac.py` | `test_interrupted_zone_cleared_and_fans_left_on` | RED |
| D3.timeout-reads-knob | `hvac.py` | `test_pre_arrival_ends_on_timeout_knob[20-1260-True]` | RED |
| D3.zi-off-inactive | `hvac.py` | `test_zi_off_ends_pre_arrival_borrows` | RED |
| D3.max-aged-dropped | `hvac.py` | `test_pre_arrival_max_age_with_repeated_triggers[1800-True]` | RED |
| D3.recon-inactive-release | `hvac_predict.py` | `test_pre_arrival_ends_on_timeout_knob[20-1260-True]` | RED |
| D3.recon-max-age | `hvac_predict.py` | `test_pre_arrival_max_age_with_repeated_triggers[1800-True]` | RED |
| D3.recon-max-age-inclusive | `hvac_predict.py` | `test_pre_arrival_max_age_with_repeated_triggers[1800-True]` | RED |
| D3.recon-zone-filter | `hvac_predict.py` | `test_fast_run_ends_only_its_zone` | RED |
| D3.recon-site-filter | `hvac_predict.py` | `test_reconciliation_ignores_energy_precool_borrows` | RED |
| D3.no-throttle-write | `hvac_predict.py` | `test_pre_arrival_release_does_not_touch_last_emitted_range` | RED |
| D3.trigger-passed | `hvac_predict.py` | `test_pre_arrival_ends_on_hvac_arrival_before_s1` | RED |
| D5.ctor-clamp | `hvac.py` | `test_pre_arrival_window_clamped_in_constructor` | RED |
| D5.clamp-max | `hvac_const.py` | `test_pre_arrival_window_clamp[200-110]` | RED |
| D5.number-live-push | `number.py` | `test_pre_arrival_window_knob_live_and_persisted` | RED |
| D5.form-field | `config_flow.py` | `test_pre_arrival_window_on_hvac_settings_form` | RED |
| D5.suppress-key | `__init__.py` | `test_pre_arrival_window_key_in_reload_suppress_set` | RED |
| D5.apply-in-place | `__init__.py` | `test_apply_in_place_pushes_pre_arrival_window_live` | RED |
| D5.setup-kwarg | `__init__.py` | `test_pre_arrival_window_seeded_from_cm_options_at_boot[saved0-45]` | RED |
| C3.guard | `hvac_zones.py` | `test_continuous_clock_not_reset_while_room_reloading` | RED |
| C3.guard-wraps-whole-else(M4) | `hvac_zones.py` | `test_backfill_still_runs_while_room_reloading` | RED |

### Name-diff
`scripts/suite_namediff.py --isolate` vs `develop` (base trees 2635d35e2 / 32931dc80, identical code) over 133 test files, in 6 foreground chunks: **CLEAN, 0 NEW, 0 GONE** at branch HEAD 432119ba7.


---

## Builder notes — fix-up round 1 (2026-09-29, after reviews A / B / C / D)

Review record: `docs/reviews/code-review/v5.103.23_hvac_w1_w2_finish.md`. Every item below has its own behavioural test and a per-site drill.

| Item | Change | Where |
|---|---|---|
| A-M1 | Max-age pre-arrival end turns the zone's pre-arrival fans off (like the timeout) | `hvac.py` `_async_end_pre_arrival_borrows` |
| A-L1 = B-M1 | `_apply_compromise` re-checks the generation AFTER the S3 await. If superseded, the row closes `human_interrupt`/None, no token is stored and no timer is armed. Stood-down `_apply_compromise` / `_revert_override` pop their OWN timer handle (identity via a per-closure holder) | `hvac_override.py` |
| A-L2 | The startup-audit revert records an episode (original = the audit target) and captures generation + handle | `async_startup_audit` |
| B-L4 | `enabled=False` bumps every zone's generation | `enabled` setter |
| A-L4 = B-L1 (Q7) | `pre_arrival_reference_preset(house_state)`: sleep in sleep/waking, else home. The resolver's `arrival=True` path uses it; the arrester passes `arrival=_is_pa`. Other borrow kinds keep H3 (named pre-borrow preset). The redundant `not _is_pa` conjunct was dropped | `hvac_const.py`, `hvac.py` resolver, `hvac_override.py` case A |
| D-M1 | Latch discharge only when the new state is readable AND the new preset is named and not `manual` | manual-exit block |
| D-M2 | `__interrupt_latch` side-key: saved on set, discharge and in the snapshot; `rehydrate_interrupt_latch` at boot (kept while manual or unreadable, discharged and persisted otherwise). D2e above is corrected | `hvac_override.py`, `hvac.py` |
| D-L1 | S11 skips a person-latched zone (closes its row `human_interrupt`/None, no write). This covers the flip-off, the orphan path at `hvac_predict.py` ~524-544 (it routes through S11) and D3 | `_release_banked_zones` |
| D-L2 | Latched zones are not added to `_pre_conditioning_zones` / `_energy_precool_zones` / `_last_precool_zones` | energy loop, pre-arrival branch |
| D-L3 | A live nudge on a non-nudge borrow: `nudge_win` kept, the nudge not ended and no episode touched, but the underlying borrow is ended `human_interrupt` and the zone latched (orchestrator decision) | D2 block |
| D-L4 | HVAC coordinator disabled → `_async_end_pre_arrival_borrows({}, all_inactive=True)` on each tick. A removed zone and a missing baseline close the row with no write (`s11_zone_removed` / `s11_no_baseline`) instead of `continue` | `_async_decision_cycle`, `_release_banked_zones` |
| D-L5 | `_pre_arrival_spent` (zone → last trigger). Set on a max-age end and on an inactive end (ZI or coordinator off). A trigger inside the window only refreshes it and does not re-add the zone. Discharged by HVAC arrival or a whole window without a trigger | `hvac.py` |
| D-L7 | Master OFF releases pre-arrival borrows with `pre_arrival_inactive`, `update_throttle=False` | `_check_pre_conditioning` |
| A-L6 | C3 comment corrected | `hvac_zones.py` |
| C-F1..F5 | See the review record | tests |

**Not fixed here — B-L3 (pre-existing, needs a card).** A NEW governed episode (`_handle_severe_override` / `_handle_normal_override` call `_cancel_zone_timers`) still cancels a pending AC-reset restore timer (`_reset_timers`). A person's override during a hard reset can therefore leave the zone's restore-to-heat_cool timer cancelled. Suggested card: `HVAC-ARRESTER-EPISODE-CANCELS-AC-RESET-RESTORE-1`.

**Probe P1b (A-L7 = B-L2), read-only, since 09-26:**
- 7 transitions INTO manual with a live non-nudge borrow.
- 5 are URA echoes: they match URA's writes and all fall inside 15 s, so they are dropped before D2.
- 1 is a reconnect (unavailable → manual; the classifier needs both sides `heat_cool`).
- 1 is a person (09-28 23:03:51).
- **False-human = 0.**

**Unknown:** D-L6 was not in the fix-up brief. The orchestrator should confirm its disposition.

### Drill table after fix-up 1 — 142 sites, 142 RED
The build table above is superseded where anchors moved. Tree clean after every drill.

| Site | File | Test that went RED | Result |
|---|---|---|---|
| D1.record-call | `hvac_setpoint.py` | `test_emit_set_temperature_records_before_await` | RED |
| D1.record-after-await | `hvac_setpoint.py` | `test_emit_set_temperature_records_before_await` | RED |
| D1.ring-depth | `hvac_const.py` | `test_recent_writes_depth_bound` | RED |
| D1.cls-old-heat_cool | `hvac_override.py` | `test_classify_mode_change_is_none[off-heat_cool-old0-new0]` | RED |
| D1.cls-new-heat_cool | `hvac_override.py` | `test_classify_mode_change_is_none[heat_cool-off-old1-new1]` | RED |
| D1.cls-numeric-legs | `hvac_override.py` | `test_classify_mode_change_is_none[heat_cool-heat_cool-old3-new3]` | RED |
| D1.cls-tolerance-inclusive | `hvac_override.py` | `test_classify_tolerance_boundary_inclusive[77.5-ura_echo]` | RED |
| D1.cls-changed-legs-only | `hvac_override.py` | `test_classify_only_changed_legs_must_match` | RED |
| D1.within-manual-branch | `hvac_override.py` | `test_within_manual_change_books_override_detected_row` | RED |
| D1.transition-ring-check | `hvac_override.py` | `test_transition_late_ura_echo_does_not_end_borrow` | RED |
| D1.boot-seed-call | `hvac.py` | `test_boot_seed_from_rehydrated_rows` | RED |
| D-L3.nudge-live-still-ends-underlying | `hvac_override.py` | `test_nudge_live_human_change_nudge_win_not_ended` | RED |
| D-L3.nudge-live-no-episode-supersede | `hvac_override.py` | `test_nudge_live_does_not_supersede_arrester_episode` | RED |
| D2a.interrupt-eligible | `hvac_override.py` | `test_transition_late_ura_echo_does_not_end_borrow` | RED |
| D2a.end-call | `hvac_override.py` | `test_human_interrupt_ends_banking_borrow_bookkeeping_only` | RED |
| D2a.force-borrow-row | `hvac_override.py` | `test_human_interrupt_ends_banking_borrow_bookkeeping_only` | RED |
| D2a.kinds-preheat | `hvac_override.py` | `test_human_interrupt_ends_preheat_borrow` | RED |
| D2a.ownerless-branch | `hvac_override.py` | `test_ownerless_compromise_row_ended_by_human` | RED |
| D2a.ownerless-no-timer | `hvac_override.py` | `test_compromise_row_with_timer_only_is_not_ownerless` | RED |
| D2a.ownerless-no-token | `hvac_override.py` | `test_owned_compromise_is_not_ownerless` | RED |
| D2a.ownerless-not-active | `hvac_override.py` | `test_compromise_row_being_applied_is_not_ownerless` | RED |
| D2a.egress-excluded(kind-set) | `hvac_override.py` | `test_egress_row_not_ended_by_human` | RED |
| D2e.latch-add | `hvac_override.py` | `test_interrupt_latch_survives_second_human_change` | RED |
| D2e.latch-discard-manual-exit | `hvac_override.py` | `test_interrupt_latch_discharges_on_manual_exit` | RED |
| D2e.latch-teardown | `hvac_override.py` | `test_interrupt_latch_cleared_by_teardown` | RED |
| D2e.latch-predict-precool | `hvac_predict.py` | `test_interrupt_latch_survives_second_human_change` | RED |
| D2e.latch-predict-preheat | `hvac_predict.py` | `test_interrupt_latch_blocks_preheat` | RED |
| D2e.latch-strict-True | `hvac_predict.py` | `test_interrupt_latch_survives_second_human_change` | RED |
| D2c.in-flight-grace | `hvac_override.py` | `test_d2c_gen_bump_without_redispatch` | RED |
| D2c.in-flight-comp-timer | `hvac_override.py` | `test_compromise_row_with_timer_only_is_not_ownerless` | RED |
| D2c.in-flight-owned-token | `hvac_override.py` | `test_owned_compromise_is_not_ownerless` | RED |
| D2c.in-flight-active | `hvac_override.py` | `test_compromise_row_being_applied_is_not_ownerless` | RED |
| D2c.cancel-timers | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.gen-bump | `hvac_override.py` | `test_d2c_gen_bump_without_redispatch` | RED |
| D2c.release-owned | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.force-borrow-row(H2) | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.force-comp-live(H2) | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.case-B | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.episode-write-normal | `hvac_override.py` | `test_human_change_during_compromise_redispatches` | RED |
| D2c.episode-write-severe | `hvac_override.py` | `test_case_c_plain_within_manual_dispatch_against_resolver` | RED |
| L6.severe-gen-capture | `hvac_override.py` | `test_stale_revert_stands_down` | RED |
| L6.normal-gen-capture | `hvac_override.py` | `test_d2c_gen_bump_without_redispatch` | RED |
| L6.compromise-gen-capture | `hvac_override.py` | `test_fired_compromise_revert_stands_down_on_supersede` | RED |
| L6.apply-start-check | `hvac_override.py` | `test_pending_apply_compromise_stands_down_on_gen_bump` | RED |
| L6.apply-after-begin-check | `hvac_override.py` | `test_apply_compromise_stands_down_when_superseded_during_begin` | RED |
| L6.revert-start-check (re-anchored) | `hvac_override.py` | `test_stale_revert_stands_down` | RED |
| L6.revert-before-S4-check | `hvac_override.py` | `test_revert_stands_down_when_superseded_during_mode_write` | RED |
| BASE.caseA-named-pre-preset | `hvac_override.py` | `test_case_a_single_reference_preset` | RED |
| BASE.Q7-arrival-flag | `hvac_override.py` | `test_empty_house_pre_arrival_interrupt_reverts_home_not_away` | RED |
| BASE.Q7-arrival-resolver | `hvac.py` | `test_empty_house_pre_arrival_interrupt_reverts_home_not_away` | RED |
| BASE.Q7-sleep-states | `hvac_const.py` | `test_pre_arrival_reference_preset_helper[waking-sleep]` | RED |
| BASE.Q7-helper-home | `hvac_const.py` | `test_pre_arrival_reference_preset_helper[home_night-home]` | RED |
| BASE.human-manual-snapshot | `hvac_override.py` | `test_case_a_human_manual_snapshot_uses_house_target` | RED |
| BASE.changed-high-only | `hvac_override.py` | `test_delta_and_compromise_count_only_changed_legs` | RED |
| BASE.resolver-none-no-dispatch | `hvac_override.py` | `test_case_c_resolver_none_books_no_dispatch` | RED |
| BASE.ref-preset-severe | `hvac_override.py` | `test_case_c_plain_within_manual_dispatch_against_resolver` | RED |
| BASE.ref-preset-normal | `hvac_override.py` | `test_case_a_single_reference_preset` | RED |
| BASE.normal-changed-legs | `hvac_override.py` | `test_delta_and_compromise_count_only_changed_legs` | RED |
| BASE.resolver-wiring | `hvac.py` | `test_coordinator_wires_real_resolver` | RED |
| D2d.token-named-check | `hvac_override.py` | `test_s4_revert_never_pins_manual` | RED |
| D2d.no-named-skip | `hvac_override.py` | `test_s4_revert_no_named_preset_skips` | RED |
| D2f.disable-release | `hvac_override.py` | `test_arrester_disable_releases_compromise_rows` | RED |
| D6.boot-nudge-manual-skip | `hvac_excursion.py` | `test_boot_audit_nudge_manual_snapshot_no_pin` | RED |
| EX.live_token_for | `hvac_excursion.py` | `test_human_interrupt_ends_banking_borrow_bookkeeping_only` | RED |
| EX.returned-property | `hvac_excursion.py` | `test_release_banked_zones_skips_returned_token` | RED |
| D2b.S11-returned | `hvac_predict.py` | `test_release_banked_zones_skips_returned_token` | RED |
| D2b.S13-return-returned | `hvac_predict.py` | `test_return_preheat_skips_returned_token` | RED |
| M1.S12-returned-conjunct | `hvac_predict.py` | `test_m1_returned_token_blocks_s12_write` | RED |
| M1.S12-latch-conjunct | `hvac_predict.py` | `test_m1_latch_blocks_s12_write` | RED |
| M1.S12-mark-committed | `hvac_predict.py` | `test_m1_latch_blocks_s12_write` | RED |
| M1.S13-returned-conjunct | `hvac_predict.py` | `test_m1_returned_token_blocks_s13_write` | RED |
| M1.S13-latch-conjunct | `hvac_predict.py` | `test_m1_latch_blocks_s13_write` | RED |
| D4.no-second-begin | `hvac_predict.py` | `test_pre_arrival_single_write_across_three_triggers[True]` | RED |
| D4.from-baseline-arg | `hvac_predict.py` | `test_pre_arrival_value_from_baseline_not_live` | RED |
| D4.from-baseline-value | `hvac_predict.py` | `test_pre_arrival_value_from_baseline_not_live` | RED |
| D4.baseline-none-skip | `hvac_predict.py` | `test_pre_arrival_baseline_none_no_write` | RED |
| D4.offset-const | `hvac_const.py` | `test_pre_arrival_single_write_across_three_triggers[False]` | RED |
| D4.floor-kept(solar_bank_floor) | `hvac_predict.py` | `test_precool_floor_reads_runtime_solar_bank_floor` | RED |
| D3.site-S12_pre_arrival | `hvac_predict.py` | `test_pre_arrival_single_write_across_three_triggers[False]` | RED |
| D4b.S12-foreign | `hvac_predict.py` | `test_s12_never_writes_over_foreign_row` | RED |
| D4b.S12-same-id | `hvac_predict.py` | `test_s12_stale_own_token_does_not_license_foreign_row` | RED |
| D4b.S12-same-site | `hvac_predict.py` | `test_energy_precool_does_not_write_over_pre_arrival_row` | RED |
| D4b.S13-foreign | `hvac_predict.py` | `test_s13_never_writes_over_foreign_row` | RED |
| D3.full-pass-call | `hvac.py` | `test_pre_arrival_ends_on_hvac_arrival_before_s1` | RED |
| D3.fast-run-call | `hvac.py` | `test_fast_run_ends_only_its_zone` | RED |
| D3.fast-run-expire-filter | `hvac.py` | `test_fast_run_ends_only_its_zone` | RED |
| D3.fast-run-reconcile-filter | `hvac.py` | `test_fast_run_ends_only_its_zone` | RED |
| D3.arrival-hvac-occupancy | `hvac.py` | `test_hallway_lighting_does_not_end_pre_arrival` | RED |
| D3.interrupted-clear | `hvac.py` | `test_interrupted_zone_cleared_and_fans_left_on` | RED |
| D3.timeout-reads-knob | `hvac.py` | `test_pre_arrival_ends_on_timeout_knob[20-1260-True]` | RED |
| D3.zi-off-inactive | `hvac.py` | `test_zi_off_ends_pre_arrival_borrows` | RED |
| D3.max-aged-dropped | `hvac.py` | `test_pre_arrival_max_age_with_repeated_triggers[1800-True]` | RED |
| D3.recon-inactive-release | `hvac_predict.py` | `test_pre_arrival_ends_on_timeout_knob[20-1260-True]` | RED |
| D3.recon-max-age | `hvac_predict.py` | `test_pre_arrival_max_age_with_repeated_triggers[1800-True]` | RED |
| D3.recon-max-age-inclusive | `hvac_predict.py` | `test_pre_arrival_max_age_with_repeated_triggers[1800-True]` | RED |
| D3.recon-zone-filter | `hvac_predict.py` | `test_fast_run_ends_only_its_zone` | RED |
| D3.recon-site-filter | `hvac_predict.py` | `test_reconciliation_ignores_energy_precool_borrows` | RED |
| D3.no-throttle-write | `hvac_predict.py` | `test_pre_arrival_release_does_not_touch_last_emitted_range` | RED |
| D3.trigger-passed | `hvac_predict.py` | `test_pre_arrival_ends_on_hvac_arrival_before_s1` | RED |
| D5.ctor-clamp | `hvac.py` | `test_pre_arrival_window_clamped_in_constructor` | RED |
| D5.clamp-max | `hvac_const.py` | `test_pre_arrival_window_clamp[200-110]` | RED |
| D5.number-live-push | `number.py` | `test_pre_arrival_window_knob_live_and_persisted` | RED |
| D5.form-field | `config_flow.py` | `test_pre_arrival_window_on_hvac_settings_form` | RED |
| D5.suppress-key | `__init__.py` | `test_pre_arrival_window_key_in_reload_suppress_set` | RED |
| D5.apply-in-place | `__init__.py` | `test_apply_in_place_pushes_pre_arrival_window_live` | RED |
| D5.setup-kwarg | `__init__.py` | `test_pre_arrival_window_seeded_from_cm_options_at_boot[saved0-45]` | RED |
| C3.guard | `hvac_zones.py` | `test_continuous_clock_not_reset_while_room_reloading` | RED |
| C3.guard-wraps-whole-else(M4) | `hvac_zones.py` | `test_backfill_still_runs_while_room_reloading` | RED |
| A-M1.max-age-fans-off | `hvac.py` | `test_max_age_end_turns_pre_arrival_fans_off` | RED |
| A-L1.post-emit-gen-check | `hvac_override.py` | `test_compromise_superseded_during_s3_write_arms_no_timer` | RED |
| A-L1.no-timer-after-supersede | `hvac_override.py` | `test_compromise_superseded_during_s3_write_arms_no_timer` | RED |
| B-M1.revert-pops-own-timer | `hvac_override.py` | `test_stale_revert_pops_its_own_timer_entry` | RED |
| B-M1.apply-pops-own-timer | `hvac_override.py` | `test_stale_apply_pops_its_own_grace_entry` | RED |
| B-M1.identity-check | `hvac_override.py` | `test_stale_revert_stands_down` | RED |
| B-M1.severe-handle-capture | `hvac_override.py` | `test_stale_revert_pops_its_own_timer_entry` | RED |
| B-M1.normal-handle-capture | `hvac_override.py` | `test_stale_apply_pops_its_own_grace_entry` | RED |
| A-L2.startup-gen | `hvac_override.py` | `test_startup_audit_revert_stands_down_on_supersede` | RED |
| A-L2.startup-episode | `hvac_override.py` | `test_startup_audit_revert_stands_down_on_supersede` | RED |
| B-L4.disable-bumps-gen | `hvac_override.py` | `test_disable_bumps_generation_so_queued_compromise_stands_down` | RED |
| D-M1.readable-state | `hvac_override.py` | `test_latch_kept_when_unavailable_state_carries_old_preset` | RED |
| D-M1.named-preset | `hvac_override.py` | `test_latch_kept_when_preset_empty` | RED |
| D-M2.persist-on-set | `hvac_override.py` | `test_latch_persisted_on_set_and_discharge` | RED |
| D-M2.persist-on-discharge | `hvac_override.py` | `test_latch_persisted_on_set_and_discharge` | RED |
| D-M2.snapshot-key | `hvac.py` | `test_latch_in_shutdown_snapshot` | RED |
| D-M2.rehydrate-call | `hvac.py` | `test_restart_mid_interrupt_no_s12_or_s13_begin` | RED |
| D-M2.restore-discharge-non-manual | `hvac_override.py` | `test_latch_restore_discharged_when_zone_left_manual` | RED |
| D-M2.restore-keep-unreadable | `hvac_override.py` | `test_latch_restore_kept_while_zone_unreadable` | RED |
| D-M2.restore-persist-shorter | `hvac_override.py` | `test_latch_restore_discharged_when_zone_left_manual` | RED |
| D-L1.s11-skip-latched | `hvac_predict.py` | `test_s11_skips_person_latched_zone` | RED |
| D-L2.energy-set-membership | `hvac_predict.py` | `test_latched_zone_not_tracked_as_precool_zone` | RED |
| D-L2.pre-arrival-set-membership | `hvac_predict.py` | `test_latched_zone_not_tracked_in_pre_arrival_branch` | RED |
| D-L4.disabled-path-call | `hvac.py` | `test_hvac_disabled_ends_pre_arrival_borrow_inactive` | RED |
| D-L4.zone-removed-close | `hvac_predict.py` | `test_zone_removed_mid_borrow_returns_token` | RED |
| D-L4.no-baseline-close | `hvac_predict.py` | `test_release_without_baseline_returns_token` | RED |
| D-L5.trigger-gate | `hvac.py` | `test_max_age_then_repeat_trigger_does_not_rebegin` | RED |
| D-L5.trigger-gate-window | `hvac.py` | `test_spent_episode_ends_after_a_window_of_silence` | RED |
| D-L5.spent-on-max-age | `hvac.py` | `test_max_age_then_repeat_trigger_does_not_rebegin` | RED |
| D-L5.spent-on-inactive | `hvac.py` | `test_zi_off_on_within_window_does_not_rebegin` | RED |
| D-L5.prune-on-arrival | `hvac.py` | `test_spent_episode_ends_on_arrival` | RED |
| D-L5.prune-after-window | `hvac.py` | `test_spent_episode_pruned_after_a_window_without_trigger` | RED |
| D-L7.master-off-split | `hvac_predict.py` | `test_master_off_ends_pre_arrival_with_inactive_trigger` | RED |
| F2.refresh-before-s1 | `hvac.py` | `test_pre_arrival_release_refreshes_zone_preset_before_s1` | RED |
