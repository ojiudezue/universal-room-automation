"""EC inclement leftovers D4 (parent Stage D) — "above the bottom rate" sites
rank the PASSED period through ONE helper (PLANNING_ec_inclement_leftovers_2026_11.md
Rev 2 §D4).

INV-P1: for ANY (season, period) on the live PEC tariff, and for any
non-rankable engine (None, MagicMock, unknown season/period),
`above_bottom_rate` equals `period in ("peak", "mid_peak")`. Each H site
decides only through the helper on the PASSED period (never the clock
period); future-period sites rank in the season AT the transition.

Oracles:
- the full-year sweep compares against the legacy literal (the byte-identity
  oracle, independent of the rank code);
- the synthetic tariffs are hand-built here with rates chosen so the answer
  is known by inspection (bottom = lowest rate).

Routing tests drive the REAL enclosing method of each site with a REAL
TOURateEngine whose "peak" (or the passed period) is the season's BOTTOM
rate: under the migration the site acts "bottom"; reverted to the literal it
would act "above bottom". Each is the Review-C mutation anchor for its site.
"""
from __future__ import annotations

import ast
import asyncio
import collections
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from _reserve_governor_harness import (  # noqa: F401 — `clock` is a fixture
    _st,
    clock,
    make_shell,
)
from conftest import MockHass

from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
    above_bottom_rate,
    season_at,
)

_CHI = ZoneInfo("America/Chicago")
_FIXTURE = Path(__file__).parent / "fixtures" / "tou_rates_live_pec_2026.json"
_DOMAIN = "universal_room_automation"
_ALL = list(range(1, 13))


def _literal(period):
    return period in ("peak", "mid_peak")


def _live_engine() -> TOURateEngine:
    data = json.loads(_FIXTURE.read_text())
    eng = TOURateEngine._from_parsed_data(data, str(_FIXTURE), _FIXTURE.name)
    assert eng.file_status == "ok", eng.rejection_errors
    return eng


def _p(hours, rate):
    return {"hours": hours, "import_rate": rate, "export_rate": 0.04}


# "peak" is the season's BOTTOM rate (0.03); mid_peak / off_peak above it.
_PEAK_IS_BOTTOM = {"shoulder": {"months": _ALL, "periods": {
    "peak": _p([(0, 12)], 0.03),
    "mid_peak": _p([(12, 18)], 0.06),
    "off_peak": _p([(18, 24)], 0.10),
}}}

# Rank, not name: super_off_peak is the bottom, off_peak is mid-rank.
_SUPER_OFF = {"shoulder": {"months": _ALL, "periods": {
    "super_off_peak": _p([(0, 6)], 0.02),
    "off_peak": _p([(6, 17), (21, 24)], 0.04),
    "mid_peak": _p([(17, 21)], 0.09),
}}}

# Season boundary at midnight 06-30 → 07-01 (A = Jan-Jun, B = Jul-Dec).
# Plan form: in A off_peak is the bottom; in B off_peak ranks above a
# super_off_peak bottom. At 21:00 on 06-30 (A, current mid_peak) the next
# period is B's 00:00 off_peak.
_SEASON_FLIP_OFF = {
    "a": {"months": [1, 2, 3, 4, 5, 6], "periods": {
        "off_peak": _p([(0, 17)], 0.04),
        "mid_peak": _p([(17, 24)], 0.09),
    }},
    "b": {"months": [7, 8, 9, 10, 11, 12], "periods": {
        "off_peak": _p([(0, 2), (6, 17)], 0.04),
        "super_off_peak": _p([(2, 6)], 0.02),
        "mid_peak": _p([(17, 24)], 0.09),
    }},
}
# Same boundary, period NAMED mid_peak: the bottom in A, above bottom in B.
# At 21:00 on 06-30 (A, current off_peak) the next period is B's 00:00
# mid_peak. Discriminates get_season(now + hours_until) from
# get_season(now) at sites whose first branch is `next_period == "off_peak"`.
_SEASON_FLIP_MID = {
    "a": {"months": [1, 2, 3, 4, 5, 6], "periods": {
        "mid_peak": _p([(0, 12)], 0.03),
        "off_peak": _p([(12, 24)], 0.05),
    }},
    "b": {"months": [7, 8, 9, 10, 11, 12], "periods": {
        "mid_peak": _p([(0, 6)], 0.09),
        "off_peak": _p([(6, 24)], 0.04),
    }},
}
_BOUNDARY_2100 = datetime(2026, 6, 30, 21, 0, tzinfo=_CHI)


