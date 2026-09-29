# PLANNING — HVAC W1/W2 finish

**Cards:**
- Part A: `ARRESTER-BOOT-BLIND-1` gap (2), revived 2026-09-28. Operator ruling: "The person interrupts. We end and revert. Closest to my intent."
- Part B: `HVAC-PRE-ARRIVAL-BORROW-LIFETIME-1`, approved.
- Part C: `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1` (W2-2). Parked 2026-09-27; the operator green-lit it on 2026-09-28 to finish W2.

**Author:** ura-planner, 2026-09-28. Snapshot: `develop` @`37b678966` (v5.103.21). v5.103.20 is built but not deployed.
**Status:** PLAN ONLY. Each part is gated by the §2 probe. A plan review is required before build (Tier 2 plan-review rule).
**Tier:** Tier 2-DB. Three framing-disjoint reviews, live validation, then the README write-back. §12 explains why and asks whether to elevate Part A.

Each part is a separate deliverable group with its own falsifiable invariant, so each reviewer can cover the whole plan along one axis.

---

## 0. Institutional context verified

**State of play read completely.** I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, all 472 lines: §1–§12, §9e (the four S1 gates and rulings D13/D48/D49/D50/D52) and the §10 ledger C1–C25. This plan does not re-assert any §10 claim. It respects:
- C13: `return_excursion` writes nothing; each return site does its own writes.
- C17/C23: suppression is 15 s for temperature writes and 120 s for preset writes.
- C24: HVAC occupancy rides lighting occupancy plus a tail.
- C25: the old S1 "don't fight manual" guard is superseded.

**Stale citations in the state-of-play doc.** The code wins. Fix these in the commit that lands this plan:

| Doc says | Code today (`develop`) |
|---|---|
| §9e: HIGH-1 skip at `hvac_excursion.py:629-650` | `hvac_excursion.py:644-666` (`_auto_return`) |
| §3.2 / §9.4: D5 coast defer at `hvac.py:2271-2289` | `hvac.py:2882-2962` |
| §3.2: D6 at `hvac.py:2063`; §9.4: Source-4 at `presence.py:2148-2157` | D6 entry is `hvac.py:2676-2685`. Source 1 is `presence.py:2100-2122`; Source 4 is `:2147-2159` |
| §3.2 / §9.4: `continuous_occupied_since` at `hvac_zones.py:746-754` | `hvac_zones.py:964-972` |
| Card: pre-cool offset at `hvac_predict.py:1134` | `hvac_predict.py:1135` |
| §4.2: S12 at `hvac_predict.py:1160` | begin `:1154`, write `:1193` |

**Re-verified card facts.** All were checked against source:
- The arrester books an override only on a transition INTO manual, `hvac_override.py:3218`. A setpoint change while already manual matches neither branch (`:3220-3226`) and returns silently. Confirmed.
- S12 begins a BANKING borrow with `duration_s=None` (`hvac_predict.py:1154-1164`). Its `stale_ts` then falls to `EXCURSION_LEASE_MAX_S = 7200` (`hvac_excursion.py:79`, `:146-148`). The lease-expiry sweep (`:733-778`) is the only thing that ends it. Confirmed.
- `_expire_pre_arrival_zones` (`hvac.py:5857-5887`) clears the zone set when the zone is occupied (lighting `any_room_occupied`, `:5868`) or on `PRE_ARRIVAL_TIMEOUT_MINUTES = 30` (`hvac_const.py:465`). It never touches the borrow. Confirmed.
- The ratchet is real. The pre-arrival loop calls `_execute_zone_pre_cool(zone, offset=-2.0, …)` on every pass while the zone is in the set (`hvac_predict.py:645-649`), and the offset is applied to the LIVE `zone.target_temp_high` (`:1135`). Confirmed.
- **NEW finding (widens D4).** On the 2nd and later passes, `begin_excursion` REJECTS because a row already exists and returns `None` (`hvac_excursion.py:805-813`). The CM is a no-op for `None` (`:1321-1322`), and the S12 write still goes out (`hvac_predict.py:1193-1205`). So S12 writes over ANY live row on the zone, including a foreign nudge, compromise or pre-heat row. Only egress is guarded (`:1127-1131`).
- A live row arms gate (e) (`hvac_preset.py:302-317`). The vacancy bypass then defers with `vacancy_bypass_deferred:active_borrow` (`hvac.py:3229-3236`). Confirmed.

**NEW latent defect found on the D2 path.** `_revert_override` restores `_cmp_token.pre_preset` whenever that value is truthy (`hvac_override.py:3938-3942`). A compromise always begins while the zone is already `manual`, because the human's change put it there. So the snapshot is `"manual"`, and S4 pins `manual`, which is a no-op revert. Today S1's §9e reclaim hides this on the next pass. The only test seeds `pre_preset="home"` (`quality/tests/test_hvac_excursion_compromise_migration.py:185`), so this path has never been exercised. The §2 probe P5 measures it.

### Greps run
`begin_excursion(|return_excursion(|_compromise_release_lease(|site="S[0-9]`, `_pre_arrival_zones|PRE_ARRIVAL_TIMEOUT_MINUTES`, `_last_emitted_range[`, `last_sent|values_after|_last_write`, `last_detection_for`, `override_count_today`, `caller_site`, `S12_pre_cool`, `set_on_.*|_on_sunset_notify`, `vacancy_bypass_deferred|manual_guard_verdict`, `any_room_occupied|is_zone_transient_blocked` (arrester), `continuous_occupied_since =`, `CONF_HVAC_PRE_ARRIVAL|pre_arrival` (const, number, switch, config_flow), plus Number-name prefixes.

### Prior plans consulted
- `PLANNING_hvac_w1b_thermostat_definition.md`, full read of the rulings, §2 non-goals and §5.P1. Its non-goals "no changes inside `emit_*` funnels" and "no changes to borrow code beyond accessors" were scoped to W1-B. §5 D1 and Q1 surface where this plan needs one read-only exception.
- `PLANNING_hvac_governed_excursion.md`, row table and rev-6 banner. Row 11 already required the S12 snapshot to come from `_resolve_baseline_range` "to sidestep the ratchet". `:753` explicitly left the ratchet itself unscoped. This plan closes it for pre-arrival.
- `PLANNING_hvac_fast_occupancy_response.md` REV 7. Pre-arrival zones bypass the D5 transit filter (`_zone_away_edge`, `hvac.py:4316`). Expiry also runs in fast runs (`hvac.py:4780`).
- `PLANNING_hvac_enable_custom_preset_ranges.md` §consumer table. It lists "Pre-cool / banking (reads live high; known ratchet)" as a trust reader.
- `PLANNING_hvac_reloading_room_placeholder_readers.md`, full read. Part C reuses its design. Its §5a D0 result (2026-09-27): 0 reloading-room samples, 0 boot resets. Verdict: PARK.
- `PLANNING_hvac_w2_night_sleeper_and_placeholder_readers.md` Piece B. Superseded by the dedicated plan above.
- `PLANNING_hvac_arrester_nudge_echo.md` (by name and the §10 C23 summary). It raised the 5→15 s window. Its residual is late echoes past 15 s, which Part A's value match covers.

