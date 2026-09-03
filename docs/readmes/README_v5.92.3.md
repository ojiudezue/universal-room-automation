# v5.92.3 — HA 2026.9 compat hotfix: strip deprecated `via_device` (restores coordinator entities)

**Card:** `HA-2026-9-VIA-DEVICE-COMPAT-1`
**Tier:** 1 (hotfix — single mechanical change, definitive root cause, live outage).
**Merge:** `feature/via-device-2026-9-hotfix@260a5b9dc` → develop.

## Problem (live outage)

After the operator upgraded to **Home Assistant 2026.9**, the entire Coordinator-Manager entity set went **`unavailable`** — Battery Strategy, EV Charging, House State, Security, Energy Situation, and all coordinator numbers/switches/selects/buttons/binary_sensors. Room entities were unaffected. Diagnosis from the live instance:

- The parent config entry hit a transient `setup_error` (weather-store hydration cancelled) — recovered by a reload, but the coordinator entities stayed dead.
- The real cause: `homeassistant.components.sensor: "Error adding entity None for domain sensor with platform universal_room_automation"` — **319 occurrences**, ongoing. Traceback:
  ```
  RuntimeError: Detected code that calls device_registry.async_get_or_create
  with a deprecated `via_device` parameter; use `via_device_id` instead.
  ```
  **HA 2026.9 promoted the deprecated `via_device` parameter to a hard error.** Every URA coordinator entity declares `via_device=(DOMAIN, "coordinator_manager")` (one uses `"integration"`) in its `DeviceInfo` — **109 declarations** — so under 2026.9 each entity throws at add-time and never registers. Reloads didn't help because each reload re-runs the same failing add.

## Fix

Removed all 109 `via_device=(...)` lines from the `DeviceInfo` objects across 10 files (`time.py`, `sensor.py`, `number.py`, `button.py`, `switch.py`, `select.py`, `binary_sensor.py`, `domain_coordinators/{base,notification_manager,manager}.py`), including the shared `_energy_device_info` / `_safety_device_info` / `_security_device_info` / `_nm_device_info` / `_music_following_device_info` / `_optimizer_device_info_button` helpers. `via_device` only controlled cosmetic device-tree nesting under the CM hub; `identifiers` are unchanged, so **no device/entity re-registration and no entity_id/unique_id changes** — the entities simply add cleanly again. Devices now appear un-nested on the Devices page; proper nesting (via the non-deprecated `via_device_id` path) is a tracked cosmetic follow-up (see the device/entity architecture plan).

## Pre-deploy gate
`git diff` is **deletions-only** (109 lines, 0 insertions — nothing but `via_device` lines touched); `grep via_device=(DOMAIN` across the integration = 0; py_compile clean on all 10 files; no conflict markers.

## Acceptance criteria
- **Verify (live):** post-restart, `sensor.ura_energy_coordinator_ev_charging_status`, `sensor.ura_presence_coordinator_presence_house_state`, the battery-strategy sensor, and the security/energy-situation entities are **not `unavailable`** and carry fresh `last_updated`.
- **Verify:** `error_log` no longer shows `"Error adding entity None for domain sensor with platform universal_room_automation"` after the restart.
- **Verify:** room entities + previously-working sensors unchanged.

## Validated 2026-09-03 (post-restart)

| Criterion | Observed evidence | Result |
|---|---|---|
| Coordinator entities repopulate | `sensor.ura_presence_coordinator_presence_house_state` = **`home_day`** (was `unavailable`), fresh `last_reported` 2026-09-03T10:39:49; `sensor.ura_energy_coordinator_ev_charging_status` = **`charging`** (was `unavailable`), fresh. Both had been frozen at the 09-02 23:11 failure timestamp. | **PASS** |
| Coordinator-Manager entry healthy | entry `01KJEC3FYPYAGBQKZWC94CR8GR` = **`loaded`**. | **PASS** |
| Add-error flood stops | `error_log` post-restart: **zero new** `"Error adding entity None for domain sensor with platform universal_room_automation"` (the 301 pre-restart occurrences ended 10:18; the only post-restart add-errors are unrelated amcrest/smlight entities). | **PASS** |

Outage closed. The coordinator entity layer (energy / presence / security / optimization) is live again on HA 2026.9. Cosmetic device nesting (previously via the now-illegal `via_device`) is deferred to the device/entity architecture plan (`via_device_id` path).
