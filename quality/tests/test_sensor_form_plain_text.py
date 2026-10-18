"""SENSOR-FORM-PLAIN-TEXT-1 — plain-English sensor form (Tier 1).

Covers (card SENSOR-FORM-PLAIN-TEXT-1):

  * Options "sensors" step renders the new per-entity "What can it see?"
    dropdown with plain-English option labels (Movement only / People
    sitting still / Bed or seat / Not sure (safe default)).
  * "Not sure (safe default)" writes NO override for an entity that has
    no stored override (the derived-default no-op path).
  * An existing override is still shown as the dropdown default and is
    preserved byte-identically when the operator saves without changing it.
  * The `sensor_capabilities_json` textarea is hidden in Simple mode and
    shown in Advanced mode (and stays visible when a non-default value is
    stored, per the `_adv` reach-back invariant).
  * Mutation drill: if the "Not sure (safe default)" sentinel-handling in
    the submit handler is neutered, the "no override written" test fails
    (proves the test is anchored to the production code path, not to its
    name).
"""

from __future__ import annotations

import pytest

import asyncio
import importlib
import json
from pathlib import Path

_cbcf = importlib.import_module("test_cycle_b_config_flow")
_baec = importlib.import_module("test_baec_config_flow_round_trip")

_make_options_flow = _cbcf._make_options_flow
_ha_mocks_injected = _baec._ha_mocks_injected

CONF_MOTION_SENSORS = "motion_sensors"
CONF_MMWAVE_SENSORS = "presence_sensors"
CONF_OCCUPANCY_SENSORS = "occupancy_sensors"
CONF_SENSOR_CAPABILITIES = "sensor_capabilities"

_PIR = "binary_sensor.room_motion"
_MMWAVE = "binary_sensor.room_presence"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make(options=None, show_advanced=False):
    flow = _make_options_flow(
        data={"room_name": "Test Room"},
        options=options or {
            CONF_MOTION_SENSORS: [_PIR],
            CONF_MMWAVE_SENSORS: [_MMWAVE],
        },
    )
    flow.show_advanced_options = show_advanced
    return flow


def _render(flow):
    with _ha_mocks_injected():
        return _run(flow.async_step_sensors(None))


def _submit(flow, user_input):
    with _ha_mocks_injected():
        return _run(flow.async_step_sensors(user_input))


def _schema_markers(result):
    schema = result.get("data_schema")
    return list(getattr(schema, "schema", {}).keys())


def _marker_for(result, key):
    for m in _schema_markers(result):
        if str(getattr(m, "schema", m)) == key:
            return m
    return None


# --------------------------------------------------------------------------
# D1: labels + option set
# --------------------------------------------------------------------------

def test_translation_labels_use_plain_english():
    """The three sensor-list labels/descriptions use the SENSOR-FORM-
    PLAIN-TEXT-1 wording in both strings.json and translations/en.json."""
    for rel in (
        "custom_components/universal_room_automation/strings.json",
        "custom_components/universal_room_automation/translations/en.json",
    ):
        path = Path(__file__).resolve().parents[2] / rel
        text = path.read_text()
        # Removed old wordy labels
        assert "Pre-Combined Motion + Presence Sensors" not in text, rel
        assert "Motion Sensors (PIR)" not in text, rel
        # New copy
        assert '"motion_sensors": "Motion sensors"' in text, rel
        assert '"presence_sensors": "Presence sensors"' in text, rel
        assert '"occupancy_sensors": "Combined sensors"' in text, rel
        assert '"motion_sensors": "See movement only."' in text, rel
        assert (
            '"presence_sensors": "See people sitting still."' in text
        ), rel
        assert (
            '"occupancy_sensors": "Radar and motion reported as one '
            'signal."' in text
        ), rel


def test_per_entity_dropdown_renders_plain_labels_and_default_sentinel():
    """The caps_kind__<entity> dropdown carries the new plain-English
    labels AND the "Not sure (safe default)" sentinel as its default
    for an entity with no stored override."""
    flow = _make()
    result = _render(flow)
    # Both configured entities get a dropdown
    keys = [str(getattr(m, "schema", m)) for m in _schema_markers(result)]
    assert f"caps_kind__{_PIR}" in keys
    assert f"caps_kind__{_MMWAVE}" in keys

    marker = _marker_for(result, f"caps_kind__{_PIR}")
    assert marker is not None
    # Default = sentinel when no override stored
    default = marker.default()
    assert default == "__default__", default
    # Options carry plain-English labels
    sel = result["data_schema"].schema[marker]
    opts = sel.config.options
    opt_labels = {o["value"]: o["label"] for o in opts}
    assert opt_labels["__default__"] == "Not sure (safe default)"
    assert opt_labels["motion"] == "Movement only"
    assert opt_labels["mmwave"] == "People sitting still"
    assert opt_labels["bed"] == "Bed or seat"


