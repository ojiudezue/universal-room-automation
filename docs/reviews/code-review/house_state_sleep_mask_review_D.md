# Review D — adversarial completeness (diff-blind): house-state SLEEP mask / BLE memory / observability

**Branch:** `feature/house-state-sleep-mask-ble-memory`, reviewed at `2e10e3a09` (diff base `a0cd40412`, the Rev 2 plan commit; three-dot).
**Framing:** D. State each invariant in falsifiable form, then break it across the whole reachable surface, pre-existing code included.
**Read first, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger #1–#18), the plan (Rev 2 + Rev 2.1 delta), and `AUDIT_census_arc_and_away_holistic.md` §P5 (at `1c74b467b`). `SENSOR_FLEET_CLASSES.md` was not re-read in full this pass. No sensor is reclassified here; the one finding that touches sensor kinds relies only on the CONF-list kind mapping in `occupancy_substrate.py`. No ledger claim is re-asserted.
**Note on method:** Reviewer C was running mutation drills in this same worktree during the review, and `presence.py` on disk was mutated at times. Every code read below was taken from `git show 2e10e3a09:<path>`, not from the working tree.

## Verdict: **FIX-REQUIRED**

There is one HIGH. It is pre-existing, but it is now load-bearing, and it falsifies INV-SLEEP-NOT-EMPTY in common hardware (any room with two occupancy sensors). The fix is small and local to `_zone_night_rooms`. There are three MEDIUMs: one is a cycle-introduced observability race, one is a trip-wire false page (confirms A-M1), and one is a pre-existing sibling of the SLEEP mask on path β. There are also two scope limits that the invariant text should name, and three LOWs.

---

## D-H1 — HIGH — a sleeper's room reads empty while its radar is still on (multi-sensor rooms) → nobody-home AWAY in SLEEP

**Class:** #63 coincidental equality masking a concept split ("zone tracker room view" ≠ "room is raw-occupied"); pre-existing, made load-bearing by D1.

**Mechanism (verified):**
- `ZonePresenceTracker.update_room_occupancy(room, False, kind=k)` clears **all** kinds for the room, not kind `k` (`presence.py:874-890` @2e10e3a09; its own docstring calls this "equivalent on False", which holds only when a room has one kind).
- The live feed is `OccupancySubstrate._handle_state_change` → `_dispatch(room, kind, occupied)` → `_on_substrate_kind_changed` → `tracker.update_room_occupancy(room, new_state, kind=kind)` (`occupancy_substrate.py:659-712`, `presence.py:3563-3589`). The substrate bucket is also **last-writer per (room, kind)**: `bucket[kind] = occupied` per entity (`occupancy_substrate.py:686`). So one of two same-kind sensors going off reports the kind as False even while the other is on. The seed path ORs across entities (`:271-313`), but the live path does not.
- `_zone_night_rooms` reads `tracker._room_occupied` (`presence.py` D1 helper). It inherits both defects. The P5 measurement used `binary_sensor.<room>_occupied` (the room coordinator), which does not have them, so neither P5 nor the scorecard can see the gap.

**Concrete repro (executed, production class):**
```
t = ZonePresenceTracker(hass, "Master Suite", ["Master"])
t.update_room_occupancy("Master", True, kind="mmwave")   # ZX holds still sleeper
t.update_room_occupancy("Master", True, kind="motion")   # ZV fires on a roll-over
t.update_room_occupancy("Master", False, kind="motion")  # ZV clears ~60 s later
-> t._room_occupied == {"Master": False}, t.raw_occupied == False   # ZX still on
```

**Legal-config reachable house repro:** a Wigton-shape house (the omonele tracker LOST, so census = 0, no cameras, no BLE). The Master room has `motion_sensors=[ZG-204ZV]` and `presence_sensors=[ZG-204ZX]`. This pairing is standard per SENSOR_FLEET_CLASSES: ZV is filed as motion and ZX as presence. The house is in SLEEP more than 600 s, and the sleeper is the only occupied room.
1. At 03:00 the sleeper rolls over. The ZV goes on, then off.
2. The substrate dispatches `(Master, motion, False)`. The tracker wipes the room, and `_run_inference("occupancy_change")` runs at once.
3. `any_zone_occupied_for_empty = False`, and nobody-home returns SLEEP→AWAY with the ZX still `on`.
4. After AWAY, the trackers unpin (`set_sleep(False)`), but the room stays cleared because the ZX makes no new edge. The house stays AWAY until the next rising edge, then runs ARRIVING→HOME_NIGHT→SLEEP. One flap per roll-over.

