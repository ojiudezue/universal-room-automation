"""Hierarchical Memory Stage 2 — MemoryCompactor engine.

See ``docs/planning/PLANNING_memory_compactor.md`` (rev-2).

Design invariants (plan §1):

* **(a) Atomicity, per fact.** Every emitted (INSERT [+ supersede
  UPDATE]) pair is issued via ONE call to
  ``URADatabase.distill_memory_fact`` which opens ONE ``_db()`` context
  and issues ONE ``commit()``.
* **(b) Ordering, cross-fact.** Guaranteed by the single-writer worker
  FIFO queue when two logical facts cannot be combined (rare — reserved
  for future adjacency-graph rollups).
* **(c) Preservation.** ``count(memory_episodes)`` never decreases; no
  fact row is ever edited in place; corrections write a new row and set
  ``superseded_by`` on the old.

Read discipline (HIGH-2, CRIT-blocking on review): the engine has
EXACTLY three read callsites — ``db.read_memory_episodes``,
``db.read_memory_facts``, and ``db.read_distinct_nodes_for_episodes``
(added 2026-08-14 as the fix for HIGH-A1). All three go through
``_db_read()``. Any raw ``aiosqlite`` reference (import, attribute, or
string constant) anywhere in this module is a CRIT review finding —
the AST scan in ``test_no_raw_aiosqlite_in_compactor`` catches direct
imports, ``aiosqlite.connect`` attribute access, AND string-constant
evasions (``importlib.import_module("aiosqlite")`` etc.). Each read
DAO has its own named mutation drill.
"""

from __future__ import annotations

import logging
import statistics as _statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .const import (
    MEMORY_COMPACTION_RULES,
    MEMORY_COMPACTOR_MAX_WRITES_PER_RUN,
    MEMORY_EPISODE_TYPES,
    MEMORY_FACT_TOPICS,
)

_LOGGER = logging.getLogger(__name__)


# --- Frozen statement_fn implementations (pure functions). MED-1 fix:
#     templates are frozen by the D1 hand-compact oracle; this module
#     implements them verbatim so
#     tests/test_memory_compactor.py::test_stage0_fixture_diff
#     round-trips exactly against the hand-oracle JSON.

def _median_span_seconds(rows: list[dict]) -> float:
    spans: list[float] = []
    for r in rows:
        e = r.get("ended_at")
        s = r.get("started_at")
        if not e or not s:
            continue
        try:
            spans.append(
                (datetime.fromisoformat(e)
                 - datetime.fromisoformat(s)).total_seconds()
            )
        except Exception:  # noqa: BLE001
            continue
    if not spans:
        return 0.0
    return round(_statistics.median(spans), 1)


def _statement_exterior_track_baseline(
    rows: list[dict], node_id: str, topic: str,
) -> tuple[str, dict]:
    """Frozen per docs/planning/AUDIT_memory_handbuild_compactor_exterior_track.md.

    Groups are pre-partitioned upstream by (attrs.path[0], attrs.label).
    """
    a0 = rows[0].get("attrs") or {}
    path = a0.get("path") or []
    cam = path[0] if path else "unknown"
    label = a0.get("label") or "unknown"
    n = len(rows)
    first_ts = min(r["started_at"] for r in rows)
    last_ts = max(r["started_at"] for r in rows)
    typical_span_s = _median_span_seconds(rows)
    attrs = {
        "camera": cam, "label": label, "count": n,
        "first_ts": first_ts, "last_ts": last_ts,
        "typical_span_s": typical_span_s,
    }
    statement = (
        f"exterior_track baseline camera={cam} label={label} "
        f"count={n} first={first_ts} last={last_ts} "
        f"typical_span_s={typical_span_s}"
    )
    return statement, attrs


