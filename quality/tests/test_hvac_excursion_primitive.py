"""Unit tests for the ``hvac_excursion`` primitive (D2, partial).

Covers the load-bearing lease-registry surface: snapshot on begin,
release on return, explicit bounded expiry (§4.4), double-return no-op,
and REJECT on overlapping begin (§4.6).

Behavioural drive tests for AC14 (lease honoured by tick) and AC14b
(vacancy arm gated too) live in ``test_hvac_excursion_lease_gate_placement.py``
because the shape of the drive is inseparable from the emit-merge-point
placement in ``_apply_house_state_presets``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock


def _load():
    root = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation",
        "domain_coordinators", "hvac_excursion.py",
    )
    name = "hvac_excursion_under_test"
    spec = importlib.util.spec_from_file_location(name, root)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass __module__ lookup needs this
    spec.loader.exec_module(mod)
    return mod


_ex = _load()


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _hass_with_preset(entity_id: str, preset: str, low=70.0, high=76.0):
    hass = MagicMock()
    st = MagicMock()
    st.attributes = {
        "preset_mode": preset,
        "target_temp_low": low,
        "target_temp_high": high,
    }
    def _get(eid):
        return st if eid == entity_id else None
    hass.states = MagicMock()
    hass.states.get = _get
    return hass


def setup_function(_):
    _ex._test_clear_leases()


def test_row_probe_false_when_absent():
    assert _ex._test_has_row("zone_1") is False


def test_begin_populates_lease_and_snapshots_unfiltered_preset():
    """§4.3 — the snapshot is UNFILTERED. `manual` at begin() is what
    the row records. This is the core rev-4/rev-5 semantic; regressing
    it re-introduces the self-disarm latch."""
    hass = _hass_with_preset("climate.z1", "manual", low=68.0, high=74.0)
    tok = _run(_ex.begin_excursion(
        hass, zone_id="zone_1", entity_id="climate.z1",
        kind=_ex.EXCURSION_KIND.NUDGE, duration_s=120,
        site="test", intended_mode="heat_cool",
    ))
    assert tok is not None
    assert tok.pre_preset == "manual"
    assert tok.pre_target_low == 68.0
    assert tok.pre_target_high == 74.0
    assert _ex._test_has_row("zone_1") is True


def test_return_clears_lease():
    hass = _hass_with_preset("climate.z1", "auto")
    tok = _run(_ex.begin_excursion(
        hass, zone_id="zone_1", entity_id="climate.z1",
        kind=_ex.EXCURSION_KIND.NUDGE, duration_s=120, site="test",
    ))
    assert _ex._test_has_row("zone_1") is True
    outcome = _run(_ex.return_excursion(tok, trigger="timer"))
    assert outcome.trigger == "timer"
    assert _ex._test_has_row("zone_1") is False


def test_double_return_is_no_op_returns_cached_outcome():
    """§4.6 double-return contract."""
    hass = _hass_with_preset("climate.z1", "auto")
    tok = _run(_ex.begin_excursion(
        hass, zone_id="zone_1", entity_id="climate.z1",
        kind=_ex.EXCURSION_KIND.NUDGE, duration_s=120, site="test",
    ))
    o1 = _run(_ex.return_excursion(tok, trigger="timer"))
    o2 = _run(_ex.return_excursion(tok, trigger="cancel"))
    assert o2 is o1  # cached, unchanged trigger


def test_begin_rejects_when_lease_already_active():
    """§4.6 REJECT-on-existing-row: overlapping begin returns None."""
    hass = _hass_with_preset("climate.z1", "auto")
    t1 = _run(_ex.begin_excursion(
        hass, zone_id="zone_1", entity_id="climate.z1",
        kind=_ex.EXCURSION_KIND.NUDGE, duration_s=120, site="test1",
    ))
    t2 = _run(_ex.begin_excursion(
        hass, zone_id="zone_1", entity_id="climate.z1",
        kind=_ex.EXCURSION_KIND.COMPROMISE, duration_s=1800, site="test2",
    ))
    assert t1 is not None
    assert t2 is None
    # Lease still points at t1
    assert _ex._test_has_row("zone_1") is True


def test_expiry_bounded_by_max_when_duration_none():
    """§4.4 unbounded lease still capped at EXCURSION_LEASE_MAX_S."""
    hass = _hass_with_preset("climate.z1", "auto")
    tok = _run(_ex.begin_excursion(
        hass, zone_id="zone_1", entity_id="climate.z1",
        kind=_ex.EXCURSION_KIND.EGRESS_PAUSE, duration_s=None, site="egress",
    ))
    assert tok is not None
    assert tok.stale_ts() == tok.started_ts + _ex.EXCURSION_LEASE_MAX_S


def test_expiry_uses_duration_plus_slack_when_bounded():
    """§4.4 bounded lease: duration + SLACK, capped at MAX."""
    hass = _hass_with_preset("climate.z1", "auto")
    tok = _run(_ex.begin_excursion(
        hass, zone_id="zone_1", entity_id="climate.z1",
        kind=_ex.EXCURSION_KIND.NUDGE, duration_s=120, site="nudge",
    ))
    expected = tok.started_ts + 120 + _ex.EXCURSION_LEASE_SLACK_S
    assert abs(tok.stale_ts() - expected) < 0.001


def test_expired_lease_reads_as_inactive_and_self_clears():
    """§4.4 stuck-lease housekeeping: an expired row is treated as absent
    and cleared on the read. AC15's discriminator lives here."""
    tok = _ex._test_seed_lease(
        "zone_1",
        kind=_ex.EXCURSION_KIND.NUDGE,
        duration_s=1,
        started_ts=1.0,  # way in the past → immediately expired
    )
    assert tok.stale_ts() < _ex._now()
    assert _ex._test_has_row("zone_1") is False
    # Cleared as a side effect
    assert "zone_1" not in _ex._rows


def test_excursion_kind_does_not_contain_hard_reset_preset_assert():
    """§8 non-goal 6 — MUST NOT exist so the hard-reset path cannot be
    routed through the primitive by analogy later."""
    names = {k.name for k in _ex.EXCURSION_KIND}
    assert "HARD_RESET_PRESET_ASSERT" not in names
    assert names == {"NUDGE", "COMPROMISE", "BANKING", "PREHEAT", "EGRESS_PAUSE"}


def test_snapshot_with_no_preset_attr_is_none_not_missing():
    """§4.3 — `pre_preset is None` is the ONLY skip case for restore
    step (b). Snapshot must faithfully record absence."""
    hass = MagicMock()
    st = MagicMock()
    st.attributes = {}  # no preset_mode
    hass.states = MagicMock()
    hass.states.get = lambda eid: st
    tok = _run(_ex.begin_excursion(
        hass, zone_id="zone_1", entity_id="climate.z1",
        kind=_ex.EXCURSION_KIND.NUDGE, duration_s=120, site="test",
    ))
    assert tok is not None
    assert tok.pre_preset is None
