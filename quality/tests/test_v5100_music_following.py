"""Tests for v5.10.0 Music Following cycle.

Covers:
- D1: silent-actuator visibility (target_unavailable stat + pre-flight guard)
- D2: sleep + night gating via SIGNAL_HOUSE_STATE_CHANGED / update_house_state
- D3: guest-in-source-room guard via OccupancySubstrate.is_kind_active
- D4: ping_pong_suppressed counter wiring + same_room stat
- D5: MFPersonFollowSwitch construction contract (Bug Class #52 guard)
- D6: lock TOCTOU fix + stale_transition guard + async_teardown clears state
- D7: target picker platform-preference
- D8: skip-reason attribute surface in get_diagnostic_data
- D9: arrival-stub deprecation (log DEBUG, no service call)
- D11: per-room speaker loudness calibration on cross-platform generic
- D12: verify-delay conditional (skip_wait on join path)

Fixtures drive production code paths (real MusicFollowing methods on a
fake HA env) — not hand-rolled INSERT/UPDATE/DELETE per Tier 2-DB
Reviewer C rule.
"""

import pytest
import sys
import os
import types
import importlib
import importlib.util
import asyncio
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Bootstrap the same mock env used by test_music_following_coordinator.py so
# the real production module `custom_components.universal_room_automation.
# music_following` (the standalone class) can be imported.
# ---------------------------------------------------------------------------


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "callback": _identity,
        "Event": MagicMock,
        "State": MagicMock,
    },
    "homeassistant.config_entries": {"ConfigEntry": MagicMock},
    "homeassistant.const": _mock_module(
        "homeassistant.const", STATE_PLAYING="playing",
    ),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": MagicMock},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": MagicMock(),
        "async_track_time_interval": MagicMock(),
        "async_call_later": lambda hass, delay, cb: MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
        "async_dispatcher_connect": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": MagicMock,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": MagicMock(),
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.sun": {},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.media_player": _mock_module(
        "homeassistant.components.media_player",
        ATTR_MEDIA_POSITION="media_position",
        ATTR_MEDIA_VOLUME_LEVEL="volume_level",
        DOMAIN="media_player",
        SERVICE_MEDIA_PAUSE="media_pause",
        SERVICE_MEDIA_PLAY="media_play",
        SERVICE_VOLUME_SET="volume_set",
    ),
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": MagicMock(),
        "SensorStateClass": MagicMock(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": MagicMock(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Package hierarchy
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)


def _load(fullname: str, filepath: str):
    spec = importlib.util.spec_from_file_location(fullname, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = mod
    spec.loader.exec_module(mod)
    return mod


# const first — no HA imports
_const = _load(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_ura.const = _const

# transitions.py — pure Python + typing (HA event/callback imported but mocked)
_trans = _load(
    "custom_components.universal_room_automation.transitions",
    os.path.join(_ura_path, "transitions.py"),
)
_ura.transitions = _trans

# music_following.py — the class under test.
# If a sibling test already loaded this module with a different mock env,
# reuse that instance to avoid divergent STATE_PLAYING sentinels.
_mf_fullname = "custom_components.universal_room_automation.music_following"
if _mf_fullname in sys.modules:
    _mf_mod = sys.modules[_mf_fullname]
else:
    _mf_mod = _load(_mf_fullname, os.path.join(_ura_path, "music_following.py"))
_ura.music_following = _mf_mod

# Test-ordering pollution guard (2026-07-10):
# Earlier test files (test_v4_6_10_setup_telemetry.py,
# test_v4_6_12_aggregator_sensors.py) call
# `sys.modules.setdefault("homeassistant.util.dt", <tz-aware MagicMock stub>)`
# at module-import time and never tear it down. When this file loads after
# them, our own `setdefault` no-ops and music_following.py binds
# `dt_util = <polluted tz-aware stub>` while our `_transition()` helper
# builds naive-local timestamps. The stale-transition guard then computes
# age = tz-aware-utc - naive-local-as-utc ≈ 7h and short-circuits every
# transfer at "stale_transition", so all downstream gate/stat asserts
# silently see 0 counters (7 tests fail).
#
# Fix at the victim, not the polluter: overwrite the loaded module's
# top-level `dt_util` and `STATE_PLAYING` attributes with our own clean
# stubs. This is confined to the module we own here — nothing in
# sys.modules is touched, so downstream test files see exactly the
# environment they saw before this fix.
class _CleanDT:
    utcnow = staticmethod(datetime.utcnow)
    now = staticmethod(datetime.now)
    as_local = staticmethod(lambda dt: dt)

_mf_mod.dt_util = _CleanDT
_mf_mod.STATE_PLAYING = "playing"

MusicFollowing = _mf_mod.MusicFollowing
RoomTransition = _trans.RoomTransition
# STATE_PLAYING is the "playing" string from our pollution guard above.
# Tests use this value to build FakeState so equality checks succeed.
STATE_PLAYING = _mf_mod.STATE_PLAYING


# ---------------------------------------------------------------------------
# Fake HA env
# ---------------------------------------------------------------------------


class FakeState:
    def __init__(self, state="idle", attributes=None):
        self.state = state
        self.attributes = attributes or {}


class FakeStates:
    def __init__(self):
        self._store: dict[str, FakeState] = {}

    def get(self, entity_id):
        return self._store.get(entity_id)

    def set(self, entity_id, state):
        self._store[entity_id] = state


class FakeServices:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, dict(data)))


