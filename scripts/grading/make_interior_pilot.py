#!/usr/bin/env python3
"""Build the interior-vision D0(g) description pilot batch for the LAN grading page (/grade/?batch=interior).

PLANNING_vision_interior_sightings.md §9.D0 (g): 20 frames, operator grades the model's description. This script:

  1. reads the covered rooms from sensor.ura_interior_awareness (attribute `rooms`) and maps each room to its
     Frigate camera through the HA registries (area of the Frigate camera entity; registry platform `frigate`,
     never an entity-id string). Rooms whose area name differs are listed in ROOM_AREA.
  2. reads 3 days of recorder history of each room's Frigate `<camera>_person_count` sensor (resolved by
     registry unique_id `<cam>_person`) and picks moments: bodies >= 1 (count >= 2 preferred) plus a few
     long empty stretches in daylight as controls.
  3. pulls a 3 s recording around each moment through HA's Frigate proxy (never Frigate directly) and cuts
     one still with ffmpeg.
  4. describes each still with the D3 model path: llmvision `image_analyzer`, provider = the crossing-vision
     llmvision entry (URA option crossing_vision_provider_id, else the install default
     CROSSING_VISION_PROVIDER_ID when that entry exists), model CROSSING_VISION_MODEL, max_tokens
     CROSSING_VISION_MAX_TOKENS, target_width CROSSING_VISION_TARGET_WIDTH, store_in_timeline / use_memory /
     expose_images False, JSON with the §9.D3 schema. The still is staged in /config/universal_room_automation
     for the call (llmvision reads local paths only) and deleted right after. /media/llmvision/snapshots is listed before and after.
  5. writes grade/manifest_interior.json + i##_<camera>.jpg into the homelab site dir (gitignored, LAN only).

Hard cap: MAX_CALLS model calls per run (20). Token from the keychain, header only, never printed.

Usage:
  python3 scripts/grading/make_interior_pilot.py --dry-run   # list the chosen moments, no fetch, no call
  python3 scripts/grading/make_interior_pilot.py             # build the batch (<= 20 calls)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SITE_GRADE_DIR = Path.home() / "Code/homelab-automation/sites/urakanban/grade"
CACHE_DIR = REPO / ".claude/tmp/grade_cache/interior"
HA_URL = "http://192.168.13.13:8123"
FRIGATE_INSTANCE = "frigate-f2"
AWARENESS = "sensor.ura_interior_awareness"
URA_DOMAIN = "universal_room_automation"
# URA room name -> HA area name, only where they differ (registry areas, not entity ids).
ROOM_AREA = {"Staircase": "Stairs"}
EXCLUDED_ROOM_WORDS = ("bedroom", "bath")  # hard constraint: never

# D3 model path (const.py CROSSING_VISION_*; plan §9 "Provider, model, kill" REUSE row).
MODEL = "gpt-6-luna"                       # CROSSING_VISION_MODEL
MAX_TOKENS = 4000                          # CROSSING_VISION_MAX_TOKENS
TARGET_WIDTH = 768                         # CROSSING_VISION_TARGET_WIDTH
DEFAULT_PROVIDER_ID = "01M7B731T26P2HXVW77AQR62PP"  # CROSSING_VISION_PROVIDER_ID
CONF_PROVIDER = "crossing_vision_provider_id"
MAX_CALLS = 20
# llmvision reads local paths only. The still is staged for the call in URA's own config dir (written over the
# Samba mount of /config, the ssh user cannot write there) and deleted right after the call.
HA_STAGE_DIR = "/config/universal_room_automation"
LOCAL_STAGE_DIR = Path.home() / "ha-config/universal_room_automation"

# §9.D3 schema: {people, activities: [{what, where_in_room}], context, confidence} + affect (AFFECT_ENABLED True).
SCHEMA = {
    "type": "object",
    "properties": {
        "people": {"type": "integer", "minimum": 0},
        "activities": {"type": "array", "items": {
            "type": "object",
            "properties": {"what": {"type": "string"}, "where_in_room": {"type": "string"}},
            "required": ["what", "where_in_room"], "additionalProperties": False}},
        "context": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "affect": {"type": "array", "items": {
            "type": "object",
            "properties": {"mood": {"type": "string"}, "energy": {"type": "string"}},
            "required": ["mood", "energy"], "additionalProperties": False}},
    },
    "required": ["people", "activities", "context", "confidence", "affect"],
    "additionalProperties": False,
}
PROMPT = (
    "This is one still frame from a camera inside a shared room of a house ({room}). Describe what is happening "
    "right now. people: how many people are visible (0 if none). activities: one entry per thing being done, "
    "with what it is and where in the room. context: one short sentence about the scene. affect: for each "
    "visible person, their apparent mood and energy (observational only). confidence: 0 to 1. Never name "
    "anyone or guess who they are; say 'a person', 'an adult' or 'a child'. Do not describe anything you "
    "cannot see. If no one is visible, people is 0 and activities and affect are empty."
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def ha_token() -> str:
    return subprocess.check_output(
        ["security", "find-generic-password", "-a", "oc_eval", "-s", "HA_TOKEN", "-w"]).decode().strip()


def ssh_ha(cmd: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["ssh", "-o", "ConnectTimeout=10", "ha", cmd], input=stdin,
                          capture_output=True, check=True, timeout=120).stdout


def ha_get(token: str, path: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(HA_URL + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def ha_post(token: str, path: str, body: dict, timeout: int = 150) -> dict:
    req = urllib.request.Request(HA_URL + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def storage(name: str) -> dict:
    return json.loads(ssh_ha(f"cat /config/.storage/{name}"))


# ---------- registry ----------
def room_cameras(token: str) -> dict[str, dict]:
    st = json.loads(ha_get(token, f"/api/states/{AWARENESS}"))
    rooms = list((st.get("attributes") or {}).get("rooms") or {})
    ents = storage("core.entity_registry")["data"]["entities"]
    devs = {d["id"]: d for d in storage("core.device_registry")["data"]["devices"]}
    areas = {a["id"]: a["name"] for a in storage("core.area_registry")["data"]["areas"]}
    by_uid = {e.get("unique_id"): e for e in ents if e["platform"] == "frigate"}
    out: dict[str, dict] = {}
    for room in rooms:
        if any(w in room.lower() for w in EXCLUDED_ROOM_WORDS):
            continue
        area = ROOM_AREA.get(room, room)
        cams = []
        for e in ents:
            if e["platform"] != "frigate" or not e["entity_id"].startswith("camera.") or e.get("disabled_by"):
                continue
            a = e.get("area_id") or (devs.get(e.get("device_id")) or {}).get("area_id")
            if areas.get(a) == area:
                cams.append(e)
        if len(cams) != 1:
            log(f"  {room}: {len(cams)} Frigate cameras in area {area!r}; skipped")
            continue
        uid = cams[0]["unique_id"]              # "<frigate entry>:camera:<frigate cam name>"
        prefix, _, cam = uid.rpartition(":camera:")
        sens = by_uid.get(f"{prefix}:sensor_object_count:{cam}_person")
        if not sens:
            log(f"  {room}: no person_count sensor for {cam}; skipped")
            continue
        out[room] = {"camera": cam, "camera_entity": cams[0]["entity_id"], "count_sensor": sens["entity_id"]}
    return out


def provider_id() -> str | None:
    data = storage("core.config_entries")["data"]["entries"]
    opt = None
    for entry in data:
        if entry.get("domain") == URA_DOMAIN:
            for src in ("options", "data"):
                v = (entry.get(src) or {}).get(CONF_PROVIDER)
                if v:
                    opt = str(v)
    ids = {e["entry_id"] for e in data if e.get("domain") == "llmvision"}
    for cand in (opt, DEFAULT_PROVIDER_ID):
        if cand and cand in ids:
            return cand
    return None


# ---------- moment selection ----------
def segments(token: str, sensor: str, days: float) -> list[tuple[dt.datetime, dt.datetime, int]]:
    start = (dt.datetime.now().astimezone() - dt.timedelta(days=days)).isoformat()
    path = (f"/api/history/period/{urllib.parse.quote(start)}?filter_entity_id={sensor}"
            "&minimal_response&no_attributes")
    hist = json.loads(ha_get(token, path, timeout=120))
    rows = hist[0] if hist else []
    pts = []
    for r in rows:
        ts = r.get("last_changed")
        try:
            pts.append((dt.datetime.fromisoformat(ts).astimezone(), int(float(r["state"]))))
        except (TypeError, ValueError, KeyError):
            pts.append((dt.datetime.fromisoformat(ts).astimezone(), -1)) if ts else None
    now = dt.datetime.now().astimezone()
    out = []
    for i, (t, c) in enumerate(pts):
        end = pts[i + 1][0] if i + 1 < len(pts) else now
        if c >= 0:
            out.append((t, end, c))
    return out


def pick(cams: dict[str, dict], token: str, days: float, people_per_room: int, extra: int, empties: int):
    people, empty = [], []
    for room, info in cams.items():
        segs = segments(token, info["count_sensor"], days)
        occ = [s for s in segs if s[2] >= 1 and (s[1] - s[0]).total_seconds() >= 4]
        occ.sort(key=lambda s: (-min(s[2], 3), -(s[1] - s[0]).total_seconds()))
        chosen, hours = [], set()
        for s in occ:  # spread over different hours
            h = s[0].strftime("%m%d%H")
            if h in hours:
                continue
            hours.add(h)
            chosen.append(s)
        for s in chosen:
            people.append((room, info, s))
        quiet = [s for s in segs if s[2] == 0 and (s[1] - s[0]).total_seconds() >= 900
                 and 9 <= (s[0] + (s[1] - s[0]) / 2).hour <= 20]
        if quiet:
            empty.append((room, info, quiet[len(quiet) // 2]))
        log(f"  {room} ({info['camera']}): {len(occ)} occupied segments, {len(quiet)} long empty")
    out, per_room = [], {}
    for room, info, s in people:  # first pass: people_per_room each
        if per_room.get(room, 0) < people_per_room:
            per_room[room] = per_room.get(room, 0) + 1
            out.append((room, info, s))
    rest = sorted([p for p in people if p not in out], key=lambda p: -p[2][2])
    out += rest[:extra]
    out += empty[:empties]
    return out


# ---------- media + model ----------
def still(token: str, cam: str, at: dt.datetime, out: Path) -> bool:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    t = at.timestamp()
    clip = CACHE_DIR / f"{cam}_{t:.0f}.mp4"
    if not clip.exists():
        try:
            body = ha_get(token, f"/api/frigate/{FRIGATE_INSTANCE}/recording/{cam}/start/{t - 1:.3f}/end/{t + 2:.3f}",
                          timeout=120)
        except (urllib.error.URLError, TimeoutError) as err:
            log(f"    clip fetch failed: {err}")
            return False
        if len(body) < 10_000:
            log(f"    empty clip ({len(body)} bytes)")
            return False
        clip.write_bytes(body)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(clip), "-frames:v", "1",
                        "-q:v", "3", str(out)], capture_output=True, text=True)
    return r.returncode == 0 and out.exists() and out.stat().st_size > 5_000


def snapshots_listing() -> list[str]:
    try:
        return sorted(ssh_ha("ls /media/llmvision/snapshots 2>/dev/null || true").decode().split())
    except subprocess.CalledProcessError:
        return []


def describe(token: str, img: Path, room: str, provider: str | None) -> dict:
    remote = f"{HA_STAGE_DIR}/ura_ipilot_{img.stem}.jpg"
    local = LOCAL_STAGE_DIR / f"ura_ipilot_{img.stem}.jpg"
    local.write_bytes(img.read_bytes())
    data = {
        "message": PROMPT.format(room=room), "image_file": remote, "model": MODEL,
        "max_tokens": MAX_TOKENS, "target_width": TARGET_WIDTH, "include_filename": False,
        "generate_title": False, "store_in_timeline": False, "use_memory": False, "expose_images": False,
        "response_format": "json", "structure": json.dumps(SCHEMA, separators=(",", ":")),
    }
    if provider:
        data["provider"] = provider
    t0 = dt.datetime.now()
    try:
        resp = ha_post(token, "/api/services/llmvision/image_analyzer?return_response", data)
        err = None
    except urllib.error.HTTPError as e:
        resp, err = {}, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError) as e:
        resp, err = {}, str(e)
    finally:
        local.unlink(missing_ok=True)
    latency = (dt.datetime.now() - t0).total_seconds()
    sr = resp.get("service_response") or {}
    if not isinstance(sr, dict):
        sr = {}
    # llmvision returns `structured_response` for response_format json, `response_text` otherwise.
    text = sr.get("structured_response") or sr.get("response_text")
    parsed = None
    if isinstance(text, dict):
        parsed = text
    elif isinstance(text, str):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
    if parsed is None and not err:
        err = f"unparsed response, keys={sorted(sr)}"
    return {"raw": text if isinstance(text, str) else None, "parsed": parsed, "error": err,
            "latency_s": round(latency, 1)}


def describe_text(p: dict | None, raw: str | None) -> str:
    if not p:
        return raw or "(no description returned)"
    parts = [f"People: {p.get('people')}."]
    for a in p.get("activities") or []:
        parts.append(f"{a.get('what')} ({a.get('where_in_room')}).")
    if p.get("context"):
        parts.append(p["context"])
    aff = [f"{x.get('mood')}/{x.get('energy')}" for x in p.get("affect") or []]
    if aff:
        parts.append("Affect: " + ", ".join(aff) + ".")
    if p.get("confidence") is not None:
        parts.append(f"Confidence {p['confidence']}.")
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=3.0)
    ap.add_argument("--people-per-room", type=int, default=2)
    ap.add_argument("--extra-people", type=int, default=3)
    ap.add_argument("--empties", type=int, default=3)
    ap.add_argument("--site-dir", type=Path, default=SITE_GRADE_DIR)
    ap.add_argument("--max-calls", type=int, default=MAX_CALLS, help=f"model call cap, <= {MAX_CALLS}")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cap = max(0, min(args.max_calls, MAX_CALLS))

    token = ha_token()
    cams = room_cameras(token)
    log(f"{len(cams)} covered rooms: {', '.join(r + '=' + c['camera'] for r, c in cams.items())}")
    moments = pick(cams, token, args.days, args.people_per_room, args.extra_people, args.empties)
    moments = moments[:cap]
    if args.dry_run:
        for room, info, (s, e, c) in moments:
            print(room, info["camera"], c, s.isoformat(), f"{(e - s).total_seconds():.0f}s")
        return 0
    prov = provider_id()
    log(f"provider: {'crossing-vision llmvision entry' if prov else 'llmvision default'}")
    before = snapshots_listing()
    out_dir: Path = args.site_dir
    for old in out_dir.glob("i*.jpg"):
        old.unlink()
    batch_id = dt.datetime.now().strftime("i%Y%m%d-%H%M")
    cards, calls = [], 0
    for room, info, (s, e, c) in moments:
        if calls >= cap:
            break
        span = (e - s).total_seconds()
        at = s + dt.timedelta(seconds=min(span / 2, 3.0) if c >= 1 else span / 2)
        idx = len(cards)
        fname = f"i{idx:02d}_{info['camera']}.jpg"
        log(f"[{idx:02d}] {room} bodies={c} {at.isoformat()}")
        if not still(token, info["camera"], at, out_dir / fname):
            continue
        calls += 1
        d = describe(token, out_dir / fname, room, prov)
        log(f"    {d['latency_s']} s, error={d['error']}, parsed={'yes' if d['parsed'] else 'no'}")
        if calls == 1 and not d["parsed"]:
            log(f"    first call failed, stopping to save budget: {d['error']} {str(d['raw'])[:300]}")
            return 2
        cards.append({
            "frame_key": f"interior:{info['camera']}@{at.isoformat()}", "kind": "interior_desc",
            "room": room, "camera": info["camera"], "at": at.isoformat(),
            "when_local": at.strftime("%a %d %b %H:%M:%S"), "file": fname, "control": c == 0,
            "description": describe_text(d["parsed"], d["raw"]), "description_json": d["parsed"],
            "model_error": d["error"], "latency_s": d["latency_s"],
            "hidden": {"nvr_bodies": c, "named_residents": None},
        })
    after = snapshots_listing()
    manifest = {"batch_id": batch_id, "kind": "interior_desc", "generated_at": dt.datetime.now().astimezone().isoformat(),
                "model_calls": calls, "snapshots_added": sorted(set(after) - set(before)), "cards": cards}
    (out_dir / "manifest_interior.json").write_text(json.dumps(manifest, indent=1))
    log(f"batch {batch_id}: {len(cards)} cards, {calls} model calls, "
        f"{len(manifest['snapshots_added'])} new files under /media/llmvision/snapshots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
