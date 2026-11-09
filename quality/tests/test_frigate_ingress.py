"""PERIMETER-FRIGATE-MQTT-DIRECT-1 + FRIGATE-FACE-BRIDGE-DEAD-PREFIX-1.

Plan: docs/planning/PLANNING_frigate_mqtt_direct_2026_11.md (rev 2).
Drives the PRODUCTION `FrigateEventIngress` (frigate_ingress.py) and the
`__init__` setup/teardown helpers with a fake bus / fake MQTT. Every fake is
installed through `monkeypatch` (restored after each test; no permanent
sys.modules surgery). Expected values are literals or come from the live D0
fixture (`fixtures/frigate_events_mqtt_live.json`, bus twins captured
independently of this code), never from the code under test.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os as _os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

_os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import pytest

import custom_components.universal_room_automation as ura_pkg
from custom_components.universal_room_automation import const as C
from custom_components.universal_room_automation import frigate_ingress as fi

FIXTURE = Path(__file__).parent / "fixtures" / "frigate_events_mqtt_live.json"
EV = "frigate_events"


def _pairs(case: str | None = None) -> list[dict]:
    pairs = json.loads(FIXTURE.read_text())["pairs"]
    return [p for p in pairs if case is None or p["case"] == case]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeEntry:
    def __init__(self, entry_id: str, data=None, options=None):
        self.entry_id = entry_id
        self.data = dict(data or {})
        self.options = dict(options or {})


class FakeEntries:
    def __init__(self, entries):
        self.entries = list(entries)

    def async_entries(self, domain):
        return list(self.entries) if domain == "frigate" else []


class FakeBus:
    def __init__(self):
        self.listeners: list[tuple[str, object]] = []

    def _add(self, ev, cb):
        rec = (ev, cb)
        self.listeners.append(rec)

        def _unsub():
            if rec in self.listeners:
                self.listeners.remove(rec)

        return _unsub

    def async_listen(self, ev, cb):
        return self._add(ev, cb)

    def async_listen_once(self, ev, cb):
        return self._add(ev, cb)

    def count(self, ev):
        return sum(1 for e, _ in self.listeners if e == ev)

    def fire(self, ev, data):
        for e, cb in list(self.listeners):
            if e == ev:
                cb(SimpleNamespace(event_type=ev, data=data))


class FakeHass:
    def __init__(self, entries=(), runtime=None, is_running=True):
        self.data = {C.DOMAIN: {}}
        if runtime is not None:
            self.data["frigate"] = runtime
        self.bus = FakeBus()
        self.config_entries = FakeEntries(entries)
        self.is_running = is_running

    def async_create_task(self, coro, *a, **k):
        return asyncio.get_running_loop().create_task(coro)


class FakeMqtt:
    def __init__(self):
        self.subs: dict[str, list] = {}
        self.calls: list[str] = []
        self.fail = False
        self.gate: asyncio.Event | None = None

    async def async_subscribe(self, hass, topic, cb, *a, **k):
        self.calls.append(topic)
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("Cannot subscribe: MQTT not set up")
        self.subs.setdefault(topic, []).append(cb)

        def _unsub():
            lst = self.subs.get(topic, [])
            if cb in lst:
                lst.remove(cb)

        return _unsub

    def active(self):
        return {t: len(v) for t, v in self.subs.items() if v}

    def publish(self, topic, payload, retain=False):
        for cb in list(self.subs.get(topic, [])):
            cb(SimpleNamespace(topic=topic, payload=payload, retain=retain, qos=0))


def rt(prefix="frigate2", eid="E2"):
    return {eid: {"config": {"mqtt": {"topic_prefix": prefix}}}}


@pytest.fixture
def mqtt(monkeypatch):
    fake = FakeMqtt()
    mod = importlib.import_module("homeassistant.components.mqtt")
    monkeypatch.setattr(mod, "async_subscribe", fake.async_subscribe)
    pkg = importlib.import_module("homeassistant.components")
    if getattr(pkg, "mqtt", None) is not None and pkg.mqtt is not mod:
        monkeypatch.setattr(pkg.mqtt, "async_subscribe", fake.async_subscribe)
    return fake


@pytest.fixture
def hooks(monkeypatch):
    rec: dict[str, list] = {"when_setup": [], "intervals": []}
    setup_mod = importlib.import_module("homeassistant.setup")
    monkeypatch.setattr(
        setup_mod, "async_when_setup",
        lambda hass, comp, cb: rec["when_setup"].append((comp, cb)),
    )
    ev_mod = importlib.import_module("homeassistant.helpers.event")

    def _ti(hass, cb, interval):
        item = (cb, interval)
        rec["intervals"].append(item)

        def _u():
            if item in rec["intervals"]:
                rec["intervals"].remove(item)

        return _u

    monkeypatch.setattr(ev_mod, "async_track_time_interval", _ti)
    return rec


async def _drain():
    for _ in range(8):
        await asyncio.sleep(0)


async def _up(hass):
    ing = fi.FrigateEventIngress(hass)
    hass.data[C.DOMAIN][fi.FRIGATE_INGRESS_HASS_KEY] = ing
    await ing.async_setup()
    await _drain()
    return ing


def _rec(ing, name="c"):
    seen: list[tuple[str, object]] = []
    ing.register_consumer(name, lambda d, s: seen.append((s, d)))
    return seen


def _when(hooks, comp):
    return [cb for c, cb in hooks["when_setup"] if c == comp][0]


def _dual_hass():
    return FakeHass(entries=[FakeEntry("E2")], runtime=rt())


# ===========================================================================
# D1: prefix discovery + normaliser
# ===========================================================================
def test_prefix_discovery_reads_frigate_runtime_config():
    hass = FakeHass(
        entries=[
            # Entry data/options carry decoy keys: never read.
            FakeEntry("E1", data={"topic_prefix": "decoy"}, options={"mqtt_topic_prefix": "decoy2"}),
            FakeEntry("E2"),
        ],
        runtime={**rt("frigate_a/", "E1"), **rt("frigate2", "E2"), "llm_unregister": object()},
    )
    assert fi.discover_frigate_topic_prefixes(hass) == {"frigate_a", "frigate2"}


def test_prefix_discovery_empty_when_frigate_absent():
    assert fi.discover_frigate_topic_prefixes(FakeHass(entries=[FakeEntry("E2")])) == set()
    # Entry present, runtime data missing keys at each level -> empty.
    for runtime in ({}, {"E2": {}}, {"E2": {"config": {}}}, {"E2": {"config": {"mqtt": {}}}},
                    {"E2": {"config": {"mqtt": {"topic_prefix": "  "}}}}):
        hass = FakeHass(entries=[FakeEntry("E2", data={"topic_prefix": "frigate"})], runtime=runtime)
        assert fi.discover_frigate_topic_prefixes(hass) == set()
    # Runtime data for an entry that is not a frigate entry -> ignored.
    assert fi.discover_frigate_topic_prefixes(FakeHass(entries=[], runtime=rt())) == set()


def test_normalise_matches_live_bus_fixture():
    pairs = _pairs()
    assert len(pairs) == 16
    for p in pairs:
        got = fi.normalise_frigate_event_payload(p["mqtt_payload"])
        assert got == p["bus_data"]
        # Key order matches the bridge automation (before, after, type).
        assert json.dumps(got) == json.dumps(p["bus_data"])


def test_normalise_defaults_null_and_bad_payloads():
    assert fi.normalise_frigate_event_payload('{"type": "new"}') == {
        "before": {}, "after": {}, "type": "new",
    }
    assert fi.normalise_frigate_event_payload('{"before": null, "after": {"id": "x"}}') == {
        "before": None, "after": {"id": "x"}, "type": "",
    }
    assert fi.normalise_frigate_event_payload(b'{"type": "end"}')["type"] == "end"
    for bad in ("not json", "[1, 2]", "3", None, 7):
        assert fi.normalise_frigate_event_payload(bad) is None


def test_mqtt_absent_bus_only_unchanged(monkeypatch, hooks):
    import sys
    pkg = importlib.import_module("homeassistant.components")
    monkeypatch.delattr(pkg, "mqtt", raising=False)
    monkeypatch.setitem(sys.modules, "homeassistant.components.mqtt", None)

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        seen = _rec(ing)
        p = _pairs("person_face")[0]
        hass.bus.fire(EV, p["bus_data"])
        return ing, seen, p

    ing, seen, p = asyncio.run(_t())
    assert ing._mqtt_subs == {}
    assert seen == [("bus", p["bus_data"])]


def test_mqtt_subscribe_raises_inert(mqtt, hooks):
    mqtt.fail = True

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        seen = _rec(ing)
        hass.bus.fire(EV, _pairs("person_face")[0]["bus_data"])
        return ing, seen

    ing, seen = asyncio.run(_t())
    assert mqtt.calls == ["frigate2/events"]
    assert ing._mqtt_subs == {}
    assert [s for s, _ in seen] == ["bus"]


# ===========================================================================
# D2: dedup source latch
# ===========================================================================
def test_dual_source_exactly_once_preserves_updates(mqtt, hooks):
    person = _pairs("person_zoned")
    assert len(person) == 7  # 1 new + 5 update + 1 end, one event id

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        t = [1000.0]
        ing._clock = lambda: t[0]
        seen = _rec(ing)
        for p in person:  # MQTT first, bus twin 50 ms later
            mqtt.publish("frigate2/events", p["mqtt_payload"])
            t[0] += 0.05
            hass.bus.fire(EV, p["bus_data"])
            t[0] += 1.0
        return ing, seen

    ing, seen = asyncio.run(_t())
    # Under the rejected (id, type) key this would be 2 (new + one update).
    assert len(seen) == 7
    assert [d for _, d in seen] == [p["bus_data"] for p in person]
    assert {s for s, _ in seen} == {"mqtt:frigate2"}
    assert ing.dedup_dropped == {"bus": 7, "mqtt": 0}


def test_replay_byte_identical_dual_source(mqtt, hooks):
    """INV-3: the sequence each consumer receives with both sources live
    equals the bus-only sequence (all 16 fixture messages, 3 events)."""
    pairs = _pairs()

    async def _bus_only():
        hass = FakeHass(entries=[FakeEntry("E2")])  # no runtime -> no MQTT
        ing = await _up(hass)
        a, b = _rec(ing, "perimeter"), _rec(ing, "linker")
        for p in pairs:
            hass.bus.fire(EV, p["bus_data"])
        return a, b

    async def _dual():
        hass = _dual_hass()
        ing = await _up(hass)
        a, b = _rec(ing, "perimeter"), _rec(ing, "linker")
        for p in pairs:
            mqtt.publish("frigate2/events", p["mqtt_payload"])
            hass.bus.fire(EV, p["bus_data"])
        return a, b

    a0, b0 = asyncio.run(_bus_only())
    a1, b1 = asyncio.run(_dual())
    dump = lambda seq: [json.dumps(d) for _, d in seq]  # noqa: E731
    assert len(a0) == 16
    assert dump(a1) == dump(a0) and dump(b1) == dump(b0)


def test_bus_first_then_mqtt_drops_mqtt(mqtt, hooks):
    p_new, p_upd = _pairs("person_face")[:2]

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        t = [50.0]
        ing._clock = lambda: t[0]
        seen = _rec(ing)
        hass.bus.fire(EV, p_new["bus_data"])
        t[0] += 0.1
        mqtt.publish("frigate2/events", p_new["mqtt_payload"])
        mqtt.publish("frigate2/events", p_upd["mqtt_payload"])
        hass.bus.fire(EV, p_upd["bus_data"])
        return ing, seen

    ing, seen = asyncio.run(_t())
    assert [s for s, _ in seen] == ["bus", "bus"]
    assert ing.dedup_dropped == {"bus": 0, "mqtt": 2}


def test_latch_failover_after_ttl(mqtt, hooks, monkeypatch):
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_SOURCE_LATCH_TTL_S", 30)
    new, upd1, upd2, upd3, upd4 = _pairs("person_zoned")[:5]

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        t = [0.0]
        ing._clock = lambda: t[0]
        seen = _rec(ing)
        mqtt.publish("frigate2/events", new["mqtt_payload"])       # t=0
        t[0] = 1.0
        mqtt.publish("frigate2/events", upd1["mqtt_payload"])      # t=1 (last mqtt)
        t[0] = 1.05
        hass.bus.fire(EV, new["bus_data"])                          # dropped
        t[0] = 30.9  # 29.9 s after the last MQTT message: inside the TTL
        hass.bus.fire(EV, upd2["bus_data"])                         # dropped
        t[0] = 31.0  # exactly 30 s: latch expired -> bus takes over
        hass.bus.fire(EV, upd3["bus_data"])                         # dispatched
        t[0] = 31.5
        mqtt.publish("frigate2/events", upd4["mqtt_payload"])      # now dropped
        return ing, seen

    ing, seen = asyncio.run(_t())
    assert [s for s, _ in seen] == ["mqtt:frigate2", "mqtt:frigate2", "bus"]
    assert seen[2][1] == upd3["bus_data"]
    assert ing.dedup_dropped == {"bus": 2, "mqtt": 1}


def test_ttl_floor_clamp(mqtt, hooks, monkeypatch):
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_SOURCE_LATCH_TTL_S", 1)
    assert fi.effective_latch_ttl_s() == 10.0
    new, upd = _pairs("person_face")[:2]

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        t = [0.0]
        ing._clock = lambda: t[0]
        seen = _rec(ing)
        mqtt.publish("frigate2/events", new["mqtt_payload"])
        t[0] = 9.0   # floor - 1 s: still latched to mqtt
        hass.bus.fire(EV, new["bus_data"])
        t[0] = 10.0  # floor: expired
        hass.bus.fire(EV, upd["bus_data"])
        return seen

    seen = asyncio.run(_t())
    assert [s for s, _ in seen] == ["mqtt:frigate2", "bus"]


def test_latch_bounded(mqtt, hooks, monkeypatch):
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_LATCH_MAX", 3)

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        ing._clock = lambda: 5.0
        for i in range(5):
            mqtt.publish("frigate2/events", json.dumps(
                {"type": "new", "before": {}, "after": {"id": f"id{i}", "camera": "c", "label": "person"}}))
        return ing

    ing = asyncio.run(_t())
    assert list(ing._latch) == ["id2", "id3", "id4"]


def test_latch_prunes_expired_on_insert(mqtt, hooks, monkeypatch):
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_SOURCE_LATCH_TTL_S", 30)

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        t = [0.0]
        ing._clock = lambda: t[0]
        for i, at in enumerate((0.0, 5.0, 40.0)):
            t[0] = at
            mqtt.publish("frigate2/events", json.dumps(
                {"type": "new", "after": {"id": f"id{i}"}}))
        return ing

    ing = asyncio.run(_t())
    # id0 (40 s old) and id1 (35 s old) are past the 30 s TTL.
    assert list(ing._latch) == ["id2"]


def test_idless_single_family(mqtt, hooks):
    idless = {"type": "update", "before": {}, "after": {"camera": "g5_bullet", "label": "person"}}

    async def _with_mqtt():
        hass = _dual_hass()
        ing = await _up(hass)
        seen = _rec(ing)
        hass.bus.fire(EV, idless)
        mqtt.publish("frigate2/events", json.dumps(idless))
        return ing, seen

    async def _bus_only():
        hass = FakeHass(entries=[FakeEntry("E2")])
        ing = await _up(hass)
        seen = _rec(ing)
        hass.bus.fire(EV, idless)
        return ing, seen

    ing, seen = asyncio.run(_with_mqtt())
    assert [s for s, _ in seen] == ["mqtt:frigate2"]
    assert ing.idless == 2 and ing.dedup_dropped == {"bus": 1, "mqtt": 0}
    ing, seen = asyncio.run(_bus_only())
    assert [s for s, _ in seen] == ["bus"]
    assert ing.dedup_dropped == {"bus": 0, "mqtt": 0}


def test_retained_events_skipped(mqtt, hooks):
    p = _pairs("person_face")[0]

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        seen = _rec(ing)
        mqtt.publish("frigate2/events", p["mqtt_payload"], retain=True)
        mqtt.publish("frigate2/events", p["mqtt_payload"], retain=False)
        return ing, seen

    ing, seen = asyncio.run(_t())
    assert len(seen) == 1
    assert ing.mqtt_retained_skipped == 1
    assert ing.diag_stats()["frigate_ingress_mqtt_24h"] == 1


def test_bad_payload_counted(mqtt, hooks):
    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        seen = _rec(ing)
        mqtt.publish("frigate2/events", "not json")
        mqtt.publish("frigate2/events", "[1, 2]")
        return ing, seen

    ing, seen = asyncio.run(_t())
    assert seen == [] and ing.mqtt_bad_payload == 2


def test_consumer_exception_isolated(mqtt, hooks):
    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)

        def _boom(d, s):
            raise RuntimeError("consumer bug")

        ing.register_consumer("a", _boom)
        seen = _rec(ing, "b")
        hass.bus.fire(EV, _pairs("person_face")[0]["bus_data"])
        return seen

    assert len(asyncio.run(_t())) == 1


def test_unregister_only_removes_own_fn(mqtt, hooks):
    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        old_unreg = ing.register_consumer("p", lambda d, s: None)
        seen = _rec(ing, "p")  # re-registration replaces under the same name
        old_unreg()
        hass.bus.fire(EV, _pairs("person_face")[0]["bus_data"])
        return seen

    assert len(asyncio.run(_t())) == 1


# ===========================================================================
# D3: lifecycle / load order
# ===========================================================================
def test_load_order_matrix(mqtt, hooks):
    async def _mqtt_before():
        hass = _dual_hass()
        await _up(hass)
        return mqtt.active()

    assert asyncio.run(_mqtt_before()) == {"frigate2/events": 1}


def test_load_order_mqtt_after_ura(mqtt, hooks):
    async def _t():
        mqtt.fail = True
        hass = _dual_hass()
        ing = await _up(hass)
        assert mqtt.active() == {}
        mqtt.fail = False
        await _when(hooks, "mqtt")(hass, "mqtt")
        await _when(hooks, "mqtt")(hass, "mqtt")  # idempotent
        await ing.async_reconcile()
        return mqtt.active()

    assert asyncio.run(_t()) == {"frigate2/events": 1}


def test_load_order_frigate_after_ura(mqtt, hooks):
    async def _t():
        hass = FakeHass(entries=[FakeEntry("E2")])
        await _up(hass)
        assert mqtt.active() == {}
        hass.data["frigate"] = rt()
        await _when(hooks, "frigate")(hass, "frigate")
        return mqtt.active()

    assert asyncio.run(_t()) == {"frigate2/events": 1}


def test_started_hook_reconciles(mqtt, hooks):
    async def _t():
        hass = FakeHass(entries=[FakeEntry("E2")], is_running=False)
        ing = await _up(hass)
        assert hass.bus.count("homeassistant_started") == 1
        hass.data["frigate"] = rt()  # Frigate entry finished setup later
        hass.bus.fire("homeassistant_started", {})
        await _drain()
        return ing

    ing = asyncio.run(_t())
    assert mqtt.active() == {"frigate2/events": 1}
    assert ing._unsub_started is None


def test_periodic_reconcile_subscribes_late_prefix(mqtt, hooks):
    async def _t():
        hass = FakeHass(entries=[FakeEntry("E2")])
        await _up(hass)
        assert len(hooks["intervals"]) == 1
        cb, interval = hooks["intervals"][0]
        assert interval.total_seconds() == 300
        hass.data["frigate"] = rt()
        cb(None)
        await _drain()

    asyncio.run(_t())
    assert mqtt.active() == {"frigate2/events": 1}


def test_reconcile_interval_zero_disables_timer(mqtt, hooks, monkeypatch):
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_RECONCILE_S", 0)

    async def _t():
        await _up(_dual_hass())

    asyncio.run(_t())
    assert hooks["intervals"] == []


def test_mqtt_kill_switch_bus_only(mqtt, hooks, monkeypatch):
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_MQTT_ENABLED", False)

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        seen = _rec(ing)
        hass.bus.fire(EV, _pairs("person_face")[0]["bus_data"])
        return seen

    seen = asyncio.run(_t())
    assert mqtt.calls == [] and [s for s, _ in seen] == ["bus"]


def test_unload_drains_all_subs(mqtt, hooks):
    async def _t():
        hass = FakeHass(entries=[FakeEntry("E2")], runtime=rt(), is_running=False)
        ing = await _up(hass)
        ing.register_topic_handler("tracked_object_update", "census_face", lambda m: None)
        await _drain()
        assert mqtt.active() == {"frigate2/events": 1, "frigate2/tracked_object_update": 1}
        assert hass.bus.count(EV) == 1 and hass.bus.count("homeassistant_started") == 1
        ing.async_teardown()
        return hass, ing

    hass, ing = asyncio.run(_t())
    assert mqtt.active() == {}
    assert hass.bus.count(EV) == 0 and hass.bus.count("homeassistant_started") == 0
    assert hooks["intervals"] == []
    assert ing._consumers == {} and ing._topic_handlers == {}


def test_late_when_setup_after_unload_noop(mqtt, hooks):
    async def _t():
        hass = FakeHass(entries=[FakeEntry("E2")])
        ing = await _up(hass)
        ing.async_teardown()
        hass.data[C.DOMAIN].pop(fi.FRIGATE_INGRESS_HASS_KEY, None)
        hass.data["frigate"] = rt()
        await _when(hooks, "mqtt")(hass, "mqtt")
        await _when(hooks, "frigate")(hass, "frigate")

    asyncio.run(_t())
    assert mqtt.calls == []


def test_late_when_setup_on_replaced_ingress_noop(mqtt, hooks):
    """Liveness guard: an old ingress whose hass.data slot now holds a NEW
    instance never subscribes (its teardown is unreachable)."""
    async def _t():
        hass = FakeHass(entries=[FakeEntry("E2")])
        await _up(hass)
        old_cb = _when(hooks, "frigate")
        hass.data[C.DOMAIN][fi.FRIGATE_INGRESS_HASS_KEY] = object()
        hass.data["frigate"] = rt()
        await old_cb(hass, "frigate")

    asyncio.run(_t())
    assert mqtt.calls == []


def test_teardown_during_inflight_subscribe_unsubs(mqtt, hooks):
    async def _t():
        mqtt.gate = asyncio.Event()
        hass = _dual_hass()
        ing = fi.FrigateEventIngress(hass)
        hass.data[C.DOMAIN][fi.FRIGATE_INGRESS_HASS_KEY] = ing
        task = asyncio.get_running_loop().create_task(ing.async_reconcile())
        await _drain()
        ing.async_teardown()
        mqtt.gate.set()
        await task
        return ing

    ing = asyncio.run(_t())
    assert mqtt.calls == ["frigate2/events"]
    assert mqtt.active() == {} and ing._mqtt_subs == {}


def test_orphan_callback_after_teardown_inert(mqtt, hooks):
    """HA restores subscriptions across an MQTT entry reload
    (mqtt/__init__.py:643-646 -> :433-438), so an old unsub may not reach
    the restored subscription. A torn-down ingress's callbacks are inert."""
    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        ing.register_topic_handler("tracked_object_update", "f", lambda m: hits.append(m))
        await _drain()
        seen = _rec(ing)
        events_cb = mqtt.subs["frigate2/events"][0]
        face_cb = mqtt.subs["frigate2/tracked_object_update"][0]
        ing.async_teardown()
        events_cb(SimpleNamespace(payload=_pairs("person_face")[0]["mqtt_payload"], retain=False))
        face_cb(SimpleNamespace(payload="{}", retain=False))
        return ing, seen

    hits: list = []
    ing, seen = asyncio.run(_t())
    assert seen == [] and hits == []
    # The orphan neither latches nor counts (torn-down guard, not just the
    # cleared consumer map).
    assert len(ing._latch) == 0
    assert ing.diag_stats()["frigate_ingress_mqtt_24h"] == 0


