"""v4.7.2.1 hotfix: OccupancyWeightedPredictionSwitch restore across restart.

Bug: switch.ura_energy_occupancy_weighted_prediction flipped OFF after every
HA restart. The prior bespoke OccupancyWeightedPredictionSwitch class used
RestoreEntity but had:
  - No SIGNAL_ENERGY_COORDINATOR_READY subscription (Bug Class #5).
  - Only a single 5s timer retry — if the EC was not yet registered at that
    point, the user's persisted ON state was silently dropped.

Fix (Path 1): Replaced the bespoke class with _ec_switch_factory("occupancy_weighted",
"occupancy_weighted_prediction", ...), which has the v4.5.3 retry chain (5s/30s/120s)
AND the v4.7.x D2 SIGNAL_ENERGY_COORDINATOR_READY subscription, both already proven
correct for the other factory-generated EC switches.

Counter: _pending_sub_switch_restores bumped from 5 → 6 so the
binary_sensor.ura_energy_coordinator_ec_sub_switches_synced health sensor
counts this switch too.
"""

import ast
import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def switch_src() -> str:
    with open("custom_components/universal_room_automation/switch.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def energy_src() -> str:
    with open(
        "custom_components/universal_room_automation/domain_coordinators/energy.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def switch_ast() -> ast.Module:
    with open("custom_components/universal_room_automation/switch.py") as f:
        src = f.read()
    return ast.parse(src)


# ===========================================================================
# Test: factory conversion (Path 1)
# ===========================================================================


class TestUsesEcSwitchFactory:
    """v4.7.2.1: OccupancyWeightedPredictionSwitch must be produced by
    _ec_switch_factory, not defined as a standalone class."""

    def test_v4721_uses_ec_switch_factory(self, switch_src):
        """OccupancyWeightedPredictionSwitch must be an _ec_switch_factory call."""
        assert "OccupancyWeightedPredictionSwitch = _ec_switch_factory(" in switch_src, (
            "v4.7.2.1: OccupancyWeightedPredictionSwitch must be produced by "
            "_ec_switch_factory (Path 1 conversion)"
        )

    def test_v4721_no_bespoke_class_definition(self, switch_src):
        """The bespoke class body must no longer exist in switch.py."""
        assert "class OccupancyWeightedPredictionSwitch(" not in switch_src, (
            "v4.7.2.1: bespoke OccupancyWeightedPredictionSwitch class definition "
            "must be removed — factory call is the only definition"
        )

    def test_v4721_factory_call_uses_occupancy_weighted_attr(self, switch_src):
        """The factory call must target the 'occupancy_weighted' attribute on EC."""
        idx = switch_src.find("OccupancyWeightedPredictionSwitch = _ec_switch_factory(")
        assert idx > 0
        call_body = switch_src[idx:idx + 400]
        assert '"occupancy_weighted"' in call_body, (
            "factory call must pass attr_name='occupancy_weighted'"
        )

    def test_v4721_factory_call_preserves_unique_id_suffix(self, switch_src):
        """unique_id suffix must be 'occupancy_weighted_prediction' for entity_id stability."""
        idx = switch_src.find("OccupancyWeightedPredictionSwitch = _ec_switch_factory(")
        assert idx > 0
        call_body = switch_src[idx:idx + 400]
        assert '"occupancy_weighted_prediction"' in call_body, (
            "factory call must preserve unique_id suffix 'occupancy_weighted_prediction' "
            "so entity_id switch.ura_energy_occupancy_weighted_prediction is stable"
        )

    def test_v4721_factory_call_default_is_false(self, switch_src):
        """Default must be False (match prior bespoke class behaviour)."""
        idx = switch_src.find("OccupancyWeightedPredictionSwitch = _ec_switch_factory(")
        assert idx > 0
        call_body = switch_src[idx:idx + 400]
        assert "default=False" in call_body, (
            "factory call must pass default=False (matches prior bespoke class)"
        )


# ===========================================================================
# Test: pending_sub_switch_restores counter
# ===========================================================================


class TestPendingSubSwitchRestoresCounter:
    """EC Envoy boot-decoupling cycle (C7 fix): the hardcoded 6 was stale
    — production now dynamically counts switches that call
    `register_sub_switch_for_restore_accounting()` at construction. The
    counter starts at 0 and accumulates as switches register.
    Original v4.7.2.1 intent (OccupancyWeightedPredictionSwitch joins the
    tracked set) is still honored — it now uses the factory's
    auto-registration path.
    """

    def test_pending_sub_switch_restores_counter_starts_at_zero(self, energy_src):
        """_pending_sub_switch_restores initial value is 0 (C7 dynamic)."""
        assert "self._pending_sub_switch_restores: int = 0" in energy_src, (
            "C7 fix: dynamic restore accounting starts at 0 and is "
            "incremented by register_sub_switch_for_restore_accounting()"
        )

    def test_register_sub_switch_helper_exists(self, energy_src):
        """The dynamic-registration helper must be defined."""
        assert "def register_sub_switch_for_restore_accounting(" in energy_src, (
            "C7 fix: dynamic registration helper missing on EnergyCoordinator"
        )

    def test_v4721_counter_not_stale_6(self, energy_src):
        """The pre-C7 hardcoded 6 must no longer appear as an init value
        (it was stale — 7 factory switches + HVACDynamicPresetSwitch = 8
        actual notifiers)."""
        assert "self._pending_sub_switch_restores: int = 6" not in energy_src, (
            "Hardcoded 6 must be replaced with dynamic registration"
        )


# ===========================================================================
# Test: deferred-restore simulation (startup race, Bug Class #5)
# ===========================================================================


class _MockEnergy:
    """Minimal EnergyCoordinator stand-in. setattr/getattr work directly."""
    pass


class _OccupancyWeightedSwitchMirror:
    """Mirror of _ec_switch_factory("occupancy_weighted", ...) deferred-restore logic.

    Replicates the v4.5.3 retry-chain + v4.7.x D2 SIGNAL_ENERGY_COORDINATOR_READY
    behaviour without importing HA. The mirror models exactly what the factory
    generates; divergence from production is caught by TestSourceMirrorContract.
    """

    _RETRY_DELAYS_S = (5, 30, 120)
    _ATTR_NAME = "occupancy_weighted"

    def __init__(self, get_energy):
        self._get_energy = get_energy
        self._default = False
        self._deferred_restore = False
        self._deferred_value = False
        self._retry_index = 0
        self.scheduled = []    # [(delay, callback), …]
        self.ec_ready_handlers = []  # SIGNAL_ENERGY_COORDINATOR_READY subscribers

    # Simplified lifecycle — no actual HA, no async
    def async_added_to_hass(self, last_state):
        # Subscribe to signal (recorded for manual fire in tests)
        self.ec_ready_handlers.append(self._handle_ec_ready)

        if last_state is None:
            return
        target = last_state == "on"
        self._deferred_value = target
        energy = self._get_energy()
        if energy is not None:
            setattr(energy, self._ATTR_NAME, target)
            self._deferred_restore = False
            return
        self._deferred_restore = True
        self._retry_index = 0
        self.scheduled.append((self._RETRY_DELAYS_S[0], self._retry_restore))

    def _handle_ec_ready(self):
        if not self._deferred_restore:
            return
        energy = self._get_energy()
        if energy is None:
            return
        setattr(energy, self._ATTR_NAME, self._deferred_value)
        self._deferred_restore = False

    def _retry_restore(self, _now=None):
        if not self._deferred_restore:
            return
        energy = self._get_energy()
        if energy is not None:
            setattr(energy, self._ATTR_NAME, self._deferred_value)
            self._deferred_restore = False
            return
        self._retry_index += 1
        if self._retry_index < len(self._RETRY_DELAYS_S):
            self.scheduled.append(
                (self._RETRY_DELAYS_S[self._retry_index], self._retry_restore)
            )

    def fire_ec_ready(self):
        """Simulate SIGNAL_ENERGY_COORDINATOR_READY dispatch."""
        for handler in self.ec_ready_handlers:
            handler()


def _last_state(s):
    return s  # string "on"/"off" / None


class TestOccupancyWeightedSurvivesRestart:
    """v4.7.2.1 core scenario: user sets switch ON, HA restarts, switch stays ON."""

    def test_v4721_occupancy_weighted_survives_restart_fast_path(self):
        """EC available at async_added_to_hass — restore lands immediately."""
        energy = _MockEnergy()
        energy.occupancy_weighted = False   # constructor seed
        switch = _OccupancyWeightedSwitchMirror(lambda: energy)

        switch.async_added_to_hass(_last_state("on"))

        assert energy.occupancy_weighted is True, (
            "v4.7.2.1: fast-path restore must set occupancy_weighted=True"
        )
        assert switch._deferred_restore is False

    def test_v4721_occupancy_weighted_survives_restart_via_ec_ready_signal(self):
        """EC NOT available at async_added_to_hass but arrives before retry fires.
        SIGNAL_ENERGY_COORDINATOR_READY must complete the restore."""
        energy_ref = [None]
        switch = _OccupancyWeightedSwitchMirror(lambda: energy_ref[0])

        switch.async_added_to_hass(_last_state("on"))

        # Confirm restore is pending
        assert switch._deferred_restore is True
        assert switch._deferred_value is True

        # EC registers — fire the signal
        energy_ref[0] = _MockEnergy()
        energy_ref[0].occupancy_weighted = False   # EC default
        switch.fire_ec_ready()

        assert energy_ref[0].occupancy_weighted is True, (
            "v4.7.2.1: SIGNAL_ENERGY_COORDINATOR_READY must complete deferred restore"
        )
        assert switch._deferred_restore is False, (
            "deferred_restore must be cleared after signal-path restore"
        )

    def test_v4721_occupancy_weighted_survives_restart_via_timer_retry(self):
        """EC NOT available at async_added_to_hass; arrives before 5s timer fires."""
        energy_ref = [None]
        switch = _OccupancyWeightedSwitchMirror(lambda: energy_ref[0])

        switch.async_added_to_hass(_last_state("on"))
        assert switch._deferred_restore is True

        # EC arrives; fire the 5s timer
        energy_ref[0] = _MockEnergy()
        energy_ref[0].occupancy_weighted = False
        delay, cb = switch.scheduled[0]
        assert delay == 5
        cb()

        assert energy_ref[0].occupancy_weighted is True
        assert switch._deferred_restore is False

    def test_v4721_off_state_also_survives_restart(self):
        """Explicitly-set OFF survives restart (deferred path)."""
        energy_ref = [None]
        switch = _OccupancyWeightedSwitchMirror(lambda: energy_ref[0])

        switch.async_added_to_hass(_last_state("off"))
        assert switch._deferred_restore is True
        assert switch._deferred_value is False

        energy_ref[0] = _MockEnergy()
        energy_ref[0].occupancy_weighted = True   # seed / previous value
        switch.fire_ec_ready()

        assert energy_ref[0].occupancy_weighted is False, (
            "deferred OFF restore must set occupancy_weighted=False even when seed is True"
        )

    def test_v4721_first_install_leaves_default(self):
        """last_state=None (first install) — constructor seed (False) is truth."""
        energy = _MockEnergy()
        energy.occupancy_weighted = False
        switch = _OccupancyWeightedSwitchMirror(lambda: energy)

        switch.async_added_to_hass(None)

        assert energy.occupancy_weighted is False
        assert switch._deferred_restore is False
        assert switch.scheduled == []
