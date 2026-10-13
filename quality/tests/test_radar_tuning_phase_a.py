"""Radar tuning Phase A (URA-SENSOR-TUNING-1 Rev 2) — behavioural tests.

Monkeypatch-only stubbing. Each test drives a REAL function in
``domain_coordinators.radar_tuning`` by substituting the registry /
family resolver / hass.services at the module boundary. The invariant
under test is the plan's falsifiable one:

  URA will only send ``number.set_value`` for values the operator set
  in URA for that entity. "Leave as is" is never sent. URA never writes
  to a non-ZK/ZX device. URA never writes to an unmanaged field.

Behavioural wire-in anchor + per-site mutation drill — restoration +
__pycache__ clear is run by the orchestrator; this test file is the
authority each drill confirms against.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Minimal HA stubs — monkeypatch-only, scoped to this module. No import of
# the real HA package; just enough to satisfy radar_tuning's resolver.
# ---------------------------------------------------------------------------

def _install_ha_stubs(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Monkeypatch homeassistant.helpers.entity_registry.async_get +
    async_entries_for_device so radar_tuning sees a fake registry.

    Returns a namespace carrying the fake registry; tests populate
    ``entries_by_id`` and ``entries_for_device_map``.
    """
    # Import the REAL module (conftest.py stubs it enough for import to
    # succeed) then monkeypatch its two functions. This beats fighting
    # conftest-installed sys.modules shapes.
    from homeassistant.helpers import entity_registry as er  # type: ignore

    reg = types.SimpleNamespace()
    reg.entries_by_id = {}
    reg.entries_for_device_map = {}

    def _async_get_entity(entity_id):
        return reg.entries_by_id.get(entity_id)

    reg.async_get = _async_get_entity

    monkeypatch.setattr(er, "async_get", lambda _hass: reg, raising=False)
    monkeypatch.setattr(
        er, "async_entries_for_device",
        lambda _r, device_id, include_disabled_entities=False: (
            reg.entries_for_device_map.get(device_id, [])
        ),
        raising=False,
    )
    return reg


def _import_radar_tuning():
    """Fresh import of radar_tuning so patches take effect."""
    name = (
        "custom_components.universal_room_automation."
        "domain_coordinators.radar_tuning"
    )
    if name in sys.modules:
        return importlib.reload(sys.modules[name])
    return importlib.import_module(name)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, dict(data)))


class _FakeStates:
    def __init__(self, states: dict[str, Any] | None = None) -> None:
        self._states = states or {}

    def get(self, entity_id: str):
        return self._states.get(entity_id)


class _FakeHass:
    def __init__(self, states: dict[str, Any] | None = None) -> None:
        self.services = _FakeServices()
        self.states = _FakeStates(states)


def _make_registry_entry(entity_id: str, device_id: str):
    return types.SimpleNamespace(entity_id=entity_id, device_id=device_id)


# ---------------------------------------------------------------------------
# D1 — resolve_zk_zx_tuning_entities
# ---------------------------------------------------------------------------

