"""Tests for the v5.94.0 device/entity architecture de-fragmentation cycle.

Design:
- The D0 fixture (`docs/planning/AUDIT_device_entity_split_ownership_2026_09_03.csv`)
  is the migration set of record; these tests load it verbatim and diff
  against source. A test that hard-codes the migration set would defeat the
  purpose (see plan reviewer-A hollow-anchor check).
- Behavioral mutation anchors: each anchor test is designed so that reverting
  a specific production edit turns exactly one test RED (documented per-test).
- Registry manipulation uses a lightweight in-memory fake — enough to prove
  the D-NEST parent map + idempotency without needing full HA scaffolding.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Note: _provenance_harness is installed LAZILY inside _import_devices() to
# avoid polluting sys.modules at collection time (would break other test
# modules' skip guards — e.g. test_d3_area_inherit skips on import-failure
# of URA modules and would silently start running when our harness is loaded
# eagerly, causing test-ordering failures).


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PKG_ROOT = REPO_ROOT / "custom_components" / "universal_room_automation"
D0_CSV = REPO_ROOT / "docs" / "planning" / "AUDIT_device_entity_split_ownership_2026_09_03.csv"


# ---------------------------------------------------------------------------
# D0 fixture loader — used across tests.
# ---------------------------------------------------------------------------


def _load_d0_migration_set():
    """Return list of dicts, one per migration-target entity."""
    with D0_CSV.open() as fh:
        return list(csv.DictReader(fh))


def test_d0_csv_exists_and_has_17_entities():
    """D0 fixture present + expected shape (guards fixture drift)."""
    assert D0_CSV.is_file(), f"D0 fixture missing at {D0_CSV}"
    rows = _load_d0_migration_set()
    assert len(rows) == 17, f"D0 fixture size drift: {len(rows)} != 17"
    # Every row must have the columns the tests read
    required = {"entity_id", "unique_id", "device_identifier", "unique_id_stability"}
    for row in rows:
        assert required.issubset(row.keys()), f"D0 row missing cols: {row}"
    # All migration targets are SAFE per plan C7
    unsafe = [r for r in rows if r["unique_id_stability"] != "SAFE"]
    assert not unsafe, f"D0 flagged BLOCKED unique_ids (plan requires SAFE): {unsafe}"


def test_d0_oji_space_unique_id_preserved_verbatim():
    """The literal ' ' (space) in Oji's unique_id MUST not be cleaned up;
    any string change mints a `_2` entity. This test asserts the exact
    byte-level presence of the space in the D0 fixture."""
    rows = _load_d0_migration_set()
    oji_next = [r for r in rows if "oji" in r["unique_id"] and "next_room_accuracy" in r["unique_id"]]
    assert len(oji_next) == 1
    assert oji_next[0]["unique_id"] == (
        "universal_room_automation_person_oji udezue_next_room_accuracy"
    ), "the oji_udezue space in unique_id was normalised — this mints a _2"


# ---------------------------------------------------------------------------
# _devices.py — D2 canonical authors + D3 dispatcher
# ---------------------------------------------------------------------------


def _import_devices():
    # Import the module by file path to avoid triggering the package
    # __init__.py (which pulls in the full HA runtime graph). Cache on the
    # sys.modules key so repeated calls are cheap.
    import importlib.util
    mod_name = "_ura_devices_under_test"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    # Install HA stubs lazily (only when this test actually needs them, so
    # earlier-collected sibling test modules aren't affected by side-effects).
    import _provenance_harness  # noqa: F401  — side-effect
    import homeassistant.helpers.device_registry as _dr_stub  # noqa: PLC0415
    if not hasattr(_dr_stub, "async_get"):
        _dr_stub.async_get = lambda hass: MagicMock()  # type: ignore[attr-defined]
    # Build a stub package for relative imports (`from .const import ...`).
    pkg_name = "custom_components.universal_room_automation"
    if pkg_name not in sys.modules:
        # The harness may not have created this — build a minimal package.
        import types as _types
        pkg = _types.ModuleType(pkg_name)
        pkg.__path__ = [str(PKG_ROOT)]  # type: ignore[attr-defined]
        sys.modules[pkg_name] = pkg
        # Load const.py so `from .const import DOMAIN, VERSION` resolves.
        spec_c = importlib.util.spec_from_file_location(
            f"{pkg_name}.const", PKG_ROOT / "const.py",
        )
        const_mod = importlib.util.module_from_spec(spec_c)
        sys.modules[f"{pkg_name}.const"] = const_mod
        spec_c.loader.exec_module(const_mod)  # type: ignore[union-attr]
    spec = importlib.util.spec_from_file_location(
        f"{pkg_name}._devices", PKG_ROOT / "_devices.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg_name}._devices"] = mod
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_music_following_device_info_canonical():
    d = _import_devices()
    di = d._music_following_device_info()
    assert (d.DEVICE_NAMES["music_following_coordinator"],
            d.DEVICE_MODELS["music_following_coordinator"]) == (
        di["name"], di["model"],
    )
    assert di["identifiers"] == {("universal_room_automation", "music_following_coordinator")}


def test_nm_device_info_canonical():
    d = _import_devices()
    di = d._nm_device_info()
    assert di["identifiers"] == {("universal_room_automation", "notification_manager")}
    assert di["model"] == "Notification Manager"


@pytest.mark.parametrize("coord_id,expected_ident,expected_model", [
    ("energy", "energy_coordinator", "Energy Coordinator"),
    ("hvac", "hvac_coordinator", "HVAC Coordinator"),
    ("optimization", "optimization_coordinator", "Optimization Coordinator"),
    ("coordinator_manager", "coordinator_manager", "Coordinator Manager"),
    ("music_following", "music_following_coordinator", "Music Following Coordinator"),
    ("notification_manager", "notification_manager", "Notification Manager"),
])
def test_coordinator_device_info_dispatcher(coord_id, expected_ident, expected_model):
    """D3 dispatcher: BaseCoordinator.device_info routes here. Reverting the
    base.py edit breaks test_base_coordinator_device_info_matches_helper below.
    """
    d = _import_devices()
    di = d._coordinator_device_info(coord_id)
    assert di["identifiers"] == {("universal_room_automation", expected_ident)}
    assert di["model"] == expected_model, (
        f"D3 model race: {coord_id} returned {di['model']!r}, expected {expected_model!r}"
    )
    # D3 anchor: NO coordinator dispatches to the retired "Domain Coordinator" string
    assert di["model"] != "Domain Coordinator"


# ---------------------------------------------------------------------------
# D3 mutation anchor — base.py routes through the helper (not "Domain Coordinator")
# ---------------------------------------------------------------------------


def test_base_coordinator_device_info_no_domain_coordinator_literal():
    """D3 anchor: `"Domain Coordinator"` string is retired from base.py.
    Reverting base.py's device_info to the old inline DeviceInfo reintroduces
    the literal and this test goes RED.
    """
    base_py = (PKG_ROOT / "domain_coordinators" / "base.py").read_text()
    # Strip line comments so ONLY code-level occurrences count.
    code_lines = [
        line for line in base_py.splitlines() if not line.strip().startswith("#")
    ]
    joined = "\n".join(code_lines)
    assert '"Domain Coordinator"' not in joined, (
        "D3 regression: base.py still emits the generic 'Domain Coordinator' model."
    )


# ---------------------------------------------------------------------------
# D1a mutation anchors — sensor.py branch-move
# ---------------------------------------------------------------------------


_MIGRATED_CLASSES_D1A = [
    "ExteriorPersonTracksActiveSensor",
    "ExteriorVehicleTracksActiveSensor",
    "ExteriorAnimalTracksActiveSensor",
    "ExteriorUnidentifiedPersonsSensor",
    "ExteriorOpenTracksDiagnosticSensor",
    "PerimeterCirclingZeroDispatch24hSensor",
    "MusicFollowingHealthSensor",
]


def _sensor_py_branches():
    """Return (integration_branch_text, cm_branch_text) segments from sensor.py."""
    src = (PKG_ROOT / "sensor.py").read_text()
    # Integration branch: from `census_sensors = [` up to `async_add_entities(census_sensors)`.
    m_int = re.search(
        r"census_sensors\s*=\s*\[(.*?)\]\s*\n\s*async_add_entities\(census_sensors\)",
        src, re.DOTALL,
    )
    assert m_int, "could not locate census_sensors block in sensor.py"
    int_branch = m_int.group(1)
    # CM branch: from `coordinator_sensors = [` up to `async_add_entities(coordinator_sensors)`.
    m_cm = re.search(
        r"coordinator_sensors\s*=\s*\[(.*?)\]\s*(?:\n.*?)?async_add_entities\(coordinator_sensors\)",
        src, re.DOTALL,
    )
    assert m_cm, "could not locate coordinator_sensors block in sensor.py"
    cm_branch = m_cm.group(1)
    return int_branch, cm_branch, src


@pytest.mark.parametrize("class_name", _MIGRATED_CLASSES_D1A)
def test_d1a_migrated_class_absent_from_integration_branch(class_name):
    """D1a mutation anchor: pasting `ExteriorPersonTracksActiveSensor(hass, entry)`
    back into the census_sensors list makes this test RED.
    """
    int_branch, _cm_branch, _src = _sensor_py_branches()
    assert f"{class_name}(hass, entry)" not in int_branch, (
        f"D1a regression: {class_name} still registered under the INTEGRATION "
        f"census_sensors branch (would re-create split ownership)."
    )


@pytest.mark.parametrize("class_name", _MIGRATED_CLASSES_D1A)
def test_d1a_migrated_class_present_in_cm_branch(class_name):
    """D1a mutation anchor: removing a class from the CM branch makes this
    test RED for that class."""
    _int_branch, cm_branch, _src = _sensor_py_branches()
    assert f"{class_name}(hass, entry)" in cm_branch, (
        f"D1a wire-in missing: {class_name} not registered under the CM branch."
    )


def test_stays_on_integration_entities_preserved():
    """STAYS list preserved: ReconcileHealthSensor + IntegrationHouseStateSensor
    remain in the INTEGRATION census_sensors block.
    """
    int_branch, cm_branch, _src = _sensor_py_branches()
    for stay in ("ReconcileHealthSensor(hass, entry)",
                 "IntegrationHouseStateSensor(hass, entry)"):
        assert stay in int_branch, f"STAYS entity moved off INTEGRATION: {stay}"
        assert stay not in cm_branch, f"STAYS entity mistakenly on CM: {stay}"


# ---------------------------------------------------------------------------
# D1b mutation anchors — CM-hosted aggregation coroutines
# ---------------------------------------------------------------------------


def test_d1b_cm_hosted_coroutines_defined():
    """The two D1b split coroutines + helper exist as `async def`/`def` at
    module scope in aggregation.py. Source-level check avoids importing the
    aggregation module (which pulls the full HA runtime).
    """
    src = (PKG_ROOT / "aggregation.py").read_text()
    assert re.search(r"^async def async_setup_cm_hosted_aggregation_sensors\b",
                     src, re.MULTILINE)
    assert re.search(r"^async def async_setup_cm_hosted_aggregation_binary_sensors\b",
                     src, re.MULTILINE)
    assert re.search(r"^def _resolve_integration_entry\b", src, re.MULTILINE)


def test_d1b_removed_from_integration_aggregation():
    """The migrated per-person + house sensors are DELETED from the
    INTEGRATION-side aggregation coroutine (else double-registration).
    """
    src = (PKG_ROOT / "aggregation.py").read_text()
    # Isolate the async_setup_aggregation_sensors body up to the closing async_add_entities.
    m = re.search(
        r"async def async_setup_aggregation_sensors\(.*?async_add_entities\(entities\)",
        src, re.DOTALL,
    )
    assert m, "could not locate async_setup_aggregation_sensors body"
    body = m.group(0)
    for cls in ("PersonNextRoomAccuracySensor(", "PersonRoutineStatusSensor(",
                "HouseNextRoomAccuracySensor(", "HouseRoutineStatusSensor("):
        assert cls not in body, (
            f"D1b regression: {cls} still constructed in "
            f"async_setup_aggregation_sensors (would double-register)."
        )
    # And DELETED from the binary sensor coroutine
    m2 = re.search(
        r"async def async_setup_aggregation_binary_sensors\(.*?async_add_entities\(entities\)",
        src, re.DOTALL,
    )
    assert m2, "could not locate async_setup_aggregation_binary_sensors body"
    body2 = m2.group(0)
    for cls in ("SafetyAlertBinarySensor(", "SecurityAlertBinarySensor("):
        assert cls not in body2, (
            f"D1b regression: {cls} still constructed in "
            f"async_setup_aggregation_binary_sensors."
        )


def test_d1b_cm_setup_invokes_new_coroutines():
    """sensor.py CM branch + binary_sensor.py CM branch invoke the new
    coroutines. Reverting the call site turns this RED.
    """
    sensor_src = (PKG_ROOT / "sensor.py").read_text()
    assert "async_setup_cm_hosted_aggregation_sensors(" in sensor_src, (
        "sensor.py CM branch does not invoke async_setup_cm_hosted_aggregation_sensors"
    )
    binary_src = (PKG_ROOT / "binary_sensor.py").read_text()
    assert "async_setup_cm_hosted_aggregation_binary_sensors(" in binary_src, (
        "binary_sensor.py CM branch does not invoke "
        "async_setup_cm_hosted_aggregation_binary_sensors"
    )


# ---------------------------------------------------------------------------
# D-NEST parent-map + stamper (in-memory fake registry)
# ---------------------------------------------------------------------------


class _FakeDevice:
    def __init__(self, device_id: str, identifiers: set[tuple[str, str]]):
        self.id = device_id
        self.identifiers = identifiers
        self.via_device_id: str | None = None


class _FakeDevReg:
    def __init__(self, devices: list[_FakeDevice]):
        self.devices = {d.id: d for d in devices}
        self.update_calls: list[tuple[str, str]] = []

    def async_get(self, device_id: str) -> _FakeDevice | None:
        return self.devices.get(device_id)

    def async_update_device(self, device_id: str, *, via_device_id: str) -> None:
        self.update_calls.append((device_id, via_device_id))
        self.devices[device_id].via_device_id = via_device_id


@pytest.mark.asyncio
async def test_d_nest_stamper_covers_all_static_identities(monkeypatch):
    """D-NEST INV-4: every non-root URA device's via_device_id resolves to
    the correct parent.
    """
    d = _import_devices()
    # Build a fake registry with every static identity + one zone + one room.
    devices = [
        _FakeDevice("dev_int", {("universal_room_automation", "integration")}),
        _FakeDevice("dev_cm", {("universal_room_automation", "coordinator_manager")}),
        _FakeDevice("dev_zm", {("universal_room_automation", "zone_manager")}),
        _FakeDevice("dev_safety", {("universal_room_automation", "safety_coordinator")}),
        _FakeDevice("dev_security", {("universal_room_automation", "security_coordinator")}),
        _FakeDevice("dev_presence", {("universal_room_automation", "presence_coordinator")}),
        _FakeDevice("dev_energy", {("universal_room_automation", "energy_coordinator")}),
        _FakeDevice("dev_hvac", {("universal_room_automation", "hvac_coordinator")}),
        _FakeDevice("dev_opt", {("universal_room_automation", "optimization_coordinator")}),
        _FakeDevice("dev_mf", {("universal_room_automation", "music_following_coordinator")}),
        _FakeDevice("dev_nm", {("universal_room_automation", "notification_manager")}),
        _FakeDevice("dev_zone1", {("universal_room_automation", "zone_1")}),
        _FakeDevice("dev_room1", {("universal_room_automation", "some_entry_id_abc")}),
    ]
    fake_reg = _FakeDevReg(devices)

    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)

    hass = MagicMock()
    updates = await d.async_stamp_via_device_tree(hass)

    # Expected: every non-integration device gets a via_device_id
    expected_parents = {
        "dev_cm": "dev_int",
        "dev_zm": "dev_int",
        "dev_safety": "dev_cm",
        "dev_security": "dev_cm",
        "dev_presence": "dev_cm",
        "dev_energy": "dev_cm",
        "dev_hvac": "dev_cm",
        "dev_opt": "dev_cm",
        "dev_mf": "dev_cm",
        "dev_nm": "dev_cm",
        "dev_zone1": "dev_zm",
        "dev_room1": "dev_int",
    }
    for dev_id, parent_id in expected_parents.items():
        assert fake_reg.devices[dev_id].via_device_id == parent_id, (
            f"D-NEST parent map wrong: {dev_id} -> {fake_reg.devices[dev_id].via_device_id}, expected {parent_id}"
        )
    # Root skipped
    assert fake_reg.devices["dev_int"].via_device_id is None
    assert updates == len(expected_parents)


@pytest.mark.asyncio
async def test_d_nest_stamper_idempotent(monkeypatch):
    """Second call is a no-op (INV-4 idempotency + INV-6 no reload)."""
    d = _import_devices()
    devices = [
        _FakeDevice("dev_int", {("universal_room_automation", "integration")}),
        _FakeDevice("dev_cm", {("universal_room_automation", "coordinator_manager")}),
    ]
    fake_reg = _FakeDevReg(devices)
    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)

    hass = MagicMock()
    first = await d.async_stamp_via_device_tree(hass)
    second = await d.async_stamp_via_device_tree(hass)
    assert first == 1
    assert second == 0, "D-NEST stamp is not idempotent (second run wrote again)"


# ---------------------------------------------------------------------------
# D6 — reload safety: _devices.py never calls async_update_entry
# ---------------------------------------------------------------------------


def test_devices_module_never_reloads_entry():
    """INV-6: D-NEST + helpers use device-registry writes only, never
    entry-options writes (which would trigger _async_update_listener +
    watchdog restart hazard)."""
    src = (PKG_ROOT / "_devices.py").read_text()
    assert "async_update_entry" not in src, (
        "INV-6 regression: _devices.py touches config-entry options — this "
        "triggers _async_update_listener and risks the parent-entry-reload "
        "watchdog hazard."
    )


# ---------------------------------------------------------------------------
# Dead-device removal wire-in
# ---------------------------------------------------------------------------


def test_dead_music_following_device_removal_guarded():
    """The removal in CM setup is guarded by zero-entity check (safety) and
    targets the bare `music_following` identifier — NOT `music_following_coordinator`.
    """
    init_src = (PKG_ROOT / "__init__.py").read_text()
    # Removal targets the DEAD (bare) identifier
    assert '(DOMAIN, "music_following")' in init_src, (
        "dead-device removal targets wrong identifier or missing"
    )
    # Guard present
    assert "async_remove_device" in init_src
    # Skip-on-remaining branch present (safety)
    assert "dead-device removal SKIPPED" in init_src or "SKIPPED" in init_src, (
        "no safety guard on dead-device removal — could orphan entities"
    )


# ---------------------------------------------------------------------------
# INV-2 scoped SSOT (D2 scope): music_following + notification_manager
# ---------------------------------------------------------------------------


def _grep_literal_authors(identifier: str) -> list[str]:
    """Return file:line for every `DeviceInfo(identifiers={(DOMAIN, "<id>")}, ...)`
    LITERAL constructor in the package."""
    pattern = re.compile(
        r'DeviceInfo\s*\(\s*[^)]*identifiers\s*=\s*\{\s*\(\s*DOMAIN\s*,\s*'
        + f'"{re.escape(identifier)}"'
        + r'\s*\)\s*\}',
        re.DOTALL,
    )
    hits = []
    for py in PKG_ROOT.rglob("*.py"):
        text = py.read_text()
        for m in pattern.finditer(text):
            # skip _devices.py — that IS the canonical author
            if py.name == "_devices.py":
                continue
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{py.relative_to(PKG_ROOT)}:{line}")
    return hits


def test_d2_music_following_single_author_in_scoped_sites():
    """The plan's D2 scoped sites for MF (`switch.py:5708` MFPersonFollowSwitch,
    `sensor.py:7352` helper body) no longer contain literal `DeviceInfo(
    identifiers={(DOMAIN, "music_following_coordinator")}, ...)` constructors.

    Other unscoped inline sites (parked to DEVICE-INFO-HELPER-CONSOLIDATION-1)
    are excluded — this test enforces the plan's SCOPED INV-2, not the
    aspirational one.
    """
    hits = _grep_literal_authors("music_following_coordinator")
    # sensor.py:7352 helper is now a thin re-export (no DeviceInfo literal).
    # switch.py:5708 MFPersonFollowSwitch now calls the helper.
    # switch.py CoordinatorEnabledSwitch at ~:633 uses PARAMETERISED
    # identifiers (variable, not literal) — the literal regex does not match.
    # Expected: ZERO literal authors outside _devices.py in the scoped sites.
    scoped_regressions = [h for h in hits if h.startswith("switch.py") or h.startswith("sensor.py")]
    assert not scoped_regressions, (
        "D2 regression: literal MF DeviceInfo author found in scoped file: "
        f"{scoped_regressions}"
    )


def test_d2_notification_manager_canonical_sites_routed():
    """The three D2-scoped NM sites (number.py mixin body, sensor.py:7791
    helper, notification_manager.py:667) all route through the canonical
    helper (no local DeviceInfo literal for the NM identifier).
    """
    # Enforce: number.py, sensor.py (helper), notification_manager.py — no LITERAL
    # DeviceInfo authors for notification_manager remain in these files.
    hits = _grep_literal_authors("notification_manager")
    scoped = {"number.py", "sensor.py",
              "domain_coordinators/notification_manager.py"}
    scoped_regressions = [h for h in hits if any(h.startswith(s) for s in scoped)]
    assert not scoped_regressions, (
        "D2 regression: literal NM DeviceInfo author found in scoped file: "
        f"{scoped_regressions}"
    )
