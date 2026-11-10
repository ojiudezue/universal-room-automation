# v5.108.2: Guest left button available after boot

Card: `GUEST-LEFT-BUTTON-READY-1` (parent `GUEST-MODE-SPLIT-VISITORS-1`). Tier 1 hotfix, one review (SHIP): `docs/reviews/code-review/v5.108.2_guest_left_button_ready.md`.

Shipped together with v5.108.3, v5.108.4 and v5.108.5 in one release and one restart (stamped v5.108.5).

## What changes

`button.ura_presence_coordinator_guest_left` was unavailable after the v5.108.1 restart. Its `available` reads the Presence Coordinator, which registers after the button platform adds the entity, and a button is never polled, so it never re-evaluated. `GuestLeftButton.async_added_to_hass` now subscribes to `SIGNAL_PRESENCE_COORDINATOR_READY` and writes its state when presence registers (`button.py`, commit 75c46282).

## Tests
- `quality/tests/test_guest_left_button.py::test_button_refreshes_when_presence_becomes_ready` (mutation drill: removing the subscription turns it RED).

## Not done (carded)
- Two buttons with the same pattern (NM mute-person, test perimeter alert) and the `super().async_added_to_hass()` call: `NM-BUTTON-READY-PATTERN-1`.

## Live validation
- **Live:** after the restart, `button.ura_presence_coordinator_guest_left` is not `unavailable`.

## Validated 2026-11-10 (restart 12:11 CST, v5.108.5 bundle)
| Criterion | Result | Evidence |
|---|---|---|
| Guest left button not unavailable after restart | PASS | `button.ura_presence_coordinator_guest_left` = `unknown` (never pressed), updated 18:12:24Z |
