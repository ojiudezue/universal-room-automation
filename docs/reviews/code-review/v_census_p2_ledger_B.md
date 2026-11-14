# Review B: census deconfliction P2 + crossing ledger (integration, lifecycle, restart, dark path)

Branch `feature/census-deconfliction-p2-ledger` @ ed9229c5. Diff base verified: `git merge-base HEAD develop` = 3ec3f4d2 (`git diff 3ec3f4d2...HEAD`).
Plans: `PLANNING_crossing_vision.md` P2-D1..D3, `PLANNING_census_deconfliction.md` CD1..CD3.
Read completely first: both plans, `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. No contradiction between code and those docs found in this lane.
Framing B only: async, lifecycle, race, restart, byte-identical dark path, cross-coordinator ordering.

## Verdict: SHIP (no CRITICAL / HIGH). One MEDIUM worth fixing in the fix-up pass.

## Findings

| # | Sev | Site | Finding | Class |
|---|---|---|---|---|
| B-M1 | MEDIUM | `crossing_vision.py:1339` (`_evaluate_disagree`) | The CD3 `crossing_vision_disagree` page calls `fire_stuck_signal` with no `severity`, so it goes out MEDIUM. `_stuck_signal_nm.py:178-182` says MEDIUM reaches no channel under the live NM config. With the shadow switch on and 5 B/C disagreements on one door in 24 h, the trip-wire "fires" into an audit row nobody sees: a trip-wire that cannot page. Same shape as the S10 latch fix (HVAC doc §4.2, HVAC-S10-NOTIFY-UNDELIVERED-1). Fix: pass `severity="HIGH"` (or a deliberate LOW plus a note saying it is display-only). The pre-existing Phase 1 `crossing_vision_errors` page (`:1294`) has the same shape and is out of scope here. | trip-wire cannot reach operator |
| B-L1 | LOW | `quality/tests/test_residency_wiring.py:169-172` | The spy was narrowed to record only `SIGNAL_PERSON_ARRIVING`. Before, `sent == []` caught ANY dispatch in observation mode; now a future non-ARRIVING dispatch from that path would pass silently. Invert the filter so only `SIGNAL_RESIDENCY_EVENT` is dropped and everything else is recorded. | #62-adjacent (weakened oracle) |
| B-L2 | LOW | `quality/tests/test_crossing_ledger_wiring.py:366-375` | `test_teardown_unsubscribes_ledger_feeds` cannot tell whether the dispatcher feeds were unsubscribed: after teardown `_on_substrate_edge` / `_on_residency_event` return early on `_torn_down`, so the test passes even if the unsubscribe is gone. In runtime terms the code is correct (`async_teardown` calls every `_unsubs` entry, `crossing_vision.py:418-423`). The only cost of a missing unsubscribe would be a dead instance held per reload. A real oracle would assert that the dispatcher's listener set for both signals has no entry for this instance after teardown. Pointer for framing C. | #62 hollow anchor |
| B-L3 | LOW | `crossing_vision.py:1050-1081` (`_flush_ledger_events`) | "Batched" means one tracked task per 60 s eval, but each row is still its own `log_memory_episode` connection and commit (`database.py:10742-10783`, not the write queue). Volume is small (one row per term plus at most one anchor per hour) and it is the same path the Phase 1 shadow rows use. Accept, or route through a batch insert if the volume grows. | DB per-row write |
| B-L4 | LOW | `const.py` `MEMORY_WRITER_BACKED_EPISODE_TYPES` (+`crossing_vision_ledger`) | While the shadow switch is OFF (the ship default), the type has 0 rows, so the weekly writer-health check pages after 7 days. The documented discharge (add it to `MEMORY_WRITER_HEALTH_EXEMPT_TYPES` for a long-term off) is inherited from Phase 1 and is the operator's call. Listed so it is not a surprise. | observation / writer health |
| B-L5 | LOW | `camera_census.py:6573-6578` | `census_tick` runs only inside `_apply_enhanced_house_census`. With enhanced census OFF, the ledger never receives bodies, never anchors, and (switch on) pages `crossing_ledger_anchor_zero` LOW after 48 h. Fails safe (unknown means case D, awareness equals trust). Worth one line in the README. | degraded-config behaviour |
| B-L6 | LOW | `switch.py:1117-1119` | The friendly name "Census Vision Awareness" does not match the entity id `..._census_authority`, and the name is still pending the operator. Not a defect: `view_for_class` keys on the entity id (`presence.py:6026-6030`). Label only. | label clarity |

## Process note (orchestrator)
My one targeted run (6 cycle test files, 109 passed / 1 skipped) tripped the test-harness TREE INTEGRITY guard. At the time, `crossing_ledger.py` carried another reviewer's live mutant (`term_count`: `if outcome == _OUTCOME_OK and vision is not None` → `if vision is not None`). The worktree is shared with reviewer C. My pass count is NOT authoritative for `crossing_ledger.py`, and nothing in this review rests on it. After my run, `git status` showed C's one-line mutant still in place plus C's two untracked drill scripts. I touched neither. C, or the orchestrator, should confirm the file is restored to ed9229c5 before any further run. My clearances below are from reading the code.

## Clearances (holds because)

**INV-P2-AWAY-LATENCY (hard constraint). No reachable delay or block found.**
- Presence carries exactly one new runtime line: the `SIGNAL_RESIDENCY_EVENT` send in `_feed_residency` (`presence.py:5331`). It sits inside the existing `try`, after the row write, and contains no `await`.
- HA does not let a callback-target exception propagate out of `async_dispatcher_send`; it is logged (`homeassistant/helpers/dispatcher.py:242-249`). The only subscriber is `CrossingVisionShadow._on_residency_event` (grep: signals.py, presence.py, crossing_vision.py only).
- That callback does constant work: gate re-read, pop or cancel one timer, `note_departure`, one `async_call_later`. It never touches house state, inference, census, locks or NM.
- The `aware_` / `vision` grep in `presence.py` hits only the `HouseCensusView` docstring and fields and `get_house_census`.
- The `SIGNAL_CENSUS_UPDATED` payload dict (`camera_census.py:1890+`) is untouched.
- The golden fixture was committed at 921fb0b7, before every production commit. `git diff 921fb0b7 HEAD` on the fixture and the generator is empty; harness and test changes are additive (an `aware` capture plus FakeVision `vision_status`).

**Census ordering and the event loop.**
- `_compute_awareness` runs synchronously inside `_apply_enhanced_house_census`, under the census `asyncio.Lock`, on the loop (`camera_census.py:1745-1812`). It runs before the result is built, `_refresh_camera_input_dark_latch` and the dispatch, so presence's `_handle_census_update` sees an unchanged payload.
- `_resident_term` reads `get_residents_home()` (`presence.py:5446-5471`): pure reads of person trust state and the PLB sensor, no stamps.
- Any exception in it falls to case D (`camera_census.py:6680-6682`), and `_camera_input_dark_latched` is initialised at `:1339`.
- `total_persons == identified_count + unidentified_count` on this path (`clamped_unidentified = clamped_total - identified_count`), so in the dark default `aware_total == total_persons`, and switch ON vs OFF gives the same entity values.

**Substrate rising edges.**
- Callback signature `(room_name, kind, new_state)` matches the dispatch at `occupancy_substrate.py:818-823`.
- The subscription is the hass-level dispatcher, not the substrate instance, so it survives a substrate rebuild or refresh.
- The boot-settle synthetic True replays (`presence.py:2558-2563`) only restart the anchor window, which errs toward no anchor.
- It is unsubscribed in `async_teardown`.

**Timers and teardown.**
- Reconcile timers: one per person, superseded (popped and cancelled) on a new departure, popped at fire, cancelled in teardown (`crossing_vision.py:409-415`).
- `set_unknown` clears `_pending`, so a timer that fires later judges nothing (`crossing_ledger.py:396-398`).
- The eval interval, the tripwire interval and both dispatcher feeds are all in `_unsubs`.
- The ledger flush is spawned BEFORE the `_torn_down` latch, so the bounded gather covers it (`crossing_vision.py:413-414`, `:436-442`).
- `_run`'s `finally` skips the fallback term once torn down.
- Integration-entry reload: `async_setup_crossing_vision` tears down any prior instance first (`:1435`).
- A census tick after teardown reads `_torn_down` and returns (None, False), i.e. case D.

**Restart.**
- The ledger is RAM only and boots `unknown` (`crossing_ledger.py:174-176`). Pending reconciles drop (accepted, plan P2-D2 5).
- `_ledger_was_enabled` starts False, so the first enabled call rebases the anchor-zero clock (`crossing_vision.py:1021-1024`). A switch OFF→ON also rebases, because `_ledger_disabled` clears the flag, so a long switch-off is never paged as an anchor drought.
- At boot, residency restore edges carry `old_state None` and return before any record (`presence.py:5305-5307`).

**Pages.**
- `crossing_ledger_stuck` is HIGH with a RAM latch, re-armed at `guest_vis` 0 or None.
- `crossing_ledger_anchor_zero` is LOW, re-armed by an anchor or rebase.
- `fire_stuck_signal` adds a once-per-day per (kind, key) dedup, so a restart re-pages at most daily.
- All are silent while the shadow switch is off (`_ledger_enabled_now` gate; `async_evaluate_tripwires` returns on switch off).
- No existing NM text, severity or route changed.

**Awareness entities.**
- Integration device (`AggregationEntity`), unique ids `universal_room_automation_census_{people,guests}_around`, no collision (grep).
- Not RestoreEntity: computed on every `SIGNAL_CENSUS_UPDATED`, 0 before the first census, never unknown.
- Attributes are unrecorded.
- No URA reader: the grep for both entity ids hits only sensor.py and the presence boot seed does not read them.

**Downgrade switch.**
- On the CM entry and CM device, matching the Phase 1 shadow switch.
- Restore yields OFF only when the last state is exactly `off`.
- Before it is added, `view_for_class` reads no state and returns `trust` (`presence.py:6026-6031`); a missing or disabled CM entry also gives trust.
- With an awareness value equal to trust in the dark default, toggling it changes no entity value.

**Observation mode.**
- The residency dispatch fires in presence observation mode by design. Its only effect is ledger RAM and `crossing_vision_ledger` display rows, the same pattern as the existing residency rows.
- No actuator, house-state or NM path is reachable from it.

**HVAC.**
- No HVAC module reads the census, the awareness fields or the new signal (grep). Byte-identical.

## Invariant checklist (framing B)
| Invariant | Result |
|---|---|
| INV-P2-AWAY-LATENCY (no delay or block on AWAY) | PASS |
| Trust payload / existing fields byte-identical | PASS (golden provenance verified) |
| Timers / listeners torn down | PASS (oracle weak, B-L2) |
| Restart / reload safe (boot unknown, rebase) | PASS |
| Event-loop safety | PASS |
| Trip-wires reach the operator | MEDIUM (B-M1) |

## Summary statistics
| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | – | – |
| HIGH | 0 | – | – |
| MEDIUM | 1 | 0 | – |
| LOW | 6 | 0 | – |

Bug-class frequency: trip-wire cannot reach the operator 1; hollow or weakened test oracle 2 (#62); per-row DB write 1; writer-health / degraded config 2; label 1.
QUALITY_CONTEXT suggestion: "a page at a severity the live NM config routes nowhere" deserves a named class (the second occurrence after the S10 latches).
