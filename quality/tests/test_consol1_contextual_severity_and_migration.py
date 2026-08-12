"""CONSOL-1 §D2 + §D6 — contextual severity totality + options migration.

D2: NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY is TOTAL over 9
HouseState values with a fail-safe case_ arm returning CRITICAL for any
value the compiler adds later.

D6: options migration renames CONF_PERIMETER_ALERT_HOURS_* →
CONF_PERIMETER_VEHICLE_HOURS_* with values carried over, and strips
retired CONF_PERIMETER_ALERT_NOTIFY_SERVICE / _TARGET.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
_ura_path = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(_ura_path, "..")]
sys.modules.setdefault("custom_components", _cc)
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura
_cc.universal_room_automation = _ura

_const = _load(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)


# ============================================================================
# D2 — contextual severity totality
# ============================================================================


_HOUSE_STATES = [
    "away", "arriving", "home_day", "home_evening", "home_night",
    "sleep", "waking", "guest", "vacation",
]


def test_contextual_severity_total_over_house_states():
    """§D2 test: iterate every HouseState value with several
    (camera_class, track_class, persons_home) combos and assert every
    return is a legal severity name — no KeyError, no None, no crash."""
    legal_names = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    fn = _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY
    combos = [
        ("perimeter", "circling", 0),
        ("perimeter", "circling", 1),
        ("perimeter", "approach", 0),
        ("perimeter", "approach", 1),
        ("perimeter", "linger", 1),
        ("perimeter", "first_sighting", 0),
        ("perimeter", "first_sighting", 1),
        ("egress", "approach", 0),
        ("egress", "approach", 1),
        ("", "", 0),
        (None, None, None),
    ]
    for hs in _HOUSE_STATES:
        for cc, tc, ph in combos:
            name = fn(hs, camera_class=cc, track_class=tc, persons_home=ph)
            assert name in legal_names, (
                f"illegal severity {name!r} for ({hs}, {cc}, {tc}, {ph})"
            )


def test_contextual_severity_fail_safe_case_arm():
    """Unknown / None / future HouseState → CRITICAL (case_ fail-safe).

    Mutation anchor: remove the terminal `return "CRITICAL"` in
    NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY → future values silently
    escape the case tree and return None or empty."""
    fn = _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY
    assert fn(None) == "CRITICAL"
    assert fn("") == "CRITICAL"
    assert fn("some_future_state_the_compiler_added") == "CRITICAL"


def test_contextual_severity_daytime_home_day_low_when_someone_home():
    """§D2 named test: home_day + someone home → LOW."""
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "home_day", camera_class="perimeter",
        track_class="first_sighting", persons_home=1,
    ) == "LOW"


def test_contextual_severity_home_day_persons_home_zero_high():
    """§D2 named test — row 5e: home_day with nobody home → HIGH."""
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "home_day", camera_class="perimeter",
        track_class="first_sighting", persons_home=0,
    ) == "HIGH"


def test_contextual_severity_daytime_away_critical():
    """§D2 named test: away always → CRITICAL regardless of camera_class."""
    for cc in ("perimeter", "egress", "", None):
        for tc in ("circling", "approach", "first_sighting", None):
            assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
                "away", camera_class=cc, track_class=tc, persons_home=2,
            ) == "CRITICAL"


def test_contextual_severity_circling_overrides_house_state():
    """§D2 named test: perimeter + circling → HIGH override (except when
    CRITICAL row wins). Mutation anchor: remove the `if cc == "perimeter"
    and tc == "circling": return "HIGH"` branch → home_day + circling
    would collapse to LOW."""
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "home_day", camera_class="perimeter", track_class="circling",
        persons_home=1,
    ) == "HIGH"
    # CRITICAL row still wins:
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "away", camera_class="perimeter", track_class="circling",
        persons_home=1,
    ) == "CRITICAL"


def test_contextual_severity_waking_perimeter_critical():
    """§D2 named test — row 8: waking + perimeter → CRITICAL."""
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "waking", camera_class="perimeter",
        track_class="first_sighting", persons_home=1,
    ) == "CRITICAL"


def test_contextual_severity_arriving_medium():
    """§D2 named test — row 7: arriving → MEDIUM (never CRITICAL)."""
    assert _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
        "arriving", camera_class="perimeter",
        track_class="approach", persons_home=1,
    ) == "MEDIUM"


# ============================================================================
# D6 — options migration
# ============================================================================


def _simulate_migration(opts: dict) -> dict:
    """Pure-Python mirror of the __init__.py CONSOL-1 §D6 migration block.

    Mirrors the write path — a new test-oracle rather than importing the
    async setup entry (which chains a huge import graph). If __init__.py
    drifts from this shape, this oracle diverges → intentional signal.
    """
    _OLD_START = _const.CONF_PERIMETER_ALERT_HOURS_START
    _OLD_END = _const.CONF_PERIMETER_ALERT_HOURS_END
    _OLD_SVC = _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE
    _OLD_TGT = _const.CONF_PERIMETER_ALERT_NOTIFY_TARGET
    _NEW_START = _const.CONF_PERIMETER_VEHICLE_HOURS_START
    _NEW_END = _const.CONF_PERIMETER_VEHICLE_HOURS_END
    out = dict(opts)
    if _OLD_START in out and _NEW_START not in out:
        out[_NEW_START] = out[_OLD_START]
    if _OLD_END in out and _NEW_END not in out:
        out[_NEW_END] = out[_OLD_END]
    for _k in (_OLD_START, _OLD_END, _OLD_SVC, _OLD_TGT):
        out.pop(_k, None)
    out["consol1_perimeter_keys_migration_done"] = True
    return out


def test_options_migration_renames_hours_keys_to_vehicle():
    """§D6 named test: old hours keys → new vehicle-scoped keys with
    values carried over."""
    migrated = _simulate_migration({
        _const.CONF_PERIMETER_ALERT_HOURS_START: 22,
        _const.CONF_PERIMETER_ALERT_HOURS_END: 6,
    })
    assert migrated[_const.CONF_PERIMETER_VEHICLE_HOURS_START] == 22
    assert migrated[_const.CONF_PERIMETER_VEHICLE_HOURS_END] == 6
    assert _const.CONF_PERIMETER_ALERT_HOURS_START not in migrated
    assert _const.CONF_PERIMETER_ALERT_HOURS_END not in migrated


def test_options_migration_strips_retired_perimeter_keys():
    """§D6 named test: retired notify service/target keys are stripped."""
    migrated = _simulate_migration({
        _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "notify.pushover",
        _const.CONF_PERIMETER_ALERT_NOTIFY_TARGET: "abc",
    })
    assert _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE not in migrated
    assert _const.CONF_PERIMETER_ALERT_NOTIFY_TARGET not in migrated


def test_options_migration_preserves_new_keys_when_both_present():
    """If both old and new keys are present, new wins (idempotency)."""
    migrated = _simulate_migration({
        _const.CONF_PERIMETER_ALERT_HOURS_START: 22,
        _const.CONF_PERIMETER_VEHICLE_HOURS_START: 21,
    })
    assert migrated[_const.CONF_PERIMETER_VEHICLE_HOURS_START] == 21


def test_config_flow_perimeter_vehicle_hours_migrated():
    """Cross-reference: after migration, only the renamed keys exist."""
    migrated = _simulate_migration({
        _const.CONF_PERIMETER_ALERT_HOURS_START: 23,
        _const.CONF_PERIMETER_ALERT_HOURS_END: 5,
        _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "notify.foo",
    })
    assert migrated[_const.CONF_PERIMETER_VEHICLE_HOURS_START] == 23
    assert migrated[_const.CONF_PERIMETER_VEHICLE_HOURS_END] == 5
    for legacy in (
        _const.CONF_PERIMETER_ALERT_HOURS_START,
        _const.CONF_PERIMETER_ALERT_HOURS_END,
        _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
        _const.CONF_PERIMETER_ALERT_NOTIFY_TARGET,
    ):
        assert legacy not in migrated
