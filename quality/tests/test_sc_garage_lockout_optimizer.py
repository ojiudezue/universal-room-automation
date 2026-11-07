"""GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 D4b — optimizer cover block (plan §6.3).

Layer 1: OptimizationCoordinator._check_safety_denylist, driven through the
REAL _apply_action chokepoint with a minimal stand-in ``self`` (no SC
registered). Layer 2: SecurityCoordinator.honor_optimizer_intent.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from _lockout_harness import TZ, World, load  # noqa: F401

const = load("const")
opt = load("domain_coordinators.optimization")
sec = load("domain_coordinators.security")

GARAGE_A = "cover.konnected_f0f5bd523b00_garage_door"
GARAGE_B = "cover.ratgdov25i_dbfe2a_door"
BLIND = "cover.living_room_blind"


class _States:
    def __init__(self, states):
        self._s = states

    def get(self, eid):
        return self._s.get(eid)


def _state(eid, device_class):
    attrs = {} if device_class is None else {"device_class": device_class}
    return SimpleNamespace(entity_id=eid, state="closed", attributes=attrs)


def _hass(states):
    return SimpleNamespace(states=_States(states), data={})


def _finding():
    return opt.OptimizationFinding(
        timestamp="2026-11-07T00:00:00", level="house", target_id=None,
        dimension="comfort", severity="low", confidence=0.99, score=1.0,
        description="llm proposal",
    )


def _fake_self(hass, cm_config):
    dispatched = []
    logged = []

    async def _log_activity(**kw):
        logged.append(kw)

    async def _dispatch(*a, **k):
        dispatched.append(a)
        return const.OPTIMIZER_OUTCOME_APPLIED if hasattr(
            const, "OPTIMIZER_OUTCOME_APPLIED") else "applied"

    fake = SimpleNamespace(
        hass=hass,
        _resolve_effective_level=lambda: (const.OPTIMIZER_LEVEL_REVERSIBLE_DEVICE, None),
        _per_dimension_cap=lambda dim: None,
        _min_level=opt.OptimizationCoordinator._min_level,
        _level_at_least=opt.OptimizationCoordinator._level_at_least,
        _read_cm_config=lambda: dict(cm_config),
        _confidence_gate=lambda: 0.0,
        _log_activity=_log_activity,
        _dispatch_device_action=_dispatch,
        broker=SimpleNamespace(fire_intent=lambda *a, **k: None),
    )
    fake._check_safety_denylist = (
        lambda *a, **k: opt.OptimizationCoordinator._check_safety_denylist(fake, *a, **k)
    )
    return fake, dispatched, logged


async def _apply(hass, cm_config, target, service="cover.open_cover"):
    fake, dispatched, logged = _fake_self(hass, cm_config)
    finding = _finding()
    outcome = await opt.OptimizationCoordinator._apply_action(
        fake, finding,
        {"service": service, "service_data": {}, "target_entity": target,
         "action_class": "reversible_device"},
    )
    return outcome, dispatched, logged


@pytest.mark.asyncio
async def test_optimizer_dispatch_disallows_garage_without_sc():
    hass = _hass({GARAGE_A: _state(GARAGE_A, "garage")})
    outcome, dispatched, logged = await _apply(hass, {}, GARAGE_A)
    assert outcome == opt.OPTIMIZER_OUTCOME_DISALLOWED
    assert dispatched == []
    assert logged[-1]["details"]["reason"] == "security_owned_cover"


@pytest.mark.asyncio
async def test_optimizer_garage_disallowed_when_state_missing_and_registry_unavailable(monkeypatch):
    co = load("cover_ownership")

    def broken(hass):
        raise RuntimeError("registry down")

    monkeypatch.setattr(co.er, "async_get", broken)
    hass = _hass({})
    cfg = {const.CONF_SECURITY_GARAGE_ENTITIES: [GARAGE_B]}
    outcome, dispatched, _ = await _apply(hass, cfg, GARAGE_B)
    assert outcome == opt.OPTIMIZER_OUTCOME_DISALLOWED
    assert dispatched == []


@pytest.mark.asyncio
async def test_optimizer_garage_disallowed_after_device_class_changed_to_door():
    hass = _hass({GARAGE_A: _state(GARAGE_A, "door")})
    cfg = {const.CONF_SECURITY_GARAGE_ENTITIES: [GARAGE_A, GARAGE_B]}
    outcome, dispatched, _ = await _apply(hass, cfg, GARAGE_A)
    assert outcome == opt.OPTIMIZER_OUTCOME_DISALLOWED
    assert dispatched == []


@pytest.mark.asyncio
async def test_optimizer_cover_on_blind_acked():
    hass = _hass({BLIND: _state(BLIND, "blind")})
    cfg = {const.CONF_SECURITY_GARAGE_ENTITIES: [GARAGE_A]}
    outcome, dispatched, _ = await _apply(hass, cfg, BLIND)
    assert outcome != opt.OPTIMIZER_OUTCOME_DISALLOWED
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_optimizer_non_cover_unaffected():
    hass = _hass({})
    cfg = {const.CONF_SECURITY_GARAGE_ENTITIES: [GARAGE_A]}
    outcome, dispatched, _ = await _apply(hass, cfg, "fan.bedroom", "fan.turn_on")
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_optimizer_predicate_raise_fails_closed(monkeypatch):
    co = load("cover_ownership")

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(co, "is_security_owned_or_configured_cover", boom)
    hass = _hass({BLIND: _state(BLIND, "blind")})
    outcome, dispatched, _ = await _apply(hass, {}, BLIND)
    assert outcome == opt.OPTIMIZER_OUTCOME_DISALLOWED
    assert dispatched == []


def _sc(hass):
    return sec.SecurityCoordinator(hass, garage_entities=[GARAGE_A, GARAGE_B])


def test_optimizer_cover_open_on_garage_vetoed():
    hass = _hass({GARAGE_A: _state(GARAGE_A, "garage")})
    sc = _sc(hass)
    assert sc.honor_optimizer_intent({"target_entity": GARAGE_A}) is False
    assert sc._last_veto_reason == "security_owned_cover"


def test_optimizer_sc_veto_configured_garage_without_device_class():
    hass = _hass({GARAGE_B: _state(GARAGE_B, "door")})
    sc = _sc(hass)
    assert sc.honor_optimizer_intent({"target_entity": GARAGE_B}) is False


def test_optimizer_sc_acks_blind():
    hass = _hass({BLIND: _state(BLIND, "blind")})
    sc = _sc(hass)
    assert sc.honor_optimizer_intent({"target_entity": BLIND}) is True
    assert sc._last_veto_reason is None


def test_owned_or_configured_predicate():
    co = load("cover_ownership")
    hass = _hass({BLIND: _state(BLIND, "blind"), GARAGE_A: _state(GARAGE_A, "garage")})
    assert co.is_security_owned_or_configured_cover(hass, BLIND, [BLIND]) is True
    assert co.is_security_owned_or_configured_cover(hass, BLIND, []) is False
    assert co.is_security_owned_or_configured_cover(hass, GARAGE_A, None) is True
