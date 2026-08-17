# RESEARCH — Census vs Guest: separation of concerns

**Date:** 2026-08-16 · **Mode:** read-only synthesis (code inspection + full prior-art read)
**Status:** authoritative context document. Not a plan. No code, no cards, no plan edits.

**Occasion.** The operator issued an architectural ruling that the current
work does not fully honour:

1. *"Census and guest are different states. Separate concerns."*
2. Census priorities: **(a) accurate head count, as fresh as possible** —
   *"don't ignore our exterior census prior art and work"*; **(b) the
   transition to guest mode from census AND OTHER SIGNALS."*
3. *"**Census decay is also not the same as Guest decay.**"*

This document is structured around that ruling. §1 defines the two states
separately. §2 is the decay analysis — the core of the ruling. §3 is the
exterior prior art. §4 audits the in-flight cycle against the separation.
§5 is the separated end-state, ranked.

**Prior art read in full:** `PLANNING_census_overcount_dedup_decay.md`,
`PLANNING_census_fusion_policy.md`, `PLANNING_census_ble_cancel_unrecognized.md`,
`PLANNING_guest_fp_lost_away_and_outdoor_census.md` (superseded stub),
`GOLDEN_MASTER_census_cutover_diff.md`, `PLANNING_v4.7.18_census_service_shared_refactor.md`,
`MAP_exterior_camera_paths.md`, `AUDIT_exterior_camera_adjacency_probe.md`,
`AUDIT_exterior_camera_detection_settings.md`, `PLANNING_exterior_person_escalation.md`,
`PLANNING_exterior_track_linking.md`, `AUDIT_census_accuracy_regression.md`,
`AUDIT_guest_fp_fixes_wiring.md`, `RESEARCH_guest_actuation_and_census.md`,
`PLANNING_guest_census_correctness.md` (rev-2, BUILDING NOW),
`PLANNING_v5.7.0_guest_mode_detection_and_actuation.md`,
`PLANNING_v4.7.x_guest_mode_actuation_phase1.md`,
`PLANNING_v4.6.2.2_guest_mode_hardening.md`,
`PLANNING_v4.7.2_dpm_hvac_surface_plus_guest_signal.md`,
`PLANNING_presence_guest_latch_and_veto_gap.md`, `PLANNING_gap_a_census_hole.md`,
`AUDIT_memory_handbuild_compactor_exterior_track.md`.

---

## §1 — The two states, defined separately

### 1.1 CENSUS

**What it IS.** A *measurement*. An estimate, produced every
`SCAN_INTERVAL_CENSUS = 30 s` (`const.py:1390`), of how many human bodies
are physically inside the house right now, partitioned into `identified`
(name-attributable via BLE ∪ fresh face) and `unidentified` (detected but
not attributable). It is a sensor reading, not a decision.

**What it is FOR.** Answering "how many people, and do we know who". It is
the substrate under every *is anyone home* judgement in the system.

**Current implementation.** `camera_census.py` (3171 lines), class
`PersonCensus`, no coordinator subclass. Two competing derivations:

- **Raw / subtractive** — `_cross_correlate_persons` `camera_census.py:1746-1818`.
  `unidentified = max(0, camera_total − identified)`; `total = max(camera_total, identified)`.
  `camera_total` comes from `_dedup_by_area` (per-area MAX, summed) at `:1331`.
  Structurally enforces *a person is counted once, as identified or as
  unidentified, never both*. **Computed on every tick and then discarded**
  whenever the enhanced path is on.
- **Enhanced / additive** — `_apply_enhanced_house_census` `camera_census.py:3075-3137`,
  **default ON** (`CONF_ENHANCED_CENSUS`, `const.py:2676`). `unidentified_raw = camera_unrecognized`
  (`:3102`) → `_apply_hold_decay` (`:3105`) → `total = identified_count + held_unidentified`
  (`:3109`). It replaced the raw path's structural invariant with two
  *best-effort corrections*: the per-camera fresh-face `−1` (`:2760`) and
  the per-area BLE-cancel (`:2798-2816`). **Both fail open, and both are
  returning zero on the live house right now.**

**Published as:** `sensor.ura_persons_in_house` (`sensor.py:3456`, base
`_CensusBaseSensor` `:3411`, `has_entity_name=True` — the planning docs
render this as `sensor.universal_room_automation_persons_in_house`),
`sensor.ura_identified_persons_in_house` (`:3534`),
`sensor.ura_unidentified_persons_in_house` (`:3573`),
`sensor.ura_persons_on_property_exterior` (`:3593`),
`sensor.ura_total_persons_on_property` (`:3630`),
`sensor.ura_census_confidence` (`:3668`, diagnostic, **disabled by
default**), `sensor.ura_census_validation_age` (`:3696`, disabled by
default); plus the presence mirror `sensor.ura_presence_census_count`
(`:5302-5337`). Dispatched on `SIGNAL_CENSUS_UPDATED`
(`domain_coordinators/signals.py:18`, emitted `camera_census.py:1178-1193`).

*Prior-art correction:* `sensor.ura_census_house` /
`sensor.ura_camera_census_house`, named in several planning docs, **do not
exist**. The v5.9.0 D-E observability attributes (`area_contributions`,
`raw_pre_dedup_sum`, `pending_peak`, `peak_held`, `peak_age_minutes`,
`camera_unrecognized`, `ble_cancelled_count`, `wifi_guest_floor`,
`stuck_cameras`) all landed on `sensor.ura_persons_in_house`
(`sensor.py:3494-3530`).

**Consumers.** ~18 trust decisions, enumerated in
`PLANNING_guest_census_correctness.md` §CONSUMER. The highest-consequence:
security lockdown (`security.py:774-775, 969-1010` — locks doors, HIGH NM,
starts recording), nobody-home→AWAY (`presence.py:1059-1063`),
`has_people` (`presence.py:1211-1214`), phone-left-behind suppression
(`binary_sensor.py:1769-1773`), wake backstop (`presence.py:6004-6014`),
and — the subject of this document — GUEST entry and exit
(`presence.py:1262-1274`, `:1241-1243`).