def _eng(table):
    return TOURateEngine(rate_table=table)


# ===========================================================================
# The helper
# ===========================================================================
def _hours_2026():
    t = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)   # 00:00 CST
    end = datetime(2027, 1, 1, 6, 0, tzinfo=timezone.utc)
    while t < end:
        yield t.astimezone(_CHI)
        t += timedelta(hours=1)


def test_above_bottom_rate_full_year_sweep_matches_literal():
    tou = _live_engine()
    seen = collections.Counter()
    n = 0
    for t in _hours_2026():
        season, period = tou.get_season(t), tou.get_current_period(t)
        got = above_bottom_rate(tou, season, period)
        assert got is _literal(period), (t, season, period)
        seen[(season, period, got)] += 1
        n += 1
    # Every hour of the year incl. both DST days (8759 local hours: one
    # skipped 02:00 in March, one repeated 01:00 in November → 8760 UTC).
    assert n == 8760
    # Non-vacuous: every season hit both answers, summer hit its peak.
    for s in ("summer", "shoulder", "winter"):
        assert seen[(s, "off_peak", False)] > 0
        assert seen[(s, "mid_peak", True)] > 0
    assert seen[("summer", "peak", True)] > 0


def test_above_bottom_rate_future_season_sweep():
    tou = _live_engine()
    n_true = 0
    for t in _hours_2026():
        tr = tou.get_next_transition(t)
        when = t + timedelta(hours=tr["hours_until"])
        got = above_bottom_rate(tou, season_at(tou, when), tr["next_period"])
        assert got is _literal(tr["next_period"]), (t, tr)
        n_true += got
    assert n_true > 0


def test_above_bottom_rate_ranks_not_names_synthetic_tariff():
    tou = _eng(_SUPER_OFF)
    assert above_bottom_rate(tou, "shoulder", "off_peak") is True
    assert _literal("off_peak") is False       # the literal says the opposite
    assert above_bottom_rate(tou, "shoulder", "super_off_peak") is False
    assert above_bottom_rate(tou, "shoulder", "mid_peak") is True
    tou2 = _eng(_PEAK_IS_BOTTOM)
    assert above_bottom_rate(tou2, "shoulder", "peak") is False
    assert above_bottom_rate(tou2, "shoulder", "off_peak") is True


def test_above_bottom_rate_season_boundary_uses_transition_season():
    """Plan discriminator: the right season is the one AT the transition."""
    tou = _eng(_SEASON_FLIP_OFF)
    now = _BOUNDARY_2100
    tr = tou.get_next_transition(now)
    assert tr["next_period"] == "off_peak" and tr["hours_until"] == 3
    right = above_bottom_rate(
        tou, season_at(tou, now + timedelta(hours=tr["hours_until"])),
        tr["next_period"])
    wrong = above_bottom_rate(tou, season_at(tou, now), tr["next_period"])
    assert (right, wrong) == (True, False)


class _Raising:
    def period_rank(self, *a):
        raise RuntimeError("boom")

    def get_season(self, *a):
        raise RuntimeError("boom")


class _BoolRank:
    def period_rank(self, *a):
        return True


@pytest.mark.parametrize("period", ["peak", "mid_peak", "off_peak", None])
def test_above_bottom_rate_fallbacks(period):
    live = _live_engine()
    cases = [
        (None, "summer"),                 # no engine
        (MagicMock(), "summer"),          # non-int rank
        (MagicMock(), MagicMock()),       # MagicMock season too
        (live, None),                     # no season
        (live, "monsoon"),                # unknown season
        (_Raising(), "summer"),           # engine raises
        (_BoolRank(), "summer"),          # bool is not a rank
    ]
    for tou, season in cases:
        assert above_bottom_rate(tou, season, period) is _literal(period), (
            tou, season)
    # Unknown period on a real engine → literal.
    assert above_bottom_rate(live, "summer", "shoulder_peak") is False


def test_season_at_failures_are_none():
    assert season_at(None, _BOUNDARY_2100) is None
    assert season_at(_live_engine(), None) is None
    assert season_at(_Raising(), _BOUNDARY_2100) is None
    assert season_at(_eng(_SEASON_FLIP_OFF), _BOUNDARY_2100) == "a"


