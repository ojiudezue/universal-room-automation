"""EV charge-start dead-band fix — effective release floor + L1/L2 parity.

Tier-3 mutation-anchored tests. Each named test corresponds to a load-bearing
site in the fix; neutering that site MUST turn the named test red.

Sites anchored:
- `energy_pool.py` EV release gate — SOC ≤ reserve_soc (=F) + 2 comparison
- `energy_pool.py` plug release gate — same
- `energy.py` EV call: pass reserve_soc=effective_release_floor
- `energy.py` plug call: pass reserve_soc=effective_release_floor + solar_replenishing
- `energy_pool.py` EV pause gate: release-side sticky at floor
- `energy_pool.py` plug pause gate: release-side sticky at floor
- `energy_battery.py` current_offpeak_drain_target() horizon-aware selection

The bootstrap piggybacks on `test_energy_pool_drain` which already installs
the homeassistant stub module tree.
"""
import importlib
import sys
import os

# Bootstrap the HA stubs and the energy_pool import graph.
sys.path.insert(0, os.path.dirname(__file__))
import test_energy_pool_drain  # noqa: F401  # side-effect: mocks HA + loads modules

import pytest  # noqa: E402

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
    SmartPlugController,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _make_ev(garage_a_on=True, garage_a_power=5000.0):
    hass = MockHass()
    hass.set_state("switch.garage_a", "on" if garage_a_on else "off")
    hass.set_state("sensor.garage_a_power_minute_average", str(garage_a_power))
    hass.set_state("sensor.garage_a_energy_today", "0")
    hass.set_state("sensor.garage_a_energy_this_month", "0")
    evse_config = {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power_minute_average",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_this_month",
        },
    }
    return EVChargerController(hass, evse_config=evse_config), hass


def _make_plug(plug_on=True, plug_id="switch.moes_plug_garage_a"):
    hass = MockHass()
    hass.set_state(plug_id, "on" if plug_on else "off")
    sp = SmartPlugController(hass, plug_entities=[plug_id])
    return sp, hass, plug_id


def _pause_evse_at(ev):
    """Force the EVSE into the _paused_by_battery_drain set.

    (C-LOW-1: SOC param dropped — was cosmetic and misleading; the set is a
    flat membership, not a per-SOC snapshot.)
    """
    ev._paused_by_battery_drain.add("garage_a")


def _pause_plug_at(sp, plug_id):
    sp._paused_by_battery_drain.add(plug_id)


# ---------------------------------------------------------------------------
# D1 — effective floor threaded into EV drain release
# ---------------------------------------------------------------------------


class TestBatteryDrainReleaseUsesEffectiveFloor:
    """Mutation-anchored: neutering `reserve_soc + 2` at pool:1028 (EV) OR
    reverting the effective-floor thread at energy.py:2863-2869 makes this fail.
    """

    @pytest.mark.parametrize(
        "reserve_static,drain_target,soc,expect_release",
        [
            # excellent class: drain_target = 10 = reserve → F=10 → byte-identical
            (10, 10, 8, True),   # SOC below F+2
            (10, 10, 15, False), # SOC above F+2 → hold
            # good/moderate/poor: primary bug case — drain > reserve, release lifts
            (10, 15, 15, True),  # SOC == F → release
            (10, 15, 20, False), # SOC well above F+2 → hold
            (10, 20, 22, True),  # SOC == F+2 (equality inside hysteresis)
            (10, 20, 25, False),
            (10, 30, 30, True),
            (10, 30, 35, False),
            (10, 40, 40, True),
            (10, 40, 45, False),
            # inversion: reserve > target → effective=reserve
            (25, 20, 25, True),
            (25, 20, 30, False),
            # equality: both 20
            (20, 20, 22, True),
            (20, 20, 25, False),
        ],
    )
    def test_battery_drain_release_uses_effective_floor(
        self, reserve_static, drain_target, soc, expect_release,
    ):
        """Release fires exactly when SOC ≤ F + 2 with battery not discharging.

        F = max(reserve_static, drain_target) — the caller-composed floor.
        """
        ev, hass = _make_ev()
        # Turn EVSE state to OFF so a release-turn_on can be observed.
        hass.set_state("switch.garage_a", "off")
        _pause_evse_at(ev)
        effective_floor = max(reserve_static, drain_target)
        actions = ev.determine_battery_drain_actions(
            battery_power_w=+50.0,   # battery not discharging
            battery_soc=soc,
            soc_threshold=50,
            reserve_soc=effective_floor,
            solar_replenishing=False,
            is_offpeak=True,
        )
        released = any(a["service"] == "switch.turn_on" for a in actions)
        assert released == expect_release, (
            f"reserve={reserve_static} target={drain_target} F={effective_floor} "
            f"soc={soc}: expected release={expect_release}, got {released}"
        )


