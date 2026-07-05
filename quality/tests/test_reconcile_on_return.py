"""Reconcile-on-Return (v5.8.0, D2) — full acceptance test suite.

Covers every test_* named in PLANNING_reconcile_on_return.md §4:
D2.1 (scaffold), D2.2 (guards), D2.3 (happy path), D2.4 (diagnostics),
D2.5 (log line), D2.7 (coalesce+grace), D2.8 (zero DB writes), D2.9
(unsub/rebuild), D2.10 (branch-table parity), D2.11 (flap quarantine),
D2.12 (observability + Auto-Recovery switch).

These drive the PRODUCTION ActuatorReconciler through the fake HA layer in
_reconcile_harness (mocks only the HA boundary the reconciler imports).
"""

from __future__ import annotations

import re
from pathlib import Path

import _reconcile_harness as H  # noqa: F401 — installs HA mocks on import
from _reconcile_harness import (
    ActuatorReconciler,
    DesiredState,
    fire_available,
    make_env,
    make_event,
    run_pending_coalesce,
)

from custom_components.universal_room_automation.const import (
    CONF_ENTRY_LIGHT_ACTION,
    CONF_EXIT_LIGHT_ACTION,
    CONF_FAN_CONTROL_ENABLED,
    CONF_FAN_TEMP_THRESHOLD,
    CONF_FANS,
    CONF_LIGHTS,
    CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS,
    CONF_NIGHT_LIGHTS,
    LIGHT_ACTION_NONE,
    LIGHT_ACTION_TURN_OFF,
    LIGHT_ACTION_TURN_ON,
    LIGHT_ACTION_TURN_ON_IF_DARK,
    RECONCILE_DEBOUNCE_SECONDS,
    RECONCILE_FLAP_SENSITIVITY_BUCKETS,
    RECONCILE_FLAP_STABILITY_SECONDS,
    RECONCILE_FLAP_THRESHOLD,
    RECONCILE_MAX_PER_HOUR,
    STATE_ILLUMINANCE,
    STATE_OCCUPIED,
    STATE_TEMPERATURE,
)

MODULE_SRC = (
    Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
    / "actuator_reconciler.py"
).read_text()


def _occupied_dark_light_room(**extra):
    data = {
        CONF_LIGHTS: ["light.bedroom"],
        CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_TURN_ON_IF_DARK,
        CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF,
        "illuminance_threshold": 20,
    }
    data.update(extra)
    cdata = {STATE_OCCUPIED: True, STATE_ILLUMINANCE: 5}
    return make_env(data=data, coordinator_data=cdata)


# ===========================================================================
# D2.1 — scaffold + listener registration
# ===========================================================================


def test_actuator_reconciler_setup_subscribes_once():
    hass, coord, r = _occupied_dark_light_room()
    before = len(H.TRACK_CAPTURES)
    r.async_register_listeners()
    assert len(H.TRACK_CAPTURES) - before == 1
    assert len(r._unsub_reconciler_listeners) == 1


def test_actuator_reconciler_async_teardown_releases_listener():
    import asyncio

    hass, coord, r = _occupied_dark_light_room()
    r.async_register_listeners()
    unsub = r._unsub_reconciler_listeners[0]
    asyncio.get_event_loop().run_until_complete(r.async_teardown())
    assert unsub.called
    assert r._unsub_reconciler_listeners == []


def test_intent_resolver_returns_none_when_action_is_NONE():
    hass, coord, r = make_env(
        data={
            CONF_LIGHTS: ["light.bedroom"],
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_NONE,
            CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_NONE,
        },
        coordinator_data={STATE_OCCUPIED: True, STATE_ILLUMINANCE: 5},
    )
    assert r.resolve_desired_state("light.bedroom") is None


# ===========================================================================
# D2.2 — guard set
# ===========================================================================


def test_reconcile_skipped_when_manual_mode_on():
    hass, coord, r = _occupied_dark_light_room()
    coord._switch_states["manual_mode"] = True
    fire_available(r, "light.bedroom", hass)
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert r._last_skip_reason == "manual_mode"


def test_reconcile_skipped_during_boot_settle():
    hass, coord, r = _occupied_dark_light_room()
    coord._boot_settle_done = False
    fire_available(r, "light.bedroom", hass)
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert r._last_skip_reason == "boot_settle"


def test_reconcile_skipped_within_debounce_window():
    hass, coord, r = _occupied_dark_light_room()
    # First reconcile succeeds.
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1
    before = r._reconcile_debounced_count
    # Second edge within debounce window.
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1  # no new call
    assert r._reconcile_debounced_count == before + 1
    assert r._last_skip_reason == "debounce"


def test_reconcile_respects_per_hour_cap():
    hass, coord, r = _occupied_dark_light_room()
    now = r._now()
    # Pre-load the rate deque at the cap.
    from collections import deque

    r._reconcile_times["light.bedroom"] = deque([now] * RECONCILE_MAX_PER_HOUR)
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert r._last_skip_reason == "rate_cap"


