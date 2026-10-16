# Plan review 2 (Tier 3, adversarial build-prediction): PLANNING_ec_storm_and_blind_decisions.md

**Plan commit:** 5709c31a7 (branch `plan/ec-storm-blind`)
**Framing:** "What will a builder get wrong reading this?" Ambiguities, orderings, state x time seams, config extremes, stage boundaries, non-discriminating acceptance criteria.
**Verified against:** worktree source at 5709c31a7, plus the installed `nws_alerts` integration at `ha-config/custom_components/nws_alerts/`.
**HVAC / presence state-of-play docs:** not read. This plan touches no HVAC or presence surface.

## Verdict: FIX-IN-PLAN

1 CRITICAL, 5 HIGH, 7 MEDIUM, 4 LOW. The decision model is sound. The defects are in plan text a builder will take literally. C1 makes Stage L fail at its stated purpose. H1 reopens INV-1 through the overlay, and the plan's "overlay can only raise" claim hides it.

---

## CRITICAL

### C1. The outage ledger is pruned after 7 or 30 days. It cannot hold evidence across seasons.
`database.py:6268-6283 prune_activity_log` deletes `ura_activity_log` rows with `importance='info'` after 7 days and all other rows after 30 days. Stage L writes to that table with "no schema, no table" (§1a row "Durable rows"), and its stated purpose is multi-season evidence: Wind Advisory promotion, freeze outages, and the pre-onset revival trigger (§10). The plan justifies shipping L first because "Enphase keeps ~7 weeks". URA would keep 1 to 4 weeks, so less than Enphase.
**Misbuild:** the builder follows the plan exactly, ships, and every Live check passes. The first freeze in January then finds no October or November rows. `ACTIVITY_LEDGER_IMPORTANCE = RESERVE_WRITE_LOG_IMPORTANCE` doesn't help: even at the notable tier the rows last 30 days.
**Plan fix:** add D-L0. Exempt `action IN ('nws_alert','grid_outage','inclement_code_drift')` from `prune_activity_log` (a hardcoded literal in the WHERE clause), or add a dedicated table with a migration. Either way this is a real `database.py` change, so Stage L is genuinely Tier 2-DB with Review A on prune and retention. Add the test `test_prune_keeps_ledger_rows` and a Live check: a row older than 31 days survives a prune pass (seed one and run the prune service). Fix the §1a row and non-goal 6 to match.

---

## HIGH

### H1. The `_reserve_action` return shape is unspecified, so the `_last_reserve_level_desired` stamp will be pre-fold, and the overlay then writes below the floor.
D-A2 says `_reserve_action(reserve_level) -> dict | None` folds internally, and that "`_last_reserve_level_desired` keeps being stamped by `_result` from the post-fold value". `_result` stamps at `energy_battery.py:6532-6534` from its own `reserve_level` argument. When the deadband suppresses the write, `_reserve_action` returns None, so `_result` can't see the post-fold value. The builder can either re-fold in `_result`, which creates a second fold site the lint can't see and that drifts later, or leave the stamp alone, which is the literal reading and stamps pre-fold.
**Consequence of a pre-fold stamp:** the overlay append leg (`energy.py:~5470-5495`) clamps `hold_reserve = max(evse_hold_soc, _last_reserve_level_desired)`. Take reserve_soc=20, partial_floor=50, hardware already at 50 so the deadband suppresses, an EVSE hold captured at 45, and a branch emitting 20. Desired is stamped 20, the overlay appends `set_value(45)`, and the reserve drops 5 points below the floor. INV-1 says "the overlay can only raise it". That is true relative to the strategy action, not relative to the floor, because the append leg writes its own value when there is no strategy action. Write-verify's `_effective_reserve_desired` (the INV-DP5 mirror) also reads the stamp, and a pre-fold stamp gives it the wrong desire.
**Plan fix:** specify `_reserve_action(reserve_level) -> tuple[int, dict | None]` returning `(folded_target, action)`, and make `_reserve_action` the one site that stamps `_last_reserve_level_desired = folded_target`, for sighted and blind alike. Remove the stamp from `_result` and from the D-A3 blind stamp sentence. Add `test_overlay_append_cannot_undercut_floor` with the repro above. Add a mutation-plan item: stamp the pre-fold value; the test must go RED.