def test_reload_no_orphan_subscription(mqtt, hooks):
    async def _t():
        hass = _dual_hass()
        await fi.async_setup_frigate_ingress(hass)
        first = hass.data[C.DOMAIN][fi.FRIGATE_INGRESS_HASS_KEY]
        await _drain()
        await fi.async_setup_frigate_ingress(hass)
        await _drain()
        await fi.async_setup_frigate_ingress(hass)
        await _drain()
        return hass, first

    hass, first = asyncio.run(_t())
    assert mqtt.active() == {"frigate2/events": 1}
    assert first._torn_down is True
    assert hass.bus.count(EV) == 1


def test_frigate_unload_gap_keeps_subscription(mqtt, hooks):
    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        hass.data.pop("frigate")  # Frigate entry unloaded / NotReady retry
        await ing.async_reconcile()
        return ing

    ing = asyncio.run(_t())
    assert mqtt.active() == {"frigate2/events": 1}
    assert ing.subscribed_prefixes() == ["frigate2"]


def test_ingress_failure_legacy_fallback(mqtt, hooks, monkeypatch):
    async def _boom(self):
        raise RuntimeError("ingress setup bug")

    monkeypatch.setattr(fi.FrigateEventIngress, "async_setup", _boom)

    async def _t():
        hass = _dual_hass()
        await fi.async_setup_frigate_ingress(hass)
        seen: list = []
        fi.register_frigate_consumer(hass, "perimeter", lambda d, s: seen.append((s, d)))
        p = _pairs("person_face")[0]
        hass.bus.fire(EV, p["bus_data"])
        return hass, seen, p

    hass, seen, p = asyncio.run(_t())
    assert fi.FRIGATE_INGRESS_HASS_KEY not in hass.data[C.DOMAIN]
    assert seen == [("bus", p["bus_data"])]


