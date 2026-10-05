"""EC degraded-data policy, Phase 1 (Tier 3).

Plan: docs/planning/PLANNING_ec_degraded_data_phase1.md (incl. plan reviews
#1 C1-1..C1-7 and #2 R2-1..R2-14 binding directives, §12 operator rulings).

Falsifiable invariants under test (plan §3):
  I-1  untrusted SOC tier → the arbitrage release path emits ZERO EVSE
       turn_on and no EVSE leaves `_paused_by_arbitrage` (only exception:
       the max-defer discharge with CFG PROVABLY off).
  I-2  write-leg CFG unknown/unavailable/missing AND (LKG latch OR the
       command ledger says ON) → grid_charge_intent True; explicit off is
       believed (and discounts an older ledger entry).
  I-3  no decision dict with charge_from_grid=True while the tick tier is
       `cloud_fallback` (storm precharge exempt — operator Q2).
  I-4  the stream tier serves only when every guard holds (fail-closed).
  I-5  kill switch off / entity unset → resolver byte-identical.
  I-6  one page per boundary when untrusted >= dwell inside the lead.
  D2c  must-start-by never overrides a breaker / protective hold; a held
       start → log + NM + anomaly row.

Drives the REAL BatteryStrategy resolver/determine_mode/_result, the REAL
EVChargerController.determine_arbitrage_actions and the REAL coordinator
methods (bound onto minimal shells). Replay rows come from the committed
recorder extract `fixtures/ec_degraded_data_p1_outages.json`; the real
resolver picks every tier (R2-13 — no tier injection on replay paths).
Expected values are hand-derived literals (Bug Class #62).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from conftest import MockHass, MockState  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_battery as eb_mod,
    energy_const as ec_mod,
    energy_pool as ep_mod,
)
from custom_components.universal_room_automation.domain_coordinators.energy import (  # noqa: E402
    EnergyCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    ARBITRAGE_PHASE_ATTAIN,
    ARBITRAGE_PHASE_CHARGE,
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (  # noqa: E402
    DEFAULT_CHARGE_FROM_GRID_ENTITY,
    DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
    DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
    DEFAULT_GRID_ENABLED_ENTITY,
    DEFAULT_RESERVE_SOC_ENTITY,
    DEFAULT_SOLCAST_REMAINING_ENTITY,
    DEFAULT_SOLCAST_TODAY_ENTITY,
    DEFAULT_SOLCAST_TOMORROW_ENTITY,
    DEFAULT_STORAGE_MODE_ENTITY,
    DEFAULT_WEATHER_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (  # noqa: E402
    TOURateEngine,
)

_NATIVE = "sensor.envoy_482543015950_battery"
_STREAM = "sensor.envoy_stream_battery_soc"
_COW = "sensor.envoy_stream_grid_power"
_CLOUD = DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY
_CFG_W = DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY  # write leg (cloud)
_CFG_L = DEFAULT_CHARGE_FROM_GRID_ENTITY               # local read leg
_SM = DEFAULT_STORAGE_MODE_ENTITY
_CDT = timezone(timedelta(hours=-5))
_UTC = timezone.utc
_FIX = Path(__file__).parent / "fixtures" / "ec_degraded_data_p1_outages.json"


def _const_modules():
    """Every module object production code may resolve `energy_const` to
    (sibling test files sometimes re-exec the package modules)."""
    pkg_name = "custom_components.universal_room_automation.domain_coordinators"
    mods = [ec_mod]
    m = sys.modules.get(pkg_name + ".energy_const")
    if m is not None and m not in mods:
        mods.append(m)
    pkg = sys.modules.get(pkg_name)
    a = getattr(pkg, "energy_const", None) if pkg is not None else None
    if a is not None and a not in mods:
        mods.append(a)
    for gm in (BatteryStrategy.battery_soc.fget.__globals__,
               EVChargerController.determine_arbitrage_actions.__globals__):
        n = gm.get("__name__", "")
        pm = sys.modules.get(n.rsplit(".", 1)[0] + ".energy_const")
        if pm is not None and pm not in mods:
            mods.append(pm)
    return mods


def _setc(monkeypatch, name, value):
    for m in _const_modules():
        monkeypatch.setattr(m, name, value, raising=False)


# ---------------------------------------------------------------------------
# Clock + harness
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def set(self, t: datetime) -> None:
        self.t = t

    def adv(self, **kw) -> None:
        self.t = self.t + timedelta(**kw)


def _dt_modules():
    mods = []
    m = sys.modules.get("homeassistant.util.dt")
    if m is not None:
        mods.append(m)
    pkg = sys.modules.get("homeassistant.util")
    alt = getattr(pkg, "dt", None) if pkg is not None else None
    if alt is not None and alt not in mods:
        mods.append(alt)
    return mods


@pytest.fixture
def clock(monkeypatch):
    """Scoped dt_util patch (restored by monkeypatch): aware UTC utcnow,
    CDT-local now/as_local. Order-robust against naive sibling stubs."""
    c = _Clock(datetime(2026, 10, 3, 21, 0, tzinfo=_UTC))
    for m in _dt_modules():
        monkeypatch.setattr(m, "utcnow", lambda: c.t, raising=False)
        monkeypatch.setattr(m, "now", lambda: c.t.astimezone(_CDT), raising=False)
        monkeypatch.setattr(m, "as_local", lambda d: d.astimezone(_CDT), raising=False)
        monkeypatch.setattr(
            m, "parse_datetime",
            lambda s: datetime.fromisoformat(s) if s else None,
            raising=False,
        )
    return c


def _st(hass, eid, state, *, unit=None, lu=None, lr=None, attrs=None):
    a = dict(attrs or {})
    if unit is not None:
        a["unit_of_measurement"] = unit
    s = MockState(eid, state, a)
    if lu is not None:
        s.last_updated = lu
        s.last_changed = lu
    if lr is not None:
        s.last_reported = lr
    elif lu is not None:
        s.last_reported = lu
    hass._states[eid] = s
    return s


class _Coord:
    """Minimal coordinator backref for BatteryStrategy (`_coord`)."""

    def __init__(self) -> None:
        self.nm: list[dict] = []
        self.saves = 0
        self._ev = None

    def _send_nm_alert(self, **kw):
        self.nm.append(kw)
        return None

    def _save_evse_state(self):
        self.saves += 1
        return None


def _strategy(clock, *, stream=True, cowitness=True, arbitrage=False, extra=None):
    hass = MockHass()
    hass.async_create_task = lambda c: None
    t = clock.t
    _st(hass, _NATIVE, "80", unit="%", lu=t)
    _st(hass, _SM, "self_consumption", lu=t)
    _st(hass, DEFAULT_GRID_ENABLED_ENTITY, "on", lu=t)
    _st(hass, _CFG_L, "off", lu=t)
    _st(hass, _CFG_W, "off", lu=t)
    _st(hass, DEFAULT_RESERVE_SOC_ENTITY, "20", lu=t)
    _st(hass, DEFAULT_SOLCAST_TODAY_ENTITY, "20", lu=t)
    _st(hass, DEFAULT_SOLCAST_TOMORROW_ENTITY, "20", lu=t)
    _st(hass, DEFAULT_SOLCAST_REMAINING_ENTITY, "5", lu=t)
    _st(hass, DEFAULT_WEATHER_ENTITY, "cloudy", lu=t)
    cfg = {
        "battery_soc": _NATIVE,
        "cloud_charge_from_grid_oracle": _CFG_W,
    }
    if stream:
        cfg["battery_soc_stream"] = _STREAM
    if cowitness:
        cfg["stream_cowitness"] = _COW
    cfg.update(extra or {})
    s = BatteryStrategy(
        hass,
        reserve_soc=10,
        arbitrage_enabled=arbitrage,
        peak_buffer_target=80,
        entity_config=cfg,
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
        tou_engine=TOURateEngine(),
        arbitrage_charge_lead_time_min=180,
    )
    coord = _Coord()
    s._coord = coord
    return s, hass, coord


@pytest.fixture
def stream_on(monkeypatch):
    _setc(monkeypatch, "SOC_STREAM_TIER_ENABLED", True)


def _native_stale(hass, clock):
    _st(hass, _NATIVE, "unavailable", unit="%", lu=clock.t)
    _st(hass, _SM, "unavailable", lu=clock.t)


def _stream(hass, clock, value="90", *, unit="%", lr_age=0, cow_age=5):
    t = clock.t
    _st(hass, _STREAM, value, unit=unit, lu=t - timedelta(seconds=lr_age),
        lr=t - timedelta(seconds=lr_age))
    _st(hass, _COW, "1234", unit="W", lu=t - timedelta(seconds=cow_age))


def _cloud(hass, clock, value="96.2", age=60):
    lu = clock.t - timedelta(seconds=age)
    _st(hass, _CLOUD, value, unit="%", lu=lu)


# ===========================================================================
# D1 — stream SOC tier
# ===========================================================================


class TestD1StreamTier:
    def test_stream_tier_serves_when_native_stale(self, clock, stream_on):
        s, hass, _ = _strategy(clock)
        _native_stale(hass, clock)
        _stream(hass, clock, "90")
        _cloud(hass, clock, "96.2")
        assert s.battery_soc == 90.0
        assert s._soc_source_last == "stream"
        assert s._soc_lkg == 90.0
        assert s._soc_lkg_at == clock.t

    def test_stream_tier_order_native_wins(self, clock, stream_on):
        s, hass, _ = _strategy(clock)
        _st(hass, _NATIVE, "88", unit="%", lu=clock.t)
        _stream(hass, clock, "90")
        assert s.battery_soc == 88.0
        assert s._soc_source_last == "envoy"

    @pytest.mark.parametrize("kill_switch_on,entity_set", [
        (False, True), (True, False), (False, False),
    ])
    def test_stream_tier_kill_switch_off_byte_identical(
        self, clock, monkeypatch, kill_switch_on, entity_set,
    ):
        """I-5: kill switch off (or entity unset) → LKG then cloud,
        exactly as develop, even with a perfectly fresh stream."""
        _setc(monkeypatch, "SOC_STREAM_TIER_ENABLED", kill_switch_on)
        s, hass, _ = _strategy(clock, stream=entity_set)
        _native_stale(hass, clock)
        _stream(hass, clock, "90")
        _cloud(hass, clock, "96.2")
        # No LKG → cloud fallback.
        assert s.battery_soc == 96.2
        assert s._soc_source_last == "cloud_fallback"
        # With a fresh LKG → LKG wins (develop order).
        s._soc_lkg, s._soc_lkg_at = 77.0, clock.t - timedelta(seconds=10)
        assert s.battery_soc == 77.0
        assert s._soc_source_last == "lkg"
        assert s.stream_trust_state() == "disabled"

    @pytest.mark.parametrize("case", [
        "unavailable", "unknown", "nonnumeric", "unit_W", "unit_missing",
        "range_101", "range_neg", "cow_stale_b", "cow_unconfigured_b",
        "cow_unavailable_b", "quarantined",
    ])
    def test_stream_tier_rejects(self, clock, stream_on, case):
        """I-4 fail-closed — every failed guard falls through to cloud."""
        s, hass, _ = _strategy(clock, cowitness=(case != "cow_unconfigured_b"))
        _native_stale(hass, clock)
        _cloud(hass, clock, "50")
        if case == "unavailable":
            _stream(hass, clock, "unavailable")
        elif case == "unknown":
            _stream(hass, clock, "unknown")
        elif case == "nonnumeric":
            _stream(hass, clock, "abc")
        elif case == "unit_W":
            _stream(hass, clock, "90", unit="W")
        elif case == "unit_missing":
            _stream(hass, clock, "90")
            hass._states[_STREAM].attributes = {}
        elif case == "range_101":
            _stream(hass, clock, "101")
        elif case == "range_neg":
            _stream(hass, clock, "-1")
        elif case == "cow_stale_b":
            _stream(hass, clock, "90", cow_age=121)
        elif case == "cow_unconfigured_b":
            _stream(hass, clock, "90")
        elif case == "cow_unavailable_b":
            _stream(hass, clock, "90")
            _st(hass, _COW, "unavailable", lu=clock.t)
        elif case == "quarantined":
            _stream(hass, clock, "90")
            s._soc_stream_trust = "quarantined"
        assert s.battery_soc == 50.0
        assert s._soc_source_last == "cloud_fallback"

    @pytest.mark.parametrize("kill", [True, False])
    @pytest.mark.parametrize("entity", [True, False])
    @pytest.mark.parametrize("native", ["fresh", "stale"])
    @pytest.mark.parametrize("stream", ["fresh", "stale", "quarantined"])
    def test_stream_config_extremes_matrix(self, clock, monkeypatch, kill, entity, native, stream):
        """§6 corners: the stream tier serves ONLY with kill on + entity
        set + native stale + stream fresh-and-trusted; native always wins
        when fresh; otherwise today's cloud fallback (no LKG seeded)."""
        _setc(monkeypatch, "SOC_STREAM_TIER_ENABLED", kill)
        s, hass, _ = _strategy(clock, stream=entity)
        if native == "fresh":
            _st(hass, _NATIVE, "61", unit="%", lu=clock.t)
        else:
            _native_stale(hass, clock)
        _stream(hass, clock, "62", cow_age=(500 if stream == "stale" else 5))
        if stream == "quarantined":
            s._soc_stream_trust = "quarantined"
        _cloud(hass, clock, "63")
        if native == "fresh":
            expect = (61.0, "envoy")
        elif kill and entity and stream == "fresh":
            expect = (62.0, "stream")
        else:
            expect = (63.0, "cloud_fallback")
        assert (s.battery_soc, s._soc_source_last) == expect

    def test_stream_cowitness_boundary_mode_b(self, clock, stream_on):
        """Co-witness max age 120 s (hard literal): 119 serves, 121 refuses."""
        s, hass, _ = _strategy(clock)
        _native_stale(hass, clock)
        _cloud(hass, clock, "50")
        _stream(hass, clock, "90", cow_age=119)
        assert s.battery_soc == 90.0
        s._soc_lkg = s._soc_lkg_at = None  # isolate the stream guard
        _stream(hass, clock, "90", cow_age=121)
        assert s.battery_soc == 50.0

    def test_stream_mode_a_last_reported_boundary(self, clock, stream_on, monkeypatch):
        """Mode (a) (max age 90): lr age 89 serves; 91 refuses; a stale
        CONFIGURED co-witness still refuses; no co-witness is allowed."""
        _setc(monkeypatch, "DEFAULT_SOC_STREAM_MAX_AGE_S", 90)
        s, hass, _ = _strategy(clock, cowitness=False)
        _native_stale(hass, clock)
        _cloud(hass, clock, "50")
        _stream(hass, clock, "90", lr_age=89)
        assert s.battery_soc == 90.0
        s._soc_lkg = s._soc_lkg_at = None  # isolate the stream guard
        _stream(hass, clock, "90", lr_age=91)
        assert s.battery_soc == 50.0
        s2, hass2, _ = _strategy(clock, cowitness=True)
        _native_stale(hass2, clock)
        _cloud(hass2, clock, "50")
        _stream(hass2, clock, "90", lr_age=10, cow_age=500)
        assert s2.battery_soc == 50.0

    def test_stream_quarantine_and_recovery(self, clock, stream_on):
        s, hass, coord = _strategy(clock)
        _st(hass, _NATIVE, "80", unit="%", lu=clock.t)
        _stream(hass, clock, "90")  # 10 pp > 3
        s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "trusted"
        # R2-5: a second compare in the SAME second does not count.
        s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "trusted"
        clock.adv(seconds=60)
        _st(hass, _NATIVE, "80", unit="%", lu=clock.t)
        _stream(hass, clock, "90")
        s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "quarantined"
        assert len([n for n in coord.nm if n["hazard_type"] == "soc_stream_divergence"]) == 1
        assert coord.saves == 1  # event-save on the transition (R2-3)
        # Quarantined stream no longer serves.
        _native_stale(hass, clock)
        _cloud(hass, clock, "50")
        assert s.battery_soc == 50.0
        # Abstain when native absent: state kept.
        clock.adv(seconds=60)
        _stream(hass, clock, "80")
        s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "quarantined"
        # Two spaced agreeing compares → trusted again.
        for _ in range(2):
            clock.adv(seconds=60)
            _st(hass, _NATIVE, "81", unit="%", lu=clock.t)
            _st(hass, _SM, "self_consumption", lu=clock.t)
            _stream(hass, clock, "80")
            s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "trusted"
        assert coord.saves == 2

    def test_stream_divergence_wired_into_get_status(self, clock, stream_on):
        """Wire-in anchor: get_status (the `_evaluate_soc_resolution`
        caller) runs the stream divergence detector."""
        s, hass, _ = _strategy(clock)
        for _ in range(2):
            _st(hass, _NATIVE, "80", unit="%", lu=clock.t)
            _st(hass, _SM, "self_consumption", lu=clock.t)
            _stream(hass, clock, "90")
            s.get_status()
            clock.adv(seconds=61)
        assert s._soc_stream_trust == "quarantined"

    def test_stream_trust_snapshot_round_trip(self, clock):
        s, _, _ = _strategy(clock)
        s._soc_stream_trust = "quarantined"
        s._soc_stream_trust_since = clock.t
        snap = json.loads(json.dumps(s.get_stream_trust_snapshot()))
        s2, _, _ = _strategy(clock)
        s2.restore_stream_trust_snapshot(snap)
        assert s2._soc_stream_trust == "quarantined"
        s3, _, _ = _strategy(clock)
        s3.restore_stream_trust_snapshot({})
        assert s3._soc_stream_trust == "trusted"
        s3.restore_stream_trust_snapshot({"state": "bogus"})
        assert s3._soc_stream_trust == "trusted"

    def test_stream_tick_degraded_refuses_fresh_charge(self, clock, stream_on):
        """Stream tick: envoy_available stays native-based → degraded flag
        `stream` → fresh grid-charge entry refused."""
        s, hass, _ = _strategy(clock)
        _native_stale(hass, clock)
        _stream(hass, clock, "40")
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert s._tick_soc_source == "stream"
        assert s._degraded_telemetry_source == "stream"
        assert s._degraded_entry_refused("attain entry") is True

    def test_tier_map_and_disagreement_include_stream(self, clock, stream_on):
        s, hass, _ = _strategy(clock)
        _native_stale(hass, clock)
        _stream(hass, clock, "90")
        _cloud(hass, clock, "96.2")
        st = s.get_status()
        assert st["soc_resolution"]["tier"] == "local_stream"
        # Discriminating config (Bug Class #63): quarantined-but-fresh
        # stream at 85, no LKG, cloud 96.2 → the gap is stream-vs-cloud
        # (11.2) and exists ONLY because stream joins the pairwise set.
        s._soc_stream_trust = "quarantined"
        s._soc_lkg = s._soc_lkg_at = None
        _stream(hass, clock, "85")
        st = s.get_status()
        assert st["soc_resolution"]["tier"] == "cloud_fallback"
        assert st["soc_resolution"]["tier_disagreement_pp"] == pytest.approx(11.2)


