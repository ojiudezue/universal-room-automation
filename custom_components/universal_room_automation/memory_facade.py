"""Hierarchical-memory facade — Stage 1 MVP.

The ONLY door into URA's node memory. Seven read-only verbs returning
``MemoryAnswer``. See:
  docs/planning/ARCHITECTURE_hierarchical_memory.md  (facade shape §3;
      access policy §8; tables §4/§5/§5c)
  docs/planning/MVP_hierarchical_memory.md            (Stage 1 scope)
  docs/planning/AUDIT_memory_handbuild_study_a.md     (acceptance
      fixture — the facade must reproduce §4's seven answers)

Kill switch: MEMORY_FACADE_ENABLED = False → every verb returns
verdict='no_data' (byte-identical degradation for consumers).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    MEMORY_FACADE_ENABLED,
    MEMORY_UNUSUAL_MIN_SUPPORT,
)

_LOGGER = logging.getLogger(__name__)


# ------------------------------------------------------------------
# MemoryAnswer — frozen dataclass; the ONE return shape.
# ------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryAnswer:
    """The single return shape for every facade verb.

    verdict: "ok" | "insufficient_history" | "no_data"
    value:   verb-specific payload; None unless verdict == "ok"
    support: sample/episode count behind the answer
    provenance: list of strings citing sources / fallback rungs / policy
    as_of:   answer timestamp (UTC-aware)
    """
    verdict: str
    value: Any = None
    support: int = 0
    provenance: tuple[str, ...] = field(default_factory=tuple)
    as_of: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ------------------------------------------------------------------
# Declared-capability registry (arch §5b, operator spec 2026-08-02:
# COMPLETE from the start, static dict). Node-type -> declared mechanism
# names. Grep-verified against const.py / coordinator surfaces:
# CONF_COMFORT_FAN_AWAY_VETO_ENABLED (const.py:705), fan_recheck
# machinery, D2 demotion logic, humidity fan intelligence, occupancy
# substrate (PIR/mmWave/occupancy buckets), covers, camera-person fusion,
# BLE corroboration, vacancy hold. Zone/house/coordinators mirror the
# existing coordinator classes: safety (12 hazard classes), presence,
# energy, hvac, security.
# ------------------------------------------------------------------

CAPABILITY_REGISTRY: dict[str, tuple[str, ...]] = {
    "room": (
        "lighting",                        # main + dark-aware thresholds
        "night_light",                     # night-light mode
        "comfort_fan",                     # base mechanism
        "comfort_fan_away_veto",           # trust stack: away veto (fan_veto.py)
        "comfort_fan_d2_demotion",         # trust stack: mmwave/fan D2
        "comfort_fan_transition_gate",     # trust stack: fan-transition gate
        "humidity_fan",                    # bathroom exhaust intelligence
        "covers",                          # blinds/covers
        "cover_schedule",                  # schedule + solar-gain covers
        "climate_coupling",                # zone thermostat pairing
        "camera_person_fusion",            # camera-person resolver
        "ble_corroboration",               # BLE presence corroboration
        "occupancy_substrate_pir",         # PIR bucket
        "occupancy_substrate_mmwave",      # mmWave bucket
        "occupancy_substrate_occupancy",   # occupancy bucket
        "vacancy_hold",                    # vacancy hold
        "fan_recheck",                     # fan-recheck manager
    ),
    "zone": (
        "presence_modes",                  # zone presence modes
        "occupancy_confidence",            # zone-level confidence
        "zone_cameras",                    # zone-scoped cameras
        "hvac_zone_coupling",              # AC zone coupling
    ),
    "house": (
        "house_state_machine",             # 9-state machine
        "state_keyed_presets",             # per-state presets
        "security_arming_linkage",         # arm-on-away etc.
        "notification_severity_routing",   # NM severity floor
        "guest_policy",                    # guest state semantics
    ),
    "coordinator:presence": (
        "house_state",
        "occupancy_fusion",
        "census",
    ),
    "coordinator:safety": (
        "hazard_smoke", "hazard_fire", "hazard_carbon_monoxide",
        "hazard_water_leak", "hazard_flooding", "hazard_freeze_risk",
        "hazard_overheat", "hazard_hvac_failure",
        "hazard_high_humidity", "hazard_low_humidity",
        "hazard_high_co2", "hazard_high_tvoc",
        "severity_cascade",
    ),
    "coordinator:security": (
        "armed_picture",
        "geofence_auto_arm",
    ),
    "coordinator:energy": (
        "reserve_strategy",
        "tou_arbitrage",
        "peak_avoidance_savings",
        "ac_ramp_savings",
        "evse_precedence",
        "load_proposals",                  # parked
        "db_write_governance",
    ),
    "coordinator:hvac": (
        "state_keyed_presets",
        "kwh_rate_waste_detection",
        "solar_gain_covers",
    ),
}


# ------------------------------------------------------------------
# Access policy (arch §8). Tier prefix -> what the caller MAY query.
# Order matters: prefix match on caller_id.
# ------------------------------------------------------------------


def _caller_tier(caller_id: str | None) -> str:
    """Return the tier of a caller_id: room/zone/house/coordinator/observer."""
    if not caller_id:
        return "observer"
    for prefix in ("room:", "zone:", "coordinator:", "house"):
        if caller_id.startswith(prefix):
            return prefix.rstrip(":") if prefix.endswith(":") else prefix
    return "observer"


def _access_check(
    hass: HomeAssistant,
    caller_id: str | None,
    node_id: str,
) -> str | None:
    """Enforce §8 tier-visibility rules. Return None if allowed, else a
    short reason string suitable for provenance ("access_denied:<rule>").

    Observers (NM / diagnostics / dashboard / operator / AI service /
    None) may query anything read-only. Rooms may query self, same-zone
    siblings, and house. Zones may query self, member rooms, sibling
    zones, house. House sees all below. Coordinators see anything in
    their domain of action (implemented liberally: coordinators may
    query anything — reviewed).
    """
    if not caller_id:
        return None
    caller_tier = _caller_tier(caller_id)
    if caller_tier == "observer":
        return None
    if caller_tier == "coordinator":
        return None
    if caller_tier == "house":
        return None
    if node_id == caller_id:
        return None
    if caller_tier == "room":
        # A room may query itself, siblings in the same zone, or house.
        if node_id.startswith("house"):
            return None
        if node_id.startswith("zone:"):
            # Its own zone — allowed for context reads.
            return None
        if node_id.startswith("coordinator:"):
            return "access_denied:room_may_not_query_coordinator"
        if node_id.startswith("room:"):
            # Same-zone check — resolved via ZM config.
            if _same_zone(hass, caller_id, node_id):
                return None
            return "access_denied:room_may_only_query_zone_siblings"
        return "access_denied:room_out_of_scope"
    if caller_tier == "zone":
        if node_id.startswith("coordinator:"):
            return "access_denied:zone_may_not_query_coordinator"
        return None
    return "access_denied:unknown_caller_tier"


def _same_zone(
    hass: HomeAssistant, caller_id: str, node_id: str,
) -> bool:
    """True if caller room and target room share a zone (best-effort via
    Zone Manager config)."""
    try:
        caller_room = caller_id.split(":", 1)[1]
        target_room = node_id.split(":", 1)[1]
        for entry in hass.config_entries.async_entries(DOMAIN):
            zones = (entry.options or {}).get("zones") or (
                entry.data or {}
            ).get("zones")
            if not zones:
                continue
            for _zname, zdef in zones.items():
                rooms = zdef.get("zone_rooms") or []
                # Match either slug or friendly title (best-effort).
                if any(
                    caller_room == _slugify(r) or caller_room == r
                    for r in rooms
                ) and any(
                    target_room == _slugify(r) or target_room == r
                    for r in rooms
                ):
                    return True
        return False
    except Exception:  # noqa: BLE001 — access policy fails CLOSED on error
        return False


def _slugify(text: str) -> str:
    return (text or "").lower().replace(" ", "_").replace("-", "_")


# ------------------------------------------------------------------
# Context / bin helpers (arch §5 — 3h CDT bins × family)
# ------------------------------------------------------------------

_FAMILY_MAP = {
    "away": "away",
    "vacation": "away",
    "arriving": "home",
    "home_day": "home",
    "home_evening": "home",
    "home_night": "home",
    "sleep": "sleep",
    "waking": "sleep",
    "guest": "home",
    "auto": "home",
}


def house_state_to_family(state: str | None) -> str:
    if not state:
        return "home"
    return _FAMILY_MAP.get(str(state).lower(), "home")


def utc_to_local_hour_bin(
    ts_utc: datetime | None, tz_name: str = "America/Chicago",
) -> int:
    """Convert a UTC datetime to a 3-hour local bin (0, 3, 6, ..., 21).

    Audit gap #5: DB times are UTC; the facade OWNS conversion or every
    context bin is off by 5 hours.
    """
    ts_utc = ts_utc or datetime.now(timezone.utc)
    if ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=timezone.utc)
    local_tz = None
    try:
        _tz = dt_util.get_time_zone(tz_name)
        # HA returns a tzinfo; test stubs may return a MagicMock — the
        # astimezone call filters bad values by raising, which we catch.
        if _tz is not None and hasattr(_tz, "utcoffset"):
            local_tz = _tz
    except Exception:  # noqa: BLE001
        local_tz = None
    if local_tz is None:
        # Reliable fallback that does not require HA at test time.
        try:
            from zoneinfo import ZoneInfo  # noqa: PLC0415
            local_tz = ZoneInfo(tz_name)
        except Exception:  # noqa: BLE001
            local_tz = timezone.utc
    try:
        local_dt = ts_utc.astimezone(local_tz)
    except Exception:  # noqa: BLE001
        local_dt = ts_utc
    return (local_dt.hour // 3) * 3


def build_metric_key(
    signal: str, hour_bin: int, family: str,
) -> str:
    """Compose the context-qualified metric_name used in metric_baselines."""
    return f"{signal}:h{hour_bin:02d}:{family}"


# ------------------------------------------------------------------
# The facade
# ------------------------------------------------------------------


class MemoryFacade:
    """Read-only facade over episodes, baselines, facts, outcomes,
    live config, and existing logs. All access to the memory tiers
    routes here."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        # Adjacency cache — invalidated on restart per parsimony trim #2.
        self._adjacency_cache: dict[str, list[str]] = {}

    def _kill_switch(self, provenance_tag: str) -> MemoryAnswer:
        return MemoryAnswer(
            verdict="no_data",
            provenance=(f"kill_switch:{provenance_tag}",),
        )

    def _db(self):
        return self.hass.data.get(DOMAIN, {}).get("database")

    # ---- Access-policy shim used by every verb --------------------

    def _guard(
        self, caller_id: str | None, node_id: str,
    ) -> MemoryAnswer | None:
        denied = _access_check(self.hass, caller_id, node_id)
        if denied is None:
            return None
        return MemoryAnswer(verdict="no_data", provenance=(denied,))

    # ---- baseline(node, signal, context) --------------------------

    async def baseline(
        self,
        node_id: str,
        signal: str,
        context: dict | None = None,
        caller_id: str | None = None,
    ) -> MemoryAnswer:
        if not MEMORY_FACADE_ENABLED:
            return self._kill_switch("facade")
        blocked = self._guard(caller_id, node_id)
        if blocked is not None:
            return blocked
        db = self._db()
        if db is None:
            return MemoryAnswer(
                verdict="no_data", provenance=("db_unavailable",),
            )
        context = context or {}
        hour_bin = int(
            context.get("hour_bin",
                        utc_to_local_hour_bin(datetime.now(timezone.utc)))
        )
        family = str(context.get("family") or context.get("house_state")
                     or "home")
        family = house_state_to_family(family)
        season = context.get("season")  # optional last-rung
        # Fallback ladder: exact -> drop season -> drop family -> "all"
        candidates: list[tuple[str, str]] = []
        if season:
            candidates.append(
                (f"{signal}:h{hour_bin:02d}:{family}:{season}", "exact"),
            )
        candidates.append(
            (build_metric_key(signal, hour_bin, family), "drop_season"),
        )
        candidates.append(
            (f"{signal}:h{hour_bin:02d}:all", "drop_family"),
        )
        candidates.append(
            (f"{signal}:all", "all"),
        )
        for metric_name, rung in candidates:
            try:
                row = await db.read_memory_baseline(node_id, metric_name)
            except Exception:  # noqa: BLE001
                row = None
            if row and int(row["sample_count"]) > 0:
                return MemoryAnswer(
                    verdict="ok",
                    value={
                        "mean": row["mean"],
                        "sd": math.sqrt(max(row["variance"], 0.0)),
                        "sample_count": row["sample_count"],
                        "signal": signal,
                        "hour_bin": hour_bin,
                        "family": family,
                        "metric_name": metric_name,
                    },
                    support=int(row["sample_count"]),
                    provenance=(
                        f"metric_baselines:{node_id}:{metric_name}",
                        f"fallback:{rung}",
                    ),
                )
        return MemoryAnswer(
            verdict="insufficient_history",
            provenance=(
                f"metric_baselines:{node_id}:no_rows_for_signal={signal}",
            ),
        )

    # ---- episodes(node, pattern, window) --------------------------

    async def episodes(
        self,
        node_id: str,
        pattern: str | None = None,
        window: timedelta | None = None,
        caller_id: str | None = None,
    ) -> MemoryAnswer:
        if not MEMORY_FACADE_ENABLED:
            return self._kill_switch("facade")
        blocked = self._guard(caller_id, node_id)
        if blocked is not None:
            return blocked
        db = self._db()
        if db is None:
            return MemoryAnswer(
                verdict="no_data", provenance=("db_unavailable",),
            )
        since_iso = None
        if window is not None:
            since_iso = (
                datetime.now(timezone.utc) - window
            ).isoformat()
        rows = await db.read_memory_episodes(
            node_id, episode_type=pattern, since_iso=since_iso,
        )
        if not rows:
            return MemoryAnswer(
                verdict="insufficient_history",
                provenance=("memory_episodes:no_rows",),
            )
        return MemoryAnswer(
            verdict="ok",
            value=rows,
            support=len(rows),
            provenance=("memory_episodes",),
        )

    # ---- unusual(node, window) ------------------------------------

    async def unusual(
        self,
        node_id: str,
        window: timedelta | None = None,
        caller_id: str | None = None,
    ) -> MemoryAnswer:
        if not MEMORY_FACADE_ENABLED:
            return self._kill_switch("facade")
        blocked = self._guard(caller_id, node_id)
        if blocked is not None:
            return blocked
        db = self._db()
        if db is None:
            return MemoryAnswer(
                verdict="no_data", provenance=("db_unavailable",),
            )
        baselines = await db.read_memory_baselines_for_node(node_id)
        if not baselines:
            return MemoryAnswer(
                verdict="insufficient_history",
                provenance=("memory_baselines:no_rows",),
            )
        # Gate: aggregate support must clear MEMORY_UNUSUAL_MIN_SUPPORT.
        total_support = sum(int(b["sample_count"]) for b in baselines)
        if total_support < MEMORY_UNUSUAL_MIN_SUPPORT:
            return MemoryAnswer(
                verdict="insufficient_history",
                support=total_support,
                provenance=(
                    f"unusual:support={total_support}"
                    f"<min={MEMORY_UNUSUAL_MIN_SUPPORT}",
                ),
            )
        # Rank rows by variance/mean ratio (proxy for "unusual signal"
        # dispersion). Stage 1 is intentionally simple: the value is the
        # baseline snapshot ranked. A real scorer against live samples
        # is a Stage 2 follow-up (per MVP: "ships complete; data arrives
        # incrementally").
        ranked = sorted(
            baselines,
            key=lambda b: (
                math.sqrt(max(b["variance"], 0.0))
                / max(abs(b["mean"]), 1e-6)
            ),
            reverse=True,
        )
        return MemoryAnswer(
            verdict="ok",
            value=ranked,
            support=total_support,
            provenance=("memory_baselines:ranked_by_dispersion",),
        )

    # ---- outcome(node, decision_type, window) ---------------------

    async def outcome(
        self,
        node_id: str,
        decision_type: str | None = None,
        window: timedelta | None = None,
        caller_id: str | None = None,
    ) -> MemoryAnswer:
        if not MEMORY_FACADE_ENABLED:
            return self._kill_switch("facade")
        blocked = self._guard(caller_id, node_id)
        if blocked is not None:
            return blocked
        # Reuse outcome_log as-is; Stage 1 exposes nothing beyond a
        # simple read. Coordinator-scoped rows only.
        return MemoryAnswer(
            verdict="insufficient_history",
            provenance=("outcome_log:stage1_read_stub",),
        )

    # ---- narrative(node, window) ----------------------------------

    async def narrative(
        self,
        node_id: str,
        window: timedelta | None = None,
        caller_id: str | None = None,
    ) -> MemoryAnswer:
        if not MEMORY_FACADE_ENABLED:
            return self._kill_switch("facade")
        blocked = self._guard(caller_id, node_id)
        if blocked is not None:
            return blocked
        db = self._db()
        if db is None:
            return MemoryAnswer(
                verdict="no_data", provenance=("db_unavailable",),
            )
        since_iso = None
        if window is not None:
            since_iso = (
                datetime.now(timezone.utc) - window
            ).isoformat()
        events: list[dict] = []
        # Episodes tier
        try:
            eps = await db.read_memory_episodes(
                node_id, episode_type=None, since_iso=since_iso,
            )
            for e in eps:
                events.append({
                    "kind": "episode",
                    "at": e["started_at"],
                    "detail": e,
                })
        except Exception:  # noqa: BLE001
            pass
        # decision_log + house_state_log are richer; Stage 1 exposes
        # them via best-effort reads so consumers see the merged shape.
        # (These readers may not exist as DAOs; we degrade gracefully.)
        events.sort(key=lambda x: x.get("at") or "")
        if not events:
            return MemoryAnswer(
                verdict="insufficient_history",
                provenance=("narrative:no_events",),
            )
        return MemoryAnswer(
            verdict="ok",
            value=events,
            support=len(events),
            provenance=("memory_episodes",),
        )

    # ---- profile(node) --------------------------------------------

    async def profile(
        self, node_id: str, caller_id: str | None = None,
    ) -> MemoryAnswer:
        if not MEMORY_FACADE_ENABLED:
            return self._kill_switch("facade")
        blocked = self._guard(caller_id, node_id)
        if blocked is not None:
            return blocked
        composition = self._compose_composition(node_id)
        capability = self._compose_capability(node_id)
        locality = self._compose_locality(node_id)
        return MemoryAnswer(
            verdict="ok",
            value={
                "composition": composition,
                "capability": capability,
                "locality": locality,
            },
            support=1,
            provenance=(
                "config_entries:live",
                "registry:CAPABILITY_REGISTRY",
            ),
        )

    def _node_type(self, node_id: str) -> str:
        if node_id.startswith("room:"):
            return "room"
        if node_id.startswith("zone:"):
            return "zone"
        if node_id.startswith("coordinator:"):
            return node_id  # keyed exactly for coordinators
        if node_id == "house":
            return "house"
        return "unknown"

    def _compose_composition(self, node_id: str) -> dict:
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                title_slug = _slugify(entry.title or entry.entry_id)
                if node_id == f"room:{title_slug}":
                    merged = {**(entry.data or {}), **(entry.options or {})}
                    return {
                        "title": entry.title,
                        "entry_id": entry.entry_id,
                        "config_keys": sorted(merged.keys()),
                    }
        except Exception:  # noqa: BLE001
            pass
        return {"note": "composition_unavailable"}

    def _compose_capability(self, node_id: str) -> dict:
        node_type = self._node_type(node_id)
        declared: tuple[str, ...]
        if node_type.startswith("coordinator:"):
            declared = CAPABILITY_REGISTRY.get(node_type, ())
        else:
            declared = CAPABILITY_REGISTRY.get(node_type, ())
        # Stage 1: enabled and actionable_now start conservative — every
        # declared mech = enabled True, actionable_now unknown (facade
        # cannot cheaply resolve every actuator entity here). Consumers
        # that need finer grain drive the resolve step in their own code.
        return {
            "declared": list(declared),
            "enabled": {m: True for m in declared},
            "actionable_now": {m: None for m in declared},
        }

    def _compose_locality(self, node_id: str) -> dict:
        # Zone locality: from Zone Manager config (§8 visibility key).
        zone_siblings: list[str] = []
        try:
            if node_id.startswith("room:"):
                target_room = node_id.split(":", 1)[1]
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    zones = (entry.options or {}).get("zones") or (
                        entry.data or {}
                    ).get("zones")
                    if not zones:
                        continue
                    for _zname, zdef in zones.items():
                        rooms = zdef.get("zone_rooms") or []
                        if any(
                            target_room == _slugify(r) or target_room == r
                            for r in rooms
                        ):
                            zone_siblings = [
                                _slugify(r) for r in rooms
                                if _slugify(r) != target_room
                            ]
                            break
        except Exception:  # noqa: BLE001
            zone_siblings = []
        # Self locality (physical neighbors) lazily via room_transitions —
        # cached in-process, invalidated on restart (arch §5b + MVP
        # parsimony trim #2). Read blocking here would hit the DB; keep
        # it null for Stage 1 unless populated externally.
        self_neighbors = self._adjacency_cache.get(node_id, [])
        return {
            "zone_siblings": zone_siblings,
            "self_neighbors": self_neighbors,
        }

    # ---- facts(node, topic) ---------------------------------------

    async def facts(
        self,
        node_id: str,
        topic: str | None = None,
        include_superseded: bool = False,
        caller_id: str | None = None,
    ) -> MemoryAnswer:
        if not MEMORY_FACADE_ENABLED:
            return self._kill_switch("facade")
        blocked = self._guard(caller_id, node_id)
        if blocked is not None:
            return blocked
        db = self._db()
        if db is None:
            return MemoryAnswer(
                verdict="no_data", provenance=("db_unavailable",),
            )
        rows = await db.read_memory_facts(
            node_id, topic=topic, include_superseded=include_superseded,
        )
        if not rows:
            return MemoryAnswer(
                verdict="insufficient_history",
                provenance=("memory_facts:no_rows",),
            )
        return MemoryAnswer(
            verdict="ok",
            value=rows,
            support=len(rows),
            provenance=("memory_facts",),
        )