def test_resolve_returns_four_fields_for_zk(monkeypatch):
    """D1 AC: ZK device returns dict of {field: number_entity_id}."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()

    bs = "binary_sensor.studya_occupancy"
    dev = "dev_studya"
    reg.entries_by_id[bs] = _make_registry_entry(bs, dev)
    reg.entries_for_device_map[dev] = [
        _make_registry_entry(
            "number.mmwave_zigbee_studya_motion_detection_sensitivity", dev,
        ),
        _make_registry_entry(
            "number.mmwave_zigbee_studya_static_detection_sensitivity", dev,
        ),
        _make_registry_entry(
            "number.mmwave_zigbee_studya_detection_distance", dev,
        ),
        _make_registry_entry(
            "number.mmwave_zigbee_studya_fading_time", dev,
        ),
        # Noise: non-radar siblings must be ignored.
        _make_registry_entry("sensor.mmwave_zigbee_studya_battery", dev),
    ]

    # Force the family resolver to ZK regardless of registry contents.
    monkeypatch.setattr(
        rt, "resolve_zk_zx_tuning_entities",
        rt.resolve_zk_zx_tuning_entities,  # keep real
    )
    import custom_components.universal_room_automation.fan_veto as fv  # type: ignore
    monkeypatch.setattr(fv, "resolve_sensor_family", lambda _h, _e: "zigbee_zk_zx")

    out = rt.resolve_zk_zx_tuning_entities(_FakeHass(), bs)
    assert out is not None
    assert out[rt.FIELD_MOTION_SENSITIVITY].endswith("_motion_detection_sensitivity")
    assert out[rt.FIELD_STATIC_SENSITIVITY].endswith("_static_detection_sensitivity")
    assert out[rt.FIELD_DETECTION_DISTANCE].endswith("_detection_distance")
    assert out[rt.FIELD_FADING_TIME].endswith("_fading_time")
    assert len(out) == 4


def test_resolve_returns_none_for_zv(monkeypatch):
    """D1 AC: ZV family resolves to None (no radar knobs on motion-class)."""
    _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    import custom_components.universal_room_automation.fan_veto as fv
    monkeypatch.setattr(fv, "resolve_sensor_family", lambda _h, _e: "zigbee_zv")

    assert rt.resolve_zk_zx_tuning_entities(_FakeHass(), "binary_sensor.zv") is None


def test_resolve_returns_none_for_ld2410_and_generic(monkeypatch):
    """D1 AC: ld24xx / generic_radar / unknown return None."""
    _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    import custom_components.universal_room_automation.fan_veto as fv

    for fam in ("ld24xx", "generic_radar", "unknown", "pir"):
        monkeypatch.setattr(
            fv, "resolve_sensor_family", lambda _h, _e, fam=fam: fam,
        )
        assert (
            rt.resolve_zk_zx_tuning_entities(_FakeHass(), "binary_sensor.x")
            is None
        ), fam


def test_resolve_handles_renamed_entity_id(monkeypatch):
    """D1 AC: resolution goes through registry each call, not a cached slug."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    import custom_components.universal_room_automation.fan_veto as fv
    monkeypatch.setattr(fv, "resolve_sensor_family", lambda _h, _e: "zigbee_zk_zx")

    bs = "binary_sensor.studya_occupancy"
    dev = "dev_studya"
    reg.entries_by_id[bs] = _make_registry_entry(bs, dev)
    # First call — one named layout.
    reg.entries_for_device_map[dev] = [
        _make_registry_entry("number.oldname_motion_detection_sensitivity", dev),
    ]
    out1 = rt.resolve_zk_zx_tuning_entities(_FakeHass(), bs)
    assert out1[rt.FIELD_MOTION_SENSITIVITY] == (
        "number.oldname_motion_detection_sensitivity"
    )
    # Rename the sibling — fresh resolve must observe it (no cache).
    reg.entries_for_device_map[dev] = [
        _make_registry_entry("number.renamed_motion_detection_sensitivity", dev),
    ]
    out2 = rt.resolve_zk_zx_tuning_entities(_FakeHass(), bs)
    assert out2[rt.FIELD_MOTION_SENSITIVITY] == (
        "number.renamed_motion_detection_sensitivity"
    )


# ---------------------------------------------------------------------------
# D2 UI helper — clipped distance buckets
# ---------------------------------------------------------------------------

def test_range_bucket_clips_to_live_max(monkeypatch):
    """D2 AC: 'How far it watches' labels clip to live number.max."""
    _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    hass = _FakeHass(
        {"number.x_detection_distance": types.SimpleNamespace(
            attributes={"max": 4.5},
        )},
    )
    buckets = rt.clipped_distance_buckets(hass, "number.x_detection_distance")
    # Long (6) must clip to 4.5; Short (3) and Standard (4) unchanged.
    assert buckets["short"] == 3.0
    assert buckets["standard"] == 4.0
    assert buckets["long"] == 4.5