# ===========================================================================
# D1 persistence through the REAL coordinator save/restore
# ===========================================================================


class _KV:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    async def save_energy_state(self, key, value):
        self.rows[key] = value

    async def restore_energy_state_with_age(self, key, max_age_hours=None):
        return self.rows.get(key)

    def __getattr__(self, name):
        async def _noop(*a, **k):
            return {} if name.startswith("restore") else None
        return _noop


def _persist_shell(hass, battery):
    from custom_components.universal_room_automation.domain_coordinators import (
        energy as _em,
    )
    ev = EVChargerController(hass, evse_config={})
    holder = SimpleNamespace(hass=hass, _ev=ev, _battery=battery)
    for name in (
        "_save_evse_state", "_restore_evse_state",
        "_save_registry_owner_lists", "_restore_registry_owner_lists",
        "_restore_wv_state", "_reconcile_dp_excess_on_restore",
    ):
        setattr(holder, name, getattr(_em.EnergyCoordinator, name).__get__(holder, type(holder)))
    return holder


@pytest.mark.asyncio
async def test_stream_trust_and_page_latch_persist_across_restart(clock):
    s, hass, _ = _strategy(clock)
    kv = _KV()
    hass.data["universal_room_automation"] = {"database": kv}
    s._soc_stream_trust = "quarantined"
    s._soc_stream_trust_since = clock.t
    s._untrusted_page_boundary_iso = "2026-10-03T17:00:00-05:00"
    s._cfg_unknown_page_boundary_iso = "2026-10-03T17:00:00-05:00"
    await _persist_shell(hass, s)._save_evse_state()
    assert "battery_soc_stream_trust" in kv.rows
    assert "ec_untrusted_page_latch" in kv.rows
    s2, hass2, _ = _strategy(clock)
    hass2.data["universal_room_automation"] = {"database": kv}
    await _persist_shell(hass2, s2)._restore_evse_state()
    assert s2._soc_stream_trust == "quarantined"
    assert s2._untrusted_page_boundary_iso == "2026-10-03T17:00:00-05:00"
    assert s2._cfg_unknown_page_boundary_iso == "2026-10-03T17:00:00-05:00"
    # Missing key → default trusted (C1-6 documented).
    s3, hass3, _ = _strategy(clock)
    hass3.data["universal_room_automation"] = {"database": _KV()}
    await _persist_shell(hass3, s3)._restore_evse_state()
    assert s3._soc_stream_trust == "trusted"


# ===========================================================================
# D2a — arbitrage release refusal on an untrusted tier (pool level)
# ===========================================================================


def _evpool(on=False):
    hass = MockHass()
    hass.set_state("switch.garage_a", "on" if on else "off")
    hass.set_state("sensor.garage_a_power", "0", attributes={"unit_of_measurement": "W"})
    ev = EVChargerController(hass, evse_config={"garage_a": {
        "switch": "switch.garage_a", "power": "sensor.garage_a_power",
    }})
    return ev


def _held(ev, label):
    ev._paused_by_arbitrage.add("garage_a")
    ev._arbitrage_pause_reason["garage_a"] = label


def _turn_ons(actions):
    return [a for a in actions if a.get("service") == "switch.turn_on"]


class _Mono:
    def __init__(self) -> None:
        self.t = 1000.0


@pytest.fixture
def mono(monkeypatch):
    m = _Mono()
    g = EVChargerController.determine_arbitrage_actions.__globals__
    monkeypatch.setitem(g, "_arb_release_clock", lambda: m.t)
    return m


class TestD2aReleaseRefusal:
    @pytest.mark.parametrize("label", ["breaker", "redirect"])
    def test_arb_release_refused_on_untrusted(self, mono, label):
        ev = _evpool()
        _held(ev, label)
        acts = ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
            soc_untrusted=True, cfg_provably_off=True,
        )
        assert _turn_ons(acts) == []
        assert "garage_a" in ev._paused_by_arbitrage
        assert ev._arbitrage_pause_reason["garage_a"] == label
        # Trusted → released.
        acts = ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak", soc_untrusted=False,
        )
        assert len(_turn_ons(acts)) == 1
        assert "garage_a" not in ev._paused_by_arbitrage

    def test_discharge_after_max_defer_cfg_off(self, mono):
        ev = _evpool()
        _held(ev, "breaker")
        ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
            soc_untrusted=True, cfg_provably_off=True,
        )
        mono.t += 59 * 60
        assert _turn_ons(ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
            soc_untrusted=True, cfg_provably_off=True,
        )) == []
        mono.t += 2 * 60  # 61 min
        # CFG not provably off → still held.
        assert _turn_ons(ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
            soc_untrusted=True, cfg_provably_off=False,
        )) == []
        assert "garage_a" in ev._paused_by_arbitrage
        # grid_charge_on True → still held.
        assert _turn_ons(ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak", grid_charge_on=True,
            soc_untrusted=True, cfg_provably_off=True,
        )) == []
        # Provably off → released.
        acts = ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
            soc_untrusted=True, cfg_provably_off=True,
        )
        assert len(_turn_ons(acts)) == 1
        assert "garage_a" not in ev._paused_by_arbitrage
        assert ev._arb_release_refused_since == {}

    def test_refusal_clock_resets_on_trusted_tick(self, mono):
        """Continuous refusal only: a trusted call (even a pause tick)
        resets the clock, so 61 min of non-continuous untrusted ≠ release."""
        ev = _evpool()
        _held(ev, "breaker")
        ev.determine_arbitrage_actions(arbitrage_charging=False, tou_period="off_peak",
                                       soc_untrusted=True, cfg_provably_off=True)
        mono.t += 30 * 60
        ev.determine_arbitrage_actions(arbitrage_charging=True, tou_period="off_peak",
                                       pause_reason="breaker", soc_untrusted=False)
        mono.t += 31 * 60
        assert _turn_ons(ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
            soc_untrusted=True, cfg_provably_off=True,
        )) == []

    @pytest.mark.asyncio
    async def test_untrusted_breaker_tick_does_not_reset_refusal_clock(self, clock, mono):
        """The pre-decision breaker call carries the SAME tick verdict: an
        untrusted breaker tick mid-refusal keeps the clock running, so the
        continuous-untrusted discharge still lands at 61 min."""
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, "off", lu=clock.t)
        ev = _evpool()
        _held(ev, "breaker")
        shell = _DispatchShell(s, hass, ev)
        ev.determine_arbitrage_actions(arbitrage_charging=False, tou_period="off_peak",
                                       soc_untrusted=True, cfg_provably_off=True)
        mono.t += 30 * 60
        charge = {"actions": [], "arbitrage_phase": "charge", "charge_from_grid": True}
        await shell._execute_breaker_safe_dispatch(charge, "off_peak", soc_untrusted=True)
        mono.t += 31 * 60
        acts = ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
            soc_untrusted=True, cfg_provably_off=True,
        )
        assert len(_turn_ons(acts)) == 1

    @pytest.mark.parametrize("cap,expect_release_at_first", [
        (0, True), (-5, True), (1, False), (60, False), (1440, False),
    ])
    def test_max_defer_extremes(self, mono, monkeypatch, cap, expect_release_at_first):
        """<=0 is the kill switch (today's behaviour)."""
        _setc(monkeypatch, "DEFAULT_ARB_RELEASE_UNTRUSTED_MAX_DEFER_MIN", cap)
        ev = _evpool()
        _held(ev, "breaker")
        # CFG NOT provably off: only the kill switch can release here.
        acts = ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
            soc_untrusted=True, cfg_provably_off=False,
        )
        assert bool(_turn_ons(acts)) is expect_release_at_first
        if cap == 1:
            mono.t += 61
            assert len(_turn_ons(ev.determine_arbitrage_actions(
                arbitrage_charging=False, tou_period="off_peak",
                soc_untrusted=True, cfg_provably_off=True,
            ))) == 1

    def test_arb_release_alternating_ticks_no_turn_on(self, clock, mono):
        """I-1 repro: tiers alternate envoy/cloud_fallback/none/lkg x10 with
        the REAL resolver picking each tier; EVSE re-held every trusted
        release → turn_on ONLY on trusted ticks."""
        s, hass, _ = _strategy(clock, stream=False)
        ev = _evpool()
        seq = ["envoy", "cloud", "none", "lkg"] * 3
        for kind in seq[:10]:
            clock.adv(minutes=5)
            if kind == "envoy":
                _st(hass, _NATIVE, "50", unit="%", lu=clock.t)
                _st(hass, _SM, "self_consumption", lu=clock.t)
            elif kind == "lkg":
                _native_stale(hass, clock)
                s._soc_lkg, s._soc_lkg_at = 50.0, clock.t - timedelta(seconds=30)
            elif kind == "cloud":
                _native_stale(hass, clock)
                s._soc_lkg_at = clock.t - timedelta(hours=1)
                _cloud(hass, clock, "50")
            else:
                _native_stale(hass, clock)
                s._soc_lkg_at = clock.t - timedelta(hours=1)
                _st(hass, _CLOUD, "unavailable", lu=clock.t)
            s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
            untrusted = not eb_mod.soc_tier_trusted(s._tick_soc_source)
            _held(ev, "breaker" if kind in ("envoy", "cloud") else "redirect")
            acts = ev.determine_arbitrage_actions(
                arbitrage_charging=False, tou_period="off_peak",
                soc_untrusted=untrusted, cfg_provably_off=False,
            )
            expect_trusted = kind in ("envoy", "lkg")
            assert untrusted is (not expect_trusted), (kind, s._tick_soc_source)
            assert bool(_turn_ons(acts)) is expect_trusted, (kind, acts)


# ===========================================================================
# D2a — coordinator wire-in (enclosing-method anchors)
# ===========================================================================


class _DispatchShell:
    def __init__(self, battery, hass, ev, *, ev_tou_enabled=True):
        self._battery = battery
        self.hass = hass
        self._ev = ev
        self._ev_tou_enabled = ev_tou_enabled
        self._pool = SimpleNamespace(determine_actions=lambda p: [])
        self.dispatched: list[dict] = []
        self._last_known_grid_charge_on = False
        self._last_cfg_off_read_at = None
        self._cfg_unknown_forced_since = None

    async def _execute_service_action(self, spec):
        self.dispatched.append(dict(spec))

    async def _tap_write_verifier(self, spec, decision, **_k):
        return None


for _n in (
    "_dispatch_post_decision_tou_and_arbitrage", "_execute_breaker_safe_dispatch",
    "_soc_untrusted_from_battery", "_cfg_ledger_says_on",
    "_cfg_write_leg_provably_off", "_cfg_breaker_blocks_ev_start",
    "_note_cfg_unknown_forced", "_cfg_off_read_fresh",
    "_cloud_last_success_age_s",
):
    setattr(_DispatchShell, _n, getattr(EnergyCoordinator, _n))


