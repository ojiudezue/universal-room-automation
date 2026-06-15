"""D1 — AlertClassifier tests (outage-relevance gate → certainty → severity).

Headline correctness: a Flood Watch (Severity=Severe, Certainty=Possible)
FAILS the outage-relevance gate because "Flood" is absent from the
power-threat list → NOTICE → the battery does not hold. This is the
"beats Enphase" proof.

All alert fixtures derive from a single canonical fixture (the operator's live
NWS sensor shape) — no hand-authored dicts scattered inline (Bug Class C5).
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
import sys
import os
import types
import importlib

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code (same pattern as test_energy_battery)
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_NOW = datetime(2026, 6, 11, 12, 0, 0)


def _now():
    return _NOW


_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": MagicMock, "callback": lambda fn: fn},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _now,
        "now": _now,
        "as_local": lambda dt: dt,
        "UTC": None,
    },
}
for name, attrs in _mods.items():
    sys.modules.setdefault(name, _mock_module(name, **attrs))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
sys.modules["custom_components.universal_room_automation"] = _ura
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc
for _submod_name in ("energy_const", "inclement"):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_submod_name}.py")
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

from custom_components.universal_room_automation.domain_coordinators.inclement import (
    AlertClassifier,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    DEFAULT_INCLEMENT_POWER_THREAT_EVENTS,
)


# ---------------------------------------------------------------------------
# Single canonical fixture — the operator's live NWS sensor shape.
# Every test derives its alert list from this builder.
# ---------------------------------------------------------------------------

def make_alert(
    event="Flood Watch",
    severity="Severe",
    certainty="Possible",
    status="Actual",
    onset="2026-06-11T08:00:00-05:00",
    ends="2026-06-12T19:00:00-05:00",
    expires=None,
):
    alert = {
        "Event": event,
        "Severity": severity,
        "Certainty": certainty,
        "Status": status,
        "Onset": onset,
        "Ends": ends,
    }
    if expires is not None:
        alert["Expires"] = expires
    return alert


def classify(alerts, threat=None, warn_min="Severe"):
    c = AlertClassifier(power_threat_events=threat, warn_min_severity=warn_min)
    return c.classify(alerts, now=_NOW)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_flood_watch_severe_possible_returns_NOTICE_because_flood_fails_gate():
    # THE headline correctness test: live operator alert as fixture.
    r = classify([make_alert(event="Flood Watch", severity="Severe", certainty="Possible")])
    assert r.tier == "none"  # failed gate → no contributing event → none
    assert "Flood Watch" in r.gated_out_events


def test_severe_thunderstorm_warning_observed_returns_warn_tier():
    r = classify([make_alert(event="Severe Thunderstorm Warning",
                             severity="Severe", certainty="Observed")])
    assert r.tier == "warn"
    assert "Severe Thunderstorm Warning" in r.contributing_events


def test_severe_thunderstorm_watch_possible_corroboration_required_returns_watch_tier():
    r = classify([make_alert(event="Severe Thunderstorm Watch",
                             severity="Severe", certainty="Possible")])
    assert r.tier == "watch"


def test_tornado_warning_observed_returns_warn_tier():
    r = classify([make_alert(event="Tornado Warning", severity="Extreme",
                             certainty="Observed")])
    assert r.tier == "warn"


def test_red_flag_warning_returns_NOTICE_by_default_because_fire_absent_from_list():
    r = classify([make_alert(event="Red Flag Warning", severity="Severe",
                             certainty="Observed")])
    assert r.tier == "none"
    assert "Red Flag Warning" in r.gated_out_events


def test_red_flag_warning_returns_warn_tier_when_operator_adds_red_flag_to_power_threat_list():
    threat = list(DEFAULT_INCLEMENT_POWER_THREAT_EVENTS) + ["Red Flag"]
    r = classify([make_alert(event="Red Flag Warning", severity="Severe",
                             certainty="Observed")], threat=threat)
    assert r.tier == "warn"


def test_severity_below_min_demotes_one_tier():
    # Moderate Severe-Thunderstorm-Warning: warn (warning product) → demote → watch.
    r = classify([make_alert(event="Severe Thunderstorm Warning",
                             severity="Moderate", certainty="Observed")])
    assert r.tier == "watch"


def test_severity_never_overrides_gate():
    # Extreme Flood Watch still NOTICE — gate is on Event, not Severity.
    r = classify([make_alert(event="Flood Watch", severity="Extreme",
                             certainty="Observed")])
    assert r.tier == "none"
    assert "Flood Watch" in r.gated_out_events


def test_expired_alert_excluded():
    expired = make_alert(event="Tornado Warning", severity="Extreme",
                         certainty="Observed",
                         ends="2026-06-10T00:00:00-05:00")  # before _NOW
    r = classify([expired])
    assert r.tier == "none"


def test_exercise_status_excluded():
    r = classify([make_alert(event="Tornado Warning", severity="Extreme",
                             certainty="Observed", status="Exercise")])
    assert r.tier == "none"


@pytest.mark.parametrize("bad", [None, [], [{}], "not a list", 42])
def test_malformed_alerts_attr_returns_none_tier_no_exception(bad):
    r = classify(bad)
    assert r.tier == "none"
    assert r.raw_alert_count == (len(bad) if isinstance(bad, list) else 0)


def test_keyword_match_case_insensitive():
    r = classify([make_alert(event="tornado warning", severity="Extreme",
                             certainty="Observed")])
    assert r.tier == "warn"


def test_warning_product_type_folds_into_higher_certainty():
    # A "Warning" product with a conservative Certainty=Possible still promotes
    # to warn (product-type folding).
    r = classify([make_alert(event="Severe Thunderstorm Warning",
                             severity="Severe", certainty="Possible")])
    assert r.tier == "warn"


def test_expires_at_is_min_across_contributors():
    a1 = make_alert(event="Tornado Warning", severity="Extreme",
                    certainty="Observed", ends="2026-06-11T20:00:00-05:00")
    a2 = make_alert(event="High Wind Warning", severity="Severe",
                    certainty="Observed", ends="2026-06-11T15:00:00-05:00")
    r = classify([a1, a2])
    assert r.expires_at is not None
    assert r.expires_at.hour == 15  # the earlier of the two


def test_max_tier_aggregates_across_contributors():
    warn = make_alert(event="Tornado Warning", severity="Extreme",
                      certainty="Observed")
    watch = make_alert(event="Severe Thunderstorm Watch", severity="Severe",
                       certainty="Possible")
    r = classify([watch, warn])
    assert r.tier == "warn"
