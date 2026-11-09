#!/usr/bin/env python3
"""Read-only falsifier probe for FACE-SOURCE-REGISTRY-DISCOVERY-1 (D1).

Usage:
    python3 scripts/probe_face_source_registry.py \
        <path/to/core.entity_registry> <path/to/core.device_registry> \
        [--emit-fixture OUT.json]

Checks (plan §1):
  (a) registry path vs the legacy name-pattern path, per Frigate camera
      person sensor: same face source? (expected on the reference install:
      agree=12, 17 SKIP rows for `*_person_occupancy_2` person sensors)
  (b) rename one face sensor's entity_id: registry still resolves it.
  (c) new Frigate entry_id prefix on every unique_id: same registry index.
  plus: `sensor_global_face` look-alikes never indexed; name-pattern hits
  that are not `sensor_recognized_face`; camera devices with no face sensor.

--emit-fixture writes the minimised registry fixture used by
quality/tests/test_face_source_registry.py (registry fields only; no MAC
connections). Never writes to HA.
"""
from __future__ import annotations

import copy
import json
import sys

TOKEN = "sensor_recognized_face"


def _seg(uid, i):
    p = (uid or "").split(":")
    return p[i] if len(p) > i else None


def registry_index(entities):
    out = {}
    for e in entities:
        if e.get("platform") != "frigate" or not e["entity_id"].startswith("sensor."):
            continue
        if _seg(e.get("unique_id"), 1) != TOKEN or e.get("disabled_by"):
            continue
        out.setdefault(e.get("device_id"), []).append(e["entity_id"])
    return out


def person_sensors(entities):
    out = []
    for e in entities:
        if e.get("platform") != "frigate" or not e["entity_id"].startswith("binary_sensor."):
            continue
        if _seg(e.get("unique_id"), 1) != "occupancy_sensor":
            continue
        if not (_seg(e.get("unique_id"), 2) or "").endswith("_person"):
            continue
        out.append(e)
    return out


def pattern_resolve(bs_id, present_ids):
    if not bs_id.endswith("_person_occupancy"):
        return "SKIP(no _person_occupancy suffix)"
    base = bs_id[len("binary_sensor."):-len("_person_occupancy")]
    for c in (f"sensor.{base}_last_recognized_face", f"sensor.{base}_last_recognized_face_2"):
        if c in present_ids:
            return c
    return None


def run(entities):
    idx = registry_index(entities)
    present = {e["entity_id"] for e in entities if not e.get("disabled_by")}
    cam_devs = {e["device_id"] for e in entities
                if e.get("platform") == "frigate" and e["entity_id"].startswith("camera.")}
    rows = []
    for ps in person_sensors(entities):
        if ps.get("disabled_by") or ps.get("device_id") not in cam_devs:
            continue
        reg = idx.get(ps.get("device_id")) or []
        reg_one = reg[0] if len(reg) == 1 else (reg or None)
        rows.append((ps["entity_id"], pattern_resolve(ps["entity_id"], present), reg_one))
    return idx, rows, cam_devs


def emit_fixture(ents, devs, out_path):
    keep_ents = []
    for e in ents:
        plat = e.get("platform")
        eid = e["entity_id"]
        seg1 = _seg(e.get("unique_id"), 1)
        if plat == "frigate" and (
            (eid.startswith("sensor.") and seg1 in (TOKEN, "sensor_global_face"))
            or eid.startswith("camera.")
            or (eid.startswith("binary_sensor.") and seg1 == "occupancy_sensor"
                and (_seg(e.get("unique_id"), 2) or "").endswith("_person"))
        ):
            keep_ents.append(e)
        elif plat == "unifiprotect" and (
            eid.startswith("camera.")
            or (eid.startswith("binary_sensor.") and eid.endswith("_person_detected"))
        ):
            keep_ents.append(e)
    dev_ids = {e.get("device_id") for e in keep_ents if e.get("device_id")}
    # include via_device parents (Frigate server)
    for did in list(dev_ids):
        via = (devs.get(did) or {}).get("via_device_id")
        if via:
            dev_ids.add(via)
    fixture = {
        "source": "core.entity_registry + core.device_registry (live, read-only)",
        "entities": [
            {k: e.get(k) for k in ("entity_id", "platform", "unique_id", "device_id", "disabled_by")}
            for e in sorted(keep_ents, key=lambda x: x["entity_id"])
        ],
        "devices": [
            {
                "id": d["id"],
                "name": d.get("name"),
                "identifiers": d.get("identifiers") or [],
                "via_device_id": d.get("via_device_id"),
            }
            for d in sorted((devs[i] for i in dev_ids if i in devs), key=lambda x: x["id"])
        ],
    }
    with open(out_path, "w") as fh:
        json.dump(fixture, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"fixture: {len(fixture['entities'])} entities, {len(fixture['devices'])} devices -> {out_path}")


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    ents = json.load(open(argv[1]))["data"]["entities"]
    devs = {d["id"]: d for d in json.load(open(argv[2]))["data"]["devices"]}
    if "--emit-fixture" in argv:
        emit_fixture(ents, devs, argv[argv.index("--emit-fixture") + 1])

    idx, rows, cam_devs = run(ents)
    agree = sum(1 for _, p, r in rows if p == r)
    print(f"== (a) live: {len(rows)} Frigate camera person sensors; agree={agree}")
    for bs, p, r in rows:
        if p != r:
            print(f"   DIFF {bs}: pattern={p} registry={r}")
    print(f"   registry face sensors={sum(len(v) for v in idx.values())} on {len(idx)} devices")
    print(f"   Frigate camera devices with NO face sensor: "
          f"{sorted(devs[d].get('name') for d in cam_devs if d not in idx)}")
    gf = [e["entity_id"] for e in ents if e.get("platform") == "frigate"
          and _seg(e.get("unique_id"), 1) == "sensor_global_face"]
    indexed = set(sum(idx.values(), []))
    print(f"   sensor_global_face look-alikes: {len(gf)}; any indexed? {any(x in indexed for x in gf)}")
    pat_only = [e["entity_id"] for e in ents if e.get("platform") == "frigate"
                and (e["entity_id"].endswith("_last_recognized_face")
                     or e["entity_id"].endswith("_last_recognized_face_2"))
                and _seg(e.get("unique_id"), 1) != TOKEN]
    print(f"   name-pattern matches that are NOT {TOKEN}: {pat_only}")

    ents_b = copy.deepcopy(ents)
    for e in ents_b:
        if e["entity_id"] == "sensor.doorbell_lite_last_recognized_face_2":
            e["entity_id"] = "sensor.front_bell_face_name"
    _, rows_b, _ = run(ents_b)
    for bs, p, r in rows_b:
        if bs.startswith("binary_sensor.doorbell_lite"):
            print(f"== (b) rename doorbell_lite face: pattern={p} registry={r}")

    ents_c = copy.deepcopy(ents)
    for e in ents_c:
        if e.get("platform") == "frigate" and e.get("unique_id") and ":" in e["unique_id"]:
            e["unique_id"] = "01NEWENTRYIDXXXXXXXXXXXXXX:" + e["unique_id"].split(":", 1)[1]
    idx_c, _, _ = run(ents_c)
    same = {k: sorted(v) for k, v in idx.items()} == {k: sorted(v) for k, v in idx_c.items()}
    print(f"== (c) new entry_id prefix: registry index identical to live = {same}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