# --------------------------------------------------------------------------
# D2: existing override is shown and preserved
# --------------------------------------------------------------------------

def test_existing_override_is_shown_as_dropdown_default():
    """An entity with a stored override (e.g. `pir`) shows that kind as
    the dropdown default — operator sees the current state."""
    opts = {
        CONF_MOTION_SENSORS: [_PIR],
        CONF_SENSOR_CAPABILITIES: {_PIR: {"kind": "pir"}},
    }
    flow = _make(options=opts)
    result = _render(flow)
    marker = _marker_for(result, f"caps_kind__{_PIR}")
    assert marker.default() == "pir"
    # The stored kind is reachable in the options even though it's not
    # one of the four primary labels (preserve-on-save guarantee).
    sel = result["data_schema"].schema[marker]
    values = {o["value"] for o in sel.config.options}
    assert "pir" in values


def test_existing_override_preserved_on_unchanged_save():
    """Submitting with the dropdown left at the stored kind preserves
    the override byte-identically."""
    opts = {
        CONF_MOTION_SENSORS: [_PIR],
        CONF_SENSOR_CAPABILITIES: {
            _PIR: {"kind": "pir", "trust_class": "witness"},
        },
    }
    flow = _make(options=opts)
    result = _submit(flow, {
        CONF_MOTION_SENSORS: [_PIR],
        CONF_MMWAVE_SENSORS: [],
        CONF_OCCUPANCY_SENSORS: [],
        "sensor_capabilities_json": json.dumps(
            opts[CONF_SENSOR_CAPABILITIES], indent=2, sort_keys=True,
        ),
        f"caps_kind__{_PIR}": "pir",
    })
    data = (result or {}).get("data") or {}
    caps = data.get(CONF_SENSOR_CAPABILITIES) or {}
    assert caps.get(_PIR, {}).get("kind") == "pir"
    assert caps.get(_PIR, {}).get("trust_class") == "witness"


# --------------------------------------------------------------------------
# D3: "Not sure" writes no override
# --------------------------------------------------------------------------

def test_not_sure_writes_no_override_for_fresh_entity():
    """Selecting "Not sure (safe default)" for an entity with no stored
    override must NOT persist an override entry."""
    flow = _make()  # no sensor_capabilities in options
    result = _submit(flow, {
        CONF_MOTION_SENSORS: [_PIR],
        CONF_MMWAVE_SENSORS: [_MMWAVE],
        CONF_OCCUPANCY_SENSORS: [],
        "sensor_capabilities_json": "",
        f"caps_kind__{_PIR}": "__default__",
        f"caps_kind__{_MMWAVE}": "__default__",
    })
    # The save must SUCCEED: an error form also has no persisted caps, so
    # without this the test passed when the sentinel leaked through as an
    # invalid literal kind (found by the D1 sandbox drill, 2026-10-17).
    assert not (result or {}).get("errors"), result
    data = (result or {}).get("data") or {}
    caps = data.get(CONF_SENSOR_CAPABILITIES) or {}
    assert _PIR not in caps, caps
    assert _MMWAVE not in caps, caps


