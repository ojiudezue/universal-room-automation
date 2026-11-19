#!/usr/bin/env python3
"""Build one crossing-grading batch for the LAN grading page (urakanban /grade/).

Crossing vision P3-D6 needs human direction and count truth (PLANNING_crossing_vision.md, P3-D6 oracles and
P2-D10 grading). This script picks crossings, pulls each clip window through HA's Frigate proxy (never Frigate
directly), cuts a contact sheet per door camera with ffmpeg, and writes manifest.json plus the JPEGs into the
homelab site's grade/ directory. The page hides what the tracker and vision said until the grade is saved.

Sources (all on by default):
  * pairs: the unlabelled (label_basis == "not_viewed") pass-key pairs in
    quality/tests/fixtures/crossing_pass_key_pairs_2026_11_15.json. One card covers both crossings
    (E1 - pad .. E2 + pad); crossing_key = "passkey_pair_2026_11_15:<index>".
  * recent: crossings with a crossing_vision_shadow row in the last --recent-days (URA DB, read-only over
    `ssh ha`). Disagreements (case B / C), vision groups and counts >= 2 first. crossing_key is the
    production key "<egress_camera>@<crossing ts>".
  * --key KEY (repeatable): explicit production crossing keys.
  * --regrade-names: already-graded crossings where names matter (URA attached a person_id, or the D8a
    egress_identity_outcome row shows a face leg, a veto or an edge anchor) plus the step 7 D0 candidates
    (REGRADE_D0_TIMES). These bypass the graded skip; their cards carry "regrade": true.
Keys already in the grades labels file (pull_grades.py output) are skipped, except --regrade-names keys.
Every crossing card's hidden block carries revealed (crossing_identity): person_id (URA slug or null, from the
crossing record), confidence, outcome, outcome_slug, identity_provenance, identity_confidence, edge_anchor.

Cameras come from the configured door_groups option of the URA config entry (keys are Frigate camera names)
and the shadow row's door_group; nothing is inferred from entity-id strings. A key with no shadow row gets its
door group from its own egress camera through the registries (egress_door_group: entity -> device -> Frigate
camera identifier, or for a non-Frigate device its area's configured door cameras when they share one group). A
key whose door still cannot be resolved is dropped and logged; a card never shows sheets from several doors.

Privacy: the images are family footage. They go only to the LAN site directory (gitignored in
homelab-automation) and a local cache under .claude/tmp/grade_cache. Each run replaces the previous batch, and
the deploy's rsync --delete removes the old batch from the server.

Token: read from the macOS keychain (security -a oc_eval -s HA_TOKEN) into a variable, sent only as an HTTP
header, never printed or put on a command line.

Usage:
  python3 scripts/grading/make_grade_batch.py                 # default batch
  python3 scripts/grading/make_grade_batch.py --dry-run       # list what would be graded
  python3 scripts/grading/make_grade_batch.py --no-pairs --recent-days 1 --max-recent 30
  python3 scripts/grading/make_grade_batch.py --key 'sensor.doorbell_lite_person_count@2026-11-15T13:34:05.977844-06:00'
Then deploy the site (see the report / docs in homelab-automation docs/urakanban-hosting.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAIRS_FIXTURE = REPO / "quality/tests/fixtures/crossing_pass_key_pairs_2026_11_15.json"
PAIRS_KEY_PREFIX = "passkey_pair_2026_11_15:"
LABELS_FILE = REPO / "quality/tests/fixtures/crossing_operator_grades.json"
CACHE_DIR = REPO / ".claude/tmp/grade_cache"
EVENT_SHEETS_DIR = REPO / ".claude/tmp"  # vision_eval_media_<event_id>.sheet.jpg from earlier evals
SITE_GRADE_DIR = Path.home() / "Code/homelab-automation/sites/urakanban/grade"
HA_URL = "http://192.168.13.13:8123"
DB_PATH = "/config/universal_room_automation/data/universal_room_automation.db"
CONFIG_ENTRIES = "/config/.storage/core.config_entries"
ENTITY_REGISTRY = "/config/.storage/core.entity_registry"
DEVICE_REGISTRY = "/config/.storage/core.device_registry"
FRIGATE_DOMAIN = "frigate"
URA_DOMAIN = "universal_room_automation"
DISAGREE_CASES = ("B", "C")
# P3-D3 review D MEDIUM-1: stability repeat rows (call_kind 'repeat') share
# source_ref and started_at with their primary; grade the primary only (rows
# written before P3-D3 have no call_kind and are primaries).
PRIMARY_ONLY = "coalesce(json_extract({a}.attrs_json,'$.call_kind'),'primary')='primary'"
PERSON_IDS_SRC = REPO / "custom_components/universal_room_automation/person_ids.py"


def _person_slug_of():
    """The one person-id rule (person_ids.slug_of), loaded by file path: the module is pure (no HA imports),
    and importing it through the package would run the integration's __init__."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ura_person_ids", PERSON_IDS_SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.slug_of


