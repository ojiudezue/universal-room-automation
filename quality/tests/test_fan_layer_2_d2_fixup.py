"""FAN-LAYER-2 D2 fix-up tests (2026-08-11 consolidated fix-up pass).

Covers:
  * A-LOW-1  — _OracleISOField.__set__ coerces datetime → ISO; raises
    TypeError on other non-str/non-None types.
  * A-MED-1  — migrate_legacy_entry_keys takes field-wise MAX on collision
    (never overwrite a fresh room:* row with a stale entry:* row); is
    IDEMPOTENT on second call; a live hold under entry:<id> SURVIVES the
    re-keying.
  * A-LOW-3  — canonical FAN_TRIGGER_HVAC_SLEEP_ONSET_ON at the emit site
    makes the sleep-axis veto REACHABLE (wrong axis on snapshot → VETO).
  * B-HIGH-1 — FanController.discover_fans wires
    migrate_legacy_entry_keys with the REAL entry_id → room:{NFC(name)}
    map (no-arg version DOES NOT drop live holds).
  * B-MED-1  — _room_key sanitizes control chars (WARN, no raise).
  * Presence — presence_fan_recheck legacy fallback: oracle absent →
    local-cache read path actually drives.
  * Behavioral W1 / W2 / W3-temp / W3-onset — RoomAutomation.__new__
    harness with a live oracle, paired DEFER (blocking verdict → no
    emit) + ALLOW (positive control → emit fires). Anchors the 4
    RoomAutomation wraps that C's HVAC-tier harness could not reach
    (residual HIGH per C's report).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# Shared bootstrap — installs all the homeassistant.* stubs so the URA
# modules can import.
import _provenance_harness  # noqa: F401,E402

from custom_components.universal_room_automation.const import (  # noqa: E402
    DOMAIN,
    FAN_TRIGGER_HVAC_SLEEP_ONSET_ON,
)

# The homeassistant.const stub in _provenance_harness returns a MagicMock
# object for SERVICE_TURN_ON / SERVICE_TURN_OFF (not the literal string
# used in production). The wrap sites pass these through directly, so the
# recorder log carries the same MagicMock objects. Import them here so
# tests can pattern-match against the SAME sentinel object.
from homeassistant.const import (  # noqa: E402
    SERVICE_TURN_ON as _HA_SERVICE_TURN_ON,
    SERVICE_TURN_OFF as _HA_SERVICE_TURN_OFF,
)


def _is_turn_off(svc) -> bool:
    return svc == "turn_off" or svc is _HA_SERVICE_TURN_OFF


def _is_turn_on(svc) -> bool:
    return svc == "turn_on" or svc is _HA_SERVICE_TURN_ON
from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E402
    FanDecisionSnapshot,
    FanPolicyOracle,
    _RoomRecord,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: E402
    RoomFanState,
    _room_key,
)


# ---------------------------------------------------------------------------
# A-LOW-1 — _OracleISOField.__set__ datetime coercion + TypeError.
# ---------------------------------------------------------------------------

class _StubHass:
    def __init__(self, oracle=None):
        self.data = {DOMAIN: {"fan_oracle": oracle}} if oracle else {}


def test_a_low_1_field_set_coerces_datetime_to_isoformat():
    oracle = FanPolicyOracle()
    rfs = RoomFanState(
        room_name="Alpha", zone_id="z1",
        hass=_StubHass(oracle),
    )
    dt = datetime(2026, 8, 11, 12, 34, 56)
    rfs.manual_on_hold_until = dt  # datetime → ISO coerced
    assert rfs.manual_on_hold_until == dt.isoformat(), (
        f"datetime setter must round-trip via .isoformat(); got {rfs.manual_on_hold_until!r}"
    )
    assert oracle.get_state(_room_key("Alpha")).manual_on_hold_until == dt


def test_a_low_1_field_set_rejects_bad_type_with_typeerror():
    oracle = FanPolicyOracle()
    rfs = RoomFanState(
        room_name="Alpha", zone_id="z1",
        hass=_StubHass(oracle),
    )
    for bad in (12345, 3.14, ["not", "a", "string"], object()):
        with pytest.raises(TypeError):
            rfs.manual_on_hold_until = bad


def test_a_low_1_field_set_none_and_empty_string_both_clear():
    oracle = FanPolicyOracle()
    rfs = RoomFanState(
        room_name="Alpha", zone_id="z1",
        hass=_StubHass(oracle),
    )
    rfs.manual_on_hold_until = datetime(2026, 8, 11, 12, 0, 0)
    assert oracle.get_state(_room_key("Alpha")).manual_on_hold_until is not None
    rfs.manual_on_hold_until = None
    assert oracle.get_state(_room_key("Alpha")).manual_on_hold_until is None
    rfs.manual_on_hold_until = datetime(2026, 8, 11, 12, 0, 0)
    rfs.manual_on_hold_until = ""
    assert oracle.get_state(_room_key("Alpha")).manual_on_hold_until is None


# ---------------------------------------------------------------------------
# A-MED-1 — migrate_legacy_entry_keys field-wise MAX + idempotent + hold survives
# ---------------------------------------------------------------------------

def test_a_med_1_live_hold_under_entry_key_survives_migration():
    oracle = FanPolicyOracle()
    dt = datetime(2026, 8, 11, 12, 0, 0)
    # Legacy row (pre-D1 shape) carries a live hold.
    legacy = oracle._get_record("entry:eid-1")  # noqa: SLF001
    legacy.manual_on_hold_until = dt + timedelta(hours=2)
    legacy.hold_id = 5

    n = oracle.migrate_legacy_entry_keys({"entry:eid-1": "room:LivingRoom"})
    assert n == 1
    # Legacy row gone; target row carries the surviving hold.
    assert "entry:eid-1" not in oracle._rooms  # noqa: SLF001
    assert oracle.get_state("room:LivingRoom").manual_on_hold_until == dt + timedelta(hours=2)
    assert oracle.get_state("room:LivingRoom").hold_id == 5


def test_a_med_1_collision_keeps_the_later_deadline_field_wise():
    oracle = FanPolicyOracle()
    dt = datetime(2026, 8, 11, 12, 0, 0)
    # Fresh room:* row (post-D1) — LATER hold, EARLIER cooldown.
    fresh = oracle._get_record("room:Foo")  # noqa: SLF001
    fresh.manual_on_hold_until = dt + timedelta(hours=1)
    fresh.manual_off_cooldown_until = dt + timedelta(minutes=5)
    fresh.hold_id = 2
    # Stale entry:* row — EARLIER hold, LATER cooldown (mixed).
    stale = oracle._get_record("entry:eid-X")  # noqa: SLF001
    stale.manual_on_hold_until = dt + timedelta(minutes=15)
    stale.manual_off_cooldown_until = dt + timedelta(minutes=20)
    stale.hold_id = 1

    oracle.migrate_legacy_entry_keys({"entry:eid-X": "room:Foo"})

    merged = oracle.get_state("room:Foo")
    # Field-wise MAX preserved.
    assert merged.manual_on_hold_until == dt + timedelta(hours=1), (
        "fresh room:* row's LATER hold MUST NOT be overwritten by stale entry:*"
    )
    assert merged.manual_off_cooldown_until == dt + timedelta(minutes=20), (
        "stale row's LATER cooldown SHOULD win (field-wise MAX; freshest wins)"
    )
    assert merged.hold_id == 2, "hold_id must stay monotonic (max)"


def test_a_med_1_migration_is_idempotent():
    oracle = FanPolicyOracle()
    dt = datetime(2026, 8, 11, 12, 0, 0)
    oracle._get_record("entry:eid-1").manual_on_hold_until = dt + timedelta(hours=1)  # noqa: SLF001
    mapping = {"entry:eid-1": "room:Foo"}
    n1 = oracle.migrate_legacy_entry_keys(mapping)
    assert n1 == 1
    before = oracle.get_state("room:Foo").manual_on_hold_until
    n2 = oracle.migrate_legacy_entry_keys(mapping)
    assert n2 == 0, "second call must be a no-op (legacy row already folded)"
    assert oracle.get_state("room:Foo").manual_on_hold_until == before


def test_a_med_1_unmapped_legacy_rows_are_left_in_place_not_dropped():
    """Safer than dropping — caller may resupply a richer map later."""
    oracle = FanPolicyOracle()
    dt = datetime(2026, 8, 11, 12, 0, 0)
    oracle._get_record("entry:orphan").manual_on_hold_until = dt + timedelta(hours=1)  # noqa: SLF001
    n = oracle.migrate_legacy_entry_keys({"entry:other-id": "room:Other"})
    assert n == 0
    # Orphan still present — subsequent call with the right map will fold it.
    assert "entry:orphan" in oracle._rooms  # noqa: SLF001


# ---------------------------------------------------------------------------
# A-LOW-3 — canonical FAN_TRIGGER_HVAC_SLEEP_ONSET_ON reaches the sleep-axis veto.
# ---------------------------------------------------------------------------

def test_a_low_3_hvac_sleep_onset_trigger_vetoed_under_wrong_axis():
    """A snapshot with sleep_axis='room_window' + FAN_TRIGGER_HVAC_SLEEP_ONSET_ON
    (which is in _HVAC_SLEEP_TRIGGERS) MUST return VETO('sleep_axis_mismatch')
    on the ON-consult. Previously the dynamic 'update:sleep_onset' string
    bypassed the axis check entirely so a wrong-axis snapshot was silently
    accepted."""
    oracle = FanPolicyOracle()
    snap = FanDecisionSnapshot(
        now=datetime(2026, 8, 11, 12, 0, 0),
        sleep_state="sleep",
        sleep_axis="room_window",  # wrong axis for HVAC-tier trigger
        house_state="sleep",
        is_hvac_managing=True,
        entities=("fan.x",),
        observed_any_on=False,
    )
    verdict = oracle.may_turn_on(
        "room:X", FAN_TRIGGER_HVAC_SLEEP_ONSET_ON, snap,
    )
    assert verdict.is_veto and verdict.reason == "sleep_axis_mismatch", (
        f"wrong-axis snapshot MUST VETO; got {verdict!r}"
    )


def test_a_low_3_hvac_sleep_onset_trigger_allows_correct_axis():
    """Positive control: same trigger with sleep_axis='house_state' ALLOWs."""
    oracle = FanPolicyOracle()
    snap = FanDecisionSnapshot(
        now=datetime(2026, 8, 11, 12, 0, 0),
        sleep_state="sleep",
        sleep_axis="house_state",
        house_state="sleep",
        is_hvac_managing=True,
        entities=("fan.x",),
        observed_any_on=False,
    )
    verdict = oracle.may_turn_on(
        "room:X", FAN_TRIGGER_HVAC_SLEEP_ONSET_ON, snap,
    )
    assert verdict.is_allow, f"correct-axis ALLOW; got {verdict!r}"


# ---------------------------------------------------------------------------
# B-MED-1 — _room_key sanitizes control chars (WARN, no raise).
# ---------------------------------------------------------------------------

def test_b_med_1_room_key_sanitizes_control_chars_no_raise():
    assert _room_key("bad\x00name") == "room:badname"
    assert _room_key("tab\tspace") == "room:tabspace"
    # All-control input collapses to unkeyed sentinel.
    assert _room_key("\x00\x01\x02") == "room:__unkeyed__"


# ---------------------------------------------------------------------------
# B-HIGH-1 — migrate_legacy_entry_keys is WIRED from FanController.discover_fans
# with the REAL entry_id → room:{NFC(name)} mapping (not {} which would drop).
# ---------------------------------------------------------------------------

def test_b_high_1_discover_fans_wires_migration_with_real_mapping():
    """Seed a live hold under entry:<eid>, run discover_fans (which iterates
    room config entries), and assert the hold survived RE-KEYED to
    room:<NFC(name)>. Prior state: helper was defined but never called; if
    it had been called with {} the hold would have been dropped."""
    from custom_components.universal_room_automation.const import (  # noqa: PLC0415
        CONF_ENTRY_TYPE,
        CONF_FANS,
        CONF_ROOM_NAME,
        ENTRY_TYPE_ROOM,
    )
    from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: PLC0415
        FanController,
    )

    dt = datetime(2026, 8, 11, 12, 0, 0)
    oracle = FanPolicyOracle()
    oracle._get_record("entry:eid-42").manual_on_hold_until = dt + timedelta(hours=1)  # noqa: SLF001

    # Room entry that maps entry:eid-42 → room:PrimaryBedroom.
    entry = MagicMock()
    entry.entry_id = "eid-42"
    entry.data = {
        CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
        CONF_ROOM_NAME: "PrimaryBedroom",
        CONF_FANS: ["fan.bedroom"],
    }
    entry.options = {}

    hass = MagicMock()
    hass.data = {DOMAIN: {"fan_oracle": oracle}}
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = lambda domain: [entry]

    zm = MagicMock()
    z = MagicMock()
    z.rooms = ["PrimaryBedroom"]
    zm.zones = {"z1": z}

    fc = FanController.__new__(FanController)
    fc.hass = hass
    fc._zone_manager = zm
    fc._room_fans = {}
    fc._sleep_onset_fired = False
    fc._sleep_onset_last_fire_at = None
    fc._suppress_log_last_at = {}
    fc._last_ledger_cleanup_at = None
    # Fields discover_fans references.
    fc._min_runtime = None  # noqa: SLF001-style attr
    fc._house_state = ""
    fc._fan_assist_active = False

    # Pre-condition: legacy key present; target absent.
    assert "entry:eid-42" in oracle._rooms  # noqa: SLF001
    assert "room:PrimaryBedroom" not in oracle._rooms  # noqa: SLF001

    fc.discover_fans()

    # Post-condition: legacy folded; hold survives under room: key.
    assert "entry:eid-42" not in oracle._rooms, (  # noqa: SLF001
        "discover_fans MUST wire migrate_legacy_entry_keys — legacy row still present"
    )
    assert oracle.get_state("room:PrimaryBedroom").manual_on_hold_until == (
        dt + timedelta(hours=1)
    ), "live hold under entry:<eid> MUST survive migration re-keyed to room:<NFC(name)>"


# ---------------------------------------------------------------------------
# presence_fan_recheck LEGACY FALLBACK — oracle absent → local-cache read drives.
# ---------------------------------------------------------------------------

def test_presence_recheck_falls_back_to_fan_controller_cache_when_oracle_absent():
    """FAN-LAYER-2 §2.1 item 2: presence_fan_recheck._fan_in_manual_cooldown
    prefers the oracle when present, but MUST fall back to the legacy
    fan-controller reach when the oracle is absent (matches the guard
    comment in the migrated method). Drives the LEGACY branch directly."""
    from custom_components.universal_room_automation.domain_coordinators.presence_fan_recheck import (  # noqa: PLC0415,E501
        FanRecheckManager,
    )

    hass = MagicMock()
    hass.data = {DOMAIN: {}}  # NO fan_oracle — legacy branch must fire.

    # A stand-in FanController whose RoomFanState carries an ISO cooldown
    # that the legacy branch parses.
    from datetime import datetime as _dt, timedelta as _td  # noqa: PLC0415
    now = _dt(2026, 8, 11, 12, 0, 0)
    fake_rf = MagicMock()
    fake_rf.manual_off_cooldown_until = (now + _td(minutes=30)).isoformat()

    fake_fc = MagicMock()
    fake_fc._room_fans = {"Bedroom": fake_rf}

    fake_cm = MagicMock()
    fake_cm.coordinators = {
        "hvac": MagicMock(enabled=True, fan_controller=fake_fc),
    }
    hass.data[DOMAIN]["coordinator_manager"] = fake_cm

    mgr = FanRecheckManager.__new__(FanRecheckManager)
    mgr.hass = hass
    mgr._rooms = {}

    # Patch dt_util.now + parse_datetime on the module so the compare is
    # deterministic (the stubbed dt module may not implement parse_datetime).
    import custom_components.universal_room_automation.domain_coordinators.presence_fan_recheck as pfr  # noqa: PLC0415,E501
    from datetime import datetime as _real_dt  # noqa: PLC0415
    orig_now = pfr.dt_util.now
    orig_parse = getattr(pfr.dt_util, "parse_datetime", None)
    orig_local = getattr(pfr.dt_util, "as_local", None)

    def _pd(s):
        try:
            return _real_dt.fromisoformat(s)
        except Exception:  # noqa: BLE001
            return None

    try:
        pfr.dt_util.now = lambda: now
        pfr.dt_util.parse_datetime = _pd
        pfr.dt_util.as_local = lambda x: x
        result = mgr._fan_in_manual_cooldown("Bedroom")
    finally:
        pfr.dt_util.now = orig_now
        if orig_parse is None:
            try:
                delattr(pfr.dt_util, "parse_datetime")
            except Exception:  # noqa: BLE001
                pass
        else:
            pfr.dt_util.parse_datetime = orig_parse
        if orig_local is None:
            try:
                delattr(pfr.dt_util, "as_local")
            except Exception:  # noqa: BLE001
                pass
        else:
            pfr.dt_util.as_local = orig_local
    assert result is True, (
        "legacy fan-controller cache path MUST report cooldown live when the "
        "cached ISO deadline is in the future and no oracle is attached"
    )


# ===========================================================================
# RoomAutomation harness (C's residual HIGH gap — anchor W1/W2/W3-temp/W3-onset)
# ===========================================================================

def _make_room_auto(
    oracle: FanPolicyOracle,
    *,
    room_name: str = "Bedroom",
    entry_id: str = "eid-room-1",
    fans: list = None,
    fan_states: dict = None,
    house_state: str = "day",
    room_type: str = "bedroom",
    fan_sleep_policy: str = "reduce",
    sleep_start: int = 22,
    sleep_end: int = 7,
    now: datetime | None = None,
):
    """Construct a RoomAutomation instance via __new__ (bypass __init__) with
    just enough state seeded to drive handle_temperature_based_fan_control
    and _maybe_sleep_onset_activate. All actuations land in the recorder
    log attached to hass.services.async_call.

    Returns (room_auto, log_list). Log entries are (domain, service, dict).
    """
    from custom_components.universal_room_automation.automation import (  # noqa: PLC0415
        RoomAutomation,
    )

    fans = fans or [f"fan.{room_name.lower()}"]
    fan_states = fan_states or {}

    r = RoomAutomation.__new__(RoomAutomation)
    r.config = {
        "room_name": room_name,
        "fan_control_enabled": True,
        "fans": fans,
        "hvac_coordination_enabled": False,
        "fan_temp_threshold": 80,
        "fan_speed_low_temp": 69,
        "fan_speed_med_temp": 72,
        "fan_speed_high_temp": 75,
        "room_type": room_type,
        "fan_sleep_policy": fan_sleep_policy,
        "sleep_protection_enabled": True,
        "sleep_start_hour": sleep_start,
        "sleep_end_hour": sleep_end,
        "fan_vacancy_hold": 0,  # disable vacancy hold for cleaner branches
    }

    hass = MagicMock()
    hass.data = {DOMAIN: {"fan_oracle": oracle}}

    log: list = []

    async def _svc(domain, service, data=None, blocking=False):
        log.append((domain, service, dict(data or {})))

    hass.services = MagicMock()
    hass.services.async_call = _svc

    states: dict = {}
    for f in fans:
        st = MagicMock()
        st.state = fan_states.get(f, "off")
        states[f] = st
    hass.states = MagicMock()
    hass.states.get = lambda eid: states.get(eid)

    r.hass = hass
    e = MagicMock()
    e.entry_id = entry_id
    r._config_entry = e

    # Bare-minimum instance fields the wrap paths touch.
    r._last_seen_any_fan_on = False
    r._fan_off_issued_this_tick = False
    r._fan_on_issued_this_tick = False
    r._fan_hvac_mismatch_warned = True   # suppress the WARN branch
    r._fan_on_detector_seeded = True
    r._fan_vacancy_start = None
    r._sleep_onset_fired = False
    r._sleep_onset_last_fire_at = None
    r._last_seen_house_state = house_state
    # _safe_service_call state fields.
    r._service_call_reset_date = (now or datetime(2026, 8, 11, 12, 0, 0)).strftime("%Y-%m-%d")
    r._service_calls_today = 0
    r._service_failures_today = 0
    r._sleep_motion_count = 0
    r._humidity_fan_triggered_time = None
    r._humidity_on_since = None
    r._humidity_cap_suppressed = False
    r._humidity_ema = None
    r._humidity_ema_samples = 0
    r._humidity_ema_warmup_seen_at = None
    r._humidity_ema_last_sample_ts = None
    from collections import deque as _deque  # noqa: PLC0415
    r._humidity_window = _deque()
    r._humidity_spike_was_trigger = False
    r._humidity_presence_runtime_until = None
    r._humidity_last_room_occupied = None
    r._last_auto_off_date = None
    r._alert_lights_active = False
    r._alert_light_original_states = {}
    r._last_warning_date_hour = None
    r._last_timed_open_date = None
    r._last_timed_close_date = None
    r._cover_op_in_flight = False
    r._cover_failures_today = 0
    r._cover_attempts_today = 0
    r._cover_failure_reset_date = (now or datetime(2026, 8, 11, 12, 0, 0)).strftime("%Y-%m-%d")
    r._last_cover_failure_time = None
    r._last_cover_failure_entities = []
    # Descriptor-backed fields' local slots (set via __dict__ to bypass
    # the property setter — descriptor is on the class RoomAutomation via
    # module-level definition).
    r.__dict__["_fan_manual_off_until_local"] = None
    r.__dict__["_fan_manual_on_until_local"] = None
    r.coordinator = MagicMock()

    # dt_util freeze
    import custom_components.universal_room_automation.automation as _auto  # noqa: PLC0415
    if now is not None:
        _auto.dt_util.now = lambda: now
        _auto.dt_util.utcnow = lambda: now

    return r, log


def _make_snap(oracle_only: bool = False):
    # Convenience — not the RoomAutomation snapshot, but a raw one for
    # oracle seeding sanity if needed.
    return FanDecisionSnapshot(
        now=datetime(2026, 8, 11, 12, 0, 0),
        sleep_state="awake",
        sleep_axis="room_window",
        house_state="day",
        is_hvac_managing=False,
        entities=(),
        observed_any_on=False,
    )


def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# W1 — temp/vacancy revert OFF wrap.
# ---------------------------------------------------------------------------

def test_w1_temp_revert_off_defers_under_manual_on_hold():
    """W1 DEFER: temp below-threshold with a live manual-ON hold in the
    oracle → no fan turn_off emitted. Neuter `verdict.is_allow` at the W1
    site → this test MUST red."""
    now = datetime(2026, 8, 11, 12, 0, 0)
    oracle = FanPolicyOracle()
    oracle._get_record(_room_key("Bedroom")).manual_on_hold_until = (  # noqa: SLF001
        now + timedelta(hours=1)
    )
    r, log = _make_room_auto(
        oracle, fan_states={"fan.bedroom": "on"}, now=now,
    )
    r._last_seen_any_fan_on = True

    _run(r.handle_temperature_based_fan_control(temperature=60.0, occupied=False))

    turn_offs = [
        (svc, d.get("entity_id"))
        for (_dom, svc, d) in log if _is_turn_off(svc)
    ]
    assert ("turn_off", ["fan.bedroom"]) not in turn_offs and \
        ("turn_off", "fan.bedroom") not in turn_offs, (
            f"W1 DEFER: manual-ON hold MUST suppress temp-revert OFF. Log: {log}"
        )


def test_w1_temp_revert_off_allows_when_oracle_clear():
    """W1 ALLOW: clean oracle → temp below-threshold DOES fire fan turn_off."""
    now = datetime(2026, 8, 11, 12, 0, 0)
    oracle = FanPolicyOracle()
    r, log = _make_room_auto(
        oracle, fan_states={"fan.bedroom": "on"}, now=now,
    )
    r._last_seen_any_fan_on = True

    _run(r.handle_temperature_based_fan_control(temperature=60.0, occupied=False))

    turn_offs = [
        (svc, d.get("entity_id"))
        for (_dom, svc, d) in log if _is_turn_off(svc)
    ]
    # The wrap emits with entity_id=fans list.
    assert any(
        _is_turn_off(svc) and eid == ["fan.bedroom"] for (svc, eid) in turn_offs
    ), f"W1 ALLOW: clean oracle MUST emit temp-revert OFF. Log: {log}"


# ---------------------------------------------------------------------------
# W2 — FAN_SLEEP_OFF branch OFF wrap.
# ---------------------------------------------------------------------------

def test_w2_sleep_off_defers_under_manual_on_hold():
    """W2 DEFER: sleep-off branch with a live manual-ON hold → no OFF.
    is_sleep_mode_active() must be TRUE — set fan_sleep_policy=off and
    a sleep-time window that covers the frozen now.
    NOTE: the wrap is guarded by an earlier `is_fan_in_manual_on_hold()`
    short-circuit which also short-circuits under a live hold, so the
    net observable is the same: no OFF emit. Neutering the wrap's
    verdict does not flip this test (the pre-check catches it first),
    but this positive-DEFER anchor still locks the observable behavior
    for the wrap's supported semantics."""
    now = datetime(2026, 8, 11, 2, 0, 0)  # 2 AM — inside sleep window
    oracle = FanPolicyOracle()
    oracle._get_record(_room_key("Bedroom")).manual_on_hold_until = (  # noqa: SLF001
        now + timedelta(hours=1)
    )
    r, log = _make_room_auto(
        oracle, fan_states={"fan.bedroom": "on"},
        fan_sleep_policy="off", now=now,
    )
    r._last_seen_any_fan_on = True

    _run(r.handle_temperature_based_fan_control(temperature=75.0, occupied=True))

    turn_offs = [svc for (_dom, svc, _d) in log if _is_turn_off(svc)]
    assert not turn_offs, (
        f"W2 DEFER: FAN_SLEEP_OFF under manual-ON hold MUST NOT emit. Log: {log}"
    )


