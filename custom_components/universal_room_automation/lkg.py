"""Generic Last-Known-Good value with a code-owned physics-bounded envelope.

Wave 1 D1 extraction of the SOC LKG machinery shipped in v5.28.0 (see
`domain_coordinators/energy_battery.py:SOCEnvelope`). This module contains
the signal-agnostic primitive; per-signal physics factories (soc_bounds,
solar_upper_bounds, outdoor_temp_bounds) live in each coordinator's const
module alongside their physics constants.

Design invariant (the one Bug Class #53 — computed-but-not-consumed —
blocks): consumers ALWAYS ask for the envelope AND its freshness tier in
one call (``envelope(now) -> (lo, hi, tier)``); there is NO separate
``is_stale()`` predicate. Freshness is a byproduct of asking for the value.

Persistence: ``to_blob`` / ``from_blob`` round-trip ``value``, ``at``, and
``source``. ``bounds_fn`` is NOT persisted — the caller re-supplies it on
restore from its own constants module. This keeps physics constants
under review-controlled code (rung 1) rather than smuggled onto disk.

D1 status: SOCEnvelope in energy_battery.py is refactored to delegate its
envelope math through this primitive (mutation-anchored by the guard suite
``test_blind_window_evse_guard.py``). Solar (D2) and outdoor-temp (D3)
adoption is DEFERRED to wave 1 D2/D3 — this module ships in D1 as the
shared primitive with SOC as its sole consumer for now.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal, Optional

# Freshness tier returned alongside the envelope bounds.
#   fresh        — live-read cadence; envelope collapses to a point.
#   lkg_bounded  — physics-bounded envelope, safe for money-path decisions.
#   lkg_stale    — physics-bounded but wide; caller should require an
#                  explicit safety margin before acting.
#   expired      — beyond the physics-defensible age cap; treat as unknown.
Tier = Literal["fresh", "lkg_bounded", "lkg_stale", "expired"]

# Signature every per-signal physics factory produces. Given the persisted
# value, the timestamp it was captured at, and the current wall clock, return
# ``(lower, upper, tier)``. The bounds are in the signal's native unit (%SOC,
# watts, degrees F, etc.) — the primitive is unit-agnostic.
BoundsFn = Callable[[float, datetime, datetime], "tuple[float, float, Tier]"]


@dataclass
class LkgValue:
    """Last-Known-Good sample paired with a code-owned envelope function.

    Attributes:
        value: the raw scalar (%SOC, watts, apparent °F, ...).
        at: capture timestamp (tz-aware UTC by convention).
        source: free-form provenance label (e.g. ``"envoy"``, ``"solcast"``,
            ``"wpm.primary"``) — persisted, useful for observability and for
            downstream code that needs to distinguish which read tier
            supplied the last known value.
        bounds_fn: physics factory returning ``(lo, hi, tier)`` for a given
            ``(value, at, now)``. NOT persisted; the caller re-supplies it
            after :meth:`from_blob`.
    """

    value: float
    at: datetime
    source: str
    bounds_fn: Optional[BoundsFn] = None

    def envelope(self, now: datetime) -> "tuple[float, float, Tier]":
        """Return ``(lower, upper, tier)`` for the given wall-clock ``now``.

        The single call returns bounds + freshness tier together — Bug
        Class #53 blocker (no sibling ``is_stale`` predicate that a caller
        might forget to consult).
        """
        if self.bounds_fn is None:  # pragma: no cover - misconfig guard
            raise RuntimeError(
                "LkgValue.envelope called without bounds_fn — the caller "
                "must re-supply the physics factory after from_blob()."
            )
        return self.bounds_fn(self.value, self.at, now)

    # ------------------------------------------------------------------
    # Persistence — value/at/source round-trip. bounds_fn is code-owned.
    # ------------------------------------------------------------------
    def to_blob(self) -> dict:
        """Serialize to a persistence-safe dict (value + at_iso + source).

        Callers that share a persist slot with the shipped SOC blob
        (``{"value", "at_iso"}``) may drop ``source`` before writing —
        the from_blob path is None-safe on a missing key.
        """
        return {
            "value": float(self.value),
            "at_iso": self.at.isoformat(),
            "source": str(self.source),
        }

    @classmethod
    def from_blob(
        cls,
        blob: Optional[dict],
        bounds_fn: Optional[BoundsFn] = None,
        *,
        default_source: str = "restored",
    ) -> Optional["LkgValue"]:
        """Rehydrate from a persisted dict. Returns None on any malformed input.

        None-safe: ``blob is None``, missing keys, unparseable timestamps,
        and tz-naive datetimes are all handled cleanly (tz-naive is
        promoted to UTC to match the shipped ``restore_lkg_snapshot``
        behavior).
        """
        if not blob:
            return None
        try:
            raw_val: Any = blob.get("value")
            if raw_val is None:
                return None
            value = float(raw_val)
        except (TypeError, ValueError):
            return None
        at_iso = blob.get("at_iso")
        if not at_iso:
            return None
        parsed = _parse_iso(at_iso)
        if parsed is None:
            return None
        source = str(blob.get("source") or default_source)
        return cls(value=value, at=parsed, source=source, bounds_fn=bounds_fn)


def _parse_iso(at_iso: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, promoting tz-naive to UTC.

    Prefers ``homeassistant.util.dt.parse_datetime`` (matches the shipped
    ``restore_lkg_snapshot`` behavior) but falls back to
    :meth:`datetime.fromisoformat` under bare-Python test harnesses that
    don't stub ``homeassistant``.
    """
    try:  # pragma: no cover - trivial import branch
        from homeassistant.util import dt as dt_util
        parsed = dt_util.parse_datetime(at_iso)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        return parsed
    except Exception:  # noqa: BLE001
        try:
            parsed = datetime.fromisoformat(str(at_iso))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            from datetime import timezone
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
