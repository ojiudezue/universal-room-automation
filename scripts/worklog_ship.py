#!/usr/bin/env python3
"""WORKLOG-APPEND-AT-SHIP-1 — append one release-index line to the month's work log.

Called by deploy.sh step 4b after the push succeeds (same post-push hook as
kanban_ship.py / vibememo_ship.py). The session work log
(docs/planning/WORKLOG_<YYYY-MM>_session.md) lapsed for a week in October
2026 because it was kept by memory; this makes the release index an output
of the deploy. Non-code work (HA config, sibling repos) is still hand-written.

Writes under a trailing "## Release index (auto-appended at deploy)" section,
creating the file and/or section if missing. Idempotent per version: a
second call for the same version is a no-op.

Exit codes: 0 = appended or already present, 1 = error. deploy.sh treats any
failure as a warning (never aborts a pushed release).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

SECTION = "## Release index (auto-appended at deploy)"


def readme_title(repo_root: str, version: str) -> str | None:
    path = os.path.join(repo_root, "docs", "readmes", f"README_v{version}.md")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    return line.lstrip("#").strip() or None
    except OSError:
        return None
    return None


def build_line(version: str, summary: str, cards: str, title: str | None,
               now: _dt.datetime) -> str:
    head = title or summary
    line = f"- {now:%Y-%m-%d %H:%M} **v{version}** — {head}"
    if cards:
        line += f" (cards: {cards})"
    return line


def append(path: str, line: str, version: str, month_label: str) -> bool:
    """Append `line` under SECTION. Returns False if the version was already logged."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = f"# Worklog — {month_label} session\n"
    idx = text.find(SECTION)
    if idx >= 0 and f"**v{version}**" in text[idx:]:
        return False
    if SECTION not in text:
        text = text.rstrip("\n") + f"\n\n{SECTION}\n\n"
    elif not text.endswith("\n"):
        text += "\n"
    text += line + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("--summary", default="")
    p.add_argument("--cards", default="")
    p.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p.add_argument("--file", help="override the worklog path (tests / dry-run)")
    p.add_argument("--now", help="override timestamp 'YYYY-MM-DD HH:MM' (tests)")
    a = p.parse_args(argv)
    now = (_dt.datetime.strptime(a.now, "%Y-%m-%d %H:%M") if a.now
           else _dt.datetime.now())
    path = a.file or os.path.join(
        a.repo_root, "docs", "planning", f"WORKLOG_{now:%Y-%m}_session.md")
    line = build_line(a.version, a.summary, a.cards,
                      readme_title(a.repo_root, a.version), now)
    try:
        wrote = append(path, line, a.version, f"{now:%B %Y}")
    except OSError as exc:
        print(f"[worklog_ship] error: {exc}", file=sys.stderr)
        return 1
    print(f"[worklog_ship] {'appended' if wrote else 'already present'}: {path}")
    print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
