"""FAN-LAYER-1 Session 3 fix-up (2026-08-11) — W11 + W12 behavioral tests.

C-HIGH-1 + C-HIGH-2 fix-up: prior Session-3 tests exercised the oracle
semantics + a source-presence grep but NEVER drove the production
`_stop_all_fans_safety` / `_activate_zone_fans` code paths. Reviewer C
demonstrated the gap by short-circuiting the loop guard in
_stop_all_fans_safety and neutering W12's oracle.actuate arg (`if False
and verdict.is_allow`) — both mutations left the suite green.

This file closes the gap by loading the real hvac.py / hvac_predict.py
modules through the same importlib harness the v5.68.0 vacancy-sweep
anchor uses, then invokes the real methods with a services.async_call
recorder + an oracle carrying a seeded ledger. Every assertion is about
observable side-effects on the recorder — not source grep.

The harness preamble is a straight port of the vacancy-sweep anchor
(quality/tests/test_hvac_vacancy_sweep_manual_on_guard.py) so the
sys.modules snapshot / restore + `_load_module` guard behavior are
identical and cannot re-introduce the sibling-test pollution the
anchor's harness solved.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# HA module mocking (ported from test_hvac_vacancy_sweep_manual_on_guard.py)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods: dict = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
        "CALLBACK_TYPE": object,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": _mock_module(
        "homeassistant.const",
        SERVICE_TURN_ON="turn_on",
        SERVICE_TURN_OFF="turn_off",
        STATE_ON="on",
        STATE_OFF="off",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
    ),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda *a, **k: (lambda: None),
        "async_call_later": lambda *a, **k: (lambda: None),
        "async_track_point_in_time": lambda *a, **k: (lambda: None),
        "async_track_time_change": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: (lambda: None),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.helpers.storage": {"Store": _mock_cls},
    "homeassistant.util": {},
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
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
    "homeassistant.exceptions": {"HomeAssistantError": Exception},
}

# CAPTURE pre-stub state for keys we're about to install stubs for —
# so the module-level restore block at the bottom can accurately put
# things back. Must happen BEFORE the install loop below (bug fix
# 2026-08-11: capturing AFTER the loop trivially restored our own
# stub, leaving Store visible to sibling tests' _HA_REAL probe).
_MISSING_SENTINEL_LATE = object()
_HA_STORAGE_ORIG = sys.modules.get(
    "homeassistant.helpers.storage", _MISSING_SENTINEL_LATE,
)

for _name, _attrs in _ha_mods.items():
    if _name not in sys.modules:
        if isinstance(_attrs, dict):
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            sys.modules[_name] = _attrs
    else:
        # 2026-08-11 test-isolation fix: sibling harnesses (e.g.
        # _provenance_harness) install a `homeassistant.core` stub that
        # LACKS ``CALLBACK_TYPE`` — hvac_covers.py's module-level
        # ``from homeassistant.core import CALLBACK_TYPE`` then fails.
        # Merge our attrs into any pre-existing stub so the critical
        # symbols are always present.
        if isinstance(_attrs, dict):
            existing_mod = sys.modules[_name]
            for _k, _v in _attrs.items():
                if not hasattr(existing_mod, _k):
                    setattr(existing_mod, _k, _v)

# dt_util shim — parity tests share this pattern.
_dt_mock = _mock_module(
    "homeassistant.util.dt",
    now=datetime.now, utcnow=datetime.utcnow, as_local=lambda dt: dt,
    UTC=timezone.utc,
)
_MISSING = object()
_HA_DT_ORIG = sys.modules.get("homeassistant.util.dt", _MISSING)
sys.modules["homeassistant.util.dt"] = _dt_mock
sys.modules.setdefault("aiosqlite", MagicMock())

# Test-isolation note (2026-08-11 fix-up): the pre-stub snapshot for
# ``homeassistant.helpers.storage`` is captured LATER, BEFORE the
# ``_ha_mods`` install loop (line 112). Capturing here — AFTER
# _dt_mock is installed but that ALSO happens after _ha_mods — would
# trivially preserve the stub we just installed and defeat the
# isolation. See the "_HA_STORAGE_ORIG" capture on line ~120.


_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(
    _project_root, "custom_components", "universal_room_automation",
)


def _load_module(full_name: str, filepath: str) -> types.ModuleType:
    existing = sys.modules.get(full_name)
    if (
        existing is not None
        and isinstance(existing, types.ModuleType)
        and isinstance(getattr(existing, "__file__", None), str)
        and os.path.isfile(existing.__file__)
    ):
        return existing
    spec = importlib.util.spec_from_file_location(full_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "custom_components" not in sys.modules:
    _cc_pkg = _mock_module("custom_components")
    _cc_pkg.__path__ = [os.path.join(_project_root, "custom_components")]
    sys.modules["custom_components"] = _cc_pkg
else:
    _existing_cc = sys.modules["custom_components"]
    if not getattr(_existing_cc, "__path__", None):
        _existing_cc.__path__ = [os.path.join(_project_root, "custom_components")]
if "custom_components.universal_room_automation" not in sys.modules:
    _ura_pkg = _mock_module("custom_components.universal_room_automation")
    _ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
    _ura_pkg.__path__ = [_ura_root]
    sys.modules["custom_components.universal_room_automation"] = _ura_pkg
else:
    _existing_ura = sys.modules["custom_components.universal_room_automation"]
    if not getattr(_existing_ura, "__path__", None):
        _existing_ura.__path__ = [_ura_root]
    if not getattr(_existing_ura, "__file__", None):
        _existing_ura.__file__ = os.path.join(_ura_root, "__init__.py")

_SNAPSHOT_KEYS = [
    "custom_components.universal_room_automation.const",
    "custom_components.universal_room_automation.fan_veto",
    "custom_components.universal_room_automation.domain_coordinators.house_state",
    "custom_components.universal_room_automation.domain_coordinators.signals",
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.base",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_fans",
    "custom_components.universal_room_automation.domain_coordinators.hvac_covers",
    "custom_components.universal_room_automation.domain_coordinators.hvac_egress",
    "custom_components.universal_room_automation.domain_coordinators.hvac_preset",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "custom_components.universal_room_automation.domain_coordinators.hvac_predict",
    "custom_components.universal_room_automation.domain_coordinators.hvac",
    "custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle",
]
_MODULE_SNAPSHOT: dict = {k: sys.modules.get(k, _MISSING) for k in _SNAPSHOT_KEYS}

_load_module(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_root, "const.py"),
)
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc_pkg = _mock_module(
        "custom_components.universal_room_automation.domain_coordinators",
    )
    _dc_pkg.__file__ = os.path.join(
        _ura_root, "domain_coordinators", "__init__.py",
    )
    _dc_pkg.__path__ = [os.path.join(_ura_root, "domain_coordinators")]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc_pkg

_load_module(
    "custom_components.universal_room_automation.domain_coordinators.house_state",
    os.path.join(_ura_root, "domain_coordinators", "house_state.py"),
)
_load_module(
    "custom_components.universal_room_automation.fan_veto",
    os.path.join(_ura_root, "fan_veto.py"),
)

_SIBLING_LOAD_ORDER = [
    ("house_state", "domain_coordinators/house_state.py"),
    ("signals", "domain_coordinators/signals.py"),
    ("hvac_const", "domain_coordinators/hvac_const.py"),
    ("base", "domain_coordinators/base.py"),
    ("fan_policy_oracle", "domain_coordinators/fan_policy_oracle.py"),
    ("hvac_zones", "domain_coordinators/hvac_zones.py"),
    ("hvac_fans", "domain_coordinators/hvac_fans.py"),
    ("hvac_covers", "domain_coordinators/hvac_covers.py"),
    ("hvac_egress", "domain_coordinators/hvac_egress.py"),
    ("hvac_preset", "domain_coordinators/hvac_preset.py"),
    ("hvac_setpoint", "domain_coordinators/hvac_setpoint.py"),
    ("hvac_override", "domain_coordinators/hvac_override.py"),
    ("hvac_predict", "domain_coordinators/hvac_predict.py"),
]
for _leaf, _rel in _SIBLING_LOAD_ORDER:
    _fq = (
        "custom_components.universal_room_automation.domain_coordinators."
        + _leaf
    )
    _load_module(_fq, os.path.join(_ura_root, _rel))

_load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac",
    os.path.join(_ura_root, "domain_coordinators", "hvac.py"),
)

import custom_components.universal_room_automation.domain_coordinators.hvac as _hvac_mod  # noqa: E402
import custom_components.universal_room_automation.domain_coordinators.hvac_predict as _predict_mod  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators.hvac import (  # noqa: E402
    HVACCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_predict import (  # noqa: E402
    HVACPredictor,
)
from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E402
    FanPolicyOracle,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_FANS,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    FAN_TRIGGER_TEMP_ROOM_ON,
)
import custom_components.universal_room_automation.domain_coordinators.hvac_fans as _hvac_fans_mod  # noqa: E402
_FanController = _hvac_fans_mod.FanController
_room_key_fn = _hvac_fans_mod._room_key

# Restore sibling sys.modules entries so we don't pollute later tests.
for _k, _orig in _MODULE_SNAPSHOT.items():
    if _orig is _MISSING:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _orig
if _HA_DT_ORIG is _MISSING:
    sys.modules.pop("homeassistant.util.dt", None)
else:
    sys.modules["homeassistant.util.dt"] = _HA_DT_ORIG

# Restore homeassistant.helpers.storage — sibling tests use it as a
# probe for a REAL HA install (``_HA_REAL = True`` iff ``from
# homeassistant.helpers.storage import Store`` succeeds). We install a
# stub with ``Store=MagicMock`` at import time so hvac.py can load, but
# we MUST NOT leave a stub with a usable ``Store`` attribute in place —
# that would flip sibling test guards from skipped → run and they'd
# fail on the stub DB backing. Install an EMPTY replacement instead
# (module present but without ``Store``) so:
#   * freeze_floor's ``if "homeassistant.helpers.storage" not in sys.modules``
#     skips its own stub-install (module IS present)
#   * ac_ramp's ``from homeassistant.helpers.storage import Store`` fails
#     (AttributeError → ``_HA_REAL = False``) → tests correctly skip
# This preserves the baseline skip behavior without breaking hvac.py's
# already-imported ``Store`` reference (Python caches the class).
if _HA_STORAGE_ORIG is _MISSING_SENTINEL_LATE:
    _empty_storage = types.ModuleType("homeassistant.helpers.storage")
    sys.modules["homeassistant.helpers.storage"] = _empty_storage
else:
    sys.modules["homeassistant.helpers.storage"] = _HA_STORAGE_ORIG

_hvac_dt_util = _hvac_mod.dt_util
_predict_dt_util = _predict_mod.dt_util


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _dt_mock.now = fn
    _dt_mock.utcnow = fn
    _hvac_dt_util.now = fn
    _hvac_dt_util.utcnow = fn
    _predict_dt_util.now = fn
    _predict_dt_util.utcnow = fn


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Stubs shared with the vacancy-sweep anchor pattern
# ---------------------------------------------------------------------------

class _StubEntry:
    def __init__(self, room_name: str, fans: list, entry_id: str):
        self.entry_id = entry_id
        self.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: room_name,
            CONF_FANS: fans,
        }
        self.options: dict = {}


class _StubRoomCoordinator:
    def __init__(self, entry: _StubEntry):
        self.config_entry = entry


class _StubZone:
    def __init__(self, zone_name: str, rooms: list):
        self.zone_name = zone_name
        self.rooms = rooms
        # W12 requires these attrs on the zone.
        self.target_temp_high = 74.0
        self.room_conditions: list = []


class _RoomCondition:
    def __init__(self, room_name: str, temperature: float):
        self.room_name = room_name
        self.temperature = temperature


def _make_hvac_coord(rooms: dict, seeded_oracle: FanPolicyOracle | None = None):
    """Build an HVACCoordinator stub with a services.async_call recorder.

    ``rooms`` — {room_name: {"fan_state": "on"|"off"}}. Every room gets
    a single fan ``fan.<room_lower>``.
    """
    coord = HVACCoordinator.__new__(HVACCoordinator)
    coord._observation_mode = False
    coord._house_state = "day"

    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    if seeded_oracle is not None:
        hass.data[DOMAIN]["fan_oracle"] = seeded_oracle
    log: list[tuple[str, str, dict]] = []

    async def _svc_call(domain, service, data=None, blocking=False):
        log.append((domain, service, dict(data or {})))

    hass.services = MagicMock()
    hass.services.async_call = _svc_call

    entries: list[_StubEntry] = []
    states: dict[str, MagicMock] = {}
    for room, cfg in rooms.items():
        fan = f"fan.{room.lower()}"
        entry = _StubEntry(
            room_name=room, fans=[fan], entry_id=f"entry_{room}",
        )
        entries.append(entry)
        st = MagicMock()
        st.state = cfg.get("fan_state", "on")
        states[fan] = st
        # Register the room coordinator at hass.data[DOMAIN][entry_id] —
        # this is exactly the shape _get_room_coordinator reads.
        hass.data[DOMAIN][entry.entry_id] = _StubRoomCoordinator(entry)

    hass.states = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = lambda domain: list(entries)
    coord.hass = hass

    # Zones dict with one zone per test call — filled in by tests via a
    # ZoneManager stub attribute.
    coord._zone_manager = MagicMock()
    coord._zone_manager.zones = {}

    fc = MagicMock()
    fc.is_room_in_manual_on_hold = lambda room: False
    coord._fan_controller = fc
    return coord, log, entries


# ===========================================================================
# C-HIGH-1 — W11 safety-stop behavioral test.
# Drives the REAL _stop_all_fans_safety method with a live manual-ON hold
# in the oracle. The safety=True semantic MUST override the hold and the
# fan.turn_off MUST be emitted (safety > policy).
# Mutation anchor 1 (MUT-STOP): short-circuit the per-fan loop guard
# (add `continue` before _safety_stop_one_fan call) — the test MUST red
# on turn_off missing from the log.
# Mutation anchor 2 (MUT3-4-behavioral): flip `direction="off", safety=True`
# to `safety=False` — the OFF is DEFER-ed by the hold, no service call,
# test reds on turn_off missing.
# ===========================================================================

def test_w11_safety_stop_overrides_manual_on_hold_and_emits_turn_off():
    """Behavioral W11 test — the reviewer C mutation anchor.

    Seed a live manual-ON hold in the oracle for a room whose fan is
    ON. Trigger the real ``_stop_all_fans_safety`` and assert:
      * fan.turn_off IS called (safety > policy)
      * the emission carries the fan entity id
    A mutation that short-circuits the loop guard (skip
    _safety_stop_one_fan) OR flips ``safety=True`` to ``safety=False``
    (DEFER on hold) MUST make this test RED.
    """
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    oracle = FanPolicyOracle()
    # Live hold on the target room — pre-safety verdict is DEFER.
    oracle._get_record("Bedroom").manual_on_hold_until = (  # noqa: SLF001
        fake_now + timedelta(hours=1)
    )

    coord, log, entries = _make_hvac_coord(
        {"Bedroom": {"fan_state": "on"}},
        seeded_oracle=oracle,
    )
    coord._zone_manager.zones = {"z1": _StubZone("Z1", ["Bedroom"])}

    _run(coord._stop_all_fans_safety())

    turn_offs = [
        (svc, d.get("entity_id"))
        for (_dom, svc, d) in log if svc == "turn_off"
    ]
    assert ("turn_off", "fan.bedroom") in turn_offs, (
        f"W11 safety-stop MUST emit turn_off even under a live manual-ON "
        f"hold (safety > policy). Log: {log}"
    )


def test_w11_safety_stop_survives_bad_room_and_continues_siblings():
    """B-MED-2 fix-up: one bad room MUST NOT abort safety for the rest."""
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    oracle = FanPolicyOracle()
    coord, log, entries = _make_hvac_coord(
        {"BadRoom": {"fan_state": "on"}, "GoodRoom": {"fan_state": "on"}},
        seeded_oracle=oracle,
    )
    # Sabotage BadRoom — its coordinator lookup will explode.
    original_get = coord._get_room_coordinator

    def _sabotaged(room_name):
        if room_name == "BadRoom":
            raise RuntimeError("bad-room-boom")
        return original_get(room_name)

    coord._get_room_coordinator = _sabotaged
    coord._zone_manager.zones = {
        "z1": _StubZone("Z1", ["BadRoom", "GoodRoom"]),
    }

    _run(coord._stop_all_fans_safety())

    turn_offs = {d.get("entity_id") for (_dom, svc, d) in log if svc == "turn_off"}
    assert "fan.goodroom" in turn_offs, (
        f"Sibling MUST still be safety-stopped after a bad room errors. "
        f"Log: {log}"
    )


def _make_hvac_coord_get_room(coord, entries):
    """Attach a real `_get_room_coordinator` that reads from entries."""
    stubs = {e.data[CONF_ROOM_NAME]: _StubRoomCoordinator(e) for e in entries}
    coord._get_room_coordinator = lambda room: stubs.get(room)


# ===========================================================================
# C-HIGH-2 — W12 pre-arrival ON behavioral test.
# Drives the REAL _activate_zone_fans with a live manual-OFF cooldown
# in the oracle. Pre-arrival ON MUST DEFER (no turn_on call) AND
# skipped-rooms diagnostic MUST record reason="manual_off_cooldown".
# Mutation anchor MUT3-6-behavioral: flip DEFER("manual_off_cooldown")
# → ALLOW in the oracle — the test MUST red on unexpected turn_on
# emission.
# ===========================================================================

def _make_predictor(hass):
    pred = HVACPredictor.__new__(HVACPredictor)
    pred.hass = hass
    pred._last_fan_activation_rooms = []
    pred._last_fan_skipped_rooms = []
    pred._hvac_coord = MagicMock()
    pred._hvac_coord._house_state = "day"
    return pred


def test_w12_prearrival_on_defers_under_manual_off_cooldown_behavioral():
    """Behavioral W12 test — the reviewer C-HIGH-2 mutation anchor."""
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    oracle = FanPolicyOracle()
    oracle._get_record("Bedroom").manual_off_cooldown_until = (  # noqa: SLF001
        fake_now + timedelta(hours=1)
    )

    coord, log, entries = _make_hvac_coord(
        {"Bedroom": {"fan_state": "off"}},
        seeded_oracle=oracle,
    )
    _make_hvac_coord_get_room(coord, entries)
    pred = _make_predictor(coord.hass)
    pred._get_room_coordinator = coord._get_room_coordinator

    zone = _StubZone("Z1", ["Bedroom"])
    zone.room_conditions = [_RoomCondition("Bedroom", 78.0)]  # above 74 setpoint

    _run(pred._activate_zone_fans(zone))

    turn_ons = [svc for (_dom, svc, _d) in log if svc == "turn_on"]
    assert turn_ons == [], (
        f"W12: pre-arrival ON MUST DEFER under live manual-OFF cooldown. "
        f"Log: {log}"
    )
    reasons = [r.get("reason") for r in pred._last_fan_skipped_rooms]
    assert "manual_off_cooldown" in reasons, (
        f"W12: skipped-rooms diagnostic MUST record "
        f"reason='manual_off_cooldown'. Skipped: {pred._last_fan_skipped_rooms}"
    )


def test_w12_prearrival_on_allows_when_cooldown_expired_behavioral():
    """Symmetric behavioral W12 test — expired cooldown → turn_on fires."""
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    oracle = FanPolicyOracle()
    # Cooldown 1 hour in the PAST — expired.
    oracle._get_record("Bedroom").manual_off_cooldown_until = (  # noqa: SLF001
        fake_now - timedelta(hours=1)
    )

    coord, log, entries = _make_hvac_coord(
        {"Bedroom": {"fan_state": "off"}},
        seeded_oracle=oracle,
    )
    _make_hvac_coord_get_room(coord, entries)
    pred = _make_predictor(coord.hass)
    pred._get_room_coordinator = coord._get_room_coordinator

    zone = _StubZone("Z1", ["Bedroom"])
    zone.room_conditions = [_RoomCondition("Bedroom", 78.0)]

    _run(pred._activate_zone_fans(zone))

    turn_ons = [(svc, d.get("entity_id")) for (_dom, svc, d) in log if svc == "turn_on"]
    assert ("turn_on", "fan.bedroom") in turn_ons, (
        f"W12: pre-arrival ON MUST fire when cooldown is expired. Log: {log}"
    )


# ===========================================================================
# A-HIGH-1 companion — two rooms without CONF_ROOM_NAME keep isolated ledgers.
# The room-key resolution prefers entry_id, so two rooms without a name
# still get distinct ledger entries via entry:<uuid>.
# ===========================================================================

def test_two_unnamed_rooms_keep_isolated_holds_via_entry_id_key():
    """A-HIGH-1: entry_id keying prevents CONF_ROOM_NAME collision."""
    import _provenance_harness  # noqa: F401
    from custom_components.universal_room_automation.automation import (  # noqa: E501,PLC0415
        RoomAutomation,
    )

    def _make(entry_id: str):
        r = RoomAutomation.__new__(RoomAutomation)
        r.hass = MagicMock()
        r.hass.data = {DOMAIN: {"fan_oracle": FanPolicyOracle()}}
        r.config = {}  # NO CONF_ROOM_NAME — the pre-fix collision case
        e = MagicMock()
        e.entry_id = entry_id
        r._config_entry = e
        return r

    # Share the same oracle so a collision would be observable.
    shared_oracle = FanPolicyOracle()
    r1 = _make("entry-A")
    r1.hass.data[DOMAIN]["fan_oracle"] = shared_oracle
    r2 = _make("entry-B")
    r2.hass.data[DOMAIN]["fan_oracle"] = shared_oracle

    t = datetime(2026, 8, 11, 12, 0, 0)
    r1._fan_manual_on_until = t + timedelta(minutes=30)
    r2._fan_manual_on_until = t + timedelta(hours=2)

    # Isolated ledger entries — each room reads back its OWN write.
    assert r1._fan_manual_on_until == t + timedelta(minutes=30)
    assert r2._fan_manual_on_until == t + timedelta(hours=2)


# ===========================================================================
# A-HIGH-2 / B-HIGH-1 — pre-oracle write hydrates on read once oracle attaches.
# ===========================================================================

def test_pre_oracle_write_is_hydrated_when_oracle_appears():
    """A-HIGH-2: write before oracle attach → attach → read returns write AND
    oracle now carries it (one-time hydration on read)."""
    import _provenance_harness  # noqa: F401
    from custom_components.universal_room_automation.automation import (  # noqa: E501,PLC0415
        RoomAutomation,
    )

    r = RoomAutomation.__new__(RoomAutomation)
    r.hass = MagicMock()
    r.hass.data = {}  # NO DOMAIN yet — oracle unavailable
    r.config = {"room_name": "Bedroom"}
    e = MagicMock()
    e.entry_id = "entry-C"
    r._config_entry = e

    t = datetime(2026, 8, 11, 12, 0, 0)
    r._fan_manual_on_until = t + timedelta(minutes=45)  # pre-oracle write

    # Now attach an oracle. The oracle knows NOTHING about this hold yet.
    oracle = FanPolicyOracle()
    r.hass.data = {DOMAIN: {"fan_oracle": oracle}}
    assert oracle.get_state("room:Bedroom").manual_on_hold_until is None

    # First read after attach hydrates the oracle from local cache.
    val = r._fan_manual_on_until
    assert val == t + timedelta(minutes=45), (
        "hydration read MUST return the pre-oracle write"
    )
    assert oracle.get_state("room:Bedroom").manual_on_hold_until == (
        t + timedelta(minutes=45)
    ), "oracle MUST now carry the hydrated hold"


# ===========================================================================
# B-HIGH-2 — CM re-construction reuses existing oracle.
# ===========================================================================

def test_coordinator_manager_reload_reuses_existing_oracle():
    """B-HIGH-2: constructing CM twice with a hold set between MUST preserve
    the hold via oracle reuse (not overwrite)."""
    # Straight oracle-level test — CoordinatorManager pulls in heavy deps.
    # The one-liner we're locking: CM.__init__ picks up
    # ``hass.data[DOMAIN]["fan_oracle"]`` if present and reuses it.
    import _provenance_harness  # noqa: F401
    from custom_components.universal_room_automation.domain_coordinators.manager import (  # noqa: E501,PLC0415
        CoordinatorManager,
    )

    hass = MagicMock()
    hass.data = {}

    cm1 = CoordinatorManager(hass=hass)
    oracle1 = cm1.fan_oracle
    assert oracle1 is not None
    # Set a hold on the shared oracle.
    from datetime import datetime as _dt
    oracle1._get_record("entry:entryZ").manual_on_hold_until = (  # noqa: SLF001
        _dt(2026, 8, 11, 13, 0, 0)
    )

    # Reload: construct a new CM with the SAME hass — the oracle MUST
    # survive (same instance, hold intact).
    cm2 = CoordinatorManager(hass=hass)
    oracle2 = cm2.fan_oracle
    assert oracle2 is oracle1, (
        "CM reload MUST reuse the existing FanPolicyOracle from hass.data "
        "(B-HIGH-2). New oracle instance drops all live holds."
    )
    assert oracle2.get_state("entry:entryZ").manual_on_hold_until == (
        _dt(2026, 8, 11, 13, 0, 0)
    ), "hold set on the pre-reload oracle MUST survive the CM reload"


# ===========================================================================
# Review-C anchors (2026-08-11) — W8 / W9 / W4-chokepoint.
# Reviewer C authored these to close the hollow-anchor gap disclosed at the
# end of FAN-LAYER-2 D2: the 7 non-safety wraps (W1, W2, W3-temp, W3-onset,
# W4-chokepoint, W8, W9) had NO behavioral anchors — the neuter mutation
# `if False and verdict.is_allow:` at each site left the entire suite green.
# These tests drive the REAL production methods with a live oracle carrying
# a hold/cooldown that makes the verdict block, and a services.async_call
# recorder — asserting suppression under DEFER and emission under ALLOW.
# W1/W2/W3-temp/W3-onset live inside RoomAutomation which is not exercised
# by this harness — reported as a residual HIGH gap; see review report.
# ===========================================================================


def _make_zone_stub(zone_name: str, rooms: list[str]):
    return _StubZone(zone_name, rooms)


def _install_real_snapshot_builder(coord, now_dt):
    """Replace MagicMock FC's snapshot builder with one that returns a real
    ``FanDecisionSnapshot`` — otherwise ``snapshot.now`` is a MagicMock and
    the oracle's `<` compare raises, tripping the fail-safe ALLOW branch and
    defeating the DEFER test."""
    from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E501,PLC0415
        FanDecisionSnapshot,
    )

    def _real_snap(room_name, fan_entities, observed_any_on):
        return FanDecisionSnapshot(
            now=now_dt,
            sleep_state="",
            sleep_axis=None,
            house_state="home_day",
            is_hvac_managing=True,
            entities=tuple(fan_entities),
            observed_any_on=bool(observed_any_on),
        )

    coord._fan_controller._build_fan_snapshot_hvac = _real_snap


# ---------------------------------------------------------------------------
# W8 — HVAC zone-vacancy sweep OFF wrap (hvac.py:2841).
# Enclosing method: _execute_vacancy_sweep. The pre-check
# `fan_hold_active` reads FanController.is_room_in_manual_on_hold and
# coordinator.automation.is_fan_in_manual_on_hold. Both are stubbed False so
# the oracle wrap is the gate.
# ---------------------------------------------------------------------------

def test_w8_vacancy_sweep_defers_under_oracle_manual_on_hold():
    """W8 DEFER: oracle-only manual-ON hold suppresses vacancy-sweep OFF."""
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    oracle = FanPolicyOracle()
    oracle._get_record("room:LivingRoom").manual_on_hold_until = (  # noqa: SLF001
        fake_now + timedelta(hours=1)
    )
    coord, log, entries = _make_hvac_coord(
        {"LivingRoom": {"fan_state": "on"}}, seeded_oracle=oracle,
    )
    coord._fan_controller.is_room_in_manual_on_hold = lambda room: False
    _install_real_snapshot_builder(coord, fake_now)
    _run(coord._execute_vacancy_sweep(_make_zone_stub("Z1", ["LivingRoom"])))

    turn_offs = [
        (svc, d.get("entity_id")) for (_dom, svc, d) in log if svc == "turn_off"
    ]
    assert ("turn_off", "fan.livingroom") not in turn_offs, (
        f"W8: oracle-DEFER (manual-ON hold with pre-check stubbed False) MUST "
        f"suppress vacancy-sweep fan turn_off. Log: {log}"
    )


def test_w8_vacancy_sweep_allows_when_oracle_clear():
    """W8 ALLOW (positive control): clean oracle → sweep emits turn_off."""
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    oracle = FanPolicyOracle()
    coord, log, entries = _make_hvac_coord(
        {"LivingRoom": {"fan_state": "on"}}, seeded_oracle=oracle,
    )
    coord._fan_controller.is_room_in_manual_on_hold = lambda room: False
    _install_real_snapshot_builder(coord, fake_now)
    _run(coord._execute_vacancy_sweep(_make_zone_stub("Z1", ["LivingRoom"])))

    turn_offs = [
        (svc, d.get("entity_id")) for (_dom, svc, d) in log if svc == "turn_off"
    ]
    assert ("turn_off", "fan.livingroom") in turn_offs, (
        f"W8: clean-oracle ALLOW MUST emit vacancy-sweep turn_off. Log: {log}"
    )


# ---------------------------------------------------------------------------
# W9 — HVAC pre-arrival deactivation OFF wrap (hvac.py:3131).
# Enclosing method: _deactivate_zone_fans. Requires predictor's
# `_last_fan_activation_rooms` to include the target room; otherwise the
# per-room loop short-circuits before the wrap.
# ---------------------------------------------------------------------------

def _prime_predictor(coord, activated_rooms: list[str]):
    pred = MagicMock()
    pred._last_fan_activation_rooms = list(activated_rooms)
    coord._predictor = pred


def test_w9_prearrival_deactivate_defers_under_oracle_manual_on_hold():
    """W9 DEFER: oracle manual-ON hold suppresses pre-arrival deactivation."""
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    oracle = FanPolicyOracle()
    oracle._get_record("room:StudyRoom").manual_on_hold_until = (  # noqa: SLF001
        fake_now + timedelta(hours=1)
    )
    coord, log, entries = _make_hvac_coord(
        {"StudyRoom": {"fan_state": "on"}}, seeded_oracle=oracle,
    )
    coord._fan_controller.is_room_in_manual_on_hold = lambda room: False
    _install_real_snapshot_builder(coord, fake_now)
    _prime_predictor(coord, ["StudyRoom"])
    _run(coord._deactivate_zone_fans(_make_zone_stub("Z1", ["StudyRoom"])))

    turn_offs = [
        (svc, d.get("entity_id")) for (_dom, svc, d) in log if svc == "turn_off"
    ]
    assert ("turn_off", "fan.studyroom") not in turn_offs, (
        f"W9: oracle-DEFER MUST suppress pre-arrival deactivation. Log: {log}"
    )


def test_w9_prearrival_deactivate_allows_when_oracle_clear():
    """W9 ALLOW (positive control): clean oracle → pre-arrival deactivation fires."""
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    oracle = FanPolicyOracle()
    coord, log, entries = _make_hvac_coord(
        {"StudyRoom": {"fan_state": "on"}}, seeded_oracle=oracle,
    )
    coord._fan_controller.is_room_in_manual_on_hold = lambda room: False
    _install_real_snapshot_builder(coord, fake_now)
    _prime_predictor(coord, ["StudyRoom"])
    _run(coord._deactivate_zone_fans(_make_zone_stub("Z1", ["StudyRoom"])))

    turn_offs = [
        (svc, d.get("entity_id")) for (_dom, svc, d) in log if svc == "turn_off"
    ]
    assert ("turn_off", "fan.studyroom") in turn_offs, (
        f"W9: clean-oracle ALLOW MUST emit pre-arrival deactivation. Log: {log}"
    )


# ---------------------------------------------------------------------------
# W4-chokepoint — hvac_fans FanController._set_fan_state ON path
# (hvac_fans.py:1565). All HVAC-tier callers converge here. Uses an ON
# direction with a live manual_off_cooldown → verdict DEFER → no turn_on
# emitted. Paired ALLOW leg: no cooldown → turn_on fires.
# ---------------------------------------------------------------------------

def _build_fc_env(now_dt, oracle):
    """Construct a minimal FanController drivable to _set_fan_state.

    Returns (fc, hass, log). The FC's room_name key is not registered in
    self._room_fans so the OFF-side manual-hold pre-check is skipped — but
    for the ON direction the OFF pre-check block is skipped anyway; we're
    proving the wrap's ON-direction gating.
    """
    FanController = _FanController
    hass = MagicMock()
    hass.data = {DOMAIN: {"fan_oracle": oracle}}
    log: list = []

    async def _svc(domain, service, data=None, blocking=False):
        log.append((domain, service, dict(data or {})))

    hass.services = MagicMock()
    hass.services.async_call = _svc
    st = MagicMock(); st.state = "off"
    hass.states = MagicMock()
    hass.states.get = lambda eid: st

    zm = MagicMock(); zm.zones = {}
    fc = FanController(hass, zm)
    return fc, hass, log


def test_w4_chokepoint_defers_on_when_oracle_carries_manual_off_cooldown():
    """W4 DEFER: ON request while cooldown live → no turn_on emitted."""
    _room_key = _room_key_fn
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    room = "PantryRoom"
    fan = f"fan.{room.lower()}"
    oracle = FanPolicyOracle()
    oracle._get_record(_room_key(room)).manual_off_cooldown_until = (  # noqa: SLF001
        fake_now + timedelta(hours=1)
    )
    fc, hass, log = _build_fc_env(fake_now, oracle)

    dispatched = _run(fc._set_fan_state(
        entities=[fan], on=True, speed_pct=50,
        room_name=room, trigger_path=FAN_TRIGGER_TEMP_ROOM_ON,
    ))
    turn_ons = [(svc, d.get("entity_id")) for (_dom, svc, d) in log if svc == "turn_on"]
    assert ("fan", "turn_on") not in [(dom, svc) for (dom, svc, _d) in log if svc == "turn_on"] or \
        ("turn_on", fan) not in turn_ons, (
        f"W4 chokepoint: oracle manual_off_cooldown MUST DEFER the ON emit. "
        f"Log: {log}"
    )
    assert dispatched is False, (
        f"W4 chokepoint: dispatched flag MUST be False under DEFER. Got {dispatched}"
    )


def test_w4_chokepoint_allows_on_when_oracle_clear():
    """W4 ALLOW: no cooldown → ON emit fires and dispatched=True."""
    fake_now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(fake_now)

    room = "PantryRoom"
    fan = f"fan.{room.lower()}"
    oracle = FanPolicyOracle()  # clean
    fc, hass, log = _build_fc_env(fake_now, oracle)

    dispatched = _run(fc._set_fan_state(
        entities=[fan], on=True, speed_pct=50,
        room_name=room, trigger_path=FAN_TRIGGER_TEMP_ROOM_ON,
    ))
    turn_ons = [(svc, d.get("entity_id")) for (_dom, svc, d) in log if svc == "turn_on"]
    assert ("turn_on", fan) in turn_ons, (
        f"W4 chokepoint: clean-oracle MUST ALLOW ON emit. Log: {log}"
    )
    assert dispatched is True, (
        f"W4 chokepoint: dispatched flag MUST be True under ALLOW. Got {dispatched}"
    )