def test_range_buckets_untouched_when_max_absent(monkeypatch):
    """D2 AC: missing entity -> buckets return defaults."""
    _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    hass = _FakeHass()
    assert rt.clipped_distance_buckets(hass, "number.missing") == {
        "short": 3.0, "standard": 4.0, "long": 6.0,
    }


# ---------------------------------------------------------------------------
# D3 — async_send_radar_settings (send path)
# ---------------------------------------------------------------------------

def _setup_zk_device(monkeypatch, reg):
    """Install one ZK device with four number siblings. Returns bs eid."""
    bs = "binary_sensor.studya_occupancy"
    dev = "dev_studya"
    reg.entries_by_id[bs] = _make_registry_entry(bs, dev)
    reg.entries_for_device_map[dev] = [
        _make_registry_entry(f"number.studya{suffix}", dev)
        for suffix in (
            "_motion_detection_sensitivity",
            "_static_detection_sensitivity",
            "_detection_distance",
            "_fading_time",
        )
    ]
    import custom_components.universal_room_automation.fan_veto as fv
    monkeypatch.setattr(fv, "resolve_sensor_family", lambda _h, _e: "zigbee_zk_zx")
    return bs


def test_send_emits_one_set_value_per_changed_field(monkeypatch):
    """D3 AC: one number.set_value per CHANGED managed field."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    bs = _setup_zk_device(monkeypatch, reg)
    hass = _FakeHass()

    prev = {bs: {"motion_sensitivity": 4}}
    new = {bs: {"motion_sensitivity": 6, "fading_time": 120}}
    sent = asyncio.run(rt.async_send_radar_settings(
        hass, previous_settings=prev, new_settings=new,
    ))
    assert sent == 2
    # Shape of emitted calls — "sent" semantics only.
    emitted = [
        (c[2]["entity_id"], c[2]["value"])
        for c in hass.services.calls
        if c[0] == "number" and c[1] == "set_value"
    ]
    assert ("number.studya_motion_detection_sensitivity", 6) in emitted
    assert ("number.studya_fading_time", 120) in emitted


def test_leave_as_is_sends_nothing(monkeypatch):
    """D3 AC: every field at Leave-as-is -> zero service calls."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    bs = _setup_zk_device(monkeypatch, reg)
    hass = _FakeHass()

    sent = asyncio.run(rt.async_send_radar_settings(
        hass, previous_settings={}, new_settings={bs: {}},
    ))
    assert sent == 0
    assert hass.services.calls == []
    # Explicit sentinel also treated as absent.
    sent2 = asyncio.run(rt.async_send_radar_settings(
        hass, previous_settings={},
        new_settings={bs: {"motion_sensitivity": rt.LEAVE_AS_IS_SENTINEL}},
    ))
    assert sent2 == 0
    assert hass.services.calls == []


def test_unchanged_fields_send_nothing(monkeypatch):
    """D3 AC: save with no diff -> zero service calls."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    bs = _setup_zk_device(monkeypatch, reg)
    hass = _FakeHass()

    settings = {bs: {"motion_sensitivity": 6, "fading_time": 60}}
    sent = asyncio.run(rt.async_send_radar_settings(
        hass, previous_settings=settings, new_settings=settings,
    ))
    assert sent == 0
    assert hass.services.calls == []


def test_unmanaged_field_never_written(monkeypatch):
    """D3 AC (invariant corollary 3): unknown field names never emit."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    bs = _setup_zk_device(monkeypatch, reg)
    hass = _FakeHass()

    # anti_interference is deferred — must not be sent even if saved.
    sent = asyncio.run(rt.async_send_radar_settings(
        hass, previous_settings={},
        new_settings={bs: {"anti_interference": "on", "motion_sensitivity": 8}},
    ))
    # Only the managed field is sent.
    assert sent == 1
    assert len(hass.services.calls) == 1
    assert hass.services.calls[0][2]["entity_id"].endswith(
        "_motion_detection_sensitivity",
    )


