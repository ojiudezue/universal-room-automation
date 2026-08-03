"""Presence Coordinator — house state inference and zone presence tracking.

Subscribes to Census updates, room occupancy sensors, BLE person tracking,
and zone camera detection. Infers house state via StateInferenceEngine.
Publishes SIGNAL_HOUSE_STATE_CHANGED.

v3.6.0-c1: Initial implementation with 3-tier zone presence signals.

Signal tiers for zone presence (any one sufficient for 'occupied'):
  1. Room occupancy sensors (mmWave/PIR) — via entity registry area_id
  2. Zone camera person/motion detection — via CameraIntegrationManager
  3. Bermuda BLE person location — via person_coordinator

Camera integration hardened from camera_census.py lessons:
  - Entity availability guards (unavailable/unknown states)
  - Entity registry for camera discovery (not substring matching)
  - Graceful degradation when sensors go offline
  - Camera detection timeout (person seen → zone occupied for N seconds)
  - try/except around all state reads
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ..const import (
    BLE_TIER_2_WEIGHT,  # v4.7.16 D3
    BOOT_SETTLE_MIN_INPUTS,  # boot-settle gate
    BOOT_SETTLE_TIMEOUT_SECONDS,  # boot-settle gate
    CONF_AREA_ID,
    CONF_DISABLE_CAMERA_PRESENCE,  # v4.7.16 D4
    CONF_ENTRY_TYPE,  # v4.7.16 D3, D4
    CONF_FANS,  # provenance-split cycle: D3 fan-interference diagnostic
    CONF_MMWAVE_SENSORS,  # provenance-split cycle: D2 classifier
    CONF_MOTION_SENSORS,  # provenance-split cycle: D2 classifier
    CONF_OCCUPANCY_SENSORS,  # provenance-split cycle: D2 classifier
    CONF_ROOM_NAME,  # provenance-split cycle: D2 classifier
    CONF_ZONE_IS_OUTDOOR,  # v5.7.0 WS-A4 outdoor-zone exclusion
    CONF_ZONE_ROOMS,
    D3_DIAGNOSTIC_ENABLED,  # v4.7.16 D3 (post-review B MED #1) — kill switch
    DEFAULT_DISABLE_CAMERA_PRESENCE,  # v4.7.16 D4
    DEFAULT_LOST_AWAY_GRACE_MIN,  # v5.7.0 WS-A3
    DEFAULT_LOST_AWAY_INDOOR_CLEAR_TICKS,  # v5.7.0 fix-up FIX-2b
    DEFAULT_LOST_AWAY_SLEEP_EXEMPT,  # v5.7.0 WS-A3
    DEFAULT_ZONE_IS_OUTDOOR,  # v5.7.0 WS-A4
    DIAGNOSTICS_SCOPE_HOUSE,
    DOMAIN,
    CONF_LOST_AWAY_GRACE_MIN,  # v5.7.0 WS-A3
    CONF_LOST_AWAY_INDOOR_CLEAR_TICKS,  # v5.7.0 fix-up FIX-2b
    CONF_LOST_AWAY_SLEEP_EXEMPT,  # v5.7.0 WS-A3
    ENTRY_TYPE_ROOM,  # v4.7.16 D3, D4
    TIER1_KINDS,  # provenance-split cycle: D2 vocabulary
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_LOST,  # v5.7.0 WS-A1
    TRACKING_STATUS_STALE,  # v5.7.0 WS-A1
)
from .base import BaseCoordinator, CoordinatorAction, Intent
from .coordinator_diagnostics import (
    AnomalyDetector,
    DecisionLog,
)
from .house_state import HouseState, HouseStateMachine
from .signals import (
    SIGNAL_CENSUS_UPDATED,
    SIGNAL_FAN_INTERFERENCE_GATE_FIRED,
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_OPTIMIZER_INTENT,
    SIGNAL_OPTIMIZER_INTENT_VETO,
    SIGNAL_PERSON_ARRIVING,
    SIGNAL_PRESENCE_ENTITIES_UPDATE,
    SIGNAL_ZM_ZONES_UPDATED,
)
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)

_LOGGER = logging.getLogger(__name__)

# Camera detection timeout: after person/motion goes off, zone stays occupied
# for this duration before reverting to away. Prevents flapping.
_CAMERA_OCCUPANCY_TIMEOUT_SECONDS = 300  # 5 minutes

# States that mean an entity is not providing real data
_UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})

# v4.6.5.1 P2: Module-level suppression registry for presence. Companion to
# PresenceCoordinator.PRESENCE_METRICS (defined as a class attribute on the
# coordinator). Every metric in PRESENCE_METRICS must be EITHER wired (have
# a record_observation call in this file with a downstream store_event +
# activity_logger.log emit) OR listed here with a comment explaining why.
# Introspected by the parametric meta-test in test_v465_observability_gap.py.
#
# Reasons each entry is suppressed:
# - census_count (suppressed in v4.6.3.3): low-cardinality int 0..N, mostly
#   0 during sleep/away. Z-score persistence produced 1825 anomaly_log
#   emits in 24h on the live system. record_observation kept for in-memory
#   anomaly counter; persistence (store_event + activity_logger.log) stripped.
# - zone_occupied_count (suppressed in v4.6.3.1): binary 0/1 per zone per
#   inference cycle. Z-score on binary input is degenerate — rarely-occupied
#   zones produce z >= 4 on every "occupied=1.0" tick. Produced 2117 emits
#   in 3h post-v4.6.3 deploy. Same treatment as census_count.
PRESENCE_SUPPRESSED_FROM_PERSISTENCE: frozenset[str] = frozenset({
    "census_count",
    "zone_occupied_count",
})


# ============================================================================
# v4.7.15 D1: Bug Class #48 shared veto helper — types
# ============================================================================
#
# The helper unifies the trust-hierarchy pattern shipped ad-hoc in v4.7.13
# (zone aggregator, scope="zone_aggregator" SLEEP) and v4.7.14 (house
# inference, scope="house_inference" AWAY). Future cycles plug additional
# patterns by extending should_veto_due_to_reliable_signals() — no new files,
# no callable proliferation.
#
# Conservative bias is preserved: the default fall-through returns fired=False,
# so adding a new caller without a matching pattern is a no-op.

# v4.7.15 D2 / D3: thresholds shared by helper patterns. Module-level so tests
# and operator tuning can introspect them without instantiating a coordinator.
_NONSLEEP_QUIET_THRESHOLD_SECONDS = 300  # 5 min — bridge structural degeneration
_WAKING_SUSTAINED_THRESHOLD_SECONDS = 90  # ≥3 Frigate confirmations at 15-30s cadence
# v4.7.18.1 D2: Daytime wake backstop margin. If the house remains SLEEP past
# `sleep_end_hour + _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END` while census_count>0,
# the WAKING gate falls through (forces wake) even if sustained signal is
# insufficient. Safety valve against any future masking regression that could
# re-trap the house in SLEEP all day.
_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END = 3

# v4.7.15.1 fix-up B2-M1 (Reviewer B): Pattern A helper fails CONSERVATIVE
# (no veto) when the per-person phone-trust / tracking-active parallel-list
# lengths disagree. The prior code emitted no log — an operator debugging a
# future caller-contract drift would have no signal. One-shot WARN-per-
# process so journald does not flood on a stable misalignment.
_LENGTH_MISMATCH_WARNED = False

# B-2026-08-03-2: Arriving re-arm cooldown. After an ARRIVING attempt collapses
# back to AWAY (deferred_retry / next-tick "no one is home" verdict) we suppress
# a fresh AWAY→ARRIVING transition for this window UNLESS the new evidence
# includes any of:
#   - interior tier1 occupancy (any_indoor_zone_occupied True), OR
#   - camera / egress evidence (census_count > 0), OR
#   - a tracked person state change toward home (any tracked person no longer
#     reported "away" — approximation via not all_tracked_persons_away with
#     tracked_count>0).
# Kill-switch: 0 disables the cooldown (pre-fix behavior).
# Rung-1 constant per Numbers-Get-Knobs: tunable only via reviewed code change;
# not exposed as an operator knob. 2026-08-03 patio-flap incident: 15 outdoor-
# only ARRIVING attempts in 3h, each lasting ~61s.
ARRIVING_REARM_COOLDOWN_S = 900


def _tracking_active_or_lost_away(info: dict) -> bool:
    """v5.7.0 WS-A1: relaxed sibling of the H3 ACTIVE-only filter.

    True iff ``tracking_status == ACTIVE``, OR
    ``(tracking_status in {LOST, STALE} AND location == "away")``.

    Used ONLY by the path-β denominator computation in
    ``PresenceCoordinator._run_inference``. The H2 phone_left_behind
    filter is still applied separately — a left-behind phone must NOT
    count as away regardless of tracking_status. The LOST/STALE-home
    case stays UNTRUSTED (a dead phone sitting at home tells us nothing
    about whether the person is here).

    Defined at module level (not as a closure inside `_run_inference`)
    so the Tier-3 review C mutation-anchor tests can import and exercise
    the REAL load-bearing site.
    """
    ts = info.get("tracking_status", TRACKING_STATUS_ACTIVE)
    if ts == TRACKING_STATUS_ACTIVE:
        return True
    if ts in (TRACKING_STATUS_LOST, TRACKING_STATUS_STALE):
        return (info.get("location") or "").lower() == "away"
    return False


@dataclass(frozen=True)
class ReliableSignal:
    """A reliable, persistent presence signal (person tracker, BLE, zone_persons).

    kind: one of "person_tracker_away", "person_tracker_home",
          "zone_persons_home", "ble_proximity_present", "ble_proximity_absent".
    value: truthiness of the signal at evaluation time.
    """

    kind: str
    value: bool


@dataclass(frozen=True)
class TransientSignal:
    """A transient presence signal (camera burst, mmWave bounce, PIR).

    kind: one of "camera_person_detected", "mmwave_occupied", "pir_motion",
          "unidentified_person_count".
    count: numeric quantity (1/0 for boolean signals, N for unidentified).
    """

    kind: str
    count: int


@dataclass(frozen=True)
class VetoDecision:
    """Result of a Bug Class #48 transient-vs-reliable arbitration.

    fired: True iff the reliable signal vetoed the transient evidence.
    confidence: 0.0-1.0 confidence in the vetoed conclusion (only meaningful
                when fired=True). Mirrors the 1.0=good / 0.0=bad scale used
                by inference_engine.confidence and signal_consensus.
    reason: Short human-readable reason for activity-log + diagnostics.
            Empty string when fired=False.
    scope: The state_context scope the decision was evaluated against.
           Empty string when no scope was provided.
    """

    fired: bool
    confidence: float
    reason: str
    scope: str = ""


# ============================================================================
# Zone Presence
# ============================================================================


class ZonePresenceMode:
    """Zone presence mode constants."""

    AWAY = "away"
    OCCUPIED = "occupied"
    SLEEP = "sleep"
    UNKNOWN = "unknown"
    AUTO = "auto"  # Used in select entity to mean "clear override"

    ALL_MODES = [AWAY, OCCUPIED, SLEEP, UNKNOWN]
    OVERRIDE_OPTIONS = [AUTO, AWAY, OCCUPIED, SLEEP]


# ============================================================================
# Presence provenance-split cycle: D2 entity-kind classifier
# ============================================================================
#
# The zone tracker today discovers Tier-1 binary_sensors by `area_id`
# (presence.py:1442-1476). It does NOT consult per-room CONF_*_SENSORS
# lists. The D2 split needs a per-kind classification of every firing
# entity. This module-level helper performs that classification with a
# two-step strategy:
#
#   1) Look up the firing entity_id in the owning room ConfigEntry's
#      CONF_MMWAVE_SENSORS / CONF_MOTION_SENSORS / CONF_OCCUPANCY_SENSORS
#      lists, in that priority order. First match wins.
#   2) If the entry cannot be resolved or the entity is not in any list,
#      fall back to entity_id substring matching using the same vocabulary
#      the zone tracker already trusts for discovery (presence.py:1460):
#      "mmwave"/"presence" → mmwave, "motion" → motion, else "occupancy".
#
# CRITICAL invariant: this function is the SINGLE classification source
# for BOTH the seed loop and the live state-change callback. The
# seed-vs-live divergence hazard is the v4.7.18.1 review finding
# B-HIGH-1 (NOT QUALITY_CONTEXT.md "Bug Class #1" — that class is
# "Coordinator Lifecycle Confusion", a different concern). Both call
# sites MUST invoke this same function for byte-equal classification.
#
# Returns one of the TIER1_KINDS strings ("motion", "mmwave", "occupancy").

def _classify_entity_kind(
    hass: HomeAssistant, entity_id: str, room_name: str
) -> str:
    """Classify a firing Tier-1 entity to a kind ∈ TIER1_KINDS.

    See module-level comment block above for the strategy.

    Args:
        hass: HomeAssistant instance (used to read room entry config).
        entity_id: The firing binary_sensor entity_id.
        room_name: The owning URA room's CONF_ROOM_NAME.

    Returns:
        One of "motion", "mmwave", "occupancy".
    """
    # Step 1 — config-list lookup.
    try:
        for entry in hass.config_entries.async_entries(DOMAIN):
            # B-LOW-3 review fix-up: merge data + options for the
            # entry-type and room-name checks too — not just the sensor
            # lists below. Options is the canonical post-flow surface,
            # and mirroring the same merge pattern as the fan-discovery
            # path at presence.py:1443 keeps the classifier consistent
            # if a future options flow ever lets the operator edit
            # CONF_ROOM_NAME or CONF_ENTRY_TYPE.
            merged = {**(entry.data or {}), **(entry.options or {})}
            if merged.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            if merged.get(CONF_ROOM_NAME) != room_name:
                continue
            # Sensor lists also from the merge (options wins).
            mmwave = list(merged.get(CONF_MMWAVE_SENSORS, []) or [])
            motion = list(merged.get(CONF_MOTION_SENSORS, []) or [])
            occ = list(merged.get(CONF_OCCUPANCY_SENSORS, []) or [])
            if entity_id in mmwave:
                return "mmwave"
            if entity_id in motion:
                return "motion"
            if entity_id in occ:
                return "occupancy"
            # Right entry found, no list-membership — fall through to substring.
            break
    except Exception:  # noqa: BLE001 — defensive: config registry mid-reload
        _LOGGER.debug(
            "Tier-1 kind classifier: config-lookup failed for %s/%s — using fallback",
            entity_id, room_name,
            exc_info=True,
        )

    # Step 2 — substring fallback matching the discovery filter at :1460.
    # Occupancy substrate unification cycle: this fallback is RETAINED
    # for non-CONF-listed sensors (defensive — should not fire for a
    # properly-configured room post-substrate). WARN-log when it does
    # fire to surface configuration gaps, per planning doc D2.
    eid = entity_id.lower()
    _LOGGER.warning(
        "Substrate-cycle: _classify_entity_kind substring fallback fired "
        "for %s in room '%s' — entity is NOT in CONF_MOTION_SENSORS / "
        "CONF_MMWAVE_SENSORS / CONF_OCCUPANCY_SENSORS for that room. "
        "Add it to the appropriate CONF list to remove the substring-"
        "classification path.",
        entity_id, room_name,
    )
    if "mmwave" in eid or "presence" in eid:
        return "mmwave"
    if "motion" in eid:
        return "motion"
    return "occupancy"


def _audit_provenance_invariants(tracker: "ZonePresenceTracker") -> list[str]:
    """Return a list of invariant-violation strings; empty list = clean.

    Read-only diagnostic per AUDIT_presence_provenance.md. Walks the
    tracker's `_room_provenance` store and verifies four invariants:

      1) For every room r, ``_room_occupied[r] == any(_room_provenance[r].values())``.
      2) Every kind in ``_room_provenance[r]`` is in :data:`TIER1_KINDS` (or
         the legacy "tier1" sentinel slot used by the back-compat path).
      3) ``raw_occupied`` composes through ``_derived_mode`` without raise.
      4) ``set(_room_provenance.keys()) == set(_room_occupied.keys())``.

    Used by:
      - ``quality/tests/test_presence_provenance_split.py::test_invariants_hold_after_inference``
      - A future diagnostic surface (not in this cycle).
    """
    violations: list[str] = []
    legacy_sentinel = "tier1"
    prov = getattr(tracker, "_room_provenance", None)
    if not isinstance(prov, dict):
        return ["tracker has no _room_provenance dict"]
    # Invariant 2 first (shape check) — must run before iterating values.
    for room, kinds in prov.items():
        if not isinstance(kinds, dict):
            violations.append(
                f"room '{room}' provenance is not a dict (got {type(kinds).__name__})"
            )
            continue
        for k in kinds.keys():
            if k not in TIER1_KINDS and k != legacy_sentinel:
                violations.append(
                    f"room '{room}' has unknown kind '{k}' "
                    f"(allowed: {list(TIER1_KINDS) + [legacy_sentinel]})"
                )
    # If any room had a non-dict shape, _room_occupied property will
    # raise; skip the cross-property checks so we still return useful
    # diagnostics.
    if any(not isinstance(v, dict) for v in prov.values()):
        return violations
    try:
        occ = tracker._room_occupied  # property
        # Invariant 4: key-set equality.
        if set(prov.keys()) != set(occ.keys()):
            violations.append(
                f"key-set mismatch: provenance={sorted(prov.keys())} "
                f"occupied={sorted(occ.keys())}"
            )
        # Invariant 1 (RELAXED for fan-noise mitigation D1): the derived
        # view is `any(provenance.values()) OR hold-active`. The hold
        # can only EXTEND occupancy (the truth-preserving invariant),
        # never shorten it. Violation cases:
        #   * provenance says True but derived says False — always bad.
        #   * provenance says False AND derived says True AND there is
        #     NO active hold for the room — also bad.
        # The pre-D1 strict-equality form would mis-fire on every
        # legitimate hold-extension, so the audit is widened to allow
        # "derived broader because of an active hold."
        # B-M3 fix-up: if either getattr() or dt_util.utcnow() raises
        # (catastrophic, but we don't want the audit to fabricate a
        # false-positive flood by flagging every hold-extended room as
        # a violation), bail out of Invariant 1 with a single diagnostic
        # entry instead. The other invariants below still run.
        hold: Dict[str, Any] = {}
        now = None
        skip_invariant_1 = False
        try:
            hold = getattr(tracker, "_fan_interference_hold_until", {}) or {}
            now = dt_util.utcnow()
        except Exception as exc:  # noqa: BLE001 — defensive
            violations.append(
                f"audit cannot run Invariant 1: hold/clock read raised "
                f"{type(exc).__name__}: {exc!r}"
            )
            skip_invariant_1 = True
        if not skip_invariant_1:
            for room, kinds in prov.items():
                expected = any(bool(v) for v in kinds.values())
                actual = bool(occ.get(room, False))
                if expected and not actual:
                    violations.append(
                        f"room '{room}' _room_occupied=False but "
                        f"any(_room_provenance)=True (truth-preserving "
                        f"invariant violated — hold cannot shorten "
                        f"occupancy)"
                    )
                elif not expected and actual:
                    hold_until = hold.get(room)
                    hold_active = (
                        hold_until is not None
                        and now is not None
                        and hold_until > now
                    )
                    if not hold_active:
                        violations.append(
                            f"room '{room}' _room_occupied=True but "
                            f"any(_room_provenance)=False with no active "
                            f"fan-interference hold"
                        )
        # Invariant 3: raw_occupied composes through _derived_mode.
        _ = tracker.raw_occupied
    except Exception as exc:  # noqa: BLE001
        violations.append(f"invariants check raised: {exc!r}")
    return violations


class ZonePresenceTracker:
    """Tracks presence for a single zone using room sensors, cameras, and BLE.

    Three signal tiers (any one is sufficient for 'occupied'):
    1. Room occupancy sensors (mmWave/PIR) — discovered via entity registry area_id
    2. Zone camera person/motion detection — discovered via CameraIntegrationManager
    3. Bermuda BLE person location — read from person_coordinator

    Camera signals hold the zone occupied for _CAMERA_OCCUPANCY_TIMEOUT_SECONDS
    after the last detection, preventing flapping when cameras briefly lose sight.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        zone_name: str,
        room_names: List[str],
    ) -> None:
        self.hass = hass
        self.zone_name = zone_name
        self.room_names = room_names
        self._override: Optional[str] = None
        self._has_sensors: bool = False
        # Presence provenance-split cycle (D2):
        # `_room_provenance[room][kind] -> bool`, kind ∈ TIER1_KINDS
        # (plus legacy "tier1" sentinel when kind=None was passed).
        # `_room_occupied` is now a derived @property that returns
        # `{room: any(provenance[room].values())}` — STRICTLY STRONGER
        # than the pre-split last-writer-wins bool (a quiet semantic
        # improvement, NOT a behavior regression — see A.6 #4).
        self._room_provenance: Dict[str, Dict[str, bool]] = {}
        # Diagnostic-only: last kind whose False→True edge fired per room.
        # Cleared when the room transitions fully vacant (all kinds False).
        self._last_kind_per_room: Dict[str, str] = {}
        # D3: rooms whose fan(s) are currently on. Populated by the
        # presence-side fan state-change listener. Set membership only —
        # consensus arithmetic is unchanged.
        self._fan_on_rooms: Set[str] = set()
        # D3 / H1 fix-up: per-tracker fan entity_id -> room_name map.
        # Declared here (instead of monkey-patched via setattr in
        # `_discover_room_fans`) so the attribute has a stable shape
        # across the tracker's lifetime — diagnostic dumps, tests, and
        # future refactors can introspect it safely. Reset on every
        # re-discovery so stale entries from a previous CONF_FANS shape
        # do not accumulate.
        self._fan_entity_to_room: Dict[str, str] = {}
        # mmWave fan-corroboration Tier-3 D2: per-room timestamp of the
        # False→True fan-on transition (or seed-time on discovery when
        # already on). Cleared when the fan goes off. Consumed by
        # ``PresenceCoordinator._compute_mmwave_fan_demoted_rooms`` to
        # enforce leg (b) of Invariant M — the fan must have been on
        # for at least ``MMWAVE_FAN_CORROBORATION_GRACE_S`` before a
        # mmwave-sole hold can be demoted. Sibling shape to
        # ``_fan_on_rooms`` (membership) but carries a datetime.
        self._fan_on_since: Dict[str, "datetime"] = {}
        # Fan-transition coincidence gate (AUDIT probe 2026-08-01):
        # per-room UTC timestamp of the most recent fan power OR speed
        # transition on any configured CONF_FANS entity mapped to the
        # room. Stamped by ``_handle_fan_change`` on every observed
        # transition (on/off edge OR percentage attribute change).
        # Consumed by the room-tier coordinator to gate mmwave-sole
        # occupancy CREATION within FAN_TRANSITION_SUSPECT_WINDOW_S of
        # the transition. Sibling shape to ``_fan_on_since`` (same key,
        # same value type) but has different lifetime — persists across
        # fan-off (last transition is not cleared on off; the off edge
        # is itself a transition and stamps the field).
        self._fan_last_transition: Dict[str, "datetime"] = {}
        self._camera_occupied: Dict[str, bool] = {}  # entity_id -> detection active
        self._camera_last_seen: Dict[str, datetime] = {}  # entity_id -> last detection time
        # Fan-noise mitigation D1 (Layer-1 silent gate): per-room hold
        # expiry. Set ONLY by `_compute_fan_interference_rooms` when the
        # room is fan-interference-suspect AND the BLE corroboration
        # ladder says not-corroborated. Consulted by the derived
        # `_room_occupied` view to EXTEND occupancy past the natural drop
        # point. CRITICAL truth-preserving invariant: the hold can only
        # extend occupancy, never shorten it — if any kind in
        # `_room_provenance[room]` is True, the OR alone keeps the room
        # occupied and the hold is functionally inert. Cleared when L1
        # fires (mmwave trusted again) or when a non-mmwave kind flips
        # True. Storage is the SAME shape as `_camera_last_seen`
        # (presence.py:71 timeout idiom) — different lifetime, same
        # design pattern.
        self._fan_interference_hold_until: Dict[str, datetime] = {}
        self._ble_occupied: bool = False
        self._last_activity: Optional[datetime] = None
        self._unsub_listeners: list = []
        # Track which signal tiers are available
        self._has_room_sensors: bool = False
        self._has_camera_sensors: bool = False
        self._has_ble_sensors: bool = False
        # Track entity_id -> room_name for reverse lookup
        self._entity_to_room: Dict[str, str] = {}
        # Track camera entity_ids belonging to this zone
        self._camera_entity_ids: Set[str] = set()
        # v3.19.0: Face-confirmed arrival tracking
        self._last_face_recognized: str = ""
        self._last_face_time: Optional[datetime] = None
        self._face_arrivals_today: int = 0

    @property
    def mode(self) -> str:
        """Return current zone presence mode."""
        if self._override is not None:
            return self._override
        return self._derived_mode

    @property
    def _room_occupied(self) -> Dict[str, bool]:
        """Derived per-room occupied view.

        Provenance-split cycle (D2): replaces the prior
        ``_room_occupied: Dict[str, bool]`` storage attribute. Returns a
        fresh dict each access so callers never mutate internal state.

        Equivalence: ``{room: any(_room_provenance[room].values())}``.

        Semantics — honest framing (R1-H1 fix-up). Pre-split storage was
        last-writer-wins per room (bare bool assignment at the old
        ``update_room_occupancy`` call site). Post-split semantics are:
          - True-edges are per-kind ADDITIVE: a True write for one kind
            does NOT clear other kinds, so the OR keeps reading True as
            long as any kind is still firing. On the True path the
            derived OR is strictly stronger than the prior collapse —
            that part of the audit note (Appendix A.6 #4) holds.
          - False-edges are FULL-ROOM CLEARS: an ``occupied=False`` call
            wipes the entire per-kind bucket for the room, regardless of
            ``kind``. Today's discovery path cannot fire per-kind
            off-edges distinguishably (the state-change callback only
            knows which ENTITY went off; mapping an off-edge to a kind
            is omitted because the prior bool was a full-room clear
            too). See ``update_room_occupancy`` for the call-site
            comment.
        Net: the derived OR is "stronger on True, equivalent on False"
        relative to the pre-split bool — NOT uniformly stronger. The
        original "strictly stronger" phrasing in
        ``PLANNING_presence_provenance_split_and_fan_diagnostic.md`` D2
        was rewritten in the same fix-up pass to match this honest
        description. All 22 SAFE consumers in Audit Appendix A.2 read
        this shape unchanged.

        Fan-noise mitigation D1 (Layer-1 silent gate): the derived OR is
        ADDITIONALLY extended by the `_fan_interference_hold_until` dict
        — if a room has an active hold (set by
        ``_compute_fan_interference_rooms`` when the BLE corroboration
        ladder says not-corroborated), the room reads True for up to
        ``CONF_FAN_INTERFERENCE_HOLD_S`` past the natural drop point.
        CRITICAL truth-preserving invariant: the hold can ONLY extend
        occupancy, never shorten it. ``any(provenance.values())`` is
        evaluated FIRST and short-circuits — a positively-firing kind
        always wins regardless of the hold dict shape. This keeps every
        downstream reader (HVAC defer gate via
        ``check_zone_occupancy_confidence``, compliance gate, house
        inference) safe from false-unoccupied regressions: the worst
        case is "a fan-suspect room stays occupied a bit too long," the
        operator's no-regression mandate. See `AUDIT_fan_interference_
        gate_ripple.md` for the consumer-by-consumer trace.
        """
        now = dt_util.utcnow()
        hold = self._fan_interference_hold_until
        return {
            room: (
                any(bool(v) for v in kinds.values())
                or (room in hold and hold[room] > now)
            )
            for room, kinds in self._room_provenance.items()
        }

    def provenance_for(self, room_name: str) -> Dict[str, bool]:
        """Return the per-kind provenance bools for a single room.

        Provenance-split cycle (D2/D5). Always returns a stable dict
        with every TIER1_KINDS slot present (False when never fired).
        Used by D5 sensor attrs on ``OccupiedBinarySensor``.

        R1-H2 fix-up: the legacy ``"tier1"`` sentinel slot (used by the
        back-compat ``kind=None`` path in ``update_room_occupancy``) is
        FOLDED into the canonical ``"occupancy"`` slot of the projection
        so the derived ``_room_occupied`` view and the D5 attr surface
        never under-report occupancy relative to the pre-split bool. If
        a caller fires ``occupied=True`` without a kind, the sentinel
        records "we don't know which Tier-1 fired" — the projection
        surfaces it as ``occupancy=True`` (the generic Tier-1 slot)
        rather than silently dropping it. The raw sentinel remains
        present in ``_room_provenance`` for diagnostics + invariant
        checks (``_audit_provenance_invariants`` already allow-lists
        the ``"tier1"`` key alongside ``TIER1_KINDS``).
        """
        stored = self._room_provenance.get(room_name, {})
        projected = {k: bool(stored.get(k, False)) for k in TIER1_KINDS}
        # Fold the legacy "tier1" sentinel into "occupancy" so a
        # kind=None True is not silently dropped from the projection.
        if bool(stored.get("tier1", False)):
            projected["occupancy"] = True
        return projected

    @property
    def raw_occupied(self) -> bool:
        """Occupancy from raw sensor tiers, IGNORING any mode override.

        The WAKING gate must see real movement during sleep, which the
        SLEEP-override-masked ``mode`` cannot surface. (v4.7.18.1)
        """
        return self._derived_mode == ZonePresenceMode.OCCUPIED

    @property
    def _derived_mode(self) -> str:
        """Derive zone mode from all signal tiers.

        v3.6.0.2: BLE (Tier 3) no longer gated by _has_sensors.
        BLE person tracking is the most reliable signal and should
        always determine zone state when available.
        """
        # Tier 3 first: BLE person location (always available, most reliable)
        if self._ble_occupied:
            return ZonePresenceMode.OCCUPIED

        # Tiers 1 & 2 require sensor discovery
        if self._has_sensors:
            # Tier 1: Room occupancy sensors
            if any(self._room_occupied.values()):
                return ZonePresenceMode.OCCUPIED

            # Tier 2: Camera person/motion detection (with timeout)
            if self._any_camera_occupied():
                return ZonePresenceMode.OCCUPIED

            return ZonePresenceMode.AWAY

        # No sensors discovered and no BLE — still report away if BLE
        # has ever updated (meaning the zone is known to the system)
        if self._has_ble_sensors:
            return ZonePresenceMode.AWAY

        return ZonePresenceMode.UNKNOWN

    def _any_camera_occupied(self) -> bool:
        """Check if any camera signal indicates occupancy (with timeout)."""
        if not self._camera_last_seen:
            return False

        now = dt_util.utcnow()
        timeout = timedelta(seconds=_CAMERA_OCCUPANCY_TIMEOUT_SECONDS)

        for entity_id, last_seen in self._camera_last_seen.items():
            # Currently detecting OR within timeout window
            if self._camera_occupied.get(entity_id, False):
                return True
            if (now - last_seen) < timeout:
                return True

        return False

    @property
    def is_overridden(self) -> bool:
        """Return True if zone mode is manually overridden."""
        return self._override is not None

    @property
    def has_sensors(self) -> bool:
        """Return True if zone has at least one sensor of any tier."""
        return self._has_sensors

    def set_override(self, mode: str) -> None:
        """Set a manual override for this zone."""
        if mode == ZonePresenceMode.AUTO:
            self.clear_override()
        else:
            self._override = mode

    def clear_override(self) -> None:
        """Clear manual override."""
        self._override = None

    def update_room_occupancy(
        self,
        room_name: str,
        occupied: bool,
        kind: Optional[str] = None,
    ) -> None:
        """Update occupancy state for a room in this zone.

        Provenance-split cycle (D2). Signature is backward-compatible —
        ``kind=None`` preserves pre-split caller behavior.

        Rules:
          * ``kind ∈ TIER1_KINDS`` and ``occupied=True``: set that single
            kind's slot to True. Other kinds are untouched.
          * ``kind=None`` and ``occupied=True`` (LEGACY back-compat
            path): set a sentinel ``"tier1"`` slot. This preserves the
            pre-split "we don't know which kind" case while keeping the
            derived OR returning True. Used only by callers that have
            not (yet) classified the firing entity.
          * ``occupied=False`` (any kind, including None): CLEAR ALL
            kinds for the room. Matches today's collapse semantic.

        See :func:`_classify_entity_kind` for how the seed loop and
        ``_handle_occupancy_change`` derive ``kind``.
        """
        if room_name not in self.room_names:
            return

        bucket = self._room_provenance.setdefault(room_name, {})
        if occupied:
            slot = kind if kind in TIER1_KINDS else "tier1"
            was_true = bool(bucket.get(slot, False))
            bucket[slot] = True
            self._has_sensors = True
            self._has_room_sensors = True
            self._last_activity = dt_util.utcnow()
            if not was_true:
                self._last_kind_per_room[room_name] = slot
            # Auto-resume: if override is AWAY but we detect presence, clear it
            if self._override == ZonePresenceMode.AWAY:
                _LOGGER.info(
                    "Zone %s: auto-resuming from AWAY override — presence detected in %s",
                    self.zone_name, room_name,
                )
                self.clear_override()
        else:
            # occupied=False clears ALL kinds for the room (matches prior
            # collapse). Per-kind False writes are not represented because
            # today's discovery path does not fire per-kind off-edges
            # distinguishably (the state-change callback only knows the
            # ENTITY that fired, not the type — and the prior bool was a
            # full-room clear too).
            # R1-H1 fix-up: the derived `_room_occupied` is therefore
            # "stronger on True, equivalent on False" relative to the
            # pre-split bool — see the `_room_occupied` docstring + the
            # matching paragraph in
            # docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md.
            # Do NOT attempt to heuristically guess the off-kind from
            # the entity_id here: that would re-introduce the
            # seed-vs-live divergence hazard (v4.7.18.1 B-HIGH-1).
            if bucket:
                self._room_provenance[room_name] = {}
                self._last_kind_per_room.pop(room_name, None)
            else:
                # ensure the room key exists even on first-write False so
                # the derived `_room_occupied` shape is stable.
                self._room_provenance[room_name] = {}
            self._has_sensors = True
            self._has_room_sensors = True

    def update_camera_detection(self, entity_id: str, detected: bool) -> None:
        """Update camera person/motion detection for this zone.

        When detected=True, records timestamp for timeout-based occupancy.
        When detected=False, the timeout keeps the zone occupied for
        _CAMERA_OCCUPANCY_TIMEOUT_SECONDS before reverting to away.
        """
        self._camera_occupied[entity_id] = detected
        self._has_sensors = True
        self._has_camera_sensors = True
        if detected:
            self._camera_last_seen[entity_id] = dt_util.utcnow()
            self._last_activity = dt_util.utcnow()
            # Auto-resume from AWAY override on camera detection
            if self._override == ZonePresenceMode.AWAY:
                _LOGGER.info(
                    "Zone %s: auto-resuming from AWAY override — camera detection on %s",
                    self.zone_name, entity_id,
                )
                self.clear_override()

    def update_ble_presence(self, has_persons: bool) -> None:
        """Update BLE-based person presence in this zone."""
        self._ble_occupied = has_persons
        if has_persons:
            self._has_sensors = True
            self._has_ble_sensors = True
            self._last_activity = dt_util.utcnow()
            if self._override == ZonePresenceMode.AWAY:
                _LOGGER.info(
                    "Zone %s: auto-resuming from AWAY override — BLE presence detected",
                    self.zone_name,
                )
                self.clear_override()

    def set_sleep(self, sleeping: bool) -> None:
        """Set sleep mode (driven by house state, not zone sensors)."""
        if sleeping and self._override is None:
            # Only set sleep if not manually overridden
            self._override = ZonePresenceMode.SLEEP
        elif not sleeping and self._override == ZonePresenceMode.SLEEP:
            # Clear sleep override when house exits sleep
            self._override = None

    def mark_has_sensors(self) -> None:
        """Mark that this zone has at least one sensor."""
        self._has_sensors = True

    def register_entity(self, entity_id: str, room_name: str) -> None:
        """Register an entity_id → room_name mapping for this zone."""
        self._entity_to_room[entity_id] = room_name
        self._has_sensors = True
        self._has_room_sensors = True

    def register_camera(self, entity_id: str) -> None:
        """Register a camera entity_id for this zone."""
        self._camera_entity_ids.add(entity_id)
        self._has_sensors = True
        self._has_camera_sensors = True

    def to_dict(self) -> dict:
        """Serialize for diagnostics."""
        return {
            "zone_name": self.zone_name,
            "mode": self.mode,
            "derived_mode": self._derived_mode,
            "is_overridden": self.is_overridden,
            "override": self._override,
            "has_sensors": self._has_sensors,
            "signal_tiers": {
                "room_sensors": self._has_room_sensors,
                "camera_sensors": self._has_camera_sensors,
                "ble_sensors": self._has_ble_sensors,
            },
            "rooms": dict(self._room_occupied),
            # Provenance-split cycle (D2): additive diagnostic dump.
            # `rooms` above remains the canonical per-room bool view for
            # back-compat consumers. `rooms_provenance` exposes the new
            # per-kind store; `last_kind_per_room` and `fan_on_rooms`
            # round out the D5 diagnostic surface.
            "rooms_provenance": {
                r: dict(p) for r, p in self._room_provenance.items()
            },
            "last_kind_per_room": dict(self._last_kind_per_room),
            "fan_on_rooms": sorted(self._fan_on_rooms),
            "cameras": {
                eid: {
                    "detecting": self._camera_occupied.get(eid, False),
                    "last_seen": (
                        self._camera_last_seen[eid].isoformat()
                        if eid in self._camera_last_seen
                        else None
                    ),
                }
                for eid in self._camera_entity_ids
            },
            "ble_occupied": self._ble_occupied,
            "last_activity": (
                self._last_activity.isoformat() if self._last_activity else None
            ),
            # v3.19.0: Face-confirmed arrival state
            "last_face_recognized": self._last_face_recognized,
            "last_face_time": self._last_face_time.isoformat() if self._last_face_time else None,
            "face_arrivals_today": self._face_arrivals_today,
        }


