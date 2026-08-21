#!/usr/bin/env python3
"""vibememo_ship.py — release-coupled vibememo entry for BOARD-CURRENCY-1 rung 2.

Chains vibememo to the same ``deploy.sh --cards`` gate: every release emits a
milestone entry capturing the WHY of the ship. Kanban = WHAT/WHERE/NEXT;
vibememo = WHY. Both become OUTPUTS of shipping rather than tasks beside it.

Format is FORMAT.md v2.1 (see .vibememo/FORMAT.md). Fields inferred from
existing entries in ``.vibememo/users/<author>/entries/`` — this script does
NOT invent schema, it matches what the operator already ships. Uncertain
inferences are marked "INFERRED" in the report.

Usage:
    vibememo_ship.py --version X.Y.Z --summary "..." --notes "..." [--cards ID,ID] [--author X]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Forcing function (operator-coined 2026-08-19: "never write a thin vibememo …
# The deploy hook should force a proper one. It doesn't take that long").
# vibememo = WHY, not WHAT. A ship entry MUST carry a real reasoning trail, not
# an echo of the release notes. These thresholds are the objective floor the
# writer refuses to go below — thin entries are rejected at the source, so the
# deploy cannot mint one no matter which caller invokes it.
MIN_REASONING_CHARS = 200
MIN_REASONING_WORDS = 40


def validate_reasoning(reasoning: str, notes: str, summary: str) -> str | None:
    """Return an error string if the reasoning is thin, else None.

    Thin = too short, too few words, or substantially just the release notes /
    summary regurgitated (WHAT, not WHY). The check is intentionally blunt: it
    cannot judge insight, only refuse the obvious box-tick.
    """
    r = (reasoning or "").strip()
    if not r:
        return "reasoning is empty — the WHY of the ship is required (decisions, alternatives, what verification caught)."
    if len(r) < MIN_REASONING_CHARS:
        return f"reasoning is too thin ({len(r)} chars < {MIN_REASONING_CHARS}). Capture the WHY: the decision, the alternatives weighed, what the review/verify actually caught."
    if len(r.split()) < MIN_REASONING_WORDS:
        return f"reasoning is too thin ({len(r.split())} words < {MIN_REASONING_WORDS}). This should read like a reasoning trail, not a headline."
    norm = re.sub(r"\s+", " ", r.lower()).strip()
    for other, label in ((notes, "release notes"), (summary, "commit summary")):
        o = re.sub(r"\s+", " ", (other or "").lower()).strip()
        if o and norm == o:
            return f"reasoning is identical to the {label} (WHAT, not WHY). vibememo needs the reasoning behind the ship, not a copy of the notes."
    return None


def _now_utc_iso() -> str:
    """Timezone-aware UTC ISO-8601 stamp. L2: replaces deprecated utcnow()."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session_stamp_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def resolve_author(explicit: str | None, vibememo_dir: Path) -> str:
    """Pick the vibememo namespace to write into.

    Preference order:
      1. --author flag
      2. sole existing directory under .vibememo/users/ (matches operator setup)
      3. git config user.name (lowercased, spaces stripped)

    INFERRED: FORMAT.md says "author = git username, maps to per-user folder"
    but does not spec normalisation. Existing repo has one folder "ojiudezue"
    which matches the operator's canonical_id, so option 2 wins in practice.
    """
    if explicit:
        return explicit
    users_dir = vibememo_dir / "users"
    if users_dir.is_dir():
        candidates = [p.name for p in users_dir.iterdir() if p.is_dir()]
        if len(candidates) == 1:
            return candidates[0]
    try:
        name = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "config", "user.name"], text=True
        ).strip()
        return re.sub(r"\s+", "", name).lower() or "unknown"
    except Exception:
        return "unknown"


def next_entry_id(entries_dir: Path) -> str:
    """Zero-padded next entry number. Existing files use NNN_slug.json."""
    max_n = 0
    if entries_dir.is_dir():
        for p in entries_dir.iterdir():
            m = re.match(r"(\d+)_", p.name)
            if m:
                try:
                    max_n = max(max_n, int(m.group(1)))
                except ValueError:
                    pass
    return f"{max_n + 1:03d}"


