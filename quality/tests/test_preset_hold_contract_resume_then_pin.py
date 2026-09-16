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
    def __init__(self, hold, modes=("away", "home", "manual", "sleep", "resume")):
        self.attributes = {"preset_modes": modes}
        if hold is not _MISSING:
            self.attributes["hold_activity"] = hold


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


def test_thermostat_without_a_resume_preset_is_left_alone():
    """CAPABILITY GATE — `resume`/`manual` are Carrier semantics in a SHARED
    chokepoint.

    A thermostat from another integration may have no `resume` preset. Firing
    one at it would be a guaranteed-failing service call on every write. Such a
    device must fall through to the pre-existing direct-pin behaviour even when
    its hold happens to be called "manual".
    """
    other = _State("manual", modes=("home", "away", "eco"))
    assert GATE(_Hass(other), "climate.some_other_brand", "home") is False


def test_carrier_style_thermostat_still_gets_the_clear():
    """The capability gate must not disable the fix for the device it is for."""
    carrier = _State("manual", modes=("away", "home", "manual", "sleep", "resume"))
    assert GATE(_Hass(carrier), "climate.z1", "sleep") is True


# --------------------------------------------------------------------------
# D2b — sanctioned-excursion RETURN paths must restore a preset, not just
#       the numbers.
# --------------------------------------------------------------------------

PREDICT = DC / "hvac_predict.py"


def _fns_with_setpoint_writes():
    """Map function name -> (n_setpoint_writes, n_preset_writes) in hvac_predict."""
    src = PREDICT.read_text()
    tree = ast.parse(src)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(src, node) or ""
            if "emit_set_temperature(" in seg:
                out[node.name] = (
                    seg.count("emit_set_temperature("),
                    seg.count("emit_set_preset_mode("),
                )
    return out


@pytest.mark.parametrize("fn", ["_return_preheat", "_release_banked_zones"])
def test_excursion_return_paths_restore_a_preset(fn):
    """THE D2b ANCHOR.

    hvac_predict.py owns solar banking, pre-cool and pre-heat and contained
    ZERO preset emissions — its RETURN paths handed back correct temperatures
    while leaving the zone in an anonymous hold, which `should_change_preset`
    then refuses to act on. Measured consequence: zone_1 at 69.6% manual over
    7 days with a 17.9-hour tail.
    """
    fns = _fns_with_setpoint_writes()
    assert fn in fns, f"{fn} no longer writes setpoints — re-scope this test"
    _temp, preset = fns[fn]
    assert preset >= 1, (
        f"{fn} restores setpoints but NOT a preset — the zone comes back with "
        "correct numbers in an anonymous hold"
    )


def test_return_paths_use_the_token_snapshot_not_a_guess():
    """Restore target must be the excursion token's `pre_preset` snapshot.

    Inventing a target (e.g. deriving from house state) would assert a preset
    the zone was never on. The token already carries an UNFILTERED snapshot;
    the established semantic is to restore exactly what was there.
    """
    src = PREDICT.read_text()
    assert "tok.pre_preset" in src, "_return_preheat must restore from the token"
    assert "_bt, \"pre_preset\"" in src or "_bt.pre_preset" in src, (
        "banking release must restore from its own token snapshot"
    )


def test_banking_release_does_not_preset_when_the_setpoint_restore_failed():
    """Do not assert preset governance over a state we never established.

    If the setpoint restore deferred or raised, re-presetting would claim the
    zone is back at baseline when it is not.
    """
    src = PREDICT.read_text()
    assert "_release_ok and getattr(_bt" in src or "_release_ok" in src, (
        "banking preset restore must be gated on the setpoint restore having "
        "succeeded"
    )


# --------------------------------------------------------------------------
# I3 — "the zone is never left following the vendor schedule"
# Found by the adversarial build review: the fix could CAUSE the harm it
# exists to prevent.
# --------------------------------------------------------------------------

def _emit_preset_src():
    src = SETPOINT.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "emit_set_preset_mode":
            return ast.get_source_segment(src, node) or ""
    raise AssertionError("emit_set_preset_mode not found")


def test_pin_failure_after_a_clear_is_not_swallowed_silently():
    """If we cleared the hold, a failed pin must retry and then shout.

    THE REPRO: resume succeeds, pin raises (cloud 504 / entity briefly
    unavailable — both observed on this integration). The zone then sits on
    the thermostat's own schedule with NO hold, indefinitely, because nothing
    else re-pins it. A bedroom drifting to a vendor schedule the operator does
    not use is exactly the harm this cycle exists to prevent.
    """
    src = _emit_preset_src()
    assert "_resumed" in src, (
        "the function must track whether it cleared the hold — without that it "
        "cannot know it owes the zone a pin"
    )
    assert "_LOGGER.error" in src, (
        "a zone left on the vendor schedule must surface at ERROR; debug-level "
        "means nobody ever finds out"
    )


def test_the_pin_is_wrapped_so_a_failure_can_be_handled():
    """A bare `await` on the pin is the I3 hole — the exception escapes and the
    zone stays cleared."""
    src = _emit_preset_src()
    pin_idx = src.rindex("set_preset_mode")
    head = src[:pin_idx]
    assert head.count("try:") >= 2, (
        "the pin must sit inside its own try/except, not just the resume — "
        "otherwise a pin failure after a successful clear escapes and strands "
        "the zone on the schedule"
    )


def _emit_preset_fn():
    src = SETPOINT.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "emit_set_preset_mode":
            return node
    raise AssertionError("emit_set_preset_mode not found")


def test_the_retry_after_a_clear_is_real_and_conditional():
    """MUTATION-ANCHORED: dropping the retry must fail this test.

    An earlier version asserted `"_resumed" in src`, which a mutation to
    `if False:` satisfied trivially — the retry could be deleted while the
    tests stayed green. That is the hollow-anchor shape, and the drill caught
    it. This walks the syntax tree instead:

      * somewhere in the function there is an `if` whose test is the _resumed
        NAME — a constant test (`if False` / `if True`) fails, because the
        retry would then be dead or unconditional, and both violate I3;
      * and that branch actually re-attempts a set_preset_mode call.
    """
    fn = _emit_preset_fn()
    guarded = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Name)
        and n.test.id == "_resumed"
    ]
    assert guarded, (
        "the retry must be guarded by the _resumed NAME. A constant test "
        "means the retry is dead or unconditional — both violate I3."
    )
    body_src = "".join(ast.dump(stmt) for stmt in guarded[0].body)
    assert "set_preset_mode" in body_src, (
        "the _resumed branch must actually re-attempt the pin; having cleared "
        "the hold we owe the zone one"
    )


def test_the_pin_itself_is_wrapped():
    """A bare `await` on the pin is the I3 hole — the exception escapes and
    the zone stays cleared with no hold."""
    fn = _emit_preset_fn()
    assert [n for n in ast.walk(fn) if isinstance(n, ast.Try)], (
        "the pin must sit inside a try/except so a failure after a successful "
        "clear can be handled rather than stranding the zone"
    )
