# PLANNING — Occupancy freshness gate (stuck-frozen-on demote)

**Card:** `STUCK-MOTION-FROZEN-ON-BLINDSPOT-1` · **Tier:** 2-DB (occupancy TRUST; presence→house_state→zone
ripple; false-negative = abandoning a real occupant).
**Origin:** live incident 2026-09-18 — `binary_sensor.upstairs_hall_motion_3` (a **camera/Frigate** motion
object) latched `on` at 16:27 when the feed stopped, held the room occupied, pinned `house_state=home_day`
and zone_2 `home` with all persons `not_home`. Every existing defense missed it (motion exempt as trusted
corroborator; staleness keyed on `unavailable`; the stuck-on sensor *vouched* for the phantom).

## Institutional context verified (from the read-only scan + measure)
**Measured (recorder, 7d): a standalone age threshold is UNSAFE.** These inputs are edge-driven (≈0
heartbeat rows); legitimate silence-while-`on` reaches **p95 1.8 h / max 23 h** (camera-motion),
**p95 20 min / max 26 h** (room PIR), **p95 52 min / max 5 h** (mmWave still-body). A useful (minutes–1 h)
age gate would clip live occupants → the false-negative the card fears. Incident confirmed: last row
16:27:56 `on`, then >1 h silence (its own p95 legit silence is 1.8 h — at 1 h the freeze is
indistinguishable from a normal latch by age alone).

**REUSE (do not rebuild):**
- `SensorExclusionSet` / STEP-EXCLUDE-1 (`sensor_exclusion.py`): a demoted sensor's vote contributes **0**
  to the room's occupancy legs, multi-writer per-client, `reset_tick()` each tick. Promotion sites:
  coordinator.py:2988 & 3070 (continuous-on + dutycycle already promote here). → **add a new client `"freshness"`.**
- `CORROBORATOR_DISAGREE_S = 900.0` (const.py) — the corroboration-disagreement window (already derived to
  exceed the 300 s D2 shield). Reuse as the "lone dissenter" gate.
- `resolve_role` / `SensorCapability.kind` (`sensor_role.py`) for per-kind resolution; `_CORROBORATOR_KINDS`
  (motion/pir/bed/camera-presence/ble) for the corroborator set.
- Continuous-on precedent `_get_stuck_sensors` (coordinator.py:2096, `_stuck_sensor_hours=4.0`) — same shape.

**BUILD (small):** a kind→expected-interval→age helper (no existing helper marries kind+`last_updated`);
per-kind age-floor constants (none exist near occupancy); the `"freshness"` exclusion client.

**Prior plans consulted:** `PLANNING_stuck_signal_watchdog.md`, `PLANNING_sensor_health_surfacing.md`
(STEP contract), `PLANNING_stuck_sensor_consequence.md` (positive-evidence variant PARKED), `PROBE_mmwave_
healthy_cadence.md` (prior cadence measure), `PLANNING_mmwave_corroboration_tier3.md`.

## Falsifiable invariant (INV-FRESH)
1. **The freshness gate NEVER causes a room to be reported unoccupied while at least one *non-stale*
   occupancy input in that room is `on`.** (Demote, not drop — a lone stale sensor is silenced; any live
   input still holds the room.)
2. **A sensor reporting within its per-kind expected interval is never excluded by freshness** — the age
   floor sits above the measured p95 legitimate silence-while-`on` for its kind.

## D1 — Freshness demote (corroboration-gated, per-kind)
A sensor is promoted into `SensorExclusionSet` under client `"freshness"` (vote → 0) **only when ALL** hold:
1. it is currently `on`;
2. `now - hass.states.get(eid).last_updated ≥ FRESHNESS_AGE_FLOOR[kind]` — **module constants (Rung-1,
   safety envelope):** `motion`/`camera_motion` = **7200 s (2 h)** (> p95 1.8 h); `mmwave`/`occupancy` =
   **21600 s (6 h)** (> still-body max 5 h). mmWave MUST be distinctly longer (still-body hold).
3. **corroboration disagrees:** every `_CORROBORATOR_KINDS` sensor in the room has been `off`/quiet for
   ≥ `CORROBORATOR_DISAGREE_S` (900 s) — i.e. the stale sensor is the *lone dissenter* against an
   otherwise-unanimously-quiet room. (This is the frozen-feed signature; never the still-occupant one.)
Released when the sensor reports again OR any corroborator goes `on`. Wire alongside the existing
continuous-on/dutycycle promotions (coordinator.py:2988/3070). Kind from `resolve_role`/`SensorCapability.kind`.
Covers camera-motion inputs (`*_motion_3`, `*_person_occupancy`), not only Zigbee — the incident kind.

### Acceptance (must DISCRIMINATE)
- **Verify (the incident):** a lone `on` motion/camera input, age > 2 h, all corroborators quiet ≥ 15 min →
  demoted; the room drops to unoccupied **iff** no other input is `on`. Reproduce the upstairs-hall case.
- **Verify (false-negative safety, INV-FRESH.1):** same stale sensor, but a sibling mmWave/camera in the
  room is `on` → room stays occupied (demote silences only the stale vote).
- **Verify (INV-FRESH.2 — live-but-quiet):** an mmWave holding `on` for a still body for 3 h with NO
  corroborator quiet-window met (its own presence-timeout still valid / a sibling alive) → NOT demoted.
  A motion sensor `on` for 30 min (< 2 h floor) → NOT demoted.
- **Test:** unit tests driving the room fusion with (frozen-lone / frozen-but-sibling-alive / live-still-mmwave
  / under-floor) fixtures; each mutation-anchored (remove the age check, the corroboration gate, or the
  demote wire-in → a specific test REDs).
- **Live:** after deploy, artificially-aged lone sensor demotes within a tick; a normally-occupied room is
  never demoted (spot-check `sensor.<room>_excluded_sensors` / the exclusion set does not carry a live input).

## Non-goals
- **NOT** a hard drop and **NOT** inside `_is_sensor_on` (coordinator.py:2727) — that would be an un-gated
  per-read drop and defeat the safety. Demote via the exclusion set only.
- **NOT** the zone_2 vacancy-override secondary (away-while-occupied coverage for motion-only occupancy) —
  stays carded separately.
- **NOT** touching the mmWave still-body presence-timeout or the existing continuous-on 4 h rule.

## Knob ladder
`FRESHNESS_AGE_FLOOR[kind]` = **module constants (Rung-1)** — they define a *trust* safety envelope
(clipping a live occupant is the harm), so changing them should require review; not a dashboard knob.
`CORROBORATOR_DISAGREE_S` reused (existing). A feature enable switch may be added if a kill is wanted.

## Review framings (Tier 2-DB)
- **A — correctness:** the 3-condition AND, per-kind floors match the measured p95, kind resolution, age
  math, release path.
- **B — trust/lifecycle:** INV-FRESH holds (never drops a room with a live input); no double-exclude with
  continuous-on/dutycycle; `reset_tick` interplay; restart; the camera-motion coverage.
- **C — test authority via mutation:** each of the three conditions + the demote wire-in is separately
  mutation-anchored to a named test that REDs when neutered (real fusion drive, not source-greps).
