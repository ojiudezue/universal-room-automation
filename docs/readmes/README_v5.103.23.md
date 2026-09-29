# v5.103.23: a person's thermostat change ends URA's temporary change; pre-arrival pre-cool now ends on arrival; a new Pre-Arrival Window setting

**Cards:** `ARRESTER-BOOT-BLIND-1` gap (2) (Part A), `HVAC-PRE-ARRIVAL-BORROW-LIFETIME-1` (Part B), `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1` C3 only (Part C, ruling Q5).
**Plan:** `docs/planning/PLANNING_hvac_w1_w2_finish.md` REV 2 + §8 rulings Q1–Q6 + Q7 ruling + Builder notes (end of the plan).
**Branch:** `feature/hvac-w1-w2-finish`. **Tier:** 2-DB with four reviews (A correctness, B precedence/lifecycle, C test authority by mutation, D adversarial completeness).

"Borrow" below means a temporary thermostat change URA makes and later puts back (pre-cool, pre-heat, an arrester compromise, a nudge, an open-door pause).

## 1. What changes for you

### A person's change now ends URA's pre-cool, pre-heat or compromise (Part A)
Operator ruling 2026-09-28: *"The person interrupts. We end and revert."*

- If someone changes the thermostat while URA's pre-cool (solar or pre-arrival), pre-heat or an arrester compromise is running, URA **stops that change without writing anything**. It is recorded as `human_interrupt`.
- URA then treats the person's change like any other override, measured against **one** reference preset:
  - **Pre-arrival pre-cool** (Q7, fix-up ruling "Home for pre-arrivals"): the preset the house would give someone ARRIVING — Sleep when the house is in Sleep or Waking, otherwise **Home**. Never Away, even when the house is empty (a pre-arrival means someone is expected).
  - **Solar pre-cool / pre-heat:** the preset the zone was in before URA started (e.g. Away), or the house target if that was already a manual hold.
  - **A compromise in progress:** the original preset of that override. The compromise is replaced, never stacked.
  - **A person fine-tuning an existing manual hold with no borrow running** (new): measured against the house's current target. The arrester now acts on these too.
- Only the setting the person actually changed counts (the other one is often a leftover URA value).
- Until the zone leaves Manual, URA starts **no new pre-cool or pre-heat** on that zone (ruling Q3), and a solar pre-cool release never writes over it either.
  - The block survives a restart: it is saved with the zone state, and restored at boot only while the zone still reads Manual.
  - A thermostat that briefly drops offline and comes back (manual → unavailable → manual) does not clear it. Only the zone going to a named preset (Home, Away, Sleep…) clears it.
- If a nudge is running on top of a pre-cool when a person changes the thermostat, the nudge still finishes, but the pre-cool underneath ends and the block above applies.
- **Not changed:** a nudge in progress still wins over a person's change (D13), and the open-door pause is not affected (Q2). An empty zone is still sent to Away by the normal occupancy rule (Q4).
- URA now recognises the thermostat echoing URA's own recent values (its last 4 setpoint writes per thermostat, within 0.5 °F) and does not mistake them for a person. A change of mode (off, cool, heat) is never read as a person's setpoint change.
- The arrester's put-back never writes `manual` any more. If the only saved preset is `manual`, the put-back is skipped and the normal occupancy rule returns the zone.
- After a restart during a nudge that began on a zone already in Manual, URA no longer writes `manual` back (D6).

### The 09-28 upstairs replay: what you will see now
1. **22:03:51** Pre-arrival for Jaya. **One** pre-cool write, from the Home setting: 76 − 2 = **74 °F**. The old 78 → 76 → 74 walk is gone.
2. **22:15:40** Someone sets 71. URA logs "override detected (within manual)", ends the pre-cool with no write, and takes the zone out of pre-arrival on the next pass. No new pre-cool starts.
3. The arrester measures 71 against **Home 76** (Q7): 5 °F cooler, a severe override.
   - If a room upstairs is occupied and the battery is at or above 85 %: 20 minutes of comfort grace, nothing written.
   - Otherwise: after the 2-minute grace URA sets **Home** (about 22:17:40). Before this release it would have been Away.
4. **23:03** A person change at that point ends the pre-cool row, so the **23:40 restart finds nothing to restore**. The observed 23:40 `stale_boot_release` that put Away back over a person's 71 cannot recur.

**Empty-zone note (A-L3).** If nobody is in the zone when the grace ends, URA sets Home (the arrival target). Then S1's normal empty-zone rule (Q4) sends the zone to Away after the vacancy delay. That is **one** Home → Away flip per interrupt, bounded by the vacancy delay (knob 48, 5 min live). It is not a loop: the zone is no longer in Manual, so no further override is booked.

