"""Round-2 fix-up (item #3, E7): ExcessSolarConfirmNumber._push reaches
the coordinator via `energy.set_solar_follow_confirm`.

Neuter drill: replace the `energy.set_solar_follow_confirm(self._value)`
call inside `ExcessSolarConfirmNumber._push` (number.py) with `pass` →
`test_e7_number_push_calls_set_solar_follow_confirm` goes RED.

This test avoids importing the full `number.py` (which pulls the entire
URA coordinator + HA stack). Instead it loads ONLY the class body via
`ast` + `exec`, isolated with the minimum names it references. That way
the test still drives the REAL method body from the production source —
mutating the source `.py` file changes what this test executes.
"""

from __future__ import annotations

import ast
import os
import types
from unittest.mock import MagicMock


_NUMBER_PY = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "custom_components",
    "universal_room_automation", "number.py",
))


def _load_excess_solar_confirm_number_class():
    """Extract the `class ExcessSolarConfirmNumber` node from number.py
    and exec it in an isolated namespace with the imports it needs."""
    src = open(_NUMBER_PY).read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ExcessSolarConfirmNumber":
            class_node = node
            break
    else:
        raise AssertionError("ExcessSolarConfirmNumber class not found in number.py")

    # Names referenced inside the class body — minimal stubs.
    class _NumberEntityStub:
        pass

    class _NumberMode:
        SLIDER = "slider"

    class _EntityCategory:
        CONFIG = "config"

    ns = {
        "__name__": "number_excess_solar_confirm_extract",
        "NumberEntity": _NumberEntityStub,
        "NumberMode": _NumberMode,
        "EntityCategory": _EntityCategory,
        "_LOGGER": MagicMock(),
        "HomeAssistant": MagicMock,
        "ConfigEntry": MagicMock,
        "DOMAIN": "universal_room_automation",
    }
    module_body = ast.Module(body=[class_node], type_ignores=[])
    code = compile(module_body, _NUMBER_PY, mode="exec")
    exec(code, ns)
    return ns["ExcessSolarConfirmNumber"]


def _make_instance():
    cls = _load_excess_solar_confirm_number_class()
    inst = cls.__new__(cls)
    inst._value = 7
    inst.hass = MagicMock()
    inst._entry = MagicMock()
    return inst


def test_e7_number_push_calls_set_solar_follow_confirm():
    """E7: `_push` invokes `energy.set_solar_follow_confirm(self._value)`.

    Neuter site: the `energy.set_solar_follow_confirm(self._value)`
    line inside `ExcessSolarConfirmNumber._push` (number.py).
    """
    inst = _make_instance()

    energy = MagicMock()
    energy.set_solar_follow_confirm = MagicMock()
    # Patch `_get_energy` to return our spy coordinator.
    inst._get_energy = lambda: energy

    ok = inst._push()

    assert ok is True
    assert energy.set_solar_follow_confirm.called, (
        "_push did not invoke energy.set_solar_follow_confirm"
    )
    ((v,), _kw) = energy.set_solar_follow_confirm.call_args
    assert v == 7


def test_e7_number_push_no_energy_returns_false():
    """E7 partner: `_push` returns False when the coordinator is absent."""
    inst = _make_instance()
    inst._get_energy = lambda: None
    assert inst._push() is False
