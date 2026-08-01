# v5.44.0 — Exterior-Person Escalation

## What shipped
Perimeter person detections now route through the NotificationManager as hazard
class `exterior_person` with HOUSE-STATE-CONDITIONAL severity:
- away / vacation / sleep / home_night → **CRITICAL** (bypasses DND; reaches
  iMessage/WhatsApp/Pushover/companion) with a camera snapshot attached
- guest → MEDIUM · home_day / home_evening / arriving / waking → LOW (digest)
- unknown/error → CRITICAL (fail-safe, incl. on resolver exceptions)

Snapshots prefer the Frigate detection-time event frame (via the notification
proxy) — sidestepping propagation lag — with a live-snapshot fallback delayed by
`exterior_snapshot_offset_s` (options flow, default 5s, 0–60). NOTE: the Frigate
integration publishes events on MQTT only; a small MQTT→event bridge automation
(created at deploy) activates the event-frame path. URLs are normalized absolute
(external_url) so Pushover/WhatsApp attachments actually load.

Safety/robustness from review: boot rising-edge-only + 30s settle gate (no
spurious CRITICAL pages on restart), cooldown reserved only AFTER successful
dispatch (a failed send can never mute a camera), person-label-filtered event
snapshots (no car pictures on person alerts), teardown-safe delayed dispatch.
Per-camera 5-min cooldown + egress suppression + alert-hours preserved; legacy
notify-service knob honored as deprecated fallback.

## Documented trade-off
During a quiet-hours window that overlaps home_evening, exterior alerts are LOW
and thus DND-held until the digest — intentional (deliveries), noted for clarity.

## Review
docs/reviews/code-review/exterior_person_escalation_tier2.md — 3 reviews +
orchestrator; 4 HIGH found+fixed incl. a Bug Class #62 test-replica catch.

## Live Validation — prospective
- **Live:** trigger a perimeter camera while house away → ONE CRITICAL on phone
  channels with a loading snapshot; second trigger within 5 min suppressed.
- **Live:** restart HA → zero exterior_person alerts in the boot window.
- **Live:** while home_day, a perimeter person → digest row only, no page.