**Where "baseline" comes from (A-L5).** The pre-arrival write is the baseline cool setting − 2 °F. The baseline is the last preset range URA itself wrote for the zone (`_last_emitted_range`) or, if there is none, the house's current target preset's configured Heat/Cool from the HVAC settings (e.g. Home 70/76). It is not read from the thermostat's live setting, so repeated arrival signals give the same value. It can differ from the Bryant profile values if those were changed on the thermostat itself.

### Pre-arrival pre-cool ends when it should (Part B)
- It ends on arrival, **before** the zone's normal preset update in the same pass:
  - arrival = someone in the zone by HVAC occupancy (walking through a hallway does not count);
  - on the Pre-Arrival Window timeout;
  - when a person changes the thermostat;
  - when Zone Intelligence is off.
- It is put back by restoring the saved preset (no raw setpoint write).
- It can never run longer than the window, counted from when the pre-cool itself started. Repeated arrival signals no longer stretch it to the 2-hour safety cap (`lease_expiry`).
- When the window ends it with nobody arrived, the zone's pre-arrival fans are turned off (same as a timeout). Further arrival signals for the same arrival do not start a second pre-cool. A new pre-cool can start only after someone arrives in the zone, or after a whole window with no arrival signal.
- If the HVAC coordinator is switched off, Zone Intelligence is switched off, or pre-conditioning is switched off while a pre-arrival pre-cool is running, it ends as `pre_arrival_inactive`. Turning Zone Intelligence back on inside the window does not restart it.
- The pre-cool never writes over another running borrow (also true for pre-heat now).

### New setting: `35 · Pre-Arrival Window (min)`
- `number.ura_hvac_coordinator_35_pre_arrival_window_min`, range 5–110, step 5, **default 30** (same as before). Also on the HVAC settings form as "Pre-arrival window (minutes)", next to "Pre-Arrival Trigger Sources".
- It is how long URA waits for someone to arrive after an arrival signal, and the longest a pre-arrival pre-cool can run.
- Changing it applies immediately without reloading the Coordinator Manager.
- Answer to "pre-cool is 2 hours? Is this a knob?": No. Pre-cool was meant to last until arrival or 30 minutes; 2 hours was the safety cap it fell back to because nothing ended it. Now it ends on arrival, on the window, or on a person's change.

### Occupancy clock kept while a room reloads (Part C)
The stuck-occupancy safety clock (`continuous_occupied_hours` on `sensor.ura_hvac_coordinator_zone_{n}_status`) is no longer reset on a pass where one of the zone's rooms is reloading. This includes the first pass after a restart. The exit-time back-fill is unchanged. The other three reloading-room readers stay parked (plan Appendix A has their revival trigger).