@pytest.mark.asyncio
@pytest.mark.parametrize("ev_tou_enabled", [True, False])
async def test_dispatch_post_decision_refuses_release_on_untrusted(
    clock, mono, ev_tou_enabled,
):
    """Wire-in: `_dispatch_post_decision_tou_and_arbitrage` threads
    soc_untrusted into the release; works with EV TOU OFF too (R2-1)."""
    s, hass, _ = _strategy(clock, stream=False)
    _native_stale(hass, clock)
    _cloud(hass, clock, "50")
    s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
    assert s._tick_soc_source == "cloud_fallback"
    ev = _evpool()
    ev.hass = hass
    hass.set_state("switch.garage_a", "off")
    hass.set_state("sensor.garage_a_power", "0", attributes={"unit_of_measurement": "W"})
    _held(ev, "breaker")
    shell = _DispatchShell(s, hass, ev, ev_tou_enabled=ev_tou_enabled)
    await shell._dispatch_post_decision_tou_and_arbitrage(
        period="off_peak", pause_reason=None, pause_requested=False,
        grid_charge_intent=False,
        soc_untrusted=shell._soc_untrusted_from_battery(),
    )
    assert [d for d in shell.dispatched if d.get("target") == "switch.garage_a"
            and d.get("service") == "switch.turn_on"] == []
    assert "garage_a" in ev._paused_by_arbitrage


class _CycleShell(EnergyCoordinator):
    """EnergyCoordinator with __init__ bypassed — drives the REAL
    `_decision_cycle_body` (enclosing method of the D2a capture)."""

    def __init__(self):  # noqa: D401 - bypass heavy init
        pass


def _cycle_shell(clock, s, hass, ev):
    c = _CycleShell()
    c.hass = hass
    c._battery = s
    c._ev = ev
    c._pool = SimpleNamespace(determine_actions=lambda p: [], state="idle")
    c._tou = SimpleNamespace(
        get_current_period=lambda *a: "off_peak", get_season=lambda *a: "shoulder",
        check_period_transition=lambda: None,
    )
    c._maybe_reset_daily = lambda: None
    c._record_decision = lambda **k: None
    c._is_any_evse_charging = lambda: False
    c._dp_decision_tick = lambda *a, **k: None
    c._observation_mode = False
    c._ev_tou_enabled = False
    c._excess_solar_enabled = False
    c.safely_ordered_ladder = lambda: {}
    c._fill_priority_soc = 50
    c._excess_solar_soc = 90
    c._ev_battery_drain_soc = 30
    c._last_known_grid_charge_on = False
    c._last_cfg_off_read_at = None
    c._cfg_unknown_forced_since = None
    c._last_arbitrage_chunk_completed = False
    c.dispatched = []

    async def _acct(decision, period, season):
        return None
    c._account_arbitrage_cycle = _acct

    async def _noop():
        return None
    c._refresh_arbitrage_status_cache = _noop

    async def _exec(spec):
        c.dispatched.append(dict(spec))
    c._execute_service_action = _exec

    async def _tap(spec, decision, **_k):
        return None
    c._tap_write_verifier = _tap
    return c


@pytest.mark.asyncio
async def test_decision_cycle_threads_verdict_into_breaker_call(clock, mono):
    """Untrusted tick with CFG reading ON (breaker path): the pre-decision
    breaker call carries the captured verdict, so the D2a refusal clock is
    NOT reset by the breaker claim."""
    s, hass, _ = _strategy(clock, stream=False)
    _native_stale(hass, clock)
    _cloud(hass, clock, "50")
    _st(hass, _CFG_W, "on", lu=clock.t)
    ev = _evpool()
    ev.hass = hass
    hass.set_state("switch.garage_a", "off")
    hass.set_state("sensor.garage_a_power", "0", attributes={"unit_of_measurement": "W"})
    _held(ev, "breaker")
    ev._arb_release_refused_since["garage_a"] = mono.t - 1800
    c = _cycle_shell(clock, s, hass, ev)
    await c._decision_cycle_body()
    assert s._tick_soc_source == "cloud_fallback"
    assert ev._arb_release_refused_since.get("garage_a") == mono.t - 1800


@pytest.mark.asyncio
async def test_decision_cycle_captures_tier_before_first_await(clock, mono):
    """Capture-site anchor (R2-1): the verdict is taken right after
    determine_mode. `_account_arbitrage_cycle` (the first await) flips the
    tier to `envoy` (models `_evaluate_battery` re-running determine_mode);
    the release must still be refused."""
    s, hass, _ = _strategy(clock, stream=False)
    _native_stale(hass, clock)
    _cloud(hass, clock, "50")
    ev = _evpool()
    ev.hass = hass
    hass.set_state("switch.garage_a", "off")
    hass.set_state("sensor.garage_a_power", "0", attributes={"unit_of_measurement": "W"})
    _held(ev, "breaker")
    c = _CycleShell()
    c.hass = hass
    c._battery = s
    c._ev = ev
    c._pool = SimpleNamespace(determine_actions=lambda p: [], state="idle")
    c._tou = SimpleNamespace(
        get_current_period=lambda *a: "off_peak", get_season=lambda *a: "shoulder",
        check_period_transition=lambda: None,
    )
    c._maybe_reset_daily = lambda: None
    c._record_decision = lambda **k: None
    c._is_any_evse_charging = lambda: False
    c._dp_decision_tick = lambda *a, **k: None
    c._observation_mode = False
    c._ev_tou_enabled = False
    c._excess_solar_enabled = False
    c.safely_ordered_ladder = lambda: {}
    c._fill_priority_soc = 50
    c._excess_solar_soc = 90
    c._ev_battery_drain_soc = 30
    c._last_known_grid_charge_on = False
    c._last_cfg_off_read_at = None
    c._cfg_unknown_forced_since = None
    c._last_arbitrage_chunk_completed = False
    c.dispatched = []

    async def _acct(decision, period, season):
        s._tick_soc_source = "envoy"
    c._account_arbitrage_cycle = _acct

    async def _noop():
        return None
    c._refresh_arbitrage_status_cache = _noop

    async def _exec(spec):
        c.dispatched.append(dict(spec))
    c._execute_service_action = _exec

    async def _tap(spec, decision, **_k):
        return None
    c._tap_write_verifier = _tap
    await c._decision_cycle_body()
    assert s._tick_soc_source == "envoy"  # flipped mid-tick
    assert [d for d in c.dispatched if d.get("target") == "switch.garage_a"
            and d.get("service") == "switch.turn_on"] == []
    assert "garage_a" in ev._paused_by_arbitrage


# ===========================================================================
# D2b — CFG unknown != off (breaker chokepoint)
# ===========================================================================


def _dispatch_shell(clock, cfg_state, *, ledger=None, ledger_at=None, lkg=False):
    s, hass, _ = _strategy(clock, stream=False)
    if cfg_state is None:
        hass._states.pop(_CFG_W, None)
    else:
        _st(hass, _CFG_W, cfg_state, lu=clock.t)
    s._last_charge_from_grid_command = ledger
    s._last_charge_from_grid_command_at = ledger_at
    ev = _evpool()
    shell = _DispatchShell(s, hass, ev)
    shell._last_known_grid_charge_on = lkg
    return shell, s


_NEUTRAL = {"actions": [], "arbitrage_phase": "n/a", "charge_from_grid": False}


class TestD2bUnknownNotOff:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("cfg", ["unavailable", "unknown", None])
    @pytest.mark.parametrize("ledger,lkg,expect", [
        (True, False, True), (None, False, False), (False, False, False),
        (None, True, True), (True, True, True), (False, True, True),
    ])
    async def test_breaker_intent_unknown_matrix(self, clock, cfg, ledger, lkg, expect):
        shell, _ = _dispatch_shell(clock, cfg, ledger=ledger, ledger_at=clock.t, lkg=lkg)
        _, _, intent = await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert intent is expect

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ledger", [True, None, False])
    async def test_explicit_off_is_believed(self, clock, ledger):
        shell, _ = _dispatch_shell(clock, "off", ledger=ledger, ledger_at=clock.t, lkg=True)
        _, _, intent = await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert intent is False

    @pytest.mark.asyncio
    async def test_breaker_intent_stale_ledger_after_manual_off(self, clock):
        """C1-2: ledger True at T0, explicit `off` at T1, unavailable at T2
        → intent False. A NEWER ON command (T3) re-arms the ledger."""
        t0 = clock.t
        shell, s = _dispatch_shell(clock, "off", ledger=True, ledger_at=t0)
        clock.adv(minutes=5)
        await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        clock.adv(minutes=5)
        _st(shell.hass, _CFG_W, "unavailable", lu=clock.t)
        _, _, intent = await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert intent is False
        clock.adv(minutes=5)
        s._last_charge_from_grid_command_at = clock.t
        _, _, intent = await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert intent is True

    @pytest.mark.asyncio
    async def test_unknown_with_ledger_pauses_ev_as_breaker(self, clock):
        shell, _ = _dispatch_shell(clock, "unavailable", ledger=True, ledger_at=clock.t)
        shell.hass.set_state("switch.garage_a", "on")
        shell._ev.hass = shell.hass
        reason, _, intent = await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert reason == "breaker" and intent is True
        assert "garage_a" in shell._ev._paused_by_arbitrage

    @pytest.mark.asyncio
    async def test_r2_8_page_after_dwell_with_ev_held(self, clock):
        """R2-8 discharge: unknown-forced intent >= 10 min during off_peak
        with an EVSE held → exactly one high page; 9 min → none."""
        shell, s = _dispatch_shell(clock, "unavailable", ledger=True, ledger_at=clock.t)
        coord = s._coord
        _held(shell._ev, "breaker")
        clock.set(datetime(2026, 10, 4, 7, 0, tzinfo=_UTC))  # 02:00 CDT off_peak
        await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        clock.adv(minutes=9)
        await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert [n for n in coord.nm if n["hazard_type"] == "battery_cfg_unknown_ev_held"] == []
        clock.adv(minutes=2)
        await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        clock.adv(minutes=5)
        await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        pages = [n for n in coord.nm if n["hazard_type"] == "battery_cfg_unknown_ev_held"]
        assert len(pages) == 1 and pages[0]["severity"] == "high"


@pytest.mark.asyncio
async def test_r2_8_no_page_without_held_evse(clock):
    """R2-8 page needs an EVSE actually held (no EVSE configured → none)."""
    shell, s = _dispatch_shell(clock, "unavailable", ledger=True, ledger_at=clock.t)
    shell._ev = EVChargerController(
        shell.hass, evse_config={"unwired": {"switch": ""}},
    )
    clock.set(datetime(2026, 10, 4, 7, 0, tzinfo=_UTC))
    await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
    clock.adv(minutes=15)
    await shell._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
    assert shell._cfg_unknown_forced_since is not None
    assert [n for n in s._coord.nm if n["hazard_type"] == "battery_cfg_unknown_ev_held"] == []


class TestD2aProvablyOff:
    def _shell(self, clock, cfg_w, cfg_l, ledger):
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, cfg_w, lu=clock.t)
        _st(hass, _CFG_L, cfg_l, lu=clock.t)
        s._last_charge_from_grid_command = ledger
        return _DispatchShell(s, hass, _evpool())

    def test_local_on_cloud_off_ledger_false_released_at_61(self, clock, mono):
        """R2-9: local Enpower `on` (standing flag) is never consulted —
        write leg off + ledger False → provably off → release at 61 min."""
        shell = self._shell(clock, "off", "on", False)
        assert shell._cfg_write_leg_provably_off() is True
        ev = shell._ev
        _held(ev, "breaker")
        ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak", soc_untrusted=True,
            cfg_provably_off=shell._cfg_write_leg_provably_off(),
        )
        mono.t += 61 * 60
        acts = ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak", soc_untrusted=True,
            cfg_provably_off=shell._cfg_write_leg_provably_off(),
        )
        assert len(_turn_ons(acts)) == 1

    @pytest.mark.parametrize("cfg_w,ledger,expect", [
        ("off", False, True), ("off", None, True), ("off", True, False),
        ("on", False, False), ("unavailable", False, False),
        ("unknown", None, False),
    ])
    def test_provably_off_matrix(self, clock, cfg_w, ledger, expect):
        assert self._shell(clock, cfg_w, "off", ledger)._cfg_write_leg_provably_off() is expect

    def test_missing_state_not_provably_off_but_no_entity_is(self, clock):
        shell = self._shell(clock, "off", "off", None)
        shell.hass._states.pop(_CFG_W)
        assert shell._cfg_write_leg_provably_off() is False
        # C1-4: no write-leg entity resolvable at all → provably off.
        shell._battery._get_entity = lambda *a, **k: None
        assert shell._cfg_write_leg_provably_off() is True


# ===========================================================================
# D2c — must-start-by waits behind breaker + protective holds
# ===========================================================================


class _MSBShell:
    def __init__(self, clock, *, cfg_w="off", ledger=None):
        self.s, self.hass, _ = _strategy(clock, stream=False)
        _st(self.hass, _CFG_W, cfg_w, lu=clock.t)
        self.s._last_charge_from_grid_command = ledger
        self.s._last_charge_from_grid_command_at = clock.t
        self._battery = self.s
        self._ev = _evpool()
        self._ev.hass = self.hass
        self.hass.set_state("switch.garage_a", "off")
        self.hass.set_state("sensor.garage_a_power", "0", attributes={"unit_of_measurement": "W"})
        self._ev._paused_by_dp.add("garage_a")
        self._ev._claim_pause_dispatch_owner("garage_a", "dp")
        self._dp_decision_soc = 30
        self._dp_must_start_unsub = None
        self._last_known_grid_charge_on = False
        self._last_cfg_off_read_at = None
        self.svc: list = []
        self.nm: list = []
        self.anoms: list = []
        self.hass.services = SimpleNamespace(
            async_call=lambda d, sv, data, blocking=False: self.svc.append((d, sv, data["entity_id"])),
        )
        self.hass.async_create_task = lambda c: None
        db = SimpleNamespace(save_anomaly_event=lambda evt: self.anoms.append(evt))
        self.hass.data["universal_room_automation"] = {"database": db}

    def blind_window_liveness_release(self, evse_id, reason, has_pressure=False):
        return True

    def _send_nm_alert(self, **kw):
        self.nm.append(kw)


for _n in (
    "_apply_dp_must_start_release", "_cancel_dp_must_start_by_timer",
    "_cfg_breaker_blocks_ev_start", "_cfg_ledger_says_on",
    "_report_must_start_by_held", "_on_dp_must_start_by",
    "_cfg_off_read_fresh", "_cloud_last_success_age_s",
    "_ev_start_hold_label", "_soc_untrusted_from_battery",
    "_apply_dp_reversion",
):
    setattr(_MSBShell, _n, getattr(EnergyCoordinator, _n))


def _forced_on(sh):
    return ("switch", "turn_on", "switch.garage_a") in sh.svc


