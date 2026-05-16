"""Music Following Coordinator — event-driven music transfer management.

Wraps the existing MusicFollowing class as a BaseCoordinator subclass,
providing: enable/disable switch, coordinator device, config flow UI for
tuning parameters, and diagnostic framework integration.

Architecture: Event-driven via TransitionDetector (not intent-driven).
evaluate() returns empty list — music transfers are triggered by
person transition callbacks, not by the intent/action pipeline.

Priority: 30 (lowest active coordinator).

v3.6.25: Initial implementation — coordinator elevation.
v3.6.26: Fix anomaly detector integration — create detector, wire listener.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ..const import (
    DEFAULT_MF_COOLDOWN_SECONDS,
    DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE,
    DEFAULT_MF_MIN_CONFIDENCE,
    DEFAULT_MF_PING_PONG_WINDOW,
    DEFAULT_MF_POSITION_OFFSET,
    DEFAULT_MF_UNJOIN_DELAY,
    DEFAULT_MF_VERIFY_DELAY,
    DOMAIN,
)
from .base import BaseCoordinator, CoordinatorAction, Intent
from .coordinator_diagnostics import AnomalyDetector
from .signals import SIGNAL_PERSON_ARRIVING, SIGNAL_SAFETY_HAZARD, SIGNAL_SECURITY_EVENT

_LOGGER = logging.getLogger(__name__)

# Metric names for AnomalyDetector (passed to constructor)
MUSIC_FOLLOWING_METRICS = [
    "transfer_success_rate",
    "cooldown_frequency",
]

# v4.6.5.1 P2: Module-level suppression registry — every metric in
# MUSIC_FOLLOWING_METRICS must be EITHER wired (record_observation call in
# this file) OR listed here. Introspected by the parametric meta-test in
# test_v465_observability_gap.py. Both MF metrics are wired (see
# _on_transfer_outcome) so this set is empty today; promoting it to a
# named constant codifies the v4.6.3.1 doctrine and gives future
# maintainers an obvious place to add a suppression rationale.
MUSIC_FOLLOWING_SUPPRESSED_FROM_PERSISTENCE: frozenset[str] = frozenset()


class MusicFollowingCoordinator(BaseCoordinator):
    """Domain coordinator for music following.

    Wraps the standalone MusicFollowing class and delegates all music
    transfer logic to it. The coordinator provides:
    - BaseCoordinator lifecycle (setup/teardown)
    - Enable/disable switch entity
    - Coordinator device in the device registry
    - Configurable tuning parameters via config flow
    - Anomaly detection hooks for transfer success rates

    evaluate() returns an empty list because music following is
    event-driven (TransitionDetector fires callbacks), not intent-driven.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        cooldown_seconds: int = DEFAULT_MF_COOLDOWN_SECONDS,
        ping_pong_window: int = DEFAULT_MF_PING_PONG_WINDOW,
        verify_delay: int = DEFAULT_MF_VERIFY_DELAY,
        unjoin_delay: int = DEFAULT_MF_UNJOIN_DELAY,
        position_offset: int = DEFAULT_MF_POSITION_OFFSET,
        min_confidence: float = DEFAULT_MF_MIN_CONFIDENCE,
        high_confidence_distance: float = DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE,
    ) -> None:
        """Initialize the Music Following Coordinator."""
        super().__init__(
            hass,
            coordinator_id="music_following",
            name="Music Following",
            priority=30,
        )
        self._cooldown_seconds = cooldown_seconds
        self._ping_pong_window = ping_pong_window
        self._verify_delay = verify_delay
        self._unjoin_delay = unjoin_delay
        self._position_offset = position_offset
        self._min_confidence = min_confidence
        # v4.6.5.3 M4 (review note from v4.6.5.2): one-shot flag per metric so
        # we log INFO on the FIRST post-deploy observation. The v4.6.5.2 Fix 1
        # denominator change starts re-drifting the stale baseline from
        # mean=0.0 — operators benefit from a discoverable signal that the
        # new emit path is live. Without this, the only signal is the metric
        # baseline slowly moving over weeks (visible only in the per-coord
        # anomaly sensor's metrics dict).
        self._first_emit_logged: set[str] = set()
        self._high_confidence_distance = high_confidence_distance
        self._music_following = None
        self._pending_tasks: set[asyncio.Task] = set()

    async def async_setup(self) -> None:
        """Set up the coordinator.

        Retrieves the existing MusicFollowing instance from hass.data
        (already initialized by __init__.py) and applies configurable
        tuning parameters. Creates an AnomalyDetector and registers a
        diagnostic listener to feed transfer outcomes into it.
        """
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is not None:
            self._music_following = mf
            # Apply configurable tuning parameters
            mf.MIN_CONFIDENCE = self._min_confidence
            mf._mf_high_confidence_distance = self._high_confidence_distance
            _LOGGER.info(
                "MusicFollowingCoordinator setup: wrapping existing MusicFollowing "
                "(cooldown=%ds, ping_pong=%ds, verify=%ds, unjoin=%ds, "
                "position_offset=%d, min_confidence=%.2f, high_conf_dist=%.1fft)",
                self._cooldown_seconds,
                self._ping_pong_window,
                self._verify_delay,
                self._unjoin_delay,
                self._position_offset,
                self._min_confidence,
                self._high_confidence_distance,
            )
        else:
            _LOGGER.warning(
                "MusicFollowingCoordinator setup: no MusicFollowing instance found "
                "in hass.data — music following may not be initialized yet"
            )

        # Anomaly detection setup — same pattern as safety/security/presence
        # v4.6.3 D10: Read sensitivity bucket from CM entry options.
        from ..const import (  # noqa: PLC0415
            CONF_MUSIC_ANOMALY_SENSITIVITY,
            DEFAULT_ANOMALY_SENSITIVITY,
            ANOMALY_SENSITIVITY_MULTIPLIERS,
            CONF_ENTRY_TYPE,
            ENTRY_TYPE_COORDINATOR_MANAGER,
        )
        _music_sensitivity = DEFAULT_ANOMALY_SENSITIVITY
        try:
            for _ce in self.hass.config_entries.async_entries(DOMAIN):
                if _ce.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    _music_sensitivity = {**_ce.data, **_ce.options}.get(
                        CONF_MUSIC_ANOMALY_SENSITIVITY, DEFAULT_ANOMALY_SENSITIVITY
                    )
                    break
        except Exception:
            pass
        _music_sensitivity_mult = ANOMALY_SENSITIVITY_MULTIPLIERS.get(_music_sensitivity, 1.0)
        self.anomaly_detector = AnomalyDetector(
            self.hass,
            "music_following",
            MUSIC_FOLLOWING_METRICS,
            sensitivity_multiplier=_music_sensitivity_mult,
            # v4.6.5.3 surface fix (set is empty today — both MF metrics wired)
            suppressed_metric_names=MUSIC_FOLLOWING_SUPPRESSED_FROM_PERSISTENCE,
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception:
            _LOGGER.debug("Failed to load music following anomaly baselines (non-fatal)")

        # Wire diagnostic listener so transfer outcomes feed anomaly detector
        if self._music_following is not None:
            self._music_following.add_diagnostic_listener(
                self._on_transfer_outcome
            )

        # v3.22.0 D2: Subscribe to safety hazard signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SAFETY_HAZARD,
                self._handle_safety_hazard,
            )
        )

        # v3.22.0 D3: Subscribe to person arriving signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PERSON_ARRIVING,
                self._handle_person_arriving,
            )
        )

        # v3.22.0 D4: Subscribe to security event signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SECURITY_EVENT,
                self._handle_security_event,
            )
        )

    def _on_transfer_outcome(self) -> None:
        """Diagnostic listener callback — feed transfer stats to anomaly detector.

        Called by MusicFollowing._record_stat() after each transfer outcome.
        Computes transfer_success_rate and cooldown_frequency from the
        standalone class's running stats and records observations.

        v4.6.5 D3: Schedules async persistence of detected anomalies via
        hass.async_create_task (this callback is sync; store_event is async).

        METRIC AUDIT (v4.6.5 binary-metric check per v4.6.3.1 doctrine,
        revised in v4.6.5.2 after live investigation):
        - transfer_success_rate: proportion 0.0–1.0 of successful transfers
          OUT OF music-involved attempts (MusicFollowing._TRANSFER_KEYS:
          success, failed, unverified, active_playback_blocked).
          Pre-v4.6.5.2 used sum(stats.values()) which included pre-music
          rejections (low_confidence, cooldown_blocked, ping_pong_suppressed)
          in the denominator — those dominated the live baseline and
          crushed the rate to ~0.0 over 1594 samples even when transfers
          attempted music. Now uses _TRANSFER_KEYS only.
        - cooldown_frequency: proportion 0.0–1.0 of cooldown-blocks OUT OF
          post-confidence decisions (music_attempts + cooldown_blocks).
          Pre-v4.6.5.2 used sum(stats.values()) same as above; now uses the
          conceptually correct "of decisions made past the confidence check,
          how often did cooldown block." Meaningful when cooldown actually
          fights with attempted transfers.
        Both metrics are still continuous floats and suitable for z-score.
        Baseline-drift caveat: existing persisted baselines (mean=0.0 over
        1594 samples) will drift slowly toward the new denominator's true
        distribution; expect ~weeks for full convergence on a household
        with active MF.
        """
        if self.anomaly_detector is None or self._music_following is None:
            return

        try:
            stats = self._music_following._transfer_stats
            # v4.6.5.2 Fix 1: use _TRANSFER_KEYS as denominator for success_rate
            # so pre-music rejections (low_confidence, ping_pong_suppressed)
            # don't dominate. Cooldown is a special case — handled separately
            # below with its own denominator.
            from ..music_following import MusicFollowing as _MF
            music_attempts = sum(stats.get(k, 0) for k in _MF._TRANSFER_KEYS)

            if music_attempts > 0:
                # transfer_success_rate: of music-involved attempts, fraction succeeded
                success_rate = stats.get("success", 0) / music_attempts
                # v4.6.5.3 M4: one-shot info-log so operators can spot when
                # the v4.6.5.2 Fix 1 denominator change starts feeding the
                # baseline. Logged on the FIRST post-deploy emit only.
                if "transfer_success_rate" not in self._first_emit_logged:
                    _LOGGER.info(
                        "MusicFollowing transfer_success_rate first post-deploy "
                        "emit: rate=%.3f music_attempts=%d (v4.6.5.2 Fix 1 — "
                        "_TRANSFER_KEYS denominator now live; baseline drift "
                        "begins from prior cumulative shape)",
                        success_rate, music_attempts,
                    )
                    self._first_emit_logged.add("transfer_success_rate")
                anomaly = self.anomaly_detector.record_observation(
                    "transfer_success_rate", "house", success_rate,
                )
                if anomaly:
                    # v4.6.5 review B-H1: track the persist task in the existing
                    # _pending_tasks set so async_unload_entry can await/cancel it
                    # (avoids the v4.6.3 A5 untracked-task class — task running
                    # after anomaly_detector / database teardown).
                    task = self.hass.async_create_task(
                        self._persist_mf_anomaly(anomaly, "transfer_success_rate", success_rate),
                        name="ura_mf_persist_transfer_success_rate",
                    )
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)

            # cooldown_frequency: of post-confidence decisions
            # (music attempts + cooldown blocks), fraction got cooldown-blocked.
            post_confidence_total = music_attempts + stats.get("cooldown_blocked", 0)
            if post_confidence_total > 0:
                cooldown_rate = stats.get("cooldown_blocked", 0) / post_confidence_total
                # v4.6.5.3 M4: one-shot info-log (see transfer_success_rate above)
                if "cooldown_frequency" not in self._first_emit_logged:
                    _LOGGER.info(
                        "MusicFollowing cooldown_frequency first post-deploy "
                        "emit: rate=%.3f post_confidence_total=%d "
                        "(v4.6.5.2 Fix 1 — post-confidence denominator now live)",
                        cooldown_rate, post_confidence_total,
                    )
                    self._first_emit_logged.add("cooldown_frequency")
                anomaly2 = self.anomaly_detector.record_observation(
                    "cooldown_frequency", "house", cooldown_rate,
                )
                if anomaly2:
                    task2 = self.hass.async_create_task(
                        self._persist_mf_anomaly(anomaly2, "cooldown_frequency", cooldown_rate),
                        name="ura_mf_persist_cooldown_frequency",
                    )
                    self._pending_tasks.add(task2)
                    task2.add_done_callback(self._pending_tasks.discard)

            # v4.5.20: fire refresh signal so MusicFollowingAnomalySensor
            # re-renders attrs after each transfer. MF is event-driven
            # (no periodic tick), so this dispatch only fires when a
            # transfer outcome happens — matches the natural cadence.
            try:
                from homeassistant.helpers.dispatcher import async_dispatcher_send
                from .signals import SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE
                async_dispatcher_send(
                    self.hass, SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE,
                )
            except Exception:
                _LOGGER.warning(
                    "MF: failed to dispatch "
                    "SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE",
                    exc_info=True,
                )
        except Exception:
            # v4.5.20 also: was bare `pass` — soft escalate.
            _LOGGER.warning(
                "MF: _on_transfer_outcome stats processing failed",
                exc_info=True,
            )

    async def _persist_mf_anomaly(self, anomaly: Any, metric: str, observed: float) -> None:
        """Persist a music_following AnomalyRecord to anomaly_log.

        Called via hass.async_create_task from _on_transfer_outcome (which is
        a sync callback and cannot directly await store_event).
        """
        try:
            from .anomaly_event import (  # noqa: PLC0415
                AnomalyEvent,
                AnomalySeverity as _NewSev,
                EVENT_CLASS_POINT_IN_TIME,
                build_context_json,
                map_diag_severity,
            )
            _ctx = build_context_json(
                source_signal="transfer_outcome_callback",
                extra={"metric": metric, "observed": round(observed, 4)},
            )
            _event = AnomalyEvent(
                coordinator="music_following",
                type=f"music_following.{metric}",
                # v4.6.6 D1: 1:1 mapping preserves all 4 z-score bands.
                severity=map_diag_severity(anomaly.severity),
                event_class=EVENT_CLASS_POINT_IN_TIME,
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
                "MusicFollowing %s anomaly persisted: observed=%.3f z=%.2f",
                metric, observed, anomaly.z_score,
            )
            _activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if _activity_logger:
                await _activity_logger.log(
                    coordinator="music_following",
                    action="anomaly",
                    description=(
                        f"MusicFollowing {metric} anomaly: "
                        f"observed={observed:.3f} z={anomaly.z_score:.2f}"
                    ),
                    importance="notable",
                    details={
                        "type": f"music_following.{metric}",
                        "z_score": round(anomaly.z_score, 3),
                        "observed": round(observed, 4),
                    },
                )
        except Exception:
            _LOGGER.debug(
                "MusicFollowing %s anomaly persist failed", metric, exc_info=True
            )

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate intents — always returns empty list.

        Music following is event-driven (TransitionDetector fires
        _on_person_transition callbacks), not intent-driven. This
        coordinator participates in the lifecycle but does not produce
        actions through the intent pipeline.
        """
        return []

    # ------------------------------------------------------------------
    # v3.22.0 D2/D3/D4: Cross-coordinator signal handlers
    # ------------------------------------------------------------------

    @callback
    def _handle_safety_hazard(self, hazard: Any) -> None:
        """Handle safety hazard signal — stop all playback on critical.

        v3.22.0 D2: Cross-coordinator response to SIGNAL_SAFETY_HAZARD.
        Gated by CONF_MUSIC_ON_HAZARD_STOP config toggle.
        """
        if not self._enabled:
            return
        # Review fix F6: observation mode guard
        if getattr(self, "observation_mode", False):
            _LOGGER.debug("MusicFollowing: Safety hazard received — suppressed by observation mode")
            return
        if hazard is None:
            return
        if isinstance(hazard, dict):
            severity = hazard.get("severity", "")
            hazard_type = hazard.get("hazard_type", "")
        elif hasattr(hazard, "severity"):
            severity = getattr(hazard, "severity", "")
            hazard_type = getattr(hazard, "hazard_type", "")
        else:
            return

        if severity != "critical":
            return

        from ..const import CONF_MUSIC_ON_HAZARD_STOP

        if self._get_signal_config(CONF_MUSIC_ON_HAZARD_STOP):
            _LOGGER.warning(
                "MusicFollowing: Safety hazard %s/%s — stopping all playback",
                hazard_type, severity,
            )
            task = self.hass.async_create_task(self._stop_all_playback())
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        else:
            _LOGGER.info(
                "MusicFollowing: Safety hazard %s/%s — would stop playback "
                "(disabled by config)",
                hazard_type, severity,
            )

    @callback
    def _handle_person_arriving(self, payload: Any) -> None:
        """Handle person arriving signal — start music in person's zone.

        v3.22.0 D3: Cross-coordinator response to SIGNAL_PERSON_ARRIVING.
        Gated by CONF_MUSIC_ON_ARRIVAL_START config toggle (OFF by default).
        """
        if not self._enabled:
            return
        if getattr(self, "observation_mode", False):
            return
        if payload is None:
            return
        if isinstance(payload, dict):
            person_entity = payload.get("person_entity", "")
            zone = payload.get("zone", "")
        elif hasattr(payload, "person_entity"):
            person_entity = getattr(payload, "person_entity", "")
            zone = getattr(payload, "zone", "")
        else:
            return

        if not person_entity:
            return

        from ..const import CONF_MUSIC_ON_ARRIVAL_START

        if self._get_signal_config(CONF_MUSIC_ON_ARRIVAL_START):
            _LOGGER.info(
                "MusicFollowing: Person arriving %s — would start music in zone %s "
                "(arrival music start is a convenience stub)",
                person_entity, zone or "unknown",
            )
            # Note: Actual playback start requires knowing the person's preferred
            # media and zone speaker. The MusicFollowing class is event-driven via
            # TransitionDetector and doesn't expose a "start playing" API.
            # This handler logs the intent; full implementation deferred to a
            # future cycle when person-preferred-media config exists.
        else:
            _LOGGER.info(
                "MusicFollowing: Person arriving %s — would start music "
                "(disabled by config)",
                person_entity,
            )

    @callback
    def _handle_security_event(self, payload: Any) -> None:
        """Handle security event signal — stop all playback on critical.

        v3.22.0 D4: Cross-coordinator response to SIGNAL_SECURITY_EVENT.
        Gated by CONF_MUSIC_ON_SECURITY_STOP config toggle.
        """
        if not self._enabled:
            return
        if getattr(self, "observation_mode", False):
            return
        if payload is None:
            return
        if isinstance(payload, dict):
            severity = payload.get("severity", "")
            event_type = payload.get("event_type", "")
        elif hasattr(payload, "severity"):
            severity = getattr(payload, "severity", "")
            event_type = getattr(payload, "event_type", "")
        else:
            return

        if severity != "critical":
            return

        from ..const import CONF_MUSIC_ON_SECURITY_STOP

        if self._get_signal_config(CONF_MUSIC_ON_SECURITY_STOP):
            _LOGGER.warning(
                "MusicFollowing: Security event %s/%s — stopping all playback",
                event_type, severity,
            )
            task = self.hass.async_create_task(self._stop_all_playback())
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        else:
            _LOGGER.info(
                "MusicFollowing: Security event %s/%s — would stop playback "
                "(disabled by config)",
                event_type, severity,
            )

    async def _stop_all_playback(self) -> None:
        """Stop all active media players (safety/security response).

        Iterates all media_player entities in the playing state and
        sends media_stop. Best-effort: failures logged but do not propagate.
        """
        stopped = 0
        for state in self.hass.states.async_all("media_player"):
            if state.state in ("playing", "paused"):
                try:
                    await self.hass.services.async_call(
                        "media_player", "media_stop",
                        {"entity_id": state.entity_id}, blocking=False,
                    )
                    stopped += 1
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "MusicFollowing: Failed to stop %s", state.entity_id
                    )
        if stopped > 0:
            _LOGGER.info("MusicFollowing: Stopped %d media player(s)", stopped)

    async def async_teardown(self) -> None:
        """Tear down the coordinator."""
        # Cancel any in-flight tasks before other cleanup
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()
        self._cancel_listeners()
        if self.anomaly_detector is not None:
            try:
                await self.anomaly_detector.save_baselines()
            except Exception:
                # v4.5.20: was debug. Periodic save; non-critical because
                # recoverable next save. Soft escalate with exc_info.
                _LOGGER.warning(
                    "MusicFollowingCoordinator: failed to save anomaly baselines",
                    exc_info=True,
                )
        self._music_following = None
        _LOGGER.info("MusicFollowingCoordinator torn down")

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Return diagnostics summary including music following stats."""
        summary = super().get_diagnostics_summary()
        if self._music_following is not None:
            summary["music_following"] = self._music_following.get_diagnostic_data()
        else:
            summary["music_following"] = {"state": "not_initialized"}
        return summary