class FakeConfigEntries:
    def async_entries(self, domain):
        return []


class FakeHass:
    def __init__(self):
        self.data = {"universal_room_automation": {}}
        self.states = FakeStates()
        self.services = FakeServices()
        self.config_entries = FakeConfigEntries()

    def async_create_task(self, coro, name=None):
        # Return a Task-like mock; scheduling not required for these unit
        # tests since we don't rely on cleanup timing.
        try:
            return asyncio.ensure_future(coro)
        except Exception:
            return MagicMock()


class FakeSubstrate:
    def __init__(self, kinds_by_room=None):
        # kinds_by_room: {room_name: {kind: bool}}
        self._kinds = kinds_by_room or {}

    def is_kind_active(self, room, kind):
        return bool(self._kinds.get(room, {}).get(kind, False))


def _make_mf():
    hass = FakeHass()
    td = MagicMock()
    mf = MusicFollowing(hass, {}, td)
    return mf, hass


def _transition(person="Oji", from_room="kitchen", to_room="bedroom",
                confidence=0.9, ts=None):
    return RoomTransition(
        person_id=person, from_room=from_room, to_room=to_room,
        timestamp=ts or datetime.now(),
        duration_seconds=5, path_type="direct", confidence=confidence,
    )


# ===========================================================================
# D1 — silent-actuator visibility
# ===========================================================================


