"""Room rules: nightly accuracy roll-up, zero-fire trip-wire, digest line.

AI-ROOM-RULES-TRUST-REPAIR-1 D6.3 / D6.4 / D6.5
(``docs/planning/PLANNING_unified_room_rules.md``). Reads the room-memory
rows the room executor writes (``room_rule_decision`` /
``room_rule_reversal``) and the per-room in-RAM rings. Never raises.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_ROOM_NAME,
    DOMAIN,
    ROOM_RULE_DECISION_EPISODE_TYPE,
    ROOM_RULE_REVERSAL_EPISODE_TYPE,
    ROOM_RULE_SWITCH_EXEMPT_TRIGGERS,
    RULE_ZERO_FIRE_DAYS,
)

_LOGGER = logging.getLogger(__name__)

ACCURACY_HASS_KEY = "room_rules_accuracy"
ACCURACY_WINDOW_DAYS = 7
DIGEST_WINDOW_S = 24 * 3600


def room_rule_coordinators(hass: Any) -> list[Any]:
    """Every room coordinator (duck-typed on the room-rule executor)."""
    try:
        values = list((hass.data.get(DOMAIN) or {}).values())
    except Exception:  # noqa: BLE001
        return []
    return [
        v for v in values
        if callable(getattr(v, "_room_rules", None)) and getattr(v, "entry", None) is not None
        and isinstance(getattr(v, "__dict__", {}).get("_rule_stats"), dict)
    ]


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = dt_util.parse_datetime(str(value))
    except Exception:  # noqa: BLE001
        return None
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt_util.UTC)
    return ts


async def run_room_rules_health(hass: Any, database: Any, *, now: datetime | None = None) -> dict:
    """Nightly: 7-day accuracy roll-up (-> ``sensor.ura_room_rules_accuracy``)
    and the per-rule ``room_rule_silent`` trip-wire. Returns a summary."""
    out: dict = {"paged": [], "accuracy": None}
    if database is None or not hasattr(database, "read_memory_episodes_by_type"):
        return out
    now = now or dt_util.utcnow()
    try:
        acc_since = (now - timedelta(days=ACCURACY_WINDOW_DAYS)).isoformat()
        rows = await database.read_memory_episodes_by_type(
            ROOM_RULE_DECISION_EPISODE_TYPE, acc_since)
        revs = await database.read_memory_episodes_by_type(
            ROOM_RULE_REVERSAL_EPISODE_TYPE, acc_since)
        per_rule: dict[str, dict] = {}
        for r in rows or []:
            a = r.get("attrs") or {}
            if a.get("outcome") != "fired":
                continue
            key = f"{r.get('node_id')}|{a.get('rule_id')}"
            per_rule.setdefault(key, {"fires": 0, "reversals": 0})["fires"] += 1
        for r in revs or []:
            a = r.get("attrs") or {}
            key = f"{r.get('node_id')}|{a.get('rule_id')}"
            per_rule.setdefault(key, {"fires": 0, "reversals": 0})["reversals"] += 1
        fires = sum(v["fires"] for v in per_rule.values())
        reversals = sum(min(v["reversals"], v["fires"]) for v in per_rule.values())
        rules_attr = {}
        for k, v in per_rule.items():
            pct = None
            if v["fires"]:
                pct = round(100.0 * (v["fires"] - min(v["reversals"], v["fires"])) / v["fires"], 1)
            rules_attr[k] = {**v, "pct": pct}
        acc = {
            "pct": round(100.0 * (fires - reversals) / fires, 1) if fires else None,
            "fires": fires, "reversals": reversals,
            "window": f"{ACCURACY_WINDOW_DAYS}d", "rules": rules_attr,
        }
        hass.data.setdefault(DOMAIN, {})[ACCURACY_HASS_KEY] = acc
        out["accuracy"] = acc
    except Exception:  # noqa: BLE001
        _LOGGER.warning("room rules accuracy roll-up failed", exc_info=True)

    if RULE_ZERO_FIRE_DAYS <= 0:
        return out
    try:
        since = (now - timedelta(days=RULE_ZERO_FIRE_DAYS)).isoformat()
        rows = await database.read_memory_episodes_by_type(
            ROOM_RULE_DECISION_EPISODE_TYPE, since)
        by_key: dict[str, dict] = {}
        for r in rows or []:
            a = r.get("attrs") or {}
            key = f"{r.get('node_id')}|{a.get('rule_id')}"
            b = by_key.setdefault(key, {"evaluations": 0, "fires": 0, "skips": {}})
            b["evaluations"] += 1
            outcome = str(a.get("outcome") or "")
            if outcome == "fired":
                b["fires"] += 1
            else:
                b["skips"][outcome] = b["skips"].get(outcome, 0) + 1
        from .domain_coordinators._stuck_signal_nm import fire_stuck_signal  # noqa: PLC0415
        from .rule_compiler import render_rule_preview  # noqa: PLC0415

        age_floor = now - timedelta(days=RULE_ZERO_FIRE_DAYS)
        for coord in room_rule_coordinators(hass):
            node = coord._rule_room_node()
            room = coord.entry.data.get(CONF_ROOM_NAME, "room")
            for rec in coord._room_rules():
                if not rec.get("enabled", True) or rec.get("needs_parse"):
                    continue
                if rec.get("trigger_type") in ROOM_RULE_SWITCH_EXEMPT_TRIGGERS:
                    continue
                created = _parse_ts(rec.get("created_at"))
                if created is not None and created > age_floor:
                    continue
                b = by_key.get(f"{node}|{rec.get('rule_id')}")
                if not b or b["evaluations"] < 1 or b["fires"] > 0:
                    continue
                top = sorted(b["skips"].items(), key=lambda kv: -kv[1])
                top_txt = f"{top[0][0]} ({top[0][1]})" if top else "none"
                sent = await fire_stuck_signal(
                    hass, "room_rule_silent", (room, rec.get("rule_id")),
                    diagnosis=(
                        f"Room rule in {room} ran 0 times in {RULE_ZERO_FIRE_DAYS} days "
                        f"although it was checked {b['evaluations']} times: "
                        f"\"{render_rule_preview(rec, hass, room)}\" Top skip: {top_txt}."
                    ),
                    remedy=(
                        "Read the 'Room rule decision' log lines and the room's "
                        "Room Rules Status sensor (rules attribute)."
                    ),
                    severity="HIGH",
                )
                out["paged"].append({"room": room, "rule_id": rec.get("rule_id"),
                                     "top_skip": top_txt, "sent": bool(sent)})
    except Exception:  # noqa: BLE001
        _LOGGER.warning("room rules trip-wire failed", exc_info=True)
    return out


def digest_section(hass: Any, *, now_ts: float | None = None) -> str:
    """One digest line (D6.4), "" when no rule was evaluated in 24 h and no
    rule needs a re-check. e.g. "Room rules, last 24 h: 9 ran, 2 skipped
    (person_absent), 1 undone by hand (Exercise Lamp). 1 rule needs a
    re-check." """
    now_ts = time.time() if now_ts is None else now_ts
    ran = 0
    skips: dict[str, int] = {}
    undone: list[str] = []
    needs = 0
    for coord in room_rule_coordinators(hass):
        for ts, _rid, outcome in list(getattr(coord, "_rule_recent", None) or []):
            if now_ts - ts > DIGEST_WINDOW_S:
                continue
            if outcome == "fired":
                ran += 1
            else:
                skips[outcome] = skips.get(outcome, 0) + 1
        for ts, _rid, eid in list(getattr(coord, "_rule_reversals_recent", None) or []):
            if now_ts - ts > DIGEST_WINDOW_S:
                continue
            name = eid
            try:
                st = hass.states.get(eid)
                if st is not None:
                    name = st.attributes.get("friendly_name", eid)
            except Exception:  # noqa: BLE001
                pass
            undone.append(str(name))
        try:
            needs += sum(1 for r in coord._room_rules()
                         if r.get("enabled", True) and r.get("needs_parse"))
        except Exception:  # noqa: BLE001
            pass
    skipped = sum(skips.values())
    if not (ran or skipped or undone or needs):
        return ""
    parts = [f"{ran} ran"]
    if skipped:
        top = ", ".join(k for k, _v in sorted(skips.items(), key=lambda kv: -kv[1])[:2])
        parts.append(f"{skipped} skipped ({top})")
    if undone:
        parts.append(f"{len(undone)} undone by hand ({', '.join(sorted(set(undone))[:3])})")
    line = "Room rules, last 24 h: " + ", ".join(parts) + "."
    if needs:
        line += f" {needs} rule{'s' if needs != 1 else ''} need{'s' if needs == 1 else ''} a re-check."
    return line
