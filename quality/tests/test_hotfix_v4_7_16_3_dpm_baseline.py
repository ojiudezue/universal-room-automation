"""Hotfix v4.7.16.3 — DPM baseline derivation fix.

`WeatherProviderManager._get_zone_baseline_high` previously probed two
attributes that `PresetManager` does not expose as instance state:
`SEASONAL_DEFAULTS` (module constant in `hvac_const.py:284`, not bound
to the instance) and `zone_presets` (does not exist). Both `getattr`
calls returned None, so `baseline_delta_for_zone` always returned None
and DPM emitted `skipped_zones_with_reason: "no_forecast_delta"` on
every tick.

The fix routes through `preset_mgr.get_seasonal_setpoints(preset)` —
the canonical accessor at `hvac_preset.py:118` that merges
`SEASONAL_DEFAULTS` with CM `entry.options` overrides per the v4.7.3
D2 contract.

Source-grep style (matches the v4.7.x convention) — fast, no running
HA required. Runtime behavior covered by post-deploy live validation
of the `bucket_*` sensor `delta_f` / `baseline_high_f` attributes.
"""

import pytest


@pytest.fixture(scope="module")
def weather_manager_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/weather_manager.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_preset_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_preset.py"
    ) as f:
        return f.read()


class TestBaselineFix:
    """v4.7.17.2 SUPERSEDES this fix.

    v4.7.16.3/v4.7.16.4 fixed `_get_zone_baseline_high` to use the
    canonical `PresetManager.get_seasonal_setpoints(preset)` accessor
    + correct tuple-index (cool, not heat).

    v4.7.17.2 redesign DELETED `_get_zone_baseline_high` entirely.
    The semantic is no longer "forecast - operator cool_target" but
    "forecast - 14-day rolling median apparent_high" (a self-tuning
    proxy for local climate norm). Operator framing rejected the
    indoor-target frame because it conflated "what I want indoors"
    with "what counts as a mild outdoor day."

    The tests below now verify the v4.7.17.2 post-deletion state:
    the broken function is gone, the canonical accessor is still
    importable for HVAC consumers (hvac.py:1191 still uses it), and
    Bug Class #49's tuple-shape contract guard remains intact.
    """

    def test_v4_7_17_2_removed_zone_baseline_helper(self, weather_manager_src):
        """v4.7.17.2: _get_zone_baseline_high was deleted entirely —
        the rolling-median mechanic replaces it. Removes the v4.7.16.4
        Bug Class #49 surface point at the source."""
        assert "def _get_zone_baseline_high" not in weather_manager_src

    def test_baseline_delta_uses_rolling_median_not_preset_manager(
        self, weather_manager_src,
    ):
        """v4.7.17.2: baseline_delta_for_zone now calls
        _rolling_median_apparent_high(), NOT the deleted helper."""
        idx = weather_manager_src.find("def baseline_delta_for_zone(")
        assert idx > 0
        body = weather_manager_src[idx: idx + 2500]
        assert "self._rolling_median_apparent_high()" in body
        # Old helper call must be gone from the body
        assert "_get_zone_baseline_high" not in body
        # No direct PresetManager access from WPM anymore
        assert "get_seasonal_setpoints" not in body

    def test_broken_v4_7_16_3_probes_remain_absent(self, weather_manager_src):
        """The original SEASONAL_DEFAULTS / zone_presets probes were the
        v4.7.16.3 bug. They must never reappear — even though the helper
        is gone, future replacements must not regress to the bad pattern."""
        assert 'getattr(preset_mgr, "SEASONAL_DEFAULTS"' not in weather_manager_src
        assert 'getattr(preset_mgr, "zone_presets"' not in weather_manager_src


class TestUpstreamAccessorExists:
    """Verify the canonical accessor we now depend on actually exists in
    PresetManager. Guards against silent breakage if PresetManager is
    refactored."""

    def test_get_seasonal_setpoints_method_exists(self, hvac_preset_src):
        assert "def get_seasonal_setpoints(" in hvac_preset_src

    def test_get_seasonal_setpoints_returns_tuple(self, hvac_preset_src):
        """Signature must remain `(preset, season=None) -> tuple[float, float] | None`
        so the (cool_low, cool_high) indexing is safe."""
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        assert idx > 0
        sig = hvac_preset_src[idx: idx + 400]
        assert "tuple[float, float] | None" in sig

    def test_get_seasonal_setpoints_reads_seasonal_defaults(self, hvac_preset_src):
        """Confirm the accessor reads from SEASONAL_DEFAULTS (the source of
        truth) and applies CM entry.options overrides on top."""
        idx = hvac_preset_src.find("def get_seasonal_setpoints(")
        body = hvac_preset_src[idx: idx + 4000]
        assert "SEASONAL_DEFAULTS" in body
        # v4.7.3 D2: CM entry.options overrides merged on top
        assert "entry.options" in body or "entry_options" in body or "cm_options" in body


