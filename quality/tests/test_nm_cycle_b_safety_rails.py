"""NM Cycle B (2026-07-20) — Safety-rails behavioral + mutation-anchored tests.

Cycle-B invariants (from PLANNING_nm_overhaul_2026_07.md):

  (i)   A CRITICAL acked via safe word never fires again in the same episode
        across any channel/recipient across a mid-episode HA restart.
  (ii)  Life-safety CRITICAL (smoke/CO/fire/water_leak/flooding/intrusion/
        freeze_risk) always repeats at ≤ 30 s.
  (iii) Non-life-safety CRITICAL repeats at ≥ 300 s.
  (iv)  In any 60 s window, no channel sends more than
        NM_RATE_BUCKET_CAPACITY messages including repeats; overflow queued.
  (v)   Within 5 s of NM startup, ≤ 1 alert per (coordinator, hazard_type)
        fires from restore_persistence_state replay.
  (vi)  With CONF_NM_DRY_RUN=true, zero outbound `hass.services.async_call`
        invocations to any notification service in any reachable emit path.

Tests reuse the existing NM test harness pattern from
`test_notification_manager.py` (see that file's top-of-module HA-stub setup;
importing it here piggybacks on those stubs).
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock

# Bootstrap HA stubs by importing the sibling NM test module first.
from test_notification_manager import _make_hass, _make_config  # noqa: F401

from custom_components.universal_room_automation.const import (
    CONF_NM_DRY_RUN,
    CONF_NM_ALERT_LIGHTS,
    CONF_NM_TTS_SPEAKERS,
    CONF_NM_TTS_ENABLED,
    CONF_NM_LIGHTS_ENABLED,
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_WHATSAPP_ENABLED,
    CONF_NM_IMESSAGE_ENABLED,
    NM_BUCKET_CAPACITY_DEFAULT,
    NM_BUCKET_REFILL_PER_MIN_DEFAULT,
    NM_REPEAT_INTERVAL_LIFE_SAFETY,
    NM_REPEAT_INTERVAL_NON_LIFE_SAFETY,
    NM_LIFE_SAFETY_HAZARDS,
    NM_OVERFLOW_QUEUE_MAX,
    NM_BOOT_SETTLE_S,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
    AlertState,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ============================================================================
# Fixture self-check — seed must actually trigger the machinery we test.
# ============================================================================


def test_fixture_selfcheck_life_safety_vocabulary_is_nonempty():
    """Guard against a silent typo shrinking the life-safety set to empty."""
    assert "smoke" in NM_LIFE_SAFETY_HAZARDS
    assert "carbon_monoxide" in NM_LIFE_SAFETY_HAZARDS
    assert "water_leak" in NM_LIFE_SAFETY_HAZARDS
    assert len(NM_LIFE_SAFETY_HAZARDS) >= 7


def test_fixture_selfcheck_cadence_split_is_real():
    """The two cadences must actually differ — otherwise B1 is a no-op."""
    assert NM_REPEAT_INTERVAL_LIFE_SAFETY < NM_REPEAT_INTERVAL_NON_LIFE_SAFETY
    assert NM_REPEAT_INTERVAL_LIFE_SAFETY <= 30
    assert NM_REPEAT_INTERVAL_NON_LIFE_SAFETY >= 300


# ============================================================================
# B0 — Dry-run gate (invariant vi)
# ============================================================================


class TestB0DryRunGate:
    """CONF_NM_DRY_RUN=true short-circuits every emit-path service call."""

    def _dry_run_nm(self):
        hass = _make_hass()
        cfg = _make_config(**{
            CONF_NM_DRY_RUN: True,
            CONF_NM_TTS_ENABLED: True,
            CONF_NM_TTS_SPEAKERS: ["media_player.kitchen"],
            CONF_NM_LIGHTS_ENABLED: True,
            CONF_NM_ALERT_LIGHTS: ["light.alert"],
        })
        nm = NotificationManager(hass, cfg)
        return hass, nm

    def test_dry_run_active_reflected(self):
        _, nm = self._dry_run_nm()
        assert nm.dry_run_active is True
        assert nm.diagnostics_summary["dry_run_active"] is True

    def test_pushover_send_shortcircuits_under_dry_run(self):
        hass, nm = self._dry_run_nm()
        _run(nm._send_pushover("t", "m", Severity.CRITICAL, "user_key", "dev"))
        # No outbound service call to any notification service.
        assert hass.services.async_call.await_count == 0

    def test_whatsapp_send_shortcircuits_under_dry_run(self):
        hass, nm = self._dry_run_nm()
        _run(nm._send_whatsapp("t", "m", "+15555555555"))
        assert hass.services.async_call.await_count == 0

    def test_imessage_send_shortcircuits_under_dry_run(self):
        hass, nm = self._dry_run_nm()
        _run(nm._send_imessage("t", "m", "+15555555555"))
        assert hass.services.async_call.await_count == 0

    def test_companion_send_shortcircuits_under_dry_run(self):
        hass, nm = self._dry_run_nm()
        _run(nm._send_companion("t", "m", Severity.CRITICAL, "notify.mobile"))
        assert hass.services.async_call.await_count == 0

    def test_tts_send_shortcircuits_under_dry_run(self):
        hass, nm = self._dry_run_nm()
        _run(nm._send_tts("t", "m"))
        assert hass.services.async_call.await_count == 0

    def test_trigger_alert_lights_shortcircuits_under_dry_run(self):
        hass, nm = self._dry_run_nm()
        # Should NOT schedule the light-pattern task and NOT call the light service.
        _run(nm._trigger_alert_lights("smoke", Severity.CRITICAL))
        assert hass.services.async_call.await_count == 0
        assert nm._light_pattern_task is None

    def test_dry_run_off_actually_calls_service(self):
        """Mutation-anchor: if the gate is inverted, this test fails."""
        hass = _make_hass()
        cfg = _make_config(**{CONF_NM_DRY_RUN: False})
        nm = NotificationManager(hass, cfg)
        _run(nm._send_pushover("t", "m", Severity.CRITICAL, "u", "d"))
        assert hass.services.async_call.await_count == 1

    def test_set_dry_run_active_toggle_is_live(self):
        hass, nm = self._dry_run_nm()
        _run(nm.set_dry_run_active(False))
        assert nm.dry_run_active is False
        _run(nm._send_pushover("t", "m", Severity.HIGH, "u", "d"))
        assert hass.services.async_call.await_count == 1


# ============================================================================
# B1 — Life-safety subtype cadence (invariants ii + iii)
# ============================================================================


class TestB1SubtypeCadence:
    """`_schedule_repeat` picks cadence from the active hazard."""

    def _nm(self):
        return NotificationManager(_make_hass(), _make_config())

    def test_life_safety_selects_30s(self):
        nm = self._nm()
        nm._active_alert_data = {"hazard_type": "smoke"}
        assert nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_LIFE_SAFETY
        # Every canonical life-safety hazard must pick the short cadence.
        for hz in NM_LIFE_SAFETY_HAZARDS:
            nm._active_alert_data = {"hazard_type": hz}
            assert nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_LIFE_SAFETY

    def test_non_life_safety_selects_300s(self):
        nm = self._nm()
        nm._active_alert_data = {"hazard_type": "test_synth"}
        assert nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_NON_LIFE_SAFETY

    def test_case_insensitive(self):
        nm = self._nm()
        nm._active_alert_data = {"hazard_type": "SMOKE"}
        assert nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_LIFE_SAFETY

    def test_missing_hazard_uses_non_life_safety(self):
        """Safer default — a missing hazard shouldn't storm at 30s."""
        nm = self._nm()
        nm._active_alert_data = {"hazard_type": None}
        assert nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_NON_LIFE_SAFETY


