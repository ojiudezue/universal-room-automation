# Plan review #2 (Tier 3, adversarial build-prediction): EC storm Stage E

**Plan:** `docs/planning/PLANNING_ec_storm_stage_e.md` Rev 1 (develop @ 6dd862d15)
**Framing:** "What will the builder get wrong reading this?" Ambiguities, orderings, non-discriminating acceptance, unfalsifiable invariants, config extremes. Completeness re-enumeration is plan review #1's lane; overlaps are noted only where a missed site is what the builder would trip on.
**Code read:** `inclement.py` (match_product, build_record, update_alert_memory, classify, `_apply_prepare`, `_decide_hold`), `energy_const.py:690-845`, `energy_battery.py` (`_inclement_config` call path ~2738-2835, `_forecast_confirmed_ids` 2909, pre-onset buy 6340-6410, `_registered_floor` 6831, narration 7057), `energy.py` (ledger 9538-9590, obs-mode latch rollback 9410-9425), `energy_outage_ledger.py:262-280`, `__init__.py` reload/live-attr key sets, `weather_manager.py:89`.

**Verdict: FIX-PLAN.** 2 CRITICAL, 5 HIGH, 6 MEDIUM, 3 LOW. E2 cannot be built as written, and the INV-7(e) golden contradicts the cycle's own E2 change.

---

## CRITICAL

**C1. E2 cannot be built as written: the buy is keyed on `preonset_floor` being non-None.**
Evidence: the pre-onset buy fires only when `decision.preonset_precharge and decision.preonset_floor is not None` (`energy_battery.py:6351-6352`), and it emits `reserve_level=decision.preonset_floor` (`:6385`). The latch becomes `engaged` only after that buy is commanded (`:6403-6409`). The plan says the floor gate goes in `_apply_prepare` and "the registration site in determine_mode stays unchanged and reads `decision.preonset_floor`" (§4).
- Build 1: the gate sets `preonset_floor=None` outside `[s−4h, s)`. The buy at 10:00 for a 21:00 Onset never fires (the `:6352` conjunct is False), so the latch never engages and floor-follows-buy can't happen. The "Verify (floor-follows-buy)" line fails. If the test is written loosely it could pass on a fixture that pre-seeds the latch as `engaged`.
- Build 2: `preonset_floor` stays populated so the buy works, and the gate goes elsewhere. `_registered_floor` (`:6839`), the narration (`:7057`), the `inclement_preonset` attr (`:3137`) and the ledger column `tick_preonset_floor` (`energy.py:9544`) all read the same field, so the floor still registers 12 h out. Either INV-8 is broken or its own falsifier fires.
**Plan fix:** split the concept into two fields, `preonset_target` (the buy and floor value, populated across the 12 h buy horizon) and `preonset_floor` (the registered floor, None outside the floor window unless the latch is engaged or reached). Or add a bool `preonset_floor_active`. Name every reader and say which field each one reads: `:6352`/`:6385` read the target, while `_registered_floor`, `:7057`, `:3137` and `energy.py:9544` read the registered floor. Add a mutation drill: make `_registered_floor` read the target, and the INV-8 repro must go RED.

**C2. The INV-7(e) zero-override golden contradicts E2, and its capture point is stated two ways.**
Evidence: INV-7(e) says that with zero overrides "every classification, hold and buy decision is byte-identical to v5.103.69", and that the only allowed diff is the E0 rows. E2 ships in the same cycle and changes the prepare floor for every alert 4-12 h before Onset, with zero overrides. §INV-7(e) and the E1 acceptance say the golden is captured "on the v5.103.69 tag before any Stage E code". §8 says "Golden captured after E0, before E1/E2 code."
Predicted builder error: either (a) the golden matrix has no time-to-Onset axis, so E2 never shows up and the golden proves nothing about prepare, or (b) the matrix covers prepare at 4-12 h, the build turns RED, and the builder widens the "expected diff" by hand. That is the same class of hand-edited oracle the golden exists to stop.
**Plan fix:** choose one capture point. It should be the v5.103.69 tag, from a worktree, written as a committed JSON fixture by a script that is itself committed. Define the projection: which `InclementDecision` and `AlertClassification` fields are compared, since adding new fields such as `unlisted` or `floor_from` changes the dataclass repr and makes "byte-identical" meaningless otherwise. Define the matrix axes fully: product × window position {active, prepare <4 h, prepare 4-12 h, polygon in/out of cap} × TOU {bottom, top} × SOC {None, 30, 95} × condition {calm, stormy ≥2} × `watch_requires_corroboration` {T, F} × option × forecast {T, F, None}. Enumerate the expected diff as an explicit list of record keys: the E0 rows plus the E2 "prepare 4-12 h → preonset_floor None" cells. Any other diff is RED. Scope INV-7(e) to "classification + hold + buy" and assign the prepare-floor cells to INV-8.

