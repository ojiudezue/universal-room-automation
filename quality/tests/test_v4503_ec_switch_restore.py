"""v4.5.3 hotfix: EC switch deferred-restore lifecycle race fix.

User-reported bug: arbitrage switch flipped from OFF (user-set yesterday)
back to ON across the v4.5.2 deploy restart, matching the deferred bug
class that the prior `_ec_switch_factory` docstring (switch.py:511-552)
acknowledged but never fixed.

Root cause: the factory's `_retry_restore` had no `_deferred_restore` flag
and only a single 5s retry. If `_get_energy()` was None at both
`async_added_to_hass` AND the 5s callback (CM platform setup still in
flight), the user's persisted toggle was silently lost — and the
EnergyCoordinator constructor's `ec.get(CONF_*_ENABLED, …)` cm_config
seed (which doesn't change when the user toggles via the UI) became the
visible state. All 5 EC switches share this factory, so the bug applied
to arbitrage / grid_import_cap / load_shedding / excess_solar / ev_tou.

v4.5.3 fix:
  - `_deferred_restore` flag set when restore is pending; cleared on
    successful setattr OR when the user explicitly toggles.
  - Retry chain: 5s, 30s, 120s; each callback reschedules the next on
    continued failure.
  - Exhausted retries log a warning so future investigations have signal.
  - User toggle (`async_turn_on/off`) clears `_deferred_restore` so a
    pending retry doesn't stomp the explicit user action.
  - First-install path (`last_state is None`) skips defer entirely; the
    constructor's cm_config seed is the source of truth.

Mirror-style tests (the factory's closure can't be cleanly imported
without HA core; mirrors v4.5.0.4's pattern in test_v4504_blind_tilt.py).
The mirror reflects the production code one-for-one; review keeps them
in sync.
"""

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mirror of the v4.5.3 _ECSwitch closure in switch.py:_ec_switch_factory.
# ---------------------------------------------------------------------------

class _MockEnergy:
    """Stand-in for the real EnergyCoordinator. setattr() works directly."""
    pass


class _ECSwitchMirror:
    """Mirror of the v4.5.3 _ec_switch_factory closure.

    Captures only the deferred-restore lifecycle. async_get_last_state is
    parameterized via a callable; async_call_later is replaced with a
    list of (delay, callback) entries we can drive manually.
    """

    _RETRY_DELAYS_S = (5, 30, 120)

    def __init__(self, attr_name, default, get_energy):
        self._attr_name = attr_name
        self._default = default
        self._get_energy = get_energy
        self._deferred_restore = False
        self._deferred_value = default
        self._retry_index = 0
        self.scheduled = []   # [(delay, callback), …]
        self.warnings = []    # ["EC switch arbitrage: …", …]

    def _async_call_later(self, delay, callback):
        self.scheduled.append((delay, callback))

    def _log_warning(self, msg):
        self.warnings.append(msg)

    @property
    def is_on(self):
        energy = self._get_energy()
        if energy is None:
            return self._default
        return getattr(energy, self._attr_name, self._default)

    def async_turn_on(self):
        energy = self._get_energy()
        if energy is not None:
            setattr(energy, self._attr_name, True)
            self._deferred_restore = False

    def async_turn_off(self):
        energy = self._get_energy()
        if energy is not None:
            setattr(energy, self._attr_name, False)
            self._deferred_restore = False

    def async_added_to_hass(self, last_state):
        if last_state is None:
            return
        target = last_state.state == "on"
        self._deferred_value = target
        energy = self._get_energy()
        if energy is not None:
            setattr(energy, self._attr_name, target)
            self._deferred_restore = False
            return
        self._deferred_restore = True
        self._retry_index = 0
        self._async_call_later(self._RETRY_DELAYS_S[0], self._retry_restore)

    def _retry_restore(self, _now=None):
        if not self._deferred_restore:
            return
        energy = self._get_energy()
        if energy is not None:
            setattr(energy, self._attr_name, self._deferred_value)
            self._deferred_restore = False
            return
        self._retry_index += 1
        if self._retry_index < len(self._RETRY_DELAYS_S):
            self._async_call_later(
                self._RETRY_DELAYS_S[self._retry_index], self._retry_restore
            )
        else:
            self._log_warning(
                f"EC switch arbitrage: deferred restore exhausted retries"
            )
            self._deferred_restore = False


