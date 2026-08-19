# AUDIT — Fan-recheck "second bug" + why the fan-transition gate missed the shake latches

**Date:** 2026-08-18
**Type:** Read-only two-part code + live trace. No code changes.
**Scope:** Study A + Living Room held occupied by fan-shake mmWave while empty; the
event under study is the **2026-08-18 CDT** episode (the recorder-confirmed timings
below match the reconstruction exactly).

> Evidence discipline: every mechanism below is cited to `file:line` and/or a live
> recorder/entity value. Where a fact could not be established from post-hoc live
> data, it is stated as **undetermined**, not guessed (No-Fabrication).

---

## Live timeline (recorder, America/Chicago), 2026-08-18

Study A (`fan.polyfan_dreo704s_wifi_studya`, `binary_sensor.mmwave_zigbee_studya_presence`):

| time | event |
|---|---|
| 20:59:02 | last real motion (`binary_sensor.study_a_occupied.last_motion`) |
| 21:10:00 | room **vacant** (`occupied=off`), but `fan_on=true`, `idle_duration=136`, `occupancy_source="none"` |
| 21:13:14.84 | fan **off** (URA vacancy-off; room already vacant) |
| 21:17:42.38 | Zigbee mmwave **on** (rising edge) — **fan still OFF** |
| 21:17:42.58 | room goes **occupied**, `occupancy_source="mmwave"`, `tier1_provenance{motion:false, mmwave:true, occupancy:false}`, `last_trigger_source="presence"`, `last_edge_entity=binary_sensor.mmwave_zigbee_studya_presence`, `fan_transition_suppressed_count=0`, `fan_on=false` |
| 21:17:43.21 | fan **on** (~0.83 s AFTER occupancy created) |
| 21:17:42 → past 22:20 | Zigbee mmwave **continuously ON**, zero off edges (raw history, `significant_changes_only=false`) |
| 23:08 (now) | still `occupied=on`, `occupancy_source="timeout"`, `fan_recheck_state="idle"`, `fan_recheck_last_outcome=null`, `fan_transition_suppressed_count=0` |

Corroborating "empty" sensors across 21:17–22:20: `binary_sensor.espresense_study_a_connectivity`
**off** the entire window; `binary_sensor.occupancy_lux_temp_humidity_studyacloset_presence`
**off** the entire window. Room was empty; only fan-shake sustained the mmWave.

Living Room (`fan.towerfan_dreopilotmaxs_wifi_livingroom`, `binary_sensor.screek_human_sensor_l13_2412s_still_target`):

| time | event |
|---|---|
| 21:32:49.77 | Screek `still_target` **on** (BEFORE fan) |
| 21:32:50.20 | `binary_sensor.living_room_occupied` **on** (occupancy created) |
| 21:34:25.29 | `still_target` **off** |
| 21:35:07.25 | fan **on** (~135 s AFTER occupancy created) |
| 21:37:08.12 | `still_target` **on** again — **121 s AFTER fan start** (sustained-airflow shake latch) |

Live Study A config of record (`.storage/core.config_entries`, `options` block wins over `data`):
`motion_sensors=[]`, `occupancy_sensors=[]`, `presence_sensors=['binary_sensor.mmwave_zigbee_studya_presence']`,
`room_type=generic`, `room_fan_recheck_enabled=True`, `fan_control_enabled=True`,
`adjacent_rooms=[]`, `zone="Master Suite"`, `scanner_areas=['study_a_closet']`,
`fan_recheck_trust_sensors_ok=True`, `fans=['fan.polyfan_dreo704s_wifi_studya']`.
The `data`-block athom sensors (`athom_presence_sensor_d93b20_*`) are **overridden** by the
`options` block AND are all **`unavailable`** live (dead device) — they contribute nothing.

---

## TRACE 1 — the recheck's "second bug" (occupancy_source precedence)

