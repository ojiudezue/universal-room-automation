"""HVAC pre-arrival accepts source=camera_face.

Wave-1 consumer #3 — HVAC-CAMERA-FACE-ARRIVAL-SOURCE-1.

Face-recognized arrivals dispatched via SIGNAL_PERSON_ARRIVING with
source="camera_face" (presence.py:4712) must pass the HVAC pre-arrival
source filter (hvac.py:3533) so pre-conditioning is triggered. Previously
the default filter list was ["geofence", "ble"] and dropped camera_face
silently.

RED-on-neuter: removing "camera_face" from EITHER
  - DEFAULT_PRE_ARRIVAL_SOURCES (hvac_const.py:345)
  - the init literal self._pre_arrival_sources = [...] (hvac.py:529)
fails these tests.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

# --- HA stubs (subset copied from test_hvac_zone_intelligence.py's pattern) --

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


for _name in ("homeassistant", "homeassistant.helpers"):
    sys.modules.setdefault(_name, _mock_module(_name))

# --- Load hvac_const.py without triggering the URA __init__.py chain --------

_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(_project_root, "custom_components", "universal_room_automation")
_dc_root = os.path.join(_ura_root, "domain_coordinators")

_cc_pkg = sys.modules.setdefault("custom_components", _mock_module("custom_components"))
_ura_pkg = sys.modules.setdefault(
    "custom_components.universal_room_automation",
    _mock_module("custom_components.universal_room_automation"),
)
_dc_pkg = sys.modules.setdefault(
    "custom_components.universal_room_automation.domain_coordinators",
    _mock_module("custom_components.universal_room_automation.domain_coordinators"),
)


def _load_module(name, filepath):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == filepath:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


hvac_const = _load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    os.path.join(_dc_root, "hvac_const.py"),
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_default_pre_arrival_sources_includes_camera_face():
    """The published default source list admits camera_face."""
    assert "camera_face" in hvac_const.DEFAULT_PRE_ARRIVAL_SOURCES
    # Baseline sources still present — non-regression for existing operators.
    assert "geofence" in hvac_const.DEFAULT_PRE_ARRIVAL_SOURCES
    assert "ble" in hvac_const.DEFAULT_PRE_ARRIVAL_SOURCES


def _hvac_source_text() -> str:
    with open(os.path.join(_dc_root, "hvac.py"), "r") as fh:
        return fh.read()


def test_hvac_init_literal_includes_camera_face():
    """The in-class init literal (hvac.py:~529) must agree with the const default.

    Guards against drift between DEFAULT_PRE_ARRIVAL_SOURCES and the hard-coded
    fallback the coordinator uses before options-flow config is applied.
    """
    src = _hvac_source_text()
    assert (
        'self._pre_arrival_sources: list[str] = ["geofence", "ble", "camera_face"]'
        in src
    ), "hvac.py init literal must include camera_face"


def test_source_membership_filter_still_present():
    """Non-regression: the membership filter that gates source acceptance is
    still the mechanism. If someone removes it, admitting camera_face in the
    lists becomes meaningless."""
    src = _hvac_source_text()
    assert "if source and source not in self._pre_arrival_sources:" in src


def _filter_admits(source: str, sources_list: list[str]) -> bool:
    """Faithful re-implementation of the source filter (hvac.py:3532-3535)
    exercised against the LIVE sources_list. Guarantees test intent tracks
    the production predicate literally."""
    if source and source not in sources_list:
        return False
    return True


def test_camera_face_admitted_by_default_list():
    """A camera_face arrival passes the filter under the shipped default list."""
    assert _filter_admits(
        "camera_face", list(hvac_const.DEFAULT_PRE_ARRIVAL_SOURCES)
    ) is True


def test_geofence_and_ble_still_admitted():
    """Non-regression: existing sources still admitted under the default list."""
    defaults = list(hvac_const.DEFAULT_PRE_ARRIVAL_SOURCES)
    assert _filter_admits("geofence", defaults) is True
    assert _filter_admits("ble", defaults) is True


def test_unknown_source_still_dropped():
    """Non-regression: unknown sources still rejected."""
    assert _filter_admits(
        "magic", list(hvac_const.DEFAULT_PRE_ARRIVAL_SOURCES)
    ) is False


def test_operator_omission_of_camera_face_is_honoured():
    """A per-deployment override that omits camera_face still drops it —
    the default only widens; the knob (CONF_PRE_ARRIVAL_SOURCES) is
    authoritative when set."""
    assert _filter_admits("camera_face", ["geofence", "ble"]) is False
