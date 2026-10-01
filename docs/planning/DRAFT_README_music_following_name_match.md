# DRAFT README section — MUSIC-FOLLOWING-NO-TRANSFERS-SINCE-MAY-1

Fold into the release that merges `fix/mf-enabled-person-name-match` (5e3c13024).

## What changed
- Music Following had made no transfers since May: the "is this person enabled?" check compared a display name ("Oji Udezue") against an entity id ("person.oji_udezue"), so it never matched. The check now compares a canonical key for both forms (`_person_key`, `music_following.py`).
- The Music Following coordinator on/off switch now really stops transfers (it used to gate only the wrapper while the engine kept running). Fail-safe: if the coordinator settings can't be read, transfers are off.
- Enabled-person storage and the boot-time auto-enable dedupe by the same canonical key, so one person can no longer appear twice and an "off" preference stored under the entity id blocks a display-name auto-enable.

## Behaviour change to expect
- **Music will start following people again** for everyone enabled (it has been silently off for ~5 months). If that is not wanted, turn the Music Following coordinator switch off before deploying.

## Evidence
- Tests: `-k music` 171 passed; drills RED then restored on the kill-switch gate and the canonical dedupe.
- Reviews: A + B on the core fix SHIP (with HIGH + 2 MEDIUM fixed in the fix-up); fix-up review A SHIP (switch key/default match `switch.py:258-266`, `:695-697`).

## Known residuals (recorded on the card, not in this cycle)
- BLE bleed: one person at 0.65-0.75 confidence can pull music into a room they did not enter.
- Anomaly baseline distortion from re-recording cumulative daily rates on every skip.
- CONF_MF_COOLDOWN_SECONDS / VERIFY_DELAY / UNJOIN_DELAY are read but unused.

## Live acceptance (after deploy)
- With an enabled person moving between two rooms that have players, `music_following` logs a transfer and the target player starts within the verify delay. Discriminates: before the fix no transfer row appears at all.
