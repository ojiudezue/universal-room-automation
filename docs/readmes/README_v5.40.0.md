# v5.40.0 — Comfort-Fan AWAY Veto (mmWave-corroboration Tier-3 cycle, D3 core)

## What shipped

Comfort fans can no longer turn ON in a room while the house is AWAY or VACATION
unless the room shows **trusted presence** — recent PIR motion (within the room's
`occupancy_timeout`; mmWave-named hybrids excluded by `MMWAVE_NAME_PATTERN`) or a
BLE-trustworthy person in the room (active trackers only). mmWave alone is
explicitly NOT trusted for this decision: fan airflow re-triggers mmWave, which
is the self-sustaining phantom loop (Study A 2026-07-31, Master Bedroom
2026-07-26) this cycle closes at the actuation edge.

**Four veto sites**, all routed through the shared `fan_veto.should_veto_comfort_fan`:
1. Room tier — `automation.py` `handle_temperature_based_fan_control` turn-on branch
2. HVAC tier — `hvac_fans.py` `FanController.update` ON edge
3. Reconciler — `actuator_reconciler.py` `_resolve_fan` (returns no-opinion on veto)
4. Recheck restore — `hvac_fans.py` `restore_after_recheck` (Review D's 4th site:
   house→AWAY during a recheck window no longer restores the fan)

**Untouched by design:** humidity/safety fans (sole-owner contract), all fan
turn-OFF paths, the sleep path (D-AUT per-room reasoning), manual actuations,
speed changes on already-on fans.

**Fail-open posture:** boot-settle window, unknown house-state, unresolvable room
config, and any predicate exception all SKIP the veto (worst case = pre-cycle
behavior). The kill switch `comfort_fan_away_veto_enabled` is per-room in the
options flow, **default ON** for every room.

**Camera trust leg: dormant by construction.** `_has_camera_person` reads
room-level `camera_person_entities`, which the v3.4.5 migration actively strips
(centralized to the census). It grants trust nowhere today; enabling it is the
scoped room-camera fusion follow-on cycle, NOT a config add.

**Known residuals (documented in plan):** a fan already ON when the house turns
away is not force-stopped (fan-recheck covers this organically post-bucket-
reclassification); AI-rule executor fan commands are unvetoed (parked).

## Companion config actualization (same cycle, applied live 2026-08-01 pre-deploy)
7 rooms' mmWave devices reclassified from `occupancy_sensors` → `presence_sensors`
(Study A, Kitchen, Media, Master Bedroom Inovelli, Master Bathroom, Guest
Bedroom 1, Upstairs Guestroom) — restoring `occupancy_source: mmwave` so
fan-recheck's mmwave-sole gate can see them. Study A's dead Athom removed
(dead `mmwave_sensors` key is unconsumed cruft).

## Review record
`docs/reviews/code-review/comfort_fan_away_veto_tier3.md` — 4 framing-disjoint
reviews + orchestrator verification. 1 CRIT + 5 HIGH found; all fixed except two
documented deferrals. 6 mutation drills red→green. Harness fix: pinned real
STATE_ON/STATE_OFF strings (bare-MagicMock constants silently broke state
comparisons suite-wide).

## Live Validation (Review 3) — prospective
- **Live:** with house AWAY and a hot room lacking trusted presence, the INFO line
  `comfort fan veto (house_state=away, room=<name>) — no trusted presence`
  appears and the fan does NOT start; `comfort_fan_away_veto_count` attribute on
  `binary_sensor.<room>_occupancy` increments.
- **Live:** zero veto lines while house is HOME (baseline preservation); at least
  one comfort fan actuates normally when occupied+hot.
- **Live:** post-restart (boot-AWAY window), no veto suppression during
  boot-settle; no URA errors referencing fan_veto.
- **Live:** reclassified rooms report `occupancy_source: mmwave` when mmWave-held.
