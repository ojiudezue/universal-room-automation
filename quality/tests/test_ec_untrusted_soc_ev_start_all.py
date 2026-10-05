"""EC degraded-data p1 — operator ruling 2026-10-04: NO EV start (L2 EVSE or
L1 plug) on ANY turn-on path while the tick's battery-SOC verdict is
untrusted (``EV_UNTRUSTED_SOC_START_REFUSAL_SCOPE == "all"``).

Falsifiable invariant: with the tick verdict stamped untrusted, no
``switch.turn_on`` for a configured EVSE switch or plug is emitted by any
energy_pool / coordinator EV path; the refusing path keeps its pause claim
(sticky) except load-shed restore (claim already dropped). Trusted verdict
→ byte-identical to before (each test's trusted leg is the discriminator).

Every test drives REAL production methods; the trusted leg of each
parametrization proves the path WOULD start, so the untrusted leg's 0 is
the gate, not a dead fixture.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy import (  # noqa: E402
    EnergyCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
    SmartPlugController,
)

from test_ec_degraded_data_p1 import (  # noqa: E402
    _CFG_W, _cycle_shell, _native_stale, _cloud, _setc, _st, _strategy,
    clock, mono,  # noqa: F401 — fixtures
)

_SW = "switch.garage_a"
_PLUG = "switch.socket_1"


def _ev(on=False, untrusted=None):
    hass = MockHass()
    hass.set_state(_SW, "on" if on else "off")
    hass.set_state("sensor.garage_a_power", "0", attributes={"unit_of_measurement": "W"})
    ev = EVChargerController(hass, evse_config={"garage_a": {
        "switch": _SW, "power": "sensor.garage_a_power",
    }})
    if untrusted is not None:
        ev._ev_start_soc_untrusted = untrusted
    return ev


def _plug(on=False, untrusted=None):
    hass = MockHass()
    hass.set_state(_PLUG, "on" if on else "off")
    p = SmartPlugController(hass=hass, plug_entities=[_PLUG])
    if untrusted is not None:
        p._ev_start_soc_untrusted = untrusted
    return p


def _ons(actions, target):
    return [a for a in actions if a.get("service") == "switch.turn_on"
            and a.get("target") == target]


def test_shipped_scope_is_all():
    """The ruled value is what ships (no monkeypatch anywhere in this file
    sets it to "all" — every refusal test below depends on the shipped
    value)."""
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const,
    )
    assert energy_const.EV_UNTRUSTED_SOC_START_REFUSAL_SCOPE == "all"


# --- L2 EVSE paths ----------------------------------------------------------


class TestL2Paths:
    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 1)])
    def test_ensure_on_offpeak(self, untrusted, n):
        """EXEMPT (ruling 2026-10-04 opt 1): off-peak ensure-on starts
        under an untrusted SOC."""
        ev = _ev(untrusted=untrusted)
        ev._paused_by_us.add("garage_a")  # TOU-pause end → off-peak ensure-on
        acts = ev.determine_actions("off_peak")
        assert len(_ons(acts, _SW)) == n

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_excess_solar_start(self, untrusted, n):
        ev = _ev(untrusted=untrusted)
        ev._paused_by_us.add("garage_a")
        acts = ev.determine_excess_solar_actions(
            99.0, 50.0, "mid_peak", soc_threshold=95, kwh_threshold=5.0,
        )
        assert len(_ons(acts, _SW)) == n
        # Refused: no claim taken, TOU membership untouched.
        assert ("garage_a" in ev._excess_solar_active) is (not untrusted)
        assert ("garage_a" in ev._paused_by_us) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_grid_cap_release(self, untrusted, n):
        ev = _ev(untrusted=untrusted)
        ev._paused_by_grid_cap.add("garage_a")
        acts = ev.determine_grid_cap_actions(
            net_power_kw=1.0, grid_cap_kw=12.0, hysteresis_kw=1.0,
        )
        assert len(_ons(acts, _SW)) == n
        assert ("garage_a" in ev._paused_by_grid_cap) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_drain_release(self, untrusted, n):
        ev = _ev(untrusted=untrusted)
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(
            battery_power_w=0.0, battery_soc=90, soc_threshold=20,
            reserve_soc=10, solar_replenishing=True, is_offpeak=False,
        )
        assert len(_ons(acts, _SW)) == n
        assert ("garage_a" in ev._paused_by_battery_drain) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_fill_priority_release(self, untrusted, n):
        ev = _ev(untrusted=untrusted)
        ev._paused_by_fill_priority.add("garage_a")
        acts = ev.determine_fill_priority_actions(
            soc=90, remaining_forecast_kwh=50.0, tou_period="mid_peak",
            soc_threshold=50, excess_solar_kwh_threshold=10.0,
            peak_ahead=True, is_daylight=True,
        )
        assert len(_ons(acts, _SW)) == n
        assert ("garage_a" in ev._paused_by_fill_priority) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_release_all_tou(self, untrusted, n):
        ev = _ev(untrusted=untrusted)
        ev._paused_by_us.add("garage_a")
        acts = ev.release_all_tou()
        assert len(_ons(acts, _SW)) == n
        assert ("garage_a" in ev._paused_by_us) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_release_all_fill_priority(self, untrusted, n):
        ev = _ev(untrusted=untrusted)
        ev._paused_by_fill_priority.add("garage_a")
        acts = ev.release_all_fill_priority()
        assert len(_ons(acts, _SW)) == n
        assert ("garage_a" in ev._paused_by_fill_priority) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_release_all_grid_cap(self, untrusted, n):
        ev = _ev(untrusted=untrusted)
        ev._paused_by_grid_cap.add("garage_a")
        acts = ev.release_all_grid_cap()
        assert len(_ons(acts, _SW)) == n
        assert ("garage_a" in ev._paused_by_grid_cap) is untrusted


# --- L1 plug paths ----------------------------------------------------------


class TestL1PlugPaths:
    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 1)])
    def test_plug_ensure_on_offpeak(self, untrusted, n):
        """EXEMPT (ruling 2026-10-04 opt 1)."""
        p = _plug(untrusted=untrusted)
        p._paused_by_us.add(_PLUG)
        acts = p.determine_actions("off_peak")
        assert len(_ons(acts, _PLUG)) == n

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_plug_drain_release(self, untrusted, n):
        p = _plug(untrusted=untrusted)
        p._paused_by_battery_drain.add(_PLUG)
        acts = p.determine_battery_drain_actions(
            battery_power_w=0.0, battery_soc=90, soc_threshold=20,
            reserve_soc=10, solar_replenishing=True, is_offpeak=False,
        )
        assert len(_ons(acts, _PLUG)) == n
        assert (_PLUG in p._paused_by_battery_drain) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_plug_fill_priority_release(self, untrusted, n):
        p = _plug(untrusted=untrusted)
        p._paused_by_fill_priority.add(_PLUG)
        acts = p.determine_fill_priority_actions(
            soc=90, remaining_forecast_kwh=50.0, tou_period="mid_peak",
            soc_threshold=50, excess_solar_kwh_threshold=10.0,
            peak_ahead=True, is_daylight=True,
        )
        assert len(_ons(acts, _PLUG)) == n
        assert (_PLUG in p._paused_by_fill_priority) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_plug_release_all_tou(self, untrusted, n):
        p = _plug(untrusted=untrusted)
        p._paused_by_us.add(_PLUG)
        acts = p.release_all_tou()
        assert len(_ons(acts, _PLUG)) == n
        assert (_PLUG in p._paused_by_us) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_plug_release_all_fill_priority(self, untrusted, n):
        p = _plug(untrusted=untrusted)
        p._paused_by_fill_priority.add(_PLUG)
        acts = p.release_all_fill_priority()
        assert len(_ons(acts, _PLUG)) == n
        assert (_PLUG in p._paused_by_fill_priority) is untrusted


# --- Load-shed restore (coordinator, real `_execute_shed_action`) ----------


class _ShedShell:
    def __init__(self, untrusted):
        self.hass = MockHass()
        self.hass.set_state(_SW, "off")
        self.hass.set_state("sensor.garage_a_power", "0",
                            attributes={"unit_of_measurement": "W"})
        self.hass.set_state(_PLUG, "off")
        self._ev = EVChargerController(self.hass, evse_config={"garage_a": {
            "switch": _SW, "power": "sensor.garage_a_power"}})
        self._ev.hass = self.hass
        self._smart_plugs = SmartPlugController(hass=self.hass, plug_entities=[_PLUG])
        self._ev._ev_start_soc_untrusted = untrusted
        self._smart_plugs._ev_start_soc_untrusted = untrusted
        self._ev._paused_by_load_shed.add("garage_a")
        self._ev._load_shed_was_on_at_shed["garage_a"] = True
        self._smart_plugs._paused_by_load_shed.add(_PLUG)
        self._smart_plugs._load_shed_was_on_at_shed[_PLUG] = True
        self._last_release_reason = None
        self.dispatched: list = []
        loop = asyncio.new_event_loop()
        self.hass.async_create_task = lambda c: loop.run_until_complete(c)

    async def _execute_service_action(self, spec):
        self.dispatched.append(spec)


_ShedShell._execute_shed_action = EnergyCoordinator._execute_shed_action


class TestLoadShedRestore:
    @pytest.mark.parametrize("target,eid", [("ev", _SW), ("smart_plugs", _PLUG)])
    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_load_shed_release(self, target, eid, untrusted, n):
        sh = _ShedShell(untrusted)
        sh._execute_shed_action(target, activate=False)
        assert len(_ons(sh.dispatched, eid)) == n


# --- Edge-logged refusal (rate-limited) -------------------------------------


def test_refusal_edge_logged_once_per_episode(monkeypatch):
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_pool as ep,
    )
    rows: list = []
    monkeypatch.setitem(
        EVChargerController.release_all_tou.__globals__, "_pool_activity_log",
        lambda hass, action, desc, eid: rows.append((action, desc, eid)),
    )
    ev = _ev(untrusted=True)
    for _ in range(3):
        ev._paused_by_us.add("garage_a")
        ev.release_all_tou()
    assert rows == [("ev_start_refused_soc_untrusted",
                     "kind=ev path=release_all_tou", "garage_a")]
    ev._ev_start_soc_untrusted = False
    ev.release_all_tou()  # trusted → episode closes
    ev._ev_start_soc_untrusted = True
    ev._paused_by_us.add("garage_a")
    ev.release_all_tou()
    assert len(rows) == 2
    assert ep  # module import used


# --- Scope kill switch + legacy stub ---------------------------------------


def test_scope_arbitrage_release_restores_start(monkeypatch):
    _setc(monkeypatch, "EV_UNTRUSTED_SOC_START_REFUSAL_SCOPE", "arbitrage_release")
    ev = _ev(untrusted=True)
    ev._paused_by_us.add("garage_a")
    assert len(_ons(ev.release_all_tou(), _SW)) == 1


@pytest.mark.parametrize("stamp", [None, 1, "true"])
def test_non_bool_stamp_reads_trusted(stamp):
    ev = _ev()
    if stamp is not None:
        ev._ev_start_soc_untrusted = stamp
    ev._paused_by_us.add("garage_a")
    assert len(_ons(ev.release_all_tou(), _SW)) == 1


# --- Wire-in: the REAL decision cycle stamps the captured verdict ----------


@pytest.mark.asyncio
@pytest.mark.parametrize("untrusted", [True, False])
async def test_decision_cycle_stamps_captured_verdict(clock, mono, untrusted):
    """Enclosing-method anchor for `_stamp_ev_start_soc_verdict`: the REAL
    `_decision_cycle_body` stamps both tiers with THIS tick's verdict, taken
    before the first await (the first await flips the battery tier — the
    stamp must not follow it), and the REAL L1 release path consumes it."""
    s, hass, _ = _strategy(clock, stream=False)
    if untrusted:
        _native_stale(hass, clock)
        _cloud(hass, clock, "50")
    _st(hass, _CFG_W, "off", lu=clock.t)
    ev = _ev()
    ev.hass = hass
    hass.set_state(_SW, "off")
    hass.set_state("sensor.garage_a_power", "0", attributes={"unit_of_measurement": "W"})
    hass.set_state(_PLUG, "off")
    c = _cycle_shell(clock, s, hass, ev)
    plugs = SmartPlugController(hass=hass, plug_entities=[_PLUG])
    plugs._paused_by_us.add(_PLUG)
    c._smart_plugs = plugs
    c._ev_tou_enabled = False          # → plug release_all_tou path
    c._excess_solar_enabled = False
    c._grid_import_cap_enabled = False
    c._grid_import_cap_kw = 12.0
    c._dp_carrier = None
    c._dp_must_start_by_min = None
    c._last_soc_recovered = False

    flip_to = "envoy" if untrusted else "cloud_fallback"

    async def _acct(decision, period, season):
        s._tick_soc_source = flip_to  # first await flips the tier
    c._account_arbitrage_cycle = _acct

    async def _anoop(*a, **k):
        return None
    c._check_fill_priority_nm_trip = _anoop
    c._post_excess_solar_bookkeeping = lambda *a, **k: None
    c._send_nm_alert = _anoop
    await c._decision_cycle_body()
    assert s._tick_soc_source == flip_to
    assert ev._ev_start_soc_untrusted is untrusted
    assert plugs._ev_start_soc_untrusted is untrusted
    on = [d for d in c.dispatched if d.get("service") == "switch.turn_on"
          and d.get("target") == _PLUG]
    assert len(on) == (0 if untrusted else 1)


# --- Operator ruling 2026-10-04 option 1: exempt paths ----------------------
#
# Off-peak ensure-on (L2 + L1) and should-start-by deadline starts proceed
# under an untrusted SOC; every other gate on them still holds; every
# non-exempt path still refuses (TestL2Paths / TestL1PlugPaths / load-shed).

from datetime import datetime, timezone  # noqa: E402

from test_ec_degraded_data_p1 import _MSBShell, _forced_on  # noqa: E402

# 03:30 with onset 04:00 → inside the hold window (onset refuses);
# must-start-by 03:00 → deadline reached. Literals, not imported consts.
_NOW_0330 = datetime(2026, 10, 4, 3, 30, tzinfo=timezone.utc)
_MSB_0300 = 180


def test_exempt_path_set_pinned():
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_const,
    )
    assert energy_const.EV_UNTRUSTED_SOC_EXEMPT_PATHS == frozenset(
        {"offpeak_ensure_on", "should_start_by"}
    )


def _onset(ctl):
    ctl._ev_charge_onset_enabled = True
    ctl._ev_charge_onset_time = "04:00"


def _drain_kw(**extra):
    # SOC 11 at reserve 10 → battery_out_of_capacity; threshold 20 → no
    # daytime soc_recovered (needs >= 25).
    kw = dict(battery_power_w=0.0, battery_soc=11, soc_threshold=20,
              reserve_soc=10, is_offpeak=True)
    kw.update(extra)
    return kw


class TestExemptOffpeakEnsureOn:
    def test_ev_ensure_on_held_by_cfg_under_untrusted(self):
        ev = _ev(untrusted=True)
        ev._paused_by_us.add("garage_a")
        acts = ev.determine_actions("off_peak", grid_charge_on=True)
        assert _ons(acts, _SW) == []
        assert ev._arbitrage_pause_reason.get("garage_a") == "breaker"

    def test_plug_ensure_on_held_by_cfg_under_untrusted(self):
        p = _plug(untrusted=True)
        p._paused_by_us.add(_PLUG)
        acts = p.determine_actions("off_peak", grid_charge_on=True)
        assert _ons(acts, _PLUG) == []

    def test_exempt_allow_logged_once_per_episode(self, monkeypatch):
        rows: list = []
        monkeypatch.setitem(
            EVChargerController.determine_actions.__globals__,
            "_pool_activity_log",
            lambda hass, action, desc, eid: rows.append((action, desc, eid))
            if action.startswith("ev_start_") else None,
        )
        ev = _ev(untrusted=True)
        for _ in range(3):
            ev.hass.set_state(_SW, "off")
            ev.determine_actions("off_peak")
        assert rows == [("ev_start_allowed_soc_untrusted_exempt",
                         "kind=ev path=offpeak_ensure_on", "garage_a")]
        ev._ev_start_soc_untrusted = False
        ev.determine_actions("off_peak")  # trusted → episode closes
        ev._ev_start_soc_untrusted = True
        ev.determine_actions("off_peak")
        assert len(rows) == 2


class TestExemptShouldStartBy:
    @pytest.mark.parametrize("untrusted", [False, True])
    def test_ev_drain_must_start_by_reached_starts(self, untrusted):
        ev = _ev(untrusted=untrusted)
        _onset(ev)
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(**_drain_kw(
            now_local=_NOW_0330, must_start_by_min=_MSB_0300,
        ))
        assert len(_ons(acts, _SW)) == 1

    def test_ev_drain_dp_forcing_starts_untrusted(self):
        ev = _ev(untrusted=True)
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(**_drain_kw(dp_forcing=True))
        assert len(_ons(acts, _SW)) == 1

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_ev_drain_onset_permits_overnight_still_refused(self, untrusted, n):
        """Overnight release NOT driven by the deadline (onset off → permits)
        is a plain drain release → still refused under untrusted SOC."""
        ev = _ev(untrusted=untrusted)
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(**_drain_kw())
        assert len(_ons(acts, _SW)) == n
        assert ("garage_a" in ev._paused_by_battery_drain) is untrusted

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_ev_drain_daytime_with_dp_forcing_still_refused(self, untrusted, n):
        """Daytime (soc_recovered) release is not a deadline start even with
        DP forcing set (overnight leg not firing) → still refused."""
        ev = _ev(untrusted=untrusted)
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(**_drain_kw(
            battery_soc=90, dp_forcing=True, is_offpeak=False,
            solar_replenishing=True,
        ))
        assert len(_ons(acts, _SW)) == n

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_plug_drain_daytime_with_dp_forcing_still_refused(self, untrusted, n):
        p = _plug(untrusted=untrusted)
        p._paused_by_battery_drain.add(_PLUG)
        acts = p.determine_battery_drain_actions(**_drain_kw(
            battery_soc=90, dp_forcing=True, is_offpeak=False,
            solar_replenishing=True,
        ))
        assert len(_ons(acts, _PLUG)) == n

    @pytest.mark.parametrize("untrusted", [False, True])
    def test_plug_drain_must_start_by_reached_starts(self, untrusted):
        p = _plug(untrusted=untrusted)
        _onset(p)
        p._paused_by_battery_drain.add(_PLUG)
        acts = p.determine_battery_drain_actions(**_drain_kw(
            now_local=_NOW_0330, must_start_by_min=_MSB_0300,
        ))
        assert len(_ons(acts, _PLUG)) == 1

    def test_plug_drain_must_start_by_held_by_cfg_under_untrusted(self):
        p = _plug(untrusted=True)
        _onset(p)
        p._paused_by_battery_drain.add(_PLUG)
        acts = p.determine_battery_drain_actions(**_drain_kw(
            now_local=_NOW_0330, must_start_by_min=_MSB_0300,
            grid_charge_on=True,
        ))
        assert _ons(acts, _PLUG) == []
        assert _PLUG in p._paused_by_battery_drain

    @pytest.mark.parametrize("untrusted,n", [(False, 1), (True, 0)])
    def test_plug_drain_onset_permits_overnight_still_refused(self, untrusted, n):
        p = _plug(untrusted=untrusted)
        p._paused_by_battery_drain.add(_PLUG)
        acts = p.determine_battery_drain_actions(**_drain_kw())
        assert len(_ons(acts, _PLUG)) == n

    def test_must_start_release_starts_untrusted(self, clock):
        sh = _MSBShell(clock)
        sh.s._tick_soc_source = "cloud_fallback"
        assert sh._soc_untrusted_from_battery() is True
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert _forced_on(sh)

    def test_must_start_release_held_by_cfg_under_untrusted(self, clock):
        sh = _MSBShell(clock, cfg_w="on")
        sh.s._tick_soc_source = "cloud_fallback"
        sh._apply_dp_must_start_release(tou_period="off_peak")
        assert not _forced_on(sh)
        assert "garage_a" in sh._ev._paused_by_dp

    def test_dp_reversion_still_refused_untrusted(self, clock):
        """Non-exempt sibling: DP reversion under the tick's untrusted label."""
        sh = _MSBShell(clock)
        sh.s._tick_soc_source = "cloud_fallback"
        hold = sh._ev_start_hold_label(soc_untrusted=sh._soc_untrusted_from_battery())
        assert hold == "soc_untrusted"
        sh._apply_dp_reversion(tou_period="off_peak", ev_start_hold=hold)
        assert not _forced_on(sh)
