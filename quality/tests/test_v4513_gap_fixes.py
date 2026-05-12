"""v4.5.13 — Observability gap fixes.

Two surgical fixes deferred from v4.5.12 live validation:

Fix 1: HVACACRampKwhRateSensor reads source AC load sensor directly,
       independent of the AC ramp-down master switch. v4.5.12 read from
       ZoneState.last_kwh_rate which OverrideArrester only populates while
       the master switch is ON. Diagnostic sensor must reflect reality.

Fix 2: AnomalyDetector.get_learning_status returns ACTIVE when a MAJORITY
       of metrics have complete baselines, not ALL. v4.5.12 (and prior)
       left presence/safety/security/HVAC/NM detectors stuck in `learning`
       for weeks because some metrics never received observations.

These tests blend source-grep (cheap structural assertions), AST (no
regressed Bug Class #34 imports), and behavior tests for the gate.
The kwh_rate source-read path is exercised by source-grep + AST because
the runtime path needs a HomeAssistant test harness (covered by the
runtime smoke framework, which skips locally without
pytest-homeassistant-custom-component).
"""

import ast

import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open("custom_components/universal_room_automation/sensor.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def diagnostics_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/coordinator_diagnostics.py"
    ) as f:
        return f.read()


# ===========================================================================
# Fix 1: kWh Rate sensor reads source directly
# ===========================================================================


def test_kwh_rate_sensor_no_longer_reads_zone_last_kwh_rate(sensor_src: str):
    """The native_value path must not return zone.last_kwh_rate. That field
    is gated by the AC ramp master switch and was the root cause of the
    v4.5.12 'always unknown' bug.

    The string `last_kwh_rate` may still appear in docstrings or in the
    underlying ZoneState/OverrideArrester paths (which are unchanged), but
    the sensor's read path must not depend on it.
    """
    tree = ast.parse(sensor_src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "HVACACRampKwhRateSensor"):
            continue
        # Inspect every function body in the class
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if item.name not in {"native_value", "_read_source_kw"}:
                continue
            # Walk for `getattr(zone, "last_kwh_rate", ...)` or `zone.last_kwh_rate`
            for sub in ast.walk(item):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    if (
                        isinstance(func, ast.Name)
                        and func.id == "getattr"
                        and len(sub.args) >= 2
                        and isinstance(sub.args[1], ast.Constant)
                        and sub.args[1].value == "last_kwh_rate"
                    ):
                        pytest.fail(
                            f"HVACACRampKwhRateSensor.{item.name} still reads "
                            f"zone.last_kwh_rate — this is the v4.5.12 bug."
                        )
                if isinstance(sub, ast.Attribute) and sub.attr == "last_kwh_rate":
                    pytest.fail(
                        f"HVACACRampKwhRateSensor.{item.name} still accesses "
                        f".last_kwh_rate — this is the v4.5.12 bug."
                    )
        return
    pytest.fail("HVACACRampKwhRateSensor class not found in sensor.py")


def test_kwh_rate_sensor_reads_hass_states_get(sensor_src: str):
    """The native_value path must reach hass.states.get(<source_entity>).

    Asserted via AST: any function in HVACACRampKwhRateSensor must contain
    a Call to self.hass.states.get(...).
    """
    tree = ast.parse(sensor_src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "HVACACRampKwhRateSensor"):
            continue
        found = False
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            # self.hass.states.get(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "states"
            ):
                found = True
                break
        assert found, (
            "HVACACRampKwhRateSensor must call hass.states.get(...) somewhere — "
            "otherwise the source-read fix isn't actually wired."
        )
        return
    pytest.fail("HVACACRampKwhRateSensor class not found in sensor.py")