def test_reconcile_skipped_when_no_data_yet():
    hass, coord, r = make_env(
        data={CONF_LIGHTS: ["light.bedroom"],
              CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_TURN_ON_IF_DARK},
        coordinator_data={},
    )
    fire_available(r, "light.bedroom", hass)
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert r._last_skip_reason == "no_data"


def test_reconcile_does_not_touch_covers_or_climate():
    hass, coord, r = make_env(
        data={
            CONF_LIGHTS: ["light.bedroom"],
            "covers": ["cover.blind"],
            "climate_entity": "climate.ac",
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_TURN_ON_IF_DARK,
        },
        coordinator_data={STATE_OCCUPIED: True, STATE_ILLUMINANCE: 5},
    )
    # Covers/climate are not tracked at all.
    assert "cover.blind" not in r._tracked_entities()
    assert "climate.ac" not in r._tracked_entities()
    fire_available(r, "cover.blind", hass)
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []


def test_reconcile_skipped_when_entity_is_flapping():
    hass, coord, r = _occupied_dark_light_room()
    r._flapping["light.bedroom"] = {"since": "x", "transition_count_at_entry": 5}
    r._flap_last_transition_ts["light.bedroom"] = r._now()
    fire_available(r, "light.bedroom", hass)
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert "light.bedroom" not in r._pending_reconcile


def test_reconcile_skipped_when_auto_recovery_off():
    hass, coord, r = _occupied_dark_light_room()
    coord._switch_states["auto_recovery"] = False
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert r._last_skip_reason == "auto_recovery_off"
    # would_reconcile still populated (D2.12).
    assert r._would_reconcile.get("light.bedroom") == "on"


# ===========================================================================
# D2.3 — live re-assert (lights + fans)
# ===========================================================================


def test_light_reconcile_turns_on_when_room_is_occupied_and_dark():
    hass, coord, r = _occupied_dark_light_room()
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1
    domain, service, data = coord.automation.service_calls[0]
    assert domain == "light" and service == "turn_on"
    assert data["entity_id"] == ["light.bedroom"]


def test_light_reconcile_turns_off_when_room_is_vacant():
    hass, coord, r = make_env(
        data={CONF_LIGHTS: ["light.bedroom"],
              CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF},
        coordinator_data={STATE_OCCUPIED: False, STATE_ILLUMINANCE: 5},
    )
    hass.states.set("light.bedroom", "on")
    fire_available(r, "light.bedroom", hass, new="on")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1
    domain, service, data = coord.automation.service_calls[0]
    assert domain == "light" and service == "turn_off"
    assert data["entity_id"] == ["light.bedroom"]


def test_light_reconcile_uses_night_brightness_when_in_sleep_mode():
    hass, coord, r = make_env(
        data={
            CONF_LIGHTS: ["light.bedroom", "light.night"],
            CONF_NIGHT_LIGHTS: ["light.night"],
            CONF_NIGHT_LIGHT_SLEEP_BRIGHTNESS: 12,
            "light_capabilities": "brightness",
        },
        coordinator_data={STATE_OCCUPIED: True, STATE_ILLUMINANCE: 5},
    )
    coord.automation._sleep = True
    hass.states.set("light.night", "off")
    fire_available(r, "light.night", hass, new="off")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1
    domain, service, data = coord.automation.service_calls[0]
    assert domain == "light" and service == "turn_on"
    assert data["brightness_pct"] == 12


def test_fan_reconcile_respects_hvac_managed_defer():
    hass, coord, r = make_env(
        data={CONF_FANS: ["fan.bedroom"], CONF_FAN_CONTROL_ENABLED: True,
              CONF_FAN_TEMP_THRESHOLD: 75},
        coordinator_data={STATE_OCCUPIED: True, STATE_TEMPERATURE: 80},
    )
    coord.automation._hvac_managing = True
    assert r.resolve_desired_state("fan.bedroom") is None


def test_fan_reconcile_off_when_vacant_or_below_threshold():
    # Occupied + cool (non-sleep) -> off (mirrors canonical temp handler).
    hass, coord, r = make_env(
        data={CONF_FANS: ["fan.bedroom"], CONF_FAN_CONTROL_ENABLED: True,
              CONF_FAN_TEMP_THRESHOLD: 75},
        coordinator_data={STATE_OCCUPIED: True, STATE_TEMPERATURE: 70},
    )
    desired = r.resolve_desired_state("fan.bedroom")
    assert desired is not None and desired.state == "off"
    # Vacant -> resolver DEFERS to the organic path (A-HIGH-2 vacancy-hold),
    # returning None rather than asserting off.
    coord.data = {STATE_OCCUPIED: False, STATE_TEMPERATURE: 90}
    assert r.resolve_desired_state("fan.bedroom") is None


# ===========================================================================
# D2.4 — diagnostics surface
# ===========================================================================