The same thing happens on the main house:
- Jaya: LD2410 and ZK are both `presence_sensors`, so they share one kind, and one dropping out wipes the room.
- Guest 1/2: ZV and MS600 next to a radar.
- Master: bed sensors and a radar.
- An unavailable blip on any one sensor of a room also wipes it (`_UNAVAILABLE_STATES → False`).

**Why this blocks ship:** the cycle's headline claims are "INV-SLEEP-NOT-EMPTY" and "helps Wigton most". Both hold only for rooms with a single sensor of a single kind. The Wigton fixture (§9.2) uses a single ZX kind, so it cannot see this.

**Recommended fix (local, no daytime blast radius):** in `_zone_night_rooms`, compute the room limb from live entity state instead of the edge-maintained provenance. A room is occupied iff any entity in `tracker._entity_to_room` that maps to it reads `on` in `hass.states`. Keep the fail-toward-holding behaviour on error. Add a test with a two-kind room (ZX on, ZV on→off) and a two-entity same-kind room (two radars, one off). Each must still hold SLEEP, and each must be mutation-anchored. Card the underlying tracker/substrate semantics (full-room clear; last-writer per kind) separately. They also make daytime `any_zone_occupied` and the WAKING sustained timer under-read, but changing them touches every zone consumer, so they need their own cycle.

---

## D-M1 — MEDIUM — `last_away_branch` and the D7 `veto_path` can read `none` for a nobody-home AWAY (capture-after-await race)

**Class:** value entry/exit (stamp-then-consume-verbatim violated); cycle-introduced exposure.

- `self._veto_path` is mirrored from the engine right after `infer()` (`presence.py:6769`). It is read again at dispatch time by `_note_away_entry` and by the D7 snapshot.
- Between the two reads, `_run_inference` awaits real I/O: `await self._count_transition()` (`:7287`) and `await self._log_state_transition(...)` → `decision_logger.log_decision` → `db.execute` (`coordinator_diagnostics.py:268-276`).
- `_run_inference` is documented as unserialized: there is no lock, and it is called from occupancy_change, census, camera, periodic and other triggers (`presence.py` B-HIGH-2 comment above the WAKING timer).
- **Repro:** a burst of room off-edges at the same moment. Tick 1 transitions SLEEP→AWAY via nobody-home and awaits the DB. Tick 2 runs with `current_state=AWAY`, takes nobody-home's already-AWAY return, which by the R2 M3 design keeps `_veto_path="none"`, and mirrors `"none"`. Tick 1 then resumes and dispatches with `last_away_branch="none"` and D7 `veto_path="none"`.
- α and β set their label on the already-AWAY return too, so only nobody-home is exposed. That is exactly the branch the D1 live acceptance and scorecard row 1 filter on (`veto_path='nobody_home'`). The race undercounts it, which biases the scorecard toward "fix working".
- **Fix:** capture the label into a local right after `infer()` and pass it to `_dispatch_house_state_change` (e.g. a `veto_path=` kwarg used by both `_note_away_entry` and the D7 snapshot). Test with a concurrent second `_run_inference` scheduled across the await.

## D-M2 — MEDIUM — the trip-wire pages falsely under a house SLEEP override (confirms A-M1 with a census-0 repro)

- `_check_sleep_raw_hold` does not consult `is_overridden`.
- `transition()` validates against the underlying `_state` (`house_state.py:212-221`). `HOME_DAY → WAKING` is not valid (`:84-88`), so D1b's WAKING proposal is rejected for as long as the override stands.
- **Repro:** Wigton S0 with the default 22→06 window. At 14:00 the operator selects SLEEP for a nap (underlying HOME_DAY) while the ZX is on. That tick has `held=True` and `held_s = 14:00 − 06:00 = 8 h > 5400`. The NM "the wake-time discharge (D1b) did not release it" fires on the first tick. The same happens with a 0-0 sleep window: SLEEP can then only come from an override, so every override past 01:30 pages.
- Pre-cycle, nobody-home would have killed that override with a false AWAY. The hold itself is now correct; only the page is wrong.
- **Fix:** add `and not manager.house_state_machine.is_overridden` to `held`.