def test_kwh_rate_sensor_converts_w_to_kw(sensor_src: str):
    """Source-grep: must handle W -> kW conversion. Source sensors on the
    canonical install (Span panel) emit W; native unit on this sensor is kW.
    """
    # Locate the class body
    start = sensor_src.find("class HVACACRampKwhRateSensor(")
    assert start >= 0, "HVACACRampKwhRateSensor class missing"
    end = sensor_src.find("\nclass ", start + 1)
    body = sensor_src[start:end if end > 0 else None]
    # Look for the W conversion idiom
    assert "/ 1000" in body or "/1000" in body, (
        "kWh Rate sensor must convert W to kW when source unit is W."
    )
    assert '"W"' in body, (
        "kWh Rate sensor must check for unit_of_measurement == 'W'."
    )


def test_kwh_rate_sensor_handles_unknown_unavailable(sensor_src: str):
    """Defensive: must return None when source is unknown/unavailable rather
    than crashing or returning a stale value.
    """
    start = sensor_src.find("class HVACACRampKwhRateSensor(")
    assert start >= 0
    end = sensor_src.find("\nclass ", start + 1)
    body = sensor_src[start:end if end > 0 else None]
    assert '"unknown"' in body and '"unavailable"' in body, (
        "kWh Rate sensor must explicitly guard against 'unknown'/'unavailable' "
        "source states."
    )


def test_kwh_rate_sensor_no_function_local_datetime_shadow(sensor_src: str):
    """Bug Class #34 prevention: `datetime` is imported at module-level.
    A function-local `from datetime import datetime` inside the kWh Rate
    sensor would shadow the module-level name and is forbidden.
    """
    start = sensor_src.find("class HVACACRampKwhRateSensor(")
    assert start >= 0
    end = sensor_src.find("\nclass ", start + 1)
    body = sensor_src[start:end if end > 0 else None]
    # function-local `from datetime import datetime` is the Bug Class #34 shape
    assert "from datetime import datetime" not in body, (
        "Bug Class #34 regression: HVACACRampKwhRateSensor must not "
        "function-locally import datetime — it's at module level (line 23)."
    )


# ===========================================================================
# Fix 2: AnomalyDetector gate relaxation
# ===========================================================================


def _load_anomaly_detector():
    """Load AnomalyDetector + LearningStatus directly from the source file.

    coordinator_diagnostics.py imports `from homeassistant.core import
    HomeAssistant` and `from ..const import DOMAIN`. We use importlib to
    load it as a standalone module with both deps stubbed — bypassing the
    package's heavy `__init__.py` (which transitively requires the full HA
    runtime). The surface under test (get_learning_status / get_status_summary)
    is pure Python; no HA call needed at runtime.
    """
    import sys
    import types
    import importlib.util
    from pathlib import Path

    if "ura_anomaly_detector_under_test" in sys.modules:
        mod = sys.modules["ura_anomaly_detector_under_test"]
        return mod.AnomalyDetector, mod.LearningStatus

    # Stub homeassistant surface
    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant"); ha.__path__ = []
        ha_core = types.ModuleType("homeassistant.core")
        ha_core.HomeAssistant = type("HomeAssistant", (), {})
        ha_helpers = types.ModuleType("homeassistant.helpers"); ha_helpers.__path__ = []
        ha_helpers_event = types.ModuleType("homeassistant.helpers.event")
        ha_helpers_event.async_call_later = lambda *a, **kw: None
        sys.modules["homeassistant"] = ha
        sys.modules["homeassistant.core"] = ha_core
        sys.modules["homeassistant.helpers"] = ha_helpers
        sys.modules["homeassistant.helpers.event"] = ha_helpers_event

    # Stub the relative `..const` parent that coordinator_diagnostics imports.
    # We register a synthetic package so importlib sees `..const` as resolvable.
    pkg = types.ModuleType("ura_diag_pkg"); pkg.__path__ = []
    const = types.ModuleType("ura_diag_pkg.const"); const.DOMAIN = "universal_room_automation"
    sys.modules["ura_diag_pkg"] = pkg
    sys.modules["ura_diag_pkg.const"] = const

    root = Path(__file__).resolve().parents[2]
    src = root / "custom_components" / "universal_room_automation" / \
        "domain_coordinators" / "coordinator_diagnostics.py"

    spec = importlib.util.spec_from_file_location(
        "ura_diag_pkg.coordinator_diagnostics", str(src),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ura_diag_pkg.coordinator_diagnostics"] = mod
    # Patch the relative import: coordinator_diagnostics uses `from ..const`
    # which, with __package__ = "ura_diag_pkg.foo", resolves to ura_diag_pkg.const.
    mod.__package__ = "ura_diag_pkg.foo"
    spec.loader.exec_module(mod)
    sys.modules["ura_anomaly_detector_under_test"] = mod
    return mod.AnomalyDetector, mod.LearningStatus


class _StubHass:
    """Minimal stub. AnomalyDetector only reads hass.data inside _database
    property — never used by get_learning_status.
    """
    data: dict = {}


def _seed_baseline(detector, metric: str, scope: str, count: int):
    """Force a baseline's sample_count to `count` by recording N samples."""
    for _ in range(count):
        detector.record_observation(metric, scope, 1.0)


def test_gate_relaxation_active_when_half_metrics_complete():
    """With 4 metrics and minimum_samples=10, ACTIVE when 2 metrics are
    above threshold (50% = floor(4/2) = 2).
    """
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2", "m3", "m4"],
        minimum_samples=10,
    )
    _seed_baseline(det, "m1", "house", 12)
    _seed_baseline(det, "m2", "house", 12)
    # m3 and m4 never observed
    assert det.get_learning_status("house") == LearningStatus.ACTIVE