slug_of = _person_slug_of()
EGRESS_OUTCOME_TYPE = "egress_identity_outcome"  # D8a outcome rows, source_ref = production crossing key
# person_entry_exit_events.timestamp is the UTC write time (database.log_entry_exit_event, datetime.utcnow()),
# written when direction resolves. Measured 2026-11-18 over 11-14..11-17: 110 of 113 same-direction rows land
# at +45.0 s (EGRESS_ENTRY_WINDOW_SECONDS); other rows in 0-180 s are neighbouring crossings on the same camera.
ENTRY_EXIT_LAG_EXPECTED_S = 45.0
ENTRY_EXIT_LAG_MIN_S = 40.0
ENTRY_EXIT_LAG_MAX_S = 55.0
# Step 7 D0 candidates (docs/planning/AUDIT_step7_d0_2026_11_17.md), local crossing times: always in
# --regrade-names whether graded or not. Matched to production keys by the key's own crossing ts.
REGRADE_D0_TIMES = (
    "2026-11-13T18:18:07", "2026-11-15T18:13:38", "2026-11-15T19:57:12", "2026-11-15T19:57:22",
    "2026-11-15T19:59:03", "2026-11-14T16:39:28",
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def ha_token() -> str:
    return subprocess.check_output(
        ["security", "find-generic-password", "-a", "oc_eval", "-s", "HA_TOKEN", "-w"]
    ).decode().strip()


def ssh_ha(cmd: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "ha", cmd],
        input=stdin, capture_output=True, text=True, check=True, timeout=120,
    ).stdout


def db_query(sql: str) -> list[dict]:
    out = ssh_ha(f"sqlite3 -readonly -json {DB_PATH}", stdin=sql)
    return json.loads(out) if out.strip() else []


def door_groups() -> dict[str, str]:
    """Configured {frigate_camera: door_group} from the URA config entry options."""
    data = json.loads(ssh_ha(f"cat {CONFIG_ENTRIES}"))
    for entry in data["data"]["entries"]:
        if entry.get("domain") != URA_DOMAIN:
            continue
        for src in ("options", "data"):
            groups = (entry.get(src) or {}).get("door_groups")
            if isinstance(groups, dict) and groups:
                return {str(k): str(v) for k, v in groups.items()}
    return {}


_REGISTRY: dict = {}


def _registries() -> tuple[dict, dict]:
    """(entity_id -> entity registry row, device_id -> device registry row), read once over ssh."""
    if not _REGISTRY:
        ents = json.loads(ssh_ha(f"cat {ENTITY_REGISTRY}"))["data"]["entities"]
        devs = json.loads(ssh_ha(f"cat {DEVICE_REGISTRY}"))["data"]["devices"]
        _REGISTRY["ents"] = {e["entity_id"]: e for e in ents}
        _REGISTRY["devs"] = {d["id"]: d for d in devs}
    return _REGISTRY["ents"], _REGISTRY["devs"]


def _frigate_camera(device: dict | None) -> str | None:
    """The Frigate camera a device registry row represents, from its ("frigate", "<entry>:<camera>") identifier."""
    for ident in (device or {}).get("identifiers") or []:
        if len(ident) == 2 and ident[0] == FRIGATE_DOMAIN and ":" in ident[1]:
            return ident[1].split(":", 1)[1]
    return None


