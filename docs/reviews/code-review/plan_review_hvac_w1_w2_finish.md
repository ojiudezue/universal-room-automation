# Plan review — PLANNING_hvac_w1_w2_finish.md (HVAC W1/W2 finish)

**Reviewer:** ura-reviewer, 2026-09-28. One adversarial plan review before build (Tier 2-DB plus a 4th D pass at code review, per ruling Q6).
**Framing:** completeness plus adversarial build-prediction ("what will the builder get wrong reading this?").
**Base:** `develop` @`37b678966`. Read-only; every claim below re-verified in source.
**Mandatory read done:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely (lines 1-472, §0-§12, §9e, §10). The §10 ledger ends at **C25**; there is no C26. This review re-asserts no §10 claim.

**Verdict: FIX-PLAN-FIRST.** 5 HIGH, 10 MEDIUM, 7 LOW. The mechanism choices hold up: ring in the funnel, pure classifier, presets-only pre-arrival end, and the single-write pre-arrival from baseline. The problems are what a builder will get wrong from the text as written:
- the classifier's None/mode semantics;
- the D2c precedence short-circuit;
- an incoherent case-A baseline;
- a latch that the next booking erases;
- Part C not re-scoped to the Q5 ruling.

---

## HIGH

**H1 — D1 books hvac_mode transitions as human setpoint changes.** Class: #53 / enum-None mismatch.
- **What the plan says:** rule step 2 ("legs whose value differs, None-safe") does not define None. The non-goal "a human `hvac_mode` change within manual" is not enforced by the rule.
- **What the code does:** `ha_carrier/climate.py:231-240` sets `target_temp_high/low = None` in any mode other than HEAT_COOL (off, cool, heat, fan_only).
- **Repro (legal config):**
  1. zone_2 is in a pre-arrival pre-cool: BANKING row live, `manual` 74/69, `heat_cool`.
  2. An egress-configured door opens. `hvac_egress.py:721` writes `set_hvac_mode off` with NO `suppress()`. EGRESS `begin_excursion` is rejected by the BANKING row (`hvac_excursion.py:805-813`), but the write still runs.
  3. The echo is `manual→manual` with high `74→None` and low `69→None`. No ring entry holds None, so the classifier returns `"human"`.
  4. D2a then ends the borrow with `human_interrupt`, sets the latch and inflates `override_count_today`. INV-A5 is falsified.
- **Same class:** AC hard-reset off/on (`hvac_override.py:4290/4412/4451`, unsuppressed mode writes) and a human switching mode.
- **Fix:** a change is within-manual only if `old.state == new.state == "heat_cool"` and both legs are numeric on both sides; otherwise return `"none"`. Add `test_classify_mode_change_is_none` (off↔heat_cool, cool).

**H2 — D2c cannot re-dispatch as written.** Class: build prediction.
- **The short-circuit:** `_borrow_row` (`hvac_override.py:3274`) and `_comp_live` (`:3282`) are computed before any D2 logic. A compromise in flight has both a live COMPROMISE row and a `_compromise_timers` entry, and D2c only *schedules* `_compromise_release_lease`. So precedence reaches `elif _borrow_row or _comp_live: "borrow_active"` (`:3317`) and returns at `:3390`. Nothing is re-dispatched.
- **Why the builder will miss it:** the plan forces `_borrow_row=False` only in D2a (BANKING/PREHEAT).
- **Fix:** D2c must force `_borrow_row` and `_comp_live` to False and rebuild `gate_snapshot`. `test_human_change_during_compromise_redispatches_against_original_baseline` must assert a new grace or compromise timer and the `override_detected` `gated_reason` is not `borrow_active`.

**H3 — Case A pairs a revert target and a delta basis from different presets.** Class: #63 (coincidental-equality concept split). The fixture outcome is also unspecified.
- **Where the values come from:**
  - S12 snapshots `pre_preset` from the live entity: `away` for a pre-arrival.
  - It then overwrites `pre_target_low/high` with the resolver baseline (`hvac_predict.py:1165-1168`), i.e. the house-target (home) values.
  - Case A therefore compares the human against home 76 and reverts to `away` 80.
