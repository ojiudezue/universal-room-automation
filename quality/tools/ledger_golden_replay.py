"""SignalTrustLedger golden-fixture OFFLINE REPLAY HARNESS.

Implements the amended Criterion 4 of
``docs/planning/PLANNING_signal_trust_ledger_abstraction.md`` (OPERATOR
APPROVED 2026-08-13), per the yield method prototyped in
``docs/planning/AUDIT_ledger_golden_fixture_yield.md``.

Design principles
-----------------
* **Read-only** against all live DBs. Every sqlite handle is opened as
  ``file:...?mode=ro`` (URI). No production ``custom_components/`` code
  is modified.
* **Extraction, not invention.** The predicates reproduced here are
  copied from HEAD with explicit ``PROD-SOURCE`` citations. Where a
  detector is closed-loop (M2/P24) or cross-coordinator (M3/P18) or
  yields zero events in-window by design (M4/D1) or was removed
  altogether (M6/D3 — deleted 2026-08-10, see ``const.py:3512``), a
  **SKELETON** fixture is emitted instead of a fabricated one, per the
  audit's recommendation and per the operator's amendment which
  explicitly permits hand-built supplements.
* **Deterministic replay.** Re-running against the same window
  produces byte-identical fixtures modulo the ``generated_at`` field
  in the manifest (which is stable when the CLI is given
  ``--generation-date``).

CLI
---
Typical live use::

    python quality/tools/ledger_golden_replay.py \\
        --ssh-host ha \\
        --remote-db /config/home-assistant_v2.db \\
        --room-map-ssh /config/.storage/core.config_entries \\
        --out quality/fixtures/ledger_golden/ \\
        --window-days 7

Typical offline use (given a local recorder copy)::

    python quality/tools/ledger_golden_replay.py \\
        --db /tmp/home-assistant_v2.db \\
        --room-map /tmp/core.config_entries \\
        --out quality/fixtures/ledger_golden/
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

_LOGGER = logging.getLogger("ledger_golden_replay")


# ---------------------------------------------------------------------------
# PROD-SOURCE constants — copied from HEAD with citations, so a mismatch
# between this harness and production is a grep away. See CLAUDE.md
# "Numbers Get Knobs" — none of these are operator-tunable in the harness;
# they are pinned to what production computes.
# ---------------------------------------------------------------------------

# coordinator.py:283  self._stuck_sensor_hours = 4.0
PROD_STUCK_SENSOR_HOURS: float = 4.0

# const.py:3504 DEFAULT_STUCK_SENSOR_DUTYCYCLE_WINDOW_MIN
PROD_D2_WINDOW_MIN: int = 60
# const.py:3506 DEFAULT_STUCK_SENSOR_DUTYCYCLE_PCT
PROD_D2_PCT: float = 0.85
# const.py:3510 DEFAULT_STUCK_SENSOR_DUTYCYCLE_MIN_TICKS
PROD_D2_MIN_TICKS: int = 20
# const.py:3524 STUCK_D2_FRESH_MOTION_SECONDS
PROD_D2_FRESH_MOTION_S: int = 300
# const.py:3525 STUCK_D2_MIN_MOTION_TRANSITIONS
PROD_D2_MIN_MOTION_TRANSITIONS: int = 2

# coordinator.py:486  update_interval=timedelta(seconds=30 + jitter)
PROD_TICK_S: int = 30

# const.py:3492 DEFAULT_STUCK_CAMERA_HOURS (M4/D1)
PROD_D1_STUCK_HOURS: float = 3.0
# const.py:3537 STUCK_CAMERA_NEVERZERO_HOURS
PROD_D1_NEVERZERO_HOURS: float = 6.0

# const.py:3512 — D3 frozen_tracker check DELETED 2026-08-10.
D3_STATUS_NOTE: str = (
    "M6/D3 frozen_tracker detector DELETED 2026-08-10 (const.py:3512); "
    "structurally unreachable at deploy cadence per AUDIT §D3. Fixture "
    "kept as a SKELETON only so a re-introduction cycle has a slot."
)

# Restart burst detection (mirrors AUDIT §'Restart modelling'):
# clusters of >= 50 old_state_id IS NULL rows within 3 min over a
# 500-entity binary_sensor sample.
RESTART_CLUSTER_MIN_ROWS: int = 50
RESTART_CLUSTER_WINDOW_S: int = 180


# ---------------------------------------------------------------------------
# Per-bucket minimums per amended Criterion 4 (planning doc, 4b).
# ---------------------------------------------------------------------------

BUCKET_MINIMUMS: dict[str, int] = {
    "P22": 5,   # M1 continuous-on
    "P24": 5,   # M2 max-active failsafe (skeleton — closed-loop)
    "P18": 3,   # M3 zone stale-occupancy (skeleton — cross-coordinator)
    "D1":  3,   # M4 camera stuck-count (skeleton — never fires in-window)
    "D2":  3,   # M5 duty-cycle
    "D3":  1,   # M6 frozen tracker (skeleton — detector removed)
    "CHATTER": 3,  # 4b — transition-rate; not yet shipped
}


# ---------------------------------------------------------------------------
# Recorder access abstraction
# ---------------------------------------------------------------------------


@dataclass
class RecorderRow:
    metadata_id: int
    entity_id: str
    state: str
    ts: float
    old_state_id: int | None


class RecorderDB:
    """Read-only recorder access.

    Two backends: local sqlite file (``--db``) or remote via
    ``ssh <host> sqlite3`` (``--ssh-host`` + ``--remote-db``). All queries
    are scoped by ``metadata_id`` per the audit's read-only compliance
    (AUDIT §'Read-only compliance').
    """

    def __init__(
        self,
        *,
        local_path: str | None = None,
        ssh_host: str | None = None,
        remote_path: str | None = None,
    ) -> None:
        self._local_path = local_path
        self._ssh_host = ssh_host
        self._remote_path = remote_path
        self._conn: sqlite3.Connection | None = None
        if local_path:
            uri = f"file:{local_path}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True)
        elif not (ssh_host and remote_path):
            raise ValueError("must supply --db OR (--ssh-host + --remote-db)")

    # -- query primitives ---------------------------------------------------

    def _remote_query(self, sql: str) -> list[list[str]]:
        # Use tab separator + .mode tabs to preserve values w/ commas.
        script = f".mode tabs\n.headers off\n{sql}\n"
        cmd = [
            "ssh", self._ssh_host,
            f"sqlite3 -readonly 'file:{self._remote_path}?mode=ro'",
        ]
        proc = subprocess.run(
            cmd, input=script, capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"remote sqlite3 failed: {proc.stderr[:500]}"
            )
        rows = []
        for line in proc.stdout.splitlines():
            if not line:
                continue
            rows.append(line.split("\t"))
        return rows

    def _query(self, sql: str) -> list[list[str]]:
        if self._conn is not None:
            cur = self._conn.execute(sql)
            return [[("" if v is None else str(v)) for v in r] for r in cur]
        return self._remote_query(sql)

    # -- API ----------------------------------------------------------------

    def metadata_id_for(self, entity_id: str) -> int | None:
        rows = self._query(
            "SELECT metadata_id FROM states_meta WHERE entity_id="
            f"'{entity_id.replace(chr(39), chr(39)*2)}'"
        )
        if not rows:
            return None
        try:
            return int(rows[0][0])
        except (ValueError, IndexError):
            return None

    def state_history(
        self, metadata_id: int, since_ts: float,
    ) -> list[RecorderRow]:
        rows = self._query(
            "SELECT state, last_updated_ts, old_state_id FROM states "
            f"WHERE metadata_id={metadata_id} "
            f"AND last_updated_ts >= {since_ts} "
            "ORDER BY last_updated_ts"
        )
        out: list[RecorderRow] = []
        for r in rows:
            try:
                st = r[0]
                ts = float(r[1]) if r[1] else 0.0
                osid = int(r[2]) if r[2] not in ("", None) else None
            except (ValueError, IndexError):
                continue
            out.append(RecorderRow(
                metadata_id=metadata_id, entity_id="",
                state=st, ts=ts, old_state_id=osid,
            ))
        return out

    def restart_boundaries(self, since_ts: float) -> list[float]:
        """Detect HA restart timestamps in-window.

        Mirrors AUDIT §'Restart modelling': clusters of >=50
        ``old_state_id IS NULL`` rows within 3 minutes on binary_sensor.
        Sample scope: first 500 binary_sensor metadata_ids by id
        (matches the audit's discovery scope).
        """
        # Get binary_sensor metadata_ids.
        meta_rows = self._query(
            "SELECT metadata_id FROM states_meta "
            "WHERE entity_id LIKE 'binary_sensor.%' "
            "ORDER BY metadata_id LIMIT 500"
        )
        ids = [int(r[0]) for r in meta_rows if r and r[0]]
        if not ids:
            return []
        id_list = ",".join(str(i) for i in ids)
        rows = self._query(
            "SELECT last_updated_ts FROM states "
            f"WHERE metadata_id IN ({id_list}) "
            f"AND last_updated_ts >= {since_ts} "
            "AND old_state_id IS NULL "
            "ORDER BY last_updated_ts"
        )
        ts_list = []
        for r in rows:
            try:
                ts_list.append(float(r[0]))
            except (ValueError, IndexError):
                continue
        # Sliding window cluster detection.
        boundaries: list[float] = []
        i = 0
        while i < len(ts_list):
            j = i
            while (
                j < len(ts_list)
                and ts_list[j] - ts_list[i] <= RESTART_CLUSTER_WINDOW_S
            ):
                j += 1
            if (j - i) >= RESTART_CLUSTER_MIN_ROWS:
                boundaries.append(ts_list[i])
                i = j
            else:
                i += 1
        return boundaries


# ---------------------------------------------------------------------------
# Room-map loading (from HA .storage/core.config_entries).
# ---------------------------------------------------------------------------


def load_room_map(path: str) -> dict[str, dict[str, list[str]]]:
    """Parse ``.storage/core.config_entries`` for URA room entries.

    Returns a ``{room_name: {"motion":[...], "mmwave":[...],
    "occupancy":[...]}}`` mapping. Keys mirror how the coordinator reads
    them (``motion_sensors``, ``presence_sensors``, ``occupancy_sensors``
    — the last is ``CONF_MMWAVE_SENSORS`` alias per ``const.py:334``).
    """
    with open(path) as fh:
        data = json.load(fh)
    entries = data.get("data", {}).get("entries", [])
    rooms: dict[str, dict[str, list[str]]] = {}
    for e in entries:
        if e.get("domain") != "universal_room_automation":
            continue
        d = {**(e.get("data") or {}), **(e.get("options") or {})}
        room_name = d.get("room_name") or e.get("title")
        if not room_name:
            continue
        # Only room-type entries have sensors.
        m = [s for s in (d.get("motion_sensors") or []) if s]
        p = [s for s in (d.get("presence_sensors") or []) if s]
        o = [s for s in (d.get("occupancy_sensors") or []) if s]
        if not (m or p or o):
            continue
        rooms[room_name] = {"motion": m, "mmwave": p, "occupancy": o}
    return rooms


# ---------------------------------------------------------------------------
# Detector replays. Each function's docstring cites the HEAD site whose
# semantics it reproduces.
# ---------------------------------------------------------------------------


def _is_on(state: str) -> bool:
    # PROD-SOURCE coordinator.py:1906 _is_sensor_on — unavailable/unknown
    # count as off.
    return state == "on"


def replay_p22(
    rows: list[RecorderRow],
    entity_id: str,
    room_name: str,
    restart_ts: list[float],
    threshold_hours: float = PROD_STUCK_SENSOR_HOURS,
) -> list[dict[str, Any]]:
    """M1/P22 continuous-on detector.

    PROD-SOURCE coordinator.py:2117-2131 — book ``_sensor_on_since``,
    fire when ``(now - since) / 3600 >= _stuck_sensor_hours`` (=4.0h).

    Restart-aware per AUDIT §'Restart modelling': in-memory
    ``_sensor_on_since`` is cleared on each restart boundary.
    """
    threshold_s = threshold_hours * 3600.0
    since: float | None = None
    fired: list[dict[str, Any]] = []
    restart_iter = iter(sorted(restart_ts))
    next_restart: float | None = next(restart_iter, None)

    def _emit(since_ts: float, close_ts: float, cleared: bool) -> None:
        episode_h = (close_ts - since_ts) / 3600.0
        if episode_h < threshold_hours:
            return
        # Approximate fired_ts as since + threshold — production fires on
        # the first tick past threshold; the recorder does not carry ticks,
        # so we pin fired_ts to the earliest instant production would have
        # fired given the stream.
        fired.append({
            "bucket": "P22",
            "kind": "continuous",
            "room_name": room_name,
            "entity_id": entity_id,
            "since_ts": since_ts,
            "fired_ts": since_ts + threshold_s,
            "cleared_ts": close_ts if cleared else None,
            "episode_hours": round(episode_h, 3),
            "on_hours_at_fire": threshold_hours,
        })

    for row in rows:
        # Consume any restart before this row's ts.
        while next_restart is not None and next_restart <= row.ts:
            if since is not None:
                _emit(since, next_restart, cleared=True)
            since = None
            next_restart = next(restart_iter, None)
        on = _is_on(row.state)
        if on:
            if since is None:
                since = row.ts
        else:
            if since is not None:
                _emit(since, row.ts, cleared=True)
            since = None
    # Open-ended tail (still on at end of window). We don't have a
    # trailing tick to close it, so record it if it clearly crossed the
    # threshold based on window end.
    if since is not None and rows:
        end_ts = max(r.ts for r in rows)
        if (end_ts - since) >= threshold_s:
            _emit(since, end_ts, cleared=False)
    return fired


def replay_d2(
    room_name: str,
    room_sensors: dict[str, list[str]],
    histories: dict[str, list[RecorderRow]],
    restart_ts: list[float],
    since_ts: float,
    until_ts: float,
) -> list[dict[str, Any]]:
    """M5/D2 duty-cycle detector.

    PROD-SOURCE coordinator.py:1504-1714 (``_detect_duty_cycle_stuck``).
    Reproduces the 30s tick grid + rolling window ring + PIR
    corroboration shield exactly. Simplifications vs production:

      * ``resolve_role`` — under empty ``CONF_SENSOR_CAPABILITIES`` the
        candidate set equals ``mmwave + occupancy`` and corroborators
        equal ``motion`` (byte-identical fallback, I1 — see PLANNING
        §Criterion 4a note on SENSOR-CAPABILITY-1). This harness assumes
        the empty-capability path; a re-generation after
        SENSOR-CAPABILITY-1 lands must extend this replay.
      * Boot-settle gate (``_d2_boot_settle_done()``) is not
        reconstructable from the recorder (AUDIT limitation #2). This
        replay over-counts by however many verdicts production would
        have suppressed in each post-boot window; the manifest flags
        this so a reviewer can discount it.
    """
    motion = [s for s in room_sensors.get("motion", []) if s]
    mmwave = [s for s in room_sensors.get("mmwave", []) if s]
    occupancy = [s for s in room_sensors.get("occupancy", []) if s]

    # Order-preserving dedup — PROD-SOURCE coordinator.py:1671-1691.
    seen: set[str] = set()
    candidates: list[str] = []
    for s in mmwave + occupancy:
        if s and s not in seen:
            candidates.append(s)
            seen.add(s)
    if not candidates:
        return []

    window_s = PROD_D2_WINDOW_MIN * 60
    # Rings per candidate: deque[(mono, on_bool)].
    rings: dict[str, deque[tuple[float, bool]]] = {
        c: deque() for c in candidates
    }
    motion_deque: deque[float] = deque()
    last_motion_state: dict[str, bool] = {}
    # Per-day dedup — production fires NM once per (room, entity, day).
    # We replicate here so counts align with the live NM ledger.
    fired_days: set[tuple[str, str]] = set()
    verdicts: list[dict[str, Any]] = []

    restarts = sorted(restart_ts)

    # Build (entity, event_list) index for O(1) state lookup.
    def state_at(entity: str, ts: float, cache: dict[str, int]) -> str | None:
        hist = histories.get(entity)
        if not hist:
            return None
        i = cache.get(entity, 0)
        # Advance until the next row is beyond ts.
        while i + 1 < len(hist) and hist[i + 1].ts <= ts:
            i += 1
        cache[entity] = i
        row = hist[i]
        if row.ts > ts:
            return None
        return row.state

    idx_cache: dict[str, int] = {}
    tick_ts = since_ts
    restart_i = 0
    while tick_ts <= until_ts:
        # Handle restart: clear rings + motion state.
        while (
            restart_i < len(restarts) and restarts[restart_i] <= tick_ts
        ):
            for r in rings.values():
                r.clear()
            motion_deque.clear()
            last_motion_state.clear()
            idx_cache.clear()
            restart_i += 1

        mono = tick_ts  # replay uses wall-clock as mono equivalent.
        # Motion transitions.
        while motion_deque and (mono - motion_deque[0]) > window_s:
            motion_deque.popleft()
        for msensor in motion:
            st = state_at(msensor, tick_ts, idx_cache)
            if st is None:
                continue
            on_now = _is_on(st)
            prev = last_motion_state.get(msensor)
            if prev is not None and prev != on_now:
                motion_deque.append(mono)
            last_motion_state[msensor] = on_now
        fresh_cutoff = mono - PROD_D2_FRESH_MOTION_S
        fresh_transitions = sum(
            1 for ts in motion_deque if ts >= fresh_cutoff
        )
        corroborated = (
            len(motion_deque) >= PROD_D2_MIN_MOTION_TRANSITIONS
            or fresh_transitions >= 1
        )

        # Candidate rings.
        for c in candidates:
            st = state_at(c, tick_ts, idx_cache)
            if st is None:
                continue
            on_now = _is_on(st)
            ring = rings[c]
            ring.append((mono, on_now))
            while ring and (mono - ring[0][0]) > window_s:
                ring.popleft()
            if len(ring) < PROD_D2_MIN_TICKS:
                continue
            on_count = sum(1 for _, v in ring if v)
            on_ratio = on_count / len(ring)
            if on_ratio < PROD_D2_PCT:
                continue
            if corroborated:
                continue
            # Fire — dedup per (entity, day).
            day = datetime.utcfromtimestamp(mono).strftime("%Y-%m-%d")
            key = (c, day)
            if key in fired_days:
                continue
            fired_days.add(key)
            verdicts.append({
                "bucket": "D2",
                "kind": "dutycycle",
                "room_name": room_name,
                "entity_id": c,
                "fired_ts": mono,
                "on_ratio": round(on_ratio, 3),
                "ring_len": len(ring),
                "window_min": PROD_D2_WINDOW_MIN,
            })

        tick_ts += PROD_TICK_S

    return verdicts


# ---------------------------------------------------------------------------
# Skeleton emission for buckets impossible / infeasible by pure replay.
# ---------------------------------------------------------------------------


# Statuses that mark a fixture file as authoritative (operator-signed or
# adjudicated). Files carrying one of these are NEVER overwritten by
# regeneration — signed supplements are commit-pinned, not
# harness-generated. Replay only writes a bucket whose fixture file is
# ABSENT or is itself a skeleton (``PLACEHOLDER``) / draft
# (DRAFT-PENDING-SIGNOFF). (MANIFEST harness_regeneration_caveat —
# RESOLVED 2026-08-13.)
PRESERVED_STATUSES: frozenset[str] = frozenset({
    "SIGNED-OFF",
    "DEFERRED-UNTIL-SITE-SHIPS",
    "OBSOLETE-BUCKET-DROPPED",
})


def _load_fixture_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _should_preserve_fixture(path: Path) -> bool:
    """True iff ``path`` exists and is a signed/adjudicated fixture."""
    if not path.exists():
        return False
    data = _load_fixture_json(path)
    if data is None:
        return False
    return data.get("status") in PRESERVED_STATUSES


def skeleton_fixture(
    bucket: str, reason: str, required_fields: list[str],
) -> dict[str, Any]:
    return {
        "bucket": bucket,
        "PLACEHOLDER": True,
        "shortfall_reason": reason,
        "required_fields": required_fields,
        "instructions": (
            "This bucket cannot be filled by pure recorder replay. "
            "The operator or orchestrator MUST hand-build one row per "
            "the required_fields list, per the operator sign-off "
            "clause of amended Criterion 4 "
            "(PLANNING_signal_trust_ledger_abstraction.md, "
            "OPERATOR APPROVED 2026-08-13). Do NOT fabricate values — "
            "each row must correspond to a real, observed event or a "
            "synthetic trace the operator has reviewed and signed."
        ),
        "entries": [],
    }


SKELETON_SPECS: dict[str, dict[str, Any]] = {
    "P24": {
        "reason": (
            "M2 max-active failsafe is closed-loop: firing mutates its "
            "own future inputs (_last_motion_time=None, "
            "STATE_OCCUPIED=False), so pure replay is not a fixture "
            "harness but a second implementation. See AUDIT §M2 row. "
            "Live NM ledger shows ~1 firing / 14 days — supplement "
            "with hand-built rows to reach minimum."
        ),
        "fields": [
            "room_name", "fired_ts", "occupancy_source",
            "became_occupied_time", "last_motion_time", "max_active_s",
        ],
    },
    "P18": {
        "reason": (
            "M3 zone stale-occupancy reads zone-object state and calls "
            "check_zone_occupancy_confidence — a live cross-coordinator "
            "call not recoverable from the recorder. AUDIT §M3 row "
            "recommends using persisted NM + decision_log rows as the "
            "fixture surface instead of replay."
        ),
        "fields": [
            "zone_name", "fired_ts", "continuous_occupied_since",
            "any_room_occupied", "confidence_verdict",
        ],
    },
    "D1": {
        "reason": (
            "M4 camera stuck-count did not fire in the 7.46-day audit "
            "window; interior max unchanged person_count>0 hold was "
            "0.31h vs 3.0h threshold (~10x margin). Additionally, "
            "the discount decision reads URA-derived per-tick state "
            "(_ble_home_by_area, _room_tier_corroboration_by_area) "
            "that is not in the recorder. Supplement per AUDIT §D1."
        ),
        "fields": [
            "camera_entity_id", "fired_ts", "person_count",
            "hold_hours", "corroboration_snapshot",
        ],
    },
    "D3": {
        "reason": D3_STATUS_NOTE,
        "fields": [
            "tracker_entity_id", "fired_ts", "last_updated_age_days",
        ],
    },
    "CHATTER": {
        "reason": (
            "Criterion 4b (transition-rate / chatter) — the new verdict "
            "kind is not yet shipped in production. Fixture is a "
            "placeholder for the migration cycle that lands the "
            "chatter classification; do NOT populate until the site "
            "exists in HEAD."
        ),
        "fields": [
            "room_name", "entity_id", "fired_ts", "transitions_in_window",
            "window_min",
        ],
    },
}


# ---------------------------------------------------------------------------
# CLI + orchestration
# ---------------------------------------------------------------------------


def get_git_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        return out
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _sorted_json_dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def build_fixtures(
    db: RecorderDB,
    room_map: dict[str, dict[str, list[str]]],
    out_dir: Path,
    window_days: float,
    generation_date: str,
    repo_root: Path,
    window_end_ts: float | None = None,
) -> dict[str, Any]:
    # Determinism: default the window end to midnight UTC of the
    # generation date, so re-running on the same date pins the window
    # bounds byte-for-byte.
    if window_end_ts is None:
        end_dt = datetime.strptime(generation_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc,
        )
        window_end_ts = end_dt.timestamp()
    now_ts = window_end_ts
    since_ts = now_ts - (window_days * 86400.0)

    restart_ts = db.restart_boundaries(since_ts)
    _LOGGER.info("Detected %d restart boundaries in window", len(restart_ts))

    p22_all: list[dict[str, Any]] = []
    d2_all: list[dict[str, Any]] = []

    # Cache histories per sensor to avoid double-fetching for D2 (which
    # needs motion + candidates) and P22 (which needs all).
    hist_cache: dict[str, list[RecorderRow]] = {}

    def get_hist(entity: str) -> list[RecorderRow]:
        if entity in hist_cache:
            return hist_cache[entity]
        mid = db.metadata_id_for(entity)
        if mid is None:
            hist_cache[entity] = []
            return []
        rows = db.state_history(mid, since_ts)
        for r in rows:
            r.entity_id = entity
        hist_cache[entity] = rows
        return rows

    for room_name, sensors in sorted(room_map.items()):
        # P22: run over every configured sensor (motion + mmwave + occupancy).
        all_sensors = list(dict.fromkeys(
            sensors.get("motion", [])
            + sensors.get("mmwave", [])
            + sensors.get("occupancy", [])
        ))
        room_histories: dict[str, list[RecorderRow]] = {}
        for s in all_sensors:
            if not s:
                continue
            rows = get_hist(s)
            room_histories[s] = rows
            episodes = replay_p22(rows, s, room_name, restart_ts)
            p22_all.extend(episodes)
        # D2: needs motion + candidates in same histories dict.
        d2_verdicts = replay_d2(
            room_name, sensors, room_histories, restart_ts,
            since_ts, now_ts,
        )
        d2_all.extend(d2_verdicts)

    # Sort for deterministic output.
    p22_all.sort(key=lambda r: (r["room_name"], r["entity_id"], r["fired_ts"]))
    d2_all.sort(key=lambda r: (r["room_name"], r["entity_id"], r["fired_ts"]))

    p22_fixture = {
        "bucket": "P22",
        "detector": "M1 continuous-on",
        "prod_source": "coordinator.py:2117-2131",
        "threshold_hours": PROD_STUCK_SENSOR_HOURS,
        "restart_aware": True,
        "restart_boundary_count": len(restart_ts),
        "entries": p22_all,
    }
    d2_fixture = {
        "bucket": "D2",
        "detector": "M5 duty-cycle",
        "prod_source": "coordinator.py:1504-1714",
        "window_min": PROD_D2_WINDOW_MIN,
        "pct_threshold": PROD_D2_PCT,
        "min_ticks": PROD_D2_MIN_TICKS,
        "fresh_motion_s": PROD_D2_FRESH_MOTION_S,
        "min_motion_transitions": PROD_D2_MIN_MOTION_TRANSITIONS,
        "tick_s": PROD_TICK_S,
        "capability_assumption": (
            "empty CONF_SENSOR_CAPABILITIES; regenerate after "
            "SENSOR-CAPABILITY-1 lands"
        ),
        "boot_settle_gate_modelled": False,
        "entries": d2_all,
    }

    _write(out_dir / "P22.json", _sorted_json_dump(p22_fixture))
    _write(out_dir / "D2.json", _sorted_json_dump(d2_fixture))

    preserved_files: list[str] = []
    preserved_data: dict[str, dict[str, Any]] = {}
    for bucket, spec in SKELETON_SPECS.items():
        path = out_dir / f"{bucket}.json"
        if _should_preserve_fixture(path):
            data = _load_fixture_json(path) or {}
            preserved_files.append(path.name)
            preserved_data[bucket] = data
            _LOGGER.info(
                "PRESERVED signed fixture %s (status=%s) — not overwritten",
                path.name, data.get("status"),
            )
            continue
        _write(
            path,
            _sorted_json_dump(skeleton_fixture(
                bucket, spec["reason"], spec["fields"],
            )),
        )

    counts = {
        "P22": len(p22_all),
        "D2": len(d2_all),
    }
    for bucket in SKELETON_SPECS:
        if bucket in preserved_data:
            counts[bucket] = int(preserved_data[bucket].get("count") or 0)
        else:
            counts[bucket] = 0

    status = {}
    for bucket, minimum in BUCKET_MINIMUMS.items():
        got = counts.get(bucket, 0)
        if bucket in preserved_data:
            status[bucket] = str(
                preserved_data[bucket].get("status"),
            )
        elif bucket in SKELETON_SPECS:
            status[bucket] = "SKELETON_AWAITS_HANDBUILD"
        elif got >= minimum:
            status[bucket] = "FILLED"
        else:
            status[bucket] = "SHORT"

    manifest = {
        "generated_at": generation_date,
        "window_days": window_days,
        "window_since_ts": since_ts,
        "window_until_ts": now_ts,
        "production_source_git_sha": get_git_sha(repo_root),
        "harness_version": "1.0.0",
        "bucket_minimums": BUCKET_MINIMUMS,
        "bucket_counts": counts,
        "bucket_status": status,
        "restart_boundary_count": len(restart_ts),
        "audit_reference": "docs/planning/AUDIT_ledger_golden_fixture_yield.md",
        "planning_reference": (
            "docs/planning/PLANNING_signal_trust_ledger_abstraction.md"
            " §Criterion 4 (AMENDED 2026-08-09, OPERATOR APPROVED "
            "2026-08-13)"
        ),
        "regeneration_rule": (
            "Fixtures are invalid once any migrated site's production "
            "behavior changes. Regenerate + cite the invalidating cycle "
            "in the commit per §4a."
        ),
        "preserved_files": sorted(preserved_files),
    }
    # Merge-preserve hand-written manifest blocks (signoff_*, supplement
    # notes, ...): any key present in the existing MANIFEST.json that the
    # harness does not itself compute is carried over verbatim, so
    # regeneration never deletes an operator sign-off record.
    existing = _load_fixture_json(out_dir / "MANIFEST.json")
    if existing:
        for key, value in existing.items():
            if key not in manifest:
                manifest[key] = value
    _write(out_dir / "MANIFEST.json", _sorted_json_dump(manifest))
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", help="Local recorder sqlite path (read-only)")
    p.add_argument("--ssh-host", help="SSH host that owns the recorder")
    p.add_argument("--remote-db", help="Remote recorder path on --ssh-host")
    p.add_argument("--room-map", help="Local core.config_entries JSON path")
    p.add_argument(
        "--room-map-ssh",
        help="Remote path to core.config_entries on --ssh-host (fetched via scp)",
    )
    p.add_argument("--out", required=True, help="Output fixture directory")
    p.add_argument("--window-days", type=float, default=7.0)
    p.add_argument(
        "--generation-date", default=None,
        help="Pin generated_at for determinism; defaults to today UTC.",
    )
    p.add_argument(
        "--self-check", action="store_true",
        help="Re-run against the same window and diff for determinism.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.db and not (args.ssh_host and args.remote_db):
        p.error("must supply --db OR (--ssh-host + --remote-db)")

    # Room map.
    room_map_path = args.room_map
    tmp_dir: tempfile.TemporaryDirectory | None = None
    if not room_map_path and args.room_map_ssh:
        tmp_dir = tempfile.TemporaryDirectory()
        local = Path(tmp_dir.name) / "core.config_entries"
        # HAOS SSH addon does not expose the SFTP subsystem; use
        # `ssh cat` instead of scp.
        with open(local, "wb") as fh:
            subprocess.check_call(
                ["ssh", args.ssh_host, f"cat {args.room_map_ssh}"],
                stdout=fh,
            )
        room_map_path = str(local)
    if not room_map_path:
        p.error("must supply --room-map or --room-map-ssh")

    room_map = load_room_map(room_map_path)
    _LOGGER.info("Loaded %d URA rooms", len(room_map))

    db = RecorderDB(
        local_path=args.db,
        ssh_host=args.ssh_host,
        remote_path=args.remote_db,
    )

    gen_date = args.generation_date or datetime.now(
        timezone.utc,
    ).strftime("%Y-%m-%d")
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = Path(args.out)

    manifest = build_fixtures(
        db, room_map, out_dir,
        window_days=args.window_days,
        generation_date=gen_date,
        repo_root=repo_root,
    )

    print(json.dumps({
        "bucket_counts": manifest["bucket_counts"],
        "bucket_status": manifest["bucket_status"],
        "restart_boundary_count": manifest["restart_boundary_count"],
        "git_sha": manifest["production_source_git_sha"],
    }, indent=2))

    if args.self_check:
        # Second pass into sibling dir, then diff (ignoring generated_at).
        with tempfile.TemporaryDirectory() as td:
            build_fixtures(
                db, room_map, Path(td),
                window_days=args.window_days,
                generation_date=gen_date,
                repo_root=repo_root,
            )
            preserved = set(manifest.get("preserved_files") or [])
            mismatches = []
            for f in sorted(out_dir.iterdir()):
                if f.name in preserved:
                    # Signed fixtures are not harness outputs — the
                    # second run (into an empty dir) writes skeletons
                    # for these buckets by design. Not a determinism
                    # failure.
                    continue
                if f.name == "MANIFEST.json" and preserved:
                    # Manifest embeds preserved counts/status + merged
                    # sign-off blocks that an empty-dir run cannot see.
                    continue
                other = Path(td) / f.name
                if not other.exists():
                    mismatches.append(f.name + " missing in second run")
                    continue
                if f.read_bytes() != other.read_bytes():
                    mismatches.append(f.name + " differs between runs")
            if mismatches:
                print("SELF-CHECK FAIL:", mismatches, file=sys.stderr)
                return 2
            print("SELF-CHECK PASS: byte-identical across runs")

    if tmp_dir is not None:
        tmp_dir.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