---

## HIGH

**H1. The INV-7(c) cap leaks through `watch_requires_corroboration=False`, which is a legal options value.**
Evidence: `corroborated = (not self._watch_requires_corroboration) or (condition…) or forecast_corroborates` (`inclement.py:1102`). The key is a CM option (`CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION`, `energy_const.py:625`, read at `energy_battery.py:2681`). The plan caps only the condition leg.
Repro: corroboration option False, operator adds `Flood Watch` to hold, bottom rate. The watch counts as corroborated and returns `watch_corroborated_offpeak_full_hold`. At top rate with an unrecoverable horizon it returns `watch_corroborated_not_recoverable_full_hold`. INV-7(c) "never exceeds partial_hold" is false.
**Plan fix:** the cap is "an unlisted record never counts as corroborated by any leg", which covers the `not requires` leg as well. Add the extreme `watch_requires_corroboration=False` to the D target list and to `test_unlisted_product_capped_partial_hold`.

**H2. Corroboration is computed per tier, not per record. "Add `and not rec_unlisted`" has no record to bind to.**
Evidence: `_decide_hold` computes one `corroborated` for the tier (`:1095-1104`). There is no `rec` in scope for the condition leg. Predicted build: `and not any(r.unlisted for r in hold_alerts)`, which uncorroborates a real Winter Storm Watch whenever an unlisted Flood Watch is co-active. That is a demotion of a table product, which INV-7 says the selection can never do. The alternative `all(...)` is what the plan intends, but it is not written down.
**Plan fix:** specify "condition and the no-requirement leg corroborate the tier iff at least one active **listed** watch record exists." Add a mixed fixture (WSW-Watch plus Flood Watch, pouring, top rate → identical to WSW-Watch alone).

