# URA v5.35.4 — NM end-to-end test button

Tier-1 (operator ask 2026-07-29). `button.ura_notification_test` ("Send Test
Notification", NM device, DIAGNOSTIC) drives `async_notify` through the FULL routing
loop — severity matrix, per-person router, DND, channel gates — unlike channel-level
tests, which bypass person routing (the gap that hid empty recipient config for weeks).
Fires at HIGH (deliberately not CRITICAL — avoids the repeat-until-ack engine);
CRITICAL-floor channels staying silent is honest routing. NM default cooldown (~10 min)
applies between presses.

Shipped alongside (options-only, no code): NM recipient wiring for the operator
(companion/iMessage/WhatsApp/Pushover — all 4 channels test-delivered), delivery_pref
→ digest + companion floor → MEDIUM (CRITICAL/HIGH stay immediate; MEDIUM — incl.
stuck-signal watchdog — batches to the 08:00 daily digest).

## Validation
- H1: clean boot; button appears on the NM device and is available once NM registers.
- H2: pressing it delivers a HIGH test notification to the companion app via the
  person router. Window: operator press.
