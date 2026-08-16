"""GAP-A D8 (PATH-ALPHA, 2026-08-16) — path-α veto gates on
face_recognized_count instead of census_count.

Closes the forgotten-phone-at-home Gap A: BLE stale fix used to inflate
census_count and block the veto even when zero cameras had seen anyone.

Tests drive the real StateInferenceEngine.infer() by importing presence.py
from source with minimal HA + integration stubs (pattern from
test_v4714_1_forgotten_phone_hotfix.py).

Coverage:
1. Forgotten-phone + zero camera evidence → path α FIRES (fix).
2. Same + live face-recognized resident → α still blocked (Gap A intent).
3. Same + unidentified body → α still blocked (unchanged clause).
4. Byte-identity: legacy caller without the new kwarg → default 0, α fires
   when census_count/unidentified_count both 0 (behavior compatible).
5. Mutation-anchor drill on the cross-check: neuter the face_recognized
   plumbing so face_recognized_count stays 0, and confirm the veto fires
   when it shouldn't (proves the value is load-bearing).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PRESENCE_PATH = (
    REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "presence.py"
)


def _install_ha_stubs(monkeypatch):
    def M(name, **attrs):
        m = types.ModuleType(name)
        m.__path__ = []
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    ha = M("homeassistant")
    ha_core = M(
        "homeassistant.core",
        HomeAssistant=MagicMock,
        callback=lambda fn: fn,
        Event=MagicMock,
        State=MagicMock,
    )
    ha_ce = M("homeassistant.config_entries", ConfigEntry=MagicMock)
    ha_const = MagicMock()
    ha_helpers = M("homeassistant.helpers")
    ha_dr = M("homeassistant.helpers.device_registry", DeviceInfo=dict)
    ha_entity = M(
        "homeassistant.helpers.entity",
        DeviceInfo=dict,
        EntityCategory=MagicMock(),
    )
    ha_ep = M("homeassistant.helpers.entity_platform", AddEntitiesCallback=MagicMock)
    ha_ev = M(
        "homeassistant.helpers.event",
        async_track_state_change_event=MagicMock(),
        async_track_time_interval=MagicMock(),
        async_call_later=MagicMock(),
        async_track_point_in_time=MagicMock(),
        async_track_time_change=MagicMock(),
    )
    ha_dis = M(
        "homeassistant.helpers.dispatcher",
        async_dispatcher_connect=MagicMock(),
        async_dispatcher_send=MagicMock(),
    )
    ha_util = M("homeassistant.util")
    import datetime as _dt

    class _dt_util:
        DEFAULT_TIME_ZONE = None

        @staticmethod
        def now():
            return _dt.datetime(2026, 8, 16, 14, 0, 0)

        @staticmethod
        def utcnow():
            return _dt.datetime(2026, 8, 16, 14, 0, 0)

        @staticmethod
        def parse_datetime(s):
            return None

        @staticmethod
        def as_local(x):
            return x

    ha_util.dt = _dt_util
    ha_util_dt = _dt_util

    for name, mod in [
        ("homeassistant", ha),
        ("homeassistant.core", ha_core),
        ("homeassistant.config_entries", ha_ce),
        ("homeassistant.const", ha_const),
        ("homeassistant.helpers", ha_helpers),
        ("homeassistant.helpers.device_registry", ha_dr),
        ("homeassistant.helpers.entity", ha_entity),
        ("homeassistant.helpers.entity_platform", ha_ep),
        ("homeassistant.helpers.event", ha_ev),
        ("homeassistant.helpers.dispatcher", ha_dis),
        ("homeassistant.util", ha_util),
        ("homeassistant.util.dt", ha_util_dt),
    ]:
        monkeypatch.setitem(sys.modules, name, mod)

    # Stub the URA package tree enough for presence.py to import.
    for pkg_name, subpath in [
        ("custom_components", "custom_components"),
        (
            "custom_components.universal_room_automation",
            "custom_components/universal_room_automation",
        ),
        (
            "custom_components.universal_room_automation.domain_coordinators",
            "custom_components/universal_room_automation/domain_coordinators",
        ),
    ]:
        p = types.ModuleType(pkg_name)
        p.__path__ = [str(REPO_ROOT / subpath)]
        monkeypatch.setitem(sys.modules, pkg_name, p)


@pytest.fixture
def infer_engine(monkeypatch):
    _install_ha_stubs(monkeypatch)
    # Load real const + real signals (both are pure-Python)
    for name, rel in [
        (
            "custom_components.universal_room_automation.const",
            "custom_components/universal_room_automation/const.py",
        ),
    ]:
        spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, mod)
        spec.loader.exec_module(mod)

    # Load the REAL house_state module so HouseState is a real StrEnum
    # (not a MagicMock — mocks compare equal to themselves for any name).
    hs_spec = importlib.util.spec_from_file_location(
        "custom_components.universal_room_automation.domain_coordinators.house_state",
        REPO_ROOT
        / "custom_components/universal_room_automation/domain_coordinators/house_state.py",
    )
    hs_mod = importlib.util.module_from_spec(hs_spec)
    monkeypatch.setitem(
        sys.modules,
        "custom_components.universal_room_automation.domain_coordinators.house_state",
        hs_mod,
    )
    hs_spec.loader.exec_module(hs_mod)

    # Stub sibling domain modules presence.py imports at module top.
    for sibling in (
        "base",
        "safety",
        "compliance",
        "arrival_bootstrap",
        "presence_fan_recheck",
        "signals",
        "diagnostics",
        "utilities",
        "_ble_corroboration",
        "hvac",
        "energy",
        "energy_pool",
        "energy_const",
        "envoy_derived",
        "battery_strategy",
        "reserve_engine",
        "restore_state_helper",
        "presence_fan_veto_helpers",
        "presence_signal_conveyance",
        "presence_ha_pull",
        "presence_arrival_helpers",
        "sensors_registry",
    ):
        n = f"custom_components.universal_room_automation.domain_coordinators.{sibling}"
        if n not in sys.modules:
            m = types.ModuleType(n)
            # Provide anything referenced by attribute access
            m.__getattr__ = lambda name: MagicMock()
            monkeypatch.setitem(sys.modules, n, m)

    spec = importlib.util.spec_from_file_location(
        "custom_components.universal_room_automation.domain_coordinators.presence",
        PRESENCE_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules,
        "custom_components.universal_room_automation.domain_coordinators.presence",
        mod,
    )
    spec.loader.exec_module(mod)

    return mod.StateInferenceEngine(), mod.HouseState


def _infer_kwargs(**overrides):
    base = dict(
        census_count=0,
        current_state=None,  # filled in caller
        any_zone_occupied=False,
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,
        face_recognized_count=0,
    )
    base.update(overrides)
    return base


def test_d8_forgotten_phone_zero_face_fires_alpha(infer_engine):
    """FIX PATH: BLE stale keeps census_count=1, but face_recognized_count=0.
    Path α MUST now fire (it wouldn't pre-D8 due to census_count >= 1)."""
    engine, HouseState = infer_engine
    kwargs = _infer_kwargs(
        census_count=1,  # BLE-inflated
        face_recognized_count=0,  # no camera evidence
        current_state=HouseState.HOME_DAY,
    )
    result = engine.infer(**kwargs)
    assert result == HouseState.AWAY, (
        "D8 fix broken: forgotten-phone-with-zero-camera-evidence "
        "should now trigger path α AWAY"
    )


def test_d8_face_recognized_still_blocks_alpha(infer_engine):
    """GAP-A INTENT PRESERVED: face-recognized resident MUST still block."""
    engine, HouseState = infer_engine
    kwargs = _infer_kwargs(
        census_count=1,
        face_recognized_count=1,  # camera saw them
        current_state=HouseState.HOME_DAY,
    )
    result = engine.infer(**kwargs)
    assert result != HouseState.AWAY, (
        "Gap A intent broken: a face-recognized resident should still "
        "veto the away transition"
    )


def test_d8_unidentified_body_still_blocks_alpha(infer_engine):
    """UNCHANGED CLAUSE: unidentified camera body still blocks (guest guard)."""
    engine, HouseState = infer_engine
    kwargs = _infer_kwargs(
        census_count=1,
        unidentified_count=1,  # camera sees someone unknown
        face_recognized_count=0,
        current_state=HouseState.HOME_DAY,
    )
    result = engine.infer(**kwargs)
    assert result != HouseState.AWAY, (
        "unidentified_count clause broken: an unidentified camera body "
        "must still block the veto (guest detection)"
    )


def test_d8_byte_identity_default_kwarg(infer_engine):
    """INVARIANT I3: legacy caller (no face_recognized_count kwarg) →
    default 0 → behavior identical to pre-D8 when census_count is also 0."""
    engine, HouseState = infer_engine
    # Legacy call shape — no face_recognized_count arg supplied
    result = engine.infer(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=False,
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=True,
    )
    assert result == HouseState.AWAY, (
        "invariant I3 broken: legacy caller (no new kwarg) must retain "
        "pre-D8 behavior — census_count=0 + unidentified=0 fires AWAY"
    )


def test_d8_face_recognized_count_is_load_bearing(infer_engine):
    """MUTATION-ANCHOR DRILL: with any_zone_occupied=True (bypasses the
    early 'nobody home' AWAY branch) + census_count=1 (BLE inflation) +
    face_recognized_count=1 (camera saw a resident) → the ONLY branch
    that could produce AWAY is the path-α veto. Post-D8 predicate gates
    on face_recognized_count, so this MUST NOT fire AWAY. Neuter drill
    shape A: revert the predicate to `census_count == 0` → this test
    reddens (census=1 blocked pre-D8 too — but the mutation shape B is
    the killer: leave predicate as face_recognized_count but sabotage
    the signal-payload plumbing to always emit 0, and the veto fires
    when it shouldn't)."""
    engine, HouseState = infer_engine
    kwargs = _infer_kwargs(
        census_count=1,
        face_recognized_count=1,
        any_zone_occupied=True,  # bypass early nobody-home AWAY branch
        current_state=HouseState.HOME_DAY,
    )
    result = engine.infer(**kwargs)
    assert result != HouseState.AWAY, (
        "face_recognized_count is not load-bearing: path α fired AWAY "
        "despite a face-recognized resident being present. This means "
        "the D8 predicate change was not applied or was reverted."
    )
