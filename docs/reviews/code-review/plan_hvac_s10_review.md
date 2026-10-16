# Plan review: PLANNING_hvac_s10_stale_range.md (Tier 2, one adversarial plan review)

**Reviewer:** ura-reviewer (plan review), 2026-10-15, `develop` @ `0256f77e1`.
**Read first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, all of it (§0-§12 including the §10 ledger C1-C37). None of the findings below re-asserts a ledger claim.
**Verdict: FIX-REQUIRED.** The proposed gate already exists in code, and it would not have caught the incident on the card.

## Findings

### F1 CRITICAL: D1 duplicates existing behaviour (Bug Class #53, missed consumer)
`hvac.py:2253-2261`: every full cycle seeds `_zones_written_this_cycle` at cycle entry with every zone whose `_zone_last_s1_write` timestamp is less than `SUPPRESS_TTL_SECONDS_PRESET` (120 s) old. S10 skip-matrix step 3 (`hvac.py:4393`, `zone_id in self._zones_written_this_cycle` → `s1_same_tick`) reads that set. Step 3 also runs again right before the call (`hvac.py:4664`). So the plan's gate, "skip while `now - _zone_last_s1_write[Z].ts < 120 s`", is already enforced today with the same anchor and the same window. The plan's prior-art table cites `_zone_last_s1_write` only at :631 and :3929-3933. It misses the consumers at `hvac.py:2259` (this seeding) and `hvac.py:5594` (`_zone_last_write_is_away`). The plan's "Effect" paragraph also gets step 3 wrong: it does not cover only "the same tick".

### F2 CRITICAL: the fix does not cover the evidence it was written for
Card evidence (`kanban.data.yaml`, `evidence_2026_10_14`): S1 changed zone_3 from sleep to away at 05:43:52Z. S10 ran 300 s later, on the next periodic tick. The legs stayed stale for about 422 s (until 00:50:54 CDT). A 120 s window ends well before the 300 s tick, so INV-S10-COOLDOWN would have allowed exactly that write. Section "Effect" says the same thing ("first full tick after ... next 5-min tick"), so the plan contradicts itself. Q3 ("raise to 300 s if measured") still falls short, because the next periodic tick lands at about 300 s plus jitter, and the measured staleness was about 422 s. If a time window is the fix, it has to be sized from the measured staleness distribution, which means running the plan's own probe BEFORE choosing the number, and it has to be at least 1.5 ticks long.

