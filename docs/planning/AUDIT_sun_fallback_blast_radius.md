# D0 — Sun-fallback blast-radius audit

Cycle: ROOM-LIGHTING-SETUP-REDESIGN-1, Slice A.
Author: builder (worktree `feature/room-lighting-roles`), 2026-09-29.
Source: prior orchestrator measurement 2026-09-29 22:2x, recorded in
`PLANNING_room_dialog_cleanup_and_lighting_roles.md:19,170`. This audit
folds that measurement into the durable artifact the plan requires as
the D1 sign-off gate.

## Rule (from plan REV 2.3, R2-3)

A room is AFFECTED by the D1 sun fallback (planned Slice B) iff BOTH:

1. `CONF_ENTRY_LIGHT_ACTION == turn_on_if_dark` — the room wants to
   light on entry only when dark; and
2. `is_dark_effective()` cannot decide from lux — the room has NO
   `CONF_ILLUMINANCE_SENSOR`, OR its sensor state is
   `unavailable` / `unknown`.

Freshness is judged by availability only (R2-3): `last_updated` age is
NEVER used, because a dark night can legitimately hold a fresh 0 for
hours.

Per-room kill switch (Slice B): `CONF_LIGHT_DARK_USE_SUN_FALLBACK`,
default **TRUE** per operator P0 ruling. Kill-switch OFF for a room
preserves today's `is_dark(None) == False` behaviour for that room.

## Prior measurement snapshot (2026-09-29 22:2x)

Read against `/Users/okosisi/ha-config/.storage/core.config_entries`
(URA room entries) + live entity reads for lux sensor availability.

| Bucket | Count | Notes |
|---|---:|---|
| Total URA room entries examined | ~40 | scope of the sweep |
| Rooms with `entry_light_action = turn_on_if_dark` and a lux sensor | 24 | today: unchanged, no fallback needed |
| Rooms with `entry_light_action = turn_on_if_dark` and NO lux sensor | 2 | AFFECTED today (will light at dusk under Slice B) |
| Rooms with `entry_light_action = turn_on_if_dark` and lux sensor currently `unavailable` | 1 | Garage B `sensor.garage_b_protect_sensor_illuminance` — AFFECTED today, will drop out of AFFECTED whenever the sensor recovers |
| **AFFECTED at probe time** | **3** | 2 no-sensor + 1 unavailable |

The unavailable bucket fluctuates as sensors drop and return (Bug Class
#7 territory — the availability-only rule is the intentional design
choice to keep the set stable across normal outages of the lux source).

## Discriminators the D1 build must satisfy (Slice B)

- Room with lux sensor at 5, threshold at 50 → dark (LUX path).
- Room with lux sensor at 500, threshold at 50 → not dark (LUX path).
- Room with lux sensor `unavailable` and sun elevation < -6° → dark
  (SUN fallback wins because lux is unavailable).
- Room with lux sensor `unavailable` and sun elevation > 0° → not dark.
- Room with NO lux sensor and sun elevation < -6° → dark (SUN
  fallback).
- Same room with `CONF_LIGHT_DARK_USE_SUN_FALLBACK=False` → NOT dark
  (kill switch preserves today).

These match `PLANNING_...md:191-196` `is_dark_effective` order and the
D1 acceptance criteria at :199-205. They are wired at BOTH
`automation.py:933` and `actuator_reconciler.py:794` per R2-2 / F2.

## Operator sign-off

D1 build (Slice B) is gated on operator ack of this AFFECTED list. The
list is expected to be small (single-digit rooms). A larger AFFECTED
list would be a signal to hand-review the entries before flipping the
default-TRUE kill switch.

Slice A ships this audit; Slice B consumes it. No behaviour change from
Slice A itself — the resolver equivalence proof is in
`quality/tests/test_lighting_resolver_equivalence.py`.
