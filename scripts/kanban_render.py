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
README_DIR = REPO_ROOT / "docs" / "readmes"

# Column display order + labels + emoji. Anything not in this map falls into "other".
COLUMN_META: list[tuple[str, str, str, str]] = [
    ("inbox",            "\U0001F4E5", "Inbox",              "raw capture"),
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
    "tags", "origin", "why", "next", "refs",
    "parsimony", "constraints", "parked_alts", "refinement",
    "knobs", "depends_on", "blocks", "sibling_of",
    "batch", "seq",
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
            out.extend(_render_card_md(c))
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


def _render_card_md(c: dict) -> list[str]:
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
    tag_bits = []
    if thread:  tag_bits.append(f"thread: **{thread}**")
    if status:  tag_bits.append(f"status: **{status}**")
    if approval: tag_bits.append(f"approval: **{approval}**")
    if tag_bits:
        lines.append(" - ".join(tag_bits))
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
  --bg: #f7f7f8; --fg: #1b1e22; --muted:#5f6672; --card-bg:#fff;
  --border:#e4e6ea; --shadow: 0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04);
  --col-bg:#eef0f4; --accent:#28a; --stale:#f6c500; --stale-bg:#fff8d4;
  --hdr-bg:#fff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#0f1216; --fg:#e8ecf2; --muted:#93a0b2; --card-bg:#161a20;
    --border:#262b33; --shadow: 0 1px 2px rgba(0,0,0,0.5), 0 4px 12px rgba(0,0,0,0.4);
    --col-bg:#1a1f27; --accent:#5aa5ff; --stale:#f6c500; --stale-bg:#3a3010;
    --hdr-bg:#151920;
  }
}
* { box-sizing: border-box; }
html, body { margin:0; padding:0; background:var(--bg); color:var(--fg);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
header.top { position:sticky; top:0; z-index:5; background:var(--hdr-bg); border-bottom:1px solid var(--border);
  padding:12px 20px; box-shadow:var(--shadow); }
header.top h1 { margin:0; font-size:18px; }
header.top .meta { color:var(--muted); font-size:12px; margin-top:4px; word-break:break-word; }
header.top .meta code { background:var(--col-bg); padding:1px 5px; border-radius:3px; }
header.top .meta a, .stale a { color: var(--accent); text-decoration: underline; }
.stale {
  background: var(--stale-bg); border-left:4px solid var(--stale); padding:12px 16px; margin:12px 20px;
  border-radius:6px; font-size:13px; color:var(--fg);
}
.stale h2 { margin:0 0 6px; font-size:15px; }
.stale ul { margin:6px 0 0 20px; padding:0; }
.summary { padding: 10px 20px; color:var(--muted); font-size:12px; display:flex; gap:8px; flex-wrap:wrap; }
.summary span { background:var(--col-bg); padding:3px 8px; border-radius:12px; }
.board { display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap:12px; padding:14px 20px 40px; align-items:start; }
@media (max-width: 720px) {
  .board { grid-template-columns: 1fr; padding:10px; }
  header.top { padding:10px 12px; }
  .stale { margin:10px 12px; }
}
.col { background:var(--col-bg); border-radius:8px; padding:10px; min-height:60px; }
.col h2 { margin:0 0 8px; font-size:14px; font-weight:600; display:flex; align-items:baseline; gap:6px;}
.col h2 .count { color:var(--muted); font-weight:400; font-size:12px; }
.col .hint { color:var(--muted); font-size:11px; margin-bottom:8px; }
.card { background:var(--card-bg); border:1px solid var(--border); border-radius:6px;
  padding:10px 12px; margin-bottom:8px; box-shadow:var(--shadow); }
.card summary { cursor:pointer; list-style:none; }
.card summary::-webkit-details-marker { display:none; }
.card summary::marker { content:""; }
.card summary .id { color:var(--accent); font-family:ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size:11px; letter-spacing:0.02em; }
.card summary .title { font-weight:600; margin-top:2px; display:block; }
.card .meta-row { display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; font-size:11px; }
.badge { padding:1px 7px; border-radius:10px; font-size:11px; background:var(--col-bg); color:var(--muted); }
.badge.thread { background:transparent; color:var(--muted); border:1px solid var(--border); }
.badge.approval { color:#fff; }
.card .body { margin-top:8px; border-top:1px dashed var(--border); padding-top:6px; }
.card dl { margin:0; }
.card dt { color:var(--muted); font-size:11px; margin-top:6px; text-transform:uppercase; letter-spacing:0.03em; }
.card dd { margin:2px 0 0; font-size:13px; word-break:break-word; }
.card ul.forensic { list-style:none; padding:0; margin:6px 0 0; }
.card ul.forensic li { margin:2px 0; font-size:12px; }
.card ul.forensic code { background:var(--col-bg); padding:1px 4px; border-radius:3px; font-size:11px;}
footer { padding:16px 20px 40px; color:var(--muted); font-size:11px; text-align:center; }
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
    parts.append('<h1>URA Kanban <span style="color:var(--muted);font-weight:400;font-size:13px;">'
                 'GENERATED - do not hand-edit; source is kanban.data.yaml</span></h1>')
    parts.append(
        '<div class="meta">'
        f'Generated: <code>{_h(meta_extras["gen_ts"])}</code> - '
        f'Data commit: <code>{_h(meta_extras["data_hash"][:12])}</code> - '
        f'last_reconciled: <code>{_h(meta.get("last_reconciled", "?"))}</code>'
    )
    if meta.get("target_host"):
        parts.append(f' - Hosted: <a href="https://{_h(meta["target_host"])}">{_h(meta["target_host"])}</a>')
    if meta.get("artifact_url"):
        parts.append(f' - <a href="{_h(meta["artifact_url"])}">Artifact</a>')
    parts.append('</div></header>')

    if meta_extras["is_stale"]:
        parts.append('<div class="stale"><h2>⚠️ STALE - board has not been reconciled against newer work</h2><ul>')
        for r in meta_extras["stale_reasons"]:
            parts.append(f'<li>{_h(r)}</li>')
        parts.append('</ul><div style="margin-top:6px">Reconcile <code>meta.last_reconciled</code> '
                     'and move shipped cards before picking next work.</div></div>')

    parts.append('<div class="summary">')
    for key, emoji, label, _ in COLUMN_META:
        n = len(buckets.get(key, []))
        if n == 0 and key == "other":
            continue
        parts.append(f'<span>{_h(emoji)} {_h(label)}: {n}</span>')
    parts.append('</div>')

    parts.append('<main class="board">')
    for key, emoji, label, hint in COLUMN_META:
        cards_here = buckets.get(key, [])
        if not cards_here and key == "other":
            continue
        parts.append(f'<section class="col" data-col="{_h(key)}">')
        parts.append(f'<h2>{_h(emoji)} {_h(label)} <span class="count">{len(cards_here)}</span></h2>')
        parts.append(f'<div class="hint">{_h(hint)}</div>')
        if not cards_here:
            parts.append('<div class="hint">(none)</div>')
        for c in cards_here:
            parts.append(_render_card_html(c))
        parts.append('</section>')
    parts.append('</main>')

    if parked_extra or backlog_refs:
        parts.append('<section class="col" style="margin:0 20px 20px;">')
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
    parts.append('</body></html>')
    return "\n".join(parts) + "\n"


def _render_card_html(c: dict) -> str:
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

    out = ['<details class="card"><summary>']
    out.append(f'<span class="id">{_h(cid)}</span>')
    out.append(f'<span class="title">{_h(title)}</span>')
    out.append('<div class="meta-row">')
    if thread:
        out.append(_badge(thread, "thread"))
    if status:
        out.append(_badge(status, "status"))
    if approval:
        color = APPROVAL_COLOR.get(approval, "#666")
        out.append(_badge(approval, "approval", color))
    tags = c.get("tags") or []
    if isinstance(tags, list):
        for t in tags[:6]:
            out.append(_badge(str(t), "tag"))
        if len(tags) > 6:
            out.append(_badge(f"+{len(tags)-6}", "tag"))
    out.append('</div>')
    out.append('</summary>')

    out.append('<div class="body"><dl>')
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

    out.append('</dl></div></details>')
    return "".join(out)


# ---------- driver ----------

def build_meta_extras(data_path: Path) -> dict:
    return {
        "data_hash": _git_hash(data_path),
        "gen_ts": _git_commit_iso(data_path),
    }


def render_all(data_path: Path) -> tuple[str, str, bool, list[str]]:
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
    md = render_markdown(data, extras)
    ht = render_html(data, extras)
    return md, ht, is_stale, reasons


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    ap.add_argument("--html-out", type=Path, default=DEFAULT_HTML)
    ap.add_argument("--check", action="store_true", help="do not write; exit 0/2 based on staleness")
    ap.add_argument("--stdout", choices=("md", "html"), help="print to stdout instead of writing")
    args = ap.parse_args(argv)

    try:
        md, ht, stale, reasons = render_all(args.data)
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

    if stale:
        print("[kanban_render] STALE:", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
