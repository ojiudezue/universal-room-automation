"""HIGH-C1 behavioral: drive REAL PersonCensus._get_face_recognized_person_names.

Review C flagged that test_census_v2.py's face cross-check test exercises
a hand-copied StubPersonCensusV2, not production — so neutering the real
`not_home` guard at camera_census.py:~2208 leaves the suite green
(tautological fixture, banned).

This test loads the real `PersonCensus` class from camera_census.py and
asserts:

  * A face-recognized person whose `person.<slug>` tracker reads
    `not_home` is EXCLUDED from the returned list.
  * A face-recognized person whose tracker reads `home` (or is missing)
    IS included (fail-open guard preserved).

Mutation anchor: temporarily replace the `person_state.state == "not_home"`
comparison with `False` in production → this test MUST fail. Verified by
the operator during batch fix-up.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731


_mods: dict = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": MagicMock, "callback": _identity},
    "homeassistant.helpers": {},
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
        "UTC": timezone.utc,
    },
}

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_HERE = os.path.dirname(__file__)
_CC_PATH = os.path.join(_HERE, "..", "..", "custom_components")
_URA_PATH = os.path.join(_CC_PATH, "universal_room_automation")


if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [_CC_PATH]
    sys.modules["custom_components"] = _cc

if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname: str, relpath: str) -> types.ModuleType:
    full = f"custom_components.universal_room_automation.{modname}"
    cached = sys.modules.get(full)
    if cached is not None and getattr(cached, "__file__", None):
        return cached
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


_load("const", "const.py")
camera_census = _load("camera_census", "camera_census.py")

PersonCensus = camera_census.PersonCensus


# ---------------------------------------------------------------------------
# Minimal fakes
# ---------------------------------------------------------------------------


class _State:
    def __init__(self, state: str, last_changed: datetime | None = None):
        self.state = state
        self.last_changed = last_changed


class _States:
    def __init__(self, mapping: dict):
        self._m = mapping

    def get(self, entity_id):
        return self._m.get(entity_id)


class _Entry:
    def __init__(self, data):
        self.data = data
        self.options = {}


class _ConfigEntries:
    def __init__(self, entries):
        self._e = entries

    def async_entries(self, _domain):
        return self._e


class _Hass:
    def __init__(self, states, entries):
        self.states = _States(states)
        self.config_entries = _ConfigEntries(entries)


def _make_census_with_person(person_state: str | None):
    """Return (census, now) with one tracked person 'oji_udezue'.

    person_state: 'home', 'not_home', or None (entity absent — fail-open).
    """
    now = datetime.now(timezone.utc)
    face_last_changed = now - timedelta(seconds=30)  # well inside window

    states = {
        "sensor.frigate_oji_udezue_last_camera": _State(
            "front_door", last_changed=face_last_changed,
        ),
    }
    if person_state is not None:
        states["person.oji_udezue"] = _State(person_state)

    entries = [
        _Entry(
            {
                camera_census.CONF_ENTRY_TYPE: (
                    camera_census.ENTRY_TYPE_INTEGRATION
                ),
                "tracked_persons": ["person.oji_udezue"],
            }
        ),
    ]

    hass = _Hass(states, entries)
    # Skip __init__ (needs camera_manager); face function only uses self.hass.
    census = object.__new__(PersonCensus)
    census.hass = hass
    return census, now


class TestFaceCrossCheckBehavioral:
    """Drive the real PersonCensus._get_face_recognized_person_names."""

    def test_face_recognized_person_included_when_home(self):
        census, now = _make_census_with_person("home")
        result = census._get_face_recognized_person_names(now)
        assert "oji_udezue" in result, (
            "person.<slug>=home must NOT drop the face-recognized person"
        )

    def test_face_recognized_person_excluded_when_not_home(self):
        """Load-bearing: the not_home guard at camera_census.py:~2208 MUST
        drop the person. Neutering the `== 'not_home'` comparison in
        production causes this assertion to fail."""
        census, now = _make_census_with_person("not_home")
        result = census._get_face_recognized_person_names(now)
        assert "oji_udezue" not in result, (
            "person.<slug>=not_home must drop the face-recognized person "
            "(stale-face-latch guard)"
        )

    def test_face_recognized_fail_open_when_person_entity_missing(self):
        """No `person.<slug>` entity → include (conservative fail-open)."""
        census, now = _make_census_with_person(None)
        result = census._get_face_recognized_person_names(now)
        assert "oji_udezue" in result, (
            "Missing person.<slug> must fail-open (include)"
        )
