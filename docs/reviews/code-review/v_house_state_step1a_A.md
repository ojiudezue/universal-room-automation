# House-state step 1a: Review A (local correctness)

Branch `feature/house-state-step1a` @ 1c602a1b, diff base develop 7d826060 (verified: `git merge-base HEAD 7d826060` =
7d826060; three-dot diff). Plan `PLANNING_house_state_axes_step1.md` rev 3 Part A. Tier 3, framing A: arithmetic,
None handling, edge cases, config extremes, per site. Mandatory presence docs read completely
(`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`). No pytest run (framing C owns the suite).

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| A-H1 | **HIGH** | `domain_coordinators/presence.py` `_residency_residents` (`str(p) if startswith("person.") else f"person.{p}"`) | `PersonTrackingCoordinator.tracked_persons` is read from `entry.data` (`person_coordinator.py:166`), and on the live install that list holds **names**: `['Ezinne', 'Oji Udezue', 'Jaya', 'Ziri']` (live `core.config_entries`; options hold the entity ids, but the person coordinator does not read options). The person coordinator itself maps a name with `person.{name.lower().replace(' ', '_')}` (`person_coordinator.py:978`). The new helper only prefixes, giving `{person.Ezinne, person.Oji Udezue, person.Jaya, person.Ziri}`. No live `person.*` id matches. Repro (run on the branch): that resident set, then `tracker.on_event("person.oji_udezue", "not_home", "home", 5000.0)` returns `None`. Effect live: the D2 producer writes **zero** records and rows; `get_residents_home()` is always empty, so the residents-home sensor reads 0, the house-state `residents_home` attribute reads 0, and the ARRIVING arm never sees evidence (every ARRIVING exterior alert resolves CRITICAL; the D0 added-pages budget was measured with real evidence, so live paging exceeds it); the weekly writer-health check sees two BACKED types at 0 rows and pages a dead producer outside away / vacation weeks. Tests miss it because every fixture uses entity ids (`test_residency_wiring.py:52-53`, `tracked_persons=[OJI]`), a fixture shape production never has. Fix: normalise each entry exactly as `person_coordinator.py:978` does (`person.` + `name.lower().replace(' ', '_')` when not already prefixed), and add a test with the live name shape (`'Oji Udezue'`, `'Ezinne'`). | #63 concept split hidden by a fixture / #53 (producer computed, never consumed live) |
| A-M1 | MEDIUM | `domain_coordinators/residency.py` `recent_arrival` | A counted arrival stays evidence for 300 s even after the same person's departure. Repro (run on the branch): `home -> not_home` at t=10000, `not_home -> home` at 10030 (counted True, `not_home -> home` always counts), `home -> not_home` at 10045 (a GPS bounce at the geofence edge); `recent_arrival(300, 10200)` returns the 10030 arrival. An exterior-person alert during body-only ARRIVING at t=10200 resolves MEDIUM instead of CRITICAL with nobody home. Fix: skip an arrival whose person has a later departure record (`last_event[pid].kind == departure` with a later `edge_ts`), plus a test. | edge case in the evidence leg |
| A-M2 | MEDIUM | `presence._persist_residency_event` -> `database.log_memory_episode` (`database.py:10722-10742`) | **Open question ruling: yes, key per edge.** The in-memory gate drops any repeat of `(node_id, episode_type)` inside `MEMORY_EPISODE_DEDUP_WINDOW_S` (60 s, `const.py:6001`). Residency records are already one per raw edge (old != new), so the window only loses real edges: `home -> not_home -> home -> not_home` inside 60 s writes one arrival and one departure row of two each. The RAM ring (the only trust reader) is unaffected; the DB rows and live check L1 ("rows match recorder edges") are. `dedup_source_ref=True` alone does not help: the window check runs first. Fix: add a `window_dedup: bool = True` kwarg to `log_memory_episode` (default keeps every existing caller identical), and have residency pass `window_dedup=False, dedup_source_ref=True` with its existing `source_ref` `"{pid}@{edge_ts}"` (unique per edge). Test: arrival / departure / arrival in 20 s -> three rows. | #53 (record computed, row dropped) |
| A-L1 | LOW | flip ledger D5 circling rows | "Switch in body" is allowed by the plan's fixture rule, so the three circling tests are legal. The finding they expose (hop 1 pass_by and hop 3 circling are both HIGH in production, so the MED-2 "severities differ" pin does not hold live) is pre-existing and needs its own card before close; it is not in the ledger as a card yet. | #62 (test passes on a non-production config) |

