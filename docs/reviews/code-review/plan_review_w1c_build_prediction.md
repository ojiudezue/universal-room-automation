# Plan review #2 (Tier 3, adversarial build-prediction) — W1-C Thermostat Profiles

Plan: `docs/planning/PLANNING_hvac_w1c_thermostat_profiles.md` (develop @30f9981ae). Reviewer lane: "what will the builder get wrong?" Site completeness is reviewer #1's lane.
I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely (incl. §10 C1–C29) first. None of the findings below re-assert a §10 claim.

**Verdict: REVISE.** 4 HIGH, 7 MEDIUM, 3 LOW. P1 cannot be built as written without a real Carrier regression. The cause is the plan's own "extend `_last_sent`" deliverable (F1), and the byte-identity proof it specifies would not catch that regression (F2).

---

## HIGH

**F1 — Extending `_last_sent` to `set_temperature` / `set_hvac_mode` breaks Carrier byte-identity through the clear-all rule.**
- Where: `hvac_strategy.py:146-149`. `_record_sent` replaces the entity's whole record (`{verb: ...}`), so any recorded write clears every other verb.
- Two consumers read the preset record:
  - the D2.5 no-op in `hold_preset` (`:189-197`);
  - `_zone_last_write_is_away` (`hvac.py:4772-4786`), which keys the fast-path limiter exemption and the exit timer.
- Repro (Carrier):
  1. S1 pins `home`, so the record is `{set_preset_mode: home}`.
  2. The B1 enforcer writes `heat_cool`. Under P1 D2 it is recorded, which wipes the preset record.
  3. On the next tick, S1 sees `home` again. Before P1 the D2.5 no-op returned `SKIPPED_ALREADY_CORRECT`. After P1 there is no record, so S1 emits `set_preset_mode home`, plus `resume` when `hold_activity == manual`.
- Result: an extra Carrier cloud write per enforcer cycle, and the P1 invariant is broken.
- A nudge's S5 `set_temperature` also wipes an `away` record. After a restart-free miss of `_zone_last_s1_write`, `_zone_last_write_is_away` then flips.
- **Fix-in-plan:** "P1 adds per-verb records WITHOUT cross-verb clearing (`_last_sent[entity][verb]` updated independently). The D2.5 no-op stays preset-only. No new verb gets a no-op skip in P1. Test: the enforcer write between two S1 ticks still yields `SKIPPED_ALREADY_CORRECT`, and `_zone_last_write_is_away` still reads `away` after an S5 write."