class TestD2cMustStartBy:
    def test_must_start_by_defers_to_breaker_pause(self, clock):
        sh = _MSBShell(clock)
        _held(sh._ev, "breaker")
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert not _forced_on(sh)
        assert "garage_a" in sh._ev._paused_by_dp  # sticky for retry
        assert len(sh.nm) == 1 and sh.nm[0]["hazard_type"] == "ev_must_start_by_held"
        assert len(sh.anoms) == 1 and sh.anoms[0].type == "ev_must_start_by_held"

    def test_must_start_by_defers_on_redirect_label(self, clock):
        """Operator ruling 2026-10-04: energy-savings holds also win."""
        sh = _MSBShell(clock)
        _held(sh._ev, "redirect")
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert not _forced_on(sh)
        assert len(sh.nm) == 1

    @pytest.mark.parametrize("cfg_w,ledger,lkg,expect_held", [
        ("on", None, False, True),
        ("unavailable", True, False, True),
        ("unavailable", None, True, True),
        ("unavailable", None, False, False),
        ("off", True, True, False),
    ])
    def test_must_start_by_defers_when_cfg_live_on(self, clock, cfg_w, ledger, lkg, expect_held):
        sh = _MSBShell(clock, cfg_w=cfg_w, ledger=ledger)
        sh._last_known_grid_charge_on = lkg
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert _forced_on(sh) is (not expect_held)
        assert (len(sh.nm) == 1) is expect_held

    @pytest.mark.parametrize("owner", [
        "_paused_by_battery_drain", "_paused_by_us", "_paused_by_grid_cap",
        "_paused_by_load_shed", "_paused_by_fill_priority",
    ])
    def test_must_start_by_defers_to_protective_owner(self, clock, owner):
        sh = _MSBShell(clock)
        getattr(sh._ev, owner).add("garage_a")
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert not _forced_on(sh)
        assert len(sh.nm) == 1 and len(sh.anoms) == 1

    def test_must_start_by_releases_when_no_hold(self, clock):
        sh = _MSBShell(clock)
        sh._apply_dp_must_start_release(tou_period="peak")
        assert _forced_on(sh)
        assert sh.nm == [] and sh.anoms == []
        assert "garage_a" not in sh._ev._paused_by_dp

    @pytest.mark.asyncio
    async def test_on_dp_must_start_by_wire_in(self, clock):
        """Enclosing-method anchor via the timer callback."""
        sh = _MSBShell(clock)
        _held(sh._ev, "breaker")
        sh._dp_carrier = None
        sh._tou = SimpleNamespace(get_current_period=lambda *a: "off_peak")
        sh._save_evse_state = lambda: None
        await sh._on_dp_must_start_by(clock.t)
        assert not _forced_on(sh)
        assert len(sh.anoms) == 1


# ===========================================================================
# D3 — cloud SOC never the sole basis for a grid charge
# ===========================================================================


def _cfg_actions(res, svc):
    return [a for a in res["actions"] if a.get("service") == svc and a.get("target") == _CFG_W]


class TestD3CloudWithhold:
    def _cloud_tick(self, clock, s, hass):
        _native_stale(hass, clock)
        s._soc_lkg_at = None
        s._soc_lkg = None
        _cloud(hass, clock, "40")
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert s._tick_soc_source == "cloud_fallback"

    def test_cloud_tier_withholds_result_charge(self, clock):
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, "on", lu=clock.t)
        self._cloud_tick(clock, s, hass)
        r = s._result("self_consumption", "Arbitrage CHARGE", "self_consumption",
                      charge_from_grid=True, reserve_level=80,
                      arbitrage_phase=ARBITRAGE_PHASE_CHARGE)
        assert r["charge_from_grid"] is False
        assert "(grid charge withheld: cloud-only battery reading)" in r["reason"]
        assert len(_cfg_actions(r, "switch.turn_off")) == 1
        assert _cfg_actions(r, "switch.turn_on") == []
        assert s._grid_charge_withheld_untrusted is True
        assert any(a["service"] == "number.set_value" and a["data"]["value"] == 80
                   for a in r["actions"])  # reserve untouched
        assert s.get_status()["grid_charge_withheld_untrusted"] is True

    def test_cloud_withhold_arbitrage_charge_emitter(self, clock):
        """REAL arbitrage CHARGE emitter via determine_mode: envoy tick
        enters CHARGE (turn_on); the next tick is cloud-only with CFG live
        on (latched continuation) → withheld: turn_off, key False, phase
        still CHARGE."""
        clock.set(datetime(2026, 10, 3, 20, 0, tzinfo=_UTC))  # 15:00 CDT
        s, hass, _ = _strategy(clock, stream=False, arbitrage=True)
        _st(hass, _NATIVE, "40", unit="%", lu=clock.t)
        r0 = s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert r0["arbitrage_phase"] == ARBITRAGE_PHASE_CHARGE
        assert r0["charge_from_grid"] is True
        _st(hass, _CFG_W, "on", lu=clock.t)
        clock.adv(minutes=5)
        _native_stale(hass, clock)
        s._soc_lkg = s._soc_lkg_at = None
        _cloud(hass, clock, "40")
        r = s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert s._tick_soc_source == "cloud_fallback"
        assert r["arbitrage_phase"] == ARBITRAGE_PHASE_CHARGE
        assert r["charge_from_grid"] is False
        assert "(grid charge withheld: cloud-only battery reading)" in r["reason"]
        assert len(_cfg_actions(r, "switch.turn_off")) == 1

    def test_cloud_withhold_attain_continuation(self, clock):
        """Attain CHARGE builder emitter on a cloud tick."""
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, "on", lu=clock.t)
        self._cloud_tick(clock, s, hass)
        d = s._get_attainability_decision(
            soc=40.0, now=clock.t.astimezone(_CDT), target_day_class="poor",
            tomorrow_class="poor", current_mode="self_consumption",
            season="shoulder", projected=70.0, rate=2.0, mins=120,
        )
        assert d["arbitrage_phase"] == ARBITRAGE_PHASE_ATTAIN
        assert d["charge_from_grid"] is False
        assert len(_cfg_actions(d, "switch.turn_off")) == 1

    @pytest.mark.parametrize("tier", ["envoy", "lkg", "stream"])
    def test_trusted_tiers_not_withheld(self, clock, monkeypatch, tier):
        _setc(monkeypatch, "SOC_STREAM_TIER_ENABLED", True)
        s, hass, _ = _strategy(clock)
        if tier != "envoy":
            _native_stale(hass, clock)
        if tier == "lkg":
            s._soc_lkg, s._soc_lkg_at = 40.0, clock.t - timedelta(seconds=30)
        if tier == "stream":
            _stream(hass, clock, "40")
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert s._tick_soc_source == tier
        r = s._result("self_consumption", "Arbitrage CHARGE", "self_consumption",
                      charge_from_grid=True, reserve_level=80)
        assert r["charge_from_grid"] is True
        assert s._grid_charge_withheld_untrusted is False

    def test_storm_precharge_exempt(self, clock):
        s, hass, _ = _strategy(clock, stream=False)
        self._cloud_tick(clock, s, hass)
        r = s._result("self_consumption", "Inclement pre-charging", "self_consumption",
                      charge_from_grid=True, reserve_level=100,
                      cloud_withhold_exempt=True)
        assert r["charge_from_grid"] is True

    def test_storm_precharge_site_exempt_on_cloud_tick(self, clock):
        """Q2 exemption wired at the REAL degraded storm-precharge call
        site: inclement full_hold + grid precharge on a cloud tick still
        commands charge_from_grid=True (safety over cost)."""
        s, hass, _ = _strategy(clock, stream=False)
        s._inclement_decision = lambda period, now: SimpleNamespace(
            hold_depth="full_hold", grid_precharge=True, reserve_floor=100,
            reason="storm watch",
        )
        s._last_inclement_decision_at = clock.t.astimezone(_CDT)
        _native_stale(hass, clock)
        s._soc_lkg = s._soc_lkg_at = None
        _cloud(hass, clock, "30")
        r = s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert s._tick_soc_source == "cloud_fallback"
        assert "pre-charging" in r["reason"]
        assert r["charge_from_grid"] is True
        assert "withheld" not in r["reason"]

    def test_tick_soc_source_not_torn(self, clock):
        """Tier flips between the determine_mode read and `_result`'s own
        `soc` re-read → the withhold follows the determine_mode tier."""
        s, hass, _ = _strategy(clock, stream=False)
        self._cloud_tick(clock, s, hass)
        # Native comes back mid-tick and an HVAC/DP read re-stamps envoy.
        _st(hass, _NATIVE, "40", unit="%", lu=clock.t)
        _st(hass, _SM, "self_consumption", lu=clock.t)
        s.battery_soc
        assert s._soc_source_last == "envoy"
        r = s._result("self_consumption", "Arbitrage CHARGE", "self_consumption",
                      charge_from_grid=True, reserve_level=80)
        assert s._soc_source_last == "envoy"
        assert r["charge_from_grid"] is False
        # And the converse: envoy tick, cloud by `_result` time → allowed.
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert s._tick_soc_source == "envoy"
        _native_stale(hass, clock)
        s._soc_lkg_at = clock.t - timedelta(hours=1)
        s.battery_soc
        assert s._soc_source_last == "cloud_fallback"
        r = s._result("self_consumption", "Arbitrage CHARGE", "self_consumption",
                      charge_from_grid=True, reserve_level=80)
        assert s._soc_source_last == "cloud_fallback"
        assert r["charge_from_grid"] is True

    def test_withhold_flag_entry_reset_on_blind_branch(self, clock):
        """R2-7: blind branch returns without `_result` — the flag resets."""
        s, hass, _ = _strategy(clock, stream=False)
        s._grid_charge_withheld_untrusted = True
        _native_stale(hass, clock)
        s._soc_lkg_at = None
        _st(hass, _CLOUD, "unavailable", lu=clock.t)
        r = s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert "Envoy unavailable" in r["reason"]
        assert s._grid_charge_withheld_untrusted is False

    @pytest.mark.asyncio
    async def test_cloud_withhold_keeps_ev_paused(self, clock):
        """Same tick through the chokepoint: CHARGE phase → breaker pause
        even though charge_from_grid was withheld (R2-11 key is False)."""
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, "off", lu=clock.t)
        self._cloud_tick(clock, s, hass)
        r = s._result("self_consumption", "Arbitrage CHARGE", "self_consumption",
                      charge_from_grid=True, reserve_level=80,
                      arbitrage_phase=ARBITRAGE_PHASE_CHARGE)
        assert r["charge_from_grid"] is False
        shell = _DispatchShell(s, hass, _evpool())
        reason, _, _ = await shell._execute_breaker_safe_dispatch(r, "off_peak")
        assert reason == "breaker"

    def test_cloud_withhold_alternation_bounded(self, clock):
        """R2-6 on the REAL arbitrage path: envoy/cloud x10 → turn_off only
        on cloud ticks, turn_on only on native ticks, phase never reset by
        the withhold (no stranding hysteresis)."""
        clock.set(datetime(2026, 10, 3, 19, 30, tzinfo=_UTC))  # 14:30 CDT
        s, hass, _ = _strategy(clock, stream=False, arbitrage=True)
        cfg_on = False
        for i in range(10):
            clock.adv(minutes=5)
            cloud = (i % 2 == 1)
            _st(hass, _CFG_W, "on" if cfg_on else "off", lu=clock.t)
            if cloud:
                _native_stale(hass, clock)
                s._soc_lkg = s._soc_lkg_at = None
                _cloud(hass, clock, "40")
            else:
                _st(hass, _NATIVE, "40", unit="%", lu=clock.t)
                _st(hass, _SM, "self_consumption", lu=clock.t)
            r = s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
            assert s._tick_soc_source == ("cloud_fallback" if cloud else "envoy")
            assert r["arbitrage_phase"] == ARBITRAGE_PHASE_CHARGE, (i, r["reason"])
            offs, ons = _cfg_actions(r, "switch.turn_off"), _cfg_actions(r, "switch.turn_on")
            assert bool(offs) is cloud and bool(ons) is (not cloud), (i, r["actions"])
            cfg_on = not cloud  # the dispatched command lands


# ===========================================================================
# D4 — page before a boundary
# ===========================================================================


def _pages(coord):
    return [n for n in coord.nm if n["hazard_type"] == "battery_soc_unknown_before_boundary"]


def _blind_tick(clock, s, hass, *, cloud=False):
    _native_stale(hass, clock)
    s._soc_lkg_at = None
    if cloud:
        _cloud(hass, clock, "50")
    else:
        _st(hass, _CLOUD, "unavailable", lu=clock.t)
    s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))


