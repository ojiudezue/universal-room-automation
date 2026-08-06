#!/usr/bin/env python3
"""Golden-master diff: legacy census cross-platform resolution vs CameraResolver.

Flip prerequisite for CENSUS_USE_NEW_RESOLVER (camera_resolver.py:92,
README_v5.45.0.md "What ships DARK"). Runs the REAL production code for both
paths — `CameraIntegrationManager.resolve_cross_platform_sensors` with the
cutover flag forced False (legacy) and True (new resolver) — against a
snapshot of the live HA entity/device registries and the live integration
camera lists, entirely offline and read-only.

Usage:
    python3 scripts/probes/golden_master_census_diff.py \
        --entity-registry <core.entity_registry.json> \
        --device-registry <core.device_registry.json> \
        [--activity <activity.json>]

Snapshot capture (read-only):
    ssh ha "cat /config/.storage/core.entity_registry" > core.entity_registry.json
    ssh ha "cat /config/.storage/core.device_registry" > core.device_registry.json

Activity capture (optional; 7-day person-sensor ON-transition counts from the
HA recorder DB, read-only):
    python3 scripts/probes/golden_master_census_diff.py --emit-activity-script

The live camera lists below were read from the URA integration config entry
(.storage/core.config_entries) on 2026-08-06. Re-read them before re-running
after any config change.
"""
from __future__ import annotations

