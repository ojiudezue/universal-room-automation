"""MUSIC-FOLLOWING-TRANSFER-REPAIR-1 D0(a): read-only player inventory.

Reads the HA registries and URA config entries from a READ-ONLY copy of
``.storage`` (default: the Samba mount) and prints, per URA room, the
primary player (``room_media_player``), its native platform, whether a
``music_assistant`` media_player exists for the same physical device
(same device_id, or a device whose connections/identifiers overlap), the
GROUPING / PLAY_MEDIA feature bits of both, and the bonus-eligible players
(other enabled media_player entities in the same HA area).

No HA writes. Run with ``python -I scripts/probes/mf_player_inventory.py
[storage_dir]``.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

GROUPING = 524288   # MediaPlayerEntityFeature.GROUPING
PLAY_MEDIA = 512    # MediaPlayerEntityFeature.PLAY_MEDIA


def _load(path):
    with open(path) as f:
        return json.load(f)["data"]


def main(storage: str) -> None:
    ents = _load(f"{storage}/core.entity_registry")["entities"]
    devs = {d["id"]: d for d in _load(f"{storage}/core.device_registry")["devices"]}
    entries = _load(f"{storage}/core.config_entries")["entries"]

    by_eid = {e["entity_id"]: e for e in ents}
    mp = [e for e in ents if e["entity_id"].startswith("media_player.")]
    ma_by_dev = defaultdict(list)
    for e in mp:
        if e.get("platform") == "music_assistant" and e.get("device_id"):
            ma_by_dev[e["device_id"]].append(e["entity_id"])

    def dev_keys(dev_id):
        d = devs.get(dev_id) or {}
        keys = {tuple(c) for c in d.get("connections") or []}
        keys |= {tuple(i) for i in d.get("identifiers") or []}
        return keys

    def _hex12(s):
        h = "".join(c for c in str(s).lower() if c in "0123456789abcdef")
        return h

    def ma_for(eid):
        """All MA candidates: (ma_eid, match_kind)."""
        e = by_eid.get(eid)
        if e is None:
            return [], "not_in_registry"
        if e.get("platform") == "music_assistant":
            return [(eid, "is_ma")], "is_ma"
        dev = e.get("device_id")
        out = []
        for m in ma_by_dev.get(dev, []) if dev else []:
            out.append((m, "same_device"))
        macs = set()
        for c in (devs.get(dev or "") or {}).get("connections") or []:
            if c[0] == "mac":
                macs.add(_hex12(c[1]))
        for mdev, meids in ma_by_dev.items():
            for ident in (devs.get(mdev) or {}).get("identifiers") or []:
                if ident[0] != "music_assistant":
                    continue
                val = str(ident[1])
                wrapped = by_eid.get(val)
                if wrapped is not None and dev and wrapped.get("device_id") == dev:
                    out += [(m, "ha_provider_wrap") for m in meids]
                elif macs and any(mac and mac in _hex12(val) for mac in macs):
                    out += [(m, "mac_in_ma_id") for m in meids]
        return out, (out[0][1] if out else "none")

    def area_of(e):
        if e.get("area_id"):
            return e["area_id"]
        d = devs.get(e.get("device_id") or "") or {}
        return d.get("area_id")

    def feats(eid):
        e = by_eid.get(eid) or {}
        sf = int(e.get("supported_features") or 0)
        return ("G" if sf & GROUPING else "-") + ("P" if sf & PLAY_MEDIA else "-")

    rooms = [e for e in entries if e["domain"] == "universal_room_automation"
             and e["data"].get("entry_type") == "room"]
    print("| Room | Primary | Platform | MA entity | MA join | Feat native/MA | MF enabled | Bonus-eligible (same area) |")
    print("|---|---|---|---|---|---|---|---|")
    covered = uncovered = noplayer = 0
    for r in sorted(rooms, key=lambda x: x["data"].get("room_name", "")):
        cfg = {**r["data"], **r["options"]}
        name = cfg.get("room_name", "?")
        prim = cfg.get("room_media_player")
        mfen = cfg.get("music_following_enabled", True)
        if not prim:
            noplayer += 1
            continue
        pe = by_eid.get(prim) or {}
        cands, how = ma_for(prim)
        ma = cands[0][0] if cands else None
        covered += 1 if ma else 0
        uncovered += 0 if ma else 1
        area = area_of(pe) or cfg.get("area_id")
        ma_set = {c[0] for c in cands}
        bonus = sorted(
            e["entity_id"] for e in mp
            if e["entity_id"] != prim and e["entity_id"] not in ma_set
            and not e.get("disabled_by") and area and area_of(e) == area
        )
        ma_txt = ", ".join(f"`{c}` ({k}, {feats(c)})" for c, k in cands) or "-"
        print(f"| {name} | `{prim}` | {pe.get('platform', '?')} | "
              f"{ma_txt} | {how} | "
              f"{feats(prim)} | {mfen} | "
              f"{', '.join(bonus) or '-'} |")
    print()
    print(f"rooms with a primary: {covered + uncovered}; MA-covered {covered}; "
          f"native-only {uncovered}; rooms without a player: {noplayer}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/Users/okosisi/ha-config/.storage")