class TestD4Page:
    def test_page_fires_once_per_boundary(self, clock):
        # 2026-10-03 15:30 CDT (off_peak; 17:00 mid_peak boundary).
        clock.set(datetime(2026, 10, 3, 20, 30, tzinfo=_UTC))
        s, hass, coord = _strategy(clock, stream=False)
        for _ in range(3):  # 15:30, 15:35, 15:40 → dwell 10 at 15:40
            _blind_tick(clock, s, hass)
            clock.adv(minutes=5)
        assert len(_pages(coord)) == 1
        p = _pages(coord)[0]
        assert p["severity"] == "high"
        assert "80 min before the 17:00" in p["message"]
        for _ in range(4):
            _blind_tick(clock, s, hass)
            clock.adv(minutes=5)
        assert len(_pages(coord)) == 1
        # Next day's boundary → one more.
        clock.set(datetime(2026, 10, 4, 20, 30, tzinfo=_UTC))
        for _ in range(3):
            _blind_tick(clock, s, hass)
            clock.adv(minutes=5)
        assert len(_pages(coord)) == 2

    def test_page_not_fired_on_blip(self, clock):
        clock.set(datetime(2026, 10, 3, 20, 30, tzinfo=_UTC))
        s, hass, coord = _strategy(clock, stream=False)
        _blind_tick(clock, s, hass)
        clock.adv(minutes=5)
        _blind_tick(clock, s, hass)
        clock.adv(minutes=5)
        _st(hass, _NATIVE, "50", unit="%", lu=clock.t)
        _st(hass, _SM, "self_consumption", lu=clock.t)
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        clock.adv(minutes=5)
        _blind_tick(clock, s, hass)
        assert _pages(coord) == []

    def test_page_not_fired_on_stream_tier(self, clock, stream_on):
        clock.set(datetime(2026, 10, 3, 20, 30, tzinfo=_UTC))
        s, hass, coord = _strategy(clock)
        for _ in range(5):
            _native_stale(hass, clock)
            _stream(hass, clock, "90")
            s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
            assert s._tick_soc_source == "stream"
            clock.adv(minutes=5)
        assert _pages(coord) == []

    def test_page_cloud_note_and_dwell_boundaries(self, clock):
        """dwell 10 min hard literal: 9:59 no page, 10:00 page; lead 90:
        first untrusted tick at T-120 pages only once inside T-90."""
        clock.set(datetime(2026, 10, 3, 20, 0, tzinfo=_UTC))  # 15:00 CDT, T-120
        s, hass, coord = _strategy(clock, stream=False)
        _blind_tick(clock, s, hass, cloud=True)
        clock.adv(minutes=29)  # 15:29 → T-91
        _blind_tick(clock, s, hass, cloud=True)
        assert _pages(coord) == []
        clock.adv(minutes=1)  # 15:30 → T-90
        _blind_tick(clock, s, hass, cloud=True)
        assert len(_pages(coord)) == 1
        assert "cloud reading only" in _pages(coord)[0]["message"]

    def test_page_dwell_exact_literal(self, clock):
        clock.set(datetime(2026, 10, 3, 21, 0, tzinfo=_UTC))  # 16:00, T-60
        s, hass, coord = _strategy(clock, stream=False)
        _blind_tick(clock, s, hass)
        clock.adv(seconds=599)
        _blind_tick(clock, s, hass)
        assert _pages(coord) == []
        clock.adv(seconds=1)
        _blind_tick(clock, s, hass)
        assert len(_pages(coord)) == 1

    @pytest.mark.parametrize("lead,dwell,expect", [
        (0, 10, 0), (-1, 10, 0), (90, 0, 0), (1440, 10, 1), (1440, 0, 1),
        (30, 10, 0),
    ])
    def test_page_knob_extremes(self, clock, monkeypatch, lead, dwell, expect):
        _setc(monkeypatch, "DEFAULT_SOC_UNTRUSTED_PAGE_LEAD_MIN", lead)
        _setc(monkeypatch, "DEFAULT_SOC_UNTRUSTED_PAGE_DWELL_MIN", dwell)
        clock.set(datetime(2026, 10, 3, 20, 0, tzinfo=_UTC))  # T-120 → T-110
        s, hass, coord = _strategy(clock, stream=False)
        _blind_tick(clock, s, hass)
        clock.adv(minutes=10)
        _blind_tick(clock, s, hass)
        assert len(_pages(coord)) == expect

    def test_page_lead_zero_never_pages_even_at_boundary(self, clock, monkeypatch):
        _setc(monkeypatch, "DEFAULT_SOC_UNTRUSTED_PAGE_LEAD_MIN", 0)
        clock.set(datetime(2026, 10, 3, 21, 40, tzinfo=_UTC))  # 16:40 CDT
        s, hass, coord = _strategy(clock, stream=False)
        _blind_tick(clock, s, hass)
        clock.set(datetime(2026, 10, 3, 21, 59, 30, tzinfo=_UTC))  # mins=0
        _blind_tick(clock, s, hass)
        assert _pages(coord) == []

    def test_page_skipped_in_peak_and_without_boundary(self, clock):
        clock.set(datetime(2026, 10, 3, 20, 30, tzinfo=_UTC))
        s, hass, coord = _strategy(clock, stream=False)
        for _ in range(4):
            _native_stale(hass, clock)
            _st(hass, _CLOUD, "unavailable", lu=clock.t)
            s.determine_mode("peak", "summer", now=clock.t.astimezone(_CDT))
            clock.adv(minutes=5)
        assert _pages(coord) == []
        s._tou = None  # no boundary (holiday / no engine)
        for _ in range(4):
            _blind_tick(clock, s, hass)
            clock.adv(minutes=5)
        assert _pages(coord) == []

    def test_page_mid_peak_targets_peak_summer(self, clock):
        """R2-2: mid_peak → next peak (summer mid 14-16 → peak 16)."""
        clock.set(datetime(2026, 7, 15, 20, 0, tzinfo=_UTC))  # 15:00 CDT, T-60
        s, hass, coord = _strategy(clock, stream=False)
        for _ in range(3):
            _native_stale(hass, clock)
            _st(hass, _CLOUD, "unavailable", lu=clock.t)
            s.determine_mode("mid_peak", "summer", now=clock.t.astimezone(_CDT))
            clock.adv(minutes=5)
        assert len(_pages(coord)) == 1
        assert "16:00" in _pages(coord)[0]["message"]

    def test_page_latch_survives_restart(self, clock):
        clock.set(datetime(2026, 10, 3, 20, 30, tzinfo=_UTC))
        s, hass, coord = _strategy(clock, stream=False)
        for _ in range(3):
            _blind_tick(clock, s, hass)
            clock.adv(minutes=5)
        assert len(_pages(coord)) == 1
        assert coord.saves >= 1  # event-save on latch
        snap = json.loads(json.dumps(s.get_page_latch_snapshot()))
        s2, hass2, coord2 = _strategy(clock, stream=False)
        s2.restore_page_latch_snapshot(snap)
        for _ in range(3):
            _blind_tick(clock, s2, hass2)
            clock.adv(minutes=5)
        assert _pages(coord2) == []

    def test_page_does_not_change_decision(self, clock, monkeypatch):
        """R2-12 / I-7: blind-branch decision dict identical with the page
        neutralised vs live."""
        clock.set(datetime(2026, 10, 3, 20, 50, tzinfo=_UTC))
        s, hass, _ = _strategy(clock, stream=False)
        s._untrusted_since = clock.t - timedelta(minutes=30)
        _native_stale(hass, clock)
        _st(hass, _CLOUD, "unavailable", lu=clock.t)
        r1 = s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        s2, hass2, _ = _strategy(clock, stream=False)
        monkeypatch.setattr(s2, "_evaluate_untrusted_boundary_page", lambda *a: None)
        _native_stale(hass2, clock)
        _st(hass2, _CLOUD, "unavailable", lu=clock.t)
        r2 = s2.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert r1 == r2


# ===========================================================================
# D5 — attributes
# ===========================================================================


class TestD5Attrs:
    @pytest.mark.parametrize("kind,trusted", [
        ("envoy", True), ("lkg", True), ("cloud", False), ("none", False),
    ])
    def test_attrs_per_tier(self, clock, kind, trusted):
        s, hass, coord = _strategy(clock, stream=False)
        coord._ev = SimpleNamespace(_arb_release_refused_since={"garage_b": 1.0, "garage_a": 2.0})
        if kind != "envoy":
            _native_stale(hass, clock)
        if kind == "lkg":
            s._soc_lkg, s._soc_lkg_at = 50.0, clock.t
        if kind == "cloud":
            _cloud(hass, clock, "50")
        if kind == "none":
            _st(hass, _CLOUD, "unavailable", lu=clock.t)
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        st = s.get_status()
        assert st["soc_tier_trusted"] is trusted
        assert st["stream_trust"] == "disabled"
        assert st["grid_charge_withheld_untrusted"] is False
        assert st["arb_release_refused"] == ["garage_a", "garage_b"]

    def test_soc_tier_trusted_uses_tick_capture_not_last(self, clock):
        s, hass, _ = _strategy(clock, stream=False)
        _native_stale(hass, clock)
        _cloud(hass, clock, "50")
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        # HVAC-style re-read after native recovers stamps `envoy` ...
        _st(hass, _NATIVE, "50", unit="%", lu=clock.t)
        _st(hass, _SM, "self_consumption", lu=clock.t)
        st = s.get_status()
        assert st["soc_source"] == "envoy"
        assert st["soc_tier_trusted"] is False  # ... the tick verdict stands

    def test_stream_trust_attr_values(self, clock, stream_on):
        s, _, _ = _strategy(clock)
        assert s.get_status()["stream_trust"] == "trusted"
        s._soc_stream_trust = "quarantined"
        assert s.get_status()["stream_trust"] == "quarantined"


# ===========================================================================
# Config flow — stream fields map + round trip
# ===========================================================================


def test_entity_map_stream_fields():
    shell = SimpleNamespace()
    m = EnergyCoordinator._build_entity_map(shell, {
        "energy_stream_battery_soc_entity": "sensor.s",
        "energy_stream_cowitness_entity": "sensor.c",
    })
    assert m["battery_soc_stream"] == "sensor.s"
    assert m["stream_cowitness"] == "sensor.c"
    m2 = EnergyCoordinator._build_entity_map(shell, {"energy_envoy_entity": "x"})
    assert "battery_soc_stream" not in m2 and "stream_cowitness" not in m2
    m3 = EnergyCoordinator._build_entity_map(shell, {"energy_stream_battery_soc_entity": ""})
    assert m3["battery_soc_stream"] == ""


def test_blank_stream_entity_keeps_tier_off(clock, stream_on):
    s, hass, _ = _strategy(clock, extra={"battery_soc_stream": ""})
    _native_stale(hass, clock)
    _stream(hass, clock, "90")
    _cloud(hass, clock, "50")
    assert s.battery_soc == 50.0
    assert s.stream_trust_state() == "disabled"


def test_config_flow_round_trip_stream_fields():
    import importlib
    rt = importlib.import_module("test_baec_config_flow_round_trip")
    flow = rt._make_options_flow(options={"energy_envoy_entity": "sensor.envoy"})
    user_input = {"cloud_verification": {
        "energy_stream_battery_soc_entity": "sensor.envoy_stream_battery_soc",
        "energy_stream_cowitness_entity": "sensor.envoy_stream_grid_power",
    }}
    with rt._ha_mocks_injected():
        result = rt._run(flow.async_step_coordinator_energy(user_input=user_input))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert saved["energy_stream_battery_soc_entity"] == "sensor.envoy_stream_battery_soc"
    assert saved["energy_stream_cowitness_entity"] == "sensor.envoy_stream_grid_power"
    assert "cloud_verification" not in saved
    m = EnergyCoordinator._build_entity_map(SimpleNamespace(), saved)
    assert m["battery_soc_stream"] == "sensor.envoy_stream_battery_soc"


# ===========================================================================
# §7 Replay — recorder windows, REAL resolver picks every tier (R2-13)
# ===========================================================================


def _fx():
    return json.loads(_FIX.read_text())


def _p(s):
    return datetime.fromisoformat(s) if s else None


def _apply_asof(hass, win, t):
    """Set every fixture entity to its recorder as-of row at time t.

    Native Envoy SOC + local storage-mode freshness reconstruction (see
    fixture `known_recorder_limit`): a numeric as-of row is reporting at t.
    Everything else keeps its recorded stamps.
    """
    for eid, rows in win.items():
        if eid == "strategy_oracle":
            continue
        row = None
        for r in rows:
            if _p(r[1]) <= t:
                row = r
            else:
                break
        if row is None:
            continue
        state, lu, lr, unit = row[0], _p(row[1]), _p(row[2]), row[3]
        if eid in (_NATIVE, _SM) and state not in ("unavailable", "unknown"):
            lr = t
        _st(hass, eid, state, unit=unit, lu=lu, lr=lr or lu)


def _replay(clock, win, t0, t1, *, stream, render_s=30, decide_at=None, on_decide=None):
    s, hass, coord = _strategy(clock, stream=stream, cowitness=stream)
    _st(hass, _CFG_W, "off", lu=t0)
    out = []
    renders = []
    t = t0
    while t <= t1:
        renders.append((t, 0))
        t = t + timedelta(seconds=render_s)
    timeline = sorted(renders + [(d, 1) for d in (decide_at or [])])
    for t, kind in timeline:
        clock.set(t)
        _apply_asof(hass, win, t)
        if kind == 0:
            s.battery_soc  # sensor render cadence keeps LKG as live
            continue
        r = s.determine_mode(
            s._tou.get_current_period(t.astimezone(_CDT)),
            "shoulder", now=t.astimezone(_CDT),
        )
        out.append((t, s._tick_soc_source, r))
        if on_decide is not None:
            on_decide(t, s, r)
    return s, coord, out


def _oracle_ticks(win, t0, t1):
    return [(_p(r[0]), r[1], r[2]) for r in win["strategy_oracle"]
            if t0 <= _p(r[0]) <= t1 and r[1] is not None]


