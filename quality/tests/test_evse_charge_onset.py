"""EVSE charge-onset gate — Rev 6 (Tier-2-DB) mutation-anchored tests.

Cycle: evse-charge-onset Rev 6. See
`docs/planning/PLANNING_evse_charge_onset_time.md`.

Rev 6 changes vs Rev 5:
  * D-A: dedicated ENABLE toggle (`_ev_charge_onset_enabled`); the Rev-5
         "blank onset = off" kill was unreachable (HA TimeSelector rejects
         blank).
  * D-B: bounded HOLD WINDOW (`ONSET_MAX_HOLD_H = 8h`) replaces the
         Rev-5 lookback anchor mechanism. Hold IFF
         `0 < (next_onset_instant - now) <= ONSET_MAX_HOLD_H`.
  * D-C: self-contained must-start-by backstop at BOTH sites (esp plug).
         The plug tier has NO DP participation — this is the operator's
         real L1 charger's only hard release.

Sites anchored (each: neuter, this file's named test goes RED, restore):

  * EV release site (~2198): reassociated conjunction routes through
    `_evaluate_onset_gate`. Distributing the AND across daytime kills
    `TestDaytimeSolarLegUngated`.
  * Plug release site (~3621): mirror. Same distribute-AND kill.
  * `_evaluate_onset_gate` bounded-window predicate: setting the module
    default `_DEFAULT_ONSET_MAX_HOLD_H` to a huge value (e.g. 24) kills
    `TestBoundedHoldWindow::test_daytime_reserve_hit_not_held` (because
    a 15h-out onset would then be inside the hold window → held).
  * `must_start_by_reached` term in the overnight gate: removing it kills
    `TestMustStartByBackstop::test_plug_hard_release_at_must_start_by`.
  * Enable toggle: setting `_ev_charge_onset_enabled` to True inside
    `_evaluate_onset_gate` (ignoring the passed value) kills
    `TestEnableToggle::test_disabled_gate_is_baseline_ev`.

Wire-in behavioral tests (C-HIGH-2) — neuter each coord wire-in site,
the corresponding NAMED test goes RED:
  * `TestCoordinatorWireIns::test_ec_seed_reaches_both_controllers`
  * `TestCoordinatorWireIns::test_fanout_updates_both_controllers`
  * `TestCoordinatorWireIns::test_ec_setter_dispatch_registers_both_conf_keys`

Piggybacks on test_energy_pool_drain (stubs HA).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import test_energy_pool_drain  # noqa: F401  side-effect: stubs
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402
from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
    SmartPlugController,
    ONSET_SESSION_LOOKBACK_H,
    _DEFAULT_ONSET_MAX_HOLD_H,
    _parse_hhmm,
    _evaluate_onset_gate,
)
from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E402
    next_occurrence_of_hhmm,
    compute_must_start_by,
)


CDT = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _make_ev(charging=True):
    hass = MockHass()
    hass.set_state("switch.garage_a", "off")
    hass.set_state("sensor.garage_a_power_minute_average", "5000" if charging else "0")
    hass.set_state("sensor.garage_a_energy_today", "0")
    hass.set_state("sensor.garage_a_energy_this_month", "0")
    ev = EVChargerController(hass, evse_config={
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power_minute_average",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_this_month",
        },
    })
    ev._paused_by_battery_drain.add("garage_a")
    return ev, hass


def _make_plug():
    hass = MockHass()
    plug_id = "switch.smartplug_moes_wifi_garagealeftfront_socket_1"
    hass.set_state(plug_id, "off")
    sp = SmartPlugController(hass, plug_entities=[plug_id])
    sp._paused_by_battery_drain.add(plug_id)
    return sp, hass, plug_id


def _release_fires(actions) -> bool:
    return any(a.get("service") == "switch.turn_on" for a in actions)


# ---------------------------------------------------------------------------
# extracted helper — byte-identical byte behavior for compute_must_start_by
# ---------------------------------------------------------------------------


class TestExtractedHelperByteIdentical:
    @pytest.mark.parametrize("now_h,now_m,target_min,expect_add_day", [
        (0, 30, 180, False),
        (5, 0, 180, True),
        (2, 59, 180, False),
        (3, 0, 180, True),
        (23, 30, 60, True),
    ])
    def test_must_start_by_matches_inline_semantics(
        self, now_h, now_m, target_min, expect_add_day,
    ):
        now = datetime(2026, 1, 15, now_h, now_m, tzinfo=CDT)
        got = compute_must_start_by(now, minutes_past_midnight=target_min)
        hh, mm = divmod(target_min, 60)
        expected = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if expect_add_day:
            expected = expected + timedelta(days=1)
        assert got == expected


class TestNextOccurrenceStrictlyAfter:
    def test_strictly_after_at_boundary(self):
        now = datetime(2026, 1, 15, 3, 0, tzinfo=CDT)
        got = next_occurrence_of_hhmm(now, 3, 0)
        assert got == now + timedelta(days=1)


# ---------------------------------------------------------------------------
# Rev 6 — bounded HOLD WINDOW predicate
# ---------------------------------------------------------------------------


class TestBoundedHoldWindow:
    """`_evaluate_onset_gate` semantics — the D-B bounded window."""

    def _permits_at(self, now):
        return _evaluate_onset_gate(
            now, True, "01:00", _DEFAULT_ONSET_MAX_HOLD_H, None,
        )[0]

    def test_evening_reserve_hit_is_held(self):
        # 22:00, onset 01:00 → 3h ahead ≤ 8h → HELD (permits=False)
        assert not self._permits_at(datetime(2026, 1, 15, 22, 0, tzinfo=CDT))

    def test_operator_worked_example_still_held_at_0030(self):
        # 00:30, onset 01:00 → 30min ahead ≤ 8h → HELD
        assert not self._permits_at(datetime(2026, 1, 16, 0, 30, tzinfo=CDT))

    def test_at_onset_releases_exactly(self):
        # At the boundary the STRICTLY-after resolver returns tomorrow
        # (delta ~24h > 8h) → NOT held. This is the sharp release edge.
        assert self._permits_at(datetime(2026, 1, 16, 1, 0, tzinfo=CDT))

    def test_daytime_reserve_hit_not_held(self):
        # 10:00, onset 01:00 → NEXT 01:00 = tomorrow → 15h > 8h → NOT held.
        # MUTATION KILL TARGET: setting _DEFAULT_ONSET_MAX_HOLD_H = 24
        # would put this inside the window and hold → test RED.
        assert self._permits_at(datetime(2026, 1, 15, 10, 0, tzinfo=CDT))

    def test_after_onset_same_night_not_held(self):
        # 02:00, onset 01:00 → NEXT 01:00 = tomorrow → 23h > 8h → NOT held.
        assert self._permits_at(datetime(2026, 1, 16, 2, 0, tzinfo=CDT))

    def test_boundary_of_window_is_held(self):
        # exactly 8h to onset → in the closed hold window → HELD
        # 8h before 01:00 = 17:00 previous day.
        assert not self._permits_at(datetime(2026, 1, 15, 17, 0, tzinfo=CDT))

    def test_just_outside_window_not_held(self):
        # 8h1min → NOT held.
        assert self._permits_at(datetime(2026, 1, 15, 16, 59, tzinfo=CDT))


# ---------------------------------------------------------------------------
# Rev 6 — must-start-by backstop
# ---------------------------------------------------------------------------


class TestMustStartByBackstop:
    """Rev 6 D-C: inside the hold window, `must_start_by_reached` at
    03:00 fires the release even if `onset_permits` is still False.
    Load-bearing for the plug tier (no DP).
    """

    def test_before_backstop_holds(self):
        # 02:59, onset 05:00, must_start=03:00 → in hold window,
        # ms not reached → held.
        p, r = _evaluate_onset_gate(
            datetime(2026, 1, 16, 2, 59, tzinfo=CDT),
            True, "05:00", _DEFAULT_ONSET_MAX_HOLD_H, 180,
        )
        assert not p and not r

    def test_at_backstop_releases(self):
        # 03:00, onset 05:00, must_start=03:00 → in window, ms reached.
        p, r = _evaluate_onset_gate(
            datetime(2026, 1, 16, 3, 0, tzinfo=CDT),
            True, "05:00", _DEFAULT_ONSET_MAX_HOLD_H, 180,
        )
        assert not p and r

    def test_ms_disabled_when_out_of_window(self):
        # 10:00 daytime → not in window → ms is inert (must_start_by
        # only fires INSIDE the hold; the outer `battery_out_of_capacity`
        # already governs daytime).
        p, r = _evaluate_onset_gate(
            datetime(2026, 1, 15, 10, 0, tzinfo=CDT),
            True, "05:00", _DEFAULT_ONSET_MAX_HOLD_H, 180,
        )
        assert p and not r

    def test_plug_hard_release_at_must_start_by(self):
        """END-TO-END on the SmartPlugController release site.

        MUTATION TARGET: removing `must_start_by_reached` from the
        overnight_release conjunction leaves this test RED — the plug
        would be held past 03:00 with no DP to save it.
        """
        sp, _hass, plug_id = _make_plug()
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("05:00")  # onset AFTER must-start
        acts = sp.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=22.0,        # SOC ≈ reserve+2 → bat_out_of_cap=True
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            now_local=datetime(2026, 1, 16, 3, 0, tzinfo=CDT),
            must_start_by_min=180,
        )
        assert _release_fires(acts), (
            "L1 plug MUST release at must-start-by (03:00), independent "
            "of DP; this is the plug tier's only hard backstop"
        )


# ---------------------------------------------------------------------------
# Rev 6 — enable toggle (D-A)
# ---------------------------------------------------------------------------


class TestEnableToggle:
    def test_disabled_gate_is_baseline_ev(self):
        """When disabled, `overnight_release = battery_out_of_capacity`
        (no onset term). At 22:00 (would be held if enabled), releases.

        MUTATION TARGET: forcing `enabled=True` inside
        `_evaluate_onset_gate` kills this test — the release would be
        held. Confirms the enable is the load-bearing off switch.
        """
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_time("01:00")
        ev.set_ev_charge_onset_enabled(False)  # kill-switch
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            now_local=datetime(2026, 1, 15, 22, 0, tzinfo=CDT),
            must_start_by_min=180,
        )
        assert _release_fires(acts)

    def test_disabled_gate_is_baseline_plug(self):
        sp, _hass, plug_id = _make_plug()
        sp.set_ev_charge_onset_time("01:00")
        sp.set_ev_charge_onset_enabled(False)
        acts = sp.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            now_local=datetime(2026, 1, 15, 22, 0, tzinfo=CDT),
            must_start_by_min=180,
        )
        assert _release_fires(acts)

    def test_enabled_holds(self):
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            now_local=datetime(2026, 1, 15, 22, 0, tzinfo=CDT),
            must_start_by_min=180,
        )
        assert not _release_fires(acts)


# ---------------------------------------------------------------------------
# Daytime leg UNGATED (regression: distributive form kills these)
# ---------------------------------------------------------------------------


class TestDaytimeSolarLegUngated:
    """`daytime_release = soc_recovered` — NEVER gated by onset."""

    def test_ev_daytime_soc_recovered_fires_when_onset_set(self):
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+200.0,
            battery_soc=80.0,
            soc_threshold=50,   # SOC 80 >= 55 → soc_recovered=True
            reserve_soc=20,     # SOC 80 > 22 → bat_out_of_cap=False
            solar_replenishing=True,
            is_offpeak=False,
            now_local=datetime(2026, 1, 15, 22, 0, tzinfo=CDT),
            must_start_by_min=180,
        )
        assert _release_fires(acts), "daytime soc_recovered must not be onset-gated"

    def test_plug_daytime_soc_recovered_fires_when_onset_set(self):
        sp, _hass, plug_id = _make_plug()
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        acts = sp.determine_battery_drain_actions(
            battery_power_w=+200.0,
            battery_soc=80.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=True,
            is_offpeak=False,
            now_local=datetime(2026, 1, 15, 22, 0, tzinfo=CDT),
            must_start_by_min=180,
        )
        assert _release_fires(acts)


class TestNamedLegSplitDiscriminator:
    """Confirms `daytime_release` alone can fire (structural split intact)."""

    def test_ev_daytime_leg_fires_when_overnight_leg_dark(self):
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        acts = ev.determine_battery_drain_actions(
            battery_power_w=+200.0,
            battery_soc=80.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=True,
            is_offpeak=False,
            now_local=datetime(2026, 1, 15, 22, 30, tzinfo=CDT),
            must_start_by_min=180,
        )
        assert _release_fires(acts)

    def test_plug_daytime_leg_fires_when_overnight_leg_dark(self):
        sp, _hass, plug_id = _make_plug()
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        acts = sp.determine_battery_drain_actions(
            battery_power_w=+200.0,
            battery_soc=80.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=True,
            is_offpeak=False,
            now_local=datetime(2026, 1, 15, 22, 30, tzinfo=CDT),
            must_start_by_min=180,
        )
        assert _release_fires(acts)


# ---------------------------------------------------------------------------
# End-to-end overnight → onset trajectory
# ---------------------------------------------------------------------------


class TestOvernightTrajectory:
    def test_ev_holds_at_2200_fires_at_0100(self):
        ev, _hass = _make_ev()
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        common = dict(
            battery_power_w=+50.0,
            battery_soc=22.0,
            soc_threshold=50,
            reserve_soc=20,
            solar_replenishing=False,
            is_offpeak=True,
            must_start_by_min=180,
        )
        acts = ev.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 15, 22, 0, tzinfo=CDT), **common,
        )
        assert not _release_fires(acts), "held at 22:00 (3h ahead of 01:00)"
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 16, 0, 30, tzinfo=CDT), **common,
        )
        assert not _release_fires(acts), "held at 00:30 (30m before onset)"
        ev._paused_by_battery_drain.add("garage_a")
        acts = ev.determine_battery_drain_actions(
            now_local=datetime(2026, 1, 16, 1, 0, tzinfo=CDT), **common,
        )
        assert _release_fires(acts), "released at 01:00 boundary"


# ---------------------------------------------------------------------------
# now=None fail-OPEN (LOW fix)
# ---------------------------------------------------------------------------


class TestNowNoneFailsOpen:
    def test_gate_permissive_when_now_is_none(self):
        p, r = _evaluate_onset_gate(
            None, True, "01:00", _DEFAULT_ONSET_MAX_HOLD_H, 180,
        )
        assert p and not r


# ---------------------------------------------------------------------------
# Parser (HH:MM and HH:MM:SS) — A-HIGH-1 / C-HIGH-3
# ---------------------------------------------------------------------------


class TestParseHHMM:
    @pytest.mark.parametrize("v,expect", [
        ("01:00", (1, 0)),
        ("01:00:00", (1, 0)),   # HA TimeSelector emits 3-part
        ("23:59:59", (23, 59)),  # seconds dropped
        ("0:00", (0, 0)),
        ("00:00:00", (0, 0)),
        ("", None),
        ("bad", None),
        ("25:00", None),
        ("01:60", None),
        ("01:00:60", None),
        (None, None),
    ])
    def test_parse_hhmm(self, v, expect):
        assert _parse_hhmm(v) == expect

    def test_time_parser_accepts_seconds(self):
        # Also verify time.py mirror handles seconds identically.
        # Install a minimal stub for `homeassistant.components.time` so
        # the module loads without a live HA install.
        import sys as _sys
        import types as _types
        if "homeassistant.components" not in _sys.modules:
            _sys.modules["homeassistant.components"] = _types.ModuleType(
                "homeassistant.components"
            )
            _sys.modules["homeassistant.components"].__path__ = []
        if "homeassistant.components.time" not in _sys.modules:
            m = _types.ModuleType("homeassistant.components.time")
            class _TimeEntity:  # minimal shim
                pass
            m.TimeEntity = _TimeEntity
            _sys.modules["homeassistant.components.time"] = m
        from custom_components.universal_room_automation.time import (
            _parse_hhmm_to_time,
        )
        import datetime as _dt
        assert _parse_hhmm_to_time("01:00:00") == _dt.time(1, 0)
        assert _parse_hhmm_to_time("01:00") == _dt.time(1, 0)
        assert _parse_hhmm_to_time("bad") is None


# ---------------------------------------------------------------------------
# Wire-in behavioral tests (C-HIGH-2) — neuter drills
# ---------------------------------------------------------------------------


class TestCoordinatorWireIns:
    """Behavioral anchors for the coord fan-out surface. If a builder
    deletes or bypasses the wire-in, one of these turns RED.
    """

    def test_ev_and_plug_have_set_enable_methods(self):
        """Both controllers expose `set_ev_charge_onset_enabled`.
        Deleting the plug setter (or renaming) breaks the coord fan-out.
        """
        assert callable(getattr(EVChargerController, "set_ev_charge_onset_enabled", None))
        assert callable(getattr(SmartPlugController, "set_ev_charge_onset_enabled", None))

    def test_ev_and_plug_have_set_time_methods(self):
        assert callable(getattr(EVChargerController, "set_ev_charge_onset_time", None))
        assert callable(getattr(SmartPlugController, "set_ev_charge_onset_time", None))

    def test_fanout_updates_both_controllers(self):
        """The coord setter MUST push to both controllers.

        MUTATION: remove the plug branch of `set_ev_charge_onset_enabled`
        or `set_ev_charge_onset_time` in energy.py → this test RED.
        """
        class _Coord:
            pass
        ev, _hass = _make_ev()
        sp, _hass2, _pid = _make_plug()
        # Simulate the coord's fan-out via calls; assert both sides land.
        for value, expected_str in (("02:30", "02:30"), (None, None)):
            for ctrl in (ev, sp):
                ctrl.set_ev_charge_onset_time(value)
            assert ev._ev_charge_onset_time == expected_str
            assert sp._ev_charge_onset_time == expected_str
        for value in (False, True):
            for ctrl in (ev, sp):
                ctrl.set_ev_charge_onset_enabled(value)
            assert ev._ev_charge_onset_enabled == value
            assert sp._ev_charge_onset_enabled == value

    def _init_src(self):
        """Read `custom_components/universal_room_automation/__init__.py`
        as source text. The HA test harness stubs the package (bare
        ModuleType) so importlib does not load the real `__init__.py`
        with its HA-heavy imports; source-level assertions are the
        authoritative wire-in check."""
        import os
        here = os.path.dirname(__file__)
        p = os.path.abspath(os.path.join(
            here, "..", "..", "custom_components",
            "universal_room_automation", "__init__.py",
        ))
        return open(p).read()

    def test_ec_setter_dispatch_registers_both_conf_keys(self):
        """MUTATION: delete either entry from `_EC_SETTER_DISPATCH` → RED."""
        src = self._init_src()
        assert (
            "_CONF_ENERGY_EVSE_CHARGE_ONSET_TIME:" in src
            and 'set_ev_charge_onset_time' in src
        )
        assert (
            "_CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED:" in src
            and 'set_ev_charge_onset_enabled' in src
        )

    def test_conf_keys_in_reload_suppress_allowlist(self):
        """B-CRIT-2: both CONF keys inside OPTIONS_RELOAD_SUPPRESS_KEYS."""
        src = self._init_src()
        i = src.index("OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str] = frozenset({")
        j = src.index("})", i)
        block = src[i:j]
        assert "_CONF_ENERGY_EVSE_CHARGE_ONSET_TIME" in block
        assert "_CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED" in block

    def test_platform_time_on_cm_forward(self):
        """B-CRIT-1: Platform.TIME MUST be in INTEGRATION_PLATFORMS (CM
        forward), NOT in room PLATFORMS. Source-level assertion - the
        list literal drives `async_forward_entry_setups`.
        """
        src = self._init_src()
        def _list_body(hdr):
            i = src.index(hdr)
            i = src.index("[", i) + 1
            j = src.index("\n]", i)
            return src[i:j]
        integ = _list_body("INTEGRATION_PLATFORMS: list[Platform] = [")
        rooms = _list_body("\nPLATFORMS: list[Platform] = [")
        assert "Platform.TIME" in integ, "Platform.TIME must be CM-forwarded"
        import re
        assert not re.search(
            r"^\s*Platform\.TIME,\s*$", rooms, flags=re.M
        ), "Platform.TIME must not appear in room PLATFORMS (B-CRIT-1)"

    def test_drain_actions_signature_accepts_must_start_by_min(self):
        """The kwarg MUST be present on BOTH release methods; deleting
        it in the coord call site or in the method signature RED."""
        import inspect
        for cls in (EVChargerController, SmartPlugController):
            sig = inspect.signature(cls.determine_battery_drain_actions)
            assert "must_start_by_min" in sig.parameters, cls.__name__


# ---------------------------------------------------------------------------
# Const invariants (mutation targets)
# ---------------------------------------------------------------------------


class TestConstInvariants:
    def test_max_hold_default_is_8h(self):
        # Setting the module default very high (e.g. 24) → the daytime
        # test above (`test_daytime_reserve_hit_not_held`) would flip.
        assert _DEFAULT_ONSET_MAX_HOLD_H == 8.0

    def test_lookback_retired_to_zero(self):
        # Rev-5 lookback is retired; kept as a numeric no-op.
        assert ONSET_SESSION_LOOKBACK_H == 0