# ============================================================================
# State Inference Engine
# ============================================================================


class StateInferenceEngine:
    """Infer house state from Census, time, and occupancy signals.

    Rules (evaluated in priority order):
    1. Census shows 0 people + all zones away → AWAY
    2. Census shows people + sleep hours → SLEEP
    3. Unidentified persons detected while home → GUEST
    4. Census shows people + time-based variant → HOME_DAY/EVENING/NIGHT
    5. Census shows new arrivals from AWAY → ARRIVING
    """

    def __init__(
        self,
        sleep_start_hour: int = 23,
        sleep_end_hour: int = 6,
        evening_start_hour: int = 18,
        night_start_hour: int = 21,
    ) -> None:
        self.sleep_start_hour = sleep_start_hour
        self.sleep_end_hour = sleep_end_hour
        self.evening_start_hour = evening_start_hour
        self.night_start_hour = night_start_hour
        self._confidence: float = 0.0

    @property
    def confidence(self) -> float:
        """Return confidence of last inference."""
        return self._confidence

    def infer(
        self,
        census_count: int,
        current_state: HouseState,
        any_zone_occupied: bool,
        now: Optional[datetime] = None,
        unidentified_count: int = 0,
        guest_gate_armed: bool = False,
        all_tracked_persons_away: bool = False,
        # v5.7.0 WS-A path-β kwargs. All default to safe values so callers
        # that omit them get v4.7.14 behavior byte-identical (invariant I3).
        all_trusted_or_lost_away_persons_away: bool = False,
        any_indoor_zone_occupied: Optional[bool] = None,
        grace_elapsed_for_lost_away: bool = False,
        lost_away_persons_present: bool = False,
        sleep_exempt_state: bool = False,
        # Presence batch fix-up (A-CRIT-1 / B-CRIT-1 / C-HIGH-1):
        # sustained_external_empty is an INDEPENDENT signal computed in
        # the caller — True iff the caller has observed N consecutive
        # ticks where (census_count == 0 AND unidentified_count == 0 AND
        # the FIX-2b indoor-clear debounce is already satisfied). It is
        # NOT implied by the outer path-β predicate below (which is a
        # single-tick check on census/unid/indoor). This is the ONLY
        # signal the immediate-engage limb may condition on beyond what
        # the outer clause already requires — otherwise the OR-group
        # collapses to a tautology and silently deletes the grace and
        # the indoor-clear debounce. Default False → caller-omitted
        # means v5.7.0 grace-only behavior (invariant preservation).
        sustained_external_empty: bool = False,
    ) -> Optional[HouseState]:
        """Infer the appropriate house state.

        Returns the inferred state, or None if no change is warranted.

        v4.6.2.2: guest_gate_armed replaces the raw unidentified_count > 0
        check for guest entry. It is pre-evaluated by PresenceCoordinator via
        _guest_gate_armed() which applies threshold, confidence, and persistence
        guards before passing the armed flag in.

        v4.7.14: all_tracked_persons_away is a person-tracker veto signal.
        When True (all configured person.* entities are not_home) AND there
        are no unidentified people in the house, return AWAY regardless of
        camera Tier 2 motion. Defends against camera ghost-presence.

        v5.7.0 WS-A: path β admits LOST-but-away trackers into the AWAY-veto
        denominator, gated by indoor-occupancy guard (A2/A4) + configurable
        grace (A3) + sleep exemption (A3). Path α (v4.7.14 ACTIVE-only) is
        preserved BYTE-IDENTICAL when only `all_tracked_persons_away` is
        passed — the new kwargs default to safe values that cannot fire β.
        The most-recently-fired path is recorded on ``self._veto_path`` ∈
        {"none", "active", "lost_admitted"}.
        """
        if now is None:
            now = dt_util.now()

        hour = now.hour

        # v5.7.0 WS-A2: per-call veto-path diagnostic. Re-initialized to
        # "none" each call; path α / β branches overwrite below.
        # v5.7.0 fix-up FIX-6 (B3/D-LOW-2): the prior docstring claim that
        # the value was "preserved across ticks" did not match the code
        # (each call re-sets to "none"). Dropped that claim — operators
        # reading the sensor surface get the verdict from the MOST RECENT
        # inference tick, not a sticky last-non-none verdict.
        self._veto_path: str = "none"

        # Nobody home
        if census_count == 0 and not any_zone_occupied:
            if current_state == HouseState.AWAY:
                return None  # Already away
            self._confidence = 0.9
            return HouseState.AWAY

        # v4.7.14: Person-tracker veto path α (ACTIVE-only) — if all configured
        # phone trackers say away AND no unidentified person is in the house,
        # return AWAY regardless of camera Tier 2 motion. Defends against
        # camera ghost-presence (Frigate motion-without-person-ID on empty
        # rooms). Note: unidentified_count > 0 preserves guest detection — a
        # guest at the door triggering camera motion legitimately means
        # someone IS here even if all tracked persons are away.
        # v4.7.14.1 (H1): also require census_count == 0. If Frigate face-IDs a
        # resident (census_count >= 1), SOMEONE is provably in front of a
        # camera — phone trustworthiness is irrelevant. Prevents the
        # forgotten-phone-at-home false-positive veto (Gap A).
        #
        # v5.7.0 invariant I3: this branch is byte-identical to v4.7.14 when
        # the WS-A kwargs are at their defaults (no LOST admitted, no indoor
        # guard, no grace). DO NOT modify path α — extend with path β below.
        if (
            all_tracked_persons_away
            and unidentified_count == 0
            and census_count == 0
        ):
            if current_state == HouseState.AWAY:
                self._veto_path = "active"
                return None  # Already away
            self._confidence = 0.95  # higher than camera-driven 0.85
            self._veto_path = "active"
            return HouseState.AWAY

        # v5.7.0 WS-A2: path β — LOST-admitted AWAY veto.
        #
        # Fires only when the LOST-relaxed denominator says all trusted-or-
        # lost-away persons are away AND no real indoor evidence contradicts
        # (no indoor zone occupied, census==0, no unidentified) AND the
        # configured grace has elapsed for the oldest LOST-away person AND
        # the house is not in a sleep-exempt state.
        #
        # Indoor-occupancy guard: `any_indoor_zone_occupied` is supplied by
        # the caller (PresenceCoordinator._run_inference) computed from zone
        # trackers excluding outdoor-flagged zones (WS-A4). When omitted
        # (None), we fall back to `any_zone_occupied` for conservative
        # behavior — a missing caller is treated as "any zone counts as
        # indoor", which can only SUPPRESS path β (never fire it spuriously).
        # That preserves I1 (no-force-AWAY-while-home) under partial wiring.
        #
        # Grace gate: `grace_elapsed_for_lost_away` is True iff (a) no LOST
        # persons are present in the denominator at all (no grace needed —
        # path α already failed for some other reason), OR (b) the oldest
        # LOST-stamp timestamp is older than CONF_LOST_AWAY_GRACE_MIN.
        # `lost_away_persons_present` is True iff at least one LOST+away
        # person is in the denominator. The legal combinations that admit
        # β are: (lost_present=False AND grace_elapsed=True) — degenerate,
        # path α should have already fired — OR (lost_present=True AND
        # grace_elapsed=True). The "no_lost_persons_present" carve-out in
        # the plan §A3 is encoded as the OR limb below.
        #
        # Sleep exemption: when CONF_LOST_AWAY_SLEEP_EXEMPT (default True)
        # and current_state is one of SLEEP/HOME_NIGHT/WAKING, the caller
        # passes sleep_exempt_state=True and path β is denied regardless
        # of grace. Protects sleeping residents whose phones may die for
        # hours (invariant I4).
        indoor_blocked = (
            any_indoor_zone_occupied
            if any_indoor_zone_occupied is not None
            else any_zone_occupied
        )
        # Presence batch D2 (fix-up: A-CRIT-1 / B-CRIT-1 / C-HIGH-1):
        # immediate-engage veto. Bypasses the CONF_LOST_AWAY_GRACE_MIN
        # grace ONLY when the house is externally corroborated empty for
        # a SUSTAINED window (N consecutive ticks). The original build
        # restated census/unid/!indoor here — inside the outer path-β
        # `if` those are already required, so the OR-limb reduced to
        # `lost_away_persons_present` and the whole OR-group evaluated
        # True unconditionally, silently deleting BOTH the 60-min grace
        # AND the FIX-2b indoor-clear debounce. The correct
        # discriminator is `sustained_external_empty` — computed in the
        # caller as N consecutive ticks of (census==0 AND unid==0 AND
        # _indoor_clear_debounced). N is the same
        # CONF_LOST_AWAY_INDOOR_CLEAR_TICKS constant FIX-2b uses (default
        # 3) — consistent semantics with the existing debounce, no new
        # CONF surface. Because sustained_external_empty carries the
        # indoor-clear debounce inside it, a single-tick mmWave dropout
        # CANNOT force AWAY — the same D-HIGH-2 protection FIX-2b
        # provides on the grace-elapsed limb. Falsifiable invariant
        # I-D2 preserved.
        # 2026-07-12 empty-house-flapping incident: for the entire
        # 63-min empty window every veto was denied by the grace clock,
        # leaving the state machine to free-oscillate on a noisy
        # Study-A motion sensor. Sleep exemption inherited from the
        # existing sleep_exempt_state gate below (unchanged).
        immediate_engage_empty_house = (
            sustained_external_empty
            and lost_away_persons_present
        )
        if (
            all_trusted_or_lost_away_persons_away
            and unidentified_count == 0
            and census_count == 0
            and not indoor_blocked
            and (
                grace_elapsed_for_lost_away
                or not lost_away_persons_present
                or immediate_engage_empty_house
            )
            and not sleep_exempt_state
        ):
            # Differentiate the immediate-engage path from the grace-
            # elapsed path via the veto_path attribute string so future
            # analytics can distinguish which limb fired. Confidence
            # stays at 0.95 for parity with path α (operator-resolved
            # 2026-07-13); differentiation is via the string, not a
            # weaker confidence.
            fired_immediate = (
                immediate_engage_empty_house
                and not grace_elapsed_for_lost_away
            )
            path_label = (
                "lost_admitted_immediate" if fired_immediate else "lost_admitted"
            )
            if current_state == HouseState.AWAY:
                self._veto_path = path_label
                return None  # Already away
            self._confidence = 0.95
            self._veto_path = path_label
            _LOGGER.info(
                "v5.7.0 path β: LOST-admitted AWAY veto fired "
                "(current=%s, indoor_zone_occupied=%s, grace_elapsed=%s, "
                "lost_present=%s, path=%s)",
                current_state.value,
                indoor_blocked,
                grace_elapsed_for_lost_away,
                lost_away_persons_present,
                path_label,
            )
            return HouseState.AWAY

        # People are home — determine variant
        has_people = census_count > 0 or any_zone_occupied

        if not has_people:
            return None

        # Arriving transition from AWAY
        if current_state == HouseState.AWAY:
            self._confidence = 0.85
            return HouseState.ARRIVING

        # Arriving → time-based home (must resolve before sleep/guest checks;
        # ARRIVING→SLEEP is not a valid state machine transition, so we first
        # move to HOME_*, then the next inference cycle handles HOME_*→SLEEP).
        if current_state == HouseState.ARRIVING:
            self._confidence = 0.85
            return self._time_based_home(hour)

        # Presence batch D1: GUEST-exit evaluated BEFORE the sleep-hours
        # branch so a cleared guest signal is not latched overnight.
        # 2026-07-11 incident: guest arrived 20:57, gate cleared 23:05,
        # the state was held in GUEST until 06:05 because the sleep-hours
        # branch returned first and shadowed the guest-exit check that
        # used to live further down. Reorder is a no-op outside sleep
        # hours (guest-exit was already reachable there). Falsifiable
        # invariant I-D1: for any tick where current_state==GUEST and
        # unidentified_count==0 and guest_gate_armed==False, infer()
        # MUST propose a non-GUEST successor regardless of sleep hour.
        # v4.7.2 D5 semantics preserved: check guest_gate_armed (OR of
        # both paths) not just unidentified_count so the guest_room path
        # can hold the state even with unidentified_count==0.
        if current_state == HouseState.GUEST and unidentified_count == 0 and not guest_gate_armed:
            self._confidence = 0.75
            return self._time_based_home(hour)

        # Sleep hours (don't enter guest mode during sleep)
        if self._is_sleep_hour(hour):
            if current_state not in (HouseState.SLEEP, HouseState.WAKING):
                self._confidence = 0.7
                return HouseState.SLEEP
            return None

        # Waking transition
        if current_state == HouseState.SLEEP:
            self._confidence = 0.8
            return HouseState.WAKING

        # Waking → HOME_DAY
        if current_state == HouseState.WAKING:
            self._confidence = 0.85
            return HouseState.HOME_DAY

        # v3.15.0 / v4.6.2.2: Guest detection — unidentified persons while home.
        # v4.6.2.2: guest_gate_armed pre-applies threshold + confidence +
        # persistence guards (see PresenceCoordinator._guest_gate_armed).
        # NOTE: ARRIVING excluded — must transition to HOME_* first (GUEST is
        # not a valid transition from ARRIVING). Guest detection fires next cycle.
        if guest_gate_armed and current_state in (
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
        ):
            if current_state != HouseState.GUEST:
                self._confidence = 0.8
                return HouseState.GUEST
        # (Guest-mode exit moved above the sleep-hours branch — see
        # "Presence batch D1" comment earlier in this function.)

        # Time-based transitions while home
        time_home = self._time_based_home(hour)
        if current_state in (
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
        ):
            if time_home != current_state:
                self._confidence = 0.75
                return time_home
            return None

        return None

    def _time_based_home(self, hour: int) -> HouseState:
        """Determine HOME variant based on time of day.

        Timeline (with defaults): 0-5 night, 6-17 day, 18-20 evening, 21+ night.
        Hours before sleep_end (0-5 AM) are HOME_NIGHT so the valid
        transition HOME_NIGHT → SLEEP can fire on the next cycle.
        """
        if hour >= self.night_start_hour:
            return HouseState.HOME_NIGHT
        if hour >= self.evening_start_hour:
            return HouseState.HOME_EVENING
        if hour < self.sleep_end_hour:
            return HouseState.HOME_NIGHT
        return HouseState.HOME_DAY

    def _is_sleep_hour(self, hour: int) -> bool:
        """Check if current hour is within sleep hours."""
        if self.sleep_start_hour > self.sleep_end_hour:
            # Crosses midnight (e.g., 23-6)
            return hour >= self.sleep_start_hour or hour < self.sleep_end_hour
        return self.sleep_start_hour <= hour < self.sleep_end_hour


# ============================================================================
# Presence Coordinator
# ============================================================================


