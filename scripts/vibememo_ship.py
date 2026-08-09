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
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VIBEMEMO_DIR = REPO_ROOT / ".vibememo"


def resolve_author(explicit: str | None) -> str:
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
    users_dir = VIBEMEMO_DIR / "users"
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
    cards: list[str],
    now_iso: str,
) -> dict:
    """Assemble a milestone entry matching the schema of e.g. entry 031."""
    ver = version if version.startswith("v") else f"v{version}"
    session_stamp = _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return {
        "format_version": "2.1",
        "entry_id": entry_id,
        "author": author,
        "session_id": f"claude_{session_stamp}_ship_{ver.replace('.', '_')}",
        "timestamp": now_iso,
        "type": "milestone",
        "weight": "significant",
        "title": f"{ver} shipped: {summary}",
        "summary": notes,
        "refs": {
            "cards": cards,
            "docs": [f"docs/readmes/README_{ver}.md"],
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
    idx_path.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--notes", required=True)
    p.add_argument("--cards", default="")
    p.add_argument("--author", default=None)
    args = p.parse_args(argv)

    author = resolve_author(args.author)
    user_dir = VIBEMEMO_DIR / "users" / author
    entries_dir = user_dir / "entries"

    entry_id = next_entry_id(entries_dir)
    now_iso = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    cards = [c.strip() for c in args.cards.split(",") if c.strip()]

    entry = build_entry(
        entry_id=entry_id,
        author=author,
        version=args.version,
        summary=args.summary,
        notes=args.notes,
        cards=cards,
        now_iso=now_iso,
    )
    slug = slugify(f"v{args.version.lstrip('v')}_{args.summary}")
    path = write_entry(entries_dir, entry, slug)
    update_index(user_dir, entry)
    print(f"vibememo_ship: wrote {path.relative_to(REPO_ROOT)} (author={author})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