**Freshness/persistence requirement.** **Freshness is the whole
requirement.** A census reading that is thirty minutes old is not a
conservative reading, it is a *wrong* reading, and every consumer above
treats it as current. The only legitimate persistence census needs is a
short bridge across detector dropout — the gap between camera frames, the
mmWave still-body gap. That is a *sensor-debounce* requirement measured in
detection cadence (tens of seconds), not a policy requirement measured in
tens of minutes.

### 1.2 GUEST

**What it IS.** A *policy state*. One value of the `HouseState` enum
(`domain_coordinators/house_state.py:32`), owned by `HouseStateMachine`
(`:108-252`), meaning "the household is currently hosting someone who is
not a resident, and the house should behave differently because of it."

**What it is FOR.** Changing how the house behaves while a visitor is
present. Per the honest inventory in `RESEARCH_guest_actuation_and_census.md`
§4 and independently verified: it preserves manual HVAC holds
(`hvac_const.py:224` `ARRESTER_HOLD_PRESERVING_STATES`, consumed
`hvac_override.py:528-560`) — the single largest real effect; zeroes the
DPM offset (`dynamic_preset.py:860-861`); suppresses Bayesian occupancy
learning (`__init__.py:2453-2473`); suppresses optimizer accuracy-drift
findings (`optimization.py:2610-2650`) and the anomaly sensor
(`binary_sensor.py:2662-2669`); excludes guest rows from routine-forecast
training (`routine_forecaster.py:101,319-322,467-481`); downgrades
exterior-person NM severity to MEDIUM (`const.py:1617,1711-1712` →
`perimeter_alert.py:1563-1570`); arms security to `ARMED_HOME`
(`security.py:161`); and **blocks the house from entering SLEEP at all**
(`house_state.py:82` — `VALID_TRANSITIONS[GUEST]` has no SLEEP target).
Guest HVAC *setpoints* are identical to HOME (`hvac_const.py:789`
`"guest": "home"`), and the designed per-zone guest override producer
`build_guest_mode_overrides` was **deleted for having zero callers**
(`preset_overrides.py:241-249`).

**Published as:** `sensor.universal_room_automation_house_state`;
`binary_sensor.ura_guest_mode` (`binary_sensor.py:2004-2039`, a pure
mirror with no internal consumer).

**Current implementation — three paths OR'd.** `presence.py:5382-5404`:

- **Path A (census-unidentified)** — `_guest_gate_armed` `presence.py:4861-4938`.
  Kill switch → `unidentified_count > 0` → census confidence ≥ `medium` →
  sustained 300 s. Confidence 0.8.
- **Path B (guest-room sustained occupancy, v4.7.2 D5)** —
  `_guest_room_gate_armed` `presence.py:4830-4859`. Any room flagged
  `CONF_ROOM_IS_GUEST_ROOM` (`const.py:386`) occupied by an unknown
  occupant continuously for `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN`
  (`const.py:387`, live 30 min on 3 rooms). No confidence gate, no
  persistence knob, immediate exit. Confidence 0.9.
- **Path C (manual)** — `HouseStateMachine.set_override()` `house_state.py:213-221`,
  bypasses validation, hysteresis, and the kill switch.

`guest_armed = unid_gate_armed or guest_room_gate_armed` (`:5392`) is
collapsed to a single boolean before it reaches the engine (`:5784`); the
engine (`:1267-1274`) cannot tell which path fired.

**Freshness/persistence requirement.** **The exact opposite of census.**
Guest wants *hysteresis*. A guest asleep in a dark room, invisible to every
camera and carrying no known BLE tag, is still a guest — the house must not
revert to HOME the moment the measurement drops. Guest should be sticky by
design, entered on strong evidence and exited on evidence of *departure*,
not on evidence *decaying*.

### 1.3 Where the implementation serves one concern at the other's expense