### Memory bodies pulled
- `project_reload_storm_refuted_restart_storm_live`: restarts, not reloads, are the live trigger. This bears on Part C's value case.
- `feedback_suppression_needs_discharge`: every latch in this plan names its discharge, backstop and restart behaviour.
- Index lines: `reference_hvac_state_of_play`, `feedback_extend_existing_never_rebuild`, `feedback_marginal_benefit_pushback`, `feedback_wire_in_anchor_mandatory`, `feedback_hollow_test_anchors`.

### Code read for scope
- `hvac_override.py`: `:2628-2676`, `:2690-2722`, `:2973-3008`, `:3094-3560`, `:3569-4015`, `:6490-6530`.
- `hvac_excursion.py`: `:60-230`, `:540-1370`.
- `hvac_predict.py`: `:400-690`, `:860-1226`, `:1409-1627`.
- `hvac_egress.py`: `:425-454`, `:635-905`.
- `hvac.py`: `:1048-1068`, `:2120-2230`, `:2380-2560`, `:2560-2620`, `:2640-2975`, `:3200-3340`, `:3385-3435`, `:3900-3985`, `:4290-4340`, `:4760-4800`, `:5797-5888`, `:6011-6045`.
- `hvac_preset.py`: `:225-376`. `hvac_strategy.py`: full. `hvac_setpoint.py`: `:100-485`.
- `hvac_zones.py`: `:950-980`, `:2347-2371`. `presence.py`: `:2100-2161`.
- `number.py`: `:505-590`. `switch.py`: `:4232-4261`.

### REUSE-or-BUILD per piece

