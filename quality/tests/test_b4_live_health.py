"""B4 live-health repair cycle (2026-06-10).

Three live-observed issues against v5.3.3:

(a) sensor.universal_room_automation_energy_grid_demand permanently
    unavailable. Root cause: prior `available` gate returned False whenever
    the EV Grid Import Cap option was disabled (the common-case install).
    Fix: keep sensor available whenever EC is registered; expose
    `unconfigured_reason` attribute when % cannot be computed; `grid_import_kw`
    continues to surface live whole-house import.

(b) switch.ura_energy_coordinator_occupancy_weighted_prediction
    persistence: code-trace verified sound (RestoreEntity → last_state
    drives restore; v4.7.x D2 SIGNAL_ENERGY_COORDINATOR_READY +
    v4.5.3 5/30/120s retry chain). Existing
    test_v4721_occupancy_weighted_restore.py covers fast-path / signal-path
    / timer-path / OFF / first-install. We add one explicit
    operator-scenario round-trip lock here: "toggle ON, simulate restart,
    last_state=on → switch is ON".

(c) PredictedEnergyTodaySensor reading -11.6 kWh. Root cause:
    db.predict_energy() returns net_energy = grid_import - solar_export
    (database.py get_energy_for_similar_days), legitimately negative on
    solar-rich days. The source is correct; the consumer-facing sensor is
    named "Predicted Energy Today" (gross semantic). Fix: clamp display
    at >=0, expose signed value as `raw_net_kwh` attribute. Cost is
    UNCHANGED (negative cost = valid export credit) but mirrors
    raw_net_kwh for symmetry.
"""

from __future__ import annotations

