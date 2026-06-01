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
    """Verify the new canonical accessor call replaces the broken probes."""

    def test_uses_canonical_accessor(self, weather_manager_src):
        """The function must call `preset_mgr.get_seasonal_setpoints(preset)`
        — the public method that merges SEASONAL_DEFAULTS with CM overrides."""
        idx = weather_manager_src.find("def _get_zone_baseline_high")
        assert idx > 0
        body = weather_manager_src[idx: idx + 3000]
        assert "preset_mgr.get_seasonal_setpoints(preset)" in body, (
            "v4.7.16.3 hotfix: must use the canonical accessor, not "
            "private-attr probes"
        )

    def test_old_broken_probes_removed(self, weather_manager_src):
        """Neither of the broken probes should remain in the function body.

        - `getattr(preset_mgr, "SEASONAL_DEFAULTS", None)` — module const,
          never on the instance
        - `getattr(preset_mgr, "zone_presets", {})` — attribute does not exist
        """
        idx = weather_manager_src.find("def _get_zone_baseline_high")
        body = weather_manager_src[idx: idx + 3000]
        assert 'getattr(preset_mgr, "SEASONAL_DEFAULTS"' not in body, (
            "SEASONAL_DEFAULTS probe is the bug — must be removed"
        )
        assert 'getattr(preset_mgr, "zone_presets"' not in body, (
            "zone_presets probe is the bug — must be removed"
        )

    def test_returns_cool_high_index(self, weather_manager_src):
        """The tuple returned by `get_seasonal_setpoints` is
        `(cool_low, cool_high)`. We want cool_high → index [1]."""
        idx = weather_manager_src.find("def _get_zone_baseline_high")
        body = weather_manager_src[idx: idx + 3000]
        assert "float(pair[1])" in body


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


class TestFunctionStructureUnchanged:
    """The function's public signature and call-site contract must remain
    stable so DPM + Battery callers don't have to change."""

    def test_signature_unchanged(self, weather_manager_src):
        """`baseline_delta_for_zone(zone_id, preset="home")` call path."""
        # baseline_delta_for_zone is the public caller; verify it still
        # calls _get_zone_baseline_high(zone_id, preset).
        idx = weather_manager_src.find("def baseline_delta_for_zone(")
        assert idx > 0
        body = weather_manager_src[idx: idx + 1000]
        assert "self._get_zone_baseline_high(zone_id, preset)" in body

    def test_internal_signature_unchanged(self, weather_manager_src):
        """Function still takes (zone_id, preset) and returns float | None."""
        assert (
            "def _get_zone_baseline_high(self, zone_id: str, preset: str) -> float | None:"
            in weather_manager_src
        )