def test_diagnostic_attrs_present_after_one_reconcile():
    hass, coord, r = _occupied_dark_light_room()
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    diag = r.diagnostics()
    assert diag["reconciles_today"] == 1
    assert len(diag["recent_reconciles"]) == 1
    entry = diag["recent_reconciles"][0]
    assert set(entry.keys()) == {
        "entity_id", "ts_iso", "desired_state", "reason", "result",
    }
    assert diag["flapping_entities"] == []


def test_diagnostic_attrs_degrade_gracefully_when_no_actuators_configured():
    hass, coord, r = make_env(data={}, coordinator_data={STATE_OCCUPIED: True})
    # No lights/fans configured — reconciler exists but tracks nothing.
    assert r._tracked_entities() == []
    diag = r.diagnostics()
    assert diag["reconciles_today"] == 0


# ===========================================================================
# D2.5 — canonical log line
# ===========================================================================


def test_reconcile_emits_canonical_log_line(caplog):
    import logging

    caplog.set_level(logging.INFO)
    hass, coord, r = _occupied_dark_light_room()
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert any(m.startswith("reconciled ") for m in caplog.messages)


# ===========================================================================
# D2.7 — coalesce + grace (CORE)
# ===========================================================================


def _five_light_room():
    lights = [f"light.l{i}" for i in range(5)]
    hass, coord, r = make_env(
        data={CONF_LIGHTS: lights,
              CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_TURN_ON},
        coordinator_data={STATE_OCCUPIED: True, STATE_ILLUMINANCE: 5},
    )
    for eid in lights:
        hass.states.set(eid, "off")
    return hass, coord, r, lights


def test_batch_reconnect_collapses_to_one_resolver_pass():
    hass, coord, r, lights = _five_light_room()
    # 5 edges arrive within the same window (no timer fired yet).
    for eid in lights:
        r._handle_state_change(make_event(eid, "unavailable", "off"))
    # Exactly one coalesce timer armed.
    assert len(H.CALL_LATER_CAPTURES) == 1
    assert r._reconcile_coalesced_count == 4
    run_pending_coalesce(hass)
    # One service call per light (single pass, single timer).
    assert len(coord.automation.service_calls) == 5


def test_coalesce_is_per_room_not_global():
    hass1, coord1, r1, lights1 = _five_light_room()
    hass2, coord2, r2, lights2 = _five_light_room()
    r1._handle_state_change(make_event(lights1[0], "unavailable", "off"))
    r2._handle_state_change(make_event(lights2[0], "unavailable", "off"))
    # Each reconciler armed its own timer independently.
    assert r1._pending_reconcile == {lights1[0]}
    assert r2._pending_reconcile == {lights2[0]}


def test_post_boot_grace_suppresses_trailing_transitions():
    hass, coord, r = _occupied_dark_light_room()
    hass.states.set("light.bedroom", "off")
    r.note_boot_settle_released()  # arms grace, _grace_active True
    assert r._grace_active is True
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert r._last_skip_reason == "boot_settle"
    # End the grace window (fire the grace timer), then a new edge reconciles.
    grace = [c for c in H.CALL_LATER_CAPTURES]
    for c in grace:
        c["cb"](None)
    H.CALL_LATER_CAPTURES.clear()
    assert r._grace_active is False
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1


def test_reload_path_grace_active_immediately_after_construction():
    """D-HIGH clause-3 grace leak: on the RELOAD path (hass.is_running True →
    boot-settle born True, note_boot_settle_released never fires against a real
    edge), a mid-flight unavailable→available must NOT dispatch a service call
    with zero grace. The implicit construction-age grace covers it.
    """
    hass, coord, r = _occupied_dark_light_room()
    # Undo the harness back-dating so this test sees a freshly-constructed
    # reconciler (simulates the reload instant).
    r._created_monotonic = r._now()
    # Boot-settle is born True (reload path), but grace was NEVER explicitly
    # armed — the implicit construction-age grace must still hold.
    assert r._boot_settle_done() is True
    assert r._in_post_boot_grace() is True
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert r._last_skip_reason == "boot_settle"


def test_boot_storm_release_shape():
    # 20 entities across 5 rooms reconnect within 1s of release.
    total_passes = 0
    for _room in range(5):
        hass, coord, r, lights = _five_light_room()
        lights4 = lights[:4]
        for eid in lights4:
            r._handle_state_change(make_event(eid, "unavailable", "off"))
        # At most ONE coalesce timer (== one resolver pass) per room.
        assert len(H.CALL_LATER_CAPTURES) == 1
        total_passes += len(H.CALL_LATER_CAPTURES)
    assert total_passes <= 5


# ===========================================================================
# D2.8 — zero DB writes (CORE)
# ===========================================================================


def test_reconcile_module_does_not_import_database_daos():
    assert "from .database" not in MODULE_SRC
    assert "import database" not in MODULE_SRC
    assert not re.search(r"\bdatabase\.", MODULE_SRC)


