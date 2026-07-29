# URA v5.35.3 — DeviceStatusSensor 255-char state hotfix

Tier-1. `sensor.<room>_device_status` joined all device names into the STATE; rooms
with many devices (Laundry: 10) exceeded HA's 255-char state limit → core ERROR
"longer than 255, falling back to unknown" every ~30s (~2,880 log lines/day flood,
found during a v5.35.2 error sweep). Fix: state degrades to "N devices (see
device_list)" when the join exceeds 255; the full list was already in the
`device_list` attribute (no data loss). Diagnostic-category sensor, no consumers of
the joined-string state format found.

## Validation
- H1: the repeating `sensor.laundry_device_status ... longer than 255` error STOPS
  post-restart; sensor reads "10 devices (see device_list)". 15 min.

### Validated 2026-07-29 (~00:31 CDT)
| # | Result | Evidence |
|---|---|---|
| H1 | **PASS** | `sensor.laundry_device_status` = "10 devices (see device_list)"; last "longer than 255" error timestamped 00:24:33 (pre-restart) — flood stopped. Watchdog sensor survived restart (0/healthy); zero URA errors post-boot. |
