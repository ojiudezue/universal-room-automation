"""P2-D3 wire-in: PresenceCoordinator._feed_residency dispatches each
residency record on SIGNAL_RESIDENCY_EVENT (the crossing ledger's
departure-reconcile feed). REAL HA core + REAL presence module (shared
sighting rig scope). Drives the enclosing method, not a helper.
"""
from __future__ import annotations

import pytest

from test_person_sighting import hass, mods  # noqa: F401 — fixture reuse


@pytest.mark.asyncio
async def test_feed_residency_dispatches_record(mods, hass):  # noqa: F811
    from homeassistant.core import State

    got: list = []

    def _cap(record):
        got.append(record)

    _cap._hass_callback = True
    unsub = mods.dispatcher.async_dispatcher_connect(
        hass, mods.signals.SIGNAL_RESIDENCY_EVENT, _cap)
    try:
        p = mods.presence.PresenceCoordinator(hass)
        p._setup_residency()
        pid = "person.oji_udezue"
        p._feed_residency(pid, State(pid, "home"), State(pid, "not_home"))
        p._feed_residency(pid, State(pid, "not_home"), State(pid, "home"))
        # Same state (attribute-only) -> no record, no dispatch.
        p._feed_residency(pid, State(pid, "home"), State(pid, "home"))
        await hass.async_block_till_done()
    finally:
        unsub()
    assert [(r.kind, r.person, r.old_state, r.new_state) for r in got] == [
        ("departure", pid, "home", "not_home"),
        ("arrival", pid, "not_home", "home"),
    ]
