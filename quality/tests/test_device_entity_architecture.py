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
    """MED-A1 (2026-09-03): assert the PRODUCTION DERIVATION at
    sensor.py:14113 preserves the space. The pre-fix version of this test
    only asserted the CSV\'s own text — which is hollow (mutating the
    production formula leaves it green).

    The formula must be `f"{DOMAIN}_person_{person_id.lower()}_next_room_accuracy"`
    with NO `.replace(" ", "_")` (or similar normalisation). If a well-meaning
    cleanup rewrites it to `person_id.lower().replace(" ", "_")`, this test
    goes RED — matching the live-registry acceptance gate (any string change
    mints a _2 for oji-udezue).
    """
    sensor_src = (PKG_ROOT / "sensor.py").read_text()
    # The PersonNextRoomAccuracySensor.__init__ formula literal must be present.
    assert 'f"{DOMAIN}_person_{person_id.lower()}_next_room_accuracy"' in sensor_src, (
        "MED-A1: PersonNextRoomAccuracySensor unique_id derivation at "
        "sensor.py:~14113 has drifted from the exact literal that produces "
        "the space in the live oji_udezue unique_id."
    )
    # No cleanup .replace(...) applied to person_id in that formula\'s vicinity.
    # Anchor around the formula and forbid a normalising .replace on person_id
    # within 200 chars.
    idx = sensor_src.index(
        'f"{DOMAIN}_person_{person_id.lower()}_next_room_accuracy"'
    )
    context = sensor_src[max(0, idx - 200):idx + 200]
    assert "person_id.lower().replace(" not in context, (
        "MED-A1: person_id is normalised in the accuracy unique_id derivation "
        "— this mints a _2 for the oji-udezue live entity."
    )
    # Cross-check the CSV still shows the space (fixture integrity).
    rows = _load_d0_migration_set()
    oji = [r for r in rows if "oji" in r["unique_id"] and "next_room_accuracy" in r["unique_id"]]
    assert len(oji) == 1 and " " in oji[0]["unique_id"]


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
    """D3 dispatcher-correctness unit test: `_coordinator_device_info()`
    returns the right DeviceInfo per coordinator id.

    FIX-11 (2026-09-03, Review C M-2): NOTE this is NOT a race-fix proof.
    `BaseCoordinator` (domain_coordinators/base.py:154) is `class
    BaseCoordinator(ABC)`, NOT an HA `Entity`, so HA never reads the
    `device_info` property on base.py:200 — the "model first-writer-wins
    race" D3 originally claimed to fix was never reachable through
    base.py. The `_coordinator_device_info` routing in base.py is kept
    as harmless future-proofing IF BaseCoordinator ever becomes an
    Entity, but these tests only prove the dispatcher, not a race
    resolution.
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
    # CRITICAL-B1 fix-up (2026-09-03): the aggregation.py-defined SafetyAlert /
    # SecurityAlertBinarySensor pair is a DIFFERENT class from the
    # binary_sensor.py-defined coordinator-device pair (aggregation.py=Whole-House
    # unique_ids `ura_safety_alert`/`ura_security_alert`; binary_sensor.py=
    # coordinator-device `ura_safety_coordinator_safety_alert`/
    # `ura_security_coordinator_security_alert`). Only the coordinator-device
    # pair is D1b-migrated; the Whole-House pair STAYS on INTEGRATION. Assert
    # the Whole-House pair is PRESENT (safety guard against re-deletion).
    m2 = re.search(
        r"async def async_setup_aggregation_binary_sensors\(.*?async_add_entities\(entities\)",
        src, re.DOTALL,
    )
    assert m2, "could not locate async_setup_aggregation_binary_sensors body"
    body2 = m2.group(0)
    for cls in ("SafetyAlertBinarySensor(hass, entry)",
                "SecurityAlertBinarySensor(hass, entry)"):
        assert cls in body2, (
            f"CRITICAL-B1 restore: {cls} (Whole-House pair) accidentally "
            f"removed from async_setup_aggregation_binary_sensors."
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
    """FIX-4 (2026-09-03, Review D live-registry): the dead identifier is
    `(DOMAIN, "coordinator_music_following")` (two records, 0 entities
    each) — NOT bare `music_following` (that was a silent-no-op miss in
    the initial build). Also: `async_get_device` returns only one match,
    so the D1 block must iterate `dev_reg2.devices.values()` to catch
    both records. Bind to the SPECIFIC removal block via its comment
    anchor; sequence required:
      1) `(DOMAIN, "coordinator_music_following")` identifier lookup
      2) iteration over the device registry (not `async_get_device`)
      3) `async_entries_for_device(...)` zero-entity guard
      4) `async_remove_device(_device.id)` call
      5) skip-on-remaining safety branch present
    """
    init_src = (PKG_ROOT / "__init__.py").read_text()
    anchor = init_src.find("guarded removal of dead")
    if anchor < 0:
        anchor = init_src.find("guarded removal of the dead")
    assert anchor >= 0, "D1 dead-device removal block missing"
    block = init_src[anchor:anchor + 2500]
    assert '(DOMAIN, "coordinator_music_following")' in block, (
        "FIX-4: D1 dead-device removal targets wrong identifier — must be "
        "(DOMAIN, 'coordinator_music_following') per live-registry ground truth"
    )
    assert "dev_reg2.devices.values()" in block, (
        "FIX-4: D1 dead-device removal must iterate dev_reg2.devices.values() "
        "to catch BOTH dead records (async_get_device returns only one)"
    )
    assert "async_entries_for_device" in block, (
        "FIX-4: D1 dead-device removal missing zero-entity guard "
        "(async_entries_for_device call)"
    )
    assert "async_remove_device(_device.id)" in block, (
        "FIX-4: D1 dead-device removal call absent from D1 block "
        "(unrelated async_remove_device sites elsewhere don't count)"
    )
    assert "SKIPPED" in block, (
        "FIX-4: D1 dead-device removal missing skip-on-remaining safety branch"
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


# ---------------------------------------------------------------------------
# HIGH-A2 (2026-09-03): exactly-once guards + wire-in construction anchors
# for the D1b-migrated sensors + binaries. Double-registration of any of
# these is the _2-mint mechanism = the D1 acceptance gate. Each of these
# tests is designed to go RED under a specific mutation (documented per test)
# so a subsequent name-diff drill can prove the anchor is load-bearing.
# ---------------------------------------------------------------------------


import re as _re


def _read(rel: str) -> str:
    return (PKG_ROOT / rel).read_text()


_D1B_MIGRATED_SENSOR_CLASSES = [
    "PersonNextRoomAccuracySensor",
    "PersonRoutineStatusSensor",
    "HouseNextRoomAccuracySensor",
    "HouseRoutineStatusSensor",
]


@pytest.mark.parametrize("cls", _D1B_MIGRATED_SENSOR_CLASSES)
def test_d1b_sensor_constructed_exactly_once_across_package(cls):
    """FIX-8 (2026-09-03, Review C-CRIT-3): each D1b-migrated sensor class
    must be CONSTRUCTED exactly once across the ENTIRE URA package (not
    just aggregation.py). A duplicate constructor call — in aggregation.py
    OR sensor.py OR any other module — is the _2-mint mechanism (D1
    acceptance gate) and would double-register the same unique_id under a
    different config entry.

    Mutation drill: add a second `PersonNextRoomAccuracySensor(hass, entry, person_id)`
    line anywhere under `custom_components/universal_room_automation/` ->
    this test RED for that class.
    """
    hits: list[str] = []
    for py in PKG_ROOT.rglob("*.py"):
        text = py.read_text()
        # Exclude class definition itself (`class Foo(`) — only match constructor calls.
        for m in _re.finditer(rf"\b{cls}\(", text):
            # Skip class definitions.
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.start())
            line = text[line_start:line_end if line_end != -1 else len(text)]
            if line.lstrip().startswith("class "):
                continue
            hits.append(f"{py.relative_to(PKG_ROOT)}:{text.count(chr(10), 0, m.start()) + 1}")
    assert len(hits) == 1, (
        f"FIX-8 exactly-once guard: {cls} constructed {len(hits)} times "
        f"across package (expected 1). Sites: {hits}. A second "
        f"construction double-registers -> _2 mint."
    )


def test_d1b_binaries_constructed_exactly_once_in_cm_coroutine():
    """Exactly-once guard for the CM-owned SafetyAlert/SecurityAlert
    binaries (binary_sensor.py-defined pair). The CM coroutine must
    construct each ONCE. Adding a second call turns this RED.

    Note: aggregation.py:1151 / :1354 define a DIFFERENT Whole-House pair
    with the same class names. Both pairs must exist (Whole-House pair
    stays on INTEGRATION). This test scopes to the CM coroutine only.
    """
    src = _read("aggregation.py")
    m = _re.search(
        r"async def async_setup_cm_hosted_aggregation_binary_sensors\b.*?(?=\n(?:async )?def [A-Za-z_])",
        src, _re.DOTALL,
    )
    assert m, "async_setup_cm_hosted_aggregation_binary_sensors not found"
    body = m.group(0)
    # The disambiguating import in the fix-up aliases the classes; count
    # construction of the ALIASED names (which is what fires).
    assert body.count("_CoordSafetyAlert(") == 1, (
        "HIGH-A2: coordinator-device SafetyAlert must be constructed exactly once "
        "in the CM binary coroutine"
    )
    assert body.count("_CoordSecurityAlert(") == 1, (
        "HIGH-A2: coordinator-device SecurityAlert must be constructed exactly once "
        "in the CM binary coroutine"
    )


def test_d1b_cm_binary_coroutine_imports_from_binary_sensor_module():
    """CRITICAL-B1 anchor: the CM binary coroutine MUST import
    SafetyAlertBinarySensor / SecurityAlertBinarySensor explicitly from
    `.binary_sensor` (not fall back to aggregation.py's own definitions
    of those names). Reverting the disambiguating import turns this RED
    and would re-introduce the wrong-class instantiation bug.
    """
    src = _read("aggregation.py")
    m = _re.search(
        r"async def async_setup_cm_hosted_aggregation_binary_sensors\b.*?(?=\n(?:async )?def [A-Za-z_])",
        src, _re.DOTALL,
    )
    assert m, "async_setup_cm_hosted_aggregation_binary_sensors not found"
    body = m.group(0)
    assert "from .binary_sensor import" in body, (
        "CRITICAL-B1 regression: CM binary coroutine no longer explicitly "
        "imports from .binary_sensor — will resolve to aggregation.py's "
        "Whole-House pair (wrong classes)."
    )
    assert "SafetyAlertBinarySensor as _CoordSafetyAlert" in body
    assert "SecurityAlertBinarySensor as _CoordSecurityAlert" in body


def test_d1b_whole_house_pair_restored_on_integration():
    """B1 restore: the aggregation.py Whole-House SafetyAlert/SecurityAlert
    pair is BACK in `async_setup_aggregation_binary_sensors` (they were
    accidentally deleted in the initial build). Deleting them again turns
    this test RED.
    """
    src = _read("aggregation.py")
    m = _re.search(
        r"async def async_setup_aggregation_binary_sensors\b.*?async_add_entities\(entities\)",
        src, _re.DOTALL,
    )
    assert m, "async_setup_aggregation_binary_sensors not found"
    body = m.group(0)
    assert "SafetyAlertBinarySensor(hass, entry)" in body, (
        "CRITICAL-B1 restore: Whole-House SafetyAlertBinarySensor missing "
        "from async_setup_aggregation_binary_sensors"
    )
    assert "SecurityAlertBinarySensor(hass, entry)" in body, (
        "CRITICAL-B1 restore: Whole-House SecurityAlertBinarySensor missing "
        "from async_setup_aggregation_binary_sensors"
    )


def test_d1b_cm_setup_defers_per_person_via_async_at_started():
    """CRITICAL-B2 anchor: the CM sensor coroutine schedules the per-person
    branch via `async_at_started` (HA sets up domain entries concurrently,
    so person_coordinator is absent at CM setup time on cold boot).
    Removing the async_at_started scheduling turns this RED.
    """
    src = _read("aggregation.py")
    m = _re.search(
        r"async def async_setup_cm_hosted_aggregation_sensors\b.*?(?=\n(?:async )?def [A-Za-z_])",
        src, _re.DOTALL,
    )
    assert m
    body = m.group(0)
    assert "async_at_started(hass" in body, (
        "CRITICAL-B2: CM per-person branch is no longer deferred via "
        "async_at_started (cold-boot ordering hazard reintroduced)."
    )
    # MED-B4/B5: guard on INTEGRATION entry LOADED state is delegated to the
    # module-level `_integration_entry_is_loaded` helper (which references
    # ConfigEntryState.LOADED). Assert the deferred callback invokes the guard.
    assert "_integration_entry_is_loaded(" in body, (
        "MED-B4/B5: CM per-person branch no longer guards on INTEGRATION "
        "entry being LOADED (mere existence is insufficient)."
    )
    src_all = _read("aggregation.py")
    assert "ConfigEntryState.LOADED" in src_all, (
        "MED-B4/B5: _integration_entry_is_loaded no longer checks "
        "ConfigEntryState.LOADED"
    )


def test_d_nest_at_start_sweep_scheduled():
    """HIGH-B3 anchor: `async_schedule_device_tree_sweep` exists in
    `_devices.py` and CM setup invokes it. Removing the schedule call turns
    this RED; a cold-boot residual would then re-open the INV-4 gap.
    """
    devices_src = _read("_devices.py")
    assert "def async_schedule_device_tree_sweep(" in devices_src
    assert "async_at_started(hass, _sweep)" in devices_src
    # WARN-level residual log for the trip-wire
    assert "still lack via_device_id" in devices_src, (
        "HIGH-B3: unresolved-parent count is no longer logged at WARN as "
        "the INV-4 trip-wire"
    )
    init_src = _read("__init__.py")
    assert "async_schedule_device_tree_sweep" in init_src, (
        "HIGH-B3: CM setup no longer schedules the at-start device-tree sweep"
    )


# ---------------------------------------------------------------------------
# FIX-6..FIX-10 (2026-09-03, Review C fix-ups) — behavioural / call-position
# anchors for the CM-hosted coroutines, the D-NEST call sites, and the
# FIX-1 retry loop.
# ---------------------------------------------------------------------------


def _extract_coroutine_body(module_rel: str, name: str) -> str:
    """Return the source text of an async def coroutine by name.
    Anchored on the next top-level `def`/`async def` boundary.
    """
    src = _read(module_rel)
    m = _re.search(
        rf"async def {name}\b.*?(?=\n(?:async )?def [A-Za-z_])",
        src, _re.DOTALL,
    )
    assert m, f"could not locate {name} in {module_rel}"
    return m.group(0)


def test_fix6_cm_hosted_sensors_construct_expected_classes():
    """FIX-6 (Review C-CRIT-1): async_setup_cm_hosted_aggregation_sensors
    must construct BOTH House-level sensors (immediate phase) AND, in the
    deferred branch, both per-person sensor classes. Reverting the body
    to a bare `return` turns this test RED.

    Not a full-runtime behavioural test (aggregation.py's import graph is
    too large for this test package's stub set) — but pins the exact
    constructor calls that must live inside the coroutine body, so a
    neuter (delete either construction) fails.
    """
    body = _extract_coroutine_body(
        "aggregation.py", "async_setup_cm_hosted_aggregation_sensors",
    )
    # Phase 1: house-level sensors
    assert "HouseNextRoomAccuracySensor(hass, cm_entry)" in body, (
        "FIX-6: HouseNextRoomAccuracySensor not constructed in CM coroutine"
    )
    assert "HouseRoutineStatusSensor(hass, cm_entry)" in body, (
        "FIX-6: HouseRoutineStatusSensor not constructed in CM coroutine"
    )
    # Phase 2: per-person sensor construction present in deferred branch
    assert "PersonNextRoomAccuracySensor(hass, integration_entry, person_id)" in body, (
        "FIX-6: PersonNextRoomAccuracySensor not constructed in deferred branch"
    )
    assert "PersonRoutineStatusSensor(hass, integration_entry, person_id)" in body, (
        "FIX-6: PersonRoutineStatusSensor not constructed in deferred branch"
    )
    # Phase 1 targets the CM entry via async_add_entities
    assert "async_add_entities([" in body and "HouseNextRoomAccuracySensor" in body, (
        "FIX-6: phase-1 entities not added via async_add_entities under CM entry"
    )
    # Not the Whole House / INTEGRATION entry — assert we do NOT pass a
    # bare `entry` (the INTEGRATION forwarder's param) to House constructors.
    assert "HouseNextRoomAccuracySensor(hass, entry)" not in body, (
        "FIX-6: House sensor constructed with INTEGRATION entry — must be cm_entry"
    )


def test_fix6_cm_hosted_binary_sensors_construct_coordinator_pair():
    """FIX-6: async_setup_cm_hosted_aggregation_binary_sensors must
    construct exactly the coordinator-device SafetyAlert/SecurityAlert
    binaries (aliased) and add them via async_add_entities. Neutering the
    body to `return` turns this RED.
    """
    body = _extract_coroutine_body(
        "aggregation.py", "async_setup_cm_hosted_aggregation_binary_sensors",
    )
    assert "_CoordSafetyAlert(hass, cm_entry)" in body, (
        "FIX-6: coordinator SafetyAlert not constructed in CM binary coroutine"
    )
    assert "_CoordSecurityAlert(hass, cm_entry)" in body, (
        "FIX-6: coordinator SecurityAlert not constructed in CM binary coroutine"
    )
    assert "async_add_entities([" in body, (
        "FIX-6: CM binary coroutine does not call async_add_entities"
    )


def test_fix7_cm_hosted_sensors_deferred_guard_present():
    """FIX-7 (Review C-CRIT-2): the deferred per-person branch must:
      (a) guard against double-execution via `_register_per_person_sensors_scheduled["done"]`
      (b) set `["done"] = True` after successful registration
    Removing the guard OR the done-flip re-opens the _2 mint window.

    Note: the FIX-8 exactly-once-across-package guard already covers the
    static-source duplicate. This test covers the DYNAMIC re-fire path.
    """
    body = _extract_coroutine_body(
        "aggregation.py", "async_setup_cm_hosted_aggregation_sensors",
    )
    # (a) idempotency guard read
    assert '_register_per_person_sensors_scheduled["done"]' in body, (
        "FIX-7: per-person idempotency guard flag missing"
    )
    assert "already registered, skipping" in body or "return" in body, (
        "FIX-7: guard body doesn't short-circuit on already-done"
    )
    # (b) done-flip after success
    assert '_register_per_person_sensors_scheduled["done"] = True' in body, (
        "FIX-7: `done` flag never set to True — re-fire will double-add"
    )


def test_fix9_cm_sweep_call_after_forward_setups():
    """FIX-9 (Review C-HIGH-3): `async_schedule_device_tree_sweep` must be
    CALLED (not just imported) AFTER `async_forward_entry_setups` in the
    CM branch of __init__.py. Removing the call — even while leaving the
    import — turns this RED. The check is positional, not mere presence.
    """
    init_src = _read("__init__.py")
    # Locate CM branch by its `cm_platforms = ...` marker.
    cm_marker = init_src.find("cm_platforms = list(INTEGRATION_PLATFORMS)")
    assert cm_marker >= 0, "CM branch marker missing from __init__.py"
    # Slice a bounded window after the marker (well within the CM entry setup).
    window = init_src[cm_marker:cm_marker + 4000]
    # forward_setups must appear before the call.
    fwd_pos = window.find("async_forward_entry_setups(entry, cm_platforms)")
    call_pos = window.find("async_schedule_device_tree_sweep(hass)")
    assert fwd_pos >= 0, "CM branch: async_forward_entry_setups call missing"
    assert call_pos >= 0, (
        "FIX-9: async_schedule_device_tree_sweep NOT CALLED in CM branch "
        "(name might still be imported — this test requires the call)"
    )
    assert fwd_pos < call_pos, (
        "FIX-9: sweep scheduled BEFORE async_forward_entry_setups in CM "
        "branch — devices don't exist yet at that point"
    )


def test_fix3_room_stamp_call_after_forward_setups():
    """FIX-3 (Review D D-LEAK-3): the ROOM async_setup_entry branch must
    call `async_stamp_via_device_tree` + `async_schedule_device_tree_sweep`
    AFTER `async_forward_entry_setups(entry, PLATFORMS)`. Without this a
    runtime-added room floats unparented until restart.
    """
    init_src = _read("__init__.py")
    # PLATFORMS forward is at the room async_setup_entry (the last matching site).
    room_fwd = init_src.rfind("async_forward_entry_setups(entry, PLATFORMS)")
    assert room_fwd >= 0, "ROOM branch async_forward_entry_setups call missing"
    tail = init_src[room_fwd:room_fwd + 3000]
    assert "async_stamp_via_device_tree(hass)" in tail, (
        "FIX-3: ROOM branch does not stamp via_device_id after forward_setups"
    )
    assert "async_schedule_device_tree_sweep(hass)" in tail, (
        "FIX-3: ROOM branch does not schedule the at-start sweep after "
        "forward_setups (runtime-added rooms stay unparented until restart)"
    )


def test_fix2_integration_branch_also_schedules_sweep():
    """FIX-2 (Review D D-LEAK-2): the INTEGRATION branch must ALSO call
    `async_schedule_device_tree_sweep`, so a CM-late/CM-less boot still
    gets an at-start cover-all sweep. Prior code only scheduled from the
    CM branch.
    """
    init_src = _read("__init__.py")
    # Find INTEGRATION branch by its distinctive stamping comment.
    marker = init_src.find(
        "D-NEST): stamp via_device_id AFTER"
    )
    assert marker >= 0, "INTEGRATION branch D-NEST marker missing"
    window = init_src[marker:marker + 2000]
    assert "async_schedule_device_tree_sweep(hass)" in window, (
        "FIX-2: INTEGRATION branch does not schedule the at-start sweep — "
        "a CM-late boot leaves the sweep unarmed"
    )


def test_fix2_sweep_has_rearm_ceiling():
    """FIX-2 (Review D D-LEAK-2): `async_schedule_device_tree_sweep`
    must (a) allow bounded re-arm on residual > 0, and (b) cap re-arms so
    a persistent parent gap doesn't schedule forever.
    """
    src = _read("_devices.py")
    assert "_device_tree_sweep_count" in src, (
        "FIX-2: sweep scheduler missing re-arm counter"
    )
    assert "_MAX_SCHEDULES" in src, (
        "FIX-2: sweep scheduler missing re-arm ceiling"
    )
    # The at-start sweep must clear the pending latch so future callers can re-arm.
    assert '_device_tree_sweep_scheduled"] = False' in src or \
           "_device_tree_sweep_scheduled'] = False" in src, (
        "FIX-2: at-start sweep does not clear the pending-latch, blocking re-arm"
    )
    # Retry via async_call_later on residual.
    assert "async_call_later" in src and "residual" in src, (
        "FIX-2: sweep does not schedule an async_call_later retry on residual"
    )


def test_fix5_devices_module_tracks_unsub():
    """FIX-5 (Review D D-LEAK-5): the async_at_started unsub in _devices.py
    is stored (not discarded) so a reload-before-started can cancel it.
    """
    src = _read("_devices.py")
    assert "unsub = async_at_started(hass, _sweep)" in src, (
        "FIX-5: _devices.py discards the async_at_started unsub"
    )
    assert "_device_tree_sweep_unsubs" in src, (
        "FIX-5: _devices.py does not track sweep unsubs"
    )


def test_fix5_aggregation_registers_unsub_with_cm_entry():
    """FIX-5 (Review D D-LEAK-5): the async_at_started unsub in
    aggregation.py is registered on the CM entry via async_on_unload so
    a reload-before-started tears it down.
    """
    src = _read("aggregation.py")
    body = _extract_coroutine_body(
        "aggregation.py", "async_setup_cm_hosted_aggregation_sensors",
    )
    assert "unsub = async_at_started(hass, _register_per_person)" in body, (
        "FIX-5: aggregation.py discards the async_at_started unsub"
    )
    assert "cm_entry.async_on_unload(unsub)" in body, (
        "FIX-5: async_at_started unsub not registered with cm_entry.async_on_unload"
    )


def test_fix10_cm_deferred_branch_retry_on_prereqs_missing():
    """FIX-10 (Review C-HIGH-2): the deferred branch, when INTEGRATION is
    not LOADED or person_coordinator is absent, must schedule a bounded
    async_call_later retry (with a max-attempts cap) so a slow-DB boot
    doesn't permanently orphan the 8 per-person sensors. This anchors on
    the retry machinery required by FIX-1.
    """
    body = _extract_coroutine_body(
        "aggregation.py", "async_setup_cm_hosted_aggregation_sensors",
    )
    # Machinery introduced by FIX-1 must be present:
    assert "_MAX_RETRY_ATTEMPTS" in body, (
        "FIX-10: no max-attempts cap on the retry loop"
    )
    assert "async_call_later" in body, (
        "FIX-10: no async_call_later retry scheduled on prereq-miss"
    )
    assert "cm_entry.async_on_unload(handle)" in body, (
        "FIX-10: async_call_later handle not cancelled on unload — leak"
    )
    # Retry must call back into the same closure (discharge).
    assert "async_call_later(\n                    hass, _RETRY_DELAY_S, _register_per_person" in body \
        or "async_call_later(hass, _RETRY_DELAY_S, _register_per_person)" in body \
        or "_register_per_person" in body.split("async_call_later")[1][:200], (
        "FIX-10: async_call_later does not re-schedule _register_per_person "
        "(no discharge)"
    )
    # `attempts` counter incremented before scheduling.
    assert '_register_per_person_sensors_scheduled["attempts"]' in body, (
        "FIX-10: no attempts counter on the retry loop"
    )


# ---------------------------------------------------------------------------
# v5.94.1 FIX 1 + FIX 2 — parent-entry shell cleanup + sweep tie-break.
# ---------------------------------------------------------------------------


class _FakeDevice2:
    """Extended fake device with config_entries — used by v5.94.1 tests."""

    def __init__(
        self,
        device_id: str,
        identifiers: set[tuple[str, str]],
        config_entries: set[str] | None = None,
    ):
        self.id = device_id
        self.identifiers = identifiers
        self.via_device_id: str | None = None
        self.config_entries = set(config_entries or [])


class _FakeDevReg2:
    """Fake device registry that simulates HA's `_identifiers` index +
    the `__delitem__` un-index-on-remove behaviour v5.94.1 B2 targets.

    On removal, the shared identifier slot is dropped unconditionally
    (mirrors helpers/device_registry.py). B2's re-index call feeds the
    survivor's identifiers back through `async_update_device(
    new_identifiers=...)` — we rebuild the index slot only when that
    call is made, so a test can assert re-index is deterministic (not
    a side effect).
    """

    def __init__(self, devices: list[_FakeDevice2]):
        self.devices = {d.id: d for d in devices}
        self.removed: list[str] = []
        self.update_calls: list[tuple] = []
        # Build the identifier -> device_id index, last-writer-wins
        # (mirrors HA's dict insertion order).
        self._ident_index: dict[tuple[str, str], str] = {}
        for d in devices:
            for ident in d.identifiers:
                self._ident_index[ident] = d.id

    def async_get(self, device_id):
        return self.devices.get(device_id)

    def async_get_device(self, identifiers=None, **_kw):
        """Mirror HA's identifier-index lookup — returns whatever the
        index slot points at (or None if un-indexed)."""
        if not identifiers:
            return None
        for ident in identifiers:
            did = self._ident_index.get(tuple(ident))
            if did is not None:
                return self.devices.get(did)
        return None

    def async_get_or_create(
        self, *, config_entry_id, identifiers, **_kw,
    ):
        """Mirror HA's async_get_or_create resolution — reuse the
        identifier-index slot when present, else mint a new device.
        This is the exact code path A-MED protects against.
        """
        existing = self.async_get_device(identifiers=identifiers)
        if existing is not None:
            existing.config_entries.add(config_entry_id)
            return existing
        new_id = f"minted_{len(self.devices)}"
        dev = _FakeDevice2(new_id, set(identifiers), config_entries={config_entry_id})
        self.devices[new_id] = dev
        for ident in dev.identifiers:
            self._ident_index[ident] = new_id
        return dev

    def async_update_device(
        self,
        device_id,
        *,
        via_device_id=None,
        remove_config_entry_id=None,
        new_identifiers=None,
    ):
        self.update_calls.append(
            (device_id, via_device_id, remove_config_entry_id, new_identifiers)
        )
        dev = self.devices.get(device_id)
        if dev is None:
            return
        if via_device_id is not None:
            dev.via_device_id = via_device_id
        if new_identifiers is not None:
            # Re-index: replace this device's identifier slots.
            dev.identifiers = set(new_identifiers)
            for ident in dev.identifiers:
                self._ident_index[ident] = device_id
        if remove_config_entry_id is not None:
            dev.config_entries.discard(remove_config_entry_id)
            # HA auto-deletes when this was the sole entry.
            if not dev.config_entries:
                self.removed.append(device_id)
                self.devices.pop(device_id, None)
                # HA's __delitem__ drops the identifier slot
                # UNCONDITIONALLY — mirror that here so the un-index
                # hazard shows up in tests (B2 must re-index).
                for ident in list(dev.identifiers):
                    self._ident_index.pop(ident, None)


class _FakeEntReg:
    """Trivial entity registry returning the pre-seeded list for a device."""

    def __init__(self, entities_by_device: dict[str, list]):
        self._by_dev = entities_by_device

    def async_entries_for_device(self, device_id, include_disabled_entities=False):  # noqa: D401
        return list(self._by_dev.get(device_id, []))


def _install_ent_reg(monkeypatch, ent_reg):
    from homeassistant.helpers import entity_registry as er
    monkeypatch.setattr(er, "async_get", lambda hass: ent_reg, raising=False)
    monkeypatch.setattr(
        er, "async_entries_for_device",
        lambda reg, dev_id, include_disabled_entities=False:
            reg.async_entries_for_device(
                dev_id, include_disabled_entities=include_disabled_entities,
            ),
        raising=False,
    )


def _fake_hass_with_parent_entry(parent_entry_id: str | None):
    """Minimal hass with config_entries.async_entries('universal_room_automation')."""
    hass = MagicMock()
    if parent_entry_id is None:
        hass.config_entries.async_entries = MagicMock(return_value=[])
        return hass
    entry = MagicMock()
    entry.entry_id = parent_entry_id
    entry.data = {"entry_type": "integration"}
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    return hass


# --- FIX 1: shell-removal predicate ----------------------------------------


@pytest.mark.asyncio
async def test_v5_94_1_shell_cleanup_removes_only_empty_shell(monkeypatch):
    """FIX 1: only the empty parent-owned shell is removed; the real
    populated CM-owned device survives (same identifier)."""
    d = _import_devices()

    parent = "PARENT_ENTRY"
    cm = "CM_ENTRY"

    real_cm = _FakeDevice2(
        "dev_real_cm",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={cm},
    )
    shell = _FakeDevice2(
        "dev_shell_cm",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={parent},
    )
    # A third device we should NEVER touch (has entities, on parent).
    inhab = _FakeDevice2(
        "dev_inhabited",
        {("universal_room_automation", "security_coordinator")},
        config_entries={parent},
    )
    fake_reg = _FakeDevReg2([real_cm, shell, inhab])

    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)

    ent_reg = _FakeEntReg({
        "dev_real_cm": ["entity_1", "entity_2"],  # populated
        "dev_shell_cm": [],  # empty
        "dev_inhabited": ["entity_3"],  # populated
    })
    _install_ent_reg(monkeypatch, ent_reg)

    hass = MagicMock()
    removed = await d.async_cleanup_parent_entry_shells(hass, parent)

    assert removed == 1, f"expected 1 shell removed, got {removed}"
    assert "dev_shell_cm" in fake_reg.removed, (
        "empty parent-owned shell was NOT removed"
    )
    assert "dev_real_cm" in fake_reg.devices, (
        "REAL CM device (same identifier) was destroyed — same-identifier hazard"
    )
    assert "dev_inhabited" in fake_reg.devices, (
        "populated parent-owned device was wrongly removed"
    )


@pytest.mark.asyncio


@pytest.mark.asyncio
async def test_v5_94_1_shell_cleanup_survives_three_tuple_identifiers(monkeypatch):
    """v5.94.3 regression: other integrations (bond, homekit) register
    3-ELEMENT identifiers. The cleanup iterates ALL devices in the
    registry; a `for (dom, ident) in device.identifiers` unpack raised
    ValueError on the first such non-URA device and aborted the whole
    cleanup before reaching any URA shell. Guard: a 3-tuple device must
    be skipped safely and the real shell still removed."""
    d = _import_devices()
    parent = "PARENT_ENTRY"
    cm = "CM_ENTRY"

    # Non-URA device with a 3-element identifier (bond-style) — must NOT crash.
    bond = _FakeDevice2(
        "dev_bond",
        {("bond", "ZPGH77358", "9be870302e561726")},
        config_entries={"BOND_ENTRY"},
    )
    shell = _FakeDevice2(
        "dev_shell_cm",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={parent},
    )
    fake_reg = _FakeDevReg2([bond, shell])

    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)
    _install_ent_reg(monkeypatch, _FakeEntReg({"dev_bond": ["e1"], "dev_shell_cm": []}))

    hass = MagicMock()
    removed = await d.async_cleanup_parent_entry_shells(hass, parent)

    # Must not raise, and the shell must be removed despite the 3-tuple device.
    assert removed == 1, f"expected shell removed past the 3-tuple device, got {removed}"
    assert "dev_shell_cm" not in fake_reg.devices
    assert "dev_bond" in fake_reg.devices  # untouched

async def test_v5_94_1_shell_cleanup_skips_dual_owned(monkeypatch):
    """FIX 1: a shell dual-owned by parent AND another entry is NEVER
    removed — sole-owner (exact set equality) guard, not membership."""
    d = _import_devices()
    parent = "PARENT_ENTRY"
    dual = _FakeDevice2(
        "dev_dual",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={parent, "OTHER_ENTRY"},
    )
    fake_reg = _FakeDevReg2([dual])
    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)
    _install_ent_reg(monkeypatch, _FakeEntReg({"dev_dual": []}))

    hass = MagicMock()
    removed = await d.async_cleanup_parent_entry_shells(hass, parent)
    assert removed == 0
    assert "dev_dual" in fake_reg.devices
    # Must NOT even have attempted a demote either — sole-owner guard blocks it.
    assert fake_reg.update_calls == []


# --- FIX 2: sweep same-identifier tie-break --------------------------------


@pytest.mark.asyncio
async def test_v5_94_1_stamp_prefers_populated_over_shell(monkeypatch):
    """FIX 2: when two devices share the coordinator_manager identifier
    (one empty-parent shell, one populated CM), children resolve to the
    POPULATED device — never the shell."""
    d = _import_devices()
    parent = "PARENT_ENTRY"
    cm = "CM_ENTRY"

    integration = _FakeDevice2(
        "dev_int",
        {("universal_room_automation", "integration")},
        config_entries={parent},
    )
    # Two coord_manager devices (same identifier).
    shell_cm = _FakeDevice2(
        "dev_shell_cm",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={parent},
    )
    real_cm = _FakeDevice2(
        "dev_real_cm",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={cm},
    )
    # A child that should nest under coordinator_manager.
    child = _FakeDevice2(
        "dev_child_safety",
        {("universal_room_automation", "safety_coordinator")},
        config_entries={cm},
    )
    # ORDER MATTERS: real_cm FIRST, shell_cm LAST — under last-writer-wins
    # (pre-FIX 2 behaviour) the shell would overwrite the real CM in
    # ura_index and children would nest under the dead shell. FIX 2 must
    # skip the shell regardless of insertion order.
    fake_reg = _FakeDevReg2([integration, real_cm, shell_cm, child])
    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)

    ent_reg = _FakeEntReg({
        "dev_int": ["e_int"],
        "dev_shell_cm": [],
        "dev_real_cm": ["e_cm_1"],
        "dev_child_safety": ["e_safety"],
    })
    _install_ent_reg(monkeypatch, ent_reg)

    hass = _fake_hass_with_parent_entry(parent)
    # ENTRY_TYPE_INTEGRATION value is "integration" — const.py:50.
    # _fake_hass_with_parent_entry already sets entry.data["entry_type"]="integration".

    await d.async_stamp_via_device_tree(hass)

    assert fake_reg.devices["dev_child_safety"].via_device_id == "dev_real_cm", (
        "FIX 2 tie-break broken — child resolved to the shell instead of "
        f"the real CM (got {fake_reg.devices['dev_child_safety'].via_device_id})"
    )
    # Shell must NEVER be chosen as a parent for anyone.
    for dev in fake_reg.devices.values():
        assert dev.via_device_id != "dev_shell_cm", (
            f"shell was picked as parent for {dev.id}"
        )


@pytest.mark.asyncio
async def test_v5_94_1_shell_cleanup_survival_all_three_identifiers(monkeypatch):
    """Operator safety mandate: for EACH of coordinator_manager /
    security_coordinator / music_following_coordinator — the REAL CM-owned
    device with entities MUST survive; only the empty parent-owned shell
    is removed. Belt-and-suspenders: sole-parent AND not-CM-owned AND
    zero-entities. Removal ops MUST target shell device.ids ONLY.
    """
    d = _import_devices()
    parent = "PARENT_ENTRY"
    cm = "CM_ENTRY"

    idents = [
        "coordinator_manager",
        "security_coordinator",
        "music_following_coordinator",
    ]
    devices = []
    ent_map = {}
    real_ids: dict[str, str] = {}
    shell_ids: dict[str, str] = {}
    for ident in idents:
        real_id = f"dev_real_{ident}"
        shell_id = f"dev_shell_{ident}"
        real_ids[ident] = real_id
        shell_ids[ident] = shell_id
        devices.append(_FakeDevice2(
            real_id,
            {("universal_room_automation", ident)},
            config_entries={cm},
        ))
        devices.append(_FakeDevice2(
            shell_id,
            {("universal_room_automation", ident)},
            config_entries={parent},
        ))
        ent_map[real_id] = [f"e_{ident}_1", f"e_{ident}_2"]
        ent_map[shell_id] = []

    fake_reg = _FakeDevReg2(devices)
    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)
    _install_ent_reg(monkeypatch, _FakeEntReg(ent_map))

    hass = MagicMock()
    removed = await d.async_cleanup_parent_entry_shells(
        hass, parent, cm_entry_id=cm,
    )

    assert removed == 3, f"expected all 3 shells removed, got {removed}"
    # Every shell gone
    for ident, sid in shell_ids.items():
        assert sid not in fake_reg.devices, (
            f"shell {sid} for {ident} not removed"
        )
    # Every REAL device survives
    for ident, rid in real_ids.items():
        assert rid in fake_reg.devices, (
            f"REAL device {rid} for {ident} was destroyed — safety guard failed"
        )
    # Removal ops targeted shell IDs ONLY, never a real id. Filter to
    # remove_config_entry_id calls — B2 re-index calls (new_identifiers)
    # deliberately DO target the surviving real device.
    real_id_set = set(real_ids.values())
    for (dev_id, via, remove_ce, _new_ids) in fake_reg.update_calls:
        if remove_ce is None:
            continue
        assert dev_id not in real_id_set, (
            f"async_update_device(remove_config_entry_id=...) called on REAL "
            f"device {dev_id} — must be shell-only"
        )


# ---------------------------------------------------------------------------
# v5.94.1 review-fix-up tests — B2 re-index, A-MED ordering, B1 kill-switch.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v5_94_1_b2_reindex_after_shell_removal(monkeypatch):
    """B2: after cleanup, `async_get_device({(DOMAIN,'coordinator_manager')})`
    resolves to the surviving CM device — the shared identifier slot was
    re-indexed deterministically (not left un-indexed by
    __delitem__).
    """
    d = _import_devices()
    parent = "PARENT_ENTRY"
    cm = "CM_ENTRY"
    real_cm = _FakeDevice2(
        "dev_real_cm",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={cm},
    )
    shell = _FakeDevice2(
        "dev_shell_cm",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={parent},
    )
    # Insert shell LAST so the initial index points at the shell — this is
    # the exact pre-condition that motivates B2 (removing the shell drops
    # the shared slot; without re-index the survivor is unfindable).
    fake_reg = _FakeDevReg2([real_cm, shell])
    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)
    _install_ent_reg(monkeypatch, _FakeEntReg({
        "dev_real_cm": ["entity_1"], "dev_shell_cm": [],
    }))

    hass = MagicMock()
    ident = ("universal_room_automation", "coordinator_manager")

    # Pre-condition: index resolves to the shell (last-writer-wins).
    assert fake_reg.async_get_device(identifiers={ident}).id == "dev_shell_cm"

    removed = await d.async_cleanup_parent_entry_shells(
        hass, parent, cm_entry_id=cm,
    )
    assert removed == 1

    # Post-condition: index resolves to the survivor (re-indexed).
    resolved = fake_reg.async_get_device(identifiers={ident})
    assert resolved is not None, (
        "B2: identifier slot un-indexed and NOT re-indexed — a subsequent "
        "async_get_or_create would mint a DUPLICATE for coordinator_manager"
    )
    assert resolved.id == "dev_real_cm", (
        f"B2: identifier slot re-indexed to wrong device {resolved.id}"
    )

    # A simulated second async_get_or_create (what CM setup does at
    # ~__init__.py:4181) must resolve to the survivor — no duplicate.
    result = fake_reg.async_get_or_create(
        config_entry_id=cm, identifiers={ident},
    )
    assert result.id == "dev_real_cm", (
        f"B2: get_or_create minted a duplicate ({result.id}) instead of "
        f"resolving to the re-indexed survivor"
    )


@pytest.mark.asyncio
async def test_v5_94_1_amed_order_cleanup_before_get_or_create(monkeypatch):
    """A-MED: with a pre-existing empty parent-owned shell + real CM,
    the intended CM-setup sequence — cleanup FIRST, then get_or_create —
    yields EXACTLY ONE coordinator_manager device bound to the CM entry.

    The bug the ordering fix prevents: get_or_create runs first, the
    identifier index resolves to the shell (last-writer-wins), the shell
    is bound to the CM entry (`config_entries` becomes {parent, cm}),
    guard-1 (== {parent}) then permanently excludes it and the CM
    entities re-home onto the shell.
    """
    d = _import_devices()
    parent = "PARENT_ENTRY"
    cm = "CM_ENTRY"
    ident = ("universal_room_automation", "coordinator_manager")
    real_cm = _FakeDevice2("dev_real_cm", {ident}, config_entries={cm})
    shell = _FakeDevice2("dev_shell_cm", {ident}, config_entries={parent})
    # Shell inserted last — index resolves to shell.
    fake_reg = _FakeDevReg2([real_cm, shell])
    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)
    _install_ent_reg(monkeypatch, _FakeEntReg({
        "dev_real_cm": ["e_cm_1"], "dev_shell_cm": [],
    }))
    hass = MagicMock()

    # A-MED sequence: cleanup, THEN get_or_create.
    await d.async_cleanup_parent_entry_shells(hass, parent, cm_entry_id=cm)
    result = fake_reg.async_get_or_create(
        config_entry_id=cm, identifiers={ident},
        name="URA: Coordinator Manager",
    )

    # Exactly one device carries the identifier + it's the real CM +
    # sole-owned by CM.
    carriers = [
        dev for dev in fake_reg.devices.values() if ident in dev.identifiers
    ]
    assert len(carriers) == 1, (
        f"A-MED: expected exactly 1 coordinator_manager device, got "
        f"{len(carriers)}: {[d.id for d in carriers]}"
    )
    assert result.id == "dev_real_cm"
    assert result.config_entries == {cm}, (
        f"A-MED: real CM ended up with wrong config_entries={result.config_entries}"
    )


@pytest.mark.asyncio
async def test_v5_94_1_amed_wrong_order_would_bind_shell_to_cm(monkeypatch):
    """A-MED counter-example: the OLD ordering (get_or_create first, then
    cleanup) leaves the shell bound to BOTH entries and guard-1 permanently
    excludes it. Test proves the failure mode is real (would FAIL without
    the ordering fix).
    """
    d = _import_devices()
    parent = "PARENT_ENTRY"
    cm = "CM_ENTRY"
    ident = ("universal_room_automation", "coordinator_manager")
    real_cm = _FakeDevice2("dev_real_cm", {ident}, config_entries={cm})
    shell = _FakeDevice2("dev_shell_cm", {ident}, config_entries={parent})
    fake_reg = _FakeDevReg2([real_cm, shell])
    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)
    _install_ent_reg(monkeypatch, _FakeEntReg({
        "dev_real_cm": ["e_cm_1"], "dev_shell_cm": [],
    }))
    hass = MagicMock()

    # OLD (broken) sequence: get_or_create FIRST, then cleanup.
    fake_reg.async_get_or_create(
        config_entry_id=cm, identifiers={ident},
    )
    # Shell now dual-owned.
    assert fake_reg.devices["dev_shell_cm"].config_entries == {parent, cm}
    removed = await d.async_cleanup_parent_entry_shells(
        hass, parent, cm_entry_id=cm,
    )
    # Guard-1 (sole == {parent}) skips the dual-owned shell; guard-2
    # (cm-owned) also skips. Removal is zero — the shell lingers with
    # the CM entry bound.
    assert removed == 0, (
        "Counter-example broken — cleanup unexpectedly removed a "
        "dual-owned shell (violates safety guards)"
    )
    # And there are TWO coordinator_manager carriers — the exact
    # nondeterministic-duplicate state A-MED prevents.
    carriers = [
        dev for dev in fake_reg.devices.values() if ident in dev.identifiers
    ]
    assert len(carriers) == 2, (
        "Counter-example broken — expected 2 carriers under the old order"
    )


@pytest.mark.asyncio
async def test_v5_94_1_b1_kill_switch_disables_shell_cleanup(monkeypatch):
    """B1: `URA_DEVICE_TREE_STAMPING_ENABLED = False` disables shell
    cleanup as well (fate-share with the stamper). Otherwise disabling
    D-NEST would strand the 6 real coordinators with via_device_id=None
    while still deleting the shells that were their only parent slot.
    """
    d = _import_devices()
    parent = "PARENT_ENTRY"
    cm = "CM_ENTRY"
    shell = _FakeDevice2(
        "dev_shell_cm",
        {("universal_room_automation", "coordinator_manager")},
        config_entries={parent},
    )
    fake_reg = _FakeDevReg2([shell])
    from homeassistant.helpers import device_registry as dr
    monkeypatch.setattr(dr, "async_get", lambda hass: fake_reg)
    _install_ent_reg(monkeypatch, _FakeEntReg({"dev_shell_cm": []}))

    monkeypatch.setattr(d, "URA_DEVICE_TREE_STAMPING_ENABLED", False)

    hass = MagicMock()
    removed = await d.async_cleanup_parent_entry_shells(
        hass, parent, cm_entry_id=cm,
    )
    assert removed == 0, (
        "B1: kill-switch False should make cleanup a no-op"
    )
    assert "dev_shell_cm" in fake_reg.devices, (
        "B1: shell removed despite URA_DEVICE_TREE_STAMPING_ENABLED=False"
    )
    assert fake_reg.update_calls == [], (
        "B1: no update_device calls should have been made under kill-switch"
    )


def test_v5_94_1_amed_source_order_cleanup_precedes_get_or_create():
    """A-MED source anchor: in the CM entry setup branch of __init__.py,
    `async_cleanup_parent_entry_shells` MUST appear textually BEFORE the
    CM `dev_reg.async_get_or_create(identifiers={(DOMAIN, "coordinator_manager")`.
    Mutating the ordering (reverting A-MED) makes this test RED.
    """
    src = (PKG_ROOT / "__init__.py").read_text()
    cm_anchor = "if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:"
    cm_idx = src.find(cm_anchor)
    assert cm_idx >= 0, "CM entry branch anchor not found in __init__.py"
    # Scope the search window to the CM branch — pick the FIRST occurrence
    # of each marker after the CM anchor.
    body = src[cm_idx:cm_idx + 20000]
    cleanup_pos = body.find("async_cleanup_parent_entry_shells(")
    goc_pos = body.find('identifiers={(DOMAIN, "coordinator_manager")}')
    assert cleanup_pos > 0, "shell-cleanup call not found in CM branch"
    assert goc_pos > 0, "CM async_get_or_create not found in CM branch"
    assert cleanup_pos < goc_pos, (
        f"A-MED regression: async_cleanup_parent_entry_shells at "
        f"offset {cleanup_pos} runs AFTER the CM async_get_or_create at "
        f"offset {goc_pos}. Cleanup MUST precede get_or_create so the "
        f"identifier index isn't populated with the shell before "
        f"resolution (see v5.94.1 A-MED)."
    )


def test_v5_94_1_b3_teardown_helper_drains_sweep_handles():
    """B3: `async_teardown_device_tree_sweep_handles` invokes each unsub
    (callable) and cancels each async_call_later handle, then clears the
    lists so a subsequent unload no-ops."""
    d = _import_devices()

    called_unsub = []
    called_cancel = []

    def _unsub():
        called_unsub.append("u1")

    class _Handle:
        def cancel(self):
            called_cancel.append("c1")

    _DOM = "universal_room_automation"
    hass = MagicMock()
    hass.data = {
        _DOM: {
            "_device_tree_sweep_unsubs": [_unsub],
            "_device_tree_sweep_retry_handles": [_Handle()],
            "_device_tree_sweep_scheduled": True,
        }
    }

    d.async_teardown_device_tree_sweep_handles(hass)
    assert called_unsub == ["u1"], "B3: unsub was not invoked"
    assert called_cancel == ["c1"], "B3: retry handle was not cancelled"
    assert hass.data[_DOM]["_device_tree_sweep_unsubs"] == []
    assert hass.data[_DOM]["_device_tree_sweep_retry_handles"] == []
    assert hass.data[_DOM]["_device_tree_sweep_scheduled"] is False

    # Idempotent — second call is a no-op.
    d.async_teardown_device_tree_sweep_handles(hass)
    assert called_unsub == ["u1"]  # not re-invoked
    assert called_cancel == ["c1"]


def test_v5_94_1_b3_teardown_wired_into_cm_and_integration_unload():
    """B3 source anchor: `async_teardown_device_tree_sweep_handles` is
    called from BOTH the CM and INTEGRATION unload paths in __init__.py."""
    src = (PKG_ROOT / "__init__.py").read_text()
    # Find the unload function.
    unload_idx = src.find("async def async_unload_entry(")
    assert unload_idx > 0
    unload_body = src[unload_idx:]

    # INTEGRATION branch.
    int_branch = unload_body.find("if entry_type == ENTRY_TYPE_INTEGRATION:")
    assert int_branch > 0
    int_slice = unload_body[int_branch:int_branch + 4000]
    assert "async_teardown_device_tree_sweep_handles" in int_slice, (
        "B3: teardown not wired into INTEGRATION unload branch"
    )

    # CM branch.
    cm_branch = unload_body.find("if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:")
    assert cm_branch > 0
    cm_slice = unload_body[cm_branch:cm_branch + 4000]
    assert "async_teardown_device_tree_sweep_handles" in cm_slice, (
        "B3: teardown not wired into CM unload branch"
    )


def test_v5_94_1_b1_schedule_hoisted_out_of_stamp_try_except():
    """B1 source anchor: in the CM setup branch, the
    `async_schedule_device_tree_sweep(hass)` call must live in its OWN
    try/except — a stamp exception must NOT prevent sweep scheduling.
    Concretely: the call must NOT sit inside the same `try:` block as
    `await async_stamp_via_device_tree(hass)`.
    """
    src = (PKG_ROOT / "__init__.py").read_text()
    cm_idx = src.find("if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:")
    assert cm_idx > 0
    # Grab a large window covering the D-NEST section.
    body = src[cm_idx:cm_idx + 20000]
    # Find the stamp await and the schedule call.
    stamp_pos = body.find("await async_stamp_via_device_tree(hass)")
    sched_pos = body.find("async_schedule_device_tree_sweep(hass)")
    assert stamp_pos > 0 and sched_pos > 0
    # Between stamp and schedule there MUST be an `except` block closure —
    # i.e., a line starting with `except` after stamp and before schedule.
    interstitial = body[stamp_pos:sched_pos]
    assert "\n        except" in interstitial, (
        "B1: async_schedule_device_tree_sweep still sits inside the same "
        "try/except as async_stamp_via_device_tree — a stamp raise would "
        "skip sweep scheduling"
    )
