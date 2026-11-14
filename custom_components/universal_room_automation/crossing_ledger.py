"""Crossing ledger: pure core (crossing vision P2-D2).

Plan: docs/planning/PLANNING_crossing_vision.md P2-D2 (census side:
PLANNING_census_deconfliction.md §3.3). No Home Assistant import and no clock
read: every time is passed in (epoch seconds). The wiring lives in
``crossing_vision.CrossingVisionShadow``.

One house ledger in RAM. ``L`` (>= 0) is the ledger's people-in-house
estimate; ``L_raw`` is the same arithmetic without the zero clamp
(diagnostic only). State ``known`` / ``unknown``; boot is ``unknown`` (no
replay; a restart never restores ``known``).

Fact model: F3 crossings in (terms), F2 out only through ``census_tick``
(``guest_vis = max(0, L - R)``); the census owns F2. The module stores what
it is given and never reads the census, presence, house state or the
resident set.

Falsifiable invariants (tests in quality/tests/test_crossing_ledger.py):

* INV-P2-DISCHARGE. For any sequence of terms, missed exits, vision errors,
  cap skips, restarts or resident tracker state (a phone left at home
  included): once the camera body total is 0, the fleet is not dark, no
  room rising edge has occurred and no entry term was applied, continuously
  for ``empty_reset_s``, the anchor sets ``L = R`` and ``guest_vis`` is 0 at
  the next ``census_tick``. The predicate reads no house state, census
  output, resident set or ledger value. Late terms (crossing E before the
  last anchor) are recorded, not applied.
* INV-P2-IDENTITY. Nothing here names a person or changes any identity
  value; ``person`` on a reconcile is the residency record's id, read only.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

STATE_UNKNOWN = "unknown"
STATE_KNOWN = "known"

DIRECTION_ENTRY = "entry"
DIRECTION_EXIT = "exit"

SOURCE_VISION = "vision"
SOURCE_CAMERA = "camera"

FALLBACK_CAMERA = "camera"
FALLBACK_SKIP = "skip"

KIND_TERM = "term"
KIND_ANCHOR = "anchor"
KIND_RECONCILE = "reconcile"

# Vision outcome that carries a usable count (crossing_vision.OUTCOME_OK).
_OUTCOME_OK = "ok"


@dataclass(frozen=True)
class LedgerEvent:
    """One ledger change (or recorded non-change) for the episode log."""

    kind: str
    at: float
    applied: bool
    reason: str | None = None
    direction: str | None = None
    n: int | None = None
    term_source: str | None = None
    crossing_key: str | None = None
    e_ts: float | None = None
    l_before: int | None = None
    l_after: int | None = None
    l_raw_after: int | None = None
    residue: int | None = None
    person: str | None = None
    # Anchors only: True when a term or reconcile was applied since the
    # previous anchor (or this is the first anchor), so the scorer's drift
    # bar counts independent anchors only (back-to-back anchors of an empty
    # house carry no new evidence).
    independent: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def term_count(
    outcome: str | None,
    people_count: Any,
    camera_peak_count: Any,
    fallback: str,
) -> tuple[int | None, str | None]:
    """``n`` and ``term_source`` for one crossing outcome (plan P2-D2 3).

    Vision ``people_count`` when the outcome is ``ok`` (source ``vision``);
    otherwise, under the ``camera`` policy, the transit validator's
    ``camera_peak_count``, else 1 (source ``camera``; ``blank`` falls back
    too). Under the ``skip`` policy a non-vision outcome yields no term
    (None, None).
    """
    vision = _count(people_count)
    if outcome == _OUTCOME_OK and vision is not None:
        return vision, SOURCE_VISION
    if fallback == FALLBACK_SKIP:
        return None, None
    peak = _count(camera_peak_count)
    return (peak if peak is not None else 1), SOURCE_CAMERA


def cluster_terms(
    members: list[dict[str, Any]],
    outcome: str | None,
    people_count: Any,
    fallback: str,
) -> list[dict[str, Any]]:
    """Terms for a cluster (primary first in ``members``).

    Each member: ``{"crossing_key", "direction", "camera_peak_count",
    "e_ts"}``. All members share a direction -> ONE term with the primary's
    count (vision when ``ok``, else the primary's camera fallback), keyed by
    the primary. Mixed directions -> one camera term per member (vision
    count never used: it cannot be split by direction). Members whose
    direction is not entry / exit are dropped (no term).
    """
    usable = [m for m in members
              if m.get("direction") in (DIRECTION_ENTRY, DIRECTION_EXIT)]
    if not usable:
        return []
    directions = {m["direction"] for m in usable}
    if len(directions) == 1:
        primary = usable[0]
        n, src = term_count(outcome, people_count,
                            primary.get("camera_peak_count"), fallback)
        if n is None:
            return []
        return [{**primary, "n": n, "term_source": src}]
    out = []
    for m in usable:
        n, src = term_count(None, None, m.get("camera_peak_count"), fallback)
        if n is not None:
            out.append({**m, "n": n, "term_source": src})
    return out


class CrossingLedger:
    """The house crossing ledger (RAM; boot = unknown)."""

    def __init__(
        self,
        *,
        empty_reset_s: float,
        eval_s: float,
        reconcile_lead_s: float,
        reconcile_lag_s: float,
        reconcile_delay_s: float,
        stuck_s: float,
        anchor_zero_s: float,
        setup_ts: float,
    ) -> None:
        self.empty_reset_s = max(0.0, float(empty_reset_s))
        self.eval_s = max(0.0, float(eval_s))
        self.reconcile_lead_s = max(0.0, float(reconcile_lead_s))
        self.reconcile_lag_s = max(0.0, float(reconcile_lag_s))
        self.reconcile_delay_s = max(0.0, float(reconcile_delay_s))
        self.stuck_s = max(0.0, float(stuck_s))
        self.anchor_zero_s = max(0.0, float(anchor_zero_s))
        self.setup_ts = float(setup_ts)

        self.state = STATE_UNKNOWN
        self.unknown_reason: str | None = "boot"
        self.L: int | None = None
        self.L_raw: int | None = None
        self.last_anchor_ts: float | None = None
        self.residue_last: int | None = None

        # census_tick inputs (stored, never re-derived).
        self._R: int | None = None
        self._bodies: int | None = None
        self._bodies_ts: float | None = None
        self._dark = False

        # Anchor window.
        self._t_start: float | None = None
        self._edge_since_sample = False
        self._entry_since_sample = False
        self._changed_since_anchor = True

        # Departure reconcile: person -> t_e (superseded per person).
        self._pending: dict[str, float] = {}
        self._exit_es: deque[float] = deque(maxlen=512)

        # Trip-wire state (RAM latches).
        self._stuck_since: float | None = None
        self._stuck_latched = False
        self._anchor_zero_latched = False

        # Display counters (the wiring resets them at local midnight).
        self.terms_today: dict[str, int] = {SOURCE_VISION: 0, SOURCE_CAMERA: 0}
        self.reconciled_today = 0

    # ---------------------------------------------------------------- reads
    def guest_vis(self) -> int | None:
        if self.state != STATE_KNOWN or self.L is None or self._R is None:
            return None
        return max(0, self.L - self._R)

    def healthy(self) -> bool:
        return self._bodies is not None and not self._dark

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "unknown_reason": self.unknown_reason if self.state == STATE_UNKNOWN else None,
            "L": self.L,
            "L_raw": self.L_raw,
            "last_anchor": self.last_anchor_ts,
            "residue_last": self.residue_last,
            "terms_today": dict(self.terms_today),
            "reconciled_today": self.reconciled_today,
            "pending_reconciles": len(self._pending),
        }

    def reset_daily_counters(self) -> None:
        self.terms_today = {SOURCE_VISION: 0, SOURCE_CAMERA: 0}
        self.reconciled_today = 0

    # --------------------------------------------------------------- inputs
    def set_unknown(self, reason: str) -> None:
        """Forget the estimate (switch off / kill / cap 0). The next anchor
        makes it known again."""
        self.state = STATE_UNKNOWN
        self.unknown_reason = reason
        self.L = None
        self.L_raw = None
        self._t_start = None
        self._pending.clear()
        self._stuck_since = None
        self._changed_since_anchor = True

    def rebase(self, now: float) -> None:
        """The producer was (re-)enabled at ``now``: the anchor-zero clock
        restarts there (a long switch-off is not an anchor drought)."""
        self.setup_ts = float(now)
        self._anchor_zero_latched = False

    def census_tick(
        self,
        now: float,
        resident_term: Any,
        camera_bodies: Any,
        camera_input_dark: Any,
    ) -> tuple[int | None, bool]:
        """Store the census inputs; apply the floor; return
        ``(guest_vis | None, healthy)``. ``healthy`` is False while the
        fleet is dark or the body total is None."""
        r = _count(resident_term)
        self._R = r
        self._bodies = _count(camera_bodies)
        self._bodies_ts = float(now)
        self._dark = bool(camera_input_dark)
        # Floor: L never below the resident term while known.
        if self.state == STATE_KNOWN and self.L is not None and r is not None:
            self.L = max(self.L, r)
        return self.guest_vis(), self.healthy()

    def note_rising_edge(self, now: float) -> None:
        """A Tier-1 room sensor rising edge (edges, not levels: a stuck-on
        sensor produces no edge and cannot block the anchor)."""
        del now
        self._edge_since_sample = True

    def apply_term(
        self,
        *,
        direction: str,
        n: int | None,
        term_source: str | None,
        crossing_key: str | None,
        e_ts: float,
        now: float,
    ) -> LedgerEvent | None:
        """One crossing term. Entry ``L += n``; exit ``L = max(0, L - n)``
        (``L_raw`` unclamped). While unknown, or for a late term (E before
        the last anchor), the term is recorded with ``applied`` False."""
        if direction not in (DIRECTION_ENTRY, DIRECTION_EXIT) or n is None:
            return None
        e_ts = float(e_ts)
        if direction == DIRECTION_EXIT:
            self._exit_es.append(e_ts)
        base = dict(kind=KIND_TERM, at=float(now), direction=direction, n=int(n),
                    term_source=term_source, crossing_key=crossing_key, e_ts=e_ts)
        if self.state != STATE_KNOWN or self.L is None or self.L_raw is None:
            return LedgerEvent(applied=False, reason="unknown", **base)
        if self.last_anchor_ts is not None and e_ts < self.last_anchor_ts:
            return LedgerEvent(applied=False, reason="late", l_before=self.L,
                               l_after=self.L, l_raw_after=self.L_raw, **base)
        before = self.L
        if direction == DIRECTION_ENTRY:
            self.L += int(n)
            self.L_raw += int(n)
            # An applied entry term fails the anchor window.
            self._entry_since_sample = True
        else:
            self.L_raw -= int(n)
            self.L = max(0, self.L - int(n))
        if term_source in self.terms_today:
            self.terms_today[term_source] += 1
        self._changed_since_anchor = True
        return LedgerEvent(applied=True, l_before=before, l_after=self.L,
                           l_raw_after=self.L_raw, **base)

    # ----------------------------------------------------------- the anchor
    def _sample_ok(self, now: float, *, entry_blocks: bool) -> bool:
        fresh = (
            self._bodies_ts is not None
            and float(now) - self._bodies_ts <= 2.0 * self.eval_s
        )
        return (
            fresh
            and self._bodies == 0
            and not self._dark
            and not self._edge_since_sample
            and not (entry_blocks and self._entry_since_sample)
        )

    def evaluate(self, now: float) -> list[LedgerEvent]:
        """One anchor-window sample (the wiring calls this every
        ``eval_s``). Returns the anchor event, if one fired."""
        now = float(now)
        events: list[LedgerEvent] = []
        ok = self._sample_ok(now, entry_blocks=True)
        stuck_ok = self._sample_ok(now, entry_blocks=False)
        self._edge_since_sample = False
        self._entry_since_sample = False
        if not ok:
            self._t_start = None
        else:
            if self._t_start is None:
                self._t_start = now
            if now - self._t_start >= self.empty_reset_s and self._R is not None:
                events.append(self._anchor(now))
        gv = self.guest_vis()
        if gv is None or gv == 0:
            self._stuck_latched = False
        if stuck_ok and gv is not None and gv >= 1:
            if self._stuck_since is None:
                self._stuck_since = now
        else:
            self._stuck_since = None
        return events

    def _anchor(self, now: float) -> LedgerEvent:
        before = self.L if self.state == STATE_KNOWN else None
        residue = (before - self._R) if before is not None else None
        self.L = int(self._R)
        self.L_raw = int(self._R)
        self.state = STATE_KNOWN
        self.unknown_reason = None
        self.last_anchor_ts = now
        if residue is not None:
            self.residue_last = residue
        self._t_start = now
        # An anchor at or after a departure voids its pending reconcile.
        self._pending = {p: t for p, t in self._pending.items() if t > now}
        self._anchor_zero_latched = False
        independent = self._changed_since_anchor
        self._changed_since_anchor = False
        return LedgerEvent(kind=KIND_ANCHOR, at=now, applied=True,
                           l_before=before, l_after=self.L,
                           l_raw_after=self.L_raw, residue=residue,
                           independent=independent)

    # ------------------------------------------------- departure reconcile
    def reconcile_enabled(self) -> bool:
        return self.reconcile_lead_s > 0 or self.reconcile_lag_s > 0

    def note_departure(self, person: str, t_e: float) -> float | None:
        """A resident departure edge at ``t_e``. Returns the time to judge
        it (``t_e + lag + delay``), or None when not tracked (ledger
        unknown, reconcile disabled)."""
        if self.state != STATE_KNOWN or not self.reconcile_enabled():
            return None
        self._pending[str(person)] = float(t_e)
        return float(t_e) + self.reconcile_lag_s + self.reconcile_delay_s

    def judge_reconcile(self, person: str, now: float) -> LedgerEvent | None:
        """Judge one pending departure: an exit term with E in
        [t_e - lead, t_e + lag] cancels it; otherwise ``L = max(0, L - 1)``.
        Voided (None) when the ledger is no longer known or an anchor at or
        after t_e already ran."""
        t_e = self._pending.pop(str(person), None)
        if t_e is None or self.state != STATE_KNOWN or self.L is None:
            return None
        if self.last_anchor_ts is not None and self.last_anchor_ts >= t_e:
            return None
        lo, hi = t_e - self.reconcile_lead_s, t_e + self.reconcile_lag_s
        if any(lo <= e <= hi for e in self._exit_es):
            return LedgerEvent(kind=KIND_RECONCILE, at=float(now), applied=False,
                               reason="exit_term", person=str(person), e_ts=t_e,
                               l_before=self.L, l_after=self.L,
                               l_raw_after=self.L_raw)
        before = self.L
        self.L = max(0, self.L - 1)
        if self.L_raw is not None:
            self.L_raw -= 1
        self.reconciled_today += 1
        self._changed_since_anchor = True
        return LedgerEvent(kind=KIND_RECONCILE, at=float(now), applied=True,
                           person=str(person), e_ts=t_e, n=1,
                           l_before=before, l_after=self.L,
                           l_raw_after=self.L_raw)

    def pending_people(self) -> list[str]:
        return list(self._pending)

    # ----------------------------------------------------------- trip-wires
    def stuck_due(self, now: float) -> bool:
        """True ONCE when ``guest_vis >= 1`` has held while every sample for
        ``stuck_s`` had zero bodies, a lit fleet and no rising edge (entry
        terms do not count, so a term stream that blocks the anchor IS
        paged). Re-armed when ``guest_vis`` reads 0. ``stuck_s`` 0 = off."""
        if self.stuck_s <= 0 or self._stuck_latched or self._stuck_since is None:
            return False
        if float(now) - self._stuck_since < self.stuck_s:
            return False
        self._stuck_latched = True
        return True

    def anchor_zero_due(self, now: float) -> bool:
        """True ONCE when no anchor ran for ``anchor_zero_s`` (from setup or
        the last anchor). Re-armed by an anchor. 0 = off."""
        if self.anchor_zero_s <= 0 or self._anchor_zero_latched:
            return False
        since = max(self.setup_ts, self.last_anchor_ts or self.setup_ts)
        if float(now) - since < self.anchor_zero_s:
            return False
        self._anchor_zero_latched = True
        return True