def egress_door_group(egress_camera: str, groups: dict[str, str]) -> tuple[str | None, str]:
    """Door group of a crossing key's egress camera entity, through the registries only.

    entity registry -> device -> that device's Frigate camera -> door_groups option. A non-Frigate device (e.g. a
    UniFi Protect camera, whose registry row carries no Frigate identifier) resolves through its device AREA: the
    configured door cameras whose Frigate devices sit in the same area, accepted only when they all belong to one
    door group. Returns (group or None, route) and never parses the entity id.
    """
    ents, devs = _registries()
    ent = ents.get(egress_camera)
    if not ent:
        return None, "not in entity registry"
    dev = devs.get(ent.get("device_id") or "")
    if not dev:
        return None, "no device"
    cam = _frigate_camera(dev)
    if cam is not None:
        return (groups.get(cam), "frigate device") if cam in groups else (None, f"frigate camera {cam} not a door")
    area = dev.get("area_id")
    if not area:
        return None, f"{ent.get('platform')} device has no area"
    found = {groups[c] for d in devs.values() if d.get("area_id") == area
             for c in [_frigate_camera(d)] if c in groups}
    if len(found) == 1:
        return found.pop(), f"{ent.get('platform')} device area {area}"
    return None, f"{ent.get('platform')} device area {area} -> {sorted(found) or 'no door camera'}"


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def when_local(ts: dt.datetime) -> str:
    return ts.strftime("%a %d %b %H:%M:%S")


