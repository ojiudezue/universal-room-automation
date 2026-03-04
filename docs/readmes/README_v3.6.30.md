# v3.6.30 — NM Diagnostic Sensors + Music Following Device Fix

**Date:** 2026-03-04
**Scope:** Hotfix — adds missing NM anomaly/diagnostic sensors, fixes Music Following device duplication

---

## Fixes

### Music Following Device Duplication
The Music Following coordinator appeared as two separate devices in HA:
- "URA: Music Following" (enable switch only)
- "URA: Music Following Coordinator" (all sensors)

**Root cause:** Device identifier mismatch in `switch.py` (`"coordinator_music_following"`) vs `sensor.py` (`"music_following_coordinator"`). All other coordinators (safety, security, presence) had matching identifiers.

**Fix:** Aligned `switch.py` to use `"music_following_coordinator"` — both platforms now produce the same device identifier, merging all entities onto one device.

### NM Missing Diagnostic Sensors
Every other domain coordinator (presence, safety, security, music following) has anomaly and compliance/diagnostic sensors. NM was missing these, creating an inconsistency.

**Added 3 new diagnostic sensors:**

| Entity | State | Attributes |
|--------|-------|------------|
| `sensor.ura_notification_anomaly` | `nominal` / `learning` / `advisory` / `alert` | dedup_suppressions, quiet_suppressions, notifications_today |
| `sensor.ura_notification_delivery_rate` | 0–100% | send_attempts, send_successes, send_failures |
| `sensor.ura_notification_diagnostics` | `healthy` / `degraded` / `disabled` | Full breakdown: by_severity, by_channel, dedup/quiet suppressions, delivery_rate |

**Anomaly detection:** Uses hourly notification volume tracking (24-slot rolling window). Flags `advisory` when current hour exceeds 3x the rolling average, `alert` at 5x.

**Delivery rate:** Analogous to the compliance sensor on other coordinators. Tracks send attempts vs successes across all channels. 100% when no attempts yet.

**Diagnostics health:** Composite health — `degraded` if any channel has 3+ consecutive failures or delivery rate drops below 80%.

### Underlying NM Tracking (notification_manager.py)
- Send attempt/success/failure counters
- Dedup and quiet-hour suppression counters
- Per-severity notification counts (LOW/MEDIUM/HIGH/CRITICAL)
- Per-channel notification counts (pushover/companion/whatsapp/tts/lights)
- 24-slot hourly volume tracking for anomaly detection

## Files Changed

| File | Change |
|------|--------|
| `switch.py` | Fix device_id `"coordinator_music_following"` → `"music_following_coordinator"` |
| `domain_coordinators/notification_manager.py` | +50 lines: diagnostic counters, properties, hourly tracking |
| `sensor.py` | +180 lines: 3 new sensor classes (NMAnomalySensor, NMDeliveryRateSensor, NMDiagnosticsSensor) + registration |
| `quality/tests/test_notification_manager.py` | +55 lines: 7 new tests for diagnostic counters |

## Testing

- 7 new tests: delivery rate, quiet/dedup suppression counting, anomaly status, diagnostics summary, severity tracking
- Full suite: 686 tests passing, 0 failures
