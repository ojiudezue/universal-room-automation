"""v4.7.3.1: HVAC bespoke switches deferred-restore hotfix (Bug Class #5).

Root cause: 3 bespoke HVAC (SwitchEntity, RestoreEntity) switches lacked a
deferred-restore mechanism. If the HVAC coordinator was not yet registered in
hass.data["coordinator_manager"] when async_added_to_hass fired, the switch
silently dropped the restored value — next time the HVAC coord ran a decision
cycle, the backing attribute was at its constructor default (e.g. ON for
Override Arrester), not the user-saved value.

Bug class #5 (startup race) pattern — same root cause as the v4.7.2.1 fix for
occupancy-weighted switches, and the v4.5.3 fix for EC sub-switches.

Fix:
  - SIGNAL_HVAC_COORDINATOR_READY constant added to signals.py.
  - HVACCoordinator.async_setup() dispatches the signal at the end of setup.
  - Three bespoke switches subscribe to the signal via async_dispatcher_connect
    (unsub tracked via async_on_remove — Bug Class #38).
  - Each switch implements fast-path (coord ready immediately) and deferred-path
    (coord arrives via signal) restore.
  - _handle_hvac_ready uses @callback (not async, not lambda — Bug Class #42/#19).

Affected switches:
  - HVACGuestModeActuationSwitch (backing: hvac._guest_mode_actuation_enabled)
  - HVACOverrideArresterSwitch (backing: hvac.override_arrester.enabled)
  - HVACACRampMasterSwitch (backing: hvac._override_arrester.ramp_master_enabled,
    accessed via _get_arrester() — structural quirk of this class)

Mirror-style tests (the bespoke switch bodies can't be cleanly imported without
HA core; mirrors the v4.5.3 pattern in test_v4503_ec_switch_restore.py).
"""

import ast
import os
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers / mock objects
# ---------------------------------------------------------------------------

SWITCH_PY_PATH = os.path.join(
    "custom_components", "universal_room_automation", "switch.py"
)
SIGNALS_PY_PATH = os.path.join(
    "custom_components",
    "universal_room_automation",
    "domain_coordinators",
    "signals.py",
)
HVAC_PY_PATH = os.path.join(
    "custom_components",
    "universal_room_automation",
    "domain_coordinators",
    "hvac.py",
)


def _make_last_state(state: str) -> MagicMock:
    return MagicMock(state=state)


class _MockOverrideArrester:
    """Stand-in for OverrideArrester."""

    def __init__(self):
        self.enabled = True
        self._ramp_master_enabled = False

    @property
    def ramp_master_enabled(self) -> bool:
        return self._ramp_master_enabled

    @ramp_master_enabled.setter
    def ramp_master_enabled(self, value: bool) -> None:
        self._ramp_master_enabled = value


class _MockHVAC:
    """Stand-in for HVACCoordinator."""

    def __init__(self):
        self._guest_mode_actuation_enabled = True
        self._override_arrester = _MockOverrideArrester()

    @property
    def override_arrester(self) -> _MockOverrideArrester:
        return self._override_arrester


# ---------------------------------------------------------------------------
# Mirror of HVACGuestModeActuationSwitch restore logic
# ---------------------------------------------------------------------------

class _GuestModeActuationMirror:
    """Mirror of HVACGuestModeActuationSwitch restore lifecycle.

    Reflects the v4.7.3.1 fast-path + deferred-path pattern for
    hvac._guest_mode_actuation_enabled.
    """

    def __init__(self, get_hvac):
        self._get_hvac = get_hvac
        self._deferred_value = None
        self._signal_callbacks = []  # subscriptions registered on add

    def _async_on_remove_connect(self, callback_fn):
        self._signal_callbacks.append(callback_fn)

    def async_added_to_hass(self, last_state):
        # Subscribe to SIGNAL_HVAC_COORDINATOR_READY (tracked via async_on_remove).
        self._async_on_remove_connect(self._handle_hvac_ready)

        if last_state is None or last_state.state not in ("on", "off"):
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._guest_mode_actuation_enabled = target
            self._deferred_value = None
            return
        self._deferred_value = target

    def _handle_hvac_ready(self):
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            return
        hvac._guest_mode_actuation_enabled = self._deferred_value
        self._deferred_value = None

    def async_turn_on(self):
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._guest_mode_actuation_enabled = True
            self._deferred_value = None

    def async_turn_off(self):
        hvac = self._get_hvac()
        if hvac is not None:
            hvac._guest_mode_actuation_enabled = False
            self._deferred_value = None