## D-M3 — MEDIUM (pre-existing; sibling of the mask, #53 one-missed-site) — path β in SLEEP reads the masked indoor input when `lost_away_sleep_exempt` is off

- `any_indoor_zone_occupied` is mode-based (`presence.py` WS-A4 block, `t.mode == OCCUPIED`), so SLEEP-pinned zones read empty.
- `CONF_LOST_AWAY_SLEEP_EXEMPT` is an options-flow field (`config_flow.py:5630`), so turning it off is legal.
- **Repro:**
  - Config: `lost_away_sleep_exempt=False`; house in SLEEP; Frigate fleet degraded, so α is skipped.
  - Residents: one tracked resident, ACTIVE, `away` by GPS. An untracked sleeper is in Master with the ZX on.
  - Inputs: census 0, unidentified 0.
  - What β sees: `all_tracked_persons_away=True`, `indoor_blocked=False` (masked), and `not lost_away_persons_present=True`, so it returns AWAY with the sleeper's radar on.
- With the shipped default (exempt) β cannot fire in SLEEP, so this does not block ship.
- **Recommendation:** either OR the SLEEP-mode non-outdoor `night_raw` into the β indoor input (one local, same helper), or name it as an explicit exception in INV-SLEEP-NOT-EMPTY. Card it.

## Scope limits the invariant text must name (not defects of this diff)