def test_gate_relaxation_learning_when_minority_complete():
    """With 4 metrics and only 1 above threshold (25%), still LEARNING."""
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2", "m3", "m4"],
        minimum_samples=10,
    )
    _seed_baseline(det, "m1", "house", 12)
    _seed_baseline(det, "m2", "house", 3)  # learning, not active
    assert det.get_learning_status("house") == LearningStatus.LEARNING


def test_gate_relaxation_insufficient_when_no_samples():
    """Zero samples on any metric -> INSUFFICIENT_DATA (unchanged behavior)."""
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2"],
        minimum_samples=10,
    )
    assert det.get_learning_status("house") == LearningStatus.INSUFFICIENT_DATA


def test_gate_relaxation_active_for_single_metric_detector():
    """Single-metric detector: max(1, 1//2) = 1. ACTIVE when that one metric
    crosses minimum_samples.
    """
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1"],
        minimum_samples=10,
    )
    _seed_baseline(det, "m1", "house", 12)
    assert det.get_learning_status("house") == LearningStatus.ACTIVE


def test_gate_relaxation_active_for_two_metric_detector_one_complete():
    """Two-metric detector: max(1, 2//2) = 1. ACTIVE when either metric
    crosses minimum_samples.
    """
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2"],
        minimum_samples=10,
    )
    _seed_baseline(det, "m1", "house", 12)
    # m2 never observed
    assert det.get_learning_status("house") == LearningStatus.ACTIVE


def test_gate_relaxation_three_metric_floor_half_min_one():
    """Three-metric detector: max(1, 3//2) = 1. The docstring is honest
    that this is floor-half-with-floor-1 semantics, not majority. Pin
    the actual behavior: 1-of-3 = ACTIVE (matches the floor math).
    """
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2", "m3"],
        minimum_samples=10,
    )
    _seed_baseline(det, "m1", "house", 12)
    # m2 and m3 never observed
    assert det.get_learning_status("house") == LearningStatus.ACTIVE


def test_gate_relaxation_five_metric_floor_half():
    """Five-metric detector: max(1, 5//2) = 2. Pin behavior: 2-of-5 ACTIVE,
    1-of-5 LEARNING.
    """
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2", "m3", "m4", "m5"],
        minimum_samples=10,
    )
    _seed_baseline(det, "m1", "house", 12)
    _seed_baseline(det, "m2", "house", 12)
    assert det.get_learning_status("house") == LearningStatus.ACTIVE

    det2 = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2", "m3", "m4", "m5"],
        minimum_samples=10,
    )
    _seed_baseline(det2, "m1", "house", 12)
    # one complete, four either learning or insufficient
    _seed_baseline(det2, "m2", "house", 3)
    assert det2.get_learning_status("house") == LearningStatus.LEARNING


