"""Music Following Coordinator — event-driven music transfer management.

Wraps the existing MusicFollowing class as a BaseCoordinator subclass,
providing: enable/disable switch, coordinator device, config flow UI for
tuning parameters, and diagnostic framework integration.

Architecture: Event-driven via TransitionDetector (not intent-driven).
evaluate() returns empty list — music transfers are triggered by
person transition callbacks, not by the intent/action pipeline.

Priority: 30 (lowest active coordinator).

v3.6.24: Initial implementation — coordinator elevation.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    CONF_MF_COOLDOWN_SECONDS,
    CONF_MF_HIGH_CONFIDENCE_DISTANCE,
    CONF_MF_MIN_CONFIDENCE,
    CONF_MF_PING_PONG_WINDOW,
    CONF_MF_POSITION_OFFSET,
    CONF_MF_UNJOIN_DELAY,
    CONF_MF_VERIFY_DELAY,
    DEFAULT_MF_COOLDOWN_SECONDS,
    DEFAULT_MF_HIGH_CONFIDENCE_DISTANCE,
    DEFAULT_MF_MIN_CONFIDENCE,
    DEFAULT_MF_PING_PONG_WINDOW,
    DEFAULT_MF_POSITION_OFFSET,
    DEFAULT_MF_UNJOIN_DELAY,
    DEFAULT_MF_VERIFY_DELAY,
    DOMAIN,
    MUSIC_TRANSFER_COOLDOWN_SECONDS,
    PING_PONG_WINDOW_SECONDS,
    TRANSFER_VERIFY_DELAY_SECONDS,
    GROUP_UNJOIN_DELAY_SECONDS,
)
from .base import BaseCoordinator, CoordinatorAction, Intent

_LOGGER = logging.getLogger(__name__)


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
        self._high_confidence_distance = high_confidence_distance
        self._music_following = None

    async def async_setup(self) -> None:
        """Set up the coordinator.

        Retrieves the existing MusicFollowing instance from hass.data
        (already initialized by __init__.py) and applies configurable
        tuning parameters. If no MusicFollowing instance exists yet,
        logs a warning — it will be picked up on next reload.
        """
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is not None:
            self._music_following = mf
            # Apply configurable tuning parameters
            mf.MIN_CONFIDENCE = self._min_confidence
            # v3.6.24: Store high_confidence_distance on the MusicFollowing instance
            # so _on_person_transition can use it for BLE distance gating
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

        # Set up anomaly detector if injected
        if self.anomaly_detector is not None:
            self.anomaly_detector.register_metric(
                "transfer_success_rate",
                window_size=50,
                z_threshold=2.5,
            )
            self.anomaly_detector.register_metric(
                "cooldown_frequency",
                window_size=50,
                z_threshold=2.0,
            )
            _LOGGER.debug("MusicFollowingCoordinator: anomaly metrics registered")

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

    async def async_teardown(self) -> None:
        """Tear down the coordinator."""
        self._cancel_listeners()
        # Save anomaly baselines if available
        if self.anomaly_detector is not None:
            try:
                await self.anomaly_detector.async_save_baselines()
            except Exception as exc:
                _LOGGER.debug(
                    "MusicFollowingCoordinator: failed to save anomaly baselines: %s",
                    exc,
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
