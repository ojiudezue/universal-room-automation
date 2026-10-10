# PLANNING — OC-STUCK-SENSOR-GENERALIZE-1

Optimization Coordinator should surface stuck sensors across ALL device kinds,
keyed to the SENSOR, not to a room score.

- Status: PLAN only (operator approved plan 2026-09-18; do not build yet).
- Tier recommended: **Tier 2** (feature cycle, two reviews + live validation).
  - Rationale: extension of an existing OC dimension that already owns
    row-volume suppression and NM paging; no shared-primitive change, no
    cross-coordinator ripple, no DB schema change. Scope is bounded to adding
    row-emitters inside `optimization.py` and (optionally) one knob + one
    override map in `const.py`.
  - Not Tier 3: no cost-and-safety invariant, no state machine, no
    multi-emission-site primitive. Not Tier 2-DB: no schema or DAO change.
- Falsifiable invariant (one line, the thing the cycle must guarantee):
  **"For every raw device sensor URA is configured to consume in classes
  {motion, occupancy}, a stuck-ON episode exceeding its configured horizon
  produces exactly ONE OC `sensor_stuck` finding per episode per day, and a
  class-expected sensor that produces zero ON transitions over the configured
  never-fires window produces at most ONE `sensor_never_fires` finding per
  sensor per day."** Reviewer D's job is to break this with a legal config:
  shared camera_key suffix collisions, URA-aggregate occupancy sensors,
  unavailable gaps masquerading as ON, and daily-latch rollovers at local
  midnight DST.

---

## Institutional context verified

### Code locations surveyed (read end-to-end during scoping)
- `custom_components/universal_room_automation/domain_coordinators/optimization.py`:
  - `_evaluate_camera_stuck_dimension` lines 1881-1953 — camera-only
    stuck-ON evaluator shipped v5.101.3 (CAMERA-STUCK-SENSOR-TRIPWIRE-1).
    Per-key latch (`_camera_stuck_fired`, line 602), measured threshold
    constant, per-camera overrides, resolves cameras from live config lists.
    This is the structural template for the generalized check.
  - `_exterior_person_sensors` lines 1955-1982 — resolver pattern that reads
    `CONF_PERIMETER_CAMERAS` + `CONF_EGRESS_CAMERAS` from live entries and
    probes `_person_occupancy_2` / `_person_occupancy` suffixes.
  - `_evaluate_sensor_health_dimension` lines 1984-2044 — the existing
    ROOM-keyed health evaluator. Keys `("sensor_health", room, eid)` with a
    60s sustain gate; emits `level="room"`, `target_id=room`.  Does NOT see
    sensors stuck at plausible values; this is the dimension the operator
    said we are "very likely extending".
  - `_filter_repeat_sensor_health` lines 3922-3977 — the volume suppressor
    (v5.101.1 B2) that collapses unchanged repeats to ~1/day/sensor via
    `_sensor_health_last_persisted` (line 608) + repersist interval
    `OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S` (const.py:4051).
    **Reusable as-is** for any new `SENSOR_HEALTH` dimension finding, because
    it keys on `(str(dedup_key), stuck_state)` — not on evaluator identity.
  - Dimension registration lines 934-935 — adding a new dimension entry is
    one list append.
- `custom_components/universal_room_automation/coordinator.py`:
  - `_sensor_on_since` (line 363), `_stuck_sensor_fired` (line 393),
    `_stuck_sensor_fired_date` (line 424) + daily rollover at line 2338-2341,
    `_stuck_store_key` + Store restore (lines 2235-2279), persist (lines
    2297-2363), `_emit_p22_stuck_sensor_for_tick` + dutycycle path
    (lines ~3071-3256). This is **room-scoped** P22: it keys to the room
    coordinator and runs per-room-tick, with HA Store persistence of
    `_sensor_on_since` across restarts and a per-day emission latch.
    **NOT the right surface to extend** — see verdict below.
- `custom_components/universal_room_automation/const.py`:
  - `OPTIMIZER_DIMENSION_SENSOR_HEALTH` (line 3956),
    `OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S` (line 4051),
    `CAMERA_STUCK_ON_THRESHOLD_S=1800` (line 4103),
    `CAMERA_STUCK_ON_OVERRIDES_S` (line 4117). The per-camera override map
    is the model for the proposed per-entity override map.
- `custom_components/universal_room_automation/sensor.py` lines 1751-1840 —
  `UnavailableEntitiesSensor` exposes `sensor.<room>_unavailable_entities`
  tracking INPUT sensors only (per CLAUDE.md troubleshooting note). Actuator
  unavailability is OUT OF SCOPE for v1 (card has four shapes; v1 = two).

### Prior-art scan — REUSE vs NEW per proposed piece

| Proposed piece | Verdict | Where |
|---|---|---|
| OC dimension host | **REUSE** — extend `OptimizationDimension.SENSOR_HEALTH` with two new evaluators `_evaluate_sensor_stuck_dimension` and `_evaluate_sensor_never_fires_dimension` | optimization.py:934-935 register site; dimension enum already exists |
| Row volume suppression (≤1/day/sensor) | **REUSE** `_filter_repeat_sensor_health` + `_sensor_health_last_persisted` | optimization.py:3922, line 608 |
| Dedup latch per (entity, episode) | **NEW** (`_sensor_stuck_fired: set[tuple[str,str]]`, `_sensor_on_since_oc: dict[str, datetime]`) — the room-level `_sensor_on_since` in coordinator.py:363 is per-room-coordinator and does not see OC's union of entities; reusing it across process boundaries would violate scope. The CAMERA-STUCK fields `_camera_on_since` / `_camera_stuck_fired` (optimization.py:602 and `_camera_on_since` pop at line 1911) are the direct template |
| Daily latch clear + local-midnight rollover | **REUSE PATTERN** from coordinator.py:2338-2341 (`_stuck_sensor_fired_date`), re-implemented locally in OC (same ≤10 lines) |
| HA Store restore of `_sensor_on_since` across restart | **DO NOT REUSE / SKIP for v1** — coordinator.py:2235-2363 justifies that persistence because missing it lets a sensor stuck for 29h disappear across a 1-min restart. In OC the equivalent would be a new Store key. v1 **does not persist**: on restart the clock resets; the first stuck finding re-fires after one new horizon. This is a conscious marginal-benefit decision (see Marginal-benefit note below). PICK B offers the Store variant if the operator wants restart-robust horizons. |
| Threshold constant(s) | **NEW**: `SENSOR_STUCK_ON_THRESHOLD_S` (default 43200 = 12h, measured below). Per-entity override map `SENSOR_STUCK_ON_OVERRIDES_S: dict[str,int]` modeled on `CAMERA_STUCK_ON_OVERRIDES_S` (const.py:4117). Kill-switch: 0 disables. |
| Never-fires horizon | **NEW**: `SENSOR_NEVER_FIRES_HORIZON_S` default 604800 (7d; matches AUDIT window). |
| Class scope | **REUSE** entity-registry `device_class` read; no new infra. Classes gated to `{motion, occupancy}` in v1 — the only two classes with a non-trivial expected-ON transition rate per the audit |
| Resolver (which entities to watch) | **REUSE** `_iter_room_entries` (used throughout optimization.py) for room inputs + `_exterior_person_sensors` (line 1955) for cameras. **NEW** small filter: exclude URA-aggregate occupancy sensors (any entity whose entity_id starts with `universal_room_automation_` or whose unique_id originates from this integration), per AUDIT caveat 2 |
| NM paging | **REUSE** existing optimizer NM allowlist path (`CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS` const.py:4133) — dimension is already `sensor_health`, so no new allowlist entry needed |
| Dashboard / sensor entity | **NONE in v1** — findings land in `anomaly_log` + `notification_log` same as `camera_stuck`; existing dashboards already show OC rows |

