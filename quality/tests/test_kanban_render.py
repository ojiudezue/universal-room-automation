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
    """No external requests: no <link rel="stylesheet">, no <script src=>,
    no CDN references."""
    _, ht, _, _ = rendered
    lower = ht.lower()
    assert '<link rel="stylesheet"' not in lower
    assert "<script src=" not in lower
    assert "cdn." not in lower
    assert "googleapis" not in lower


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
    code = kr.main(["--data", str(p), "--check"])
    assert code == 2


def test_exit_code_fresh(tmp_path):
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    data["meta"]["last_reconciled"] = "2099-12-31"
    p = tmp_path / "d.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    code = kr.main(["--data", str(p), "--check"])
    assert code == 0