class TestTupleShapeAgreement:
    """v4.7.16.4 + Bug Class #49: WPM and the canonical HVAC consumer
    must agree on the tuple shape returned by `get_seasonal_setpoints`.

    The shape is (cool_setpoint, heat_setpoint), authoritative at
    `hvac_const.py:283` and `hvac.py:1190-1198`. If a future refactor
    swaps the tuple order, both the canonical consumer in hvac.py AND
    the WPM accessor must change together; this test couples them so
    drift in either is caught.
    """

    @pytest.fixture(scope="module")
    def hvac_src(self) -> str:
        with open(
            "custom_components/universal_room_automation/"
            "domain_coordinators/hvac.py"
        ) as f:
            return f.read()

    def test_canonical_hvac_consumer_destructures_cool_first(self, hvac_src):
        """`hvac.py:1190-1200` destructures
        `baseline_cool, _baseline_heat = baseline` — cool is index 0."""
        assert "baseline_cool, _baseline_heat = baseline" in hvac_src

    def test_canonical_hvac_consumer_documents_cool_is_high(self, hvac_src):
        """The canonical site has an explicit comment so future readers
        don't make the same `pair[1]` mistake the v4.7.16.3 builder did."""
        assert (
            "(cool_setpoint, heat_setpoint) — cool is the high" in hvac_src
        ), (
            "hvac.py canonical comment must remain to prevent recurrence of "
            "v4.7.16.3 Bug Class #49 (tuple shape assumption drift)"
        )

    def test_seasonal_defaults_documents_tuple_shape(self):
        """`hvac_const.py:283` comment is the source of truth for the
        SEASONAL_DEFAULTS tuple shape. Lock it down."""
        with open(
            "custom_components/universal_room_automation/"
            "domain_coordinators/hvac_const.py"
        ) as f:
            src = f.read()
        assert "{season: {preset: (cool, heat)}}" in src

    def test_v4_7_17_2_new_call_site_indexes_cool_at_zero(self):
        """v4.7.17.2 fix-up A-M2: lock the tuple shape for the new DPM
        call site in `_build_overrides_with_reason`. The cycle added a
        fresh `get_seasonal_setpoints` consumer at dynamic_preset.py
        (`_season_pair = _pm.get_seasonal_setpoints(...)`) and indexes
        `_season_pair[0]` as the cool setpoint. Bug Class #49 requires
        a parallel test that fails if the tuple order regresses.

        This test guards two things:
          1. The new caller uses `[0]` (cool), not `[1]` (heat).
          2. The canonical-contract comment is present in the new caller
             so a future reader understands why `[0]` is correct.
        """
        with open(
            "custom_components/universal_room_automation/"
            "domain_coordinators/dynamic_preset.py"
        ) as f:
            src = f.read()
        idx = src.find("def _build_overrides_with_reason")
        assert idx > 0
        body = src[idx: idx + 8000]
        # The new call site indexes [0] for cool — not [1].
        assert "_season_pair[0]" in body
        assert "_season_pair[1]" not in body
        # Canonical-contract comment from Bug Class #49 fix pattern
        assert "(cool_setpoint, heat_setpoint)" in body


class TestPublicCallerContractV4_7_17_2:
    """v4.7.17.2: `baseline_delta_for_zone(zone_id, preset)` remains
    the public API; DPM + Battery + sensor callers are unchanged. The
    internal mechanic flipped from `forecast - cool_target` to
    `forecast - 14d rolling median apparent_high`."""

    def test_public_signature_unchanged(self, weather_manager_src):
        """Callers pass (zone_id, preset). Signature must stay stable."""
        idx = weather_manager_src.find("def baseline_delta_for_zone(")
        assert idx > 0
        sig = weather_manager_src[idx: idx + 200]
        assert "zone_id" in sig and "preset" in sig

    def test_returns_float_or_none(self, weather_manager_src):
        """Return contract preserved for callers that None-guard."""
        idx = weather_manager_src.find("def baseline_delta_for_zone(")
        assert idx > 0
        sig = weather_manager_src[idx: idx + 200]
        assert "float | None" in sig