class TestReplay:
    def test_fixture_authority_resolver_matches_live_soc_source(self, clock):
        """Kill switch off: the real resolver on recorder rows reproduces
        the live `soc_source` at the oracle render times (10-01 window).
        Validates the replay reconstruction before trusting it below."""
        win = _fx()["windows"]["w_2026_10_01_0600z"]
        t0 = datetime(2026, 10, 1, 5, 44, tzinfo=_UTC)
        t1 = datetime(2026, 10, 1, 7, 59, tzinfo=_UTC)
        ticks = _oracle_ticks(win, t0, t1)
        s, _, out = _replay(clock, win, t0 - timedelta(minutes=2), t1, stream=False,
                            render_s=30, decide_at=[t for t, _, _ in ticks])
        got = {t: tier for t, tier, _ in out}
        matches = sum(1 for t, src, _ in ticks if got.get(t) == src)
        # Measured 2026-10-04: all 49 oracle rows reproduce exactly.
        assert len(ticks) == 49
        assert matches == 49
        for t, src, _ in ticks:
            if src in ("cloud_fallback", "fallback_stale_reject"):
                assert not eb_mod.soc_tier_trusted(got[t]), (t, src, got[t])

    def test_replay_2026_10_01_d2a_refuses_untrusted_turn_ons(self, clock, mono):
        """§7 row 4: solar_attain (redirect pause) → wait (release) ticks.
        Releases on untrusted ticks (live: 3 cloud + 1 blind turn-ons) are
        refused; trusted-tick releases still turn on."""
        win = _fx()["windows"]["w_2026_10_01_0600z"]
        t0 = datetime(2026, 10, 1, 5, 44, tzinfo=_UTC)
        t1 = datetime(2026, 10, 1, 7, 59, 30, tzinfo=_UTC)
        ticks = _oracle_ticks(win, t0, t1)
        ev = _evpool()
        log = []

        def _on(t, s, r):
            phase = next(p for tt, _, p in ticks if tt == t)
            untrusted = not eb_mod.soc_tier_trusted(s._tick_soc_source)
            if phase == "solar_attain":
                ev.determine_arbitrage_actions(
                    arbitrage_charging=True, tou_period="off_peak",
                    pause_reason="redirect", soc_untrusted=untrusted)
            else:
                acts = ev.determine_arbitrage_actions(
                    arbitrage_charging=False, tou_period="off_peak",
                    soc_untrusted=untrusted, cfg_provably_off=True)
                log.append((t, s._tick_soc_source, bool(_turn_ons(acts))))
        _replay(clock, win, t0 - timedelta(minutes=2), t1, stream=False,
                decide_at=[t for t, _, _ in ticks], on_decide=_on)
        untrusted_on = [x for x in log if x[2] and not eb_mod.soc_tier_trusted(x[1])]
        by_t = {t.strftime("%H:%M:%S"): (tr, on) for t, tr, on in log}
        # Live, EVs turned on right after these two cloud ticks (06:20:09,
        # 06:30:22 switch rows); under D2a both releases are refused.
        assert by_t["06:19:59"] == ("cloud_fallback", False)
        assert by_t["06:29:45"] == ("cloud_fallback", False)
        # First trusted tick after the outage releases (liveness).
        assert by_t["06:39:35"] == ("envoy", True)
        assert untrusted_on == []
        trusted_on = [x for x in log if x[2]]
        assert len(trusted_on) >= 3  # liveness on trusted ticks preserved

    def test_replay_2026_10_03_1600_kill_switch_off(self, clock):
        """§7 row 1 (kill switch off): untrusted < dwell before 17:00 →
        no page; no cloud tick returns charge_from_grid=True; the 22:21Z
        cloud reading is the 96.2 over-read."""
        win = _fx()["windows"]["w_2026_10_03_1600_cdt"]
        t0 = datetime(2026, 10, 3, 20, 55, tzinfo=_UTC)
        t1 = datetime(2026, 10, 3, 22, 35, tzinfo=_UTC)
        dec = [t0 + timedelta(minutes=5 * i) for i in range(21)]
        s, coord, out = _replay(clock, win, t0, t1, stream=False, decide_at=dec)
        tiers = {t: tier for t, tier, _ in out}
        assert tiers[datetime(2026, 10, 3, 21, 10, tzinfo=_UTC)] == "fallback_stale_reject"
        assert tiers[datetime(2026, 10, 3, 22, 25, tzinfo=_UTC)] == "cloud_fallback"
        assert out[[t for t, _, _ in out].index(datetime(2026, 10, 3, 22, 25, tzinfo=_UTC))][2]["soc"] == 96.2
        assert _pages(coord) == []
        for t, tier, r in out:
            if tier == "cloud_fallback":
                assert r.get("charge_from_grid") is not True

    def test_replay_2026_10_03_1600_kill_switch_on(self, clock, stream_on):
        """§7 row 1 (kill switch on): every native-out decision tick is
        served by the stream at ~90, never the 96.2 cloud over-read."""
        win = _fx()["windows"]["w_2026_10_03_1600_cdt"]
        t0 = datetime(2026, 10, 3, 22, 5, tzinfo=_UTC)
        t1 = datetime(2026, 10, 3, 22, 27, tzinfo=_UTC)
        dec = [t0 + timedelta(minutes=5 * i) for i in range(5)]
        _, coord, out = _replay(clock, win, t0 - timedelta(minutes=10), t1,
                                stream=True, decide_at=dec)
        assert [tier for _, tier, _ in out] == ["stream"] * 5
        socs = [r["soc"] for _, _, r in out]
        assert socs == [96.0, 95.0, 93.0, 92.0, 91.0]  # stream as-of rows
        assert all("Envoy unavailable" not in r["reason"] for _, _, r in out)
        assert _pages(coord) == []

    def test_replay_2026_10_03_0037_restart_outage(self, clock, stream_on):
        """§7 row 2: stream was OFF (unavailable) → falls through cleanly
        (never parsed as 0); no page (17:00 boundary outside the lead)."""
        win = _fx()["windows"]["w_2026_10_03_0037_cdt"]
        t0 = datetime(2026, 10, 3, 5, 35, tzinfo=_UTC)
        t1 = datetime(2026, 10, 3, 6, 0, tzinfo=_UTC)
        dec = [t0 + timedelta(minutes=5 * i) for i in range(6)]
        _, coord, out = _replay(clock, win, t0, t1, stream=True, decide_at=dec)
        tiers = [tier for _, tier, _ in out]
        assert "stream" not in tiers
        assert any(not eb_mod.soc_tier_trusted(x) for x in tiers)
        assert all(r["soc"] != 0 for _, _, r in out)
        assert _pages(coord) == []

    def test_replay_2026_10_02_page_time(self, clock):
        """§7 row 3: 10-02 14:00-15:48 CDT blind hold (cloud frozen 10.0
        since 14:28Z → stale) → exactly one page at the first decision
        tick inside T-90 (15:30 CDT = 20:30Z)."""
        win = _fx()["windows"]["w_2026_10_02_1400_cdt"]
        t0 = datetime(2026, 10, 2, 19, 0, tzinfo=_UTC)
        t1 = datetime(2026, 10, 2, 20, 47, tzinfo=_UTC)
        dec = [t0 + timedelta(minutes=5 * i) for i in range(22)]
        sent = []

        def _on(t, s, r):
            n = len(_pages(s._coord))
            if n and not sent:
                sent.append(t)
        _, coord, out = _replay(clock, win, t0, t1, stream=False, decide_at=dec, on_decide=_on)
        assert len(_pages(coord)) == 1
        assert sent == [datetime(2026, 10, 2, 20, 30, tzinfo=_UTC)]
        assert "90 min before the 17:00" in _pages(coord)[0]["message"]


# ===========================================================================
# Resilience bundle (PLANNING_ec_enphase_resilience_and_p1_adjust.md §5)
#   B1 LKG persistence, B2 write-outcome capture + churn, B3 must-start-by
#   behind the blind-window guard, B4 Envoy-offline text, B5 fresh CFG off.
# ===========================================================================


# --- B1 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lkg_soc_survives_restart_real_writer(clock):
    """I-R2: production `_save_evse_state` → `_restore_evse_state` round
    trip of the LKG SOC (was never written: unbound `_json`)."""
    s, hass, _ = _strategy(clock)
    kv = _KV()
    hass.data["universal_room_automation"] = {"database": kv}
    stamp = clock.t - timedelta(seconds=40)
    s._soc_lkg, s._soc_lkg_at = 61.5, stamp
    await _persist_shell(hass, s)._save_evse_state()
    assert json.loads(kv.rows["battery_soc_lkg"])["value"] == 61.5
    s2, hass2, _ = _strategy(clock)
    hass2.data["universal_room_automation"] = {"database": kv}
    assert s2.get_lkg_snapshot() is None
    await _persist_shell(hass2, s2)._restore_evse_state()
    assert s2._soc_lkg == 61.5
    assert s2._soc_lkg_at == stamp


@pytest.mark.asyncio
async def test_solar_lkg_survives_restart_real_writer(clock):
    s, hass, _ = _strategy(clock)
    kv = _KV()
    hass.data["universal_room_automation"] = {"database": kv}
    stamp = clock.t - timedelta(seconds=90)
    s._solar_prod_lkg_w, s._solar_prod_lkg_at = 4321.0, stamp
    await _persist_shell(hass, s)._save_evse_state()
    assert "solar_production_w_lkg" in kv.rows
    s2, hass2, _ = _strategy(clock)
    hass2.data["universal_room_automation"] = {"database": kv}
    await _persist_shell(hass2, s2)._restore_evse_state()
    assert s2._solar_prod_lkg_w == 4321.0
    assert s2._solar_prod_lkg_at == stamp


@pytest.mark.asyncio
async def test_lkg_save_failure_logs_warning_once(clock, caplog):
    import logging as _lg
    s, hass, _ = _strategy(clock)
    hass.data["universal_room_automation"] = {"database": _KV()}

    def _boom():
        raise RuntimeError("boom")
    s.get_lkg_snapshot = _boom
    shell = _persist_shell(hass, s)
    shell._warn_lkg_save_failed_once = (
        EnergyCoordinator._warn_lkg_save_failed_once.__get__(shell, type(shell))
    )
    with caplog.at_level(_lg.DEBUG):
        await shell._save_evse_state()
        await shell._save_evse_state()
    warns = [r for r in caplog.records
             if r.levelno == _lg.WARNING and "LKG SOC save failed" in r.getMessage()]
    assert len(warns) == 1


# --- B2 -------------------------------------------------------------------


class _AnomDB:
    def __init__(self) -> None:
        self.rows: list = []

    async def save_anomaly_event(self, evt):
        self.rows.append(evt)


class _WriteShell(EnergyCoordinator):
    """Real `_execute_breaker_safe_dispatch` / `_execute_service_action` /
    `_tap_write_verifier` + a REAL WriteVerifier. Only the HA service bus
    and NM are faked."""

    def __init__(self):  # noqa: D401 - bypass heavy init
        pass


def _write_shell(clock, *, cfg_state="on", raise_on=None, exc=None):
    from custom_components.universal_room_automation.domain_coordinators.energy_write_verify import (
        WriteVerifier,
    )
    s, hass, _ = _strategy(clock, stream=False)
    _st(hass, _CFG_W, cfg_state, lu=clock.t)
    c = _WriteShell()
    c.hass = hass
    c._battery = s
    c._ev = _evpool()
    c._ev.hass = hass
    c._last_known_grid_charge_on = False
    c._last_cfg_off_read_at = None
    c._cfg_unknown_forced_since = None
    c.calls: list = []
    c.nm: list = []
    db = _AnomDB()
    c.db = db
    hass.data["universal_room_automation"] = {"database": db}

    async def _svc(domain, svc, data, blocking=False, **kw):
        c.calls.append((domain, svc, data.get("entity_id")))
        if raise_on is not None and (domain, svc) == raise_on:
            raise exc
    hass.services = SimpleNamespace(async_call=_svc)

    async def _nm(**kw):
        c.nm.append(kw)
    c._send_nm_alert = _nm
    c._write_verifier = WriteVerifier(hass, c)
    s._write_verifier = c._write_verifier
    return c, s


def _sve(key):
    from homeassistant.exceptions import ServiceValidationError
    return ServiceValidationError(translation_domain="enphase_ev", translation_key=key)


def _anoms(c, typ):
    return [e for e in c.db.rows if e.type == typ]


def _dispatch_nms(c):
    return [n for n in c.nm if n["title"].startswith("Battery command failed")]


_CFG_OFF_DECISION = {
    "actions": [{"service": "switch.turn_off", "target": _CFG_W, "data": {}}],
    "arbitrage_phase": "n/a", "charge_from_grid": False,
}


class TestB2WriteOutcome:
    @pytest.mark.asyncio
    async def test_cfg_turn_off_failure_records_dispatch_failed(self, clock):
        """I-R1: a raised CFG write → `dispatch_failed`, 1 anomaly, 1 NM;
        a second failure the same day → anomaly only."""
        c, s = _write_shell(
            clock, raise_on=("switch", "turn_off"),
            exc=_sve("charge_from_grid_toggle_not_applied"),
        )
        await c._execute_breaker_safe_dispatch(dict(_CFG_OFF_DECISION), "peak")
        rec = c._write_verifier._records["charge_from_grid"]
        assert rec.status == "dispatch_failed"
        assert rec.commanded is False
        a = _anoms(c, "battery_write_failed")
        assert len(a) == 1
        assert a[0].payload["extra"]["translation_key"] == (
            "charge_from_grid_toggle_not_applied")
        assert a[0].payload["extra"]["exception"] == "ServiceValidationError"
        assert a[0].payload["extra"]["surface"] == "charge_from_grid"
        assert len(_dispatch_nms(c)) == 1
        assert _dispatch_nms(c)[0]["severity"] == "high"
        clock.adv(minutes=5)
        await c._execute_breaker_safe_dispatch(dict(_CFG_OFF_DECISION), "peak")
        assert len(_anoms(c, "battery_write_failed")) == 2
        assert len(_dispatch_nms(c)) == 1

    @pytest.mark.asyncio
    async def test_successful_write_records_nothing(self, clock):
        c, s = _write_shell(clock)
        await c._execute_breaker_safe_dispatch(dict(_CFG_OFF_DECISION), "peak")
        assert c._write_verifier._records["charge_from_grid"].status != "dispatch_failed"
        assert _anoms(c, "battery_write_failed") == [] and _dispatch_nms(c) == []

    @pytest.mark.asyncio
    async def test_reserve_and_storage_failures_recorded(self, clock):
        from homeassistant.exceptions import HomeAssistantError
        c, s = _write_shell(clock, raise_on=("number", "set_value"),
                            exc=HomeAssistantError("cloud down"))
        reserve_eid = s._get_entity("reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY,
                                    role="write")
        d = {"actions": [{"service": "number.set_value", "target": reserve_eid,
                          "data": {"value": 40}}],
             "arbitrage_phase": "n/a", "charge_from_grid": False}
        await c._execute_breaker_safe_dispatch(d, "peak")
        assert c._write_verifier._records["reserve_soc"].status == "dispatch_failed"
        assert s._last_reserve_level == 40  # intent ledger unchanged
        assert len(_anoms(c, "battery_write_failed")) == 1

    @pytest.mark.asyncio
    async def test_failed_turn_on_keeps_ledger_fail_closed(self, clock):
        """Ledger stays an INTENT ledger: a failed turn_on still stamps it,
        so with the cloud leg unavailable the breaker intent is True."""
        c, s = _write_shell(clock, cfg_state="unavailable", raise_on=("switch", "turn_on"),
                            exc=_sve("battery_settings_update_debounced"))
        d = {"actions": [{"service": "switch.turn_on", "target": _CFG_W, "data": {}}],
             "arbitrage_phase": "n/a", "charge_from_grid": False}
        await c._execute_breaker_safe_dispatch(d, "off_peak")
        assert s._last_charge_from_grid_command is True
        assert c._write_verifier._records["charge_from_grid"].status == "dispatch_failed"
        clock.adv(minutes=5)
        _, _, intent = await c._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert intent is True
        assert c._last_known_grid_charge_on is False  # ledger alone holds

    @pytest.mark.asyncio
    async def test_d3_withhold_dispatch_failed_attr(self, clock):
        """D3 cloud-only withhold emits CFG turn_off; it raises → D5 attr
        True. Next determine_mode entry-resets it."""
        c, s = _write_shell(clock, cfg_state="on", raise_on=("switch", "turn_off"),
                            exc=_sve("charge_from_grid_toggle_not_applied"))
        _native_stale(c.hass, clock)
        s._soc_lkg = s._soc_lkg_at = None
        _cloud(c.hass, clock, "40")
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        r = s._result("self_consumption", "Arbitrage CHARGE", "self_consumption",
                      charge_from_grid=True, reserve_level=80,
                      arbitrage_phase=ARBITRAGE_PHASE_CHARGE)
        assert s._grid_charge_withheld_untrusted is True
        assert s.get_status()["grid_charge_withhold_dispatch_failed"] is False
        await c._execute_breaker_safe_dispatch(r, "off_peak")
        assert s.get_status()["grid_charge_withhold_dispatch_failed"] is True
        s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(_CDT))
        assert s.get_status()["grid_charge_withhold_dispatch_failed"] is False

    @pytest.mark.asyncio
    async def test_storage_mode_failure_recorded(self, clock):
        from homeassistant.exceptions import HomeAssistantError
        c, s = _write_shell(clock, raise_on=("select", "select_option"),
                            exc=HomeAssistantError("cloud down"))
        sm = s._get_entity("storage_mode", DEFAULT_STORAGE_MODE_ENTITY, role="write")
        d = {"actions": [{"service": "select.select_option", "target": sm,
                          "data": {"option": "backup"}}],
             "arbitrage_phase": "n/a", "charge_from_grid": False}
        await c._execute_breaker_safe_dispatch(d, "peak")
        assert c._write_verifier._records["storage_mode"].status == "dispatch_failed"
        assert len(_anoms(c, "battery_write_failed")) == 1

    @pytest.mark.asyncio
    async def test_withhold_successful_turn_off_no_attr(self, clock):
        c, s = _write_shell(clock)
        s._grid_charge_withheld_untrusted = True
        await c._execute_breaker_safe_dispatch(dict(_CFG_OFF_DECISION), "peak")
        assert s.get_status()["grid_charge_withhold_dispatch_failed"] is False

    @pytest.mark.asyncio
    async def test_withhold_failed_turn_on_no_attr(self, clock):
        """Only the withhold's own turn_OFF sets the attr."""
        c, s = _write_shell(clock, cfg_state="off", raise_on=("switch", "turn_on"),
                            exc=_sve("battery_settings_update_debounced"))
        s._grid_charge_withheld_untrusted = True
        d = {"actions": [{"service": "switch.turn_on", "target": _CFG_W, "data": {}}],
             "arbitrage_phase": "n/a", "charge_from_grid": False}
        await c._execute_breaker_safe_dispatch(d, "off_peak")
        assert s.get_status()["grid_charge_withhold_dispatch_failed"] is False

    @pytest.mark.asyncio
    async def test_failed_turn_off_without_withhold_no_attr(self, clock):
        c, s = _write_shell(clock, raise_on=("switch", "turn_off"),
                            exc=_sve("charge_from_grid_toggle_not_applied"))
        s._grid_charge_withheld_untrusted = False
        await c._execute_breaker_safe_dispatch(dict(_CFG_OFF_DECISION), "peak")
        assert s.get_status()["grid_charge_withhold_dispatch_failed"] is False

    @pytest.mark.asyncio
    async def test_execute_service_action_callers_unchanged(self, clock):
        """Non-battery callers: no raise, same service call, result is
        returned (ok / failed) and ignored safely."""
        c, s = _write_shell(clock, raise_on=("switch", "turn_on"),
                            exc=RuntimeError("x"))
        c._log_charger_actuation = lambda *a, **k: None
        ok = await c._execute_service_action(
            {"service": "switch.turn_off", "target": "switch.garage_a"})
        bad = await c._execute_service_action(
            {"service": "switch.turn_on", "target": "switch.garage_a"})
        none = await c._execute_service_action({"service": ""})
        assert (ok.ok, ok.exc_type, ok.translation_key) == (True, None, None)
        assert (bad.ok, bad.exc_type, bad.translation_key) == (False, "RuntimeError", None)
        assert none is None
        assert c.calls == [("switch", "turn_off", "switch.garage_a"),
                           ("switch", "turn_on", "switch.garage_a")]
        malformed = await c._execute_service_action({"service": "noservice"})
        assert (malformed.ok, malformed.exc_type) == (False, "malformed_service")
        # A failed NON-battery call never reaches the battery verifier.
        assert _anoms(c, "battery_write_failed") == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("n,expect_nm", [(12, 0), (13, 1), (30, 1)])
    async def test_battery_write_churn_nm(self, clock, n, expect_nm):
        """I-R4: >12 CFG writes in a rolling hour → exactly 1 NM + 1 anomaly
        per surface per day; 12 → none."""
        c, s = _write_shell(clock)
        for i in range(n):
            await c._execute_breaker_safe_dispatch(dict(_CFG_OFF_DECISION), "peak")
            clock.adv(seconds=150)  # 30 writes span 75 min; first 13 < 60 min
        churn = [x for x in c.nm if x["title"].startswith("Battery command churn")]
        assert len(churn) == expect_nm
        assert len(_anoms(c, "battery_write_churn")) == expect_nm

    @pytest.mark.asyncio
    async def test_churn_window_rolls(self, clock):
        """13 writes spread over > 60 min never exceed 12 in the window."""
        c, s = _write_shell(clock)
        for _ in range(13):
            await c._execute_breaker_safe_dispatch(dict(_CFG_OFF_DECISION), "peak")
            clock.adv(seconds=301)
        assert [x for x in c.nm if x["title"].startswith("Battery command churn")] == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cap", [0, -1])
    async def test_churn_kill_switch(self, clock, monkeypatch, cap):
        _setc(monkeypatch, "DEFAULT_BATTERY_WRITE_CHURN_MAX_PER_H", cap)
        c, s = _write_shell(clock)
        for _ in range(20):
            await c._execute_breaker_safe_dispatch(dict(_CFG_OFF_DECISION), "peak")
        assert _anoms(c, "battery_write_churn") == []


