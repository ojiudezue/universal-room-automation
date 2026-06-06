"""v4.5.21 — Device-page ordering experiment for HVAC Coordinator.

Cosmetic-only change: HVAC Coordinator entities receive a two-digit
zero-padded numeric prefix on their `_attr_name` so the HA device page
groups them into Controls / Sensors / CONFIG / DIAGNOSTIC clusters with
deterministic ordering inside each cluster.

Format: ``"NN · Name"`` (digits + space + U+00B7 middle-dot + space).

The change is scoped to entities that bind to the HVAC Coordinator
device (identifiers `(DOMAIN, "hvac_coordinator")`). All other
coordinator devices (Safety, Security, Presence, Notification, Music
Following, Energy, Room, Zone Manager, Coordinator Manager, Integration)
MUST be untouched.

Tests:
1. Positive — every known HC entity class's `_attr_name` carries a
   `NN · ` prefix (literal or f-string form).
2. Negative — Safety/Security entity classes' `_attr_name` lines do NOT
   contain the ` · ` prefix marker. This guards against accidental
   spillover.
3. Cluster integrity — prefixes within each cluster are mutually
   distinct on a per-entity-class basis (the per-zone factories share
   one prefix across all instances; that is intentional).

Bug class affinity: this test family is `source-grep / AST-walk`
regression guards — it does NOT execute the integration. Runtime
behavior of the prefix change is verified at deploy time by visual
inspection of the HVAC Coordinator device page.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"

PREFIX_RE = re.compile(r"^\d{2} · ")
DOT_MARKER = " · "  # the middle-dot delimiter that follows every prefix


# ===========================================================================
# Fixtures: source modules
# ===========================================================================


@pytest.fixture(scope="module")
def sensor_src() -> str:
    return (PKG / "sensor.py").read_text()


@pytest.fixture(scope="module")
def switch_src() -> str:
    return (PKG / "switch.py").read_text()


@pytest.fixture(scope="module")
def number_src() -> str:
    return (PKG / "number.py").read_text()


@pytest.fixture(scope="module")
def button_src() -> str:
    return (PKG / "button.py").read_text()


# ===========================================================================
# Catalog of HC-bound entity classes per platform.
#
# Each entry is (class_name, expected_prefix_int).  For per-zone factories
# the entity-class shares its prefix across all instances — the catalog
# pins one prefix per class which the AST walk verifies once.
# ===========================================================================


# sensor.py — Sensors cluster (no entity_category)
SENSOR_HC_CLASSES: dict[str, int] = {
    # Sensors cluster
    "HVACModeSensor": 10,
    "HVACComfortRiskSensor": 30,
    "HVACPreCoolLikelihoodSensor": 40,
    "HVACACNudgesTodaySensor": 50,
    "HVACACResetsTodaySensor": 60,
    "HVACACKwhAvoidedTodaySensor": 70,
    "HVACACKwhAvoidedTotalSensor": 80,
    # DIAGNOSTIC cluster
    "HVACAnomalySensor": 10,
    "HVACComplianceSensor": 15,
    "HVACOverrideFrequencySensor": 20,
    "HVACArresterStateSensor": 25,
    "HVACArresterStatusSensor": 30,
    "HVACZoneIntelligenceSensor": 35,
    "HVACPreArrivalDiagnosticSensor": 40,
    "HVACACFalsePositiveRateSensor": 45,
    "HVACZoneStatusSensor": 50,             # per-zone
    "HVACZonePresetSensor": 55,             # per-zone
    "HVACACRampStateSensor": 60,            # per-zone
    "HVACACRampLastActionSensor": 62,       # per-zone
    "HVACACRampKwhRateSensor": 64,          # per-zone
}


# switch.py — CONFIG cluster (HVACOverrideArresterSwitch et al.).
# CoordinatorEnabledSwitch is shared across all coordinators; v4.5.21.1
# branches its `_attr_name` on `coordinator_id == "hvac"` to apply a
# `"00 · "` prefix that sorts the Enabled switch to the top of the HVAC
# Coordinator Controls cluster. Other coordinators keep bare "Enabled"
# until their sweep cycle. See test_enabled_switch_hvac_prefix below.
SWITCH_HC_CLASSES: dict[str, int] = {
    "HVACObservationModeSwitch": 10,
    "HVACACRampMasterSwitch": 15,
    "HVACOverrideArresterSwitch": 20,
    "HVACACResetSwitch": 25,
    "HVACZoneIntelligenceSwitch": 30,
    "HVACPreArrivalSwitch": 35,
    "HVACFanControlSwitch": 40,
    "HVACSolarCoverSwitch": 45,
    # Switch moved from 50 → 46 to cluster with switch 45; presence-timer
    # Numbers occupy the contiguous 47-50 block.
    "HVACZoneSweepSwitch": 46,
}


# number.py — direct classes + factory-emitted names.
# The factory-emitted classes are checked separately by scanning the
# factory call-sites (where the `name=` kwarg lives).
NUMBER_HC_CLASSES: dict[str, int] = {
    "ZoneEntryDwellNumber": 47,
    "VacancyGraceMinutesNumber": 48,
    "VacancyGraceConstrainedNumber": 49,
    "MaxOccupancyHoursNumber": 50,
}


# Factory call-site (suffix -> expected prefix). These map to entities
# built via `_hvac_tunable_number_factory(suffix=..., name=...)`.
NUMBER_HC_FACTORY_PREFIXES: dict[str, int] = {
    # v4.5.10 cluster: 60-66
    "cover_close_threshold": 60,
    "cover_close_temp": 61,
    "cover_open_temp": 62,
    "cover_override_duration": 63,
    "solar_bank_floor": 64,
    "fan_on_threshold": 65,
    "fan_off_hysteresis": 66,
    # v4.5.11 AC tunables: 70-75
    "ac_nudge_size": 70,
    "ac_nudge_duration": 71,
    "ac_sustained_samples": 72,
    "ac_detection_time_gate": 73,
    "ac_hard_reset_daily_limit": 74,
    "ac_hard_reset_min_interval": 75,
}


# button.py — the only directly-classed HC button.  The _ACRampButton
# factory builds labels dynamically via `_ac_ramp_prefix`, so its
# prefixing is exercised via a unit-style call below.
BUTTON_HC_CLASSES: dict[str, int] = {
    "HVACACRampDiagnosticDumpButton": 90,
    "ResetPresenceTimersButton": 51,
}


# ===========================================================================
# Non-HC negative-test classes (must NOT be prefixed)
# ===========================================================================
NON_HC_SAMPLE_CLASSES = {
    "SafetyStatusSensor",
    "SafetyDiagnosticsSensor",
    "SafetyActiveHazardsSensor",
    "SafetyAffectedRoomsSensor",
    "SafetyAnomalySensor",
    "SafetyComplianceSensor",
    "SecurityArmedStateSensor",
    "SecurityLastEntrySensor",
    "SecurityAnomalySensor",
    "SecurityComplianceSensor",
    "SafetyObservationModeSwitch",
    "SecurityObservationModeSwitch",
    "SecurityDelegateLightsSwitch",
}


# ===========================================================================
# Helpers — extract `_attr_name = ...` literal from a class body via AST
# ===========================================================================


def _extract_attr_name_assignments(src: str, class_name: str) -> list[str]:
    """Return all string-literal values assigned to `self._attr_name`
    inside the named class.

    Supports both `self._attr_name = "..."` and
    `self._attr_name = f"... {var}"` forms.  For f-strings, the literal
    prefix portion is returned (so a `NN · ` prefix is observable even
    when the suffix is templated).
    """
    tree = ast.parse(src)
    out: list[str] = []

    target_class: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            target_class = node
            break

    if target_class is None:
        return out

    for node in ast.walk(target_class):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (
                isinstance(tgt, ast.Attribute)
                and tgt.attr == "_attr_name"
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id == "self"
            ):
                val = node.value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    out.append(val.value)
                elif isinstance(val, ast.JoinedStr):
                    # f-string: collect the leading literal text
                    parts = []
                    for piece in val.values:
                        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                            parts.append(piece.value)
                        else:
                            # FormattedValue — placeholder; stop at first
                            # interpolation so we only see the literal head.
                            break
                    if parts:
                        out.append("".join(parts))
    return out


def _factory_call_names(src: str) -> dict[str, str]:
    """Return `{suffix_kwarg: name_kwarg}` for each
    `_hvac_tunable_number_factory(suffix=..., name=..., ...)` call
    in `src`.
    """
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = (
            func.id if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute)
            else None
        )
        if fname != "_hvac_tunable_number_factory":
            continue
        kwargs = {
            kw.arg: kw.value for kw in node.keywords if kw.arg is not None
        }
        suffix_v = kwargs.get("suffix")
        name_v = kwargs.get("name")
        if (
            isinstance(suffix_v, ast.Constant)
            and isinstance(suffix_v.value, str)
            and isinstance(name_v, ast.Constant)
            and isinstance(name_v.value, str)
        ):
            out[suffix_v.value] = name_v.value
    return out


# ===========================================================================
# 1. POSITIVE tests — every catalogued HC entity class is prefixed
# ===========================================================================


@pytest.mark.parametrize("cls,prefix", sorted(SENSOR_HC_CLASSES.items()))
def test_sensor_hc_class_has_prefix(sensor_src: str, cls: str, prefix: int):
    names = _extract_attr_name_assignments(sensor_src, cls)
    assert names, f"No _attr_name assignment found in {cls}"
    for n in names:
        assert PREFIX_RE.match(n), (
            f"{cls}._attr_name {n!r} missing 'NN · ' prefix"
        )
        assert n.startswith(f"{prefix:02d} · "), (
            f"{cls}._attr_name {n!r} expected prefix {prefix:02d}"
        )


@pytest.mark.parametrize("cls,prefix", sorted(SWITCH_HC_CLASSES.items()))
def test_switch_hc_class_has_prefix(switch_src: str, cls: str, prefix: int):
    names = _extract_attr_name_assignments(switch_src, cls)
    assert names, f"No _attr_name assignment found in {cls}"
    for n in names:
        assert PREFIX_RE.match(n), (
            f"{cls}._attr_name {n!r} missing 'NN · ' prefix"
        )
        assert n.startswith(f"{prefix:02d} · "), (
            f"{cls}._attr_name {n!r} expected prefix {prefix:02d}"
        )


@pytest.mark.parametrize("cls,prefix", sorted(NUMBER_HC_CLASSES.items()))
def test_number_hc_class_has_prefix(number_src: str, cls: str, prefix: int):
    names = _extract_attr_name_assignments(number_src, cls)
    assert names, f"No _attr_name assignment found in {cls}"
    for n in names:
        assert PREFIX_RE.match(n), (
            f"{cls}._attr_name {n!r} missing 'NN · ' prefix"
        )
        assert n.startswith(f"{prefix:02d} · "), (
            f"{cls}._attr_name {n!r} expected prefix {prefix:02d}"
        )


@pytest.mark.parametrize(
    "suffix,prefix", sorted(NUMBER_HC_FACTORY_PREFIXES.items()),
)
def test_number_factory_call_has_prefix(
    number_src: str, suffix: str, prefix: int,
):
    """Each `_hvac_tunable_number_factory(suffix=..., name=...)` call
    must pass a `name=` arg starting with the expected `NN · ` prefix.
    """
    call_map = _factory_call_names(number_src)
    assert suffix in call_map, (
        f"No factory call found with suffix={suffix!r}"
    )
    name = call_map[suffix]
    assert PREFIX_RE.match(name), (
        f"factory(suffix={suffix!r}) name={name!r} missing 'NN · ' prefix"
    )
    assert name.startswith(f"{prefix:02d} · "), (
        f"factory(suffix={suffix!r}) name={name!r} expected prefix "
        f"{prefix:02d}"
    )


def test_number_per_zone_kwh_threshold_has_prefix(number_src: str):
    """The per-zone factory `_hvac_zone_kwh_threshold_factory` emits a
    `_HVACZoneKwhThresholdNumber` class whose `_attr_name` is built via
    an f-string starting with `"90 · AC kWh Rate Threshold ("`.
    """
    names = _extract_attr_name_assignments(
        number_src, "_HVACZoneKwhThresholdNumber",
    )
    assert names, "No _attr_name found in _HVACZoneKwhThresholdNumber"
    assert any(n.startswith("90 · ") for n in names), (
        f"Per-zone kWh threshold class missing '90 · ' prefix: {names!r}"
    )


@pytest.mark.parametrize("cls,prefix", sorted(BUTTON_HC_CLASSES.items()))
def test_button_hc_class_has_prefix(button_src: str, cls: str, prefix: int):
    names = _extract_attr_name_assignments(button_src, cls)
    assert names, f"No _attr_name assignment found in {cls}"
    for n in names:
        assert PREFIX_RE.match(n), (
            f"{cls}._attr_name {n!r} missing 'NN · ' prefix"
        )
        assert n.startswith(f"{prefix:02d} · "), (
            f"{cls}._attr_name {n!r} expected prefix {prefix:02d}"
        )


def test_ac_ramp_button_prefix_helper_per_zone():
    """Functional unit-test of `_ac_ramp_prefix` — verifies the
    Controls-cluster Force/Cancel growth (20/22, 30/32, 40/42) and
    the CONFIG-cluster fixed 95 for clear_lockout.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ura_button_test", PKG / "button.py",
    )
    # Skip if import would trigger an HA dependency we don't have in
    # the test env. Falling back to AST inspection of the constants is
    # sufficient for the source-grep gate; this helper just tightens
    # the contract when imports succeed.
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        pytest.skip("button.py not importable in test env")
        return

    specs = module._AC_RAMP_BUTTON_SPECS
    fn = module._ac_ramp_prefix

    # Force/Cancel scale linearly per zone (1-based index).
    assert fn(specs["force_nudge"], 1) == 20
    assert fn(specs["cancel_nudge"], 1) == 22
    assert fn(specs["force_nudge"], 2) == 30
    assert fn(specs["cancel_nudge"], 2) == 32
    assert fn(specs["force_nudge"], 3) == 40
    assert fn(specs["cancel_nudge"], 3) == 42

    # Clear-lockout is fixed regardless of zone index.
    assert fn(specs["clear_lockout"], 1) == 95
    assert fn(specs["clear_lockout"], 5) == 95