### H2. Stage L's hook location is unspecified, and the natural placements miss alerts exactly when they matter.
D-L1 says "on each decision tick". D-L2 says the witness is "sampled per decision tick". Two natural placements both fail:
- Inside `_inclement_decision`, or anywhere after `energy_battery.py:5776`: during a real grid outage `determine_mode` returns at the grid-disconnect `_result` (`:5774-5780`) **before** `_inclement_decision` (`:5787`). Alert rows are lost for the whole outage, which is the period the ledger exists to cover. Before Stage A, the fully-blind gate (`:5578`) also returns before the decision.
- Inside `determine_mode`: it is synchronous (§1b), but `log_activity` is `async def` (`database.py:6233`), so the builder has to invent a task-scheduling pattern inside the hot sync path.
**Plan fix:** pin the hook in `energy.py`, after `determine_mode` returns in the decision cycle (next to `_track_envoy_availability`). It reads the NWS sensor directly via `_read_nws_alerts` (not the cached classification) and `_grid_outage_active`, and writes fire-and-forget through the same `hass.async_create_task` contract as `_record_reserve_dispatch` (`energy.py:9094`). Add the test `test_ledger_logs_alerts_during_grid_disconnect_return`.

### H3. D-B3 staleness can't be measured the way the plan implies, and the integration erases alerts without going stale.
Read from `nws_alerts/coordinator.py:57-72` and `sensor.py:15-95`:
- `last_updated` is a **separate sensor entity** (`SENSOR_TYPES["last_updated"]`), not an attribute of the alerts sensor. P2(d) would answer "no" and leave the builder to guess. The guess will be HA `State.last_updated`, which only advances when state or attributes change. One steady alert for 15 minutes would then read as "stale" all day.
- On `AttributeError` the coordinator returns `{"state": 0, "alerts": [], "last_updated": now}`: an empty feed with a fresh timestamp. A partial API failure during a storm therefore looks like "all clear, fresh" and drops every hold. On any other exception the coordinator raises `UpdateFailed`, and the CoordinatorEntity goes `unavailable`.
**Misbuild:** staleness keyed on `State.last_updated` leaves `inclement_alerts_stale` stuck true. The AttributeError path drops a Winter Storm Warning hold mid-storm, and the stale branch never fires.
**Plan fix:** define stale as (alerts sensor `unavailable`/`unknown`) OR (`sensor.nws_alerts_last_updated` older than `NWS_ALERTS_STALE_S`). Build the HOLD memory (keyed by alert `ID`, plus `(NWSCode, start)` for Update chains) **unconditionally**, not only on P2(a). Clear an entry only at its own `end`, on a Cancel referencing it, or when the alert disappears from a feed that is healthy *and non-empty*. A drop to zero alerts holds the memory until `end`. Add tests: `test_empty_feed_on_attribute_error_keeps_hold`, `test_unavailable_sensor_is_stale`, `test_steady_alert_not_stale`. Correct P2(d) to ask which entity carries the timestamp.

### H4. The INV-1 legal-config repro describes an unreachable scenario that contradicts the Stage A acceptance.
§3 INV-1 gives the repro: "fully blind, top-rate de-escalation with CFG on, **uncorroborated off-peak watch** (today this writes 20; after the change it writes 50)". Off-peak is never top rate, so de-escalation can't fire there. The Stage A acceptance says the top-rate uncorroborated watch is allow_discharge and writes **20**. Reviewer D and the builder will each write a test from INV-1, see it fail, and either "fix" the code by flooring under allow_discharge (wrong) or doubt the fold.
**Plan fix:** replace the INV-1 repro with the reachable case: `reserve_soc=20, partial_floor=50`, fully blind, October 18:00, CFG on, a *corroborated* (or recoverable) watch, so partial_hold at top rate. Today it writes 20 at `:5658`; after the change it writes 50.