def test_single_frigate_events_listener_site(mqtt, hooks):
    """Plan §4 build gate, behavioural form: with the ingress present the
    consumers add NO bus listener of their own."""
    async def _t():
        hass = _dual_hass()
        await _up(hass)
        fi.register_frigate_consumer(hass, "perimeter", lambda d, s: None)
        fi.register_frigate_consumer(hass, "linker", lambda d, s: None)
        return hass

    assert asyncio.run(_t()).bus.count(EV) == 1


def test_unload_entry_tears_down_ingress(mqtt, hooks):
    """Wire-in anchor for the async_unload_entry call site.

    Needs the REAL package __init__. Sibling files (e.g.
    test_exterior_track_linker) leave a stub package in sys.modules, and
    conftest deliberately does not restore `custom_components.*`
    (conftest.py:43-47), so in those orders this anchor cannot run; it runs
    when this file is collected first (cycle-file runs, mutation drills)."""
    if not hasattr(ura_pkg, "async_unload_entry"):
        pytest.skip("stub URA package resident in sys.modules (collection order)")

    async def _t():
        hass = _dual_hass()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        ing = await _up(hass)
        entry = SimpleNamespace(
            entry_id="ura_int",
            data={C.CONF_ENTRY_TYPE: C.ENTRY_TYPE_INTEGRATION},
            options={},
        )
        assert await ura_pkg.async_unload_entry(hass, entry) is True
        return hass, ing

    hass, ing = asyncio.run(_t())
    assert ing._torn_down is True
    assert mqtt.active() == {}
    assert fi.FRIGATE_INGRESS_HASS_KEY not in hass.data[C.DOMAIN]


