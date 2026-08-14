# URA v5.75.1 — iMessage photos actually deliver + the [audit] resurrection loop dies (IMSG-IMAGE-FAIL-1)

Tier-1 batch hotfix from the operator's 2026-08-14 screenshots (WhatsApp carried alert photos —
including re-pages, organically confirming v5.73.1 L3 — while iMessage showed text-only bubbles
reading "Perimeter Alert — Person Detected\n[audit]", re-paging every 5 minutes from 4 AM to 1 PM).

## Fix A — iMessage attachment keys
`_send_imessage` sent `attachment_path` (a key the installed BlueBubbles integration never reads)
and fell back to a URL in `attachment` (which the integration validates as a local path and
raises — after the text already went out). Now mirrors the working WhatsApp leg against the
installed integration's actual schema: `attachment` = HA-local snapshot path (inside the
auto-allowed `/media` dir; no allowlist change, no new exposure), `media_url` fallback. The stale
docstring claiming the integration lacks attachment support is deleted (it was false for the
installed version — No Fabrication). **A live diagnostic send with a real snapshot proved the
corrected path end-to-end before the fix was written.**

## Fix B — the [audit] sentinel filter, actually complete this time
v5.73.0 filtered three `notification_log` readers but missed three more. The audit twin (written
~4ms after every real row) was therefore: (1) resurrected as the active alert at every boot by
`get_active_critical` → every re-page bodied "[audit]"; (2) self-sustaining — the `[ACK]` audit
row was itself unacknowledged CRITICAL, so each restart resurrected the previous ack; (3) silently
eating the operator's acks — `acknowledge_notification` flipped the twin, leaving the real row
unacked forever (the review's independent re-enumeration found this third sibling). All three now
filter the sentinel with the byte-identical sibling idiom, and `[ACK]` rows are born
`acknowledged=1` (unresurrectable by construction). No DB cleanup needed: filtered readers make
historical poisoned rows invisible; they remain for analytics.

## Acceptance criteria
- **Test:** `test_imsg_audit_fix_1.py` (9 — real writer/reader against production schema, incl.
  the 4ms-twin scenario and ack-routing), all mutation-anchored (6 drills red-then-green;
  orchestrator re-drilled the ack filter: 1 named red, restored 9/9).
- **Live:** loads, zero URA errors; post-boot `_active_alert_data` recovery selects a real-bodied
  row or none (no "[audit]" re-pages after boot).
- **Live (organic):** next security alert arrives on iMessage WITH the photo, clean body, exactly
  once per event (self-chat both-sides rendering is inherent and expected).

## Live Validation

(prospective — replaced with Validated table post-restart)