### H5. A de-escalation that raises the reserve never arms the release, so blind ends at the floor.
D-A3 captures `_blind_pre_raise` only in rule 2 (Hold). Rule 1 (de-escalation, folded) can also raise the reserve: reserve_soc=20, floor 50, hardware 20, so it writes 50. On the next tick CFG is off, so rule 2 runs with `base = _last_reserve_level_desired = 50` and `max(50, 50)`, which is no raise and no capture. When the hazard ends while blind, rule 3 needs `_blind_raised`, finds it unset, and doesn't release. The reserve stays at 50 for the rest of the blind episode. INV-2's falsifier requires "with the episode flag set", so the leak passes INV-2 as written.
The reverse order also needs a rule: hazard end at top rate with CFG still on means rule 1 wins, writes reserve_soc and leaves `_blind_raised` set, and rule 3 then fires on a later tick.
**Plan fix:** any blind write whose folded target is above the pre-write base captures `_blind_pre_raise` (first raise only) and sets `_blind_raised`, whichever rule wrote it. A de-escalation write at or below `_blind_pre_raise` clears the flag. Drop "with the episode flag set" from the INV-2 falsifier. Add `test_blind_deescalation_raise_arms_release`.

---

## MEDIUM

### M1. "max-known end" (§4) versus per-alert `end` (D-B1): the aggregate rule is unstated.
Today `AlertClassification.expires_at = min(expiries)` across contributors (`inclement.py:263`), and `compute_solar_horizon` (`:381-389`) and `_overnight_fallback` (`:438-453`) consume it. §4 says "max-known end"; D-B1 defines only a per-alert `end`. One builder keeps `min`, so a Notice with an early end shortens a Warning's horizon. Another switches to `max`.
**Fix:** state the aggregate explicitly. Use `max(end)` over **HOLD-class contributors only**, so NOTICE alerts never contribute. List both consumers with the behavior change, and add a test with two overlapping holds whose ends differ.

### M2. Blind hold rule: `base` can be None, and a None `current_reserve` defeats "one write".
"`base = _last_reserve_level_desired` (or the write-leg state when None)". After a restart while blind, both can be None, because the cloud number is often unavailable during an outage, and `max(F, None)` raises. If `current_reserve` is None, `_reserve_action`'s deadband (`current_reserve is None or …`) writes every tick. That breaks INV-2's "zero reserve actions after the first" and adds a governor row every 5 minutes.
**Fix:** if `base` is None, treat it as `F` (write F once and arm no release). For "one write" under an unreadable hardware value, compare against `_last_reserve_level_desired`, not the hardware. Test `test_blind_hold_unreadable_reserve_writes_once`.

### M3. Stage A Live (b) and (c) are vacuous or self-contradicting.
- (b) "zero `reserve_write` rows whose reason starts 'Envoy unavailable'". D-A3 doesn't define reason strings for hold or release writes. A correct blind *hold* write keeps today's reason, "Envoy unavailable — holding", so it fails the check, or the builder renames the reason to pass. Either way (b) observes a string, not v5.17.5 behavior. It is also vacuous when no blind episode happens.
- (c) "`floor_ok` query returns 0" gives the same result under the fix and when no blind partial-hold episode occurs.
**Fix:** define the three blind reason prefixes ("Blind hold —", "Blind release —", "Blind de-escalation —"). Rewrite (b): for each `reserve_write` row in a window where `blind_hold_active` was true, the reason starts with one of those prefixes, and there is at most one hold row per episode. Mark (c) conditional, with a fallback in-suite proof, so the absence of an episode reads as "not observed", not PASS.