def test_reconcile_burst_no_synchronous_db_writes():
    hass, coord, r = _occupied_dark_light_room()
    # Instrument a synchronous-write spy on hass.data database (there is none;
    # the module must never reach for it). Also assert no DAO surface touched.
    hass.data["universal_room_automation"]["database"] = _DBSpy()
    for i in range(20):
        hass.states.set("light.bedroom", "off")
        # Advance the debounce clock so each edge is a fresh reconcile.
        r._last_reconcile_edge.pop("light.bedroom", None)
        r._reconcile_times.pop("light.bedroom", None)
        fire_available(r, "light.bedroom", hass, new="off")
        run_pending_coalesce(hass)
    assert hass.data["universal_room_automation"]["database"].writes == 0


class _DBSpy:
    def __init__(self):
        self.writes = 0

    def __getattr__(self, name):
        def _spy(*a, **k):
            self.writes += 1
        return _spy


def test_reconcile_telemetry_routes_through_batched_activity_logger():
    hass, coord, r = _occupied_dark_light_room()
    logger = _ActivitySpy()
    hass.data["universal_room_automation"]["activity_logger"] = logger
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert logger.log_calls == 1


class _ActivitySpy:
    def __init__(self):
        self.log_calls = 0

    async def log(self, **kwargs):
        self.log_calls += 1


# ===========================================================================
# D2.9 — unsub list + rebuild-hook re-arm (CORE)
# ===========================================================================


def test_reconciler_listener_survives_subscription_rebuild():
    hass, coord, r = _occupied_dark_light_room()
    r.async_register_listeners()
    first_unsub = r._unsub_reconciler_listeners[0]
    # Simulate a rebuild: re-register drains + re-arms.
    r.async_register_listeners()
    assert first_unsub.called  # old listener drained
    assert len(r._unsub_reconciler_listeners) == 1
    # A new edge post-rebuild still triggers reconcile.
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1


def test_reconciler_listener_survives_options_flow_reload_simulation():
    hass, coord, r = _occupied_dark_light_room()
    r.async_register_listeners()
    # Options save -> rebuild hook re-arms.
    r.async_register_listeners()
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1


def test_rearm_is_wired_into_update_signal_subscriptions_not_first_refresh():
    """B-HIGH-1 / D2.9: the reconciler re-arm MUST live at the top of the
    room coordinator's _update_signal_subscriptions rebuild hook, so the
    in-place options-save rebuild path re-arms too (not only first_refresh).

    This is a source-authority guard: it asserts the wiring is inside the
    correct method. A regression that moves the re-arm back into
    async_config_entry_first_refresh (only) would leave the in-place rebuild
    path orphaning the listener against the OLD entity set (Bug Class #50).
    """
    coord_src = (
        Path(__file__).resolve().parents[2]
        / "custom_components" / "universal_room_automation" / "coordinator.py"
    ).read_text()
    # Locate the _update_signal_subscriptions method body.
    marker = "def _update_signal_subscriptions(self)"
    idx = coord_src.index(marker)
    # Grab a window of the method body (next ~2000 chars covers the top).
    body = coord_src[idx:idx + 2000]
    # Pin the EXACT guard form, not just the call substring. A source-grep for
    # the bare call would still pass if a regression neutered it behind a
    # disabling guard (e.g. `if False and getattr(...)`) while leaving the
    # string present — a semantic neuter the orchestrator's mutation pass
    # actually hit. Asserting the exact two-line snippet rejects that class.
    expected = (
        'if getattr(self, "_actuator_reconciler", None) is not None:\n'
        "            self._actuator_reconciler.async_register_listeners()"
    )
    assert expected in body, (
        "reconciler re-arm must be inside _update_signal_subscriptions as an "
        "unconditional (reconciler-presence-guarded) call — not deleted, "
        "moved to first_refresh, or neutered behind a disabling guard"
    )


def test_rearm_clears_stale_coalesce_and_survives_changed_entity_set():
    """B-MED-3: re-arm on the same instance cancels a pending coalesce timer
    and clears the pending set, so a stale timer can't fire against an entity
    set that changed during an in-place rebuild.
    """
    hass, coord, r = _occupied_dark_light_room()
    r.async_register_listeners()
    # Open a coalesce window (pending set + timer armed).
    hass.states.set("light.bedroom", "off")
    r._handle_state_change(make_event("light.bedroom", "unavailable", "off"))
    assert r._pending_reconcile == {"light.bedroom"}
    assert r._coalesce_unsub is not None
    # Simulate an in-place rebuild that changed the tracked entity set.
    coord.entry.data[CONF_LIGHTS] = ["light.newbedroom"]
    r.async_register_listeners()
    # Stale pending set + timer are cleared.
    assert r._pending_reconcile == set()
    assert r._coalesce_unsub is None


def test_reconciler_async_teardown_drains_all_unsubs():
    import asyncio

    hass, coord, r = _occupied_dark_light_room()
    r.async_register_listeners()
    asyncio.get_event_loop().run_until_complete(r.async_teardown())
    assert r._unsub_reconciler_listeners == []


# ===========================================================================
# D2.10 — branch-table parity (CORE, GATING)
# ===========================================================================


