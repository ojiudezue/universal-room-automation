"""CIRCLING-SEVERITY-1 D2 — per-house-state severity pin tests.

Pins the contextual severity table's `circling` rows across the 9
HouseState values. Reads NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY at
test time so a future re-tune of GUEST severity does NOT block this
test (build-pred #3).

See docs/planning/PLANNING_circling_severity.md §D2.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest


# --- package plumbing (avoid triggering __init__.py chain) --------------------

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

_cc = sys.modules.get("custom_components")
if _cc is None:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "custom_components",
        )
    ]
    sys.modules["custom_components"] = _cc

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = sys.modules.get("custom_components.universal_room_automation")
if _ura is None:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura
    _cc.universal_room_automation = _ura


def _load(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_const = _load(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)


# --- 9-row pin tests ---------------------------------------------------------

_CIRCLING = dict(camera_class="perimeter", track_class="circling")


@pytest.mark.parametrize("persons_home", [0, 1, 2])
@pytest.mark.parametrize(
    "house_state",
    ["away", "vacation", "sleep", "home_night"],
)
def test_circling_severity_critical_failsafe_rows(house_state, persons_home):
    """CRITICAL-first fail-safe rows short-circuit above the override."""
    # Mutation anchor: neutering const.py:1586 (`if hs in ("away", ...)
    # return "CRITICAL"`) would make away/sleep/etc. fall through to
    # the perimeter/circling override → HIGH — this asserts CRITICAL.
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        house_state, persons_home=persons_home, **_CIRCLING,
    ) == "CRITICAL"


@pytest.mark.parametrize("persons_home", [0, 1, 2])
def test_circling_severity_home_day(persons_home):
    """CONSOL-1 §6 override: home_day/perimeter/circling → HIGH."""
    # Mutation anchor: changing the override "HIGH" → "LOW" at
    # const.py:1596 makes this test fail.
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "home_day", persons_home=persons_home, **_CIRCLING,
    ) == "HIGH"


@pytest.mark.parametrize("persons_home", [0, 1, 2])
def test_circling_severity_home_evening(persons_home):
    """CONSOL-1 §6 override: home_evening/perimeter/circling → HIGH."""
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "home_evening", persons_home=persons_home, **_CIRCLING,
    ) == "HIGH"


@pytest.mark.parametrize("persons_home", [0, 1, 2])
def test_circling_severity_arriving(persons_home):
    """arriving row wins → MEDIUM regardless of circling (O2 = no-widen)."""
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "arriving", persons_home=persons_home, **_CIRCLING,
    ) == "MEDIUM"


@pytest.mark.parametrize("persons_home", [0, 1, 2])
def test_circling_severity_waking_perimeter(persons_home):
    """waking + perimeter → CRITICAL (row 8, above the override)."""
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "waking", persons_home=persons_home, **_CIRCLING,
    ) == "CRITICAL"


@pytest.mark.parametrize("persons_home", [0, 1, 2])
def test_circling_severity_guest(persons_home):
    """guest row → NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY (read at test time).

    Build-pred #3: no hardcoded severity string here — a future
    GUEST-severity re-tune tracks through automatically.
    """
    expected = _const.NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "guest", persons_home=persons_home, **_CIRCLING,
    ) == expected