def test_gate_relaxation_active_when_all_metrics_complete():
    """Backward-compatibility: when ALL metrics are complete (the old
    requirement), ACTIVE still holds. This guards against accidental
    inversion of the comparison.
    """
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2", "m3"],
        minimum_samples=10,
    )
    _seed_baseline(det, "m1", "house", 12)
    _seed_baseline(det, "m2", "house", 12)
    _seed_baseline(det, "m3", "house", 12)
    assert det.get_learning_status("house") == LearningStatus.ACTIVE


def test_get_status_summary_still_shows_per_metric_active_flag():
    """Sanity: per-metric `active` flag in the status summary must remain
    per-baseline (sample_count >= minimum_samples). The gate relaxation
    only changes the coordinator-level learning_status — dead metrics
    must still surface as active=False so the gap remains visible.
    """
    AnomalyDetector, LearningStatus = _load_anomaly_detector()
    det = AnomalyDetector(
        _StubHass(), "test",
        ["m1", "m2"],
        minimum_samples=10,
    )
    _seed_baseline(det, "m1", "house", 12)
    # m2 never observed
    summary = det.get_status_summary("house")
    assert summary["metrics"]["m1"]["active"] is True
    assert summary["metrics"]["m2"]["active"] is False
    assert summary["learning_status"] == LearningStatus.ACTIVE


# ===========================================================================
# Behavior tests for _read_source_kw (Fix 1)
# ===========================================================================
# Source-grep proves the right strings are in the file; these tests prove
# the right numbers come out. Mocks the minimum HA surface the helper
# touches: hass.states.get -> _StubState with `state` and `attributes`.


class _StubState:
    def __init__(self, state: str, unit: str = None, last_updated=None):
        self.state = state
        self.attributes = {"unit_of_measurement": unit} if unit is not None else {}
        self.last_updated = last_updated


class _StubStatesRegistry:
    def __init__(self, **entities):
        self._entities = entities

    def get(self, entity_id):
        return self._entities.get(entity_id)


class _StubHassWithStates:
    def __init__(self, states_dict):
        self.states = _StubStatesRegistry(**states_dict)
        self.data = {}


class _StubZone:
    def __init__(self, ac_load_sensor=None, climate_entity=None, kwh_rate_threshold=0.8):
        self.ac_load_sensor = ac_load_sensor
        self.climate_entity = climate_entity
        self.kwh_rate_threshold = kwh_rate_threshold


def _make_kwh_rate_sensor(hass, zone, climate_entity):
    """Construct the sensor with the package import-chain bypassed.

    The sensor class lives in sensor.py which imports heavily from HA. We
    can't just instantiate it — instead we use a minimal subclass that
    plugs in _get_zone() directly (bypassing the manager.coordinators
    lookup), and we re-implement _read_source_kw inline by copy of the
    parse logic. That defeats the purpose. Better: use exec on the source
    fragment and inject our stubs.

    Pragmatic alternative: load sensor.py as a text-extract of the
    _read_source_kw method body and exec it in a controlled namespace.
    """
    import ast
    from pathlib import Path
    src_file = Path(__file__).resolve().parents[2] / \
        "custom_components" / "universal_room_automation" / "sensor.py"
    src = src_file.read_text()
    tree = ast.parse(src)
    method_src = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "HVACACRampKwhRateSensor":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_read_source_kw":
                    method_src = ast.get_source_segment(src, item)
                    break
            # Also grab the class-level sanity-bound constants
            class_consts = []
            for item in node.body:
                if isinstance(item, ast.Assign) and len(item.targets) == 1:
                    tgt = item.targets[0]
                    if isinstance(tgt, ast.Name) and tgt.id in {
                        "_MAX_PLAUSIBLE_KW", "_MIN_PLAUSIBLE_KW",
                    }:
                        class_consts.append(ast.get_source_segment(src, item))
            break
    assert method_src, "_read_source_kw not found in HVACACRampKwhRateSensor"

    # Build a synthetic class with just the constants + method
    class_src = "class _SyntheticReader:\n"
    for c in class_consts:
        class_src += "    " + c + "\n"
    # Indent the method body
    indented_method = "\n".join("    " + line for line in method_src.splitlines())
    class_src += indented_method + "\n"

    ns = {}
    exec(class_src, ns)
    reader_cls = ns["_SyntheticReader"]
    reader = reader_cls()
    reader.hass = hass
    reader._climate_entity = climate_entity
    reader._zone_to_return = zone
    reader._get_zone = lambda: reader._zone_to_return
    return reader


