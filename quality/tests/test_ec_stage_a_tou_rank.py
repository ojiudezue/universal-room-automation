"""EC storm/blind Stage A D-A1 — TOU rate-rank primitive (INV-4).

PLANNING_ec_storm_and_blind_decisions.md §3 INV-4: `is_top_rate(now)` is
True iff the active period's import rate equals the season's maximum
distinct import rate AND the season has >= 2 distinct rates. Oracles below
are hand-authored from the PEC tariff schedule (not derived from the engine):
  summer (Jun-Sep):        top 16-19, bottom 0-13 + 21-23
  shoulder (Mar-May, Oct-Nov): top 17-20, bottom 0-16 + 21-23
  winter (Dec-Feb):        top 05-08 + 17-20, bottom 0-4 + 9-16 + 21-23
Clock: tz-aware America/Chicago wall time for every hour of 2026, including
both DST transition days and each season-boundary day. No real time is read.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators.energy_tou import (  # noqa: E402
    TOURateEngine,
)

_CHI = ZoneInfo("America/Chicago")

_SUMMER = {6, 7, 8, 9}
_SHOULDER = {3, 4, 5, 10, 11}
_WINTER = {12, 1, 2}

_TOP = {
    "summer": set(range(16, 20)),
    "shoulder": set(range(17, 21)),
    "winter": set(range(5, 9)) | set(range(17, 21)),
}
_BOTTOM = {
    "summer": set(range(0, 14)) | set(range(21, 24)),
    "shoulder": set(range(0, 17)) | set(range(21, 24)),
    "winter": set(range(0, 5)) | set(range(9, 17)) | set(range(21, 24)),
}


def _season(month: int) -> str:
    if month in _SUMMER:
        return "summer"
    if month in _SHOULDER:
        return "shoulder"
    return "winter"


def _every_local_hour_2026():
    """Every distinct local wall hour of 2026 (walks UTC, so the DST
    spring-forward gap and fall-back repeat are both exercised)."""
    t = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, 6, 0, tzinfo=timezone.utc)
    while t < end:
        yield t.astimezone(_CHI)
        t += timedelta(hours=1)


def test_tou_rate_rank_hour_sweep_pec_dst():
    eng = TOURateEngine()  # committed PEC tariff (energy_const.PEC_TOU_RATES)
    seen_days = set()
    n = 0
    for local in _every_local_hour_2026():
        s = _season(local.month)
        assert eng.is_top_rate(local) is (local.hour in _TOP[s]), local
        assert eng.is_bottom_rate(local) is (local.hour in _BOTTOM[s]), local
        assert eng.is_bottom_rate(local) is (
            eng.get_current_period(local) == "off_peak"
        ), local
        seen_days.add(local.date())
        n += 1
    # The sweep actually covered the DST days and every season boundary.
    from datetime import date
    for d in (
        date(2026, 3, 8), date(2026, 11, 1),            # DST transitions
        date(2026, 2, 28), date(2026, 3, 1),            # winter -> shoulder
        date(2026, 5, 31), date(2026, 6, 1),            # shoulder -> summer
        date(2026, 9, 30), date(2026, 10, 1),           # summer -> shoulder
        date(2026, 11, 30), date(2026, 12, 1),          # shoulder -> winter
    ):
        assert d in seen_days
    assert n == 8760


def test_tou_rate_rank_october_1800_is_top_1600_is_not():
    """Live (a) discriminator: a name-keyed check reads False all shoulder day."""
    eng = TOURateEngine()
    assert eng.is_top_rate(datetime(2026, 10, 15, 18, 0, tzinfo=_CHI)) is True
    assert eng.is_top_rate(datetime(2026, 10, 15, 16, 0, tzinfo=_CHI)) is False
    assert eng.rate_rank(datetime(2026, 10, 15, 18, 0, tzinfo=_CHI)) == 1
    assert eng.rate_rank(datetime(2026, 10, 15, 3, 0, tzinfo=_CHI)) == 0


def _table(rates: dict[str, tuple[list, float]], months) -> dict:
    return {
        "only": {
            "months": list(months),
            "periods": {
                p: {"hours": h, "import_rate": r, "export_rate": r}
                for p, (h, r) in rates.items()
            },
        }
    }


def test_tou_rate_rank_ties_and_single_rate():
    # mid == peak: both rank 1, both top; off rank 0.
    tie = TOURateEngine(rate_table=_table({
        "off_peak": ([(0, 14), (21, 24)], 0.04),
        "mid_peak": ([(14, 16), (20, 21)], 0.10),
        "peak": ([(16, 20)], 0.10),
    }, range(1, 13)))
    assert tie.period_rank("only", "mid_peak") == 1
    assert tie.period_rank("only", "peak") == 1
    assert tie.period_rank("only", "off_peak") == 0
    assert tie.is_top_rate(datetime(2026, 7, 1, 15, 0, tzinfo=_CHI)) is True
    assert tie.is_top_rate(datetime(2026, 7, 1, 17, 0, tzinfo=_CHI)) is True
    assert tie.is_top_rate(datetime(2026, 7, 1, 3, 0, tzinfo=_CHI)) is False
    # Three distinct rates: mid is NOT top.
    three = TOURateEngine(rate_table=_table({
        "off_peak": ([(0, 14), (21, 24)], 0.04),
        "mid_peak": ([(14, 16), (20, 21)], 0.09),
        "peak": ([(16, 20)], 0.16),
    }, range(1, 13)))
    assert three.period_rank("only", "mid_peak") == 1
    assert three.is_top_rate(datetime(2026, 7, 1, 15, 0, tzinfo=_CHI)) is False
    assert three.is_top_rate(datetime(2026, 7, 1, 17, 0, tzinfo=_CHI)) is True
    # Single-rate season: every hour bottom, no hour top.
    flat = TOURateEngine(rate_table=_table({
        "off_peak": ([(0, 12)], 0.07),
        "mid_peak": ([(12, 24)], 0.07),
    }, range(1, 13)))
    for h in range(24):
        t = datetime(2026, 7, 1, h, 0, tzinfo=_CHI)
        assert flat.is_top_rate(t) is False
        assert flat.is_bottom_rate(t) is True
    assert flat.is_top_period("only", "mid_peak") is False
    assert flat.is_top_period("only", None) is False


@pytest.mark.parametrize("hour,expected", [(18, True), (16, False)])
def test_tou_top_rate_strategy_attr(hour, expected, monkeypatch):
    """D-A1 display attr `tou_top_rate` via get_status (frozen dt_util.now)."""
    import sys
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    eng = TOURateEngine()
    s = BatteryStrategy.__new__(BatteryStrategy)
    s._tou = eng
    t = datetime(2026, 10, 15, hour, 0, tzinfo=_CHI)
    for name in ("homeassistant.util.dt",):
        m = sys.modules.get(name)
        if m is not None:
            monkeypatch.setattr(m, "now", lambda *a, **k: t, raising=False)
    pkg = sys.modules.get("homeassistant.util")
    if pkg is not None and getattr(pkg, "dt", None) is not None:
        monkeypatch.setattr(pkg.dt, "now", lambda *a, **k: t, raising=False)
    assert s._tou_top_rate_attr() is expected
    s._tou = None
    assert s._tou_top_rate_attr() is None