# ===========================================================================
# D4: diagnostics + face topic handler
# ===========================================================================
def test_ingress_diag_attrs(mqtt, hooks):
    pairs = _pairs("person_face")

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        for p in pairs:
            mqtt.publish("frigate2/events", p["mqtt_payload"])
            hass.bus.fire(EV, p["bus_data"])
        mqtt.publish("frigate2/events", "bad")
        return ing

    assert asyncio.run(_t()).diag_stats() == {
        "frigate_ingress_prefixes": ["frigate2"],
        "frigate_ingress_mqtt_24h": 4,
        "frigate_ingress_bus_24h": 3,
        "frigate_ingress_dedup_dropped": 3,
        "frigate_ingress_mqtt_bad_payload": 1,
        "frigate_ingress_mqtt_retained_skipped": 0,
        "frigate_ingress_idless": 0,
    }


def test_topic_handler_subscribes_each_prefix_even_with_kill_switch(mqtt, hooks, monkeypatch):
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_MQTT_ENABLED", False)

    async def _t():
        hass = FakeHass(entries=[FakeEntry("E1"), FakeEntry("E2")],
                        runtime={**rt("frigate_a", "E1"), **rt("frigate2", "E2")})
        ing = await _up(hass)
        got: list = []
        ing.register_topic_handler("tracked_object_update", "census_face", got.append)
        await _drain()
        mqtt.publish("frigate2/tracked_object_update", '{"type": "face"}', retain=True)
        return got

    got = asyncio.run(_t())
    assert mqtt.active() == {
        "frigate_a/tracked_object_update": 1, "frigate2/tracked_object_update": 1,
    }
    # Raw message handed through, retain flag intact (handler's policy).
    assert len(got) == 1 and got[0].retain is True


