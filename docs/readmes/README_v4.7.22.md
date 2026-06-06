# v4.7.22 — Fan-noise Mode-2: room-tier BLE-gated fan pause + clean recheck

**Feature cycle (three framing-disjoint reviews + fix-up + live validation).**
Adds a room-tier state machine that detects when a ceiling/standing fan's
airflow is shaking an mmWave sensor into a false "occupied" reading, pauses the
fan, waits for airflow to spin down, and rechecks presence cleanly — dropping
occupancy only when the room is genuinely empty. Gated by a BLE corroboration
ladder (in-room phone → adjacent rooms → zone-wide) and hard-guarded against
vacating still occupants in bedrooms / media rooms. Ships with the master kill
switch **OFF** — dormant until the operator flips it on the Presence
Coordinator page.

Reviews: A = correctness + edge cases + sleep-gate, B = async / lifecycle /
race / restart resilience, C = new surfaces + test fixture authority. 2 CRITICAL
+ 4 HIGH + 4 MEDIUM all fixed in a single fix-up pass before deploy.

## The problem — fan airflow fabricates occupancy

In rooms where presence degenerates to mmWave-only (no motion / occupancy /
camera signal), a running fan's airflow periodically jiggles the mmWave sensor
enough to read "occupied" in an empty room. The room never vacates, so HVAC and
lighting stay energized and — most visibly — the fan keeps running. The earlier
v4.7.20 Layer-1 gate only *extended* occupancy (silent confidence hold/decay);
it could not actively confirm vacancy. Mode-2 is the actuation layer: it pauses
the interfering fan so mmWave can be read without airflow contamination.

## The mechanism — pause, spin down, recheck

A per-room state machine (`presence_fan_recheck.py`) runs IDLE → ARMED → PAUSED
→ COOLDOWN:

- **ARMED** after `arm_delay` of sustained mmWave-only occupancy (filters quick
  false-positives).
- **PAUSED** pauses the room's fan; mmWave is ignored for `spindown` while
  airflow stops.
- **Recheck window** observes mmWave with the fan off. If presence drops, the
  room vacates via occupancy source `fan_recheck_release`; if it holds, the room
  stays occupied and the fan resumes.
- **COOLDOWN** rate-limits rechecks (`cooldown` between, hard `max_per_hour`
  cap). HVAC fan-routing is suppressed for `hvac_suppress` after a pause so
  heat/cool doesn't immediately re-energize the fan.

### BLE corroboration ladder
Before vacating, a BLE ladder can veto: **L1** (trustworthy phone in-room),
**L2** (adjacent rooms, opt-in, *rejected* for high-still-risk room types),
**L3** (zone-wide, scans all rooms in the room's zone). An empty zone-rooms list
falls back to the room itself so an unconfigured zone can't grant a free vacate.

### High-still-risk guard
Bedrooms and media rooms (`HIGH_STILL_RISK_ROOM_TYPES`) are never vacated by the
sensors-only authorize path — a still napper would otherwise be eligible to
vacate with no BLE protection now that `trust_sensors_ok` defaults ON. The guard
fires on both the Tier-1 L2 branch and the Tier-0/2 fall-through (review C1).

### Sleep gate — don't fight v4.7.13
Both eligibility gates short-circuit when `house_state == HouseState.SLEEP`, so
Mode-2 never cycles a fan the v4.7.13 keep-fans-on-through-sleep contract is
deliberately holding on. The gate keys on SLEEP only (not WAKING) to match
hvac_fans exactly (review H1).

## Config surface (Presence Coordinator page)

Domain-correct placement: everything lives on Settings → Coordinator Manager →
**Presence Coordinator** (`async_step_coordinator_presence`).

| Surface | Key | Default |
|---|---|---|
| Master kill switch | `fan_recheck_enabled` | **OFF** |
| Per-room participate | `room_fan_recheck_enabled` | ON |
| Allow L2 adjacent authorize | `fan_recheck_l2_allowed` | ON |
| Trust sensors-only authorize | `fan_recheck_trust_sensors_ok` | ON |

Seven timing knobs (arm delay 60s, spindown 30s, recheck window 60s, cooldown
1800s, max/hour 2, HVAC suppress 600s, mmWave history ticks 3) live in a
**collapsed "Advanced" section** on the same page — moved out of the previous
Number entities. The 7 orphaned Number registry entries are removed by a
run-once cleanup migration (`__init__.py`, gated on
`fan_recheck_number_cleanup_done`).

## Reviews + fixes

Three parallel framing-disjoint reviews. Fixed before deploy:
- **C1 (CRITICAL):** high-still-risk guard missing on the Tier-0/2 path → bedroom
  nap false-vacate. Guard added.
- **C2 (CRITICAL):** dead-code overwrite of `zone_persons`; empty zone-rooms →
  free L3-vacate. Dead assignment removed, `or [room_name]` fallback added.
- **H1:** sleep gate narrowed SLEEP-only to match hvac_fans.
- **H2:** strings.json labels/descriptions added for all 7 timing fields.
- **H3:** orphan Number registry cleanup migration.
- **M-A3:** tz-naive `fromisoformat` → `dt_util.parse_datetime` + tz coercion.
- **M-C1/C3:** unused `room_coord` param removed from `_enter_armed`.
- **M-C2:** stale "Default OFF" comments corrected.

## Acceptance / live validation

- Master switch OFF → no fan-recheck state machine activity in logs.
- After flipping master ON in a fan-problem bedroom: state machine arms on
  sustained mmWave-only occupancy, pauses the fan, and either vacates (room
  empty) or resumes (occupant present) — visible via occupancy source
  `fan_recheck_release`.
- Sleep window: no Mode-2 fan cycling while `house_state == sleep`.
- The 7 legacy `number.ura_..._fan_recheck_*` entities are gone post-restart.
