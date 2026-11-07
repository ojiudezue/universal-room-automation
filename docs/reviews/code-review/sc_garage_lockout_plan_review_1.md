# Plan review 1 of 2: COMPLETENESS — PLANNING_sc_garage_remote_lockout.md (rev 2 + operator answers)

Card: GARAGE-REMOTE-LOCKOUT-SCHEDULE-1. Reviewer framing: completeness (independent re-enumeration). Read-only review: no code or plan edits.

Mandatory reads done completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 835 lines, including the §10 ledger) and `docs/architecture/SENSOR_FLEET_CLASSES.md`. No ledger claim is re-asserted below. Code read: `domain_coordinators/security.py`, `house_state.py`, `manager.py` (intent batch), `person_coordinator.py` (BLE pre-arrival), `cover_ownership.py`, `optimization.py` / `optimization_llm.py` dispatch, `automation.py` / `hvac_covers.py` cover writers, `notification_manager.py` companion actions.

**Verdict: FIX-PLAN.** Phase 1 has two HIGH gaps (restart loses `reason`, so a night restart strands the lockout; SC disable / observation-on leave an engaged lockout with no release path). Phase 2 has two HIGH gaps (INV-1 is false repo-wide through the optimizer; the pre-existing sweep makes an auto-open a remote-close hazard). The fixes are all plan text. None needs a redesign.

## Findings

### HIGH

**H1. Restart loses `reason`, so a SLEEP lockout is never released by wake or backstop (INV-4 can be falsified).**
`reason` is "in memory only" (§6.1). The boot rule (rev 1 §5, commit ea4bc6a8 line 135) only "reads, maybe releases; never engages". It does not rebuild `reason`. After a restart, wake release and the 07:00 backstop both key on `reason == sleep` (§6.1 rows 4-5), so neither fires.
Repro: lockout ON at 22:30 SLEEP → HA restart 02:00 (`reason` = none, both locks still `locked` on the opener) → SLEEP → WAKING at 06:40 → no release; 07:00 → no release. The lockout stays on all day until some resident arrival.
Fix: at boot, if a lockout reads `locked`, rebuild `reason` from the restored house state (SLEEP gives sleep, VACATION gives vacation) or persist `reason`. Add `test_restart_mid_sleep_backstop_still_releases`.

**H2. An engaged lockout can be left with no release path in two legal states.**
(a) **SC coordinator disabled.** `manager.async_set_coordinator_enabled(False)` calls `_cancel_listeners()` (`manager.py:1279-1283`), and `_async_process_batch` skips disabled coordinators (`manager.py:971`). The person listener, the arrival signal (`security.py:2113`) and the hazard path (`:2057`) all return on `not self._enabled`. If SC is disabled at 23:00 with the lockout on, every resident arriving at 03:00 is locked out.
(b) **SC observation mode turned ON while engaged.** `evaluate()` returns `[]` (`security.py:825-831`), so the arrival release is suppressed.
Under §5.2, "fail-safe = released". Neither state is in the kill-switch semantics, and INV-2's "not in observation mode" exemption hides (b).
Fix: either release once on the SC-disable edge and on the observation-ON edge (as for the kill switch), or name both as accepted residuals with an NM. Add tests for each.

**H3 (Phase 2). INV-1 is false repo-wide: the optimizer can call `cover.open_cover` on a garage door.**
`OPTIMIZER_ALLOWED_DOMAINS_DEVICE` includes `cover` (`const.py:4364-4366`). `optimization.py:4989` dispatches the proposed service directly. SC's veto `honor_optimizer_intent` blocks only `lock.*` and `alarm_control_panel.*` (`security.py:1903-1909`). It ACKs `cover.*`, and the dispatch path makes no `cover_ownership` check (grep: 0 hits in `optimization*.py`).
Repro: optimizer autonomy at L2 (a legal setting; the default is shadow, `const.py:4299`) and an LLM finding that proposes `cover.open_cover` on `cover.ratgdov25i_dbfe2a_door`. The intent is ACKed and the door opens.
INV-1 is worded as "code added by this cycle", so it holds as worded. But Phase 2's `test_only_auto_open_module_emits_cover_open` ("drives every SC path") cannot see this path, and the cycle's safety case is "only one writer raises a garage door".
Fix: before D6, make `honor_optimizer_intent` veto any target where `cover_ownership.is_security_owned_cover()` is true, add a test, and restate INV-1 over the whole integration.

