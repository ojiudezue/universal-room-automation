"""Shared harness for the NM diag text-menu tests (NM-INBOUND-HOUSE-QUERIES-1).

Builds a REAL NotificationManager (HA stubs from test_notification_manager)
with a recording hass + DB mock and a fixed clock, and drives
``_process_inbound_reply`` directly (no swallowed exceptions).

Also used once to capture ``fixtures/nm_inbound_golden_pre_diag.json`` from the
merge-base code (I4 oracle, plan §5) by calling ``capture()`` from a
pytest session on the unmodified merge-base tree (sha in the fixture header)
and json-dumping ``{"_merge_base_sha", "records": capture()}``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_notification_manager import _make_hass, _make_config  # noqa: E402,F401

import custom_components.universal_room_automation.domain_coordinators.notification_manager as nm_mod  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (  # noqa: E402
    AlertState,
    NotificationManager,
    RESPONSE_COMMANDS,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_NM_SAFE_WORD,
    CONF_NM_PERSONS,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_WHATSAPP_ENABLED,
    DOMAIN,
    NM_DELIVERY_IMMEDIATE,
)

PERSON = "person.op"
SAFE_WORD = "dukeword"
T0 = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)
FIXTURE = os.path.join(HERE, "fixtures", "nm_inbound_golden_pre_diag.json")


class Clock:
    def __init__(self, now: datetime = T0):
        self.now = now

    def utcnow(self):
        return self.now


@contextlib.contextmanager
def fixed_clock(clock: Clock):
    """Scoped patch of the dt_util.utcnow NM reads; always restored."""
    dt = nm_mod.dt_util
    orig = dt.utcnow
    dt.utcnow = clock.utcnow
    try:
        yield clock
    finally:
        dt.utcnow = orig


def make_nm():
    """Real NM, one person on whatsapp + imessage + pushover, DB mock."""
    hass = _make_hass()
    # A ha-wa-bridge 2.x install (no `wa_bridge` service), so WhatsApp sends keep
    # the `whatsapp` domain the merge-base golden fixtures recorded.
    hass.services.has_service = lambda domain, service: domain != "wa_bridge"
    cfg = _make_config(**{
        CONF_NM_SAFE_WORD: SAFE_WORD,
        CONF_NM_WHATSAPP_ENABLED: True,
        CONF_NM_PERSONS: [{
            CONF_NM_PERSON_ENTITY: PERSON,
            CONF_NM_PERSON_PUSHOVER_KEY: "pkey",
            CONF_NM_PERSON_COMPANION_SERVICE: "notify.mobile_app_op",
            CONF_NM_PERSON_WHATSAPP_PHONE: "+15550001",
            CONF_NM_PERSON_IMESSAGE_HANDLE: "op@example.com",
            CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
        }],
    })
    nm = NotificationManager(hass, cfg)
    nm._dry_run_active = False
    db = MagicMock()
    db.log_inbound = AsyncMock(return_value=None)
    db.get_active_criticals = AsyncMock(return_value=[])
    db.get_active_critical = AsyncMock(return_value={"id": 7})
    hass.data = {DOMAIN: {"database": db}}
    nm.async_acknowledge = AsyncMock(return_value=None)
    nm._announce_ack = AsyncMock(return_value=None)
    created = []

    def _capture_task(coro):
        created.append(coro)
        coro.close()
        return MagicMock()

    hass.async_create_task = _capture_task
    nm._test_created_tasks = created
    nm._test_db = db
    return nm


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def set_scenario(nm, scenario: str, clock: Clock) -> None:
    from datetime import timedelta
    if scenario == "idle_no_context":
        nm._notifications_today_count = 0
    elif scenario == "idle_context":
        nm._notifications_today_count = 3
    elif scenario == "critical_alerting":
        nm._notifications_today_count = 1
        nm._alert_state = AlertState.ALERTING
        nm._active_alert_data = {
            "severity": "CRITICAL", "hazard_type": "smoke",
            "location": "kitchen", "coordinator_id": "safety",
        }
    elif scenario == "silenced":
        nm._notifications_today_count = 2
        nm._silence_until = clock.now + timedelta(minutes=20)
    else:  # pragma: no cover
        raise ValueError(scenario)


SCENARIOS = ("idle_no_context", "idle_context", "critical_alerting", "silenced")
CHANNELS = ("imessage", "whatsapp", "pushover")


def golden_inputs() -> list[str]:
    """Every non-diag golden input (plan D3)."""
    base = sorted(RESPONSE_COMMANDS.keys())
    return base + [SAFE_WORD, f"{SAFE_WORD} 2h", f"{SAFE_WORD} 9h", "hello there", "9", "0", "10", "4", "7"]


def observe(nm, text: str, channel: str, person=PERSON) -> dict:
    """Drive one inbound; return a JSON-able record of every effect."""
    before_silence = nm._silence_until
    ret = run(nm._process_inbound_reply(person, channel, text))
    calls = [
        [c.args[0], c.args[1], {k: v for k, v in sorted(c.args[2].items())}]
        for c in nm.hass.services.async_call.call_args_list
    ]
    logs = [list(c.args) for c in nm._test_db.log_inbound.call_args_list]
    acks = [sorted(c.kwargs.items()) for c in nm.async_acknowledge.call_args_list]
    return {
        "ret": ret,
        "calls": calls,
        "logs": logs,
        "acks": [[list(kv) for kv in a] for a in acks],
        "silence_changed": nm._silence_until != before_silence,
        "tasks": len(nm._test_created_tasks),
    }


def golden_record(text: str, scenario: str, channel: str) -> dict:
    clock = Clock()
    with fixed_clock(clock):
        nm = make_nm()
        set_scenario(nm, scenario, clock)
        return observe(nm, text, channel)


def capture() -> dict:
    out = {}
    for sc in SCENARIOS:
        for ch in CHANNELS:
            for t in golden_inputs():
                out[f"{sc}|{ch}|{t}"] = golden_record(t, sc, ch)
    return out