- **Incoherent outcome:** a human 78 gives +2 vs 76, which is a normal override. The arrester compromises at 77 (toward home), then pins `away`. That is the exact incoherence P3's own rationale rejects.
- **The 09-28 fixture:** 71 vs 76 = 5 °F, which is severe (`OVERRIDE_SEVERE_DELTA=3`). If lighting-unoccupied, the comfort rung fails at `:2718-2722`. After `OVERRIDE_SEVERE_GRACE_MINUTES=2`, S4 pins `away` at about 22:17:40.
- **What is missing:** that is consistent with Q4, but the plan never states it. No acceptance criterion names the fixture's expected write sequence.
- **Fix:**
  1. Pick ONE coherent pair: either (`pre_preset`, that preset's seasonal setpoints) or (resolver preset, resolver setpoints).
  2. Add a replay AC: "09-28 zone_2: 22:15:40 71 → `override_detected within_manual` → borrow ended → [grace/compromise/revert per the chosen pair] → S4 `<preset>` at ~22:17:40".
  3. Put that line in front of the operator as the concrete meaning of "We end and revert".

**H4 — The D2e latch is erased by the next booking.** Class: #53 / suppression-needs-discharge.
- **The erase:** `self._last_detection[entity_id] = _detect_rec` (`hvac_override.py:3363`) replaces the whole record on every `override_detected`. After the interrupt, the borrow is gone. A second human tweak in the same manual episode is booked as case C with no `human_interrupt` key, so the latch is lost.
- **Repro:**
  1. Energy pre-cool (auto_pv_tiered, occupied zone_1): BANKING row live at 73.
  2. Human sets 71: interrupt, latch set, comfort grant.
  3. Human sets 70 one minute later: new record, latch gone.
  4. After the 20-min grant, the next tick runs `_execute_zone_pre_cool` (`hvac_predict.py:598`). It begins a new BANKING and writes `max(70-3, floor)` over the human. INV-A.2 is falsified.
- **Fix:** a separate `_interrupt_latch: set[entity_id]`, popped only at the `:3112` episode boundary, or carry the flag forward within the episode. Add a test with two consecutive human changes.

**H5 — Part C is not scoped to the Q5 ruling.** Class: scope growth by build prediction.
- **Stale text the builder will follow:**
  - §PART C still specifies C1, C2 and C4 as deliverables, with tests, live criteria and INV-C (a)/(c).
  - The C.0 / cross-part note still ties Part A to C4.
  - §6 still frames reviewers on "C1 shed dominance" and "Part C truth tables".
  - The builder will build all four.
- **Revival trigger:** §8 says "first measured reloading-room harm", which cannot be evaluated as written.
- **Fix:**
  1. Move C1/C2/C4 to a PARKED appendix with an evaluable trigger. Examples: a P6 re-run showing at least one transient-room sample coincident with a D5 coast / D6 / row-11 decision, or an anomaly trip-wire wired to NM.
  2. Restate INV-C as (b) only.
  3. Fix §6.

## MEDIUM

**M1 — Two write sites are missing from the D2b table (INV-A.1 falsifier).** Class: #53.
- S12 (`begin` `hvac_predict.py:1154`, then write `:1193`) and S13 (`:1445`, then `:1482`) both await `save_excursion_row` inside `begin_excursion` (`hvac_excursion.py:863`) before writing.
- A human interrupt landing in that await returns the brand-new token. The write then goes out anyway with `excursion_id=B.id`, and `_banking_excursion_tokens` registers a returned token.
- **Fix:** add `if token is not None and token.returned: skip` immediately before each emit.

**M2 — D4b is not applied to S13.** Class: #53 (one-missed-site sibling of the plan's own §0 finding).
- When `begin` returns None (foreign row), S13 still writes (`:1482`). `_pt is None`, so no return timer is registered (`:1504`).
- Result: an un-returned pre-heat low over a live compromise or nudge.
- **Fix:** apply the same foreign-row guard.

**M3 — Orphan COMPROMISE rows are ended by neither D2a nor D2c.** Class: #53.
- **How orphans arise:**
  - boot rehydrate (`hvac_excursion.py:1240-1256`: no arrester token or timer);
  - the `enabled=False` setter (`hvac_override.py:3070-3083` cancels compromise timers but never releases the row);
  - arrester teardown followed by a reload.
- **Consequence:** a human change is booked `borrow_active` until `stale_ts`, so INV-A.4 is false. These paths are also absent from §3.
- **Fix:** treat a COMPROMISE row with no `_compromise_timers` entry as D2a-endable, with a case-C baseline. List the three paths in §3.

**M4 — C3's edit shape would break the v5.103.20 back-fill.**
- The `else:` at `hvac_zones.py:970` also holds the v5.103.20 `last_occupied_time` back-fill (`:973+`).
- The plan's `elif not self.is_zone_transient_blocked(...)` would skip the back-fill during a transient, changing exit-timer / INV-2 behaviour.
- **Fix:** specify guarding only the single assignment inside the `else`. The plan's cite `:970-972` is too narrow.

**M5 — The pre-arrival borrow can still reach `lease_expiry`.**
- The window counts from the LAST trigger (`_pre_arrival_start` reset at `hvac.py:5823`; D4 keeps this). The borrow's age counts from the first begin.
- The knob max is 120 min, equal to `EXCURSION_LEASE_MAX_S` (7200 s). The sweep runs every 60 s (`EXCURSION_AUTORELEASE_SWEEP_S`); D3 runs on the 5-min tick.
- **Repro:** knob = 120, no arrival. The sweep at 7200 s beats the next tick, falsifying INV-B.2. Repeated triggers also extend any window.
- **Fix:** D3 ends the borrow when its age reaches the window, and the knob max stays at or below 110.

**M6 — D5 knob wiring is under-specified.** Class: #32, and the parent-reload hazard.
- The Return Window precedent spans several `__init__.py` sites, not only `number.py:511-587`:
  - the setup read (`:3898`);
  - the import (`:6201`);
  - `OPTIONS_RELOAD_SUPPRESS_KEYS` (`:6859`);
  - the apply-in-place set (`:7287`);
  - the dispatch (`:7389`).
- If the key is missing from the suppress set, a knob turn reloads the CM.
- **Also state:**
  - the CONF home (`hvac_const.py` next to `CONF_PRE_ARRIVAL_SOURCES`);
  - whether the knob also goes on the HVAC settings form (the knob-52 precedent put it on both).

**M7 — The P1 probe cannot discriminate as specified.**
- **Data span:** `climate_write` rows exist only since v5.103.16 (live 2026-09-26). `--days 14` would count every earlier echo as "unmatched" and trigger a false stop. It also leaves only about 2 days of data.
- **Fix, window:** bound P1 to 09-26 onward, state a minimum N, or use `ac_ramp_events` values for older nudges.
- **Fix, rule:** P1 must apply the classifier's changed-legs rule, not a whole-`values_after` match.
- **Fix, late arrivals:** split out within-manual changes arriving more than 5 min after a write. That covers the end-of-guard full read in ha_carrier (C16/C21), which can present a cloud-normalised value URA never sent. Neither the 15 s / 120 s windows nor ring depth addresses those, so the plan needs a named remediation branch beyond "raise depth".

**M8 — Two invariants are mis-stated, so D and C would "falsify" legal behaviour.**
- INV-A.3 is false under D48/D52: `check_ac_reset` skips only `_override_active` zones, so S5 nudge starts and hard resets proceed on a manual zone. The egress mode write and the heat_cool enforcer also qualify.
- INV-B.2 omits `stale_boot_release` (a restart mid-pre-arrival, §4) and the CM `s12_banking_wire_failed` release.
- **Fix:** restate both with explicit carve-outs.

**M9 — Case C is a behaviour change with no test or AC.**
- Case C is a plain within-manual human change with no borrow and no episode.
- The arrester now acts on every human fine-tune of a manual hold, comparing against the resolver baseline. That reaches beyond the borrow scope.
- The resolver-None branch ("book, don't dispatch") is also untested.
- **Fix:** add tests for both branches and a README line.

**M10 — The fast-run D3 is cross-zone.**
- `_expire_pre_arrival_zones` iterates ALL zones (`hvac.py:5865`) even in a zone-scoped fast run. S1 runs with `zone_filter={Z}` (`:4782`).
- D3 can therefore pin zone Y to its snapshot (`away`) on arrival while Y's S1 waits for the next tick. INV-B.3 fails for Y.
- **Fix:** scope D3 to `{Z}` in the fast run, or state and test the cross-zone case.

## LOW

- **L1 — Fixture AC per-row class.** "classifier returns `ura_echo` for 78, 76, 74" is wrong for 78 if the prior preset was `away`. That row is an INTO-manual transition, and rule 1 returns `"none"`. Take the expected class per row from the P1 rows.
- **L2 — Boot seed runs after the listener.** The arrester listener goes live at `hvac.py:1401`; the audit/seed runs at `:1432` after awaits. Seed before any await, or accept and document the window.
- **L3 — Known funnel escapes.** Some URA writes bypass the ring and would be misclassified as human if ever used:
  - the optimizer's raw `climate` call (`optimization.py:3545`, allowlisted via `DYNAMIC_DOMAIN_ALLOWLIST`, L2+ only);
  - AI-rule chained script/scene (`coordinator.py:1104-1137`).

  Name them as INV-A5 carve-outs.
- **L4 — Reason vocabulary.** `HVAC_PRESET_REASONS` (`const.py:1321`) is enforced by `test_v5_103_8_hvac_knobs_and_obs.py`. Any new `reason=` literal from D3 or D2d must be added. Name this in the #22 list.
- **L5 — Latch discharge on a feed flicker.** A status-feed flicker (manual→named→manual, §9.7 / C22) pops `_last_detection` at `:3112` and discharges the latch. Document it.
- **L6 — D2c race.** Cancelling a grace handle whose `_apply_compromise` task is already pending does not stop that task.
- **L7 — Doc hygiene:**
  - there are two "## 8." headings;
  - §6 still says three reviews (Q6 added D);
  - the ring stores `monotonic_ts` but nothing uses it (drop it or define an age bound);
  - INV-A.1 compares `ts_issued`, which is monotonic in the `climate_write` row; use `issued_wallclock`.

---

## Independent re-enumeration (§3 check)

| Surface | Grep result | Plan §3 | Verdict |
|---|---|---|---|
| begin sites | S3 `hvac_override.py:3732`, S5 `:4823`, S12 `hvac_predict.py:1154` (callers `:598`, `:649`), S13 `:1445`, S15 `hvac_egress.py:688`; rehydrate `hvac_excursion.py:1240-1256` | all listed | complete |
| `return_excursion` callers | `hvac_excursion.py:719` (`_auto_return` ← sweep `:765`, boot `:1196`), `:1330` (CM); `hvac_predict.py:1090` (S11), `:1601` (S13); `hvac_egress.py:444/806/886`; `hvac_override.py:4004` (←3843/3861/3880/3973), `:5297`, `:6412`, `:6522` | all listed | complete |
| row mutation outside return | `_reap_stale` `:597-608`, boot `:1194/1209/1255`, test helpers | listed | complete |
| end paths WITHOUT a return (orphaning) | `enabled=False` setter `hvac_override.py:3070-3083`; arrester teardown `:2337`; rehydrated COMPROMISE/PREHEAT with no owner | **absent** | M3 |
| writes after begin with no returned-check | S12 `:1193`, S13 `:1482` | **absent** from D2b | M1 |
| writes over a foreign row | S12 (plan D4b), **S13** | S13 absent | M2 |

**Funnel lint (ground truth, `test_hvac_climate_write_funnel_completeness.py`).** It walks the whole integration and allowlists only `optimization.py`. The ring is therefore complete for `set_temperature` apart from L3's documented escapes. The D1 bypass risk is not unrouted writes. It is echoes that are not `set_temperature` values: mode writes (H1) and cloud-normalised full reads (M7).

**Echo and suppression interplay.**
- A within-manual change inside a window is dropped (`_is_genuine_manual`, `:2662-2667`). That is the safe direction, correctly stated in the plan.
- Egress and hard-reset mode writes open no window.
- The ha_carrier 5-min guard (C16/C21) hides a cloud revert and then releases it on a full read. That arrival can land minutes after any window.

**Knob `35 · Pre-Arrival Window (min)`.**
- Rung 3 is justified: the operator asked for it and it is tuned by observation.
- No collision. The numeric prefixes are group labels, not unique ids: `35 · Pre-Arrival Conditioning` is a switch (`switch.py:4253`), `35 · HVAC Zone Intelligence` is a sensor (`sensor.py:13699`), and no `number.*` uses 35.
- The entity id `number.ura_hvac_coordinator_35_pre_arrival_window_min` matches the knob-52 slug pattern.
- The max value conflicts with the lease cap (M5), and the wiring is under-specified (M6).

**Q5 scoping.** Not done in the body (H5).

## Invariant checklist

| Invariant | Falsifiable? | Status |
|---|---|---|
| INV-A.1 | yes | LEAK: M1 (write after begin), L7 (timestamp) |
| INV-A.2 | yes | LEAK: H4 (latch erased) |
| INV-A.3 | as written, falsified by legal D48/D52 behaviour | RESTATE (M8) |
| INV-A.4 | yes | LEAK: M3 (orphan compromise) |
| INV-A4 (D13) | yes | holds (`_nudge_live` is checked first, `:3307`) |
| INV-A5 | yes | LEAK: H1 (mode echoes), M7 (full-read arrivals), L3 |
| INV-B.1 | yes | holds with D4, plus M1/M2 |
| INV-B.2 | yes | LEAK: M5; RESTATE for `stale_boot_release` (M8) |
| INV-B.3 | yes | LEAK: M10 (fast-run cross-zone) |
| INV-B.4 | yes | holds for S12 via D4b; S13 sibling in M2 |
| INV-C | restate as (b) only | H5, M4 |

## Must-fix before build dispatch

H1, H2, H3 (with the operator-visible fixture outcome), H4, H5, M1-M10.

The LOWs can be fixed in the same plan edit.

## Summary statistics

| Severity | Found |
|---|---|
| HIGH | 5 |
| MEDIUM | 10 |
| LOW | 7 |

| Bug class | Count |
|---|---|
| #53 computed-but-not-consumed / one-missed-site | 6 (H1, H4, M1, M2, M3, M10) |
| #63 coincidental equality / concept split | 1 (H3) |
| #32 options writeback | 1 (M6) |
| #22 enum / vocabulary | 1 (L4) |
| Invariant mis-statement | 1 (M8) |
| Scope / build prediction | 3 (H2, H5, M4) |
| Probe design | 1 (M7) |