| Site | Serves | At the expense of |
|---|---|---|
| `_apply_hold_decay` `camera_census.py:2500-2621` — 3-min hold + −1/300 s decay applied to `unidentified_raw` | GUEST (wants stickiness) | **CENSUS** — the published head count is deliberately not the measurement. `sensor.persons_in_house` is a *lagging maximum*, not a count. |
| `presence.py:4886` — Path A arms on `unidentified_count > 0`, reading the **held** value | GUEST (borrows census's stickiness as its own hysteresis) | **CENSUS** — census cannot reduce its hold without destabilising guest, so the hold is politically frozen. |
| `presence.py:1243` — GUEST exit requires `unidentified_count == 0`, the **held** value | CENSUS (census "owns" the exit) | **GUEST** — guest cannot define its own release condition; it is released by an arithmetic decay it does not control. |
| Enhanced path chosen over raw `camera_census.py:3109` | GUEST/anomaly detection (wants a bigger unidentified bucket, more sensitive) | **CENSUS** — dropped the raw path's one-person-one-count invariant; live reads **10 for 5 people**. |
| `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800` (`const.py:2711`) as a rung-1 constant | neither, historically | **CENSUS** — post-F2 it is the binding gate; `face_recognized_persons: []` while `face_confirmed` has all 4 names. |
| Exterior census `_calculate_property_census` `camera_census.py:1501-1580` counts 1 per firing camera and sums | nothing | **CENSUS** — one walker across three perimeter cameras reads 3, while a fully-built track-deduped counter sits unused (§3). |

**Summary of the pathology:** there is exactly ONE temporal mechanism in
this system — `_apply_hold_decay` — and it is doing double duty as
census's anti-flicker filter *and* as guest's hysteresis. The two want
opposite behaviour from it. That is the ruling, stated mechanically.

---

## §2 — DECAY: the core of the ruling

### 2.1 Every timer, both systems

**Census (`camera_census.py`):**

| Timer | file:line | Value | What it does |
|---|---|---|---|
| `SCAN_INTERVAL_CENSUS` | `const.py:1390` | 30 s | tick cadence |
| `CENSUS_EVENT_DEBOUNCE_SECONDS` | `const.py:2708` | 30 s | event-trigger coalescing (was 5 s, raised v4.2.8 for DB write burst) |
| `CENSUS_PEAK_SUSTAIN_SECONDS` | `const.py:2705` | **15 s** | upward moves must sustain before latching the peak. **House only** — `sustain_applies = zone == "house"` `camera_census.py:2543`; property latches instantly `:2579-2584` |
| `CONF_CENSUS_HOLD_INTERIOR` / `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES` | `const.py:2679` / `:2695` | **3 min** (was 15; retuned v5.9.0 D-C) | within the hold window the stored peak is returned verbatim `camera_census.py:2600-2602` |
| `CONF_CENSUS_HOLD_EXTERIOR` / `DEFAULT_CENSUS_HOLD_EXTERIOR_MINUTES` | `const.py:2680` / `:2696` | 5 min | as above, property zone |
| `CENSUS_DECAY_STEP_SECONDS` | `const.py:2697` | **300 s** | after the hold expires, house decays **−1 person per 5 minutes** `camera_census.py:2606-2616`. **Property drops instantly instead** `:2617-2621` |
| peak-refresh-on-equality | `camera_census.py:2585-2589` | — | if `fresh_count == peak`, the peak timestamp is **reset**. Decay never starts while the error is steady. |
| `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` | `const.py:2711` | 1800 s | face-match freshness; gates both `identified` and the per-camera `−1` |
| Bermuda/BLE `tracking_status == 'stale'` handling | `camera_census.py:2309`, `:2344-2350` | — | a resident held STALE/LOST by `bermuda_decay` is excluded from BLE-cancel, so it cannot cancel a real detection |
| `CONF_CENSUS_BLE_CANCEL_ENABLED` | `const.py:2688-2689` | True | kill switch on the per-area BLE subtraction (`camera_census.py:2459`, applied `:2803`). Shipped **despite the plan explicitly rejecting a CONF flag** |
| `STUCK_CAMERA_HOURS` / `STUCK_CAMERA_NEVERZERO_HOURS` | `const.py:3605` / `:3673` | **3.0 h / 6.0 h** | `_watchdog_stuck_cameras` `camera_census.py:1997` — the only *staleness* defense in the census, and it runs on a multi-hour horizon. Fail-open (`:1116-1125`) |
| `CENSUS_MISMATCH_THRESHOLD` / `_DURATION_MINUTES` | `const.py:2124` / `:2125` | 2 / 10 min | census-vs-other mismatch anomaly |
| peak/pending state lifetime | `camera_census.py:2625-2652` | **RAM-only** | `_peak_house_camera_count`, `_peak_house_timestamp`, `_pending_house_peak*` reset on every reload — the hold/decay state is not persisted |
| `TRACK_LINK_WINDOW_S` / `TRACK_CLOSE_IDLE_S` (exterior) | `const.py:1724` / `:1725` | 180 s / 300 s | §3 |

**Guest (`presence.py`, `house_state.py`):**

| Timer | file:line | Value | What it does |
|---|---|---|---|
| `CONF_GUEST_MODE_PERSISTENCE_SECONDS` | `const.py:2719-2720` | **300 s** (live 300; 0 = fire immediately) | Path A: `unidentified_count > 0` must hold *continuously*; `_unidentified_first_seen` cleared on any non-qualifying tick `presence.py:4653-4662`. Read `:4911-4938` |
| persistence recheck buffer | `presence.py:4961-4966` | +5 s | forced one-shot recheck so firing doesn't depend on census jitter |
| `CONF_GUEST_MODE_REQUIRE_CONFIDENCE` | `const.py:2722-2723` | `"medium"` | Path A only; rank map `presence.py:4641` |
| `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN` | `const.py:387`, read `presence.py:4705` | **30 min** (live, all 3 rooms) | Path B arming dwell. **Exit is immediate** (`presence.py:4837`); state is in-memory, resets on restart |
| GUEST hysteresis / min dwell | `house_state.py:103` | **300 s** | vs 120 s for HOME_* |
| guest-exit damping (v4.7.15 D3) | `presence.py:6032-6087`, veto scope `:1952-1971` | threshold falls back to `_guest_persistence_seconds` = **300 s** | GUEST→HOME_* suppressed unless the quiet condition sustains |
| `_disarm_guest_gate` clears | `presence.py:4653-4662`, `:5365-5372`, `:6286-6293`, `:6976-6977` | — | on fire, count drop, confidence regression, leaving HOME_*/GUEST, unload |

### 2.2 Which timers are shared or coupled

Path B is **fully decoupled** from census — it reads room occupancy binary
sensors and a known-person map, nothing else. Path C bypasses everything.

**Path A is coupled to census at two points, both reading the SAME held
value, and both are load-bearing:**

- **ENTRY.** `presence.py:5384-5388` passes `self._unidentified_count`
  into `_guest_gate_armed`; Guard 1 at `:4886` tests `unidentified_count <= 0`.
  `self._unidentified_count` is set at `presence.py:4319-4323` from the
  dispatched payload, which carries `unidentified_count=held_unidentified`
  (`camera_census.py:3116`) — **the post-hold, post-decay value.**
- **EXIT.** `presence.py:1241-1243`:
  `if current_state == HouseState.GUEST and unidentified_count == 0 and not guest_gate_armed:`
  — the same held value, as a **conjunct**. Both terms must be satisfied.

So the *only* hysteresis Path A has is `guest_mode_persistence_seconds = 300 s`,
and the *only* release Path A has is census decaying to exactly zero. Guest
owns neither of its own temporal boundaries.

### 2.3 Quantifying the conflict

**Case 1 — a 15-second phantom becomes GUEST mode. Deterministically.**

Take a single spurious detection (an IR ghost, a reflection, a resident
double-counted across two cameras in the same second) of magnitude +1,
lasting just long enough to clear the sustain gate.

| t | State | Mechanism |
|---|---|---|
| 0 s | `fresh = 1`, true count 0. Pending latch opens | `camera_census.py:2545-2551` |
| 15 s | Sustain met → **peak = 1 latched** | `:2566-2571` (`CENSUS_PEAK_SUSTAIN_SECONDS`) |
| 15 s+ | Phantom gone, `fresh = 0`. Hold window returns `peak = 1` | `:2600-2602` |
| 195 s | Hold (180 s) expires, decay begins. `decay_steps = int(15/300) = 0` → still returns 1 | `:2606-2609` |
| 495 s | `decay_steps = 1` → `decayed = max(0, 1−1) = 0`. Released | `:2610-2614` |

`unidentified_count ≥ 1` is published continuously for **480 seconds**.
Path A requires 300 s continuous. **480 > 300.** GUEST fires at t ≈ 315 s
and the house enters GUEST mode — blocking SLEEP, preserving HVAC holds,
suppressing learning — on the strength of a **fifteen-second** camera
artefact.

The census's own stabiliser *manufactures the durability that the guest
gate treats as evidence.* `RESEARCH_guest_actuation_and_census.md` §1.5
states it exactly: *"The existing sustain machinery cannot distinguish
'sustained because real' from 'sustained because held.'"* This is the
mechanism behind the **50 guest ENTRY episodes since 2026-07-13**, across
22 of 31 days, 1–7/day, almost all daytime and flappy
(`AUDIT_guest_fp_fixes_wiring.md` §3).

Note also that `PLANNING_census_overcount_dedup_decay.md:100-114` explicitly
audited this coupling and **cleared it**: *"A 15 s sustain-latch is well
inside that 300 s persistence window and does not shift GUEST behavior
perceptibly. **Tolerates.**"* The reasoning compared the sustain window to
the persistence window and never asked how long the latched value *stays*.
It is off by a factor of 32.

**Case 2 — GUEST cannot be released for 33 minutes.**

Tonight's live over-count is `unidentified = 6`. If the cameras clear
completely, decay from 6 to 0 costs `180 s hold + 6 × 300 s = 1980 s`
(**33 minutes**) before `unidentified_count == 0` is even *possible*.
Then the exit must survive the `guest_exit` veto scope's 300 s quiet
window (`presence.py:6032-6087`) and the 300 s GUEST hysteresis
(`house_state.py:103`). **Minimum GUEST release latency after the house is
physically empty of strangers: ~38 minutes.**

**Case 3 — the worst case: decay never runs at all.**

`camera_census.py:2585-2589`: when `fresh_count == peak`, `_store_peak` is
called with `now`, **resetting the hold timestamp**. Decay only advances
when the fresh count is strictly *below* the peak. A *systematic* error —
which is precisely today's failure, where BLE-cancel returns 0 on every
tick and `camera_unrecognized == frigate_count` every tick — produces a
steady `fresh` value that continuously refreshes its own peak. **The decay
mechanism provides zero protection against systematic over-count.** It is
a transient-smoother that does nothing about the actual error class, while
converting sub-minute transients into guest-qualifying evidence.

Decay has the wrong sign on both axes.

### 2.4 What each concern actually needs

| | CENSUS | GUEST |
|---|---|---|
| Wants | **Freshness.** A stale count is a wrong count. | **Hysteresis.** A guest asleep in a dark room is still a guest. |
| Legitimate persistence | Bridge detector dropout only — one to two detection cadences. Today's cadence is 30 s. **~30–60 s, symmetric.** | Long. A guest visit is hours. Release should require *evidence of departure*, not absence of evidence. |
| Correct release | Instant drop to the fresh measurement, with the measurement's **age and confidence stamped on the payload** so consumers decide for themselves. | An explicit exit predicate: the guest room cleared, or a known person occupies it, or the house went AWAY, or manual. |
| Correct shape | A number + a timestamp + a confidence. | A latch with named entry and exit conditions. |
| Wrong shape | A lagging maximum with a linear decay slope. | A decaying count crossing zero. |

**Target semantics — census.** Publish the measurement. Adopt for the house
zone the semantics the **property zone already has**
(`camera_census.py:2617-2621`: hold, then *instant drop to fresh*). Delete
the linear `−1 per 300 s` slope entirely — it has no measurement
justification and is the whole of the durability problem. Reduce
`CONF_CENSUS_HOLD_INTERIOR` from 3 min toward detector cadence (it is
already a rung-2 knob, `const.py:2679`, so this is reversible without a
deploy). Keep `CENSUS_PEAK_SUSTAIN_SECONDS = 15` — that one is genuinely a
measurement-quality gate and it is symmetric in intent. Then publish
`peak_held` and `peak_age` — **already returned by `_apply_hold_decay`
(`camera_census.py:2505`) and already partly surfaced** — alongside the
count, so every consumer can see whether it is looking at an observation or
at an echo.

**Target semantics — guest.** Guest should not be derived from a decaying
count at all. It should be a latch with explicit conditions:

- **Entry:** room-attributed sustained unknown occupancy (Path B, which
  already exists and is already live on three rooms), corroborated —
  optionally, for confidence only — by census, guest-VLAN WiFi, BLE-unknown,
  or an exterior arrival track.
- **Exit:** the arming condition clears, i.e. `not guest_armed` — plus the
  existing 300 s damping and 300 s hysteresis, which are the *right* kind
  of timer for a policy state and should be retained.
- **Not:** `unidentified_count == 0`.

If any census signal remains in the guest path at all, it must read
`unidentified_raw` (`camera_census.py:3102`, already computed on every
tick), **never** `held_unidentified`. That is gap G6 in
`RESEARCH_guest_actuation_and_census.md` §7 — and it is currently parked.

### 2.5 Prior art: the separation was already designed once, and never built

`PLANNING_v4.7.18_census_service_shared_refactor.md` proposed exactly this
split and is **almost entirely unbuilt**:

- **D1 — `CensusHoldDecayService`**: extract hold/decay out of
  `PersonCensus` into a shared service so the temporal policy is owned
  separately from the measurement. **NOT BUILT** — no `census_service.py`
  exists; the class name appears nowhere in the repo except that planning
  doc. `_apply_hold_decay` still owns its state in place at
  `camera_census.py:2500`.
- **D5 — presence-side `peek()` visibility into hold state**: so the guest
  gate could *see* whether it was looking at a held value or a live one.
  **NOT BUILT.** Presence sees hold state only indirectly, via the
  `peak_held` / `peak_age_minutes` attributes it does not read.
- D2 (phantom filter via `person_active_count`, `CENSUS_PHANTOM_GRACE_SECONDS`),
  D3 (tier-1/tier-2 `binary_sensor.ura_any_person_on_property` /
  `ura_possible_guest_entry`), D4 (full-scan warning sensor) — **none
  built**. Note D3's `ura_possible_guest_entry` was an explicit attempt to
  give guest its *own* derived signal rather than have it read the census
  count directly.

The triggering incident for that cycle is the same failure this document
describes: a stationary Frigate ghost (`playroom_person_count = 1`,
`person_active_count = 0`) latched through `_apply_hold_decay`, outlasted
the guest persistence gate, and put the house into GUEST **with all four
residents `not_home`**. The remedy chosen at the time was the 3 h/6 h stuck
watchdog and the divergence downgrade — neither of which catches a
sub-three-hour ghost that has any house-wide corroboration.

**The idea in the ruling is not new to this codebase. It was scoped in
v4.7.18, deferred, and the intervening cycles have all been accuracy
patches to the measurement rather than a separation of the two concerns.**

---

## §3 — Exterior census prior art

The operator's *"don't ignore our exterior census prior art and work"* is
well-founded: there is a substantial, live, correctly-shaped exterior
counting system, and the census does not consume it.

### 3.1 Two independent "exterior" concepts, which do not touch

**(a) The zone outdoor flag.** `CONF_ZONE_IS_OUTDOOR` (`const.py:72-73`,
default False), set in the zone flow (`config_flow.py:903-927`,
`7830-8018`). Consumed by exactly three surfaces:
`presence.py:5306-5318` (`any_indoor_zone_occupied` — so an occupied patio
does not jam the WS-A2 path-β AWAY veto), `safety.py:1302-1308`, and
`aggregation.py:4284-4334`. **`camera_census.py` never imports it** —
verified, zero `is_outdoor` hits in the file. This is v5.7.0 WS-A
Residual-B1, and it is gap **G9**.

**(b) The census house/property split.** Not a flag at all — pure config-list
membership. Interior = `CONF_CAMERA_PERSON_ENTITIES`
(`camera_census.py:1836-1850`); exterior = `CONF_EGRESS_CAMERAS` +
`CONF_PERIMETER_CAMERAS` (`camera_census.py:1501-1580`). The two zones
produce separate `CensusZoneResult`s that join only at
`total_on_property = house + property` (`camera_census.py:1137`).

**Does exterior feed the interior count? No.** The dispatch payload
(`camera_census.py:1180-1191`) carries `interior_count`, `unidentified_count`,
and a separate `property_count`; `PresenceCoordinator._handle_census_update`
reads **only** `interior_count` (`presence.py:4310`) and `unidentified_count`
(`:4317`). `property_count` has zero readers outside `camera_census.py`.
So the "patio person counted as interior" hypothesis is **structurally
false today**, with exactly one residual exposure: a camera placed in *both*
`CONF_CAMERA_PERSON_ENTITIES` and `CONF_PERIMETER_CAMERAS` would count in
both zones, and `config_flow.py:2923-2951` has **no cross-exclusion
validation**. The documented contamination incident runs the *other*
direction — interior cameras opening exterior tracks and "poisoning the
census" (`exterior_track_linker.py:364-371`, and SECC-1 at `:424-437`,
2026-08-07) — fixed with a fail-closed camera allowlist.