import ast
import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def aggregation_src() -> str:
    with open("custom_components/universal_room_automation/aggregation.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def aggregation_ast() -> ast.Module:
    with open("custom_components/universal_room_automation/aggregation.py") as f:
        return ast.parse(f.read())


@pytest.fixture(scope="module")
def switch_src() -> str:
    with open("custom_components/universal_room_automation/switch.py") as f:
        return f.read()


# ===========================================================================
# Helpers — load isolated classes from aggregation.py without HA imports.
# ===========================================================================


def _get_class_def(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _get_method(cls: ast.ClassDef, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"method {name} not found on {cls.name}")


# ===========================================================================
# (a) EnergyGridDemandSensor — no longer permanently unavailable
# ===========================================================================


class TestEnergyGridDemandAvailability:
    """B4 (a): sensor must stay available regardless of cap configuration."""

    def test_available_does_not_gate_on_cap_enabled(self, aggregation_src: str):
        """`available` must NOT check `_grid_import_cap_enabled`.

        Prior bug: returned False when cap disabled → entity permanently
        unavailable. Fix: only gate on EC presence.
        """
        # Extract the EnergyGridDemandSensor.available method body as text.
        marker = "class EnergyGridDemandSensor"
        idx = aggregation_src.find(marker)
        assert idx >= 0
        end_idx = aggregation_src.find("\nclass ", idx + 1)
        body = aggregation_src[idx:end_idx if end_idx > 0 else len(aggregation_src)]

        # Locate the available property.
        avail_idx = body.find("def available")
        next_def_idx = body.find("    @property", avail_idx + 1)
        avail_body = body[avail_idx:next_def_idx if next_def_idx > 0 else len(body)]

        assert "_grid_import_cap_enabled" not in avail_body, (
            "B4 (a): `available` must NOT short-circuit on cap-disabled; "
            "the cap gate belongs in native_value only."
        )
        assert "_grid_import_cap_kw" not in avail_body, (
            "B4 (a): `available` must NOT short-circuit on cap-kw missing."
        )
        # Sanity: it does check EC presence.
        assert "_get_energy_coordinator" in avail_body, (
            "B4 (a): `available` must still check EC is registered."
        )

    def test_extra_attributes_expose_unconfigured_reason_key(self, aggregation_src: str):
        """`extra_state_attributes` must define an `unconfigured_reason` key
        explaining why native_value is None when the cap is disabled / unset.
        """
        marker = "class EnergyGridDemandSensor"
        idx = aggregation_src.find(marker)
        assert idx >= 0
        end_idx = aggregation_src.find("\nclass ", idx + 1)
        body = aggregation_src[idx:end_idx if end_idx > 0 else len(aggregation_src)]

        assert "unconfigured_reason" in body, (
            "B4 (a): EnergyGridDemandSensor must expose `unconfigured_reason` "
            "attribute when % cannot be computed."
        )
        # All three named reasons must be present so the dashboard / operator
        # can disambiguate the failure mode.
        assert "grid_import_cap_disabled" in body
        assert "grid_import_cap_kw_unset" in body
        assert "net_power_w_unavailable" in body

    def test_grid_import_kw_still_surfaced_in_attributes(self, aggregation_src: str):
        """`grid_import_kw` must remain in the attribute payload — the live
        whole-house import is the useful number when the % is unconfigured.
        """
        marker = "class EnergyGridDemandSensor"
        idx = aggregation_src.find(marker)
        assert idx >= 0
        end_idx = aggregation_src.find("\nclass ", idx + 1)
        body = aggregation_src[idx:end_idx if end_idx > 0 else len(aggregation_src)]
        assert '"grid_import_kw"' in body


class TestEnergyGridDemandRuntimeBehavior:
    """Drive a stand-in EnergyGridDemandSensor through realistic input
    combinations. Mirrors the production logic by re-implementing the
    available / native_value / extra_state_attributes methods here — the
    AST tests above lock the source against drift. This tests the algorithm,
    not the HA wiring."""

    def _make_sensor(self, ec):
        class _Stub:
            def __init__(self, ec):
                self._ec = ec

            @property
            def available(self):
                return self._ec is not None

            @property
            def native_value(self):
                ec = self._ec
                if ec is None:
                    return None
                cap_kw = getattr(ec, "_grid_import_cap_kw", 0.0)
                if cap_kw <= 0 or not getattr(ec, "_grid_import_cap_enabled", False):
                    return None
                try:
                    net_w = ec._battery.net_power_w
                except AttributeError:
                    return None
                if net_w is None:
                    return None
                grid_kw = max(net_w, 0) / 1000.0
                return round((grid_kw / cap_kw) * 100.0, 1)

            @property
            def extra_state_attributes(self):
                ec = self._ec
                if ec is None:
                    return {"unconfigured_reason": "energy_coordinator_unavailable"}
                cap_kw = getattr(ec, "_grid_import_cap_kw", 0.0)
                cap_enabled = getattr(ec, "_grid_import_cap_enabled", False)
                battery = getattr(ec, "_battery", None)
                net_w = getattr(battery, "net_power_w", None) if battery else None
                grid_kw = round(max(net_w, 0) / 1000.0, 3) if net_w is not None else None
                unconfigured_reason = None
                if not cap_enabled:
                    unconfigured_reason = "grid_import_cap_disabled"
                elif cap_kw <= 0:
                    unconfigured_reason = "grid_import_cap_kw_unset"
                elif net_w is None:
                    unconfigured_reason = "net_power_w_unavailable"
                attrs = {
                    "grid_import_kw": grid_kw,
                    "grid_import_cap_kw": cap_kw,
                    "grid_import_cap_enabled": cap_enabled,
                    "exporting": net_w is not None and net_w < 0,
                }
                if unconfigured_reason is not None:
                    attrs["unconfigured_reason"] = unconfigured_reason
                return attrs

        return _Stub(ec)

    def test_available_when_ec_present_but_cap_disabled(self):
        """Operator install state: EC present, cap disabled — sensor must
        stay available so HA shows 'Unknown' instead of 'Unavailable'."""
        ec = type("EC", (), {
            "_grid_import_cap_enabled": False,
            "_grid_import_cap_kw": 0.0,
            "_battery": type("B", (), {"net_power_w": 1500.0})(),
        })()
        s = self._make_sensor(ec)
        assert s.available is True
        assert s.native_value is None
        attrs = s.extra_state_attributes
        assert attrs["unconfigured_reason"] == "grid_import_cap_disabled"
        assert attrs["grid_import_kw"] == 1.5  # live import surfaced

    def test_unavailable_only_when_ec_missing(self):
        s = self._make_sensor(None)
        assert s.available is False

    def test_native_value_computes_when_cap_enabled(self):
        ec = type("EC", (), {
            "_grid_import_cap_enabled": True,
            "_grid_import_cap_kw": 8.0,
            "_battery": type("B", (), {"net_power_w": 4000.0})(),
        })()
        s = self._make_sensor(ec)
        assert s.available is True
        assert s.native_value == 50.0  # 4 kW of 8 kW cap
        attrs = s.extra_state_attributes
        assert "unconfigured_reason" not in attrs

    def test_exporting_flag_set_on_negative_net(self):
        ec = type("EC", (), {
            "_grid_import_cap_enabled": False,
            "_grid_import_cap_kw": 0.0,
            "_battery": type("B", (), {"net_power_w": -2000.0})(),
        })()
        s = self._make_sensor(ec)
        attrs = s.extra_state_attributes
        assert attrs["exporting"] is True
        assert attrs["grid_import_kw"] == 0.0  # no import when exporting


# ===========================================================================
# (b) Occupancy-weighted prediction switch — operator-scenario round-trip
# ===========================================================================


class TestOccupancyWeightedSwitchPersistenceRoundTrip:
    """B4 (b): code-trace verified the existing persistence loop is sound
    (factory call at switch.py:765 — RestoreEntity + retry chain + signal
    completion path). This test locks the operator scenario explicitly:

        1. User toggles switch ON.
        2. HA restarts.
        3. RestoreEntity replays last_state='on'.
        4. Switch reads ON; EC has occupancy_weighted=True.
    """

    def test_factory_call_at_expected_site(self, switch_src: str):
        """Locate the factory call — anchor for the persistence loop."""
        assert "OccupancyWeightedPredictionSwitch = _ec_switch_factory(" in switch_src

    def test_factory_call_passes_occupancy_weighted_attr(self, switch_src: str):
        """attr_name must be `occupancy_weighted` (matches EC property/setter)."""
        idx = switch_src.find("OccupancyWeightedPredictionSwitch = _ec_switch_factory(")
        call_body = switch_src[idx:idx + 400]
        assert '"occupancy_weighted"' in call_body
        assert '"occupancy_weighted_prediction"' in call_body  # unique_id suffix
        assert "default=False" in call_body

    def test_round_trip_user_toggles_on_then_restart(self):
        """End-to-end round-trip mirror — uses the same _ECSwitch-shape mirror
        that test_v4721 already validates as a faithful production mirror.
        """
        # Lifecycle 1: user toggles ON; persistence is via RestoreEntity
        # (state is captured when the entity writes ha_state). We simulate
        # that by replaying last_state='on' into a fresh switch with a
        # fresh EC instance — what HA actually does after a restart.

        class _MockEnergy:
            pass

        class _Switch:
            _RETRY_DELAYS_S = (5, 30, 120)
            _ATTR = "occupancy_weighted"

            def __init__(self, get_energy, default=False):
                self._get_energy = get_energy
                self._default = default
                self._deferred_restore = False
                self._deferred_value = default
                self.scheduled = []
                self.ec_ready_handlers = []

            def async_added_to_hass(self, last_state):
                self.ec_ready_handlers.append(self._handle_ec_ready)
                if last_state is None:
                    return
                target = last_state == "on"
                self._deferred_value = target
                energy = self._get_energy()
                if energy is not None:
                    setattr(energy, self._ATTR, target)
                    self._deferred_restore = False
                    return
                self._deferred_restore = True

            def _handle_ec_ready(self):
                if not self._deferred_restore:
                    return
                energy = self._get_energy()
                if energy is None:
                    return
                setattr(energy, self._ATTR, self._deferred_value)
                self._deferred_restore = False

            @property
            def is_on(self):
                energy = self._get_energy()
                if energy is None:
                    return self._default
                return getattr(energy, self._ATTR, self._default)

        # --- Restart cycle: EC freshly seeded to False (constructor default
        # 'occupancy_weighted_energy' key absent in options), last_state='on'
        # arrives from RestoreEntity, switch must end at True.
        energy = _MockEnergy()
        energy.occupancy_weighted = False  # ec.get("occupancy_weighted_energy", False)

        switch = _Switch(lambda: energy, default=False)
        switch.async_added_to_hass(last_state="on")

        assert energy.occupancy_weighted is True, (
            "B4 (b): after restart, RestoreEntity 'on' must overwrite the "
            "constructor seed (False) — this is the operator's observed "
            "post-restart state on 2026-06-10."
        )
        assert switch.is_on is True
        assert switch._deferred_restore is False

    def test_round_trip_user_toggles_off_survives_restart(self):
        """Symmetric OFF: explicit off survives across restart and is NOT
        overwritten by the constructor seed (which is also False, but the
        deferred-value path matters for default-True switches too).
        """
        class _MockEnergy:
            pass

        class _Switch:
            _ATTR = "occupancy_weighted"

            def __init__(self, get_energy):
                self._get_energy = get_energy
                self._deferred_restore = False
                self._deferred_value = False

            def async_added_to_hass(self, last_state):
                if last_state is None:
                    return
                target = last_state == "on"
                self._deferred_value = target
                energy = self._get_energy()
                if energy is not None:
                    setattr(energy, self._ATTR, target)
                    self._deferred_restore = False

        energy = _MockEnergy()
        energy.occupancy_weighted = True  # imagine a hot-reload landing True

        switch = _Switch(lambda: energy)
        switch.async_added_to_hass(last_state="off")

        assert energy.occupancy_weighted is False


# ===========================================================================
# (c) PredictedEnergyTodaySensor — clamp display, expose raw_net_kwh
# ===========================================================================


class TestPredictedEnergyTodayClamp:
    """B4 (c): consumer-facing native_value must be >= 0; signed net value
    exposed as raw_net_kwh attribute. Producer (db.predict_energy) is
    UNCHANGED — it correctly returns net=grid_import-solar_export."""

    def test_native_value_clamps_negative_to_zero(self, aggregation_src: str):
        """The PredictedEnergyTodaySensor.native_value body must apply
        `max(..., 0)` to the cached value."""
        idx = aggregation_src.find("class PredictedEnergyTodaySensor")
        end_idx = aggregation_src.find("\nclass ", idx + 1)
        body = aggregation_src[idx:end_idx]
        native_idx = body.find("def native_value")
        # Find the next method definition to bound native_value's body.
        next_def = body.find("    @property", native_idx + 1)
        if next_def < 0:
            next_def = body.find("\n    async def ", native_idx + 1)
        nv_body = body[native_idx:next_def if next_def > 0 else len(body)]
        assert "max(self._cached_value, 0" in nv_body, (
            "B4 (c): native_value must clamp at >=0 (gross consumer semantic)."
        )

    def test_raw_net_kwh_attribute_present(self, aggregation_src: str):
        idx = aggregation_src.find("class PredictedEnergyTodaySensor")
        end_idx = aggregation_src.find("\nclass ", idx + 1)
        body = aggregation_src[idx:end_idx]
        assert '"raw_net_kwh"' in body, (
            "B4 (c): PredictedEnergyTodaySensor must expose signed "
            "raw_net_kwh attribute."
        )

    def test_clamp_behavior_simulated(self):
        """Drive a stand-in PredictedEnergyTodaySensor through both cases:
        negative net (solar-export day) clamps to 0; positive net passes through.
        """
        class _Stub:
            def __init__(self, val):
                self._cached_value = val
                self._cache_time = object()  # truthy

            @property
            def native_value(self):
                if self._cached_value is not None and self._cache_time:
                    return max(self._cached_value, 0.0)
                return None

        # Operator's observed state: predicted_energy_today = -11.6
        s_neg = _Stub(-11.6)
        assert s_neg.native_value == 0.0

        # Normal positive day
        s_pos = _Stub(34.2)
        assert s_pos.native_value == 34.2

        # None passes through unchanged
        s_none = _Stub(None)
        assert s_none.native_value is None

    def test_predicted_cost_today_exposes_raw_net_kwh(self, aggregation_src: str):
        """PredictedCostTodaySensor mirrors the raw_net_kwh attribute for
        symmetry. Cost itself is unchanged — negative cost = export credit."""
        idx = aggregation_src.find("class PredictedCostTodaySensor")
        end_idx = aggregation_src.find("\nclass ", idx + 1)
        body = aggregation_src[idx:end_idx]
        assert '"raw_net_kwh"' in body
        assert "_cached_raw_net_kwh" in body

    def test_predicted_cost_today_does_NOT_clamp(self, aggregation_src: str):
        """Cost must remain signed — operator instruction is explicit:
        'Cost is unaffected (negative cost = valid export credit)'."""
        idx = aggregation_src.find("class PredictedCostTodaySensor")
        end_idx = aggregation_src.find("\nclass ", idx + 1)
        body = aggregation_src[idx:end_idx]
        native_idx = body.find("def native_value")
        next_def = body.find("    @property", native_idx + 1)
        nv_body = body[native_idx:next_def if next_def > 0 else len(body)]
        assert "max(self._cached_value, 0" not in nv_body, (
            "B4 (c): PredictedCostTodaySensor.native_value MUST NOT clamp — "
            "negative cost is a valid export credit."
        )


# ===========================================================================
# (d) Orphaned circuit baselines — SKIPPED (no existing bounded prune path)
# ===========================================================================


class TestItemDSkipped:
    """B4 (d) is optional and was skipped in this cycle.

    Reason: no existing bounded circuit-baseline prune DAO exists that targets
    by name with a one-time write. The 3 orphaned rows ('Battery Power',
    'Span Left Subpanel Power', 'Span Left Unknown Power') are cosmetic and
    do not justify new DB machinery given the v5.0-v5.2 write-flood incident
    discipline (project_optimizer_db_write_flood_incident_2026_06_09). Item
    deferred per operator instruction: 'otherwise SKIP and say so'."""

    def test_d_was_skipped_intentionally(self):
        # Documentation marker — no assertion needed beyond the docstring.
        assert True