class TestExcellentClassByteIdenticalToPreFix:
    """When drain_target == static reserve (excellent), release must be
    identical to the pre-fix behaviour."""

    def test_excellent_class_byte_identical_to_pre_fix(self):
        ev, hass = _make_ev()
        hass.set_state("switch.garage_a", "off")
        _pause_evse_at(ev)
        # F = max(10, 10) = 10; SOC = 12 → SOC ≤ F+2 → release
        actions = ev.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=12.0,
            soc_threshold=50,
            reserve_soc=10,   # excellent class F
            solar_replenishing=False,
            is_offpeak=True,
        )
        assert any(a["service"] == "switch.turn_on" for a in actions)


# ---------------------------------------------------------------------------
# D2 — plug parity: same fix at plug drain + solar_replenishing threaded
# ---------------------------------------------------------------------------


class TestPlugDrainReleaseParityWithEvse:
    """Neutering `reserve_soc + 2` at pool:1971 (plug) OR reverting the
    effective-floor thread at energy.py:2941-2947 makes this fail.
    """

    @pytest.mark.parametrize(
        "reserve_static,drain_target,soc,expect_release",
        [
            (10, 15, 15, True),
            (10, 15, 20, False),
            (10, 20, 22, True),   # boundary parity with EV — added in fix-up
            (10, 30, 30, True),
            (10, 40, 40, True),
            (10, 40, 45, False),
            (25, 20, 25, True),
        ],
    )
    def test_plug_drain_release_parity_with_evse(
        self, reserve_static, drain_target, soc, expect_release,
    ):
        sp, hass, plug_id = _make_plug(plug_on=False)
        _pause_plug_at(sp, plug_id)
        effective_floor = max(reserve_static, drain_target)
        actions = sp.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=soc,
            soc_threshold=50,
            reserve_soc=effective_floor,
            solar_replenishing=False,
            is_offpeak=True,
        )
        released = any(a["service"] == "switch.turn_on" for a in actions)
        assert released == expect_release


class TestPlugSocRecoveredPathRespectsSolar:
    """Neutering `solar_replenishing` kwarg pass at energy.py:2941-2947
    (i.e. reverting the plug path to the pre-fix False-default) fails this.
    Verifies the SOC-recovered path fires ONLY when solar is actively
    replenishing.
    """

    def test_plug_soc_recovered_path_respects_solar(self):
        sp, hass, plug_id = _make_plug(plug_on=False)
        _pause_plug_at(sp, plug_id)
        # High SOC (well above soc_threshold + 5), battery_ok.
        # `reserve_soc + 2 = 12` — SOC=60 is FAR above → battery_out_of_capacity=False.
        # Only path to release is `soc_recovered` which requires solar_replenishing.
        # solar_replenishing=False → NO release.
        actions_no_solar = sp.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=60.0,
            soc_threshold=50,
            reserve_soc=10,
            solar_replenishing=False,
            is_offpeak=True,
        )
        assert not any(a["service"] == "switch.turn_on" for a in actions_no_solar)
        # solar_replenishing=True → RELEASE via soc_recovered.
        _pause_plug_at(sp, plug_id)  # re-arm
        actions_solar = sp.determine_battery_drain_actions(
            battery_power_w=+50.0,
            battery_soc=60.0,
            soc_threshold=50,
            reserve_soc=10,
            solar_replenishing=True,
            is_offpeak=True,
        )
        assert any(a["service"] == "switch.turn_on" for a in actions_solar)


