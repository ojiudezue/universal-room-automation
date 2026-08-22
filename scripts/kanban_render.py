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

# Column display order + labels + emoji. Anything not in this map falls into "other".
COLUMN_META: list[tuple[str, str, str, str]] = [
    ("inbox",            "\U0001F4E5", "Inbox",              "raw capture"),
    ("investigating",    "\U0001F52C", "Investigating",      "measuring; truth not yet known"),
    ("pre_planning",     "\U0001F9ED", "Pre-planning",       "idea being decomposed"),
    ("planned",          "\U0001F4DD", "Planned",            "has plan / acceptance"),
    ("in_progress",      "\U0001F528", "In progress",        "being built"),
    ("review",           "\U0001F50D", "Review",             "under review"),
    ("shipped_organic",  "\U0001F680", "Shipped (organic open)", "live, awaiting proof"),
    ("waiting_operator", "⏸️", "Waiting on operator", "needs a human call"),
    ("waiting_me",       "⏳", "Waiting on me (Claude)", "I owe something"),
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
        out.setdefault(cid, []).append(
            {"action": str(d.get("action", "?")), "at": str(d.get("at", ""))}
        )
    return out


# ---------- card classification ----------

def _column_for(status: str) -> str:
    known = {k for k, *_ in COLUMN_META}
    return status if status in known else "other"


def group_cards(cards: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {k: [] for k, *_ in COLUMN_META}
    for c in cards:
        buckets[_column_for(str(c.get("status", "")))].append(c)
    return buckets


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
    lines.append(f"### `{cid}` - {_md_escape(title)}")
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
  --bg:#f4f1ea; --fg:#232019; --muted:#7a7263; --card-bg:#fbf9f4;
  --border:#ddd6c8; --rule:#c9c0ae;
  --lane-bg:transparent; --accent:#9a6108; --accent-dim:#b98a3a;
  --ok:#3f7d47; --warn:#a2541f; --bad:#a03030; --info:#3d6b80;
  --stale:#8a5a00; --stale-bg:#f3e3bd; --code-bg:#ece7db;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#131518; --fg:#d6d3c9; --muted:#7d8494; --card-bg:#1a1d22;
    --border:#2a2e36; --rule:#3a3f49;
    --accent:#ffb454; --accent-dim:#b98a3a;
    --ok:#7fbf7a; --warn:#e0954f; --bad:#e07070; --info:#7ab3cc;
    --stale:#ffb454; --stale-bg:#2b2210; --code-bg:#22252c;
  }
}
* { box-sizing:border-box; }
html,body { margin:0; padding:0; background:var(--bg); color:var(--fg);
  font:14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-variant-numeric: tabular-nums; }
code, .mono, .id, .statusline, .lane h2, .count, .tagline, .kv dt {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

header.top { position:sticky; top:0; z-index:5; background:var(--bg);
  border-bottom:2px solid var(--rule); padding:14px 22px 10px; }
header.top h1 { margin:0; font-size:17px; letter-spacing:0.14em; text-transform:uppercase;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
header.top h1 .gen { color:var(--muted); font-size:10.5px; letter-spacing:0.08em; font-weight:400;
  display:block; margin-top:2px; text-transform:none; }
.statusline { margin-top:8px; font-size:11.5px; color:var(--muted);
  display:flex; flex-wrap:wrap; gap:2px 18px; }
.statusline b { color:var(--fg); font-weight:600; }
.statusline a { color:var(--accent); text-decoration:none; border-bottom:1px solid var(--accent-dim); }

.stale { background:var(--stale-bg); border:1px solid var(--stale);
  border-left:6px solid var(--stale); padding:12px 18px; margin:14px 22px 0;
  font-family: ui-monospace, Menlo, monospace; font-size:12.5px; }
.stale h2 { margin:0 0 6px; font-size:13px; letter-spacing:0.1em; text-transform:uppercase;
  color:var(--stale); }
.stale ul { margin:4px 0 0 18px; padding:0; }
.stale a { color:var(--accent); }

.summary { padding:10px 22px 2px; font-size:11.5px; color:var(--muted);
  display:flex; gap:0; flex-wrap:wrap;
  font-family: ui-monospace, Menlo, monospace; }
.summary span { padding:2px 10px; border-right:1px solid var(--border); }
.summary span:first-child { padding-left:0; }
.summary span:last-child { border-right:none; }
.summary b { color:var(--fg); }

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
  font-family:ui-monospace, Menlo, monospace; }

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
  font-family:ui-monospace, Menlo, monospace; color:var(--muted); }
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
  font-family:ui-monospace, Menlo, monospace; }
footer { padding:26px 22px 40px; color:var(--muted); font-size:10.5px;
  font-family:ui-monospace, Menlo, monospace; }
/* --- operator disposition UI (KHOST-2) --- */
.actions { margin-top:8px; display:flex; gap:6px; flex-wrap:wrap; }
.actions button { font-family:ui-monospace, Menlo, monospace; font-size:10.5px;
  letter-spacing:0.06em; padding:3px 9px; cursor:pointer;
  background:var(--code-bg); color:var(--fg); border:1px solid var(--border); }
.actions button:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
.actions button:disabled { opacity:0.4; cursor:default; }
.pending-chip { display:inline-block; margin-top:6px; margin-right:6px;
  font-family:ui-monospace, Menlo, monospace; font-size:10px; letter-spacing:0.08em;
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
  font-family:ui-monospace, Menlo, monospace; z-index:20; display:none; }
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
  function post(cardId, action) {
    return fetch('api/disposition', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ card_id: cardId, action: action, at: new Date().toISOString() })
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
    for disp in (pending or {}).get(cid, []):
        act = disp["action"]
        chip_cls = "op-move" if act.startswith("move:") else f"op-{act}"
        out.append(f'<span class="pending-chip {_h(chip_cls)}" title="at {_h(disp["at"])}">'
                   f'OPERATOR: {_h(act)} — pending apply</span>')
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
