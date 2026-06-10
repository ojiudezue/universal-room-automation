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
from types import SimpleNamespace
from unittest.mock import MagicMock

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

    # ---------------------------------------------------------------------
    # Production-driven round-trip — B4 review A-H1 / B-M1 (2026-06-10).
    #
    # We drive the REAL `_ec_switch_factory` body from switch.py. The body
    # is extracted via AST from production source and exec'd in a stubbed
    # namespace (the full import chain — coordinator.py → automation.py →
    # 120+ HA imports — is too heavy to load in unit tests). We then build
    # the OccupancyWeightedPredictionSwitch by calling the real factory
    # exactly as switch.py does at module-load time, and use
    # `object.__new__` to get a bare instance so we can seed it with the
    # attrs the production __init__ would set without running the __init__
    # (which reads entry.data + builds DeviceInfo).
    #
    # The restore body that runs is the SAME source text shipped to the
    # user — drift between production and test is structurally impossible
    # because the source is read at test time from disk.
    # ---------------------------------------------------------------------

    # Pollution-safe sys.modules patches: track every key we add so the
    # fixture can restore on teardown (other tests — test_activity_logger,
    # test_v47x_dynamic_preset — own these module names and break if we
    # leave stubs in sys.modules).
    _POLLUTION_KEYS = (
        "homeassistant",
        "homeassistant.helpers",
        "homeassistant.helpers.dispatcher",
        "custom_components",
        "custom_components.universal_room_automation",
        "custom_components.universal_room_automation.domain_coordinators",
        "custom_components.universal_room_automation.domain_coordinators.signals",
    )

    @pytest.fixture(autouse=True)
    def _sys_modules_isolation(self):
        """Save + restore sys.modules entries we touch. Without this, the
        stubs we install bleed into sibling test files that depend on the
        REAL packages being absent / re-importable (B4 review B-M1
        follow-up: pollution check)."""
        import sys
        saved = {k: sys.modules.get(k, None) for k in self._POLLUTION_KEYS}
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    @staticmethod
    def _build_production_oc_weighted_class():
        """Extract + exec the production _ec_switch_factory and instantiate
        the OccupancyWeightedPredictionSwitch class from it. Returns the
        real factory-produced class (the `_ECSwitch` from switch.py).

        sys.modules patches installed here are reverted by the
        `_sys_modules_isolation` autouse fixture."""
        import sys
        import types as _types

        # Pre-seed sys.modules for the function-local imports inside
        # `async_added_to_hass`. The body executes:
        #   from homeassistant.helpers.dispatcher import async_dispatcher_connect
        #   from .domain_coordinators.signals import SIGNAL_ENERGY_COORDINATOR_READY
        # Both must resolve.
        sys.modules.setdefault("homeassistant", _types.ModuleType("homeassistant"))
        sys.modules.setdefault(
            "homeassistant.helpers", _types.ModuleType("homeassistant.helpers")
        )
        disp_mod = _types.ModuleType("homeassistant.helpers.dispatcher")
        disp_mod.async_dispatcher_connect = lambda hass, sig, cb: (lambda: None)
        sys.modules["homeassistant.helpers.dispatcher"] = disp_mod
        sys.modules.setdefault(
            "custom_components", _types.ModuleType("custom_components")
        )
        sys.modules.setdefault(
            "custom_components.universal_room_automation",
            _types.ModuleType("custom_components.universal_room_automation"),
        )
        sys.modules.setdefault(
            "custom_components.universal_room_automation.domain_coordinators",
            _types.ModuleType(
                "custom_components.universal_room_automation.domain_coordinators"
            ),
        )
        sig_mod_name = (
            "custom_components.universal_room_automation.domain_coordinators.signals"
        )
        sig_mod = _types.ModuleType(sig_mod_name)
        sig_mod.SIGNAL_ENERGY_COORDINATOR_READY = "ura_ec_ready"
        sys.modules[sig_mod_name] = sig_mod

        switch_path = "custom_components/universal_room_automation/switch.py"
        with open(switch_path) as f:
            full_src = f.read()
        tree = ast.parse(full_src, filename=switch_path)
        factory_node = next(
            n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_ec_switch_factory"
        )
        factory_src = ast.get_source_segment(full_src, factory_node)
        assert factory_src is not None

        # Distinct bare bases for SwitchEntity / RestoreEntity — the
        # production `class _ECSwitch(SwitchEntity, RestoreEntity)` line
        # rejects duplicate base classes. async_get_last_state is
        # overridden per-test on the instance to feed the simulated
        # post-restart last_state.
        class _StubSwitchEntity:
            def async_on_remove(self, _unsub):
                pass

            def async_write_ha_state(self):
                pass

            async def async_added_to_hass(self):
                return None

        class _StubRestoreEntity:
            pass

        # `__package__` must be set so the exec'd body's relative import
        # (`from .domain_coordinators.signals import …`) resolves against
        # the pre-seeded sig_mod above.
        ns: dict = {
            "SwitchEntity": _StubSwitchEntity,
            "RestoreEntity": _StubRestoreEntity,
            "DeviceInfo": dict,
            "EntityCategory": SimpleNamespace(CONFIG="config"),
            "DOMAIN": "universal_room_automation",
            "VERSION": "test",
            "callback": lambda fn: fn,
            "async_call_later": lambda *a, **kw: (lambda: None),
            "_LOGGER": MagicMock(),
            "__package__": "custom_components.universal_room_automation",
            "__name__": "custom_components.universal_room_automation.switch",
        }
        exec(factory_src, ns)
        # Build OccupancyWeightedPredictionSwitch exactly as switch.py:765-771.
        return ns["_ec_switch_factory"](
            "occupancy_weighted",
            "occupancy_weighted_prediction",
            "Occupancy Weighted Prediction",
            "mdi:account-clock",
            default=False,
        )

    @staticmethod
    def _bare_instance(cls):
        """object.__new__ bypass of the production __init__ (which reads
        entry.data + builds DeviceInfo). Seed only the attrs the restore
        body reads — names taken from the production __init__."""
        s = object.__new__(cls)
        s._default = False
        s._deferred_restore = False
        s._deferred_value = False
        s._retry_index = 0
        return s

    @pytest.mark.asyncio
    async def test_round_trip_user_toggles_on_then_restart(self):
        """Drive the PRODUCTION restore body. last_state='on' + EC present →
        EC.occupancy_weighted must end at True, _deferred_restore False,
        notify_sub_switch_restore_complete fired."""
        cls = self._build_production_oc_weighted_class()
        switch = self._bare_instance(cls)

        notify_calls = []
        energy = SimpleNamespace(occupancy_weighted=False)
        energy.notify_sub_switch_restore_complete = lambda: notify_calls.append(True)

        switch.hass = SimpleNamespace(
            data={
                "universal_room_automation": {
                    "coordinator_manager": SimpleNamespace(
                        coordinators={"energy": energy}
                    )
                }
            }
        )

        async def _last_state_on():
            return SimpleNamespace(state="on")

        switch.async_get_last_state = _last_state_on

        # Production restore body executes here.
        await switch.async_added_to_hass()

        assert energy.occupancy_weighted is True, (
            "B4 (b): production restore body must overwrite the EC seed "
            "(False) with RestoreEntity 'on'."
        )
        assert switch.is_on is True
        assert switch._deferred_restore is False
        assert notify_calls == [True], (
            "production restore must fire notify_sub_switch_restore_complete "
            "so ECSubSwitchesSyncedSensor tracks per-switch sync."
        )

    @pytest.mark.asyncio
    async def test_round_trip_user_toggles_off_survives_restart(self):
        """Symmetric OFF: last_state='off' + EC.occupancy_weighted=True
        (stale hot-reload) → production restore overwrites to False."""
        cls = self._build_production_oc_weighted_class()
        switch = self._bare_instance(cls)

        energy = SimpleNamespace(occupancy_weighted=True)
        energy.notify_sub_switch_restore_complete = lambda: None

        switch.hass = SimpleNamespace(
            data={
                "universal_room_automation": {
                    "coordinator_manager": SimpleNamespace(
                        coordinators={"energy": energy}
                    )
                }
            }
        )

        async def _last_state_off():
            return SimpleNamespace(state="off")

        switch.async_get_last_state = _last_state_off

        await switch.async_added_to_hass()

        assert energy.occupancy_weighted is False, (
            "B4 (b) OFF: production restore must overwrite the stale True "
            "EC seed with RestoreEntity 'off'."
        )
        assert switch.is_on is False
        assert switch._deferred_restore is False


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