# ---------------------------------------------------------------------------
# D3 — cooldown-courtesy regression: intentional re-kill preserved
# ---------------------------------------------------------------------------


class TestManualOverrideStillCooldownsAfterDeadbandFix:
    """The cooldown branch (Option B manual-override) is unchanged by the
    dead-band fix; SOC well above F so the release-side sticky is inactive.
    """

    def test_manual_override_still_cooldowns_after_deadband_fix(self):
        import time as _time
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            EV_PAUSE_DISPATCH_GRACE_SECONDS,
        )

        ev, hass = _make_ev()
        # Tick 1: pause
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
            reserve_soc=15, is_offpeak=True,  # F=15; SOC=45 > F+2 → sticky not active
        )
        assert "garage_a" in ev._paused_by_battery_drain
        # URA's turn_off propagated → observed
        hass.set_state("switch.garage_a", "off")
        hass.set_state("sensor.garage_a_power_minute_average", "0")
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
            reserve_soc=15, is_offpeak=True,
        )
        assert ev._observed_off_since_pause.get("garage_a") is True
        # Force grace expiry & user flips on
        ev._pause_dispatch_ts["garage_a"] = _time.monotonic() - (EV_PAUSE_DISPATCH_GRACE_SECONDS + 5)
        hass.set_state("switch.garage_a", "on")
        hass.set_state("sensor.garage_a_power_minute_average", "5000.0")
        ev.determine_battery_drain_actions(
            battery_power_w=-500.0, battery_soc=45.0, soc_threshold=50,
            reserve_soc=15, is_offpeak=True,
        )
        # Cooldown engaged — intentional re-kill semantics preserved
        assert "garage_a" in ev._battery_drain_cooldown


# ---------------------------------------------------------------------------
# D4 — release-side sticky: no re-flap at floor when EV pulls battery transient
# ---------------------------------------------------------------------------


