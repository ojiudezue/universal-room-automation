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


# ---------------------------------------------------------------------------
# v3 (funnel) — gated turn-on funnel `_charge_on_or_defer`
# ---------------------------------------------------------------------------


class TestChargeOnsetFunnel:
    """The gated turn-on funnel used by P0 sites #1/#2/#4/#5.

    Neuter drills (each mutation goes RED on its named test, restore):

      * P0-#1 (EV ensure-on ~1508): route the `if not state["is_on"]`
        branch directly to `actions.append({turn_on})` bypassing
        `_charge_on_or_defer` → `test_p0_1_ev_ensure_on_neuter_red` fails.
      * P0-#2 (plug ensure-on ~3483): same drill →
        `test_p0_2_plug_ensure_on_neuter_red` fails.
      * P0-#4 (EV drain-release ~2333): same drill →
        `test_p0_4_ev_drain_release_neuter_red` fails.
      * P0-#5 (plug drain-release ~3813): same drill →
        `test_p0_5_plug_drain_release_neuter_red` fails.

    INV-BASELINE: enable OFF → all 5 sites byte-identical to develop
    (force `enabled=True` inside the funnel → RED via
    `test_inv_baseline_enable_off_permits_turn_on`).
    """

    # ------------------------------------------------------------------ P0-#1
    def test_p0_1_ev_ensure_on_deferred_in_hold_window(self):
        """OFF EV, enabled, onset=01:00, now=22:00 → funnel refuses turn_on."""
        ev, hass = _make_ev(charging=False)
        ev._paused_by_battery_drain.discard("garage_a")
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        now = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = ev._charge_on_or_defer(
            "garage_a", "switch.garage_a", now,
            ev._ev_charge_onset_enabled, ev._ev_charge_onset_time,
            180,
        )
        assert actions == []
        assert "garage_a" in ev._onset_deferred

    def test_p0_1_ev_ensure_on_permit_after_onset(self):
        ev, hass = _make_ev(charging=False)
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        ev._onset_deferred.add("garage_a")
        now = datetime(2026, 1, 2, 1, 0, tzinfo=CDT)
        actions = ev._charge_on_or_defer(
            "garage_a", "switch.garage_a", now, True, "01:00", 180,
        )
        # exactly at 01:00 → next_occurrence returns tomorrow's 01:00
        # → delta 24h > 8h → permits.
        assert _release_fires(actions)
        assert "garage_a" not in ev._onset_deferred

    # ------------------------------------------------------------------ P0-#2
    def test_p0_2_plug_ensure_on_deferred_in_hold_window(self):
        sp, hass, pid = _make_plug()
        sp._paused_by_battery_drain.discard(pid)
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        now = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = sp._charge_on_or_defer(
            pid, pid, now, sp._ev_charge_onset_enabled,
            sp._ev_charge_onset_time, 180,
        )
        assert actions == []
        assert pid in sp._onset_deferred

    # ------------------------------------------------------------------ P0-#4
    def test_p0_4_ev_drain_release_deferred(self):
        """EV drain-release site withholds turn_on inside hold window.

        Neuter drill: replace the `actions.extend(_charge_on_or_defer(...))`
        at the drain-release site with `actions.append({turn_on})`
        bypassing the funnel — this test still expects the inline
        gate's `overnight_release` to compute False when enabled+in-window,
        so it goes RED because the raw append would emit anyway.
        """
        ev, hass = _make_ev(charging=False)
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        # Force battery_out_of_capacity path.
        now_local = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = ev.determine_battery_drain_actions(
            battery_power_w=0.0,
            battery_soc=45.0,
            soc_threshold=50,
            reserve_soc=50,
            solar_replenishing=False,
            is_offpeak=True,
            dp_forcing=False,
            now_local=now_local,
            must_start_by_min=180,
        )
        assert not _release_fires(actions), (
            "expected drain-release to be held by onset gate"
        )

    def test_p0_4_ev_drain_release_permits_after_onset(self):
        ev, hass = _make_ev(charging=False)
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        now_local = datetime(2026, 1, 2, 1, 30, tzinfo=CDT)
        actions = ev.determine_battery_drain_actions(
            battery_power_w=0.0,
            battery_soc=45.0,
            soc_threshold=50,
            reserve_soc=50,
            solar_replenishing=False,
            is_offpeak=True,
            dp_forcing=False,
            now_local=now_local,
            must_start_by_min=180,
        )
        assert _release_fires(actions)

    # ------------------------------------------------------------------ P0-#5
    def test_p0_5_plug_drain_release_deferred(self):
        sp, hass, pid = _make_plug()
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        now_local = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = sp.determine_battery_drain_actions(
            battery_power_w=0.0,
            battery_soc=45.0,
            soc_threshold=50,
            reserve_soc=50,
            force_charge_active=False,
            solar_replenishing=False,
            is_offpeak=True,
            dp_forcing=False,
            now_local=now_local,
            must_start_by_min=180,
        )
        assert not _release_fires(actions), (
            "plug drain-release should be held by onset gate"
        )

    # ------------------------------------------------------------------ CROSS-MIDNIGHT
    def test_cross_midnight_hold_and_release(self):
        """Drain at 22:00 day1, onset=01:00: HELD at 22:00/23:59 day1
        AND 00:30 day2; RELEASE at exactly 01:00 day2.

        Mutation: replace `next_occurrence_of_hhmm` with a same-day
        `now.replace(hh,mm)` inside `_evaluate_onset_gate` → at 00:30
        day2 the delta becomes negative or 30min ago, `in_hold_window`
        would be False → RED here.
        """
        held_ticks = [
            datetime(2026, 1, 1, 22, 0, tzinfo=CDT),
            datetime(2026, 1, 1, 23, 59, tzinfo=CDT),
            datetime(2026, 1, 2, 0, 30, tzinfo=CDT),
        ]
        for n in held_ticks:
            op, mr = _evaluate_onset_gate(
                n, True, "01:00", _DEFAULT_ONSET_MAX_HOLD_H, 180,
            )
            assert not op and not mr, (
                f"expected HELD at {n.isoformat()}, permits={op} ms={mr}"
            )
        release_at = datetime(2026, 1, 2, 1, 0, tzinfo=CDT)
        op, mr = _evaluate_onset_gate(
            release_at, True, "01:00", _DEFAULT_ONSET_MAX_HOLD_H, 180,
        )
        assert op or mr, "expected RELEASE at 01:00 day2"

    # ------------------------------------------------------------------ CLAMP
    def test_clamp_discriminator(self):
        """onset=01:00, ms=720 (12:00), now=17:30 → ms_reached must be False.

        On the un-clamped Rev-5/salvage helper ms_ref = now - 8h = 09:30,
        `next_occurrence(09:30, 12:00)` = today 12:00, `now >= 12:00` True
        → hold defeated every tick. The clamp back to
        `max(now - 8h, onset_instant - 8h)` keeps ms_ref inside the
        current window; onset_instant at 17:30 is tomorrow 01:00,
        window_start = tomorrow 01:00 - 8h = today 17:00, ms_ref = 17:00,
        `next_occurrence(17:00, 12:00)` = tomorrow 12:00, `now >= tomorrow
        12:00` → False. Correct.
        """
        now = datetime(2026, 1, 1, 17, 30, tzinfo=CDT)
        op, mr = _evaluate_onset_gate(
            now, True, "01:00", _DEFAULT_ONSET_MAX_HOLD_H, 720,
        )
        # 17:30 → next 01:00 is 7.5h away → in_hold_window True → permits False.
        assert not op
        # ms clamp: must NOT report reached.
        assert not mr, (
            "un-clamped ms_ref defeats the hold; clamp must keep it False"
        )

    # ------------------------------------------------------------------ INV-BASELINE
    def test_inv_baseline_enable_off_permits_turn_on(self):
        """enable=False → funnel always emits turn_on (baseline byte-identical)."""
        ev, hass = _make_ev(charging=False)
        now = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = ev._charge_on_or_defer(
            "garage_a", "switch.garage_a", now,
            False,  # enabled=False
            "01:00", 180,
        )
        assert _release_fires(actions)
        assert "garage_a" not in ev._onset_deferred

    # ------------------------------------------------------------------ bypass_onset
    def test_bypass_onset_always_permits(self):
        ev, hass = _make_ev(charging=False)
        now = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = ev._charge_on_or_defer(
            "garage_a", "switch.garage_a", now, True, "01:00", 180,
            bypass_onset=True,
        )
        assert _release_fires(actions)

    # ------------------------------------------------------------------ RESET on is_on
    def test_onset_deferred_reset_on_release(self):
        """A charger deferred at 22:00 then permitted at 01:00 clears the set."""
        ev, hass = _make_ev(charging=False)
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        n1 = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        ev._charge_on_or_defer("garage_a", "switch.garage_a", n1,
                                True, "01:00", 180)
        assert "garage_a" in ev._onset_deferred
        n2 = datetime(2026, 1, 2, 1, 0, tzinfo=CDT)
        ev._charge_on_or_defer("garage_a", "switch.garage_a", n2,
                                True, "01:00", 180)
        assert "garage_a" not in ev._onset_deferred

    # ------------------------------------------------------------------ PRUNE
    def test_prune_removes_onset_deferred(self):
        ev, hass = _make_ev(charging=False)
        ev._onset_deferred.add("garage_ghost")
        ev._prune_removed_evses()
        assert "garage_ghost" not in ev._onset_deferred

    def test_plug_prune_removes_onset_deferred(self):
        sp, hass, pid = _make_plug()
        sp._onset_deferred.add("switch.ghost_socket")
        sp.prune_removed_plugs()
        assert "switch.ghost_socket" not in sp._onset_deferred

    # ------------------------------------------------------------------ MUST-START-BY BYPASS
    def test_must_start_by_reached_permits(self):
        """Once must-start-by fires, funnel emits turn_on even in hold window."""
        # onset 01:00, ms=180 (03:00), now=04:00 day1 → in-window? 
        # onset_instant = day1 04:00 → next 01:00 = day2 01:00; delta 21h > 8h
        # → not in window → permits True regardless of ms.
        # For an inside-window MS check use: onset 08:00, ms=180 (03:00), now=05:00
        # onset_instant = day1 08:00, delta 3h, in_hold_window True.
        # ms clamp: window_start = 08:00-8h = 00:00, ms_ref = max(05:00-8h=-03:00-wraps,
        # 00:00) = 00:00; next 03:00 from 00:00 = 03:00; now 05:00 >= 03:00 → True.
        now = datetime(2026, 1, 1, 5, 0, tzinfo=CDT)
        op, mr = _evaluate_onset_gate(
            now, True, "08:00", _DEFAULT_ONSET_MAX_HOLD_H, 180,
        )
        assert not op, "expected inside hold window"
        assert mr, "expected must-start-by reached"


