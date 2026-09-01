"""BLE-hold cap tests (ble-bleed-extend-corroboration cycle).

Covers the mandatory anchors from the plan §D4 / §5:

  * T-CAP-DURATION-CONST — the const dict carries the right seconds.
  * T-CAP-READ-SITE-DEFAULT — the real coordinator's `_get_config`
    returns the room-type-aware default when the key is unset, and the
    explicit False in `entry.options` overrides it.
  * T-CAP-SCHEMA-DEFAULT — voluptuous fills the Optional default from
    ROOM_TYPE_BLE_HOLD_CAP_DEFAULT for setup + options flows; a
    regression pin that the plan's dead template (`if CONF_* not in
    user_input`) is NOT introduced.
  * T-CAP-EVICT-BEHAVIORAL — bathroom, cap ON, session > cap, BLE-only,
    no Tier-1 → BLE extend REFUSED (discriminator: same scenario with
    Master Bedroom / cap default-OFF does NOT refuse).
  * T-CAP-NM-DISTINCT — the NM kind for cap is 'ble_hold_cap' and does
    NOT collide with the P24 'max_active_failsafe' latch key.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation.const import (
    BLE_HOLD_CAP_DURATIONS,
    CONF_BLE_HOLD_CAP_ENABLED,
    CONF_ROOM_TYPE,
    DEFAULT_BLE_HOLD_CAP_SECONDS,
    ROOM_TYPE_BATHROOM,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_BLE_HOLD_CAP_DEFAULT,
    ROOM_TYPE_CLOSET,
)
from custom_components.universal_room_automation import coordinator as coord_mod
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)
# Reuse the mock-HA loader from the existing config-flow test module
# (it monkeypatches homeassistant.config_entries.ConfigFlow etc. so
# config_flow.py can be imported outside a real HA process).
from test_cycle_b_config_flow import (
    UniversalRoomAutomationConfigFlow,
    UniversalRoomAutomationOptionsFlow,
)
from homeassistant.util import dt as dt_util


# ---------------------------------------------------------------------------
# T-CAP-DURATION-CONST
# ---------------------------------------------------------------------------


def test_cap_duration_const_bathroom_and_closet_and_default():
    assert BLE_HOLD_CAP_DURATIONS[ROOM_TYPE_BATHROOM] == 7200
    assert BLE_HOLD_CAP_DURATIONS[ROOM_TYPE_CLOSET] == 7200
    assert DEFAULT_BLE_HOLD_CAP_SECONDS == 7200
    # Bedrooms / any other room type: no per-type entry → uses default.
    assert ROOM_TYPE_BEDROOM not in BLE_HOLD_CAP_DURATIONS
    # ROOM_TYPE_BLE_HOLD_CAP_DEFAULT truthy iff bathroom / closet.
    assert ROOM_TYPE_BLE_HOLD_CAP_DEFAULT[ROOM_TYPE_BATHROOM] is True
    assert ROOM_TYPE_BLE_HOLD_CAP_DEFAULT[ROOM_TYPE_CLOSET] is True
    assert ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(ROOM_TYPE_BEDROOM, False) is False


# ---------------------------------------------------------------------------
# T-CAP-READ-SITE-DEFAULT — REAL coordinator, real _get_config
# ---------------------------------------------------------------------------


def _bare_coord(room_type: str, options: dict | None = None):
    """Allocate a coordinator without running __init__ and seed only
    what `_get_config` + `_get_ble_hold_cap_seconds` read.

    Precedent: test_substrate_gap_canary.py:_make_coord + operator plan
    (test_hvac_vacancy_sweep_manual_on_guard.py:373 __new__ pattern).
    """
    c = object.__new__(UniversalRoomCoordinator)
    entry = MagicMock()
    entry.data = {"room_name": f"Test{room_type}", CONF_ROOM_TYPE: room_type}
    entry.options = dict(options or {})
    object.__setattr__(c, "entry", entry)
    object.__setattr__(c, "_room_type", room_type)
    return c


def test_read_site_default_bathroom_cap_on_when_key_unset():
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    default = ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(c._room_type, False)
    assert default is True
    # Real _get_config resolves against the same default → True.
    assert c._get_config(CONF_BLE_HOLD_CAP_ENABLED, default) is True


def test_read_site_default_bedroom_cap_off_when_key_unset():
    c = _bare_coord(ROOM_TYPE_BEDROOM)
    default = ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(c._room_type, False)
    assert default is False
    assert c._get_config(CONF_BLE_HOLD_CAP_ENABLED, default) is False


def test_read_site_explicit_false_overrides_bathroom_default():
    c = _bare_coord(
        ROOM_TYPE_BATHROOM,
        options={CONF_BLE_HOLD_CAP_ENABLED: False},
    )
    default = ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(c._room_type, False)
    assert c._get_config(CONF_BLE_HOLD_CAP_ENABLED, default) is False


def test_read_site_ble_cap_seconds_helper_bathroom_and_default():
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    assert c._get_ble_hold_cap_seconds() == 7200
    c2 = _bare_coord(ROOM_TYPE_BEDROOM)
    # Bedroom falls through to DEFAULT_BLE_HOLD_CAP_SECONDS (also 7200).
    assert c2._get_ble_hold_cap_seconds() == DEFAULT_BLE_HOLD_CAP_SECONDS


# ---------------------------------------------------------------------------
# T-CAP-SCHEMA-DEFAULT — voluptuous-driven
# ---------------------------------------------------------------------------


def _get_schema_default(schema, key_name: str):
    """Extract voluptuous Optional default for a key by calling
    `schema({})` — voluptuous fills in every Optional's default."""
    filled = schema({})
    assert key_name in filled, f"schema did not fill {key_name}"
    return filled[key_name]