# ===========================================================================
# Review C fix-ups (v5.108.1_frigate_mqtt_C.md)
# ===========================================================================
_IDLESS = {"type": "update", "before": {}, "after": {"camera": "g5_bullet", "label": "person"}}


def test_c3_idless_bus_delivered_with_kill_switch_and_face_handler(mqtt, hooks, monkeypatch):
    """C-3: kill switch off + face topic subscribed -> only the EVENTS
    subscription makes MQTT own id-less messages, so the bus copy is
    delivered."""
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_MQTT_ENABLED", False)

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        ing.register_topic_handler("tracked_object_update", "census_face", lambda m: None)
        await _drain()
        seen = _rec(ing)
        hass.bus.fire(EV, _IDLESS)
        return ing, seen

    ing, seen = asyncio.run(_t())
    assert mqtt.active() == {"frigate2/tracked_object_update": 1}
    assert seen == [("bus", _IDLESS)]
    assert ing.dedup_dropped == {"bus": 0, "mqtt": 0}


def test_c5_concurrent_reconcile_single_subscribe(mqtt, hooks):
    async def _t():
        mqtt.gate = asyncio.Event()
        hass = _dual_hass()
        ing = fi.FrigateEventIngress(hass)
        hass.data[C.DOMAIN][fi.FRIGATE_INGRESS_HASS_KEY] = ing
        loop = asyncio.get_running_loop()
        t1 = loop.create_task(ing.async_reconcile())
        t2 = loop.create_task(ing.async_reconcile())
        await _drain()
        mqtt.gate.set()
        await asyncio.gather(t1, t2)

    asyncio.run(_t())
    assert mqtt.calls == ["frigate2/events"]
    assert mqtt.active() == {"frigate2/events": 1}


