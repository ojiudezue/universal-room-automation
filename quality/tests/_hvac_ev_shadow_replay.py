"""INV-SHADOW replay fixture (HVAC-GUEST-EVIDENCE-RULE-1 phase 1, plan D0).

Drives the REAL `ZoneManager.update_room_conditions` (fake room coordinators,
fake config entries) through a deterministic scenario that covers every house
state, a hallway re-type, a coordinator-absent room, a refresh failure, a D5
away edge with W = 5 min, zone-scoped fast runs and a restart re-seed. After
every pass it snapshots every INV-SHADOW item (plan §2) that the producer
owns: each pre-existing ZoneManager dict, the zone rollup fields and the live
release helpers.

The golden (`golden/hvac_evidence_shadow_inv.json`) was captured with this
module on the PRE-BUILD source (commit recorded in the file). The build must
reproduce it byte-for-byte with `HVAC_EVIDENCE_SHADOW_ENABLED` True AND
False. The new shadow dicts are deliberately NOT in the snapshot (they are
the only allowed difference).

Capture:  PYTHONPATH=quality .venv-ha/bin/python quality/tests/_hvac_ev_shadow_replay.py --capture
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    ROOM_TYPE_HVAC_HOLD,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_zones as _hvac_zones,
)

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden", "hvac_evidence_shadow_inv.json")

T0 = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
SEED = 20261110

# Pre-existing ZoneManager per-room / per-zone state the producer writes
# (plan §2 INV-SHADOW list, plus the other pass-scoped producer state).
SNAP_DICTS = (
    "_hvac_output", "_hvac_rule", "_hvac_day_release_at", "_hvac_ev_released_at",
    "_hvac_pending", "_hvac_cold", "_hvac_exempt_reason",
    "_hvac_arm_onset", "_hvac_ep_armed", "_hvac_armed_at", "_hvac_arm_class",
    "_hvac_arm_span_s", "_hvac_dwell_s",
    "_hvac_episode_start", "_hvac_episode_onsets", "_hvac_episode_prev_ev",
    "_hvac_episode_closed_s", "_hvac_episode_active_s",
    "transit_filtered_today",
    "_hvac_armed", "_hvac_tail_until", "_hvac_arm_source", "_hvac_shadow_release_at",
    "_hvac_prev_state_occupied", "_hvac_last_ev", "_hvac_last_active",
)
SNAP_SETS = ("_hvac_seen", "_coordinator_absent_this_pass", "_rooms_processed_this_pass")

ZONES = {
    "zone_1": [("bed1", "bedroom"), ("kit", "common_area"), ("hall", "hallway"), ("clo", "closet")],
    "zone_2": [("media", "media_room"), ("gst", "bedroom"), ("bath", "bathroom")],
}

# (house_state, passes) segments. Every state, twice for the evidence states.
SEGMENTS = (
    ("home_day", 22), ("home_evening", 14), ("home_night", 12), ("sleep", 16),
    ("waking", 8), ("guest", 16), ("arriving", 6), ("away", 10), (None, 6),
    ("home_day", 18), ("guest", 12), ("home_evening", 10),
)


class _Entry:
    def __init__(self, room_name: str, room_type: str) -> None:
        from homeassistant.config_entries import ConfigEntryState
        self.entry_id = f"e_{room_name}"
        self.state = ConfigEntryState.LOADED
        self.disabled_by = None
        self.data = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            CONF_ROOM_NAME: room_name,
            CONF_ROOM_TYPE: room_type,
        }
        self.options: dict = {}


class _RoomCoord:
    """Fake room coordinator with the v5.103.20 accessor surface."""

    def __init__(self) -> None:
        self.data = {"occupied": False}
        self.ev: datetime | None = None
        self.active = False
        self.onset: datetime | None = None
        self.last_update_success = True

    def get_last_hvac_evidence_time(self):
        return self.ev

    def is_hvac_evidence_active(self):
        return self.active

    def get_hvac_evidence_onset(self):
        return self.onset


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_iso(x) for x in v]
    if isinstance(v, float):
        return round(v, 6)
    return v


def _snapshot(zm: Any, now: datetime) -> dict:
    snap: dict[str, Any] = {}
    for name in SNAP_DICTS:
        d = getattr(zm, name)
        snap[name] = {str(k): _iso(d[k]) for k in sorted(d, key=str)}
    for name in SNAP_SETS:
        snap[name] = sorted(getattr(zm, name, set()) or set())
    zones: dict[str, Any] = {}
    with patch.object(_hvac_zones.dt_util, "now", return_value=now), \
         patch.object(_hvac_zones.dt_util, "utcnow", return_value=now):
        for zid in sorted(zm.zones):
            z = zm.zones[zid]
            zones[zid] = {
                "any_room_hvac_occupied": bool(z.any_room_hvac_occupied),
                "any_room_occupied": bool(z.any_room_occupied),
                "last_occupied_time": _iso(z.last_occupied_time),
                "continuous_occupied_since": _iso(z.continuous_occupied_since),
                "current_session_start": _iso(z.current_session_start),
                "vacancy_sweep_done": bool(z.vacancy_sweep_done),
                "hvac_pending_arm_rooms": list(z.hvac_pending_arm_rooms or []),
                "room_conditions": [
                    [c.room_name, bool(c.occupied), bool(c.hvac_occupied)]
                    for c in z.room_conditions
                ],
                "zone_release_at": _iso(zm.zone_release_at(zid)),
                "room_release_at": {
                    r: _iso(zm.room_release_at(r)) for r in z.rooms
                },
            }
    snap["zones"] = zones
    return snap


class Replay:
    """Builds the world and steps it deterministically."""

    def __init__(self) -> None:
        self.entries = {r: _Entry(r, rt) for rooms in ZONES.values() for r, rt in rooms}
        self.coords = {r: _RoomCoord() for r in self.entries}
        self.hass = MagicMock()
        entries = list(self.entries.values())

        class _CEs:
            def async_entries(self, dom):
                return entries

        self.hass.config_entries = _CEs()
        self.hass.data = {DOMAIN: {}}
        self._sync_coords(absent=set())
        self.hass.states = MagicMock()
        self.hass.states.get = lambda ent_id: None
        self.zm = self._new_zm()
        self.light_until: dict[str, datetime | None] = {r: None for r in self.entries}
        self.phys: dict[str, bool] = {r: False for r in self.entries}

    def _sync_coords(self, absent: set[str]) -> None:
        dd = self.hass.data[DOMAIN]
        dd.clear()
        for r, e in self.entries.items():
            if r not in absent:
                dd[e.entry_id] = self.coords[r]

    def _new_zm(self) -> Any:
        zm = _hvac_zones.ZoneManager(self.hass)
        for zid, rooms in ZONES.items():
            z = _hvac_zones.ZoneState(zone_id=zid, zone_name=zid.upper(), climate_entity=f"climate.{zid}")
            z.rooms = [r for r, _rt in rooms]
            zm._zones[zid] = z
        return zm

    def _step_rooms(self, rng: random.Random, now: datetime) -> None:
        for r in sorted(self.entries):
            c = self.coords[r]
            p = 0.35 if self.phys[r] else 0.10
            if rng.random() < p:
                self.phys[r] = not self.phys[r]
                if self.phys[r]:
                    c.onset = now - timedelta(seconds=rng.randint(0, 50))
            if self.phys[r]:
                c.active = True
                c.ev = now - timedelta(seconds=rng.randint(0, 20))
                self.light_until[r] = now + timedelta(seconds=300)
            else:
                c.active = False
            lu = self.light_until[r]
            c.data = {"occupied": bool(self.phys[r] or (lu is not None and now < lu))}

    def run(self) -> list[dict]:
        rng = random.Random(SEED)
        now = T0
        passes: list[dict] = []
        n = 0
        away_edge = {"zone_1": False}

        def _edge(zid: str) -> bool:
            return bool(away_edge.get(zid, False))

        for seg_i, (hs, count) in enumerate(SEGMENTS):
            for j in range(count):
                n += 1
                prev = now
                now = now + timedelta(seconds=rng.choice((20, 45, 60, 90, 150, 300, 300, 420)))
                if n % 3 == 0:
                    # Boundary pass: land EXACTLY on an idle room's evidence
                    # release (ev + hold) or the refresh-fail bound (ev +
                    # 600), so a `<` -> `<=` edit on a live line changes the
                    # snapshot.
                    cands = []
                    for r, e in sorted(self.entries.items()):
                        c = self.coords[r]
                        if self.phys[r] or c.ev is None:
                            continue
                        ov = (e.options or {}).get("hvac_vacancy_hold")
                        hold = ov if ov is not None else ROOM_TYPE_HVAC_HOLD.get(
                            e.data[CONF_ROOM_TYPE], 60)
                        cands.append(c.ev + timedelta(seconds=hold))
                        cands.append(c.ev + timedelta(seconds=600))
                    cands = sorted(t for t in cands if t > prev)
                    if cands:
                        now = cands[0]
                self._step_rooms(rng, now)
                # --- scripted events -------------------------------------
                absent: set[str] = set()
                if 30 <= n <= 36:
                    absent.add("gst")                       # coordinator-absent room
                self._sync_coords(absent)
                self.coords["bath"].last_update_success = not (40 <= n <= 46 or 140 <= n <= 144)
                if n == 60:
                    self.entries["clo"].data[CONF_ROOM_TYPE] = "hallway"   # re-type
                if n == 72:
                    self.entries["clo"].data[CONF_ROOM_TYPE] = "closet"
                if n == 80:
                    self.entries["bed1"].options = {"hvac_vacancy_hold": 400}
                away_edge["zone_1"] = (hs == "home_day" and seg_i == 9 and j < 12) or (
                    hs == "home_day" and seg_i == 0 and 3 <= j < 10
                )
                if n == 120:
                    # Restart re-seed: a fresh ZoneManager; every room's
                    # evidence stamp is None until its next evidence.
                    self.zm = self._new_zm()
                    for r, c in self.coords.items():
                        if not self.phys[r]:
                            c.ev = None
                            c.onset = None
                zone_ids = None
                if j % 5 == 3:
                    zone_ids = {"zone_2"} if j % 2 else {"zone_1"}
                dwell = 300.0
                with patch.object(_hvac_zones.dt_util, "now", return_value=now), \
                     patch.object(_hvac_zones.dt_util, "utcnow", return_value=now):
                    self.zm.update_room_conditions(
                        house_state=hs, zone_ids=zone_ids, entry_dwell_s=dwell,
                        away_edge_fn=_edge, return_window_s=600.0,
                    )
                snap = _snapshot(self.zm, now)
                snap["_pass"] = {"n": n, "t": now.isoformat(), "house_state": hs,
                                 "zone_ids": sorted(zone_ids) if zone_ids else None}
                passes.append(snap)
        return passes


def run_replay() -> list[dict]:
    return Replay().run()


def load_golden() -> dict:
    with open(GOLDEN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _capture() -> None:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True,
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", "custom_components"], cwd=_REPO_ROOT, text=True,
    ).strip()
    if dirty:
        raise SystemExit("refusing to capture: production source is modified")
    passes = run_replay()
    os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
    with open(GOLDEN_PATH, "w", encoding="utf-8") as fh:
        json.dump({"capture_commit": commit, "seed": SEED, "passes": passes},
                  fh, sort_keys=True, separators=(",", ":"))
        fh.write("\n")
    print(f"captured {len(passes)} passes at {commit}")


if __name__ == "__main__":
    if "--capture" in sys.argv:
        _capture()
