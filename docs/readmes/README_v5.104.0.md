# v5.104.0 — Ask the house by text: `diag` menu over iMessage / WhatsApp / HA app

**Card:** NM-INBOUND-HOUSE-QUERIES-1 (option A). **Tier:** 2, elevated to three framing-disjoint reviews
because the change sits in the single parser that handles CRITICAL acks.
**Plan:** `docs/planning/PLANNING_nm_diag_text_menu.md` rev 2. **Reviews:** plan review 1; code reviews A
(correctness), B (async/race), C (per-site mutation) in `docs/reviews/code-review/nm_diag_text_menu_*`.

## Why
The Notification Manager already received replies (ack / status / silence / safe word) but could not
answer questions. Operator 2026-11-07: query house state and run simple diagnostics by text, with a
`diag` command that returns a numbered menu.

## What's new
- **`diag`** (also `menu`, `house`) replies with a 7-item menu: doors, garage, who, hvac, energy, alerts, health.
  Reply with the number inside the 120 s menu window, or text a name (`doors`, `garage`, …) any time.
- **New read-only module `house_status.py`.** Pure reads that return structured fields with their source
  entity plus a short text render (≤900 chars). The OC agent can reuse these as tools later.
- **Safety rails for the alert reply digits** (1 = Ack, 2 = Status, 3 = Silence keep their meaning):
  - While any alert is active, digits keep the legacy meaning and `diag` shows a words-only menu.
  - Every outbound send closes all open menu windows, before and after the send.
  - A digit sent shortly after an alert closed the window gets "Menu closed — reply diag to reopen".
  - Diag replies neither check nor stamp the 30 s reply floor, so a safe-word confirmation is never dropped.
  - Diag has its own budget: 10 replies / 10 min per person and channel.
- **WhatsApp inbound fixed.** It had been silently dropped: NM read `phone`/`message`, the bridge sends
  `from`/`body`. WhatsApp now accepts commands from the operator's own self-chat only (the bridge runs on
  the operator's number, so every other direct chat is personal conversation). Groups, newsletters and
  broadcasts are ignored, and replays within 600 s are dropped.
- **HA app (Companion) replies now answer.** The sender is resolved from the app's logged-in user. Replies
  carry no action buttons (no one-tap Acknowledge on a status reply).

## Knobs (rung 1, module constants)
| Constant | Default | Kill switch |
|---|---|---|
| `NM_DIAG_ENABLED` | True | False restores pre-cycle inbound behaviour for diag |
| `NM_WHATSAPP_INBOUND_ENABLED` | True | False ignores all WhatsApp inbound |
| `NM_WHATSAPP_DEDUP_TTL_S` | 600 | 0 disables replay dedup |
| Menu window | 120 s | 0 = names only |
| `NM_DIAG_CLOSED_NOTICE_S` | 300 | 0 disables the notice |

## Tests
Cycle files `test_house_status.py`, `test_nm_diag_menu.py`, `test_nm_diag_dispatch.py`,
`test_nm_inbound_whatsapp.py`, `test_nm_inbound_companion.py`. Review C re-drilled 43 sites independently;
the three untested sites it found now have tests that go red. The full suite has the same 14 failures as
develop and no new ones.

## Known limits
- The WhatsApp bridge has never forwarded a message the operator sent (0 of 1,704 events had `fromMe`),
  so WhatsApp commands may stay dark. iMessage is the live channel.
- `doors` lists Security-coordinator locks (now front + garage hallway; master bedroom removed pending
  SC-LOCK-SWEEP-EXCLUDE-1) plus both garage remote lockouts read directly.
- `health` covers 21 of 47 rooms (26 unavailable-entities sensors are disabled by default).

## Live validation (to run after restart)
- Text `diag` over iMessage → numbered menu arrives; reply `1` → doors answer.
- Text `hvac`, `energy`, `who`, `health` → answers with live values matching HA.
- With no alert active, `3` inside the window → `who`; outside the window → legacy silence path.
- `notification_inbound` rows for each query with channel `imessage`.
- Send `diag` in the operator WhatsApp self-chat → does a `channel='whatsapp'` row appear? (records the
  bridge fromMe question either way).
- Tap Status in the HA app → a reply with no buttons.
- Core log: no NM exceptions after boot.
