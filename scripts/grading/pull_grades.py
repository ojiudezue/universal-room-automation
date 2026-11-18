#!/usr/bin/env python3
"""Pull operator crossing grades from the LAN grading page into a URA labels file.

Reads GET /api/grades (grades.jsonl on the urakanban site, written by the /grade/ page), joins each grade to
its card in the batch manifest (door group, crossing time, pair index), merges into
quality/tests/fixtures/crossing_operator_grades.json, then clears the server queue (POST /api/grades/clear)
once the file is written. Mirrors the dispositions puller (homelab scripts/webhost/refresh_urakanban.sh).

Labels file (read by the P3-D6 scorer and the P3-D0 gates):
  {"description": ..., "grades": [
     {"crossing_key", "direction", "count", "at", "batch", "kind", "door_group", "e_ts",
      "direction_tracker_vocab", "pair_index", "e2_ts", "pair_label"}, ...]}
  * one row per crossing_key; a later grade of the same key replaces the earlier one (regrade).
  * direction: in | out | both | no_cross | unclear | unknown (operator vocabulary;
    no_cross = someone came to the door but did not go through, added 2026-11-15);
    direction_tracker_vocab maps in -> entry, out -> exit, else null.
  * count: int people who crossed, or "unknown".
  * who (optional, page 2026-11-18, homelab a778edb): list of who crossed, from oji_udezue | ezinne | jaya |
    ziri | guest | unknown_person | cant_tell in that fixed order; the page omits it when none was picked.
  * guest_count (optional): int 1-8, sent only when guest is in who.
  * notes (optional): free text <= 500 chars, omitted when empty. All three are copied exactly as sent and
    written only when the grade carried them: an absent key means "not recorded" (older grades, older page),
    never "nobody" or "no notes".
  * a regrade (same crossing_key, later `at`) replaces the whole row, so a names regrade supersedes the
    direction-only grade.
  * kind "pair" rows carry pair_index into crossing_pass_key_pairs_2026_11_15.json and pair_label in that
    fixture's rubric: both -> round_trip, in / out -> one_pass, unclear / unknown -> unknown.
Interior description pilot grades (kind "interior_desc", /grade/?batch=interior, interior vision D0(g)) go to
quality/tests/fixtures/interior_desc_operator_grades.json instead: one row per frame_key, latest grade wins,
{frame_key, people_count, description, note, at, batch, room, camera, frame_at, nvr_bodies, control}.
No images, no vision text, no identities are written: only keys, times and the operator's answers.

Usage:
  python3 scripts/grading/pull_grades.py              # import + clear the server queue
  python3 scripts/grading/pull_grades.py --no-clear   # import, leave the queue
  python3 scripts/grading/pull_grades.py --dry-run    # show what would be imported
The file is not committed for you: review and commit it in the URA repo.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LABELS_FILE = REPO / "quality/tests/fixtures/crossing_operator_grades.json"
SITE = "http://192.168.13.137:3010"
LOCAL_MANIFEST = Path.home() / "Code/homelab-automation/sites/urakanban/grade/manifest.json"
INTERIOR_LABELS_FILE = REPO / "quality/tests/fixtures/interior_desc_operator_grades.json"
LOCAL_INTERIOR_MANIFEST = Path.home() / "Code/homelab-automation/sites/urakanban/grade/manifest_interior.json"
INTERIOR_KIND = "interior_desc"
INTERIOR_DESCRIPTION = (
    "Operator grades of the interior-vision D0(g) description pilot (urakanban /grade/?batch=interior, "
    "scripts/grading/make_interior_pilot.py + pull_grades.py). One row per frame_key, latest grade wins. "
    "people_count = people the operator sees in the frame (0-8 or 'unknown'); description = "
    "accurate|minor_errors|wrong|made_up for the model's description; nvr_bodies = Frigate person count at "
    "frame time; control = an empty-room control frame. Gate D0-P3 (PLANNING_vision_interior_sightings.md)."
)
TRACKER_VOCAB = {"in": "entry", "out": "exit"}
OPTIONAL_FIELDS = ("who", "guest_count", "notes")  # page 2026-11-18; copied only when the grade carries them
PAIR_LABEL = {"both": "round_trip", "in": "one_pass", "out": "one_pass",
              "no_cross": "no_pass", "unclear": "unknown", "unknown": "unknown"}
DESCRIPTION = (
    "Operator crossing grades from the urakanban /grade/ page (scripts/grading/pull_grades.py). Human truth "
    "for crossing vision P3-D6 direction and count scoring and the P3-D0 gates. One row per crossing_key, "
    "latest grade wins. direction in|out|both|no_cross|unclear|unknown (no_cross = came to the door, did not go through; unclear = seen, cannot tell; unknown = no "
    "door traversal visible); count = people who crossed or 'unknown'. Optional who = list from "
    "oji_udezue|ezinne|jaya|ziri|guest|unknown_person|cant_tell, guest_count = 1-8 when guest is in who, "
    "notes = free text; absent means not recorded. kind=pair rows index "
    "crossing_pass_key_pairs_2026_11_15.json (pair_label in its rubric)."
)


def http_get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read().decode("utf-8")


def http_post(url: str) -> None:
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def load_manifest(site: str, name: str = "manifest.json", local: Path = LOCAL_MANIFEST) -> dict:
    try:
        return json.loads(http_get(f"{site}/grade/{name}"))
    except Exception:  # noqa: BLE001 - fall back to the local copy
        try:
            return json.loads(local.read_text())
        except (FileNotFoundError, ValueError):
            return {"cards": []}


def merge_interior(incoming: list[dict], site: str, path: Path) -> tuple[int, list[dict]]:
    """Merge interior_desc grades into the interior fixture rows (latest grade per frame_key wins)."""
    cards = {c["frame_key"]: c for c in load_manifest(site, "manifest_interior.json",
                                                       LOCAL_INTERIOR_MANIFEST).get("cards", [])}
    try:
        existing = json.loads(path.read_text()).get("grades", [])
    except (FileNotFoundError, ValueError):
        existing = []
    by_key = {g["frame_key"]: g for g in existing}
    added = 0
    for g in sorted(incoming, key=lambda r: r.get("at", "")):
        key = g.get("frame_key")
        if not key:
            continue
        old = by_key.get(key) or {}
        if old and old.get("at", "") >= g.get("at", ""):
            continue
        card = cards.get(key, {})
        by_key[key] = {
            "frame_key": key,
            "people_count": g.get("people_count"),
            "description": g.get("description"),
            "note": g.get("note"),
            "at": g.get("at"),
            "batch": g.get("batch"),
            "room": card.get("room") or old.get("room"),
            "camera": card.get("camera") or old.get("camera"),
            "frame_at": card.get("at") or old.get("frame_at"),
            "nvr_bodies": (card.get("hidden") or {}).get("nvr_bodies", old.get("nvr_bodies")),
            "control": card.get("control", old.get("control")),
        }
        added += 1
    return added, sorted(by_key.values(), key=lambda r: (r.get("frame_at") or "", r["frame_key"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-clear", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--site", default=SITE, help="grading site base URL (default the urakanban webhost)")
    ap.add_argument("--labels", type=Path, default=LABELS_FILE)
    ap.add_argument("--interior-labels", type=Path, default=INTERIOR_LABELS_FILE)
    args = ap.parse_args()
    site = args.site.rstrip("/")

    raw = http_get(f"{site}/api/grades")
    incoming = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            incoming.append(json.loads(line))
        except ValueError:
            print(f"skip unparsable line: {line[:80]}", file=sys.stderr)
    if not incoming:
        print("no queued grades")
        return 0
    interior = [g for g in incoming if g.get("kind") == INTERIOR_KIND]
    incoming = [g for g in incoming if g.get("kind") != INTERIOR_KIND]

    cards = {c["crossing_key"]: c for c in load_manifest(site).get("cards", [])}
    try:
        existing = json.loads(args.labels.read_text()).get("grades", [])
    except (FileNotFoundError, ValueError):
        existing = []
    by_key = {g["crossing_key"]: g for g in existing}

    added = 0
    for g in sorted(incoming, key=lambda r: r.get("at", "")):
        key = g.get("crossing_key")
        if not key:
            continue
        old = by_key.get(key)
        if old and old.get("at", "") >= g.get("at", ""):
            continue
        card = cards.get(key, {})
        d = g.get("direction")
        row = {
            "crossing_key": key,
            "direction": d,
            "count": g.get("count"),
            "at": g.get("at"),
            "batch": g.get("batch"),
            "kind": card.get("kind") or (old or {}).get("kind"),
            "door_group": card.get("door_group") or (old or {}).get("door_group"),
            "e_ts": card.get("e_ts") or (old or {}).get("e_ts"),
            "direction_tracker_vocab": TRACKER_VOCAB.get(d),
        }
        for opt in OPTIONAL_FIELDS:  # absent stays absent (not recorded), never an empty default
            if opt in g:
                row[opt] = g[opt]
        if row["kind"] == "pair":
            row["pair_index"] = card.get("pair_index", (old or {}).get("pair_index"))
            row["e2_ts"] = card.get("e2_ts", (old or {}).get("e2_ts"))
            row["pair_label"] = PAIR_LABEL.get(d)
        by_key[key] = row
        added += 1

    grades = sorted(by_key.values(), key=lambda r: (r.get("e_ts") or "", r["crossing_key"]))
    print(f"{len(incoming)} queued, {added} new or regraded, {len(grades)} total in {args.labels}")
    i_added, i_grades = merge_interior(interior, site, args.interior_labels) if interior else (0, [])
    if interior:
        print(f"{len(interior)} interior queued, {i_added} new or regraded, {len(i_grades)} total in "
              f"{args.interior_labels}")
    if args.dry_run:
        for r in grades:
            print(r["crossing_key"], r["direction"], r["count"])
        for r in i_grades:
            print(r["frame_key"], r["people_count"], r["description"])
        return 0
    if incoming:
        args.labels.write_text(json.dumps({"description": DESCRIPTION, "grades": grades}, indent=1) + "\n")
    if interior:
        args.interior_labels.write_text(
            json.dumps({"description": INTERIOR_DESCRIPTION, "grades": i_grades}, indent=1) + "\n")
    if not args.no_clear:
        http_post(f"{site}/api/grades/clear")
        print("cleared server queue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