**F2 — The byte-identity proof has no fixture authority and is too narrow to catch a real regression.**
- *Oracle authority.* "Pre- vs post-P1 … assert equality" does not say where the "pre" comes from. A builder will write expectations by reading the new code, which makes a hollow anchor (Bug Class #62).
  - **Fix:** "Goldens are CAPTURED by running the scenario harness on the tagged pre-P1 commit (`pre-w1c-p1`), committed as JSON before any P1 source edit, and never regenerated in the P1 branch. A regeneration is a review-blocking diff."
- *Capture point.* The capture must be at `hass.services.async_call` (the real funnels run, including resume-then-pin and gates). It must not be at `strategy.*` or the funnel.
  - The strategy under test must be the REAL `CarrierStrategy` with a registry fixture whose `platform="ha_carrier"`. Monkeypatching `strategy_for` defeats detection.
- *Outcome axis.* The invariant says "every WriteStatus", but the test says "APPLIED and DEFERRED". There are 4 states, and FAILED has two causes (emit raised; `no_presets_supported` with zero calls on an unavailable entity whose attrs are empty).
  - **Fix:** parametrize over all four, plus the unavailable-entity case.
- *What equality covers.* Wrapping bool-returning funnels in `WriteResult` forces every `if await emit_…:` caller to be rewritten, because truthiness raises. Mapping DEFERRED to the old falsy branch versus the FAILED branch changes `_last_emitted_range`, `restore_ok`, `ac_ramp_events` / `hvac_excursion_events` rows, timers and the latch, with identical service calls.
  - **Fix:** "Byte-identity = service calls AND the ledger rows (`climate_write`, `ac_ramp_events`, `hvac_excursion_events`, `ura_activity_log`) AND the named in-memory state per site (`_last_emitted_range`, `_nudge_restore_timers`, `_zone_last_s1_write`, excursion rows). Each site's old bool→branch mapping is tabled in the plan, e.g. funnel False → old falsy branch → `DEFERRED`."
- *Order across awaits.* "Emission order" must be per zone and per site sequence, not global. Concurrent zones interleave nondeterministically. Say so, or the builder will write a flaky global-order test and loosen it.

**F3 — Generic "person change" rule names the wrong store, and it cannot represent single-setpoint thermostats.**
- D4 and the Plan header say "within ±0.5 °F of any URA-recorded `set_temperature` in `_last_sent` … in the last N min AND no `climate_write` row".
- Problems with the stores:
  - `_last_sent` holds one value per verb, and it is flushed on divergence and on any other-verb write.
  - The value-matched record the arrester actually uses is `_URA_SETPOINT_WRITES` / `recent_ura_setpoints` (`hvac_setpoint.py:71-100`, ring depth `ARRESTER_URA_WRITE_RING_DEPTH`, boot-seeded from borrow rows).
  - A `climate_write` row is an async DB write (fire-and-forget `_schedule_climate_write_row`, `hvac_setpoint.py:213`). Reading it on the event path is a DB read in the decision path and races its own insert.
  - "N min" is an unnamed literal.
- Problem with the shape: the ring stores `(low, high)`, and ecobee single-mode writes `temperature`, so nothing matches and every URA echo books HUMAN.
- **Fix:** "Person-change for all profiles consults `recent_ura_setpoints` (REUSED). P2 extends the ring entry to `(low, high, single)`, recorded in `emit_set_temperature` for the `temperature` key. It also adds a URA select-write ring for `select_option`. No DB read on the event path. The window is a named rung-1 const per profile (`person_change_match_window_s`)."

**F4 — P3 D0 is labelled read-only but its go/no-go needs writes; the ecobee hold model is asserted, not measured.**
- Three of D0's go/no-go items need writes: "`button.press` on Clear Hold returns cleanly", "setpoint write latency + echo timing", and "select transitions … reflected".
- D5's ecobee hold semantics are stated without a source. Nothing in the plan establishes:
  - whether `select_option current_mode` creates a hold, and of what duration (ecobee device "hold action" setting: until next activity / indefinite / 2 h / 4 h);
  - what Clear Hold returns the thermostat to (its own schedule);
  - whether a setpoint write over HomeKit creates the same hold.
- Under "until next activity", the ecobee's own schedule silently undoes URA's hold at each comfort boundary. That is the Carrier-schedule problem (§5, §9b, C12) again, not a person.
- **Fix:** split D0 into:
  - **D0a** — read-only, 24 h, including the schedule transitions seen;
  - **D0b** — operator-witnessed, scripted write probe on House 2 with HVAC physically safe. It records hold duration after `select_option`, after a `temperature` write, and after `clear_hold`, plus echo latency distribution (p50/p95/max), which sets `echo_ttl_s`. It also reads the device's "hold action" setting.
- The `echo_ttl_s = 30` and `preset_echo_ttl_s = 60` numbers in D5 are placeholders until D0b. Mark them TBD, not values.

## MEDIUM

**F5 — Thermostat-side schedule transitions are unclassified.**
- Generic and ecobee "setpoint moved without a URA write → HUMAN" books every schedule boundary (ecobee comfort-setting change, Carrier's 06:00 Home entry, a generic thermostat's program) as a person.
- The arrester would then revert it (fight the schedule), or the interrupt ends a borrow and latches the zone (§9e Q3).
- **Fix:** add a third verdict `DEVICE_SCHEDULE` to `PersonChangeVerdict`. Its detection per profile:
  - ecobee: `current_mode` changes at the D0a-measured schedule times, with no URA select write;
  - Carrier: unchanged, byte-identical;
  - Generic: not distinguishable, so be conservative and book but never revert. Say this explicitly.
- Also state which consumers treat the verdict how: arrester, interrupt latch, gate (a/b).

**F6 — `PersonChangeVerdict` / `classify_person_change` has no contract.**
- Missing inputs: old and new observation, `recent_ura_setpoints`, reference resolver, suppression state.
- Missing return values: enum members plus `delta_f` / changed legs.
- Missing side effects: none allowed; ledger rows are written by the caller.
- The relation to the existing `classify_manual_setpoint_change` (`hvac_override.py:167`) and `_transition_is_human` is also unspecified. The P1 B5 deliverable routes through it, but D1 says "replaces".
- If the builder re-implements, Carrier drifts.
- **Fix:** "Carrier `classify_person_change` = a verbatim delegate to the existing classifier and suppression check. Generic and ecobee are new implementations of the same contract. A shared contract test table runs every profile over the same event fixtures, and the Carrier rows are pinned to pre-P1 verdicts."
- The same need applies to `set_setpoints` / `set_hvac_mode` / `release_hold`. Specify per method: kwargs (site, zone_id, reason, blocking, gate, excursion_id), return mapping, `_last_sent` / ring effects, and suppression registration (`suppress(kind=...)` lives in `hvac_override` today; say who calls it after P1, since otherwise it is dropped or doubled).

**F7 — Echo TTLs become per-profile, but the suppression store is per arrester.**
- `SUPPRESS_TTL_SECONDS` / `_PRESET` (`hvac_override.py:133/173`) are read at suppress/check time without an entity→profile lookup.
- P2-5 "accessed via `strategy.capabilities`" is not placed. The builder will either read the zone's profile at suppress time or at check time, and on a profile switch mid-window those two choices differ.
- **Fix:** "The TTL is resolved at suppress time and stored with the suppression entry."

**F8 — Detection vs override persistence is mixed; restart, boot and hardware swap are unspecified.**
- D2 persists `zone_thermostat_profile` and also says a Carrier entry "keeps `carrier` explicitly". The builder will write the detected value into options, which makes every zone an override, so a hardware swap never re-detects (Open Q3 answered by accident).
- **Fix:** "Options store ONLY an operator override (absent = detect). Detection is computed live from the registry, never persisted. `profile_source` is derived."
- Boot: registry entries persist across restarts, so an unavailable Carrier entity (Batch D) still resolves Carrier. Say this, and add a test with an unavailable state plus a present registry entry, to Carrier.
- The miss path returns a FRESH uncached `GenericStrategy` per call (`hvac_strategy.py:257-258`), so its `_last_sent` and no-op are lost on every call. Specify that a miss is loud: one INFO per entity per boot and a sensor attr `profile_source=detect_miss`.
- "Where is the zone setting stored": HVAC zones are thermostat-keyed zone_N from the Zone Manager (HVAC zone ≠ house zone). Name the entry and the key, e.g. keyed by `climate_entity`, not by house zone, or two house zones on one thermostat can disagree.
- Profile switch "flushes `_last_sent`": records live on the per-platform instance, so switching away and back revives the old instance's stale record. **Fix:** flush on BOTH instances. Also flush the ring and the suppression entries.

**F9 — Generic override is called "safe", but it is not safe on a Carrier device.**
- Rung table: "kill switch for the wrong profile (`Generic` = safe)". Generic holds by setpoint on a Carrier thermostat, which creates the anonymous manual holds behind §9.1. Generic never pins or resumes, so nothing reclaims them, and `infinite_holds` keeps them.
- There is also a contradiction: the existing `GenericStrategy.hold_preset` PINS presets when the entity advertises them (`hvac_strategy.py:99-110`, `:171-217`), while P2's invariant says Generic makes ZERO named-preset writes.
- **Fix:** state P2's explicit behaviour change to `GenericStrategy`. Then either:
  - (a) restrict the override dropdown to profiles compatible with the detected integration, or
  - (b) show a warning that Generic on a detected Carrier device only writes setpoints.

  Test the override-to-Generic-on-Carrier case.

**F10 — D4 "operator's per-zone comfort table already used for Carrier presets" does not exist.**
- Carrier preset setpoints live on the thermostat (Bryant comfort profiles, §1). A grep for comfort tables and preset setpoints in the integration finds nothing.
- Open Q2 half-admits this for ecobee. For Generic it is a fabricated REUSE.
- **Fix:** mark it NEW (a per-zone home/sleep/away setpoint config, knob rung 2) with an institutional-context citation, or have Generic write nothing without a configured table (`feature_unavailable("hold")`).

**F11 — P1 deliverable 5 (`profile` / `profile_source` on `climate_write`) edits the funnel.**
- The operator constraint is "nothing added to the `emit_*` funnels" (`hvac_strategy.py:7-8`; one reviewed exception already at `hvac_setpoint.py:60-68`). The deliverable either needs a new funnel kwarg, which breaks call byte-identity of the funnel signature, or a lookup inside the funnel.
- It also belongs in P2, since `profile_source` does not exist in P1.
- **Fix:** move it to P2, and record it as a second named funnel exception with its reason.

## LOW

**F12 — The AST lint "no raw `preset_mode == 'manual'`" is too narrow.**
- It misses the forms actually used: `pre_preset in (None, "", "manual")` (`hvac_strategy.py:164`, `hvac_excursion` `_auto_return`, C26), `!= "manual"`, `.get("preset_mode") == ...`, and comparisons against a `MANUAL` constant.
- **Fix:** the lint flags any `"manual"` string literal in `hvac*.py` outside `hvac_strategy.py` and an explicit allowlist, with a reason per entry.

**F13 — P3 acceptance "classifies HUMAN within one tick".**
- Person-change is event-driven (`_handle_climate_change`), not tick-driven.
- "Exactly 3 `climate_write` rows" assumes no enforcer, S1 reclaim or retry writes during the walk.
- **Fix:** "Within one state event after the HomeKit echo. Rows filtered by `site=S1`."

**F14 — P1 live criterion "24 h of rows show no new verb/site/values shape".**
- This is a soak-shaped criterion and non-discriminating, since the values legitimately vary.
- **Fix:** replace it with a one-shot DB query (distinct `(verb, site, service_data keys)` before vs after), per the Soak Exit rule.

---

## Phase boundaries (question 6)
- **P1 can ship alone** only after F1 and F2 are fixed. With those, it is a pure refactor for Carrier.
- **P2 depends on P1 details:** the method kwargs contract (F6), the ring shape (F3) and the TTL placement (F7). Freeze all three in P1's text, even if the Generic implementations land in P2.
- **P3 depends on P2** for the Generic fallback and detection, and **on D0b** (F4). Open Q1 (House 2-only flag) should be answered before P2 merges, because P2's detection is what would first route a House-2 ecobee through Generic.
- **Batch C (CPR) and W1-C touch the same `emit_set_activity_setpoint` strategy hook.** The plan should state merge order.

## Tier / knobs (question 7)
- Tiers are adequate (P1 and P2 Tier 3, P3 Tier 2-DB).
- P4 at Tier 2 is under-tiered. It gates the nudge and AC hard reset, which are live cost/comfort paths and have multiple sites (#53). Make it Tier 2-DB.
- Knobs:
  - The unnamed N-min window (F3) and `HVAC_PROFILE_DETECTION_RECHECK_S` have no stated value or consumer. Either name a value and consumer, or drop the recheck: detection is live per call (F8).
  - The ecobee TTLs are TBD until D0b (F4).

## Must-fix before build dispatch
F1, F2, F3, F4 (HIGH); F6, F8, F9, F10 (MEDIUM, all builder-divergence risks). F5, F7 and F11 should also be fixed in the plan, since they are cheap text changes.

---

# REV 2 re-review (2026-09-30)

**Verdict: REVISE (narrow).** Most original findings are closed; F1 and F6 are only partly closed. REV 2 introduces 2 new HIGH (N1, N2) that would break P1's Carrier byte-identity or its liveness, plus 4 MEDIUM and 2 LOW. All are text fixes. Once N1–N4 are fixed, P1 can ship alone.

## Original findings — status
| # | Status | Note |
|---|---|---|
| F1 | CLOSED except N3 | Per-verb records, no cross-verb clearing, no new no-op, §J protected. The `release_hold` row "records the exit verb" reopens the risk (N3). |
| F2 | CLOSED | Tagged goldens, capture at `async_call`, real `CarrierStrategy`, all outcomes plus unavailable, equality covering rows/state/branch mapping, order per zone and site. One residual: the invariant says "across restart and reload", but no restart/reload scenario is in the harness list. Add a scenario for boot-audit rehydrate and a scenario for a room reload mid-borrow. |
| F3 | CLOSED except N4 | The ring is reused, the window is named, and there is no DB read. The tuple-arity change is under-specified (N4). |
| F4 | CLOSED | D0a/D0b split; ecobee timings `None` = TBD. Add: a profile with `echo_ttl_s is None` must be undispatchable, meaning detection falls to Generic until D0b fills the value. Otherwise a `None` TTL reaches the suppression math. |
| F5 | CLOSED except N5 | |
| F6 | PARTIAL | The contract table's suppression column contradicts the code (N1). |
| F8 | CLOSED | Override-only persistence, live detection, loud miss, keyed by `climate_entity`, flush on both instances plus ring plus suppression, Repair on mismatch. |
| F9 | CLOSED | Generic is honest; the change to `GenericStrategy.hold_preset` is explicit; the warning is present and tested. |
| F10 | CLOSED | Per-zone Home/Sleep/Away fields are an operator-ruled NEW item; a missing table gives `feature_unavailable("hold")`. |
| F11–F14 | CLOSED | F11's "second exception" numbering now collides (N6). |

## New in REV 2

**N1 — HIGH — The contract table moves arrester suppression into the funnel, and that is wrong for P1.**
- The table says "funnel registers `preset` / `temp` suppression" and "`set_hvac_mode`: no suppression".
- In the code, suppression is registered by the CALLER at about 20 sites: `hvac.py:2588` (the heat_cool enforcer, which suppresses on `set_hvac_mode` with the default kind), `:3564`, `:4115`; `hvac_predict.py:1105/1128/1396/1762/1869/1884`; `hvac_override.py:4536/4546/4765/4775/4797/5401/5751/5919/6073/7261`.
- A builder following the table will either:
  - add suppression to the funnel, which is a third undeclared funnel exception, doubles registration, and moves the TTL start across the write `await`; or
  - drop the enforcer's suppression.
- Either way the arrester verdicts change, which is not visible in the service calls. The golden's equality list does not include suppression state.
- **Fix text:** "P1: suppression stays caller-registered at every existing site, unchanged (site list above). The Suppression column reads 'caller, unchanged in P1'. Suppression state `(entity, kind, expires_at)` is added to the byte-identity equality set. Moving registration into the strategy is a P2 decision, reviewed on its own."

**N2 — HIGH — P1 deliverable 5 stubs Generic/ecobee as `NotImplementedError`, but Generic is dispatched live in P1.**
- `strategy_for` returns an uncached `GenericStrategy` on any registry miss (`hvac_strategy.py:257-258`), and for any non-`ha_carrier` platform.
- Once every A-site calls `strategy.set_setpoints` / `set_hvac_mode`, a miss raises on a write path, for example a restored or renamed entity or a test fixture without a registry. Today the same call writes.
- **Fix text:** "In P1, `GenericStrategy.set_setpoints` / `set_hvac_mode` / `release_hold` delegate to the same funnel calls as Carrier (today's behaviour for every platform). Only `classify_person_change` for non-Carrier may be a stub, and it must return `INCONCLUSIVE`, never raise. Add a test: a registry-miss entity is driven through every A-site with identical calls to the Carrier golden."

**N3 — MEDIUM — `release_hold` "records the exit verb" is ambiguous.**
- If the Carrier `resume` is recorded under `set_preset_mode`, `_zone_last_write_is_away` (§J) reads `"resume"`, not `away`, and the D2.5 no-op compares against `"resume"`.
- In P1 there is no Carrier `release_hold` site: resume lives inside `emit_set_preset_mode`.
- **Fix text:** "P1: `release_hold` has no Carrier caller and records nothing. From P2 it records under its own verb key `release_hold`, never `set_preset_mode`."

**N4 — MEDIUM — The ring tuple-arity change breaks consumers that expect pairs.**
- `recent_ura_setpoints` is consumed as `(low, high)` pairs in `_transition_is_human` / `classify_manual_setpoint_change` (`hvac_override.py:3587-3600`) and by the boot seeding from borrow rows.
- The plan says only "funnel appends `(low, high, single)`", and the contract table is marked frozen in P1.
- **Fix text:** "The ring stays `(low, high)` in P1. In P2 the single setpoint is stored in a separate `single` slot, readable only through a new accessor `recent_ura_single_setpoints`. The existing accessor's return shape is unchanged, so Carrier consumers are untouched. The boot seed is updated in the same commit."

**N5 — MEDIUM — Generic's schedule-change handling is described three different ways.**
- The changelog says "Generic = conservative BOOK but never revert".
- §3c says `INCONCLUSIVE` (arrester ignores, latch ignores), one INFO per zone per DAY.
- §3d says `INCONCLUSIVE` for select=unknown, one INFO per zone per BOOT.
- "BOOK" means an `override_detected` row; "ignore" means none.
- It is also unstated whether `INCONCLUSIVE` or `DEVICE_SCHEDULE` discharges or blocks gate (a/b), and whether it counts as a "person change" for INFO-1 (the §9e person-owned restore).
- **Fix text:** add one consumer table with rows = {HUMAN, URA_ECHO, DEVICE_SCHEDULE, INCONCLUSIVE} and columns = {`override_detected` row (with `gated_reason`), arrester revert, borrow `human_interrupt`, interrupt latch, INFO-1 person restore, INFO cadence}.
  - Proposed: DEVICE_SCHEDULE and INCONCLUSIVE write a row with `gated_reason` set to `device_schedule` or `inconclusive`, and have no other effect. Cadence: one INFO per zone per day for both.
  - State that Carrier never emits either verdict in P1 or P2.
  - State where DEVICE_SCHEDULE's catalog lives: a rung-1 const per profile seeded from the D0a catalog, or learned. Pick "const from D0a, reviewed". A learned catalog is a new mechanism.

**N6 — MEDIUM — There are two "second funnel exceptions", and the rename of `verb` would break P1's golden and live query.**
- The changelog calls both `emit_call_service` (select/button) and the `profile` kwarg on the `climate_write` row the "second named exception".
- "Row `verb` becomes `"{domain}.{service}"`" is ambiguous: does `set_temperature` become `climate.set_temperature`? If it does, the P1 goldens, the live DISTINCT query and existing readers of `verb` all break.
- **Fix text:**
  - Number the exceptions: second = the `profile` / `profile_source` kwarg (P2); third = `emit_call_service` (P3, the only non-climate writer).
  - The `verb` value for climate calls is unchanged (bare service name). Only non-climate rows carry `domain.service`.
  - `emit_call_service` is allowlisted to exactly `select.select_option` and `button.press` on siblings resolved by `device_id`. Any other domain/service returns FAILED with zero calls.
  - The AST lint's select/button clause turns on in P3, not P1.

**N7 — LOW — "D0a gates on … within 60 s of a `select_option` write" is a write inside the read-only phase, and 60 is an inline literal.**
- Move that check to D0b and name the window.

**N8 — LOW — "Timings TBD" includes `person_change_match_window_s`, but P3 acceptance needs it.**
- State that it comes from D0b's p95 echo latency, or use the Carrier ring depth semantics if count-based.

## Can P1 ship alone?
Yes, after N1 and N2 are fixed. N3, N4 and N6 must also be fixed in text now, because the P1 contracts are declared frozen and those three change P1-visible shapes. N5, N7 and N8 are P2/P3 issues but are cheap to fix now.

**Must-fix before build dispatch:** N1, N2, N3, N4, N6. Recommended: N5, N7, N8, plus the F2 restart/reload harness scenario and the F4 `None`-TTL undispatchable rule.

---

# REV 3 final pass (2026-09-30)

**Verdict: READY for P1 dispatch once R1 (a one-line text fix) is applied. P2 needs R2 and R3 fixed in the plan before P2 build dispatch.**

## REV 2 fixes — status
| # | Status | Note |
|---|---|---|
| N1 | CLOSED except R1 | Suppression stays with callers; the ~20 sites are listed; suppression is in the equality set. |
| N2 | CLOSED | Generic uses the same funnels as Carrier in P1; the stub returns `INCONCLUSIVE`; there is a registry-miss golden test. |
| N3 | CLOSED | No `release_hold` caller or record in P1; own verb key from P2. |
| N4 | CLOSED | The pair ring is untouched; a separate timestamped single ring and a select ring land in P2; the boot seed is in the same commit. |
| N5 | CLOSED except R2 | |
| N6 | CLOSED | Exceptions numbered 1/2/3; climate verbs stay bare; allowlist of exactly 2 services; the lint clause lands with P3. |
| N7, N8 | CLOSED | Named `ECOBEE_SELECT_READBACK_S` / `ECOBEE_PC_WINDOW_MARGIN_S`; Generic 600 s, Carrier N/A. |
| Restart/reload residual | CLOSED | Boot-audit rehydrate and mid-borrow room-reload scenarios, with goldens from `pre-w1c-p1`. |
| TBD-timing residual | CLOSED | A profile with a `None` TTL is undispatchable: it falls to Generic-blocked plus a Repair. |

## New in REV 3

**R1 — MEDIUM (P1) — The suppression store names are wrong.**
- The changelog names `_recent_suppressions` / `_preset_suppressions`; neither exists.
- The real stores are `OverrideArrester._suppressed_until` (`hvac_override.py:353`) and `_suppress_kind` (`:368`).
- A builder will either invent the attributes or snapshot nothing, which makes the N1 equality leg hollow.
- **Fix text:** "Equality includes `{entity: (_suppressed_until[entity], _suppress_kind[entity])}`, snapshotted after each site."

**R2 — MEDIUM (P2) — §3d's "not written (`gated_reason=device_schedule`)" contradicts itself.**
- A `gated_reason` only exists on a written row.
- **Fix text (pick one):** "DEVICE_SCHEDULE / INCONCLUSIVE WRITE one `override_detected` row with `gated_reason=device_schedule` or `inconclusive`, with no other effect". This keeps diagnosis on ground truth. Otherwise, delete the `gated_reason` text and state "no row; INFO only".

**R3 — MEDIUM (P2) — Generic-override and registry-miss behaviour contradict each other.**
- §3d says "a Carrier device forced to Generic still routes writes identically to Carrier".
- The P2 deliverables at plan line 260 say Generic is `hold_via="unsupported"` / `feature_available("hold")=False`, so S1 stands down.
- The P2 test at plan line 265 says "writes match Carrier goldens; only `feature_available("hold")` flips".
- A builder cannot satisfy all three. The same ambiguity also decides a P2 regression: a transient registry miss on a Carrier entity (uncached Generic) would turn S1 off with a Repair.
- **Fix text:**
  - "(a) The OVERRIDE to Generic makes S1 stand down (hold unavailable) and the dropdown warning says so. The line-265 test asserts ZERO S1 writes plus one Repair, not Carrier goldens."
  - "(b) A detection MISS keeps the entity's last successfully resolved profile (RAM, per entity) for the boot. Only an entity never resolved this boot falls to Generic-blocked, and then with the loud INFO / `detect_miss` attr."

**R4 — LOW (P2) — The new single-ring producer is not placed.**
- The existing pair record is written inside `emit_set_temperature` (`hvac_setpoint.py:486`), under the first narrow exception.
- **Fix text:** "The single ring and the select ring are recorded by the same funnels (`emit_set_temperature` for the `temperature` key; `emit_call_service` for `select_option`), as an extension of exception #1 / #3 respectively. The pair ring is NOT appended when the call carries only `temperature`, so no `(None, None)` entries are recorded."

## P1 alone
Safe to ship once R1 is applied. R2–R4 do not touch P1-visible shapes.
