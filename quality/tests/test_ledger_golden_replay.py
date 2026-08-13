"""Tests for quality/tools/ledger_golden_replay.py.

Covers:
1. Harness importability.
2. Determinism on a small synthetic recorder DB (schema extracted from
   a real HA recorder — see the module docstring; the exact CREATE TABLE
   text was pulled from ``ssh ha 'sqlite3 file:...?mode=ro .schema states'``
   on 2026-08-12, NOT hand-copied from memory).
3. P22 end-to-end on synthetic data: a sensor pinned "on" for >4h fires
   one continuous episode; a sensor that flips before 4h does not.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "quality" / "tools"))

import ledger_golden_replay as lgr  # noqa: E402


# ---------------------------------------------------------------------------
# Real-schema recorder fixture. DDL extracted 2026-08-12 from
# ssh ha 'sqlite3 file:/config/home-assistant_v2.db?mode=ro .schema'.
# ---------------------------------------------------------------------------

_RECORDER_DDL = """
CREATE TABLE states_meta (
    metadata_id INTEGER NOT NULL,
    entity_id VARCHAR(255),
    PRIMARY KEY (metadata_id)
);
CREATE UNIQUE INDEX ix_states_meta_entity_id ON states_meta (entity_id);
CREATE TABLE states (
    state_id INTEGER NOT NULL,
    entity_id CHAR(0),
    state VARCHAR(255),
    attributes CHAR(0),
    event_id SMALLINT,
    last_changed CHAR(0),
    last_changed_ts FLOAT,
    last_reported_ts FLOAT,
    last_updated CHAR(0),
    last_updated_ts FLOAT,
    old_state_id INTEGER,
    attributes_id INTEGER,
    context_id CHAR(0),
    context_user_id CHAR(0),
    context_parent_id CHAR(0),
    origin_idx SMALLINT,
    context_id_bin BLOB,
    context_user_id_bin BLOB,
    context_parent_id_bin BLOB,
    metadata_id INTEGER,
    PRIMARY KEY (state_id),
    FOREIGN KEY(metadata_id) REFERENCES states_meta (metadata_id)
);
CREATE INDEX ix_states_metadata_id_last_updated_ts
    ON states (metadata_id, last_updated_ts);
"""


def _build_synthetic_db(tmp_path: Path, base_ts: float) -> Path:
    """One P22-firing sensor + one non-firing sensor.

    ``binary_sensor.room_a_presence`` — on for 5h continuously, then off.
    ``binary_sensor.room_a_motion``   — flips every 30 min (never > 4h on).
    """
    db_path = tmp_path / "recorder.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_RECORDER_DDL)
    conn.execute(
        "INSERT INTO states_meta(metadata_id, entity_id) VALUES (1, ?)",
        ("binary_sensor.room_a_presence",),
    )
    conn.execute(
        "INSERT INTO states_meta(metadata_id, entity_id) VALUES (2, ?)",
        ("binary_sensor.room_a_motion",),
    )
    # Presence: on at base, off at base+5h+1min.
    events = [
        (1, "off", base_ts - 60.0),
        (1, "on", base_ts),
        (1, "off", base_ts + 5 * 3600 + 60),
    ]
    # Motion: flips every 30 min for 6h.
    for i in range(12):
        st = "on" if i % 2 == 0 else "off"
        events.append((2, st, base_ts + i * 1800))
    events.sort(key=lambda e: e[2])
    sid = 1
    for mid, st, ts in events:
        conn.execute(
            "INSERT INTO states(state_id, state, last_updated_ts, "
            "old_state_id, metadata_id) VALUES (?, ?, ?, ?, ?)",
            (sid, st, ts, None if sid == 1 else sid - 1, mid),
        )
        sid += 1
    conn.commit()
    conn.close()
    return db_path


def _write_room_map(tmp_path: Path) -> Path:
    p = tmp_path / "core.config_entries"
    p.write_text(json.dumps({
        "data": {
            "entries": [{
                "domain": "universal_room_automation",
                "title": "Room A",
                "data": {
                    "room_name": "Room A",
                    "motion_sensors": ["binary_sensor.room_a_motion"],
                    "presence_sensors": ["binary_sensor.room_a_presence"],
                    "occupancy_sensors": [],
                },
                "options": {},
            }],
        },
    }))
    return p


def test_harness_importable():
    assert callable(lgr.main)
    assert callable(lgr.replay_p22)
    assert callable(lgr.replay_d2)
    # Prod constants match cited HEAD values.
    assert lgr.PROD_STUCK_SENSOR_HOURS == 4.0
    assert lgr.PROD_D2_WINDOW_MIN == 60
    assert lgr.PROD_D2_PCT == 0.85


def test_p22_end_to_end_on_synthetic(tmp_path):
    # base_ts fixed so ordering + window bounds are stable.
    base_ts = 1_700_000_000.0
    db_path = _build_synthetic_db(tmp_path, base_ts)
    room_map_path = _write_room_map(tmp_path)
    out_dir = tmp_path / "out"

    rc = lgr.main([
        "--db", str(db_path),
        "--room-map", str(room_map_path),
        "--out", str(out_dir),
        # 10 years of window so our base_ts is included regardless of `now`.
        "--window-days", "3650",
        "--generation-date", "2026-08-12",
    ])
    assert rc == 0

    p22 = json.loads((out_dir / "P22.json").read_text())
    entries = p22["entries"]
    # Exactly one continuous episode on the presence sensor.
    assert len(entries) == 1, entries
    e = entries[0]
    assert e["entity_id"] == "binary_sensor.room_a_presence"
    assert e["kind"] == "continuous"
    assert e["on_hours_at_fire"] >= 4.0

    # Manifest bucket_status wired correctly.
    mfst = json.loads((out_dir / "MANIFEST.json").read_text())
    assert mfst["bucket_status"]["P22"] == "SHORT"  # 1 < min 5
    assert mfst["bucket_status"]["P24"] == "SKELETON_AWAITS_HANDBUILD"
    assert mfst["bucket_status"]["D3"] == "SKELETON_AWAITS_HANDBUILD"

    # Skeleton files carry PLACEHOLDER markers.
    for bucket in ("P24", "P18", "D1", "D3", "CHATTER"):
        sk = json.loads((out_dir / f"{bucket}.json").read_text())
        assert sk["PLACEHOLDER"] is True
        assert sk["entries"] == []


def test_determinism_self_check(tmp_path):
    base_ts = 1_700_000_000.0
    db_path = _build_synthetic_db(tmp_path, base_ts)
    room_map_path = _write_room_map(tmp_path)
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"

    args = [
        "--db", str(db_path),
        "--room-map", str(room_map_path),
        "--window-days", "3650",
        "--generation-date", "2026-08-12",
    ]
    assert lgr.main(args + ["--out", str(out_a)]) == 0
    assert lgr.main(args + ["--out", str(out_b)]) == 0

    files_a = sorted(p.name for p in out_a.iterdir())
    files_b = sorted(p.name for p in out_b.iterdir())
    assert files_a == files_b

    for name in files_a:
        a_bytes = (out_a / name).read_bytes()
        b_bytes = (out_b / name).read_bytes()
        assert a_bytes == b_bytes, f"{name} differs between runs"