def test_c6_teardown_cancels_tracked_pending_reconcile(mqtt, hooks):
    async def _t():
        mqtt.gate = asyncio.Event()
        hass = _dual_hass()
        ing = fi.FrigateEventIngress(hass)
        hass.data[C.DOMAIN][fi.FRIGATE_INGRESS_HASS_KEY] = ing
        ing.register_topic_handler("tracked_object_update", "f", lambda m: None)
        await _drain()  # the scheduled reconcile is now blocked in subscribe
        tasks = list(ing._tasks)
        assert len(tasks) == 1 and not tasks[0].done()
        ing.async_teardown()
        await _drain()
        # Checked inside the loop: asyncio.run cancels leftovers at exit.
        cancelled_in_loop = tasks[0].done() and tasks[0].cancelled()
        mqtt.gate.set()
        await _drain()
        return ing, cancelled_in_loop

    ing, cancelled_in_loop = asyncio.run(_t())
    assert cancelled_in_loop is True
    assert ing._tasks == set() and mqtt.active() == {}


def test_c7_refreshed_key_moves_back_so_expired_are_pruned(mqtt, hooks, monkeypatch):
    monkeypatch.setattr(fi._c, "FRIGATE_INGRESS_SOURCE_LATCH_TTL_S", 30)

    def _new(i):
        return json.dumps({"type": "update", "after": {"id": f"id{i}"}})

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        t = [0.0]
        ing._clock = lambda: t[0]
        mqtt.publish("frigate2/events", _new(0))   # t=0
        t[0] = 1.0
        mqtt.publish("frigate2/events", _new(1))   # t=1
        t[0] = 20.0
        mqtt.publish("frigate2/events", _new(0))   # refresh id0 at t=20
        t[0] = 40.0
        mqtt.publish("frigate2/events", _new(2))   # id1 is 39 s old -> expired
        return ing

    assert list(asyncio.run(_t())._latch) == ["id0", "id2"]