# --- B3 -------------------------------------------------------------------


class TestB3MustStartByBlindWindow:
    def test_must_start_by_holds_behind_blind_window(self, clock):
        """I-R3 repro: EVSE in `_paused_by_blind_window` + `_paused_by_dp`
        at must-start-by → no turn_on, DP claim kept, blind-window claim
        kept, 1 NM + 1 anomaly naming `blind_window`."""
        sh = _MSBShell(clock)
        sh._ev._paused_by_blind_window.add("garage_a")
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert not _forced_on(sh)
        assert "garage_a" in sh._ev._paused_by_dp
        assert "garage_a" in sh._ev._paused_by_blind_window
        assert len(sh.nm) == 1 and "blind_window" in sh.nm[0]["message"]
        assert len(sh.anoms) == 1
        assert sh.anoms[0].type == "ev_must_start_by_held"
        assert sh.anoms[0].payload["extra"]["held"] == [["garage_a", "blind_window"]]

    def test_must_start_by_releases_when_blind_window_drained(self, clock):
        """Sighted-tick drain (membership gone) → the next fire releases."""
        sh = _MSBShell(clock)
        sh._ev._paused_by_blind_window.add("garage_a")
        sh._apply_dp_must_start_release(tou_period="off_peak")
        sh._ev._paused_by_blind_window.discard("garage_a")
        sh.nm.clear()
        sh.anoms.clear()
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert _forced_on(sh)
        assert sh.nm == [] and sh.anoms == []


# --- B4 -------------------------------------------------------------------


@pytest.mark.parametrize("tier,expect", [
    ("stream", "Battery strategy is using the local stream battery reading."),
    ("lkg", "Battery strategy is using the last good battery reading."),
    ("cloud_fallback", "Battery strategy is using the cloud battery reading only; "
                       "grid charging is withheld."),
    ("none", "Battery strategy is holding: no battery reading."),
    ("envoy", "Battery strategy is holding: no battery reading."),
])
def test_envoy_offline_nm_text_per_tier(clock, tier, expect):
    sent: list = []
    shell = SimpleNamespace(
        _battery=SimpleNamespace(_tick_soc_source=tier),
        _envoy_unavailable_count=2, _decision_interval=5,
        _envoy_degraded=True, _envoy_degraded_since="x",
        hass=SimpleNamespace(async_create_task=lambda c: None),
        _send_nm_alert=lambda **kw: sent.append(kw),
    )
    shell._envoy_offline_tier_text = (
        EnergyCoordinator._envoy_offline_tier_text.__get__(shell)
    )
    EnergyCoordinator._track_envoy_availability(shell, {"envoy_available": False})
    assert len(sent) == 1
    assert sent[0]["message"] == f"Envoy has been unavailable for 15 minutes. {expect}"


# --- B5 -------------------------------------------------------------------


class TestB5FreshCfgOff:
    def _shell(self, clock, age, *, ledger=None, lkg=False):
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, "off", lu=clock.t - timedelta(seconds=age or 0))
        if age is None:
            s._read_cloud_settings_max_age_s = lambda *a, **k: None
        s._last_charge_from_grid_command = ledger
        s._last_charge_from_grid_command_at = clock.t
        sh = _DispatchShell(s, hass, _evpool())
        sh._last_known_grid_charge_on = lkg
        return sh

    @pytest.mark.parametrize("age,expect", [(0, True), (300, True), (301, False),
                                            (None, False)])
    def test_provably_off_needs_fresh_read(self, clock, age, expect):
        assert self._shell(clock, age)._cfg_write_leg_provably_off() is expect

    @pytest.mark.parametrize("age,lkg,expect_block", [
        (0, True, False), (300, True, False), (301, True, True), (None, True, True),
        (301, False, False), (None, False, False),
    ])
    def test_start_block_stale_off_is_unknown(self, clock, age, lkg, expect_block):
        """Stale `off` → D2b unknown rule (LKG latch / ledger decides)."""
        assert self._shell(clock, age, lkg=lkg)._cfg_breaker_blocks_ev_start() is expect_block

    def test_stale_off_ledger_on_blocks(self, clock):
        sh = self._shell(clock, 301, ledger=True)
        assert sh._cfg_breaker_blocks_ev_start() is True

    @pytest.mark.parametrize("cap", [0, -5])
    def test_kill_switch_believes_any_off(self, clock, monkeypatch, cap):
        _setc(monkeypatch, "DEFAULT_CFG_OFF_READ_MAX_AGE_S", cap)
        sh = self._shell(clock, 10_000, lkg=True)
        assert sh._cfg_write_leg_provably_off() is True
        assert sh._cfg_breaker_blocks_ev_start() is False

    def test_local_leg_not_gated(self, clock):
        """No cloud oracle configured → write leg is local → no gate."""
        s, hass, _ = _strategy(clock, stream=False,
                               extra={"cloud_charge_from_grid_oracle": ""})
        eid = s._get_entity("charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY,
                            role="write")
        assert eid == _CFG_L
        _st(hass, _CFG_L, "off", lu=clock.t - timedelta(hours=5))
        s._read_cloud_settings_max_age_s = lambda *a, **k: None
        sh = _DispatchShell(s, hass, _evpool())
        assert sh._cfg_write_leg_provably_off() is True

    @pytest.mark.asyncio
    async def test_stale_off_holds_must_start_by(self, clock):
        """Wire-in via the REAL must-start-by release: stale cloud `off`
        + LKG latch on → held (`grid_charge_on`)."""
        sh = _MSBShell(clock, cfg_w="off")
        _st(sh.hass, _CFG_W, "off", lu=clock.t - timedelta(seconds=301))
        sh._last_known_grid_charge_on = True
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert not _forced_on(sh)
        assert sh.anoms[0].payload["extra"]["held"] == [["garage_a", "grid_charge_on"]]


# ===========================================================================
# Fix-up round (reviews A/B/C/D): Review B HIGH latch identity, D-HIGH-1
# EV-start gate, A M1/M2/M3, D-MED-1/3/4, Review C L1 (comment only).
# Oracles are hand-derived literals (TOU table: Oct 20:xx CDT = mid_peak,
# 21:xx-23:xx CDT = off_peak).
# ===========================================================================


# --- Review B HIGH — arbitrage latch TOU-period identity ---------------------


async def _latch_round_trip(clock, save_at, boot_at):
    s, hass, _ = _strategy(clock)
    kv = _KV()
    hass.data["universal_room_automation"] = {"database": kv}
    clock.set(save_at)
    s._arbitrage_chunk_completed = True
    await _persist_shell(hass, s)._save_evse_state()
    payload = json.loads(kv.rows["arbitrage_chunk_latch"])
    clock.set(boot_at)
    s2, hass2, _ = _strategy(clock)
    hass2.data["universal_room_automation"] = {"database": kv}
    await _persist_shell(hass2, s2)._restore_evse_state()
    return payload, s2


class TestReviewBLatchIdentity:
    @pytest.mark.asyncio
    async def test_latch_saved_mid_peak_dropped_on_off_peak_boot(self, clock):
        """Repro: chunk A completed, saved 20:50 CDT (mid_peak), restart
        lands 21:04 CDT (new off_peak chunk B) → latch NOT restored."""
        payload, s2 = await _latch_round_trip(
            clock,
            datetime(2026, 10, 4, 1, 50, tzinfo=_UTC),
            datetime(2026, 10, 4, 2, 4, tzinfo=_UTC),
        )
        assert payload["period"] == "mid_peak"
        assert s2._arbitrage_chunk_completed is False

    @pytest.mark.asyncio
    async def test_latch_saved_in_same_off_peak_restored(self, clock):
        """Saved 22:00 CDT (off_peak), boot 22:30 CDT same chunk → kept."""
        payload, s2 = await _latch_round_trip(
            clock,
            datetime(2026, 10, 4, 3, 0, tzinfo=_UTC),
            datetime(2026, 10, 4, 3, 30, tzinfo=_UTC),
        )
        assert payload["period"] == "off_peak"
        assert s2._arbitrage_chunk_completed is True

    @pytest.mark.asyncio
    async def test_latch_saved_mid_peak_boot_mid_peak_restored(self, clock):
        """Restart inside the same mid_peak (no off_peak entry) → kept."""
        _, s2 = await _latch_round_trip(
            clock,
            datetime(2026, 10, 4, 1, 10, tzinfo=_UTC),
            datetime(2026, 10, 4, 1, 50, tzinfo=_UTC),
        )
        assert s2._arbitrage_chunk_completed is True


# --- Review D D-HIGH-1 — one EV-start gate for DP + must-start-by ----------


class TestDHigh1EvStartGate:
    @pytest.mark.parametrize("hold,expect_on", [("grid_charge_on", False), (None, True)])
    def test_dp_reversion_honours_start_hold(self, clock, hold, expect_on):
        """`_apply_dp_reversion` under a hold: no turn_on, DP claim sticky."""
        sh = _MSBShell(clock)
        sh._apply_dp_reversion(tou_period="off_peak", ev_start_hold=hold)
        assert _forced_on(sh) is expect_on
        assert ("garage_a" in sh._ev._paused_by_dp) is (not expect_on)

    @pytest.mark.parametrize("dgc,cfg_w,ledger,expect", [
        (True, "off", None, "grid_charge_on"),   # same-tick decision CFG ON
        (False, "on", None, "grid_charge_on"),   # switch ON
        (False, "unavailable", True, "grid_charge_on"),  # D2b ledger
        (False, "off", None, None),
    ])
    def test_start_hold_label_matrix(self, clock, dgc, cfg_w, ledger, expect):
        sh = _MSBShell(clock, cfg_w=cfg_w, ledger=ledger)
        assert sh._ev_start_hold_label(decision_grid_charge=dgc) == expect

    @pytest.mark.parametrize("scope,expect", [
        ("arbitrage_release", None), ("all", "soc_untrusted"),
    ])
    def test_untrusted_scope_switch(self, clock, monkeypatch, scope, expect):
        """The open-ruling one-line switch: default scope = today."""
        _setc(monkeypatch, "EV_UNTRUSTED_SOC_START_REFUSAL_SCOPE", scope)
        sh = _MSBShell(clock)
        assert sh._ev_start_hold_label(soc_untrusted=True) == expect

    @pytest.mark.parametrize("scope,expect_on", [
        # "all": should-start-by is EXEMPT (operator ruling 2026-10-04 opt 1).
        ("arbitrage_release", True), ("all", True),
    ])
    def test_must_start_by_untrusted_scope(self, clock, monkeypatch, scope, expect_on):
        _setc(monkeypatch, "EV_UNTRUSTED_SOC_START_REFUSAL_SCOPE", scope)
        sh = _MSBShell(clock)
        sh.s._tick_soc_source = "cloud_fallback"
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert _forced_on(sh) is expect_on
        if not expect_on:
            assert sh.anoms[0].payload["extra"]["held"] == [["garage_a", "soc_untrusted"]]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("dgc,expect", [(True, "grid_charge_on"), (False, None)])
    async def test_decision_cycle_threads_start_hold_into_dp_tick(
        self, clock, mono, dgc, expect,
    ):
        """Enclosing-method anchor: the REAL `_decision_cycle_body` passes
        THIS tick's decision grid-charge intent to the DP tick (which runs
        before the breaker chokepoint dispatches the CFG turn_on)."""
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, "off", lu=clock.t)
        ev = _evpool()
        ev.hass = hass
        c = _cycle_shell(clock, s, hass, ev)
        seen: list = []
        c._dp_decision_tick = lambda *a, **k: seen.append(k.get("ev_start_hold", "MISSING"))
        _real = s.determine_mode

        def _dm(*a, **k):
            d = _real(*a, **k)
            d["charge_from_grid"] = dgc
            return d
        s.determine_mode = _dm
        await c._decision_cycle_body()
        assert seen == [expect]


