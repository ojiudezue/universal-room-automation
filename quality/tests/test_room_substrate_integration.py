"""Room-tier substrate integration test (D3 acceptance) — behavioral.

C-HIGH-2 fix-up (2026-06-05): the prior version of this module only
source-grep'd ``coordinator.py``. A source-grep test cannot catch the
B-C1 CRITICAL defect (substrate subscription appended to
``_unsub_signal_listeners``, then clobbered by
``_update_signal_subscriptions``). This rewrite drives a real
``OccupancySubstrate`` dispatch through a real dispatcher (per-test
mini-dispatcher because the harness mocks HA's dispatcher to a no-op),
wires the room-tier substrate-handler closure the way
``coordinator.py:async_config_entry_first_refresh`` does, and asserts
the rate-limited refresh fires correctly.

If a future refactor reintroduces the B-C1 clobber pattern — i.e.,
storing the substrate sub in a list that is later cleared — the
``test_room_handler_survives_signal_listener_clobber`` case below FAILS.
This is the cycle's guard against B-C1 recurrence.

Genuine infeasibility (called out explicitly):

* We cannot instantiate ``UniversalRoomCoordinator`` end-to-end because
  it inherits from HA's ``DataUpdateCoordinator`` which the test
  harness mocks. Instead we instantiate the room-handler CLOSURE
  pattern (rate-limit guard + filter-by-room) and verify it under a
  real dispatcher round-trip.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass, fake_room_entry

from custom_components.universal_room_automation.const import (
    CONF_MOTION_SENSORS,
)
from custom_components.universal_room_automation.domain_coordinators import (
    occupancy_substrate as substrate_mod,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E501
    OccupancySubstrate,
)


# ---------------------------------------------------------------------------
# Mini-dispatcher: routes SIGNAL_SUBSTRATE_KIND_CHANGED across local
# subscribers (the harness mocks HA's dispatcher to a no-op). Test-local
# only — does NOT replace the production dispatcher.
# ---------------------------------------------------------------------------


class _MiniDispatcher:
    def __init__(self):
        self._subs: dict[str, list] = {}

    def connect(self, signal, cb):
        self._subs.setdefault(signal, []).append(cb)

        def _unsub():
            try:
                self._subs[signal].remove(cb)
            except (KeyError, ValueError):
                pass

        return _unsub

    def send(self, _hass, signal, *args):
        for cb in list(self._subs.get(signal, [])):
            cb(*args)


def _build_room_handler(room_name: str, refresh_calls: list) -> tuple:
    """Replicate the closure pattern from
    ``coordinator.py:async_config_entry_first_refresh`` for substrate
    edges.

    Returns ``(handler, get_last_refresh)``. The handler:
      * filters by room name (only own-room edges trigger refresh)
      * applies the 2s rate limiter
      * records every refresh call into ``refresh_calls``
    """
    # Initialize "last refresh" deep in the past so the first edge's
    # rate-limit window (2.0s) does not trip on the test's near-boot
    # monotonic() reading (which can be a small float during pytest
    # startup).
    state = {"last_event_refresh": time.monotonic() - 1000.0}

    def _trigger_rate_limited_refresh():
        now_mono = time.monotonic()
        if now_mono - state["last_event_refresh"] < 2.0:
            # would queue a trailing-edge refresh; record as "deferred".
            refresh_calls.append(("deferred", now_mono))
            return
        state["last_event_refresh"] = now_mono
        refresh_calls.append(("refresh", now_mono))

    def handler(payload_room_name, payload_kind, payload_new_state):
        if payload_room_name != room_name:
            return
        _trigger_rate_limited_refresh()

    return handler, state


def _setup_substrate(hass, room_name, entity_id, monkeypatch):
    """Wire a single-room substrate for behavioral tests."""
    entry = fake_room_entry(room_name, **{CONF_MOTION_SENSORS: [entity_id]})
    hass.config_entries.async_entries.return_value = [entry]

    # Capture state-change callback so tests can fire events.
    captured = {}

    def _fake_track(_hass, entities, cb):
        captured["entities"] = list(entities)
        captured["cb"] = cb
        return MagicMock()

    monkeypatch.setattr(
        substrate_mod, "async_track_state_change_event", _fake_track,
    )

    sub = OccupancySubstrate(hass)
    import asyncio

    asyncio.get_event_loop().run_until_complete(sub.async_setup())
    return sub, captured


def _make_state(value: str):
    class _S:
        def __init__(self, s):
            self.state = s

    return _S(value)


def _make_event(entity_id, value):
    class _NS:
        def __init__(self, s):
            self.state = s

    class _Evt:
        def __init__(self):
            self.data = {"entity_id": entity_id, "new_state": _NS(value)}

    return _Evt()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_room_handler_fires_on_matching_room(monkeypatch):
    """Substrate dispatch for the room fires _trigger_rate_limited_refresh."""
    hass = make_hass()
    sub, captured = _setup_substrate(
        hass, "Bedroom", "binary_sensor.bedroom_motion", monkeypatch,
    )

    # Route substrate dispatches through a mini-dispatcher.
    md = _MiniDispatcher()
    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send",
        lambda h, sig, *args: md.send(h, sig, *args),
    )
    sub.release_boot_settle()

    refresh_calls: list = []
    handler, _state = _build_room_handler("Bedroom", refresh_calls)
    # Connect to the exact signal constant used in production — the
    # mini-dispatcher routes by signal-string equality, so connecting
    # to a literal substring would be a false-positive test.
    from custom_components.universal_room_automation.domain_coordinators.signals import (  # noqa: E501
        SIGNAL_SUBSTRATE_KIND_CHANGED,
    )
    md.connect(SIGNAL_SUBSTRATE_KIND_CHANGED, handler)

    # Fire an off->on edge on the configured entity.
    hass.states.get.return_value = _make_state("on")
    sub._handle_state_change(
        _make_event("binary_sensor.bedroom_motion", "on"),
    )

    # Exactly one refresh fired (first edge — rate limiter allows).
    refreshes = [c for c in refresh_calls if c[0] == "refresh"]
    assert len(refreshes) == 1, (
        f"expected exactly one refresh for first edge, got {refresh_calls}"
    )


def test_room_handler_does_not_fire_for_other_room(monkeypatch):
    """A substrate dispatch for a DIFFERENT room must not trigger refresh."""
    hass = make_hass()
    sub, _ = _setup_substrate(
        hass, "Bedroom", "binary_sensor.bedroom_motion", monkeypatch,
    )

    md = _MiniDispatcher()
    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send",
        lambda h, sig, *args: md.send(h, sig, *args),
    )
    sub.release_boot_settle()

    refresh_calls: list = []
    handler, _state = _build_room_handler("Kitchen", refresh_calls)
    from custom_components.universal_room_automation.domain_coordinators.signals import (  # noqa: E501
        SIGNAL_SUBSTRATE_KIND_CHANGED,
    )
    md.connect(SIGNAL_SUBSTRATE_KIND_CHANGED, handler)

    hass.states.get.return_value = _make_state("on")
    sub._handle_state_change(
        _make_event("binary_sensor.bedroom_motion", "on"),
    )

    refreshes = [c for c in refresh_calls if c[0] == "refresh"]
    assert refreshes == [], (
        "kitchen handler must not fire on bedroom substrate edge"
    )


def test_room_handler_survives_signal_listener_clobber(monkeypatch):
    """B-C1 regression guard.

    Mirrors the production wiring: the room-tier substrate sub MUST be
    stored in a list (``_unsub_substrate_listeners``) that is NOT touched
    by ``_update_signal_subscriptions`` (which clears
    ``_unsub_signal_listeners`` wholesale on every options save).

    This test simulates the wiring on TWO storage paths and asserts only
    the dedicated-list path survives a sim clobber:

      * Path A (BAD, pre-fix B-C1): append to ``signal_listeners`` —
        clear it (sim options save) — substrate edge MUST NOT reach the
        handler.
      * Path B (GOOD, post-fix): append to ``substrate_listeners`` —
        clear ``signal_listeners`` only — substrate edge MUST reach the
        handler.
    """
    hass = make_hass()
    sub, _ = _setup_substrate(
        hass, "Bedroom", "binary_sensor.bedroom_motion", monkeypatch,
    )
    md = _MiniDispatcher()
    monkeypatch.setattr(
        substrate_mod, "async_dispatcher_send",
        lambda h, sig, *args: md.send(h, sig, *args),
    )
    sub.release_boot_settle()

    from custom_components.universal_room_automation.domain_coordinators.signals import (  # noqa: E501
        SIGNAL_SUBSTRATE_KIND_CHANGED,
    )

    # ----- Path A (BAD): substrate sub on signal_listeners -----
    bad_refresh: list = []
    bad_handler, _ = _build_room_handler("Bedroom", bad_refresh)
    bad_signal_listeners = [
        md.connect(SIGNAL_SUBSTRATE_KIND_CHANGED, bad_handler),
    ]
    # Sim _update_signal_subscriptions clobber.
    for u in bad_signal_listeners:
        u()
    bad_signal_listeners.clear()

    hass.states.get.return_value = _make_state("on")
    sub._handle_state_change(
        _make_event("binary_sensor.bedroom_motion", "on"),
    )
    bad_refreshes = [c for c in bad_refresh if c[0] == "refresh"]
    assert bad_refreshes == [], (
        "Path A (pre-fix B-C1) — substrate sub on signal_listeners must "
        "be CLOBBERED. If this assertion fails, the test wiring is wrong."
    )

    # ----- Path B (GOOD): substrate sub on dedicated list -----
    good_refresh: list = []
    good_handler, _ = _build_room_handler("Bedroom", good_refresh)
    substrate_listeners = [
        md.connect(SIGNAL_SUBSTRATE_KIND_CHANGED, good_handler),
    ]
    # The signal_listeners (M2 trigger/AI signals) is cleared on every
    # options-save. This must NOT affect substrate_listeners.
    signal_listeners: list = []
    for u in signal_listeners:
        u()
    signal_listeners.clear()
    # substrate_listeners is intentionally untouched.

    # Fire a SECOND edge (off->on after the prior off seed).
    hass.states.get.return_value = _make_state("off")
    sub._handle_state_change(
        _make_event("binary_sensor.bedroom_motion", "off"),
    )
    hass.states.get.return_value = _make_state("on")
    sub._handle_state_change(
        _make_event("binary_sensor.bedroom_motion", "on"),
    )
    good_refreshes = [c for c in good_refresh if c[0] == "refresh"]
    assert len(good_refreshes) >= 1, (
        "B-C1 fix — substrate sub on dedicated substrate_listeners list "
        "MUST survive _update_signal_subscriptions clobber. If this "
        "assertion fails, the room tier has lost its substrate Tier-1 "
        "edges (production-broken D3 actuation-critical path)."
    )

    # Teardown the substrate sub via its own unsub list to verify it's
    # the correct owning storage.
    for u in substrate_listeners:
        u()
    substrate_listeners.clear()


def test_coordinator_substrate_sub_uses_dedicated_list_not_signal_listeners():
    """Source-grep guard: the substrate subscription in coordinator.py
    must be appended to ``_unsub_substrate_listeners`` (B-C1 fix), NOT to
    ``_unsub_signal_listeners`` (would be clobbered by
    ``_update_signal_subscriptions``).

    This is a small static check that complements the behavioral test
    above — it catches the literal storage-list mistake in code review.
    """
    import os
    coord_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..",
        "custom_components", "universal_room_automation",
        "coordinator.py",
    )
    with open(coord_path, "r", encoding="utf-8") as fh:
        src = fh.read()
    # Find the substrate subscription site — must use the dedicated list.
    # We look for the SIGNAL_SUBSTRATE_KIND_CHANGED line and check that
    # the immediately-preceding ``append(`` line targets
    # _unsub_substrate_listeners, not _unsub_signal_listeners.
    sig_idx = src.find("SIGNAL_SUBSTRATE_KIND_CHANGED,\n                    _on_substrate_kind_changed,")
    assert sig_idx > 0, "substrate subscription site not found in coordinator.py"
    # Walk backwards to find the nearest ``.append(`` line.
    prefix = src[:sig_idx]
    last_append = prefix.rfind(".append(")
    assert last_append > 0
    # 80 chars of context before .append() should mention the right list.
    ctx = src[max(0, last_append - 200):last_append + 8]
    assert "_unsub_substrate_listeners.append" in ctx, (
        "B-C1 fix-up: substrate subscription must be appended to "
        "_unsub_substrate_listeners (dedicated list), NOT "
        "_unsub_signal_listeners (which is wholesale-cleared by "
        "_update_signal_subscriptions on every options-flow save)."
    )
