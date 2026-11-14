"""PERIMETER-GATE-EVIDENCE D3: VLM on-property vs street question, recorded only.

Plan: PLANNING_perimeter_gate_evidence_and_input_health.md D3 (INV-LOC).
Drives the REAL person handler with a fake llmvision service (the only
external seam) and asserts the prompt sent, the severity dispatched, the
message text and the gate record. Expected values are hand-written.
"""

from __future__ import annotations

import asyncio

import pytest

import custom_components.universal_room_automation.perimeter_enrichment as pe
from test_perimeter_fp_gates import (  # noqa: E402
    RP_CAM,
    RP_KEY,
    RP_PR,
    Severity,
    _build,
    _const,
    _perimeter,
    _run,
    _setup,
    _sev,
)


class _FakeDb:
    def __init__(self):
        self.rows: list[dict] = []

    async def log_memory_episode(self, **kw):
        self.rows.append(kw)
        return len(self.rows)


def _vlm(monkeypatch, mode, text, *, tier="frigate_event", db=None):
    hass, nm = _build(perimeter=(RP_CAM,), extra_opts={
        _const.CONF_PERIMETER_VLM_GATE: mode,
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: True,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [RP_PR],
    })
    mgr, _subs = _setup(hass, monkeypatch)
    calls: list[dict] = []

    async def _svc(domain, service, data, **kw):
        calls.append(dict(data))
        return {"response_text": text}

    hass.services.async_call = _svc
    path = "/media/ura/snapshots/rear_ptz_x.jpg"

    async def _cap(_eid):
        mgr._last_snapshot_capture[RP_KEY] = {"path": path, "engine": tier}
        return path
    mgr._await_edge_capture = _cap
    monkeypatch.setattr(pe.os.path, "exists", lambda p: True)
    pending: list = []
    if db is not None:
        hass.data[_const.DOMAIN]["database"] = db
        hass.async_create_task = lambda coro, *a, **k: pending.append(coro) or _Done()
    _run(mgr._async_handle_perimeter_trigger(RP_PR))

    async def _drain():
        for c in pending:
            if asyncio.iscoroutine(c):
                await c
    if pending:
        asyncio.run(_drain())
    return mgr, nm, calls


class _Done:
    def add_done_callback(self, _cb):
        return None

    def done(self):
        return True


def _vlm_rec(mgr):
    return mgr._last_gate_decisions[RP_KEY]["vlm"]


def test_off_mode_byte_identical_call(monkeypatch):
    _mgr, nm, calls = _vlm(monkeypatch, "off", "A man.")
    assert calls == [{
        "message": pe._DEFAULT_PROMPT,
        "image_file": "/media/ura/snapshots/rear_ptz_x.jpg",
        "max_tokens": calls[0]["max_tokens"],
        "model": calls[0]["model"],
    }]
    assert set(calls[0]) == {"message", "image_file", "max_tokens", "model"}
    assert nm.async_notify.await_args.kwargs["message"].endswith("\n\nA man.")