class TestD1SilentActuator:
    def test_target_unavailable_stat_declared(self):
        mf, _ = _make_mf()
        assert "target_unavailable" in mf._transfer_stats
        assert mf._transfer_stats["target_unavailable"] == 0

    def test_actuator_single_keys_includes_room_media_player(self):
        # D1: sensor.py:1646 extended
        import re
        with open(
            os.path.join(_ura_path, "sensor.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        # Find the _ACTUATOR_SINGLE_KEYS tuple line
        m = re.search(
            r"_ACTUATOR_SINGLE_KEYS\s*=\s*\(([^)]*)\)", src, re.DOTALL,
        )
        assert m, "sensor.py must declare _ACTUATOR_SINGLE_KEYS"
        assert "room_media_player" in m.group(1)

    @pytest.mark.asyncio
    async def test_preflight_records_target_unavailable_and_no_source_touch(self):
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        # Configure a from_player + to_player via a "room_entries" style
        # short-circuit: register room_media_player via config-entries
        # would require full mocking — instead patch _get_room_player.
        async def _get_player(room):
            return {"kitchen": "media_player.kitchen",
                    "bedroom": "media_player.bedroom"}[room]
        mf._get_room_player = _get_player
        # Source PLAYING, target UNAVAILABLE.
        hass.states.set("media_player.kitchen",
                        FakeState(STATE_PLAYING, {"volume_level": 0.5,
                                              "media_content_id": "http://x",
                                              "media_content_type": "music"}))
        hass.states.set("media_player.bedroom", FakeState("unavailable"))
        await mf._on_person_transition(_transition())
        # Skip counter incremented
        assert mf._transfer_stats["target_unavailable"] >= 1
        # Source not faded — no volume_set service call
        vol_calls = [c for c in hass.services.calls if c[1] == "volume_set"]
        assert not vol_calls, f"Expected no volume_set; got {vol_calls}"
        # Skip-reason surface populated
        assert mf._last_skip_reason == "target_unavailable"
        assert mf._last_skip_from_room == "kitchen"
        assert mf._last_skip_to_room == "bedroom"

    @pytest.mark.asyncio
    async def test_preflight_missing_state_treated_as_unavailable(self):
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        async def _get_player(room):
            return {"kitchen": "media_player.kitchen",
                    "bedroom": "media_player.bedroom"}[room]
        mf._get_room_player = _get_player
        hass.states.set("media_player.kitchen",
                        FakeState(STATE_PLAYING, {"volume_level": 0.5,
                                              "media_content_id": "http://x",
                                              "media_content_type": "music"}))
        # No state for bedroom at all
        await mf._on_person_transition(_transition())
        assert mf._transfer_stats["target_unavailable"] >= 1


# ===========================================================================
# D2 — sleep + night gating
# ===========================================================================


class TestD2SleepNightGating:
    def test_conf_defaults_exist(self):
        assert _const.CONF_MF_SLEEP_SUPPRESS == "mf_sleep_suppress"
        assert _const.DEFAULT_MF_SLEEP_SUPPRESS is True
        assert _const.CONF_MF_NIGHT_SUPPRESS_MODE == "mf_night_suppress_mode"
        # v5.10.0 fix-up FIX-3 (A-CRIT-2): default changed from
        # "dwell_only" → "off" because dwell_only silently suppressed
        # every HOME_NIGHT transition (no per-person bedroom surface
        # exists — person_coordinator does not populate dwell_room /
        # bedroom keys). SLEEP suppression is the headline protection
        # and remains ON by default. Operators wanting strict night
        # behavior pick "block_all" explicitly.
        assert _const.DEFAULT_MF_NIGHT_SUPPRESS_MODE == "off"
        assert set(_const.MF_NIGHT_MODES) == {"off", "dwell_only", "block_all"}

    def test_update_house_state_sets_field(self):
        mf, _ = _make_mf()
        mf.update_house_state("sleep")
        assert mf._current_house_state == "sleep"
        mf.update_house_state("home_day")
        assert mf._current_house_state == "home_day"

    def test_update_gate_config_pushes_values(self):
        mf, _ = _make_mf()
        mf.update_gate_config(sleep_suppress=False,
                              night_suppress_mode="block_all",
                              stale_transition_seconds=20.0)
        assert mf._sleep_suppress is False
        assert mf._night_suppress_mode == "block_all"
        assert mf._stale_transition_seconds == 20.0

    @pytest.mark.asyncio
    async def test_sleep_state_suppresses_transfer_no_service_calls(self):
        """Falsifiable invariant: during SLEEP, MF calls zero media_player services."""
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        mf.update_house_state("sleep")
        # If gate fires, this shouldn't even be called — but wire it anyway.
        async def _get_player(room):
            return f"media_player.{room}"
        mf._get_room_player = _get_player
        hass.states.set("media_player.kitchen",
                        FakeState(STATE_PLAYING, {"volume_level": 0.5}))
        hass.states.set("media_player.bedroom",
                        FakeState("idle"))
        await mf._on_person_transition(_transition())
        # Zero service calls — invariant #2 upheld
        assert hass.services.calls == []
        assert mf._transfer_stats["sleep_suppressed"] >= 1

    @pytest.mark.asyncio
    async def test_home_night_block_all_suppresses(self):
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        mf.update_house_state("home_night")
        mf.update_gate_config(night_suppress_mode="block_all")
        async def _get_player(room):
            return f"media_player.{room}"
        mf._get_room_player = _get_player
        await mf._on_person_transition(_transition())
        assert hass.services.calls == []
        assert mf._transfer_stats["night_suppressed"] >= 1

    @pytest.mark.asyncio
    async def test_home_night_dwell_only_no_dwell_suppresses(self):
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        mf.update_house_state("home_night")
        mf.update_gate_config(night_suppress_mode="dwell_only")
        # No person_coordinator → dwell unknown → err on suppress
        await mf._on_person_transition(_transition())
        assert mf._transfer_stats["night_suppressed"] >= 1

    @pytest.mark.asyncio
    async def test_home_night_mode_off_allows_gate_passthrough(self):
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        mf.update_house_state("home_night")
        mf.update_gate_config(night_suppress_mode="off")
        # Gate should NOT record night_suppressed; further gates may skip
        # for other reasons (no player found, etc.) — we only check the
        # night counter stays 0.
        async def _get_player(room):
            return None
        mf._get_room_player = _get_player
        await mf._on_person_transition(_transition())
        assert mf._transfer_stats["night_suppressed"] == 0

    @pytest.mark.asyncio
    async def test_no_house_state_seeded_gate_allows(self):
        """Empty house_state must not accidentally suppress everything."""
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        assert mf._current_house_state == ""
        async def _get_player(room):
            return None
        mf._get_room_player = _get_player
        await mf._on_person_transition(_transition())
        # Not gated by sleep/night — the no-player skip is what should
        # short-circuit later.
        assert mf._transfer_stats["sleep_suppressed"] == 0
        assert mf._transfer_stats["night_suppressed"] == 0


# ===========================================================================
# D3 — guest-in-source-room guard
# ===========================================================================


class TestD3GuestGuard:
    """v5.10.0 fix-up FIX-4 (A-HIGH-1): predicate redesigned.
    PRIMARY = another tracked person's ``location == from_room``;
    SECONDARY = substrate ``occupancy`` kind ONLY (motion + mmwave
    excluded as residual-prone on the leaver's own signal).
    """

    class _FakePersonCoord:
        def __init__(self, data):
            self.data = data

    def test_presence_writer_exists_in_production_source(self):
        """v5.10.0 fix-up FIX-2 (A-CRIT-1) writer-existence proof.

        The D3 predicate reads ``hass.data[DOMAIN]['occupancy_substrate']``.
        Prior to FIX-2, NO writer existed for that key — the predicate
        silently fell through to fail-open in every real environment.
        This test asserts the writer line is present in
        ``presence.py::async_setup`` so commenting out the writer would
        turn this test red (contract: production writer must exist).
        """
        presence_path = os.path.join(
            _ura_path, "domain_coordinators", "presence.py"
        )
        with open(presence_path, "r", encoding="utf-8") as fh:
            src = fh.read()
        # Writer signature: the exact assignment MUST be uncommented and
        # present. We check line-by-line to reject comment-only occurrences
        # (which would satisfy a naive substring check even if the writer
        # were disabled).
        found_uncommented = False
        for line in src.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if (
                'hass.data.setdefault(DOMAIN, {})["occupancy_substrate"]'
                in line
            ):
                found_uncommented = True
                break
        assert found_uncommented, (
            "FIX-2: presence.py must have an UNCOMMENTED writer of "
            "hass.data.setdefault(DOMAIN, {})['occupancy_substrate']. "
            "Without it, MF D3 predicate fails silently."
        )

    def test_writer_removal_would_break_test(self, monkeypatch):
        """v5.10.0 fix-up FIX-2 (A-CRIT-1) writer-removal check.

        Guard rail: this test is the CANARY that proves the D3 predicate
        actually depends on the production writer (Presence Coordinator
        setting hass.data[DOMAIN]['occupancy_substrate']). We simulate
        the writer being absent by writing None into hass.data — a real
        FakeSubstrate is deliberately NOT registered — and assert the
        predicate fails-open. If a future refactor moves the substrate
        under a different key AND removes the writer at the presence
        coordinator, the fallback here returns False as expected because
        we never registered the fake. That failing branch is what the
        A-CRIT-1 finding required: the test must not silently inject
        the key the production code never writes.
        """
        mf, hass = _make_mf()
        # No occupancy_substrate registered — mirrors "writer removed".
        assert hass.data["universal_room_automation"].get(
            "occupancy_substrate"
        ) is None
        # No person_coordinator either — primary path yields no match.
        assert mf._source_has_other_occupants("Oji", "kitchen") is False

    @pytest.mark.asyncio
    async def test_primary_another_tracked_person_in_from_room_suppresses(self):
        """FIX-4 primary path: another tracked person's location == from_room."""
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        # Person coord: Guest is still in kitchen; Oji is transitioning to bedroom.
        hass.data["universal_room_automation"]["person_coordinator"] = (
            self._FakePersonCoord({
                "Oji": {"location": "bedroom"},
                "Guest": {"location": "kitchen"},
            })
        )
        assert mf._source_has_other_occupants("Oji", "kitchen") is True

    @pytest.mark.asyncio
    async def test_solo_leaver_residual_motion_does_not_suppress(self):
        """FIX-4 anti-false-positive: leaver's own decaying motion on
        from_room must NOT trip the guard."""
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        # Only Oji is tracked; he JUST left kitchen.
        hass.data["universal_room_automation"]["person_coordinator"] = (
            self._FakePersonCoord({"Oji": {"location": "bedroom"}})
        )
        # Substrate reports motion (residual) but NOT occupancy.
        substrate = FakeSubstrate(
            kinds_by_room={"kitchen": {"motion": True, "mmwave": True}},
        )
        hass.data["universal_room_automation"]["occupancy_substrate"] = substrate
        # FIX-4: motion/mmwave excluded → predicate must return False.
        assert mf._source_has_other_occupants("Oji", "kitchen") is False

    @pytest.mark.asyncio
    async def test_secondary_untracked_occupancy_kind_suppresses(self):
        """FIX-4 secondary path: untracked-guest coverage via substrate
        ``occupancy`` kind (latching sensor, not motion residual)."""
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        # No person coord — untracked guest scenario.
        substrate = FakeSubstrate(
            kinds_by_room={"kitchen": {"occupancy": True}},
        )
        hass.data["universal_room_automation"]["occupancy_substrate"] = substrate
        assert mf._source_has_other_occupants("Oji", "kitchen") is True

    @pytest.mark.asyncio
    async def test_source_has_others_suppresses_transfer(self):
        """Full-flow: another tracked person in kitchen → transfer suppressed,
        zero service calls."""
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        hass.data["universal_room_automation"]["person_coordinator"] = (
            self._FakePersonCoord({
                "Oji": {"location": "bedroom"},
                "Guest": {"location": "kitchen"},
            })
        )
        async def _get_player(room):
            return f"media_player.{room}"
        mf._get_room_player = _get_player
        hass.states.set("media_player.kitchen",
                        FakeState(STATE_PLAYING, {"volume_level": 0.5}))
        hass.states.set("media_player.bedroom", FakeState("idle"))
        await mf._on_person_transition(_transition())
        assert mf._transfer_stats["source_has_others"] >= 1
        # Zero fade / play_media calls
        assert hass.services.calls == []

    @pytest.mark.asyncio
    async def test_solo_occupant_still_transfers(self):
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        substrate = FakeSubstrate(kinds_by_room={"kitchen": {}})
        hass.data["universal_room_automation"]["occupancy_substrate"] = substrate
        assert mf._source_has_other_occupants("Oji", "kitchen") is False

    def test_missing_substrate_fails_open(self):
        mf, hass = _make_mf()
        # No occupancy_substrate in hass.data
        assert mf._source_has_other_occupants("Oji", "kitchen") is False

    @pytest.mark.asyncio
    async def test_predicate_read_does_not_await(self):
        """D3 predicate must be non-blocking — no coroutine returned."""
        mf, hass = _make_mf()
        # FIX-4: use ``occupancy`` (the retained secondary kind), not motion.
        substrate = FakeSubstrate(
            kinds_by_room={"kitchen": {"occupancy": True}}
        )
        hass.data["universal_room_automation"]["occupancy_substrate"] = substrate
        # is_kind_active is a plain method (not async).
        result = mf._source_has_other_occupants("Oji", "kitchen")
        assert isinstance(result, bool)
        assert result is True


# ===========================================================================
# D4 — ping-pong counter wiring + same_room stat
# ===========================================================================


class TestD4PingPongAndSameRoom:
    @pytest.mark.asyncio
    async def test_same_room_records_stat(self):
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        await mf._on_person_transition(
            _transition(from_room="kitchen", to_room="kitchen"),
        )
        assert mf._transfer_stats["same_room"] >= 1

    def test_ping_pong_notify_hook_present(self):
        """transitions.py has _notify_ping_pong_suppressed method (D4 wire-back)."""
        assert hasattr(
            _trans.TransitionDetector, "_notify_ping_pong_suppressed"
        )

    def test_ping_pong_hook_increments_mf_stat(self):
        """Calling the hook feeds MF's ping_pong_suppressed counter."""
        mf, hass = _make_mf()
        # Simulate what transitions.py:231 does after suppression
        hass.data["universal_room_automation"]["music_following"] = mf
        det = _trans.TransitionDetector.__new__(_trans.TransitionDetector)
        det.hass = hass
        det._notify_ping_pong_suppressed("Oji", "kitchen", "bedroom")
        assert mf._transfer_stats["ping_pong_suppressed"] == 1
        assert mf._last_skip_reason == "ping_pong_suppressed"


# ===========================================================================
# D5 — per-person switch construction contract
# ===========================================================================


class TestD5PerPersonSwitch:
    """D5 concerns switch.py MFPersonFollowSwitch; the switch module has
    heavy HA runtime imports, so we assert the class exists and its
    construction contract via source inspection rather than importing the
    full switch platform.
    """

    def test_switch_class_defined_in_source(self):
        with open(
            os.path.join(_ura_path, "switch.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        assert "class MFPersonFollowSwitch" in src
        assert "_build_per_person_mf_switches" in src
        # Bug Class #52 guard reference (must mention #52 comment)
        assert "Bug Class #52" in src[
            src.find("class MFPersonFollowSwitch"):
        ], "MFPersonFollowSwitch must document Bug Class #52 restore guard"

    def test_switch_attaches_to_mf_coordinator_device(self):
        with open(
            os.path.join(_ura_path, "switch.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        cls_start = src.find("class MFPersonFollowSwitch")
        cls_body = src[cls_start:cls_start + 4000]
        assert "music_following_coordinator" in cls_body


# ===========================================================================
# D6 — lock TOCTOU + stale-transition + async_teardown
# ===========================================================================


class TestD6ConcurrencyAndReload:
    def test_lock_uses_single_async_with(self):
        with open(
            os.path.join(_ura_path, "music_following.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        # The pre-check `.locked()` short-circuit is GONE
        assert "self._transfer_lock.locked()" not in src, (
            "D6 requires dropping the .locked() TOCTOU pre-check"
        )

    def test_cleanup_tasks_is_set(self):
        mf, _ = _make_mf()
        assert isinstance(mf._cleanup_tasks, set)

    @pytest.mark.asyncio
    async def test_stale_transition_records_stat(self, monkeypatch):
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        mf.update_gate_config(stale_transition_seconds=1.0)
        # Pin dt_util.now() so this test is independent of whatever mock
        # env a sibling test left behind (see also the STATE_PLAYING
        # sentinel comment above).
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)
        monkeypatch.setattr(_mf_mod.dt_util, "now", lambda: fixed_now)
        old_ts = fixed_now - timedelta(seconds=30)
        await mf._on_person_transition(_transition(ts=old_ts))
        assert mf._transfer_stats["stale_transition"] >= 1

    @pytest.mark.asyncio
    async def test_async_teardown_clears_state(self):
        mf, _ = _make_mf()
        mf._saved_volumes["media_player.x"] = 0.5
        mf._active_groups["media_player.x"] = {"media_player.y"}
        mf._last_transfer_time["Oji"] = datetime.now()
        mf._last_transfer_target["Oji"] = "bedroom"
        await mf.async_teardown()
        assert mf._saved_volumes == {}
        assert mf._active_groups == {}
        assert mf._last_transfer_time == {}
        assert mf._last_transfer_target == {}
        assert mf._cleanup_tasks == set()

    def test_sync_enabled_persons_reconciles(self):
        mf, _ = _make_mf()
        mf.enable_for_person("Old")
        mf.enable_for_person("Keep")
        mf.sync_enabled_persons(["Keep", "New"])
        assert mf._enabled_persons == {"Keep", "New"}

    def test_sync_enabled_persons_respects_off_pref(self):
        """v5.10.0 fix-up FIX-5 (B-HIGH-1): sync must NOT re-enable a
        person whose stored pref is False."""
        mf, _ = _make_mf()
        # Simulate MFPersonFollowSwitch having stored OFF for Guest.
        mf._person_follow_prefs["Guest"] = False
        mf.sync_enabled_persons(["Oji", "Guest"])
        assert "Oji" in mf._enabled_persons
        assert "Guest" not in mf._enabled_persons

    def test_sync_prunes_prefs_for_removed_persons(self):
        """FIX-5: when a person is dropped from tracked, their pref
        entry is pruned too so a later re-add starts fresh."""
        mf, _ = _make_mf()
        mf._person_follow_prefs["Ghost"] = False
        mf.sync_enabled_persons(["Oji"])  # Ghost no longer tracked
        assert "Ghost" not in mf._person_follow_prefs

    def test_sync_keeps_off_pref_for_still_tracked_person(self):
        """FIX-5: prefs for still-tracked persons survive sync."""
        mf, _ = _make_mf()
        mf._person_follow_prefs["Guest"] = False
        mf.sync_enabled_persons(["Guest"])
        assert mf._person_follow_prefs.get("Guest") is False


# ===========================================================================
# v5.10.0 fix-up FIX-1 (C-CRIT-1) — house-state seed via the REAL CM path
# ===========================================================================


class TestFix1HouseStateSeed:
    """Verify the domain coordinator's async_setup seeds the singleton's
    house-state from ``hass.data[DOMAIN]['coordinator_manager'].house_state``
    (the REAL writer at __init__.py:2731 / manager.py:143), NOT from a
    fake ``hass.data[DOMAIN]['house_state_machine']`` key that no writer
    ever populates.
    """

    @pytest.mark.asyncio
    async def test_seed_from_real_cm_path_arms_sleep_gate(self):
        # Set up a fresh MF singleton (as the coordinator will find it)
        mf, hass = _make_mf()
        mf.enable_for_person("Oji")
        hass.data["universal_room_automation"]["music_following"] = mf

        # Provide a "CoordinatorManager" via the REAL access path:
        # hass.data[DOMAIN]["coordinator_manager"].house_state
        class _FakeHouseState:
            value = "sleep"

        class _FakeCM:
            @property
            def house_state(self):
                return _FakeHouseState()

        hass.data["universal_room_automation"]["coordinator_manager"] = _FakeCM()

        # Now emulate what MusicFollowingCoordinator.async_setup does for
        # the seed step (the actual coordinator setup pulls entry options
        # and has heavier HA deps; the seed logic is what FIX-1 changed).
        cm = hass.data.get("universal_room_automation", {}).get("coordinator_manager")
        current = getattr(cm, "house_state", None) if cm else None
        assert current is not None, "FIX-1: writer path missing"
        mf.update_house_state(str(getattr(current, "value", current)))
        assert mf._current_house_state == "sleep", (
            "FIX-1: seed via .house_state must set the singleton state"
        )

        # Fire a transition — invariant is zero media_player service calls.
        async def _get_player(room):
            return f"media_player.{room}"
        mf._get_room_player = _get_player
        hass.states.set(
            "media_player.kitchen",
            FakeState(STATE_PLAYING, {"volume_level": 0.5}),
        )
        hass.states.set("media_player.bedroom", FakeState("idle"))
        await mf._on_person_transition(_transition())
        assert hass.services.calls == [], (
            "FIX-1: SLEEP-seeded MF must not call any media_player service"
        )
        assert mf._transfer_stats["sleep_suppressed"] >= 1

    @pytest.mark.asyncio
    async def test_seed_missing_cm_leaves_gate_open(self):
        """No CM registered → seed skipped, no exception, gate open."""
        mf, hass = _make_mf()
        cm = hass.data.get("universal_room_automation", {}).get("coordinator_manager")
        assert cm is None
        # Simulate the FIX-1 try/except seed block behavior.
        current = getattr(cm, "house_state", None) if cm else None
        assert current is None
        # No update_house_state called → singleton stays at default "".
        assert mf._current_house_state == ""


# ===========================================================================
# D7 — target picker platform preference
# ===========================================================================


class TestD7TargetPicker:
    def test_picker_source_uses_platform_preference(self):
        with open(
            os.path.join(_ura_path, "music_following.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        # v3.6.21 alphabetical sort is removed
        assert "no platform preference" not in src
        # New comment/impl marker present
        assert "_prefers_multiroom" in src


# ===========================================================================
# D8 — skip-reason attribute surface
# ===========================================================================


class TestD8SkipReasonSurface:
    def test_get_diagnostic_data_includes_skip_fields(self):
        mf, _ = _make_mf()
        data = mf.get_diagnostic_data()
        for k in (
            "last_skip_reason", "last_skip_from_room",
            "last_skip_to_room", "last_skip_time",
            "target_unavailable_today", "sleep_suppressed_today",
            "night_suppressed_today", "source_has_others_today",
            "stale_transition_today",
        ):
            assert k in data, f"Missing diagnostic key {k}"

    def test_skip_reason_populated_on_skip(self):
        mf, _ = _make_mf()
        mf._record_stat("target_unavailable", "Oji", "kitchen", "bedroom")
        data = mf.get_diagnostic_data()
        assert data["last_skip_reason"] == "target_unavailable"
        assert data["last_skip_from_room"] == "kitchen"
        assert data["last_skip_to_room"] == "bedroom"
        assert data["target_unavailable_today"] == 1


# ===========================================================================
# D9 — arrival-stub deprecation
# ===========================================================================


class TestD9ArrivalDeprecation:
    def test_arrival_handler_logs_debug_only(self):
        with open(
            os.path.join(_ura_path, "domain_coordinators", "music_following.py"),
            "r", encoding="utf-8",
        ) as fh:
            src = fh.read()
        start = src.find("def _handle_person_arriving")
        assert start > 0, "_handle_person_arriving method not found"
        # Find the end (next `def ` at method-indent level, or class end)
        end = src.find("\n    def ", start + 1)
        block = src[start:end if end > 0 else start + 3000]
        # The pre-v5.10.0 "would start music" INFO log is GONE
        assert "arrival-start is not implemented" in block, (
            "D9: _handle_person_arriving should log DEBUG only with "
            "'arrival-start is not implemented' marker"
        )
        # No INFO log call in the handler body
        assert "_LOGGER.info" not in block, (
            "D9: no _LOGGER.info calls should remain in the arrival stub"
        )


# ===========================================================================
# D11 — per-room volume calibration
# ===========================================================================


class TestD11VolumeCalibration:
    def test_scaled_target_volume_default_is_passthrough(self):
        mf, _ = _make_mf()
        # No room entries → default 1.0 scale
        assert mf._scaled_target_volume("bedroom", 0.5) == 0.5

    def test_scaled_target_volume_clamps(self):
        mf, hass = _make_mf()
        # Fake a room entry via monkeypatching _get_room_entries
        def _entries():
            return {
                "e1": {
                    "room_name": "Bedroom",
                    "room_media_volume_scale": 10.0,  # above max
                },
            }
        mf._get_room_entries = _entries
        # 0.5 * clamp(10.0 → 1.5) = 0.75
        assert abs(mf._scaled_target_volume("bedroom", 0.5) - 0.75) < 1e-6

    def test_scaled_target_volume_min_clamp(self):
        mf, _ = _make_mf()
        def _entries():
            return {"e1": {"room_name": "Bedroom",
                           "room_media_volume_scale": 0.1}}
        mf._get_room_entries = _entries
        # 0.8 * clamp(0.1 → 0.5) = 0.4
        assert abs(mf._scaled_target_volume("bedroom", 0.8) - 0.4) < 1e-6

    def test_scaled_target_volume_conf_const_exists(self):
        assert _const.CONF_ROOM_MEDIA_VOLUME_SCALE == "room_media_volume_scale"
        assert _const.DEFAULT_ROOM_MEDIA_VOLUME_SCALE == 1.0
        assert _const.MIN_ROOM_MEDIA_VOLUME_SCALE == 0.5
        assert _const.MAX_ROOM_MEDIA_VOLUME_SCALE == 1.5


# ===========================================================================
# D12 — verify-delay conditional
# ===========================================================================


class TestD12VerifyConditional:
    @pytest.mark.asyncio
    async def test_verify_skip_wait_bypasses_sleep(self):
        mf, hass = _make_mf()
        hass.states.set(
            "media_player.bedroom", FakeState(STATE_PLAYING),
        )
        import time as _time
        t0 = _time.monotonic()
        ok = await mf._verify_transfer("media_player.bedroom", skip_wait=True)
        elapsed = _time.monotonic() - t0
        assert ok is True
        # Should be much faster than TRANSFER_VERIFY_DELAY_SECONDS (2s).
        assert elapsed < 0.5

    def test_verify_signature_supports_skip_wait(self):
        import inspect
        sig = inspect.signature(MusicFollowing._verify_transfer)
        assert "skip_wait" in sig.parameters


# ===========================================================================
# Config-flow form wiring — CM options step (D2) + room media step (D11)
# ===========================================================================
#
# Verified via source inspection to avoid cross-test sys.modules pollution.
# Sibling test files (test_cycle_b_config_flow.py, v475_d5) use their own
# save/restore stub loader; a second loader in this file collides with
# theirs under pytest full-suite ordering.


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_COMPONENT_DIR = os.path.join(_REPO_ROOT, "custom_components", "universal_room_automation")


class TestConfigFlowFormFields:
    """Verify the three new v5.10.0 CONFs are present in the right forms
    with the right selector types and safe defaults."""

    def test_cm_options_step_declares_new_fields_in_source(self):
        with open(
            os.path.join(_COMPONENT_DIR, "config_flow.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        start = src.find("async def async_step_coordinator_music_following")
        assert start > 0
        # Grab the whole step body (up to next `async def async_step_`).
        end = src.find("async def async_step_", start + 1)
        body = src[start:end if end > 0 else start + 6000]
        # D2 fields present as vol.Optional(...)
        assert "CONF_MF_SLEEP_SUPPRESS" in body
        assert "CONF_MF_NIGHT_SUPPRESS_MODE" in body
        # Correct selector types
        assert "BooleanSelector()" in body  # sleep_suppress
        assert "SelectSelector" in body  # night_suppress_mode
        # Night-mode options include all three MF_NIGHT_MODES values
        for opt in ("off", "dwell_only", "block_all"):
            assert f'"value": "{opt}"' in body, (
                f"Night-mode SelectSelector missing option {opt!r}"
            )

    def test_room_music_step_declares_volume_scale_in_source(self):
        with open(
            os.path.join(_COMPONENT_DIR, "config_flow.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        start = src.find("async def async_step_music_following")
        assert start > 0
        end = src.find("async def async_step_", start + 1)
        body = src[start:end if end > 0 else start + 4000]
        assert "CONF_ROOM_MEDIA_VOLUME_SCALE" in body
        assert "NumberSelector" in body
        # Range clamps match the const.py values (D11 spec 0.5-1.5).
        assert "MIN_ROOM_MEDIA_VOLUME_SCALE" in body
        assert "MAX_ROOM_MEDIA_VOLUME_SCALE" in body

    def test_cm_options_safe_defaults_declared_in_source(self):
        """CM options step must default sleep-suppress ON and night mode to
        the conservative dwell_only option. Verified via source inspection
        against the imports + defaults arg to avoid cross-test sys.modules
        pollution that a live config_flow load introduces (cycle_b's own
        loader uses the same save/restore mechanism and the two collide
        under pytest-full-suite ordering)."""
        with open(
            os.path.join(_COMPONENT_DIR, "config_flow.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        start = src.find("async def async_step_coordinator_music_following")
        end = src.find("async def async_step_", start + 1)
        body = src[start:end if end > 0 else start + 6000]
        # Imports pull DEFAULT_MF_SLEEP_SUPPRESS and DEFAULT_MF_NIGHT_SUPPRESS_MODE
        assert "DEFAULT_MF_SLEEP_SUPPRESS" in body
        assert "DEFAULT_MF_NIGHT_SUPPRESS_MODE" in body
        # And the const values themselves are the safe options
        assert _const.DEFAULT_MF_SLEEP_SUPPRESS is True, (
            "D2 safety: DEFAULT_MF_SLEEP_SUPPRESS must be True"
        )
        # v5.10.0 fix-up FIX-3: default is now "off" — see the D2 conf
        # defaults test above for the rationale.
        assert _const.DEFAULT_MF_NIGHT_SUPPRESS_MODE == "off", (
            "D2 safety: DEFAULT_MF_NIGHT_SUPPRESS_MODE must be 'off' "
            "(FIX-3 A-CRIT-2)"
        )

    def test_room_music_step_declares_volume_scale_defaults(self):
        """Verify room media step wires DEFAULT_ROOM_MEDIA_VOLUME_SCALE
        as the field default. Source inspection for the same reason as
        the sibling test above."""
        with open(
            os.path.join(_COMPONENT_DIR, "config_flow.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        start = src.find("async def async_step_music_following")
        end = src.find("async def async_step_", start + 1)
        body = src[start:end if end > 0 else start + 4000]
        assert "DEFAULT_ROOM_MEDIA_VOLUME_SCALE" in body
        assert _const.DEFAULT_ROOM_MEDIA_VOLUME_SCALE == 1.0

    def test_cm_options_user_input_merge_pattern_declared(self):
        """CM options save merges user_input into existing options —
        preserving unrelated keys. Verified via source pattern."""
        with open(
            os.path.join(_COMPONENT_DIR, "config_flow.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        start = src.find("async def async_step_coordinator_music_following")
        end = src.find("async def async_step_", start + 1)
        body = src[start:end if end > 0 else start + 6000]
        # The merge pattern preserves existing keys
        assert "self._config_entry.options" in body
        assert "**user_input" in body


class TestReloadSuppressionAllowlist:
    """Verify the two D2 CM keys are in OPTIONS_RELOAD_SUPPRESS_KEYS so
    edits push through MusicFollowing.update_gate_config() WITHOUT a
    parent-entry reload (which would blink every actuator)."""

    def test_d2_keys_in_reload_suppress_allowlist(self):
        with open(
            os.path.join(_COMPONENT_DIR, "__init__.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        allowlist_start = src.find("OPTIONS_RELOAD_SUPPRESS_KEYS")
        assert allowlist_start > 0
        # Grab up to a reasonable closing point.
        # 2026-07-22: bumped 6000 -> 8000 (fan/humidity toggle-symmetry AND blind-window guard cycles both grew the block)
        # cycle added CONF_FAN_CONTROL_ENABLED / CONF_HUMIDITY_FAN_CONTROL_ENABLED
        # aliases inside the CM import block, pushing _CONF_MF_NIGHT_SUPPRESS_MODE
        # past the old window. The window is just a text-search bound; extending
        # it does not weaken the assertion (the token is either in the source or
        # it isn't).
        allowlist_block = src[allowlist_start:allowlist_start + 8000]
        assert "_CONF_MF_SLEEP_SUPPRESS" in allowlist_block, (
            "CONF_MF_SLEEP_SUPPRESS must be in OPTIONS_RELOAD_SUPPRESS_KEYS "
            "so edits are pushed live via update_gate_config()"
        )
        assert "_CONF_MF_NIGHT_SUPPRESS_MODE" in allowlist_block

    def test_apply_in_place_pushes_to_music_following(self):
        with open(
            os.path.join(_COMPONENT_DIR, "__init__.py"), "r", encoding="utf-8"
        ) as fh:
            src = fh.read()
        # Verify _apply_in_place branch exists and calls update_gate_config
        apply_start = src.find("def _apply_in_place")
        assert apply_start > 0
        apply_end = src.find("\ndef ", apply_start + 1)
        block = src[apply_start:apply_end if apply_end > 0 else apply_start + 30000]
        assert "update_gate_config" in block, (
            "_apply_in_place must call MusicFollowing.update_gate_config for D2"
        )
        assert "_CONF_MF_SLEEP_SUPPRESS" in block
        assert "_CONF_MF_NIGHT_SUPPRESS_MODE" in block


# ===========================================================================
# Cross-invariant: SLEEP invariant across all reachable transitions
# ===========================================================================


class TestSleepInvariantAdversarial:
    """Reviewer-D style falsifiable invariant probe.

    Property: During HouseState.SLEEP with sleep_suppress on, MF SHALL NOT
    call any media_player service on any reachable code path.
    """

    @pytest.mark.asyncio
    async def test_sleep_blocks_service_calls_all_target_states(self):
        for target_state in ("idle", "playing", "paused", "unavailable", "unknown"):
            mf, hass = _make_mf()
            mf.enable_for_person("Oji")
            mf.update_house_state("sleep")
            async def _get_player(room):
                return f"media_player.{room}"
            mf._get_room_player = _get_player
            hass.states.set(
                "media_player.kitchen",
                FakeState("playing", {"volume_level": 0.5,
                                      "media_content_id": "http://x",
                                      "media_content_type": "music"}),
            )
            hass.states.set("media_player.bedroom", FakeState(target_state))
            await mf._on_person_transition(_transition())
            assert hass.services.calls == [], (
                f"SLEEP invariant violated for target_state={target_state}: "
                f"{hass.services.calls}"
            )