# ---------------------------------------------------------------------------
# Mirror of HVACOverrideArresterSwitch restore logic
# ---------------------------------------------------------------------------

class _OverrideArresterMirror:
    """Mirror of HVACOverrideArresterSwitch restore lifecycle.

    Backing field: hvac.override_arrester.enabled.
    """

    def __init__(self, get_hvac):
        self._get_hvac = get_hvac
        self._deferred_value = None
        self._signal_callbacks = []

    def _async_on_remove_connect(self, callback_fn):
        self._signal_callbacks.append(callback_fn)

    def async_added_to_hass(self, last_state):
        self._async_on_remove_connect(self._handle_hvac_ready)

        if last_state is None:
            return
        target = last_state.state == "on"
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.enabled = target
            self._deferred_value = None
            return
        self._deferred_value = target

    def _handle_hvac_ready(self):
        if self._deferred_value is None:
            return
        hvac = self._get_hvac()
        if hvac is None:
            return
        hvac.override_arrester.enabled = self._deferred_value
        self._deferred_value = None

    def async_turn_on(self):
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.enabled = True
            self._deferred_value = None

    def async_turn_off(self):
        hvac = self._get_hvac()
        if hvac is not None:
            hvac.override_arrester.enabled = False
            self._deferred_value = None


# ---------------------------------------------------------------------------
# Mirror of HVACACRampMasterSwitch restore logic
# ---------------------------------------------------------------------------

class _ACRampMasterMirror:
    """Mirror of HVACACRampMasterSwitch restore lifecycle.

    Backing field: hvac._override_arrester.ramp_master_enabled (property
    setter), accessed via _get_arrester() — consistent with the production
    switch's structural quirk (no _get_hvac() on this class).
    """

    def __init__(self, get_arrester):
        self._get_arrester = get_arrester
        self._deferred_value = None
        self._signal_callbacks = []

    def _async_on_remove_connect(self, callback_fn):
        self._signal_callbacks.append(callback_fn)

    def async_added_to_hass(self, last_state):
        self._async_on_remove_connect(self._handle_hvac_ready)

        if last_state is None:
            return
        target = last_state.state == "on"
        arr = self._get_arrester()
        if arr is not None:
            arr.ramp_master_enabled = target
            self._deferred_value = None
            return
        self._deferred_value = target

    def _handle_hvac_ready(self):
        if self._deferred_value is None:
            return
        arr = self._get_arrester()
        if arr is None:
            return
        arr.ramp_master_enabled = self._deferred_value
        self._deferred_value = None

    def async_turn_on(self):
        arr = self._get_arrester()
        if arr is not None:
            arr.ramp_master_enabled = True
            self._deferred_value = None

    def async_turn_off(self):
        arr = self._get_arrester()
        if arr is not None:
            arr.ramp_master_enabled = False
            self._deferred_value = None


# ---------------------------------------------------------------------------
# Tests: signal constant + dispatch site
# ---------------------------------------------------------------------------

class TestSignalInfrastructure:
    """Static checks for SIGNAL_HVAC_COORDINATOR_READY constant and dispatch."""

    def test_v4731_signal_hvac_coordinator_ready_constant_exists(self):
        """SIGNAL_HVAC_COORDINATOR_READY must be defined in signals.py."""
        with open(SIGNALS_PY_PATH) as f:
            source = f.read()
        assert "SIGNAL_HVAC_COORDINATOR_READY" in source, (
            "signals.py must define SIGNAL_HVAC_COORDINATOR_READY"
        )
        assert '"ura_hvac_coordinator_ready"' in source, (
            "constant value must be 'ura_hvac_coordinator_ready'"
        )

    def test_v4731_signal_dispatched_from_hvac_coordinator(self):
        """hvac.py must dispatch SIGNAL_HVAC_COORDINATOR_READY via async_dispatcher_send."""
        with open(HVAC_PY_PATH) as f:
            source = f.read()
        assert "SIGNAL_HVAC_COORDINATOR_READY" in source, (
            "hvac.py must import and dispatch SIGNAL_HVAC_COORDINATOR_READY"
        )
        assert "async_dispatcher_send(self.hass, SIGNAL_HVAC_COORDINATOR_READY)" in source, (
            "hvac.py must call async_dispatcher_send(self.hass, SIGNAL_HVAC_COORDINATOR_READY)"
        )

    def test_v4731_dispatch_is_after_setup_complete_log(self):
        """Dispatch must come after 'HVAC Coordinator: setup complete' log line."""
        with open(HVAC_PY_PATH) as f:
            source = f.read()
        setup_complete_pos = source.find('"HVAC Coordinator: setup complete"')
        dispatch_pos = source.find("async_dispatcher_send(self.hass, SIGNAL_HVAC_COORDINATOR_READY)")
        assert setup_complete_pos > 0, "setup complete log must exist"
        assert dispatch_pos > setup_complete_pos, (
            "SIGNAL_HVAC_COORDINATOR_READY dispatch must come after setup_complete log"
        )


