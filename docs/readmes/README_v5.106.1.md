# v5.106.1 — WhatsApp sends via ha-wa-bridge 3.x (`wa_bridge`)

**Card:** WA-BRIDGE-DOMAIN-1. **Tier:** 1 (hotfix, one review).

## Why
ha-wa-bridge 3.0.0 renamed its Home Assistant domain from `whatsapp` to `wa_bridge`, and 3.1.0 made the
bridge add-on require an API token. The 2.x integration has no token field, so after the add-on update it
gets HTTP 401 and every URA WhatsApp send failed. The operator installed and configured `wa_bridge` 3.1.1
(2026-11-08) and keeps the 2.x entry until 3.x is validated.

## What changed
- `_send_whatsapp` sends through the first domain in `NM_WHATSAPP_SERVICE_DOMAINS` = (`wa_bridge`,
  `whatsapp`) whose `send_message` service is registered, so it uses 3.x while both are installed and
  still works on a 2.x-only install. If neither is registered it calls `whatsapp` and the failure is logged
  and marked in channel health, as before.
- Payload fields are unchanged (`number`, `message`, `media_path` / `media_url`). Inbound is unchanged:
  3.x keeps the `whatsapp_*_received` event names.

## Knobs
`NM_WHATSAPP_SERVICE_DOMAINS` (rung 1, module constant): preference order.

## Tests
`test_nm_inbound_whatsapp.py::test_send_uses_wa_bridge_domain_when_registered` (4 cases). Reversing the
tuple turns 2 red. The diag/golden harness models a 2.x-only install so the merge-base goldens stay
byte-identical. Full suite: no new failures against develop (one known order-dependent Frigate snapshot
test flakes and passes in isolation).

## Live validation (after restart)
- A URA WhatsApp send (an NM test notification) arrives, and the core log shows no `WhatsApp send failed`.
- `wa_bridge` add-on log shows the handshake accepted (no 401).
- After the operator removes the 2.x entry, sends still arrive.

## Validated 2026-11-08 (post-restart 11:00 CST)
| Criterion | Result | Evidence |
|---|---|---|
| URA WhatsApp send arrives | PASS | `universal_room_automation.test_notification` (channel `whatsapp`, LOW) after restart; operator confirmed receipt |
| No `WhatsApp send failed` in core log | PASS | system_log (current boot): no NM WhatsApp errors; only the 2.x client's 401s (`custom_components.whatsapp.client`), expected while the old entry exists |
| Bridge accepts 3.x | PASS | direct `wa_bridge.send_message` to the operator succeeded earlier (operator confirmed) |
| Sends survive removal of the 2.x entry | PENDING | operator removes the 2.x entry when ready; code falls back only when `wa_bridge` is absent (tests) |
| Inbound WhatsApp reaches `_handle_whatsapp_reply` | NOT RUN | needs an operator self-chat message; event name unchanged in 3.x per upstream notes |
