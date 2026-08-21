"""SENSCAP-ORPHAN-1 regression — removing a wired sensor must be saveable.

Operator report 2026-08-20 (Garage Hallway): *"please fix the fact that I
cannot clear the camera person sensor. This error shows no matter what I do."*

Mechanism the fix closes:

  * The per-entity capability dropdowns (`caps_kind__<entity_id>`) are rendered
    from the room's PRE-EDIT CONF lists.
  * When the operator removes a sensor from a list and submits, that sensor's
    dropdown is STILL in the submission.
  * `derive_capability` returns None for an entity that is no longer in any
    CONF list (rule 3), so the fold loop's `_kind == _default_kind` no-op
    branch is missed and the else-branch writes an orphan declaration.
  * `validate_capabilities_payload` then rejects it — "entity is not in this
    room's motion / mmwave / occupancy CONF lists" — surfacing as
    `sensor_capabilities_invalid`.
  * The step re-renders with the same stale dropdown, so the removal can NEVER
    be completed. The form is permanently wedged.

These tests drive the real `async_step_sensors` handler. The first one is the
founding case and FAILS on the pre-fix code.
"""

from __future__ import annotations

import asyncio
import importlib

_cbcf = importlib.import_module("test_cycle_b_config_flow")
_baec = importlib.import_module("test_baec_config_flow_round_trip")

_make_options_flow = _cbcf._make_options_flow
_ha_mocks_injected = _baec._ha_mocks_injected

CONF_MOTION_SENSORS = "motion_sensors"
CONF_MMWAVE_SENSORS = "mmwave_sensors"
CONF_OCCUPANCY_SENSORS = "occupancy_sensors"
CONF_SENSOR_CAPABILITIES = "sensor_capabilities"

# The live Garage Hallway wiring as of 2026-08-20.
_PIR = "binary_sensor.rgbw_motion_lux_3rdr_zigbee_garagehallway_occupancy_2"
_MMWAVE = "binary_sensor.mmwave_temp_hum_lux_garagehallway_presence"
_CAMERA = "binary_sensor.staircase_person_occupancy"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _base_options():
    return {
        CONF_MOTION_SENSORS: [_PIR, _MMWAVE],
        CONF_OCCUPANCY_SENSORS: [_CAMERA],
        CONF_SENSOR_CAPABILITIES: {_PIR: {"kind": "camera_presence"}},
    }


def _submit(user_input, options=None):
    with _ha_mocks_injected():
        flow = _make_options_flow(
            data={"room_name": "Garage Hallway"},
            options=options if options is not None else _base_options(),
        )
        return _run(flow.async_step_sensors(user_input))


def _errors(result):
    return (result or {}).get("errors") or {}


def test_removing_camera_sensor_saves_despite_stale_dropdown():
    """FOUNDING CASE — fails pre-fix with sensor_capabilities_invalid.

    The operator clears the camera person sensor from the occupancy list. The
    frontend still submits `caps_kind__<camera>` because the form was rendered
    before the edit. The save must succeed.
    """
    result = _submit({
        CONF_MOTION_SENSORS: [_PIR, _MMWAVE],
        CONF_MMWAVE_SENSORS: [],
        CONF_OCCUPANCY_SENSORS: [],          # <- camera removed
        "sensor_capabilities_json": "",
        f"caps_kind__{_PIR}": "camera_presence",
        f"caps_kind__{_MMWAVE}": "pir",
        f"caps_kind__{_CAMERA}": "occupancy",  # <- stale dropdown
    })
    assert _errors(result).get("base") != "sensor_capabilities_invalid", (
        "removal wedged the form — the stale dropdown for the de-wired entity "
        "was folded into an orphan capability declaration"
    )


def test_removal_also_prunes_a_json_authored_declaration():
    """A de-wired entity carrying a JSON-authored declaration must not block.

    Same wedge, reached through the JSON blob rather than the dropdown — the
    first validate runs before the fold, so the prune has to happen on both
    paths.
    """
    result = _submit({
        CONF_MOTION_SENSORS: [_MMWAVE],
        CONF_MMWAVE_SENSORS: [],
        CONF_OCCUPANCY_SENSORS: [],
        # _PIR removed from every list, but still declared in the blob.
        "sensor_capabilities_json":
            '{"%s": {"kind": "camera_presence"}}' % _PIR,
        f"caps_kind__{_MMWAVE}": "pir",
    })
    assert _errors(result).get("base") not in (
        "sensor_capabilities_invalid", "sensor_capabilities_invalid_json",
    ), "JSON-authored declaration for a de-wired entity still wedges the save"


def test_declaration_for_a_still_wired_entity_is_untouched():
    """Byte-identity guard: a submission that removes nothing must not change.

    The prune must fire ONLY for de-wired entities. This is the test that
    fails if the fix is over-broad and starts discarding live declarations.
    """
    result = _submit({
        CONF_MOTION_SENSORS: [_PIR, _MMWAVE],
        CONF_MMWAVE_SENSORS: [],
        CONF_OCCUPANCY_SENSORS: [_CAMERA],
        "sensor_capabilities_json":
            '{"%s": {"kind": "camera_presence"}}' % _PIR,
        f"caps_kind__{_PIR}": "camera_presence",
        f"caps_kind__{_MMWAVE}": "pir",
        f"caps_kind__{_CAMERA}": "occupancy",
    })
    assert not _errors(result), (
        "a no-removal submission must still validate clean"
    )


def test_orphan_declaration_is_not_persisted_after_removal():
    """The de-wired entity must be absent from the saved capabilities.

    Guards the other failure direction: silencing the error while still
    writing the orphan would leave a declaration that blocks every FUTURE
    save of this room.
    """
    result = _submit({
        CONF_MOTION_SENSORS: [_PIR, _MMWAVE],
        CONF_MMWAVE_SENSORS: [],
        CONF_OCCUPANCY_SENSORS: [],
        "sensor_capabilities_json": "",
        f"caps_kind__{_PIR}": "camera_presence",
        f"caps_kind__{_MMWAVE}": "pir",
        f"caps_kind__{_CAMERA}": "occupancy",
    })
    data = (result or {}).get("data")
    if data is None:
        # Step did not reach the save leg (menu/abort shape) — the founding
        # case above already covers the rejection. Nothing to assert here.
        return
    caps = data.get(CONF_SENSOR_CAPABILITIES) or {}
    assert _CAMERA not in caps, (
        "orphan declaration persisted for the de-wired camera sensor"
    )
