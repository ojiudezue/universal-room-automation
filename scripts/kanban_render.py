#!/usr/bin/env python3
"""kanban_render.py — render kanban.data.yaml into KANBAN.md + kanban_board.html.

Pure function of the data file: same input -> byte-identical output.

Exit codes:
  0 = fresh (rendered, meta.last_reconciled is up to date)
  1 = error
  2 = stale (rendered anyway; STALE banner in both outputs)

Usage:
  python3 scripts/kanban_render.py                   # write both outputs
  python3 scripts/kanban_render.py --check           # exit code only, no writes
  python3 scripts/kanban_render.py --data <path>     # override data file
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO_ROOT / "docs" / "planning" / "kanban.data.yaml"
DEFAULT_MD = REPO_ROOT / "docs" / "planning" / "KANBAN.md"
DEFAULT_HTML = REPO_ROOT / "docs" / "planning" / "kanban_board.html"
DEFAULT_PENDING = REPO_ROOT / "docs" / "planning" / "kanban.dispositions.pending.jsonl"
README_DIR = REPO_ROOT / "docs" / "readmes"

# URA brand favicon — 48x48 PNG from universalroom.org/assets/brand/icon.png,
# inlined as a data URI so the static board is self-contained (no extra deploy file).
URA_FAVICON = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAABGdBTUEAALGPC/xhBQAAACBjSFJNAAB6JgAAgIQAAPoAAACA6AAAdTAAAOpgAAA6mAAAF3CculE8AAAARGVYSWZNTQAqAAAACAABh2kABAAAAAEAAAAaAAAAAAADoAEAAwAAAAEAAQAAoAIABAAAAAEAAAAwoAMABAAAAAEAAAAwAAAAANs3bAwAAAHLaVRYdFhNTDpjb20uYWRvYmUueG1wAAAAAAA8eDp4bXBtZXRhIHhtbG5zOng9ImFkb2JlOm5zOm1ldGEvIiB4OnhtcHRrPSJYTVAgQ29yZSA2LjAuMCI+CiAgIDxyZGY6UkRGIHhtbG5zOnJkZj0iaHR0cDovL3d3dy53My5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIyI+CiAgICAgIDxyZGY6RGVzY3JpcHRpb24gcmRmOmFib3V0PSIiCiAgICAgICAgICAgIHhtbG5zOmV4aWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20vZXhpZi8xLjAvIj4KICAgICAgICAgPGV4aWY6Q29sb3JTcGFjZT4xPC9leGlmOkNvbG9yU3BhY2U+CiAgICAgICAgIDxleGlmOlBpeGVsWERpbWVuc2lvbj4yNTY8L2V4aWY6UGl4ZWxYRGltZW5zaW9uPgogICAgICAgICA8ZXhpZjpQaXhlbFlEaW1lbnNpb24+MjU2PC9leGlmOlBpeGVsWURpbWVuc2lvbj4KICAgICAgPC9yZGY6RGVzY3JpcHRpb24+CiAgIDwvcmRmOlJERj4KPC94OnhtcG1ldGE+CuYattQAABGmSURBVGgFnVppbFzXdf5m5s2QM9wXUyS1y9Qu25IoyWskb/FSxbGSKKkboAkQBHCMFkVrxAXaX/7TAv2bP4X7pwXaxkibokFs2Cocs94dRbUtL4plkbYkWiIpiuIyHM4+8/p95943JBUVaHvFmXffveee853lnruMYrV6NYwhBishEIsDYRhicq6Gz6freOuzGr6cZjtJ2MxiX3xqTJzteg9Rr4cgL6BeQ61WRa1aQalUNl6pVApBECBIpsg/QDyR4DgKUpFMV/MVNvCvTlTrbgpxeGcCN/clMNgt+rjxk0QHI0SsLsksxoRfo5MVvPxBjc8QxQqQYFtcYxsakFx1jggJtlwuolwqolIuU4maCTDmEUNSyiBRiZOZFJBSyVQzn83kT2AiIGgHhG/8E7JaLURzChgaAB7dG2DbYNL6jJ5DYjVSxAhIljxxuoxfnqqhUo0jSAinyNxHXrJBpJV1i/kllIoFs7bwiYcTriG0jB9pjaYMG1isnfSh42aeSTWnkU63sJ5qWNgNcd/iX6U2qSDEY8MJPLKvyY2WXFrNFDhxuoSfv1tDMhGFhaRRjIhMsixexVIuZ+BlbXlCuK2QTkXWdm1eYY5WzfhEtCL0dbWrM54I0JxpQTrThoR5RB3EYlAdsWgrtTqO30kl9lIJvsdlOYXNL09VkQwEXtxZzPpOjtpk7dmZq1QgS9fWHXiSWXiQk57Xg494mT8ivh6SM6EaJTNuc2gpu4j5a9OcO0W2ecUjTTlA/GTgF/6rapj1Hq9T8MsfVKhZjNoQmOPMB3s1vfnILS5gYXYGtUqV7GxCGJkDTxvJWCwkXf2t8b7F9alf6njv+HH24JdAV6tVyrqGpcWsp9UYFRHUiTFEmSEuzMIevzJfw9hknZoZiaP138wtWJhfZuYRktBLlnYrCmORXQ6yYGoSuhQhopW0TolGm7ETQGdlIZEC2fk58pNRNZzjSSL2SWaW0SlA2OOfX6miUJGlxVSEYiTaOhnMMt7zfKfVxcDaRcRixKo4epvEavTja5wiTckYUvxUhUH00cfoRKvxfHjeYmUfT1coLJkBhcV8afSSxwxZDqlEFcEbZ+ucNN6lYmY8QiwuzKFYKJC5QsYa7WGURiRpLFb342UEgilVQuxan8KPHus3kudevIIz4yUqRF4axjFVpkefwY2Gob0Kh9mFvMqlAhZpyI6uXlPCS2WWjOH1T2uIPfV3OXne83WeyGaz5kLO8Ea0mBTjylrEpVEhAynCr1Kljtu3Z/AnxwbQ3sKczbKYr+Inv5jAybN5NKXiXPCALWuSWNfLtOl5jE2UMDnLkDA+xorsPLB6Ha3tHWjhx5H7UYynIBGvoxZ6K5O+yGyTzy06t4o6YqLQWFn0HjV58GWCf3BfK548OsDFJ0HlNR5oywT48bfX4rkXJ/Gr0znzxB99fQ02D2QaHN8+s4C/+ZcppLRyGj92RXONWuWY/QIufk1cMxrNVCBuGOyLCxS3AIsL2QaB9HQgHBCTJtpIgCrmpRgXvxqO3dWBP358cBV4kYpHE7OE+o7d1Wmhk1DM+D49NVeWA1kdao2K61nMzhMjJ5cVYqMRg5WTPM9FqlqpeOuTihpqqDLLSgc4wzqm9TohhjX84QM9OH74Jsc6MhFBRDikhLYMP3h4DbpbowWK5N4YIdOVhom+ISsarElMQ1XKVUZH1sLJDMv2QBKJz4Dn8zmtK2pZluxM6BibtX032xXLCsEnj/bhoQM91mHYbYz4+OLfJVQReezuPnqhTp4+811PJ2kk1DArVnEJosAtjFbsRELzS+sC1ZV22tuIqRvGEfyTYpEICVaxB7+URdLcZP34eL+BF7gGeEfqvv04e2HdGVXecB0NI68UQE+pWJ/IrE84lbnqhtWRcxILYMjYLxXzHryGOeYNV9orv9il3ko1RE9bHE8fH8Atm9ssxtVj+Zz9VhyL6M0ZxBCttLuXJVpWI3nRszHY1hGa1tNpW9PS2sbliZtO5flK2e0qlwGYpEgP8vHg+VCmWd8b4M+/sxab+jMEL+6kYF+pBJzn4tKWJmMGJ+2C85NVZPN1HNiewk2dtGxk+chdAsUiD2rH6RIveToTO4v5ehSCSjblShnNTRkqwBRaKhZpAPnCc4uefFWLBqqiHL9zXROeYUrs69JucNnq+QLw9m8r+NUnZQz1xdHbyknH88RH57mAUZnZhRraM3EeUgL0dMSwYTCQ0T1A7vfXpunNZpy56Bc8gRaBABgIPViRe/hXIeZ0Ko3Ewcf/4tkc9x0u/hV7oo4K6yvA374tQ8uvQ3e727drJZ26FmJsooZ3zlbQzP1Ukm796m0p7B9K4ir3Kv1dCXz7cAt2b0libiHE8ycW8clYGVsGU+hiGKoIa4ZaHtrRistXS7g4XUFgniJS7QQ0Ga2sfqY5meOKf7mkMXmltS+WKMm9zK3BA7e14hmC1+qqsJHQuWyI517J480zFRzZlcSRW5LoTIM03MjRTKOXK9hAi3fS4uIxMVPGo3dl8Hv3tODVd5fwxZeUSz6ykbzZnklSxlo8uLeV9DrdEQiNFDMFHHjhVK1OzCHTd2L46DPP5pj/G/EvjkbCJ/+0ZX3s9g48+bUBnojc6hrRnhrllpbb8JamGDby3NrdEcf4dA2XrtawnsDX9ibw9idFmxNfTrn15WEq0N/DIyX3RSO/znNMgC4qKJ7Cy60BDm5vZbjWcO5yycG1WS1czluWHYlLp7jE3keefjbPTZuhJROnnyMuM9vsH0rjz761TvmWNM49zGT49KK24TV8885mZqQYXnm/DJ7hcYiTVRP5F28vmRK97Qks5OrWN89l5gK98t6ZIqZnqzgzWsaliTIO3ZZhXnfspYhk7RtqxeilPMZnKn7eS0kHE1o86eNkUxqBLc3aC6mXqjmIjlBNVxeq+HQ8hwz3NpnmODNJCpdp5X8aKeDw7hRaGS65fAyzizW8zFPdzvUB7t7dhItX6B0qqq3N+FQN5wl0KU+F723DPfuaMb9Qx9wcCWjJq9dqGOyXBsDMAumKNRRKdcxkqw68YoleELYYQ8qMTVOXKzy5/f5fj4YVnrTUqDwUPRXFelUIJTi4xoH33tqOP/3GWkxT4M9eK3JnGcPWwQSmuIvcuCZArsjIJ90du5oxea2KyZkqxi5VuFqH2DKQwpqeADtv5hwi6xHOAe1/0jTK1JUyjj6gvB7DT/59AiMfZnlGZhqmYRNmWMGiB6SI1FCdT+2nAr/oefAi1KQxPUwBEUppHTlNeXZ1MmSUCg9tbcbpL4o4ea6E/duSGN7WhL8/kcPlmRw66Jn+rgAP35FhuovjAj1wiV65zM8kD1Efnyviqe92M6PF8dkYr2YYrjIIF3hUKEj7/RiPkIRpYAResCxSZFm+BzRAcGhHGiPv5Xigl25OSyP1qUu6apBubkwx8pDlttDlH18o4cDWJub5ONqYQ0+dLaGXgO7bm0abhVaIj8ZK0ATu6w4YfgnbaulCYy6bxJsnl7B5PdcTxjSTChmbzSiRd0fCItlEbeDlCb3onTVtZfYNNSPYsz6NV6nA7xRq6MAz8/iBbqjxwMEdSbzOe6TXPy4gQ4VePpk3Ixw/kjFFPhwtobMljg39TK/DGW4WQwz0BSgwzDqp5JGDaUwxxE6M5HD2syLuOZjBpo1aFwSSGoaR5R0ygZZ8RYT+KRr2rKcCfZyUNKAVtpHGaW1q+lhyilivI+R3Iojh8N4U5hfd4v8RFydloQxBC6Ri9+uHW7kGxPHSG0v8LGL/zjSuMftMMYye/mEvNq5Loo/zArRkB0NSRXv8UItYtIAJQ4RJ0A1ezLLWQBex93UGll0KFC46x4acrCJqMrDFUHovFzUr9fV2Oe1vvTmFF99awjunY9i5qYlbgxQ+/KyEK5zMuh584tEOLnAB3vpNDsN7MnwuYZBHyiWm2O890cGcLoHLEvTWuBlks+aCrG80fGS49vR1JRHvaacVqIRcIihuoHvau9dBqpsnSGNFvMSST2We3q4YvnFvC2a5fXjndB6/4QL2wmtZXGTef/z+NuwZasLnXxQIvhnfPdbOxS2Bf/zpLHZx3RB4d8CXdHIVb+Mv5g6Lb7C+kPl5DRfAXmIPdBu3g7E0NrHIdBcRGxvvLjF0sadWFfkiWo2tga6TvPY24OjhjB10tAYcHk7j5Ed5fgoY5WQev1TGHiaN8+MVC6UHmTo3b3L7KnnfijArfHzYiK/q1i1rUbsq8/B2Yk5yZ8AABIaHMnjp1AJrmjgOoHvSK8zFodJZjHsTg0kejh2tf50iClD+JRLK0cC6gTi6O1vxby9l0UFrtWRqOPl+gVmLAOiRA/t5M01A8n7E04B7OcaM/KSQ2w8RA5XR/Bre2mJYLXnu2tiCtd1Ju9aIvKAMrEGaVBE/s4K9UBWBZbGtttUozqwWqak+xirDY+fNTZjgaryBi9n+W9LYNhSYggobAy9WZl2qwTG6aZBPxU4lRosLuPjXeY4dINbdG3WjwZOdAGSaA3xlT6vd/MqCHhsJ/L09G5WXo+JkLQtQeyTMaETqycV/aHOKZ44a5piBXnxpjucEGYAofVlRNT002HnES6VWphAVqfBW4p49LcSsXTE3f05SiAf3d+LEe1leQjlgJp+h41jJqmx3lzANcGyyuhMmNGY61yjuZCKSdq7cD93firPnyrxp402CBa4jMwJWIwtoO6FxNlYsZHn1k1BRoTPEV4nVcTYFWKWwmzqb8MiBDvx0ZNZuzyTYmcMB0Q5xqcCZSXZuZ2pVz1zEKk6UfS9/sTnkHIjj9gM8LKwoK0mi5jzXEPM7rW3QBcTcy1tpeu5bd3cya7rToMZEtmCV+/47uvHubxcxfpWXpitvyMgqxcnxyYU8nh+ZxoY+zyCKGxNiX+TCp6u6p6Q4vZbbHTT1NIpYjU+XeATliq59kHr8/FOdxwOeOQLDuMyYJPqFxnHhIHL5YCyLv3p+UqP5F7nPUYihrNAAqGYDKxGeDZ9uMitq5TFXDBCrimabZFGDxq3goWt+G+9UYN2C19aav3yiH/u3tlvE+EGrFZAoDf7Za9P45/9kKDVukylNAg1jBFRAbICGsUTt1ujIzYIO6arhavcAHQ9jsIJfxFtH15BbFK7k93bhD+7r8+A9PR9abFcVzYfjh3tx/21tNrAhSMa09MQhekZ1jRaeCL+AsW6vpBFwhYd7j4hFLyIyZaLQ6crVjYqO1ijVeeFG8PfxPP6dI70O/DIj9t9AATXqR7Yffa0fd+3KoMR9uikhFOKrL6uz3YS7psbmSzZRv9/Ha7RbM0SvjzHhU3Ru0yxjNMKGivH4ZLS6xrlzZ8awCJOVCIP48t+qOeAo9O3iuFiu42/548TIh0sMp+vmA2nMC6aEuDLmG0BkUbY1QkWRr5Vc66baZXUVqSe+DpybMy7mdYF2360teIo/kjTzQCSH/W65oQKOqYhlLB0l//WNa/j5m7raZtqK8paAULQDsTxG4xwoKsTthwPsFiSDRlI93TgjZVUKsI0K66CiDPjNuzssbPTrkY6115uPA6zcwAMRGIph1V3CxvD+6CL+4ZUZXOBxUGku8qhxEaF0YdFNX+MnH+iYpUYCNIU93Upzykv805aiQvCb+lL4/kO93OtwZ8gOB96Y6Ou60vCAl76qmxwjVKrRHblCFS/8ehb/wRX72iLvMamILBQ5wvlD3wohx0x7KXcY51ViTArpnQqRTAlDHuZvI+jh9cvDw+2W51vTpF2ppGN1g++GAuqT4BuVZUXc/Ither6EV99fwFtnljDB/Y1CS4roIxq78G3Ev3hSkK2v8qoDXeM5WLcVgzwrf+WWNjywt8PuW0X7v8LuoTKElGbcJLoR/OU2b1JCiRTJF3k5dTHP8FrC2UslTM/xF5QS/7cKHSAa/X8LhY7e7XqGYjJNcTtAbV/XbFvi3Zsytpn8vwKPcPE/e0iB/8n6EdnKZ6SIAxn9DFvhj8G6iLoyV8HUXAnnJoo4/Tmvpwn+Vm6fdwymec3CuyEeA3s6krymjIzGOCfN/6corP8bAWwoXijzvR4AAAAASUVORK5CYII="

# Column display order + labels + emoji. Anything not in this map falls into "other".
COLUMN_META: list[tuple[str, str, str, str]] = [
    ("inbox",            "\U0001F4E5", "Inbox",              "raw capture"),
    ("investigating",    "\U0001F52C", "Investigating",      "measuring; truth not yet known"),
    ("pre_planning",     "\U0001F9ED", "Pre-planning",       "idea being decomposed"),
    ("planned",          "\U0001F4DD", "Planned",            "has plan / acceptance"),
    ("in_progress",      "\U0001F528", "In progress",        "being built"),
    ("review",           "\U0001F50D", "Review",             "under review"),
    # WAITING-OP-INSTRUCTIONS-1: waiting_operator/waiting_me are elevated to
    # just after review (ahead of shipped_organic) so the operator's decision
    # queue is prominent — these lanes are groomed FIRST each session.
    ("waiting_operator", "⏸️", "Waiting on operator", "needs a human call — groomed first"),
    ("waiting_me",       "⏳", "Waiting on me (Claude)", "I owe something"),
    ("shipped_organic",  "\U0001F680", "Shipped (organic open)", "live, awaiting proof"),
    ("parked",           "\U0001F17F️", "Parked",       "revisit-trigger set"),
    ("done",             "✅", "Done",                    "closed, evidence in refs"),
    ("other",            "❓", "Other",                    "unknown status bucket"),
]

# Fields we render *structurally*. Anything else on a card is a "forensic" key.
STANDARD_FIELDS = {
    "id", "title", "thread", "status", "approval",
    "approved_by", "approved_on", "autonomy",
    "created", "updated", "refinement_status", "problem_solution",
    "tags", "origin", "why", "next", "refs",
    "parsimony", "constraints", "parked_alts", "refinement",
    "knobs", "depends_on", "blocks", "sibling_of",
    "batch", "seq", "shipped_version",
    "links", "rank", "live_broken", "disposition",
    "_wsjf", "_lane_rank",  # transient render-only annotations (see compute_wsjf/group_cards)
}

APPROVAL_COLOR = {
    "unreviewed": "#888",
    "implied":    "#3a7",
    "explicit":   "#28a",
    "blocked":    "#c33",
}


# ---------- helpers ----------

def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        out = subprocess.check_output(cmd, cwd=cwd or REPO_ROOT, stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _git_hash(path: Path) -> str:
    h = _run(["git", "log", "-1", "--format=%H", "--", str(path)])
    return h or "unknown"


def _git_commit_iso(path: Path) -> str:
    """ISO-8601 commit date of the last change to the data file. Fallback to mtime."""
    iso = _run(["git", "log", "-1", "--format=%cI", "--", str(path)])
    if iso:
        return iso
    try:
        return _dt.datetime.utcfromtimestamp(path.stat().st_mtime).isoformat() + "Z"
    except OSError:
        return "unknown"


def _newest_tag_date() -> tuple[str, str]:
    """(tag_name, date_iso) of the most recent v*.*.* tag."""
    tags = _run(["git", "tag", "-l", "v*", "--sort=-creatordate"]).splitlines()
    for t in tags:
        if re.match(r"^v\d+\.\d+\.\d+$", t):
            iso = _run(["git", "log", "-1", "--format=%cI", t])
            return t, (iso[:10] if iso else "")
    return "", ""


_SEMVER_RE = re.compile(r"README_v(\d+)\.(\d+)\.(\d+)\.md$")


def _newest_readme() -> tuple[str, str]:
    """(filename, date) of the highest-version README_v*.md."""
    if not README_DIR.is_dir():
        return "", ""
    best: tuple[tuple[int, int, int], Path] | None = None
    for p in README_DIR.iterdir():
        m = _SEMVER_RE.match(p.name)
        if not m:
            continue
        ver = tuple(int(x) for x in m.groups())
        if best is None or ver > best[0]:
            best = (ver, p)
    if best is None:
        return "", ""
    p = best[1]
    iso = _run(["git", "log", "-1", "--format=%cI", "--", str(p)])
    if iso:
        date = iso[:10]
    else:
        date = _dt.datetime.utcfromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
    return p.name, date


def _parse_date(s: str) -> _dt.date | None:
    if not s:
        return None
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def compute_staleness(meta: dict, tag: tuple[str, str], readme: tuple[str, str]) -> tuple[bool, list[str]]:
    """Return (is_stale, reasons_list). Reasons are human-readable."""
    last = _parse_date(meta.get("last_reconciled", ""))
    reasons: list[str] = []
    if last is None:
        reasons.append("meta.last_reconciled is missing or unparseable")
        return True, reasons
    tag_name, tag_date_s = tag
    tag_date = _parse_date(tag_date_s)
    if tag_date and tag_date > last:
        reasons.append(f"newest git tag {tag_name} ({tag_date_s}) is newer than last_reconciled ({last.isoformat()})")
    readme_name, readme_date_s = readme
    readme_date = _parse_date(readme_date_s)
    if readme_date and readme_date > last:
        reasons.append(f"newest README {readme_name} ({readme_date_s}) is newer than last_reconciled ({last.isoformat()})")
    return (len(reasons) > 0), reasons


def load_pending_dispositions(path: Path) -> dict[str, list[dict]]:
    """Read kanban.dispositions.pending.jsonl -> {card_id: [{action, at}, ...]}.

    Operator dispositions queued from the hosted board, not yet applied to
    kanban.data.yaml. Missing file -> empty map (the common case).
    """
    import json
    out: dict[str, list[dict]] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        cid = str(d.get("card_id", "")).strip()
        if not cid:
            continue
        entry = {"action": str(d.get("action", "?")), "at": str(d.get("at", ""))}
        # WAITING-OP-INSTRUCTIONS-1: preserve the operator's free-form text
        # (action=instruct) so the pending chip can show it.
        if d.get("text"):
            entry["text"] = str(d.get("text"))
        out.setdefault(cid, []).append(entry)
    return out


def autonomy_stats(data: dict, now: _dt.datetime | None = None) -> dict:
    """BOARD-AUTONOMY-PROGRESS-1: compute the last-24h progress counter and the
    live feed (entries not acknowledged AND younger than 7 days, newest first).

    - numerator   = feed entries whose `at` is within the last 24h (ack-agnostic;
                    a conclusion is a historical fact).
    - denominator = cards whose status != 'done' (shrinks as work completes).
    - live feed   = unacknowledged entries younger than 7 days.
    """
    now = now or _dt.datetime.now()
    cards = data.get("cards", []) or []
    denom = sum(1 for c in cards if str(c.get("status", "")) != "done")
    feed = (data.get("meta", {}) or {}).get("autonomy_feed", []) or []

    def _parse(ts: str) -> _dt.datetime | None:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return _dt.datetime.strptime(ts, fmt)
            except (ValueError, TypeError):
                continue
        return None

    last24 = 0
    live: list[dict] = []
    for e in feed:
        if not isinstance(e, dict):
            continue
        ts = _parse(str(e.get("at", "")))
        age = (now - ts) if ts else None
        if age is not None and age <= _dt.timedelta(hours=24):
            last24 += 1
        archived = (age is not None and age > _dt.timedelta(days=7))
        if not e.get("acknowledged") and not archived:
            live.append({**e, "_sort": ts or _dt.datetime.min})
    live.sort(key=lambda e: e["_sort"], reverse=True)
    return {"num": last24, "denom": denom, "live": live}


# ---------- card classification ----------

def _column_for(status: str) -> str:
    known = {k for k, *_ in COLUMN_META}
    return status if status in known else "other"


# ---------- WSJF ranking (operator-finalized 2026-09-11) ----------
# WSJF = (value + time_criticality + unblock) / effort   (higher = do sooner)

_TIER_EFFORT = {
    "hotfix": 2, "tier-1": 2, "tier1": 2,
    "tier-2": 5, "tier2": 5,
    "tier-2db": 8, "tier2db": 8, "tier-2-db": 8,
    "tier-3": 13, "tier3": 13,
}
_FOUNDATIONAL_TAGS = {"platform-enabler", "shared-primitive"}
_DEFAULT_VALUE = 5
_DEFAULT_TC = 3
_DEFAULT_EFFORT = 5


def _card_tags(card: dict) -> set:
    return {str(t).lower() for t in (card.get("tags") or []) if t is not None}


def _tier_effort(tags: set) -> int:
    efforts = [e for t, e in _TIER_EFFORT.items() if t in tags]
    return max(efforts) if efforts else _DEFAULT_EFFORT


def _links_of(card: dict) -> dict:
    links = card.get("links")
    return links if isinstance(links, dict) else {}


def build_blocks_count(cards: list[dict]) -> dict:
    """For each card id, how many distinct other cards depend on it (it unblocks them)."""
    deps: dict = {}

    def bump(enabler, dependent):
        if enabler and dependent and enabler != dependent:
            deps.setdefault(str(enabler), set()).add(str(dependent))

    for c in cards:
        cid = c.get("id")
        links = _links_of(c)
        for t in (links.get("blocks") or []):
            bump(cid, t)
        for fld in ("blocked_by", "after", "depends_on"):
            for x in (links.get(fld) or []):
                bump(x, cid)
        for t in (c.get("blocks") or []):
            bump(cid, t)
        for x in (c.get("depends_on") or []):
            bump(x, cid)
    return {k: len(v) for k, v in deps.items()}


def compute_wsjf(card: dict, blocks_count: dict) -> dict:
    rank = card.get("rank") or {}
    if not isinstance(rank, dict):
        rank = {}
    tags = _card_tags(card)
    value = rank.get("value", _DEFAULT_VALUE)
    tc = rank.get("time_criticality", _DEFAULT_TC)
    if card.get("live_broken") or "live-broken" in tags:
        tc = max(tc, 8)
    fanout = blocks_count.get(str(card.get("id")), 0)
    foundational = rank.get("foundational")
    if foundational is None:
        foundational = 6 if (tags & _FOUNDATIONAL_TAGS) else 0
    unblock = min(10, max(2 + 2 * fanout, foundational))
    effort = rank.get("effort") or _tier_effort(tags)
    try:
        score = (value + tc + unblock) / effort
    except ZeroDivisionError:
        score = 0.0
    default_scored = not any(k in rank for k in ("value", "effort", "foundational"))
    return {"wsjf": round(score, 1), "value": value, "tc": tc,
            "unblock": unblock, "effort": effort, "fanout": fanout, "default": default_scored}


def _sort_lane(key: str, lane: list, blocks_count: dict, in_progress_batches: set) -> list:
    if key in ("done", "other"):
        ordered = sorted(lane, key=lambda c: str(c.get("updated", "")), reverse=True)
        for c in ordered:
            c["_wsjf"] = compute_wsjf(c, blocks_count)
            c["_lane_rank"] = 0
        return ordered

    def sortkey(c):
        w = compute_wsjf(c, blocks_count)
        batch = c.get("batch")
        affinity = 1 if (batch and batch in in_progress_batches) else 0
        return (-w["wsjf"], -affinity, -w["unblock"], str(c.get("updated", "")))

    ordered = sorted(lane, key=sortkey)
    for i, c in enumerate(ordered, 1):
        c["_wsjf"] = compute_wsjf(c, blocks_count)
        c["_lane_rank"] = i
    return ordered


def group_cards(cards: list[dict]) -> dict:
    buckets: dict = {k: [] for k, *_ in COLUMN_META}
    for c in cards:
        buckets[_column_for(str(c.get("status", "")))].append(c)
    blocks_count = build_blocks_count(cards)
    in_progress_batches = {c.get("batch") for c in buckets["in_progress"] if c.get("batch")}
    for key in buckets:
        buckets[key] = _sort_lane(key, buckets[key], blocks_count, in_progress_batches)
    return buckets


def _wsjf_badge_text(c: dict) -> str:
    w = c.get("_wsjf")
    if not isinstance(w, dict):
        return ""
    rank = c.get("_lane_rank") or 0
    head = f"#{rank} · " if rank else ""
    mark = " ⚠" if w.get("default") else ""
    return (f"{head}WSJF {w['wsjf']} · "
            f"v{w['value']} tc{w['tc']} u{w['unblock']} /e{w['effort']}{mark}")


def _first_line(value: Any) -> str:
    """First non-empty line of a scalar-or-collection value, trimmed."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            s = _first_line(item)
            if s:
                return s
        return ""
    if isinstance(value, dict):
        for k, v in value.items():
            s = _first_line(v)
            if s:
                return f"{k}: {s}"
        return ""
    text = str(value).replace("\r", "").strip()
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    if len(line) > 240:
        line = line[:237] + "..."
    return line