def test_shadow_asks_location_and_records_it(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK", True)
    mgr, nm, calls = _vlm(monkeypatch, "shadow", "PERSON: YES\nLOCATION: STREET\nA man walks.")
    assert [c["message"] for c in calls] == [pe._VERDICT_LOCATION_PROMPT]
    d = _vlm_rec(mgr)
    assert d["location"] == "STREET" and d["verdict"] == "YES"
    assert _sev(nm) == Severity.CRITICAL
    msg = nm.async_notify.await_args.kwargs["message"]
    assert msg.endswith("\n\nA man walks.")
    assert "LOCATION" not in msg and "PERSON:" not in msg


def test_enforce_keeps_verdict_prompt_until_parity(monkeypatch):
    """PERSON-parity guard: enforce sends today's prompt (location UNSURE)
    even with the ask knob on."""
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK", True)
    mgr, _nm, calls = _vlm(monkeypatch, "enforce", "PERSON: YES\nA man.")
    assert [c["message"] for c in calls] == [pe._VERDICT_PROMPT]
    assert _vlm_rec(mgr)["location"] == "UNSURE"


def test_location_never_demotes_enforce(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK", True)
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK_IN_ENFORCE", True)
    mgr, nm, calls = _vlm(monkeypatch, "enforce", "PERSON: YES\nLOCATION: STREET\nOn the road.")
    assert [c["message"] for c in calls] == [pe._VERDICT_LOCATION_PROMPT]
    assert _sev(nm) == Severity.CRITICAL
    d = _vlm_rec(mgr)
    assert d["location"] == "STREET" and d["demoted"] is False
    assert d["reason"] == "verdict_not_no"


def test_person_no_still_demotes_enforce(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK", True)
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK_IN_ENFORCE", True)
    mgr, nm, _calls = _vlm(monkeypatch, "enforce", "PERSON: NO\nLOCATION: PROPERTY\nEmpty yard.")
    assert _sev(nm) == Severity.LOW
    d = _vlm_rec(mgr)
    assert d["location"] == "PROPERTY" and d["demoted"] is True
    assert d["reason"] == "vlm_no_person"


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_ask_off_prompt_identical(monkeypatch, mode):
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK", False)
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK_IN_ENFORCE", True)
    mgr, _nm, calls = _vlm(monkeypatch, mode, "PERSON: YES\nLOCATION: STREET\nx")
    assert [c["message"] for c in calls] == [pe._VERDICT_PROMPT]
    # today's parser: location UNSURE and the line is NOT stripped
    assert _vlm_rec(mgr)["location"] == "UNSURE"


def test_location_recorded_in_gate_row(monkeypatch):
    monkeypatch.setattr(_perimeter, "PERIMETER_VLM_LOCATION_ASK", True)
    db = _FakeDb()
    mgr, _nm, _calls = _vlm(
        monkeypatch, "shadow", "PERSON: YES\nLOCATION: PROPERTY\nAt the door.", db=db,
    )
    vlm_rows = [r for r in db.rows if r["attrs"]["gate"] == "vlm"]
    assert len(vlm_rows) == 1
    a = vlm_rows[0]["attrs"]
    assert a["location"] == "PROPERTY" and a["verdict"] == "YES"
    assert a["snapshot"] == "rear_ptz_x.jpg"
    assert a["tier"] == "frigate_event"


def test_enrich_with_verdicts_failure_is_unsure(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(pe, "enrich_dispatched_alert", _boom)
    assert tuple(asyncio.run(pe.enrich_with_verdicts(None, "/x", "e", True))) == (
        None, "UNSURE", "UNSURE")

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(pe, "enrich_dispatched_alert", _none)
    assert tuple(asyncio.run(pe.enrich_with_verdicts(None, "/x", "e", False))) == (
        None, "UNSURE", "UNSURE")


@pytest.mark.parametrize("mode,text,sev", [
    ("shadow", "PERSON: NO\nEmpty.", Severity.CRITICAL),
    ("enforce", "PERSON: NO\nEmpty.", Severity.LOW),
    ("shadow", "PERSON: YES\nLOCATION: STREET\nA man.", Severity.CRITICAL),
])
def test_default_knob_off_byte_identical(monkeypatch, mode, text, sev):
    """D3 ships dark: with shipped defaults, every select mode sends today's
    `_VERDICT_PROMPT` and the message / severity / record are develop's
    (location UNSURE, a LOCATION line in the reply stays in the text exactly
    as today's parser leaves it)."""
    assert _perimeter.PERIMETER_VLM_LOCATION_ASK is False
    assert _perimeter.PERIMETER_VLM_LOCATION_ASK_IN_ENFORCE is False
    mgr, nm, calls = _vlm(monkeypatch, mode, text)
    assert [c["message"] for c in calls] == [pe._VERDICT_PROMPT]
    assert set(calls[0]) == {"message", "image_file", "max_tokens", "model"}
    assert _sev(nm) == sev
    from custom_components.universal_room_automation.perimeter_fp_gates import parse_vlm_verdict
    desc, _v = parse_vlm_verdict(text)
    assert nm.async_notify.await_args.kwargs["message"].endswith("\n\n" + desc)
    assert _vlm_rec(mgr)["location"] == "UNSURE"