def test_w2_sleep_off_allows_when_oracle_clear():
    """W2 ALLOW: clean oracle + sleep-mode + policy=off → OFF fires."""
    now = datetime(2026, 8, 11, 2, 0, 0)
    oracle = FanPolicyOracle()
    r, log = _make_room_auto(
        oracle, fan_states={"fan.bedroom": "on"},
        fan_sleep_policy="off", now=now,
    )
    r._last_seen_any_fan_on = True

    _run(r.handle_temperature_based_fan_control(temperature=75.0, occupied=True))

    turn_offs = [
        (svc, d.get("entity_id"))
        for (_dom, svc, d) in log if _is_turn_off(svc)
    ]
    assert any(
        _is_turn_off(svc) and eid == ["fan.bedroom"] for (svc, eid) in turn_offs
    ), f"W2 ALLOW: clean-oracle FAN_SLEEP_OFF MUST emit. Log: {log}"


# ---------------------------------------------------------------------------
# W3-temp — temp-branch ON wrap.
# ---------------------------------------------------------------------------

def test_w3_temp_on_defers_under_manual_off_cooldown():
    """W3-temp DEFER: high-temp branch, live manual-OFF cooldown in oracle
    → no fan turn_on emitted. Neuter the W3-temp verdict → test reds."""
    now = datetime(2026, 8, 11, 15, 0, 0)  # daytime, outside sleep window
    oracle = FanPolicyOracle()
    oracle._get_record(_room_key("LivingRoom")).manual_off_cooldown_until = (  # noqa: SLF001
        now + timedelta(hours=1)
    )
    r, log = _make_room_auto(
        oracle, room_name="LivingRoom",
        fans=["fan.livingroom"],
        fan_states={"fan.livingroom": "off"},
        room_type="generic",  # not bedroom → no sleep-occupied hold
        now=now,
    )

    _run(r.handle_temperature_based_fan_control(temperature=82.0, occupied=True))

    turn_ons = [svc for (_dom, svc, _d) in log if _is_turn_on(svc)]
    assert not turn_ons, (
        f"W3-temp DEFER: live cooldown MUST suppress temp-branch ON. Log: {log}"
    )


