# Plan review 3: PLANNING_ec_storm_and_blind_decisions.md Rev 3 (Tier-3, framing 1 = COMPLETENESS)

**Target:** `docs/planning/PLANNING_ec_storm_and_blind_decisions.md` at 4665b252b (branch `plan/ec-storm-rev3`); code read at the same tree (= 57ffbe55b code).
**Focus:** Rev 3 delta. That means D-A5 (blind floor Number), D-B6 (pre-onset floor + pre-charge leg), D-A3 keyed on `_tick_reserve_floor`, and the Q6/Q7 defaults.
**Method:** I re-ran every enumeration with grep and did not take the plan's lists on trust. HVAC and presence state-of-play docs do not apply (energy-only).

**Verdict:** FIX-IN-PLAN before any Stage A/B build dispatch. 0 CRITICAL, 4 HIGH, 5 MEDIUM, 6 LOW.

---

## Independent re-enumeration (what checks out)

| Claim | Re-check | Result |
|---|---|---|
| CFG=True `_result(` sites | `grep -n "charge_from_grid=True" domain_coordinators/*.py` → `energy_battery.py:3961` (arb CHARGE), `:4724` (attain), `:5840`, `:5856` (storm precharge). No CFG=True kwarg in energy.py / energy_pool.py (only comments + `decision.get("charge_from_grid")` readers at `energy.py:6436, 7313`). | Matches. D-B6 adds exactly one more (5 total). |
| 19 `self._result(` calls | `grep -c` = 19, same line list as §5. | Matches. |
| `number.set_value` literals in energy_battery | `:5664, :6395, :6818, :6836`. | Matches. |
| `RESERVE_SET_VALUE_WRITERS` | `energy_const.py:2307-2318`, `_result:1` + `determine_mode:1` rows present. | Matches. |
| Sole `_last_reserve_level_desired` writer | Package-wide grep: one assignment, `energy_battery.py:6534`. | Matches, so the D-A2 "sole stamper" target is achievable. |
| `_tick_reserve_floor` / `_reserve_action` | 0 hits. | As stated. The consumers are all plan-defined: the fold, D-A4 row, D-A3 hold/release trigger, and D-B6 registration. But see H4: one more reader *should* consume it. |
| Pre-charge gate reuse | `_precharge_refused_on_blind` `:4106-4152`. It refuses only under degraded telemetry (SOC None, or decision age > 1800 s / unstamped). | Fine for D-B6. On refusal D-B6 falls through to the TOU branches, where the storm precharge instead returns BACKUP. That difference is stated in the plan. |
| D-B6 placement | Returns between `:5787` and the TOU branches: only the full_hold block (`:5788-5869`). The chunk reset is at `:5512`, above. | The placement is sound. The early return skips no per-tick bookkeeping that the TOU branches own (the arbitrage phase is not updated on that tick, same as the storm precharge). |
| INV-6 falsifiable | Floor repro (`reserve_soc=20, partial=50, knob=80`, WSW Onset 21:00, 18:00 Oct) and pre-charge repro are both legal configs. Falsifiers are row/command-observable. | Yes, except for the memory leg (H3). |
| Knobs on the ladder | Two rung-3 Numbers, `INCLEMENT_PREONSET_LEAD_H` rung 1 (0 = kill), reused option rung 2. | Yes. Gaps in the D-B6 Number spec are listed in M4. |
| Q6 / Q7 defaults | `BLIND_RESPECT_MANUAL_LOWER=False`, `INCLEMENT_UNVERIFIED_POLYGON_TIER="notice"` with re-confirm at the Stage B checkpoint. They are consistent across §6/§7/§14. | OK. |
| Parked-plan triggers fired | `PLANNING_inclement_hardening.md:263` Non-goal 6 ("no pre-charge CFG writer") is lifted by the Q3 ruling and recorded. The §10 polygon-matcher trigger is half-armed (Q7 = notice). It fires only if P2(b) flips. No other plan in `docs/planning` references pre-onset. | Accounted for. |

