"""Tests for scripts/worklog_ship.py — WORKLOG-APPEND-AT-SHIP-1.

deploy.sh step 4b appends one release-index line per ship to the month's
work log. Pure logic, no shelling out; the deploy.sh warn-only wrapper is
the same pattern as kanban_ship / vibememo_ship.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import worklog_ship  # noqa: E402

NOW = "2026-10-24 09:15"


def _run(tmp_path, *extra):
    return worklog_ship.main([
        "--version", "5.103.70", "--summary", "fix: solcast wiring",
        "--cards", "EC-PREDICTOR-SOLCAST-UNWIRED-1",
        "--repo-root", str(tmp_path), "--now", NOW, *extra,
    ])


def test_creates_month_file_and_section(tmp_path):
    (tmp_path / "docs" / "planning").mkdir(parents=True)
    assert _run(tmp_path) == 0
    text = (tmp_path / "docs" / "planning" / "WORKLOG_2026-10_session.md").read_text()
    assert text.startswith("# Worklog — October 2026 session\n")
    assert worklog_ship.SECTION in text
    assert "**v5.103.70**" in text


def test_appends_under_section_to_existing_log(tmp_path):
    plan = tmp_path / "docs" / "planning"
    plan.mkdir(parents=True)
    log = plan / "WORKLOG_2026-10_session.md"
    log.write_text("# Worklog — October 2026 session\n\n## 1. Hand log\n- did a thing\n")
    assert _run(tmp_path) == 0
    text = log.read_text()
    assert "- did a thing" in text  # hand-written content preserved
    assert text.index(worklog_ship.SECTION) > text.index("- did a thing")
    assert ("- 2026-10-24 09:15 **v5.103.70** — fix: solcast wiring "
            "(cards: EC-PREDICTOR-SOLCAST-UNWIRED-1)") in text


def test_readme_title_preferred_over_summary(tmp_path):
    (tmp_path / "docs" / "planning").mkdir(parents=True)
    rd = tmp_path / "docs" / "readmes"
    rd.mkdir(parents=True)
    (rd / "README_v5.103.70.md").write_text("\n# v5.103.70 — Solar forecast restored\n\nbody\n")
    assert _run(tmp_path) == 0
    text = (tmp_path / "docs" / "planning" / "WORKLOG_2026-10_session.md").read_text()
    assert "**v5.103.70** — v5.103.70 — Solar forecast restored" in text
    assert "fix: solcast wiring" not in text


def test_idempotent_per_version_and_no_prefix_collision(tmp_path):
    (tmp_path / "docs" / "planning").mkdir(parents=True)
    log = tmp_path / "docs" / "planning" / "WORKLOG_2026-10_session.md"
    assert worklog_ship.main(["--version", "5.103.7", "--repo-root", str(tmp_path), "--now", NOW]) == 0
    # 5.103.70 must NOT be treated as already logged because 5.103.7 is.
    assert _run(tmp_path) == 0
    assert _run(tmp_path) == 0  # second call for same version: no-op
    text = log.read_text()
    assert text.count("**v5.103.70**") == 1
    assert text.count("**v5.103.7**") == 1
    assert text.count(worklog_ship.SECTION) == 1


def test_new_month_file_created_with_header(tmp_path):
    (tmp_path / "docs" / "planning").mkdir(parents=True)
    assert worklog_ship.main(["--version", "5.104.0", "--summary", "s",
                              "--repo-root", str(tmp_path), "--now", "2026-11-01 08:00"]) == 0
    text = (tmp_path / "docs" / "planning" / "WORKLOG_2026-11_session.md").read_text()
    assert text.startswith("# Worklog — November 2026 session\n")
    assert "- 2026-11-01 08:00 **v5.104.0** — s" in text
    assert "(cards:" not in text


def test_unwritable_path_returns_error_not_raise(tmp_path):
    # Missing parent directory -> OSError -> rc 1 (deploy.sh warns, continues).
    assert worklog_ship.main(["--version", "1.0.0", "--repo-root", str(tmp_path),
                              "--file", str(tmp_path / "nope" / "x.md"), "--now", NOW]) == 1