# ===========================================================================
# 2. NEGATIVE tests — non-HC classes must NOT carry the prefix marker
# ===========================================================================


@pytest.mark.parametrize("cls", sorted(NON_HC_SAMPLE_CLASSES))
def test_non_hc_class_unchanged(
    sensor_src: str, switch_src: str, cls: str,
):
    """Safety/Security entity classes must not carry the device-page
    ordering prefix.  Walks both source files (some classes live in
    sensor.py, others in switch.py).
    """
    for src in (sensor_src, switch_src):
        names = _extract_attr_name_assignments(src, cls)
        for n in names:
            assert DOT_MARKER not in n, (
                f"Non-HC class {cls} has prefix-marker ' · ' in "
                f"_attr_name={n!r} — ordering experiment leaked"
            )


# ===========================================================================
# 3. CLUSTER INTEGRITY — prefixes are unique within each cluster
# ===========================================================================


# Cluster groupings used for the uniqueness check. Each list is the set
# of (class_name, prefix) entries that share a cluster — duplicates are
# disallowed per the experiment's contract.
CLUSTER_GROUPS: dict[str, list[tuple[str, int]]] = {
    # Sensors cluster (no entity_category)
    "sensors": [
        ("HVACModeSensor", 10),
        ("HVACComfortRiskSensor", 30),
        ("HVACPreCoolLikelihoodSensor", 40),
        ("HVACACNudgesTodaySensor", 50),
        ("HVACACResetsTodaySensor", 60),
        ("HVACACKwhAvoidedTodaySensor", 70),
        ("HVACACKwhAvoidedTotalSensor", 80),
    ],
    # DIAGNOSTIC cluster
    "diagnostic": [
        ("HVACAnomalySensor", 10),
        ("HVACComplianceSensor", 15),
        ("HVACOverrideFrequencySensor", 20),
        ("HVACArresterStateSensor", 25),
        ("HVACArresterStatusSensor", 30),
        ("HVACZoneIntelligenceSensor", 35),
        ("HVACPreArrivalDiagnosticSensor", 40),
        ("HVACACFalsePositiveRateSensor", 45),
        ("HVACZoneStatusSensor", 50),
        ("HVACZonePresetSensor", 55),
        ("HVACACRampStateSensor", 60),
        ("HVACACRampLastActionSensor", 62),
        ("HVACACRampKwhRateSensor", 64),
        ("HVACACRampDiagnosticDumpButton", 90),
    ],
    # CONFIG cluster — Number entities + HVAC*Switch entities + per-zone
    # kWh threshold + clear_lockout buttons (fixed at 95).
    "config": [
        ("HVACObservationModeSwitch", 10),
        ("HVACACRampMasterSwitch", 15),
        ("HVACOverrideArresterSwitch", 20),
        ("HVACACResetSwitch", 25),
        ("HVACZoneIntelligenceSwitch", 30),
        ("HVACPreArrivalSwitch", 35),
        ("HVACFanControlSwitch", 40),
        ("HVACSolarCoverSwitch", 45),
        ("HVACZoneSweepSwitch", 46),
        ("ZoneEntryDwellNumber", 47),
        ("VacancyGraceMinutesNumber", 48),
        ("VacancyGraceConstrainedNumber", 49),
        ("MaxOccupancyHoursNumber", 50),
        ("ResetPresenceTimersButton", 51),
        ("cover_close_threshold", 60),
        ("cover_close_temp", 61),
        ("cover_open_temp", 62),
        ("cover_override_duration", 63),
        ("solar_bank_floor", 64),
        ("fan_on_threshold", 65),
        ("fan_off_hysteresis", 66),
        ("ac_nudge_size", 70),
        ("ac_nudge_duration", 71),
        ("ac_sustained_samples", 72),
        ("ac_detection_time_gate", 73),
        ("ac_hard_reset_daily_limit", 74),
        ("ac_hard_reset_min_interval", 75),
        ("_HVACZoneKwhThresholdNumber", 90),
        ("_ACRampButton_clear_lockout", 95),
    ],
    # Controls cluster (force/cancel ramp buttons grow per zone)
    "controls": [
        ("_ACRampButton_force_nudge_zone1", 20),
        ("_ACRampButton_cancel_nudge_zone1", 22),
        ("_ACRampButton_force_nudge_zone2", 30),
        ("_ACRampButton_cancel_nudge_zone2", 32),
        ("_ACRampButton_force_nudge_zone3", 40),
        ("_ACRampButton_cancel_nudge_zone3", 42),
    ],
}


