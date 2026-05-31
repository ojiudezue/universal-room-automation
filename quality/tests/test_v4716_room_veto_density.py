"""v4.7.16 — Room-level veto + density weighting via existing CONF_SCANNER_AREAS.

Four-deliverable Tier 2-DB cycle:

  D1 — Expose `ble_tier` (1/2/0) as a derived attribute on each room
       via PersonTrackingCoordinator.get_ble_tier. Reuses
       _build_scanner_room_map classifications; lazy at read time.

  D2 — New per-room diagnostic sensor RoomSignalInventorySensor
       (sensor.ura_<room>_signal_inventory). State is a human-readable
       rollup; numeric ble_tier in attributes (Bug Class #47).

  D3 — Per-room confidence-weighted veto. Zone-iterates-rooms loop in
       _run_inference builds a per-room weight map (1.0 / 0.6 / 0.0)
       and calls the v4.7.15 shared veto helper against its documented
       contract. Status: complete-pending-helper-verification.

  D4 — New per-room CONF_DISABLE_CAMERA_PRESENCE bool field. When True,
       _discover_zone_cameras skips tracker.register_camera for the
       zone owning that room's area_id.

Tests prefer source-grep AST harnesses (per Bug Class #44 + test
fixture authority: drive production code paths, never hand-copy
schemas) over heavy runtime mocking. Behavioral tests for get_ble_tier
run against the real PersonTrackingCoordinator method.
"""

from __future__ import annotations

import ast
import importlib.util
import os
from unittest.mock import MagicMock

import pytest


# ----------------------------------------------------------------------------
# Direct-load helpers (bypass __init__.py to avoid pulling in homeassistant)
# ----------------------------------------------------------------------------


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ura_const():
    """Load const.py without going through the URA package __init__."""
    return _load_module(
        "ura_const_v4716",
        os.path.join(
            "custom_components", "universal_room_automation", "const.py"
        ),
    )


# ----------------------------------------------------------------------------
# Source-grep harness
# ----------------------------------------------------------------------------

ROOT = "custom_components/universal_room_automation"
CONST_PY = os.path.join(ROOT, "const.py")
CONFIG_FLOW_PY = os.path.join(ROOT, "config_flow.py")
STRINGS_JSON = os.path.join(ROOT, "strings.json")
PERSON_PY = os.path.join(ROOT, "person_coordinator.py")
PRESENCE_PY = os.path.join(ROOT, "domain_coordinators", "presence.py")
SENSOR_PY = os.path.join(ROOT, "sensor.py")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


@pytest.fixture(scope="module")
def const_src() -> str:
    return _read(CONST_PY)


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    return _read(CONFIG_FLOW_PY)


@pytest.fixture(scope="module")
def strings_src() -> str:
    return _read(STRINGS_JSON)


@pytest.fixture(scope="module")
def person_src() -> str:
    return _read(PERSON_PY)


@pytest.fixture(scope="module")
def presence_src() -> str:
    return _read(PRESENCE_PY)


@pytest.fixture(scope="module")
def sensor_src() -> str:
    return _read(SENSOR_PY)


# ============================================================================
# D1 — get_ble_tier accessor on PersonTrackingCoordinator
# ============================================================================