**H3. Overrides have no defined path into `match_product`, and there is a third caller the plan does not list.**
Evidence: `match_product` is a pure module function with no config parameter. Its callers are `classify` (`:495`), `build_record` (`:326`), **and `energy_outage_ledger.py:271`**, which writes `nws_alert.ura_class`. §4 says "its two callers". `update_alert_memory` reaches it via `build_record` (`:403`). `AlertClassifier()` is built with no arguments (`energy_battery.py:2749`).
Predicted build: a module global set from `_inclement_config` (hidden mutable state, ordering-dependent across ticks and across the ledger's object), or a parameter added to `classify` but not to `update_alert_memory` or the ledger. Then (a) a hold-added unlisted product is never admitted to D-B3 memory, so it is lost on a feed dropout, and (b) the ledger records the table class. That breaks the plan's own §3 claim ("ledger records the effective class") and the E0/E1 Live discriminator.
**Plan fix:** thread an explicit `selection` argument through `match_product`, `build_record`, `update_alert_memory`, `AlertClassifier(selection=…)` and the ledger call. Name the ledger's source of the selection (it runs outside the battery tick). Ban a module global. Add `test_selection_overlay_applies_in_memory_admission` and `…_in_ledger` beside the existing `build_record` anchor. Also: a synthetic unlisted row has code None, so any alert carrying an NWSCode would emit an `observed_code` drift row (`:303-306`). State that unlisted rows skip drift.

**H4. Buy ⊆ hold and the family rule are enforced only in the form, but INV-7 claims them "for every legal stored value".**
Evidence: E1.4 stores deltas against table defaults, and E1.1 validates only on submit. Repro: the operator stores `buy_added=["Tornado Watch"]`. A later reviewed table edit (E0-style, which the plan expects to reach every install) makes Tornado Watch not a default hold. Effective buy is now not a subset of effective hold, and no form was submitted. The same happens with a hand-edited `.storage`.
**Plan fix:** at runtime, compute `effective_buy = (default_buy − buy_removed + buy_added) ∩ effective_hold`, filtered to rows with a family or polygon. The validator stays for UX. Add a test that seeds the illegal stored combination directly and asserts no buy.

**H5. Retired table names are not in the choice list, so "submit defaults unchanged stores four empty lists" fails.**
Evidence: the defaults are derived from the table, which keeps Hard Freeze and Wind Chill (KEEP+DOCUMENT, E0). The choices are `NWS_WEATHER_EVENT_NAMES`, which excludes them (that is the point of `test_vocab_snapshot_covers_table`'s retired list). A multi-select default containing values outside its options is either rejected on submit or dropped silently. If dropped, `hold_removed` = the retired names, which is a stored override the operator never made.
**Plan fix:** compute defaults and deltas over `table_names ∩ choices`, and treat retired rows as outside the selection entirely (always table behaviour). Or make choices = vocabulary ∪ table names. Pin it with the "submit defaults → four empty lists" test, run against the real flow handler.

---

## MEDIUM

**M1. The reload-suppress set alone is not enough.** The four keys also need `_NO_LIVE_ATTR_KEYS` (`__init__.py:7353`; the consumer at `:7982`). The house comment at `:6982-6984` records that two NM cycles tripped on exactly this omission. The plan names only `OPTIONS_RELOAD_SUPPRESS_KEYS`. Fix: name both sets and test membership in both.

**M2. The E2 key alert is ambiguous with more than one prepare alert.** `_apply_prepare` keys on `key_row` (the earliest row of the highest class) but sets `pstart = min(start over all prep)` (`:957-963`). Example: a warn 10 h out and a watch 3 h out. A gate on `key_row.start` gives no floor, although a hold-class alert starts in 3 h. A gate on `pstart` gives the warn-level floor 80, 7 h early for the warn. The latch is keyed on `key_id`, so floor-follows-buy also follows only the key row. Fix: state that the floor gate uses `pstart` (the earliest prepare start of any class), that the floor *value* uses the class of the rows inside the floor window, and that the latch exemption is checked on `key_id`. Add the two-alert fixture.

**M3. E2's position in `_apply_prepare` is unspecified.** The latch purge (`:950-953`) and the `engaged→reached` advance (`:974-980`) must still run outside the floor window. Otherwise the buy horizon loses its "reached" stop, and the buy re-fires after reaching 80 at 12:00 because `state != "reached"` is no longer checked. Fix: "the gate only nulls the registered-floor field after the latch advance and after `pre` is computed. It never early-returns."

**M4. The E0 acceptance lines don't fix TOU, so they pass or fail depending on the fixture.** At top rate, an uncorroborated watch returns `allow_discharge`, not `partial_hold` (`:1105-1127`). At top rate, a ≤28 °F confirmed watch consults recoverability and can return `partial_hold` (`:1159-1172`). Both "Verify" lines need the TOU stated (bottom), plus a top-rate row with its own expected value. Also say explicitly that a 34 °F Freeze Warning in the 05-09 winter top-rate block **releases** the battery, because the operator should approve that.

**M5. E0 misstates the current state of Freeze Watch.** The table has no Freeze Watch row (`energy_const.py:694-725`). It is gated out, not "notice". The `FZA` code is unverified, while the table comment says codes are probe-verified (P3). A builder adding `("FZA", …)` creates a code-match path with no evidence. Fix: add it as a name-only row (code None). The `observed_code` drift will record the real code. List "Freeze Watch: gated_out → watch" in the golden expected diff (C2).

**M6. Widened notice rows (Wind Advisory) get condition corroboration, and the plan doesn't say whether that is intended.** E1.2 says "watch class (partial hold unless corroborated)". So `Wind Advisory` in hold plus a `pouring` provider gives full hold at any TOU. That is the same exposure the unlisted cap exists to close, for a product the operator ruled "I don't want grid buys on mere rain" about. A hold isn't a buy, but the plan should either extend the H1/H2 cap to "selection-widened" rows or state that table-known widened rows deliberately keep condition corroboration, and test whichever is chosen.

---

## LOW

**L1. Floor lead greater than the buy lead.** The prepare set holds only alerts ≤ `INCLEMENT_PREONSET_LEAD_H` out, so floor lead 13 behaves like 12, and INV-8's "iff" is false at the extreme. Document `effective floor lead = min(floor_lead, buy_lead)` on the knob and pin it in `test_preonset_floor_lead_window` (parametrize 0, 4, 12, 13).

**L2. Restart and obs-mode.** The latch is RAM (§12 limit 15 class). After a restart mid-buy outside the 4 h window, the floor drops until the solar test re-engages it. In observation mode the latch is rolled back every tick (`energy.py:9420`), so floor-follows-buy never applies there. Both are acceptable, but state them in INV-8 so Reviewer D doesn't file them as leaks, or so the plan owns them.

**L3. Several Live lines don't discriminate.** E1 Live (b) "`inclement_selection` reads `[]` with no alert" is the same under a build where the attr is never populated. Pair it with a test-only discriminator, or drop it. E2 Live: "`inclement_preonset` is null with no alert" holds pre- and post-E2. The useful line is the `floor_from` one, which is event-gated and fine.

---

## Mutation-authority gaps (each would let a monkeypatch pass)
- INV-7(e) "table not mutated" is an AST test. Add a behavioural drill: overlay writes into a copied list that aliases the tuple rows, then assert the defaults are unchanged after an override run.
- INV-8 needs a drill on the **reader** side (C1), not only "key the floor on the buy horizon".
- The H4 runtime intersection needs its own drill: drop `∩ effective_hold` and the seeded-illegal-store test must go RED.
- Reviewer C should mutate each `match_product` caller separately (classify, build_record, memory admission, ledger). One aggregate patch on `match_product` hides a caller that bypasses the overlay.

---

## Forecast-intersection pushback (§0.3 / §E2)

**The narrow claim holds:** the pre-onset floor lives in `[s−lead, s)`, and an intersection with `T ≥ s` can only start it later. I could not build a counter-case for the *floor*.

**The framing is too narrow, and the counter-cases sit where the operator was pointing:**
1. **NWS re-stamps Onset to issue time on Updates.** `AUDIT_ec_storm_stage0_probes.md:41,47`: "When the hazard is already underway the Update re-stamps onset = sent", and Wind Advisory has 0 lead in 53 % of messages. Example: WSW Onset 21:00, an Update at 13:00 re-stamps Onset to 13:00 (for example, early flurries upstream). D-B1 `start = Onset` makes the warn active at 13:00, a full hold at any TOU, while the OWM hourly rows show the freezing-precip hour at 22:00. A 13:00 full hold through the 17-21 top-rate block is exactly "alert time vs forecast time". Neither E2 nor the floor touches it.
2. **Long watch windows.** Watches are issued 15-37 h ahead (same audit) with 24-48 h windows. Once a watch is active and corroborated (condition or forecast), the in-window hold spans the whole window. That is the operator's "holding for 12 hours is wasteful", inside the window rather than before it.
3. **Calling E2b a "demotion of an active warn (INV-3)" overstates its cost for watches.** An uncorroborated watch at top rate already allows discharge (`inclement.py:1121-1127`). Deferring a watch's corroboration-driven *full* hold to `T − L` is a narrowing of a raise, not a warn demotion. That is a lower bar than the plan's evidence trigger implies.

**Recommendation:** keep E2 as specified (after C1 is fixed). Rewrite §0.3 to say the intersection has ≈0 margin *for the floor*, and that its margin is in-window (Onset re-stamps, long watch windows). Re-scope E2b's trigger to measure Onset-vs-first-confirming-hour on watches and on Updates whose Onset equals Sent, not only on HOLD warns. OQ-3 should show the operator counter-case 1, because it is the concrete instance of his complaint.

---

## Summary

| Sev | # | Findings |
|---|---|---|
| CRITICAL | 2 | C1 E2 buy/floor single-field conflict (unbuildable); C2 golden contradicts E2 + two capture points + undefined projection/axes |
| HIGH | 5 | H1 `watch_requires_corroboration=False` leak; H2 per-tier vs per-record cap; H3 overlay threading + ledger caller; H4 runtime buy ⊆ hold; H5 retired names vs choices |
| MEDIUM | 6 | M1 `_NO_LIVE_ATTR_KEYS`; M2 multi-prepare key; M3 gate ordering vs latch advance; M4 E0 TOU unspecified; M5 Freeze Watch absent / FZA unverified; M6 widened-notice corroboration |
| LOW | 3 | L1 floor lead > buy lead; L2 restart/obs-mode latch; L3 non-discriminating Live lines |

Bug classes: #53 one-missed-site (C1 readers, H3 ledger caller, M1); #63 coincidental equality masking a concept split (C1: "buy target" and "registered floor" are the same field today only because they are equal); #62 hollow anchor risk (C2 golden without a projection, AST-only table test); observation-mode gating (L2).

**Must-fix before build dispatch:** C1, C2, H1-H5, M1-M3. M4-M6 and the LOWs are fixed in the plan text in the same revision.

---

## Re-check Rev 2 (a181ae959, 2026-10-17)

### Prior findings: resolved in the plan text?
| ID | Status | Evidence in Rev 2 |
|---|---|---|
| C1 | RESOLVED | §E2.4 split; §4.3 lists 7 readers. Re-grep `preonset_floor` confirms exactly `energy_battery.py:2835, 3137, 6352, 6385, 6839, 7057` + `energy.py:9544` (plus config keys 2693/2798, producer `inclement.py:1009`). Swap drills per row. |
| C2 | RESOLVED, residual F8 | One capture point (v5.103.69 tag, committed script + fixture), named projection, full axes, INV-7(e) scoped. |
| H1 | RESOLVED | INV-7(c) "any leg", repro (i), tests parametrized on `watch_requires_corroboration`. |
| H2 | RESOLVED | §4.2 `any(r.corroborable for r in watch_records)` ANDed onto the tier `corroborated`; mixed fixture. |
| H3 | RESOLVED | §4.1 three callers incl. ledger; explicit `selection` param; no global; drift skip for unlisted. |
| H4 | RESOLVED | §E1.3 runtime `∩ hold ∩ (family ∪ polygon)`; seeded-store test + drill. |
| H5 | RESOLVED | §E1.2 selection domain excludes retired rows; real-flow "four empty lists" test. |
| M1-M6 | RESOLVED | §E1.6 both sets; §E2.4 multi-alert + placement; §E0 TOU rows; Freeze Watch name-only; widened rows non-corroborable. (M2 residual: F7.) |
| L1-L3 | RESOLVED | min(floor, buy) lead; INV-8 non-guarantees; Live lines replaced. |

### Prior-art check (operator: "don't invent unnecessary code")
Holds. The scheduler ranks each hour with existing `period_rank`/`get_season`/`get_current_period` (`energy_tou.py:459, 491, 516`). No existing "N cheapest hours before T" selector exists (grep `cheap|cheapest|rate_rank(` outside `energy_tou.py`: no energy hits), so ~20 new lines is the minimum. `_is_charge_window_open` (`energy_battery.py:3558-3573`) is cited as an analogy, not reused; fine.

### New findings (E2 schedule, field split)

**F1 HIGH. The candidate rule excludes the current hour, which breaks the plan's own repro and test.** §E2.2: candidates are whole hours `H` with `now ≤ H < T`; the gate is "now's hour ∈ S". At any tick after hh:00:00 the current hour is not a candidate. Concrete: "Verify (unavoidable top rate)": issued 17:30, Onset 19:00, expects `S ⊇ {17:00}`, but 17:00 < 17:30 is excluded, so S = {18:00}. INV-9 repro: if S is recomputed at 15:01 (pre-freeze or after a target change), 15:00 drops out and the ordering picks {16:00, 20:00}, i.e. a top-rate hour. Event 50 min away (20:10, T 21:00) gives S = () and no buy. Fix: candidate slots `[H, H+1h)` with `H+1h > now` and `H < T`. The gate is "the slot containing now ∈ S". Add a test at hh:30.

**F2 HIGH. The freeze point is stated two ways, and its storage changes the latch type without enumerating the latch readers.** INV-9 says "frozen when the latch first engages". §E2.2 says "computed on the first tick where a buy would be eligible and stored on the latch entry `{state, hours, T, target}`". Engagement happens only after a commanded buy (`energy_battery.py:6401-6409`), so INV-9's reading recomputes S every tick before the buy, and F1 bites. §E2.2's reading turns `dict[str, str]` (`energy_battery.py:474`) into dict values. Five readers compare against strings: `inclement.py:975` (advance), `:984` (`state`), `energy_battery.py:3145` (attr), `:6403-6408` (engage), and `energy.py:9420-9421` (obs-mode rollback). A dict entry never `== "engaged"`, so the advance and the rollback silently stop (#53). The observation-mode rollback deletes only `engaged`, so a pre-engage schedule entry would survive obs mode. Fix: keep the latch type. Add a sibling RAM dict `_preonset_buy_schedule[key_id] = (hours, T, target)`, purged in the same loop as `inclement.py:950-953`. Freeze it on the first tick where every D-B6 conjunct except hour ∈ S holds. Enumerate its readers in §4.3. State its discharge: purge on alert exit; clear on option-off or forecast-unconfirm (today's eligibility rule covers only `engaged`).

**F3 MED. Onset Updates re-key the alert, so "recompute on T change" never happens in place.** `alert_id = alert_key` takes the NWS `ID` (`energy_outage_ledger.py:72-81`, `inclement.py:252`). An Update is a new message with a new ID. The old latch and schedule are purged at `:950-953`, and the new ID starts fresh: `engaged`/`reached` are lost, and the solar test re-runs. A `test_schedule_recomputed_on_onset_update` written with the same ID and a moved Onset is hollow (#62). Fix: the fixture replaces the alert with a new ID and a new Onset, and the plan states the real semantics (fresh schedule, parent limit 23).

**F4 MED. The engine-missing fallback is unbuildable, and an unranked hour crashes the sort.** "Engine missing → `get_current_period(H) == "off_peak"`" calls the engine that is missing. Today's fallback is `tou_period == "off_peak"` for now only (`energy_battery.py:2960-2969`). `period_rank` returns None for an unknown period (`energy_tou.py:491-506`), and `(None, Δ) < (0, Δ)` raises TypeError. That is not the "engine raises" path. Fix: engine missing → S = () (no D-B6 buy, a stated byte change), or legacy current-tick behaviour. A None rank excludes that hour. Test both.

**F5 MED. `h_req` is ≥ 1 even when SOC ≥ target, so the floor starts early with no buy.** `ceil(max(0, target − SOC)/rate) + margin` = 0 + 1 = 1, so S is non-empty and INV-8(ii) registers the floor from min(S). In winter with Onset 21:00 that is 16:00 instead of 17:00, with nothing bought. That breaks "floor no earlier than needed", and the INV-8 falsifier can't see it because it is defined relative to S. Fix: SOC ≥ target or SOC None → S = (). Test it.

**F6 MED. DST and timezone handling are unspecified, and the cited walk pattern carries the bug.** `T` is a fixed-offset datetime (`inclement.py:185-190`, `fromisoformat`); `now` is zoneinfo. `peak_ahead_before_offpeak` (`energy_tou.py:661-668`) steps with wall-clock `+ timedelta(hours=1)` on aware datetimes, which skips the repeated 01:00 on fall-back and yields a non-existent 02:00 on spring-forward. Hour counts and `T − H` ordering are then off by one. Fix: step UTC hour boundaries and rank via `dt_util.as_local(H)`. Add DST-night and window-across-midnight tests (§8 names DST as a D target, but §E2 has no test for it).

**F7 MED. The multi-alert floor value contradicts the field definition.** §E2.4 says the registered floor equals `preonset_target` when INV-8 holds. M2's rule says the floor value comes from rows inside the floor window. With a warn 10 h out and a watch 3 h out, the buy target is 80 (key row = warn, `inclement.py:956-970`), while the registered value is the watch's lower floor. Bought energy can then discharge to 50 before T. Fix: under INV-8(ii), registered = target. The window-class rule applies only under (i).

**F8 MED. The golden's E2 expected diff is generated by the code under test.** "Prepare cells at a bottom-rate hour outside S" requires computing S, which only the build branch's scheduler can do. A wrong scheduler then widens its own allowed diff (#62). Fix: take the E2 buy cells out of the golden and give them to the explicit INV-9 tests, or derive the diff from a hand table independent of `schedule_buy_hours`.

**F9 LOW.** "Verify (closest to event)" is conditional ("only if those are bottom rate. Otherwise…"); pin the shoulder answer {15:00, 16:00}. There is no test where T is less than `h_req` hours away (partial S), and none for T exactly on the hour.

**F10 (mutation authority, INV-9).** The listed drills (`is_bottom_rate(now)` gate; `(rank, H − now)` order) are falsifiable. They are not enough. Add:
- (a) no freeze, recompute every tick: needs a fixture where SOC rises mid-buy so S shifts and CFG cycles twice. Without that fixture, `test_schedule_frozen_on_engage` stays GREEN;
- (b) a current-hour exclusion drill (F1);
- (c) drop the margin, or compute `h_req` from `floor` instead of `target`;
- (d) drop the eligibility conjunct from INV-8(ii);
- (e) the engine-missing path.

### Discharge paths (operator's three cases)
- Alert cancel or expiry: covered by the purge at `inclement.py:950-953`.
- Forecast unconfirm, or option off: covered for `engaged` only. A pre-engage frozen schedule has no clear (F2).
- Option back on later: a stale frozen S whose hours have passed gives no buy until a new ID arrives. State it.

### Verdict: **FIX-PLAN**
All of C1-C2, H1-H5 and M1-M6 are genuinely resolved. The new E2 schedule has two HIGH build traps:
- F1: the current-hour exclusion contradicts the plan's own repro.
- F2: the freeze point and its storage are ambiguous, and five string-typed latch readers are not enumerated.

Must-fix before build: F1, F2, F4, F5. F3 and F6-F10 are fixed in the same revision.