class PresenceCoordinator(BaseCoordinator):
    """Presence domain coordinator.

    Infers house state from Census + time + zone occupancy.
    Manages zone presence tracking with 3-tier signal support.
    Publishes SIGNAL_HOUSE_STATE_CHANGED.
    """

    PRESENCE_METRICS = [
        "census_count",
        "zone_occupied_count",
        "transition_count_daily",
    ]

    def __init__(
        self,
        hass: HomeAssistant,
        sleep_start_hour: int = 23,
        sleep_end_hour: int = 6,
        guest_persistence_seconds: int = 300,
        guest_require_confidence: str = "medium",
    ) -> None:
        super().__init__(
            hass=hass,
            coordinator_id="presence",
            name="Presence Coordinator",
            priority=60,
        )
        self._inference_engine = StateInferenceEngine(
            sleep_start_hour=sleep_start_hour,
            sleep_end_hour=sleep_end_hour,
        )
        self._zone_trackers: Dict[str, ZonePresenceTracker] = {}
        self._census_count: int = 0
        self._unidentified_count: int = 0
        # v4.7.14: Person-tracker veto diagnostics (populated by _run_inference).
        # v4.7.14.1 fix-up A-M2: `_tracked_persons_count` preserves the
        # pre-v4.7.14.1 semantic (raw configured-person count from
        # person_coordinator.data) so existing operator dashboards / templates
        # don't silently flip to a smaller post-filter number.
        # `_tracked_persons_count_trusted` is the NEW post-H2/H3 filtered
        # denominator used by the veto reduction.
        self._tracked_persons_count: int = 0
        self._tracked_persons_count_trusted: int = 0
        self._all_tracked_persons_away: bool = False
        # v4.7.14.1 fix-up A-M1/A-M3: persons filtered out by H2 (phone_left_behind)
        # or H3 (tracking_status STALE/LOST), mapped to their exclusion reason.
        # Surfaced in the veto-fired INFO log so operators can diagnose why a
        # particular person did NOT block the veto.
        self._excluded_persons: dict[str, str] = {}
        # v4.7.15 D1: Last shared-veto-helper decision (diagnostics).
        # Populated each _run_inference tick when the helper is consulted.
        self._last_veto_decision: VetoDecision = VetoDecision(False, 0.0, "", "")
        # v4.7.15 D3: Sustained-occupancy tracking — set when any_zone_occupied
        # flips False -> True, cleared when False. Drives WAKING gate.
        self._first_positive_zone_occupied_since: Optional[datetime] = None
        self._wake_blocked_ticks: int = 0
        # v4.7.18.1 D2: Times the daytime wake-backstop forced WAKING despite
        # insufficient sustained signal. Surfaced on the house-state sensor.
        self._wake_backstop_fires: int = 0
        # v4.7.15 D3: Exit-side persistence for GUEST -> HOME_*. Set when
        # the "no unidentified, no guest_gate_armed" condition first becomes
        # true while in GUEST state; cleared when it goes false.
        self._guest_exit_quiet_since: Optional[datetime] = None
        # v4.7.15 D5: Per-cycle signal_consensus + sustained-low tracker.
        self._signal_consensus: float = 1.0
        self._signal_consensus_inputs: Dict[str, Any] = {}
        self._consensus_low_since: Optional[datetime] = None
        # Fan-noise mitigation D1: runtime-tunable hold duration (seconds)
        # for the Layer-1 silent gate. Seeded from the URA Coordinator-
        # Manager entry.options when present (URA-mirror pattern — see
        # `feedback_ura_mirror_pattern.md`), falling back to
        # ``DEFAULT_FAN_INTERFERENCE_HOLD_S`` (300s, mirrors camera
        # tier). FanInterferenceHoldNumber pushes operator changes via
        # ``set_fan_interference_hold_s`` AND mirrors them back into
        # entry.options so the value survives restore-from-backup /
        # fresh-install-with-config paths where RestoreEntity has no
        # last state. Range 60-1800 enforced at the Number entity.
        # B-H1 fix-up: prior code hard-coded the default at __init__ —
        # operator value only arrived via RestoreEntity, silently
        # reverting to 300s on any no-last-state path.
        from ..const import (
            CONF_ENTRY_TYPE as _CONF_ENTRY_TYPE,
            CONF_FAN_INTERFERENCE_HOLD_S as _CONF_FAN_INTERFERENCE_HOLD_S,
            DEFAULT_FAN_INTERFERENCE_HOLD_S,
            ENTRY_TYPE_COORDINATOR_MANAGER as _ENTRY_TYPE_COORDINATOR_MANAGER,
        )
        _seed_hold_s = int(DEFAULT_FAN_INTERFERENCE_HOLD_S)
        try:
            for _ce in self.hass.config_entries.async_entries(DOMAIN):
                if _ce.data.get(_CONF_ENTRY_TYPE) == _ENTRY_TYPE_COORDINATOR_MANAGER:
                    _seed_hold_s = int(
                        {**_ce.data, **_ce.options}.get(
                            _CONF_FAN_INTERFERENCE_HOLD_S,
                            DEFAULT_FAN_INTERFERENCE_HOLD_S,
                        )
                    )
                    break
        except Exception:  # noqa: BLE001 — defensive; fall back to default
            _seed_hold_s = int(DEFAULT_FAN_INTERFERENCE_HOLD_S)
        # Clamp to the supported range so a hand-edited options blob
        # can't push out-of-band values into the gate.
        self._fan_interference_hold_s: int = max(60, min(1800, _seed_hold_s))
        # Fan-noise mitigation D1: edge-detection set so the
        # SIGNAL_FAN_INTERFERENCE_GATE_FIRED dispatch only fires on the
        # tick a room moves from "no hold" to "hold active." Avoids
        # tick-rate spam during a sustained interference window.
        self._fan_interference_gated_prev: Set[str] = set()
        # B-M1 fix-up: cached adjacency map (room_name -> list of
        # adjacent room_names) for the Layer-1 gate. Previously the
        # gate rebuilt this dict every tick by walking every URA
        # config entry — exactly the per-tick walk this feature
        # family is sensitive to (mirrors the `_room_to_zone` cache
        # rationale at the C2/C3 fix-up). Built once at the end of
        # `_discover_zones` / `_discover_room_sensors` and on the
        # first gate call (lazy initialization for tests that build
        # the coordinator outside the normal discovery path).
        # Invalidated by clearing the dict — any code path that
        # rewires rooms must call `_invalidate_adjacency_cache()`.
        self._adjacency_cache: Optional[Dict[str, List[str]]] = None
        # v4.7.16 D3: per-zone weighted-veto verdicts populated each cycle.
        # Read by sensors + reviewers for diagnostics; gating wired in
        # post-v4.7.15 helper integration pass.
        self._v4716_zone_verdicts: Dict[str, Dict[str, Any]] = {}
        # v5.7.0 fix-up FIX-2b: indoor-clear debounce counter for the WS-A2
        # path-β AWAY veto. Incremented on each tick where
        # `any_indoor_zone_occupied == False`, reset to 0 on any indoor
        # occupancy. Path β requires this counter to meet
        # `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS` before firing — a single-tick
        # mmWave dropout cannot force AWAY on a present-still resident.
        self._indoor_clear_consecutive_ticks: int = 0
        # Presence batch fix-up (A-CRIT-1 / B-CRIT-1 / C-HIGH-1):
        # sustained-external-empty counter. Incremented on each tick
        # where (census_count == 0 AND unidentified_count == 0 AND
        # _indoor_clear_debounced). Reset to 0 on any tick that fails
        # any of the three. Path β's immediate-engage limb requires
        # this counter to meet CONF_LOST_AWAY_INDOOR_CLEAR_TICKS (same
        # N as FIX-2b) — a genuinely empty house confirms within ~N
        # ticks (vs 60-min grace); a single-tick BLE-dropout-while-home
        # cannot escalate to force-AWAY because the multi-tick census/
        # unid/indoor-clear conjunction cannot be satisfied by a single
        # flake. Sibling of `_indoor_clear_consecutive_ticks`.
        self._external_empty_consecutive_ticks: int = 0
        # v5.7.0 fix-up: cache for the CM options entry (read once per
        # process; refreshed if a new CM appears). Hoisted here so the
        # WS-A3 grace/sleep CONF read in _run_inference doesn't rely on
        # a class-attr fallback.
        self._cm_entry_cache: Optional[Any] = None
        self._transitions_today: int = 0
        self._transition_reset_date: str = ""
        # Room area_id lookup: room_name -> area_id (from config entries)
        self._room_area_ids: Dict[str, str] = {}
        # C2/C3 fix-up: room_name -> zone_name reverse lookup, populated
        # once at the end of `_discover_zones`. Lets hot paths (D5 attr
        # block in binary_sensor.py; D2 classifier; _handle_*_change)
        # skip the per-call O(N_zones x N_rooms_per_zone) walk over
        # `_zone_trackers` to find which tracker owns a given room.
        # Rebuilt on every `_discover_zones` call so a config reload that
        # rewires zones leaves no stale mapping.
        self._room_to_zone: Dict[str, str] = {}
        # M1 fix-up: cache for `_classify_entity_kind` results. Entities'
        # classifications are stable per (entity_id, room_name) pair —
        # they only change on a config-flow update to CONF_*_SENSORS.
        # The cache is invalidated on `_discover_room_sensors` re-entry
        # so a reload that rewires sensor lists picks up the new shape.
        self._entity_kind_cache: Dict[tuple, str] = {}
        # H2 fix-up: dedicated slots for the fan + camera + occupancy
        # state-change-listener unsubs so re-discovery (config reload,
        # zone-rewire) can tear down the prior subscription before
        # registering a new one. Without these slots, repeated calls to
        # `_discover_room_fans` / `_discover_zone_cameras` /
        # `_discover_room_sensors` would stack duplicate listeners on
        # `_unsub_listeners` — a leak in the strictest sense and a
        # double-emit hazard if a fan / camera / sensor toggles between
        # discoveries. The unsubs ALSO live in `_unsub_listeners` so the
        # existing teardown path in `_cancel_listeners` cleans them up
        # on unload; the dedicated slot lets us find + remove the prior
        # entry on re-discovery without scanning the whole list. Today
        # these discovery methods are only invoked once from
        # `async_setup`, so the slots default to None; the
        # belt-and-braces unsub logic is defense-in-depth against a
        # future re-discovery caller (e.g. a config-flow-driven reload).
        self._fan_listener_unsub: Optional[Any] = None
        self._camera_listener_unsub: Optional[Any] = None
        self._occupancy_listener_unsub: Optional[Any] = None
        # Deferred retry for hysteresis-blocked transitions
        self._retry_unsub: Optional[Any] = None
        # B-2026-08-03-2: monotonic-time expiry of the arriving re-arm cooldown.
        # 0.0 = inactive (default / expired). Set after ARRIVING→AWAY collapse.
        self._arriving_rearm_until: float = 0.0
        # Flap-diagnostic counters for the suppressed / bypassed paths.
        self._arriving_rearm_suppressed: int = 0
        self._arriving_rearm_bypassed: int = 0
        # Outcome measurement
        self._outcome_true_positives: int = 0
        self._outcome_false_positives: int = 0
        self._last_transition_state: Optional[HouseState] = None
        self._last_transition_time: Optional[datetime] = None
        # Observation mode: when True, inference and zone tracking continue
        # but SIGNAL_HOUSE_STATE_CHANGED and SIGNAL_PERSON_ARRIVING are not
        # dispatched.  Controlled via switch.ura_presence_observation_mode.
        self.observation_mode: bool = False

        # OC Phase 5 Pillar A handshake — unsub for SIGNAL_OPTIMIZER_INTENT.
        # ``async_setup`` checks this for None before subscribing so an
        # options reload that re-enters setup can't double-subscribe.
        self._optimizer_intent_unsub = None
        # Reason string for the most recent honor_optimizer_intent veto;
        # read by ``_on_optimizer_intent`` immediately after evaluation.
        self._last_veto_reason: str | None = None

        # Cold-boot away-actuation storm mitigation (Gate 1 — presence
        # dispatch settle gate). When False, the dispatch site for
        # SIGNAL_HOUSE_STATE_CHANGED short-circuits with an INFO log so the
        # boot-time AWAY default does not fan-out into HA chained automations
        # before census/zone data has settled. The HouseStateMachine still
        # transitions internally — only cross-coordinator fan-out is held.
        # Flips True via Predicate A (first real input observed inside
        # _run_inference) OR Predicate B (EVENT_HOMEASSISTANT_STARTED fires
        # OR BOOT_SETTLE_TIMEOUT_SECONDS elapses), whichever comes first.
        # Scoped to cold boot only — released immediately when async_setup
        # runs during an options-flow reload (hass.is_running already True).
        self._boot_settle_done: bool = False
        self._boot_settle_started_utc: Optional[datetime] = None
        # Tier-3 D2 snapshot (D-HIGH-3): refreshed once per
        # _run_inference tick; is_room_mmwave_fan_demoted reads this
        # instead of calling the primitive live.
        self._mmwave_fan_demoted_snapshot: frozenset = frozenset()
        self._mmwave_grace_clamp_logged: bool = False
        self._boot_settle_release_reason: str = "pending"
        self._boot_settle_presence_suppressed: int = 0

        # v3.19.0: Face-confirmed arrival state
        self._face_arrival_cooldown: Dict[str, datetime] = {}
        self._face_recognition_enabled: bool = False
        # v3.21.0 D2: Ready event for downstream coordinators (e.g., HVAC).
        # Initialized as None here; created in async_setup() to ensure it
        # binds to the correct event loop (review fix F3).
        self._ready_event: asyncio.Event | None = None

        # v4.6.2.2: Guest mode false-positive hardening
        # Census confidence fields — updated by _handle_census_update
        self._census_confidence: str = "none"
        # Persistence arm: timestamp of first qualifying unidentified tick
        self._unidentified_first_seen: Optional[datetime] = None
        # Deferred recheck handle — cancelled on disarm, gate fire, and unload
        self._guest_persistence_check_handle: Optional[Any] = None
        # Guest mode config knobs
        self._guest_persistence_seconds: int = guest_persistence_seconds
        self._guest_require_confidence: str = guest_require_confidence

        # v4.7.2 D5: Sustained-occupancy guest signal (Feature B)
        # Per-room anti-flap state machine. Keyed by room_name.
        # {room_name: {"first_seen": Optional[datetime], "current_occupancy_known": bool}}
        self._guest_room_state: Dict[str, dict] = {}
        # Per-room listener unsubs (separate from _unsub_listeners for targeted cleanup)
        self._guest_room_unsubs: Dict[str, Any] = {}

        # Fan-noise Mode-2 mitigation: room-tier fan-recheck manager. Built
        # lazily in async_setup so we don't import the module at __init__ time
        # (avoids a circular if presence_fan_recheck ever needs PC types).
        self._fan_recheck_manager: Optional[Any] = None

        # Occupancy substrate unification cycle: shared per-room, per-kind
        # raw-signal layer beneath the room + zone tiers. Owned by this
        # PresenceCoordinator instance; built in async_setup() before
        # _discover_room_sensors fires. The zone tier subscribes to
        # SIGNAL_SUBSTRATE_KIND_CHANGED instead of state-change events on
        # the entity-registry area-sweep set. See
        # docs/planning/PLANNING_occupancy_substrate_unification.md.
        self._substrate: Optional[Any] = None
        # Substrate signal subscription unsub (dispatcher channel). Captured
        # so async_teardown can clean it up — Bug Class #38.
        self._substrate_signal_unsub: Optional[Any] = None
        # F3 fix-up (B-HIGH-1): track substrate refresh tasks scheduled
        # from the room-lifecycle handler so async_teardown can cancel +
        # gather them BEFORE the substrate is torn down. Prevents a
        # late-fired refresh from racing with teardown.
        self._substrate_refresh_tasks: Set[Any] = set()
        # Routine-Awareness Next-State Forecaster (cycle:
        # routine-next-state-forecaster). Built in async_setup right
        # after the house_state_log hydration; teardown calls
        # async_shutdown to cancel its timer + signal subscription
        # (Bug Class #19 + #50). Read by get_next_state_prediction().
        self._routine_forecaster: Optional[Any] = None

    @property
    def inference_engine(self) -> StateInferenceEngine:
        """Return the state inference engine."""
        return self._inference_engine

    @property
    def zone_trackers(self) -> Dict[str, ZonePresenceTracker]:
        """Return zone presence trackers."""
        return self._zone_trackers

    def _outdoor_zone_names_snapshot(self) -> set[str]:
        """v5.7.0 WS-A4: snapshot of zone_names flagged CONF_ZONE_IS_OUTDOOR.

        Zones may live in two shapes (see config_flow.py):

        - Legacy ENTRY_TYPE_ZONE entries: read entry.data + entry.options
          directly for CONF_ZONE_IS_OUTDOOR.
        - Modern Zone Manager: per-zone dict lives under
          zone_manager_entry.options["zones"][<zone_name>][CONF_ZONE_IS_OUTDOOR].

        Read EACH cycle (cheap — small set of entries; reading once at
        setup would silently miss operator edits made between restarts).
        Defensive: any registry / entry shape error returns an empty set
        (fail-OPEN — outdoor exclusion becomes a no-op; path β behaves
        conservatively, indoor guard treats all zones as indoor).
        """
        outdoor: set[str] = set()
        try:
            from ..const import (
                CONF_ENTRY_TYPE,
                ENTRY_TYPE_ZONE,
                ENTRY_TYPE_ZONE_MANAGER,
            )
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                etype = entry.data.get(CONF_ENTRY_TYPE)
                if etype == ENTRY_TYPE_ZONE:
                    merged = {**entry.data, **entry.options}
                    if merged.get(CONF_ZONE_IS_OUTDOOR, DEFAULT_ZONE_IS_OUTDOOR):
                        zname = merged.get("zone_name")
                        if zname:
                            outdoor.add(zname)
                elif etype == ENTRY_TYPE_ZONE_MANAGER:
                    merged = {**entry.data, **entry.options}
                    zones = merged.get("zones") or {}
                    if isinstance(zones, dict):
                        for zname, zcfg in zones.items():
                            if not isinstance(zcfg, dict):
                                continue
                            if zcfg.get(
                                CONF_ZONE_IS_OUTDOOR, DEFAULT_ZONE_IS_OUTDOOR
                            ):
                                outdoor.add(zname)
        except Exception as exc:  # noqa: BLE001 — defensive: registry/shape errors
            _LOGGER.debug(
                "v5.7.0 WS-A4: outdoor zone snapshot failed: %s — "
                "treating all zones as indoor (path β behaves conservatively)",
                exc,
            )
            return set()
        return outdoor

    def _classify_entity_kind_cached(
        self, entity_id: str, room_name: str,
    ) -> str:
        """Cached wrapper around :func:`_classify_entity_kind`.

        M1 fix-up: the underlying classifier walks every URA config
        entry per call. The (entity_id, room_name) -> kind mapping is
        STABLE between config-flow edits to CONF_*_SENSORS, so caching
        the result is safe. The cache is invalidated by
        ``_discover_room_sensors`` (re-discovery is the only path that
        can produce a new sensor list).

        Both the seed loop and the live state-change callback route
        through this wrapper, preserving the v4.7.18.1 B-HIGH-1
        seed-vs-live byte-equal invariant: a single cache slot per
        (entity, room) means both call sites get the exact same kind.
        """
        key = (entity_id, room_name)
        cached = self._entity_kind_cache.get(key)
        if cached is not None:
            return cached
        kind = _classify_entity_kind(self.hass, entity_id, room_name)
        self._entity_kind_cache[key] = kind
        return kind

    def tracker_for_room(
        self, room_name: str,
    ) -> Optional["ZonePresenceTracker"]:
        """Return the ZonePresenceTracker that owns ``room_name``, or None.

        C2/C3 fix-up: O(1) reverse lookup via ``_room_to_zone`` instead
        of walking ``_zone_trackers`` per call. Falls back to a linear
        scan ONLY if the cache is empty (pre-``_discover_zones`` window)
        to preserve correctness in cold-start edge cases. Used by the D5
        binary_sensor attr block + any consumer that historically walked
        all zones to find a room.
        """
        zone_name = self._room_to_zone.get(room_name)
        if zone_name is not None:
            return self._zone_trackers.get(zone_name)
        if self._room_to_zone:
            # Cache is populated but room isn't in it — definitively
            # unknown, no need to walk.
            return None
        # Cache empty — cold-start window. One-shot linear scan; result
        # is not memoized because the cache is rebuilt by
        # `_discover_zones`.
        for _zone_name, _tracker in self._zone_trackers.items():
            if room_name in _tracker.room_names:
                return _tracker
        return None

    @property
    def census_count(self) -> int:
        """Return current census count."""
        return self._census_count

    @property
    def house_state(self) -> str:
        """Return current house state from the manager's state machine."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        state = manager.house_state
        return state.value if hasattr(state, 'value') else str(state)

    @property
    def confidence(self) -> float:
        """Return confidence of current state inference."""
        return self._inference_engine.confidence

    # ------------------------------------------------------------------
    # v4.7.15 D1: Shared Bug Class #48 veto helper
    # ------------------------------------------------------------------
    def should_veto_due_to_reliable_signals(
        self,
        *,
        reliable_signals: List[ReliableSignal],
        transient_signals: List[TransientSignal],
        state_context: Dict[str, Any],
    ) -> VetoDecision:
        """Bug Class #48 arbitration: reliable-signal veto of transient evidence.

        v4.7.15 D1: Promotes the v4.7.13 (zone aggregator SLEEP) and v4.7.14
        (house inference AWAY) inline patterns to a shared utility so future
        cycles (v4.7.16 room-level, v4.8.x BLE proximity) plug new patterns
        here rather than fork the logic. Default fall-through is fired=False —
        adding a new caller without a matching pattern is a no-op.

        Patterns shipped (scope dispatch):
          - "house_inference"  : Pattern A — v4.7.14 AWAY veto
          - "zone_aggregator"  : Pattern B (SLEEP, v4.7.13) + Pattern C (non-sleep, v4.7.15 D2)
          - "waking_transition": Pattern D — v4.7.15 D3 sustained-signal WAKING gate
          - "guest_exit"       : Pattern E — v4.7.15 D3 GUEST→HOME exit-side persistence
        """
        scope = str(state_context.get("scope", ""))
        # Bug Class #22 mitigation: accept enum or string for house_state.
        _hs_raw = state_context.get("house_state", "")
        house_state = str(getattr(_hs_raw, "value", _hs_raw)).lower()
        tracked_count = int(state_context.get("tracked_count", 0))

        # Pattern A — v4.7.14 house-inference AWAY veto.
        # v4.7.15.1: extended to consume the v4.7.14.1 H1/H2/H3 surfaces.
        #   H1 (census_count == 0) — transient signal kind "census_count".
        #   H2 (phone_left_behind not on) — reliable signal kind
        #       "person_phone_trustworthy" (one per tracked person).
        #   H3 (tracking_status ACTIVE) — reliable signal kind
        #       "person_tracking_active" (one per tracked person).
        # Callers supply the per-person H2/H3 signals in parallel order — the
        # helper does a positional zip to derive the trusted count.
        # Backward compat: if H2/H3 lists are empty, fall back to
        # state_context["tracked_count"] (pre-v4.7.14.1 baseline for callers
        # that don't have per-person trust data — e.g., zone aggregator).
        if scope == "house_inference":
            phone_trust = [
                s.value for s in reliable_signals
                if s.kind == "person_phone_trustworthy"
            ]
            track_active = [
                s.value for s in reliable_signals
                if s.kind == "person_tracking_active"
            ]
            if phone_trust or track_active:
                # Length-parity check: misaligned input fails CONSERVATIVE so
                # we cannot accidentally veto on broken caller contracts.
                if (
                    len(phone_trust) == len(track_active)
                    and len(phone_trust) > 0
                ):
                    trusted_count = sum(
                        1 for p, t in zip(phone_trust, track_active) if p and t
                    )
                else:
                    # v4.7.15.1 fix-up B2-M1 (Reviewer B): one-shot WARN-per-
                    # process so operators can diagnose a future per-person
                    # parallel-list contract violation. Without this, a
                    # caller-side regression silently degrades to "no veto"
                    # with zero log signal.
                    global _LENGTH_MISMATCH_WARNED
                    if not _LENGTH_MISMATCH_WARNED:
                        _LENGTH_MISMATCH_WARNED = True
                        _LOGGER.warning(
                            "v4.7.15.1 helper Pattern A: per-person "
                            "parallel-list length mismatch — "
                            "phone_trust=%d, tracking_active=%d. Failing "
                            "conservative (no veto). Subsequent "
                            "occurrences suppressed for this process.",
                            len(phone_trust),
                            len(track_active),
                        )
                    trusted_count = 0
            else:
                # Backward compat: no per-person trust signals → use caller's
                # tracked_count from state_context (pre-v4.7.14.1 semantic).
                trusted_count = tracked_count

            all_away = any(
                s.kind == "person_tracker_away" and s.value for s in reliable_signals
            )
            any_home = any(
                s.kind == "person_tracker_home" and s.value for s in reliable_signals
            )
            unid = next(
                (s.count for s in transient_signals
                 if s.kind == "unidentified_person_count"),
                0,
            )
            # H1: census_count == 0 required for veto to fire.
            census = next(
                (s.count for s in transient_signals
                 if s.kind == "census_count"),
                0,
            )
            if (
                trusted_count > 0
                and all_away
                and not any_home
                and unid == 0
                and census == 0
            ):
                return VetoDecision(
                    True,
                    0.95,
                    (
                        "all_tracked_persons_away (no guests, no census, "
                        f"trusted={trusted_count})"
                    ),
                    scope,
                )
            return VetoDecision(False, 0.0, "", scope)

        # Pattern B — v4.7.13 zone-aggregator SLEEP fallback.
        if scope == "zone_aggregator" and house_state == "sleep":
            any_home = any(
                s.kind == "zone_persons_home" and s.value for s in reliable_signals
            )
            if any_home:
                return VetoDecision(True, 0.90, "zone_persons home during sleep", scope)
            return VetoDecision(False, 0.0, "", scope)

        # Pattern C — v4.7.15 D2 zone-aggregator non-sleep states.
        if scope == "zone_aggregator" and house_state in (
            "home_day", "home_evening", "home_night",
            "arriving", "guest", "waking",
        ):
            any_home = any(
                s.kind == "zone_persons_home" and s.value for s in reliable_signals
            )
            sensors_quiet_seconds = int(
                state_context.get("room_sensors_quiet_seconds", 0)
            )
            if any_home and sensors_quiet_seconds >= _NONSLEEP_QUIET_THRESHOLD_SECONDS:
                return VetoDecision(
                    True,
                    0.85,
                    f"zone_persons home during {house_state} "
                    f"(quiet {sensors_quiet_seconds}s)",
                    scope,
                )
            return VetoDecision(False, 0.0, "", scope)

        # Pattern D — v4.7.15 D3 WAKING sustained-signal gate.
        if scope == "waking_transition":
            sustained_seconds = int(
                state_context.get("sustained_occupancy_seconds", 0)
            )
            if sustained_seconds >= _WAKING_SUSTAINED_THRESHOLD_SECONDS:
                return VetoDecision(
                    False, 0.85,
                    f"sustained occupancy confirms wake ({sustained_seconds}s)",
                    scope,
                )
            return VetoDecision(
                True, 0.6,
                f"insufficient sustained signal ({sustained_seconds}s "
                f"< {_WAKING_SUSTAINED_THRESHOLD_SECONDS}s)",
                scope,
            )

        # Pattern E — v4.7.15 D3 GUEST exit-side persistence.
        if scope == "guest_exit":
            quiet_seconds = int(state_context.get("guest_exit_quiet_seconds", 0))
            threshold = int(
                state_context.get(
                    "guest_persistence_seconds", self._guest_persistence_seconds,
                )
            )
            if threshold <= 0:
                return VetoDecision(False, 0.0, "guest exit persistence disabled", scope)
            if quiet_seconds >= threshold:
                return VetoDecision(
                    False, 0.85,
                    f"guest exit sustained ({quiet_seconds}s >= {threshold}s)",
                    scope,
                )
            return VetoDecision(
                True, 0.7,
                f"guest exit not yet sustained ({quiet_seconds}s < {threshold}s)",
                scope,
            )

        # Unknown / unmatched scope — fall through (forward compatible).
        # v4.7.15 fix-up A7-H1 / B6 / Reviewer C C4 (deferral comment):
        # v4.7.16 D3 calls this helper with scope="room_level_weighted" for
        # diagnostic-only purposes (per v4.7.16 plan §0.7 — D3 is intentionally
        # diagnostic-only until v4.7.17 flips it to gating). v4.7.15 deliberately
        # does NOT add a Pattern F handler here because the threshold semantic
        # (sum vs max weights, 1.0 vs 0.6 etc.) needs the diagnostic data first,
        # and ReliableSignal/VetoDecision need extending with weight + defer-to-
        # consensus fields. Both belong in the same cycle that flips D3 from
        # diagnostic to gating. Until then, falling through to fired=False is
        # the correct conservative behaviour — diagnostic recorder logs a
        # constant-False signal that v4.7.17+ will refine. Do NOT add Pattern F
        # in a v4.7.15 hotfix without coordinating the contract evolution.
        return VetoDecision(False, 0.0, "", scope)

    # ------------------------------------------------------------------
    # v4.7.15 D4: Multi-source zone occupancy confidence (relocated from HVAC)
    # ------------------------------------------------------------------
    def check_zone_occupancy_confidence(self, zone) -> tuple[int, int]:
        """Count independent occupancy sources confirming zone presence.

        Migrated from hvac.py:1350 in v4.7.15 D4. Identical semantics; now
        public on PresenceCoordinator so D5/D6 consensus calc and v4.7.16
        room-level callers can consume it without HVAC ↔ presence circular
        imports.

        Provenance-split cycle (D4) docstring fidelity update — per
        AUDIT_presence_provenance.md Appendix A.6 #2: Source 1 reads
        each ROOM COORDINATOR's ``_last_motion_time`` (see line ~1014
        below), NOT the zone tracker's ``_room_occupied``. The
        provenance OR split therefore does NOT couple to this helper:
        ``possible`` count is unchanged regardless of D2 storage shape,
        and ``hvac.py:953-961`` adaptive-threshold behavior is pinned
        by this docstring, not by code. Source 1 motion is judged on
        recency (30 minute window) at room granularity — orthogonal to
        the per-kind split that D2 introduces on the zone-side view.

        Returns (confirmed, possible) where:
        - confirmed: number of source types actively confirming presence (0-4)
        - possible: number of source types available for this zone (0-4)

        Source types:
        1. Motion/mmWave sensors (recent activity within 30 min) — reads
           room coordinator ``_last_motion_time``, independent of D2.
        2. BLE person detection (phone detected in zone)
        3. Camera person detection (Frigate person entity "on")
        4. Multiple occupied rooms (2+ rooms occupied = unlikely all stuck)

        The caller uses adaptive threshold: require min(2, possible) sources.
        Accepts HVAC's `Zone` dataclass shape duck-typed (reads .rooms,
        .zone_cameras, .room_conditions).
        """
        # function-local import — Bug Class #34
        from ..const import (  # noqa: PLC0415
            CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM,
        )
        confirmed = 0
        possible = 0

        # Source 1: Motion/mmWave — always available (every room has sensors)
        possible += 1
        has_recent_motion = False
        now = dt_util.utcnow()
        try:
            for room_name in getattr(zone, "rooms", []) or []:
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if (
                        entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM
                        and entry.data.get(CONF_ROOM_NAME) == room_name
                    ):
                        coord = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
                        if (
                            coord
                            and hasattr(coord, "_last_motion_time")
                            and coord._last_motion_time
                        ):
                            age = (now - coord._last_motion_time).total_seconds()
                            if age < 1800:  # Motion in last 30 min
                                has_recent_motion = True
                        break
        except Exception:  # noqa: BLE001 — defensive: stale registry
            pass
        if has_recent_motion:
            confirmed += 1

        # Source 2: BLE person detection
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord:
            possible += 1
            try:
                ble_persons = person_coord.get_persons_in_zone(
                    getattr(zone, "rooms", []) or [],
                )
                if ble_persons:
                    confirmed += 1
            except Exception:  # noqa: BLE001
                pass

        # Source 3: Camera person detection
        zone_cameras = getattr(zone, "zone_cameras", None) or []
        if zone_cameras:
            possible += 1
            for camera_entity in zone_cameras:
                state = self.hass.states.get(camera_entity)
                if state and state.state == "on":
                    confirmed += 1
                    break  # One camera confirmation is enough

        # Source 4: Multiple occupied rooms (only possible if zone has 2+ rooms)
        rooms = getattr(zone, "rooms", []) or []
        if len(rooms) >= 2:
            possible += 1
            try:
                room_conditions = getattr(zone, "room_conditions", []) or []
                occupied_count = sum(
                    1 for rc in room_conditions if getattr(rc, "occupied", False)
                )
                if occupied_count >= 2:
                    confirmed += 1
            except Exception:  # noqa: BLE001
                pass

        return confirmed, possible

    def get_next_state_prediction(self) -> dict:
        """Return the next-state prediction in the D1 PWA contract shape.

        Delegates to ``self._routine_forecaster`` (see
        ``routine_forecaster.py``) when it is set AND the cold-boot
        settle gate has released. During boot-settle or when the
        forecaster is unavailable (DB down, init failed) we emit the
        graceful-degrade placeholder shape — keeps the PWA tile stable
        and out-of-vocab leaks impossible (Bug Class #22, #29, #37).

        Output keys (PWA contract — DO NOT change shape):
          state, confidence, predicted_at_iso, model, current_state,
          transition_eta_minutes

        See ``docs/planning/PLANNING_routine_awareness_next_state_forecaster.md``.
        TODO(v4.7.x): legacy hook removed — forecaster now lives on this
        coordinator (``self._routine_forecaster``), not in hass.data.
        """
        predicted_at_iso = dt_util.utcnow().isoformat()
        current_state = self.house_state

        forecaster = getattr(self, "_routine_forecaster", None)
        boot_settle_done = getattr(self, "_boot_settle_done", True)
        if forecaster is not None and boot_settle_done:
            try:
                prediction = forecaster.predict(current_state)
                if isinstance(prediction, dict) and "state" in prediction:
                    return prediction
            except Exception:  # noqa: BLE001 — defensive: NEVER let the
                # forecaster crash the sensor read path.
                _LOGGER.debug(
                    "RoutineForecaster.predict raised — falling back to "
                    "placeholder shape",
                    exc_info=True,
                )

        # Graceful degrade — preserves PWA contract when the forecaster
        # is unavailable (boot, DB down, init failed).
        return {
            "state": "unknown",
            "confidence": 0.0,
            "predicted_at_iso": predicted_at_iso,
            "model": "placeholder_v0",
            "current_state": current_state,
            "transition_eta_minutes": None,
        }

    # ------------------------------------------------------------------
    # Cold-boot away-actuation storm mitigation — Gate 1 release callbacks
    # ------------------------------------------------------------------
    def _release_boot_settle(self, reason: str) -> None:
        """Idempotent gate-flip used by all three release paths.

        Predicate A (real_input) and B (ha_started, timeout) all converge
        here. Subsequent calls are no-ops so duplicate release paths firing
        late (e.g., a timeout that races with the HA-started event) cannot
        emit duplicate log lines or stomp on the recorded reason.
        """
        if self._boot_settle_done:
            return
        self._boot_settle_done = True
        self._boot_settle_release_reason = reason
        # Occupancy substrate unification cycle (D6): release the substrate's
        # dispatch-suppression gate at the same moment the presence
        # coordinator's own gate releases. Emits ONE synthetic
        # SIGNAL_SUBSTRATE_KIND_CHANGED per (room, kind) slot whose seeded
        # state is True (False slots emit nothing — consumers default False).
        try:
            if self._substrate is not None:
                self._substrate.release_boot_settle()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "OccupancySubstrate: release_boot_settle raised (non-fatal)",
                exc_info=True,
            )
        # Routine forecaster B-1 (review): trigger the deferred initial
        # DB load now that the cold-boot window has closed. Idempotent;
        # the interval-tick backstop covers the case where the
        # forecaster doesn't exist yet (DB wasn't ready at setup time).
        try:
            forecaster = getattr(self, "_routine_forecaster", None)
            if forecaster is not None:
                self.hass.async_create_task(
                    forecaster.async_trigger_initial_refresh()
                )
        except Exception:  # noqa: BLE001 — defensive: NEVER let the
            # forecaster's first load crash the boot-settle release path.
            _LOGGER.debug(
                "RoutineForecaster: async_trigger_initial_refresh "
                "scheduling raised (non-fatal)",
                exc_info=True,
            )
        if reason == "timeout":
            _LOGGER.warning(
                "Boot-settle: released via TIMEOUT after %ss (no real input "
                "observed and HA-started event did not fire) — actuation will "
                "now proceed on next inference tick",
                BOOT_SETTLE_TIMEOUT_SECONDS,
            )
        else:
            _LOGGER.info(
                "Boot-settle: released via %s — actuation will now proceed",
                reason,
            )

    @callback
    def _on_ha_started_release_boot_settle(self, _event: Any) -> None:
        """EVENT_HOMEASSISTANT_STARTED listener — Predicate B path 1."""
        self._release_boot_settle("ha_started")

    @callback
    def _timeout_release_boot_settle(self, _now: Any = None) -> None:
        """Failsafe timeout — Predicate B path 2. Bounded by
        BOOT_SETTLE_TIMEOUT_SECONDS so the gate can NEVER suppress
        actuation indefinitely.
        """
        self._release_boot_settle("timeout")

    async def async_setup(self) -> None:
        """Set up the Presence Coordinator.

        Discovers zones and their rooms, sets up zone trackers,
        subscribes to Census and occupancy signals, discovers zone cameras.
        """
        import asyncio
        # v3.21.0 D2: Create ready event on the event loop (not in __init__)
        self._ready_event = asyncio.Event()

        _LOGGER.info("Setting up Presence Coordinator")

        # Cold-boot away-actuation storm mitigation — Gate 1 init.
        # Scope strictly to genuine HA startup: if HA core has already
        # reached RUNNING (i.e. this is an options-flow reload, not a cold
        # boot), the gate is born already-released so the reload actuates
        # normally. Otherwise schedule both release paths (Predicate B) and
        # let Predicate A flip the gate from inside _run_inference.
        try:
            _ha_running = bool(getattr(self.hass, "is_running", False))
        except Exception:  # noqa: BLE001 — defensive against stub hass
            _ha_running = False
        if _ha_running:
            self._boot_settle_done = True
            self._boot_settle_release_reason = "not_cold_boot"
            _LOGGER.info(
                "Boot-settle: HA already RUNNING — gate released at setup "
                "(reload path, not cold boot)"
            )
        else:
            self._boot_settle_started_utc = dt_util.utcnow()
            from homeassistant.helpers.event import async_call_later  # noqa: PLC0415
            try:
                from homeassistant.const import EVENT_HOMEASSISTANT_STARTED  # noqa: PLC0415
            except Exception:  # noqa: BLE001 — defensive (older HA shapes / test stubs)
                EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
            # Predicate B path 1: EVENT_HOMEASSISTANT_STARTED.
            try:
                _unsub_ha_started = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    self._on_ha_started_release_boot_settle,
                )
                self._unsub_listeners.append(_unsub_ha_started)
            except Exception:  # noqa: BLE001 — defensive (bus may be a stub in tests)
                _LOGGER.debug(
                    "Boot-settle: failed to register EVENT_HOMEASSISTANT_STARTED listener",
                    exc_info=True,
                )
            # Predicate B path 2: failsafe timeout — guarantees release
            # within BOOT_SETTLE_TIMEOUT_SECONDS even if Predicate A and
            # the HA-started event both fail to fire (empty house cold boot
            # with no sensors changing state).
            try:
                _unsub_timeout = async_call_later(
                    self.hass,
                    BOOT_SETTLE_TIMEOUT_SECONDS,
                    self._timeout_release_boot_settle,
                )
                self._unsub_listeners.append(_unsub_timeout)
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "Boot-settle: failed to register failsafe timeout",
                    exc_info=True,
                )

        # v3.6.0.3: Instantiate anomaly detector FIRST so it's always available
        # even if discovery fails. Minimum 24 samples (~1 day of hourly
        # observations) before activation.
        # v4.6.3 D10: sensitivity bucket from CM entry options.
        from .coordinator_diagnostics import AnomalyDetector
        from ..const import (  # noqa: PLC0415
            CONF_PRESENCE_ANOMALY_SENSITIVITY,
            DEFAULT_ANOMALY_SENSITIVITY,
            ANOMALY_SENSITIVITY_MULTIPLIERS,
            ENTRY_TYPE_COORDINATOR_MANAGER,
        )
        _presence_sensitivity = DEFAULT_ANOMALY_SENSITIVITY
        try:
            for _ce in self.hass.config_entries.async_entries(DOMAIN):
                if _ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    _presence_sensitivity = {**_ce.data, **_ce.options}.get(
                        CONF_PRESENCE_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                    )
                    break
        except Exception:
            pass
        self.anomaly_detector = AnomalyDetector(
            hass=self.hass,
            coordinator_id="presence",
            metric_names=self.PRESENCE_METRICS,
            minimum_samples=24,
            sensitivity_multiplier=ANOMALY_SENSITIVITY_MULTIPLIERS.get(_presence_sensitivity, 1.0),
            # v4.6.5.3 surface fix: census_count + zone_occupied_count fire
            # in-memory (degenerate-shape per v4.6.3.1 / v4.6.3.3 doctrine) but
            # are suppressed from persistence — exclude them from the sensor's
            # severity calculation so it doesn't permanently show critical.
            suppressed_metric_names=PRESENCE_SUPPRESSED_FROM_PERSISTENCE,
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception:
            _LOGGER.debug("Could not load presence anomaly baselines (non-fatal)", exc_info=True)

        # v4.6.5.1 P4 (M3 fix from v4.6.4 review): hydrate _transitions_today
        # from house_state_log so the daily counter survives reload/restart.
        # Without this, the counter resets to 0 on every restart and the
        # transition_count_daily baseline distribution skews low —
        # biasing future thrashy-day anomalies to fire more than they should.
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                today_iso = dt_util.now().date().isoformat()
                count = await db.count_house_state_changes_since(today_iso)
                self._transitions_today = count
                self._transition_reset_date = today_iso
                _LOGGER.info(
                    "Hydrated _transitions_today=%d from house_state_log (since %s)",
                    count, today_iso,
                )
        except Exception:
            _LOGGER.debug(
                "Could not hydrate _transitions_today from house_state_log (non-fatal)",
                exc_info=True,
            )

        # Routine-Awareness Next-State Forecaster — replaces the
        # placeholder_v0 stub behind sensor.ura_presence_coordinator_next_state.
        # In-memory frequency/recency aggregate over house_state_log;
        # bounded read, no new DB writes. See
        # docs/planning/PLANNING_routine_awareness_next_state_forecaster.md.
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                from .routine_forecaster import RoutineForecaster  # noqa: PLC0415
                # B-3 (review): re-setup leak guard. If a forecaster was
                # already attached (re-entrant setup path), shut it down
                # first so its timer + dispatcher subscription release
                # cleanly before we install a new instance — otherwise
                # the prior one keeps ticking against the same hass
                # (untracked-background-tasks bug class #19).
                existing = getattr(self, "_routine_forecaster", None)
                if existing is not None:
                    try:
                        await existing.async_shutdown()
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "RoutineForecaster: shutdown of prior instance "
                            "raised during re-setup (non-fatal)",
                            exc_info=True,
                        )
                    self._routine_forecaster = None
                forecaster = RoutineForecaster(self.hass, db)
                await forecaster.async_setup()
                self._routine_forecaster = forecaster
                _LOGGER.info(
                    "RoutineForecaster: attached to PresenceCoordinator"
                )
            else:
                _LOGGER.debug(
                    "RoutineForecaster: database not yet available — "
                    "next-state prediction will degrade to placeholder shape"
                )
        except Exception:
            _LOGGER.debug(
                "RoutineForecaster: setup failed (non-fatal); "
                "next-state prediction will degrade to placeholder shape",
                exc_info=True,
            )

        # v3.19.0: Read face recognition toggle from integration config
        try:
            from ..const import CONF_FACE_RECOGNITION_ENABLED, ENTRY_TYPE_INTEGRATION, CONF_ENTRY_TYPE
            for config_entry in self.hass.config_entries.async_entries(DOMAIN):
                if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                    merged = {**config_entry.data, **config_entry.options}
                    self._face_recognition_enabled = merged.get(CONF_FACE_RECOGNITION_ENABLED, False)
                    break
        except Exception:
            self._face_recognition_enabled = False

        # v3.6.0.3: Wrap discovery/subscription in try/except so partial
        # failures don't prevent the coordinator from functioning.
        try:
            # Build room → area_id mapping from room config entries
            self._build_room_area_map()

            # Discover zones and create trackers
            self._discover_zones()

            # Occupancy substrate unification cycle (D1 + D2):
            # Build the substrate BEFORE the zone-tier Tier-1 discovery
            # call so the substrate's CONF-list-driven discovery is the
            # single source of truth for which entities are subscribed.
            # The zone tier no longer area-sweeps — it subscribes to
            # SIGNAL_SUBSTRATE_KIND_CHANGED and routes per-kind edges
            # into ``tracker.update_room_occupancy`` with the same call
            # shape the prior state-change callback used.
            from .occupancy_substrate import OccupancySubstrate  # noqa: PLC0415
            self._substrate = OccupancySubstrate(self.hass)
            # v5.10.0 fix-up FIX-2 (A-CRIT-1): register the substrate in
            # hass.data so cross-coordinator readers (e.g. MusicFollowing
            # D3 guest-in-source-room guard at music_following.py:452)
            # have a real writer to bind to. Mirrors the MusicFollowing
            # singleton registration at __init__.py:1910. Cleared in
            # async_teardown alongside self._substrate = None (see below).
            try:
                self.hass.data.setdefault(DOMAIN, {})["occupancy_substrate"] = self._substrate
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "OccupancySubstrate hass.data registration failed",
                    exc_info=True,
                )
            # Mirror the boot-settle gate state: if HA is already RUNNING
            # (options-flow reload, not cold boot) the gate is born
            # released, so the substrate must also dispatch immediately.
            if self._boot_settle_done:
                # release_boot_settle() is idempotent and emits synthetic
                # True-slot signals AFTER discovery; do it after setup
                # below so the seed has already populated ``_raw_state``.
                pass
            await self._substrate.async_setup()
            # If the coordinator's own boot-settle gate has already
            # released (reload path), release the substrate's gate now
            # too so live edges dispatch immediately.
            if self._boot_settle_done:
                try:
                    self._substrate.release_boot_settle()
                except Exception:  # noqa: BLE001 — defensive
                    _LOGGER.debug(
                        "OccupancySubstrate: reload-path release raised",
                        exc_info=True,
                    )
            # Zone-tier subscription (D2): replace the prior state-change
            # listener path with a substrate signal subscription.
            # B-H1 fix-up: async_dispatcher_connect imported at module top
            # (alongside async_dispatcher_send) to avoid Bug Class #34
            # function-local shadow-binding hazard.
            from .signals import (  # noqa: PLC0415
                SIGNAL_ROOM_ENTRY_LIFECYCLE,
                SIGNAL_SUBSTRATE_KIND_CHANGED,
            )
            self._substrate_signal_unsub = async_dispatcher_connect(
                self.hass,
                SIGNAL_SUBSTRATE_KIND_CHANGED,
                self._on_substrate_kind_changed,
            )
            self._unsub_listeners.append(self._substrate_signal_unsub)

            # Substrate re-subscribe cycle (D3): subscribe to per-ROOM
            # lifecycle events dispatched from ROOM async_setup_entry /
            # async_unload_entry / _async_update_listener suppressed
            # writes (WRITER sites: __init__.py:~3505 loaded / ~3830
            # unloaded / ~4860 options_updated). Restores the pre-v4.7.24
            # (commit e165e1cb) per-room-onboarding guarantee: a room
            # added WITHOUT restart is event-driven immediately.
            # Bug Class #50 guardrail: unsub appended to
            # ``_unsub_listeners``, which — per 2026-07-10 grep of this
            # file — is only cleared by ``async_teardown``. No periodic
            # rebuild path clears it (see :2811-2836 fan re-arm which
            # uses selective .remove(), and :3423-3433 camera re-arm
            # which does the same; both patterns leave sibling unsubs
            # intact). Discipline mirrors v5.10.0 reconciler wiring.
            self._unsub_listeners.append(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_ROOM_ENTRY_LIFECYCLE,
                    self._on_room_entry_lifecycle,
                )
            )

            # F5 fix-up (C-LOW-1): sweep any room that loaded BETWEEN
            # the substrate's discovery walk and the subscriber attach
            # above — its lifecycle dispatch would have been missed
            # otherwise. refresh_subscriptions() is a no-op if nothing
            # actually diffs. Tracked per F3.
            try:
                _sweep_task = self.hass.async_create_task(
                    self._substrate.refresh_subscriptions()
                )
                self._substrate_refresh_tasks.add(_sweep_task)
                _sweep_task.add_done_callback(
                    self._substrate_refresh_tasks.discard
                )
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "Cold-boot substrate refresh sweep failed to schedule",
                    exc_info=True,
                )

            # Discover and subscribe to room occupancy sensors (Tier 1).
            # Post-substrate this is a thin compatibility shim — the actual
            # state-change subscription lives in the substrate. We keep the
            # call so the legacy `register_entity` hooks still fire for any
            # consumer reading `tracker._entity_to_room`.
            self._discover_room_sensors()

            # Discover and subscribe to zone cameras (Tier 2)
            self._discover_zone_cameras()

            # Provenance-split cycle (D3): subscribe to per-room CONF_FANS
            # state-change events so the fan-interference diagnostic
            # has live `_fan_on_rooms` truth before the next
            # _run_inference tick. Observation-only — zone-tracker
            # `mode` output is unchanged. See module-level docstring on
            # `_compute_fan_interference_rooms` for the primitive.
            self._discover_room_fans()

            # v4.7.2 D5: Discover and subscribe to guest rooms (Feature B)
            self._discover_guest_rooms()

            # Subscribe to geofence (person entity state changes)
            self._subscribe_geofence()

            # Subscribe to census updates
            # B-H1 fix-up: async_dispatcher_connect now imported at
            # module top — no function-local import needed.
            self._unsub_listeners.append(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_CENSUS_UPDATED,
                    self._handle_census_update,
                )
            )

            # Zone Delete Flow (fix-up R4 / B-HIGH-2): presence lives on
            # the parent entry and does NOT reload when a ZM options
            # mutation fires, so the ``_discover_zones`` prune block is
            # dead code on the delete path. Subscribe here so the prune
            # runs whenever the config_flow deletes a zone. Unsub tracked
            # via ``_unsub_listeners`` per Bug Class #50.
            self._unsub_listeners.append(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_ZM_ZONES_UPDATED,
                    self._handle_zm_zones_updated,
                )
            )

            # OC Phase 5 Pillar A: subscribe to SIGNAL_OPTIMIZER_INTENT so
            # this coordinator can veto Optimizer actuation on presence
            # input sensors (mmWave, occupancy). Bug Class #50 guardrail:
            # the unsub is appended to ``_unsub_listeners`` AND tracked
            # separately for double-subscribe protection on re-setup.
            if self._optimizer_intent_unsub is None:
                self._optimizer_intent_unsub = async_dispatcher_connect(
                    self.hass,
                    SIGNAL_OPTIMIZER_INTENT,
                    self._on_optimizer_intent,
                )
                self._unsub_listeners.append(self._optimizer_intent_unsub)

            # Periodic inference (every 60 seconds for time-based transitions + camera timeouts)
            self._unsub_listeners.append(
                async_track_time_interval(
                    self.hass,
                    self._periodic_inference,
                    timedelta(seconds=60),
                )
            )
        except Exception:
            _LOGGER.exception("Error during presence discovery (non-fatal)")

        # v3.6.0-c2.3: Seed census count from existing data before first
        # inference. Without this, _census_count=0 → infers "away" even
        # when people are home. Read from census manager if available,
        # else fall back to the identified_persons sensor state.
        try:
            census_mgr = self.hass.data.get(DOMAIN, {}).get(
                "camera_integration_manager"
            )
            if census_mgr and hasattr(census_mgr, "last_result"):
                last = census_mgr.last_result
                if last is not None:
                    self._census_count = last.house.total_persons
                    _LOGGER.info(
                        "Seeded census count from manager: %d",
                        self._census_count,
                    )
            if self._census_count == 0:
                # Fallback: read from sensor state
                state = self.hass.states.get(
                    f"sensor.{DOMAIN}_identified_persons_in_house"
                )
                if state and state.state not in ("unknown", "unavailable"):
                    try:
                        self._census_count = int(state.state)
                        _LOGGER.info(
                            "Seeded census count from sensor: %d",
                            self._census_count,
                        )
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            _LOGGER.warning("Failed to seed census count: %s", e)

        # Fan-noise Mode-2 mitigation: build + rehydrate the state machine.
        try:
            from .presence_fan_recheck import FanRecheckManager  # noqa: PLC0415
            self._fan_recheck_manager = FanRecheckManager(self.hass, self)
            await self._fan_recheck_manager.async_setup()
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "FanRecheck: manager setup failed (Mode-2 disabled)",
                exc_info=True,
            )
            self._fan_recheck_manager = None

        # Run initial inference with seeded census count
        await self._run_inference("startup")

        # v3.21.0 D2: Signal readiness so downstream coordinators (HVAC) can
        # safely read house state without racing startup ordering.
        self._ready_event.set()

        _LOGGER.info(
            "Presence Coordinator ready: %d zones tracked",
            len(self._zone_trackers),
        )

    def _build_room_area_map(self) -> None:
        """Build room_name → area_id mapping from room config entries.

        v3.6.0.11: Falls back to matching room names against HA area registry
        names when CONF_AREA_ID is not configured on the room entry.
        """
        from ..const import CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM

        # Build name→area_id lookup from HA area registry for fallback
        area_name_to_id: Dict[str, str] = {}
        try:
            from homeassistant.helpers import area_registry as ar
            area_reg = ar.async_get(self.hass)
            for area in area_reg.async_list_areas():
                area_name_to_id[area.name.lower()] = area.area_id
        except Exception:
            _LOGGER.debug("Cannot access area registry for room area fallback")

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                room_name = entry.data.get(CONF_ROOM_NAME, "")
                area_id = (
                    entry.options.get(CONF_AREA_ID)
                    or entry.data.get(CONF_AREA_ID)
                )
                # Fallback: match room name to HA area name
                if not area_id and room_name:
                    area_id = area_name_to_id.get(room_name.lower())
                    if area_id:
                        _LOGGER.debug(
                            "Room '%s' area_id resolved via area registry: %s",
                            room_name, area_id,
                        )
                if room_name and area_id:
                    self._room_area_ids[room_name] = area_id

        _LOGGER.info(
            "Room area map: %d rooms mapped to areas: %s",
            len(self._room_area_ids),
            {k: v for k, v in self._room_area_ids.items()},
        )

    def _invalidate_adjacency_cache(self) -> None:
        """Clear the cached fan-interference adjacency map.

        B-M1 fix-up: any discovery path that rewires rooms (zone or
        room discovery, config-flow update) must invalidate the
        cache so the gate rebuilds from current config on next read.
        """
        self._adjacency_cache = None

    def _rebuild_adjacency_cache(self) -> None:
        """Rebuild the room_name -> [adjacent_room_name] cache.

        B-M1 fix-up: the Layer-1 fan-interference gate previously
        walked every URA config entry every tick to resolve
        `CONF_ADJACENT_ROOMS`. Adjacency only changes on options-flow
        save; cache it once at discovery (or lazily on first gate
        call) and let the gate read O(1). Forward-compat note:
        unresolved tokens are kept as-is (the operator may have
        configured a bare room_name) — pruning stale entry_id
        references after room deletion is deferred (review C2 / B-L1
        in the fix-up doc).
        """
        try:
            from ..const import CONF_ADJACENT_ROOMS  # noqa: PLC0415
        except Exception:  # noqa: BLE001 — defensive (const import is safe)
            self._adjacency_cache = {}
            return
        adjacency: Dict[str, List[str]] = {}
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
            id_to_name: Dict[str, str] = {}
            name_to_adj_ids: Dict[str, List[str]] = {}
            for entry in entries:
                try:
                    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                        continue
                except Exception:  # noqa: BLE001
                    continue
                room_name = (
                    entry.data.get(CONF_ROOM_NAME, "") or entry.title or ""
                )
                if not room_name:
                    continue
                id_to_name[entry.entry_id] = room_name
                merged = {**entry.data, **(entry.options or {})}
                adj_raw = merged.get(CONF_ADJACENT_ROOMS, []) or []
                if isinstance(adj_raw, (list, tuple)):
                    name_to_adj_ids[room_name] = list(adj_raw)
            for room_name, adj_ids in name_to_adj_ids.items():
                resolved: List[str] = []
                for tok in adj_ids:
                    if not isinstance(tok, str) or not tok:
                        continue
                    if tok in id_to_name:
                        resolved.append(id_to_name[tok])
                    else:
                        # Forward-compat: bare room_name token. Stale
                        # entry_id references after room deletion are
                        # deferred (review C2 — runtime-safe).
                        resolved.append(tok)
                adjacency[room_name] = resolved
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "Fan-noise D1: adjacency cache rebuild failed (non-fatal)",
                exc_info=True,
            )
            adjacency = {}
        self._adjacency_cache = adjacency

    def get_adjacent_rooms(self, room_name: str) -> List[str]:
        """Return the list of adjacent room names for a given room.

        Public method for the room-tier fan-recheck state machine — lets it
        read the cached adjacency map without rebuilding its own. Lazily
        builds the cache on first call (mirrors the zone-tier gate's lazy
        path at presence.py:2825-2827).
        """
        if not room_name:
            return []
        if self._adjacency_cache is None:
            self._rebuild_adjacency_cache()
        return list((self._adjacency_cache or {}).get(room_name, []))

    def _prune_stale_zone_trackers(self, all_entries=None) -> None:
        """Zone Delete Flow (fix-up R4 / B-HIGH-2): prune any tracker whose
        zone is no longer present in a ZM zones dict OR in a legacy
        ENTRY_TYPE_ZONE entry.

        Callable from BOTH ``_discover_zones`` (defense-in-depth on every
        rebuild) AND ``_handle_zm_zones_updated`` (the delete-path signal
        target — presence lives on the parent entry and does not reload on
        a ZM options mutation, so the rebuild alone is dead code on that
        path). Safe to call multiple times; idempotent.
        """
        from ..const import (
            CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE, ENTRY_TYPE_ZONE_MANAGER,
            CONF_ZONE_NAME,
        )
        if all_entries is None:
            try:
                all_entries = self.hass.config_entries.async_entries(DOMAIN)
            except Exception:  # noqa: BLE001
                return
        current_zone_names: set[str] = set()
        for _e in all_entries:
            _et = _e.data.get(CONF_ENTRY_TYPE)
            if _et == ENTRY_TYPE_ZONE:
                _zn = _e.data.get(CONF_ZONE_NAME, "")
                if _zn:
                    current_zone_names.add(_zn)
            elif _et == ENTRY_TYPE_ZONE_MANAGER:
                _opts = _e.options.get("zones", {}) or {}
                _data = _e.data.get("zones", {}) or {}
                current_zone_names.update(_opts.keys())
                current_zone_names.update(_data.keys())
        stale = [zn for zn in list(self._zone_trackers.keys())
                 if zn not in current_zone_names]
        for zn in stale:
            self._zone_trackers.pop(zn, None)
            _LOGGER.info(
                "Zone tracker pruned (zone no longer in config): %s", zn,
            )

    def _handle_zm_zones_updated(self, payload=None) -> None:
        """Zone Delete Flow (fix-up R4 / B-HIGH-2): SIGNAL_ZM_ZONES_UPDATED
        target.

        Presence lives on the parent entry — a ZM options mutation does
        NOT reload presence, so the ``_discover_zones`` prune block would
        never re-run on the delete path. This handler re-runs the prune
        directly.
        """
        try:
            self._prune_stale_zone_trackers()
            _LOGGER.debug(
                "Presence: zone tracker prune via SIGNAL_ZM_ZONES_UPDATED "
                "complete (payload=%s)", payload,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "Presence: zone tracker prune via signal failed",
                exc_info=True,
            )

    def _discover_zones(self) -> None:
        """Discover zones and their rooms from config entries.

        v3.6.0.2: Full diagnostic logging + entry ID resolution.
        """
        from ..const import (
            CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE, ENTRY_TYPE_ZONE_MANAGER,
            CONF_ZONE_NAME, CONF_ROOM_NAME,
        )

        all_entries = self.hass.config_entries.async_entries(DOMAIN)
        entry_types = [e.data.get(CONF_ENTRY_TYPE, "unknown") for e in all_entries]
        _LOGGER.info(
            "Zone discovery: %d config entries, types: %s",
            len(all_entries), entry_types,
        )

        # Zone Delete Flow D3: prune any tracker whose zone is no longer
        # present in the ZM zones dict OR in a legacy ENTRY_TYPE_ZONE entry.
        # Extracted into ``_prune_stale_zone_trackers`` (fix-up R4 / B-HIGH-2)
        # so it can be re-invoked on the SIGNAL_ZM_ZONES_UPDATED path — the
        # presence coordinator lives on the parent entry and does NOT reload
        # when a ZM options mutation fires, so the ``_discover_zones`` call
        # site alone was dead code on the delete path.
        self._prune_stale_zone_trackers(all_entries)

        # Legacy: individual ENTRY_TYPE_ZONE entries
        for entry in all_entries:
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                zone_name = entry.data.get(CONF_ZONE_NAME, "")
                room_names = list(
                    entry.options.get(CONF_ZONE_ROOMS, [])
                    or entry.data.get(CONF_ZONE_ROOMS, [])
                )
                if zone_name and room_names:
                    self._zone_trackers[zone_name] = ZonePresenceTracker(
                        hass=self.hass,
                        zone_name=zone_name,
                        room_names=room_names,
                    )
                    _LOGGER.info(
                        "Zone tracker created (legacy): %s with rooms %s",
                        zone_name, room_names,
                    )

        # Zone Manager entry: zones in data["zones"] or options["zones"]
        zm_found = False
        for entry in all_entries:
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                zm_found = True
                # Check both data and options for zones
                data_zones = entry.data.get("zones", {})
                opts_zones = entry.options.get("zones", {})
                _LOGGER.info(
                    "Zone Manager found: entry_id=%s, data has %d zones, options has %d zones, "
                    "data keys: %s, options keys: %s",
                    entry.entry_id,
                    len(data_zones), len(opts_zones),
                    list(data_zones.keys()) if data_zones else "[]",
                    list(opts_zones.keys()) if opts_zones else "[]",
                )

                # Options takes priority over data (config flow writes to options)
                zones_data = opts_zones if opts_zones else data_zones

                for zone_name, zone_cfg in zones_data.items():
                    if zone_name in self._zone_trackers:
                        continue
                    raw_rooms = list(zone_cfg.get(CONF_ZONE_ROOMS, []))
                    _LOGGER.info(
                        "Zone '%s' raw room refs: %s", zone_name, raw_rooms,
                    )
                    # Resolve entry IDs to room names
                    room_names = []
                    for room_ref in raw_rooms:
                        room_entry = self.hass.config_entries.async_get_entry(room_ref)
                        if room_entry:
                            name = room_entry.data.get(CONF_ROOM_NAME, "")
                            if name:
                                room_names.append(name)
                                _LOGGER.debug(
                                    "  Resolved %s -> '%s'", room_ref[:12], name,
                                )
                                continue
                        # Fallback: treat as a room name directly
                        room_names.append(room_ref)
                        _LOGGER.debug(
                            "  Fallback (no entry): %s used as-is", room_ref[:20],
                        )
                    if zone_name and room_names:
                        self._zone_trackers[zone_name] = ZonePresenceTracker(
                            hass=self.hass,
                            zone_name=zone_name,
                            room_names=room_names,
                        )
                        _LOGGER.info(
                            "Zone tracker created: '%s' with %d rooms: %s",
                            zone_name, len(room_names), room_names,
                        )
                    else:
                        _LOGGER.warning(
                            "Zone '%s' skipped: zone_name=%r, room_names=%s",
                            zone_name, zone_name, room_names,
                        )
                break

        if not zm_found:
            _LOGGER.warning("No Zone Manager entry found among %d entries", len(all_entries))

        # C2/C3 fix-up: rebuild the room -> zone reverse lookup so hot
        # paths can do O(1) tracker resolution instead of walking all
        # zones per call. Cleared first so a re-discovery that drops a
        # room leaves no stale mapping. If the same room appears in
        # multiple zones (pathological config), FIRST-writer-wins —
        # matches the prior `for tracker in ...: if room in
        # tracker.room_names: ...; break` lookup pattern used by the D5
        # attr block in binary_sensor.py.
        self._room_to_zone.clear()
        for _zone_name, _tracker in self._zone_trackers.items():
            for _room_name in _tracker.room_names:
                if _room_name not in self._room_to_zone:
                    self._room_to_zone[_room_name] = _zone_name

        # B-M1 fix-up: rebuild adjacency cache once at zone discovery
        # so the per-tick gate doesn't walk all config entries.
        self._rebuild_adjacency_cache()

        _LOGGER.info(
            "Zone discovery complete: %d zone trackers created: %s",
            len(self._zone_trackers), list(self._zone_trackers.keys()),
        )

    # ------------------------------------------------------------------
    # Tier 1: Room Occupancy Sensors (via entity registry area_id)
    # ------------------------------------------------------------------

    def _discover_room_sensors(self) -> None:
        """Register CONF-listed Tier-1 entities with zone trackers.

        Occupancy substrate unification cycle (D2). The prior area-sweep
        body (entity-registry walk by name + area_id) is DELETED — it was
        the source of the Jaya/Exercise sensor-set divergence between the
        room tier (CONF-driven) and the zone tier (area-sweep). The
        ``OccupancySubstrate`` (built earlier in ``async_setup``) is now
        the canonical state-change subscription set, sourced exclusively
        from the operator's curated ``CONF_MOTION_SENSORS`` /
        ``CONF_MMWAVE_SENSORS`` / ``CONF_OCCUPANCY_SENSORS`` lists.

        Substrate sits BENEATH the room + zone tiers — it is NOT a new
        tier and does not replace either of them. Both tiers continue to
        apply their own legitimate temporal smoothing on top of the
        substrate's raw view.

        This method now performs only:

          * Cache invalidation (entity_kind_cache, adjacency cache) so
            re-discovery callers still see fresh state.
          * Per-tracker ``register_entity`` calls for every CONF-listed
            entity in that tracker's rooms, so ``tracker._entity_to_room``
            mappings remain populated for downstream consumers (e.g.
            ``_handle_occupancy_change`` callers that haven't yet been
            migrated, diagnostic dumps).
          * Seed the per-kind ``_room_provenance`` from the substrate's
            ``_raw_state`` snapshot — preserves the v4.7.18.1 B-HIGH-1
            invariant that the first ``_run_inference("startup")`` tick
            observes accurate provenance even before state-change events
            have fired.

        It does NOT register state-change listeners — those are owned by
        the substrate's single canonical subscription set.
        """
        # M1 fix-up: invalidate the (entity_id, room_name) -> kind cache
        # on every re-discovery so a config-flow update that rewires
        # CONF_*_SENSORS lists picks up the new shape on the next firing.
        self._entity_kind_cache.clear()
        # B-M1 fix-up: room re-discovery may pick up a rewired
        # CONF_ADJACENT_ROOMS list — invalidate the adjacency cache
        # so the next gate call rebuilds from the current entries.
        self._invalidate_adjacency_cache()

        # Resolve the substrate snapshot once for seeding below.
        substrate = self._substrate
        if substrate is None:
            _LOGGER.debug(
                "Substrate unification: _discover_room_sensors called "
                "before substrate setup — skipping (no listeners to "
                "register; substrate owns state-change subscriptions)"
            )
            return

        # Walk every ROOM entry's CONF lists and register entities into
        # the matching zone tracker via the existing register_entity API.
        # This keeps ``tracker._entity_to_room`` populated so any consumer
        # that still walks it (e.g. live diagnostics) finds the same set
        # the substrate is subscribed to.
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
        except Exception:  # noqa: BLE001 — defensive: registry mid-reload
            _LOGGER.warning(
                "Cannot enumerate config entries — Tier-1 register_entity "
                "pass skipped",
                exc_info=True,
            )
            entries = []

        registered_count = 0
        seeded_count = 0
        for entry in entries:
            try:
                merged = {**(entry.data or {}), **(entry.options or {})}
            except Exception:  # noqa: BLE001
                continue
            if merged.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            room_name = merged.get(CONF_ROOM_NAME)
            if not room_name:
                continue

            # Find the tracker that owns this room.
            tracker: Optional[ZonePresenceTracker] = None
            zone_name = self._room_to_zone.get(room_name)
            if zone_name is not None:
                tracker = self._zone_trackers.get(zone_name)
            if tracker is None:
                # Cold-start fallback — the cache may not be primed yet
                # if discover_zones order changes in the future. Walk.
                for _zone_name, _t in self._zone_trackers.items():
                    if room_name in _t.room_names:
                        tracker = _t
                        zone_name = _zone_name
                        break
            if tracker is None:
                continue

            # Collect CONF entities for this room across all three kinds.
            for conf_key in (
                CONF_MOTION_SENSORS,
                CONF_MMWAVE_SENSORS,
                CONF_OCCUPANCY_SENSORS,
            ):
                for entity_id in (merged.get(conf_key, []) or []):
                    if not entity_id:
                        continue
                    tracker.register_entity(entity_id, room_name)
                    registered_count += 1

            # Seed the tracker's per-kind provenance from the substrate's
            # current raw view (v4.7.18.1 B-HIGH-1 seed invariant).
            try:
                kinds = substrate.get_room_kinds(room_name)
            except Exception:  # noqa: BLE001 — defensive
                kinds = {}
            any_true = False
            for kind, value in kinds.items():
                if value:
                    any_true = True
                    tracker.update_room_occupancy(
                        room_name, True, kind=kind,
                    )
                    seeded_count += 1
            if not any_true:
                # B-LOW-1 fix-up parity: ensure the room key exists in
                # ``_room_provenance`` even when no kind is currently
                # firing, so set(_room_provenance.keys()) ==
                # set(_room_occupied.keys()) (Invariant 4).
                tracker.update_room_occupancy(room_name, False)

        _LOGGER.info(
            "Substrate-driven Tier-1 registration: %d (entity, room) "
            "register_entity calls, %d True-kind seed write(s) across "
            "%d trackers",
            registered_count, seeded_count, len(self._zone_trackers),
        )

    @callback
    def _on_substrate_kind_changed(
        self,
        room_name: str,
        kind: str,
        new_state: bool,
    ) -> None:
        """Substrate signal handler — fan out into the zone tier.

        Occupancy substrate unification cycle (D2). Replaces the prior
        state-change-event subscription on the area-sweep entity set.
        The substrate guarantees ``room_name`` matches the operator's
        ``CONF_ROOM_NAME`` and ``kind`` ∈ TIER1_KINDS — so the call
        shape ``tracker.update_room_occupancy(room, new_state, kind=kind)``
        is identical to the prior live-path call and ``_room_provenance``
        writes are unchanged.
        """
        tracker = self.tracker_for_room(room_name)
        if tracker is None:
            _LOGGER.debug(
                "Substrate edge for unknown room '%s' (kind=%s, new=%s) "
                "— no tracker; ignored",
                room_name, kind, new_state,
            )
            return
        tracker.update_room_occupancy(room_name, new_state, kind=kind)
        # Trigger an inference cycle the same way the prior
        # `_handle_occupancy_change` did — preserves zone-tier reaction
        # cadence on a per-kind edge.
        self.hass.async_create_task(self._run_inference("occupancy_change"))

    @callback
    def _on_room_entry_lifecycle(
        self,
        entry_id: str,
        room_name: str | None,
        action: str,
    ) -> None:
        """Handle SIGNAL_ROOM_ENTRY_LIFECYCLE — refresh substrate subscriptions.

        WRITER: dispatched from three ROOM lifecycle sites in
        ``__init__.py`` (D1 of the substrate re-subscribe cycle):
          - ROOM ``async_setup_entry`` (action="loaded")
          - ROOM ``async_unload_entry`` (action="unloaded")
          - ``_async_update_listener`` suppressed-write branch
            (action="options_updated")

        The refresh is a coroutine on ``OccupancySubstrate``; schedule it
        as a background task so this @callback stays sync.
        """
        if self._substrate is None:
            # Presence coordinator not fully initialized yet — substrate
            # will pick this room up at its own async_setup() enumeration.
            _LOGGER.debug(
                "Room entry lifecycle (%s) for '%s' before substrate "
                "constructed — ignored (async_setup will enumerate)",
                action, room_name,
            )
            return
        _LOGGER.info(
            "Room entry lifecycle: entry_id=%s room=%s action=%s — "
            "scheduling substrate refresh",
            entry_id, room_name, action,
        )
        # F3 fix-up (B-HIGH-1): track the task so async_teardown can
        # cancel+gather it before the substrate is torn down; wrap in
        # try/except so a lifecycle event can never propagate a raise
        # up the dispatcher chain.
        try:
            task = self.hass.async_create_task(
                self._substrate.refresh_subscriptions()
            )
            self._substrate_refresh_tasks.add(task)
            task.add_done_callback(self._substrate_refresh_tasks.discard)
        except Exception:  # noqa: BLE001 — defensive: never raise from dispatcher
            _LOGGER.debug(
                "Failed to schedule substrate refresh for %s (%s)",
                room_name, action, exc_info=True,
            )

    # ------------------------------------------------------------------
    # Tier 2: Zone Camera Sensors (via CameraIntegrationManager)
    # ------------------------------------------------------------------

    def _rooms_opting_out_of_camera_presence(self) -> Set[str]:
        """v4.7.16 D4: return the set of room_names with CONF_DISABLE_CAMERA_PRESENCE=True.

        Lazy read of room config entries — no migration helper, absent key
        defaults to False (Bug Class #46 doctrine). Guarded against config
        registry exceptions for boot-race safety.
        """
        opted_out: Set[str] = set()
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.debug(
                "_rooms_opting_out_of_camera_presence: entry walk failed: %s",
                exc,
            )
            return opted_out
        for entry in entries:
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            room_name = entry.data.get("room_name")
            if not room_name:
                continue
            config = {**entry.data, **entry.options}
            if config.get(
                CONF_DISABLE_CAMERA_PRESENCE, DEFAULT_DISABLE_CAMERA_PRESENCE
            ):
                opted_out.add(room_name)
        if opted_out:
            _LOGGER.info(
                "v4.7.16 D4: %d room(s) opting out of camera-presence: %s",
                len(opted_out), sorted(opted_out),
            )
        return opted_out

    def _discover_room_fans(self) -> None:
        """Discover CONF_FANS entities per room and subscribe to state changes.

        Presence provenance-split cycle (D3). Observation-only — the
        listener writes into ``ZonePresenceTracker._fan_on_rooms`` so the
        fan-interference compute helper can read room-level fan truth
        on the NEXT ``_run_inference`` tick. Does NOT change `mode`
        output, consensus arithmetic, or HVAC behavior in any way.

        Resolution path: iterate room ConfigEntries
        (``CONF_ENTRY_TYPE == ENTRY_TYPE_ROOM``), read
        ``CONF_FANS`` from ``data``/``options`` merge per
        v4.7.4.4 Bug Class #46 doctrine, then route each fan entity to
        its owning zone tracker via the existing ``room_names``
        mapping.

        Lifecycle: listener unsubs are appended to
        ``self._unsub_listeners`` so the existing teardown path
        (``async_will_remove_from_hass`` / reload) cleans them up
        correctly. No new lifecycle hook required.
        """
        # H1 + H2 fix-up: clear prior per-tracker fan state before
        # rebuilding. Without this, a re-discovery (e.g. config-flow
        # edit to CONF_FANS, or some future caller invoking
        # `_discover_room_fans` a second time) would leave stale fan
        # entries in `_fan_entity_to_room` and `_fan_on_rooms`, causing
        # the D3 diagnostic to mis-attribute a "previously-fan-room"
        # state to the wrong room. Belt-and-braces: also tear down the
        # prior fan-listener subscription so we don't double-subscribe.
        for tracker in self._zone_trackers.values():
            tracker._fan_entity_to_room.clear()
            tracker._fan_on_rooms.clear()
            # Tier-3 D2: clear per-room fan-on stamps on re-discovery so
            # a re-seeded "on" fan gets a fresh grace clock (mirrors
            # `_fan_on_rooms` reset above).
            tracker._fan_on_since.clear()
            # Fan-transition gate: clear per-room transition stamps on
            # re-discovery so a re-seeded fan does not carry a stale
            # transition timestamp into the new listener wiring.
            tracker._fan_last_transition.clear()
        if self._fan_listener_unsub is not None:
            try:
                self._fan_listener_unsub()
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "Provenance-split D3: prior fan listener unsub raised "
                    "(non-fatal)",
                    exc_info=True,
                )
            try:
                self._unsub_listeners.remove(self._fan_listener_unsub)
            except ValueError:
                pass
            self._fan_listener_unsub = None
        try:
            fan_entity_ids: Set[str] = set()
            # entity_id -> list of (tracker, room_name) — one fan can in
            # principle live in multiple rooms in pathological configs;
            # we accept either by iterating all matches.
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                config = {**(entry.data or {}), **(entry.options or {})}
                room_name = config.get(CONF_ROOM_NAME)
                if not room_name:
                    continue
                fans = config.get(CONF_FANS, []) or []
                if not fans:
                    continue
                for fan_id in fans:
                    fan_entity_ids.add(fan_id)
                    # Seed initial _fan_on_rooms from current state.
                    try:
                        state = self.hass.states.get(fan_id)
                    except Exception:  # pragma: no cover - defensive
                        state = None
                    is_on = bool(
                        state is not None
                        and state.state not in _UNAVAILABLE_STATES
                        and state.state == "on"
                    )
                    # H1 fix-up: `_fan_entity_to_room` is now a declared
                    # tracker attribute (`ZonePresenceTracker.__init__`),
                    # NOT a setattr-monkey-patched dict. Assign into it
                    # directly. The whole map was cleared above so no
                    # stale entries can persist across re-discovery.
                    for tracker in self._zone_trackers.values():
                        if room_name in tracker.room_names:
                            if is_on:
                                tracker._fan_on_rooms.add(room_name)
                                # Tier-3 D2: seed fan-on stamp only if
                                # not already set (a second fan in the
                                # same room going on later must not
                                # reset the grace clock).
                                if room_name not in tracker._fan_on_since:
                                    tracker._fan_on_since[room_name] = (
                                        dt_util.utcnow()
                                    )
                            else:
                                tracker._fan_on_rooms.discard(room_name)
                                tracker._fan_on_since.pop(room_name, None)
                            tracker._fan_entity_to_room[fan_id] = room_name
            if fan_entity_ids:
                # H2 fix-up: capture the unsub returned by
                # `async_track_state_change_event` so we can tear it
                # down on re-discovery (above) without scanning all of
                # `self._unsub_listeners`. The unsub still goes into
                # `_unsub_listeners` so the existing
                # `_cancel_listeners` teardown path (called from
                # `async_teardown`) cleans it up on unload.
                fan_unsub = async_track_state_change_event(
                    self.hass,
                    list(fan_entity_ids),
                    self._handle_fan_change,
                )
                self._fan_listener_unsub = fan_unsub
                self._unsub_listeners.append(fan_unsub)
                _LOGGER.info(
                    "Provenance-split D3: subscribed to %d fan entities across "
                    "%d zones for interference diagnostic",
                    len(fan_entity_ids), len(self._zone_trackers),
                )
        except Exception:  # noqa: BLE001 — defensive: config registry mid-reload
            _LOGGER.exception(
                "Provenance-split D3: fan discovery failed (non-fatal)"
            )

    @callback
    def _handle_fan_change(self, event: Any) -> None:
        """Handle a CONF_FANS entity state change for D3 diagnostic.

        Writes ``room_name`` into / out of
        ``ZonePresenceTracker._fan_on_rooms`` based on whether the fan
        is reporting ``"on"``. Treats unavailable/unknown as off (same
        convention as occupancy and camera handlers above).

        Observation-only: does NOT trigger ``_run_inference``. The
        existing occupancy/inference cadence picks up the new flag on
        the next tick — no need to burn extra cycles on every fan
        toggle.
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not entity_id or new_state is None:
            return
        if new_state.state in _UNAVAILABLE_STATES:
            is_on = False
        else:
            is_on = new_state.state == "on"
        # Fan-transition coincidence gate (AUDIT probe 2026-08-01):
        # detect ANY transition — the on/off state edge OR a
        # percentage attribute change (speed step, e.g. 33% -> 55%).
        # HA's async_track_state_change_event fires the state_changed
        # event for BOTH state and attribute changes, so a bare
        # attribute-only change (state string unchanged, percentage
        # changed) still reaches this callback with distinct
        # old_state / new_state objects.
        transition_now: "datetime | None" = None
        try:
            state_changed = (
                old_state is None or old_state.state != new_state.state
            )
            old_pct = (
                old_state.attributes.get("percentage")
                if old_state is not None else None
            )
            new_pct = new_state.attributes.get("percentage")
            pct_changed = old_pct != new_pct
            if state_changed or pct_changed:
                transition_now = dt_util.utcnow()
        except Exception:  # noqa: BLE001 — defensive: partial state objects
            # A-LOW-2: fail OPEN on the gate (never stamp on garbage).
            # A stamped-on-exception transition would falsely suppress a
            # legitimate mmwave-sole creation on the very next tick.
            transition_now = None
        for tracker in self._zone_trackers.values():
            # H1 fix-up: `_fan_entity_to_room` is now declared in
            # `ZonePresenceTracker.__init__`, so this is a stable dict
            # attribute (no `getattr(..., None)` fallback needed).
            room_name = tracker._fan_entity_to_room.get(entity_id)
            if not room_name:
                continue
            # Fan-transition coincidence gate: stamp the room's most
            # recent fan transition on ANY change (state edge OR
            # percentage attribute change). Consumed by the room
            # coordinator via `get_fan_last_transition` to gate
            # mmwave-sole occupancy CREATION within a small window.
            if transition_now is not None:
                # Defensive: sibling test fakes may not declare this
                # attribute. Production ZonePresenceTracker always
                # declares it in __init__.
                lt = getattr(tracker, "_fan_last_transition", None)
                if lt is not None:
                    lt[room_name] = transition_now
            if is_on:
                tracker._fan_on_rooms.add(room_name)
                # Tier-3 D2: stamp the False→True edge for the
                # grace-window check. Do NOT reset the stamp for a
                # second fan going on in the same room (keeps the
                # oldest fan-on transition as the reference).
                if room_name not in tracker._fan_on_since:
                    tracker._fan_on_since[room_name] = dt_util.utcnow()
            else:
                # Multi-fan safety (A-MED-1 / B-3 fix-up): a room may
                # have >1 configured fan (e.g. Master Bedroom has 2).
                # Only clear _fan_on_rooms / _fan_on_since when NO
                # configured fan for the room is currently on — live-
                # checked via hass.states.get on the sibling fan
                # entities (survives reloads; no refcount to drift).
                any_other_on = False
                try:
                    for other_id, other_room in (
                        tracker._fan_entity_to_room.items()
                    ):
                        if other_room != room_name or other_id == entity_id:
                            continue
                        st = self.hass.states.get(other_id)
                        if (
                            st is not None
                            and st.state not in _UNAVAILABLE_STATES
                            and st.state == "on"
                        ):
                            any_other_on = True
                            break
                except Exception:  # noqa: BLE001 — defensive
                    any_other_on = False
                if not any_other_on:
                    tracker._fan_on_rooms.discard(room_name)
                    tracker._fan_on_since.pop(room_name, None)
            _LOGGER.debug(
                "Provenance-split D3: fan %s in room %s -> on=%s "
                "(fan_on_rooms=%s)",
                entity_id, room_name, is_on, sorted(tracker._fan_on_rooms),
            )

    def _compute_fan_interference_rooms(self) -> List[str]:
        """Per-tick D3 fan-interference observation.

        =====================================================================
        Interference-conditional reliability — primitive definition (D7).
        =====================================================================

        This function names + computes a single primitive: an
        interference-conditional reliability flag that asks, on every
        inference tick, "is this room's Tier-1 occupancy signal
        currently driven by mmwave WHILE a known interference source
        (a fan) is running AND no other corroborating signal exists?"

        Why interference-conditional reliability matters. Static-
        reliability fusion (Bayesian / Augmented Operator Decisions /
        weight-by-trust schemes) treats each sensor's reliability as a
        constant. mmWave sensors, however, have known FAILURE MODES
        whose probability is conditional on environmental state — fans
        and oscillating airflow induce micro-motion that mmWave
        classifiers cannot distinguish from human micro-motion. A
        sensor that is otherwise highly reliable becomes UNRELIABLE
        when interference is present. Static fusion has no input
        channel for "interference is currently happening". This
        primitive provides exactly that channel as a per-tick
        observation, without altering the consensus arithmetic.

        Cross-reference: see
        ``docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md``
        for the full research note stub and the deferred Layer-2 /
        Layer-3 / PIR-fusion design directions.

        The three conditions a room must satisfy to be FLAGGED.
            1) A configured ``CONF_FANS`` entity for the room is ``on``
               (provided by the D3 listener via
               ``ZonePresenceTracker._fan_on_rooms``). NECESSARY because
               the primitive is only meaningful when interference is
               active.
            2) The room's Tier-1 provenance shows mmwave as the SOLE
               positive kind — motion=False, occupancy=False, mmwave=True.
               NECESSARY because PIR + mmwave agreement is the
               canonical corroboration pattern that disproves the
               interference hypothesis.
            3) BLE Layer-1 indicates absence — i.e.,
               ``person_coordinator.get_persons_in_room(room_name)``
               returns an empty list AND no camera is currently
               flagging the same room. NECESSARY because a
               corroborating BLE / camera signal disproves the
               interference hypothesis just as PIR would.

        Layers 2 (adjacent-drift hold) and Layer 3 (zone-absent ->
        fan-pause-and-recheck) are deferred to a later cycle. See
        ``docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md``.

        Returns the sorted list of room_names currently flagged.
        Empty list when D3_DIAGNOSTIC_ENABLED is False, when no fans
        are running anywhere, or when the operator's setup does not
        exhibit the fan-interference pathology in the current tick.

        Off-cadence read note (C-MED-2 review fix-up). This helper
        reads ``tracker._room_provenance`` and ``tracker._fan_on_rooms``
        WITHOUT the inference cadence lock — i.e. an occupancy
        state-change listener (``_handle_occupancy_change``) or a fan
        state-change listener (``_handle_fan_change``) may mutate
        either dict between the time this helper begins iterating and
        the time it returns. This is INTENTIONAL and ACCEPTABLE because:
          (a) the primitive is OBSERVATION-ONLY (no veto / gate /
              actuation consumer — see Review C "observation-only
              guarantee verified GREEN"); a one-listener-event-behind
              read is reconciled on the next inference tick.
          (b) the helper short-reads via ``.get(room_name, {})`` /
              ``getattr(..., set())`` so a mid-iteration insertion or
              deletion cannot raise.
        Future readers MUST NOT assume tick-synchrony between
        ``_room_provenance`` and the consensus emit block; if the
        primitive is ever promoted to feed a gate or veto, this read
        path needs to be snapshotted ONCE at the top of
        ``_run_inference`` instead of called inline.
        """
        if not D3_DIAGNOSTIC_ENABLED:
            return []
        flagged: List[str] = []
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        try:
            for tracker in self._zone_trackers.values():
                fan_rooms = getattr(tracker, "_fan_on_rooms", set()) or set()
                if not fan_rooms:
                    continue
                for room_name in fan_rooms:
                    if room_name not in tracker.room_names:
                        continue
                    prov = tracker._room_provenance.get(room_name, {})
                    # Condition 2: mmwave-sole.
                    mmwave_on = bool(prov.get("mmwave", False))
                    motion_on = bool(prov.get("motion", False))
                    occ_on = bool(prov.get("occupancy", False))
                    if not (mmwave_on and not motion_on and not occ_on):
                        continue
                    # Condition 3a: BLE Layer-1 absence.
                    ble_persons: list = []
                    if person_coord is not None:
                        try:
                            ble_persons = person_coord.get_persons_in_room(
                                room_name,
                            ) or []
                        except Exception:  # noqa: BLE001
                            ble_persons = []
                    if ble_persons:
                        continue
                    # Condition 3b: camera absence for the zone owning
                    # the room (R1-H3 fix-up: documented, not re-
                    # architected). Two design points worth pinning so
                    # a future reader does not "fix" this into a
                    # per-room veto:
                    #   (a) The camera signal feeding this veto is
                    #       PERSON-classified, not motion. Only
                    #       ``camera_info.person_binary_sensor``
                    #       (``*_person_occupancy`` Frigate /
                    #       ``*_person_detected`` UniFi) is ever
                    #       registered for a zone — see
                    #       ``register_camera`` at the
                    #       ``_discover_zone_cameras`` site
                    #       (presence.py: ~2201) and the
                    #       ``camera_census.py`` filter at :251 that
                    #       drops any non-person binary_sensor before
                    #       it reaches here. Person-classification is
                    #       the stable + intentional choice; this
                    #       observation-only veto is not the place to
                    #       broaden the camera surface.
                    #   (b) The grain is ZONE-WIDE
                    #       (``any(_camera_occupied.values())``)
                    #       BY DESIGN. URA cameras are registered at
                    #       zone granularity — no per-room camera
                    #       routing map exists today (only
                    #       ``_room_to_zone``; the reverse direction is
                    #       intentionally absent because a multi-area
                    #       camera can serve multiple rooms in a zone).
                    #       A per-room camera veto would require new
                    #       camera→room mapping in CameraIntegrationManager,
                    #       which is out of scope for D3. Conservative-
                    #       by-necessity is fine for an observation-only
                    #       primitive: the worst case is "we suppress a
                    #       fan-interference flag in a zone where a
                    #       different room has a person on camera" —
                    #       a false negative on an observation-only
                    #       diagnostic, never a false positive on an
                    #       actuation.
                    if any(
                        bool(v)
                        for v in getattr(tracker, "_camera_occupied", {}).values()
                    ):
                        continue
                    flagged.append(room_name)
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.debug(
                "Provenance-split D3: fan-interference compute failed "
                "(non-fatal)",
                exc_info=True,
            )
            return []
        return sorted(flagged)

    def _apply_fan_interference_gate(
        self,
        suspect_rooms: List[str],
        hold_seconds: int,
    ) -> tuple[List[str], Dict[str, str]]:
        """Fan-noise mitigation D1 (Layer-1 silent gate).

        Promotes the observation-only ``_compute_fan_interference_rooms``
        verdict into a SILENT confidence discount: a fan-suspect room
        whose mmwave-sole provenance is NOT corroborated by the BLE
        ladder gets a hold applied via
        ``ZonePresenceTracker._fan_interference_hold_until``. The hold
        extends the derived ``_room_occupied`` view past the natural
        drop point — it can never shorten a genuinely-occupied room
        (the truth-preserving invariant; see the property's docstring).

        The BLE corroboration ladder (3 layers, all evaluated):

          - L1 (room BLE present): if ``get_persons_in_room(room)``
            returns any phone-TRUSTWORTHY person (mirrors the v4.7.14.1
            H2 ``PersonPhoneLeftBehindSensor`` carve-out at
            presence.py:3289 — phones in the "forgotten phone" sensor
            don't corroborate), mmwave is trusted again. CLEAR any
            existing hold. No new hold. Ladder verdict = "L1".
          - L2 (adjacent room BLE present): if any room in
            ``CONF_ADJACENT_ROOMS`` for the suspect room has a
            trustworthy phone, treat as "probably the same person
            drifting." SET hold. Ladder verdict = "L2". (Pause
            eligibility is FORBIDDEN here — but pause is a D2
            consideration, deferred.)
          - L3 (zone-wide BLE absence): if ``tracker._ble_occupied`` is
            False, this is the strongest discount signal. SET hold.
            Ladder verdict = "L3".
          - "none": L3 inconclusive (zone has no BLE infra / BLE
            occupied but L1 + L2 silent). Fall through: SET hold under
            decay. Ladder verdict = "none".

        Pets are NOT rejected by L1 / L2 (a dog has no phone); only L3
        zone-absence positively excludes pets.

        Returns ``(gated_rooms, ladder_verdicts)`` where ``gated_rooms``
        is the sorted list of rooms whose hold is currently active (set
        this tick OR a prior tick), and ``ladder_verdicts`` maps every
        SUSPECT room to its strongest non-fired layer label.

        Truth-preserving: this method writes ONLY to
        ``tracker._fan_interference_hold_until`` — it never mutates
        ``_room_provenance``. The derived ``_room_occupied`` view
        consults the hold dict in addition to the OR (see property
        docstring). Worst case is a fan-suspect room reads occupied
        for up to ``hold_seconds`` too long; a genuinely-occupied
        room (any True in provenance) is NEVER flipped to unoccupied.
        """
        ladder: Dict[str, str] = {}
        gated_rooms: List[str] = []
        if not D3_DIAGNOSTIC_ENABLED:
            # H-A2 fix-up: if the kill switch is flipped off (now or
            # post-restart with the flag flipped in const.py), we MUST
            # drain every existing hold. Otherwise the `_room_occupied`
            # property keeps reading the stranded hold dict and a room
            # stays occupied past the natural drop point with no
            # mechanism to expire (the gate short-returns and never
            # reaches the decay/clear path). Draining at the gate entry
            # is cheaper than gating the per-tick property read.
            try:
                for tracker in self._zone_trackers.values():
                    if getattr(tracker, "_fan_interference_hold_until", None):
                        tracker._fan_interference_hold_until.clear()
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.warning(
                    "Fan-noise D1: hold-drain on kill-switch-off failed "
                    "(non-fatal)",
                    exc_info=True,
                )
            return gated_rooms, ladder

        # Build the phone-trustworthy checker once per call (mirrors the
        # v4.7.14.1 H2 pattern at presence.py:3289). Fail-OPEN: missing
        # sensor / unknown / unavailable -> True (preserves v4.7.14
        # baseline). Resolves entity_id via entity_registry by
        # unique_id rather than string construction.
        try:
            from homeassistant.helpers import entity_registry as er
            _entity_reg = er.async_get(self.hass)
        except Exception:  # noqa: BLE001 — defensive
            _entity_reg = None

        def _phone_trustworthy(person_name: str) -> bool:
            person_slug = (person_name or "").lower().replace(" ", "_")
            if not person_slug:
                return True
            unique_id = f"{DOMAIN}_person_{person_slug}_phone_left_behind"
            entity_id: Optional[str] = None
            if _entity_reg is not None:
                try:
                    entity_id = _entity_reg.async_get_entity_id(
                        "binary_sensor", DOMAIN, unique_id,
                    )
                except Exception:  # noqa: BLE001 — fail-OPEN
                    entity_id = None
            if entity_id is None:
                return True
            try:
                state = self.hass.states.get(entity_id)
            except Exception:  # noqa: BLE001 — fail-OPEN
                return True
            if state is None or state.state in _UNAVAILABLE_STATES:
                return True
            return state.state != "on"

        def _trustworthy_persons_in_room(room: str) -> List[str]:
            if person_coord is None or not room:
                return []
            try:
                raw = person_coord.get_persons_in_room(room) or []
            except Exception:  # noqa: BLE001 — defensive
                return []
            return [p for p in raw if _phone_trustworthy(p)]

        # B-M1 fix-up: read adjacency from the cached map. Rebuild on
        # demand if the cache hasn't been populated yet (test paths
        # that construct the coordinator without calling
        # `_discover_zones`, first-tick-post-restart edge). Every
        # discovery method invalidates the cache so a config-flow
        # reload picks up the new shape.
        if self._adjacency_cache is None:
            self._rebuild_adjacency_cache()
        adjacency: Dict[str, List[str]] = self._adjacency_cache or {}

        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        now = dt_util.utcnow()

        try:
            suspect_set = set(suspect_rooms)
            for tracker in self._zone_trackers.values():
                for room_name in list(tracker.room_names):
                    if room_name not in suspect_set:
                        # Not fan-suspect this tick: if the room had a
                        # hold, apply reset rules in priority order
                        # (planning doc §D1.2 "Reset rules"):
                        #   1. L1 positive corroboration (room BLE
                        #      present, phone-trustworthy) clears the
                        #      hold — mmwave is trusted again the
                        #      moment a known person is in the room.
                        #      H-A1 fix-up: prior code missed this
                        #      branch entirely on non-suspect ticks,
                        #      so a stale hold persisted for the full
                        #      window after a phone walked in.
                        #   2. Any non-mmwave provenance kind True
                        #      clears the hold (room is no longer
                        #      mmwave-sole — corroborated by another
                        #      Tier-1 sensor).
                        #   3. Hold naturally expired (<= now) — drop.
                        #   4. Otherwise — keep extending occupancy
                        #      this tick, surface in gated_rooms.
                        if room_name in tracker._fan_interference_hold_until:
                            # Reset #1: L1 positive corroboration.
                            if _trustworthy_persons_in_room(room_name):
                                tracker._fan_interference_hold_until.pop(
                                    room_name, None,
                                )
                                continue
                            prov = tracker._room_provenance.get(room_name, {})
                            non_mmwave_true = any(
                                bool(prov.get(k, False))
                                for k in prov.keys()
                                if k != "mmwave"
                            )
                            if non_mmwave_true:
                                # Reset #2.
                                tracker._fan_interference_hold_until.pop(
                                    room_name, None,
                                )
                            elif tracker._fan_interference_hold_until[room_name] <= now:
                                # Reset #3: hold expired naturally.
                                tracker._fan_interference_hold_until.pop(
                                    room_name, None,
                                )
                            else:
                                # Hold still active for a previously-
                                # suspect room; surface it in the gated
                                # list (the silent extension is still
                                # in effect this tick).
                                gated_rooms.append(room_name)
                        continue

                    # L1 — room BLE present (trustworthy phones).
                    l1_persons = _trustworthy_persons_in_room(room_name)
                    if l1_persons:
                        ladder[room_name] = "L1"
                        # L1 clears any prior hold — mmwave is trusted
                        # again the moment a known person is in the room.
                        tracker._fan_interference_hold_until.pop(
                            room_name, None,
                        )
                        continue

                    # L2 — adjacent room BLE present.
                    l2_hit = False
                    for adj_room in adjacency.get(room_name, []):
                        if _trustworthy_persons_in_room(adj_room):
                            l2_hit = True
                            break

                    # L3 — zone-wide BLE absence (strongest discount).
                    l3_hit = not bool(getattr(tracker, "_ble_occupied", False))

                    if l2_hit:
                        ladder[room_name] = "L2"
                    elif l3_hit:
                        ladder[room_name] = "L3"
                    else:
                        ladder[room_name] = "none"

                    # Apply hold (silent extension under decay). Refresh
                    # on every tick the room remains suspect.
                    tracker._fan_interference_hold_until[room_name] = (
                        now + timedelta(seconds=int(hold_seconds))
                    )
                    gated_rooms.append(room_name)
        except Exception:  # noqa: BLE001 — defensive
            # M-A4 fix-up: elevate to WARNING so a real defect in the
            # per-room loop is visible at default log level. The
            # partial `gated_rooms` is still returned (callers prefer
            # graceful degradation to a `_run_inference` crash).
            _LOGGER.warning(
                "Fan-noise D1: gate apply raised (partial gated list "
                "returned, non-fatal)",
                exc_info=True,
            )
            return sorted(gated_rooms), ladder

        return sorted(set(gated_rooms)), ladder

    def _compute_mmwave_fan_demoted_rooms(self) -> Set[str]:
        """Tier-3 D2 — mmWave fan-corroboration DEMOTION wrapper.

        Wraps the existing observation-only ``_compute_fan_interference_rooms``
        primitive (mmwave-sole + BLE-absent + camera-absent) with the
        additional fan-on-duration gate (Invariant M leg (b)): the fan
        must have been continuously ``on`` for at least
        ``MMWAVE_FAN_CORROBORATION_GRACE_S`` seconds. The other Invariant
        M legs live at the CONSUMER site (room coordinator):

            - leg (b) fan-on ≥ grace           — HERE (per-tracker stamp)
            - leg (e) PIR-motion stale ≥ MULT×timeout — CONSUMER (room coord)
            - recheck-in-flight guard          — CONSUMER (room coord)
            - debounce / boot-settle guard     — CONSUMER (room coord)

        The primitive's zone-camera-any check is preserved as-is (it is
        strictly fail-safe for a demotion — extra camera visibility can
        only PREVENT demotion, never cause a spurious one). Per
        Amendment 1, no per-room camera-covered check is added here:
        with ``CAMERA_COVERED_ROOMS`` currently a single-room set with
        no camera in effective use, the extra leg is dormant and the
        zone-any check already provides the "no camera person" leg for
        covered rooms in camera zones.

        Kill switch: ``MMWAVE_FAN_CORROBORATION_ENABLED = False`` in
        const.py → returns empty set. No stranded state to drain here
        (unlike ``_apply_fan_interference_gate``) because this wrapper
        writes NOTHING — it is a pure per-tick predicate.

        Returns the set of room_names currently eligible for demotion.
        """
        from ..const import (  # noqa: PLC0415 — local to avoid import order concerns
            CAMERA_COVERED_ROOMS,
            MMWAVE_FAN_CORROBORATION_ENABLED,
            MMWAVE_FAN_CORROBORATION_GRACE_S,
        )
        if not MMWAVE_FAN_CORROBORATION_ENABLED:
            return set()
        # D-CRIT-1: sleep-family veto — mirrors presence_fan_recheck's
        # sleep gate (presence_fan_recheck.py:374) and the duty-cycle
        # detector's sleeping-bedroom refusal (coordinator.py:1812-1817).
        # Never demote while people are asleep, waking, or in the
        # home_night wind-down; mmwave stillness is expected there.
        try:
            hs = getattr(self, "house_state", "") or ""
            if hs in (
                HouseState.SLEEP.value,
                HouseState.WAKING.value,
                HouseState.HOME_NIGHT.value,
            ):
                return set()
        except Exception:  # noqa: BLE001 — defensive
            pass
        try:
            suspects = self._compute_fan_interference_rooms()
        except Exception:  # noqa: BLE001 — defensive
            return set()
        if not suspects:
            return set()
        now = dt_util.utcnow()
        # D-MED-2: grace floor. Sub-floor values clamp to 300s; log once
        # per process. ENABLED=False is the sole full kill switch.
        try:
            grace_raw = int(MMWAVE_FAN_CORROBORATION_GRACE_S)
        except (TypeError, ValueError):
            grace_raw = 600
        grace = max(300, grace_raw)
        if grace != grace_raw and not getattr(
            self, "_mmwave_grace_clamp_logged", False,
        ):
            _LOGGER.info(
                "MMWAVE_FAN_CORROBORATION_GRACE_S=%d below floor 300 — "
                "clamping to 300s",
                grace_raw,
            )
            self._mmwave_grace_clamp_logged = True
        demoted: Set[str] = set()
        for tracker in self._zone_trackers.values():
            fan_since_map = getattr(tracker, "_fan_on_since", {}) or {}
            for room_name in suspects:
                if room_name not in tracker.room_names:
                    continue
                stamp = fan_since_map.get(room_name)
                if stamp is None:
                    continue
                try:
                    age = (now - stamp).total_seconds()
                except Exception:  # noqa: BLE001 — tz mismatch / naive dt
                    continue
                if age < 0:
                    # Clock skew — refuse to demote (fail-safe).
                    continue
                if age < grace:
                    continue
                # D-MED-1: fail-closed for CAMERA_COVERED_ROOMS. If any
                # camera on the room's zone tracker is unavailable /
                # unknown, corroboration is UNKNOWN — skip demotion.
                if room_name in CAMERA_COVERED_ROOMS:
                    cam_unknown = False
                    try:
                        for cam_id in list(
                            getattr(tracker, "_camera_occupied", {}).keys()
                        ):
                            st = self.hass.states.get(cam_id)
                            if st is None or st.state in _UNAVAILABLE_STATES:
                                cam_unknown = True
                                break
                    except Exception:  # noqa: BLE001 — defensive
                        cam_unknown = True
                    if cam_unknown:
                        continue
                demoted.add(room_name)
        return demoted

    def is_room_mmwave_fan_demoted(self, room_name: str) -> bool:
        """Public accessor for the room coordinator's D2 sustain-gate.

        D-HIGH-3 fix-up: reads a per-inference-tick SNAPSHOT
        (``_mmwave_fan_demoted_snapshot``) refreshed at the top of
        ``_run_inference``. NEVER invokes the primitive live — the
        snapshot contract in ``_compute_fan_interference_rooms``'s
        off-cadence note (presence.py:3301-3319) forbids inline reads
        from consumers that gate/actuate. One-tick-behind is acceptable
        per that contract.
        """
        if not room_name:
            return False
        return room_name in getattr(
            self, "_mmwave_fan_demoted_snapshot", frozenset(),
        )

    def get_fan_last_transition(self, room_name: str):
        """Return the room's most recent fan-transition UTC datetime, or None.

        Fan-transition coincidence gate (AUDIT probe 2026-08-01):
        stamped by ``_handle_fan_change`` on any observed transition
        (on/off state edge OR percentage attribute change) of a
        configured CONF_FANS entity mapped to the room. Consumed by
        the room-tier coordinator to gate mmwave-sole occupancy
        CREATION within FAN_TRANSITION_SUSPECT_WINDOW_S.

        Off-cadence read is intentional and safe: the dict is only
        written from `_handle_fan_change` (state-change listener),
        never mutated mid-iteration here. Returns None when no
        transition has been observed for the room since boot / last
        discovery (kill-switch friendly — caller treats None as "no
        fan transition, admit normally").

        B-LOW-4 fix-up: when a room appears in multiple trackers
        (multi-tracker deployments), return the MAX (newest) stamp
        across all trackers — not the first-hit. Newest wins because
        the gate cares about "any transition within the window", and
        the newest stamp is the one most likely to satisfy `Δt <= W`.

        MED-B2 (same-tick event-ordering race): HA fires state_changed
        events synchronously in listener-registration order. If the
        room coordinator's mmWave-triggered refresh runs BEFORE
        `_handle_fan_change` stamps for the same underlying tick, this
        method returns the stale/prior stamp (or None) for that tick
        and the gate misses. The sibling D2 sustain-demotion backstops
        this one-tick miss on the next cadence — deliberate per
        three-mechanism complementarity (creation gate + sustain
        demotion + actuation veto).
        """
        if not room_name:
            return None
        newest = None
        for tracker in self._zone_trackers.values():
            lt = getattr(tracker, "_fan_last_transition", None)
            if lt is None:
                continue
            stamp = lt.get(room_name)
            if stamp is None:
                continue
            if newest is None or stamp > newest:
                newest = stamp
        return newest

    def _discover_zone_cameras(self) -> None:
        """Discover cameras in each zone using CameraIntegrationManager.

        Cameras are mapped to zones via their area_id in the entity registry.
        If a camera's area_id matches a room's area_id, and that room is in
        a zone, the camera's person detection entity is subscribed for that zone.

        This mirrors how camera_census.py uses area_id for camera→room mapping,
        but applied at the zone level.
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            _LOGGER.debug("No coordinator manager — camera discovery skipped")
            return

        # Get CameraIntegrationManager from the coordinator data
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if camera_manager is None:
            _LOGGER.debug("No camera manager initialized — zone camera discovery skipped")
            return

        if not camera_manager.has_cameras():
            _LOGGER.debug("No cameras discovered — zone camera signals unavailable")
            return

        camera_entity_ids: Set[str] = set()

        # Build area_id → zone mapping from room → zone assignments.
        # v4.7.16 D4: also track which area_ids are owned by rooms that have
        # set CONF_DISABLE_CAMERA_PRESENCE=True so we can skip register_camera
        # for those areas. Opt-out is enforced at registration time — the
        # ZonePresenceTracker itself stays oblivious to per-room policy.
        area_to_zone: Dict[str, str] = {}
        opted_out_area_ids: Set[str] = set()
        opted_out_rooms = self._rooms_opting_out_of_camera_presence()
        for zone_name, tracker in self._zone_trackers.items():
            for room_name in tracker.room_names:
                area_id = self._room_area_ids.get(room_name)
                if area_id:
                    area_to_zone[area_id] = zone_name
                    if room_name in opted_out_rooms:
                        opted_out_area_ids.add(area_id)

        # Find cameras in each zone's areas
        for area_id, zone_name in area_to_zone.items():
            # v4.7.16 D4: skip cameras for opted-out room areas. Other rooms
            # in the same zone continue to receive their cameras.
            if area_id in opted_out_area_ids:
                cameras_in_area = camera_manager.get_cameras_for_area(area_id)
                _LOGGER.info(
                    "Camera-presence opt-out: skipping %d cameras for "
                    "zone %s (area %s) per CONF_DISABLE_CAMERA_PRESENCE",
                    len(cameras_in_area), zone_name, area_id,
                )
                continue

            cameras_in_area = camera_manager.get_cameras_for_area(area_id)
            tracker = self._zone_trackers[zone_name]

            for camera_info in cameras_in_area:
                person_sensor = camera_info.person_binary_sensor
                if person_sensor and person_sensor not in camera_entity_ids:
                    camera_entity_ids.add(person_sensor)
                    tracker.register_camera(person_sensor)
                    _LOGGER.debug(
                        "Zone %s: camera sensor %s (area %s, platform %s)",
                        zone_name, person_sensor, area_id, camera_info.platform,
                    )

        if camera_entity_ids:
            # H2 fix-up: tear down the prior camera-listener
            # subscription if one was already registered (defense-in-
            # depth against a future re-discovery caller). Without
            # this, a second invocation would stack a duplicate
            # listener and `_handle_camera_change` would fire twice per
            # state change, double-counting camera occupancy timeouts.
            if self._camera_listener_unsub is not None:
                try:
                    self._camera_listener_unsub()
                except Exception:  # noqa: BLE001 — defensive
                    _LOGGER.debug(
                        "Prior camera listener unsub raised (non-fatal)",
                        exc_info=True,
                    )
                try:
                    self._unsub_listeners.remove(self._camera_listener_unsub)
                except ValueError:
                    pass
                self._camera_listener_unsub = None
            camera_unsub = async_track_state_change_event(
                self.hass,
                list(camera_entity_ids),
                self._handle_camera_change,
            )
            self._camera_listener_unsub = camera_unsub
            self._unsub_listeners.append(camera_unsub)
            _LOGGER.info(
                "Subscribed to %d zone camera entities across %d zones",
                len(camera_entity_ids), len(self._zone_trackers),
            )

            # v4.7.18.1 fix-up B-HIGH-1: seed tracker._camera_occupied from
            # current camera states. Without this seed, the first inference
            # tick sees an empty _camera_last_seen dict and raw_occupied is
            # False even if a person is actively detected. Predicate mirrors
            # _handle_camera_change (state == "on"; unavailable/unknown → False).
            for entity_id in camera_entity_ids:
                try:
                    state = self.hass.states.get(entity_id)
                except Exception:  # pragma: no cover - defensive
                    state = None
                if state is None:
                    continue
                if state.state in _UNAVAILABLE_STATES:
                    continue
                detected = state.state == "on"
                if not detected:
                    continue
                for _zone_name, tracker in self._zone_trackers.items():
                    if entity_id in tracker._camera_entity_ids:
                        tracker.update_camera_detection(entity_id, detected)
                        break

    # ------------------------------------------------------------------
    # Geofence: person entity state changes (home/not_home)
    # ------------------------------------------------------------------

    def _subscribe_geofence(self) -> None:
        """Subscribe to person.* entity state changes for geofence signals.

        HA person entities track home/not_home/zone state. When a person
        transitions to 'home' from 'not_home' (or vice versa), this provides
        an early AWAY→ARRIVING signal before camera census updates.
        """
        person_entity_ids = [
            state.entity_id
            for state in self.hass.states.async_all()
            if state.entity_id.startswith("person.")
        ]

        if not person_entity_ids:
            _LOGGER.debug("No person entities found — geofence signal unavailable")
            return

        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass,
                person_entity_ids,
                self._handle_geofence_change,
            )
        )
        _LOGGER.info(
            "Subscribed to %d person entities for geofence signals",
            len(person_entity_ids),
        )

    @callback
    def _handle_geofence_change(self, event: Any) -> None:
        """Handle person entity state change (geofence transition)."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        new_zone = new_state.state
        old_zone = old_state.state if old_state else None

        # Guard: skip unavailable/unknown
        if new_zone in _UNAVAILABLE_STATES:
            return

        # Detect home arrival or departure
        if new_zone == "home" and old_zone != "home":
            self.handle_geofence_event(entity_id, "home")
            # v3.17.0 D3: Signal person arriving for HVAC zone pre-conditioning
            # v3.21.1 D1: Gate signal dispatch on observation mode
            if self.observation_mode:
                _LOGGER.info(
                    "[observation mode] Presence would dispatch "
                    "SIGNAL_PERSON_ARRIVING for %s (geofence) — suppressed",
                    entity_id,
                )
            else:
                # B-H1 fix-up: async_dispatcher_send is imported at module
                # top — use it directly. Eliminates the Bug Class #34
                # latent function-local import.
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_PERSON_ARRIVING,
                    {"person_entity": entity_id, "source": "geofence"},
                )
        elif new_zone == "not_home" and old_zone == "home":
            self.handle_geofence_event(entity_id, "not_home")

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    @callback
    def _handle_census_update(self, census_data: dict) -> None:
        """Handle Census update signal."""
        old_count = self._census_count
        old_unidentified = self._unidentified_count
        # v4.6.2.3: Capture confidence BEFORE reassignment so the change-detection
        # comparison below is valid. Without this, comparing self._census_confidence
        # to self._census_confidence after the update would always be equal.
        old_confidence = self._census_confidence
        try:
            self._census_count = int(census_data.get("interior_count", 0))
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid census interior_count: %s — keeping previous value",
                census_data.get("interior_count"),
            )
            return

        # v3.15.0: Track unidentified count for guest mode
        try:
            self._unidentified_count = int(census_data.get("unidentified_count", 0))
        except (ValueError, TypeError):
            self._unidentified_count = 0

        # v4.6.2.2: Read confidence fields for guest gate — default to "none"
        # if not present (backward compat with any caller not yet sending them).
        try:
            self._census_confidence = str(
                census_data.get("confidence", "none") or "none"
            )
        except (TypeError, ValueError, KeyError, AttributeError):
            # Tolerate malformed signal payload (legacy subscribers or test stubs).
            _LOGGER.debug("Malformed census payload: could not read confidence field")
            self._census_confidence = "none"

        _LOGGER.debug(
            "Census update: count=%d unidentified=%d confidence=%s",
            self._census_count, self._unidentified_count, self._census_confidence,
        )

        # v4.6.2.3: Also trigger inference on confidence-only changes (e.g., low→high
        # with counts unchanged). Without this, a confidence upgrade waits up to the
        # next 60s periodic tick before the guest gate re-evaluates.
        if (
            old_count != self._census_count
            or old_unidentified != self._unidentified_count
            or old_confidence != self._census_confidence
        ):
            self.hass.async_create_task(self._run_inference("census_update"))

    @callback
    def _handle_occupancy_change(self, event: Any) -> None:
        """Handle room occupancy sensor state change.

        Guards against unavailable/unknown states — treats them as 'not occupied'
        to avoid false positives from offline sensors (lesson from camera_census).
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Guard: treat unavailable/unknown as not occupied
        if new_state.state in _UNAVAILABLE_STATES:
            _LOGGER.debug(
                "Occupancy sensor %s is %s — treating as not occupied",
                entity_id, new_state.state,
            )
            occupied = False
        else:
            occupied = new_state.state == "on"

        # Find which zone and room this entity belongs to (via registered mapping)
        matched = False
        for _zone_name, tracker in self._zone_trackers.items():
            room_name = tracker._entity_to_room.get(entity_id)
            if room_name:
                # Provenance-split cycle (D2): classify per-kind using
                # the SAME cached classifier the seed loop uses.
                # Function identity + single cache slot matters —
                # v4.7.18.1 review finding B-HIGH-1 hazard
                # (NOT QUALITY_CONTEXT.md Bug Class #1).
                kind = self._classify_entity_kind_cached(
                    entity_id, room_name,
                )
                tracker.update_room_occupancy(
                    room_name, occupied, kind=kind,
                )
                matched = True
                break

        # Occupancy substrate unification cycle: the prior name-based
        # fallback-matching block (previously at presence.py:3255-3270)
        # was DELETED here. With `_discover_room_sensors_by_name`
        # removed and the substrate sourcing entities exclusively from
        # CONF lists, no entity can reach this callback without a
        # registered ``_entity_to_room`` mapping. Retaining the fallback
        # would only reintroduce the substring-classification divergence
        # the substrate cycle exists to remove.

        self.hass.async_create_task(self._run_inference("occupancy_change"))

    @callback
    def _handle_camera_change(self, event: Any) -> None:
        """Handle camera person/motion detection state change.

        Guards against unavailable/unknown states. Camera detection uses
        timeout-based occupancy — when person is detected the zone stays
        occupied for _CAMERA_OCCUPANCY_TIMEOUT_SECONDS after detection ends.
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # Guard: unavailable/unknown means not detecting
        if new_state.state in _UNAVAILABLE_STATES:
            _LOGGER.debug(
                "Camera sensor %s is %s — treating as no detection",
                entity_id, new_state.state,
            )
            detected = False
        else:
            detected = new_state.state == "on"

        # Route to the correct zone tracker (EXISTING — unchanged)
        matched_zone_name = None
        for _zone_name, tracker in self._zone_trackers.items():
            if entity_id in tracker._camera_entity_ids:
                tracker.update_camera_detection(entity_id, detected)
                matched_zone_name = _zone_name
                break

        # v3.19.0: Face-confirmed arrival (ADDITIVE — all failures return gracefully)
        if detected and matched_zone_name and self._face_recognition_enabled:
            face_name = self._get_face_for_camera(entity_id)
            if face_name:
                self._handle_face_arrival(entity_id, face_name, matched_zone_name)

        self.hass.async_create_task(self._run_inference("camera_detection"))

    # ------------------------------------------------------------------
    # v3.19.0: Face-confirmed arrival helpers (additive — never modify
    # existing camera detection behavior, all failures return gracefully)
    # ------------------------------------------------------------------

    def _get_face_for_camera(self, camera_entity: str) -> Optional[str]:
        """Get recognized face from Frigate face sensor for this camera.

        v3.19.0: Uses confirmed Frigate naming pattern:
        binary_sensor.{name}_person_occupancy → sensor.{name}_last_recognized_face

        Returns face name if fresh (<30s), None on any failure.
        All failures are graceful — face rec is an accelerator, not a requirement.
        """
        try:
            # Derive face sensor from camera entity using Frigate naming convention
            bs_id = camera_entity
            base_name = None
            for suffix in ("_person_occupancy", "_person_detected", "_occupancy"):
                if bs_id.startswith("binary_sensor.") and bs_id.endswith(suffix):
                    base_name = bs_id[len("binary_sensor."):-len(suffix)]
                    break

            if not base_name:
                return None  # Not a recognized camera pattern

            face_sensor_id = f"sensor.{base_name}_last_recognized_face"
            state = self.hass.states.get(face_sensor_id)
            if not state:
                return None  # Face sensor doesn't exist

            # Check for valid face name
            face_value = state.state.strip() if state.state else ""
            if not face_value or face_value.lower() in ("unknown", "unavailable", "none", "no_match", ""):
                return None  # No face recognized

            # Freshness check: face rec must be recent (<30s)
            if state.last_changed:
                age = (dt_util.utcnow() - state.last_changed).total_seconds()
                if age > 30:  # FACE_FRESHNESS_SECONDS
                    return None  # Stale face data

            return face_value
        except Exception:  # noqa: BLE001
            return None  # Face rec is an accelerator — never fail

    @callback
    def _handle_face_arrival(self, camera_entity: str, face_name: str, zone_name: str) -> None:
        """Fire pre-arrival signal for face-recognized person in a zone.

        v3.19.0: Debounced (60s per person+zone). All failures graceful.
        """
        try:
            # async_dispatcher_send imported at module top (v4.7.20.1) — no
            # function-local import, to avoid re-scoping it as a method-local.
            # Map face name to person entity
            person_entity = self._find_person_entity_from_face(face_name)
            if not person_entity:
                _LOGGER.debug("Face '%s' has no matching person entity — skipping", face_name)
                return

            # Debounce: 60s cooldown per person+zone
            key = f"{person_entity}:{zone_name}"
            now = dt_util.utcnow()
            last = self._face_arrival_cooldown.get(key)
            if last and (now - last).total_seconds() < 60:
                return
            self._face_arrival_cooldown[key] = now

            # Update zone tracker face state
            tracker = self._zone_trackers.get(zone_name)
            if tracker:
                tracker._last_face_recognized = face_name
                tracker._last_face_time = now
                tracker._face_arrivals_today += 1

            # Update HVAC zone counter if available
            try:
                manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                if manager:
                    hvac = manager.coordinators.get("hvac")
                    if hvac and hvac.zone_manager:
                        for _zid, zstate in hvac.zone_manager.zones.items():
                            if zstate.zone_name == zone_name:
                                zstate.camera_face_arrivals_today += 1
                                break
            except Exception:  # noqa: BLE001
                pass  # Best effort — don't fail face arrival on HVAC counter update

            # Fire the signal
            # v3.21.1 D1: Gate signal dispatch on observation mode
            if self.observation_mode:
                _LOGGER.info(
                    "[observation mode] Presence would dispatch "
                    "SIGNAL_PERSON_ARRIVING for %s (camera_face) in zone %s — suppressed",
                    face_name, zone_name,
                )
            else:
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_PERSON_ARRIVING,
                    {"person_entity": person_entity, "source": "camera_face"},
                )
                _LOGGER.info(
                    "Camera face arrival: %s recognized in zone %s via %s",
                    face_name, zone_name, camera_entity,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Face arrival handling failed (non-fatal)", exc_info=True)

    def _find_person_entity_from_face(self, face_name: str) -> Optional[str]:
        """Map Frigate face name to HA person entity.

        v3.19.0: Frigate face names are configured names (e.g., "Oji", "Jaya").
        Try matching to person.{lowercase_name}.
        """
        try:
            candidate = f"person.{face_name.lower().replace(' ', '_')}"
            if self.hass.states.get(candidate):
                return candidate
            # Try without modification
            candidate2 = f"person.{face_name}"
            if self.hass.states.get(candidate2):
                return candidate2
            return None
        except Exception:  # noqa: BLE001
            return None  # Face rec is an accelerator — never fail

    async def _periodic_inference(self, _now: Any = None) -> None:
        """Run periodic inference for time-based transitions and camera timeouts.

        Also updates BLE-based zone presence (Tier 3) from person_coordinator.
        """
        # Update BLE presence for each zone (Tier 3)
        self._update_ble_zone_presence()

        await self._run_inference("periodic")

    def _update_ble_zone_presence(self) -> None:
        """Update BLE-based zone presence from person_coordinator.

        Checks person_coordinator for persons located in rooms that belong
        to each zone. If any person is in a room within a zone, that zone
        is BLE-occupied.
        """
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator or not hasattr(person_coordinator, "data") or not person_coordinator.data:
            return

        for _zone_name, tracker in self._zone_trackers.items():
            zone_has_person = False
            for _person_id, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location and location not in ("away", "unknown", ""):
                    # Check if this person's room is in this zone
                    if location in tracker.room_names:
                        zone_has_person = True
                        break

            tracker.update_ble_presence(zone_has_person)

    def _schedule_deferred_retry(self, delay_seconds: float) -> None:
        """Schedule a one-shot deferred inference retry after hysteresis expires.

        v3.6.0.11: Prevents lost transitions when hysteresis blocks.
        """
        from homeassistant.helpers.event import async_call_later

        # Cancel any existing retry
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

        @callback
        def _retry_callback(_now):
            self._retry_unsub = None
            self.hass.async_create_task(self._run_inference("deferred_retry"))

        self._retry_unsub = async_call_later(
            self.hass, delay_seconds, _retry_callback,
        )
        _LOGGER.debug(
            "Deferred retry scheduled in %.0fs", delay_seconds,
        )

    # ------------------------------------------------------------------
    # v4.6.2.2: Guest mode hardening helpers
    # ------------------------------------------------------------------

    # Confidence level rank map — strict ordering for gate compare.
    # NEVER compare confidence strings lexicographically.
    _CONFIDENCE_RANK: dict = {"none": 0, "low": 1, "medium": 2, "high": 3}

    def _confidence_at_least(self, observed: str, required: str) -> bool:
        """Return True iff observed census confidence >= required level.

        Uses the private rank map to avoid lexicographic comparison bugs.
        Unknown values are treated as 'none' (rank 0) — safest default.
        """
        observed_rank = self._CONFIDENCE_RANK.get(observed, 0)
        required_rank = self._CONFIDENCE_RANK.get(required, 0)
        return observed_rank >= required_rank

    def _disarm_guest_gate(self) -> None:
        """Clear all guest gate arm state and cancel any pending recheck timer.

        Call on: disarm (count drops / confidence regresses), gate fire,
        house state change away from HOME_*, coordinator unload.
        """
        self._unidentified_first_seen = None
        if self._guest_persistence_check_handle is not None:
            self._guest_persistence_check_handle()
            self._guest_persistence_check_handle = None

    # ------------------------------------------------------------------
    # v4.7.2 D5: Sustained-occupancy guest signal (Feature B)
    # ------------------------------------------------------------------

    def _discover_guest_rooms(self) -> None:
        """Discover rooms flagged is_guest_room=True and register occupancy listeners.

        Called from async_setup() after _discover_room_sensors().
        Reads CONF_ROOM_IS_GUEST_ROOM and CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN
        from each room entry's options (D4 CONFs). Bug Class #14: reads fresh from
        options each call.

        For each guest room, subscribes to the room's URA occupancy entity
        (binary_sensor.{room_slug}_occupied). Bug Class #38: unsubs stored in
        _guest_room_unsubs; cleaned up on teardown.
        """
        from ..const import (
            CONF_ENTRY_TYPE, CONF_ROOM_NAME, ENTRY_TYPE_ROOM,
            CONF_ROOM_IS_GUEST_ROOM, CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
        )

        # Cancel any existing guest-room listeners (handles reconfigure-without-restart).
        for unsub in self._guest_room_unsubs.values():
            try:
                unsub()
            except Exception:
                pass
        self._guest_room_unsubs.clear()
        self._guest_room_state.clear()

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            merged = {**entry.data, **entry.options}
            if not merged.get(CONF_ROOM_IS_GUEST_ROOM, False):
                continue

            room_name = merged.get(CONF_ROOM_NAME, "")
            if not room_name:
                continue

            threshold_min = int(merged.get(CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN, 30))
            room_slug = room_name.lower().replace(" ", "_")
            occupancy_entity_id = f"binary_sensor.{room_slug}_occupied"

            # Initialise anti-flap state for this room.
            self._guest_room_state[room_name] = {
                "first_seen": None,
                "current_occupancy_known": False,
                "threshold_min": threshold_min,
            }

            # Subscribe to the room's URA occupancy sensor.
            # Bug Class #42: listener callback is a bound method; no lambda captures.
            # Bug Class #38: unsub stored for cleanup.
            unsub = async_track_state_change_event(
                self.hass,
                [occupancy_entity_id],
                self._handle_guest_room_occupancy_change,
            )
            self._guest_room_unsubs[room_name] = unsub

            _LOGGER.info(
                "D5 guest room registered: '%s' (threshold=%d min, entity=%s)",
                room_name, threshold_min, occupancy_entity_id,
            )

    @callback
    def _handle_guest_room_occupancy_change(self, event: Any) -> None:
        """Handle occupancy state change for a designated guest room (D5).

        State machine transitions (per plan §4.D5):
        1. Room occupied + occupant unknown → arm first_seen (if None).
        2. Room occupied + occupant known → reset first_seen, set known=True.
        3. Room unoccupied → reset first_seen.

        Bug Class #11: uses dt_util.utcnow() for UTC-aware timestamps.
        Bug Class #42: @callback bound method, not lambda.
        Bug Class #19: async_create_task used for inference scheduling — safe because
        @callback runs on the event loop thread (not a background thread). This matches
        the established pattern at _handle_occupancy_change and _handle_state_change.
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        if new_state.state in _UNAVAILABLE_STATES:
            occupied = False
        else:
            occupied = new_state.state == "on"

        # Identify which guest room this entity belongs to.
        room_name = None
        for rn, state_dict in self._guest_room_state.items():
            rn_slug = rn.lower().replace(" ", "_")
            if f"binary_sensor.{rn_slug}_occupied" == entity_id:
                room_name = rn
                break

        if room_name is None:
            return

        state_dict = self._guest_room_state[room_name]
        now = dt_util.utcnow()

        if not occupied:
            # Transition 3: room unoccupied → reset first_seen.
            if state_dict["first_seen"] is not None:
                _LOGGER.debug(
                    "D5 guest room '%s': went unoccupied — resetting first_seen",
                    room_name,
                )
            state_dict["first_seen"] = None
            state_dict["current_occupancy_known"] = False
        else:
            # Room occupied — check if occupant is known.
            occupant_known = self._is_known_person_in_room(room_name)
            if occupant_known:
                # Transition 2: known person → reset, not a guest signal.
                state_dict["first_seen"] = None
                state_dict["current_occupancy_known"] = True
                _LOGGER.debug(
                    "D5 guest room '%s': known person detected — gate disarmed",
                    room_name,
                )
            else:
                # Transition 1: unknown occupant → arm first_seen if not already set.
                if state_dict["first_seen"] is None:
                    state_dict["first_seen"] = now
                    _LOGGER.info(
                        "D5 guest room '%s': unknown occupant — first_seen armed at %s",
                        room_name, now.isoformat(),
                    )
                state_dict["current_occupancy_known"] = False

        # Trigger inference re-evaluation.
        self.hass.async_create_task(self._run_inference("guest_room_occupancy"))

    def _is_known_person_in_room(self, room_name: str) -> bool:
        """Return True if any known tracked person is currently in the given room.

        Uses person_coordinator's zone tracker if available.
        Falls back to False (unknown = safer for guest detection).
        Bug Class #14: reads fresh from hass.data each call.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return False
            person_coord = manager.coordinators.get("person")
            if person_coord is None:
                return False
            # Check if any tracked person's current location resolves to this room.
            tracked = getattr(person_coord, "_tracked_persons", {})
            for _pid, person_data in tracked.items():
                location = person_data.get("location", "")
                if location and location.lower().replace(" ", "_") == room_name.lower().replace(" ", "_"):
                    return True
        except Exception:
            _LOGGER.debug(
                "D5: could not check known persons in room '%s' (non-fatal)",
                room_name, exc_info=True,
            )
        return False

    def _guest_room_gate_armed(self, now: datetime) -> bool:
        """Evaluate whether any designated guest room triggers the sustained-occupancy gate.

        Returns True if ANY guest room has:
        1. An unknown occupant continuously present for >= threshold_min minutes, AND
        2. The occupant is NOT a known tracked person.

        Exit is immediate: if the condition clears for all rooms, returns False.
        Bug Class #11: uses UTC-aware now parameter.
        """
        for room_name, state_dict in self._guest_room_state.items():
            first_seen = state_dict.get("first_seen")
            if first_seen is None:
                continue
            if state_dict.get("current_occupancy_known", False):
                continue
            threshold_min = state_dict.get("threshold_min", 30)
            elapsed_min = (now - first_seen).total_seconds() / 60.0
            if elapsed_min >= threshold_min:
                _LOGGER.info(
                    "D5 guest room gate fires: room='%s', elapsed=%.1f min (>= %d min)",
                    room_name, elapsed_min, threshold_min,
                )
                return True
        return False

    def _guest_gate_armed(
        self,
        unidentified_count: int,
        census_confidence: str,
        now: datetime,
    ) -> bool:
        """Evaluate all guest-mode entry guards.

        Guards (short-circuit on first failure):
        1. Existence: unidentified_count > 0
        2. Confidence: census_confidence >= _guest_require_confidence
        3. Persistence: unidentified has been seen for >= _guest_persistence_seconds

        On first qualifying tick: arms the gate (sets _unidentified_first_seen)
        and schedules a recheck after persistence_seconds + 5s.
        On non-qualifying tick: disarms (clears state + cancels timer).
        Returns True only when all guards pass.
        """
        # Guard 1: Existence
        if unidentified_count <= 0:
            _LOGGER.debug(
                "Guest gate: no unidentified persons (count=%d) — disarming",
                unidentified_count,
            )
            self._disarm_guest_gate()
            return False

        # Guard 2: Confidence
        if not self._confidence_at_least(census_confidence, self._guest_require_confidence):
            _LOGGER.debug(
                "Guest gate: confidence too low (observed=%s < required=%s) — disarming",
                census_confidence, self._guest_require_confidence,
            )
            self._disarm_guest_gate()
            return False

        # Guard 3: Persistence
        persistence_secs = self._guest_persistence_seconds
        if persistence_secs <= 0:
            # Persistence disabled — fire immediately
            _LOGGER.debug("Guest gate: persistence disabled — firing immediately")
            self._disarm_guest_gate()
            return True

        if self._unidentified_first_seen is None:
            # First qualifying tick — arm the gate
            self._unidentified_first_seen = now
            _LOGGER.info(
                "Guest gate armed: unidentified=%d, confidence=%s — "
                "waiting %ds before firing",
                unidentified_count, census_confidence, persistence_secs,
            )
            # Schedule a forced recheck so we don't depend on census jitter
            self._schedule_guest_persistence_recheck(persistence_secs)
            return False

        elapsed = (now - self._unidentified_first_seen).total_seconds()
        if elapsed >= persistence_secs:
            _LOGGER.info(
                "Guest gate fires: unidentified=%d persisted for %.0fs (>= %ds)",
                unidentified_count, elapsed, persistence_secs,
            )
            # Cancel pending recheck handle — gate is firing now
            if self._guest_persistence_check_handle is not None:
                self._guest_persistence_check_handle()
                self._guest_persistence_check_handle = None
            return True

        _LOGGER.debug(
            "Guest gate: persistence not yet met (%.0f / %d s)",
            elapsed, persistence_secs,
        )
        return False

    def _schedule_guest_persistence_recheck(self, persistence_secs: int) -> None:
        """Schedule a one-shot recheck after the persistence window + 5s buffer.

        Cancelled on disarm, gate fire, or coordinator unload.
        The +5s buffer ensures we always fire AFTER the window, never at its edge.
        """
        from homeassistant.helpers.event import async_call_later

        # Cancel any existing handle first (e.g. if re-armed after partial disarm)
        if self._guest_persistence_check_handle is not None:
            self._guest_persistence_check_handle()
            self._guest_persistence_check_handle = None

        @callback
        def _recheck_callback(_now: datetime) -> None:
            self._guest_persistence_check_handle = None
            self.hass.async_create_task(
                self._run_inference("guest_persistence_recheck")
            )

        self._guest_persistence_check_handle = async_call_later(
            self.hass, persistence_secs + 5, _recheck_callback,
        )
        _LOGGER.debug(
            "Guest persistence recheck scheduled in %ds",
            persistence_secs + 5,
        )

    async def _run_inference(self, trigger: str) -> None:
        """Run state inference and apply transitions.

        v3.6.0.11: Schedules deferred retry when hysteresis blocks.
        """
        if not self._enabled:
            return

        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        # Cold-boot settle gate — Predicate A (input-driven release).
        # Flip BEFORE the dispatch decision so the first inference tick that
        # sees real-world signal is NOT itself suppressed. Counts as "real":
        #   - census_count >= BOOT_SETTLE_MIN_INPUTS, OR
        #   - any zone tracker already in OCCUPIED mode.
        # DATA-DRIVEN ONLY — the inference trigger label is deliberately NOT
        # consulted. Boot-time triggers like "camera_detection" / "census_update"
        # / "occupancy_change" arrive before census has settled, so releasing on
        # trigger-label would defeat the gate on exactly the cold-boot profile it
        # exists to hold (Reviewer A HIGH-A1, 2026-06-04). census_update naturally
        # bumps _census_count, and a real occupant flips a zone tracker OCCUPIED,
        # so both legitimate release paths are still covered by the data checks.
        if not self._boot_settle_done:
            _real_input = (
                self._census_count >= BOOT_SETTLE_MIN_INPUTS
                or any(
                    t.mode == ZonePresenceMode.OCCUPIED
                    for t in (self._zone_trackers or {}).values()
                )
            )
            if _real_input:
                self._release_boot_settle("real_input")

        # Tier-3 D2 (D-HIGH-3): refresh the mmwave-fan demoted snapshot
        # ONCE per inference tick. is_room_mmwave_fan_demoted (consumed
        # by room coordinators) reads this frozen view — never calls the
        # primitive live. Off-cadence contract per
        # _compute_fan_interference_rooms docstring.
        try:
            self._mmwave_fan_demoted_snapshot = frozenset(
                self._compute_mmwave_fan_demoted_rooms()
            )
        except Exception:  # noqa: BLE001 — defensive; keep last snapshot
            _LOGGER.debug(
                "mmwave-fan demoted snapshot refresh failed (non-fatal)",
                exc_info=True,
            )

        # D4: Capture zone modes before inference for change detection
        zone_modes_before = {
            name: tracker.mode for name, tracker in self._zone_trackers.items()
        }

        # v4.7.14: Compute all-persons-away veto signal from person_coordinator.
        # When every configured person.* tracker reports "away" (and the config
        # is non-empty), pass this to infer() so it can veto camera ghost-presence.
        # tracked_count > 0 guard: empty config must not veto (fail-safe).
        # "unknown" is NOT treated as away (conservative — unknown is genuine
        # uncertainty, not confirmed absence).
        #
        # v4.7.14.1 (H2): exclude any person whose phone-left-behind sensor
        # is `on` from the veto denominator. PersonPhoneLeftBehindSensor
        # (binary_sensor.py:973-1084) flags "BLE places phone in a room but no
        # camera has seen the person in the last hour" — the canonical
        # forgotten-phone signal. Their location field is meaningless for veto
        # purposes. Fail-OPEN: if the binary_sensor doesn't exist (disabled
        # by default per binary_sensor.py:988) or is unknown/unavailable, the
        # person is counted (preserves v4.7.14 baseline behavior).
        #
        # v4.7.14.1 fix-up A-H1: resolve entity_id via the ENTITY REGISTRY by
        # unique_id rather than by string construction. The sensor registers
        # with `_attr_has_entity_name=True` (binary_sensor.py:989) + DeviceInfo
        # name "Universal Room Automation" (binary_sensor.py:1003-1008), which
        # composes a device-prefixed entity_id (e.g.
        # `binary_sensor.universal_room_automation_oji_udezue_phone_left_behind`,
        # operator-verified 2026-05-30) — NOT the bare slug. We MUST mirror
        # binary_sensor.py:1000's unique_id formula and resolve via
        # entity_registry.async_get_entity_id; otherwise H2 silently fails-OPEN
        # for every person and Gap B remains unclosed.
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        all_tracked_persons_away = False
        tracked_count = 0
        away_person_ids: list[str] = []

        # Import inline to keep module import surface minimal (only used here).
        from homeassistant.helpers import entity_registry as er
        try:
            _entity_reg = er.async_get(self.hass)
        except Exception:  # noqa: BLE001 — defensive: registry may be unavailable in tests/early-boot
            _entity_reg = None

        def _phone_trustworthy(person_name: str) -> bool:
            """v4.7.14.1 (H2): True iff the phone-left-behind sensor is NOT 'on'.

            Fail-OPEN: missing entity / unknown / unavailable -> True.
            Resolves the entity_id via entity_registry by unique_id (fix-up
            A-H1) — mirrors binary_sensor.py:1000's unique_id formula:
            ``f"{DOMAIN}_person_{<slug>}_phone_left_behind"``. Robust to
            device renames and operator entity_id renames.
            """
            person_slug = person_name.lower().replace(" ", "_")
            unique_id = f"{DOMAIN}_person_{person_slug}_phone_left_behind"
            entity_id: str | None = None
            if _entity_reg is not None:
                try:
                    entity_id = _entity_reg.async_get_entity_id(
                        "binary_sensor", DOMAIN, unique_id
                    )
                except Exception:  # noqa: BLE001 — registry shape errors are fail-OPEN
                    entity_id = None
            if entity_id is None:
                # Entity not registered (sensor disabled by default per
                # binary_sensor.py:988, or operator hasn't enabled it). Fail-OPEN.
                return True
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                return True
            return state.state != "on"

        def _tracking_active(info: dict) -> bool:
            """v4.7.14.1 (H3): True iff tracking_status is ACTIVE.

            REUSES the `tracking_status` field set by person_coordinator.py at
            :213 (ACTIVE), :288 (STALE), :153/:333/:345/:377 (LOST). Only
            ACTIVE counts as confirmed-away for the high-confidence veto.

            Defensive default: missing tracking_status field -> ACTIVE (fail
            forward toward v4.7.14 baseline; older-shape entries are
            preserved rather than silently excluded).
            """
            return info.get("tracking_status", TRACKING_STATUS_ACTIVE) == TRACKING_STATUS_ACTIVE

        # v5.7.0 WS-A1: module-level `_tracking_active_or_lost_away` is the
        # load-bearing predicate; bind a local alias for readability inside
        # the per-person loop below. Defined at module scope (above) so the
        # Tier-3 mutation-anchor tests can drive the REAL site.
        _tracking_active_or_lost_away_local = _tracking_active_or_lost_away

        # v4.7.14.1 fix-up A-M1/A-M3: track WHO was filtered out and WHY so the
        # veto-fired INFO log can enumerate excluded persons + reason. Without
        # this, operators debugging "why didn't X block the veto?" must grep
        # the source to understand the post-filter shape.
        # v5.7.0 WS-A path-β state. Mirror of the path-α denominator built
        # with the relaxed `_tracking_active_or_lost_away` predicate. Empty
        # / False unless the relaxed-denominator block below populates them.
        all_trusted_or_lost_away_persons_away: bool = False
        lost_away_persons: list[str] = []
        # excluded_persons is the path-α exclusion-reason map (preserved verbatim).
        excluded_persons: dict[str, str] = {}
        # v4.7.14.1 fix-up A-M2: separately track the RAW configured-person
        # count so the diagnostic sensor can expose BOTH the raw count
        # (pre-v4.7.14.1 semantic preserved) AND the post-filter trustworthy
        # count (new). Without this, operators seeing `tracked_persons_count`
        # drop from 4 to 3 would misdiagnose person_coordinator dropout.
        tracked_count_raw = 0
        # v4.7.15.1 D1: capture per-person H2/H3 booleans in deterministic
        # (sorted) order so we can feed them as parallel-list reliable signals
        # to should_veto_due_to_reliable_signals(scope="house_inference"). The
        # helper's positional zip relies on the two lists being aligned.
        person_phone_trust_signals: list[bool] = []
        person_tracking_active_signals: list[bool] = []
        try:
            if person_coordinator and getattr(person_coordinator, "data", None):
                person_data = person_coordinator.data or {}
                tracked_count_raw = len(person_data)
                # H2 + H3 filter: remove persons whose phone is flagged
                # phone_left_behind OR whose tracking_status is not ACTIVE.
                # The per-name loop replaces the dict-comprehension to capture
                # the exclusion reason inline (A-M1/M3).
                trustworthy_persons: dict[str, dict] = {}
                # Deterministic order for parallel-list signal alignment.
                for name in sorted(person_data.keys()):
                    info = person_data[name]
                    phone_ok = _phone_trustworthy(name)
                    track_ok = _tracking_active(info)
                    person_phone_trust_signals.append(bool(phone_ok))
                    person_tracking_active_signals.append(bool(track_ok))
                    if phone_ok and track_ok:
                        trustworthy_persons[name] = info
                        continue
                    # phone_left_behind takes precedence in the reason string
                    # when both fire (it's the more specific user-actionable
                    # signal — "your phone is home but you aren't").
                    if not phone_ok:
                        excluded_persons[name] = "phone_left_behind=on"
                    else:
                        excluded_persons[name] = (
                            f"tracking_status={info.get('tracking_status', 'unknown')}"
                        )
                tracked_count = len(trustworthy_persons)
                if tracked_count > 0:
                    all_tracked_persons_away = all(
                        (info.get("location") or "") in ("away", "")
                        for info in trustworthy_persons.values()
                    )
                    if all_tracked_persons_away:
                        away_person_ids = sorted(trustworthy_persons.keys())

                # v5.7.0 WS-A1: build the relaxed-denominator denominator for
                # path β. Same H2 phone-left-behind filter (preserved
                # verbatim) but using the H3-relaxed predicate
                # _tracking_active_or_lost_away. Persons whose phone is
                # phone_left_behind=on are STILL excluded (left-behind phone
                # is the canonical not-trustworthy signal). LOST+home
                # entries are NOT counted as away (the LOST-relaxed
                # predicate returns False for them). Final all-away check
                # uses ("away", "") tuple identical to path α — "unknown"
                # is conservatively excluded.
                relaxed_persons: dict[str, dict] = {}
                for name in sorted(person_data.keys()):
                    info = person_data[name]
                    if not _phone_trustworthy(name):
                        continue  # H2 preserved
                    if not _tracking_active_or_lost_away_local(info):
                        continue  # neither ACTIVE nor LOST/STALE+away
                    relaxed_persons[name] = info
                if len(relaxed_persons) > 0:
                    all_trusted_or_lost_away_persons_away = all(
                        (info.get("location") or "") in ("away", "")
                        for info in relaxed_persons.values()
                    )
                    if all_trusted_or_lost_away_persons_away:
                        # lost_away_persons enumerates the subset that are
                        # in path β but NOT in path α — i.e. the LOST/STALE
                        # entries that are now admitted. Used for the
                        # `lost_away_persons` sensor attribute (per plan
                        # WS-A1 acceptance criteria).
                        for name, info in relaxed_persons.items():
                            ts = info.get(
                                "tracking_status", TRACKING_STATUS_ACTIVE
                            )
                            if ts != TRACKING_STATUS_ACTIVE:
                                lost_away_persons.append(name)
                        lost_away_persons.sort()
        except Exception as exc:  # noqa: BLE001 — defensive: stale coord data
            _LOGGER.debug(
                "v4.7.14: failed to compute all_tracked_persons_away: %s", exc
            )
            all_tracked_persons_away = False
            tracked_count = 0
            tracked_count_raw = 0
            away_person_ids = []
            excluded_persons = {}
            person_phone_trust_signals = []
            person_tracking_active_signals = []
            # v5.7.0 WS-A: also reset path-β locals on failure (fail-safe:
            # path β cannot fire when denominator computation raised).
            all_trusted_or_lost_away_persons_away = False
            lost_away_persons = []
        # Expose for diagnostics (PresenceHouseStateSensor attributes).
        # v4.7.14.1 fix-up A-M2: `_tracked_persons_count` preserves pre-v4.7.14.1
        # semantic (raw configured count); `_tracked_persons_count_trusted` is
        # the new post-H2/H3 filtered denominator.
        self._tracked_persons_count = tracked_count_raw
        self._tracked_persons_count_trusted = tracked_count
        self._all_tracked_persons_away = all_tracked_persons_away
        # v4.7.14.1 fix-up A-M1/A-M3: snapshot of filtered-out persons + reason
        # for the veto-fired log and downstream sensor attribute exposure.
        self._excluded_persons = dict(excluded_persons)

        any_zone_occupied = any(
            t.mode == ZonePresenceMode.OCCUPIED
            for t in self._zone_trackers.values()
        )

        # v5.7.0 WS-A4: per-zone outdoor exclusion. `any_indoor_zone_occupied`
        # mirrors `any_zone_occupied` but excludes zones flagged
        # CONF_ZONE_IS_OUTDOOR=True in their config. An occupied outdoor
        # zone (doorbell-camera "Outside", "Front Porch") still contributes
        # to `any_zone_occupied` for HVAC/fan/comfort consumers, but does
        # NOT block the WS-A2 path-β AWAY veto — otherwise a doorbell
        # face-ID while everyone is away would silently jam the veto.
        outdoor_zone_names = self._outdoor_zone_names_snapshot()
        any_indoor_zone_occupied = any(
            t.mode == ZonePresenceMode.OCCUPIED
            for zone_name, t in self._zone_trackers.items()
            if zone_name not in outdoor_zone_names
        )
        # Expose for diagnostics.
        self._outdoor_zones = sorted(outdoor_zone_names)

        # v4.7.18.1 D1: Parallel raw-signal local for the WAKING gate. The
        # mode-based `any_zone_occupied` above is masked to SLEEP during sleep
        # hours (set_sleep hard-overrides every auto tracker), so it can never
        # surface real morning movement. The wake timer must observe the raw
        # tiers (`_derived_mode == OCCUPIED`) to detect the sustained signal
        # that exits SLEEP. `any_zone_occupied` is left untouched for its
        # other consumers (infer() arg, AWAY-veto log).
        any_zone_raw_occupied = any(
            t.raw_occupied for t in self._zone_trackers.values()
        )

        # v4.7.15 D3: Track sustained-occupancy timer for the WAKING gate.
        # Bug Class #11: UTC-aware timestamps.
        # v4.7.18.1 D1: Re-sourced from `any_zone_raw_occupied` (see above).
        #
        # v4.7.18.1 fix-up B-HIGH-2 (document-and-accept): `_run_inference`
        # is invoked unserialized from multiple sites (census_update,
        # occupancy_change, camera_detection, deferred_retry, guest_room_*,
        # geofence_*, periodic). No asyncio.Lock guards the body — this is
        # a pre-existing condition that predates this hotfix. The only new
        # exposure introduced by D2 is a possible cosmetic double-increment
        # of `_wake_backstop_fires` if two ticks pass the gate concurrently.
        # The WAKING transition itself is idempotent — re-proposing WAKING
        # when current_state is already WAKING is rejected by the state
        # machine's transition() guard. Blast radius minimal; no lock added.
        _now_utc = dt_util.utcnow()
        if any_zone_raw_occupied:
            if self._first_positive_zone_occupied_since is None:
                self._first_positive_zone_occupied_since = _now_utc
        else:
            # Cleared on any False — a brief True→False→True burst cannot
            # accumulate sustained seconds (per plan §3 D3 acceptance).
            self._first_positive_zone_occupied_since = None

        current_state = manager.house_state_machine.state

        # v4.6.2.2: Evaluate guest gate (threshold + confidence + persistence)
        # before calling the inference engine. Also clear the arm state when
        # house leaves HOME_* so we don't carry stale arm across state changes.
        now = dt_util.now()
        _home_like_states = (
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
        )
        if current_state not in _home_like_states and current_state != HouseState.GUEST:
            # House is not in a HOME/GUEST state — disarm any pending gate
            if self._unidentified_first_seen is not None:
                _LOGGER.debug(
                    "Guest gate disarmed: house left HOME_* (current=%s)",
                    current_state.value,
                )
                self._disarm_guest_gate()

        # Evaluate the guest gate when in HOME_* states (entry path) or already
        # in GUEST state (hold/exit path).  The unid gate (_guest_gate_armed) has
        # side effects (arms/disarms persistence state) so it is SKIPPED in GUEST
        # state.  The guest_room gate (_guest_room_gate_armed) is a pure predicate
        # with no side effects, so it is safe to evaluate in GUEST state and MUST
        # be evaluated so the exit condition at infer() line 449 gets a truthful
        # value.  Without this, the exit condition reduces to unidentified_count==0
        # which causes immediate GUEST→HOME oscillation on every inference cycle.
        # B1 fix (v4.7.2 reviewer fix-up) — Bug Class #46: Exit-Path Gate Skip.
        if current_state in _home_like_states:
            unid_gate_armed = self._guest_gate_armed(
                unidentified_count=self._unidentified_count,
                census_confidence=self._census_confidence,
                now=now,
            )
            # v4.7.2 D5: Sustained-occupancy guest room path (additive OR).
            # Bug Class #11: D5 timestamps are UTC-aware (dt_util.utcnow()).
            guest_room_gate_armed = self._guest_room_gate_armed(now=dt_util.utcnow())
            guest_armed = unid_gate_armed or guest_room_gate_armed
        elif current_state == HouseState.GUEST:
            # Already in GUEST state — skip unid gate (side-effect-bearing) but
            # evaluate guest_room gate (pure predicate) so the hold/exit decision
            # at infer() line 449 is truthful.
            unid_gate_armed = False
            # Bug Class #11: D5 timestamps are UTC-aware (dt_util.utcnow()).
            guest_room_gate_armed = self._guest_room_gate_armed(now=dt_util.utcnow())
            guest_armed = guest_room_gate_armed
        else:
            unid_gate_armed = False
            guest_room_gate_armed = False
            guest_armed = False

        # v4.7.2 D5: Confidence layering math (plan §7).
        # unid path: 0.8 (existing). guest_room path: 0.9 (higher specificity).
        # max() when both fire; individual when only one fires.
        if guest_room_gate_armed and unid_gate_armed:
            _d5_guest_confidence: float = max(0.8, 0.9)  # = 0.9
        elif guest_room_gate_armed:
            _d5_guest_confidence = 0.9
        else:
            _d5_guest_confidence = 0.8  # unid path only, or neither (ignored)

        # v4.7.16 D3: Per-room BLE-tier weighted veto (zone-iterates-rooms).
        # For each zone, build a weight map keyed by room_name using the
        # canonical CONF_SCANNER_AREAS classification surfaced by
        # PersonTrackingCoordinator.get_ble_tier (D1). Tier 1 = 1.0,
        # Tier 2 = BLE_TIER_2_WEIGHT (default 0.6), Tier 0 = 0.0.
        #
        # The aggregated weight is fed to the v4.7.15 shared veto helper
        # which decides whether to veto an OCCUPIED reading in favor of
        # the multi-tier consensus. v4.7.16 records the verdict on
        # self._v4716_zone_verdicts for diagnostics; downstream gating
        # ties in once the helper API is stable.
        #
        # v4.7.16 D3: verify helper signature post v4.7.15 lands
        # — expected: should_veto_due_to_reliable_signals(
        #              reliable_signals=[...], transient_signals=[...],
        #              state_context={...}) -> VetoDecision(fired, confidence, reason, scope)
        #
        # Post-review B LOW-1: drop the per-tick type annotation here;
        # the field is annotated once in __init__ at line 560. This is a
        # reset, not a redeclaration.
        self._v4716_zone_verdicts = {}

        # Post-review B MEDIUM #1 (perf kill-switch): skip the entire D3
        # block when the diagnostic flag is False. Saves ~1200 string
        # normalizations/cycle on a 30-room install. Default True (D3 is
        # the v4.7.15 helper integration scaffold) — operators can flip
        # to False when the diagnostic is not being consumed downstream.
        #
        # Post-review B MEDIUM #2 (sleep-state gate): skip during
        # house_state=SLEEP. Room sensors are intentionally degenerate
        # during sleep (mmWave drops motionless body, PIR silent, cameras
        # blind) — v4.7.13 trusts the person tracker, NOT per-room BLE
        # weights, during sleep. Future consumers of _v4716_zone_verdicts
        # must not act on D3 weights when house_state is SLEEP, so skip
        # the computation entirely. `current_state` is the HouseState
        # enum read at :1995 above.
        _d3_skip = (
            (not D3_DIAGNOSTIC_ENABLED)
            or (current_state == HouseState.SLEEP)
        )
        try:
            if _d3_skip:
                # Verdict dict stays empty; downstream consumers fall back
                # to pre-v4.7.16 inference behavior.
                pass
            else:
                for zone_name, tracker in self._zone_trackers.items():
                    weights: Dict[str, float] = {}
                    for room_name in getattr(tracker, "room_names", []) or []:
                        if person_coordinator is None or not hasattr(
                            person_coordinator, "get_ble_tier"
                        ):
                            # Fail-open: behave like pre-v4.7.16 (every room
                            # gets weight 1.0). Logged once per cycle below.
                            weights[room_name] = 1.0
                            continue
                        try:
                            tier = int(person_coordinator.get_ble_tier(room_name))
                        except Exception as exc:  # pragma: no cover - defensive
                            _LOGGER.debug(
                                "v4.7.16 D3: get_ble_tier(%s) failed: %s",
                                room_name, exc,
                            )
                            tier = 0
                        if tier == 1:
                            weights[room_name] = 1.0
                        elif tier == 2:
                            weights[room_name] = BLE_TIER_2_WEIGHT
                        else:
                            weights[room_name] = 0.0
                    # v4.7.16 D3 (post-review A1, HIGH): aggregation = max.
                    # Reviewer A explicitly picked `max` over `sum` to preserve
                    # the v3.8.9 invariant "Tier 1 dominates Tier 2". Under sum,
                    # five Tier-2 rooms (5 * 0.6 = 3.0) would outweigh one
                    # Tier-1 room (1.0), inverting the design rationale.
                    # Under max, a zone's aggregate equals the strongest BLE
                    # evidence present:
                    #   max=1.0  ⟺ ≥1 Tier-1 room (own scanner)
                    #   max=0.6  ⟺ only Tier-2 rooms (borrowed scanner)
                    #   max=0.0  ⟺ Tier-0 only (no BLE)
                    # Per-room weights remain available to the v4.7.15 helper
                    # via state_context["room_weights"] for any aggregation
                    # the helper wants to perform internally.
                    aggregate_weight = max(weights.values()) if weights else 0.0

                    # Invoke v4.7.15 helper if available. Otherwise degrade
                    # gracefully to no-veto (preserves pre-v4.7.16 behavior).
                    # v4.7.16 D3: verify helper signature post v4.7.15 lands
                    #
                    # Post-review A2 (FALSE ALARM, verified against shipped
                    # v4.7.15 D1 commit 221b814): v4.7.15 ships the helper as
                    # an instance method on `PresenceCoordinator`, not as a
                    # module-level function. `getattr(self, ...)` is therefore
                    # the CORRECT lookup pattern. See commit 221b814:
                    # `def should_veto_due_to_reliable_signals(self, reliable_signals,
                    #  transient_signals, state_context) -> VetoDecision`. Reviewer
                    # A's concern was based on the planning doc's language; the
                    # actual ship is instance-method, so this lookup will resolve
                    # post-v4.7.15-merge.
                    veto_decision = None
                    helper = getattr(
                        self, "should_veto_due_to_reliable_signals", None
                    )
                    if helper is not None:
                        try:
                            reliable_signals: list = []
                            transient_signals: list = []
                            state_context = {
                                "scope": "room_level_weighted",
                                "zone_name": zone_name,
                                "house_state": getattr(
                                    manager, "house_state", ""
                                ),
                                "room_weights": dict(weights),
                                "aggregate_weight": aggregate_weight,
                                "all_tracked_persons_away": all_tracked_persons_away,
                                "tracked_count": tracked_count,
                                # v4.7.16 D3 (post-review A3, HIGH): Bug Class #11.
                                # Sibling guest-gate code at :2032/:2040 uses UTC;
                                # helper context must too. Local `now` above is
                                # still fine for the guest-gate code that built it.
                                "now": dt_util.utcnow(),
                            }
                            # v4.7.16 D3: verify helper signature post v4.7.15 lands
                            veto_decision = helper(
                                reliable_signals=reliable_signals,
                                transient_signals=transient_signals,
                                state_context=state_context,
                            )
                        except Exception as exc:  # pragma: no cover - defensive
                            _LOGGER.warning(
                                "v4.7.16 D3: shared veto helper raised for "
                                "zone %s: %s — degrading to no-veto",
                                zone_name, exc,
                            )
                            veto_decision = None
                    self._v4716_zone_verdicts[zone_name] = {
                        "room_weights": dict(weights),
                        "aggregate_weight": aggregate_weight,
                        "veto_fired": (
                            bool(getattr(veto_decision, "fired", False))
                            if veto_decision is not None
                            else None
                        ),
                        "veto_confidence": (
                            float(getattr(veto_decision, "confidence", 0.0))
                            if veto_decision is not None
                            else None
                        ),
                        "veto_reason": (
                            str(getattr(veto_decision, "reason", ""))
                            if veto_decision is not None
                            else "helper_unavailable"
                        ),
                    }
        except Exception as exc:  # pragma: no cover - top-level guard
            _LOGGER.warning(
                "v4.7.16 D3: per-room weighting block failed: %s — "
                "preserving pre-v4.7.16 behavior",
                exc,
            )
            self._v4716_zone_verdicts = {}

        # v5.7.0 WS-A3: grace + sleep-exempt computation for path β.
        #
        # Read both CONFs from the CM entry options. Defaults preserved
        # from const (60 min grace, sleep-exempt True). Source-of-truth
        # lookup mirrors the existing guest-knob pattern at :3009-3110 of
        # config_flow.py — values land in CM entry options.
        _cm_entry = self._cm_entry_cache
        if _cm_entry is None:
            try:
                from ..const import ENTRY_TYPE_COORDINATOR_MANAGER, CONF_ENTRY_TYPE
                for e in self.hass.config_entries.async_entries(DOMAIN):
                    if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                        _cm_entry = e
                        self._cm_entry_cache = e
                        break
            except Exception:  # noqa: BLE001 — defensive: registry shape errors
                _cm_entry = None
        _cm_opts: dict = {}
        if _cm_entry is not None:
            try:
                _cm_opts = {**_cm_entry.data, **_cm_entry.options}
            except Exception:  # noqa: BLE001 — defensive
                _cm_opts = {}
        # v5.7.0 fix-up FIX-4 (A-MED-1): wrap int()/bool() reads in try/except
        # so storage corruption (a non-numeric CONF value) cannot abort the
        # inference tick. Fall back to the const defaults.
        try:
            _grace_min = int(
                _cm_opts.get(
                    CONF_LOST_AWAY_GRACE_MIN, DEFAULT_LOST_AWAY_GRACE_MIN
                )
            )
        except (TypeError, ValueError):  # noqa: BLE001 — storage corruption
            _grace_min = DEFAULT_LOST_AWAY_GRACE_MIN
            _LOGGER.debug(
                "v5.7.0 WS-A3: %s CONF unreadable; falling back to %d min",
                CONF_LOST_AWAY_GRACE_MIN, DEFAULT_LOST_AWAY_GRACE_MIN,
            )
        try:
            _sleep_exempt_cfg = bool(
                _cm_opts.get(
                    CONF_LOST_AWAY_SLEEP_EXEMPT,
                    DEFAULT_LOST_AWAY_SLEEP_EXEMPT,
                )
            )
        except Exception:  # noqa: BLE001 — defensive
            _sleep_exempt_cfg = DEFAULT_LOST_AWAY_SLEEP_EXEMPT
        try:
            _indoor_clear_ticks_req = int(
                _cm_opts.get(
                    CONF_LOST_AWAY_INDOOR_CLEAR_TICKS,
                    DEFAULT_LOST_AWAY_INDOOR_CLEAR_TICKS,
                )
            )
            if _indoor_clear_ticks_req < 0:
                _indoor_clear_ticks_req = DEFAULT_LOST_AWAY_INDOOR_CLEAR_TICKS
        except (TypeError, ValueError):  # noqa: BLE001
            _indoor_clear_ticks_req = DEFAULT_LOST_AWAY_INDOOR_CLEAR_TICKS

        # v5.7.0 fix-up FIX-5 (MED-B1): read the SEPARATE WS-A stamp dict
        # (`_lost_away_since`) — NOT `_person_lost_since`, which is owned by
        # the BLE pre-arrival timer. Stamping/clearing happens at the same
        # 4 LOST sites + 4 home transitions in person_coordinator, so the
        # two maps stay aligned on real away/home edges; isolating the maps
        # ensures BLE pre-arrival's `_min_away_minutes` budget is byte-
        # unaffected by WS-A grace.
        _lost_since_map: dict = {}
        if person_coordinator is not None:
            try:
                _lost_since_map = dict(
                    getattr(person_coordinator, "_lost_away_since", {}) or {}
                )
            except Exception:  # noqa: BLE001
                _lost_since_map = {}
        _now_local = dt_util.now()
        _grace_remaining_s: Optional[int] = None
        _grace_elapsed = True
        _youngest_lost_age_s: int = 0
        if lost_away_persons:
            # v5.7.0 fix-up FIX-2a (D-MED-1/D-MED-2/A-LOW-1): gate grace on
            # the YOUNGEST (most-recently-lost) stamp, not the oldest. The
            # most-recently-lost person is the one most likely to still be
            # home with a dead phone; `grace_elapsed` must remain False
            # until even that newest stamp exceeds the window. Also fixes
            # A-LOW-1: a person without a stamp keeps grace_elapsed=False
            # (we never break out preserving an artificial elapsed=True).
            _youngest_dt = None
            _any_stampless = False
            for name in lost_away_persons:
                dt = _lost_since_map.get(name)
                if dt is None:
                    # No stamp => treat as "just went LOST now" => the
                    # youngest LOST-age is 0 and grace cannot have elapsed.
                    _any_stampless = True
                    _youngest_dt = _now_local
                    continue
                if _youngest_dt is None or dt > _youngest_dt:
                    _youngest_dt = dt
            if _any_stampless:
                _grace_elapsed = False
                _grace_remaining_s = max(0, _grace_min * 60)
                _youngest_lost_age_s = 0
            elif _youngest_dt is not None:
                try:
                    _youngest_lost_age_s = int(
                        (_now_local - _youngest_dt).total_seconds()
                    )
                except Exception:  # noqa: BLE001 — tz mismatch
                    _youngest_lost_age_s = 0
                _grace_seconds = _grace_min * 60
                if _youngest_lost_age_s < _grace_seconds:
                    _grace_elapsed = False
                    _grace_remaining_s = max(
                        0, _grace_seconds - _youngest_lost_age_s
                    )
                else:
                    _grace_remaining_s = 0

        # v5.7.0 fix-up FIX-2b (D-HIGH-2): indoor-clear consecutive-tick
        # debounce. `any_indoor_zone_occupied` is already computed earlier
        # in this method (~:4416). Increment counter when clear; reset on
        # any indoor signal. Path β cannot fire until the counter meets
        # the configured threshold — protects against a single mmWave
        # dropout (or a 0-min grace misconfig) force-AWAYing a present
        # resident.
        if any_indoor_zone_occupied:
            self._indoor_clear_consecutive_ticks = 0
        else:
            self._indoor_clear_consecutive_ticks = min(
                self._indoor_clear_consecutive_ticks + 1, 10_000
            )
        _indoor_clear_debounced = (
            self._indoor_clear_consecutive_ticks >= _indoor_clear_ticks_req
        )

        # Presence batch fix-up (A-CRIT-1 / B-CRIT-1 / C-HIGH-1):
        # sustained-external-empty confirmation for D2 immediate-engage.
        # Requires N consecutive ticks of (census==0 AND unid==0 AND
        # _indoor_clear_debounced already satisfied). Reuses the FIX-2b
        # threshold (CONF_LOST_AWAY_INDOOR_CLEAR_TICKS, default 3) so
        # the two debounces stay consistent — no new CONF surface.
        _external_empty_this_tick = (
            self._census_count == 0
            and self._unidentified_count == 0
            and _indoor_clear_debounced
        )
        if _external_empty_this_tick:
            self._external_empty_consecutive_ticks = min(
                self._external_empty_consecutive_ticks + 1, 10_000
            )
        else:
            self._external_empty_consecutive_ticks = 0
        _sustained_external_empty = (
            self._external_empty_consecutive_ticks >= _indoor_clear_ticks_req
        )

        # Sleep exemption: SLEEP / HOME_NIGHT / WAKING are the protected
        # windows where a sleeping resident's phone may be dead for hours.
        # v5.7.0 fix-up FIX-1 (D-HIGH-1): also union with the sleep-HOUR
        # predicate so a still resident with a dead phone at e.g. 22:55
        # (HOME_EVENING but already inside the sleep window 23-06) is not
        # force-AWAYed before the state-machine has rolled into SLEEP.
        # Uses the SAME `_is_sleep_hour` the engine uses for guest-gate
        # suppression (~:1066), so both surfaces agree on what "sleep hour"
        # means.
        # VACATION: HouseState.VACATION is intentionally NOT in the
        # sleep-exempt tuple — when residents are deliberately away the
        # whole point is to allow force-AWAY; sleep-hour OR-extension is
        # also harmless during VACATION because by definition no resident
        # is home to be misjudged.
        _sleep_hour_now = False
        try:
            _sleep_hour_now = bool(
                self._inference_engine._is_sleep_hour(_now_local.hour)
            )
        except Exception:  # noqa: BLE001 — defensive: engine attr missing
            _sleep_hour_now = False
        _sleep_exempt_state = bool(
            _sleep_exempt_cfg
            and (
                current_state in (
                    HouseState.SLEEP,
                    HouseState.HOME_NIGHT,
                    HouseState.WAKING,
                )
                or _sleep_hour_now
            )
        )

        # v5.7.0 fix-up FIX-6 (B4): populate the diagnostic enumeration of
        # LOST-away persons even when a resident is HOME so the sensor
        # attribute is debuggable on the no-β-fire path. Grace remaining
        # is suppressed (set to None) when β is sleep-exempt so the surface
        # does not surface a misleading `grace_remaining_s = 0` (A-LOW-2).
        self._lost_away_persons = list(lost_away_persons)
        if _sleep_exempt_state:
            self._lost_away_grace_remaining_s = None
        else:
            self._lost_away_grace_remaining_s = _grace_remaining_s
        # Surface the debounce counter for live diagnostics.
        self._lost_away_indoor_clear_ticks = self._indoor_clear_consecutive_ticks

        # FIX-2b: fold the debounce into the grace_elapsed signal passed
        # into infer(). Path β requires BOTH grace elapsed AND debounce
        # satisfied. We bake debounce into `grace_elapsed_for_lost_away`
        # so the engine surface stays unchanged (engine signature is the
        # invariant — see I3) — semantically, grace_elapsed now means
        # "all gates the caller can compute outside the engine are clear".
        _grace_elapsed_with_debounce = bool(
            _grace_elapsed and _indoor_clear_debounced
        )

        new_state = self._inference_engine.infer(
            census_count=self._census_count,
            current_state=current_state,
            any_zone_occupied=any_zone_occupied,
            unidentified_count=self._unidentified_count,
            guest_gate_armed=guest_armed,
            all_tracked_persons_away=all_tracked_persons_away,
            # v5.7.0 WS-A path-β kwargs.
            all_trusted_or_lost_away_persons_away=all_trusted_or_lost_away_persons_away,
            any_indoor_zone_occupied=any_indoor_zone_occupied,
            grace_elapsed_for_lost_away=_grace_elapsed_with_debounce,
            lost_away_persons_present=bool(lost_away_persons),
            sleep_exempt_state=_sleep_exempt_state,
            # Presence batch fix-up: independent multi-tick signal for
            # the D2 immediate-engage limb. See infer() kwarg docstring.
            sustained_external_empty=_sustained_external_empty,
        )
        # Mirror engine's most-recent veto-path verdict for sensor surface.
        self._veto_path = getattr(self._inference_engine, "_veto_path", "none")

        # v4.7.14: log when the person-tracker veto fires to a non-AWAY state.
        # v4.7.14.1 fix-up A-M1: tighten gate to mirror the v4.7.14.1 H1
        # predicate (census_count == 0 AND any_zone_occupied) so this log
        # ONLY fires on the actual veto path (confidence 0.95), not the
        # line-398 AND-gate path (confidence 0.9). Pre-fix the log was
        # outcome-driven (`new_state == AWAY`) and could fire on either path,
        # misattributing the line-398 AND-gate transition to the veto.
        # A-M3 enriches the message: census_count, excluded_persons enumeration,
        # confidence — so operators reading journald can see why the veto fired.
        if (
            all_tracked_persons_away
            and self._unidentified_count == 0
            and self._census_count == 0
            and any_zone_occupied
            and new_state == HouseState.AWAY
            and current_state != HouseState.AWAY
        ):
            _excluded_payload = (
                ", ".join(
                    f"{p}({reason})"
                    for p, reason in sorted(self._excluded_persons.items())
                )
                if self._excluded_persons
                else "(none)"
            )
            # v4.7.15.1 fix-up A-M1 (Reviewer A): unify vocabulary with the
            # helper reason ("trusted=N") so journald log correlation works
            # against a single token. Prior wording said "trustworthy persons"
            # while the helper reason said "trusted=N" for the same number —
            # two labels for the same concept.
            _LOGGER.info(
                "v4.7.14.1: Person-tracker veto fired — %d trusted persons "
                "confirmed away (%s), %d excluded (%s), no unidentified people, "
                "census_count=0; forcing AWAY (was %s, any_zone_occupied=%s, "
                "confidence=0.95)",
                tracked_count,
                ", ".join(away_person_ids) if away_person_ids else "(none)",
                len(self._excluded_persons),
                _excluded_payload,
                current_state.value,
                any_zone_occupied,
            )

        # Override confidence if transitioning to GUEST via the D5 guest_room path.
        # The inference engine sets 0.8 by default; D5 raises it to 0.9 when warranted.
        if new_state == HouseState.GUEST and guest_room_gate_armed:
            self._inference_engine._confidence = _d5_guest_confidence

        # v4.7.15 D3: WAKING sustained-signal gate (Pattern D).
        # When the engine wants to flip SLEEP→WAKING, require sustained
        # occupancy. A single 03:24 Frigate blip cannot flip WAKING.
        if (
            new_state == HouseState.WAKING
            and current_state == HouseState.SLEEP
        ):
            sustained_seconds = 0
            if self._first_positive_zone_occupied_since is not None:
                sustained_seconds = int(
                    (_now_utc - self._first_positive_zone_occupied_since)
                    .total_seconds()
                )
            wake_decision = self.should_veto_due_to_reliable_signals(
                reliable_signals=[],
                transient_signals=[],
                state_context={
                    "scope": "waking_transition",
                    "house_state": current_state,
                    "sustained_occupancy_seconds": sustained_seconds,
                },
            )
            self._last_veto_decision = wake_decision
            if wake_decision.fired:
                # v4.7.18.1 D2: Daytime wake backstop. If the house has been
                # SLEEP well past sleep_end_hour and someone is provably home
                # (census_count > 0), force the WAKING transition rather than
                # suppress it. AWAY owns the census==0 case; this branch is the
                # safety valve for "stuck in SLEEP all morning with people
                # home." Assumes overnight sleep window (sleep_end < sleep_start,
                # shipped default 6/23).
                engine = self._inference_engine
                _local_hour = dt_util.now().hour
                _backstop_hour = (
                    engine.sleep_end_hour
                    + _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END
                )
                # v4.7.18.1 fix-up A-M2: clamp backstop_hour so the window
                # `_backstop_hour <= hour < sleep_start_hour` always contains
                # at least 1 hour. Without the clamp, an unusual sleep_end_hour
                # (e.g. 22 with sleep_start=23) yields _backstop_hour=25 → the
                # window is empty → backstop silently never fires. Assumes
                # overnight sleep (sleep_end < sleep_start) per plan.
                _backstop_hour_clamped = min(
                    _backstop_hour, engine.sleep_start_hour - 1
                )
                if _backstop_hour_clamped != _backstop_hour:
                    if not getattr(self, "_backstop_clamp_logged", False):
                        _LOGGER.debug(
                            "v4.7.18.1: backstop hour clamped from %02d to %02d "
                            "(sleep_end_hour=%d + %d >= sleep_start_hour=%d)",
                            _backstop_hour,
                            _backstop_hour_clamped,
                            engine.sleep_end_hour,
                            _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END,
                            engine.sleep_start_hour,
                        )
                        self._backstop_clamp_logged = True
                    _backstop_hour = _backstop_hour_clamped
                _backstop = (
                    self._census_count > 0
                    and _backstop_hour <= _local_hour < engine.sleep_start_hour
                )
                if _backstop:
                    self._wake_backstop_fires += 1
                    _LOGGER.warning(
                        "v4.7.18.1: WAKING backstop fired — SLEEP past %02d:00 "
                        "with census_count=%d; forcing wake despite "
                        "insufficient sustained signal (%s)",
                        _backstop_hour,
                        self._census_count,
                        wake_decision.reason,
                    )
                    # fall through WITHOUT suppressing — allow WAKING transition
                else:
                    self._wake_blocked_ticks += 1
                    _LOGGER.debug(
                        "v4.7.15 D3: WAKING transition blocked — %s",
                        wake_decision.reason,
                    )
                    new_state = None  # Suppress the WAKING transition this tick.

        # v4.7.15 D3: GUEST exit sustained-signal gate (Pattern E).
        # When the engine wants to flip GUEST → a HOME_* state, require the
        # exit condition (unidentified_count==0 AND not guest_armed) to have
        # persisted for >= _guest_persistence_seconds. Single-frame Frigate
        # FP that drops unidentified_count to 0 momentarily cannot exit GUEST.
        # Mirrors the v4.6.2.2 entry-side persistence symmetrically.
        if (
            current_state == HouseState.GUEST
            and new_state is not None
            and new_state != HouseState.GUEST
            and new_state in (
                HouseState.HOME_DAY,
                HouseState.HOME_EVENING,
                HouseState.HOME_NIGHT,
            )
        ):
            # The condition for exit must currently be true (otherwise infer()
            # wouldn't have returned a HOME_* state). Track first-seen time.
            if self._guest_exit_quiet_since is None:
                self._guest_exit_quiet_since = _now_utc
            quiet_seconds = int(
                (_now_utc - self._guest_exit_quiet_since).total_seconds()
            )
            exit_decision = self.should_veto_due_to_reliable_signals(
                reliable_signals=[],
                transient_signals=[],
                state_context={
                    "scope": "guest_exit",
                    "house_state": current_state,
                    "guest_exit_quiet_seconds": quiet_seconds,
                    # guest_persistence_seconds: helper will fall back to
                    # self._guest_persistence_seconds if omitted (symmetric).
                },
            )
            self._last_veto_decision = exit_decision
            if exit_decision.fired:
                _LOGGER.debug(
                    "v4.7.15 D3: GUEST exit blocked — %s", exit_decision.reason,
                )
                new_state = None  # Suppress the GUEST exit this tick.
            else:
                # Exit sustained — clear the timer so the next GUEST entry
                # restarts from None.
                self._guest_exit_quiet_since = None
        else:
            # Presence batch fix-up (A-MED-1): reset the timer on ANY
            # tick where the outer exit-tracking condition above is not
            # satisfied. The prior predicate
            # ``current_state != GUEST or new_state == GUEST`` missed
            # the case where the gate re-arms mid-persistence — e.g. a
            # new SLEEP-proposal or None is returned while still in
            # GUEST — leaving a stale epoch that would fire a later
            # exit instantly (no persistence). Clear whenever we are
            # not actively evaluating an exit for the current GUEST
            # state.
            self._guest_exit_quiet_since = None

        # v4.7.15.1 D1: Consolidated Pattern A invocation — house_inference
        # is the LAST writer of self._last_veto_decision per cycle
        # (operator-mandated DIAGNOSTIC-SURFACE invariant per plan
        # §"CRITICAL RISK PREMIUM" item 4).
        #
        # v4.7.15.1 fix-up A-M2 (Reviewer A): "LAST writer" here refers ONLY
        # to the DIAGNOSTIC surface (`_last_veto_decision`). It does NOT
        # mean Pattern A's verdict overrides state-transition authority.
        # The actual `new_state` came from `infer()` higher in this method
        # (line ~2452 — see `new_state = self._inference_engine.infer(...)`);
        # this call exists solely to populate the diagnostic surface that
        # operators query via
        # `sensor.ura_presence_house_state.last_veto_decision`. The
        # WAKING/GUEST gates above may have written transient values into
        # the surface earlier in the cycle — overwriting them with the
        # house_inference result is intentional and correct (operators see
        # the house-level veto state, not a transient WAKING gate result).
        #
        # The v4.7.14.1 H1/H2/H3 surfaces are plumbed through the shared
        # helper via the parallel-list signal contract:
        #   - H2 carried as ReliableSignal("person_phone_trustworthy", bool)
        #     one per tracked person (sorted-name order).
        #   - H3 carried as ReliableSignal("person_tracking_active", bool)
        #     one per tracked person (same order — helper does positional zip).
        #   - H1 carried as TransientSignal("census_count", int).
        # The inline filter loop above is preserved — it owns the
        # excluded_persons reason map (for the INFO log + diagnostic sensor)
        # and the all_tracked_persons_away boolean (consumed by
        # _inference_engine.infer()). Both paths read the same H1/H2/H3 data
        # so they MUST agree.
        try:
            reliable_signals_a = [
                ReliableSignal("person_tracker_away", all_tracked_persons_away),
                ReliableSignal(
                    "person_tracker_home",
                    not all_tracked_persons_away and tracked_count > 0,
                ),
            ]
            for _phone_ok in person_phone_trust_signals:
                reliable_signals_a.append(
                    ReliableSignal("person_phone_trustworthy", _phone_ok)
                )
            for _track_ok in person_tracking_active_signals:
                reliable_signals_a.append(
                    ReliableSignal("person_tracking_active", _track_ok)
                )
            house_inference_decision = self.should_veto_due_to_reliable_signals(
                reliable_signals=reliable_signals_a,
                transient_signals=[
                    TransientSignal(
                        "unidentified_person_count", self._unidentified_count,
                    ),
                    TransientSignal("census_count", self._census_count),
                ],
                state_context={
                    "scope": "house_inference",
                    "house_state": current_state,
                    "tracked_count": tracked_count,
                },
            )
            # Write UNCONDITIONALLY — preserves diagnostic surface every cycle
            # (per plan §D1.2 step 3). Because this is the LAST writer, when
            # the WAKING/GUEST gates also wrote earlier in the cycle, the
            # house_inference result becomes authoritative — which is correct
            # for diagnostic purposes (operators see the house-level veto
            # state, not a transient WAKING gate result).
            self._last_veto_decision = house_inference_decision
        except Exception as exc:  # noqa: BLE001 — defensive: don't crash _run_inference
            # v4.7.15.1 fix-up B1-M1 + B4-M1 (Reviewers B+D, converged):
            # Reviewer B flagged this as a silent-exception hole; if Pattern A
            # raises, the prior `pass` would leave `_last_veto_decision`
            # retaining a stale WAKING/GUEST write — no log, no diagnostic.
            # Bug Class #14 / #44 cousin (v4.6.1.1-class silent-payload-shape).
            # It also causes `_signal_consensus` (read by HVAC + Compliance
            # defer gates) and `_last_veto_decision` to diverge from each
            # other on the same tick.
            #
            # Fix: log explicitly + write a fallback sentinel that
            # PRESERVES the invariant `last_veto_decision.scope ==
            # "house_inference"` so operators monitoring the diagnostic
            # surface can still trust the scope label. Any non-
            # "house_inference" scope post-restart = silent-exception path
            # firing (the live-validation key documented in the README).
            _LOGGER.warning(
                "v4.7.15.1 Pattern A (house_inference) raised %s: %s — "
                "falling back to no-veto sentinel (preserves scope invariant)",
                type(exc).__name__,
                exc,
            )
            # Sentinel: fired=False (safe default), scope="house_inference"
            # (operator-visible invariant preserved).
            self._last_veto_decision = VetoDecision(
                False, 0.0, "fallback: helper raised", "house_inference"
            )

        # B-2026-08-03-2: Arriving re-arm cooldown gate. After an ARRIVING
        # attempt collapsed back to AWAY, suppress a fresh AWAY→ARRIVING
        # unless truly new evidence (interior tier1, camera/egress, or a
        # tracked person no longer away) is present. Outdoor-only zone
        # motion (patio, front porch) is precisely the flapping stimulus
        # the cooldown exists to damp — it does NOT bypass. Kill-switch:
        # ARRIVING_REARM_COOLDOWN_S == 0 → disabled.
        if (
            ARRIVING_REARM_COOLDOWN_S > 0
            and new_state == HouseState.ARRIVING
            and current_state == HouseState.AWAY
            and self._arriving_rearm_until > 0.0
        ):
            import time as _time_mod
            _now_mono = _time_mod.monotonic()
            if _now_mono < self._arriving_rearm_until:
                bypass = (
                    bool(any_indoor_zone_occupied)
                    or self._census_count > 0
                    or (tracked_count > 0 and not all_tracked_persons_away)
                )
                if bypass:
                    self._arriving_rearm_bypassed += 1
                    self._arriving_rearm_until = 0.0
                    _LOGGER.info(
                        "Arriving re-arm cooldown bypassed by new evidence "
                        "(indoor=%s census=%d tracked_away=%s trigger=%s)",
                        bool(any_indoor_zone_occupied),
                        self._census_count,
                        all_tracked_persons_away,
                        trigger,
                    )
                else:
                    self._arriving_rearm_suppressed += 1
                    _LOGGER.info(
                        "Arriving re-arm cooldown suppressing AWAY→ARRIVING "
                        "(outdoor-only evidence; remaining=%ds trigger=%s)",
                        int(self._arriving_rearm_until - _now_mono),
                        trigger,
                    )
                    new_state = None
            else:
                # Cooldown expired — clear latch and let the attempt proceed.
                self._arriving_rearm_until = 0.0

        if new_state is not None:
            accepted = manager.house_state_machine.transition(
                new_state, trigger=trigger
            )
            if accepted:
                # Clear any pending retry — transition succeeded
                if self._retry_unsub is not None:
                    self._retry_unsub()
                    self._retry_unsub = None

                # B-2026-08-03-2: on ARRIVING→AWAY collapse, arm the cooldown
                # so outdoor-only motion cannot immediately re-trigger ARRIVING.
                if (
                    ARRIVING_REARM_COOLDOWN_S > 0
                    and current_state == HouseState.ARRIVING
                    and new_state == HouseState.AWAY
                ):
                    import time as _time_mod
                    self._arriving_rearm_until = (
                        _time_mod.monotonic() + ARRIVING_REARM_COOLDOWN_S
                    )
                    _LOGGER.info(
                        "Arriving re-arm cooldown armed (%ds) after "
                        "ARRIVING→AWAY collapse (trigger=%s)",
                        ARRIVING_REARM_COOLDOWN_S,
                        trigger,
                    )

                # v4.6.2.2: If we just transitioned INTO guest mode, clear the
                # arm state (gate fired successfully — no need to keep the timer).
                if new_state == HouseState.GUEST:
                    self._disarm_guest_gate()
                # If we just transitioned OUT of guest mode (exit path),
                # also clear any residual arm state.
                elif current_state == HouseState.GUEST:
                    self._disarm_guest_gate()

                await self._count_transition()

                # Propagate sleep state to zones
                if new_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(True)
                elif current_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(False)

                # Log decision (house-scoped)
                await self._log_state_transition(
                    current_state, new_state, trigger
                )

                # D3: Log house state change to database
                db = self.hass.data.get(DOMAIN, {}).get("database")
                if db is not None:
                    self.hass.async_create_task(
                        db.log_house_state_change(
                            state=new_state.value,
                            confidence=self._inference_engine.confidence,
                            trigger=trigger,
                            previous_state=current_state.value,
                        )
                    )

                # Publish signal (async_dispatcher_send imported at module top —
                # a function-local import here re-scopes the name as a local for
                # all of _run_inference, leaving later uses unbound on ticks that
                # skip this branch → UnboundLocalError. v4.7.20.1 regression fix.)
                # v3.21.1 D1: Observation mode — inference runs but signal
                # dispatch is suppressed so downstream coordinators don't react.
                # Cold-boot away-actuation storm mitigation (Gate 1): same
                # short-circuit pattern, different trigger. Either gate
                # suppresses; both gates can be active at once on a cold-boot
                # observation-mode run — the boot-settle log wins for clarity.
                if not self._boot_settle_done:
                    self._boot_settle_presence_suppressed += 1
                    _LOGGER.info(
                        "Boot-settle: suppressed presence away-dispatch "
                        "SIGNAL_HOUSE_STATE_CHANGED %s -> %s (trigger=%s, "
                        "suppressed_count=%d, observation_mode=%s)",
                        current_state.value,
                        new_state.value,
                        trigger,
                        self._boot_settle_presence_suppressed,
                        self.observation_mode,
                    )
                elif self.observation_mode:
                    _LOGGER.info(
                        "[observation mode] Presence would dispatch "
                        "SIGNAL_HOUSE_STATE_CHANGED %s → %s (trigger=%s) — suppressed",
                        current_state.value,
                        new_state.value,
                        trigger,
                    )
                else:
                    async_dispatcher_send(
                        self.hass,
                        SIGNAL_HOUSE_STATE_CHANGED,
                        {
                            "old_state": current_state.value,
                            "new_state": new_state.value,
                            "trigger": trigger,
                            "confidence": self._inference_engine.confidence,
                        },
                    )

                    # Activity log: house state transition
                    activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
                    if activity_logger:
                        self.hass.async_create_task(
                            activity_logger.log(
                                coordinator="presence",
                                action="house_state_change",
                                description=f"House state {current_state.value} -> {new_state.value} (trigger={trigger})",
                                importance="notable",
                                details={
                                    "old_state": current_state.value,
                                    "new_state": new_state.value,
                                    "trigger": trigger,
                                    "confidence": self._inference_engine.confidence,
                                },
                            )
                        )

                # House-level anomaly detection
                # v4.6.3 D3/D11/D12: Use canonical AnomalyEvent + ActivityLogger.
                if self.anomaly_detector is not None:
                    anomaly = self.anomaly_detector.record_observation(
                        "census_count",
                        DIAGNOSTICS_SCOPE_HOUSE,
                        float(self._census_count),
                    )
                    if anomaly:
                        # v4.6.3.3: SUPPRESS anomaly_log persistence + ActivityLogger emit for
                        # census_count. Same degenerate-shape problem as v4.6.3.1's zone_occupancy
                        # suppression: census_count is a low-cardinality integer (0-N people)
                        # that is mostly 0 during sleep/away or 1-4 when occupied. With
                        # minimum_samples=24 and Z_SCORE_ADVISORY=2.0, any "person appears"
                        # tick during a mostly-empty period produces a high z-score on every
                        # observation, so v4.6.3 D3's persistence path emitted 1825 anomalies
                        # in 24h after v4.6.3.1 suppressed zone_occupancy.
                        # In-memory tracking via record_observation() above is preserved, so the
                        # per-coordinator anomaly sensor (sensor.ura_presence_coordinator_presence_anomaly)
                        # still counts these. They just don't pollute anomaly_log.
                        # Proper fix (deferred to a future cycle): drop census_count from
                        # PRESENCE_METRICS entirely; use Bayesian time-bin distributions
                        # for census patterns (mirrors the v4.6.2 routine-awareness shape).
                        _LOGGER.debug(
                            "Presence census_count in-memory anomaly only (persistence suppressed): "
                            "severity=%s z=%.2f count=%d",
                            anomaly.severity.value, anomaly.z_score, self._census_count,
                        )

                # Outcome measurement: record for accuracy tracking
                self._record_outcome(current_state, new_state, trigger)

            else:
                # Transition blocked (likely hysteresis) — schedule retry
                remaining = manager.house_state_machine.remaining_hysteresis()
                if remaining > 0 and trigger != "deferred_retry":
                    self._schedule_deferred_retry(remaining + 1)

        # v4.7.15 D5: signal_consensus calculation.
        # v4.7.15 fix-up B2-HIGH: Relocated past the transition-record block so
        # readers (HVAC defer gate, compliance gate) never observe new-consensus
        # paired with stale `_last_transition_time`. The read race used to invert
        # the D6 HVAC gate at exactly the tick the new state landed.
        # Computed every cycle (even when new_state is None) — consensus
        # tracks INPUT agreement, not output transitions.
        # 1.0 = inputs in perfect agreement, 0.0 = severely degraded.
        # All four deltas per INVESTIGATION §6.5 line 257-268.
        # Provenance-split cycle (D2): rename
        # `mmwave_occupied_count` -> `tier1_occupied_count`. The old name
        # was always a misnomer — counts ALL Tier-1 truth, not mmwave-
        # only. Old key is retained in the published dict as a
        # deprecation shim for one cycle (see D3/D5 below).
        camera_occupied_count = 0
        tier1_occupied_count = 0
        # Per-zone per-kind breakdown for diagnostic surface (D5).
        # Shape: {zone_name: {"motion": int, "mmwave": int, "occupancy": int}}.
        tier1_provenance_breakdown: Dict[str, Dict[str, int]] = {}
        try:
            for zname, t in self._zone_trackers.items():
                # Camera tier: any True in _camera_occupied dict.
                if any(getattr(t, "_camera_occupied", {}).values()):
                    camera_occupied_count += 1
                # Tier-1 (mmWave/PIR/occupancy): any True in the derived
                # _room_occupied view. Identical reading shape to the
                # pre-split version — the property returns the same dict.
                if any(getattr(t, "_room_occupied", {}).values()):
                    tier1_occupied_count += 1
                # Per-kind counts (D2/D5 diagnostic): count rooms where
                # each kind slot is True. A-LOW-2 review fix-up: include
                # the legacy "tier1" sentinel slot in the breakdown so
                # rooms written via the back-compat `kind=None` path
                # (used by test_v47181_sleep_wake_deadlock.py and any
                # future external caller that forgets `kind=`) remain
                # visible on the diagnostic surface. Pre-fix, those
                # rooms still rolled into `tier1_occupied_count` via the
                # derived-property OR but contributed ZERO to any
                # per-kind bucket, silently disappearing from the UI.
                bucket: Dict[str, int] = {k: 0 for k in TIER1_KINDS}
                bucket["tier1"] = 0
                for _room, kinds in getattr(t, "_room_provenance", {}).items():
                    for k in TIER1_KINDS:
                        if kinds.get(k, False):
                            bucket[k] += 1
                    if kinds.get("tier1", False):
                        bucket["tier1"] += 1
                tier1_provenance_breakdown[zname] = bucket
        except Exception:  # noqa: BLE001 — defensive
            camera_occupied_count = 0
            tier1_occupied_count = 0
            tier1_provenance_breakdown = {}

        # D3: fan-on interference-conditional reliability diagnostic
        # (OBSERVATION ONLY — no actuation, no mode change). See the
        # `_compute_fan_interference_rooms` docstring for the full
        # primitive definition + cross-references.
        fan_interference_rooms = self._compute_fan_interference_rooms()
        fan_interference_active = bool(fan_interference_rooms)

        # Fan-noise mitigation D1: silent Layer-1 gate. Applies a hold
        # via tracker._fan_interference_hold_until to every fan-suspect
        # room whose BLE corroboration ladder says not-corroborated.
        # The hold EXTENDS the derived `_room_occupied` view past the
        # natural drop point — it CANNOT shorten a genuinely-occupied
        # room (truth-preserving invariant; see property docstring +
        # AUDIT_fan_interference_gate_ripple.md). Returns the sorted
        # list of currently-held rooms + the ladder verdict per suspect.
        fan_interference_gated_rooms, fan_interference_ladder = (
            self._apply_fan_interference_gate(
                fan_interference_rooms,
                self._fan_interference_hold_s,
            )
        )
        # Edge-detect newly-held rooms so SIGNAL_FAN_INTERFERENCE_GATE_FIRED
        # only dispatches when at least one room moved from "no hold" to
        # "hold active" this tick. Avoids tick-rate spam during a long
        # interference window.
        gated_now = set(fan_interference_gated_rooms)
        newly_gated = gated_now - self._fan_interference_gated_prev
        self._fan_interference_gated_prev = gated_now
        if newly_gated:
            # B-H2 fix-up: imports for async_dispatcher_send +
            # SIGNAL_FAN_INTERFERENCE_GATE_FIRED hoisted to module top so
            # import failures surface at module load, not silently inside
            # a per-tick `except`. Dispatcher-side exceptions are still
            # tolerated but now logged at WARNING so they're visible at
            # default log level (Bug Class #4 — broad-except tightening).
            try:
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_FAN_INTERFERENCE_GATE_FIRED,
                    {
                        "rooms": sorted(newly_gated),
                        "ladder": {
                            r: fan_interference_ladder.get(r, "none")
                            for r in newly_gated
                        },
                    },
                )
                _LOGGER.info(
                    "Fan-noise D1: gate fired — newly-held rooms=%s "
                    "ladder=%s hold_s=%d",
                    sorted(newly_gated),
                    {r: fan_interference_ladder.get(r, "none") for r in newly_gated},
                    self._fan_interference_hold_s,
                )
            except Exception:  # noqa: BLE001 — dispatch is best-effort
                _LOGGER.warning(
                    "Fan-noise D1: SIGNAL_FAN_INTERFERENCE_GATE_FIRED "
                    "dispatch failed (non-fatal)",
                    exc_info=True,
                )

        # Fan-noise Mode-2 mitigation: room-tier fan-recheck per-room tick.
        # Runs after the zone-tier gate so any visible state from this tick
        # is settled. The state machine is opt-in (master OFF by default).
        if self._fan_recheck_manager is not None:
            try:
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                        continue
                    room_coord = self.hass.data.get(DOMAIN, {}).get(
                        entry.entry_id,
                    )
                    if room_coord is None or not hasattr(room_coord, "entry"):
                        continue
                    self._fan_recheck_manager.on_room_tick(room_coord)
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "FanRecheck: per-tick fan-out failed (non-fatal)",
                    exc_info=True,
                )

        # Back-compat alias for renamed local — the old name still
        # appears in some downstream string formatters but the value is
        # the same.
        mmwave_occupied_count = tier1_occupied_count

        any_stale_or_lost_tracker = False
        try:
            person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
            if person_coord and getattr(person_coord, "data", None):
                any_stale_or_lost_tracker = any(
                    (info.get("location") or "") == "unknown"
                    for info in (person_coord.data or {}).values()
                )
        except Exception:  # noqa: BLE001
            any_stale_or_lost_tracker = False

        consensus = 1.0
        # Disagreement 1: phones say away, zones say occupied (the v4.7.14 shape).
        if all_tracked_persons_away and any_zone_occupied:
            consensus -= 0.4
        # Disagreement 2: at least one tracker is STALE/LOST (not confirmed away).
        if any_stale_or_lost_tracker and not all_tracked_persons_away:
            consensus -= 0.2
        # Disagreement 3: cameras firing without mmWave/PIR backup.
        if camera_occupied_count > 0 and mmwave_occupied_count == 0:
            consensus -= 0.15
        # Disagreement 4: engine itself is uncertain about its chosen state.
        if self._inference_engine.confidence < 0.85:
            consensus -= 0.1
        self._signal_consensus = max(0.0, consensus)
        self._signal_consensus_inputs = {
            "all_tracked_persons_away": all_tracked_persons_away,
            "any_zone_occupied": any_zone_occupied,
            "any_stale_or_lost_tracker": any_stale_or_lost_tracker,
            "camera_occupied_count": camera_occupied_count,
            # Provenance-split cycle (D2 rename + D5 deprecation shim):
            # `tier1_occupied_count` is the new canonical key; the old
            # name `mmwave_occupied_count` is preserved as an alias for
            # one cycle so any sensor/dashboard reading the old key
            # keeps working. Both keys carry the same value within the
            # SAME tick (asserted by
            # quality/tests/test_presence_provenance_split.py).
            "tier1_occupied_count": tier1_occupied_count,
            "mmwave_occupied_count": mmwave_occupied_count,
            # D2/D5: per-zone per-kind breakdown for the diagnostic UI.
            "tier1_provenance_breakdown": tier1_provenance_breakdown,
            # D3: fan-interference observation-only diagnostic.
            "fan_interference_active": fan_interference_active,
            "fan_interference_rooms": fan_interference_rooms,
            # Fan-noise mitigation D1 (Layer-1 silent gate):
            # `fan_interference_gated_rooms` is the list of rooms with
            # an ACTIVE hold this tick (distinct from
            # `fan_interference_rooms`, which is the observation-only
            # suspect list). `fan_interference_ladder` maps each
            # suspect to the strongest non-fired BLE layer label
            # (L1 / L2 / L3 / none). Hold-seconds is exposed for the
            # diagnostic surface so operators can correlate the slider
            # with observed gate behavior.
            "fan_interference_gated_rooms": fan_interference_gated_rooms,
            "fan_interference_ladder": fan_interference_ladder,
            "fan_interference_hold_s": self._fan_interference_hold_s,
            "state_confidence": round(self._inference_engine.confidence, 2),
        }

        # Sustained-low tracker (D6 compliance gate input).
        if self._signal_consensus < 0.6:
            if self._consensus_low_since is None:
                self._consensus_low_since = _now_utc
        else:
            self._consensus_low_since = None

        # D4: Log zone mode changes to database.
        # B-H3 fix-up: tag rooms whose occupancy is currently hold-
        # extended by the Layer-1 fan-interference gate so post-hoc DB
        # forensics can distinguish "mmwave actually fired" from
        # "hold-extension kept the room occupied past mmwave drop."
        # Without this, the row's `rooms` list silently conflates the
        # two and operators querying "why was Bedroom 2 occupied at
        # 3am?" cannot tell the gate apart from genuine occupancy.
        # Cheap implementation: prefix the room name with `"(hold) "`
        # in the persisted list — no new DAO/table (that's deferred
        # D2). The room is hold-extended when provenance OR is False
        # but the derived view is True (which is exactly the gate's
        # extension semantic; see _room_occupied property docstring).
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is not None:
            for zone_name, tracker in self._zone_trackers.items():
                old_mode = zone_modes_before.get(zone_name)
                new_mode = tracker.mode
                if old_mode is not None and old_mode != new_mode:
                    raw_occupied = tracker._room_occupied
                    prov = getattr(tracker, "_room_provenance", {}) or {}
                    tagged_rooms: List[str] = []
                    for rn, occ in raw_occupied.items():
                        if not occ:
                            continue
                        room_prov = prov.get(rn, {}) or {}
                        prov_true = any(bool(v) for v in room_prov.values())
                        if not prov_true:
                            # Hold-extended — surface in the persisted
                            # row so forensics can join on the prefix.
                            tagged_rooms.append(f"(hold) {rn}")
                        else:
                            tagged_rooms.append(rn)
                    self.hass.async_create_task(
                        db.log_zone_event(
                            zone=zone_name,
                            event_type=new_mode,
                            room_count=len(tagged_rooms),
                            rooms=tagged_rooms if tagged_rooms else None,
                        )
                    )

        # Zone-scoped anomaly detection (runs every inference, not just on transition)
        await self._check_zone_anomalies()

        # v4.5.20: fire per-cycle refresh signal so PresenceAnomalySensor
        # (and any other sensor subscribed) re-renders attrs without
        # waiting for HA to naturally re-query. Mirrors HVAC/Safety/
        # Security pattern. Function-local import keeps Presence's
        # import surface minimal.
        try:
            async_dispatcher_send(self.hass, SIGNAL_PRESENCE_ENTITIES_UPDATE)
        except Exception:
            _LOGGER.warning(
                "Presence: failed to dispatch SIGNAL_PRESENCE_ENTITIES_UPDATE",
                exc_info=True,
            )

    async def _check_zone_anomalies(self) -> None:
        """Record zone-level anomaly observations.

        Checks each zone's occupied status and records it as an observation
        for zone-scoped anomaly detection. Detects unusual occupancy patterns
        like "zone occupied at unusual time."
        """
        if self.anomaly_detector is None:
            return

        hour = dt_util.now().hour
        for zone_name, tracker in self._zone_trackers.items():
            if not tracker.has_sensors:
                continue
            scope = f"zone:{zone_name}"
            # Record occupancy as 1.0/0.0 observation for time-of-day baseline
            occupied_value = 1.0 if tracker.mode == ZonePresenceMode.OCCUPIED else 0.0
            anomaly = self.anomaly_detector.record_observation(
                "zone_occupied_count",
                scope,
                occupied_value,
            )
            if anomaly:
                # v4.6.3.1: SUPPRESS anomaly_log persistence + ActivityLogger emit for
                # zone_occupied_count. Binary 0/1 occupancy is a degenerate input to
                # z-score detection: a rarely-occupied zone develops mean ≈ occupancy_ratio
                # and std ≈ sqrt(p*(1-p)), so every "occupied=1.0" observation produces
                # z >= 4 → CRITICAL. v4.6.3 D3 wired this through save_anomaly_event,
                # which produced 2117 emits in 3h post-deploy.
                # In-memory tracking via record_observation() above is preserved, so the
                # per-coordinator anomaly sensor (sensor.ura_presence_coordinator_presence_anomaly)
                # still counts these. They just don't pollute anomaly_log.
                # Proper fix (deferred to a future cycle): drop zone_occupied_count from
                # PRESENCE_METRICS entirely; use Bayesian time-bin distributions for
                # occupancy patterns instead (v4.6.2 routine-awareness already uses this
                # shape for per-person routines).
                _LOGGER.debug(
                    "Zone %s in-memory anomaly only (zone_occupancy persistence suppressed): "
                    "severity=%s z=%.2f",
                    zone_name, anomaly.severity.value, anomaly.z_score,
                )

    async def _log_zone_mode_change(
        self,
        zone_name: str,
        old_mode: str,
        new_mode: str,
        trigger: str,
    ) -> None:
        """Log a zone mode change as a decision (zone-scoped)."""
        if self.decision_logger is None:
            return

        decision = DecisionLog(
            timestamp=dt_util.utcnow(),
            coordinator_id=self.coordinator_id,
            decision_type="zone_mode_change",
            scope=f"zone:{zone_name}",
            situation_classified=new_mode,
            urgency=30,
            confidence=0.9,
            context={
                "zone_name": zone_name,
                "old_mode": old_mode,
                "new_mode": new_mode,
                "trigger": trigger,
            },
        )
        await self.decision_logger.log_decision(decision)

    async def _count_transition(self) -> None:
        """Count daily transitions and record observation for anomaly detection.

        v4.6.4 P1: `transition_count_daily` was declared in PRESENCE_METRICS since
        v3.6.0-c1 but never had a `record_observation` call site. The metric is
        well-shaped — monotone within day (0,1,2…), resets at midnight — so
        z-score persistence is safe (no degenerate-shape risk like census_count /
        zone_occupied_count which were suppressed in v4.6.3.3 / v4.6.3.1).
        """
        today = dt_util.now().date().isoformat()
        if today != self._transition_reset_date:
            self._transitions_today = 0
            self._transition_reset_date = today
            # v3.19.0: Reset face arrival counters at midnight
            for tracker in self._zone_trackers.values():
                tracker._face_arrivals_today = 0
            self._face_arrival_cooldown.clear()
        self._transitions_today += 1

        # v4.6.4 P1: record and emit if anomalously high transition count
        if self.anomaly_detector is None:
            return
        anomaly = self.anomaly_detector.record_observation(
            "transition_count_daily",
            DIAGNOSTICS_SCOPE_HOUSE,
            float(self._transitions_today),
        )
        if not anomaly:
            return
        from .anomaly_event import (
            AnomalyEvent,
            AnomalySeverity as _NewSev,
            AnomalyType,
            build_context_json,
            map_diag_severity,
        )
        _ctx = build_context_json(
            source_signal="SIGNAL_HOUSE_STATE_CHANGED",
            extra={
                "transitions_today": self._transitions_today,
            },
        )
        _event = AnomalyEvent(
            coordinator="presence",
            type="presence.transition_count_daily",
            # v4.6.6 D1: 1:1 mapping preserves all 4 z-score bands.
            severity=map_diag_severity(anomaly.severity),
            anomaly_type=AnomalyType.POINT_IN_TIME,
            detected_at=anomaly.timestamp.isoformat(),
            payload=_ctx,
            observed_value=anomaly.observed_value,
            expected_mean=anomaly.expected_mean,
            expected_std=anomaly.expected_std,
            z_score=round(anomaly.z_score, 3),
            sample_size=anomaly.sample_size,
        )
        await self.anomaly_detector.store_event(_event)
        _LOGGER.info(
            "Presence transition_count_daily anomaly: z=%.2f count=%d severity=%s",
            anomaly.z_score, self._transitions_today, anomaly.severity.value,
        )
        _activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
        if _activity_logger:
            await _activity_logger.log(
                coordinator="presence",
                action="anomaly",
                description=(
                    f"Presence transition_count_daily anomaly z={anomaly.z_score:.2f} "
                    f"count={self._transitions_today}"
                ),
                importance="notable",
                details={
                    "type": "presence.transition_count_daily",
                    "z_score": round(anomaly.z_score, 3),
                    "transitions_today": self._transitions_today,
                },
            )

    # ------------------------------------------------------------------
    # Outcome measurement
    # ------------------------------------------------------------------

    def _record_outcome(
        self,
        old_state: HouseState,
        new_state: HouseState,
        trigger: str,
    ) -> None:
        """Record a state transition outcome for accuracy tracking.

        Tracks detection accuracy by measuring how often transitions are
        later contradicted (e.g., went to AWAY but immediately came back).
        """
        now = dt_util.utcnow()

        # Track if previous transition was contradicted
        if hasattr(self, '_last_transition_time') and self._last_transition_state is not None:
            elapsed = (now - self._last_transition_time).total_seconds()
            if elapsed < 120:  # Contradiction within 2 minutes
                self._outcome_false_positives += 1
                _LOGGER.debug(
                    "Potential false positive: %s lasted only %.0fs before %s",
                    self._last_transition_state.value, elapsed, new_state.value,
                )
            else:
                self._outcome_true_positives += 1

        self._last_transition_state = new_state
        self._last_transition_time = now

    @property
    def detection_accuracy(self) -> float:
        """Return detection accuracy as ratio of true positives to total."""
        total = self._outcome_true_positives + self._outcome_false_positives
        if total == 0:
            return 1.0
        return self._outcome_true_positives / total

    @property
    def false_positive_rate(self) -> float:
        """Return false positive rate."""
        total = self._outcome_true_positives + self._outcome_false_positives
        if total == 0:
            return 0.0
        return self._outcome_false_positives / total

    # ------------------------------------------------------------------
    # Decision logging
    # ------------------------------------------------------------------

    async def _log_state_transition(
        self,
        old_state: HouseState,
        new_state: HouseState,
        trigger: str,
    ) -> None:
        """Log a state transition as a decision."""
        if self.decision_logger is None:
            return

        decision = DecisionLog(
            timestamp=dt_util.utcnow(),
            coordinator_id=self.coordinator_id,
            decision_type="state_transition",
            scope=DIAGNOSTICS_SCOPE_HOUSE,
            situation_classified=new_state.value,
            urgency=50,
            confidence=self._inference_engine.confidence,
            context={
                "old_state": old_state.value,
                "new_state": new_state.value,
                "trigger": trigger,
                "census_count": self._census_count,
                "zones": {
                    name: tracker.mode
                    for name, tracker in self._zone_trackers.items()
                },
            },
        )
        await self.decision_logger.log_decision(decision)

    async def evaluate(
        self,
        intents: list,
        context: dict,
    ) -> List[CoordinatorAction]:
        """Evaluate intents — Presence doesn't generate actions directly.

        Presence is informational: it publishes state, other coordinators
        react to it. But we still process intents if any are routed to us.
        """
        return []

    async def async_teardown(self) -> None:
        """Tear down the Presence Coordinator."""
        # Cancel deferred retry timer
        if self._retry_unsub is not None:
            self._retry_unsub()
            self._retry_unsub = None

        # v4.6.2.2: Cancel guest persistence recheck timer on teardown (Bug Class #19)
        self._disarm_guest_gate()

        # v4.7.2 D5: Cancel guest-room occupancy listeners (Bug Class #38)
        for unsub in self._guest_room_unsubs.values():
            try:
                unsub()
            except Exception:
                pass
        self._guest_room_unsubs.clear()
        self._guest_room_state.clear()

        # Fan-noise Mode-2: cancel per-room async_call_later timers in the
        # FanRecheckManager and persist final state. Leaked timers across
        # reload would otherwise fire callbacks against a discarded
        # PresenceCoordinator instance (Bug Class #38/#42). The manager's
        # shutdown is safe to call multiple times.
        if self._fan_recheck_manager is not None:
            try:
                await self._fan_recheck_manager.shutdown()
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "FanRecheckManager shutdown failed during teardown",
                    exc_info=True,
                )
            self._fan_recheck_manager = None

        # F3 fix-up (B-HIGH-1): cancel + gather any in-flight substrate
        # refresh tasks BEFORE we tear the substrate down. The
        # substrate's own ``_is_torn_down`` sentinel is set at the top of
        # its async_teardown, so any task that survives cancellation
        # short-circuits on its next resume — but cancel+gather is the
        # cleaner contract.
        if self._substrate_refresh_tasks:
            _pending = list(self._substrate_refresh_tasks)
            for _t in _pending:
                try:
                    _t.cancel()
                except Exception:  # noqa: BLE001 — defensive
                    pass
            try:
                await asyncio.gather(*_pending, return_exceptions=True)
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.debug(
                    "Substrate refresh task gather raised during teardown",
                    exc_info=True,
                )
            self._substrate_refresh_tasks.clear()

        # Occupancy substrate unification cycle: tear down substrate
        # listeners + local subscribers before _cancel_listeners runs so
        # the substrate's own state-change subscriptions are released
        # cleanly (Bug Class #38). The substrate's signal subscription
        # itself lives in self._unsub_listeners and is unsubscribed by
        # _cancel_listeners below.
        if self._substrate is not None:
            try:
                await self._substrate.async_teardown()
            except Exception:  # noqa: BLE001 — defensive teardown
                _LOGGER.debug(
                    "OccupancySubstrate teardown raised (non-fatal)",
                    exc_info=True,
                )
            self._substrate = None
            # v5.10.0 fix-up FIX-2: symmetric hass.data cleanup for the
            # occupancy_substrate key registered at setup.
            try:
                _dom = self.hass.data.get(DOMAIN, {})
                if _dom.get("occupancy_substrate") is not None:
                    _dom.pop("occupancy_substrate", None)
            except Exception:  # noqa: BLE001
                pass

        # B-M1 / C-C7 fix-up: reset the optimizer-intent unsub handle so
        # re-setup after teardown re-subscribes cleanly. The actual
        # dispatcher unsub fires via ``_cancel_listeners`` (handle is
        # already on ``self._unsub_listeners``).
        self._optimizer_intent_unsub = None

        # Routine-Awareness Next-State Forecaster: cancel the periodic
        # refresh timer + signal subscription. Cancellation is idempotent
        # (the forecaster guards its own unsubs). Bug Class #19 + #50.
        if self._routine_forecaster is not None:
            try:
                await self._routine_forecaster.async_shutdown()
            except Exception:  # noqa: BLE001 — defensive teardown
                _LOGGER.debug(
                    "RoutineForecaster shutdown raised (non-fatal)",
                    exc_info=True,
                )
            self._routine_forecaster = None

        self._cancel_listeners()

        # Save anomaly baselines
        if self.anomaly_detector is not None:
            await self.anomaly_detector.save_baselines()

        _LOGGER.info("Presence Coordinator torn down")

    # ------------------------------------------------------------------
    # Override controls (backing select entities + services)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # OC Phase 5 Pillar A — sibling-coordinator handshake
    # ------------------------------------------------------------------

    @callback
    def _on_optimizer_intent(self, intent: dict) -> None:
        """Dispatcher callback for SIGNAL_OPTIMIZER_INTENT.

        Evaluates ``honor_optimizer_intent`` and fires
        ``SIGNAL_OPTIMIZER_INTENT_VETO`` when this coordinator refuses.
        Defensive against malformed payloads so the broker can never
        crash a sibling.
        """
        try:
            if not isinstance(intent, dict):
                return
            # B-H1 fix-up: L1 inertness — see Energy._on_optimizer_intent
            # for the full rationale.
            eff = intent.get("effective_level")
            if eff in ("advisory", "shadow"):
                _LOGGER.debug(
                    "Presence: skipping intent honor at L1 "
                    "effective_level=%s (action_id=%s target=%s)",
                    eff,
                    intent.get("action_id"),
                    intent.get("target_entity"),
                )
                return
            if self.honor_optimizer_intent(intent):
                return
            action_id = intent.get("action_id")
            if not action_id:
                return
            async_dispatcher_send(
                self.hass,
                SIGNAL_OPTIMIZER_INTENT_VETO,
                {
                    "action_id": action_id,
                    "vetoed_by": "presence",
                    "reason": self._last_veto_reason or "presence_policy",
                },
            )
            _LOGGER.info(
                "Optimizer intent vetoed by Presence (action_id=%s "
                "reason=%s target=%s)",
                action_id,
                self._last_veto_reason,
                intent.get("target_entity"),
            )
        except Exception:  # noqa: BLE001 — never crash sibling on broker intent
            _LOGGER.debug(
                "Presence._on_optimizer_intent raised", exc_info=True,
            )

    def honor_optimizer_intent(self, intent: dict) -> bool:
        """Return True to ACK (allow), False to VETO an Optimizer intent.

        Default vetoes (Pillar A safe-defaults from the plan):
            * ``self.observation_mode`` is True — veto everything.
            * The intent targets a curated presence-input sensor
              (``CONF_MOTION_SENSORS`` / ``CONF_MMWAVE_SENSORS`` /
              ``CONF_OCCUPANCY_SENSORS`` on any ROOM entry). The
              optimizer must never spoof presence inputs.

        Read-only — never mutates state, never raises.
        """
        self._last_veto_reason = None

        try:
            target = (intent.get("target_entity") or "").strip()
        except Exception:  # noqa: BLE001
            return True
        if not target:
            return True

        if self.observation_mode:
            self._last_veto_reason = "observation_mode"
            return False

        try:
            presence_inputs = self._collect_presence_input_entities()
        except Exception:  # noqa: BLE001
            presence_inputs = set()
        if target in presence_inputs:
            self._last_veto_reason = "presence_input_sensor"
            return False

        return True

    def _collect_presence_input_entities(self) -> set[str]:
        """Build the union of curated motion/mmwave/occupancy entities
        across every configured ROOM entry. Resolved live so adding a
        new room in the options flow takes effect without a coordinator
        restart.
        """
        out: set[str] = set()
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                merged = {**(entry.data or {}), **(entry.options or {})}
                if merged.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                for key in (
                    CONF_MOTION_SENSORS,
                    CONF_MMWAVE_SENSORS,
                    CONF_OCCUPANCY_SENSORS,
                ):
                    vals = merged.get(key) or []
                    if isinstance(vals, (list, tuple, set)):
                        out.update(str(v) for v in vals if v)
        except Exception:  # noqa: BLE001
            return out
        return out

    def set_house_state_override(self, state_value: str) -> None:
        """Set house state override from select entity or service call.

        Called by select entity when user changes the dropdown,
        or by ura.set_house_state service.
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        if state_value == "auto":
            manager.house_state_machine.clear_override()
            # Clear zone sleep overrides too
            for tracker in self._zone_trackers.values():
                if tracker._override == ZonePresenceMode.SLEEP:
                    tracker.clear_override()
        else:
            try:
                house_state = HouseState(state_value)
                manager.house_state_machine.set_override(house_state)

                # Propagate AWAY to all zones
                if house_state == HouseState.AWAY:
                    for tracker in self._zone_trackers.values():
                        tracker.set_override(ZonePresenceMode.AWAY)
                elif house_state == HouseState.SLEEP:
                    for tracker in self._zone_trackers.values():
                        tracker.set_sleep(True)
            except ValueError:
                _LOGGER.warning("Invalid house state override: %s", state_value)

    def set_fan_interference_hold_s(self, value: int) -> None:
        """Update the Layer-1 fan-interference hold duration (seconds).

        Fan-noise mitigation D1: called by ``FanInterferenceHoldNumber``
        when the operator changes the slider. Range is enforced at the
        Number entity (60-1800).

        H-A3 fix-up: existing per-room hold expiries are RE-CLAMPED to
        ``min(existing_expiry, now + new_seconds)`` on every change so
        a slider drop (e.g. 1800 -> 60) takes effect on currently-
        active holds immediately. The truth-preserving invariant is
        preserved — we never EXTEND an existing expiry past what was
        already promised, only shorten it. A slider raise leaves
        existing expiries alone; only the next suspect-tick refresh
        picks up the longer duration (which is correct — we should
        not silently extend past the original promise).
        """
        try:
            clamped = max(60, min(1800, int(value)))
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Fan-noise D1: ignoring non-integer hold-seconds value %r "
                "(type=%s)",
                value, type(value).__name__,
            )
            return
        if clamped != self._fan_interference_hold_s:
            _LOGGER.info(
                "Fan-noise D1: hold duration updated %ds -> %ds",
                self._fan_interference_hold_s, clamped,
            )
            self._fan_interference_hold_s = clamped
            # H-A3 fix-up: re-clamp existing holds so the new value
            # affects already-active holds, not just future
            # suspect-tick refreshes.
            try:
                now = dt_util.utcnow()
                max_expiry = now + timedelta(seconds=clamped)
                for tracker in self._zone_trackers.values():
                    hold = getattr(tracker, "_fan_interference_hold_until", None)
                    if not hold:
                        continue
                    for room_name, expiry in list(hold.items()):
                        if expiry > max_expiry:
                            hold[room_name] = max_expiry
            except Exception:  # noqa: BLE001 — defensive
                _LOGGER.warning(
                    "Fan-noise D1: hold re-clamp after slider change failed "
                    "(non-fatal)",
                    exc_info=True,
                )

    def get_house_state_override(self) -> str:
        """Get current house state override value for select entity."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None or not manager.house_state_machine.is_overridden:
            return "auto"
        return manager.house_state_machine.state.value

    # ------------------------------------------------------------------
    # Geofence signal (v3.6.0-c1.1: wired to person.* state changes)
    # ------------------------------------------------------------------

    def handle_geofence_event(self, person_id: str, zone: str) -> None:
        """Handle geofence enter/leave event for a person.

        When a person's device tracker transitions to/from 'home',
        triggers inference for state re-evaluation.

        v3.6.0.11: Triggers from any state on arrival, not just AWAY.
        The inference engine determines the valid transition.
        """
        if zone == "home":
            # Person arriving — trigger inference from any state
            self.hass.async_create_task(self._run_inference("geofence_arrive"))
            _LOGGER.info("Geofence: %s arrived home", person_id)
        elif zone == "not_home":
            # Person left — trigger inference to check if house is now empty
            self.hass.async_create_task(self._run_inference("geofence_leave"))
            _LOGGER.debug("Geofence: %s left home", person_id)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Return full presence diagnostics."""
        summary = super().get_diagnostics_summary()
        summary["census_count"] = self._census_count
        summary["unidentified_count"] = self._unidentified_count
        summary["house_state"] = self.house_state
        summary["confidence"] = self.confidence
        summary["transitions_today"] = self._transitions_today
        summary["detection_accuracy"] = round(self.detection_accuracy, 3)
        summary["false_positive_rate"] = round(self.false_positive_rate, 3)
        summary["outcome_stats"] = {
            "true_positives": self._outcome_true_positives,
            "false_positives": self._outcome_false_positives,
        }
        summary["zones"] = {
            name: tracker.to_dict()
            for name, tracker in self._zone_trackers.items()
        }
        return summary