### 3.2 BUILT vs DESIGNED-BUT-UNBUILT

**BUILT and live:**

- **`ExteriorTrackLinker`** — `exterior_track_linker.py`, ~970 lines, live
  since 2026-08-06. Space-time track linking, no re-ID: `observe()` `:399-553`,
  adjacency+window candidate search `:581-602`, idle sweep `:604-614`,
  close+episode write `:633-703`, classification `:705-750`. The compactor
  audit found **1052 `exterior_track` rows spanning 2026-08-06 → 2026-08-14**.
  Instantiated `__init__.py:2729-2746`, torn down `:4605-4608`.
- **A track-deduped, identity-aware exterior person count** —
  `ExteriorTrackLinker.census_counts()` `exterior_track_linker.py:766-782`,
  returning `exterior_person_tracks_active` and — note this —
  **`exterior_unidentified_persons`** (`:774-776`, `sum(1 for t in person if not t.identified)`).
  Published as real sensors at `sensor.py:3780-3930`, registered `:162-167`.
- **The ratified adjacency graph** — `const.py:1742-1800`, mined from the
  recorder and then **corrected against physical truth by the operator**
  (`AUDIT_exterior_camera_adjacency_probe.md:174-201`): pool-service chain
  added despite low counts, `pool_equipment↔rear_ptz` (6 obs) and
  `rear_ptz↔utilities_ptz` (17 obs) removed as physically impossible.
  Standing policy from that audit: *"If splits at these seams recur, fix
  camera detection reliability, do NOT re-add false edges."*