### Producer check — how `occupancy_source` is derived
`coordinator.py:3065-3078` sets the source with a fixed precedence inside the
occupied branch: `motion_detected` → `"motion"` (and stamps `_last_pir_motion_time`),
else `presence_detected` → `"mmwave"`, else `"occupancy_sensor"`. `motion_detected`
is computed at `coordinator.py:~3059` over `motion_sensors` (`CONF_MOTION_SENSORS =
"motion_sensors"`, const.py:432); `presence_detected` over `mmwave_sensors`
(`CONF_MMWAVE_SENSORS = "presence_sensors"`, const.py:433, sourced at
`coordinator.py:1216`). So motion DOES outrank mmwave — the hypothesis's premise
about the code is correct.

### The hypothesis is DISPROVEN by live data
The precedence gap can only bite if the Zigbee mmwave is filed under
`motion_sensors`. It is not. Live effective config: `motion_sensors=[]`,
`presence_sensors=['binary_sensor.mmwave_zigbee_studya_presence']`. There is **no
motion entity at all** in Study A (the only PIR, `athom_..._pir_sensor`, is
overridden out AND dead). Consequently:

- At occupancy creation 21:17:42.58, live attributes read `occupancy_source="mmwave"`,
  `tier1_provenance{motion:false, mmwave:true}`, `last_kind_to_fire="mmwave"`.
- `motion_detected` can NEVER be true for Study A → source can NEVER be `"motion"`.

The arm gate at `presence_fan_recheck.py:860` (and condition 2 at :393) requires
`occupancy_source == "mmwave"`. That requirement was **satisfied**, not violated.
The precedence gap did not fire and cannot fire for this room.

### Guest-vs-sleep reconciliation (the wrinkle)
The observation was: source `== "mmwave"` at sleep-time (~22:17), implying source
was *something else* ("motion") during guest. **Live data shows no such divergence.**
The Zigbee mmwave was continuously ON from 21:17:42 with zero off edges, and there is
no motion entity that could have produced a "motion" source at any point. Source was
`"mmwave"` throughout the occupied span (later decaying to `"timeout"` only after the
sensor eventually released, which is why the *current* 23:08 read shows `"timeout"`).
**There was never a "motion" source during guest.** The premise that the source
differed between guest and sleep is not borne out; the reconciliation collapses to
"same source both times," so there is no categorization divergence to explain.

### So why did the recheck never arm? (elimination against every documented veto)
Walking `_is_eligible` (`presence_fan_recheck.py:339-504`) against live state:

| veto (`file:line`) | ruled out by |
|---|---|
| `master_off` (:350) | `switch.ura_presence_coordinator_fan_recheck` = **on** |
| `room_disabled` (:355) | `switch.study_a_study_a_fan_recheck` = **on**; `room_fan_recheck_enabled=True` |
| `fan_control_off` (:358) | `fan_control_enabled=True` |
| `sleep_state` (:374) | guest window 21:17–22:02 is not `SLEEP` (the KNOWN veto; not in play here) |
| `not_occupied` (:379) | `occupied=on` continuously |
| `mmwave_history_short` / `not_mmwave_sole` (:392/:394) | mmwave continuously ON; source `"mmwave"` every occupied tick |
| `no_fan_configured` / `no_fan_on` (:402/:404) | fan configured + ON from 21:17:43 |
| `boot_settle` (:408) | HA up since ~16:18; 5 h before the event |
| `manual_off_cooldown` (:414) | URA turned the fan back **on** at 21:17:43 — incompatible with an active manual-off cooldown |
| `rate_cap` (:427) | never armed → `attempts` empty |
| `no_person_coord` (:432) | person coordinator live (guest mode functioning) |
| `ble_l1` (:440) | `current_persons=[]`, `ble_persons=[]` at creation |
| `ble_l2` adjacent (:479/:484) | **`adjacent_rooms=[]`** — the adjacent scan has no rooms to hit |
| `high_still_risk` (:475/:493) | `room_type=generic` ∉ `{bedroom, media_room}` (`:92`) |
| `trust_sensors_off` (:501) | `fan_recheck_trust_sensors_ok=True` |

**Every enumerated veto is ruled out by live config/state, yet the machine stayed
`idle` (`fan_recheck_last_attempt_iso=null`, `fan_transition_suppressed_count=0`).**
On the evidence, the recheck *should* have armed and did not.

