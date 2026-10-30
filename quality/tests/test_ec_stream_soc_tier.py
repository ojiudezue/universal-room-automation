"""EC source failover — stream SOC tier enable (Tier 3).

Plan: docs/planning/PLANNING_ec_source_failover_class.md rev 3.1 + B2a +
operator checkpoint 2026-10-30.

Falsifiable invariants under test (plan B5):
  INV-SF2  battery_soc is None only when every configured producer fails a
           guard. A numeric, %, fresh (house max age), settled, in-envelope,
           `trusted` stream while native is down is SERVED.
  INV-SF3  `envoy_available` never reads the stream.
  INV-SF4  stream entity unset → resolver output, tier labels,
           `_soc_source_last` and trust attributes identical to develop, with
           the SHIPPED constants (no monkeypatch).
  INV-SF5  one stream miss while native is down drops to LKG, not None.
  INV-SF6  the stream is never served unless it agreed with native N times
           since boot / restore / quarantine and within the trust max age.
  INV-SF7  never served or compared inside the settle window after a
           reconnect (observed unavailable, or a sub-tick change + jump), and
           never served outside the native-referenced slew bound.
  INV-SF8  no served stream value while a configured co-witness is frozen.

Drives the REAL BatteryStrategy resolver / divergence evaluator / get_status,
the REAL EnergyCoordinator.blind_hold_active and the REAL
EVChargerController blind-window entry predicate. Expected values are
hand-derived literals (Bug Class #62); every boundary is a hard literal.
Synthetic entity ids only (plan D4).
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

P1 = importlib.import_module("test_ec_degraded_data_p1")

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_battery as eb_mod,
    energy_const as ec_mod,
)
from custom_components.universal_room_automation.domain_coordinators.energy import (  # noqa: E402
    EnergyCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (  # noqa: E402
    BatteryStrategy,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (  # noqa: E402
    TOURateEngine,
)

clock = P1.clock  # scoped dt_util fixture (restored by monkeypatch)
_st = P1._st
_setc = P1._setc
_NATIVE = "sensor.test_native_battery_soc"
_STREAM = "sensor.test_second_source_battery"
_COW = "sensor.test_second_source_load_power"
_CAP = "sensor.test_battery_capacity"
_CLOUD = P1._CLOUD
_SM = P1._SM


def _mk(clock, *, max_age=None, stream=True, cowitness=True, extra=None):
    """Same harness as test_ec_degraded_data_p1._strategy, but the per-house
    max age goes through the REAL constructor kwarg (plan D1.2)."""
    hass = MockHass()
    hass.async_create_task = lambda c: None
    t = clock.t
    _st(hass, _NATIVE, "80", unit="%", lu=t)
    _st(hass, _SM, "self_consumption", lu=t)
    cfg = {
        "battery_soc": _NATIVE,
        "cloud_charge_from_grid_oracle": P1._CFG_W,
    }
    if stream:
        cfg["battery_soc_stream"] = _STREAM
    if cowitness:
        cfg["stream_cowitness"] = _COW
    cfg.update(extra or {})
    s = BatteryStrategy(
        hass,
        reserve_soc=10,
        peak_buffer_target=80,
        entity_config=P1.phalanx_battery_entities() | cfg,
        solar_classification_mode="custom",
        custom_solar_thresholds={
            "excellent": 100.0, "good": 80.0, "moderate": 50.0, "poor": 30.0,
        },
        tou_engine=TOURateEngine(),
        stream_max_age_s=max_age,
    )
    coord = P1._Coord()
    s._coord = coord
    return s, hass, coord


def _native(hass, clock, v):
    _st(hass, _NATIVE, v, unit="%", lu=clock.t)
    _st(hass, _SM, "self_consumption", lu=clock.t)


def _native_down(hass, clock):
    _st(hass, _NATIVE, "unavailable", unit="%", lu=clock.t)
    _st(hass, _SM, "unavailable", lu=clock.t)


def _stream(hass, clock, v, *, lr_age=0, cow_age=5, lc=None):
    t = clock.t
    lu = t - timedelta(seconds=lr_age)
    s = _st(hass, _STREAM, v, unit="%", lu=lu, lr=lu)
    if lc is not None:
        s.last_changed = lc
    _st(hass, _COW, "1234", unit="W", lu=t - timedelta(seconds=cow_age))
    return s


def _earn(s, hass, clock, v="80", n=3):
    """n spaced agreeing compares while native is fresh. Each tick also
    reads battery_soc (native tier) — mirrors get_status, sets native ref."""
    for i in range(n):
        if i:
            clock.adv(seconds=60)
        _native(hass, clock, v)
        _stream(hass, clock, v)
        assert s.battery_soc == float(v)
        assert s._soc_source_last == "envoy"
        s._evaluate_stream_divergence(now=clock.t)


def _no_lkg(s):
    s._soc_lkg = s._soc_lkg_at = None


# ===========================================================================
# Shipped constants + INV-SF4 (no monkeypatch anywhere in this section)
# ===========================================================================


def test_shipped_stream_constants():
    assert ec_mod.SOC_STREAM_TIER_ENABLED is True
    assert ec_mod.DEFAULT_SOC_STREAM_MAX_AGE_S == 0
    assert ec_mod.DEFAULT_SOC_STREAM_TRUST_EARN_SAMPLES == 3
    assert ec_mod.DEFAULT_SOC_STREAM_TRUST_MAX_AGE_S == 21600
    assert ec_mod.DEFAULT_SOC_STREAM_SLEW_MARGIN_PCT == 3.0
    assert ec_mod.DEFAULT_SOC_STREAM_RECONNECT_SETTLE_S == 60
    assert ec_mod.DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S == 120
    assert ec_mod.CONF_ENERGY_STREAM_BATTERY_SOC_MAX_AGE_S == (
        "energy_stream_battery_soc_max_age_s"
    )


def test_stream_entity_unset_byte_identical_shipped_constants(clock):
    """INV-SF4 with SHIPPED constants: no stream entity → develop's order
    envoy → LKG (300 s) → cloud (600 s) → none, labels unchanged, trust attr
    `disabled`, even with a perfect stream + co-witness present in hass."""
    s, hass, _ = _mk(clock, stream=False, cowitness=False)
    _stream(hass, clock, "55")  # present in hass, NOT configured
    _native(hass, clock, "80")
    assert (s.battery_soc, s._soc_source_last) == (80.0, "envoy")
    # Native ref fields are written (internal only, rev 3.1).
    assert s._soc_native_last_value == 80.0
    assert s._soc_native_last_at == clock.t
    _native_down(hass, clock)
    clock.adv(seconds=299)
    assert (s.battery_soc, s._soc_source_last) == (80.0, "lkg")
    clock.adv(seconds=2)  # LKG 301 s old
    _st(hass, _CLOUD, "63", unit="%", lu=clock.t - timedelta(seconds=60))
    assert (s.battery_soc, s._soc_source_last) == (63.0, "cloud_fallback")
    _st(hass, _CLOUD, "63", unit="%", lu=clock.t - timedelta(seconds=601))
    assert (s.battery_soc, s._soc_source_last) == (None, "fallback_stale_reject")
    _st(hass, _CLOUD, "unavailable", unit="%", lu=clock.t)
    assert (s.battery_soc, s._soc_source_last) == (None, "none")
    s._evaluate_stream_divergence(now=clock.t)
    st = s.get_status()
    assert st["stream_trust"] == "disabled"
    assert st["stream_unproven_since"] is None
    assert st["stream_unproven_native_fresh_s"] == 0
    assert st["soc_resolution"]["tier"] in (None, "none")
    assert s._stream_div_count == 0 and s._stream_agree_count == 0


# ===========================================================================
# D1 — per-house max age (mode "a" via the config field, mode "b" default)
# ===========================================================================


class TestMaxAge:
    def test_stream_serves_when_native_down_mode_a_via_config_max_age(self, clock):
        s, hass, _ = _mk(clock, max_age=120)
        _earn(s, hass, clock, "80")
        assert s._soc_stream_trust == "trusted"
        clock.adv(seconds=30)
        _native_down(hass, clock)
        _stream(hass, clock, "80", lr_age=60)
        assert (s.battery_soc, s._soc_source_last) == (80.0, "stream")
        assert s.get_status()["soc_resolution"]["tier"] == "local_stream"

    @pytest.mark.parametrize("max_age,fresh,stale", [
        (120, 119, 121), (30, 29, 31), (3600, 3599, 3601),
    ])
    def test_stream_stale_last_reported_rejected(self, clock, max_age, fresh, stale):
        """Field-driven boundary (hard literals). A fresh co-witness would
        make mode "b" serve, so a stale lr refusing proves mode "a" from the
        FIELD (the rung-1 default is 0)."""
        s, hass, _ = _mk(clock, max_age=max_age)
        _earn(s, hass, clock, "80")
        clock.adv(seconds=10)
        _native_down(hass, clock)
        _no_lkg(s)
        _stream(hass, clock, "80", lr_age=fresh)
        assert (s.battery_soc, s._soc_source_last) == (80.0, "stream")
        _no_lkg(s)
        _stream(hass, clock, "80", lr_age=stale)
        assert s.battery_soc is None
        assert s._soc_source_last == "none"

    def test_stream_mode_a_unknown_age_refused(self, clock):
        """Mode "a": a naive last_reported (age unknown) is NOT a pass."""
        s, hass, _ = _mk(clock, max_age=120)
        _earn(s, hass, clock, "80")
        clock.adv(seconds=10)
        _native_down(hass, clock)
        _no_lkg(s)
        st = _stream(hass, clock, "80")
        st.last_reported = datetime(2026, 10, 3, 21, 0)  # naive
        st.last_updated = datetime(2026, 10, 3, 21, 0)
        assert s.battery_soc is None

    @pytest.mark.parametrize("max_age", [None, 0])
    def test_stream_mode_b_when_max_age_unset(self, clock, max_age):
        """Unset / 0 → mode "b": last_reported age ignored, co-witness
        mandatory."""
        s, hass, _ = _mk(clock, max_age=max_age)
        _earn(s, hass, clock, "80")
        clock.adv(seconds=10)
        _native_down(hass, clock)
        _no_lkg(s)
        _stream(hass, clock, "80", lr_age=3000)
        assert (s.battery_soc, s._soc_source_last) == (80.0, "stream")
        s2, hass2, _ = _mk(clock, max_age=max_age, cowitness=False)
        s2._soc_stream_trust = "trusted"
        s2._stream_last_agree_at = clock.t
        _native_down(hass2, clock)
        _stream(hass2, clock, "80")
        assert s2.battery_soc is None

    def test_mode_a_cowitness_unset_serves(self, clock):
        """Config extreme: co-witness unset in mode "a" → allowed."""
        s, hass, _ = _mk(clock, max_age=120, cowitness=False)
        _earn(s, hass, clock, "80")
        clock.adv(seconds=10)
        _native_down(hass, clock)
        _stream(hass, clock, "80", lr_age=30)
        assert (s.battery_soc, s._soc_source_last) == (80.0, "stream")

    def test_cowitness_frozen_value_refuses_stream(self, clock):
        """INV-SF8: co-witness stamp stays `last_updated` (value change):
        a fresh `last_reported` with a 121 s old value change refuses."""
        s, hass, _ = _mk(clock, max_age=120)
        _earn(s, hass, clock, "80")
        clock.adv(seconds=10)
        _native_down(hass, clock)
        _no_lkg(s)
        _stream(hass, clock, "80", lr_age=10)
        _st(hass, _COW, "1234", unit="W",
            lu=clock.t - timedelta(seconds=121), lr=clock.t)
        assert s.battery_soc is None
        _st(hass, _COW, "1234", unit="W",
            lu=clock.t - timedelta(seconds=119), lr=clock.t)
        assert s.battery_soc == 80.0

    def test_max_age_option_not_in_entity_map(self):
        m = EnergyCoordinator._build_entity_map(SimpleNamespace(), {
            "energy_stream_battery_soc_entity": "sensor.s",
            "energy_stream_battery_soc_max_age_s": 120,
        })
        assert m["battery_soc_stream"] == "sensor.s"
        assert 120 not in m.values()
        assert "energy_stream_battery_soc_max_age_s" not in m


@pytest.mark.parametrize("raw,expect", [
    (None, None), ("", None), (0, None), (0.0, None), (-5, None),
    ("abc", None), (120, 120), (120.0, 120), ("120", 120), (30, 30), (3600, 3600),
])
def test_parse_stream_max_age(raw, expect):
    from custom_components.universal_room_automation.domain_coordinators import (
        energy as em,
    )
    assert em._parse_stream_max_age_s(raw) == expect


# ===========================================================================
# D2 — earned trust
# ===========================================================================


class TestEarnedTrust:
    def test_init_state_is_unproven(self, clock):
        s, _, _ = _mk(clock)
        assert s._soc_stream_trust == "unproven"
        assert s.get_status()["stream_trust"] == "unproven"

    def test_stream_unproven_at_boot_not_served(self, clock):
        s, hass, _ = _mk(clock)
        _native_down(hass, clock)
        _stream(hass, clock, "80")
        _st(hass, _CLOUD, "50", unit="%", lu=clock.t)
        assert (s.battery_soc, s._soc_source_last) == (50.0, "cloud_fallback")

    def test_stream_earns_trust_after_n_agreements(self, clock):
        s, hass, _ = _mk(clock)
        _earn(s, hass, clock, "80", n=2)
        assert s._soc_stream_trust == "unproven"
        # Too soon (59 s): does not count.
        clock.adv(seconds=59)
        _native(hass, clock, "80")
        _stream(hass, clock, "81")
        s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "unproven"
        clock.adv(seconds=1)
        _native(hass, clock, "80")
        _stream(hass, clock, "81")
        s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "trusted"
        assert s._stream_last_agree_at == clock.t

    def test_divergent_sample_resets_earn_count(self, clock):
        s, hass, _ = _mk(clock)
        _earn(s, hass, clock, "80", n=2)
        # Constant-offset producer (no jump between reads → no settle).
        clock.adv(seconds=60)
        _native(hass, clock, "80")
        _stream(hass, clock, "84", lc=clock.t - timedelta(seconds=200))
        s._evaluate_stream_divergence(now=clock.t)
        assert s._stream_div_count == 1 and s._stream_agree_count == 0
        assert s._soc_stream_trust == "unproven"
        # 84 → 80 is a > 3 pp step: its first read only arms the settle;
        # then the count restarts from 0 → two more agreements = 2 < 3.
        clock.adv(seconds=60)
        _earn(s, hass, clock, "80", n=3)
        assert s._stream_agree_count == 2
        assert s._soc_stream_trust == "unproven"
        clock.adv(seconds=60)
        _earn(s, hass, clock, "80", n=1)
        assert s._soc_stream_trust == "trusted"

    def test_earn_wired_through_get_status(self, clock):
        """Wire-in anchor: the production caller (get_status) earns trust."""
        s, hass, _ = _mk(clock)
        for _ in range(3):
            _native(hass, clock, "80")
            _stream(hass, clock, "80")
            s.get_status()
            clock.adv(seconds=61)
        assert s._soc_stream_trust == "trusted"

    @pytest.mark.parametrize("earn,n_trusted_at", [(1, 1), (100, None)])
    def test_earn_samples_extremes(self, clock, monkeypatch, earn, n_trusted_at):
        _setc(monkeypatch, "DEFAULT_SOC_STREAM_TRUST_EARN_SAMPLES", earn)
        s, hass, _ = _mk(clock)
        _earn(s, hass, clock, "80", n=1)
        assert (s._soc_stream_trust == "trusted") == (n_trusted_at == 1)
        clock.adv(seconds=60)
        _earn(s, hass, clock, "80", n=5)
        assert (s._soc_stream_trust == "trusted") == (n_trusted_at is not None)

    def test_quarantine_recovery_needs_n_agreements(self, clock):
        s, hass, coord = _mk(clock)
        _earn(s, hass, clock, "80")
        assert s._soc_stream_trust == "trusted"
        t_jump = clock.t + timedelta(seconds=1)
        for _ in range(2):
            clock.adv(seconds=61)
            _native(hass, clock, "80")
            _stream(hass, clock, "90", lc=t_jump)
            s.battery_soc
            s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "quarantined"
        # 90 → 80 step: first read settles; then 2 agreements → unproven
        # (not trusted), counter reset.
        clock.adv(seconds=60)
        _earn(s, hass, clock, "80", n=2)
        assert s._soc_stream_trust == "quarantined"
        clock.adv(seconds=60)
        _earn(s, hass, clock, "80", n=1)
        assert s._soc_stream_trust == "unproven"
        assert s._stream_agree_count == 0
        # unproven never serves.
        clock.adv(seconds=10)
        _native_down(hass, clock)
        _no_lkg(s)
        _stream(hass, clock, "80")
        assert s.battery_soc is None
        # 2 more agreements: still unproven; the 3rd earns trust.
        clock.adv(seconds=60)
        _earn(s, hass, clock, "80", n=2)
        assert s._soc_stream_trust == "unproven"
        clock.adv(seconds=60)
        _earn(s, hass, clock, "80", n=1)
        assert s._soc_stream_trust == "trusted"

    def test_native_fresh_stream_plus_5pp_quarantined(self, clock):
        """MEDIUM-R3-1: the slew check never runs on the comparison read,
        so a real 5 pp divergence reaches quarantine although the native
        reference is seconds old (slew bound ~3.6 pp would refuse it)."""
        s, hass, coord = _mk(clock)
        _earn(s, hass, clock, "80")
        # The 80 → 85 step arms the 60 s settle at the first read (t_jump);
        # comparisons resume once it expires.
        clock.adv(seconds=60)
        t_jump = clock.t
        _native(hass, clock, "80")
        _stream(hass, clock, "85", lc=t_jump)
        s._evaluate_stream_divergence(now=clock.t)
        assert s._stream_div_count == 0
        for _ in range(2):
            clock.adv(seconds=60)
            _native(hass, clock, "80")
            _stream(hass, clock, "85", lc=t_jump)
            assert s.battery_soc == 80.0  # native ref = 80, now
            s._evaluate_stream_divergence(now=clock.t)
        assert s._soc_stream_trust == "quarantined"
        assert [n["hazard_type"] for n in coord.nm] == ["soc_stream_divergence"]
        assert "Local second-source battery level 85%" in coord.nm[0]["message"]

    def test_trust_lapse_fires_in_read_path_while_native_down(self, clock):
        s, hass, coord = _mk(clock)
        _earn(s, hass, clock, "80")
        t_agree = clock.t
        saves = coord.saves
        _native_down(hass, clock)
        clock.set(t_agree + timedelta(seconds=21599))
        _stream(hass, clock, "80")
        assert (s.battery_soc, s._soc_source_last) == (80.0, "stream")
        clock.set(t_agree + timedelta(seconds=21601))
        _stream(hass, clock, "80")
        # INV-SF5: lapse refusal drops to the LKG (2 s old), not None.
        assert (s.battery_soc, s._soc_source_last) == (80.0, "lkg")
        assert s._soc_stream_trust == "unproven"
        assert coord.saves == saves + 1
        clock.adv(seconds=400)
        _stream(hass, clock, "80")
        assert s.battery_soc is None

    def test_trust_lapses_after_max_age_get_status_attr(self, clock):
        s, hass, _ = _mk(clock)
        _earn(s, hass, clock, "80")
        _native_down(hass, clock)
        clock.adv(seconds=21601)
        _stream(hass, clock, "80")
        st = s.get_status()
        assert st["stream_trust"] == "unproven"

    def test_trust_max_age_zero_never_lapses(self, clock, monkeypatch):
        _setc(monkeypatch, "DEFAULT_SOC_STREAM_TRUST_MAX_AGE_S", 0)
        s, hass, _ = _mk(clock)
        _earn(s, hass, clock, "80")
        _native_down(hass, clock)
        clock.adv(seconds=100000)
        _stream(hass, clock, "80")
        assert (s.battery_soc, s._soc_source_last) == (80.0, "stream")

    def test_boot_during_native_outage_stays_blind(self, clock):
        """Today's behaviour: boot during the outage → never earns (evaluator
        abstains without native) → never served → SOC None → blind hold."""
        s, hass, _ = _mk(clock)
        for _ in range(12):
            _native_down(hass, clock)
            _stream(hass, clock, "80")
            s.get_status()
            assert s.battery_soc is None
            clock.adv(seconds=60)
        assert s._soc_stream_trust == "unproven"
        assert _blind_hold(s) is True

    def test_one_divergent_sample_then_native_down_residual(self, clock):
        """Accepted residual (B5): one divergent sample does not quarantine;
        if native then drops, the still-trusted stream serves."""
        s, hass, _ = _mk(clock)
        _earn(s, hass, clock, "80")
        clock.adv(seconds=60)
        _native(hass, clock, "80")
        _stream(hass, clock, "84", lc=clock.t - timedelta(seconds=120))
        assert s.battery_soc == 80.0
        s._evaluate_stream_divergence(now=clock.t)
        assert s._stream_div_count == 1 and s._soc_stream_trust == "trusted"
        clock.adv(seconds=120)
        _native_down(hass, clock)
        _stream(hass, clock, "84", lc=clock.t - timedelta(seconds=240))
        assert (s.battery_soc, s._soc_source_last) == (84.0, "stream")


class TestRestore:
    @pytest.mark.parametrize("persisted,expect", [
        ("trusted", "unproven"), ("quarantined", "quarantined"),
        ("unproven", "unproven"), ("bogus", "unproven"), (None, "unproven"),
    ])
    def test_restore_mapping(self, clock, persisted, expect):
        s, _, _ = _mk(clock)
        s.restore_stream_trust_snapshot(
            {"state": persisted, "since_iso": None} if persisted else {},
        )
        assert s._soc_stream_trust == expect

    def test_restore_trusted_becomes_unproven(self, clock):
        s, _, _ = _mk(clock)
        s.restore_stream_trust_snapshot({"state": "trusted", "since_iso": None})
        assert s._soc_stream_trust == "unproven"

    def test_restore_quarantined_stays(self, clock):
        s, _, _ = _mk(clock)
        s.restore_stream_trust_snapshot({"state": "quarantined", "since_iso": None})
        assert s._soc_stream_trust == "quarantined"

    def test_restore_unproven_stays_unproven(self, clock):
        s, _, _ = _mk(clock)
        s._soc_stream_trust = "trusted"
        s.restore_stream_trust_snapshot({"state": "unproven", "since_iso": None})
        assert s._soc_stream_trust == "unproven"

    @pytest.mark.asyncio
    async def test_trusted_persisted_restores_unproven_via_real_coordinator(self, clock):
        """Wire-in: the REAL EnergyCoordinator save/restore path."""
        s, hass, _ = _mk(clock)
        kv = P1._KV()
        hass.data["universal_room_automation"] = {"database": kv}
        _earn(s, hass, clock, "80")
        assert s._soc_stream_trust == "trusted"
        await P1._persist_shell(hass, s)._save_evse_state()
        s2, hass2, _ = _mk(clock)
        hass2.data["universal_room_automation"] = {"database": kv}
        await P1._persist_shell(hass2, s2)._restore_evse_state()
        assert s2._soc_stream_trust == "unproven"
        _native_down(hass2, clock)
        _no_lkg(s2)
        _stream(hass2, clock, "80")
        s2.battery_soc
        assert s2._soc_source_last != "stream"


# ===========================================================================
# D3 — reconnect settle + slew backstop
# ===========================================================================


def _trusted_old_native_ref(clock, minutes=30):
    """Trusted stream whose native reference is `minutes` old (slew bound
    wide enough that 0 vs 36 passes — isolates the settle guard)."""
    s, hass, coord = _mk(clock)
    _earn(s, hass, clock, "36")
    _native_down(hass, clock)
    clock.adv(minutes=minutes)
    return s, hass, coord


class TestSettle:
    def test_reconnect_sequence_unavailable_0_36_never_serves_0(self, clock):
        s, hass, _ = _trusted_old_native_ref(clock)
        _stream(hass, clock, "36")
        assert (s.battery_soc, s._soc_source_last) == (36.0, "stream")
        clock.adv(seconds=30)
        _stream(hass, clock, "unavailable")
        out = [(s.battery_soc, s._soc_source_last)]
        t_zero = clock.t + timedelta(seconds=30)
        for k in range(2):  # t_zero, t_zero+30: inside the 60 s settle
            clock.adv(seconds=30)
            _stream(hass, clock, "0", lc=t_zero)
            out.append((s.battery_soc, s._soc_source_last))
        assert (0.0, "stream") not in out
        assert out[1] == (36.0, "lkg")  # INV-SF5: miss → LKG, not None
        # Settle ends at t_zero + 60 s; then 36 returns and is served.
        clock.set(t_zero + timedelta(seconds=60))
        _stream(hass, clock, "36", lc=clock.t)
        assert (s.battery_soc, s._soc_source_last) == (36.0, "stream")

    def test_settle_boundary_literals(self, clock):
        s, hass, _ = _trusted_old_native_ref(clock)
        _stream(hass, clock, "unavailable")
        s.battery_soc
        t_back = clock.t + timedelta(seconds=5)
        _no_lkg(s)
        clock.set(t_back + timedelta(seconds=59))
        _stream(hass, clock, "36", lc=t_back)
        assert s.battery_soc is None
        clock.set(t_back + timedelta(seconds=60))
        _stream(hass, clock, "36", lc=t_back)
        assert (s.battery_soc, s._soc_source_last) == (36.0, "stream")

    def test_settle_zero_disables(self, clock, monkeypatch):
        """Config extreme: settle 0 → the value after unavailable serves."""
        _setc(monkeypatch, "DEFAULT_SOC_STREAM_RECONNECT_SETTLE_S", 0)
        s, hass, _ = _trusted_old_native_ref(clock)
        _stream(hass, clock, "unavailable")
        s.battery_soc
        clock.adv(seconds=30)
        _stream(hass, clock, "36", lc=clock.t)
        assert (s.battery_soc, s._soc_source_last) == (36.0, "stream")

    def test_sub_tick_blip_then_zero_arms_settle(self, clock):
        """Arm (b): no read saw `unavailable`, but last_changed moved since
        the last read and the value jumped > 3 pp → settle; not served."""
        s, hass, _ = _trusted_old_native_ref(clock)
        _stream(hass, clock, "36")
        assert s.battery_soc == 36.0
        t_read = clock.t
        clock.adv(seconds=30)
        _stream(hass, clock, "0", lc=t_read + timedelta(seconds=20))
        assert (s.battery_soc, s._soc_source_last) == (36.0, "lkg")
        clock.adv(seconds=30)  # t_read+60 < settle end t_read+80
        _stream(hass, clock, "0", lc=t_read + timedelta(seconds=20))
        assert (s.battery_soc, s._soc_source_last) == (36.0, "lkg")

    def test_normal_step_does_not_arm_settle(self, clock):
        s, hass, _ = _trusted_old_native_ref(clock)
        _stream(hass, clock, "36")
        assert s.battery_soc == 36.0
        clock.adv(seconds=30)
        _stream(hass, clock, "39", lc=clock.t - timedelta(seconds=10))  # 3 pp
        assert (s.battery_soc, s._soc_source_last) == (39.0, "stream")

    def test_prev_none_after_stale_read_is_no_jump(self, clock):
        """RC-1: a previous read that returned None (stale) is treated as no
        jump — the next fresh value with a moved last_changed is served."""
        s, hass, _ = _mk(clock, max_age=120)
        _earn(s, hass, clock, "36")
        _native_down(hass, clock)
        clock.adv(minutes=30)
        _stream(hass, clock, "36")
        assert (s.battery_soc, s._soc_source_last) == (36.0, "stream")
        clock.adv(seconds=30)
        _stream(hass, clock, "36", lr_age=200)  # stale → None
        s.battery_soc
        clock.adv(seconds=30)
        _no_lkg(s)
        _stream(hass, clock, "30", lc=clock.t)
        assert (s.battery_soc, s._soc_source_last) == (30.0, "stream")

    def test_settle_junk_never_reaches_comparison(self, clock):
        """Native fresh at 36 throughout; the stream drops and comes back at
        0: no divergent sample is counted (observed-unavailable arm)."""
        s, hass, _ = _mk(clock)
        _native(hass, clock, "36")
        _stream(hass, clock, "36")
        s._evaluate_stream_divergence(now=clock.t)
        assert s._stream_agree_count == 1
        clock.adv(seconds=60)
        _native(hass, clock, "36")
        _stream(hass, clock, "unavailable")
        s._evaluate_stream_divergence(now=clock.t)
        for _ in range(2):  # +60 then +90: inside 60 s from t_back (+60)
            clock.adv(seconds=30 if _ else 60)
            _native(hass, clock, "36")
            _stream(hass, clock, "0", lc=clock.t if not _ else clock.t - timedelta(seconds=30))
            s._evaluate_stream_divergence(now=clock.t)
        assert s._stream_div_count == 0
        assert s._stream_agree_count == 1

    def test_sub_tick_junk_never_reaches_comparison(self, clock):
        s, hass, _ = _mk(clock)
        _native(hass, clock, "36")
        _stream(hass, clock, "36")
        s._evaluate_stream_divergence(now=clock.t)
        t0 = clock.t
        clock.adv(seconds=60)
        _native(hass, clock, "36")
        _stream(hass, clock, "0", lc=t0 + timedelta(seconds=50))
        s._evaluate_stream_divergence(now=clock.t)
        assert s._stream_div_count == 0
        assert s._stream_last_compared_at == t0


class TestSlew:
    @pytest.fixture(autouse=True)
    def _no_settle(self, monkeypatch):
        # Isolate the slew backstop from the settle guard (config extreme
        # "settle 0"); settle has its own tests above.
        _setc(monkeypatch, "DEFAULT_SOC_STREAM_RECONNECT_SETTLE_S", 0)

    def _setup(self, clock, native="95", extra=None):
        s, hass, coord = _mk(clock, extra=extra)
        _earn(s, hass, clock, native)
        t_native = clock.t
        _native_down(hass, clock)
        return s, hass, t_native

    def test_stream_slew_backstop_rejects_zero_after_20_min(self, clock):
        s, hass, t_native = self._setup(clock)
        clock.set(t_native + timedelta(minutes=20))
        _no_lkg(s)
        _stream(hass, clock, "0")
        assert s.battery_soc is None

    def test_stream_slew_backstop_rejects_87_within_3_min(self, clock):
        s, hass, t_native = self._setup(clock)
        clock.set(t_native + timedelta(minutes=3))
        _no_lkg(s)
        _stream(hass, clock, "87")  # bound 3.84 + 3 = 6.84 < 8
        assert s.battery_soc is None

    def test_stream_slew_backstop_allows_87_after_10_min(self, clock):
        """Documents the coarse limit: bound 12.8 + 3 = 15.8 > 8."""
        s, hass, t_native = self._setup(clock)
        clock.set(t_native + timedelta(minutes=10))
        _stream(hass, clock, "87")
        assert (s.battery_soc, s._soc_source_last) == (87.0, "stream")

    def test_stream_one_pp_step_served(self, clock):
        s, hass, t_native = self._setup(clock, native="40")
        clock.set(t_native + timedelta(seconds=30))
        _stream(hass, clock, "41")  # 1 <= 0.64 + 3
        assert (s.battery_soc, s._soc_source_last) == (41.0, "stream")
        _no_lkg(s)
        _stream(hass, clock, "44")  # 4 > 3.64
        assert s.battery_soc is None

    def test_slew_reference_is_native_not_lkg(self, clock):
        """Native 95 at T; stream 87 served at T+10 min (LKG := 87). At
        T+10m30s stream 80: vs native |15| <= 13.44+3 → served; vs the LKG
        |7| > 0.64+3 would refuse."""
        s, hass, t_native = self._setup(clock)
        clock.set(t_native + timedelta(minutes=10))
        _stream(hass, clock, "87")
        assert s.battery_soc == 87.0
        clock.adv(seconds=30)
        _stream(hass, clock, "80")
        assert (s.battery_soc, s._soc_source_last) == (80.0, "stream")

    @pytest.mark.parametrize("cap_state,unit,served", [
        ("13.5", "kWh", True),    # bound 11.38 + 3 > 8
        ("13500", "Wh", True),
        (None, None, False),      # unset → 40 kWh: 6.84 < 8
        ("0", "kWh", False),      # <= 0 → constant
        ("-5", "kWh", False),
        ("unavailable", "kWh", False),
    ])
    def test_stream_slew_uses_config_capacity_entity(self, clock, cap_state, unit, served):
        extra = {"battery_capacity": _CAP}
        s, hass, t_native = self._setup(clock, extra=extra)
        if cap_state is not None:
            _st(hass, _CAP, cap_state, unit=unit, lu=clock.t)
        clock.set(t_native + timedelta(minutes=3))
        _no_lkg(s)
        _stream(hass, clock, "87")
        assert (s.battery_soc == 87.0) is served

    def test_no_native_reference_abstains(self, clock):
        s, hass, _ = _mk(clock)
        s._soc_stream_trust = "trusted"
        s._stream_last_agree_at = clock.t
        _native_down(hass, clock)
        _stream(hass, clock, "3")
        assert s._soc_native_last_value is None
        assert (s.battery_soc, s._soc_source_last) == (3.0, "stream")


# ===========================================================================
# Diagnostics + consumers
# ===========================================================================


def test_stream_unproven_native_fresh_attribute_counts(clock):
    s, hass, _ = _mk(clock)
    t0 = clock.t
    for _ in range(3):  # t0, +60, +120: native fresh, stream never compared
        _native(hass, clock, "80")
        _stream(hass, clock, "unavailable")
        st = s.get_status()
        clock.adv(seconds=60)
    assert st["stream_trust"] == "unproven"
    assert st["stream_unproven_since"] == t0.isoformat()
    assert st["stream_unproven_native_fresh_s"] == 120.0
    # Native down for one tick: no accumulation; resumes from the next
    # fresh tick (t0+240 adds 0, t0+300 adds 60).
    _native_down(hass, clock)
    s.get_status()                         # t0+180
    for _ in range(2):
        clock.adv(seconds=60)              # t0+240, t0+300
        _native(hass, clock, "80")
        _stream(hass, clock, "unavailable")
        st = s.get_status()
    assert st["stream_unproven_native_fresh_s"] == 180.0
    # Earning trust clears both attrs (first read after `unavailable` only
    # arms the settle; three spaced agreements follow).
    clock.adv(seconds=120)
    for _ in range(4):
        _native(hass, clock, "80")
        _stream(hass, clock, "80")
        st = s.get_status()
        clock.adv(seconds=61)
    assert st["stream_trust"] == "trusted"
    assert st["stream_unproven_since"] is None
    assert st["stream_unproven_native_fresh_s"] == 0


def test_envoy_available_ignores_stream(clock):
    """INV-SF3: stream serving never makes envoy_available True; the stream
    tier counts as trusted for the tick verdict."""
    s, hass, _ = _mk(clock)
    _earn(s, hass, clock, "80")
    clock.adv(seconds=30)
    _native_down(hass, clock)
    _stream(hass, clock, "80")
    s.determine_mode("off_peak", "shoulder", now=clock.t.astimezone(P1._CDT))
    assert s._tick_soc_source == "stream"
    assert eb_mod.soc_tier_trusted("stream") is True
    assert eb_mod.soc_tier_trusted("cloud_fallback") is False
    assert s.envoy_available is False


class _CoordShim:
    """Exposes the REAL EnergyCoordinator.blind_hold_active over a strategy."""

    def __init__(self, battery):
        self._battery = battery

    blind_hold_active = property(EnergyCoordinator.blind_hold_active.fget)

    def reserve_write_verifiable(self):
        return False


def _blind_hold(s):
    return _CoordShim(s).blind_hold_active


def test_blind_hold_and_evse_guard_stand_down_when_stream_serves(clock):
    """Operator ruling (3): the EVSE blind guard stands down while a trusted
    stream supplies SOC — no special case, it falls out of SOC != None."""
    s, hass, _ = _mk(clock)
    _earn(s, hass, clock, "80")
    clock.adv(seconds=30)
    _native_down(hass, clock)
    _no_lkg(s)
    _stream(hass, clock, "80")
    ev = EVChargerController(hass, evse_config={})
    shim = _CoordShim(s)
    assert shim.blind_hold_active is False
    assert ev._blind_window_entry_predicate(shim) is False
    # Same outage, stream unset (develop): blind → guard predicate engages.
    s2, hass2, _ = _mk(clock, stream=False, cowitness=False)
    _native_down(hass2, clock)
    _stream(hass2, clock, "80")
    shim2 = _CoordShim(s2)
    assert shim2.blind_hold_active is True
    assert ev._blind_window_entry_predicate(shim2) is True


# ===========================================================================
# B2a — options flow + strings
# ===========================================================================

_KEY = "energy_stream_battery_soc_max_age_s"


def _save(user_cv):
    rt = importlib.import_module("test_baec_config_flow_round_trip")
    flow = rt._make_options_flow(options={"energy_envoy_entity": "sensor.envoy"})
    flow.hass._states = {}
    flow.hass.data = {}
    with rt._ha_mocks_injected():
        return rt._run(flow.async_step_coordinator_energy(
            user_input={"cloud_verification": dict(user_cv)},
        ))


@pytest.mark.parametrize("val", [120, 30, 0, 3600])
def test_options_max_age_round_trip(val):
    r = _save({
        "energy_stream_battery_soc_entity": "sensor.test_second_source_battery",
        _KEY: val,
    })
    assert r["type"] == "create_entry", r
    assert r["data"][_KEY] == val
    assert "cloud_verification" not in r["data"]


@pytest.mark.parametrize("val", [10, 20, 29])
def test_options_max_age_below_30_rejected(val):
    r = _save({_KEY: val})
    assert r["type"] == "form", r
    assert r["errors"][_KEY] == "stream_max_age_too_small"


def test_options_schema_places_max_age_after_cowitness():
    rt = importlib.import_module("test_baec_config_flow_round_trip")
    flow = rt._make_options_flow(options={})
    flow.hass._states = {}
    flow.hass.data = {}
    with rt._ha_mocks_injected():
        r = rt._run(flow.async_step_coordinator_energy(user_input=None))
    top = {str(k): v for k, v in r["data_schema"].schema.items()}
    cv_keys = [str(k) for k in top["cloud_verification"].schema.keys()]
    i = cv_keys.index("energy_stream_cowitness_entity")
    assert cv_keys[i + 1] == _KEY


_COMP = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"


@pytest.mark.parametrize("fname", ["strings.json", "translations/en.json"])
def test_strings_b2a_exact(fname):
    d = json.loads((_COMP / fname).read_text())
    step = d["options"]["step"]["coordinator_energy"]
    cv = step["sections"]["cloud_verification"]
    assert cv["data"][_KEY] == "Local battery stream max age (s)"
    assert cv["data_description"][_KEY] == (
        "Optional. Ignore the local battery stream when its last report is "
        "older than this. Use a few times the stream's update interval (for "
        "example 120 for a sensor that updates every 30 s). Leave blank or 0 "
        "for a stream that goes unavailable by itself when it stops (such as "
        "an MQTT sensor with expire_after); then the heartbeat sensor is used "
        "instead."
    )
    assert cv["data_description"]["energy_stream_battery_soc_entity"] == (
        "Optional. A fast local battery-level sensor used when the battery "
        "gateway integration drops out. Pick one from a different integration "
        "that stays up when the gateway drops; a sensor that fails at the same "
        "time gives no protection."
    )
    assert "(for example its house load power)" in (
        cv["data_description"]["energy_stream_cowitness_entity"]
    )
    assert cv["description"].endswith(
        "The local battery stream fields set a second local source for "
        "battery level."
    )
    assert step["error"]["stream_max_age_too_small"]
