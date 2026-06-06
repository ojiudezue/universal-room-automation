# URA v4.7.24 — Occupancy Substrate Unification

**Release date:** 2026-06-05
**Tier:** Tier 2-DB (three framing-disjoint staff-engineer reviews — A: discovery, B: lifecycle/smoothing, C: boundaries/tests — plus live validation)
**Scope:** Introduces a single per-room, per-kind raw-signal layer
(`OccupancySubstrate`) BENEATH both the room-coordinator occupancy tier and
the presence-coordinator (zone) occupancy tier, so the operator's curated
`CONF_MOTION_SENSORS` / `CONF_MMWAVE_SENSORS` / `CONF_OCCUPANCY_SENSORS` lists
become the single source of truth for sensor discovery AND kind classification
in both tiers.

**Files:**
- `domain_coordinators/occupancy_substrate.py` (NEW)
- `domain_coordinators/presence.py`
- `domain_coordinators/signals.py`
- `domain_coordinators/__init__.py`
- `coordinator.py`
- `binary_sensor.py`
- `quality/scripts/audit_substrate_conf_coverage.py` (NEW)
- 11 substrate test modules in `quality/tests/`

---

## Trigger

The room tier and the zone tier discovered and classified their occupancy
sensors by two different mechanisms that could disagree:

- **Room tier** read the operator's curated CONF sensor lists
  (`coordinator.py`).
- **Zone tier** did an entity-registry area-sweep
  (`presence.py:_discover_room_sensors`), which could pick up sensors the
  operator never curated, fail on `area_id == null`, and classify a sensor's
  kind (motion / mmwave / occupancy) differently than the room tier.

Concretely: the Jaya room's zone sweep saw 4 sensors vs the curated 2; Exercise
saw 3 vs 2. This divergence is the *generalized* root behind the kind of
room-tier/zone-tier disagreement that the manual bed-sensor wiring patched as a
one-off. The substrate makes the curated lists authoritative for both tiers.

---

## Headline Changes

- **`OccupancySubstrate`** — a new per-room, per-kind, instantaneous raw-signal
  layer. It tracks each curated sensor's current state, classifies it by kind
  from the CONF list it came from (no registry guessing), and publishes
  `SIGNAL_SUBSTRATE_KIND_CHANGED(room, kind, new_state)` on every edge. It is
  NOT a new tier and does NOT replace either occupancy tier — both tiers now
  consume the same substrate beneath them.
- **Zone-tier migration (D2).** The presence coordinator's entity-registry
  area-sweep and its name-fallback discovery are replaced by substrate
  subscription. The curated CONF lists are now authoritative for the zone tier
  too.
- **Room-tier rewire (D3).** The room coordinator's Tier-1 fast-path listener
  now reacts to `SIGNAL_SUBSTRATE_KIND_CHANGED` (preserving the existing 2s
  rate-limiter + leading-edge `async_refresh()`); the lux sensor keeps its own
  direct state-change listener since it lives outside the CONF presence-sensor
  lists.
- **Back-compat preserved (D4).** `_room_provenance` / `_room_occupied`
  (derived OR), `any_zone_raw_occupied`, and the `_zone_provenance_breakdown`
  diagnostic all keep their existing shapes and consumers.
- **No-CONF fallback + audit (D5).** A room with empty CONF lists degrades
  cleanly; `quality/scripts/audit_substrate_conf_coverage.py` reports any room
  whose curated coverage looks thin.
- **Boot-storm coordination (D6).** The substrate respects the existing
  cold-boot settle gates so it can't contribute to the away-actuation storm.

---

## Tier 2-DB Review + Fix-up

Three framing-disjoint reviews ran in parallel. The wave surfaced a real
CRITICAL that static parity-testing missed:

- **B-C1 (CRITICAL, fixed).** The room tier's substrate subscription was stored
  in `_unsub_signal_listeners`, which `_update_signal_subscriptions()` clears
  and rebuilds wholesale at first refresh AND on every options-flow save —
  silently dropping the room tier's Tier-1 substrate edges (the lux direct
  listener masked it). Fixed with a dedicated `_unsub_substrate_listeners` list
  that the signal-rebuild routine never touches, torn down in the reload-clear
  and unload paths. New behavioral regression guard simulates an options-save
  clobber between setup and dispatch. Filed as **QUALITY_CONTEXT Bug Class #50**
  (long-lived subscription stored in a list cleared by a periodic rebuild).