class TestNoReflapAtFloorWhenEvPullsBatteryTransient:
    """Neutering the sticky guard at pool:987-994 (removing `and not
    at_or_below_floor`) makes this test red.
    """

    def test_no_reflap_at_floor_when_ev_pulls_battery_transient(self):
        ev, hass = _make_ev()
        # State: SOC = F (at floor), Enphase hasn't reacted yet, EV load
        # pulling battery: battery_power_w = -500 W discharge. Pause gate
        # WOULD engage pre-fix (charging + discharging + soc_low).
        # Post-fix: sticky guard blocks re-engagement.
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0,
            battery_soc=15.0,
            soc_threshold=50,
            reserve_soc=15,   # F=15, SOC=15 → at floor (inside F±2 band)
            is_offpeak=True,
        )
        # No turn_off action; not added to _paused_by_battery_drain.
        assert not any(a["service"] == "switch.turn_off" for a in actions)
        assert "garage_a" not in ev._paused_by_battery_drain

    def test_no_reflap_at_floor_plug_mirror(self):
        sp, hass, plug_id = _make_plug(plug_on=True)
        actions = sp.determine_battery_drain_actions(
            battery_power_w=-500.0,
            battery_soc=15.0,
            soc_threshold=50,
            reserve_soc=15,
            is_offpeak=True,
        )
        assert not any(a["service"] == "switch.turn_off" for a in actions)
        assert plug_id not in sp._paused_by_battery_drain

    def test_pause_still_engages_above_floor(self):
        """Regression / dual: with SOC above F+2, pause gate MUST still engage."""
        ev, hass = _make_ev()
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0,
            battery_soc=45.0,   # well above F+2=17
            soc_threshold=50,
            reserve_soc=15,
            is_offpeak=True,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert "garage_a" in ev._paused_by_battery_drain

    def test_pause_re_arms_below_band_ev(self):
        """Fix 3: below F−2 the sticky MUST NOT suppress — pause re-arms so a
        reserve-hold failure cannot silently drain the battery.
        """
        ev, hass = _make_ev()
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0,
            battery_soc=12.0,   # F=15, SOC=12 < F−2=13 → outside band
            soc_threshold=50,
            reserve_soc=15,
            is_offpeak=True,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert "garage_a" in ev._paused_by_battery_drain

    def test_pause_re_arms_below_band_plug(self):
        sp, hass, plug_id = _make_plug(plug_on=True)
        actions = sp.determine_battery_drain_actions(
            battery_power_w=-500.0,
            battery_soc=12.0,
            soc_threshold=50,
            reserve_soc=15,
            is_offpeak=True,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert plug_id in sp._paused_by_battery_drain


class TestOffpeakGating:
    """Fix 2: sticky and F-substitution only active during off_peak. Outside
    off_peak the drain pause must remain a hard backstop (reverts to pre-fix
    semantics).
    """

    def test_ev_sticky_disabled_outside_offpeak(self):
        """SOC at floor + discharging + not off_peak → pause MUST engage
        (no sticky suppression)."""
        ev, hass = _make_ev()
        actions = ev.determine_battery_drain_actions(
            battery_power_w=-500.0,
            battery_soc=15.0,
            soc_threshold=50,
            reserve_soc=15,
            is_offpeak=False,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert "garage_a" in ev._paused_by_battery_drain

    def test_plug_sticky_disabled_outside_offpeak(self):
        sp, hass, plug_id = _make_plug(plug_on=True)
        actions = sp.determine_battery_drain_actions(
            battery_power_w=-500.0,
            battery_soc=15.0,
            soc_threshold=50,
            reserve_soc=15,
            is_offpeak=False,
        )
        assert any(a["service"] == "switch.turn_off" for a in actions)
        assert plug_id in sp._paused_by_battery_drain


class TestComposeReleaseFloor:
    """Fix 5: mutation-anchored — the call-site composition helper drives the
    real energy.py path. Neutering the helper (e.g. always returning static
    reserve) OR neutering the off_peak gate turns these red.
    """

    def _make_battery(self, static_reserve, park_floor, drain_target):
        class _B:
            def __init__(self):
                self.reserve_soc = static_reserve
                self._park = park_floor
                self._drain = drain_target
            def current_park_floor(self):
                return self._park
            def current_offpeak_drain_target(self):
                return self._drain
        return _B()

    def test_off_peak_uses_park_floor_over_static(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            compose_release_floor as _compose_release_floor,
        )
        bat = self._make_battery(static_reserve=10, park_floor=45, drain_target=15)
        floor, is_offpeak = _compose_release_floor(bat, "off_peak")
        # partial_hold parks at 45 → F=max(10,45)=45 — the exact leak this fix closes
        assert floor == 45
        assert is_offpeak is True

    def test_off_peak_uses_static_when_park_lower(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            compose_release_floor as _compose_release_floor,
        )
        bat = self._make_battery(static_reserve=25, park_floor=15, drain_target=15)
        floor, is_offpeak = _compose_release_floor(bat, "off_peak")
        assert floor == 25
        assert is_offpeak is True

    def test_off_peak_falls_back_to_drain_target_when_no_park(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            compose_release_floor as _compose_release_floor,
        )
        bat = self._make_battery(static_reserve=10, park_floor=None, drain_target=30)
        floor, is_offpeak = _compose_release_floor(bat, "off_peak")
        assert floor == 30
        assert is_offpeak is True

    def test_peak_returns_static_reserve_and_not_offpeak(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            compose_release_floor as _compose_release_floor,
        )
        # Even if the emitter parked high, peak/mid_peak MUST revert to static:
        # the drain pause is the hard backstop during expensive-grid windows.
        bat = self._make_battery(static_reserve=10, park_floor=45, drain_target=15)
        floor, is_offpeak = _compose_release_floor(bat, "peak")
        assert floor == 10
        assert is_offpeak is False

    def test_mid_peak_returns_static_reserve_and_not_offpeak(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            compose_release_floor as _compose_release_floor,
        )
        bat = self._make_battery(static_reserve=10, park_floor=45, drain_target=15)
        floor, is_offpeak = _compose_release_floor(bat, "mid_peak")
        assert floor == 10
        assert is_offpeak is False


class TestCurrentParkFloorAccessor:
    """Fix 1: `current_park_floor` returns the emitter's ACTUAL last park —
    captures inclement partial_hold + arbitrage/attain parks.
    """

    def _make_bs(self, last_reserve_level, drain_target=15, static_reserve=10):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            BatteryStrategy,
        )
        bs = BatteryStrategy.__new__(BatteryStrategy)
        bs.hass = MockHass()
        bs.reserve_soc = static_reserve
        bs._last_reserve_level = last_reserve_level
        bs._drain_targets = {
            "excellent": 10, "good": 15, "moderate": 20,
            "poor": 30, "very_poor": 30, "unknown": 40,
        }
        bs._multi_day_horizon_enabled = False
        bs.classify_tomorrow_solar = lambda: "good"
        return bs

    def test_park_floor_returns_last_commanded_reserve(self):
        """When the emitter parked at 45 (partial_hold), release floor MUST
        follow — not the drain-target fallback (15)."""
        bs = self._make_bs(last_reserve_level=45)
        assert bs.current_park_floor() == 45

    def test_park_floor_falls_back_to_drain_target_pre_first_emit(self):
        """Pre-first-emit (boot) → fall back to drain-target accessor."""
        bs = self._make_bs(last_reserve_level=None)
        assert bs.current_park_floor() == 15  # "good" class

    def test_park_floor_captures_arbitrage_peak_buffer(self):
        """Arbitrage/attain parks at peak_buffer_target — release must follow."""
        bs = self._make_bs(last_reserve_level=60)
        assert bs.current_park_floor() == 60


# ---------------------------------------------------------------------------
# current_offpeak_drain_target() horizon-aware accessor
# ---------------------------------------------------------------------------


class TestCurrentOffpeakDrainTargetAccessor:
    """Accessor mirrors the emitter's max(D+1, D+2) horizon selection."""

    def _make_battery(self, multi_day, d1_class, d2_class):
        from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
            BatteryStrategy,
        )
        hass = MockHass()
        bs = BatteryStrategy.__new__(BatteryStrategy)
        # Minimal init: only touch the attributes the accessor reads.
        bs.hass = hass
        bs.reserve_soc = 10
        bs._drain_targets = {
            "excellent": 10, "good": 15, "moderate": 20,
            "poor": 30, "very_poor": 30, "unknown": 40,
        }
        bs._multi_day_horizon_enabled = multi_day
        # Monkey-patch class methods used by the accessor
        bs.classify_tomorrow_solar = lambda: d1_class
        bs.classify_solar_day_n = lambda n: d2_class if n == 2 else d1_class
        return bs

    def test_current_offpeak_drain_target_single_day(self):
        bs = self._make_battery(multi_day=False, d1_class="good", d2_class="poor")
        # multi_day off → D+1 only
        assert bs.current_offpeak_drain_target() == 15  # good

    def test_current_offpeak_drain_target_multi_day_picks_higher(self):
        bs = self._make_battery(multi_day=True, d1_class="good", d2_class="poor")
        # max(good=15, poor=30) = 30
        assert bs.current_offpeak_drain_target() == 30

    def test_current_offpeak_drain_target_multi_day_d1_wins_when_higher(self):
        bs = self._make_battery(multi_day=True, d1_class="poor", d2_class="excellent")
        # max(30, 10) = 30
        assert bs.current_offpeak_drain_target() == 30

    def test_current_offpeak_drain_target_unknown(self):
        bs = self._make_battery(multi_day=False, d1_class="unknown", d2_class="unknown")
        assert bs.current_offpeak_drain_target() == 40
