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


# Fix-up C-SN-MIG + A2 (2026-08-11): tests drive the REAL migration helper
# `migrate_consol1_perimeter_keys` in perimeter_alert.py — the pre-fix-up
# `_simulate_migration` mirror has been deleted so a mutation on the real
# helper flips these tests red. Loading perimeter_alert.py requires the
# same HA stubs as test_perimeter_alert_nm_routing; import via the sibling
# fixture module (it already installs everything).
from test_perimeter_alert_nm_routing import _perimeter  # noqa: E402
migrate_consol1_perimeter_keys = _perimeter.migrate_consol1_perimeter_keys


def _migrate(opts: dict) -> dict:
    """Thin wrapper: run the real helper + append the done-marker the
    __init__ caller adds so test-oracles are apples-to-apples."""
    out, _changed = migrate_consol1_perimeter_keys(opts)
    out["consol1_perimeter_keys_migration_done"] = True
    return out


def test_options_migration_renames_hours_keys_to_vehicle():
    """§D6 named test: old hours keys → new vehicle-scoped keys with
    values carried over.

    MUTATION ANCHOR (perimeter_alert.py migrate_consol1_perimeter_keys):
    remove the `if _OLD_START in out and _NEW_START not in out` copy
    line → this test flips red."""
    migrated = _migrate({
        _const.CONF_PERIMETER_ALERT_HOURS_START: 22,
        _const.CONF_PERIMETER_ALERT_HOURS_END: 6,
    })
    assert migrated[_const.CONF_PERIMETER_VEHICLE_HOURS_START] == 22
    assert migrated[_const.CONF_PERIMETER_VEHICLE_HOURS_END] == 6
    assert _const.CONF_PERIMETER_ALERT_HOURS_START not in migrated
    assert _const.CONF_PERIMETER_ALERT_HOURS_END not in migrated


def test_options_migration_strips_retired_perimeter_keys():
    """§D6 named test: retired notify service/target keys are stripped.

    MUTATION ANCHOR: remove the `for _k in (_OLD_START, _OLD_END,
    _OLD_SVC, _OLD_TGT): out.pop(_k, None)` block → red."""
    migrated = _migrate({
        _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "notify.pushover",
        _const.CONF_PERIMETER_ALERT_NOTIFY_TARGET: "abc",
    })
    assert _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE not in migrated
    assert _const.CONF_PERIMETER_ALERT_NOTIFY_TARGET not in migrated


def test_options_migration_preserves_new_keys_when_both_present():
    """If both old and new keys are present, new wins (idempotency)."""
    migrated = _migrate({
        _const.CONF_PERIMETER_ALERT_HOURS_START: 22,
        _const.CONF_PERIMETER_VEHICLE_HOURS_START: 21,
    })
    assert migrated[_const.CONF_PERIMETER_VEHICLE_HOURS_START] == 21


def test_options_migration_reports_changed_flag():
    """Helper's 2-tuple return: `changed=True` iff at least one action
    occurred; `False` on a no-op input."""
    _, changed_none = migrate_consol1_perimeter_keys({})
    assert changed_none is False
    _, changed_rename = migrate_consol1_perimeter_keys({
        _const.CONF_PERIMETER_ALERT_HOURS_START: 22,
    })
    assert changed_rename is True
    _, changed_strip = migrate_consol1_perimeter_keys({
        _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "notify.x",
    })
    assert changed_strip is True


