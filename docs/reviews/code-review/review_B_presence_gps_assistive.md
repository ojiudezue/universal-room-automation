# Review B — presence GPS assistive (PERSON-BLE-WINS-OVER-STALE-GPS-1)

**Framing B:** cross-coordinator ripple + async / lifecycle / race / restart.
**Branch:** `fix/presence-gps-assistive`. **Diff:** `f96aaa0ed...acab9c3f3` (base verified as an ancestor; 2 commits, f2941715f + acab9c3f3).
**Read first, completely:** `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`, `HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. No claim from either §10 ledger is re-asserted here. Also read: the plan (Rev 3), `AUDIT_presence_gps_assistive_consequence_replay.md`.
**Suite:** `test_person_gps_assistive.py` + `test_person_gps_assistive_hvac.py` 57 passed (worktree `.claude/worktrees/revB-gps`, no bytecode).

## Verdict: FIX-REQUIRED (operator disposition, not code)

The lifecycle and async mechanics are sound. The two HIGH findings are behaviour the consequence replay measured. The operator's 2026-10-24 answers came before the replay (f96aaa0ed precedes it), and they do not cover these two outcomes. acab9c3f3 fixed the pre-arrival guard and the face latch, but it left the at-home location flip itself unchanged. The operator has to accept these by name, or the rule needs one more witness, before ship.

## Findings

| # | SEV | Site | Finding | Bug class |
|---|---|---|---|---|
| B-H1 | HIGH | `person_coordinator.py` overrule arms (~:1026, ~:1122) → `camera_census._get_ble_persons` (`camera_census.py:2671-2687`) → `presence._guest_gate_armed` (`presence.py:5972`) | **False GUEST at home survives the fix.** An overruled resident gets `location = "away"`, so he drops out of the census BLE-identified list, and the camera body he makes becomes unidentified. The guest gate then arms after 300 s. Leaving the face latch raw (acab9c3f3) only shortened the runs. **Repro (replay, legal config, live 10-24):** Oji is home with both BLE trackers `not_home`, GPS frozen `home`, WiFi `MISSING`, proxy count ≥ 30 for ≥ 360 s, and Ezinne is away. Unidentified run at medium/high confidence: IV10 1,080 s and IV11 1,411 s, both with the guard left raw, against `_guest_persistence_seconds` 300. GUEST arms. Before this change, the GPS-forced `home` counted him as identified and the run was 0. Operator Q3 accepted the pre-arrival effect only. Audit §5: "does not cover a false GUEST state". | cross-coordinator ripple / concept split (#63: a GPS `home` was doing identity work for the census) |
| B-H2 | HIGH | same overrule → `presence.py` path α (`all_tracked_persons_away`, location only; §10 #12) | **House AWAY with a resident home, reachable whenever cameras lose him for 30 min.** α needs all trackers away, unidentified 0 and face 0. It ignores room occupancy, and the face latch expires after 1800 s. **Repro:** Oji's phone stays in the car in the garage (the audit's hypothesis for 10-24: `area_last_seen = Garage A`, GPS home). Oji sits in Study A, which has no interior camera, for more than 30 min while the other residents are away. His BLE trackers read `not_home` (the phone is out of every scanner's reach), WiFi is `MISSING` and the fleet is armed, so the overrule fires and he is set away. He has no face for 1800 s and makes no unidentified body, so α fires AWAY. Study A's ZK holds a zone, which blocks nobody-home but not α. Before the change he was held home. In the replay, IV10 was saved by face latches (19/19 min) and IV11 by face latches plus unidentified bodies. "Camera luck, not a guarantee" (audit §3.7). AWAY then fans out on `SIGNAL_HOUSE_STATE_CHANGED`: HVAC presets, lighting, security, EVSE, battery. | cross-coordinator ripple |
| B-M1 | MEDIUM | `_apply_s3_away_arm(was_away_after_min_away=True)` (`person_coordinator.py` ~:571-577) | The 15-min guard measures `now - _person_lost_since`, and that stamp is set only if absent. The S2 forced-home arm pops it. The S5 arm (`person.state` unknown / unavailable, ~:1065-1077) and the LOST no-room branch (~:943) stamp it and do not pop it. **Repro:** `person.oji` reads `unavailable` for 20 min (a companion app or person integration hiccup) while the fleet is armed, then returns `home` with BLE `not_home`. The overrule's first tick sees a lost age of ≥ 15 min, sets `_person_was_away = True` at once, and the next BLE re-fix fires `SIGNAL_PERSON_ARRIVING` and an S12 pre-cool. Narrow, and a dropout pre-arrival is Q3-accepted, but the guard does not measure the overrule itself as the plan row 15 text says. Fix: reset the stamp on the first overrule tick (keyed on `person_name not in self._gps_home_overruled`), or document it. | value entry/exit (stale stamp reused) |
| B-M2 | MEDIUM | overrule ≥ 15 min at home → BLE return | After the fix, at-home spells of 15 min or more still fire a false pre-arrival on the BLE return: IV6 is 77 min and IV12 is 300 min or more, both camera-verified at home. That pre-arrival drives `hvac._handle_person_arriving` → an S12 pre-cool write on an occupied zone, plus security's expected-arrival. Q3 accepted "dropout pre-arrival", but before the replay showed 65 % of overrule minutes were at home. Re-confirm this with the operator together with B-H1 and B-H2. | ripple |
| B-L1 | LOW | `_async_update_data`: `_fleet_armed_now` is captured, but `_ble_overrules_gps_home` re-reads `_fleet_armed(now)` live per person | A listener dip that lands at an await mid-loop can make persons in one tick disagree. It only fails toward no overrule (conservative), and the log line uses the captured value. Thread the captured local for one value per tick. | capture-before-await |
| B-L2 | LOW | `PresenceCoordinator._ble_leads_enabled = True` in ctor + `_PresenceKillSwitchBase` deferred restore | After a presence-coordinator rebuild (CM reload), a switch the operator turned OFF reads ON until the deferred restore lands. The person coordinator is not rebuilt, so the fleet can already be armed, and one 30 s tick can overrule. The same window exists for the other three presence kill switches. Accept by name. | restart / restore window |

## Cleared (holds because)

- **Listener register-on-first-resolve / rename:** `_ensure_proxy_listener` runs every tick. A new `eid` releases the old unsub before it subscribes, and a missing `eid` clears the latch (rule off). Each subscription appends an idempotent `_release_proxy_listener` to `async_on_unload`, so the list grows by one per rename, which is harmless.
- **Double release:** `async_teardown` and on_unload both call `_release_proxy_listener`, which pops `_proxy_unsub` before it calls the unsub. Idempotent.
- **Re-subscribe during unload:** a refresh that fires between `async_teardown` (`__init__.py` ~:5683) and HA's `_async_process_on_unload` re-subscribes and appends a release. HA drains `_on_unload` with `while self._on_unload: pop()()` (`config_entries.py:1188`), so that release still runs. The DUC registers `async_shutdown` on the same entry (`update_coordinator.py:149`), so the old coordinator stops ticking.
- **Reload storms:** every reload builds a new coordinator: `_fleet_healthy_since = None`, so the boot latch re-arms, and an empty overruled set means raw reads. The first 360 s are byte-identical.
- **Restart, first 360 s:** the latch starts at None, and `effective_person_state` returns raw for an empty set. The replay confirms the latch suppressed the 10-20 22:21 and 10-24 14:03 restart artefacts.
- **Callback thread safety:** `_on_proxy_state_change` is `@callback`, non-blocking, pure arithmetic, and runs on the event loop. Event and tick ordering is irrelevant because both write the same latch with fail-closed semantics.
- **Assign-once / UpdateFailed:** the set is built in a local and assigned once after the loop. An exception keeps the previous set. `effective_person_state` also requires `get_person_location == "away"` from `self.data`, which the DUC publishes only after return, so the set-new / data-old window can only return raw (conservative).
- **Name → entity mapping** in `effective_person_state` uses the same derivation as the tick (`person_coordinator.py:774`).
- **Edge-triggered raw readers** (security geofence `security.py:1987`, BLE transition legs, egress / face vetoes): the overrule writes no HA state edge, so they see nothing new.
- **HVAC D7 / fan night holds:** they read the overrule only in FAN_TRUST states, with 0 overrule minutes measured there. Daytime HVAC retreat never reads person state (HVAC SoP §3.2). No HVAC logic changed, so the no-op path stays byte-identical. `zone_has_home_person` has no production caller.

## Must-fix before ship

1. B-H1 and B-H2: get explicit operator acceptance by name, using the replay numbers (65 % of overrule minutes were at home; GUEST arms at home; α is held only by cameras). Otherwise add a home witness, such as a recent interior face for that person, or a disarm while the person's last BLE area is a garage or vehicle area. Code wins: leaving the face latch raw does not fix either one.
2. B-M1: reset `_person_lost_since` on the first overrule tick, or record the case.
3. B-M2: re-confirm Q3 with the post-replay numbers.

## Stats

| SEV | Found | Fixed |
|---|---|---|
| HIGH | 2 | 0 |
| MEDIUM | 2 | 0 |
| LOW | 2 | 0 |

Bug-class tally: cross-coordinator ripple 3, value entry/exit 1, capture-before-await 1, restore window 1. Candidate for QUALITY_CONTEXT: **"a trust value doing hidden identity work."** A GPS `home` counted the person as identified for the census. Removing it moves the person's body into unidentified and arms GUEST.
