"""Tests for scripts/kanban_ship.py — BOARD-CURRENCY-1 rung 1 helper.

Exercised as pure logic (no shelling out). Six behaviors from the card are
covered, each with a NAMED test the mutation drill can point at:

  (a) refuses with no --cards        → covered indirectly via CLI validate rc
  (b) refuses on unknown card ID     → test_validate_rejects_unknown_id
  (c) --no-cards proceeds + logs     → deploy.sh integration (bash-level)
  (d) named cards get shipped_organic + shipped_version + last_reconciled bumped
                                       → test_mark_shipped_updates_status_version_and_meta
  (e) simulated write failure warns + exits 0
                                       → deploy.sh wrapper behavior; helper's
                                         atomic-write property is tested in
                                         test_atomic_write_aborts_on_corruption
  (f) YAML-corrupting write aborts write only
                                       → test_atomic_write_aborts_on_corruption
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

# The helper lives under scripts/, not on the default test path. Import it
# by prepending the repo's scripts/ dir — mirrors how scripts/probes/ tests
# reach their subjects.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import kanban_ship  # noqa: E402


LIVE_BOARD = REPO_ROOT / "docs" / "planning" / "kanban.data.yaml"


@pytest.fixture
def board_copy(tmp_path: Path) -> Path:
    """A private mutable copy of the live board — never touch the real file."""
    dst = tmp_path / "kanban.data.yaml"
    shutil.copy(LIVE_BOARD, dst)
    return dst


# ---------------------------------------------------------------------------
# Loader + validator
# ---------------------------------------------------------------------------


def test_load_board_returns_dict_with_cards(board_copy: Path) -> None:
    board = kanban_ship.load_board(board_copy)
    assert isinstance(board, dict)
    assert "cards" in board
    assert len(kanban_ship.all_card_ids(board)) > 0


def test_validate_rejects_unknown_id(board_copy: Path) -> None:
    """(b) unknown IDs are surfaced BEFORE any mutation. deploy.sh keys off
    the non-empty return list to refuse pre-push."""
    board = kanban_ship.load_board(board_copy)
    missing = kanban_ship.validate_ids(board, ["BOARD-CURRENCY-1", "DEFINITELY-NOT-A-CARD"])
    assert missing == ["DEFINITELY-NOT-A-CARD"]


def test_validate_accepts_known_id(board_copy: Path) -> None:
    board = kanban_ship.load_board(board_copy)
    assert kanban_ship.validate_ids(board, ["BOARD-CURRENCY-1"]) == []


def test_candidate_cards_are_in_progress_or_review(board_copy: Path) -> None:
    board = kanban_ship.load_board(board_copy)
    for c in kanban_ship.candidate_cards(board):
        assert c["status"] in kanban_ship.CANDIDATE_STATUSES


# ---------------------------------------------------------------------------
# Mutation
# ---------------------------------------------------------------------------


def test_mark_shipped_updates_status_version_and_meta(board_copy: Path) -> None:
    """(d) the load-bearing write. Named cards get status + shipped_version;
    meta.last_reconciled bumped to today (injected)."""
    board = kanban_ship.load_board(board_copy)
    # Pick any two known IDs deterministically.
    ids = kanban_ship.all_card_ids(board)[:2]
    mutated, unknown = kanban_ship.mark_shipped(board, ids, "5.99.0", "2026-08-09")
    assert unknown == []
    hit = {c["id"]: c for c in mutated["cards"] if c["id"] in ids}
    for cid in ids:
        assert hit[cid]["status"] == "shipped_organic", cid
        assert hit[cid]["shipped_version"] == "v5.99.0", cid
    assert mutated["meta"]["last_reconciled"] == "2026-08-09"


def test_mark_shipped_preserves_untouched_cards(board_copy: Path) -> None:
    board = kanban_ship.load_board(board_copy)
    all_ids = kanban_ship.all_card_ids(board)
    target = all_ids[0]
    untouched_ids = all_ids[1:]
    pre = {c["id"]: dict(c) for c in board["cards"] if c["id"] in untouched_ids}
    mutated, _ = kanban_ship.mark_shipped(board, [target], "9.9.9", "2026-08-09")
    post = {c["id"]: c for c in mutated["cards"] if c["id"] in untouched_ids}
    for cid in untouched_ids:
        assert post[cid].get("status") == pre[cid].get("status")
        assert post[cid].get("shipped_version") == pre[cid].get("shipped_version")


def test_mark_shipped_version_prefix_is_normalised(board_copy: Path) -> None:
    board = kanban_ship.load_board(board_copy)
    target = kanban_ship.all_card_ids(board)[0]
    mutated, _ = kanban_ship.mark_shipped(board, [target], "v1.2.3", "2026-08-09")
    hit = next(c for c in mutated["cards"] if c["id"] == target)
    assert hit["shipped_version"] == "v1.2.3"  # not "vv1.2.3"


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def test_atomic_write_roundtrip(board_copy: Path) -> None:
    board = kanban_ship.load_board(board_copy)
    target = kanban_ship.all_card_ids(board)[0]
    mutated, _ = kanban_ship.mark_shipped(board, [target], "5.99.0", "2026-08-09")
    kanban_ship.atomic_write_yaml(board_copy, mutated)

    reloaded = yaml.safe_load(board_copy.read_text())
    assert reloaded["meta"]["last_reconciled"] == "2026-08-09"
    hit = next(c for c in reloaded["cards"] if c["id"] == target)
    assert hit["status"] == "shipped_organic"
    assert hit["shipped_version"] == "v5.99.0"


def test_atomic_write_aborts_on_corruption(board_copy: Path, monkeypatch) -> None:
    """(f) if the temp file cannot round-trip as a valid kanban board, the
    write aborts and the ORIGINAL file is untouched. deploy.sh treats this as
    a warning, not a deploy abort."""
    original_bytes = board_copy.read_bytes()

    # Force safe_dump to emit garbage that safe_load will not accept as a board.
    def broken_dump(data, stream, **kwargs):
        stream.write("this: is: not: a: valid: kanban: board:\n:::\n")

    monkeypatch.setattr(kanban_ship.yaml, "safe_dump", broken_dump)
    with pytest.raises(Exception):
        kanban_ship.atomic_write_yaml(board_copy, {"cards": []})

    # Original file survived.
    assert board_copy.read_bytes() == original_bytes
    # No leftover .tmp files.
    leftovers = list(board_copy.parent.glob(f"{board_copy.name}.*.tmp"))
    assert leftovers == [], f"stale temp files: {leftovers}"


# ---------------------------------------------------------------------------
# CLI wrappers (thin — just verify exit codes deploy.sh depends on)
# ---------------------------------------------------------------------------


def test_cli_validate_returns_1_on_unknown(board_copy: Path) -> None:
    rc = kanban_ship.main(["validate", "NOPE-1,ALSO-NOPE", "--file", str(board_copy)])
    assert rc == 1


def test_cli_validate_returns_0_on_known(board_copy: Path) -> None:
    known = kanban_ship.all_card_ids(kanban_ship.load_board(board_copy))[0]
    rc = kanban_ship.main(["validate", known, "--file", str(board_copy)])
    assert rc == 0


def test_cli_list_candidates_runs(board_copy: Path, capsys) -> None:
    rc = kanban_ship.main(["list-candidates", "--file", str(board_copy)])
    assert rc == 0
    # Doesn't crash on the real board — enough for a smoke check.
    capsys.readouterr()
