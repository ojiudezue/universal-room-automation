# Review A (local correctness) — house-state SLEEP mask + BLE memory + AWAY observability

- **Branch:** `feature/house-state-sleep-mask-ble-memory` @ `2e10e3a09`
- **Base:** `a0cd40412`, verified as `git merge-base HEAD develop`. Diff is `git diff a0cd40412...HEAD` (three-dot).
- **Framing:** A, local correctness: arithmetic, predicates, clamps, None handling and fail-safe direction, per site. Tests and lifecycle belong to the other framings and are out of scope here.
- **Read in full first:** `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (§10 ledger respected), `SENSOR_FLEET_CLASSES.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, the plan (Rev 2 + the Rev 2.1 build delta), and `AUDIT_census_arc_and_away_holistic.md` §P5 (read at `1c74b467b`).
- **Worktree note:** during this review the working copy of `presence.py` carried an uncommitted mutant at `:4073` (`if False:`), almost certainly reviewer C's drill in progress. Every finding below was read from the committed diff. This commit adds only this file.

## Verdict: **SHIP**. No CRITICAL or HIGH. Two MEDIUMs and three LOWs should be folded in the fix-up pass.

## Per-site verification

| Site | file:line (HEAD) | Result |
|---|---|---|
| D1: nobody-home reads the un-masked input | `presence.py:1137-1146` | **Holds.** It uses `_zone_occ_for_empty`, and `None` falls back to `any_zone_occupied`. The already-AWAY return stays first and leaves the label at `none`. Only the firing return sets `nobody_home`. |
| D1 call-site local | `presence.py:6221-6232`; kwarg `:6740` | **Holds.** The value is `any(mode==OCCUPIED or (mode==SLEEP and night_raw))` and is keyed on tracker mode. With no SLEEP-mode tracker it equals `any_zone_occupied` (INV-BYTE-ID). Kill switch False gives `None`, which is masked behaviour. |
| D1 AWAY-override carve-out | `ZonePresenceTracker.mode` `:654-659`; `set_sleep` `:933-940` | **Holds.** An AWAY-overridden tracker reports `mode == AWAY` and so never enters either limb. `set_sleep` does not overwrite a manual override. |
| `_zone_night_rooms` vs `_derived_mode` | `:4026-4048` vs `:765-790` | **Exact mirror** of `_derived_mode == OCCUPIED`: BLE first, then `_has_sensors`, then rooms (incl. the fan-interference hold extension), then cameras. A zone with no sensors and no BLE gives `[]`, which matches UNKNOWN/AWAY. No fan term, as Rev 2.1 requires. |
| D1 error direction | `:4040-4048` | **Fail-safe.** A `_room_occupied` or camera raise returns `["<error>"]`, so the zone counts occupied and SLEEP is held. The discharge is D1b at window end. `_ble_occupied` / `_has_sensors` are plain ctor attributes and sit outside the try, which is acceptable. |
| D1b wake disjunct | `:1315-1327` | **Holds.** It needs `not has_people`, `current_state == SLEEP`, `not _is_sleep_hour(hour)` (where `hour = now.hour`, local, `:1126`) and `for_empty is True`. It then reaches the existing `SLEEP → WAKING` branch (`:1374-1377`) because GUEST is not current and it is not a sleep hour. The kwarg is `None` when the kill switch is off, so D1b is gated by the same switch. Under a manual house SLEEP override with the underlying state at HOME_*, WAKING is proposed but `HOME_NIGHT→WAKING` is not in `VALID_TRANSITIONS` (`house_state.py:95-107`), so it is rejected. This is inert and matches the existing census>0 behaviour. |
| D1b equivalence | — | `any_zone_raw_occupied` (WAKING 90 s gate) is a superset of `for_empty` for SLEEP trackers (same `_derived_mode`), so the gate sees the same raw signal and passes. INV-SLEEP-HOLD-BOUNDED (b) holds locally. |
| Trip-wire predicate | `:4057-4116`, call `:6777-6782` | `held` = SLEEP, census 0, masked empty, raw held. The clock runs from the sleep end. It is cleared in sleep hours (the fired flag is kept, which is correct within an episode). It fires once per episode via `_sleep_raw_hold_nm_fired`, and `fire_stuck_signal` adds a per-(kind,key)-per-day latch (`_stuck_signal_nm.py:185-190`). Bound 0 disables it (`<= 0`). The call is wrapped in try/except. Truth table (22→06, bound 5400): 05:00 → no fire; 06:30 → 1800 s, no fire; 07:31 → 5460 s, **fires**; census flicker >0 → episode reset and re-arm, still latched per day. Exceptions: see A-M1. |
| D2 `_tracking_active` | `:6066-6073` | **Holds.** ACTIVE gives True. STALE gives True only while `PRESENCE_STALE_RESIDENT_COUNTS_HOME`. A missing status defaults to ACTIVE (unchanged). |
| D2 bound | `person_coordinator.py:607-616` | STALE requires `time_since_update < decay_timeout` with `last_bermuda_update` carried, not refreshed, so the hold is at most last fix + N (+ person tick + presence tick). `decay_timeout = 0` means STALE is never assigned and D2 is inert. STALE keeps `location = old_location` (a room), so `all_tracked_persons_away` (`:6150-6153`) reads it as home. If an older tick had left `location="away"`, STALE stays away, which is the safe direction. |
| D2 phone_left_behind precedence | `:6116-6136` | **Unchanged.** `phone_ok and track_ok` still gates trust, and `not phone_ok` gives `phone_left_behind=on,...` first. `stale_counted_home` is appended only inside the trusted branch. It is entry-reset per tick and reset in the except. |
| D3 counter placement | `presence.py:8276-8284` | After the boot-settle return (`:8204-8213`) and the observation return (`:8214-8220`), next to the `log_house_state_change` task. The condition `new_val=="away" and old_val!="away"` is exactly the SQL `previous_state <> 'away'` (the row's `previous_state = old_val`). Gated dispatches are not counted. |
| D3 `last_away_branch` | `:8150-8161` | For inference it reads the mirrored `self._veto_path` (`:6770`), which is set earlier in the same `_run_inference` than the dispatch (`:7321`). All three `return HouseState.AWAY` sites now carry a label (`:1153`, `:1203`, `:1300`). `override_adapter` (`manager.py:772`) and `boot_settle_override` (`:2504`) both map to `override`. There is no `restore`. |
| D3 midnight | `:8136-8151` | The getter compares against `dt_util.now().date()`. The periodic `_roll_away_count_day` (`:5257`) and `_note_away_entry` roll first. Hydration sets the date. **Holds.** |
| D3 hydration bound | `:8166-8181` | `as_utc(start_of_local_day()).replace(tzinfo=None).isoformat()` gives `'YYYY-MM-DDT05:00:00'` (CDT). The column is `datetime.utcnow().isoformat()` (`database.py:2968`), and the lexical `>=` includes a row stamped exactly at the boundary. DST-correct via `start_of_local_day`. |
| D3 DAO | `database.py:3031-3070` | With no kwargs: `"SELECT COUNT(*) FROM house_state_log WHERE timestamp >= ?"`, `(since_iso,)`, **byte-identical**. `exclude_same_previous` without `state` is silently ignored (harmless; the only caller passes both). |
| `_unrecorded_attributes` | `sensor.py:5570-5572` | HA `Entity.__init_subclass__` unions the class frozenset with `_entity_component_unrecorded_attributes` (`.venv-ha .../helpers/entity.py:560-564`). `AggregationEntity` defines none, so nothing is shadowed. The four recorded D3 fields are not in the set, which is correct. |
| Periodic out of the discovery try | `presence.py:2993-3016` | It is at the same nesting level as the discovery try, still appended to `_unsub_listeners`, and still once per setup. |

## Findings

### A-M1 — MEDIUM — the trip-wire false-fires when house SLEEP is entered by override outside the sleep window
**Bug class:** day-boundary-blind clock.

**Site:** `presence.py:4074-4084`. `window_end` is always "the most recent `sleep_end_hour` at or before now". It is never later than the SLEEP entry.

**Repro (legal config):**
- Sleep window 22→06.
- Census 0, the Wigton S0 shape.
- At 21:30 the operator sets a house SLEEP override (early bedtime).
- `set_sleep(True)` pins the zones, and a bedroom ZX reads occupied.

**Result:** `current_state` is the override-aware `machine.state` = SLEEP (`:6257`), and 21 is not a sleep hour. So `window_end` = 06:00 today, `held_s` ≈ 55,800 > 5,400, and the NM fires on the first tick. It reads "House still in SLEEP 930 min after the sleep window ended … D1b did not release it". That is false: D1b cannot release an override, and the window has not even started.

The same thing happens for a non-wrapping window (1→9) with a SLEEP override at 00:30, where `window_end` = yesterday 09:00.

**Fix (≤ 5 LoC):** either skip the clock while `house_state_machine.is_overridden`, or anchor it at `max(window_end, SLEEP entry time)` (`machine.state_since`). The first matches the trip-wire's stated meaning, "D1b failed".

### A-M2 — MEDIUM — the trip-wire NM is MEDIUM severity, which the HVAC state-of-play says reaches no channel live
**Bug class:** #53 computed-but-not-consumed (alarm without a reader).

**Site:** `fire_stuck_signal` hard-codes `Severity.MEDIUM` (`_stuck_signal_nm.py:222`). The HVAC state of play (`HVAC_ARCHITECTURE_STATE_OF_PLAY.md:71`, 2026-10-16) records that MEDIUM "reaches no channel under the live NM config (companion is HIGH+, the rest CRITICAL)". That is why the S10 latches were raised to HIGH.

**Consequence:** the cycle's only code trip-wire for INV-SLEEP-HOLD-BOUNDED (b), and the revival trigger for the parked fan breaker, would land as an audit row nobody is paged with.

**Caveat:** I did not re-read the live NM config; that claim rests on the doc. If it still holds, pass a severity override or route through a HIGH path. A `title_override` already exists; a `severity` kwarg would mirror it. Otherwise record explicitly that the trip-wire is ledger-only and that the README check is a ledger query.

### A-L1 — LOW — `guest_reason="unidentified_persistent"` is reported while GUEST is not armed
**Bug class:** #63 concept split.

**Site:** `presence.py:6327-6335`. Since GUEST-CENSUS D2, `guest_armed = guest_room_gate_armed` only (`:6294`, `:6304`). Path A (`unid_gate_armed`) arms nothing by itself. The attribute's comment says "why GUEST is (or would be) armed", but in a HOME_* state with the unid gate armed and no guest room it reports a reason for a GUEST that will not happen.

**Fix:** either rename the value to `unidentified_persistent_corroborator_only`, or set it only when `guest_armed`. The plan's precedence (R2 L6) predates the D2 semantics, so this is plan-inherited.

### A-L2 — LOW — stale comment in the `infer()` kwarg docstring
**Site:** `presence.py:1059-1065`. The docstring still says "(fan-phantom rooms dropped)". Rev 2.1 removed the breaker, and `_zone_night_rooms` has no fan term. A future reader may "restore" the breaker from this comment.

### A-L3 — LOW — the trip-wire's clock differs from `infer()`'s
**Site:** `presence.py:4071`. `_check_sleep_raw_hold` reads its own `dt_util.now()` instead of the `now` that `_run_inference` captured (`:6262`) and handed to `infer()`. If those straddle an hour boundary (`hour` 05:59:59 vs 06:00:00), the two disagree on sleep hour for one tick. The result is harmless: the bound is 90 min. Threading the captured `now` would make the tick self-consistent and make the clock test-patchable at one site.

### Cleared (holds because …)
- **D2 cannot hold beyond last fix + N + I + T.** The STALE predicate is strictly `< decay_timeout` on a carried stamp (`person_coordinator.py:610-615`). The else branch takes over afterwards.
- **None handling.** `any_zone_occupied_for_empty` is `bool` or `None`, never another falsy value. D1b uses `is True`. The sensor's getattr defaults cover a presence coordinator that lacks the new attrs.
- **INV-BYTE-ID locally.** With no SLEEP-mode tracker, `for_empty == any_zone_occupied`, so nobody-home and D1b are unchanged. The only delta is the `nobody_home` label on the firing return, which is permitted. No decision reads `_veto_path` (grep: only sensor attrs, the D7 snapshot and `_note_away_entry`. The D5 episode computes its own `_veto_path_str`, `:6812`).
- **Counter vs log.** The predicate is identical. The only divergence is when `hass.data[DOMAIN]["database"]` is None: the counter increments and no row is written. That is not reachable on a live install, so it is acceptable.

## Invariant checklist (local view)
| Invariant | Status |
|---|---|
| INV-SLEEP-NOT-EMPTY (with AWAY carve-out) | PASS |
| INV-SLEEP-HOLD-BOUNDED (a) / (b) | PASS (b's trip-wire has the A-M1 false positive and the A-M2 delivery gap) |
| INV-BLE-SEEN-NOT-AWAY (phone_left_behind precedence) | PASS |
| INV-NO-BLE-HOLD | PASS |
| INV-BYTE-ID | PASS |
| INV-COUNTER-MATCHES-LOG | PASS |

## Summary
| Severity | Found | Must-fix before ship |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 2 (A-M1, A-M2) | recommended in the fix-up pass (observability only; no AWAY decision is affected) |
| LOW | 3 (A-L1..L3) | fold in (each 1–5 LoC) |

Bug classes seen: day-boundary-blind clock (1), #53 alarm without a reader (1), #63 concept split (1), stale documentation (1), dual clock read (1).
