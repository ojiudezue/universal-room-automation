"""Next room from the current room + honest from-room scoring
(PREDICT-MODEL-DWELL-MIGRATION-1, plan D4; invariant I4).

Drives the REAL ``PersonLikelyNextRoomSensor.async_update`` and the REAL
``TransitionDetector._log_transition`` (the method that contains the
``_score_prediction`` call). Every test awaits directly; nothing swallows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from occ_dwell_helpers import real_package

from custom_components.universal_room_automation.const import DOMAIN

UTC = timezone.utc


@pytest.fixture(autouse=True, scope="module")
def _real_ura_package():
    import importlib

    global dt_util, sensor, transitions, const, bp, dispatcher
    with real_package():
        dt_util = importlib.import_module("homeassistant.util.dt")
        dispatcher = importlib.import_module("homeassistant.helpers.dispatcher")
        sensor = importlib.import_module(
            "custom_components.universal_room_automation.sensor")
        transitions = importlib.import_module(
            "custom_components.universal_room_automation.transitions")
        const = importlib.import_module(
            "custom_components.universal_room_automation.const")
        bp = importlib.import_module(
            "custom_components.universal_room_automation.bayesian_predictor")
        yield


@pytest.fixture(autouse=True)
def _no_dispatch():
    with patch.object(dispatcher, "async_dispatcher_send", MagicMock()) as m:
        yield m


# ---------------------------------------------------------------------------
# Sensor (source order + cache)
# ---------------------------------------------------------------------------


def _pl_pred(room="Kitchen"):
    return {"next_room": room, "confidence": 0.6, "sample_size": 40,
            "reliability": "high",
            "alternatives": [{"room": "Foyer", "confidence": 0.2}],
            "predicted_path": [room]}


def _bayes(top="Master Bedroom"):
    b = MagicMock()
    b.predict_room_at_time = MagicMock(return_value={
        "top_room": top, "probability": 0.3, "learning_status": "active",
        "alternatives": [{"room": "Study A"}]})
    return b


def _sensor(location="Study A", pl_pred=None, bayes=None, db=None):
    pl = SimpleNamespace(predict_next_room=AsyncMock(
        return_value=pl_pred if pl_pred is not None else _pl_pred()))
    pc = SimpleNamespace(data={"Oji": {"location": location}})
    domain = {"pattern_learner": pl, "person_coordinator": pc}
    if bayes is not None:
        domain["bayesian_predictor"] = bayes
    if db is not None:
        domain["database"] = db
    hass = SimpleNamespace(data={DOMAIN: domain},
                           states=SimpleNamespace(get=lambda _e: None))
    ent = sensor.PersonLikelyNextRoomSensor(hass, SimpleNamespace(), "Oji")
    return ent, hass, pl


@pytest.mark.asyncio
async def test_current_room_primary():
    ent, hass, pl = _sensor(bayes=_bayes())
    await ent.async_update()
    assert ent.native_value == "Kitchen"
    attrs = ent.extra_state_attributes
    assert attrs["source"] == "frequency"
    assert attrs["current_room"] == "Study A"
    pl.predict_next_room.assert_awaited_with("Oji", "Study A")


@pytest.mark.asyncio
async def test_flag_off_bayesian_first():
    with patch.object(const, "NEXT_ROOM_CURRENT_ROOM_PRIMARY", False):
        ent, hass, _ = _sensor(bayes=_bayes())
        await ent.async_update()
    assert ent.native_value == "Master Bedroom"
    assert ent.extra_state_attributes["source"] == "bayesian"
    assert hass.data[DOMAIN]["next_room_predictions"]["Oji"]["current_room"] is None


@pytest.mark.asyncio
async def test_flag_off_frequency_fallback_keeps_old_shape():
    """Kill switch: the frequency fallback carries no from-room stamp, so
    the scorer behaves exactly as before (legacy, ungated)."""
    with patch.object(const, "NEXT_ROOM_CURRENT_ROOM_PRIMARY", False):
        ent, hass, _ = _sensor()          # no Bayesian -> frequency fallback
        await ent.async_update()
    assert ent.native_value == "Kitchen"
    assert ent.extra_state_attributes["current_room"] == ""
    assert hass.data[DOMAIN]["next_room_predictions"]["Oji"]["current_room"] is None


@pytest.mark.asyncio
async def test_no_current_room_falls_back_to_bayesian():
    ent, hass, pl = _sensor(location="unknown", bayes=_bayes())
    await ent.async_update()
    assert ent.native_value == "Master Bedroom"
    pl.predict_next_room.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_learned_transition_falls_back_to_bayesian():
    ent, hass, pl = _sensor(pl_pred={}, bayes=_bayes())
    pl.predict_next_room.return_value = None
    await ent.async_update()
    assert ent.native_value == "Master Bedroom"
    assert hass.data[DOMAIN]["next_room_predictions"]["Oji"]["current_room"] is None


@pytest.mark.asyncio
async def test_away_keeps_away_typical():
    insufficient = MagicMock()
    insufficient.predict_room_at_time = MagicMock(
        return_value={"learning_status": "insufficient_data"})
    with patch.object(bp, "is_cell_stale", AsyncMock(return_value=True)):
        ent, hass, pl = _sensor(location="away", bayes=insufficient,
                                db=object())
        await ent.async_update()
    assert ent.native_value == "away_typical"
    assert ent.extra_state_attributes["source"] == "away_typical"
    pl.predict_next_room.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_carries_current_room():
    ent, hass, _ = _sensor(bayes=_bayes())
    await ent.async_update()
    cache = hass.data[DOMAIN]["next_room_predictions"]["Oji"]
    assert cache["current_room"] == "Study A"
    assert cache["top"] == "Kitchen"
    assert cache["source"] == "frequency"
    assert cache["alternatives"] == ["Foyer"]


# ---------------------------------------------------------------------------
# Scorer (I4 gate + counters), driven through _log_transition
# ---------------------------------------------------------------------------


def _detector(cache):
    db = SimpleNamespace(log_transition=AsyncMock(),
                         save_next_room_prediction_result=AsyncMock())
    hass = SimpleNamespace(data={DOMAIN: {"next_room_predictions": {"Oji": cache}}})
    det = transitions.TransitionDetector(hass, None, db)
    return det, db, hass


def _cache(current_room="A", top="C"):
    c = {"top": top, "alternatives": [], "confidence": 0.5,
         "source": "frequency",
         "timestamp": dt_util.utcnow().isoformat()}
    if current_room is not ...:
        c["current_room"] = current_room
    return c


def _tr(frm, to):
    return transitions.RoomTransition(
        person_id="Oji", from_room=frm, to_room=to,
        timestamp=datetime.now(UTC), duration_seconds=10,
        path_type="direct", confidence=0.9)


def _stats(hass):
    return hass.data[DOMAIN]["next_room_scoring_stats"]["Oji"]


@pytest.mark.asyncio
async def test_scorer_skips_room_mismatch():
    det, db, hass = _detector(_cache("A"))
    await det._log_transition(_tr("B", "C"))
    db.save_next_room_prediction_result.assert_not_awaited()
    assert _stats(hass) == {"scored": 0, "skipped_room_mismatch": 1}
    await det._log_transition(_tr("A", "C"))
    db.save_next_room_prediction_result.assert_awaited_once()
    assert db.save_next_room_prediction_result.await_args.kwargs["actual_room"] == "C"
    assert _stats(hass) == {"scored": 1, "skipped_room_mismatch": 1}


@pytest.mark.asyncio
async def test_scorer_legacy_cache_without_room():
    det, db, hass = _detector(_cache(...))          # no current_room key
    await det._log_transition(_tr("B", "C"))
    db.save_next_room_prediction_result.assert_awaited_once()
    assert _stats(hass) == {"scored": 1, "skipped_room_mismatch": 0}


@pytest.mark.asyncio
async def test_scorer_bayesian_cache_none_room_scored():
    det, db, hass = _detector(_cache(None))
    await det._log_transition(_tr("B", "C"))
    db.save_next_room_prediction_result.assert_awaited_once()
    assert _stats(hass)["skipped_room_mismatch"] == 0


@pytest.mark.asyncio
async def test_scorer_without_from_room_is_legacy():
    """A caller that passes no from_room keeps the old (ungated) scoring."""
    det, db, hass = _detector(_cache("A"))
    await det._score_prediction("Oji", "C")
    db.save_next_room_prediction_result.assert_awaited_once()
    assert _stats(hass) == {"scored": 1, "skipped_room_mismatch": 0}


@pytest.mark.asyncio
async def test_room_names_same_producer_exact_compare():
    """Both names come from person_coordinator's resolved room (sensor reads
    ``location``; the transition carries the event's ``previous_location``),
    so the compare is exact: same string scores, a different string skips."""
    det, db, hass = _detector(_cache("Study A"))
    await det._log_transition(_tr("Study A", "Kitchen"))
    await det._log_transition(_tr("Study B", "Kitchen"))
    assert _stats(hass) == {"scored": 1, "skipped_room_mismatch": 1}


@pytest.mark.asyncio
async def test_stale_cache_neither_scored_nor_skipped():
    c = _cache("A")
    c["timestamp"] = "2026-01-01T00:00:00+00:00"
    det, db, hass = _detector(c)
    await det._log_transition(_tr("B", "C"))
    db.save_next_room_prediction_result.assert_not_awaited()
    assert "next_room_scoring_stats" not in hass.data[DOMAIN]


# ---------------------------------------------------------------------------
# Accuracy sensor exposes the counters (H2)
# ---------------------------------------------------------------------------


def _acc(hass):
    return sensor.PersonNextRoomAccuracySensor(hass, SimpleNamespace(), "Oji")


@pytest.mark.asyncio
async def test_skip_counter_exposed_on_accuracy_sensor():
    det, db, hass = _detector(_cache("A"))
    for frm in ("A", "A", "A", "A", "A", "A", "A", "B", "B", "B"):
        await det._log_transition(_tr(frm, "C"))
    attrs = _acc(hass).extra_state_attributes
    assert attrs["scored_since_start"] == 7
    assert attrs["skipped_room_mismatch_since_start"] == 3
    assert attrs["skip_ratio"] == 0.3
    assert attrs["skip_ratio_ok"] is True      # 0.30 <= 0.30


def test_skip_ratio_null_when_no_events():
    attrs = _acc(SimpleNamespace(data={DOMAIN: {}})).extra_state_attributes
    assert attrs["skip_ratio"] is None and attrs["skip_ratio_ok"] is None
    assert attrs["scored_since_start"] == 0


def test_skip_ratio_ok_uses_knob():
    hass = SimpleNamespace(data={DOMAIN: {"next_room_scoring_stats": {
        "Oji": {"scored": 6, "skipped_room_mismatch": 4}}}})
    assert _acc(hass).extra_state_attributes["skip_ratio_ok"] is False  # 0.4
    with patch.object(const, "NEXT_ROOM_MAX_SKIP_RATIO", 0.4):
        assert _acc(hass).extra_state_attributes["skip_ratio_ok"] is True
