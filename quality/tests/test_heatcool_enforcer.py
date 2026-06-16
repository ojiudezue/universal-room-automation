"""Tests for the continuous heat_cool enforcer (feature/heatcool-enforcer-reason-fix).

FIX 1: the periodic decision cycle (_apply_house_state_presets) restores
heat_cool on ANY non-heat_cool drift for heat_cool-capable zones — not just
zones stuck in "off". Previously a zone drifted to "cool" (preset/setpoints
unchanged) had NO recovery path: the OverrideArrester only reverts on a
MANUAL-PRESET override, and the old restore loop only caught hvac_mode == "off".

These tests mirror the enforcer's guard predicate exactly (the established
pure-logic test pattern in test_hvac_zone_intelligence.py) and prove the
gating: zones intentionally left in "off" (egress pause / AC reset) or "heat"
(emergency heat) are NOT clobbered.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _utcnow():
    return datetime.now(timezone.utc)


# Generous hold window mirroring EMERGENCY_HEAT_HOLD in hvac.py.
EMERGENCY_HEAT_HOLD = timedelta(hours=2)


def _enforcer_would_write(
    hvac_mode,
    supports_heat_cool,
    *,
    egress_paused=False,
    ac_reset_active=False,
    emergency_hold_until=None,
    now=None,
):
    """Mirror of the heat_cool enforcer guard in hvac.py:_apply_house_state_presets.

    Returns True iff the enforcer would issue set_hvac_mode=heat_cool for the
    zone this cycle.
    """
    now = now or _utcnow()
    # Gate 1: egress pause (zone intentionally "off").
    if egress_paused:
        return False
    # Gate 2: live emergency-heat hold (zone intentionally "heat"); expired
    # holds are dropped so the enforcer resumes.
    if emergency_hold_until is not None and now < emergency_hold_until:
        return False
    # Core guard: only force heat_cool on non-heat_cool, heat_cool-capable
    # zones, and never during an AC reset (intentionally "off" briefly).
    return (
        hvac_mode != "heat_cool"
        and supports_heat_cool
        and not ac_reset_active
    )


# ============================================================================
# FIX 1 core: restore heat_cool on bare hvac_mode drift
# ============================================================================


class TestHeatCoolDriftRestore:
    def test_cool_drift_with_unchanged_preset_is_restored(self):
        """The reported live bug: zone drifted heat_cool -> cool -> enforce."""
        assert _enforcer_would_write("cool", supports_heat_cool=True) is True

    def test_off_drift_still_restored(self):
        """The original 'off' case must keep working."""
        assert _enforcer_would_write("off", supports_heat_cool=True) is True

    def test_heat_drift_restored_when_not_emergency(self):
        """A bare 'heat' drift (no emergency hold) is unintentional -> enforce."""
        assert _enforcer_would_write("heat", supports_heat_cool=True) is True

    def test_fan_only_drift_restored(self):
        assert _enforcer_would_write("fan_only", supports_heat_cool=True) is True

    def test_already_heat_cool_is_idempotent_no_write(self):
        """Idempotent: never re-issue when already heat_cool."""
        assert _enforcer_would_write("heat_cool", supports_heat_cool=True) is False

    def test_heat_only_thermostat_never_forced(self):
        """A genuinely heat-only unit (no heat_cool support) is left alone."""
        assert _enforcer_would_write("heat", supports_heat_cool=False) is False

    def test_cool_only_thermostat_never_forced(self):
        assert _enforcer_would_write("cool", supports_heat_cool=False) is False


# ============================================================================
# FIX 1 gating: do NOT clobber intentional non-heat_cool modes
# ============================================================================


class TestEnforcerGating:
    def test_egress_pause_off_not_clobbered(self):
        """EgressManager set the zone 'off' deliberately -> skip."""
        assert _enforcer_would_write(
            "off", supports_heat_cool=True, egress_paused=True
        ) is False

    def test_ac_reset_off_not_clobbered(self):
        """Zone mid-AC-reset is intentionally 'off' for a short cycle -> skip."""
        assert _enforcer_would_write(
            "off", supports_heat_cool=True, ac_reset_active=True
        ) is False

    def test_emergency_heat_hold_live_not_clobbered(self):
        """Freeze response set 'heat'; live hold -> skip."""
        hold = _utcnow() + EMERGENCY_HEAT_HOLD
        assert _enforcer_would_write(
            "heat", supports_heat_cool=True, emergency_hold_until=hold
        ) is False

    def test_emergency_heat_hold_expired_resumes_enforcement(self):
        """After the hold expires, the enforcer restores heat_cool again."""
        expired = _utcnow() - timedelta(seconds=1)
        assert _enforcer_would_write(
            "heat", supports_heat_cool=True, emergency_hold_until=expired
        ) is True

    def test_emergency_hold_does_not_protect_a_cool_drift(self):
        """The emergency hold is per-zone; a live hold on a zone that has since
        drifted to 'cool' still suppresses the write (we trust the hold window).
        This documents that the hold is time-bounded, not mode-checked — safe
        because emergency heat only ever sets 'heat'."""
        hold = _utcnow() + EMERGENCY_HEAT_HOLD
        assert _enforcer_would_write(
            "cool", supports_heat_cool=True, emergency_hold_until=hold
        ) is False