def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def already_graded() -> set[str]:
    try:
        data = json.loads(LABELS_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return set()
    return {g["crossing_key"] for g in data.get("grades", []) if g.get("crossing_key")}


# ---------- answers the page hides until after the grade ----------
def vision_answer(attrs: dict | None) -> dict | None:
    if not attrs:
        return None
    out = {
        "outcome": attrs.get("outcome"),
        "people_count": attrs.get("people_count"),
        "group": attrs.get("group"),
        "frame_counts": attrs.get("frame_counts"),
    }
    for k in ("vision_direction", "direction_vision", "vision_direction_confidence"):
        if k in attrs:
            out[k] = attrs[k]
    if attrs.get("desc"):
        out["desc"] = attrs["desc"]
    return out


def tracker_answer(shadow: dict | None, egress: dict | None) -> dict:
    out: dict = {}
    if egress:
        out["direction"] = egress.get("direction")
        out["egress_outcome"] = egress.get("outcome")
    elif shadow:
        out["direction"] = shadow.get("direction")
    if shadow:
        out["camera_peak_count"] = shadow.get("camera_peak_count")
        out["agreement_case"] = shadow.get("agreement_case")
    return out


# ---------- candidate selection ----------
def recent_candidates(days: float, limit: int, skip: set[str]) -> list[dict]:
    since = (dt.datetime.now().astimezone() - dt.timedelta(days=days)).isoformat()
    rows = db_query(
        "select v.source_ref, v.started_at, v.attrs_json, e.attrs_json as egress_attrs "
        "from memory_episodes v left join memory_episodes e "
        "on e.episode_type='egress_identity_outcome' and e.source_ref=v.source_ref "
        f"where v.episode_type='crossing_vision_shadow' and v.started_at >= {sql_str(since)} "
        f"and {PRIMARY_ONLY.format(a='v')} "
        "order by v.started_at desc;"
    )
    seen: set[str] = set()
    cands = []
    for r in rows:
        key = r["source_ref"]
        if not key or key in seen or key in skip:
            continue
        seen.add(key)
        sh = json.loads(r["attrs_json"] or "{}")
        eg = json.loads(r["egress_attrs"]) if r.get("egress_attrs") else None
        pc = sh.get("people_count")
        prio = 0 if sh.get("agreement_case") in DISAGREE_CASES else 1
        if sh.get("group") or (isinstance(pc, int) and pc >= 2):
            prio = min(prio, 0)
        cands.append({
            "kind": "crossing", "crossing_key": key, "e_ts": key.split("@", 1)[1],
            "door_group": sh.get("door_group"), "shadow": sh, "egress": eg, "prio": prio,
        })
    cands.sort(key=lambda c: c["prio"])  # stable: newest first within a band
    return cands[:limit]


def pair_candidates(limit: int, skip: set[str]) -> list[dict]:
    data = json.loads(PAIRS_FIXTURE.read_text())
    out = []
    for p in data["pairs"]:
        if p.get("label_basis") != "not_viewed":
            continue
        key = f"{PAIRS_KEY_PREFIX}{p['index']}"
        if key in skip:
            continue
        out.append({
            "kind": "pair", "crossing_key": key, "e_ts": p["e1"], "e2_ts": p["e2"],
            "door_group": p["door_group"], "pair": p,
        })
    return out[:limit]


def key_candidates(keys: list[str], skip: set[str]) -> list[dict]:
    out = []
    for key in keys:
        if key in skip or "@" not in key:
            log(f"skip key (graded or not '<camera>@<ts>'): {key}")
            continue
        rows = db_query(
            "select v.attrs_json, e.attrs_json as egress_attrs from (select 1) "
            "left join memory_episodes v on v.episode_type='crossing_vision_shadow' "
            f"and v.source_ref={sql_str(key)} and {PRIMARY_ONLY.format(a='v')} "
            "left join memory_episodes e on e.episode_type='egress_identity_outcome' "
            f"and e.source_ref={sql_str(key)} limit 1;"
        )
        r = rows[0] if rows else {}
        sh = json.loads(r["attrs_json"]) if r.get("attrs_json") else None
        eg = json.loads(r["egress_attrs"]) if r.get("egress_attrs") else None
        out.append({
            "kind": "crossing", "crossing_key": key, "e_ts": key.split("@", 1)[1],
            "door_group": (sh or {}).get("door_group"), "shadow": sh, "egress": eg,
        })
    return out


def crossing_identity(keys: list[str]) -> dict[str, dict]:
    """What URA named for each production crossing key, for the page's after-save reveal.

    person_id / confidence come from the crossing record (person_entry_exit_events: same egress_camera, same
    direction as the D8a row, written ENTRY_EXIT_LAG_MIN_S..MAX_S after the crossing ts, nearest to 45 s). An
    ambiguous crossing writes no record, so its person_id is null. outcome / slug / identity_provenance /
    identity_confidence / edge_anchor come from the D8a outcome row (egress_identity_outcome, source_ref = key).
    The D8a slug is reported separately: on a vetoed or abstained row it is the name URA did NOT attach.
    """
    keys = [k for k in keys if "@" in k]
    if not keys:
        return {}
    out: dict[str, dict] = {k: {} for k in keys}
    rows = db_query(
        "select source_ref, attrs_json from memory_episodes "
        f"where episode_type='{EGRESS_OUTCOME_TYPE}' and source_ref in ({','.join(sql_str(k) for k in keys)});"
    )
    for r in rows:
        a = json.loads(r["attrs_json"] or "{}")
        rev = out[r["source_ref"]]
        rev["outcome"] = a.get("outcome")
        rev["direction"] = a.get("direction")
        rev["outcome_slug"] = slug_of(a.get("slug")) or None
        if a.get("provenance") is not None:
            rev["identity_provenance"] = a["provenance"]
        if a.get("identity_confidence") is not None:
            rev["identity_confidence"] = a["identity_confidence"]
        if a.get("edge_anchor"):
            rev["edge_anchor"] = a["edge_anchor"]
    utc = {}
    for k in keys:
        cam, ts = k.split("@", 1)
        utc[k] = (cam, parse_ts(ts).astimezone(dt.timezone.utc).replace(tzinfo=None))
    lo = min(t for _c, t in utc.values())
    hi = max(t for _c, t in utc.values()) + dt.timedelta(seconds=ENTRY_EXIT_LAG_MAX_S)
    cams = sorted({c for c, _t in utc.values()})
    ee = db_query(
        "select timestamp, egress_camera, direction, person_id, confidence from person_entry_exit_events "
        f"where timestamp >= {sql_str(lo.isoformat())} and timestamp <= {sql_str(hi.isoformat())} "
        f"and egress_camera in ({','.join(sql_str(c) for c in cams)});"
    )
    for k, (cam, t) in utc.items():
        best = None
        rev = out[k]
        for r in ee:
            if r["egress_camera"] != cam:
                continue
            if rev.get("direction") and r["direction"] != rev["direction"]:
                continue
            lag = (dt.datetime.fromisoformat(r["timestamp"]) - t).total_seconds()
            if ENTRY_EXIT_LAG_MIN_S <= lag <= ENTRY_EXIT_LAG_MAX_S and (
                    best is None or abs(lag - ENTRY_EXIT_LAG_EXPECTED_S) < abs(best[0] - ENTRY_EXIT_LAG_EXPECTED_S)):
                best = (lag, r)
        if best:
            rev["person_id"] = slug_of(best[1]["person_id"]) or None  # slug per person_ids, None = unnamed
            rev["confidence"] = best[1]["confidence"]
            rev["crossing_record"] = True
        else:
            rev["person_id"] = None
            rev["crossing_record"] = False
    return out


def names_matter(rev: dict) -> bool:
    """A crossing whose names are worth a regrade: URA attached a person, or the D8a row shows a face leg,
    a veto or an edge anchor."""
    outcome = str(rev.get("outcome") or "")
    prov = str(rev.get("identity_provenance") or "")
    return bool(rev.get("person_id") or "face" in prov or "face" in outcome or outcome == "vetoed"
                or rev.get("edge_anchor"))


def regrade_name_candidates(graded: set[str]) -> list[dict]:
    """Already-graded crossings where names matter, plus the step 7 D0 candidates; these bypass the graded skip."""
    d0 = db_query(
        "select distinct source_ref from memory_episodes "
        f"where episode_type='{EGRESS_OUTCOME_TYPE}' and ("
        + " or ".join(f"source_ref like {sql_str('%@' + t + '%')}" for t in REGRADE_D0_TIMES) + ");"
    )
    d0_keys = [r["source_ref"] for r in d0]
    found = {t for t in REGRADE_D0_TIMES for k in d0_keys if f"@{t}" in k}
    for t in REGRADE_D0_TIMES:
        if t not in found:
            log(f"regrade-names: no production key for D0 crossing {t}")
    graded_keys = sorted(k for k in graded if "@" in k)
    ids = crossing_identity(graded_keys)
    picked = [k for k in graded_keys if names_matter(ids.get(k, {}))]
    keys = list(dict.fromkeys(d0_keys + picked))
    log(f"regrade-names: {len(d0_keys)} D0 keys, {len(picked)} of {len(graded_keys)} graded keys where names matter")
    cands = key_candidates(keys, set())
    for c in cands:
        c["regrade"] = c["crossing_key"] in graded
    return cands


def pair_vision(cands: list[dict]) -> None:
    """Attach shadow rows (if any) whose crossing ts equals a pair's e1 or e2."""
    stamps = sorted({c[k] for c in cands if c["kind"] == "pair" for k in ("e_ts", "e2_ts")})
    if not stamps:
        return
    rows = db_query(
        "select started_at, attrs_json from memory_episodes m where episode_type='crossing_vision_shadow' "
        f"and {PRIMARY_ONLY.format(a='m')} "
        f"and started_at in ({','.join(sql_str(s) for s in stamps)});"
    )
    by_ts = {r["started_at"]: json.loads(r["attrs_json"] or "{}") for r in rows}
    for c in cands:
        if c["kind"] == "pair":
            c["vision_rows"] = [by_ts.get(c["e_ts"]), by_ts.get(c["e2_ts"])]


# ---------- media ----------
def fetch_clip(token: str, instance: str, cam: str, start: float, end: float) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{cam}_{start:.0f}_{end:.0f}.mp4"
    if f.exists() and f.stat().st_size > 10_000:
        return f
    url = f"{HA_URL}/api/frigate/{instance}/recording/{cam}/start/{start:.3f}/end/{end:.3f}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
    except urllib.error.HTTPError as err:
        log(f"  {cam}: HTTP {err.code}")
        return None
    except (urllib.error.URLError, TimeoutError) as err:
        log(f"  {cam}: fetch failed ({err})")
        return None
    if len(body) < 10_000:
        log(f"  {cam}: empty clip ({len(body)} bytes)")
        return None
    f.write_bytes(body)
    return f


def duration_s(f: Path) -> float | None:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def make_sheet(clip: Path, out: Path, frames: int) -> bool:
    dur = duration_s(clip)
    if not dur or dur < 2:
        return False
    rows = (frames + 3) // 4
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf",
         f"fps={frames}/{dur:.2f},scale=420:-2,tile=4x{rows}", "-frames:v", "1", "-q:v", "5", str(out)],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and out.exists()


