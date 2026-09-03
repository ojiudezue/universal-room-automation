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


def _drive_ble_block(
    coord, now, *, ble_only_hold_since, became_occupied_time=None,
    capture_tasks=None,
):
    """Drive the ACTUAL extracted BLE block from coordinator.py and
    return (refused: bool, hass, s). Mutation-anchor: neutering the
    production cap logic must flip whether it admits.

    A1 re-anchor: the cap now measures from `_ble_only_hold_since`, not
    `_became_occupied_time` — the caller controls both explicitly so
    the discriminator test can pin BLE-only-fresh vs session-old.

    `capture_tasks` (list) receives every arg passed to
    `hass.async_create_task` so the NM wire-in can be behaviorally
    anchored (C-HIGH-1): neuter-deleting the fire call MUST leave the
    list empty for the evict test.
    """
    from test_ble_extend_not_create import (  # noqa: PLC0415
        _run_ble_block, _make_person_coord,
    )
    hass = make_hass()
    room_name = f"Test{coord._room_type}"
    pc = _make_person_coord(
        persons_by_room={room_name: {"oji"}},
        direct_ble_rooms={room_name},
    )
    hass.data.setdefault("universal_room_automation", {})["person_coordinator"] = pc

    if capture_tasks is not None:
        def _capture(coro, *a, **kw):
            capture_tasks.append(coro)
            # Close the coroutine to silence "was never awaited" warnings.
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass
            return MagicMock()
        hass.async_create_task = _capture

    class _Shim:
        pass
    s = _Shim()
    s.hass = hass
    s._occupancy_timeout = 300
    s._last_motion_time = now
    s._failsafe_fired = False
    s._became_occupied_time = became_occupied_time
    s._ble_only_hold_since = ble_only_hold_since
    s._last_occupied_state = True
    s._last_occupied_time = now
    s._room_type = coord._room_type
    s.entry = coord.entry
    s._get_config = coord._get_config
    s._get_ble_hold_cap_seconds = coord._get_ble_hold_cap_seconds

    data = {}
    _run_ble_block(s, data, now, room_name)
    refused = not data.get("occupied", False)
    return refused, hass, s


def _would_refuse_ble(coord, now, *, ble_only_hold_since=None,
                     became_occupied_time=None):
    refused, _, _ = _drive_ble_block(
        coord, now,
        ble_only_hold_since=ble_only_hold_since,
        became_occupied_time=became_occupied_time,
    )
    return refused


def test_evict_bathroom_cap_on_refuses_ble_when_ble_only_hold_stale():
    """Cap fires when BLE-only-hold anchor is older than the cap."""
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    now = dt_util.now()
    assert _would_refuse_ble(
        c, now, ble_only_hold_since=now - timedelta(seconds=7201),
    ) is True


def test_A1_anchor_uses_ble_only_not_session_start():
    """A1 discriminator: a bathroom whose overall session is old
    (`_became_occupied_time` = 7h ago) but whose most-recent BLE-only
    stretch is fresh (`_ble_only_hold_since` = 100s ago) MUST NOT be
    evicted — a real bather who moved <cap ago keeps their hold.

    Neutering the anchor (swapping `_ble_only_hold_since` back to
    `_became_occupied_time` in production) flips this to refuse.
    """
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    now = dt_util.now()
    assert _would_refuse_ble(
        c, now,
        ble_only_hold_since=now - timedelta(seconds=100),
        became_occupied_time=now - timedelta(seconds=7 * 3600),
    ) is False


def test_evict_master_bedroom_cap_default_off_admits_ble_after_cap():
    """Discriminator: same scenario, different room_type → NO refusal."""
    c = _bare_coord(ROOM_TYPE_BEDROOM)
    now = dt_util.now()
    assert _would_refuse_ble(
        c, now, ble_only_hold_since=now - timedelta(seconds=7201),
    ) is False


def test_evict_fail_open_when_ble_only_hold_since_none():
    """Restart-pin preservation: cap MUST fail open when the anchor is
    unset (first tick since a body fire, or restart before any BLE-only
    admit has been observed) — otherwise a mid-hold restart would drop
    a BLE-held bathroom immediately."""
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    assert _would_refuse_ble(
        c, dt_util.now(), ble_only_hold_since=None,
    ) is False


def test_evict_within_cap_bathroom_admits():
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    now = dt_util.now()
    assert _would_refuse_ble(
        c, now, ble_only_hold_since=now - timedelta(seconds=3600),
    ) is False


# ---------------------------------------------------------------------------
# C-HIGH-1 — NM wire-in behavioral anchor. Neuter-deletable call must
# fail this pair (fires on evict, does NOT fire within cap).
# ---------------------------------------------------------------------------


def test_wire_in_fires_async_create_task_on_evict():
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    now = dt_util.now()
    tasks: list = []
    refused, _, _ = _drive_ble_block(
        c, now,
        ble_only_hold_since=now - timedelta(seconds=7201),
        capture_tasks=tasks,
    )
    assert refused is True
    assert len(tasks) == 1, (
        f"Expected exactly one hass.async_create_task on cap eviction "
        f"(the NM fire); got {len(tasks)}. Neuter-deletable wire-in?"
    )
    # The scheduled coroutine must be the ble_hold_cap NM fire — assert
    # against the function object so a rename or accidental swap trips.
    coro = tasks[0]
    assert coro.__name__ == "_fire_ble_hold_cap_nm", (
        f"Scheduled coro was {coro.__name__!r}, expected "
        "_fire_ble_hold_cap_nm — wire-in went to the wrong helper."
    )