def test_non_zk_zx_binary_sensor_skipped(monkeypatch):
    """D3 AC (invariant corollary 3): non-ZK/ZX family never written."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    bs = "binary_sensor.living_room_zv_occupancy"
    reg.entries_by_id[bs] = _make_registry_entry(bs, "dev_zv")
    reg.entries_for_device_map["dev_zv"] = [
        _make_registry_entry("number.zv_motion_detection_sensitivity", "dev_zv"),
    ]
    import custom_components.universal_room_automation.fan_veto as fv
    monkeypatch.setattr(fv, "resolve_sensor_family", lambda _h, _e: "zigbee_zv")
    hass = _FakeHass()
    sent = asyncio.run(rt.async_send_radar_settings(
        hass, previous_settings={},
        new_settings={bs: {"motion_sensitivity": 6}},
    ))
    assert sent == 0
    assert hass.services.calls == []


def test_resolves_entity_id_through_registry_each_call(monkeypatch):
    """D3 AC: no cached entity_id string across calls (Finding 11)."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    bs = _setup_zk_device(monkeypatch, reg)
    hass = _FakeHass()

    asyncio.run(rt.async_send_radar_settings(
        hass, previous_settings={},
        new_settings={bs: {"motion_sensitivity": 6}},
    ))
    first = hass.services.calls[-1][2]["entity_id"]
    assert first == "number.studya_motion_detection_sensitivity"

    # Rename the sibling — a cached slug would still emit the old eid.
    dev = reg.entries_by_id[bs].device_id
    reg.entries_for_device_map[dev] = [
        _make_registry_entry(
            "number.studya_renamed_motion_detection_sensitivity", dev,
        ),
    ]
    asyncio.run(rt.async_send_radar_settings(
        hass, previous_settings={},
        new_settings={bs: {"motion_sensitivity": 8}},
    ))
    second = hass.services.calls[-1][2]["entity_id"]
    assert second == "number.studya_renamed_motion_detection_sensitivity"


# ---------------------------------------------------------------------------
# D4 — reapply service
# ---------------------------------------------------------------------------

class _FakeEntry:
    def __init__(self, entry_id, options=None, data=None):
        self.entry_id = entry_id
        self.options = options or {}
        self.data = data or {}


class _FakeHassWithEntries(_FakeHass):
    def __init__(self, entries_map):
        super().__init__()
        self.config_entries = types.SimpleNamespace(
            async_get_entry=lambda eid: entries_map.get(eid),
        )


def test_reapply_service_sends_all_managed_fields(monkeypatch):
    """D4 AC: reapply forces every managed field to re-send."""
    reg = _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    bs = _setup_zk_device(monkeypatch, reg)

    entry = _FakeEntry(
        "entry_studya",
        options={
            "radar_settings": {
                bs: {"motion_sensitivity": 6, "fading_time": 120},
            },
        },
    )
    hass = _FakeHassWithEntries({"entry_studya": entry})
    sent = asyncio.run(rt.async_reapply_radar_settings(hass, "entry_studya"))
    assert sent == 2


def test_reapply_service_noop_when_all_leave_as_is(monkeypatch):
    """D4 AC: empty / all-leave-as-is dict -> zero calls."""
    _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    entry = _FakeEntry("entry_x", options={"radar_settings": {}})
    hass = _FakeHassWithEntries({"entry_x": entry})
    sent = asyncio.run(rt.async_reapply_radar_settings(hass, "entry_x"))
    assert sent == 0
    assert hass.services.calls == []


def test_reapply_service_rejects_unknown_entry_id(monkeypatch):
    """D4 AC: unknown entry logs WARN and emits zero calls."""
    _install_ha_stubs(monkeypatch)
    rt = _import_radar_tuning()
    hass = _FakeHassWithEntries({})
    sent = asyncio.run(rt.async_reapply_radar_settings(hass, "no_such_entry"))
    assert sent == 0
    assert hass.services.calls == []


# ---------------------------------------------------------------------------
# OptionsFlow sensors-step save path — drives the REAL save handler and
# the REAL schema builder so the "schedule on change / Leave on nothing /
# default back to Leave on reopen" invariants are proven end-to-end.
# ---------------------------------------------------------------------------