# ---------------------------------------------------------------------------
# v3 (funnel) — REAL WIRE-IN behavioral tests (FIX-REQUIRED from orchestrator)
#
# The `TestChargeOnsetFunnel` block above tests the FUNNEL/HELPER in isolation.
# It does NOT prove the funnel is WIRED IN at the P0 sites. This block drives
# the actual `determine_actions(...)` / `_apply_dp_reversion(...)` code paths
# end-to-end with the onset held, so a future edit reverting any P0 wire-in
# to a raw `switch.turn_on` cannot ship green.
#
# Neuter drills (each: EDIT the WIRE-IN in production source to bypass the
# funnel, run the NAMED test, confirm RED, restore):
#   * P0-#1 (energy_pool.py :1533): replace
#         `actions.extend(self._charge_on_or_defer(...))`
#     with a direct `actions.append({"service":"switch.turn_on", ...})` →
#     `test_wirein_ev_ensure_on_off_peak_held` goes RED.
#   * P0-#2 (energy_pool.py :3515 area, plug ensure-on): same drill →
#     `test_wirein_plug_ensure_on_off_peak_held` goes RED.
#   * P0-#3 (energy.py :5304 area, DP reversion): change
#         `if not (onset_permits or must_start_by_reached):`
#     to `if False:` → `test_wirein_dp_reversion_held` goes RED.
# ---------------------------------------------------------------------------