# ---------------------------------------------------------------------------
# Tests: HVACGuestModeActuationSwitch
# ---------------------------------------------------------------------------

class TestHVACGuestModeActuationSwitchRestore:
    """Deferred-restore tests for HVACGuestModeActuationSwitch."""

    def test_v4731_guest_mode_fast_path_restore_when_coord_present(self):
        """HVAC coord registered before async_added_to_hass → restore lands immediately."""
        hvac = _MockHVAC()
        hvac._guest_mode_actuation_enabled = True  # running state
        switch = _GuestModeActuationMirror(lambda: hvac)

        switch.async_added_to_hass(_make_last_state("off"))

        assert hvac._guest_mode_actuation_enabled is False, (
            "fast path must apply restored value immediately"
        )
        assert switch._deferred_value is None, "no deferred value after fast path"

    def test_v4731_guest_mode_deferred_restore_via_signal(self):
        """HVAC coord NOT registered at async_added_to_hass → restore via signal."""
        hvac_ref = [None]
        switch = _GuestModeActuationMirror(lambda: hvac_ref[0])

        switch.async_added_to_hass(_make_last_state("off"))

        # Coord not ready yet — should be deferred.
        assert switch._deferred_value is False
        # Coord arrives.
        hvac_ref[0] = _MockHVAC()
        hvac_ref[0]._guest_mode_actuation_enabled = True
        # Signal fires.
        switch._handle_hvac_ready()

        assert hvac_ref[0]._guest_mode_actuation_enabled is False, (
            "deferred restore must apply value when signal fires"
        )
        assert switch._deferred_value is None, "deferred value cleared after restore"

    def test_v4731_guest_mode_off_state_also_survives_restart(self):
        """last_state OFF (symmetric case) — both ON and OFF must survive."""
        hvac = _MockHVAC()
        hvac._guest_mode_actuation_enabled = True
        switch = _GuestModeActuationMirror(lambda: hvac)

        switch.async_added_to_hass(_make_last_state("off"))
        assert hvac._guest_mode_actuation_enabled is False

    def test_v4731_guest_mode_on_state_survives_restart(self):
        """last_state ON — value restored to True."""
        hvac = _MockHVAC()
        hvac._guest_mode_actuation_enabled = False
        switch = _GuestModeActuationMirror(lambda: hvac)

        switch.async_added_to_hass(_make_last_state("on"))
        assert hvac._guest_mode_actuation_enabled is True

    def test_v4731_guest_mode_no_prior_state_is_noop(self):
        """last_state None → no restore; running state untouched."""
        hvac = _MockHVAC()
        hvac._guest_mode_actuation_enabled = True
        switch = _GuestModeActuationMirror(lambda: hvac)

        switch.async_added_to_hass(None)

        assert hvac._guest_mode_actuation_enabled is True
        assert switch._deferred_value is None

    def test_v4731_guest_mode_signal_registered_unconditionally(self):
        """Signal subscription must be registered even when coord is available."""
        hvac = _MockHVAC()
        switch = _GuestModeActuationMirror(lambda: hvac)

        switch.async_added_to_hass(_make_last_state("on"))

        # Subscription must have been registered (async_on_remove pair).
        assert len(switch._signal_callbacks) == 1

    def test_v4731_guest_mode_deferred_value_none_when_signal_is_noop(self):
        """If no deferred value, _handle_hvac_ready is a safe no-op."""
        hvac = _MockHVAC()
        switch = _GuestModeActuationMirror(lambda: hvac)
        switch._deferred_value = None  # already None (fast path or no state)

        # Should not raise; coord attr untouched.
        original = hvac._guest_mode_actuation_enabled
        switch._handle_hvac_ready()
        assert hvac._guest_mode_actuation_enabled == original


# ---------------------------------------------------------------------------
# Tests: HVACOverrideArresterSwitch
# ---------------------------------------------------------------------------

