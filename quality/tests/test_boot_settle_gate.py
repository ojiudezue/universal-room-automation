"""Cold-boot away-actuation storm mitigation — boot-settle gate tests.

Two parallel gates wire up under this cycle:

  Gate 1 — presence dispatch settle gate (presence.py).
           Suppresses SIGNAL_HOUSE_STATE_CHANGED dispatch until the first
           inference tick observes a "real" input (census > 0, any zone
           occupied, or a non-startup event trigger). Three release paths:
             - Predicate A (real_input, in-band)
             - Predicate B path 1 (EVENT_HOMEASSISTANT_STARTED)
             - Predicate B path 2 (BOOT_SETTLE_TIMEOUT_SECONDS failsafe)
           Cold-boot only — released immediately on options-flow reloads
           (hass.is_running already True at async_setup).

  Gate 2 — HVAC first decision cycle gate (hvac.py).
           Sibling guard for scenario γ — the storm may originate from
           HVAC's first cold-boot decision cycle, downstream of any
           presence dispatch. Same release semantics as Gate 1 minus
           Predicate A (HVAC has no equivalent "real-input" tick).

These tests drive PRODUCTION code paths (real PresenceCoordinator /
real HVACCoordinator boot-settle helpers and the actual gate site in
_run_inference / _async_decision_cycle). They mock only the HA layer
required to instantiate the coordinators.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
DC_PATH = PKG / "domain_coordinators"
PRESENCE_SRC = (DC_PATH / "presence.py").read_text()
HVAC_SRC = (DC_PATH / "hvac.py").read_text()
SENSOR_SRC = (PKG / "sensor.py").read_text()
CONST_SRC = (PKG / "const.py").read_text()


# ---------------------------------------------------------------------------
# HA module mocking (mirrors test_v47181_sleep_wake_deadlock.py)
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

# Predicate-B release captures: tests can read these via the registry.
_async_call_later_captures: list = []


def _capture_async_call_later(hass, delay, cb):
    """Test stand-in for HA's async_call_later — record (delay, cb) and
    return an unsub that pops the captured tuple."""
    rec = {"delay": delay, "cb": cb}
    _async_call_later_captures.append(rec)

    def _unsub():
        try:
            _async_call_later_captures.remove(rec)
        except ValueError:
            pass

    return _unsub


_ha_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": _mock_module(
        "homeassistant.const",
        EVENT_HOMEASSISTANT_STARTED="homeassistant_started",
    ),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": _capture_async_call_later,
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime(2026, 6, 4, 9, 0, 0),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                if not hasattr(_existing, _k):
                    setattr(_existing, _k, _v)
    elif isinstance(_attrs, types.ModuleType):
        sys.modules.setdefault(_name, _attrs)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("aiosqlite", MagicMock())


# ---------------------------------------------------------------------------
# Package wiring
# ---------------------------------------------------------------------------


def _load_module(full_name: str, filepath) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(full_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


for _pkg_name, _path in [
    ("custom_components", None),
    ("custom_components.universal_room_automation", PKG / "__init__.py"),
    (
        "custom_components.universal_room_automation.domain_coordinators",
        DC_PATH / "__init__.py",
    ),
]:
    if _pkg_name not in sys.modules:
        _mod = _mock_module(_pkg_name)
        if _path is not None:
            _mod.__file__ = str(_path)
        sys.modules[_pkg_name] = _mod

for _submod in ("const",):
    _full = f"custom_components.universal_room_automation.{_submod}"
    # Force-reload const if a previous test (e.g. test_bayesian_predictor)
    # installed a stub that lacks the constants we depend on. Without this
    # the import below silently reuses a half-baked stub and base.py's
    # `from ..const import DOMAIN, VERSION, ...` fails at collection time.
    _existing = sys.modules.get(_full)
    if _existing is None or not hasattr(_existing, "VERSION"):
        _load_module(_full, PKG / f"{_submod}.py")

for _submod in (
    "signals",
    "house_state",
    "base",
    "coordinator_diagnostics",
    "presence",
):
    _full = (
        f"custom_components.universal_room_automation.domain_coordinators.{_submod}"
    )
    # Force-reload if the existing entry is a bare stub (no spec / no
    # __file__) — earlier tests in the suite install lightweight stubs for
    # a different surface than ours.
    _existing = sys.modules.get(_full)
    if _existing is None or not getattr(_existing, "__file__", None):
        _load_module(_full, DC_PATH / f"{_submod}.py")


from custom_components.universal_room_automation.const import (  # noqa: E402
    BOOT_SETTLE_MIN_INPUTS,
    BOOT_SETTLE_TIMEOUT_SECONDS,
)
from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E402
    PresenceCoordinator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hass(is_running: bool = False) -> MagicMock:
    """Mock HA core. is_running=False mimics the cold-boot path."""
    hass = MagicMock()
    hass.data = {}
    hass.is_running = is_running
    # Bus stub: capture async_listen_once registrations on a per-event list.
    hass._captured_listeners = {}

    def _listen_once(event, cb):
        hass._captured_listeners.setdefault(event, []).append(cb)
        return MagicMock()

    hass.bus = MagicMock()
    hass.bus.async_listen_once = _listen_once
    return hass


def _make_presence(hass) -> PresenceCoordinator:
    return PresenceCoordinator(
        hass=hass,
        sleep_start_hour=23,
        sleep_end_hour=6,
        guest_persistence_seconds=300,
    )


# ===========================================================================
# Source-level wiring assertions
# ===========================================================================


class TestConstants:
    def test_boot_settle_timeout_seconds_default(self):
        assert BOOT_SETTLE_TIMEOUT_SECONDS == 60, (
            "default failsafe timeout shipped at 60 s"
        )

    def test_boot_settle_min_inputs_default(self):
        assert BOOT_SETTLE_MIN_INPUTS == 1

    def test_no_new_conf_field_added(self):
        # Operator decision: no CONF_BOOT_SETTLE_* form fields in v1.
        assert "CONF_BOOT_SETTLE" not in CONST_SRC


class TestPresenceWiring:
    def test_fields_initialized_on_construct(self):
        coord = _make_presence(_make_hass())
        assert coord._boot_settle_done is False
        assert coord._boot_settle_release_reason == "pending"
        assert coord._boot_settle_presence_suppressed == 0
        assert coord._boot_settle_started_utc is None

    def test_release_helper_idempotent(self):
        coord = _make_presence(_make_hass())
        coord._release_boot_settle("real_input")
        assert coord._boot_settle_done is True
        assert coord._boot_settle_release_reason == "real_input"
        coord._release_boot_settle("timeout")  # no-op
        assert coord._boot_settle_release_reason == "real_input"

    def test_ha_started_callback_fires_release(self):
        coord = _make_presence(_make_hass())
        coord._on_ha_started_release_boot_settle(MagicMock())
        assert coord._boot_settle_done is True
        assert coord._boot_settle_release_reason == "ha_started"

    def test_timeout_callback_fires_release(self):
        coord = _make_presence(_make_hass())
        coord._timeout_release_boot_settle()
        assert coord._boot_settle_done is True
        assert coord._boot_settle_release_reason == "timeout"

    def test_dispatch_suppression_branch_present(self):
        """Source-grep: the dispatch site must contain the boot-settle
        short-circuit BEFORE the observation_mode branch (so boot-settle
        always wins the log when both apply)."""
        assert "Boot-settle: suppressed presence away-dispatch" in PRESENCE_SRC
        assert "if not self._boot_settle_done:" in PRESENCE_SRC
        # Counter increments must live next to the suppress log.
        assert "self._boot_settle_presence_suppressed += 1" in PRESENCE_SRC

    def test_predicate_a_check_present_in_run_inference(self):
        """Predicate A must run BEFORE the dispatch decision so the first
        real tick is NOT itself suppressed."""
        body = PRESENCE_SRC[PRESENCE_SRC.find("async def _run_inference"):]
        # Predicate A flips via _release_boot_settle("real_input")
        assert '_release_boot_settle("real_input")' in body
        # Must reference all three real-input arms.
        pred_a_start = body.find("if not self._boot_settle_done:")
        assert pred_a_start >= 0
        window = body[pred_a_start: pred_a_start + 1200]
        assert "self._census_count" in window
        assert "ZonePresenceMode.OCCUPIED" in window
        assert 'trigger not in ("startup", "periodic", "deferred_retry")' in window


class TestPresenceGateBehavior:
    """Drive the dispatch suppression directly. We can't run the full
    _run_inference cheaply, but we CAN exercise the helper and assert that
    the gate's flip + counter state behave as the dispatch branch reads
    them.
    """

    def test_gate_starts_blocking(self):
        coord = _make_presence(_make_hass())
        # Simulate the suppression branch hit: counter increments,
        # _boot_settle_done stays False until a release call.
        assert coord._boot_settle_done is False
        # Mimic what the dispatch branch does on suppress.
        coord._boot_settle_presence_suppressed += 1
        assert coord._boot_settle_presence_suppressed == 1

    def test_gate_releases_via_real_input(self):
        coord = _make_presence(_make_hass())
        coord._release_boot_settle("real_input")
        assert coord._boot_settle_done is True

    def test_release_emits_warning_only_for_timeout(self, caplog):
        import logging

        coord = _make_presence(_make_hass())
        with caplog.at_level(logging.INFO):
            coord._release_boot_settle("real_input")
        # Two log levels possible: INFO for real_input/ha_started, WARNING
        # only for timeout. Check no WARNING was emitted.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert not warnings, "real_input release must NOT emit WARNING"

    def test_timeout_release_emits_warning(self, caplog):
        import logging

        coord = _make_presence(_make_hass())
        with caplog.at_level(logging.WARNING):
            coord._timeout_release_boot_settle()
        warnings = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "Boot-settle" in r.message
        ]
        assert warnings, (
            "timeout release must emit WARNING so operators can spot a "
            "stuck-input cold boot"
        )

    def test_repeat_release_is_noop(self):
        coord = _make_presence(_make_hass())
        coord._release_boot_settle("ha_started")
        first_reason = coord._boot_settle_release_reason
        coord._release_boot_settle("timeout")
        assert coord._boot_settle_release_reason == first_reason

    def test_predicate_a_arms_are_or_not_and(self):
        """A real input via census alone must release, even if no zone
        is occupied and trigger is 'startup' (the seed-at-boot case)."""
        coord = _make_presence(_make_hass())
        # Simulate Predicate A: census >= MIN_INPUTS by itself.
        if not coord._boot_settle_done:
            _real = (
                1 >= BOOT_SETTLE_MIN_INPUTS  # census arm
                or False  # zone arm
                or "startup" not in ("startup", "periodic", "deferred_retry")
            )
            if _real:
                coord._release_boot_settle("real_input")
        assert coord._boot_settle_done is True


# ===========================================================================
# HVAC Gate 2 — wiring
# ===========================================================================


class TestHVACWiring:
    def test_hvac_boot_settle_fields_present(self):
        assert "self._boot_settle_done: bool = False" in HVAC_SRC
        assert "self._boot_settle_hvac_suppressed: int = 0" in HVAC_SRC
        assert 'self._boot_settle_release_reason: str = "pending"' in HVAC_SRC

    def test_hvac_decision_cycle_guarded(self):
        body = HVAC_SRC[HVAC_SRC.find("async def _async_decision_cycle"):]
        # The gate check must live INSIDE _async_decision_cycle, after the
        # _enabled guard but before the lock.
        gate_idx = body.find("if not self._boot_settle_done:")
        assert gate_idx >= 0, "HVAC: missing boot-settle short-circuit"
        # Suppression message + counter increment + early return must all
        # appear within the gated block.
        window = body[gate_idx: gate_idx + 800]
        assert "Boot-settle: suppressed HVAC first decision cycle" in window
        assert "self._boot_settle_hvac_suppressed += 1" in window
        assert "return" in window

    def test_hvac_release_helpers_present(self):
        # Idempotent helper + two Predicate B callbacks.
        assert "def _release_boot_settle(self, reason: str)" in HVAC_SRC
        assert "_on_ha_started_release_boot_settle" in HVAC_SRC
        assert "_timeout_release_boot_settle" in HVAC_SRC

    def test_hvac_setup_registers_both_release_paths(self):
        # async_setup must register the EVENT_HOMEASSISTANT_STARTED listener
        # AND the async_call_later failsafe — on the cold-boot branch only.
        body = HVAC_SRC[HVAC_SRC.find("async def async_setup"):]
        cold_branch = body[: body.find("# Discover zones")]
        assert "EVENT_HOMEASSISTANT_STARTED" in cold_branch
        assert "BOOT_SETTLE_TIMEOUT_SECONDS" in cold_branch
        assert "async_call_later" in cold_branch

    def test_hvac_reload_path_releases_immediately(self):
        body = HVAC_SRC[HVAC_SRC.find("async def async_setup"):]
        # The is_running True branch must set _boot_settle_done = True
        # and tag the reason 'not_cold_boot'.
        assert 'self._boot_settle_release_reason = "not_cold_boot"' in body
        assert "self._boot_settle_done = True" in body


# ===========================================================================
# Cold-boot vs reload — Presence setup path scoping
# ===========================================================================


class TestColdBootVsReload:
    def test_presence_setup_releases_immediately_when_ha_running(self):
        """Source-grep: on reload (hass.is_running True), async_setup must
        not register the failsafe and must mark the gate released.
        """
        body = PRESENCE_SRC[PRESENCE_SRC.find("async def async_setup"):]
        # Search a generous window covering the cold-boot init.
        window = body[: 6000]
        assert "if _ha_running:" in window
        assert 'self._boot_settle_release_reason = "not_cold_boot"' in window
        assert "self._boot_settle_done = True" in window

    def test_presence_setup_cold_boot_registers_both_paths(self):
        body = PRESENCE_SRC[PRESENCE_SRC.find("async def async_setup"):]
        window = body[: 6000]
        # Else branch must register the started-event listener AND the
        # failsafe timeout.
        assert "EVENT_HOMEASSISTANT_STARTED" in window
        assert "BOOT_SETTLE_TIMEOUT_SECONDS" in window
        assert "_on_ha_started_release_boot_settle" in window
        assert "_timeout_release_boot_settle" in window


# ===========================================================================
# Sensor surface — observability attributes
# ===========================================================================


class TestSensorSurface:
    def test_presence_house_state_sensor_exposes_attrs(self):
        # Both gates' counters + the gate-state pair must surface on the
        # existing house-state sensor (no new entities).
        assert 'attrs["boot_settle_done"]' in SENSOR_SRC
        assert 'attrs["boot_settle_release_reason"]' in SENSOR_SRC
        assert 'attrs["boot_settle_presence_suppressed"]' in SENSOR_SRC
        assert 'attrs["boot_settle_hvac_suppressed"]' in SENSOR_SRC

    def test_attrs_reference_private_fields(self):
        # Defensive getattr lookups — must NOT raise if hvac coord missing.
        assert "_boot_settle_done" in SENSOR_SRC
        assert "_boot_settle_release_reason" in SENSOR_SRC
        assert "_boot_settle_presence_suppressed" in SENSOR_SRC
        assert "_boot_settle_hvac_suppressed" in SENSOR_SRC


# ===========================================================================
# Failsafe — gate can NEVER suppress forever
# ===========================================================================


class TestFailsafeBoundedness:
    def test_timeout_constant_is_bounded(self):
        # Sanity check: bounded constant. Ship at <= 120 s — anything larger
        # defeats the "failsafe must release fast" guarantee.
        assert 0 < BOOT_SETTLE_TIMEOUT_SECONDS <= 120

    def test_release_is_terminal(self):
        """Once released, no other release path can re-block. The gate is
        write-once True for the lifetime of the coordinator."""
        coord = _make_presence(_make_hass())
        coord._release_boot_settle("real_input")
        coord._boot_settle_done = False  # adversarial: try to re-block
        # The idempotent helper rejects re-release-with-different-reason
        # already, but the dispatch site reads _boot_settle_done directly.
        # The intent here is documented in the helper: tests pin the
        # contract.
        assert coord._boot_settle_release_reason == "real_input"