def _statement_phantom_recurrence(
    rows: list[dict], node_id: str, topic: str,
) -> tuple[str, dict]:
    """Per-room D2-DETECTED phantom-recurrence rate + typical fan-on span.

    Groups are (node_id,) — one fact per room.

    IMPORTANT (per AUDIT_memory_retro_value.md + Vision §6 confident-
    garbage warning + orchestrator amendment 2026-08-14): this rule
    measures phantoms the D2 detector actually caught. A room with zero
    phantom episodes may be sensor-blind, not healthy — the fact carries
    ``coverage="d2_gated"`` in attrs and the statement text says
    ``d2-detected`` so downstream readers cannot invert the reading
    (Ziri 39 vs Guestroom 0 misread class).
    """
    n = len(rows)
    typical_span_s = _median_span_seconds(rows)
    first_ts = min(r["started_at"] for r in rows)
    last_ts = max(r["started_at"] for r in rows)
    attrs = {
        "room": node_id,
        "phantom_count": n,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "typical_fan_on_s": typical_span_s,
        # Coverage-provenance marker — DO NOT drop. Absence would invite
        # the confident-garbage misread. See docstring.
        "coverage": "d2_gated",
    }
    statement = (
        f"phantom_recurrence (d2-detected) room={node_id} "
        f"phantom_count={n} first={first_ts} last={last_ts} "
        f"typical_fan_on_s={typical_span_s} coverage=d2_gated"
    )
    return statement, attrs


def _statement_actuation_conflict_summary(
    rows: list[dict], node_id: str, topic: str,
) -> tuple[str, dict]:
    """Per-(room, action, trigger, house_state) rolling-window summary.

    Groups pre-partitioned by identity_keys = (action, trigger,
    house_state); this fn sees one such group at a time.

    Rev-2 rename (MED-A3, orchestrator fix-up 2026-08-14): topic
    renamed from ``actuation_conflict_daily`` ->
    ``actuation_conflict_summary`` and statement text now explicitly
    labels the aggregate as a ``window`` sum with the observed span
    in seconds — the fact is a rolling 7-day count, NOT a per-day
    bucket. Day-bucketing was explicitly ruled OUT of this cycle by
    the orchestrator.
    """
    a0 = rows[0].get("attrs") or {}
    action = a0.get("action") or "unknown"
    trigger = a0.get("trigger") or "unknown"
    house_state = a0.get("house_state") or "unknown"
    n = len(rows)
    first_ts = min(r["started_at"] for r in rows)
    last_ts = max(r["started_at"] for r in rows)
    # Observed span (seconds) between first and last row in this window.
    try:
        window_span_s = int(
            (datetime.fromisoformat(last_ts)
             - datetime.fromisoformat(first_ts)).total_seconds()
        )
    except Exception:  # noqa: BLE001
        window_span_s = 0
    attrs = {
        "room": node_id, "action": action, "trigger": trigger,
        "house_state": house_state, "count": n,
        "first_ts": first_ts, "last_ts": last_ts,
        "window_span_s": window_span_s,
    }
    statement = (
        f"actuation_conflict summary room={node_id} action={action} "
        f"trigger={trigger} house_state={house_state} count={n} "
        f"window_span_s={window_span_s} first={first_ts} last={last_ts}"
    )
    return statement, attrs


_STATEMENT_FNS: dict[str, Callable[[list[dict], str, str], tuple[str, dict]]] = {
    "exterior_track_baseline": _statement_exterior_track_baseline,
    "phantom_recurrence": _statement_phantom_recurrence,
    "actuation_conflict_summary": _statement_actuation_conflict_summary,
}


# Per-rule attrs -> identity-key extractor. exterior_track's "camera" is
# nested under attrs.path[0], not a top-level attr. Keeping this table
# alongside _STATEMENT_FNS keeps rule-specific quirks in one place. The
# extractor returns a tuple aligned with the rule's ``identity_keys``.
def _key_exterior_track(attrs: dict) -> tuple:
    path = attrs.get("path") or []
    return (path[0] if path else None, attrs.get("label"))


def _key_from_attrs(identity_keys: tuple) -> Callable[[dict], tuple]:
    """Default extractor: read each identity_key as a top-level attr."""
    def _extract(attrs: dict) -> tuple:
        return tuple(attrs.get(k) for k in identity_keys)
    return _extract


