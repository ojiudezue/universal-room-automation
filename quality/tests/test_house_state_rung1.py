"""v5.37.0 House-State Rung 1 — build-time proofs.

Three targeted tests that drive REAL production methods (Bug Class #62):

1. ``test_energy_house_state_reads_canonical`` — AST-extract
   ``EnergyCoordinator._get_house_state`` and prove it reads
   ``CoordinatorManager.house_state`` (the canonical source), returning
   the string when the manager is present and "" when it is missing.
2. ``test_optimization_night_literal_fixed`` — the security-posture gate
   used the literal "night" which never matched the ``HouseState`` enum
   value "home_night"; assert "home_night" is in the tuple and "night"
   (as its own token) is not.
3. ``test_security_house_state_subscribed_and_flag_gated`` — AST-extract
   ``SecurityCoordinator._on_house_state_changed_signal`` and prove:
     - flag off → NO ``manager.queue_intent`` call
     - flag on  → exactly one ``Intent`` queued with
                  ``source="house_state_change"`` + ``data["new_state"]``
   The observation-mode gate lives inside ``evaluate()`` (line ~695) and
   is exercised by ``test_security.py``; here we assert the wiring
   invariant.
"""

from __future__ import annotations

import ast as _ast
import os
import re
import textwrap as _tw
from types import SimpleNamespace as _NS

import pytest

_HERE = os.path.dirname(__file__)
_URA = os.path.abspath(
    os.path.join(
        _HERE, "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators",
    )
)