def test_read_source_kw_w_to_kw_conversion():
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    hass = _StubHassWithStates({"sensor.ac_power": _StubState("2119.1", "W")})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw == 2.119


def test_read_source_kw_kw_passthrough():
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    hass = _StubHassWithStates({"sensor.ac_power": _StubState("2.15", "kW")})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw == 2.15


def test_read_source_kw_unknown_state_returns_none():
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    hass = _StubHassWithStates({"sensor.ac_power": _StubState("unknown", "W")})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


def test_read_source_kw_unavailable_returns_none():
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    hass = _StubHassWithStates({"sensor.ac_power": _StubState("unavailable", "W")})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


def test_read_source_kw_non_numeric_returns_none():
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    hass = _StubHassWithStates({"sensor.ac_power": _StubState("off", "W")})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


def test_read_source_kw_missing_unit_returns_none():
    """A template sensor that forgot unit_of_measurement should NOT be
    silently treated as kW. Review-1 MEDIUM finding."""
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    # State with no unit_of_measurement attribute at all
    s = _StubState("2150")
    hass = _StubHassWithStates({"sensor.ac_power": s})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


def test_read_source_kw_unknown_unit_returns_none():
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    hass = _StubHassWithStates({"sensor.ac_power": _StubState("2.15", "mW")})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


def test_read_source_kw_negative_returns_none():
    """Negative kW on an AC compressor draw is impossible. Sensor bug.
    Review-1 MEDIUM finding."""
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    hass = _StubHassWithStates({"sensor.ac_power": _StubState("-150", "W")})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


def test_read_source_kw_implausibly_huge_returns_none():
    """Sanity cap prevents glitches from polluting long-term statistics.
    Review-1 MEDIUM finding (kW/W glitch class)."""
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    # 999999 W = 999.999 kW — well above _MAX_PLAUSIBLE_KW=50
    hass = _StubHassWithStates({"sensor.ac_power": _StubState("999999", "W")})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


def test_read_source_kw_missing_source_entity_returns_none():
    zone = _StubZone(ac_load_sensor=None)
    hass = _StubHassWithStates({})
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


def test_read_source_kw_missing_state_returns_none():
    zone = _StubZone(ac_load_sensor="sensor.ac_power")
    hass = _StubHassWithStates({})  # entity not registered
    reader = _make_kwh_rate_sensor(hass, zone, "climate.x")
    _z, kw = reader._read_source_kw()
    assert kw is None


# ===========================================================================
# Source-grep on the fix site itself (regression guard against accidental
# revert of the comparison operator)
# ===========================================================================


def test_gate_uses_threshold_not_full_equality(diagnostics_src: str):
    """Guard against a future refactor reverting the relaxation: the gate
    must use a `>= threshold` comparison, not `== len(metric_names)`.
    """
    # Locate get_learning_status body
    start = diagnostics_src.find("def get_learning_status(")
    assert start >= 0
    end = diagnostics_src.find("\n    def ", start + 1)
    body = diagnostics_src[start:end if end > 0 else None]
    # Must contain the relaxation idiom
    assert "max(1, len(self.metric_names) // 2)" in body, (
        "get_learning_status no longer uses majority-of-metrics threshold. "
        "Did v4.5.13's relaxation get reverted?"
    )
    # And must NOT be back to the strict equality
    assert "active_metrics == len(self.metric_names)" not in body, (
        "get_learning_status reverted to strict equality — that's the v4.5.12 "
        "bug that left detectors stuck in LEARNING."
    )