# ===========================================================================
# Per-site routing (Review-C mutation anchors)
# ===========================================================================
def _ec():
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )

    class _EC(EnergyCoordinator):
        load_shedding_active = False

    return _EC.__new__(_EC)


def test_update_energy_situation_routes_through_above_bottom_rate():
    c = _ec()
    c._tou = _eng(_PEAK_IS_BOTTOM)
    c._update_energy_situation("peak")
    assert c._energy_situation == "normal"
    c._update_energy_situation("off_peak")        # ranked above bottom
    assert c._energy_situation == "optimizing"
    c._tou = None                                 # literal fallback
    c._update_energy_situation("peak")
    assert c._energy_situation == "optimizing"


def test_update_load_shedding_routes_through_above_bottom_rate():
    """"peak" ranked as the bottom → the off-peak exit (readings cleared,
    level 0, return) instead of the shed evaluation."""
    c = _ec()
    c._tou = _eng(_PEAK_IS_BOTTOM)
    c._load_shedding_enabled = True
    c._load_shedding_active_level = 0
    c._sustained_import_readings = collections.deque([5.0, 6.0])
    c._update_load_shedding("peak")
    assert len(c._sustained_import_readings) == 0
    assert c._load_shedding_active_level == 0


def _arb_ec(tou, db):
    from custom_components.universal_room_automation.domain_coordinators.energy_billing import (
        ArbitrageInventory,
        PeakAvoidanceTracker,
    )
    c = _ec()
    c.hass = SimpleNamespace(data={_DOMAIN: {"database": db}})
    c._tou = tou
    c._battery = SimpleNamespace(battery_soc=100.0, _get_entity=lambda k: None,
                                 solar_production_w=None, battery_power_w=None)
    c._cached_battery_capacity_kwh = 40.0
    c._arb_inventory = ArbitrageInventory()
    c._arb_inventory_loaded = True
    c._arb_inventory_changed_ticks = 0
    c._peak_avoidance = PeakAvoidanceTracker(MagicMock())
    c._savings_baselines_loaded = True
    c._billing = SimpleNamespace(_get_net_power=lambda: None)
    return c


class _ArbDB:
    def __init__(self):
        self.rows = []

    async def save_arbitrage_cycle(self, **kw):
        self.rows.append(kw)

    async def save_energy_state(self, key, value):
        pass


def _arb_tick(served):
    return {"elapsed_h": 5 / 60, "charge_kwh_grid": 0.0,
            "charge_kwh_solar": 0.0, "charge_kwh_unsplit": 0.0,
            "discharge_kwh": served, "battery_served_kwh": served}


@pytest.mark.parametrize("table,period,books", [
    (_PEAK_IS_BOTTOM, "peak", False),   # passed period is the bottom
    (_PEAK_IS_BOTTOM, "mid_peak", True),
])
def test_apply_arbitrage_tick_routes_through_above_bottom_rate(
    table, period, books,
):
    db = _ArbDB()
    c = _arb_ec(_eng(table), db)
    now = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
    asyncio.new_event_loop().run_until_complete(
        c._apply_arbitrage_tick(_arb_tick(0.5), period, "shoulder", now))
    assert (len(db.rows) == 1) is books


def _ev_shell(clock, tou, on=True):
    c, s = make_shell(clock)
    _st(c.hass, "switch.ab_garage_a", "on" if on else "off", lu=clock.t)
    _st(c.hass, "sensor.ab_garage_a_power", "7000" if on else "0", unit="W",
        lu=clock.t)
    c._tou = tou
    c._ev.attach_coord(c)      # production wiring (energy.py attach_coord)
    return c


def test_evse_tou_pause_routes_through_above_bottom_rate(clock):
    c = _ev_shell(clock, _eng(_PEAK_IS_BOTTOM))
    acts = c._ev.determine_actions("peak")
    assert not [a for a in acts if a["service"] == "switch.turn_off"]
    assert "garage_a" not in c._ev._paused_by_us
    # Positive control: "mid_peak" ranks above the bottom → TOU pause.
    acts = c._ev.determine_actions("mid_peak")
    assert [a["target"] for a in acts if a["service"] == "switch.turn_off"] == [
        "switch.ab_garage_a"]


_PLUG = "switch.leftovers_plug"


def _plug():
    from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
        SmartPlugController,
    )
    hass = MockHass()
    hass.set_state(_PLUG, "on")
    return SmartPlugController(hass=hass, plug_entities=[_PLUG])