def _make_last_state(state):
    return MagicMock(state=state)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFastPath:
    """Coord ready at async_added_to_hass — restore lands immediately."""

    def test_restore_off_overrides_seed(self):
        energy = _MockEnergy()
        energy.arbitrage_enabled = True   # constructor seed from cm_config
        switch = _ECSwitchMirror("arbitrage_enabled", False, lambda: energy)

        switch.async_added_to_hass(_make_last_state("off"))

        assert energy.arbitrage_enabled is False, (
            "RestoreEntity 'off' must override constructor seed True"
        )
        assert switch._deferred_restore is False
        assert switch.scheduled == [], "no retry should be scheduled when fast path lands"

    def test_restore_on_overrides_seed(self):
        energy = _MockEnergy()
        energy.arbitrage_enabled = False
        switch = _ECSwitchMirror("arbitrage_enabled", False, lambda: energy)

        switch.async_added_to_hass(_make_last_state("on"))

        assert energy.arbitrage_enabled is True
        assert switch._deferred_restore is False

    def test_first_install_no_restore_state(self):
        """last_state=None → no override; constructor seed is truth."""
        energy = _MockEnergy()
        energy.arbitrage_enabled = True   # what the cm_config seeded
        switch = _ECSwitchMirror("arbitrage_enabled", False, lambda: energy)

        switch.async_added_to_hass(None)

        assert energy.arbitrage_enabled is True, (
            "first-install path must leave constructor seed alone"
        )
        assert switch._deferred_restore is False
        assert switch.scheduled == []


class TestDeferredPath:
    """Coord not ready at async_added_to_hass — must defer + retry."""

    def test_defer_when_coord_unavailable(self):
        energy_ref = [None]   # mutable so retry sees coord later
        switch = _ECSwitchMirror(
            "arbitrage_enabled", False, lambda: energy_ref[0]
        )

        switch.async_added_to_hass(_make_last_state("off"))

        assert switch._deferred_restore is True
        assert switch._deferred_value is False
        assert len(switch.scheduled) == 1
        assert switch.scheduled[0][0] == 5

    def test_first_retry_lands_when_coord_now_available(self):
        energy_ref = [None]
        switch = _ECSwitchMirror(
            "arbitrage_enabled", False, lambda: energy_ref[0]
        )
        switch.async_added_to_hass(_make_last_state("off"))

        # CM finishes registering between defer and retry
        energy_ref[0] = _MockEnergy()
        energy_ref[0].arbitrage_enabled = True   # cm_config seed
        delay, cb = switch.scheduled[-1]
        cb()

        assert energy_ref[0].arbitrage_enabled is False
        assert switch._deferred_restore is False
        # No further retry scheduled after success
        assert len(switch.scheduled) == 1

    def test_retry_chain_progresses_until_success(self):
        """First retry None → schedule 30s. Second retry succeeds."""
        energy_ref = [None]
        switch = _ECSwitchMirror(
            "arbitrage_enabled", False, lambda: energy_ref[0]
        )
        switch.async_added_to_hass(_make_last_state("off"))

        # First retry: still None
        switch.scheduled[-1][1]()
        assert switch._deferred_restore is True
        assert len(switch.scheduled) == 2
        assert switch.scheduled[1][0] == 30

        # Coord arrives, second retry succeeds
        energy_ref[0] = _MockEnergy()
        energy_ref[0].arbitrage_enabled = True
        switch.scheduled[-1][1]()

        assert energy_ref[0].arbitrage_enabled is False
        assert switch._deferred_restore is False

    def test_retry_chain_exhaustion_logs_warning(self):
        """All 3 retries fail → warning logged, deferred_restore cleared."""
        energy_ref = [None]
        switch = _ECSwitchMirror(
            "arbitrage_enabled", False, lambda: energy_ref[0]
        )
        switch.async_added_to_hass(_make_last_state("off"))

        # Fire all retries with coord still None
        for _ in range(len(switch._RETRY_DELAYS_S)):
            switch.scheduled[-1][1]()

        # Schedule list is the 3 attempts; no fourth was scheduled.
        assert len(switch.scheduled) == len(switch._RETRY_DELAYS_S)
        assert switch._deferred_restore is False
        assert any("exhausted retries" in w for w in switch.warnings)

    def test_retry_delays_match_5_30_120(self):
        """Spec: retry chain is 5s, 30s, 120s in that order."""
        assert _ECSwitchMirror._RETRY_DELAYS_S == (5, 30, 120)


