"""HVAC W1-C P1 — thermostat-profile contract + "manual"-literal lint.

Plan: ``docs/planning/PLANNING_hvac_w1c_thermostat_profiles.md`` REV 3 +
3.1 errata, P1 deliverables 2-8. The byte-identity of every write site is
proven by ``test_hvac_w1c_p1_byte_identity.py`` (goldens); this file pins the
contract surface the goldens cannot see:

  * the public types (``PersonChangeVerdict``, ``ProfileCapabilities``) and
    their exact values;
  * the pure delegates (``set_setpoints`` / ``set_hvac_mode`` /
    ``pin_preset``): exact funnel call, True->APPLIED / False->DEFERRED,
    wire exception PROPAGATES, nothing recorded in ``last_sent``;
  * ``release_hold`` records nothing and has no production caller (N3);
  * ``is_manual_hold`` is the exact Carrier predicate for both profiles;
  * Carrier ``classify_person_change`` == the Carrier classifier verbatim;
    the non-Carrier stub returns INCONCLUSIVE and never raises (N2);
  * deliverable 4(b): no raw ``"manual"`` literal in ``hvac*.py`` outside
    ``hvac_strategy.py`` + a reasoned allowlist (stale entries fail).
"""
from __future__ import annotations

import ast
import asyncio
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DC = ROOT / "custom_components" / "universal_room_automation" / "domain_coordinators"

_Q = Path(__file__).resolve().parents[1]
if str(_Q) not in sys.path:
    sys.path.insert(0, str(_Q))

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_strategy as S,
)

ENT = "climate.test_zone_1"


# --------------------------------------------------------------------------
# Deliverable 4(b) — "manual" literal lint
# --------------------------------------------------------------------------

# (file, stripped source line) -> reason. Every entry must still match
# (a stale entry fails), and every literal must be listed.
MANUAL_LITERAL_ALLOWLIST = {
    ("hvac_fans.py", 'room_fan.trigger = "manual"'):
        "fan trigger provenance label, not a thermostat hold (B13 name collision)",
    ("hvac_override.py", 'self, zone_id: str, triggered_by: str = "manual",'):
        "nudge trigger provenance (button / service), not a thermostat hold",
    ("hvac_override.py", 'await self._perform_soft_nudge(zone, kwh_rate, triggered_by="manual")'):
        "nudge trigger provenance (force-nudge button), not a thermostat hold",
    ("hvac_override.py", 'zone, 0.0, triggered_by="manual",'):
        "nudge trigger provenance (force-nudge path), not a thermostat hold",
    ("hvac_setpoint.py", 'ANONYMOUS_HOLD: Final = "manual"'):
        "B11 resume-then-pin lives INSIDE the funnel (Carrier quirk, capability-"
        "gated); the W1-B operator constraint forbids routing new logic into "
        "the emit_* funnels",
}


def _manual_literals():
    out = []
    for f in sorted(DC.glob("hvac*.py")):
        if f.name == "hvac_strategy.py":
            continue
        src = f.read_text()
        lines = src.splitlines()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Constant) and n.value == "manual":
                out.append((f.name, lines[n.lineno - 1].strip(), n.lineno))
    return out


def test_no_raw_manual_literal_outside_strategy():
    found = _manual_literals()
    bad = [
        f"{f}:{ln}: raw \"manual\" literal — route through hvac_strategy "
        f"(is_manual_hold / MANUAL_HOLD_PRESET) or allowlist with a reason: {txt}"
        for f, txt, ln in found if (f, txt) not in MANUAL_LITERAL_ALLOWLIST
    ]
    assert not bad, "\n".join(bad)


def test_manual_allowlist_has_no_stale_entries():
    seen = {(f, txt) for f, txt, _ in _manual_literals()}
    stale = [k for k in MANUAL_LITERAL_ALLOWLIST if k not in seen]
    assert not stale, f"stale allowlist entries: {stale}"


def test_lint_catches_a_planted_literal(tmp_path, monkeypatch):
    """The walker is not vacuous: a planted literal in a hvac*.py is found."""
    planted = tmp_path / "hvac_planted.py"
    planted.write_text('def f(z):\n    return z.preset_mode == "manual"\n')
    monkeypatch.setattr(sys.modules[__name__], "DC", tmp_path)
    found = _manual_literals()
    assert found == [("hvac_planted.py", 'return z.preset_mode == "manual"', 2)]


def test_release_hold_has_no_production_caller():
    """N3: P1 has no `release_hold` caller (Carrier resume stays inside
    `emit_set_preset_mode`)."""
    callers = []
    for f in sorted((DC.parent).rglob("*.py")):
        if f.name == "hvac_strategy.py":
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "release_hold"
            ):
                callers.append(f"{f.name}:{n.lineno}")
    assert callers == []