def test_not_sure_drops_a_kind_only_override_and_preserves_trust_class():
    """Selecting "Not sure" on an entity whose stored override has ONLY
    `kind` drops the entry entirely (becomes the default); if it has
    co-stored metadata (trust_class) that metadata is preserved."""
    opts_kind_only = {
        CONF_MOTION_SENSORS: [_PIR],
        CONF_SENSOR_CAPABILITIES: {_PIR: {"kind": "pir"}},
    }
    flow = _make(options=opts_kind_only)
    result = _submit(flow, {
        CONF_MOTION_SENSORS: [_PIR],
        CONF_MMWAVE_SENSORS: [],
        CONF_OCCUPANCY_SENSORS: [],
        "sensor_capabilities_json": json.dumps(
            opts_kind_only[CONF_SENSOR_CAPABILITIES], indent=2, sort_keys=True,
        ),
        f"caps_kind__{_PIR}": "__default__",
    })
    caps = ((result or {}).get("data") or {}).get(
        CONF_SENSOR_CAPABILITIES
    ) or {}
    assert _PIR not in caps, caps

    opts_with_trust = {
        CONF_MOTION_SENSORS: [_PIR],
        CONF_SENSOR_CAPABILITIES: {
            _PIR: {"kind": "pir", "trust_class": "witness"},
        },
    }
    flow = _make(options=opts_with_trust)
    result = _submit(flow, {
        CONF_MOTION_SENSORS: [_PIR],
        CONF_MMWAVE_SENSORS: [],
        CONF_OCCUPANCY_SENSORS: [],
        "sensor_capabilities_json": json.dumps(
            opts_with_trust[CONF_SENSOR_CAPABILITIES], indent=2, sort_keys=True,
        ),
        f"caps_kind__{_PIR}": "__default__",
    })
    caps = ((result or {}).get("data") or {}).get(
        CONF_SENSOR_CAPABILITIES
    ) or {}
    # Co-stored metadata preserved; the kind re-written to the derived
    # default (which for a motion-list entity is "motion") because the
    # existing default-match no-op path leaves the entry intact when it
    # has residual keys.
    assert _PIR in caps, caps
    assert caps[_PIR].get("trust_class") == "witness"


# --------------------------------------------------------------------------
# D4: JSON textarea hidden in Simple mode, shown in Advanced mode
# --------------------------------------------------------------------------

def test_sensor_capabilities_json_marked_advanced_when_default():
    """With NO stored overrides, the raw-JSON textarea carries the
    ``advanced: True`` marker so HA drops it in Simple mode (via
    ``add_suggested_values_to_schema`` at runtime). The mock test flow
    doesn't honour the HA UI filter, so we assert the MARKER directly."""
    flow = _make()
    result = _render(flow)
    marker = _marker_for(result, "sensor_capabilities_json")
    assert marker is not None
    desc = marker.description
    assert isinstance(desc, dict) and desc.get("advanced") is True, desc


def test_sensor_capabilities_json_reachable_when_value_is_non_default():
    """I2 reach-back: a room with a stored override has NO advanced
    marker on the textarea, so it stays visible in Simple mode."""
    flow = _make(
        options={
            CONF_MOTION_SENSORS: [_PIR],
            CONF_SENSOR_CAPABILITIES: {_PIR: {"kind": "pir"}},
        },
    )
    result = _render(flow)
    marker = _marker_for(result, "sensor_capabilities_json")
    assert marker is not None
    desc = marker.description
    # Either no description, or no advanced marker.
    advanced = isinstance(desc, dict) and desc.get("advanced") is True
    assert not advanced, desc


# --------------------------------------------------------------------------
# D5: mutation drill — neuter the sentinel path, prove a test fails
# --------------------------------------------------------------------------

@pytest.mark.source_mutation
def test_mutation_drill_not_sure_sentinel_path_is_load_bearing():
    """Replace the production sentinel-resolution block with a dead branch
    (so "__default__" passes through unresolved, writing a raw literal
    override), and prove that `test_not_sure_writes_no_override_for_fresh_entity`
    fails. Anchors that test to the production code path, not its name.

    TEST-HARNESS D1: the mutant is applied to a tmp COPY of the repo and the
    anchor runs there in a subprocess (apply_mutation_in_sandbox). The old
    drill wrote config_flow.py in place and relied on a ``finally`` restore.
    The sandbox also requires the anchor to be GREEN unmutated.
    """
    from _mutation_sandbox import apply_mutation_in_sandbox

    src_path = Path(__file__).resolve().parents[2] / (
        "custom_components/universal_room_automation/config_flow.py"
    )
    apply_mutation_in_sandbox(
        prod_path=src_path,
        # Neuter: force the equality to False so the "__default__" value
        # survives into _dropdown_selections as a literal kind.
        swap_from="if _val == _CAPS_KIND_DEFAULT:",
        swap_to="if False and _val == _CAPS_KIND_DEFAULT:",
        anchor_test_file=Path(__file__).resolve(),
        anchor_test_name="test_not_sure_writes_no_override_for_fresh_entity",
        expect="KILLED",
        timeout=180.0,
    )
