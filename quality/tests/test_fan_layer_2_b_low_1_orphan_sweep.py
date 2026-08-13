"""FAN-LAYER-2 B-LOW-1 orphan-ledger-row sweep (2026-08-12).

Reviewer B B-LOW-1 followup: ``FanPolicyOracle.migrate_legacy_entry_keys``
now sweeps orphan rows when called with an authoritative
``current_room_keys`` set:

  * legacy ``entry:<eid>`` rows whose entry_id is not in the mapping AND
    a ``current_room_keys`` set was supplied → DROP (provably orphan).
  * ``room:<name>`` rows whose room_key is not in ``current_room_keys``
    → DROP (rename/delete/recreate within a session).

Live rows (mapped legacy + current room:*) are preserved byte-identical.
The wire-in anchor is ``hvac_fans.FanController.discover_fans`` — the
neuter test detaches the ``current_room_keys=`` kwarg from that call
site and asserts a specific test reds.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401,E402

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    CONF_FANS,
    CONF_ROOM_NAME,
    DOMAIN,
    ENTRY_TYPE_ROOM,
)
from custom_components.universal_room_automation.domain_coordinators.fan_policy_oracle import (  # noqa: E402
    FanPolicyOracle,
)


# ---------------------------------------------------------------------------
# Direct-call semantics on the helper.
# ---------------------------------------------------------------------------

def test_orphan_room_row_dropped_when_current_room_keys_supplied():
    """A ``room:*`` row not in current_room_keys is dropped."""
    oracle = FanPolicyOracle()
    dt = datetime(2026, 8, 12, 12, 0, 0)
    oracle._get_record("room:LivingRoom").manual_on_hold_until = dt  # noqa: SLF001
    oracle._get_record("room:GhostRoom").manual_on_hold_until = dt  # noqa: SLF001

    oracle.migrate_legacy_entry_keys(
        {}, current_room_keys={"room:LivingRoom"},
    )

    assert "room:LivingRoom" in oracle._rooms  # noqa: SLF001
    assert "room:GhostRoom" not in oracle._rooms, (  # noqa: SLF001
        "orphan room:* row MUST be dropped when current_room_keys supplied"
    )


def test_orphan_entry_row_dropped_when_current_room_keys_supplied():
    """A legacy ``entry:*`` row with no mapping AND current_room_keys
    supplied is dropped (provably orphan — no live entry maps to it)."""
    oracle = FanPolicyOracle()
    dt = datetime(2026, 8, 12, 12, 0, 0)
    oracle._get_record("entry:zombie-eid").manual_on_hold_until = dt  # noqa: SLF001

    oracle.migrate_legacy_entry_keys(
        {}, current_room_keys={"room:LivingRoom"},
    )

    assert "entry:zombie-eid" not in oracle._rooms, (  # noqa: SLF001
        "orphan entry:* row MUST be dropped when current_room_keys supplied"
    )


def test_live_rows_preserved_byte_identical_on_sweep():
    """A live room:* row with all fields set is preserved byte-identical
    across a sweep pass that drops sibling orphans."""
    oracle = FanPolicyOracle()
    dt_on = datetime(2026, 8, 12, 12, 0, 0)
    dt_off = datetime(2026, 8, 12, 13, 0, 0)
    rec = oracle._get_record("room:LivingRoom")  # noqa: SLF001
    rec.manual_on_hold_until = dt_on + timedelta(hours=1)
    rec.manual_off_cooldown_until = dt_off + timedelta(hours=1)
    rec.last_on_time = dt_on
    rec.last_off_time = dt_off
    rec.hold_id = 7
    rec.last_trigger_path = "temp_room"
    rec.last_actuation_source = "ura"
    rec.pause_context = "ctx"

    # Sibling orphan to force the sweep loop to actually run.
    oracle._get_record("room:Ghost").manual_on_hold_until = dt_on  # noqa: SLF001

    oracle.migrate_legacy_entry_keys(
        {}, current_room_keys={"room:LivingRoom"},
    )

    survived = oracle._rooms["room:LivingRoom"]  # noqa: SLF001
    assert survived.manual_on_hold_until == dt_on + timedelta(hours=1)
    assert survived.manual_off_cooldown_until == dt_off + timedelta(hours=1)
    assert survived.last_on_time == dt_on
    assert survived.last_off_time == dt_off
    assert survived.hold_id == 7
    assert survived.last_trigger_path == "temp_room"
    assert survived.last_actuation_source == "ura"
    assert survived.pause_context == "ctx"
    assert "room:Ghost" not in oracle._rooms  # noqa: SLF001


def test_sweep_idempotent_second_call_no_op():
    """A second migrate call with the same map + set is a no-op."""
    oracle = FanPolicyOracle()
    dt = datetime(2026, 8, 12, 12, 0, 0)
    oracle._get_record("room:LivingRoom").manual_on_hold_until = dt  # noqa: SLF001
    oracle._get_record("room:Ghost").manual_on_hold_until = dt  # noqa: SLF001

    oracle.migrate_legacy_entry_keys({}, current_room_keys={"room:LivingRoom"})
    snapshot_1 = dict(oracle._rooms)  # noqa: SLF001

    oracle.migrate_legacy_entry_keys({}, current_room_keys={"room:LivingRoom"})
    snapshot_2 = dict(oracle._rooms)  # noqa: SLF001

    assert snapshot_1.keys() == snapshot_2.keys() == {"room:LivingRoom"}


def test_backcompat_no_current_room_keys_leaves_unmapped_and_orphans_intact():
    """When ``current_room_keys`` is None (partial-map caller), unmapped
    legacy rows are preserved AND room:* orphans are NOT swept. This is
    the pre-existing contract that in-flight callers rely on."""
    oracle = FanPolicyOracle()
    dt = datetime(2026, 8, 12, 12, 0, 0)
    oracle._get_record("entry:orphan").manual_on_hold_until = dt  # noqa: SLF001
    oracle._get_record("room:Ghost").manual_on_hold_until = dt  # noqa: SLF001

    oracle.migrate_legacy_entry_keys({"entry:other": "room:Other"})

    assert "entry:orphan" in oracle._rooms  # noqa: SLF001
    assert "room:Ghost" in oracle._rooms  # noqa: SLF001


# ---------------------------------------------------------------------------
# Wire-in anchor — the sweep must be reachable from FanController.discover_fans.
# Neutering the ``current_room_keys=`` kwarg (removing it from the call site)
# reverts to default-None → orphans stay → this test REDS. This is the
# behavioral anchor per "wire-in anchor mandatory" (call site != helper).
# ---------------------------------------------------------------------------

def test_wire_in_discover_fans_passes_current_room_keys_and_sweeps_orphan_room():
    from custom_components.universal_room_automation.domain_coordinators.hvac_fans import (  # noqa: PLC0415
        FanController,
    )

    dt = datetime(2026, 8, 12, 12, 0, 0)
    oracle = FanPolicyOracle()
    # Pre-seed a room:* row for a room that will NOT appear in the current
    # config-entry iteration — i.e. a renamed/deleted room orphan.
    oracle._get_record("room:GhostRoom").manual_on_hold_until = (  # noqa: SLF001
        dt + timedelta(hours=1)
    )
    # Live room the entry iteration will surface (control — must survive).
    oracle._get_record("room:PrimaryBedroom").manual_on_hold_until = (  # noqa: SLF001
        dt + timedelta(hours=2)
    )

    entry = MagicMock()
    entry.entry_id = "eid-live"
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
    fc._min_runtime = None
    fc._house_state = ""
    fc._fan_assist_active = False

    fc.discover_fans()

    # Live room preserved.
    assert oracle.get_state("room:PrimaryBedroom").manual_on_hold_until == (
        dt + timedelta(hours=2)
    ), "live room:* row MUST survive discover_fans sweep"
    # Orphan swept — this is the neuter-detecting assertion.
    assert "room:GhostRoom" not in oracle._rooms, (  # noqa: SLF001
        "discover_fans MUST pass current_room_keys= to migrate_legacy_entry_keys; "
        "orphan room:* row still present → sweep is not wired"
    )