### The dispositive finding: the arm-blocker is not observable
The exact blocking reason **cannot be pinned from post-hoc live data**, because
`_veto` (`presence_fan_recheck.py:136-139`) only increments an **in-memory per-room
counter** — it emits no log line and writes no DB row. The snapshot that *does*
carry `fan_recheck_veto_counts` + `fan_recheck_eval_count` (`:302-313`) is exposed on
**no entity** (the `binary_sensor.study_a_occupied` attribute set carries
`fan_recheck_state` / `_last_outcome` / `_last_attempt_iso` / `_ble_ladder_layer`
only — `binary_sensor.py:396-399` region). The per-tick fan-out is additionally
wrapped in a `try/except` that swallows to **DEBUG** (`presence.py:6904-6907`), so a
raised exception inside `on_room_tick` / `_is_eligible` for one room would silently
suppress that room forever with no visible trace.

**TRACE 1 VERDICT.** The "second bug" is **not** occupancy_source precedence and
**not** sensor mis-categorization — those are disproven live (source was `"mmwave"`,
no motion entity exists, no guest-vs-sleep divergence). The real defect is that the
fan-recheck **failed to arm for a textbook-eligible empty room and left no evidence
of why**: veto reasons and eval counts are computed but surfaced nowhere, and the
tick fan-out swallows exceptions at DEBUG. The immediate corrective is
**observability** (expose `fan_recheck_veto_counts` / `fan_recheck_eval_count`
per room, and raise the swallowed-exception log level), which is the prerequisite to
root-causing the silent non-arm. Changing sensor categorization would be wrong — the
categorization is already correct.

---

## TRACE 2 — why the shipped fan-transition gate did not suppress these latches

### What the gate is (cited)
`FAN_TRANSITION_SUSPECT_WINDOW_S: Final = 5.0` (const.py:828), a **rung-1 module
constant**, kill switch `= 0.0` (const.py:826). It is **enabled** (value 5.0, and live
`fan_transition_suppressed_count=0` confirms it is running but simply never matched —
not disabled). Semantics documented at const.py:809-824 and implemented at
`coordinator.py:2843-2923`. The firing predicate (`coordinator.py:2890-2912`) requires
ALL of:

- (a) `FAN_TRANSITION_SUSPECT_WINDOW_S > 0` (kill switch)
- (b) `any_sensor_active` this tick (would-create)
- (c) `not self._last_occupied_state` — **CREATION only**, never sustain (:2893, :2857)
- (d) `presence_detected and not motion_detected and not occupancy_detected` — mmwave-sole
- (e) `0 <= (now - fan_last_transition) <= 5s` (:2911-2912) — coincidence with a fan
  power/speed **transition edge**

It keys on `presence.get_fan_last_transition(room)` (`coordinator.py:2907`), i.e. the
**edge** of a fan power/speed change, not sustained running. On fire it clears
`any_sensor_active` so the creation does not execute (`:2922`). It is explicitly
scoped to leave D2 (sustain demotion) and fan-recheck (test-under-fan) untouched
(const.py:821-824).

### Why it missed Study A
At the creation tick (21:17:42.58), predicate (e) computes `delta` against the
**most recent** fan transition, which was the **21:13:14 OFF edge** — `delta ≈ 268 s`,
far outside the 5 s window. The fan-ON edge that people would blame (21:17:43.21)
had **not happened yet** — it fired ~0.83 s *after* the occupancy was already
created. The gate only looks **backward** (`delta >= 0`) at the last transition; a
mmwave edge that **leads** the fan-on is never "within 5 s of a recent transition."
Live `fan_transition_suppressed_count=0` confirms the gate never matched. And once
occupancy exists, every subsequent shake tick flunks predicate (c) (sustain, not
creation), so the gate can never retroactively catch the fan-sustained latch.

Answering the operator's sub-question directly: **the gate does NOT catch a mmwave
that PRECEDES the fan transition.** It measures elapsed time *since the last
transition*, so an mmwave onset before the fan-on is scored against the previous
(stale) transition and misses.