_KEY_FNS: dict[str, Callable[[dict], tuple]] = {
    "exterior_track_baseline": _key_exterior_track,
    # actuation_conflict_summary + phantom_recurrence use default extractor
    # (identity_keys map to top-level attrs).
}


# --- Boot-time asserts (CRIT-2 fix). Import-time failure surfaces
#     before any write. Symmetric with the episode-type constraint.
_rule_types = set(MEMORY_COMPACTION_RULES.keys())
assert _rule_types <= MEMORY_EPISODE_TYPES, (
    "MEMORY_COMPACTION_RULES keys must be a subset of MEMORY_EPISODE_TYPES; "
    f"orphans: {sorted(_rule_types - MEMORY_EPISODE_TYPES)}"
)
_rule_topics = {r["topic"] for r in MEMORY_COMPACTION_RULES.values()}
assert _rule_topics <= MEMORY_FACT_TOPICS, (
    "Every rule topic must be in MEMORY_FACT_TOPICS (write-quality gate); "
    f"orphans: {sorted(_rule_topics - MEMORY_FACT_TOPICS)}"
)
_rule_fns = {r["statement_fn"] for r in MEMORY_COMPACTION_RULES.values()}
assert _rule_fns <= set(_STATEMENT_FNS.keys()), (
    "Every rule statement_fn must be implemented in _STATEMENT_FNS; "
    f"missing: {sorted(_rule_fns - set(_STATEMENT_FNS.keys()))}"
)