def _canonical_light_decision(occupied, sleep, is_dark, entry_action,
                              exit_action, is_night):
    """Reference decision mirroring _control_lights_entry/exit for ONE entity.

    Returns "on" / "off" / None.
    """
    if sleep:
        # night-lights-only branch requires at least one night light; our
        # parity cells always have night_lights present when is_night True.
        return "on" if is_night else "off"
    if occupied:
        if entry_action == LIGHT_ACTION_NONE:
            return None
        should_on = entry_action == LIGHT_ACTION_TURN_ON or (
            entry_action == LIGHT_ACTION_TURN_ON_IF_DARK and is_dark
        )
        return "on" if should_on else None
    # vacant
    if exit_action == LIGHT_ACTION_TURN_OFF:
        return "off"
    return None


def test_resolver_branch_table_parity_with_canonical_handlers():
    for occupied in (True, False):
        for sleep in (True, False):
            for is_dark in (True, False):
                for entry_action in (
                    LIGHT_ACTION_TURN_ON, LIGHT_ACTION_TURN_ON_IF_DARK,
                    LIGHT_ACTION_NONE,
                ):
                    for exit_action in (LIGHT_ACTION_TURN_OFF, LIGHT_ACTION_NONE):
                        for is_night in (True, False):
                            night = ["light.bedroom"] if is_night else ["light.other"]
                            lights = ["light.bedroom", "light.other"]
                            illum = 5 if is_dark else 500
                            hass, coord, r = make_env(
                                data={
                                    CONF_LIGHTS: lights,
                                    CONF_NIGHT_LIGHTS: night,
                                    CONF_ENTRY_LIGHT_ACTION: entry_action,
                                    CONF_EXIT_LIGHT_ACTION: exit_action,
                                    "illuminance_threshold": 20,
                                },
                                coordinator_data={
                                    STATE_OCCUPIED: occupied,
                                    STATE_ILLUMINANCE: illum,
                                },
                            )
                            coord.automation._sleep = sleep
                            desired = r.resolve_desired_state("light.bedroom")
                            got = desired.state if desired else None
                            expected = _canonical_light_decision(
                                occupied, sleep, is_dark, entry_action,
                                exit_action, is_night,
                            )
                            assert got == expected, (
                                f"cell occ={occupied} sleep={sleep} "
                                f"dark={is_dark} entry={entry_action} "
                                f"exit={exit_action} night={is_night}: "
                                f"got {got} expected {expected}"
                            )


def test_resolver_none_for_alert_lights_only_entity():
    """A-CRIT-1 gate: alert_lights are NOT in the resolver control surface.

    Canonical _control_lights_entry/_control_lights_exit only drive CONF_LIGHTS
    (+ CONF_NIGHT_LIGHTS in sleep). An alert-lights-only entity must never be
    tracked or given an opinion.
    """
    from custom_components.universal_room_automation.const import (
        CONF_ALERT_LIGHTS,
    )

    hass, coord, r = make_env(
        data={
            CONF_ALERT_LIGHTS: ["light.alert"],
            CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_TURN_ON,
            CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF,
        },
        coordinator_data={STATE_OCCUPIED: True, STATE_ILLUMINANCE: 5},
    )
    assert "light.alert" not in r._tracked_entities()
    assert r.resolve_desired_state("light.alert") is None


def test_resolver_none_for_night_light_only_entity_on_vacant_exit():
    """A-HIGH-1 gate: canonical _control_lights_exit turns off CONF_LIGHTS only.

    A night_lights-only entity (NOT in CONF_LIGHTS) is never turned off on exit
    by canonical, so the resolver must return None (not 'off') for it when the
    room is vacant.
    """
    hass, coord, r = make_env(
        data={
            CONF_LIGHTS: ["light.regular"],
            CONF_NIGHT_LIGHTS: ["light.night"],
            CONF_EXIT_LIGHT_ACTION: LIGHT_ACTION_TURN_OFF,
        },
        coordinator_data={STATE_OCCUPIED: False, STATE_ILLUMINANCE: 5},
    )
    # night-only entity on vacant exit -> None (canonical doesn't touch it).
    assert r.resolve_desired_state("light.night") is None
    # regular light (in CONF_LIGHTS) on vacant exit -> off.
    desired = r.resolve_desired_state("light.regular")
    assert desired is not None and desired.state == "off"


def _canonical_fan_decision(occupied, temp_above, hvac_managing, fan_enabled,
                            sleep):
    """Reference decision for a TEMPERATURE fan (CONF_FANS).

    A-HIGH-2: the resolver defers to the organic temp-fan path (returns None)
    whenever sleep mode is active (canonical applies FAN_SLEEP_OFF/REDUCE which
    the resolver cannot reproduce) OR the room is vacant (a fan_vacancy_hold
    window may be holding the fan ON — the resolver has no live view of it). The
    resolver only asserts an opinion on the plain OCCUPIED, non-sleep cells:
    on when hot, off when cool.
    """
    if not fan_enabled:
        return None
    if hvac_managing:
        return None
    if sleep:
        return None  # defer — sleep policy is organic-only
    if not occupied:
        return None  # defer — vacancy-hold window may be active
    return "on" if temp_above else "off"


