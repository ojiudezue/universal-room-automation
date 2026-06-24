"""Pure helper for the humidity-venting gate decision.

This module is intentionally dependency-free (stdlib only — and not even
that). It exists so the boolean gate that fronts
`RoomAutomation.handle_humidity_based_fan_control` can be unit-tested as
a real function rather than via a test-side mirror of the inline
expression. Importing the parent package (or `coordinator.py`) pulls the
full Home Assistant dependency tree and is not viable inside the
quality/ test harness; this module imports cleanly on its own.

Tier-3 test-authority closure (see PLANNING_zone_camera_person_only_guard
and the bathroom-exhaust cycle fix-up commit): without this extraction,
mutating the inline `and` to `or` in coordinator.py left the cycle suite
green — a real reachable regression (humidity VENTING would run under
ManualMode / master-automation-OFF) was invisible to tests. Centralising
the decision here makes that mutation falsifiable by a named test.

Contract (Option-2, operator-decided):

* VENTING (turn-on, off-threshold, EMA spike, presence-runtime arming,
  sleep-policy off) is allowed ONLY on a non-skip-first tick AND while
  master automation is on.
* The max-runtime SAFETY CAP is NOT gated by this function — it fires
  universally inside the handler so a stuck fan is always force-off'd.
"""

from __future__ import annotations


def humidity_venting_enabled(
    skip_first_this_tick: bool,
    automation_enabled: bool,
) -> bool:
    """Return True iff humidity VENTING may run this tick.

    Args:
        skip_first_this_tick: The per-tick capture of the coordinator's
            ``_skip_first_automation`` flag, taken BEFORE the skip-first
            branch consumes (clears) the underlying flag. True means
            this is the first post-reload tick — anchors are being
            seeded and venting must be suppressed.
        automation_enabled: The master-automation predicate
            (``RoomCoordinator._is_automation_enabled()``). False means
            the room is in ManualMode or has master automation off.

    Returns:
        True only when BOTH gates are satisfied. The safety cap path
        in the handler bypasses this function entirely and must remain
        bypassable — do NOT inline it here.
    """
    return (not skip_first_this_tick) and automation_enabled
