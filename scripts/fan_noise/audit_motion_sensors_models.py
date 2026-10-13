#!/usr/bin/env python3
"""One-shot, read-only: URA room sensor lists x device-registry model.

PLANNING_fan_noise_running_rejection.md Rev 2, C2 (Finding 7) pre-ship
audit. Reads a HA ``.storage`` directory (core.config_entries,
core.entity_registry, core.device_registry) and, for every URA room entry,
joins each ``motion_sensors`` / ``presence_sensors`` entity to its device's
``model_id`` (fallback ``model``) and the sensor family from
``sensor_capability.FAMILY_BY_MODEL_ID``.

Flags every radar-family entity filed under ``motion_sensors`` (the
"radar filed as motion" case the C2 model-id safety net filters).

Usage:
    python3 scripts/fan_noise/audit_motion_sensors_models.py <storage_dir> [label]

Writes nothing; prints a Markdown table to stdout.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

_CAP = (
    Path(__file__).resolve().parents[2]
    / "custom_components/universal_room_automation/domain_coordinators"
    / "sensor_capability.py"
)


def _load_family_map() -> tuple[dict, set]:
    """Read FAMILY_BY_MODEL_ID / RADAR families out of the module source
    without importing HA (the module imports ..const)."""
    tree = ast.parse(_CAP.read_text())
    consts: dict = {}
    fam: dict = {}
    radar: set = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
            name = getattr(tgt, "id", None)
            val = node.value
            if name and name.startswith("SENSOR_FAMILY_") and isinstance(val, ast.Constant):
                consts[name] = val.value
            if name == "FAMILY_BY_MODEL_ID":
                for k, v in zip(val.keys, val.values):
                    fam[k.value] = consts[v.id]
            if name == "RADAR_SENSOR_FAMILIES":
                for elt in val.args[0].elts:
                    radar.add(consts[elt.id])
    return fam, radar


def _family(fam: dict, model_id, model) -> str:
    for key in (model_id, model):
        if key and key in fam:
            return fam[key]
    return "unknown"


def main(storage: str, label: str) -> int:
    base = Path(storage)
    entries = json.loads((base / "core.config_entries").read_text())["data"]["entries"]
    ents = json.loads((base / "core.entity_registry").read_text())["data"]["entities"]
    devs = json.loads((base / "core.device_registry").read_text())["data"]["devices"]
    dev_by_id = {d["id"]: d for d in devs}
    ent_by_id = {e["entity_id"]: e for e in ents}
    fam, radar = _load_family_map()

    rows = []
    for ce in entries:
        if ce.get("domain") != "universal_room_automation":
            continue
        data = {**(ce.get("data") or {}), **(ce.get("options") or {})}
        if data.get("entry_type") != "room":
            continue
        room = data.get("room_name") or ce.get("title")
        overrides = data.get("sensor_capabilities") or {}
        for role in ("motion_sensors", "presence_sensors"):
            for eid in data.get(role) or []:
                e = ent_by_id.get(eid)
                d = dev_by_id.get(e.get("device_id")) if e else None
                model_id = d.get("model_id") if d else None
                model = d.get("model") if d else None
                manu = d.get("manufacturer") if d else None
                family = _family(fam, model_id, model)
                ov = (overrides.get(eid) or {}).get("kind")
                flag = ""
                if role == "motion_sensors" and family in radar:
                    flag = "RADAR-FILED-AS-MOTION"
                if e is None:
                    flag = (flag + " NOT-IN-REGISTRY").strip()
                rows.append((room, role, eid, manu, model_id, model, family, ov or "", flag))

    rows.sort()
    print(f"### {label}\n")
    print("| Room | List | Entity | Manufacturer | model_id | model | Family | Override kind | Flag |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(str(x) if x not in (None, "") else "–" for x in r) + " |")
    flagged = [r for r in rows if "RADAR-FILED-AS-MOTION" in r[8]]
    print(f"\nRooms: {len({r[0] for r in rows})}; entities: {len(rows)}; "
          f"radar-filed-as-motion: {len(flagged)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]))