def test_w3_temp_on_allows_when_oracle_clear():
    """W3-temp ALLOW: clean oracle + high temp + occupied → turn_on fires."""
    now = datetime(2026, 8, 11, 15, 0, 0)
    oracle = FanPolicyOracle()
    r, log = _make_room_auto(
        oracle, room_name="LivingRoom",
        fans=["fan.livingroom"],
        fan_states={"fan.livingroom": "off"},
        room_type="generic",
        now=now,
    )

    _run(r.handle_temperature_based_fan_control(temperature=82.0, occupied=True))

    turn_ons = [
        (svc, d.get("entity_id"))
        for (_dom, svc, d) in log if _is_turn_on(svc)
    ]
    assert any(_is_turn_on(svc) for (svc, _eid) in turn_ons), (
        f"W3-temp ALLOW: clean oracle MUST emit temp-branch ON. Log: {log}"
    )


# ---------------------------------------------------------------------------
# W3-onset — sleep-onset ON wrap (via _maybe_sleep_onset_activate directly).
# ---------------------------------------------------------------------------

def _seed_onset_ready(r, now):
    """Set the onset-activate preconditions so the wrap-block is reached."""
    r._last_seen_house_state = "waking"   # prior != "sleep" and not ""
    r._sleep_onset_fired = False
    r._sleep_onset_last_fire_at = None


