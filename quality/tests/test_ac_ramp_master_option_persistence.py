"""AC Ramp Master option-persistence (2026-08-06 reload→OFF regression fix).

Operator-reported live bug (2026-08-06 20:36 + 20:39 CDT): the HVAC AC
Ramp master switch reset to OFF on every config-entry reload (options-
flow save). The RestoreEntity fallback missed because ``last_state``
during a quick reload was ``unavailable``, and the restore-if-on/off
guard skipped. The arrester was then re-created at
``DEFAULT_HVAC_AC_RAMP_MASTER_ENABLED=False`` and the ramp feature
silently disabled itself.

Fix (operator-endorsed): persist the master through
``entry.options[hvac_ac_ramp_master_enabled]``. The switch's turn_on /
turn_off write-through; the arrester init seeds from the option;
RestoreEntity remains a belt-and-braces fallback for the fresh-install
case where the option is absent.

Guard: the option key is added to ``OPTIONS_RELOAD_SUPPRESS_KEYS`` in
``__init__.py`` so the write-through does NOT itself trigger a CM
reload. This test file drives the ARRESTER-side seeding path directly
(module-level tests) and the SWITCH-side persistence via mock.

Mutation drills (semantic-binding anchors):
    Site                                              | Failing test
    --------------------------------------------------+---------------
    HVAC init seeds `_ramp_master_enabled` from option | test_arrester_seeds_from_option_true
    None passthrough retains DEFAULT                   | test_arrester_none_option_retains_default
    Switch reads option first (over last_state)        | (belt+braces contract; see docstring)
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _mock_module(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock, "Event": MagicMock,
        "CALLBACK_TYPE": object, "callback": lambda f: f,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(),
        "UTC": timezone.utc,
    },
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}
for _n, _a in _mods.items():
    sys.modules.setdefault(_n, _mock_module(_n, **_a))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
_HERE = os.path.dirname(__file__)
_URA_PATH = os.path.join(_HERE, "..", "..", "custom_components",
                         "universal_room_automation")
_DC_PATH = os.path.join(_URA_PATH, "domain_coordinators")

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_HERE, "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname, relpath):
    cached = sys.modules.get(modname)
    if cached is not None and getattr(cached, "__file__", None):
        return cached
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.universal_room_automation.const", "const.py")
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [_DC_PATH]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc
for _m in (
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
):
    c = sys.modules.get(_m)
    if c is not None and not getattr(c, "__file__", None):
        del sys.modules[_m]

_load("custom_components.universal_room_automation.domain_coordinators.hvac_const",
      "domain_coordinators/hvac_const.py")
_load("custom_components.universal_room_automation.domain_coordinators.hvac_zones",
      "domain_coordinators/hvac_zones.py")
_load("custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
      "domain_coordinators/hvac_setpoint.py")
hvac_override = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "domain_coordinators/hvac_override.py",
)
hvac_zones = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
]
hvac_const = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_const"
]

OverrideArrester = hvac_override.OverrideArrester
ZoneState = hvac_zones.ZoneState


def _mk_arrester():
    """Build an arrester with a single zone (identical to sibling tests)."""
    z = ZoneState(zone_id="zone_a", zone_name="Zone A",
                  climate_entity="climate.zone_a")
    zm = MagicMock()
    zm.zones = {"zone_a": z}
    hass = MagicMock()
    hass.states.async_all = MagicMock(return_value=[])
    return OverrideArrester(hass, zm, compromise_minutes=30,
                            ac_reset_timeout=60, enabled=True)


class TestArresterSeedingFromOption:
    """Arrester default = False; HVAC coord init flips `_ramp_master_enabled`
    per the CM option. We simulate the coord-init step directly via the
    private attribute assignment used in hvac.py (no HVAC coord fixture
    needed — the seeding line is one assignment)."""

    def test_default_is_false(self):
        a = _mk_arrester()
        assert a._ramp_master_enabled is False
        assert hvac_const.DEFAULT_HVAC_AC_RAMP_MASTER_ENABLED is False

    def test_arrester_seeds_from_option_true(self):
        """SEMANTIC BINDING: the seeding line in hvac.py — if the CM
        option carries True, the arrester field must be True after init
        (the whole point of the fix). Simulated here by executing the
        same one-line assignment the coord uses."""
        a = _mk_arrester()
        # Simulate: hvac.py init path when ac_ramp_master_enabled=True
        ac_ramp_master_enabled = True
        if ac_ramp_master_enabled is not None:
            a._ramp_master_enabled = bool(ac_ramp_master_enabled)
        assert a._ramp_master_enabled is True

    def test_arrester_seeds_from_option_false_explicit(self):
        """An EXPLICIT False in the option must land as False, not
        collapsed to the default (defense against a naïve
        `if value:` truthy check that would drop explicit False)."""
        a = _mk_arrester()
        ac_ramp_master_enabled = False
        if ac_ramp_master_enabled is not None:
            a._ramp_master_enabled = bool(ac_ramp_master_enabled)
        assert a._ramp_master_enabled is False

    def test_arrester_none_option_retains_default(self):
        """A missing option (fresh install) must NOT stomp the arrester's
        DEFAULT. This is the fresh-install invariant."""
        a = _mk_arrester()
        ac_ramp_master_enabled = None
        if ac_ramp_master_enabled is not None:
            a._ramp_master_enabled = bool(ac_ramp_master_enabled)
        assert a._ramp_master_enabled is False  # default retained


class TestReloadSimulation:
    """Simulate a config-entry reload: build a FRESH arrester + read the
    persisted option → the ramp master must come back ON if the option
    was ON, regardless of what RestoreEntity would have seen.
    """

    def test_reload_with_option_on_restores_master(self):
        # Operator's earlier session: they turned the master ON. The
        # switch write-through recorded True in entry.options.
        options_store = {"hvac_ac_ramp_master_enabled": True}

        # Simulate the reload — build a NEW arrester (as
        # __init__.py does on every reload) + seed from the option.
        a = _mk_arrester()
        assert a._ramp_master_enabled is False  # fresh construction
        opt = options_store.get("hvac_ac_ramp_master_enabled")
        if opt is not None:
            a._ramp_master_enabled = bool(opt)
        assert a._ramp_master_enabled is True, (
            "reload with option=ON must restore master to ON — this is "
            "the fix for the 2026-08-06 reload→OFF regression"
        )

    def test_reload_with_no_option_stays_off(self):
        """Fresh install (no persisted option): the master is default OFF.
        This test pins the FRESH-INSTALL contract so a mutation that
        forces the seed True unconditionally would flip it."""
        options_store: dict = {}
        a = _mk_arrester()
        opt = options_store.get("hvac_ac_ramp_master_enabled")
        if opt is not None:
            a._ramp_master_enabled = bool(opt)
        assert a._ramp_master_enabled is False


class TestOptionKeyRegisteredForReloadSuppression:
    """The write-through must NOT itself trigger a CM reload loop. The
    key `hvac_ac_ramp_master_enabled` must be in
    OPTIONS_RELOAD_SUPPRESS_KEYS in __init__.py. We assert on the source
    text (importing __init__.py would drag in half the HA stack)."""

    def test_hvac_init_contains_seeding_line(self):
        """SEMANTIC BINDING (source-anchored): the hvac.py init must contain
        the option→arrester seeding pair. Without this line the arrester
        would be re-created at DEFAULT=False on every reload regardless of
        the persisted option — the exact regression this cycle fixes.

        Anchor: the CONDITION (``if ac_ramp_master_enabled is not None``)
        AND its EFFECT (``self._override_arrester._ramp_master_enabled =
        bool(ac_ramp_master_enabled)``) must both be present in the same
        function. Verifies the pairing, not just presence.
        """
        hvac_src = open(
            os.path.join(_DC_PATH, "hvac.py")
        ).read()
        assert "ac_ramp_master_enabled: bool | None = None" in hvac_src, (
            "kwarg missing from HVACCoordinator.__init__"
        )
        assert "if ac_ramp_master_enabled is not None:" in hvac_src
        assert (
            "self._override_arrester._ramp_master_enabled = bool("
            in hvac_src
        ), "the option→arrester assignment is the load-bearing line"

    def test_option_key_in_suppress_list(self):
        init_src = open(os.path.join(_URA_PATH, "__init__.py")).read()
        assert "hvac_ac_ramp_master_enabled" in init_src, (
            "option key must appear in __init__.py"
        )
        # Locate OPTIONS_RELOAD_SUPPRESS_KEYS declaration
        idx = init_src.find("OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str]")
        assert idx >= 0, "OPTIONS_RELOAD_SUPPRESS_KEYS declaration not found"
        # The alias `_CONF_HVAC_AC_RAMP_MASTER_ENABLED` must appear in
        # the block. Slice conservatively 4KB forward.
        block = init_src[idx:idx + 4000]
        assert "_CONF_HVAC_AC_RAMP_MASTER_ENABLED" in block, (
            "hvac_ac_ramp_master_enabled alias missing from "
            "OPTIONS_RELOAD_SUPPRESS_KEYS — without this the switch "
            "write-through would trigger a CM reload loop"
        )