def test_config_flow_perimeter_vehicle_hours_migrated():
    """Cross-reference: after migration, only the renamed keys exist."""
    migrated = _migrate({
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


# ============================================================================
# Fix-up C-MED — per-§6-row specific severity assertions.
# Every row gets exactly one specific-severity pin so a row mutation is
# caught. Rows 2/3/4 (vacation/sleep/home_night) added; 5b, 5d, all 6-series,
# 8b, 9-guest.
# ============================================================================

fn = _const.NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY


def test_row_1_away_any():
    assert fn("away", camera_class="perimeter", track_class="linger", persons_home=1) == "CRITICAL"


def test_row_2_vacation_any():
    assert fn("vacation", camera_class="perimeter", track_class="approach", persons_home=0) == "CRITICAL"


def test_row_3_sleep_any():
    assert fn("sleep", camera_class="egress", track_class="first_sighting", persons_home=2) == "CRITICAL"


def test_row_4_home_night_any():
    assert fn("home_night", camera_class="perimeter", track_class="circling", persons_home=3) == "CRITICAL"


def test_row_5a_home_day_perimeter_circling_high_override():
    """A1 narrowed override — home_day + perimeter + circling → HIGH."""
    assert fn("home_day", camera_class="perimeter", track_class="circling", persons_home=1) == "HIGH"


def test_row_5b_home_day_perimeter_approach_persons_home_medium():
    assert fn("home_day", camera_class="perimeter", track_class="approach", persons_home=1) == "MEDIUM"


def test_row_5b_home_day_perimeter_linger_persons_home_medium():
    assert fn("home_day", camera_class="perimeter", track_class="linger", persons_home=2) == "MEDIUM"


def test_row_5c_home_day_perimeter_first_sighting_persons_home_low():
    assert fn("home_day", camera_class="perimeter", track_class="first_sighting", persons_home=1) == "LOW"


def test_row_5d_home_day_egress_persons_home_low():
    assert fn("home_day", camera_class="egress", track_class="approach", persons_home=1) == "LOW"


def test_row_5e_home_day_persons_home_zero_high():
    assert fn("home_day", camera_class="perimeter", track_class="first_sighting", persons_home=0) == "HIGH"


def test_row_6a_home_evening_perimeter_circling_high_override():
    assert fn("home_evening", camera_class="perimeter", track_class="circling", persons_home=1) == "HIGH"


def test_row_6b_home_evening_perimeter_approach_persons_home_medium():
    assert fn("home_evening", camera_class="perimeter", track_class="approach", persons_home=2) == "MEDIUM"


def test_row_6c_home_evening_perimeter_first_sighting_persons_home_low():
    assert fn("home_evening", camera_class="perimeter", track_class="first_sighting", persons_home=1) == "LOW"


def test_row_6d_home_evening_egress_persons_home_low():
    assert fn("home_evening", camera_class="egress", track_class="approach", persons_home=1) == "LOW"


def test_row_6e_home_evening_persons_home_zero_high():
    assert fn("home_evening", camera_class="perimeter", track_class="first_sighting", persons_home=0) == "HIGH"


def test_row_7_arriving_medium():
    assert fn("arriving", camera_class="perimeter", track_class="approach", persons_home=1) == "MEDIUM"


def test_row_8_waking_perimeter_critical():
    assert fn("waking", camera_class="perimeter", track_class="first_sighting", persons_home=1) == "CRITICAL"


def test_row_8b_waking_egress_medium():
    assert fn("waking", camera_class="egress", track_class="first_sighting", persons_home=1) == "MEDIUM"


def test_row_9_guest_uses_guest_severity_const():
    """Row 9 delegates to NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY."""
    assert fn("guest", camera_class="perimeter", track_class="first_sighting", persons_home=1) == (
        _const.NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY
    )


# ============================================================================
# Fix-up A1 — narrowed circling override anchors.
# Circling at perimeter DOES NOT collapse arriving/guest rows post-narrowing.
# ============================================================================


def test_A1_arriving_perimeter_circling_stays_medium():
    """Row 7 (arriving) must NOT be widened by circling override.

    MUTATION ANCHOR: revert the A1 narrowing (drop the
    `and hs in ("home_day","home_evening")` guard) → this flips to HIGH.
    """
    assert fn("arriving", camera_class="perimeter", track_class="circling", persons_home=1) == "MEDIUM"


def test_A1_guest_perimeter_circling_stays_guest_severity():
    """Row 9 (guest) must keep GUEST severity even under circling."""
    assert fn("guest", camera_class="perimeter", track_class="circling", persons_home=1) == (
        _const.NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY
    )


def test_A1_waking_perimeter_circling_still_critical():
    """Row 8 (waking + perimeter) is CRITICAL — circling does not lower."""
    assert fn("waking", camera_class="perimeter", track_class="circling", persons_home=1) == "CRITICAL"


# ============================================================================
# Fix-up A4 — burst-demote night_window boundary test.
# PERIMETER_BURST_NIGHT_WINDOW = (23, 5). 22:30 must be OUTSIDE.
# ============================================================================


def test_A4_burst_night_window_pinned_at_23_05():
    """PERIMETER_BURST_NIGHT_WINDOW must be (23, 5). Any drift here
    silently widens the XCORR-1 burst-demote scope."""
    assert _const.PERIMETER_BURST_NIGHT_WINDOW == (23, 5)


def test_A4_burst_gate_outside_at_2230():
    """22:30 must be OUTSIDE the burst-demote window. Recomputes the
    inline wrap logic used at perimeter_alert.py :_evaluate_burst_demotion.

    MUTATION ANCHOR: change PERIMETER_BURST_NIGHT_WINDOW to (22, 6) →
    this test flips green→red (22:30 becomes in-window)."""
    start, end = _const.PERIMETER_BURST_NIGHT_WINDOW
    h = 22
    if start == end:
        in_hours = True
    elif start < end:
        in_hours = start <= h < end
    else:
        in_hours = h >= start or h < end
    assert in_hours is False
