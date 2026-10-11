# DRAFT README — OC-STUCK-SENSOR-GENERALIZE-1 (never-fires only)

Spec: `docs/planning/PLANNING_oc_stuck_sensor_generalize.md` (Rev 3 wins
where it conflicts with Rev 2). Branch: `feature/oc-never-fires`.
Tier 2 (two framing-disjoint reviews + live validation). This README is
prospective; the "Live" rows below will be rewritten with observed
evidence after HA restarts.

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
  `{first_seen, last_on_seen, unavailable_s, last_fired_at}`.
- Writes go through `Store.async_delay_save` (whole-blob, 120s debounce)
  on every listener-observed transition and on `first_seen` write.
- Load runs BEFORE the 5-min cycle timer in `async_setup` so tick #1
  sees persisted state. Evaluator returns `[]` while `_never_fires_loaded`
  is False. Fail-open on corrupt / missing blob.
- `async_track_state_change_event` subscription appended to
  `_unsub_listeners` (Bug Class #50 teardown contract).
- Prune eids no longer in the D1 resolver at load AND at evaluator entry.

Semantics:

- **Horizon clock** = max(first_seen, last_on_seen, last_fired_at).
  `last_fired_at` is set when the evaluator emits a finding, so a
  stuck-silent sensor re-fires at most once per horizon (and across
  restarts) rather than once per daily-latch window.
- **Available-now gate**: must not currently be `unavailable` /
  `unknown`.
- **Availability-fraction gate (F1)**: `unavailable_s` across the
  window must be ≤ `(1 - 0.8) × horizon`. HA-down time is uncharged —
  only listener-observed state transitions accrue seconds. This is
  what lets the 7d horizon fire under the measured ~10.5h mean uptime
  / 16 restarts per week cadence.
- **Daily latch** `_never_fires_fired` + local-midnight rollover.
- **Discharge** (Rev 2 M2): on any ON transition, pop the RAM latch,
  pop `last_fired_at`, AND pop the matching
  `_sensor_health_last_persisted` key so a re-silence within 24h of
  recovery persists a row (and is not suppressed by the shared 24h
  repeat cover).
- **URA-aggregate filter** (Rev 2 M1): entity-registry
  `platform == DOMAIN` entries are dropped. Unregistered eids are
  INCLUDED and logged at DEBUG (Rev 3 F6).

## Knob ladder (module constants in `const.py`)

| Knob | Default | Rung | Why |
|---|---|---|---|
| `SENSOR_NEVER_FIRES_HORIZON_S` | 604800 (7d) | module constant | Matches the measurement window in `AUDIT_stuck_sensor_duration_distributions.md`. **0 disables the evaluator** (kill switch). A shorter window raises false-positives on legitimately dormant exterior detectors. |
| `SENSOR_NEVER_FIRES_MIN_AVAILABILITY_FRACTION` | 0.8 | module constant | F1 gate: at most 20% of the horizon spent in `unavailable`/`unknown` since the clock last reset. Below this the sensor's silence is `sensor_health`'s problem, not never-fires. HA-down time counts as neither (uncharged). |
| `SENSOR_NEVER_FIRES_PERSIST_DEBOUNCE_S` | 120 (2 min) | module constant | Whole-blob `Store.async_delay_save` debounce. 60-300s matches the precedent at `coordinator.py:~2405` (60.0). 120s coalesces listener bursts; a crash within the window loses at most one state-transition record. |

Rung is module constant (not operator-tunable Number entity) by design:
these knobs trade false-positive rate against detection latency and
crash-loss risk — moving them should require review.

## Prospective Live acceptance criteria (DISCRIMINATING)

Each row below describes the single observation that distinguishes
"this shipped correctly" from "a different plausible failure". After
the restart that lands this cycle, these turn into observed-evidence
rows (`Validated <date>`).

- **Live (store shape)**: inspect
  `.storage/optimization.sensor_never_fires_last_on_seen` after one OC
  tick → contains per-eid records with `first_seen`, `last_on_seen`,
  `unavailable_s`, (optionally) `last_fired_at`. This is the F1
  discriminator: bare-timestamp values would mean the Rev 2 shape
  shipped dormant.
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
- **Live (16-restarts-in-7d invariant)**: under the measured restart
  cadence, a single eid known to be silent for ≥ 7d produces exactly
  ONE `anomaly_log` row across the window (not one per restart).
  Multiple rows per eid per 7d = `last_fired_at` not persisting or not
  being consulted.

Non-goals (unchanged from Rev 1/2):

- No numeric-value stuck detection (shape 3).
- No actuator-unavailability detection (shape 4).
- No OC stuck-ON mirror (Rev 2 parsimony SIMPLIFY).
- No recorder reads.
- No new config-flow fields or Number entities.
- No class expansion beyond `{motion, occupancy}` in v1.
