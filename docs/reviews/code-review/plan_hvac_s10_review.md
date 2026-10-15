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