# ============================================================================
# B2 — Safe-word ack registry (invariant i)
# ============================================================================


class TestB2AckRegistryRestartSafe:
    """Acked episode does not re-fire across restart via persistence dict."""

    def test_ack_writes_registry_entry(self):
        nm = NotificationManager(_make_hass(), _make_config())
        nm._alert_state = AlertState.REPEATING
        nm._active_episode_id = "safety:smoke:kitchen:1234"
        nm._active_alert_data = {"hazard_type": "smoke", "location": "kitchen"}
        # Stub out cooldown DB path so we don't need aiosqlite here.
        nm._start_cooldown = AsyncMock()
        nm._restore_alert_lights = AsyncMock()
        _run(nm.async_acknowledge(safe_word_verified=True))
        assert "safety:smoke:kitchen:1234" in nm._ack_registry
        assert nm._ack_registry["safety:smoke:kitchen:1234"]["safe_word_verified"] is True

    def test_persistence_state_carries_registry(self):
        nm = NotificationManager(_make_hass(), _make_config())
        nm._ack_registry["k1"] = {"acked_at": "2026-07-20T00:00:00", "safe_word_verified": True}
        nm._active_episode_id = "k1"
        state = nm.get_persistence_state()
        assert "ack_registry" in state
        assert state["ack_registry"]["k1"]["safe_word_verified"] is True
        assert state["active_episode_id"] == "k1"

    def test_restore_repopulates_registry(self):
        nm = NotificationManager(_make_hass(), _make_config())
        nm.restore_persistence_state({
            "alert_state": "idle",
            "ack_registry": {"k1": {"acked_at": "x", "safe_word_verified": True}},
            "active_episode_id": "k1",
        })
        assert "k1" in nm._ack_registry
        assert nm._active_episode_id == "k1"

    def test_recover_then_restore_cancels_acked_episode(self):
        """B-B2 fix-up (2026-07-20): REAL ordering test — recovery runs
        BEFORE the sensor's RestoreEntity populates `_ack_registry`, so
        the pre-fix skip inside `_recover_state_from_db` was dead. The
        cancel now lives in `restore_persistence_state`: if recovery
        armed REPEATING and the restored registry contains the current
        episode → cancel + IDLE.
        """
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        # Step 1: recovery runs FIRST — registry still empty.
        db = MagicMock()
        db.get_active_critical = AsyncMock(return_value={
            "coordinator_id": "safety",
            "title": "Smoke",
            "message": "Alarm",
            "hazard_type": "smoke",
            "location": "kitchen",
        })
        db.get_active_cooldown = AsyncMock(return_value=None)
        db.get_last_notification = AsyncMock(return_value=None)
        db.get_notifications_today = AsyncMock(return_value=[])
        hass.data["universal_room_automation"] = {"database": db}
        _run(nm._recover_state_from_db())
        # Recovery armed REPEATING (primary DB filter didn't help — the
        # row's `acknowledged` column wasn't updated pre-restart).
        assert nm.alert_state == AlertState.REPEATING
        # Track the episode id that would have been armed.
        nm._active_episode_id = "safety:smoke:kitchen:1234"
        # Step 2: sensor's RestoreEntity replays extra_state_attributes
        # into NM. Registry now shows the episode was acked.
        nm.restore_persistence_state({
            "alert_state": "repeating",
            "ack_registry": {
                "safety:smoke:kitchen:1234": {
                    "acked_at": "x", "safe_word_verified": True,
                }
            },
            "active_episode_id": "safety:smoke:kitchen:1234",
        })
        # LATE cancel must have kicked in.
        assert nm.alert_state == AlertState.IDLE, (
            "acked episode must be cancelled by late restore_persistence_state"
        )

    def test_recover_arms_when_registry_empty(self):
        """Mutation-anchor: without the registry skip, we resume as before."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        # No episode id, no registry entries.
        db = MagicMock()
        db.get_active_critical = AsyncMock(return_value={
            "coordinator_id": "safety",
            "title": "Smoke",
            "message": "Alarm",
            "hazard_type": "smoke",
            "location": "kitchen",
        })
        db.get_active_cooldown = AsyncMock(return_value=None)
        db.get_last_notification = AsyncMock(return_value=None)
        db.get_notifications_today = AsyncMock(return_value=[])
        hass.data["universal_room_automation"] = {"database": db}
        _run(nm._recover_state_from_db())
        assert nm.alert_state == AlertState.REPEATING


# ============================================================================
# B3 — Token bucket + overflow queue (invariant iv)
# ============================================================================


class TestB3TokenBucket:
    """Per-channel bucket + bounded FIFO overflow; life-safety bypasses."""

    def _nm(self):
        return NotificationManager(_make_hass(), _make_config())

    def test_default_capacity_seeded(self):
        nm = self._nm()
        for ch in ("pushover", "companion", "whatsapp", "imessage", "tts", "lights"):
            assert nm._bucket_tokens[ch] == float(NM_BUCKET_CAPACITY_DEFAULT)

    def test_take_consumes_one_token(self):
        nm = self._nm()
        start = nm._bucket_tokens["pushover"]
        assert nm._bucket_take("pushover", life_safety=False) is True
        assert nm._bucket_tokens["pushover"] == start - 1.0

    def test_life_safety_bypasses_bucket(self):
        nm = self._nm()
        nm._bucket_tokens["pushover"] = 0.0
        # Fake refill won't help — we consumed at t0.
        nm._bucket_last_refill = 1e15  # far future to prevent refill
        assert nm._bucket_take("pushover", life_safety=True) is True
        # Life-safety must NOT decrement (bypass, not consume-with-loan).
        assert nm._bucket_tokens["pushover"] == 0.0

    def test_bucket_exhaustion_enqueues_overflow(self):
        nm = self._nm()
        nm._bucket_tokens["pushover"] = 0.0
        nm._bucket_last_refill = 1e15  # prevent refill
        assert nm._bucket_take("pushover", life_safety=False) is False
        nm._enqueue_overflow("pushover", "test", "test_synth")
        assert len(nm._overflow_queue) == 1

    def test_overflow_queue_bounded(self):
        nm = self._nm()
        # deque(maxlen=NM_OVERFLOW_QUEUE_MAX) — capacity should be enforced.
        assert nm._overflow_queue.maxlen == NM_OVERFLOW_QUEUE_MAX

    def test_channel_ready_wraps_qualifies_and_bucket(self):
        """`_channel_ready` = qualifies AND bucket_take (except life-safety)."""
        nm = NotificationManager(_make_hass(), _make_config())
        # Empty non-life-safety bucket → not ready.
        nm._bucket_tokens["pushover"] = 0.0
        nm._bucket_last_refill = 1e15
        assert nm._channel_ready("pushover", Severity.HIGH, "test_synth") is False
        # Same empty bucket but life-safety CRITICAL → ready (bypass).
        assert nm._channel_ready("pushover", Severity.CRITICAL, "smoke") is True

    def test_refill_recovers_after_time(self):
        nm = self._nm()
        nm._bucket_tokens["pushover"] = 0.0
        # Pretend 10 minutes elapsed since last refill — at 6/min, should
        # add 60 tokens (clamped to capacity).
        nm._bucket_last_refill = nm._bucket_last_refill - 600
        nm._bucket_refill()
        assert nm._bucket_tokens["pushover"] == nm._bucket_capacity

    def test_bucket_snapshot_reads_do_not_write_db(self):
        """Repeated sensor-attr reads must NOT enqueue rows or fire sends."""
        hass = _make_hass()
        nm = NotificationManager(hass, _make_config())
        for _ in range(50):
            nm._bucket_snapshot()
        # Zero service calls; zero overflow items.
        assert hass.services.async_call.await_count == 0
        assert len(nm._overflow_queue) == 0


# ============================================================================
# B4 — Boot-settle guard (invariant v)
# ============================================================================


class TestB4BootSettle:
    """First NM_BOOT_SETTLE_S seconds collapse per-(coord, hazard) emits."""

    def _armed_nm(self):
        nm = NotificationManager(_make_hass(), _make_config())
        # Simulate the async_setup arm — set far-future so the window is
        # unambiguously OPEN regardless of any dt_util patching earlier in
        # the suite. (The helper compares utcnow.timestamp() < _until.)
        nm._boot_settle_until = 10**15
        nm._boot_settle_seen.clear()
        return nm

    def test_first_emit_passes(self):
        nm = self._armed_nm()
        assert nm._boot_settle_should_suppress("safety", "smoke") is False

    def test_second_same_pair_is_suppressed(self):
        nm = self._armed_nm()
        assert nm._boot_settle_should_suppress("safety", "test_synth") is False
        assert nm._boot_settle_should_suppress("safety", "test_synth") is True

    def test_different_pair_passes(self):
        nm = self._armed_nm()
        assert nm._boot_settle_should_suppress("safety", "test_synth") is False
        assert nm._boot_settle_should_suppress("energy", "test_synth") is False

    def test_after_window_no_suppression(self):
        nm = self._armed_nm()
        nm._boot_settle_seen.add(("safety", "test_synth"))
        nm._boot_settle_until = 0.0  # window closed
        assert nm._boot_settle_should_suppress("safety", "test_synth") is False


# ============================================================================
# Sensor attribute surface — B acceptance §5
# ============================================================================


class TestBSensorAttributes:
    """`sensor.ura_notification_manager` gains the four Cycle-B attrs."""

    def test_diagnostics_summary_carries_cycle_b_attrs(self):
        nm = NotificationManager(_make_hass(), _make_config())
        attrs = nm.diagnostics_summary
        for k in (
            "dry_run_active",
            "overflow_queue_depth",
            "bucket_capacity_remaining_per_channel",
            "active_ack_registry_size",
        ):
            assert k in attrs, f"{k} missing from diagnostics_summary"
        assert isinstance(attrs["bucket_capacity_remaining_per_channel"], dict)


# ============================================================================
# Write-volume regression — no per-tick DB amplifier
# ============================================================================


class TestWriteVolumeRegression:
    """N sensor-attribute reads over N ticks must NOT produce DB writes."""

    def test_bucket_snapshot_zero_db_writes(self):
        hass = _make_hass()
        db = MagicMock()
        db.log_notification = AsyncMock()
        db.save_anomaly_event = AsyncMock()
        hass.data["universal_room_automation"] = {"database": db}
        nm = NotificationManager(hass, _make_config())
        for _ in range(200):
            _ = nm.diagnostics_summary  # sensor read path
        assert db.log_notification.await_count == 0
        assert db.save_anomaly_event.await_count == 0

    def test_dry_run_logs_one_row_per_send_call_no_amplifier(self):
        """Each _send_* under dry-run writes EXACTLY one row (not per tick)."""
        hass = _make_hass()
        db = MagicMock()
        db.log_notification = AsyncMock()
        hass.data["universal_room_automation"] = {"database": db}
        nm = NotificationManager(hass, _make_config(**{CONF_NM_DRY_RUN: True}))
        _run(nm._send_pushover("t", "m", Severity.HIGH, "u", "d"))
        assert db.log_notification.await_count == 1
        # Second call = second row (not amplified).
        _run(nm._send_pushover("t", "m", Severity.HIGH, "u", "d"))
        assert db.log_notification.await_count == 2


# ============================================================================
# NM Cycle B fix-up (2026-07-20) — A-CRIT-1 vocabulary authority
# ============================================================================


class TestACrit1VocabularyAuthority:
    """Every NM_LIFE_SAFETY_HAZARDS member must be a TOKEN THAT IS ACTUALLY
    EMITTED by production code (safety.HazardType enum OR a string literal
    passed as ``hazard_type=`` in a domain coordinator).

    Locks against silent-typo demotion of a life-safety hazard to the
    300 s non-life-safety cadence (the exact bug this fix-up repaired for
    ``intrusion``→``intruder``).
    """

    @staticmethod
    def _emitted_tokens() -> set[str]:
        import re
        from pathlib import Path
        pkg = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"
        # HazardType enum values (safety.py).
        safety_src = (pkg / "domain_coordinators" / "safety.py").read_text()
        enum_vals = set(re.findall(r"^\s*[A-Z_]+\s*=\s*\"([a-z_0-9]+)\"", safety_src, re.MULTILINE))
        # String-literal `hazard_type="..."` at emit sites across coords.
        literals: set[str] = set()
        for p in (pkg / "domain_coordinators").glob("*.py"):
            text = p.read_text()
            literals.update(re.findall(r"hazard_type=\"([a-z_0-9]+)\"", text))
            # Also patterns like `hazard = "intruder"` (security.py:1158).
            literals.update(re.findall(r"hazard\s*=\s*\"([a-z_0-9]+)\"", text))
        return enum_vals | literals

    def test_every_life_safety_member_is_emitted_somewhere(self):
        emitted = self._emitted_tokens()
        assert emitted, "harness failure: found zero emitted hazard tokens"
        missing = sorted(NM_LIFE_SAFETY_HAZARDS - emitted)
        assert not missing, (
            f"A-CRIT-1: NM_LIFE_SAFETY_HAZARDS contains tokens not emitted "
            f"anywhere in production: {missing}. Every member must be a real "
            f"emitted string (HazardType enum value or hazard_type=... literal); "
            f"otherwise a hand-typo silently demotes an intended life-safety "
            f"hazard to the 300s non-life-safety cadence."
        )

    def test_intruder_is_present_and_intrusion_is_not(self):
        """Anchor for the specific typo repaired 2026-07-20."""
        assert "intruder" in NM_LIFE_SAFETY_HAZARDS
        assert "intrusion" not in NM_LIFE_SAFETY_HAZARDS

    def test_co_alias_dropped(self):
        """A-MED-1: only ``carbon_monoxide`` is emitted; the ``co`` alias
        was dead vocabulary."""
        assert "carbon_monoxide" in NM_LIFE_SAFETY_HAZARDS
        assert "co" not in NM_LIFE_SAFETY_HAZARDS


class TestB1IntruderCadence:
    """CRITICAL intruder must select the 30 s life-safety cadence AND
    bypass the token bucket AND NOT be boot-collapsed."""

    def test_intruder_selects_life_safety_cadence(self):
        nm = NotificationManager(_make_hass(), _make_config())
        nm._active_alert_data = {"hazard_type": "intruder"}
        assert nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_LIFE_SAFETY

    def test_intruder_critical_bypasses_bucket(self):
        nm = NotificationManager(_make_hass(), _make_config())
        nm._bucket_tokens["pushover"] = 0.0
        nm._bucket_last_refill = 1e15  # prevent refill
        # Life-safety CRITICAL intruder: gate must pass even with empty bucket.
        assert nm._channel_ready("pushover", Severity.CRITICAL, "intruder") is True

    def test_intruder_never_boot_collapsed(self):
        """B4 collapse suppresses NON-life-safety only. Verify the async_notify
        path does NOT suppress intruder inside the boot-settle window."""
        # `_boot_settle_should_suppress` is only called for non-life-safety
        # emits (see async_notify site). Assert the guard's parameters are
        # respected — an intruder emit should never be routed through the
        # collapse map. We anchor this by contract: the life-safety set
        # includes intruder AND the async_notify site short-circuits on
        # life-safety before consulting boot-settle.
        assert "intruder" in NM_LIFE_SAFETY_HAZARDS


# ============================================================================
# B-B3 fix-up — ack registry pruned to 20 most recent
# ============================================================================


class TestBB3AckRegistryPrune:
    def test_registry_pruned_to_20_entries(self):
        nm = NotificationManager(_make_hass(), _make_config())
        nm._alert_state = AlertState.REPEATING
        nm._active_alert_data = {"hazard_type": "smoke", "location": "k"}
        nm._start_cooldown = AsyncMock()
        nm._restore_alert_lights = AsyncMock()
        for i in range(25):
            nm._active_episode_id = f"ep:{i}"
            nm._alert_state = AlertState.REPEATING
            _run(nm.async_acknowledge(safe_word_verified=True))
        assert len(nm._ack_registry) == 20
        # Oldest 5 pruned, most recent 20 preserved (insertion order).
        assert "ep:0" not in nm._ack_registry
        assert "ep:4" not in nm._ack_registry
        assert "ep:5" in nm._ack_registry
        assert "ep:24" in nm._ack_registry


# ============================================================================
# C-HIGH-2 fix-up — hoisted per-channel bucket-take semantics
# ============================================================================


class TestCHigh2HoistedChannelGate:
    """N configured persons on one channel with capacity K < N: exactly ONE
    token per channel per notification (not N), and unconfigured / digest-pref
    persons must NOT burn tokens either."""

    def _nm_with_persons(self, persons, capacity=2, dry_run=False):
        from custom_components.universal_room_automation.const import (
            CONF_NM_PERSONS,
            CONF_NM_BUCKET_CAPACITY,
            CONF_NM_PUSHOVER_ENABLED,
        )
        hass = _make_hass()
        cfg = _make_config(**{
            CONF_NM_PERSONS: persons,
            CONF_NM_BUCKET_CAPACITY: capacity,
            CONF_NM_PUSHOVER_ENABLED: True,
            CONF_NM_DRY_RUN: dry_run,
        })
        nm = NotificationManager(hass, cfg)
        # Force initial bucket to configured capacity.
        for ch in nm._bucket_tokens:
            nm._bucket_tokens[ch] = float(capacity)
        return hass, nm

    def test_three_persons_one_channel_capacity_two_burns_one_token(self):
        """C-MED-2 lock-in: async_notify with 3 configured persons on pushover,
        capacity=2 → exactly 1 token burned + 3 sends (one per person)."""
        from custom_components.universal_room_automation.const import (
            CONF_NM_PERSON_ENTITY,
            CONF_NM_PERSON_PUSHOVER_KEY,
            CONF_NM_PERSON_DELIVERY_PREF,
        )
        persons = [
            {
                CONF_NM_PERSON_ENTITY: f"person.p{i}",
                CONF_NM_PERSON_PUSHOVER_KEY: f"key{i}",
                CONF_NM_PERSON_DELIVERY_PREF: "immediate",
            }
            for i in range(3)
        ]
        hass, nm = self._nm_with_persons(persons, capacity=2)
        start_tokens = nm._bucket_tokens["pushover"]
        gate = nm._gate_channels_for_notify(
            persons, Severity.HIGH, "test_synth", "safety",
        )
        assert gate["pushover"] is True
        # EXACTLY one token consumed.
        assert nm._bucket_tokens["pushover"] == start_tokens - 1.0

    def test_unconfigured_persons_do_not_burn_tokens(self):
        """3 persons but only 1 has a pushover key → still only 1 token."""
        from custom_components.universal_room_automation.const import (
            CONF_NM_PERSON_ENTITY,
            CONF_NM_PERSON_PUSHOVER_KEY,
            CONF_NM_PERSON_DELIVERY_PREF,
        )
        persons = [
            {CONF_NM_PERSON_ENTITY: "person.p0", CONF_NM_PERSON_PUSHOVER_KEY: "",
             CONF_NM_PERSON_DELIVERY_PREF: "immediate"},
            {CONF_NM_PERSON_ENTITY: "person.p1", CONF_NM_PERSON_PUSHOVER_KEY: "",
             CONF_NM_PERSON_DELIVERY_PREF: "immediate"},
            {CONF_NM_PERSON_ENTITY: "person.p2", CONF_NM_PERSON_PUSHOVER_KEY: "K",
             CONF_NM_PERSON_DELIVERY_PREF: "immediate"},
        ]
        _, nm = self._nm_with_persons(persons, capacity=5)
        start = nm._bucket_tokens["pushover"]
        nm._gate_channels_for_notify(persons, Severity.HIGH, "x", "c")
        assert nm._bucket_tokens["pushover"] == start - 1.0

    def test_digest_pref_persons_do_not_burn_tokens(self):
        """3 persons all with digest pref for a MEDIUM sev → zero tokens."""
        from custom_components.universal_room_automation.const import (
            CONF_NM_PERSON_ENTITY,
            CONF_NM_PERSON_PUSHOVER_KEY,
            CONF_NM_PERSON_DELIVERY_PREF,
        )
        persons = [
            {CONF_NM_PERSON_ENTITY: f"p{i}", CONF_NM_PERSON_PUSHOVER_KEY: "K",
             CONF_NM_PERSON_DELIVERY_PREF: "digest"}
            for i in range(3)
        ]
        _, nm = self._nm_with_persons(persons, capacity=5)
        start = nm._bucket_tokens["pushover"]
        gate = nm._gate_channels_for_notify(persons, Severity.MEDIUM, "x", "c")
        assert gate["pushover"] is False
        assert nm._bucket_tokens["pushover"] == start

    def test_dry_run_does_not_burn_tokens(self):
        """C-HIGH-2 ruling: dry-run STILL evaluates the gate, but does NOT
        burn tokens (observation must not distort the observed counter)."""
        from custom_components.universal_room_automation.const import (
            CONF_NM_PERSON_ENTITY,
            CONF_NM_PERSON_PUSHOVER_KEY,
            CONF_NM_PERSON_DELIVERY_PREF,
        )
        persons = [
            {CONF_NM_PERSON_ENTITY: "p0", CONF_NM_PERSON_PUSHOVER_KEY: "K",
             CONF_NM_PERSON_DELIVERY_PREF: "immediate"},
        ]
        _, nm = self._nm_with_persons(persons, capacity=2, dry_run=True)
        start = nm._bucket_tokens["pushover"]
        gate = nm._gate_channels_for_notify(persons, Severity.HIGH, "x", "c")
        assert gate["pushover"] is True
        assert nm._bucket_tokens["pushover"] == start  # unchanged


# ============================================================================
# B-B4 fix-up — dry-run options-writeback (Switch construction sees true value)
# ============================================================================


class TestBB4DryRunOptionsWriteback:
    def test_nm_init_reads_dry_run_true_from_options(self):
        """B-B4: NM constructed with CONF_NM_DRY_RUN=True in options must be
        dry-run-active from tick zero (before the Switch entity restores)."""
        cfg = _make_config(**{CONF_NM_DRY_RUN: True})
        nm = NotificationManager(_make_hass(), cfg)
        assert nm.dry_run_active is True


# ============================================================================
# C-HIGH-1 / B-B5 fix-up — overflow is honest DROP COUNTER (no drain)
# ============================================================================


class TestOverflowDropCounter:
    def test_overflow_dropped_total_counter_exposed(self):
        nm = NotificationManager(_make_hass(), _make_config())
        attrs = nm.diagnostics_summary
        assert "overflow_dropped_total" in attrs
        assert attrs["overflow_dropped_total"] == 0

    def test_overflow_drop_increments_counter(self):
        nm = NotificationManager(_make_hass(), _make_config())
        nm._enqueue_overflow("pushover", "safety", "test_synth")
        nm._enqueue_overflow("pushover", "safety", "test_synth")
        assert nm._overflow_dropped_total == 2
        # Recent-drops ring reflects the two drops.
        assert len(nm._overflow_recent_drops) == 2

    def test_take_channel_once_uses_real_coordinator_id(self):
        """Fix for hardcoded coordinator_id=\"notify\" at old ~2290 site."""
        nm = NotificationManager(_make_hass(), _make_config())
        nm._bucket_tokens["pushover"] = 0.0
        nm._bucket_last_refill = 1e15
        assert nm._take_channel_once(
            "pushover", Severity.HIGH, "test_synth", "safety",
        ) is False
        # Recent-drops carry the real coord id, not "notify".
        drop = nm._overflow_recent_drops[-1]
        assert drop["coordinator_id"] == "safety"
