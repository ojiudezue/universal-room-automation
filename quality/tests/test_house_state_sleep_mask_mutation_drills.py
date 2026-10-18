"""Per-site mutation drills for the SLEEP-mask / BLE-memory / AWAY
observability cycle (Tier 3, plan Rev 2).

Each case neuters ONE load-bearing site in a TEMP COPY of the repo
(``_mutation_sandbox.apply_mutation_in_sandbox``: baseline-green first,
production file md5 unchanged afterwards) and asserts that the NAMED anchor
test in test_house_state_sleep_mask_ble_memory.py goes RED.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from _mutation_sandbox import apply_mutation_in_sandbox  # noqa: E402

_REPO = _HERE.parent.parent
_URA = _REPO / "custom_components" / "universal_room_automation"
PRES = _URA / "domain_coordinators" / "presence.py"
DBF = _URA / "database.py"
SENS = _URA / "sensor.py"
ANCHOR = _HERE / "test_house_state_sleep_mask_ble_memory.py"


def _move_periodic_into_try(src: str) -> str:
    """Put the periodic registration back inside the discovery try."""
    reg = (
        "            try:\n"
        "                self._unsub_listeners.append(\n"
        "                    async_track_time_interval(\n"
        "                        self.hass,\n"
        "                        self._periodic_inference,\n"
        "                        timedelta(seconds=60),\n"
        "                    )\n"
        "                )\n"
        "            except Exception:  # noqa: BLE001\n"
        "                _LOGGER.exception(\n"
        "                    \"Presence: periodic inference registration failed\"\n"
        "                )\n"
    )
    assert src.count(reg) == 1
    src = src.replace(reg, "", 1)
    anchor = "                    self._unsub_listeners.append(self._optimizer_intent_unsub)\n"
    inner = (
        "                self._unsub_listeners.append(\n"
        "                    async_track_time_interval(\n"
        "                        self.hass,\n"
        "                        self._periodic_inference,\n"
        "                        timedelta(seconds=60),\n"
        "                    )\n"
        "                )\n"
    )
    assert src.count(anchor) == 1
    return src.replace(anchor, anchor + inner, 1)


def _count_before_gates(src: str) -> str:
    """Move the AWAY-entry note ABOVE the boot-settle / observation gates."""
    gate = "        # F5: boot-settle gate — same short-circuit as pre-refactor site.\n"
    assert src.count(gate) == 1
    note = (
        "        if new_val == HouseState.AWAY.value and old_val != HouseState.AWAY.value:\n"
        "            self._note_away_entry(source)\n"
    )
    src = src.replace(gate, note + gate, 1)
    return src.replace(
        "            try:\n                self._note_away_entry(source)\n",
        "            try:\n                pass\n", 1,
    )


# (id, file, swap_from | mutator, swap_to, anchor test)
DRILLS = [
    # ---- D1 ----
    ("d1_callsite_kwarg_deleted", PRES,
     "            any_zone_occupied_for_empty=any_zone_occupied_for_empty,\n", "",
     "test_nobody_home_blocked_in_sleep_when_zone_raw_occupied"),
    ("d1_infer_ignores_new_input", PRES,
     "        if census_count == 0 and not _zone_occ_for_empty:",
     "        if census_count == 0 and not any_zone_occupied:",
     "test_nobody_home_blocked_in_sleep_when_zone_raw_occupied"),
    ("d1_raw_limb_dropped", PRES,
     "                    t.mode == ZonePresenceMode.SLEEP\n                    and self._zone_night_raw(t)",
     "                    False",
     "test_nobody_home_blocked_in_sleep_when_zone_raw_occupied"),
    ("d1_kill_constant_gate_inverted", PRES,
     "        if PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP:\n            any_zone_occupied_for_empty",
     "        if not PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP:\n            any_zone_occupied_for_empty",
     "test_kill_constant_false_restores_masked_behaviour"),
    ("d1_room_limb_dropped", PRES,
     "            rooms = [r for r, occ in tracker._room_occupied.items() if occ]",
     "            rooms = []",
     "test_nobody_home_blocked_in_sleep_when_zone_raw_occupied"),
    ("d1_ble_limb_dropped", PRES,
     "        if tracker._ble_occupied:\n            return [\"<ble>\"]",
     "        if False:\n            return [\"<ble>\"]",
     "test_night_raw_ble_and_camera_limbs"),
    ("d1_camera_limb_dropped", PRES,
     "            return [\"<camera>\"] if tracker._any_camera_occupied() else []",
     "            return []",
     "test_night_raw_ble_and_camera_limbs"),
    ("d1_error_counts_empty", PRES,
     "        except Exception:  # noqa: BLE001 — fail toward holding\n            return [\"<error>\"]\n        if rooms:",
     "        except Exception:  # noqa: BLE001 — fail toward holding\n            return []\n        if rooms:",
     "test_night_raw_helper_error_counts_room_occupied"),
    # ---- D1b wake-time discharge (Rev 2.1, P5) ----
    ("d1b_disjunct_removed", PRES,
     "            has_people = True\n\n        if not has_people:",
     "            pass\n\n        if not has_people:",
     "test_sleep_leaves_after_window_with_raw_occupancy"),
    # d1b_sleep_hour_conjunct_dropped is an EQUIVALENT mutant: inside sleep
    # hours a SLEEP house returns None from the sleep-hours branch anyway.
    # The conjunct is kept as documentation of P5's "window has ended".
    ("d1b_sleep_state_conjunct_dropped", PRES,
     "            and current_state == HouseState.SLEEP\n            and not self._is_sleep_hour(hour)",
     "            and not self._is_sleep_hour(hour)",
     "test_infer_wake_disjunct_engine_level"),
    # ---- D1 trip-wire (Rev 2.1, P5) ----
    ("tripwire_call_removed", PRES,
     "            self._check_sleep_raw_hold(\n                current_state, any_zone_occupied, any_zone_occupied_for_empty,\n            )",
     "            pass",
     "test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound"),
    ("tripwire_fire_removed", PRES,
     "        self.hass.async_create_task(\n            fire_stuck_signal(",
     "        (lambda *_a, **_k: None)(\n            fire_stuck_signal(",
     "test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound"),
    ("tripwire_bound_ignored", PRES,
     "        if held_s <= bound:\n            return",
     "        if False:\n            return",
     "test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound"),
    ("tripwire_once_latch_dropped", PRES,
     "        if bound <= 0 or self._sleep_raw_hold_nm_fired:",
     "        if bound <= 0:",
     "test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound"),
    ("tripwire_census_conjunct_dropped", PRES,
     "            and self._census_count == 0\n            and not any_zone_occupied",
     "            and not any_zone_occupied",
     "test_sleep_raw_hold_tripwire_not_when_census_positive"),
    ("tripwire_kill_switch_ignored", PRES,
     "        if bound <= 0 or self._sleep_raw_hold_nm_fired:",
     "        if self._sleep_raw_hold_nm_fired:",
     "test_sleep_raw_hold_tripwire_kill_switch_zero"),
    ("tripwire_window_gate_dropped", PRES,
     "        if engine._is_sleep_hour(now_local.hour):\n            self._sleep_raw_hold_since = None\n            return",
     "        if False:\n            return",
     "test_sleep_raw_hold_tripwire_silent_during_sleep_window"),
    ("tripwire_clock_from_hold_not_window_end", PRES,
     "        held_s = (now_local - window_end).total_seconds()",
     "        held_s = (now_local - window_end).total_seconds() + 3600",
     "test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound"),
    ("tripwire_episode_not_reset", PRES,
     "        if not held:\n            self._sleep_raw_hold_since = None",
     "        if not held:\n            pass",
     "test_sleep_raw_hold_tripwire_episode_resets_when_room_clears"),
    ("d1_nobody_home_label_dropped", PRES,
     "            self._veto_path = \"nobody_home\"\n", "",
     "test_nobody_home_fires_in_sleep_when_all_raw_clear"),
    ("d1_label_on_already_away", PRES,
     "                return None  # Already away (label stays \"none\", R2 M3)",
     "                self._veto_path = \"nobody_home\"\n                return None",
     "test_already_away_tick_keeps_veto_path_none"),
    ("d1_periodic_back_in_try", PRES, _move_periodic_into_try, None,
     "test_periodic_registered_when_discovery_raises"),
    # ---- D2 ----
    ("d2_predicate_reverted", PRES,
     "            return bool(\n                PRESENCE_STALE_RESIDENT_COUNTS_HOME\n                and _status == TRACKING_STATUS_STALE\n            )",
     "            return False",
     "test_stale_resident_blocks_alpha"),
    ("d2_kill_conjunct_dropped", PRES,
     "                PRESENCE_STALE_RESIDENT_COUNTS_HOME\n                and _status == TRACKING_STATUS_STALE",
     "                _status == TRACKING_STATUS_STALE",
     "test_kill_constant_false_excludes_stale"),
    ("d2_stale_conjunct_widened", PRES,
     "                and _status == TRACKING_STATUS_STALE\n",
     "\n",
     "test_wigton_shape_sleep_loop_suppressed"),
    ("d2_phone_precedence_dropped", PRES,
     "                    if phone_ok and track_ok:",
     "                    if track_ok:",
     "test_d2_preserves_phone_left_behind_precedence"),
    ("d2_stale_list_not_recorded", PRES,
     "                            stale_counted_home.append(name)", "                            pass",
     "test_stale_resident_blocks_alpha"),
    # ---- D3 ----
    ("d3_note_call_removed", PRES,
     "            try:\n                self._note_away_entry(source)\n",
     "            try:\n                pass\n",
     "test_last_away_branch_nobody_home"),
    ("d3_count_before_gates", PRES, _count_before_gates, None,
     "test_gated_dispatch_not_counted"),
    ("d3_entry_condition_dropped", PRES,
     "        if new_val == HouseState.AWAY.value and old_val != HouseState.AWAY.value:\n            try:",
     "        if new_val == HouseState.AWAY.value:\n            try:",
     "test_no_restore_branch_value_emitted"),
    ("d3_override_branch_uses_veto_path", PRES,
     "            branch = self._AWAY_BRANCH_FOR_SOURCE.get(source, str(source))",
     "            branch = str(self._veto_path)",
     "test_last_away_branch_override_and_boot_settle_override"),
    ("d3_inference_branch_not_veto_path", PRES,
     "            branch = str(getattr(self, \"_veto_path\", \"none\") or \"none\")",
     "            branch = \"inference\"",
     "test_last_away_branch_nobody_home"),
    ("d3_getter_day_check_dropped", PRES,
     "        if self._away_count_date != self._local_day_key():\n            return 0\n        return int(self._away_entries_today)",
     "        return int(self._away_entries_today)",
     "test_away_entries_today_getter_zero_after_local_midnight"),
    ("d3_periodic_roll_removed", PRES,
     "        try:\n            self._roll_away_count_day()\n        except Exception:  # noqa: BLE001 — display only\n            pass\n",
     "",
     "test_periodic_rolls_away_count_at_midnight"),
    ("d3_setup_hydration_call_removed", PRES,
     "                    await self._hydrate_away_entries_today(db)",
     "                    pass",
     "test_setup_hydrates_away_entries_today"),
    ("d3_bound_not_utc", PRES,
     "            dt_util.as_utc(dt_util.start_of_local_day())\n",
     "            dt_util.start_of_local_day()\n",
     "test_away_count_hydration_naive_utc_bound_includes_boundary_row"),
    ("d3_bound_keeps_tz_suffix", PRES,
     "            .replace(tzinfo=None)\n            .isoformat()\n        )\n        count = await",
     "            .isoformat()\n        )\n        count = await",
     "test_away_count_hydration_naive_utc_bound_includes_boundary_row"),
    ("d3_hydration_state_kwarg_dropped", PRES,
     "            state=HouseState.AWAY.value,\n            exclude_same_previous=True,\n",
     "",
     "test_away_count_hydration_naive_utc_bound_includes_boundary_row"),
    ("d3_dao_state_clause_dropped", DBF,
     "            sql += \" AND state = ?\"\n            params.append(state)\n",
     "",
     "test_away_count_hydration_naive_utc_bound_includes_boundary_row"),
    ("d3_dao_exclude_clause_dropped", DBF,
     "                sql += \" AND (previous_state IS NULL OR previous_state <> ?)\"\n                params.append(state)\n",
     "                pass\n",
     "test_away_count_excludes_away_to_away_rows"),
    ("d3_guest_precedence_swapped", PRES,
     "        if guest_room_gate_armed:\n            self._guest_reason = (",
     "        if guest_room_gate_armed and not unid_gate_armed:\n            self._guest_reason = (",
     "test_guest_reason_room_precedes_unidentified"),
    ("d3_guest_room_not_recorded", PRES,
     "                self._guest_room_gate_fired_room = room_name\n", "",
     "test_guest_reason_room_precedes_unidentified"),
    ("d3_guest_override_dropped", PRES,
     "        elif _guest_override:\n            self._guest_reason = \"override\"\n", "",
     "test_guest_reason_override"),
    ("d3_unrecorded_key_dropped", SENS,
     "        {\"stale_counted_home\", \"nobody_home_zone_input\"}\n    )",
     "        {\"stale_counted_home\"}\n    )",
     "test_unrecorded_attributes_set"),
    ("d3_sensor_attr_detached", SENS,
     "                int(_away_getter()) if callable(_away_getter) else 0",
     "                0",
     "test_sensor_publishes_d3_attributes"),
]


@pytest.mark.parametrize(
    "file_,swap_from,swap_to,anchor",
    [pytest.param(f, a, b, t, id=i) for i, f, a, b, t in DRILLS],
)
def test_mutation_drill_goes_red(file_, swap_from, swap_to, anchor):
    kwargs = dict(anchor_test_file=ANCHOR, anchor_test_name=anchor,
                  expect="KILLED", timeout=300)
    if callable(swap_from):
        apply_mutation_in_sandbox(file_, mutator=swap_from, **kwargs)
    else:
        apply_mutation_in_sandbox(file_, swap_from=swap_from, swap_to=swap_to,
                                  **kwargs)
