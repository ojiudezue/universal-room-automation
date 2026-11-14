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
  Tier-1 input is held (reads ``on``, or is dead with a last known-good
  ``on`` or no known-good reading), no room rising edge has occurred and no
  entry term arrived, continuously for ``empty_reset_s``, the anchor sets
  ``L = R``, clears every arrival credit, and ``guest_vis`` is 0 at the next
  ``census_tick``. The predicate reads no house state, census output,
  resident set or ledger value. Late terms (crossing E before the last
  anchor) are recorded, not applied.
* INV-P2-ONCE. Every person is counted in ``L`` at most once per arrival
  and removed at most once per departure: the resident floor lifts ``L``
  only when ``R`` rises, and opens an arrival credit that the matching
  entry term consumes; an exit term of ``n`` cancels at most ``n``
  departure reconciles. No identity attach is read.
* INV-P2-IDENTITY. Nothing here names a person or changes any identity
  value; ``person`` on a reconcile is the residency record's id, read only.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

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
KIND_LIFT = "lift"

# Vision outcome that carries a usable count (crossing_vision.OUTCOME_OK).
_OUTCOME_OK = "ok"

# Tier-1 input readings (HA binary_sensor states).
_ON = "on"
_OFF = "off"


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
    # Entry terms: arrival credit consumed (INV-P2-ONCE). Lifts: the credit
    # opened (k).
    credit_consumed: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def classify_held(
    readings: Mapping[str, tuple[Any, Any]],
    last_good: dict[str, str],
) -> tuple[set[str], set[str]]:
    """The held Tier-1 inputs for one anchor sample (plan P2-D2 step 2).

    ``readings``: entity id -> (state string or None when missing, stream
    dead: the camera input stream health getter's answer, True / False /
    None). ``last_good`` (the wiring's RAM map) is updated in place from
    every good ``on`` / ``off`` reading.

    An input is DEAD when its state is missing, ``unavailable``,
    ``unknown`` or any other non on/off value, or the stream getter reads
    True ("a dead camera is not a presence or absence of signal": its
    frozen reading is not a good reading). A live input is held when it
    reads ``on``. A dead input is held when its last known-good reading was
    ``on`` or it has no known-good reading since setup; a dead input whose
    last good reading was ``off`` is not held. A dead input therefore
    blocks, never enables, the anchor. Returns ``(held, dead_held)``.
    """
    held: set[str] = set()
    dead_held: set[str] = set()
    for eid, (state, stream_dead) in readings.items():
        dead = stream_dead is True or state not in (_ON, _OFF)
        if not dead:
            last_good[eid] = state
            if state == _ON:
                held.add(eid)
            continue
        if last_good.get(eid, _ON) == _ON:
            held.add(eid)
            dead_held.add(eid)
    return held, dead_held