- **B-H1 (HIGH, fixed).** Function-local `async_dispatcher_connect` imports in
  `presence.py` hoisted to module top (Bug Class #34).
- **B-H2 (HIGH, fixed).** Setup log now reports substrate-routed sensor count
  (motion + mmwave + occupancy) separately from the lux direct listener.
- **C-HIGH-1/2/3 (fixed).** Tautological back-compat test and source-grep
  integration test rewritten to drive a real substrate; weakened invariant in
  the sleep-wake deadlock test restored.

Deferred (documented in the review docs): the FanRecheck
`STATE_OCCUPANCY_SOURCE` ring round-trip in the back-compat test (needs a full
HA coordinator fixture; call-shape equivalence is covered), a boot-settle gate
on the room-tier refresh (room coordinator has no `_boot_settle` flag; the
v4.7.21 settle gates already cover the actuation layer), and LOW cosmetic /
dead-code removals.

---

## Tests

- 45 substrate cycle tests pass (backcompat, room integration, zone migration,
  discovery, classification, lifecycle, boot-settle, seed, no-CONF fallback,
  sleep-wake deadlock).
- Full suite: 5034 passed / 62 failed / 14 errors — the 62 failures and 14
  errors are the known pre-existing baseline (uninstalled-module test groups);
  no new regressions. The +2 vs the pre-fix baseline are the new behavioral
  tests.
- All changed modules `py_compile` clean; no conflict markers.

---

## Live Validation (Review D)

**Validated 2026-06-05** — HACS v4.7.24 downloaded, `ha_check_config` valid, HA
restarted. Results recorded against the prospective criteria:

| Criterion | Result |
|---|---|
| Substrate instantiated + feeding per-kind state (not the fail-open all-False default) | **PASS** — `binary_sensor.master_bedroom_occupied` (occupied) reports `substrate_kinds = {motion:false, mmwave:true, occupancy:true}`. Real per-kind reads, not the default. |
| Per-room discrimination (substrate not stuck / global) | **PASS** — `binary_sensor.exercise_room_occupied` (empty) reports `substrate_kinds` all-false alongside the occupied master read. Two rooms, opposite states, same tick. |
| Room occupancy correct + updating post-boot | **PASS** — master bedroom `on`, `current_persons` populated, `last_reported` advancing after boot. |
| No substrate / B-C1 / dispatcher errors | **PASS** — error-log scan since boot shows zero substrate / `UnboundLocalError` / dispatcher errors. Only pre-existing, boot-only transients: "DB write worker not running" (census/energy snapshots ~1 min into boot, before the write worker starts) and boot-storm websocket saturation to the iOS app. Both cleared after settle. |
| House-state persistence across restart | **As-expected** — boots `away` (state machine still does not persist across restart; known, decided-dropped). |

Notes:
- The `Event-driven mode — N Tier 1 sensors via substrate signal` setup line is
  INFO level and HA's default logger is WARNING, so it does not reach journald.
  The live `substrate_kinds` entity attribute is the authoritative signal and
  was used instead.
- The B-C1 clobber-survival (options-save between setup and dispatch) is proven
  in-suite by `test_room_substrate_integration.py::test_room_handler_survives_signal_listener_clobber`
  rather than by an intrusive live options-save on the running house. The live
  reads confirm substrate edges are reaching the room entity.
- HA's event loop was saturated by the cold-boot away-actuation storm for the
  first few minutes (MCP calls timed out until it settled — the documented
  boot-storm behavior; v4.7.21 settle gates mitigate but it still takes a few
  minutes to clear).

---

## Not in scope

This cycle unifies discovery + classification; it does **not** by itself change
the Zone-1 `home_night` `away`-flip. That still needs the separate person-trust
extension (extend the sleep-only trust at `hvac.py:1151` to `home_night`). The
substrate is the foundation that fix should build on.

## Review

See `docs/reviews/code-review/substrate_review_B_lifecycle.md` and
`substrate_review_C_boundaries.md` (each with a fix-up resolution footer).
