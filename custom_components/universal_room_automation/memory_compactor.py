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
EXACTLY two read callsites — ``db.read_memory_episodes`` and
``db.read_memory_facts``. A raw ``aiosqlite.connect`` anywhere in this
module is a CRIT review finding (enforced by
``test_no_raw_aiosqlite_in_compactor``).
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
    """Per-room phantom recurrence rate + typical fan-on span.

    Groups are (node_id,) — one fact per room.
    """
    n = len(rows)
    typical_span_s = _median_span_seconds(rows)
    first_ts = min(r["started_at"] for r in rows)
    last_ts = max(r["started_at"] for r in rows)
    attrs = {
        "room": node_id, "phantom_count": n,
        "first_ts": first_ts, "last_ts": last_ts,
        "typical_fan_on_s": typical_span_s,
    }
    statement = (
        f"phantom_recurrence room={node_id} phantom_count={n} "
        f"first={first_ts} last={last_ts} "
        f"typical_fan_on_s={typical_span_s}"
    )
    return statement, attrs


def _statement_actuation_conflict_daily(
    rows: list[dict], node_id: str, topic: str,
) -> tuple[str, dict]:
    """Per-(room, action, trigger, house_state) daily counts.

    Groups pre-partitioned by identity_keys = (action, trigger,
    house_state); this fn sees one such group at a time.
    """
    a0 = rows[0].get("attrs") or {}
    action = a0.get("action") or "unknown"
    trigger = a0.get("trigger") or "unknown"
    house_state = a0.get("house_state") or "unknown"
    n = len(rows)
    first_ts = min(r["started_at"] for r in rows)
    last_ts = max(r["started_at"] for r in rows)
    attrs = {
        "room": node_id, "action": action, "trigger": trigger,
        "house_state": house_state, "count": n,
        "first_ts": first_ts, "last_ts": last_ts,
    }
    statement = (
        f"actuation_conflict room={node_id} action={action} "
        f"trigger={trigger} house_state={house_state} count={n} "
        f"first={first_ts} last={last_ts}"
    )
    return statement, attrs


_STATEMENT_FNS: dict[str, Callable[[list[dict], str, str], tuple[str, dict]]] = {
    "exterior_track_baseline": _statement_exterior_track_baseline,
    "phantom_recurrence": _statement_phantom_recurrence,
    "actuation_conflict_daily": _statement_actuation_conflict_daily,
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

    async def run(self, *, triggered_by: str = "nightly") -> dict:
        """One compactor pass.

        Returns ``{facts_created, facts_superseded, episodes_redacted,
        writes_total, aborted_reason, triggered_by, started_at,
        finished_at}``.
        """
        started_at = datetime.now(timezone.utc)
        stats = {
            "facts_created": 0,
            "facts_superseded": 0,
            "episodes_redacted": 0,
            "writes_total": 0,
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
            # Partition by identity keys.
            groups: dict[tuple, list[dict]] = {}
            for r in rows:
                a = r.get("attrs") or {}
                key = tuple(a.get(k) for k in identity_keys)
                # Skip rows with missing identity-key values when the
                # rule needs them — defensive against upstream shape
                # surprises.
                if identity_keys and any(v is None for v in key):
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
                stats["writes_total"] += 1
                if res.get("inserted_id") is not None:
                    stats["facts_created"] += 1
                if res.get("superseded"):
                    stats["facts_superseded"] += 1
                if res.get("redacted"):
                    stats["episodes_redacted"] += 1

    # ---------- helpers ----------

    async def _distinct_nodes_for_type(
        self, ep_type: str, since_iso: str,
    ) -> list[str]:
        """Discover node_ids that have episodes of the given type.

        Uses ``get_memory_status_counts``-style aggregation via the
        sanctioned status accessor to avoid a third read DAO. We fall
        back to a single-node discovery when the status accessor does
        not surface per-node lists — for rev-2 the compactor iterates a
        small, known set of nodes derived from the episode-type rule
        catalog. To stay strictly within the two-DAO cap, we ask the DB
        for facts + episodes only; distinct-node discovery here reads
        the status accessor (which itself uses ``_db_read`` — see
        database.get_memory_status_counts) purely for the by-type
        totals used as a *presence* signal.

        NOTE: `get_memory_status_counts` returns totals but not node
        lists. To honor HIGH-2 without adding a third read DAO, we
        instead scan the shipped rule set: for each ep_type we know the
        canonical node namespace (``room:*`` for room-scoped types,
        ``exterior:perimeter`` for exterior_track). This is a design
        constraint of rev-2 and is documented in the plan (§9 deferrals
        for anything that outgrows this scheme).
        """
        # Rev-2 mapping of episode types to their canonical node
        # discovery. Values are either:
        #   * a single literal node_id (str), or
        #   * the sentinel "rooms:*" meaning "iterate configured rooms".
        # For "rooms:*" we lean on hass.data if reachable through the
        # DB; otherwise return an empty list (compactor no-ops for that
        # rule for that run — safe, next run picks up when the room
        # roster is available).
        SCOPES = {
            "exterior_track": ("literal", "exterior:perimeter"),
            "occupancy_phantom": ("rooms", None),
            "actuation_conflict": ("rooms", None),
        }
        kind, val = SCOPES.get(ep_type, ("rooms", None))
        if kind == "literal":
            return [val]
        # kind == "rooms" — enumerate configured room node_ids from
        # hass.data if reachable via the DB handle.
        hass = getattr(self._db, "hass", None)
        if hass is None:
            return []
        try:
            data = hass.data.get("universal_room_automation", {}) or {}
            room_ids = list(
                (data.get("rooms") or data.get("room_coordinators") or {}).keys()
            )
        except Exception:  # noqa: BLE001
            return []
        return [f"room:{rid}" for rid in room_ids]

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