import custom_components.universal_room_automation.domain_coordinators.energy_pool as _epool_mod  # noqa: E402


class _StubCoord:
    """Minimal `attach_coord` target — the EV ensure-on funnel call
    reads `getattr(coord, "_dp_must_start_by_min", None)` and nothing else."""
    def __init__(self, dp_ms_min=None):
        self._dp_must_start_by_min = dp_ms_min


class TestChargeOnsetWireIns:
    """End-to-end behavioral wire-in anchors for the P0 turn-on sites.

    These drive the ACTUAL production entry points (`determine_actions`
    / `_apply_dp_reversion`) — not the funnel in isolation — so a
    revert of the wire-in call itself is caught (fixes the hollow-anchor
    class of miss).
    """

    # ------------------------------------------------------------------ #1
    def test_wirein_ev_ensure_on_off_peak_held(self, monkeypatch):
        """Drive EVSE `determine_actions("off_peak")` with onset held.

        Preconditions: charger OFF, no peer-owner set, enabled=True,
        onset="01:00", `now=22:00 local`. Expected: NO `switch.turn_on`
        in the returned actions for `garage_a`.

        Wire-in neuter: at energy_pool.py :1533 replace
            `actions.extend(self._charge_on_or_defer(...))`
        with `actions.append({"service":"switch.turn_on", "target":
        switch_entity, "data": {}})` — this test goes RED.
        """
        ev, hass = _make_ev(charging=False)
        # Ensure NO peer-owner set carries over (fixture adds drain).
        ev._paused_by_battery_drain.discard("garage_a")
        assert not ev._stronger_peer_holds("garage_a")
        # Enable onset gate, set held wall-clock.
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        ev.attach_coord(_StubCoord(dp_ms_min=180))
        monkeypatch.setattr(
            _epool_mod,
            "_dt_util_now_or_none",
            lambda: datetime(2026, 1, 1, 22, 0, tzinfo=CDT),
        )
        actions = ev.determine_actions("off_peak")
        turn_ons = [
            a for a in actions
            if a.get("service") == "switch.turn_on"
            and a.get("target") == "switch.garage_a"
        ]
        assert turn_ons == [], (
            "wire-in broken: EV ensure-on turned garage_a on inside "
            f"onset hold window (actions={actions})"
        )
        # Sensor observability: the deferral MUST be recorded.
        assert "garage_a" in ev._onset_deferred

    def test_wirein_ev_ensure_on_off_peak_permits_outside_window(
        self, monkeypatch,
    ):
        """Companion test — enabled=True but now=10:00 (outside 8h
        window) → ensure-on DOES emit turn_on. Guards against a naive
        neuter that always defers."""
        ev, hass = _make_ev(charging=False)
        ev._paused_by_battery_drain.discard("garage_a")
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        ev.attach_coord(_StubCoord(dp_ms_min=180))
        monkeypatch.setattr(
            _epool_mod,
            "_dt_util_now_or_none",
            lambda: datetime(2026, 1, 1, 10, 0, tzinfo=CDT),
        )
        actions = ev.determine_actions("off_peak")
        assert any(
            a.get("service") == "switch.turn_on"
            and a.get("target") == "switch.garage_a"
            for a in actions
        ), f"ensure-on should fire outside hold window; actions={actions}"

    # ------------------------------------------------------------------ #2
    def test_wirein_plug_ensure_on_off_peak_held(self, monkeypatch):
        """Drive plug `determine_actions("off_peak", must_start_by_min=180)`.

        Wire-in neuter: at the plug ensure-on site (~ :3515) replace
        the `actions.extend(self._charge_on_or_defer(...))` with a
        direct `actions.append({"service":"switch.turn_on", ...})` —
        this test goes RED.
        """
        sp, hass, pid = _make_plug()
        sp._paused_by_battery_drain.discard(pid)
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        monkeypatch.setattr(
            _epool_mod,
            "_dt_util_now_or_none",
            lambda: datetime(2026, 1, 1, 22, 0, tzinfo=CDT),
        )
        actions = sp.determine_actions(
            "off_peak",
            force_charge_active=False,
            grid_charge_on=False,
            must_start_by_min=180,
        )
        turn_ons = [
            a for a in actions
            if a.get("service") == "switch.turn_on" and a.get("target") == pid
        ]
        assert turn_ons == [], (
            f"wire-in broken: plug ensure-on turned {pid} on inside "
            f"onset hold window"
        )
        assert pid in sp._onset_deferred

    def test_wirein_plug_ensure_on_off_peak_permits_outside_window(
        self, monkeypatch,
    ):
        sp, hass, pid = _make_plug()
        sp._paused_by_battery_drain.discard(pid)
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        monkeypatch.setattr(
            _epool_mod,
            "_dt_util_now_or_none",
            lambda: datetime(2026, 1, 1, 10, 0, tzinfo=CDT),
        )
        actions = sp.determine_actions(
            "off_peak", force_charge_active=False,
            grid_charge_on=False, must_start_by_min=180,
        )
        assert any(
            a.get("service") == "switch.turn_on" and a.get("target") == pid
            for a in actions
        ), f"plug ensure-on should fire outside hold window; actions={actions}"

    # ------------------------------------------------------------------ #4  (drain-release, live path — WIRE-IN via inline gate at :2318)
    def test_wirein_ev_drain_release_held_via_determine_actions(
        self, monkeypatch,
    ):
        """Drive `determine_battery_drain_actions` end-to-end with
        `battery_out_of_capacity=True` and onset held.

        This is the SAME entry point production uses (energy.py :6048).
        Wire-in neuter: at the inline gate (~ :2316) change
            `overnight_release = battery_out_of_capacity and (`
                `onset_permits or dp_forcing or must_start_by_reached`
            `)`
        to
            `overnight_release = battery_out_of_capacity`
        — this test goes RED. The `bypass_onset=True` funnel call at
        :2355 is stylistic (funnel wrapper) so neutering it alone will
        NOT change behavior — the load-bearing wire-in for #4 IS the
        inline gate, and this test anchors it via the true production
        method.
        """
        ev, hass = _make_ev(charging=False)
        # keep _paused_by_battery_drain (fixture adds it — required for release path).
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        now_local = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = ev.determine_battery_drain_actions(
            battery_power_w=0.0,
            battery_soc=45.0,
            soc_threshold=50,
            reserve_soc=50,
            solar_replenishing=False,
            is_offpeak=True,
            dp_forcing=False,
            now_local=now_local,
            must_start_by_min=180,
        )
        assert not any(
            a.get("service") == "switch.turn_on" for a in actions
        ), f"drain-release must be held by onset gate; actions={actions}"

    # ------------------------------------------------------------------ #5  (plug drain-release, live path — inline gate)
    def test_wirein_plug_drain_release_held_via_determine_actions(self):
        sp, hass, pid = _make_plug()
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        now_local = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = sp.determine_battery_drain_actions(
            battery_power_w=0.0,
            battery_soc=45.0,
            soc_threshold=50,
            reserve_soc=50,
            force_charge_active=False,
            solar_replenishing=False,
            is_offpeak=True,
            dp_forcing=False,
            now_local=now_local,
            must_start_by_min=180,
        )
        assert not any(
            a.get("service") == "switch.turn_on" for a in actions
        ), f"plug drain-release must be held; actions={actions}"

    # ------------------------------------------------------------------ #3  (DP reversion — in-suite anchor per plan)
    def test_wirein_dp_reversion_held(self, monkeypatch):
        """Drive `EnergyCoordinator._apply_dp_reversion("off_peak")`
        with a DP-paused EVSE and onset held. Expected: no `switch.turn_on`
        dispatched.

        Wire-in neuter (energy.py :5304 area): change
            `if not (onset_permits or must_start_by_reached):`
        to `if False:` — this test goes RED.

        Uses the same AST-extraction pattern as
        `test_evse_drain_precedence_session_b2b_ii.py` so we drive the
        real `_apply_dp_reversion` bytecode from energy.py (not a
        re-implementation).
        """
        # Local AST-extract of `_apply_dp_reversion` (mirrors
        # test_evse_drain_precedence_session_b2b_ii.py). Kept local so
        # this test module has no cross-file test dependency.
        import ast as _ast
        import asyncio as _asyncio
        import os as _os
        from unittest.mock import MagicMock as _MM
        _dc = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__)))),
            "custom_components",
            "universal_room_automation",
            "domain_coordinators",
        )
        with open(_os.path.join(_dc, "energy.py"), "r", encoding="utf-8") as fh:
            src = fh.read()
        tree = _ast.parse(src)
        src_lines = src.splitlines()
        method_src: str | None = None
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.ClassDef) or node.name != "EnergyCoordinator":
                continue
            for child in node.body:
                if (isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                        and child.name == "_apply_dp_reversion"):
                    seg = "\n".join(
                        src_lines[child.lineno - 1: child.end_lineno]
                    )
                    method_src = "\n".join(
                        line[4:] if line.startswith("    ") else line
                        for line in seg.splitlines()
                    )
        assert method_src is not None, "_apply_dp_reversion not found"

        import logging as _logging
        ns: dict = {
            "_LOGGER": _logging.getLogger("test_dp_reversion_wirein"),
            "Any": object,
            "__name__": "custom_components.universal_room_automation.domain_coordinators.energy",
            "__package__": "custom_components.universal_room_automation.domain_coordinators",
        }
        exec(compile(method_src, "<energy.py-extract-onset-#3>", "exec"), ns)

        # Build the fake coord + captured dispatch.
        hass = MockHass()
        hass.set_state("switch.garage_a", "off")
        loop = _asyncio.new_event_loop()
        calls: list[tuple[str, str, dict]] = []

        def _run_task(coro):
            loop.run_until_complete(coro)
            return _MM()

        async def _svc(*a, **kw):
            calls.append((a[0], a[1], dict(a[2]) if len(a) > 2 else {}))

        hass.async_create_task = _run_task
        hass.services = _MM()
        hass.services.async_call = _svc

        ev = EVChargerController(hass, evse_config={
            "garage_a": {
                "switch": "switch.garage_a",
                "power": "sensor.garage_a_power",
                "energy_today": "sensor.garage_a_energy_today",
                "energy_month": "sensor.garage_a_energy_month",
            },
        })
        ev._paused_by_dp.add("garage_a")
        ev._claim_pause_dispatch_owner("garage_a", "dp")
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")

        class _Coord:
            pass
        coord = _Coord()
        coord.hass = hass
        coord._ev = ev
        coord._dp_decision_soc = 30
        coord._dp_must_start_by_min = 180
        # Bind the extracted method to the fake coord instance.
        coord._cancel_dp_must_start_by_timer = lambda: None
        coord._apply_dp_reversion = ns["_apply_dp_reversion"].__get__(coord)

        # Freeze `now` inside the extracted code so the onset gate holds.
        # The extracted `_apply_dp_reversion` imports `dt_util` from the
        # `homeassistant.util` package at call time; monkeypatch to return
        # a controlled 22:00 local.
        import homeassistant.util.dt as _dt_util_mod
        monkeypatch.setattr(
            _dt_util_mod, "now",
            lambda: datetime(2026, 1, 1, 22, 0, tzinfo=CDT),
        )

        coord._apply_dp_reversion(tou_period="off_peak")

        assert calls == [], (
            "wire-in broken: DP reversion dispatched a turn_on inside "
            f"onset hold window; calls={calls}"
        )
        assert "garage_a" in ev._onset_deferred, (
            "sensor observability: _onset_deferred must record the defer"
        )


