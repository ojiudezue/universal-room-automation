"""Signed-supplement preservation tests for the ledger golden replay harness.

Covers the 2026-08-13 sign-off requirement: regeneration must PRESERVE
fixture files whose status is signed/adjudicated (SIGNED-OFF /
DEFERRED-UNTIL-SITE-SHIPS / OBSOLETE-BUCKET-DROPPED), only writing
buckets whose file is absent or itself a skeleton/draft — and the
determinism guarantee must stay intact for harness-generated files.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO_ROOT / "quality" / "tools" / "ledger_golden_replay.py"

spec = importlib.util.spec_from_file_location(
    "ledger_golden_replay", HARNESS_PATH,
)
harness = importlib.util.module_from_spec(spec)
import sys as _sys  # noqa: E402

_sys.modules[spec.name] = harness  # dataclass resolution needs the module registered
spec.loader.exec_module(harness)

GEN_DATE = "2026-08-13"
# Window end = midnight UTC of GEN_DATE (harness pins this for determinism).
import datetime as _dt  # noqa: E402

WINDOW_END = _dt.datetime(2026, 8, 13, tzinfo=_dt.timezone.utc).timestamp()


@pytest.fixture()
def synthetic_db(tmp_path: Path) -> harness.RecorderDB:
    """Minimal recorder DB: one motion sensor with a 5h continuous-on
    episode inside the window (fires P22) and no mmwave/occupancy
    candidates (D2 returns empty)."""
    db_path = tmp_path / "recorder.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, "
        "entity_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE states (metadata_id INTEGER, state TEXT, "
        "last_updated_ts REAL, old_state_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO states_meta VALUES (1, 'binary_sensor.test_motion')"
    )
    on_ts = WINDOW_END - 2 * 86400
    off_ts = on_ts + 5 * 3600  # 5h > 4.0h threshold -> P22 episode
    conn.executemany(
        "INSERT INTO states VALUES (1, ?, ?, 10)",
        [("off", on_ts - 600), ("on", on_ts), ("off", off_ts)],
    )
    conn.commit()
    conn.close()
    return harness.RecorderDB(local_path=str(db_path))


ROOM_MAP = {"Test Room": {"motion": ["binary_sensor.test_motion"],
                          "mmwave": [], "occupancy": []}}


def _build(db, out_dir: Path):
    return harness.build_fixtures(
        db, ROOM_MAP, out_dir,
        window_days=7.0,
        generation_date=GEN_DATE,
        repo_root=REPO_ROOT,
    )


def test_signed_off_supplement_preserved_byte_identical(
    synthetic_db, tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    signed = {
        "bucket": "P24",
        "status": "SIGNED-OFF",
        "signoff": "operator, 2026-08-13, verbatim: "
                   '"Stuck sensor recommends accepted"',
        "count": 5,
        "entries": [{"room_name": "Ziri Bedroom (Bedroom 5)"}],
    }
    p24 = out / "P24.json"
    p24.write_text(json.dumps(signed, indent=2))
    before = p24.read_bytes()

    manifest = _build(synthetic_db, out)

    assert p24.read_bytes() == before, (
        "SIGNED-OFF fixture must never be overwritten by regeneration"
    )
    assert "P24.json" in manifest["preserved_files"]
    assert manifest["bucket_counts"]["P24"] == 5
    assert manifest["bucket_status"]["P24"] == "SIGNED-OFF"
    # Non-preserved skeleton buckets are still written.
    assert (out / "P18.json").exists()
    assert json.loads((out / "P18.json").read_text()).get("PLACEHOLDER")


def test_deferred_and_obsolete_statuses_preserved(
    synthetic_db, tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    for bucket, status in (
        ("CHATTER", "DEFERRED-UNTIL-SITE-SHIPS"),
        ("D3", "OBSOLETE-BUCKET-DROPPED"),
    ):
        (out / f"{bucket}.json").write_text(json.dumps(
            {"bucket": bucket, "status": status, "count": 0,
             "sentinel": "hand-written"},
        ))
    before = {
        b: (out / f"{b}.json").read_bytes() for b in ("CHATTER", "D3")
    }
    manifest = _build(synthetic_db, out)
    for b in ("CHATTER", "D3"):
        assert (out / f"{b}.json").read_bytes() == before[b]
        assert f"{b}.json" in manifest["preserved_files"]


def test_skeleton_and_draft_are_overwritten(
    synthetic_db, tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    # A draft (not signed) supplement IS regenerated to a skeleton.
    (out / "P24.json").write_text(json.dumps({
        "bucket": "P24", "status": "DRAFT-PENDING-SIGNOFF",
        "draft_marker": "should be replaced",
    }))
    # An old skeleton is likewise regenerated.
    (out / "D1.json").write_text(json.dumps({
        "bucket": "D1", "PLACEHOLDER": True, "old_marker": True,
    }))
    manifest = _build(synthetic_db, out)
    p24 = json.loads((out / "P24.json").read_text())
    d1 = json.loads((out / "D1.json").read_text())
    assert p24.get("PLACEHOLDER") is True
    assert "draft_marker" not in p24
    assert d1.get("PLACEHOLDER") is True
    assert "old_marker" not in d1
    assert manifest["preserved_files"] == []


def test_manifest_signoff_blocks_survive_regeneration(
    synthetic_db, tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "MANIFEST.json").write_text(json.dumps({
        "signoff_2026_08_13": {"operator_quote":
                               "Stuck sensor recommends accepted"},
        "bucket_counts": {"stale": True},  # harness-computed: replaced
    }))
    manifest = _build(synthetic_db, out)
    assert manifest["signoff_2026_08_13"]["operator_quote"] == (
        "Stuck sensor recommends accepted"
    )
    assert "stale" not in manifest["bucket_counts"]
    on_disk = json.loads((out / "MANIFEST.json").read_text())
    assert "signoff_2026_08_13" in on_disk


def test_determinism_without_preserved_files(
    synthetic_db, tmp_path: Path,
) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    _build(synthetic_db, out_a)
    _build(synthetic_db, out_b)
    # Second build of out_b happens after out_a; MANIFEST merge sees the
    # fresh manifest only. Compare every file byte-for-byte.
    names_a = sorted(p.name for p in out_a.iterdir())
    names_b = sorted(p.name for p in out_b.iterdir())
    assert names_a == names_b
    for name in names_a:
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes(), (
            f"{name} differs between identical runs"
        )
    # And the P22 replay actually produced the synthetic 5h episode.
    p22 = json.loads((out_a / "P22.json").read_text())
    assert len(p22["entries"]) == 1
    assert p22["entries"][0]["room_name"] == "Test Room"
