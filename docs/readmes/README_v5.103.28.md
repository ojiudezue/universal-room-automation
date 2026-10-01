# v5.103.28: HA no longer freezes for 2.5 minutes at every restart; garage doors are Security-only

**Cards:** `BOOT-EVENT-LOOP-FREEZE-1`, `ROOM-COVERS-NO-GARAGE-DOOR-GUARD-1`.

## Boot freeze — root cause found and fixed

The v5.103.26 loop-stall watchdog fired on the 2026-09-30 07:46 restart: `Event loop stalled >= 10.0s ... phase=boot`, total stall **153.3 s**, main-thread stack ending in
`__init__.py:2833 async_setup_entry -> bayesian_predictor.py:194 initialize -> :743 scan_data_quality`:
`seen_ts_keys = {k[0] for k in seen_timestamps[person_id]}` rebuilt a set of every earlier key for the person on every row — O(n^2) over 90 days of room transitions, on the event loop. Every one of the 12+ measured restarts had the same ~140-156 s freeze (AUDIT_db_write_worker_slow_2026_09_29.md); the DB wait warnings, Meross/ElkM1/MQTT/Protect timeouts and the boot house-state "away" window were all symptoms.

Fix: keep `seen_ts_keys_by_person` incrementally (same counts, linear time). Tests: count equivalence (duplicate vs same-second-distinct) and 30k rows < 2 s; drill: restoring the quadratic line makes the timing test fail (38 s run).

**Live:** next restart — no `Event loop stalled` WARNING (or one far shorter, naming a different site); `homeassistant_start` within ~1-2 min of shutdown instead of 5-9.

---

## Room-cover garage/gate guard

Card: `ROOM-COVERS-NO-GARAGE-DOOR-GUARD-1`
Branch: `fix/room-covers-garage-guard` (deploy HELD)
Tier: 1 (hotfix; safety guard; no config knob)

## What ships

Room-tier cover automation (`automation.py`) now refuses to open/close covers
whose `device_class` is `garage` or `gate`. Security owns those covers
(`domain_coordinators/security.py`; `hvac_covers.py` already excluded garage
from HVAC solar-gain closes). The guard runs at every room-tier cover writer
path — entry, exit, timed-open, timed-close, and sleep-block — because all
four paths route through the single choke helper `_get_available_covers`
(pre-filter) plus `_send_covers_with_verify` (defence-in-depth at dispatch).

Concretely, live rooms Garage A and Garage B listed their garage doors in
room covers with `timed_close_enabled=True`; after this ship, URA will
never dispatch `cover.open_cover` / `cover.close_cover` against them,
regardless of room config.

### Files

- `custom_components/universal_room_automation/cover_ownership.py` (new) —
  single source of truth (`SECURITY_OWNED_COVER_DEVICE_CLASSES = {"garage",
  "gate"}`), state-then-registry lookup + a registry-only variant for the
  choke point.
- `automation.py` — `_get_available_covers` filters and INFO-logs once per
  (room, cover) on first skip; `_send_covers_with_verify` filters again at
  dispatch (registry-only variant, no redundant state read).
- `domain_coordinators/hvac_covers.py::_is_garage_cover` — delegates to the
  shared helper (now also excludes `gate`, previously garage-only).

### Not shipped / non-goals

- No config knob (safety rule, rung 1 — module constant).
- Security-side cover writes untouched (`security.py` legitimately writes
  garage doors and is out of scope for this card).
- Does not change which covers are listed in a room's config; only guards
  the write path.

## Tests

Added `quality/tests/test_room_covers_garage_guard.py` (5 tests):

- `test_get_available_covers_filters_garage_and_gate` — mixed room with
  garage + gate + shade returns only the shade.
- `test_get_available_covers_logs_garage_skip_once` — INFO fires once per
  cover across repeated calls (not every tick).
- `test_send_covers_with_verify_refuses_garage_direct` — direct call to
  the choke helper skips the garage and still actuates the shade
  (one `hass.services.async_call`, for the shade).
- `test_send_covers_with_verify_all_garage_is_noop` — batch of only
  garage covers is a clean no-op, zero service calls.
- `test_shade_in_garage_room_still_actuates_via_available` — end-to-end
  through both guards, shade actuates.

### Per-site mutation drill

| Guard site | Neuter → tests red | Restore → tests green |
| --- | --- | --- |
| `_get_available_covers` (`automation.py`) — replace `is_security_owned_cover(...)` check with `False` | 3 failed: filters_garage_and_gate, logs_garage_skip_once, shade_actuates_via_available | 5/5 green |
| `_send_covers_with_verify` (`automation.py`) — replace `is_security_owned_cover_by_registry(...)` check with `False` | 2 failed: refuses_garage_direct, all_garage_is_noop | 5/5 green |

Bytecode disabled (`PYTHONDONTWRITEBYTECODE=1`) and `__pycache__` cleared
between mutations. Git status clean after restore.

## Live acceptance (post-restart, when deployed)

- Log: on the first coordinator tick, look for one INFO per Garage A /
  Garage B garage entity — `Room Garage A: skipping Security-owned cover
  cover.konnected_f0f5bd523b00_garage_door (device_class garage/gate);
  Security keeps sole control.` No log spam on subsequent ticks.
- DB: `ura_activity_log` shows zero `cover_open` / `cover_close` rows for
  Garage A / Garage B garage-door entities in the 24h following restart.
- Any co-configured shade in a garage room still actuates (dispose by
  checking activity log for the shade entity).

## Validated 2026-09-30 (08:00 restart)

| Criterion | Result | Evidence |
|---|---|---|
| No boot event-loop freeze | PASS | no `Event loop stalled` WARNING; boot to HVAC boot-settle release ~2.3 min (was 5-9 min with a 133-156 s freeze on every restart since 09-25) |
| Garage doors skipped by room covers | pending event | next sunset timed close in Garage A/B: expect the one-time skip INFO and no garage-door move by the room tier |