| Piece | Verdict | Symbol (file:line) |
|---|---|---|
| Suppression / echo windows for D1 | REUSE, no new window | `_is_genuine_manual` `hvac_override.py:2628-2676`; for a within-manual change it returns False in-window (`:2666-2667`) |
| Reconnect / cloud-flap guard | REUSE | `hvac_override.py:3145-3191` |
| Setpoint match tolerance | REUSE | `LAST_SENT_TOLERANCE_F = 0.5` `hvac_strategy.py:53` |
| Record of URA's recent setpoint writes (in RAM) | NEW, small | Nothing equivalent exists. Strategy `last_sent` records only S1 preset holds (`hvac_strategy.py:141-149`, `:216`). The W1-A `climate_write` row is DB-only and fire-and-forget (`hvac_setpoint.py:163-255`), and there is no DB read on the decision path (N4). See §5 D1 and Q1 |
| Manual-episode boundary for the latch | REUSE | `_last_detection` is popped on leaving manual (`hvac_override.py:3109-3115`); accessor `last_detection_for` (`:3561-3567`) |
| Borrow end (bookkeeping, no wire) | REUSE | `return_excursion(..., restore_ok=None)` (`hvac_excursion.py:879`); precedent `force_reset` (`hvac_override.py:6517-6525`) |
| Registry reads | REUSE + one pure accessor | `is_borrow_active` / `excursion_id_for` (`:570-594`); NEW `live_token_for(zone_id)` pure read (same shape) |
| Cancelling the arrester's own timers | REUSE | the cancel loop in `_defer_arrester_to_borrow` (`hvac_override.py:3528-3533`), NOT `_cancel_zone_timers`, which also kills `_reset_timers` |
| HUMAN_MANUAL snapshot classifier | REUSE | `strategy_for(...).is_human_manual_snapshot` (`hvac_strategy.py:155-168`, `:231-235`) |
| Baseline preset and setpoints for a revert | REUSE the arithmetic | startup-audit shape (`hvac_override.py:2222-2229`); the arrester gets it through a NEW callback setter mirroring `set_on_sunset_notify` (`:1130-1137`) |
| Pre-arrival end writer (presets-only return) | REUSE + extend | `_release_banked_zones` (`hvac_predict.py:922-1099`). Adds a `trigger` param, an `update_throttle` param and a returned-token guard |
| No-ratchet baseline | REUSE | `_resolve_baseline_range` (`hvac_predict.py:864-920`) |
| Arrival signal | REUSE | `any_room_hvac_occupied`, with the defensive fallback pattern of `hvac_predict.py:583-586` |
| Pre-arrival window knob | NEW Number, REUSE the pattern | `ReturnWindowMinutesNumber` (`number.py:511-587`, Bug Class #32 options writeback) |
| Part C predicates | REUSE (unchanged from the parked plan) | `_zone_conditioning_retreat_ok` (`hvac.py:5679`); `is_zone_transient_blocked` (`hvac_zones.py:2347`); the local `_transient_blocked_row1` (`hvac.py:2567-2575`); `HVAC_LIVE_ROOM_TRANSIENT_GRACE_S = 300` (`hvac_const.py:1029`) |
| Probe | NEW read-only script (Parts A/B); REUSE `scripts/probes/hvac_reloading_room_probe.py` (Part C) | — |

---

## 1. Decisions this plan makes (reviewers: check these first)

| # | Question | Decision | Why |
|---|---|---|---|
| P1 | Which borrows does a human interrupt end? | **BANKING (pre-arrival and energy pre-cool), PREHEAT and COMPROMISE.** NUDGE is excluded (D13 unchanged). EGRESS_PAUSE is excluded (Q2) | Egress writes only `hvac_mode=off` for an open door (`hvac_egress.py:721-730`). A setpoint change does not conflict with the pause, and ending the bookkeeping would leave `_paused_by_egress` (the real owner state) inconsistent: S1 would keep skipping the zone while the row is gone. Egress already ignores comfort grace on purpose (`:717-719`) |
| P2 | Compromise | **END and RE-DISPATCH.** A human change during the arrester's own grace or compromise cancels those timers, returns the compromise row (`human_interrupt`, `restore_ok=None`), and re-runs the ordinary delta rules for the new value against the episode's ORIGINAL baseline and preset | A compromise is the arrester's answer to an earlier human value. After a newer change, that answer is stale (halfway to an outdated request). Re-dispatching against the original baseline is exactly "the arrester treats it as an ordinary human override". The revert target never drifts because the baseline is the pre-episode one. Unbounded re-grace needs a human action each time. D50 is unchanged: an immune person still wins |
| P3 | Delta basis for a within-manual change | Compare against the **baseline** (§5 D2 table), counting **only the legs the human changed**. Not against the old value | The old value is URA's borrow value. Comparing against it would make the compromise "halfway between the pre-cool and the human" and then revert to a preset: incoherent. The changed-legs rule stops the S12 snapshot's synthetic low (`cool − 7`, `hvac_predict.py:918`) from inventing a heat-leg delta |
| P4 | Arrival signal for the pre-arrival end | **`any_room_hvac_occupied`** (hallway-excluded), with the lighting value as fallback. Lighting is what `hvac.py:5868` reads today | With the lighting signal, a hallway crossing (zone_2 contains the up hallway) would end the pre-cool before the person reaches their room. Pre-arrival zones already bypass the D5 transit filter (`hvac.py:4316`), so the room arms on its first evidence |
| P5 | What the pre-arrival end writes | **Presets-only return of the snapshot preset** (the S11 path), run **before** S1 in the same pass, followed by a zone state refresh so S1 decides at once | This is the established borrow contract: each return restores its own snapshot (W1-B D2.4). A bookkeeping-only end that relies on S1 leaves a strand when gate (d) (arrester passive) or (a/b) refuses. Running before S1 means an `away`→`home` arrival costs two back-to-back pins with no comfort gap |
| P6 | Stop URA re-starting over the human | A **latch**: no S12 or S13 begin on a zone whose current manual episode has a `human_interrupt` detection. It clears when the zone leaves manual. The interrupted pre-arrival episode also ends (the zone leaves the set) | Without the latch, the next pass (≤5 min) begins a new pre-cool over the human and the interrupt is meaningless. This narrows D48 only after an interrupt (Q3) |

---

## 2. Measure first — one read-only probe, gating all three parts

NEW script: `scripts/probes/hvac_borrow_end_probe.py`. It follows the access pattern of `hvac_reloading_room_probe.py`: recorder opened with `mode=ro`, URA DB read-only. Run with `ssh ha "python3 - --days 14" < scripts/probes/hvac_borrow_end_probe.py`. The orchestrator runs it; the builder does not.

| Id | Question | Go / no-go use |
|---|---|---|
| P1 | For the 3 zones, find every recorder state change where `preset_mode` is `manual` on both sides and a setpoint changed. For each, is there a URA `climate_write` `set_temperature` in the 4 writes before it on that entity whose `values_after` matches the new values within 0.5 °F? Split into matched (URA echo), unmatched-with-a-borrow-live and unmatched-no-borrow. Report echo lag for matched rows | **D1 gate.** The 2026-09-28 22:15:40 zone_2 event (71, no URA write) must come out unmatched. If any KNOWN URA echo (inside an `ac_ramp_events` nudge window or a borrow window) is unmatched with ring depth 4, raise the depth, or stop and report. **Hand-build the fixture:** commit the 09-28 22:03-22:16 zone_2 sequence as `quality/tests/fixtures/hvac_09_28_zone2_prearrival.json` |
| P2 | Every `hvac_excursion_events` row with `site='S12_pre_cool'` over 14 d: duration, trigger, and the count of `climate_write` rows sharing its `excursion_id` plus the S12 writes with a NULL `excursion_id` in the same window | Sizes the ratchet and the lifetime problem. Expect `lease_expiry` at about 7200 s and more than one write per borrow |
| P3 | Minutes between pre-arrival (`ura_activity_log` `pre_arrival`) and the zone's first HVAC-occupied sample; share of events that reach 30 min without arrival | Chooses the D5 default (30 stays unless the median arrival is well past it) |
| P4 | Live seasonal setpoints the baseline resolver returns now, per house state (URA config), next to the Bryant profile values seen on the entity when the zone sits in a named preset | Checks the P3/D2 baseline. If they disagree by ≥ 1 °F, use the token snapshot (the §5 D2 table already prefers it for case A) and say so in the README |
| P5 | `climate_write` rows with `site='S4_revert'` and `values_after.preset_mode='manual'` | Confirms the §0 latent defect (D2d) |
| P6 (Part C) | Re-run `hvac_reloading_room_probe.py` P1/P3 over the span since v5.103.15 | Refreshes the evidence. The operator's green light stands whatever the result, but the README must quote it |

---

## PART A — A human change ends a non-nudge borrow (ARRESTER-BOOT-BLIND-1 gap 2)

### A.0 Producer / consumer

**Producer: "human within-manual change".**
- Inputs:
  - The HA `state_changed` event on the climate entity, read by `_handle_climate_change`.
  - The status feed's `preset_mode`, `target_temp_high` and `target_temp_low`. §5 of the state of play: status setpoints can be stale and then jump when a full poll lands. ha_carrier's 5-min post-write guard can re-post URA's own values into HA's local copy (C16/C21).
  - The NEW recent-writes record.
- Health: the status feed is a known-lagging, known-stale source. That is why a match against a timing window alone is not enough, and why the record keeps the last K writes rather than only the last one.
- Failure direction: an unmatched URA echo would be read as a human, and URA would end its own borrow and revert. That is the harmful direction; P1 measures it. A human value that happens to equal a recent URA value is missed, which is today's behaviour and the safe direction.

**Consumers of the new detection:**

| Consumer | file:line | Kind | Effect |
|---|---|---|---|
| `override_detected` ledger row (gains keys) | `hvac_override.py:3366-3388` | Durable, display | Tier 2-DB trigger: the payload changes |
| `_last_detection`, read by S1's `_classify_manual_episode` (`manual_class`) | `hvac_override.py:3363`; `hvac.py:3398-3406` | Ledger label on S1's `preset_change` row | `manual_class` now also sees within-manual bookings |
| `zone.override_count_today` | `hvac_override.py:3396/3432/3444/3459` | Trust (optimizer advisory at ≥ 10/day, `optimization.py:2471-2508`); display (comfort penalty, `sensor.py:1596`) | More human changes are counted. A misread echo would inflate it, which P1 guards |
| Borrow end (D2) | new | Trust | Ends BANKING, PREHEAT or COMPROMISE |
| Predictor latch (D2e) | new, reads `last_detection_for` | Trust | Blocks S12/S13 begins |
| Governed severity dispatch | `hvac_override.py:3466-3496` | Trust (writes S3/S4) | Uses the §5 D2 baseline |

### A.1 Falsifiable invariant

> **INV-A.** Suppose a change on zone Z's thermostat at time t is classified HUMAN by D1: outside the suppression windows, and not matching any of URA's last K setpoint writes to that entity. Suppose also that a BANKING, PREHEAT or COMPROMISE borrow B is live on Z at t. Then, until Z next leaves `manual`:
> 1. no `climate_write` row for Z's entity carries `excursion_id = B.id` with `ts_issued > t`;
> 2. no `climate_write` row for Z has `site ∈ {S12_pre_cool, S13_pre_heat}`;
> 3. the only URA setpoint or preset writes to Z are the arrester's S3 compromise or S4 revert (tagged with the NEW episode), or S1 under the §9e gates;
> 4. B's `hvac_excursion_events` row has `trigger='human_interrupt'` and `restore_ok` NULL.
>
> **INV-A4 (D13 held).** If a NUDGE is live on Z at t (`_nudge_in_flight` or `_nudge_restore_timers`), the change is booked `gated_reason='nudge_win'`, the nudge is not ended, and no arrester timer is created.
>
> **INV-A5 (no self-interrupt).** Every URA `set_temperature` echo that arrives outside suppression but matches one of the last K URA writes is never booked as HUMAN.

How to falsify live: join `climate_write` × `hvac_excursion_events` × `override_detected` (`details.within_manual`) per zone for 14 d after deploy.

### D1: Detect a human within-manual change

**Where.** `hvac_override.py:3216-3226`, inside `_handle_climate_change`. It runs after the reconnect guard (`:3145-3191`) and after `_is_genuine_manual` (`:3198`), so the existing 15 s / 120 s windows are REUSED and no new window is added.

**Rule.** Put it in a pure function, `classify_manual_setpoint_change(old_attrs, new_attrs, recent, tol) -> "none" | "ura_echo" | "human"`, so it can be tested on its own:
1. The change is within-manual only if `old.preset_mode == new.preset_mode == "manual"`.
2. `changed_legs` = the `target_temp_high` / `target_temp_low` legs whose value differs, None-safe. If there are none → `"none"`.
3. If ANY entry in `recent` matches the new value on every changed leg within `tol`, inclusive → `"ura_echo"`. A leg missing from an entry counts as a match.
4. Otherwise → `"human"`.

`"human"` sets `is_override = True` with `within_manual=True`. `"ura_echo"` returns silently, as today, plus one DEBUG line. The transition-into-manual branch (`:3218`) is unchanged.

**The recent-writes record (NEW, RAM only).** A module-level map in `hvac_setpoint.py`: `entity_id → deque[(low, high, monotonic_ts)]` with `maxlen = ARRESTER_URA_WRITE_RING_DEPTH`. It is appended inside `emit_set_temperature` right after `service_data` is built (post-guard values, `:427-431`) and BEFORE the wire await. Recording the intent, including failed calls, errs toward "URA". Read it through a pure accessor, `recent_ura_setpoints(entity_id)`.
- Nothing else in the funnel changes: no gate, no transform, no wire difference.
- The AST completeness lint (`test_hvac_climate_write_funnel_completeness.py`) already guarantees that every URA `set_temperature` passes through here. So the record is complete by construction, where suppressing per site would need N callers.
- **This is the one exception to the W1-B non-goal "no changes inside `emit_*` funnels" (Q1).**

**Boot seeding.** Right after `async_startup_excursion_audit` (`hvac.py:1432`), seed the record from every rehydrated row's `excursion_target_low/high` (pure read of `hvac_excursion._rows`). This stops a post-restart poll of a live PREHEAT or COMPROMISE value from being read as human. Rows that are not rehydrated are either released at boot with a preset pin (NUDGE, BANKING) or dropped.

**Ledger.** The one `override_detected` row gains `details.within_manual` (bool), `details.changed_legs` (list) and `details.ura_write_match` (always False on a booked row). The in-memory `_last_detection` record gains `within_manual`.

#### Acceptance criteria
- **Verify:** on the committed 09-28 fixture, the classifier returns `ura_echo` for the replayed 78, 76 and 74 echoes and `human` for 71.
- **Verify:** within-manual changes inside a 15 s temp or 120 s preset window are not booked. They go through the REUSED `_is_genuine_manual` path.
- **Test:** `test_classify_within_manual_human_vs_echo_fixture_09_28`. Oracle values are typed by hand from the P1 rows, not derived from the code.
- **Test:** `test_within_manual_change_books_override_detected_row` drives the real `_handle_climate_change` with a manual→manual event and asserts one row with `within_manual=True`. **Mutation:** restore the `:3218` two-branch test and this must go red.
- **Test:** `test_emit_set_temperature_records_recent_write_before_await` makes the service call raise and asserts the entry still exists. **Mutation:** move the append after the await and this must go red.
- **Test:** `test_recent_writes_ring_depth_bound` (depth 4, oldest evicted).
- **Test:** `test_boot_seed_from_rehydrated_rows`.
- **Test:** `test_reconnect_within_manual_ignored` (the REUSED guard still wins).
- **Live:** during a live zone_1 nudge (about one every 25 min), the operator changes the setpoint by 2 °F in the Carrier app. Expect one `override_detected` with `within_manual=true` and `gated_reason='nudge_win'`, no arrester timer, and the nudge restores on schedule (INV-A4). **Discriminates:** before the fix there is no row at all; if the nudge were wrongly ended there would be an `ac_ramp_events` restore before `nudge_duration`.
- **Live:** 7 d after deploy, `override_detected` rows with `within_manual=true` whose values match a URA `climate_write` of the same entity within the prior 4 writes = **0** (INV-A5). One `sqlite3` query.

### D2: Apply the ruling — end, then take the ordinary path

**D2a — End.** In `_handle_climate_change`, after `is_override` and after the `_nudge_live` check (`:3307-3310`, still first):
- Let `T = live_token_for(zone_id)`.
- If `T.kind ∈ {BANKING, PREHEAT}`, schedule `return_excursion(T, trigger="human_interrupt", restore_ok=None, trigger_detail=f"human_change:{old_high}->{new_high}")`. This is bookkeeping only; nothing is written to the thermostat.
- Set `_detect_rec["human_interrupt"]=True` and `interrupted_excursion_id=T.excursion_id`, and treat `_borrow_row` as False for the rest of the precedence.
- Scheduling the return (rather than awaiting it in a `@callback`) is safe. If an S1 pass runs before the task, it reads gate (e) armed and defers once. The arrester's own timers fire ≥ 2 min later, by which time the row is gone. Deferring is the safe direction.
- The precedence after this rung is unchanged: `immune_stamp` → `borrow_active` (EGRESS rows, and a fresh NUDGE row without live timers, only) → `temp_arrester_override` → `comfort_grant` → `passive_mode` → governed. So an immune person, TAO, a comfort grant or passive mode each handle the change exactly as they would with no borrow. The borrow still ends in all of those cases.

**D2b — Owner guards.** Each place that can still write for an ended token must first check `token.returned` (NEW read-only property over `_returned`). If it is set, pop the token and write nothing:

| Site | file:line |
|---|---|
| `_release_banked_zones` (S11; used by master flip-off, gate flip-off, post-restart orphans, and D3) | `hvac_predict.py:922-1099` |
| `_return_preheat` (S13) | `hvac_predict.py:1518-1606` |

This also closes a pre-existing hole. After a `lease_expiry` sweep, the stale S12 token stays in `_banking_excursion_tokens`, so a later master flip-off would pin its `pre_preset` over whatever the zone holds by then.

**D2c — Compromise and grace re-dispatch.** If the zone has an arrester episode in flight (`zone_id in _grace_timers or _compromise_timers`):
- Cancel ONLY those two timers (REUSE the `:3528-3533` loop) and clear `_override_active` / `_compromise_active`.
- If a compromise token exists, schedule `_compromise_release_lease(zone_id, trigger="human_interrupt", restore_ok=None, trigger_detail="compromise_superseded_by_human")`.
- Then dispatch through the same precedence, using the stored episode baseline.
- NEW dict `_arrest_episode[zone_id] = {original_preset, expected_cool, expected_heat}`. It is written in `_handle_severe_override` / `_handle_normal_override` and cleared in `_revert_override`, `_defer_arrester_to_borrow`, the `enabled=False` setter (`:3070-3091`) and teardown. It is not persisted; grace and compromise already are not (W1-B non-goal).

**Baseline for the governed dispatch** (decision P3):

| Situation | Revert target `original_preset` | Expected value per CHANGED leg |
|---|---|---|
| A: a BANKING/PREHEAT borrow T was just ended | `T.pre_preset` if named (not `is_human_manual_snapshot`), else the resolver's preset | `T.pre_target_<leg>` if numeric, else the resolver's seasonal value |
| B: an arrester episode was in flight | `episode.original_preset` | `episode.expected_<leg>` |
| C: a plain within-manual change (no borrow, no episode) | the resolver's preset | the resolver's seasonal value |
| A transition INTO manual with no interrupt | today's `old_preset` | today's `old_high` / `old_low` (unchanged) |

- Resolver: a NEW arrester setter, `set_baseline_resolver(cb)`, mirroring `set_on_sunset_notify` (`:1130-1137`). HVACCoordinator implements `cb(zone_id) -> (preset, cool, heat) | None` with the startup-audit arithmetic (`:2222-2229`): house target preset plus seasonal setpoints.
- If the resolver returns None: book the row, do not dispatch, and let S1's §9e reclaim own the zone.
- The delta counts changed legs only, and applies the same `OVERRIDE_NORMAL_DELTA` / `OVERRIDE_SEVERE_DELTA` / coast bonus (`hvac_override.py:3476-3496`).

**D2d — S4 revert target (the §0 latent defect).** At `hvac_override.py:3938-3942`, use `_cmp_token.pre_preset` only when it is NOT a HUMAN_MANUAL snapshot (REUSE `strategy_for(...).is_human_manual_snapshot`). Otherwise use `original_preset`. If neither is named, skip the S4 write and close the lease with `restore_ok=None`, `trigger_detail="revert_no_named_preset"`; S1 then reclaims.

**D2e — Predictor latch.** Before the S12 begin (both reasons) and the S13 begin, skip zone Z when `arrester.last_detection_for(Z.climate_entity)` has `human_interrupt=True`.
- Discharge: Z leaves `manual`. The record is popped at `hvac_override.py:3109-3115`, by an S4 revert, an S1 reclaim or a human preset choice.
- Backstop: the record is RAM. A restart loses it, and the boot audit then releases BANKING rows with a preset pin (`hvac_excursion.py:1169-1215`), which ends the manual episode anyway.
- In the same pass, `_expire_pre_arrival_zones` clears Z from the pre-arrival set with reason `human_interrupt` when Z's pre-arrival token is `returned`. This is a pull, not a new callback. The fans are left on.

#### Acceptance criteria
- **Verify:** a human change during a pre-arrival pre-cool ends the borrow with no URA write carrying its `excursion_id`. The arrester then grants grace, compromises or reverts by the P3 delta against the snapshot preset.
- **Verify:** a human change during a compromise restarts the episode against the ORIGINAL baseline. The revert target is the pre-episode named preset, never `manual`.
- **Verify:** an egress-paused zone keeps booking `borrow_active` (P1), unchanged.
- **Test:** `test_human_interrupt_ends_banking_borrow_bookkeeping_only`. Real `_handle_climate_change` plus the real registry; the `hvac_excursion_events` row has trigger `human_interrupt`, and there are no `climate_write` rows from the borrow. **Mutation:** delete the D2a end call and this must go red.
- **Test:** `test_human_interrupt_ends_preheat_and_return_preheat_writes_nothing`. **Mutation:** remove the D2b guard in `_return_preheat` and this must go red.
- **Test:** `test_release_banked_zones_skips_returned_token` (the D2b S11 guard; mutation-anchored).
- **Test:** `test_human_change_during_compromise_redispatches_against_original_baseline`. Asserts `_arrest_episode` is used and the S4 preset is the original. **Mutation:** use `old_high` as the basis and this must go red.
- **Test:** `test_nudge_live_human_change_nudge_win_not_ended` (INV-A4). **Mutation:** move the D2a end above the `_nudge_live` check and this must go red.
- **Test:** `test_immune_person_interrupt_ends_borrow_and_stamps` and `test_passive_mode_interrupt_ends_borrow_no_revert`.
- **Test:** `test_s4_revert_never_pins_manual` (D2d). Real compromise begin on a manual zone, then revert; assert the S4 `values_after.preset_mode` is named. **Mutation:** restore the truthy test and this must go red.
- **Test:** `test_predictor_latch_blocks_s12_s13_begin_until_manual_exit`. Includes the discharge: after the zone leaves manual, a begin is allowed.
- **Test:** `test_interrupt_clears_pre_arrival_zone_next_pass`.
- **Test:** `test_detect_interrupt_uses_defer_cancel_loop_not_cancel_zone_timers`. A pending `_reset_timers` entry survives.
- **Live:** for the next organic (or operator-staged) human change during a pre-arrival pre-cool: `hvac_excursion_events` shows `trigger='human_interrupt'`, `restore_ok` NULL; `override_detected` shows `within_manual=true` and `gated_reason` NULL or a person rung; there is no S12 `climate_write` for that zone until the manual episode ends; and an S4 or S1 write follows within grace. **Discriminates:** before the fix the borrow ends `lease_expiry` about 7200 s later and there is no `override_detected` row. A wrong-direction fix would show S12 writes after t.
- **Live:** 7 d query, S4 `climate_write` rows with `values_after.preset_mode='manual'` = 0 (D2d).

---

## PART B — Pre-arrival borrow lifetime (HVAC-PRE-ARRIVAL-BORROW-LIFETIME-1)

### B.0 Producer / consumer

**Producers:**
- The `_pre_arrival_zones` set. Writer: `_handle_person_arriving` (`hvac.py:5798-5855`); each trigger resets `_pre_arrival_start`.
- The S12 pre-arrival borrow (`hvac_predict.py:1118-1225`), whose baseline comes from `_resolve_baseline_range`. That function prefers `_last_emitted_range`, which is written only by S10 (dormant), an S11 release and an S13 return (`hvac.py:3977`, `hvac_predict.py:1065`, `:1590`). So on the live house it is usually either empty or a pair left behind by an earlier release. That is a Bug Class #7 risk: the pair can come from an earlier release made under a different house state. The fallback is the house target preset's seasonal cool, and the low is synthetic (`cool − 7`).

**Consumers of set membership:**

| Consumer | file:line | Kind |
|---|---|---|
| Row-1 hold eligibility | `hvac.py:2586` | Trust |
| S1 reason ladder | `hvac.py:3335` | Ledger |
| D5 away edge | `hvac.py:4316` | Trust |
| `zone_presence_state` | `hvac.py:6031` | Display |
| Sensor attrs | `hvac.py:6716`, `:6785` | Display |
| Predictor loop | `hvac.py:2215` → `hvac_predict.py:645-653` | Trust |

Keeping a zone in the set until HVAC arms (P4) lengthens its membership. Every trust consumer then treats it as "arriving", which is the intent.

**Consumers of the borrow:** gate (e) (`hvac_preset.py:302-317`), the arrester precedence, the borrows sensor (`sensor.py:18199`) and `hvac_excursion_events`.

### B.1 Falsifiable invariant

> **INV-B.** For every borrow with `caller_site='S12_pre_arrival'` on zone Z:
> 1. exactly ONE S12 `set_temperature` for Z carries its `excursion_id`, and its `target_temp_high = max(baseline_high + PRE_ARRIVAL_PRECOOL_OFFSET_F, floor)`;
> 2. its `hvac_excursion_events.trigger ∈ {pre_arrival_arrived, pre_arrival_timeout, pre_arrival_inactive, human_interrupt}`, and never `lease_expiry`;
> 3. it ends within the same decision pass that removes Z from the pre-arrival set (or finds pre-arrival inactive), before S1 runs in that pass;
> 4. no S12 write lands on Z while any other borrow row is live on Z.

### D3: End conditions

**Arrival.** `_expire_pre_arrival_zones` (`hvac.py:5857-5887`) takes arrival from `any_room_hvac_occupied`, falling back to `any_room_occupied` only when the attribute is missing (P4). It returns `{zone_id: reason}`, where reason is one of `arrived`, `timeout` or `interrupted` (D2e).

**Ending, before S1.** A NEW predictor method, `async_end_pre_arrival_borrows(active_zones, reasons)`, is the single reconciliation. It walks `_banking_excursion_tokens`:
- a token with `caller_site == "S12_pre_arrival"` that is `returned` → pop it and write nothing;
- such a token whose zone ∉ `active_zones` → `_release_banked_zones({Z}, trigger=f"pre_arrival_{reason or 'inactive'}", update_throttle=False)`, a presets-only pin of `pre_preset` (P5).

HVACCoordinator calls it with `active_zones = self._pre_arrival_zones if zone_intelligence else set()`:
- in `_async_decision_cycle`, AFTER the ZI block (`hvac.py:2145-2149`) and BEFORE `_apply_house_state_presets` (`:2174`), outside the `if zi` guard, so Zone Intelligence OFF also ends them;
- in the fast run, after `hvac.py:4780` and before `:4782`.

Then refresh the zone state (`self._zone_manager.update_zone_climate_state(zone_id)`, `hvac_zones.py:600`) so S1 reads the post-pin preset. The call runs whatever the observation mode, because the S12 start also runs regardless (`hvac.py:2212` is outside the observation `if`). Leaving the borrow open would strand the zone.

**Site string.** S12 begins with `site="S12_pre_arrival"` when `reason == "pre_arrival"`. The `climate_write` site stays `S12_pre_cool`, with `reason="pre_arrival"`. `caller_site` consumers are the DB (free text, `database.py:1553`) and the borrows sensor attr (display, `sensor.py:18199`). No logic keys on the value. Tests that pin `S12_pre_cool` for the pre-arrival path are updated.

**Backstops.** The lease sweep (`hvac_excursion.py:733`) and the boot audit (`:1169-1215`) are unchanged. After this fix, reaching them is itself an INV-B failure.

#### Acceptance criteria
- **Verify:** the pre-arrival borrow ends on arrival (HVAC-occupied), on window expiry, on a human interrupt, or when pre-arrival goes inactive (ZI OFF). In each case a named-preset pin follows, then S1 on the same pass.
- **Test:** `test_pre_arrival_borrow_ends_on_hvac_arrival_before_s1`. Asserts the order: preset pin, then S1 write; no gate (e) deferral row. **Mutation:** move the call after `_apply_house_state_presets` and this must go red.
- **Test:** `test_pre_arrival_borrow_ends_on_timeout` (window from the D5 knob).
- **Test:** `test_hallway_lighting_does_not_end_pre_arrival` (P4). **Mutation:** revert to `any_room_occupied` and this must go red.
- **Test:** `test_zi_off_ends_pre_arrival_borrows`.
- **Test:** `test_fast_run_path_ends_pre_arrival_borrow`.
- **Test:** `test_pre_arrival_release_does_not_touch_last_emitted_range`.
- **Live:** for the next pre-arrival on any zone, the `hvac_excursion_events` row has `site='S12_pre_arrival'`, trigger `pre_arrival_arrived` or `pre_arrival_timeout`, and `duration_actual_s ≤ window + 300`. **Discriminates:** today it is `lease_expiry` at about 7200 s (09-25 7249 s, 09-27 7202 s). Pre-arrivals are about daily, so this is observable within the disposal window.
- **Live:** `preset_change_deferred` rows with `vacancy_bypass_deferred:active_borrow` on a zone after its pre-arrival ended = 0.

### D4: No ratchet — one write, from the baseline

**The pre-arrival guard.** In the pre-arrival branch (`hvac_predict.py:645-653`), call `_execute_zone_pre_cool` only if `not is_borrow_active(zone_id)` and the D2e latch is not set. So there is exactly one begin and one write per pre-arrival borrow. Another trigger for the same zone resets the window (existing behaviour) but writes nothing.

**Computing the value.** NEW keyword `from_baseline: bool = False` on `_execute_zone_pre_cool`. When True: `banked_high = baseline_high + offset`, with `baseline = _resolve_baseline_range(zone_id)`. If the baseline is None, skip; there is no write, and failing closed is correct. The floor (`:1137`) and the "never warm the zone" check (`:1140`, against the live high) are kept. The pre-arrival call passes `from_baseline=True`. The energy pre-cool call is unchanged; its own ratchet is a non-goal and gets a new card.

**The offset literal.** The `-2.0` at `:649` becomes the named rung-1 constant `PRE_ARRIVAL_PRECOOL_OFFSET_F = -2.0`.

**D4b — Never write over a foreign row (all reasons).** In `_execute_zone_pre_cool`, if `begin_excursion` returned None and the live row (`excursion_id_for`) is not this path's own token (the same `excursion_id` in `_banking_excursion_tokens` AND the same `caller_site`), return before the suppress and the write. Energy pre-cool on its own row keeps today's behaviour. Energy pre-cool meeting a live pre-arrival row, nudge, compromise or pre-heat row now skips.

**Consequence to call out in the README.** The first write moves from "live − 2" to "baseline − 2". With the zone at `away` 80 and home 76, today writes 78 → 76 → 74 over several passes; after the fix, one write of 74. P4 confirms the baseline values.

#### Acceptance criteria
- **Test:** `test_pre_arrival_single_write_across_three_triggers`. Geofence, BLE, tick, as on 09-28. Exactly one S12 `set_temperature`. **Mutation:** drop the `is_borrow_active` guard and this must go red (3 writes).
- **Test:** `test_pre_arrival_value_from_baseline_not_live` (live 78, baseline 76 → 74).
- **Test:** `test_pre_arrival_baseline_none_no_write`.
- **Test:** `test_s12_never_writes_over_foreign_row` (a nudge row live → no write). **Mutation:** remove D4b and this must go red.
- **Test:** `test_energy_precool_own_row_behaviour_unchanged` (a byte-identical twin).
- **Live:** for each `S12_pre_arrival` `excursion_id`, the count of `climate_write` rows = 1. **Discriminates:** P2 today shows several writes per borrow, plus NULL-id writes.

### D5: Knobs

| Number | Rung | Knob | Why |
|---|---|---|---|
| Pre-arrival window, 30 min (`PRE_ARRIVAL_TIMEOUT_MINUTES`, const) | **3: Number entity** | NEW `CONF_HVAC_PRE_ARRIVAL_WINDOW_MINUTES`; default = `PRE_ARRIVAL_TIMEOUT_MINUTES` (30, REUSED as the default); entity `35 · Pre-Arrival Window (min)` next to `35 · Pre-Arrival Conditioning` (`switch.py:4253`); range 5–120, step 5, CONFIG category; pattern `number.py:511-587` (live-attr push, then options writeback) | The operator asked for it. Commute lead times vary, and it is tuned by observation. 120 is the ceiling because the lease cap would cut anything longer. It has no kill-switch value: turning pre-arrival off is the switch's job |
| Pre-arrival offset, −2 °F (inline literal) | 1: module constant | NEW `PRE_ARRIVAL_PRECOOL_OFFSET_F` | Comfort magnitude, with no observation evidence yet for a live knob. Raise it to rung 3 only on an operator ask |
| Recent-writes depth, 4 | 1 | NEW `ARRESTER_URA_WRITE_RING_DEPTH` | Part of how URA's own echoes are recognised. Changing it changes what counts as human, so it should need review |
| Match tolerance, 0.5 °F | 1 | REUSE `LAST_SENT_TOLERANCE_F` | Already the "half a displayed degree" rule |
| `EXCURSION_LEASE_MAX_S`, 7200 | 1, unchanged | — | A safety cap and the backstop, not a lifetime |

#### Acceptance criteria
- **Sensor:** `number.ura_hvac_coordinator_35_pre_arrival_window_min` shows 30 after deploy.
- **Test:** `test_pre_arrival_window_knob_live_and_persisted`. Set it to 10, and `_expire_pre_arrival_zones` uses 600 s with no restart; the options entry carries the value. **Mutation:** read the constant instead and this must go red.
- **Live:** set it to 20 and confirm the attr on `sensor.ura_hvac_coordinator_*pre_arrival*` and the options write, then set it back to 30.

**Answer to the operator's question ("pre-cool is 2 hours? Is this a knob?").** No. Pre-cool was meant to last until you arrive, or 30 minutes. The 2 hours was a safety cap it fell back on, because nothing ended the borrow. After this fix it ends on arrival, on the window, or when someone changes the thermostat. The window becomes the knob `35 · Pre-Arrival Window (min)`.

---

## PART C — Reloading-room placeholder readers (W2-2)

This reuses the design of `PLANNING_hvac_reloading_room_placeholder_readers.md` §4. Its D1–D4 are renamed C1–C4 here. Line numbers are re-verified on `develop`.

**Pushback, recorded as required.** That plan's D0 (2026-09-27) measured 0 reloading-room samples and 0 boot resets, so every build gate failed and the verdict was PARK. The operator's 2026-09-28 green light overrides that for W2 closure. The value is latent-defect insurance, not measured harm. About 40 production lines. P6 refreshes the evidence. Q5 offers to cut the part down to C3, the only one guarding a failsafe clock.

### C.0 Producer / consumer
Unchanged from the parked plan §1–§2. Producer: the placeholder in `update_room_conditions` (`hvac_zones.py:623+`), with classification at `:779`. The trust readers that bypass the gate are R2 (D5), R3 (D6), R4 (the occupancy clock) and R9 (the row-11 grant). Part B's P4 switches the pre-arrival clear (R12) to the HVAC-fused signal. The placeholder reads False there, so the clear is delayed, which is the safe direction.

### C.1 Falsifiable invariant (unchanged)
> **INV-C.** On any decision pass where zone Z contains a TRANSIENT room:
> (a) no `away` write to Z has reason `stale_occupancy`, or reason `energy_shed_cap_reached` with `constraint_mode != "shed"`;
> (b) if fused HVAC occupancy is False, `Z.continuous_occupied_since` after the pass equals its value before;
> (c) a manual change on Z is never refused comfort grace for want of lighting occupancy.
>
> Carve-outs: house away/vacation, and EC shed.

### C1: D5 coast defers unless retreat is authorized
- Store the row-1 `_zone_conditioning_retreat_ok(zone)` result (`hvac.py:2540`) in `_retreat_ok_row1`, hoisted to the loop top with the other locals (`:2501-2510`). This avoids the UnboundLocalError when zi is off. Do not call it a second time.
- At `hvac.py:2896-2900`, replace `_row2054_fused` in the defer condition with `not _retreat_ok_row1`.
- The ledger row (`:2908-2948`) gains `details.defer_basis ∈ {occupied, room_reloading, unestablished}`, and `defer_basis` joins `_ep_key` (`:2912-2915`).
- Shed still forces away and still clears both holds (`:2949-2962`).
- **Tests:** `test_d5_coast_defers_when_zone_has_reloading_room` (mutation: restore `_row2054_fused` → red); `test_d5_coast_all_dead_zone_defers`; `test_d5_coast_established_empty_zone_still_forces_away`; `test_d5_shed_with_reloading_room_still_forces_away_and_clears_hold`; `test_d5_retreat_ok_local_hoisted_zi_off_no_unboundlocal` (real `_apply_house_state_presets`, no exception-swallowing helper).
- **Live:** every new D5 `preset_change_suppressed` row carries `defer_basis`. No coast `energy_shed_cap_reached` away coincides with a non-empty `transient_rooms`.

### C2: D6 skips its verdict while a room is reloading
- At `hvac.py:2679-2685`, add `and not _transient_blocked_row1` (computed at `:2567-2575`, before this point).
- No change to `presence.py`: Sources 1 and 4 (`:2100-2122`, `:2147-2159`) both lose the room, so excluding it cannot restore the lost confirmation.
- Discharge: the 300 s grace, after which the room is EXCLUDED.
- **Tests:** `test_d6_skips_verdict_while_room_reloading` (mutation: drop the conjunct → red); `test_d6_resumes_after_room_excluded_past_grace`.
- **Live:** in-suite only (a 4 h occupancy plus a reload on a tick cannot be staged).

### C3: The occupancy clock is not reset while a room is reloading
- At `hvac_zones.py:970-972`, the reset becomes `elif not self.is_zone_transient_blocked(zone.zone_id): zone.continuous_occupied_since = None`.
- Note: `is_zone_transient_blocked` returns False until classification is ready (`hvac_zones.py:2362-2363`). The very first boot pass therefore behaves as today; P3 measured 0 boot resets.
- **Tests:** `test_continuous_clock_not_reset_while_room_reloading` (real `update_room_conditions` and a real `ConfigEntryState`; mutation → red); `test_continuous_clock_resets_after_room_excluded`; `test_boot_pass_keeps_restored_continuous_clock`.
- **Live:** after the next HA restart, for zones HVAC-occupied on both sides, `continuous_occupied_hours` at the first sample is ≥ the last sample before the stop.

### C4: The row-11 grant counts a reloading room
- At `hvac_override.py:2718`: `occupied = bool(any_room_occupied) or (_tb is True)`, with `_tb = zm.is_zone_transient_blocked(zone_id)`.
- Only an exact `True` counts, so a MagicMock zone manager keeps legacy behaviour.
- **Tests:** `test_row11_grants_grace_when_only_occupied_room_reloading` (mutation → red); `test_row11_magicmock_zone_manager_keeps_legacy_behaviour`.
- **Live:** in-suite only.

**Cross-part note.** Part A's within-manual detections flow into row 11 through `_comfort_request_qualifies`. C4 therefore also applies to a human interrupt made while a room is reloading, which is consistent.

---

## 3. Emission-site enumeration: every borrow begin, every return, every end

"Change" says what this plan does at each site. Reviewers must re-run this enumeration independently (Tier 2 plan-review rule); the list below is a hypothesis.

**Begins**

| Site | Kind | file:line | Change |
|---|---|---|---|
| S3 compromise begin | COMPROMISE | `hvac_override.py:3732-3742` | none. Ended by D2c |
| S5 nudge start | NUDGE | `hvac_override.py:4823-4831` | none (D13) |
| S12 pre-cool, energy | BANKING | `hvac_predict.py:598` → `:1154` | D2e latch; D4b foreign-row guard |
| S12 pre-cool, pre-arrival | BANKING | `hvac_predict.py:649` → `:1154` | site `S12_pre_arrival`; D4 one-shot from baseline; D4b; D2e latch |
| S13 pre-heat | PREHEAT | `hvac_predict.py:1445-1455` | D2e latch |
| S15 egress pause | EGRESS_PAUSE | `hvac_egress.py:688-696` | none (P1) |
| Boot rehydrate (PREHEAT/COMPROMISE/EGRESS) | — | `hvac_excursion.py:1240-1256` | D1 boot seed reads it |

**Returns and ends**

| Site | Kind | file:line | Change |
|---|---|---|---|
| S4 revert → `_compromise_release_lease` (4 exits) | COMPROMISE | `hvac_override.py:3817-3981`, `:3983-4014` | D2d revert target; D2c adds a `human_interrupt` exit |
| S6/S7 nudge restore → return | NUDGE | `hvac_override.py:5071`, `:5116`, `:5293-5297` | none |
| S8 cancel-nudge | NUDGE | `hvac_override.py:6298`, `:6326`, `:6408-6412` | none |
| force_ac_reset | NUDGE | `hvac_override.py:6517-6525` | none |
| S9 boot ramp audit | NUDGE (setpoint/preset) | `hvac_override.py:6770`, `:6791` | none |
| S11 `_release_banked_zones` (callers `hvac_predict.py:472`, `:542`, `:551`, and NEW D3) | BANKING | `hvac_predict.py:922-1099` | D2b returned guard; `trigger` / `update_throttle` params |
| S13 `_return_preheat` (timer) | PREHEAT | `hvac_predict.py:1518-1606` | D2b returned guard |
| Egress resume / abort / rehydrate-orphan | EGRESS_PAUSE | `hvac_egress.py:773-904`, `:799-811`, `:442-453` | none |
| Lease-expiry sweep → `_auto_return` | non-nudge | `hvac_excursion.py:733-778`, `:632-730` | none (becomes an INV-B failure for pre-arrival) |
| Boot audit NUDGE / BANKING / stale | all | `hvac_excursion.py:1126-1238` | none |
| CM auto-release on an incomplete write | all | `hvac_excursion.py:1297-1365` | none |
| `_reap_stale` (from begin) | all | `hvac_excursion.py:597-608` | none |
| NEW human-interrupt end | BANKING / PREHEAT | `hvac_override.py` (`_handle_climate_change`) | D2a |
| NEW pre-arrival end | BANKING (`S12_pre_arrival`) | `hvac_predict.py` `async_end_pre_arrival_borrows` | D3 |

**Everything else that can end or override a borrow's effect on the wire.** Checked, and none changes:
- the S1 vacancy bypass and reclaim, which stay gated by (e) while the row lives;
- the heat_cool enforcer (`hvac.py:2409-2440`, mode only);
- AC hard reset;
- S10 DPM (dormant).

---

## 4. Edge cases (against QUALITY_CONTEXT classes)

- **#53 (computed but not consumed).** "Ended" must be honoured by every writer that holds a token: the two D2b guards, the D3 pop, and the D2e latch at S12 and S13. Reviewer C mutates each one.
- **#7 (stale data source).** `_last_emitted_range` can be stale for D4's baseline. D3 passes `update_throttle=False`, so pre-arrival never writes the throttle map. S11 and S13 still do, which is pre-existing; card it if P4 shows a mismatch.
- **#22 (enum mismatch).** New strings:
  - site: `S12_pre_arrival`;
  - triggers: `human_interrupt`, `pre_arrival_arrived`, `pre_arrival_timeout`, `pre_arrival_interrupted`, `pre_arrival_inactive`;
  - trigger_details: `compromise_superseded_by_human`, `revert_no_named_preset`.
  Grep every consumer of `trigger` / `site` values (DB, borrows sensor, probes) before merge.
- **#23 (observation mode).** D3 ends borrows in observation mode, matching S12, which starts them in observation mode too. The D2 arrester path already respects observation mode through its own writes.
- **#32 (options writeback).** The D5 Number follows the Return Window pattern exactly.
- **#43 / Part C.** The placeholder carries egress and window state; untouched.
- **D49 interplay (Q4).** After D2 ends a borrow in an EMPTY zone, S1's vacancy bypass ignores gate (c). It writes `away` on the next pass, over the human's value. That is today's ordinary behaviour for a remote change to an empty zone.
- **Restart.** Everything new is RAM: the recent-writes record (seeded at boot), `_arrest_episode`, the latch and the pre-arrival set. At boot, BANKING rows are released with a preset pin and `_pre_arrival_zones` starts empty, so no pre-arrival borrow survives a restart. That is today's behaviour too.
- **Pre-arrival switch turned OFF mid-episode.** The episode runs to the window (now bounded), as today. Non-goal.

---

## 5. Non-goals

- Boot-window reconciliation (ARRESTER-BOOT-BLIND-1 gap (1), manual holds that predate the listener). Stays parked.
- A human NAMED-preset choice during a borrow (a preset→preset change, which the arrester ignores at `:3220`). The borrow's return would pin its snapshot over it. Card it.
- A human `hvac_mode` change within manual.
- The energy pre-cool ratchet on its own row (`hvac_predict.py:598` path). NEW card: `HVAC-ENERGY-PRECOOL-RATCHET-1`.
- Any change to `begin_excursion` / `return_excursion` semantics. Only `live_token_for` and `ExcursionToken.returned` are added, and both are pure reads.
- A DB-seeded recent-writes record (reading `climate_write` at boot). Seeding from rehydrated rows is enough.
- Egress under the interrupt rule (P1, Q2).
- Persisting grace, compromise or the episode (W1-B non-goal).
- Part C: everything in the parked plan's §9 non-goals.
- No new DB table, DAO or signal.

---

## 6. Tier and reviews

**Tier 2-DB, as the orchestrator directed.** Triggers:
- persisted payload shape changes (`override_detected` details keys; excursion `site` / `trigger` values);
- trust-hierarchy ripple: arrester ↔ S1 gates ↔ predictor ↔ egress;
- strategy change on a comfort and cost path.

**Three parallel reviews with disjoint framings:**
- **A: correctness and edge cases.** The D1 classifier and ring semantics against the P1 fixture; the baseline table and changed-legs delta; D4 arithmetic and floor; Part C truth tables and the D5 knob bounds.
- **B: cross-coordinator precedence, lifecycle and no-flap.** Arrester precedence with the new rung vs D13/D48/D49/D50; ordering of the D3 end before S1 in both the tick and the fast run; task-scheduling races with gate (e); restart and RAM discharges; shed dominance in C1.
- **C: test authority and DB surfaces.** Real per-site source mutation for EVERY row of §3 marked changed, and every mutation named above. Also: the ledger/event payload shapes and values; the Number round-trip and persistence; and that `climate_write` rows are byte-identical except for the new RAM record.

Plus ONE plan review before build (Tier 2 rule), which re-runs the §3 enumeration with greps. Then live validation and the README write-back.

---

## 7. Open operator questions

1. **Q1.** D1 needs ONE read-only in-memory record inside `emit_set_temperature` of what URA just wrote. That is an exception to W1-B's "no changes inside the funnels". The alternative, having every write site pass its values to the arrester, has 8+ places to miss, and a miss makes URA "interrupt" itself. OK to add the record?
2. **Q2.** Egress pause is left out of "person interrupts" (the door-open pause keeps the zone off). OK?
3. **Q3.** After a person interrupts, URA does not start a NEW pre-cool or pre-heat on that zone until it leaves manual. This narrows D48 ("URA wins on starts") for that one case. OK?
4. **Q4.** If someone changes an EMPTY zone (for example from the app on the way home), the arrester takes over, but S1's empty-zone retreat still sends it to Away on the next pass (≤ 5 min), as it does today. Keep that, or hold such a zone until arrival or the window ends?
5. **Q5.** Part C has measured zero exposure. Build all four (C1–C4) as green-lit, or only C3 (the occupancy clock that feeds the stuck-sensor failsafe)?
6. **Q6.** Part A changes the arrester's core detection, and one missed return site means URA overwrites the person. That is the Tier 3 "one missed site" shape. Keep Tier 2-DB with mandatory per-site mutation, or add a 4th adversarial completeness reviewer?

## 8. State-of-play updates due with the build

- §0 stale-citation table.
- §6: interruptible borrow kinds.
- §7: within-manual detection.
- §9e: a new ruling row for 2026-09-28 "person interrupts" (D13 kept; D48 narrowed per Q3; compromise re-dispatch).
- §4.2: `S12_pre_arrival`.
- §10: a new correction entry for the S4 `manual`-pin defect, if P5 confirms it.

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