class MemoryCompactor:
    """One-pass compactor engine (distill / correct / redact-stub).

    Not stateful across runs — cadence + last-stats live on the
    URADatabase instance (see ``run_memory_compactor``).
    """

    def __init__(self, db: Any) -> None:
        # `db` is a URADatabase; typed Any to avoid circular import.
        self._db = db

    async def run(
        self,
        *,
        triggered_by: str = "nightly",
        now: datetime | None = None,
    ) -> dict:
        """One compactor pass.

        `now` is an optional injection point so tests can pin the
        rolling-window anchor deterministically against frozen fixture
        data. Production callers pass None; the engine anchors on
        ``datetime.now(timezone.utc)``.

        Returns ``{facts_created, facts_superseded, episodes_redacted,
        writes_total, aborted_reason, triggered_by, started_at,
        finished_at}``.
        """
        started_at = now or datetime.now(timezone.utc)
        stats = {
            "facts_created": 0,
            "facts_superseded": 0,
            "episodes_redacted": 0,
            # Effective writes only (fix-up B-LOW-2). See _run_rule.
            "writes_total": 0,
            # Raw distill_memory_fact call count — observability delta
            # vs writes_total so cap starvation surfaces if it happens.
            "distill_calls": 0,
            # Rows skipped because identity_keys attrs missing on the
            # upstream episode (fix-up MED-A2). Surfaces upstream-
            # writer shape drift.
            "skipped_missing_identity": 0,
            "aborted_reason": None,
            "triggered_by": triggered_by,
            "started_at": started_at.isoformat(),
            "finished_at": None,
        }
        # Ordered rules — lowest priority int runs first. Deterministic.
        rules = sorted(
            MEMORY_COMPACTION_RULES.items(),
            key=lambda kv: (kv[1].get("priority", 999), kv[0]),
        )
        try:
            for ep_type, rule in rules:
                if stats["writes_total"] >= MEMORY_COMPACTOR_MAX_WRITES_PER_RUN:
                    stats["aborted_reason"] = "cap"
                    break
                await self._run_rule(ep_type, rule, stats, started_at)
                if stats["writes_total"] >= MEMORY_COMPACTOR_MAX_WRITES_PER_RUN:
                    stats["aborted_reason"] = "cap"
                    break
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("memory_compactor.run: %s", e, exc_info=True)
            stats["aborted_reason"] = f"exception:{type(e).__name__}"
        stats["finished_at"] = datetime.now(timezone.utc).isoformat()
        if stats["aborted_reason"] == "cap":
            _LOGGER.info(
                "memory_compactor: write cap hit (%d) — resuming next tick",
                MEMORY_COMPACTOR_MAX_WRITES_PER_RUN,
            )
        return stats

    # ---------- per-rule execution ----------

    async def _run_rule(
        self, ep_type: str, rule: dict, stats: dict, now_utc: datetime,
    ) -> None:
        topic: str = rule["topic"]
        min_count: int = int(rule["min_count"])
        if min_count >= 2**31 - 1:
            # Kill-switch semantics (§5): sys.maxsize disables the rule.
            _LOGGER.debug("compactor rule %s disabled (min_count)", ep_type)
            return
        window_days: int = int(rule["window_days"])
        require_adj: bool = bool(rule.get("require_adjudicated", False))
        identity_keys: tuple = tuple(rule.get("identity_keys", ()))
        fn_name: str = rule["statement_fn"]
        stmt_fn = _STATEMENT_FNS[fn_name]

        since_iso = (now_utc - timedelta(days=window_days)).isoformat()
        # Snapshot for MED-A2 per-rule WARN.
        _skipped_before = int(stats.get("skipped_missing_identity", 0))

        node_ids = await self._distinct_nodes_for_type(ep_type, since_iso)
        for node_id in node_ids:
            if stats["writes_total"] >= MEMORY_COMPACTOR_MAX_WRITES_PER_RUN:
                return
            # SANCTIONED READ #1
            rows = await self._db.read_memory_episodes(
                node_id, episode_type=ep_type, since_iso=since_iso,
            )
            if require_adj:
                rows = [
                    r for r in rows
                    if (r.get("adjudication") or "unadjudicated")
                    != "unadjudicated"
                ]
            if not rows:
                continue
            # Partition by identity keys. Rule-specific extractor when
            # the identity key is nested (e.g. exterior_track's
            # "camera" = attrs.path[0]); default extractor reads
            # each identity_key as a top-level attr.
            key_fn = _KEY_FNS.get(fn_name) or _key_from_attrs(identity_keys)
            groups: dict[tuple, list[dict]] = {}
            for r in rows:
                a = r.get("attrs") or {}
                key = key_fn(a)
                # Skip rows with missing identity-key values when the
                # rule needs them — defensive against upstream shape
                # surprises. Fix-up MED-A2 (2026-08-14): count the
                # drops in run stats + WARN once per rule per run so
                # upstream-writer shape drift can't silently under-
                # distill.
                if identity_keys and any(v is None for v in key):
                    stats["skipped_missing_identity"] = int(
                        stats.get("skipped_missing_identity", 0),
                    ) + 1
                    continue
                groups.setdefault(key, []).append(r)

            # Read existing current facts for this (node, topic) ONCE.
            # SANCTIONED READ #2
            current_facts = await self._db.read_memory_facts(
                node_id, topic=topic, include_superseded=False,
            )

            for key, gp_rows in groups.items():
                if len(gp_rows) < min_count:
                    continue
                if stats["writes_total"] >= MEMORY_COMPACTOR_MAX_WRITES_PER_RUN:
                    return
                # Skip empty-attrs edge case defensively.
                try:
                    statement, attrs = stmt_fn(gp_rows, node_id, topic)
                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning(
                        "statement_fn %s failed for node=%s key=%s: %s",
                        fn_name, node_id, key, e,
                    )
                    continue
                derived_from = ",".join(
                    str(r["id"]) for r in sorted(gp_rows, key=lambda r: r["id"])
                )
                # Correction detection: find existing current fact under
                # matching identity_keys whose attrs differ.
                supersede_old_id = self._match_supersede(
                    current_facts, attrs, identity_keys,
                )
                res = await self._db.distill_memory_fact(
                    node_id=node_id,
                    topic=topic,
                    statement=statement,
                    attrs=attrs,
                    confidence=self._confidence_for(rule, gp_rows),
                    derived_from=derived_from,
                    supersede_old_id=supersede_old_id,
                )
                # Fix-up B-LOW-2 (2026-08-14): count only EFFECTIVE
                # writes toward the cap. INSERT-OR-IGNORE no-ops (same
                # (node,topic,statement) already present) don't consume
                # a real write slot; re-runs must be able to iterate
                # every group cheaply after a prior cap-abort or the
                # rules starve each other across nights. `distill_calls`
                # tracks the raw DAO call count for observability.
                stats["distill_calls"] = int(
                    stats.get("distill_calls", 0),
                ) + 1
                effective = (
                    res.get("inserted_id") is not None
                    or res.get("superseded")
                    or res.get("redacted")
                )
                if effective:
                    stats["writes_total"] += 1
                if res.get("inserted_id") is not None:
                    stats["facts_created"] += 1
                if res.get("superseded"):
                    stats["facts_superseded"] += 1
                if res.get("redacted"):
                    stats["episodes_redacted"] += 1

        # Fix-up MED-A2: WARN once per rule if any rows were dropped
        # for missing identity-key attrs (upstream shape drift signal).
        _skipped_after = int(stats.get("skipped_missing_identity", 0))
        _delta = _skipped_after - _skipped_before
        if _delta > 0:
            _LOGGER.warning(
                "memory_compactor rule=%s dropped %d row(s) for missing "
                "identity_keys=%s — check upstream writer shape drift",
                ep_type, _delta, list(identity_keys),
            )

    # ---------- helpers ----------

    async def _distinct_nodes_for_type(
        self, ep_type: str, since_iso: str,
    ) -> list[str]:
        """Data-driven node discovery via the sanctioned third read DAO.

        Fix-up HIGH-A1 + MED-A1 (2026-08-14): the prior rev shipped a
        hardcoded ``SCOPES`` table that (i) required a separate boot-
        assert to catch new-rule drift and (ii) looked up
        ``hass.data[DOMAIN]["rooms"]`` — a key that never exists (rooms
        live under ``hass.data[DOMAIN][entry.entry_id]``), so both
        room-scoped rules silently distilled nothing. Replaced with
        ``db.read_distinct_nodes_for_episodes(ep_type, since_iso)``
        which reads exactly the nodes that *actually have* episodes in
        the window. HIGH-2 (Stage-1) compliance: the new read DAO is
        on ``_db_read()`` and covered by mutation drill #5.
        """
        try:
            return await self._db.read_distinct_nodes_for_episodes(
                ep_type, since_iso,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "_distinct_nodes_for_type(%s): DAO read failed: %s",
                ep_type, e,
            )
            return []

    @staticmethod
    def _match_supersede(
        current_facts: list[dict], new_attrs: dict, identity_keys: tuple,
    ) -> int | None:
        """Return the id of an existing current fact whose identity-key
        subset of attrs matches `new_attrs` but whose FULL attrs
        differ. Returns None if no match, or if identity keys match AND
        full attrs match (idempotent no-op path — DAO's INSERT OR IGNORE
        handles this).
        """
        for f in current_facts:
            f_attrs = f.get("attrs") or {}
            if identity_keys:
                if any(
                    f_attrs.get(k) != new_attrs.get(k)
                    for k in identity_keys
                ):
                    continue
            # identity match (or no identity keys). Compare full attrs.
            if _dict_equal(f_attrs, new_attrs):
                return None  # idempotent — no supersede
            return int(f["id"])
        return None

    @staticmethod
    def _confidence_for(rule: dict, rows: list[dict]) -> float:
        """Rev-2: coarse confidence — 0.6 if all rows unadjudicated,
        0.8 if the rule required adjudication.
        """
        return 0.8 if rule.get("require_adjudicated") else 0.6


def _dict_equal(a: dict, b: dict) -> bool:
    """Deterministic key-sorted equality for two flat dicts (attrs)."""
    if set(a.keys()) != set(b.keys()):
        return False
    for k in a:
        if a[k] != b[k]:
            return False
    return True