def test_c8_consumer_name_collision_warns(mqtt, hooks, caplog):
    import logging

    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        fn = lambda d, s: None  # noqa: E731
        with caplog.at_level(logging.WARNING):
            ing.register_consumer("perimeter", fn)
            ing.register_consumer("perimeter", fn)  # same fn: re-setup, quiet
            assert "re-registered" not in caplog.text
            ing.register_consumer("perimeter", lambda d, s: None)
        return ing

    asyncio.run(_t())
    assert caplog.text.count("consumer name 'perimeter' re-registered") == 1


def test_c14_topic_handlers_isolated_and_all_called(mqtt, hooks):
    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        got: list = []

        def _boom(m):
            raise RuntimeError("handler bug")

        ing.register_topic_handler("tracked_object_update", "a", _boom)
        ing.register_topic_handler("tracked_object_update", "b", got.append)
        ing.register_topic_handler("tracked_object_update", "c", got.append)
        await _drain()
        mqtt.publish("frigate2/tracked_object_update", "{}")
        return got

    assert len(asyncio.run(_t())) == 2


def test_c14_topic_unregister_only_own_fn_and_no_handler_no_subscribe(mqtt, hooks):
    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        old = ing.register_topic_handler("tracked_object_update", "f", lambda m: None)
        got: list = []
        ing.register_topic_handler("tracked_object_update", "f", got.append)
        old()  # stale unregister must not remove the replacement
        await _drain()
        mqtt.publish("frigate2/tracked_object_update", "{}")
        # A suffix whose handlers were all removed is not subscribed on a
        # later prefix.
        gone = ing.register_topic_handler("reviews", "r", lambda m: None)
        gone()
        hass.data["frigate"]["E3"] = {"config": {"mqtt": {"topic_prefix": "frigate3"}}}
        hass.config_entries.entries.append(FakeEntry("E3"))
        await ing.async_reconcile()
        return got

    got = asyncio.run(_t())
    assert len(got) == 1
    assert "frigate3/reviews" not in mqtt.calls
    assert "frigate3/events" in mqtt.calls


def test_c14_non_mapping_bus_data_ignored(mqtt, hooks):
    async def _t():
        hass = _dual_hass()
        ing = await _up(hass)
        seen = _rec(ing)
        hass.bus.fire(EV, ["not", "a", "mapping"])
        hass.bus.fire(EV, None)
        return ing, seen

    ing, seen = asyncio.run(_t())
    assert seen == [] and ing.idless == 0
