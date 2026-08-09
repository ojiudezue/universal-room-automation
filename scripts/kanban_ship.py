#!/usr/bin/env python3
"""kanban_ship.py — release-coupled board reconciliation for BOARD-CURRENCY-1.

Two responsibilities:

1. **Validation** (pre-push): given a set of card IDs, verify every ID exists
   in ``docs/planning/kanban.data.yaml``. Missing IDs are printed and a
   non-zero exit code is returned so ``deploy.sh`` can REFUSE before it has
   pushed anything. Also exposes a candidates listing (in_progress + review)
   for the "you forgot --cards" error message.

2. **Mutation** (post-push): for each supplied card ID, set
   ``status: shipped_organic`` and ``shipped_version: v<version>``, and bump
   ``meta.last_reconciled`` to today. Writes atomically via a temp file that
   is re-parsed before rename, so a corrupting write aborts the WRITE (not
   the deploy). Per the BOARD-CURRENCY-1 safety constraint, callers that
   invoke this AFTER the push must never exit non-zero on failure — this
   module returns rc>0 but deploy.sh wraps the call.

Usage:
    kanban_ship.py list-candidates [--file PATH]
    kanban_ship.py validate ID[,ID...] [--file PATH]
    kanban_ship.py mark-shipped ID[,ID...] --version X.Y.Z [--file PATH] [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import tempfile
from pathlib import Path
from typing import Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_YAML = REPO_ROOT / "docs" / "planning" / "kanban.data.yaml"

# Statuses that make a card a legitimate "you shipped this" candidate.
CANDIDATE_STATUSES = ("in_progress", "review")


# ---------------------------------------------------------------------------
# Pure functions — the meat of the helper, exercised by unit tests.
# ---------------------------------------------------------------------------


def load_board(path: Path) -> dict:
    """Load the kanban YAML. Raises on parse error — callers decide."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "cards" not in data:
        raise ValueError(f"{path}: not a valid kanban board (missing 'cards')")
    return data


def all_card_ids(board: dict) -> list[str]:
    return [str(c.get("id")) for c in board.get("cards", []) if c.get("id")]


def candidate_cards(board: dict) -> list[dict]:
    """Cards eligible to be marked shipped: in_progress or review."""
    return [
        c for c in board.get("cards", [])
        if c.get("status") in CANDIDATE_STATUSES
    ]


def validate_ids(board: dict, ids: Iterable[str]) -> list[str]:
    """Return the subset of *ids* that are NOT present on the board."""
    known = set(all_card_ids(board))
    return [i for i in ids if i not in known]


def mark_shipped(
    board: dict,
    ids: Iterable[str],
    version: str,
    today: str,
) -> tuple[dict, list[str]]:
    """Return a mutated copy of *board* with the named cards marked shipped.

    Returns (mutated_board, unknown_ids). If any id is unknown, the mutation
    is applied to the recognised ones anyway and the unknowns are returned so
    the caller can decide (deploy.sh calls validate first, so at this stage
    unknowns should be impossible).
    """
    unknown: list[str] = []
    id_set = set(ids)
    ver = version if version.startswith("v") else f"v{version}"
    known = set(all_card_ids(board))
    for i in id_set:
        if i not in known:
            unknown.append(i)

    for card in board.get("cards", []):
        if card.get("id") in id_set:
            card["status"] = "shipped_organic"
            card["shipped_version"] = ver

    meta = board.setdefault("meta", {})
    meta["last_reconciled"] = today

    return board, unknown


def atomic_write_yaml(path: Path, board: dict) -> None:
    """Write *board* to *path* atomically, re-parsing the temp file first.

    If the temp file cannot be parsed back (corruption), the temp file is
    removed and the original *path* is left untouched. This is the "abort
    the WRITE, not the deploy" safety property from the card.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_path)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(board, fh, sort_keys=False, allow_unicode=True)
        # Verify the temp file is still parseable BEFORE clobbering the real one.
        with open(tmp, "r", encoding="utf-8") as fh:
            verify = yaml.safe_load(fh)
        if not isinstance(verify, dict) or "cards" not in verify:
            raise ValueError("post-write verify: YAML no longer a valid kanban board")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def _split_ids(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def cmd_list_candidates(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    cands = candidate_cards(board)
    if not cands:
        print("(no cards currently in_progress or review)")
        return 0
    for c in cands:
        print(f"  {c.get('id')}  [{c.get('status')}]  {c.get('title', '')}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    ids = _split_ids(args.ids)
    if not ids:
        print("ERROR: no card IDs supplied", file=sys.stderr)
        return 2
    missing = validate_ids(board, ids)
    if missing:
        print(
            "ERROR: unknown card ID(s): " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_mark_shipped(args: argparse.Namespace) -> int:
    path = Path(args.file)
    board = load_board(path)
    ids = _split_ids(args.ids)
    if not ids:
        print("ERROR: no card IDs supplied", file=sys.stderr)
        return 2
    today = args.today or _dt.date.today().isoformat()
    board, unknown = mark_shipped(board, ids, args.version, today)
    if unknown:
        # deploy.sh validates BEFORE push, so this should not happen post-push;
        # if it does, we still write the ones we recognised, but flag loudly.
        print(
            "WARN: unknown card ID(s) at write time: " + ", ".join(unknown),
            file=sys.stderr,
        )
    atomic_write_yaml(path, board)
    print(
        f"kanban_ship: marked {len(ids) - len(unknown)} card(s) shipped_organic "
        f"at v{args.version.lstrip('v')}; meta.last_reconciled={today}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-candidates", help="print in_progress + review cards")
    p_list.add_argument("--file", default=str(DEFAULT_YAML))
    p_list.set_defaults(func=cmd_list_candidates)

    p_val = sub.add_parser("validate", help="verify card IDs exist on the board")
    p_val.add_argument("ids")
    p_val.add_argument("--file", default=str(DEFAULT_YAML))
    p_val.set_defaults(func=cmd_validate)

    p_mark = sub.add_parser("mark-shipped", help="mark cards shipped_organic + bump last_reconciled")
    p_mark.add_argument("ids")
    p_mark.add_argument("--version", required=True)
    p_mark.add_argument("--file", default=str(DEFAULT_YAML))
    p_mark.add_argument("--today", default=None, help="override today (YYYY-MM-DD) for tests")
    p_mark.set_defaults(func=cmd_mark_shipped)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
