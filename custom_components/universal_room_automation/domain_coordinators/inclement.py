"""Inclement-weather detection + TOU/solar-horizon-aware battery hold.

Robust Inclement-Weather Reserve cycle. Replaces URA's reliance on Enphase
Storm Guard (cloud-only, NWS-driven, no local veto, multi-day stale locks,
blunt 100% grid pre-charge) with a local **alert + condition fusion** that
produces a **graduated hold-depth decision** parameterized by:

  (a) confidence tier  — AlertClassifier (outage-relevance gate first)
  (b) current TOU period
  (c) solar recovery horizon — SolarHorizon (surplus-based, nets house load)

The three primitives are pure-derivation helpers (no IO except the surplus
reads delegated to the battery coordinator) so they are unit-testable in
isolation. ``InclementFusion.decide()`` fuses them into an
``InclementDecision`` consumed by ``EnergyBatteryCoordinator.determine_mode``.

Design property (load-bearing, D-A): **Event-type outage-relevance is the
PRIMARY gate.** Severity / Certainty / product-type (Watch vs Warning) are
independent CAP axes and are NEVER the gate — a Flood Watch (Severity=Severe)
fails the gate and exits as NOTICE because "Flood" is absent from the
power-threat list.

Robustness / bug-class prevention:
- #21 (timezone naive/aware): all datetime ops via dt_util; naive coerced.
- #22 (enum mismatch): tier / hold_depth Literals match the CONF policy values.
- None-safe throughout; malformed ``attributes.Alerts`` returns tier="none".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from homeassistant.util import dt as dt_util

from .energy_const import (
    DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
    DEFAULT_INCLEMENT_POWER_THREAT_EVENTS,
    DEFAULT_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
    DEFAULT_INCLEMENT_WARN_MIN_SEVERITY,
    DEFAULT_INCLEMENT_WATCH_REQUIRES_CORROBORATION,
    INCLEMENT_SEVERITY_ORDER,
)

_LOGGER = logging.getLogger(__name__)

# CAP statuses that represent a real, actionable alert. Everything else
# (Exercise / Test / Draft / System) is dropped before classification.
_ACTIONABLE_STATUS = "actual"

_Tier = Literal["warn", "watch", "notice", "none"]
_HoldDepth = Literal["full_hold", "partial_hold", "allow_discharge"]


# ---------------------------------------------------------------------------
# D1 — AlertClassifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlertClassification:
    """Result of classifying ``attributes.Alerts`` for outage relevance."""

    tier: _Tier
    contributing_events: tuple[str, ...]
    max_severity: str
    max_certainty: str
    expires_at: datetime | None  # min(Ends, Expires) across contributors
    raw_alert_count: int
    # Events that failed the outage-relevance gate (observability / debugging).
    gated_out_events: tuple[str, ...] = ()


def _severity_rank(severity: str | None) -> int:
    """Rank an NWS Severity string; unknown / missing → 0 (Unknown)."""
    if not severity:
        return 0
    try:
        return INCLEMENT_SEVERITY_ORDER.index(str(severity).strip().title())
    except ValueError:
        return 0


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO timestamp; coerce naive → local; None-safe."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        # Bug Class #21 — coerce naive to local before any comparison.
        try:
            return dt_util.as_local(dt)
        except Exception:  # noqa: BLE001
            return dt
    return dt


def _coerce_compatible(a: datetime, b: datetime) -> tuple[datetime, datetime]:
    """Return (a, b) both tz-aware or both naive so they can be compared.

    Production always passes tz-aware datetimes (dt_util.now()); tests may pass
    naive ones. When awareness mismatches, drop tzinfo from the aware side so
    the comparison never raises (Bug Class #21 robustness at the boundary).
    """
    a_aware = a.tzinfo is not None
    b_aware = b.tzinfo is not None
    if a_aware == b_aware:
        return a, b
    return (
        a.replace(tzinfo=None) if a_aware else a,
        b.replace(tzinfo=None) if b_aware else b,
    )


def _dt_le(a: datetime, b: datetime) -> bool:
    aa, bb = _coerce_compatible(a, b)
    return aa <= bb


def _dt_lt(a: datetime, b: datetime) -> bool:
    aa, bb = _coerce_compatible(a, b)
    return aa < bb


def _alert_expires_at(alert: dict[str, Any]) -> datetime | None:
    """min(Ends, Expires) for a single alert; None when neither parses."""
    candidates = [
        _parse_dt(alert.get("Ends")),
        _parse_dt(alert.get("Expires")),
    ]
    candidates = [c for c in candidates if c is not None]
    if not candidates:
        return None
    return min(candidates)


def _event_matches_threat(event: str, threat_events: list[str]) -> str | None:
    """Return the matched threat keyword (case-insensitive substring) or None."""
    if not event:
        return None
    event_l = event.lower()
    for keyword in threat_events:
        if keyword and keyword.lower() in event_l:
            return keyword
    return None


class AlertClassifier:
    """Pure classifier: gate → certainty → severity-noise-filter → tier."""

    def __init__(
        self,
        power_threat_events: list[str] | None = None,
        warn_min_severity: str | None = None,
    ) -> None:
        self._threat_events = list(
            power_threat_events
            if power_threat_events is not None
            else DEFAULT_INCLEMENT_POWER_THREAT_EVENTS
        )
        self._warn_min_severity = (
            warn_min_severity or DEFAULT_INCLEMENT_WARN_MIN_SEVERITY
        )

    def classify(
        self, alerts: Any, now: datetime | None = None,
    ) -> AlertClassification:
        """Classify the ``attributes.Alerts`` payload into a single tier.

        ``alerts`` may be None / [] / [{}] / a non-list — all yield tier=none
        with no exception (Bug Class — malformed sensor robustness).
        """
        if now is None:
            now = dt_util.now()

        empty = AlertClassification(
            tier="none",
            contributing_events=(),
            max_severity="Unknown",
            max_certainty="Unknown",
            expires_at=None,
            raw_alert_count=0,
            gated_out_events=(),
        )

        if not isinstance(alerts, list) or not alerts:
            return empty

        contributing: list[str] = []
        gated_out: list[str] = []
        expiries: list[datetime] = []
        tier_per_alert: list[_Tier] = []
        max_sev_rank = 0
        max_sev = "Unknown"
        max_cert = "Unknown"

        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            event = str(alert.get("Event", "") or "").strip()

            # Drop non-Actual statuses (Exercise / Test / Draft).
            status = str(alert.get("Status", "Actual") or "Actual").strip().lower()
            if status != _ACTIONABLE_STATUS:
                continue

            # Drop already-expired alerts.
            expires = _alert_expires_at(alert)
            if expires is not None and _dt_le(expires, now):
                continue

            # (1) OUTAGE-RELEVANCE GATE — the primary, load-bearing gate.
            matched = _event_matches_threat(event, self._threat_events)
            if matched is None:
                if event:
                    gated_out.append(event)
                continue

            # (2) CERTAINTY TIERING.
            certainty = str(alert.get("Certainty", "Unknown") or "Unknown").strip()
            cert_l = certainty.lower()
            if cert_l in ("observed", "likely"):
                tier: _Tier = "warn"
            else:  # possible / unlikely / unknown → watch-candidate
                tier = "watch"
            # Product-type folding: a "Warning" product promotes certainty
            # even when the Certainty field is conservative.
            if event.lower().endswith("warning"):
                tier = "warn"

            # (3) SEVERITY NOISE FILTER (secondary — never the gate).
            # A-MED-1 (resolved precedence — WORKING AS INTENDED): the severity
            # filter runs AFTER certainty/product-folding, so a product-folded
            # warn (e.g. a "...Warning" event) IS demotable when its Severity is
            # below warn_min_severity (Tornado Warning @ Moderate → watch). This
            # is the plan's intent: severity is a secondary filter that may
            # demote tier but never OVERRIDES the Event-type gate (a gated-out
            # event already exited above and can never be promoted back).
            severity = str(alert.get("Severity", "Unknown") or "Unknown").strip()
            if _severity_rank(severity) < _severity_rank(self._warn_min_severity):
                tier = _demote(tier)

            contributing.append(event)
            tier_per_alert.append(tier)
            if expires is not None:
                expiries.append(expires)
            srank = _severity_rank(severity)
            if srank >= max_sev_rank:
                max_sev_rank = srank
                max_sev = severity.title() if severity else "Unknown"
                max_cert = certainty.title() if certainty else "Unknown"

        final_tier = _max_tier(tier_per_alert)
        return AlertClassification(
            tier=final_tier,
            contributing_events=tuple(contributing),
            max_severity=max_sev,
            max_certainty=max_cert,
            expires_at=min(expiries) if expiries else None,
            raw_alert_count=len(alerts),
            gated_out_events=tuple(gated_out),
        )


_TIER_ORDER: dict[str, int] = {"none": 0, "notice": 1, "watch": 2, "warn": 3}


def _demote(tier: _Tier) -> _Tier:
    """warn→watch, watch→notice, notice/none unchanged."""
    if tier == "warn":
        return "watch"
    if tier == "watch":
        return "notice"
    return tier


def _max_tier(tiers: list[_Tier]) -> _Tier:
    if not tiers:
        return "none"
    return max(tiers, key=lambda t: _TIER_ORDER.get(t, 0))


# ---------------------------------------------------------------------------
# D2 — SolarHorizon (FIN-2 surplus-based recoverability + FIN-3 rung gate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SolarHorizon:
    """Solar recovery horizon for the partial-hold recoverability decision."""

    recoverable: bool | None  # None when not consulted (off_peak per FIN-3)
    surplus_pct_to_window: float | None
    permitted_discharge_pct: float | None
    margin_pct: float | None
    tomorrow_class: str  # poor|fair|good|unknown
    minutes_to_sunset: int | None
    minutes_to_risk_window_end: int | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "recoverable": self.recoverable,
            "surplus_pct_to_window": self.surplus_pct_to_window,
            "permitted_discharge_pct": self.permitted_discharge_pct,
            "margin_pct": self.margin_pct,
            "tomorrow_class": self.tomorrow_class,
            "minutes_to_sunset": self.minutes_to_sunset,
            "minutes_to_risk_window_end": self.minutes_to_risk_window_end,
            "reason": self.reason,
        }


# Tomorrow-solar classes that count as "expect sun to refill in the morning".
# A-HIGH-1 — the real domain of classify_tomorrow_solar() is
# {excellent, good, moderate, poor, unknown} (energy_battery.py:541-571) —
# there is NO "fair" class, and "moderate" over-permits discharge into a real
# watch. Restrict to the unambiguous "expect sun to refill" classes.
_GOOD_TOMORROW_CLASSES = {"good", "excellent"}


def compute_solar_horizon(
    battery: Any,
    tou_period: str,
    now: datetime,
    current_soc: float | None,
    alert_expires_at: datetime | None,
    partial_hold_reserve_floor: int = DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
    surplus_margin_pct: int = DEFAULT_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
) -> SolarHorizon:
    """Compute recoverability (FIN-2) gated by TOU rung (FIN-3).

    For ``off_peak`` callers this short-circuits to ``recoverable=None`` and
    DOES NOT call ``battery._expected_solar_surplus_pct`` — holding during
    off_peak forgoes no arbitrage discharge revenue, so recoverability is moot.

    For ``mid_peak`` / ``peak`` callers it projects the solar SURPLUS (net of
    house load via the v5.3.8 attainability machinery's SOLAR_CAPTURE_FACTOR)
    over the risk window and requires it to exceed the permitted discharge by
    a conservative margin.
    """
    minutes_to_sunset = _minutes_to_sunset(battery, now)

    # A-MED-3 — TODAY's sunset (projected onto now's local date), which may be
    # in the past. The today-path risk window MUST cap at this, NOT at
    # `minutes_to_sunset` (which rolls to tomorrow's ~24h-out sunset post-dusk
    # and would inflate the surplus projection).
    today_sunset = _today_sunset(battery, now)

    # FIN-3 — off_peak short-circuit. MUST NOT call the surplus helper.
    if tou_period == "off_peak":
        return SolarHorizon(
            recoverable=None,
            surplus_pct_to_window=None,
            permitted_discharge_pct=None,
            margin_pct=None,
            tomorrow_class=_safe_tomorrow_class(battery),
            minutes_to_sunset=minutes_to_sunset,
            minutes_to_risk_window_end=None,
            reason="off_peak_skip",
        )

    soc = float(current_soc) if current_soc is not None else 0.0
    permitted_discharge_pct = max(0.0, soc - float(partial_hold_reserve_floor))
    margin = float(surplus_margin_pct)

    # A-MED-3 — if there is no sun left TODAY (now past today's sunset), the
    # today-path cannot recover anything; force today_recoverable False and
    # let the overnight fallback decide. Skipping the surplus projection here
    # also avoids the ~24h-inflated risk window from next-day sunset.
    if today_sunset is not None and not _dt_lt(now, today_sunset):
        surplus_pct = 0.0
        mins_to_window = 0
        today_recoverable = False
        reason = "post_sunset_no_recovery_today"
    else:
        # Risk window end = min(alert.Expires, TODAY's sunset) from now.
        # Normalize candidates to `now`'s awareness before min()/subtraction.
        window_end_candidates = []
        for d in (alert_expires_at, today_sunset):
            if d is None:
                continue
            _, d_norm = _coerce_compatible(now, d)
            window_end_candidates.append(d_norm)
        window_end = min(window_end_candidates) if window_end_candidates else None
        if window_end is not None:
            now_norm, end_norm = _coerce_compatible(now, window_end)
            mins_to_window = max(0, int((end_norm - now_norm).total_seconds() // 60))
        else:
            mins_to_window = None

        # Project surplus into battery over the risk window (FIN-2). Nets house
        # load by construction (SOLAR_CAPTURE_FACTOR=0.5) — REUSES energy_battery.
        try:
            surplus_pct = float(
                battery._expected_solar_surplus_pct(now, mins_to_window)
            )
        except Exception:  # noqa: BLE001 — guard external read (#7 stale data)
            _LOGGER.debug(
                "compute_solar_horizon: surplus read failed", exc_info=True
            )
            surplus_pct = 0.0

        today_recoverable = surplus_pct >= permitted_discharge_pct + margin
        reason = "today_surplus_ok" if today_recoverable else "today_surplus_short"

    recoverable = today_recoverable
    if not today_recoverable:
        # Overnight fallback (rung-gated — only reached for mid_peak/peak).
        if _overnight_fallback(battery, now, alert_expires_at):
            recoverable = True
            reason = "overnight_fallback_tomorrow_good"

    return SolarHorizon(
        recoverable=recoverable,
        surplus_pct_to_window=round(surplus_pct, 2),
        permitted_discharge_pct=round(permitted_discharge_pct, 2),
        margin_pct=margin,
        tomorrow_class=_safe_tomorrow_class(battery),
        minutes_to_sunset=minutes_to_sunset,
        minutes_to_risk_window_end=mins_to_window,
        reason=reason,
    )


def _safe_tomorrow_class(battery: Any) -> str:
    try:
        return str(battery.classify_tomorrow_solar())
    except Exception:  # noqa: BLE001
        return "unknown"


def _overnight_fallback(
    battery: Any, now: datetime, alert_expires_at: datetime | None,
) -> bool:
    """classify_tomorrow_solar() good AND alert expires before tomorrow's
    sunrise + 2h (i.e. discharge happens overnight, sun refills by morning)."""
    if alert_expires_at is None:
        return False
    tomorrow_class = _safe_tomorrow_class(battery)
    if tomorrow_class not in _GOOD_TOMORROW_CLASSES:
        return False
    try:
        sunrise_tom, _ = battery._daylight_bounds(now + timedelta(days=1))
    except Exception:  # noqa: BLE001
        sunrise_tom = None
    if sunrise_tom is None:
        return False
    return _dt_lt(alert_expires_at, sunrise_tom + timedelta(hours=2))


def _today_sunset(battery: Any, now: datetime) -> datetime | None:
    """TODAY's sunset projected onto ``now``'s local date (may be in the past).

    Distinct from ``_minutes_to_sunset`` (which rolls forward to tomorrow's
    sunset once today's has passed). A-MED-3 needs today's sunset specifically
    so the today-path risk window does not inflate to ~24h after dusk.
    """
    try:
        _, sunset_today = battery._daylight_bounds(now)
    except Exception:  # noqa: BLE001
        return None
    return sunset_today


def _minutes_to_sunset(battery: Any, now: datetime) -> int | None:
    """Minutes from ``now`` until the next sunset (today's, else tomorrow's)."""
    try:
        _, sunset_today = battery._daylight_bounds(now)
    except Exception:  # noqa: BLE001
        sunset_today = None
    if sunset_today is not None and sunset_today > now:
        return max(0, int((sunset_today - now).total_seconds() // 60))
    try:
        _, sunset_tom = battery._daylight_bounds(now + timedelta(days=1))
    except Exception:  # noqa: BLE001
        sunset_tom = None
    if sunset_tom is not None and sunset_tom > now:
        return max(0, int((sunset_tom - now).total_seconds() // 60))
    return None


# ---------------------------------------------------------------------------
# D5 — InclementFusion.decide()
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InclementDecision:
    """Fused decision consumed by determine_mode."""

    hold_depth: _HoldDepth
    grid_precharge: bool
    tier: str  # warn|watch|notice|none
    source: str  # alert|condition|both|none
    contributing_event: str | None
    expires_at: datetime | None
    reserve_floor: int  # 0-100 — the floor passed to determine_mode
    reason: str
    solar_horizon: SolarHorizon

    def expires_at_iso(self) -> str | None:
        return self.expires_at.isoformat() if self.expires_at else None


def _allow_discharge_decision(
    reserve_soc: int,
    tier: str = "none",
    source: str = "none",
    reason: str = "no_inclement",
    horizon: SolarHorizon | None = None,
    contributing_event: str | None = None,
    expires_at: datetime | None = None,
) -> InclementDecision:
    return InclementDecision(
        hold_depth="allow_discharge",
        grid_precharge=False,
        tier=tier,
        source=source,
        contributing_event=contributing_event,
        expires_at=expires_at,
        reserve_floor=reserve_soc,
        reason=reason,
        solar_horizon=horizon or _na_horizon(),
    )


def _na_horizon() -> SolarHorizon:
    return SolarHorizon(
        recoverable=None,
        surplus_pct_to_window=None,
        permitted_discharge_pct=None,
        margin_pct=None,
        tomorrow_class="unknown",
        minutes_to_sunset=None,
        minutes_to_risk_window_end=None,
        reason="not_consulted",
    )


class InclementFusion:
    """Fuse alert classification + condition election + solar horizon → decision."""

    def __init__(
        self,
        reserve_soc: int,
        partial_hold_reserve_floor: int = DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
        grid_precharge_on_hold: bool = False,
        watch_requires_corroboration: bool = DEFAULT_INCLEMENT_WATCH_REQUIRES_CORROBORATION,
        surplus_margin_pct: int = DEFAULT_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
        storm_charge_threshold: int = 90,
    ) -> None:
        self._reserve_soc = int(reserve_soc)
        self._partial_floor = int(partial_hold_reserve_floor)
        self._grid_precharge_on_hold = bool(grid_precharge_on_hold)
        self._watch_requires_corroboration = bool(watch_requires_corroboration)
        self._surplus_margin_pct = int(surplus_margin_pct)
        self._storm_charge_threshold = int(storm_charge_threshold)

    def decide(
        self,
        battery: Any,
        classification: AlertClassification,
        condition_stormy: bool,
        condition_provider_count: int,
        tou_period: str,
        now: datetime,
        current_soc: float | None,
    ) -> InclementDecision:
        """Produce the InclementDecision (matrix in PLANNING §Design)."""
        tier = classification.tier
        has_alert_hold = tier in ("warn", "watch")

        # No alert hold AND no corroborated condition → allow_discharge.
        condition_only = (not has_alert_hold) and condition_stormy and (
            condition_provider_count >= 2
        )
        if not has_alert_hold and not condition_only:
            return _allow_discharge_decision(
                self._reserve_soc,
                tier=tier,
                source="alert" if classification.raw_alert_count else "none",
                reason=f"tier_{tier}_allow_discharge",
            )

        # ── warn tier ────────────────────────────────────────────────────
        if tier == "warn":
            # Warn always holds at any TOU period; recoverability not consulted.
            grid_precharge = (
                self._grid_precharge_on_hold
                and tou_period == "off_peak"
                and current_soc is not None
                and current_soc < self._storm_charge_threshold
            )
            return InclementDecision(
                hold_depth="full_hold",
                grid_precharge=grid_precharge,
                tier="warn",
                source="alert",
                contributing_event=_first(classification.contributing_events),
                expires_at=classification.expires_at,
                reserve_floor=self._full_hold_floor(current_soc),
                reason="warn_full_hold",
                solar_horizon=_na_horizon(),
            )

        # ── watch tier ───────────────────────────────────────────────────
        if tier == "watch":
            corroborated = (not self._watch_requires_corroboration) or (
                condition_stormy and condition_provider_count >= 1
            )
            if not corroborated:
                # Uncorroborated watch: off_peak partial_hold; mid/peak discharge.
                if tou_period == "off_peak":
                    return InclementDecision(
                        hold_depth="partial_hold",
                        grid_precharge=False,
                        tier="watch",
                        source="alert",
                        contributing_event=_first(classification.contributing_events),
                        expires_at=classification.expires_at,
                        reserve_floor=self._partial_floor_value(current_soc),
                        reason="watch_uncorroborated_offpeak_partial_hold",
                        solar_horizon=_na_horizon(),
                    )
                return _allow_discharge_decision(
                    self._reserve_soc,
                    tier="watch",
                    source="alert",
                    reason="watch_uncorroborated_allow_discharge",
                    contributing_event=_first(classification.contributing_events),
                    expires_at=classification.expires_at,
                )

            # Corroborated watch.
            if tou_period == "off_peak":
                # Off_peak holds readily (FIN-3 — recoverability not consulted).
                grid_precharge = (
                    self._grid_precharge_on_hold
                    and current_soc is not None
                    and current_soc < self._storm_charge_threshold
                )
                return InclementDecision(
                    hold_depth="full_hold",
                    grid_precharge=grid_precharge,
                    tier="watch",
                    source="alert",
                    contributing_event=_first(classification.contributing_events),
                    expires_at=classification.expires_at,
                    reserve_floor=self._full_hold_floor(current_soc),
                    reason="watch_corroborated_offpeak_full_hold",
                    solar_horizon=_na_horizon(),
                )

            # mid_peak / peak corroborated watch — consult recoverability.
            horizon = compute_solar_horizon(
                battery,
                tou_period,
                now,
                current_soc,
                classification.expires_at,
                partial_hold_reserve_floor=self._partial_floor,
                surplus_margin_pct=self._surplus_margin_pct,
            )
            if horizon.recoverable:
                return InclementDecision(
                    hold_depth="partial_hold",
                    grid_precharge=False,
                    tier="watch",
                    source="alert",
                    contributing_event=_first(classification.contributing_events),
                    expires_at=classification.expires_at,
                    reserve_floor=self._partial_floor_value(current_soc),
                    reason="watch_corroborated_recoverable_partial_hold",
                    solar_horizon=horizon,
                )
            return InclementDecision(
                hold_depth="full_hold",
                grid_precharge=False,
                tier="watch",
                source="alert",
                contributing_event=_first(classification.contributing_events),
                expires_at=classification.expires_at,
                reserve_floor=self._full_hold_floor(current_soc),
                reason="watch_corroborated_not_recoverable_full_hold",
                solar_horizon=horizon,
            )

        # ── condition-only path (NWS sensor absent / no alert tier) ───────
        # ≥2 healthy providers stormy: off_peak partial_hold; mid/peak discharge.
        if condition_only:
            if tou_period == "off_peak":
                return InclementDecision(
                    hold_depth="partial_hold",
                    grid_precharge=False,
                    tier="notice",
                    source="condition",
                    contributing_event=None,
                    expires_at=None,
                    reserve_floor=self._partial_floor_value(current_soc),
                    reason="condition_only_offpeak_partial_hold",
                    solar_horizon=_na_horizon(),
                )
            return _allow_discharge_decision(
                self._reserve_soc,
                tier="notice",
                source="condition",
                reason="condition_only_allow_discharge",
            )

        # Fallback (unreachable in practice).
        return _allow_discharge_decision(self._reserve_soc, tier=tier)

    # -- floor helpers ----------------------------------------------------

    def _full_hold_floor(self, current_soc: float | None) -> int:
        """full_hold preserves everything: hold at current SOC (clamp 0-100).

        Mirrors today's BACKUP behavior (no discharge). When SOC unknown,
        defaults to 100 (hold all) — conservative.
        """
        if current_soc is None:
            return 100
        return max(0, min(100, int(current_soc)))

    def _partial_floor_value(self, current_soc: float | None) -> int:
        """partial_hold floor = max(reserve_soc, configured partial floor)."""
        return max(self._reserve_soc, self._partial_floor)


def _first(events: tuple[str, ...]) -> str | None:
    return events[0] if events else None
