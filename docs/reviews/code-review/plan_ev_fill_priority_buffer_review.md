# Plan review: PLANNING_ev_fill_priority_soc_buffer.md (EV-FILL-PRIORITY-SOC-CHATTER-1)

- Reviewer: ura-reviewer (adversarial plan review, Tier 2-DB, one pass before build)
- Base: develop @ f7e6dd922, plan plus the "Orchestrator rulings" section
- Code read: `energy_pool.py` 2668-2921 (EV FP), 3120-3165 (arbitrage hand-off), 3491-3540 (EV release_all), 4018-4060 (plug release_all), 4384-4562 (plug FP); `energy.py` 6776-6845, 6942-6970 (call sites)
- HVAC/presence docs not applicable (energy-only change)

## Verdict: FIX-REQUIRED (plan edits only; the design direction, option A, is sound)

## Findings

1. **HIGH — No day-boundary or inert discharge, so a stale latch suppresses the next day's first pause (suppression without discharge, day-boundary-blind).**
   §5.3 lists four clear sites. The inert branch (`energy_pool.py:2760-2766`, plug `:4441-4446`) is not one of them. Peak and off_peak-night run every day, and Q2 dropped the TTL, so nothing time-anchored clears the latch.
   Repro: fill_priority_soc=80. The EV resumes at SOC 80 at 13:00 and the latch is set. Battery ends the day at 90+, overnight arbitrage grid-charges to 100, and SOC is 79 at 08:00 in daylight off_peak. The EV is ON (it charged overnight), so the latch says re-pause and the gate requires SOC < 77. The EV drains the home battery from 79 to 77 with no pause. Under the legacy code a pause fires at 79. That is INV-2 broken in spirit: this is the first pause of a new fill window, not chatter.
   Fix: clear the latch for every id in the inert branch (EV and plug), and say so explicitly. The orchestrator's Q2 ruling ("already has a discharge") is wrong without this site.

2. **HIGH — The named cross-owner-steal clear site is unreachable in the latched state.**
   §5.3 cites `:2871-2888`. That block sits under `elif evse_id in self._paused_by_fill_priority` (`:2865`). The latch exists only after the terminal discard at `:2916`, so a latched EVSE is never in the FP set and that branch never executes for it. Drain, arbitrage, load_shed, grid_cap, and blind_window pause through their own sets, which FP never observes.
   A8 ("drain takes over during latch → fresh FP pause at 78 after drain releases") will fail, or the builder will invent an ad-hoc site.
   Fix: specify a per-EVSE check at the top of the FP loop: if the id is latched and in any peer set (`_paused_by_grid_cap/_battery_drain/_us/_arbitrage/_load_shed/_blind_window`; plug: `_us/_battery_drain/_load_shed`), clear the latch. Alternatively, rule that a steal does not clear it.

3. **MEDIUM — The force-charge clear is placed inside a membership check.**
   `:2785-2793` and `:4458-4466` only act `if evse_id in self._paused_by_fill_priority`, and a latched EVSE is never in the set. The clear must be unconditional in the force_charge branch. A7 is also self-contradictory: "SOC=79 tick pauses immediately once force-charge clears below floor", but 79 is not below the floor of 77. Restate A7 as: force-charge on, then off at SOC 79 → pause fires at 79.

4. **MEDIUM — The latch is set on a forecast_decayed resume, not only on an SOC resume.**
   The terminal resume at `:2916`/`:4558` covers both `resume_soc_met` and `forecast_decayed`. The chatter mechanism is SOC-only, and the forecast side already has its own band (`safety_margin_kwh`, `:2726-2731`).
   Repro: SOC 78, forecast decays → resume and latch set. The forecast recovers to healthy with SOC still 78. Legacy behavior is to re-pause. Under the plan the EV draws the battery to 77 first.
   Fix: set the latch only when `resume_soc_met`. A10 should cover this case.

5. **MEDIUM — `_fill_priority_would_hold` (`:2776`) stays global and latch-blind, which contradicts the latch on the arbitrage hand-off path.**
   At SOC 78 with a latched EVSE, `would_hold=True`. The arbitrage release (`:3150-3160`) then adds the charger to the FP set and leaves it OFF until 80. Is that a re-pause inside the band (INV-1 says no membership transition) or a legitimate first claim? The plan must rule on this:
   - either make would_hold per-EVSE (latched → False for that id),
   - or exempt the hand-off and clear the latch there.

   Also add the hand-off to the §8 producer list. The plan omits that `:3156` and `:3525` are FP-set writers outside FP.

