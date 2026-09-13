"""BOARD-AUTONOMY-PROGRESS-1 — guard for the render counter/feed logic in
scripts/kanban_render.py::autonomy_stats.

- numerator counts feed entries within the last 24h (ack-agnostic);
- denominator = cards with status != done (shrinks as work completes);
- live feed excludes acknowledged entries AND entries older than 7 days.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC = os.path.join(_REPO, "scripts", "kanban_render.py")


def _load():
    spec = importlib.util.spec_from_file_location("_kanban_render", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NOW = dt.datetime(2026, 9, 12, 18, 0, 0)


def _data(feed, cards):
    return {"meta": {"autonomy_feed": feed}, "cards": cards}


def test_numerator_counts_last_24h_only():
    kr = _load()
    feed = [
        {"fid": "a", "at": "2026-09-12T12:00:00", "outcome": "built", "headline": "a"},   # 6h ago
        {"fid": "b", "at": "2026-09-11T19:00:00", "outcome": "built", "headline": "b"},   # 23h ago
        {"fid": "c", "at": "2026-09-10T10:00:00", "outcome": "parked", "headline": "c"},  # >24h ago
    ]
    s = kr.autonomy_stats(_data(feed, []), now=NOW)
    assert s["num"] == 2  # a + b within 24h; c excluded


def test_denominator_is_non_done_count():
    kr = _load()
    cards = [{"status": "done"}, {"status": "review"}, {"status": "parked"},
             {"status": "done"}, {"status": "investigating"}]
    s = kr.autonomy_stats(_data([], cards), now=NOW)
    assert s["denom"] == 3  # 5 total - 2 done


def test_live_feed_excludes_acked_and_archived():
    kr = _load()
    feed = [
        {"fid": "live", "at": "2026-09-12T12:00:00", "outcome": "built", "headline": "live"},
        {"fid": "acked", "at": "2026-09-12T12:00:00", "outcome": "built", "headline": "x",
         "acknowledged": True},
        {"fid": "old", "at": "2026-09-01T12:00:00", "outcome": "built", "headline": "y"},  # >7d
    ]
    s = kr.autonomy_stats(_data(feed, []), now=NOW)
    fids = [e["fid"] for e in s["live"]]
    assert fids == ["live"]  # acked + >7d old both hidden


def test_live_feed_newest_first():
    kr = _load()
    feed = [
        {"fid": "older", "at": "2026-09-12T09:00:00", "outcome": "built", "headline": "1"},
        {"fid": "newer", "at": "2026-09-12T15:00:00", "outcome": "built", "headline": "2"},
    ]
    s = kr.autonomy_stats(_data(feed, []), now=NOW)
    assert [e["fid"] for e in s["live"]] == ["newer", "older"]