def test_resolver_fan_branch_table_parity_with_temperature_handler():
    for occupied in (True, False):
        for temp_above in (True, False):
            for hvac_managing in (True, False):
                for fan_enabled in (True, False):
                    for sleep in (True, False):
                        temp = 90 if temp_above else 60
                        hass, coord, r = make_env(
                            data={
                                CONF_FANS: ["fan.bedroom"],
                                CONF_FAN_CONTROL_ENABLED: fan_enabled,
                                CONF_FAN_TEMP_THRESHOLD: 75,
                            },
                            coordinator_data={
                                STATE_OCCUPIED: occupied,
                                STATE_TEMPERATURE: temp,
                            },
                        )
                        coord.automation._hvac_managing = hvac_managing
                        coord.automation._sleep = sleep
                        desired = r.resolve_desired_state("fan.bedroom")
                        got = desired.state if desired else None
                        expected = _canonical_fan_decision(
                            occupied, temp_above, hvac_managing, fan_enabled,
                            sleep,
                        )
                        assert got == expected, (
                            f"occ={occupied} hot={temp_above} "
                            f"hvac={hvac_managing} en={fan_enabled} "
                            f"sleep={sleep}: got {got} expected {expected}"
                        )


def test_resolver_fan_none_for_humidity_fan():
    """A-CRIT-2 gate: humidity fans are OUT of the resolver's opinion surface.

    They are driven solely by handle_humidity_based_fan_control (humidity spike
    state machine) — the resolver must never assert a temperature-derived
    opinion on them.
    """
    from custom_components.universal_room_automation.const import (
        CONF_HUMIDITY_FANS,
    )

    hass, coord, r = make_env(
        data={
            CONF_HUMIDITY_FANS: ["fan.exhaust"],
            CONF_FAN_CONTROL_ENABLED: True,
            CONF_FAN_TEMP_THRESHOLD: 75,
        },
        coordinator_data={STATE_OCCUPIED: True, STATE_TEMPERATURE: 90},
    )
    # Humidity fan is not even tracked (excluded from _FAN_KEYS)...
    assert "fan.exhaust" not in r._tracked_entities()
    # ...and if resolved directly, returns None (belt-and-braces guard).
    assert r.resolve_desired_state("fan.exhaust") is None


def test_resolver_fan_none_under_sleep_and_vacancy_hold():
    """A-HIGH-2 gate: sleep-active and vacant cells defer to organic (None)."""
    # Sleep active, occupied, hot -> defer (canonical would apply sleep policy).
    hass, coord, r = make_env(
        data={CONF_FANS: ["fan.bedroom"], CONF_FAN_CONTROL_ENABLED: True,
              CONF_FAN_TEMP_THRESHOLD: 75},
        coordinator_data={STATE_OCCUPIED: True, STATE_TEMPERATURE: 90},
    )
    coord.automation._sleep = True
    assert r.resolve_desired_state("fan.bedroom") is None
    # Vacant (vacancy-hold window may be active) -> defer.
    coord.automation._sleep = False
    coord.data = {STATE_OCCUPIED: False, STATE_TEMPERATURE: 90}
    assert r.resolve_desired_state("fan.bedroom") is None


def test_resolver_none_on_no_data_is_intentional():
    hass, coord, r = make_env(
        data={CONF_LIGHTS: ["light.bedroom"],
              CONF_ENTRY_LIGHT_ACTION: LIGHT_ACTION_TURN_ON},
        coordinator_data={},  # no STATE_OCCUPIED key
    )
    assert r.resolve_desired_state("light.bedroom") is None


# ===========================================================================
# D2.11 — flap detector + quarantine
# ===========================================================================


def _flap(r, entity_id, hass):
    for _ in range(RECONCILE_FLAP_THRESHOLD):
        fire_available(r, entity_id, hass, new="on")


def test_flap_enters_quarantine_at_threshold_within_window():
    hass, coord, r = _occupied_dark_light_room()
    _flap(r, "light.bedroom", hass)
    assert "light.bedroom" in r._flapping
    ids = {f["entity_id"] for f in r.flapping_entities()}
    assert "light.bedroom" in ids
    detail = r.flapping_detail("light.bedroom")
    assert detail is not None and "transition_count" in detail


def test_flap_zero_reconcile_service_calls_while_flagged():
    hass, coord, r = _occupied_dark_light_room()
    _flap(r, "light.bedroom", hass)
    coord.automation.service_calls.clear()
    for _ in range(10):
        fire_available(r, "light.bedroom", hass, new="on")
        run_pending_coalesce(hass)
    assert coord.automation.service_calls == []


