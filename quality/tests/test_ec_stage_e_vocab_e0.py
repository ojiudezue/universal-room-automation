"""EC storm Stage E E0 — NWS vocabulary re-sync (PLANNING_ec_storm_stage_e.md
§0.1, §E0, OQ-1 approved 2026-10-17).

Freeze Warning notice -> watch (eligible, freeze family, air temp); Freeze
Watch added (name-only watch); Cold Weather Advisory stays notice but joins
the apparent-temperature set. Decision tests drive the REAL
`BatteryStrategy.determine_mode` (December, America/Chicago).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from _ec_stage_e_harness import (  # noqa: F401 — fixtures
    L,
    alert,
    bshell,
    cfg_on,
    chi_clock,
    clock,
    inc_mod,
    outlook,
    tick,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    FORECAST_APPARENT_TEMP_PRODUCTS,
    INCLEMENT_FORECAST_FAMILY,
    INCLEMENT_PRODUCT_TABLE,
    NWS_WEATHER_EVENT_NAMES,
)

# Independent oracle: the retired NWS names (verified absent from
# api.weather.gov/alerts/types, 2026-10-17), typed by hand.
RETIRED = {
    "Hard Freeze Warning", "Hard Freeze Watch",
    "Wind Chill Warning", "Wind Chill Watch", "Wind Chill Advisory",
}


def test_vocab_snapshot_covers_table():
    table = {row[1] for row in INCLEMENT_PRODUCT_TABLE}
    vocab = set(NWS_WEATHER_EVENT_NAMES)
    # Every non-retired table row is a live NWS weather product...
    assert table - vocab == RETIRED
    # ...and the retired list is pinned (none of them came back).
    assert not (RETIRED & vocab)
    # Vocabulary hygiene: no duplicates, includes the E0 rows, excludes the
    # marine / statement / civil classes named in the plan (§E1.2).
    assert len(NWS_WEATHER_EVENT_NAMES) == len(vocab)
    assert {"Freeze Warning", "Freeze Watch", "Cold Weather Advisory",
            "Snow Squall Warning", "Flood Watch"} <= vocab
    assert not ({"Gale Warning", "Storm Warning", "Storm Surge Warning",
                 "Typhoon Warning", "Special Weather Statement",
                 "Hazardous Weather Outlook", "Test",
                 "Administrative Message", "911 Telephone Outage"} & vocab)


def _row(name):
    return next(r for r in INCLEMENT_PRODUCT_TABLE if r[1] == name)


def test_freeze_watch_name_only_row():
    assert _row("Freeze Watch") == (None, "Freeze Watch", "watch", False, True)
    assert _row("Freeze Warning") == ("FZW", "Freeze Warning", "watch", False, True)
    assert INCLEMENT_FORECAST_FAMILY["Freeze Watch"] == "freeze"
    inc = inc_mod()
    now = L(2026, 12, 16, 3)
    a = alert("Freeze Watch", onset=now - timedelta(hours=1),
              ends=now + timedelta(hours=8), id_="fza")
    c = inc.AlertClassifier().classify([a], now=now)
    # Was gated out (no row) on v5.103.69; now a watch hold contributor.
    assert c.tier == "watch" and "Freeze Watch" not in c.gated_out_events
    assert c.drift == ()
    # Name-only row: an alert carrying a code records it as drift.
    a2 = dict(a, NWSCode="FZA", ID="fza2")
    c2 = inc.AlertClassifier().classify([a2], now=now)
    assert c2.drift == (("Freeze Watch", "FZA", "observed_code"),)


def test_cold_weather_advisory_apparent_temp():
    assert _row("Cold Weather Advisory")[2] == "notice"
    assert _row("Cold Weather Advisory")[4] is False
    assert "Cold Weather Advisory" in FORECAST_APPARENT_TEMP_PRODUCTS
    inc = inc_mod()
    # 30 F air, 20 F apparent: apparent confirms (<= 28), air would not.
    o = outlook(min_temp=30.0, apparent=20.0)
    assert inc.forecast_confirms("Cold Weather Advisory", o) is True
    assert inc.forecast_confirms("Freeze Warning", o) is False  # air temp
    now = L(2026, 12, 16, 3)
    a = alert("Cold Weather Advisory", onset=now - timedelta(hours=1),
              ends=now + timedelta(hours=8))
    assert inc.AlertClassifier().classify([a], now=now).tier == "notice"


def _fzw(now):
    return alert("Freeze Warning", code="FZW", onset=now - timedelta(hours=1),
                 ends=now + timedelta(hours=14), id_="fzw")


@pytest.mark.parametrize(
    "hour,temp,soc,tomorrow,depth,buy,floor",
    [
        # bottom rate (03:00 Dec): watch, uncorroborated -> partial, no buy.
        (3, 34.0, "50", "excellent", "partial_hold", False, 50),
        # <= 28 F corroborates: full hold, eligible buy fires (SOC 50 < 90).
        (3, 25.0, "50", "excellent", "full_hold", True, None),
        # top rate (18:00 Dec): uncorroborated watch releases the battery.
        (18, 34.0, "50", "excellent", "allow_discharge", False, None),
        # top rate, corroborated: recoverability decides.
        (18, 25.0, "95", "excellent", "partial_hold", False, 50),
        (18, 25.0, "30", "poor", "full_hold", False, None),
    ],
    ids=["bottom_34F", "bottom_25F", "top_34F", "top_25F_recoverable",
         "top_25F_not_recoverable"],
)
def test_freeze_warning_watch_class_forecast_lift(
    chi_clock, hour, temp, soc, tomorrow, depth, buy, floor,
):
    now = L(2026, 12, 16, hour)
    c, s, _wm = bshell(chi_clock, now, soc=soc, alerts=[_fzw(now)],
                       ol=outlook(min_temp=temp, pop=0.0), option=True)
    s.classify_tomorrow_solar = lambda: tomorrow
    s._daylight_bounds = lambda d: (
        d.replace(hour=7, minute=20, second=0, microsecond=0),
        d.replace(hour=17, minute=30, second=0, microsecond=0),
    )
    d = tick(chi_clock, c, s, now)
    dec = s._last_inclement_decision
    assert dec.tier == "watch" and dec.reason != "classify_error"
    assert dec.hold_depth == depth
    assert cfg_on(d) is buy
    if floor is not None:
        assert dec.reserve_floor == floor