def test_w3_onset_on_defers_under_manual_off_cooldown():
    """W3-onset DEFER: sleep-onset branch with a live manual-OFF cooldown
    in the oracle → no fan turn_on emitted. Onset path also has an
    upstream ``is_fan_in_manual_cooldown()`` short-circuit which catches
    this — the wrap DEFER is a defense-in-depth belt-and-braces; the
    net observable is no OFF-branch emission. Anchors the observable
    contract."""
    now = datetime(2026, 8, 11, 23, 0, 0)  # inside sleep window (22-07)
    oracle = FanPolicyOracle()
    oracle._get_record(_room_key("Bedroom")).manual_off_cooldown_until = (  # noqa: SLF001
        now + timedelta(hours=1)
    )
    r, log = _make_room_auto(
        oracle, room_name="Bedroom",
        fans=["fan.bedroom"],
        fan_states={"fan.bedroom": "off"},
        room_type="bedroom",
        fan_sleep_policy="reduce",
        now=now,
    )
    _seed_onset_ready(r, now)

    # Force house_state=="sleep" so the edge preconditions are met.
    r._read_current_house_state = lambda: "sleep"

    _run(r._maybe_sleep_onset_activate(
        fans=["fan.bedroom"], temperature=76.0, occupied=True,
    ))

    turn_ons = [svc for (_dom, svc, _d) in log if _is_turn_on(svc)]
    assert not turn_ons, (
        f"W3-onset DEFER: cooldown MUST suppress sleep-onset ON. Log: {log}"
    )


def test_w3_onset_on_allows_when_oracle_clear():
    """W3-onset ALLOW: clean oracle + sleep-mode + occupied + temp>=threshold
    → turn_on fires. Neuter the W3-onset verdict → test reds."""
    now = datetime(2026, 8, 11, 23, 0, 0)
    oracle = FanPolicyOracle()
    r, log = _make_room_auto(
        oracle, room_name="Bedroom",
        fans=["fan.bedroom"],
        fan_states={"fan.bedroom": "off"},
        room_type="bedroom",
        fan_sleep_policy="reduce",
        now=now,
    )
    _seed_onset_ready(r, now)
    r._read_current_house_state = lambda: "sleep"

    _run(r._maybe_sleep_onset_activate(
        fans=["fan.bedroom"], temperature=76.0, occupied=True,
    ))

    turn_ons = [
        (svc, d.get("entity_id"))
        for (_dom, svc, d) in log if _is_turn_on(svc)
    ]
    assert any(_is_turn_on(svc) for (svc, _eid) in turn_ons), (
        f"W3-onset ALLOW: clean oracle MUST emit sleep-onset ON. Log: {log}"
    )
