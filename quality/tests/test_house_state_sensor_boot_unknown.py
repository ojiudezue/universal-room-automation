"""HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1 — None at boot, machine value otherwise.

Three house-state sensors previously returned ``"away"`` when the
coordinator manager had not yet attached (pre-boot / early-restart):

* ``HouseStateSensor``                (sensor.py:~5416)
* ``PresenceHouseStateSensor``        (sensor.py:~5510)
* ``IntegrationHouseStateSensor``     (sensor.py:~6525)

That wrote a false Away into recorder history at every restart. These
tests pin the new contract: no manager ⇒ ``None`` (surfaces as HA
``unknown``), never a mode name. Behavioural anchor: if any site
reverts to ``"away"``, the test fails.

The sensors read ``hass.data[DOMAIN]["coordinator_manager"]`` directly
so we instantiate without calling ``__init__`` and set a minimal
``hass`` stub — no HA harness required.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.universal_room_automation import sensor as _sensor
from custom_components.universal_room_automation.const import DOMAIN


class _FakeHass:
    def __init__(self, manager=None):
        self.data = {DOMAIN: {"coordinator_manager": manager}} if manager else {DOMAIN: {}}


def _mk(cls, hass):
    inst = cls.__new__(cls)
    inst.hass = hass
    return inst


_TARGETS = [
    _sensor.HouseStateSensor,
    _sensor.PresenceHouseStateSensor,
    _sensor.IntegrationHouseStateSensor,
]


def test_no_manager_returns_none_not_away():
    hass = _FakeHass(manager=None)
    for cls in _TARGETS:
        inst = _mk(cls, hass)
        assert inst.native_value is None, f"{cls.__name__} returned {inst.native_value!r}"
        # extra_state_attributes still returns {} pre-boot (unchanged)
        assert inst.extra_state_attributes == {}


def test_with_manager_returns_machine_value():
    machine = SimpleNamespace(to_dict=lambda: {"last": "boot"})
    manager = SimpleNamespace(
        house_state=SimpleNamespace(value="home"),
        house_state_machine=machine,
        coordinators={},  # PresenceHouseStateSensor.extra_state_attributes reads this
    )
    hass = _FakeHass(manager=manager)
    for cls in _TARGETS:
        inst = _mk(cls, hass)
        assert inst.native_value == "home", f"{cls.__name__} returned {inst.native_value!r}"


def test_safety_status_pre_boot_returns_none():
    """F5: SafetyStatusSensor returned "normal" when the manager (or
    the safety coordinator slot) was missing, writing a false
    all-clear into history at every restart. Now returns None.
    """
    cls = _sensor.SafetyStatusSensor
    # Case A: no manager at all.
    inst = _mk(cls, _FakeHass(manager=None))
    assert inst.native_value is None

    # Case B: manager present but safety coordinator slot empty.
    manager = SimpleNamespace(coordinators={})
    inst2 = _mk(cls, _FakeHass(manager=manager))
    assert inst2.native_value is None

    # Case C: safety coordinator present ⇒ its real value.
    safety = SimpleNamespace(get_safety_status=lambda: "normal")
    manager2 = SimpleNamespace(coordinators={"safety": safety})
    inst3 = _mk(cls, _FakeHass(manager=manager2))
    assert inst3.native_value == "normal"


def test_security_armed_state_pre_boot_returns_none():
    """F5: SecurityArmedStateSensor returned "disarmed" when the
    manager (or the security coordinator slot) was missing. Now None.
    """
    cls = _sensor.SecurityArmedStateSensor
    inst = _mk(cls, _FakeHass(manager=None))
    assert inst.native_value is None

    manager = SimpleNamespace(coordinators={})
    inst2 = _mk(cls, _FakeHass(manager=manager))
    assert inst2.native_value is None

    security = SimpleNamespace(armed_state=SimpleNamespace(value="armed_home"))
    manager2 = SimpleNamespace(coordinators={"security": security})
    inst3 = _mk(cls, _FakeHass(manager=manager2))
    assert inst3.native_value == "armed_home"


def test_anchor_no_literal_away_fallback_in_native_value():
    """Behavioural anchor: no house-state ``native_value`` branch returns
    ``"away"`` as the manager-None fallback. If any site is reverted to
    ``return "away"`` for the ``manager is None`` guard, this test fails.
    """
    import inspect
    import re
    pat = re.compile(r"return\s+['\"]away['\"]")
    for cls in _TARGETS:
        src = inspect.getsource(cls.native_value.fget)
        assert not pat.search(src), (
            f"{cls.__name__}.native_value must not `return \"away\"`: {src}"
        )