def test_flap_release_requires_stability_window_not_bare_timer():
    hass, coord, r = _occupied_dark_light_room()
    _flap(r, "light.bedroom", hass)
    assert "light.bedroom" in r._flapping
    # Advance clock by stability-1 with a transition mid-window -> stays.
    now = r._now()
    r._flap_last_transition_ts["light.bedroom"] = now - (
        RECONCILE_FLAP_STABILITY_SECONDS - 1
    )
    r.check_quarantine_release()
    assert "light.bedroom" in r._flapping
    # Full stability window, zero transitions -> released.
    r._flap_last_transition_ts["light.bedroom"] = now - (
        RECONCILE_FLAP_STABILITY_SECONDS + 1
    )
    hass.states.set("light.bedroom", "off")
    r.check_quarantine_release()
    assert "light.bedroom" not in r._flapping


def test_flap_release_runs_exactly_one_reconcile_pass():
    hass, coord, r = _occupied_dark_light_room()
    _flap(r, "light.bedroom", hass)
    coord.automation.service_calls.clear()
    r._flap_last_transition_ts["light.bedroom"] = r._now() - (
        RECONCILE_FLAP_STABILITY_SECONDS + 1
    )
    hass.states.set("light.bedroom", "off")
    r.check_quarantine_release()
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1


def test_flap_hysteresis_no_oscillation():
    hass, coord, r = _occupied_dark_light_room()
    _flap(r, "light.bedroom", hass)
    r._flap_last_transition_ts["light.bedroom"] = r._now() - (
        RECONCILE_FLAP_STABILITY_SECONDS + 1
    )
    hass.states.set("light.bedroom", "off")
    r.check_quarantine_release()
    assert "light.bedroom" not in r._flapping
    # A single follow-up edge must NOT immediately re-quarantine (window purged).
    fire_available(r, "light.bedroom", hass, new="off")
    assert "light.bedroom" not in r._flapping


def test_flap_state_not_persisted_across_restart():
    hass, coord, r = _occupied_dark_light_room()
    _flap(r, "light.bedroom", hass)
    assert r._flapping
    # Fresh construction == restart with zero memory.
    r2 = ActuatorReconciler(coord)
    assert r2._flap_windows == {}
    assert r2._flapping == {}
    assert r2._flap_last_transition_ts == {}


def test_flap_window_pruning_rolling():
    hass, coord, r = _occupied_dark_light_room()
    from collections import deque

    # 3 edges spread beyond threshold count but pruning keeps < threshold in
    # window: inject old timestamps that should be pruned.
    now = r._now()
    r._flap_windows["light.bedroom"] = deque([now - 1000, now - 900, now - 800])
    fire_available(r, "light.bedroom", hass, new="on")
    # Old ones pruned (>120s), only the fresh edge remains -> below threshold.
    assert "light.bedroom" not in r._flapping


def test_flap_detector_records_edge_before_guard_chain():
    hass, coord, r = _occupied_dark_light_room()
    coord._boot_settle_done = False  # a guard that would skip reconcile
    fire_available(r, "light.bedroom", hass, new="on")
    # Edge still recorded despite boot-settle skip.
    assert "light.bedroom" in r._flap_windows
    assert len(r._flap_windows["light.bedroom"]) == 1


# ===========================================================================
# D2.12 — observability + control surface
# ===========================================================================


def test_auto_recovery_switch_off_suppresses_reconcile():
    hass, coord, r = _occupied_dark_light_room()
    coord._switch_states["auto_recovery"] = False
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert coord.automation.service_calls == []
    assert r._would_reconcile.get("light.bedroom") == "on"


def test_auto_recovery_switch_on_reconciles_normally():
    hass, coord, r = _occupied_dark_light_room()
    coord._switch_states["auto_recovery"] = True
    hass.states.set("light.bedroom", "off")
    fire_available(r, "light.bedroom", hass, new="off")
    run_pending_coalesce(hass)
    assert len(coord.automation.service_calls) == 1


def test_room_reconcile_sensor_shape():
    hass, coord, r = _occupied_dark_light_room()
    attrs = r.room_sensor_attrs()
    assert set(attrs.keys()) == {
        "last_reconcile", "reconciles_today", "coalesced_count",
        "last_skip_reason", "would_reconcile",
    }
    assert isinstance(attrs["would_reconcile"], dict)


def test_reconcile_health_sensor_aggregates_across_rooms():
    # Build 3 reconcilers directly and aggregate manually (sensor logic).
    envs = []
    for i in range(3):
        hass, coord, r = _occupied_dark_light_room()
        coord.entry.data["room_name"] = f"Room{i}"
        envs.append((hass, coord, r))
    # Room0: one reconcile. Room1: quarantined. Room2: auto-recovery off.
    h0, c0, r0 = envs[0]
    h0.states.set("light.bedroom", "off")
    fire_available(r0, "light.bedroom", h0, new="off")
    run_pending_coalesce(h0)
    _flap(envs[1][2], "light.bedroom", envs[1][0])
    envs[2][1]._switch_states["auto_recovery"] = False

    total = sum(r.reconciles_today for _, _, r in envs)
    quarantined = sum(1 for _, _, r in envs if r.flapping_entities())
    ar_off = [c.entry.data["room_name"] for _, c, r in envs
              if not r._auto_recovery_on()]
    assert total == 1
    assert quarantined == 1
    assert ar_off == ["Room2"]


