"""Tests for the boot re-resolve fix on CameraPersonDetectedSensor.

Bug: at HA startup, `CameraPersonDetectedSensor.async_added_to_hass` runs
before Frigate MQTT sensors and UniFi Protect finish setup. The initial
`_get_fusion()` resolves to zero fusions / zero source entity_ids, caches
`self._fusions = []` (truthy-check `is not None` prevents recompute), and
`_subscribe_sources()` returns early because `eids` is empty. The fused
sensor stays inert (attribute `agreement=no_sources`) and the fan-veto
camera leg reads OFF until a manual config-entry reload. Live-reproduced
in v5.46.0; see docs/readmes/README_v5.46.0.md.

Fix: after the initial `_subscribe_sources()` call, if configured
`CONF_ROOM_CAMERAS` is non-empty AND the resolution came back empty AND
`hass.is_running` is False, register a one-shot listener on
`EVENT_HOMEASSISTANT_STARTED` that clears the cache and re-runs
`_subscribe_sources()`. Cleanup via `async_on_remove` mirrors
`_unsub_state` / `_unsub_lifecycle`.

Test strategy (Bug Class #62 disclosure): binary_sensor.py's top-level
imports (RestoreEntity, CoordinatorEntity, typed generics) exceed what
the shared `_provenance_harness` mocks provide, so a real instantiation
of `CameraPersonDetectedSensor` is INFEASIBLE without materially
expanding the harness. These tests therefore use source-level anchors on
the exact fix surface — a real code mutation that removes any of the
guarded conditions, the `async_listen_once` call, the cache clear + re-
call, or the cleanup wiring will fail a specific anchor. This mirrors
the pattern used by test_comfort_fan_away_veto.py T10 (source-anchored
per-site routing).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BINARY_SENSOR = (
    REPO_ROOT / "custom_components/universal_room_automation/binary_sensor.py"
).read_text()


# ---------------------------------------------------------------------------
# Anchor helpers
# ---------------------------------------------------------------------------

def _class_body() -> str:
    """Return only the CameraPersonDetectedSensor class body slice.

    Prevents false-positive matches from unrelated classes further down
    the file that also cleanup unsubs.
    """
    marker = "class CameraPersonDetectedSensor("
    start = BINARY_SENSOR.index(marker)
    # next top-level class begins with 'class '
    end = BINARY_SENSOR.index("\nclass ", start + len(marker))
    return BINARY_SENSOR[start:end]


CLASS_BODY = _class_body()


# ---------------------------------------------------------------------------
# T1: __init__ initializes the new unsub slot
# ---------------------------------------------------------------------------

def test_init_declares_unsub_started_slot():
    """__init__ must declare self._unsub_started = None so cleanup can
    safely test-and-unsub without AttributeError paths."""
    assert "self._unsub_started = None" in CLASS_BODY, (
        "CameraPersonDetectedSensor.__init__ must initialize "
        "self._unsub_started = None"
    )


# ---------------------------------------------------------------------------
# T2: boot re-resolve — empty resolution + not running → listener registered
# ---------------------------------------------------------------------------

def test_boot_reresolve_registers_started_listener_when_empty_and_booting():
    """The boot re-resolve block must:
       - Guard on CONF_ROOM_CAMERAS non-empty (room_cams_boot).
       - Guard on empty resolution (empty_resolve = not fusions or not sources).
       - Guard on `hass.is_running` False (ha_running).
       - Register async_listen_once on EVENT_HOMEASSISTANT_STARTED.
       - Store the returned unsub in self._unsub_started.
    """
    assert "room_cams_boot = config_boot.get(CONF_ROOM_CAMERAS" in CLASS_BODY
    assert (
        "empty_resolve = not self._fusions or not self._source_entity_ids"
        in CLASS_BODY
    )
    assert 'ha_running = bool(getattr(self.hass, "is_running", False))' in CLASS_BODY
    assert "if room_cams_boot and empty_resolve and not ha_running:" in CLASS_BODY
    assert "EVENT_HOMEASSISTANT_STARTED" in CLASS_BODY
    assert "self.hass.bus.async_listen_once(" in CLASS_BODY
    assert "self._unsub_started = self.hass.bus.async_listen_once(" in CLASS_BODY


# ---------------------------------------------------------------------------
# T3: the started callback clears the cache AND re-subscribes AND logs INFO
# ---------------------------------------------------------------------------

def test_boot_reresolve_callback_clears_cache_and_resubscribes():
    """The started callback must clear _fusions/_source_entity_ids before
    re-calling _subscribe_sources, then log a re-resolved INFO line."""
    # cache clear + re-subscribe within the started callback
    started_cb_start = CLASS_BODY.index("def _on_ha_started(")
    started_cb_end = CLASS_BODY.index(
        "self._unsub_started = self.hass.bus.async_listen_once("
    )
    started_cb = CLASS_BODY[started_cb_start:started_cb_end]
    assert "self._fusions = None" in started_cb
    assert "self._source_entity_ids = []" in started_cb
    assert "_subscribe_sources()" in started_cb
    assert "re-resolved after HA" in started_cb
    assert "_LOGGER.info(" in started_cb


# ---------------------------------------------------------------------------
# T4: non-empty resolution → no started listener (guard prevents entry)
# ---------------------------------------------------------------------------

def test_no_started_listener_when_resolution_non_empty():
    """The whole boot-reresolve block sits under
       `if room_cams_boot and empty_resolve and not ha_running:` — so a
       non-empty initial resolution cannot register the listener. Anchor
       that the async_listen_once call is INSIDE this guard, not at the
       top of async_added_to_hass."""
    guard = "if room_cams_boot and empty_resolve and not ha_running:"
    guard_pos = CLASS_BODY.index(guard)
    listen_pos = CLASS_BODY.index("self._unsub_started = self.hass.bus.async_listen_once(")
    assert guard_pos < listen_pos, (
        "async_listen_once must be nested under the empty-resolve boot guard"
    )
    # And it must be reached ONLY through that guard — no other
    # async_listen_once call exists in the class body.
    assert CLASS_BODY.count("async_listen_once(") == 1


# ---------------------------------------------------------------------------
# T5: empty resolution + hass ALREADY running → no listener (guard blocks)
# ---------------------------------------------------------------------------

def test_no_started_listener_when_hass_already_running():
    """The `not ha_running` clause is the discriminator between the boot
    path (register) and the options-updated-post-boot path (skip; the
    lifecycle signal already covers it)."""
    assert "and not ha_running:" in CLASS_BODY, (
        "guard must include `not ha_running` — otherwise options-updated "
        "with a bad entity list would register a listener that never fires"
    )


# ---------------------------------------------------------------------------
# T6: cleanup wiring parallels _unsub_state / _unsub_lifecycle
# ---------------------------------------------------------------------------

def test_cleanup_unsub_started_registered_via_async_on_remove():
    """If the entity is removed BEFORE HA finishes starting, the one-shot
    listener must be explicitly unsubscribed. async_on_remove(_cleanup_started)
    mirrors the existing _cleanup_state pattern."""
    assert "def _cleanup_started():" in CLASS_BODY
    assert "self.async_on_remove(_cleanup_started)" in CLASS_BODY
    # cleanup must actually call the stored unsub
    cleanup_start = CLASS_BODY.index("def _cleanup_started():")
    cleanup_end = CLASS_BODY.index("self.async_on_remove(_cleanup_started)")
    cleanup = CLASS_BODY[cleanup_start:cleanup_end]
    assert "self._unsub_started" in cleanup
    assert "self._unsub_started = None" in cleanup