### M4. Witness episodes across restart and witness validity are unspecified.
RAM witness state starts unknown. After a boot mid-outage, is the first `True` a transition? Then the restore writes a close with no open. Separately, `_grid_outage_active` reads `switch.enpower_*_grid_enabled == "off"` (`energy_write_verify.py:1821-1850`). Nothing shows that this switch flips when the utility drops. It may only reflect the operator's grid-connect permission.
**Fix:** treat a boot as prior=None. The first `True` after boot opens the episode with `opened_at_boot=true`; a close without an open writes a close row with `episode_id=null`. P4 must check that the switch went `off` during at least one calendar off-grid event (discriminating); otherwise the local witness is dropped and the sweep is the only source.

### M5. Stage B's Onset gating removes holds the house has today. The plan doesn't state this as a safety change.
Today an alert is active from `Sent` until `min(Ends, Expires)` (`inclement.py:205-214`). A Winter Storm Warning issued 18 h ahead holds from issue. After D-B1 it holds only from Onset, so the battery can drain at peak and enter the storm low, and the parked pre-onset floor is the only mitigation. This is operator doctrine, so it is not a defect. But Stage B "leaves the house safe" only if the operator accepts it knowingly, and the builder needs to know it is intended. Otherwise a reviewer "fixes" it.
**Fix:** add to Stage B a stated behavior change, an acceptance line ("WSW Sent 06:00, Onset 21:00: allow_discharge at 18:00; today: hold"), and an operator-checkpoint line.

### M6. The D-B3 memory key `(code, start)` doesn't match how Update and Cancel chains reference alerts.
Update and Cancel messages carry new IDs. A Cancel's `onset` can differ from the original's, and Cancels for exact-name-only rows (where P3 left the code unverified) have no code. The key will miss Cancels, and the hold persists to `end`.
**Fix:** use the alert `ID`. Clear on a Cancel with the same event name and an overlapping window, and log an `inclement_memory_cleared` row so drift is visible.

### M7. Stage C corroboration window shrinks during the hold and can flap full↔partial.
The window is `[now, hazard end]`. As `now` moves past the coldest hour, `min_temp` rises above 28 °F, and a forecast-confirmed watch drops from full_hold to partial mid-event.
**Fix:** latch: once confirmed for an alert ID, it stays confirmed until that alert's `end`. Add a test.

---

## LOW

- **L1.** "Set `_tick_reserve_floor` immediately after each `_inclement_decision` call": specify that the assignment goes in `determine_mode` at the two call sites, not inside `_inclement_decision`, which `_inclement_attrs` also reaches.
- **L2.** INV-4 hour sweep: require tz-aware local iteration including both 2026 DST transition days, and a season-boundary day. A naive-datetime sweep passes and hides a DST bug.
- **L3.** Envoy flaps break blind episodes up, so a sighted tick resets the flags and the next blind episode can't release (it inherits a floored base). Add this to §12 as known limit 13, so a reviewer doesn't file it as a bug.
- **L4.** INV-5 "exactly one `nws_alert` row per ID per boot" combined with the RAM seen-set: specify that the seen-set is pruned of IDs that leave the feed, so a long uptime doesn't grow it without bound.

---

## Checks that passed (no finding)

- Fold order (fold, then clamp, stand-down, deadband) is unambiguous and correct against `_result` `:6352-6395`.
- Config extremes in §12 (floor > target, reserve_soc > floor, partial 100, sighted full hold below reserve_soc) hold under the fold as specified. Partial floor 0 reduces to `reserve_soc`, which is correct.
- The lint change is right: the literal moves from `determine_mode` and `_result` into `_reserve_action`, and `RESERVE_SET_VALUE_WRITERS` (`energy_const.py:2307`) counts per function.
- No `_result` caller exists outside `energy_battery.py`. `_inclement_decision` has one call site (`:5787`).
- Stage A can ship alone and leaves the house safe (it only adds floors and blind writes that are floored or restoring). Stage D is separable.
- `Type` = CAP messageType is confirmed at `nws_alerts/coordinator.py:166`. Keeping Update and dropping Cancel is correct.
