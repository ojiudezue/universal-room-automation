#!/usr/bin/env python3
"""Planning-time audit — substrate CONF-list coverage per room.

Run this script during cycle scoping to enumerate every configured ROOM
config entry and report whether it has at least one Tier-1 occupancy
sensor in its curated CONF lists (CONF_MOTION_SENSORS /
CONF_MMWAVE_SENSORS / CONF_OCCUPANCY_SENSORS).

This is a **planning-time informational tool**, NOT a deploy gate (per
operator decision 2026-06-05 in
``docs/planning/PLANNING_occupancy_substrate_unification.md`` D5). Rooms
with empty CONF lists degenerate gracefully to no-Tier-1 substrate
coverage post-deploy and the substrate emits an INFO-once log at
runtime; this script lets the operator decide which rooms to curate
BEFORE deploy.

Usage:

    python3 quality/scripts/audit_substrate_conf_coverage.py \\
        /path/to/.storage/core.config_entries

The argument is the HA core.config_entries JSON dump (read-only). Output
is a per-room table to stdout and an exit code 0 — informational only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List


# Constants mirror custom_components.universal_room_automation.const
# without importing the package — keeps this script standalone and
# runnable outside the HA test environment.
DOMAIN = "universal_room_automation"
CONF_ENTRY_TYPE = "entry_type"
CONF_ROOM_NAME = "room_name"
CONF_MOTION_SENSORS = "motion_sensors"
CONF_MMWAVE_SENSORS = "presence_sensors"
CONF_OCCUPANCY_SENSORS = "occupancy_sensors"
ENTRY_TYPE_ROOM = "room"


def _load_entries(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as fh:
        blob = json.load(fh)
    raw_entries = blob.get("data", {}).get("entries", [])
    return [e for e in raw_entries if e.get("domain") == DOMAIN]


def _coverage_for_entry(entry: dict) -> Dict[str, int]:
    data = entry.get("data", {}) or {}
    options = entry.get("options", {}) or {}
    merged = {**data, **options}
    return {
        "motion": len(merged.get(CONF_MOTION_SENSORS, []) or []),
        "mmwave": len(merged.get(CONF_MMWAVE_SENSORS, []) or []),
        "occupancy": len(merged.get(CONF_OCCUPANCY_SENSORS, []) or []),
    }


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: audit_substrate_conf_coverage.py "
            "<path/to/core.config_entries>",
            file=sys.stderr,
        )
        return 1
    path = Path(argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    ura_entries = _load_entries(path)
    room_entries = [
        e for e in ura_entries
        if (e.get("data") or {}).get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
        or (e.get("options") or {}).get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
    ]

    empty_rooms: List[str] = []
    covered_rooms: List[tuple] = []
    for entry in sorted(
        room_entries,
        key=lambda e: ((e.get("data") or {}).get(CONF_ROOM_NAME, ""),),
    ):
        merged = {**(entry.get("data") or {}), **(entry.get("options") or {})}
        room_name = merged.get(CONF_ROOM_NAME, "<no room_name>")
        coverage = _coverage_for_entry(entry)
        total = sum(coverage.values())
        if total == 0:
            empty_rooms.append(room_name)
        else:
            covered_rooms.append((room_name, coverage, total))

    print("=" * 72)
    print("URA Occupancy Substrate — CONF-list coverage audit")
    print("=" * 72)
    print(f"Total ROOM entries: {len(room_entries)}")
    print(f"Empty CONF lists (no Tier-1 sensors): {len(empty_rooms)}")
    print(f"Covered rooms: {len(covered_rooms)}")
    print()
    print("--- Covered rooms (room: motion / mmwave / occupancy) ---")
    for room_name, coverage, total in covered_rooms:
        print(
            f"  {room_name}: {coverage['motion']} / "
            f"{coverage['mmwave']} / {coverage['occupancy']}  "
            f"(total {total})"
        )
    print()
    print("--- Rooms with empty CONF lists (no-Tier-1 substrate coverage) ---")
    for room_name in empty_rooms:
        print(f"  {room_name}")
    print()
    print(
        "Reminder: empty-CONF-list rooms degenerate gracefully — substrate "
        "subscribes zero entities for them and the zone tier falls back to "
        "camera/BLE composition. This script is informational only."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
