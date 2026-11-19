"""Read-only generator for room_registry_live_2026_11_19.json.

Reads the live HA .storage (Samba mount) config entries + entity registry and
writes, per URA room entry: hashed entry_id, room_name, title, and the
registry entity_id for each URA room key. No secrets, no other options.

Run: python3 quality/tests/fixtures/_gen_room_registry_fixture.py
"""
import hashlib
import json
import os
import re
import sys

STORAGE = "/Users/okosisi/ha-config/.storage"
OUT = os.path.join(os.path.dirname(__file__), "room_registry_live_2026_11_19.json")
KEYS = {
    "occupied": "binary_sensor", "temperature": "sensor", "humidity": "sensor",
    "unavailable_entities": "sensor", "camera_person_detected": "binary_sensor",
    "automation": "switch", "ai_automation": "switch", "cover_automation": "switch",
    "manual_mode": "switch", "override_occupied": "switch", "override_vacant": "switch",
}


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "_", (t or "").lower()).strip("_")


def main():
    ce = json.load(open(f"{STORAGE}/core.config_entries"))["data"]["entries"]
    reg = json.load(open(f"{STORAGE}/core.entity_registry"))["data"]["entities"]
    by_uid = {
        e["unique_id"]: e["entity_id"] for e in reg
        if e.get("platform") == "universal_room_automation"
    }
    rooms = []
    for c in ce:
        if c["domain"] != "universal_room_automation":
            continue
        if (c.get("data") or {}).get("entry_type") != "room":
            continue
        merged = {**c["data"], **(c.get("options") or {})}
        eid = c["entry_id"]
        rooms.append({
            "entry_id": "room_" + hashlib.sha256(eid.encode()).hexdigest()[:12],
            "room_name": merged.get("room_name"),
            "title": c.get("title"),
            "entities": {k: by_uid.get(f"{eid}_{k}") for k in KEYS},
        })
    rooms.sort(key=lambda r: r["room_name"] or "")
    miss = [
        r["room_name"] for r in rooms
        if r["entities"]["occupied"] != f"binary_sensor.{_slug(r['room_name'])}_occupied"
    ]
    print(len(rooms), "rooms;", len(miss), "occupied slug misses:", miss, file=sys.stderr)
    with open(OUT, "w") as f:
        json.dump({
            "generated": "2026-11-19, read-only from .storage core.config_entries + "
                         "core.entity_registry; entry_id = sha256 prefix of the real id",
            "keys": KEYS,
            "rooms": rooms,
        }, f, indent=1, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