### F3 HIGH: the mechanism contradicts ha_carrier source and the evidence
- The plan says the legs come from the lagging status feed. `ha_carrier/climate.py:222-230` reads the setpoints from `_current_activity()`, which is the CONFIG activity of the type the status names (upstream #408, state-of-play §5 row). It falls back to `_status_zone` (stale status setpoints) only when that activity cannot be resolved.
- The plan says "the write LANDS correctly". The card says `wire_ok false`, `HomeAssistantError`, returned in under 1 ms. That is a local raise before any API call. `async_set_activity_setpoint` raises "Current activity unavailable" when `_current_activity()` is None (`climate.py:551-553`).
- A single hypothesis explains both observations (stale legs AND an instant local rejection): during the transition `current_status_activity()` returns None, so the legs fall back to the stale `_status_zone` values and the service raises. This is UNVERIFIED. The plan must test it, or any alternative, against the recorder before choosing a fix. Its acceptance criteria must also be able to tell "stale legs + landed write" apart from "unresolvable activity + rejected write".

### F4 HIGH: the harm is understated, and the real harm escalates
- **Failure-counter latch.** The rejected write is `FAILED emit_raised`, so `rec["failures"] += 1` (`hvac.py:4718-4726`). `_s10_success` resets only `writes` (`hvac.py:4779`). Failures clear only when the value changes. Live store `.storage/universal_room_automation.hvac_zone_state`: `zone_3 away|apply failures: 1`. Two more preset changes into away with the same race would hit `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` = 3. The result is a `call_failed` latch plus an NM, and S10 stops managing away on zone_3.
- **Snapshot poisoning.** Step 9 (`hvac.py:4536-4544`) captures the original only once per (zone, preset) and never overwrites it. If the first visit to a preset happens while the legs are stale, the PREVIOUS preset's range is persisted as this preset's device original. Every later restore (switch OFF, or ruling A6 rollout removal) would then write the wrong range into the profile. This did not happen on zone_3: its snapshots date from 10-13. It is reachable when zones 1 and 2 are rolled out, which is when the plan says the fix matters.
- The plan must name both harms and add an acceptance criterion for each.

### F5 HIGH: the anchor is S1-only, but other writers change the preset (question 4)
These sites also change the preset and do not stamp `_zone_last_s1_write`: S4 arrester revert, S7 nudge restore, the AC-reset preset restore (`_restore_after_reset` / `_verify_restore`), egress resume, the excursion auto-return (`hvac_excursion.py` `_auto_return`), S11/S13 presets-only returns, a human changing the preset in the app or at the wall, and the Bryant schedule (zones 2/3 still run schedules, §5). After any of these the same stale or unresolvable read can occur. Q2 scopes this out without evidence. Recommendation: anchor on the OBSERVED preset transition. One option is a per-zone "preset_mode / hold_activity last changed" stamp kept where the zone climate state is already read (`hvac_zones.update_zone_climate_state`). That covers every writer, including a person. Keep the S1 stamp as a second input. Alternatively, make the gate a readiness predicate instead of a timer, for example "the adapter can resolve the current activity". Neither option suppresses a legitimate first write: a cooldown only delays it. Restore is also delayed, which is acceptable.

### F6 MEDIUM: the invariant is falsifiable but already holds, and the acceptance criteria do not discriminate
INV-S10-COOLDOWN at 120 s is true on today's code (F1). The "Live" criterion ("no S10 write on the same tick as the S1 `preset_change` row") is already guaranteed by step 3. Unit tests (a) through (e) would pass against a no-op build, because step 3 already returns `s1_same_tick` in the same window. That makes them hollow (Bug Class #62). Restate the invariant over the observed-staleness window and the failure-counter and snapshot outcomes, for example: "no S10 wire attempt and no snapshot capture for Z while its activity is unresolved or within W of an observed preset transition". Then write tests that fail on current `develop`.

### F7 MEDIUM: rung, tier and knob
Rung 1 is fine. But `S10_POST_PRESET_CHANGE_COOLDOWN_S = SUPPRESS_TTL_SECONDS_PRESET` couples two concepts: arrester echo suppression and Carrier read staleness. They are equal today only by coincidence (Bug Class #63). The S10 window needs its own measured value. Tier 2 is acceptable as long as the change stays inside S10. If it adds a stamp in `hvac_zones` or changes the failure-counter semantics, re-assess the tier, since that is a ripple into the arrester or zone state.

### F8 LOW: baseline query and doc audit
- The probe SQL groups by `zone`. `climate_write` rows carry `zone_id` inside `details_json`; verify the column before relying on it.
- The plan's doc-correction item 5 promised to audit any remaining "not deployed" wording. That audit was not done: §3.3 line 201 and the §4.1 `emit_set_activity_setpoint` row (line 214) still say "built 2026-10-05, not deployed".
- The S10-row residual added to the state-of-play (§4.2) repeats the F3 mechanism ("status-feed setpoints", "redundant write"). Correct it, or mark it UNVERIFIED, when F3 is resolved.
- Code comments `hvac.py` ~3938 and ~5592 still refer to the zone_1 away feed-split as "§9.7". That section is now §9.9.

## Re-enumeration (question 3)
- **S10 wire sites:** one, `strategy.set_preset_range` in `_s10_write_one` (`hvac.py` ~4677), reached from `_s10_pass` in apply and restore modes, which `_async_apply_preset_overrides` calls on full ticks only, outside observation mode (`hvac.py:4100-4101`).
- **S10 capture sites:** step 9 snapshot (:4536), the post-await re-check (:4642), and the limit-view read (:4603).
- **Skip-matrix call sites:** :4475 (pass) and :4664 (pre-call). A new skip step would cover both, as the plan says.
- **`_zone_last_s1_write` consumers:** :2259 (cycle seeding, missed by the plan), :3929-3933 (writer), :5304 docstring, :5594 (away-edge key).

## State-of-play corrections in commit 0256f77e1 (spot-checked)
| # | Correction | Result | Evidence |
|---|---|---|---|
| 1 | §1: CPR live on zone_3 | PASS | Live `core.config_entries`: CM options `hvac_s10_rollout_zone_ids = ['zone_3']`. `core.restore_state`: switch `on` |
| 2 | §8 switch row | PASS | Same evidence; agrees with the §3.3 LIVE-STATE NOTE |
| 3 | Second 9.7 renumbered to 9.9 | PASS (doc) | The remaining §9.7 references in the doc are the CPR-blocker 9.7, which is correct. Two stale code-comment references remain (F8) |
| 4 | C37 ledger row | PASS | |
| 5 | §4.2 S10 residual note | PARTIAL | Says "SHIPPED v5.103.39" correctly, but the residual mechanism text is wrong or unverified (F3) |

## Must-fix before build
F1, F2, F3, F4, F5, F6. F7 and F8 should be fixed in the same pass.

---

## Rev 2 re-review (2026-10-15, `develop` @ `7668ebe0c`)

**Reviewer:** ura-reviewer (plan re-review). Read `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely first (§0-§12, ledger C1-C37); no ledger claim re-asserted.
**Verdict: FIX-REQUIRED.** The direction is right: an observed-change anchor, its own constant, and the failure reset. But D1's observer site cannot do what the plan says, and D2 is placed where it misses the case it is meant to fix. Both are plan-text fixes, about 30 minutes of work, with no redesign.

### Prior findings: status
| # | Status | Note |
|---|---|---|
| F1 | RESOLVED | Rev 1 gate withdrawn; consumers :2258-2261 / :5594 listed. |
| F2 | RESOLVED (n=1 caveat) | 600 s own constant; Q3 revisit criteria stated. See R5 for the effective delay. |
| F3 | RESOLVED | Mechanism marked PARTIAL/UNVERIFIED (n=1); matches `ha_carrier/climate.py:551-553`. |
| F4 | RESOLVED in text, PARTIAL in fix | Both harms named. D2's placement does not cover the observed APPLIED case (R2). |
| F5 | PARTIAL | Anchor is now observed, but the observer as specified cannot see `hold_activity` (R1). |
| F6 | PARTIAL | Invariants falsifiable; T9 and T12 are defective (R6). |
| F7 | RESOLVED | `S10_POST_PRESET_CHANGE_SETTLE_S` uncoupled. |
| F8 | RESOLVED | SQL uses `json_extract(details_json,'$.zone_id')`; doc labels fixed in `1480811ba`; two code comments carried to D3. |

### New findings

**R1 HIGH: the observer site does not read `hold_activity`, and ZoneManager has no route to the coordinator.**
- `hvac_zones.py:651-670` `update_zone_climate_state` sets `zone.preset_mode` (`preset_of_for`, :666) and nothing about `hold_activity`. `grep hold_activity hvac_zones.py` returns 0 hits.
- `ZoneManager.__init__(self, hass)` (:279) holds no coordinator reference, so the plan's `coordinator._note_observed_preset_change(...)` call needs new wiring the plan does not specify.
- Fix in the plan: read `hold_activity` at :666 (raw attribute, Carrier only), keep the prior values and the stamp on `ZoneState` (or ZoneManager), and have `_s10_zone_skip_reason` read `zone.<stamp>`. That keeps the map off the coordinator and removes the back-reference.

**R2 HIGH: D2 in `_s10_success` never runs on APPLIED, so INV-S10-LATCH-RESET and T9 cannot hold as written.**
- `_s10_write_one` step 12 (`hvac.py:~4688-4706`): APPLIED increments `writes` and never calls `_s10_success`.
- `_s10_success` runs only on SKIPPED_ALREADY_CORRECT (:~4707) and on a matching view at the limit (:~4596).
- So "APPLIED ... ALSO resets failures" (the INV text, D2 text, T9) is false for the proposed one-line change. The incident record (failure, then APPLIED, store `failures:1 writes:2`) would keep `failures=1` until a later SKIPPED_ALREADY_CORRECT.
- Pick one and say it explicitly:
  - (i) reset only on confirmed success. This matches the A4 semantics, where APPLIED is a wire return and not a confirmation. Restate the INV and T9 to match.
  - (ii) also reset on APPLIED. Justify it: alternating raise/APPLIED then never latches `call_failed`, but `writes` still reaches 3 and the limit path latches `not_sticking` (:4590), so the latch is not defeated.
- I recommend (i).

**R3 MEDIUM: the first observation after a restart is unspecified, and the default makes it stamp.**
- `ZoneState.preset_mode` defaults to `""` (`hvac_zones.py:137`), and the boot read (`hvac.py:1555`) changes it from `""` to the live preset. A literal "differs from previous RAM copy" therefore stamps every zone at every boot, and S10 is held for 600 s (2-3 ticks) after each restart.
- The plan's "boot/reload = empty map (correct)" implies no stamp but does not say how to prevent one.
- State the rule: the first readable observation seeds the copy without stamping, or it stamps on purpose. A boot read can land inside a real Carrier transition, which argues for stamping and accepting the 600 s delay. Either is acceptable if stated.
- The `unavailable` early return (:658) keeps the copy across outages. `unknown` does NOT return early (it falls to `preset_of_for(...,"")` and becomes `""`), so an unknown flap produces two stamps. Specify this too, for example by treating `unknown` and `""` as unreadable and not updating the copy.

**R4 MEDIUM: on a flapping feed the settle re-arms continuously (suppression with no discharge).**
- §9.9 measured zone_1 at about 46 status home/away flips in 4 h (about every 5 min). Every flip re-stamps, so 600 s never elapses and S10 never runs on that zone while the split persists. The nudge cadence (about 25 min, two transitions each) also eats about 10 of every 25 min on zones with nudges.
- During the §9.9 split, S10's `_confirmed_on` already fails (it needs both feeds to name the preset). And the only both-away windows are the ha_carrier optimistic-guard windows, the exact source of poisoned snapshots. So starving S10 there is arguably correct.
- But the plan must state this outcome and give the suppression a discharge or trip-wire: a counter or `_s10_last_outcome` age, or an anomaly or NM when a rollout zone has been in `post_preset_change_settle` for more than N hours. That way a permanently blocked zone (the likely zone_1 rollout case) is visible and not silent.
- Bryant schedule chatter (Q2) is low-rate under `infinite_holds` and is not a concern.
- Sampling is per pass (full tick :2308, fast runs :5765, pre-arrival :7179), so an A to B to A flip inside one pass is invisible. That is acceptable, but state it.

**R5 LOW: the effective delay is up to 15 min, not about 10, and the observed timestamp lags the real transition.**
- S1 writes after `update_all_zones` in the same cycle, so an S1 change is first observed on the NEXT tick (+300 s). Settle then runs 600 s from that observation, and the `<` comparison against a fixed 300 s interval can need one more tick.
- S10 after an S1 change therefore lands at about 900-1200 s. That is fine (conservative against the 422 s measurement), but the Live criterion and Effect paragraph should say so.

**R6 MEDIUM: test defects.**
- **T9** asserts a reset on APPLIED via `_s10_success`, which is unreachable (R2). Rewrite it to match the chosen option.
- **T12** exercises ha_carrier internals (`current_status_activity`) that URA tests cannot drive. The test would be a mock asserting its own setup, a hollow anchor (Bug Class #62). Its oracle is also left open ("possible_wrong_profile ... or similar"), and it would pass on `develop`, which contradicts the section header. Drop it, or turn it into a recorder probe in the falsifier runbook.
- Missing tests:
  - (a) the observer itself: a real `hass.states` change in `preset_mode` and in `hold_activity` → `update_zone_climate_state` stamps. T8 writes the map directly, so it does not prove the observer is wired (wire-in anchor rule).
  - (b) R3 boot and unknown behaviour.
  - (c) an R4 repeated-flip test showing the trip-wire fires.
  - (d) a mutation anchor for the skip-step ORDER: settle before `s1_same_tick`.
- T1-T8, T10 and T11 do fail on `develop`, because the step and the map do not exist.

**R7 LOW: tier and ecobee.**
- Tier 2-DB (operator-elevated) is appropriate. Once R1 puts the stamp in `ZoneState` and not on the coordinator, the ripple is smaller.
- The plan calls the ecobee path a "harmless no-op skip", which is not accurate. An option-C select hold flips `preset_of` to `manual` when its settled legs drift, and that stamps and delays ecobee S10 storage. No ecobee zone runs a coordinator today, so this is LOW. Say "delays" rather than "no-op".

### D2 reachable defeat case (question 3)
Under option (i), the latch is defeated only if raises alternate with a SKIPPED_ALREADY_CORRECT whose view is itself wrong. That happens when, during an unresolvable-activity window, the `_status_zone` fallback legs happen to equal the desired range. The 7800 s retry spacing after a wire attempt (:4587) makes that pairing very unlikely, and in that case the device view matches, so the harm is nil. A persistently failing preset, one that raises on every attempt, never reaches a success, so it still latches at 3. Accept.

### Must-fix before build
R1, R2, R3, R4, R6. R5 and R7 should be fixed in the same pass.