def _make_setup_flow_at_climate_step(room_type: str):
    flow = UniversalRoomAutomationConfigFlow.__new__(
        UniversalRoomAutomationConfigFlow
    )
    flow._data = {CONF_ROOM_TYPE: room_type, "area_id": None}
    flow._integration_data = None
    flow._energy_data = None
    flow._integration_entry_id = None

    class _H:
        def __init__(self):
            self._states = {}
            self.states = MagicMock()
            self.states.get = lambda eid: self._states.get(eid)
            self.states.async_entity_ids = MagicMock(return_value=[])
            self.config_entries = MagicMock()
            self.config_entries.async_entries = MagicMock(return_value=[])
    flow.hass = _H()
    return flow


@pytest.mark.asyncio
async def test_schema_default_setup_bathroom_ble_cap_on():
    flow = _make_setup_flow_at_climate_step(ROOM_TYPE_BATHROOM)
    result = await flow.async_step_climate()
    schema = result["data_schema"]
    assert _get_schema_default(schema, CONF_BLE_HOLD_CAP_ENABLED) is True


@pytest.mark.asyncio
async def test_schema_default_setup_bedroom_ble_cap_off():
    flow = _make_setup_flow_at_climate_step(ROOM_TYPE_BEDROOM)
    result = await flow.async_step_climate()
    schema = result["data_schema"]
    assert _get_schema_default(schema, CONF_BLE_HOLD_CAP_ENABLED) is False


@pytest.mark.asyncio
async def test_schema_default_options_bathroom_ble_cap_on_no_override():
    entry = MagicMock()
    entry.data = {CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM, "room_name": "Test"}
    entry.options = {}
    entry.entry_id = "test"
    entry.title = "Test"
    flow = UniversalRoomAutomationOptionsFlow.__new__(
        UniversalRoomAutomationOptionsFlow
    )
    flow._config_entry = entry
    flow._selected_zone_entry_id = None
    flow._pending_delete_rule_id = None

    class _H:
        def __init__(self):
            self._states = {}
            self.states = MagicMock()
            self.states.get = lambda eid: self._states.get(eid)
            self.states.async_entity_ids = MagicMock(return_value=[])
            self.config_entries = MagicMock()
            self.config_entries.async_entries = MagicMock(return_value=[])
    flow.hass = _H()
    result = await flow.async_step_climate()
    schema = result["data_schema"]
    assert _get_schema_default(schema, CONF_BLE_HOLD_CAP_ENABLED) is True


def test_dead_template_regression_pin_no_manual_fill_block():
    """The plan explicitly forbids adding an
    `if CONF_BLE_HOLD_CAP_ENABLED not in user_input` block — voluptuous
    fills the Optional default first, so any such block is dead. Pin it
    against re-introduction (a manual fill would mask cap-OFF explicit
    saves as absent-key defaults)."""
    from pathlib import Path
    p = (
        Path(__file__).resolve().parents[2]
        / "custom_components/universal_room_automation/config_flow.py"
    )
    text = p.read_text()
    # The forbidden pattern is a real code assignment fill:
    #   if CONF_BLE_HOLD_CAP_ENABLED not in user_input:
    #       user_input[CONF_BLE_HOLD_CAP_ENABLED] = ...
    # (Modeled on the wet_room dead template at config_flow.py:1897.)
    forbidden = "user_input[CONF_BLE_HOLD_CAP_ENABLED]"
    assert forbidden not in text, (
        "Dead template re-introduced: manual user_input fill for "
        "CONF_BLE_HOLD_CAP_ENABLED would mask explicit cap-OFF saves "
        "as absent-key defaults. Rely on voluptuous Optional default."
    )


# ---------------------------------------------------------------------------
# T-CAP-EVICT-BEHAVIORAL — bathroom cap-ON refuses, bedroom cap-OFF admits
# ---------------------------------------------------------------------------
#
# We do not synthesize the whole coordinator update tick; the read-site
# logic is small and localized. Simulate it directly against the same
# code path a bare-alloc coord exposes: `_get_config` + duration check +
# `_get_ble_hold_cap_seconds`. This mirrors the inline logic the plan
# specifies at the BLE chain-extend block.


