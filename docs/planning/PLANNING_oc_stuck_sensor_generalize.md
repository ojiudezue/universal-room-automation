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
