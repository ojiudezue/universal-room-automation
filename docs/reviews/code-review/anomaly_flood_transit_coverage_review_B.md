# ANOMALY-FLOOD-ROWS-1 — Review B (cross-coordinator consumers + lifecycle/race + restart)

Branch `fix/anomaly-flood-transit-coverage` @ a6319b7e3, base b0b47a42c (`git diff b0b47a42c..a6319b7e3`).
Tier 2, framing B. Read: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md transit rows + the new coverage paragraph,
QUALITY_CONTEXT bug classes. No pytest run (serial validator follows). Note: the site is
`transitions.py:250-258` calling `transit_validator.py:validate_transition` (~:645-760).

Identity model: this cycle consumes F3-adjacent interior camera sightings (shared-space cameras) only as
path evidence; it produces no F1-F5 fact. Consumers below are all display / analytics class.

## 1. Consumer enumeration (path_method / path_confidence_delta / _validation / transition confidence)

Re-enumerated with `git grep` over `custom_components/` at a6319b7e3 (not the plan's list).

| # | Consumer | file:line | Class | Effect of implausible -> no_camera_data |
|---|---|---|---|---|
| C1 | `_update_transition_confidence` gate `delta != 0.0` | transitions.py:251, :640-656 | DB write | Row keeps base confidence; `validation_method` stays NULL instead of `path_implausible`. Intended. |
| C2 | `database.update_transition_validation` | database.py:4570-4595 | DB | Called ~230/day less. `validation_method` column has NO reader in custom_components (grep). |
| C3 | `_emit_invalid_transition_anomaly` (anomaly row + activity) | transitions.py:256-257, :440-495 | anomaly / display | The intended row reduction. |
| C4 | Diagnostics roll-up `COORDINATOR_EMIT_LABELS["presence"]` includes `transit` | domain_coordinators/coordinator_telemetry_const.py:25 | display | Presence anomaly counts on the Diagnostics tab drop. Expected, not a regression. |
| C5 | `transition._validation` attribute | transitions.py:254 | none | NO reader anywhere (grep `_validation` across custom_components: only the setter). Dead attach, unchanged. |
| C6 | In-memory `transition.confidence` | transitions.py:648 | - | The validator never mutates the in-memory object (`new_confidence` goes to DB only). Listeners see the same value before and after. |
| C7 | Bayesian live update listener | __init__.py:3249-3259 | prediction | Reads in-memory confidence (C6) -> unchanged. |
| C8 | Bayesian cold-start priors from DB `confidence` | bayesian_predictor.py:245-263 (filter `< MIN_CONFIDENCE_FULL_WEIGHT` 0.3, :44); database.py:8070-8105 | prediction | Filter-only (raw `+= 1` count, :283). Base confidences are >= 0.50 (transitions.py:385-404), so 0.50-0.15 = 0.35 never crossed 0.3 before. No change. |
| C9 | Pattern learning `get_transitions` | pattern_learning.py:69, database.py:4367-4440 | prediction | Selects `confidence`; no threshold on it in the read path I found. Values rise 0.15 on ~230 rows/day. LOW, see B-L2. |
| C10 | Music following | music_following.py:2305 | display (decision log) | Logs `transition_confidence` only; state-of-play row 121 + code confirm MF no longer gates on transition confidence. No behaviour change. |
| C11 | Presence / census / HVAC / NM | grep | - | No reader of path_method, delta or transit confidence. NM is reached only via the anomaly pipeline (C3). |

No consumer used the -0.15 penalty as an action gate. Behaviour change is confined to the anomaly rows (intended),
the DB `confidence` / `validation_method` values on uncovered moves, and display counts.

## 2. Lifecycle / race / restart

- **Room -> area map** (`build_room_to_area_id_map`, camera_census.py:160-187): rebuilt on EVERY call, no cache, reads
  `config_entries.async_entries(DOMAIN)` which lists all entries from boot regardless of load state. No boot window
  where it is stale; room option changes are picked up immediately. Failure returns `{}` -> not covered -> delta 0:
  the safe direction (no false penalty, no row). HOLDS.
- **Camera -> area cache** (`_shared_camera_area`, transit_validator.py:~329, cleared :~556, filled :~839-846):
  entity registry is loaded before integration setup, so first-use lookups are valid at boot.
  **B-L1 (LOW, stale cache):** the only rebuild triggers are an entity-registry update of a `unifiprotect`
  entity (:~420-432), the transit-config signal, and restart. An area change on a non-Protect shared camera, or
  on a camera's DEVICE (device-registry event, not an entity event), leaves the cached area stale until the next
  rebuild/restart. Direction: stale `None` / old area -> mostly no penalty (safe); an old area could still penalise
  moves in a room that no longer has the camera. Rare operator action; acceptable, worth a docstring note or
  adding `EVENT_DEVICE_REGISTRY_UPDATED` / clearing the cache in the existing listener for any area change.
- **Import / call-before-setup:** `build_room_to_area_id_map` is imported lazily inside
  `_transition_covered_by_shared_camera`; camera_census has no module-level import of transit_validator
  (only docstring mentions). No cycle. It needs only `hass`, not a set-up `PersonCensus`. HOLDS.
  `PersonCensus._build_room_to_area_id_map` delegation is byte-identical (same body moved). HOLDS.
- **Unsub fields moved into `__init__`** (transit_validator.py:~339-343): previously dead code after the
  `return` in `build_diagnostic_attrs`. Before the fix, `_schedule_rebuild` / `async_teardown` read the
  attributes inside `try/except Exception`, so an AttributeError was swallowed (teardown before init was safe
  by luck). Now set to None before `async_init` assigns them (:~467, :~512). `async_teardown` (:~1001-1029)
  still cancels timer, config signal and face signal and resets to None. Correct; strictly an improvement.
- **Counters** are plain ints mutated on the event loop inside a sync section of `validate_transition`
  (no await between check and increment). No race.
- **Concurrent-correlation branch** (`_correlate_sighting_to_transition`, :~696) is not gated by coverage, but the
  only production caller (transitions.py:250) passes no `concurrent_transitions`, so it is unreachable live.
  Noted, not a finding (plan states it unchanged).

## 3. PresenceDiagnosticSensor attributes (sensor.py:6840-6892)

Two monotone ints added. Sensor is disabled by default (`_attr_entity_registry_enabled_default = False`),
push-only (`_attr_should_poll = False`), already carries O(rooms) attrs that change per refresh. Two ints add
negligible recorder cost; no `_unrecorded_attributes` needed. Reads via `getattr(..., 0)` with `int(... or 0)` —
safe on an older validator object. **B-L3 (LOW, cosmetic):** counters are "since start" and reset on restart /
reload; documented as such in the payload comment. Fine for diagnostics.

## Findings

| ID | Sev | Class | file:line | Status |
|---|---|---|---|---|
| B-L1 | LOW | Stale cache (no invalidation on non-Protect / device area change) | transit_validator.py `_shared_camera_area` + registry listener ~:420-432 | open, optional |
| B-L2 | LOW | Downstream value shift (pattern learning sees +0.15 on uncovered moves) | pattern_learning.py:69 | accept, intended |
| B-L3 | LOW | Since-start counters reset on restart | transit_validator.py build_diagnostic_attrs | accept |

No CRITICAL / HIGH / MEDIUM.

## Verdict

**SHIP.** No consumer gated on the penalty; boot/fallback direction is safe (no penalty); teardown is correct
and improved; no import cycle. B-L1 is an optional small hardening.
