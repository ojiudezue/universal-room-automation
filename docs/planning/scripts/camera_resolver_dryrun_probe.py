"""CameraResolver D0 dry-run probe (read-only).

Reads live HA registries from the Samba-mounted ~/ha-config/.storage/
and produces the full derived camera pairing table for the room-camera
fusion cycle (docs/planning/PLANNING_room_camera_fusion.md §Amendment
2026-08-01 test battery item #5).

- No HA import, no live network calls, no writes.
- Outputs a Markdown table + JSON dump to stdout.
- Consumed by docs/planning/AUDIT_camera_resolver_pairing_dryrun.md.

Usage:
    python3 docs/planning/scripts/camera_resolver_dryrun_probe.py \\
        > docs/planning/AUDIT_camera_resolver_pairing_dryrun.raw.md
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

STORAGE = Path(os.path.expanduser("~/ha-config/.storage"))
ENTITY_REG = STORAGE / "core.entity_registry"
DEVICE_REG = STORAGE / "core.device_registry"
CONFIG_ENTRIES = STORAGE / "core.config_entries"
RESTORE_STATE = STORAGE / "core.restore_state"

# --- Hand-built acceptance fixture (from operator CM config, 2026-08-01) ---
FIXTURE_INTERIOR = [
    "camera.playroom_high_resolution_channel",
    "camera.master_hallway",
    "camera.staircase_high_resolution_channel",
    "camera.playroom",
    "camera.foyer_fisheye",
    "camera.family_room",
    "camera.family_room_high_resolution_channel",
    "camera.foyer_fisheye_high_resolution_channel",
    "camera.master_hallway_high_resolution_channel",
]
FIXTURE_EGRESS = [
    "camera.madrone_g6_entry",
    "camera.doorbell_lite",
    "camera.front_door_aerial",
]
FIXTURE_PERIMETER = [
    "camera.reolinkstudybporchptz",
    "camera.rear_ptz_high_resolution_channel",
    "camera.utilities_ptz_high_resolution_channel",
    "camera.front_side_ptz",
    "camera.armcrest",
    "camera.hot_tub",
    "camera.pool_equipment",
    "camera.g5_bullet",
    "camera.back_yard",
]
CAMERA_PLATFORMS = {"frigate", "unifiprotect", "reolink", "amcrest", "dahua"}

# Person / face / count / motion patterns
PERSON_BS_SUFFIXES = ("_person_occupancy", "_person_detected", "_person")
FACE_BS_PATTERNS = ("face_detected", "_face", "face_recognized")
COUNT_SENSOR_SUFFIX = "_person_count"
PERSON_SWITCH_PATTERNS = (
    "_detections_person",  # UniFi Protect
    "_person_detection",   # Reolink / Amcrest
    "_smart_detect_person",
)
FACE_SWITCH_PATTERNS = (
    "_detections_face",
    "_face_detection",
)
MOTION_BS_SUFFIXES = ("_motion", "_motion_detected", "_any_motion_detected")


def load_json(p: Path) -> dict:
    with p.open() as fh:
        return json.load(fh)


def build_indexes():
    er = load_json(ENTITY_REG)["data"]["entities"]
    dr = load_json(DEVICE_REG)["data"]["devices"]

    entities_by_device: dict[str, list[dict]] = defaultdict(list)
    entity_by_id: dict[str, dict] = {}
    for e in er:
        if e.get("device_id"):
            entities_by_device[e["device_id"]].append(e)
        entity_by_id[e["entity_id"]] = e

    device_by_id: dict[str, dict] = {d["id"]: d for d in dr}
    mac_to_devices: dict[str, list[str]] = defaultdict(list)
    identifier_to_devices: dict[tuple, list[str]] = defaultdict(list)
    for d in dr:
        for conn in d.get("connections", []) or []:
            if conn and len(conn) == 2 and conn[0] == "mac":
                mac_to_devices[conn[1].lower()].append(d["id"])
        for iden in d.get("identifiers", []) or []:
            if iden and len(iden) == 2:
                identifier_to_devices[tuple(iden)].append(d["id"])

    return {
        "entities": er,
        "devices": dr,
        "entities_by_device": entities_by_device,
        "entity_by_id": entity_by_id,
        "device_by_id": device_by_id,
        "mac_to_devices": mac_to_devices,
        "identifier_to_devices": identifier_to_devices,
    }


def device_platforms(idx, device_id: str) -> set[str]:
    """Platforms owning entities on this device."""
    return {e.get("platform") for e in idx["entities_by_device"].get(device_id, [])
            if e.get("platform")}


def device_macs(idx, device_id: str) -> list[str]:
    d = idx["device_by_id"].get(device_id, {})
    return [c[1].lower() for c in (d.get("connections") or []) if c and c[0] == "mac"]


def extract_stem(entity_id: str) -> str | None:
    if "." not in entity_id:
        return None
    name = entity_id.split(".", 1)[1]
    # strip channel suffix
    name = re.sub(r"_high_resolution_channel$", "", name)
    name = re.sub(r"_low_resolution_channel$", "", name)
    for suf in ("_person_occupancy", "_person_detected", "_person_count", "_person",
                "_face_detected", "_smart_detect_person",
                "_detections_person", "_person_detection",
                "_fisheye", "_2"):
        if name.endswith(suf):
            name = name[: -len(suf)]
            break
    return name or None


def find_person_sensors_on_device(idx, device_id: str) -> dict:
    """Return dict of person_bs / face_bs / person_count / person_switch / face_switch entity_ids on a device."""
    out = {"person_bs": [], "face_bs": [], "person_count": [], "person_switch": [], "face_switch": [], "motion_bs": []}
    for e in idx["entities_by_device"].get(device_id, []):
        eid = e["entity_id"]
        domain = eid.split(".", 1)[0]
        if e.get("disabled_by"):
            continue
        if domain == "binary_sensor":
            if any(eid.endswith(s) for s in PERSON_BS_SUFFIXES):
                out["person_bs"].append(eid)
            elif any(p in eid for p in FACE_BS_PATTERNS):
                out["face_bs"].append(eid)
            elif any(eid.endswith(s) for s in MOTION_BS_SUFFIXES):
                out["motion_bs"].append(eid)
        elif domain == "sensor" and eid.endswith(COUNT_SENSOR_SUFFIX):
            out["person_count"].append(eid)
        elif domain == "switch":
            if any(p in eid for p in PERSON_SWITCH_PATTERNS):
                out["person_switch"].append(eid)
            elif any(p in eid for p in FACE_SWITCH_PATTERNS):
                out["face_switch"].append(eid)
    return out


def resolve_via_ladder(idx, camera_entity_id: str) -> dict:
    """Apply the correlation ladder OFFLINE."""
    result = {
        "input_entity": camera_entity_id,
        "rung": None,             # 'same_device' | 'mac' | 'identifiers' | 'name_stem' | 'unmatchable'
        "confidence": None,       # 'certain' | 'likely' | 'ambiguous' | 'unmatchable'
        "primary_device_id": None,
        "primary_device_name": None,
        "primary_platform": None,
        "sibling_devices": [],    # list of {device_id, name, platform, basis}
        "sensors": {},            # merged
        "notes": [],
    }

    ent = idx["entity_by_id"].get(camera_entity_id)
    if ent is None:
        result["rung"] = "unmatchable"
        result["confidence"] = "unmatchable"
        result["notes"].append("entity not in registry")
        return result
    dev_id = ent.get("device_id")
    if not dev_id:
        result["rung"] = "unmatchable"
        result["confidence"] = "unmatchable"
        result["notes"].append("entity has no device_id")
        return result
    dev = idx["device_by_id"].get(dev_id, {})
    result["primary_device_id"] = dev_id
    result["primary_device_name"] = dev.get("name") or dev.get("name_by_user")
    plats = device_platforms(idx, dev_id)
    result["primary_platform"] = ",".join(sorted(plats)) or "unknown"

    # Rung 1: same-device
    same = find_person_sensors_on_device(idx, dev_id)
    merged = {k: list(v) for k, v in same.items()}
    if any(same[k] for k in ("person_bs", "person_count")):
        result["rung"] = "same_device"
        result["confidence"] = "certain"

    # Rung 2: MAC match to sibling devices (different platform, same physical camera)
    macs = device_macs(idx, dev_id)
    mac_siblings: list[str] = []
    for mac in macs:
        for sib in idx["mac_to_devices"].get(mac, []):
            if sib == dev_id:
                continue
            sib_plats = device_platforms(idx, sib)
            if sib_plats & CAMERA_PLATFORMS:
                mac_siblings.append(sib)
    mac_siblings = list(dict.fromkeys(mac_siblings))
    for sib in mac_siblings:
        sib_dev = idx["device_by_id"].get(sib, {})
        s = find_person_sensors_on_device(idx, sib)
        for k in merged:
            merged[k].extend(x for x in s[k] if x not in merged[k])
        result["sibling_devices"].append({
            "device_id": sib,
            "name": sib_dev.get("name") or sib_dev.get("name_by_user"),
            "platform": ",".join(sorted(device_platforms(idx, sib))),
            "basis": "mac",
            "shared_macs": [m for m in macs if m in [c[1].lower() for c in (sib_dev.get("connections") or []) if c and c[0]=="mac"]],
        })

    # Rung 3: identifiers overlap (rare cross-integration, but check)
    id_siblings: list[str] = []
    for iden in dev.get("identifiers", []) or []:
        if not iden or len(iden) != 2:
            continue
        # identifiers are integration-scoped; look for identical (integration, value)
        # AND for cross-integration overlap via the value part alone
        val = iden[1]
        for other_key, other_devs in idx["identifier_to_devices"].items():
            if other_key[1] != val:
                continue
            for od in other_devs:
                if od == dev_id or od in mac_siblings or od in id_siblings:
                    continue
                if device_platforms(idx, od) & CAMERA_PLATFORMS:
                    id_siblings.append(od)
                    result["sibling_devices"].append({
                        "device_id": od,
                        "name": idx["device_by_id"].get(od, {}).get("name"),
                        "platform": ",".join(sorted(device_platforms(idx, od))),
                        "basis": "identifiers",
                        "shared_identifier_value": val,
                    })
                    s = find_person_sensors_on_device(idx, od)
                    for k in merged:
                        merged[k].extend(x for x in s[k] if x not in merged[k])

    if mac_siblings and not result["rung"]:
        result["rung"] = "mac"
        result["confidence"] = "certain"
    elif mac_siblings:
        # already rung 1; note MAC augmented
        result["notes"].append(f"MAC-augmented +{len(mac_siblings)} sibling device(s)")

    # Rung 4: name-stem heuristic across ALL camera-platform entities
    stem = extract_stem(camera_entity_id)
    stem_matches: list[dict] = []
    if stem:
        # Search for sibling person/face/count sensors that share the stem prefix
        for e in idx["entities"]:
            eid = e["entity_id"]
            if e.get("disabled_by"):
                continue
            if e.get("platform") not in CAMERA_PLATFORMS:
                continue
            other_dev = e.get("device_id")
            if other_dev == dev_id or other_dev in mac_siblings or other_dev in id_siblings:
                continue
            name = eid.split(".", 1)[1] if "." in eid else eid
            if not name.startswith(stem):
                continue
            # Match on our sensor patterns
            is_person = (eid.split(".",1)[0] == "binary_sensor" and any(name.endswith(s) for s in PERSON_BS_SUFFIXES))
            is_count = eid.endswith(COUNT_SENSOR_SUFFIX)
            is_face = any(p in eid for p in FACE_BS_PATTERNS)
            is_pswitch = eid.split(".",1)[0] == "switch" and any(p in eid for p in PERSON_SWITCH_PATTERNS)
            is_fswitch = eid.split(".",1)[0] == "switch" and any(p in eid for p in FACE_SWITCH_PATTERNS)
            if not any([is_person, is_count, is_face, is_pswitch, is_fswitch]):
                continue
            stem_matches.append({"entity_id": eid, "device_id": other_dev, "platform": e.get("platform")})
            if is_person and eid not in merged["person_bs"]: merged["person_bs"].append(eid)
            if is_count and eid not in merged["person_count"]: merged["person_count"].append(eid)
            if is_face and eid not in merged["face_bs"]: merged["face_bs"].append(eid)
            if is_pswitch and eid not in merged["person_switch"]: merged["person_switch"].append(eid)
            if is_fswitch and eid not in merged["face_switch"]: merged["face_switch"].append(eid)
    if stem_matches and not result["rung"]:
        result["rung"] = "name_stem"
        result["confidence"] = "likely"
    elif stem_matches:
        result["notes"].append(f"stem '{stem}' added {len(stem_matches)} more sensor(s) from other camera devices")
    # record stem sibling devices
    stem_devs_seen = set()
    for sm in stem_matches:
        d2 = sm["device_id"]
        if not d2 or d2 in stem_devs_seen: continue
        stem_devs_seen.add(d2)
        if any(s["device_id"] == d2 for s in result["sibling_devices"]):
            continue
        result["sibling_devices"].append({
            "device_id": d2,
            "name": idx["device_by_id"].get(d2, {}).get("name"),
            "platform": ",".join(sorted(device_platforms(idx, d2))),
            "basis": "name_stem",
            "stem": stem,
        })

    if not result["rung"]:
        # No sensors on same device, no MAC siblings, no stem siblings
        result["rung"] = "unmatchable"
        result["confidence"] = "unmatchable"
        result["notes"].append("no person/face/count sensors reachable via any rung — operator declaration required")
    result["sensors"] = merged

    # Ambiguity check: multiple non-MAC candidate siblings with different stems
    stems_seen = {extract_stem(s.get("stem") or s.get("device_id") or "") for s in result["sibling_devices"] if s["basis"] == "name_stem"}
    if len(stem_devs_seen) > 3:
        result["confidence"] = "ambiguous"
        result["notes"].append(f"{len(stem_devs_seen)} name-stem siblings — verify no over-collection")

    return result


def enumerate_switches(idx) -> dict:
    """D4 auto-enable probe: person / face detection switches per platform."""
    inv = defaultdict(list)
    for e in idx["entities"]:
        if e.get("disabled_by"):
            continue
        eid = e["entity_id"]
        if not eid.startswith("switch."):
            continue
        plat = e.get("platform") or ""
        if any(p in eid for p in PERSON_SWITCH_PATTERNS):
            inv[(plat, "person")].append(eid)
        elif any(p in eid for p in FACE_SWITCH_PATTERNS):
            inv[(plat, "face")].append(eid)
    return dict(inv)


def read_restore_states(entity_ids: set[str]) -> dict[str, str]:
    """Read last-known state from core.restore_state (best-effort)."""
    if not RESTORE_STATE.exists():
        return {}
    try:
        data = load_json(RESTORE_STATE)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for row in data.get("data", []):
        st = (row.get("state") or {})
        eid = st.get("entity_id")
        if eid in entity_ids:
            out[eid] = st.get("state", "?")
    return out


# ------------------------------- MAIN ------------------------------- #

def main() -> None:
    idx = build_indexes()

    # 1. Enumerate all camera devices
    all_camera_devices = []
    for d in idx["devices"]:
        plats = device_platforms(idx, d["id"])
        cam_plats = plats & CAMERA_PLATFORMS
        if cam_plats:
            all_camera_devices.append({
                "device_id": d["id"],
                "name": d.get("name_by_user") or d.get("name"),
                "platforms": sorted(cam_plats),
                "macs": device_macs(idx, d["id"]),
                "identifiers": d.get("identifiers", []),
                "via_device_id": d.get("via_device_id"),
            })

    # 2. Apply ladder to every configured interior/egress/perimeter camera
    all_fixture = [(cid, "interior") for cid in FIXTURE_INTERIOR] \
                + [(cid, "egress") for cid in FIXTURE_EGRESS] \
                + [(cid, "perimeter") for cid in FIXTURE_PERIMETER]
    resolutions = []
    for cid, category in all_fixture:
        r = resolve_via_ladder(idx, cid)
        r["category"] = category
        resolutions.append(r)

    # 3. Fixture diff (interior only per the acceptance fixture in operator config)
    fixture_diff = []
    for r in resolutions:
        if r["category"] != "interior":
            continue
        exp_person_bs = f"binary_sensor.{r['input_entity'].split('.',1)[1]}_person_occupancy"
        actual = r["sensors"].get("person_bs", [])
        agree = any(a == exp_person_bs or a.startswith("binary_sensor." + extract_stem(r["input_entity"]) or "") for a in actual) if actual else False
        fixture_diff.append({
            "camera": r["input_entity"],
            "expected_person_bs_stem": extract_stem(r["input_entity"]),
            "actual_person_bs": actual,
            "actual_face_bs": r["sensors"].get("face_bs", []),
            "actual_person_count": r["sensors"].get("person_count", []),
            "rung": r["rung"],
            "confidence": r["confidence"],
            "agreement": "AGREE" if agree else "DISAGREE",
        })

    # 4. Switch inventory
    switches = enumerate_switches(idx)
    all_switch_eids = set()
    for eids in switches.values():
        all_switch_eids.update(eids)
    switch_states = read_restore_states(all_switch_eids)

    # Per-rung counts (interior only)
    rung_counts = defaultdict(int)
    conf_counts = defaultdict(int)
    for r in resolutions:
        if r["category"] == "interior":
            rung_counts[r["rung"]] += 1
            conf_counts[r["confidence"]] += 1

    out = {
        "generated_at": "PROBE_RUN",
        "counts": {
            "camera_devices_total": len(all_camera_devices),
            "camera_devices_by_platform": {
                p: sum(1 for d in all_camera_devices if p in d["platforms"])
                for p in sorted(CAMERA_PLATFORMS)
            },
            "fixture_interior": len(FIXTURE_INTERIOR),
            "fixture_egress": len(FIXTURE_EGRESS),
            "fixture_perimeter": len(FIXTURE_PERIMETER),
            "interior_rung": dict(rung_counts),
            "interior_confidence": dict(conf_counts),
        },
        "camera_devices": all_camera_devices,
        "resolutions": resolutions,
        "fixture_diff": fixture_diff,
        "switches_per_platform": {f"{k[0]}/{k[1]}": v for k, v in switches.items()},
        "switch_states_restore": switch_states,
    }
    json.dump(out, sys.stdout, indent=2, default=str)


if __name__ == "__main__":
    main()