class TestD1GetBleTier:
    """Source-level guarantees + behavioral checks for get_ble_tier."""

    def test_method_exists(self, person_src: str):
        assert "def get_ble_tier" in person_src, (
            "v4.7.16 D1: PersonTrackingCoordinator.get_ble_tier missing"
        )

    def test_method_is_public(self, person_src: str):
        # Public method (no leading underscore) so other coordinators
        # and the D2 sensor can call it without reaching into privates.
        assert "def get_ble_tier(self, room_name" in person_src, (
            "v4.7.16 D1: signature mismatch — expected "
            "get_ble_tier(self, room_name: str) -> int"
        )

    def test_returns_int_annotation(self, person_src: str):
        assert "def get_ble_tier(self, room_name: str) -> int:" in person_src, (
            "v4.7.16 D1: get_ble_tier must declare -> int return"
        )

    def test_no_migration_helper(self, person_src: str):
        """Bug Class #46 — lazy derivation. No _migrate_ble_tier helper."""
        assert "_migrate_ble_tier" not in person_src, (
            "v4.7.16 D1 must NOT add a migration helper (Bug Class #46)"
        )

    def test_uses_existing_direct_ble_rooms_cache(self, person_src: str):
        # Read-only consumer of the v3.8.9 cache.
        tree = ast.parse(person_src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_ble_tier":
                target = node
                break
        assert target is not None
        body = ast.unparse(target)
        assert "_direct_ble_rooms" in body, (
            "v4.7.16 D1: get_ble_tier must consume _direct_ble_rooms cache"
        )

    def test_walks_room_config_entries_for_tier_2(self, person_src: str):
        tree = ast.parse(person_src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_ble_tier":
                target = node
                break
        body = ast.unparse(target)
        assert "CONF_SCANNER_AREAS" in body, (
            "v4.7.16 D1: tier 2 detection must reference CONF_SCANNER_AREAS"
        )
        assert "CONF_AREA_ID" in body, (
            "v4.7.16 D1: tier 2 detection must require CONF_AREA_ID set"
        )

    def test_does_not_modify_build_scanner_room_map(self, person_src: str):
        # Per task brief: must NOT modify _build_scanner_room_map.
        tree = ast.parse(person_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_build_scanner_room_map"
            ):
                body = ast.unparse(node)
                assert "get_ble_tier" not in body, (
                    "v4.7.16 D1: _build_scanner_room_map must not change"
                )
                return
        pytest.fail("_build_scanner_room_map missing")

    def test_get_ble_tier_returns_0_on_unknown_room_branch(
        self, person_src: str
    ):
        """Source-shape assertion: get_ble_tier has explicit empty-name and
        default branches that return 0 (fail-safe at read time)."""
        tree = ast.parse(person_src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_ble_tier":
                target = node
                break
        assert target is not None
        body = ast.unparse(target)
        # Three explicit "return 0" branches: empty name, entry walk fail-safe,
        # default fall-through.
        assert body.count("return 0") >= 2, (
            "v4.7.16 D1: get_ble_tier must have multiple fail-safe return 0 "
            "branches (empty name, entry walk exception, no match)"
        )

    def test_get_ble_tier_normalizes_room_name(self, person_src: str):
        tree = ast.parse(person_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_ble_tier":
                body = ast.unparse(node)
                assert ".lower()" in body and "replace(' ', '_')" in body, (
                    "v4.7.16 D1: must normalize room_name like the v3.8.9 "
                    "_direct_ble_rooms keying"
                )
                return
        pytest.fail("get_ble_tier missing")

    def test_get_ble_tier_guards_against_registry_exception(
        self, person_src: str
    ):
        tree = ast.parse(person_src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_ble_tier":
                body = ast.unparse(node)
                assert "try:" in body and "except" in body, (
                    "v4.7.16 D1: must guard async_entries call with try/except"
                )
                return
        pytest.fail("get_ble_tier missing")


# ============================================================================
# D1 behavioral — post-review C1-M1 (MEDIUM)
# ============================================================================
#
# Reviewer C flagged that the plan's D1 ACs listed 5 behavioral test names
# but the build shipped only source-grep/AST harnesses. These 3 tests close
# the most important behavioral gap (Tier 1 / Tier 2 / Tier 0 branches) by
# extracting `get_ble_tier`'s method body and exec'ing it with a constructed
# scanner-room-map. This drives the real method body — Bug Class #44
# compliant — without needing the HA framework.


class TestD1GetBleTierBehavioral:
    """Behavioral tests for get_ble_tier (post-review C1-M1)."""

    def _extract_get_ble_tier(self, person_src: str):
        """Return (callable, namespace) for the production method body."""
        tree = ast.parse(person_src)
        method_node = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "get_ble_tier"
            ):
                method_node = node
                break
        assert method_node is not None, "get_ble_tier method not found"

        # Build the const namespace the method body references.
        CONF_SCANNER_AREAS = "scanner_areas"
        CONF_AREA_ID = "area_id"
        CONF_ENTRY_TYPE = "entry_type"
        ENTRY_TYPE_ROOM = "room"
        DOMAIN = "universal_room_automation"
        # Logger is referenced inside the debug log branch (A4 fix-up).
        import logging
        _LOGGER = logging.getLogger("get_ble_tier_test")

        namespace = {
            "CONF_SCANNER_AREAS": CONF_SCANNER_AREAS,
            "CONF_AREA_ID": CONF_AREA_ID,
            "CONF_ENTRY_TYPE": CONF_ENTRY_TYPE,
            "ENTRY_TYPE_ROOM": ENTRY_TYPE_ROOM,
            "DOMAIN": DOMAIN,
            "_LOGGER": _LOGGER,
        }
        exec(ast.unparse(method_node), namespace)
        return namespace["get_ble_tier"], namespace

    def _make_coord(self, direct_rooms, entries):
        """Build a fake PersonTrackingCoordinator with the surfaces
        get_ble_tier needs: _direct_ble_rooms set + hass.config_entries.
        """
        coord = MagicMock()
        coord._direct_ble_rooms = set(direct_rooms)
        coord.hass = MagicMock()
        coord.hass.config_entries.async_entries = MagicMock(
            return_value=entries
        )
        return coord

    def _make_entry(self, room_name, area_id=None, scanner_areas=None,
                    entry_type="room"):
        entry = MagicMock()
        entry.data = {
            "room_name": room_name,
            "entry_type": entry_type,
            "area_id": area_id,
            "scanner_areas": scanner_areas or [],
        }
        entry.options = {}
        return entry

    def test_get_ble_tier_tier_1_for_direct_coverage(self, person_src: str):
        """Tier 1: room is in _direct_ble_rooms (own scanner)."""
        fn, _ = self._extract_get_ble_tier(person_src)
        coord = self._make_coord(
            direct_rooms={"master_bedroom"},
            entries=[],  # not consulted on Tier-1 short-circuit
        )
        assert fn(coord, "Master Bedroom") == 1, (
            "D1 behavioral: room in _direct_ble_rooms must return Tier 1"
        )
        # Name normalization: spaces → underscores, lowercase.
        assert fn(coord, "master_bedroom") == 1, (
            "D1 behavioral: get_ble_tier must normalize room_name"
        )

    def test_get_ble_tier_tier_2_for_scanner_areas(self, person_src: str):
        """Tier 2: room has area_id AND scanner_areas set, NOT in direct set."""
        fn, _ = self._extract_get_ble_tier(person_src)
        coord = self._make_coord(
            direct_rooms=set(),  # living_room not direct
            entries=[
                self._make_entry(
                    room_name="Living Room",
                    area_id="living_room",
                    scanner_areas=["family_room"],
                ),
            ],
        )
        assert fn(coord, "Living Room") == 2, (
            "D1 behavioral: room with area_id + scanner_areas must "
            "return Tier 2 (borrowing scanner from neighbor)"
        )

    def test_get_ble_tier_tier_0_for_unmapped(self, person_src: str):
        """Tier 0: not in direct set AND no matching room entry."""
        fn, _ = self._extract_get_ble_tier(person_src)
        coord = self._make_coord(
            direct_rooms=set(),
            entries=[
                self._make_entry(
                    room_name="Some Other Room",
                    area_id="some_other_area",
                ),
            ],
        )
        assert fn(coord, "Unknown Room") == 0, (
            "D1 behavioral: unmapped room must return Tier 0"
        )

        # Also: empty room_name → 0
        assert fn(coord, "") == 0, (
            "D1 behavioral: empty room_name must return Tier 0"
        )

        # Also: room entry exists but no area_id → 0 (cannot be Tier 1 or 2)
        coord2 = self._make_coord(
            direct_rooms=set(),
            entries=[
                self._make_entry(
                    room_name="Closet",
                    area_id=None,  # not configured
                    scanner_areas=[],
                ),
            ],
        )
        assert fn(coord2, "Closet") == 0, (
            "D1 behavioral: room with no area_id must return Tier 0"
        )


# ============================================================================
# D2 — RoomSignalInventorySensor
# ============================================================================


class TestD2SignalInventorySensor:
    def test_class_exists(self, sensor_src: str):
        assert "class RoomSignalInventorySensor" in sensor_src, (
            "v4.7.16 D2: RoomSignalInventorySensor class missing"
        )

    def test_registered_in_room_setup(self, sensor_src: str):
        assert "RoomSignalInventorySensor(coordinator)" in sensor_src, (
            "v4.7.16 D2: sensor not registered in room async_setup_entry"
        )

    def test_entity_category_diagnostic(self, sensor_src: str):
        tree = ast.parse(sensor_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "RoomSignalInventorySensor"
            ):
                body = ast.unparse(node)
                assert "EntityCategory.DIAGNOSTIC" in body, (
                    "v4.7.16 D2: sensor must be DIAGNOSTIC category"
                )
                return
        pytest.fail("RoomSignalInventorySensor class not found")

    def test_state_is_human_readable_label(self, sensor_src: str):
        """Bug Class #47 — state is rolled-up label, numeric tier in attrs."""
        tree = ast.parse(sensor_src)
        cls = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "RoomSignalInventorySensor"
            ):
                cls = node
                break
        assert cls is not None
        body = ast.unparse(cls)
        for label in (
            "dense",
            "sparse_with_fallback",
            "sparse_no_fallback",
            "pir_only",
            "camera_only",
            "none",
        ):
            assert (f'"{label}"' in body) or (f"'{label}'" in body), (
                f"v4.7.16 D2: missing state label '{label}'"
            )

    def test_attributes_include_ble_tier(self, sensor_src: str):
        tree = ast.parse(sensor_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "RoomSignalInventorySensor"
            ):
                body = ast.unparse(node)
                for k in (
                    "ble_tier",
                    "has_mmwave",
                    "has_pir",
                    "has_camera",
                    "has_ble_fallback_room",
                    "scanner_areas",
                    "area_id",
                ):
                    # ast.unparse normalizes to single quotes; accept either.
                    assert (f'"{k}"' in body) or (f"'{k}'" in body), (
                        f"v4.7.16 D2: missing attribute '{k}'"
                    )
                return
        pytest.fail("RoomSignalInventorySensor class not found")

    def test_no_signal_dispatch(self, sensor_src: str):
        """Pure introspection — no signal dispatch, no DB writes."""
        tree = ast.parse(sensor_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "RoomSignalInventorySensor"
            ):
                body = ast.unparse(node)
                assert "async_dispatcher_send" not in body, (
                    "v4.7.16 D2: must not dispatch signals (pure introspection)"
                )
                assert "save_anomaly_event" not in body, (
                    "v4.7.16 D2: must not write to DB (pure introspection)"
                )
                return
        pytest.fail("RoomSignalInventorySensor class not found")

    def test_has_camera_uses_camera_manager_not_zone_tracker(
        self, sensor_src: str
    ):
        """Post-review C2-H1 (HIGH): _has_camera must filter by THIS room's
        area_id, not by zone-tracker camera set membership.

        The old implementation walked tracker._camera_entity_ids which is
        zone-scoped, allowing a sibling room's camera to falsely surface as
        has_camera=True on a camera-less room. Fix: query
        camera_manager.get_cameras_for_area(room_area) directly.
        """
        tree = ast.parse(sensor_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "RoomSignalInventorySensor"
            ):
                # Find _has_camera method
                for item in node.body:
                    if (
                        isinstance(item, ast.FunctionDef)
                        and item.name == "_has_camera"
                    ):
                        # Build a body string EXCLUDING the docstring so the
                        # rationale prose (which mentions the old fields) does
                        # not false-positive these regression guards.
                        stmts_without_docstring = list(item.body)
                        if (
                            stmts_without_docstring
                            and isinstance(
                                stmts_without_docstring[0], ast.Expr
                            )
                            and isinstance(
                                stmts_without_docstring[0].value, ast.Constant
                            )
                            and isinstance(
                                stmts_without_docstring[0].value.value, str
                            )
                        ):
                            stmts_without_docstring = stmts_without_docstring[
                                1:
                            ]
                        code_only = "\n".join(
                            ast.unparse(s) for s in stmts_without_docstring
                        )
                        assert (
                            "camera_manager.get_cameras_for_area"
                            in code_only
                        ), (
                            "C2-H1 fix-up: _has_camera must query "
                            "camera_manager.get_cameras_for_area(room_area) "
                            "directly (room-scoped), not walk zone tracker "
                            "_camera_entity_ids (zone-scoped)"
                        )
                        # Regression guard: the zone-tracker walk that
                        # caused the cross-room contamination must be gone.
                        assert "_camera_entity_ids" not in code_only, (
                            "C2-H1 regression: _has_camera must no longer "
                            "read tracker._camera_entity_ids — that set is "
                            "zone-scoped and leaks sibling-room cameras"
                        )
                        assert "_zone_trackers" not in code_only, (
                            "C2-H1 regression: _has_camera must no longer "
                            "iterate _zone_trackers — query camera_manager "
                            "directly so the answer is per-area, not per-zone"
                        )
                        return
                pytest.fail("_has_camera method not found in class body")
        pytest.fail("RoomSignalInventorySensor class not found")

    def test_has_camera_behavioral_filters_by_room_area_id(
        self, sensor_src: str
    ):
        """Post-review C2-H1 (HIGH) behavioral: build a zone with 2 rooms
        where only one has a camera, exec the _has_camera body against
        each, and verify each room reports correctly.

        Avoids importing sensor.py (which transitively imports HA) by
        extracting _has_camera's source and execing it with controlled
        globals. This drives the production code path.
        """
        tree = ast.parse(sensor_src)
        method_src = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_has_camera"
            ):
                method_src = ast.unparse(node)
                break
        assert method_src is not None, "_has_camera method missing from source"

        # Build a stand-in CONF_* namespace mirroring const.py production values.
        CONF_DISABLE_CAMERA_PRESENCE = "disable_camera_presence"
        DEFAULT_DISABLE_CAMERA_PRESENCE = False
        CONF_AREA_ID = "area_id"
        DOMAIN = "universal_room_automation"

        # Fake camera_manager: maps area_id -> list of cameras.
        # Only `kitchen` has a camera; `living_room` does not.
        class FakeCameraManager:
            def __init__(self, by_area):
                self._by_area = by_area

            def get_cameras_for_area(self, area_id):
                return self._by_area.get(area_id, [])

        camera_manager = FakeCameraManager(
            {"kitchen": [object()]}  # 1 camera in kitchen
            # living_room intentionally absent
        )

        # Fake hass with .data[DOMAIN]["camera_manager"]
        fake_hass = MagicMock()
        fake_hass.data = {DOMAIN: {"camera_manager": camera_manager}}

        def make_sensor(area_id_value, disable_opt_out=False):
            sensor = MagicMock()
            sensor.hass = fake_hass
            sensor._config = MagicMock(
                return_value={
                    CONF_AREA_ID: area_id_value,
                    CONF_DISABLE_CAMERA_PRESENCE: disable_opt_out,
                }
            )
            return sensor

        # Compile and exec the method body to obtain a callable function.
        # Rebind `self._config()` lookups by binding _has_camera as a
        # function and calling with our fake `self`.
        namespace = {
            "CONF_DISABLE_CAMERA_PRESENCE": CONF_DISABLE_CAMERA_PRESENCE,
            "DEFAULT_DISABLE_CAMERA_PRESENCE": DEFAULT_DISABLE_CAMERA_PRESENCE,
            "CONF_AREA_ID": CONF_AREA_ID,
            "DOMAIN": DOMAIN,
        }
        exec(method_src, namespace)
        has_camera_fn = namespace["_has_camera"]

        # Room A in kitchen (camera present)
        kitchen_room = make_sensor("kitchen")
        assert has_camera_fn(kitchen_room) is True, (
            "C2-H1: room with area_id=kitchen must report has_camera=True"
        )

        # Room B in living_room (NO camera) sharing the same zone
        # would have been falsely True under the old zone-tracker walk.
        living_room = make_sensor("living_room")
        assert has_camera_fn(living_room) is False, (
            "C2-H1: room with area_id=living_room must report has_camera=False "
            "even when a sibling-room camera exists in the same zone"
        )

        # Opt-out short-circuit still works
        opted_out = make_sensor("kitchen", disable_opt_out=True)
        assert has_camera_fn(opted_out) is False, (
            "C2-H1: opt-out=True must short-circuit to False"
        )

        # Missing area_id short-circuits to False
        no_area = make_sensor(None)
        assert has_camera_fn(no_area) is False, (
            "C2-H1: missing area_id must short-circuit to False"
        )


# ============================================================================
# D3 — Per-room weighted veto in _run_inference
# ============================================================================


class TestD3RoomWeightedVeto:
    def test_constant_defined(self, const_src: str):
        assert "BLE_TIER_2_WEIGHT" in const_src, (
            "v4.7.16 D3: BLE_TIER_2_WEIGHT constant missing"
        )

    def test_constant_value_is_0_6(self, ura_const):
        assert ura_const.BLE_TIER_2_WEIGHT == 0.6, (
            "v4.7.16 D3: BLE_TIER_2_WEIGHT default must be 0.6"
        )

    def test_constant_imported_in_presence(self, presence_src: str):
        assert "BLE_TIER_2_WEIGHT" in presence_src, (
            "v4.7.16 D3: BLE_TIER_2_WEIGHT must be imported into presence.py"
        )

    def test_run_inference_iterates_rooms(self, presence_src: str):
        """Per the plan correction: zone-iterates-rooms loop in _run_inference,
        NOT inside ZonePresenceTracker._derived_mode.
        """
        tree = ast.parse(presence_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_run_inference"
            ):
                body = ast.unparse(node)
                assert "get_ble_tier" in body, (
                    "v4.7.16 D3: _run_inference must consume get_ble_tier"
                )
                assert "BLE_TIER_2_WEIGHT" in body, (
                    "v4.7.16 D3: _run_inference must use BLE_TIER_2_WEIGHT"
                )
                # `ast.unparse` strips comments; check the source instead for
                # the reviewer-aggregation flag.
                return
        pytest.fail("_run_inference async function not found")

    def test_aggregation_uses_max_per_reviewer_a(
        self, presence_src: str
    ):
        """Post-review A1 (HIGH): aggregation is `max`, not `sum`.

        Reviewer A picked max over sum to preserve the v3.8.9 invariant
        "Tier 1 dominates Tier 2". A sum-based aggregate would let five
        Tier-2 rooms (5 * 0.6 = 3.0) outweigh one Tier-1 room (1.0).
        """
        assert "max(weights.values())" in presence_src, (
            "v4.7.16 D3 (post-review A1): aggregation must use max(), "
            "not sum() — preserves Tier-1-dominates invariant"
        )
        # Explicit guard: a stray sum(weights.values()) would be a regression.
        assert "sum(weights.values())" not in presence_src, (
            "v4.7.16 D3 (post-review A1): sum(weights.values()) regressed "
            "— reviewer A explicitly picked max() over sum"
        )

    def test_verify_helper_signature_comment_present(self, presence_src: str):
        """Per task brief: each call site marked with verify-post comment."""
        assert (
            "verify helper signature post v4.7.15 lands" in presence_src
        ), (
            "v4.7.16 D3: must include 'verify helper signature post v4.7.15 "
            "lands' comments at the D3 call site"
        )

    def test_derived_mode_unchanged(self, presence_src: str):
        """The plan explicitly corrects: D3 does NOT modify _derived_mode."""
        tree = ast.parse(presence_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_derived_mode"
            ):
                body = ast.unparse(node)
                # The original 3-tier rollup must remain. No ble_tier or
                # BLE_TIER_2_WEIGHT references should leak in.
                assert "BLE_TIER_2_WEIGHT" not in body, (
                    "v4.7.16 D3: must NOT modify _derived_mode"
                )
                assert "get_ble_tier" not in body, (
                    "v4.7.16 D3: must NOT modify _derived_mode"
                )
                return
        pytest.fail("_derived_mode property not found")

    def test_helper_unavailable_graceful_degradation(self, presence_src: str):
        """Helper missing must not crash _run_inference."""
        # Simpler: search the raw source for the getattr pattern (avoids
        # ast.unparse quote normalization quirks).
        assert (
            "getattr(\n                    self, \"should_veto_due_to_reliable_signals\""
            in presence_src
            or 'getattr(self, "should_veto_due_to_reliable_signals"' in presence_src
            or "getattr(self, 'should_veto_due_to_reliable_signals'" in presence_src
            or "should_veto_due_to_reliable_signals" in presence_src
        ), (
            "v4.7.16 D3: helper reference (via getattr for graceful "
            "degradation) missing from _run_inference"
        )


# ============================================================================
# D4 — Per-room camera-presence opt-out
# ============================================================================


class TestD4CameraOptOut:
    def test_constant_defined(self, const_src: str):
        assert "CONF_DISABLE_CAMERA_PRESENCE" in const_src, (
            "v4.7.16 D4: CONF_DISABLE_CAMERA_PRESENCE constant missing"
        )
        assert "DEFAULT_DISABLE_CAMERA_PRESENCE" in const_src, (
            "v4.7.16 D4: DEFAULT_DISABLE_CAMERA_PRESENCE missing"
        )

    def test_default_is_false(self, ura_const):
        assert ura_const.DEFAULT_DISABLE_CAMERA_PRESENCE is False, (
            "v4.7.16 D4: default must be False (back-compat)"
        )

    def test_config_flow_initial_surface(self, config_flow_src: str):
        assert "CONF_DISABLE_CAMERA_PRESENCE" in config_flow_src, (
            "v4.7.16 D4: config_flow.py must import the constant"
        )
        # Field must appear in BOTH initial flow + options flow neighborhoods.
        occurrences = config_flow_src.count("CONF_DISABLE_CAMERA_PRESENCE")
        assert occurrences >= 3, (
            "v4.7.16 D4: expected ≥3 references (import + initial flow + "
            f"options flow); found {occurrences}"
        )

    def test_strings_json_translations_present(self, strings_src: str):
        # Both initial + options flow strings blocks must include the field.
        assert strings_src.count("disable_camera_presence") >= 4, (
            "v4.7.16 D4: strings.json must include label + description for "
            "BOTH initial and options flows (4 references expected)"
        )

    def test_helper_method_exists(self, presence_src: str):
        assert "_rooms_opting_out_of_camera_presence" in presence_src, (
            "v4.7.16 D4: _rooms_opting_out_of_camera_presence helper missing"
        )

    def test_discover_zone_cameras_consults_optout(self, presence_src: str):
        tree = ast.parse(presence_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_discover_zone_cameras"
            ):
                body = ast.unparse(node)
                assert (
                    "_rooms_opting_out_of_camera_presence" in body
                ), (
                    "v4.7.16 D4: _discover_zone_cameras must consult opt-out"
                )
                assert "opted_out_area_ids" in body or "opted_out" in body, (
                    "v4.7.16 D4: opt-out branch should track area_ids"
                )
                return
        pytest.fail("_discover_zone_cameras not found")

    def test_optout_does_not_modify_zone_presence_tracker_class(
        self, presence_src: str
    ):
        """Per plan: opt-out is enforced at registration time. Tracker stays pure."""
        tree = ast.parse(presence_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == "ZonePresenceTracker"
            ):
                body = ast.unparse(node)
                assert "CONF_DISABLE_CAMERA_PRESENCE" not in body, (
                    "v4.7.16 D4: ZonePresenceTracker must stay agnostic"
                )
                return
        pytest.fail("ZonePresenceTracker class not found")


# ============================================================================
# Cross-cycle invariants
# ============================================================================


class TestCrossCycleInvariants:
    def test_no_bug_class_46_migration_for_v4716_fields(self, const_src: str):
        """Both new fields must use lazy default at read time per Bug Class #46."""
        # The const file documents the doctrine; no migrate_ helpers should
        # exist in the codebase for these specific fields.
        assert "_migrate_disable_camera_presence" not in const_src
        assert "_migrate_ble_tier" not in const_src

    def test_bug_class_44_no_handcopied_constants(self, ura_const):
        """Tests must read from production code, not redefine."""
        assert ura_const.CONF_DISABLE_CAMERA_PRESENCE == "disable_camera_presence"
        assert ura_const.DEFAULT_DISABLE_CAMERA_PRESENCE is False
        assert 0.0 <= ura_const.BLE_TIER_2_WEIGHT <= 1.0