import argparse
import json
import sys
import types
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Live integration-entry camera lists (captured 2026-08-06 from
# .storage/core.config_entries, entry_type=integration). These are the ONLY
# inputs the flag-gated call sites feed to resolve_cross_platform_sensors
# (camera_census.py get_transit_interior_entities / get_transit_egress_entities).
CAMERA_LISTS: dict[str, list[str]] = {
    "interior (CONF_CAMERA_PERSON_ENTITIES)": [
        "camera.playroom_high_resolution_channel",
        "camera.master_hallway",
        "camera.staircase_high_resolution_channel",
        "camera.playroom",
        "camera.foyer_fisheye",
        "camera.family_room",
        "camera.family_room_high_resolution_channel",
        "camera.foyer_fisheye_high_resolution_channel",
        "camera.master_hallway_high_resolution_channel",
    ],
    "egress (CONF_EGRESS_CAMERAS)": [
        "camera.madrone_g6_entry",
        "camera.doorbell_lite",
        "camera.front_door_aerial",
    ],
}

ACTIVITY_SCRIPT = r"""
# Run ON the HA box (read-only recorder query), e.g.:
#   ssh ha "python3 -" < /tmp/activity.py > activity.json
import json, sqlite3, time
con = sqlite3.connect("file:/config/home-assistant_v2.db?mode=ro", uri=True)
cutoff = time.time() - 7 * 86400
rows = con.execute(
    "SELECT m.entity_id, COUNT(*) FROM states s "
    "JOIN states_meta m ON s.metadata_id = m.metadata_id "
    "WHERE s.last_updated_ts > ? AND s.state = 'on' AND ("
    "  m.entity_id LIKE 'binary_sensor.%person_occupancy' OR"
    "  m.entity_id LIKE 'binary_sensor.%person_detected' OR"
    "  m.entity_id LIKE 'binary_sensor.%_person') "
    "GROUP BY m.entity_id", (cutoff,)).fetchall()
print(json.dumps(dict(rows), indent=1))
"""


# ---------------------------------------------------------------------------
# Duck-typed registry fakes backed by the .storage snapshots. Attribute names
# mirror homeassistant RegistryEntry / DeviceEntry exactly for the fields the
# two resolution paths read.
# ---------------------------------------------------------------------------

class FakeEntityEntry:
    def __init__(self, raw: dict) -> None:
        self.entity_id = raw["entity_id"]
        self.device_id = raw.get("device_id")
        self.platform = raw.get("platform")
        self.area_id = raw.get("area_id")
        self.disabled_by = raw.get("disabled_by")
        # Faithful to RegistryEntry: .name is the USER override (often None);
        # .original_name is the integration-provided name.
        self.name = raw.get("name")
        self.original_name = raw.get("original_name")
        self.domain = self.entity_id.split(".", 1)[0]


class FakeEntityRegistry:
    def __init__(self, path: Path) -> None:
        data = json.loads(path.read_text())
        self.entities: dict[str, FakeEntityEntry] = {}
        for raw in data["data"]["entities"]:
            e = FakeEntityEntry(raw)
            self.entities[e.entity_id] = e
        # Deleted entities are NOT in .entities (matches production).

    def async_get(self, entity_id: str) -> FakeEntityEntry | None:
        return self.entities.get(entity_id)


class FakeDeviceEntry:
    def __init__(self, raw: dict) -> None:
        self.id = raw["id"]
        self.identifiers = {tuple(i) for i in raw.get("identifiers", []) if len(i) == 2}
        self.connections = {tuple(c) for c in raw.get("connections", []) if len(c) == 2}
        self.name = raw.get("name")


class FakeDeviceRegistry:
    def __init__(self, path: Path) -> None:
        data = json.loads(path.read_text())
        self.devices: dict[str, FakeDeviceEntry] = {}
        for raw in data["data"]["devices"]:
            d = FakeDeviceEntry(raw)
            self.devices[d.id] = d

    def async_get(self, device_id: str) -> FakeDeviceEntry | None:
        return self.devices.get(device_id)


def _install_ha_stubs(ent_reg: FakeEntityRegistry, dev_reg: FakeDeviceRegistry) -> None:
    """Install minimal homeassistant module stubs so the REAL camera_census
    module imports and runs against the snapshot registries (Bug Class #62
    discipline: exercise the production module, not a reimplementation)."""

    def _mod(name: str) -> types.ModuleType:
        m = sys.modules.get(name)
        if m is None:
            m = types.ModuleType(name)
            sys.modules[name] = m
        return m

    ha = _mod("homeassistant")
    core = _mod("homeassistant.core")
    core.HomeAssistant = object
    helpers = _mod("homeassistant.helpers")
    er_mod = _mod("homeassistant.helpers.entity_registry")
    er_mod.async_get = lambda hass: ent_reg
    dr_mod = _mod("homeassistant.helpers.device_registry")
    dr_mod.async_get = lambda hass: dev_reg

    def format_mac(mac: str) -> str:
        """Verbatim logic of homeassistant.helpers.device_registry.format_mac."""
        to_test = mac
        if len(to_test) == 17 and to_test.count(":") == 5:
            return to_test.lower()
        if len(to_test) == 17 and to_test.count("-") == 5:
            to_test = to_test.replace("-", "")
        elif len(to_test) == 14 and to_test.count(".") == 2:
            to_test = to_test.replace(".", "")
        if len(to_test) == 12:
            return ":".join(to_test.lower()[i : i + 2] for i in range(0, 12, 2))
        return mac

    dr_mod.format_mac = format_mac
    util = _mod("homeassistant.util")
    dt_mod = _mod("homeassistant.util.dt")
    dt_mod.now = datetime.now
    dt_mod.utcnow = datetime.utcnow
    util.dt = dt_mod
    helpers.entity_registry = er_mod
    helpers.device_registry = dr_mod
    ha.core = core
    ha.helpers = helpers
    ha.util = util


def _run_path(use_new: bool, camera_lists: dict[str, list[str]]):
    """Run resolve_cross_platform_sensors with the cutover flag forced."""
    # Import the component modules under a synthetic package so the package
    # __init__.py (which imports the full HA framework) is NOT executed —
    # camera_census/camera_resolver/const only need the stubs installed above.
    import importlib
    pkg_name = "ura_gm_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(REPO_ROOT / "custom_components" / "universal_room_automation")]
        sys.modules[pkg_name] = pkg
    camera_resolver = importlib.import_module(f"{pkg_name}.camera_resolver")
    CameraIntegrationManager = importlib.import_module(
        f"{pkg_name}.camera_census"
    ).CameraIntegrationManager

    saved = camera_resolver.CENSUS_USE_NEW_RESOLVER
    camera_resolver.CENSUS_USE_NEW_RESOLVER = use_new
    try:
        hass = types.SimpleNamespace(
            states=types.SimpleNamespace(get=lambda eid: None)
        )
        out: dict[str, list[dict]] = {}
        for label, cams in camera_lists.items():
            mgr = CameraIntegrationManager(hass)  # fresh (device cache empty)
            infos = mgr.resolve_cross_platform_sensors(list(cams))
            out[label] = [
                {
                    "entity_id": i.entity_id,
                    "platform": i.platform,
                    "person_binary_sensor": i.person_binary_sensor,
                    "person_count_sensor": i.person_count_sensor,
                    "area_id": i.area_id,
                }
                for i in infos
            ]
        return out
    finally:
        camera_resolver.CENSUS_USE_NEW_RESOLVER = saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity-registry", type=Path)
    ap.add_argument("--device-registry", type=Path)
    ap.add_argument("--activity", type=Path, help="JSON {entity_id: 7d on-count}")
    ap.add_argument("--emit-activity-script", action="store_true")
    args = ap.parse_args()

    if args.emit_activity_script:
        print(ACTIVITY_SCRIPT)
        return 0
    if not args.entity_registry or not args.device_registry:
        ap.error("--entity-registry and --device-registry are required")

    ent_reg = FakeEntityRegistry(args.entity_registry)
    dev_reg = FakeDeviceRegistry(args.device_registry)
    _install_ha_stubs(ent_reg, dev_reg)

    legacy = _run_path(False, CAMERA_LISTS)
    new = _run_path(True, CAMERA_LISTS)

    activity: dict[str, int] = {}
    if args.activity:
        activity = json.loads(args.activity.read_text())

    total = identical = differing = 0
    for label in CAMERA_LISTS:
        l_rows = legacy[label]
        n_rows = new[label]
        # Compare on the census-consumed surface: the set of person
        # binary_sensors (what _is_entity_on iterates) + their count sensors.
        l_person = {r["person_binary_sensor"] for r in l_rows if r["person_binary_sensor"]}
        n_person = {r["person_binary_sensor"] for r in n_rows if r["person_binary_sensor"]}
        l_counts = {r["person_count_sensor"] for r in l_rows if r["person_count_sensor"]}
        n_counts = {r["person_count_sensor"] for r in n_rows if r["person_count_sensor"]}
        union = l_person | n_person
        print(f"\n=== {label} ===")
        print(f"legacy person sensors : {len(l_person)}")
        print(f"resolver person sensors: {len(n_person)}")
        for eid in sorted(union):
            in_l, in_n = eid in l_person, eid in n_person
            total += 1
            act = activity.get(eid, "n/a")
            if in_l == in_n:
                identical += 1
                # platform label comparison for shared entities
                lp = next(r["platform"] for r in l_rows if r["person_binary_sensor"] == eid)
                np_ = next(r["platform"] for r in n_rows if r["person_binary_sensor"] == eid)
                flag = "" if lp == np_ else f"  PLATFORM-DIFF legacy={lp} new={np_}"
                print(f"  BOTH   {eid}  (7d_on={act}){flag}")
            else:
                differing += 1
                side = "LEGACY-ONLY" if in_l else "RESOLVER-ONLY"
                print(f"  {side}  {eid}  (7d_on={act})")
        c_union = l_counts | n_counts
        for cid in sorted(c_union):
            in_l, in_n = cid in l_counts, cid in n_counts
            total += 1
            if in_l == in_n:
                identical += 1
                print(f"  BOTH   {cid}  [count]")
            else:
                differing += 1
                side = "LEGACY-ONLY" if in_l else "RESOLVER-ONLY"
                print(f"  {side}  {cid}  [count]")

    print(f"\nTOTAL compared={total} identical={identical} differing={differing}")
    print(json.dumps({"legacy": legacy, "new": new}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