## Cleared (holds because)

- **D1 rule extraction is verbatim.** `really_away` / `counted_return` / `update_last_real` / `stamp_restored`
  (`arrival_edges.py`) match the removed lock bodies line for line: boot window first, `None` or restored -> True, home ->
  False, `>= min_away_s`; ledger restamp only on missing / different / restored; same `_UNREAL` set as the lock's
  `_UNREAL_STATES` (`security_lock_regime.py:107`). `new_val=None` still stamps `(None, ts, ...)` on both paths
  (byte-identical). Lock passes `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN * 60`; producer passes `RESIDENT_RETURN_MIN_AWAY_MIN * 60`;
  aliases are equal (15). `_apply_arrival`'s `_really_away` calls (1303, 1305) unchanged. No test patches `_really_away`.
- **Producer arithmetic.** Arrival from the PRE-update ledger, then `update_last_real` for every event, resident or not.
  `home -> unknown` / same-state -> no record; departure only to a real non-home value. Boot flag `ts < setup + 600`.
  `recent_arrival(within_s <= 0)` -> None (the 0 kill semantics); negative age skipped.
- **`_edge_decision` truth table** (reason x new x operator): waking -> release iff sleep-like; guest_night + home_night
  in window -> guest_yield_hold (before the HOME_* arm, so an operator HOME_NIGHT in the window is held, plan R26);
  HOME_* / arriving -> `none` with reason NONE (no hand-lock unlock, delta L2), `release` iff operator, else
  `house_edge_ignored`; sleep / vacation / guest-in-window engage unchanged. The ignored return precedes the
  manual-unlock clear. `override_clear` is emitted only by `HouseStateMachine.clear_override`
  (`house_state.py:314`), whose callers are the select, the two services and `set_house_state_override("auto")`; all
  operator.
- **Boot recheck.** `operator` is never passed, so a `boot_recheck` release is reachable only from WAKING (trip-wire
  exempt). A `boot_unknown` lock in an awake house is `house_edge_ignored`; `boot_unknown` is sleep-like
  (`security_lock_regime.py:105`), so `_boot_rebuild` arms the backstop with `allow_immediate` (daytime past deadline ->
  immediate; 23:00-24:00 restart -> next morning, as README delta L2 states).
- **saw_empty.** Set on old or new in {away, vacation, arriving} with reason != NONE, not operator-gated; an engage edge
  that sets it is cleared by `_set_engage_reason`. Legacy `garage_arrival_taint: True` maps to True; the two legacy keys
  are not written. `_boot_gap_return_page` and `_uncounted_return_pages` conditions match plan items 5-6.
- **Trip-wire** no longer reads any episode flag and never calls `_edge_decision`.
- **Severity resolver** (`const.py` arriving arm): evidence None -> MEDIUM, False + switch -> CRITICAL, True -> MEDIUM,
  switch off -> MEDIUM. CRITICAL-first rows return before it. `_get_persons_home` returns 0 with the switch False, so
  HOME_* / GUEST rows equal production (INV-NO-LOWER holds by construction). Evidence try/except returns False and the
  INFO line still logs.
- **Phone-left-behind slug.** `person_slug("person.oji_udezue")` = `oji_udezue`; the sensor's unique id is built from
  `"Oji Udezue".lower().replace(' ', '_')` (`binary_sensor.py:122`, `:2124`): match. Fail-open paths return False.
- **Occupancy getter** compares `.value` strings against `away` / `vacation`; same result as the enum compare.

## Flip ledger check

Every D4 row is a rewrite of the same scenario to the new rule, or a rename for a plan-stated behaviour change (delta L2,
M2, M3). The three re-points to `override_set` are justified by the original docstrings: `test_override_sleep_to_home_releases`
(name), `test_manual_sleep_to_home_night_in_window_releases` ("an override to HOME_NIGHT"),
`test_guest_night_home_night_outside_window_releases` ("cannot come from inference; forced"). No test was bent to the code.
D5 rows follow the fixture rule (real getters on `coordinators["presence"]`, no `.presence` attribute). See A-L1.

## Verdict

**FIX-REQUIRED.** Must fix: **A-H1** (resident set never matches live; producer and residents-home dead). Should fix in
the same pass: A-M1, A-M2 (with tests), card A-L1.

| Sev | Found | Bug classes |
|---|---|---|
| HIGH | 1 | #63 / #53 |
| MEDIUM | 2 | edge case; #53 |
| LOW | 1 | #62 |