- **Detection tuning** — `AUDIT_exterior_camera_detection_settings.md`:
  masks/zones ruled out fleet-wide as a miss cause; person threshold
  0.7→0.6 and `min_initialized` 2→1 on three cameras; the 320×320 model vs
  640×360 detect stream identified as the real miss mechanism. Operator
  correction at `:119-152`: F1/F2 do **not** share an MQTT prefix, so the
  720p win lands only on `_2` entities. **Standing follow-up: re-run the
  adjacency transition-mining probe ~1 week after 2026-08-06 — overdue.**
- Escalation surfaces: `NM_HAZARD_EXTERIOR_PERSON` `const.py:1547`,
  severity-by-house-state `const.py:1622-1633`, track severity map
  `const.py:1842-1875`, consumed in `perimeter_alert.py` and `button.py`.

**DESIGNED-BUT-UNBUILT:**

- **G9 — the camera-census outdoor filter.** Zero code. Latent-safe only
  because Patio has no camera person inputs; a config change alone arms it.
- Adjacency-as-data (`exterior_adjacency.json` export/import service,
  `PLANNING_exterior_track_linking.md:148-168`) — const-only today.
- `SIGNAL_NM_EXTERIOR_PERSON` security auto-follow
  (`PLANNING_exterior_person_escalation.md` D6) — explicitly note-only.
- `MAP_exterior_camera_paths.md` is a pure narrative/vision doc, zero code
  artifacts.

### 3.3 Exterior decay — and why it is the right shape

| Mechanism | file:line | Value |
|---|---|---|
| `CONF_CENSUS_HOLD_EXTERIOR` | `const.py:2680` / `:2696` | 5 min |
| **Instant drop after hold** (no linear decay) | `camera_census.py:2617-2621` | — |
| **No sustain gate** (instant rise) | `camera_census.py:2543`, `:2579-2584` | — |
| `TRACK_LINK_WINDOW_S` | `const.py:1724` | 180 s (0 = kill switch) |
| `TRACK_CLOSE_IDLE_S` | `const.py:1725` | 300 s |
| sweep cadence | `exterior_track_linker.py:277-281` | 150 s |
| `_OBSERVE_DEDUP_S` | `exterior_track_linker.py:67`, used `:465` | 2.5 s |
| `PERIMETER_ALERT_COOLDOWN_SECONDS` | `const.py:1452` | 300 s |