**H4 (Phase 2). The pre-existing sweep turns an auto-open into an unattended remote close, the hazard the plan itself names.**
`_evaluate_lock_check` closes any `open` garage on a fixed `timedelta(minutes=lock_check_interval)` timer (`security.py:702-709`, `:1705-1723`; live interval 60). It has no occupancy, obstruction or "just opened" check. The sweep tick can land at any point in that window, so roughly 2-3 % of auto-opens would see a close command within the first 1-2 minutes, while the car is still pulling in.
The plan rejects auto-close because of obstruction risk (§6.2) but leaves this path in place ("carded, not fixed here", §3.2, §9). For Phase 1 that is fine (no new opens). For Phase 2 it is not.
Fix: make `SC-SWEEP-CLOSES-OPEN-GARAGE-1`, or at least a sweep hold-off on a door URA auto-opened, a prerequisite of D6. Add a test that a sweep inside `AUTO_OPEN_NO_ENTRY_S` after an auto-open emits no `close_cover`.

### MEDIUM

**M1. The person listener snapshots `person.*` at setup.** `_setup_geofence_listener` subscribes to `hass.states.async_all("person")` once (`security.py:1989-2008`). If it returns empty at setup, it logs at debug level and returns, so P1 is silently dead until the next reload. `manifest.json` does not list `person` among its dependencies, so the setup-time ordering is UNVERIFIED. Fix: the regime should subscribe to its own `CONF_SECURITY_LOCKOUT_RESIDENTS` ids, resolved explicitly, and fail loudly if any are missing.

**M2. A GUEST night never engages, and this contradicts the presence doc.** `VALID_TRANSITIONS[GUEST]` = {HOME_DAY, HOME_EVENING, HOME_NIGHT, AWAY} (`house_state.py:116-121`). There is no SLEEP, and `transition()` enforces the table (`house_state.py:219-221`). The presence doc §7 says "GUEST → SLEEP transition had been missing; the latch now survives the night" (v5.16.0). The code has no GUEST → SLEEP edge. **The code wins; the doc must be fixed or the latch mechanism cited.** For this plan: with a guest staying (live now, per operator travel memory), house reads GUEST overnight, so no lockout engages. That fails in the safe direction but misses the goal. The plan should state it (§4.2 / non-goals) and add `test_guest_night_does_not_engage`.

**M3. P5 (approach zone) has no producer mechanics, and a passive zone probably gives no signal.** An HA zone entity's state is the count of persons whose state is that zone. A passive zone never becomes a person's state, so `zone.home_approach` likely reads 0 for good. (This is my reading of HA behaviour, not verified in this pass; D0 Q2 must confirm it.) If so, P5 / A1 can only come from computing distance from tracker lat/lon against the zone centre and radius. The plan names no such code path, knob or test. `_handle_person_state_change`'s `not_home → zone` branch (`:2037`) fires only for non-passive zones. Fix: specify the P5 producer under both outcomes (passive gives a haversine on fixes, non-passive gives a state edge), or make P5 conditional on D0.

**M4. HA `proximity` has no single `proximity.*` entity to point at.** The plan greps `proximity\.` and adds a single `CONF_SECURITY_AUTO_OPEN_PROXIMITY_ENTITY`. Current HA proximity, since its UI-config migration, exposes sensor entities (distance, direction of travel, per tracked entity). That is from my memory of HA and is UNVERIFIED. If true, A2 needs two entities, and the config field and D0 Q3 wording must change. Verify against HA docs before D6.

**M5. The recovery path and INV-1A contradict each other on whether an opener accepts `open_cover` while locked.** §4.1 says "the HA app / dashboard can always open the door while the lockout is on". §6.2 says "open only once the release read-back passed …; otherwise the open would be refused by the opener". Only one can be true for each model. This is load-bearing for the family recovery path: an HA-down night is also unrecoverable through the garage, because the lockout blocks remotes and keypad and HA cannot release. Fix: add "HA open_cover with lockout ON" to D5b on both doors. Name the HA-outage-at-night residual (front-door key only).

**M6. INV-1A lacks an alert / lockdown gate.** `_generate_lockdown_actions` closes garages on an alert (`security.py:1642-1672`, callers `:1043`, `:1578`). Nothing in INV-1A stops an auto-open during an active intrusion alert (`_active_alert`) or right after a lockdown close. Fix: add "no active security alert / lockdown within N min" to INV-1A and to the D framing's mutation list.

**M7. The no-entry NM text "Tap to close" implies a new close writer.** NM companion actions today are only ACK / STATUS / SILENCE (`notification_manager.py:3373-3400`). A close button would be a new `cover.close_cover` caller, which INV-1B forbids. Fix: drop "tap to close" or make it a deep link to the dashboard, and say which.