## 2. Measured before building (read-only probes)
- **P1** (`scripts/probes/hvac_borrow_end_probe.py`, 09-26 → 09-28, 3 zones): **N = 53** within-manual changes; 48 match URA's last 4 writes; **0 unmatched inside a URA echo window**. The 09-28 22:15:40 zone_2 change (71) is unmatched with the borrow live. Every nudge echo matches **only because the 0.5 °F tolerance is inclusive** (URA writes 77.5, Carrier shows 78). The gate passed.
- **P5:** 4 `climate_write` rows since 09-26 where the arrester's put-back pinned `manual` on zone_1 (the D2d defect, confirmed live). 0 boot-audit nudge rows pinned `manual` in the window (D6 fixed from code reading).
- **P1b** (fix-up 1, same probe): transitions INTO manual while a non-nudge borrow is live, since 09-26: N = 7.
  - 5 are URA echoes (they match URA's writes, all inside the 15 s window).
  - 1 is a reconnect (unavailable → manual; not a person).
  - 1 is a person (09-28 23:03:51).
  - **False-human = 0.**
- **P7** (`scripts/probes/hvac_borrow_end_p7_probe.py`): 13 out-of-window S12 borrows with no pre-arrival row within 2 min. 12 are from 08-26 → 08-29, before `ura_activity_log` begins (08-30), so they cannot be classified. The 13th (09-28 09:00:20) is a pre-arrival pre-cool that started 2.4 min after its trigger, which Part B covers. No new Part B case and no new card.

## 3. Tests
- New: `quality/tests/test_hvac_w1w2_finish_part_a.py` (91), `…_part_b.py` (52), `…_part_c.py` (7); fixture `quality/tests/fixtures/hvac_09_28_zone2_prearrival.json` (09-28 rows with the P1 class for each).
- Review record: `docs/reviews/code-review/v5.103.23_hvac_w1_w2_finish.md` (reviews A/B/C/D and fix-up round 1).
- **Per-site mutation drills:** after fix-up round 1, 142 sites, **142 red** (each neutered alone, `PYTHONDONTWRITEBYTECODE=1`, caches cleared, restored, `git status` clean). Table in the builder report / plan Builder notes.
- **`--isolate` name-diff** vs `develop` over 133 test files (every file importing hvac / hvac_override / hvac_excursion / hvac_predict / hvac_zones / hvac_setpoint / presence, plus every touched file): **CLEAN, 0 new, 0 gone**.
- Existing tests updated to the new contract:
  - the boot-audit "write manual back" test (superseded by D6);
  - the W1-B booking tests (a BANKING row / compromise timer no longer books `borrow_active` for a person; they now use an egress row);
  - the AST-slice loaders (two new `__init__` symbols);
  - the reload-suppress key counts;
  - two source greps converted to behavioural tests.

## 4. Live acceptance criteria (prospective — write the observed results back after the restart)
- **Knob:** `number.ura_hvac_coordinator_35_pre_arrival_window_min` = 30 after deploy. Set it to 20: the Coordinator Manager does not reload (sibling `last_changed` unchanged), the options hold 20, and the expiry uses 20. Then set it back to 30.
- **Pre-arrival lifetime (next pre-arrival):**
  - `hvac_excursion_events` row with `site='S12_pre_arrival'`;
  - a trigger in {`pre_arrival_arrived`, `pre_arrival_timeout`, `pre_arrival_interrupted`, `pre_arrival_inactive`, `pre_arrival_max_age`, `human_interrupt`};
  - `duration_actual_s ≤ window + 300`.
  - **Discriminates:** before this release, `lease_expiry` at about 7200 s.
- **One write:** for each `S12_pre_arrival` excursion id, exactly **1** `climate_write` row. Its `target_temp_high` = baseline − 2 (e.g. 74 with Home 76), not live − 2.
- **After a pre-arrival ends:** 0 `preset_change_deferred` rows with reason `vacancy_bypass_deferred:active_borrow` for that zone.
- **Person interrupt (next organic or operator-staged change during a pre-cool):**
  - `hvac_excursion_events` `trigger='human_interrupt'` with `restore_ok` NULL;
  - `override_detected.within_manual=true` (or `human_interrupt=true` on a transition);
  - no S12 `climate_write` for the zone until it leaves manual;
  - then the S4 / comfort-grant / S1 write per §1.
  - **Discriminates:** today, no detection row and a `lease_expiry` about 7200 s later.
- **Nudge still wins (operator-staged):** during a live zone_1 nudge, change the setpoint by 2 °F in the app. Expect:
  - `override_detected` with `within_manual=true` and `gated_reason='nudge_win'`;
  - no arrester timer;
  - the nudge restores on schedule.
- **7 days after deploy:**
  - `override_detected` rows with `within_manual=true` whose values match one of the prior 4 `climate_write` rows for the entity = **0**;
  - rows with either state not `heat_cool` = **0**;
  - S4 `climate_write` rows with `values_after.preset_mode='manual'` = **0** (P5 baseline: 4 since 09-26);
  - `startup_audit_nudge_preset_restore` rows with `manual` = **0**.
- **Part C (after the next HA restart):** for zones HVAC-occupied on both sides of the restart, `continuous_occupied_hours` at the first sample is ≥ the last sample before the stop (P6 / `hvac_reloading_room_probe.py` P3).

## 5. Not done / parked (accounted for)
- **Parked by ruling Q5:** C1 (D5 coast defer), C2 (D6 skip) and C4 (row-11 grant) of the reloading-room readers. Revival trigger in plan Appendix A.
- **Non-goals, unchanged:**
  - the energy pre-cool ratchet on its own row (card `HVAC-ENERGY-PRECOOL-RATCHET-1`);
  - boot-window reconciliation (ARRESTER-BOOT-BLIND-1 gap 1);
  - a person choosing a named preset during a borrow;
  - person `hvac_mode` changes;
  - the S7 `manual` re-pin (idempotent);
  - egress under the interrupt rule (Q2).
- **Not fixed here (B-L3, pre-existing):** a new governed override episode still cancels a pending AC-reset restore timer (`_cancel_zone_timers`). It needs its own card.
- **Known, accepted:**
  - A single human action that the Carrier feed reports as several same-second within-manual rows (e.g. 09-27 21:31:30: 68/72 → 70/80 → 70/72) books one row per step and re-dispatches each time; the last value wins. `override_count_today` counts each step.
  - Pre-existing and unchanged: a new governed episode still cancels a pending AC-reset restore timer (`_cancel_zone_timers` in the severe/normal handlers).
