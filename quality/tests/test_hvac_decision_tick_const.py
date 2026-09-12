"""Behavioral anchor: HVAC decision-cycle interval routes through the
named HVAC_DECISION_TICK module constant (not an inline literal).

Rung-1 module const per Numbers-Get-Knobs — cloud API call-rate bound,
change requires review. This test detaches the value: the setup site
must pass HVAC_DECISION_TICK by NAME to async_track_time_interval, so a
mutation of the const flips the observable interval (a coincidentally-
equal literal would survive a const change and silently drift).
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path


_REPO = Path(__file__).resolve().parent.parent.parent
_CC = _REPO / "custom_components" / "universal_room_automation" / \
    "domain_coordinators"


def test_hvac_decision_tick_const_is_5_minutes():
    from custom_components.universal_room_automation.domain_coordinators \
        import hvac_const
    assert hvac_const.HVAC_DECISION_TICK == timedelta(minutes=5)


def test_hvac_setup_uses_named_tick_not_inline_literal():
    src = (_CC / "hvac.py").read_text(encoding="utf-8")
    # HVAC_DECISION_TICK must be imported from hvac_const.
    assert re.search(
        r"from \.hvac_const import \([^)]*\bHVAC_DECISION_TICK\b",
        src,
        re.DOTALL,
    ), "hvac.py must import HVAC_DECISION_TICK from .hvac_const"
    # Decision-timer install must pass the named symbol as the interval
    # argument to async_track_time_interval (behavioral anchor: mutating
    # the const flips the value used at the wire-in site).
    m = re.search(
        r"async_track_time_interval\(\s*self\.hass,\s*"
        r"self\._async_decision_cycle,\s*(?P<interval>[^,)\n]+)\s*,?\s*\)",
        src,
    )
    assert m, "decision-cycle async_track_time_interval site not found"
    assert m.group("interval").strip() == "HVAC_DECISION_TICK", (
        "decision-cycle install must pass HVAC_DECISION_TICK (not an "
        f"inline literal). Got: {m.group('interval')!r}"
    )