def _extract_method(path: str, class_name: str, method_name: str) -> str:
    src = open(path).read()
    tree = _ast.parse(src)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ClassDef) and node.name == class_name:
            for m in node.body:
                if (
                    isinstance(m, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                    and m.name == method_name
                ):
                    seg = _ast.get_source_segment(src, m)
                    assert seg is not None
                    return _tw.dedent(seg)
    raise AssertionError(f"{class_name}.{method_name} not found in {path}")


# ---------------------------------------------------------------------------
# 1. energy._get_house_state reads canonical CoordinatorManager.house_state
# ---------------------------------------------------------------------------

def _load_get_house_state():
    seg = _extract_method(
        os.path.join(_URA, "energy.py"),
        "EnergyCoordinator",
        "_get_house_state",
    )
    # Stub the sole `from ..const import DOMAIN as _DOMAIN_KEY` — inject
    # a fake package tree so the relative import resolves.
    import sys
    import types
    pkg_root = "_ura_stub_pkg"
    if pkg_root not in sys.modules:
        root = types.ModuleType(pkg_root)
        root.__path__ = []  # mark as package
        sub = types.ModuleType(pkg_root + ".sub")
        sub.__path__ = []
        const = types.ModuleType(pkg_root + ".sub.const")
        const.DOMAIN = "universal_room_automation"
        sys.modules[pkg_root] = root
        sys.modules[pkg_root + ".sub"] = sub
        sys.modules[pkg_root + ".sub.const"] = const
    # Rewrite the relative import inside the segment source to absolute.
    seg2 = seg.replace(
        "from ..const import DOMAIN as _DOMAIN_KEY",
        "from _ura_stub_pkg.sub.const import DOMAIN as _DOMAIN_KEY",
    )
    ns: dict = {}
    exec(seg2, ns)
    return ns["_get_house_state"]


def test_energy_house_state_reads_canonical():
    fn = _load_get_house_state()

    # Case A: manager present, house_state = "guest"
    mgr = _NS(house_state="guest")
    hass = _NS(data={"universal_room_automation": {"coordinator_manager": mgr}})
    stub = _NS(hass=hass)
    assert fn(stub) == "guest"

    # Case B: manager present, house_state = "home_night"
    mgr2 = _NS(house_state="home_night")
    hass2 = _NS(data={"universal_room_automation": {"coordinator_manager": mgr2}})
    assert fn(_NS(hass=hass2)) == "home_night"

    # Case C: manager missing → ""
    hass_missing = _NS(data={"universal_room_automation": {}})
    assert fn(_NS(hass=hass_missing)) == ""

    # Case D: DOMAIN bucket missing → ""
    assert fn(_NS(hass=_NS(data={}))) == ""

    # Case E: the OLD bug — reading presence._house_state — must NOT be
    # what the method does anymore. Prove by putting an obvious sentinel
    # on a presence coordinator and NO house_state on the manager: the
    # function should NOT return the sentinel.
    mgr3 = _NS(coordinators={"presence": _NS(_house_state="SENTINEL_OLD_BUG")})
    hass3 = _NS(data={"universal_room_automation": {"coordinator_manager": mgr3}})
    # getattr(mgr3, "house_state", "") → "" (no house_state attr on mgr3)
    assert fn(_NS(hass=hass3)) == ""


# ---------------------------------------------------------------------------
# 2. optimization.py "night" -> "home_night"
# ---------------------------------------------------------------------------

def test_optimization_night_literal_fixed():
    src = open(os.path.join(_URA, "optimization.py")).read()
    # The gated tuple should now include the canonical enum value.
    assert re.search(
        r'gated\s*=\s*house_state\.lower\(\)\s*in\s*\(\s*"away"\s*,\s*"home_night"\s*,\s*"sleep"\s*\)',
        src,
    ), "expected the security-posture gate tuple to include 'home_night'"
    # And the standalone "night" token must NOT be in that tuple.
    m = re.search(
        r'gated\s*=\s*house_state\.lower\(\)\s*in\s*\(([^)]*)\)',
        src,
    )
    assert m is not None
    inside = m.group(1)
    tokens = [t.strip().strip('"').strip("'") for t in inside.split(",")]
    assert "night" not in tokens, (
        f"bare 'night' literal still present in gate tuple: {tokens!r}"
    )
    assert "home_night" in tokens


# ---------------------------------------------------------------------------
# 3. security._on_house_state_changed_signal — subscribed + flag-gated
# ---------------------------------------------------------------------------

def _load_signal_handler():
    seg = _extract_method(
        os.path.join(_URA, "security.py"),
        "SecurityCoordinator",
        "_on_house_state_changed_signal",
    )
    # Provide DOMAIN and Intent stubs plus a _LOGGER shim.
    class _Intent:
        def __init__(self, source="", entity_id="", data=None, coordinator_id=""):
            self.source = source
            self.entity_id = entity_id
            self.data = data or {}
            self.coordinator_id = coordinator_id
    ns = {
        "DOMAIN": "universal_room_automation",
        "Intent": _Intent,
        "Any": object,
        "callback": (lambda f: f),
        "_LOGGER": _NS(
            info=lambda *a, **k: None,
            debug=lambda *a, **k: None,
        ),
    }
    exec(seg, ns)
    return ns["_on_house_state_changed_signal"], _Intent


def _stub_security(flag: bool, queued: list):
    mgr = _NS(queue_intent=lambda intent: queued.append(intent))
    return _NS(
        _auto_follow_house_state=flag,
        COORDINATOR_ID="security",
        hass=_NS(data={"universal_room_automation": {"coordinator_manager": mgr}}),
    )


def test_security_house_state_subscribed_and_flag_gated():
    # Wiring proof 1: the signal import + subscription line are present.
    sec_src = open(os.path.join(_URA, "security.py")).read()
    assert "SIGNAL_HOUSE_STATE_CHANGED" in sec_src, (
        "SecurityCoordinator must import SIGNAL_HOUSE_STATE_CHANGED"
    )
    assert "_on_house_state_changed_signal" in sec_src
    # Subscription must be registered inside async_setup, appended to
    # _unsub_listeners so async_teardown -> _cancel_listeners fires it.
    assert re.search(
        r"_unsub_listeners\.append\(\s*async_dispatcher_connect\(\s*self\.hass,\s*SIGNAL_HOUSE_STATE_CHANGED,",
        sec_src,
    ), "SIGNAL_HOUSE_STATE_CHANGED must be subscribed via _unsub_listeners"

    fn, Intent = _load_signal_handler()

    # Case A: flag OFF → NO intent queued (no arming call path invoked)
    queued: list = []
    stub_off = _stub_security(flag=False, queued=queued)
    fn(stub_off, {"new_state": "away", "old_state": "home_day",
                  "trigger": "test", "confidence": 0.9})
    assert queued == [], (
        "flag off must produce NO manager.queue_intent call — arming "
        "path must stay dormant"
    )

    # Case B: flag ON + valid payload → exactly one Intent queued with
    # source="house_state_change" and data["new_state"]="away".
    queued2: list = []
    stub_on = _stub_security(flag=True, queued=queued2)
    fn(stub_on, {"new_state": "away", "old_state": "home_day",
                 "trigger": "test", "confidence": 0.9})
    assert len(queued2) == 1
    intent = queued2[0]
    assert intent.source == "house_state_change"
    assert intent.data.get("new_state") == "away"
    assert intent.coordinator_id == "security"

    # Case C: flag ON but payload has no new_state → no queue (safe).
    queued3: list = []
    stub_on2 = _stub_security(flag=True, queued=queued3)
    fn(stub_on2, {})
    assert queued3 == []

    # Case D: flag ON but manager missing → no crash, no queue.
    queued4: list = []
    stub_no_mgr = _NS(
        _auto_follow_house_state=True,
        COORDINATOR_ID="security",
        hass=_NS(data={"universal_room_automation": {}}),
    )
    fn(stub_no_mgr, {"new_state": "home_night"})
    assert queued4 == []
