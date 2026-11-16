#!/usr/bin/env python3
"""VISION-INTERIOR-SIGHTINGS-1 D0(a) -- READ-ONLY coverage probe (plan
``docs/planning/PLANNING_vision_interior_sightings.md`` §7, §9.D0 (a)).

Reads ``.storage/core.entity_registry``, ``core.device_registry``,
``core.config_entries`` and ``universal_room_automation/interior_paths.json``
from an HA config directory (the Samba mount); writes nothing.

    .venv-ha/bin/python scripts/probes/interior_vision_d0a.py /Users/okosisi/ha-config

Per interior camera (the integration entry's ``camera_person_entities``, the
list ``PersonCensus.interior_camera_entities()`` resolves): entity -> registry
device -> ship 3b twin group (``camera_stream_health.twin_pair_for_device``)
-> ``interior_camera_key`` (min device id of the group) vs
``canonical_camera_key`` of ``CameraResolver.resolve_operator_declaration``
-> area (entity area, else device area) -> URA room (room entry area id) ->
room type -> still source (``frigate_member`` + ``own_camera_entity_for_device``)
-> path-map membership. Asserts: the keys are equal, one group per area, every
group has a still source. A key mismatch or two groups in one area print
STOP (the build stops, plan §7); a group with no still source prints
ORCHESTRATOR (an operator question for the vision ships, plan §8). Registry only: no name or suffix is parsed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class _Entities(dict):
    def get_entries_for_device_id(self, device_id, include_disabled_entities=False):
        return [e for e in self.values() if e.device_id == device_id
                and (include_disabled_entities or e.disabled_by is None)]


class _ER:
    def __init__(self, rows):
        self.entities = _Entities()
        for r in rows:
            ns = SimpleNamespace(**{k: r.get(k) for k in (
                "entity_id", "device_id", "platform", "disabled_by", "unique_id",
                "area_id", "original_name", "name", "config_entry_id", "hidden_by",
                "entity_category", "original_device_class", "device_class")})
            self.entities[ns.entity_id] = ns

    def async_get(self, entity_id):
        return self.entities.get(entity_id)

    def async_get_entity_id(self, domain, platform, unique_id):
        for e in self.entities.values():
            if e.platform == platform and e.unique_id == unique_id \
                    and e.entity_id.startswith(domain + "."):
                return e.entity_id
        return None


class _DR:
    def __init__(self, rows):
        self.devices = {}
        for r in rows:
            ns = SimpleNamespace(
                id=r.get("id"),
                identifiers={tuple(x) for x in r.get("identifiers") or ()},
                connections={tuple(x) for x in r.get("connections") or ()},
                name=r.get("name"), name_by_user=r.get("name_by_user"),
                area_id=r.get("area_id"), manufacturer=r.get("manufacturer"),
                model=r.get("model"), model_id=r.get("model_id"),
                via_device_id=r.get("via_device_id"),
                config_entries=set(r.get("config_entries") or ()),
                disabled_by=r.get("disabled_by"),
            )
            self.devices[ns.id] = ns

    def async_get(self, device_id):
        return self.devices.get(device_id)


def main(base: str) -> int:
    from custom_components.universal_room_automation import const as c
    from custom_components.universal_room_automation.camera_resolver import (
        CameraResolver, canonical_camera_key,
    )
    from custom_components.universal_room_automation.domain_coordinators import (
        camera_stream_health as csh,
    )

    st = Path(base) / ".storage"
    er = _ER(json.loads((st / "core.entity_registry").read_text())["data"]["entities"])
    dr = _DR(json.loads((st / "core.device_registry").read_text())["data"]["devices"])
    entries = json.loads((st / "core.config_entries").read_text())["data"]["entries"]
    ura = [e for e in entries if e.get("domain") == c.DOMAIN]
    integ = next((e for e in ura if (e.get("data") or {}).get(c.CONF_ENTRY_TYPE)
                  == c.ENTRY_TYPE_INTEGRATION), None)
    merged = {**(integ or {}).get("data", {}), **(integ or {}).get("options", {})}
    configured = list(merged.get(c.CONF_CAMERA_PERSON_ENTITIES) or [])
    rooms = {}
    for e in ura:
        m = {**(e.get("data") or {}), **(e.get("options") or {})}
        if m.get(c.CONF_ENTRY_TYPE) == c.ENTRY_TYPE_ROOM and m.get(c.CONF_AREA_ID):
            rooms.setdefault(m[c.CONF_AREA_ID], []).append(
                (m.get(c.CONF_ROOM_NAME), m.get(c.CONF_ROOM_TYPE)))
    groups_map = csh.pure_twin_groups(er, dr)
    resolver = CameraResolver(er, dr)
    pmap_nodes: set[str] = set()
    pfile = Path(base) / "universal_room_automation" / "interior_paths.json"
    pmap_raw = json.loads(pfile.read_text()) if pfile.exists() else {}
    for door, body in (pmap_raw.get("doors") or {}).items():
        for edge in body.get("edges") or ():
            for ent in (edge.get("from"), edge.get("to")):
                fus = resolver.resolve_operator_declaration([ent]) if ent else []
                if fus:
                    pmap_nodes.add(canonical_camera_key(fus[0]))
    stops: list[str] = []   # build stop (plan §7)
    notes: list[str] = []   # orchestrator question (plan §8, §9.D0 gates)
    seen_groups: dict[frozenset, dict] = {}
    for cam in configured:
        dev = csh.camera_device_for_entity(er, cam)
        if dev is None:
            stops.append(f"{cam}: no camera device in the registry")
            continue
        group = csh.twin_pair_for_device(er, dr, dev, groups=groups_map)
        row = seen_groups.setdefault(group, {"entities": [], "group": sorted(group)})
        row["entities"].append(cam)
    area_groups: dict[str, list] = {}
    print("group | interior_key | canonical_key | path_node | area | room(type) | still_source")
    for group, row in seen_groups.items():
        ikey = min(group)
        fus = resolver.resolve_operator_declaration([row["entities"][0]])
        ckey = canonical_camera_key(fus[0]) if fus else None
        fsrc = sorted(s.device_id for s in fus[0].sources) if fus else []
        area = None
        for cam in row["entities"]:
            ent = er.async_get(cam)
            area = getattr(ent, "area_id", None) or getattr(
                dr.async_get(getattr(ent, "device_id", None)), "area_id", None)
            if area:
                break
        area_groups.setdefault(area, []).append(ikey)
        room = rooms.get(area)
        frig = csh.frigate_member(er, group)
        still = csh.own_camera_entity_for_device(er, frig) if frig else None
        print(f"{row['group']} | {ikey} | {ckey} (sources {fsrc}) | "
              f"{ikey in pmap_nodes} | {area} | {room} | {still}")
        if ckey != ikey:
            stops.append(f"key mismatch {row['entities']}: interior {ikey} != canonical {ckey}")
        if still is None:
            notes.append(f"no still source (no Frigate member) for {row['entities']}")
    for area, keys in area_groups.items():
        if len(keys) > 1:
            stops.append(f"two groups in area {area}: {keys}")
    print(f"configured={len(configured)} groups={len(seen_groups)}")
    for s in stops:
        print("STOP:", s)
    for s in notes:
        print("ORCHESTRATOR:", s)
    return 1 if stops else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/Users/okosisi/ha-config"))