### Prior planning docs consulted
- `docs/planning/AUDIT_stuck_sensor_duration_distributions.md` — step-2
  measurements (THIS cycle's measure-before-build artifact). Table lines
  18-45; caveats 1 (unavailable must be a break) and 2 (filter URA
  aggregates) are load-bearing design constraints below.
- `docs/planning/PLANNING_mmwave_corroboration_tier3.md` lines 70, 175-186,
  306, 515-524 — D6 parked "dead/stuck mmwave in stuck-signal watchdog"
  with evidence trigger that has **fired** (2026-08-09 incident). D6 is
  subsumed by this plan: the generalized check covers stuck-ON mmwave
  (occupancy class) and the never-fires twin for a motion/occupancy sensor
  pinned OFF; the mmwave-dead case is already covered by
  `_evaluate_sensor_health_dimension` (unavailable path).
- v5.101.3 README + review record (`docs/reviews/code-review/`) —
  CAMERA-STUCK-SENSOR-TRIPWIRE-1 shipped as a separate evaluator rather
  than a threshold tweak, with per-key latch and measured threshold. Same
  structural template reused here.
- v5.75.0 stuck-sensor consequence README and v5.35.0 stuck-signal
  watchdog review record — the room-level P22 machinery (dutycycle +
  chatter paths in coordinator.py:2415+) addresses a different problem
  (per-room duty-cycle), confirming OC is the right host.

### Memory bodies pulled
- `feedback_measure_before_build.md` — step 2 (AUDIT) was the probe; this
  plan quotes its measured horizons and does not invent numbers.
- `feedback_marginal_benefit_pushback.md` — the simplest version (no Store
  persistence; motion+occupancy only; one default threshold + override map)
  captures the measured outliers; richer variants parked.
- `feedback_config_first_before_code.md` — N/A, no live knob existed for
  this (confirmed by grep: zero existing stuck-threshold Number/Select
  entities on the OC surface).
- `feedback_label_style_guide.md` — if any user-visible label is added,
  must be short and non-nerd ("sensor stuck on", not "stuck duration
  horizon excursion").

### Design docs read
- None required (OC does not have a dedicated manual; sensor_health is
  documented in-code).

---

## Extend-vs-new verdict

**EXTEND the Optimization Coordinator `SENSOR_HEALTH` dimension with two new
evaluators.** Reasons:

1. The card itself names OC as the host and says "likely an EXTENSION of that
   dimension keyed on entity_id, NOT a new coordinator".
2. The existing camera_stuck evaluator (optimization.py:1881) is the exact
   structural template and already lives in OC. The generalized check is
   that evaluator minus the camera-only resolver, plus a class gate and the
   never-fires twin.
3. The row-volume safety net (`_filter_repeat_sensor_health`,
   optimization.py:3922) already dedups any `SENSOR_HEALTH`-dimension finding
   to ~1/day/sensor — the v5.101.1 B2 flood protection the card calls out.
4. P22 room-level machinery is scoped to a RoomCoordinator (`self` in
   coordinator.py:363) and runs per room tick for duty-cycle chatter. Lifting
   it to a cross-room, entity-keyed role would double its purpose and
   duplicate storage + daily rollover; worse, two latches on the same sensor.
5. CAMERA-STUCK-SENSOR-TRIPWIRE-1 is explicitly linked to fold into this
   card when built.

Rejected alternatives: (a) new coordinator — overkill, no new persistence or
scheduling needed; (b) extend room-level P22 — wrong scope (card says "keyed
to the SENSOR, not the room"); (c) threshold tweak to sensor_health —
sensor_health only sees `unavailable`/`unknown`, cannot see stuck at a
plausible value.

---

## Deliverables (v1 scope: stuck-ON + never-fires, classes motion + occupancy)

### D1 — Resolver: cross-config enumeration of watched raw-device sensors

Build `_watched_raw_sensors(self) -> dict[str, dict]` returning a map
`entity_id -> {device_class, source: "room_input"|"perimeter_camera"|"egress_camera", room: Optional[str], class_expected_fires_per_day: Optional[int]}`.

- Enumerates room inputs via `_iter_room_entries` reading
  `CONF_OCCUPANCY_SENSORS`, `CONF_MOTION_SENSORS`, `CONF_MMWAVE_SENSORS`
  (same keys sensor_health uses, optimization.py:1992-1994).
- Enumerates perimeter + egress person-detectors via
  `_exterior_person_sensors` (line 1955).
- Reads `device_class` from the entity registry; keeps classes
  `{"motion","occupancy"}` only in v1.
- **Filters out URA-aggregate occupancy sensors** by unique_id prefix /
  entity_id prefix `universal_room_automation_` or any entity owned by the
  URA config entries (AUDIT caveat 2).
- Deduplicates when the same entity is referenced by multiple rooms
  (keeps first room, logs collision at debug).

#### Acceptance Criteria
- **Verify:** given a test config with 3 motion sensors in Room A, 1
  occupancy in Room B, and `anyone_home` present as an aggregate, the
  resolver returns 4 entries and does NOT include `anyone_home`.
- **Verify:** `pool_equipment_person_occupancy_2` from the perimeter list
  resolves with `source="perimeter_camera"`.
- **Test:** `test_watched_raw_sensors_filters_ura_aggregates`,
  `test_watched_raw_sensors_resolves_perimeter_cameras`,
  `test_watched_raw_sensors_dedups_cross_room_entity`.
- **Live:** on first OC tick after restart, debug log emits
  `watched_raw_sensors n=<N>` with N ≈ (motion sensors + occupancy sensors
  + perimeter cameras + egress cameras) from live config; no URA-aggregate
  entity_ids appear in the list.

### D2 — Evaluator: `_evaluate_sensor_stuck_dimension` (stuck-ON)

Mirrors `_evaluate_camera_stuck_dimension` (optimization.py:1881) over
D1's resolver.

- Per-entity on-since tracker `_sensor_stuck_on_since: dict[str, datetime]`.
- Per-entity episode latch `_sensor_stuck_fired: set[str]`; cleared the
  moment the sensor transitions to OFF *or* to unavailable/unknown.
- **Unavailable is a break** (AUDIT caveat 1): on `unavailable`/`unknown`
  state, pop `_sensor_stuck_on_since[eid]` and `_sensor_stuck_fired.discard`.
  This means a 60h offline gap cannot be counted as 60h stuck-ON.
- Threshold: `SENSOR_STUCK_ON_OVERRIDES_S.get(eid, SENSOR_STUCK_ON_THRESHOLD_S)`.
- Horizon kill-switch: `SENSOR_STUCK_ON_THRESHOLD_S == 0` disables (returns `[]`).
- Emits `OptimizationFinding(dimension=SENSOR_HEALTH, severity="high",
  level="house", target_id=eid, dedup_key=("sensor_stuck", eid), payload={entity_id, device_class, stuck_seconds, threshold_s, source, room})`.
- Daily latch rollover: `_sensor_stuck_fired_date` + reset at local
  midnight, same shape as coordinator.py:2338-2341.

#### Acceptance Criteria
- **Verify:** a motion sensor held ON for `threshold_s + 1` with no
  intervening transitions produces exactly ONE finding, dedup_key
  `("sensor_stuck", "<eid>")`.
- **Verify:** the same sensor then going OFF, then stuck ON again across
  midnight, produces a second finding (latch cleared on OFF).
- **Verify:** an unavailable gap of 10h followed by ON of 4h does NOT fire
  (clock reset by unavailable break).
- **Verify:** the aggregate `_filter_repeat_sensor_health` suppresses a
  second row for the same entity within
  `OPTIMIZER_SENSOR_HEALTH_REPERSIST_INTERVAL_S` (24h) — no row-flood
  regression vs v5.101.1 B2.
- **Test:** `test_sensor_stuck_on_fires_once_per_episode`,
  `test_sensor_stuck_unavailable_is_a_break`,
  `test_sensor_stuck_daily_latch_rollover`,
  `test_sensor_stuck_respects_per_entity_override`,
  `test_sensor_stuck_zero_threshold_is_kill_switch`,
  `test_sensor_stuck_respects_sensor_health_repersist`.
- **Live:** post-deploy within 24h, `anomaly_log` contains at most one row
  per `(camera_key or room, entity_id)` from `sensor_stuck`; row count on
  the first day ≤ `(known stuck sensors) + ε`. (On the measured dataset:
  `pool_equipment_motion_3`, `madroneptultra_motion`,
  `reolinkstudybporchptz_motion_2` are the plausible first-24h hits if they
  reproduce.)
- **Live:** `notification_log` carries ≤ (dimension's NM allowlist decision)
  rows per entity per day; no sensor emits >1 row/day without a legitimate
  recovery+re-stick cycle.

### D3 — Evaluator: `_evaluate_sensor_never_fires_dimension`

For every D1 entity in classes `{motion, occupancy}`, if the entity has
produced ZERO ON transitions in the last `SENSOR_NEVER_FIRES_HORIZON_S`
(default 7d) AND the sensor is "class-expected to fire" (see per-class
expectation), emit one HIGH finding per sensor per day.

- "ON transitions in the last 7d" is read from the HA recorder via
  `recorder.history.state_changes_during_period` for the entity, filtering
  to on-state transitions. One-shot per OC tick, cached with a
  `_never_fires_last_check: dict[str, datetime]` so this is at most ONE
  recorder read per entity per 1h (knob below).
- Per-class expectation (v1): motion AND occupancy classes in a room that
  has had ANY ON transition on any OTHER raw sensor in the last 7d — this
  gates "class-expected" without needing a per-sensor baseline. For
  perimeter/egress cameras, the gate is "the camera's device is
  available" (not `unavailable`).
- `_sensor_never_fires_fired: set[str]` latch + daily rollover + same
  `_filter_repeat_sensor_health` volume cover.
- `dedup_key=("sensor_never_fires", eid)`.
- Horizon kill-switch: `SENSOR_NEVER_FIRES_HORIZON_S == 0` disables.

#### Acceptance Criteria
- **Verify:** three exterior detectors (CAMERA-ZERO-FIRE-DETECTORS-1 case)
  with zero ON transitions in 7d produce three findings.
- **Verify:** a door-sensor (device_class `door`) with zero transitions is
  NOT emitted (out-of-scope class in v1).
- **Verify:** a motion sensor in an unoccupied test fixture (no other
  room sensor fired in 7d either) is NOT emitted (class-expected gate).
- **Test:** `test_never_fires_fires_on_zero_transitions_in_horizon`,
  `test_never_fires_gated_by_class_scope`,
  `test_never_fires_gated_by_room_activity`,
  `test_never_fires_once_per_day_latch`,
  `test_never_fires_recorder_cache_ttl`.
- **Live:** within 24h of deploy, `anomaly_log` carries one row per silent
  exterior detector from CAMERA-ZERO-FIRE-DETECTORS-1; absent rows for any
  sensor that is actively firing.

### D4 — Register the two evaluators + dedup fields

- Append entries to the dimension list at optimization.py:934-935:
  `("sensor_stuck", self._evaluate_sensor_stuck_dimension)` and
  `("sensor_never_fires", self._evaluate_sensor_never_fires_dimension)`.
- Add instance fields in `__init__` near line 602:
  `self._sensor_stuck_on_since: dict[str, datetime] = {}`,
  `self._sensor_stuck_fired: set[str] = set()`,
  `self._sensor_never_fires_fired: set[str] = set()`,
  `self._sensor_stuck_fired_date: str | None = None`,
  `self._never_fires_last_check: dict[str, datetime] = {}`.

#### Acceptance Criteria
- **Verify:** OC tick after restart runs both evaluators once per cycle;
  debug log shows per-evaluator timing.
- **Test:** `test_dimension_registration_includes_sensor_stuck_and_never_fires`.

### D5 — Constants + overrides (knob ladder)

Add to `const.py` near line 4103 (next to `CAMERA_STUCK_ON_THRESHOLD_S`):

- `SENSOR_STUCK_ON_THRESHOLD_S: Final = 43200`  # 12h.
- `SENSOR_STUCK_ON_OVERRIDES_S: Final[dict[str, int]] = {}`  # per-entity
  overrides, same pattern as `CAMERA_STUCK_ON_OVERRIDES_S`.
- `SENSOR_NEVER_FIRES_HORIZON_S: Final = 604800`  # 7d.
- `SENSOR_NEVER_FIRES_RECORDER_CACHE_TTL_S: Final = 3600`  # 1h; bounds
  recorder reads to 1 per entity per hour.

### D6 — Tests + live validation table in README

Standard. Live validation table (added to README post-restart per CLAUDE.md
mandate) must contain rows for each acceptance criterion with observed
evidence (entity_id, `anomaly_log` row timestamp, `notification_log` row
timestamp, verified entity count).

---

## Numbers Get Knobs — placement ladder

| Number | Default | Rung | Why |
|---|---|---|---|
| `SENSOR_STUCK_ON_THRESHOLD_S` | 43200 (12h) | **Module constant** (const.py) | Measured from AUDIT: motion p90=9.7h, max 26.1h; occupancy raw p90=3.2h, max 26.6h. 12h is above p90 and catches the three measured outliers (26.1 / 21.9 / 21.2h) with margin, without false-firing on the long-dwell tail. Changing it should require review because it is derived from a fitted distribution (same reasoning as `CAMERA_STUCK_ON_THRESHOLD_S` at const.py:4103). 0 disables (kill-switch). |
| `SENSOR_STUCK_ON_OVERRIDES_S` | `{}` | **Module constant** (const.py) | Mirrors `CAMERA_STUCK_ON_OVERRIDES_S` (const.py:4117). An override is a reviewed, named exemption; not something an operator should flip at 2am. |
| `SENSOR_NEVER_FIRES_HORIZON_S` | 604800 (7d) | **Module constant** (const.py) | Matches the AUDIT measurement window; a shorter window increases false positives on legitimately dormant sensors (opening/safety classes already excluded). |
| `SENSOR_NEVER_FIRES_RECORDER_CACHE_TTL_S` | 3600 (1h) | **Module constant** (const.py) | Caps recorder read rate per entity; not a user-tunable comfort knob. |

No new config-flow fields, no new Number entities. If live data proves the
operator legitimately wants to tune `SENSOR_STUCK_ON_THRESHOLD_S` by
observation, promote to a Number entity in a follow-up cycle — do not
pre-build the rung.

---

## Suppression / discharge story (per "suppression needs a discharge" rule)

Each suppression here is paired with its discharge, backstop, and
restart story:

| Suppression | Discharge (re-fires when) | Backstop | Restart behaviour |
|---|---|---|---|
| `_sensor_stuck_fired[eid]` (per-episode latch) | sensor transitions to OFF, or to unavailable/unknown | daily latch clear at local midnight via `_sensor_stuck_fired_date` | fresh set on restart; episode re-starts tracking `_sensor_stuck_on_since` from live state; a sensor that was stuck across restart will re-fire after one new horizon (acceptable per marginal-benefit decision; PICK B persists). |
| `_sensor_never_fires_fired[eid]` | the sensor emits any ON transition in `_never_fires_last_check` window | daily latch clear at local midnight | fresh set on restart; first OC tick after restart re-reads 7d of recorder; the finding re-emits if the condition still holds. |
| `_filter_repeat_sensor_health` (24h per-row suppressor, optimization.py:3922) | 24h elapsed from last persist, OR evaluator recovery clears entry (optimization.py:2033-2043) | 24h is the backstop itself | `_sensor_health_last_persisted` is in-memory; on restart the next finding persists immediately (desired). |
| `_never_fires_last_check[eid]` (recorder-read TTL) | 1h since last read for that entity | — | fresh dict on restart; first tick reads 7d once per entity. |

NM volume bound: with 128 motion + 382 occupancy entities in the audit
window, filtered to raw-device sensors (motion ~128, occupancy ~raw subset
of 382 minus ~a dozen URA aggregates), and the per-day per-entity
suppressor, **worst-case upper bound is on the order of 500 rows/day
system-wide**, but in a steady state (nothing stuck, everything firing)
expected row rate is **0/day**. The three audit-identified outliers set the
realistic bound at **3-6 rows/day until the underlying devices are fixed**.
This is at least 1000x below the pre-B2 row flood sensor_health used to
produce.

---

## Producer + Consumer check

### Producer (how the stuck signal is computed)
- Entry: HA state registry via `self._state_value(eid)` (existing OC
  helper) — same arithmetic as `_evaluate_camera_stuck_dimension`
  (optimization.py:1908-1927).
- Multiple derivations: ONE path per shape (stuck-ON = live state
  tracker; never-fires = recorder history read). No alternative derivations
  competing.
- Dependency health: depends on (a) HA entity-registry `device_class` for
  the class gate; (b) recorder availability for the never-fires evaluator;
  (c) a correctly-populated live config list for cameras.
- Ground-truth cross-check: the AUDIT measurements (sibling-file
  `AUDIT_stuck_sensor_duration_distributions.md`) establish the measured
  outliers; live validation checks these specific entity_ids first.

### Consumers (who reads it, trust vs display)
- `anomaly_log` DB table (via existing OC persistence) — DISPLAY (operator
  reviews after the fact).
- `notification_log` DB table + NM paging via the optimizer HIGH allowlist
  path (`CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS` at const.py:4133).
  If `sensor_health` is in the allowlist, these HIGH findings page; if not,
  they land in the daily digest via `_build_optimizer_digest_section`. Both
  are DISPLAY, not trust-based decisions — no coordinator consumes the
  finding to change behaviour.
- No cross-coordinator trust consumer in v1. (Future: feed into
  SignalTrustLedger when it ships; not this cycle.)

### Discriminating acceptance observation
A failure that would look identical to success under naive counting
("rows exist") must be ruled out. The AUDIT's false-60h ON cluster
(unavailable mis-counted as ON) is the exact adversarial case. The live
validation table MUST include a row per acceptance criterion AND must
include one row proving "no finding fired against a sensor whose only
on-duration was an unavailable gap" — verified by `anomaly_log` payload
`stuck_seconds` field vs recorder `unavailable` segments for the same
entity in the same window.

---

## Non-goals (v1)

- NO numeric-value stuck detection ("temperature frozen at 72.3F for 48h"),
  which the card lists as shape 3. Deferred — needs a different horizon
  model (variance over a window, not duration-of-same-state).
- NO actuator-unavailability detection (shape 4). The
  `sensor.<room>_unavailable_entities` sensor at sensor.py:1751 covers
  input sensors; actuators are tracked by the BACKLOG gap in CLAUDE.md
  troubleshooting and deserve a dedicated card.
- NO new coordinator, no new DB table, no new DAO.
- NO new config-flow fields, no new Number/Select entities.
- NO Store persistence of `_sensor_stuck_on_since` across restart (see
  PICK B).
- NO quarantine arm (shadow or active). Finding-only, no action.
- NO expansion beyond classes `{motion, occupancy}` in v1. `connectivity`,
  `power`, `door`, `opening` all have legitimate long-stable states (see
  AUDIT table) and need per-class reasoning to produce useful findings.
- CAMERA-STUCK-SENSOR-TRIPWIRE-1 (`_evaluate_camera_stuck_dimension`) stays
  as-is for one release, then folds into this evaluator in a follow-up
  cleanup once the generalized check is proven live. Removing it in the
  same cycle doubles the regression surface for no gain.

---

## Open operator decisions

- **PICK A:** Universal 12h threshold for both motion and occupancy, per
  the AUDIT. (RECOMMENDED — simplest, catches the three measured
  outliers, zero knobs to tune.)
  **PICK B:** Per-class defaults (motion=12h, occupancy=24h) because
  occupancy includes mmwave and bed-presence patterns that legitimately
  run longer. Adds one constant and one dict read.

- **PICK A:** No Store persistence of `_sensor_stuck_on_since` across OC
  restart. A sensor stuck across restart re-fires after one fresh horizon
  (worst-case extra 12h delay). (RECOMMENDED — simplest; OC restart is
  rare and the delay cost is bounded.)
  **PICK B:** Add Store persistence mirroring coordinator.py:2235-2363.
  ~80 LoC, one more Store key, one more test surface.

- **PICK A:** Keep CAMERA-STUCK-SENSOR-TRIPWIRE-1 evaluator in place for
  one release; schedule removal in a follow-up card. (RECOMMENDED — avoids
  regression surface in this cycle.)
  **PICK B:** Remove `_evaluate_camera_stuck_dimension` in-cycle;
  perimeter + egress cameras flow through `_evaluate_sensor_stuck_dimension`
  from day one. Adds a camera-key-vs-entity_id dedup migration risk.

- **PICK A:** v1 scope = classes `{motion, occupancy}` only.
  (RECOMMENDED — matches the card's "v1 shapes = stuck-ON and never-fires"
  and the only two classes with non-trivial expected-ON rates.)
  **PICK B:** Add `door` + `opening` never-fires for occupied rooms. Needs
  a per-room "expected transitions per day" baseline we do not have.

- **PICK A:** Never-fires horizon = 7d.
  **PICK B:** 72h — faster alert, more false-positives on legitimately
  dormant exterior detectors on quiet nights.

---

## Deliverable list (summary)
1. D1 Resolver `_watched_raw_sensors`
2. D2 `_evaluate_sensor_stuck_dimension`
3. D3 `_evaluate_sensor_never_fires_dimension`
4. D4 Dimension registration + instance fields
5. D5 Constants + override map
6. D6 Tests + live validation table in README

Recommended tier: **Tier 2** (two framing-disjoint reviews — A: correctness
+ edge cases incl. unavailable-is-a-break; B: lifecycle + restart + volume
cap + recorder read bound — plus Live Validation and a README validation
table).

---

# Revision 2 — SUPERSEDES Rev 1 (2026-10-10)

**Supersedes which Rev 1 sections:** Extend-vs-new verdict; D2 (dropped);
D3 producer design (switched to in-memory with persisted last-ON timestamp,
not recorder); Knob ladder (removed SENSOR_STUCK_ON_* entries, added
availability + persistence knobs); Suppression/discharge table (new row for
`_sensor_never_fires_fired` discharge via local pop); Open PICKs (Picks 1,
2, 3 moot/retired); Deliverable list (D1 scoped, D2 dropped, D3 kept, D4
registers one evaluator, D5 knob list changed, D6 unchanged).

**Rev 1 text above is retained for history.** Where Rev 1 and Rev 2
disagree, Rev 2 wins. Line references below re-verified against develop
`49b20bdfb` on 2026-10-10 (optimization.py: evaluator tuple at 966,
`_evaluate_camera_stuck_dimension` at 1921, `_exterior_person_sensors` at
2182-ish, `_evaluate_sensor_health_dimension` recovery clear at 2259-2270
clearing only `("sensor_health", room, eid)` keys, `_filter_repeat_sensor_health`
at 4149). Rev 1 line numbers are historical artefacts and should be read
as "the same symbol one or two hundred lines up or down".

## Rev 2 — Parsimony verdict: SIMPLIFY

Plan reviewer flagged D2 as a duplicate of the room-level P22 continuous
stuck detector plus the OC `camera_stuck` evaluator plus the camera_census
`get_stuck_cameras` list — three detectors already covering the same
physical sensors. Operator parsimony verdict: **SIMPLIFY**.

**Drop D2 entirely.** The room-level P22 check in coordinator.py:1824 /
2208-2234 / 3065-3072 stays the single stuck-ON detector for room sensors
(motion / mmwave / occupancy). OC `_evaluate_camera_stuck_dimension`
(optimization.py:1921) stays the stuck-ON detector for perimeter + egress
cameras. We do **NOT** add an OC "mirror" evaluator over
`get_stuck_sensor_kinds()`. The operator-visible surface gap that would
justify a mirror has not been demonstrated: both P22 and camera_stuck
already feed `sensor.ura_stuck_signal_watchdog` (sensor.py:5323-5351) and
NM. A mirror would add a second notification path for the same event.

Default: no mirror. Revival trigger: a specific operator-visible stuck
sensor that P22 and `camera_stuck` BOTH miss, cited with
file:line + the observation it was missed (not a theoretical gap).

## Rev 2 — Extend-vs-new verdict (replaces Rev 1 section)

**EXTEND the OC `SENSOR_HEALTH` dimension with ONE new evaluator:
`_evaluate_sensor_never_fires_dimension` (D3).** Reasons:

1. Stuck-ON for room sensors is already covered by room P22
   (coordinator.py:364 `_stuck_sensor_hours=4.0`, 2208-2234 producer, 3065-3072
   per-tick path, 2235-2363 Store persistence, 2338-2341 daily rollover,
   2861-2866 `_is_sensor_on` treats unavailable/unknown as off → unavailable
   already acts as a break).
2. Stuck-ON for exterior cameras is already covered by OC
   `_evaluate_camera_stuck_dimension` (optimization.py:1921) + camera_census
   `get_stuck_cameras` (camera_census.py:2945).
3. The ONLY shape with no existing detector is **class-expected sensors
   that have produced ZERO ON transitions over a long horizon** — the
   CAMERA-ZERO-FIRE-DETECTORS-1 case. That is D3.
4. The row-volume safety net `_filter_repeat_sensor_health`
   (optimization.py:4149) is still reused for D3 at ≤1 row/entity/day.

Rejected alternatives: (a) OC mirror over `get_stuck_sensor_kinds()` —
creates a second notification for the same event, no operator-visible gap
cited; (b) room-level never-fires via P22 — P22 is scoped to a
RoomCoordinator and only sees entities configured for THAT room, so it
cannot see exterior cameras as room inputs, and it carries no
7-day-horizon machinery.

## Rev 2 — Falsifiable invariant (narrowed)

**"For every raw device sensor URA is configured to consume in classes
{motion, occupancy}, a class-expected sensor that produces zero ON
transitions over `SENSOR_NEVER_FIRES_HORIZON_S` AND has been available for
at least `SENSOR_NEVER_FIRES_MIN_AVAILABILITY_FRACTION` of that window
produces at most ONE `sensor_never_fires` finding per sensor per local
day."** AND **"For any single stuck-ON sensor, the total count of NM
notifications per local day across P22 + camera_stuck + the new OC
evaluator is at most 1."** The second clause is the no-double-surface
check: because we are shipping D3 only, this reduces to "D3 does not emit
`sensor_stuck`, and never-fires does not fire for an entity that P22 or
camera_stuck already flagged in the same day" (trivially true — different
dedup keys and different conditions, codified in test).

Reviewer D's break list: unavailable gaps masquerading as "no ON
transitions" (H2); URA-aggregate occupancy sensors leaking into the
never-fires list (M1); re-silence within 24h of recovery not persisting a
new row (M2); local-midnight DST fall-back / spring-forward double-fire
(M4); horizon kill-switch (0) actually disabling.

## Rev 2 — Deliverables (final list)

- **D1 (scoped):** `_watched_raw_sensors` resolver — unchanged in intent;
  URA-aggregate filter uses the entity registry
  (`er.async_get(hass).async_get(eid).platform == DOMAIN`), NOT the
  `universal_room_automation_` entity_id prefix (per M1). No registry
  entry → include + log at debug. Realistic test: a room whose
  `CONF_OCCUPANCY_SENSORS` contains a URA zone/room occupancy
  binary_sensor (platform == DOMAIN) — the filter MUST drop it.
- **D2 — DROPPED.** See parked list below.
- **D3:** `_evaluate_sensor_never_fires_dimension` — kept; producer
  switched to in-memory per Rev 2 H1; availability gate added per Rev 2
  H2; local discharge pop added per Rev 2 M2; DST test named per Rev 2 M4.
- **D4:** Register ONE evaluator in the tuple at optimization.py:966 —
  `("sensor_never_fires", self._evaluate_sensor_never_fires_dimension)`.
  Instance fields: `_sensor_last_on_seen: dict[str, datetime]`,
  `_sensor_never_fires_fired: set[str]`,
  `_sensor_never_fires_fired_date: str | None`,
  `_sensor_available_since: dict[str, datetime]`.
  Acceptance (replaces Rev 1 D4 timing-log check): assert the evaluator
  returns a `list[OptimizationFinding]` whose length equals the number of
  class-expected silent sensors in the fixture (**per-evaluator output
  count**, not a timing log — per LOW L3).
- **D5 (knob list changed):** see Rev 2 knob table below. Rev 1's
  `SENSOR_STUCK_ON_THRESHOLD_S`, `SENSOR_STUCK_ON_OVERRIDES_S` are
  **removed** (D2 dropped).
- **D6:** unchanged — tests + README live-validation table.

### D3 — Rev 2 producer design (in-memory, with persisted last-ON)

Rev 1 planned a recorder read per entity each tick. Operator decision
(H1): **prefer in-memory**. Track `last_on_seen[eid]` from LIVE
state-change events (`async_track_state_change_event` on the resolved D1
list) and from the OC tick read of `hass.states.get(eid)`; start the
horizon clock at OC start-of-tracking time.

- No recorder reads in v1.
- No `hass.data[recorder]` dependency; no executor jobs.
- Fire only when `now - max(oc_tracking_start, last_on_seen[eid]) ≥
  SENSOR_NEVER_FIRES_HORIZON_S` AND the availability gate (H2) holds.

**Honest restart-cadence trade (operator-mandated):**

The pure in-memory PICK 2A design means the horizon clock resets on every
restart (reload, HA restart, URA integration reload). For a 7-day horizon
to fire, URA must be up continuously for ≥ 7 days. Prior-art memory
indicates URA restarts/reloads at a cadence that frequently exceeds daily
in incident periods (reload-storm investigations across the v5.100 arc,
v5.5.3 Tier-3 arc, routine develop deploys, Config-entry reload after
options-flow edits). Typical steady-state uptime between reloads: on the
order of **1-3 days**, not 7. Pure PICK 2A therefore makes D3 effectively
dormant most of the time — the horizon is almost never reached.

**Recommendation (operator pick required):** a **lightweight persisted
last-ON timestamp** per entity, as the better trade. Specifically:

- Persist a single HA Store blob at key
  `optimization.sensor_never_fires_last_on_seen` — one dict
  `{entity_id: last_on_seen_iso}`, debounced to **at most one write per
  entity per hour**, flushed on `homeassistant.async_stop`.
- On OC setup: restore the dict; horizon clock = `max(restored_last_on,
  oc_tracking_start_for_entity)`. If the restored timestamp is older than
  the horizon on first tick after restart, the evaluator fires once (which
  is desired — the entity really has been silent).
- Size: 500 entities × ~80 B each ≈ 40 KB blob. Precedent:
  coordinator.py:2235-2279 `_stuck_store_key` is the same pattern for the
  room-level stuck tracker.
- LoC: ~40 (one Store key, one restore in `async_added_to_hass`, one
  debounced write on state-change-to-on, one dict probe in evaluator).
- Review impact: Tier 2 unchanged (no shared primitive touched).

**Alternative if operator rejects persistence (pure PICK 2A kept):**
also knob the horizon down to **48h or 72h** (`SENSOR_NEVER_FIRES_HORIZON_S
= 172800 or 259200`) so the horizon is reachable within one typical
uptime. Trade: more false-positives for exterior detectors on genuinely
quiet nights, and the recommended value becomes a policy call rather than
a measured one (the AUDIT measured 7d).

**My recommendation:** persist. The 40 LoC pays for the measured
7d horizon surviving the real restart cadence. State the consequence
honestly: without persistence AND without a shorter horizon, D3 ships
dormant.

### D3 — Rev 2 availability gate (H2)

Never-fires fires only when:

1. The entity's current state is NOT in `{unavailable, unknown}`.
2. The entity has been available for at least
   `SENSOR_NEVER_FIRES_MIN_AVAILABILITY_FRACTION` (default **0.8** = 80%)
   of the horizon window. Tracked via a simple `_sensor_available_since`
   dict updated on state-change: when the sensor transitions out of
   unavailable/unknown, we stamp `now`; when it transitions INTO
   unavailable/unknown, we subtract `(now - last_available_stamp)` from an
   accrued-available-seconds counter. On evaluator tick, require
   `accrued_available_s ≥ fraction * horizon_s`.

Unavailable is sensor_health's job (optimization.py `_evaluate_sensor_health_dimension`
~2200), not never-fires. Repro that this gate now blocks: a room mmwave
unavailable for 8 days produces one `sensor_health` unavailable finding
and ZERO `sensor_never_fires` findings for the same eid.

Test: `test_never_fires_blocked_by_unavailability_mostly_offline`.

### D3 — Rev 2 M1 (resolver): entity-registry platform match

The URA-aggregate filter MUST use
`er.async_get(hass).async_get(eid)` and check `entry.platform == DOMAIN`.
Entity-id prefix match (`universal_room_automation_*`) is wrong — URA
sensors do not uniformly carry that id prefix. Realistic test case:
construct a room whose `CONF_OCCUPANCY_SENSORS` contains a URA
zone-anyone binary_sensor (platform == DOMAIN); assert D1 drops it. No
registry entry → include with a `WARN` log (so stray external sensors are
still watched, not silently skipped).

Tests: `test_watched_raw_sensors_filters_ura_platform_entity`,
`test_watched_raw_sensors_includes_unregistered_with_warn`.

### D3 — Rev 2 M2 (discharge for the new key)

optimization.py:2259-2270 (verified in Rev 2 re-read against develop) only
clears `_sensor_health_last_persisted` entries whose stringified
dedup_key begins with `("sensor_health", room, eid)` — the recovery
branch of `_evaluate_sensor_health_dimension`. The new
`("sensor_never_fires", eid)` key is **NOT** cleared by that recovery
path, so a re-silence within 24h of recovery would fire the finding (good)
but `_filter_repeat_sensor_health` would suppress the DB row (bad —
anomaly_log would miss it; NM would still fire; the two outputs
disagree).

**Fix location (local to D3, does NOT edit the shared helper):** inside
`_evaluate_sensor_never_fires_dimension`, when we observe the discharge
condition (any ON transition in the horizon → we remove the eid from
`_sensor_never_fires_fired`), also pop every
`_sensor_health_last_persisted` key whose first tuple element stringifies
to `("sensor_never_fires", eid)` — same ≤5-line idiom as the sensor_health
recovery branch at 2265-2270, just targeted at the new key. This keeps
the fix local to D3 and leaves `_filter_repeat_sensor_health` untouched
→ **Tier 2 stays correct, NOT elevated to Tier 2-DB.**

(If a reviewer argues the discharge belongs INSIDE
`_filter_repeat_sensor_health` for symmetry with sensor_health recovery,
that would elevate to Tier 2-DB — explicitly flagged as the elevation
trigger.)

Test: `test_never_fires_resilence_within_24h_persists_a_row`.

### D3 — Rev 2 M4 (invariant form + DST test)

Invariant (narrowed): **"at most one `sensor_never_fires` finding per
sensor per local day."** Daily latch clears at local midnight via
`_sensor_never_fires_fired_date`. The 30h-episode double-fire concern from
Rev 1 does not apply to D3 (there is no "episode" for never-fires; the
condition is a flat threshold crossing).

DST test (named): `test_never_fires_daily_latch_dst_fall_back_does_not_double_fire`
— fixture ticks the clock across the 2026-11-01 02:00 → 01:00 fall-back in
America/Chicago; the evaluator must NOT emit a second finding for the
same eid in the two overlapping 01:00 hours. Companion spring-forward test
is nice-to-have, not required for v1 (fall-back is the double-count
hazard; spring-forward collapses time rather than duplicating it).

## Rev 2 — Knob ladder (replaces Rev 1 table)

| Number | Default | Rung | Why |
|---|---|---|---|
| `SENSOR_NEVER_FIRES_HORIZON_S` | 604800 (7d) | **Module constant** (const.py, near line 4103) | Matches the AUDIT measurement window. 0 disables (kill-switch). Only a reviewed change should alter it; a shorter window raises false-positives on legitimately dormant exterior detectors. |
| `SENSOR_NEVER_FIRES_MIN_AVAILABILITY_FRACTION` | 0.8 | **Module constant** (const.py) | H2 gate. 0.8 means "available for at least 80% of the horizon". Below this, the sensor's silence is sensor_health's problem, not never-fires'. |
| `SENSOR_NEVER_FIRES_PERSIST_DEBOUNCE_S` | 3600 (1h) | **Module constant** (const.py) | Debounces Store writes for the persisted-last-ON blob to ≤1 write/entity/hour. Only present if operator picks the persisted-last-ON option. |

Rev 1's `SENSOR_STUCK_ON_THRESHOLD_S`, `SENSOR_STUCK_ON_OVERRIDES_S`, and
`SENSOR_NEVER_FIRES_RECORDER_CACHE_TTL_S` are all **removed**: the first
two with D2; the third because the recorder is no longer called.

Bug Class #63 (coincidental-equality / dual-threshold smell) is dissolved
by this simplification: there is now ONE stuck-ON threshold in URA
(coordinator.py:364 `_stuck_sensor_hours = 4.0`), not two.

## Rev 2 — Suppression / discharge story (replaces Rev 1 table)

| Suppression | Discharge (re-fires when) | Backstop | Restart behaviour |
|---|---|---|---|
| `_sensor_never_fires_fired[eid]` | the entity emits any ON transition observed by the OC listener (pops the eid from the latch AND pops the matching `_sensor_health_last_persisted` key per M2) | daily latch clear at local midnight via `_sensor_never_fires_fired_date` | fresh set on restart; first tick after restart re-fires if the restored `last_on_seen` is older than the horizon. |
| `_filter_repeat_sensor_health` (24h per-row suppressor, optimization.py:4149) | 24h elapsed from last persist; OR evaluator-local pop on recovery per M2 | 24h backstop | `_sensor_health_last_persisted` is in-memory; on restart the next finding persists immediately. |
| `_sensor_last_on_seen[eid]` (horizon clock) | state-change-to-on for the entity (immediate) | — | restored from Store (if operator picks persisted-last-ON) OR reset to OC start (if operator picks pure in-memory + short horizon). |
| `_sensor_available_since[eid]` + accrued-available counter (H2) | state-change into unavailable/unknown decrements accrual; state-change back out resets stamp | — | reset at restart; first horizon window after restart will not satisfy the 0.8-availability gate for its first few days — this is a conscious cost of in-memory, and part of why persisting last_on_seen is recommended. |

## Rev 2 — Non-goals (adjusted)

Add to Rev 1 non-goals:
- NO OC stuck-ON mirror (no `_evaluate_sensor_stuck_dimension`).
- NO recorder reads from OC in v1.
- NO edit to `_filter_repeat_sensor_health` (keeps cycle Tier 2, not
  Tier 2-DB).

Remove from Rev 1 non-goals:
- The clause about "CAMERA-STUCK-SENSOR-TRIPWIRE-1 folds into this
  evaluator in a follow-up cleanup" — the fold is now permanently
  cancelled; `_evaluate_camera_stuck_dimension` is the production path.

## Rev 2 — Open operator decisions

Retired as moot: Rev 1 Pick 1 (threshold choice), Pick 2 (Store
persistence of `_sensor_stuck_on_since`), Pick 3 (keep or fold
`camera_stuck`). All three were about D2, which is dropped.

**Open Pick (NEW, operator decision required):**

- **PICK A (RECOMMENDED):** Persist a lightweight
  `last_on_seen[eid]` dict via HA Store (one Store key, ~40 KB blob, ~1
  write/entity/hour debounce, restored at setup). D3 fires at 7d horizon
  across restarts; typical URA uptime (1-3 days) does not matter.
  **PICK B:** Pure in-memory PICK 2A as literally stated by the operator
  directive. Also knob horizon down to **72h** so the horizon is
  reachable within one typical uptime. D3 is louder and policy-based
  rather than measurement-based.
  **Why PICK A:** the Rev 1 producer explicitly cited the AUDIT 7d
  horizon; dropping to 72h to accommodate restart cadence is a policy
  concession when ~40 LoC of Store persistence preserves the measured
  horizon. The restart-storm memory (2026-09-10 reload storm; v5.100 arc)
  argues the cadence problem is real and not reliably fixable upstream.

- Rev 1 Pick 4 (class scope = `{motion, occupancy}`) — **UNCHANGED,
  PICK A stands.** Raw devices only.
- Rev 1 Pick 5 (never-fires horizon = 7d) — **UNCHANGED, PICK A stands**
  IF Pick-A (persist) is chosen; otherwise horizon drops to 72h under
  Pick-B.

## Rev 2 — Tier (unchanged, but owners re-scoped)

**Tier 2** (two framing-disjoint reviews + Live Validation).

- **Reviewer A — Correctness + edge cases:** D1 resolver filter via entity
  registry, class gate, availability-fraction accounting (H2),
  daily-latch DST fall-back, discharge pop (M2) correctly stringifies the
  dedup key, kill-switch (horizon=0) actually returns `[]`.
- **Reviewer B — Lifecycle + restart + volume cap + no-recorder
  invariant:** OC start-of-tracking semantics, Store blob restore / write
  debounce / `async_stop` flush (if Pick A), state-change listener
  cleanup on reload, `_filter_repeat_sensor_health` still ≤1 row/entity/day
  for the new key, confirm `grep recorder optimization.py` returns zero
  new hits (no event-loop blocking DB call), confirm no new NM paging
  surface beyond `sensor_health` allowlist.
- Elevate to **Tier 2-DB** ONLY if the M2 fix moves inside
  `_filter_repeat_sensor_health` (it should not; it stays local to D3).

## Rev 2 — Plan Completion / parked

Items from Rev 1 that will NOT ship in this cycle, with reason + revival
trigger:

- **D2 `_evaluate_sensor_stuck_dimension` — DROPPED (parsimony SIMPLIFY).**
  Reason: room-level P22 (coordinator.py:1824 / 2208-2234 / 3065-3072)
  already detects stuck-ON for all room motion/mmwave/occupancy inputs;
  OC `_evaluate_camera_stuck_dimension` (optimization.py:1921) covers
  exterior cameras; a third detector would create multi-notification for
  the same event. **Revival trigger:** a specific operator-visible stuck
  sensor that P22 AND `camera_stuck` BOTH miss, cited with the entity_id,
  the observed stuck window, and the code paths that failed to flag it.
  Theoretical gaps do not qualify; a reproduced miss does.
- Rev 1 D5 constants `SENSOR_STUCK_ON_THRESHOLD_S` and
  `SENSOR_STUCK_ON_OVERRIDES_S` — not added (fall out of D2 drop).
- Rev 1 D5 constant `SENSOR_NEVER_FIRES_RECORDER_CACHE_TTL_S` — not added
  (recorder-less producer).
- "CAMERA-STUCK-SENSOR-TRIPWIRE-1 folds into generalized evaluator in a
  follow-up" — cancelled; the Rev 1 fold was predicated on D2.
- Non-goals from Rev 1 that remain parked: numeric-value stuck (shape 3),
  actuator-unavailability (shape 4), class expansion beyond
  {motion, occupancy}, quarantine arms. Unchanged.

## Rev 2 — LOW adjustments

- **Sequencing:** build D3 **after** `fix/stuck-sensor-warn-once`
  (33b730db4) merges to develop. That branch edits coordinator.py-only
  (boot INFO naming latched sensors) and shares the P22 surface this
  cycle leans on for the invariant's "at most 1 NM per sensor per day"
  clause. No code collision expected, but ordering keeps the
  Reviewer-A/B framings against a stable P22 baseline.
- **D4 acceptance check:** per-evaluator output COUNT, not a timing log
  (per plan-review LOW L3).
- **Line refs:** Rev 2 cites `966`, `1921`, `2259-2270`, `4149` from
  develop `49b20bdfb`. Rev 1 refs (`934-935`, `1881`, `1992-1994`,
  `3922`) have drifted and should be read as the same symbol a few
  hundred lines away.
