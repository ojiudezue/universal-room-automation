"""HVAC-MANUAL-PRESET-CONTRACT-1 D1+D2a — resume-then-pin and the per-kind TTL.

THE MECHANISM (measured live 2026-09-16 on zone_1, not theorised). A Bryant zone
sitting in an ANONYMOUS hold (`hold_activity == "manual"`, which any raw setpoint
write leaves behind) will not accept a named activity hold written over it: the
cloud keeps the activity's SETPOINTS and discards the NAME. Two direct writes
reverted in 44s and 68s. `resume` first, then pin, held 8 minutes across 9
cloud-confirmed refreshes.

WHAT THESE TESTS PIN, and why each is discriminating rather than decorative:
  * resume fires ONLY for an anonymous hold  (a blanket resume would expose
    every zone to the Bryant schedule the operator does not use — invariant I3)
  * resume NEVER fires for a named hold      (zone_3 pins directly today; a
    regression here would add a schedule gap to the one zone that works)
  * resume never recurses on itself
  * the preset TTL is LONGER than the temp TTL, and the temp TTL is UNCHANGED
    (a global raise would blind the human-override witness — see D1 comment)
"""
from __future__ import annotations

import ast
import pathlib

import pytest


DC = pathlib.Path(__file__).resolve().parents[2].joinpath(
    "custom_components", "universal_room_automation", "domain_coordinators"
)
SETPOINT = DC / "hvac_setpoint.py"
OVERRIDE = DC / "hvac_override.py"


def _load_gate():
    """Exec just `_needs_resume_first` with a stub hass — no HA runtime needed."""
    tree = ast.parse(SETPOINT.read_text())
    consts, fn = {}, None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") in (
            "PRESET_RESUME", "ANONYMOUS_HOLD"
        ):
            consts[node.target.id] = node.value.value
        if isinstance(node, ast.FunctionDef) and node.name == "_needs_resume_first":
            fn = node
    assert fn is not None, "_needs_resume_first missing from hvac_setpoint.py"
    ns = dict(consts)
    ns["HomeAssistant"] = object
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<gate>", "exec"), ns)
    return ns["_needs_resume_first"], consts


GATE, CONSTS = _load_gate()


class _State:
    def __init__(self, hold):
        self.attributes = {} if hold is _MISSING else {"hold_activity": hold}


_MISSING = object()


class _Hass:
    def __init__(self, state):
        self._state = state

    @property
    def states(self):
        outer = self

        class _S:
            def get(self, _eid):
                return outer._state
        return _S()


def test_resume_fires_for_an_anonymous_hold():
    """THE POSITIVE CASE — the stuck-zone shape measured on zone_1."""
    assert GATE(_Hass(_State("manual")), "climate.z1", "sleep") is True


def test_resume_does_not_fire_for_a_named_hold():
    """THE NEGATIVE CASE, and the one that protects the healthy zone.

    zone_3 holds `away` and pins directly today. Firing resume there would open
    a needless window on the Bryant schedule (invariant I3) in the ONE zone that
    currently works — a regression disguised as a fix.
    """
    assert GATE(_Hass(_State("away")), "climate.z3", "home") is False


def test_no_hold_at_all_pins_directly():
    """A zone with no hold accepts a pin; resume would be pure cost."""
    assert GATE(_Hass(_State(None)), "climate.z", "home") is False
    assert GATE(_Hass(_State(_MISSING)), "climate.z", "home") is False


def test_resume_never_recurses_on_itself():
    """Writing `resume` must not first try to `resume` — infinite regress."""
    assert GATE(_Hass(_State("manual")), "climate.z1", CONSTS["PRESET_RESUME"]) is False


def test_gate_is_fail_safe_when_state_is_unavailable():
    """A missing entity must not raise — it must not block a thermostat write."""
    assert GATE(_Hass(None), "climate.missing", "home") is False


# --------------------------------------------------------------------------
# D1 — per-kind suppression TTL
# --------------------------------------------------------------------------

def _ttl_consts():
    tree = ast.parse(OVERRIDE.read_text())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            n = node.targets[0].id
            if n.startswith("SUPPRESS_TTL_SECONDS"):
                out[n] = node.value.value
    return out


def test_temp_ttl_is_unchanged():
    """The temp window must STAY short.

    kind="temp" is the only suppression that swallows a genuine human manual
    flip. Lengthening it would blind the independent witness the spurious-away
    metric depends on.
    """
    assert _ttl_consts()["SUPPRESS_TTL_SECONDS"] == 5


def test_preset_ttl_spans_the_measured_refresh_window():
    """The preset window must outlast resume -> pin -> refresh -> verify.

    Sized against the MEASURED ha_carrier refresh window (42-79s). Anything at
    or below 79 could see URA book its own write as a human override (I2).
    """
    ttls = _ttl_consts()
    assert "SUPPRESS_TTL_SECONDS_PRESET" in ttls, "per-kind preset TTL missing"
    assert ttls["SUPPRESS_TTL_SECONDS_PRESET"] > 79, (
        "preset TTL must exceed the measured 42-79s refresh window, else URA "
        "books its own second write as a human override"
    )


def test_suppress_selects_the_ttl_by_kind():
    """The split must be WIRED, not merely defined.

    A constant that nothing reads is the hollow-anchor shape: it looks like a
    fix and changes nothing.
    """
    tree = ast.parse(OVERRIDE.read_text())
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "suppress":
            target = node
    assert target is not None, "suppress() not found"
    src = ast.get_source_segment(OVERRIDE.read_text(), target) or ""
    assert "SUPPRESS_TTL_SECONDS_PRESET" in src, (
        "suppress() must actually select the preset TTL — a defined-but-unread "
        "constant is a hollow fix"
    )
    assert '"preset"' in src or "'preset'" in src