### Why it missed Living Room
Occupancy was created at 21:32:50 (`still_target` rose 21:32:49) — **before** the
fan turned on at 21:35:07. The dramatic latch at 21:37:08 (`still_target` on again,
**121 s after** fan-on) is the sustained-airflow shake — but the room was already
occupied, so it hits the **sustain** path, flunking predicate (c). Even if it had
been a creation, 121 s is ~24× outside the 5 s window (e). The gate is structurally
incapable of this case on two independent grounds (creation-only AND window length).

### The structural gaps (the operator's three)
- **(a) window too short:** yes for the *sustained* signature — Living Room's latch
  appeared 121 s post-start; a transition-edge window can never cover shake that
  manifests seconds-to-minutes after the fan reaches steady airflow.
- **(b) "creation-only" misses re-assert / sustain:** yes — this is the dominant miss
  for BOTH rooms. In both, occupancy was **created before** the fan moved (because the
  fan turns on *as a consequence of* the room going occupied), so the shake only ever
  **sustains** an existing hold. The gate deliberately never touches sustain.
- **(c) keying on TRANSITIONS misses steady-state running shake:** yes — the
  separability probe (const.py:811-815) that motivated the gate measured phantom
  **onsets** aligned to transition edges; but these two episodes are phantom
  **sustains** driven by steady running airflow (Study A mmwave held ON for >60 min
  with the fan running), which a transition-edge detector cannot see.

**TRACE 2 VERDICT.** The gate did not suppress these two latches because both are
**sustain-direction phantoms created before the fan transition and held by steady
running airflow** — precisely the two directions the gate, by design (const.py:821-824),
does not cover: it is a **creation-only, backward-looking, 5 s transition-edge**
suppressor. It can only catch a mmwave-sole rising edge that FOLLOWS a fan transition
within 5 s. The class of fix that closes it is a **sustained-shake veto/demotion keyed
on fan RUNNING state** (not transition edges), acting on the SUSTAIN path — i.e. the
STEP/chatter fan-shake work — rather than extending the coincidence window.

---

## Bottom line

- **(a) Fix sensor categorization? NO.** Study A's categorization is already correct
  (`presence_sensors=[zigbee mmwave]`, `motion_sensors=[]`, no motion entity). The
  precedence "second bug" is disproven live; touching categorization would be a fix
  to a non-bug and would not have armed the recheck.
- **(b) Extend/replace the fan-transition gate? YES — but replace, don't stretch.**
  The two live misses are sustain-direction phantoms (occupancy created before the
  fan-on; shake sustains for minutes). A longer window would not help Study A (the
  edge preceded occupancy) and only partially helps Living Room. The correct fix is a
  **fan-RUNNING sustained-shake demotion/veto** (the STEP/chatter track), plus
  ensuring the **fan-recheck actually arms** as the test-under-fan backstop.
- **Prerequisite finding (highest priority):** the fan-recheck did not arm for a
  textbook-eligible empty room and left **no diagnosable evidence** — veto reasons and
  eval counts are computed (`presence_fan_recheck.py:302-313`) but exposed on no
  entity/log, and the tick fan-out swallows exceptions to DEBUG (`presence.py:6904`).
  Surface these before assuming any specific arm-blocker. The two sustain backstops
  that should have caught these rooms — D2 mmwave-fan demotion (`mmwave_fan_demoted=false`
  live) and fan-recheck (`fan_recheck_state="idle"`) — **both silently no-opped**, and
  the creation gate structurally could not. That triple-miss, not sensor
  categorization, is why the empty rooms stayed occupied.

### What is undetermined (stated explicitly, not guessed)
- The single arm-blocking veto for Study A: not recoverable post-hoc (no surfaced
  counter/log). Every documented veto is ruled out by live state, which points at
  either a swallowed exception in the tick fan-out or a race not visible after the
  fact — both require the observability fix to confirm.
- Whether D2 mmwave-fan demotion evaluated-but-declined vs never-ran for Study A:
  `mmwave_fan_demoted=false` live tells us the outcome, not the reason (same
  observability gap).
