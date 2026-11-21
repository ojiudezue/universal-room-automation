"""AI-ROOM-RULES-TRUST-REPAIR-1 D6 / D7: decision log, stats, reversal,
digest, zero-fire trip-wire, room-memory episodes (real DB, production DDL).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from _room_rules_rig import Rig, light_rule, run, st
from custom_components.universal_room_automation import const as C
from custom_components.universal_room_automation import room_rules_health as H
from custom_components.universal_room_automation.const import DOMAIN


def _m(name):
    """The module the production code resolves NOW (another file may have
    re-imported the package after this file was collected)."""
    import importlib
    return importlib.import_module(f"custom_components.universal_room_automation.{name}")


def _lamp_states(**extra):
    s = {"light.exercise_lamp": st("off", friendly_name="Exercise Lamp"),
         "fan.exercise_fan": st("off", friendly_name="Exercise Fan")}
    s.update(extra)
    return s


# ---------------------------------------------------------------------------
# D6.1 decision log
# ---------------------------------------------------------------------------


def test_rule_decision_log_line_fields(caplog):
    rig = Rig(rules=[light_rule(conditions=[{"type": "after_dark"}])], states=_lamp_states())
    rig.c.data = {C.STATE_ILLUMINANCE: 180}
    with caplog.at_level(logging.INFO, logger="custom_components.universal_room_automation.coordinator"):
        run(rig.c._run_room_rules(["enter"]))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Room rule decision")]
    assert len(lines) == 1
    line = lines[0]
    for field in ("room=Exercise Room", "rule_id=r1", "source=described", "trigger=enter",
                  "person=-", "outcome=condition_false", "guard=-",
                  "conditions=[after_dark=False]", "actions=-", "ms="):
        assert field in line, (field, line)


def test_rule_stats_and_status_sensor_rules_attr():
    from custom_components.universal_room_automation.sensor import AIAutomationStatusSensor
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    rig.switches["ai_automation"] = False
    run(rig.c._run_room_rules(["enter"]))
    sensor = AIAutomationStatusSensor.__new__(AIAutomationStatusSensor)
    sensor.coordinator = rig.c
    sensor.hass = rig.hass
    assert sensor.native_value == "off"
    rule = sensor.extra_state_attributes["rules"][0]
    assert rule["fires"] == 1 and rule["skips_by_reason"] == {"switch_off": 1}
    assert rule["last_skip_reason"] == "switch_off" and rule["last_fire"]
    assert rule["preview"] == "When someone enters Exercise Room: turn on Exercise Lamp."
    assert rule["status"] == "active"
    assert "rules" in AIAutomationStatusSensor._unrecorded_attributes
    # name: three words or fewer, no "AI"
    assert AIAutomationStatusSensor(rig.c)._attr_name == "Room Rules Status"


@pytest.mark.parametrize("records,switches,expected", [
    ([], {}, "none"),
    ([light_rule()], {"manual_mode": True}, "manual_mode"),
    ([light_rule()], {"ai_automation": False}, "off"),
    ([light_rule(enabled=False)], {}, "off"),
    ([light_rule(), {**light_rule(rule_id="x"), "actions": []}], {}, "needs_parse"),
    ([light_rule()], {}, "active"),
])
def test_status_sensor_states_exact(records, switches, expected):
    from custom_components.universal_room_automation.sensor import AIAutomationStatusSensor
    rig = Rig(rules=records, states=_lamp_states(), switches=switches)
    sensor = AIAutomationStatusSensor.__new__(AIAutomationStatusSensor)
    sensor.coordinator = rig.c
    sensor.hass = rig.hass
    assert sensor.native_value == expected


def test_switch_display_name_is_room_rules():
    from custom_components.universal_room_automation.switch import AiAutomationSwitch
    rig = Rig(rules=[], states={})
    sw = AiAutomationSwitch(rig.c)
    assert sw._attr_name == "Room Rules"
    assert sw._attr_unique_id == "EX1_ai_automation"


# ---------------------------------------------------------------------------
# D6.3 reversal
# ---------------------------------------------------------------------------


class _Ctx:
    def __init__(self, parent_id=None, id_="person-ctx"):
        self.parent_id = parent_id
        self.id = id_
        self.user_id = "u1"


def _light_event(eid, old, new, ctx):
    return SimpleNamespace(data={
        "entity_id": eid,
        "old_state": SimpleNamespace(state=old),
        "new_state": SimpleNamespace(state=new, context=ctx),
    }, context=ctx)


def test_rule_reversal_light_turned_off_by_person():
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    # The person turns the lamp off by hand: the REAL reconciler listener.
    rig.c._actuator_reconciler._handle_state_change(
        _light_event("light.exercise_lamp", "on", "off", _Ctx()))
    run(rig.drain())
    assert rig.c._rule_stats["r1"]["reversals"] == 1
    revs = rig.episodes("room_rule_reversal")
    assert len(revs) == 1 and revs[0]["attrs"]["entity_id"] == "light.exercise_lamp"
    assert revs[0]["node_id"] == "room:exercise_room"


def test_rule_own_action_not_reversal():
    from custom_components.universal_room_automation.ura_context import ura_write_context
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    # URA's own write echo (URA mark), and a same-direction person change.
    rig.c._actuator_reconciler._handle_state_change(
        _light_event("light.exercise_lamp", "off", "on", ura_write_context()))
    rig.c._actuator_reconciler._handle_state_change(
        _light_event("light.exercise_lamp", "off", "on", _Ctx()))
    assert rig.c._rule_stats["r1"]["reversals"] == 0


def test_rule_reversal_window_expired():
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    rig.c._rule_light_watch["light.exercise_lamp"]["r1"]["deadline"] = time.monotonic() - 1
    rig.c._actuator_reconciler._handle_state_change(
        _light_event("light.exercise_lamp", "on", "off", _Ctx()))
    assert rig.c._rule_stats["r1"]["reversals"] == 0


def test_rule_reversal_non_light_target_listener():
    rig = Rig(rules=[light_rule(entity="fan.exercise_fan", data={"percentage": 50})],
              states=_lamp_states())
    captured = {}

    def _track(hass, ids, cb):
        captured["ids"] = list(ids)
        captured["cb"] = cb
        return MagicMock()

    with patch.object(rig.co, "async_track_state_change_event", _track), \
            patch.object(rig.co, "async_call_later", lambda h, d, cb: MagicMock()):
        run(rig.c._run_room_rules(["enter"]))
    assert captured["ids"] == ["fan.exercise_fan"]
    own_ctx = rig.services.rule_calls()[0].context
    assert own_ctx is not None
    cb = captured["cb"]
    # the rule's own state change (its context) is not a reversal
    cb(_light_event("fan.exercise_fan", "off", "on", own_ctx))
    assert rig.c._rule_stats["r1"]["reversals"] == 0
    cb(_light_event("fan.exercise_fan", "on", "off", _Ctx()))
    assert rig.c._rule_stats["r1"]["reversals"] == 1


def test_rule_reversal_watches_cancelled_on_unload():
    rig = Rig(rules=[light_rule(entity="fan.exercise_fan")], states=_lamp_states())
    unsub_track, unsub_timer = MagicMock(), MagicMock()
    with patch.object(rig.co, "async_track_state_change_event", lambda h, i, c: unsub_track), \
            patch.object(rig.co, "async_call_later", lambda h, d, c: unsub_timer):
        run(rig.c._run_room_rules(["enter"]))
    rig.c._cancel_rule_reversal_watches()
    unsub_track.assert_called_once()
    unsub_timer.assert_called_once()


def _capture_watch(rig, rules_states=None):
    captured = {}

    def _track(hass, ids, cb):
        captured["ids"] = list(ids)
        captured["cb"] = cb
        return MagicMock()

    with patch.object(rig.co, "async_track_state_change_event", _track), \
            patch.object(rig.co, "async_call_later", lambda h, d, cb: MagicMock()):
        run(rig.c._run_room_rules(["enter"]))
    return captured


def test_rule_reversal_slow_cover_late_arrival_not_reversal():
    """Review B1: HA drops the call context after 5 s, so a 15 s shade's
    ``closing -> closed`` arrives with a fresh context. Arriving at the
    commanded state (and passing through ``closing``) is not a reversal; a
    real move back to open is."""
    rig = Rig(rules=[light_rule(entity="cover.exercise_shade", service="close_cover")],
              states=_lamp_states(**{"cover.exercise_shade": st("open")}))
    cap = _capture_watch(rig)
    assert cap["ids"] == ["cover.exercise_shade"]
    cb = cap["cb"]
    cb(_light_event("cover.exercise_shade", "open", "closing", _Ctx(id_="late-1")))
    cb(_light_event("cover.exercise_shade", "closing", "closed", _Ctx(id_="late-2")))
    assert rig.c._rule_stats["r1"]["reversals"] == 0
    cb(_light_event("cover.exercise_shade", "closed", "open", _Ctx(id_="hand")))
    assert rig.c._rule_stats["r1"]["reversals"] == 1


def test_rule_reversal_watch_refused_after_unload_cancel():
    """Review B3: a run still in flight after unload's cancel must not arm a
    new listener on the dead coordinator."""
    rig = Rig(rules=[light_rule(entity="fan.exercise_fan")], states=_lamp_states())
    rig.c._cancel_rule_reversal_watches()
    track = MagicMock()
    with patch.object(rig.co, "async_track_state_change_event", track), \
            patch.object(rig.co, "async_call_later", MagicMock()):
        run(rig.c._run_room_rules(["enter"]))
    track.assert_not_called()
    assert rig.c._rule_watch_unsubs == []


def test_rule_reversal_two_rules_same_light_both_credited():
    """Review B4: a second same-direction rule on the light no longer erases
    the first rule's watch; a person's undo credits both."""
    rig = Rig(rules=[light_rule(), light_rule(rule_id="r2")], states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    assert set(rig.c._rule_light_watch["light.exercise_lamp"]) == {"r1", "r2"}
    rig.c._actuator_reconciler._handle_state_change(
        _light_event("light.exercise_lamp", "on", "off", _Ctx()))
    run(rig.drain())
    assert rig.c._rule_stats["r1"]["reversals"] == 1
    assert rig.c._rule_stats["r2"]["reversals"] == 1


def test_rule_reversal_opposite_later_rule_supersedes_earlier():
    """Review B4: a later rule commanding the opposite direction takes the
    light over; the earlier rule is not credited when the person's change
    matches the earlier command."""
    rig = Rig(rules=[light_rule(), light_rule(rule_id="r2", service="turn_off")],
              states=_lamp_states())
    run(rig.c._run_room_rules(["enter"]))
    assert set(rig.c._rule_light_watch["light.exercise_lamp"]) == {"r2"}
    rig.c._actuator_reconciler._handle_state_change(
        _light_event("light.exercise_lamp", "off", "on", _Ctx()))
    run(rig.drain())
    assert rig.c._rule_stats["r2"]["reversals"] == 1
    assert rig.c._rule_stats.get("r1", {}).get("reversals", 0) == 0


# ---------------------------------------------------------------------------
# D6.4 digest
# ---------------------------------------------------------------------------


def test_rules_digest_section():
    rig = Rig(rules=[light_rule(), light_rule(rule_id="r2", person="person.oji_udezue",
                                              trigger="lux_dark")],
              states=_lamp_states())
    rig.hass.data[DOMAIN]["EX1"] = rig.c
    run(rig.c._run_room_rules(["enter"]))
    run(rig.c._run_room_rules(["lux_dark"]))            # person absent
    rig.c._actuator_reconciler._handle_state_change(
        _light_event("light.exercise_lamp", "on", "off", _Ctx()))
    assert _m("room_rules_health").digest_section(rig.hass) == (
        "Room rules, last 24 h: 1 ran, 1 skipped (person_absent), 1 undone by hand (Exercise Lamp)."
    )
    rig.entry.options = {"ai_rules": [*rig.entry.options["ai_rules"],
                                      {**light_rule(rule_id="x"), "actions": []}]}
    assert _m("room_rules_health").digest_section(rig.hass).endswith("1 rule needs a re-check.")
    # outside 24 h -> nothing ran
    assert _m("room_rules_health").digest_section(rig.hass, now_ts=time.time() + 2 * 86400) == (
        "Room rules, last 24 h: 0 ran. 1 rule needs a re-check."
    )


def test_digest_section_wired_into_nm():
    from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
        NotificationManager,
    )
    nm = NotificationManager.__new__(NotificationManager)
    nm.hass = MagicMock()
    with patch.object(_m("room_rules_health"), "digest_section", lambda hass: "Room rules, last 24 h: 3 ran."):
        assert nm._build_room_rules_digest_section() == "Room rules, last 24 h: 3 ran."


# ---------------------------------------------------------------------------
# D6.5 zero-fire trip-wire
# ---------------------------------------------------------------------------


class _DB:
    def __init__(self, rows=None, revs=None):
        self.rows = rows or []
        self.revs = revs or []

    async def read_memory_episodes_by_type(self, episode_type, since_iso=None):
        return list(self.rows if episode_type == "room_rule_decision" else self.revs)


def _row(rule_id, outcome, node="room:exercise_room"):
    return {"node_id": node, "attrs": {"rule_id": rule_id, "outcome": outcome}}


def _trip(rig, db):
    rig.hass.data[DOMAIN]["EX1"] = rig.c
    fired = []

    async def _fake(hass, kind, key, diagnosis, remedy="", severity=None, **kw):
        fired.append((kind, key, diagnosis, severity))
        return True

    from custom_components.universal_room_automation.domain_coordinators import _stuck_signal_nm
    with patch.object(_stuck_signal_nm, "fire_stuck_signal", _fake):
        res = run(_m("room_rules_health").run_room_rules_health(rig.hass, db))
    return fired, res


def test_rule_silent_tripwire_pages_after_skips():
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    fired, _ = _trip(rig, _DB(rows=[_row("r1", "person_absent")] * 3 + [_row("r1", "switch_off")]))
    assert len(fired) == 1
    kind, key, diag, sev = fired[0]
    assert (kind, key, sev) == ("room_rule_silent", ("Exercise Room", "r1"), "HIGH")
    assert "person_absent (3)" in diag and "checked 4 times" in diag


def test_rule_silent_tripwire_quiet_for_safety_and_unevaluated():
    rig = Rig(rules=[light_rule(rule_id="s1", trigger="safety_hazard"), light_rule(rule_id="u1")],
              states=_lamp_states())
    fired, _ = _trip(rig, _DB(rows=[_row("s1", "condition_false")]))
    assert fired == []


def test_rule_silent_tripwire_quiet_when_fired_or_young():
    young = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    rig = Rig(rules=[light_rule(rule_id="f1"), light_rule(rule_id="y1", created_at=young)],
              states=_lamp_states())
    fired, _ = _trip(rig, _DB(rows=[_row("f1", "fired"), _row("f1", "switch_off"),
                                    _row("y1", "switch_off")]))
    assert fired == []


def test_rule_silent_tripwire_off_at_zero():
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    with patch.object(_m("room_rules_health"), "RULE_ZERO_FIRE_DAYS", 0):
        fired, _ = _trip(rig, _DB(rows=[_row("r1", "switch_off")]))
    assert fired == []


def test_accuracy_rollup_feeds_sensor():
    from custom_components.universal_room_automation.sensor import RoomRulesAccuracySensor
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    _f, res = _trip(rig, _DB(rows=[_row("r1", "fired")] * 4,
                             revs=[{"node_id": "room:exercise_room", "attrs": {"rule_id": "r1"}}]))
    assert res["accuracy"]["pct"] == 75.0
    sensor = RoomRulesAccuracySensor.__new__(RoomRulesAccuracySensor)
    sensor.hass = rig.hass
    assert sensor.native_value == 75.0
    assert sensor.extra_state_attributes["fires"] == 4


def test_nightly_op_registered_and_delegates():
    from custom_components.universal_room_automation import nightly_maintenance as NMx
    from custom_components.universal_room_automation.database import UniversalRoomDatabase
    names = [op[1] for op in NMx.nightly_cleanup_ops()]
    assert "run_room_ai_health_check" in names
    db = UniversalRoomDatabase.__new__(UniversalRoomDatabase)
    db.hass = MagicMock()
    seen = []

    async def _fake(hass, database, **kw):
        seen.append(database)
        return {"paged": []}

    with patch.object(_m("room_rules_health"), "run_room_rules_health", _fake):
        assert run(db.run_room_ai_health_check()) == {"paged": []}
    assert seen == [db]


# ---------------------------------------------------------------------------
# D7 room memory episodes (registry + real DB, production DDL)
# ---------------------------------------------------------------------------


def test_rule_episode_types_registered():
    assert {"room_rule_decision", "room_rule_reversal"} <= C.MEMORY_EPISODE_TYPES
    assert "room_rule_decision" in C.MEMORY_WRITER_BACKED_EPISODE_TYPES
    assert "room_rule_decision" in C.MEMORY_WRITER_HEALTH_EXEMPT_TYPES
    assert "room_rule_reversal" not in C.MEMORY_WRITER_BACKED_EPISODE_TYPES


def test_rule_episode_per_decision():
    rig = Rig(rules=[light_rule(), light_rule(rule_id="r2", trigger="enter",
                                              entity="fan.exercise_fan")],
              states=_lamp_states(), switches={})
    run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    eps = rig.episodes()
    assert [e["attrs"]["rule_id"] for e in eps] == ["r1", "r2"]
    e = eps[0]
    assert e["node_id"] == "room:exercise_room"
    assert e["window_dedup"] is False and e["dedup_source_ref"] is False
    assert e["source_ref"].startswith("rule:r1:")
    assert set(e["attrs"]) >= {"room", "rule_id", "source", "trigger", "person", "outcome",
                               "guard", "conditions", "actions", "ms", "ts"}


def test_rule_episode_log_persist_off():
    rig = Rig(rules=[light_rule()], states=_lamp_states())
    with patch.object(_m("const"), "ROOM_RULE_EPISODE_LOG_PERSIST", False):
        run(rig.c._run_room_rules(["enter"]))
    run(rig.drain())
    assert rig.episodes() == []


def test_rule_episode_two_fires_in_ten_seconds_both_written(tmp_path):
    from custom_components.universal_room_automation.database import UniversalRoomDatabase

    async def _go():
        db_hass = MagicMock()
        db_hass.config.path = lambda *parts: str(tmp_path / os.path.join(*parts))

        def _sched(coro, name=None, **_kw):
            return asyncio.ensure_future(coro)

        db_hass.async_create_task = _sched
        db_hass.async_create_background_task = _sched
        db = UniversalRoomDatabase(db_hass)
        assert await db.initialize()
        await db.start_write_worker()
        try:
            rig = Rig(rules=[light_rule()], states=_lamp_states())
            rig.hass.data[DOMAIN]["database"] = db
            await rig.c._run_room_rules(["enter"])
            await rig.c._run_room_rules(["enter"])
            await rig.drain()
            rows = []
            for _ in range(50):
                rows = await db.read_memory_episodes("room:exercise_room", "room_rule_decision")
                if len(rows) >= 2:
                    break
                await asyncio.sleep(0.05)
            return rows
        finally:
            await db.stop_write_worker()

    loop = asyncio.new_event_loop()
    try:
        rows = loop.run_until_complete(_go())
    finally:
        loop.close()
    assert len(rows) == 2
    assert {r["attrs"]["outcome"] for r in rows} == {"fired"}
    assert rows[0]["source_ref"] != rows[1]["source_ref"]


# ---------------------------------------------------------------------------
# Wire-in anchors: the NM digest flush and the room-entry unload
# ---------------------------------------------------------------------------


def test_room_rules_line_reaches_delivered_nm_digest():
    """The REAL NotificationManager._fire_digest appends the room-rules line
    to the message it delivers (call site, not the helper)."""
    import types
    NM = _m("domain_coordinators.notification_manager").NotificationManager
    sent = []

    class _DB:
        async def get_pending_digest(self, pid):
            return []

        async def count_no_route_since(self, pid, since):
            return 0

        async def mark_digest_delivered(self, *a, **k):
            return None

    hass = MagicMock()
    hass.data = {DOMAIN: {"database": _DB()}}
    nm_like = types.SimpleNamespace(hass=hass, _last_digest_flush={}, _config={})
    nm_like._build_optimizer_digest_section = lambda: ""
    nm_like._build_music_following_digest_section = lambda: ""
    nm_like._build_room_rules_digest_section = types.MethodType(
        NM._build_room_rules_digest_section, nm_like)
    nm_like._format_digest = lambda pending: ""

    async def _deliver(pid, cfg, msg):
        sent.append(msg)
        return False

    nm_like._deliver_digest = _deliver
    with patch.object(_m("room_rules_health"), "digest_section",
                      lambda hass: "Room rules, last 24 h: 2 ran."):
        run(NM._fire_digest(nm_like, "person.oji_udezue", {}))
    assert sent and sent[0].endswith("Room rules, last 24 h: 2 ran.")


def _real_async_unload_entry():
    """The REAL ``async_unload_entry`` body (AST-sliced from __init__.py and
    executed, the test_camera_stream_health pattern): behaviour, not a grep."""
    import ast
    from pathlib import Path
    init_path = Path(_m("coordinator").__file__).with_name("__init__.py")
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_unload_entry")
    c = _m("const")
    ns = {
        "__name__": "custom_components.universal_room_automation",
        "__package__": "custom_components.universal_room_automation",
        "_LOGGER": logging.getLogger("room_rules_test_unload"),
        "HomeAssistant": object, "ConfigEntry": object, "DOMAIN": DOMAIN,
        "CONF_ENTRY_TYPE": c.CONF_ENTRY_TYPE,
        "ENTRY_TYPE_INTEGRATION": c.ENTRY_TYPE_INTEGRATION,
        "ENTRY_TYPE_ZONE_MANAGER": c.ENTRY_TYPE_ZONE_MANAGER,
        "ENTRY_TYPE_COORDINATOR_MANAGER": c.ENTRY_TYPE_COORDINATOR_MANAGER,
        "ENTRY_TYPE_ZONE": c.ENTRY_TYPE_ZONE,
        "PLATFORMS": [], "INTEGRATION_PLATFORMS": [], "Platform": MagicMock(),
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(init_path), "exec"), ns)
    return ns["async_unload_entry"]


def test_reversal_watch_cancelled_by_room_unload():
    unload = _real_async_unload_entry()
    rig = Rig(rules=[light_rule(entity="fan.exercise_fan")], states=_lamp_states())
    unsub_track, unsub_timer = MagicMock(), MagicMock()
    with patch.object(rig.co, "async_track_state_change_event", lambda h, i, cb: unsub_track), \
            patch.object(rig.co, "async_call_later", lambda h, d, cb: unsub_timer):
        run(rig.c._run_room_rules(["enter"]))
    rig.hass.data[DOMAIN]["EX1"] = rig.c
    rig.hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    rig.hass.config_entries.async_entries = MagicMock(return_value=[])
    assert run(unload(rig.hass, rig.entry)) is True
    unsub_track.assert_called_once()
    unsub_timer.assert_called_once()