---

## HIGH

**H1. One `_EC_SETTER_DISPATCH` row does not keep the options write off the reload path.** §1a row "Blind floor slider", D-A5 and §7 all claim that "one `_EC_SETTER_DISPATCH` row each" stops the CM reload. It does not. The reload decision is `changed_keys ⊆ OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:6774`), and that set is a separate explicit frozenset (`__init__.py:7450-7594`). It spreads `_HVAC_TUNABLE_DISPATCH`, `_NM_A2_KEYS` and `_NM_C_KEYS` but **not** `_EC_SETTER_DISPATCH`. `_EC_SETTER_DISPATCH.keys()` feeds only `_ec_owned_keys` (`:7946`) and the apply loop (`:8175`). Every existing EC Number key is listed by hand in both places, for example `_CONF_ENERGY_PEAK_BUFFER_TARGET` at `:7294` **and** `:7467`. A builder who follows the plan literally ships two sliders whose every move reloads the Coordinator Manager, which is the parent-reload watchdog hazard (memory `feedback_parent_entry_reload_watchdog_hazard`). Live (e) would catch it after deploy. **Fix:** name both sets for both keys in D-A5 and D-B6, and add `test_*_key_in_options_reload_suppress_keys` (the source-anchored pattern from `test_ac_ramp_master_option_persistence.py:294-333`).

**H2. The claim that a running arbitrage CHARGE or attain leg "charges to `max(target, floor)` with no new code" is false.** It appears in §1a "Grid refill toward a floor", §6 D-B6 "Reuse vs new writer", and the marginal-benefit paragraph. The phase engine exits CHARGE on `soc >= self._peak_buffer_target` (`energy_battery.py:3733-3734`, HOLD with `charge_from_grid=False` at `:3938`) and latches `_arbitrage_chunk_completed` (`:3924`). Attain is likewise sized to `_peak_buffer_target`. The fold only raises the *reserve number*. Grid charge stops when SOC reaches the buffer target, not the floor. Repro: `peak_buffer_target=60`, pre-onset floor 80, option False, off-peak, SOC 40. CHARGE runs to 60, then HOLD with reserve 80 and CFG off, so the battery sits at about 60 at Onset. Partial-hold floors above the buffer target already behave this way, so this is a property of the current code and not a new leak. But the plan uses the false claim (a) to price the pre-charge leg's margin as "only the case where SOC is below the floor and solar can't close it". In fact, with the option False, *no* path lifts SOC to the floor. (b) It also invites reviewer D or the builder to "make it true" by changing phase-exit logic in the arbitrage state machine. **Fix:** correct the three passages. State that with the option False the pre-onset floor is discharge-prevention only, and that grid refill to the floor exists only through the D-B6 pre-charge leg. Add a §12 case for `peak_buffer_target < preonset_floor` with the option False, expecting CHARGE to stop at the target. Put the phase engine on the Non-goals list.

**H3. The D-B3 memory text contradicts INV-6 (and INV-3) for alerts issued ahead of Onset.** INV-6 defines a prepare alert as "present in the healthy feed **or the D-B3 memory**". D-B6 says memory "admits HOLD alerts at classification regardless of Onset". But D-B3, which Rev 3 did not amend, says (1) memory holds "every alert classified HOLD", and under D-B1 a `now < start` alert is dropped before it can classify. It also says (2) "the classifier input is the healthy feed's active alerts plus memory entries **still inside `[start, end]`**". A pre-onset entry is not inside `[start, end]`, so even if admitted it is never fed to the prepare set. Legal repro: WSW Sent 06:00, Onset 21:00, Ends +12 h; the alerts sensor goes `unavailable` 15:00–23:00 (an internet drop during a storm build-up, the case D-B3 exists for). At 18:00 a D-B3-literal build has no prepare floor, which falsifies INV-6(i). At 21:00 it has no hold, which falsifies INV-3 ("a Winter Storm Warning hold dropping while the feed is unavailable before its end"). `test_preonset_memory_survives_feed_loss` is named, but the spec it tests against is self-contradictory. **Fix:** amend D-B3 so that admission = HOLD table class and Status/Type filters pass, with no window condition (a stale feed still admits nothing). Classifier input = feed active ∪ memory entries with `now ≤ end`, and the active/prepare split is applied after the union. Add an INV-3 test for "issued ahead, feed lost before Onset, hold at Onset".