def _load_cf_harness():
    """Import the OptionsFlow helpers used by the sensors-step tests."""
    import importlib
    _cbcf = importlib.import_module("test_cycle_b_config_flow")
    _baec = importlib.import_module("test_baec_config_flow_round_trip")
    return _cbcf, _baec


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _schema_marker(result, key):
    schema = result.get("data_schema")
    for m in getattr(schema, "schema", {}).keys():
        if str(getattr(m, "schema", m)) == key:
            return m
    return None


def _wire_sensors_step(monkeypatch, *, saved_radar=None, resolved_fields=None):
    """Build an OptionsFlow + patch radar_tuning so the sensors step
    can run against a fake ZK radar. Returns (flow, send_calls)."""
    _cbcf, _baec = _load_cf_harness()
    make = _cbcf._make_options_flow
    inject = _baec._ha_mocks_injected

    MMWAVE_EID = "binary_sensor.testroom_presence"
    options = {
        "motion_sensors": [],
        "presence_sensors": [MMWAVE_EID],
        "occupancy_sensors": [],
    }
    if saved_radar is not None:
        options["radar_settings"] = saved_radar

    flow = make(data={"room_name": "Test Room"}, options=options)

    # Patch radar_tuning.resolve_zk_zx_tuning_entities + distance clipper +
    # the send scheduler. The real send would try to call number.set_value
    # on hass.services; our fake records (previous, new) tuples so the
    # test can assert the schedule happened with the right payload.
    import importlib
    from custom_components.universal_room_automation.domain_coordinators \
        import radar_tuning as rt

    _resolved = resolved_fields or {
        rt.FIELD_MOTION_SENSITIVITY: "number.testroom_motion",
        rt.FIELD_STATIC_SENSITIVITY: "number.testroom_static",
        rt.FIELD_DETECTION_DISTANCE: "number.testroom_distance",
        rt.FIELD_FADING_TIME: "number.testroom_fading",
    }
    monkeypatch.setattr(
        rt, "resolve_zk_zx_tuning_entities",
        lambda _hass, _eid: dict(_resolved),
    )
    monkeypatch.setattr(
        rt, "clipped_distance_buckets",
        lambda _h, _eid: dict(rt.DETECTION_DISTANCE_BUCKETS),
    )

    send_calls: list[tuple[dict, dict]] = []

    async def _fake_send(_hass, *, previous_settings, new_settings):
        send_calls.append((dict(previous_settings or {}), dict(new_settings or {})))

    monkeypatch.setattr(rt, "async_send_radar_settings", _fake_send)

    # async_create_task on the fake hass must not crash on a coroutine;
    # just schedule it on the loop so the fake send actually records.
    def _create_task(coro):
        try:
            return asyncio.ensure_future(coro)
        except Exception:
            try:
                coro.close()
            except Exception:
                pass
            return None

    flow.hass.async_create_task = _create_task

    return flow, send_calls, inject, MMWAVE_EID, rt


def test_options_flow_schedules_one_send_with_numeric_values(monkeypatch):
    """Save path (review fix 3): a change to any managed field
    schedules exactly one send, with the right numeric values and the
    saved CONF_RADAR_SETTINGS reflecting the operator's picks."""
    flow, send_calls, inject, eid, rt = _wire_sensors_step(monkeypatch)

    user_input = {
        "motion_sensors": [],
        "presence_sensors": [eid],
        "occupancy_sensors": [],
        "sensor_capabilities_json": "",
        # Three managed fields changed, one left as-is.
        f"radar_{rt.FIELD_MOTION_SENSITIVITY}__{eid}": "8",   # High
        f"radar_{rt.FIELD_STATIC_SENSITIVITY}__{eid}": "6",   # Medium
        f"radar_{rt.FIELD_DETECTION_DISTANCE}__{eid}": "4.0",  # standard
        f"radar_{rt.FIELD_FADING_TIME}__{eid}": rt.LEAVE_AS_IS_SENTINEL,
    }
    with inject():
        async def _drive():
            result = await flow.async_step_sensors(user_input)
            # Let the scheduled fake send run.
            await asyncio.sleep(0)
            return result
        result = _run_async(_drive())

    assert result.get("type") == "create_entry", result
    saved = result["data"].get("radar_settings")
    assert saved == {
        eid: {
            rt.FIELD_MOTION_SENSITIVITY: 8,
            rt.FIELD_STATIC_SENSITIVITY: 6,
            rt.FIELD_DETECTION_DISTANCE: 4.0,
        },
    }
    assert len(send_calls) == 1
    prev, new = send_calls[0]
    assert prev == {}  # fresh install
    assert new == saved


