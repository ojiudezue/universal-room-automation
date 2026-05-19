#!/usr/bin/env python3
"""Post-restart read-only validation against the running HA instance.

Usage:
    python3 scripts/post_restart_validation.py <cycle>

Where <cycle> is one of: v4.6.11, v4.6.12, v4.6.13, or "all".

This script performs NO HA actions — no HACS download, no restart, no
service calls. It only reads entity state and (where available) the URA
sqlite DB via a `template render` WS call. All actions are SELECT-only.

Designed for use when the user is remote and cannot watch the HA UI:
the user triggers HACS install + restart in their own UI; this script
verifies the rollout landed cleanly.

Reads the HA long-lived token from `.mcp.json` under
`mcpServers.home-assistant.env.HOMEASSISTANT_TOKEN`.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time

try:
    import websockets
except ImportError:
    print("websockets package not installed — `pip install websockets`", file=sys.stderr)
    sys.exit(2)


HA_WS_URL = "ws://192.168.13.13:8123/api/websocket"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_token() -> str:
    with open(REPO_ROOT / ".mcp.json") as f:
        cfg = json.load(f)
    return cfg["mcpServers"]["home-assistant"]["env"]["HOMEASSISTANT_TOKEN"]


async def _ws_call(ws, msg_id: int, msg_type: str, **kwargs):
    await ws.send(json.dumps({"id": msg_id, "type": msg_type, **kwargs}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == msg_id:
            return msg


async def _connect():
    token = _load_token()
    ws = await websockets.connect(HA_WS_URL, max_size=2**26, open_timeout=10)
    await ws.recv()  # auth_required
    await ws.send(json.dumps({"type": "auth", "access_token": token}))
    auth_resp = json.loads(await ws.recv())
    if auth_resp.get("type") != "auth_ok":
        raise RuntimeError(f"HA WS auth failed: {auth_resp}")
    return ws


# ---------------------------------------------------------------------------
# Per-cycle validation criteria
# ---------------------------------------------------------------------------


async def validate_v4611(states_map: dict) -> list[tuple[str, bool, str]]:
    """v4.6.11 acceptance criteria — see docs/reviews/code-review/v4.6.11_*.md."""
    out = []

    # Criterion 2: sensor.ura_safety_events_summary loads + returns int
    s = states_map.get("sensor.ura_safety_events_summary")
    ok = False
    msg = "missing"
    if s:
        try:
            int(s["state"])
            ok = True
            msg = f"state={s['state']} attrs={list(s.get('attributes', {}).keys())}"
        except (ValueError, TypeError):
            msg = f"state not int: {s['state']!r}"
    out.append(("v4.6.11/2 safety_events_summary", ok, msg))

    # Criterion 3: CM summary health_status ∈ {green, orange, red}
    cm_summary_eids = [
        eid for eid in states_map
        if "coordinator_manager" in eid and "summary" in eid
    ]
    health_ok = False
    health_msg = f"no CM summary entity found (candidates={cm_summary_eids})"
    for eid in cm_summary_eids:
        attrs = states_map[eid].get("attributes", {})
        hs = attrs.get("health_status")
        if hs in ("green", "orange", "red"):
            health_ok = True
            health_msg = f"{eid} health_status={hs}"
            break
        else:
            health_msg = f"{eid} health_status={hs!r} (expected green/orange/red)"
    out.append(("v4.6.11/3 CM health_status", health_ok, health_msg))

    # Criterion 4: CM summary status_per_coordinator dict-shaped
    spc_ok = False
    spc_msg = "not found"
    for eid in cm_summary_eids:
        attrs = states_map[eid].get("attributes", {})
        spc = attrs.get("status_per_coordinator")
        if isinstance(spc, dict):
            sample = next(iter(spc.values()), {})
            needed = {"status", "active_anomalies", "enabled"}
            if isinstance(sample, dict) and needed.issubset(sample.keys()):
                spc_ok = True
                spc_msg = f"{eid} coordinators={list(spc.keys())}"
                break
            else:
                spc_msg = f"{eid} sample={sample} missing keys"
        else:
            spc_msg = f"{eid} status_per_coordinator type={type(spc).__name__}"
    out.append(("v4.6.11/4 CM status_per_coordinator", spc_ok, spc_msg))

    return out


async def validate_v4612(states_map: dict) -> list[tuple[str, bool, str]]:
    """v4.6.12 acceptance criteria — see docs/readmes/README_v4.6.12.md."""
    out = []

    motion = states_map.get("sensor.ura_zones_with_motion")
    ok = False
    msg = "missing"
    if motion:
        try:
            v = int(motion["state"])
            ok = v >= 0
            msg = f"state={v} attrs={list(motion.get('attributes', {}).keys())}"
        except (ValueError, TypeError):
            msg = f"state not int: {motion['state']!r}"
    out.append(("v4.6.12/1 zones_with_motion", ok, msg))

    hvac = states_map.get("sensor.ura_hvac_system_demand")
    ok = False
    msg = "missing"
    if hvac:
        st = hvac["state"]
        if st in ("unknown", "unavailable"):
            ok = True
            msg = f"state={st} (acceptable — no HVAC coord OR zero zones)"
        else:
            try:
                v = int(st)
                ok = 0 <= v <= 100
                msg = f"state={v} attrs={list(hvac.get('attributes', {}).keys())}"
            except (ValueError, TypeError):
                msg = f"state not int: {st!r}"
    out.append(("v4.6.12/2 hvac_system_demand", ok, msg))

    grid = states_map.get("sensor.ura_energy_grid_demand")
    ok = False
    msg = "missing"
    if grid:
        st = grid["state"]
        if st in ("unknown", "unavailable"):
            ok = True
            msg = f"state={st} (acceptable — EC cap disabled OR coord missing)"
        else:
            try:
                v = float(st)
                ok = True
                msg = f"state={v} attrs={list(grid.get('attributes', {}).keys())}"
            except (ValueError, TypeError):
                msg = f"state not float: {st!r}"
    out.append(("v4.6.12/3 energy_grid_demand", ok, msg))

    return out


VALIDATORS = {
    "v4.6.11": validate_v4611,
    "v4.6.12": validate_v4612,
}


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target not in VALIDATORS and target != "all":
        print(f"Unknown cycle: {target}. Choose: {list(VALIDATORS)} or 'all'", file=sys.stderr)
        return 2

    print(f"[{time.strftime('%H:%M:%S')}] Connecting to HA WS...")
    try:
        ws = await _connect()
    except Exception as e:
        print(f"[FATAL] Cannot reach HA WebSocket at {HA_WS_URL}: {e}", file=sys.stderr)
        return 3

    async with ws:
        r = await _ws_call(ws, 1, "get_states")
        states = r.get("result", [])
        states_map = {s["entity_id"]: s for s in states}
        print(f"[{time.strftime('%H:%M:%S')}] Loaded {len(states)} entities")

        # Get HA version + URA version for sanity
        config = await _ws_call(ws, 2, "get_config")
        ha_version = config.get("result", {}).get("version")
        print(f"  HA version: {ha_version}")

        ura_update = (
            states_map.get("update.universal_room_automation")
            or states_map.get("update.ura")
        )
        if ura_update:
            ua = ura_update.get("attributes", {})
            print(f"  URA installed: {ua.get('installed_version')}  latest: {ua.get('latest_version')}")

    cycles = list(VALIDATORS.keys()) if target == "all" else [target]
    all_pass = True
    for c in cycles:
        print(f"\n=== {c} ===")
        results = await VALIDATORS[c](states_map)
        for name, ok, msg in results:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {name}: {msg}")
            if not ok:
                all_pass = False

    print()
    print(f"OVERALL: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