# --------------------------------------------------------------------------
# Deliverable 5 — public types, exact values
# --------------------------------------------------------------------------


def test_person_change_verdict_members_exact():
    assert {m.name: m.value for m in S.PersonChangeVerdict} == {
        "HUMAN": "human",
        "DEVICE_SCHEDULE": "device_schedule",
        "URA_ECHO": "ura_echo",
        "INCONCLUSIVE": "inconclusive",
    }


def test_write_status_members_exact():
    assert {m.name: m.value for m in S.WriteStatus} == {
        "APPLIED": "applied",
        "SKIPPED_ALREADY_CORRECT": "skipped_already_correct",
        "DEFERRED": "deferred",
        "FAILED": "failed",
    }


def test_profile_capabilities_field_set_frozen():
    import dataclasses
    assert [f.name for f in dataclasses.fields(S.ProfileCapabilities)] == [
        "platform", "manufacturer", "has_named_presets", "named_preset_vocabulary",
        "has_heat_cool_mode", "setpoint_shape", "supports_resume",
        "supports_activity_setpoint", "has_next_activity_time",
        "has_write_confirmation_feed", "has_mode_select", "mode_select_options",
        "hold_via", "hold_release_mechanism", "equipment_telemetry", "echo_ttl_s",
        "preset_echo_ttl_s", "write_rate_min_interval_s", "retry_interval_s",
        "person_change_match_window_s", "person_change_shape",
    ]


def test_strategy_capabilities_bound_per_profile():
    assert S.CarrierStrategy().capabilities is S.CARRIER_CAPABILITIES
    assert S.GenericStrategy().capabilities is S.GENERIC_CAPABILITIES
    assert S.CARRIER_CAPABILITIES.hold_via == "preset"
    assert S.CARRIER_CAPABILITIES.person_change_match_window_s is None
    assert S.GENERIC_CAPABILITIES.hold_via == "unsupported"
    assert S.GENERIC_CAPABILITIES.person_change_match_window_s == 600


def test_carrier_capabilities_mirror_constants():
    """Carrier timings mirror the live module constants (hardcoded oracle:
    15 / 120 / 60 — the values the state-of-play doc records)."""
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_const, hvac_override,
    )
    c = S.CARRIER_CAPABILITIES
    assert (c.echo_ttl_s, c.preset_echo_ttl_s, c.write_rate_min_interval_s) == (15, 120, 60)
    assert hvac_override.SUPPRESS_TTL_SECONDS == c.echo_ttl_s
    assert hvac_override.SUPPRESS_TTL_SECONDS_PRESET == c.preset_echo_ttl_s
    assert hvac_const.HVAC_FAST_PATH_MIN_INTERVAL_S == c.write_rate_min_interval_s


@pytest.mark.parametrize("cls,feature,expected", [
    (S.CarrierStrategy, "hold", True),
    (S.CarrierStrategy, "nudge", True),
    (S.CarrierStrategy, "borrow.banking", True),
    (S.CarrierStrategy, "cpr", True),
    (S.CarrierStrategy, "teleport", False),
    (S.GenericStrategy, "hold", False),
    (S.GenericStrategy, "nudge", False),
    (S.GenericStrategy, "borrow.preheat", False),
    (S.GenericStrategy, "cpr", False),
])
def test_feature_available_table(cls, feature, expected):
    assert cls().feature_available(feature) is expected


# --------------------------------------------------------------------------
# Deliverable 3 — is_manual_hold
# --------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [S.CarrierStrategy, S.GenericStrategy])
@pytest.mark.parametrize("value,expected", [
    ("manual", True), ("home", False), ("away", False), ("", False),
    (None, False), ("Manual", False), ("resume", False),
])
def test_is_manual_hold_exact(cls, value, expected):
    st = cls()
    assert st.is_manual_hold(value) is expected
    obs = S.HoldObservation(
        preset_mode=value, hold_activity=None, target_high=None,
        target_low=None, hvac_mode="heat_cool",
    )
    assert st.is_manual_hold(obs) is expected


def test_is_manual_hold_for_no_entity_uses_generic():
    assert S.is_manual_hold_for(None, None, "manual") is True
    assert S.is_manual_hold_for(None, None, "home") is False


# --------------------------------------------------------------------------
# Pure delegates (deliverables 1, 2, 6)
# --------------------------------------------------------------------------


class _Spy:
    def __init__(self, ret=True, exc=None):
        self.calls = []
        self.ret = ret
        self.exc = exc

    async def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        if self.exc is not None:
            raise self.exc
        return self.ret