class TestUserToggleWinsOverPendingRestore:
    """If user explicitly toggles between defer and retry, retry must
    NOT stomp the user's intent."""

    def test_turn_on_clears_pending_restore_off(self):
        energy_ref = [None]
        switch = _ECSwitchMirror(
            "arbitrage_enabled", False, lambda: energy_ref[0]
        )
        switch.async_added_to_hass(_make_last_state("off"))   # defers

        # User toggles ON before retry fires (energy now available)
        energy_ref[0] = _MockEnergy()
        energy_ref[0].arbitrage_enabled = True
        switch.async_turn_on()

        assert energy_ref[0].arbitrage_enabled is True
        assert switch._deferred_restore is False

        # Retry fires; should be a no-op
        switch.scheduled[-1][1]()
        assert energy_ref[0].arbitrage_enabled is True, (
            "pending retry must not overwrite explicit user toggle"
        )

    def test_turn_off_clears_pending_restore_on(self):
        energy_ref = [None]
        switch = _ECSwitchMirror(
            "arbitrage_enabled", False, lambda: energy_ref[0]
        )
        switch.async_added_to_hass(_make_last_state("on"))

        energy_ref[0] = _MockEnergy()
        energy_ref[0].arbitrage_enabled = False
        switch.async_turn_off()

        assert energy_ref[0].arbitrage_enabled is False
        switch.scheduled[-1][1]()
        assert energy_ref[0].arbitrage_enabled is False


class TestSourceMirrorContract:
    """Static checks: production switch.py must implement the contract
    this mirror models. Catches drift before deploy."""

    @pytest.fixture
    def switch_source(self):
        with open("custom_components/universal_room_automation/switch.py") as f:
            return f.read()

    def test_factory_has_deferred_restore_flag(self, switch_source):
        # Locate the factory and assert _deferred_restore is set in __init__
        idx = switch_source.find("def _ec_switch_factory(")
        assert idx > 0, "factory must exist"
        body = switch_source[idx:idx + 6000]
        assert "self._deferred_restore: bool = False" in body, (
            "_ec_switch_factory.__init__ must initialize _deferred_restore"
        )

    def test_factory_has_retry_chain(self, switch_source):
        idx = switch_source.find("def _ec_switch_factory(")
        body = switch_source[idx:idx + 6000]
        assert "_RETRY_DELAYS_S" in body, (
            "factory must define a retry-chain constant"
        )
        # Spec: 5s, 30s, 120s
        assert "5" in body and "30" in body and "120" in body

    def test_factory_retry_clears_flag_on_success(self, switch_source):
        idx = switch_source.find("def _retry_restore", switch_source.find("def _ec_switch_factory("))
        assert idx > 0
        body = switch_source[idx:idx + 1200]
        assert "if not self._deferred_restore:" in body, (
            "_retry_restore must early-return when restore not pending"
        )
        assert "self._deferred_restore = False" in body, (
            "_retry_restore must clear flag after successful setattr"
        )

    def test_factory_user_toggle_clears_pending(self, switch_source):
        # async_turn_on / async_turn_off must clear _deferred_restore
        # so a pending retry doesn't stomp the user.
        for fn_name in ("async_turn_on", "async_turn_off"):
            idx = switch_source.find(
                f"async def {fn_name}",
                switch_source.find("_ec_switch_factory"),
            )
            assert idx > 0, f"{fn_name} must exist in factory"
            body = switch_source[idx:idx + 600]
            assert "self._deferred_restore = False" in body, (
                f"{fn_name} must clear _deferred_restore"
            )