The rationale is recorded in the source
(`camera_census.py:2530-2540`): *"a perimeter camera firing is a safety
signal that must not be delayed by 15 s."*

**This is the important observation.** The exterior leg already resolves
the census/guest tension correctly, by accident of its safety framing:
instant rise, instant fall, no decay slope — and where persistence *is*
needed, it is expressed as **track identity with an idle-close**
(`TRACK_CLOSE_IDLE_S`), not as a decaying count. A track is a *thing that
exists until it stops being observed for 5 minutes*; that is a latch, and
it is exactly the shape guest wants. The interior census, by contrast, uses
a decaying number for both jobs and does neither well.

### 3.4 What the exterior work implies

**(a) For headcount accuracy.** Two parallel, non-reconciled exterior
counts run in production. `sensor.persons_on_property_exterior`
(`camera_census.py:1517-1527`) counts **1 per firing camera and sums** —
one walker across three perimeter cameras reads 3, with `identified_count`
hard-zero (`:1567`) and confidence pinned MEDIUM (`:1546-1557`).
`sensor.exterior_person_tracks_active` counts **open linked tracks** — one
walker reads 1. The de-duplicated answer is already computed, already
published, and already correct. The census does not consume it. `camera_census.py`
contains no reference to the linker.

**(b) For guest transitions.** `exterior_unidentified_persons`
(`exterior_track_linker.py:774-776`) is a *track-identity-derived count of
unidentified people on the property* — arguably the single best-formed
"other signal" in the codebase for the operator's priority (b), *"the
transition to guest mode from census AND OTHER SIGNALS."* An exterior
person track that approaches an egress camera and then disappears is an
**arrival**; an arrival is exactly the kind of discrete, latchable event a
guest state should be entered on. Today it feeds NM severity shaping and
nothing else.

---

## §4 — Does the in-flight cycle honour the separation?

`PLANNING_guest_census_correctness.md` rev-2, card `CENSUS-GHOST-DEDUP-1`,
Tier 2-DB, is BUILDING NOW. Verdict: **directionally right, and it
contains one specific defect that will produce a visible failure on
deploy.**

### 4.1 Per-deliverable

| | Belongs to | Assessment |
|---|---|---|
| **D1 clamp** (`camera_census.py:3109`, INV-CENSUS-ATTRIBUTION) | **CENSUS-accuracy** | **Correct and well-placed.** It restores the raw path's one-person-one-count invariant to the enhanced path as a *clamp* rather than a third fail-open correction. The rev-2 correction — ceiling from the PRE-cancel Step-2 scalar (`:2779`) rather than the POST-cancel return (`:3090`) — is right, and the reviewer's counter-example that forced it is a genuine catch. Does not couple the concerns. Keep. |
| **D1 / G2 observability** (pre-cancel scalar, `area_raw_max_pre_cancel`, `ble_by_area`, `ble_cancel_enabled`, enhanced `area_contributions`) | **CENSUS-accuracy** | **Correct, and it is the acceptance instrument** — without it, neither the clamp nor the underlying cancellation gap can be validated live. Keep. |
| **D2 guest-rooms-lead** (`presence.py:5392` → `guest_armed = guest_room_gate_armed`) | **GUEST-transition** | **Correct, and it is the single largest step toward the ruling.** It demotes census from *decider* to *corroborator* on guest ENTRY. Both operands already exist and are computed every tick; this is composition, not new mechanism. Keep. |
| **D3 registry-resolve** (`presence.py:4704-4724`, `:4757-4762`) | **GUEST-transition** | **Correct, and a hard prerequisite of D2.** Path B currently subscribes to `binary_sensor.{slug}_occupied` — a *guess*. "Upstairs Guestroom" was renamed, so its real entity is `binary_sensor.upstairs_guest_bedroom_occupied` and the subscription silently fails. Under D2, Path B becomes the **only** entry path; shipping D2 without D3 would ship a guest detector that is broken for a third of the flagged rooms. Correctly sequenced. Keep. |

Nothing in the cycle couples the two concerns *further*. On composition,
the cycle moves in the right direction.

### 4.2 The defect: D1 and D2's acceptance criteria contradict each other

The cycle severs the census→guest coupling on **ENTRY** (D2) and leaves it
fully intact on **EXIT** (`presence.py:1241-1243`, untouched, explicitly
listed under "Preservation checks", plan line 419-422).

Trace the plan's own numbers through its own untouched exit predicate:

- Plan's before-picture (line 626-632): live `house_state = guest` since
  13:38 CT, **entered on Path A alone**, `unidentified_count = 6`.
- Plan's D1 post-fix prediction (line 564-569): `persons_in_house = 6`,
  `identified_count = 4`, **`unidentified_count = 2`**.
- Plan's D2 acceptance criterion (lines 597-599): *"`_guest_gate_armed=True`
  but `guest_armed=False`; `house_state` transitions out of `guest` within
  its exit debounce window."*
- The actual exit predicate, unchanged by this cycle:
  `current_state == GUEST and unidentified_count == 0 and not guest_gate_armed`.

`unidentified_count` will be **2**, not 0. The conjunction fails. **GUEST
will not exit.**

And there is no alternative route out. Walking `infer()` past line 1243
with `current_state == GUEST`: the sleep branch (`:1245-1250`) would
propose SLEEP, but `VALID_TRANSITIONS[GUEST]` (`house_state.py:82`) has no
SLEEP target, so the proposal is rejected; the guest-entry limb
(`:1267-1274`) requires `current_state ∈ {HOME_DAY, HOME_EVENING, HOME_NIGHT}`
and no-ops; the time-based limb (`:1279-1289`) is likewise gated on
`current_state in (HOME_DAY, HOME_EVENING, HOME_NIGHT)`; the function
returns `None`.

**Under this cycle as planned, GUEST becomes a terminal state, exitable only
by the AWAY paths or by manual override, for as long as the residual
over-count keeps `unidentified_count > 0` — which, per §2.3 Case 3, is
indefinitely while the cancellation defenses remain broken.** The cycle's
D1 numeric FAIL thresholds (lines 570-576) would all read PASS while the
house sits stuck in GUEST. The live validation would score green on a
regression.

