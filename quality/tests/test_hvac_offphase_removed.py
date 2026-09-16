"""S14 off-phase ceiling hold — REMOVED 2026-09-16. Regression suite.

WHAT WAS REMOVED AND WHY
------------------------
HVAC-PRESET-FLAP-1 (2026-08-11) added "duty off-phase honesty": during an
energy coast/shed phase in an OCCUPIED zone, rather than writing `preset=away`
(which relaxes toward ~80F), S14 held `home_target_high + OFFSET` with a RAW
SETPOINT write. The intent was kind — save energy without abandoning a room
somebody is sitting in.

The defect: a raw setpoint write puts the Bryant into preset `manual`, and
`should_change_preset` refuses to act on a manual zone. So **S14 created the
exact condition that prevented its own documented exit** ("holds until the next
preset transition"). No timer, no decay, no restore — a zone could sit
off-preset indefinitely. The flap fix had introduced a permanent-manual writer.

Removed rather than repaired because the kill switch had been OFF for weeks
(operator disabled it on instinct, later: "marginal — possibly should not have
built it at all"), so the limb was already dead and the away path was already
what ran. Removal is therefore BEHAVIOUR-NEUTRAL; repair would have re-enabled
a disliked behaviour. Operator picked remove 2026-09-16.

THE DELIBERATE TRADE THIS OVERTURNS — RECORDED, NOT SILENTLY DROPPED
--------------------------------------------------------------------
The no-release behaviour was INTENDED and three artifacts encoded it:
  1. PLANNING_preset_flap_offphase_honesty.md:184-195 — the ceiling holds until
     the next preset transition BY DESIGN;
  2. :280 — a live acceptance criterion asserting NO follow-on restore fires;
  3. the shipped test `test_ceiling_held_until_next_preset_transition`, which
     ENFORCED it.

That third artifact is the important one: after the removal it would have kept
PASSING — vacuously, because with nothing writing a ceiling there is trivially
no follow-on restore. A test that passes for the opposite reason is worse than
one that fails. It is therefore INVERTED here (see
`test_ceiling_is_no_longer_held_at_all`) rather than deleted quietly.

The original rationale for wanting no release was sound and is preserved for
whoever revisits this: a release write is itself another preset transition,
i.e. FLAP — the very thing PRESET-FLAP-1 was fixing. Any future re-introduction
must fire ONCE PER OFF-PHASE, not per tick. That is the anti-flap property, and
it is the criterion separating a good design from a re-opened flap.

The superseded behavioural tests (S14 happy path, its emit throttle, its defer
rollback, its ledger cache) were removed with the feature; they live in git
history at the commit that removed them.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


DC = pathlib.Path(__file__).resolve().parents[2].joinpath(
    "custom_components", "universal_room_automation"
)
HVAC = DC / "domain_coordinators" / "hvac.py"


def _hvac_tree():
    return ast.parse(HVAC.read_text())


def test_the_raw_setpoint_writer_is_gone():
    """S14's method must not exist. This is the actual defect removal."""
    names = {
        n.name for n in ast.walk(_hvac_tree())
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_apply_duty_off_phase" not in names, (
        "S14 wrote a raw setpoint during an occupied off-phase, which put the "
        "zone into `manual` and thereby blocked its own documented exit"
    )


def test_ceiling_is_no_longer_held_at_all():
    """THE INVERTED GUARANTEE.

    `test_ceiling_held_until_next_preset_transition` asserted the ceiling is
    HELD with no follow-on restore. That encoded the defect as a guarantee, and
    after removal it would have passed VACUOUSLY. The guarantee is now the
    opposite: no ceiling is held, because nothing writes one.
    """
    src = HVAC.read_text()
    assert "_apply_duty_off_phase" not in src.replace(
        "``_apply_duty_off_phase``", ""
    ) or src.count("_apply_duty_off_phase") <= 1, (
        "only a docstring back-reference may mention the removed method"
    )
    # The off-phase limb must now resolve to the away path.
    assert "S14 REMOVED 2026-09-16" in src, (
        "the removal must be recorded AT the site, so the next reader learns "
        "why the gentler behaviour is gone rather than re-adding it"
    )


def test_offphase_now_resolves_to_away():
    """The surviving behaviour: an occupied off-phase writes preset=away.

    This is what the kill switch already produced, which is why the removal is
    behaviour-neutral.
    """
    src = HVAC.read_text()
    idx = src.index("S14 REMOVED 2026-09-16")
    tail = src[idx:idx + 2000]
    assert 'effective_preset = "away"' in tail, (
        "the off-phase limb must fall through to the away path"
    )


def test_no_inert_controls_left_behind():
    """A switch or knob that governs nothing is a footgun.

    The operator could toggle it and reasonably expect an effect. Both the
    kill-switch entity and the offset Number were removed with the feature.
    """
    for fname in ("switch.py", "number.py"):
        src = (DC / fname).read_text()
        classes = {
            n.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef)
        }
        assert "HvacOffphaseHonestyEnabledSwitch" not in classes, (
            f"{fname} still defines the S14 kill switch — it now controls nothing"
        )
        assert "ComfortOffphaseOffsetNumber" not in classes, (
            f"{fname} still defines the S14 offset knob — it now controls nothing"
        )


def test_diagnostic_attribute_does_not_claim_a_dead_state():
    """`duty_cycle_off_phase` must not report an S14 state that cannot occur."""
    src = (DC / "sensor.py").read_text()
    assert "hvac.hvac_offphase_honesty_enabled" not in src, (
        "the sensor still reads the now-inert S14 flag; the attribute would "
        "advertise a state the code can no longer enter"
    )