@pytest.mark.parametrize("cls", [S.CarrierStrategy, S.GenericStrategy])
@pytest.mark.parametrize("ret,status", [
    (True, "applied"), (False, "deferred"),
])
def test_delegates_map_funnel_bool(cls, ret, status):
    st = cls()
    hass = object()
    for meth, args, kw in (
        ("set_setpoints", (), {"target_temp_low": 68.0, "target_temp_high": 76.0,
                               "site": "S", "zone_id": "zone_1", "reason": "r"}),
        ("set_hvac_mode", ("heat_cool",), {"site": "B", "zone_id": "zone_1",
                                           "reason": "r", "blocking": True}),
        ("pin_preset", ("home",), {"blocking": False, "site": "S4", "zone_id": "zone_1",
                                   "reason": "r", "excursion_id": "x"}),
    ):
        spy = _Spy(ret=ret)
        res = asyncio.run(getattr(st, meth)(hass, ENT, *args, emit=spy, **kw))
        assert res.status.value == status
        # Exact call shape: positional (hass, entity, *args), kwargs verbatim.
        assert spy.calls == [((hass, ENT, *args), kw)]
    assert st._last_sent == {}


@pytest.mark.parametrize("cls", [S.CarrierStrategy, S.GenericStrategy])
@pytest.mark.parametrize("meth,args", [
    ("set_setpoints", ()), ("set_hvac_mode", ("off",)), ("pin_preset", ("home",)),
])
def test_delegates_propagate_wire_exception(cls, meth, args):
    st = cls()
    spy = _Spy(exc=RuntimeError("wire"))
    with pytest.raises(RuntimeError, match="wire"):
        asyncio.run(getattr(st, meth)(
            object(), ENT, *args, emit=spy, site="s", zone_id="zone_1", reason="r",
        ))
    assert st._last_sent == {}


def test_pin_preset_never_noops_on_matching_last_sent():
    """Return sites must NOT inherit S1's D2.5 no-op."""
    st = S.CarrierStrategy()
    st._record_sent(ENT, "set_preset_mode", "home")
    spy = _Spy()
    res = asyncio.run(st.pin_preset(object(), ENT, "home", emit=spy,
                                    site="S7", zone_id="zone_1", reason="r"))
    assert res.status is S.WriteStatus.APPLIED
    assert len(spy.calls) == 1
    # and the S1 record is untouched (no new verb, no clear)
    assert st.last_sent(ENT, "set_preset_mode") == "home"


def test_release_hold_records_nothing(monkeypatch):
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_setpoint,
    )
    spy = _Spy()
    monkeypatch.setattr(hvac_setpoint, "emit_set_preset_mode", spy)
    st = S.CarrierStrategy()
    res = asyncio.run(st.release_hold(object(), ENT, site="x", zone_id="zone_1", reason="r"))
    assert res.status is S.WriteStatus.APPLIED
    assert spy.calls[0][0][2] == "resume"
    assert st._last_sent == {}


# --------------------------------------------------------------------------
# classify_person_change (deliverable 5)
# --------------------------------------------------------------------------


def _st(state, pm, low, high):
    return types.SimpleNamespace(
        state=state,
        attributes={"preset_mode": pm, "target_temp_low": low, "target_temp_high": high},
    )


_CASES = [
    # (old, new, recent, expected verdict, expected legs)
    (_st("heat_cool", "manual", 68, 76), _st("heat_cool", "manual", 68, 74), (), "human", ("high",)),
    (_st("heat_cool", "manual", 68, 76), _st("heat_cool", "manual", 68, 74), ((68.0, 74.0),), "ura_echo", ("high",)),
    (_st("heat_cool", "manual", 68, 76), _st("heat_cool", "manual", 68, 76), (), None, ()),
    (_st("heat_cool", "home", 68, 76), _st("heat_cool", "manual", 68, 74), (), None, ()),
    (_st("cool", "manual", 68, 76), _st("cool", "manual", 68, 74), (), None, ()),
    (_st("heat_cool", "manual", None, 76), _st("heat_cool", "manual", 68, 74), (), None, ()),
]


@pytest.mark.parametrize("old,new,recent,verdict,legs", _CASES)
def test_carrier_classify_person_change_pins_classifier(old, new, recent, verdict, legs):
    res = S.CarrierStrategy().classify_person_change(old, new, recent=recent, tol=0.5)
    assert (res.verdict.value if res.verdict else None) == verdict
    assert res.changed_legs == legs
    assert res.delta_f is None


@pytest.mark.parametrize("old,new", [
    (None, None), (object(), 42), (_CASES[0][0], _CASES[0][1]),
])
def test_generic_classify_person_change_stub_inconclusive_never_raises(old, new):
    res = S.GenericStrategy().classify_person_change(old, new, recent=object())
    assert res.verdict is S.PersonChangeVerdict.INCONCLUSIVE
