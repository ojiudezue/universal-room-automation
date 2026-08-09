"""SENSOR-CAPABILITY-1 — capability derivation + role resolution tests.

Covers D1 (SensorCapability + derive_capability), D2 (resolve_role), and
D3 (_detect_duty_cycle_stuck migration) per
``docs/planning/PLANNING_sensor_capability_vs_role.md``.

Invariants under test:
  I1 — byte-identity under empty overrides
  I2 — roles are pure functions, never persisted
  I3 — capability kinds MUST NOT leak onto the legacy provenance channel
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstrap homeassistant mocks

from custom_components.universal_room_automation.const import (
    CAPABILITY_KIND_BED,
    CAPABILITY_KIND_CAMERA_PRESENCE,
    CAPABILITY_KIND_MMWAVE,
    CAPABILITY_KIND_MOTION,
    CAPABILITY_KIND_OCCUPANCY,
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    CONF_SENSOR_CAPABILITIES,
    TIER1_CAPABILITIES,
    TIER1_KINDS,
    TRUST_CLASS_STRONG_EVIDENCE,
    TRUST_CLASS_WEAK_WITNESS,
    TRUST_CLASS_WITNESS,
)
from custom_components.universal_room_automation.domain_coordinators.sensor_capability import (  # noqa: E501
    DEFAULT_FAILURE_MODE_BY_KIND,
    DEFAULT_TRUST_BY_KIND,
    SensorCapability,
    derive_capability,
    validate_capabilities_payload,
)
from custom_components.universal_room_automation.domain_coordinators.sensor_role import (  # noqa: E501
    RoleQuery,
    resolve_role,
)


# ----------------------------------------------------------------------
# D1 — derive_capability
# ----------------------------------------------------------------------


def _room(motion=(), mmwave=(), occupancy=(), overrides=None):
    room = {
        CONF_MOTION_SENSORS: list(motion),
        CONF_MMWAVE_SENSORS: list(mmwave),
        CONF_OCCUPANCY_SENSORS: list(occupancy),
    }
    if overrides:
        room[CONF_SENSOR_CAPABILITIES] = overrides
    return room


def test_capability_default_matches_conf_list_kind() -> None:
    """I1: derive_capability returns the CONF-list kind for every entity
    when no overrides are declared — for every kind slot."""
    room = _room(
        motion=["binary_sensor.pir_1"],
        mmwave=["binary_sensor.mm_1"],
        occupancy=["binary_sensor.occ_1"],
    )
    assert derive_capability(room, "binary_sensor.pir_1") == SensorCapability(
        kind="motion",
        trust_class=TRUST_CLASS_WITNESS,
        failure_mode="unknown",
        source="conf_list",
    )
    assert derive_capability(room, "binary_sensor.mm_1").kind == "mmwave"
    assert derive_capability(room, "binary_sensor.occ_1").kind == "occupancy"
    assert (
        derive_capability(room, "binary_sensor.occ_1").trust_class
        == TRUST_CLASS_WEAK_WITNESS
    )


def test_capability_unknown_entity_returns_none() -> None:
    room = _room(motion=["binary_sensor.pir_1"])
    assert derive_capability(room, "binary_sensor.ghost") is None
    assert derive_capability(room, "") is None


def test_capability_override_wins_over_conf_list() -> None:
    """Operator declaring a bed sensor (wired into occupancy) turns it
    from occupancy → bed / strong_evidence."""
    room = _room(
        occupancy=["binary_sensor.bed"],
        overrides={
            "binary_sensor.bed": {
                "kind": CAPABILITY_KIND_BED,
                "trust_class": TRUST_CLASS_STRONG_EVIDENCE,
            },
        },
    )
    cap = derive_capability(room, "binary_sensor.bed")
    assert cap is not None
    assert cap.kind == CAPABILITY_KIND_BED
    assert cap.trust_class == TRUST_CLASS_STRONG_EVIDENCE
    assert cap.source == "override"


def test_capability_override_defaults_trust_and_failure() -> None:
    """Kind-only override fills trust/failure from per-kind defaults."""
    room = _room(
        occupancy=["binary_sensor.bed"],
        overrides={"binary_sensor.bed": {"kind": CAPABILITY_KIND_BED}},
    )
    cap = derive_capability(room, "binary_sensor.bed")
    assert cap.trust_class == DEFAULT_TRUST_BY_KIND[CAPABILITY_KIND_BED]
    assert cap.failure_mode == DEFAULT_FAILURE_MODE_BY_KIND[CAPABILITY_KIND_BED]


def test_capability_malformed_override_falls_back_to_conf_list() -> None:
    """Malformed override (unknown kind) MUST NOT silently take effect."""
    room = _room(
        occupancy=["binary_sensor.bed"],
        overrides={"binary_sensor.bed": {"kind": "not_a_real_kind"}},
    )
    cap = derive_capability(room, "binary_sensor.bed")
    assert cap.kind == "occupancy"
    assert cap.source == "conf_list"


def test_capability_p15_multi_list_uses_precedence() -> None:
    """Entity in BOTH mmwave and occupancy lists → mmwave wins
    (matches occupancy_substrate._KIND_PRECEDENCE)."""
    room = _room(
        mmwave=["binary_sensor.dual"],
        occupancy=["binary_sensor.dual"],
    )
    assert derive_capability(room, "binary_sensor.dual").kind == "mmwave"


def test_tier1_capabilities_is_superset_of_tier1_kinds() -> None:
    """Capability vocabulary MUST contain every TIER1_KINDS value —
    ward against a schema drift that would break the byte-identity
    fallback (I1)."""
    for k in TIER1_KINDS:
        assert k in TIER1_CAPABILITIES


# ----------------------------------------------------------------------
# D2 — resolve_role: purity + query matrix
# ----------------------------------------------------------------------


def test_role_is_pure_no_hidden_state() -> None:
    """I2 — same inputs, N calls, N identical outputs; module carries
    no observable per-call state."""
    room = _room(mmwave=["binary_sensor.mm"])
    r0 = resolve_role(room, "binary_sensor.mm", RoleQuery.CANDIDATE_FOR_STUCK)
    for _ in range(50):
        assert resolve_role(
            room, "binary_sensor.mm", RoleQuery.CANDIDATE_FOR_STUCK,
        ) == r0


def test_role_query_matrix_conf_defaults() -> None:
    """Every default CONF-list membership × query cell."""
    room = _room(
        motion=["binary_sensor.pir"],
        mmwave=["binary_sensor.mm"],
        occupancy=["binary_sensor.occ"],
    )
    # PIR: corroborator YES, candidate NO
    assert resolve_role(
        room, "binary_sensor.pir", RoleQuery.CORROBORATOR_FOR_ROOM,
    )
    assert not resolve_role(
        room, "binary_sensor.pir", RoleQuery.CANDIDATE_FOR_STUCK,
    )
    # mmwave: candidate YES, corroborator NO
    assert resolve_role(
        room, "binary_sensor.mm", RoleQuery.CANDIDATE_FOR_STUCK,
    )
    assert not resolve_role(
        room, "binary_sensor.mm", RoleQuery.CORROBORATOR_FOR_ROOM,
    )
    # occupancy: candidate YES, corroborator NO
    assert resolve_role(
        room, "binary_sensor.occ", RoleQuery.CANDIDATE_FOR_STUCK,
    )
    assert not resolve_role(
        room, "binary_sensor.occ", RoleQuery.CORROBORATOR_FOR_ROOM,
    )


def test_role_bed_override_flips_candidate_to_corroborator() -> None:
    """Master-bedroom acceptance fixture (Finding 6 of the audit):
    the bed sensor operator-declared as bed/strong_evidence becomes
    a CORROBORATOR and stops being a CANDIDATE."""
    room = _room(
        occupancy=["binary_sensor.bed"],
        overrides={
            "binary_sensor.bed": {
                "kind": CAPABILITY_KIND_BED,
                "trust_class": TRUST_CLASS_STRONG_EVIDENCE,
            },
        },
    )
    assert resolve_role(
        room, "binary_sensor.bed", RoleQuery.CORROBORATOR_FOR_ROOM,
    )
    assert not resolve_role(
        room, "binary_sensor.bed", RoleQuery.CANDIDATE_FOR_STUCK,
    )


def test_role_strong_evidence_trust_demotes_from_candidate() -> None:
    """CANDIDATE_FOR_STUCK strong_evidence gate: an operator declaring
    an mmwave-wired entity with trust=strong_evidence (kind stays
    mmwave) is DEMOTED out of the candidate set and ELEVATED into the
    corroborator set. Load-bearing per plan §D2 acceptance."""
    room = _room(
        mmwave=["binary_sensor.mm_strong"],
        overrides={
            "binary_sensor.mm_strong": {
                "kind": CAPABILITY_KIND_MMWAVE,
                "trust_class": TRUST_CLASS_STRONG_EVIDENCE,
            },
        },
    )
    assert not resolve_role(
        room, "binary_sensor.mm_strong", RoleQuery.CANDIDATE_FOR_STUCK,
    )
    assert resolve_role(
        room, "binary_sensor.mm_strong", RoleQuery.CORROBORATOR_FOR_ROOM,
    )


def test_role_camera_presence_is_corroborator() -> None:
    """Study-A room_cameras — declared as camera_presence — corroborate
    even though today they live outside the three CONF lists.
    (Here we simulate by declaring an entity wired into occupancy as
    camera_presence.)"""
    room = _room(
        occupancy=["binary_sensor.cam"],
        overrides={
            "binary_sensor.cam": {"kind": CAPABILITY_KIND_CAMERA_PRESENCE},
        },
    )
    assert resolve_role(
        room, "binary_sensor.cam", RoleQuery.CORROBORATOR_FOR_ROOM,
    )
    assert not resolve_role(
        room, "binary_sensor.cam", RoleQuery.CANDIDATE_FOR_STUCK,
    )


def test_role_unknown_entity_false_for_every_query() -> None:
    room = _room(motion=["binary_sensor.pir"])
    for q in RoleQuery:
        assert not resolve_role(room, "binary_sensor.ghost", q)


# ----------------------------------------------------------------------
# validate_capabilities_payload — options-flow guardrail
# ----------------------------------------------------------------------


def test_validate_rejects_unknown_entity() -> None:
    room = _room(motion=["binary_sensor.pir"])
    errs = validate_capabilities_payload(
        room, {"binary_sensor.not_wired": {"kind": CAPABILITY_KIND_BED}},
    )
    assert any("not_wired" in e for e in errs)


def test_validate_rejects_unknown_kind() -> None:
    room = _room(occupancy=["binary_sensor.bed"])
    errs = validate_capabilities_payload(
        room, {"binary_sensor.bed": {"kind": "fabricated"}},
    )
    assert any("fabricated" in e for e in errs)


def test_validate_accepts_valid_payload() -> None:
    room = _room(occupancy=["binary_sensor.bed"])
    errs = validate_capabilities_payload(
        room, {"binary_sensor.bed": {"kind": CAPABILITY_KIND_BED}},
    )
    assert errs == []


# ----------------------------------------------------------------------
# D3 — _detect_duty_cycle_stuck migration
#
# Byte-identity + collision + bed-corroborator behavioural tests, driving
# the real production method on a minimally-mocked coordinator instance.
# ----------------------------------------------------------------------


class _FakeConfigEntries:
    def __init__(self, integration_entry):
        self._entries = [integration_entry]

    def async_entries(self, _domain):
        return self._entries


class _FakeState:
    def __init__(self, state):
        self.state = state


class _FakeStates:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, entity_id):
        s = self._m.get(entity_id)
        return _FakeState(s) if s is not None else None


def _make_coord(room_config, states, dutycycle_window_min=60):
    """Instantiate UniversalRoomCoordinator without running __init__.

    We only exercise ``_detect_duty_cycle_stuck``; wiring is minimal.
    """
    from custom_components.universal_room_automation.coordinator import (
        UniversalRoomCoordinator,
    )
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_INTEGRATION,
    )

    # UniversalRoomCoordinator inherits from DataUpdateCoordinator, which
    # is mocked (MagicMock) by the harness — __new__ therefore returns a
    # Mock. Bypass by binding _detect_duty_cycle_stuck to a plain object.
    class _StubCoord:
        pass
    coord = _StubCoord()
    coord._detect_duty_cycle_stuck = (
        UniversalRoomCoordinator._detect_duty_cycle_stuck.__get__(
            coord, _StubCoord,
        )
    )
    coord.hass = MagicMock()
    integration_entry = MagicMock()
    integration_entry.data = {
        CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION,
        "stuck_sensor_dutycycle_window_min": dutycycle_window_min,
        "stuck_sensor_dutycycle_pct": 0.9,
        "stuck_sensor_dutycycle_min_ticks": 3,
    }
    integration_entry.options = {}
    coord.hass.config_entries = _FakeConfigEntries(integration_entry)
    coord.hass.states = _FakeStates(states)
    coord.hass.data = {}
    # Room entry (source of room_config for capability lookups).
    room_entry = MagicMock()
    room_entry.data = {"room_name": "TestRoom"}
    room_entry.options = dict(room_config)
    coord.entry = room_entry
    # State bookkeeping the detector consults.
    coord._sensor_dutycycle_rings = {}
    coord._sensor_dutycycle_motion_transitions = {}
    coord._sensor_last_motion_state = {}
    # Bypass the boot-settle gate — it reads across coordinators; the
    # detector itself is what we're isolating.
    coord._d2_boot_settle_done = lambda: True

    # Bind the real _is_sensor_on helper (production code path — reads
    # hass.states via the fakes above).
    from custom_components.universal_room_automation.coordinator import (
        UniversalRoomCoordinator as _URC,
    )
    coord._is_sensor_on = _URC._is_sensor_on.__get__(coord, type(coord))
    return coord


def _run_detect(coord, motion, mmwave, occupancy):
    import datetime as _dt
    return coord._detect_duty_cycle_stuck(
        now=_dt.datetime.now(),
        motion_sensors=list(motion),
        mmwave_sensors=list(mmwave),
        occupancy_sensors=list(occupancy),
        room_name="TestRoom",
    )


def test_d2_no_capability_declared_byte_identical_no_stuck() -> None:
    """I1: with no overrides, all sensors OFF → no stuck verdicts."""
    room = _room(
        motion=["binary_sensor.pir"],
        mmwave=["binary_sensor.mm"],
        occupancy=["binary_sensor.occ"],
    )
    coord = _make_coord(
        room, states={
            "binary_sensor.pir": "off",
            "binary_sensor.mm": "off",
            "binary_sensor.occ": "off",
        },
    )
    for _ in range(5):
        assert _run_detect(
            coord,
            ["binary_sensor.pir"],
            ["binary_sensor.mm"],
            ["binary_sensor.occ"],
        ) == set()


def test_d2_no_capability_stuck_mmwave_flagged() -> None:
    """I1: with no overrides, a 100%-on mmwave with no PIR
    transitions → flagged (matches pre-migration behaviour)."""
    room = _room(
        motion=["binary_sensor.pir"],
        mmwave=["binary_sensor.mm"],
    )
    coord = _make_coord(
        room,
        states={"binary_sensor.pir": "off", "binary_sensor.mm": "on"},
    )
    stuck = set()
    for _ in range(5):
        stuck = _run_detect(
            coord, ["binary_sensor.pir"], ["binary_sensor.mm"], [],
        )
    assert "binary_sensor.mm" in stuck


def test_d2_bed_override_shields_bed_from_being_flagged() -> None:
    """Master-bedroom acceptance fixture: a bed sensor operator-
    declared as bed/strong_evidence lives in CONF_OCCUPANCY_SENSORS
    but is a CORROBORATOR, not a CANDIDATE — so a 100%-on bed does
    NOT get flagged as stuck."""
    room = _room(
        motion=["binary_sensor.pir"],
        occupancy=["binary_sensor.bed"],
        overrides={
            "binary_sensor.bed": {
                "kind": CAPABILITY_KIND_BED,
                "trust_class": TRUST_CLASS_STRONG_EVIDENCE,
            },
        },
    )
    coord = _make_coord(
        room,
        states={"binary_sensor.pir": "off", "binary_sensor.bed": "on"},
    )
    stuck = set()
    for _ in range(5):
        stuck = _run_detect(
            coord, ["binary_sensor.pir"], [], ["binary_sensor.bed"],
        )
    assert "binary_sensor.bed" not in stuck


def test_d2_p15_both_buckets_scored_exactly_once() -> None:
    """Riskiest-part test (plan §10): an entity present in BOTH
    mmwave_sensors AND occupancy_sensors under P15 defensive
    precedence MUST be scored EXACTLY ONCE.

    Verified via the per-tick ring: after N ticks, the ring must
    hold N samples for the dual-listed entity, not 2×N. The pre-
    migration list-concat semantics double-appended.
    """
    room = _room(
        motion=["binary_sensor.pir"],
        mmwave=["binary_sensor.dual"],
        occupancy=["binary_sensor.dual"],  # P15 defensive collision
    )
    coord = _make_coord(
        room,
        states={"binary_sensor.pir": "off", "binary_sensor.dual": "on"},
    )
    N = 3
    for _ in range(N):
        _run_detect(
            coord,
            ["binary_sensor.pir"],
            ["binary_sensor.dual"],
            ["binary_sensor.dual"],
        )
    ring = coord._sensor_dutycycle_rings.get("binary_sensor.dual")
    assert ring is not None
    assert len(ring) == N, (
        f"P15 collision: expected {N} samples, got {len(ring)} — "
        "candidate was double-scored"
    )


def test_d2_i3_ward_capability_kinds_absent_from_tier1_kinds() -> None:
    """I3 ward: extended capability kinds (bed, camera_presence, …)
    MUST NOT be members of TIER1_KINDS. If a future builder adds one
    here, the substrate dispatch channel + provenance audit would
    silently accept it — undoing I3."""
    assert "bed" not in TIER1_KINDS
    assert "camera_presence" not in TIER1_KINDS
    assert "ble_presence" not in TIER1_KINDS


def test_i3_audit_docstring_names_capability_layer() -> None:
    """I3 durable ward — the _audit_provenance_invariants docstring
    must explicitly forbid capability-kind widening (per plan §10)."""
    from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E501
        _audit_provenance_invariants,
    )
    doc = _audit_provenance_invariants.__doc__ or ""
    assert "SENSOR-CAPABILITY-1" in doc
    assert "closed by design" in doc


# ----------------------------------------------------------------------
# Options-flow round-trip surrogate (no HA harness needed — validation
# is pure and the JSON parse path is exercised in the flow save handler).
# ----------------------------------------------------------------------


def test_options_flow_capability_roundtrip_via_validate() -> None:
    """Empty JSON → empty payload → no key persisted (byte-identity)."""
    room = _room(occupancy=["binary_sensor.bed"])
    # Empty payload survives validation with no errors.
    assert validate_capabilities_payload(room, {}) == []
    # Round-trip: declare, validate, then re-derive.
    payload = {"binary_sensor.bed": {"kind": CAPABILITY_KIND_BED}}
    assert validate_capabilities_payload(room, payload) == []
    room_with = _room(
        occupancy=["binary_sensor.bed"], overrides=payload,
    )
    assert derive_capability(room_with, "binary_sensor.bed").kind == "bed"