**H4. A decision consumer of an off-peak value stamp is not floored by the pre-onset floor (Bug Class #53).** §5 says the DP stamp in `_offpeak_drain_branch_target` "reaches dispatch only through `_result`, so the fold covers it." It doesn't. The stamp (`energy_battery.py:6233`) is consumed **verbatim by EnergyCoordinator's DP tick** ("so EnergyCoordinator's DP tick can consume THIS tick's value verbatim", comment at `:6226-6232`), which is a trust-decision consumer separate from reserve dispatch. Its clamp is keyed on `decision.hold_depth == "partial_hold"` (`:6223-6224`, and the second inline clamp at `:6262-6263`). A pre-onset floor runs under `allow_discharge`, so the stamp stays at the drain target (for example 25) while the reserve is folded to 80. Repro: DP enabled (Path A drain-pause), WSW Onset 21:00 tomorrow, overnight off-peak inside the 12 h lead, drain target 25, floor 80, SOC 70. DP plans an EV drain-precedence window against a battery that is meant to fall to 25 and physically cannot (reserve 80). The EV can be held paused toward `must_start_by` waiting for a drain that never happens. No reserve leak, but a wrong decision on a value the plan says is covered. **Fix:** key both inline clamps on the registered floor (`if self._tick_reserve_floor is not None: drain_target = max(drain_target, self._tick_reserve_floor)`), which is byte-identical before D-B6 because Stage A registers only when holding and full_hold returns earlier. Add it to §5 and the D-B6 mutation list, and add `test_preonset_floor_reaches_dp_drain_stamp`. Also re-grep the other per-tick value stamps that `determine_mode` publishes for non-dispatch consumers (`grep -n "value stamp\|VALUE STAMP" energy_battery.py`) and record each as floored or N/A.

---

## MEDIUM

**M1. A simpler persistence path already exists for both sliders (simplify).** `_inclement_config` (`energy_battery.py:2556-2600`) re-reads the CM entry's `{**data, **options}` **every tick**, and `InclementFusion` is constructed per tick from that cfg (`:2712-2719`). So the inclement knobs are already "options are the sole source, read live". D-A5's "coordinator setter + read from the battery strategy" adds a second copy of the value, a setter on EnergyCoordinator, and the PeakBuffer boot push-retry race (`number.py` `_push_to_coordinator` + signal retry). The house's existing pattern for "consumer re-reads entry.options" keys is `_NO_LIVE_ATTR_KEYS` (`__init__.py:7347`) plus `OPTIONS_RELOAD_SUPPRESS_KEYS`. The Number seeds from options and writes options; `_inclement_config` adds two keys; no setter, no `_EC_SETTER_DISPATCH` row. Recommend switching both Numbers to this, or justify the setter path in the plan.

**M2. The pre-charge leg has no latch, so CFG can flap at the floor.** The leg turns CFG on while `soc < preonset_floor` and `soc + surplus < floor`, and off the next tick it isn't. Arbitrage prevents exactly this with `_arbitrage_chunk_completed` ("so a momentary SOC dip doesn't drop us back into CHARGE", `:3920-3924`). The solar-surplus term also moves tick to tick. Near the floor, Envoy CFG toggles can alternate every 5 min (and CFG has known debounce/apply failures, `energy_write_verify.py:68`). The storm precharge (`soc < 90`) has the same exposure today. It is dormant by default, but INV-6(iii) should not quietly inherit it. **Fix:** a per-prepare-alert-ID "reached" latch (cleared at Onset or when the alert leaves), or state the exposure as a §12 known limit with the storm-precharge parity.

**M3. §12 known limit 14 (observation-mode bypass on the evaluate path) was not extended to D-B6.** It covers only the widened blind de-escalation. D-B6 adds a CFG **turn_on** at bottom-rate ticks, and the transition-into-off_peak evaluate tick runs `determine_mode` without the observation-mode gate (plan §5, arc step 8). That is a real grid-import actuation while the operator has asked for observation. **Fix:** extend limit 14 to the pre-charge leg, or gate the leg on observation mode (one boolean, `_result` caller side).

**M4. `InclementPreonsetFloorNumber` is under-specified next to D-A5.** D-B6 gives no min/max/step/unit, entity_id spec or options key definition (only the §7 row and Live (b) entity id), and only one test (`test_preonset_floor_number_live_slider`) against D-A5's five (seed, setter/options, no-reload, live read, extremes). The `inclement_preonset` attribute named in §4 and Live (a) is not a deliverable: which of `_inclement_attrs` and `sensor.ura_inclement_state` (`sensor.py:9376-9385`) carries it, and what shape? **Fix:** mirror D-A5's spec block and test list, and add the attribute as an explicit D-B6 item.

**M5. "Through `_result` only, no new CFG writer" has no mechanical pin.** The plan admits that no CFG lint exists and leaves it to the mutation item and reviewer D's hand-read. Cheap fix: extend `test_reserve_write_chokepoint_lint.py` with an AST count of `charge_from_grid=True` keyword args per function in `energy_battery.py` (expected: `_get_arbitrage_decision:1`, attain helper `:1`, `determine_mode:3` after D-B6) and zero CFG `switch.turn_on` service literals outside `_result`'s action builder. That turns INV-6(iii)'s routing clause into a lint instead of a reading exercise.

---

## LOW

- **L1.** Non-goal 1 still says the only governor-row changes are `tick_floor`/`tick_hold_depth`. D-B6 adds `tick_preonset`. Update it.
- **L2.** §14 Q3 "plan effect" says "new grid-charge writer = Tier 3 ingredient". §5, §6 and Non-goal 3 say "a new emission site, not a new writer". Pick one wording. The substance (one new CFG=True call site) is the same.
- **L3.** `prepare_start = min(start)` across warn and watch rows while `prepare_class` comes from any warn row. The pre-charge solar sizing then uses an earlier watch start for a later warn. That is conservative (fewer minutes, so less solar credit, so it fails toward charging), but state it.
- **L4.** `_inclement_partial_hold_floor` (`energy_write_verify.py:1659`; consumers `:1730` effective desire, `:1935` conduct exemption) and the governor row's `inclement_floor`/`floor_ok` (`energy.py:9243-9316`) are partial-hold-only, so they do not see a pre-onset floor. `:1730` is covered because it composes from the folded stamp. `:1935` is a lower-floor exemption, so it doesn't apply. `_resolve_hold_owner` will not report `inclement` for a pre-onset floor (display). List these in §4 as "intentionally unaware" so reviewer D doesn't re-derive them.
- **L5.** Grid-import-guard parity (`_arbitrage_grid_import_guard_*`, `energy_battery.py:614-656`) for the D-B6 pre-charge is unstated. Say it matches the storm precharge (exempt or not, with a cite).
- **L6.** D-B6 Live (d) queries "`command_trail` / activity log" for the reason `Inclement pre-onset`. Confirm that the decision reason is persisted on the CFG command record before relying on it, or name the column/attribute.

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 4 | H1 reload-suppress set, H2 false CHARGE-to-floor composition, H3 D-B3 memory vs INV-6/INV-3, H4 DP drain stamp unfloored |
| MEDIUM | 5 | M1 simpler options-read persistence, M2 pre-charge flap, M3 observation-mode limit not extended, M4 D-B6 Number under-spec, M5 no CFG pin |
| LOW | 6 | L1–L6 |

Bug classes: #53 computed-but-not-consumed (H4); one-missed-site / allowlist omission (H1); false prior-art claim (H2); spec self-contradiction across deliverables (H3); state × time flap (M2).