This is not a hypothetical: the plan itself states the house is in GUEST
*right now*, on Path A, with `unidentified = 6`.

### 4.3 What should be pulled or reshaped

**Nothing should be pulled.** D1, D2, D3 are all correct and all belong.
The cycle is under-scoped by exactly one line.

**Reshape:** the exit predicate at `presence.py:1243` must be brought under
the same ruling as the entry predicate. Under the separation, once
`guest_armed` is defined purely by guest rooms (D2), the complete and
correct exit condition is `not guest_armed` — the `unidentified_count == 0`
conjunct becomes not merely redundant but actively wrong, because it lets
a census artefact hold a policy state that a census artefact can no longer
create.

Three things make this safe to do inside this cycle rather than after it:

1. It makes exit **strictly easier**, which is the safe direction relative
   to the incident that produced the current predicate (2026-07-11: guest
   arrived 20:57, gate cleared 23:05, state held GUEST until 06:05 —
   `PLANNING_presence_guest_latch_and_veto_gap.md`, v5.16.0 D1). The
   v5.16.0 D1 ordering fix — exit evaluated *above* the sleep branch — is
   untouched and still does its job.
2. The stated reason for the `unidentified_count` conjunct
   (`RESEARCH_guest_actuation_and_census.md` §3.3: *"the exit condition
   deliberately tests `guest_gate_armed` (the OR), not raw
   `unidentified_count`, so Path B can hold GUEST at
   `unidentified_count == 0`"*) is satisfied **more directly** after D2:
   `guest_armed` *is* Path B.
3. The exit remains damped by the 300 s `guest_exit` veto scope
   (`presence.py:6032-6087`) and the 300 s GUEST hysteresis
   (`house_state.py:103`) — guest keeps hysteresis it actually owns.

The invariant `INV-GUEST-LEAD` in the plan should be extended
symmetrically, from an entry-only statement to an entry-and-exit one:
*for every inference tick, GUEST membership is determined by
`_guest_room_gate_armed()` alone (Path C excepted).* As written it
constrains only entry, which is why the exit gap survived plan review.

Two smaller notes for the build, neither blocking:

- **`_guest_room_state` is in-memory and resets on restart**
  (`PLANNING_v4.7.2` D5:250). Under D2 this becomes load-bearing: a restart
  now drops the *only* thing that can sustain GUEST, and a real guest
  re-arms only after another 30 minutes. Worth stating as an accepted trade
  in the M1 list, which currently names three trades and not this one.
- **Path B has no confidence gate at all** (`presence.py:4830-4859` checks
  only the kill switch). That was tolerable when it was the weaker operand
  of an OR; under D2 it is the sole decider. Not a defect to fix in this
  cycle, but it should be recorded.

---

## §5 — The separated architecture

**End state.** Two systems with no shared timer.

- **Census** is a measurement service. It publishes a count, the age of
  that count, and a confidence, for interior and exterior separately. It
  smooths only far enough to bridge detector dropout, and it drops
  instantly to the fresh value thereafter. It never holds a value to make a
  downstream policy comfortable. Its accuracy work — attribution clamp,
  BLE-cancel repair, face freshness, exterior track dedup, outdoor
  filtering — is judged solely against ground-truth headcount.
- **Guest** is a policy latch. It has explicit entry conditions
  (room-attributed sustained unknown occupancy, leading; census, guest-VLAN
  WiFi, BLE-unknown, exterior arrival tracks, manual — corroborating) and
  explicit exit conditions (the arming condition clears; a known person
  occupies the room; the house goes AWAY; manual). It owns its own
  hysteresis — the 300 s dwell and the 300 s exit damping it already has.
  It never reads a decayed count.

### Ranked changes

| # | Change | Class | Notes |
|---|---|---|---|
| **1** | **Sever GUEST exit from the census count.** `presence.py:1243`: drop the `unidentified_count == 0` conjunct, leaving `not guest_gate_armed`. | **composition** (one line, 0 net LoC) | *The ruling, in one line.* **Blocks the in-flight cycle** (§4.2) — without it D2 ships a terminal GUEST state. `guest_armed` already computed every tick. |
| **2** | **Guest rooms lead; census corroborates.** `presence.py:5392` → `guest_armed = guest_room_gate_armed`; census raises confidence 0.9→0.95. | **composition** (~5 LoC) | = cycle D2. Both operands built and live. `_guest_room_gate_armed` `presence.py:4830-4859`; 3 rooms already flagged. |
| **3** | **Resolve guest-room entities via the registry.** `presence.py:4704-4724`. | new code (~15 LoC) | = cycle D3. Hard prerequisite of #2 — Path B is currently subscribed to a nonexistent entity for Upstairs Guestroom. |
| **4** | **Attribution clamp on the enhanced census path.** `camera_census.py:3109`, ceiling from the PRE-cancel Step-2 scalar `:2779`. | new code (~10 LoC) | = cycle D1. Restores the raw path's invariant (`:1780-1782`) as a clamp that cannot fail open. |
| **5** | **Delete the linear decay slope on the house zone.** `camera_census.py:2604-2616` → adopt the property zone's instant-drop (`:2617-2621`). Reduce `CONF_CENSUS_HOLD_INTERIOR` 3 min → detector cadence. | **composition + config** | **The instant-drop branch is already written and already running for the exterior** — this deletes an asymmetry rather than adding a mechanism. `CONF_CENSUS_HOLD_INTERIOR` is rung-2 (`const.py:2679`) so the hold change needs no deploy. Only safe **after** #1 and #2, which is why it ranks below them. |
| **6** | **Publish census freshness.** Surface `peak_held` / `peak_age` / a `count_as_of` stamp on the payload and the sensor. | **composition** (~5 LoC) | **`_apply_hold_decay` already returns all three** (`camera_census.py:2505`); they are computed and partly discarded. Lets consumers distinguish an observation from an echo. |
| **7** | **Feed the exterior census from `ExteriorTrackLinker`.** Replace the per-camera OR-sum at `camera_census.py:1517-1527` with `census_counts()`. | **composition** | **Fully built, live, published, zero census consumers** (`exterior_track_linker.py:766-782`, `sensor.py:3780-3930`). Fixes the 1-walker-reads-3 over-count at a stroke. Highest built-but-uncomposed value in the codebase. |
| **8** | **Admit `exterior_unidentified_persons` as a guest corroborating signal.** | **composition** | `exterior_track_linker.py:774-776`. Track-identity-derived, so it is already a latch, not a decaying count. Directly serves operator priority (b), *"guest mode from census AND OTHER SIGNALS."* Corroborator only — never a sole decider. |
| **9** | **Gate any residual census signal in the guest path on `unidentified_raw`, never the held value.** | new code (~15 LoC) | = G6, currently **parked** as `CENSUS-G6-RAW-PERSISTENCE`. `unidentified_raw` already exists at `camera_census.py:3102`. Under #1+#2 this is defence-in-depth rather than the primary fix; it should be the standing *rule* even if the cycle ships without it. |
| **10** | **G9 — outdoor-zone filter in the camera census.** Import `CONF_ZONE_IS_OUTDOOR` (`const.py:72`) into `camera_census.py`. | new code | Latent-safe today only because Patio has no camera person inputs. A config change alone arms it. Also: add cross-exclusion validation so one camera cannot sit in both the interior and perimeter lists (`config_flow.py:2923-2951`). |
| **11** | **Repair the fail-open census defenses.** BLE-cancel returning 0 (`camera_census.py:2793-2822`, root of `CENSUS-GHOST-DEDUP-1`; `_ble_home_by_area` returns `{}` on any exception, `:2374-2380`) and `_get_face_recognized_person_names` returning `[]` while 4 faces are confirmed (the person-tracker cross-check at `:3040-3068` is itself **fail-OPEN** when `person.<slug>` is missing/unknown, leaving only the 1800 s age gate). | new code | The *actual* accuracy fixes. #4's clamp caps the damage; it does not repair the count. |
| **11b** | **Scope the divergence-downgrade corroboration bundle to the zone, not the house.** `camera_census.py:1400-1404` builds `_corroborated` from `bool(ble_persons)` house-wide, so **one resident's phone anywhere in the house re-enables max-wins for a phantom in any room** — the exact 2026-08-01 playroom mechanism the fusion cycle was built to kill. | new code (small) | The fusion policy shipped (`:1646-1670`); its corroboration predicate is over-broad. |
| **12** | **Promote `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` rung 1 → rung 2.** `const.py:2711`. | **config / knob-ladder** | 1800 s was fitted to F1; F2 tuning changed the recognition regime underneath it, and it is now the binding gate. Per the knob ladder, a number the operator would re-tune by observation after a detector change belongs on rung 2. |
| **13** | **Re-run the exterior adjacency transition-mining probe.** | measurement, no code | Standing follow-up from both exterior audits, due ~1 week after the 2026-08-06 detection tuning. **Overdue.** Measure-before-you-build applies before any further exterior work. |

### Already built — needs composing, not building

Per the operator's no-cruft / no-reinvention rule, the following exist,
run, and are tested; they need wiring or a boolean changed, not a cycle:

- `_guest_room_gate_armed` + `CONF_ROOM_IS_GUEST_ROOM` + per-room threshold
  — `presence.py:4830-4859`, `const.py:386-387`, live on 3 rooms. (#2)
- The raw subtractive derivation — `camera_census.py:1780-1782`. Computed
  every tick, then discarded. (#4 borrows its invariant.)
- `unidentified_raw` — `camera_census.py:3102`. Computed, then held, then
  the pre-hold value thrown away. (#9)
- `peak_held` / `peak_age` — `camera_census.py:2505`. Returned, partly
  unused. (#6)
- The instant-drop-after-hold branch — `camera_census.py:2617-2621`.
  Written and running, for one zone only. (#5)
- `ExteriorTrackLinker.census_counts()` including
  `exterior_unidentified_persons` — `exterior_track_linker.py:766-782`,
  with live sensors at `sensor.py:3780-3930`. (#7, #8)
- The ratified adjacency graph — `const.py:1742-1800`. (#7)
- `CONF_ZONE_IS_OUTDOOR` — `const.py:72`, consumed by three coordinators,
  never by the census. (#10)
- Guest's own hysteresis — 300 s dwell (`house_state.py:103`) and 300 s
  exit damping (`presence.py:6032-6087`). These are the *right* timers for
  a policy state. Guest does not need new ones; it needs to stop borrowing
  census's.
- `_cross_validate_platforms` divergence-downgrade — **shipped**
  (`camera_census.py:1586-1609`, `corroborated=` kwarg live at `:1404-1406`),
  despite `PLANNING_census_fusion_policy.md` and
  `RESEARCH_guest_actuation_and_census.md` §5 both recording it as
  DESIGNED-BUT-UNBUILT. Prior-art correction.

### Not to build

- `CONF_GUEST_MODE_MIN_UNIDENTIFIED` (G8) — designed and dropped in
  v4.6.2.2; #2 makes room attribution a better bar than a count threshold.
- `guest_mode_require_confidence` medium→high (G7) — census confidence
  measures *platform agreement*, not correctness. It reads `high` right
  now while the count is wrong by five. Wrong oracle. **And it is not
  inert: do not remove it either.** The fusion cycle's D1b (an explicit
  DISAGREE→suppress-guest gate in presence) was never built; suppression
  is achieved *indirectly* by DISAGREE→LOW (`camera_census.py:1799-1800`)
  failing guard 2 of `_guest_gate_armed` at
  `DEFAULT_GUEST_REQUIRE_CONFIDENCE = "medium"`. That knob is load-bearing
  by accident — a coupling worth recording, since under #2 Path A's guards
  stop deciding anything and the divergence downgrade quietly loses its
  only consumer.
- Guest actuation (`RESEARCH` §4) — do not build actuation on a count that
  reads 10 for 5. `OVERRIDE_SOURCE_GUEST_MODE` and the per-zone guest
  setpoint keys exist with no producer;
  `build_guest_mode_overrides` was deleted for zero callers
  (`preset_overrides.py:241-249`). Leave it deleted until #1–#4 are live.
- Re-admitting the WiFi guest-VLAN floor (`CENSUS-GUEST-FLOOR-1`, parked)
  — its trigger was *under*-reading; today is an over-read. Its premise is
  inverted and must be re-examined before it is unparked.
