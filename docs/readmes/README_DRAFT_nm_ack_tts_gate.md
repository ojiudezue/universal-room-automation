# DRAFT — NM ack announce honours the TTS enable switch (NM-ACK-TTS-IGNORES-DISABLE-1)

## Problem
`NotificationManager._announce_ack` (safe-word ack of a CRITICAL alert) checked only
`CONF_NM_TTS_SPEAKERS` and the dry-run gate. It ignored `CONF_NM_TTS_ENABLED`. Live
2026-10-25 00:39 CDT: `nm_tts_enabled` = False with 5 speakers configured. An ack still
tried to speak on all 5 speakers in a sleeping house. It only failed because of a separate
defect: `tts.speak` has no `tts.*` entity target. That defect is out of scope and parked as
an operator PICK.

## Change
`_announce_ack` now returns early (no `tts.speak`, no dry-run row) unless
`_channel_qualifies("tts", Severity.CRITICAL)` is true. That is the same enable+severity
check the alert path uses. Acks only exist for CRITICAL alerts, and no bucket token is
burned. When TTS is enabled, behaviour is unchanged, including the dry-run branch.
Quiet-hours/DND is not added: the alert path's global TTS predicate always admits CRITICAL
under the default bypass set, so the extra gate would never fire by default and would be
untested.

## Tests
`quality/tests/test_safeword_window.py`:
- `test_ack_announce_silent_when_tts_disabled`: no `tts.speak`, no dry-run log.
- `test_ack_announce_speaks_when_tts_enabled`: both speakers are called with the exact message.
- Mutation: removing the guard turns the disabled test RED.

## Live acceptance criteria
- With `nm_tts_enabled` False, the next safe-word ack produces no `TTS ack announcement failed`
  ERROR in system_log and no `tts.speak` service call.