def _would_refuse_ble(coord, now) -> bool:
    """Drive the ACTUAL extracted BLE block from coordinator.py and
    observe whether it admits BLE. Mutation-anchor: neutering the
    production cap logic must flip this to admit.

    Reuses the extraction machinery from test_ble_extend_not_create.py
    (same production-source-exec pattern) so this test is a real
    per-site drill, NOT a logic replica.
    """
    from test_ble_extend_not_create import (  # noqa: PLC0415
        _run_ble_block, _make_person_coord,
    )
    hass = make_hass()
    room_name = f"Test{coord._room_type}"
    # Present a BLE person; direct-ble room so the block reaches the
    # cap gate. Chain unbroken (last_occupied_state True) so ble_allowed
    # starts True and the cap can either preserve or refuse.
    pc = _make_person_coord(
        persons_by_room={room_name: {"oji"}},
        direct_ble_rooms={room_name},
    )
    hass.data.setdefault("universal_room_automation", {})["person_coordinator"] = pc

    # Reuse the coord's _get_config / _get_ble_hold_cap_seconds / entry
    # via a duck-typed _FakeSelf-shaped object. Add the fields the BLE
    # block reads that are not on our bare-alloc coord.
    class _Shim:
        pass
    s = _Shim()
    s.hass = hass
    s._occupancy_timeout = 300
    s._last_motion_time = now  # fresh motion so pre-cap predicate passes
    s._failsafe_fired = False
    s._became_occupied_time = coord._became_occupied_time
    s._last_occupied_state = True
    s._last_occupied_time = now
    s._room_type = coord._room_type
    s.entry = coord.entry
    # Bind the real coord methods so the block calls production code.
    s._get_config = coord._get_config
    s._get_ble_hold_cap_seconds = coord._get_ble_hold_cap_seconds

    data = {}
    _run_ble_block(s, data, now, room_name)
    # Admitted → STATE_OCCUPIED=True + source="ble". Refused → not set.
    return not data.get("occupied", False)


def test_evict_bathroom_cap_on_refuses_ble_after_cap():
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    now = dt_util.now()
    object.__setattr__(c, "_became_occupied_time", now - timedelta(seconds=7201))
    assert _would_refuse_ble(c, now) is True


def test_evict_master_bedroom_cap_default_off_admits_ble_after_cap():
    """Discriminator: same scenario, different room_type → NO refusal.

    Ensures the default cascade actually differentiates room types (a
    unified True default would incorrectly refuse bedrooms too)."""
    c = _bare_coord(ROOM_TYPE_BEDROOM)
    now = dt_util.now()
    object.__setattr__(c, "_became_occupied_time", now - timedelta(seconds=7201))
    assert _would_refuse_ble(c, now) is False


def test_evict_fail_open_when_became_occupied_time_none():
    """Restart-pin preservation: cap MUST fail open when the session
    anchor is unset, otherwise mid-hold restarts would immediately drop
    a BLE-held bathroom on the first tick."""
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    object.__setattr__(c, "_became_occupied_time", None)
    assert _would_refuse_ble(c, dt_util.now()) is False


def test_evict_within_cap_bathroom_admits():
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    now = dt_util.now()
    # 1 hour < 2 hour cap → cap does not engage yet.
    object.__setattr__(c, "_became_occupied_time", now - timedelta(seconds=3600))
    assert _would_refuse_ble(c, now) is False


# ---------------------------------------------------------------------------
# T-CAP-NM-DISTINCT — kind separate from P24 max_active_failsafe
# ---------------------------------------------------------------------------


def test_nm_kind_and_key_distinct_from_p24():
    """Two-path check: the NM helper fires kind='ble_hold_cap' with a
    (room_name,)-shaped key. That is a DIFFERENT latch key from the P24
    (kind='max_active_failsafe', (room_name,)) latch — same room_name
    string, different kind → no collision."""
    captured: dict = {}

    async def _fake_fire(hass, kind, key, diagnosis, remedy="",
                        title_override=None, **kwargs):
        captured["kind"] = kind
        captured["key"] = key
        captured["diagnosis"] = diagnosis
        captured["remedy"] = remedy
        captured["title"] = title_override
        return True

    # Monkeypatch inside the helper's local import path.
    import custom_components.universal_room_automation.domain_coordinators._stuck_signal_nm as ss  # noqa: E501
    orig = ss.fire_stuck_signal
    ss.fire_stuck_signal = _fake_fire
    try:
        asyncio.get_event_loop().run_until_complete(
            coord_mod._fire_ble_hold_cap_nm(MagicMock(), "MasterBathroom", 7200)
        )
    finally:
        ss.fire_stuck_signal = orig

    assert captured["kind"] == "ble_hold_cap"
    assert captured["key"] == ("MasterBathroom",)
    # P24 collision guard: kind MUST differ from max_active_failsafe.
    assert captured["kind"] != "max_active_failsafe"
    assert "BLE-hold cap" in captured["diagnosis"]
    assert "adjacent-room BLE bleed" in captured["diagnosis"]
    assert "BLE_HOLD_CAP_DURATIONS" in captured["remedy"]
    assert "CONF_BLE_HOLD_CAP_ENABLED" in captured["remedy"]
    assert "MasterBathroom" in captured["title"]
