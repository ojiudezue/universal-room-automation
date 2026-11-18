"""Tests for scripts/kanban_render.py (KHOST-1).

Renders the REAL board data file and asserts:
  - every card id in the data appears in BOTH outputs (nothing dropped)
  - forensic/unknown keys are represented (at least mentioned by name)
  - STALE banner appears when meta.last_reconciled is backdated
    and is ABSENT when it is current
  - byte-stability: two renders in a row produce byte-identical output
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "kanban_render.py"
DATA_FILE = REPO_ROOT / "docs" / "planning" / "kanban.data.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location("kanban_render", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kanban_render"] = mod
    spec.loader.exec_module(mod)
    return mod


kr = _load_module()


@pytest.fixture(scope="module")
def data():
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def rendered():
    md, ht, is_stale, reasons = kr.render_all(DATA_FILE)
    return md, ht, is_stale, reasons


def test_data_file_parses(data):
    assert "cards" in data
    assert "meta" in data
    assert isinstance(data["cards"], list)
    assert len(data["cards"]) > 0


def test_every_card_id_present_in_markdown(data, rendered):
    md, _, _, _ = rendered
    missing = [c["id"] for c in data["cards"] if c["id"] not in md]
    assert not missing, f"missing card ids in markdown: {missing}"


def test_every_card_id_present_in_html(data, rendered):
    _, ht, _, _ = rendered
    missing = [c["id"] for c in data["cards"] if c["id"] not in ht]
    assert not missing, f"missing card ids in html: {missing}"


def test_every_card_title_present_in_html(data, rendered):
    import html as _html
    _, ht, _, _ = rendered
    for c in data["cards"]:
        title = str(c.get("title", ""))
        needle = _html.escape(title[:60])
        assert needle in ht, f"card {c['id']} title fragment not in html: {needle!r}"


def test_forensic_keys_are_represented(data, rendered):
    """Any card key not in STANDARD_FIELDS must be mentioned by name in the
    forensic list of both outputs — the generator must not silently drop it."""
    md, ht, _, _ = rendered
    for c in data["cards"]:
        forensic = [k for k in c.keys() if k not in kr.STANDARD_FIELDS]
        for k in forensic:
            assert k in md, f"forensic key {k!r} on card {c['id']} missing from markdown"
            assert k in ht, f"forensic key {k!r} on card {c['id']} missing from html"


def test_stale_banner_present_when_stale(tmp_path):
    """Backdate last_reconciled to force stale; STALE banner must render in both."""
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["meta"]["last_reconciled"] = "1970-01-01"
    stale_path = tmp_path / "kanban.data.yaml"
    stale_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    md, ht, is_stale, reasons = kr.render_all(stale_path)
    assert is_stale, "expected stale=True with 1970 last_reconciled"
    assert reasons, "expected reasons list to be non-empty"
    assert "STALE - board has not been reconciled" in md, "STALE banner missing from markdown"
    assert "STALE" in ht, "STALE banner missing from html"


def test_stale_banner_absent_when_current(tmp_path):
    """Bump last_reconciled far into the future; banner must be absent."""
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["meta"]["last_reconciled"] = "2099-12-31"
    fresh_path = tmp_path / "kanban.data.yaml"
    fresh_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    md, ht, is_stale, reasons = kr.render_all(fresh_path)
    assert not is_stale, f"expected fresh, got reasons: {reasons}"
    # The word "STALE" must not appear in either output body when fresh.
    # (No banner and no reasons list.)
    assert "STALE - board has not been reconciled" not in md  # banner MARKER, not substring: card prose legitimately contains the word STALE
    assert "STALE - board has not been reconciled" not in ht


def test_byte_stability_on_double_render():
    md1, ht1, _, _ = kr.render_all(DATA_FILE)
    md2, ht2, _, _ = kr.render_all(DATA_FILE)
    assert md1 == md2, "markdown render is not byte-stable"
    assert ht1 == ht2, "html render is not byte-stable"


def test_html_is_self_contained(rendered):
    """No external requests except the URA brand fonts (operator 2026-10-17:
    allow Google Fonts, added deliberately in the 2026-09-12 reskin). No
    external scripts, no CDNs, no other hosts."""
    import re
    from urllib.parse import urlparse

    _, ht, _, _ = rendered
    lower = ht.lower()
    assert "<script src=" not in lower
    assert "cdn." not in lower
    allowed = {"fonts.googleapis.com", "fonts.gstatic.com"}
    hosts = {
        urlparse(u).hostname
        for u in re.findall(r'(?:href|src)="(https?://[^"]+)"', ht, re.I)
    }
    assert hosts <= allowed, f"unexpected external hosts: {hosts - allowed}"


def test_columns_grouping(data, rendered):
    """Every column heading present."""
    md, ht, _, _ = rendered
    for key, _emoji, label, _hint in kr.COLUMN_META:
        # Skip the "other" bucket if empty (rendered only when nonempty).
        buckets = kr.group_cards(data["cards"])
        if key == "other" and not buckets.get(key):
            continue
        assert label in md, f"missing column heading {label!r} in markdown"
        assert label in ht, f"missing column heading {label!r} in html"


def test_generation_timestamp_derived_from_data_commit(rendered):
    """The generation timestamp must NOT be a live wall-clock now(); it must
    come from the data file's git commit date so regeneration without a data
    change is byte-stable. Verified by ensuring double-render produces the
    same timestamp (covered by test_byte_stability), and that the header text
    contains the phrase 'GENERATED' as promised."""
    md, ht, _, _ = rendered
    assert "GENERATED" in md
    assert "GENERATED" in ht


def test_exit_code_stale_when_backdated(tmp_path, monkeypatch, capsys):
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["meta"]["last_reconciled"] = "1970-01-01"
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    code = kr.main(["--data", str(p), "--check",
                    "--pending", str(tmp_path / "no_pending.jsonl")])
    assert code == 2


def test_exit_code_fresh(tmp_path):
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["meta"]["last_reconciled"] = "2099-12-31"
    for c in data["cards"]:  # real follow-ups may be due; exit 4 has its own test
        c.pop("due", None)
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    code = kr.main(["--data", str(p), "--check",
                    "--pending", str(tmp_path / "no_pending.jsonl")])
    assert code == 0


def test_exit_code_unapplied_dispositions(tmp_path):
    """Forcing function (2026-08-15): --check exits 3 while dispositions
    sit unapplied, regardless of freshness."""
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["meta"]["last_reconciled"] = "2099-12-31"
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    pend = tmp_path / "pending.jsonl"
    pend.write_text('{"card_id": "X-1", "action": "approve", "at": "2026-08-15T00:00:00Z"}\n',
                    encoding="utf-8")
    code = kr.main(["--data", str(p), "--check", "--pending", str(pend)])
    assert code == 3


# ---------- due-dated follow-ups + Decisions view (2026-11-18) ----------

def _mini_board(tmp_path, cards):
    data = {"meta": {"last_reconciled": "2099-12-31"}, "cards": cards}
    p = tmp_path / "mini.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


_DUE_CARDS = [
    {"id": "OVER-1", "title": "t", "status": "waiting_me",
     "due": "2026-11-18 10:00", "due_note": "ship it"},
    {"id": "SOON-1", "title": "t", "status": "planned", "due": "2026-11-19 09:00"},
    {"id": "LATER-1", "title": "t", "status": "planned", "due": "2026-11-24 10:00"},
    {"id": "DONE-1", "title": "t", "status": "done", "due": "2026-11-01 10:00"},
    {"id": "PLAIN-1", "title": "t", "status": "planned"},
]
_NOW = "2026-11-18 12:00"


def test_due_state_classification():
    now = kr._parse_now(_NOW)
    st = {c["id"]: kr.due_state(c, now) for c in _DUE_CARDS}
    assert st == {"OVER-1": "overdue", "SOON-1": "soon", "LATER-1": "upcoming",
                  "DONE-1": "overdue", "PLAIN-1": None}
    assert kr.due_state({"due": "next tuesday"}, now) == "invalid"
    ids = [e["id"] for e in kr.due_entries({"cards": _DUE_CARDS}, now)]
    assert ids == ["OVER-1", "SOON-1"]  # done excluded, upcoming excluded, sorted by due


def test_check_exit_4_when_due_and_listed(tmp_path, capsys):
    p = _mini_board(tmp_path, _DUE_CARDS)
    code = kr.main(["--data", str(p), "--check", "--now", _NOW,
                    "--pending", str(tmp_path / "none.jsonl")])
    assert code == 4
    err = capsys.readouterr().err
    assert "OVERDUE" in err and "OVER-1" in err and "ship it" in err and "SOON-1" in err
    assert "LATER-1" not in err


def test_check_exit_0_when_nothing_due(tmp_path):
    p = _mini_board(tmp_path, _DUE_CARDS)
    code = kr.main(["--data", str(p), "--check", "--now", "2026-10-01 00:00",
                    "--pending", str(tmp_path / "none.jsonl")])
    assert code == 0


def test_check_precedence_queue_over_due(tmp_path):
    p = _mini_board(tmp_path, _DUE_CARDS)
    pend = tmp_path / "pending.jsonl"
    pend.write_text('{"card_id": "X-1", "action": "approve", "at": "2026-08-15T00:00:00Z"}\n',
                    encoding="utf-8")
    assert kr.main(["--data", str(p), "--check", "--now", _NOW, "--pending", str(pend)]) == 3


def test_due_flag_plain_and_hook_json(tmp_path, capsys):
    import json
    p = _mini_board(tmp_path, _DUE_CARDS)
    assert kr.main(["--data", str(p), "--due", "--now", _NOW]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2 and "OVER-1" in out[0] and "status: waiting_me" in out[0]
    assert kr.main(["--data", str(p), "--due", "--hook-json", "--now", _NOW]) == 0
    payload = json.loads(capsys.readouterr().out)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "OVER-1" in ctx and "SOON-1" in ctx
    # nothing due -> hook prints nothing
    assert kr.main(["--data", str(p), "--due", "--hook-json", "--now", "2026-10-01 00:00"]) == 0
    assert capsys.readouterr().out == ""


def test_due_renders_on_card_and_absent_cards_unchanged():
    card = {"id": "C-1", "title": "x", "status": "planned", "due": "2026-11-18 10:00",
            "due_note": "pull grades"}
    md = "\n".join(kr._render_card_md(dict(card)))
    ht = kr._render_card_html(dict(card))
    assert "Due:** 2026-11-18 10:00 — pull grades" in md
    assert 'data-due="2026-11-18T10:00"' in ht and "pull grades" in ht
    assert "Forensic" not in ht  # due/due_note are standard fields, not forensic
    bare = {k: v for k, v in card.items() if k not in ("due", "due_note")}
    assert "due" not in "\n".join(kr._render_card_md(dict(bare))).lower()
    assert "due-chip" not in kr._render_card_html(dict(bare))


def test_due_chip_bytes_do_not_depend_on_clock():
    """Soon/OVERDUE styling is applied client-side; the render is clock-free."""
    card = {"id": "C-1", "title": "x", "status": "planned", "due": "2000-01-01 00:00"}
    ht = kr._render_card_html(dict(card))
    assert "OVERDUE" not in ht and 'class="due-chip"' in ht


def test_pick_options_parsing():
    assert [l for l, _ in kr.pick_options(
        "PICK: A keep sweep-close, or B make it a knob -> I plan it.")] == ["A", "B"]
    assert [l for l, _ in kr.pick_options(
        "PICK: (A) PARK lever A, RECOMMENDED. (B) BUILD it anyway -> I act.")] == ["A", "B"]
    assert [l for l, _ in kr.pick_options(
        "PICK scope: (a) fix solar-only, or (b) build the shared check")] == ["A", "B"]
    three = kr.pick_options("PICK: A (recommended) add a radar; or B check the app, or C accept -> x")
    assert [l for l, _ in three] == ["A", "B", "C"]
    assert three[0][1].startswith("(recommended) add a radar")
    assert kr.pick_options("PICK (operator): today / off / night lights only -> x") == []
    assert kr.pick_options("APPROVE: A or B") == []


def test_decisions_view_oldest_first_with_picks(tmp_path):
    cards = [
        {"id": "NEW-1", "title": "n", "status": "waiting_operator", "updated": "2026-11-17",
         "next": "PICK: A do it, or B skip -> I act."},
        {"id": "OLD-1", "title": "o", "status": "waiting_operator", "updated": "2026-10-01",
         "next": "APPROVE: the plan -> I build."},
        {"id": "OTHER-1", "title": "x", "status": "planned", "next": "PICK: A or B"},
    ]
    p = _mini_board(tmp_path, cards)
    v = kr.render_views(p, tmp_path / "none.jsonl")
    dec = v["decisions"]
    assert dec.index('data-id="OLD-1"') < dec.index('data-id="NEW-1"')
    assert 'data-id="OTHER-1"' not in dec
    assert 'data-pick="A"' in dec and 'data-pick="B"' in dec
    assert "api/disposition" in dec and "'instruct'" in dec and "'PICK '" in dec
    assert '<form class="answer">' in dec
    # the same section is anchored on the main board
    assert 'id="decisions"' in v["html"]
    # pure function of the data
    assert kr.render_views(p, tmp_path / "none.jsonl")["decisions"] == dec