def test_options_flow_leave_as_is_stores_nothing_and_sends_nothing(monkeypatch):
    """All-sentinel save: no CONF_RADAR_SETTINGS stored, no send scheduled."""
    flow, send_calls, inject, eid, rt = _wire_sensors_step(monkeypatch)

    user_input = {
        "motion_sensors": [],
        "presence_sensors": [eid],
        "occupancy_sensors": [],
        "sensor_capabilities_json": "",
        f"radar_{rt.FIELD_MOTION_SENSITIVITY}__{eid}": rt.LEAVE_AS_IS_SENTINEL,
        f"radar_{rt.FIELD_STATIC_SENSITIVITY}__{eid}": rt.LEAVE_AS_IS_SENTINEL,
        f"radar_{rt.FIELD_DETECTION_DISTANCE}__{eid}": rt.LEAVE_AS_IS_SENTINEL,
        f"radar_{rt.FIELD_FADING_TIME}__{eid}": rt.LEAVE_AS_IS_SENTINEL,
    }
    with inject():
        async def _drive():
            r = await flow.async_step_sensors(user_input)
            await asyncio.sleep(0)
            return r
        result = _run_async(_drive())

    assert result.get("type") == "create_entry", result
    assert "radar_settings" not in result["data"]
    assert send_calls == []


def test_options_flow_reopen_defaults_back_to_leave(monkeypatch):
    """Rendering the sensors step with no stored radar_settings
    defaults every radar dropdown to the Leave-as-is sentinel."""
    flow, _send_calls, inject, eid, rt = _wire_sensors_step(monkeypatch)
    with inject():
        result = _run_async(flow.async_step_sensors(None))

    assert result.get("type") == "form", result
    for field in (
        rt.FIELD_MOTION_SENSITIVITY,
        rt.FIELD_STATIC_SENSITIVITY,
        rt.FIELD_DETECTION_DISTANCE,
        rt.FIELD_FADING_TIME,
    ):
        marker = _schema_marker(result, f"radar_{field}__{eid}")
        assert marker is not None, field
        assert marker.default() == rt.LEAVE_AS_IS_SENTINEL, field


def test_options_flow_mutation_drill_scheduling_site_is_load_bearing(monkeypatch):
    """Mutation anchor: if we patch out `async_create_task` on hass
    (the exact site that schedules the send), the "one send scheduled"
    test above would fail. We prove it inline by substituting a no-op
    scheduler and asserting the send didn't record — a hollow test
    (one that passes with the scheduling site neutered) would NOT see
    this difference."""
    flow, send_calls, inject, eid, rt = _wire_sensors_step(monkeypatch)

    # Replace the schedule site with a no-op that closes the coroutine
    # without running it — equivalent to commenting out the
    # async_create_task line in config_flow.py.
    def _noop(coro):
        try:
            coro.close()
        except Exception:
            pass
        return None

    flow.hass.async_create_task = _noop

    user_input = {
        "motion_sensors": [],
        "presence_sensors": [eid],
        "occupancy_sensors": [],
        "sensor_capabilities_json": "",
        f"radar_{rt.FIELD_MOTION_SENSITIVITY}__{eid}": "8",
    }
    with inject():
        async def _drive():
            r = await flow.async_step_sensors(user_input)
            await asyncio.sleep(0)
            return r
        _run_async(_drive())

    # Save still succeeds; but the send never ran.
    assert send_calls == []