class TestHVACOverrideArresterSwitchRestore:
    """Deferred-restore tests for HVACOverrideArresterSwitch."""

    def test_v4731_arrester_fast_path_restore_when_coord_present(self):
        """HVAC coord registered before async_added_to_hass → restore lands immediately."""
        hvac = _MockHVAC()
        hvac.override_arrester.enabled = True
        switch = _OverrideArresterMirror(lambda: hvac)

        switch.async_added_to_hass(_make_last_state("off"))

        assert hvac.override_arrester.enabled is False
        assert switch._deferred_value is None

    def test_v4731_arrester_deferred_restore_via_signal(self):
        """HVAC coord NOT registered at async_added_to_hass → restore via signal."""
        hvac_ref = [None]
        switch = _OverrideArresterMirror(lambda: hvac_ref[0])

        switch.async_added_to_hass(_make_last_state("off"))
        assert switch._deferred_value is False

        hvac_ref[0] = _MockHVAC()
        hvac_ref[0].override_arrester.enabled = True
        switch._handle_hvac_ready()

        assert hvac_ref[0].override_arrester.enabled is False
        assert switch._deferred_value is None

    def test_v4731_arrester_off_state_also_survives_restart(self):
        """OFF state restored correctly (symmetric)."""
        hvac = _MockHVAC()
        hvac.override_arrester.enabled = True
        switch = _OverrideArresterMirror(lambda: hvac)

        switch.async_added_to_hass(_make_last_state("off"))
        assert hvac.override_arrester.enabled is False

    def test_v4731_arrester_on_state_survives_restart(self):
        """ON state restored correctly."""
        hvac = _MockHVAC()
        hvac.override_arrester.enabled = False
        switch = _OverrideArresterMirror(lambda: hvac)

        switch.async_added_to_hass(_make_last_state("on"))
        assert hvac.override_arrester.enabled is True

    def test_v4731_arrester_no_prior_state_is_noop(self):
        """last_state None → no restore."""
        hvac = _MockHVAC()
        switch = _OverrideArresterMirror(lambda: hvac)

        switch.async_added_to_hass(None)

        assert switch._deferred_value is None

    def test_v4731_arrester_signal_registered_unconditionally(self):
        """Signal subscription registered even when coord present."""
        hvac = _MockHVAC()
        switch = _OverrideArresterMirror(lambda: hvac)

        switch.async_added_to_hass(_make_last_state("on"))
        assert len(switch._signal_callbacks) == 1


# ---------------------------------------------------------------------------
# Tests: HVACACRampMasterSwitch
# ---------------------------------------------------------------------------

class TestHVACACRampMasterSwitchRestore:
    """Deferred-restore tests for HVACACRampMasterSwitch.

    Structural note: HVACACRampMasterSwitch uses _get_arrester() (not _get_hvac())
    because the backing field lives on hvac._override_arrester. _handle_hvac_ready
    must also use _get_arrester() — verified by the source-mirror contract test.
    """

    def test_v4731_ramp_master_fast_path_restore_when_coord_present(self):
        """Arrester present before async_added_to_hass → restore lands immediately."""
        arr = _MockOverrideArrester()
        arr._ramp_master_enabled = False
        switch = _ACRampMasterMirror(lambda: arr)

        switch.async_added_to_hass(_make_last_state("on"))

        assert arr.ramp_master_enabled is True
        assert switch._deferred_value is None

    def test_v4731_ramp_master_deferred_restore_via_signal(self):
        """Arrester NOT ready at async_added_to_hass → restore via signal."""
        arr_ref = [None]
        switch = _ACRampMasterMirror(lambda: arr_ref[0])

        switch.async_added_to_hass(_make_last_state("on"))
        assert switch._deferred_value is True

        arr_ref[0] = _MockOverrideArrester()
        arr_ref[0]._ramp_master_enabled = False
        switch._handle_hvac_ready()

        assert arr_ref[0].ramp_master_enabled is True
        assert switch._deferred_value is None

    def test_v4731_ramp_master_off_state_also_survives_restart(self):
        """OFF state (default) restored correctly when prior state was ON then turned OFF."""
        arr = _MockOverrideArrester()
        arr._ramp_master_enabled = True
        switch = _ACRampMasterMirror(lambda: arr)

        switch.async_added_to_hass(_make_last_state("off"))
        assert arr.ramp_master_enabled is False
        assert switch._deferred_value is None

    def test_v4731_ramp_master_on_state_survives_restart(self):
        """ON state survives restart (user explicitly opted in)."""
        arr = _MockOverrideArrester()
        arr._ramp_master_enabled = False
        switch = _ACRampMasterMirror(lambda: arr)

        switch.async_added_to_hass(_make_last_state("on"))
        assert arr.ramp_master_enabled is True

    def test_v4731_ramp_master_no_prior_state_is_noop(self):
        """last_state None → default OFF; nothing restored."""
        arr = _MockOverrideArrester()
        arr._ramp_master_enabled = False
        switch = _ACRampMasterMirror(lambda: arr)

        switch.async_added_to_hass(None)

        assert arr._ramp_master_enabled is False
        assert switch._deferred_value is None

    def test_v4731_ramp_master_signal_registered_unconditionally(self):
        """Signal subscription registered even when arrester present."""
        arr = _MockOverrideArrester()
        switch = _ACRampMasterMirror(lambda: arr)

        switch.async_added_to_hass(_make_last_state("on"))
        assert len(switch._signal_callbacks) == 1

    def test_v4731_ramp_master_uses_get_arrester_not_get_hvac(self):
        """Source-mirror contract: _handle_hvac_ready must use _get_arrester()."""
        with open(SWITCH_PY_PATH) as f:
            source = f.read()
        # Find the HVACACRampMasterSwitch class body.
        class_start = source.find("class HVACACRampMasterSwitch")
        assert class_start > 0
        # Find the next class after it (to bound the search).
        next_class = source.find("\nclass ", class_start + 1)
        class_body = source[class_start:next_class] if next_class > 0 else source[class_start:]

        assert "_handle_hvac_ready" in class_body, (
            "HVACACRampMasterSwitch must define _handle_hvac_ready"
        )
        # The handle must call _get_arrester, NOT _get_hvac.
        handle_start = class_body.find("def _handle_hvac_ready")
        assert handle_start > 0
        # Find next method def within the body to bound the handler.
        next_def = class_body.find("\n    def ", handle_start + 1)
        handle_body = (
            class_body[handle_start:next_def] if next_def > 0 else class_body[handle_start:]
        )
        assert "_get_arrester" in handle_body, (
            "_handle_hvac_ready must use _get_arrester() (not _get_hvac())"
        )