# --- Review A M1 — CFG ledger stamped on EVERY turn_on dispatch path --------


_CFG_ON_DECISION = {
    "actions": [{"service": "switch.turn_on", "target": _CFG_W, "data": {}}],
    "arbitrage_phase": "n/a", "charge_from_grid": True,
}


class TestM1LedgerEveryTurnOn:
    @pytest.mark.asyncio
    async def test_resent_turn_on_after_fresh_off_read_rearms_ledger(self, clock):
        """Ledger True since T0; cloud reads a fresh `off` at T1; URA re-sends
        turn_on at T1 (ledger value unchanged → `_at` unchanged) → the
        D2b ledger must read ON."""
        c, s = _write_shell(clock, cfg_state="off")
        s._last_charge_from_grid_command = True
        s._last_charge_from_grid_command_at = clock.t
        c._last_cfg_on_dispatch_at = None
        clock.adv(minutes=5)
        _st(c.hass, _CFG_W, "off", lu=clock.t)
        await c._execute_breaker_safe_dispatch(dict(_CFG_ON_DECISION), "off_peak")
        assert c._last_cfg_off_read_at == clock.t
        assert c._cfg_ledger_says_on() is True

    @pytest.mark.asyncio
    async def test_manager_evaluate_path_stamps_ledger(self, clock):
        """`_evaluate_battery` (CoordinatorManager path) stamps the ledger."""
        c, s = _write_shell(clock, cfg_state="off")
        c._last_cfg_on_dispatch_at = None
        c._tou = SimpleNamespace(get_current_period=lambda *a: "off_peak",
                                 get_season=lambda *a: "shoulder")
        c._is_any_evse_charging = lambda: False
        c._evse_battery_hold_active = False
        c._evse_hold_soc = None
        s.determine_mode = lambda *a, **k: {
            "actions": [{"service": "switch.turn_on", "target": _CFG_W, "data": {}}],
            "reason": "x", "charge_from_grid": True,
        }
        acts = await c._evaluate_battery()
        assert len(acts) == 1
        assert s._last_charge_from_grid_command is True
        assert s._last_charge_from_grid_command_at == clock.t
        assert c._last_cfg_on_dispatch_at == clock.t


# --- Review A M2 / D-MED-1 — off-read stamp only when fresh -----------------


class TestM2OffStampFresh:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("age,expect_stamped,expect_block", [
        (300, True, False), (301, False, True),
    ])
    async def test_stale_off_does_not_clear_ledger(
        self, clock, age, expect_stamped, expect_block,
    ):
        c, s = _write_shell(clock, cfg_state="off")
        s._last_charge_from_grid_command = True
        s._last_charge_from_grid_command_at = clock.t - timedelta(hours=1)
        c._last_cfg_on_dispatch_at = None
        _st(c.hass, _CFG_W, "off", lu=clock.t - timedelta(seconds=age))
        await c._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert (c._last_cfg_off_read_at is not None) is expect_stamped
        assert c._cfg_breaker_blocks_ev_start() is expect_block


# --- Review A M3 — cloud freshness from enphase_ev last-success stamp --------


_LS = "sensor.enphase_cloud_last_successful_update"


class TestM3LastSuccess:
    @pytest.mark.parametrize("ls_age,settings_age,expect", [
        (10, 1000, True),     # integration fresh; settings old → fresh
        (299, 0, True),
        (300, 0, True),
        (301, 0, False),      # integration stale; settings fresh → stale
        ("unavailable", 0, False),
    ])
    def test_last_success_drives_freshness(self, clock, ls_age, settings_age, expect):
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, "off", lu=clock.t - timedelta(seconds=settings_age))
        if ls_age == "unavailable":
            _st(hass, _LS, "unavailable")
        else:
            _st(hass, _LS, (clock.t - timedelta(seconds=ls_age)).isoformat())
        sh = _DispatchShell(s, hass, _evpool())
        assert sh._cfg_write_leg_provably_off() is expect

    def test_absent_entity_falls_back_to_settings_age(self, clock):
        s, hass, _ = _strategy(clock, stream=False)
        _st(hass, _CFG_W, "off", lu=clock.t - timedelta(seconds=301))
        assert _LS not in hass._states
        sh = _DispatchShell(s, hass, _evpool())
        assert sh._cfg_write_leg_provably_off() is False


# --- D-MED-4 — fresh off clears a stuck ledger; stale ledger not restored ----


class TestDMed4:
    @pytest.mark.asyncio
    async def test_fresh_off_read_clears_stuck_true_ledger(self, clock):
        """Ledger True (T0); a fresh `off` read at T1 in the chokepoint →
        provably off (was: any True ledger → never)."""
        c, s = _write_shell(clock, cfg_state="off")
        s._last_charge_from_grid_command = True
        s._last_charge_from_grid_command_at = clock.t
        c._last_cfg_on_dispatch_at = None
        assert c._cfg_write_leg_provably_off() is False
        clock.adv(minutes=5)
        _st(c.hass, _CFG_W, "off", lu=clock.t)
        await c._execute_breaker_safe_dispatch(dict(_NEUTRAL), "off_peak")
        assert c._cfg_write_leg_provably_off() is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd,age_s,expect", [
        (True, 43199, True), (True, 43200, True), (True, 43201, None),
        (False, 50000, False),
    ])
    async def test_cfg_ledger_restore_age_gate(self, clock, cmd, age_s, expect):
        s, hass, _ = _strategy(clock)
        kv = _KV()
        kv.rows["wv_commanded_ledger"] = json.dumps({"charge_from_grid": {
            "commanded": cmd,
            "commanded_at": (clock.t - timedelta(seconds=age_s)).isoformat(),
        }})
        sh = _persist_shell(hass, s)
        await sh._restore_wv_state(kv, s, None, 10.0)
        assert s._last_charge_from_grid_command is expect


# --- D-MED-3 — force_redispatch failure recorded ----------------------------


@pytest.mark.asyncio
async def test_force_redispatch_failure_records_dispatch_failed(clock):
    from homeassistant.exceptions import HomeAssistantError
    c, s = _write_shell(clock, raise_on=("number", "set_value"),
                        exc=HomeAssistantError("cloud down"))
    s._desired_stamped_at = clock.t
    s._last_reserve_level_desired = 40
    s._write_verifier._effective_reserve_desired = lambda b: 40
    await s.force_redispatch("reserve_soc")
    assert c._write_verifier._records["reserve_soc"].status == "dispatch_failed"
    a = _anoms(c, "battery_write_failed")
    assert len(a) == 1 and a[0].payload["extra"]["exception"] == "HomeAssistantError"


@pytest.mark.asyncio
async def test_latch_legacy_payload_without_period_keeps_old_rule(clock):
    """Legacy row (no `period`) → today's boundary-identity rule only:
    a valid boundary at an off_peak boot is still restored."""
    clock.set(datetime(2026, 10, 4, 2, 4, tzinfo=_UTC))
    s, hass, _ = _strategy(clock)
    bnd, _, _ = s._attain_target_boundary(clock.t.astimezone(_CDT), "off_peak")
    kv = _KV()
    kv.rows["arbitrage_chunk_latch"] = json.dumps(
        {"completed": True, "boundary_iso": bnd.isoformat()})
    hass.data["universal_room_automation"] = {"database": kv}
    await _persist_shell(hass, s)._restore_evse_state()
    assert s._arbitrage_chunk_completed is True


# ===========================================================================
# Review-D M1 — L1 smart-plug tier cedes on the L2 grid-charge signal
# ===========================================================================


def _plug_ctrl(on=False):
    from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
        SmartPlugController,
    )
    hass = MockHass()
    hass.set_state("switch.socket_1", "on" if on else "off")
    return SmartPlugController(hass=hass, plug_entities=["switch.socket_1"])


def _plug_turn_ons(actions):
    return [a for a in actions if a.get("service") == "switch.turn_on"
            and a.get("target") == "switch.socket_1"]


class TestM1PlugCedesOnGridCharge:
    @pytest.mark.parametrize("gc,expect_on", [(False, 1), (True, 0)])
    def test_plug_release_all_tou_defers_on_grid_charge(self, gc, expect_on):
        p = _plug_ctrl()
        p._paused_by_us.add("switch.socket_1")
        acts = p.release_all_tou(grid_charge_on=gc)
        assert len(_plug_turn_ons(acts)) == expect_on
        assert ("switch.socket_1" in p._paused_by_us) is gc

    @pytest.mark.parametrize("gc,expect_on", [(False, 1), (True, 0)])
    def test_plug_release_all_fill_priority_defers_on_grid_charge(self, gc, expect_on):
        p = _plug_ctrl()
        p._paused_by_fill_priority.add("switch.socket_1")
        acts = p.release_all_fill_priority(grid_charge_on=gc)
        assert len(_plug_turn_ons(acts)) == expect_on
        assert ("switch.socket_1" in p._paused_by_fill_priority) is gc

    @pytest.mark.parametrize("gc,expect_on", [(False, 1), (True, 0)])
    def test_plug_drain_resume_held_on_grid_charge(self, gc, expect_on):
        p = _plug_ctrl()
        p._paused_by_battery_drain.add("switch.socket_1")
        acts = p.determine_battery_drain_actions(
            battery_power_w=0.0, battery_soc=90, soc_threshold=20,
            reserve_soc=10, solar_replenishing=True, is_offpeak=False,
            grid_charge_on=gc,
        )
        assert len(_plug_turn_ons(acts)) == expect_on
        assert ("switch.socket_1" in p._paused_by_battery_drain) is gc

    @pytest.mark.parametrize("gc,expect_on", [(False, 1), (True, 0)])
    def test_plug_fill_priority_resume_held_on_grid_charge(self, gc, expect_on):
        p = _plug_ctrl()
        p._paused_by_fill_priority.add("switch.socket_1")
        acts = p.determine_fill_priority_actions(
            soc=90, remaining_forecast_kwh=50.0, tou_period="mid_peak",
            soc_threshold=50, excess_solar_kwh_threshold=10.0,
            peak_ahead=True, is_daylight=True, grid_charge_on=gc,
        )
        assert len(_plug_turn_ons(acts)) == expect_on
        assert ("switch.socket_1" in p._paused_by_fill_priority) is gc


class _PlugSpy:
    """Records the grid_charge_on kwarg each plug entry point receives."""

    def __init__(self) -> None:
        self.seen: dict[str, object] = {}

    def _rec(self, name, kw):
        self.seen[name] = kw.get("grid_charge_on", "MISSING")
        return []

    def determine_actions(self, *a, **kw):
        return self._rec("determine_actions", kw)

    def release_all_tou(self, *a, **kw):
        return self._rec("release_all_tou", kw)

    def determine_battery_drain_actions(self, *a, **kw):
        return self._rec("drain", kw)

    def determine_fill_priority_actions(self, *a, **kw):
        return self._rec("fill_priority", kw)

    def release_all_fill_priority(self, *a, **kw):
        return self._rec("release_all_fill_priority", kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg_on", [True, False])
@pytest.mark.parametrize("toggles", [False, True])
async def test_decision_cycle_threads_grid_charge_into_plug_paths(
    clock, mono, cfg_on, toggles,
):
    """Wire-in anchor (enclosing method `_decision_cycle_body`): every plug
    turn-on path receives grid_charge_on == the tick's grid_charge_intent.
    toggles=False drives the two release_all_* paths; True the drain +
    fill-priority + TOU paths."""
    s, hass, _ = _strategy(clock, stream=False)
    _st(hass, _CFG_W, "on" if cfg_on else "off", lu=clock.t)
    ev = _evpool()
    ev.hass = hass
    c = _cycle_shell(clock, s, hass, ev)
    spy = _PlugSpy()
    c._smart_plugs = spy
    c._ev_tou_enabled = toggles
    c._excess_solar_enabled = toggles
    c._excess_solar_kwh = 10.0
    c._grid_import_cap_enabled = False
    c._grid_import_cap_kw = 12.0
    c._dp_carrier = None
    c._dp_must_start_by_min = None
    c._last_soc_recovered = False

    async def _anoop(*a, **k):
        return None
    c._check_fill_priority_nm_trip = _anoop
    c._post_excess_solar_bookkeeping = lambda *a, **k: None
    c._send_nm_alert = _anoop
    await c._decision_cycle_body()
    if toggles:
        names = ("determine_actions", "drain", "fill_priority")
    else:
        names = ("release_all_tou", "drain", "release_all_fill_priority")
    for n in names:
        assert spy.seen.get(n) is cfg_on, (n, spy.seen)


# ===========================================================================
# Review-D L2 — CFG ledger restore age-gates on the newer dispatch stamp
# ===========================================================================


@pytest.mark.asyncio
async def test_cfg_ledger_on_13h_with_recent_redispatch_restored(clock):
    """CFG continuously ON 13h (ledger `_at` 13h old) but re-dispatched 60s
    ago: persisted through the REAL save → restore, the ledger survives."""
    s, hass, _ = _strategy(clock)
    kv = _KV()
    hass.data["universal_room_automation"] = {"database": kv}
    s._last_charge_from_grid_command = True
    s._last_charge_from_grid_command_at = clock.t - timedelta(hours=13)
    sh = _persist_shell(hass, s)
    sh._last_cfg_on_dispatch_at = clock.t - timedelta(seconds=60)
    await sh._save_evse_state()
    s2, hass2, _ = _strategy(clock)
    hass2.data["universal_room_automation"] = {"database": kv}
    sh2 = _persist_shell(hass2, s2)
    sh2._last_cfg_on_dispatch_at = None
    await sh2._restore_evse_state()
    assert s2._last_charge_from_grid_command is True
    assert sh2._last_cfg_on_dispatch_at == clock.t - timedelta(seconds=60)


@pytest.mark.asyncio
@pytest.mark.parametrize("disp_age_h,expect", [(None, None), (13, None), (1, True)])
async def test_cfg_ledger_restore_uses_newer_stamp(clock, disp_age_h, expect):
    s, hass, _ = _strategy(clock)
    kv = _KV()
    row = {"commanded": True,
           "commanded_at": (clock.t - timedelta(hours=13)).isoformat()}
    if disp_age_h is not None:
        row["last_on_dispatch_at"] = (
            clock.t - timedelta(hours=disp_age_h)).isoformat()
    kv.rows["wv_commanded_ledger"] = json.dumps({"charge_from_grid": row})
    sh = _persist_shell(hass, s)
    await sh._restore_wv_state(kv, s, None, 10.0)
    assert s._last_charge_from_grid_command is expect