def test_plug_tou_pause_routes_through_above_bottom_rate():
    p = _plug()
    acts = p.determine_actions("peak", tou_engine=_eng(_PEAK_IS_BOTTOM))
    assert not [a for a in acts if a["service"] == "switch.turn_off"]
    assert _PLUG not in p._paused_by_us
    # Positive control: no engine → literal → pause.
    p2 = _plug()
    acts = p2.determine_actions("peak")
    assert [a["target"] for a in acts if a["service"] == "switch.turn_off"] == [
        _PLUG]


class _Transition(TOURateEngine):
    """Real ranking; the transition / current period are pinned so the site
    reads a known period (the engine still ranks it)."""

    def __init__(self, table, next_period, hours_until, current):
        super().__init__(rate_table=table)
        self._np, self._hu, self._cur = next_period, hours_until, current

    def get_next_transition(self, now=None):
        return {"next_period": self._np, "hours_until": self._hu,
                "transition_hour": 0}

    def get_current_period(self, now=None):
        return self._cur


def _intent_attrs(tou, monkeypatch=None, now=None):
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_predict as hp,
    )
    if now is not None:
        monkeypatch.setattr(hp.dt_util, "now", lambda *a, **k: now)
    energy = MagicMock()
    energy.tou_engine = tou
    energy._cached_forecast_high = None
    energy.battery_status = {}
    mgr = SimpleNamespace(coordinators={"energy": energy})
    fake = SimpleNamespace(hass=SimpleNamespace(
        data={_DOMAIN: {"coordinator_manager": mgr}}))
    return hp.HVACPredictor.get_intent_attrs(fake)


def test_intent_anchor_next_period_routes_through_above_bottom_rate():
    a = _intent_attrs(_Transition(_PEAK_IS_BOTTOM, "peak", 2, "off_peak"))
    assert a["anchor_period"] is None          # next "peak" is the bottom
    a = _intent_attrs(_Transition(_PEAK_IS_BOTTOM, "mid_peak", 2, "peak"))
    assert a["anchor_period"] == "mid_peak"
    assert a["anchor_starts_in_minutes"] == 120


def test_intent_anchor_current_period_routes_through_above_bottom_rate():
    a = _intent_attrs(_Transition(_PEAK_IS_BOTTOM, "off_peak", 2, "peak"))
    # next "off_peak" ranks ABOVE the bottom here → anchored as next period.
    assert a["anchor_period"] == "off_peak"
    # Current-period branch: next off_peak is the bottom, current "peak" is
    # also the bottom → no anchor (literal would anchor "peak").
    tbl = {"shoulder": {"months": _ALL, "periods": {
        "peak": _p([(0, 12)], 0.03), "off_peak": _p([(12, 24)], 0.03),
        "mid_peak": _p([], 0.09)}}}
    a = _intent_attrs(_Transition(tbl, "off_peak", 2, "peak"))
    assert a["anchor_period"] is None
    # Positive control: current mid_peak above the bottom → anchored now.
    a = _intent_attrs(_Transition(tbl, "off_peak", 2, "mid_peak"))
    assert (a["anchor_period"], a["anchor_starts_in_minutes"]) == ("mid_peak", 0)


def test_intent_anchor_ranks_not_names_synthetic_tariff():
    """Plan §D4 acceptance: next off_peak (mid-rank) → anchored; next
    super_off_peak (bottom) → None (the `off_peak` elif is out of scope)."""
    a = _intent_attrs(_Transition(_SUPER_OFF, "off_peak", 3, "super_off_peak"))
    assert a["anchor_period"] == "off_peak"
    a = _intent_attrs(_Transition(_SUPER_OFF, "super_off_peak", 3, "mid_peak"))
    assert a["anchor_period"] is None


def test_intent_anchor_season_boundary_uses_transition_season(monkeypatch):
    """hvac_predict next-period site ranks in the season AT the transition:
    06-30 21:00 (season A, mid_peak = bottom) → next = B's 00:00 mid_peak
    (above bottom in B). get_season(now) would read A → no anchor."""
    tou = _eng(_SEASON_FLIP_MID)
    assert tou.get_next_transition(_BOUNDARY_2100)["next_period"] == "mid_peak"
    pinned = _Transition(_SEASON_FLIP_MID, **{
        "next_period": "mid_peak", "hours_until": 3, "current": "off_peak"})
    a = _intent_attrs(pinned, monkeypatch, now=_BOUNDARY_2100)
    assert a["anchor_period"] == "mid_peak"


