"""LightPolicyOracle — D2 light manual hold (v5.103.28 Slice C).

Mirrors the shape of ``fan_policy_oracle.FanPolicyOracle`` (verdicts +
RAM-only ledger + ``release``), scoped per room AND per light.

Invariant (plan D2 + REV 2.3.1): no URA write ever opens a hold (writes are
stamped, see ``ura_context``); a person's change to a room light while the
room is occupied is never undone by URA until the room counts as empty.

Ledger per ``(room_key, entity_id)``:

* ``on_hold_until`` — a person turned the light ON while occupied. URA's
  OFF paths skip the light until this passes or the room empties
  (``release_on_vacancy``).
* ``off_cooldown_until`` — a person turned the light OFF while occupied.
  URA's ON paths skip the light until this passes. It survives the vacancy
  transition on purpose (it protects the OFF against a re-triggered entry).

Room key = the room config entry_id (same string at every consumer:
RoomAutomation, ActuatorReconciler, HVAC zone sweep, RoomLightsSwitch).

Exception posture: any internal failure ALLOWS the URA write (today's
behaviour) — the hold can only ever suppress, never invent, a write.
RAM-only: a restart forgets holds (the fan oracle precedent).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Literal

_LOGGER = logging.getLogger(__name__)

LIGHT_ORACLE_KEY = "light_oracle"


@dataclass
class _LightRecord:
    on_hold_until: datetime | None = None
    off_cooldown_until: datetime | None = None


class LightPolicyOracle:
    """Per-room, per-light manual hold ledger."""

    def __init__(self) -> None:
        self._rooms: dict[str, dict[str, _LightRecord]] = {}

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    def note_manual(
        self,
        room_key: str,
        entity_id: str,
        direction: Literal["on", "off"],
        *,
        now: datetime,
        on_hold_s: float,
        off_cooldown_s: float,
    ) -> None:
        """Record a person's change. ON opens a hold, OFF a cooldown.

        The opposite kind is cleared (the newest instruction wins).
        A window of 0 disables that kind (nothing is opened).
        """
        try:
            rec = self._rooms.setdefault(room_key, {}).setdefault(
                entity_id, _LightRecord(),
            )
            if direction == "on":
                rec.off_cooldown_until = None
                rec.on_hold_until = (
                    now + timedelta(seconds=float(on_hold_s))
                    if float(on_hold_s) > 0 else None
                )
            elif direction == "off":
                rec.on_hold_until = None
                rec.off_cooldown_until = (
                    now + timedelta(seconds=float(off_cooldown_s))
                    if float(off_cooldown_s) > 0 else None
                )
        except Exception:  # noqa: BLE001
            _LOGGER.error(
                "LightPolicyOracle.note_manual failed room=%s entity=%s",
                room_key, entity_id, exc_info=True,
            )

    def release_on_vacancy(self, room_key: str) -> None:
        """The room counts as empty: end every ON hold (cooldowns stay)."""
        try:
            for rec in (self._rooms.get(room_key) or {}).values():
                rec.on_hold_until = None
        except Exception:  # noqa: BLE001
            _LOGGER.error(
                "LightPolicyOracle.release_on_vacancy failed room=%s",
                room_key, exc_info=True,
            )

    def release(self, room_key: str) -> None:
        """Drop every hold and cooldown for the room."""
        self._rooms.pop(room_key, None)

    # ------------------------------------------------------------------
    # Verdicts
    # ------------------------------------------------------------------

    def may_turn_off(self, room_key: str, entity_id: str, now: datetime) -> bool:
        try:
            rec = (self._rooms.get(room_key) or {}).get(entity_id)
            if rec is None or rec.on_hold_until is None:
                return True
            return not now < rec.on_hold_until
        except Exception:  # noqa: BLE001 — fail toward today's behaviour
            return True

    def may_turn_on(self, room_key: str, entity_id: str, now: datetime) -> bool:
        try:
            rec = (self._rooms.get(room_key) or {}).get(entity_id)
            if rec is None or rec.off_cooldown_until is None:
                return True
            return not now < rec.off_cooldown_until
        except Exception:  # noqa: BLE001
            return True

    def allowed(
        self,
        room_key: str,
        entities: Iterable[str],
        direction: Literal["on", "off"],
        now: datetime,
    ) -> list[str]:
        """Return the subset of ``entities`` URA may move in ``direction``."""
        check = self.may_turn_on if direction == "on" else self.may_turn_off
        return [e for e in entities if check(room_key, e, now)]

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    def get_state(self, room_key: str) -> dict[str, dict[str, Any]]:
        """Snapshot for display / tests: entity -> {on_hold_until, off_cooldown_until}."""
        out: dict[str, dict[str, Any]] = {}
        for eid, rec in (self._rooms.get(room_key) or {}).items():
            out[eid] = {
                "on_hold_until": rec.on_hold_until,
                "off_cooldown_until": rec.off_cooldown_until,
            }
        return out


def get_light_oracle(hass: Any, domain: str) -> LightPolicyOracle | None:
    """Return the shared oracle in ``hass.data[domain]``, creating it lazily."""
    try:
        data = getattr(hass, "data", None)
        if not isinstance(data, dict):
            return None
        bucket = data.setdefault(domain, {})
        if not isinstance(bucket, dict):
            return None
        oracle = bucket.get(LIGHT_ORACLE_KEY)
        if oracle is None or not hasattr(oracle, "may_turn_off"):
            oracle = LightPolicyOracle()
            bucket[LIGHT_ORACLE_KEY] = oracle
        return oracle
    except Exception:  # noqa: BLE001
        _LOGGER.debug("get_light_oracle failed", exc_info=True)
        return None
