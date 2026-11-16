"""S3a (CHATTER-MODE-SELECT-NOT-WIRED-1): one owner for the chatter mode.

Plan: docs/planning/PLANNING_stuck_sensor_truth.md rev 2, §3 S3a.
INV-S3a: the value ``_chatter_mode()`` returns in every room equals the
select's current option (or ``off`` when the module kill const is False).

Bug classes guarded: #32 / #55 (the select wrote an entry no reader read),
#14 (stale cache after a write), #62 (no source greps: the REAL select, the
REAL room resolver and the REAL update listener are driven).

Oracles are hand-written option dicts (what the operator stored), never the
resolver's own output.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import select as sel
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators import (
    _nm_cycle_a as nma,
)

DOMAIN = ura_const.DOMAIN


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Entry:
    def __init__(self, entry_id, etype, options=None):
        self.entry_id = entry_id
        self.title = entry_id
        self.data = {ura_const.CONF_ENTRY_TYPE: etype}
        self.options = dict(options or {})


class _Hass:
    """Config entries + an ``async_update_entry`` that only persists (HA's
    real one also fires the update listener; the listener is driven
    separately so each flush site is proven on its own)."""

    def __init__(self, entries):
        self._entries = entries
        self.data = {DOMAIN: {}}
        self.created = []
        self.config_entries = SimpleNamespace(
            async_entries=lambda domain=None: list(self._entries),
            async_update_entry=self._update,
            async_reload=self._reload,
        )

    def _update(self, entry, options=None, **_kw):
        if options is not None:
            entry.options = dict(options)
        return True

    async def _reload(self, entry_id):
        return True

    def async_create_task(self, coro, *a, **k):
        self.created.append(coro)
        try:
            coro.close()
        except Exception:  # noqa: BLE001
            pass


def _integration(options=None):
    return _Entry("int1", ura_const.ENTRY_TYPE_INTEGRATION, options)


def _cm(options=None):
    return _Entry("cm1", ura_const.ENTRY_TYPE_COORDINATOR_MANAGER, options)


def _room(hass):
    room = SimpleNamespace(hass=hass)
    room._chatter_mode = UniversalRoomCoordinator._chatter_mode.__get__(room)
    return room


def _select(hass, entry):
    s = sel.ChatterModeSelect(hass, entry)
    s.hass = hass
    s.async_write_ha_state = lambda: None
    return s


@pytest.fixture
def ura_init(monkeypatch):
    """The REAL package ``__init__`` (holder of ``_async_update_listener``).

    Some sibling files leave a stub package module in ``sys.modules``; when
    that is the case, import the real one for this test only (monkeypatch
    restores the stub afterwards). Submodules stay the shared ones, so the
    listener flushes the same resolver cache the rooms read."""
    import importlib
    import sys

    name = "custom_components.universal_room_automation"
    mod = sys.modules.get(name)
    if mod is not None and hasattr(mod, "_async_update_listener"):
        return mod
    monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module(name)


@pytest.fixture(autouse=True)
def _fresh_cache():
    nma.invalidate_chatter_mode_cache()
    yield
    nma.invalidate_chatter_mode_cache()


def test_chatter_select_write_is_room_mode():
    """The select writes the integration entry; every room runs that mode.

    Live shape (11-15): integration option set by the select, CM entry has no
    key -> rooms ran the default (shadow) while the select read act.
    """
    integ = _integration({ura_const.CONF_CHATTER_MODE: "shadow"})
    hass = _Hass([integ, _cm({})])
    s = _select(hass, integ)
    _run(s.async_select_option("act"))
    assert integ.options[ura_const.CONF_CHATTER_MODE] == "act"
    room_a, room_b = _room(hass), _room(hass)
    assert room_a._chatter_mode() == "act"
    assert room_b._chatter_mode() == "act"
    assert s.current_option == "act"


def test_chatter_live_shape_select_act_cm_absent_rooms_act():
    """The exact live .storage shape: integration act, CM has no key."""
    hass = _Hass([_cm({}), _integration({ura_const.CONF_CHATTER_MODE: "act"})])
    assert _room(hass)._chatter_mode() == "act"


def test_chatter_mode_cm_fallback():
    """No integration value -> the CM entry's value (pre-D7 migrate target);
    the select shows the same value the rooms run (INV-S3a)."""
    integ = _integration({})
    hass = _Hass([integ, _cm({ura_const.CONF_CHATTER_MODE: "off"})])
    assert _room(hass)._chatter_mode() == "off"
    assert _select(hass, integ).current_option == "off"


def test_chatter_integration_wins_over_cm():
    """Config boundary: the two entries disagree -> the integration (owner)
    wins, in both directions."""
    hass = _Hass([
        _cm({ura_const.CONF_CHATTER_MODE: "act"}),
        _integration({ura_const.CONF_CHATTER_MODE: "off"}),
    ])
    assert _room(hass)._chatter_mode() == "off"
    nma.invalidate_chatter_mode_cache()
    hass = _Hass([
        _cm({ura_const.CONF_CHATTER_MODE: "off"}),
        _integration({ura_const.CONF_CHATTER_MODE: "act"}),
    ])
    assert _room(hass)._chatter_mode() == "act"


def test_chatter_invalid_integration_value_falls_back():
    hass = _Hass([
        _integration({ura_const.CONF_CHATTER_MODE: "bogus"}),
        _cm({ura_const.CONF_CHATTER_MODE: "act"}),
    ])
    assert _room(hass)._chatter_mode() == "act"


def test_chatter_no_value_anywhere_is_default_shadow():
    hass = _Hass([_integration({}), _cm({})])
    assert _room(hass)._chatter_mode() == "shadow"


def test_chatter_cache_flushed_on_select():
    """A room tick primed the cache with shadow; the select write must reach
    the next tick without a reload."""
    integ = _integration({ura_const.CONF_CHATTER_MODE: "shadow"})
    hass = _Hass([integ, _cm({})])
    room = _room(hass)
    assert room._chatter_mode() == "shadow"
    _run(_select(hass, integ).async_select_option("act"))
    assert room._chatter_mode() == "act"


def test_chatter_cache_flushed_on_integration_update_listener(ura_init):
    """An integration-entry options write from any other path (options flow,
    service) reaches rooms through the update listener's flush, and a
    chatter-only change does not reload the parent entry."""
    integ = _integration({ura_const.CONF_CHATTER_MODE: "shadow"})
    hass = _Hass([integ, _cm({})])
    hass.data[DOMAIN]["integration_last_applied_options"] = {
        integ.entry_id: dict(integ.options),
    }
    room = _room(hass)
    assert room._chatter_mode() == "shadow"
    integ.options = {ura_const.CONF_CHATTER_MODE: "act"}
    _run(ura_init._async_update_listener(hass, integ))
    assert room._chatter_mode() == "act"
    assert hass.created == [], "chatter-only change must not reload the parent"


def test_chatter_cache_flushed_on_cm_update():
    """CM fallback value changes reach rooms after the CM knob flush."""
    cm = _cm({ura_const.CONF_CHATTER_MODE: "shadow"})
    hass = _Hass([_integration({}), cm])
    room = _room(hass)
    assert room._chatter_mode() == "shadow"
    cm.options = {ura_const.CONF_CHATTER_MODE: "act"}
    nma.invalidate_knob_cache()
    assert room._chatter_mode() == "act"


def test_chatter_kill_const_short_circuits_off(monkeypatch):
    hass = _Hass([_integration({ura_const.CONF_CHATTER_MODE: "act"})])
    # Patch the const module the resolver resolves at call time (another
    # test file may have re-imported const since collection).
    import importlib
    pkg = UniversalRoomCoordinator.__module__.rsplit(".", 1)[0]
    monkeypatch.setattr(
        importlib.import_module(f"{pkg}.const"),
        "CHATTER_QUARANTINE_ENABLED", False,
    )
    assert _room(hass)._chatter_mode() == "off"


def test_chatter_lookup_error_not_cached():
    """A failing entry lookup returns the default but does not stick."""
    state = {"fail": True}
    integ = _integration({ura_const.CONF_CHATTER_MODE: "act"})

    def _entries(domain=None):
        if state["fail"]:
            raise RuntimeError("boom")
        return [integ]

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=_entries))
    room = _room(hass)
    assert room._chatter_mode() == "shadow"
    state["fail"] = False
    assert room._chatter_mode() == "act"


def test_perimeter_vlm_select_unaffected():
    """The subclass sharing ChatterModeSelect keeps its own key."""
    integ = _integration({
        ura_const.CONF_CHATTER_MODE: "act",
        ura_const.CONF_PERIMETER_VLM_GATE: "off",
    })
    hass = _Hass([integ])
    s = sel.PerimeterVlmGateSelect(hass, integ)
    s.hass = hass
    assert s.current_option == "off"


def test_chatter_entry_options_override_entry_data():
    """Review C a9: on one entry, options (what the select writes) win over
    data (merge order ``{**data, **options}``)."""
    integ = _integration({ura_const.CONF_CHATTER_MODE: "act"})
    integ.data[ura_const.CONF_CHATTER_MODE] = "shadow"
    hass = _Hass([integ, _cm({})])
    assert _room(hass)._chatter_mode() == "act"