def _forensic_keys(card: dict) -> list[str]:
    return [k for k in card.keys() if k not in STANDARD_FIELDS]


# ---------- markdown ----------

def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def render_markdown(data: dict, meta_extras: dict) -> str:
    meta = data.get("meta", {}) or {}
    cards = list(data.get("cards", []) or [])
    parked_extra = data.get("parked", []) or []
    backlog_refs = data.get("broader_backlog_refs", []) or []
    buckets = group_cards(cards)

    out: list[str] = []
    out.append("# URA Kanban - generated view")
    out.append("")
    out.append(
        "> **GENERATED - do not hand-edit.** Source of truth is "
        "`docs/planning/kanban.data.yaml`. Regenerate via `python3 scripts/kanban_render.py`."
    )
    out.append("")
    out.append(f"_Generated: {meta_extras['gen_ts']}_ - "
               f"_Data commit: `{meta_extras['data_hash'][:12]}`_ - "
               f"_last_reconciled: {meta.get('last_reconciled', '?')}_")
    out.append("")
    if meta.get("target_host"):
        out.append(f"**Hosted:** https://{meta['target_host']}")
    if meta.get("artifact_url"):
        out.append(f"**Artifact:** {meta['artifact_url']}")
    out.append("")

    if meta_extras["is_stale"]:
        out.append("> ## ⚠️ STALE - board has not been reconciled against newer work")
        out.append(">")
        for r in meta_extras["stale_reasons"]:
            out.append(f"> - {r}")
        out.append(">")
        out.append("> Reconcile the board (update `meta.last_reconciled` + move shipped cards) before "
                   "using it to pick next work.")
        out.append("")

    out.append("## Columns")
    out.append("")
    out.append("| Column | Count |")
    out.append("|---|---:|")
    for key, emoji, label, _hint in COLUMN_META:
        n = len(buckets.get(key, []))
        if n == 0 and key == "other":
            continue
        out.append(f"| {emoji} {_md_escape(label)} | {n} |")
    out.append("")

    for key, emoji, label, hint in COLUMN_META:
        cards_here = buckets.get(key, [])
        if not cards_here and key == "other":
            continue
        out.append(f"## {emoji} {label} ({len(cards_here)})")
        out.append(f"_{hint}_")
        out.append("")
        if not cards_here:
            out.append("_(none)_")
            out.append("")
            continue
        for c in cards_here:
            out.extend(_render_card_md(c, meta_extras.get("pending", {})))
            out.append("")

    if parked_extra:
        out.append("## \U0001F17F️ Parked ideas (top-level list)")
        out.append("")
        for item in parked_extra:
            if isinstance(item, dict):
                title = item.get("title", "?")
                trig = item.get("revisit_if") or item.get("status") or ""
                out.append(f"- **{_md_escape(str(title))}** - {_md_escape(str(trig))}")
            else:
                out.append(f"- {_md_escape(str(item))}")
        out.append("")

    if backlog_refs:
        out.append("## Broader backlog references")
        out.append("")
        for item in backlog_refs:
            out.append(f"- {_md_escape(str(item))}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def _render_card_md(c: dict, pending: dict[str, list[dict]] | None = None) -> list[str]:
    cid = str(c.get("id", "?"))
    title = str(c.get("title", ""))
    thread = str(c.get("thread", ""))
    approval = str(c.get("approval", ""))
    status = str(c.get("status", ""))
    origin = c.get("origin", {}) or {}
    origin_line = ""
    if isinstance(origin, dict):
        od = origin.get("date", "")
        og = origin.get("gist", "")
        origin_line = f"{od} - {og}".strip(" -") if (od or og) else ""

    lines: list[str] = []
    _badge_txt = _wsjf_badge_text(c)
    _badge_md = f" — _{_md_escape(_badge_txt)}_" if _badge_txt else ""
    lines.append(f"### `{cid}` - {_md_escape(title)}{_badge_md}")
    for disp in (pending or {}).get(cid, []):
        lines.append(f"> **⚡ OPERATOR: {_md_escape(disp['action'])} — pending apply** (at {disp['at']})")
    tag_bits = []
    if thread:  tag_bits.append(f"thread: **{thread}**")
    if status:  tag_bits.append(f"status: **{status}**")
    if approval: tag_bits.append(f"approval: **{approval}**")
    if tag_bits:
        lines.append(" - ".join(tag_bits))

    # created / updated / refinement status meta line
    created = str(c.get("created", "") or "")
    updated = str(c.get("updated", "") or "")
    ref_status = str(c.get("refinement_status", "") or "")
    n_refine = len(c.get("refinement") or []) if isinstance(c.get("refinement"), list) else 0
    meta_bits = []
    if created: meta_bits.append(f"created {created}")
    if updated and updated != created: meta_bits.append(f"updated {updated}")
    if ref_status:
        rlabel = ref_status
        if ref_status == "refined" and n_refine:
            rlabel = f"refined ×{n_refine}"
        meta_bits.append(rlabel)
    elif n_refine:  # inferred when the field is absent but a trail exists
        meta_bits.append(f"refined ×{n_refine}")
    if meta_bits:
        lines.append(f"_{' · '.join(meta_bits)}_")

    # Problem / Solution — the plain-language core, rendered prominently.
    ps = c.get("problem_solution")
    if isinstance(ps, str) and ps.strip():
        ps = [ps]
    if isinstance(ps, list) and ps:
        lines.append("- **Problem / Solution:**")
        for item in ps:
            lines.append(f"  - {_first_line(item)}")

    if origin_line:
        lines.append(f"- **Origin:** {_first_line(origin_line)}")
    for label, key in (("Why", "why"), ("Next", "next")):
        v = _first_line(c.get(key, ""))
        if v:
            lines.append(f"- **{label}:** {v}")
    tags = c.get("tags") or []
    if isinstance(tags, list) and tags:
        lines.append(f"- **Tags:** {', '.join(str(t) for t in tags)}")
    for label, key in (("Depends on", "depends_on"), ("Blocks", "blocks"), ("Sibling of", "sibling_of")):
        v = c.get(key)
        if isinstance(v, list) and v:
            lines.append(f"- **{label}:** {', '.join(str(x) for x in v)}")
    pars = c.get("parsimony") or {}
    if isinstance(pars, dict) and pars:
        verdict = pars.get("verdict", "")
        problem = _first_line(pars.get("problem", ""))
        if verdict or problem:
            lines.append(f"- **Parsimony:** [{verdict}] {problem}".rstrip())
    refs = c.get("refs") or []
    if isinstance(refs, list) and refs:
        shown = "; ".join(str(r) for r in refs[:6])
        extra = f" (+{len(refs) - 6} more)" if len(refs) > 6 else ""
        lines.append(f"- **Refs:** {shown}{extra}")

    forensic = _forensic_keys(c)
    if forensic:
        lines.append(f"- **Forensic keys ({len(forensic)}):**")
        for k in forensic:
            fl = _first_line(c[k])
            lines.append(f"  - `{k}`: {fl}" if fl else f"  - `{k}`: _(empty)_")
    return lines


# ---------- html ----------

CSS = """
:root {
  /* URA brand tokens — lifted from https://universalroom.org/style.css (OKLCH).
     Light "paper" + cool "ink" + brand blue `--accent` / warm secondary. */
  --bg:oklch(0.985 0.003 240); --fg:oklch(0.15 0.008 240); --muted:oklch(0.55 0.010 240);
  --card-bg:oklch(0.995 0.002 240); --border:oklch(0.88 0.008 240); --rule:oklch(0.80 0.010 240);
  --lane-bg:transparent; --accent:oklch(0.50 0.16 235); --accent-dim:oklch(0.66 0.12 235);
  --ok:oklch(0.55 0.13 150); --warn:oklch(0.60 0.13 50); --bad:oklch(0.55 0.17 25);
  --info:oklch(0.55 0.10 210);
  --stale:oklch(0.58 0.13 50); --stale-bg:oklch(0.93 0.05 65); --code-bg:oklch(0.965 0.005 240);
  --font-sans:'Hanken Grotesk', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif;
  --font-mono:'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    /* URA is light-only; this is a URA-consistent cool dark (deep slate + brand
       blue) for dark-OS viewers — NOT the old muddy default. */
    --bg:oklch(0.20 0.012 240); --fg:oklch(0.93 0.004 240); --muted:oklch(0.66 0.012 240);
    --card-bg:oklch(0.24 0.012 240); --border:oklch(0.33 0.012 240); --rule:oklch(0.42 0.012 240);
    --accent:oklch(0.72 0.13 235); --accent-dim:oklch(0.55 0.12 235);
    --ok:oklch(0.72 0.14 150); --warn:oklch(0.74 0.13 55); --bad:oklch(0.70 0.16 25);
    --info:oklch(0.72 0.10 210);
    --stale:oklch(0.74 0.13 55); --stale-bg:oklch(0.28 0.05 60); --code-bg:oklch(0.27 0.012 240);
  }
}
* { box-sizing:border-box; }
html,body { margin:0; padding:0; background:var(--bg); color:var(--fg);
  font:14px/1.55 var(--font-sans);
  font-variant-numeric: tabular-nums; -webkit-font-smoothing:antialiased; }
code, .mono, .id, .statusline, .lane h2, .count, .tagline, .kv dt {
  font-family: var(--font-mono); }

header.top { position:sticky; top:0; z-index:5; background:var(--bg);
  border-bottom:2px solid var(--rule); padding:14px 22px 10px; }
header.top h1 { margin:0; font-size:17px; letter-spacing:0.14em; text-transform:uppercase;
  font-family:var(--font-mono); }
header.top h1 .gen { color:var(--muted); font-size:10.5px; letter-spacing:0.08em; font-weight:400;
  display:block; margin-top:2px; text-transform:none; }
.statusline { margin-top:8px; font-size:11.5px; color:var(--muted);
  display:flex; flex-wrap:wrap; gap:2px 18px; }
.statusline b { color:var(--fg); font-weight:600; }
.statusline a { color:var(--accent); text-decoration:none; border-bottom:1px solid var(--accent-dim); }

.stale { background:var(--stale-bg); border:1px solid var(--stale);
  border-left:6px solid var(--stale); padding:12px 18px; margin:14px 22px 0;
  font-family:var(--font-mono); font-size:12.5px; }
.stale h2 { margin:0 0 6px; font-size:13px; letter-spacing:0.1em; text-transform:uppercase;
  color:var(--stale); }
.stale ul { margin:4px 0 0 18px; padding:0; }
.stale a { color:var(--accent); }

.summary { padding:10px 22px 2px; font-size:11.5px; color:var(--muted);
  display:flex; gap:0; flex-wrap:wrap;
  font-family:var(--font-mono); }
.summary span { padding:2px 10px; border-right:1px solid var(--border); }
.summary span:first-child { padding-left:0; }
.summary span:last-child { border-right:none; }
.summary b { color:var(--fg); }

/* BOARD-AUTONOMY-PROGRESS-1 — last-24h progress counter + recent-work feed */
.autonomy { margin:12px 22px 0; border:1px solid var(--border); border-left:6px solid var(--accent);
  background:var(--code-bg); }
.autonomy .hd { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; padding:12px 18px 6px; }
.autonomy .hd .lbl { font-family:var(--font-mono); font-size:11px; letter-spacing:0.14em;
  text-transform:uppercase; color:var(--muted); }
.autonomy .hd .metric { font-family:var(--font-mono); font-weight:700;
  font-size:34px; line-height:1; color:var(--accent); letter-spacing:0.02em; }
.autonomy .hd .metric .den { color:var(--muted); font-size:22px; }
.autonomy .hd .sub { font-size:11.5px; color:var(--muted); }
.autonomy details { border-top:1px dashed var(--border); }
.autonomy details > summary { cursor:pointer; list-style:none; padding:7px 18px; font-size:11.5px;
  font-family:var(--font-mono); letter-spacing:0.06em; color:var(--muted); }
.autonomy details > summary::-webkit-details-marker { display:none; }
.autonomy details > summary::marker { content:""; }
.autonomy .feed { margin:0; padding:0 18px 12px; list-style:none; }
.autonomy .feed li { display:flex; align-items:flex-start; gap:10px; padding:7px 0;
  border-top:1px solid var(--border); font-size:12.5px; }
.autonomy .feed li:first-child { border-top:none; }
.autonomy .feed .oc { font-family:var(--font-mono); font-size:9.5px; font-weight:700;
  letter-spacing:0.08em; text-transform:uppercase; padding:2px 7px; border:1px solid var(--border);
  white-space:nowrap; }
.autonomy .feed .oc.built { color:var(--ok); border-color:var(--ok); }
.autonomy .feed .oc.parked { color:var(--muted); }
.autonomy .feed .oc.waiting_operator { color:var(--info); border-color:var(--info); }
.autonomy .feed .oc.shipped, .autonomy .feed .oc.done { color:var(--accent); border-color:var(--accent); }
.autonomy .feed .fhd { flex:1; }
.autonomy .feed .ft { color:var(--muted); font-size:10.5px; font-family:var(--font-mono); }
.autonomy .feed button.ack { font-family:var(--font-mono); font-size:10px;
  letter-spacing:0.06em; padding:3px 9px; cursor:pointer; background:var(--code-bg); color:var(--fg);
  border:1px solid var(--border); white-space:nowrap; }
.autonomy .feed button.ack:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
.autonomy .feed button.ack:disabled { opacity:0.4; cursor:default; }
.autonomy .feed .empty { color:var(--muted); padding:8px 0; font-size:12px; }
/* acked state (pending apply, before the next groom culls it) */
.autonomy .feed li.acked { opacity:0.6; }
.autonomy .feed li.acked .fhd { text-decoration:line-through; text-decoration-color:var(--muted); }
.autonomy .feed .ackmark { font-family:var(--font-mono); font-size:10px;
  letter-spacing:0.06em; color:var(--ok); white-space:nowrap; border:1px solid var(--ok);
  padding:3px 9px; }
/* operator decision, queued from the feed (pending apply) */
.autonomy .feed .decision-chip { display:block; margin-top:4px; font-family:var(--font-mono);
  font-size:10.5px; color:var(--info); border-left:2px solid var(--info); padding-left:7px; }
.autonomy .feed li.decision-row { border-top:none; padding-top:0; }
.autonomy .feed .feed-instruct { flex:1; margin-top:0; }
.autonomy .feed .feed-instruct input { flex:1; font-family:var(--font-mono);
  font-size:11px; padding:4px 8px; background:var(--bg); color:var(--fg); border:1px solid var(--border); }
.autonomy .feed .feed-instruct input:focus { outline:none; border-color:var(--accent); }
.autonomy .feed .feed-instruct button { font-family:var(--font-mono); font-size:10.5px;
  padding:3px 10px; cursor:pointer; background:var(--code-bg); color:var(--fg); border:1px solid var(--border); }
.autonomy .feed .feed-instruct button:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
.autonomy .feed .feed-instruct button:disabled { opacity:0.4; cursor:default; }
/* waiting_operator free-form instruction box (WAITING-OP-INSTRUCTIONS-1) */
.instruct { margin-top:8px; display:flex; gap:6px; }
.instruct input { flex:1; font-family:var(--font-mono); font-size:11px;
  padding:4px 8px; background:var(--bg); color:var(--fg); border:1px solid var(--border); }
.instruct input:focus { outline:none; border-color:var(--accent); }
.instruct button { font-family:var(--font-mono); font-size:10.5px; letter-spacing:0.06em;
  padding:3px 10px; cursor:pointer; background:var(--code-bg); color:var(--fg); border:1px solid var(--border); }
.instruct button:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
.instruct button:disabled { opacity:0.4; cursor:default; }
.pending-chip.op-instruct { background:transparent; color:var(--info); border-color:var(--info); }
.pending-chip.op-ack { background:transparent; color:var(--ok); border-color:var(--ok); }

main.board { padding:6px 22px 30px; }
.lane { margin-top:18px; }
.lane > h2 { margin:0; font-size:12px; font-weight:600; letter-spacing:0.16em;
  text-transform:uppercase; color:var(--fg);
  border-bottom:1px solid var(--rule); padding-bottom:5px;
  display:flex; align-items:baseline; gap:10px; }
.lane > h2 .count { color:var(--accent); font-size:12px; }
.lane > h2 .hint { color:var(--muted); font-weight:400; font-size:10.5px;
  letter-spacing:0.03em; text-transform:none; margin-left:auto; }
.lane .cards { display:grid; grid-template-columns:repeat(auto-fill, minmax(320px,1fr));
  gap:10px; padding-top:10px; }
.lane .none { color:var(--muted); font-size:11px; padding:8px 0 0;
  font-family:var(--font-mono); }

.card { background:var(--card-bg); border:1px solid var(--border);
  border-left:3px solid var(--muted); padding:9px 12px 8px; }
.card.ap-explicit  { border-left-color:var(--ok); }
.card.ap-implied   { border-left-color:var(--info); }
.card.ap-unreviewed{ border-left-style:dashed; border-left-color:var(--muted); }
.card.ap-blocked   { border-left-color:var(--bad); }
.card summary { cursor:pointer; list-style:none; }
.card summary::-webkit-details-marker { display:none; }
.card summary::marker { content:""; }
.card .id { color:var(--accent); font-size:11px; letter-spacing:0.04em; }
.card .apl { float:right; font-size:9.5px; letter-spacing:0.1em; text-transform:uppercase;
  font-family:var(--font-mono); color:var(--muted); }
.card.ap-blocked .apl { color:var(--bad); }
.card.ap-unreviewed .apl { color:var(--warn); }
.card .title { font-weight:600; margin-top:2px; display:block; font-size:13.5px; line-height:1.35; }
.tagline { margin-top:5px; font-size:10.5px; color:var(--muted); letter-spacing:0.02em; }
.cardmeta { font-size:10px; color:var(--muted); margin:2px 0 6px; letter-spacing:0.02em; font-variant-numeric:tabular-nums; }
.tagline .sep { opacity:0.5; padding:0 4px; }

.card .body { margin-top:8px; border-top:1px solid var(--border); padding-top:7px; }
.kv { margin:0; }
.kv dt { color:var(--muted); font-size:10px; margin-top:7px; text-transform:uppercase;
  letter-spacing:0.1em; }
.kv dd { margin:2px 0 0; font-size:12.5px; word-break:break-word; }
.card ul.forensic { list-style:none; padding:0; margin:4px 0 0; }
.card ul.forensic li { margin:3px 0; font-size:11.5px; color:var(--muted); }
.card ul.forensic code { background:var(--code-bg); padding:1px 4px; font-size:10.5px; color:var(--fg); }
code { background:var(--code-bg); padding:1px 5px; font-size:0.92em; }

section.extras { margin:26px 22px 0; border-top:1px solid var(--rule); padding-top:12px; }
section.extras h2 { font-size:12px; letter-spacing:0.16em; text-transform:uppercase;
  font-family:var(--font-mono); }
footer { padding:26px 22px 40px; color:var(--muted); font-size:10.5px;
  font-family:var(--font-mono); }
/* --- operator disposition UI (KHOST-2) --- */
.actions { margin-top:8px; display:flex; gap:6px; flex-wrap:wrap; }
.actions button { font-family:var(--font-mono); font-size:10.5px;
  letter-spacing:0.06em; padding:3px 9px; cursor:pointer;
  background:var(--code-bg); color:var(--fg); border:1px solid var(--border); }
.actions button:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
.actions button:disabled { opacity:0.4; cursor:default; }
.pending-chip { display:inline-block; margin-top:6px; margin-right:6px;
  font-family:var(--font-mono); font-size:10px; letter-spacing:0.08em;
  text-transform:uppercase; padding:2px 8px; font-weight:600;
  background:var(--stale-bg); color:var(--stale); border:1px solid var(--stale); }
.pending-chip.op-done     { background:transparent; color:var(--ok); border-color:var(--ok); }
.pending-chip.op-declined { background:transparent; color:var(--bad); border-color:var(--bad); }
.pending-chip.op-move     { background:transparent; color:var(--info); border-color:var(--info); }
.pending-chip.op-approve  { background:transparent; color:var(--ok); border-color:var(--ok); }
.pending-chip.op-investigate { background:transparent; color:var(--info); border-color:var(--info); }
.card[draggable="true"] { cursor:grab; }
.card.dragging { opacity:0.5; }
.lane.drop-ok { outline:2px dashed var(--accent); outline-offset:4px; }
#toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%);
  background:var(--fg); color:var(--bg); padding:8px 16px; font-size:12px;
  font-family:var(--font-mono); z-index:20; display:none; }
@media (max-width:720px) {
  main.board, .summary, header.top { padding-left:12px; padding-right:12px; }
  .stale { margin:10px 12px 0; }
  .lane .cards { grid-template-columns:1fr; }
  .card .apl { float:none; display:block; margin-top:2px; }
}
"""


BOARD_JS = """
(function () {
  'use strict';
  var toastEl = document.getElementById('toast');
  var toastTimer = null;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.style.display = 'block';
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.style.display = 'none'; }, 3200);
  }
  function post(cardId, action, extra) {
    var body = { card_id: cardId, action: action, at: new Date().toISOString() };
    if (extra) { for (var k in extra) { if (extra.hasOwnProperty(k)) body[k] = extra[k]; } }
    return fetch('api/disposition', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r;
    });
  }
  function addChip(card, action) {
    var chip = document.createElement('span');
    var cls = action.indexOf('move:') === 0 ? 'op-move' : 'op-' + action;
    chip.className = 'pending-chip ' + cls;
    chip.textContent = 'pending: ' + action;
    var summary = card.querySelector('summary');
    var title = summary.querySelector('.title');
    summary.insertBefore(chip, title);
  }
  function readOnlyToast() { toast('board is read-only here'); }

  // Disposition buttons
  document.querySelectorAll('.card .actions button').forEach(function (btn) {
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      var card = btn.closest('.card');
      var action = btn.getAttribute('data-action');
      var buttons = card.querySelectorAll('.actions button');
      buttons.forEach(function (b) { b.disabled = true; });
      post(card.getAttribute('data-id'), action).then(function () {
        addChip(card, action);
      }).catch(function () {
        buttons.forEach(function (b) { b.disabled = false; });
        readOnlyToast();
      });
    });
  });

  // WAITING-OP-INSTRUCTIONS-1 — free-form instruction send
  document.querySelectorAll('.card .instruct').forEach(function (box) {
    var input = box.querySelector('input');
    var btn = box.querySelector('button[data-action="instruct"]');
    if (!input || !btn) return;
    function send() {
      var text = (input.value || '').trim();
      if (!text) { input.focus(); return; }
      var card = btn.closest('.card');
      btn.disabled = true; input.disabled = true;
      post(card.getAttribute('data-id'), 'instruct', { text: text }).then(function () {
        addChip(card, 'instruct');
        input.value = '';
        toast('instruction queued');
      }).catch(function () {
        btn.disabled = false; input.disabled = false;
        readOnlyToast();
      });
    }
    btn.addEventListener('click', function (ev) { ev.preventDefault(); ev.stopPropagation(); send(); });
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); send(); }
    });
    // keep clicks inside the box from toggling the <details> card
    box.addEventListener('click', function (ev) { ev.stopPropagation(); });
  });

  // BOARD-AUTONOMY-PROGRESS-1 — acknowledge / decide on recent-work feed entries.
  // The board is served as a CACHED STATIC file (re-rendered every ~5min by the
  // refresh cron), so a click's state must survive a reload BEFORE the next
  // render. Two layers: (1) the server render already paints the acked/decided
  // state by reading the pending queue (durable); (2) a localStorage echo
  // re-applies it instantly on reload in the gap before that render lands.
  var LS_ACK = 'ura_kanban_acked';      // {fid: true}
  var LS_DEC = 'ura_kanban_decided';    // {card_id: text}
  function lsGet(k) { try { return JSON.parse(localStorage.getItem(k) || '{}'); } catch (e) { return {}; } }
  function lsSet(k, o) { try { localStorage.setItem(k, JSON.stringify(o)); } catch (e) {} }

  function markAcked(li) {
    if (!li || li.classList.contains('acked')) return;
    li.classList.add('acked');
    var btn = li.querySelector('button.ack');
    if (btn) {
      var mark = document.createElement('span');
      mark.className = 'ackmark';
      mark.textContent = '✓ acked — pending apply';
      btn.replaceWith(mark);
    }
  }
  function markDecided(cardId, text) {
    document.querySelectorAll('.autonomy .feed li[data-card="' + (window.CSS && CSS.escape ? CSS.escape(cardId) : cardId) + '"]').forEach(function (li) {
      if (li.classList.contains('decision-row')) return;  // the input row itself
      if (li.querySelector('.decision-chip')) return;
      var chip = document.createElement('span');
      chip.className = 'decision-chip';
      chip.textContent = 'decision queued: "' + text + '" — pending apply';
      var fhd = li.querySelector('.fhd');
      if (fhd) fhd.appendChild(chip);
    });
  }

  document.querySelectorAll('.autonomy .feed button.ack').forEach(function (btn) {
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      var fid = btn.getAttribute('data-fid');
      var li = btn.closest('li');
      btn.disabled = true;
      post(fid, 'ack').then(function () {
        markAcked(li);                       // mark in place — do NOT remove
        var a = lsGet(LS_ACK); a[fid] = true; lsSet(LS_ACK, a);
        toast('acknowledged — culled at next groom');
      }).catch(function () {
        btn.disabled = false;
        readOnlyToast();
      });
    });
  });

  // Inline DECISION box on waiting_operator feed rows (action=instruct on the card).
  document.querySelectorAll('.autonomy .feed .feed-instruct').forEach(function (box) {
    var input = box.querySelector('input');
    var btn = box.querySelector('button[data-action="instruct"]');
    var row = box.closest('li');
    if (!input || !btn || !row) return;
    var cardId = row.getAttribute('data-card');
    function send() {
      var text = (input.value || '').trim();
      if (!text) { input.focus(); return; }
      btn.disabled = true; input.disabled = true;
      post(cardId, 'instruct', { text: text }).then(function () {
        markDecided(cardId, text);
        var d = lsGet(LS_DEC); d[cardId] = text; lsSet(LS_DEC, d);
        input.value = '';
        toast('decision queued — applied at next groom');
      }).catch(function () {
        btn.disabled = false; input.disabled = false;
        readOnlyToast();
      });
    }
    btn.addEventListener('click', function (ev) { ev.preventDefault(); send(); });
    input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); send(); } });
  });

  // On-load shim: re-apply acked/decided state from localStorage, so a reload
  // in the gap before the next static re-render still shows the operator's action.
  (function () {
    var a = lsGet(LS_ACK);
    Object.keys(a).forEach(function (fid) {
      document.querySelectorAll('.autonomy .feed li[data-fid="' + (window.CSS && CSS.escape ? CSS.escape(fid) : fid) + '"]').forEach(markAcked);
    });
    var d = lsGet(LS_DEC);
    Object.keys(d).forEach(function (cardId) { markDecided(cardId, d[cardId]); });
    // Prune localStorage entries the server has since culled (feed row gone).
    var liveFids = {}, liveCards = {};
    document.querySelectorAll('.autonomy .feed li[data-fid]').forEach(function (li) { liveFids[li.getAttribute('data-fid')] = 1; });
    document.querySelectorAll('.autonomy .feed li[data-card]').forEach(function (li) { liveCards[li.getAttribute('data-card')] = 1; });
    var a2 = {}; Object.keys(a).forEach(function (f) { if (liveFids[f]) a2[f] = true; }); lsSet(LS_ACK, a2);
    var d2 = {}; Object.keys(d).forEach(function (c) { if (liveCards[c]) d2[c] = d[c]; }); lsSet(LS_DEC, d2);
  })();

  // Drag between columns
  var draggingCard = null;
  document.querySelectorAll('.card[draggable="true"]').forEach(function (card) {
    card.addEventListener('dragstart', function (ev) {
      draggingCard = card;
      card.classList.add('dragging');
      ev.dataTransfer.setData('text/plain', card.getAttribute('data-id'));
      ev.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', function () {
      card.classList.remove('dragging');
      document.querySelectorAll('.lane.drop-ok').forEach(function (l) { l.classList.remove('drop-ok'); });
      draggingCard = null;
    });
  });
  document.querySelectorAll('section.lane[data-col]').forEach(function (lane) {
    var col = lane.getAttribute('data-col');
    if (col === 'other') return;
    lane.addEventListener('dragover', function (ev) {
      if (!draggingCard) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'move';
      lane.classList.add('drop-ok');
    });
    lane.addEventListener('dragleave', function () { lane.classList.remove('drop-ok'); });
    lane.addEventListener('drop', function (ev) {
      ev.preventDefault();
      lane.classList.remove('drop-ok');
      if (!draggingCard) return;
      var card = draggingCard;
      var fromLane = card.closest('section.lane');
      if (fromLane === lane) return;
      var fromParent = card.parentElement;
      var fromNext = card.nextElementSibling;
      var cardsDiv = lane.querySelector('.cards');
      if (!cardsDiv) {
        cardsDiv = document.createElement('div');
        cardsDiv.className = 'cards';
        var none = lane.querySelector('.none');
        if (none) none.remove();
        lane.appendChild(cardsDiv);
      }
      cardsDiv.appendChild(card);  // optimistic move
      var action = 'move:' + col;
      post(card.getAttribute('data-id'), action).then(function () {
        addChip(card, action);
      }).catch(function () {
        fromParent.insertBefore(card, fromNext);  // revert
        readOnlyToast();
      });
    });
  });
})();
"""


def _h(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _badge(text: str, cls: str = "", color: str | None = None) -> str:
    style = f' style="background:{color}"' if color else ""
    return f'<span class="badge {cls}"{style}>{_h(text)}</span>'


def render_html(data: dict, meta_extras: dict) -> str:
    meta = data.get("meta", {}) or {}
    cards = list(data.get("cards", []) or [])
    parked_extra = data.get("parked", []) or []
    backlog_refs = data.get("broader_backlog_refs", []) or []
    buckets = group_cards(cards)

    parts: list[str] = []
    parts.append('<!doctype html><html lang="en"><head>')
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append('<meta name="generator" content="kanban_render.py (URA)">')
    parts.append('<title>URA Kanban</title>')
    parts.append('<meta name="theme-color" content="#fafaf8">')
    parts.append(f'<link rel="icon" type="image/png" href="{URA_FAVICON}">')
    # URA brand fonts (same two the site loads): Hanken Grotesk + JetBrains Mono.
    # System fallbacks in the stacks keep it legible if Google Fonts is blocked.
    parts.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
    parts.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    parts.append('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
                 'family=Hanken+Grotesk:ital,wght@0,300..800;1,300..700&'
                 'family=JetBrains+Mono:wght@400;500&display=swap">')
    parts.append(f'<style>{CSS}</style>')
    parts.append('</head><body>')

    parts.append('<header class="top">')
    parts.append('<h1>URA://KANBAN'
                 '<span class="gen">GENERATED - do not hand-edit; source is kanban.data.yaml</span></h1>')
    parts.append('<div class="statusline">')
    parts.append(f'<span>generated <b>{_h(meta_extras["gen_ts"])}</b></span>')
    parts.append(f'<span>data <b>{_h(meta_extras["data_hash"][:12])}</b></span>')
    parts.append(f'<span>reconciled <b>{_h(meta.get("last_reconciled", "?"))}</b></span>')
    if meta.get("target_host"):
        parts.append(f'<span><a href="https://{_h(meta["target_host"])}">{_h(meta["target_host"])}</a></span>')
    if meta.get("artifact_url"):
        parts.append(f'<span><a href="{_h(meta["artifact_url"])}">artifact</a></span>')
    parts.append('</div></header>')

    if meta_extras["is_stale"]:
        parts.append('<div class="stale"><h2>▲ STALE - board has not been reconciled against newer work</h2><ul>')
        for r in meta_extras["stale_reasons"]:
            parts.append(f'<li>{_h(r)}</li>')
        parts.append('</ul><div style="margin-top:6px">Reconcile <code>meta.last_reconciled</code> '
                     'and move shipped cards before picking next work.</div></div>')

    # BOARD-AUTONOMY-PROGRESS-1 — last-24h progress counter + recent-work feed.
    stats = autonomy_stats(data)
    parts.append('<section class="autonomy">')
    parts.append('<div class="hd">')
    parts.append('<span class="lbl">Board progress · last 24h</span>')
    parts.append(f'<span class="metric">{stats["num"]}<span class="den"> / {stats["denom"]}</span></span>')
    parts.append('<span class="sub">cards concluded autonomously in the last 24h · '
                 'denominator = open cards (all minus done), shrinks as work completes</span>')
    parts.append('</div>')
    live = stats["live"]
    pending = meta_extras.get("pending", {}) or {}
    if live:
        parts.append(f'<details open><summary>recent autonomous work — {len(live)} '
                     'unacknowledged (acknowledge to retire; auto-archived after 7 days)</summary>')
        parts.append('<ul class="feed">')
        for e in live:
            oc = str(e.get("outcome", "")).strip() or "done"
            fid = str(e.get("fid", ""))
            card_id = fid.split("@", 1)[0] if "@" in fid else fid
            # Pending-queue overlay (the durable acked/decided state between an
            # operator click and the next groom — survives reload because the
            # render reads the queue). ack keys on the feed fid; instruct
            # (decision) keys on the underlying card id.
            acked = any(d.get("action") == "ack" for d in pending.get(fid, []))
            decisions = [d.get("text", "") for d in pending.get(card_id, [])
                         if d.get("action") == "instruct" and d.get("text")]
            li_cls = "acked" if acked else ""
            parts.append(f'<li class="{li_cls}" data-fid="{_h(fid)}" data-card="{_h(card_id)}">')
            parts.append(f'<span class="oc {_h(oc)}">{_h(oc)}</span>')
            parts.append('<span class="fhd">' + _h(str(e.get("headline", "")))
                         + f'<br><span class="ft">{_h(str(e.get("at", "")))}</span>')
            if decisions:
                parts.append(f'<span class="decision-chip">decision queued: '
                             f'"{_h(decisions[-1])}" — pending apply</span>')
            parts.append('</span>')
            # action column: acked-state vs ack button
            if acked:
                parts.append('<span class="ackmark">✓ acked — pending apply</span>')
            else:
                parts.append(f'<button type="button" class="ack" data-fid="{_h(fid)}">✓ ack</button>')
            parts.append('</li>')
            # waiting_operator feed entries get an inline DECISION box too, so the
            # operator can decide straight from the progress digest (not just on
            # the card in its lane). Posts action=instruct against the CARD id.
            if oc == "waiting_operator":
                parts.append(f'<li class="decision-row" data-card="{_h(card_id)}">'
                             '<span class="oc"></span>'
                             '<div class="instruct feed-instruct">'
                             f'<input type="text" placeholder="decision for {_h(card_id)}…" '
                             'aria-label="operator decision">'
                             '<button type="button" data-action="instruct">send</button>'
                             '</div></li>')
        parts.append('</ul></details>')
    parts.append('</section>')

    parts.append('<div class="summary">')
    for key, emoji, label, _ in COLUMN_META:
        n = len(buckets.get(key, []))
        if n == 0 and key == "other":
            continue
        parts.append(f'<span>{_h(label)} <b>{n}</b></span>')
    parts.append('</div>')

    parts.append('<main class="board">')
    for key, emoji, label, hint in COLUMN_META:
        cards_here = buckets.get(key, [])
        if not cards_here and key == "other":
            continue
        parts.append(f'<section class="lane" data-col="{_h(key)}">')
        parts.append(f'<h2>{_h(label)} <span class="count">{len(cards_here)}</span>'
                     f'<span class="hint">{_h(hint)}</span></h2>')
        if not cards_here:
            parts.append('<div class="none">(none)</div>')
        else:
            parts.append('<div class="cards">')
            for c in cards_here:
                parts.append(_render_card_html(c, meta_extras.get("pending", {})))
            parts.append('</div>')
        parts.append('</section>')
    parts.append('</main>')

    if parked_extra or backlog_refs:
        parts.append('<section class="extras">')
        if parked_extra:
            parts.append(f'<h2>\U0001F17F️ Parked ideas <span class="count">{len(parked_extra)}</span></h2>')
            parts.append('<ul>')
            for item in parked_extra:
                if isinstance(item, dict):
                    title = item.get("title", "?")
                    trig = item.get("revisit_if") or item.get("status") or ""
                    parts.append(f"<li><strong>{_h(title)}</strong> - {_h(trig)}</li>")
                else:
                    parts.append(f"<li>{_h(item)}</li>")
            parts.append('</ul>')
        if backlog_refs:
            parts.append('<h2>Broader backlog references</h2><ul>')
            for item in backlog_refs:
                parts.append(f'<li>{_h(item)}</li>')
            parts.append('</ul>')
        parts.append('</section>')

    parts.append(f'<footer>Generated by <code>scripts/kanban_render.py</code> from '
                 f'<code>docs/planning/kanban.data.yaml</code> @ '
                 f'<code>{_h(meta_extras["data_hash"][:12])}</code>. '
                 'Regenerate on every commit that touches the data.</footer>')
    parts.append('<div id="toast"></div>')
    parts.append(f'<script>{BOARD_JS}</script>')
    parts.append('</body></html>')
    return "\n".join(parts) + "\n"


def _render_card_html(c: dict, pending: dict[str, list[dict]] | None = None) -> str:
    cid = str(c.get("id", "?"))
    title = str(c.get("title", ""))
    thread = str(c.get("thread", ""))
    approval = str(c.get("approval", ""))
    status = str(c.get("status", ""))

    origin = c.get("origin", {}) or {}
    origin_line = ""
    if isinstance(origin, dict):
        od = origin.get("date", "")
        og = origin.get("gist", "")
        origin_line = f"{od} - {og}".strip(" -")
    why = _first_line(c.get("why", ""))
    nxt = _first_line(c.get("next", ""))

    ap_class = f" ap-{approval}" if approval in ("explicit", "implied", "unreviewed", "blocked") else ""
    out = [f'<details class="card{ap_class}" data-id="{_h(cid)}" draggable="true"><summary>']
    out.append(f'<span class="id">{_h(cid)}</span>')
    _badge_txt = _wsjf_badge_text(c)
    if _badge_txt:
        out.append(f'<span class="wsjf" style="font-size:11px;font-weight:600;color:#c65;'
                   f'background:#c651;border-radius:4px;padding:0 5px;margin-left:4px">'
                   f'{_h(_badge_txt)}</span>')
    for disp in (pending or {}).get(cid, []):
        act = disp["action"]
        chip_cls = "op-move" if act.startswith("move:") else f"op-{act}"
        txt = disp.get("text")
        suffix = f': "{_h(txt)}"' if txt else ""
        out.append(f'<span class="pending-chip {_h(chip_cls)}" title="at {_h(disp["at"])}">'
                   f'OPERATOR: {_h(act)}{suffix} — pending apply</span>')
    if approval and approval != "implied":
        out.append(f'<span class="apl">{_h(approval)}</span>')
    out.append(f'<span class="title">{_h(title)}</span>')
    tagbits = []
    if thread:
        tagbits.append(_h(thread))
    tags = c.get("tags") or []
    if isinstance(tags, list):
        tagbits.extend(_h(str(t)) for t in tags[:5])
        if len(tags) > 5:
            tagbits.append(f"+{len(tags)-5}")
    if tagbits:
        out.append('<div class="tagline">' + '<span class="sep">·</span>'.join(tagbits) + '</div>')
    out.append('</summary>')

    out.append('<div class="body"><dl class="kv">')

    # created / updated / refinement status meta line
    created = str(c.get("created", "") or "")
    updated = str(c.get("updated", "") or "")
    ref_status = str(c.get("refinement_status", "") or "")
    n_refine = len(c.get("refinement") or []) if isinstance(c.get("refinement"), list) else 0
    meta_bits = []
    if created: meta_bits.append(f"created {_h(created)}")
    if updated and updated != created: meta_bits.append(f"updated {_h(updated)}")
    if ref_status:
        rlabel = ref_status
        if ref_status == "refined" and n_refine:
            rlabel = f"refined ×{n_refine}"
        meta_bits.append(_h(rlabel))
    elif n_refine:
        meta_bits.append(f"refined ×{n_refine}")
    if meta_bits:
        out.append(f'<div class="cardmeta">{" · ".join(meta_bits)}</div>')

    # Problem / Solution — the plain-language core, rendered first and prominent.
    ps = c.get("problem_solution")
    if isinstance(ps, str) and ps.strip():
        ps = [ps]
    if isinstance(ps, list) and ps:
        joined = "<br>".join(_h(_first_line(item)) for item in ps)
        out.append(f'<dt>Problem / Solution</dt><dd>{joined}</dd>')

    if origin_line:
        out.append(f'<dt>Origin</dt><dd>{_h(_first_line(origin_line))}</dd>')
    if why:
        out.append(f'<dt>Why</dt><dd>{_h(why)}</dd>')
    if nxt:
        out.append(f'<dt>Next</dt><dd>{_h(nxt)}</dd>')

    for label, key in (("Depends on", "depends_on"), ("Blocks", "blocks"), ("Sibling of", "sibling_of")):
        v = c.get(key)
        if isinstance(v, list) and v:
            out.append(f"<dt>{_h(label)}</dt><dd>{_h(', '.join(str(x) for x in v))}</dd>")
    pars = c.get("parsimony") or {}
    if isinstance(pars, dict) and pars:
        verdict = pars.get("verdict", "")
        problem = _first_line(pars.get("problem", ""))
        if verdict or problem:
            out.append(f"<dt>Parsimony</dt><dd>[{_h(verdict)}] {_h(problem)}</dd>")
    refs = c.get("refs") or []
    if isinstance(refs, list) and refs:
        shown = "; ".join(str(r) for r in refs[:6])
        extra = f" (+{len(refs) - 6} more)" if len(refs) > 6 else ""
        out.append(f"<dt>Refs</dt><dd>{_h(shown + extra)}</dd>")

    forensic = _forensic_keys(c)
    if forensic:
        out.append(f'<dt>Forensic ({len(forensic)})</dt><dd><ul class="forensic">')
        for k in forensic:
            fl = _first_line(c[k])
            body = _h(fl) if fl else '<em>(empty)</em>'
            out.append(f'<li><code>{_h(k)}</code>: {body}</li>')
        out.append('</ul></dd>')

    out.append('</dl>')
    # Inbox + pre-planning cards get two extra out-of-band buttons:
    # approve (operator grants explicit approval without a chat turn)
    # and investigate (flags the card for the bounded lull sweep).
    extra = ''
    if str(c.get("status", "")) in ("inbox", "investigating", "pre_planning"):
        extra = ('<button type="button" data-action="approve">▶ approve</button>'
                 '<button type="button" data-action="investigate">🔍 investigate</button>')
    out.append('<div class="actions">'
               '<button type="button" data-action="done">✓ done</button>'
               '<button type="button" data-action="deferred">⏸ deferred</button>'
               '<button type="button" data-action="declined">✕ declined</button>'
               + extra +
               '</div>')
    # WAITING-OP-INSTRUCTIONS-1: free-form instruction channel on the operator
    # decision queue — the operator types HOW to resolve; the agent applies it
    # (action=instruct, with text) at session start.
    if str(c.get("status", "")) == "waiting_operator":
        out.append('<div class="instruct">'
                   '<input type="text" placeholder="instruction for the agent…" '
                   'aria-label="operator instruction">'
                   '<button type="button" data-action="instruct">send</button>'
                   '</div>')
    out.append('</div></details>')
    return "".join(out)


# ---------- driver ----------

def build_meta_extras(data_path: Path) -> dict:
    return {
        "data_hash": _git_hash(data_path),
        "gen_ts": _git_commit_iso(data_path),
    }


def render_all(data_path: Path, pending_path: Path | None = None) -> tuple[str, str, bool, list[str]]:
    """Return (markdown_text, html_text, is_stale, stale_reasons)."""
    with open(data_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    meta = data.get("meta", {}) or {}
    tag = _newest_tag_date()
    readme = _newest_readme()
    is_stale, reasons = compute_staleness(meta, tag, readme)
    extras = build_meta_extras(data_path)
    extras["is_stale"] = is_stale
    extras["stale_reasons"] = reasons
    extras["pending"] = load_pending_dispositions(pending_path or DEFAULT_PENDING)
    md = render_markdown(data, extras)
    ht = render_html(data, extras)
    return md, ht, is_stale, reasons


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--pending", type=Path, default=DEFAULT_PENDING,
                    help="operator dispositions pending-apply jsonl (missing file = none)")
    ap.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    ap.add_argument("--html-out", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--check", action="store_true", help="do not write; exit 0/2 based on staleness")
    ap.add_argument("--stdout", choices=("md", "html"), help="print to stdout instead of writing")
    args = ap.parse_args(argv)

    try:
        md, ht, stale, reasons = render_all(args.data, args.pending)
    except FileNotFoundError as exc:
        print(f"[kanban_render] ERROR: {exc}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"[kanban_render] ERROR: YAML parse failure: {exc}", file=sys.stderr)
        return 1

    if args.stdout == "md":
        sys.stdout.write(md)
    elif args.stdout == "html":
        sys.stdout.write(ht)
    elif not args.check:
        args.md_out.write_text(md, encoding="utf-8")
        args.html_out.write_text(ht, encoding="utf-8")
        print(f"[kanban_render] wrote {args.md_out} ({len(md)} bytes) "
              f"and {args.html_out} ({len(ht)} bytes)", file=sys.stderr)

    # Forcing function (2026-08-14): under --check, unapplied operator
    # dispositions FAIL with a distinct exit code (3), so the session-start
    # `--check` cannot pass while a board-button disposition sits unapplied.
    # A chip in the rendered view is a banner, not a mechanism — the operator
    # ruled banners insufficient; the non-zero exit is the mechanism. Scoped
    # to --check ONLY: a plain render (the homelab site deploy) still writes
    # the views (with pending chips) and does not break on the queue — so the
    # operator's live board keeps showing the pending state while MY
    # session-start gate hard-fails. Takes precedence over staleness so the
    # actionable item (apply the queue) is surfaced first.
    if args.check:
        pending = load_pending_dispositions(args.pending)
        if pending:
            n = sum(len(v) for v in pending.values())
            print(f"[kanban_render] UNAPPLIED OPERATOR DISPOSITIONS ({n}) — apply "
                  f"the queue per ura-kanban Cadence step 1, then delete "
                  f"{args.pending.name}:", file=sys.stderr)
            for cid, disps in pending.items():
                for d in disps:
                    print(f"  - {cid}: {d.get('action')} (at {d.get('at')})",
                          file=sys.stderr)
            return 3

    if stale:
        print("[kanban_render] STALE:", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
