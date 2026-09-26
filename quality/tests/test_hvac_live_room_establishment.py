"""HVAC-DEGRADED-ROOM-TRIPWIRE-1 — live-room establishment tests.

Drives the REAL ZoneManager code path against real HA
`ConfigEntryState` / `ConfigEntryDisabler` enums (per REV-2 F13:
"Import ConfigEntryState from HA (never hand-copy)"). Clock is
patched via `unittest.mock.patch` on `homeassistant.util.dt.utcnow`
as imported by `hvac_zones` — there is no clock seam; the module
calls `dt_util.utcnow()` directly.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Ensure the repo root is importable so we can load custom_components.*
# via its real package path — no HA stubs, no sys.modules mutation
# beyond the standard sys.path prepend.
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Real HA imports — the .venv-ha interpreter carries a real
# homeassistant installation; REV-2 F13 requires importing enum
# members from HA, never hand-copying.
from homeassistant.config_entries import (  # noqa: E402
    ConfigEntryState,
    ConfigEntryDisabler,
)

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_zones as _hvac_zones,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E402
    HVAC_LIVE_ROOM_TRANSIENT_GRACE_S,
)


ZoneManager = _hvac_zones.ZoneManager
ZoneState = _hvac_zones.ZoneState
RoomCondition = _hvac_zones.RoomCondition


NOW = datetime(2026, 9, 26, 3, 0, 0, tzinfo=timezone.utc)


class _FakeEntry:
    """Minimal config-entry surface used by ZoneManager classifier."""

    def __init__(
        self,
        room_name: str,
        state: ConfigEntryState = ConfigEntryState.LOADED,
        disabled_by: ConfigEntryDisabler | None = None,
        entry_id: str | None = None,
    ) -> None:
        self.entry_id = entry_id or f"e_{room_name}"
        self.state = state
        self.disabled_by = disabled_by
        self.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: room_name,
        }
        self.options: dict = {}


def _mk_zm(
    entries: list[_FakeEntry] | None = None,
    coordinators: dict[str, object] | None = None,
) -> ZoneManager:
    """Build a ZoneManager whose hass exposes the given ROOM entries."""
    hass = MagicMock()

    class _CEs:
        def async_entries(self, dom):
            return list(entries or [])

    hass.config_entries = _CEs()
    hass.data = {DOMAIN: dict(coordinators or {})}
    hass.states = MagicMock()
    hass.states.get = lambda ent_id: None
    return ZoneManager(hass)


def _seed_room_class(
    zm: ZoneManager,
    room_name: str,
    kind: str,
    reason: str = "",
) -> None:
    """Directly seed classifier output for a room — for tests that
    exercise `is_zone_hvac_established` without driving the full
    producer."""
    zm._hvac_classification_ready = True
    zm._room_hvac_class[room_name] = (kind, reason)


# ---------------------------------------------------------------------------
# D1 — _live_zone_rooms / classification
# ---------------------------------------------------------------------------


def test_live_zone_rooms_excludes_disabled_by_user():
    zm = _mk_zm(entries=[
        _FakeEntry("r_live", state=ConfigEntryState.LOADED),
        _FakeEntry(
            "r_disabled", state=ConfigEntryState.NOT_LOADED,
            disabled_by=ConfigEntryDisabler.USER,
        ),
    ])
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_live", "r_disabled"]
    zm._zones["z1"] = zone
    zm.update_room_conditions(house_state="home_day")
    excluded, transient, live = zm._classify_zone_rooms(zone)
    assert live == ["r_live"]
    assert transient == []
    names = [e["name"] if isinstance(e, dict) else e for e in excluded]
    assert "r_disabled" in names
    assert zm._room_hvac_class["r_disabled"][1] == "disabled_by_user"


def test_live_zone_rooms_excludes_disabled_by_integration():
    # HA only ships ConfigEntryDisabler.USER today, but the classifier
    # must map any non-USER value to `disabled_by_integration`. Simulate
    # via a stub disabler object with `.value != "user"`.
    class _Fake:
        value = "integration"
        def __str__(self): return "integration"

    zm = _mk_zm(entries=[
        _FakeEntry("r_live", state=ConfigEntryState.LOADED),
        _FakeEntry("r_dis_int", state=ConfigEntryState.NOT_LOADED,
                   disabled_by=_Fake()),
    ])
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_live", "r_dis_int"]
    zm._zones["z1"] = zone
    zm.update_room_conditions(house_state="home_day")
    assert zm._room_hvac_class["r_dis_int"] == (
        "excluded", "disabled_by_integration",
    )


def test_live_zone_rooms_all_dead_returns_empty():
    zm = _mk_zm(entries=[
        _FakeEntry("r_a", state=ConfigEntryState.SETUP_ERROR),
        _FakeEntry("r_b", disabled_by=ConfigEntryDisabler.USER),
    ])
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_a", "r_b"]
    zm._zones["z1"] = zone
    zm.update_room_conditions(house_state="home_day")
    assert zm._live_zone_rooms(zone) == []


def test_zone_all_rooms_disabled_stays_unestablished():
    zm = _mk_zm(entries=[
        _FakeEntry("r_a", disabled_by=ConfigEntryDisabler.USER),
    ])
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_a"]
    zm._zones["z1"] = zone
    zm.update_room_conditions(house_state="home_day")
    assert zm.is_zone_hvac_established("z1") is False


# ---------------------------------------------------------------------------
# Grace-window boundary (NOT_LOADED, per REV-2 F5 replacement of SETUP_RETRY)
# ---------------------------------------------------------------------------


def _patched_now(dt: datetime):
    """Patch dt_util.utcnow/now as imported by hvac_zones (no clock seam)."""
    return patch.object(_hvac_zones.dt_util, "now", return_value=dt), \
           patch.object(_hvac_zones.dt_util, "utcnow", return_value=dt)


def test_live_zone_rooms_blocks_not_loaded_within_grace():
    entries = [_FakeEntry("r_x", state=ConfigEntryState.NOT_LOADED)]
    zm = _mk_zm(entries=entries)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_x"]
    zm._zones["z1"] = zone

    p1, p2 = _patched_now(NOW)
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    kind, _ = zm._room_hvac_class["r_x"]
    assert kind == "transient"

    # Advance 60s (< grace 300s) — still transient.
    p1, p2 = _patched_now(NOW + timedelta(seconds=60))
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    assert zm._room_hvac_class["r_x"][0] == "transient"


def test_live_zone_rooms_excludes_not_loaded_past_grace():
    entries = [_FakeEntry("r_x", state=ConfigEntryState.NOT_LOADED)]
    zm = _mk_zm(entries=entries)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_x"]
    zm._zones["z1"] = zone

    p1, p2 = _patched_now(NOW)
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    p1, p2 = _patched_now(
        NOW + timedelta(seconds=HVAC_LIVE_ROOM_TRANSIENT_GRACE_S + 1)
    )
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    assert zm._room_hvac_class["r_x"][0] == "excluded"


def test_transient_room_recovers_after_load_clears_grace():
    entries = [_FakeEntry("r_x", state=ConfigEntryState.NOT_LOADED)]
    zm = _mk_zm(entries=entries)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_x"]
    zm._zones["z1"] = zone

    p1, p2 = _patched_now(NOW)
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    assert "r_x" in zm._room_non_loaded_since

    # Flip to LOADED — grace timer must clear.
    entries[0].state = ConfigEntryState.LOADED
    p1, p2 = _patched_now(NOW + timedelta(seconds=60))
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    assert "r_x" not in zm._room_non_loaded_since
    assert zm._room_hvac_class["r_x"] == ("live", "loaded")


# ---------------------------------------------------------------------------
# SETUP_RETRY — REV-2 F5 immediate-exclude
# ---------------------------------------------------------------------------


def test_setup_retry_room_excluded_immediately():
    entries = [_FakeEntry("r_x", state=ConfigEntryState.SETUP_RETRY)]
    zm = _mk_zm(entries=entries)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_x"]
    zm._zones["z1"] = zone
    zm.update_room_conditions(house_state="home_day")
    assert zm._room_hvac_class["r_x"] == ("excluded", "setup_retry")


# ---------------------------------------------------------------------------
# Diag surface (REV-2 D3)
# ---------------------------------------------------------------------------


def test_diag_reports_excluded_disabled_room():
    entries = [
        _FakeEntry("r_live", state=ConfigEntryState.LOADED),
        _FakeEntry(
            "r_dis", state=ConfigEntryState.NOT_LOADED,
            disabled_by=ConfigEntryDisabler.USER,
        ),
    ]
    zm = _mk_zm(entries=entries)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_live", "r_dis"]
    zm._zones["z1"] = zone
    zm.update_room_conditions(house_state="home_day")
    attrs = zm.get_zone_status_attrs("z1")
    assert attrs["live_rooms"] == ["r_live"]
    excluded = attrs["excluded_rooms"]
    assert any(e["name"] == "r_dis" for e in excluded)
    assert any(
        e["reason"] == "disabled_by_user" for e in excluded
        if e["name"] == "r_dis"
    )


# ---------------------------------------------------------------------------
# AM-1 — reloading room previously in _hvac_seen must block
# ---------------------------------------------------------------------------


def test_reloading_room_previously_seen_blocks_establishment():
    # Two-room zone so the discriminator is the TRANSIENT block, not
    # the `not live` guard: r_ok is LIVE + seen (would satisfy the
    # remaining-rooms test alone), r_reload is transient. AM-1
    # invariant (F-INV-A): the whole zone MUST NOT establish.
    class _RC:
        def __init__(self):
            self.data = {"occupied": False, "temperature": None, "humidity": None}
    entries = [
        _FakeEntry("r_ok", state=ConfigEntryState.LOADED),
        _FakeEntry("r_reload", state=ConfigEntryState.SETUP_IN_PROGRESS),
    ]
    coords = {entries[0].entry_id: _RC()}
    zm = _mk_zm(entries=entries, coordinators=coords)
    zone = ZoneState(
        zone_id="z1", zone_name="Z1", climate_entity="c.z1",
    )
    zone.rooms = ["r_ok", "r_reload"]
    zm._zones["z1"] = zone
    # BOTH rooms were seen on a prior tick — the stale _hvac_seen entry
    # for r_reload must NOT satisfy establishment while the entry is
    # transient.
    zm._hvac_seen.update(["r_ok", "r_reload"])
    zm.update_room_conditions(house_state="home_day")
    assert zm.is_zone_hvac_established("z1") is False


# ---------------------------------------------------------------------------
# F4 — coordinator-present conjunct
# ---------------------------------------------------------------------------


def test_loaded_entry_absent_coordinator_blocks_establishment():
    # Entry is LOADED but the room coordinator isn't in hass.data — the
    # D1 producer takes the synthetic-empty branch and adds the room to
    # `_coordinator_absent_this_pass`. REV-2 D2 step 4 must block.
    entries = [_FakeEntry("r_x", state=ConfigEntryState.LOADED)]
    zm = _mk_zm(entries=entries, coordinators={})
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_x"]
    zm._zones["z1"] = zone
    # Seed as previously seen to isolate the coordinator-absence path.
    zm._hvac_seen.add("r_x")
    zm.update_room_conditions(house_state="home_day")
    assert "r_x" in zm._coordinator_absent_this_pass
    assert zm.is_zone_hvac_established("z1") is False


# ---------------------------------------------------------------------------
# Enum completeness — REV-2 AM-2 / F5
# ---------------------------------------------------------------------------


def test_every_config_entry_state_is_classified():
    # Drive the classifier once per HA ConfigEntryState member and
    # assert the result is one of the three defined kinds (never a
    # KeyError / missing map entry). Uses `list(ConfigEntryState)`
    # imported from HA — the plan's F13 no-hand-copy discipline.
    for member in list(ConfigEntryState):
        entries = [_FakeEntry("r_x", state=member)]
        zm = _mk_zm(entries=entries)
        zone = ZoneState(
            zone_id="z1", zone_name="Z1", climate_entity="c.z1",
        )
        zone.rooms = ["r_x"]
        zm._zones["z1"] = zone
        zm.update_room_conditions(house_state="home_day")
        kind, _ = zm._room_hvac_class["r_x"]
        assert kind in ("live", "transient", "excluded"), (
            f"ConfigEntryState.{member.name} produced kind={kind!r}"
        )


# ---------------------------------------------------------------------------
# F7 — enum-unavailable fallback fails CLOSED
# ---------------------------------------------------------------------------


def test_live_rooms_blocks_when_state_enum_unavailable():
    entries = [_FakeEntry("r_x", state=ConfigEntryState.LOADED)]
    zm = _mk_zm(entries=entries)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_x"]
    zm._zones["z1"] = zone
    # Simulate the enum-import failure by monkeypatching sys.modules
    # so the classifier's inline `from homeassistant.config_entries
    # import ConfigEntryState` raises AttributeError.
    real_mod = sys.modules["homeassistant.config_entries"]
    stub = types.ModuleType("homeassistant.config_entries")
    stub.ConfigEntry = MagicMock  # keep imports elsewhere happy
    try:
        sys.modules["homeassistant.config_entries"] = stub
        zm.update_room_conditions(house_state="home_day")
    finally:
        sys.modules["homeassistant.config_entries"] = real_mod
    # Room classified as transient (fail-CLOSED) — zone must not
    # establish.
    assert zm._room_hvac_class["r_x"][0] == "transient"
    assert zm.is_zone_hvac_established("z1") is False


# ---------------------------------------------------------------------------
# REPLACES the round-5 assertion
# ---------------------------------------------------------------------------


def test_f1_disabled_room_excluded_zone_establishes_from_live_rooms():
    # Replaces test_f1_disabled_room_leaves_zone_unestablished_round5.
    # A zone containing (r_live LOADED, r_disabled disabled_by USER)
    # establishes on r_live alone once r_live is coordinator-present
    # AND in _hvac_seen — no longer INERT for the whole zone.
    class _RC:
        def __init__(self):
            self.data = {"occupied": False, "temperature": None, "humidity": None}
    entries = [
        _FakeEntry("r_live", state=ConfigEntryState.LOADED),
        _FakeEntry(
            "r_disabled", state=ConfigEntryState.NOT_LOADED,
            disabled_by=ConfigEntryDisabler.USER,
        ),
    ]
    coords = {entries[0].entry_id: _RC()}
    zm = _mk_zm(entries=entries, coordinators=coords)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_live", "r_disabled"]
    zm._zones["z1"] = zone
    zm.update_room_conditions(house_state="home_day")
    assert zm.is_zone_hvac_established("z1") is True


# ---------------------------------------------------------------------------
# NM emission — sync-gate silence + async-drain queue
# ---------------------------------------------------------------------------


def test_transient_to_permanent_emits_one_warn_and_nm():
    entries = [_FakeEntry("r_x", state=ConfigEntryState.NOT_LOADED)]
    zm = _mk_zm(entries=entries)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_x"]
    zm._zones["z1"] = zone

    p1, p2 = _patched_now(NOW)
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    # Within grace — nothing to emit yet.
    assert zm.drain_degraded_events() == []

    p1, p2 = _patched_now(
        NOW + timedelta(seconds=HVAC_LIVE_ROOM_TRANSIENT_GRACE_S + 1),
    )
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    events = zm.drain_degraded_events()
    assert len(events) == 1
    name, reason = events[0]
    assert name == "r_x"
    assert reason == "transient_past_grace"

    # Debounced — a second past-grace tick does NOT re-enqueue.
    p1, p2 = _patched_now(
        NOW + timedelta(seconds=HVAC_LIVE_ROOM_TRANSIENT_GRACE_S + 60),
    )
    with p1, p2:
        zm.update_room_conditions(house_state="home_day")
    assert zm.drain_degraded_events() == []


def test_excluded_room_nm_emitted_from_async_producer_not_sync_gate():
    # The sync `is_zone_hvac_established` gate must NEVER enqueue an
    # event — that's the sync-vs-async split (REV-2 D3/F9). Only
    # `update_room_conditions` (async producer path in production)
    # enqueues via `_classify_all_rooms`.
    entries = [_FakeEntry("r_x", disabled_by=ConfigEntryDisabler.USER)]
    zm = _mk_zm(entries=entries)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_x"]
    zm._zones["z1"] = zone
    # First, call the sync gate BEFORE any producer pass — it must not
    # enqueue anything, and it must not raise.
    _ = zm.is_zone_hvac_established("z1")
    assert zm.drain_degraded_events() == []
    # Now drive the producer — the enqueue happens here, off the sync
    # gate path.
    zm.update_room_conditions(house_state="home_day")
    events = zm.drain_degraded_events()
    assert [e[0] for e in events] == ["r_x"]


# ---------------------------------------------------------------------------
# Binary-sensor `established` attribute inheritance (REV-2 F2)
# ---------------------------------------------------------------------------


def test_room_established_attr_false_while_sibling_room_reloading():
    # HVACOccupiedBinarySensor's `established` attribute reads
    # `zm.is_zone_hvac_established(zone_id)` at binary_sensor.py:914.
    # Under REV-2 D2, a zone with any transient sibling reads False
    # for EVERY room's `established` attr — intended, and pinned here.
    entries = [
        _FakeEntry("r_ok", state=ConfigEntryState.LOADED),
        _FakeEntry("r_reload", state=ConfigEntryState.SETUP_IN_PROGRESS),
    ]

    class _RC:
        def __init__(self):
            self.data = {"occupied": False, "temperature": None, "humidity": None}
    coords = {entries[0].entry_id: _RC()}
    zm = _mk_zm(entries=entries, coordinators=coords)
    zone = ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["r_ok", "r_reload"]
    zm._zones["z1"] = zone
    zm._hvac_seen.update(["r_ok", "r_reload"])
    zm.update_room_conditions(house_state="home_day")
    assert zm.is_zone_hvac_established("z1") is False, (
        "Any transient sibling must block the whole zone's established "
        "flag — F-INV-A."
    )