**M8. A sweep branch in review collides with this plan.** `SECURITY-LOCK-SWEEP-RETRY-CAP-1` (status review, kanban line 33601) changes `_evaluate_lock_check`. This plan states the sweep "stays" byte-identical and Phase 2 depends on its garage-close behaviour (H4). Sequence the two explicitly and rebase this plan's line cites after it merges.

**M9. Two sleep windows.** The plan uses the CM sleep window 22→06 and `sleep_end_hour` 6 for the backstop and re-engage. Presence infers SLEEP on its own hours: 23→06 by default (presence doc §2), and the live value is unread. The two agree today on the end hour only. That is a coincidental-equality smell (Bug Class #63). State which source the regime reads, and test with the two windows different.

### LOW

- **L1.** §6.1 lists "SLEEP → WAKING / HOME_*". SLEEP's valid targets are only WAKING and AWAY (`house_state.py:108-111`), so HOME_* arrives only via override (`set_override` bypasses the table, `:267-290`). Say so and test the override edge. Also add explicit rows: SLEEP → AWAY with `reason=sleep` (kept until arrival or backstop) and VACATION → AWAY (kept until arrival). Both are reachable today and silent in the table.
- **L2.** P2 is gated by `person_coordinator._pre_arrival_enabled` (`person_coordinator.py:209`, `:1111`). It fires only when BLE resolves a room, so it is late. Presence observation also suppresses P2, P3 and every house-state edge (`switch.py:3512-3517`; `presence.py:8512-8518`). Document that P2 is a corroborator, not the lead.
- **L3.** `_handle_person_arriving_signal` returns on observation before any branch (`security.py:2115`), so the "observation records would" behaviour (D2 test) does not happen on the P2 path unless the regime branch is placed above that return. Name the placement, as was done for `:1104` and `:2015`.
- **L4.** Knob ladder gaps: the "shadow NM" knob is mentioned in §6.2 but missing from §7. The no-entry evidence sensors (garage / mudroom motion, interior BLE room) have no CONF field. The read-back retry count is not stated. The kill-switch restore direction under `unavailable` is not stated for Phase 1 (it is for the Phase 2 shadow switch).
- **L5.** G4 (0 FP over one 7-day window with N ≥ 8) has little power on its own. It is acceptable because D7 adds 10 more arrivals, but say that G4 is a screen, not the proof.
- **L6.** INV-2's 5 s budget runs through a 100 ms intent batch (`manager.py:50`, `:939-944`). That is fine, but the oracle should measure from the event to the `lock.unlock` call, not from the intent being queued.

## Re-enumeration results

### Writers to garage covers / lockout locks (today plus after the change)

| Site | Service | Gate | In plan? |
|---|---|---|---|
| `security.py:1660-1670` lockdown | `cover.close_cover` | alert path | yes |
| `security.py:1705-1723` sweep | `cover.close_cover` | fixed timer, no occupancy check | yes, carded (H4) |
| `security.py:2084-2091` hazard egress | `lock.unlock` on `_lock_entities` only | `_enabled`, observation, config | yes (extended) |
| `automation.py:2486/2583/2631/2715` room covers | open/close | `cover_ownership` filter by device_class garage/gate | **no**: INV-1 depends on both covers reporting `device_class: garage` (unverified live; HVAC-GARAGE-GUARD-STAGED-SUNSET-1 observed it holding on 10-11) |
| `hvac_covers.py:669-699` | open/close | `_is_garage_cover` → `cover_ownership` | no (same dependency) |
| `optimization.py:4989` (LLM / L2 dispatch) | any `cover.*` | SC veto lets `cover.*` through | **no (H3)** |
| NM companion actions | none for covers or locks | — | n/a (M7) |
| Outside HA: Garage B moved with no HA call on 10-11 19:07 (kanban HVAC-GARAGE-GUARD-STAGED-SUNSET-1) | opener-side | — | should be noted: an opener-side automation or wall button can open regardless |
| New: regime (`lock.lock` / `lock.unlock`), `AutoOpenController._fire_open` | — | — | yes |

Before INV-1 counts as proven, `cover_ownership.py` should be cited and a D0 check added that both covers read `device_class: garage`.

### Arrival inputs

| Input | Handled? |
|---|---|
| `not_home → home` | yes (P1) |
| `unknown → home` | yes (D3 test) |
| `unavailable → home` | add a test |
| `<named zone> → home` (non-passive approach zone) | add a test |
| `old_state None` (entity added after a restart) | no; covered only by the boot rule |
| Person whose GPS stayed frozen `home` (no edge; ledger #26 shape) | only P2 (BLE) catches it |
| BLE P2 | yes (gated, late) |
| Geofence P3 | yes (suppressed under Presence observation) |
| Face P4 | yes (sparse) |
| Approach P5 | under-specified (M3) |
| Restart | boot rule, but `reason` is lost (H1) |

### House-state edges

| Edge | Plan |
|---|---|
| HOME_NIGHT → SLEEP | engage |
| SLEEP → WAKING | release |
| SLEEP → AWAY | silent (L1) |
| override → SLEEP / VACATION / HOME_* | the D2 adapter dispatches (`house_state.py:267-317`); needs an explicit test |
| AWAY → VACATION | engage |
| VACATION → ARRIVING / AWAY | no release until arrival (L1) |
| GUEST overnight | never SLEEP (M2) |
| Presence boot-settle or observation | no signal at all (`presence.py:8507-8518`) |

### Early returns that would starve the regime

| Line | Return | Covered by plan? |
|---|---|---|
| `security.py:1104` | `if not self._auto_follow_house_state: return` | yes |
| `security.py:2015` | `if self._armed_state == ArmedState.DISARMED: return` | yes |
| `security.py:2113`, `:2115` | arrival signal: `not _enabled`, observation | no (L3) |
| `security.py:2020` | `old_state is None` | no |
| `security.py:815` | `evaluate()` routes `house_state_change` only when auto-follow is on; there is no branch for a new intent source | the new `lock_regime` source needs its own branch, which the plan implies but does not state |
| `manager.py:971` | disabled coordinators skipped | no (H2a) |

### Kill-switch semantics vs other sections

The changes are consistent across §5.2, §7 and D1. Two gaps:
1. Whether the OFF-edge release goes through `evaluate()` (so SC observation suppresses it) or is a direct call is unstated.
2. Restore `unavailable` direction is unstated (L4).

There is no conflict with Phase 2, because auto-open requires the lockout to be released or unlocked first.

### Parked-plan / card triggers this cycle touches

| Card | Status | Relationship |
|---|---|---|
| `SECURITY-LOCK-SWEEP-RETRY-CAP-1` | review | collision (M8) |
| `SC-SWEEP-CLOSES-OPEN-GARAGE-1` | new card | must become a Phase-2 prerequisite (H4) |
| `GARAGE-COVER-FLAP-1` | done; refuted | blaQ has no reed input, so state comes from the Security+ bus; relevant to the "door reads closed" gate |
| `HVAC-GARAGE-GUARD-STAGED-SUNSET-1` | done | shows opener-side movement with no HA call |
| `ROOM-COVERS-NO-GARAGE-DOOR-GUARD-1` | — | the device_class guard INV-1 relies on |

No parked deliverable is fired by Phase 1.

### Phase 2 gate data availability (INV-1A)

| Gate | Data available? |
|---|---|
| Toggles / shadow / sleep sub-toggle / allowlist | new, OK |
| Door `closed` | yes (opener state) |
| SC observation | yes |
| Genuinely away ≥ 15 min | yes (person + `_person_was_away`) |
| Already home past the debounce | yes |
| `fast_approach` speed / accuracy / fix age | tracker attributes exist in the recorder (no recorder exclude found); `speed` on iOS UNVERIFIED (D0 Q4) |
| Approach zone and proximity | **no history exists until the operator creates them at D0**, so G2 (approach form) and G6 cannot be evaluated on the first D0 pass |

D0 is sufficient for G1, G3, G4 and G5 on GPS fixes, and for G2 in the home-ring form. It is not sufficient for any approach-zone or proximity threshold until after ≥ N post-config arrivals. The plan half-acknowledges this (Q2 re-run) and should state it as a gate on D6's approach form.

### Non-goals

Clear. Add GUEST nights (M2) and the HA-outage-at-night residual (M5).

## Must-fix before build dispatch

- **Phase 1:** H1, H2, M1, M2 (doc fix plus a stated non-goal), M5 (D5b HA-open test), M8, M9, L1, L3.
- **Phase 2 (before D6):** H3, H4, M3, M4, M6, M7, L4.

## Doc contradiction to fix (code wins)

`PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §7 "GUEST → SLEEP transition had been missing; the latch now survives the night" vs `house_state.py:116-121`: GUEST has no SLEEP target. Either cite the mechanism or correct §7 and add a ledger entry.