def test_flap_sensitivity_maps_to_const_triple():
    for bucket, expected in RECONCILE_FLAP_SENSITIVITY_BUCKETS.items():
        hass, coord, r = make_env(
            data={CONF_LIGHTS: ["light.bedroom"], "flap_sensitivity": bucket},
        )
        assert r._flap_triple() == expected
    # relaxed / normal / aggressive concretely.
    hass, coord, r = make_env(
        data={CONF_LIGHTS: ["light.bedroom"], "flap_sensitivity": "relaxed"},
    )
    assert r._flap_triple() == (6, 180, 900)


def test_auto_recovery_switch_restores_across_restart():
    # Switch OFF -> restart (last_state "off") -> stays OFF. The reconciler
    # reads the gate via the room switch state; verify the OFF gate is honored.
    hass, coord, r = _occupied_dark_light_room()
    coord._switch_states["auto_recovery"] = False
    assert r._auto_recovery_on() is False
    coord._switch_states["auto_recovery"] = True
    assert r._auto_recovery_on() is True


def _load_real_auto_recovery_switch():
    """Execute the REAL AutoRecoverySwitch class body (switch.py) in a namespace
    with mocked bases, so tests drive PRODUCTION async_added_to_hass — not a
    local re-implementation of the guard (C-GAP-1).
    """
    import ast
    import asyncio
    import inspect
    import logging as _logging
    from unittest.mock import MagicMock

    switch_src = (
        Path(__file__).resolve().parents[2]
        / "custom_components" / "universal_room_automation" / "switch.py"
    ).read_text()
    tree = ast.parse(switch_src)
    class_node = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "AutoRecoverySwitch"
    )
    class_src = ast.get_source_segment(switch_src, class_node)

    # Mocked bases: capture __init__ so super().__init__ works; provide
    # async_get_last_state / async_write_ha_state on the base.
    class _Base:
        def __init__(self, coordinator, *a, **k):
            self.coordinator = coordinator

        async def async_added_to_hass(self):
            return None

        async def async_get_last_state(self):
            return self._last_state_stub

        def async_write_ha_state(self):
            return None

    class _SwitchEntity:
        pass

    class _RestoreEntity:
        pass

    ns = {
        "UniversalRoomEntity": _Base,
        "SwitchEntity": _SwitchEntity,
        "RestoreEntity": _RestoreEntity,
        "_LOGGER": _logging.getLogger("test"),
    }
    exec(compile(class_src, "switch_autorecovery", "exec"), ns)
    return ns["AutoRecoverySwitch"], asyncio, MagicMock, inspect


def test_auto_recovery_switch_unavailable_last_state_falls_back_to_on():
    """C-GAP-1: drive the REAL AutoRecoverySwitch.async_added_to_hass with each
    of unavailable / unknown / None / off / on last-states and assert the
    Bug Class #52 guard (unavailable never coerces to OFF).
    """
    Switch, asyncio, MagicMock, _ = _load_real_auto_recovery_switch()
    coord = MagicMock()
    coord.entry.data = {"room_name": "Bedroom"}

    def _restore_result(last_state):
        sw = Switch(coord)
        sw._last_state_stub = last_state
        asyncio.get_event_loop().run_until_complete(sw.async_added_to_hass())
        return sw._attr_is_on

    assert _restore_result(MagicMock(state="unavailable")) is True
    assert _restore_result(MagicMock(state="unknown")) is True
    assert _restore_result(None) is True
    assert _restore_result(MagicMock(state="off")) is False
    assert _restore_result(MagicMock(state="on")) is True


def test_auto_recovery_switch_restore_guard_is_load_bearing():
    """C-GAP-1 counter-proof: if the guard were mutated to coerce
    unavailable->OFF, the unavailable case would return False. Confirm the
    production source does NOT do that (the ('on','off') membership guard is
    present), so the test above is not vacuously passing.
    """
    switch_src = (
        Path(__file__).resolve().parents[2]
        / "custom_components" / "universal_room_automation" / "switch.py"
    ).read_text()
    # The load-bearing guard: only adopt a concrete on/off last-state.
    idx = switch_src.index("class AutoRecoverySwitch")
    body = switch_src[idx:idx + 2400]
    assert 'last_state.state in ("on", "off")' in body


def test_would_reconcile_populated_for_quarantined_entity():
    hass, coord, r = _occupied_dark_light_room()
    _flap(r, "light.bedroom", hass)
    assert "light.bedroom" in r._flapping
    # A subsequent edge while quarantined: would_reconcile still computed,
    # last_skip_reason == flapping.
    fire_available(r, "light.bedroom", hass, new="on")
    assert r._would_reconcile.get("light.bedroom") == "on"
    assert r._last_skip_reason == "flapping"