def _situation(tou, monkeypatch=None, now=None):
    from custom_components.universal_room_automation import sensor as S
    if now is not None:
        monkeypatch.setattr(S.dt_util, "now", lambda *a, **k: now)
    energy = MagicMock()
    energy._tou = tou
    energy.last_battery_decision = {}
    attrs = S.EnergyBatteryStrategySensor._build_situation_attrs(
        None, energy, {})
    return attrs["next_decision_boundary"]


def test_situation_next_boundary_routes_through_above_bottom_rate():
    nb = _situation(_Transition(_PEAK_IS_BOTTOM, "peak", 2, "off_peak"))
    assert nb["expected_action"] == "re-evaluate"
    nb = _situation(_Transition(_PEAK_IS_BOTTOM, "mid_peak", 2, "peak"))
    assert nb["expected_action"] == "EV TOU pause will engage; battery holds"


def test_situation_next_boundary_season_boundary(monkeypatch):
    pinned = _Transition(_SEASON_FLIP_MID, "mid_peak", 3, "off_peak")
    nb = _situation(pinned, monkeypatch, now=_BOUNDARY_2100)
    assert nb["expected_action"] == "EV TOU pause will engage; battery holds"


# ===========================================================================
# The pin (§D4.1 rule): every non-docstring "peak"/"mid_peak" constant.
# ===========================================================================
_PKG = (Path(__file__).resolve().parents[2]
        / "custom_components" / "universal_room_automation")
_LITS = {"peak", "mid_peak"}


def _period_literal_sites(trees):
    """`trees`: iterable of (relative path, ast.Module). Returns
    {"path::func::literal": count}. Docstrings (the first-statement string
    of a Module / ClassDef / FunctionDef / AsyncFunctionDef) are excluded;
    comments are not AST nodes."""
    out: dict[str, int] = {}
    for rel, tree in trees:
        parents: dict = {}
        docs: set[int] = set()
        for n in ast.walk(tree):
            for ch in ast.iter_child_nodes(n):
                parents[ch] = n
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)):
                b = n.body
                if (b and isinstance(b[0], ast.Expr)
                        and isinstance(b[0].value, ast.Constant)):
                    docs.add(id(b[0].value))
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and n.value in _LITS and id(n) not in docs):
                continue
            o, fn = n, "<module>"
            while o in parents:
                o = parents[o]
                if isinstance(o, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = o.name
                    break
            k = f"{rel}::{fn}::{n.value}"
            out[k] = out.get(k, 0) + 1
    return out


def test_period_literal_sites_pinned():
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        TOU_PERIOD_NAME_LITERAL_SITES,
    )
    trees = [
        (p.relative_to(_PKG).as_posix(), ast.parse(p.read_text()))
        for p in sorted(_PKG.rglob("*.py"))
    ]
    got = _period_literal_sites(trees)
    pin = dict(TOU_PERIOD_NAME_LITERAL_SITES)
    added = {k: v for k, v in got.items() if pin.get(k) != v}
    stale = {k: v for k, v in pin.items() if got.get(k) != v}
    assert not added and not stale, (
        f"period-name literal drift — new/changed: {added}; pinned but "
        f"gone/changed: {stale}. Route an 'above the bottom rate' use "
        f"through energy_tou.above_bottom_rate, or edit "
        f"TOU_PERIOD_NAME_LITERAL_SITES in a reviewed change.")
    # Independent hand count (plan §D4.2 regenerated after migration).
    assert sum(pin.values()) == 50 and len(pin) == 29


def test_period_literal_pin_ignores_docstrings():
    src = (
        '"""module doc mentions "peak"."""\n'
        'X = "peak"\n'
        'class C:\n'
        '    "peak"\n'
        '    def f(self, p):\n'
        '        "mid_peak"\n'
        '        return p == "mid_peak" or p in ("peak", "off_peak")\n'
        'async def g():\n'
        '    """peak"""\n'
        '    y = "peak"  # "mid_peak" in a comment\n'
        '    return y\n'
    )
    got = _period_literal_sites([("m.py", ast.parse(src))])
    assert got == {
        "m.py::<module>::peak": 1,
        "m.py::f::mid_peak": 1,
        "m.py::f::peak": 1,
        "m.py::g::peak": 1,
    }