6. **MEDIUM — The SOC-below-floor clear has no specified location.**
   It must be evaluated for every latched id regardless of `is_on`, the excess-solar deferral (`:2836`), or untrusted-SOC refusal. Otherwise an EVSE that is OFF (car full or unplugged) while SOC dips below 77 stays latched. With SOC `None` (`pause_conditions_global` False) the latch should be left untouched. State that explicitly.

7. **MEDIUM — The live acceptance criteria are not discriminating.**
   L1 and L3 ("zero re-pause rows", "tripwire=0") are satisfied equally by the fix and by a regression that suppresses all pauses, or by a day with no charging. Add a positive control: on the same day, ≥1 `fill_priority_pause` row for a first pause below 80 (L2, made mandatory) and/or a re-pause row only at SOC < 77. Otherwise report "not exercised" rather than PASS.

8. **LOW — "Same latch" for the plug path is ambiguous.**
   `PlugPool` is a separate class with its own `_paused_by_fill_priority` (`:3634`). Specify a per-instance dict initialized in each `__init__` (`:585` and `:3634` siblings). The grid_charge_on held-resume (`:4529-4535` `continue`) correctly sets no latch; keep A6 asserting that.

9. **LOW — A4 monkeypatch hygiene.**
   If `energy_pool` does `from .energy_const import DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT`, patching `energy_const` is a no-op. The test must patch `energy_pool.<name>`, or this becomes a hollow anchor (#62). A cleaner option is to pass the band as a kwarg with the constant as default, matching `safety_margin_kwh`.

10. **LOW — Clamp wording.**
    The ruling `effective = min(band, soc_threshold)` gives floor ≥ 0. Fine, and §7's "clamp to 0" matches. Also clamp a negative band (`max(0, …)`), since the unit test only guards the constant, not a future kwarg.

## Cleared

- **Band=0 byte-identical:** holds. The floor becomes `soc_threshold`, so the gate equals the legacy `soc < soc_threshold`. The latch writes are dict-only side state.
- **Restart/reload:** the RAM-only latch matches the RAM-only FP set (`:585`). Losing it on reload yields at most one pause, which is acceptable (§5.4).
- **Resume edge unchanged (`:2773`):** confirmed. No EV can stay paused above 80 because of this change; the latch only gates pause, never resume. INV-1/2/3 are falsifiable once findings 1, 2, 4 and 6 are fixed.
- **release_all_fill_priority as a clear site:** reachable, since it is called when the excess-solar toggle is off (`energy.py:6842`, `:6968`). Note that when the toggle is off, FP is not called at all, so clearing there is required. Correct.
- **Knob rung 1 (module constant, 0 = kill switch):** justified.
- **Tests fail on develop:** A1, A3 and A7 assert behavior absent today (`:2770` has no band), so they will fail RED on develop. A2 and A5 are regression guards (green on develop by design, which is fine).

## Must-fix before build

Findings 1, 2, 3, 4, 5, 6, 7. 8-10 are recommended.

---

## Tier 3 plan review 1 (completeness)

- Reviewer: ura-reviewer, framing = completeness / independent re-enumeration. Base: develop HEAD (after a9e45da38 / 92f324f43), plan Rev 2 plus the "Tier elevation" section.
- Method: I enumerated from code first (`grep _paused_by_fill_priority|_fill_priority_would_hold` across `domain_coordinators/`, `energy_pool_owners.py`, `energy.py`, `sensor.py`), then compared against D1-D5, §5.4, §5.5 and §8. HVAC/presence docs don't apply (energy only).

### Independent enumeration (ground truth)
- **EV FP-set writers (`energy_pool.py`):** 2764 (inert), 2787 (force), 2819 (manual override), 2851 (pause add), 2880 (peer steal, inside FP guard), 2916 (terminal), 3156 (arbitrage hand-off add), 3497 (release_all discard), 3525 (release_all re-add on untrusted SOC). **Plug:** 4444, 4460, 4486, 4501, 4523, 4558, plus `release_all` 4034 / 4054 (untrusted re-add).
- **Persistence:** the EV FP set is **KV-persisted**. `energy_pool_owners.py:312` has `persistence_key="evse_fill_priority_paused"`, and it is restored with a 10h staleness guard (`energy.py:1565-1577`, saved at `:2166`). The plug FP set has no persistence key (`:394`).
- **Readers outside energy_pool:** `energy.py:1814, 5669, 5811, 7834, 8801, 8914, 10728, 11348`, `sensor.py:10506`. None of these are affected by an additive latch.
- **Call gating:** both FP calls sit under `if not self._observation_mode:` (`energy.py:6582`) and `if self._excess_solar_enabled:` (`:6776`, `:6942`). The else branch calls `release_all` (`:6842`, `:6968`).
- **EV pause owners (registry):** tou, grid_cap, battery_drain, dp, arbitrage, load_shed, fill_priority, proactive_offpeak, blind_window (`energy_pool_owners.py:234-339`). **Plug:** tou, battery_drain, fill_priority, load_shed, proactive_offpeak.

### Rev-1 finding re-check
| # | Resolved at a reachable site? |
|---|---|
| 1 inert | YES. The D1 sites EV `:2763` / plug `:4443` run every inert tick before `return`. **But** see F2 below (observation mode bypasses D1). |
| 2 steal | YES. The top-of-loop placement (`:2780`/`:4453`) is reachable for unlatched-member ids. The peer list is incomplete (F4). |
| 3 force | YES. Unconditional pop under `if force_charge_active:` (`:2785`/`:4458`). |
| 4 forecast | YES. `resume_soc_met` is in scope at `:2916`/`:4558`. |
| 5 arbitrage | Resolved, but the chosen global `any()` creates a new sibling regression (F1). The §8 list now has 3156. **The 3525 label is wrong** (F6). |
| 6 below-floor | YES (D5 at function head, after inert return; `soc is None` → no-op). |
| 7 live | YES (L2 positive control). |
| 8-10 | YES. |

### Findings

1. **MEDIUM — The §5.4 global `any()` regresses the NON-latched sibling EVSE (contradicts clause (2) of the Tier invariant).** `energy_pool.py:3150-3160`: when the hand-off is suppressed, release falls through to `switch.turn_on` (`:3168-3172`, off_peak only). FP's next tick then pauses it again (unlatched, ON, SOC<80).
   - Legal repro: off_peak daylight (non-inert), fill_priority_soc=80, two EVSEs.
     - garage_a resumed SOC-reached earlier, so it is latched. Its car is now full and the charger OFF, so D2 never fires and D5 doesn't either (SOC 78 ≥ 77).
     - garage_b is arbitrage-paused. Arbitrage releases at SOC 78 → `would_hold=False` because of garage_a → garage_b is turned ON → paused next tick.
     - That is one 11.6 kW toggle develop would not make (develop hands it off).
   - Also: given D2 pops the latch whenever arbitrage owns an id, a *latched* id can almost never reach the hand-off. The global `any()` therefore mostly affects siblings, which is the wrong population.
   - Fix: keep `_fill_priority_would_hold` global and add `and evse_id not in self._recently_released_by_fill_priority` at the per-id gate `:3153`. That is one token, per-id, and byte-identical with no latch. A13 should assert sibling behavior.
2. **MEDIUM — Observation mode bypasses every discharge (D1/D5 never run), so a stale latch survives the mode exit (suppression-without-discharge, #observation-mode gating).** `energy.py:6582` gates the whole FP block.
   - Repro: latch set at 13:00, then the operator enables observation mode for 2 days and disables it at 09:00 in off_peak daylight with SOC 79 and the EV ON → no pause until 77. Develop pauses at 79.
   - Q2's "no TTL" grounding ("D1 is the daily discharge") is false whenever FP isn't called.
   - Fix: clear both latches on the observation-mode → active edge (or in the observation-mode branch), or store the set-date and pop on a date change. Add a test.
3. **MEDIUM — §5.6 / §1 factual error: the EV FP set is NOT RAM-only.** It is KV-persisted (`energy_pool_owners.py:312`, restore at `energy.py:1565-1577`). After a restart the FP set comes back and the latch doesn't. Outcome:
   - A latched, resumed EV in the band at boot hits the first-pause edge → one extra toggle per restart (acceptable).
   - A restored FP member resumes normally.
   - The plan must state this truthfully and decide explicitly: persist the latch (registry `persistence_kind="list"`), or accept. Framing C's "reload-wipes-latch is tested" test must not assume the FP set is also wiped. Also forbid the builder from registering the latch as an `OwnerDeclaration` with `peer_holds_member=True`: it is not a pause owner, and it would leak into `_stronger_peer_holds` and the classifier.
4. **LOW — The D2 peer set omits `_paused_by_dp` and `_proactive_offpeak_holds` (EV) and `_proactive_offpeak_holds` (plug).** It mirrors the existing resume guard (`:2871-2879`), which also omits them, but the D2 rationale is "a steal = a new session".
   - Repro: latched EV at SOC 79, DP pauses it, then DP releases at 78 → latch still live → no pause until 77.
   - Rule explicitly whether these count as steals, and test whichever is chosen.
5. **LOW — The plug D4 placement must come BEFORE the `grid_charge_on` early return** (`energy_pool.py:4028-4032`). "At the top" is right, but say it, or a builder will put the clear next to the loop.
6. **LOW — Label errors in §5.4 / §5.5 / §8 / §1.** `:3525` is the EV `release_all` untrusted-SOC **re-add**, not the "plug mirror writer". The plug `release_all` is `:4018-4060` (writers `:4034`, `:4054`). The FP-reader list also omits the `energy.py` / `sensor.py` readers enumerated above (additive latch, no behavior impact, but the map is presented as complete).
7. **LOW — The latch is not pruned on EVSE removal** (`_prune_removed_evses`, `energy_pool.py:1221`). This is harmless because `any()` / the gate iterate `self._evse`, but state it (or pop in prune) so framing D doesn't relitigate it.
8. **LOW (semantics, operator-visible) — No car-session discharge.** A latch set at 08:30 for an EVSE that goes OFF (car leaves) survives to a 15:00 replug at SOC 78 (D5 only fires below 77). The cost is bounded (≤3% SOC), but say it is intended.

### Tier invariant: testable and complete?
**Not as written.**
- Clause (1) ("never left paused by fill_priority while SOC ≥ threshold and forecast healthy") is **falsified by pre-existing legal paths**:
  - untrusted-SOC refusal keeps the FP claim (`:2893-2896`, `:4536-4539`);
  - plug grid_charge_on M1 hold (`:4529-4535`);
  - the onset funnel deferral;
  - the arbitrage hand-off membership that persists until FP's next tick.

  Framing D will either report develop's behavior as leaks or have to hand-wave. Enumerate the exceptions (or scope the clause to "the cycle introduces no new path..."). "Forecast healthy" is irrelevant to resume and should be dropped from (1).
- Clause (2) says "after a fill-priority resume". It must say **SOC-reached** resume with no intervening discharge event (D1-D5, observation-mode exit, restart). Otherwise it contradicts §5.3.1 and D2/D3.
- Clause (2) should also cover non-latched siblings explicitly: "a non-latched id behaves exactly as develop on every path, including arbitrage hand-off". That would have made F1 a direct falsification target.

### Parked-plan triggers
`EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` (KANBAN.md:895-906) is parked with revival trigger "EV toggle alarm fires / >2 strategy toggles/hr". The 10-11 firing was already attributed to fill_priority, not rung-1 (`trigger_check_2026_10_12_overnight`). This cycle does not fire it. L3 (tripwire=0) and L1 should attribute any toggle row by `pause_owners` so a rung-1 recurrence isn't misread as an FP regression. No other parked plan in `docs/planning` has a fill_priority revival trigger (grep of the 30 files mentioning fill_priority).

### Verdict: **FIX-REQUIRED (plan edits only)**
Must-fix before build: F1, F2, F3, plus the invariant rewrite (clauses 1-2). F4-F8 are recommended and fit in the same edit.

## Tier 3 plan review 2 (build-prediction)

- Reviewer: ura-reviewer, framing "what will the builder get wrong reading Rev 2"
- Base: develop HEAD (92f324f43 lineage). Code read: `domain_coordinators/energy_pool.py` 2668-2921, 3110-3165, 3491-3540, 4018-4060, 4384-4560; `energy_pool_owners.py` 295-320, 393-400; `energy.py` 1845-1905, 6810-6830, 7860-7895; `number.py` ~1840-1885.
- Note: the files live under `domain_coordinators/`. The plan's bare `energy_pool.py` paths are fine as shorthand.

### Verdict: FIX-REQUIRED (plan text only; the design holds)

### Findings

1. **HIGH — §7 says "SOC exactly 77 (floor) pauses". That contradicts §5.3.2 and INV-1.** The gate is `soc < effective_floor` (= `< 77`), and INV-1's band `[77, 80)` includes 77 as a no-transition value. Likely wrong build: the builder writes the §7 test first, sees it fail, and "fixes" the gate to `<=`, which shrinks the band to 78-79 and breaks INV-1 at 77. Fix: SOC 77.0 with a latch does NOT pause; SOC 76.9 pauses (INV-3).

2. **HIGH — The global `any()` in the §5.4 `_fill_priority_would_hold` brings back the arbitrage-release flap for a second, unlatched EVSE.** The house has two chargers (garage_a/garage_b), so this is a legal config.
   Repro: garage_a has the latch (SOC-resumed at 80, now 78, ON). garage_b is OFF under an arbitrage hold, SOC is 78, it is off_peak daylight, and arbitrage releases. `would_hold` is False because of garage_a, so `:3151-3155` does not hand garage_b to FP, and `:3165` turns it ON. On the next FP tick garage_b takes a first pause (no latch, `soc < 80`, is_on) and goes OFF. That on/off pair is the exact flap EV-ARBITRAGE-RELEASE-IGNORES-FILL-PRIORITY-1 fixed. "Byte-identical on the no-latch path" is true but beside the point: the mixed path regresses.
   The stated reason for rejecting per-EVSE handling ("two new publications") does not apply to the cheap version. Leave `:2776-2778` unchanged and add one per-id peer term at the hand-off: `and evse_id not in self._recently_released_by_fill_priority` at `:3151-3155`. Add the two-EVSE case to A13.

3. **HIGH — The D4 plug anchor is wrong, and the real plug site has an early return.** `:3525` is the EV `release_all_fill_priority` untrusted-SOC re-add (`self._paused_by_fill_priority.add(evse_id)`), not the plug mirror. The plug sibling is `PlugPool.release_all_fill_priority` at `:4019-4060`, and it `return`s early at `:4027-4032` when `grid_charge_on`.
   Likely wrong builds: (a) the plug D4 is skipped entirely, because the "plug sibling (:3525)" is just another line inside the EV function; (b) the clear goes after the early return, so the plug latch survives a toggle-OFF while grid-charge is on and suppresses the first pause at the next toggle-ON. Fix: name `:4019`, require the `.clear()` BEFORE the `grid_charge_on` return, and correct §5.4/§5.5/§8, which call `:3525` "plug mirror".

4. **MEDIUM — §5.6 "Both the FP set and the latch are RAM-only" is false for the EVSE set.**
   - `energy_pool_owners.py:310-312` declares `persistence_key="evse_fill_priority_paused", persistence_kind="list"`. It is saved and restored via `energy.py:1845-1905` (`_restore_registry_owner_lists`). The plug FP set (`:393-400`) has no persistence key, so it is RAM-only.
   - The restore is therefore an FP-set writer missing from the §5.5/§8 producer lists.
   - Likely wrong builds: a framing-C "reload wipes latch AND set" test that fails, or a builder who "restores symmetry" by persisting the latch, which is out of scope and adds a stale-latch-across-days path.
   Fix: state that the EVSE FP set is persisted and restored, the plug FP set and both latches are RAM-only, and that post-restart behavior is at most one first-pause toggle (acceptable). The restart test must assert exactly that.

5. **MEDIUM — The D5 position contradicts itself ("HEAD of the function" vs "`:2780`-ish").** `:2780` is AFTER the `_fill_priority_would_hold` publish at `:2776`. If the builder takes the line anchor, the publish reads a latch that D5 is about to pop, and with the §5.4 `any()` that is a wrong value one tick later. Fix: D5 runs once per tick immediately after the inert `return` (after `:2766` / `:4446`) and BEFORE `pause_conditions_global` and the `would_hold` publish. Placing it before the inert check is harmless, because D1 clears everything anyway. Pin a single location.

6. **MEDIUM — D5 and the latched-consumer floor test are redundant, so framing C's mutation drill comes back GREEN by design.** After D5, a latched id always has `soc >= effective_floor` (or `soc is None`), so `soc < effective_floor` in §5.3.2 is dead code. Neutering either one alone leaves A3/A11 green, and C will report an untested site. Fix: make D5 the single authority and write the consumer as `pause_this_tick = False if is_latched else pause_conditions_global`. Or drop D5's pop for ON chargers and keep the consumer test. Either way, the plan must name which site the A3/A11 drills target.

7. **MEDIUM — Invariant (1) in the Tier-elevation section is false on develop.** FP deliberately keeps a pause at SOC >= threshold in these cases:
   - untrusted-SOC refusal (`:2889-2892`, plug `:4537-4540`);
   - plug `grid_charge_on` hold (`:4529-4535`);
   - the peer-held clear path, where FP drops its claim but the device stays OFF.

   Reviewer D will "falsify" pre-existing behavior, or a builder will "fix" these holds. Fix: list them as explicit exemptions to (1).

8. **MEDIUM — A4 contradicts itself and can be satisfied by a hollow test.**
   - Option (a), a kwarg defaulting to the module constant, needs the constant bound in `energy_pool`'s namespace via the bare `from .energy_const import (` block (`:21-26`, exactly how `safety_margin_kwh` is defaulted at `:2675`). That is the binding A4 "forbids".
   - A test that passes `repause_band_pct=0` explicitly says nothing about production wiring: `energy.py:6817` passes kwargs explicitly and would silently run band 3 or band 0 depending on what the builder does.

   Fix: allow the bare import for the default. Require A1 and A9 to call WITHOUT the kwarg (so they exercise the shipped default of 3). Require at least one test to drive through the `energy.py` call site, or assert that the call site passes `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT`.

9. **MEDIUM — L1 and L2 cannot be executed as written.** No `fill_priority_pause` / `fill_priority_release` row type exists (grep: zero hits). `_log_charger_actuation` (`energy.py:~7880-7893`) writes `coordinator="energy_pool"`, `action=<service>`, `entity_id=<switch>`, and a description `kind=… pause_owners=…`, with no SOC. The validator will improvise, or report a vacuous PASS. Fix: specify the query as `coordinator='energy_pool'` + `entity_id` + `description LIKE '%fill_priority%'`, joined to recorder history of the named SOC entity for the `[77, 80)` band test.

10. **LOW — Anchors.**
    - `resume_soc_met` is computed at `:2773` / `:4451`; `:2866` / `:4516` are only where it is read.
    - The plug variable is `pause_conditions`, not `pause_conditions_global`.
    - The plug has no `_fill_priority_would_hold`, and the builder must not add one.
    - Plug force-charge is a kwarg (`:4392`), not `_is_force_charge_active()`.

    Say so, so the mirror is not built as a literal copy of the EV path.

11. **LOW — §5.3.2 should limit `pause_this_tick` to the `:2844` / `:4493` pause gate.** The excess-solar deferral (`:2836`) and the `would_hold` publish keep the global value. Otherwise a builder may swap the name everywhere.

12. **LOW — A13 says "mock arbitrage release path".** That is a hollow-anchor risk (#62). The test must drive the real release leg in `determine_arbitrage_actions` (`:2951`, hand-off `:3151`) and include the two-EVSE case from finding 2.

13. **LOW — The config extremes have no expected values.** `fill_priority_soc` has a minimum of 50 (number entity, `number.py` ~1857), so the floor is 47 at band 3, with the same pass/fail table as at 80. Say that band ≥ threshold and negative band are reachable only through the kwarg, and give the expected result for each (floor 0: no re-pause while latched above 0; negative band: floor = threshold, legacy behavior).

### Must-fix before build
Findings 1-9. Fold 10-13 into the same plan revision.
