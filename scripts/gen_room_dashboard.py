#!/usr/bin/env python3
"""
Re-runnable config-driven Lovelace room-card generator.

Purpose (LOVELACE-DECLUTTER-MIGRATION-1 / LOVELACE-AUTO-ROOM-DASHBOARD-1):
Every URA room (config entry entry_type='room') should appear on the
Residence dashboard (v8) as a bubble popup + a zone-grouped button-card,
and on the v6 Rooms dashboard as a mushroom-template-card. Rooms newly
added to config should auto-appear on the next run.

Safety: never writes to the live .storage. Reads live .storage as
sources of truth, writes regenerated dashboards to --out-dir (default:
this file's scratchpad path).

Scope: "add-missing, match-archetype" — existing bespoke cards
(bubble popups w/ hand-tuned fan/blind tiles; curated mushroom groupings)
are preserved byte-for-byte. New rooms get the standard archetype. The
temporary "Recently Added Rooms" sections (interim plain entities-cards)
are removed. Miscontained cards in v8 "Unzoned / Utility" are moved to
their real zone section per config.

Usage:
    python3 scripts/gen_room_dashboard.py \
        --ha-config /Users/okosisi/ha-config \
        --out-dir  /path/to/scratch/gen_out

Exit non-zero on any validation failure.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections import defaultdict
from typing import Any, Optional

# -- standard <slug>_* entities that make up a room bubble popup include list.
# Only those that actually exist in the entity registry are emitted.
STANDARD_INCLUDES: list[tuple[str, str]] = [
    ("binary_sensor", "occupied"),
    ("sensor", "current_occupants"),
    ("binary_sensor", "energy_saving_active"),
    ("binary_sensor", "hvac_cooling"),
    ("binary_sensor", "hvac_heating"),
    ("binary_sensor", "fan_should_run"),
    ("sensor", "automation_health"),
    ("sensor", "temperature"),
    ("sensor", "humidity"),
    ("sensor", "illuminance"),
    ("sensor", "lights_on"),
    ("sensor", "fans_on"),
    ("binary_sensor", "motion"),
]

# v8 zone-heading -> ordered index in the Residence view. Kept as an
# assertion, not a hard-coded write: we look up sections by heading.
V8_ZONE_HEADINGS = ["Entertainment", "Master Suite", "Upstairs", "Back Hallway", "Outside"]
V8_UNZONED_HEADING = "Unzoned / Utility"
V8_TEMP_HEADING = "Recently Added Rooms"
V8_BUBBLE_SECTION_INDEX_HINT = 8  # verified: no heading, contains bubble popups
V8_RESIDENCE_VIEW_TITLE = "Residence"

V6_ROOMS_VIEW_TITLE = "Rooms"
V6_TEMP_HEADING = "Recently Added Rooms"


# ---- room roster --------------------------------------------------------

def load_room_roster(ha_config: str) -> list[dict]:
    """Return list of room dicts from core.config_entries (URA entry_type=room)."""
    path = os.path.join(ha_config, ".storage", "core.config_entries")
    with open(path) as f:
        ce = json.load(f)
    rooms = []
    for e in ce["data"]["entries"]:
        if e.get("domain") != "universal_room_automation":
            continue
        merged = {**(e.get("data") or {}), **(e.get("options") or {})}
        if merged.get("entry_type") != "room":
            continue
        rooms.append({
            "entry_id": e["entry_id"],
            "title": e["title"],
            "zone": merged.get("zone"),
            "lights": list(merged.get("lights") or []),
            "night_lights": list(merged.get("night_lights") or []),
            "alert_lights": list(merged.get("alert_lights") or []),
            "climate_entity": merged.get("climate_entity"),
            "temperature_sensor": merged.get("temperature_sensor"),
            "humidity_sensor": merged.get("humidity_sensor"),
            "motion_sensors": list(merged.get("motion_sensors") or []),
            "lux_sensors": list(merged.get("lux_sensors") or []),
            "fans": list(merged.get("fans") or []),
            "covers": list(merged.get("covers") or []),
        })
    return rooms


def load_entity_registry(ha_config: str) -> tuple[set[str], dict[str, str]]:
    """Return (set of all entity_ids, mapping URA-entry_id -> room slug)."""
    path = os.path.join(ha_config, ".storage", "core.entity_registry")
    with open(path) as f:
        er = json.load(f)
    all_eids: set[str] = set()
    entry_to_slug: dict[str, str] = {}
    for ent in er["data"]["entities"]:
        eid = ent.get("entity_id")
        if eid:
            all_eids.add(eid)
        if (
            ent.get("platform") == "universal_room_automation"
            and isinstance(eid, str)
            and eid.startswith("binary_sensor.")
            and eid.endswith("_occupied")
        ):
            slug = eid[len("binary_sensor."):-len("_occupied")]
            entry_to_slug.setdefault(ent["config_entry_id"], slug)
    return all_eids, entry_to_slug


# ---- archetype builders -------------------------------------------------

_ICON_KEYWORDS = [
    ("toilet", "mdi:toilet"),
    ("bath", "mdi:bathtub-outline"),
    ("kitchen", "mdi:silverware-fork-knife"),
    ("pantry", "mdi:cupboard-outline"),
    ("closet", "mdi:hanger"),
    ("hallway", "mdi:transit-connection-horizontal"),
    ("stair", "mdi:stairs"),
    ("garage", "mdi:garage-variant"),
    ("laundry", "mdi:washing-machine"),
    ("patio", "mdi:umbrella-beach-outline"),
    ("media", "mdi:television"),
    ("game", "mdi:gamepad-variant-outline"),
    ("exercise", "mdi:dumbbell"),
    ("study", "mdi:desk"),
    ("dining", "mdi:table-chair"),
    ("living", "mdi:sofa"),
    ("bedroom", "mdi:bed"),
    ("nook", "mdi:coffee-outline"),
    ("vanity", "mdi:mirror-rectangle"),
    ("av ", "mdi:home-theater"),
    ("receiving", "mdi:seat-outline"),
]

_ZONE_COLOR = {
    "Entertainment": "blue",
    "Master Suite": "purple",
    "Upstairs": "teal",
    "Back Hallway": "amber",
    "Outside": "green",
    None: "grey",
}


def guess_icon(title: str) -> str:
    t = title.lower()
    for kw, icon in _ICON_KEYWORDS:
        if kw in t:
            return icon
    return "mdi:home-outline"


def build_bubble_card(room: dict, slug: str, all_eids: set[str]) -> dict:
    """Standard bubble popup, filtered to existing entities."""
    include: list[dict] = []
    for dom, suf in STANDARD_INCLUDES:
        eid = f"{dom}.{slug}_{suf}"
        if eid in all_eids:
            include.append({"entity_id": eid})

    # Room-configured physical devices (only those that exist).
    for grp in ("lights", "night_lights", "alert_lights", "motion_sensors", "lux_sensors", "fans", "covers"):
        for eid in room.get(grp) or []:
            if eid in all_eids and not any(x.get("entity_id") == eid for x in include):
                include.append({"entity_id": eid})
    for single in ("climate_entity", "temperature_sensor", "humidity_sensor"):
        eid = room.get(single)
        if eid and eid in all_eids and not any(x.get("entity_id") == eid for x in include):
            include.append({"entity_id": eid})

    return {
        "type": "custom:bubble-card",
        "card_type": "pop-up",
        "hash": f"#{slug}",
        "name": room["title"],
        "icon": guess_icon(room["title"]),
        "bg_color": "var(--contrast1)",
        "width_desktop": "clamp(420px, 80vw, 820px)",
        "cards": [
            {
                "type": "custom:auto-entities",
                "card": {"type": "entities", "title": room["title"], "state_color": True},
                "filter": {
                    "include": include,
                    "exclude": [
                        {"state": "unavailable"},
                        {"state": "unknown"},
                        {"state": "None"},
                        {"state": "none"},
                    ],
                },
                "sort": {"method": "friendly_name"},
            }
        ],
    }


def build_button_card(room: dict, slug: str, all_eids: set[str]) -> dict:
    """Standard zone tile — matches the existing room_card template."""
    occ = f"binary_sensor.{slug}_occupied"
    variables: dict[str, Any] = {"color": _ZONE_COLOR.get(room.get("zone"), "grey")}
    temp = f"sensor.{slug}_temperature"
    co = f"sensor.{slug}_current_occupants"
    if temp in all_eids:
        variables["temp"] = temp
    if co in all_eids:
        variables["co"] = co
    return {
        "type": "custom:button-card",
        "template": "room_card",
        "entity": occ,
        "name": room["title"],
        "icon": guess_icon(room["title"]),
        "variables": variables,
        "tap_action": {"action": "navigate", "navigation_path": f"#{slug}"},
        "grid_options": {"columns": 6, "rows": 3},
    }


def build_mushroom_card(room: dict, slug: str, all_eids: set[str]) -> Optional[dict]:
    """v6 archetype — matches existing mushroom-template-card style."""
    occ = f"binary_sensor.{slug}_occupied"
    if occ not in all_eids:
        return None
    return {
        "type": "custom:mushroom-template-card",
        "primary": room["title"],
        "secondary": f"{{{{ 'Occupied' if is_state('{occ}', 'on') else 'Vacant' }}}}",
        "icon": guess_icon(room["title"]),
        "icon_color": f"{{{{ 'green' if is_state('{occ}', 'on') else 'disabled' }}}}",
        "tap_action": {"action": "more-info", "entity": occ},
        "card_mod": {
            "style": "ha-card { border-radius: 16px; border: 1px solid var(--divider-color); }"
        },
    }


# ---- v8 regeneration ----------------------------------------------------

def _section_heading(sec: dict) -> Optional[str]:
    for c in sec.get("cards", []):
        if c.get("type") == "heading":
            return c.get("heading")
    return None


def regenerate_v8(v8: dict, rooms: list[dict], entry_to_slug: dict[str, str], all_eids: set[str], summary: list[str]) -> dict:
    v8_new = copy.deepcopy(v8)
    view = next(v for v in v8_new["data"]["config"]["views"] if v.get("title") == V8_RESIDENCE_VIEW_TITLE)
    sections = view["sections"]

    # 1. Drop the temporary "Recently Added Rooms" section.
    dropped = [i for i, s in enumerate(sections) if _section_heading(s) == V8_TEMP_HEADING]
    for i in reversed(dropped):
        sections.pop(i)
        summary.append(f"[v8] removed temp section index {i} '{V8_TEMP_HEADING}'")

    # Locate zone sections + bubble section by heading (positions may have shifted).
    zone_sections: dict[str, dict] = {}
    for s in sections:
        h = _section_heading(s)
        if h in V8_ZONE_HEADINGS + [V8_UNZONED_HEADING]:
            zone_sections[h] = s
    # Ensure every real zone section exists (they all do, per inspection).
    for z in V8_ZONE_HEADINGS + [V8_UNZONED_HEADING]:
        if z not in zone_sections:
            raise RuntimeError(f"expected v8 zone section not found: {z}")

    bubble_section = sections[V8_BUBBLE_SECTION_INDEX_HINT]
    if _section_heading(bubble_section) is not None or not any(c.get("type") == "custom:bubble-card" for c in bubble_section.get("cards", [])):
        # Fall back: find the section with the most bubble-cards
        cand = max(sections, key=lambda s: sum(1 for c in s.get("cards", []) if c.get("type") == "custom:bubble-card"))
        bubble_section = cand
        summary.append("[v8] bubble section index hint missed; located by content")

    # roster lookups
    slug_by_entry = entry_to_slug
    roster_slugs: dict[str, dict] = {}
    for r in rooms:
        slug = slug_by_entry.get(r["entry_id"])
        if not slug:
            summary.append(f"[v8] WARN room {r['title']!r} has no _occupied slug; skipped")
            continue
        r["_slug"] = slug
        roster_slugs[slug] = r

    # 2. MOVE miscontained button-cards from Unzoned/Utility to their real zone.
    unz = zone_sections[V8_UNZONED_HEADING]
    kept: list[dict] = []
    for c in unz.get("cards", []):
        if c.get("type") == "custom:button-card":
            nav = (c.get("tap_action") or {}).get("navigation_path", "")
            slug = nav.lstrip("#")
            room = roster_slugs.get(slug)
            if room and room.get("zone") in V8_ZONE_HEADINGS:
                zone_sections[room["zone"]]["cards"].append(c)
                summary.append(f"[v8] moved button {c.get('name')!r} Unzoned -> {room['zone']!r}")
                continue
        kept.append(c)
    unz["cards"] = kept

    # 3. ADD button-cards for roster rooms not represented in ANY zone section.
    existing_slugs_buttoned: set[str] = set()
    for s in list(zone_sections.values()):
        for c in s.get("cards", []):
            if c.get("type") == "custom:button-card":
                nav = (c.get("tap_action") or {}).get("navigation_path", "")
                if nav.startswith("#"):
                    existing_slugs_buttoned.add(nav[1:])

    for slug, room in roster_slugs.items():
        if slug in existing_slugs_buttoned:
            continue
        zone = room.get("zone")
        heading = zone if zone in V8_ZONE_HEADINGS else V8_UNZONED_HEADING
        card = build_button_card(room, slug, all_eids)
        zone_sections[heading]["cards"].append(card)
        summary.append(f"[v8] added button {room['title']!r} -> {heading!r}")

    # 4. ADD bubble popups for roster rooms not yet in the bubble section.
    existing_hashes: set[str] = {
        c.get("hash", "") for c in bubble_section.get("cards", []) if c.get("type") == "custom:bubble-card"
    }
    for slug, room in roster_slugs.items():
        h = f"#{slug}"
        if h in existing_hashes:
            continue
        card = build_bubble_card(room, slug, all_eids)
        bubble_section["cards"].append(card)
        n_ents = len(card["cards"][0]["filter"]["include"])
        summary.append(f"[v8] added bubble {room['title']!r} ({n_ents} entities)")

    return v8_new


# ---- v6 regeneration ----------------------------------------------------

def regenerate_v6(v6: dict, rooms: list[dict], entry_to_slug: dict[str, str], all_eids: set[str], summary: list[str]) -> dict:
    v6_new = copy.deepcopy(v6)
    view = next(v for v in v6_new["data"]["config"]["views"] if v.get("title") == V6_ROOMS_VIEW_TITLE)
    sections = view["sections"]

    # 1. Drop the temporary section.
    for i in [i for i, s in enumerate(sections) if _section_heading(s) == V6_TEMP_HEADING][::-1]:
        sections.pop(i)
        summary.append(f"[v6] removed temp section index {i} '{V6_TEMP_HEADING}'")

    # 2. Collect slugs already represented by existing mushroom cards.
    represented: set[str] = set()
    for s in sections:
        for c in s.get("cards", []):
            if c.get("type") == "custom:mushroom-template-card":
                tap = c.get("tap_action") or {}
                ent = tap.get("entity") or ""
                if ent.startswith("binary_sensor.") and ent.endswith("_occupied"):
                    represented.add(ent[len("binary_sensor."):-len("_occupied")])

    # 3. Group missing rooms by config zone; add one section per zone.
    missing_by_zone: dict[Optional[str], list[dict]] = defaultdict(list)
    for r in rooms:
        slug = entry_to_slug.get(r["entry_id"])
        if not slug or slug in represented:
            continue
        missing_by_zone[r.get("zone")].append((slug, r))

    zone_order = ["Entertainment", "Master Suite", "Upstairs", "Back Hallway", "Outside", None]
    for zone in zone_order:
        items = missing_by_zone.get(zone) or []
        if not items:
            continue
        heading = f"More Rooms — {zone}" if zone else "More Rooms — Unzoned / Utility"
        cards: list[dict] = [{"type": "heading", "heading": heading}]
        for slug, room in sorted(items, key=lambda x: x[1]["title"]):
            m = build_mushroom_card(room, slug, all_eids)
            if m is None:
                summary.append(f"[v6] WARN room {room['title']!r} has no _occupied; skipped")
                continue
            cards.append(m)
            summary.append(f"[v6] added mushroom {room['title']!r} -> {heading!r}")
        sections.append({"type": "grid", "cards": cards, "column_span": 1})

    return v6_new


# ---- validation ---------------------------------------------------------

def validate(v8_orig: dict, v8_new: dict, v6_orig: dict, v6_new: dict, rooms: list[dict], entry_to_slug: dict[str, str], all_eids: set[str]) -> list[str]:
    errors: list[str] = []

    # (a) valid JSON round-trip
    for name, obj in [("v8_new", v8_new), ("v6_new", v6_new)]:
        try:
            json.loads(json.dumps(obj))
        except Exception as e:
            errors.append(f"{name} not JSON-serializable: {e}")

    # (b) every roster room appears exactly once in v8 as bubble AND button.
    view = next(v for v in v8_new["data"]["config"]["views"] if v.get("title") == V8_RESIDENCE_VIEW_TITLE)
    hashes: list[str] = []
    nav_paths: list[str] = []
    for s in view["sections"]:
        for c in s.get("cards", []):
            if c.get("type") == "custom:bubble-card":
                hashes.append(c.get("hash", ""))
            if c.get("type") == "custom:button-card":
                nav_paths.append(((c.get("tap_action") or {}).get("navigation_path") or ""))
    from collections import Counter
    hc = Counter(hashes)
    nc = Counter(nav_paths)
    for r in rooms:
        slug = entry_to_slug.get(r["entry_id"])
        if not slug:
            continue
        if hc.get(f"#{slug}", 0) != 1:
            errors.append(f"[v8] room {r['title']!r} bubble count = {hc.get(f'#{slug}',0)}")
        if nc.get(f"#{slug}", 0) != 1:
            errors.append(f"[v8] room {r['title']!r} button count = {nc.get(f'#{slug}',0)}")

    # (c) every entity referenced by NEW cards exists in the registry.
    #     We only enforce this on cards we authored — bespoke cards may reference
    #     entities that pre-date any current registry state and we don't touch them.
    def entities_in(card: dict) -> list[str]:
        out: list[str] = []
        if card.get("entity"):
            out.append(card["entity"])
        for k in ("tap_action",):
            v = card.get(k) or {}
            if v.get("entity"):
                out.append(v["entity"])
        if card.get("type") == "custom:bubble-card":
            f = ((card.get("cards") or [{}])[0].get("filter") or {})
            for x in f.get("include", []):
                if x.get("entity_id"):
                    out.append(x["entity_id"])
        return out

    orig_v8_dump = json.dumps(v8_orig)
    for s in view["sections"]:
        for c in s.get("cards", []):
            dump = json.dumps(c)
            if dump in orig_v8_dump:
                continue  # untouched from original
            for eid in entities_in(c):
                if eid not in all_eids:
                    errors.append(f"[v8] NEW card refs nonexistent entity {eid} (name={c.get('name')})")

    # (d) roster coverage on v6 — every room must appear at least once as mushroom.
    view6 = next(v for v in v6_new["data"]["config"]["views"] if v.get("title") == V6_ROOMS_VIEW_TITLE)
    repr_slugs: set[str] = set()
    for s in view6["sections"]:
        for c in s.get("cards", []):
            if c.get("type") == "custom:mushroom-template-card":
                ent = (c.get("tap_action") or {}).get("entity") or ""
                if ent.startswith("binary_sensor.") and ent.endswith("_occupied"):
                    repr_slugs.add(ent[len("binary_sensor."):-len("_occupied")])
    for r in rooms:
        slug = entry_to_slug.get(r["entry_id"])
        if slug and slug not in repr_slugs:
            errors.append(f"[v6] room {r['title']!r} not represented")

    # (e) non-room sections unchanged: verify by title-set + non-mutated non-room views JSON equality.
    def non_room_views(cfg: dict, room_view_title: str) -> str:
        return json.dumps({v["title"]: v for v in cfg["data"]["config"]["views"] if v.get("title") != room_view_title}, sort_keys=True)

    if non_room_views(v8_orig, V8_RESIDENCE_VIEW_TITLE) != non_room_views(v8_new, V8_RESIDENCE_VIEW_TITLE):
        errors.append("[v8] non-Residence views differ from original")
    if non_room_views(v6_orig, V6_ROOMS_VIEW_TITLE) != non_room_views(v6_new, V6_ROOMS_VIEW_TITLE):
        errors.append("[v6] non-Rooms views differ from original")

    return errors


# ---- main ---------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ha-config", default="/Users/okosisi/ha-config", help="HA config root (Samba mount)")
    ap.add_argument(
        "--out-dir",
        default="/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/0a51310f-d57c-4e0f-abb7-c8ed23acdfa5/scratchpad/gen_out",
    )
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    v8_path = os.path.join(args.ha_config, ".storage", "lovelace.ura_v8")
    v6_path = os.path.join(args.ha_config, ".storage", "lovelace.ura_v6")
    with open(v8_path) as f:
        v8_orig = json.load(f)
    with open(v6_path) as f:
        v6_orig = json.load(f)

    rooms = load_room_roster(args.ha_config)
    all_eids, entry_to_slug = load_entity_registry(args.ha_config)

    summary: list[str] = []
    v8_new = regenerate_v8(v8_orig, rooms, entry_to_slug, all_eids, summary)
    v6_new = regenerate_v6(v6_orig, rooms, entry_to_slug, all_eids, summary)

    errors = validate(v8_orig, v8_new, v6_orig, v6_new, rooms, entry_to_slug, all_eids)

    out_v8 = os.path.join(args.out_dir, "lovelace.ura_v8.new")
    out_v6 = os.path.join(args.out_dir, "lovelace.ura_v6.new")
    with open(out_v8, "w") as f:
        json.dump(v8_new, f, indent=2)
    with open(out_v6, "w") as f:
        json.dump(v6_new, f, indent=2)

    print(f"wrote {out_v8}")
    print(f"wrote {out_v6}")
    print(f"\n=== SUMMARY ({len(summary)} actions) ===")
    for line in summary:
        print(" ", line)

    if errors:
        print(f"\n=== VALIDATION ERRORS ({len(errors)}) ===")
        for e in errors:
            print(" ", e)
        return 1
    print("\nvalidation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