- **S-1 (path α, ledger #12, Rev 4 guard A parked):** INV-SLEEP-NOT-EMPTY as briefed ("no branch returns AWAY") is false for α.
  - Repro: four trackers, three ACTIVE away, the sleeper's phone dead (LOST, so it drops out of the denominator), cameras healthy, no interior camera on the sleeper, house SLEEP, and Master ZX on. α returns AWAY (`presence.py:1169-1180`).
  - The plan scopes the invariant to nobody-home, which is correct. The test header and README should say "nobody-home only" so the scorecard is not read as a whole-ladder guarantee.
- **S-2 (PICK 1 carve-out, reachable):** the operator sets a house AWAY override at 21:00 by mistake, which pins every zone AWAY (`presence.py:8352-8355`), then selects `auto`, which clears only SLEEP pins (`:8342-8345`). The sleeper's ZX is already on, so it makes no new rising edge to auto-resume the zone. Then SLEEP is entered, `set_sleep` skips the AWAY-pinned zones (`:933-937`), census goes to 0, and nobody-home fires AWAY. This is documented as PICK 1 and confirmed reachable; no change requested.

## Pre-existing stuck state found while hunting INV-SLEEP-HOLD-BOUNDED (card, not must-fix)

**D-P1 — MEDIUM (pre-existing):** the zone SLEEP pin can leak permanently through a HOME_* override.
- The unpin is keyed on `current_state == SLEEP` (`presence.py:7291-7295`), and `current_state` is the override-aware effective state (`:6257`).
- **Repro (Wigton S0):**
  1. SLEEP is inferred at 23:00.
  2. At 02:00 the operator selects HOME_DAY. The underlying state stays SLEEP and the zones stay pinned.
  3. At 08:00 the rooms clear, nobody-home → AWAY, and `transition` from the underlying SLEEP is valid and clears the override. But `current_state` was HOME_DAY, so `set_sleep(False)` never runs.
  4. The zones stay SLEEP-pinned while the house is AWAY. With census 0, `has_people` (masked) never goes True, so the house never reaches ARRIVING. It stays AWAY with the occupant home until someone selects `auto`.
- This predates the cycle (the masking is identical), and the R2 M2 test enshrines the pin surviving the override.
- **Card it:** unpin on any transition whose underlying `_previous_state` was SLEEP, or whenever the new state is not SLEEP.

## LOWs

- **D-L1:** `_sleep_raw_hold_since` is written and never read; the clock uses `window_end` directly. This is dead state. Remove it, or expose it as the diagnostic it was meant to be.
- **D-L2 (DST):** `held_s = now_local - window_end` subtracts two aware datetimes that share a tzinfo object, so Python takes the wall-clock difference. It is off by 1 h only when a DST jump falls between `window_end` and now, which needs `sleep_end_hour ≤ 2`. Negligible; note it in the code comment.
- **D-L3 (INV-NO-BLE-HOLD frame):** "last Bermuda room fix" means URA's last poll with a valid area. `last_bermuda_update = now` on every tick where the area is valid (`person_coordinator.py:513`), and STALE starts only when the area sensor goes unknown/unavailable. A frozen-but-valid Bermuda area keeps the person ACTIVE with no bound. That is pre-existing, D2 is not involved, and the bound holds in URA's frame. State this frame in the invariant.

---

## Invariant checklist

| Invariant | Result | Evidence |
|---|---|---|
| INV-SLEEP-NOT-EMPTY (nobody-home only, as planned) | **LEAK** | D-H1. Holds only for single-sensor, single-kind rooms. |
| INV-SLEEP-NOT-EMPTY (whole ladder, as briefed) | LEAK, scope | S-1 (α, parked), D-M3 (β with exempt off), S-2 (PICK 1) |
| INV-SLEEP-HOLD-BOUNDED (b) | PASS for inferred SLEEP | D1b → WAKING. `night_raw` ≡ `_derived_mode` minus the override, so it agrees with `raw_occupied` and the 90 s gate sees the same signal. WAKING unpins (`:7295`) and then reaches HOME_DAY or AWAY. Sleep window 0-0: SLEEP comes only from an override (by design). 20-10 and 1-9 windows behave correctly. Restart mid-window: the restore pins (`:2462`); if the restore is stale (>1800 s), daytime rules apply. DST is hour-granular. Under an override, D1b is rejected by `transition` and the override holds; that is intended, apart from the D-M2 page. |
| INV-NO-BLE-HOLD | PASS | STALE needs `old_last_bermuda_update`, the stamp is carried and not refreshed (`person_coordinator.py:610-640`), and after decay it is set to None (`:~746`). With `decay_timeout=0`, STALE is never assigned. With a huge decay (no flow field, entry.data only), census already counts STALE persons today, so D2 only makes α/β agree with nobody-home. STALE is not restored after a restart. The frame caveat is D-L3. |
| INV-COUNTER-MATCHES-LOG | PASS (within one flush) | The increment sits after both gates and next to the only `house_state_log` writer (`presence.py:8290`; grep found no other INSERT). Its predicate matches the DAO's (`state='away' AND previous<>'away'`). The bound is naive UTC from `start_of_local_day`. Residuals are LOW and accepted by the "one flush" wording: a sub-second midnight straddle, a failed DB write, and a setup-await window on the reload path. |
| INV-BYTE-ID | PASS | With no SLEEP-mode tracker, `for_empty == any_zone_occupied`. D1b needs a SLEEP-mode zone that is raw-occupied. The trip-wire's `held` is impossible. With the kill constants off, `None` goes to the masked path. Permitted deltas: the `nobody_home` label and the attributes. |

## Must-fix list

1. **D-H1:** the `night_raw` room limb must read live entity state, plus two-sensor tests (two kinds; two entities of the same kind), mutation-anchored. Card the tracker/substrate semantics.

**Should-fix in the same fix-up:** D-M1 (thread the label as a local), D-M2 / A-M1 (gate the trip-wire on `not is_overridden`), D-M3 (OR `night_raw` into β's indoor input, or name the exception). Add S-1/S-2 wording to the invariant text. Card D-P1. Fold in the LOWs.

## Bug-class tally

| Class | Findings |
|---|---|
| #63 coincidental equality / concept split | D-H1 |
| #53 one-missed-site | D-M3 |
| value entry/exit (capture before await) | D-M1 |
| observation gating / false trip-wire | D-M2 |
| state-machine pin leak (pre-existing) | D-P1 |