def build_card(c: dict, idx: int, groups: dict[str, str], token: str, args, out_dir: Path) -> dict | None:
    e1 = parse_ts(c["e_ts"])
    if c["kind"] == "pair":
        e2 = parse_ts(c["e2_ts"])
        start, end = e1.timestamp() - args.pair_pad_s, e2.timestamp() + args.pair_pad_s
    else:
        start, end = e1.timestamp() - args.pad_s, e1.timestamp() + args.pad_s
    group = c.get("door_group")
    cams = sorted(k for k, g in groups.items() if g == group) if group else []
    if not cams:
        # Never show every door: a sheet set from several doors cannot be graded as one crossing.
        log(f"  no door cameras for group {group!r} of {c['crossing_key']}; card dropped")
        return None
    win = end - start
    frames = 12 if win <= 26 else 20
    sheets = []
    for cam in cams:
        clip = fetch_clip(token, args.frigate_instance, cam, start, end)
        if clip is None:
            continue
        fname = f"c{idx:02d}_{cam}.jpg"
        if make_sheet(clip, out_dir / fname, frames):
            step = win / frames
            if c["kind"] == "pair":
                cap = (f"{frames} frames, one every {step:.1f} s, from {args.pair_pad_s:.0f} s before the first "
                       f"crossing to {args.pair_pad_s:.0f} s after the second")
            else:
                cap = f"{frames} frames, one every {step:.1f} s, crossing at the middle (±{args.pad_s:.0f} s)"
            sheets.append({"camera": cam, "file": fname, "caption": cap, "start": start, "end": end})
    shadow = c.get("shadow") or {}
    ev = shadow.get("event_id")
    if ev:
        src = EVENT_SHEETS_DIR / f"vision_eval_media_{ev}.sheet.jpg"
        if src.exists():
            fname = f"c{idx:02d}_event.jpg"
            shutil.copyfile(src, out_dir / fname)
            sheets.append({"camera": shadow.get("event_camera") or "event clip", "file": fname,
                           "caption": "the Frigate event clip vision was given"})
    if not sheets:
        log(f"  no media for {c['crossing_key']} (recording outside retention?); card dropped")
        return None
    card = {
        "crossing_key": c["crossing_key"], "kind": c["kind"], "door_group": group,
        "e_ts": c["e_ts"], "when_local": when_local(e1), "window_s": round(win), "sheets": sheets,
    }
    if c["kind"] == "pair":
        p = c["pair"]
        card["pair_index"] = p["index"]
        card["e2_ts"] = c["e2_ts"]
        card["prompt"] = ("Two crossings close together at this door. Direction: in, out, or both (a round "
                          "trip). Count the people who went through the door.")
        vis = [vision_answer(v) for v in c.get("vision_rows") or []]
        card["hidden"] = {
            "tracker": {"first": p["dir1"], "second": p["dir2"], "gap_s": p["gap_s"],
                        "times_approximate": p.get("crossing_time_approximate")},
            "vision": ({"first": json.dumps(vis[0]) if vis[0] else None,
                        "second": json.dumps(vis[1]) if len(vis) > 1 and vis[1] else None}
                       if any(vis) else None),
        }
    else:
        card["prompt"] = "Did anyone go through the door here? Direction and how many people."
        card["hidden"] = {
            "tracker": tracker_answer(c.get("shadow"), c.get("egress")),
            "vision": vision_answer(c.get("shadow")),
            # What URA named (crossing_identity); revealed with the other answers after the grade is saved.
            "revealed": c.get("revealed") or {"person_id": None},
        }
    if c.get("regrade"):
        card["regrade"] = True
    return card


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", action="append", default=[], help="production crossing key (repeatable)")
    ap.add_argument("--no-pairs", action="store_true")
    ap.add_argument("--no-recent", action="store_true")
    ap.add_argument("--recent-days", type=float, default=2.0)
    ap.add_argument("--max-recent", type=int, default=25)
    ap.add_argument("--max-pairs", type=int, default=50)
    ap.add_argument("--pad-s", type=float, default=10.0, help="seconds either side of a single crossing")
    ap.add_argument("--pair-pad-s", type=float, default=8.0, help="seconds before E1 / after E2 for a pair")
    ap.add_argument("--frigate-instance", default="frigate-f2")
    ap.add_argument("--site-dir", type=Path, default=SITE_GRADE_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--regrade-names", action="store_true",
                    help="add already-graded crossings where names matter, plus the step 7 D0 candidates "
                         "(bypass the graded skip)")
    args = ap.parse_args()

    skip = already_graded()
    cands: list[dict] = []
    if args.regrade_names:
        cands += regrade_name_candidates(skip)
    if args.key:
        cands += key_candidates(args.key, skip)
    if not args.no_recent:
        cands += recent_candidates(args.recent_days, args.max_recent, skip)
    if not args.no_pairs:
        cands += pair_candidates(args.max_pairs, skip)
    pair_vision(cands)
    dedup, seen = [], set()
    for c in cands:
        if c["crossing_key"] not in seen:
            seen.add(c["crossing_key"])
            dedup.append(c)
    groups = door_groups()
    if not groups:
        log("ERROR: no door_groups configured on the URA entry")
        return 1
    resolved = []
    for c in dedup:
        if c["kind"] == "crossing" and not c.get("door_group"):
            group, route = egress_door_group(c["crossing_key"].split("@", 1)[0], groups)
            if group is None:
                log(f"drop unresolved door ({route}): {c['crossing_key']}")
                continue
            c["door_group"] = group
            log(f"door {group} via {route}: {c['crossing_key']}")
        resolved.append(c)
    cands = resolved
    ids = crossing_identity([c["crossing_key"] for c in cands if c["kind"] == "crossing"])
    for c in cands:
        if c["kind"] == "crossing":
            c["revealed"] = ids.get(c["crossing_key"]) or {"person_id": None}
    log(f"{len(cands)} candidates ({sum(c['kind'] == 'pair' for c in cands)} pairs, "
        f"{sum(bool(c.get('regrade')) for c in cands)} regrades), {len(skip)} already graded")
    if args.dry_run:
        for c in cands:
            rev = c.get("revealed") or {}
            print(c["kind"], c.get("door_group"), "regrade" if c.get("regrade") else "new",
                  rev.get("person_id"), rev.get("outcome"), c["crossing_key"])
        return 0

    token = ha_token()
    out_dir: Path = args.site_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in list(out_dir.glob("c*.jpg")) + [out_dir / "manifest.json"]:
        if old.exists():
            old.unlink()  # keep only the current door batch (index.html and the interior i*.jpg batch stay)
    batch_id = dt.datetime.now().strftime("g%Y%m%d-%H%M")
    cards = []
    for c in cands:
        log(f"[{len(cards):02d}] {c['kind']} {c.get('door_group')} {c['crossing_key']}")
        card = build_card(c, len(cards), groups, token, args, out_dir)
        if card:
            cards.append(card)
    manifest = {"batch_id": batch_id, "generated_at": dt.datetime.now().astimezone().isoformat(),
                "cards": cards}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    log(f"batch {batch_id}: {len(cards)} cards written to {out_dir}")
    for card in cards:
        print(card["kind"], card["door_group"], card["crossing_key"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
