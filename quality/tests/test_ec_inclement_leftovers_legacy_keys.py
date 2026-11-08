"""EC inclement leftovers D2 — INV-L1: the retired v5.5.0 inclement keys are
decision-neutral (PLANNING_ec_inclement_leftovers_2026_11.md Rev 2 §D2).

For any CM options dict, including one that still carries
`inclement_power_threat_events` and/or `inclement_warn_min_severity` with any
value, every `InclementDecision` and every `determine_mode` result is
identical to the same run without the keys.

Discriminator: a leftover reader of the list makes the customized-list case
(`+ ["Flood"]`, which would make a Flood Watch hold) diverge; a leftover
severity reader makes `warn_min_severity="Extreme"` demote the Severe
warning. Under a clean removal all variants equal the baseline.

Harness: REAL BatteryStrategy + REAL InclementFusion via a real NWS alert
entity (`_reserve_governor_harness`), frozen clock.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _CDT,
    clock,
    make_shell,
)

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

_UTC = timezone.utc
OCT_18 = datetime(2026, 10, 15, 23, 0, tzinfo=_UTC)  # 18:00 CDT, shoulder top rate
OCT_03 = datetime(2026, 10, 15, 8, 0, tzinfo=_UTC)   # 03:00 CDT, off_peak
_NWS = "sensor.leftovers_nws_alerts"

_V550_DEFAULT = [
    "Tornado", "Severe Thunderstorm", "Ice Storm", "Winter Storm",
    "High Wind", "Extreme Wind", "Hurricane", "Blizzard",
]

LEGACY_VARIANTS = {
    "default_list": {"inclement_power_threat_events": list(_V550_DEFAULT)},
    "custom_list_flood": {
        "inclement_power_threat_events": list(_V550_DEFAULT) + ["Flood"]},
    "string_form": {"inclement_power_threat_events": "Flood\nRed Flag\n"},
    "warn_min_extreme": {
        "inclement_power_threat_events": list(_V550_DEFAULT),
        "inclement_warn_min_severity": "Extreme"},
}

ALERT_SETS = {
    "flood_watch": [{"Event": "Flood Watch", "Severity": "Severe",
                     "Certainty": "Possible"}],
    "winter_storm_warning_severe": [{"Event": "Winter Storm Warning",
                                     "Severity": "Severe",
                                     "Certainty": "Likely"}],
    "svr_warning_moderate": [{"Event": "Severe Thunderstorm Warning",
                              "Severity": "Moderate",
                              "Certainty": "Observed"}],
}


def _run(clock, t, period, alerts, extra_opts):
    clock.t = t
    c, s = make_shell(clock, soc="45", reserve_state="20")
    s.reserve_soc = 20
    s._tou = TOURateEngine()
    full = [dict(a, Status="Actual", Onset="2026-10-14T00:00:00-05:00",
                 Ends="2026-10-20T00:00:00-05:00") for a in alerts]
    c.hass.set_state(_NWS, "1", attributes={"Alerts": full})
    opts = {CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS}
    opts.update(copy.deepcopy(extra_opts))
    s._inclement_config_override = opts
    d = s.determine_mode(period, "shoulder", now=t.astimezone(_CDT))
    inc = s._last_inclement_decision
    return d, inc


@pytest.mark.parametrize("variant", sorted(LEGACY_VARIANTS))
@pytest.mark.parametrize("alerts", sorted(ALERT_SETS))
@pytest.mark.parametrize("when", ["top", "bottom"])
def test_legacy_inclement_keys_decision_neutral(clock, variant, alerts, when):
    t, period = (OCT_18, "mid_peak") if when == "top" else (OCT_03, "off_peak")
    base_d, base_inc = _run(clock, t, period, ALERT_SETS[alerts], {})
    d, inc = _run(clock, t, period, ALERT_SETS[alerts],
                  LEGACY_VARIANTS[variant])
    assert base_inc is not None and inc is not None
    assert inc == base_inc
    assert d == base_d


@pytest.mark.parametrize("alerts,holds", [
    ("flood_watch", False),
    ("winter_storm_warning_severe", True),
])
def test_neutrality_fixture_hold_depth(clock, alerts, holds):
    """Self-test: the alert sets reach different decisions, so the equality
    above is not vacuous (a Flood Watch must NOT hold — the case a leftover
    `+["Flood"]` list reader would flip; a Severe Winter Storm Warning MUST
    hold — the case a leftover "Extreme" severity reader would demote)."""
    _, inc = _run(clock, OCT_18, "mid_peak", ALERT_SETS[alerts], {})
    assert (inc.hold_depth != "allow_discharge") is holds, inc
