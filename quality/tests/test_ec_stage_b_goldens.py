"""EC storm Stage B goldens — captured on the D-B1..D-B5 HEAD (137c885ba),
BEFORE any D-B2a / D-B6 / D-B7 / Stage C code (plan review 4 M4).

Two checks, one fixture:
  * `test_precharge_option_off_byte_identical` — with
    `inclement_grid_precharge_on_hold` False (the live value) the D-B2a
    eligibility gates, the polygon top-up leg, the forecast-confirmed buy and
    the D-B6 pre-onset leg change NOTHING: InclementDecision + determine_mode
    output equal this golden for eligible and ineligible products.
  * `test_preonset_noop_byte_identical` — with no prepare alert (none issued,
    or Onset beyond the lead) the tick is byte-identical to Stage B without
    D-B6 (INV-6(iv)).
Hour sweep: one day in each of Jan/Apr/Jul/Oct 2026, every local hour; TOU
period/season from the committed tariff (TOURateEngine).

Regenerate ONLY on a commit with no D-B2a/D-B6 code:
    EC_STAGE_B_WRITE_GOLDEN=1 PYTHONPATH=quality .venv-ha/bin/python \
        -m pytest quality/tests/test_ec_stage_b_goldens.py -q
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _SOC,
    _st,
    clock,
    make_shell,
)
from conftest import MockState

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD,
    CONF_INCLEMENT_NWS_ALERTS_ENTITY,
    CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)

GOLDEN = Path(__file__).parent / "fixtures" / "ec_stage_b_golden.json"
WRITE = os.environ.get("EC_STAGE_B_WRITE_GOLDEN") == "1"
_CHI = ZoneInfo("America/Chicago")
_UTC = timezone.utc
_NWS = "sensor.stage_b_golden_nws"
_TS = "sensor.stage_b_golden_ts"

_DAYS = ((1, 15), (4, 15), (7, 15), (10, 15))
# (label, event, code, onset offset h, ends offset h)
_SCEN = (
    ("none", None, None, 0, 0),
    ("wsw", "Winter Storm Warning", None, -0.5, 3),
    ("svw", "Severe Thunderstorm Warning", "SVW", -0.25, 0.75),
    ("sva", "Severe Thunderstorm Watch", None, -0.5, 3),
    ("wsa", "Winter Storm Watch", None, -0.5, 3),
    ("hurw", "Hurricane Warning", None, -0.5, 3),
    ("wiy", "Wind Advisory", "WIY", -0.5, 3),
    ("wsw_far", "Winter Storm Warning", None, 20, 30),  # beyond the 12 h lead
)
_SOCS = ("50", "95")

CASES = [
    f"{m:02d}-{d:02d}|{h:02d}|{sc[0]}|soc{soc}"
    for (m, d) in _DAYS for h in range(24) for sc in _SCEN for soc in _SOCS
]


def _alerts(now, scen):
    _label, event, code, on_h, end_h = scen
    if event is None:
        return []
    a = {
        "Event": event, "Type": "Alert", "Status": "Actual",
        "Severity": "Severe", "Certainty": "Likely", "ID": f"g-{_label}",
        "Sent": (now - timedelta(hours=1)).isoformat(),
        "Onset": (now + timedelta(hours=on_h)).isoformat(),
        "Ends": (now + timedelta(hours=end_h)).isoformat(),
    }
    if code:
        a["NWSCode"] = code
    return [a]


def _run(case, clock):
    md, hh, label, soc_s = case.split("|")
    m, d = (int(x) for x in md.split("-"))
    now = datetime(2026, m, d, int(hh), 0, tzinfo=_CHI)
    scen = next(s for s in _SCEN if s[0] == label)
    clock.t = now.astimezone(_UTC)
    c, s = make_shell(clock, soc=soc_s[3:])
    _st(c.hass, _SOC, soc_s[3:], unit="%", lu=clock.t)
    tou = TOURateEngine()
    s._tou = tou
    s._inclement_config_override = {
        CONF_INCLEMENT_NWS_ALERTS_ENTITY: _NWS,
        CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD: False,
        # Corroborated watches without a weather manager.
        CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION: False,
    }
    s._nws_last_updated_entity = lambda eid: _TS
    alerts = _alerts(now, scen)
    c.hass._states[_NWS] = MockState(_NWS, str(len(alerts)), {"Alerts": alerts})
    ts = MockState(_TS, now.isoformat(), {})
    ts.last_changed = ts.last_updated = clock.t
    c.hass._states[_TS] = ts
    period = tou.get_current_period(now)
    season = tou.get_season(now)
    out = s.determine_mode(period, season, now=now)
    dec = s._last_inclement_decision
    return {
        "period": period,
        "decision": {
            "hold_depth": dec.hold_depth,
            "grid_precharge": dec.grid_precharge,
            "tier": dec.tier,
            "reserve_floor": dec.reserve_floor,
            "reason": dec.reason,
            "expires_at": dec.expires_at_iso(),
        },
        "mode": out.get("mode"),
        "reason": out.get("reason"),
        "actions": out.get("actions"),
        "charge_from_grid": out.get("charge_from_grid"),
        "desired": s._last_reserve_level_desired,
        "dp_stamp": s._offpeak_drain_branch_target,
        "tick_floor": s._tick_reserve_floor,
    }


def _check(case, clock):
    observed = json.loads(json.dumps(_run(case, clock), default=str))
    if WRITE:
        data = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
        data[case] = observed
        GOLDEN.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
        return
    assert observed == json.loads(GOLDEN.read_text())[case]


@pytest.mark.parametrize("case", [c for c in CASES if "|none|" not in c
                                  and "|wsw_far|" not in c])
def test_precharge_option_off_byte_identical(case, clock):
    _check(case, clock)


@pytest.mark.parametrize("case", [c for c in CASES if "|none|" in c
                                  or "|wsw_far|" in c])
def test_preonset_noop_byte_identical(case, clock):
    _check(case, clock)
