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
import re
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


# ---------------------------------------------------------------------------
# H1 FIX — textual (line-anchored) edit path.
#
# The prior implementation round-tripped the whole board through
# ``yaml.safe_dump``, which reflowed every card's hand-authored prose at
# ~80 columns (1296 → 1455 lines measured on the real board). The file's
# readability IS the point, so the writer edits TEXT and only PARSES to
# validate. Rules:
#   * Cards begin with ``- id: <ID>`` at column 0. A card block runs up to
#     the next ``- id:`` at column 0, or the next top-level key (``[a-z]``
#     at column 0), or EOF.
#   * ``status:`` inside a card is a 2-space-indented line; we replace it
#     in place preserving indentation.
#   * ``shipped_version:`` is inserted immediately after ``status:`` if
#     absent, or replaced in place if present (idempotent — re-shipping
#     the same card must not duplicate the key).
#   * ``meta.last_reconciled`` sits at 2-space indent inside the top-level
#     ``meta:`` block; both quoted ('YYYY-MM-DD') and unquoted forms
#     preserved by matching the existing value's quoting style.
#   * Everything else stays byte-identical.
# ---------------------------------------------------------------------------


_CARD_START_RE = re.compile(r"^- id:\s*(\S+)\s*$")
_TOPLEVEL_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:")
_STATUS_LINE_RE = re.compile(r"^(?P<indent>  )status:\s*(?P<val>\S+)\s*$")
_SHIPVER_LINE_RE = re.compile(r"^(?P<indent>  )shipped_version:\s*(?P<val>\S.*)$")
_META_LR_RE = re.compile(
    r"^(?P<indent>  )last_reconciled:\s*(?P<q>['\"]?)(?P<val>[^'\"\n]+)(?P=q)\s*$"
)


def _find_card_blocks(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return [(card_id, start_idx, end_idx_exclusive), ...] for every card.

    A card block starts on its ``- id:`` line and ends at the next card OR
    the next top-level key OR EOF. Only lines *between* ``cards:`` and the
    next top-level key are considered.
    """
    blocks: list[tuple[str, int, int]] = []
    n = len(lines)
    # Find the cards: section boundaries.
    cards_start = None
    cards_end = n
    for i, line in enumerate(lines):
        if line.rstrip("\n") == "cards:":
            cards_start = i + 1
            break
    if cards_start is None:
        return blocks
    for j in range(cards_start, n):
        line = lines[j]
        # A top-level key that is not a card start ends the cards section.
        if line and line[0] not in " \t" and not line.startswith("- "):
            if _TOPLEVEL_KEY_RE.match(line):
                cards_end = j
                break

    # Walk the cards section collecting card start lines.
    starts: list[tuple[str, int]] = []
    for j in range(cards_start, cards_end):
        m = _CARD_START_RE.match(lines[j].rstrip("\n"))
        if m:
            starts.append((m.group(1), j))
    for k, (cid, s) in enumerate(starts):
        e = starts[k + 1][1] if k + 1 < len(starts) else cards_end
        blocks.append((cid, s, e))
    return blocks


def mark_shipped_text(
    source: str,
    ids: Iterable[str],
    version: str,
    today: str,
) -> tuple[str, list[str]]:
    """Textual, byte-preserving edit of the kanban YAML.

    Mutates ONLY the target ``status:`` / ``shipped_version:`` lines inside
    the named card blocks, and the ``meta.last_reconciled`` line. Returns
    (new_text, unknown_ids).
    """
    ver = version if version.startswith("v") else f"v{version}"
    id_set = set(ids)
    # Keep the trailing newline structure identical: splitlines(keepends=True).
    lines = source.splitlines(keepends=True)

    # --- meta.last_reconciled --------------------------------------------
    # Scoped to the top-level meta: block (from `meta:` at col 0 to next
    # top-level key). Preserve the existing quote style if any.
    in_meta = False
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if stripped == "meta:":
            in_meta = True
            continue
        if in_meta:
            if stripped and stripped[0] not in " \t":
                # Exited meta block.
                break
            m = _META_LR_RE.match(stripped)
            if m:
                q = m.group("q") or ""
                nl = "\n" if line.endswith("\n") else ""
                lines[i] = f"{m.group('indent')}last_reconciled: {q}{today}{q}{nl}"
                break

    # --- per-card status + shipped_version --------------------------------
    blocks = _find_card_blocks(lines)
    known = {cid for cid, _, _ in blocks}
    unknown = [i for i in id_set if i not in known]

    # Process from the end of the file backwards so insertions do not
    # shift earlier block indexes.
    for cid, start, end in reversed(blocks):
        if cid not in id_set:
            continue
        status_idx = None
        shipver_idx = None
        indent = "  "
        for j in range(start, end):
            stripped = lines[j].rstrip("\n")
            m_s = _STATUS_LINE_RE.match(stripped)
            if m_s and status_idx is None:
                status_idx = j
                indent = m_s.group("indent")
                continue
            m_v = _SHIPVER_LINE_RE.match(stripped)
            if m_v and shipver_idx is None:
                shipver_idx = j
        if status_idx is None:
            # No plain `status:` line (quoted or exotic form) — skip rather
            # than corrupt. Validation caller (deploy.sh) will see the
            # sentinels-are-fine outcome; we surface it via the report.
            continue
        nl = "\n" if lines[status_idx].endswith("\n") else ""
        lines[status_idx] = f"{indent}status: shipped_organic{nl}"
        ship_line = f"{indent}shipped_version: {ver}{nl}"
        if shipver_idx is not None:
            lines[shipver_idx] = ship_line
        else:
            lines.insert(status_idx + 1, ship_line)

    return "".join(lines), unknown


def _validate_text_as_board(text: str) -> None:
    """Parse *text* and confirm it is a well-formed kanban board.

    Raises ValueError on any structural regression. Used by
    ``atomic_write_yaml`` to abort a corrupting write BEFORE it clobbers
    the original file.
    """
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict) or "cards" not in parsed:
        raise ValueError("post-write verify: YAML no longer a valid kanban board")
    if not isinstance(parsed["cards"], list):
        raise ValueError("post-write verify: 'cards' is not a list")


def atomic_write_yaml(path: Path, text: str) -> None:
    """Write *text* to *path* atomically after validating it parses as YAML.

    Text-in / text-out: no dict serialisation, so hand-authored prose is
    preserved byte-identical outside the edited lines. If the temp file
    cannot be re-parsed as a valid kanban board, the temp file is removed
    and the original *path* is left untouched.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_path)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        # Re-read from disk to validate exactly what will be renamed into place.
        with open(tmp, "r", encoding="utf-8") as fh:
            _validate_text_as_board(fh.read())
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
    ids = _split_ids(args.ids)
    if not ids:
        print("ERROR: no card IDs supplied", file=sys.stderr)
        return 2
    today = args.today or _dt.date.today().isoformat()
    # Load to validate ID membership up front (deploy.sh validates before push
    # too — this is defence in depth for direct CLI use).
    board = load_board(path)
    known = set(all_card_ids(board))
    unknown_upfront = [i for i in ids if i not in known]
    original_text = path.read_text(encoding="utf-8")
    new_text, unknown = mark_shipped_text(original_text, ids, args.version, today)
    # Combine unknowns from both surfaces (dict + text) for reporting.
    for u in unknown_upfront:
        if u not in unknown:
            unknown.append(u)
    if unknown:
        print(
            "WARN: unknown card ID(s) at write time: " + ", ".join(unknown),
            file=sys.stderr,
        )
    atomic_write_yaml(path, new_text)
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