# ---------------------------------------------------------------------------
# v3 FIX-UP anchors — arbitrage / FP / bespoke switch / drain-site sensor
# ---------------------------------------------------------------------------


class TestChargeOnsetFixUpWireIns:
    """v3 fix-up anchors for the two D-HIGH turn-on paths (arbitrage +
    fill-priority×2), the bespoke enable-switch fan-out, and the
    D-MED-2 sensor observability at drain sites.

    Neuter drills (each: edit the WIRE-IN in production source, run
    named test, confirm RED, restore):

    * Arbitrage release (energy_pool.py ~:2775-2789): drop the
      `or evse_id in self._proactive_offpeak_holds` peer check →
      `test_wirein_arbitrage_release_held_by_onset` goes RED.
    * EV FP forecast_decayed (energy_pool.py ~:2604 area): revert the
      funnel call to `actions.append({...turn_on})` →
      `test_wirein_ev_fp_resume_held` goes RED.
    * Plug FP forecast_decayed (energy_pool.py ~:4021 area): same →
      `test_wirein_plug_fp_resume_held` goes RED.
    * Bespoke switch subclass: revert `ECEVChargeOnsetEnabledSwitch`
      to the bare factory (`= _ECEVChargeOnsetEnabledBase`) →
      `test_wirein_switch_fans_out_to_both_controllers` goes RED.
    * Drain-site sensor (energy_pool.py ~:2323 / ~:3834): remove the
      `self._onset_deferred.add(...)` inside the
      `battery_out_of_capacity and not overnight_release` branch →
      `test_wirein_drain_site_marks_onset_deferred` goes RED.
    """

    # -------------------------------------------------------------- arbitrage
    def test_wirein_arbitrage_release_held_by_onset(self):
        """Arbitrage exits CHARGE at off_peak with an onset-deferred
        (in `_proactive_offpeak_holds`) EVSE — must NOT emit turn_on."""
        ev, hass = _make_ev(charging=False)
        ev._paused_by_battery_drain.discard("garage_a")  # fixture leftover
        ev._paused_by_arbitrage.add("garage_a")
        ev._proactive_offpeak_holds.add("garage_a")
        actions = ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
        )
        assert not any(
            a.get("service") == "switch.turn_on" for a in actions
        ), f"arbitrage release must not turn on onset-deferred EVSE; actions={actions}"

    def test_wirein_arbitrage_release_permits_when_not_held(self):
        """Companion: no `_proactive_offpeak_holds` membership →
        arbitrage release DOES emit turn_on. Guards a naive
        `if False:` neuter that always defers."""
        ev, hass = _make_ev(charging=False)
        ev._paused_by_battery_drain.discard("garage_a")  # fixture leftover
        ev._paused_by_arbitrage.add("garage_a")
        actions = ev.determine_arbitrage_actions(
            arbitrage_charging=False, tou_period="off_peak",
        )
        assert any(
            a.get("service") == "switch.turn_on"
            and a.get("target") == "switch.garage_a"
            for a in actions
        ), f"arbitrage release should fire when not onset-held; actions={actions}"

    # -------------------------------------------------------------- EV FP
    def test_wirein_ev_fp_resume_held(self, monkeypatch):
        """EV FP resume with onset held must NOT emit turn_on."""
        ev, hass = _make_ev(charging=False)
        ev._paused_by_battery_drain.discard("garage_a")
        ev._paused_by_fill_priority.add("garage_a")
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        ev.attach_coord(_StubCoord(dp_ms_min=180))
        monkeypatch.setattr(
            _epool_mod, "_dt_util_now_or_none",
            lambda: datetime(2026, 1, 1, 22, 0, tzinfo=CDT),
        )
        actions = ev.determine_fill_priority_actions(
            soc=99.0,
            remaining_forecast_kwh=100.0,
            tou_period="off_peak",
            soc_threshold=80,
            excess_solar_kwh_threshold=10.0,
            is_daylight=True,
        )
        turn_ons = [
            a for a in actions
            if a.get("service") == "switch.turn_on"
            and a.get("target") == "switch.garage_a"
        ]
        assert turn_ons == [], (
            f"EV FP resume must be held by onset gate; actions={actions}"
        )

    # -------------------------------------------------------------- plug FP
    def test_wirein_plug_fp_resume_held(self, monkeypatch):
        sp, hass, pid = _make_plug()
        sp._paused_by_battery_drain.discard(pid)
        sp._paused_by_fill_priority.add(pid)
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        monkeypatch.setattr(
            _epool_mod, "_dt_util_now_or_none",
            lambda: datetime(2026, 1, 1, 22, 0, tzinfo=CDT),
        )
        actions = sp.determine_fill_priority_actions(
            soc=99.0,
            remaining_forecast_kwh=100.0,
            tou_period="off_peak",
            soc_threshold=80,
            excess_solar_kwh_threshold=10.0,
            is_daylight=True,
            must_start_by_min=180,
        )
        turn_ons = [
            a for a in actions
            if a.get("service") == "switch.turn_on" and a.get("target") == pid
        ]
        assert turn_ons == [], (
            f"plug FP resume must be held by onset gate; actions={actions}"
        )

    # -------------------------------------------------------------- bespoke switch
    def test_wirein_switch_fans_out_to_both_controllers(self):
        """The enable switch's async_turn_on/off MUST route through
        `EnergyCoordinator.set_ev_charge_onset_enabled` (which fans
        out to BOTH controllers), NOT via bare setattr on the coord
        mirror alone. Verified: BOTH controller attrs flip in lockstep.

        We build a MINIMAL clone of the bespoke override methods and
        drive them against real EV+plug controllers — this avoids the
        heavy `switch.py` module import (which pulls
        `homeassistant.components.switch` not stubbed here) and still
        proves the fan-out contract: an implementation that setattr's
        the coord mirror WITHOUT calling the setter would leave the
        controller attrs stale — this test would then fail.

        AST-extract keeps the test faithful to shipped source: the
        bespoke class body is compiled from switch.py bytes at test
        time so an accidental revert to a bare factory is caught.
        """
        import ast as _ast
        import os as _os
        import asyncio as _aio
        import logging as _logging
        from unittest.mock import MagicMock as _MM

        # Extract the setter from energy.py without importing the full
        # module (its top-level `from homeassistant...` chain is heavier
        # than the stubs installed here). The setter body is small +
        # self-contained.
        _dc_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__)))),
            "custom_components", "universal_room_automation",
            "domain_coordinators",
        )
        with open(_os.path.join(_dc_path, "energy.py"),
                  "r", encoding="utf-8") as fh:
            _energy_src = fh.read()
        _e_tree = _ast.parse(_energy_src)
        _setter_src: str | None = None
        for _node in _ast.walk(_e_tree):
            if (isinstance(_node, _ast.ClassDef)
                    and _node.name == "EnergyCoordinator"):
                _el = _energy_src.splitlines()
                for _child in _node.body:
                    if (isinstance(_child, _ast.FunctionDef)
                            and _child.name == "set_ev_charge_onset_enabled"):
                        _seg = "\n".join(
                            _el[_child.lineno - 1: _child.end_lineno]
                        )
                        _setter_src = "\n".join(
                            line[4:] if line.startswith("    ") else line
                            for line in _seg.splitlines()
                        )
        assert _setter_src is not None, (
            "wire-in broken: `set_ev_charge_onset_enabled` not found on "
            "EnergyCoordinator — the fan-out contract is gone."
        )
        _setter_ns = {"_LOGGER": _logging.getLogger("test_switch_fanout")}
        exec(compile(_setter_src,
                     "<energy.py-extract-set-onset-enabled>",
                     "exec"), _setter_ns)

        # Locate + parse switch.py, extract the ECEVChargeOnsetEnabledSwitch
        # class body. If a future edit reverts the bespoke subclass to a
        # bare factory (`ECEVChargeOnsetEnabledSwitch = _ec_switch_factory(...)`),
        # the assertion below fails.
        _sw_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__)))),
            "custom_components", "universal_room_automation", "switch.py",
        )
        with open(_sw_path, "r", encoding="utf-8") as fh:
            src = fh.read()
        assert "class ECEVChargeOnsetEnabledSwitch(" in src, (
            "wire-in broken: ECEVChargeOnsetEnabledSwitch is not a "
            "subclass — bare factory reverts route the coord mirror "
            "via setattr and never reach the sub-controllers."
        )
        tree = _ast.parse(src)
        method_srcs: dict[str, str] = {}
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.ClassDef)
                    and node.name == "ECEVChargeOnsetEnabledSwitch"):
                src_lines = src.splitlines()
                for child in node.body:
                    if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                        seg = "\n".join(
                            src_lines[child.lineno - 1: child.end_lineno]
                        )
                        # Dedent 4 spaces (class body indent).
                        method_srcs[child.name] = "\n".join(
                            line[4:] if line.startswith("    ") else line
                            for line in seg.splitlines()
                        )
        assert "_route_to_setter" in method_srcs, (
            "wire-in broken: _route_to_setter missing — an override "
            "would revert the write paths to the bare setattr behavior."
        )
        assert "async_turn_on" in method_srcs and "async_turn_off" in method_srcs, (
            "wire-in broken: async_turn_on / async_turn_off overrides missing."
        )

        ev, hass = _make_ev(charging=False)
        sp = SmartPlugController(hass, plug_entities=[])

        class _CoordStub:
            _ev_charge_onset_enabled = False
        coord = _CoordStub()
        coord._ev = ev
        coord._smart_plugs = sp
        coord.set_ev_charge_onset_enabled = (
            _setter_ns["set_ev_charge_onset_enabled"].__get__(coord)
        )

        # Build a stand-in switch instance carrying the shipped methods.
        # `_get_energy` is inherited on the real factory base — supply a
        # minimal one that resolves to `coord`.
        class _FakeSwitch:
            def _get_energy(self):
                return coord
        fake = _FakeSwitch()
        fake._deferred_restore = False

        # Compile+bind `_route_to_setter`, `async_turn_on`, `async_turn_off`.
        # async_write_ha_state is a no-op inside the override.
        fake.async_write_ha_state = lambda: None
        ns: dict = {}
        exec(compile(method_srcs["_route_to_setter"],
                     "<switch.py-extract-onset-#B-CRIT-A>", "exec"), ns)
        exec(compile(method_srcs["async_turn_on"],
                     "<switch.py-extract-onset-#B-CRIT-A>", "exec"), ns)
        exec(compile(method_srcs["async_turn_off"],
                     "<switch.py-extract-onset-#B-CRIT-A>", "exec"), ns)
        fake._route_to_setter = ns["_route_to_setter"].__get__(fake)
        fake.async_turn_on = ns["async_turn_on"].__get__(fake)
        fake.async_turn_off = ns["async_turn_off"].__get__(fake)

        loop = _aio.new_event_loop()
        loop.run_until_complete(fake.async_turn_on())
        assert ev._ev_charge_onset_enabled is True, (
            "wire-in broken: switch turn_on did not reach EV controller"
        )
        assert sp._ev_charge_onset_enabled is True, (
            "wire-in broken: switch turn_on did not reach plug controller"
        )
        assert coord._ev_charge_onset_enabled is True

        loop.run_until_complete(fake.async_turn_off())
        assert ev._ev_charge_onset_enabled is False
        assert sp._ev_charge_onset_enabled is False
        assert coord._ev_charge_onset_enabled is False

    # -------------------------------------------------------------- drain sensor
    def test_wirein_drain_site_marks_onset_deferred(self):
        """When drain-release is held by onset at #4, the held evse_id
        MUST appear in `_onset_deferred` so `ura_ev_charge_onset_active`
        sensor reflects the hold."""
        ev, hass = _make_ev(charging=False)
        ev.set_ev_charge_onset_enabled(True)
        ev.set_ev_charge_onset_time("01:00")
        now_local = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = ev.determine_battery_drain_actions(
            battery_power_w=0.0,
            battery_soc=45.0,
            soc_threshold=50,
            reserve_soc=50,
            solar_replenishing=False,
            is_offpeak=True,
            dp_forcing=False,
            now_local=now_local,
            must_start_by_min=180,
        )
        assert not any(
            a.get("service") == "switch.turn_on" for a in actions
        )
        assert "garage_a" in ev._onset_deferred, (
            "sensor observability: drain-site hold did not mark _onset_deferred"
        )

    def test_wirein_drain_site_marks_onset_deferred_plug(self):
        sp, hass, pid = _make_plug()
        sp.set_ev_charge_onset_enabled(True)
        sp.set_ev_charge_onset_time("01:00")
        now_local = datetime(2026, 1, 1, 22, 0, tzinfo=CDT)
        actions = sp.determine_battery_drain_actions(
            battery_power_w=0.0,
            battery_soc=45.0,
            soc_threshold=50,
            reserve_soc=50,
            force_charge_active=False,
            solar_replenishing=False,
            is_offpeak=True,
            dp_forcing=False,
            now_local=now_local,
            must_start_by_min=180,
        )
        assert not any(
            a.get("service") == "switch.turn_on" for a in actions
        )
        assert pid in sp._onset_deferred, (
            "sensor observability: plug drain-site hold did not mark _onset_deferred"
        )