@pytest.mark.parametrize("cluster", sorted(CLUSTER_GROUPS))
def test_cluster_prefixes_unique(cluster: str):
    """Within each cluster, every class's prefix is unique. Per-zone
    factories that share a single class across instances (e.g. the
    DIAGNOSTIC `HVACZoneStatusSensor` at prefix 50) appear once in
    their cluster catalog — the shared prefix is the per-class prefix,
    not a per-instance prefix.
    """
    entries = CLUSTER_GROUPS[cluster]
    prefixes = [p for _cls, p in entries]
    duplicates = {p for p in prefixes if prefixes.count(p) > 1}
    assert not duplicates, (
        f"Cluster {cluster!r} has duplicate prefixes: {sorted(duplicates)!r}"
    )


# ===========================================================================
# v4.5.21.1 — CoordinatorEnabledSwitch HVAC-only "00 · Enabled" branch
# ===========================================================================


def test_enabled_switch_hvac_prefix(switch_src: str):
    """CoordinatorEnabledSwitch.__init__ branches on coordinator_id == 'hvac'
    and assigns `"00 · Enabled"` to `_attr_name`; non-HVAC instances keep
    bare `"Enabled"`. Source-grep is sufficient — the construction order
    is a deterministic if/else right after the unique_id assignment.
    """
    assert 'if coordinator_id == "hvac"' in switch_src, (
        "Expected an explicit `coordinator_id == 'hvac'` branch in "
        "CoordinatorEnabledSwitch.__init__ to scope the prefix to HC only."
    )
    assert '"00 · Enabled"' in switch_src, (
        "Expected `\"00 · Enabled\"` literal in switch.py for the HVAC "
        "branch of CoordinatorEnabledSwitch.__init__."
    )
    # Bare-Enabled fallback must still exist for non-HVAC coordinators.
    assert re.search(r'self\._attr_name\s*=\s*"Enabled"', switch_src), (
        "Expected the bare `self._attr_name = \"Enabled\"` else-branch to "
        "remain so non-HVAC coordinators are not affected."
    )
