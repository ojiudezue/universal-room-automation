# v5.108.7 — NM buttons refresh when the Notification Manager is ready

Card: NM-BUTTON-READY-PATTERN-1 (Tier 1 hotfix). Follows GUEST-LEFT-BUTTON-READY-1 (v5.108.2, commit 75c46282).

## Problem

Buttons are never polled. Two Notification Manager buttons compute `available` from
`hass.data[DOMAIN]["notification_manager"]`, which `__init__.py` sets after the button
platform has added them. Without a refresh, they could stay `unavailable` after boot
(the same defect the Guest left button had):

- NM mute-person button (`NMMutePersonChannelPrimaryButton`)
- Send Test Perimeter Alert button (`SendTestPerimeterAlertButton`)

## Change

- Both buttons subscribe in `async_added_to_hass` to the existing `SIGNAL_NM_READY`
  (`domain_coordinators/signals.py:78`, dispatched at `__init__.py:4590` right after
  `hass.data[DOMAIN]["notification_manager"] = nm`) and call `async_write_ha_state()`
  when it fires. The subscription is registered with `self.async_on_remove(...)`.
  This is the same pattern `NMAcknowledgeButton` and `NMTestNotificationButton` already use.
- `GuestLeftButton.async_added_to_hass` and the two new handlers now call
  `super().async_added_to_hass()`.
- No new signal, constant, or knob.

## Tests

- `quality/tests/test_nm_button_ready.py` (new): for each button, unavailable after
  `async_added_to_hass`, subscription on `SIGNAL_NM_READY` handed to `async_on_remove`,
  then available (state written) once NM registers and the signal fires. Also pins both unique_ids.
- `quality/tests/test_guest_left_button.py`: the ready-signal test now also asserts the
  subscription handle is passed to `async_on_remove`.
- Mutation drills (each restored, `git status` clean): neutering the mute subscription,
  the perimeter subscription, and the Guest left `async_on_remove` wrapper each turned
  exactly one named test RED.

## Live acceptance

After restart, both buttons are NOT `unavailable`:

- Send Test Perimeter Alert: unique_id `universal_room_automation_send_test_perimeter_alert`
  (expected entity_id `button.ura_notification_manager_send_test_perimeter_alert` from
  has_entity_name + device "URA: Notification Manager"; the class docstring says
  `button.ura_send_test_perimeter_alert`; confirm in the entity registry by unique_id).
- Mute person buttons: unique_id `universal_room_automation_nm_mute_<person_id with . and : as _>_<channel>`,
  e.g. `universal_room_automation_nm_mute_person_oji_imessage` (find by unique_id prefix
  `universal_room_automation_nm_mute_`).
- Guest left (`button.ura_presence_coordinator_guest_left`) still not `unavailable`.

## Validated 2026-11-10 (restart ~18:40 CST, v5.108.7 via HACS, house away)
| Criterion | Result | Evidence |
|---|---|---|
| Test perimeter alert button available after boot | PASS | `button.ura_notification_manager_send_test_perimeter_alert` = `unknown` (never pressed) at 18:41; was `unavailable` after the 17:52 v5.108.6 restart |
| NM mute-person button available after boot | PASS | `button.ura_notification_manager_mute_person_oji_udezue_pushover` = `unknown` at 18:41; was `unavailable` after 17:52 |
| Guest left button still available | PASS | `button.ura_presence_coordinator_guest_left` = `unknown` |
| Load clean | PASS | system_log: 0 URA ERROR entries |

Pre-ship gate: full suite on merged develop 18 failed / 20,483 passed, failure names identical to v5.108.6 (+3 passes). Review: `docs/reviews/code-review/v5.108.7_nm_button_ready.md` (SHIP).