# ---------------------------------------------------------------------------
# Source-mirror contract: all 3 switches have required structure
# ---------------------------------------------------------------------------

class TestSourceMirrorContract:
    """Static checks against switch.py production source."""

    @pytest.fixture
    def switch_source(self):
        with open(SWITCH_PY_PATH) as f:
            return f.read()

    def _class_body(self, source: str, class_name: str) -> str:
        start = source.find(f"class {class_name}")
        assert start > 0, f"{class_name} must exist in switch.py"
        next_class = source.find("\nclass ", start + 1)
        return source[start:next_class] if next_class > 0 else source[start:]

    def test_v4731_all_three_switches_have_deferred_value(self, switch_source):
        for cls in (
            "HVACGuestModeActuationSwitch",
            "HVACOverrideArresterSwitch",
            "HVACACRampMasterSwitch",
        ):
            body = self._class_body(switch_source, cls)
            assert "self._deferred_value" in body, (
                f"{cls} must define self._deferred_value"
            )

    def test_v4731_all_three_switches_subscribe_to_hvac_ready_signal(self, switch_source):
        for cls in (
            "HVACGuestModeActuationSwitch",
            "HVACOverrideArresterSwitch",
            "HVACACRampMasterSwitch",
        ):
            body = self._class_body(switch_source, cls)
            assert "SIGNAL_HVAC_COORDINATOR_READY" in body, (
                f"{cls} must subscribe to SIGNAL_HVAC_COORDINATOR_READY"
            )

    def test_v4731_all_three_switches_use_async_on_remove(self, switch_source):
        """Bug Class #38: every async_dispatcher_connect must be paired with async_on_remove."""
        for cls in (
            "HVACGuestModeActuationSwitch",
            "HVACOverrideArresterSwitch",
            "HVACACRampMasterSwitch",
        ):
            body = self._class_body(switch_source, cls)
            assert "async_on_remove" in body, (
                f"{cls} must use async_on_remove to track dispatcher unsub (Bug Class #38)"
            )

    def test_v4731_all_three_handle_hvac_ready_is_callback(self, switch_source):
        """Bug Class #42/#19: _handle_hvac_ready must be a @callback, not a lambda/async."""
        for cls in (
            "HVACGuestModeActuationSwitch",
            "HVACOverrideArresterSwitch",
            "HVACACRampMasterSwitch",
        ):
            body = self._class_body(switch_source, cls)
            assert "_handle_hvac_ready" in body, f"{cls} must define _handle_hvac_ready"
            # @callback decorator must appear before the method.
            handle_pos = body.find("def _handle_hvac_ready")
            # Look backwards from def position for @callback.
            pre = body[max(0, handle_pos - 30):handle_pos]
            assert "@callback" in pre, (
                f"{cls}._handle_hvac_ready must be decorated with @callback"
            )
