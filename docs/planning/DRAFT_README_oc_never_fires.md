# DRAFT README — OC-STUCK-SENSOR-GENERALIZE-1 (never-fires only)

Spec: `docs/planning/PLANNING_oc_stuck_sensor_generalize.md` (Rev 3 wins
where it conflicts with Rev 2). Branch: `feature/oc-never-fires`.
Tier 2 (two framing-disjoint reviews + live validation). This README is
prospective; the "Live" rows below will be rewritten with observed
evidence after HA restarts.

**Review A fix-up pass applied** (2026-10-11):

- HIGH #1 (Bug Class #53): removed the per-day latch and the
  `last_fired_at` dedup clock. The evaluator now emits every cycle
  while the condition holds (same shape as sensor_health). The daily
  digest built from `_last_findings` sees the finding every 5-min
  cycle; `_filter_repeat_sensor_health` caps DB persistence to ≤1
  row/entity/24h. Also fixes the boot-storm-skip loss case.
- HIGH #2: `unavailable_s` resets to 0 on a genuine off->on
  transition. The fraction gate now measures unavailable time SINCE
  the clock last reset (per spec), not cumulative lifetime. A sensor
  that suffered a 36h outage, recovered + fired, and then went silent
  for 7d WILL fire again.
- HIGH #3: `_never_fires_resubscribe()` reconciles the listener
  subscription with the current D1 universe on every evaluator tick.
  A sensor added after `async_setup` (options-flow edit, or a camera
  binary_sensor that materialised later) is subscribed before it is
  evaluated. The old subscription's unsub is removed from
  `_unsub_listeners` across the swap so Bug Class #50 teardown stays
  correct.
- MEDIUM #6: all test module-attr overrides routed through
  `monkeypatch.setattr`.
- SHOULD #5: added `SENSOR_NEVER_FIRES_OVERRIDES_S: dict[str, int]`
  module constant. 0 opts a sensor out, >0 sets a per-sensor horizon.
- SHOULD #7: dimension-registration anchor is now behavioral (drives
  `_run_cycle_body` and asserts the finding in the cycle output and
  `_last_findings`).
- SHOULD #8: unavailable->on (rejoin) is NOT treated as a firing.
  Only genuine off->on resets the clock.

## What changed

A new OC evaluator `_evaluate_sensor_never_fires_dimension` fires one
HIGH `SENSOR_HEALTH`-dimension finding per sensor per local day when a
raw motion/occupancy sensor URA is configured to consume has produced
ZERO ON transitions over the horizon.

- Dimension host: existing `SENSOR_HEALTH` (reuses
  `_filter_repeat_sensor_health` 24h row cover and the optimizer NM
  allowlist — no new wiring).
- Companion to: room-level P22 (stuck-ON, `coordinator.py`) and
  `_evaluate_camera_stuck_dimension` (exterior cameras stuck-ON). Rev 2
  SIMPLIFY: NO OC stuck-ON mirror; the room/camera detectors stay.
- Scope v1: classes `{motion, occupancy}`. Sources: room inputs via
  `CONF_OCCUPANCY_SENSORS` / `CONF_MOTION_SENSORS` /
  `CONF_MMWAVE_SENSORS` + perimeter + egress camera person-detectors
  via `_exterior_person_sensors`.

Persistence (Rev 3 PICK A, F1-F7):