def slugify(text: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return s[:maxlen] or "release"


def build_entry(
    entry_id: str,
    author: str,
    version: str,
    summary: str,
    notes: str,
    reasoning: str,
    cards: list[str],
    now_iso: str,
) -> dict:
    """Assemble a reasoning entry: WHAT in the title, WHY in the summary.

    ``reasoning`` (validated non-thin by the caller) becomes the entry summary —
    the decision trail. ``notes`` (the release blurb, WHAT shipped) is preserved
    under refs so the entry stays self-contained without diluting the WHY.
    """
    ver = version if version.startswith("v") else f"v{version}"
    session_stamp = _session_stamp_utc()
    return {
        "format_version": "2.1",
        "entry_id": entry_id,
        "author": author,
        "session_id": f"claude_{session_stamp}_ship_{ver.replace('.', '_')}",
        "timestamp": now_iso,
        "type": "reasoning",
        "weight": "significant",
        "title": f"{ver} shipped: {summary}",
        "summary": reasoning.strip(),
        "refs": {
            "cards": cards,
            "docs": [f"docs/readmes/README_{ver}.md"],
            "release_notes": notes.strip(),
        },
    }


def write_entry(entries_dir: Path, entry: dict, slug: str) -> Path:
    entries_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{entry['entry_id']}_{slug}.json"
    path = entries_dir / filename
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    # Verify parseable, then rename atomically.
    with open(tmp, "r", encoding="utf-8") as fh:
        json.load(fh)
    tmp.replace(path)
    return path


def _atomic_write_json(path: Path, obj: object) -> None:
    """L5: atomic write via tempfile.mkstemp + os.replace, same-directory.

    Mirrors kanban_ship.atomic_write_yaml: if json.dump errors mid-flight,
    the original file is left untouched. Prevents partial-write corruption
    of index.json on interrupt / disk-full.
    """
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            Path(tmp).unlink()
        except FileNotFoundError:
            pass
        raise


def update_index(user_dir: Path, entry: dict) -> None:
    """Bump index.json entry_count + last_entry. Best-effort; missing file is OK."""
    idx_path = user_dir / "index.json"
    if not idx_path.exists():
        return
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception:
        return
    # entry_count is a soft counter (index at 031 while 032 exists on disk).
    # Bump it to at least our new entry number so the file stays monotonic.
    n = int(entry["entry_id"])
    idx["entry_count"] = max(int(idx.get("entry_count", 0)), n)
    idx["last_entry"] = entry["entry_id"]
    idx["last_updated"] = entry["timestamp"]
    _atomic_write_json(idx_path, idx)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--notes", required=True)
    p.add_argument(
        "--reasoning",
        required=True,
        help="The WHY of the ship — decision, alternatives weighed, what review/verify "
        "caught. Rejected if thin (see MIN_REASONING_* thresholds).",
    )
    p.add_argument("--cards", default="")
    p.add_argument("--author", default=None)
    p.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="override repo root (used by deploy.sh --dry-run rehearsal)",
    )
    args = p.parse_args(argv)

    vibememo_dir = Path(args.repo_root) / ".vibememo"
    author = resolve_author(args.author, vibememo_dir)
    user_dir = vibememo_dir / "users" / author
    entries_dir = user_dir / "entries"

    # Forcing function: refuse a thin entry at the source, before any write.
    err = validate_reasoning(args.reasoning, args.notes, args.summary)
    if err is not None:
        print(f"vibememo_ship: REFUSED — {err}", file=sys.stderr)
        return 2

    entry_id = next_entry_id(entries_dir)
    now_iso = _now_utc_iso()
    cards = [c.strip() for c in args.cards.split(",") if c.strip()]

    entry = build_entry(
        entry_id=entry_id,
        author=author,
        version=args.version,
        summary=args.summary,
        notes=args.notes,
        reasoning=args.reasoning,
        cards=cards,
        now_iso=now_iso,
    )
    slug = slugify(f"v{args.version.lstrip('v')}_{args.summary}")
    path = write_entry(entries_dir, entry, slug)
    update_index(user_dir, entry)
    root = Path(args.repo_root)
    try:
        display = path.relative_to(root)
    except ValueError:
        display = path
    print(f"vibememo_ship: wrote {display} (author={author})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