def test_wire_in_does_not_fire_async_create_task_within_cap():
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    now = dt_util.now()
    tasks: list = []
    refused, _, _ = _drive_ble_block(
        c, now,
        ble_only_hold_since=now - timedelta(seconds=3600),
        capture_tasks=tasks,
    )
    assert refused is False
    assert tasks == [], (
        f"Within-cap admit MUST NOT schedule the NM fire; got {tasks}."
    )


# ---------------------------------------------------------------------------
# C-MED-3 — duration lookup discriminates dict-hit from default (bug
# class #63 coincidental equality: cap default == bathroom cap == 7200).
# ---------------------------------------------------------------------------


def test_cap_seconds_helper_reads_room_type_from_dict_not_default(monkeypatch):
    """Replace BLE_HOLD_CAP_DURATIONS with a dict that carries a
    DIFFERENT bathroom value (1800). The helper must return 1800,
    proving it routes through the per-type dict lookup, not the
    DEFAULT_BLE_HOLD_CAP_SECONDS fallback."""
    from custom_components.universal_room_automation import const as _const

    monkeypatch.setattr(
        _const, "BLE_HOLD_CAP_DURATIONS",
        {ROOM_TYPE_BATHROOM: 1800, ROOM_TYPE_CLOSET: 1801},
    )
    c = _bare_coord(ROOM_TYPE_BATHROOM)
    assert c._get_ble_hold_cap_seconds() == 1800
    c2 = _bare_coord(ROOM_TYPE_CLOSET)
    assert c2._get_ble_hold_cap_seconds() == 1801
    # Bedroom (not in dict) still routes through DEFAULT.
    c3 = _bare_coord(ROOM_TYPE_BEDROOM)
    assert c3._get_ble_hold_cap_seconds() == DEFAULT_BLE_HOLD_CAP_SECONDS


# ---------------------------------------------------------------------------
# T-CAP-NM-DISTINCT — kind separate from P24 max_active_failsafe
# ---------------------------------------------------------------------------


def test_nm_kind_and_key_distinct_from_p24_two_path():
    """C-MED-2: drive BOTH `_fire_ble_hold_cap_nm` AND
    `_fire_max_active_failsafe_nm` through the same capture and
    assert their (kind, key) tuples DIFFER. A production kind-collision
    (someone reusing 'max_active_failsafe' or 'ble_hold_cap' across
    the two helpers) must go RED here."""
    calls: list = []

    async def _fake_fire(hass, kind, key, diagnosis, remedy="",
                        title_override=None, **kwargs):
        calls.append({
            "kind": kind, "key": key, "diagnosis": diagnosis,
            "remedy": remedy, "title": title_override,
        })
        return True

    import custom_components.universal_room_automation.domain_coordinators._stuck_signal_nm as ss  # noqa: E501
    orig = ss.fire_stuck_signal
    ss.fire_stuck_signal = _fake_fire
    try:
        loop = asyncio.new_event_loop()
        try:
            # A2/B4: pass observed=8100s (135min), cap=7200s (120min).
            loop.run_until_complete(
                coord_mod._fire_ble_hold_cap_nm(
                    MagicMock(), "MasterBathroom", 8100, 7200,
                )
            )
            # Same room, different NM path — must yield a different
            # (kind, key) tuple even though room_name matches.
            loop.run_until_complete(
                coord_mod._fire_max_active_failsafe_nm(
                    MagicMock(), "MasterBathroom", 240.0, 240.0,
                )
            )
        finally:
            loop.close()
    finally:
        ss.fire_stuck_signal = orig

    assert len(calls) == 2, f"Expected 2 NM emits, got {len(calls)}"
    cap_call, p24_call = calls[0], calls[1]
    assert cap_call["kind"] == "ble_hold_cap"
    assert cap_call["key"] == ("MasterBathroom",)
    assert p24_call["kind"] == "max_active_failsafe"
    assert p24_call["key"] == ("MasterBathroom",)
    # THE collision guard.
    assert (cap_call["kind"], cap_call["key"]) != (p24_call["kind"], p24_call["key"]), (
        "ble_hold_cap and max_active_failsafe MUST have distinct "
        "(kind, key) tuples so their per-day latches don't collide."
    )
    # A2/B4: diagnosis + title carry OBSERVED elapsed (135 min), not
    # the cap constant (120 min).
    assert "135 min" in cap_call["diagnosis"], (
        f"diagnosis missing observed 135 min: {cap_call['diagnosis']!r}"
    )
    assert "cap 120 min" in cap_call["diagnosis"]
    assert "135 min" in cap_call["title"], (
        f"title missing observed 135 min: {cap_call['title']!r}"
    )
    assert "adjacent-room BLE bleed" in cap_call["diagnosis"]
    assert "BLE_HOLD_CAP_DURATIONS" in cap_call["remedy"]
    assert "CONF_BLE_HOLD_CAP_ENABLED" in cap_call["remedy"]
    assert "MasterBathroom" in cap_call["title"]
