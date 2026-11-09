# Plan review 2 of 2 (ADVERSARIAL BUILD-PREDICTION): guest mode split

**Plan:** `docs/planning/PLANNING_guest_mode_split_2026_11.md` rev 2 @ `e4aba26d` → rev 3 (this commit).
**Card:** `GUEST-MODE-SPLIT-VISITORS-1`. **Reviewer:** ura-planner, Mode 2. **Framing:** "what will the builder get
wrong reading this plan?" It is disjoint from review 1, which was a completeness re-enumeration. **Date:** 2026-11-09.
**Code read:** `develop` @ `e4aba26d`.

**Read completely first:** plan review 1; `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (860 lines, §10
ledger 1-29); `docs/architecture/SENSOR_FLEET_CLASSES.md`; `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`
(726 lines, §10 C1-C38). No ledger claim is re-asserted. No code contradicts either doc on the surfaces this plan
touches. D0 (`AUDIT_guest_split_d0_2026_11.md`) was not touched.

**Verdict: BUILD-AFTER-D0.** All findings were fixed in the plan as rev 3. No finding needs an operator answer. The
§5.0 gate stands: no builder dispatch until D0 commits its verdict line and the operator confirms the stay dates.

---

## 1. Findings

| ID | Sev | What the builder would get wrong | Evidence | Fix in rev 3 |
|---|---|---|---|---|
| P2-1 | HIGH | **Wrong object (the v5.107.6 class).** D3 Live and §10 name `sensor.universal_room_automation_house_state` as the `guest_reason` oracle. That entity does not exist. There are TWO house-state sensors. `HouseStateSensor` (`sensor.py:5595`, unique `{DOMAIN}_house_state`, live `sensor.ura_coordinator_manager_house_state`) has no `guest_reason`. `PresenceHouseStateSensor` (`sensor.py:5695`, unique `{DOMAIN}_presence_house_state`, live `sensor.ura_presence_coordinator_presence_house_state`) carries it at `:5836`. A validator would read the wrong sensor, find no attribute, and either FAIL a good build or "fix" it by adding `guest_reason` to the manager sensor | live `.storage/core.entity_registry`, read 2026-11-09 | All oracles name the presence sensor and say to resolve it by unique id |
| P2-2 | HIGH | **The oracle reads the wrong tick.** The house-state sensor is POLLED every 30 s (`sensor.py:5711`, HOUSE-STATE-SENSOR-ATTR-CHURN-1 comment), and `guest_reason` is recomputed every tick. The recorded value at a GUEST transition is usually the first GUEST-state tick's value, not the entry tick's. Under rev 2's S4 that would be the hold reason, for example `two_leg:room` with one leg, so the L4 "contains room" check would pass even for a bad entry. Rev 2 also left `guest_reason` undefined inside GUEST | `presence.py:6615-6637`; sensor polling | New sticky, recorded attribute `guest_entry_legs`, stamped in the accepted-transition branch (`presence.py:7596-7603`) before the first await (`:7605`) and cleared on exit. `guest_reason` is defined per state (`two_leg:` on HOME_*, `guest_hold:` in GUEST). D3 Live and L4 now read `guest_entry_legs` from the first recorded `guest` state at or after each `house_state_log` row |
| P2-3 | HIGH | **Hollow anchor bait.** `test_guest_census_correctness.py::test_home_like_guest_armed_is_room_only` (`:337`) and `::test_inside_guest_branch_unchanged` (`:375`) assert the literal `guest_armed = guest_room_gate_armed` in both branches. The new composition turns them red. The cheapest way back to green is to keep that literal in a `not GUEST_TWO_LEG_GATE_ENABLED` arm. That arm would satisfy a grep while proving nothing. The plan did not name these tests | test file lines cited | The plan lists them as superseded. Each is replaced by a behavioural test, and keeping the literal to satisfy a grep is forbidden. The canary test `test_recorder_bloat_logflood.py:172` is updated with the narrowed condition |
| P2-4 | HIGH | **Restart / reload manufactures WiFi arrivals.** The rev 2 rule was "seen not `home` on a prior tick". UniFi trackers pass through `unavailable` / `unknown` on an integration load or reload. A builder reading "not home" literally gives every device an arrival edge, which defeats the restart guard D1 exists for. A reload one hour after boot escapes the 600 s exclusion entirely. Separately, the plan scoped tracking to "trackers on the guest SSID that pass filters 1-4c", but the filter loop reads `essid` / `host_name` from attributes (`camera_census.py:6080-6110`), and whether those persist on `not_home` is unverified | `camera_census.py:6001-6170` | "Seen away" means EXACTLY `not_home` at or after setup + exclude. `unavailable` / `unknown` never count as away and delete `home_since`. SSID and filters apply only on the `home` read. `last_changed` is never read. New D0 Q5 measures tracker states at restart and reload. New discriminating test: a reload replay must give 0 |
| P2-5 | MED | **WiFi leg transport unspecified.** "Census, read by presence (pure read)" does not say how. The likely mistakes are a guessed `hass.data[DOMAIN]["camera_census"]` (the real key is `"census"`, `__init__.py:2938`), or presence calling census private methods on its own clock | `presence.py:5158-5230`; `camera_census.py:1848` | The count goes in the `SIGNAL_CENSUS_UPDATED` payload, key `wifi_guest_devices_sustained` (S16), and is stored by `_handle_census_update`, default 0 (S17). It is NOT added to the inference-trigger set. Lag is at most 30 s (`SCAN_INTERVAL_CENSUS` `const.py:2344`) |
| P2-6 | MED | **Contradictory knob semantics.** §2.1 says the WiFi leg is "forced False when `GUEST_WIFI_LEG_ENABLED` is False". §6 says it is "computed for display, never counted for entry or hold". Under the §6 reading, `visitors_present` (GUEST OR any leg) would turn on from a leg D0 rejected | plan §2.1 vs §6 | False everywhere (entry, hold, `visitors_present`, D4). The count stays as a shadow on the census sensor |
| P2-7 | MED | **Frozen constant reads.** `from ..const import GUEST_TWO_LEG_GATE_ENABLED` binds at import. A test that patches `const.X` then never reaches the code under test, so the kill-switch tests pass hollow. The repo already has this rule for `ZONE_OCCUPANCY_PER_ENTITY_ENABLED` (presence state of play §4, lint-enforced) | presence doc §4 | Constants are read as `const.X` at call time. New test `test_const_read_at_call_time` |
| P2-8 | MED | **`visitors_present` push path invented.** Rev 2 says "push-updated with the house-state sensor", but that sensor polls. A builder would add a dispatcher signal or `async_write_ha_state` calls from inside the inference tick, which adds a new signal for a display entity | `binary_sensor.py:2415-2450` `GuestModeBinarySensor` (polled) | Polled, copied from `GuestModeBinarySensor`. Presence is reached through `coordinator_manager.coordinators.get("presence")` (`sensor.py:5760`) |
| P2-9 | MED | **Kill-switch golden cannot be produced.** "Replay a fixture of 200 recorded ticks" has no source, because no tick recording exists. A builder would hand-write 200 rows that agree with whatever they built | plan D3 rev 2 | Two parts. (a) The existing behavioural guest modules run unmodified and green under switch False. (b) A seeded synthetic-input golden is generated by running base `6b97e434` through the test harness, and the generator is committed |
| P2-10 | MED | **INV-SPLIT-1/2 not falsifiable as written.** "infer() proposes GUEST" is not the commit point, because `transition()` can refuse. The legs had no defined time base. INV-SPLIT-2 left out the 300 s GUEST minimum dwell (`house_state.py:137`) and the inference cadence, so reviewer D could "break" it with a legal min-dwell case that is not a defect | `presence.py:7543`; `house_state.py:137` | INV-SPLIT-1 is restated against the ACCEPTED transition from HOME_*, with each leg defined exactly and the exempt writers closed (select, service, restore) by file:line. INV-SPLIT-2 is bounded by max(persistence after the last room/WiFi tick, min dwell) plus one measured inference interval |
| P2-11 | MED | **Detection-switch-off clear placed in the wrong branch.** Rev 2 puts the clear "in the compose step", which runs only in HOME_* / GUEST. In AWAY / SLEEP (S3), `visitors_present` would keep reading a stale cam latch with the switch OFF | `presence.py:6586-6613` | The switch check sits before the branch split and covers S3 |
| P2-12 | LOW | Entity ids wrong in the plan. The kill switch is `switch.ura_presence_coordinator_guest_detection` (not `..._guest_detection_enabled`), and guest mode is `binary_sensor.ura_presence_coordinator_guest_mode` (not `binary_sensor.ura_guest_mode`) | live registry | Corrected |
| P2-13 | LOW | The §2.2 restart row said GUEST "holds only on `room` until the cam latch ... re-forms". The cam latch never re-forms inside GUEST (Path A is skipped in GUEST, `presence.py:6602-6606`) and cannot hold anyway | cited | Corrected. Added the row for a guest asleep in GB1 with the house in SLEEP: `visitors_present` is off overnight, which is expected |
| P2-14 | LOW | **`visitor_names` costs more than it is worth.** It is display only, its producer is empty since HomeLab removed the Ojini library on 11-09, and filling it means reading census private state, which is wrong-object bait | plan §2.3 | PARKED with the known-face revival trigger (marginal-benefit rule) |
| P2-15 | LOW | D4 shape left to invention: the span anchor, override detection, the NM call and the restart behaviour | `presence.py:4173-4255` | Copies `_check_sleep_raw_hold` and `fire_stuck_signal`; anchor `_guest_room_false_since`; RAM only |

**Checked, no finding:**
- **Hidden awaits.** There is no `await` between the guest block (`presence.py:6563`), `infer()` (`:7046`) and
  `transition()` (`:7543`). The first await is `:7605`. The plan now pins every new synchronous write ahead of it.
- **Retry path.** `_schedule_deferred_retry` (`:5562`) re-runs `_run_inference`, so legs are always recomputed and
  never replayed stale.
- **Time base.** The room gate uses `utcnow` and Path A uses local `now`; both are aware, so they compare correctly. The
  cam stamp is specified as UTC-aware.
- **D0 gate wording (§5.0).** Unambiguous. It names three verdict tokens and blocks every deliverable.

---

## 2. Will the acceptance tests catch the likely builder mistakes?

| Likely mistake | Caught by (rev 3) |
|---|---|
| Room-alone still enters (kept `guest_armed = room`) | `test_pair_matrix`, `test_1017_replay` (`guest_entry_legs`), mutation on S1 |
| `cam+wifi` admitted | `test_cam_wifi_never_enters`, `test_party_fixture_no_guest` |
| `cam` holds GUEST | `test_cam_alone_never_holds` |
| `_disarm_guest_gate` clears the cam latch | `test_cam_latch_survives_disarm` |
| `unavailable` treated as away | `test_unavailable_is_not_away` (new) |
| `last_changed` reused for sustain | D1 restart discriminator |
| Constant imported by name | `test_const_read_at_call_time` (new) |
| Literal kept in a kill arm to satisfy greps | superseded-test list plus behavioural replacements; framing-C mutation |
| Entry legs stamped after an await, or not cleared | `test_entry_legs_stamped_before_await`, `test_entry_legs_latched_and_cleared` (new) |
| Wrong live entity | L1 / L4 resolve by unique id |
| Switch-off leaves a stale latch in SLEEP | `test_detection_switch_off_clears_latch` (now spans S3) |

Residual: an INV-SPLIT-1 entry through a path not enumerated (a new `transition(GUEST)` caller). Reviewer D re-greps
`transition(` and `set_override(`, as the plan already requires.

---

## 3. Summary statistics

| Severity | Found | Fixed in rev 3 | Deferred |
|---|---|---|---|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 4 | 4 | 0 |
| MEDIUM | 7 | 7 | 0 |
| LOW | 4 | 4 | 0 |

| Bug class | Count |
|---|---|
| Wrong object / wrong entity (v5.107.6 class) | 2 (P2-1, P2-12) |
| Oracle reads a different tick than the decision (polled display vs transition) | 1 (P2-2) |
| Hollow test anchor bait | 1 (P2-3) |
| Restart/reload transient manufactures an edge | 1 (P2-4) |
| Under-specified transport / option ambiguity | 3 (P2-5, P2-6, P2-8) |
| Frozen import of a kill-switch constant | 1 (P2-7) |
| Unproducible golden | 1 (P2-9) |
| Invariant not falsifiable as stated | 1 (P2-10) |
| Level-triggered discharge in the wrong branch | 1 (P2-11) |
| Stale text / marginal-benefit trims | 3 (P2-13, P2-14, P2-15) |

**QUALITY_CONTEXT candidate:** "Polled display oracle at a transition". A per-tick attribute on a POLLED entity, read
from the recorder at a state-transition timestamp, reports a later tick's value. If the transition's own inputs are the
evidence, latch them at the commit point into a sticky recorded attribute.
