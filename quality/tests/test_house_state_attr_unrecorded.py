"""HOUSE-STATE-SENSOR-ATTR-CHURN-1: churny house-state attributes stay out
of the recorder; low-churn diagnostics stay in.

Asserts on the set HA actually hands the recorder
(``Entity.__combined_unrecorded_attributes``, built in
``Entity.__init_subclass__`` — helpers/entity.py:563 and emitted at :1487),
not on source text.
"""

from custom_components.universal_room_automation.sensor import (
    PresenceHouseStateSensor,
)

_UNRECORDED = {
    "dwell_seconds",
    "zones",
    "signal_consensus",
    "signal_consensus_band",
    "signal_consensus_inputs",
    "stale_counted_home",
    "nobody_home_zone_input",
}

_KEPT_RECORDED = {
    "state",
    "previous_state",
    "state_since",
    "veto_path",
    "last_veto_decision",
    "last_away_branch",
    "last_away_at",
    "census_count",
    "boot_settle_done",
    "guest_reason",
}


def _combined():
    return PresenceHouseStateSensor._Entity__combined_unrecorded_attributes


def test_churny_keys_unrecorded():
    combined = _combined()
    for key in sorted(_UNRECORDED):
        assert key in combined, f"{key} would be recorded"


def test_low_churn_diagnostics_stay_recorded():
    combined = _combined()
    for key in sorted(_KEPT_RECORDED):
        assert key not in combined, f"{key} would be dropped from the recorder"
