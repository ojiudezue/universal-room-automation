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
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from homeassistant.util import dt as dt_util

from .energy_outage_ledger import alert_key
from .energy_const import (
    DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
    DEFAULT_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT,
    DEFAULT_INCLEMENT_WATCH_REQUIRES_CORROBORATION,
    CONF_INCLEMENT_BUY_ADDED,
    CONF_INCLEMENT_BUY_REMOVED,
    CONF_INCLEMENT_HOLD_ADDED,
    CONF_INCLEMENT_HOLD_REMOVED,
    INCLEMENT_ALERT_MAX_HOLD_H,
    INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT,
    INCLEMENT_FORECAST_FAMILY,
    INCLEMENT_GRID_CHARGE_PP_PER_H,
    INCLEMENT_POINT_FEED_POLYGON_EXACT,
    INCLEMENT_POLYGON_TOPUP_MAX_MIN,
    INCLEMENT_PREONSET_BUY_MARGIN_H,
    INCLEMENT_PREONSET_FLOOR_LEAD_H,
    INCLEMENT_PREONSET_FLOOR_PCT,
    INCLEMENT_PREONSET_LEAD_H,
    INCLEMENT_PRODUCT_TABLE,
    INCLEMENT_SEVERITY_ORDER,
    INCLEMENT_UNVERIFIED_POLYGON_TIER,
    NWS_WEATHER_EVENT_NAMES,
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
class AlertRecord:
    """One table-matched, filtered alert (EC storm Stage B D-B1/D-B2).

    ``tier`` is the EFFECTIVE tier (table tier, or ``notice`` for a polygon
    row under the unverified-polygon switch). ``start``/``end`` are the
    hazard window (``_hazard_window``); ``start`` None = no lower bound.
    """

    alert_id: str | None
    event: str
    code: str | None
    cls: str  # table class: warn | watch | notice
    tier: str  # effective tier
    polygon_local: bool
    precharge_eligible: bool
    start: datetime | None
    end: datetime
    # Stage E E1.3 / INV-7(c): False for an unlisted or selection-widened
    # record (never buys, never corroborates a watch on any leg).
    corroborable: bool = True


@dataclass(frozen=True)
class AlertClassification:
    """Result of classifying ``attributes.Alerts`` for outage relevance."""

    tier: _Tier
    contributing_events: tuple[str, ...]
    max_severity: str
    max_certainty: str
    # EC storm Stage B D-B1: max(end) over ACTIVE HOLD contributors (was
    # min(Ends, Expires) over all contributors). None = no HOLD contributor.
    expires_at: datetime | None
    raw_alert_count: int
    # Alerts with no product-table row (observability / debugging).
    gated_out_events: tuple[str, ...] = ()
    # Stage B: active HOLD records (start <= now <= end, effective tier
    # warn/watch) — consumed by the eligibility / forecast gates.
    hold_alerts: tuple[AlertRecord, ...] = ()
    # Stage B D-B2: code/name disagreements seen this tick:
    # (event, observed_code, kind) with kind "mismatch" or "observed_code".
    drift: tuple[tuple[str, str | None, str], ...] = ()
    # D-B6 prepare set: non-polygon HOLD records with
    # now < start <= now + INCLEMENT_PREONSET_LEAD_H (never feed tier /
    # expires_at).
    prepare_alerts: tuple[AlertRecord, ...] = ()
    # D-B2a flags (computed by the guarded `_precharge_flags`):
    #   precharge_eligible — some ACTIVE non-polygon HOLD record is eligible;
    #   polygon_topup_active — some ACTIVE verified-local polygon record is
    #     inside [start, min(end, start + INCLEMENT_POLYGON_TOPUP_MAX_MIN)];
    #   prepare_precharge_eligible — some prepare record of the prepare class
    #     is eligible.
    precharge_eligible: bool = False
    polygon_topup_active: bool = False
    prepare_precharge_eligible: bool = False
    # Stage E E1.7 (display only): every ACTIVE record incl. notice, for the
    # `inclement_selection` attr. No decision path reads it.
    active_alerts: tuple[AlertRecord, ...] = ()


def prepare_class_of(records: tuple[AlertRecord, ...] | list[AlertRecord]) -> str | None:
    """D-B6: "warn" if any warn row, else "watch"; None when empty."""
    if not records:
        return None
    return "warn" if any(r.cls == "warn" for r in records) else "watch"


def polygon_topup_records(
    hold: list[AlertRecord] | tuple[AlertRecord, ...], now: datetime,
) -> list[AlertRecord]:
    """D-B2a polygon immediate leg predicate (ONE definition, shared by the
    decision flag and the grid-buy stamp): ACTIVE verified-local eligible
    polygon records inside ``[start, min(end, start + cap)]``. Cap 0 or an
    unverified point feed → []. May raise (callers guard)."""
    out: list[AlertRecord] = []
    cap = int(INCLEMENT_POLYGON_TOPUP_MAX_MIN)
    if cap <= 0 or not INCLEMENT_POINT_FEED_POLYGON_EXACT:
        return out
    for r in hold:
        if not (r.polygon_local and r.precharge_eligible):
            continue
        if r.start is None:
            continue
        cap_end = r.start + timedelta(minutes=cap)
        stop = r.end if _dt_lt(r.end, cap_end) else cap_end
        if _dt_le(r.start, now) and _dt_le(now, stop):
            out.append(r)
    return out


def _precharge_flags(
    hold: list[AlertRecord], prepare: list[AlertRecord], now: datetime,
) -> tuple[bool, bool, bool]:
    """D-B2a guarded helper (Rev 3.3 M1). Any exception → (False, False,
    False) with one debug log, so it can never reach the `classify_error`
    fallback and never lose a hold."""
    try:
        eligible = any(
            r.precharge_eligible and not r.polygon_local for r in hold
        )
        topup = bool(polygon_topup_records(hold, now))
        pclass = prepare_class_of(prepare)
        prep_eligible = any(
            r.precharge_eligible and r.cls == pclass for r in prepare
        )
        return eligible, topup, prep_eligible
    except Exception:  # noqa: BLE001
        _LOGGER.debug("inclement: _precharge_flags failed", exc_info=True)
        return False, False, False


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


def _dt_max(values: list[datetime]) -> datetime | None:
    best: datetime | None = None
    for v in values:
        if best is None or _dt_lt(best, v):
            best = v
    return best


# Message key of one NWS alert (``ID``, else ``URL``, else Event|Sent).
# REUSED from the outage ledger (A-LOW-2): memory entries and ledger rows
# must name the same message, so there is exactly one implementation.
alert_id = alert_key


def _hazard_window(
    alert: dict[str, Any],
) -> tuple[datetime | None, datetime | None]:
    """D-B1: ``start = Onset or Sent``; ``end = Ends or Expires or start +
    INCLEMENT_ALERT_MAX_HOLD_H``. Unparseable values are treated as missing.
    (None, None) = unbounded on both sides (contributes nothing)."""
    start = _parse_dt(alert.get("Onset")) or _parse_dt(alert.get("Sent"))
    end = _parse_dt(alert.get("Ends")) or _parse_dt(alert.get("Expires"))
    # Stage E fix-up (AUDIT_nws_alert_fields_and_updates): an end at or
    # before the start (e.g. Ends null and Onset == Expires) is not a window.
    if start is not None and (end is None or _dt_le(end, start)):
        end = start + timedelta(hours=INCLEMENT_ALERT_MAX_HOLD_H)
    return start, end


def _is_actual(alert: dict[str, Any]) -> bool:
    status = str(alert.get("Status", "Actual") or "Actual").strip().lower()
    return status == _ACTIONABLE_STATUS


def _is_cancel(alert: dict[str, Any]) -> bool:
    return str(alert.get("Type", "") or "").strip().lower() == "cancel"


# ---------------------------------------------------------------------------
# Stage E E1 — operator alert selection over the internal product table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InclementSelection:
    """Effective operator selection (PLANNING_ec_storm_stage_e.md §E1.3).

    All names case-folded. ``hold`` / ``buy`` are the EFFECTIVE sets over the
    selection domain (NWS_WEATHER_EVENT_NAMES); ``buy`` is already clamped to
    ``hold ∩ (forecast family ∪ polygon rows) ∩ corroborable`` (INV-7(c)/(d)
    at runtime). ``widened`` = table notice rows added to hold; ``unlisted``
    = held names with no table row. ``overrides`` keeps the four stored
    delta lists (canonical spellings, vocabulary-filtered) for display.
    The selection chooses WHETHER a product holds / buys, never HOW
    (INV-7): it never changes locality, thresholds or the polygon cap.
    """

    hold: frozenset[str]
    buy: frozenset[str]
    widened: frozenset[str] = frozenset()
    unlisted: frozenset[str] = frozenset()
    overrides: tuple[tuple[str, tuple[str, ...]], ...] = ()


_UNKNOWN_SELECTION_LOGGED: set[str] = set()


def build_selection(options: Any) -> InclementSelection:
    """Pure: the effective selection from the four stored override lists.

    Unknown / out-of-vocabulary stored names are ignored (one debug log per
    name per process). Retired table rows (not in the vocabulary) are
    outside the domain: table behaviour always."""
    opts = options if isinstance(options, Mapping) else {}
    vocab = {n.casefold(): n for n in NWS_WEATHER_EVENT_NAMES}

    def _names(key: str) -> list[str]:
        raw = opts.get(key)
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return []
        out: list[str] = []
        for v in raw:
            cf = str(v).strip().casefold()
            if cf in vocab:
                if vocab[cf] not in out:
                    out.append(vocab[cf])
            elif cf and cf not in _UNKNOWN_SELECTION_LOGGED:
                _UNKNOWN_SELECTION_LOGGED.add(cf)
                _LOGGER.debug(
                    "inclement selection: ignoring unknown stored name %r "
                    "(%s)", v, key,
                )
        return out

    lists = {
        k: _names(k)
        for k in (CONF_INCLEMENT_HOLD_ADDED, CONF_INCLEMENT_HOLD_REMOVED,
                  CONF_INCLEMENT_BUY_ADDED, CONF_INCLEMENT_BUY_REMOVED)
    }
    table: dict[str, tuple] = {}
    for row in INCLEMENT_PRODUCT_TABLE:
        table.setdefault(row[1].casefold(), row)
    default_hold = {
        cf for cf, row in table.items()
        if row[2] in ("warn", "watch") and cf in vocab
    }
    default_buy = {cf for cf, row in table.items() if row[4] and cf in vocab}
    corroborable = {cf for cf, row in table.items() if row[2] in ("warn", "watch")}
    can_buy = {cf for cf, row in table.items() if row[3]} | {
        n.casefold() for n in INCLEMENT_FORECAST_FAMILY
    }

    def _cf(key: str) -> set[str]:
        return {n.casefold() for n in lists[key]}

    hold = (default_hold - _cf(CONF_INCLEMENT_HOLD_REMOVED)) | _cf(
        CONF_INCLEMENT_HOLD_ADDED,
    )
    buy = (
        ((default_buy - _cf(CONF_INCLEMENT_BUY_REMOVED))
         | _cf(CONF_INCLEMENT_BUY_ADDED))
        & hold & can_buy & corroborable
    )
    return InclementSelection(
        hold=frozenset(hold),
        buy=frozenset(buy),
        widened=frozenset(
            cf for cf in hold if cf in table and table[cf][2] == "notice"
        ),
        unlisted=frozenset(cf for cf in hold if cf not in table),
        overrides=tuple((k, tuple(v)) for k, v in lists.items()),
    )


# The zero-override selection (the table defaults) at import time. Callers
# that omit `selection` get `build_selection({})` from the CURRENT table
# (`_resolve_selection`), which equals this constant unless the table is
# replaced (tests). Never mutated (frozen dataclass of frozensets).
TABLE_SELECTION: InclementSelection = build_selection({})


def selection_form_defaults(options: Any) -> tuple[list[str], list[str]]:
    """Stage E E1.6 rendering: the EFFECTIVE hold / buy lists as canonical
    vocabulary spellings (vocabulary order). Stored names no longer in the
    vocabulary are never rendered (HA's selector rejects unknown values)."""
    sel = build_selection(options)
    hold = [n for n in NWS_WEATHER_EVENT_NAMES if n.casefold() in sel.hold]
    buy = [n for n in NWS_WEATHER_EVENT_NAMES if n.casefold() in sel.buy]
    return hold, buy


def selection_form_deltas(
    hold_submitted: Any, buy_submitted: Any,
) -> tuple[dict[str, list[str]], str | None]:
    """Stage E E1.6 submit: the four override lists (deltas vs the table
    defaults over the selection domain) + the first validation error key
    for the buy field (None = valid). Retired table rows are outside the
    domain, so they never produce a delta."""
    def _canon(raw: Any) -> list[str]:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return []
        cfs = {str(v).strip().casefold() for v in raw}
        return [n for n in NWS_WEATHER_EVENT_NAMES if n.casefold() in cfs]

    hold = _canon(hold_submitted)
    buy = _canon(buy_submitted)
    table = build_selection({})  # zero overrides = the table defaults
    default_hold = [n for n in NWS_WEATHER_EVENT_NAMES if n.casefold() in table.hold]
    default_buy = [n for n in NWS_WEATHER_EVENT_NAMES if n.casefold() in table.buy]
    hold_cf = {n.casefold() for n in hold}
    buy_cf = {n.casefold() for n in buy}
    error: str | None = None
    family = {n.casefold() for n in INCLEMENT_FORECAST_FAMILY}
    for n in buy:
        cf = n.casefold()
        # The table row via the single table iterator (zero overrides).
        row = match_product({"Event": n}, table)[0]
        if cf not in hold_cf:
            error = "buy_not_in_hold"
            break
        if cf not in family and not (row is not None and row[3]):
            error = "buy_needs_forecast"
            break
        if cf not in table.hold:  # default class is not warn/watch
            error = "buy_needs_table_hold"
            break
    deltas = {
        CONF_INCLEMENT_HOLD_ADDED: [n for n in hold if n not in default_hold],
        CONF_INCLEMENT_HOLD_REMOVED: [
            n for n in default_hold if n.casefold() not in hold_cf
        ],
        CONF_INCLEMENT_BUY_ADDED: [n for n in buy if n not in default_buy],
        CONF_INCLEMENT_BUY_REMOVED: [
            n for n in default_buy if n.casefold() not in buy_cf
        ],
    }
    return deltas, error


def _resolve_selection(selection: InclementSelection | None) -> InclementSelection:
    """None = the zero-override selection built from the CURRENT table
    (byte-identical to the table; robust to a monkeypatched table)."""
    return selection if selection is not None else build_selection({})


def _overlay(
    row: tuple, selection: InclementSelection,
) -> tuple[tuple, bool]:
    """Stage E E1.3 overlay of a TABLE row: (effective 5-tuple, corroborable).
    Positions 0-4 keep their meaning; ``polygon_local`` (3) is never
    changed (INV-7(a))."""
    name_cf = row[1].casefold()
    default_hold = row[2] in ("warn", "watch")
    if name_cf not in {n.casefold() for n in NWS_WEATHER_EVENT_NAMES}:
        return row, default_hold  # retired row: table behaviour always
    eligible = name_cf in selection.buy
    if name_cf not in selection.hold:
        if default_hold:
            return (row[0], row[1], "notice", row[3], False), True
        return (row[0], row[1], row[2], row[3], False), False
    if not default_hold:
        return (row[0], row[1], "watch", row[3], eligible), False
    return (row[0], row[1], row[2], row[3], eligible), True


def match_product(
    alert: dict[str, Any],
    selection: InclementSelection | None = None,
) -> tuple[tuple | None, tuple[str, str | None, str] | None, bool]:
    """D-B2: match by NWS code (coded rows) OR exact case-folded event name.

    Stage E E1.3: the matched table row is passed through the operator
    ``selection`` overlay (default = zero overrides, byte-identical), and an
    unlisted vocabulary name the operator added to hold matches a synthetic
    watch row ``(None, event, "watch", False, False)`` with no drift.

    Returns (row, drift, corroborable). ``drift`` is (event, observed_code, kind):
    ``"mismatch"`` when code and name point at different rows (or one of
    them matches no row while the other does), ``"observed_code"`` when a
    name-only row is matched and the alert carries a code (records the
    first observed code; the battery dedups per boot). The code row wins a
    disagreement (codes are probe-verified).
    """
    sel = _resolve_selection(selection)
    event = str(alert.get("Event", "") or "").strip()
    code_raw = alert.get("NWSCode")
    code = str(code_raw).strip().upper() if code_raw else None
    ev_cf = event.casefold()
    name_row = None
    code_row = None
    for row in INCLEMENT_PRODUCT_TABLE:
        if name_row is None and row[1].casefold() == ev_cf:
            name_row = row
        if code is not None and code_row is None and row[0] == code:
            code_row = row
    drift = None
    if code_row is not None and code_row is not name_row:
        drift = (event, code, "mismatch")
    elif name_row is not None and code is not None:
        if name_row[0] is not None and name_row[0] != code:
            drift = (event, code, "mismatch")
        elif name_row[0] is None:
            drift = (event, code, "observed_code")
    row = code_row or name_row
    if row is None:
        if ev_cf and ev_cf in sel.unlisted:
            # Unlisted operator-held product: synthetic zone watch, capped
            # (never buys, never corroborates), no drift reporting.
            return (None, event, "watch", False, False), None, False
        return None, drift, False
    eff, corroborable = _overlay(row, sel)
    return eff, drift, corroborable


def _effective_tier(row: tuple) -> str:
    """Table tier, or the unverified-polygon switch for polygon rows when
    the point feed is not polygon-exact (D-B1 / Q7)."""
    cls = row[2]
    if row[3] and not INCLEMENT_POINT_FEED_POLYGON_EXACT:
        if INCLEMENT_UNVERIFIED_POLYGON_TIER == "notice":
            return "notice"
    return cls


def build_record(
    alert: dict[str, Any],
    selection: InclementSelection | None = None,
) -> AlertRecord | None:
    """Status/Type-filtered, table-matched record with its hazard window.
    None = not Actual, a Cancel, no table row, or no usable window.
    Stage E: ``cls`` / ``tier`` / ``precharge_eligible`` / ``corroborable``
    are the selection-overlaid values."""
    if not isinstance(alert, dict) or not _is_actual(alert) or _is_cancel(alert):
        return None
    row, _drift, corroborable = match_product(alert, selection)
    if row is None:
        return None
    start, end = _hazard_window(alert)
    if end is None:
        return None
    return AlertRecord(
        alert_id=alert_id(alert),
        event=str(alert.get("Event", "") or "").strip(),
        code=(str(alert.get("NWSCode")).strip().upper()
              if alert.get("NWSCode") else None),
        cls=row[2],
        tier=_effective_tier(row),
        polygon_local=bool(row[3]),
        precharge_eligible=bool(row[4]),
        start=start,
        end=end,
        corroborable=bool(corroborable),
    )


def update_alert_memory(
    memory: dict[str, dict[str, Any]],
    feed: Any,
    healthy: bool,
    now: datetime,
    selection: InclementSelection | None = None,
) -> list[tuple[str, str, str]]:
    """D-B3 hold memory, mutated in place. Returns rows to log for clears
    under rules (2)/(3): [(alert_id, event, reason)].

    Admission: healthy feed only; Actual, not Cancel, product class HOLD
    (warn/watch, table class), any window (an alert whose Onset is still
    ahead is admitted, Rev 3.1 H3). Clearing: (1) ``now > end`` (silent);
    (2) a Cancel in a healthy feed with the same event name and an
    overlapping window (code compared when both carry one); (3) the entry's
    ID is absent from a healthy NON-EMPTY feed. A stale / unavailable /
    empty feed clears nothing and admits nothing.
    """
    cleared: list[tuple[str, str, str]] = []
    feed_list = feed if isinstance(feed, list) else []
    feed_dicts = [a for a in feed_list if isinstance(a, dict)]
    # (1) expiry.
    for key in list(memory):
        if _dt_lt(memory[key]["end"], now):
            del memory[key]
    if not healthy:
        return cleared
    # (2) Cancel clears by event name + overlapping window.
    for a in feed_dicts:
        if not (_is_actual(a) and _is_cancel(a)):
            continue
        c_ev = str(a.get("Event", "") or "").strip().casefold()
        c_code = str(a.get("NWSCode")).strip().upper() if a.get("NWSCode") else None
        c_start, c_end = _hazard_window(a)
        for key in list(memory):
            m = memory[key]
            if m["event"].casefold() != c_ev:
                continue
            if c_code and m.get("code") and c_code != m["code"]:
                continue
            m_start = m.get("start")
            overlap = True
            if c_end is not None and m_start is not None and _dt_lt(c_end, m_start):
                overlap = False
            if c_start is not None and _dt_lt(m["end"], c_start):
                overlap = False
            if overlap:
                cleared.append((key, m["event"], "cancel"))
                del memory[key]
    # (3) absent from a healthy non-empty feed.
    present = {alert_id(a) for a in feed_dicts}
    if feed_dicts:
        for key in list(memory):
            if key not in present:
                cleared.append((key, memory[key]["event"], "left_feed"))
                del memory[key]
    # Admission.
    for a in feed_dicts:
        rec = build_record(a, selection)
        if rec is None or rec.cls not in ("warn", "watch") or rec.alert_id is None:
            continue
        if _dt_lt(rec.end, now):
            continue
        memory[rec.alert_id] = {
            "alert": dict(a),
            "event": rec.event,
            "code": rec.code,
            "start": rec.start,
            "end": rec.end,
        }
    return cleared


def classifier_input(
    feed: Any, memory: dict[str, dict[str, Any]], now: datetime,
) -> list[dict[str, Any]]:
    """D-B3: feed alerts ∪ memory entries with ``now <= end`` (feed wins on
    a shared ID). The D-B1 window split is applied after this union."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(feed, list):
        for a in feed:
            if isinstance(a, dict):
                out.append(a)
                k = alert_id(a)
                if k:
                    seen.add(k)
    for key, m in memory.items():
        if key in seen or _dt_lt(m["end"], now):
            continue
        out.append(m["alert"])
    return out


class AlertClassifier:
    """Pure classifier (EC storm Stage B): Status/Type filter → product
    table (code or exact name) → hazard window (Onset→Ends) → tier.

    Severity / Certainty are attrs only (no demotion on this path).
    Stage E E1.3: ``selection`` (the operator overlay) is taken per
    construction; the battery builds the classifier per tick. None = zero
    overrides (byte-identical to the table).
    """

    def __init__(self, selection: InclementSelection | None = None) -> None:
        self._selection = selection

    def classify(
        self,
        alerts: Any,
        now: datetime | None = None,
        preonset_lead_h: float | None = None,
    ) -> AlertClassification:
        """Classify the alert list into a single tier.

        ``alerts`` may be None / [] / [{}] / a non-list — all yield tier=none
        with no exception (Bug Class — malformed sensor robustness).
        """
        if now is None:
            now = dt_util.now()

        if not isinstance(alerts, list) or not alerts:
            return AlertClassification(
                tier="none", contributing_events=(), max_severity="Unknown",
                max_certainty="Unknown", expires_at=None, raw_alert_count=0,
            )

        active: list[tuple[AlertRecord, dict[str, Any]]] = []
        prepare: list[AlertRecord] = []
        if preonset_lead_h is None:
            preonset_lead_h = INCLEMENT_PREONSET_LEAD_H  # read at call time
        lead_end = now + timedelta(hours=max(0.0, float(preonset_lead_h or 0)))
        gated_out: list[str] = []
        drift: list[tuple[str, str | None, str]] = []
        seen_ids: set[str] = set()

        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            if not _is_actual(alert) or _is_cancel(alert):
                continue
            key = alert_id(alert)
            if key is not None:
                if key in seen_ids:
                    continue
                seen_ids.add(key)
            event = str(alert.get("Event", "") or "").strip()
            row, d, _corr = match_product(alert, self._selection)
            if d is not None:
                drift.append(d)
            if row is None:
                if event:
                    gated_out.append(event)
                continue
            rec = build_record(alert, self._selection)
            if rec is None:
                continue
            # D-B1 window split: start <= now <= end is active. Pre-onset
            # contributes nothing to tier / expires_at (Q5 doctrine).
            if rec.start is not None and _dt_lt(now, rec.start):
                # D-B6 prepare split: non-polygon HOLD, start <= now + lead.
                if (
                    rec.cls in ("warn", "watch")
                    and not rec.polygon_local
                    and _dt_le(rec.start, lead_end)
                    and _dt_lt(now, lead_end)
                ):
                    prepare.append(rec)
                continue
            if _dt_lt(rec.end, now):
                continue
            active.append((rec, alert))

        active.sort(key=lambda ra: -_TIER_ORDER.get(ra[0].tier, 0))
        hold = [r for r, _ in active if r.tier in ("warn", "watch")]
        max_sev_rank = 0
        max_sev = "Unknown"
        max_cert = "Unknown"
        for _rec, alert in active:
            severity = str(alert.get("Severity", "Unknown") or "Unknown").strip()
            certainty = str(alert.get("Certainty", "Unknown") or "Unknown").strip()
            srank = _severity_rank(severity)
            if srank >= max_sev_rank:
                max_sev_rank = srank
                max_sev = severity.title() if severity else "Unknown"
                max_cert = certainty.title() if certainty else "Unknown"

        eligible, topup, prep_eligible = _precharge_flags(hold, prepare, now)
        return AlertClassification(
            tier=_max_tier([r.tier for r, _ in active]),  # type: ignore[arg-type]
            contributing_events=tuple(r.event for r, _ in active),
            max_severity=max_sev,
            max_certainty=max_cert,
            expires_at=_dt_max([r.end for r in hold]),
            raw_alert_count=len(alerts),
            gated_out_events=tuple(gated_out),
            hold_alerts=tuple(hold),
            drift=tuple(drift),
            prepare_alerts=tuple(prepare),
            precharge_eligible=eligible,
            polygon_topup_active=topup,
            prepare_precharge_eligible=prep_eligible,
            active_alerts=tuple(r for r, _ in active),
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
    bottom_rate: bool | None = None,
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

    # FIN-3 — bottom-rate short-circuit. MUST NOT call the surplus helper.
    # EC storm Stage B D-B4: keyed on the TOU engine's bottom rate when the
    # caller passes it; legacy period-name literal otherwise (byte-safe).
    if (bottom_rate if bottom_rate is not None else tou_period == "off_peak"):
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
    # EC storm Stage B D-B6 (defaults keep every construction site valid).
    # The prepare floor raises `_tick_reserve_floor`; it never changes
    # hold_depth (no pre-onset hold).
    # Stage E E2.4 field split: `preonset_target` is the floor / buy VALUE,
    # populated across the whole buy horizon (what v5.103.69 carried in
    # `preonset_floor`); `preonset_floor` is now the REGISTERED floor, set
    # only when INV-8 (i) or (ii) holds (None = no floor this tick).
    preonset_target: int | None = None
    preonset_floor: int | None = None
    # Stage E E2.2: the frozen buy schedule (UTC hour-slot starts, sorted;
    # () = no buy scheduled) and when the registered floor starts.
    preonset_buy_hours: tuple[datetime, ...] = ()
    preonset_floor_from: datetime | None = None
    preonset_precharge: bool = False
    preonset_start: datetime | None = None  # aware
    preonset_event: str | None = None
    # Latch key (prepare alert ID) + prepare class, for the emission site
    # and the `inclement_preonset` attr shape.
    preonset_alert_id: str | None = None
    preonset_class: str | None = None
    # D-B2a / INV-6(vii): which full-hold leg set grid_precharge ("zone" /
    # "polygon"; None when grid_precharge is False) and whether a zone
    # buy was forecast-confirmed this tick (attr `inclement_buy_forecast`).
    precharge_leg: str | None = None
    buy_forecast_confirmed: bool = False

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


# ---------------------------------------------------------------------------
# Stage E E2 — buy in the cheapest hours closest to the event (INV-9)
# ---------------------------------------------------------------------------


def preonset_slot(now: datetime) -> datetime:
    """The UTC hour slot ``[H, H+1h)`` containing ``now`` (its start H)."""
    return dt_util.as_utc(now).replace(minute=0, second=0, microsecond=0)


def preonset_h_req(current_soc: float | None, target: int) -> int:
    """Hours to book: 0 when SOC is unknown or already >= target (no buy);
    else ceil((target - SOC) / INCLEMENT_GRID_CHARGE_PP_PER_H) + margin."""
    if current_soc is None or float(current_soc) >= float(target):
        return 0
    rate = float(INCLEMENT_GRID_CHARGE_PP_PER_H)
    if rate <= 0:
        return 0
    return int(math.ceil((float(target) - float(current_soc)) / rate)) + max(
        0, int(INCLEMENT_PREONSET_BUY_MARGIN_H),
    )


def schedule_buy_hours(
    tou: Any, now: datetime, event_time: datetime | None, h_req: int,
    horizon_h: float,
) -> tuple[datetime, ...]:
    """Stage E E2.2 (pure): ONE CONTIGUOUS run of ``h_req`` UTC hour slots to
    buy in (operator ruling 2026-10-17: "starting earlier is probably less
    error prone than start stop" -- never on/off/on).

    Candidates: slots ``[H, H+1h)`` with ``H+1h > now``, ``H < T`` and
    ``T - H <= horizon_h`` (the slot containing ``now`` included; stepping is
    on UTC hours, so a DST night neither skips nor repeats a slot). Each slot
    is ranked / priced by the TOU engine at its LOCAL start (``period_rank``
    and ``get_current_rate``; no tariff parsing). An unranked slot breaks a
    run. Among contiguous runs of length ``h_req`` (or the longest that fits
    when fewer slots remain before T), the run with the lowest total import
    rate wins; ties go to the run ending closest to T. So a higher-rate slot
    is used only when no all-cheapest run fits. Engine missing / raising,
    ``h_req <= 0`` or no ``T`` -> (). Returned sorted ascending."""
    if tou is None or event_time is None or h_req <= 0:
        return ()
    try:
        now_u = dt_util.as_utc(now)
        t_u = dt_util.as_utc(event_time)
        horizon = timedelta(hours=max(0.0, float(horizon_h)))
        slot = now_u.replace(minute=0, second=0, microsecond=0)
        seq: list[tuple[datetime, float | None]] = []
        while slot < t_u:
            if t_u - slot <= horizon:
                loc = dt_util.as_local(slot)
                period = tou.get_current_period(loc)
                rank = tou.period_rank(tou.get_season(loc), period)
                cost: float | None = None
                if rank is not None:
                    try:
                        cost = float(tou.get_current_rate(loc))
                    except Exception:  # noqa: BLE001 — rank as the price
                        cost = float(rank)
                seq.append((slot, cost))
            slot = slot + timedelta(hours=1)
        length = min(int(h_req), len(seq))
        while length > 0:
            best: tuple[float, int] | None = None
            for start in range(0, len(seq) - length + 1):
                win = seq[start:start + length]
                if any(c is None for _, c in win):
                    continue
                total = sum(c for _, c in win)  # type: ignore[misc]
                # Lowest total; ties -> the later run (closest to T).
                if best is None or total <= best[0] + 1e-12:
                    best = (total, start)
            if best is not None:
                return tuple(s for s, _ in seq[best[1]:best[1] + length])
            length -= 1
        return ()
    except Exception:  # noqa: BLE001 — engine raising -> no buy
        _LOGGER.debug("inclement: schedule_buy_hours failed", exc_info=True)
        return ()


def _carry_over_updates(
    sched: dict[str, tuple], latch: dict[str, str] | None,
    prep: tuple[AlertRecord, ...],
) -> None:
    """Stage E fix-up (AUDIT_nws_alert_fields_and_updates): an NWS Update
    arrives as a NEW message ID. When a scheduled key's ID has left the
    prepare set and a new prepare record with the same Event + NWSCode and
    an overlapping hazard window appears, move the frozen schedule AND the
    latch state to the new ID (no fresh start, no re-buy after "reached").
    A changed T is then re-planned by the stale-T rule."""
    live = {r.alert_id: r for r in prep if r.alert_id}
    for old in [k for k in sched if k not in live]:
        entry = sched[old]
        meta = entry[3] if len(entry) > 3 else None
        if not meta:
            continue
        ev, code, o_start, o_end = meta
        for nid, r in live.items():
            if nid in sched or (latch is not None and nid in latch):
                continue
            if r.event.casefold() != ev or r.code != code:
                continue
            if r.start is not None and o_end is not None and _dt_lt(o_end, r.start):
                continue
            if o_start is not None and _dt_lt(r.end, o_start):
                continue
            sched[nid] = sched.pop(old)
            if latch is not None and old in latch:
                latch[nid] = latch.pop(old)
            break


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
        blind_full_hold_floor: int = INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT,
        preonset_floor: int = INCLEMENT_PREONSET_FLOOR_PCT,
        polygon_import_guard_tripped: bool = False,
    ) -> None:
        self._reserve_soc = int(reserve_soc)
        # EC storm Stage B D-B6: live pre-onset slider (re-read per tick).
        self._preonset_knob = max(0, min(100, int(preonset_floor)))
        # D-B2a / Rev 3.3 M4: the arbitrage grid-import guard (only when its
        # toggle is on) refuses the polygon immediate leg this tick.
        self._polygon_import_guard_tripped = bool(polygon_import_guard_tripped)
        # EC storm/blind Stage A D-A5: live slider value (re-read per tick by
        # `_inclement_config`); used only when SOC is unknown.
        self._blind_full_hold_floor = max(0, min(100, int(blind_full_hold_floor)))
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
        bottom_rate: bool | None = None,
        forecast_confirmed_ids: frozenset[str] | set[str] = frozenset(),
        preonset_latch: dict[str, str] | None = None,
        preonset_buy_schedule: dict[str, tuple] | None = None,
    ) -> InclementDecision:
        """Produce the InclementDecision (matrix in PLANNING §Design).

        EC storm Stage B D-B4: ``bottom_rate`` (TOU engine ``is_bottom_rate``)
        replaces the literal ``tou_period == "off_peak"`` checks; None =
        legacy literal (no engine).

        Stage C D-C2: ``forecast_confirmed_ids`` = alert IDs whose local
        forecast confirms the product's hazard over its window (latched per
        ID by the caller). Raise-only: corroborates a watch and is REQUIRED
        for every zone-product grid buy (INV-6(vii)). Empty = no forecast.

        D-B6: ``preonset_latch`` (RAM, owned by the battery) is advanced here
        every tick, leg-independently (INV-6(viii)).

        Stage E E2: ``preonset_buy_schedule`` (RAM, owned by the battery)
        holds the frozen buy schedule per prepare key ``(S, T, target)``;
        None = no schedule store (no D-B6 buy, floor by rule (i) only).
        """
        is_bottom = (
            bottom_rate if bottom_rate is not None else tou_period == "off_peak"
        )
        confirmed = frozenset(forecast_confirmed_ids or ())
        base = self._decide_hold(
            battery, classification, condition_stormy,
            condition_provider_count, tou_period, now, current_soc,
            is_bottom, confirmed,
        )
        return self._apply_prepare(
            base, battery, classification, now, current_soc, is_bottom,
            confirmed, preonset_latch, preonset_buy_schedule,
        )

    def _zone_buy_confirmed(
        self, records: tuple[AlertRecord, ...] | list[AlertRecord],
        confirmed: frozenset[str],
    ) -> bool:
        """D-B2a + INV-6(vii) on the SAME record: some active/prepare record
        that is precharge-eligible AND forecast-confirmed. This is the
        eligibility gate of every zone buy (the classification-level
        `precharge_eligible` flag is display-only: an "any eligible" AND
        "any confirmed" pair would let a confirmed INELIGIBLE watch buy on
        behalf of an unconfirmed eligible warning). Polygon records never
        enter `confirmed` (`_forecast_confirmed_ids` skips them)."""
        return any(
            r.precharge_eligible
            and r.alert_id is not None and r.alert_id in confirmed
            for r in records
        )

    def _apply_prepare(
        self,
        base: InclementDecision,
        battery: Any,
        classification: AlertClassification,
        now: datetime,
        current_soc: float | None,
        is_bottom: bool,
        confirmed: frozenset[str],
        latch: dict[str, str] | None,
        sched: dict[str, tuple] | None = None,
    ) -> InclementDecision:
        """D-B6 pre-onset prepare floor / pre-charge eligibility.

        Stage E E2 (INV-8 / INV-9): the value (``preonset_target``) is set
        across the buy horizon; the floor is REGISTERED only when (ii) a
        frozen buy schedule exists and ``now >= min(S)``, or (i) ``now >= T -
        min(FLOOR_LEAD_H, LEAD_H)``. The buy fires only in a scheduled slot.
        ``is_bottom`` no longer gates the D-B6 buy (INV-9 amends INV-6(iii)).
        """
        del is_bottom  # INV-9: the schedule replaces the bottom-rate gate
        prep = tuple(getattr(classification, "prepare_alerts", ()) or ())
        live = {r.alert_id for r in prep}
        if sched is not None:
            _carry_over_updates(sched, latch, prep)
        if latch is not None:
            for k in list(latch):
                if k not in live:  # Onset reached or left the prepare set
                    del latch[k]
        if sched is not None:
            for k in list(sched):
                if k not in live:  # same discharge as the latch
                    del sched[k]
        if not prep:
            return base
        # Stage E fix-up (Review D D-HIGH-1, INV-7(f)): the class, key row
        # and event time T come from CORROBORABLE (table) records only, so an
        # unlisted / widened product can never set a table product's T, key,
        # reason, latch or schedule. With no corroborable record the
        # non-corroborable set is used (it gets only the lower floor).
        basis = [r for r in prep if r.corroborable] or list(prep)
        pclass = prepare_class_of(basis)
        prows = [r for r in basis if r.cls == pclass]
        key_row = min(
            prows, key=lambda r: (r.start.timestamp() if r.start else 0.0),
        )
        pstart = key_row.start
        for r in basis:
            if r.start is not None and pstart is not None and _dt_lt(r.start, pstart):
                pstart = r.start
        key_id = key_row.alert_id
        # Stage E E1.4 / INV-7(c): the higher floor needs a CORROBORABLE
        # record: a warn (every warn record is a table HOLD row, so always
        # corroborable -- the selection only ever adds WATCH-class rows), or
        # a table watch that is itself confirmed. An unlisted / widened
        # prepare record gets only `lower`.
        watch_confirmed = pclass == "watch" and any(
            r.alert_id in confirmed and r.corroborable
            for r in prows if r.alert_id
        )
        high = pclass == "warn" or watch_confirmed
        lower = max(self._reserve_soc, self._partial_floor)
        target = max(lower, self._preonset_knob) if high else lower
        target = max(0, min(100, int(target)))
        # INV-6(viii): leg-independent latch advance (full_hold shadowing
        # included). A full_hold tick never sets "engaged".
        if (
            latch is not None and key_id is not None
            and latch.get(key_id) == "engaged"
            and current_soc is not None and current_soc >= target
        ):
            latch[key_id] = "reached"
        # Stage E §E2.4 eligibility-loss discharge (INV-8(ii)): option off
        # or the same-record forecast confirm lost -> an "engaged" latch
        # entry and the schedule are deleted ("reached" stays: no re-buy).
        eligible = self._grid_precharge_on_hold and self._zone_buy_confirmed(
            prows, confirmed,
        )
        if not eligible and key_id is not None:
            if latch is not None and latch.get(key_id) == "engaged":
                del latch[key_id]
            if sched is not None:
                sched.pop(key_id, None)
        if sched is not None:
            # Review B B2: only the current key alert may own a schedule.
            for k in list(sched):
                if k != key_id:
                    del sched[k]
            # Review D D-MED-1: a frozen S whose T is no longer the current T
            # (the earlier alert onset, or an Update) is re-planned.
            if key_id in sched and sched[key_id][1] != pstart:
                del sched[key_id]
        if base.hold_depth == "full_hold":
            return base  # the active hold governs; prepare fields stay default
        state = latch.get(key_id) if (latch is not None and key_id) else None
        stored = sched.get(key_id) if (sched is not None and key_id) else None
        pre = False
        # Evaluation order (§E2.2 rule 5): (1) every other D-B6 buy gate,
        # then the solar test (skipped while engaged); (2) freeze S if none
        # is stored; (3) buy only in a scheduled slot.
        if (
            eligible
            and current_soc is not None
            and current_soc < target
            and state != "reached"
        ):
            if state == "engaged":
                solar_ok = True
            else:
                mins = 0
                if pstart is not None:
                    _n, _s = _coerce_compatible(now, pstart)
                    mins = max(0, int((_s - _n).total_seconds() // 60))
                try:
                    surplus = float(battery._expected_solar_surplus_pct(now, mins))
                except Exception:  # noqa: BLE001 — Solcast missing → 0
                    surplus = 0.0
                solar_ok = float(current_soc) + surplus < target
            if solar_ok:
                if stored is None and sched is not None and key_id is not None:
                    hours = schedule_buy_hours(
                        getattr(battery, "_tou", None), now, pstart,
                        preonset_h_req(current_soc, target),
                        INCLEMENT_PREONSET_LEAD_H,
                    )
                    if hours:  # Review A A-LOW-1 / B B3: never freeze ()
                        stored = (hours, pstart, target, (
                            key_row.event.casefold(), key_row.code,
                            key_row.start, key_row.end,
                        ))
                        sched[key_id] = stored
                pre = stored is not None and preonset_slot(now) in stored[0]
        # Registered floor -- the ONE rule (§E2.4).
        hours = tuple(stored[0]) if stored else ()
        eff_lead = max(0.0, min(float(INCLEMENT_PREONSET_FLOOR_LEAD_H),
                                float(INCLEMENT_PREONSET_LEAD_H)))
        starts: list[datetime] = []
        registered: int | None = None
        if hours:
            starts.append(hours[0])
            if _dt_le(hours[0], now):  # INV-8(ii)
                registered = target
        if eff_lead > 0 and pstart is not None:
            fstart = pstart - timedelta(hours=eff_lead)
            starts.append(fstart)
            if registered is None and _dt_le(fstart, now):  # INV-8(i)
                horizon_end = now + timedelta(hours=eff_lead)
                in_window = [
                    r for r in prep
                    if r.start is not None and _dt_le(r.start, horizon_end)
                ]
                hi = any(
                    r.corroborable and (
                        r.cls == "warn"
                        or (r.cls == "watch" and r.alert_id in confirmed)
                    )
                    for r in in_window
                )
                registered = max(
                    0, min(100, int(max(lower, self._preonset_knob) if hi else lower)),
                )
        floor_from = None
        for st in starts:
            if floor_from is None or _dt_lt(st, floor_from):
                floor_from = st
        return replace(
            base,
            preonset_target=target,
            preonset_floor=registered,
            preonset_buy_hours=hours,
            preonset_floor_from=floor_from,
            preonset_precharge=pre,
            preonset_start=pstart,
            preonset_event=key_row.event,
            preonset_alert_id=key_id,
            preonset_class=pclass,
            # D-MED-1: the buy attr reports the SAME per-record conjunct the
            # pre-onset gate used (else a legal pre-onset buy reads "not
            # confirmed" and fires the §3 INV-6(vii) falsifier).
            buy_forecast_confirmed=(
                base.buy_forecast_confirmed
                or self._zone_buy_confirmed(prows, confirmed)
            ),
        )

    def _decide_hold(
        self,
        battery: Any,
        classification: AlertClassification,
        condition_stormy: bool,
        condition_provider_count: int,
        tou_period: str,
        now: datetime,
        current_soc: float | None,
        is_bottom: bool,
        confirmed: frozenset[str],
    ) -> InclementDecision:
        """The v5.5.0 hold ladder (unchanged except the D-B2a buy gates and
        the D-C2 forecast corroboration)."""
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
            # D-B2a narrowed (Rev 3.2/3.3): zone leg = bottom rate + an
            # eligible active zone product + forecast-confirmed buy; polygon
            # leg = a verified-local polygon inside its cap window, any TOU,
            # unless the (toggle-on) arbitrage import guard tripped. Option
            # False short-circuits first (byte-identical).
            zone_ok = poly_ok = buy_ok = False
            grid_precharge = (
                self._grid_precharge_on_hold
                and current_soc is not None
                and current_soc < self._storm_charge_threshold
            )
            if grid_precharge:
                buy_ok = self._zone_buy_confirmed(
                    classification.hold_alerts, confirmed,
                )
                zone_ok = is_bottom and buy_ok
                poly_ok = (
                    classification.polygon_topup_active
                    and not self._polygon_import_guard_tripped
                )
                grid_precharge = zone_ok or poly_ok
            return InclementDecision(
                hold_depth="full_hold",
                grid_precharge=grid_precharge,
                precharge_leg=(
                    "zone" if zone_ok else ("polygon" if poly_ok else None)
                ),
                buy_forecast_confirmed=buy_ok,
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
            # Stage C D-C2: forecast confirmation of an active watch counts
            # as corroboration (corroborated = condition OR forecast).
            # Stage E §4.2 / INV-7(c)/(f): every corroboration leg requires a
            # corroborable watch record (a table watch); an unlisted or
            # widened watch never corroborates, and a co-active table watch
            # keeps its own corroboration (no demotion).
            watch_records = [
                r for r in classification.hold_alerts if r.tier == "watch"
            ]
            corr_ok = any(r.corroborable for r in watch_records)
            forecast_corroborates = any(
                r.alert_id in confirmed and r.corroborable
                for r in watch_records
                if r.alert_id
            )
            corroborated = (
                (not self._watch_requires_corroboration) and corr_ok
            ) or (
                condition_stormy and condition_provider_count >= 1 and corr_ok
            ) or forecast_corroborates
            if not corroborated:
                # Uncorroborated watch: off_peak partial_hold; mid/peak discharge.
                if is_bottom:
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
            if is_bottom:
                # Off_peak holds readily (FIN-3 — recoverability not consulted).
                # D-B2a + INV-6(vii): eligible product AND forecast-confirmed
                # buy (no polygon watches exist → no immediate leg here).
                grid_precharge = (
                    self._grid_precharge_on_hold
                    and current_soc is not None
                    and current_soc < self._storm_charge_threshold
                )
                buy_ok = False
                if grid_precharge:
                    buy_ok = self._zone_buy_confirmed(
                        classification.hold_alerts, confirmed,
                    )
                    grid_precharge = buy_ok
                return InclementDecision(
                    hold_depth="full_hold",
                    grid_precharge=grid_precharge,
                    precharge_leg="zone" if grid_precharge else None,
                    buy_forecast_confirmed=buy_ok,
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
                # EC-SOC-LADDER #6: recoverability uses the SAME clamped
                # floor the emission uses (max(reserve, floor)) so an
                # inverted floor < reserve cannot overstate permitted
                # discharge. Validator/anomaly still read the RAW option.
                partial_hold_reserve_floor=self._partial_floor_value(current_soc),
                surplus_margin_pct=self._surplus_margin_pct,
                bottom_rate=is_bottom,
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
            if is_bottom:
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

        Mirrors today's BACKUP behavior (no discharge). Sighted (SOC known):
        ``int(soc)`` — may be below reserve_soc, by design (P3-08).

        EC storm/blind Stage A D-A3/D-A5: SOC unknown → ``max(reserve_soc,
        partial_floor, blind_full_hold_floor)`` (the D-A5 slider, default 60;
        100 = the legacy pin, 0 = no extra blind floor). Was a hard 100.
        """
        if current_soc is None:
            return max(
                0,
                min(
                    100,
                    max(
                        self._reserve_soc,
                        self._partial_floor,
                        self._blind_full_hold_floor,
                    ),
                ),
            )
        return max(0, min(100, int(current_soc)))

    def _partial_floor_value(self, current_soc: float | None) -> int:
        """partial_hold floor = max(reserve_soc, configured partial floor)."""
        return max(self._reserve_soc, self._partial_floor)


def _first(events: tuple[str, ...]) -> str | None:
    return events[0] if events else None


# ---------------------------------------------------------------------------
# EC storm Stage C D-C2 — forecast confirmation (provider-agnostic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Outlook:
    """Aggregated hourly forecast over one hazard window (D-C1 producer:
    ``WeatherProviderManager.hourly_outlook``).

    Precipitation is split by what each hour's provider actually carries:
    ``max_pop`` over hours whose provider has ``precipitation_probability``;
    ``max_precip_mm_no_pop`` over hours whose provider has only an amount.
    ``sources`` = ((provider, first_hour_iso, last_hour_iso), ...).
    """

    window_start: datetime
    window_end: datetime
    hours: int
    min_temp_f: float | None
    max_pop: float | None
    max_precip_mm_no_pop: float | None
    max_gust: float | None
    conditions: frozenset[str]
    sources: tuple[tuple[str, str, str], ...] = ()
    # Min apparent ("feels like") temperature over hours whose provider
    # carries it; None when no covered hour does (operator 2026-10-17).
    min_apparent_f: float | None = None


def forecast_family(event: str | None) -> str | None:
    """D-C2 family of a product (exact name, case-folded)."""
    if not event:
        return None
    ev = str(event).strip().casefold()
    for name, fam in INCLEMENT_FORECAST_FAMILY.items():
        if name.casefold() == ev:
            return fam
    return None


def forecast_confirms(event: str | None, outlook: Outlook | None) -> bool:
    """D-C2: does the local forecast confirm this product's hazard over the
    window the outlook covers? Outlook None (never fetched, stale, provider
    down, no hourly support) → False: no corroboration, no buy.

    freeze/cold: min temp <= FORECAST_FREEZE_CONFIRM_F (any provider). For
      FORECAST_APPARENT_TEMP_PRODUCTS (wind chill / extreme cold) the min
      APPARENT temp is used when the outlook carries one, else air temp.
    winter storm: min temp <= FORECAST_WINTER_STORM_CONFIRM_F AND precip
      (probability >= FORECAST_PRECIP_CONFIRM_PCT where the hour's provider
      has it, else amount >= FORECAST_PRECIP_CONFIRM_MM).
    convective (operator 2026-10-17: no grid buys on mere rain): a storm
      condition (FORECAST_CONVECTIVE_STORM_CONDITIONS; excludes "pouring" /
      "snowy-rainy") in the window AND strong precip (probability >=
      FORECAST_CONVECTIVE_PRECIP_CONFIRM_PCT where the hour's provider has it,
      else amount >= FORECAST_PRECIP_CONFIRM_MM). Rain alone never confirms.
    """
    if outlook is None or outlook.hours <= 0:
        return False
    fam = forecast_family(event)
    if fam is None:
        return False
    from .energy_const import (
        FORECAST_APPARENT_TEMP_PRODUCTS,
        FORECAST_CONVECTIVE_PRECIP_CONFIRM_PCT,
        FORECAST_CONVECTIVE_STORM_CONDITIONS,
        FORECAST_FREEZE_CONFIRM_F,
        FORECAST_PRECIP_CONFIRM_MM,
        FORECAST_PRECIP_CONFIRM_PCT,
        FORECAST_WINTER_STORM_CONFIRM_F,
    )
    precip_ok = (
        (outlook.max_pop is not None
         and outlook.max_pop >= FORECAST_PRECIP_CONFIRM_PCT)
        or (outlook.max_precip_mm_no_pop is not None
            and outlook.max_precip_mm_no_pop >= FORECAST_PRECIP_CONFIRM_MM)
    )
    tmin = outlook.min_temp_f
    if fam == "freeze":
        ev = str(event).strip().casefold()
        if (
            outlook.min_apparent_f is not None
            and any(p.casefold() == ev for p in FORECAST_APPARENT_TEMP_PRODUCTS)
        ):
            tmin = outlook.min_apparent_f
        return tmin is not None and tmin <= FORECAST_FREEZE_CONFIRM_F
    if fam == "winter_storm":
        return (
            tmin is not None and tmin <= FORECAST_WINTER_STORM_CONFIRM_F
            and precip_ok
        )
    if fam == "convective":
        convective_precip_ok = (
            (outlook.max_pop is not None
             and outlook.max_pop >= FORECAST_CONVECTIVE_PRECIP_CONFIRM_PCT)
            or (outlook.max_precip_mm_no_pop is not None
                and outlook.max_precip_mm_no_pop >= FORECAST_PRECIP_CONFIRM_MM)
        )
        return (
            bool(outlook.conditions & FORECAST_CONVECTIVE_STORM_CONDITIONS)
            and convective_precip_ok
        )
    return False