def term_count(
    outcome: str | None,
    people_count: Any,
    camera_peak_count: Any,
    fallback: str,
) -> tuple[int | None, str | None]:
    """``n`` and ``term_source`` for one crossing outcome (plan P2-D2 3).

    Vision ``people_count`` when the outcome is ``ok`` (source ``vision``);
    otherwise, under the ``camera`` policy, ``max(1, camera_peak_count)``
    with None as 1 (source ``camera``; ``blank`` falls back too; a resolved
    direction is at least one person, review A-MED-1). Under the ``skip``
    policy a non-vision outcome yields no term (None, None).
    """
    vision = _count(people_count)
    if outcome == _OUTCOME_OK and vision is not None:
        return vision, SOURCE_VISION
    if fallback == FALLBACK_SKIP:
        return None, None
    peak = _count(camera_peak_count)
    return max(1, peak if peak is not None else 1), SOURCE_CAMERA


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
        arrival_before_s: float,
        arrival_after_s: float,
        stuck_s: float,
        anchor_zero_s: float,
        setup_ts: float,
        anchor_needs_no_hold: bool = True,
    ) -> None:
        self.empty_reset_s = max(0.0, float(empty_reset_s))
        self.eval_s = max(0.0, float(eval_s))
        self.reconcile_lead_s = max(0.0, float(reconcile_lead_s))
        self.reconcile_lag_s = max(0.0, float(reconcile_lag_s))
        self.reconcile_delay_s = max(0.0, float(reconcile_delay_s))
        self.arrival_before_s = max(0.0, float(arrival_before_s))
        self.arrival_after_s = max(0.0, float(arrival_after_s))
        self.stuck_s = max(0.0, float(stuck_s))
        self.anchor_zero_s = max(0.0, float(anchor_zero_s))
        self.setup_ts = float(setup_ts)
        # Kill switch for the held-input conjunct (P2-D2 step 2): False =
        # the edge-only predicate.
        self.anchor_needs_no_hold = bool(anchor_needs_no_hold)

        self.state = STATE_UNKNOWN
        self.unknown_reason: str | None = "boot"
        self.L: int | None = None
        self.L_raw: int | None = None
        self.last_anchor_ts: float | None = None
        self.residue_last: int | None = None

        # census_tick inputs (stored, never re-derived).
        self._R: int | None = None
        # The resident term at the previous census tick (P2-D2 step 4).
        self._R_prev: int | None = None
        self._bodies: int | None = None
        self._bodies_ts: float | None = None
        self._dark = False

        # Arrival credits [t, k_left] (P2-D2 step 4), oldest first.
        self._credits: list[list[float]] = []
        # Events produced inside census_tick (lifts) for the wiring's row
        # write; drained by ``drain_events``.
        self._events: list[LedgerEvent] = []

        # Anchor window.
        self._t_start: float | None = None
        self._edge_since_sample = False
        self._entry_since_sample = False
        self._changed_since_anchor = True
        # Last held set seen by ``evaluate`` (diagnostic).
        self._held_last: tuple[str, ...] = ()

        # Departure reconcile: person -> t_e (superseded per person); applied
        # exits only, as [E, n_left] (review A-MED-4 / D-L1).
        self._pending: dict[str, float] = {}
        self._exits: deque[list[float]] = deque(maxlen=512)

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

    def census_tick_seen(self) -> bool:
        """True once any ``census_tick`` has arrived (enhanced census on)."""
        return self._bodies_ts is not None

    def held_last(self) -> tuple[str, ...]:
        return self._held_last

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
            "open_credits": [[t, int(k)] for t, k in self._credits],
            "held": list(self._held_last[:5]),
            "anchor_zero_suppressed": (
                None if self.census_tick_seen() else "no_census_tick"
            ),
        }

    def reset_daily_counters(self) -> None:
        self.terms_today = {SOURCE_VISION: 0, SOURCE_CAMERA: 0}
        self.reconciled_today = 0

    def drain_events(self) -> list[LedgerEvent]:
        events, self._events = self._events, []
        return events

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
        self._credits.clear()
        self._exits.clear()
        self._stuck_since = None
        self._changed_since_anchor = True

    def rebase(self, now: float) -> None:
        """The producer was (re-)enabled at ``now``: the anchor-zero clock
        restarts there (a long switch-off is not an anchor drought)."""
        self.setup_ts = float(now)
        self._anchor_zero_latched = False

    def _prune_credits(self, now: float) -> None:
        """A credit opened at t expires at t + AFTER + reconcile_delay_s; its
        lift stays in L (a resident through an uncounted door)."""
        horizon = self.arrival_after_s + self.reconcile_delay_s
        self._credits = [c for c in self._credits
                         if c[1] >= 1 and float(now) <= c[0] + horizon]

    def census_tick(
        self,
        now: float,
        resident_term: Any,
        camera_bodies: Any,
        camera_input_dark: Any,
    ) -> tuple[int | None, bool]:
        """Store the census inputs; apply the arrival floor; return
        ``(guest_vis | None, healthy)``. ``healthy`` is False while the
        fleet is dark or the body total is None.

        Floor (P2-D2 step 4, INV-P2-ONCE): while known, if ``R`` rose since
        the previous tick and ``L < R``, lift ``k = R - L`` and open an
        arrival credit ``(now, k)`` for the matching entry term to consume.
        Flat or falling ``R`` never lifts; the floor never lowers ``L``."""
        now = float(now)
        r = _count(resident_term)
        self._R = r
        self._bodies = _count(camera_bodies)
        self._bodies_ts = now
        self._dark = bool(camera_input_dark)
        self._prune_credits(now)
        if r is not None:
            if (
                self.state == STATE_KNOWN
                and self.L is not None
                and self.L_raw is not None
                and self._R_prev is not None
                and r > self._R_prev
                and self.L < r
            ):
                k = r - self.L
                before = self.L
                self.L += k
                self.L_raw += k
                self._credits.append([now, k])
                self._changed_since_anchor = True
                self._events.append(LedgerEvent(
                    kind=KIND_LIFT, at=now, applied=True, n=k,
                    l_before=before, l_after=self.L, l_raw_after=self.L_raw,
                    credit_consumed=None,
                ))
            self._R_prev = r
        return self.guest_vis(), self.healthy()

    def note_rising_edge(self, now: float) -> None:
        """A Tier-1 room sensor rising edge (catches a pulse shorter than
        the eval interval; levels are passed to ``evaluate`` as ``held``)."""
        del now
        self._edge_since_sample = True

    def _consume_credits(self, e_ts: float, n: int) -> int:
        """Consume up to ``n`` from open credits whose window
        [t - BEFORE, t + AFTER] contains ``e_ts``, oldest first."""
        left = n
        for c in self._credits:
            if left <= 0:
                break
            if c[1] < 1:
                continue
            if c[0] - self.arrival_before_s <= e_ts <= c[0] + self.arrival_after_s:
                take = min(left, int(c[1]))
                c[1] -= take
                left -= take
        self._credits = [c for c in self._credits if c[1] >= 1]
        return n - left

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
        """One crossing term. Entry: consume matching arrival credit ``m``
        then ``L += n - m``; exit ``L = max(0, L - n)`` (``L_raw``
        unclamped) and the exit is stored for the departure reconcile.
        While unknown, or for a late term (E before the last anchor), the
        term is recorded with ``applied`` False and an exit is NOT stored.
        Every entry term (applied, late or while unknown) fails the anchor
        window (review A-MED-2)."""
        if direction not in (DIRECTION_ENTRY, DIRECTION_EXIT) or n is None:
            return None
        e_ts = float(e_ts)
        now = float(now)
        n = int(n)
        if direction == DIRECTION_ENTRY:
            self._entry_since_sample = True
        base = dict(kind=KIND_TERM, at=now, direction=direction, n=n,
                    term_source=term_source, crossing_key=crossing_key, e_ts=e_ts)
        if self.state != STATE_KNOWN or self.L is None or self.L_raw is None:
            return LedgerEvent(applied=False, reason="unknown", **base)
        if self.last_anchor_ts is not None and e_ts < self.last_anchor_ts:
            return LedgerEvent(applied=False, reason="late", l_before=self.L,
                               l_after=self.L, l_raw_after=self.L_raw, **base)
        before = self.L
        consumed = None
        if direction == DIRECTION_ENTRY:
            self._prune_credits(now)
            consumed = self._consume_credits(e_ts, n)
            self.L += n - consumed
            self.L_raw += n - consumed
        else:
            self.L_raw -= n
            self.L = max(0, self.L - n)
            self._exits.append([e_ts, n])
        if term_source in self.terms_today:
            self.terms_today[term_source] += 1
        self._changed_since_anchor = True
        return LedgerEvent(applied=True, l_before=before, l_after=self.L,
                           l_raw_after=self.L_raw, credit_consumed=consumed,
                           **base)

    # ----------------------------------------------------------- the anchor
    def _sample_ok(self, now: float, held: bool, *, entry_blocks: bool) -> bool:
        # EVAL_S 0 means a 1 s interval, not "never anchor" (review D-L2).
        fresh = (
            self._bodies_ts is not None
            and float(now) - self._bodies_ts <= 2.0 * max(self.eval_s, 1.0)
        )
        return (
            fresh
            and self._bodies == 0
            and not self._dark
            and not (self.anchor_needs_no_hold and held)
            and not self._edge_since_sample
            and not (entry_blocks and self._entry_since_sample)
        )

    def evaluate(self, now: float, held: Iterable[str]) -> list[LedgerEvent]:
        """One anchor-window sample (the wiring calls this every
        ``eval_s``). ``held`` = the Tier-1 inputs held this sample (see
        ``classify_held``). Returns the anchor event, if one fired."""
        now = float(now)
        self._held_last = tuple(sorted(str(h) for h in held))
        is_held = bool(self._held_last)
        events: list[LedgerEvent] = []
        ok = self._sample_ok(now, is_held, entry_blocks=True)
        # The stuck sample: the anchor predicate minus the entry-term
        # conjunct, held inputs included (a still guest never pages it).
        stuck_ok = self._sample_ok(now, is_held, entry_blocks=False)
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
        self._R_prev = int(self._R)
        self._credits.clear()
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
        """Judge one pending departure: consume one person from the
        earliest applied exit with E in [t_e - lead, t_e + lag] and
        ``n_left >= 1`` (cancel); otherwise ``L = max(0, L - 1)``. One exit
        term of ``n`` cancels at most ``n`` reconciles. Voided (None) when
        the ledger is no longer known or an anchor at or after t_e ran."""
        t_e = self._pending.pop(str(person), None)
        if t_e is None or self.state != STATE_KNOWN or self.L is None:
            return None
        if self.last_anchor_ts is not None and self.last_anchor_ts >= t_e:
            return None
        lo, hi = t_e - self.reconcile_lead_s, t_e + self.reconcile_lag_s
        match = None
        for ex in self._exits:
            if lo <= ex[0] <= hi and ex[1] >= 1 and (match is None or ex[0] < match[0]):
                match = ex
        if match is not None:
            match[1] -= 1
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
        ``stuck_s`` passed the anchor predicate except the entry-term
        conjunct (zero bodies, a lit fleet, no held input, no rising edge;
        so a term stream that blocks the anchor IS paged and a still guest
        on a radar is not). Re-armed when ``guest_vis`` reads 0. ``stuck_s``
        0 = off."""
        if self.stuck_s <= 0 or self._stuck_latched or self._stuck_since is None:
            return False
        if float(now) - self._stuck_since < self.stuck_s:
            return False
        self._stuck_latched = True
        return True

    def anchor_zero_due(self, now: float) -> bool:
        """True ONCE when no anchor ran for ``anchor_zero_s`` (from setup or
        the last anchor). Re-armed by an anchor. 0 = off. Suppressed (no
        latch) while no ``census_tick`` has ever arrived (enhanced census
        off: reviews A-LOW-1 / D-L3; the cause is in the diagnostics)."""
        if self.anchor_zero_s <= 0 or self._anchor_zero_latched:
            return False
        if not self.census_tick_seen():
            return False
        since = max(self.setup_ts, self.last_anchor_ts or self.setup_ts)
        if float(now) - since < self.anchor_zero_s:
            return False
        self._anchor_zero_latched = True
        return True
