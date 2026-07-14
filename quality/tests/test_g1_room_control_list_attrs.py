"""Cycle G1: per-room control_* list attrs on OccupiedBinarySensor.

Tests the module-level helper `_build_control_attrs(coordinator)` which is
called from `OccupiedBinarySensor.extra_state_attributes`. The helper reads
the six actuator-driving CONF lists via `coordinator._get_config`
(options-first-with-data-fallback) so emitted attrs cannot diverge from
the actuator's ground truth (`coordinator.py:820-840`).

Each test carries a mutation-anchor note describing the on-disk mutation
in production source that MUST turn the test red — the check that the
test actually drives the production path, not a parallel copy of it.
"""
import pytest

import _provenance_harness  # noqa: F401 — stubs homeassistant modules

from custom_components.universal_room_automation.binary_sensor_control_attrs import (
    build_control_attrs as _build_control_attrs,
)
from custom_components.universal_room_automation.const import (
    CONF_LIGHTS,
    CONF_NIGHT_LIGHTS,
    CONF_FANS,
    CONF_HUMIDITY_FANS,
    CONF_COVERS,
    CONF_CLIMATE_ENTITY,
)


class _FakeEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}


class _FakeCoordinator:
    """Mirrors the real _get_config semantics from coordinator.py:346."""

    def __init__(self, data=None, options=None, raise_for=None):
        self.entry = _FakeEntry(data=data, options=options)
        self._raise_for = raise_for or set()

    def _get_config(self, key, default=None):
        if key in self._raise_for:
            raise RuntimeError(f"synthetic failure reading {key}")
        return self.entry.options.get(
            key, self.entry.data.get(key, default)
        )


# ---------------------------------------------------------------------------
# T1
# ---------------------------------------------------------------------------
def test_attrs_present_when_configured():
    """All six control_* keys populate from entry.data.

    Mutation anchor: in `_build_control_attrs`, replace the six-tuple
    `_G1_LIST_CONFS` list with an empty tuple → this test goes red on
    missing `control_lights` / `control_fans` keys, proving the helper
    (not a hand-copied dict) is the production path under test.
    """
    coord = _FakeCoordinator(data={
        CONF_LIGHTS: ["light.a", "switch.b"],
        CONF_NIGHT_LIGHTS: ["light.night"],
        CONF_FANS: ["fan.x"],
        CONF_HUMIDITY_FANS: ["fan.hum"],
        CONF_COVERS: ["cover.blind"],
        CONF_CLIMATE_ENTITY: "climate.zone_1",
    })
    attrs = _build_control_attrs(coord)
    assert attrs["control_lights"] == ["light.a", "switch.b"]
    assert attrs["control_night_lights"] == ["light.night"]
    assert attrs["control_fans"] == ["fan.x"]
    assert attrs["control_humidity_fans"] == ["fan.hum"]
    assert attrs["control_covers"] == ["cover.blind"]
    assert attrs["control_climate_entity"] == "climate.zone_1"


# ---------------------------------------------------------------------------
# T2
# ---------------------------------------------------------------------------
def test_attrs_default_when_absent():
    """Missing keys yield [] for lists and None for climate — never KeyError.

    Mutation anchor: change the list default in `_get_config(conf_key, [])`
    to `None` (drop the `or []`) → this test goes red on `TypeError: 'NoneType'
    is not iterable` inside `list(...)`, proving the None-safety branch is
    exercised.
    """
    coord = _FakeCoordinator(data={})
    attrs = _build_control_attrs(coord)
    for key in (
        "control_lights",
        "control_night_lights",
        "control_fans",
        "control_humidity_fans",
        "control_covers",
    ):
        assert attrs[key] == [], f"{key} default should be []"
    assert attrs["control_climate_entity"] is None


# ---------------------------------------------------------------------------
# T3 — options-over-data (guards against PWA seeing stale data-tier values)
# ---------------------------------------------------------------------------
def test_options_override_data():
    """entry.options wins over entry.data — mirrors `_get_config`.

    Mutation anchor: in the helper, swap the read from
    `coordinator._get_config(conf_key, [])` to
    `coordinator.entry.data.get(conf_key, [])` (drop the options-first
    fallback) → this test goes red because ["b"] would come back as ["a"].
    """
    coord = _FakeCoordinator(
        data={CONF_LIGHTS: ["a"]},
        options={CONF_LIGHTS: ["b"]},
    )
    attrs = _build_control_attrs(coord)
    assert attrs["control_lights"] == ["b"]


# ---------------------------------------------------------------------------
# T4 — copy semantics (attr mutation must not corrupt underlying store)
# ---------------------------------------------------------------------------
def test_attrs_are_copies_not_refs():
    """Mutating an emitted attr list must not mutate entry.options.

    Mutation anchor: in the helper, replace `out[attr_key] = list(raw)`
    with `out[attr_key] = raw` (emit the raw reference) → this test goes
    red because the append leaks into entry.options[CONF_LIGHTS].
    """
    coord = _FakeCoordinator(options={CONF_LIGHTS: ["light.original"]})
    attrs = _build_control_attrs(coord)
    attrs["control_lights"].append("light.injected")
    assert coord.entry.options[CONF_LIGHTS] == ["light.original"], (
        "emitted attr must be a copy — caller mutation leaked into store"
    )


# ---------------------------------------------------------------------------
# T5 — malformed one key does not blank other keys
# ---------------------------------------------------------------------------
def test_malformed_options_do_not_blank_other_attrs():
    """A synthetic raise on CONF_LIGHTS falls back to [] but leaves the
    other five keys populated from data.

    Mutation anchor: remove the per-key try/except in `_build_control_attrs`
    (single outer try) → this test goes red because the raise on CONF_LIGHTS
    would blank ALL keys, and `control_fans` would come back as [] instead
    of ["fan.x"].
    """
    coord = _FakeCoordinator(
        data={
            CONF_LIGHTS: ["light.a"],
            CONF_FANS: ["fan.x"],
            CONF_CLIMATE_ENTITY: "climate.z",
        },
        raise_for={CONF_LIGHTS},
    )
    attrs = _build_control_attrs(coord)
    assert attrs["control_lights"] == []  # raised → default
    assert attrs["control_fans"] == ["fan.x"]  # other reads survive
    assert attrs["control_climate_entity"] == "climate.z"