- One HA Store at `optimization.sensor_never_fires_last_on_seen`,
  version 1, keyed per entity:
  `{first_seen, last_on_seen, unavailable_s}`. (`last_fired_at` was
  dropped in the review A fix-up — see HIGH #1 above.)
- Writes go through `Store.async_delay_save` (whole-blob, 120s debounce)
  on every listener-observed transition and on `first_seen` write.
- Load runs BEFORE the 5-min cycle timer in `async_setup` so tick #1
  sees persisted state. Evaluator returns `[]` while `_never_fires_loaded`
  is False. Fail-open on corrupt / missing blob.
- `async_track_state_change_event` subscription appended to
  `_unsub_listeners` (Bug Class #50 teardown contract).
- Prune eids no longer in the D1 resolver at load AND at evaluator entry.

Semantics (post review A fix-up):

- **Horizon clock** = `max(first_seen, last_on_seen)`. Per-entity
  horizon = `SENSOR_NEVER_FIRES_OVERRIDES_S.get(eid, SENSOR_NEVER_FIRES_HORIZON_S)`.
- **Per-cycle emit** (HIGH #1): the evaluator emits every cycle while
  the condition holds. The shared `_filter_repeat_sensor_health`
  (24h) caps DB persistence to ≤1 row/eid/24h; `_last_findings` and
  the daily digest see the finding every 5-min tick.
- **Available-now gate**: must not currently be `unavailable` /
  `unknown`.
- **Availability-fraction gate**: `unavailable_s` SINCE the clock
  last reset must be ≤ `(1 - 0.8) × horizon`. The ON reset zeroes
  this counter (HIGH #2), so a prior outage does not permanently
  disable detection. HA-down time is uncharged (only listener-
  observed transitions accrue).
- **Clock reset** (HIGH #2 + SHOULD #8): a genuine `off->on`
  transition sets `last_on_seen = now` AND `unavailable_s = 0` AND
  clears the matching `_sensor_health_last_persisted` key (Rev 2 M2
  — re-silence within 24h still persists a row). An
  `unavailable->on` transition is a REJOIN and does NOT reset the
  clock.
- **URA-aggregate filter** (Rev 2 M1): entity-registry
  `platform == DOMAIN` entries are dropped. Unregistered eids are
  INCLUDED and logged at DEBUG (Rev 3 F6).
- **Listener resubscribe** (HIGH #3): every evaluator tick reconciles
  the subscription set with the current D1 universe. The old unsub
  is called, dropped from `_unsub_listeners`, and the new one
  appended — Bug Class #50 teardown stays correct across the swap.

## Knob ladder (module constants in `const.py`)

| Knob | Default | Rung | Why |
|---|---|---|---|
| `SENSOR_NEVER_FIRES_HORIZON_S` | 604800 (7d) | module constant | Matches the measurement window in `AUDIT_stuck_sensor_duration_distributions.md`. **0 disables the evaluator** (kill switch). A shorter window raises false-positives on legitimately dormant exterior detectors. |
| `SENSOR_NEVER_FIRES_MIN_AVAILABILITY_FRACTION` | 0.8 | module constant | F1 gate: at most 20% of the horizon spent in `unavailable`/`unknown` since the clock last reset. Below this the sensor's silence is `sensor_health`'s problem, not never-fires. HA-down time counts as neither (uncharged). |
| `SENSOR_NEVER_FIRES_PERSIST_DEBOUNCE_S` | 120 (2 min) | module constant | Whole-blob `Store.async_delay_save` debounce. 60-300s matches the precedent at `coordinator.py:~2405` (60.0). 120s coalesces listener bursts; a crash within the window loses at most one state-transition record. |
| `SENSOR_NEVER_FIRES_OVERRIDES_S` | `{}` | module constant | Per-entity horizon overrides (mirrors `CAMERA_STUCK_ON_OVERRIDES_S`). 0 opts a sensor out entirely; >0 sets a shorter or longer horizon for that eid. Named exemption, not operator policy — e.g. a guest-room motion detector that may legitimately sit idle for weeks between stays. |

Rung is module constant (not operator-tunable Number entity) by design:
these knobs trade false-positive rate against detection latency and
crash-loss risk — moving them should require review.

### Silencing a rarely-used sensor

The default 7d horizon means a motion detector in a room that is
empty for 7+ days (guest rooms, basement storage) will produce one
`sensor_never_fires` finding — this is working as designed: the
operator genuinely does not know whether such a sensor is broken or
just not being tripped. Two ways to silence:

- **For a single sensor**, add it to `SENSOR_NEVER_FIRES_OVERRIDES_S`
  with value `0`:
  ```python
  SENSOR_NEVER_FIRES_OVERRIDES_S: Final[dict[str, int]] = {
      "binary_sensor.guest_room_motion": 0,  # never alert
  }
  ```
  A reviewed code change, same shape as `CAMERA_STUCK_ON_OVERRIDES_S`
  for the per-camera exemptions.
- **For a different horizon** (e.g. the sensor should alert after
  30d of silence rather than 7d): set the override to the horizon in
  seconds (30d = 2592000).

## Prospective Live acceptance criteria (DISCRIMINATING)

Each row below describes the single observation that distinguishes
"this shipped correctly" from "a different plausible failure". After
the restart that lands this cycle, these turn into observed-evidence
rows (`Validated <date>`).

- **Live (store shape)**: inspect
  `.storage/optimization.sensor_never_fires_last_on_seen` after one OC
  tick → contains per-eid records with `first_seen`, `last_on_seen`,
  `unavailable_s`. Bare-timestamp values would mean the Rev 2 shape
  shipped dormant.
- **Live (resubscribe)**: add a sensor to a room via options flow;
  within the next OC cycle, the `_never_fires_subscribed` set grows
  to include the new eid AND an ON event for that eid lands in the
  blob's `last_on_seen`. If `_never_fires_subscribed` doesn't update,
  HIGH #3 regressed.
- **Live (load before cycle)**: HA log shows
  `never-fires: restored N entries from Store` BEFORE
  `Coordinator optimization started`. Reversed order = F5 regressed.
- **Live (resolver scope)**: within 10 min, OC debug log carries one
  `watched_raw_sensors` entry per CONF_OCCUPANCY/MOTION/MMWAVE sensor
  across rooms + perimeter + egress camera person-detectors; zero
  entity_ids owned by the URA platform (M1 regression discriminator).
- **Live (listener wiring, not just defined)**: within 10 min, at least
  one record in the Store blob shows `last_on_seen` advancing on a
  natural room ON event. If `last_on_seen` stays `null` for an eid
  that the state log shows transitioned to ON, the F7 subscription is
  not wired (vs just the method being defined).
- **Live (24h)**: for any eid known-silent for ≥ 7d, exactly one
  `anomaly_log` row with `dedup_key=("sensor_never_fires", <eid>)` and
  payload carrying `first_seen`, `last_on_seen`, `unavailable_s`.
  Multiple rows for the same eid within 24h = daily-latch regression;
  zero rows for a known-silent eid within 24h after `first_seen` is
  ≥ 7d past = evaluator dormant.
- **Live (unavailable discriminator)**: for an eid whose only
  on-duration was an `unavailable` segment (AUDIT caveat 1), NO
  never-fires row fires AND no `anomaly_log.payload.stuck_seconds`
  equals the unavailable-segment length. (The row that DOES fire for
  this eid, if any, is from `sensor_health`'s unavailable path with a
  different dedup key — not from never-fires.)
- **Live (per-cycle emit)**: the daily digest built from
  `_last_findings` carries the `sensor_never_fires` row every day the
  condition holds (not just the day the finding first "latches"). A
  silent 7d sensor shows up in every digest until it recovers; the
  DB side carries ≤1 row/eid/24h thanks to
  `_filter_repeat_sensor_health`.
- **Live (unavailable_s reset)**: inspect the Store blob after a
  sensor fires (off->on) → `unavailable_s` for that eid is 0 and
  `last_on_seen` advances. Discriminator vs the pre-fix shape: a
  sensor that cumulatively saw > 20% × horizon of unavailable time
  over its lifetime still fires again after a reset-then-silence
  cycle (the HIGH #2 case).

Non-goals (unchanged from Rev 1/2):

- No numeric-value stuck detection (shape 3).
- No actuator-unavailability detection (shape 4).
- No OC stuck-ON mirror (Rev 2 parsimony SIMPLIFY).
- No recorder reads.
- No new config-flow fields or Number entities.
- No class expansion beyond `{motion, occupancy}` in v1.
