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
SUB = _URA / "domain_coordinators" / "occupancy_substrate.py"
INIT = _URA / "__init__.py"
DBF = _URA / "database.py"
SENS = _URA / "sensor.py"
STUCK = _URA / "domain_coordinators" / "_stuck_signal_nm.py"
ANCHOR = _HERE / "test_house_state_sleep_mask_ble_memory.py"
ZT = _HERE / "test_zone_tracker_per_entity.py"     # Rev 3 anchors

# Rev 3.2 R1-F10 / R3.2.2: the runner accepts 5-tuples (id, file, swap_from,
# swap_to, anchor) -> anchor_file=ANCHOR, switch="on", or 7-tuples adding
# (anchor_file, switch). An "off" drill runs its anchor with
# `--per-entity-off` (ZONE_OCCUPANCY_PER_ENTITY_ENABLED patched False on the
# const module), so a kill-switch anchor goes RED for the right reason.
pytestmark = pytest.mark.source_mutation


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
     "                    t.mode == ZonePresenceMode.SLEEP\n                    and self._zone_night_raw(t)\n                )\n                for t in self._zone_trackers.values()",
     "                    False\n                )\n                for t in self._zone_trackers.values()",
     "test_nobody_home_blocked_in_sleep_when_zone_raw_occupied"),
    ("d1_kill_constant_gate_inverted", PRES,
     "        if PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP:\n            any_zone_occupied_for_empty",
     "        if not PRESENCE_NOBODY_HOME_READS_RAW_IN_SLEEP:\n            any_zone_occupied_for_empty",
     "test_kill_constant_false_restores_masked_behaviour"),
    ("d1_ble_limb_dropped", PRES,
     "        if tracker._ble_occupied:\n            return [\"<ble>\"]",
     "        if False:\n            return [\"<ble>\"]",
     "test_night_raw_ble_and_camera_limbs"),
    ("d1_camera_limb_dropped", PRES,
     "            return [\"<camera>\"] if tracker._any_camera_occupied() else []",
     "            return []",
     "test_night_raw_ble_and_camera_limbs"),
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
    ("tripwire_fire_removed", PRES,
     "        self.hass.async_create_task(\n            fire_stuck_signal(\n                self.hass,\n                kind=\"sleep_raw_hold\",",
     "        (lambda *_a, **_k: None)(\n            fire_stuck_signal(\n                self.hass,\n                kind=\"sleep_raw_hold\",",
     "test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound"),
    ("tripwire_bound_ignored", PRES,
     "        held_s = (now_local - anchor).total_seconds()\n        if held_s <= bound:\n            return",
     "        held_s = (now_local - anchor).total_seconds()\n        if False:\n            return",
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
    ("d1_room_limb_dropped", PRES,
     "            rooms = {r for r, occ in tracker._room_occupied.items() if occ}",
     "            rooms = set()",
     "test_tracker_view_alone_holds_room"),
    ("d1_error_counts_empty", PRES,
     "            rooms = {r for r, occ in tracker._room_occupied.items() if occ}\n        except Exception:  # noqa: BLE001 — fail toward holding\n            return [\"<error>\"]",
     "            rooms = {r for r, occ in tracker._room_occupied.items() if occ}\n        except Exception:  # noqa: BLE001 — fail toward holding\n            return []",
     "test_night_raw_helper_error_counts_room_occupied"),
    # ---- review D-H1 live limb: kept under the switch (R3.2 L4) -> off ----
    ("dh1_live_limb_dropped", PRES,
     "                    if state is not None and state.state == \"on\":\n                        rooms.add(room_name)",
     "                    pass",
     "test_two_kind_room_zv_pulse_then_clear_keeps_zx_sleeper_switch_off", ANCHOR, "off"),
    ("dh1_live_limb_dropped_same_kind", PRES,
     "                    if state is not None and state.state == \"on\":\n                        rooms.add(room_name)",
     "                    pass",
     "test_same_kind_two_sensor_room_one_off_keeps_sleeper_switch_off", ANCHOR, "off"),
    ("dh1_live_limb_dropped_wigton", PRES,
     "                    if state is not None and state.state == \"on\":\n                        rooms.add(room_name)",
     "                    pass",
     "test_wigton_shape_multi_sensor_master_rollover_holds", ANCHOR, "off"),
    ("dh1_live_limb_counts_unavailable", PRES,
     "                    if state is not None and state.state == \"on\":",
     "                    if state is not None and state.state != \"off\":",
     "test_live_limb_ignores_unavailable_and_other_rooms", ANCHOR, "off"),
    ("dh1_live_limb_ignores_zone_membership", PRES,
     "                    if room_name in rooms or room_name not in tracker.room_names:",
     "                    if room_name in rooms:",
     "test_live_limb_ignores_unavailable_and_other_rooms", ANCHOR, "off"),
    ("dh1_waking_gate_not_fed", PRES,
     "            if not _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n                any_zone_raw_occupied = True",
     "            if not _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n                pass",
     "test_wigton_shape_multi_sensor_master_ends_via_waking_switch_off", ANCHOR, "off"),
    # ---- Rev 3 kill-switch gates (R3.1.1) ----
    ("ks_limb_gate_inverted", PRES,
     "        if not _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n            try:\n                for entity_id, room_name in list(tracker._entity_to_room.items()):",
     "        if _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n            try:\n                for entity_id, room_name in list(tracker._entity_to_room.items()):",
     "test_kill_switch_off_dh1_repro_holds_sleep", ZT, "off"),
    ("ks_d4b_ungated", PRES,
     "            kind in TIER1_KINDS\n            and _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED\n",
     "            kind in TIER1_KINDS\n",
     "test_kill_switch_off_matches_branch_trace", ZT, "off"),
    ("ks_d4a_ungated", SUB,
     "        if per_entity:\n            # Sleep-mask Rev 3 D4a + D4c.1",
     "        if True:\n            # Sleep-mask Rev 3 D4a + D4c.1",
     "test_kill_constant_false_restores_last_writer", ZT, "off"),
    ("ks_d4d_ungated", PRES,
     "        if not _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n            return\n        overridden = bool(getattr(machine, \"is_overridden\", False))\n        tier1_rooms",
     "        overridden = bool(getattr(machine, \"is_overridden\", False))\n        tier1_rooms",
     "test_d4d_silent_when_kill_switch_off", ZT, "off"),
    ("ks_forcing_line_ungated", PRES,
     "            if not _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n                any_zone_raw_occupied = True",
     "            if True:\n                any_zone_raw_occupied = True",
     "test_manual_occupied_zone_override_does_not_force_waking_gate", ZT, "on"),
    # ---- D4a substrate per-kind OR ----
    ("d4a_last_writer", SUB,
     "            occupied = self._kind_on_now(\n                room_name, kind, self._entity_to_room_kind,\n                event_entity=entity_id, event_state=new_state,\n            )",
     "            occupied = new_state is not None and new_state.state == \"on\"",
     "test_substrate_same_kind_sibling_off_keeps_kind_on", ZT, "on"),
    ("d4a_last_writer_same_kind", SUB,
     "            occupied = self._kind_on_now(\n                room_name, kind, self._entity_to_room_kind,\n                event_entity=entity_id, event_state=new_state,\n            )",
     "            occupied = new_state is not None and new_state.state == \"on\"",
     "test_same_kind_two_sensor_room_one_off_keeps_sleeper", ANCHOR, "on"),
    ("d4a_or_never_false", SUB,
     "            if state is not None and state.state == \"on\":\n                return True\n        return False",
     "            if state is not None and state.state == \"on\":\n                return True\n        return True",
     "test_multi_sensor_room_really_empty_still_reaches_away", ANCHOR, "on"),
    ("d4a_unavailable_counts_on", SUB,
     "            if state is not None and state.state == \"on\":\n                return True\n        return False",
     "            if state is not None and state.state != \"off\":\n                return True\n        return False",
     "test_substrate_unavailable_sibling_counts_off", ZT, "on"),
    ("d4a_seed_uses_live_map", SUB,
     "                room_name, k, desired_entity_to_room_kind,\n            )",
     "                room_name, k, self._entity_to_room_kind,\n            )",
     "test_options_save_removing_on_sensor_releases_room", ZT, "on"),
    ("d4a_seed_uses_live_map_add", SUB,
     "                room_name, k, desired_entity_to_room_kind,\n            )",
     "                room_name, k, self._entity_to_room_kind,\n            )",
     "test_options_save_adding_on_sensor_sets_kind", ZT, "on"),
    ("d4a_event_from_states", SUB,
     "            if event_state is not None and getattr(event_state, \"state\", None) == \"on\":",
     "            if (self.hass.states.get(event_entity) is not None\n                    and self.hass.states.get(event_entity).state == \"on\"):",
     "test_callback_before_state_store_uses_payload", ZT, "on"),
    ("d4a_seed_live_rules_differ", SUB,
     "            if state is not None and state.state == \"on\":\n                return True\n        return False",
     "            if state is not None and state.state == \"on\" and event_entity is not None:\n                return True\n        return False",
     "test_seed_and_live_share_kind_on_now", ZT, "on"),
    ("d4_tracker_room_membership", PRES,
     "        if room_name not in self.room_names:\n            return\n\n        bucket = self._room_provenance.setdefault(room_name, {})",
     "        bucket = self._room_provenance.setdefault(room_name, {})",
     "test_tracker_ignores_foreign_room", ZT, "on"),
    # ---- D4b tracker per-kind clear ----
    ("d4b_full_clear", PRES,
     "            bucket.pop(kind, None)\n            if not any(bool(v) for v in bucket.values()):",
     "            self._room_provenance[room_name] = {}\n            bucket = {}\n            if not any(bool(v) for v in bucket.values()):",
     "test_tracker_kind_off_clears_only_that_kind", ZT, "on"),
    ("d4b_full_clear_two_kind", PRES,
     "            bucket.pop(kind, None)\n            if not any(bool(v) for v in bucket.values()):",
     "            self._room_provenance[room_name] = {}\n            bucket = {}\n            if not any(bool(v) for v in bucket.values()):",
     "test_two_kind_room_zv_pulse_then_clear_keeps_zx_sleeper", ANCHOR, "on"),
    ("d4b_full_clear_wigton", PRES,
     "            bucket.pop(kind, None)\n            if not any(bool(v) for v in bucket.values()):",
     "            self._room_provenance[room_name] = {}\n            bucket = {}\n            if not any(bool(v) for v in bucket.values()):",
     "test_wigton_shape_multi_sensor_master_rollover_holds", ANCHOR, "on"),
    ("d4b_full_clear_wigton_day", PRES,
     "            bucket.pop(kind, None)\n            if not any(bool(v) for v in bucket.values()):",
     "            self._room_provenance[room_name] = {}\n            bucket = {}\n            if not any(bool(v) for v in bucket.values()):",
     "test_wigton_shape_multi_sensor_master_ends_via_waking", ANCHOR, "on"),
    ("d4b_pop_becomes_false_slot", PRES,
     "            bucket.pop(kind, None)\n",
     "            bucket[kind] = False\n",
     "test_single_sensor_provenance_shape_identical", ZT, "on"),
    ("d4b_last_kind_always_popped", PRES,
     "            bucket.pop(kind, None)\n            if not any(bool(v) for v in bucket.values()):\n                self._last_kind_per_room.pop(room_name, None)",
     "            bucket.pop(kind, None)\n            if True:\n                self._last_kind_per_room.pop(room_name, None)",
     "test_last_kind_popped_only_when_room_empty", ZT, "on"),
    ("inv_bounded_b_gate_input", PRES,
     "        any_zone_raw_occupied = any(\n            t.raw_occupied for t in self._zone_trackers.values()\n        )",
     "        any_zone_raw_occupied = any(\n            t.mode == ZonePresenceMode.OCCUPIED for t in self._zone_trackers.values()\n        )",
     "test_wigton_shape_multi_sensor_master_ends_via_waking", ANCHOR, "on"),
    ("night_raw_camera_skipped", PRES,
     "            return [\"<camera>\"] if tracker._any_camera_occupied() else []",
     "            return []",
     "test_night_raw_equals_raw_occupied_property", ZT, "on"),
    # ---- D4c discharges ----
    ("d4c_deleted_ignored", SUB,
     "        if new_state is None and not per_entity:\n            return",
     "        if new_state is None:\n            return",
     "test_deleted_entity_while_on_releases_room", ZT, "on"),
    ("d4c2_removed_room_walk_skipped", SUB,
     "                    walk_rooms = desired_rooms | set(snapshot.keys())",
     "                    walk_rooms = desired_rooms",
     "test_removed_room_true_kinds_get_false_edges", ZT, "on"),
    ("d4c2_no_remove_hook", INIT,
     "    if not _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n        return\n    try:\n        if entry.data.get(_ura_const.CONF_ENTRY_TYPE) != _ura_const.ENTRY_TYPE_ROOM:",
     "    return\n    try:\n        if entry.data.get(_ura_const.CONF_ENTRY_TYPE) != _ura_const.ENTRY_TYPE_ROOM:",
     "test_room_delete_via_config_entries_async_remove_releases_kinds", ZT, "on"),
    ("d4c3_reconcile_dropped", PRES,
     "            try:\n                self._reconcile_trackers_to_substrate()\n",
     "            try:\n                pass\n",
     "test_release_clears_kind_that_went_off_during_settle", ZT, "on"),
    ("d4c3_reconcile_dropped_removed_room", PRES,
     "            try:\n                self._reconcile_trackers_to_substrate()\n",
     "            try:\n                pass\n",
     "test_release_reconcile_removed_room_during_settle", ZT, "on"),
    ("d4c3_reconcile_dropped_replay", PRES,
     "            try:\n                self._reconcile_trackers_to_substrate()\n",
     "            try:\n                pass\n",
     "test_boot_settle_replay_unchanged", ZT, "on"),
    ("d4c3_reconcile_writes_all_slots", PRES,
     "                    if bool(have.get(kind, False)) != value:",
     "                    if True:",
     "test_release_reconcile_writes_only_differing_slots", ZT, "on"),
    ("d4c3_reconcile_guard_removed", PRES,
     "            except Exception:  # noqa: BLE001 — defensive\n                _LOGGER.debug(\n                    \"Zone tracker boot-settle reconcile raised (non-fatal)\",",
     "            except ZeroDivisionError:  # noqa: BLE001 — defensive\n                _LOGGER.debug(\n                    \"Zone tracker boot-settle reconcile raised (non-fatal)\",",
     "test_release_reconcile_exception_does_not_abort_tick", ZT, "on"),
    ("d4_refresh_mutates_before_subscribe", SUB,
     "                seed_target = {\n                    room: dict(bucket)\n                    for room, bucket in self._raw_state.items()\n                }",
     "                seed_target = self._raw_state",
     "test_refresh_subscribe_failure_leaves_state_untouched", ZT, "on"),
    ("d4_refresh_swap_dropped", SUB,
     "            if per_entity:\n                self._raw_state = seed_target\n",
     "",
     "test_refresh_retry_after_failure_emits_edges", ZT, "on"),
    # ---- rev32 build-review fix-up ----
    ("d4c3_reconcile_multi_zone", PRES,
     "                if self.tracker_for_room(room_name) is not tracker:\n                    continue\n",
     "",
     "test_reconcile_multi_zone_room_only_owner_written", ZT, "on"),
    ("ks_reconcile_ungated", PRES,
     "        if _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n            try:\n                self._reconcile_trackers_to_substrate()",
     "        if True:\n            try:\n                self._reconcile_trackers_to_substrate()",
     "test_switch_off_release_does_not_reconcile", ZT, "off"),
    ("ks_scratch_ungated", SUB,
     "            if per_entity:\n                seed_target = {",
     "            if True:\n                seed_target = {",
     "test_switch_off_refresh_seeds_in_place", ZT, "off"),
    ("ks_limb_runs_when_on", PRES,
     "        if not _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n            try:\n                for entity_id, room_name in list(tracker._entity_to_room.items()):",
     "        if True:\n            try:\n                for entity_id, room_name in list(tracker._entity_to_room.items()):",
     "test_switch_on_night_limb_skipped_with_divergent_tracker", ZT, "on"),
    ("ks_remove_hook_ungated", INIT,
     "    if not _ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED:\n        return\n    try:\n        if entry.data.get(_ura_const.CONF_ENTRY_TYPE) != _ura_const.ENTRY_TYPE_ROOM:",
     "    try:\n        if entry.data.get(_ura_const.CONF_ENTRY_TYPE) != _ura_const.ENTRY_TYPE_ROOM:",
     "test_async_remove_entry_silent_when_off", ZT, "off"),
    ("d4c2_remove_hook_kind_dropped", INIT,
     "            \"removed\",\n        )",
     "            \"unloaded\",\n        )",
     "test_async_remove_entry_dispatches_removed_when_on", ZT, "on"),
    ("d4d_tier1_any_zone_mode", PRES,
     "            if tracker.mode != ZonePresenceMode.OCCUPIED:\n                continue\n            for room_name, kinds in tracker._room_provenance.items():",
     "            for room_name, kinds in tracker._room_provenance.items():",
     "test_zone_hold_all_away_silent_when_holder_zone_is_away_overridden", ZT, "on"),
    # ---- D4d trip-wire ----
    ("d4d_call_removed", PRES,
     "            self._check_zone_hold_all_away(\n                current_state, any_zone_occupied, tracked_count,\n                all_tracked_persons_away, machine=manager.house_state_machine,\n            )",
     "            pass",
     "test_zone_hold_all_away_fires_once_past_bound", ZT, "on"),
    ("d4d_bound_ignored", PRES,
     "        held_s = (now - self._zone_hold_all_away_since).total_seconds()\n        if held_s <= bound:",
     "        held_s = (now - self._zone_hold_all_away_since).total_seconds()\n        if False:",
     "test_zone_hold_all_away_fires_once_past_bound", ZT, "on"),
    ("d4d_episode_latch_dropped", PRES,
     "        if bound <= 0 or self._zone_hold_all_away_fired:",
     "        if bound <= 0:",
     "test_zone_hold_all_away_fires_once_past_bound", ZT, "on"),
    ("d4d_bound_zero_ignored", PRES,
     "        if bound <= 0 or self._zone_hold_all_away_fired:",
     "        if self._zone_hold_all_away_fired:",
     "test_zone_hold_all_away_bound_zero_disables", ZT, "on"),
    ("d4d_severity_medium", PRES,
     "                    \"that sensor is stuck/phantom (fan?)\"\n                ),\n                severity=\"HIGH\",",
     "                    \"that sensor is stuck/phantom (fan?)\"\n                ),",
     "test_zone_hold_all_away_fires_once_past_bound", ZT, "on"),
    ("d4d_any_zone_occupied_dropped", PRES,
     "            and all_tracked_persons_away\n            and any_zone_occupied\n",
     "            and all_tracked_persons_away\n",
     "test_zone_hold_all_away_silent_when_zone_not_occupied", ZT, "on"),
    ("d4d_tier1_holder_dropped", PRES,
     "            )\n            and tier1_rooms\n        )",
     "            )\n        )",
     "test_zone_hold_all_away_silent_for_camera_only_hold", ZT, "on"),
    ("d4d_all_away_dropped", PRES,
     "            and tracked_count > 0\n            and all_tracked_persons_away\n",
     "            and tracked_count > 0\n",
     "test_zone_hold_all_away_silent_with_stale_resident", ZT, "on"),
    # d4d_tracked_count_dropped is an EQUIVALENT mutant: the producer sets
    # all_tracked_persons_away True only when tracked_count > 0 (and the
    # away-veto kill switch coerces it False), so the `tracked_count > 0`
    # conjunct is defence in depth (plan §R3.6 spelling kept).
    ("d4d_override_not_skipped", PRES,
     "            and not overridden\n            and self._census_count == 0\n            and tracked_count > 0",
     "            and self._census_count == 0\n            and tracked_count > 0",
     "test_zone_hold_all_away_silent_under_override", ZT, "on"),
    ("d4d_sleep_not_excluded", PRES,
     "                HouseState.AWAY, HouseState.VACATION, HouseState.SLEEP,\n            )",
     "                HouseState.AWAY, HouseState.VACATION,\n            )",
     "test_zone_hold_all_away_silent_in_sleep", ZT, "on"),
    ("d4d_ble_not_excluded", PRES,
     "            and not any(\n                t._ble_occupied for t in self._zone_trackers.values()\n            )\n            and tier1_rooms",
     "            and tier1_rooms",
     "test_zone_hold_all_away_silent_with_ble_presence", ZT, "on"),
    ("d4d_census_dropped", PRES,
     "            and not overridden\n            and self._census_count == 0\n            and tracked_count > 0",
     "            and not overridden\n            and tracked_count > 0",
     "test_d4d_clock_resets_on_blip", ZT, "on"),
    ("d4d_episode_not_reset", PRES,
     "            self._zone_hold_all_away_since = None\n            self._zone_hold_all_away_fired = False\n            return",
     "            self._zone_hold_all_away_since = None\n            return",
     "test_zone_hold_all_away_rearms_after_clear", ZT, "on"),
    # ---- review D-M3: beta indoor input ----
    ("dm3_beta_indoor_not_fed", PRES,
     "            if not any_indoor_zone_occupied:\n                any_indoor_zone_occupied = any(",
     "            if False:\n                any_indoor_zone_occupied = any(",
     "test_beta_with_sleep_exempt_off_does_not_away_pinned_sleeper"),
    # ---- review D-M1 / B-M1: label captured before the await ----
    ("dm1_dispatch_reads_live_attr", PRES,
     "                    veto_path=tick_veto_path,\n", "",
     "test_concurrent_tick_cannot_overwrite_away_branch"),
    ("dm1_d7_ignores_captured_label", PRES,
     "                    veto_path if veto_path is not None\n                    else getattr(self, \"_veto_path\", \"none\")\n                ),",
     "                    getattr(self, \"_veto_path\", \"none\")\n                ),",
     "test_concurrent_tick_cannot_overwrite_away_branch"),
    # ---- trip-wire ----
    ("tripwire_call_removed", PRES,
     "            self._check_sleep_raw_hold(\n                current_state, any_zone_occupied, any_zone_occupied_for_empty,\n                now_local=now, machine=manager.house_state_machine,\n            )",
     "            pass",
     "test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound"),
    ("tripwire_window_gate_dropped", PRES,
     "        if engine._is_sleep_hour(now_local.hour):\n            return\n        window_end",
     "        if False:\n            return\n        window_end",
     "test_sleep_raw_hold_tripwire_silent_during_sleep_window"),
    ("tripwire_override_not_skipped", PRES,
     "            and not overridden\n            and self._census_count == 0\n            and not any_zone_occupied",
     "            and self._census_count == 0\n            and not any_zone_occupied",
     "test_sleep_raw_hold_tripwire_skips_override_1400_nap"),
    ("tripwire_override_not_skipped_2130", PRES,
     "            and not overridden\n            and self._census_count == 0\n            and not any_zone_occupied",
     "            and self._census_count == 0\n            and not any_zone_occupied",
     "test_sleep_raw_hold_tripwire_skips_override_2130_early_bedtime"),
    ("tripwire_entry_anchor_dropped", PRES,
     "            if entered > anchor:\n                anchor = entered",
     "            if False:\n                anchor = entered",
     "test_sleep_raw_hold_tripwire_anchors_at_sleep_entry"),
    ("tripwire_window_roll_dropped", PRES,
     "        if window_end > now_local:  # sleep_end later today -> yesterday's end",
     "        if False:  # roll removed",
     "test_sleep_raw_hold_tripwire_non_wrapping_window_rolls_back_a_day"),
    ("tripwire_severity_medium", PRES,
     "                    \"whether that room's sensor is holding a phantom\"\n                ),\n                severity=\"HIGH\",",
     "                    \"whether that room's sensor is holding a phantom\"\n                ),",
     "test_sleep_raw_hold_tripwire_fires_once_after_window_end_plus_bound"),
    ("stuck_signal_severity_kwarg_ignored", STUCK,
     "                getattr(Severity, severity) if severity else Severity.MEDIUM",
     "                Severity.MEDIUM",
     "test_fire_stuck_signal_severity_kwarg"),
    ("tripwire_episode_not_reset", PRES,
     "        if not held:\n            self._sleep_raw_hold_nm_fired = False",
     "        if not held:\n            pass",
     "test_sleep_raw_hold_tripwire_episode_resets_when_room_clears"),
    # ---- D3 (re-anchored) ----
    ("d3_note_call_removed", PRES,
     "            try:\n                self._note_away_entry(source, veto_path)\n",
     "            try:\n                pass\n",
     "test_last_away_branch_nobody_home"),
    ("d3_inference_branch_not_veto_path", PRES,
     "            branch = str(label or \"none\")",
     "            branch = \"inference\"",
     "test_last_away_branch_nobody_home"),
    ("d3_guest_corroborator_value", PRES,
     "            self._guest_reason = \"unidentified_corroborator_only\"",
     "            self._guest_reason = \"unidentified_persistent\"",
     "test_guest_reason_unidentified_and_none"),
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


import os  # noqa: E402

# Order-robustness check (review C): URA_DRILL_REVERSE=1 runs the drills in
# reverse. Every drill copies the tree to a private temp dir, so no drill
# can see another's mutant regardless of order.
_ORDER = list(reversed(DRILLS)) if os.environ.get("URA_DRILL_REVERSE") == "1" else DRILLS


def _norm(d):
    if len(d) == 5:
        return (*d, ANCHOR, "on")
    assert len(d) == 7 and d[6] in ("on", "off"), d[0]
    return d


@pytest.mark.parametrize(
    "file_,swap_from,swap_to,anchor,anchor_file,switch",
    [pytest.param(f, a, b, t, af, sw, id=i)
     for i, f, a, b, t, af, sw in (_norm(d) for d in _ORDER)],
)
def test_mutation_drill_goes_red(file_, swap_from, swap_to, anchor, anchor_file, switch):
    kwargs = dict(anchor_test_file=anchor_file, anchor_test_name=anchor,
                  expect="KILLED", timeout=300,
                  extra_pytest_args=("--per-entity-off",) if switch == "off" else ())
    if callable(swap_from):
        apply_mutation_in_sandbox(file_, mutator=swap_from, **kwargs)
    else:
        apply_mutation_in_sandbox(file_, swap_from=swap_from, swap_to=swap_to,
                                  **kwargs)
